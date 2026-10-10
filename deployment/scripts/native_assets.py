"""Pinned native runtime inputs; the public kernel kit needs no HF credential."""
import concurrent.futures
import hashlib
import json
import subprocess
from pathlib import Path

from configuration import CONFIG, read
from assets import fetch_file, relative
from runtime import atomic, now


def kit_spec():
    spec = read(CONFIG/'native-inputs.json')['kernel_kit']
    payload = (CONFIG/relative(spec['files'])).read_bytes()
    if hashlib.sha256(payload).hexdigest() != spec['files_sha256']:
        raise ValueError('Native kit inventory differs from its pin')
    rows = json.loads(payload)
    seen = set()
    for row in rows:
        path = relative(row['path'])
        if len(path.parts) < 2 or path.parts[0] != 'kit' or row['path'] in seen:
            raise ValueError('Invalid or duplicate native kit entry')
        seen.add(row['path'])
    return spec, rows


def fetch_kit_root(root):
    """Acquire only the verified kit files into a dedicated directory."""
    root = Path(root)
    if root.is_symlink() or root.resolve() != root.absolute():
        raise ValueError('Native kit directory is redirected')
    spec, rows = kit_spec()
    def one(row):
        dest = root/Path(*relative(row['path']).parts[1:])
        if dest.resolve() != dest.absolute():
            raise ValueError('Native kit entry is redirected')
        fetch_file(spec, row, dest)
    with concurrent.futures.ThreadPoolExecutor(max_workers=4) as pool:
        list(pool.map(one, rows))
    return dict(files=len(rows), bytes=sum(row['size'] for row in rows), revision=spec['revision'])


VERIFY_KIT = r'''import hashlib,json,os,pathlib,sys
p=json.load(sys.stdin);root=pathlib.Path(p['root']);expected=p['files']
if root.is_symlink() or root.resolve()!=root:raise ValueError('Redirected native kit root')
actual={str(f.relative_to(root)) for f in root.rglob('*') if not f.is_dir() or f.is_symlink()}
if actual!=set(expected):raise ValueError('Native kit inventory differs')
out={}
for name,row in expected.items():
 f=root/name
 if not f.is_file() or f.is_symlink() or f.resolve()!=f:raise ValueError('Redirected native kit entry')
 s=f.stat();fp=[s.st_dev,s.st_ino,s.st_size,s.st_mtime_ns,s.st_ctime_ns]
 if s.st_size!=row['size']:raise ValueError('Native kit file size differs')
 if p['full']:
  h=hashlib.sha256()
  with f.open('rb') as stream:
   while block:=stream.read(2**20):
    h.update(block);os.posix_fadvise(stream.fileno(),stream.tell()-len(block),len(block),os.POSIX_FADV_DONTNEED)
  if h.hexdigest()!=row['sha256']:raise ValueError('Native kit digest differs')
 elif fp!=p['previous']['files'].get(name):raise ValueError('Verified native kit fingerprint changed')
 s=f.stat()
 if fp!=[s.st_dev,s.st_ino,s.st_size,s.st_mtime_ns,s.st_ctime_ns]:raise ValueError('Native kit changed during verification')
 out[name]=fp
print(json.dumps(out))
'''


def verify_kit(pair, host, full=False):
    spec, rows = kit_spec()
    receipt = pair.state/('native-kit-'+host+'.json')
    files = {str(Path(*relative(row['path']).parts[1:])): row for row in rows}
    previous = read(receipt) if not full else None
    if previous and previous['revision'] != spec['revision']:
        raise ValueError('Verified native kit revision changed')
    result = pair.run(host, ['python3', '-B', '-c', VERIFY_KIT], input=json.dumps(dict(
        root=pair.config[host]['data_root']+'/native-kit', files=files, full=full, previous=previous)), timeout=300)
    atomic(receipt, dict(time=now(), revision=spec['revision'], files=json.loads(result.stdout)))


def fetch_kit(pair):
    pair.roots('head')
    fetch_kit_root(Path(pair.config['head']['data_root'])/'native-kit')
    verify_kit(pair, 'head', full=True)


def replicate_kit(pair):
    for host in ('head','worker'):
        pair.roots(host)
    verify_kit(pair,'head',full=False)
    transport='ssh -o BatchMode=yes -o StrictHostKeyChecking=yes -o UpdateHostKeys=no -o ConnectTimeout=10'
    subprocess.run(['rsync','-rt','--whole-file','--partial-dir=.rsync-partial','-e',transport,
        pair.config['head']['data_root']+'/native-kit/',
        pair.config['worker']['ssh']+':'+pair.config['worker']['data_root']+'/native-kit/'],check=True)
    verify_kit(pair,'worker',full=True)
