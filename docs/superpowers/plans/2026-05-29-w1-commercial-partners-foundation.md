# W1 — Commercial Partners Foundation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Stand up the `commercial_partners` domain (model + migration + service + routes + RBAC) separating commercial customers/suppliers from hedge brokers/banks, with the append-only `sanctions_screenings` / `sanctions_adjudications` tables created (no external calls yet), per governance W1.

**Architecture:** New `commercial_partners` table (kind ∈ {customer, supplier}, trader-owned) mirrors `counterparties` (hedge, risk_manager-owned) but carries the full commercial-KYC field set (sanctions status, LEI fields, kind-asymmetric Decimal credit/terms). A numbered Alembic migration (`049`) creates the three new tables + enums, migrates existing customer/supplier rows out of `counterparties` **reusing the same UUID** (so `orders.counterparty_id` stays valid), resets compliance state fail-closed, runs two pre-move HALT validations, repoints the `orders` FK, and restricts `counterparties` to hedge types. RBAC follows the AUTHORIZATION MATRIX. **No OpenSanctions / GLEIF calls in W1** — those are W2/W4; W1 only creates the tables and the gated-field invariants.

**Tech Stack:** FastAPI, SQLAlchemy 2.0 + Alembic, Pydantic v2, Python 3.11/3.12; pytest (SQLite-in-memory). Frontend types regenerated via `openapi-typescript`.

---

## Binding authority (read before coding)

`docs/governance.md` is the constitution — **reference it by section name, do not paraphrase it into code comments**. The W1-relevant sections (read them; line numbers drift):

- **AUTHORIZATION MATRIX** → trader / risk_manager / auditor role bullets, "Authorization invariants", "Service identities" (incl. `service:sanctions_screening`), and the commercial-partner mutation rules (POST forces `pending`; generic PATCH excludes `kyc_status` + credit/terms for ALL actors → 403; soft-delete; **identity-edit reset**).
- **"Hedge counterparty sanctions gate (binding)"** — gate field is `sanctions_status`; enum gains `unscreened`; **the W1 model makes `unscreened` the column default (NOT `clear`)**.
- **"Status transitions (binding)"** — commercial `kyc_status` is risk_manager-only; transition→`approved` is BLOCKED unless effective `sanctions_status == clear`; event `commercial_partner_kyc_status_changed` with payload `{commercial_partner_id, previous_status, new_status, transition_actor_sub, reason}` (reason min 8 chars).
- **"Sanctions screening governance"** + **"Adjudication"** — defines the immutable `sanctions_screenings` / `sanctions_adjudications` table shapes W1 must create (the *writing* of rows is W2).
- **"LEI validation governance"** — defines `lei_status` members + `lei_legal_name` / `lei_checked_at` columns (the GLEIF call is W4).
- **"Credit and terms governance"** — kind-asymmetric Decimal credit/terms; risk_manager-only; event `commercial_partner_credit_approved` with payload `{commercial_partner_id, kind, fields_changed, previous_values, new_values, approving_actor_sub}`.
- **"Schema (binding)"** — the migration contract (UUID reuse, fail-closed reset on BOTH domains, two pre-move HALT validations, FK repoint, restrict `counterparties` to {broker, bank_br}, ENUM lifecycle).

Design spec: `docs/superpowers/specs/2026-05-29-commercial-partners-kyc-separation-design.md` (§5 data model, §6 RBAC, §7 services, §8 routes, §10 testing, §11 waves). Handoff: `docs/superpowers/2026-05-29-W1-handoff.md`.

## Scope decisions (derived from governance — flagged for the executor)

These two items touch the **existing hedge domain**, not just additive commercial work. Both are mandated by governance and are therefore **in W1**:

1. **Hedge `sanctions_status` default flips `clear` → `unscreened`** (governance "Hedge counterparty sanctions gate": *"The W1 model adds the `unscreened` member as the column default (NOT `clear`)"*). Ripple is tiny: only `backend/tests/test_counterparty_crud.py:50` asserts the unspecified default. Fixed in Task 1.
2. **`counterparties` becomes strictly hedge-only** (governance Authorization invariants: *"The `counterparties` table holds ONLY hedge types after the W1 migration … trader simply has no hedge-counterparty access"*). The create route rejects `customer`/`supplier`; trader-only actors are fully invisible to the table. Three existing RBAC tests (`test_counterparty_post_type_gate`, `test_counterparty_patch_trader_accepts_customer`, `test_counterparty_get_list_trader_filters_broker_bank`) change accordingly. Done in Task 7.

**Out of W1** (do NOT implement here): OpenSanctions screening service, GLEIF LEI validation, the commercial order gate, RFQ gate re-target, HB-3 `risk_flags` re-align, the three external-call endpoints (`/screen`, `/validate-lei`, `/adjudicate-sanctions`), and frontend surfaces. The `/screen`, `/validate-lei`, `/adjudicate-sanctions` endpoints are **not even skeletoned** in W1 — they arrive with their services (W2/W3/W4) to avoid dead routes.

## What W1 does NOT do (anti-scope guards)

- No `OPENSANCTIONS_API_KEY` / `GLEIF` config, no boot validator (W2).
- No write path into `sanctions_screenings` / `sanctions_adjudications` (tables exist, no service writes them in W1).
- No change to `rfq_service.py` `assert_kyc_approved` call sites (W3).
- No drop of the vestigial `counterparties.kyc_status` column (later migration).

---

## File Structure

**Create:**
- `backend/app/models/commercial_partner.py` — `CommercialPartner` ORM model + `CommercialPartnerKind`, `LeiStatus` enums.
- `backend/app/models/sanctions.py` — `SanctionsScreening` + `SanctionsAdjudication` ORM models (append-only) + `SanctionsPartnerType`, `ScreeningResult`, `ScreeningStatus`, `AdjudicationDecision` enums.
- `backend/app/schemas/commercial_partner.py` — Pydantic Create/Update/Read/ListResponse + `CreditApprovalRequest`.
- `backend/app/services/commercial_partner_service.py` — `CommercialPartnerService`.
- `backend/app/api/routes/commercial_partners.py` — router.
- `backend/alembic/versions/049_commercial_partners_foundation.py` — migration.
- `backend/tests/test_049_migration_roundtrip.py` — migration tests.
- `backend/tests/test_commercial_partner_service.py` — service + precision unit tests.

**Modify:**
- `backend/app/models/counterparty.py` — add `unscreened` to `SanctionsStatus`; flip `Counterparty.sanctions_status` default.
- `backend/app/schemas/counterparty.py` — add `unscreened` to `SanctionsStatus`; flip `CounterpartyCreate.sanctions_status` default.
- `backend/app/services/counterparty_service.py` — flip the `sanctions_status` create default to `"unscreened"`.
- `backend/app/models/__init__.py` — import the two new model modules (table registration).
- `backend/app/main.py` — import + mount the `commercial_partners` router.
- `backend/app/api/routes/counterparties.py` — reject customer/supplier creation; full trader-invisibility (hedge-only).
- `backend/tests/test_counterparty_crud.py` — fix the one default assertion.
- `backend/tests/test_rbac_matrix_enforcement.py` — update 3 existing counterparty tests + add commercial-partner RBAC cases.

---

## Setup (once, before Task 1)

- [ ] Create the working branch off `main`:

```bash
git checkout main && git pull
git checkout -b w1/commercial-partners-foundation
```

- [ ] Confirm baseline is green and the head is `048`:

```bash
cd backend && python -m pytest -x -q && python -m alembic heads
```
Expected: tests pass; `048_order_external_reference (head)`.

---

## Task 1: Add `unscreened` to `SanctionsStatus` + flip hedge default

**Files:**
- Modify: `backend/app/models/counterparty.py:29-32` (enum), `:71-75` (column default)
- Modify: `backend/app/schemas/counterparty.py:22-25` (enum), `:52` (Create default)
- Modify: `backend/app/services/counterparty_service.py:35` (create default literal)
- Modify: `backend/tests/test_counterparty_crud.py:50` (assertion)
- Test: `backend/tests/test_counterparty_crud.py`

- [ ] **Step 1: Update the failing assertion to the new default**

In `backend/tests/test_counterparty_crud.py`, the create test that does not pass `sanctions_status` currently asserts `clear`. Change line 50:

```python
    assert body["sanctions_status"] == "unscreened"
```

- [ ] **Step 2: Run it to verify it fails (default still `clear`)**

Run: `cd backend && python -m pytest tests/test_counterparty_crud.py -q`
Expected: FAIL — assertion gets `"clear"`, expected `"unscreened"`.

- [ ] **Step 3: Add the enum member (model)**

In `backend/app/models/counterparty.py` replace the `SanctionsStatus` class:

```python
class SanctionsStatus(enum.Enum):
    unscreened = "unscreened"
    clear = "clear"
    flagged = "flagged"
    blocked = "blocked"
```

And in the `Counterparty` model flip the `sanctions_status` column default:

```python
    sanctions_status: Mapped[SanctionsStatus] = mapped_column(
        Enum(SanctionsStatus, name="sanctions_status"),
        nullable=False,
        default=SanctionsStatus.unscreened,
    )
```

- [ ] **Step 4: Add the enum member (schema) + flip the Create default**

In `backend/app/schemas/counterparty.py` replace `SanctionsStatus`:

```python
class SanctionsStatus(str, Enum):
    unscreened = "unscreened"
    clear = "clear"
    flagged = "flagged"
    blocked = "blocked"
```

And change `CounterpartyCreate.sanctions_status` (line ~52):

```python
    sanctions_status: SanctionsStatus = SanctionsStatus.unscreened
```

- [ ] **Step 5: Flip the service create default literal**

In `backend/app/services/counterparty_service.py`, in `CounterpartyService.create`, change the `sanctions_status` line:

```python
            sanctions_status=SanctionsStatus(data.get("sanctions_status", "unscreened")),
```

- [ ] **Step 6: Run to verify pass + no collateral breakage**

Run: `cd backend && python -m pytest tests/test_counterparty_crud.py tests/test_internal_test_endpoint_gated.py -q`
Expected: PASS. (`test_internal_test_endpoint_gated.py` + `tests/e2e/_fixtures.py` set `clear` explicitly, so they are unaffected.)

- [ ] **Step 7: Commit**

```bash
git add backend/app/models/counterparty.py backend/app/schemas/counterparty.py backend/app/services/counterparty_service.py backend/tests/test_counterparty_crud.py
git commit -m "feat(counterparty): add unscreened SanctionsStatus member; default hedge sanctions_status to unscreened (W1)"
```

---

## Task 2: `CommercialPartner` model + enums + registration

**Files:**
- Create: `backend/app/models/commercial_partner.py`
- Modify: `backend/app/models/__init__.py`
- Test: `backend/tests/test_commercial_partner_service.py` (new — first test here)

Field set per spec §5.1. **Dedicated PG enum type names** (`commercial_kyc_status`, `commercial_sanctions_status`, `commercial_risk_rating`, `commercial_partner_kind`, `lei_status`) — NOT the hedge `kyc_status`/`sanctions_status`/`risk_rating` type names — so `op.create_table` auto-creates them cleanly on fresh Postgres without colliding with the existing hedge types (avoids the `create_type=False` dance). The Python enum *classes* `KycStatus`/`SanctionsStatus`/`RiskRating` are reused from `counterparty.py`.

- [ ] **Step 1: Write the failing test** (`backend/tests/test_commercial_partner_service.py`, new file)

```python
from __future__ import annotations

import uuid
from decimal import Decimal

import pytest
from sqlalchemy.exc import IntegrityError

from app.core.database import SessionLocal
from app.models.commercial_partner import (
    CommercialPartner,
    CommercialPartnerKind,
    LeiStatus,
)
from app.models.counterparty import KycStatus, RiskRating, SanctionsStatus


def test_commercial_partner_defaults_are_fail_closed():
    with SessionLocal() as session:
        cp = CommercialPartner(
            kind=CommercialPartnerKind.customer,
            name="Acme Co",
            country="BRA",
        )
        session.add(cp)
        session.commit()
        session.refresh(cp)
        assert isinstance(cp.id, uuid.UUID)
        assert cp.kyc_status is KycStatus.pending
        assert cp.sanctions_status is SanctionsStatus.unscreened
        assert cp.lei_status is LeiStatus.not_provided
        assert cp.risk_rating is RiskRating.medium
        assert cp.is_active is True
        assert cp.is_deleted is False


def test_commercial_partner_supplier_cannot_carry_customer_credit_fields():
    with SessionLocal() as session:
        cp = CommercialPartner(
            kind=CommercialPartnerKind.supplier,
            name="Bad Supplier",
            country="BRA",
            credit_limit=Decimal("1000.00"),  # customer-only field — CHECK must reject
        )
        session.add(cp)
        with pytest.raises(IntegrityError):
            session.commit()
```

