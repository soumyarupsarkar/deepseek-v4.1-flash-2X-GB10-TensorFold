"""Pinned model acquisition and standard safetensors extraction, without host ML packages."""
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import shlex
import struct
import subprocess
import urllib.parse
import urllib.request

from configuration import CONFIG, read
from range_download import download, sha
from runtime import atomic, now


def relative(name):
    p = PurePosixPath(name)
    if not name or p.is_absolute() or '..' in p.parts or str(p) != name:
        raise ValueError('Invalid asset-relative path')
    return p


def url(spec, name):
    relative(name)
    if not re.fullmatch(r'[0-9a-f]{40}', spec['revision']):
        raise ValueError('Asset revision must be immutable')
    return 'https://huggingface.co/'+spec['repo']+'/resolve/'+spec['revision']+'/'+urllib.parse.quote(name)


def authorization(request, token):
    if token:
        # Redirects to signed storage URLs must not receive the HF credential.
        request.add_unredirected_header('Authorization','Bearer '+token)
    return request


def fetch_file(spec, row, dest, token=None):
    dest = Path(dest)
    if row['sha256']:
        download(url(spec,row['path']),dest,row['sha256'],row['size'],workers=4,token=token)
        return
    if dest.is_symlink():
        raise ValueError('Asset destination is a symlink')
    if dest.exists():
        raw = dest.read_bytes()
    else:
        request = authorization(urllib.request.Request(url(spec,row['path'])),token)
        with urllib.request.urlopen(request,timeout=90) as response:
            raw = response.read(row['size']+1)
    actual = hashlib.sha1(b'blob '+str(len(raw)).encode()+b'\0'+raw).hexdigest()
    if len(raw)!=row['size'] or actual!=row['git_blob_id']:
        raise ValueError('Pinned metadata differs: '+row['path'])
    dest.parent.mkdir(parents=True,exist_ok=True)
    if not dest.exists():
        with dest.open('xb') as f:
            f.write(raw)


def header(path):
    with Path(path).open('rb') as f:
        prefix = f.read(8)
        if len(prefix)!=8:
            raise ValueError('Truncated safetensors length')
        n = struct.unpack('<Q',prefix)[0]
        if not 1 <= n <= 32*2**20:
            raise ValueError('Unreasonable safetensors header')
        raw = f.read(n)
    if len(raw)!=n:
        raise ValueError('Truncated safetensors header')
    entries = json.loads(raw)
    entries.pop('__metadata__',None)
    for entry in entries.values():
        lo,hi = entry['data_offsets']
        if type(lo) is not int or type(hi) is not int or not 0 <= lo <= hi:
            raise ValueError('Invalid tensor offsets')
        if hi+8+n > Path(path).stat().st_size:
            raise ValueError('Tensor extends beyond file')
    return entries,8+n


def range_bytes(spec, name, begin, end, token=None):
    if not 0 <= begin <= end or end-begin > 32*2**20:
        raise ValueError('Only bounded metadata/tensor ranges are allowed')
    request = urllib.request.Request(url(spec,name),headers={
        'Range':f'bytes={begin}-{end}','Accept-Encoding':'identity'})
    with urllib.request.urlopen(authorization(request,token),timeout=90) as response:
        content_range = response.headers.get('Content-Range','')
        if response.status!=206 or not re.fullmatch(fr'bytes {begin}-{end}/[0-9]+',content_range):
            raise ValueError('Source did not honor the exact bounded HTTP range')
        raw = response.read(end-begin+2)
    if len(raw)!=end-begin+1:
        raise ValueError('Source range length differs')
    return raw


def write_safetensors(dest, encoded, chunks, expected=None):
    """Write header and streaming payload; never overwrite a different finished asset."""
    dest = Path(dest)
    if dest.is_symlink():
        raise ValueError('Redirected output asset')
    if dest.exists():
        if expected and dest.stat().st_size==expected['bytes'] and sha(dest)==expected['sha256']:
            return
        raise ValueError('Existing output requires explicit review')
    part = dest.with_name(dest.name+'.prepare-part')
    with part.open('xb') as f:
        f.write(struct.pack('<Q',len(encoded)));f.write(encoded)
        for chunk in chunks:
            f.write(chunk)
        f.flush();os.fsync(f.fileno())
    if expected and (part.stat().st_size!=expected['bytes'] or sha(part)!=expected['sha256']):
        raise ValueError('Derived asset hash differs; unfinished file retained')
    os.link(part,dest,follow_symlinks=False);part.unlink()


