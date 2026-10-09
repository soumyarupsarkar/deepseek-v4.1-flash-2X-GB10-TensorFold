"""Deterministic metadata-only packing of a fragmented shared KV pool."""
from __future__ import annotations


def plan(total: int, align: int, active, retained, need: int) -> dict | None:
    """Pack live extents and retained prefixes to the left, evicting only as needed.

    Active entries are (stream id, base, size); retained entries additionally
    carry their LRU tick. Addresses and sizes are physical, aligned pool rows.
    A plan never moves an extent to the right or changes an active reservation.
    None means the request cannot fit even after evicting all retained prefixes.
    """
    if align <= 0 or total < 0 or total % align or need <= 0:
        raise ValueError('invalid KV compaction capacity or alignment')
    active, retained = list(active), list(retained)
    required = -(-need // align)*align
    blocks = []
    identifiers = set()
    for kind, entries in (('active', active), ('retained', retained)):
        for entry in entries:
            ident, base, size = entry[:3]
            if ((kind, ident) in identifiers or base < 0 or size <= 0 or
                    base % align or size % align or base+size > total):
                raise ValueError('invalid KV extent in compaction plan')
            identifiers.add((kind, ident))
            blocks.append(dict(kind=kind,id=ident,base=base,size=size))
    blocks.sort(key=lambda b:b['base'])
    if any(a['base']+a['size'] > b['base'] for a,b in zip(blocks,blocks[1:])):
        raise ValueError('overlapping KV extents in compaction plan')
    used = sum(b['size'] for b in blocks)
    dropped = []
    for ident, base, size, tick in sorted(retained,key=lambda item:(item[3],item[0])):
        if used+required <= total:
            break
        dropped.append(ident)
        used -= size
    if used+required > total:
        return None
    removed = set(dropped)
    moves, cursor = [], 0
    for block in blocks:
        if block['kind']=='retained' and block['id'] in removed:
            continue
        if block['base'] != cursor:
            moves.append(dict(kind=block['kind'],id=block['id'],source=block['base'],
                              destination=cursor,size=block['size']))
        cursor += block['size']
    return dict(dropped=dropped,moves=moves,used_rows=cursor,free_rows=total-cursor)


def copy_range(tensor, source: int, destination: int, rows: int, max_temporary_bytes: int) -> None:
    """Tensor memmove with bounded clones, in the direction that preserves unread rows.

    This only enqueues ordinary tensor copies on the caller's stream. It does not
    allocate another KV pool or change storage referenced by captured graphs.
    """
    if rows < 0 or min(source,destination) < 0 or max(source,destination)+rows > tensor.shape[0]:
        raise ValueError('KV copy is outside its tensor')
    if max_temporary_bytes <= 0:
        raise ValueError('KV copy needs a positive temporary-memory bound')
    if source == destination or rows == 0:
        return
    overlap = source < destination+rows and destination < source+rows
    if not overlap:
        tensor[destination:destination+rows].copy_(tensor[source:source+rows])
        return
    row_bytes = tensor[0].numel()*tensor.element_size()
    if row_bytes <= 0:
        raise ValueError('KV rows must contain data')
    chunk = max_temporary_bytes//row_bytes
    if chunk < 1:
        raise ValueError('one KV row exceeds the temporary-memory bound')
    offsets = range(0,rows,chunk)
    if destination > source:
        offsets = reversed(offsets)
    for offset in offsets:
        count = min(chunk,rows-offset)
        saved = tensor[source+offset:source+offset+count].clone()
        tensor[destination+offset:destination+offset+count].copy_(saved)
        del saved


__all__ = ['plan','copy_range']
