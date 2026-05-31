# W2 — Sanctions Screening Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Implement the OpenSanctions screening writer + risk_manager adjudication + manual `/screen` endpoints + scheduled daily re-screen + boot validator + service identity, setting `sanctions_status` from recorded evidence for both hedge counterparties and commercial partners.

**Architecture:** A thin mockable `opensanctions_client` (the one external-I/O boundary) feeds a domain-agnostic `sanctions_screening_service` that maps `top_score`→`result`, persists immutable `sanctions_screenings` rows, sets `sanctions_status`, and emits HMAC audit events — using the `kyc_gate` dual-session pattern to record provider-error evidence that survives `unit_of_work` rollback. A scheduler task re-screens both domains daily. No gate logic changes (W3 owns the RFQ re-target).

**Tech Stack:** FastAPI, SQLAlchemy 2.0, pydantic-settings, httpx, APScheduler, pytest (SQLite in-memory). Decimal end-to-end.

**Spec:** `docs/superpowers/specs/2026-05-30-w2-sanctions-screening-design.md`. **Branch:** `w2/sanctions-screening` (already created off `main` `898a0bc`).

---

## File structure

| File | Responsibility |
|---|---|
| `backend/app/core/config.py` *(modify)* | `OPENSANCTIONS_API_KEY`, `SANCTIONS_SCREENING_ENABLED`, `SANCTIONS_REVIEW_THRESHOLD`, `SANCTIONS_HARD_THRESHOLD` settings + APP_ENV-gated boot validator |
| `backend/app/core/auth.py` *(modify)* | add `service:sanctions_screening` to `_INTERNAL_SERVICE_IDENTITIES` |
| `backend/app/services/opensanctions_client.py` *(create)* | build `EntityMatchQuery`, POST, parse → `MatchResult`; raise `ScreeningProviderError` |
| `backend/app/services/sanctions_screening_service.py` *(create)* | `map_score_to_result`, `screen()`, `adjudicate()`, `effective_sanctions_status()` |
| `backend/app/schemas/sanctions.py` *(create)* | `SanctionsScreeningRead`, `SanctionsAdjudicationRequest`, `SanctionsAdjudicationRead` |
| `backend/app/api/routes/commercial_partners.py` *(modify)* | `POST /{id}/screen`, `POST /{id}/adjudicate-sanctions` |
| `backend/app/api/routes/counterparties.py` *(modify)* | `POST /{id}/screen`, `POST /{id}/adjudicate-sanctions` |
| `backend/app/tasks/sanctions_rescreen_task.py` *(create)* | `run_sanctions_rescreen_daily()` |
| `backend/app/tasks/scheduler.py` *(modify)* | register `sanctions_rescreen_daily` cron job |
| `frontend-svelte/src/lib/api/schema.d.ts` *(regen)* | OpenAPI types for the new endpoints (`openapi_diff` CI gate) |
| `backend/tests/test_sanctions_*` *(create)* | client, service, routes, task, config, RBAC |

**Audit emission decision:** the status-change HMAC event is emitted **inside the service** (`AuditTrailService.record`), not via the route `audit_event` dependency — because the scheduled task calls `screen()` with no request context, so the service is the single uniform emission point.

**Enum mapping:** `ScreeningResult` and `SanctionsStatus` share string values (`clear`/`flagged`/`blocked`), so `SanctionsStatus(result.value)` is the conversion. `SanctionsStatus` is the shared enum in `app.models.counterparty`, used by both `Counterparty` and `CommercialPartner`.

---

## Task 1: Config settings + boot validator

**Files:**
- Modify: `backend/app/core/config.py`
- Test: `backend/tests/test_sanctions_config_boot_validator.py`

- [ ] **Step 1: Write the failing test**

```python
# backend/tests/test_sanctions_config_boot_validator.py
import pytest

from app.core.config import Settings

PG = "postgresql://u:p@h/db"


def test_prod_enabled_missing_key_refuses_boot():
    with pytest.raises(ValueError, match="OPENSANCTIONS_API_KEY"):
        Settings(
            database_url=PG,
            app_env="production",
            audit_signing_key="x" * 16,
            sanctions_screening_enabled=True,
            opensanctions_api_key="",
        )


def test_prod_enabled_with_key_boots():
    s = Settings(
        database_url=PG,
        app_env="production",
        audit_signing_key="x" * 16,
        sanctions_screening_enabled=True,
        opensanctions_api_key="key-123",
    )
    assert s.opensanctions_api_key == "key-123"


def test_prod_disabled_missing_key_boots():
    s = Settings(
        database_url=PG,
        app_env="production",
        audit_signing_key="x" * 16,
        sanctions_screening_enabled=False,
        opensanctions_api_key="",
    )
    assert s.sanctions_screening_enabled is False


def test_dev_missing_key_boots():
    s = Settings(
        database_url=PG,
        app_env="development",
        sanctions_screening_enabled=True,
        opensanctions_api_key="",
    )
    assert s.app_env == "development"


def test_default_thresholds():
    from decimal import Decimal

    s = Settings(database_url="sqlite+pysqlite:///:memory:")
    assert s.sanctions_review_threshold == Decimal("0.70")
    assert s.sanctions_hard_threshold == Decimal("0.90")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && python -m pytest tests/test_sanctions_config_boot_validator.py -q`
