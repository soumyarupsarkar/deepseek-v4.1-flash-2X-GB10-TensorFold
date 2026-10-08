"""A reproducible qualification ceiling may tighten, never relax, the host floor."""
import io
from types import SimpleNamespace

import pytest
import torch

from tensorfold.families.deepseek_v41.cuda.engine import DsEngine


@pytest.mark.parametrize('asked,expected', [(None,104),('103',103),('120',104)])
def test_explicit_budget_never_spends_the_host_reserve(monkeypatch,asked,expected):
    gib=2**30
    monkeypatch.setenv('TF_DS_MEM_FLOOR_GIB','4')
    if asked is None:
        monkeypatch.delenv('TF_DS_ALLOCATOR_LIMIT_GIB',raising=False)
    else:
        monkeypatch.setenv('TF_DS_ALLOCATOR_LIMIT_GIB',asked)
    monkeypatch.setattr('builtins.open',lambda *a,**kw:io.StringIO('MemAvailable: 8388608 kB\n'))
    monkeypatch.setattr(torch.cuda,'synchronize',lambda:None)
    monkeypatch.setattr(torch.cuda,'mem_get_info',lambda:(8*gib,128*gib))
    monkeypatch.setattr(torch.cuda,'memory_reserved',lambda:100*gib)
    monkeypatch.setattr(torch.cuda,'memory_allocated',lambda:99*gib)
    limits=[]
    monkeypatch.setattr(torch.cuda,'set_per_process_memory_fraction',limits.append)
    e=SimpleNamespace(rank=0,capacity_plan={})
    DsEngine._memory_ceiling(e)
    assert limits==[expected/128]
    assert e.capacity_plan['torch_allocator_ceiling_bytes']==expected*gib
    assert e.capacity_plan['host_floor_bytes']==4*gib
