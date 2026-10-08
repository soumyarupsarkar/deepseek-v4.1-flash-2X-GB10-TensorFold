"""Bound decode graph widths so serving cannot accumulate unbudgeted captures.

The bounded-width, widest-first shared-pool approach follows urtho/TensorFold
8b05ee70ef2891c579ce7f3292a65dfd39fe600c (Apache-2.0), cuda/serial.py and
cuda/engine.py. Graph executable memory is outside PyTorch's allocator; warming
the entire selected family before setting its ceiling accounts for both.
"""
from __future__ import annotations


def widths(spec: str | None, cap: int) -> tuple[int, ...]:
    """Empty spec keeps the historical power-of-two policy; ``0`` is full only.

    Always include the request position cap, independently of aggregate pool
    size. Concurrent verification clamps drafts to the remaining reply budget.
    Including speculative scratch padding here would enlarge power-of-two
    selection workspaces at the native million-token boundary.
    """
    if not spec:
        return ()
    values = [int(word.strip()) for word in spec.split(',')]
    if any(v < 0 for v in values):
        raise ValueError('TF_DS_GRAPH_BUCKETS must contain nonnegative widths')
    return tuple(sorted({v for v in values if 0 < v < cap} | {cap}))


def select(deepest: int, choices: tuple[int, ...]) -> int:
    for width in choices:
        if deepest <= width:
            return width
    raise ValueError(f'decode position {deepest} exceeds graph position cap {choices[-1]}')