Expected: FAIL (fields don't exist / no validator).

- [ ] **Step 3: Add settings fields**

In `backend/app/core/config.py`, after the WhatsApp/Twilio blocks (before the `# ── Helpers ──` section, ~line 138), add:

```python
    # ── Sanctions screening (OpenSanctions) ──────────────────────
    opensanctions_api_key: str = Field("")
    sanctions_screening_enabled: bool = Field(True)
    sanctions_review_threshold: Decimal = Field(
        Decimal("0.70"), description="top_score >= this -> flagged (below -> clear)"
    )
    sanctions_hard_threshold: Decimal = Field(
        Decimal("0.90"), description="top_score >= this -> blocked"
    )
```

- [ ] **Step 4: Extend the boot validator**

In `model_post_init`, append after the `audit_signing_key` check (after the existing `raise ValueError("AUDIT_SIGNING_KEY ...")` block, ~line 99):

```python
        if self.sanctions_screening_enabled and (
            not self.opensanctions_api_key or not self.opensanctions_api_key.strip()
        ):
            raise ValueError(
                "OPENSANCTIONS_API_KEY must be set to a non-empty value when "
                "SANCTIONS_SCREENING_ENABLED is true. Sanctions screening is "
                "fail-closed; refusing to boot without a provider key."
            )
```

(The existing early `return`s for sqlite-in-memory and `development/dev/local/test` env markers already exempt dev/test from this check.)

- [ ] **Step 5: Run test to verify it passes**

Run: `cd backend && python -m pytest tests/test_sanctions_config_boot_validator.py -q`
Expected: PASS (5 passed).

- [ ] **Step 6: Commit**

```bash
git add backend/app/core/config.py backend/tests/test_sanctions_config_boot_validator.py
git commit -m "feat(w2): OpenSanctions settings + APP_ENV-gated boot validator

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Task 2: Register `service:sanctions_screening` identity

**Files:**
- Modify: `backend/app/core/auth.py:301-306`
- Test: `backend/tests/test_sanctions_service_identity.py`

- [ ] **Step 1: Write the failing test**

```python
# backend/tests/test_sanctions_service_identity.py
from app.core.auth import _INTERNAL_SERVICE_IDENTITIES


def test_sanctions_screening_identity_registered():
    assert "service:sanctions_screening" in _INTERNAL_SERVICE_IDENTITIES
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && python -m pytest tests/test_sanctions_service_identity.py -q`
Expected: FAIL (identity not in the frozenset).

- [ ] **Step 3: Add the identity**

In `backend/app/core/auth.py`, add `"service:sanctions_screening",` to the `_INTERNAL_SERVICE_IDENTITIES` frozenset (after `"service:cashflow_pipeline",`):

```python
_INTERNAL_SERVICE_IDENTITIES = frozenset(
    {
        "service:westmetall_ingest",
        "service:rfq_outbound",
        "service:cashflow_pipeline",
        "service:sanctions_screening",
    }
)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd backend && python -m pytest tests/test_sanctions_service_identity.py -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/app/core/auth.py backend/tests/test_sanctions_service_identity.py
git commit -m "feat(w2): register service:sanctions_screening internal identity

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Task 3: OpenSanctions client

**Files:**
- Create: `backend/app/services/opensanctions_client.py`
- Test: `backend/tests/test_opensanctions_client.py`

- [ ] **Step 1: Write the failing test**

```python
# backend/tests/test_opensanctions_client.py
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
    body = {"responses": {"q1": {"results": [{"score": 0.93}, {"score": 0.40}], "total": {"value": 2}}}}
    cap = _patch_post(monkeypatch, json_body=body)
    res = screen_entity(name="Rusal", country="RUS", tax_id="123", lei=None)
    assert isinstance(res, MatchResult)
    assert res.top_score == Decimal("0.93")
    assert res.match_count == 2
    assert res.algorithm == "logic-v2"
    # envelope: array-valued, leiCode omitted (None), header carries ApiKey
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
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && python -m pytest tests/test_opensanctions_client.py -q`
Expected: FAIL (module does not exist).

- [ ] **Step 3: Implement the client**

```python
# backend/app/services/opensanctions_client.py
"""Thin, mockable boundary to the hosted OpenSanctions match API.

This is the single external-I/O point of the W2 sanctions subsystem. It builds
the OpenSanctions ``EntityMatchQuery`` envelope, POSTs it, and parses the
response into a normalized ``MatchResult``. It NEVER returns a default ``clear``:
any network / HTTP / parse failure raises ``ScreeningProviderError`` so the
service can record fail-closed error evidence.
"""
from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

import httpx

from app.core.config import get_settings

_MATCH_URL = "https://api.opensanctions.org/match/sanctions"
_ALGORITHM = "logic-v2"
_QUERY_ID = "q1"
_TIMEOUT_SECONDS = 30.0


class ScreeningProviderError(Exception):
    """Raised on any provider failure (missing key, network, non-2xx, parse)."""


@dataclass(frozen=True)
class MatchResult:
    top_score: Decimal
    match_count: int
    matches: list
    dataset_version: str | None
    algorithm: str


def _api_key() -> str:
    return get_settings().opensanctions_api_key


def _build_envelope(name: str, country: str | None, tax_id: str | None, lei: str | None) -> dict:
    # Array-valued properties; omit keys whose source value is absent (a bare or
    # scalar body is rejected by the API).
    props: dict[str, list[str]] = {"name": [name]}
    if country:
        props["jurisdiction"] = [country]
    if tax_id:
        props["registrationNumber"] = [tax_id]
    if lei:
        props["leiCode"] = [lei]
    return {"queries": {_QUERY_ID: {"schema": "Company", "properties": props}}}


def screen_entity(
    *, name: str, country: str | None, tax_id: str | None, lei: str | None
) -> MatchResult:
    key = _api_key()
    if not key or not key.strip():
        raise ScreeningProviderError("OPENSANCTIONS_API_KEY is not configured")
    envelope = _build_envelope(name, country, tax_id, lei)
    try:
        response = httpx.post(
            f"{_MATCH_URL}?algorithm={_ALGORITHM}",
            headers={"Authorization": f"ApiKey {key}"},
            json=envelope,
            timeout=_TIMEOUT_SECONDS,
        )
        response.raise_for_status()
        data = response.json()
    except httpx.HTTPError as exc:
        raise ScreeningProviderError(f"OpenSanctions request failed: {exc}") from exc
    except ValueError as exc:  # JSON decode
        raise ScreeningProviderError(f"OpenSanctions returned unparseable body: {exc}") from exc

    try:
        results = data["responses"][_QUERY_ID]["results"]
    except (KeyError, TypeError) as exc:
        raise ScreeningProviderError(f"OpenSanctions response missing results: {exc}") from exc

    scores = [Decimal(str(r["score"])) for r in results if "score" in r]
    top_score = max(scores) if scores else Decimal("0")
    dataset_version = data.get("responses", {}).get(_QUERY_ID, {}).get("dataset_version")
    return MatchResult(
        top_score=top_score,
        match_count=len(results),
        matches=results,
        dataset_version=dataset_version,
        algorithm=_ALGORITHM,
    )
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd backend && python -m pytest tests/test_opensanctions_client.py -q`
Expected: PASS (5 passed).

- [ ] **Step 5: Commit**

```bash
git add backend/app/services/opensanctions_client.py backend/tests/test_opensanctions_client.py
git commit -m "feat(w2): OpenSanctions match-API client (mockable I/O boundary)

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Task 4: Threshold mapping (pure function)

**Files:**
- Create: `backend/app/services/sanctions_screening_service.py` (start the module with the pure mapper + module imports)
- Test: `backend/tests/test_sanctions_threshold_mapping.py`

- [ ] **Step 1: Write the failing test**

```python
# backend/tests/test_sanctions_threshold_mapping.py
from decimal import Decimal

import pytest

from app.models.sanctions import ScreeningResult
from app.services.sanctions_screening_service import map_score_to_result

REVIEW = Decimal("0.70")
HARD = Decimal("0.90")


@pytest.mark.parametrize(
    "score,expected",
    [
        ("0.00", ScreeningResult.clear),
        ("0.69", ScreeningResult.clear),
        ("0.70", ScreeningResult.flagged),
        ("0.89", ScreeningResult.flagged),
        ("0.90", ScreeningResult.blocked),
        ("1.00", ScreeningResult.blocked),
    ],
)
def test_boundaries(score, expected):
    assert map_score_to_result(Decimal(score), REVIEW, HARD) == expected
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && python -m pytest tests/test_sanctions_threshold_mapping.py -q`
Expected: FAIL (module/function does not exist).

- [ ] **Step 3: Create the module with the mapper**

```python
# backend/app/services/sanctions_screening_service.py
"""Domain-agnostic sanctions screening + adjudication orchestration.

Writes immutable ``sanctions_screenings`` / ``sanctions_adjudications`` rows,
sets the entity ``sanctions_status``, and emits HMAC audit events. Reuses the
``kyc_gate`` dual-session pattern to record provider-error evidence that
survives the request ``unit_of_work`` rollback.
"""
from __future__ import annotations

import hashlib
import json
import uuid
from datetime import UTC, datetime
from decimal import Decimal

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.database import SessionLocal
from app.models.commercial_partner import CommercialPartner
from app.models.counterparty import Counterparty, SanctionsStatus
from app.models.sanctions import (
    AdjudicationDecision,
    SanctionsAdjudication,
    SanctionsPartnerType,
    SanctionsScreening,
    ScreeningResult,
    ScreeningStatus,
)
from app.services.audit_trail_service import AuditTrailService
from app.services.opensanctions_client import ScreeningProviderError, screen_entity

_PROVIDER = "opensanctions"


def map_score_to_result(
    top_score: Decimal, review_threshold: Decimal, hard_threshold: Decimal
) -> ScreeningResult:
    if top_score >= hard_threshold:
        return ScreeningResult.blocked
    if top_score >= review_threshold:
        return ScreeningResult.flagged
    return ScreeningResult.clear
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd backend && python -m pytest tests/test_sanctions_threshold_mapping.py -q`
Expected: PASS (6 passed).

- [ ] **Step 5: Commit**

```bash
git add backend/app/services/sanctions_screening_service.py backend/tests/test_sanctions_threshold_mapping.py
git commit -m "feat(w2): sanctions threshold mapping (clear/flagged/blocked)

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Task 5: `screen()` — success + provider-error dual-session

**Files:**
- Modify: `backend/app/services/sanctions_screening_service.py`
- Test: `backend/tests/test_sanctions_screen_service.py`

- [ ] **Step 1: Write the failing test**

```python
# backend/tests/test_sanctions_screen_service.py
from decimal import Decimal

import pytest

from app.core.database import SessionLocal
from app.models.audit import AuditEvent
from app.models.commercial_partner import CommercialPartner, CommercialPartnerKind
from app.models.counterparty import KycStatus, RiskRating, SanctionsStatus
from app.models.sanctions import (
    SanctionsPartnerType,
    SanctionsScreening,
    ScreeningResult,
    ScreeningStatus,
)
from app.services import opensanctions_client as oc
from app.services import sanctions_screening_service as svc
from app.services.opensanctions_client import MatchResult, ScreeningProviderError


def _commercial(session) -> CommercialPartner:
    cp = CommercialPartner(
        kind=CommercialPartnerKind.customer, name="Rusal", country="RUS",
        kyc_status=KycStatus.pending, sanctions_status=SanctionsStatus.unscreened,
        risk_rating=RiskRating.medium,
    )
    session.add(cp)
    session.commit()
    session.refresh(cp)
    return cp


def _fake_match(score, monkeypatch):
    monkeypatch.setattr(
        svc, "screen_entity",
        lambda **kw: MatchResult(Decimal(score), 1, [{"score": float(score)}], "2026-05-30", "logic-v2"),
    )


def test_clear_sets_status_and_writes_row_and_audit(monkeypatch):
    _fake_match("0.10", monkeypatch)
    with SessionLocal() as session:
        cp = _commercial(session)
        screening = svc.screen(
            session, SanctionsPartnerType.commercial, cp.id, actor_sub="rm-1", commit=True
        )
        assert screening.status is ScreeningStatus.success
        assert screening.result is ScreeningResult.clear
        session.refresh(cp)
        assert cp.sanctions_status is SanctionsStatus.clear
        ev = (
            session.query(AuditEvent)
            .filter(AuditEvent.event_type == "sanctions_status_changed")
            .filter(AuditEvent.entity_id == cp.id)
            .one()
        )
        assert ev.payload["new_status"] == "clear"


def test_flagged_and_blocked_tiers(monkeypatch):
    for score, expected in [("0.75", SanctionsStatus.flagged), ("0.95", SanctionsStatus.blocked)]:
        _fake_match(score, monkeypatch)
        with SessionLocal() as session:
            cp = _commercial(session)
            svc.screen(session, SanctionsPartnerType.commercial, cp.id, actor_sub="rm", commit=True)
            session.refresh(cp)
            assert cp.sanctions_status is expected


def test_provider_error_records_error_row_and_raises_without_status_change(monkeypatch):
    def boom(**kw):
        raise ScreeningProviderError("down")

    monkeypatch.setattr(svc, "screen_entity", boom)
    with SessionLocal() as session:
        cp = _commercial(session)
        with pytest.raises(Exception) as exc:
            svc.screen(session, SanctionsPartnerType.commercial, cp.id, actor_sub="rm", commit=True)
        assert getattr(exc.value, "status_code", None) == 502
        session.rollback()
        session.refresh(cp)
        assert cp.sanctions_status is SanctionsStatus.unscreened  # untouched
    # error row persisted on the separate session
    with SessionLocal() as check:
        rows = check.query(SanctionsScreening).filter(
            SanctionsScreening.status == ScreeningStatus.error
        ).all()
        assert len(rows) == 1
        assert rows[0].result is None


def test_missing_entity_404(monkeypatch):
    import uuid

    _fake_match("0.10", monkeypatch)
    with SessionLocal() as session:
        with pytest.raises(Exception) as exc:
            svc.screen(session, SanctionsPartnerType.commercial, uuid.uuid4(), actor_sub="rm")
        assert getattr(exc.value, "status_code", None) == 404
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && python -m pytest tests/test_sanctions_screen_service.py -q`
Expected: FAIL (`screen` not defined).

- [ ] **Step 3: Implement `screen()` + helpers**

Append to `backend/app/services/sanctions_screening_service.py`:

```python
def _load_entity(session: Session, partner_type: SanctionsPartnerType, partner_id: uuid.UUID):
    if partner_type is SanctionsPartnerType.commercial:
        entity = session.get(CommercialPartner, partner_id)
    else:
        entity = session.get(Counterparty, partner_id)
    if entity is None or entity.is_deleted:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Partner not found")
    return entity


def _entity_audit_type(partner_type: SanctionsPartnerType) -> str:
    return "commercial_partner" if partner_type is SanctionsPartnerType.commercial else "counterparty"


def _query_hash(name, country, tax_id, lei) -> str:
    canonical = json.dumps(
        {"name": name, "country": country, "tax_id": tax_id, "lei": lei}, sort_keys=True
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _record_error_screening(
    partner_type: SanctionsPartnerType, partner_id: uuid.UUID, *, actor_sub: str, detail: str
) -> None:
    # Dual-session: persist the error evidence on its own committed session so it
    # survives the request unit_of_work rollback (mirrors kyc_gate).
    error_session = SessionLocal()
    try:
        error_session.add(
            SanctionsScreening(
                id=uuid.uuid4(),
                partner_type=partner_type,
                partner_id=partner_id,
                screened_at=datetime.now(UTC),
                provider=_PROVIDER,
                algorithm="logic-v2",
                dataset_version=None,
                query_hash="",
                top_score=None,
                match_count=0,
                matches_json=None,
                result=None,
                actor_sub=actor_sub,
                status=ScreeningStatus.error,
                error_detail=detail[:2000],
            )
        )
        error_session.commit()
    finally:
        error_session.close()


def screen(
    session: Session,
    partner_type: SanctionsPartnerType,
    partner_id: uuid.UUID,
    *,
    actor_sub: str,
    commit: bool = True,
) -> SanctionsScreening:
    entity = _load_entity(session, partner_type, partner_id)
    lei = getattr(entity, "lei", None)  # hedge Counterparty has no lei column
    try:
        match = screen_entity(
            name=entity.name, country=entity.country, tax_id=entity.tax_id, lei=lei
        )
    except ScreeningProviderError as exc:
        _record_error_screening(partner_type, partner_id, actor_sub=actor_sub, detail=str(exc))
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail={"code": "sanctions_screening_provider_error", "partner_id": str(partner_id)},
        ) from exc

    settings = get_settings()
    result = map_score_to_result(
        match.top_score, settings.sanctions_review_threshold, settings.sanctions_hard_threshold
    )
    previous_status = entity.sanctions_status
    screening = SanctionsScreening(
        id=uuid.uuid4(),
        partner_type=partner_type,
        partner_id=partner_id,
        screened_at=datetime.now(UTC),
        provider=_PROVIDER,
        algorithm=match.algorithm,
        dataset_version=match.dataset_version,
        query_hash=_query_hash(entity.name, entity.country, entity.tax_id, lei),
        top_score=match.top_score,
        match_count=match.match_count,
        matches_json=match.matches,
        result=result,
        actor_sub=actor_sub,
        status=ScreeningStatus.success,
        error_detail=None,
    )
    session.add(screening)
    entity.sanctions_status = SanctionsStatus(result.value)
    session.flush()
    AuditTrailService.record(
        session,
        event_id=uuid.uuid4(),
        entity_type=_entity_audit_type(partner_type),
        entity_id=partner_id,
        event_type="sanctions_status_changed",
        payload_raw="",
        payload_obj={
            "partner_type": partner_type.value,
            "partner_id": str(partner_id),
            "previous_status": previous_status.value,
            "new_status": result.value,
            "screening_id": str(screening.id),
            "top_score": str(match.top_score),
            "result": result.value,
            "actor_sub": actor_sub,
        },
        commit=False,
    )
    if commit:
        session.commit()
        session.refresh(screening)
    return screening
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd backend && python -m pytest tests/test_sanctions_screen_service.py -q`
Expected: PASS (4 passed).

- [ ] **Step 5: Commit**

```bash
git add backend/app/services/sanctions_screening_service.py backend/tests/test_sanctions_screen_service.py
git commit -m "feat(w2): screen() writes evidence, sets status, dual-session error path

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Task 6: `adjudicate()` + `effective_sanctions_status()`

**Files:**
- Modify: `backend/app/services/sanctions_screening_service.py`
- Test: `backend/tests/test_sanctions_adjudicate_service.py`

- [ ] **Step 1: Write the failing test**

```python
# backend/tests/test_sanctions_adjudicate_service.py
import uuid
from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest

from app.core.database import SessionLocal
from app.models.audit import AuditEvent
from app.models.commercial_partner import CommercialPartner, CommercialPartnerKind
from app.models.counterparty import KycStatus, RiskRating, SanctionsStatus
from app.models.sanctions import (
    AdjudicationDecision,
    SanctionsPartnerType,
    SanctionsScreening,
    ScreeningResult,
    ScreeningStatus,
)
from app.services import sanctions_screening_service as svc


def _partner(session) -> CommercialPartner:
    cp = CommercialPartner(
        kind=CommercialPartnerKind.customer, name="X", country="BRA",
        kyc_status=KycStatus.pending, sanctions_status=SanctionsStatus.flagged,
        risk_rating=RiskRating.medium,
    )
    session.add(cp)
    session.commit()
    session.refresh(cp)
    return cp


def _screening(session, pid, result, *, when, status_=ScreeningStatus.success) -> SanctionsScreening:
    s = SanctionsScreening(
        id=uuid.uuid4(), partner_type=SanctionsPartnerType.commercial, partner_id=pid,
        screened_at=when, provider="opensanctions", algorithm="logic-v2", query_hash="h",
        top_score=Decimal("0.75"), match_count=1, matches_json=[], result=result,
        actor_sub="rm", status=status_,
    )
    session.add(s)
    session.commit()
    return s


def test_adjudicate_flagged_to_clear(self_=None):
    with SessionLocal() as session:
        cp = _partner(session)
        _screening(session, cp.id, ScreeningResult.flagged, when=datetime.now(UTC))
        adj = svc.adjudicate(
            session, SanctionsPartnerType.commercial, cp.id,
            decision=AdjudicationDecision.clear, reason="false positive match", actor_sub="rm-1",
        )
        assert adj.decision is AdjudicationDecision.clear
        session.refresh(cp)
        assert cp.sanctions_status is SanctionsStatus.clear
        ev = session.query(AuditEvent).filter(
            AuditEvent.event_type == "sanctions_status_adjudicated",
            AuditEvent.entity_id == cp.id,
        ).one()
        assert ev.payload["new_status"] == "clear"


def test_reject_when_latest_not_flagged():
    with SessionLocal() as session:
        cp = _partner(session)
        _screening(session, cp.id, ScreeningResult.blocked, when=datetime.now(UTC))
        with pytest.raises(Exception) as exc:
            svc.adjudicate(
                session, SanctionsPartnerType.commercial, cp.id,
                decision=AdjudicationDecision.clear, reason="should fail here", actor_sub="rm",
            )
        assert getattr(exc.value, "status_code", None) == 422


def test_reject_when_flagged_superseded_by_newer_blocked():
    with SessionLocal() as session:
        cp = _partner(session)
        now = datetime.now(UTC)
        _screening(session, cp.id, ScreeningResult.flagged, when=now - timedelta(hours=2))
        _screening(session, cp.id, ScreeningResult.blocked, when=now)  # newer hard hit
        with pytest.raises(Exception) as exc:
            svc.adjudicate(
                session, SanctionsPartnerType.commercial, cp.id,
                decision=AdjudicationDecision.clear, reason="stale flagged abuse", actor_sub="rm",
            )
        assert getattr(exc.value, "status_code", None) == 422


def test_effective_status_latest_event_wins():
    with SessionLocal() as session:
        cp = _partner(session)
        now = datetime.now(UTC)
        _screening(session, cp.id, ScreeningResult.flagged, when=now)
        eff = svc.effective_sanctions_status(session, SanctionsPartnerType.commercial, cp.id)
        assert eff == "flagged"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && python -m pytest tests/test_sanctions_adjudicate_service.py -q`
Expected: FAIL (`adjudicate` / `effective_sanctions_status` not defined).

- [ ] **Step 3: Implement `adjudicate()` + `effective_sanctions_status()`**

Append to `backend/app/services/sanctions_screening_service.py`:

```python
def _latest_screening(session: Session, partner_type, partner_id) -> SanctionsScreening | None:
    stmt = (
        select(SanctionsScreening)
        .where(
            SanctionsScreening.partner_type == partner_type,
            SanctionsScreening.partner_id == partner_id,
            SanctionsScreening.status == ScreeningStatus.success,
        )
        .order_by(SanctionsScreening.screened_at.desc())
    )
    return session.execute(stmt).scalars().first()


def _latest_adjudication(session: Session, partner_type, partner_id) -> SanctionsAdjudication | None:
    stmt = (
        select(SanctionsAdjudication)
        .where(
            SanctionsAdjudication.partner_type == partner_type,
            SanctionsAdjudication.partner_id == partner_id,
        )
        .order_by(SanctionsAdjudication.adjudicated_at.desc())
    )
    return session.execute(stmt).scalars().first()


def effective_sanctions_status(session: Session, partner_type, partner_id) -> str | None:
    screening = _latest_screening(session, partner_type, partner_id)
    adjudication = _latest_adjudication(session, partner_type, partner_id)
    if screening is None and adjudication is None:
        return None
    if adjudication is None:
        return screening.result.value if screening.result else None
    if screening is None:
        return adjudication.decision.value
    # latest event wins by timestamp
    if adjudication.adjudicated_at >= screening.screened_at:
        return adjudication.decision.value
    return screening.result.value if screening.result else None


def adjudicate(
    session: Session,
    partner_type: SanctionsPartnerType,
    partner_id: uuid.UUID,
    *,
    decision: AdjudicationDecision,
    reason: str,
    actor_sub: str,
    commit: bool = True,
) -> SanctionsAdjudication:
    entity = _load_entity(session, partner_type, partner_id)
    screening = _latest_screening(session, partner_type, partner_id)
    adjudication = _latest_adjudication(session, partner_type, partner_id)
    # valid only when the LATEST compliance event is a screening still `flagged`
    latest_is_flagged_screening = (
        screening is not None
        and screening.result is ScreeningResult.flagged
        and (adjudication is None or screening.screened_at > adjudication.adjudicated_at)
    )
    if not latest_is_flagged_screening:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={
                "code": "sanctions_adjudication_invalid_target",
                "partner_id": str(partner_id),
                "reason": "adjudication is valid only against the latest screening while flagged",
            },
        )
    previous_status = entity.sanctions_status
    row = SanctionsAdjudication(
        id=uuid.uuid4(),
        partner_type=partner_type,
        partner_id=partner_id,
        superseded_screening_id=screening.id,
        decision=decision,
        reason=reason,
        adjudicating_actor_sub=actor_sub,
        adjudicated_at=datetime.now(UTC),
    )
    session.add(row)
    entity.sanctions_status = SanctionsStatus(decision.value)
    session.flush()
    AuditTrailService.record(
        session,
        event_id=uuid.uuid4(),
        entity_type=_entity_audit_type(partner_type),
        entity_id=partner_id,
        event_type="sanctions_status_adjudicated",
        payload_raw="",
        payload_obj={
            "partner_type": partner_type.value,
            "partner_id": str(partner_id),
            "previous_status": previous_status.value,
            "new_status": decision.value,
            "superseded_screening_id": str(screening.id),
            "reason": reason,
            "actor_sub": actor_sub,
        },
        commit=False,
    )
    if commit:
        session.commit()
        session.refresh(row)
    return row
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd backend && python -m pytest tests/test_sanctions_adjudicate_service.py -q`
Expected: PASS (4 passed).

- [ ] **Step 5: Commit**

```bash
git add backend/app/services/sanctions_screening_service.py backend/tests/test_sanctions_adjudicate_service.py
git commit -m "feat(w2): adjudicate() + effective-status (latest-event-wins, flagged-only)

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Task 7: Sanctions schemas

