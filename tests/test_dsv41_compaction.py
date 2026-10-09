"""Move real CPU cache tensors through the serving allocator, without loading weights."""
from types import SimpleNamespace as NS
import weakref

import pytest
import torch

from tensorfold.cuda.streams import Stream
from tensorfold.families.deepseek_v41.cuda import engine, multi
from tensorfold.families.deepseek_v41.cuda.compaction import copy_range
from tensorfold.families.deepseek_v41.cuda.model import Model, PoolCache, RAW
from tensorfold.families.deepseek_v41.ops import HostIds


@pytest.mark.parametrize('source,destination,rows', [(9, 2, 19), (2, 9, 19), (0, 20, 9), (9, 9, 8), (0, 0, 0)])
@pytest.mark.parametrize('dtype', [torch.int64, torch.uint8, torch.bfloat16])
def test_copy_preserves_every_bit_including_overlap(source, destination, rows, dtype):
    values = torch.arange(128).reshape(32, 4).to(dtype)
    expected = values.clone()
    expected[destination:destination+rows] = values[source:source+rows].clone()
    copy_range(values, source, destination, rows, max_temporary_bytes=4*values.element_size()*3)
    assert torch.equal(values, expected)


def test_overlap_has_at_most_one_live_bounded_clone(monkeypatch):
    values = torch.arange(240).reshape(40, 6)
    expected = values.clone()
    expected[2:34] = values[7:39].clone()
    real_clone, references, sizes = torch.Tensor.clone, [], []

    def observed(t, *args, **kwargs):
        assert all(ref() is None for ref in references), 'previous temporary was retained'
        sizes.append(t.numel()*t.element_size())
        saved = real_clone(t, *args, **kwargs)
        references.append(weakref.ref(saved))
        return saved

    monkeypatch.setattr(torch.Tensor, 'clone', observed)
    copy_range(values, 7, 2, 32, 200)
    assert torch.equal(values, expected)
    assert len(sizes) > 1 and max(sizes) <= 200
    assert all(ref() is None for ref in references)


@pytest.mark.parametrize('source,destination,rows,budget', [(-1, 0, 1, 32), (0, 9, 2, 32),
                                                          (0, 0, -1, 32), (0, 1, 3, 0), (0, 1, 3, 1)])
def test_invalid_copy_fails_before_modifying_data(source, destination, rows, budget):
    values = torch.arange(40).reshape(10, 4)
    before = values.clone()
    with pytest.raises(ValueError):
        copy_range(values, source, destination, rows, budget)
    assert torch.equal(values, before)


