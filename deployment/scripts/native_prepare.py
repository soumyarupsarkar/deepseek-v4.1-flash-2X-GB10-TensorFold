"""CPU preparation and byte-for-byte cache qualification for the native image."""
import hashlib
import json
from pathlib import Path

from configuration import CONFIG, fingerprint, read, source_revision
from runtime import atomic, now
from assets import verify
from native_assets import verify_kit

INVENTORY = r'''import json,pathlib,sys
root=pathlib.Path(sys.argv[1]);rank=int(sys.argv[2]);files=list(root.glob('rank'+str(rank)+'of2-*.bin'))
if len(files)>1:raise ValueError('Several completed rank caches')
out=None
if files:
 f=files[0]
 if f.is_symlink() or not f.is_file():raise ValueError('Redirected rank cache')
 s=f.stat();out=dict(name=f.name,fingerprint=[s.st_dev,s.st_ino,s.st_size,s.st_mtime_ns,s.st_ctime_ns])
print(json.dumps(out))
'''


def inventory(pair, host):
    return json.loads(pair.run(host,['python3','-B','-c',INVENTORY,
        pair.config[host]['data_root']+'/prepared',str(int(host=='worker'))],timeout=30).stdout)


def mounts(pair, host, prepared_writable=False):
    root = pair.config[host]['data_root']
    args = ['run','--rm','--network','none','--memory','16g','--memory-swap','16g',
            '--cpus','4','--pids-limit','256']
    for sub,target,ro in [('model','/model',True),('native-kit','/kit',True),
                          ('prepared','/prepared',not prepared_writable),('kernel-cache','/cache',False)]:
        args += ['-v',root+'/'+sub+':'+target+(':ro' if ro else '')]
    return args


def prepare(pair):
    """Prepare absent caches; imported or existing caches are only read."""
    build = read(pair.state/'build.json')
    if build['revision'] != source_revision():
        raise ValueError('Rebuild the reviewed source before native preparation')
    imported = (pair.state/'prepared-import.json').exists()
    for host in ('head','worker'):
        pair.roots(host);pair.idle(host)
        verify(pair,host,full=False);verify_kit(pair,host,full=False)
    receipt=dict(time=now(),image=build['id'],status='running',hosts={})
    atomic(pair.state/'native-prepare.json',receipt)
    try:
        for rank,host in enumerate(('head','worker')):
            entry = inventory(pair,host)
            if entry is None:
                if imported:
                    raise ValueError('Imported rank cache is missing; refusing to regenerate a shared file')
                digest = fingerprint(dict(assets=read(pair.state/'runtime-assets.json'),rank=rank,
                    native_revision=build['revision']))
                result=pair.docker(host,*mounts(pair,host,prepared_writable=True),
                    '--entrypoint','/opt/tensorfold/bin/tf-dsv41-prepare',build['id'],
                    '/model','/prepared',str(rank),'2',digest,timeout=7200)
                receipt['hosts'][host]=dict(preparation_output=result.stdout+result.stderr)
            else:
                receipt['hosts'][host]=dict(reused=True)
            result=pair.docker(host,*mounts(pair,host), '--entrypoint','python3',build['id'],
                '/opt/tensorfold/source/deployment/scripts/prepare_token_map.py',
                '/model','/kit','/cache/token-map.json',timeout=300)
            receipt['hosts'][host]['token_map']=json.loads(result.stdout)
            atomic(pair.state/'native-prepare.json',receipt)
        receipt['status']='passed'
    except BaseException:
        receipt['status']='failed'
        raise
    finally:
        atomic(pair.state/'native-prepare.json',receipt)


