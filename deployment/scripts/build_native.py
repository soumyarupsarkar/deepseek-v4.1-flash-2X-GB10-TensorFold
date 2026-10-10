"""Container-only native build from reviewed, immutable input pins."""
import hashlib
from pathlib import Path
import subprocess
import tarfile
import urllib.request
import json


def run(*args, cwd=None):
    subprocess.run(args, cwd=cwd, check=True)


def main():
    source, build = Path('/src'), Path('/build')
    build.mkdir(exist_ok=True)
    pins = json.loads((source/'deployment/config/native-inputs.json').read_text())
    archive = build/'zig.tar.xz'
    with urllib.request.urlopen(pins['zig']['url'], timeout=180) as response, archive.open('wb') as out:
        while block := response.read(2**20):
            out.write(block)
    with archive.open('rb') as stream:
        if hashlib.file_digest(stream, 'sha256').hexdigest() != pins['zig']['sha256']:
            raise ValueError('Zig compiler checksum differs')
    with tarfile.open(archive) as tf:
        tf.extractall(build, filter='data')
    zig = build/('zig-aarch64-linux-'+pins['zig']['version'])/'zig'
    run('git','init',str(build/'xgrammar'))
    run('git','remote','add','origin',pins['xgrammar']['repository'],cwd=build/'xgrammar')
    run('git','fetch','--depth','1','origin',pins['xgrammar']['revision'],cwd=build/'xgrammar')
    run('git','checkout','--detach','FETCH_HEAD',cwd=build/'xgrammar')
    rev=subprocess.check_output(['git','rev-parse','HEAD'],cwd=build/'xgrammar',text=True).strip()
    if rev != pins['xgrammar']['revision']:
        raise ValueError('xgrammar revision differs')
    run('git','submodule','update','--init','--recursive','--depth','1',cwd=build/'xgrammar')
    run('cmake','-S',str(source/'zig/native_xgrammar'),'-B',str(build/'grammar'),
        '-DXGRAMMAR_SOURCE_DIR='+str(build/'xgrammar'),'-DCMAKE_BUILD_TYPE=Release',
        '-DCMAKE_INSTALL_PREFIX='+str(build/'grammar/out'))
    run('cmake','--build',str(build/'grammar'),'--parallel','4')
    run('ctest','--test-dir',str(build/'grammar'),'--output-on-failure')
    run('cmake','--install',str(build/'grammar'),'--component','native')
    run(str(zig),'build','native','install','test','test-server','-Dtarget=aarch64-linux-gnu',
        '-Doptimize=safe','-Dnvcc=/usr/local/cuda/bin/nvcc','-Dsm=121','-j2',
        '--cache-dir',str(build/'cache'),'--prefix',str(build/'out'),'--summary','all',cwd=source)
    run('cp',str(build/'out/native/bin/tensorfold-native'),str(build/'out/bin/tensorfold-native'))


if __name__ == '__main__':
    main()
