"""Owner-thread KV accounting, without tensors, prompt contents or CUDA calls."""
from __future__ import annotations

import time


def snapshot(decoder) -> dict:
    """A completed scheduler step's disjoint extents and populated logical history.

    Prefix reuse copies positions into disjoint active extents: count each copy.
    The pending output token has not been forwarded yet. Compressed KV tensors
    encode these logical positions; this is not a dense bytes-per-token estimate.
    """
    filling = list(decoder.filling)
    decoding = list(decoder.streams.values())
    kept = list(decoder.kept.values())
    gaps = list(decoder.extents.gaps)
    free = sum(b-a for a, b in gaps)
    active = filling + decoding
    filled = sum(s.filled for s in filling)
    filled += sum(min(s.st.sc.length, len(s.prompt) + max(0, len(s.out)-1)) for s in decoding)
    retained = sum(k.top for k in kept)
    active_reserved = sum(s.size for s in active)
    retained_reserved = sum(k.size for k in kept)
    return dict(updated_monotonic_s=time.monotonic(), allocator_rows=decoder.extents.total,
                reserved_rows=decoder.extents.total-free, active_reserved_rows=active_reserved,
                retained_reserved_rows=retained_reserved, free_rows=free,
                largest_free_extent_rows=max((b-a for a, b in gaps), default=0),
                free_extents=len(gaps), active_filled_tokens=filled,
                retained_prefix_tokens=retained, resident_logical_tokens=filled+retained,
                reserved_unfilled_rows=active_reserved+retained_reserved-filled-retained,
                active_requests=len(active), prefilling=len(filling), decoding=len(decoding),
                retained_prefixes=len(kept), free_slots=len(decoder.free),
                reserved_accounted_rows=active_reserved+retained_reserved)
