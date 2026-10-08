"""Offline publication checks, not a GPU/installation qualification or secret scanner."""
import ast
import hashlib
import json
from pathlib import Path
import re
import subprocess
import sys
from urllib.parse import unquote, urlsplit

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'deployment/scripts'))
import cli
import configuration as cfg
import runtime
import assets
import reuse


def git(*args):
    return subprocess.check_output(['git', *args], cwd=ROOT, text=True)


def main():
    failures = []
    manifest = cfg.read(ROOT / 'release/engine-source.json')
    pins = {row['path']: row['sha256'] for row in manifest['files']}
    if len(pins) != len(manifest['files']):
        failures.append('duplicate source pins')
    source_paths = set(git('ls-files', '-c', '-o', '--exclude-standard', '--',
                          'src', 'pyproject.toml', 'tools/dsv41/kit_bench.py').splitlines())
    if source_paths != set(pins):
        failures.append('engine source inventory changed')
    for name, digest in pins.items():
        path = ROOT / name
        if not path.is_file() or path.is_symlink() or hashlib.sha256(path.read_bytes()).hexdigest() != digest:
            failures.append('engine source differs: ' + name)
    if subprocess.run(['git', 'merge-base', '--is-ancestor', manifest['upstream_base'], 'HEAD'],
                      cwd=ROOT, capture_output=True).returncode:
        failures.append('public upstream ancestry missing')
    paths = set(git('ls-files', '-c', '-o', '--exclude-standard').splitlines())
    prohibited = ('deployment/.local/', 'deployment/records/', 'deployment/baseline/')
    for name in paths:
        if (name.startswith(prohibited) or name == 'deployment/local.json'
                or name.endswith(('.safetensors', '.pem', '.env', '.log'))
                or Path(name).name in ('.env', 'hf-token')):
            failures.append('installation/asset file included: ' + name)
    syntax_files = set()
    for directory in ('deployment/scripts', 'tests/publication', 'scripts'):
        syntax_files.update((ROOT / directory).glob('*.py'))
    for path in syntax_files | {ROOT / 'cluster'}:
        ast.parse(path.read_text(), filename=str(path.relative_to(ROOT)))
    for module, names in ((runtime, ('ROOTS', 'SNAPSHOT', 'FABRIC')), (assets, ('VERIFY',)),
                          (reuse, ('IMPORT', 'PREPARED'))):
        for name in names:
            ast.parse(getattr(module, name), filename=module.__name__ + '.' + name)
    cfg.validate(cfg.read(cfg.CONFIG / 'cluster.example.json'))
    profile = cfg.profile()
    if (profile['context'], profile['parallel'], profile['environment']['TF_DS_POOL_TOKENS']) != (1048576, 32, '8650752'):
        failures.append('qualified profile capacity changed')
    if 'allow_temporary_drm' not in cli.plan(cfg.read(cfg.CONFIG / 'cluster.example.json'))['config']:
        failures.append('example plan incomplete')
    specs = cfg.read(cfg.CONFIG / 'assets.json')
    for spec in specs.values():
        if not re.fullmatch('[0-9a-f]{40}', spec['revision']):
            failures.append('asset revision is not immutable')
        for row in spec['files']:
            assets.relative(row['path'])
            digest = row['sha256'] or row['git_blob_id']
            if not re.fullmatch('[0-9a-f]{64}' if row['sha256'] else '[0-9a-f]{40}', digest):
                failures.append('asset digest invalid')
    # Check links authored for this candidate; inherited upstream docs remain outside this scope.
    documents = [ROOT / n for n in ('README.md', 'CONTRIBUTING.md', 'SECURITY.md')]
    for directory in ('deployment', 'benchmarks', 'release'):
        documents.extend((ROOT / directory).glob('*.md'))
    link_count = 0
    for path in documents:
        for target in re.findall(r'\]\(([^\s)]+)\)', path.read_text()):
            link = urlsplit(target)
            if link.scheme or target.startswith('#'):
                continue
            link_count += 1
            if not (path.parent / unquote(link.path)).exists():
                failures.append('broken local link in ' + str(path.relative_to(ROOT)) + ': ' + target)
    if failures:
        raise SystemExit('\n'.join(failures))
    print(json.dumps(dict(status='passed', engine_files=len(pins),
                          python_files=len(syntax_files)+1, local_document_links=link_count,
                          scope='offline source/configuration/publication checks only'), sort_keys=True))


if __name__ == '__main__':
    main()
