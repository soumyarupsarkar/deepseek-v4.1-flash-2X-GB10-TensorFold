"""Require actual matched workloads and keep missing steady intervals explicit."""
import copy
import importlib.util
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location('compare_native', ROOT / 'scripts/compare_native.py')
comparison = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(comparison)


def receipt(image, rate):
    return dict(status='passed', launch=dict(image=image), rows=[dict(
        case=dict(streams=1, prompt_tokens=16, reply_tokens=32, cache='cold', mode='default', rep=rep),
        results=[dict(index=0, prompt_sha256='synthetic', usage=dict(prompt_tokens=16, completion_tokens=32),
                      tensorfold=dict(cached=0, token_sha='hash-' + image))],
        summary=dict(aggregate_e2e_tps=rate, sampled_steady_decode_tps=rate + 1, peak_decoding=1))
        for rep in range(2)])


class NativeComparison(unittest.TestCase):
    def test_workloads_match_without_claiming_cross_engine_token_identity(self):
        result = comparison.compare(receipt('reference', 10), receipt('candidate', 20))
        self.assertEqual(result['matched_requests'], 2)
        self.assertEqual(result['matching_output_hashes'], 0)
        metric = result['rows'][0]['median_comparison']['aggregate_e2e_tps']
        self.assertEqual(metric['candidate_change_percent'], 100)

    def test_missing_steady_repetition_is_not_dropped(self):
        candidate = receipt('candidate', 20)
        candidate['rows'][1]['summary']['sampled_steady_decode_tps'] = None
        result = comparison.compare(receipt('reference', 10), candidate)
        metric = result['rows'][0]['median_comparison']['sampled_steady_decode_tps']
        self.assertIsNone(metric['candidate'])
        self.assertIsNone(metric['candidate_change_percent'])

    def test_mislabeled_or_single_repetitions_cannot_be_reported_as_medians(self):
        for mutation in ('single', 'repeat_alias', 'missing', 'boolean'):
            reference, candidate = receipt('reference', 10), receipt('candidate', 20)
            for value in (reference, candidate):
                if mutation == 'single':
                    value['rows'].pop()
                else:
                    for row in value['rows']:
                        rep = row['case'].pop('rep')
                        if mutation == 'repeat_alias':
                            row['case']['repeat'] = rep
                        elif mutation == 'boolean':
                            row['case']['rep'] = bool(rep)
            with self.subTest(mutation=mutation), self.assertRaises(ValueError):
                comparison.compare(reference, candidate)

    def test_mismatched_inputs_budgets_or_cache_cannot_be_compared(self):
        for mutation in ('prompt', 'output', 'cache', 'missing', 'duplicate', 'failed'):
            candidate = receipt('candidate', 20)
            result = candidate['rows'][0]['results'][0]
            if mutation == 'prompt':
                result['prompt_sha256'] = 'different'
            elif mutation == 'output':
                result['usage']['completion_tokens'] -= 1
            elif mutation == 'cache':
                result['tensorfold']['cached'] = 1
            elif mutation == 'missing':
                candidate['rows'].pop()
            elif mutation == 'duplicate':
                candidate['rows'].append(copy.deepcopy(candidate['rows'][0]))
            else:
                candidate['status'] = 'failed'
            with self.subTest(mutation=mutation), self.assertRaises(ValueError):
                comparison.compare(receipt('reference', 10), candidate)


if __name__ == '__main__':
    unittest.main()
