"""Admission geometry must displace every old retained extent, not just its LRU count."""
import importlib.util
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location('compaction_fixture', ROOT / 'tools/qualification/compaction_fixture.py')
fixture = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(fixture)


class CompactionReservationGeometry(unittest.TestCase):
    def profile(self, **changes):
        return dict(dict(pool_tokens=8650752, parallel=32, context=1048576,
            environment={'TF_DS_ROUND_ROWS': '48'}), **changes)

    def test_live_reservations_cover_pool_without_rounding_past_its_end(self):
        plan = fixture.reservation_plan(self.profile())
        # The engine adds 48 verification rows and two boundary tokens before
        # rounding up to 2048. Omitting that padding over-reserves every slot.
        self.assertEqual(plan['request_budget'], 270286)
        self.assertEqual(plan['reservation_tokens'], 270336)
        self.assertEqual(plan['reservation_tokens'] * plan['streams'], 8650752)
        self.assertEqual(plan['reservation_tokens'] % 2048, 0)

    def test_a_tail_gap_or_nonuniform_slot_count_cannot_prove_eviction(self):
        for changed in ({'pool_tokens': 8650751}, {'pool_tokens': 8650752 + 2048}, {'parallel': 31}):
            with self.subTest(changed=changed), self.assertRaises(ValueError):
                fixture.reservation_plan(self.profile(**changed))

    def test_context_or_slot_limits_cannot_make_conditioning_silently_partial(self):
        for changed in ({'context': 262144}, {'parallel': 0}, {'parallel': 64}, {'parallel': True}):
            with self.subTest(changed=changed), self.assertRaises(ValueError):
                fixture.reservation_plan(self.profile(**changed))

    def test_round_budget_change_keeps_the_same_complete_pool_coverage(self):
        plan = fixture.reservation_plan(self.profile(environment={'TF_DS_ROUND_ROWS': '96'}))
        self.assertEqual(plan['request_budget'], 270238)
        self.assertEqual(plan['reservation_tokens'], 270336)
        self.assertEqual(plan['reservation_tokens'] * plan['streams'], 8650752)


if __name__ == '__main__':
    unittest.main()