**Files:**
- Create: `backend/app/schemas/sanctions.py`
- Test: `backend/tests/test_sanctions_schemas.py`

- [ ] **Step 1: Write the failing test**

```python
# backend/tests/test_sanctions_schemas.py
import pytest
from pydantic import ValidationError

from app.schemas.sanctions import SanctionsAdjudicationRequest


def test_reason_min_length_enforced():
    with pytest.raises(ValidationError):
        SanctionsAdjudicationRequest(decision="clear", reason="short")  # < 8 chars


def test_decision_must_be_clear_or_blocked():
    ok = SanctionsAdjudicationRequest(decision="clear", reason="valid reason text")
    assert ok.decision == "clear"
    with pytest.raises(ValidationError):
        SanctionsAdjudicationRequest(decision="flagged", reason="valid reason text")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && python -m pytest tests/test_sanctions_schemas.py -q`
Expected: FAIL (module does not exist).

- [ ] **Step 3: Implement the schemas**

```python
# backend/app/schemas/sanctions.py
from __future__ import annotations

import enum
import uuid
from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field


class AdjudicationDecisionIn(str, enum.Enum):
    clear = "clear"
    blocked = "blocked"


class SanctionsScreeningRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    partner_id: uuid.UUID
    screened_at: datetime
    provider: str
    algorithm: str
    top_score: Decimal | None
    match_count: int
    result: str | None
    status: str


class SanctionsAdjudicationRequest(BaseModel):
    decision: AdjudicationDecisionIn
    reason: str = Field(min_length=8)


class SanctionsAdjudicationRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    partner_id: uuid.UUID
    superseded_screening_id: uuid.UUID
    decision: str
    reason: str
    adjudicated_at: datetime
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd backend && python -m pytest tests/test_sanctions_schemas.py -q`
Expected: PASS (2 passed).

