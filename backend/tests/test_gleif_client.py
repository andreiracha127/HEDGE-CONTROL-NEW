# backend/tests/test_gleif_client.py
import httpx
import pytest

from app.services import gleif_client as gc
from app.services.gleif_client import GleifLookupError, GleifRecord, fetch_lei_record

_RECORD = {
    "data": {
        "attributes": {
            "registration": {"status": "ISSUED"},
            "entity": {
                "legalName": {"name": "Bloomberg Finance L.P.", "language": "en"},
                "status": "ACTIVE",
            },
        }
    }
}


def _patch_get(monkeypatch, *, json_body=None, status_code=200, raise_exc=None):
    def fake_get(url, *, timeout):
        if raise_exc is not None:
            raise raise_exc
        return httpx.Response(status_code, json=json_body, request=httpx.Request("GET", url))

    monkeypatch.setattr(gc.httpx, "get", fake_get)
    monkeypatch.setattr(gc, "_base_url", lambda: "http://mock/api/v1")


def test_parses_record(monkeypatch):
    _patch_get(monkeypatch, json_body=_RECORD)
    rec = fetch_lei_record("5493001KJTIIGC8Y1R12")
    assert isinstance(rec, GleifRecord)
    assert rec.registration_status == "ISSUED"
    assert rec.legal_name == "Bloomberg Finance L.P."
    assert rec.legal_name_language == "en"
    assert rec.entity_status == "ACTIVE"


def test_404_returns_none(monkeypatch):
    _patch_get(monkeypatch, json_body={"errors": []}, status_code=404)
    assert fetch_lei_record("529900T8BM49AURSDO55") is None


def test_5xx_raises(monkeypatch):
    _patch_get(monkeypatch, json_body={}, status_code=500)
    with pytest.raises(GleifLookupError):
        fetch_lei_record("529900T8BM49AURSDO55")


def test_network_error_raises(monkeypatch):
    _patch_get(monkeypatch, raise_exc=httpx.ConnectError("boom"))
    with pytest.raises(GleifLookupError):
        fetch_lei_record("529900T8BM49AURSDO55")


def test_missing_fields_raises(monkeypatch):
    _patch_get(monkeypatch, json_body={"data": {"attributes": {"entity": {}}}})
    with pytest.raises(GleifLookupError):
        fetch_lei_record("529900T8BM49AURSDO55")
