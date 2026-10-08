"""One constrained token at a time, with rank agreement at safe request boundaries.

The model forward has completed before masks or matchers run. Grammar failures
are exchanged before another forward, so both ranks end only that request.
Transport/CUDA failures still propagate and poison the paired runtime.
"""
from __future__ import annotations

import torch

from tensorfold.engine import grammar
from tensorfold.server.errors import RequestError


def _exchange(engine, values: list[int], device="cuda") -> list[list[int]]:
    if engine.world == 1:
        return [values]
    # Token IDs fit exactly in fp32; this uses the same small-message fabric as
    # the existing step agreement, outside any captured CUDA graph.
    tensor = torch.tensor(values, dtype=torch.float32, device=device)
    return [[int(v) for v in row] for row in engine.model.comm.gather(tensor).tolist()]


def ready(engine, constraint, packed: list[int]):
    """Compile the follower's grammar before allocating a slot; agree on errors."""
    if not packed:
        return None
    error = None
    try:
        if constraint is None:
            constraint = grammar.compiler(engine, engine.model_dir, engine.eos).follow(packed)
        if grammar.pack(constraint) != packed:
            raise grammar.GrammarError("the ranks received different grammar specifications")
    except (RequestError, grammar.GrammarError, ValueError) as exc:
        error = exc
    states = _exchange(engine, [int(error is not None)])
    if any(row[0] for row in states):
        raise grammar.GrammarError("the request's grammar could not be prepared on every rank") from error
    return constraint


@torch.inference_mode()
def sample(engine, logits, positions, sampling, constraint):
    """Sample and commit one grammar token; failures end this request on all ranks."""
    if constraint is None:
        return engine._sample(logits, positions, sampling)
    if logits.shape[0] != 1 or len(positions) != 1:
        raise ValueError("constrained DeepSeek streams must have speculative drafting disabled")
    error, token, finished = None, -1, False
    try:
        # Forward/graph replay returns inference tensors. The scheduler itself
        # runs under no_grad, which does not permit their in-place masking.
        logits = constraint.mask(logits)
        if not bool(torch.isfinite(logits).any()):
            raise grammar.GrammarError("the grammar permits no finite next-token logit")
        token = engine._sample(logits, positions, sampling)[0]
        constraint.advance([token])
        finished = constraint.finished
    except grammar.GrammarError as exc:
        error = exc
    states = _exchange(engine, [int(error is not None), token, int(finished)], logits.device)
    if any(row[0] for row in states):
        raise grammar.GrammarError("the reply's grammar failed on a rank; this request has ended") from error
    if any(row != states[0] for row in states):
        raise grammar.GrammarError("the ranks disagreed on a constrained token; this request has ended")
    return [token]