- [ ] **Step 5: Commit**

```bash
git add backend/app/schemas/sanctions.py backend/tests/test_sanctions_schemas.py
git commit -m "feat(w2): sanctions screening + adjudication schemas

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Task 8: Commercial-partner `/screen` + `/adjudicate-sanctions` routes

**Files:**
- Modify: `backend/app/api/routes/commercial_partners.py`
- Test: `backend/tests/test_sanctions_routes_commercial.py`

- [ ] **Step 1: Write the failing test**

```python
# backend/tests/test_sanctions_routes_commercial.py
from decimal import Decimal

from fastapi.testclient import TestClient

from app.core.auth import get_current_user
from app.main import app
from app.services import sanctions_screening_service as svc
from app.services.opensanctions_client import MatchResult


def _as(role):
    app.dependency_overrides[get_current_user] = lambda: {"sub": f"{role}-1", "roles": [role]}


def _make_partner(client, kind="customer"):
    _as("trader")
    r = client.post("/commercial-partners", json={"kind": kind, "name": "Rusal", "country": "RUS"})
    assert r.status_code == 201
    return r.json()["id"]


def test_trader_can_screen_commercial(client, monkeypatch):
    monkeypatch.setattr(
        svc, "screen_entity",
        lambda **kw: MatchResult(Decimal("0.10"), 0, [], None, "logic-v2"),
    )
    pid = _make_partner(client)
    _as("trader")
    r = client.post(f"/commercial-partners/{pid}/screen")
    assert r.status_code == 200
    assert r.json()["result"] == "clear"
    app.dependency_overrides.pop(get_current_user, None)


