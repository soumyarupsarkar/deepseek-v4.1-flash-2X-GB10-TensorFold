"""Independent per-request context and aggregate KV pool geometry, without CUDA."""
from __future__ import annotations


def plan(cfg, *, context: int, slots: int, pool_tokens: int, decode_rows: int = 16,
         native_context: int = 1048576, quantized: bool = True, align: int = 2048) -> dict:
    if not 1 <= context <= native_context:
        raise ValueError(f"per-request context must be between 1 and {native_context} tokens")
    if not 1 <= slots <= decode_rows:
        raise ValueError(f"parallel must be between 1 and the {decode_rows}-row decode capacity")
    if pool_tokens < context:
        raise ValueError("the shared KV pool must hold at least one full per-request context")
    # Reserve each stream's scratch positions and worst-case extent rounding.
    # User pool_tokens describes prompt/reply tokens, not allocator overhead.
    reserve = slots * (decode_rows + 12) + (slots - 1) * (align - 1)
    cap = -(-(pool_tokens + reserve) // align) * align
    comp = index = 0
    planes = []
    for layer in cfg.kv_sources:
        if layer >= cfg.n_layers:
            continue
        rows = cap // cfg.compress_ratios[layer] + 2
        comp += rows * (cfg.head_dim // 2 + cfg.head_dim // 16 if quantized else cfg.head_dim * 2)
        planes.extend([rows * cfg.head_dim // 2, rows * cfg.head_dim // 16] if quantized
                      else [rows * cfg.head_dim * 2])
        if layer in cfg.index_sources:
            index += rows * (cfg.idx_dim // 2 + cfg.idx_dim // 32 if quantized else cfg.idx_dim * 2)
            planes.extend([rows * cfg.idx_dim // 2, rows * cfg.idx_dim // 32] if quantized
                          else [rows * cfg.idx_dim * 2])
    rings = slots * cfg.n_layers * (cfg.window + 16) * cfg.head_dim * 2
    raw = slots * sum(layer < cfg.n_layers and cfg.compress_ratios[layer] > 1 for layer in cfg.kv_sources) \
        * 2 * 64 * cfg.head_dim * 4
    tokens = cap * 8
    return dict(per_request_tokens=context, shared_pool_tokens=pool_tokens, allocated_pool_rows=cap,
                parallel=slots, compressed_bytes=comp, index_bytes=index, window_ring_bytes=rings,
                compressor_ring_bytes=raw, token_ids_bytes=tokens,
                pool_bytes=comp + index + rings + raw + tokens, quantized=quantized, sparse_plane_bytes=planes)


def display_placement(planes: list[int], capacity: int, align: int = 256) -> int:
    """Exact bytes that the whole-tensor fallback allocator can place in display RAM."""
    used = placed = 0
    for size in planes:
        start = -(-used // align) * align
        if start + size <= capacity:
            used = start + size
            placed += size
    return placed