def check_caches(pair, image):
    receipt=dict(time=now(),image=image,status='running',hosts={},
        assets_sha256=hashlib.sha256((pair.state/'runtime-assets.json').read_bytes()).hexdigest(),
        kit_revision=read(CONFIG/'native-inputs.json')['kernel_kit']['revision'])
    atomic(pair.state/'native-cache-check.json',receipt)
    try:
        for rank,host in enumerate(('head','worker')):
            before=inventory(pair,host)
            if before is None:raise ValueError('Prepare both native rank caches first')
            result=pair.docker(host,*mounts(pair,host),'--entrypoint','/opt/tensorfold/bin/tf-dsv41-check',
                image,'/model','/prepared',str(rank),'2','--bytes','1',timeout=7200)
            checked=json.loads(result.stdout.strip().splitlines()[-1])
            if (not checked['ok'] or checked['compared'] != checked['entries']
                    or checked['compared_bytes'] != checked['bytes']):
                raise ValueError('The native reader did not validate every prepared tensor byte')
            if inventory(pair,host) != before:raise ValueError('Prepared cache changed during native verification')
            receipt['hosts'][host]=dict(**before,check=checked)
            atomic(pair.state/'native-cache-check.json',receipt)
        receipt['status']='passed'
    except BaseException:
        receipt['status']='failed'
        raise
    finally:
        atomic(pair.state/'native-cache-check.json',receipt)


def precompile(pair):
    """Kernels are built into the image; exercise driver ABI without model weights."""
    build=read(pair.state/'build.json');image=build['id']
    if build['revision'] != source_revision():raise ValueError('Image source differs')
    for host in ('head','worker'):
        pair.roots(host);pair.idle(host)
    receipt=dict(time=now(),image=image,status='running',hosts={})
    atomic(pair.state/'precompile.json',receipt)
    try:
        for host in ('head','worker'):
            results={}
            for command in ('info','smoke','graph','sample','cublaslt','nccl'):
                result=pair.docker(host,'run','--rm','--gpus','all','--network','none',
                    '--memory','8g','--memory-swap','8g','--pids-limit','512',
                    '--entrypoint','/opt/tensorfold/bin/tf-cuda-test',image,command,timeout=300)
                results[command]=dict(returncode=result.returncode,output=result.stdout+result.stderr)
            result=pair.docker(host,'run','--rm','--gpus','all','--network','none',
                '--memory','8g','--memory-swap','8g','--pids-limit','512',
                '-v',pair.config[host]['data_root']+'/native-kit:/kit:ro',
                '--entrypoint','/opt/tensorfold/bin/tf-dsv41-router-check',image,'/kit/aot',timeout=300)
            results['router_widths']=dict(returncode=result.returncode,output=result.stdout+result.stderr)
            result=pair.docker(host,'run','--rm','--gpus','all','--network','none',
                '--memory','3g','--memory-swap','3g','--cpus','4','--pids-limit','256',
                '--entrypoint','/opt/tensorfold/bin/tf-dsv41-fp8-check',image,timeout=600)
            results['fp8_wo_a']=dict(returncode=result.returncode,output=result.stdout+result.stderr)
            result=pair.docker(host,'run','--rm','--network','none',
                '--memory','3g','--memory-swap','3g','--cpus','4','--pids-limit','256',
                '-v',pair.config[host]['data_root']+'/engram:/engram:ro',
                '--entrypoint','/opt/tensorfold/bin/tf-dsv41-engram-check',image,
                '/engram','--rows','4096','--seed','1017',timeout=300)
            summary=json.loads(result.stdout.strip().splitlines()[-1])
            if summary.get('layers')!=2 or summary.get('all_equal') is not True:
                raise ValueError('Both Engram tables must match across buffered, direct and AIO reads')
            results['engram_rows']=dict(returncode=result.returncode,output=result.stdout+result.stderr)
            receipt['hosts'][host]=results
            atomic(pair.state/'precompile.json',receipt)
        check_caches(pair,image)
        receipt['status']='passed'
    except BaseException:
        receipt['status']='failed'
        raise
    finally:
        atomic(pair.state/'precompile.json',receipt)