def make_decoder(quantized=True, device='cpu'):
    """Three disjoint extents; no contiguous hole fits 24 rows, even after prefix eviction."""
    model = Model.__new__(Model)
    model.cfg = NS(compress_ratios={0: 2, 1: 4})
    pool = PoolCache(slots=3, cap=64, ring_size=4)
    pool.tokens = torch.arange(64, dtype=torch.int64)
    pool.ring = [torch.arange(24).reshape(12, 2)]
    pool.comp_raw = {0: (torch.arange(3*RAW*2).reshape(3*RAW, 2), torch.full((3*RAW, 2), 5))}
    for layer, ratio in model.cfg.compress_ratios.items():
        values = torch.arange(64//ratio*4).reshape(64//ratio, 4)
        if quantized:
            pool.comp[layer] = (values.to(torch.uint8), (values[:, :1]+71).to(torch.uint8))
            pool.index_k[layer] = ((values+23).to(torch.uint8), (values[:, :1]+113).to(torch.uint8))
        else:
            pool.comp[layer] = values.to(torch.bfloat16)
            pool.index_k[layer] = (values+23).to(torch.bfloat16)
    def on_device(value):
        return tuple(t.to(device) for t in value) if isinstance(value, tuple) else value.to(device)
    pool.tokens = pool.tokens.to(device)
    pool.ring = [t.to(device) for t in pool.ring]
    for name in ('comp', 'index_k', 'comp_raw'):
        setattr(pool, name, {key: on_device(value) for key, value in getattr(pool, name).items()})
    d = multi.MultiDecoder.__new__(multi.MultiDecoder)
    d.m, d.pool, d.e = model, pool, NS(world=1, rank=0, limit=64)
    d.watch, d.link, d.next_id, d.max_rows = None, None, 2, 0
    d.extents, d.free, d.kept, d.streams, d.filling = multi.Extents(64, align=4), [2], {}, {}, []
    d.kv_compactions = d.kv_compacted_rows = d.kv_compacted_streams = 0
    d.kv_compacted_prefills = d.kv_compaction_evictions = 0
    for sid, base, size in ((0, 8, 16), (1, 32, 12)):
        assert d.extents.take_at(base, size)
        cache = model.pool_view(pool, sid, base, size)
        cache.length, cache.host = 4, HostIds([3, 4, 5, 6])
        s = Stream(prompt=list(range(8)), count=4, sid=sid)
        s.base, s.size, s.filled, s.st = base, size, 4, multi.Slot(sid, object())
        s.st.sc, s.snaps = cache, {4: object()}
        if sid == 0:
            s.out = [12, 13]
            d.streams[sid] = s
        else:
            d.filling.append(s)
    assert d.extents.take_at(48, 8)
    d.kept[0] = multi.Kept(0, 48, 8, 8, HostIds(range(8)), {4: object()}, True, list(range(8)), 9)
    d._publish_occupancy()
    return d


def tensors(pool):
    yield ('tokens', 0, 0), pool.tokens
    for name in ('comp', 'index_k'):
        for layer, plane in getattr(pool, name).items():
            for part, tensor in enumerate(plane if isinstance(plane, tuple) else (plane,)):
                yield (name, layer, part), tensor


@pytest.mark.parametrize('quantized', [True, False])
def test_compaction_preserves_views_prefixes_and_all_cache_bytes(quantized):
    d = make_decoder(quantized)
    assert not d._room(24)
    before = {key: tensor.clone() for key, tensor in tensors(d.pool)}
    pointers = {key: tensor.data_ptr() for key, tensor in tensors(d.pool)}
    active = [*d.streams.values(), *d.filling]
    identities = {s.sid: (s.st.sc, s.st.sc.host, s.st.sc.ring, s.st.sc.comp_raw, s.st.dc, s.snaps) for s in active}
    retained = d.kept[0]
    d._compact(24)
    assert d.extents.gaps == [(36, 64)] and d._room(24)
    assert [s.base for s in active] == [0, 16] and d.kept[0].base == 28
    assert d.kept[0] is retained and d.kv_compaction_evictions == 0
    assert (d.kv_compactions, d.kv_compacted_rows, d.kv_compacted_streams, d.kv_compacted_prefills) == (1, 36, 2, 1)
    assert d._pool_snapshot['reserved_rows'] == d._pool_snapshot['reserved_accounted_rows'] == 36
    assert d.extents.take(24) == 36
    for key, tensor in tensors(d.pool):
        assert tensor.data_ptr() == pointers[key]
        ratio = 1 if key[0] == 'tokens' else d.m.cfg.compress_ratios[key[1]]
        for source, destination, rows in ((8, 0, 16), (32, 16, 12), (48, 28, 8)):
            assert torch.equal(tensor[destination//ratio:(destination+rows)//ratio],
                               before[key][source//ratio:(source+rows)//ratio])
    for s in active:
        current = (s.st.sc, s.st.sc.host, s.st.sc.ring, s.st.sc.comp_raw, s.st.dc, s.snaps)
        assert all(a is b for a, b in zip(current, identities[s.sid]))
        assert s.st.sc.length == 4 and s.st.sc.cap == s.size
        assert s.st.sc.tokens.data_ptr() == d.pool.tokens[s.base:].data_ptr()
        for name in ('comp', 'index_k'):
            for layer, plane in getattr(s.st.sc, name).items():
                parts = plane if isinstance(plane, tuple) else (plane,)
                original = getattr(d.pool, name)[layer]
                original = original if isinstance(original, tuple) else (original,)
                for part, global_plane in zip(parts, original):
                    assert part.data_ptr() == global_plane[s.base//d.m.cfg.compress_ratios[layer]:].data_ptr()


def test_suspended_real_prefill_generator_resumes_on_relocated_views(monkeypatch):
    d = make_decoder()
    s, cache = d.filling[0], d.filling[0].st.sc
    e = engine.DsEngine.__new__(engine.DsEngine)
    e.model, e.w, e.replay_mode, e.rank = d.m, NS(cfg=NS(window=4)), False, 0
    d.m.engram = None
    monkeypatch.setattr(engine, 'PREFILL_CHUNK', 4)
    monkeypatch.setattr(engine, 'CHUNK_LOG', False)
    original_tensor = torch.tensor

    def cpu_tensor(*args, **kwargs):
        if kwargs.get('device') == 'cuda':
            kwargs['device'] = 'cpu'
        return original_tensor(*args, **kwargs)

    monkeypatch.setattr(torch, 'tensor', cpu_tensor)
    seen = []

    def forward(sc, ids, start, **kwargs):
        seen.append((sc, sc.tokens.data_ptr(), start))
        sc.tokens[start:start+len(ids)].copy_(ids)
        sc.length = start+len(ids)
        return ids[-1:]

    d.m.forward = forward
    s.steps = e.prefill_steps(cache, None, s.prompt)
    assert next(s.steps) == 4
    d._compact(24)
    with pytest.raises(StopIteration) as end:
        next(s.steps)
    assert end.value.value.item() == s.prompt[-1]
    assert seen[0][0] is seen[1][0] is cache
    assert seen[0][1] != seen[1][1] == d.pool.tokens[16:].data_ptr()
    assert torch.equal(d.pool.tokens[16:24], torch.arange(8))
    assert cache.length == 8


def test_disagreement_rejects_the_move_before_any_pool_mutation():
    d = make_decoder()
    before = {key: tensor.clone() for key, tensor in tensors(d.pool)}
    shape = d._shape()
    def disagree(what, placement):
        assert what == 'KV compaction' and placement[0] == shape
        raise multi.OutOfStep('test peer mismatch')
    d._agree = disagree
    with pytest.raises(multi.OutOfStep):
        d._compact(24)
    assert d._shape() == shape and d.kv_compactions == 0
    assert all(torch.equal(tensor, before[key]) for key, tensor in tensors(d.pool))


def test_leader_admission_compacts_before_matching_and_follower_matches_bits(monkeypatch):
    head, follower = make_decoder(), make_decoder()
    operations, placements = [], []
    monkeypatch.setattr(multi, 'KEEP', False)
    head._send = operations.append
    def allocated(s, index, positions, reuse, packed):
        placements.append(head.extents.take(head._need(s)))
    head._admit = allocated
    head.admit(Stream(prompt=list(range(8)), count=4))  # 8+4+0+12 = 24 rows
    assert operations[0] == ['compact', 24] and operations[1][0] == 'admit'
    assert placements == [36]
    commands = iter([operations[0], None])
    with pytest.raises(RuntimeError, match='step link closed'):
        follower.follow(NS(receive=lambda: next(commands)))
    assert follower.kv_compactions == 1
    assert all(torch.equal(a, b) for (_, a), (_, b) in zip(tensors(head.pool), tensors(follower.pool)))


def test_impossible_admission_does_not_move_live_requests_or_send_an_operation():
    d = make_decoder()
    operations, shape = [], d._shape()
    d._send = operations.append
    with pytest.raises(multi.NoRoom):
        d.admit(Stream(prompt=list(range(40)), count=8))
    assert d._shape() == shape and not operations and d.kv_compactions == 0


@pytest.mark.skipif(not torch.cuda.is_available(), reason='needs a CUDA device; CPU tests do not create a context')
@pytest.mark.parametrize('quantized', [True, False])
def test_cuda_copies_and_captured_storage_survive_relocation(quantized):
    d = make_decoder(quantized, device='cuda')
    before = {key: tensor.clone() for key, tensor in tensors(d.pool)}
    pointers = {key: tensor.data_ptr() for key, tensor in tensors(d.pool)}
    indices = torch.arange(8, 24, device='cuda')
    out = torch.empty(16, dtype=torch.int64, device='cuda')
    warm = torch.cuda.Stream()
    warm.wait_stream(torch.cuda.current_stream())
    with torch.cuda.stream(warm):
        torch.index_select(d.pool.tokens, 0, indices, out=out)
    torch.cuda.current_stream().wait_stream(warm)
    graph = torch.cuda.CUDAGraph()
    with torch.cuda.graph(graph):
        torch.index_select(d.pool.tokens, 0, indices, out=out)
    d._compact(24)
    indices.sub_(8)
    graph.replay()
    torch.cuda.synchronize()
    assert torch.equal(out, before[('tokens', 0, 0)][8:24])
    for key, tensor in tensors(d.pool):
        assert tensor.data_ptr() == pointers[key]
        ratio = 1 if key[0] == 'tokens' else d.m.cfg.compress_ratios[key[1]]
        for source, destination, rows in ((8, 0, 16), (32, 16, 12), (48, 28, 8)):
            assert torch.equal(tensor[destination//ratio:(destination+rows)//ratio],
                               before[key][source//ratio:(source+rows)//ratio])
    # Force multiple overlapping chunks on CUDA as well as the allocator's tiny fixture.
    values = torch.arange(512*1024, device='cuda').reshape(-1, 8)
    expected = values.clone()
    expected[123:60123] = values[:60000].clone()
    copy_range(values, 0, 123, 60000, 65536)
    torch.cuda.synchronize()
    assert torch.equal(values, expected)
