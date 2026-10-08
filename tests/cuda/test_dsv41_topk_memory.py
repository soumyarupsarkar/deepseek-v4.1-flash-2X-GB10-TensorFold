"""Bound prompt-index selection memory without changing score/index ordering."""
import pytest
import torch

from tensorfold.families.deepseek_v41.cuda import kernels as K


def reference(score, k):
    bits = (score + 0.0).view(torch.int32)
    ordered = torch.where(bits < 0, bits ^ 0x7FFFFFFF, bits).to(torch.int64)
    keys = (ordered << 32) | (0xFFFFFFFF - torch.arange(score.shape[-1], device=score.device, dtype=torch.int64))
    top = keys.topk(k, dim=-1, sorted=False).values
    return (0xFFFFFFFF - (top & 0xFFFFFFFF)).sort(dim=-1).values


@pytest.mark.parametrize('rows,width,k', [(1,1,1), (19,137,17), (33,1024,512),
    (1024,16384,512), (16,524288,512)])
def test_prompt_selection_matches_original(rows, width, k):
    torch.manual_seed(62432)
    score = torch.randn((rows,width), device='cuda')
    score[:,::7] = 0.0
    score[:,1::7] = -0.0
    score[:,2::7] = float('-inf')
    score[:,3::7] = float('inf')
    score[:,4::7] = 0.5  # tied finite scores, signed zeros and infinities
    expected = reference(score,k)
    assert torch.equal(K.topk_indices(score,k), expected)
    assert torch.equal(K.topk_indices(score[:1],k), expected[:1])


def test_selection_reduces_peak_scratch():
    score = torch.randn((1024,16384), device='cuda')
    K.topk_indices(score,512)  # compile outside the measurement
    torch.cuda.synchronize()
    def peak(fn):
        torch.cuda.empty_cache()
        baseline = torch.cuda.memory_allocated()
        torch.cuda.reset_peak_memory_stats()
        value = fn(score,512)
        torch.cuda.synchronize()
        used = torch.cuda.max_memory_allocated() - baseline
        del value
        return used
    original, bounded = peak(reference), peak(K.topk_indices)
    print(f'topk scratch bytes: original={original}, bounded={bounded}', flush=True)
    assert original - bounded > 256 * 2**20
    assert bounded < 64 * 2**20


def test_captured_selection_replays_new_scores():
    score = torch.randn((33,1024), device='cuda')
    side = torch.cuda.Stream()
    side.wait_stream(torch.cuda.current_stream())
    with torch.cuda.stream(side):
        K.topk_indices(score,128)
    torch.cuda.current_stream().wait_stream(side)
    graph = torch.cuda.CUDAGraph()
    with torch.cuda.graph(graph):
        out = K.topk_indices(score,128)
    for value in (0.,1.,-1.):
        score[:,::2] = value
        graph.replay()
        assert torch.equal(out,reference(score,128))
