"""Private rotating monitor evidence; no prompts, responses, argv or environment."""
from collections import deque
import json
import os
from pathlib import Path
import time

HOST_PROBE = Path(__file__).with_name('memory_probe.py').read_text()
MAX_BYTES = 4*2**20
BACKUPS = 7


def host_sample(pair, host, pid, *, floor_bytes, detail=False):
    args = ['sudo', '-n', 'python3', '-B', '-', '--pid', str(pid),
            '--warning-bytes', str(floor_bytes+2**30)]
    if detail:
        args.append('--detail')
    return json.loads(pair.run(host, args, input=HOST_PROBE, timeout=20).stdout)


def numeric(values):
    return {k: v for k, v in values.items() if type(v) in (int, float, bool) or v is None}


def health_sample(health):
    # Health extensions may contain arbitrary text or large arrays: allowlist
    # sections and scalar numbers instead of persisting the complete response.
    result = {k: health[k] for k in ('ok', 'busy', 'requests_running', 'requests_total',
              'completion_tokens_total', 'prompt_tokens_total', 'cached_tokens_total')
              if k in health and type(health[k]) in (bool, int, float)}
    for key in ('streams', 'scheduler', 'progress'):
        if isinstance(health.get(key), dict):
            result[key] = numeric(health[key])
    if isinstance(health.get('memory'), dict):
        result['memory'] = numeric(health['memory'])
        for key in ('kv_pool', 'retention'):
            if isinstance(health['memory'].get(key), dict):
                result['memory'][key] = numeric(health['memory'][key])
    return result


class History:
    """At most 64 MiB on disk, plus twelve recent samples in memory.

    Full samples are written each watchdog cycle. A separate minute series
    survives longer than the high-resolution pre-fault window. Recording errors
    are handled by the caller and never suppress the paired shutdown.
    """
    def __init__(self, root, *, max_bytes=MAX_BYTES, backups=BACKUPS):
        self.root = Path(root)
        self.max_bytes, self.backups = max_bytes, backups
        self.recent = deque(maxlen=12)
        self.next_trend = 0.0

    def _append(self, name, record):
        line = (json.dumps(record, sort_keys=True, separators=(',', ':'), allow_nan=False)+'\n').encode()
        if len(line) > min(128*1024, self.max_bytes):
            raise ValueError('Memory sample exceeds bounded record size')
        self.root.mkdir(mode=0o700, parents=True, exist_ok=True)
        if self.root.is_symlink():
            raise ValueError('Memory history directory is redirected')
        path = self.root/(name+'.jsonl')
        paths = [path] + [self.root/f'{name}.{i}.jsonl' for i in range(1, self.backups+1)]
        if any(p.is_symlink() for p in paths):
            raise ValueError('Memory history file is redirected')
        if path.exists() and path.stat().st_size+len(line) > self.max_bytes:
            paths[-1].unlink(missing_ok=True)
            for index in range(len(paths)-2, -1, -1):
                if paths[index].exists():
                    paths[index].replace(paths[index+1])
        fd = os.open(path, os.O_WRONLY | os.O_APPEND | os.O_CREAT | os.O_NOFOLLOW, 0o600)
        with os.fdopen(fd, 'ab') as out:
            out.write(line)

    def append(self, record):
        self.recent.append(record)
        self._append('samples', record)
        moment = time.monotonic()
        if moment >= self.next_trend:
            self._append('minutes', record)
            self.next_trend = moment+60
