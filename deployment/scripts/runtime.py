"""Owned two-node operations. Installation state lives outside tracked source."""
import contextlib
import fcntl
import hashlib
import json
import os
from pathlib import Path
import pwd
import shlex
import subprocess
import sys
import tempfile
import time
import urllib.request
import uuid

from configuration import SOURCE, STATE, LABEL, ROLE, SUBDIRS, MODEL, fingerprint, profile, read, validate, launch_args, source_revision


def now():
    import datetime
    return datetime.datetime.now(datetime.timezone.utc).isoformat()


def atomic(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_name(path.name+'.tmp')
    with temp.open('w') as f:
        json.dump(value, f, indent=2, sort_keys=True)
        f.write('\n'); f.flush(); os.fsync(f.fileno())
    temp.chmod(0o600)
    temp.replace(path)
    fd = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


SNAPSHOT = r'''import json,pathlib,re,subprocess
def cmd(args):
 p=subprocess.run(args,capture_output=True,text=True,timeout=20)
 return p.stdout.strip()
p=pathlib.Path('/sys/module/nvidia_drm/parameters')
print(json.dumps(dict(boot_id=pathlib.Path('/proc/sys/kernel/random/boot_id').read_text().strip(),
 display_manager=cmd(['systemctl','is-active','display-manager']),
 modeset=(p/'modeset').read_text().strip() if (p/'modeset').exists() else None,
 fbdev=(p/'fbdev').read_text().strip() if (p/'fbdev').exists() else None,
 modules={n:pathlib.Path('/sys/module',n).exists() for n in ('nvidia_drm','nvidia_modeset')},
 cards={d.name:(d/'device/driver').resolve().name for d in pathlib.Path('/sys/class/drm').glob('card*') if re.fullmatch(r'card\d+',d.name)},
 addresses=json.loads(cmd(['ip','-j','-4','addr'])),
 driver=cmd(['nvidia-smi','--query-gpu=name,driver_version','--format=csv,noheader']),
 kernel=cmd(['uname','-r']))))
'''

ROOTS = '''import json,os,pathlib,sys
p=json.load(sys.stdin);root=pathlib.Path(p['root'])
if root.resolve()!=root or root.is_symlink():raise ValueError('Data root or parent is a symlink')
marker=root/'.spark-owned.json'
if p['init']:
 if root.exists() and not marker.exists() and any(root.iterdir()):raise ValueError('Refusing to adopt a nonempty directory')
 root.mkdir(parents=True,exist_ok=True)
 if not marker.exists():
  with marker.open('x') as f:
   json.dump({'deployment_id':p['id']},f);f.flush();os.fsync(f.fileno())
if marker.is_symlink() or json.loads(marker.read_text())['deployment_id']!=p['id']:raise ValueError('Data-root ownership differs')
for name in p['subdirs']:
 d=root/name
 if d.is_symlink() or d.resolve()!=d:raise ValueError('Data subdirectory is redirected')
 if p['init']:d.mkdir(exist_ok=True)
 if not d.is_dir():raise ValueError('Missing data subdirectory')
print('Owned data root verified')
'''

FABRIC = '''import ipaddress,json,pathlib,re,subprocess,sys
p=json.load(sys.stdin)
links=json.loads(subprocess.check_output(['ip','-j','-4','addr'],text=True))
links={r['ifname']:r for r in links};out=[]
for rail in p:
 dev,net=rail['hca'],rail['interface'];base=pathlib.Path('/sys/class/infiniband')/dev/'ports/1'
 if 'ACTIVE' not in (base/'state').read_text():raise ValueError(dev+': port inactive')
 link=links[net]
 if link['mtu']!=9000:raise ValueError(net+': MTU 9000 required; no network settings are changed')
 if rail['address'] not in {a['local'] for a in link.get('addr_info',[])}:raise ValueError(net+': configured address absent')
 info=subprocess.check_output(['ibv_devinfo','-d',dev],text=True)
 if not re.search(r'active_mtu:\\s+4096\\s',info):raise ValueError(dev+': RDMA MTU 4096 required')
 choices=[]
 for f in sorted((base/'gids').iterdir(),key=lambda f:int(f.name)):
  ip=ipaddress.IPv6Address(f.read_text().strip()).ipv4_mapped
  if (str(ip)==rail['address'] and (base/'gid_attrs/types'/f.name).read_text().strip()=='RoCE v2'
      and (base/'gid_attrs/ndevs'/f.name).read_text().strip()==net):choices.append(int(f.name))
 if not choices:raise ValueError(dev+': missing matching IPv4 RoCE-v2 GID')
 out.append(dict(rail,gid_index=choices[0],mtu=9000,rdma_mtu=4096))
print(json.dumps(out))
'''


class Pair:
    def __init__(self, config, state=STATE):
        self.config = validate(config)
        self.state = Path(state)

    def _ssh(self):
        return ['ssh','-T','-o','BatchMode=yes','-o','ConnectTimeout=10',
                '-o','ServerAliveInterval=15','-o','ServerAliveCountMax=3',
                '-o','StrictHostKeyChecking=yes','-o','UpdateHostKeys=no']

    @contextlib.contextmanager
    def watch_connection(self):
        """Reuse one private SSH login for polling; never edit the user's SSH config.

        A short socket path avoids Unix-domain path limits in long checkouts.
        ControlPersist bounds an orphan's idle lifetime if the watcher is killed;
        the systemd monitor also owns its children in the same service cgroup.
        """
        if getattr(self, '_worker_control', None) is not None:
            raise RuntimeError('Watch connection already open')
        try:
            temporary = tempfile.TemporaryDirectory(prefix='deepseek-watch-', dir='/tmp')
        except OSError as exc:
            # Reuse is an optimization, not a prerequisite for memory safety.
            print('Watch SSH reuse unavailable: '+type(exc).__name__, file=sys.stderr, flush=True)
            yield
            return
        with temporary as directory:
            control = Path(directory)/'ssh'
            self._worker_control = control
            try:
                yield
            finally:
                self._worker_control = None
                if control.exists():
                    try:
                        subprocess.run([*self._ssh(), '-o', 'ControlPath='+str(control),
                                        '-O', 'exit', self.config['worker']['ssh']],
                                       capture_output=True, text=True, timeout=5, check=False)
                    except (OSError, subprocess.TimeoutExpired):
                        # Do not replace a failure being handled by paired stop.
                        # With no clients, ControlPersist closes the master shortly.
                        pass

    def run(self, host, args, **kwargs):
        args = [str(a) for a in args]
        if host == 'worker':
            options = []
            control = getattr(self, '_worker_control', None)
            if control is not None:
                options = ['-o','ControlMaster=auto','-o','ControlPersist=30',
                           '-o','ControlPath='+str(control)]
            args = [*self._ssh(), *options, self.config['worker']['ssh'], shlex.join(args)]
        elif host != 'head':
            raise ValueError('Unknown host')
        return subprocess.run(args, capture_output=True, text=True, check=True, **kwargs)

    def docker(self, host, *args, **kwargs):
        return self.run(host, ['sudo','-n','docker',*args], **kwargs)

    def sudo(self, host, *args):
        return self.run(host, ['sudo','-n',*args], timeout=60)

    @contextlib.contextmanager
    def lock(self):
        self.state.mkdir(parents=True, exist_ok=True, mode=0o700)
        with (self.state/'operation.lock').open('w') as f:
            fcntl.flock(f, fcntl.LOCK_EX | fcntl.LOCK_NB)
            yield

    def ownership(self):
        value = read(self.state/'ownership.json')
        if value['config_sha256'] != fingerprint(self.config):
            raise ValueError('Configuration changed since init; use .local/installed.json to stop/restore the original pair')
        uuid.UUID(value['deployment_id'])
        return value['deployment_id']

    def roots(self, host, init=False):
        return self.run(host, ['python3','-B','-c',ROOTS], input=json.dumps(dict(
            root=self.config[host]['data_root'], id=self.ownership(), init=init, subdirs=SUBDIRS)), timeout=30)

    def snapshot(self, host):
        return json.loads(self.sudo(host,'python3','-B','-c',SNAPSHOT).stdout)

    def initialize(self):
        # Capture the baseline before deployment activity on otherwise idle hosts.
        for host in ('head','worker'):
            self.idle(host)
        path = self.state/'ownership.json'
        if not path.exists():
            atomic(self.state/'installed.json', self.config)
            atomic(path, dict(deployment_id=str(uuid.uuid4()), config_sha256=fingerprint(self.config), created=now()))
        self.ownership()
        # Refuses nonempty or redirected roots; never adopts another deployment.
        for host in ('head','worker'):
            self.roots(host, init=True)
            baseline = self.state/('baseline-'+host+'.json')
            if not baseline.exists():
                atomic(baseline, self.snapshot(host))

    def containers(self, host):
        ids = self.docker(host,'ps','-aq','--filter','label='+LABEL+'='+self.ownership(),
                          '--filter','label='+ROLE+'=inference',timeout=30).stdout.split()
        return json.loads(self.docker(host,'inspect',*ids,timeout=30).stdout) if ids else []

    def fabric(self, host):
        rows = json.loads(self.run(host,['python3','-B','-c',FABRIC],
                         input=json.dumps(self.config[host]['rails']),timeout=30).stdout)
        if len({r['gid_index'] for r in rows}) != 1:
            raise ValueError(host+': different GID indices across the two rails')
        return rows

    def memory(self, host):
        return {line.split(':')[0]:int(line.split()[1])*1024
                for line in self.run(host,['cat','/proc/meminfo'],timeout=20).stdout.splitlines()
                if len(line.split()) > 1 and line.split()[1].isdigit()}

    def idle(self, host):
        if self.docker(host,'ps','-q',timeout=30).stdout.strip():
            raise RuntimeError(host+': containers are running; refusing display/module changes')
        if self.run(host,['nvidia-smi','--query-compute-apps=pid','--format=csv,noheader'],timeout=30).stdout.strip():
            raise RuntimeError(host+': a compute workload is running')

    def restore_display(self, host):
        path = self.state/('drm-'+host+'.json')
        if not path.exists():
            return
        rec = read(path)
        if rec['deployment_id'] != self.ownership():
            raise RuntimeError('Display journal ownership differs')
        if not rec['active']:
            return
        self.idle(host)
        before, current = rec['before'], self.snapshot(host)
        fields = ('modeset','fbdev','display_manager','modules')
        if current['boot_id'] == before['boot_id']:
            change = (current['modeset'],current['fbdev']) != (before['modeset'],before['fbdev'])
            if current['display_manager'] == 'active' and change:
                self.sudo(host,'systemctl','stop','display-manager')
            if change:
                if current['modules']['nvidia_drm']:
                    self.sudo(host,'modprobe','-r','nvidia_drm')
                self.sudo(host,'modprobe','nvidia_drm','modeset='+str(int(before['modeset']=='Y')),
                          'fbdev='+str(int(before['fbdev']=='Y')))
                self.sudo(host,'udevadm','settle','--timeout=15')
            if self.snapshot(host)['display_manager'] != before['display_manager']:
                self.sudo(host,'systemctl','start' if before['display_manager']=='active' else 'stop','display-manager')
            current = self.snapshot(host)
        # After reboot, compare with the journal but never impose stale runtime settings.
        if any(current[k] != before[k] for k in fields):
            raise RuntimeError(host+': original display state differs; journal retained for review')
        atomic(path,dict(rec,active=False,restored=now(),restored_state=current))

    def apply_display(self, host):
        if not self.config['allow_temporary_drm']:
            raise ValueError('This profile requires explicit allow_temporary_drm=true')
        self.roots(host); self.idle(host)
        path = self.state/('drm-'+host+'.json')
        if path.exists() and read(path)['active']:
            raise RuntimeError('Restore the existing display journal first')
        before = self.snapshot(host)
        if before['display_manager'] not in ('active','inactive') or any(before[k] not in ('Y','N') for k in ('modeset','fbdev')):
            raise RuntimeError('Driver/display state is not covered by reversible setup')
        rec = dict(time=now(),deployment_id=self.ownership(),active=True,before=before)
        atomic(path,rec)
        try:
            if before['display_manager'] == 'active':
                self.sudo(host,'systemctl','stop','display-manager')
            if (before['modeset'],before['fbdev']) != ('Y','N'):
                self.sudo(host,'modprobe','-r','nvidia_drm')
                self.sudo(host,'modprobe','nvidia_drm','modeset=1','fbdev=0')
                self.sudo(host,'udevadm','settle','--timeout=15')
            after = self.snapshot(host)
            if (after['modeset'],after['fbdev'],after['display_manager']) != ('Y','N','inactive'):
                raise RuntimeError('Temporary display settings did not apply')
            atomic(path,dict(rec,after=after))
        except BaseException:
            self.restore_display(host)
            raise

    def unit(self):
        return 'deepseek-spark-'+self.ownership()[:8]+'.service'

    def monitor_properties(self):
        result = self.run('head',['systemctl','show',self.unit(),'-p',
                         'LoadState,ActiveState,MainPID,Description,User,WorkingDirectory,Transient,ExecStart'],timeout=20)
        return dict(line.split('=',1) for line in result.stdout.splitlines() if '=' in line)

    def stop_monitor(self):
        # A missing unit is normal. systemctl show may return nonzero for it.
        try:
            props = self.monitor_properties()
        except subprocess.CalledProcessError as exc:
            if 'LoadState=not-found' in (exc.stdout or ''):
                return
            raise
        if props.get('LoadState') == 'not-found':
            return
        if (props.get('Description') != 'DeepSeek Spark '+self.ownership()
                or props.get('User') != pwd.getpwuid(os.getuid()).pw_name
                or props.get('WorkingDirectory') != str(SOURCE)
                or props.get('Transient') != 'yes'
                or str(SOURCE/'deployment/scripts/cli.py') not in props.get('ExecStart','')):
            raise RuntimeError('Monitor unit ownership differs')
        if int(props.get('MainPID',0)) != os.getpid():
            self.sudo('head','systemctl','stop',self.unit())

    def start_monitor(self):
        self.sudo('head','systemd-run','--quiet','--collect','--unit',self.unit(),
            '--description','DeepSeek Spark '+self.ownership(), '--property','Type=exec',
            '--property','User='+pwd.getpwuid(os.getuid()).pw_name,
            '--property','WorkingDirectory='+str(SOURCE), '--property','Restart=no',
            '--property','TimeoutStopSec=15', '--property','StandardOutput=append:'+str(self.state/'monitor.log'),
            '--property','StandardError=inherit', '/usr/bin/python3','-B',str(SOURCE/'deployment/scripts/cli.py'),
            '--config',str(self.state/'installed.json'),'watch')
        props = self.monitor_properties()
        if props.get('ActiveState') != 'active' or int(props.get('MainPID',0)) <= 0:
            raise RuntimeError('Paired monitor did not stay active')

    def stop(self):
        self.ownership()
        errors = []
        try:
            self.stop_monitor()
        except Exception as exc:
            errors.append('monitor: '+str(exc))
        for host in ('worker','head'):
            try:
                for row in self.containers(host):
                    if row['Config']['Labels'].get(LABEL) != self.ownership():
                        raise RuntimeError('Container ownership differs')
                    if row['State']['Running']:
                        self.docker(host,'stop','--time','30',row['Id'],timeout=60)
                    logs = self.docker(host,'logs','--timestamps',row['Id'],timeout=30)
                    (self.state/(host+'-'+row['Id'][:12]+'.log')).write_text(logs.stdout+logs.stderr)
                    atomic(self.state/'stops'/(host+'-'+row['Id'][:12]+'.json'),
                           dict(time=now(),container=row['Id'],image=row['Image'],before=row['State']))
                    self.docker(host,'rm',row['Id'],timeout=30)
            except Exception as exc:
                errors.append(host+': '+str(exc))
        if errors:
            raise RuntimeError('Paired stop incomplete: '+'; '.join(errors))
        for host in ('worker','head'):
            try:
                self.restore_display(host)
            except Exception as exc:
                errors.append(host+': '+str(exc))
        if errors:
            raise RuntimeError('Display restoration incomplete: '+'; '.join(errors))
        atomic(self.state/'active.json',dict(running=False,time=now()))

    def get(self, path, timeout=10):
        bind = self.config['api']['bind']
        address = '127.0.0.1' if bind == '0.0.0.0' else bind
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
        with opener.open('http://'+address+':'+str(self.config['api']['port'])+path,timeout=timeout) as r:
            return json.load(r)

    def doctor(self):
        result = {}
        for host in ('head','worker'):
            result[host] = dict(rails=self.fabric(host), memory_available_gib=self.memory(host)['MemAvailable']/2**30,
                                display=self.snapshot(host))
        return result

    def start(self):
        if not self.config['allow_temporary_drm']:
            raise ValueError('Set allow_temporary_drm=true after reviewing the display takeover and rollback')
        self.ownership()
        build = read(self.state/'build.json')
        if build['revision'] != source_revision():
            raise RuntimeError('Source/profile differs from the selected image; rebuild and qualify it first')
        if any(self.containers(h) for h in ('head','worker')):
            raise RuntimeError('Owned rank containers exist; stop the pair before another start')
        from assets import verify
        p = profile(); image = build['id']
        if read(self.state/'precompile.json')['image'] != image:
            raise RuntimeError('Precompile the selected image with model weights unloaded')
        rails, cards = {}, {}
        prepared_readonly = (self.state/'prepared-import.json').exists()
        prepared = read(self.state/'prepared-import.json') if prepared_readonly else None
        if prepared and (set(prepared['hosts'])!={'head','worker'} or prepared['weights_source_sha256']!=hashlib.sha256(
                (SOURCE/'src/tensorfold/families/deepseek_v41/cuda/weights.py').read_bytes()).hexdigest()):
            raise RuntimeError('Imported prepared cache is incomplete or its loader source changed')
        for host in ('head','worker'):
            self.roots(host); self.idle(host); verify(self,host,full=False)
            if prepared:
                code="import json,pathlib,sys\np=pathlib.Path(sys.argv[1]);expected=json.loads(sys.argv[2]);s=p.stat()\nif p.is_symlink() or [s.st_dev,s.st_ino,s.st_size,s.st_mtime_ns,s.st_ctime_ns]!=expected:raise ValueError('Imported prepared cache fingerprint changed')\n"
                row=prepared['hosts'][host]
                self.run(host,['python3','-B','-c',code,self.config[host]['data_root']+'/prepared/'+row['name'],
                               json.dumps(row['fingerprint'])],timeout=30)
            row = json.loads(self.docker(host,'image','inspect',image,timeout=30).stdout)[0]
            if row['Id'] != image:
                raise RuntimeError('Image ID differs')
            if self.memory(host)['MemAvailable'] < 112*2**30:
                raise RuntimeError(host+': need at least 112 GiB available before loading')
            rails[host] = self.fabric(host)
            code = "import socket,sys\nfor p in sys.argv[1:]:\n with socket.socket() as s:\n  s.setsockopt(socket.SOL_SOCKET,socket.SO_REUSEADDR,1);s.bind(('0.0.0.0',int(p)));s.listen(1)\n"
            self.run(host,['python3','-B','-c',code,str(self.config['api']['port']),str(self.config['master_port'])],timeout=20)
        started = {}
        try:
            for host in ('head','worker'):
                self.apply_display(host)
                # Reloading the module can change the DRM minor number.
                found = [k for k,v in self.snapshot(host)['cards'].items() if v=='nvidia']
                if len(found) != 1:
                    raise RuntimeError('Expected exactly one NVIDIA DRM card after display setup')
                cards[host] = '/dev/dri/'+found[0]
            for host in ('worker','head'):
                args = launch_args(self.config,host,self.ownership(),image,rails[host],cards[host],
                                   prepared_readonly=prepared_readonly)
                started[host] = self.docker(host,*args,timeout=90).stdout.strip()
            atomic(self.state/'launch.json',dict(time=now(),config=self.config,profile=p,image=image,containers=started))
            deadline = time.monotonic()+3600
            while time.monotonic() < deadline:
                for host in ('head','worker'):
                    rows = self.containers(host)
                    if len(rows)!=1 or not rows[0]['State']['Running']:
                        raise RuntimeError(host+': rank exited during startup')
                    if self.memory(host)['MemAvailable'] < p['minimum_available_gib']*2**30:
                        raise RuntimeError(host+': host memory floor crossed during startup')
                try:
                    health = self.get('/health',3)
                    if health['ok'] and health.get('capacity',{}).get('shared_pool_tokens') == 8650752:
                        break
                except (OSError,ValueError,KeyError):
                    pass
                time.sleep(5)
            else:
                raise TimeoutError('Pair startup timed out')
            atomic(self.state/'active.json',dict(time=now(),running=True,image=image,containers=started))
            self.start_monitor()
        except BaseException:
            self.stop()
            raise

    def watch(self):
        with self.watch_connection():
            self._watch()

    def _watch(self):
        from memory_watch import History, health_sample, host_sample
        expected = read(self.state/'launch.json')
        history = History(self.state/'memory')
        floor = int(expected['profile']['minimum_available_gib']*2**30)
        last_health = None
        last_health_at = None
        last_hosts = {}
        next_detail = 0.0
        failed = 0; previous = None; changed = time.monotonic()
        while True:
            reason = None
            sample = dict(schema=1, time=now(), minimum_available_bytes=floor,
                          image=expected['image'], hosts={})
            detail = time.monotonic() >= next_detail
            if detail:
                next_detail = time.monotonic()+60
            try:
                for host in ('head','worker'):
                    stage, kind = host+':container', 'rank-state'
                    rows = self.containers(host)
                    if (len(rows)!=1 or not rows[0]['State']['Running']
                            or rows[0]['Id']!=expected['containers'][host]):
                        raise RuntimeError(host+': rank absent, exited or replaced')
                    stage, kind = host+':memory-probe', 'host-probe'
                    host_memory = host_sample(self, host, rows[0]['State']['Pid'],
                                              floor_bytes=floor, detail=detail)
                    sample['hosts'][host] = host_memory
                    last_hosts[host] = (sample['time'], time.monotonic(), host_memory)
                    stage, kind = host+':memory-floor', 'host-floor'
                    if host_memory['meminfo']['MemAvailable'] < floor:
                        raise RuntimeError(host+': host memory floor crossed')
                stage, kind = 'api:health', 'api-health'
                health = self.get('/health')
                last_health = sample['health'] = health_sample(health)
                last_health_at = time.monotonic()
                if not health.get('ok') or health.get('fatal'):
                    raise RuntimeError('API reports an unhealthy runtime')
                stage, kind = 'scheduler:progress', 'scheduler-stall'
                progress = (health.get('requests_total'),health.get('completion_tokens_total'),
                            json.dumps(health.get('progress',{}),sort_keys=True))
                if progress != previous or not health.get('busy'):
                    previous,changed = progress,time.monotonic()
                if health.get('busy') and time.monotonic()-changed>300:
                    raise RuntimeError('No scheduler progress for 300 seconds')
                failed = 0
            except Exception as exc:
                reason = str(exc); failed += 1
                sample['failure_stage'] = stage
                sample['failure_kind'] = (kind+'-timeout' if isinstance(exc, (TimeoutError, subprocess.TimeoutExpired))
                                          else kind)
                sample['exception_type'] = type(exc).__name__
            sample['failure_count'] = failed
            if reason:
                sample['reason'] = reason
                if last_health_at is not None:
                    sample['last_health_age_seconds'] = round(time.monotonic()-last_health_at, 3)
            try:
                history.append(sample)
            except Exception as exc:
                print('Memory history recording failed: '+type(exc).__name__, file=sys.stderr, flush=True)
            if failed >= 2:
                try:
                    # A head failure can precede the worker probe. Preserve the
                    # previous observation with its age, without delaying a
                    # required shutdown to fetch another host sample.
                    last_known = {host: dict(time=stamp, age_seconds=round(time.monotonic()-at, 3),
                                           current_cycle=host in sample['hosts'], sample=values)
                                  for host, (stamp, at, values) in last_hosts.items()}
                    atomic(self.state/'fault.json',dict(time=now(),reason=reason,
                           sample=sample,last_health=last_health,last_known_hosts=last_known,
                           recent_samples=list(history.recent)))
                finally:
                    # Even a full/read-only history filesystem must not prevent
                    # the original paired cleanup and host restoration.
                    with self.lock():
                        self.stop()
                return
            time.sleep(5)
