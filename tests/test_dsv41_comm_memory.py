"""The rank-ordered reduction must preserve input values without a second copy."""
import pytest
import torch

from tensorfold.families.deepseek_v41.cuda.model import Comm


class Collective:
    def __init__(self, parts):
        self.parts=parts

    def all_gather(self, source, target):
        # No auxiliary GPU comparisons here: their temporary Boolean buffers
        # would contaminate the allocation measurement below.
        for i,part in enumerate(self.parts):
            target[i*source.numel():(i+1)*source.numel()].copy_(source if i==0 else part.reshape(-1))


@pytest.mark.parametrize('world',[1,2,3])
@pytest.mark.parametrize('strided',[False,True])
def test_sum_preserves_rank_order_inputs_and_independent_results(world,strided):
    # Cancellation makes a tree/reordered reduction observably wrong for world 3.
    x=torch.tensor([[1e20,1.,-1e20,17.],[3.,-2.,0.,-5.]],dtype=torch.float32)
    if strided:x=x.t()
    parts=[x,-x,torch.ones_like(x)][:world]
    before=[v.clone() for v in parts]
    expected=parts[0].clone()
    for part in parts[1:]:expected+=part
    comm=Comm(Collective(parts),world)
    got=comm.sum(x)
    assert torch.equal(got,expected)
    assert all(torch.equal(a,b) for a,b in zip(parts,before))
    if world>1:
        got.zero_()
        assert torch.equal(x,before[0])
        assert torch.equal(comm.sum(x),expected)


@pytest.mark.skipif(not torch.cuda.is_available(),reason='requires CUDA for allocation accounting')
@pytest.mark.parametrize('temporary_input',[False,True])
def test_engram_reduction_reduces_peak_with_retained_and_temporary_inputs(temporary_input):
    # Exactly the failed projection's shape; emulate the gather without network
    # timing, then compare identical ordered arithmetic and BF16 conversion.
    shape=(2048,25600)
    parts=[torch.full(shape,0.25,device='cuda'),torch.full(shape,-0.5,device='cuda')]
    comm=Comm(Collective(parts),2)

    def original(x):
        g=comm.gather(x);acc=g[0].clone();acc+=g[1]
        return acc

    peaks=[]
    for reduce in (original,comm.sum):
        torch.cuda.synchronize();torch.cuda.empty_cache()
        baseline=torch.cuda.memory_allocated();torch.cuda.reset_peak_memory_stats()
        # The serving call passes a temporary projection directly into sum().
        # Also cover a retained argument: the returned view holds the complete
        # gather until conversion, saving 100 MiB at peak in that case.
        out=reduce(parts[0].clone() if temporary_input else parts[0]).to(torch.bfloat16)
        torch.cuda.synchronize()
        peaks.append(torch.cuda.max_memory_allocated()-baseline)
        assert bool((out==-0.25).all())
        del out
    assert peaks[0]-peaks[1]>=(200 if temporary_input else 100)*2**20,peaks
    print('Engram reduction peak bytes (temporary input, original, in-place):',temporary_input,peaks)
