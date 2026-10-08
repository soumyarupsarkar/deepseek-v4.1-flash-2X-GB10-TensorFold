"""Committed-token loop decisions and precision startup policy, without a GPU."""
import os
from pathlib import Path
import sys
import types
import unittest
from unittest.mock import patch

SOURCE = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(SOURCE / 'src'))
from tensorfold.engine.call_gate import ThinkLoop, generate_gated
from tensorfold.families import deepseek_v41

END, NEWLINE, ANSWER, EOS = 90001, 90002, 90003, 90004
CLOSE = [NEWLINE, END, NEWLINE, NEWLINE]


def generate_reply(width, *, limit=5000, natural_end=None, stop_client=False):
    guard = ThinkLoop(CLOSE, END)
    output, prompts = [], []

    def generate(prompt, count, feed):
        prompts.append(list(prompt))
        if END in prompt:
            reply = [ANSWER, EOS]
        else:
            reply = [7] * count
            if natural_end is not None and natural_end < len(reply):
                reply[natural_end:] = [END, ANSWER, EOS]
        for at in range(0, min(count, len(reply)), width):
            if feed(reply[at:min(at + width, count)]):
                break
        return {'runs': 1}

    def receive(tokens):
        output.extend(tokens)
        return stop_client and END in output

    stats = generate_gated(generate, [1, 2], limit, [guard], receive)
    return guard, output, prompts, stats


class ReasoningGuardTests(unittest.TestCase):
    def test_repetition_closes_at_same_committed_token_for_any_callback_width(self):
        expected = [7] * 4096 + CLOSE + [ANSWER, EOS]
        for width in (1, 3, 6, 17, 1024, 2048, 5000):
            with self.subTest(width=width):
                guard, output, prompts, stats = generate_reply(width)
                self.assertEqual(output, expected)
                self.assertTrue(guard.fired)
                self.assertFalse(guard.open)
                self.assertEqual(prompts[1], [1, 2, *expected[:-2]])
                self.assertEqual(stats['runs'], 2)

    def test_natural_close_does_not_trigger_or_rewrite_answer(self):
        for width in (1, 6, 5000):
            guard, output, prompts, _ = generate_reply(width, natural_end=4095)
            self.assertEqual(output, [7] * 4095 + [END, ANSWER, EOS])
            self.assertFalse(guard.fired)
            self.assertEqual(len(prompts), 1)

    def test_novel_reasoning_is_unchanged(self):
        guard = ThinkLoop(CLOSE, END)
        for start in range(0, 6144, 6):
            chunk = list(range(start, start + 6))
            self.assertIsNone(guard.cut(chunk))
            for token in chunk:
                guard.observe(token)
        self.assertFalse(guard.fired)
        self.assertEqual(guard.dry, 0)

    def test_preview_does_not_change_committed_history(self):
        guard = ThinkLoop(CLOSE, END)
        snapshot = (set(guard.seen), list(guard.win), list(guard.tail), guard.dry, guard.fired)
        for _ in range(2):
            self.assertEqual(guard.cut([7] * 5000), (4096, CLOSE))
            self.assertEqual((guard.seen, guard.win, guard.tail, guard.dry, guard.fired), snapshot)

    def test_close_respects_remaining_reply_budget(self):
        guard, output, prompts, _ = generate_reply(6, limit=4098)
        self.assertEqual(output, [7] * 4096 + CLOSE[:2])
        self.assertEqual(len(prompts), 1)
        self.assertTrue(guard.fired)

    def test_client_stop_prevents_continuation(self):
        guard, output, prompts, _ = generate_reply(6, stop_client=True)
        self.assertEqual(output, [7] * 4096 + CLOSE)
        self.assertEqual(len(prompts), 1)
        self.assertTrue(guard.fired)


class PrecisionStartupTests(unittest.TestCase):
    def test_override_is_cleared_before_engine_creation_and_probe_runs(self):
        events = []
        sentinel = object()

        def engine(*args, **kwargs):
            events.append(('engine', os.environ['TORCH_ALLOW_TF32_CUBLAS_OVERRIDE']))
            return sentinel

        module = types.ModuleType('tensorfold.families.deepseek_v41.cuda.engine')
        module.DsEngine = engine
        with patch.dict(os.environ, {'TORCH_ALLOW_TF32_CUBLAS_OVERRIDE': '1'}), \
             patch.dict(sys.modules, {module.__name__: module}), \
             patch.object(deepseek_v41, 'fp32_gemms', side_effect=lambda: events.append(('probe',))):
            self.assertIs(deepseek_v41.cuda_engine('/unused', tp=1), sentinel)
        self.assertEqual(events, [('engine', '0'), ('probe',)])

    def test_failed_precision_probe_prevents_returning_ready_engine(self):
        module = types.ModuleType('tensorfold.families.deepseek_v41.cuda.engine')
        module.DsEngine = lambda *args, **kwargs: object()
        with patch.dict(os.environ), patch.dict(sys.modules, {module.__name__: module}), \
             patch.object(deepseek_v41, 'fp32_gemms', side_effect=RuntimeError('precision mismatch')):
            with self.assertRaisesRegex(RuntimeError, 'precision mismatch'):
                deepseek_v41.cuda_engine('/unused', tp=1)


if __name__ == '__main__':
    unittest.main()
