"""Native-heap pressure behavior and numeric-only cross-container evidence."""
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
MODULE = ROOT/'src/tensorfold/families/deepseek_v41/cuda/host_memory.py'
spec = importlib.util.spec_from_file_location('host_memory', MODULE)
heap = importlib.util.module_from_spec(spec)
spec.loader.exec_module(heap)
sys.path.insert(0, str(ROOT/'deployment/scripts'))
import memory_probe


class FakeHeap:
    def __init__(self):
        self.calls = 0

    def snapshot(self):
        return {'glibc_' + key: 100 for key in heap.HEAP_FIELDS}

    def trim(self):
        self.calls += 1
        return 1


def memory(available):
    return dict(MemAvailable=available, RssAnon=1000, VmRSS=2000, VmSwap=3000)


class HostHeapTests(unittest.TestCase):
    def test_pressure_trim_keeps_before_after_and_constant_size_evidence(self):
        with tempfile.TemporaryDirectory() as root:
            path = Path(root)/'heap.json'
            native = FakeHeap()
            reads = iter([memory(1), memory(5), memory(6)])
            monitor = heap.HostMemoryMonitor(3, heap=native, memory=lambda: next(reads), report=path)
            monitor.tick()
            monitor.tick()
            result = memory_probe.host_heap(path)
            self.assertEqual(native.calls, 1)
            self.assertEqual(result['trim_releases'], 1)
            self.assertEqual(result['last_trim_before']['MemAvailable'], 1)
            self.assertEqual(result['last_trim_after']['MemAvailable'], 5)
            self.assertEqual(result['current']['MemAvailable'], 6)
            self.assertEqual(result['errors'], 0)
            self.assertEqual(path.stat().st_mode & 0o777, 0o600)
            self.assertEqual(list(Path(root).iterdir()), [path])

    def test_zero_threshold_observes_without_trimming(self):
        with tempfile.TemporaryDirectory() as root:
            native = FakeHeap()
            monitor = heap.HostMemoryMonitor(0, heap=native, memory=lambda: memory(1),
                                             report=Path(root)/'heap.json')
            for _ in range(100):
                monitor.tick()
            self.assertEqual(native.calls, 0)
            self.assertEqual(monitor.state['samples'], 100)
            self.assertLess(monitor.report.stat().st_size, 2048)

    def test_sampling_and_writing_failures_are_counted_without_exception_text(self):
        with tempfile.TemporaryDirectory() as root:
            def failed():
                raise RuntimeError('PRIVATE INPUT')
            monitor = heap.HostMemoryMonitor(1, heap=FakeHeap(), memory=failed, report=Path(root)/'heap')
            monitor.tick()
            self.assertEqual(json.loads(monitor.report.read_text())['errors'], 1)
            self.assertNotIn('PRIVATE', monitor.report.read_text())
            monitor.report = Path(root)
            monitor.tick()
            self.assertEqual(monitor.state['write_errors'], 1)
            self.assertEqual(len(list(Path(root).iterdir())), 1)

    def test_atomic_write_does_not_follow_destination_symlinks(self):
        with tempfile.TemporaryDirectory() as root:
            other = Path(root)/'private'; other.write_text('PRIVATE')
            report = Path(root)/'report'; report.symlink_to(other)
            heap._write(report, {'schema': 1})
            self.assertEqual(other.read_text(), 'PRIVATE')
            self.assertFalse(report.is_symlink())

    def test_probe_rejects_non_numeric_unknown_large_redirected_and_special_files(self):
        with tempfile.TemporaryDirectory() as root:
            path = Path(root)/'report'
            for value in ({'schema': 1, 'sample_unix_ns': 1, 'prompt': 'PRIVATE'},
                          {'schema': 1, 'sample_unix_ns': 1, 'pid': 'PRIVATE'},
                          {'schema': 1, 'sample_unix_ns': 1, 'errors': float('nan')},
                          {'schema': 1, 'sample_unix_ns': 1, 'current': {'prompt': 1}},
                          {'schema': 1, 'sample_unix_ns': True}):
                path.write_text(json.dumps(value))
                with self.assertRaises(ValueError):
                    memory_probe.host_heap(path)
            path.write_bytes(b' ' * 8193)
            with self.assertRaises(ValueError):
                memory_probe.host_heap(path)
            path.unlink(); path.symlink_to(Path(root)/'missing')
            with self.assertRaises(OSError):
                memory_probe.host_heap(path)
            path.unlink(); os.mkfifo(path)
            with self.assertRaises(ValueError):
                memory_probe.host_heap(path)

    def test_monitor_disabled_by_default_and_configuration_is_validated(self):
        with patch.dict(os.environ, {}, clear=True), patch.object(heap, 'HostMemoryMonitor') as cls:
            self.assertIsNone(heap.start())
            cls.assert_not_called()
            for value in ('nan', 'inf', '-1', '129', 'invalid'):
                os.environ['TF_DS_HOST_TRIM_GIB'] = value
                with self.assertRaises(ValueError):
                    heap.start()

    def test_stats_only_and_trim_share_one_daemon(self):
        with patch.dict(os.environ, {'TF_DS_HOST_MEMORY_STATS': '1'}, clear=True), \
                patch.object(heap, '_monitor', None), patch.object(heap, 'HostMemoryMonitor') as cls:
            cls.return_value.start.return_value.state = {'pid': os.getpid()}
            first = heap.start()
            self.assertIs(heap.start(), first)
            cls.assert_called_once_with(0)

    @unittest.skipUnless(sys.platform == 'linux', 'glibc/Linux ABI smoke check')
    def test_real_libc_trim_preserves_a_live_allocation(self):
        code = '''import ctypes,importlib.util,json,sys
spec=importlib.util.spec_from_file_location('host_memory',sys.argv[1])
m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)
h=m.LibcHeap();lib=h.libc
lib.malloc.argtypes=[ctypes.c_size_t];lib.malloc.restype=ctypes.c_void_p
lib.free.argtypes=[ctypes.c_void_p];lib.free.restype=None
size=16*1024*1024
p=lib.malloc(size);assert p
try:
 ctypes.memset(p,91,size)
 result=h.trim();after=h.snapshot()
 assert ctypes.string_at(p,64)==bytes([91])*64
 assert ctypes.string_at(p+size-64,64)==bytes([91])*64
 assert result in (0,1) and all(type(n)==int and n>=0 for n in after.values())
 print(json.dumps({'passed':True,'fields':len(after)}))
finally:lib.free(p)
'''
        result = subprocess.run([sys.executable, '-B', '-c', code, str(MODULE)],
                                capture_output=True, text=True, timeout=15, check=True)
        self.assertEqual(json.loads(result.stdout), {'passed': True, 'fields': 10})


if __name__ == '__main__':
    unittest.main()
