"""Import pinned assets from an existing installation without modifying its contents."""
import hashlib
import json
from pathlib import Path

from configuration import CONFIG, SOURCE, read
from runtime import atomic, now
from assets import model_view, relative, verify


# Run on each host. Hardlinks are permitted only after validating the pinned
# bytes; all serving model mounts and imported prepared caches are read-only.
IMPORT = r'''import concurrent.futures,hashlib,json,os,pathlib,shutil,sys
p=json.load(sys.stdin);source=pathlib.Path(p['source']);root=pathlib.Path(p['root'])
if not source.is_absolute() or source.resolve()!=source or source==root or source in root.parents or root in source.parents:
 raise ValueError('Source and destination must be distinct real directories')
def one(row):
 src=source/row['source'];dst=root/row['target']
 if src.resolve()!=src or not src.is_file():raise ValueError('Missing or redirected source: '+row['source'])
 if dst.resolve()!=dst:raise ValueError('Redirected destination')
 before=src.stat()
 if before.st_size!=row['bytes']:raise ValueError('Source size differs: '+row['source'])
 sha=hashlib.sha256();blob=hashlib.sha1(b'blob '+str(before.st_size).encode()+b'\0')
 with src.open('rb') as stream:
  while block:=stream.read(4*2**20):
   sha.update(block)
   if row.get('git_blob_id'):blob.update(block)
   os.posix_fadvise(stream.fileno(),stream.tell()-len(block),len(block),os.POSIX_FADV_DONTNEED)
 digest=sha.hexdigest()
 if row.get('sha256') and digest!=row['sha256']:raise ValueError('Source SHA256 differs: '+row['source'])
 if row.get('git_blob_id') and blob.hexdigest()!=row['git_blob_id']:raise ValueError('Pinned metadata differs: '+row['source'])
 after=src.stat()
 if (before.st_size,before.st_mtime_ns,before.st_ctime_ns)!=(after.st_size,after.st_mtime_ns,after.st_ctime_ns):
  raise ValueError('Source changed during verification')
 dst.parent.mkdir(parents=True,exist_ok=True)
 if dst.exists():
  if not os.path.samefile(src,dst):raise ValueError('Existing destination is not this verified asset')
 else:os.link(src,dst,follow_symlinks=False)
 return row['target'],dict(bytes=before.st_size,sha256=digest)
with concurrent.futures.ThreadPoolExecutor(3) as pool:out=dict(pool.map(one,p['files']))
print(json.dumps(out))
'''

PREPARED = r'''import hashlib,json,os,pathlib,struct,sys
p=json.load(sys.stdin);source=pathlib.Path(p['source'])/'prepared';dest=pathlib.Path(p['root'])/'prepared'
if source.resolve()!=source:raise ValueError('Redirected prepared source')
files=list(source.glob('rank'+str(p['rank'])+'of2-*.bin'))
if len(files)!=1:raise ValueError('Expected one completed prepared cache for this rank')
f=files[0]
if f.is_symlink() or not f.is_file():raise ValueError('Invalid prepared cache')
before=f.stat();h=hashlib.sha256()
with f.open('rb') as stream:
 while block:=stream.read(4*2**20):
  h.update(block);os.posix_fadvise(stream.fileno(),stream.tell()-len(block),len(block),os.POSIX_FADV_DONTNEED)
 stream.seek(-16,2);footer=stream.read(16)
 if footer[8:]!=b'TFDSRK01':raise ValueError('Incomplete prepared cache')
 at=struct.unpack('<Q',footer[:8])[0]
 if not 0<before.st_size-at<32*2**20:raise ValueError('Invalid prepared footer offset')
 stream.seek(at);index=json.loads(stream.read()[:-16])
 if not index or any(row[3]<0 or row[4]<0 or row[3]+row[4]>at for row in index):raise ValueError('Invalid prepared tensor index')
after=f.stat()
if (before.st_size,before.st_mtime_ns,before.st_ctime_ns)!=(after.st_size,after.st_mtime_ns,after.st_ctime_ns):raise ValueError('Prepared cache changed while hashing')
target=dest/f.name
if target.is_symlink():raise ValueError('Redirected prepared destination')
if target.exists():
 if not os.path.samefile(f,target):raise ValueError('Existing prepared destination differs')
else:os.link(f,target,follow_symlinks=False)
st=target.stat()
print(json.dumps(dict(name=f.name,bytes=st.st_size,sha256=h.hexdigest(),fingerprint=[st.st_dev,st.st_ino,st.st_size,st.st_mtime_ns,st.st_ctime_ns])))
'''


