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


def test_per_query_error_status_raises(monkeypatch):
    # HTTP 200 batch but the per-query status indicates a failure with no results;
    # must fail closed (ScreeningProviderError), NOT map empty results -> clear.
    _patch_post(
        monkeypatch,
        json_body={"responses": {"q1": {"status": 500, "error": "upstream", "results": []}}},
    )
    with pytest.raises(ScreeningProviderError):
        screen_entity(name="X", country="BRA", tax_id=None, lei=None)


def test_per_query_status_200_is_accepted(monkeypatch):
    _patch_post(
        monkeypatch,
        json_body={"responses": {"q1": {"status": 200, "results": [{"score": 0.10}]}}},
    )
    res = screen_entity(name="X", country="BRA", tax_id=None, lei=None)
    assert res.match_count == 1


@pytest.mark.parametrize(
    "results",
    [None, {"score": 0.9}, [{"score": 0.9}, "not-an-object"], [123]],
)
def test_malformed_results_payload_raises(monkeypatch, results):
    # results: null, a dict instead of a list, or a non-object item must fail closed
    # (ScreeningProviderError), never slip through to a default top_score=0 clear.
    _patch_post(monkeypatch, json_body={"responses": {"q1": {"results": results}}})
    with pytest.raises(ScreeningProviderError):
        screen_entity(name="X", country="BRA", tax_id=None, lei=None)
