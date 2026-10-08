"""Rank order and overwrite lifetime of the graph family's shared output plane."""
import pytest
import torch

from tensorfold.families.deepseek_v41.cuda.rounds import RoundOutputs


@pytest.mark.parametrize('world',[1,2,3])
def test_shared_logits_preserve_rank_order_and_require_copy_before_next_forward(world):
    outputs=RoundOutputs(64,world*7,9,device='cpu')
    base=outputs.logits.data_ptr()
    saved=[]
    for rows in (1,32,63,64,3):
        g=torch.arange(world*rows*7,dtype=torch.float32).reshape(world,rows,7)+rows
        expected=g.permute(1,0,2).reshape(rows,-1)
        result=outputs.store_logits(g)
        assert result.data_ptr()==base
        assert torch.equal(result,expected)
        saved.append((result.clone(),expected.clone()))
        outputs.taps[:rows].fill_(rows)
    outputs.logits.fill_(-1)
    assert all(torch.equal(a,b) for a,b in saved)


def test_invalid_shapes_fail_without_reallocating_outputs():
    outputs=RoundOutputs(64,12,0,device='cpu')
    assert outputs.taps is None
    before=outputs.logits.data_ptr()
    for shape in ((2,65,6),(2,64,7)):
        with pytest.raises(ValueError,match='fixed output plane'):
            outputs.store_logits(torch.empty(shape))
    assert outputs.logits.data_ptr()==before


@pytest.mark.skipif(not torch.cuda.is_available(),reason='CUDA graph capture and allocator accounting')
def test_64_graph_shapes_reuse_one_output_plane_and_replay_changed_values():
    outputs=RoundOutputs(64,131072,15360)
    source=torch.empty((2*64*65536,),dtype=torch.float32,device='cuda')
    before=torch.cuda.memory_allocated()
    graphs=[]
    for rows in range(64,0,-1):
        g=source[:2*rows*65536].view(2,rows,65536)
        outputs.store_logits(g)
        graph=torch.cuda.CUDAGraph()
        with torch.cuda.graph(graph):
            view=outputs.store_logits(g)
            outputs.taps[:rows].fill_(rows)
        graphs.append((rows,graph,g,view))
    torch.cuda.synchronize()
    # Retaining 64 independent logits planes would take over a GiB. Views of
    # the fixed output do not add that storage as graphs are captured.
    assert torch.cuda.memory_allocated()-before < 8*2**20
    for trial in range(3):
        source.copy_(torch.arange(source.numel(),device='cuda').float()+trial)
        for rows,graph,g,view in graphs[::7]:
            outputs.logits.fill_(float('nan'))
            graph.replay()
            torch.cuda.synchronize()
            assert torch.equal(view,g.permute(1,0,2).reshape(rows,-1))
            assert bool((outputs.taps[:rows]==rows).all())
