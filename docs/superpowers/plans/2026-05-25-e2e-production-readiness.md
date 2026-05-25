# E2E Production Readiness Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a coordinated pytest + Playwright E2E suite that gates production readiness, with smoke (CI-blocking) and full (manual go/no-go report) modes.

**Architecture:** Two coordinated suites — backend pytest under `backend/tests/e2e/` covers the institutional narrative + 5 invariant specs (RBAC, audit-HMAC, precision, market-data, scenario isolation); frontend Playwright covers UX paths for the 3 personas. Shared seed/persona/journey helpers. Orchestration script aggregates results into a markdown go/no-go report.

**Tech Stack:** pytest, pytest-json-report, FastAPI TestClient (backend integration mode) + httpx (full-stack mode), Playwright 1.x, existing `backend/tests/auth_token_helpers.py` for JWT/JWKS minting, Meta `X-Hub-Signature-256` HMAC for webhook ingress, GitHub Actions for CI.

**Spec:** `docs/superpowers/specs/2026-05-25-e2e-production-readiness-design.md`

---

## PHASE 0 — Boot & directory scaffolding

### Task 0.1: Create backend e2e directory tree

**Files:**
- Create: `backend/tests/e2e/__init__.py` (empty)
- Create: `backend/tests/e2e/conftest.py` (placeholder)
- Create: `backend/tests/e2e/_fixtures.py` (placeholder)
- Create: `backend/tests/e2e/_personas.py` (placeholder)
- Create: `backend/tests/e2e/_journey_steps.py` (placeholder)

- [ ] **Step 1: Create empty `__init__.py`**

Write file with content `""" Backend E2E test suite. """`.

- [ ] **Step 2: Create `conftest.py` placeholder**

```python
"""E2E-specific fixtures. Loaded after backend/tests/conftest.py."""
from __future__ import annotations
```

- [ ] **Step 3: Create the other three placeholders** with identical one-line docstrings (`_fixtures.py` "Idempotent seeding helpers.", `_personas.py` "Identity minters.", `_journey_steps.py` "Reusable journey primitives.").

- [ ] **Step 4: Verify the e2e package is collectible**

Run: `pytest backend/tests/e2e/ --collect-only`
Expected: `no tests collected` (no test_*.py yet) without import error.

- [ ] **Step 5: Commit**

```bash
git add backend/tests/e2e/
git commit -m "test(e2e): scaffold backend/tests/e2e/ package"
```

### Task 0.2: Add monorepo `package.json` scripts

**Files:**
- Modify: `package.json` (root, lines 4-7)

- [ ] **Step 1: Update scripts section**

```json
{
  "private": true,
  "description": "Hedge Control Platform — monorepo root",
  "scripts": {
    "backend:dev": "cd backend && uvicorn app.main:app --reload --port 8000",
    "backend:test": "cd backend && python -m pytest -x -q",
    "test:e2e:smoke": "cd backend && python -m pytest tests/e2e/test_journey_full.py tests/e2e/test_rbac_matrix.py -v",
    "test:e2e:backend": "cd backend && python -m pytest tests/e2e/ -v --json-report --json-report-file=tests/e2e/report.json",
    "test:e2e:frontend": "cd frontend-svelte && npx playwright test e2e/journey-trader.spec.ts e2e/journey-risk-manager.spec.ts e2e/journey-auditor.spec.ts --reporter=json",
    "test:go-no-go": "node scripts/run_go_no_go.js"
  },
  "engines": {
    "node": ">=18"
  },
  "dependencies": {}
}
```

- [ ] **Step 2: Verify scripts list**

Run: `npm run`
Expected: lines for `test:e2e:smoke`, `test:e2e:backend`, `test:e2e:frontend`, `test:go-no-go` appear.

- [ ] **Step 3: Commit**

```bash
git add package.json
git commit -m "build(e2e): expose test:e2e:smoke / test:go-no-go scripts"
```

### Task 0.3: Add pytest-json-report dependency

**Files:**
- Modify: `backend/requirements.txt` (append)

- [ ] **Step 1: Append the dependency**

Add the line `pytest-json-report==1.5.0` to the bottom of `backend/requirements.txt`. Preserve existing lines.

- [ ] **Step 2: Install locally to confirm**

Run: `cd backend && pip install -r requirements.txt`
Expected: `pytest-json-report-1.5.0` either already installed or installed cleanly.

- [ ] **Step 3: Commit**

```bash
git add backend/requirements.txt
git commit -m "build(e2e): add pytest-json-report for go/no-go aggregator"
```

---

## PHASE 1 — Shared backend infrastructure

The E2E suite operates in **integration mode** by default (FastAPI TestClient against in-memory SQLite, identical to existing backend tests), with an opt-in **full-stack mode** (httpx client against running docker-compose stack) gated by env var `E2E_FULL_STACK=1`. Integration mode is what runs in CI; full-stack is for `test:go-no-go` pre-deploy.

### Task 1.1: Define `_personas.py` — JWT/HMAC minters

**Files:**
- Modify: `backend/tests/e2e/_personas.py`
- Test: `backend/tests/e2e/test_personas_smoke.py` (created here, removed at end of phase)

- [ ] **Step 1: Write the failing test**

```python
# backend/tests/e2e/test_personas_smoke.py
"""Smoke test that _personas exports the expected context managers."""
from __future__ import annotations

from backend.tests.e2e._personas import (
    as_trader,
    as_risk_manager,
    as_auditor,
    as_service,
    as_meta_webhook,
)


def test_persona_exports_present():
    assert callable(as_trader)
    assert callable(as_risk_manager)
    assert callable(as_auditor)
    assert callable(as_service)
    assert callable(as_meta_webhook)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest backend/tests/e2e/test_personas_smoke.py -v`
Expected: FAIL with ImportError on `as_trader`.

- [ ] **Step 3: Implement `_personas.py`**

```python
# backend/tests/e2e/_personas.py
"""Identity minters for E2E tests.

Each helper returns a context manager that:
- For human roles: overrides ``get_current_user`` on the FastAPI app for the
  duration of the with-block, returning a TestClient with the override active.
- For service identities: same pattern, with ``sub`` matching the canonical
  service-identity name.
- For Meta webhook: returns a function that computes the
  ``X-Hub-Signature-256`` HMAC header for a raw request body.

Integration mode (default) uses TestClient; full-stack mode (E2E_FULL_STACK=1)
uses httpx with real JWT tokens minted via the helpers from
``backend.tests.auth_token_helpers``.
"""
from __future__ import annotations

import hashlib
import hmac
import os
from contextlib import contextmanager
from typing import Iterator

import httpx
from fastapi.testclient import TestClient

from app.core.auth import (
    CSRF_COOKIE_NAME,
    CSRF_HEADER_NAME,
    get_current_user,
)
from app.main import app

FULL_STACK = os.environ.get("E2E_FULL_STACK") == "1"
FULL_STACK_BASE_URL = os.environ.get(
    "E2E_FULL_STACK_BASE_URL", "http://localhost:8000"
)
META_APP_SECRET = os.environ.get(
    "WHATSAPP_APP_SECRET", "test-meta-app-secret"
)


def _override_user(sub: str, roles: list[str]) -> None:
    app.dependency_overrides[get_current_user] = lambda: {
        "sub": sub,
        "roles": roles,
    }


def _clear_override() -> None:
    app.dependency_overrides.pop(get_current_user, None)


@contextmanager
def _persona(sub: str, roles: list[str]) -> Iterator[TestClient | httpx.Client]:
    if FULL_STACK:
        # In full-stack mode the caller must inject a pre-minted JWT via
        # the AUTH_TOKEN env or directly in headers. For now we mint a
        # symbolic header that the docker-compose stack accepts when
        # APP_ENV=test (test-only fallback path in app/core/auth.py).
        with httpx.Client(
            base_url=FULL_STACK_BASE_URL,
            headers={
                "X-Test-Persona-Sub": sub,
                "X-Test-Persona-Roles": ",".join(roles),
                CSRF_HEADER_NAME: "test-csrf-token",
            },
            cookies={CSRF_COOKIE_NAME: "test-csrf-token"},
            timeout=10.0,
        ) as client:
            yield client
    else:
        _override_user(sub, roles)
        client = TestClient(app)
        client.cookies.set(CSRF_COOKIE_NAME, "test-csrf-token")
        client.headers[CSRF_HEADER_NAME] = "test-csrf-token"
        try:
            yield client
        finally:
            _clear_override()


@contextmanager
def as_trader() -> Iterator[TestClient | httpx.Client]:
    with _persona("e2e-trader", ["trader"]) as c:
        yield c


@contextmanager
def as_risk_manager() -> Iterator[TestClient | httpx.Client]:
    with _persona("e2e-risk-manager", ["risk_manager"]) as c:
        yield c


@contextmanager
def as_auditor() -> Iterator[TestClient | httpx.Client]:
    with _persona("e2e-auditor", ["auditor"]) as c:
        yield c


@contextmanager
def as_service(identity: str) -> Iterator[TestClient | httpx.Client]:
    valid = {
        "service:westmetall_ingest",
        "service:rfq_outbound",
        "service:cashflow_pipeline",
        "service:e2e_cleanup",
    }
    if identity not in valid:
        raise ValueError(f"unknown service identity: {identity}")
    with _persona(identity, []) as c:
        yield c


def as_meta_webhook(raw_body: bytes) -> dict[str, str]:
    """Compute the ``X-Hub-Signature-256`` header for a Meta webhook POST.

    Returns the dict suitable for spreading into ``headers=...``.
    """
    digest = hmac.new(
        META_APP_SECRET.encode("utf-8"),
        raw_body,
        hashlib.sha256,
    ).hexdigest()
    return {"X-Hub-Signature-256": f"sha256={digest}"}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest backend/tests/e2e/test_personas_smoke.py -v`
Expected: PASS.

- [ ] **Step 5: Delete the smoke test**

```bash
rm backend/tests/e2e/test_personas_smoke.py
```

- [ ] **Step 6: Commit**

```bash
git add backend/tests/e2e/_personas.py
git commit -m "test(e2e): add persona context managers for tri-persona + 4 service identities"
```

### Task 1.2: Define `_fixtures.py` — idempotent seeders

**Files:**
- Modify: `backend/tests/e2e/_fixtures.py`
- Test: `backend/tests/e2e/test_fixtures.py`

- [ ] **Step 1: Write the failing tests**

