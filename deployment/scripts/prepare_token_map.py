"""Offline CPU asset preparation; never imported by the native inference server.

The normalization follows Bertholomus TensorFold's compressed_token_map (MIT),
itself following DeepSeek's Engram reference. The pinned kit certifies the bytes.
"""
import hashlib
import json
from pathlib import Path
import sys


def prepare(model, kit, output):
    from tokenizers import Regex, Tokenizer, normalizers
    expected = json.loads((Path(kit)/'engram.json').read_text())
    output = Path(output)
    if output.is_symlink():
        raise ValueError('Token map destination is redirected')
    if output.exists():
        raw = output.read_bytes()
    else:
        tokenizer = Tokenizer.from_file(str(Path(model)/'tokenizer.json'))
        sentinel = '\ue000'
        norm = normalizers.Sequence([
            normalizers.NFKC(), normalizers.NFD(), normalizers.StripAccents(), normalizers.Lowercase(),
            normalizers.Replace(Regex(r'[ \t\r\n]+'), ' '), normalizers.Replace(Regex(r'^ $'), sentinel),
            normalizers.Strip(), normalizers.Replace(sentinel, ' ')])
        groups, lookup = {}, []
        for tid in range(tokenizer.get_vocab_size(with_added_tokens=True)):
            text = tokenizer.decode([tid], skip_special_tokens=False)
            key = tokenizer.id_to_token(tid) if '\ufffd' in text else (norm.normalize_str(text) or text)
            if key not in groups:
                groups[key] = len(groups)
            lookup.append(groups[key])
        raw = json.dumps(lookup).encode()
    if hashlib.sha256(raw).hexdigest() != expected['token_map_sha256']:
        raise ValueError('Compressed token map differs from the pinned native kit')
    if len(json.loads(raw)) != expected['token_map_len']:
        raise ValueError('Unexpected compressed vocabulary size')
    if not output.exists():
        with output.open('xb') as stream:
            stream.write(raw)
    print(json.dumps(dict(status='passed', entries=expected['token_map_len'], sha256=expected['token_map_sha256'])))


if __name__ == '__main__':
    prepare(*sys.argv[1:])
