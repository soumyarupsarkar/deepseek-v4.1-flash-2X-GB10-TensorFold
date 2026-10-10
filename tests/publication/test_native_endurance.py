"""Fail closed on stale prerequisites; retain bounded evidence without prompts."""
import hashlib
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location('native_endurance', ROOT / 'tools/qualification/native_endurance.py')
endurance = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(endurance)


class NativeEndurance(unittest.TestCase):
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
                      usage=dict(prompt_tokens=5, completion_tokens=2, total_tokens=7),
                      tensorfold=dict(token_sha='abc', token_ids=[1, 2], sampling_seed='0', drafts=True)))
        compact = endurance.compact_result(result)
        self.assertEqual(compact['usage']['total_tokens'], 7)
        self.assertEqual(compact['token_sha'], 'abc')
        self.assertNotIn('choices', compact)
        self.assertNotIn('token_ids', compact)
        self.assertNotIn('synthetic output', json.dumps(compact))


if __name__ == '__main__':
    unittest.main()
