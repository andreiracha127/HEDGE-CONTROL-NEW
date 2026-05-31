from decimal import Decimal

import httpx
import pytest

from app.services import opensanctions_client as oc
from app.services.opensanctions_client import MatchResult, ScreeningProviderError, screen_entity


def _patch_post(monkeypatch, *, json_body=None, status_code=200, raise_exc=None):
    captured = {}

    def fake_post(url, *, headers, json, timeout):
        captured["url"] = url
        captured["headers"] = headers
        captured["json"] = json
        if raise_exc is not None:
            raise raise_exc
        resp = httpx.Response(status_code, json=json_body, request=httpx.Request("POST", url))
        return resp

    monkeypatch.setattr(oc.httpx, "post", fake_post)
    monkeypatch.setattr(oc, "_api_key", lambda: "test-key")
    return captured


def test_builds_envelope_and_parses_top_score(monkeypatch):
    body = {
        "responses": {"q1": {"results": [{"score": 0.93}, {"score": 0.40}], "total": {"value": 2}}}
    }
    cap = _patch_post(monkeypatch, json_body=body)
    res = screen_entity(name="Rusal", country="RUS", tax_id="123", lei=None)
    assert isinstance(res, MatchResult)
    assert res.top_score == Decimal("0.93")
    assert res.match_count == 2
    assert res.algorithm == "logic-v2"
    props = cap["json"]["queries"]["q1"]["properties"]
    assert props["name"] == ["Rusal"]
    assert props["jurisdiction"] == ["RUS"]
    assert props["registrationNumber"] == ["123"]
    assert "leiCode" not in props
    assert cap["headers"]["Authorization"] == "ApiKey test-key"


def test_no_match_is_zero_score(monkeypatch):
    _patch_post(monkeypatch, json_body={"responses": {"q1": {"results": []}}})
    res = screen_entity(name="Clean Co", country="BRA", tax_id=None, lei=None)
    assert res.top_score == Decimal("0")
    assert res.match_count == 0


def test_non_2xx_raises(monkeypatch):
    _patch_post(monkeypatch, json_body={"detail": "bad"}, status_code=422)
    with pytest.raises(ScreeningProviderError):
        screen_entity(name="X", country="BRA", tax_id=None, lei=None)


def test_network_error_raises(monkeypatch):
    _patch_post(monkeypatch, raise_exc=httpx.ConnectError("boom"))
    with pytest.raises(ScreeningProviderError):
        screen_entity(name="X", country="BRA", tax_id=None, lei=None)


def test_empty_key_raises(monkeypatch):
    monkeypatch.setattr(oc, "_api_key", lambda: "")
    with pytest.raises(ScreeningProviderError):
        screen_entity(name="X", country="BRA", tax_id=None, lei=None)


def test_malformed_envelope_missing_responses_raises(monkeypatch):
    _patch_post(monkeypatch, json_body={"status": "ok"})  # no "responses" key
    with pytest.raises(ScreeningProviderError):
        screen_entity(name="X", country="BRA", tax_id=None, lei=None)


def test_non_numeric_score_raises(monkeypatch):
    _patch_post(monkeypatch, json_body={"responses": {"q1": {"results": [{"score": "high"}]}}})
    with pytest.raises(ScreeningProviderError):
        screen_entity(name="X", country="BRA", tax_id=None, lei=None)


def test_dataset_version_parsed(monkeypatch):
    body = {"responses": {"q1": {"results": [{"score": 0.10}], "dataset_version": "20260101"}}}
    _patch_post(monkeypatch, json_body=body)
    res = screen_entity(name="X", country="BRA", tax_id=None, lei=None)
    assert res.dataset_version == "20260101"
