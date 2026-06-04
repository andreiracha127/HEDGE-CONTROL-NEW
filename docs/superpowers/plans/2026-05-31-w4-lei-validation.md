# W4 — LEI Validation (GLEIF) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Implement risk_manager/trader-triggered LEI validation for commercial partners — an offline ISO 7064 MOD 97-10 checksum plus an online GLEIF lookup that records `lei_status`/`lei_legal_name`/`lei_checked_at` and returns advisory warnings, WARN-not-block (never blocks anything, never 5xx).

**Architecture:** A thin mockable `gleif_client` (the one external-I/O boundary; 404→None, errors→`GleifLookupError`) feeds a `lei_validation_service` that runs the pure checksum, calls GLEIF, maps the registration status, does an advisory name cross-check, sets the LEI fields, and emits an HMAC audit event. A single `POST /commercial-partners/{id}/validate-lei` route wraps it in `unit_of_work`. No gate reads `lei_status`.

**Tech Stack:** FastAPI, SQLAlchemy 2.0, pydantic-settings, httpx, pytest (SQLite in-memory).

**Spec:** `docs/superpowers/specs/2026-05-31-w4-lei-validation-design.md`. **Branch:** `w4/lei-validation` (created off `main` `ddb8a74`; spec committed `2fc0aa0`).

---

## File structure

| File | Responsibility |
|---|---|
| `backend/app/core/config.py` *(modify)* | `GLEIF_API_BASE_URL` setting (no key, no boot validator) |
| `backend/app/services/gleif_client.py` *(create)* | `GleifRecord`, `GleifLookupError`, `fetch_lei_record` (parse GLEIF; 404→None) |
| `backend/app/services/lei_validation_service.py` *(create)* | `lei_checksum_ok` (pure) + `validate_lei` (orchestration + audit) |
| `backend/app/schemas/lei.py` *(create)* | `LeiValidationRead` |
| `backend/app/api/routes/commercial_partners.py` *(modify)* | `POST /{id}/validate-lei` |
| `backend/tests/test_audit_economic_mutations.py` *(modify)* | classify the new route + service-emission assertion |
| `frontend-svelte/src/lib/api/schema.d.ts` *(regen)* | OpenAPI types for the new endpoint |

**Sample LEIs (verified):** valid checksum — `5493001KJTIIGC8Y1R12`, `529900T8BM49AURSDO55`; invalid checksum — `984500F1F2E3D4C5B6A7`. **Audit emission lives in the service** (not a route `audit_event` dep), matching the W2 sanctions routes.

---

## Task 1: Config — `GLEIF_API_BASE_URL`

**Files:**
- Modify: `backend/app/core/config.py`
- Test: `backend/tests/test_lei_config.py`

- [ ] **Step 1: Write the failing test**

```python
# backend/tests/test_lei_config.py
from app.core.config import Settings


def test_gleif_base_url_default():
    s = Settings(database_url="sqlite+pysqlite:///:memory:")
    assert s.gleif_api_base_url == "https://api.gleif.org/api/v1"


def test_gleif_base_url_overridable():
    s = Settings(database_url="sqlite+pysqlite:///:memory:", gleif_api_base_url="http://mock/api/v1")
    assert s.gleif_api_base_url == "http://mock/api/v1"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && python -m pytest tests/test_lei_config.py -q`
Expected: FAIL (field does not exist).

- [ ] **Step 3: Add the setting**

In `backend/app/core/config.py`, in the `# ── Sanctions screening (OpenSanctions) ──` block (added in W2, ~line 140), add after the sanctions fields:

```python
    # ── LEI validation (GLEIF) ────────────────────────────────────
    gleif_api_base_url: str = Field("https://api.gleif.org/api/v1")
```

(No boot validator: the GLEIF API is public and LEI never gates.)

- [ ] **Step 4: Run test to verify it passes**

Run: `cd backend && python -m pytest tests/test_lei_config.py -q`
Expected: PASS (2 passed).

