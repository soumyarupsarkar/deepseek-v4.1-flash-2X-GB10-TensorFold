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
