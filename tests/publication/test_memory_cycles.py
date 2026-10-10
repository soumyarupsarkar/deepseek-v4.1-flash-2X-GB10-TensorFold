"""A quiet comparison needs matching resident work and complete host evidence."""
import copy
import importlib.util
from pathlib import Path
import unittest

path = Path(__file__).resolve().parents[2]/'tools/qualification/qualify_memory_cycles.py'
spec = importlib.util.spec_from_file_location('memory_cycles', path)
client = importlib.util.module_from_spec(spec)
spec.loader.exec_module(client)


class MatchedCyclesTests(unittest.TestCase):
    def windows(self):
        host = dict(glibc_live_bytes=1000, rank_anon_plus_swap_bytes=2000, available_bytes=4000)
        return [dict(signature=dict(prefixes=32), samples=[dict(hosts=dict(head=copy.copy(host),
                     worker=copy.copy(host))) for _ in range(6)]) for _ in range(3)]

    def test_matching_windows_and_bounded_growth(self):
        windows = self.windows()
        for s in windows[-1]['samples']:
            s['hosts']['worker']['glibc_live_bytes'] += 20
        result = client.compare(windows, 30)
        self.assertTrue(result['within_budget'])
        self.assertEqual(result['maximum_growth_bytes']['worker']['glibc_live_bytes'], 20)
        self.assertFalse(client.compare(windows, 19)['within_budget'])

    def test_different_occupancy_cannot_be_called_a_memory_trend(self):
        windows = self.windows()
        windows[-1]['signature']['prefixes'] = 31
        with self.assertRaisesRegex(AssertionError, 'states differ'):
            client.compare(windows, 1000)

    def test_missing_or_too_few_host_observations_cannot_pass(self):
        windows = self.windows()
        del windows[-1]['samples'][0]['hosts']['worker']
        with self.assertRaises(KeyError):
            client.compare(windows, 1000)
        windows = self.windows()
        windows[-1]['samples'].pop()
        with self.assertRaisesRegex(AssertionError, 'Insufficient'):
            client.compare(windows, 1000)


if __name__ == '__main__':
    unittest.main()