def test_trader_cannot_adjudicate(client):
    pid = _make_partner(client)
    _as("trader")
    r = client.post(
        f"/commercial-partners/{pid}/adjudicate-sanctions",
        json={"decision": "clear", "reason": "trader not allowed"},
    )
    assert r.status_code == 403
    app.dependency_overrides.pop(get_current_user, None)


def test_risk_manager_adjudicates_flagged(client, monkeypatch):
    monkeypatch.setattr(
        svc, "screen_entity",
        lambda **kw: MatchResult(Decimal("0.75"), 1, [{"score": 0.75}], None, "logic-v2"),
    )
    pid = _make_partner(client)
    _as("risk_manager")
    assert client.post(f"/commercial-partners/{pid}/screen").json()["result"] == "flagged"
    r = client.post(
        f"/commercial-partners/{pid}/adjudicate-sanctions",
        json={"decision": "clear", "reason": "confirmed false positive"},
    )
    assert r.status_code == 200
    assert r.json()["decision"] == "clear"
    app.dependency_overrides.pop(get_current_user, None)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && python -m pytest tests/test_sanctions_routes_commercial.py -q`
Expected: FAIL (routes 404 / not defined).

- [ ] **Step 3: Add imports + routes**

In `backend/app/api/routes/commercial_partners.py`, add to imports:

```python
from app.models.sanctions import AdjudicationDecision, SanctionsPartnerType
from app.schemas.sanctions import (
    SanctionsAdjudicationRead,
    SanctionsAdjudicationRequest,
    SanctionsScreeningRead,
)
from app.services.sanctions_screening_service import adjudicate as adjudicate_sanctions
from app.services.sanctions_screening_service import screen as screen_partner
```

Append the routes at the end of the file:

```python
@router.post(
    "/{commercial_partner_id}/screen",
    response_model=SanctionsScreeningRead,
    status_code=status.HTTP_200_OK,
)
def screen_commercial_partner(
    commercial_partner_id: UUID,
    request: Request,
    actor_sub: str = Depends(get_current_actor_sub),
    _: None = Depends(require_any_role("trader", "risk_manager")),
    session: Session = Depends(get_session),
) -> SanctionsScreeningRead:
    with unit_of_work(session, request=request):
        screening = screen_partner(
            session, SanctionsPartnerType.commercial, commercial_partner_id,
            actor_sub=actor_sub, commit=False,
        )
    return SanctionsScreeningRead.model_validate(screening)