- [ ] **Step 2: Run to verify it fails**

Run: `cd backend && python -m pytest tests/test_commercial_partner_service.py -q`
Expected: FAIL with `ModuleNotFoundError: app.models.commercial_partner`.

- [ ] **Step 3: Create the model**

`backend/app/models/commercial_partner.py`:

```python
import enum
import uuid
from datetime import datetime
from decimal import Decimal

import sqlalchemy as sa
from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    Enum,
    Numeric,
    String,
    Text,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.sql import func

from app.models.base import Base
from app.models.counterparty import KycStatus, RiskRating, SanctionsStatus

JsonPayload = sa.JSON().with_variant(JSONB(astext_type=Text()), "postgresql")


class CommercialPartnerKind(enum.Enum):
    customer = "customer"
    supplier = "supplier"


class LeiStatus(enum.Enum):
    not_provided = "not_provided"
    valid = "valid"
    invalid = "invalid"
    lapsed = "lapsed"
    issued = "issued"
    error = "error"


class CommercialPartner(Base):
    __tablename__ = "commercial_partners"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    kind: Mapped[CommercialPartnerKind] = mapped_column(
        Enum(CommercialPartnerKind, name="commercial_partner_kind"), nullable=False
    )
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    short_name: Mapped[str | None] = mapped_column(String(50), nullable=True)
    tax_id: Mapped[str | None] = mapped_column(String(50), nullable=True, unique=True)
    country: Mapped[str] = mapped_column(String(3), nullable=False)
    city: Mapped[str | None] = mapped_column(String(100), nullable=True)
    address: Mapped[str | None] = mapped_column(Text, nullable=True)
    contact_name: Mapped[str | None] = mapped_column(String(200), nullable=True)
    contact_email: Mapped[str | None] = mapped_column(String(200), nullable=True)
    contact_phone: Mapped[str | None] = mapped_column(String(50), nullable=True)
    whatsapp_phone: Mapped[str | None] = mapped_column(String(50), nullable=True)

    lei: Mapped[str | None] = mapped_column(String(20), nullable=True)
    lei_status: Mapped[LeiStatus] = mapped_column(
        Enum(LeiStatus, name="lei_status"),
        nullable=False,
        default=LeiStatus.not_provided,
    )
    lei_legal_name: Mapped[str | None] = mapped_column(String(200), nullable=True)
    lei_checked_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    kyc_status: Mapped[KycStatus] = mapped_column(
        Enum(KycStatus, name="commercial_kyc_status"),
        nullable=False,
        default=KycStatus.pending,
    )
    sanctions_status: Mapped[SanctionsStatus] = mapped_column(
        Enum(SanctionsStatus, name="commercial_sanctions_status"),
        nullable=False,
        default=SanctionsStatus.unscreened,
    )
    risk_rating: Mapped[RiskRating] = mapped_column(
        Enum(RiskRating, name="commercial_risk_rating"),
        nullable=False,
        default=RiskRating.medium,
    )

    # customer-only credit fields (CHECK: NULL when kind=supplier)
    credit_limit: Mapped[Decimal | None] = mapped_column(Numeric(18, 2), nullable=True)
    credit_currency: Mapped[str | None] = mapped_column(String(3), nullable=True)
    payment_conditions: Mapped[dict | None] = mapped_column(JsonPayload, nullable=True)

    # supplier-only terms fields (CHECK: NULL when kind=customer)
    approved_value: Mapped[Decimal | None] = mapped_column(Numeric(18, 2), nullable=True)
    approved_currency: Mapped[str | None] = mapped_column(String(3), nullable=True)
    approved_terms: Mapped[dict | None] = mapped_column(JsonPayload, nullable=True)

    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), onupdate=func.now(), nullable=True
    )
    is_deleted: Mapped[bool] = mapped_column(Boolean, default=False)
    deleted_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True, default=None
    )

    __table_args__ = (
        CheckConstraint(
            "kind <> 'supplier' OR ("
            "credit_limit IS NULL AND credit_currency IS NULL "
            "AND payment_conditions IS NULL)",
            name="ck_commercial_partners_supplier_no_customer_credit",
        ),
        CheckConstraint(
            "kind <> 'customer' OR ("
            "approved_value IS NULL AND approved_currency IS NULL "
            "AND approved_terms IS NULL)",
            name="ck_commercial_partners_customer_no_supplier_terms",
        ),
    )
```

- [ ] **Step 4: Register the model for table creation**

In `backend/app/models/__init__.py`, add an import next to `from app.models.counterparty import (...)`:

```python
from app.models.commercial_partner import (
    CommercialPartner,
    CommercialPartnerKind,
    LeiStatus,
)
```

(If `__init__.py` maintains an `__all__`, append the three names.)

- [ ] **Step 5: Run to verify pass**

Run: `cd backend && python -m pytest tests/test_commercial_partner_service.py -q`
Expected: PASS (both tests). The CHECK constraint fires on SQLite because the enum value `'supplier'` is stored as text.

- [ ] **Step 6: Commit**

```bash
git add backend/app/models/commercial_partner.py backend/app/models/__init__.py backend/tests/test_commercial_partner_service.py
git commit -m "feat(model): add CommercialPartner with kind-asymmetric Decimal credit CHECKs (W1)"
```

---

## Task 3: `SanctionsScreening` + `SanctionsAdjudication` models (append-only)

**Files:**
- Create: `backend/app/models/sanctions.py`
- Modify: `backend/app/models/__init__.py`
- Test: `backend/tests/test_commercial_partner_service.py` (append)

Shapes per governance "Sanctions screening governance" (`sanctions_screenings`) + "Adjudication" (`sanctions_adjudications`). These are created in W1 but **written by no service code until W2** — the test only asserts the table/columns exist and accept a row.

- [ ] **Step 1: Write the failing test** (append to `tests/test_commercial_partner_service.py`)

```python
def test_sanctions_tables_exist_and_accept_rows():
    from datetime import datetime, timezone

    from app.models.sanctions import (
        AdjudicationDecision,
        SanctionsAdjudication,
        SanctionsPartnerType,
        SanctionsScreening,
        ScreeningResult,
        ScreeningStatus,
    )

    with SessionLocal() as session:
        partner_id = uuid.uuid4()
        screening = SanctionsScreening(
            partner_type=SanctionsPartnerType.commercial,
            partner_id=partner_id,
            screened_at=datetime.now(timezone.utc),
            provider="opensanctions",
            algorithm="logic-v2",
            query_hash="deadbeef",
            match_count=0,
            result=ScreeningResult.clear,
            actor_sub="risk-1",
            status=ScreeningStatus.success,
        )
        session.add(screening)
        session.commit()
        session.refresh(screening)

        adj = SanctionsAdjudication(
            partner_type=SanctionsPartnerType.commercial,
            partner_id=partner_id,
            superseded_screening_id=screening.id,
            decision=AdjudicationDecision.clear,
            reason="false positive, confirmed",
            adjudicating_actor_sub="risk-1",
            adjudicated_at=datetime.now(timezone.utc),
        )
        session.add(adj)
        session.commit()
        assert screening.status is ScreeningStatus.success
        assert adj.decision is AdjudicationDecision.clear
```

- [ ] **Step 2: Run to verify it fails**

Run: `cd backend && python -m pytest tests/test_commercial_partner_service.py::test_sanctions_tables_exist_and_accept_rows -q`
Expected: FAIL with `ModuleNotFoundError: app.models.sanctions`.

- [ ] **Step 3: Create the models**

`backend/app/models/sanctions.py`:

```python
import enum
import uuid
from datetime import datetime
from decimal import Decimal

import sqlalchemy as sa
from sqlalchemy import DateTime, Enum, Integer, Numeric, String, Text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base

JsonPayload = sa.JSON().with_variant(JSONB(astext_type=Text()), "postgresql")


class SanctionsPartnerType(enum.Enum):
    commercial = "commercial"
    hedge = "hedge"


class ScreeningResult(enum.Enum):
    clear = "clear"
    flagged = "flagged"
    blocked = "blocked"


class ScreeningStatus(enum.Enum):
    success = "success"
    error = "error"


class AdjudicationDecision(enum.Enum):
    clear = "clear"
    blocked = "blocked"


class SanctionsScreening(Base):
    """Append-only, immutable. Written by the W2 screening service; created in W1."""

    __tablename__ = "sanctions_screenings"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    partner_type: Mapped[SanctionsPartnerType] = mapped_column(
        Enum(SanctionsPartnerType, name="sanctions_partner_type"), nullable=False
    )
    partner_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    screened_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    provider: Mapped[str] = mapped_column(String(64), nullable=False)
    algorithm: Mapped[str] = mapped_column(String(64), nullable=False)
    dataset_version: Mapped[str | None] = mapped_column(String(64), nullable=True)
    query_hash: Mapped[str] = mapped_column(String(128), nullable=False)
    top_score: Mapped[Decimal | None] = mapped_column(Numeric(6, 4), nullable=True)
    match_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    matches_json: Mapped[dict | None] = mapped_column(JsonPayload, nullable=True)
    result: Mapped[ScreeningResult | None] = mapped_column(
        Enum(ScreeningResult, name="sanctions_screening_result"), nullable=True
    )  # NULL when status=error
    actor_sub: Mapped[str] = mapped_column(String(200), nullable=False)
    status: Mapped[ScreeningStatus] = mapped_column(
        Enum(ScreeningStatus, name="sanctions_screening_status"), nullable=False
    )
    error_detail: Mapped[str | None] = mapped_column(Text, nullable=True)


class SanctionsAdjudication(Base):
    """Append-only, immutable risk_manager override of a flagged screening. Created in W1."""

    __tablename__ = "sanctions_adjudications"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    partner_type: Mapped[SanctionsPartnerType] = mapped_column(
        Enum(SanctionsPartnerType, name="sanctions_partner_type"), nullable=False
    )
    partner_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    superseded_screening_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), nullable=False
    )
    decision: Mapped[AdjudicationDecision] = mapped_column(
        Enum(AdjudicationDecision, name="sanctions_adjudication_decision"),
        nullable=False,
    )
    reason: Mapped[str] = mapped_column(Text, nullable=False)
    adjudicating_actor_sub: Mapped[str] = mapped_column(String(200), nullable=False)
    adjudicated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
```

> Note: `partner_type` reuses the same named enum `sanctions_partner_type` on BOTH tables. On Postgres this means the migration must create that type once and reference it with `create_type=False` on the second table (handled in Task 8). On SQLite it is two independent CHECKs — harmless.

- [ ] **Step 4: Register**

In `backend/app/models/__init__.py` add:

```python
from app.models.sanctions import (
    AdjudicationDecision,
    SanctionsAdjudication,
    SanctionsPartnerType,
    SanctionsScreening,
    ScreeningResult,
    ScreeningStatus,
)
```

- [ ] **Step 5: Run to verify pass**

Run: `cd backend && python -m pytest tests/test_commercial_partner_service.py -q`
Expected: PASS (all three tests).

- [ ] **Step 6: Commit**

```bash
git add backend/app/models/sanctions.py backend/app/models/__init__.py backend/tests/test_commercial_partner_service.py
git commit -m "feat(model): add append-only SanctionsScreening + SanctionsAdjudication tables (W1)"
```

---

## Task 4: Pydantic schemas for commercial partners

**Files:**
- Create: `backend/app/schemas/commercial_partner.py`
- Test: `backend/tests/test_commercial_partner_service.py` (append)