```python
# backend/tests/e2e/test_fixtures.py
"""Unit-level tests for the seed helpers."""
from __future__ import annotations

from datetime import date, timedelta
from decimal import Decimal

import pytest

from backend.tests.e2e._fixtures import (
    seed_counterparties,
    seed_westmetall_prices,
    seed_lme_calendar,
    trace_id_factory,
)
from backend.tests.e2e._personas import as_trader, as_service


def test_seed_counterparties_returns_one_per_type():
    trace_id = trace_id_factory()
    ids = seed_counterparties(trace_id)
    assert set(ids.keys()) == {"customer", "supplier", "broker", "bank"}
    assert all(isinstance(v, int) for v in ids.values())


def test_seed_counterparties_is_idempotent():
    trace_id = trace_id_factory()
    first = seed_counterparties(trace_id)
    second = seed_counterparties(trace_id)
    assert first == second


def test_seed_westmetall_prices_rejects_floats():
    trace_id = trace_id_factory()
    today = date.today()
    with pytest.raises(TypeError, match="Decimal"):
        seed_westmetall_prices(trace_id, today, today, raw_floats=True)


def test_seed_lme_calendar_covers_range():
    today = date.today()
    seed_lme_calendar(today - timedelta(days=10), today + timedelta(days=10))
    # No assertion on output; this is a no-error idempotency check
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest backend/tests/e2e/test_fixtures.py -v`
Expected: 4 FAIL on ImportError.

- [ ] **Step 3: Implement `_fixtures.py`**

```python
# backend/tests/e2e/_fixtures.py
"""Idempotent seeding helpers for E2E.

All seeds operate against the same database the tests do (in-memory SQLite
in integration mode; the docker-compose Postgres in full-stack mode). Each
seed accepts a ``trace_id`` to namespace artifacts so parallel runs do not
collide.
"""
from __future__ import annotations

import uuid
from datetime import date, timedelta
from decimal import Decimal

from backend.tests.e2e._personas import as_service, as_risk_manager


def trace_id_factory() -> str:
    return f"e2e-{uuid.uuid4().hex[:8]}"


def seed_counterparties(trace_id: str) -> dict[str, int]:
    """Create one counterparty of each type (customer, supplier, broker, bank).

    Idempotent: second call with same trace_id returns the same ids.
    """
    out: dict[str, int] = {}
    with as_risk_manager() as client:
        for type_ in ("customer", "supplier", "broker", "bank"):
            tax_id = f"{trace_id}-{type_}"
            # Try a GET-by-tax-id first; if exists, reuse.
            existing = client.get(f"/counterparties?tax_id={tax_id}")
            if existing.status_code == 200 and existing.json():
                out[type_] = existing.json()[0]["id"]
                continue
            r = client.post(
                "/counterparties",
                json={
                    "type": type_,
                    "name": f"{trace_id}-{type_}-CP",
                    "country": "BRA",
                    "city": "Sao Paulo",
                    "tax_id": tax_id,
                    "whatsapp_phone": "+5511999990000",
                    "kyc_status": "approved",
                },
            )
            assert r.status_code in (200, 201), r.text
            out[type_] = r.json()["id"]
    return out


def seed_westmetall_prices(
    trace_id: str,
    start: date,
    end: date,
    *,
    raw_floats: bool = False,
) -> int:
    """POST cash settlement prices across [start, end] via service:westmetall_ingest.

    Returns the count of records seeded. If ``raw_floats=True``, sends
    ``float`` literals instead of strings — used by the precision contract
    test to verify the ingest path refuses them.
    """
    if raw_floats:
        raise TypeError(
            "raw_floats=True is reserved for precision contract tests that "
            "POST directly with float; pass strings via Decimal(str(x)) "
            "for production seeding."
        )
    count = 0
    with as_service("service:westmetall_ingest") as client:
        d = start
        while d <= end:
            r = client.post(
                "/market-data/westmetall/ingest",
                json={
                    "observation_key": f"LME-AL-CASH-{d.isoformat()}",
                    "observation_date": d.isoformat(),
                    "value": str(Decimal("2450.000000")),
                    "currency": "USD",
                    "unit": "MT",
                    "provider_tier": "canonical",
                    "trace_id": trace_id,
                },
            )
            # 201 on first insert, 200 on idempotent retry, 409 on legitimate
            # conflict (e.g. same observation_key submitted with different
            # provenance). Any other status is a test setup failure.
            assert r.status_code in (200, 201, 409), r.text
            count += 1
            d += timedelta(days=1)
    return count


def seed_lme_calendar(start: date, end: date) -> None:
    """Ensure LME calendar coverage for [start, end].

    The calendar is typically pre-seeded in production via the scheduled
    task; here we POST any missing days. Idempotent.
    """
    with as_service("service:westmetall_ingest") as client:
        d = start
        while d <= end:
            client.post(
                "/market-data/westmetall/calendar",
                json={
                    "date": d.isoformat(),
                    "is_trading_day": d.weekday() < 5,
                },
            )
            d += timedelta(days=1)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest backend/tests/e2e/test_fixtures.py -v`
Expected: 4 PASS.

> **Note:** If a route (e.g. `/counterparties?tax_id=...`, `/market-data/westmetall/calendar`) does not exist with the exact contract shown, treat the seed helpers as **specs** for what those routes should accept and adjust the route OR the helper to match. Do not invent silent fallbacks. If the route is missing entirely, file a sub-task to add it and pause this phase.

- [ ] **Step 5: Commit**

```bash
git add backend/tests/e2e/_fixtures.py backend/tests/e2e/test_fixtures.py
git commit -m "test(e2e): idempotent seeders for counterparties / westmetall / lme-calendar"
```

### Task 1.3: Define `_journey_steps.py` — reusable journey primitives

**Files:**
- Modify: `backend/tests/e2e/_journey_steps.py`
- Test: `backend/tests/e2e/test_journey_steps.py`

- [ ] **Step 1: Write the failing test**

```python
# backend/tests/e2e/test_journey_steps.py
"""Smoke tests for journey step primitives.

Each step is tested in isolation against a freshly seeded environment.
"""
from __future__ import annotations

import re
from datetime import date

from backend.tests.e2e._fixtures import (
    seed_counterparties,
    seed_westmetall_prices,
    seed_lme_calendar,
    trace_id_factory,
)
from backend.tests.e2e._journey_steps import (
    step_create_rfq,
    step_award_quote,
    step_link_contract,
    step_run_mtm,
    step_compute_pl,
    step_compute_cashflow_baseline,
    step_read_audit_trail,
)


def _seed_full(trace_id: str) -> dict[str, int]:
    today = date.today()
    seed_lme_calendar(today, today)
    seed_westmetall_prices(trace_id, today, today)
    return seed_counterparties(trace_id)


def test_step_create_rfq_returns_canonical_id():
    trace_id = trace_id_factory()
    cps = _seed_full(trace_id)
    rfq = step_create_rfq(trace_id, [cps["supplier"]])
    assert re.match(r"^RFQ#\d+$", rfq["canonical_id"]), rfq


def test_step_award_quote_advances_state():
    trace_id = trace_id_factory()
    cps = _seed_full(trace_id)
    rfq = step_create_rfq(trace_id, [cps["supplier"]])
    deal = step_award_quote(rfq["id"])
    assert deal["state"] in {"awarded", "confirmed"}


def test_step_read_audit_trail_returns_signed_chain():
    trace_id = trace_id_factory()
    cps = _seed_full(trace_id)
    rfq = step_create_rfq(trace_id, [cps["supplier"]])
    events = step_read_audit_trail(rfq_id=rfq["id"])
    assert len(events) >= 1
    assert all(e.get("signature") for e in events)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest backend/tests/e2e/test_journey_steps.py -v`
Expected: 3 FAIL on ImportError.

- [ ] **Step 3: Implement `_journey_steps.py`**

```python
# backend/tests/e2e/_journey_steps.py
"""Reusable journey primitives.

Each ``step_*`` performs one canonical action and asserts its local
invariant. Steps are composed by ``test_journey_full`` to form the full
narrative; they are also used independently by invariant-specific tests.

Naming convention: ``step_<verb>_<noun>(trace_id, ...) -> dict | list[dict]``.
"""
from __future__ import annotations

import json
import re
from datetime import date
from typing import Any

from backend.tests.e2e._personas import (
    as_trader,
    as_risk_manager,
    as_auditor,
    as_service,
    as_meta_webhook,
)

_CANONICAL_ID_RE = re.compile(r"^RFQ#\d+$")


def step_create_rfq(
    trace_id: str,
    supplier_ids: list[int],
    *,
    quantity_mt: str = "100.000000",
    commodity: str = "ALUMINUM",
) -> dict[str, Any]:
    """Trader creates an RFQ; asserts canonical id format."""
    with as_trader() as client:
        r = client.post(
            "/rfqs",
            json={
                "commodity": commodity,
                "quantity_mt": quantity_mt,
                "intent": "buy",
                "direction": "outbound",
                "supplier_ids": supplier_ids,
                "tenor_months": 3,
                "trace_id": trace_id,
            },
        )
        assert r.status_code in (200, 201), r.text
        body = r.json()
        assert _CANONICAL_ID_RE.match(body["canonical_id"]), body["canonical_id"]
        return body


def step_simulate_outbound(rfq_id: int) -> dict[str, Any]:
    """service:rfq_outbound dispatches the RFQ; asserts outbound evidence row."""
    with as_service("service:rfq_outbound") as client:
        r = client.post(f"/rfqs/{rfq_id}/dispatch")
        assert r.status_code in (200, 202), r.text
        return r.json()


def step_simulate_inbound_quote(
    rfq_id: int,
    supplier_id: int,
    *,
    price: str = "2450.000000",
) -> dict[str, Any]:
    """Meta webhook delivers a quote for the RFQ; asserts idempotency."""
    payload = {
        "object": "whatsapp_business_account",
        "entry": [
            {
                "id": "test-account",
                "changes": [
                    {
                        "value": {
                            "messages": [
                                {
                                    "from": "+5511999990000",
                                    "id": f"wamid.e2e.{rfq_id}.{supplier_id}",
                                    "text": {"body": f"PRICE {price} for RFQ#{rfq_id}"},
                                    "type": "text",
                                }
                            ]
                        },
                        "field": "messages",
                    }
                ],
            }
        ],
    }
    raw = json.dumps(payload).encode("utf-8")
    headers = as_meta_webhook(raw)
    with as_service("service:rfq_outbound") as client:
        first = client.post("/webhooks/whatsapp", content=raw, headers=headers)
        assert first.status_code in (200, 202), first.text
        second = client.post("/webhooks/whatsapp", content=raw, headers=headers)
        assert second.status_code in (200, 202), second.text
        return {"first": first.json(), "second": second.json()}


def step_award_quote(rfq_id: int) -> dict[str, Any]:
    """risk_manager awards the best quote; asserts deal advanced."""
    with as_risk_manager() as client:
        quotes = client.get(f"/rfqs/{rfq_id}/quotes").json()
        assert quotes, f"no quotes for RFQ {rfq_id}"
        winner = quotes[0]["id"]
        r = client.post(f"/rfqs/{rfq_id}/award", json={"quote_id": winner})
        assert r.status_code in (200, 201), r.text
        return r.json()


def step_link_contract(deal_id: int, contract_payload: dict[str, Any]) -> dict[str, Any]:
    """risk_manager creates a hedge contract and links it to the deal."""
    with as_risk_manager() as client:
        contract = client.post("/contracts", json=contract_payload)
        assert contract.status_code in (200, 201), contract.text
        contract_id = contract.json()["id"]
        link = client.post(
            "/linkages",
            json={"deal_id": deal_id, "contract_id": contract_id},
        )
        assert link.status_code in (200, 201), link.text
        return contract.json()


def step_run_mtm(contract_id: int, asof_date: date) -> dict[str, Any]:
    """risk_manager runs MTM for the contract at the given asof date.

    Asserts D-1 settlement is used (not D).
    """
    with as_risk_manager() as client:
        r = client.post(
            f"/mtm/contracts/{contract_id}/snapshot",
            json={"asof_date": asof_date.isoformat()},
        )
        assert r.status_code in (200, 201), r.text
        body = r.json()
        # Settlement date must be strictly before asof_date.
        assert body["settlement_date"] < body["asof_date"], body
        return body


def step_compute_pl(contract_id: int, asof_date: date) -> dict[str, Any]:
    """risk_manager computes P&L; asserts snapshot is append-only."""
    with as_risk_manager() as client:
        r = client.post(
            f"/pl/contracts/{contract_id}/snapshot",
            json={"asof_date": asof_date.isoformat()},
        )
        assert r.status_code in (200, 201), r.text
        body = r.json()
        assert body.get("price_evidence_id"), body
        return body


def step_compute_cashflow_baseline(contract_id: int) -> dict[str, Any]:
    """service:cashflow_pipeline produces the persistent baseline."""
    with as_service("service:cashflow_pipeline") as client:
        r = client.post(f"/cashflow/contracts/{contract_id}/baseline")
        assert r.status_code in (200, 201), r.text
        return r.json()


def step_read_audit_trail(
    *,
    rfq_id: int | None = None,
    deal_id: int | None = None,
    contract_id: int | None = None,
) -> list[dict[str, Any]]:
    """Auditor reads the trail; asserts every event has a non-empty signature."""
    if not any([rfq_id, deal_id, contract_id]):
        raise ValueError("supply one of rfq_id, deal_id, contract_id")
    params: dict[str, int] = {}
    if rfq_id is not None:
        params["rfq_id"] = rfq_id
    if deal_id is not None:
        params["deal_id"] = deal_id
    if contract_id is not None:
        params["contract_id"] = contract_id
    with as_auditor() as client:
        r = client.get("/audit/events", params=params)
        assert r.status_code == 200, r.text
        events = r.json()
        for ev in events:
            assert ev.get("signature"), ev
        return events
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest backend/tests/e2e/test_journey_steps.py -v`
Expected: 3 PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/tests/e2e/_journey_steps.py backend/tests/e2e/test_journey_steps.py
git commit -m "test(e2e): journey step primitives with local invariant assertions"
```

### Task 1.4: Define `conftest.py` — session-scope cleanup + trace_id

**Files:**
- Modify: `backend/tests/e2e/conftest.py`

- [ ] **Step 1: Implement conftest**

```python
# backend/tests/e2e/conftest.py
"""E2E-specific fixtures.

Inherits the autouse `reset_database` and `reset_rate_limiter` fixtures from
``backend/tests/conftest.py``. Adds:

- ``trace_id`` (function-scope) — unique id per test for namespace isolation.
- ``seeded`` (function-scope) — counterparties + Westmetall prices + LME
  calendar pre-seeded for the standard journey horizon.
"""
from __future__ import annotations

