"""Seed policy at the request boundary: fresh requests, stable continuations and explicit replay."""

import json
from types import SimpleNamespace

import pytest

from tensorfold.engine import exact_sampling as sampling
from tensorfold.server.request_options import RequestOptions
from tests.test_cuda_admission import http_server
from tests.test_cuda_server_errors import HI, app_for, events, request


@pytest.mark.parametrize("value,expected", [(None, "prompt"), ("prompt", "prompt"),
                                            ("random", "random"), (" RANDOM ", "random")])
def test_startup_seed_mode(monkeypatch, value, expected):
    if value is None:
        monkeypatch.delenv("TENSORFOLD_SEED_MODE", raising=False)
    else:
        monkeypatch.setenv("TENSORFOLD_SEED_MODE", value)
    assert sampling._seed_mode_from_env() == expected


@pytest.mark.parametrize("value", ["", "rand", "0"])
def test_invalid_startup_seed_mode_is_refused(monkeypatch, value):
    monkeypatch.setenv("TENSORFOLD_SEED_MODE", value)
    with pytest.raises(ValueError, match="TENSORFOLD_SEED_MODE must be prompt or random"):
        sampling._seed_mode_from_env()


def entropy(monkeypatch, values):
    draws, values = [], iter(values)

    def draw(bits):
        draws.append(bits)
        return next(values)

    monkeypatch.setattr(sampling.secrets, "randbits", draw)
    return draws


@pytest.mark.parametrize("chat", [True, False])
@pytest.mark.parametrize("fields", [{}, {"seed": None}])
def test_random_http_requests_get_one_seed_each_including_streaming(tmp_path, monkeypatch, chat, fields):
    monkeypatch.setattr(sampling, "SEED_MODE", "random")
    seeds = [2**63 - 1, 2**62 + 7]
    draws = entropy(monkeypatch, seeds)
    app = app_for(tmp_path)
    body = {**({"messages": HI} if chat else {"prompt": "Hi"}), **fields}
    with http_server(app) as port:
        for seed, stream in zip(seeds, (False, True)):
            status, _, result = request(port, {**body, "stream": stream,
                                              "stream_options": {"include_usage": True}}, chat=chat)
            assert status == 200
            parts = [p for p in events(result) if isinstance(p, dict)] if stream else [json.loads(result)]
            metadata = [p["tensorfold"] for p in parts if "tensorfold" in p]
            assert metadata[-1]["sampling_seed"] == str(seed)
    assert [call["sampling"].seed for call in app.engine.calls] == seeds
    assert draws == [63, 63]  # admission, run and streaming all reuse the prepared seed


@pytest.mark.parametrize("mode", ["prompt", "random"])
@pytest.mark.parametrize("seed", [0, 27, -7, 2**63 - 1])
def test_explicit_seed_wins_without_drawing_entropy(tmp_path, monkeypatch, mode, seed):
    monkeypatch.setattr(sampling, "SEED_MODE", mode)
    draws = entropy(monkeypatch, [])
    app = app_for(tmp_path)
    body = {"messages": HI, "seed": seed}
    a, b = (app.prepare(body, True).sampling for _ in range(2))
    assert a == b == sampling.Sampling(seed, 1.0, 20, 0.95)
    assert draws == []


def test_prompt_mode_preserves_salt_and_existing_default(tmp_path, monkeypatch):
    monkeypatch.setattr(sampling, "SEED_MODE", "prompt")
    monkeypatch.setattr(sampling, "SEED_SALT", 19)
    draws = entropy(monkeypatch, [])
    app = app_for(tmp_path)
    a, b = (app.prepare({"messages": HI}, True) for _ in range(2))
    assert a.sampling == b.sampling
    assert a.sampling.seed == sampling.seed_for(a.prompt, salt=19)
    assert draws == []


def test_random_prepared_request_keeps_seed_through_run(tmp_path, monkeypatch):
    monkeypatch.setattr(sampling, "SEED_MODE", "random")
    draws = entropy(monkeypatch, [31])
    app = app_for(tmp_path)
    body = {"messages": HI}
    prepared = app.prepare(body, True)
    assert app.check(body, prepared=prepared) is None
    result = app.run(body, True, lambda delta: True, prepared=prepared)
    assert app.engine.calls[0]["sampling"] is prepared.sampling
    assert result["stats"]["sampling_seed"] == "31"
    assert draws == [63]


@pytest.mark.parametrize("mode", ["prompt", "random"])
def test_greedy_does_not_draw_or_use_a_seed(tmp_path, monkeypatch, mode):
    monkeypatch.setattr(sampling, "SEED_MODE", mode)
    draws = entropy(monkeypatch, [])
    app = app_for(tmp_path)
    body = {"messages": HI, "temperature": 0}
    result = app.run(body, True, lambda delta: True)
    assert app.engine.calls[0]["sampling"] is None
    assert result["stats"]["sampling_seed"] is None
    assert draws == []


def test_shared_server_resolver_obeys_policy_and_preserves_model_seed(monkeypatch):
    monkeypatch.setattr(sampling, "SEED_MODE", "random")
    draws = entropy(monkeypatch, [13, 17])
    app = SimpleNamespace(default_sampling={"temperature": 1.0})
    resolve = lambda fields: RequestOptions._resolve_sampling(app, fields, 1.0, [1, 2, 3])
    assert [resolve({}).seed, resolve({"seed": None}).seed] == [13, 17]
    assert resolve({"seed": 0}).seed == 0
    app.default_sampling["seed"] = 23
    assert resolve({}).seed == resolve({"seed": None}).seed == 23
    assert resolve({"temperature": 0}) is None
    assert draws == [63, 63]
