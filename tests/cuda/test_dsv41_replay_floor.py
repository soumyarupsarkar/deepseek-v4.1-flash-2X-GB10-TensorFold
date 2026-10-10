"""Reproduce stale-slot attention through the real dispatcher and CUDA kernel.

No model weights: projection/norm/rotary stages are identities; attention, floor
selection, compressed-key padding and ring writes use the serving implementation.
"""
from types import SimpleNamespace as NS

import pytest
import torch

from tensorfold.families.deepseek_v41.cuda import model as M
from tensorfold.families.deepseek_v41.cuda import kernels as K

pytestmark = pytest.mark.skipif(not torch.cuda.is_available(), reason='requires CUDA')


def fixture(monkeypatch, start, rows, floor, compressed):
    torch.manual_seed(342)
    h, hd, window = 16, 512, 128
    q = torch.randn((rows, h, hd), device='cuda', dtype=torch.bfloat16)*.1
    keys = torch.randn((window+rows, hd), device='cuda', dtype=torch.bfloat16)*.1
    pos = torch.arange(start, start+rows, device='cuda')
    sink = torch.zeros(h, device='cuda')
    ring = torch.empty((window+M.RING_EXTRA, hd), device='cuda', dtype=torch.bfloat16)
    comp = torch.randn((37, hd), device='cuda', dtype=torch.bfloat16)*.1 if compressed else None
    idx = torch.arange(37, device='cuda').expand(rows, -1).contiguous() if compressed else None
    if compressed:
        idx[:, -3:] = -1  # non-multiple-of-16 width and masked picks
    model = M.Model.__new__(M.Model)
    model.cfg = NS(rope_dim=0, head_dim=hd, window=window, eps=1e-6)
    model.Hl, model.scratch = h, {}
    model._zero = torch.zeros(1, device='cuda', dtype=torch.int64)
    model._cs = lambda *args: (None, None)
    layer = NS(idx=0, ratio=64 if compressed else 0, q_norm=None, kv_norm=None,
               wq_b=None, wo_b=None, sink=sink, comp_wkv=None, idx_wq_b=None)
    cache = NS(ring=[ring], ring_size=ring.shape[0], comp={0: comp})
    monkeypatch.setattr(M, 'attn_in', lambda *a, **kw: (q.flatten(1), keys[-rows:], None, None))
    monkeypatch.setattr(M, 'mm', lambda w, x, dtype=None: x if dtype is None else x.to(dtype))
    monkeypatch.setattr(M, 'wo_a_out', lambda lay, out: out.flatten(1))
    monkeypatch.setattr(K, 'rmsnorm', lambda x, *a: x)
    monkeypatch.setattr(K, 'rope_heads', lambda x, *a, **kw: x)
    monkeypatch.setattr(K, 'DECODE_ROWS', 32)  # qualified deployment, including the 17-row control

    def write_keys(y, norm, cos, sin, positions, destination, slots, *args, out=None):
        if out is None:
            destination[slots] = y
        else:
            out.copy_(y)
        return y
    monkeypatch.setattr(K, 'kv_norm_rope', write_keys)

    lo = max(floor, start-(window-1))
    valid = keys[-(start-lo+rows):]

    def run(enabled, poison):
        monkeypatch.setattr(M, 'REPLAY_FLOOR', enabled)
        ring.fill_(poison)
        if start > lo:
            ring[torch.arange(lo, start, device='cuda') % ring.shape[0]] = valid[:-rows]
        result = model.attention_k(layer, q.flatten(1), cache, start,
                                   {'kv_layer': 0, 'topk': idx}, pos, floor=floor)
        # The replay correction must still install the current keys for decode.
        assert torch.equal(ring[pos % ring.shape[0]], keys[-rows:])
        return result.clone()

    def reference():
        return K.sparse_attn(q, sink, valid.contiguous(), torch.tensor([lo], device='cuda'),
                            False, comp, idx, pos, hd**-.5, window, one_split=True).flatten(1).float()
    return run, reference


@pytest.mark.parametrize('chunk', [1024, 2048])
@pytest.mark.parametrize('rows,previous', [(1, 0), (2, 0), (8, 5), (16, 16)])
@pytest.mark.parametrize('compressed', [False, True])
def test_replay_excludes_poisoned_keys_and_uses_prompt_reduction(monkeypatch, chunk, rows, previous, compressed):
    start = 2*chunk-rows
    run, reference = fixture(monkeypatch, start, rows, start-previous, compressed)
    old_a, old_b = run(False, 2.), run(False, -2.)
    assert not torch.equal(old_a, old_b), 'fixture did not reproduce the stale-key defect'
    fixed_a, fixed_b = run(True, 2.), run(True, -2.)
    assert torch.equal(fixed_a, fixed_b), 'previous request changed corrected attention'
    assert torch.equal(fixed_a, reference()), 'short replay differs from the bounded prompt path'


@pytest.mark.parametrize('rows,floor', [(1, 0), (16, 0), (17, 2048), (33, 2048)])
def test_unaffected_ring_and_gather_paths_preserve_bits(monkeypatch, rows, floor):
    run, _ = fixture(monkeypatch, 2048, rows, floor, True)
    assert torch.equal(run(False, 2.), run(True, 2.))
