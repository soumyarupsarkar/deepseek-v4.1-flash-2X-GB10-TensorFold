"""Exercise exact top-k prompt boundaries with ordinary/drafted token parity.

Only generated fixtures are sent to an idle, isolated candidate. In particular,
512 and 513 tokens require the N=KK=256 kernel added to the pinned native kit.
"""
import argparse
import hashlib
import json
from pathlib import Path
import subprocess
import sys

SOURCE = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(SOURCE / 'tools/qualification'))
import common
import qualify as q
from benchmark import tokens, wait_idle
from configuration import STATE, profile, read
from engine_health import ready
from native_endurance import rank_epochs, validate_continuity


def exact_prompt(length):
    marker = 'SYNTHETIC_BOUNDARY_SENTINEL'
    content = (f'Synthetic top-k boundary {length}:\n' + marker
               + '\n\nWrite a Python generator yielding even numbers.')
    rendered = tokens(common.API_BASE, messages=[dict(role='user', content=content)])
    middle = tokens(common.API_BASE, text=marker)
    cuts = [i for i in range(len(rendered)) if rendered[i:i + len(middle)] == middle]
    if len(cuts) != 1:
        raise ValueError('Fixture marker did not tokenize uniquely')
    prefix, suffix = rendered[:cuts[0]], rendered[cuts[0] + len(middle):]
    filler = tokens(common.API_BASE, text='birch maple cedar willow oak elm ')
    count = length - len(prefix) - len(suffix)
    if count < 1 or not filler:
        raise ValueError('Boundary is too short for the complete template')
    ids = prefix + (filler * ((count + len(filler) - 1) // len(filler)))[:count] + suffix
    assert len(ids) == length
    return ids


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--record', required=True)
    args = parser.parse_args()
    assert args.record.replace('-', '').isalnum()
    path = common.ROOT / 'records' / ('validation-' + args.record + '.json')
    assert not path.exists(), 'Preserve earlier evidence'
    pair = common.PAIR
    assert pair.config['api']['bind'] == '127.0.0.1', 'Require an isolated candidate'
    revision = subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=SOURCE, text=True).strip()
    assert not subprocess.check_output(['git', 'status', '--porcelain'], cwd=SOURCE, text=True).strip()
    launch, build = read(STATE / 'launch.json'), read(STATE / 'build.json')
    p = profile()
    assert build['revision'] == revision and build['id'] == launch['image']
    assert launch['profile'] == p
    before = pair.get('/health')
    assert ready(before, p) and not before['scheduler']['running'] and not before['scheduler']['waiting']
    epochs = rank_epochs(pair, launch)
    record = dict(started=common.now(), status='running', source=revision,
                  image=launch['image'], health_before=before, checks=[],
                  script_sha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest())
    common.atomic(path, record)
    try:
        for length in (511, 512, 513, 514):
            ids = exact_prompt(length)
            body = dict(prompt=ids, max_tokens=64, ignore_eos=True, temperature=0, return_token_ids=True)
            ordinary = q.post(dict(body, draft=False), '/v1/completions')['response']
            pre = pair.get('/health')['native']['draft_passes']
            drafted = q.post(dict(body, draft=True), '/v1/completions')['response']
            after, _ = wait_idle(common.API_BASE)
            passes = after['native']['draft_passes'] - pre
            assert ready(after, p), 'Runtime became unhealthy'
            assert ordinary['tensorfold']['token_ids'] == drafted['tensorfold']['token_ids']
            assert len(ordinary['tensorfold']['token_ids']) == 64 and passes > 0
            assert ordinary['tensorfold']['drafts'] is False and drafted['tensorfold']['drafts'] is True
            assert ordinary['usage']['prompt_tokens'] == length == drafted['usage']['prompt_tokens']
            record['checks'].append(dict(prompt_tokens=length, reply_tokens=64,
                prompt_sha256=hashlib.sha256(json.dumps(ids, separators=(',', ':')).encode()).hexdigest(),
                token_sha=ordinary['tensorfold']['token_sha'], draft_passes=passes))
            common.atomic(path, record)
            print(length, 'tokens: ordinary/drafted parity passed', flush=True)
        after, drain = wait_idle(common.API_BASE)
        assert ready(after, p) and after['completed']['requests'] - before['completed']['requests'] == 8
        validate_continuity(pair, launch, epochs, read(STATE / 'launch.json'), read(STATE / 'active.json'))
        record.update(status='passed', health_after=after, post_response_drain=drain)
    except BaseException as exc:
        record.update(status='failed', error=type(exc).__name__ + ': ' + str(exc))
        raise
    finally:
        record['finished'] = common.now()
        common.atomic(path, record)
    print('Exact top-k boundaries passed; receipt:', path)


if __name__ == '__main__':
    main()
