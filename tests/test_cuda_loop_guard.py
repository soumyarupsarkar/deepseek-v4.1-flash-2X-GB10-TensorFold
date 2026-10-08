"""Real HTTP routing for the opt-in guard with a deterministic synthetic engine."""
from concurrent.futures import ThreadPoolExecutor
from types import SimpleNamespace

import pytest

from tensorfold.cuda import server
from tensorfold.engine import exact_sampling
from tests.test_cuda_thinking_controls import ChainEngine, app_for, ask
from tests.test_cuda_tool_choice import END


@pytest.mark.parametrize('stream', [False, True])
@pytest.mark.parametrize('width', [1, 6, 2048])
@pytest.mark.parametrize('seed', [None, 0, 73])
def test_looping_thinking_closes_and_continues_without_changing_request_seed(tmp_path, monkeypatch, stream, width, seed):
    monkeypatch.setattr(exact_sampling, 'SEED_MODE', 'random')
    draws = []
    monkeypatch.setattr(exact_sampling.secrets, 'randbits', lambda bits: draws.append(bits) or 123)
    engine = ChainEngine(width)
    seeds = []
    original = engine.generate

    def generate(prompt, max_tokens, sampling, on_tokens, draft=True):
        seeds.append(sampling.seed)
        return original(prompt, max_tokens, sampling, on_tokens, draft)

    engine.generate = generate
    app = app_for(tmp_path, engine)
    app.sampling.update(top_k=20, top_p=0.95)
    status, body = ask(app, stream, loop_guard=True, max_tokens=4200, temperature=0.7, seed=seed)
    assert status == 200
    assert body['tensorfold']['loop_guard'] is True
    expected_seed = 123 if seed is None else seed
    assert body['tensorfold']['sampling_seed'] == str(expected_seed)
    tokens = body['tensorfold']['token_ids']
    assert tokens.index(END) == 4097 and len(tokens) == 4200
    content = body['content'] if stream else body['choices'][0]['message']['content']
    assert content
    assert seeds == [expected_seed, expected_seed]
    assert draws == ([63] if seed is None else [])
    assert engine.prompts[1] == engine.prompts[0] + tokens[:4100]


@pytest.mark.parametrize('default,override,enabled', [
    (False, None, False), (False, False, False), (False, True, True),
    (True, None, True), (True, False, False), (True, True, True),
])
def test_server_default_and_request_override(tmp_path, monkeypatch, default, override, enabled):
    monkeypatch.setattr(server, 'LOOP_GUARD', default)
    app = app_for(tmp_path, ChainEngine(6))
    fields = {} if override is None else {'loop_guard': override}
    status, body = ask(app, max_tokens=4104, **fields)
    assert status == 200
    assert body['tensorfold'].get('loop_guard', False) is enabled
    assert (END in body['tensorfold']['token_ids']) is enabled


@pytest.mark.parametrize('thinking,grammar,budget', [
    (False, None, 0), (True, object(), 0), (True, None, 128),
])
def test_grammar_thinking_budget_and_nonreasoning_requests_keep_their_own_policy(thinking, grammar, budget):
    app = server.App.__new__(server.App)
    app.tok = object()  # eligibility must be checked before looking up a token
    prepared = SimpleNamespace(grammar=grammar, think_budget=budget)
    assert app._think_loop({'loop_guard': True}, prepared, thinking) is None


def test_naturally_finished_thinking_is_identical_with_guard_enabled(tmp_path):
    replies = []
    for enabled in (False, True):
        app = app_for(tmp_path, ChainEngine(6, end_at=50))
        status, body = ask(app, loop_guard=enabled, max_tokens=128)
        assert status == 200 and 'loop_guard' not in body['tensorfold']
        replies.append(body['tensorfold']['token_ids'])
    assert replies[0] == replies[1]


def test_concurrent_requests_have_independent_guards(tmp_path):
    engine = ChainEngine(6)
    engine.concurrent = True
    app = app_for(tmp_path, engine)
    with ThreadPoolExecutor(2) as pool:
        replies = list(pool.map(lambda enabled: ask(app, loop_guard=enabled, max_tokens=4104), [True, False]))
    assert all(status == 200 for status, _ in replies)
    assert replies[0][1]['tensorfold']['loop_guard'] is True
    assert 'loop_guard' not in replies[1][1]['tensorfold']
