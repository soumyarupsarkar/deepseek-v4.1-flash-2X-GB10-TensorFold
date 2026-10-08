"""Explicit portable setup/lifecycle commands; no host action occurs on import."""
import argparse
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import tarfile

from configuration import CONFIG, SOURCE, STATE, BASE_IMAGE, load, profile, launch_args, read, source_revision
from runtime import Pair, atomic, now

COMPILE = '''from tensorfold.cuda.exl3 import linear,experts,prefetch
from tensorfold.cuda import rdma
from tensorfold.families.deepseek_v41.cuda.model import _engram_io
for fn in (linear._ext,experts._ext,prefetch._ext,rdma._ext,_engram_io):fn()
print('Serving extensions compiled without loading model weights')
'''


def plan(config):
    # Do not probe SSH, Docker, credentials, files under data_root or host configuration.
    p=profile()
    return dict(mode='read-only plan; no commands executed',
        profile={k:v for k,v in p.items() if k!='environment'},
        environment={k:v for k,v in p['environment'].items() if k!='TF_DS_COST_MODEL_JSON'},
        config=config, base_image=BASE_IMAGE,
        requires=dict(nodes=2,minimum_available_gib_before_load=112,ethernet_mtu=9000,rdma_mtu=4096,
                      passwordless_ssh=True,noninteractive_sudo=True,temporary_drm=True),
        actions=['init owned roots and baselines','fetch pinned model/Keys/original assets',
                 'extract and hash Engram/vision assets','copy and verify worker assets',
                 'build identical source image','precompile with weights unloaded',
                 'journal and apply temporary display settings','start worker then head',
                 'watch both ranks; stop both on failure','paired stop restores display settings'],
        status='publication preparation; portable two-node lifecycle not yet hardware-qualified')


def build(pair):
    for host in ('head','worker'):
        pair.roots(host);pair.idle(host)
    rev=source_revision()
    context=pair.state/'build'/rev
    context.mkdir(parents=True,exist_ok=True)
    archive=context/'source.tar'
    with archive.open('wb') as out:
        subprocess.run(['git','archive',rev],cwd=SOURCE,stdout=out,check=True)
    engine=context/'engine';engine.mkdir(exist_ok=True)
    with tarfile.open(archive) as tf:
        tf.extractall(engine,filter='data')
    archive.unlink()
    shutil.copyfile(CONFIG/'Dockerfile',context/'Dockerfile')
    tag=pair.config['name']+'-'+pair.ownership()[:8]+':'+rev[:12]
    subprocess.run(['sudo','-n','docker','build','--build-arg','SOURCE_REVISION='+rev,
                    '-t',tag,str(context)],check=True)
    image=json.loads(pair.docker('head','image','inspect',tag,timeout=30).stdout)[0]['Id']
    # No registry or publication is involved; transfer the same local image bytes.
    sender=subprocess.Popen(['sudo','-n','docker','save',tag],stdout=subprocess.PIPE)
    receiver=subprocess.Popen(['ssh','-T','-o','BatchMode=yes','-o','StrictHostKeyChecking=yes',
                               '-o','UpdateHostKeys=no',pair.config['worker']['ssh'],
                               'sudo -n docker load'],stdin=sender.stdout)
    sender.stdout.close()
    received=receiver.wait();sent=sender.wait()
    if received or sent:raise RuntimeError('Image transfer failed')
    if json.loads(pair.docker('worker','image','inspect',tag,timeout=30).stdout)[0]['Id']!=image:
        raise RuntimeError('Worker image differs')
    atomic(pair.state/'build.json',dict(time=now(),revision=rev,id=image,tag=tag))


def precompile(pair):
    image=read(pair.state/'build.json')['id'];results={}
    for host in ('head','worker'):
        pair.roots(host);pair.idle(host)
    for host in ('head','worker'):
        result=pair.docker(host,'run','--rm','--gpus','all','--network','none',
            '--memory','16g','--memory-swap','16g','--pids-limit','512',
            '-e','MAX_JOBS=4','-v',pair.config[host]['data_root']+'/kernel-cache:/cache',
            '--entrypoint','python',image,'-u','-c',COMPILE,timeout=1800)
        results[host]=dict(returncode=result.returncode,output=result.stdout+result.stderr)
    atomic(pair.state/'precompile.json',dict(time=now(),image=image,hosts=results,status='passed'))


