"""Verification and prompt scratch must never replace each other's graph buffers."""
from types import SimpleNamespace

import pytest

from tensorfold.cuda.exl3 import experts
from tensorfold.families.deepseek_v41.cuda.model import Model


def test_64_row_verification_reuses_decode_scratch_after_prompt_growth(monkeypatch):
    allocations = []

    def scratch(ex, **kwargs):
        result = SimpleNamespace(**kwargs)
        allocations.append(result)
        return result

    monkeypatch.setattr(experts, 'Scratch', scratch)
    model = SimpleNamespace(scratch={})
    layer = SimpleNamespace(experts=SimpleNamespace(count=257))
    get = lambda n, **kw: Model._moe_scratch(model, layer, n, 7, **kw)
    decode = get(6)
    assert decode.rows == 64 and not decode.prompt
    assert get(64, decode_window=True) is decode
    prompt = get(64)
    assert prompt is not decode and prompt.prompt
    bigger = get(512)
    assert bigger is not prompt and bigger.prompt
    assert get(32, decode_window=True) is get(64, decode_window=True) is decode
    assert len(allocations) == 3
    with pytest.raises(ValueError, match='1 to 64'):
        get(65, decode_window=True)
    assert len(allocations) == 3


@pytest.mark.parametrize('rows', [0, 129])
def test_explicit_decode_rejects_unsupported_rows_before_cuda(rows):
    with pytest.raises(ValueError, match='1 to 128'):
        experts.routed(None, None, None, None, None, None, rows, decode_window=True)


def test_explicit_decode_rejects_prompt_scratch_before_cuda():
    with pytest.raises(ValueError, match='fixed decode scratch'):
        experts.routed(None, None, None, None, SimpleNamespace(xg=None), None, 64, decode_window=True)
