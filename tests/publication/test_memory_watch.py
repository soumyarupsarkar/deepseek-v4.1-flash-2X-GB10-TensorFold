"""Memory evidence and shutdown contracts, using synthetic /proc and rank state."""
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT/'deployment/scripts'))
import configuration
import memory_probe
import memory_watch
import runtime


class ProbeTests(unittest.TestCase):
    def test_probe_source_is_stdin_not_a_logged_command_argument(self):
        pair = runtime.Pair(configuration.read(configuration.CONFIG/'cluster.example.json'))
        with patch.object(pair, 'run', return_value=subprocess.CompletedProcess([], 0, '{"ok":true}')) as run:
            self.assertEqual(memory_watch.host_sample(pair, 'worker', 42, floor_bytes=2*2**30), {'ok': True})
        args, kwargs = run.call_args
        self.assertEqual(args[0], 'worker')
        self.assertEqual(args[1][:5], ['sudo', '-n', 'python3', '-B', '-'])
        self.assertNotIn(memory_watch.HOST_PROBE, args[1])
        self.assertEqual(kwargs['input'], memory_watch.HOST_PROBE)
        self.assertEqual(kwargs['timeout'], 20)

    def test_rank_descendants_and_private_mappings_without_request_or_argv_reads(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            (root/'meminfo').write_text('MemAvailable: 1048576 kB\nMemTotal: 4194304 kB\n')
            (root/'vmstat').write_text('oom_kill 0\npswpout 42\n')
            (root/'pressure').mkdir()
            (root/'pressure/memory').write_text('some avg10=0.01 avg60=0.02 avg300=0.03 total=50\n')
            for pid, parent, rss in ((10, 1, 10), (11, 10, 200), (12, 11, 30), (13, 1, 400)):
                p = root/str(pid); p.mkdir()
                (p/'status').write_text(f'Name:\tprocess\nPPid:\t{parent}\nUid:\t1000 1000 1000 1000\n'
                                        f'Threads:\t1\nVmRSS:\t{rss} kB\nRssAnon:\t{rss} kB\n')
                (p/'stat').write_text(f'{pid} (process with spaces) S '+'0 '*18+'99 0\n')
                (p/'smaps_rollup').write_text(f'Pss: {rss-1} kB\nRss: {rss} kB\n')
                (p/'cmdline').write_text('PRIVATE PROMPT')
                (p/'environ').write_text('PRIVATE TOKEN')
            (root/'10/cgroup').write_text('0::/test\n')
            cg = root/'cg/test'; cg.mkdir(parents=True)
            (cg/'memory.current').write_text('12345')
            (cg/'memory.events').write_text('oom 0\noom_kill 0\n')
            (cg/'memory.stat').write_text('anon 123\nfile 456\n')
            observed = []
            read = Path.read_text
            def checked(path, *args, **kwargs):
                self.assertNotIn(path.name, ('cmdline', 'environ'))
                observed.append(path)
                return read(path, *args, **kwargs)
            with patch.object(Path, 'read_text', checked):
                sample = memory_probe.collect(10, proc=root, cgroups=root/'cg')
            self.assertEqual(sample['meminfo']['MemAvailable'], 2**30)
            self.assertEqual({p['pid'] for p in sample['rank_processes']}, {10, 11, 12})
            self.assertEqual(sample['rank_rss_sum_bytes'], 240*1024)
            self.assertEqual(sample['cgroup']['memory.current'], 12345)
            self.assertTrue(sample['process_details'])
            self.assertTrue(all(p['start_ticks'] == 99 for p in sample['rank_processes']))
            self.assertNotIn('PRIVATE', json.dumps(sample))

    def test_absent_memavailable_cannot_be_reported_as_healthy(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp); (root/'meminfo').write_text('MemFree: 100 kB\n')
            with self.assertRaisesRegex(ValueError, 'MemAvailable absent'):
                memory_probe.collect(proc=root)


class HistoryTests(unittest.TestCase):
    def test_rotation_is_bounded_and_records_are_private(self):
        with tempfile.TemporaryDirectory() as temp:
            h = memory_watch.History(Path(temp)/'memory', max_bytes=1024, backups=2)
            for i in range(100):
                h.append(dict(index=i, value='x'*100))
            files = list(h.root.glob('samples*.jsonl'))
            self.assertEqual(len(files), 3)
            self.assertLessEqual(sum(p.stat().st_size for p in files), 3072)
            self.assertTrue(all(p.stat().st_mode & 0o777 == 0o600 for p in files))
            self.assertEqual(len(h.recent), 12)
            self.assertEqual(json.loads((h.root/'samples.jsonl').read_text().splitlines()[-1])['index'], 99)

    def test_symlink_does_not_overwrite_an_unrelated_file(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            other = root/'keep'; other.write_text('keep')
            directory = root/'memory'; directory.mkdir()
            (directory/'samples.jsonl').symlink_to(other)
            with self.assertRaisesRegex(ValueError, 'redirected'):
                memory_watch.History(directory).append({'sample': 1})
            self.assertEqual(other.read_text(), 'keep')

    def test_health_evidence_omits_text_tokens_and_large_nested_extensions(self):
        selected = memory_watch.health_sample(dict(ok=True, prompt='PRIVATE', response='PRIVATE',
            memory=dict(allocated_bytes=123, token_ids=[1, 2], draft_calibration={'body': 'PRIVATE'},
                        kv_pool=dict(active_requests=2, request='PRIVATE'))))
        self.assertEqual(selected['memory']['allocated_bytes'], 123)
        self.assertEqual(selected['memory']['kv_pool'], {'active_requests': 2})
        self.assertNotIn('PRIVATE', json.dumps(selected))
        self.assertNotIn('token_ids', selected['memory'])


class WatchConnectionTests(unittest.TestCase):
    def setUp(self):
        self.pair = runtime.Pair(configuration.read(configuration.CONFIG/'cluster.example.json'))

    def test_one_private_socket_scoped_to_watch_and_closed_on_error(self):
        calls = []
        def run(args, **kwargs):
            calls.append(args)
            if args[0] == 'ssh' and '-O' not in args:
                self.pair._worker_control.touch()  # emulate the master's socket
            return subprocess.CompletedProcess(args, 0, '')
        with patch('runtime.subprocess.run', side_effect=run):
            with self.assertRaisesRegex(RuntimeError, 'rank failed'):
                with self.pair.watch_connection():
                    path = self.pair._worker_control
                    self.assertEqual(path.parent.stat().st_mode & 0o777, 0o700)
                    self.assertLess(len(str(path)), 100)
                    self.pair.run('worker', ['true'])
                    self.pair.run('head', ['true'])
                    self.pair.run('worker', ['true'])
                    raise RuntimeError('rank failed')
        worker = [args for args in calls if args[0] == 'ssh' and '-O' not in args]
        self.assertEqual(len(worker), 2)
        self.assertTrue(all('ControlPath='+str(path) in args for args in worker))
        self.assertTrue(all('ControlPersist=30' in args for args in worker))
        self.assertTrue(all('StrictHostKeyChecking=yes' in args and 'BatchMode=yes' in args for args in worker))
        self.assertIn(['true'], calls)  # head commands are unaffected
        self.assertIn('-O', calls[-1]); self.assertIn('exit', calls[-1])
        self.assertIsNone(self.pair._worker_control)
        self.assertFalse(path.parent.exists())
        with patch('runtime.subprocess.run', return_value=subprocess.CompletedProcess([], 0, '')) as run:
            self.pair.run('worker', ['true'])
        self.assertFalse(any(arg.startswith('ControlPath=') for arg in run.call_args.args[0]))

    def test_master_cleanup_timeout_does_not_hide_the_original_fault(self):
        with patch('runtime.subprocess.run', side_effect=subprocess.TimeoutExpired('ssh', 5)):
            with self.assertRaisesRegex(RuntimeError, 'original fault'):
                with self.pair.watch_connection():
                    path = self.pair._worker_control
                    path.touch()
                    raise RuntimeError('original fault')
        self.assertIsNone(self.pair._worker_control)
        self.assertFalse(path.parent.exists())

    def test_temp_directory_failure_keeps_the_watchdog_running(self):
        with patch('runtime.tempfile.TemporaryDirectory', side_effect=PermissionError('unavailable')), \
             patch.object(self.pair, '_watch') as watch:
            self.pair.watch()
        watch.assert_called_once()
        self.assertIsNone(getattr(self.pair, '_worker_control', None))


class WatchdogTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        self.state = Path(self.temp.name)
        self.pair = runtime.Pair(configuration.read(configuration.CONFIG/'cluster.example.json'), self.state)
        runtime.atomic(self.state/'launch.json', dict(image='test-image',
            profile={'minimum_available_gib': 2}, containers={'head': 'head-id', 'worker': 'worker-id'}))

    def containers(self, host):
        return [dict(Id=host+'-id', State=dict(Running=True, Pid=42))]

    def sample(self, pair, host, pid, **kwargs):
        return dict(meminfo={'MemAvailable': (4 if host == 'head' else 1.9)*2**30})

    def test_low_worker_memory_saved_before_both_ranks_stop(self):
        def stop():
            fault = configuration.read(self.state/'fault.json')
            self.assertEqual(fault['reason'], 'worker: host memory floor crossed')
            self.assertLess(fault['sample']['hosts']['worker']['meminfo']['MemAvailable'], 2*2**30)
            self.assertEqual(len(fault['recent_samples']), 2)
        with patch.object(self.pair, 'containers', side_effect=self.containers), \
             patch('memory_watch.host_sample', side_effect=self.sample), \
             patch.object(self.pair, 'stop', side_effect=stop) as stopper, \
             patch('runtime.time.sleep'):
            self.pair.watch()
        stopper.assert_called_once()

    def test_disk_full_cannot_prevent_memory_shutdown(self):
        with patch.object(self.pair, 'containers', side_effect=self.containers), \
             patch('memory_watch.host_sample', side_effect=self.sample), \
             patch('memory_watch.History._append', side_effect=OSError('disk full')), \
             patch('runtime.atomic', side_effect=OSError('disk full')), \
             patch.object(self.pair, 'stop') as stopper, patch('runtime.time.sleep'):
            with self.assertRaises(OSError):
                self.pair.watch()
        stopper.assert_called_once()

    def test_single_low_sample_recovers_and_resets_failure_count(self):
        worker = iter([1.9, 4, 1.9, 1.9])
        def sample(pair, host, pid, **kwargs):
            return dict(meminfo={'MemAvailable': (4 if host == 'head' else next(worker))*2**30})
        with patch.object(self.pair, 'containers', side_effect=self.containers), \
             patch('memory_watch.host_sample', side_effect=sample), \
             patch.object(self.pair, 'get', return_value={'ok': True, 'busy': False}), \
             patch.object(self.pair, 'stop') as stopper, patch('runtime.time.sleep'):
            self.pair.watch()
        stopper.assert_called_once()
        fault = configuration.read(self.state/'fault.json')
        self.assertEqual([r['failure_count'] for r in fault['recent_samples']], [1, 0, 1, 2])
        self.assertTrue(fault['last_health']['ok'])

    def test_health_failure_still_saves_host_evidence_and_stops(self):
        with patch.object(self.pair, 'containers', side_effect=self.containers), \
             patch('memory_watch.host_sample', return_value={'meminfo': {'MemAvailable': 4*2**30}}), \
             patch.object(self.pair, 'get', side_effect=TimeoutError('health timeout')), \
             patch.object(self.pair, 'stop') as stopper, patch('runtime.time.sleep'):
            self.pair.watch()
        stopper.assert_called_once()
        fault = configuration.read(self.state/'fault.json')
        self.assertEqual(set(fault['sample']['hosts']), {'head', 'worker'})
        self.assertEqual(fault['reason'], 'health timeout')


if __name__ == '__main__':
    unittest.main()