@router.post(
    "/{commercial_partner_id}/adjudicate-sanctions",
    response_model=SanctionsAdjudicationRead,
    status_code=status.HTTP_200_OK,
)
def adjudicate_commercial_partner(
    commercial_partner_id: UUID,
    payload: SanctionsAdjudicationRequest,
    request: Request,
    actor_sub: str = Depends(get_current_actor_sub),
    _: None = Depends(require_role("risk_manager")),
    session: Session = Depends(get_session),
) -> SanctionsAdjudicationRead:
    with unit_of_work(session, request=request):
        row = adjudicate_sanctions(
            session, SanctionsPartnerType.commercial, commercial_partner_id,
            decision=AdjudicationDecision(payload.decision.value),
            reason=payload.reason, actor_sub=actor_sub, commit=False,
        )
    return SanctionsAdjudicationRead.model_validate(row)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd backend && python -m pytest tests/test_sanctions_routes_commercial.py -q`
Expected: PASS (3 passed).

- [ ] **Step 5: Commit**

```bash
git add backend/app/api/routes/commercial_partners.py backend/tests/test_sanctions_routes_commercial.py
git commit -m "feat(w2): commercial /screen + /adjudicate-sanctions routes

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Task 9: Hedge counterparty `/screen` + `/adjudicate-sanctions` routes

**Files:**
- Modify: `backend/app/api/routes/counterparties.py`
- Test: `backend/tests/test_sanctions_routes_hedge.py`

- [ ] **Step 1: Write the failing test**

```python
# backend/tests/test_sanctions_routes_hedge.py
from decimal import Decimal

from app.core.auth import get_current_user
from app.main import app
from app.services import sanctions_screening_service as svc
from app.services.opensanctions_client import MatchResult


def _as(role):
    app.dependency_overrides[get_current_user] = lambda: {"sub": f"{role}-1", "roles": [role]}


def _make_broker(client):
    _as("risk_manager")
    r = client.post("/counterparties", json={"type": "broker", "name": "Marex", "country": "GBR"})
    assert r.status_code == 201
    return r.json()["id"]


def test_risk_manager_screens_hedge(client, monkeypatch):
    monkeypatch.setattr(
        svc, "screen_entity",
        lambda **kw: MatchResult(Decimal("0.10"), 0, [], None, "logic-v2"),
    )
    cid = _make_broker(client)
    _as("risk_manager")
    r = client.post(f"/counterparties/{cid}/screen")
    assert r.status_code == 200
    assert r.json()["result"] == "clear"
    app.dependency_overrides.pop(get_current_user, None)


def test_trader_screen_hedge_is_404(client):
    cid = _make_broker(client)
    _as("trader")
    r = client.post(f"/counterparties/{cid}/screen")
    assert r.status_code == 404  # hedge invisible to trader (no existence leak)
    app.dependency_overrides.pop(get_current_user, None)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && python -m pytest tests/test_sanctions_routes_hedge.py -q`
Expected: FAIL (routes not defined).

- [ ] **Step 3: Add imports + routes**

Inspect the current imports/dependencies in `backend/app/api/routes/counterparties.py` (it already imports `require_role`, `get_current_actor_sub`, `get_session`, `unit_of_work`, `_is_trader_only`). Add:

```python
from app.models.sanctions import AdjudicationDecision, SanctionsPartnerType
from app.schemas.sanctions import (
    SanctionsAdjudicationRead,
    SanctionsAdjudicationRequest,
    SanctionsScreeningRead,
)
from app.services.sanctions_screening_service import adjudicate as adjudicate_sanctions
from app.services.sanctions_screening_service import screen as screen_partner
```

Append the routes. The trader-invisible 404 is enforced by reusing the existing `_is_trader_only(actor_roles)` guard (see `list_counterparties`): a trader-only actor must get 404 before the service runs.