Mirrors `schemas/counterparty.py`. The `kyc-status` endpoint **reuses** `KycStatusTransitionRequest` from `schemas/counterparty.py` (same shape: `new_status` + `reason` min 8). Credit uses a new `CreditApprovalRequest` with **Decimal** monetary fields (governance "Credit and terms governance": Decimal, never float).

- [ ] **Step 1: Write the failing test** (append)

```python
def test_commercial_partner_create_schema_rejects_kyc_and_credit_fields():
    from app.schemas.commercial_partner import CommercialPartnerCreate

    # kyc_status / credit fields are NOT part of the create schema at all
    payload = CommercialPartnerCreate(kind="customer", name="Acme", country="BRA")
    dumped = payload.model_dump()
    assert "kyc_status" not in dumped
    assert "credit_limit" not in dumped
    assert "approved_value" not in dumped


def test_credit_approval_request_parses_decimal():
    from decimal import Decimal

    from app.schemas.commercial_partner import CreditApprovalRequest

    req = CreditApprovalRequest(credit_limit="12345.67", credit_currency="USD")
    assert req.credit_limit == Decimal("12345.67")
```

- [ ] **Step 2: Run to verify it fails**

Run: `cd backend && python -m pytest tests/test_commercial_partner_service.py -k schema_rejects -q`
Expected: FAIL with `ModuleNotFoundError: app.schemas.commercial_partner`.

- [ ] **Step 3: Create the schemas**

`backend/app/schemas/commercial_partner.py`:

```python
from datetime import datetime
from decimal import Decimal
from enum import Enum
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from app.schemas.counterparty import KycStatus, RiskRating, SanctionsStatus


class CommercialPartnerKind(str, Enum):
    customer = "customer"
    supplier = "supplier"


class LeiStatus(str, Enum):
    not_provided = "not_provided"
    valid = "valid"
    invalid = "invalid"
    lapsed = "lapsed"
    issued = "issued"
    error = "error"


class CommercialPartnerCreate(BaseModel):
    # NOTE: deliberately omits kyc_status, sanctions_status, and all credit/terms
    # fields — server forces kyc_status=pending, sanctions_status=unscreened, and
    # credit/terms are set only via the dedicated risk_manager flow.
    kind: CommercialPartnerKind
    name: str = Field(..., max_length=200)
    short_name: str | None = Field(None, max_length=50)
    tax_id: str | None = Field(None, max_length=50)
    country: str = Field(..., min_length=3, max_length=3)
    city: str | None = Field(None, max_length=100)
    address: str | None = None
    contact_name: str | None = Field(None, max_length=200)
    contact_email: str | None = Field(None, max_length=200)
    contact_phone: str | None = Field(None, max_length=50)
    whatsapp_phone: str | None = Field(
        None, max_length=50, description="WhatsApp number in E.164 format"
    )
    lei: str | None = Field(None, max_length=20)
    risk_rating: RiskRating = RiskRating.medium
    is_active: bool = True
    notes: str | None = None


class CommercialPartnerUpdate(BaseModel):
    # Identity/contact/LEI-input fields ONLY. kyc_status + credit/terms are NOT here;
    # the route additionally rejects any attempt to send them (defense in depth).
    name: str | None = Field(None, max_length=200)
    short_name: str | None = Field(None, max_length=50)
    tax_id: str | None = Field(None, max_length=50)
    country: str | None = Field(None, min_length=3, max_length=3)
    city: str | None = Field(None, max_length=100)
    address: str | None = None
    contact_name: str | None = Field(None, max_length=200)
    contact_email: str | None = Field(None, max_length=200)
    contact_phone: str | None = Field(None, max_length=50)
    whatsapp_phone: str | None = Field(None, max_length=50)
    lei: str | None = Field(None, max_length=20)
    risk_rating: RiskRating | None = None
    is_active: bool | None = None
    notes: str | None = None


class CreditApprovalRequest(BaseModel):
    # customer fields
    credit_limit: Decimal | None = None
    credit_currency: str | None = Field(None, min_length=3, max_length=3)
    payment_conditions: dict | None = None
    # supplier fields
    approved_value: Decimal | None = None
    approved_currency: str | None = Field(None, min_length=3, max_length=3)
    approved_terms: dict | None = None


class CommercialPartnerRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    kind: CommercialPartnerKind
    name: str
    short_name: str | None = None
    tax_id: str | None = None
    country: str
    city: str | None = None
    address: str | None = None
    contact_name: str | None = None
    contact_email: str | None = None
    contact_phone: str | None = None
    whatsapp_phone: str | None = None
    lei: str | None = None
    lei_status: LeiStatus
    lei_legal_name: str | None = None
    lei_checked_at: datetime | None = None
    kyc_status: KycStatus
    sanctions_status: SanctionsStatus
    risk_rating: RiskRating
    credit_limit: Decimal | None = None
    credit_currency: str | None = None
    payment_conditions: dict | None = None
    approved_value: Decimal | None = None
    approved_currency: str | None = None
    approved_terms: dict | None = None
    is_active: bool
    notes: str | None = None
    created_at: datetime
    updated_at: datetime | None = None
    is_deleted: bool
    deleted_at: datetime | None = None


class CommercialPartnerListResponse(BaseModel):
    items: list[CommercialPartnerRead]
    next_cursor: str | None = Field(None, max_length=256)
```

- [ ] **Step 4: Run to verify pass**

Run: `cd backend && python -m pytest tests/test_commercial_partner_service.py -k "schema_rejects or credit_approval" -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/app/schemas/commercial_partner.py backend/tests/test_commercial_partner_service.py
git commit -m "feat(schema): commercial partner Create/Update/Read + Decimal CreditApprovalRequest (W1)"
```

---

## Task 5: `CommercialPartnerService`

**Files:**
- Create: `backend/app/services/commercial_partner_service.py`
- Test: `backend/tests/test_commercial_partner_service.py` (append)

Mirrors `CounterpartyService` + adds the W1 invariants:
- `update` **rejects** `kyc_status` and any credit/terms key (HTTP 403) for ALL actors, and applies the **identity-edit fail-closed reset** (governance Authorization invariants): if `name`/`country`/`tax_id`/`lei` change and `sanctions_status != unscreened`, reset `sanctions_status → unscreened` and `kyc_status → pending` (if it was `approved`).
- `set_kyc_status` enforces transition→`approved` requires `sanctions_status == clear` (governance "Status transitions").
- `approve_credit` validates kind/field coherence and returns previous values for the audit payload.

- [ ] **Step 1: Write the failing tests** (append)

```python
def _new_partner(session, kind=CommercialPartnerKind.customer, **overrides):
    cp = CommercialPartner(
        kind=kind, name=overrides.pop("name", "Acme"), country="BRA", **overrides
    )
    session.add(cp)
    session.commit()
    session.refresh(cp)
    return cp


def test_service_update_rejects_kyc_status():
    from fastapi import HTTPException

    from app.services.commercial_partner_service import CommercialPartnerService

    with SessionLocal() as session:
        cp = _new_partner(session)
        with pytest.raises(HTTPException) as exc:
            CommercialPartnerService.update(session, cp, {"kyc_status": "approved"})
        assert exc.value.status_code == 403


def test_service_update_rejects_credit_fields():
    from fastapi import HTTPException

    from app.services.commercial_partner_service import CommercialPartnerService

    with SessionLocal() as session:
        cp = _new_partner(session)
        with pytest.raises(HTTPException) as exc:
            CommercialPartnerService.update(session, cp, {"credit_limit": "10.00"})
        assert exc.value.status_code == 403


def test_service_identity_edit_resets_compliance_fail_closed():
    from app.services.commercial_partner_service import CommercialPartnerService

    with SessionLocal() as session:
        cp = _new_partner(session)
        cp.sanctions_status = SanctionsStatus.clear
        cp.kyc_status = KycStatus.approved
        session.commit()
        CommercialPartnerService.update(session, cp, {"name": "Acme Renamed"})
        assert cp.sanctions_status is SanctionsStatus.unscreened
        assert cp.kyc_status is KycStatus.pending


def test_service_kyc_approve_blocked_unless_sanctions_clear():
    from fastapi import HTTPException

    from app.services.commercial_partner_service import CommercialPartnerService

    with SessionLocal() as session:
        cp = _new_partner(session)  # sanctions_status defaults to unscreened
        with pytest.raises(HTTPException) as exc:
            CommercialPartnerService.set_kyc_status(
                session, cp.id, new_status=KycStatus.approved
            )
        assert exc.value.status_code == 422

        cp.sanctions_status = SanctionsStatus.clear
        session.commit()
        updated, previous = CommercialPartnerService.set_kyc_status(
            session, cp.id, new_status=KycStatus.approved
        )
        assert updated.kyc_status is KycStatus.approved
        assert previous is KycStatus.pending


def test_service_approve_credit_customer_decimal_roundtrip():
    from app.services.commercial_partner_service import CommercialPartnerService

    with SessionLocal() as session:
        cp = _new_partner(session, kind=CommercialPartnerKind.customer)
        cp2, changed, previous, new_values = CommercialPartnerService.approve_credit(
            session, cp, {"credit_limit": Decimal("12345.67"), "credit_currency": "USD"}
        )
        session.refresh(cp2)
        assert cp2.credit_limit == Decimal("12345.67")
        assert "credit_limit" in changed


def test_service_approve_credit_rejects_cross_kind_fields():
    from fastapi import HTTPException

    from app.services.commercial_partner_service import CommercialPartnerService

    with SessionLocal() as session:
        cp = _new_partner(session, kind=CommercialPartnerKind.customer)
        with pytest.raises(HTTPException) as exc:
            CommercialPartnerService.approve_credit(
                session, cp, {"approved_value": Decimal("1.00")}  # supplier field on a customer
            )
        assert exc.value.status_code == 422
```

- [ ] **Step 2: Run to verify it fails**

Run: `cd backend && python -m pytest tests/test_commercial_partner_service.py -k service_ -q`
Expected: FAIL with `ModuleNotFoundError: app.services.commercial_partner_service`.

- [ ] **Step 3: Create the service**

`backend/app/services/commercial_partner_service.py`:

