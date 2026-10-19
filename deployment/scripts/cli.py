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

def plan(config, weight_variant='stock'):
    # Do not probe SSH, Docker, credentials, files under data_root or host configuration.
    p=profile(weight_variant)
    return dict(mode='read-only plan; no commands executed',
        profile={k:v for k,v in p.items() if k!='environment'},
        environment=p['environment'],
        config=config, base_image=BASE_IMAGE,
        requires=dict(nodes=2,minimum_available_gib_before_load=112,ethernet_mtu=9000,rdma_mtu=4096,
                      passwordless_ssh=True,noninteractive_sudo=True,temporary_drm=True),
        actions=['init owned roots and baselines','fetch pinned checkpoint and matching original assets',
                 'extract and hash Engram/vision assets; verify the pinned native kernel kit',
                 'copy and verify worker assets','build identical native source image',
                 'prepare native rank caches and compressed token maps with CPU tools',
                 'test CUDA primitives with weights unloaded; compare every prepared tensor byte',
                 'journal and apply temporary display settings','start worker then head',
                 'watch both ranks; stop both on failure','paired stop restores display settings'],
        status=p['qualification'])


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
    from native_prepare import precompile as native_precompile
    native_precompile(pair)


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
    parser.add_argument('action',choices=('plan','init','doctor','fetch','fetch-kit','replicate-kit','prepare','reuse','reuse-prepared','replicate','verify','build',
                                         'precompile','setup-keys','start','switch','stop','status','check-host','watch'))
    parser.add_argument('--variant',choices=('stock','keys'),help='Weight set for plan/start/switch; start remembers the last successful choice')
    parser.add_argument('--overlay-source',type=Path,help='Verified local Keys sidecar for setup-keys, avoiding a download')
    parser.add_argument('--from-head',help='Existing head asset root for reuse (never adopted)')
    parser.add_argument('--from-worker',help='Existing worker asset root for reuse (never adopted)')
    parser.add_argument('--reuse-prepared',action='store_true',help='Import completed rank caches, mounted read-only')
    args=parser.parse_args()
    if args.variant and args.action not in ('plan','start','switch'):
        parser.error('--variant applies only to plan/start/switch')
    if args.action=='switch' and not args.variant:
        parser.error('switch requires --variant stock or keys')
    if args.overlay_source and args.action!='setup-keys':
        parser.error('--overlay-source applies only to setup-keys')
    if args.action not in ('reuse','reuse-prepared') and (args.from_head or args.from_worker or args.reuse_prepared):
        parser.error('Asset source arguments apply only to reuse')
    config=load(args.config)
    if args.action=='plan':
        print(json.dumps(plan(config,args.variant or 'stock'),indent=2));return
    pair=Pair(config)
    if args.action=='doctor':
        print(json.dumps(pair.doctor(),indent=2));return
    if args.action=='watch':
        pair.watch();return
    if args.action=='status':
        from keys_overlay import selected
        print('selected_weight_variant',selected(pair))
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
        elif args.action=='fetch-kit':
            from native_assets import fetch_kit
            fetch_kit(pair)
        elif args.action=='replicate-kit':
            from native_assets import replicate_kit
            replicate_kit(pair)
        elif args.action=='prepare':
            from native_prepare import prepare
            prepare(pair)
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
        elif args.action=='setup-keys':
            from keys_overlay import setup
            print(json.dumps(setup(pair,args.overlay_source),indent=2))
        elif args.action=='start':pair.start(args.variant)
        elif args.action=='switch':pair.switch(args.variant)
        elif args.action=='stop':pair.stop()
        elif args.action=='check-host':check_host(pair)


if __name__=='__main__':
    main()
