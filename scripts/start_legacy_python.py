#!/usr/bin/env python3
"""Start the retained, pinned Python fallback after native host restoration.

This migration-only helper leaves a successful Python start running. On failure
it stops the owned pair and checks host restoration. It never modifies source,
profiles, allocator limits, global VM policy, or existing evidence. It can issue
one anonymous reclaim request to the owned worker cgroup during warm-up, before
the legacy engine fixes its allocator ceiling. It does not run inference tests.
"""
import argparse
import datetime
import hashlib
import json
import os
from pathlib import Path
import re
import signal
import subprocess
import sys
import time

SOURCE = '32c4ebea7d0a81808aaa503d88ebe1a84612d0cf'
IMAGE = 'sha256:973b52dedb5e9e9270fdcaa1840f4ff61076c08fadb3d97c1aea98bef6795834'
REMOTE = r'''
import errno,json,os,pathlib,re,subprocess,sys,time,traceback
mode,cid,image,label,owner,role=sys.argv[1:]
evidence={'mode':mode,'write_attempted':False}
def require(ok,reason):
 if not ok:raise RuntimeError(reason)
def emit(value):
 print(json.dumps(value),flush=True)
try:
 require(mode in ('probe','apply'),'invalid mode')
 require(os.geteuid()==0 and re.fullmatch(r'[a-f0-9]{64}',cid),'invalid root or container identity')
 row,=json.loads(subprocess.check_output(['docker','inspect',cid],text=True,timeout=10))
 require(row['Id']==cid and row['Image']==image and row['State']['Running'],'owned image is not running')
 require(not row['State']['Paused'] and not row['State']['Restarting'] and row['RestartCount']==0,'container state changed')
 require(row['Config']['Labels'].get(label)==owner and row['Config']['Labels'].get(role)=='inference','ownership mismatch')
 pid=row['State']['Pid'];require(type(pid) is int and pid>1,'invalid container init pid')
 lines=(pathlib.Path('/proc')/str(pid)/'cgroup').read_text().splitlines()
 groups=[x.split(':',2)[2] for x in lines if x.startswith('0::')]
 require(len(groups)==1,'expected unified cgroup')
 root=pathlib.Path('/sys/fs/cgroup');group=root/groups[0].lstrip('/')
 evidence.update(cgroup=groups[0],container_pid=pid)
 require(group.resolve()==group and group.parent==root/'system.slice','unexpected Docker cgroup parent')
 require(group.name=='docker-'+cid+'.scope','cgroup does not match the owned container')
 require((group/'memory.reclaim').is_file(),'memory.reclaim unavailable')
 def numbers(path):
  return {k:int(v) for k,v in (x.split() for x in path.read_text().splitlines())}
 def snapshot():
  mem={x.split(':')[0]:int(x.split()[1])*1024 for x in pathlib.Path('/proc/meminfo').read_text().splitlines() if x.split(':')[0] in ('MemAvailable','SwapFree')}
  stat=numbers(group/'memory.stat')
  return dict(meminfo=mem,memory_current=int((group/'memory.current').read_text()),swap_current=int((group/'memory.swap.current').read_text()),
   stat={k:stat.get(k) for k in ('anon','file','kernel','pswpin','pswpout','pgscan_proactive','pgsteal_proactive')},events=numbers(group/'memory.events'),
   limits={k:(group/k).read_text().strip() for k in ('memory.min','memory.low','memory.high','memory.max','memory.swap.max')},
   global_swappiness=pathlib.Path('/proc/sys/vm/swappiness').read_text().strip())
 before=snapshot();evidence['before']=before
 guards={'swap_free_at_least_4gib':before['meminfo']['SwapFree']>=4*2**30,
  'anon_at_least_2gib':before['stat']['anon']>=2*2**30,
  'swap_permitted':before['limits']['memory.swap.max']!='0',
  'host_available_at_least_2gib':before['meminfo']['MemAvailable']>=2*2**30}
 evidence.update(guards=guards,eligible=all(guards.values()))
 if mode=='probe':
  evidence['status']='probe';emit(evidence);sys.exit(0)
 require(evidence['eligible'],'reclaim preconditions changed')
 # Reject a late operation remotely too, immediately before touching the cgroup.
 logs=subprocess.run(['docker','logs','--tail','100',cid],capture_output=True,text=True,check=True,timeout=10)
 require('rank 1 capacity:' in logs.stdout+logs.stderr,'pool setup has not completed')
 require('allocator ceiling' not in logs.stdout+logs.stderr,'allocator ceiling already recorded')
 started=time.monotonic();error=None
 evidence.update(status='write-attempt',write_attempted=True,requested_bytes=2*2**30)
 emit(evidence)
 try:
  with (group/'memory.reclaim').open('w') as stream:stream.write(str(2*2**30)+' swappiness=max\n')
 except OSError as exc:
  if exc.errno!=errno.EAGAIN:raise
  error='EAGAIN: less than requested; no retry'
 after=snapshot();evidence.update(after=after,seconds=time.monotonic()-started,error=error)
 require(after['limits']==before['limits'] and after['global_swappiness']==before['global_swappiness'],'memory policy changed')
 require(after['events']['oom_kill']==before['events']['oom_kill'],'cgroup OOM kill increased')
 evidence.update(status='completed',requests=1,swappiness='max',persistent_settings_changed=False)
 emit(evidence)
except Exception as exc:
 evidence.update(status='failed',error=type(exc).__name__+': '+str(exc));emit(evidence)
 traceback.print_exc();sys.exit(1)
'''