def reuse(pair, sources, prepared=False):
    """Head source needs stock-model/overlays; worker source needs its runtime view.

    Unknown source files (including private provenance) are never imported.
    Hardlinks change inode ctime: refresh the old installation's hash receipts
    before returning to it. Byte contents, timestamps and ownership are retained.
    """
    for host in ('head', 'worker'):
        pair.roots(host); pair.idle(host)
        if not sources.get(host):
            raise ValueError('Both existing source roots are required')
    specs=read(CONFIG/'assets.json');derived=read(CONFIG/'derived-assets.json')
    rows=[]
    for kind,folder in (('model','stock-model'),('keys','overlays')):
        for row in specs[kind]['files']:
            name=folder+'/'+str(relative(row['path']))
            rows.append(dict(source=name,target=name,bytes=row['size'],sha256=row['sha256'],
                             git_blob_id=row['git_blob_id'] if not row['sha256'] else None))
    rows.extend(dict(source=n,target=n,**row) for n,row in derived.items())
    print('Head: hashing pinned source assets before linking them',flush=True)
    result=pair.run('head',['python3','-B','-c',IMPORT],input=json.dumps(dict(
        source=sources['head'],root=pair.config['head']['data_root'],files=rows)),timeout=7200)
    imported=json.loads(result.stdout)
    root=Path(pair.config['head']['data_root'])
    model_view(root,specs)
    manifest={}
    for name,row in imported.items():
        if name.startswith('stock-model/') and name!='stock-model/model.safetensors.index.json':
            manifest['model/'+name.split('/',1)[1]]=row
        elif name in derived:manifest[name]=row
    manifest['model/zz_keys_overlay.safetensors']=imported['overlays/'+specs['keys']['files'][0]['path']]
    index=(root/'model/model.safetensors.index.json').read_bytes()
    manifest['model/model.safetensors.index.json']=dict(bytes=len(index),sha256=hashlib.sha256(index).hexdigest())
    atomic(pair.state/'runtime-assets.json',manifest)
    # The newly rendered index has the same tensor mapping but may differ in
    # formatting from the old installer. Copy only this small generated metadata.
    code="import pathlib,sys\np=pathlib.Path(sys.argv[1]);data=sys.stdin.buffer.read()\nif p.exists():\n if p.is_symlink() or p.read_bytes()!=data:raise ValueError('Existing index differs')\nelse:\n with p.open('xb') as f:f.write(data)\n"
    pair.run('worker',['python3','-B','-c',code,pair.config['worker']['data_root']+'/model/model.safetensors.index.json'],
             input=index.decode(),timeout=60)
    rows=[dict(source=n,target=n,**row) for n,row in manifest.items() if n!='model/model.safetensors.index.json']
    print('Worker: hashing and linking the matching runtime assets',flush=True)
    pair.run('worker',['python3','-B','-c',IMPORT],input=json.dumps(dict(
        source=sources['worker'],root=pair.config['worker']['data_root'],files=rows)),timeout=7200)
    if prepared:
        receipt=dict(time=now(),readonly=True,hosts={},weights_source_sha256=hashlib.sha256(
            (SOURCE/'src/tensorfold/families/deepseek_v41/cuda/weights.py').read_bytes()).hexdigest())
        # Publish the read-only policy before any shared prepared inode exists.
        atomic(pair.state/'prepared-import.json',receipt)
        for rank,host in enumerate(('head','worker')):
            print(host+': checking the completed prepared cache for read-only reuse',flush=True)
            result=pair.run(host,['python3','-B','-c',PREPARED],input=json.dumps(dict(
                source=sources[host],root=pair.config[host]['data_root'],rank=rank)),timeout=3600)
            receipt['hosts'][host]=json.loads(result.stdout)
            atomic(pair.state/'prepared-import.json',receipt)
    for host in ('head','worker'):
        print(host+': verifying the complete new runtime view',flush=True)
        verify(pair,host,full=True)
    atomic(pair.state/'reuse.json',dict(time=now(),sources=sources,prepared_readonly=prepared,status='passed'))
    print('Verified asset reuse complete; previous source contents retained',flush=True)
