"""Synthetic constrained ordinary/drafted parity across formats and forced cuts."""
import argparse
import hashlib
import json
from pathlib import Path
import re
import sys
import urllib.error

SOURCE = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(SOURCE / 'tools/qualification'))
import common
from configuration import profile, read, STATE
from engine_health import ready
from benchmark import wait_idle
from native_endurance import rank_epochs, validate_continuity
from qualify import post, stream_post, text


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--record', required=True)
    a = p.parse_args()
    assert re.fullmatch('[a-z0-9-]+', a.record)
    assert common.PAIR.config['api']['bind'] == '127.0.0.1'
    out = common.ROOT / 'records' / ('validation-' + a.record + '.json')
    assert not out.exists()
    pair = common.PAIR
    launch = read(STATE / 'launch.json')
    epochs = rank_epochs(pair, launch)
    initial, _ = wait_idle(common.API_BASE)
    assert ready(initial, profile()) and initial['structured_drafts']
    record = dict(status='running', started=common.now(), checks=[], health_before=initial,
                  launch=launch, script_sha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest())
    schema = dict(type='object', properties=dict(
        result=dict(anyOf=[dict(type='null'), dict(type='object',
            properties=dict(code=dict(type='string', pattern='^[A-Z]{2}[0-9]{3}$'),
                            count=dict(type='integer', minimum=2, maximum=7)),
            required=['code', 'count'], additionalProperties=False)])),
        required=['result'], additionalProperties=False)
    strict = dict(type='json_schema', json_schema=dict(name='record', strict=True, schema=schema))
    cases = [
        ('object', 'Return a JSON object with status ready.', dict(response_format=dict(type='json_object'))),
        ('nested-schema', 'Return result with code AB123 and count 5.', dict(response_format=strict)),
        ('regex', 'Return a short reference code.', dict(guided_regex='[A-Z]{2}[0-9]{3}')),
        ('choice', 'Choose a status word.', dict(guided_choice=['READY', 'WAITING', 'COMPLETE'])),
        ('grammar', 'Return an acknowledgement.', dict(guided_grammar='root ::= "ACK" ("NOW" | "LATER")')),
        ('length-cut', 'Return result with code AB123 and count 5.', dict(response_format=strict, max_tokens=1)),
        ('stop-cut', 'Return the exact word FOOBAR.', dict(guided_choice=['FOOBAR'], stop=['BAR'])),
    ]
    for budget in (1, 2, 5, 16):
        cases.append(('thinking-' + str(budget), 'Return result with code AB123 and count 5.',
                      dict(response_format=strict, chat_template_kwargs={'enable_thinking': True}, thinking_budget=budget)))
    try:
        # These must fail before SSE or a decode round, in either draft mode.
        refusals = 0
        for route, payload in (
            ('/v1/chat/completions', dict(messages=[dict(role='user', content='Return JSON.')])),
            ('/v1/completions', dict(prompt='Return JSON.')),
        ):
            for stream in (False, True):
                for draft in (False, True):
                    try:
                        post(dict(payload, max_tokens=16, stream=stream, draft=draft, ignore_eos=True,
                                  response_format=dict(type='json_object')),
                             route=route)
                    except urllib.error.HTTPError as exc:
                        assert exc.code == 400 and 'ignore_eos' in exc.response_body
                        refusals += 1
                    else:
                        raise AssertionError('A terminated grammar cannot ignore EOS')
        record['ignore_eos_refusals'] = refusals
        for temperature in (0, 1):
            for name, prompt, options in cases:
                body = dict(messages=[dict(role='user', content=prompt)], max_tokens=192,
                            temperature=temperature, seed=301026, return_token_ids=True,
                            chat_template_kwargs={'enable_thinking': False})
                body.update(options)
                ordinary = post(dict(body, draft=False))['response']
                drafted = post(dict(body, draft=True))['response']
                assert ordinary['tensorfold']['drafts'] is False and drafted['tensorfold']['drafts'] is True
                assert ordinary['tensorfold']['token_sha'] == drafted['tensorfold']['token_sha'], (name, temperature)
                value = text(dict(response=drafted))
                if name in ('nested-schema', 'object') or name.startswith('thinking-'):
                    parsed = json.loads(value)
                    assert isinstance(parsed, dict)
                    if name != 'object':
                        assert set(parsed) == {'result'}
                        if parsed['result'] is not None:
                            item = parsed['result']
                            assert set(item) == {'code', 'count'} and re.fullmatch('[A-Z]{2}[0-9]{3}', item['code'])
                            assert type(item['count']) is int and 2 <= item['count'] <= 7
                elif name == 'regex':
                    assert re.fullmatch('[A-Z]{2}[0-9]{3}', value)
                elif name == 'choice':
                    assert value in options['guided_choice']
                elif name == 'grammar':
                    assert value in ('ACKNOW', 'ACKLATER')
                if name in ('nested-schema', 'thinking-5'):
                    streamed = stream_post(dict(body, draft=True))
                    assert streamed['tensorfold']['token_sha'] == drafted['tensorfold']['token_sha']
                record['checks'].append(dict(name=name, temperature=temperature,
                    token_sha=drafted['tensorfold']['token_sha'], usage=drafted['usage'],
                    finish_reason=drafted['choices'][0]['finish_reason'], parity=True))
                common.atomic(out, record)
                print(name, 'temperature', temperature, 'passed', flush=True)
        final, _ = wait_idle(common.API_BASE)
        assert ready(final, profile())
        validate_continuity(pair, launch, epochs, read(STATE / 'launch.json'), read(STATE / 'active.json'))
        record.update(status='passed', health_after=final)
    except BaseException as exc:
        record.update(status='failed', error=type(exc).__name__ + ': ' + str(exc))
        raise
    finally:
        record['finished'] = common.now()
        common.atomic(out, record)


if __name__ == '__main__':
    main()