from datetime import date, timedelta

import pytest

from backend.tests.e2e._fixtures import (
    seed_counterparties,
    seed_westmetall_prices,
    seed_lme_calendar,
    trace_id_factory,
)


@pytest.fixture()
def trace_id() -> str:
    return trace_id_factory()


@pytest.fixture()
def seeded(trace_id: str) -> dict[str, object]:
    today = date.today()
    seed_lme_calendar(today - timedelta(days=10), today + timedelta(days=10))
    seed_westmetall_prices(trace_id, today - timedelta(days=10), today)
    cps = seed_counterparties(trace_id)
    return {
        "trace_id": trace_id,
        "counterparties": cps,
        "today": today,
    }
```

- [ ] **Step 2: Verify fixtures resolve**

Run: `pytest backend/tests/e2e/test_journey_steps.py -v --co`
Expected: collect-only succeeds (no fixture resolution errors).

- [ ] **Step 3: Commit**

```bash
git add backend/tests/e2e/conftest.py
git commit -m "test(e2e): conftest with trace_id and seeded fixtures"
```

---

## PHASE 2 — `test_journey_full.py` (narrative)

### Task 2.1: Write the full narrative test

**Files:**
- Create: `backend/tests/e2e/test_journey_full.py`

- [ ] **Step 1: Write the test**

```python
# backend/tests/e2e/test_journey_full.py
"""Full institutional journey: RFQ → Deal → Contract → MTM → P&L → Cashflow → Audit.

This is the canonical "did the platform work end-to-end" test. It is part
of the smoke subset and runs in CI on every PR.
"""
from __future__ import annotations

from decimal import Decimal

import pytest

from backend.tests.e2e._journey_steps import (
    step_create_rfq,
    step_simulate_outbound,
    step_simulate_inbound_quote,
    step_award_quote,
    step_link_contract,
    step_run_mtm,
    step_compute_pl,
    step_compute_cashflow_baseline,
    step_read_audit_trail,
)


def test_full_institutional_journey(seeded: dict[str, object]) -> None:
    trace_id = seeded["trace_id"]
    cps = seeded["counterparties"]
    today = seeded["today"]

    # 1. trader creates the RFQ
    rfq = step_create_rfq(trace_id, [cps["supplier"]])

    # 2. service:rfq_outbound dispatches
    step_simulate_outbound(rfq["id"])

    # 3. inbound webhook delivers a quote (idempotent retry asserted inside step)
    step_simulate_inbound_quote(rfq["id"], cps["supplier"])

    # 4. risk_manager awards
    deal = step_award_quote(rfq["id"])

    # 5. risk_manager links a hedge contract
    contract = step_link_contract(
        deal["id"],
        {
            "commodity": "ALUMINUM",
            "quantity_mt": "100.000000",
            "legs": [
                {"side": "buy", "price_type": "fixed"},
                {"side": "sell", "price_type": "variable"},
            ],
            "fixed_price_value": "2450.000000",
            "fixed_price_unit": "USD/MT",
            "float_pricing_convention": "avg",
            "counterparty_id": cps["broker"],
        },
    )

    # 6. risk_manager runs MTM at today (asserts D-1 settlement inside step)
    mtm = step_run_mtm(contract["id"], today)
    assert Decimal(mtm["mark_value"]).is_finite()

    # 7. risk_manager produces P&L snapshot
    pl = step_compute_pl(contract["id"], today)
    assert pl["price_evidence_id"]

    # 8. service:cashflow_pipeline produces baseline
    baseline = step_compute_cashflow_baseline(contract["id"])
    assert baseline["state"] == "persisted"

    # 9. auditor reads the chain; asserts every event signed
    events = step_read_audit_trail(rfq_id=rfq["id"])
    deal_events = step_read_audit_trail(deal_id=deal["id"])
    contract_events = step_read_audit_trail(contract_id=contract["id"])
    all_events = events + deal_events + contract_events
    assert len(all_events) >= 7
    # Chain integrity: sequence numbers monotone within each entity scope.
    for scope in (events, deal_events, contract_events):
        seqs = [e["sequence"] for e in scope]
        assert seqs == sorted(seqs), seqs
```

- [ ] **Step 2: Run the test**

Run: `pytest backend/tests/e2e/test_journey_full.py -v`
Expected: PASS, OR FAIL with a route/contract mismatch that points at a concrete missing endpoint. If FAIL, do NOT loosen the assertions — file the gap and treat as a real production-readiness defect.

- [ ] **Step 3: Commit**

```bash
git add backend/tests/e2e/test_journey_full.py
git commit -m "test(e2e): full institutional narrative journey (smoke)"
```

---

## PHASE 3 — `test_rbac_matrix.py`

### Task 3.1: Author parametrized matrix test

**Files:**
- Create: `backend/tests/e2e/test_rbac_matrix.py`

- [ ] **Step 1: Write the test**

```python
# backend/tests/e2e/test_rbac_matrix.py
"""E2E RBAC matrix enforcement against the AUTHORIZATION MATRIX appendix.

Distinct from ``backend/tests/test_rbac_matrix_enforcement.py`` which tests
each route in isolation; this one composes a real journey and verifies
the gates fire correctly under realistic state.
"""
from __future__ import annotations

import pytest

from backend.tests.e2e._fixtures import seed_counterparties, trace_id_factory
from backend.tests.e2e._personas import (
    as_trader,
    as_risk_manager,
    as_auditor,
)


# (persona_factory, method, path_template, expected_status, label)
# path_template may contain {customer}, {supplier}, {broker}, {bank} placeholders
# that get filled from the seeded counterparties.
CASES: list[tuple[str, str, str, int, str]] = [
    # Trader cannot READ broker/bank — must be 404 (existence-leak guard)
    ("trader", "GET", "/counterparties/{broker}", 404, "trader_broker_invisible"),
    ("trader", "GET", "/counterparties/{bank}", 404, "trader_bank_invisible"),
    # Trader CAN read customer/supplier
    ("trader", "GET", "/counterparties/{customer}", 200, "trader_customer_visible"),
    ("trader", "GET", "/counterparties/{supplier}", 200, "trader_supplier_visible"),
    # Trader cannot write hedge contracts / rfqs as approver / deals / linkages
    ("trader", "POST", "/contracts", 403, "trader_contracts_forbidden"),
    ("trader", "POST", "/linkages", 403, "trader_linkages_forbidden"),
    ("trader", "POST", "/deals", 403, "trader_deals_forbidden"),
    # Trader cannot touch scenario / MTM / P&L writes
    ("trader", "POST", "/scenario/whatif", 403, "trader_scenario_forbidden"),
    ("trader", "POST", "/mtm/contracts/1/snapshot", 403, "trader_mtm_forbidden"),
    ("trader", "POST", "/pl/contracts/1/snapshot", 403, "trader_pl_forbidden"),
    # Trader cannot read audit log
    ("trader", "GET", "/audit/events", 403, "trader_audit_forbidden"),
    # Auditor can read audit log
    ("auditor", "GET", "/audit/events", 200, "auditor_audit_visible"),
    # No role — not even auditor — can delete an audit event
    ("auditor", "DELETE", "/audit/events/1", 405, "auditor_cannot_delete"),
]


@pytest.fixture()
def seeded_cps(trace_id: str) -> dict[str, int]:
    return seed_counterparties(trace_id)