```python
from datetime import UTC, datetime
from decimal import Decimal
from uuid import UUID

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.precision import to_decimal
from app.models.commercial_partner import CommercialPartner, CommercialPartnerKind, LeiStatus
from app.models.counterparty import KycStatus, RiskRating, SanctionsStatus

_IDENTITY_FIELDS = {"name", "country", "tax_id", "lei"}
_CREDIT_FIELDS = {
    "credit_limit",
    "credit_currency",
    "payment_conditions",
    "approved_value",
    "approved_currency",
    "approved_terms",
}
_CUSTOMER_CREDIT_FIELDS = {"credit_limit", "credit_currency", "payment_conditions"}
_SUPPLIER_CREDIT_FIELDS = {"approved_value", "approved_currency", "approved_terms"}


class CommercialPartnerService:
    @staticmethod
    def create(session: Session, data: dict, *, commit: bool = True) -> CommercialPartner:
        cp = CommercialPartner(
            kind=CommercialPartnerKind(data["kind"]),
            name=data["name"],
            short_name=data.get("short_name"),
            tax_id=data.get("tax_id"),
            country=data["country"],
            city=data.get("city"),
            address=data.get("address"),
            contact_name=data.get("contact_name"),
            contact_email=data.get("contact_email"),
            contact_phone=data.get("contact_phone"),
            whatsapp_phone=data.get("whatsapp_phone"),
            lei=data.get("lei"),
            lei_status=LeiStatus.not_provided,
            kyc_status=KycStatus.pending,  # server-forced, fail-closed
            sanctions_status=SanctionsStatus.unscreened,  # server-forced, fail-closed
            risk_rating=RiskRating(data.get("risk_rating", "medium")),
            is_active=data.get("is_active", True),
            notes=data.get("notes"),
        )
        session.add(cp)
        session.flush()
        if commit:
            session.commit()
            session.refresh(cp)
        return cp

    @staticmethod
    def get_by_id(session: Session, cp_id: UUID) -> CommercialPartner | None:
        cp = session.get(CommercialPartner, cp_id)
        if cp and not cp.is_deleted:
            return cp
        return None

    @staticmethod
    def list(
        session: Session,
        *,
        kind_filter: str | None = None,
        kyc_status_filter: str | None = None,
        is_active_filter: bool | None = None,
    ):
        query = session.query(CommercialPartner).filter(
            CommercialPartner.is_deleted == False  # noqa: E712
        )
        if kind_filter:
            query = query.filter(
                CommercialPartner.kind == CommercialPartnerKind(kind_filter)
            )
        if kyc_status_filter:
            query = query.filter(
                CommercialPartner.kyc_status == KycStatus(kyc_status_filter)
            )
        if is_active_filter is not None:
            query = query.filter(CommercialPartner.is_active == is_active_filter)
        return query

    @staticmethod
    def update(
        session: Session, cp: CommercialPartner, data: dict, *, commit: bool = True
    ) -> CommercialPartner:
        if "kyc_status" in data:
            raise HTTPException(
                status_code=403,
                detail=(
                    "kyc_status mutations require the dedicated risk_manager "
                    "transition endpoint (POST /commercial-partners/{id}/kyc-status). "
                    "Generic update path cannot mutate kyc_status."
                ),
            )
        if _CREDIT_FIELDS & data.keys():
            raise HTTPException(
                status_code=403,
                detail=(
                    "credit/terms mutations require the dedicated risk_manager "
                    "endpoint (PATCH /commercial-partners/{id}/credit). Generic "
                    "update path cannot mutate credit/terms."
                ),
            )

        identity_changed = any(
            key in _IDENTITY_FIELDS and value is not None and getattr(cp, key) != value
            for key, value in data.items()
        )
        for key, value in data.items():
            if value is not None:
                if key == "risk_rating":
                    setattr(cp, key, RiskRating(value))
                else:
                    setattr(cp, key, value)

        # Identity-edit fail-closed reset (governance Authorization invariants):
        # stale compliance evidence must not survive an identity change.
        if identity_changed and cp.sanctions_status is not SanctionsStatus.unscreened:
            cp.sanctions_status = SanctionsStatus.unscreened
            if cp.kyc_status is KycStatus.approved:
                cp.kyc_status = KycStatus.pending

        session.flush()
        if commit:
            session.commit()
            session.refresh(cp)
        return cp

    @staticmethod
    def set_kyc_status(
        session: Session, cp_id: UUID, *, new_status: KycStatus
    ) -> tuple[CommercialPartner, KycStatus]:
        stmt = (
            select(CommercialPartner)
            .where(
                CommercialPartner.id == cp_id,
                CommercialPartner.is_deleted == False,  # noqa: E712
            )
            .with_for_update()
        )
        cp = session.execute(stmt).scalar_one_or_none()
        if not cp:
            raise HTTPException(status_code=404, detail="Commercial partner not found")
        # Transition to approved requires effective clear (governance Status transitions).
        # In W1 the stored sanctions_status already reflects any adjudication (W2 writes it),
        # so the check reads the stored field directly.
        if (
            new_status is KycStatus.approved
            and cp.sanctions_status is not SanctionsStatus.clear
        ):
            raise HTTPException(
                status_code=422,
                detail=(
                    "kyc_status cannot transition to approved unless the partner's "
                    f"sanctions_status is clear (observed: {cp.sanctions_status.value})."
                ),
            )
        previous_status = cp.kyc_status
        cp.kyc_status = new_status
        session.flush()
        return cp, previous_status

    @staticmethod
    def approve_credit(
        session: Session, cp: CommercialPartner, data: dict, *, commit: bool = True
    ) -> tuple[CommercialPartner, list[str], dict, dict]:
        allowed = (
            _CUSTOMER_CREDIT_FIELDS
            if cp.kind is CommercialPartnerKind.customer
            else _SUPPLIER_CREDIT_FIELDS
        )
        provided = {k: v for k, v in data.items() if v is not None}
        cross_kind = provided.keys() - allowed
        if cross_kind:
            raise HTTPException(
                status_code=422,
                detail=(
                    f"{cp.kind.value} partners cannot carry fields {sorted(cross_kind)}; "
                    f"allowed: {sorted(allowed)}"
                ),
            )
        previous_values: dict = {}
        new_values: dict = {}
        changed: list[str] = []
        for key, value in provided.items():
            previous_values[key] = _jsonable(getattr(cp, key))
            if key in {"credit_limit", "approved_value"}:
                value = to_decimal(value)
            setattr(cp, key, value)
            new_values[key] = _jsonable(value)
            changed.append(key)
        session.flush()
        if commit:
            session.commit()
            session.refresh(cp)
        return cp, changed, previous_values, new_values

    @staticmethod
    def soft_delete(
        session: Session, cp: CommercialPartner, *, commit: bool = True
    ) -> CommercialPartner:
        cp.is_deleted = True
        cp.deleted_at = datetime.now(UTC)
        cp.is_active = False
        session.flush()
        if commit:
            session.commit()
            session.refresh(cp)
        return cp

    @staticmethod
    def check_tax_id_unique(
        session: Session, tax_id: str, exclude_id: UUID | None = None
    ) -> bool:
        query = session.query(CommercialPartner).filter(
            CommercialPartner.tax_id == tax_id,
            CommercialPartner.is_deleted == False,  # noqa: E712
        )
        if exclude_id:
            query = query.filter(CommercialPartner.id != exclude_id)
        return query.first() is None


def _jsonable(value):
    if isinstance(value, Decimal):
        return str(value)
    return value
```

- [ ] **Step 4: Run to verify pass**

Run: `cd backend && python -m pytest tests/test_commercial_partner_service.py -q`
Expected: PASS (all tests).

- [ ] **Step 5: Lint + commit**

```bash
cd backend && ruff check app/services/commercial_partner_service.py && ruff format app/services/commercial_partner_service.py
git add backend/app/services/commercial_partner_service.py backend/tests/test_commercial_partner_service.py
git commit -m "feat(service): CommercialPartnerService CRUD + kyc/credit invariants + identity reset (W1)"
```

---

## Task 6: `commercial_partners` router + mount

**Files:**
- Create: `backend/app/api/routes/commercial_partners.py`
- Modify: `backend/app/main.py`
- Test: covered by Task 10 (RBAC matrix). Add a smoke test here for the happy paths.

Mirrors `routes/counterparties.py`. Endpoints: `POST` / `GET` (filter by kind/kyc_status/is_active) / `GET {id}` / `PATCH` / `DELETE` / `POST {id}/kyc-status` (risk_manager) / `PATCH {id}/credit` (risk_manager). Audit events: `commercial_partner_created/updated/deleted`, `commercial_partner_kyc_status_changed`, `commercial_partner_credit_approved`. RBAC per matrix: writes `require_any_role("trader","risk_manager")`; reads add `"auditor"`; kyc-status + credit `require_role("risk_manager")`.

- [ ] **Step 1: Write a smoke test** (append to `tests/test_commercial_partner_service.py`)

```python
def test_router_create_and_get_roundtrip(client, auth_as):
    auth_as("trader")
    resp = client.post(
        "/commercial-partners",
        json={"kind": "customer", "name": "Roundtrip Co", "country": "BRA"},
    )
    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert body["kind"] == "customer"
    assert body["kyc_status"] == "pending"
    assert body["sanctions_status"] == "unscreened"

    got = client.get(f"/commercial-partners/{body['id']}")
    assert got.status_code == 200
```

> `client` + `auth_as` fixtures already exist in `tests/test_rbac_matrix_enforcement.py`; if they are not shared via `conftest.py`, replicate the local `auth_as`/`client` fixtures at the top of `test_commercial_partner_service.py` using the same `app.dependency_overrides[get_current_user]` pattern (see Task 10 Step 1 for the canonical fixtures). Verify which by grepping `conftest.py` for `def client` before assuming.

- [ ] **Step 2: Run to verify it fails**

Run: `cd backend && python -m pytest tests/test_commercial_partner_service.py -k router_create -q`
Expected: FAIL — 404 (route not mounted).

- [ ] **Step 3: Create the router**

`backend/app/api/routes/commercial_partners.py`:

```python
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from sqlalchemy.orm import Session

from app.api.dependencies.audit import audit_event, mark_audit_success
from app.api.dependencies.uow import unit_of_work
from app.core.auth import (
    get_current_actor_sub,
    require_any_role,
    require_role,
)
from app.core.database import get_session
from app.core.pagination import paginate
from app.models.commercial_partner import CommercialPartner
from app.schemas.commercial_partner import (
    CommercialPartnerCreate,
    CommercialPartnerListResponse,
    CommercialPartnerRead,
    CommercialPartnerUpdate,
    CreditApprovalRequest,
)
from app.schemas.counterparty import KycStatusTransitionRequest
from app.services.commercial_partner_service import CommercialPartnerService

router = APIRouter()


@router.post("", response_model=CommercialPartnerRead, status_code=status.HTTP_201_CREATED)
def create_commercial_partner(
    payload: CommercialPartnerCreate,
    request: Request,
    actor_sub: str = Depends(get_current_actor_sub),
    _: None = Depends(
        audit_event(entity_type="commercial_partner", event_type="created")
    ),
    __: None = Depends(require_any_role("trader", "risk_manager")),
    session: Session = Depends(get_session),
) -> CommercialPartnerRead:
    if payload.tax_id and not CommercialPartnerService.check_tax_id_unique(
        session, payload.tax_id
    ):
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="tax_id already exists")
    with unit_of_work(session, request=request):
        cp = CommercialPartnerService.create(session, payload.model_dump(), commit=False)
        mark_audit_success(request, cp.id, metadata={"actor_sub": actor_sub})
    return CommercialPartnerRead.model_validate(cp)


@router.get("", response_model=CommercialPartnerListResponse)
def list_commercial_partners(
    kind: str | None = Query(None, description="Filter by kind"),
    kyc_status: str | None = Query(None, description="Filter by KYC status"),
    is_active: bool | None = Query(None, description="Filter by active status"),
    cursor: str | None = Query(None),
    limit: int = Query(50, ge=1, le=200),
    _: None = Depends(require_any_role("trader", "risk_manager", "auditor")),
    session: Session = Depends(get_session),
) -> CommercialPartnerListResponse:
    query = CommercialPartnerService.list(
        session,
        kind_filter=kind,
        kyc_status_filter=kyc_status,
        is_active_filter=is_active,
    )
    items, next_cursor = paginate(
        query,
        created_at_col=CommercialPartner.created_at,
        id_col=CommercialPartner.id,
        cursor=cursor,
        limit=limit,
    )
    return CommercialPartnerListResponse(
        items=[CommercialPartnerRead.model_validate(cp) for cp in items],
        next_cursor=next_cursor,
    )


@router.get("/{commercial_partner_id}", response_model=CommercialPartnerRead)
def get_commercial_partner(
    commercial_partner_id: UUID,
    _: None = Depends(require_any_role("trader", "risk_manager", "auditor")),
    session: Session = Depends(get_session),
) -> CommercialPartnerRead:
    cp = CommercialPartnerService.get_by_id(session, commercial_partner_id)
    if not cp:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Commercial partner not found"
        )
    return CommercialPartnerRead.model_validate(cp)


@router.patch("/{commercial_partner_id}", response_model=CommercialPartnerRead)
def update_commercial_partner(
    commercial_partner_id: UUID,
    payload: CommercialPartnerUpdate,
    request: Request,
    actor_sub: str = Depends(get_current_actor_sub),
    _: None = Depends(
        audit_event(entity_type="commercial_partner", event_type="updated")
    ),
    __: None = Depends(require_any_role("trader", "risk_manager")),
    session: Session = Depends(get_session),
) -> CommercialPartnerRead:
    cp = CommercialPartnerService.get_by_id(session, commercial_partner_id)
    if not cp:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Commercial partner not found"
        )
    update_data = payload.model_dump(exclude_unset=True)
    if "tax_id" in update_data and update_data["tax_id"] is not None:
        if not CommercialPartnerService.check_tax_id_unique(
            session, update_data["tax_id"], exclude_id=cp.id
        ):
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT, detail="tax_id already exists"
            )
    with unit_of_work(session, request=request):
        cp = CommercialPartnerService.update(session, cp, update_data, commit=False)
        mark_audit_success(request, cp.id, metadata={"actor_sub": actor_sub})
    return CommercialPartnerRead.model_validate(cp)


@router.delete("/{commercial_partner_id}", response_model=CommercialPartnerRead)
def delete_commercial_partner(
    commercial_partner_id: UUID,
    request: Request,
    actor_sub: str = Depends(get_current_actor_sub),
    _: None = Depends(
        audit_event(entity_type="commercial_partner", event_type="deleted")
    ),
    __: None = Depends(require_any_role("trader", "risk_manager")),
    session: Session = Depends(get_session),
) -> CommercialPartnerRead:
    cp = CommercialPartnerService.get_by_id(session, commercial_partner_id)
    if not cp:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Commercial partner not found"
        )
    with unit_of_work(session, request=request):
        cp = CommercialPartnerService.soft_delete(session, cp, commit=False)
        mark_audit_success(request, cp.id, metadata={"actor_sub": actor_sub})
    return CommercialPartnerRead.model_validate(cp)


@router.post(
    "/{commercial_partner_id}/kyc-status",
    response_model=CommercialPartnerRead,
    status_code=status.HTTP_200_OK,
)
def transition_kyc_status(
    commercial_partner_id: UUID,
    payload: KycStatusTransitionRequest,
    request: Request,
    actor_sub: str = Depends(get_current_actor_sub),
    _: None = Depends(
        audit_event(
            entity_type="commercial_partner",
            event_type="commercial_partner_kyc_status_changed",
        )
    ),
    __: None = Depends(require_role("risk_manager")),
    session: Session = Depends(get_session),
) -> CommercialPartnerRead:
    with unit_of_work(session, request=request):
        cp, previous_status = CommercialPartnerService.set_kyc_status(
            session, commercial_partner_id, new_status=payload.new_status
        )
        mark_audit_success(
            request,
            cp.id,
            metadata={
                "commercial_partner_id": str(cp.id),
                "previous_status": previous_status.value,
                "new_status": payload.new_status.value,
                "transition_actor_sub": actor_sub,
                "reason": payload.reason,
            },
        )
    return CommercialPartnerRead.model_validate(cp)


@router.patch(
    "/{commercial_partner_id}/credit",
    response_model=CommercialPartnerRead,
    status_code=status.HTTP_200_OK,
)
def approve_credit(
    commercial_partner_id: UUID,
    payload: CreditApprovalRequest,
    request: Request,
    actor_sub: str = Depends(get_current_actor_sub),
    _: None = Depends(
        audit_event(
            entity_type="commercial_partner",
            event_type="commercial_partner_credit_approved",
        )
    ),
    __: None = Depends(require_role("risk_manager")),
    session: Session = Depends(get_session),
) -> CommercialPartnerRead:
    cp = CommercialPartnerService.get_by_id(session, commercial_partner_id)
    if not cp:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Commercial partner not found"
        )
    data = payload.model_dump(exclude_unset=True)
    with unit_of_work(session, request=request):
        cp, changed, previous_values, new_values = CommercialPartnerService.approve_credit(
            session, cp, data, commit=False
        )
        mark_audit_success(
            request,
            cp.id,
            metadata={
                "commercial_partner_id": str(cp.id),
                "kind": cp.kind.value,
                "fields_changed": changed,
                "previous_values": previous_values,
                "new_values": new_values,
                "approving_actor_sub": actor_sub,
            },
        )
    return CommercialPartnerRead.model_validate(cp)
```

