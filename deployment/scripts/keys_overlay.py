"""Acquire and qualify small Keys caches without modifying stock model files."""
import hashlib
import json
import os
from pathlib import Path
import subprocess

from configuration import CONFIG, fingerprint, read, source_revision
from runtime import atomic, now
from assets import fetch_file, sha
from native_prepare import INVENTORY, inventory

FOLDER = 'overlays/keys-1017'
SOURCE = FOLDER + '/source'
PREPARED = FOLDER + '/prepared'


def spec():
    value = read(CONFIG/'keys-1017.json')
    base = read(CONFIG/'assets.json')['model']
    if (value['schema'] != 1 or value['world'] != 2 or 'keys' in read(CONFIG/'assets.json')
            or base['repo'] != value['base_repo'] or base['revision'] != value['base_revision']):
        raise ValueError('Keys overlay requires its pinned stock 1017 quantization')
    return value


def variant(value):
    if value not in ('stock', 'keys'):
        raise ValueError('Weight variant must be stock or keys')
    return value


def selected(pair):
    path = pair.state/'variant.json'
    return variant(read(path)['variant']) if path.exists() else 'stock'


def input_digest(pair):
    return hashlib.sha256((pair.state/'runtime-assets.json').read_bytes()).hexdigest()


ENSURE = r'''import pathlib,sys
root=pathlib.Path(sys.argv[1])
for sub in ('overlays/keys-1017','overlays/keys-1017/source','overlays/keys-1017/prepared'):
 p=root/sub
 if p.is_symlink() or p.resolve()!=p:raise ValueError('Redirected overlay directory')
 p.mkdir(exist_ok=True)
'''

# Bounded standard-library reader, shared by head and worker. Full hashing is
# done only during setup; startup checks all verified file identities instead.
VERIFY = r'''import hashlib,json,os,pathlib,struct,sys
p=json.load(sys.stdin);root=pathlib.Path(p['root']);files={}
def one(relative,expected):
 f=root/relative
 if f.is_symlink() or f.resolve()!=f or not f.is_file():raise ValueError('Missing or redirected overlay file')
 st=f.stat();fp=[st.st_dev,st.st_ino,st.st_size,st.st_mtime_ns,st.st_ctime_ns]
 if p['full']:
  h=hashlib.sha256()
  with f.open('rb') as stream:
   while block:=stream.read(2**20):
    h.update(block);os.posix_fadvise(stream.fileno(),stream.tell()-len(block),len(block),os.POSIX_FADV_DONTNEED)
  digest=h.hexdigest()
  if expected and (st.st_size!=expected['size'] or digest!=expected['sha256']):raise ValueError('Overlay pin differs')
 else:
  old=p['previous'][relative]
  if old['fingerprint']!=fp:raise ValueError('Verified overlay file changed; re-run setup-keys')
  digest=old['sha256']
 after=f.stat()
 if fp!=[after.st_dev,after.st_ino,after.st_size,after.st_mtime_ns,after.st_ctime_ns]:raise ValueError('Overlay changed during verification')
 files[relative]=dict(fingerprint=fp,sha256=digest,bytes=st.st_size)
 return f
row=p['spec']['files'][0];source='overlays/keys-1017/source/'+row['path']
f=one(source,row)
folder=f.parent
if {x.name for x in folder.iterdir()}!={f.name}:raise ValueError('Unexpected overlay source entry')
with f.open('rb') as stream:
 raw=stream.read(8)
 if len(raw)!=8:raise ValueError('Truncated overlay')
 n=struct.unpack('<Q',raw)[0]
 if not 1<=n<=1024*1024:raise ValueError('Invalid overlay header size')
 h=json.loads(stream.read(n));h.pop('__metadata__',None)
 wanted={f'layers.{i}.attn.wo_b.{part}' for i in range(10,36) for part in ('trellis','suh','svh','mul1')}
 if set(h)!=wanted:raise ValueError('Unexpected overlay tensor scope')
 words=p['spec']['trellis_words']
 if words not in (80,96):raise ValueError('Unsupported pinned Keys width')
 widths={'trellis':('I16',[512,320,words],512*320*words*2),'suh':('F16',[8192],8192*2),'svh':('F16',[5120],5120*2),'mul1':('I32',[],4)}
 spans=[]
 for key,e in h.items():
  dtype,shape,size=widths[key.rsplit('.',1)[1]];lo,hi=e['data_offsets']
  if e['dtype']!=dtype or e['shape']!=shape or type(lo)is not int or type(hi)is not int or lo<0 or hi-lo!=size or hi+8+n>f.stat().st_size:raise ValueError('Unexpected overlay layout')
  spans.append((lo,hi))
 at=0
 for lo,hi in sorted(spans):
  if lo!=at:raise ValueError('Overlapping or incomplete overlay payload')
  at=hi
 if 8+n+at!=f.stat().st_size:raise ValueError('Trailing overlay bytes')
if p.get('prepared'):
 name=p['prepared'];one('overlays/keys-1017/prepared/'+name,None)
 folder=root/'overlays/keys-1017/prepared'
 if {x.name for x in folder.iterdir()}!={name}:raise ValueError('Unexpected prepared overlay entry')
print(json.dumps(files))
'''


def files(pair, host, *, prepared=None, full=False, previous=None):
    result = pair.run(host, ['python3','-B','-c',VERIFY], input=json.dumps(dict(
        root=pair.config[host]['data_root'], spec=spec(), prepared=prepared, full=full,
        previous=previous)), timeout=300)
    return json.loads(result.stdout)


def overlay_inventory(pair, host):
    return json.loads(pair.run(host, ['python3','-B','-c',INVENTORY,
        pair.config[host]['data_root']+'/'+PREPARED, str(int(host=='worker'))], timeout=30).stdout)


