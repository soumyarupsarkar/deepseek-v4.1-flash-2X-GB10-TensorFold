"""Real xgrammar masks, coordinated failures, and the DeepSeek admission path."""
import json
import threading
from types import SimpleNamespace

import pytest
import torch
import xgrammar as xgr

from tensorfold.engine import grammar
from tensorfold.cuda.streams import Stream
from tensorfold.families.deepseek_v41.cuda import structured
from tensorfold.families.deepseek_v41.cuda.engine import DsEngine
from tensorfold.families.deepseek_v41.cuda.multi import MultiDecoder

VOCAB = ["", "a", "b", "c", "</think>", "{", "}", '"', ":", "1", "2", ",", " "]
GRAMMARS = grammar.Grammars(xgr.TokenizerInfo(VOCAB, xgr.VocabType.RAW,
                                            vocab_size=len(VOCAB), stop_token_ids=[0]))


def constraint(kind="choice", text='["ab"]', think_end=None):
    spec = grammar.Spec(kind, text)
    return GRAMMARS.constraint(GRAMMARS.compile(spec), spec=spec, think_end=think_end)


def engine():
    return SimpleNamespace(world=1, _sample=lambda logits, positions, sampling: logits.argmax(-1).tolist())


def test_masks_first_and_subsequent_tokens_and_terminates():
    c = constraint()
    e = engine()
    # The model always prefers c, which is never allowed by this grammar.
    logits = torch.arange(len(VOCAB), dtype=torch.float32).reshape(1, -1)
    logits[0, 3] = 100
    out = [structured.sample(e, logits.clone(), [i], None, c)[0] for i in range(3)]
    assert out == [1, 2, 0] and c.finished


def test_masks_inference_tensor_after_forward_context_has_exited():
    with torch.inference_mode():
        logits = torch.zeros(1, len(VOCAB))
        logits[0, 3] = 100
    assert torch.is_inference(logits)
    assert not torch.is_inference_mode_enabled()
    assert structured.sample(engine(), logits, [0], None, constraint()) == [1]


def test_thinking_is_free_then_constraint_starts_after_end_token():
    c = constraint(think_end=4)
    e = engine()
    for chosen in [3, 4]:
        lg = torch.zeros(1, len(VOCAB)); lg[0, chosen] = 10
        assert structured.sample(e, lg, [0], None, c) == [chosen]
    assert c.active
    lg = torch.zeros(1, len(VOCAB)); lg[0, 3] = 10
    assert structured.sample(e, lg, [0], None, c) == [1]


def test_empty_mask_is_a_request_error_not_arbitrary_argmax():
    with pytest.raises(grammar.GrammarError):
        structured.sample(engine(), torch.full((1, len(VOCAB)), float('-inf')), [0], None, constraint())


@pytest.mark.parametrize('peer', [[1, -1, 0], [0, 2, 0]])
def test_peer_error_or_token_disagreement_ends_request(monkeypatch, peer):
    monkeypatch.setattr(structured, '_exchange', lambda e, row, device=None: [row, peer])
    with pytest.raises(grammar.GrammarError):
        structured.sample(engine(), torch.zeros(1, len(VOCAB)), [0], None, constraint())


def test_compile_refusal_agreed_before_admission(monkeypatch):
    c = constraint()
    monkeypatch.setattr(structured, '_exchange', lambda e, row, device=None: [row, [1]])
    with pytest.raises(grammar.GrammarError):
        structured.ready(engine(), c, grammar.pack(c))


def test_request_failure_does_not_poison_other_streams(monkeypatch):
    decoder = MultiDecoder.__new__(MultiDecoder); decoder.e = engine()
    s = Stream([1], 10, constraint=constraint())
    assert decoder._sample_stream(s, torch.full((1, len(VOCAB)), float('-inf')), [1]) == []
    assert s.done and isinstance(s.error, grammar.GrammarError)
    other = Stream([1], 10)
    assert decoder._sample_stream(other, torch.tensor([[0., 5.]]), [1]) == [1]
    assert not other.done and other.error is None


def test_generate_disables_drafts_only_for_constrained_request():
    e = DsEngine.__new__(DsEngine)
    e.request = threading.local()
    calls = []
    e.scheduler = SimpleNamespace(submit=lambda *a, **kw: calls.append((a, kw)))
    c = constraint()
    e.generate([1, 2], 10, None, lambda x: False, draft=True, constraint=c)
    e.generate([1, 2], 10, None, lambda x: False, draft=True)
    assert calls[0][0][3] is False and calls[0][1]['constraint'] is c
    assert calls[1][0][3] is True and calls[1][1]['constraint'] is None


def test_prefill_first_token_uses_the_constraint():
    d = MultiDecoder.__new__(MultiDecoder)
    d.e = engine(); d._step = lambda busy: None; d._agree = lambda *args: None
    d._shape = lambda: []; d._ends = lambda s: (0,)
    d.streams = {}; d.round_end = None
    s = Stream([1, 2], 10, constraint=constraint())
    s.filled = 0
    def steps():
        yield from ()
        lg = torch.zeros(1, len(VOCAB)); lg[0, 3] = 10
        return lg
    s.steps = steps(); d.filling = [s]
    assert d._fill(s) == []
    assert s.out == [1] and s.pending == 1 and not d.filling


def test_tool_selection_preserves_named_strict_and_single_call_contract():
    tools = [{'type':'function','function':{'name':'pick','strict':True,
              'parameters':{'type':'object','properties':{'n':{'type':'integer'}},'required':['n']}}}]
    spec = grammar.tool_spec({'tool_choice':{'type':'function','function':{'name':'pick'}},
                              'parallel_tool_calls':False}, tools)
    config = json.loads(spec.text)
    assert config['tool_choice']['function']['name'] == 'pick'
    assert config['tools'][0]['function']['strict'] is True
    assert config['parallel_tool_calls'] is False
