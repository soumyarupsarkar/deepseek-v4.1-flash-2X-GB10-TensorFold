"""Exercise the pinned Pillow fallback and image translation on each API."""
import argparse
import base64
import hashlib
import json
from pathlib import Path
import sys
import urllib.error

SOURCE = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(SOURCE / 'tools/qualification'))
import common
from cluster import get
from configuration import profile, read, STATE
from engine_health import ready, busy
from qualify import post, text
from benchmark import wait_idle


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--record', required=True)
    args = parser.parse_args()
    if not args.record.replace('-', '').isalnum():
        raise ValueError('Use a simple unique record name')
    path = common.ROOT / 'records' / ('validation-' + args.record + '.json')
    if path.exists() or common.PAIR.config['api']['bind'] != '127.0.0.1':
        raise RuntimeError('Use a new receipt and isolated loopback installation')
    health = get('/health')
    if not ready(health, profile()) or busy(health):
        raise RuntimeError('Require an idle healthy candidate')
    fixture_path = Path(__file__).parent / 'fixtures/native-image-formats.json'
    fixtures = json.loads(fixture_path.read_text())['fixtures']
    record = dict(status='running', started=common.now(), launch=read(STATE / 'launch.json'),
                  fixtures_sha256=hashlib.sha256(fixture_path.read_bytes()).hexdigest(), checks=[])
    common.atomic(path, record)
    question = 'What color is the large square? Answer with just the color name.'
    parameters = dict(max_tokens=32, temperature=0, chat_template_kwargs={'enable_thinking': False})
    try:
        for fixture in fixtures:
            data = base64.b64decode(fixture['base64'], validate=True)
            if hashlib.sha256(data).hexdigest() != fixture['sha256']:
                raise RuntimeError('Synthetic fixture digest changed')
            mime = 'image/' + fixture['format']
            uri = 'data:' + mime + ';base64,' + fixture['base64']
            for route in ('chat/completions', 'responses', 'messages'):
                if route == 'chat/completions':
                    result = post(dict(parameters, messages=[dict(role='user', content=[
                        dict(type='text', text=question), dict(type='image_url', image_url=dict(url=uri))])]))
                    answer = text(result)
                elif route == 'responses':
                    result = post(dict(temperature=0, max_output_tokens=32,
                        chat_template_kwargs={'enable_thinking': False}, input=[dict(role='user', content=[
                            dict(type='input_text', text=question), dict(type='input_image', image_url=uri)])]), '/v1/responses')
                    answer = ''.join(part.get('text', '') for item in result['response']['output']
                                     for part in item.get('content', []))
                else:
                    result = post(dict(parameters, thinking=dict(type='disabled'), messages=[dict(role='user', content=[
                        dict(type='text', text=question), dict(type='image', source=dict(type='base64',
                            media_type=mime, data=fixture['base64']))])]), '/v1/messages')
                    answer = ''.join(part.get('text', '') for part in result['response']['content'])
                if fixture['color'] not in answer.lower():
                    raise AssertionError('Synthetic color differs on ' + route + ' with ' + mime)
                record['checks'].append(dict(format=fixture['format'], color=fixture['color'], route=route,
                                             seconds=result['seconds'], response=result['response']))
                common.atomic(path, record)
        invalid = 'data:image/jpeg;base64,' + base64.b64encode(b'not-an-image').decode()
        try:
            post(dict(parameters, messages=[dict(role='user', content=[
                dict(type='text', text=question), dict(type='image_url', image_url=dict(url=invalid))])]))
        except urllib.error.HTTPError as exc:
            if exc.code != 400:
                raise
            record['invalid_image_status'] = exc.code
        else:
            raise AssertionError('Malformed image was accepted')
        health, drain = wait_idle(common.API_BASE)
        if not ready(health, profile()) or busy(health):
            raise RuntimeError('Image checks did not leave a healthy idle pair')
        record.update(status='passed', health_after=health, post_response_drain=drain)
    except BaseException as exc:
        record.update(status='failed', error=type(exc).__name__ + ': ' + str(exc))
        raise
    finally:
        record['finished'] = common.now()
        common.atomic(path, record)
    print('JPEG/WebP on Chat, Responses and Messages passed; malformed image refused', flush=True)


if __name__ == '__main__':
    main()
