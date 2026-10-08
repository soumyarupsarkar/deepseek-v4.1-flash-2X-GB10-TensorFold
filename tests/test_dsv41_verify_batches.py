"""Verification preserves window order and graph outputs when replay buffers alias."""
from types import SimpleNamespace

import pytest
import torch

from tensorfold.families.deepseek_v41.cuda import multi


def decoder(rows=32):
    d = multi.MultiDecoder.__new__(multi.MultiDecoder)
    d.max_rows, d.depth_most = rows, 5
    d.verification_batches_total = d.max_verification_batches = d.peak_verification_rows = 0
    return d


def windows(lengths):
    return [(slot, slot*4096, 4096, 128, list(range(slot*10, slot*10+n)), [])
            for slot,n in enumerate(lengths)]


@pytest.mark.parametrize('lengths', [[2]*32, [1,2,1,2,2]*6, [3,2,1,3,3,2]])
@pytest.mark.parametrize('with_taps', [False, True])
def test_shared_buffers_are_copied_before_replay(monkeypatch, lengths, with_taps):
    monkeypatch.setattr(multi, 'VERIFY_BATCHED', True)
    d = decoder(32 if len(lengths)>10 else 6)
    logit_buffer, tap_buffer = torch.empty((d.max_rows,2)), torch.empty((d.max_rows,3))
    calls = []
    def forward(batch):
        ids = [t for w in batch for t in w[4]]
        calls.append([w[0] for w in batch])
        assert len(ids) <= d.max_rows
        logit_buffer.fill_(-999)
        tap_buffer.fill_(-999)
        logit_buffer[:len(ids)] = torch.tensor(ids)[:,None]
        tap_buffer[:len(ids)] = torch.tensor(ids)[:,None] + 1000
        return logit_buffer[:len(ids)], tap_buffer[:len(ids)] if with_taps else None
    d.runner = SimpleNamespace(forward=forward)
    ws = windows(lengths)
    out, taps = d._verify(ws)
    expected = torch.tensor([t for w in ws for t in w[4]])
    assert torch.equal(out[:,0], expected)
    assert taps is None if not with_taps else torch.equal(taps[:,0], expected+1000)
    assert sum(calls, []) == list(range(len(lengths)))
    assert d.max_verification_batches == len(calls) > 1
    assert d.peak_verification_rows == sum(lengths)
    if lengths == [2]*32:
        assert len(calls) == 2


def test_default_refuses_overflow_and_single_batch_returns_original_outputs(monkeypatch):
    monkeypatch.setattr(multi, 'VERIFY_BATCHED', False)
    d = decoder()
    output = (torch.zeros((32,2)), None)
    d.runner = SimpleNamespace(forward=lambda _:output)
    assert d._verify(windows([2]*16)) is output
    with pytest.raises(ValueError, match='enable TF_DS_VERIFY_BATCHED'):
        d._verify(windows([2]*32))
    with pytest.raises(ValueError, match='must fit'):
        d._verify(windows([33]))


def test_depth_only_extends_when_opted_in_and_respects_disabled_policy(monkeypatch):
    d = decoder()
    monkeypatch.setattr(multi,'DEPTH_BY',[5,5,3,3])
    monkeypatch.setattr(multi,'VERIFY_BATCHED',False)
    original = [d._depth(n) for n in range(1,33)]
    assert original[15:]==[1]+[0]*16
    monkeypatch.setattr(multi,'VERIFY_BATCHED',True)
    assert [d._depth(n) for n in range(1,17)] == original[:16]
    assert [d._depth(n) for n in range(17,33)] == [1]*16
    assert d._forward_cost(64)==2*d._forward_cost(32)
    monkeypatch.setattr(multi,'DEPTH_BY',[0])
    assert d._depth(32)==0
    monkeypatch.setattr(multi,'DEPTH_BY',[5])
    d.depth_most=0
    assert d._depth(32)==0


def test_64_rows_draft_all_32_streams_in_one_forward_without_batching(monkeypatch):
    monkeypatch.setattr(multi, 'VERIFY_BATCHED', False)
    monkeypatch.setattr(multi, 'DEPTH_BY', [5,5,3,3])
    d = decoder(64)
    assert d._depth(16) == 3
    assert d._depth(24) == d._depth(32) == 1
    calls = []
    output = (torch.zeros((64,2)), torch.zeros((64,3)))
    def forward(ws):
        calls.append(ws)
        return output
    d.runner = SimpleNamespace(forward=forward)
    ws = windows([2]*32)
    assert d._verify(ws) is output
    assert calls == [ws]
    assert d.max_verification_batches == 1 and d.peak_verification_rows == 64
