"""KV gauges count occupied logical positions, reservations and fragmentation separately."""
from types import SimpleNamespace as NS

from tensorfold.families.deepseek_v41.cuda.occupancy import snapshot
from tensorfold.families.deepseek_v41.cuda.multi import Extents
from tensorfold.cuda.scheduler import Scheduler, Waiting


def test_disjoint_copies_pending_output_and_fragmented_free_space():
    ex = Extents(16384)
    assert ex.take(4096) == 0
    assert ex.take(4096) == 4096
    assert ex.take(2048) == 8192
    assert ex.take(2048) == 10240
    ex.give(4096, 4096)
    # Same prefix copied into active and retained extents counts twice. The
    # fourth emitted token is pending, and speculative scratch is not history.
    d = NS(extents=ex, free=[2, 3],
           filling=[NS(size=4096, filled=512)],
           streams={1:NS(size=2048, prompt=[0]*1000, out=[1]*4, st=NS(sc=NS(length=1005)))},
           kept={2:NS(size=2048, top=1000)})
    before = snapshot(d)
    assert before['reserved_rows'] == before['reserved_accounted_rows'] == 8192
    assert before['free_rows'] == 8192 and before['largest_free_extent_rows'] == 4096
    assert before['active_filled_tokens'] == 1515
    assert before['resident_logical_tokens'] == 2515
    assert before['reserved_unfilled_rows'] == 5677
    d.filling.clear()
    assert before['prefilling'] == 1  # published snapshot does not retain live containers


def test_empty_pool_has_full_free_extent_without_resident_history():
    d = NS(extents=Extents(16384), free=list(range(4)), filling=[], streams={}, kept={})
    state = snapshot(d)
    assert state['resident_logical_tokens'] == state['reserved_rows'] == 0
    assert state['largest_free_extent_rows'] == state['free_rows'] == 16384
    assert state['free_slots'] == 4


def test_scheduler_reports_capacity_hold_and_admission_without_counting_stop_sentinel():
    scheduler = Scheduler.__new__(Scheduler)
    scheduler.waiting, scheduler.held = Waiting(), (object(), object())
    scheduler.admitting, scheduler.yields = True, 2
    scheduler.waiting.put((NS(background=False), object()))
    scheduler.waiting.put((NS(background=True), object()))
    scheduler.waiting.stop()
    assert scheduler.health_state() == dict(queued=3, waiting=2, held_for_capacity=1,
                                           admitting=1, background_yields=2)
