"""Validate installation-specific settings; importing this module does no I/O."""
import hashlib
import ipaddress
import json
import re
import subprocess
from pathlib import Path, PurePosixPath

SOURCE = Path(__file__).resolve().parents[2]
CONFIG = SOURCE / 'deployment/config'
STATE = SOURCE / 'deployment/.local'
LABEL = 'org.deepseek-spark.deployment'
ROLE = 'org.deepseek-spark.role'
MODEL = 'DeepSeek-V4.1-Flash-Keys'
BASE_IMAGE = 'nvcr.io/nvidia/pytorch@sha256:7531d90bcbe0e43e1f7363029c7e145ce90eebeb494a7b4695fdba0329d7c3c3'
SUBDIRS = ('stock-model', 'overlays', 'original', 'model', 'engram', 'vision-extra',
           'prepared', 'kernel-cache', 'state')


def read(path):
    return json.loads(Path(path).read_text())


def fingerprint(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(',', ':')).encode()).hexdigest()


def validate(value):
    if not isinstance(value, dict) or set(value) != {
            'schema', 'name', 'head', 'worker', 'api', 'master_port', 'allow_temporary_drm'}:
        raise ValueError('Expected the complete cluster.example.json schema; unknown keys are rejected')
    if type(value['schema']) is not int or value['schema'] != 1 or not re.fullmatch(r'[a-z][a-z0-9-]{2,39}', str(value['name'])):
        raise ValueError('Invalid schema or deployment name')
    for host in ('head', 'worker'):
        node = value[host]
        if set(node) != ({'data_root', 'rails', 'ssh'} if host == 'worker' else {'data_root', 'rails'}):
            raise ValueError(host + ': unknown or missing node fields')
        root = PurePosixPath(node['data_root'])
        # These become bind mounts and owned roots. Do not permit shell/mount syntax or broad roots.
        if (not root.is_absolute() or str(root) != node['data_root'] or '..' in root.parts
                or len(root.parts) < 3 or not re.fullmatch(r'/[A-Za-z0-9_./-]+', str(root))
                or root.parts[1] in ('etc', 'proc', 'sys', 'dev', 'boot', 'usr', 'bin', 'sbin', 'lib', 'lib64')
                or (root.parts[1] == 'home' and len(root.parts) < 4)):
            raise ValueError(host + ': choose a dedicated absolute data directory')
        if not isinstance(node['rails'], list) or len(node['rails']) != 2:
            raise ValueError(host + ': exactly two RoCE rails are required by this qualified profile')
        for rail in node['rails']:
            if set(rail) != {'hca', 'interface', 'address'}:
                raise ValueError(host + ': unknown rail fields')
            if any(not re.fullmatch(r'[A-Za-z0-9_.-]+', rail[k]) for k in ('hca', 'interface')):
                raise ValueError(host + ': invalid rail device name')
            ip = ipaddress.IPv4Address(rail['address'])
            if ip.is_unspecified or ip.is_multicast or ip.is_loopback:
                raise ValueError(host + ': rail address must be a unicast IPv4 address')
        for field in ('hca', 'interface', 'address'):
            if len({r[field] for r in node['rails']}) != 2:
                raise ValueError(host + ': rail ' + field + ' values must be distinct')
    ssh = value['worker']['ssh']
    if not isinstance(ssh, str) or not re.fullmatch(r'[A-Za-z_][A-Za-z0-9_-]*@[A-Za-z0-9][A-Za-z0-9.-]*', ssh):
        raise ValueError('worker.ssh must be user@host; use SSH config for identity/port settings')
    if set(value['api']) != {'bind', 'port', 'allow_unauthenticated_lan'}:
        raise ValueError('Unknown API settings')
    bind = ipaddress.IPv4Address(value['api']['bind'])
    if bind.is_multicast:
        raise ValueError('API bind must be a local unicast address or 0.0.0.0')
    if type(value['api']['allow_unauthenticated_lan']) is not bool:
        raise ValueError('allow_unauthenticated_lan must be a boolean')
    if not bind.is_loopback and not value['api']['allow_unauthenticated_lan']:
        raise ValueError('A LAN bind requires explicit allow_unauthenticated_lan=true')
    for port in (value['api']['port'], value['master_port']):
        if type(port) is not int or not 1024 <= port <= 65535:
            raise ValueError('Ports must be integer values from 1024 through 65535')
    if value['api']['port'] == value['master_port']:
        raise ValueError('API and rendezvous ports must differ')
    if type(value['allow_temporary_drm']) is not bool:
        raise ValueError('allow_temporary_drm must be a boolean')
    head = {r['address'] for r in value['head']['rails']}
    worker = {r['address'] for r in value['worker']['rails']}
    if head & worker:
        raise ValueError('Head and worker rail addresses must differ')
    return value


