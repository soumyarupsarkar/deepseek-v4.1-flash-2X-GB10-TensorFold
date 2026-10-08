"""The decode read ring must fit an entire target window, including both row tables."""
import os

import pytest
import torch

from tensorfold.families.deepseek_v41.cuda.model import _engram_aio_slots


@pytest.mark.parametrize('rows,columns,expected', [(16,12,1024),(32,12,1024),(64,12,2048),(64,24,4096)])
def test_ring_fits_weight_and_scale_reads_without_changing_smaller_defaults(rows, columns, expected):
    assert _engram_aio_slots(rows,columns)==expected
    assert _engram_aio_slots(rows,columns)>=2*rows*columns


@pytest.mark.parametrize('rows,columns',[(0,12),(64,0),(-1,12)])
def test_invalid_ring_dimensions(rows,columns):
    with pytest.raises(ValueError,match='positive'):
        _engram_aio_slots(rows,columns)


@pytest.mark.skipif(os.environ.get('TF_TEST_ENGRAM_AIO')!='1',reason='explicit Linux O_DIRECT integration test')
def test_full_64_row_batches_wrap_the_aio_ring_and_preserve_both_tables(tmp_path):
    from tensorfold.families.deepseek_v41.cuda.model import _engram_io

    io=_engram_io()
    assert io.aio_init(_engram_aio_slots(64,12))
    rows,count=8192,64*12
    tables=[torch.arange(rows*width,dtype=torch.int64).remainder(251).byte().reshape(rows,width)
            for width in (256,8)]
    offsets=(513,1037)
    fds=[]
    try:
        for i,(table,offset) in enumerate(zip(tables,offsets)):
            path=tmp_path/f'table-{i}.bin'
            path.write_bytes(b'h'*offset+table.numpy().tobytes()+bytes(8192))
            fds.append(os.open(path,os.O_RDONLY|os.O_DIRECT))
        for trial in range(4):
            pending=[]
            # Each submission is 1536 reads. The second must reap overlaps in
            # the 2048-slot ring before reusing bounce pages from the first.
            for side in range(2):
                ids=((torch.arange(count)+trial*191+side*79)*17)%rows
                outputs=[torch.empty((count,t.shape[1]),dtype=torch.uint8) for t in tables]
                batch=io.aio_start(fds[0],offsets[0],256,fds[1],offsets[1],8,ids,*outputs,1)
                pending.append((batch,ids,outputs))
            for batch,ids,outputs in reversed(pending):
                io.aio_wait(batch)
                assert all(torch.equal(out,table[ids]) for out,table in zip(outputs,tables))
    finally:
        for fd in fds:os.close(fd)