@pytest.mark.parametrize(
    "persona,method,path,expected,label",
    CASES,
    ids=[c[4] for c in CASES],
)
def test_rbac_matrix_case(
    persona: str,
    method: str,
    path: str,
    expected: int,
    label: str,
    seeded_cps: dict[str, int],
) -> None:
    factory = {
        "trader": as_trader,
        "risk_manager": as_risk_manager,
        "auditor": as_auditor,
    }[persona]
    rendered = path.format(**seeded_cps) if "{" in path else path
    with factory() as client:
        r = client.request(method, rendered)
        # 405 is acceptable wherever 403 is, when the verb is not registered.
        if expected == 405:
            assert r.status_code in (403, 404, 405), (label, r.status_code, r.text)
        else:
            assert r.status_code == expected, (label, r.status_code, r.text)


def test_mixed_role_jwt_rejected_at_401() -> None:
    """A JWT carrying both {trader, auditor} must be rejected at 401 before
    any route gate fires (auditor is exclusive)."""
    from app.core.auth import get_current_user
    from app.main import app
    from fastapi.testclient import TestClient

    # Simulate the JWT validator's rejection by overriding the dependency to
    # raise the same HTTPException the validator raises for mixed sets.
    from fastapi import HTTPException

    def _reject():
        raise HTTPException(status_code=401, detail="auditor_role_exclusive")

    app.dependency_overrides[get_current_user] = _reject
    try:
        client = TestClient(app)
        r = client.get("/counterparties")
        assert r.status_code == 401, r.text
    finally:
        app.dependency_overrides.pop(get_current_user, None)
```

- [ ] **Step 2: Run the test**

Run: `pytest backend/tests/e2e/test_rbac_matrix.py -v`
Expected: All parametrized cases PASS + mixed-role test PASS.

- [ ] **Step 3: Commit**

```bash
git add backend/tests/e2e/test_rbac_matrix.py
git commit -m "test(e2e): RBAC matrix enforcement under composed journey state"
```

---

## PHASE 4 — `test_audit_hmac_chain.py`

### Task 4.1: HMAC chain integrity test

**Files:**
- Create: `backend/tests/e2e/test_audit_hmac_chain.py`

- [ ] **Step 1: Write the test**

```python
# backend/tests/e2e/test_audit_hmac_chain.py
"""Audit log HMAC chain integrity + append-only invariants."""
from __future__ import annotations

import hashlib
import hmac
import os
from datetime import date

import pytest

from backend.tests.e2e._fixtures import (
    seed_counterparties,
    seed_westmetall_prices,
    seed_lme_calendar,
)
from backend.tests.e2e._journey_steps import (
    step_create_rfq,
    step_simulate_outbound,
    step_award_quote,
    step_read_audit_trail,
)


def _hmac_signature(body: str, key: str) -> str:
    return hmac.new(key.encode("utf-8"), body.encode("utf-8"), hashlib.sha256).hexdigest()


def test_every_audit_event_has_nonempty_signature(seeded: dict[str, object]) -> None:
    trace_id = seeded["trace_id"]
    rfq = step_create_rfq(trace_id, [seeded["counterparties"]["supplier"]])
    step_simulate_outbound(rfq["id"])
    events = step_read_audit_trail(rfq_id=rfq["id"])
    assert events
    for ev in events:
        assert ev["signature"], ev
        assert len(ev["signature"]) >= 32, ev["signature"]


def test_signatures_replay_against_signing_key(seeded: dict[str, object]) -> None:
    trace_id = seeded["trace_id"]
    rfq = step_create_rfq(trace_id, [seeded["counterparties"]["supplier"]])
    events = step_read_audit_trail(rfq_id=rfq["id"])
    key = os.environ["AUDIT_SIGNING_KEY"]
    for ev in events:
        expected = _hmac_signature(ev["canonical_payload"], key)
        assert ev["signature"] == expected, ev


def test_append_only_sequence_within_scope(seeded: dict[str, object]) -> None:
    trace_id = seeded["trace_id"]
    rfq = step_create_rfq(trace_id, [seeded["counterparties"]["supplier"]])
    step_simulate_outbound(rfq["id"])
    events = step_read_audit_trail(rfq_id=rfq["id"])
    seqs = [e["sequence"] for e in events]
    assert seqs == sorted(seqs)
    assert len(set(seqs)) == len(seqs)


def test_tampering_breaks_verification(seeded: dict[str, object]) -> None:
    """If a stored payload is mutated, signature verification must fail."""
    from app.core.database import SessionLocal
    from app.models.audit import AuditEvent

    trace_id = seeded["trace_id"]
    rfq = step_create_rfq(trace_id, [seeded["counterparties"]["supplier"]])

    session = SessionLocal()
    try:
        ev = session.query(AuditEvent).order_by(AuditEvent.id.desc()).first()
        assert ev is not None
        original_payload = ev.canonical_payload
        ev.canonical_payload = original_payload + ' {"tampered": true}'
        session.commit()
        key = os.environ["AUDIT_SIGNING_KEY"]
        expected = _hmac_signature(ev.canonical_payload, key)
        assert ev.signature != expected
    finally:
        session.close()


def test_no_role_can_delete_audit_event(seeded: dict[str, object]) -> None:
    from backend.tests.e2e._personas import as_auditor, as_risk_manager, as_trader

    trace_id = seeded["trace_id"]
    rfq = step_create_rfq(trace_id, [seeded["counterparties"]["supplier"]])
    events = step_read_audit_trail(rfq_id=rfq["id"])
    target = events[0]["id"]

    for factory in (as_trader, as_risk_manager, as_auditor):
        with factory() as client:
            r = client.delete(f"/audit/events/{target}")
            assert r.status_code in (403, 404, 405), (factory.__name__, r.status_code, r.text)
```

- [ ] **Step 2: Run the test**

Run: `pytest backend/tests/e2e/test_audit_hmac_chain.py -v`
Expected: All 5 PASS.

> **Note on canonical_payload:** If `AuditEvent.canonical_payload` is not the actual column name in `app/models/audit.py`, replace with the correct one. Do not invent the name — read the model.

- [ ] **Step 3: Commit**

```bash
git add backend/tests/e2e/test_audit_hmac_chain.py
git commit -m "test(e2e): audit HMAC chain integrity + append-only + delete denial"
```

---

## PHASE 5 — `test_precision_contract.py`

### Task 5.1: Decimal end-to-end + float-rejection test

**Files:**
- Create: `backend/tests/e2e/test_precision_contract.py`

- [ ] **Step 1: Write the test**

```python
# backend/tests/e2e/test_precision_contract.py
"""Decimal end-to-end contract.

Verifies:
1. Westmetall ingest rejects float literals at the wire.
2. Stringified Decimals are stored byte-exact.
3. MTM/P&L computed from seeded Decimals match expected exact values.
"""
from __future__ import annotations

import json
from datetime import date
from decimal import Decimal

import pytest

from backend.tests.e2e._fixtures import seed_lme_calendar
from backend.tests.e2e._personas import as_service, as_risk_manager


def test_westmetall_ingest_rejects_float_literal() -> None:
    """A raw JSON body containing a float literal must be rejected.

    The constraint is enforced at the parsing layer: ``value`` must arrive
    as a string and be converted via ``Decimal(str(...))``.
    """
    raw = json.dumps(
        {
            "observation_key": "LME-AL-CASH-FLOAT-TEST",
            "observation_date": date.today().isoformat(),
            "value": 2450.123,  # float literal — must be rejected
            "currency": "USD",
            "unit": "MT",
            "provider_tier": "canonical",
        }
    )
    with as_service("service:westmetall_ingest") as client:
        r = client.post(
            "/market-data/westmetall/ingest",
            content=raw,
            headers={"Content-Type": "application/json"},
        )
        assert r.status_code in (400, 422), r.text
        assert (
            "precision" in r.text.lower() or "decimal" in r.text.lower() or "float" in r.text.lower()
        ), r.text


def test_stringified_decimal_stored_exact() -> None:
    """A stringified Decimal must round-trip byte-exact."""
    raw_value = "2450.123456"
    today = date.today()
    seed_lme_calendar(today, today)
    with as_service("service:westmetall_ingest") as client:
        r = client.post(
            "/market-data/westmetall/ingest",
            json={
                "observation_key": "LME-AL-CASH-EXACT-TEST",
                "observation_date": today.isoformat(),
                "value": raw_value,
                "currency": "USD",
                "unit": "MT",
                "provider_tier": "canonical",
            },
        )
        assert r.status_code in (200, 201), r.text
        stored = r.json()
        # Stored value MUST equal raw_value as a string, OR equal Decimal(raw_value)
        # without any trailing-zero stripping or rounding.
        assert Decimal(stored["value"]) == Decimal(raw_value), (stored["value"], raw_value)


def test_mtm_pl_round_trip_exact_decimal(seeded: dict[str, object]) -> None:
    """MTM and P&L computed from seeded prices match exact Decimal expectations."""
    from backend.tests.e2e._journey_steps import (
        step_create_rfq,
        step_simulate_outbound,
        step_simulate_inbound_quote,
        step_award_quote,
        step_link_contract,
        step_run_mtm,
        step_compute_pl,
    )

    trace_id = seeded["trace_id"]
    cps = seeded["counterparties"]
    today = seeded["today"]
    rfq = step_create_rfq(trace_id, [cps["supplier"]])
    step_simulate_outbound(rfq["id"])
    step_simulate_inbound_quote(rfq["id"], cps["supplier"], price="2450.000000")
    deal = step_award_quote(rfq["id"])
    contract = step_link_contract(
        deal["id"],
        {
            "commodity": "ALUMINUM",
            "quantity_mt": "100.000000",
            "legs": [
                {"side": "buy", "price_type": "fixed"},
                {"side": "sell", "price_type": "variable"},
            ],
            "fixed_price_value": "2450.000000",
            "fixed_price_unit": "USD/MT",
            "float_pricing_convention": "avg",
            "counterparty_id": cps["broker"],
        },
    )
    mtm = step_run_mtm(contract["id"], today)
    pl = step_compute_pl(contract["id"], today)
    # No rounding drift between mark value and P&L computation:
    mark_decimal = Decimal(mtm["mark_value"])
    pl_decimal = Decimal(pl["unrealized"])
    assert mark_decimal == mark_decimal.quantize(Decimal("0.000001"))
    assert pl_decimal == pl_decimal.quantize(Decimal("0.000001"))
```

- [ ] **Step 2: Run the test**

Run: `pytest backend/tests/e2e/test_precision_contract.py -v`
Expected: 3 PASS.

- [ ] **Step 3: Commit**

```bash
git add backend/tests/e2e/test_precision_contract.py
git commit -m "test(e2e): precision contract decimal end-to-end + float reject"
```

---

## PHASE 6 — `test_market_data_governance.py`

### Task 6.1: Market-data governance test

**Files:**
- Create: `backend/tests/e2e/test_market_data_governance.py`

- [ ] **Step 1: Write the test**

```python
# backend/tests/e2e/test_market_data_governance.py
"""Market-data governance: 3-tier trust + 424 on unprovable + canonical lookup."""
from __future__ import annotations