def check_host(pair):
    result={}
    for host in ('head','worker'):
        if pair.containers(host):raise RuntimeError('Stop both owned ranks before checking restoration')
        before=read(pair.state/('baseline-'+host+'.json'));after=pair.snapshot(host)
        differences=[k for k in ('driver','kernel','modeset','fbdev','modules','display_manager') if before[k]!=after[k]]
        def rails(snapshot):
            wanted={r['interface'] for r in pair.config[host]['rails']}
            return {r['ifname']:{'mtu':r['mtu'],'ipv4':sorted((a['local'],a['prefixlen']) for a in r.get('addr_info',[]))}
                    for r in snapshot['addresses'] if r['ifname'] in wanted}
        if rails(before)!=rails(after):differences.append('rail_addresses_or_mtu')
        result[host]=dict(differences=differences,observed=after)
    record=dict(time=now(),hosts=result,status='passed' if all(not r['differences'] for r in result.values()) else 'different')
    atomic(pair.state/'restoration-check.json',record)
    print(json.dumps(record,indent=2))
    if record['status']!='passed':raise RuntimeError('Host baseline differs; no corrective mutations were made')


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--config',type=Path,default=SOURCE/'deployment/local.json')
    parser.add_argument('action',choices=('plan','init','doctor','fetch','reuse','reuse-prepared','replicate','verify','build',
                                         'precompile','start','stop','status','check-host','watch'))
    parser.add_argument('--from-head',help='Existing head asset root for reuse (never adopted)')
    parser.add_argument('--from-worker',help='Existing worker asset root for reuse (never adopted)')
    parser.add_argument('--reuse-prepared',action='store_true',help='Import completed rank caches, mounted read-only')
    args=parser.parse_args()
    if args.action not in ('reuse','reuse-prepared') and (args.from_head or args.from_worker or args.reuse_prepared):
        parser.error('Asset source arguments apply only to reuse')
    config=load(args.config)
    if args.action=='plan':
        print(json.dumps(plan(config),indent=2));return
    pair=Pair(config)
    if args.action=='doctor':
        print(json.dumps(pair.doctor(),indent=2));return
    if args.action=='watch':
        pair.watch();return
    if args.action=='status':
        for host in ('head','worker'):
            print(host,json.dumps([dict(id=r['Id'],image=r['Image'],state=r['State']['Status']) for r in pair.containers(host)]))
        try:print(json.dumps(pair.get('/health'),indent=2))
        except OSError:print('API offline')
        return
    with pair.lock():
        if args.action=='init':pair.initialize()
        elif args.action=='fetch':
            from assets import fetch
            fetch(pair)
        elif args.action=='reuse':
            from reuse import reuse
            reuse(pair,dict(head=args.from_head,worker=args.from_worker),args.reuse_prepared)
        elif args.action=='reuse-prepared':
            from reuse import reuse_prepared
            reuse_prepared(pair,dict(head=args.from_head,worker=args.from_worker))
        elif args.action=='replicate':
            from assets import replicate
            replicate(pair)
        elif args.action=='verify':
            from concurrent.futures import ThreadPoolExecutor
            from assets import verify
            with ThreadPoolExecutor(2) as pool:
                results={host:pool.submit(verify,pair,host,full=True) for host in ('head','worker')}
                for host,future in results.items():
                    future.result()
                    print(host+': all runtime asset hashes verified',flush=True)
        elif args.action=='build':build(pair)
        elif args.action=='precompile':precompile(pair)
        elif args.action=='start':pair.start()
        elif args.action=='stop':pair.stop()
        elif args.action=='check-host':check_host(pair)


if __name__=='__main__':
    main()
