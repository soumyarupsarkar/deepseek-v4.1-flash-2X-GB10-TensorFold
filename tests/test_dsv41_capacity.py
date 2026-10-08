"""Aggregate capacity must fit all extents without enlarging positional tables."""
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from tensorfold.families.deepseek_v41.config import Cfg
from tensorfold.families.deepseek_v41.cuda.capacity import plan, display_placement
from tensorfold.families.deepseek_v41.cuda.model import Model, SeqCache
from tensorfold.families.deepseek_v41.cuda.multi import Extents
from tensorfold.families.deepseek_v41.cuda.multi import MultiDecoder
from tensorfold.families.deepseek_v41.cuda.rounds import RoundRunner
from tensorfold.families.deepseek_v41.ops import RopeTables

CFG = Cfg.from_dict(json.loads((Path(__file__).parent / 'fixtures/deepseek_v41/config.json').read_text()))


@pytest.mark.parametrize('slots', [4, 8, 16])
@pytest.mark.parametrize('context', [65536, 262144, 614400, 1048576])
def test_every_full_stream_and_its_scratch_fit(slots, context):
    p = plan(CFG, context=context, slots=slots, pool_tokens=slots * context)
    ext = Extents(p['allocated_pool_rows'])
    addresses = [ext.take(context + 16 + 12) for _ in range(slots)]
    assert None not in addresses and len(set(addresses)) == slots
    assert p['shared_pool_tokens'] == slots * context
    assert p['pool_bytes'] == sum(p[k] for k in ('compressed_bytes','index_bytes','window_ring_bytes',
                                               'compressor_ring_bytes','token_ids_bytes'))


def test_aggregate_may_exceed_native_context_but_request_cannot():
    assert plan(CFG, context=614400, slots=16, pool_tokens=9830400)['shared_pool_tokens'] == 9830400
    with pytest.raises(ValueError, match='per-request context'):
        plan(CFG, context=1048577, slots=16, pool_tokens=16777232)
    with pytest.raises(ValueError, match='at least one full'):
        plan(CFG, context=614400, slots=16, pool_tokens=262144)
    with pytest.raises(ValueError, match='decode capacity'):
        plan(CFG, context=614400, slots=17, pool_tokens=10485760)


def test_rope_table_uses_sequence_positions_not_physical_pool_addresses():
    m = Model.__new__(Model)
    m.rope_cap = 614400 + 14
    m.cfg = CFG
    m.rope = SimpleNamespace(cs=lambda kind, need: RopeTables.rows(need))
    assert m._cs(0, SeqCache(cap=9830400)) == 618496
    assert m._cs(0, SeqCache(cap=2048)) == 618496


@pytest.mark.parametrize('context', [262144, 524288, 614400, 1048576])
def test_rope_scratch_does_not_double_the_user_context_bucket(context):
    m = Model.__new__(Model)
    m.rope_context = context
    m.rope_cap = context + 14
    m.cfg = CFG
    m.rope = SimpleNamespace(cs=lambda kind, need: RopeTables.rows(need))
    rows = m._cs(0, SeqCache(cap=8716288))
    assert rows >= context + 14           # verification may touch padded positions
    assert rows < context + 14 + 4096
    assert m._cs(2, SeqCache(cap=2048)) == rows   # small drafter and large target agree


def test_native_context_reuses_the_same_shared_pool_allocation():
    old = plan(CFG, context=614400, slots=16, pool_tokens=4194304)
    native = plan(CFG, context=1048576, slots=16, pool_tokens=4194304)
    assert {k: v for k, v in old.items() if k != 'per_request_tokens'} == {
        k: v for k, v in native.items() if k != 'per_request_tokens'}
    ext = Extents(native['allocated_pool_rows'])
    assert all(ext.take(1048576 + 28) is not None for _ in range(4))
    assert ext.take(1048576 + 28) is None


def test_round_buckets_are_bounded_by_per_request_positions():
    r = RoundRunner.__new__(RoundRunner)
    r.m = SimpleNamespace(rope_cap=614414)
    r.pool = SimpleNamespace(cap=9863168)
    assert r.bucket(614400) == 614414
    assert r.bucket(2000) == 2048


def test_growing_pool_does_not_multiply_fixed_rings():
    small = plan(CFG, context=614400, slots=16, pool_tokens=614400)
    large = plan(CFG, context=614400, slots=16, pool_tokens=9830400)
    for key in ('window_ring_bytes', 'compressor_ring_bytes'):
        assert small[key] == large[key]
    assert large['compressed_bytes'] > small['compressed_bytes']


def test_display_credit_counts_only_fitting_tensors_and_alignment():
    assert display_placement([1024, 100, 1024, 128], 1280) == 1124
    assert display_placement([4096, 512, 256], 1024) == 768
    assert display_placement([100, 100], 300) == 100
    assert display_placement([1], 0) == 0


@pytest.mark.parametrize('slots', [4, 8, 16])
def test_warm_skips_drafter_counts_runtime_cannot_use(monkeypatch, slots):
    import torch
    decoder=MultiDecoder.__new__(MultiDecoder)
    decoder.e=SimpleNamespace(drafter=object(),rank=1)
    decoder.slots=list(range(slots));decoder.max_rows=16;decoder.depth_most=5
    decoder.drafters={}
    counts=[]
    decoder._drafts=lambda tokens,positions,slots:counts.append(len(tokens))
    monkeypatch.setattr(torch.cuda,'synchronize',lambda:None)
    decoder.warm(buckets=())
    assert counts==list(range(1,min(slots,8)+1))
