"""Pure, rank-deterministic proposal allocation within one target-row budget.

No timers, CUDA calls or mutable learned state. Costs come from a fixed model
shared by both ranks. This helper is opt-in at the serving integration point.
"""
from __future__ import annotations

import math
from collections.abc import Callable, Sequence


def sigmoid(value: float) -> float:
    if not math.isfinite(value):
        if value == math.inf:
            return 1.0
        if value == -math.inf:
            return 0.0
        raise ValueError('draft confidence must not be NaN')
    if value >= 0:
        return 1.0/(1.0+math.exp(-value))
    z = math.exp(value)
    return z/(1.0+z)


def select_depths(confidences: Sequence[Sequence[float]], caps: Sequence[int], *,
                  live: int, row_budget: int, forward_ms: Callable[[int], float],
                  draft_ms: float) -> list[int]:
    """Maximize expected emitted tokens / round cost, including ordinary streams.

    Each extra verified row contributes its prefix-survival probability. Those
    gains decrease within a stream, so descending marginal gains find the best
    allocation at each row count. Scan every feasible count, including zero
    proposals; prefer fewer rows on an exact tie. The drafter has already run,
    hence its fixed cost is charged even if all proposals are discarded.
    """
    if (len(confidences) != len(caps) or live < len(caps) or not 0 < live <= row_budget
            or not math.isfinite(draft_ms) or draft_ms < 0):
        raise ValueError('invalid drafting streams, row budget or drafter cost')
    gains = []
    for stream, (values, cap) in enumerate(zip(confidences, caps)):
        if not isinstance(cap, int) or not 0 <= cap <= len(values):
            raise ValueError('draft cap must fit the provided confidence prefix')
        survival = 1.0
        for depth in range(1, cap+1):
            survival *= sigmoid(float(values[depth-1]))
            gains.append((survival, depth, stream))
    gains.sort(key=lambda item:(-item[0], item[1], item[2]))
    def cost(rows):
        target = float(forward_ms(rows))
        value = target+draft_ms
        if not math.isfinite(value) or target <= 0:
            raise ValueError('round cost must be finite and positive')
        return value
    chosen = [0]*len(caps)
    best = chosen.copy()
    expected = float(live)
    score = expected/cost(live)
    for added, (gain, depth, stream) in enumerate(gains[:row_budget-live], 1):
        assert chosen[stream] == depth-1  # prefix precedence, including tied gains
        chosen[stream] = depth
        expected += gain
        value = expected/cost(live+added)
        if value > score:
            score, best = value, chosen.copy()
    return best


def interpolate(points: Sequence[tuple[int, float]], coordinate: int) -> float:
    """Piecewise linear costs, clamped to the measured range at its endpoints."""
    if not points:
        raise ValueError('cost curve is empty')
    if coordinate <= points[0][0]:
        return float(points[0][1])
    for (a,x), (b,y) in zip(points, points[1:]):
        if coordinate <= b:
            return x+(y-x)*(coordinate-a)/(b-a)
    return float(points[-1][1])


class CostModel:
    """Validated fixed calibration curves; interpolation uses no rank-local state."""

    def __init__(self, value: dict):
        self.schema=value.get('schema')
        if self.schema not in (1,2):
            raise ValueError('unsupported draft cost model schema')
        def points(rows):
            out = [(int(x),float(y)) for x,y in rows]
            if (not out or any(x<=0 or not math.isfinite(y) or y<=0 for x,y in out)
                    or any(a[0]>=b[0] for a,b in zip(out,out[1:]))):
                raise ValueError('cost curves need increasing positive coordinates and finite positive costs')
            return tuple(out)
        def curves(row):
            out={key:points(row[key]) for key in ('sampling_ms','draft_ms')}
            if self.schema==1:
                out['forward_ms']=points(row['forward_ms'])
            else:
                grid=tuple((int(cell['live']),points(cell['points'])) for cell in row['forward_by_live'])
                if (not grid or any(live<=0 or ps[0][0]!=live for live,ps in grid)
                        or any(a[0]>=b[0] for a,b in zip(grid,grid[1:]))):
                    raise ValueError('forward stream counts must increase and include their ordinary reference')
                covered=0
                for lo,hi in sorted((ps[0][0],ps[-1][0]) for _,ps in grid):
                    if lo>covered+1:
                        raise ValueError('forward row coverage has a gap')
                    covered=max(covered,hi)
                out['forward_by_live']=grid
            return out
        self.contexts=tuple((int(row['tokens']),curves(row)) for row in value['contexts'])
        if (not self.contexts or self.contexts[0][0]<=0
                or any(a[0]>=b[0] for a,b in zip(self.contexts,self.contexts[1:]))):
            raise ValueError('cost contexts must increase')
        if self.schema==1:
            if any(curves['forward_ms'][0][0]!=1 for _,curves in self.contexts):
                raise ValueError('forward cost curves must include the one-row reference')
            self.max_rows=min(curves['forward_ms'][-1][0] for _,curves in self.contexts)
        else:
            self.max_rows=min(max(ps[-1][0] for _,ps in curves['forward_by_live']) for _,curves in self.contexts)
            self.max_live=min(curves['forward_by_live'][-1][0] for _,curves in self.contexts)
            self._forward_tables={}
            for n,curves in self.contexts:
                self._forward_tables[n]={}
                for live in range(1,self.max_live+1):
                    values=[]
                    for rows in range(live,self.max_rows+1):
                        covered=[(count,interpolate(ps,rows)) for count,ps in curves['forward_by_live']
                                 if ps[0][0]<=rows<=ps[-1][0]]
                        estimate=interpolate(covered,live)
                        # The set of covering curves changes at row boundaries.
                        # Prevent an interpolation discontinuity from claiming
                        # that adding proposals makes the target pass cheaper.
                        values.append(max(values[-1] if values else 0.,estimate))
                    self._forward_tables[n][live]=tuple(values)

    def _cost(self, kind: str, coordinate: int, context: int) -> float:
        return interpolate([(n,interpolate(curves[kind],coordinate)) for n,curves in self.contexts],context)

    def forward(self, rows: int, context: int, live: int | None = None) -> float:
        if not 1<=rows<=self.max_rows:
            raise ValueError('verification rows exceed calibrated cost coverage')
        if self.schema==1:
            return self._cost('forward_ms',rows,context)
        if live is None or not 1<=live<=min(rows,self.max_live):
            raise ValueError('forward costs need the actual live-stream count')
        return interpolate([(n,self._forward_tables[n][live][rows-live]) for n,_ in self.contexts],context)

    def sampling(self, live: int, context: int) -> float:
        return self._cost('sampling_ms',live,context)

    def draft(self, drafting: int, context: int) -> float:
        return self._cost('draft_ms',drafting,context) if drafting else 0.0