- [ ] **Step 4: Mount the router** in `backend/app/main.py`

Add `commercial_partners` to the `from app.api.routes import (...)` block (alphabetical, after `cashflow_ledger`/before `contracts` is fine), and register near the `counterparties` include:

```python
app.include_router(
    commercial_partners.router,
    prefix="/commercial-partners",
    tags=["Commercial Partners"],
)
```

- [ ] **Step 5: Run to verify pass**

Run: `cd backend && python -m pytest tests/test_commercial_partner_service.py -k router_create -q`
Expected: PASS.

- [ ] **Step 6: Lint + commit**

```bash
cd backend && ruff check app/api/routes/commercial_partners.py app/main.py && ruff format app/api/routes/commercial_partners.py
git add backend/app/api/routes/commercial_partners.py backend/app/main.py backend/tests/test_commercial_partner_service.py
git commit -m "feat(routes): mount commercial_partners router (CRUD + kyc-status + credit) (W1)"
```

---

## Task 7: Make `counterparties` hedge-only (route + 3 existing tests)

**Files:**
- Modify: `backend/app/api/routes/counterparties.py`
- Modify: `backend/tests/test_rbac_matrix_enforcement.py` (3 tests)
- Test: `backend/tests/test_rbac_matrix_enforcement.py`

Governance "Authorization invariants": after W1, `counterparties` holds ONLY hedge types and trader has no hedge-counterparty access. Implementation: reject `customer`/`supplier` on create (they belong in `/commercial-partners`), and refuse trader-only on every method (404 by-id, empty list, 403 on create). Keep the route gates as `require_any_role(...)` per the matrix; the second layer enforces trader-invisibility.

- [ ] **Step 1: Update the 3 existing tests to the hedge-only contract**

In `backend/tests/test_rbac_matrix_enforcement.py`:

Replace `test_counterparty_post_type_gate` parametrization + body:

```python
@pytest.mark.parametrize(
    ("role", "type_", "expected_status"),
    [
        ("trader", "broker", 403),       # trader has no hedge write access
        ("trader", "customer", 403),     # trader-only refused before type check
        ("risk_manager", "broker", 201),
        ("risk_manager", "customer", 422),  # customer/supplier belong in /commercial-partners
    ],
)
def test_counterparty_post_type_gate(
    client, auth_as, role: str, type_: str, expected_status: int
) -> None:
    auth_as(role)
    response = client.post(
        "/counterparties", json=_counterparty_payload(type_, f"post-{role}-{type_}")
    )
    assert response.status_code == expected_status
```

Replace `test_counterparty_patch_trader_accepts_customer` with a trader-invisibility assertion (customer rows no longer live in `counterparties`; a trader PATCH on any hedge row 404s):

```python
def test_counterparty_patch_trader_404s_any_hedge_row(client, auth_as, session) -> None:
    broker = _insert_counterparty(session, CounterpartyType.broker, "broker patch")
    auth_as("trader")
    response = client.patch(f"/counterparties/{broker.id}", json={"city": "Rio"})
    assert response.status_code == 404
```

Replace `test_counterparty_get_list_trader_filters_broker_bank` with an empty-list assertion for trader:

```python
def test_counterparty_get_list_trader_sees_empty(client, auth_as, session) -> None:
    _insert_counterparty(session, CounterpartyType.broker, "broker list")
    _insert_counterparty(session, CounterpartyType.bank_br, "bank list")
    auth_as("trader")

    response = client.get("/counterparties")

    assert response.status_code == 200
    assert response.json()["items"] == []
```

- [ ] **Step 2: Run to verify they fail**

Run: `cd backend && python -m pytest tests/test_rbac_matrix_enforcement.py -k "counterparty_post_type_gate or counterparty_patch_trader or counterparty_get_list" -q`
Expected: FAIL (current routes still allow trader customer create / customer rows).

- [ ] **Step 3: Update `create_counterparty`** in `backend/app/api/routes/counterparties.py`

Replace the trader/type branch at the top of `create_counterparty` with hedge-only logic:

```python
    # counterparties is hedge-only after W1: customer/supplier are managed via
    # /commercial-partners. Trader has no hedge-counterparty write access.
    if payload.type in (CounterpartyType.customer, CounterpartyType.supplier):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=(
                "customer/supplier partners are managed via /commercial-partners, "
                "not /counterparties (hedge brokers/banks only)."
            ),
        )
    if "risk_manager" not in actor_roles:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Hedge counterparties are risk_manager-only.",
        )
```

> Keep `payload` typed as `CounterpartyCreate` and `payload.type` as `CounterpartyType` (the schema enum still lists customer/supplier — we reject them at the route, not by removing the enum members, to avoid churn on the vestigial paths).

- [ ] **Step 4: Update the trader-invisibility on read/update/delete**

The existing `_is_trader_only` / `_is_trader_counterparty_type` helpers already 404/empty broker/bank for trader-only actors (broker/bank are not "trader types"), so `get_counterparty`, `update_counterparty`, `delete_counterparty`, and `list_counterparties` already produce the hedge-only behavior for trader. **Verify** by re-reading those handlers — no change needed if they 404/empty for trader on broker/bank. (If any path still has a customer/supplier-specific branch that could 200 for trader, remove it.) The simplest correct end state: a `{trader}`-only actor gets 404 by-id and `[]` on list for every row in `counterparties`.

- [ ] **Step 5: Run to verify pass**

Run: `cd backend && python -m pytest tests/test_rbac_matrix_enforcement.py -k counterparty -q`
Expected: PASS for all counterparty tests (incl. the unchanged `test_counterparty_delete_trader_404s_broker`, `test_counterparty_get_by_id_trader_404s_broker`, `test_counterparty_get_by_id_auditor_returns_broker`).

- [ ] **Step 6: Commit**

```bash
git add backend/app/api/routes/counterparties.py backend/tests/test_rbac_matrix_enforcement.py
git commit -m "feat(routes): restrict counterparties to hedge-only; trader fully invisible (W1)"
```

---

## Task 8: Migration `049_commercial_partners_foundation`

**Files:**
- Create: `backend/alembic/versions/049_commercial_partners_foundation.py`
- Test: Task 9.

