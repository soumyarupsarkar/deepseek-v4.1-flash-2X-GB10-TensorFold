"""A failed replay or an unexercised relocation cannot become a passing receipt."""
import contextlib
import importlib.util
import io
import json
from pathlib import Path
import sys
import tempfile
import threading
from types import ModuleType
import unittest
from unittest.mock import patch

SOURCE = Path(__file__).resolve().parents[2]


class MemoryQualificationTests(unittest.TestCase):
    def exercise(self, fault=None):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root/'records').mkdir()
            (root/'records/active.json').write_text('{}')
            calls, lock = {}, threading.Lock()

            def health(*args, **kwargs):
                return dict(ok=True, requests_running=0, streams=dict(decoding=2),
                            memory=dict(kv_compactions=int(bool(calls) and fault != 'no-compaction')))

            def post(body, *args, **kwargs):
                seed = body.get('seed')
                ids = list(range(body['max_tokens']))
                if seed is not None:
                    with lock:
                        calls[seed] = calls.get(seed, 0)+1
                        if fault == 'changed-token' and seed == 9000 and calls[seed] == 2:
                            ids[-1] += 1
                return dict(seconds=0, response=dict(
                    usage=dict(prompt_tokens=len(body['prompt']), completion_tokens=body['max_tokens']),
                    tensorfold=dict(token_ids=None if fault == 'missing-ids' else ids),
                    choices=[dict(finish_reason='length')]))

            def module(name, **values):
                result = ModuleType(name)
                result.__dict__.update(values)
                return result

            stubs = dict(
                common=module('common', ROOT=root, now=lambda:'synthetic-time',
                              atomic=lambda p,v:p.write_text(json.dumps(v))),
                cluster=module('cluster', get=health, memory=lambda h:dict(MemAvailable=4*2**30)),
                qualify=module('qualify', post=post, vision=lambda color:dict(color='red'),
                               text=lambda result:result['color']),
                qualify_pool=module('qualify_pool', prompt_ids=lambda size,ident:list(range(size))))
            spec = importlib.util.spec_from_file_location('qualification_under_test',
                SOURCE/'tools/qualification/qualify_memory.py')
            client = importlib.util.module_from_spec(spec)
            arguments = ['qualify_memory','--record','fixture','--streams','2','--rounds','2',
                '--initial-tokens','8','--growth','0','--reply-tokens','4',
                '--shared-prefix','--identical','--require-replay-parity','--require-compaction']
            raised = None
            with patch.dict(sys.modules,stubs), patch.object(sys,'argv',arguments), contextlib.redirect_stdout(io.StringIO()):
                spec.loader.exec_module(client)
                try:
                    client.main()
                except (AssertionError, RuntimeError) as exc:
                    raised = exc
            result = json.loads((root/'records/validation-fixture.json').read_text())
            for cycle in result['cycles']:
                for row in cycle['results']:
                    self.assertNotIn('token_ids',row['tensorfold'])
            return raised,result

    def test_matching_seeded_replays_with_relocation_pass(self):
        error,result = self.exercise()
        self.assertIsNone(error)
        self.assertEqual(result['status'],'passed')
        self.assertEqual(result['compactions_exercised'],1)
        self.assertTrue(result['cycles'][1]['replay_parity_passed'])
        self.assertTrue(all(len(r['token_ids_sha256'])==64 for r in result['cycles'][1]['results']))

    def test_one_changed_token_fails_and_preserves_both_wave_hashes(self):
        error,result = self.exercise('changed-token')
        self.assertIsInstance(error,AssertionError)
        self.assertEqual(result['status'],'failed')
        self.assertEqual(len(result['cycles']),2)
        self.assertIn('token IDs changed',result['error'])

    def test_missing_token_ids_cannot_claim_exact_replay(self):
        error,result = self.exercise('missing-ids')
        self.assertIsInstance(error,RuntimeError)
        self.assertEqual(result['status'],'failed')
        self.assertIn('Missing complete token IDs',result['error'])

    def test_equal_outputs_without_relocation_fail_the_coverage_gate(self):
        error,result = self.exercise('no-compaction')
        self.assertIsInstance(error,AssertionError)
        self.assertEqual(result['status'],'failed')
        self.assertIn('No KV compaction occurred',result['error'])


if __name__ == '__main__':
    unittest.main()