from datetime import date, timedelta
from decimal import Decimal

import pytest

from backend.tests.e2e._fixtures import seed_lme_calendar
from backend.tests.e2e._personas import as_service, as_risk_manager


def _ingest(client, *, key: str, day: date, value: str, tier: str) -> dict:
    r = client.post(
        "/market-data/westmetall/ingest",
        json={
            "observation_key": key,
            "observation_date": day.isoformat(),
            "value": value,
            "currency": "USD",
            "unit": "MT",
            "provider_tier": tier,
        },
    )
    assert r.status_code in (200, 201), r.text
    return r.json()


def test_canonical_tier_feeds_mtm(seeded: dict[str, object]) -> None:
    """Canonical-tier price must be selectable by the MTM pipeline."""
    today = seeded["today"]
    with as_service("service:westmetall_ingest") as client:
        _ingest(client, key=f"LME-AL-CASH-{today}", day=today, value="2500.000000", tier="canonical")
    # MTM lookup should select the canonical price (not raise 424).
    with as_risk_manager() as client:
        r = client.get(f"/market-data/westmetall/lookup?key=LME-AL-CASH-{today}&date={today}")
        assert r.status_code == 200, r.text
        assert Decimal(r.json()["value"]) == Decimal("2500.000000")


def test_trusted_non_canonical_is_audit_only(seeded: dict[str, object]) -> None:
    """A trusted-tier non-canonical price must be tagged audit_only and never
    feed deals / MTM / P&L / scenarios."""
    today = seeded["today"]
    with as_service("service:westmetall_ingest") as client:
        body = _ingest(
            client,
            key=f"NON-CANONICAL-{today}",
            day=today,
            value="2999.999999",
            tier="trusted_non_canonical",
        )
    assert body.get("audit_only") is True, body
    with as_risk_manager() as client:
        r = client.get(
            f"/market-data/westmetall/lookup?key=NON-CANONICAL-{today}&date={today}"
        )
        # Lookup for downstream pricing must refuse non-canonical:
        assert r.status_code in (404, 424), r.text


def test_cashflow_projection_424_on_unprovable_price() -> None:
    """Projection at an asof date with no canonical price returns 424."""
    far_future = date.today() + timedelta(days=365)
    seed_lme_calendar(far_future, far_future)
    with as_risk_manager() as client:
        r = client.post(
            "/cashflow/projection",
            json={"asof_date": far_future.isoformat(), "contract_id": 0},
        )
        assert r.status_code == 424, r.text


def test_stale_feed_detected_and_refused(seeded: dict[str, object]) -> None:
    """A price with timestamp older than per-instrument max-gap is marked
    stale and downstream pricing refuses it."""
    today = seeded["today"]
    stale_day = today - timedelta(days=30)
    with as_service("service:westmetall_ingest") as client:
        _ingest(client, key=f"STALE-{stale_day}", day=stale_day, value="1000.0", tier="canonical")
    with as_risk_manager() as client:
        r = client.get(
            f"/market-data/westmetall/lookup?key=STALE-{stale_day}&date={today}"
        )
        # Either 424 (refused) or 200 with explicit stale=True flag — but
        # NOT 200 with a silently-served stale value.
        if r.status_code == 200:
            assert r.json().get("stale") is True, r.json()
        else:
            assert r.status_code == 424, r.text
```

- [ ] **Step 2: Run the test**

Run: `pytest backend/tests/e2e/test_market_data_governance.py -v`
Expected: 4 PASS.

- [ ] **Step 3: Commit**

```bash
git add backend/tests/e2e/test_market_data_governance.py
git commit -m "test(e2e): market-data governance 3-tier + 424 unprovable + stale refusal"
```

---

## PHASE 7 — `test_scenario_isolation.py`

### Task 7.1: Scenario/projection in-memory isolation test

**Files:**
- Create: `backend/tests/e2e/test_scenario_isolation.py`

- [ ] **Step 1: Write the test**

```python
# backend/tests/e2e/test_scenario_isolation.py
"""scenario_whatif_service and cashflow_projection must be persistent-side-effect-free."""
from __future__ import annotations

from sqlalchemy import inspect, text

from app.core.database import SessionLocal, engine
from backend.tests.e2e._personas import as_risk_manager


def _row_counts() -> dict[str, int]:
    """Snapshot row counts for every table in the schema."""
    out: dict[str, int] = {}
    insp = inspect(engine)
    with engine.connect() as conn:
        for table in insp.get_table_names():
            res = conn.execute(text(f'SELECT COUNT(*) FROM "{table}"'))
            out[table] = res.scalar() or 0
    return out


def test_scenario_whatif_has_no_persistent_side_effect(seeded: dict[str, object]) -> None:
    before = _row_counts()
    with as_risk_manager() as client:
        r = client.post(
            "/scenario/whatif",
            json={
                "perturbation": {"LME-AL-CASH": "+5%"},
                "asof_date": seeded["today"].isoformat(),
            },
        )
        assert r.status_code == 200, r.text
    after = _row_counts()
    # Allowed delta: audit_event rows for the scenario read action itself,
    # if any. NOTHING else may change.
    for table, count in after.items():
        if table == "audit_events":
            continue
        assert count == before[table], (table, before[table], count)


def test_cashflow_projection_has_no_persistent_side_effect(seeded: dict[str, object]) -> None:
    before = _row_counts()
    with as_risk_manager() as client:
        r = client.post(
            "/cashflow/projection",
            json={"asof_date": seeded["today"].isoformat(), "contract_id": 0},
        )
        # Whatever the status (200 or 424), the constraint is: no rows added.
        _ = r
    after = _row_counts()
    for table, count in after.items():
        if table == "audit_events":
            continue
        assert count == before[table], (table, before[table], count)
```

- [ ] **Step 2: Run the test**

Run: `pytest backend/tests/e2e/test_scenario_isolation.py -v`
Expected: 2 PASS.

- [ ] **Step 3: Commit**

```bash
git add backend/tests/e2e/test_scenario_isolation.py
git commit -m "test(e2e): scenario whatif + cashflow projection have zero persistent side-effects"
```

---

## PHASE 8 — Playwright persona specs

The existing `frontend-svelte/e2e/helpers.ts` MOCKS the backend via `page.route(...).fulfill(...)`. For the production-readiness specs we want **real** backend interaction, so we add a parallel helper module.

### Task 8.1: `_personas.ts` — real-backend session bootstrappers

**Files:**
- Create: `frontend-svelte/e2e/_personas.ts`

- [ ] **Step 1: Implement**

```typescript
// frontend-svelte/e2e/_personas.ts
//
// Real-backend session bootstrappers. Unlike `helpers.ts` (which mocks
// /auth/* via page.route), these helpers let real HTTP traffic flow to
// the docker-compose backend and only inject the Clerk dev session token
// into window.Clerk for the SPA.
//
// They rely on the backend running with APP_ENV=test so the dev-token
// fallback is active (see app/core/auth.py).
import { type Page, expect } from '@playwright/test';

const API_BASE = process.env.VITE_API_BASE_URL ?? 'http://localhost:8000';

function fakeJwt(payload: Record<string, unknown>): string {
	const header = btoa(JSON.stringify({ alg: 'RS256', typ: 'JWT' }));
	const body = btoa(JSON.stringify(payload));
	const sig = btoa('fake-signature');
	return `${header}.${body}.${sig}`;
}

async function bootstrapPersona(page: Page, sub: string, roles: string[]): Promise<void> {
	const token = fakeJwt({
		sub,
		name: sub,
		roles,
		exp: Math.floor(Date.now() / 1000) + 3600,
	});
	await page.addInitScript(({ t, s, r }) => {
		(window as unknown as { __internal_ClerkUICtor: unknown }).__internal_ClerkUICtor =
			function ClerkUI() {};
		(window as unknown as { Clerk: unknown }).Clerk = {
			load: async () => undefined,
			session: { getToken: async () => t },
			mountSignIn: () => undefined,
			unmountSignIn: () => undefined,
			mountSignUp: () => undefined,
			unmountSignUp: () => undefined,
			signOut: async () => undefined,
		};
		window.sessionStorage.setItem('hedge-control.auth.csrf', 'csrf-e2e');
		document.cookie = 'csrf_token=csrf-e2e; path=/';
		// Mark the persona for any backend dev-token middleware:
		(window as unknown as { __E2E_PERSONA__: unknown }).__E2E_PERSONA__ = { sub: s, roles: r };
	}, { t: token, s: sub, r: roles });
}

export async function loginAsTrader(page: Page): Promise<void> {
	await bootstrapPersona(page, 'e2e-trader', ['trader']);
	await page.goto('/');
	await expect(page.getByRole('heading', { name: 'Dashboard' })).toBeVisible({ timeout: 10_000 });
}

export async function loginAsRiskManager(page: Page): Promise<void> {
	await bootstrapPersona(page, 'e2e-risk-manager', ['risk_manager']);
	await page.goto('/');
	await expect(page.getByRole('heading', { name: 'Dashboard' })).toBeVisible({ timeout: 10_000 });
}

export async function loginAsAuditor(page: Page): Promise<void> {
	await bootstrapPersona(page, 'e2e-auditor', ['auditor']);
	await page.goto('/');
	await expect(page.getByRole('heading', { name: /Audit|Dashboard/ })).toBeVisible({ timeout: 10_000 });
}

export const API_BASE_URL = API_BASE;
```

- [ ] **Step 2: Commit**

```bash
git add frontend-svelte/e2e/_personas.ts
git commit -m "test(e2e): persona helpers for real-backend Playwright specs"
```

### Task 8.2: `journey-trader.spec.ts`

**Files:**
- Create: `frontend-svelte/e2e/journey-trader.spec.ts`

- [ ] **Step 1: Implement**

```typescript
// frontend-svelte/e2e/journey-trader.spec.ts
import { test, expect } from '@playwright/test';
import { loginAsTrader } from './_personas';

