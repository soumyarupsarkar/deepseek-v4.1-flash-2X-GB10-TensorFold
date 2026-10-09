"""Pure planning checks for the observed warm C32 fragmentation regression."""
import importlib.util
from pathlib import Path
import random
import unittest

ROOT = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location('kv_compaction',ROOT/'src/tensorfold/families/deepseek_v41/cuda/compaction.py')
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)
plan = MODULE.plan


class CompactionPlanTests(unittest.TestCase):
    def test_observed_31_stream_geometry_can_fit_the_thirty_second(self):
        active, cursor = [], 0
        for i in range(31):
            if i in (10,20):
                cursor += 184320
            active.append((i,cursor,264192))
            cursor += 264192
        result = plan(8716288,2048,active,[],261120+1024+32+12)
        self.assertEqual(result['free_rows'],526336)
        self.assertGreaterEqual(result['free_rows'],264192)
        self.assertEqual(result['used_rows'],31*264192)
        self.assertEqual(len(result['moves']),21)
        self.assertEqual(result['dropped'],[])
        self.assertTrue(all(m['destination'] < m['source'] for m in result['moves']))

    def test_no_prefix_is_evicted_when_packing_alone_suffices(self):
        result = plan(64,4,[(0,8,12)],[(0,32,8,9),(1,48,8,1)],32)
        self.assertEqual(result['dropped'],[])
        self.assertEqual((result['used_rows'],result['free_rows']),(28,36))

    def test_pressure_evicts_only_the_oldest_prefixes_needed(self):
        result = plan(64,4,[(9,8,32)],[(0,40,8,100),(1,48,8,2),(2,56,8,1)],20)
        self.assertEqual(result['dropped'],[2,1])
        self.assertEqual(result['free_rows'],24)
        self.assertTrue(any(m['kind']=='retained' and m['id']==0 for m in result['moves']))

    def test_equal_ticks_use_id_order_and_input_order_does_not_change_plan(self):
        active=[(0,0,32)]
        kept=[(4,32,8,1),(2,48,8,1),(9,56,8,1)]
        a=plan(64,4,active,kept,20)
        self.assertEqual(a,plan(64,4,active,list(reversed(kept)),20))
        self.assertEqual(a['dropped'],[2,4])

    def test_live_reservations_are_never_shrunk_to_make_a_request_fit(self):
        self.assertIsNone(plan(64,4,[(0,8,56)],[(0,0,4,1)],12))

    def test_invalid_layouts_are_rejected(self):
        for active,kept in [([(0,0,16),(1,8,16)],[]), ([(0,0,16)],[(0,12,8,1)]),
                            ([(0,2,16)],[]), ([(0,60,8)],[]), ([(0,0,4),(0,8,4)],[])]:
            with self.subTest(active=active,kept=kept),self.assertRaises(ValueError):
                plan(64,4,active,kept,4)

    def test_varied_layouts_preserve_all_live_reservations(self):
        rng=random.Random(739)
        for _ in range(200):
            active,kept,cursor=[],[],0
            for ident in range(rng.randint(1,20)):
                cursor += rng.randint(0,4)*4
                size=rng.randint(1,10)*4
                if rng.randrange(2):active.append((ident,cursor,size))
                else:kept.append((ident,cursor,size,rng.randrange(20)))
                cursor += size
            total=cursor+rng.randint(0,8)*4
            need=rng.randint(1,60)*4
            result=plan(total,4,active,kept,need)
            if sum(x[2] for x in active)+need > total:
                self.assertIsNone(result)
                continue
            self.assertIsNotNone(result)
            self.assertGreaterEqual(result['free_rows'],need)
            self.assertEqual(result['used_rows']+result['free_rows'],total)
            survivors=sum(x[2] for x in active)+sum(x[2] for x in kept if x[0] not in result['dropped'])
            self.assertEqual(result['used_rows'],survivors)
            original={(kind,x[0]):x for kind,items in (('active',active),('retained',kept)) for x in items}
            for move in result['moves']:
                old=original[(move['kind'],move['id'])]
                self.assertEqual((move['source'],move['size']),old[1:3])
                self.assertLess(move['destination'],move['source'])
                self.assertEqual(move['destination']%4,0)


if __name__ == '__main__':
    unittest.main()
