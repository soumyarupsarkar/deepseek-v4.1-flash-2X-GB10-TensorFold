"""CPU-only allocator control using the pinned native grammar bridge.

Run in a disposable container with a read-only model mount. This never connects
to an inference server. It generates constant-object schemas, then repeats them
while recording cache size, glibc accounting and anonymous memory plus swap.
"""
import argparse
import ctypes as c
import hashlib
import json
import os
from pathlib import Path
import time


class Mallinfo(c.Structure):
    _fields_ = [(key, c.c_size_t) for key in ('arena', 'ordblks', 'smblks', 'hblks',
        'hblkhd', 'usmblks', 'fsmblks', 'uordblks', 'fordblks', 'keepcost')]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--library', type=Path, default=Path('/opt/tensorfold/lib/libtf_xgrammar.so'))
    parser.add_argument('--model', type=Path, default=Path('/model'))
    parser.add_argument('--repeats', type=int, default=12)
    parser.add_argument('--trim-at-end', action='store_true',
                        help='Diagnostic trim of this disposable process only, after all repeated work')
    args = parser.parse_args()
    if not 1 <= args.repeats <= 64:
        parser.error('--repeats must be between 1 and 64')
    lib, libc = c.CDLL(str(args.library)), c.CDLL(None)
    libc.mallinfo2.restype = Mallinfo
    libc.malloc_trim.argtypes = [c.c_size_t]
    libc.malloc_trim.restype = c.c_int
    lib.tf_xg_compiler_create.argtypes = [c.c_char_p, c.c_size_t, c.POINTER(c.c_uint32),
        c.c_size_t, c.c_int, c.c_int64, c.c_char_p, c.c_size_t]
    lib.tf_xg_compiler_create.restype = c.c_void_p
    lib.tf_xg_matcher_create.argtypes = [c.c_void_p, c.c_uint32, c.c_char_p, c.c_size_t,
                                       c.c_char_p, c.c_size_t]
    lib.tf_xg_matcher_create.restype = c.c_void_p
    lib.tf_xg_matcher_destroy.argtypes = [c.c_void_p]
    lib.tf_xg_matcher_destroy.restype = None
    lib.tf_xg_compiler_destroy.argtypes = [c.c_void_p]
    lib.tf_xg_compiler_destroy.restype = None
    lib.tf_xg_cache_bytes.argtypes = [c.c_void_p]
    lib.tf_xg_cache_bytes.restype = c.c_uint64
    raw = (args.model/'tokenizer.json').read_bytes()
    eos = json.loads((args.model/'config.json').read_text())['eos_token_id']
    eos = eos if isinstance(eos, list) else [eos]
    stops, error = (c.c_uint32 * len(eos))(*eos), c.create_string_buffer(1024)
    compiler, started = None, time.monotonic()
    print(json.dumps(dict(kind='inputs', tokenizer_sha256=hashlib.sha256(raw).hexdigest(),
        library_sha256=hashlib.sha256(args.library.read_bytes()).hexdigest(),
        repeats=args.repeats, schemas=128, compiler_threads=4, cache_bytes_per_vocabulary=256*2**20,
        allocator_environment={k: os.environ.get(k) for k in
            ('MALLOC_ARENA_MAX', 'MALLOC_TRIM_THRESHOLD_', 'MALLOC_MMAP_THRESHOLD_')})), flush=True)

    def sample(label):
        heap = libc.mallinfo2()
        memory = {}
        for line in Path('/proc/self/status').read_text().splitlines():
            if line.startswith(('RssAnon:', 'VmSwap:', 'VmRSS:')):
                key, value = line.split(':')
                memory[key] = int(value.split()[0])*1024
        print(json.dumps(dict(kind='sample', label=label, elapsed_s=time.monotonic()-started,
            heap={key: getattr(heap, key) for key, _ in heap._fields_}, memory=memory,
            cache_bytes=lib.tf_xg_cache_bytes(compiler) if compiler else 0)), flush=True)

    def compile_schema(value):
        schema = dict(type='object', properties={'status': {'const': 'ok'}, 'value': {'const': value}},
                      required=['status', 'value'], additionalProperties=False)
        data = json.dumps(schema).encode()
        matcher = lib.tf_xg_matcher_create(compiler, 1, data, len(data), error, len(error))
        if not matcher:
            raise RuntimeError(error.value.decode(errors='replace'))
        lib.tf_xg_matcher_destroy(matcher)

    sample('before-compiler')
    compiler = lib.tf_xg_compiler_create(raw, len(raw), stops, len(eos), 4, 256*2**20, error, len(error))
    if not compiler:
        raise RuntimeError(error.value.decode(errors='replace'))
    try:
        sample('compiler')
        compile_schema(0)
        for _ in range(128):
            compile_schema(0)
        sample('hot-128')
        for batch in range(4):
            for value in range(batch*32, (batch+1)*32):
                compile_schema(value)
            sample('distinct-'+str((batch+1)*32))
        for epoch in range(args.repeats):
            for value in range(128):
                compile_schema(value)
            sample('repeat-'+str((epoch+1)*128))
        if args.trim_at_end:
            libc.malloc_trim(0)
            sample('after-trim')
    finally:
        lib.tf_xg_compiler_destroy(compiler)
        compiler = None
    if args.trim_at_end:
        libc.malloc_trim(0)
    sample('destroyed')


if __name__ == '__main__':
    main()
