"""Fail closed on stale prerequisites; retain bounded evidence without prompts."""
import copy
import hashlib
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch

ROOT = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location('native_endurance', ROOT / 'tools/qualification/native_endurance.py')
endurance = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(endurance)


class NativeEndurance(unittest.TestCase):
    def ranks(self):
        launch = dict(image='candidate-image', containers={'head': 'head-id', 'worker': 'worker-id'})
        rows = {host: [dict(Id=ident, Image=launch['image'], RestartCount=0,
                State=dict(Running=True, Paused=False, Restarting=False, StartedAt='2026-10-10T12:00:00Z'))]
                for host, ident in launch['containers'].items()}
        pair = Mock()
        pair.containers.side_effect = lambda host: rows[host]
        active = dict(launch, running=True)
        return pair, launch, active, rows

    def test_same_container_restart_invalidates_endurance(self):
        pair, launch, active, rows = self.ranks()
        epochs = endurance.rank_epochs(pair, launch)
        endurance.validate_continuity(pair, launch, epochs, copy.deepcopy(launch), active)
        # A manual restart can preserve the ID and automatic restart counter.
        rows['worker'][0]['State']['StartedAt'] = '2026-10-10T13:00:00Z'
        with self.assertRaisesRegex(RuntimeError, 'rank restarted'):
            endurance.validate_continuity(pair, launch, epochs, launch, active)

    def test_restart_counter_or_launch_change_invalidates_endurance(self):
        for change in ('counter', 'launch', 'active', 'active-image', 'active-container'):
            pair, launch, active, rows = self.ranks()
            epochs = endurance.rank_epochs(pair, launch)
            current = copy.deepcopy(launch)
            if change == 'counter':
                rows['head'][0]['RestartCount'] = 1
            elif change == 'launch':
                current['containers']['head'] = 'replacement'
            elif change == 'active':
                active['running'] = False
            elif change == 'active-image':
                active['image'] = 'replacement'
            else:
                active['containers'] = dict(active['containers'], head='replacement')
            with self.subTest(change=change), self.assertRaises(RuntimeError):
                endurance.validate_continuity(pair, launch, epochs, current, active)

    def test_unhealthy_or_unidentifiable_ranks_are_rejected(self):
        for change in ('absent', 'duplicate', 'id', 'image', 'stopped', 'paused', 'restarting',
                       'missing-start', 'zero-start', 'missing-counter', 'boolean-counter'):
            pair, launch, active, rows = self.ranks()
            row = rows['head'][0]
            if change == 'absent':
                rows['head'].clear()
            elif change == 'duplicate':
                rows['head'].append(copy.deepcopy(row))
            elif change == 'id':
                row['Id'] = 'replacement'
            elif change == 'image':
                row['Image'] = 'replacement'
            elif change == 'stopped':
                row['State']['Running'] = False
            elif change == 'paused':
                row['State']['Paused'] = True
            elif change == 'restarting':
                row['State']['Restarting'] = True
            elif change == 'missing-start':
                del row['State']['StartedAt']
            elif change == 'zero-start':
                row['State']['StartedAt'] = '0001-01-01T00:00:00Z'
            elif change == 'missing-counter':
                del row['RestartCount']
            else:
                row['RestartCount'] = False
            with self.subTest(change=change), self.assertRaises(RuntimeError):
                endurance.rank_epochs(pair, launch)

    def test_exact_image_source_and_prerequisites_required(self):
        with tempfile.TemporaryDirectory() as directory:
            receipt = Path(directory) / 'receipt.json'
            receipt.write_text('{"status":"passed"}')
            gates = dict(status='passed', passed=sorted(endurance.GATES), image='candidate-image',
                         source='candidate-source', receipts=[dict(path=str(receipt),
                         sha256=hashlib.sha256(receipt.read_bytes()).hexdigest())])
            launch = dict(image='candidate-image')
            endurance.validate_gates(gates, launch, 'candidate-source')
            for change in (dict(status='running'), dict(image='old-image'), dict(source='old-source'),
                           dict(passed=sorted(endurance.GATES - {'recovery'})), dict(receipts=[])):
                with self.subTest(change=change), self.assertRaises(RuntimeError):
                    endurance.validate_gates(dict(gates, **change), launch, 'candidate-source')
            receipt.write_text('{"status":"failed"}')
            with self.assertRaisesRegex(RuntimeError, 'receipt changed'):
                endurance.validate_gates(gates, launch, 'candidate-source')

    def test_limit_preserves_previous_evidence(self):
        with tempfile.TemporaryDirectory() as directory:
            evidence = Path(directory) / 'cycles.jsonl'
            evidence.touch()
            first = dict(kind='first', value=3)
            endurance.append(evidence, first)
            before = evidence.read_bytes()
            with patch.object(endurance, 'MAX_EVIDENCE_BYTES', len(before) + 2):
                with self.assertRaisesRegex(RuntimeError, 'evidence limit'):
                    endurance.append(evidence, dict(kind='second'))
            self.assertEqual(evidence.read_bytes(), before)
            self.assertEqual(json.loads(before), first)

    def test_evidence_omits_response_text_and_token_ids(self):
        result = dict(seconds=1.5, response=dict(choices=[dict(message=dict(content='synthetic output'))],
                      usage=dict(prompt_tokens=5, completion_tokens=2, total_tokens=7,
                                 prompt_tokens_details=dict(cached_tokens=3)),
                      tensorfold=dict(token_sha='abc', token_ids=[1, 2], sampling_seed='0', drafts=True)))
        compact = endurance.compact_result(result)
        self.assertEqual(compact['usage']['total_tokens'], 7)
        self.assertEqual(compact['token_sha'], 'abc')
        self.assertEqual(compact['cached'], 3)
        self.assertNotIn('choices', compact)
        self.assertNotIn('token_ids', compact)
        self.assertNotIn('synthetic output', json.dumps(compact))


if __name__ == '__main__':
    unittest.main()
