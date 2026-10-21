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
MODEL = 'DeepSeek-V4.1-Flash-1017'
BASE_IMAGE = 'nvcr.io/nvidia/pytorch@sha256:7531d90bcbe0e43e1f7363029c7e145ce90eebeb494a7b4695fdba0329d7c3c3'
SUBDIRS = ('stock-model', 'overlays', 'original', 'model', 'engram', 'vision-extra',
           'prepared', 'kernel-cache', 'state', 'native-kit')


def read(path):
    return json.loads(Path(path).read_text())


def fingerprint(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(',', ':')).encode()).hexdigest()


def prepared_producer():
    # Legacy files are imported read-only and then checked tensor-for-tensor by
    # the native loader. This pin is provenance, not a compatibility assertion.
    return read(CONFIG/'native-inputs.json')['prepared_cache_producer']


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


def profile(weight_variant=None):
    if weight_variant is None:
        selection = STATE/'variant.json'
        weight_variant = read(selection)['variant'] if selection.exists() else 'stock'
    if weight_variant not in ('stock','keys'):
        raise ValueError('Weight variant must be stock or keys')
    value = read(CONFIG / 'profile.json')
    if value['engine'] != 'native-zig':
        raise ValueError('This controller requires the native Zig profile')
    for field in ('context', 'pool_tokens', 'parallel'):
        if type(value[field]) is not int or value[field] <= 0:
            raise ValueError('Invalid native profile capacity')
    if value['parallel'] > 32 or value['context'] > 1048576 or value['pool_tokens'] < value['context']:
        raise ValueError('Native profile exceeds the implemented capacity')
    if value['drafts'] != 5:
        raise ValueError('The pinned native drafter has a five-token block; disable drafts per request when needed')
    if 'TF_DS_WEIGHT_OVERLAY' in value['environment']:
        raise ValueError('Select the verified Keys variant instead of overriding its path')
    value['weight_variant'] = weight_variant
    value['keys_overlay'] = weight_variant == 'keys'
    if weight_variant == 'keys':
        value['name'] += '-keys'
        value['description'] = 'Stock Mia EAQ 1017 2.9 bpw with separately prepared matching Keys K5 wo_b replacements'
    return value


def launch_args(config, host, deployment_id, image, rails, drm_card='/dev/dri/card0', *, prepared_readonly=False,
                weight_variant='stock'):
    """Pure command rendering; GID indices and DRM card come from host preflight."""
    validate(config)
    if not re.fullmatch(r'[0-9a-f-]{36}', deployment_id):
        raise ValueError('An installation UUID is required')
    if host not in ('head', 'worker') or len(rails) != 2:
        raise ValueError('Expected one of the two ranks and its validated rails')
    if len({r['gid_index'] for r in rails}) != 1:
        raise ValueError('Both rails must have the same IPv4 RoCE-v2 GID index')
    p = profile(weight_variant)
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
        'TF_RDMA_GID_INDEX': str(rails[0]['gid_index']),
        'TF_RDMA_DEVICES': ','.join(r['hca'] for r in rails),
        'TF_TP_WORLD': '2', 'TF_TP_MASTER': config['head']['rails'][0]['address'],
        'TF_TP_PORT': str(config['master_port']),
        'TF_DS_ENGRAM': '/engram',
        'TF_DS_RANK_CACHE': '/prepared', 'TF_DS_RANK_CACHE_READERS': '16',
        'TF_DS_TOKEN_MAP': '/cache/token-map.json',
        'CUDA_CACHE_PATH': '/cache/nv/ComputeCache', 'XDG_CACHE_HOME': '/cache',
        'TF_CARVEOUT': '1', 'TF_DRM_CARD': drm_card,
    }
    env.update(p['environment'])
    if weight_variant == 'keys':
        env['TF_DS_WEIGHT_OVERLAY'] = '/weight-overlay'
    aliases = {'deepseek-v4.1-flash': p['context']}
    for stem in (MODEL, 'deepseek-v4.1-flash'):
        for suffix, tokens in (('262k',262144),('524k',524288),('614k',614400),('1m',1048576)):
            if tokens <= p['context']:
                aliases[stem+'-'+suffix] = tokens
    env['TENSORFOLD_MODEL_CONTEXTS'] = json.dumps(aliases, separators=(',',':'))
    args = ['run', '-d', '--init', '--name', config['name']+'-'+deployment_id[:8]+'-r'+str(rank),
            '--label', LABEL+'='+deployment_id, '--label', ROLE+'=inference', '--restart', 'no',
            '--gpus', 'all', '--network', 'host', '--ipc', 'private', '--shm-size', '2g',
            '--device', '/dev/infiniband', '--device', '/dev/dri', '--ulimit', 'memlock=-1',
            '--cap-add', 'IPC_LOCK', '--pids-limit', '4096', '--log-opt', 'max-size=50m',
            '--log-opt', 'max-file=3']
    for sub, mount, ro in [('model','/model',True), ('engram','/engram',True),
                           ('vision-extra','/vision-extra',True), ('prepared','/prepared',True),
                           ('native-kit','/kit',True),
                           ('kernel-cache','/cache',False), ('state','/state',False)]:
        args += ['-v', str(root/sub)+':'+mount+(':ro' if ro else '')]
    if weight_variant == 'keys':
        args += ['-v',str(root/'overlays/keys-1017/prepared')+':/weight-overlay:ro']
    for key, value in sorted(env.items()):
        args += ['-e', key+'='+str(value)]
    if rank == 0:
        args += ['--entrypoint','/opt/tensorfold/bin/tensorfold-native', image, 'serve', '/model',
                 '--context',str(p['context']),'--parallel',str(p['parallel']),
                 '--prompt-cache-gib','0.5','--host',config['api']['bind'],'--port',str(config['api']['port']),
                 '--name',MODEL,'--max-tokens','32768','--temperature','1','--top-p','0.95','--top-k','20']
        for alias in aliases:
            args += ['--alias', alias]
    else:
        args += ['--entrypoint','/opt/tensorfold/bin/tf-dsv41-lanes', image,
                 '/model','/prepared','1','2',config['head']['rails'][0]['address'],str(config['master_port']),'/kit',
                 '--pool',str(p['pool_tokens']),'--context',str(p['context']),'--streams',str(p['parallel']),
                 '--round-rows',p['environment']['TF_DS_ROUND_ROWS'],'--drafts','1',
                 '--graphs',p['environment']['TF_DS_GRAPHS'],'--side',p['environment']['TF_DS_HC_SIDE'],
                 '--prefetch',p['environment']['TF_DS_L2_PREFETCH'],'--aio',p['environment']['TF_DS_ENGRAM_AIO'],
                 '--rdma',env['TF_RDMA_DEVICES'],'--engram','/engram','--token-map','/cache/token-map.json']
    return args
