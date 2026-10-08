"""Bounded concurrent HTTP ranges with crash-resumable journals and full SHA256."""
import concurrent.futures
import hashlib
import json
import os
from pathlib import Path
import re
import threading
import time
import urllib.error
import urllib.request


def atomic(path, value):
    temporary = path.with_name(path.name+'.tmp')
    with temporary.open('w') as out:
        json.dump(value, out, sort_keys=True); out.flush(); os.fsync(out.fileno())
    temporary.replace(path)


def sha(path):
    value = hashlib.sha256()
    with path.open('rb') as source:
        while block := source.read(2**20):
            value.update(block)
            os.posix_fadvise(source.fileno(), source.tell()-len(block), len(block), os.POSIX_FADV_DONTNEED)
    return value.hexdigest()


def download(url, path, digest, size, *, workers=4, chunk_bytes=128*2**20, token=None):
    path = Path(path)
    if not re.fullmatch('[0-9a-f]{64}', digest) or type(size) is not int or size <= 0:
        raise ValueError('Pinned size and SHA256 required')
    if path.exists():
        if path.is_symlink() or path.stat().st_size != size or sha(path) != digest:
            raise ValueError('Existing asset differs; preserve it')
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    partial = path.with_name(path.name+'.download-part')
    journal = path.with_name(path.name+'.ranges.json')
    if partial.is_symlink() or journal.is_symlink():
        raise ValueError('Redirected partial download')
    pin = dict(url_sha256=hashlib.sha256(url.encode()).hexdigest(), sha256=digest, bytes=size)
    if journal.exists():
        state = json.loads(journal.read_text())
        if any(state.get(k) != v for k, v in pin.items()) or not partial.is_file():
            raise ValueError('Range journal belongs to different data')
        prefix = state['prefix']; chunk_bytes = state['chunk_bytes']
    else:
        prefix = partial.stat().st_size if partial.exists() else 0
        state = dict(**pin, prefix=prefix, chunk_bytes=chunk_bytes, complete=[])
        partial.touch(exist_ok=True)
        atomic(journal, state)
    if not 0 <= prefix <= size or partial.stat().st_size > size or chunk_bytes <= 0:
        raise ValueError('Invalid partial size or journal')
    ranges = [(start, min(start+chunk_bytes, size)-1) for start in range(prefix, size, chunk_bytes)]
    done = set(state['complete'])
    if not done <= set(range(len(ranges))):
        raise ValueError('Invalid completed ranges')
    guard = threading.Lock()
    fd = os.open(partial, os.O_RDWR | os.O_NOFOLLOW)
    try:
        def one(number):
            if number in done: return
            start, end = ranges[number]
            for attempt in range(6):
                try:
                    request = urllib.request.Request(url, headers={'Range':f'bytes={start}-{end}', 'Accept-Encoding':'identity'})
                    if token:
                        request.add_unredirected_header('Authorization', 'Bearer ' + token)
                    with urllib.request.urlopen(request, timeout=120) as response:
                        if response.status != 206 or response.headers.get('Content-Range') != f'bytes {start}-{end}/{size}':
                            raise ValueError('Server did not honor the exact HTTP range')
                        offset = start
                        while offset <= end:
                            block = response.read(min(2**20, end-offset+1))
                            if not block: raise ConnectionError('Truncated HTTP range')
                            view = memoryview(block)
                            while view:
                                wrote = os.pwrite(fd, view, offset)
                                if not wrote: raise OSError('Short disk write')
                                offset += wrote; view = view[wrote:]
                        if response.read(1): raise ValueError('Oversized HTTP range')
                    # A range is durable before its completion is journaled.
                    with guard:
                        os.fsync(fd); done.add(number)
                        state['complete'] = sorted(done); atomic(journal, state)
                    os.posix_fadvise(fd, start, end-start+1, os.POSIX_FADV_DONTNEED)
                    return
                except (urllib.error.URLError, TimeoutError, ConnectionError) as error:
                    if isinstance(error, urllib.error.HTTPError) and error.code not in (408,429,500,502,503,504): raise
                    if attempt == 5: raise
                    time.sleep(min(30, 2**attempt))
        with concurrent.futures.ThreadPoolExecutor(max_workers=workers) as pool:
            list(pool.map(one, range(len(ranges))))
    finally:
        os.close(fd)
    if partial.stat().st_size != size or sha(partial) != digest:
        raise ValueError('Completed range download failed full SHA256 verification')
    os.link(partial, path, follow_symlinks=False)
    partial.unlink(); journal.unlink()
    print(json.dumps(dict(stage='download_verified', file=path.name, bytes=size, transport=f'{workers} HTTP ranges')), flush=True)