```python
@router.post(
    "/{counterparty_id}/screen",
    response_model=SanctionsScreeningRead,
    status_code=status.HTTP_200_OK,
)
def screen_counterparty(
    counterparty_id: UUID,
    request: Request,
    actor_roles: list[str] = Depends(get_current_actor_roles),
    actor_sub: str = Depends(get_current_actor_sub),
    _: None = Depends(require_any_role("trader", "risk_manager", "auditor")),
    session: Session = Depends(get_session),
) -> SanctionsScreeningRead:
    if _is_trader_only(actor_roles):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Counterparty not found")
    with unit_of_work(session, request=request):
        screening = screen_partner(
            session, SanctionsPartnerType.hedge, counterparty_id,
            actor_sub=actor_sub, commit=False,
        )
    return SanctionsScreeningRead.model_validate(screening)


@router.post(
    "/{counterparty_id}/adjudicate-sanctions",
    response_model=SanctionsAdjudicationRead,
    status_code=status.HTTP_200_OK,
)
def adjudicate_counterparty(
    counterparty_id: UUID,
    payload: SanctionsAdjudicationRequest,
    request: Request,
    actor_roles: list[str] = Depends(get_current_actor_roles),
    actor_sub: str = Depends(get_current_actor_sub),
    _: None = Depends(require_role("risk_manager")),
    session: Session = Depends(get_session),
) -> SanctionsAdjudicationRead:
    if _is_trader_only(actor_roles):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Counterparty not found")
    with unit_of_work(session, request=request):
        row = adjudicate_sanctions(
            session, SanctionsPartnerType.hedge, counterparty_id,
            decision=AdjudicationDecision(payload.decision.value),
            reason=payload.reason, actor_sub=actor_sub, commit=False,
        )
    return SanctionsAdjudicationRead.model_validate(row)
```

Confirm `get_current_actor_roles` is imported in `counterparties.py` (it is used by `list_counterparties`); if missing from the import block, add it from `app.core.auth`.

- [ ] **Step 4: Run test to verify it passes**

Run: `cd backend && python -m pytest tests/test_sanctions_routes_hedge.py -q`
Expected: PASS (2 passed).

- [ ] **Step 5: Commit**

```bash
git add backend/app/api/routes/counterparties.py backend/tests/test_sanctions_routes_hedge.py
git commit -m "feat(w2): hedge /screen + /adjudicate-sanctions routes (trader 404)

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Task 10: Scheduled daily re-screen task

**Files:**
- Create: `backend/app/tasks/sanctions_rescreen_task.py`
- Modify: `backend/app/tasks/scheduler.py`
- Test: `backend/tests/test_sanctions_rescreen_task.py`

- [ ] **Step 1: Write the failing test**

```python
# backend/tests/test_sanctions_rescreen_task.py
from decimal import Decimal

from app.core.database import SessionLocal
from app.models.commercial_partner import CommercialPartner, CommercialPartnerKind
from app.models.counterparty import Counterparty, CounterpartyType, KycStatus, RiskRating, SanctionsStatus
from app.models.sanctions import SanctionsScreening, ScreeningStatus
from app.services import sanctions_screening_service as svc
from app.services.opensanctions_client import MatchResult, ScreeningProviderError
from app.tasks.sanctions_rescreen_task import run_sanctions_rescreen_daily


def _seed():
    with SessionLocal() as s:
        s.add(CommercialPartner(
            kind=CommercialPartnerKind.customer, name="C", country="BRA",
            kyc_status=KycStatus.pending, sanctions_status=SanctionsStatus.unscreened,
            risk_rating=RiskRating.medium,
        ))
        s.add(Counterparty(
            type=CounterpartyType.broker, name="B", country="GBR",
            kyc_status=KycStatus.pending, sanctions_status=SanctionsStatus.unscreened,
            risk_rating=RiskRating.medium,
        ))
        s.commit()


def test_rescreens_both_domains(monkeypatch):
    _seed()
    monkeypatch.setattr(
        svc, "screen_entity",
        lambda **kw: MatchResult(Decimal("0.05"), 0, [], None, "logic-v2"),
    )
    summary = run_sanctions_rescreen_daily()
    assert summary["screened"] == 2
    assert summary["errors"] == 0
    with SessionLocal() as s:
        rows = s.query(SanctionsScreening).filter(
            SanctionsScreening.status == ScreeningStatus.success
        ).all()
        assert len(rows) == 2


def test_continues_on_per_entity_error(monkeypatch):
    _seed()
    calls = {"n": 0}

    def flaky(**kw):
        calls["n"] += 1
        if calls["n"] == 1:
            raise ScreeningProviderError("down")
        return MatchResult(Decimal("0.05"), 0, [], None, "logic-v2")

    monkeypatch.setattr(svc, "screen_entity", flaky)
    summary = run_sanctions_rescreen_daily()
    assert summary["screened"] == 1
    assert summary["errors"] == 1
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && python -m pytest tests/test_sanctions_rescreen_task.py -q`
Expected: FAIL (module does not exist).

- [ ] **Step 3: Implement the task**

```python
# backend/app/tasks/sanctions_rescreen_task.py
"""Scheduled daily sanctions re-screen across both domains."""
from __future__ import annotations

from app.core.database import SessionLocal
from app.core.logging import get_logger
from app.models.commercial_partner import CommercialPartner
from app.models.counterparty import Counterparty
from app.models.sanctions import SanctionsPartnerType
from app.services.sanctions_screening_service import screen

logger = get_logger()

_ACTOR = "service:sanctions_screening"


def run_sanctions_rescreen_daily() -> dict:
    """Re-screen all active, non-deleted partners across both domains.

    Per-entity failures are isolated: the screening service records the
    status=error evidence on its own session and raises; this loop logs and
    continues so one provider hiccup never aborts the whole run.
    """
    screened = 0
    errors = 0
    with SessionLocal() as session:
        commercial_ids = [
            row.id
            for row in session.query(CommercialPartner.id.label("id"))
            .filter(CommercialPartner.is_deleted == False, CommercialPartner.is_active == True)  # noqa: E712
            .all()
        ]
        hedge_ids = [
            row.id
            for row in session.query(Counterparty.id.label("id"))
            .filter(Counterparty.is_deleted == False, Counterparty.is_active == True)  # noqa: E712
            .all()
        ]

    targets = [(SanctionsPartnerType.commercial, pid) for pid in commercial_ids] + [
        (SanctionsPartnerType.hedge, cid) for cid in hedge_ids
    ]
    for partner_type, partner_id in targets:
        work = SessionLocal()
        try:
            screen(work, partner_type, partner_id, actor_sub=_ACTOR, commit=True)
            screened += 1
        except Exception as exc:  # provider error already recorded on its own session
            work.rollback()
            errors += 1
            logger.warning(
                "sanctions_rescreen_entity_failed",
                partner_type=partner_type.value,
                partner_id=str(partner_id),
                error=str(exc),
            )
        finally:
            work.close()

    logger.info("sanctions_rescreen_complete", screened=screened, errors=errors)
    return {"screened": screened, "errors": errors}
