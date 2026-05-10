# Phase A3 - PR-A3-4 Dispatch - Cashflow Boundaries and Ledger/Baseline Reconciliation

**Wave:** 4 (depends on Wave 1 PR #41, Wave 2 PR #44, Wave 3 PR #47)
**Stage:** Remediation (post-jury)
**Authoring date:** 2026-05-10
**Findings covered:** J-A3-04 (T1, Baseline reads Analytic and Scenario labels Analytic as Baseline) + J-A3-OPUS-08 (T2, Ledger and Baseline lack a reconciliation invariant)
**Branch name:** `audit-a3/cashflow-boundaries-reconciliation`
**Base:** `main` (currently `40aa682d6`, post-PR-#47 cashflow projection hardening merge)

---

## 0. Refresh notes (read first)

This is the first PR-A3-4 dispatch. It is intentionally narrower than "cashflow refactor".

Verified against `main = 40aa682d6`:

- `backend/app/services/cashflow_baseline_service.py:10` imports `compute_cashflow_analytic`.
- `backend/app/services/cashflow_baseline_service.py:42-44` computes Baseline by calling Analytic, then persists `analytic.model_dump(mode="json")`.
- `backend/app/schemas/scenario.py:95-98` declares `ScenarioCashflowSnapshot.analytic` and `.baseline` with the same `CashFlowAnalyticResponse` type.
- `backend/app/services/scenario_whatif_service.py:523-530` builds one `cashflow_analytic` object and assigns it to both `analytic` and `baseline`.
- `backend/app/services/cashflow_ledger_service.py:77-157` now derives ledger rows server-side and persists price provenance for the floating leg.
- `backend/app/models/cashflow.py:25-41` stores `CashFlowBaselineSnapshot.snapshot_data` as JSON and `total_net_cashflow` as a column.
- Legacy rows in `cashflow_baseline_snapshots` may already contain the old Analytic-shaped `snapshot_data["cashflow_items"]` payload. Because the table is unique by `as_of_date`, PR-A3-4 must preserve and archive those legacy rows before the new Baseline-owned shape can be created for the same date.
- `docs/governance.md:131-159` already defines cashflow views and Projection-specific invariants after PR #47. PR-A3-4 does not need another constitutional change.

The institutional issue is not that Baseline and Analytic share arithmetic. The issue is that Baseline is currently an alias of Analytic, and Scenario publishes a Baseline field that is literally the Analytic object. Ledger also exists as accounting evidence but Baseline does not persist any realized-ledger reconciliation evidence. That is a cashflow-boundary failure.

---

## 1. Mission

Close PR-A3-4 by making cashflow boundaries explicit and auditable:

1. Baseline must be persisted by `cashflow_baseline_service` through a Baseline-owned builder. It must not import or call `compute_cashflow_analytic`, and it must not persist an Analytic response dump as its snapshot payload.
2. Baseline snapshot data must include realized ledger evidence up to `as_of_date`, with a deterministic reconciliation block proving how the persisted `total_net_cashflow` was formed.
3. Scenario must stop exposing a fake Baseline. `ScenarioCashflowSnapshot.baseline` is removed; What-if keeps its in-memory Analytic cashflow view only. If a future product needs Scenario-vs-Baseline comparison, it must be designed as a separate explicit contract, not by duplicating Analytic.
4. Existing Analytic-shaped Baseline rows must be archived by migration, not silently rewritten and not deleted without evidence.

After PR-A3-4:

- `cashflow_baseline_service.py` has no `compute_cashflow_analytic` import and no `CashFlowAnalyticResponse` dependency.
- `create_cashflow_baseline_snapshot()` persists a Baseline payload shaped as:

```json
{
  "view": "baseline",
  "as_of_date": "2026-02-01",
  "unrealized_items": [],
  "realized_ledger_entries": [],
  "reconciliation": {
    "unrealized_total_usd": "0.000000",
    "realized_total_usd": "0.000000",
    "total_net_cashflow": "0.000000",
    "unrealized_item_count": 0,
    "ledger_entry_count": 0
  }
}
```

- `CashFlowBaselineSnapshot.total_net_cashflow` equals `Decimal(reconciliation["total_net_cashflow"])`.
- `reconciliation["total_net_cashflow"]` equals `unrealized_total_usd + realized_total_usd`.
- `realized_total_usd` equals the sum of signed ledger entries where `IN` is positive and `OUT` is negative.
- Baseline includes realized ledger entries with provenance fields already landed by Wave 1.
- Scenario response schema no longer contains `cashflow_snapshot.baseline`.
- Migration 039 preserves legacy Analytic-shaped baseline rows in an archive table and removes them from the active `cashflow_baseline_snapshots` table so the new Baseline shape can be created without permanent 409 lock.

---

## 2. Reference docs and code (read before coding)

- `docs/audits/2026-05-09-phase-a3-jury-verdict.md`:
  - J-A3-04 section - Baseline cashflow reads Analytic and scenario labels Analytic as Baseline.
  - J-A3-OPUS-08 section - Ledger and Baseline lack a reconciliation invariant.
  - Remediation plan recommendation section, Wave 4.
- `docs/governance.md:131-159` - CashFlow views, one methodology per endpoint, no fallback pricing regimes, Projection invariants.
- `docs/governance.md:171-186` - hard-fail rules and no mixed regimes.
- `docs/governance.md:220-228` - output contract: explicit, audit-friendly, free of speculation.
- `backend/app/services/cashflow_baseline_service.py:1-86` - target Baseline service.
- `backend/app/services/cashflow_analytic_service.py:15-68` - current Analytic implementation. Read it to understand current arithmetic, but do not make Baseline call it.
- `backend/app/services/cashflow_ledger_service.py:77-157` - derived ledger entry and provenance contract.
- `backend/app/services/cashflow_ledger_service.py:299-315` - `list_entries_by_contract()`, useful only as a ledger-query reference. Do not copy its `created_at` ordering into Baseline reconciliation.
- `backend/app/models/cashflow.py:25-41` - Baseline snapshot model.
- `backend/app/models/cashflow.py:44-90` - ledger event and entry model.
- `backend/alembic/versions/038_a3_price_provenance.py` - prior A3 migration style.
- `backend/app/schemas/cashflow.py:34-68` - `CashFlowItem`, `CashFlowAnalyticResponse`, `CashFlowBaselineSnapshotResponse`.
- `backend/app/schemas/scenario.py:95-113` - scenario cashflow response schema.
- `backend/app/services/scenario_whatif_service.py:510-530` - current duplicate Analytic/Baseline assignment.
- `backend/tests/test_cashflow_baseline_service.py` - existing baseline tests to extend.
- `backend/tests/test_scenario_whatif_run.py` - scenario response tests to update.
- `backend/app/core/precision.py:34-35` - `quantize_money()` canonical 6-decimal money normalization.

---

## 3. Scope IN

### 3.1 Baseline-owned snapshot builder

Modify `backend/app/services/cashflow_baseline_service.py`.

Remove:

```python
from app.services.cashflow_analytic_service import compute_cashflow_analytic
```

Do not replace it with a wrapper around Analytic. Baseline owns its own snapshot construction.

Add helpers in `cashflow_baseline_service.py`:

```python
from app.core.precision import quantize_money
from app.models.cashflow import CashFlowBaselineSnapshot, CashFlowLedgerEntry
```

```python
def _signed_ledger_amount(entry: CashFlowLedgerEntry) -> Decimal:
    amount = quantize_money(entry.amount)
    if entry.direction == "IN":
        return amount
    if entry.direction == "OUT":
        return -amount
    raise HTTPException(
        status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
        detail=f"Unsupported ledger direction: {entry.direction}",
    )
```

```python
def _ledger_entry_payload(entry: CashFlowLedgerEntry) -> dict:
    signed_amount = _signed_ledger_amount(entry)
    return {
        "id": str(entry.id),
        "hedge_contract_id": str(entry.hedge_contract_id),
        "source_event_type": entry.source_event_type,
        "source_event_id": str(entry.source_event_id) if entry.source_event_id else None,
        "leg_id": entry.leg_id,
        "cashflow_date": entry.cashflow_date.isoformat(),
        "currency": entry.currency,
        "direction": entry.direction,
        "amount": str(quantize_money(entry.amount)),
        "signed_amount_usd": str(signed_amount),
        "price_source": entry.price_source,
        "price_symbol": entry.price_symbol,
        "price_settlement_date": (
            entry.price_settlement_date.isoformat()
            if entry.price_settlement_date is not None
            else None
        ),
        "price_value": str(entry.price_value) if entry.price_value is not None else None,
    }
```

```python
def _load_realized_ledger_entries(db: Session, as_of_date: date) -> list[CashFlowLedgerEntry]:
    return (
        db.query(CashFlowLedgerEntry)
        .filter(CashFlowLedgerEntry.cashflow_date <= as_of_date)
        .order_by(
            CashFlowLedgerEntry.cashflow_date.asc(),
            CashFlowLedgerEntry.hedge_contract_id.asc(),
            CashFlowLedgerEntry.leg_id.asc(),
            CashFlowLedgerEntry.source_event_id.asc().nulls_first(),
        )
        .all()
    )
```

Do not filter realized ledger entries by `source_event_type`. Baseline
reconciliation consumes accounting ledger evidence; future ledger source types
must not be silently excluded from realized totals. Preserve
`source_event_type` in each payload row for auditability.

Add a Baseline-owned unrealized item builder. It may call MTM services directly because MTM is the valuation primitive; it must not call Analytic.

Contracts:

- Include `HedgeContractStatus.active` and `HedgeContractStatus.partially_settled`.
- Exclude archived/soft-deleted contracts with `HedgeContract.deleted_at.is_(None)`.
- Skip `settled` contracts for unrealized items; their realized flows belong in ledger entries.
- Preserve price provenance fields in each `CashFlowItem`.
- Set `amount_usd=quantize_money(mtm.mtm_value)` and
  `mtm_value=quantize_money(mtm.mtm_value)` so persisted Baseline totals match
  the `Numeric(18, 6)` storage contract and idempotency does not false-409 on
  precision drift.

Orders:

- Include variable orders with MTM-eligible conventions, mirroring Analytic eligibility.
- Exclude archived/soft-deleted orders with `Order.deleted_at.is_(None)`.
- Preserve price provenance fields in each `CashFlowItem`.
- Set `amount_usd=quantize_money(mtm.mtm_value)` and
  `mtm_value=quantize_money(mtm.mtm_value)`.

Acceptable implementation shape:

```python
def _cashflow_item_from_mtm(mtm: MTMResultResponse, as_of_date: date) -> CashFlowItem:
    mtm_value = quantize_money(mtm.mtm_value)
    return CashFlowItem(
        object_type=mtm.object_type.value,
        object_id=mtm.object_id,
        settlement_date=as_of_date,
        amount_usd=mtm_value,
        mtm_value=mtm_value,
        price_source=mtm.price_quote.source,
        price_symbol=mtm.price_quote.symbol,
        price_settlement_date=mtm.price_quote.settlement_date,
        price_value=mtm.price_quote.value,
    )


def _build_unrealized_items(db: Session, as_of_date: date) -> list[CashFlowItem]:
    items: list[CashFlowItem] = []
    # Query active + partially_settled, non-deleted contracts and variable
    # MTM-eligible, non-deleted orders.
    # Call compute_mtm_for_contract / compute_mtm_for_order directly.
    # Convert each MTMResultResponse through _cashflow_item_from_mtm() so
    # every unrealized item carries price_quote provenance.
    return items
```

This intentionally shares the same pricing primitives as Analytic without making Baseline a proxy for Analytic.

### 3.2 Baseline payload contract and reconciliation invariant

Replace the current lines `42-45` pattern:

```python
analytic = compute_cashflow_analytic(db, as_of_date=as_of_date)
total = Decimal(analytic.total_net_cashflow)
payload = _canonicalize_snapshot_payload(analytic.model_dump(mode="json"))
inputs_hash = _compute_inputs_hash(as_of_date, payload, total)
```

with Baseline-owned payload creation:

```python
unrealized_items = _build_unrealized_items(db, as_of_date)
realized_entries = _load_realized_ledger_entries(db, as_of_date)

unrealized_total = quantize_money(
    sum((item.amount_usd for item in unrealized_items), Decimal("0"))
)
realized_amounts = [_signed_ledger_amount(entry) for entry in realized_entries]
realized_payload = [_ledger_entry_payload(entry) for entry in realized_entries]
realized_total = quantize_money(
    sum(realized_amounts, Decimal("0"))
)
total = quantize_money(unrealized_total + realized_total)

payload = _canonicalize_snapshot_payload(
    {
        "view": "baseline",
        "as_of_date": as_of_date.isoformat(),
        "unrealized_items": [
            item.model_dump(mode="json") for item in unrealized_items
        ],
        "realized_ledger_entries": realized_payload,
        "reconciliation": {
            "unrealized_total_usd": str(unrealized_total),
            "realized_total_usd": str(realized_total),
            "total_net_cashflow": str(total),
            "unrealized_item_count": len(unrealized_items),
            "ledger_entry_count": len(realized_payload),
        },
    }
)
inputs_hash = _compute_inputs_hash(as_of_date, payload, total)
```

Replace `_canonicalize_snapshot_payload()` with:

```python
def _canonicalize_snapshot_payload(payload: dict) -> dict:
    if "unrealized_items" in payload and isinstance(payload["unrealized_items"], list):
        payload["unrealized_items"] = sorted(
            payload["unrealized_items"],
            key=lambda item: (item.get("object_type"), item.get("object_id")),
        )
    if "realized_ledger_entries" in payload and isinstance(
        payload["realized_ledger_entries"], list
    ):
        payload["realized_ledger_entries"] = sorted(
            payload["realized_ledger_entries"],
            key=lambda item: (
                item.get("cashflow_date"),
                item.get("hedge_contract_id"),
                item.get("leg_id"),
                item.get("source_event_id") or "",
            ),
        )
    return payload
```

The database query order and canonical payload order must use the same stable
four-field realized-ledger key. Do not use `created_at` as a reconciliation
tiebreaker; it is not serialized into `snapshot_data` and therefore cannot be
part of the persisted hash contract.

`source_event_id` is nullable in the model. The SQL order must use
`.nulls_first()` so it matches the Python canonicalization sentinel
`item.get("source_event_id") or ""`. Without explicit NULL placement,
PostgreSQL and SQLite sort NULLs differently.

Keep the existing conflict behavior: if an existing snapshot for `as_of_date` does not match the newly derived payload, return HTTP 409. Do not silently rewrite old analytic-shaped snapshots into the new Baseline shape.

The conflict check must use the replacement `_canonicalize_snapshot_payload()`
for both the newly computed payload and `existing.snapshot_data`; otherwise
persisted rows with new `unrealized_items` / `realized_ledger_entries` arrays
may false-conflict because only the old `cashflow_items` array is sorted.

### 3.3 Scenario response boundary

Modify `backend/app/schemas/scenario.py`.

Current:

```python
class ScenarioCashflowSnapshot(BaseModel):
    analytic: CashFlowAnalyticResponse
    baseline: CashFlowAnalyticResponse
```

Replace with:

```python
class ScenarioCashflowSnapshot(BaseModel):
    analytic: CashFlowAnalyticResponse
```

Modify `backend/app/services/scenario_whatif_service.py`.

Current:

```python
cashflow_snapshot = ScenarioCashflowSnapshot(
    analytic=cashflow_analytic, baseline=cashflow_analytic
)
```

Replace with:

```python
cashflow_snapshot = ScenarioCashflowSnapshot(analytic=cashflow_analytic)
```

Do not add a new scenario baseline comparison field in this PR. That would be a product/API design task and would need its own contract: baseline snapshot selection, missing baseline handling, and comparison semantics.

### 3.4 OpenAPI/frontend schema regeneration

Because `ScenarioCashflowSnapshot` changes, regenerate API artifacts:

- `docs/api/openapi_v1.json`
- `frontend-svelte/src/lib/api/schema.d.ts`

No frontend component change is expected unless the generated type change exposes a real consumer. Current search on `main = 40aa682d6` found no direct frontend read of `cashflow_snapshot.baseline`.

Evidence command used during dispatch authoring:

```bash
rg -n "cashflow_snapshot.*baseline|baseline\\]" frontend-svelte backend/tests backend/app
```

It returned no direct consumer of `cashflow_snapshot.baseline` in frontend code.

### 3.5 Migration 039 - archive legacy Analytic-shaped baseline snapshots

PR-A3-4 must add a data-preserving migration because the payload shape changes under a table-level unique constraint on `as_of_date`.

Create `backend/alembic/versions/039_a3_cashflow_baseline_legacy_archive.py`.

The migration identifiers must be:

```python
revision = "039_a3_cashflow_baseline_legacy_archive"
down_revision = "038_a3_price_provenance"
```

Migration requirements:

- Create archive table `cashflow_baseline_snapshot_archives`.
- Archive table columns:
  - `id` UUID primary key, new archive row id.
  - `original_snapshot_id` UUID not null.
  - `as_of_date` Date not null.
  - `snapshot_data` JSON not null.
  - `total_net_cashflow` Numeric(18, 6) not null.
  - `inputs_hash` String(64), nullable.
  - `correlation_id` String(64) not null.
  - `original_created_at` DateTime(timezone=True), nullable.
  - `archived_at` DateTime(timezone=True), server default `func.now()`, not null.
  - `archive_reason` String(128) not null.
- Move only legacy Analytic-shaped rows:
  - `snapshot_data` contains root key `cashflow_items`, OR
  - `snapshot_data["view"]` is absent/not `"baseline"`.
- Insert those rows into the archive table with `archive_reason="PR-A3-4 legacy analytic-shaped baseline payload"`.
- Delete those moved rows from `cashflow_baseline_snapshots`.
- Leave already-new rows with `snapshot_data["view"] == "baseline"` untouched.
- Downgrade restores archived rows into `cashflow_baseline_snapshots` only when no active row exists for the same `as_of_date`; if an active row exists, downgrade must hard-fail with an explicit exception rather than silently overwrite.
- Restored rows must satisfy the `cashflow_baseline_snapshots.correlation_id` NOT NULL contract. If archived data has `correlation_id IS NULL`, downgrade must hard-fail with an explicit exception rather than inserting invalid data.

Use SQLAlchemy/Alembic APIs rather than PostgreSQL-only JSON operators unless the migration branches by dialect. This repo's migration tests run SQLite roundtrips.

For the archive `snapshot_data` column, follow the migration 038 JSON pattern:

```python
json_type = postgresql.JSONB() if bind.dialect.name == "postgresql" else sa.JSON()
```

Use `json_type` for `cashflow_baseline_snapshot_archives.snapshot_data` so PostgreSQL receives JSONB and SQLite tests receive generic JSON.

The downgrade `correlation_id IS NULL` guard is defensive against corrupted archive rows; live rows moved from `cashflow_baseline_snapshots` should already satisfy the source table's NOT NULL constraint.

`cd backend && python -m alembic heads` must return one head: `039_a3_cashflow_baseline_legacy_archive`.

---

## 4. Scope OUT

- Do not change `docs/governance.md`. PR #47 already declared Projection; PR-A3-4 is enforcement against existing governance.
- Do not refactor all cashflow services into a shared framework.
- Do not add a Scenario-vs-Baseline comparison feature.
- Do not persist Scenario outputs.
- Do not change the ledger ingestion API.
- Do not change settlement amount derivation rules from Wave 1.
- Do not touch PR-A3-5 / J-A3-OPUS-09 partially-settled P&L lifecycle logic.
- Do not relax hard-fail behavior for price lookup or unsupported ledger directions.
- Do not add any migration beyond the legacy Baseline archive migration 039.

---

## 5. Acceptance criteria

- [ ] `backend/app/services/cashflow_baseline_service.py` no longer imports `compute_cashflow_analytic`.
- [ ] `backend/app/services/cashflow_baseline_service.py` no longer contains `analytic.model_dump`.
- [ ] Baseline snapshot payload root contains exactly the institutional fields `view`, `as_of_date`, `unrealized_items`, `realized_ledger_entries`, `reconciliation`.
- [ ] `snapshot_data["view"] == "baseline"`.
- [ ] `snapshot_data["reconciliation"]["total_net_cashflow"] == snapshot.total_net_cashflow` after Decimal normalization.
- [ ] `snapshot_data["reconciliation"]["total_net_cashflow"] == realized_total_usd + unrealized_total_usd`.
- [ ] Realized ledger reconciliation signs `IN` as positive and `OUT` as negative.
- [ ] Realized ledger reconciliation includes all `CashFlowLedgerEntry` rows with `cashflow_date <= as_of_date`, regardless of `source_event_type`, and carries `source_event_type` into each payload row.
- [ ] Unsupported ledger direction hard-fails with HTTP 422; no silent ignore.
- [ ] Baseline unrealized items include `active` and `partially_settled` contracts; `settled` contracts are represented only through realized ledger entries.
- [ ] Baseline unrealized queries exclude rows with `deleted_at` set on both `HedgeContract` and `Order`.
- [ ] Scenario response no longer includes `cashflow_snapshot.baseline`.
- [ ] `backend/app/services/scenario_whatif_service.py` no longer contains `baseline=cashflow_analytic`.
- [ ] OpenAPI and `schema.d.ts` are regenerated and included if they change.
- [ ] `docs/governance.md` has no diff.
- [ ] Migration 039 archives legacy Analytic-shaped baseline snapshots before deleting active rows.
- [ ] Migration 039 downgrade hard-fails rather than overwriting active Baseline rows for the same `as_of_date`.
- [ ] `cd backend && python -m alembic heads` returns one head: `039_a3_cashflow_baseline_legacy_archive`.

Mechanical grep checks:

```bash
grep -n "compute_cashflow_analytic\|analytic.model_dump" backend/app/services/cashflow_baseline_service.py
grep -n "baseline=cashflow_analytic" backend/app/services/scenario_whatif_service.py
grep -n "baseline: CashFlowAnalyticResponse" backend/app/schemas/scenario.py
```

All three commands must return zero matches after the fix.

---

## 6. Required tests

Extend `backend/tests/test_cashflow_baseline_service.py`.

Before adding new tests, update existing Baseline tests that assume the old
Analytic-shaped payload. In particular,
`test_cashflow_baseline_per_row_provenance_quadruple_inside_snapshot_data`
currently reads:

```python
item = snapshot.snapshot_data["cashflow_items"][0]
```

Change it to read the new Baseline-owned key:

```python
item = snapshot.snapshot_data["unrealized_items"][0]
```

Keep the existing assertions for `price_source`, `price_symbol`,
`price_settlement_date`, and `price_value`; those provenance fields remain
inside each unrealized item. Do not leave any test that indexes
`snapshot_data["cashflow_items"]`, because PR-A3-4 explicitly removes that
Analytic-shaped root key from Baseline.

### 6.1 Baseline no longer proxies Analytic

Add a test that creates a baseline snapshot and asserts the new payload shape:

```python
def test_cashflow_baseline_snapshot_uses_baseline_payload_contract(client) -> None:
    _insert_price(settlement_date=date(2026, 1, 30), price_usd=110.0)
    _create_variable_sales_order(client, avg_entry_price=100.0)

    with SessionLocal() as session:
        snapshot = create_cashflow_baseline_snapshot(
            session, as_of_date=date(2026, 2, 1), correlation_id="c-1"
        )

    assert snapshot.snapshot_data["view"] == "baseline"
    assert set(snapshot.snapshot_data) == {
        "view",
        "as_of_date",
        "unrealized_items",
        "realized_ledger_entries",
        "reconciliation",
    }
    assert "cashflow_items" not in snapshot.snapshot_data
```

Also add a static boundary test if the project accepts source-inspection tests:

```python
def test_cashflow_baseline_service_does_not_import_analytic() -> None:
    source_path = Path(__file__).resolve().parents[1] / "app" / "services" / "cashflow_baseline_service.py"
    source = source_path.read_text()
    assert "compute_cashflow_analytic" not in source
    assert "analytic.model_dump" not in source
```

This is not style policing; it pins the constitutional boundary from J-A3-04.

### 6.2 Ledger reconciliation is persisted

Add a test that:

1. Creates an active hedge contract.
2. Seeds the required settlement price.
3. Calls `ingest_hedge_contract_settlement()` with derived fixed and float leg amounts.
4. Creates a Baseline snapshot with `as_of_date >= cashflow_date`.
5. Asserts both ledger entries appear in `snapshot_data["realized_ledger_entries"]`.
6. Asserts `realized_total_usd` equals signed ledger sum.
7. Asserts `total_net_cashflow` equals realized plus unrealized.

Use existing ledger tests in `backend/tests/test_cashflow_ledger_settlement.py` as fixture guidance. Do not duplicate an end-to-end settlement suite; this test only proves Baseline consumes ledger evidence and stores reconciliation.

### 6.3 Partially settled unrealized tail is included by Baseline

Add a test that creates a `HedgeContract(status=HedgeContractStatus.partially_settled)` with price evidence and no new settlement event, then creates a Baseline snapshot.

Assert:

- One unrealized item exists for that contract.
- The item carries price provenance.
- The item is not represented as a realized ledger entry unless ledger rows actually exist.

This closes the OPUS-08 edge where Analytic excludes non-active contracts while MTM supports partially-settled contracts.

Also add a deleted-row exclusion test:

- Create one active non-deleted contract/order that should appear in `unrealized_items`.
- Create one otherwise-eligible contract with `deleted_at` set.
- Create one otherwise-eligible variable order with `deleted_at` set.
- Create a Baseline snapshot.
- Assert only the non-deleted rows appear in `unrealized_items` and the deleted rows do not affect `reconciliation["unrealized_total_usd"]`.

### 6.4 Unsupported ledger direction hard-fails

Add a focused service test that inserts a `CashFlowLedgerEntry(direction="SIDEWAYS")` directly, then calls `create_cashflow_baseline_snapshot()`.

Assert:

- HTTP 422.
- Detail contains `Unsupported ledger direction`.

This protects the reconciliation invariant from silently dropping bad accounting rows.

### 6.5 Existing snapshot conflict still protects reconstruction

Adapt `test_snapshot_conflict_returns_409` if necessary so the conflict is against the new payload shape.

The behavior must remain:

- First create returns a persisted snapshot.
- If persisted `snapshot_data` or `total_net_cashflow` is mutated, second create for same `as_of_date` raises HTTP 409.
- Legacy Analytic-shaped snapshots are handled by migration 039 before service runtime. Do not add service-side silent rewrite of old `cashflow_items` payloads.

Also add or extend a deterministic-hash test so it proves canonical ordering is
part of the hash input for both payload arrays:

- `unrealized_items` sorted by `(object_type, object_id)`.
- `realized_ledger_entries` sorted by `(cashflow_date, hedge_contract_id, leg_id, source_event_id or "")`.

If a test inserts a direct ledger row with `source_event_id=None`, it must prove
the `source_event_id or ""` sort key is deterministic. Normal settlement-ledger
rows created by `ingest_hedge_contract_settlement()` should still carry a
non-null `source_event_id`.

### 6.6 Scenario no longer emits fake Baseline

Extend `backend/tests/test_scenario_whatif_run.py`.

Add or update:

```python
def test_scenario_cashflow_snapshot_has_no_fake_baseline(client) -> None:
    symbol = "LME_ALU_CASH_SETTLEMENT_DAILY"
    _insert_price(symbol, settlement_date=date(2026, 1, 29), price_usd=105.0)
    _insert_price(symbol, settlement_date=date(2026, 1, 30), price_usd=110.0)
    _insert_contract(quantity_mt=5.0, entry_price=100.0)

    response = client.post(
        "/scenario/what-if/run",
        json={
            "as_of_date": "2026-02-01",
            "period_start": "2026-01-01",
            "period_end": "2026-01-31",
            "deltas": [],
        },
    )

    assert response.status_code == 200
    cashflow = response.json()["cashflow_snapshot"]
    assert set(cashflow) == {"analytic"}
    assert "baseline" not in cashflow
```

Update any existing tests that assume `cashflow_snapshot.baseline` exists. Do not replace it with another fake field.

### 6.7 Migration archive coverage

Add `backend/tests/test_039_cashflow_baseline_legacy_archive_migration.py` or extend the migration roundtrip suite.

Required tests:

- Upgrade from revision 038 with one row in `cashflow_baseline_snapshots` whose `snapshot_data` root contains `cashflow_items`.
- Assert upgrade creates `cashflow_baseline_snapshot_archives`.
- Assert the legacy row is present in the archive table with the same `original_snapshot_id`, `as_of_date`, `snapshot_data`, `total_net_cashflow`, `inputs_hash`, and `correlation_id`.
- Assert the legacy row is removed from `cashflow_baseline_snapshots`.
- Assert a row whose `snapshot_data["view"] == "baseline"` remains active and is not archived.
- Assert downgrade restores archived rows only when no active row exists for that `as_of_date`.
- Assert downgrade hard-fails if restoring would overwrite an active row for the same `as_of_date`.
- Assert downgrade hard-fails if an archived row has `correlation_id IS NULL`.

---

## 7. Verification commands

Run focused tests first:

```bash
pytest backend/tests/test_cashflow_baseline_service.py backend/tests/test_scenario_whatif_run.py -v
```

Run cashflow adjacent tests:

```bash
pytest backend/tests/test_cashflow_analytic_service.py backend/tests/test_cashflow_ledger_service.py backend/tests/test_cashflow_ledger_settlement.py backend/tests/test_cashflow_projection_service.py backend/tests/test_cashflow_projection_routes.py -v
```

Run schema and migration checks:

```bash
cd backend && python -m alembic heads
cd ..
pytest backend/tests/test_039_cashflow_baseline_legacy_archive_migration.py -v
```

Regenerate OpenAPI and frontend schema:

```bash
cd backend && DATABASE_URL=sqlite:///:memory: SECRET_KEY=dummy JWT_SIGNING_SECRET=dummy AUDIT_HMAC_KEY=dummy AUDIT_SIGNING_KEY=test python -c "from app.main import app; import json; json.dump(app.openapi(), open('../docs/api/openapi_v1.json', 'w'), indent=2, sort_keys=True)"
cd ../frontend-svelte && OPENAPI_SOURCE=../docs/api/openapi_v1.json node scripts/regen-schema.mjs
```

Run diff/grep gates:

```bash
git diff --check
git diff -- docs/governance.md
grep -n "compute_cashflow_analytic\|analytic.model_dump" backend/app/services/cashflow_baseline_service.py
grep -n "baseline=cashflow_analytic" backend/app/services/scenario_whatif_service.py
grep -n "baseline: CashFlowAnalyticResponse" backend/app/schemas/scenario.py
```

Expected:

- `git diff --check` is clean.
- `git diff -- docs/governance.md` is empty.
- Each grep returns zero matches.

Then run the full backend suite:

```bash
pytest backend/tests/ -v
```

Known local baseline note: if the only failures are the existing Python 3.14 `backend/tests/test_ws.py` `asyncio.get_event_loop()` failures, report them as baseline noise with exact counts. Do not hide new cashflow/scenario failures behind that baseline.

---

## 8. Workflow

1. `git fetch origin`
2. `git worktree add D:/Projetos/Hedge-Control-New-pr-a3-4 origin/main`
3. `cd D:/Projetos/Hedge-Control-New-pr-a3-4`
4. `git checkout -b audit-a3/cashflow-boundaries-reconciliation`
5. `python scripts/install_git_hooks.py`
6. Confirm hook v2 active: `git config core.hooksPath` returns `.githooks`.
7. Read the jury sections for J-A3-04 and J-A3-OPUS-08 in full.
8. Implement Baseline-owned payload and reconciliation per sections 3.1-3.2.
9. Remove fake Scenario Baseline per section 3.3.
10. Add migration 039 per section 3.5 and its migration roundtrip/archive tests.
11. Regenerate OpenAPI/frontend schema per section 3.4.
12. Run focused tests first, then adjacent cashflow tests, migration tests, then full backend.
13. Push normally. Do not use `--no-verify` unless explicitly authorized by the orchestrator.
14. Open a PR against `main`. Do not auto-merge.
15. Wait for Codex Connector review. Adjudicate every catch by direct code reading before accepting or rejecting it.

---

## 9. PR shape

**Title:** `fix(audit-a3): PR-A3-4 - cashflow boundaries and baseline reconciliation`

**Body skeleton:**

```markdown
## Summary

Wave 4 of Phase A3 remediation. Closes J-A3-04 and J-A3-OPUS-08.

- Baseline snapshot creation no longer imports or calls Analytic.
- Baseline snapshot payload now has an explicit `view="baseline"` contract:
  `unrealized_items`, `realized_ledger_entries`, and `reconciliation`.
- Baseline reconciliation persists ledger realized-to-date evidence and proves
  `total_net_cashflow = unrealized_total_usd + realized_total_usd`.
- Scenario no longer emits `cashflow_snapshot.baseline` as a duplicate
  Analytic object.
- Migration 039 archives legacy Analytic-shaped baseline snapshots before
  deleting them from the active table, avoiding permanent 409 lock under the
  `as_of_date` unique constraint.
- OpenAPI and frontend schema regenerated for the Scenario response change.

## Files changed

- `backend/app/services/cashflow_baseline_service.py`
- `backend/app/schemas/scenario.py`
- `backend/app/services/scenario_whatif_service.py`
- `backend/alembic/versions/039_a3_cashflow_baseline_legacy_archive.py`
- `backend/tests/test_cashflow_baseline_service.py`
- `backend/tests/test_scenario_whatif_run.py`
- `backend/tests/test_039_cashflow_baseline_legacy_archive_migration.py`
- `docs/api/openapi_v1.json`
- `frontend-svelte/src/lib/api/schema.d.ts`

## Acceptance evidence

- [ ] Focused tests: include the exact command and pass/fail counts from this PR run.
- [ ] Adjacent cashflow tests: include the exact command and pass/fail counts from this PR run.
- [ ] Full backend: include the exact command and pass/fail counts; separate any known `test_ws.py` Python 3.14 baseline failures from regressions.
- [ ] `cd backend && python -m alembic heads`: `039_a3_cashflow_baseline_legacy_archive`
- [ ] Migration 039 roundtrip/archive tests: include command and pass/fail counts
- [ ] `git diff --check`: clean
- [ ] `git diff -- docs/governance.md`: empty
- [ ] grep `compute_cashflow_analytic|analytic.model_dump` in baseline service: zero matches
- [ ] grep `baseline=cashflow_analytic` in scenario service: zero matches
- [ ] grep `baseline: CashFlowAnalyticResponse` in scenario schema: zero matches

## Constitutional impact

Enforces cashflow view boundaries and output auditability under
`docs/governance.md` VALUATION/MTM/CASHFLOW, hard-fail, and output-contract
sections. No Constitution change in this PR.

## Out of scope

- P&L partially-settled lifecycle semantics (PR-A3-5 / J-A3-OPUS-09)
- Scenario-vs-Baseline comparison feature
- Ledger ingestion API changes
- Any migration beyond 039 legacy Baseline archive
- Any change to `docs/governance.md`

## Closes

J-A3-04 + J-A3-OPUS-08.
```

---

## 10. Constraints - what NOT to do

- Do not keep `compute_cashflow_analytic` in `cashflow_baseline_service.py`.
- Do not keep `analytic.model_dump()` as the Baseline payload source.
- Do not keep `ScenarioCashflowSnapshot.baseline` if it is just another `CashFlowAnalyticResponse`.
- Do not add a new fake baseline-like scenario field.
- Do not silently skip unsupported ledger directions.
- Do not include settled contracts in `unrealized_items`; settled flows belong in realized ledger evidence.
- Do not omit partially-settled contracts from Baseline unrealized items.
- Do not mutate existing snapshots to the new shape; conflicting persisted snapshots must continue to return HTTP 409.
- Do not modify `docs/governance.md`.
- Do not omit migration 039; old Analytic-shaped Baseline rows must be preserved and removed from the active table before the new Baseline shape can be created for the same `as_of_date`.
- Do not silently rewrite old `snapshot_data["cashflow_items"]` payloads into the new Baseline shape.
- Do not delete legacy baseline rows without archiving them first.
- Do not use `--no-verify` or `--force`.
- Do not auto-merge.

---

## 11. Final report shape

When complete, report back with:

- Branch, PR URL, final SHA.
- Files touched, grouped by service/schema/test/generated.
- Focused test counts and adjacent cashflow test counts.
- Full backend test count, with baseline failures separated from regressions.
- Codex Connector review state and catches absorbed/rejected.
- Hook v2 artifact path and `tool_calls` summary.
- Grep evidence for the three zero-match boundary checks.
- `docs/governance.md` zero-diff evidence.
- OpenAPI/frontend schema regeneration evidence.
- Migration 039 archive and downgrade evidence.

Keep the report under 600 words.