This is the highest-risk task. Contract (governance "Schema (binding)"):
1. Add `unscreened` to the existing hedge `sanctions_status` PG enum (**Postgres-only, in an `autocommit_block`** so the value is committed before it is used in the same migration; early-return on SQLite per the migration-023 precedent).
2. Create new enums + `commercial_partners`, `sanctions_screenings`, `sanctions_adjudications` (named ENUMs auto-created by `op.create_table`; the shared `sanctions_partner_type` is created once and re-used with `create_type=False` on the second table).
3. **Two pre-move HALT validations** (run FIRST, before any mutation): orders→broker/bank refs; hedge-domain refs (`rfq_invitations`, `rfq_quotes`, `hedge_contracts`, `llm_decision_artifacts`)→customer/supplier. Either non-empty ⇒ `RuntimeError` with a remediation report.
4. Copy `counterparties` rows where `type ∈ {customer,supplier}` into `commercial_partners` **reusing `id`**, kind-mapping `credit_limit_usd` → customer `credit_limit` / supplier `approved_value`, carrying contacts/risk_rating/notes/timestamps/soft-delete, and **resetting fail-closed** (`kyc_status='pending'`, `sanctions_status='unscreened'`). Migrate ALL such rows (incl. soft-deleted) so every `orders.counterparty_id` resolves.
5. Reset hedge `counterparties.sanctions_status → 'unscreened'`.
6. Repoint the `orders.counterparty_id` FK from `counterparties` → `commercial_partners` (PG: drop `fk_orders_counterparty_id` + recreate; SQLite: no-op — the original was created outside batch and isn't an enforced named constraint, and ids are preserved).
7. Restrict `counterparties` to hedge: delete the migrated customer/supplier rows.
8. `downgrade()` is best-effort (drop new tables + new enums; PG cannot drop an enum value, mirror migration-023's no-op note).

- [ ] **Step 1: Create the migration**

`backend/alembic/versions/049_commercial_partners_foundation.py`:

```python
"""commercial_partners_foundation

Creates commercial_partners + sanctions_screenings + sanctions_adjudications,
migrates customer/supplier rows out of counterparties (UUID-reuse, fail-closed
reset), runs two pre-move HALT validations, repoints orders FK, and restricts
counterparties to hedge types.

Revision ID: 049_commercial_partners_foundation
Revises: 048_order_external_reference
Create Date: 2026-05-29
"""

import sqlalchemy as sa
from sqlalchemy import text
from sqlalchemy.dialects import postgresql

from alembic import op

revision = "049_commercial_partners_foundation"
down_revision = "048_order_external_reference"
branch_labels = None
depends_on = None


# --- enum objects (auto-created by create_table on PG; CHECKs on SQLite) ---
commercial_partner_kind = sa.Enum("customer", "supplier", name="commercial_partner_kind")
commercial_kyc_status = sa.Enum(
    "pending", "approved", "expired", "rejected", name="commercial_kyc_status"
)
commercial_sanctions_status = sa.Enum(
    "unscreened", "clear", "flagged", "blocked", name="commercial_sanctions_status"
)
commercial_risk_rating = sa.Enum("low", "medium", "high", name="commercial_risk_rating")
lei_status = sa.Enum(
    "not_provided", "valid", "invalid", "lapsed", "issued", "error", name="lei_status"
)
sanctions_partner_type = sa.Enum("commercial", "hedge", name="sanctions_partner_type")
# second use of sanctions_partner_type must NOT re-create the type on PG
sanctions_partner_type_reuse = sa.Enum(
    "commercial", "hedge", name="sanctions_partner_type"
)
screening_result = sa.Enum("clear", "flagged", "blocked", name="sanctions_screening_result")
screening_status = sa.Enum("success", "error", name="sanctions_screening_status")
adjudication_decision = sa.Enum("clear", "blocked", name="sanctions_adjudication_decision")


def _uuid_type() -> sa.types.TypeEngine:
    return postgresql.UUID(as_uuid=True).with_variant(sa.String(length=36), "sqlite")


def _json_type() -> sa.types.TypeEngine:
    return postgresql.JSONB(astext_type=sa.Text()).with_variant(sa.JSON(), "sqlite")


def _ids_referencing(bind, table: str, partner_ids: set[str]) -> list[str]:
    """Return counterparty_id values in `table` that fall within partner_ids."""
    rows = bind.execute(
        text(f"SELECT counterparty_id FROM {table} WHERE counterparty_id IS NOT NULL")
    ).fetchall()
    return [str(r[0]) for r in rows if str(r[0]) in partner_ids]


def _validate_pre_move(bind) -> None:
    # (a) orders must not reference broker/bank counterparties (pre-fix data artifact).
    hedge_ids = {
        str(r[0])
        for r in bind.execute(
            text("SELECT id FROM counterparties WHERE type IN ('broker','bank_br')")
        )
    }
    bad_orders = _ids_referencing(bind, "orders", hedge_ids)
    if bad_orders:
        raise RuntimeError(
            "Refusing to migrate: "
            f"{len(bad_orders)} orders reference a hedge (broker/bank) counterparty. "
            "Re-point each affected order to the correct commercial_partner (or void "
            f"it) before running this migration. Offending counterparty_id values: {sorted(set(bad_orders))}"
        )

    # (b) hedge-domain refs must not reference customer/supplier counterparties.
    commercial_ids = {
        str(r[0])
        for r in bind.execute(
            text("SELECT id FROM counterparties WHERE type IN ('customer','supplier')")
        )
    }
    offenders: dict[str, list[str]] = {}
    for table in ("rfq_invitations", "rfq_quotes", "hedge_contracts", "llm_decision_artifacts"):
        hits = _ids_referencing(bind, table, commercial_ids)
        if hits:
            offenders[table] = sorted(set(hits))
    if offenders:
        raise RuntimeError(
            "Refusing to migrate: hedge-domain references point at commercial "
            "(customer/supplier) counterparties. Correct these references before "
            f"migration (no silent FK breakage): {offenders}"
        )


def upgrade() -> None:
    bind = op.get_bind()
    is_pg = bind.dialect.name == "postgresql"

    # 0. Validate FIRST — HALT cleanly before any mutation.
    _validate_pre_move(bind)

    # 1. Add 'unscreened' to the existing hedge sanctions_status enum (PG only).
    #    ALTER TYPE ADD VALUE must commit before the value is used in this same
    #    migration's UPDATE, so run it in an autocommit block.
    if is_pg:
        with op.get_context().autocommit_block():
            op.execute("ALTER TYPE sanctions_status ADD VALUE IF NOT EXISTS 'unscreened'")

    # 2. Create the new tables (named enums auto-created on PG).
    op.create_table(
        "commercial_partners",
        sa.Column("id", _uuid_type(), nullable=False),
        sa.Column("kind", commercial_partner_kind, nullable=False),
        sa.Column("name", sa.String(length=200), nullable=False),
        sa.Column("short_name", sa.String(length=50), nullable=True),
        sa.Column("tax_id", sa.String(length=50), nullable=True),
        sa.Column("country", sa.String(length=3), nullable=False),
        sa.Column("city", sa.String(length=100), nullable=True),
        sa.Column("address", sa.Text(), nullable=True),
        sa.Column("contact_name", sa.String(length=200), nullable=True),
        sa.Column("contact_email", sa.String(length=200), nullable=True),
        sa.Column("contact_phone", sa.String(length=50), nullable=True),
        sa.Column("whatsapp_phone", sa.String(length=50), nullable=True),
        sa.Column("lei", sa.String(length=20), nullable=True),
        sa.Column("lei_status", lei_status, nullable=False, server_default="not_provided"),
        sa.Column("lei_legal_name", sa.String(length=200), nullable=True),
        sa.Column("lei_checked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("kyc_status", commercial_kyc_status, nullable=False, server_default="pending"),
        sa.Column(
            "sanctions_status",
            commercial_sanctions_status,
            nullable=False,
            server_default="unscreened",
        ),
        sa.Column("risk_rating", commercial_risk_rating, nullable=False, server_default="medium"),
        sa.Column("credit_limit", sa.Numeric(18, 2), nullable=True),
        sa.Column("credit_currency", sa.String(length=3), nullable=True),
        sa.Column("payment_conditions", _json_type(), nullable=True),
        sa.Column("approved_value", sa.Numeric(18, 2), nullable=True),
        sa.Column("approved_currency", sa.String(length=3), nullable=True),
        sa.Column("approved_terms", _json_type(), nullable=True),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.text("1")),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("is_deleted", sa.Boolean(), nullable=False, server_default=sa.text("0")),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("tax_id", name="uq_commercial_partners_tax_id"),
        sa.CheckConstraint(
            "kind <> 'supplier' OR ("
            "credit_limit IS NULL AND credit_currency IS NULL AND payment_conditions IS NULL)",
            name="ck_commercial_partners_supplier_no_customer_credit",
        ),
        sa.CheckConstraint(
            "kind <> 'customer' OR ("
            "approved_value IS NULL AND approved_currency IS NULL AND approved_terms IS NULL)",
            name="ck_commercial_partners_customer_no_supplier_terms",
        ),
    )

    if is_pg:
        # The type was auto-created by the first create_table column referencing it;
        # prevent the second table from re-issuing CREATE TYPE.
        sanctions_partner_type_reuse.create_type = False  # type: ignore[attr-defined]

    op.create_table(
        "sanctions_screenings",
        sa.Column("id", _uuid_type(), nullable=False),
        sa.Column("partner_type", sanctions_partner_type, nullable=False),
        sa.Column("partner_id", _uuid_type(), nullable=False),
        sa.Column("screened_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("provider", sa.String(length=64), nullable=False),
        sa.Column("algorithm", sa.String(length=64), nullable=False),
        sa.Column("dataset_version", sa.String(length=64), nullable=True),
        sa.Column("query_hash", sa.String(length=128), nullable=False),
        sa.Column("top_score", sa.Numeric(6, 4), nullable=True),
        sa.Column("match_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("matches_json", _json_type(), nullable=True),
        sa.Column("result", screening_result, nullable=True),
        sa.Column("actor_sub", sa.String(length=200), nullable=False),
        sa.Column("status", screening_status, nullable=False),
        sa.Column("error_detail", sa.Text(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_sanctions_screenings_partner",
        "sanctions_screenings",
        ["partner_type", "partner_id", "screened_at"],
    )

    op.create_table(
        "sanctions_adjudications",
        sa.Column("id", _uuid_type(), nullable=False),
        sa.Column("partner_type", sanctions_partner_type_reuse, nullable=False),
        sa.Column("partner_id", _uuid_type(), nullable=False),
        sa.Column("superseded_screening_id", _uuid_type(), nullable=False),
        sa.Column("decision", adjudication_decision, nullable=False),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column("adjudicating_actor_sub", sa.String(length=200), nullable=False),
        sa.Column("adjudicated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )

    # 3. Copy customer/supplier rows (UUID reuse, kind-mapped credit, fail-closed reset).
    op.execute(
        text(
            """
            INSERT INTO commercial_partners (
                id, kind, name, short_name, tax_id, country, city, address,
                contact_name, contact_email, contact_phone, whatsapp_phone,
                lei_status, kyc_status, sanctions_status, risk_rating,
                credit_limit, credit_currency, approved_value, approved_currency,
                is_active, notes, created_at, updated_at, is_deleted, deleted_at
            )
            SELECT
                id, type, name, short_name, tax_id, country, city, address,
                contact_name, contact_email, contact_phone, whatsapp_phone,
                'not_provided', 'pending', 'unscreened', risk_rating,
                CASE WHEN type = 'customer' THEN credit_limit_usd ELSE NULL END,
                CASE WHEN type = 'customer' AND credit_limit_usd IS NOT NULL THEN 'USD' ELSE NULL END,
                CASE WHEN type = 'supplier' THEN credit_limit_usd ELSE NULL END,
                CASE WHEN type = 'supplier' AND credit_limit_usd IS NOT NULL THEN 'USD' ELSE NULL END,
                is_active, notes, created_at, updated_at, is_deleted, deleted_at
            FROM counterparties
            WHERE type IN ('customer', 'supplier')
            """
        )
    )

    # 4. Reset hedge counterparties to unscreened (fail-closed, both domains).
    op.execute(text("UPDATE counterparties SET sanctions_status = 'unscreened'"))

    # 5. Repoint orders FK (PG only; SQLite ids preserved, original FK not enforced).
    if is_pg:
        op.drop_constraint("fk_orders_counterparty_id", "orders", type_="foreignkey")
        op.create_foreign_key(
            "fk_orders_counterparty_id",
            "orders",
            "commercial_partners",
            ["counterparty_id"],
            ["id"],
        )

    # 6. Restrict counterparties to hedge: remove migrated customer/supplier rows.
    op.execute(text("DELETE FROM counterparties WHERE type IN ('customer', 'supplier')"))


def downgrade() -> None:
    bind = op.get_bind()
    is_pg = bind.dialect.name == "postgresql"

    if is_pg:
        op.drop_constraint("fk_orders_counterparty_id", "orders", type_="foreignkey")
        op.create_foreign_key(
            "fk_orders_counterparty_id",
            "orders",
            "counterparties",
            ["counterparty_id"],
            ["id"],
        )

    op.drop_table("sanctions_adjudications")
    op.drop_index("ix_sanctions_screenings_partner", table_name="sanctions_screenings")
    op.drop_table("sanctions_screenings")
    op.drop_table("commercial_partners")

    if is_pg:
        adjudication_decision.drop(bind, checkfirst=True)
        screening_status.drop(bind, checkfirst=True)
        screening_result.drop(bind, checkfirst=True)
        sanctions_partner_type.drop(bind, checkfirst=True)
        lei_status.drop(bind, checkfirst=True)
        commercial_risk_rating.drop(bind, checkfirst=True)
        commercial_sanctions_status.drop(bind, checkfirst=True)
        commercial_kyc_status.drop(bind, checkfirst=True)
        commercial_partner_kind.drop(bind, checkfirst=True)
    # NOTE: the 'unscreened' value added to the hedge sanctions_status enum is NOT
    # removed — PostgreSQL cannot drop an enum value (mirrors migration 023's note).
    # Restored customer/supplier counterparties rows are NOT re-created on downgrade;
    # downgrade is structural only.
```

- [ ] **Step 2: Verify single-head + import-clean**

Run: `cd backend && python -m pytest tests/test_alembic_chain.py -q`
Expected: PASS — single head is now `049_commercial_partners_foundation`.

- [ ] **Step 3: Lint + commit**

```bash
cd backend && ruff check alembic/versions/049_commercial_partners_foundation.py
git add backend/alembic/versions/049_commercial_partners_foundation.py
git commit -m "feat(migration): 049 commercial_partners + sanctions tables, UUID-reuse + fail-closed reset (W1)"
```

---

## Task 9: Migration roundtrip + validation tests

**Files:**
- Create: `backend/tests/test_049_migration_roundtrip.py`
- Test: same file.

Mirrors `tests/test_038_migration_roundtrip.py` (importlib load + `MigrationContext`/`Operations` on in-memory SQLite). Build a minimal pre-049 schema (only the tables/columns the migration touches), seed, run upgrade, assert.

- [ ] **Step 1: Write the tests**

`backend/tests/test_049_migration_roundtrip.py`:

```python
from __future__ import annotations

import importlib.util
import uuid
from pathlib import Path

import pytest
import sqlalchemy as sa
from alembic.migration import MigrationContext
from alembic.operations import Operations

MIGRATION_PATH = (
    Path(__file__).resolve().parents[1]
    / "alembic"
    / "versions"
    / "049_commercial_partners_foundation.py"
)


def _load():
    spec = importlib.util.spec_from_file_location("migration_049", MIGRATION_PATH)
    assert spec is not None and spec.loader is not None
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


def _create_pre_049_schema(conn: sa.Connection) -> None:
    md = sa.MetaData()
    sa.Table(
        "counterparties",
        md,
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("type", sa.String(length=20), nullable=False),
        sa.Column("name", sa.String(length=200), nullable=False),
        sa.Column("short_name", sa.String(length=50)),
        sa.Column("tax_id", sa.String(length=50)),
        sa.Column("country", sa.String(length=3), nullable=False),
        sa.Column("city", sa.String(length=100)),
        sa.Column("address", sa.Text()),
        sa.Column("contact_name", sa.String(length=200)),
        sa.Column("contact_email", sa.String(length=200)),
        sa.Column("contact_phone", sa.String(length=50)),
        sa.Column("whatsapp_phone", sa.String(length=50)),
        sa.Column("credit_limit_usd", sa.Numeric(15, 2)),
        sa.Column("risk_rating", sa.String(length=10), nullable=False),
        sa.Column("sanctions_status", sa.String(length=12), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False),
        sa.Column("notes", sa.Text()),
        sa.Column("created_at", sa.DateTime(timezone=True)),
        sa.Column("updated_at", sa.DateTime(timezone=True)),
        sa.Column("is_deleted", sa.Boolean(), nullable=False),
        sa.Column("deleted_at", sa.DateTime(timezone=True)),
    )
    for ref in ("orders", "rfq_invitations", "rfq_quotes", "hedge_contracts", "llm_decision_artifacts"):
        sa.Table(
            ref,
            md,
            sa.Column("id", sa.String(length=36), primary_key=True),
            sa.Column("counterparty_id", sa.String(length=100)),
        )
    md.create_all(conn)


def _seed_counterparty(conn, cp_id, type_, name, credit=None):
    conn.execute(
        sa.text(
            "INSERT INTO counterparties (id, type, name, country, risk_rating, "
            "sanctions_status, is_active, is_deleted, credit_limit_usd) VALUES "
            "(:id, :type, :name, 'BRA', 'medium', 'clear', 1, 0, :credit)"
        ),
        {"id": cp_id, "type": type_, "name": name, "credit": credit},
    )


def _run(conn, direction):
    m = _load()
    ctx = MigrationContext.configure(conn)
    with Operations.context(ctx):
        getattr(m, direction)()


def test_049_chains_from_048():
    m = _load()
    assert m.revision == "049_commercial_partners_foundation"
    assert m.down_revision == "048_order_external_reference"


def test_049_migrates_customer_supplier_preserving_uuid_and_resets_fail_closed():
    engine = sa.create_engine("sqlite:///:memory:")
    with engine.begin() as conn:
        _create_pre_049_schema(conn)
        cust_id = str(uuid.uuid4())
        supp_id = str(uuid.uuid4())
        broker_id = str(uuid.uuid4())
        _seed_counterparty(conn, cust_id, "customer", "Cust", credit=1000)
        _seed_counterparty(conn, supp_id, "supplier", "Supp", credit=2000)
        _seed_counterparty(conn, broker_id, "broker", "Brk")
        # an order referencing the customer (valid)
        conn.execute(
            sa.text("INSERT INTO orders (id, counterparty_id) VALUES (:i, :c)"),
            {"i": str(uuid.uuid4()), "c": cust_id},
        )

        _run(conn, "upgrade")

        rows = conn.execute(
            sa.text(
                "SELECT id, kind, kyc_status, sanctions_status, credit_limit, approved_value "
                "FROM commercial_partners ORDER BY kind"
            )
        ).fetchall()
        by_id = {r[0]: r for r in rows}
        assert cust_id in by_id and supp_id in by_id  # UUID reused
        assert by_id[cust_id][1] == "customer"
        assert by_id[cust_id][2] == "pending"        # kyc reset
        assert by_id[cust_id][3] == "unscreened"      # sanctions reset
        assert str(by_id[cust_id][4]) == "1000.00"    # customer credit_limit
        assert by_id[cust_id][5] is None              # customer has no approved_value
        assert str(by_id[supp_id][5]) == "2000.00"    # supplier approved_value

        # counterparties now hedge-only; hedge sanctions reset to unscreened
        remaining = conn.execute(
            sa.text("SELECT type, sanctions_status FROM counterparties")
        ).fetchall()
        assert {r[0] for r in remaining} == {"broker"}
        assert remaining[0][1] == "unscreened"

        # order still resolves to a commercial_partner with the same id
        oc = conn.execute(sa.text("SELECT counterparty_id FROM orders")).scalar_one()
        assert oc == cust_id


def test_049_halts_when_order_references_hedge_counterparty():
    engine = sa.create_engine("sqlite:///:memory:")
    with engine.begin() as conn:
        _create_pre_049_schema(conn)
        broker_id = str(uuid.uuid4())
        _seed_counterparty(conn, broker_id, "broker", "Brk")
        conn.execute(
            sa.text("INSERT INTO orders (id, counterparty_id) VALUES (:i, :c)"),
            {"i": str(uuid.uuid4()), "c": broker_id},
        )
        with pytest.raises(RuntimeError, match="reference a hedge"):
            _run(conn, "upgrade")


def test_049_halts_when_hedge_ref_points_at_commercial_counterparty():
    engine = sa.create_engine("sqlite:///:memory:")
    with engine.begin() as conn:
        _create_pre_049_schema(conn)
        cust_id = str(uuid.uuid4())
        _seed_counterparty(conn, cust_id, "customer", "Cust")
        conn.execute(
            sa.text("INSERT INTO rfq_invitations (id, counterparty_id) VALUES (:i, :c)"),
            {"i": str(uuid.uuid4()), "c": cust_id},
        )
        with pytest.raises(RuntimeError, match="hedge-domain references"):
            _run(conn, "upgrade")


def test_049_check_constraint_blocks_cross_kind_credit():
    engine = sa.create_engine("sqlite:///:memory:")
    with engine.begin() as conn:
        _create_pre_049_schema(conn)
        _run(conn, "upgrade")
        with pytest.raises(sa.exc.IntegrityError):
            conn.execute(
                sa.text(
                    "INSERT INTO commercial_partners "
                    "(id, kind, name, country, lei_status, kyc_status, sanctions_status, "
                    "risk_rating, is_active, is_deleted, approved_value) VALUES "
                    "(:i, 'customer', 'X', 'BRA', 'not_provided', 'pending', 'unscreened', "
                    "'medium', 1, 0, 5.00)"
                ),
                {"i": str(uuid.uuid4())},
            )
```

- [ ] **Step 2: Run the migration tests**

Run: `cd backend && python -m pytest tests/test_049_migration_roundtrip.py -q`
Expected: PASS (all 5).

- [ ] **Step 3: Commit**

```bash
git add backend/tests/test_049_migration_roundtrip.py
git commit -m "test(migration): 049 roundtrip, UUID-reuse, fail-closed reset, dual HALT validations (W1)"
```

---

## Task 10: RBAC matrix tests for commercial partners

**Files:**
- Modify: `backend/tests/test_rbac_matrix_enforcement.py`
- Test: same file.

Add cases per handoff §4 / governance Authorization invariants. Use the existing `client` / `auth_as` / `session` fixtures already in this file.

- [ ] **Step 1: Add a commercial-partner payload helper + the cases**

Append to `backend/tests/test_rbac_matrix_enforcement.py`:

```python
def _commercial_payload(kind: str, name: str | None = None) -> dict:
    return {
        "kind": kind,
        "name": name or f"{kind} CP",
        "country": "BRA",
        "tax_id": f"{kind}-{uuid.uuid4()}",
        "whatsapp_phone": "+5511999990000",
    }


def test_commercial_partner_trader_can_crud_identity(client, auth_as):
    auth_as("trader")
    created = client.post("/commercial-partners", json=_commercial_payload("customer"))
    assert created.status_code == 201, created.text
    cp_id = created.json()["id"]
    assert client.get(f"/commercial-partners/{cp_id}").status_code == 200
    patched = client.patch(f"/commercial-partners/{cp_id}", json={"city": "Rio"})
    assert patched.status_code == 200
    assert client.delete(f"/commercial-partners/{cp_id}").status_code == 200


def test_commercial_partner_trader_cannot_set_kyc_status(client, auth_as):
    auth_as("risk_manager")
    cp_id = client.post(
        "/commercial-partners", json=_commercial_payload("customer")
    ).json()["id"]
    auth_as("trader")
    resp = client.post(
        f"/commercial-partners/{cp_id}/kyc-status",
        json={"new_status": "approved", "reason": "trader attempt"},
    )
    assert resp.status_code == 403


def test_commercial_partner_trader_cannot_approve_credit(client, auth_as):
    auth_as("risk_manager")
    cp_id = client.post(
        "/commercial-partners", json=_commercial_payload("customer")
    ).json()["id"]
    auth_as("trader")
    resp = client.patch(
        f"/commercial-partners/{cp_id}/credit", json={"credit_limit": "100.00"}
    )
    assert resp.status_code == 403


def test_commercial_partner_generic_patch_rejects_kyc_for_all(client, auth_as):
    auth_as("risk_manager")
    cp_id = client.post(
        "/commercial-partners", json=_commercial_payload("customer")
    ).json()["id"]
    # even risk_manager cannot mutate kyc_status via generic PATCH
    resp = client.patch(f"/commercial-partners/{cp_id}", json={"kyc_status": "approved"})
    assert resp.status_code == 403


def test_commercial_partner_generic_patch_rejects_credit_for_all(client, auth_as):
    auth_as("risk_manager")
    cp_id = client.post(
        "/commercial-partners", json=_commercial_payload("customer")
    ).json()["id"]
    resp = client.patch(f"/commercial-partners/{cp_id}", json={"credit_limit": "5.00"})
    assert resp.status_code == 403


def test_commercial_partner_risk_manager_kyc_requires_sanctions_clear(client, auth_as, session):
    from app.models.commercial_partner import CommercialPartner
    from app.models.counterparty import SanctionsStatus

    auth_as("risk_manager")
    cp_id = client.post(
        "/commercial-partners", json=_commercial_payload("customer")
    ).json()["id"]
    # unscreened → approve denied (422)
    denied = client.post(
        f"/commercial-partners/{cp_id}/kyc-status",
        json={"new_status": "approved", "reason": "premature approve"},
    )
    assert denied.status_code == 422
    # flip to clear, then approve succeeds
    cp = session.get(CommercialPartner, uuid.UUID(cp_id))
    cp.sanctions_status = SanctionsStatus.clear
    session.commit()
    ok = client.post(
        f"/commercial-partners/{cp_id}/kyc-status",
        json={"new_status": "approved", "reason": "screening cleared"},
    )
    assert ok.status_code == 200
    assert ok.json()["kyc_status"] == "approved"


def test_commercial_partner_auditor_read_only(client, auth_as):
    auth_as("risk_manager")
    cp_id = client.post(
        "/commercial-partners", json=_commercial_payload("supplier")
    ).json()["id"]
    auth_as("auditor")
    assert client.get(f"/commercial-partners/{cp_id}").status_code == 200
    assert client.get("/commercial-partners").status_code == 200
    # auditor cannot write
    assert client.post("/commercial-partners", json=_commercial_payload("customer")).status_code == 403
    assert client.patch(f"/commercial-partners/{cp_id}", json={"city": "X"}).status_code == 403


def test_commercial_partner_identity_edit_resets_compliance(client, auth_as, session):
    from app.models.commercial_partner import CommercialPartner
    from app.models.counterparty import KycStatus, SanctionsStatus

    auth_as("risk_manager")
    cp_id = client.post(
        "/commercial-partners", json=_commercial_payload("customer")
    ).json()["id"]
    cp = session.get(CommercialPartner, uuid.UUID(cp_id))
    cp.sanctions_status = SanctionsStatus.clear
    cp.kyc_status = KycStatus.approved
    session.commit()

    auth_as("trader")
    resp = client.patch(f"/commercial-partners/{cp_id}", json={"name": "Renamed Co"})
    assert resp.status_code == 200
    assert resp.json()["sanctions_status"] == "unscreened"
    assert resp.json()["kyc_status"] == "pending"
```

> If `client`/`auth_as`/`session` are NOT module-local but live in `conftest.py`, these work as-is. If they are local fixtures defined in `test_rbac_matrix_enforcement.py` (they are — `auth_as` is at line 32), keep these tests in this same file so they share the fixtures.

- [ ] **Step 2: Run**

Run: `cd backend && python -m pytest tests/test_rbac_matrix_enforcement.py -k commercial_partner -q`
Expected: PASS (all 8).

- [ ] **Step 3: Commit**

```bash
git add backend/tests/test_rbac_matrix_enforcement.py
git commit -m "test(rbac): commercial_partners matrix — trader/risk_manager/auditor + identity reset (W1)"
```

---

## Task 11: Precision + audit-survival coverage

**Files:**
- Modify: `backend/tests/test_commercial_partner_service.py` (append)
- Test: same file.

- [ ] **Step 1: Add precision + audit tests**

```python
def test_credit_decimal_is_exact_through_api(client, auth_as):
    auth_as("risk_manager")
    cp_id = client.post(
        "/commercial-partners",
        json={"kind": "customer", "name": "Decimal Co", "country": "BRA"},
    ).json()["id"]
    resp = client.patch(
        f"/commercial-partners/{cp_id}/credit",
        json={"credit_limit": "12345.67", "credit_currency": "USD"},
    )
    assert resp.status_code == 200
    assert resp.json()["credit_limit"] == "12345.67"  # exact, no float drift


def test_credit_approved_emits_audit_event(client, auth_as, session):
    from app.models.audit import AuditEvent

    auth_as("risk_manager")
    cp_id = client.post(
        "/commercial-partners",
        json={"kind": "supplier", "name": "Audit Co", "country": "BRA"},
    ).json()["id"]
    client.patch(
        f"/commercial-partners/{cp_id}/credit",
        json={"approved_value": "999.99", "approved_currency": "USD"},
    )
    events = (
        session.query(AuditEvent)
        .filter(AuditEvent.event_type == "commercial_partner_credit_approved")
        .all()
    )
    assert len(events) >= 1
```

> `CommercialPartnerRead.credit_limit` serializes Decimal to a JSON string under Pydantic v2 default (Decimal → str). Confirm the serialized form during Step 2; if the project configures Decimal-as-number globally, assert the numeric/string form accordingly (grep for a Decimal `json_encoders`/`model_config` convention in `app/schemas/`).

- [ ] **Step 2: Run + then run the FULL suite**

```bash
cd backend && python -m pytest tests/test_commercial_partner_service.py -q
cd backend && python -m pytest -x -q
```
Expected: targeted PASS; full suite green (fix any collateral failures revealed by the default flip / hedge-only change).

- [ ] **Step 3: Lint**

```bash
cd backend && ruff check . && ruff format --check .
```

- [ ] **Step 4: Commit**

```bash
git add backend/tests/test_commercial_partner_service.py
git commit -m "test: commercial partner Decimal precision + credit-approval audit emission (W1)"
```

---

## Task 12: Frontend schema regen + final verification

**Files:**
- Modify: `frontend-svelte/src/lib/api/schema.d.ts` (generated)

- [ ] **Step 1: Regenerate the typed API client from the running backend**

In one shell:
```bash
cd backend && uvicorn app.main:app --port 8000
```
In another:
```bash
cd frontend-svelte && npm run api:types
```
This rewrites `src/lib/api/schema.d.ts` from `/openapi.json` (now includes `/commercial-partners`). Mind the `Field()` → `title` JSDoc drift noted in the handoff: regen in the same change.

- [ ] **Step 2: Frontend type check + drift guard**

```bash
cd frontend-svelte && npm run check && npm run api:types:check
```
Expected: PASS (no drift).

- [ ] **Step 3: Full backend gate once more**

```bash
cd backend && python -m pytest -x -q && python -m alembic heads
```
Expected: green; head `049_commercial_partners_foundation`.

- [ ] **Step 4: Commit + open PR**

```bash
git add frontend-svelte/src/lib/api/schema.d.ts
git commit -m "chore(frontend): regen schema.d.ts for /commercial-partners (W1)"
git push -u origin w1/commercial-partners-foundation
```
Then open the PR (W1 of the 7-wave effort). The review gate is the **Codex Connector** — `+1` reaction = acceptance; `eyes` = processing. Per the handoff: Codex inline comments LAG the review object — do NOT declare clean from an immediate empty poll; wait ≥60–120s, re-poll, and check sibling review ids.

> Pre-push hook: `.githooks/pre-push` only fires on `docs/**/*-dispatch.md` changes; this PR is code + a plan doc (not a `-dispatch.md`), so it should skip. If it fires and `ANTHROPIC_API_KEY` is absent, use `git push --no-verify` only with explicit orchestrator authorization (handoff §6).

---

## Self-Review (completed against the spec + governance)

**Spec coverage (§5/§6/§8/§10/§11):**
- §5.1 `commercial_partners` fields → Task 2 (all columns + kind CHECKs). ✓
- §5.2 `sanctions_screenings` + `sanctions_adjudications` (append-only) → Task 3 + Task 8 (tables). ✓
- §5.3 migration (enums, UUID reuse, fail-closed reset BOTH domains, two HALT validations, FK repoint, restrict, single-head) → Task 8 + Task 9. ✓
- §6 RBAC (trader CRUD minus kyc/credit; risk_manager kyc/credit; auditor read; generic PATCH rejects kyc/credit for all; identity reset; hedge invisible) → Tasks 5/6/7/10. ✓
- §7 `commercial_partner_service` (CRUD, kyc transition w/ clear invariant, credit approval) → Task 5. ✓ (sanctions/LEI services explicitly W2/W4.)
- §8 routes (POST/GET/GET{id}/PATCH/DELETE + kyc-status + credit) + schema regen → Task 6 + Task 12. ✓ (`/screen`, `/validate-lei`, `/adjudicate-sanctions` deferred to W2/W4 — documented in Scope.)
- §10 testing (RBAC, migration, service CRUD, precision) → Tasks 9/10/11. ✓ (commercial order gate + RFQ re-target tests are W3.)
- Governance "unscreened default" + "Status transitions" + "Credit and terms" event names/payloads → Tasks 1/5/6. ✓

**Placeholder scan:** no TBD/“add validation”/“similar to Task N”; every code step has full code. ✓

**Type consistency:** `CommercialPartnerService` method names (`create`, `get_by_id`, `list`, `update`, `set_kyc_status`, `approve_credit`, `soft_delete`, `check_tax_id_unique`) are used identically in Task 6 routes. Enum classes reused from `counterparty.py` (`KycStatus`/`SanctionsStatus`/`RiskRating`) with distinct PG type *names* in `commercial_partner.py`. Event types match governance verbatim (`commercial_partner_kyc_status_changed`, `commercial_partner_credit_approved`, `commercial_partner_created/updated/deleted`). ✓

**Known execution risks to watch (flagged, not placeholders):**
- The `sanctions_partner_type` enum reuse across two tables on Postgres relies on `create_type=False` for the second table; the `alembic-fresh-postgres` CI job is the durable check — run it (or a local PG `alembic upgrade head`) before declaring Task 8 done.
- Pydantic v2 Decimal JSON serialization form (string vs number) — Task 11 Step 1 note tells the executor to confirm against the project convention rather than assume.
- The full-suite run in Task 11 Step 2 is the catch-all for any collateral breakage from the hedge default flip / hedge-only route change.

---

## As-built corrections (recorded during execution)

The plan above is the design intent; these are the deltas applied during implementation (all committed on `w1/commercial-partners-foundation`). Recorded for the PR reviewer.

1. **Order model FK was missing from the plan (added).** The plan repointed `orders.counterparty_id` in the *migration* only; the ORM model still declared `ForeignKey("counterparties.id")`, diverging from the migration and from the e2e fixtures. Fixed: `backend/app/models/orders.py` now declares `ForeignKey("commercial_partners.id")` (commit `b431a8e`), so unit-test `create_all` agrees with migration 049 and with the two-domain semantics (orders → commercial supplier/customer).

2. **Migration 049 Postgres-correctness (Task 8) — three fixes vs the plan's draft code:**
   - The data copy casts `type → kind` and `risk_rating → commercial_risk_rating` via `::text::<target_enum>` on Postgres (they are *different* named enum types; a bare column copy fails at PG statement-prepare). SQLite uses the bare columns.
   - Removed `server_default=sa.text("1"/"0")` on the boolean columns (`boolean DEFAULT 1` is an integer→boolean type error on PG); `is_active`/`is_deleted` are `nullable=False` and always supplied by the INSERT.
   - Used a single shared `sanctions_partner_type` Enum object across both sanctions tables (the proven migration-046 pattern) rather than two objects + `create_type=False`.

3. **Task 7 `create_counterparty` ordering + enum bridging.** Implemented as risk_manager-check-first (→ 403) then `.value`-based type check (→ 422), because `payload.type` is the *schema* enum and the module's `CounterpartyType` is the *model* enum (direct member equality is always False). The 3 RBAC test cases were set to `(trader,broker,403) (trader,customer,403) (risk_manager,broker,201) (risk_manager,customer,422)`.

4. **Generic-PATCH 403 + KYC-transition enum normalization (commit `8308a68`, surfaced by Task 10).** `CommercialPartnerUpdate` omits `kyc_status`/credit fields, so Pydantic *silently dropped* them (200 instead of the governance-mandated 403). The route now inspects the raw request body (`request.state.audit_payload_obj`, set by the `audit_event` dependency) and refuses with 403. Separately, `set_kyc_status` normalizes the incoming (schema) `KycStatus` to the model enum (`KycStatus(getattr(new_status, "value", new_status))`) so the `is KycStatus.approved` + sanctions-clear precondition fires correctly (was a silent bypass: 200 instead of 422).

5. **Task 11 collateral alignment to the two-domain model.** `e2e/_fixtures.py` seeds hedge (broker/bank → `/counterparties`) AND commercial (customer/supplier → `/commercial-partners`); RFQ create/award fixtures + tests use hedge **brokers**; the order-enrichment PO test references a **supplier** commercial partner; the audit route-coverage `CLASSIFICATION` map gained the 5 `/commercial-partners` mutation routes.

6. **Suite status.** Full backend suite: 1560 passed, 11 skipped, **26 failed — all pre-existing/environmental** (verified identical on a clean `main` checkout with the same repo `.env`: `audit_signing_key`, `auth_fail_closed_app_env`, `internal_test_endpoint_gated`, `phase5_whatsapp_llm`, webhook, `service_token_minting`, and the route-coverage test, which needs `APP_ENV=test` so the `/internal/test/cleanup` route registers). **Zero W1-caused failures.** The `alembic-fresh-postgres` CI job remains the durable Postgres gate for migration 049's PG-only branches (ALTER TYPE autocommit, text-casts, FK repoint).

7. **Flagged for a separate session (spawned task):** `update_counterparty` (hedge) has the same silent-drop pattern for the now-vestigial `kyc_status` field — refuse with 403 mirroring the commercial-partners guard. Low severity (cannot mis-write data; the field is vestigial), so deferred rather than expanding W1.