def extract_engram(original, output, index, layouts):
    original,output = Path(original),Path(output)
    for name, layout in layouts.items():
        encoded = layout['header'].encode()
        target = json.loads(encoded)
        entries = [(key,value) for key,value in target.items() if key!='__metadata__']
        entries.sort(key=lambda item:item[1]['data_offsets'][0])
        def chunks():
            expected_offset = 0
            for key,entry in entries:
                source = original/relative(index[key])
                source_header,base = header(source)
                old = source_header[key]
                lo,hi = old['data_offsets'];tlo,thi=entry['data_offsets']
                if (old['dtype']!=entry['dtype'] or old['shape']!=entry['shape']
                        or hi-lo!=thi-tlo or tlo!=expected_offset):
                    raise ValueError('Engram tensor layout differs')
                with source.open('rb') as f:
                    f.seek(base+lo);remaining=hi-lo
                    while remaining:
                        block=f.read(min(4*2**20,remaining))
                        if not block:raise ValueError('Truncated source tensor')
                        remaining-=len(block);yield block
                        os.posix_fadvise(f.fileno(),f.tell()-len(block),len(block),os.POSIX_FADV_DONTNEED)
                expected_offset=thi
        write_safetensors(output/name,encoded,chunks(),layout)


def extract_vision(spec, index, dest, expected, token=None):
    target = Path(dest)
    if target.exists():
        if target.is_symlink() or target.stat().st_size!=expected['bytes'] or sha(target)!=expected['sha256']:
            raise ValueError('Existing vision asset differs')
        return
    keys = [f'layers.{n}.ffn.gate.bias_vl' for n in range(40)]
    headers,entries,pieces,offset = {},{},{},0
    for key in sorted(keys):
        name = str(relative(index[key]))
        if name not in headers:
            n=struct.unpack('<Q',range_bytes(spec,name,0,7,token))[0]
            if not 1<=n<=32*2**20:raise ValueError('Invalid remote tensor header')
            headers[name]=(json.loads(range_bytes(spec,name,8,7+n,token)),8+n)
        h,base=headers[name];entry=h[key];lo,hi=entry['data_offsets']
        if entry['dtype']!='F32' or entry['shape']!=[384] or hi-lo!=1536 or lo<0:
            raise ValueError('Unexpected vision routing tensor')
        pieces[key]=range_bytes(spec,name,base+lo,base+hi-1,token)
        entries[key]=dict(entry,data_offsets=[offset,offset+1536]);offset+=1536
    encoded=json.dumps(entries,separators=(',',':')).encode()
    encoded+=b' '*(-len(encoded)%8)
    write_safetensors(target,encoded,(pieces[k] for k in sorted(pieces)),expected)


def link_checked(source, dest):
    source,dest=Path(source),Path(dest)
    if source.is_symlink() or dest.is_symlink():
        raise ValueError('Model files must not be redirected')
    if dest.exists():
        if not os.path.samefile(source,dest):raise ValueError('Existing model link differs')
    else:os.link(source,dest)


def model_view(root, specs):
    root=Path(root);stock=root/'stock-model';view=root/'model'
    stock_entries={}
    for p in sorted(stock.glob('*.safetensors')):
        h,_=header(p)
        if stock_entries.keys() & h.keys():raise ValueError('Duplicate stock tensors')
        stock_entries.update(h)
    row=specs['keys']['files'][0];overlay=root/'overlays'/relative(row['path'])
    if sha(overlay)!=row['sha256']:raise ValueError('Keys overlay hash differs')
    overrides,_=header(overlay)
    names={f'layers.{n}.attn.wo_b.{part}' for n in range(10,36) for part in ('trellis','suh','svh','mul1')}
    if set(overrides)!=names:raise ValueError('Expected exactly the 104 pinned Keys tensors')
    for name,entry in overrides.items():
        if name not in stock_entries or any(entry[k]!=stock_entries[name][k] for k in ('dtype','shape')):
            raise ValueError('Incompatible Keys tensor')
    for row in specs['model']['files']:
        if row['path']!='model.safetensors.index.json':
            link_checked(stock/relative(row['path']),view/relative(row['path']))
    link_checked(overlay,view/'zz_keys_overlay.safetensors')
    index=read(stock/'model.safetensors.index.json')
    for name in overrides:index['weight_map'][name]='zz_keys_overlay.safetensors'
    index_path=view/'model.safetensors.index.json'
    if index_path.exists() and read(index_path)!=index:raise ValueError('Existing model index differs')
    if not index_path.exists():atomic(index_path,index)
    selected={}
    for p in sorted(view.glob('*.safetensors')):
        selected.update({k:p.name for k in header(p)[0]})
    if len(selected)!=len(stock_entries) or any(selected[k]!='zz_keys_overlay.safetensors' for k in overrides):
        raise ValueError('Lexical overlay resolution differs')


