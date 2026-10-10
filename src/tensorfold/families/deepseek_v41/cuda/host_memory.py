"""Optional CPU-heap accounting and pressure trim, independent of CUDA/GC.

libc can retain freed native allocations after a large request. malloc_trim(0)
asks it to return unused pages; it cannot free live allocations. These counters
cover glibc, not every allocation in the process and not the CUDA allocator.
"""
from __future__ import annotations

import ctypes
import json
import math
import os
from pathlib import Path
import tempfile
import threading
import time


REPORT = Path('/tmp/tensorfold-host-memory.json')
INTERVAL = 5.0
HEAP_FIELDS = ('arena', 'ordblks', 'smblks', 'hblks', 'hblkhd',
               'usmblks', 'fsmblks', 'uordblks', 'fordblks', 'keepcost')


class Mallinfo2(ctypes.Structure):
    _fields_ = [(name, ctypes.c_size_t) for name in HEAP_FIELDS]


class LibcHeap:
    def __init__(self):
        self.libc = ctypes.CDLL('libc.so.6')
        self.libc.mallinfo2.argtypes = []
        self.libc.mallinfo2.restype = Mallinfo2
        self.libc.malloc_trim.argtypes = [ctypes.c_size_t]
        self.libc.malloc_trim.restype = ctypes.c_int

    def snapshot(self):
        info = self.libc.mallinfo2()
        return {'glibc_' + name: int(getattr(info, name)) for name in HEAP_FIELDS}

    def trim(self):
        return int(self.libc.malloc_trim(0))


def _proc_numbers(path, wanted):
    result = {}
    for line in path.read_text().splitlines():
        fields = line.split()
        if len(fields) == 3 and fields[0].rstrip(':') in wanted and fields[2] == 'kB':
            result[fields[0].rstrip(':')] = int(fields[1]) * 1024
    if result.keys() != wanted:
        raise ValueError('Required host-memory counters are unavailable')
    return result


def process_memory():
    # Read only numeric counters, never argv, environment or model inputs.
    return {**_proc_numbers(Path('/proc/meminfo'), {'MemAvailable'}),
            **_proc_numbers(Path('/proc/self/status'), {'RssAnon', 'VmSwap', 'VmRSS'})}


def _write(path, value):
    # One latest snapshot; private file, atomic replacement, no append log.
    data = json.dumps(value, separators=(',', ':'), allow_nan=False).encode()
    if len(data) > 8192:
        raise ValueError('Host-memory snapshot exceeds its bound')
    name = None
    try:
        with tempfile.NamedTemporaryFile(dir=path.parent, prefix='.tf-host-memory-', delete=False) as stream:
            name = stream.name
            os.fchmod(stream.fileno(), 0o600)
            stream.write(data)
        os.replace(name, path)  # Replaces a destination symlink, never follows it.
    finally:
        if name is not None:
            try:
                os.unlink(name)
            except FileNotFoundError:
                pass


class HostMemoryMonitor:
    """One CPU-only daemon per process; it never enters a model collective."""
    def __init__(self, threshold_bytes, *, heap=None, memory=process_memory, report=REPORT):
        self.heap = heap if heap is not None else LibcHeap()
        self.memory, self.report = memory, report
        self.stopped = threading.Event()
        self.state = dict(schema=1, pid=os.getpid(), threshold_bytes=threshold_bytes,
                          interval_seconds=INTERVAL, samples=0, errors=0, write_errors=0,
                          trim_calls=0, trim_releases=0, sample_unix_ns=0)
        self.thread = None

    def snapshot(self):
        return {**self.memory(), **self.heap.snapshot()}

    def tick(self):
        try:
            before = self.snapshot()
            self.state.update(current=before, sample_unix_ns=time.time_ns())
            self.state['samples'] += 1
            if self.state['threshold_bytes'] > 0 and before['MemAvailable'] < self.state['threshold_bytes']:
                self.state['trim_calls'] += 1
                started = time.monotonic()
                result = self.heap.trim()
                elapsed = time.monotonic() - started
                self.state['trim_releases'] += int(result != 0)
                self.state.update(last_trim_unix_ns=time.time_ns(), last_trim_return=result,
                                  last_trim_seconds=elapsed, last_trim_before=before)
                self.state.pop('last_trim_after', None)
                after = self.snapshot()
                self.state.update(current=after, last_trim_after=after, sample_unix_ns=time.time_ns())
        except Exception:
            # Counters only: exception messages can contain paths or other data.
            # The independent paired watchdog remains responsible for stopping.
            self.state['errors'] += 1
        try:
            _write(self.report, self.state)
        except Exception:
            self.state['write_errors'] += 1

    def _run(self):
        while not self.stopped.is_set():
            self.tick()
            self.stopped.wait(INTERVAL)

    def start(self):
        self.thread = threading.Thread(target=self._run, name='tf-host-memory', daemon=True)
        self.thread.start()
        return self

    def stop(self):
        self.stopped.set()
        if self.thread is not None:
            self.thread.join(timeout=INTERVAL + 1)


_monitor = None
_lock = threading.Lock()


def start():
    """Default off. Stats alone use TF_DS_HOST_MEMORY_STATS=1 and a zero trim limit."""
    global _monitor
    threshold = float(os.environ.get('TF_DS_HOST_TRIM_GIB') or '0')
    if not math.isfinite(threshold) or not 0 <= threshold <= 128:
        raise ValueError('TF_DS_HOST_TRIM_GIB must be finite and between 0 and 128')
    stats = os.environ.get('TF_DS_HOST_MEMORY_STATS', '0')
    if stats not in ('0', '1'):
        raise ValueError('TF_DS_HOST_MEMORY_STATS must be 0 or 1')
    if threshold == 0 and stats == '0':
        return None
    with _lock:
        if _monitor is None or _monitor.state['pid'] != os.getpid():
            _monitor = HostMemoryMonitor(int(threshold * 2**30)).start()
        return _monitor