def now():
    return datetime.datetime.now(datetime.timezone.utc).isoformat()


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def read(path):
    return json.loads(path.read_text())


def require(value, message):
    if not value:
        raise ValueError(message)


def validate_identity(checkout):
    require(subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=checkout, text=True).strip() == SOURCE,
            'This helper only supports the pinned Python rollback source')
    require(not subprocess.check_output(['git', 'status', '--porcelain'], cwd=checkout, text=True).strip(),
            'Retained Python source must be clean')
    build = read(checkout / 'deployment/.local/build.json')
    require(build['revision'] == SOURCE and build['id'] == IMAGE, 'Retained build identity differs')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--checkout', required=True, type=Path, help='Retained Python installation, not the native checkout')
    parser.add_argument('--record', required=True, help='New private record name; existing records are never resumed')
    args = parser.parse_args()
    require(re.fullmatch(r'[a-z0-9][a-z0-9-]{0,79}', args.record), 'Invalid record name')
    checkout = args.checkout.resolve()
    validate_identity(checkout)
    state = checkout / 'deployment/.local'
    sys.path.insert(0, str(checkout / 'deployment/scripts'))
    from configuration import load, LABEL, ROLE
    from runtime import Pair, atomic
    pair = Pair(load(state / 'installed.json'))
    owner = pair.ownership()
    require(read(state / 'active.json')['running'] is False, 'Stop the retained installation first')
    for host in ('head', 'worker'):
        require(not pair.containers(host), host + ': existing owned container')
        require(not read(state / ('drm-' + host + '.json'))['active'], host + ': restore the existing DRM journal first')
    os.umask(0o077)
    directory = state / 'legacy-start' / args.record
    directory.mkdir(parents=True, exist_ok=False, mode=0o700)
    output = directory / 'status.json'
    immutable = ('ownership.json', 'installed.json', 'build.json', 'precompile.json',
                 'runtime-assets.json', 'assets-head.json', 'assets-worker.json', 'prepared-import.json')
    frozen = {name: sha(state / name) for name in immutable}
    record = dict(status='running', started=now(), source=SOURCE, image=IMAGE,
                  script_sha256=sha(Path(__file__)), remote_sha256=hashlib.sha256(REMOTE.encode()).hexdigest(),
                  frozen_inputs=frozen, steps=[], probes=[], reclaim_remote_attempts=0,
                  persistent_policy_changed=False, previous_run_resumed=False)

    def save():
        atomic(output, record)

    def identity():
        validate_identity(checkout)
        require(all(sha(state / name) == digest for name, digest in frozen.items()), 'Pinned installation inputs changed')

    def step(name, command, timeout=300):
        identity()
        row = dict(stage=name, started=now())
        record['steps'].append(row)
        record['phase'] = name
        save()
        path = directory / (name + '.log')
        with path.open('x') as stream:
            result = subprocess.run([sys.executable, '-B', 'cluster', *command], cwd=checkout,
                                    stdout=stream, stderr=subprocess.STDOUT, timeout=timeout)
        row.update(exit_code=result.returncode, finished=now(), log_sha256=sha(path))
        save()
        require(result.returncode == 0, name + ' failed; preserve logs and current journals')
        if command == ['check-host']:
            restored = read(state / 'restoration-check.json')
            require(restored['status'] == 'passed' and all(not h['differences'] for h in restored['hosts'].values()),
                    'Host restoration differences remain')
            target = directory / (name + '.json')
            with target.open('x') as stream:
                json.dump(restored, stream, indent=2)
                stream.write('\n')
            row.update(receipt=target.name, receipt_sha256=sha(target))
            save()

    def remote(mode, cid):
        entry = dict(mode=mode, started=now())
        argv = ['sudo', '-n', 'timeout', '--signal=TERM', '--kill-after=5s', '20s',
                'python3', '-B', '-', mode, cid, IMAGE, LABEL, owner, ROLE]
        try:
            result = pair.run('worker', argv, input=REMOTE, timeout=30)
            entry.update(exit_code=result.returncode, stdout=result.stdout, stderr=result.stderr)
        except subprocess.CalledProcessError as exc:
            entry.update(exit_code=exc.returncode, stdout=exc.stdout, stderr=exc.stderr)
        except subprocess.TimeoutExpired as exc:
            entry.update(exit_code=None, timeout=True, stdout=str(exc.stdout), stderr=str(exc.stderr))
        entry['finished'] = now()
        record['probes'].append(entry)
        save()
        require(entry['exit_code'] == 0, 'Remote ' + mode + ' failed; do not retry an uncertain write')
        values = [json.loads(line) for line in entry['stdout'].splitlines() if line.strip()]
        require(bool(values), 'Missing remote evidence')
        return values[-1]

    starter = start_row = start_log = None
    save()
    try:
        step('host-check-before-start', ['check-host'])
        identity()
        start_log = directory / 'start.log'
        start_row = dict(stage='start', started=now())
        record['steps'].append(start_row)
        record['phase'] = 'start'
        save()
        with start_log.open('x') as stream, pair.watch_connection():
            starter = subprocess.Popen([sys.executable, '-B', 'cluster', 'start'], cwd=checkout,
                                       stdout=stream, stderr=subprocess.STDOUT, start_new_session=True)
            deadline = time.monotonic() + 1200
            window_closed = False
            while starter.poll() is None:
                if time.monotonic() > deadline:
                    raise TimeoutError('Python startup exceeded twenty minutes')
                if not record['reclaim_remote_attempts'] and not window_closed:
                    rows = pair.containers('worker')
                    if len(rows) == 1 and rows[0]['State']['Running']:
                        worker = rows[0]
                        require(worker['Image'] == IMAGE and worker['RestartCount'] == 0, 'Worker identity changed')
                        logs = pair.docker('worker', 'logs', '--tail', '100', worker['Id'], timeout=15)
                        content = logs.stdout + logs.stderr
                        if 'allocator ceiling' in content:
                            window_closed = True  # Never reclaim after the ceiling is fixed.
                        elif 'rank 1 capacity:' in content:
                            probe = remote('probe', worker['Id'])
                            if probe['eligible']:
                                identity()
                                record.update(reclaim_remote_attempts=1, reclaim_requested_at=now(),
                                              worker_container=worker['Id'])
                                save()  # Durable attempt marker precedes the only possible write.
                                record['reclaim_result'] = remote('apply', worker['Id'])
                                save()
                time.sleep(1)
            start_row.update(exit_code=starter.returncode, finished=now(), log_sha256=sha(start_log))
            save()
        require(starter.returncode == 0, 'Retained controller start failed')
        identity()
        launch = read(state / 'launch.json')
        active = read(state / 'active.json')
        require(active['running'] is True and active['image'] == launch['image'] == IMAGE,
                'Active Python launch differs')
        require(active['containers'] == launch['containers'], 'Active container identities differ')
        record.update(launch=launch, epochs={}, startup_ceilings_gib_rounded={})
        for host in ('head', 'worker'):
            rows = pair.containers(host)
            require(len(rows) == 1, host + ': expected one owned rank')
            row = rows[0]
            require(row['Id'] == launch['containers'][host] and row['Image'] == IMAGE and row['RestartCount'] == 0
                    and row['State']['Running'] and not row['State']['Paused'] and not row['State']['Restarting'],
                    host + ': live epoch differs')
            record['epochs'][host] = dict(id=row['Id'], image=row['Image'], started=row['State']['StartedAt'], restart_count=0)
            logs = pair.docker(host, 'logs', row['Id'], timeout=20)
            text = logs.stdout + logs.stderr
            path = directory / (host + '-startup.log')
            with path.open('x') as stream:
                stream.write(text)
            values = re.findall(r'allocator ceiling ([0-9.]+) GiB', text)
            require(len(values) == 1 and float(values[0]) >= 108.5, host + ': insufficient startup allocator ceiling')
            record['startup_ceilings_gib_rounded'][host] = float(values[0])
        health = pair.get('/health')
        cap = health['capacity']
        require(health['ok'] and not health.get('busy') and not health['requests_running'], 'Python health is not idle/ready')
        require((cap['shared_pool_tokens'], cap['parallel'], cap['per_request_tokens']) == (8650752, 32, 1048576),
                'Python fallback capacity differs')
        properties = pair.monitor_properties()
        require(properties['ActiveState'] == 'active' and int(properties['MainPID']) > 0, 'Paired monitor inactive')
        record.update(status='started-awaiting-serving-validation', finished=now(), monitor_active=True,
                      shared_pool_tokens=8650752, parallel=32, context_tokens=1048576)
        save()
        print('Pinned Python pair started; run serving validation before accepting rollback. Record: ' + str(output))
    except BaseException as exc:
        record.update(status='failed', error=type(exc).__name__ + ': ' + str(exc))
        save()
        if starter is not None and starter.poll() is None:
            os.killpg(starter.pid, signal.SIGINT)
            try:
                starter.wait(timeout=30)
            except subprocess.TimeoutExpired:
                os.killpg(starter.pid, signal.SIGTERM)
                try:
                    starter.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    os.killpg(starter.pid, signal.SIGKILL)
                    starter.wait(timeout=5)
        if starter is not None and start_row is not None and 'exit_code' not in start_row:
            start_row.update(exit_code=starter.returncode, interrupted=True, finished=now(), log_sha256=sha(start_log))
            save()
        try:
            step('stop-after-failure', ['stop'])
            step('restored-after-failure', ['check-host'])
            record['restoration_status'] = 'passed'
        except BaseException as cleanup:
            record['restoration_status'] = 'failed'
            record['restoration_error'] = type(cleanup).__name__ + ': ' + str(cleanup)
        record['finished'] = now()
        save()
        raise


if __name__ == '__main__':
    main()