def load(path):
    return validate(read(path))


def source_revision():
    if subprocess.check_output(['git','status','--porcelain'],cwd=SOURCE,text=True).strip():
        raise RuntimeError('Commit the reviewed source before building or starting a pinned image')
    return subprocess.check_output(['git','rev-parse','HEAD'],cwd=SOURCE,text=True).strip()


def profile():
    value = read(CONFIG / 'profile.json')
    costs = read(CONFIG / value['cost_model_file'])
    serialized = json.dumps(costs, sort_keys=True, separators=(',', ':'))
    if hashlib.sha256(serialized.encode()).hexdigest() != value['cost_model_sha256']:
        raise ValueError('Qualified draft-cost table changed')
    value['environment']['TF_DS_COST_MODEL_JSON'] = serialized
    return value


def launch_args(config, host, deployment_id, image, rails, drm_card='/dev/dri/card0', *, prepared_readonly=False):
    """Pure command rendering; GID indices and DRM card come from host preflight."""
    validate(config)
    if not re.fullmatch(r'[0-9a-f-]{36}', deployment_id):
        raise ValueError('An installation UUID is required')
    if host not in ('head', 'worker') or len(rails) != 2:
        raise ValueError('Expected one of the two ranks and its validated rails')
    if len({r['gid_index'] for r in rails}) != 1:
        raise ValueError('Both rails must have the same IPv4 RoCE-v2 GID index')
    p = profile()
    rank = 0 if host == 'head' else 1
    node = config[host]
    root = PurePosixPath(node['data_root'])
    env = {
        'HF_HUB_OFFLINE': '1', 'TENSORFOLD_NO_UPDATE_CHECK': '1',
        'OMP_NUM_THREADS': '4', 'MAX_JOBS': '4', 'PYTHONDONTWRITEBYTECODE': '1',
        'NCCL_DEBUG': 'INFO', 'NCCL_IB_DISABLE': '0', 'NCCL_NET': 'IB',
        'NCCL_IB_HCA': '=' + ','.join(r['hca'] for r in rails),
        'NCCL_SOCKET_IFNAME': '=' + rails[0]['interface'],
        'NCCL_IB_GID_INDEX': str(rails[0]['gid_index']),
        'GLOO_SOCKET_IFNAME': rails[0]['interface'],
        'TF_RDMA_DEVICES': ','.join(r['hca'] for r in rails),
        'TF_DS_ENGRAM': '/engram', 'TF_DS_VISION_EXTRA': '/vision-extra',
        'TF_DS_RANK_CACHE': '/prepared', 'TF_DS_RANK_CACHE_READERS': '16',
        'TF_DS_TOKEN_MAP': '/cache/token-map.json',
        'TORCH_EXTENSIONS_DIR': '/cache/torch_extensions', 'TRITON_CACHE_DIR': '/cache/triton',
        'CUDA_CACHE_PATH': '/cache/nv/ComputeCache', 'XDG_CACHE_HOME': '/cache',
        'TF_CARVEOUT': '1', 'TF_DRM_CARD': drm_card,
    }
    env.update(p['environment'])
    args = ['run', '-d', '--init', '--name', config['name']+'-'+deployment_id[:8]+'-r'+str(rank),
            '--label', LABEL+'='+deployment_id, '--label', ROLE+'=inference', '--restart', 'no',
            '--gpus', 'all', '--network', 'host', '--ipc', 'private', '--shm-size', '2g',
            '--device', '/dev/infiniband', '--device', '/dev/dri', '--ulimit', 'memlock=-1',
            '--cap-add', 'IPC_LOCK', '--pids-limit', '4096', '--log-opt', 'max-size=50m',
            '--log-opt', 'max-file=3']
    for sub, mount, ro in [('model','/model',True), ('engram','/engram',True),
                           ('vision-extra','/vision-extra',True), ('prepared','/prepared',prepared_readonly),
                           ('kernel-cache','/cache',False), ('state','/state',False)]:
        args += ['-v', str(root/sub)+':'+mount+(':ro' if ro else '')]
    for key, value in sorted(env.items()):
        args += ['-e', key+'='+str(value)]
    args += [image, 'serve', '/model', '--tp', '2', '--rank', str(rank),
             '--master', config['head']['rails'][0]['address'], '--master-port', str(config['master_port']),
             '--context', str(p['context']), '--parallel', str(p['parallel']),
             '--mtp-drafts', str(p['drafts']), '--no-update-check', '--vision']
    if rank == 0:
        args += ['--host', config['api']['bind'], '--port', str(config['api']['port']),
                 '--name', MODEL, '--alias', 'deepseek-v4.1-flash', '--max-tokens', '32768']
    return args
