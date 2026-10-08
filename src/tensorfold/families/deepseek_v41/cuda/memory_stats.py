"""Allocation diagnostics for the TP2 lane; no prompt contents or token IDs."""
from __future__ import annotations

import json
import os
import sys
import traceback

import torch


def tensor_bytes(values) -> int:
    """Unique tensor storage bytes, including shared prefix-snapshot references."""
    seen = set()
    total = 0
    def visit(value):
        nonlocal total
        if isinstance(value, torch.Tensor):
            storage = value.untyped_storage()
            key = (str(value.device), storage.data_ptr())
            if key not in seen:
                seen.add(key)
                total += storage.nbytes()
        elif isinstance(value, dict):
            for item in list(value.values()):
                visit(item)
        elif isinstance(value, (list, tuple)):
            for item in value:
                visit(item)
    visit(values)
    return total


def snapshot(decoder) -> dict:
    stats = torch.cuda.memory_stats()
    streams = list(decoder.streams.values()) + list(decoder.filling)
    kept = list(decoder.kept.values())
    snaps = [getattr(s, 'snaps', {}) for s in streams] + [k.snaps for k in kept]
    graphs = dict(decoder.runner.graphs or {})
    return dict(allocated_bytes=torch.cuda.memory_allocated(),
                reserved_bytes=torch.cuda.memory_reserved(),
                peak_allocated_bytes=torch.cuda.max_memory_allocated(),
                inactive_split_bytes=stats.get('inactive_split_bytes.all.current', 0),
                allocation_retries=stats.get('num_alloc_retries', 0),
                allocation_ooms=stats.get('num_ooms', 0),
                snapshot_bytes=tensor_bytes(snaps),
                snapshot_references=sum(len(v or {}) for v in snaps),
                kv_pool=getattr(decoder, '_pool_snapshot', None),
                draft_calibration=dict(getattr(decoder, 'calibration', {})),
                draft_depth_histogram={str(k): list(v) for k, v in list(getattr(decoder, 'k_hist', {}).items())},
                kept_prompts=len(kept), prefilling=len(decoder.filling), decoding=len(decoder.streams),
                retention=dict(getattr(decoder, 'retention_config', {})),
                round_graphs=len(graphs), round_graph_captures=decoder.runner.captures,
                round_graph_widths=sorted({key[1] for key in graphs}),
                round_graphs_sealed=decoder.runner.sealed,
                drafter_graphs=len(decoder.drafters),
                drafter_cuda_graphs=sum(g.graph_count for g in getattr(decoder, 'draft_leaves', {}).values()),
                peak_drafting_streams=getattr(decoder, 'peak_drafting_streams', 0),
                verification_batches_total=getattr(decoder, 'verification_batches_total', 0),
                max_verification_batches=getattr(decoder, 'max_verification_batches', 0),
                peak_verification_rows=getattr(decoder, 'peak_verification_rows', 0))


def trace(decoder, stage: str, **fields) -> None:
    if os.environ.get('TF_DS_MEMORY_TRACE') == '1':
        print('[tensorfold-memory] ' + json.dumps(dict(rank=decoder.e.rank, stage=stage,
              **snapshot(decoder), **fields), sort_keys=True), flush=True)


def failure(decoder, exc: BaseException) -> None:
    """Capture the originating stack before request threads re-raise the exception."""
    if getattr(decoder, '_memory_failure_recorded', False):
        return
    decoder._memory_failure_recorded = True
    print(f'[tensorfold] originating failure on rank {decoder.e.rank}:', file=sys.stderr, flush=True)
    traceback.print_exception(type(exc), exc, exc.__traceback__, file=sys.stderr)
    try:
        print('[tensorfold-memory] ' + json.dumps(dict(rank=decoder.e.rank, stage='failure',
              **snapshot(decoder)), sort_keys=True), file=sys.stderr, flush=True)
    except Exception:
        pass