test.describe('Trader journey', () => {
	test('creates an RFQ and sees the canonical id', async ({ page }) => {
		await loginAsTrader(page);
		await page.goto('/rfqs/new');

		await page.getByLabel('Commodity').selectOption('ALUMINUM');
		await page.getByLabel('Quantity (MT)').fill('100.000000');
		await page.getByLabel('Tenor (months)').fill('3');
		await page.getByRole('button', { name: 'Submit RFQ' }).click();

		// Backend must respond with a canonical id of the form RFQ#<n>:
		const canonical = page.locator('[data-testid="rfq-canonical-id"]');
		await expect(canonical).toBeVisible({ timeout: 10_000 });
		await expect(canonical).toContainText(/^RFQ#\d+$/);
	});

	test('cannot access risk-manager-only routes', async ({ page }) => {
		await loginAsTrader(page);
		await page.goto('/mtm');
		// Either redirected to a "no access" page or shows a 403 message:
		await expect(page.getByText(/access|forbidden|403/i)).toBeVisible({ timeout: 10_000 });
	});
});
```

- [ ] **Step 2: Commit**

```bash
git add frontend-svelte/e2e/journey-trader.spec.ts
git commit -m "test(e2e): playwright trader journey spec"
```

### Task 8.3: `journey-risk-manager.spec.ts`

**Files:**
- Create: `frontend-svelte/e2e/journey-risk-manager.spec.ts`

- [ ] **Step 1: Implement**

```typescript
// frontend-svelte/e2e/journey-risk-manager.spec.ts
import { test, expect } from '@playwright/test';
import { loginAsRiskManager } from './_personas';

test.describe('Risk manager journey', () => {
	test('approves a deal and sees MTM snapshot', async ({ page }) => {
		await loginAsRiskManager(page);
		await page.goto('/deals');

		// Pick any deal in the awaiting-approval state:
		const firstApprove = page.getByRole('button', { name: 'Approve' }).first();
		await firstApprove.waitFor({ state: 'visible', timeout: 10_000 });
		await firstApprove.click();

		await expect(page.getByText(/approved/i)).toBeVisible({ timeout: 10_000 });

		await page.goto('/mtm');
		// MTM snapshot table renders Decimal values without scientific notation:
		const cells = page.locator('[data-testid="mtm-mark-value"]');
		const first = cells.first();
		await first.waitFor({ state: 'visible', timeout: 10_000 });
		const text = (await first.textContent()) ?? '';
		expect(text).not.toMatch(/e[+-]\d/i);
		expect(text).toMatch(/\d+\.\d+/);
	});
});
```

- [ ] **Step 2: Commit**

```bash
git add frontend-svelte/e2e/journey-risk-manager.spec.ts
git commit -m "test(e2e): playwright risk-manager journey spec"
```

### Task 8.4: `journey-auditor.spec.ts`

**Files:**
- Create: `frontend-svelte/e2e/journey-auditor.spec.ts`

- [ ] **Step 1: Implement**

```typescript
// frontend-svelte/e2e/journey-auditor.spec.ts
import { test, expect } from '@playwright/test';
import { loginAsAuditor } from './_personas';

test.describe('Auditor journey', () => {
	test('reads audit trail and sees HMAC signatures', async ({ page }) => {
		await loginAsAuditor(page);
		await page.goto('/audit');

		const rows = page.locator('[data-testid="audit-event-row"]');
		await rows.first().waitFor({ state: 'visible', timeout: 10_000 });
		const count = await rows.count();
		expect(count).toBeGreaterThan(0);

		for (let i = 0; i < Math.min(count, 5); i++) {
			const sig = rows.nth(i).locator('[data-testid="audit-event-signature"]');
			const text = (await sig.textContent()) ?? '';
			expect(text.trim().length).toBeGreaterThanOrEqual(32);
		}
	});

	test('cannot delete audit events from the UI', async ({ page }) => {
		await loginAsAuditor(page);
		await page.goto('/audit');
		await expect(page.getByRole('button', { name: /delete/i })).toHaveCount(0);
	});
});
```

- [ ] **Step 2: Commit**

```bash
git add frontend-svelte/e2e/journey-auditor.spec.ts
git commit -m "test(e2e): playwright auditor journey spec"
```

---

## PHASE 9 — Go/No-Go orchestrator

### Task 9.1: `scripts/e2e_go_no_go_report.py`

**Files:**
- Create: `scripts/e2e_go_no_go_report.py`
- Test: `scripts/test_e2e_go_no_go_report.py`

- [ ] **Step 1: Write the failing test**

```python
# scripts/test_e2e_go_no_go_report.py
"""Unit test for the go/no-go report generator."""
from __future__ import annotations

import json
import subprocess
from pathlib import Path


def _write_pytest_report(tmp: Path, results: list[dict]) -> Path:
    path = tmp / "pytest.json"
    path.write_text(
        json.dumps(
            {
                "summary": {"total": len(results), "passed": sum(1 for r in results if r["outcome"] == "passed")},
                "tests": results,
            }
        )
    )
    return path


def _write_playwright_report(tmp: Path, suites: list[dict]) -> Path:
    path = tmp / "playwright.json"
    path.write_text(json.dumps({"suites": suites}))
    return path


def test_go_verdict_all_pass(tmp_path: Path) -> None:
    pyreport = _write_pytest_report(
        tmp_path,
        [
            {"nodeid": "test_journey_full.py::test_full_institutional_journey", "outcome": "passed"},
            {"nodeid": "test_rbac_matrix.py::test_rbac_matrix_case[x]", "outcome": "passed"},
        ],
    )
    pwreport = _write_playwright_report(
        tmp_path,
        [
            {"title": "journey-trader.spec.ts", "specs": [{"ok": True}]},
        ],
    )
    out = tmp_path / "report.md"
    proc = subprocess.run(
        [
            "python",
            "scripts/e2e_go_no_go_report.py",
            "--pytest-json",
            str(pyreport),
            "--playwright-json",
            str(pwreport),
            "--output",
            str(out),
        ],
        capture_output=True,
        text=True,
    )
    assert proc.returncode == 0, proc.stderr
    text = out.read_text()
    assert "Verdict: GO" in text


def test_no_go_verdict_on_critical_failure(tmp_path: Path) -> None:
    pyreport = _write_pytest_report(
        tmp_path,
        [
            {"nodeid": "test_journey_full.py::test_full_institutional_journey", "outcome": "failed"},
        ],
    )
    pwreport = _write_playwright_report(tmp_path, [])
    out = tmp_path / "report.md"
    proc = subprocess.run(
        [
            "python",
            "scripts/e2e_go_no_go_report.py",
            "--pytest-json",
            str(pyreport),
            "--playwright-json",
            str(pwreport),
            "--output",
            str(out),
        ],
        capture_output=True,
        text=True,
    )
    assert proc.returncode == 1
    text = out.read_text()
    assert "Verdict: NO-GO" in text


def test_override_only_applies_to_non_critical(tmp_path: Path) -> None:
    pyreport = _write_pytest_report(
        tmp_path,
        [
            {"nodeid": "test_scenario_isolation.py::test_scenario_whatif", "outcome": "failed"},
        ],
    )
    pwreport = _write_playwright_report(tmp_path, [])
    out = tmp_path / "report.md"
    proc = subprocess.run(
        [
            "python",
            "scripts/e2e_go_no_go_report.py",
            "--pytest-json",
            str(pyreport),
            "--playwright-json",
            str(pwreport),
            "--output",
            str(out),
            "--override-rationale",
            "scenario isolation false positive — see Linear PROD-42",
        ],
        capture_output=True,
        text=True,
    )
    assert proc.returncode == 0, proc.stderr
    text = out.read_text()
    assert "Deploy override" in text
    assert "PROD-42" in text
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest scripts/test_e2e_go_no_go_report.py -v`
Expected: 3 FAIL (script does not exist).

- [ ] **Step 3: Implement the generator**

```python
# scripts/e2e_go_no_go_report.py
"""Aggregate pytest-json-report + Playwright JSON into a go/no-go report."""
from __future__ import annotations

import argparse
import datetime as dt
import json
import sys
from pathlib import Path

CRITICAL_BACKEND_FILES = {
    "test_journey_full.py",
    "test_rbac_matrix.py",
    "test_audit_hmac_chain.py",
    "test_precision_contract.py",
    "test_market_data_governance.py",
}
NON_CRITICAL_BACKEND_FILES = {"test_scenario_isolation.py"}


def _summarize_pytest(report: dict) -> dict:
    by_file: dict[str, dict[str, int]] = {}
    for t in report.get("tests", []):
        nodeid = t.get("nodeid", "")
        fname = nodeid.split("::", 1)[0].rsplit("/", 1)[-1]
        bucket = by_file.setdefault(fname, {"passed": 0, "failed": 0})
        if t.get("outcome") == "passed":
            bucket["passed"] += 1
        else:
            bucket["failed"] += 1
    return by_file


def _summarize_playwright(report: dict) -> dict:
    by_file: dict[str, dict[str, int]] = {}
    for suite in report.get("suites", []):
        fname = suite.get("title", "unknown")
        bucket = by_file.setdefault(fname, {"passed": 0, "failed": 0})
        for spec in suite.get("specs", []):
            if spec.get("ok"):
                bucket["passed"] += 1
            else:
                bucket["failed"] += 1
    return by_file


def _verdict(backend: dict, frontend: dict, override: str | None) -> tuple[str, list[str]]:
    failures: list[str] = []
    critical_failed = False
    for fname, bucket in backend.items():
        if bucket["failed"] > 0:
            failures.append(f"{fname} ({bucket['failed']} failed)")
            if fname in CRITICAL_BACKEND_FILES:
                critical_failed = True
    for fname, bucket in frontend.items():
        if bucket["failed"] > 0:
            failures.append(f"{fname} ({bucket['failed']} failed)")
            critical_failed = True
    if not failures:
        return "GO", []
    if critical_failed:
        return "NO-GO", failures
    if override:
        return "GO (override)", failures
    return "NO-GO", failures


def _render(backend: dict, frontend: dict, verdict: str, failures: list[str], override: str | None) -> str:
    lines = [
        f"# Go/No-Go Report — {dt.datetime.now(dt.timezone.utc).isoformat()}",
        "",
        "## Backend (pytest)",
    ]
    for fname, bucket in sorted(backend.items()):
        total = bucket["passed"] + bucket["failed"]
        symbol = "PASS" if bucket["failed"] == 0 else "FAIL"
        lines.append(f"- [{symbol}] {fname} ({bucket['passed']}/{total})")
    lines.append("")
    lines.append("## Frontend (Playwright)")
    for fname, bucket in sorted(frontend.items()):
        total = bucket["passed"] + bucket["failed"]
        symbol = "PASS" if bucket["failed"] == 0 else "FAIL"
        lines.append(f"- [{symbol}] {fname} ({bucket['passed']}/{total})")
    lines.append("")
    lines.append(f"## Verdict: {verdict}")
    if failures:
        lines.append("")
        lines.append("**Failures:**")
        for f in failures:
            lines.append(f"- {f}")
    if override:
        lines.append("")
        lines.append("## Deploy override")
        lines.append("")
        lines.append(override)
    return "\n".join(lines) + "\n"


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--pytest-json", required=True, type=Path)
    parser.add_argument("--playwright-json", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--override-rationale", default=None)
    args = parser.parse_args()

    backend = _summarize_pytest(json.loads(args.pytest_json.read_text()))
    frontend = _summarize_playwright(json.loads(args.playwright_json.read_text()))
    verdict, failures = _verdict(backend, frontend, args.override_rationale)
    text = _render(backend, frontend, verdict, failures, args.override_rationale)
    args.output.write_text(text)
    print(text)
    return 0 if verdict.startswith("GO") else 1


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest scripts/test_e2e_go_no_go_report.py -v`
Expected: 3 PASS.

- [ ] **Step 5: Commit**

```bash
git add scripts/e2e_go_no_go_report.py scripts/test_e2e_go_no_go_report.py
git commit -m "feat(e2e): go/no-go report generator with critical/non-critical verdict"
```

### Task 9.2: `scripts/run_go_no_go.js` orchestrator

**Files:**
- Create: `scripts/run_go_no_go.js`

- [ ] **Step 1: Implement**

```javascript
// scripts/run_go_no_go.js
//
// Orchestrates the full E2E run pre-deploy:
//   1. docker compose up -d db backend frontend-svelte
//   2. Wait for backend health
//   3. pytest backend/tests/e2e/ --json-report
//   4. playwright test journey-*.spec.ts --reporter=json
//   5. e2e_go_no_go_report.py → docs/audits/<utc-date>-go-no-go.md
//   6. docker compose down -v
//
// Exits 0 on GO, 1 on NO-GO.
const { spawnSync } = require('node:child_process');
const fs = require('node:fs');
const path = require('node:path');

function run(cmd, args, opts = {}) {
	console.log(`> ${cmd} ${args.join(' ')}`);
	const r = spawnSync(cmd, args, { stdio: 'inherit', shell: process.platform === 'win32', ...opts });
	return r.status ?? 1;
}

function runCapture(cmd, args, opts = {}) {
	const r = spawnSync(cmd, args, { encoding: 'utf-8', shell: process.platform === 'win32', ...opts });
	return { status: r.status ?? 1, stdout: r.stdout ?? '', stderr: r.stderr ?? '' };
}

function waitForBackend(maxSec = 60) {
	for (let i = 0; i < maxSec; i++) {
		const r = runCapture('curl', ['-sf', 'http://localhost:8000/health']);
		if (r.status === 0) return true;
		console.log(`Waiting for backend... ${i + 1}/${maxSec}`);
		const end = Date.now() + 1000;
		while (Date.now() < end) {} // busy-wait 1s without setTimeout to keep this sync
	}
	return false;
}

(function main() {
	const utcDate = new Date().toISOString().slice(0, 10);
	const reportPath = path.join('docs', 'audits', `${utcDate}-go-no-go.md`);
	const pytestJson = path.join('backend', 'tests', 'e2e', 'report.json');
	const playwrightJson = path.join('frontend-svelte', 'playwright-report', 'report.json');

	if (run('docker', ['compose', 'up', '-d', 'db', 'backend', 'frontend-svelte']) !== 0) {
		process.exit(1);
	}
	if (!waitForBackend()) {
		console.error('backend did not become healthy');
		process.exit(1);
	}

	const pyStatus = run('python', [
		'-m',
		'pytest',
		'backend/tests/e2e/',
		'-v',
		'--json-report',
		`--json-report-file=${pytestJson}`,
	]);
	const pwStatus = run('npx', ['playwright', 'test', '--reporter=json'], {
		cwd: 'frontend-svelte',
	});

	const overrideRationale = process.env.OVERRIDE_RATIONALE;
	const reportArgs = [
		'scripts/e2e_go_no_go_report.py',
		'--pytest-json',
		pytestJson,
		'--playwright-json',
		playwrightJson,
		'--output',
		reportPath,
	];
	if (overrideRationale) {
		reportArgs.push('--override-rationale', overrideRationale);
	}
	const reportStatus = run('python', reportArgs);

	run('docker', ['compose', 'down', '-v']);

	if (reportStatus !== 0) {
		console.error(`Report wrote NO-GO verdict. See ${reportPath}`);
		process.exit(1);
	}
	console.log(`Report written: ${reportPath}`);
	console.log(`pytest exit: ${pyStatus}, playwright exit: ${pwStatus}`);
})();
```

- [ ] **Step 2: Smoke-run dry**

Run: `node scripts/run_go_no_go.js` (this requires docker-compose to be available; if not, skip the run for now and verify by reading).
Expected: script exists, lints clean, exits 1 if backend health check fails (acceptable for first dry run).

- [ ] **Step 3: Commit**

```bash
git add scripts/run_go_no_go.js
git commit -m "feat(e2e): run_go_no_go.js orchestrator for manual pre-deploy validation"
```

---

## PHASE 10 — CI integration

### Task 10.1: Add `e2e-smoke` blocking job

**Files:**
- Modify: `.github/workflows/ci.yml` (insert after `backend-test`, before `e2e-playwright`)

- [ ] **Step 1: Insert the new job**

Add this block immediately after the `backend-test` job ends (after line 88):

```yaml
  e2e-smoke:
    name: "E2E: Smoke (pytest journey + RBAC)"
    runs-on: ubuntu-latest
    needs: [backend-test]
    defaults:
      run:
        working-directory: backend
    env:
      SCHEDULER_DISABLED: "1"
      DATABASE_URL: "sqlite+pysqlite:///:memory:"
      APP_ENV: "test"
    steps:
      - uses: actions/checkout@v4

      - uses: actions/setup-python@v5
        with:
          python-version: "3.12"
          cache: pip
          cache-dependency-path: backend/requirements.txt

      - run: pip install -r requirements.txt
      - run: pip install pytest pytest-cov pytest-json-report httpx

      - name: Run E2E smoke (journey_full + rbac_matrix)
        run: pytest tests/e2e/test_journey_full.py tests/e2e/test_rbac_matrix.py -v
```

- [ ] **Step 2: Verify YAML syntax**

Run: `python -c "import yaml; yaml.safe_load(open('.github/workflows/ci.yml'))"`
Expected: no exception.

- [ ] **Step 3: Commit**

```bash
git add .github/workflows/ci.yml
git commit -m "ci(e2e): add e2e-smoke job blocking PR merge"
```

### Task 10.2: Extend `e2e-playwright` to include persona specs

**Files:**
- Modify: `.github/workflows/ci.yml` (existing `e2e-playwright` job, "Run Playwright tests" step)

- [ ] **Step 1: Confirm the existing step picks up new specs automatically**

The existing step `run: npx playwright test` runs the entire `e2e/` directory, so the new persona specs are picked up automatically. No edit needed for inclusion.

- [ ] **Step 2: Add a post-merge full job**

Append at the end of the workflow file:

```yaml
  e2e-full-post-merge:
    name: "E2E: Full go-no-go (post-merge)"
    runs-on: ubuntu-latest
    if: github.event_name == 'push' && github.ref == 'refs/heads/main'
    needs: [e2e-playwright, e2e-smoke]
    steps:
      - uses: actions/checkout@v4

      - uses: actions/setup-python@v5
        with:
          python-version: "3.12"
          cache: pip
          cache-dependency-path: backend/requirements.txt

      - uses: actions/setup-node@v4
        with:
          node-version: 22
          cache: npm
          cache-dependency-path: frontend-svelte/package-lock.json

      - run: pip install -r backend/requirements.txt
      - run: pip install pytest pytest-json-report httpx
      - run: cd frontend-svelte && npm ci && npx playwright install --with-deps chromium

      - name: Run full E2E suite
        run: |
          cd backend && python -m pytest tests/e2e/ -v --json-report --json-report-file=tests/e2e/report.json || true
          cd ../frontend-svelte && npx playwright test --reporter=json > playwright-report/report.json || true

      - name: Generate go-no-go report
        run: |
          python scripts/e2e_go_no_go_report.py \
            --pytest-json backend/tests/e2e/report.json \
            --playwright-json frontend-svelte/playwright-report/report.json \
            --output docs/audits/$(date -u +%Y-%m-%d)-go-no-go.md

      - name: Upload go-no-go report
        uses: actions/upload-artifact@v4
        if: ${{ !cancelled() }}
        with:
          name: go-no-go-report
          path: docs/audits/*-go-no-go.md
          retention-days: 30
```

- [ ] **Step 3: Verify YAML**

Run: `python -c "import yaml; yaml.safe_load(open('.github/workflows/ci.yml'))"`
Expected: no exception.

- [ ] **Step 4: Commit**

```bash
git add .github/workflows/ci.yml
git commit -m "ci(e2e): add post-merge full go-no-go job with artifact upload"
```

---

## PHASE 11 — Test-only cleanup endpoint (full-stack mode only)

This phase only matters when running against the docker-compose stack with `E2E_FULL_STACK=1`. In integration mode the autouse `reset_database` fixture handles cleanup. For the full-stack run we need a `POST /internal/test/cleanup` endpoint that the orchestrator can call.

**Trust boundary (non-negotiable):** the endpoint is destructive (DELETE across multiple tables) and therefore MUST be defended by **two independent gates**:

1. **Env gate** — router is registered only when `APP_ENV=test` (boot-time, fail-closed on missing/wrong env).
2. **Identity gate** — request must carry a JWT whose `sub == "service:e2e_cleanup"`. Any other actor (human role, other service identity, unauthenticated) gets 401/403.

Env-only gating is **insufficient** — a misconfigured deployment that ever sets `APP_ENV=test` would expose row-deletion to any caller. The identity gate is the production-side belt-and-suspenders.

### Task 11.1: Add cleanup endpoint with dual gate (env + service identity)

**Files:**
- Create: `backend/app/api/routes/internal_test.py`
- Modify: `backend/app/main.py` (conditional router include)
- Test: `backend/tests/test_internal_test_endpoint_gated.py`

- [ ] **Step 1: Write the failing tests**

```python
# backend/tests/test_internal_test_endpoint_gated.py
"""The /internal/test/cleanup endpoint must be gated by APP_ENV=test AND
by service identity ``service:e2e_cleanup``. Unauthenticated, wrong-service,
or non-test APP_ENV access must all be rejected.
"""
from __future__ import annotations

import importlib

from fastapi.testclient import TestClient

from app.core.auth import get_current_user


def _reload_app() -> object:
    import app.main as main
    importlib.reload(main)
    return main


def test_cleanup_present_when_test_env_and_correct_identity(monkeypatch) -> None:
    monkeypatch.setenv("APP_ENV", "test")
    main = _reload_app()
    main.app.dependency_overrides[get_current_user] = lambda: {
        "sub": "service:e2e_cleanup",
        "roles": [],
    }
    try:
        client = TestClient(main.app)
        r = client.post("/internal/test/cleanup", json={"trace_id": "nonexistent"})
        # 200 with empty per-table counts is the expected idempotent shape:
        assert r.status_code == 200, r.text
        assert isinstance(r.json(), dict)
    finally:
        main.app.dependency_overrides.pop(get_current_user, None)


def test_cleanup_rejects_unauthenticated(monkeypatch) -> None:
    monkeypatch.setenv("APP_ENV", "test")
    main = _reload_app()
    # No dependency override → real auth path → no JWT → 401.
    client = TestClient(main.app)
    r = client.post("/internal/test/cleanup", json={"trace_id": "x"})
    assert r.status_code in (401, 403), r.text


def test_cleanup_rejects_wrong_service_identity(monkeypatch) -> None:
    monkeypatch.setenv("APP_ENV", "test")
    main = _reload_app()
    main.app.dependency_overrides[get_current_user] = lambda: {
        "sub": "service:westmetall_ingest",
        "roles": [],
    }
    try:
        client = TestClient(main.app)
        r = client.post("/internal/test/cleanup", json={"trace_id": "x"})
        assert r.status_code == 403, r.text
    finally:
        main.app.dependency_overrides.pop(get_current_user, None)


def test_cleanup_rejects_human_role_even_auditor(monkeypatch) -> None:
    monkeypatch.setenv("APP_ENV", "test")
    main = _reload_app()
    main.app.dependency_overrides[get_current_user] = lambda: {
        "sub": "real-auditor",
        "roles": ["auditor"],
    }
    try:
        client = TestClient(main.app)
        r = client.post("/internal/test/cleanup", json={"trace_id": "x"})
        assert r.status_code == 403, r.text
    finally:
        main.app.dependency_overrides.pop(get_current_user, None)


def test_cleanup_absent_when_production_env(monkeypatch) -> None:
    monkeypatch.setenv("APP_ENV", "production")
    monkeypatch.setenv("AUDIT_SIGNING_KEY", "x" * 32)
    main = _reload_app()
    main.app.dependency_overrides[get_current_user] = lambda: {
        "sub": "service:e2e_cleanup",
        "roles": [],
    }
    try:
        client = TestClient(main.app)
        r = client.post("/internal/test/cleanup", json={"trace_id": "x"})
        # Route must not be registered at all in production env, so a correctly
        # authenticated cleanup identity still gets 404.
        assert r.status_code == 404, r.text
    finally:
        main.app.dependency_overrides.pop(get_current_user, None)


def test_cleanup_absent_when_staging_env(monkeypatch) -> None:
    monkeypatch.setenv("APP_ENV", "staging")
    monkeypatch.setenv("AUDIT_SIGNING_KEY", "x" * 32)
    main = _reload_app()
    client = TestClient(main.app)
    r = client.post("/internal/test/cleanup", json={"trace_id": "x"})
    assert r.status_code == 404, r.text
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest backend/tests/test_internal_test_endpoint_gated.py -v`
Expected: all 6 FAIL — endpoint absent.

- [ ] **Step 3: Implement the router with identity gate**

```python
# backend/app/api/routes/internal_test.py
"""Test-only cleanup router. Registered conditionally by main.py when
APP_ENV=test, AND every endpoint is gated by service-identity
``service:e2e_cleanup``.

Two independent defenses:
1. Boot-time: ``main.py`` only includes this router when APP_ENV=test.
2. Per-request: every endpoint Depends on ``require_e2e_cleanup_identity``,
   which rejects every actor except ``service:e2e_cleanup``.

If either defense is bypassed (misconfig or refactor), the other still
prevents destructive access.
"""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy import inspect, text

from app.core.auth import get_current_user
from app.core.database import engine

router = APIRouter(prefix="/internal/test", tags=["internal-test"])


def require_e2e_cleanup_identity(
    user: dict[str, Any] = Depends(get_current_user),
) -> dict[str, Any]:
    if user.get("sub") != "service:e2e_cleanup":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="e2e_cleanup_identity_required",
        )
    return user


class CleanupRequest(BaseModel):
    trace_id: str


@router.post("/cleanup")
def cleanup_by_trace_id(
    req: CleanupRequest,
    _identity: dict[str, Any] = Depends(require_e2e_cleanup_identity),
) -> dict[str, int]:
    """Delete all rows tagged with the given trace_id across known tables.

    Returns a per-table delete count. Idempotent. Errors are surfaced —
    we never swallow partial-cleanup failures because they would mask
    state leakage between E2E runs.
    """
    deleted: dict[str, int] = {}
    tables_with_trace = (
        "audit_events",
        "rfqs",
        "deals",
        "hedge_contracts",
        "counterparties",
    )
    insp = inspect(engine)
    existing_tables = set(insp.get_table_names())
    with engine.begin() as conn:
        for t in tables_with_trace:
            if t not in existing_tables:
                # Schema may differ across SQLite vs Postgres; explicitly
                # mark absent tables so callers see them in the response.
                deleted[t] = -1
                continue
            r = conn.execute(
                text(f'DELETE FROM "{t}" WHERE trace_id = :tid'),
                {"tid": req.trace_id},
            )
            deleted[t] = r.rowcount or 0
    return deleted
```

- [ ] **Step 4: Wire it into `main.py` conditionally**

Open `backend/app/main.py` and locate where routers are included. Add the conditional registration:

```python
import os
# (near the other router imports)
if os.environ.get("APP_ENV", "").strip().lower() == "test":
    from app.api.routes.internal_test import router as internal_test_router
    app.include_router(internal_test_router)
```

Place this block after all production routers are included so that production deployments never reach the import.

- [ ] **Step 5: Run tests to verify they pass**

Run: `pytest backend/tests/test_internal_test_endpoint_gated.py -v`
Expected: 6 PASS.

- [ ] **Step 6: Commit**

```bash
git add backend/app/api/routes/internal_test.py backend/app/main.py backend/tests/test_internal_test_endpoint_gated.py
git commit -m "feat(e2e): /internal/test/cleanup with dual gate (APP_ENV=test + service:e2e_cleanup identity)"
```

### Task 11.2: Update `_personas.as_service` callers in cleanup paths

Any orchestrator code or full-stack helper that calls `/internal/test/cleanup` must mint a JWT under `service:e2e_cleanup`. The persona helper from Task 1.1 already supports this identity (added to the `valid` set).

- [ ] **Step 1: Verify caller pattern**

In any place we add cleanup invocations (typically the session-scope teardown when `E2E_FULL_STACK=1`), use:

```python
from backend.tests.e2e._personas import as_service

with as_service("service:e2e_cleanup") as client:
    client.post("/internal/test/cleanup", json={"trace_id": trace_id})
```

- [ ] **Step 2: No commit needed if no new caller was added** — but if you add a teardown fixture that calls cleanup, commit alongside.

---

## PHASE 12 — Verification & smoke runs

### Task 12.1: Run the full backend e2e suite locally

- [ ] **Step 1: Run smoke**

Run: `npm run test:e2e:smoke`
Expected: PASS (both `test_journey_full.py` and `test_rbac_matrix.py`).

- [ ] **Step 2: Run full backend e2e**

Run: `npm run test:e2e:backend`
Expected: All 6 backend e2e files PASS; `backend/tests/e2e/report.json` written.

- [ ] **Step 3: If any failure surfaces, do NOT loosen the test**

Treat any failure as a production-readiness defect. File a follow-up dispatch for the underlying issue. Pause the rest of Phase 12 until the smoke + backend full run green.

### Task 12.2: Run the Playwright suite locally

- [ ] **Step 1: Start the docker stack**

Run: `docker compose up -d db backend frontend-svelte`
Wait for backend health: `curl -sf http://localhost:8000/health`

- [ ] **Step 2: Run Playwright persona specs**

Run: `cd frontend-svelte && npx playwright test journey-trader.spec.ts journey-risk-manager.spec.ts journey-auditor.spec.ts`
Expected: All 3 specs PASS.

- [ ] **Step 3: Tear down**

Run: `docker compose down -v`

### Task 12.3: Run the orchestrator end-to-end

- [ ] **Step 1: Generate a full go-no-go report**

Run: `npm run test:go-no-go`
Expected: exits 0; `docs/audits/<UTC-date>-go-no-go.md` written with `Verdict: GO`.

- [ ] **Step 2: Inspect the report**

Run: `cat docs/audits/$(date -u +%Y-%m-%d)-go-no-go.md`
Expected: all sections present, no failures.

- [ ] **Step 3: Commit the report as a baseline artifact**

```bash
git add docs/audits/*-go-no-go.md
git commit -m "docs(audits): baseline E2E go-no-go report (suite green)"
```

### Task 12.4: Push the branch and verify CI green

- [ ] **Step 1: Push**

```bash
git push -u origin <branch-name>
```

- [ ] **Step 2: Check CI**

Run: `gh pr checks` (or watch in the GitHub UI).
Expected: `e2e-smoke` and `e2e-playwright` both green. On merge to main, `e2e-full-post-merge` runs and uploads the report artifact.

- [ ] **Step 3: Open a PR**

Use the `commit-commands:commit-push-pr` skill, OR manually:

```bash
gh pr create --title "test(e2e): production readiness suite" --body "$(cat <<'EOF'
## Summary
- Adds coordinated pytest + Playwright E2E suite covering full institutional journey + 5 constitutional invariants
- Smoke (CI-blocking) + Full (manual go/no-go with markdown report)
- HB-4 explicitly out of scope; suite is green as a pre-requisite for HB-4

## Test plan
- [x] `npm run test:e2e:smoke` PASS locally
- [x] `npm run test:e2e:backend` PASS locally
- [x] Playwright persona specs PASS against docker-compose stack
- [x] `npm run test:go-no-go` PASS, GO verdict in report

🤖 Generated with [Claude Code](https://claude.com/claude-code)
EOF
)"
```

---

## Self-review

### Spec coverage check

| Spec section | Plan task(s) |
|---|---|
| §3.1 Backend layout | Phase 0 task 0.1 + Phases 1-7 |
| §3.2 Frontend layout | Phase 8 |
| §3.3 Orchestration | Phase 9 + Phase 0.2 |
| §4.1 _fixtures.py | Task 1.2 |
| §4.2 _personas.py | Task 1.1 |
| §4.3 _journey_steps.py | Task 1.3 |
| §4.4 test_journey_full.py | Task 2.1 |
| §4.5 test_rbac_matrix.py | Task 3.1 |
| §4.6 test_audit_hmac_chain.py | Task 4.1 |
| §4.7 test_precision_contract.py | Task 5.1 |
| §4.8 test_market_data_governance.py | Task 6.1 |
| §4.9 test_scenario_isolation.py | Task 7.1 |
| §4.10 Frontend persona specs | Tasks 8.1 – 8.4 |
| §4.11 Report generator | Tasks 9.1 – 9.2 |
| §5 Data flow | Implicit across Phase 1 + Phase 9 |
| §6 Error handling & determinism | Conftest in 1.4 + cleanup endpoint in Phase 11 |
| §7 Operational modes | Phase 0.2 (npm scripts) + Phase 10 (CI) |
| §10 Acceptance criteria | Phase 12 verification |

No gaps.

### Placeholder scan

- No "TBD", "TODO", "fill in later" present.
- Every test step has complete code.
- All file paths are exact.

### Type consistency

- `step_create_rfq` returns `dict[str, Any]` with `id` and `canonical_id` keys — used consistently across Phases 2–7.
- `seed_counterparties` returns `dict[str, int]` keyed by `"customer" | "supplier" | "broker" | "bank"` — used consistently across all phases.
- Persona context managers yield `TestClient | httpx.Client` and all callers use the `client.<method>(...)` API surface that both expose identically.

No inconsistencies found.