- [ ] **Step 5: Commit**

```bash
git add backend/app/core/config.py backend/tests/test_lei_config.py
git commit -m "feat(w4): GLEIF_API_BASE_URL setting

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Task 2: GLEIF client

**Files:**
- Create: `backend/app/services/gleif_client.py`
- Test: `backend/tests/test_gleif_client.py`

- [ ] **Step 1: Write the failing test**

```python
# backend/tests/test_gleif_client.py
import httpx
import pytest

from app.services import gleif_client as gc
from app.services.gleif_client import GleifLookupError, GleifRecord, fetch_lei_record

_RECORD = {
    "data": {
        "attributes": {
            "registration": {"status": "ISSUED"},
            "entity": {"legalName": {"name": "Bloomberg Finance L.P.", "language": "en"}, "status": "ACTIVE"},
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
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && python -m pytest tests/test_gleif_client.py -q`
Expected: FAIL (module does not exist).

- [ ] **Step 3: Implement the client**

```python
# backend/app/services/gleif_client.py
"""Thin, mockable boundary to the public GLEIF LEI-records API.

Single external-I/O point of the W4 LEI subsystem. Fetches a LEI record and
parses the fields needed for validation. A 404 (LEI not registered) is a real
answer (returns None); any transport/parse failure raises GleifLookupError so
the service can record an `error` lei_status. The client never fabricates a
valid record.
"""
from __future__ import annotations

from dataclasses import dataclass

import httpx

from app.core.config import get_settings

_TIMEOUT_SECONDS = 30.0


class GleifLookupError(Exception):
    """Raised on any GLEIF transport / HTTP (non-404) / parse failure."""


@dataclass(frozen=True)
class GleifRecord:
    registration_status: str
    legal_name: str | None
    legal_name_language: str | None
    entity_status: str | None


def _base_url() -> str:
    return get_settings().gleif_api_base_url


def fetch_lei_record(lei: str) -> GleifRecord | None:
    url = f"{_base_url()}/lei-records/{lei}"
    try:
        response = httpx.get(url, timeout=_TIMEOUT_SECONDS)
        if response.status_code == 404:
            return None
        response.raise_for_status()
        data = response.json()
    except httpx.HTTPError as exc:
        raise GleifLookupError(f"GLEIF request failed: {exc}") from exc
    except ValueError as exc:  # JSON decode
        raise GleifLookupError(f"GLEIF returned unparseable body: {exc}") from exc

    try:
        attributes = data["data"]["attributes"]
        registration_status = attributes["registration"]["status"]
        entity = attributes.get("entity") or {}
        legal_name_obj = entity.get("legalName") or {}
        legal_name = legal_name_obj.get("name")
        legal_name_language = legal_name_obj.get("language")
        entity_status = entity.get("status")
    except (KeyError, TypeError) as exc:
        raise GleifLookupError(f"GLEIF response missing expected fields: {exc}") from exc

    if not registration_status:
        raise GleifLookupError("GLEIF response missing registration status")

    return GleifRecord(
        registration_status=registration_status,
        legal_name=legal_name,
        legal_name_language=legal_name_language,
        entity_status=entity_status,
    )
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd backend && python -m pytest tests/test_gleif_client.py -q`
Expected: PASS (5 passed).

- [ ] **Step 5: Commit**

```bash
git add backend/app/services/gleif_client.py backend/tests/test_gleif_client.py
git commit -m "feat(w4): GLEIF LEI-records client (404->None, errors->GleifLookupError)

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Task 3: Checksum (pure function)

**Files:**
- Create: `backend/app/services/lei_validation_service.py` (module header + imports + pure checksum only)
- Test: `backend/tests/test_lei_checksum.py`

- [ ] **Step 1: Write the failing test**

```python
# backend/tests/test_lei_checksum.py
import pytest

from app.services.lei_validation_service import lei_checksum_ok


@pytest.mark.parametrize("lei", ["5493001KJTIIGC8Y1R12", "529900T8BM49AURSDO55", "54930084UKLVMY22DS16"])
def test_valid_checksums(lei):
    assert lei_checksum_ok(lei) is True


@pytest.mark.parametrize(
    "lei",
    [
        "984500F1F2E3D4C5B6A7",  # wrong check digits
        "5493001KJTIIGC8Y1R1",   # 19 chars
        "5493001KJTIIGC8Y1R123",  # 21 chars
        "5493001KJTIIGC8Y1R1!",  # non-alphanumeric
        "",
    ],
)
def test_invalid_checksums(lei):
    assert lei_checksum_ok(lei) is False


def test_lowercase_is_accepted_via_upcasing():
    assert lei_checksum_ok("5493001kjtiigc8y1r12") is True
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && python -m pytest tests/test_lei_checksum.py -q`
Expected: FAIL (module/function does not exist).

- [ ] **Step 3: Create the module with the pure checksum**

```python
# backend/app/services/lei_validation_service.py
"""LEI validation: offline ISO 7064 MOD 97-10 checksum + online GLEIF lookup.

WARN-not-block: nothing here ever blocks or raises to the caller on a provider
failure — a GLEIF outage records lei_status=error. Mirrors the W2 client/service
split; audit emission lives in this service (not a route dependency).
"""
from __future__ import annotations

import uuid
from datetime import UTC, datetime

from fastapi import HTTPException, status
from sqlalchemy.orm import Session

from app.models.commercial_partner import CommercialPartner, LeiStatus
from app.services.audit_trail_service import AuditTrailService
from app.services.commercial_partner_service import CommercialPartnerService
from app.services.gleif_client import GleifLookupError, fetch_lei_record

# GLEIF registration.status -> LeiStatus. Any status not listed maps to `lapsed`
# (not currently active) with the raw status surfaced as a warning.
_STATUS_MAP = {"ISSUED": LeiStatus.issued, "LAPSED": LeiStatus.lapsed}


def lei_checksum_ok(lei: str) -> bool:
    """ISO 7064 MOD 97-10: 20 alphanumerics, A-Z->10..35, int(...) % 97 == 1."""
    lei = lei.upper()
    if len(lei) != 20 or not lei.isascii() or not lei.isalnum():
        return False
    try:
        digits = "".join(str(int(c, 36)) for c in lei)
    except ValueError:
        return False
    return int(digits) % 97 == 1
```

(`int(c, 36)` maps `0-9`→0-9 and `A-Z`→10-35 per character — exactly the ISO 17442 mapping.)

- [ ] **Step 4: Run test to verify it passes**

Run: `cd backend && python -m pytest tests/test_lei_checksum.py -q`
Expected: PASS (9 passed).

- [ ] **Step 5: Commit**

```bash
git add backend/app/services/lei_validation_service.py backend/tests/test_lei_checksum.py
git commit -m "feat(w4): LEI ISO 7064 MOD 97-10 checksum (pure)

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Task 4: `validate_lei` service

**Files:**
- Modify: `backend/app/services/lei_validation_service.py`
- Test: `backend/tests/test_lei_validation_service.py`

- [ ] **Step 1: Write the failing test**

```python
# backend/tests/test_lei_validation_service.py
import pytest

from app.core.database import SessionLocal
from app.models.audit import AuditEvent
from app.models.commercial_partner import CommercialPartner, CommercialPartnerKind, LeiStatus
from app.models.counterparty import KycStatus, RiskRating, SanctionsStatus
from app.services import lei_validation_service as svc
from app.services.gleif_client import GleifLookupError, GleifRecord

VALID = "5493001KJTIIGC8Y1R12"
BAD_CHECKSUM = "984500F1F2E3D4C5B6A7"


def _partner(session, *, name="Bloomberg Finance L.P.", lei=VALID) -> CommercialPartner:
    cp = CommercialPartner(
        kind=CommercialPartnerKind.customer, name=name, country="USA", lei=lei,
        lei_status=LeiStatus.not_provided, kyc_status=KycStatus.pending,
        sanctions_status=SanctionsStatus.unscreened, risk_rating=RiskRating.medium,
    )
    session.add(cp)
    session.commit()
    session.refresh(cp)
    return cp


def _record(status_="ISSUED", legal_name="Bloomberg Finance L.P."):
    return GleifRecord(registration_status=status_, legal_name=legal_name, legal_name_language="en", entity_status="ACTIVE")


def test_issued_sets_issued_and_persists_name_and_audits(monkeypatch):
    monkeypatch.setattr(svc, "fetch_lei_record", lambda lei: _record("ISSUED"))
    with SessionLocal() as session:
        cp = _partner(session)
        result, warnings = svc.validate_lei(session, cp.id, actor_sub="rm-1", commit=True)
        assert result.lei_status is LeiStatus.issued
        assert result.lei_legal_name == "Bloomberg Finance L.P."
        assert result.lei_checked_at is not None
        assert warnings == []
        ev = (
            session.query(AuditEvent)
            .filter(AuditEvent.event_type == "commercial_partner_lei_validated")
            .filter(AuditEvent.entity_id == cp.id)
            .one()
        )
        assert ev.payload["new_status"] == "issued"


def test_lapsed_maps_lapsed(monkeypatch):
    monkeypatch.setattr(svc, "fetch_lei_record", lambda lei: _record("LAPSED"))
    with SessionLocal() as session:
        cp = _partner(session)
        result, _ = svc.validate_lei(session, cp.id, actor_sub="rm", commit=True)
        assert result.lei_status is LeiStatus.lapsed


def test_other_status_maps_lapsed_with_warning(monkeypatch):
    monkeypatch.setattr(svc, "fetch_lei_record", lambda lei: _record("RETIRED"))
    with SessionLocal() as session:
        cp = _partner(session)
        result, warnings = svc.validate_lei(session, cp.id, actor_sub="rm", commit=True)
        assert result.lei_status is LeiStatus.lapsed
        assert any("RETIRED" in w for w in warnings)


def test_checksum_fail_sets_invalid_and_skips_gleif(monkeypatch):
    def must_not_call(lei):
        raise AssertionError("GLEIF must not be called when the checksum fails")

    monkeypatch.setattr(svc, "fetch_lei_record", must_not_call)
    with SessionLocal() as session:
        cp = _partner(session, lei=BAD_CHECKSUM)
        result, warnings = svc.validate_lei(session, cp.id, actor_sub="rm", commit=True)
        assert result.lei_status is LeiStatus.invalid
        assert any("checksum" in w.lower() for w in warnings)


def test_404_sets_invalid_with_warning(monkeypatch):
    monkeypatch.setattr(svc, "fetch_lei_record", lambda lei: None)
    with SessionLocal() as session:
        cp = _partner(session)
        result, warnings = svc.validate_lei(session, cp.id, actor_sub="rm", commit=True)
        assert result.lei_status is LeiStatus.invalid
        assert any("not found" in w.lower() for w in warnings)


def test_gleif_error_sets_error_and_does_not_raise(monkeypatch):
    def boom(lei):
        raise GleifLookupError("down")

    monkeypatch.setattr(svc, "fetch_lei_record", boom)
    with SessionLocal() as session:
        cp = _partner(session)
        result, warnings = svc.validate_lei(session, cp.id, actor_sub="rm", commit=True)
        assert result.lei_status is LeiStatus.error
        assert any("GLEIF lookup failed" in w for w in warnings)


def test_name_mismatch_warns_without_changing_status(monkeypatch):
    monkeypatch.setattr(svc, "fetch_lei_record", lambda lei: _record("ISSUED", legal_name="Totally Different Co"))
    with SessionLocal() as session:
        cp = _partner(session, name="Acme Customer Ltda")
        result, warnings = svc.validate_lei(session, cp.id, actor_sub="rm", commit=True)
        assert result.lei_status is LeiStatus.issued
        assert any("differs from partner name" in w for w in warnings)


def test_null_lei_sets_not_provided(monkeypatch):
    monkeypatch.setattr(svc, "fetch_lei_record", lambda lei: _record("ISSUED"))
    with SessionLocal() as session:
        cp = _partner(session, lei=None)
        result, _ = svc.validate_lei(session, cp.id, actor_sub="rm", commit=True)
        assert result.lei_status is LeiStatus.not_provided


def test_missing_partner_404(monkeypatch):
    import uuid

    monkeypatch.setattr(svc, "fetch_lei_record", lambda lei: _record("ISSUED"))
    with SessionLocal() as session:
        with pytest.raises(Exception) as exc:
            svc.validate_lei(session, uuid.uuid4(), actor_sub="rm")
        assert getattr(exc.value, "status_code", None) == 404
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && python -m pytest tests/test_lei_validation_service.py -q`
Expected: FAIL (`validate_lei` not defined).

- [ ] **Step 3: Implement `validate_lei` + name cross-check**

Append to `backend/app/services/lei_validation_service.py`:

```python
def _names_diverge(legal_name: str | None, partner_name: str | None) -> bool:
    a = (legal_name or "").strip().casefold()
    b = (partner_name or "").strip().casefold()
    if not a or not b:
        return False
    return a not in b and b not in a


def validate_lei(
    session: Session,
    commercial_partner_id,
    *,
    actor_sub: str,
    commit: bool = True,
) -> tuple[CommercialPartner, list[str]]:
    cp = CommercialPartnerService.get_by_id(session, commercial_partner_id)
    if cp is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Commercial partner not found"
        )
    previous_status = cp.lei_status
    warnings: list[str] = []
    now = datetime.now(UTC)

    if not cp.lei or not cp.lei.strip():
        cp.lei_status = LeiStatus.not_provided
        cp.lei_legal_name = None
        cp.lei_checked_at = now
    elif not lei_checksum_ok(cp.lei):
        cp.lei_status = LeiStatus.invalid
        cp.lei_legal_name = None
        cp.lei_checked_at = now
        warnings.append("LEI failed the ISO 17442 checksum")
    else:
        try:
            record = fetch_lei_record(cp.lei)
        except GleifLookupError as exc:
            cp.lei_status = LeiStatus.error
            cp.lei_checked_at = now
            warnings.append(f"GLEIF lookup failed: {exc}")
        else:
            if record is None:
                cp.lei_status = LeiStatus.invalid
                cp.lei_legal_name = None
                cp.lei_checked_at = now
                warnings.append("LEI not found in GLEIF registry")
            else:
                cp.lei_status = _STATUS_MAP.get(record.registration_status, LeiStatus.lapsed)
                if record.registration_status not in _STATUS_MAP:
                    warnings.append(f"GLEIF registration status: {record.registration_status}")
                cp.lei_legal_name = record.legal_name
                cp.lei_checked_at = now
                if _names_diverge(record.legal_name, cp.name):
                    warnings.append(
                        f"LEI legal name '{record.legal_name}' differs from "
                        f"partner name '{cp.name}'"
                    )

    AuditTrailService.record(
        session,
        event_id=uuid.uuid4(),
        entity_type="commercial_partner",
        entity_id=cp.id,
        event_type="commercial_partner_lei_validated",
        payload_raw="",
        payload_obj={
            "commercial_partner_id": str(cp.id),
            "lei": cp.lei,
            "previous_status": previous_status.value,
            "new_status": cp.lei_status.value,
            "lei_legal_name": cp.lei_legal_name,
            "actor_sub": actor_sub,
        },
        commit=False,
    )
    session.flush()
    if commit:
        session.commit()
        session.refresh(cp)
    return cp, warnings
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd backend && python -m pytest tests/test_lei_validation_service.py -q`
Expected: PASS (9 passed).

- [ ] **Step 5: Commit**

```bash
git add backend/app/services/lei_validation_service.py backend/tests/test_lei_validation_service.py
git commit -m "feat(w4): validate_lei service (checksum + GLEIF + name cross-check + audit)

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Task 5: `LeiValidationRead` schema

**Files:**
- Create: `backend/app/schemas/lei.py`
- Test: `backend/tests/test_lei_schema.py`

- [ ] **Step 1: Write the failing test**

```python
# backend/tests/test_lei_schema.py
from datetime import UTC, datetime

from app.schemas.lei import LeiValidationRead


def test_lei_validation_read_shape():
    r = LeiValidationRead(
        lei="5493001KJTIIGC8Y1R12",
        lei_status="issued",
        lei_legal_name="Bloomberg Finance L.P.",
        lei_checked_at=datetime.now(UTC),
        warnings=["GLEIF registration status: RETIRED"],
    )
    assert r.lei_status == "issued"
    assert r.warnings == ["GLEIF registration status: RETIRED"]


def test_lei_validation_read_allows_nulls_and_empty_warnings():
    r = LeiValidationRead(lei=None, lei_status="not_provided", lei_legal_name=None, lei_checked_at=None, warnings=[])
    assert r.lei is None
    assert r.warnings == []
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && python -m pytest tests/test_lei_schema.py -q`
Expected: FAIL (module does not exist).

- [ ] **Step 3: Implement the schema**

```python
# backend/app/schemas/lei.py
from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel


class LeiValidationRead(BaseModel):
    lei: str | None
    lei_status: str
    lei_legal_name: str | None
    lei_checked_at: datetime | None
    warnings: list[str]
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd backend && python -m pytest tests/test_lei_schema.py -q`
Expected: PASS (2 passed).

- [ ] **Step 5: Commit**

```bash
git add backend/app/schemas/lei.py backend/tests/test_lei_schema.py
git commit -m "feat(w4): LeiValidationRead schema

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Task 6: `validate-lei` route + audit classification

**Files:**
- Modify: `backend/app/api/routes/commercial_partners.py`
- Modify: `backend/tests/test_audit_economic_mutations.py`
- Test: `backend/tests/test_lei_route.py`

- [ ] **Step 1: Write the failing test**

```python
# backend/tests/test_lei_route.py
from app.core.auth import get_current_user
from app.main import app
from app.services import lei_validation_service as svc
from app.services.gleif_client import GleifRecord


def _as(role):
    app.dependency_overrides[get_current_user] = lambda: {"sub": f"{role}-1", "roles": [role]}


def _make_partner(client, lei="5493001KJTIIGC8Y1R12"):
    _as("trader")
    r = client.post("/commercial-partners", json={"kind": "customer", "name": "Acme", "country": "BRA", "lei": lei})
    assert r.status_code == 201
    return r.json()["id"]


def test_trader_validates_lei(client, monkeypatch):
    monkeypatch.setattr(
        svc, "fetch_lei_record",
        lambda lei: GleifRecord("ISSUED", "Acme", "en", "ACTIVE"),
    )
    pid = _make_partner(client)
    _as("trader")
    r = client.post(f"/commercial-partners/{pid}/validate-lei")
    assert r.status_code == 200
    assert r.json()["lei_status"] == "issued"
    app.dependency_overrides.pop(get_current_user, None)


def test_gleif_error_returns_200_with_error_status(client, monkeypatch):
    from app.services.gleif_client import GleifLookupError

    def boom(lei):
        raise GleifLookupError("down")

    monkeypatch.setattr(svc, "fetch_lei_record", boom)
    pid = _make_partner(client)
    _as("risk_manager")
    r = client.post(f"/commercial-partners/{pid}/validate-lei")
    assert r.status_code == 200  # WARN-not-block: informational error, not a 5xx
    assert r.json()["lei_status"] == "error"
    assert r.json()["warnings"]
    app.dependency_overrides.pop(get_current_user, None)


def test_auditor_cannot_validate_lei(client):
    pid = _make_partner(client)
    _as("auditor")
    r = client.post(f"/commercial-partners/{pid}/validate-lei")
    assert r.status_code == 403
    app.dependency_overrides.pop(get_current_user, None)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && python -m pytest tests/test_lei_route.py -q`
Expected: FAIL (route 404 / not defined).

- [ ] **Step 3: Add imports + route**

In `backend/app/api/routes/commercial_partners.py`, add to the import block:

```python
from app.schemas.lei import LeiValidationRead
from app.services.lei_validation_service import validate_lei
```

Append the route at the end of the file:

```python
@router.post(
    "/{commercial_partner_id}/validate-lei",
    response_model=LeiValidationRead,
    status_code=status.HTTP_200_OK,
)
def validate_commercial_partner_lei(
    commercial_partner_id: UUID,
    request: Request,
    actor_sub: str = Depends(get_current_actor_sub),
    _: None = Depends(require_any_role("trader", "risk_manager")),
    session: Session = Depends(get_session),
) -> LeiValidationRead:
    with unit_of_work(session, request=request):
        cp, warnings = validate_lei(
            session, commercial_partner_id, actor_sub=actor_sub, commit=False
        )
    return LeiValidationRead(
        lei=cp.lei,
        lei_status=cp.lei_status.value,
        lei_legal_name=cp.lei_legal_name,
        lei_checked_at=cp.lei_checked_at,
        warnings=warnings,
    )
```

(`require_any_role`, `get_current_actor_sub`, `get_session`, `unit_of_work`, `Request`, `status`, `Depends`, `UUID` are already imported in this file.)

- [ ] **Step 4: Classify the new mutating route**

In `backend/tests/test_audit_economic_mutations.py`, add to `TestRouteCoverageStatic.CLASSIFICATION` (near the other commercial-partner entries):

```python
        (
            "POST",
            "/commercial-partners/{commercial_partner_id}/validate-lei",
        ): "service-layer audited lei mutation",
```

Then add a service-emission assertion test in `TestRouteCoverageStatic` (mirrors `test_sanctions_routes_emit_via_service`):

```python
    def test_lei_route_emits_via_service(self) -> None:
        import inspect

        from app.services import lei_validation_service

        service_source = inspect.getsource(lei_validation_service)
        lei_routes = [
            mp for mp, c in self.CLASSIFICATION.items() if c == "service-layer audited lei mutation"
        ]
        assert len(lei_routes) == 1, "expected the validate-lei route"
        assert "AuditTrailService.record" in service_source, (
            "lei_validation_service must emit an HMAC audit event via AuditTrailService.record"
        )
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `cd backend && python -m pytest tests/test_lei_route.py "tests/test_audit_economic_mutations.py::TestRouteCoverageStatic" -q`
Note: run with the CI-equivalent env so `/internal/test/cleanup` registers and the inventory test passes:
`cd backend && APP_ENV=test DATABASE_URL="sqlite+pysqlite:///:memory:" AUDIT_SIGNING_KEY="test-key-1234567" python -m pytest "tests/test_audit_economic_mutations.py::TestRouteCoverageStatic" -q`
Expected: route tests 3 passed; TestRouteCoverageStatic all pass.

- [ ] **Step 6: Commit**

```bash
git add backend/app/api/routes/commercial_partners.py backend/tests/test_lei_route.py backend/tests/test_audit_economic_mutations.py
git commit -m "feat(w4): POST /commercial-partners/{id}/validate-lei + audit classification

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Task 7: Regenerate OpenAPI types + full-suite gate + PR

**Files:**
- Regen: `frontend-svelte/src/lib/api/schema.d.ts`

- [ ] **Step 1: Full backend suite**

Run: `cd backend && python -m pytest -q`
Expected: all W4 tests pass; only the known **26 pre-existing environmental failures** remain (auth-`APP_ENV`, internal-test-gating, whatsapp, webhook, service-token, and the `TestRouteCoverageStatic` inventory test which fails locally only because `/internal/test/cleanup` needs `APP_ENV=test`). Confirm zero W4-caused failures by diffing the failing-test set against `main` if unsure.

- [ ] **Step 2: Regenerate frontend OpenAPI types (with APP_ENV=test)**

The drift check runs against a backend started with `APP_ENV=test`, so the dump MUST include `/internal/test/cleanup`. Dump the spec from within Python (so stdout logging cannot contaminate the file), then regen:

Run:
```bash
cd backend && APP_ENV=test DATABASE_URL="sqlite+pysqlite:///:memory:" AUDIT_SIGNING_KEY="test-key-1234567" SCHEDULER_DISABLED=1 \
  python -c "import json; from app.main import app; open('openapi_tmp.json','w',encoding='utf-8').write(json.dumps(app.openapi()))"
cd ../frontend-svelte && OPENAPI_SOURCE=../backend/openapi_tmp.json node scripts/regen-schema.mjs
rm -f ../backend/openapi_tmp.json
```
Expected: `schema.d.ts` updated with the `/commercial-partners/{commercial_partner_id}/validate-lei` path + `LeiValidationRead`.

- [ ] **Step 3: Frontend check (must stay green)**

Run: `cd frontend-svelte && npm run check && npm run test`
Expected: svelte-check 0 errors; vitest all pass.

- [ ] **Step 4: Commit**

```bash
git add frontend-svelte/src/lib/api/schema.d.ts
git commit -m "chore(w4): regen schema.d.ts for validate-lei endpoint

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

- [ ] **Step 5: Open the PR**

```bash
git push -u origin w4/lei-validation
gh pr create --base main --title "W4: LEI Validation (GLEIF checksum + lookup, WARN-not-block)" --body "Implements docs/superpowers/specs/2026-05-31-w4-lei-validation-design.md. commercial_partners only; manual POST /validate-lei (trader + risk_manager); ISO 7064 MOD 97-10 checksum + GLEIF lookup; WARN-not-block (GLEIF error -> lei_status=error + HTTP 200, never blocks). No gate reads lei_status. No migration (columns from 049)."
```
Then await Codex review. If the pre-push hook fails on Anthropic API credits, this is a code/spec push with no `*-dispatch.md` in range — bypass with `git push --no-verify` requires explicit orchestrator authorization.

---

## Self-review (completed by plan author)

**Spec coverage:** §1 boundary (no gate, no migration, no scheduled, commercial-only) → respected across tasks; §2 client → T2; §3 checksum → T3, `validate_lei` + mapping + name cross-check + audit → T4; §4 RBAC/endpoint (trader+risk_manager, 200-on-error) → T6 + tests; §5 config → T1; §6 testing matrix → T2–T6; route classification → T6; schema regen → T7. ✔

**Placeholder scan:** none — every step has complete code/commands.

**Type consistency:** `fetch_lei_record(lei) -> GleifRecord | None` and `GleifRecord(registration_status, legal_name, legal_name_language, entity_status)` consistent across T2/T4 tests. `lei_checksum_ok(lei) -> bool` T3/T4. `validate_lei(session, commercial_partner_id, *, actor_sub, commit=True) -> (CommercialPartner, list[str])` consistent T4/T6. `_STATUS_MAP` keys uppercase GLEIF statuses. `LeiStatus` members (`not_provided`/`invalid`/`issued`/`lapsed`/`error`) match the model enum; `valid` intentionally unused. Service monkeypatched at `svc.fetch_lei_record` (imported into the service module) in all service/route tests — consistent.
