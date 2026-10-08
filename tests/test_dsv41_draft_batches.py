"""Larger proposal batches never enter the prompt MoE during graph capture."""
from types import SimpleNamespace

import pytest
import torch

from tensorfold.families.deepseek_v41.cuda import dspark


@pytest.fixture
def leaves(monkeypatch):
    zero = torch.zeros
    monkeypatch.setattr(dspark.torch, 'zeros', lambda shape, **kw: zero(shape, **{**kw, 'device':'cpu'}))
    events = []

    class Leaf:
        def __init__(self, drafter, sc, dpool, streams, steps=None):
            assert streams * drafter.size < 64, 'would enter the capturing-unsafe prompt MoE'
            self.N, self.steps = streams, steps
            self.inputs = zero((3, streams), dtype=torch.long)
            self.tokens, self.q0, self.slots = self.inputs.unbind(0)
            self.graph_count = 0

        def capture(self, pool):
            events.append(('capture', self.N, self.inputs.tolist(), pool))
            self.graph_count = 1

        def run(self, tokens, q0, slots):
            events.append(('run', self.N, list(slots)))
            self.last_conf = [[float(t+s)] * self.steps for t, s in zip(tokens, slots)]
            return [[t*100+p+s] * self.steps for t, p, s in zip(tokens, q0, slots)]

    monkeypatch.setattr(dspark, 'BatchDraftGraph', Leaf)
    return events, Leaf


@pytest.mark.parametrize('streams, expected', [(1,[1]),(12,[12]),(13,[12,1]),(16,[12,4]),(25,[12,1]),(32,[12,8])])
def test_capture_and_replay_keep_global_stream_slots_and_confidence_in_order(leaves, streams, expected):
    events, Leaf = leaves
    graph = dspark.draft_graph(SimpleNamespace(size=5), None, None, streams, steps=1)
    values = [list(range(100,100+streams)), list(range(128,128+streams)), list(range(streams-1,-1,-1))]
    graph.inputs.copy_(torch.tensor(values))
    graph.capture('shared-pool')
    captures = [x for x in events if x[0]=='capture']
    assert [x[1] for x in captures] == expected
    assert all(x[3]=='shared-pool' for x in captures)
    for row in range(3):
        expected_rows = values[row][:12] + values[row][24:] if streams > 24 else values[row]
        assert sum([x[2][row] for x in captures], []) == expected_rows
    assert graph.graph_count == len(expected)
    output = graph.run(*values)
    assert output == [[t*100+p+s] for t,p,s in zip(*values)]
    assert graph.last_conf == [[float(t+s)] for t,s in zip(values[0],values[2])]
    assert isinstance(graph, Leaf) == (streams <= 12)
    # A second replay may contain different token positions and a different slot
    # permutation. The first returned Python results must survive reuse of leaves.
    before = [list(row) for row in output]
    again = graph.run([t+1 for t in values[0]], values[1][::-1], values[2][::-1])
    assert again != before and output == before


def test_block_width_controls_the_capture_boundary_and_steps_are_preserved(leaves):
    graph = dspark.draft_graph(SimpleNamespace(size=7), None, None, 13, steps=3)
    assert [g.N for _,g in graph.parts] == [9,4]
    assert all(g.steps==3 for _,g in graph.parts)


def test_invalid_batches_fail_before_replay(leaves):
    for streams,size in ((0,5),(1,64),(1,0)):
        with pytest.raises(ValueError,match='graph-safe batch'):
            dspark.draft_graph(SimpleNamespace(size=size),None,None,streams)
    g=dspark.draft_graph(SimpleNamespace(size=5),None,None,13,steps=1)
    with pytest.raises(ValueError,match='input lengths'):
        g.run([1]*13,[1]*12,[1]*13)


def test_leaf_shapes_are_shared_across_groups_and_captured_once(leaves):
    events, _ = leaves
    cache = {}
    graphs = [dspark.draft_graph(SimpleNamespace(size=5), None, None, n, steps=1, leaves=cache)
              for n in (13, 25, 32)]
    for graph in graphs:
        graph.capture('one-pool')
    assert len(cache) == 3  # sizes 12, 1 and 8
    assert [e[1] for e in events if e[0] == 'capture'] == [12,1,8]
    assert graphs[1].parts[0][1] is graphs[1].parts[1][1]
    assert graphs[0].parts[0][1] is graphs[2].parts[0][1]
    # A different Markov depth needs its own output/graph shape.
    deeper = dspark.draft_graph(SimpleNamespace(size=5), None, None, 12, steps=3, leaves=cache)
    assert deeper is not cache[(12,1)] and len(cache) == 4


def test_shallower_requests_reuse_warmed_longer_prefix_without_changing_proposals(leaves):
    events, _ = leaves
    cache = {}
    d = SimpleNamespace(size=5)
    for n in range(1,13):
        steps = min(5 if n<=2 else 3, 32//n-1)
        dspark.draft_graph(d,None,None,n,steps=steps,leaves=cache).capture('shared')
    assert len(cache)==12
    for n in range(13,33):
        graph = dspark.draft_graph(d,None,None,n,steps=1,leaves=cache)
        graph.capture('shared')
        values = [list(range(100,100+n)),list(range(1000,1000+n)),list(reversed(range(n)))]
        assert graph.run(*values)==[[t*100+p+s] for t,p,s in zip(*values)]
        assert graph.last_conf==[[float(t+s)] for t,s in zip(values[0],values[2])]
    assert len(cache)==12
    assert len([e for e in events if e[0]=='capture'])==12
    shorter = dspark.draft_graph(d,None,None,1,steps=1,leaves=cache)
    assert shorter.run([5],[128],[7])==[[635]]
    assert shorter.last_conf==[[12.0]]
    assert len(cache)==12