def fetch(pair):
    pair.roots('head')
    root=Path(pair.config['head']['data_root']);specs=read(CONFIG/'assets.json')
    token=os.environ.get('HF_TOKEN')
    if not token and os.environ.get('HF_TOKEN_PATH'):
        token=Path(os.environ['HF_TOKEN_PATH']).read_text().strip()
    # Only immutable source metadata and weights are requested. Tokens are never journaled.
    for kind,folder in (('model','stock-model'),('keys','overlays'),('engram','original')):
        for row in specs[kind]['files']:
            fetch_file(specs[kind],row,root/folder/relative(row['path']),token)
    index=read(root/'original/model.safetensors.index.json')['weight_map']
    extract_engram(root/'original',root/'engram',index,read(CONFIG/'engram-layouts.json'))
    derived=read(CONFIG/'derived-assets.json')
    extract_vision(specs['engram'],index,root/'vision-extra/vision-routing-bias.safetensors',
                   derived['vision-extra/vision-routing-bias.safetensors'],token)
    model_view(root,specs)
    manifest={}
    for sub in ('model','engram','vision-extra'):
        for p in sorted((root/sub).iterdir()):
            if not p.is_file() or p.is_symlink():raise ValueError('Unexpected asset entry')
            manifest[sub+'/'+p.name]=dict(bytes=p.stat().st_size,sha256=sha(p))
    atomic(pair.state/'runtime-assets.json',manifest)
    verify(pair,'head',full=True)


VERIFY = '''import hashlib,json,os,pathlib,sys
p=json.load(sys.stdin);root=pathlib.Path(p['root']);out={}
actual={sub+'/'+f.name for sub in ('model','engram','vision-extra') for f in (root/sub).iterdir()}
if actual!=set(p['manifest']):raise ValueError('Asset inventory differs; extra files can override tensors')
for name,expected in p['manifest'].items():
 f=root/name
 if not f.is_file() or f.is_symlink():raise ValueError('Missing/redirected asset')
 st=f.stat();fp=[st.st_dev,st.st_ino,st.st_size,st.st_mtime_ns,st.st_ctime_ns]
 if st.st_size!=expected['bytes']:raise ValueError('Asset size differs')
 if p['full']:
  h=hashlib.sha256()
  with f.open('rb') as stream:
   while block:=stream.read(4*2**20):
    h.update(block);os.posix_fadvise(stream.fileno(),stream.tell()-len(block),len(block),os.POSIX_FADV_DONTNEED)
  if h.hexdigest()!=expected['sha256']:raise ValueError('Asset SHA256 differs')
 elif fp!=p['previous']['files'][name]:raise ValueError('Verified asset fingerprint changed')
 out[name]=fp
print(json.dumps(out))
'''


def verify(pair, host, full=True):
    pair.roots(host)
    manifest_path=pair.state/'runtime-assets.json'
    manifest=read(manifest_path);digest=hashlib.sha256(manifest_path.read_bytes()).hexdigest()
    path=pair.state/('assets-'+host+'.json')
    previous=read(path) if path.exists() else None
    if not full and (previous is None or previous['manifest_sha256']!=digest):
        raise ValueError(host+': full asset verification required')
    result=pair.run(host,['python3','-B','-c',VERIFY],input=json.dumps(dict(
        root=pair.config[host]['data_root'],manifest=manifest,full=full,previous=previous)),timeout=7200)
    if full:atomic(path,dict(time=now(),manifest_sha256=digest,files=json.loads(result.stdout)))


def replicate(pair):
    for host in ('head','worker'):pair.roots(host)
    verify(pair,'head',full=False)
    transport='ssh -o BatchMode=yes -o StrictHostKeyChecking=yes -o UpdateHostKeys=no -o ConnectTimeout=10'
    for sub in ('model','engram','vision-extra'):
        subprocess.run(['rsync','-rt','--whole-file','--partial-dir=.rsync-partial','--info=progress2',
                        '-e',transport,pair.config['head']['data_root']+'/'+sub+'/',
                        pair.config['worker']['ssh']+':'+pair.config['worker']['data_root']+'/'+sub+'/'],check=True)
    verify(pair,'worker',full=True)
