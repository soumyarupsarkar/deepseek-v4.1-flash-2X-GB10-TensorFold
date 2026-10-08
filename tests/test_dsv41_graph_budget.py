"""Serving wider contexts must not grow driver graphs after memory admission."""
from types import SimpleNamespace

import pytest
import torch

from tensorfold.families.deepseek_v41.cuda.graph_budget import widths, select
from tensorfold.families.deepseek_v41.cuda.multi import MultiDecoder
from tensorfold.families.deepseek_v41.cuda.rounds import RoundRunner


def test_native_context_is_covered_without_using_aggregate_pool_size():
    choices = widths('8192,65536,8192,9999999', 1048576)
    assert choices == (8192, 65536, 1048576)
    for pos, expected in [(1,8192),(8192,8192),(8193,65536),(65536,65536),
                          (65537,1048576),(1048576,1048576)]:
        assert select(pos, choices) == expected
    with pytest.raises(ValueError, match='exceeds graph position cap'):
        select(1048577, choices)
    assert widths(None,1048590) == ()
    assert widths('0',1048590) == (1048590,)
    with pytest.raises(ValueError):
        widths('-1',1048590)


def test_runner_does_not_inflate_native_graph_for_scratch_or_pool(monkeypatch):
    monkeypatch.setenv('TF_DS_GRAPH_BUCKETS','8192,65536')
    r=RoundRunner(SimpleNamespace(rope_context=1048576,rope_cap=1048590),
                  SimpleNamespace(cap=4227072))
    assert r.widths==(8192,65536,1048576)
    assert r.bucket(1048576)==1048576


def test_warm_covers_every_runtime_shape_largest_first_and_seals(monkeypatch):
    r = RoundRunner.__new__(RoundRunner)
    r.m = SimpleNamespace(engram=None, rope_cap=65550)
    r.pool = SimpleNamespace(cap=4227072)
    r.widths = widths('8192', r.m.rope_cap)
    r.graphs, r.sealed = {}, False
    captured = []

    def capture(windows, replay):
        assert not replay
        _, _, _, pos, tokens, _ = windows[0]
        key = (len(tokens), r.bucket(pos+len(tokens)))
        captured.append(key)
        r.graphs[key] = SimpleNamespace(run=lambda *a: 'logits', taps=None)

    decoder = MultiDecoder.__new__(MultiDecoder)
    decoder.runner = r
    decoder.cap, decoder.max_rows = r.pool.cap, 16
    decoder.extents = SimpleNamespace(total=r.pool.cap)
    decoder.e = SimpleNamespace(drafter=None,rank=1)
    decoder.drafters = {}
    monkeypatch.setattr(r,'forward',capture)
    monkeypatch.setattr(torch.cuda,'synchronize',lambda:None)
    decoder.warm()
    assert captured == [(rows,width) for width in (65550,8192) for rows in range(16,0,-1)]
    assert r.sealed
    monkeypatch.delattr(r,'forward')
    for rows in range(1,17):
        for pos in (0,8191,8192,32767,65536):
            pos = min(pos,65550-rows)
            assert r.forward([(0,0,1048576,pos,[1000]*rows,[])]) == ('logits',None)
    del r.graphs[(16,65550)]
    with pytest.raises(RuntimeError, match='not warmed before serving'):
        r.forward([(0,0,1048576,32768,[1000]*16,[])])
