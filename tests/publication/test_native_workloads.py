import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'benchmarks'))
import native_workloads as workloads


class WorkloadMetrics(unittest.TestCase):
    def result(self):
        return dict(start_s=0, end_s=10, output_tokens=100, content_decode_tps=12,
                    ttft_s=2, input_tokens=43)

    def sample(self, at, tokens, decoding=32, prefilling=0, waiting=0):
        return dict(at_s=at, health=dict(output_tokens=tokens, decoding=decoding,
                                        prefilling=prefilling, waiting=waiting))

    def test_aggregate_decode_counts_live_tokens_without_summing_request_rates(self):
        results = [self.result() for _ in range(32)]
        samples = [self.sample(2, 100), self.sample(3, 300), self.sample(4, 700)]
        summary = workloads.summarize(results, samples, 32)
        self.assertEqual(summary['aggregate_steady_decode_tps'], 300)
        self.assertEqual(summary['steady_output_tokens'], 600)
        self.assertEqual(summary['aggregate_end_to_end_tps'], 320)
        self.assertIsNone(summary['c1_content_decode_tps'])
        self.assertNotEqual(summary['aggregate_steady_decode_tps'], 32 * 12)

    def test_insufficient_or_partial_occupancy_is_not_a_c32_decode_claim(self):
        for samples in ([self.sample(2, 100), self.sample(3, 300)],
                        [self.sample(2, 100, decoding=31), self.sample(4, 700)],
                        [self.sample(2, 100, prefilling=1), self.sample(4, 700)],
                        [self.sample(2, 100, waiting=1), self.sample(4, 700)],
                        [self.sample(2, 100), self.sample(6, 700)],
                        [self.sample(9, 100), self.sample(11, 700)]):
            with self.subTest(samples=samples):
                summary = workloads.summarize([self.result()] * 32, samples, 32)
                self.assertIsNone(summary['aggregate_steady_decode_tps'])

    def test_c1_keeps_content_span_rate_and_actual_early_stop_length(self):
        result = self.result() | dict(output_tokens=299, content_decode_tps=59.5)
        summary = workloads.summarize([result], [], 1)
        self.assertEqual(summary['c1_content_decode_tps'], 59.5)
        self.assertEqual(summary['reply_tokens'], [299])
        self.assertEqual(summary['aggregate_end_to_end_tps'], 29.9)


if __name__ == '__main__':
    unittest.main()
