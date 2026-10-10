"""Compile and test native CPU contracts; no GPU, weights, SSH or host changes."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import platform
import subprocess
import tarfile
import urllib.request


def run(*args, cwd=None, env=None):
    subprocess.run([str(arg) for arg in args], cwd=cwd, env=env, check=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source', type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument('--work', type=Path, required=True, help='New, disposable build directory')
    parser.add_argument('--zig-archive', type=Path, help='Optional already-downloaded archive; checksum is still verified')
    parser.add_argument('--xgrammar', type=Path, help='Optional clean checkout at the pinned revision')
    args = parser.parse_args()
    source, work = args.source.resolve(), args.work.resolve()
    if platform.system() != 'Linux' or platform.machine() not in ('aarch64', 'arm64'):
        raise RuntimeError('This pinned compiler and CI job require ARM64 Linux')
    work.mkdir(parents=True, exist_ok=False)
    pins = json.loads((source / 'deployment/config/native-inputs.json').read_text())
    archive = args.zig_archive
    if archive is None:
        archive = work / 'zig.tar.xz'
        with urllib.request.urlopen(pins['zig']['url'], timeout=180) as response, archive.open('xb') as out:
            while block := response.read(2**20):
                out.write(block)
    with archive.open('rb') as stream:
        if hashlib.file_digest(stream, 'sha256').hexdigest() != pins['zig']['sha256']:
            raise ValueError('Compiler checksum differs from native-inputs.json')
    with tarfile.open(archive) as tf:
        tf.extractall(work, filter='data')
    zig = work / ('zig-aarch64-linux-' + pins['zig']['version']) / 'zig'
    grammar = args.xgrammar
    if grammar is None:
        grammar = work / 'xgrammar'
        run('git', 'init', grammar)
        run('git', 'remote', 'add', 'origin', pins['xgrammar']['repository'], cwd=grammar)
        run('git', 'fetch', '--depth', '1', 'origin', pins['xgrammar']['revision'], cwd=grammar)
        run('git', 'checkout', '--detach', 'FETCH_HEAD', cwd=grammar)
        run('git', 'submodule', 'update', '--init', '--recursive', '--depth', '1', cwd=grammar)
    grammar = grammar.resolve()
    revision = subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=grammar, text=True).strip()
    if revision != pins['xgrammar']['revision']:
        raise ValueError('xgrammar revision differs from native-inputs.json')
    if subprocess.check_output(['git', 'status', '--porcelain'], cwd=grammar, text=True).strip():
        raise ValueError('xgrammar checkout is not clean')
    submodules = subprocess.check_output(['git', 'submodule', 'status', '--recursive'], cwd=grammar, text=True)
    if not submodules.strip() or any(line[0] != ' ' for line in submodules.splitlines()):
        raise ValueError('xgrammar submodules do not match their gitlinks')
    run('cmake', '-S', source / 'zig/native_xgrammar', '-B', work / 'grammar',
        '-DXGRAMMAR_SOURCE_DIR=' + str(grammar), '-DCMAKE_BUILD_TYPE=Release')
    run('cmake', '--build', work / 'grammar', '--parallel', '2')
    run('ctest', '--test-dir', work / 'grammar', '--output-on-failure')
    run(zig, 'build', 'test', 'test-server', '-Dtarget=aarch64-linux-gnu',
        '-Doptimize=safe', '-j2', '--cache-dir', work / 'cache',
        '--prefix', work / 'out', '--summary', 'all', cwd=source,
        env=os.environ | {'ZIG_GLOBAL_CACHE_DIR': str(work / 'global'), 'ZIG_LOCAL_CACHE_DIR': str(work / 'cache')})
    print('Native CPU/server and C++ grammar contracts passed. GPU inference is not exercised.')


if __name__ == '__main__':
    main()