```

- [ ] **Step 4: Register the cron job**

In `backend/app/tasks/scheduler.py`, add the import (with the other task imports, ~line 11):

```python
from app.tasks.sanctions_rescreen_task import run_sanctions_rescreen_daily
```

Add the job inside `start_scheduler()` (after the `finance_pipeline_daily` block):

```python
    _scheduler.add_job(
        run_sanctions_rescreen_daily,
        trigger="cron",
        hour=int(os.getenv("SANCTIONS_RESCREEN_CRON_HOUR", "2")),
        minute=int(os.getenv("SANCTIONS_RESCREEN_CRON_MINUTE", "0")),
        id="sanctions_rescreen_daily",
        replace_existing=True,
        misfire_grace_time=3600,
    )
```

- [ ] **Step 5: Run test to verify it passes**

Run: `cd backend && python -m pytest tests/test_sanctions_rescreen_task.py -q`
Expected: PASS (2 passed).

- [ ] **Step 6: Commit**

```bash
git add backend/app/tasks/sanctions_rescreen_task.py backend/app/tasks/scheduler.py backend/tests/test_sanctions_rescreen_task.py
git commit -m "feat(w2): daily sanctions re-screen task + scheduler registration

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Task 11: RBAC matrix coverage

**Files:**
- Modify: `backend/tests/test_rbac_matrix_enforcement.py`

- [ ] **Step 1: Write the failing tests**

Add to `backend/tests/test_rbac_matrix_enforcement.py` (follow the file's existing helper/fixture conventions for setting roles and creating entities; the assertions below are the contract):

```python
def test_auditor_cannot_screen_commercial(client):
    # auditor is read-only across mutation surfaces; /screen is a mutation
    ...  # create a commercial partner (any allowed role), then auditor POST /screen -> 403


def test_auditor_cannot_screen_hedge(client):
    ...  # auditor POST /counterparties/{id}/screen -> 403


def test_trader_cannot_adjudicate_hedge_is_404(client):
    ...  # trader POST /counterparties/{id}/adjudicate-sanctions -> 404 (hedge invisible)
```

Fill each test body using the same role-override + entity-creation helpers already used elsewhere in this file (e.g. the `_as(...)`/dependency-override pattern). Assert the documented status codes: auditor `/screen` → 403 (role gate denies non-{trader,risk_manager}); trader hedge adjudicate → 404.

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd backend && python -m pytest tests/test_rbac_matrix_enforcement.py -k "screen or adjudicate" -q`
Expected: FAIL initially if assertions don't yet hold; if the route gates from Tasks 8/9 are correct they may PASS immediately — in that case this task only adds the regression coverage.

- [ ] **Step 3: Ensure gates satisfy the assertions**

No code change expected — the `require_any_role("trader","risk_manager")` gate on commercial `/screen` already excludes auditor (403), and the `_is_trader_only` guard on hedge routes yields 404. If a test fails, fix the corresponding route gate from Task 8/9, not the test.

- [ ] **Step 4: Run to verify pass**

Run: `cd backend && python -m pytest tests/test_rbac_matrix_enforcement.py -k "screen or adjudicate" -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/tests/test_rbac_matrix_enforcement.py
git commit -m "test(w2): RBAC matrix coverage for screen/adjudicate endpoints

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Task 12: Regenerate OpenAPI types + full-suite gate

**Files:**
- Regen: `frontend-svelte/src/lib/api/schema.d.ts`

- [ ] **Step 1: Run the full backend suite**

Run: `cd backend && python -m pytest -q`
Expected: all W2 tests pass; the only failures are the known 26 pre-existing environmental failures (auth-`APP_ENV`, internal-test-gating, whatsapp, webhook, service-token). Confirm zero W2-caused failures.

- [ ] **Step 2: Regenerate frontend OpenAPI types**

Start the backend, then regen (matches the W1 procedure):

Run:
```bash
cd backend && SCHEDULER_DISABLED=1 uvicorn app.main:app --port 8000 &
cd frontend-svelte && npm run api:types && npm run api:types:check
```
Expected: `schema.d.ts` updated with the four new endpoints; `api:types:check` passes (no drift).

- [ ] **Step 3: Frontend check (unaffected, must stay green)**

Run: `cd frontend-svelte && npm run check && npm run test`
Expected: svelte-check 0 errors; vitest all pass.

- [ ] **Step 4: Commit**

```bash
git add frontend-svelte/src/lib/api/schema.d.ts
git commit -m "chore(w2): regen schema.d.ts for screen/adjudicate endpoints

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

- [ ] **Step 5: Open the PR**

```bash
git push -u origin w2/sanctions-screening
gh pr create --base main --title "W2: Sanctions Screening (OpenSanctions writer + adjudication + scheduled re-screen)" --body "Implements docs/superpowers/specs/2026-05-30-w2-sanctions-screening-design.md. Writer-only (no gate changes — RFQ re-target is W3). Both domains. REVIEW 0.70 / HARD 0.90."
```
Then await Codex Connector review (`+1` = acceptance; inline comments lag — re-poll). CI: `Backend: pytest`, `alembic upgrade head against fresh Postgres`, `openapi_diff`, frontend `svelte-check`/`vitest`, both E2E. If the pre-push hook fails on Anthropic API credits, this is a code-only push — bypass requires explicit orchestrator authorization (`git push --no-verify`).

---

## Self-review (completed by plan author)

**Spec coverage:** §2 client → T3; §3 screen + dual-session → T5; §3 adjudicate + effective-status → T6; §4 RBAC/endpoints → T8/T9/T11; §5 config + boot validator → T1; service identity → T2; scheduler re-screen → T10; thresholds → T1 (0.70/0.90); schemas → T7; schema.d.ts regen → T12; testing matrix → T3–T11. No migration (tables from 049). ✔

**Placeholder scan:** Task 11 intentionally defers test *bodies* to the file's existing role-override helpers (the contract/asserts are explicit) — this is the one place the engineer must mirror an in-file pattern rather than copy verbatim, because the helper names live in that test module. All production code is complete.

**Type consistency:** `screen_entity(*, name, country, tax_id, lei)` keyword-only — used consistently in client, service, and all monkeypatches. `MatchResult(top_score, match_count, matches, dataset_version, algorithm)` positional order consistent across tests. `screen(session, partner_type, partner_id, *, actor_sub, commit)` and `adjudicate(..., *, decision, reason, actor_sub, commit)` consistent T5/T6/T8/T9/T10. `map_score_to_result(top_score, review, hard)` consistent T4/T5. `SanctionsStatus(result.value)` / `SanctionsStatus(decision.value)` conversion consistent. Route `AdjudicationDecision(payload.decision.value)` bridges schema enum → model enum.