def verify(pair, image):
    """Bind both small caches to this image, immutable base and verified source."""
    record = read(pair.state/'keys-overlay.json')
    if (record['status'] != 'passed' or record['image'] != image or record['spec_sha256'] != fingerprint(spec())
            or record['assets_sha256'] != input_digest(pair) or set(record['hosts']) != {'head','worker'}):
        raise ValueError('Run setup-keys for this image and stock checkpoint first')
    for host in ('head','worker'):
        row = record['hosts'][host]
        if inventory(pair,host) != row['base'] or overlay_inventory(pair,host) != row['prepared']:
            raise ValueError('Keys overlay or its base cache identity changed; re-run setup-keys')
        files(pair,host,prepared=row['prepared']['name'],previous=row['files'])
    return record


def setup(pair, source=None):
    """One-time offline preparation (fetch if absent); no stock bytes are written."""
    pin = spec(); build = read(pair.state/'build.json')
    if build['revision'] != source_revision():
        raise ValueError('Build this committed source before preparing Keys')
    for host in ('head','worker'):
        pair.roots(host);pair.idle(host)
    compatible = read(pair.state/'native-cache-check.json')
    if (compatible['status'] != 'passed' or compatible['image'] != build['id']
            or compatible['assets_sha256'] != input_digest(pair)):
        raise ValueError('Precompile and verify stock caches with this image before setup-keys')
    for host in ('head','worker'):
        if inventory(pair,host) != {k:compatible['hosts'][host][k] for k in ('name','fingerprint')}:
            raise ValueError('Verified stock cache identity changed')
        pair.run(host,['python3','-B','-c',ENSURE,pair.config[host]['data_root']],timeout=30)
    row = pin['files'][0]
    target = Path(pair.config['head']['data_root'])/SOURCE/row['path']
    if source is not None:
        source = Path(source).absolute()
        if source.is_symlink() or source.resolve()!=source or not source.is_file():
            raise ValueError('Use a regular pinned sidecar file for offline import')
        if source.stat().st_size!=row['size'] or sha(source)!=row['sha256']:
            raise ValueError('Offline overlay source does not match the pin')
        if not target.exists():
            # A hardlink preserves the exact verified download; never replace it.
            os.link(source,target,follow_symlinks=False)
    token = os.environ.get('HF_TOKEN')
    if not token and os.environ.get('HF_TOKEN_PATH'):
        token = Path(os.environ['HF_TOKEN_PATH']).read_text().strip()
    fetch_file(pin,row,target,token)
    files(pair,'head',full=True)
    transport='ssh -o BatchMode=yes -o StrictHostKeyChecking=yes -o UpdateHostKeys=no -o ConnectTimeout=10'
    subprocess.run(['rsync','-rt','--whole-file','--ignore-existing','-e',transport,str(target),
        pair.config['worker']['ssh']+':'+pair.config['worker']['data_root']+'/'+SOURCE+'/'],check=True)
    files(pair,'worker',full=True)
    record = dict(time=now(),status='running',image=build['id'],spec_sha256=fingerprint(pin),
        assets_sha256=input_digest(pair),hosts={})
    atomic(pair.state/'keys-overlay.json',record)
    try:
        for rank,host in enumerate(('head','worker')):
            root = pair.config[host]['data_root']; base = inventory(pair,host)
            digest = fingerprint(dict(spec=pin,assets=record['assets_sha256'],base=base['name'],rank=rank))
            expected_name = f'rank{rank}of2-native-{digest}.bin'
            entry = overlay_inventory(pair,host)
            mounts = ['run','--rm','--network','none','--memory','2g','--memory-swap','2g','--cpus','2',
                '--pids-limit','128','-v',root+'/model:/model:ro',
                '-v',root+'/prepared:/base:ro','-v',root+'/'+SOURCE+':/overlay-source:ro',
                '-v',root+'/'+PREPARED+':/overlay-prepared']
            if entry is None:
                pair.docker(host,*mounts,'--entrypoint','/opt/tensorfold/bin/tf-dsv41-prepare',build['id'],
                    '/model','/overlay-prepared',str(rank),'2',digest,'--keys-overlay','/overlay-source',timeout=600)
                entry=overlay_inventory(pair,host)
            if entry is None or entry['name']!=expected_name:
                raise ValueError('Prepared overlay belongs to different inputs; preserve it for review')
            # The native reader independently checks every slice against the raw
            # sidecar, including the complete TP2 scope and the allowed width.
            mounts[-1] += ':ro'
            checked=pair.docker(host,*mounts,'--entrypoint','/opt/tensorfold/bin/tf-dsv41-check',build['id'],
                '/model','/overlay-prepared',str(rank),'2','--keys-overlay','/overlay-source',
                '--base-cache','/base','--bytes','1',timeout=600)
            result=json.loads(checked.stdout.strip().splitlines()[-1])
            if (not result['ok'] or result['entries']!=pin['prepared_entries_per_rank']
                    or result['compared']!=result['entries'] or result['compared_bytes']!=pin['prepared_tensor_bytes_per_rank']):
                raise ValueError('Prepared Keys tensor verification failed')
            identities=files(pair,host,prepared=entry['name'],full=True)
            if inventory(pair,host)!=base or overlay_inventory(pair,host)!=entry:
                raise ValueError('Weights changed during overlay verification')
            record['hosts'][host]=dict(base=base,prepared=entry,files=identities,check=result)
            atomic(pair.state/'keys-overlay.json',record)
        record['status']='passed'
    except BaseException:
        record['status']='failed'
        raise
    finally:
        atomic(pair.state/'keys-overlay.json',record)
    return record
