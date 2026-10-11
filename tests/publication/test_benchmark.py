"""Protect timing semantics and portable receipts without issuing HTTP requests."""
import contextlib
import io
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

SOURCE = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(SOURCE / 'deployment/scripts'))
import benchmark


class BenchmarkTests(unittest.TestCase):
    def test_graph_replacements_count_as_captures_at_constant_residency(self):
        before = dict(native=dict(round_graphs=144, graph_captures=200))
        after = dict(native=dict(round_graphs=144, graph_captures=209))
        self.assertEqual(benchmark.native_graph_capture_delta(before, after), 9)
        after['native']['round_graphs'] = 143
        self.assertEqual(benchmark.native_graph_capture_delta(before, after), 9)
        after['native']['graph_captures'] = 100
        with self.assertRaises(AssertionError):
            benchmark.native_graph_capture_delta(before, after)
        legacy = dict(native=dict(round_graphs=140))
        self.assertEqual(benchmark.native_graph_capture_delta(legacy, dict(native=dict(round_graphs=144))), 4)
        with self.assertRaises(AssertionError):
            benchmark.native_graph_capture_delta(legacy, before)

    def test_completed_sse_can_drain_without_changing_scored_results(self):
        busy = dict(ok=True, requests_running=1, native=dict(active_streams=0))
        idle = dict(ok=True, requests_running=0, native=dict(active_streams=0))
        with patch.object(benchmark, 'json_request', side_effect=[busy, idle]), \
             patch.object(benchmark.time, 'perf_counter', side_effect=[0, .01, .03]), \
             patch.object(benchmark.time, 'sleep'):
            health, drain = benchmark.wait_idle('http://fixture', timeout=.5)
        self.assertEqual(health, idle)
        self.assertEqual(drain['seconds'], .03)
        self.assertEqual([s['health']['requests_running'] for s in drain['samples']], [1, 0])
        # Timing remains computed from stream endpoints, never drain duration.
        self.assertEqual(benchmark.summarize(self.results(), [], 2)['aggregate_e2e_tps'], 20)

    def test_post_response_drain_refuses_faults_and_has_a_deadline(self):
        for health, error in ((dict(ok=False, requests_running=0), RuntimeError),
                              (dict(ok=True, requests_running=1), TimeoutError)):
            with self.subTest(health=health), \
                 patch.object(benchmark, 'json_request', return_value=health), \
                 patch.object(benchmark.time, 'perf_counter', side_effect=[0, 1]), \
                 self.assertRaises(error) as caught:
                benchmark.wait_idle('http://fixture', timeout=.5)
            self.assertEqual(caught.exception.drain['samples'][0]['health']['ok'], health['ok'])

    def native_health(self):
        return dict(status='ok', runtime_poisoned=False,
                    native=dict(rdma_failed=False, active_streams=4, prefilling_streams=1),
                    scheduler=dict(running=4, waiting=2, generation_tokens_total=1700),
                    completed=dict(requests=9, generation_tokens=500))

    def test_native_steady_counter_includes_live_committed_tokens(self):
        raw = self.native_health()
        result = benchmark.normalize_health(raw)
        self.assertEqual(result['completion_tokens_total'], 1700)
        self.assertEqual(result['requests_running'], 6)
        self.assertEqual(result['streams'], dict(decoding=3, prefilling=1))
        self.assertEqual(result['scheduler']['queued'], 2)
        self.assertNotIn('queued', raw['scheduler'])
        self.assertNotIn('allocation_ooms', result)

    def test_missing_live_counter_is_not_replaced_by_completed_counter(self):
        raw = self.native_health()
        del raw['scheduler']['generation_tokens_total']
        with self.assertRaises(KeyError):
            benchmark.normalize_health(raw)

    def test_native_poison_or_rdma_failure_is_unhealthy(self):
        raw = self.native_health()
        raw['runtime_poisoned'] = True
        self.assertFalse(benchmark.normalize_health(raw)['ok'])
        raw['runtime_poisoned'] = False
        raw['native']['rdma_failed'] = True
        self.assertFalse(benchmark.normalize_health(raw)['ok'])

    def results(self):
        return [dict(start=0, end=10, wall_s=10, decode_tps=12, ttft_s=2,
                     usage=dict(completion_tokens=100, prompt_tokens=1000),
                     tensorfold=dict(cached=0, prefill_s=2)) for _ in range(2)]

    def sample(self, at, tokens, queued=0):
        return dict(at=at, health=dict(streams=dict(decoding=2, prefilling=0),
                    scheduler=dict(queued=queued), completion_tokens_total=tokens))

    def test_steady_interval_and_complete_wave_are_distinct(self):
        result=benchmark.summarize(self.results(),[self.sample(3,20),self.sample(5,140)],2)
        self.assertEqual(result['aggregate_e2e_tps'],20)
        self.assertEqual(result['sampled_steady_decode_tps'],60)
        self.assertEqual(result['sampled_steady_decode_s'],2)
        self.assertIsNone(result['effective_prefill_tps'])

    def test_short_queued_or_missing_health_cannot_be_scored_as_steady(self):
        for samples in ([self.sample(3,20),self.sample(4,80)],
                        [self.sample(3,20,queued=1),self.sample(5,140)],
                        [dict(at=3),self.sample(5,140)]):
            with self.subTest(samples=samples):
                result=benchmark.summarize(self.results(),samples,2)
                self.assertIsNone(result['sampled_steady_decode_tps'])

    def test_receipt_uses_portable_launch_location(self):
        with tempfile.TemporaryDirectory() as temporary:
            root=Path(temporary)
            (root/'launch.json').write_text(json.dumps(dict(image='test-image')))
            case=dict(streams=1,prompt_tokens=0,reply_tokens=1,prompt_class='code')
            suite=root/'suite.json';suite.write_text(json.dumps([case]))
            row=dict(summary=dict(wall_s=1,aggregate_e2e_tps=1,sampled_steady_decode_tps=None,
                                  effective_prefill_tps=1,peak_decoding=1))
            with patch.object(benchmark,'ROOT',root),patch.object(benchmark,'wave',return_value=row), \
                 patch.object(benchmark,'request',side_effect=AssertionError('network')), \
                 patch('sys.argv',['benchmark','--suite',str(suite),'--record','test']), \
                 contextlib.redirect_stdout(io.StringIO()):
                benchmark.main()
            receipt=json.loads((root/'records/benchmark-test.json').read_text())
            self.assertEqual(receipt['launch']['image'],'test-image')
            self.assertEqual(receipt['status'],'passed')


if __name__ == '__main__':unittest.main()
