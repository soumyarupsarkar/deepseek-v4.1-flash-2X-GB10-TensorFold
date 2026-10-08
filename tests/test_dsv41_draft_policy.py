"""Round allocation agrees with exhaustive optima, respects caps and ranks."""
import itertools
import math
import random

import pytest

from tensorfold.families.deepseek_v41.cuda.draft_policy import CostModel, interpolate, select_depths, sigmoid


def expected(conf, depths, live):
    result = float(live)
    for row,k in zip(conf,depths):
        survival = 1.0
        for value in row[:k]:
            survival *= sigmoid(value)
            result += survival
    return result


def test_allocation_matches_exhaustive_search_with_ordinary_streams_and_nonlinear_costs():
    rng = random.Random(7712)
    for _ in range(120):
        n = rng.randrange(1,5)
        live = n+rng.randrange(3)
        caps = [rng.randrange(4) for _ in range(n)]
        conf = [[rng.uniform(-7,7) for _ in range(k)] for k in caps]
        budget = live+rng.randrange(8)
        draft = rng.uniform(0,10)
        overhead = rng.uniform(5,30)
        slope = rng.uniform(.5,5)
        forward = lambda rows:overhead+slope*rows+0.07*rows**2
        got = select_depths(conf,caps,live=live,row_budget=budget,forward_ms=forward,draft_ms=draft)
        choices = [x for x in itertools.product(*(range(k+1) for k in caps)) if live+sum(x)<=budget]
        score = lambda x:expected(conf,x,live)/(draft+forward(live+sum(x)))
        assert score(got) == pytest.approx(max(map(score,choices)),rel=1e-12,abs=1e-12)
        assert live+sum(got)<=budget
        assert got == select_depths(conf,caps,live=live,row_budget=budget,forward_ms=forward,draft_ms=draft)


def test_every_stream_can_draft_but_the_complete_round_budget_is_never_exceeded():
    assert select_depths([[20.]]*32,[1]*32,live=32,row_budget=64,
                         forward_ms=lambda rows:100+rows,draft_ms=10)==[1]*32
    got=select_depths([[20.]*5]*32,[5]*32,live=32,row_budget=64,
                      forward_ms=lambda rows:100+rows,draft_ms=10)
    assert got==[1]*32
    assert select_depths([[-100.]*5]*4,[5]*4,live=4,row_budget=32,
                         forward_ms=lambda rows:rows*10,draft_ms=3.5)==[0]*4


def test_exact_ties_prefer_fewer_rows_and_prefix_order_survives_extreme_logits():
    assert select_depths([[math.inf]*5]*2,[5]*2,live=2,row_budget=12,
                         forward_ms=float,draft_ms=0)==[0,0]
    assert select_depths([[math.inf]*5]*2,[5]*2,live=2,row_budget=5,
                         forward_ms=lambda rows:1,draft_ms=0)==[2,1]
    assert sigmoid(-math.inf)==0 and sigmoid(math.inf)==1
    with pytest.raises(ValueError,match='NaN'):
        sigmoid(math.nan)


def test_invalid_budgets_and_costs_fail_before_returning_a_policy():
    for args in (dict(live=0,row_budget=32),dict(live=33,row_budget=32)):
        with pytest.raises(ValueError):
            select_depths([[1.]],[1],**args,forward_ms=lambda _:1,draft_ms=0)
    with pytest.raises(ValueError):
        select_depths([[1.]],[2],live=1,row_budget=32,forward_ms=lambda _:1,draft_ms=0)
    with pytest.raises(ValueError):
        select_depths([[1.]],[1],live=1,row_budget=32,forward_ms=lambda _:math.nan,draft_ms=0)


def test_curve_interpolation_clamps_outside_measured_context_or_row_range():
    points=[(1024,10.),(32768,20.),(262144,40.)]
    assert interpolate(points,100)==10
    assert interpolate(points,262144)==40
    assert interpolate(points,1048576)==40
    assert interpolate(points,(1024+32768)//2)==15


def cost_model():
    return dict(schema=1,contexts=[dict(tokens=n,forward_ms=[[1,10.*scale],[64,100.*scale]],
                sampling_ms=[[1,1.],[32,4.]],draft_ms=[[1,3.],[32,12.]])
                for n,scale in ((1024,1),(32768,2))])


def test_fixed_model_interpolates_context_and_rows_and_rejects_invalid_coverage():
    value=cost_model()
    m=CostModel(value)
    assert m.max_rows==64
    assert m.forward(1,1024)==10 and m.forward(1,32768)==20
    assert m.forward(1,(1024+32768)//2)==15
    assert m.forward(64,1048576)==200
    assert m.draft(0,100)==0 and m.draft(32,100)==12
    with pytest.raises(ValueError,match='coverage'):
        m.forward(65,1024)
    value['contexts'][0]['forward_ms']=[[1,math.nan],[64,100]]
    with pytest.raises(ValueError,match='finite'):
        CostModel(value)
    value=cost_model()
    value['contexts'].reverse()
    with pytest.raises(ValueError,match='increase'):
        CostModel(value)


def test_decoder_allocation_maps_stream_ids_and_leaves_room_for_the_pending_token(monkeypatch):
    from types import SimpleNamespace as NS
    from tensorfold.families.deepseek_v41.cuda import multi
    d=multi.MultiDecoder.__new__(multi.MultiDecoder)
    d.max_rows=8
    monkeypatch.setattr(multi,'COST_MODEL',CostModel(cost_model()))
    live=[NS(sid=sid,prompt=[0]*1024,count=count,out=out)
          for sid,count,out in ((91,20,[]),(12,1,[]),(73,3,[]))]
    got=d._budget_k(live,[live[0],live[2]],[[20.]*5,[20.]*5],5)
    assert set(got)=={91,73} and 0<=got[73]<=2
    assert len(live)+sum(got.values())<=8
    assert d._budget_k(live,[live[1]],[[20.]*5],5)=={12:0}
