"""Bounded completed-prefix retention preserves reuse and evicts whole histories."""
from types import SimpleNamespace as NS

import numpy as np
import pytest

from tensorfold.families.deepseek_v41.cuda import engine, multi
from tensorfold.families.deepseek_v41.ops import HostIds


@pytest.fixture
def recent(monkeypatch):
    monkeypatch.setattr(engine, 'PREFILL_CHUNK', 512)
    monkeypatch.setattr(multi, 'KEEP_MARK_POLICY', 'recent')
    monkeypatch.setattr(multi, 'KEEP_MARKS', 2)
    monkeypatch.setattr(multi, 'KEEP_ENTRIES', 32)
    monkeypatch.setattr(multi, 'KEEP', True)
    d = multi.MultiDecoder.__new__(multi.MultiDecoder)
    d.e, d.m = NS(replay_mode=True), NS(cfg=NS(window=512))
    d.kept, d.streams, d.filling, d.free = {}, {}, [], []
    d.next_kept, d.ticks = 32, 100
    return d


def test_two_checkpoints_reuse_the_continuation_and_replay_window_but_not_old_branches(recent):
    d = recent
    ids = np.arange(8192)
    available = {n:object() for n in d._marks(8192)}
    marks = d._kept_marks(available)
    assert marks == [7680, 8192]
    d.kept[0] = multi.Kept(0, 0, 8192, 8192, HostIds(ids),
                          {n:available[n] for n in marks}, True, ids, 1)
    # A new turn can resume at the old prompt's end. Repeating that prompt
    # leaves the replay window and uses the penultimate checkpoint instead.
    for length, cut in ((8704,8192),(8192,7680)):
        keys = np.arange(length)
        assert d._match(NS(prompt=keys), keys) == [0,cut]
    branch = np.concatenate((ids[:4096], np.arange(9000,13096)))
    assert d._match(NS(prompt=branch), branch) is None


def test_recent_is_strict_at_a_million_but_default_landmarks_remain_compatible(recent, monkeypatch):
    snaps = {n:object() for n in recent._marks(1048576)}
    assert sorted(snaps) == [1048064,1048576]  # prefill never allocates discarded landmarks
    assert recent._kept_marks(snaps) == [1048064,1048576]
    monkeypatch.setattr(multi, 'KEEP_MARK_POLICY', 'landmarks')
    monkeypatch.setattr(multi, 'KEEP_MARKS', 10)
    snaps = {n:object() for n in recent._marks(1048576)}
    expected = sorted({512*2**i for i in range(12)} | {1048064})
    assert recent._kept_marks(snaps) == expected


def fill_retained(d):
    d.extents = multi.Extents(36*4096)
    for i in range(32):
        base = d.extents.take(4096)
        keys = np.arange(4096)+i*10000
        d.kept[i] = multi.Kept(i, base, 4096, 4096, HostIds(keys),
                              {3584:object(),4096:object()}, True, keys, i)


def finished(d, keys):
    base = d.extents.take(8192)
    assert base is not None
    s = NS(sid=99, base=base, size=8192, keys=keys, prompt=keys, out=[1],
           snaps={n:object() for n in d._marks(len(keys))},
           st=NS(index=0, sc=NS(host=HostIds(keys),length=len(keys))))
    d.streams[s.sid] = s
    return s


def test_continuation_replaces_old_version_without_evicting_another_conversation(recent):
    d = recent
    fill_retained(d)
    s = finished(d, np.arange(4608))
    # Old 3584 checkpoint deliberately falls outside the newest two of the
    # continued prompt. It must not keep the obsolete conversation version.
    assert d._covered([s]) == [0]
    d._finish([s.sid], d._covered([s]))
    assert set(d.kept) == set(range(1,33))
    assert d.kept[32].top == 4608 and len(d.kept[32].snaps) == 2
    assert d.free == [0]
    assert d._pool_snapshot['reserved_rows'] == d._pool_snapshot['reserved_accounted_rows']


def test_thirty_third_distinct_prefix_evicts_least_recently_used_and_releases_extent(recent):
    d = recent
    fill_retained(d)
    d.kept[0].tick = 99  # most recently reused: entry one should leave first
    old_base = d.kept[1].base
    s = finished(d, np.arange(4608)+1000000)
    assert d._covered([s]) == []
    d._finish([s.sid])
    assert len(d.kept) == 32 and 0 in d.kept and 1 not in d.kept
    assert d.extents.take_at(old_base,4096)


def test_pool_pressure_can_evict_retained_prefixes_below_the_entry_limit(recent):
    d = recent
    fill_retained(d)
    d.kept[0].tick = 99
    # The remaining 16K cannot satisfy 20K. Space is obtained from older
    # contiguous retained extents while the recent prefix remains intact.
    assert d._room(20480)
    base, how = d._place(20480,None)
    assert base is not None and how == 'fresh'
    assert 0 in d.kept and len(d.kept) < 32
