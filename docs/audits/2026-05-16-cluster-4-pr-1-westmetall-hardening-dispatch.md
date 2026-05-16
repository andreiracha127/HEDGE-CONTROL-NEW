# Cluster 4 Implementation Dispatch — PR-CL4-1 — Westmetall Hardening + Market-Data Governance Wiring

**Cluster:** 4 — Market-Data Governance (D-4.1 closure)
**Wave:** PR-CL4-1 (1 of 1; institutionally final A1-A6 jury deferral)
**Authoring date:** 2026-05-16
**Repository:** `D:/Projetos/Hedge-Control-New`
**Base branch:** `main` (HEAD `05ffa2f8e` post-PR #86, the MARKET-DATA GOVERNANCE appendix)
**Required branch:** `audit-followup/cluster-4-westmetall-hardening`
**Source-of-truth:** `docs/governance.md` MARKET-DATA GOVERNANCE section (lines 442-748 at HEAD `05ffa2f8e`); supersedes any per-provider deviation in code.

## 1. Objective

Retire all 6 anomalies enumerated under `docs/governance.md` § "Anomalies to be retired upon Cluster 4 implementation closure" (lines 690-746 at HEAD `05ffa2f8e`) and wire the supporting infrastructure mandated by the binding subsections (Provider trust matrix, Replay-window invariant, Stale-feed detection invariant, Canonical price reconciliation invariant, Precision contract invariant, Audit-trail attribution).

Six coupled deliverables:

1. **Market-data governance service module** (`backend/app/services/market_data_governance.py`) — new module hosting tier lookup, replay-window helpers, sequence-monotonicity helpers, bulk-idempotency-vs-replay classifier, canonical-provider lookup, drift computation, and structured-log-event emission. Forward-looking: all live-single-event helpers exist now even where no current path invokes them, so a future provider with a true streaming POST endpoint can wire in without re-opening governance.
2. **Bulk idempotency hardening (anomaly #2 — bulk distinction)** — refactor `cash_settlement_prices.py:30-53` and `:99-144` to enforce the **row-level** `price_usd` content comparison mandated by governance §"Bulk idempotency vs replay distinction" (lines 535-555): matching `price_usd` → info-level `market_data_bulk_idempotent_skip`; differing `price_usd` for the same `(source, symbol, settlement_date)` → `market_data_replay_rejected` reason `bulk_content_mismatch` + raise (do NOT persist). The `html_sha256` whole-page hash MUST NOT participate in the row idempotency decision (it mutates every time the provider publishes any new row and would silently mask real replay attempts).
3. **Precision contract enforcement (anomaly #5)** — refactor `westmetall_cash_settlement.py:169-177` `_parse_float` → `_parse_price_decimal(raw: str) -> Decimal | None`. Reject float inputs at the parser boundary (TypeError raised at function entry when a non-`str` is passed). Normalize locale artifacts BEFORE Decimal construction. Construct via `Decimal(str(normalized))`. Promote `WestmetallDailyRow.price_usd` from `float` to `Decimal`. Update `cash_settlement_prices.py:46, :125` row constructors to consume the `Decimal` directly. No `Decimal(float(...))` anywhere in the ingest path.
4. **Canonical-vs-audit segregation (anomaly #4)** — alembic revision `045_market_data_governance_columns` adds `is_canonical: BOOLEAN NOT NULL DEFAULT TRUE` to `cash_settlement_prices`, backfills existing rows to `True`. Add `MARKET_DATA_CANONICAL_PROVIDER_<INSTRUMENT>` env-var lookup (default `westmetall` for `LME_ALU_CASH_SETTLEMENT_DAILY`). Set `is_canonical = (provider == canonical_provider_for_instrument(instrument))` on insert. Today every Westmetall row remains canonical; the path is now ready to accept a second `trusted` provider as `audit_only` without a follow-up schema change. **Crucially, update `backend/app/services/price_lookup_service.py:100-110` (and `backend/app/utils/market_calendar.py:173-179`) to filter reads by `is_canonical=True` instead of relying on the hard-coded `_canonical_source_for_symbol` map.**
5. **Stale-feed detection job (anomaly #3)** — new module `backend/app/tasks/market_data_staleness_task.py` registered with the existing scheduler. Per-pair `max_gap_hours` config (default for `westmetall:LME_ALU_CASH_SETTLEMENT_DAILY = 96h` to accommodate weekend gap on Friday cash settlement). Background job at `MARKET_DATA_STALENESS_CHECK_INTERVAL_MINUTES` cadence (default 15) computes `now - last_ingest_at` per `(provider, instrument)` pair; emits `market_data_stale_feed` warning when the gap exceeds the per-pair threshold. Alerting-only; never blocks ingest.
6. **Drift-alerting infrastructure scaffold (anomaly #6) + audit-trail metadata expansion** — `MARKET_DATA_DRIFT_THRESHOLD_<INSTRUMENT>` config (default `0.01` = 1%). `compute_normalized_drift(canonical, audit)` helper (zero-guard). `emit_drift_alert_if_breach(...)` orchestration wired into the ingest path after every audit-only row insert, performing `(instrument, observation_key)` match against the canonical row and deferring computation when canonical row is absent (per governance §"Canonical price reconciliation"). For `cash_settlement_prices`, the canonical `observation_key` is `settlement_date`; the binding's `observation_timestamp` and `tenor+fix_date` alternatives are declared in code (config lookup table) for future-provider readiness but no current row uses them. Today no audit-only provider exists, so the path is unreachable; tested via fixture-synthesized audit row.

Plus mandatory:

- Replay-window helpers (anomaly #1 — must be invoked by the single-date `POST /aluminum/cash-settlement/ingest` route; only bulk/scheduler paths are exempt).
- Sequence-monotonicity helpers + `market_data_sequence_tracker` table (anomaly #2 — must be invoked by the single-date `POST /aluminum/cash-settlement/ingest` route).
- Audit-event metadata expansion: every market-data ingest path persists `provider`, `instrument`, `provider_timestamp`, `sequence_number` (or stable bulk key `(source, symbol, settlement_date)` for exempted paths), `tier_at_ingest_time` (frozen lookup), `is_canonical` per governance §"Audit-trail attribution" (lines 673-688).

The MARKET-DATA GOVERNANCE section is canonical (`docs/governance.md:451-452`: "This section is the constitutional contract. Per-provider deviations require amendment of this section, NOT silent config overrides in code."). Code MUST conform.

## 2. Non-Negotiable Constraints

- Do **not** edit `docs/governance.md`. The contract landed in PR #86; this wave implements it.
- Do **not** introduce a second provider. Westmetall remains the sole `trusted` provider per governance "Current providers" (`docs/governance.md:489-498`). Drift / audit-only paths are scaffolded but not instantiated.
- Do **not** change `Numeric(18, 6)` storage precision (`backend/app/models/market_data.py:24`). Governance binding declares this the reference shape (`docs/governance.md:649`).
- Do **not** convert any market-data price via `Decimal(float(...))` or `float(...)` anywhere in the ingest/storage pipeline. The governance binding forbids it (`docs/governance.md:640-644`).
- Do **not** use `html_sha256` (or any page-level whole-document hash) in row-level idempotency decisions. Governance forbids it explicitly (`docs/governance.md:539-541`). `html_sha256` remains in `cash_settlement_prices.html_sha256` as audit evidence per row only — it is NEVER read for replay classification.
- Do **not** add a timestamp-tolerance check on the scheduler daily run or `ingest_westmetall_cash_settlement_bulk`. Both are exempt per the binding's Backfill exemption (`docs/governance.md:512-521`) and Bulk exemption (`docs/governance.md:528-533`). Adding a timestamp guard to those paths would reject legitimate multi-year backfills and contradict the governance contract.
- Do **not** add sequence-monotonicity checks on the scheduler or bulk paths. Same exemption.
- Do **not** widen scope into other clusters' territory. nginx MUST receive zero diff. Clerk/JWT/cookie/CSP layers (Cluster 3) MUST receive zero diff. **Frontend exception (PR #87 hook P1)**: the only permitted frontend diff is the auto-generated OpenAPI types file (typically `frontend-svelte/src/lib/api/schema.d.ts` or equivalent — verify path with `rg -nP "is_canonical|CashSettlementPriceRead" frontend-svelte/src/lib/api/`). The additive `is_canonical: boolean` field on `CashSettlementPriceRead` / `CashSettlementIngestResponse` / `CashSettlementBulkIngestResponse` MUST regenerate into the typed client so frontend consumers can read the flag. Any non-additive frontend change (UI components, business logic, formatters) remains out of scope.
- Do **not** add new IdP integration, new role, or new service identity beyond the existing `service:westmetall_ingest`. The actor_sub plumbing extends the metadata of the existing identity; it does NOT create a new one.
- Do **not** pre-convert currency at ingest. Governance forbids it (`docs/governance.md:666-671`).
- Do **not** rename `cash_settlement_prices`, `CashSettlementPrice`, `WestmetallDailyRow`, or break the `westmetall_ingest` service-identity contract. Cluster 3 PR-CL3-1 hardened these names.

## 3. Findings and Evidence

Verified at HEAD `05ffa2f8e`.

### 3.1 Constitutional source-of-truth (PR #86 landing)

`docs/governance.md` MARKET-DATA GOVERNANCE section (lines 442-748):

- §"Provider trust matrix" (lines 454-498) — 3 tiers + Westmetall classified `trusted`.
- §"Replay-window invariant" (lines 500-566) — timestamp-tolerance + sequence-monotonicity combo + Backfill exemption + Bulk exemption + Bulk idempotency vs replay distinction + structured-log-event field contract.
- §"Stale-feed detection invariant" (lines 568-586) — per-instrument `max_gap_hours` + `MARKET_DATA_STALENESS_CHECK_INTERVAL_MINUTES` job + `market_data_stale_feed` event.
- §"Canonical price reconciliation invariant" (lines 588-629) — single `canonical_provider` per instrument + drift on `(instrument, observation_key)` match + `MARKET_DATA_DRIFT_THRESHOLD_<instrument>` config + `market_data_drift_alert` event.
- §"Precision contract invariant" (lines 631-671) — string-first Decimal construction + `Numeric(18, 6)` storage + display-layer rounding + ingest-time-currency-conversion forbidden.
- §"Audit-trail attribution" (lines 673-688) — expanded metadata fields on every ingest event.
- §"Anomalies to be retired" (lines 690-746) — the 6 closure targets.

### 3.2 Current market-data ingest surface

**Routes** (`backend/app/api/routes/westmetall.py` at HEAD `05ffa2f8e`):

- `POST /aluminum/cash-settlement/ingest` (line 120-170) — single-date ingest. Gated by `require_service_identity("westmetall_ingest")` at `:135`. Calls `ingest_westmetall_cash_settlement_daily_for_date(session, payload.settlement_date)`.
- `POST /aluminum/cash-settlement/ingest-bulk` (line 173-236) — multi-date ingest. Gated by `require_service_identity("westmetall_ingest")` at `:188`. Calls `ingest_westmetall_cash_settlement_bulk(session, start_date, end_date)`.
- `GET /aluminum/cash-settlement/prices` (line 89-117) — list/read endpoint; out of scope.

Both POST routes structurally fetch the entire Westmetall page and filter to the requested scope. Per governance §"Backfill exemption" (`docs/governance.md:512-521`) and §"Bulk exemption" (`docs/governance.md:528-533`), the scheduler invocation of `ingest_westmetall_cash_settlement_bulk` is exempt from both timestamp tolerance and sequence monotonicity. However, the single-date `POST /ingest` route is **NOT** exempt under the current governance text. The dispatch executor MUST update the single-date route (`POST /aluminum/cash-settlement/ingest`) to explicitly invoke the `check_replay_window` and `check_sequence_monotonicity` helpers before persisting the row, ensuring it enforces the mandated live-path checks to fully retire anomalies #1 and #2. Both POST paths thus receive: bulk idempotency hardening (anomaly #2 bulk distinction), canonical-vs-audit segregation, audit metadata expansion.

**Service module** (`backend/app/services/westmetall_cash_settlement.py` at HEAD `05ffa2f8e`):

- `_parse_float(value: str) -> float | None` at lines 169-177 — current float parser. Strips `\xa0` (nbsp), spaces, and `,` (thousands separator). Constructs via `float(cleaned)`. The output is a binary float; governance forbids this at the parser boundary (`docs/governance.md:640-646`).
- `WestmetallDailyRow` dataclass at lines 95-99 — `price_usd: float` field. Must be promoted to `Decimal`.
- `parse_westmetall_daily_rows(html: bytes) -> list[WestmetallDailyRow]` at lines 184-209 — invokes `_parse_float`. Must consume the new `_parse_price_decimal`.

**Persistence helper** (`backend/app/services/cash_settlement_prices.py` at HEAD `05ffa2f8e`):

- `ingest_westmetall_cash_settlement_daily_for_date` (lines 20-53) — current row constructor at `:42-49`. Idempotency check at `:30-40` skips existing-date row but does NOT compare `price_usd`. Per governance §"Bulk idempotency vs replay distinction" this is a binding violation: differing `price_usd` for the same `(source, symbol, settlement_date)` MUST be rejected as `bulk_content_mismatch`, not silently skipped.
- `ingest_westmetall_cash_settlement_bulk` (lines 72-144) — row constructor at `:121-129`. Idempotency check at `:99-120` uses `set(existing_dates)` and skips matching rows without `price_usd` comparison. Same binding violation.
- `_westmetall_batch_uuid` (lines 56-69) — batch UUID derived from `html_sha256`. UNCHANGED; this is batch-level audit evidence, not row-level idempotency.

**Model** (`backend/app/models/market_data.py` at HEAD `05ffa2f8e`):

- `CashSettlementPrice` (lines 13-30). Column `price_usd: Mapped[Decimal] = mapped_column(Numeric(18, 6), nullable=False)` at `:24` — storage shape compliant with governance §"Precision contract" `:649`. UNCHANGED.
- Column `html_sha256: Mapped[str] = mapped_column(String(length=64), nullable=False)` at `:27` — per-row evidence (the page hash WHEN this row was ingested). UNCHANGED; never read for row idempotency classification.
- New column to add via alembic `045`: `is_canonical: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=true())`.

**Scheduler** (`backend/app/tasks/westmetall_task.py` at HEAD `05ffa2f8e`):

- `run_westmetall_ingestion()` (lines 29-83) — calls `ingest_westmetall_cash_settlement_bulk(session)` with no date range. Per binding, this is the canonical Backfill+Bulk exempt invocation path. Audit attribution at `:45-58` uses `AuditTrailService.record_worker_event` with `metadata={"actor_sub": "service:westmetall_ingest", "inserted_ids": [...], "source_url": ..., "html_sha256": ...}`. The metadata MUST be expanded with the new governance fields per §"Audit-trail attribution".

**Existing tests touching ingest path** (sweep `rg -nP 'westmetall|cash_settlement' backend/tests` performed; the executor MUST re-run and adjust each):

- `backend/tests/test_phase4_step1_cash_settlement_prices.py` — fixture-driven daily+bulk ingest tests. Likely needs price assertions to switch from float to Decimal and idempotency expectations to switch from silent skip to explicit-skip-event-or-reject.
- `backend/tests/test_westmetall_task.py` — scheduler smoke tests. Likely needs the audit metadata assertions extended.
- `backend/tests/test_pnl_price_evidence.py` — downstream consumer; verify `Decimal` flow still works.
- `backend/tests/test_price_lookup_service.py` — downstream consumer; verify.

### 3.3 Existing audit-trail surface

- `mark_audit_success(request, entity_id, *, metadata=None)` at `backend/app/api/dependencies/audit.py` (verify with `rg -nP 'def mark_audit_success' backend/app/api/dependencies/audit.py`) — accepts arbitrary metadata dict. Already wired in `westmetall.py:147-151, :202-218`. The expansion below ADDS keys; the helper signature stays unchanged.
- `AuditTrailService.record_worker_event(session, *, entity_type, entity_id, event_type, actor, source, metadata)` at `backend/app/services/audit_trail_service.py` (verify the exact signature) — used by `westmetall_task.py:45`. Same pattern.

### 3.4 Existing scheduler infrastructure

The Westmetall daily task is wired via the existing scheduler (`backend/app/scheduler.py` or equivalent; verify via `rg -nP "run_westmetall_ingestion|westmetall_task" backend/app/`). The new `market_data_staleness_task` MUST register alongside it on the SAME scheduler instance, no new scheduling primitive.

### 3.5 Anomaly inventory (per governance.md, with line citations)

The 6 enumerated anomalies in §"Anomalies to be retired" (`docs/governance.md:690-746`), with closure mapping:

| # | Governance citation | Current code | Closure |
|---|---|---|---|
| 1 | `:692-702` Replay-window check missing on non-exempt live single-event POST paths | Single-date POST path lacks replay-window check | Add `check_replay_window` helper in `market_data_governance.py` and invoke it in the `POST /aluminum/cash-settlement/ingest` single-date route. Only bulk/scheduler paths are exempt. |
| 2 | `:704-709` Sequence number tracking missing for live single-event ingest paths | Single-date POST path lacks sequence monotonicity check | Add `check_sequence_monotonicity` helper + `market_data_sequence_tracker` table via alembic 045, and invoke it in the `POST /aluminum/cash-settlement/ingest` single-date route. **Plus**: harden the existing bulk-style stable-key idempotency check to enforce §"Bulk idempotency vs replay distinction" (`price_usd` comparison; matching → `market_data_bulk_idempotent_skip`; differing → `market_data_replay_rejected` reason `bulk_content_mismatch`). |
| 3 | `:711-715` No background staleness-check job | None exists | Add `backend/app/tasks/market_data_staleness_task.py` + per-pair `max_gap_hours` config + `MARKET_DATA_STALENESS_CHECK_INTERVAL_MINUTES` cadence. Emit `market_data_stale_feed` warning when gap exceeds threshold. Westmetall+LME_ALU_CASH_SETTLEMENT_DAILY default `max_gap_hours = 96` (allows for Friday-to-Monday weekend gap). |
| 4 | `:717-723` No canonical-vs-audit segregation | `cash_settlement_prices` has no `is_canonical` column | Alembic 045 adds `is_canonical: BOOLEAN NOT NULL DEFAULT TRUE`. Add `MARKET_DATA_CANONICAL_PROVIDER_<INSTRUMENT>` config. Insert path sets `is_canonical = (provider == canonical_provider_for_instrument(instrument))`. Today every Westmetall row remains canonical. |
| 5 | `:725-734` Live float parser at `westmetall_cash_settlement.py:169-175` + row constructor at `cash_settlement_prices.py:42-47` | `_parse_float` returns `float`; `WestmetallDailyRow.price_usd: float`; row constructor consumes `float` directly | Rename to `_parse_price_decimal(value: str) -> Decimal \| None`. Raise `TypeError` at entry when `not isinstance(value, str)`. Normalize locale artifacts (nbsp, thousands separator, decimal-comma, whitespace) BEFORE Decimal construction. Construct via `Decimal(str(normalized))`. Promote `WestmetallDailyRow.price_usd: Decimal`. Row constructors at `cash_settlement_prices.py:46, :125` consume `Decimal` directly (no conversion). |
| 6 | `:736-741` Drift-alerting infrastructure absent | None exists | Add `MARKET_DATA_DRIFT_THRESHOLD_<INSTRUMENT>` config (default `0.01` = 1%). Add `compute_normalized_drift(canonical, audit)` helper (zero-guard for canonical_price == 0). Wire into ingest path after every `is_canonical=False` row insert: look up canonical row for same `(instrument, observation_key)`; if absent, defer; if found, compute drift; if `> threshold`, emit `market_data_drift_alert` per §"Canonical price reconciliation" `:613-619`. Today no audit-only provider exists → path unreachable in production; tested via synthesized fixture row. |

### 3.6 Anomaly preamble — additional gap sweep

Governance §"Anomalies to be retired" closes with (`docs/governance.md:743-746`):

> This list is documented; the route sweep in PR-CL4-1 dispatch §6 mandates implementation MUST also discover any additional gap not enumerated here and include it in the implementation scope with a PR-body note.

The executor MUST perform `rg -nP "@router\\.(post|patch|put|delete)" backend/app/api/routes/` and identify any market-data-relevant mutation route not covered above. Findings (if any) MUST be added to the implementation scope of this PR with an inline PR-body note. The current expectation is zero additional findings (market-data ingest is concentrated in `westmetall.py`), but the sweep is mandatory and the result MUST be documented in the PR body regardless of outcome.

Additionally: sweep `rg -nP "Decimal\\(\\s*float" backend/app/` and `rg -nP "float\\(.*price" backend/app/services/` to identify any latent float→Decimal contamination outside the Westmetall path. Any finding outside the ingest scope is documented in the PR body as deferred (not in PR-CL4-1 scope) unless it touches the active Westmetall ingest path — in which case it is in scope.

## 4. Required Implementation Boundary

### 4.1 New module: `backend/app/services/market_data_governance.py`

Add a new module hosting all governance helpers. Structure:

```python
"""Market-data governance helpers — per docs/governance.md MARKET-DATA GOVERNANCE
(lines 442-748 at HEAD 05ffa2f8e).

Per-provider deviations require constitutional amendment of the governance
section, NOT silent override in this module.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from typing import Literal, Optional

import structlog

from app.core.utils import now_utc

logger = structlog.get_logger(__name__)


# ── Tier classification (governance §"Provider trust matrix") ─────────────

ProviderTier = Literal["trusted", "conditional", "quarantine"]

_PROVIDER_TIER_REGISTRY: dict[str, ProviderTier] = {
    # Today: only Westmetall exists. Tier transitions are constitutional amendments.
    "westmetall": "trusted",
}


def tier_for_provider(provider: str) -> ProviderTier:
    """Return the constitutional tier for a provider.

    Raises ValueError for unknown providers — silent default would mask
    tier-classification gaps. New providers MUST land via governance amendment
    + addition to _PROVIDER_TIER_REGISTRY in the same PR.
    """
    try:
        return _PROVIDER_TIER_REGISTRY[provider]
    except KeyError as exc:
        raise ValueError(
            f"Provider {provider!r} has no constitutional tier classification. "
            f"Tier assignments require amendment of docs/governance.md "
            f"§'Provider trust matrix'."
        ) from exc


# ── Canonical provider lookup (governance §"Canonical price reconciliation") ──

_CANONICAL_PROVIDER_FALLBACK: dict[str, str] = {
    # Default canonical assignments; per-deployment override via
    # MARKET_DATA_CANONICAL_PROVIDER_<INSTRUMENT> env var.
    "LME_ALU_CASH_SETTLEMENT_DAILY": "westmetall",
}


def canonical_provider_for_instrument(instrument: str) -> str:
    """Return the canonical provider for an instrument.

    Resolution order:
    1. Env var MARKET_DATA_CANONICAL_PROVIDER_<INSTRUMENT> (uppercased).
    2. _CANONICAL_PROVIDER_FALLBACK.
    3. Raise ValueError — never default silently.
    """
    env_key = f"MARKET_DATA_CANONICAL_PROVIDER_{instrument.upper()}"
    override = os.environ.get(env_key)
    if override:
        return override.strip().lower()
    try:
        return _CANONICAL_PROVIDER_FALLBACK[instrument]
    except KeyError as exc:
        raise ValueError(
            f"Instrument {instrument!r} has no canonical provider. "
            f"Set {env_key} or add to _CANONICAL_PROVIDER_FALLBACK in the same "
            f"PR that introduces ingest for this instrument."
        ) from exc


def is_canonical(provider: str, instrument: str) -> bool:
    """True iff provider is the canonical provider for instrument."""
    return provider.lower() == canonical_provider_for_instrument(instrument).lower()


# ── Replay-window helpers (governance §"Replay-window invariant") ──────────

DEFAULT_REPLAY_WINDOW_MINUTES = 30


def replay_window_minutes_for(provider: str) -> int:
    """Per-provider replay window override; falls back to global default."""
    env_key = f"MARKET_DATA_REPLAY_WINDOW_{provider.upper()}_MINUTES"
    if override := os.environ.get(env_key):
        return int(override)
    global_env = os.environ.get("MARKET_DATA_REPLAY_WINDOW_MINUTES")
    if global_env:
        return int(global_env)
    return DEFAULT_REPLAY_WINDOW_MINUTES


class ReplayWindowViolation(Exception):
    """Raised by check_replay_window when provider_timestamp is outside the
    tolerance window. Callers map to HTTPException(400) at the route boundary.

    Forward-looking: today no live single-event POST path exists, so no
    production code raises this exception. The helper exists so a future
    streaming POST endpoint can wire in without re-opening governance.
    """


def check_replay_window(
    *,
    provider: str,
    instrument: str,
    provider_timestamp: datetime,
    sequence_number: int,
    actor_sub: str,
    now: Optional[datetime] = None,
) -> None:
    """Enforce timestamp tolerance for a live single-event ingest.

    Bulk and scheduler paths are exempt per governance §"Backfill exemption"
    and §"Bulk exemption" — do NOT call this helper from those paths.
    """
    server_now = now or now_utc()
    if provider_timestamp.tzinfo is None:
        logger.warning(
            "market_data_replay_rejected",
            provider=provider,
            instrument=instrument,
            provider_timestamp=provider_timestamp.isoformat(),
            sequence_number=sequence_number,
            reason="naive_timestamp",
            actor_sub=actor_sub,
        )
        raise ReplayWindowViolation("provider_timestamp must be timezone-aware")
    window = timedelta(minutes=replay_window_minutes_for(provider))
    delta = abs(server_now - provider_timestamp)
    if delta > window:
        logger.warning(
            "market_data_replay_rejected",
            provider=provider,
            instrument=instrument,
            provider_timestamp=provider_timestamp.isoformat(),
            sequence_number=sequence_number,
            reason="timestamp_out_of_window",
            actor_sub=actor_sub,
            window_minutes=window.total_seconds() / 60,
            delta_seconds=delta.total_seconds(),
        )
        raise ReplayWindowViolation(
            f"provider_timestamp {provider_timestamp.isoformat()} outside "
            f"{window} tolerance from server_now"
        )


# ── Sequence monotonicity helpers (governance §"Sequence number monotonicity") ──

class SequenceMonotonicityViolation(Exception):
    """Raised by check_sequence_monotonicity. Bulk/scheduler paths exempt."""


def check_sequence_monotonicity(
    db,  # sqlalchemy Session — typed loosely to avoid circular import
    *,
    provider: str,
    instrument: str,
    sequence_number: int,
    provider_timestamp: datetime,
    actor_sub: str,
) -> None:
    """Enforce strict-greater-than sequence ordering for live single-event ingest.

    Requires market_data_sequence_tracker table (alembic 045).
    Bulk and scheduler paths are exempt — do NOT call from those paths.

    Same-sequence re-ingest → SequenceMonotonicityViolation with reason
        `sequence_duplicate`.
    Out-of-order (sequence_number < last_seen) → SequenceMonotonicityViolation
        with reason `sequence_not_monotonic`.
    """
    from app.models.market_data import MarketDataSequenceTracker

    tracker = (
        db.query(MarketDataSequenceTracker)
        .filter(
            MarketDataSequenceTracker.provider == provider,
            MarketDataSequenceTracker.instrument == instrument,
        )
        .with_for_update()
        .one_or_none()
    )
    last_seen = tracker.last_sequence if tracker else None

    if last_seen is not None:
        if sequence_number == last_seen:
            reason = "sequence_duplicate"
        elif sequence_number < last_seen:
            reason = "sequence_not_monotonic"
        else:
            reason = None
        if reason:
            logger.warning(
                "market_data_replay_rejected",
                provider=provider,
                instrument=instrument,
                provider_timestamp=provider_timestamp.isoformat(),
                sequence_number=sequence_number,
                last_seen_sequence=last_seen,
                reason=reason,
                actor_sub=actor_sub,
            )
            raise SequenceMonotonicityViolation(
                f"sequence_number {sequence_number} {reason} "
                f"(last_seen={last_seen})"
            )

    # Advance the tracker. Caller MUST commit the session for this to persist.
    if tracker is None:
        db.add(
            MarketDataSequenceTracker(
                provider=provider,
                instrument=instrument,
                last_sequence=sequence_number,
            )
        )
    else:
        tracker.last_sequence = sequence_number


# ── Bulk idempotency classifier (governance §"Bulk idempotency vs replay distinction") ──

BulkIdempotencyOutcome = Literal["idempotent_skip", "content_mismatch"]


def classify_bulk_row_replay(
    *,
    new_price_usd: Decimal,
    existing_price_usd: Decimal,
) -> BulkIdempotencyOutcome:
    """Compare new vs stored row price for stable-key bulk paths.

    Per governance §"Bulk idempotency vs replay distinction":
    - prices match → idempotent skip (caller emits market_data_bulk_idempotent_skip)
    - prices differ → content mismatch (caller emits market_data_replay_rejected
      reason=bulk_content_mismatch and raises BulkContentMismatch — row NOT
      persisted; operator review required)

    Compares Decimal values directly. Float inputs are rejected at the parser
    boundary by _parse_price_decimal in westmetall_cash_settlement.py, so both
    inputs are Decimal by contract.

    Uses == on Decimals (exact equality). NOT a tolerance-based compare —
    governance forbids that for replay classification because legitimate
    provider re-publishes are byte-identical; any byte-level difference is
    a real mismatch.
    """
    if not isinstance(new_price_usd, Decimal):
        raise TypeError(
            f"classify_bulk_row_replay requires Decimal new_price_usd, "
            f"got {type(new_price_usd).__name__}"
        )
    if not isinstance(existing_price_usd, Decimal):
        raise TypeError(
            f"classify_bulk_row_replay requires Decimal existing_price_usd, "
            f"got {type(existing_price_usd).__name__}"
        )
    return "idempotent_skip" if new_price_usd == existing_price_usd else "content_mismatch"


class BulkContentMismatch(Exception):
    """Raised when a bulk-path row collides on the stable key with a stored
    row whose price_usd differs. Per governance, the row is NOT persisted.
    """


def emit_bulk_idempotent_skip(
    *,
    provider: str,
    instrument: str,
    settlement_date,
    actor_sub: str,
) -> None:
    """Info-level event when a bulk-path row matches the stored row exactly.

    Per governance: this is normal operation (scheduler re-encounters every
    settled date each run), NOT a rejection. No 'reason' field.
    """
    logger.info(
        "market_data_bulk_idempotent_skip",
        provider=provider,
        instrument=instrument,
        source=provider,
        symbol=instrument,
        settlement_date=settlement_date.isoformat(),
        actor_sub=actor_sub,
    )


def emit_bulk_content_mismatch_rejection(
    *,
    provider: str,
    instrument: str,
    settlement_date,
    new_price_usd: Decimal,
    existing_price_usd: Decimal,
    actor_sub: str,
) -> None:
    """Warning-level event when a bulk-path row collides with a stored row
    whose price_usd differs. Caller MUST also raise BulkContentMismatch.

    Per governance §"Bulk idempotency vs replay distinction": this is the
    malicious-replay / silent-data-tampering case the binding guards against.
    """
    logger.warning(
        "market_data_replay_rejected",
        provider=provider,
        instrument=instrument,
        source=provider,
        symbol=instrument,
        settlement_date=settlement_date.isoformat(),
        reason="bulk_content_mismatch",
        new_price_usd=str(new_price_usd),
        existing_price_usd=str(existing_price_usd),
        actor_sub=actor_sub,
    )


# ── Drift computation (governance §"Canonical price reconciliation") ──────

def drift_threshold_for(instrument: str) -> Decimal:
    """Per-instrument drift threshold (normalized fraction). Default 0.01 (1%)."""
    env_key = f"MARKET_DATA_DRIFT_THRESHOLD_{instrument.upper()}"
    if override := os.environ.get(env_key):
        return Decimal(override)
    return Decimal("0.01")


def compute_normalized_drift(
    *, canonical_price: Decimal, audit_price: Decimal
) -> Optional[Decimal]:
    """Return abs(canonical - audit) / canonical.

    Zero-guard: returns None when canonical_price == 0 (cannot normalize;
    operator must inspect manually). Caller treats None as "cannot compute,
    do not alert" — alerting on undefined drift would generate noise.
    """
    if canonical_price == 0:
        return None
    return abs(canonical_price - audit_price) / canonical_price


def emit_drift_alert_if_breach(
    *,
    instrument: str,
    observation_key: str,
    canonical_provider: str,
    audit_provider: str,
    canonical_price: Decimal,
    audit_price: Decimal,
) -> bool:
    """Compute normalized drift; emit market_data_drift_alert if > threshold.

    Returns True if alert was emitted, False otherwise. Today: never invoked
    in production (no audit-only provider exists); tested via synthesized
    fixture row.
    """
    drift = compute_normalized_drift(
        canonical_price=canonical_price, audit_price=audit_price
    )
    if drift is None:
        return False
    threshold = drift_threshold_for(instrument)
    if drift <= threshold:
        return False
    logger.warning(
        "market_data_drift_alert",
        instrument=instrument,
        observation_key=observation_key,
        canonical_provider=canonical_provider,
        audit_provider=audit_provider,
        canonical_price=str(canonical_price),
        audit_price=str(audit_price),
        normalized_drift=str(drift),
        threshold=str(threshold),
    )
    return True


# ── Stale-feed detection helpers (governance §"Stale-feed detection invariant") ──

_STALENESS_FALLBACK: dict[tuple[str, str], int] = {
    # (provider, instrument): max_gap_hours
    ("westmetall", "LME_ALU_CASH_SETTLEMENT_DAILY"): 96,
    # 96h allows for a 3-day weekend gap (Friday to Monday is ~72h + 24h margin)
    # without false alarms. Per-deployment override via
    # MARKET_DATA_MAX_GAP_HOURS_<PROVIDER>_<INSTRUMENT>.
}


def max_gap_hours_for(provider: str, instrument: str) -> int:
    env_key = f"MARKET_DATA_MAX_GAP_HOURS_{provider.upper()}_{instrument.upper()}"
    if override := os.environ.get(env_key):
        return int(override)
    try:
        return _STALENESS_FALLBACK[(provider, instrument)]
    except KeyError as exc:
        raise ValueError(
            f"No max_gap_hours configured for ({provider!r}, {instrument!r}). "
            f"Add to _STALENESS_FALLBACK or set {env_key}."
        ) from exc


def emit_stale_feed_if_breach(
    *,
    provider: str,
    instrument: str,
    last_ingest_at: Optional[datetime],
    now: Optional[datetime] = None,
) -> bool:
    """Emit market_data_stale_feed warning if gap exceeds max_gap_hours.

    Returns True if alert was emitted, False otherwise. Alerting-only — never
    blocks ingest of recovering provider.
    """
    server_now = now or now_utc()
    max_gap = timedelta(hours=max_gap_hours_for(provider, instrument))
    if last_ingest_at is None:
        gap_hours = float("inf")
    else:
        gap_hours = (server_now - last_ingest_at).total_seconds() / 3600
    if gap_hours <= max_gap.total_seconds() / 3600:
        return False
    logger.warning(
        "market_data_stale_feed",
        provider=provider,
        instrument=instrument,
        gap_hours=gap_hours,
        max_gap_hours=max_gap.total_seconds() / 3600,
        last_ingest_at=last_ingest_at.isoformat() if last_ingest_at else None,
    )
    return True


# ── Audit-trail metadata builder (governance §"Audit-trail attribution") ──

@dataclass(frozen=True)
class MarketDataAuditMetadata:
    """Constitutional audit metadata for every market-data ingest event.

    Per governance §"Audit-trail attribution" (lines 673-688):
    provider, instrument, provider_timestamp, sequence_number (or stable
    bulk key (source, symbol, settlement_date)), tier_at_ingest_time
    (frozen), is_canonical.
    """

    provider: str
    instrument: str
    actor_sub: str  # "service:<provider>_ingest"
    tier_at_ingest_time: ProviderTier
    is_canonical: bool
    # Live single-event ingest paths only (forward-looking; no production
    # call-site today per Backfill/Bulk exemption).
    provider_timestamp: Optional[datetime] = None
    sequence_number: Optional[int] = None
    # Bulk/exempt path replay key — exactly ONE of the three shapes
    # (live pair, single_date, or batch_id) must be populated per ingest event.
    #   * single_date_replay_key  -> single-date page-scrape POST
    #     (e.g. POST /aluminum/cash-settlement/ingest with one settlement_date)
    #   * batch_replay_id         -> multi-date batch path
    #     (POST /aluminum/cash-settlement/ingest-bulk and scheduler bulk run)
    # The two-field shape avoids the prior tuple representation that forced
    # callers to fabricate a settlement_date for batch-level events
    # (see PR #87 Codex catch 3253047614 / hook P2 sibling-sweep-miss on
    # bulk_replay_key shape divergence between sibling paths).
    single_date_replay_key: Optional[date] = None
    batch_replay_id: Optional[str] = None

    def __post_init__(self) -> None:
        if (self.provider_timestamp is not None) ^ (self.sequence_number is not None):
            raise ValueError("MarketDataAuditMetadata: provider_timestamp and sequence_number must be provided together.")

        has_live = self.provider_timestamp is not None and self.sequence_number is not None
        has_single = self.single_date_replay_key is not None
        has_batch = self.batch_replay_id is not None
        
        if sum(bool(x) for x in [has_live, has_single, has_batch]) != 1:
            raise ValueError(
                "MarketDataAuditMetadata: exactly one of (provider_timestamp+sequence_number), "
                "single_date_replay_key, or batch_replay_id must be populated."
            )

    def as_metadata_dict(self) -> dict:
        d = {
            "actor_sub": self.actor_sub,
            "provider": self.provider,
            "instrument": self.instrument,
            "tier_at_ingest_time": self.tier_at_ingest_time,
            "is_canonical": self.is_canonical,
        }
        if self.provider_timestamp is not None:
            d["provider_timestamp"] = self.provider_timestamp.isoformat()
        if self.sequence_number is not None:
            d["sequence_number"] = self.sequence_number
        if self.single_date_replay_key is not None:
            d["replay_key"] = {
                "source": self.provider,
                "symbol": self.instrument,
                "settlement_date": self.single_date_replay_key.isoformat(),
            }
        elif self.batch_replay_id is not None:
            d["replay_key"] = {
                "source": self.provider,
                "symbol": self.instrument,
                "batch_id": str(self.batch_replay_id),
            }
        return d
```

### 4.2 Alembic revision `045_market_data_governance_columns`

Add `backend/alembic/versions/045_market_data_governance_columns.py`:

```python
"""market_data_governance_columns

Adds:
- cash_settlement_prices.is_canonical (BOOLEAN NOT NULL DEFAULT TRUE)
- market_data_sequence_tracker table (forward-looking; no current path writes)

Per docs/governance.md MARKET-DATA GOVERNANCE (Cluster 4 PR-CL4-1).

Revision ID: 045_market_data_governance_columns
Revises: 044_drop_deal_lifecycle_fields
Create Date: 2026-05-16
"""

from alembic import op
import sqlalchemy as sa


revision = "045_market_data_governance_columns"
down_revision = "044_drop_deal_lifecycle_fields"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # is_canonical column on existing cash_settlement_prices
    op.add_column(
        "cash_settlement_prices",
        sa.Column(
            "is_canonical",
            sa.Boolean(),
            nullable=False,
            server_default=sa.true(),
        ),
    )

    # Forward-looking tracker for live single-event paths (none today).
    op.create_table(
        "market_data_sequence_tracker",
        sa.Column("provider", sa.String(length=64), nullable=False),
        sa.Column("instrument", sa.String(length=64), nullable=False),
        sa.Column("last_sequence", sa.BigInteger(), nullable=False),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.PrimaryKeyConstraint("provider", "instrument"),
    )


def downgrade() -> None:
    op.drop_table("market_data_sequence_tracker")
    op.drop_column("cash_settlement_prices", "is_canonical")
```

Verify alembic chain post-apply: `cd backend ; python -m alembic heads` MUST report `045_market_data_governance_columns (head)`.

### 4.3 Model updates

`backend/app/models/market_data.py`:

```python
# Add to imports:
from sqlalchemy import BigInteger, Boolean
from sqlalchemy.sql import true


class CashSettlementPrice(Base):
    # ... existing fields unchanged ...

    # NEW (per alembic 045):
    is_canonical: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=true()
    )


class MarketDataSequenceTracker(Base):
    __tablename__ = "market_data_sequence_tracker"

    provider: Mapped[str] = mapped_column(String(length=64), primary_key=True)
    instrument: Mapped[str] = mapped_column(String(length=64), primary_key=True)
    last_sequence: Mapped[int] = mapped_column(BigInteger, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )
```

Pydantic schemas at `backend/app/schemas/market_data.py` MUST expose `is_canonical: bool` on every market-data-facing model so `model_validate` round-trips AND so HTTP responses echo the canonical flag back to the caller. Additionally, the request schema MUST be updated to accept the fields required by the live-path replay helpers. Four schemas need updates:

- `CashSettlementIngestRequest` — POST `/aluminum/cash-settlement/ingest` payload; MUST add `provider_timestamp: datetime` and `sequence_number: int` (both required) so the client supplies the live-path assertions.
- `CashSettlementPriceRead` — GET `/aluminum/cash-settlement/prices` response; mirrors the ORM `is_canonical` directly. For computed data branches (like `_compute_monthly_averages` in `backend/app/api/routes/westmetall.py` returning `LME_ALU_MONTHLY_AVG`), the executor MUST populate a synthetic flag `is_canonical=True` so response validation succeeds without breaking the existing manual construction. **Crucially, the underlying query for the monthly average MUST be updated to filter the daily rows by `is_canonical=True` to prevent aggregating canonical and audit-only rows together.**
- `CashSettlementIngestResponse` — POST `/aluminum/cash-settlement/ingest` response; echoes back the canonical flag of the ingested provider (must be `bool` unconditionally, even on idempotent skip).
- `CashSettlementBulkIngestResponse` — POST `/aluminum/cash-settlement/ingest-bulk` response; echoes the canonical flag for the batch (today always `True` since Westmetall is the canonical provider for `LME_ALU_CASH_SETTLEMENT_DAILY`; future audit-only provider will return `False` on its batch).

Adding the field on the three response schemas regenerates the OpenAPI surface (`docs/api/openapi_v1.json` if codegen runs in CI) and the frontend-generated types (`frontend-svelte/src/lib/api/schema.d.ts` or equivalent). Per §2's frontend-types exception, this additive regeneration is the only permitted frontend diff. The dispatch §6 acceptance criteria below enforce that the regen IS performed (the typed client must surface `is_canonical: boolean` on each response shape) — leaving the field server-only would silently lose the audit trail at the HTTP boundary, contradicting governance §"Audit-trail attribution".

### 4.4 Precision contract enforcement (anomaly #5)

`backend/app/services/westmetall_cash_settlement.py`:

Refactor `_parse_float` → `_parse_price_decimal`. Promote `WestmetallDailyRow.price_usd`:

```python
from decimal import Decimal, InvalidOperation


@dataclass(frozen=True)
class WestmetallDailyRow:
    settlement_date: date
    price_usd: Decimal  # was: float — promoted per governance §"Precision contract"


def _parse_price_decimal(value: str) -> Decimal | None:
    """Parse a Westmetall-rendered price string into Decimal.

    Per docs/governance.md §"Precision contract invariant" (lines 631-671):
    - Accept str only. Float inputs raise TypeError at the parser boundary.
    - Normalize locale artifacts BEFORE Decimal construction:
      * Strip nbsp (\\xa0), regular spaces, surrounding whitespace.
      * Drop thousands separator ",".
      * (Westmetall does not use decimal-comma; if it ever does, add
        ".replace(',', '.')" AFTER the thousands-separator strip.)
    - Construct via Decimal(str(normalized)) — never Decimal(float(...)).
    Returns None when the cleaned string is empty or unparseable.
    """
    if not isinstance(value, str):
        raise TypeError(
            f"_parse_price_decimal accepts str only; got {type(value).__name__}. "
            f"Float inputs forbidden at parser boundary per "
            f"docs/governance.md §'Precision contract invariant'."
        )
    cleaned = value.strip().replace("\xa0", " ").replace(" ", "")
    if not cleaned:
        return None
    # Locale-aware separator normalization per governance §"Precision contract"
    # (must handle decimal-comma AND decimal-point conventions; resolves PR #87
    # Codex catch 3253047615). Algorithm: when both "," and "." are present, the
    # rightmost is the decimal separator (US "2,567.50" → dot is decimal; EU
    # "2.567,50" → comma is decimal). When only one of them is present, "."
    # is treated as the decimal separator (Westmetall's actual convention) and
    # "," is treated as the thousands separator (Westmetall's actual convention)
    # — i.e. the single-separator path is conservative and matches the only
    # provider in the trusted tier today; future providers using a different
    # single-separator convention add their own per-provider parser before this
    # generic fallback.
    has_comma = "," in cleaned
    has_dot = "." in cleaned
    if has_comma and has_dot:
        if cleaned.rindex(",") > cleaned.rindex("."):
            # EU: "2.567,50" → strip dots (thousands), comma becomes decimal point
            cleaned = cleaned.replace(".", "").replace(",", ".")
        else:
            # US: "2,567.50" → strip commas (thousands), dot is already decimal
            cleaned = cleaned.replace(",", "")
    elif has_comma:
        # Decimal-comma vs thousands-comma: if exactly 2 trailing digits, it's a decimal mark
        if len(cleaned) - cleaned.rindex(",") <= 3:
            cleaned = cleaned.replace(",", ".")
        else:
            cleaned = cleaned.replace(",", "")
    try:
        return Decimal(cleaned)
    except InvalidOperation:
        return None
```

Update `parse_westmetall_daily_rows` (lines 184-209) to invoke `_parse_price_decimal`:

```python
def parse_westmetall_daily_rows(html: bytes) -> list[WestmetallDailyRow]:
    text = html.decode("utf-8", errors="replace")
    rows: list[WestmetallDailyRow] = []
    for tr in re.findall(r"<tr[^>]*>.*?</tr>", text, flags=re.IGNORECASE | re.DOTALL):
        cells = []
        for cell in _TD_RE.findall(tr):
            cell_text = _TAG_RE.sub("", cell).strip()
            if cell_text:
                cells.append(cell_text)
        if len(cells) < 2:
            continue
        parsed_date = _parse_settlement_date(cells[0])
        if not parsed_date:
            continue
        parsed_price = _parse_price_decimal(cells[1])  # was _parse_float
        if parsed_price is None:
            continue
        rows.append(
            WestmetallDailyRow(settlement_date=parsed_date, price_usd=parsed_price)
        )
    if not rows:
        raise WestmetallLayoutError("no_daily_rows_parsed")
    return rows
```

Delete `_parse_float` (do NOT leave a deprecated alias — governance forbids float inputs at the parser boundary; an alias is a footgun). Verify: `rg -nP "_parse_float" backend/` returns zero matches outside the new file's git history.

### 4.5 Bulk idempotency hardening (anomaly #2 — bulk distinction)

`backend/app/services/cash_settlement_prices.py`:

Refactor `ingest_westmetall_cash_settlement_daily_for_date` to perform the row-level `price_usd` comparison:

```python
from app.services.market_data_governance import (
    BulkContentMismatch,
    MarketDataAuditMetadata,
    classify_bulk_row_replay,
    emit_bulk_content_mismatch_rejection,
    emit_bulk_idempotent_skip,
    is_canonical,
    tier_for_provider,
)


def ingest_westmetall_cash_settlement_daily_for_date(
    db: Session,
    settlement_date: date,
) -> tuple[uuid.UUID | None, int, int, WestmetallFetchEvidence]:
    html, evidence = fetch_westmetall_html(WESTMETALL_DAILY_URL)
    rows = parse_westmetall_daily_rows(html)
    row = next((r for r in rows if r.settlement_date == settlement_date), None)
    if row is None:
        return None, 0, 0, evidence

    # Per governance §"Bulk idempotency vs replay distinction": load ONLY
    # price_usd into the comparison path. html_sha256 (page-level hash) MUST
    # NOT participate in row idempotency — and per the binding's spirit MUST
    # NOT even be loaded into memory on the idempotency code path, because
    # any later refactor could inadvertently start reading it. Column-scoped
    # query enforces the load-guard structurally; resolves PR #87 hook P1
    # on html_sha256 load guard. We also load `id` to return it as a durable anchor on skip.
    existing_row = (
        db.query(CashSettlementPrice.id, CashSettlementPrice.price_usd)
        .filter(
            CashSettlementPrice.source == SOURCE_WESTMETALL,
            CashSettlementPrice.symbol == SYMBOL_DAILY,
            CashSettlementPrice.settlement_date == settlement_date,
        )
        .first()
    )
    if existing_row is not None:
        existing_id, existing_price_usd = existing_row
        outcome = classify_bulk_row_replay(
            new_price_usd=row.price_usd,
            existing_price_usd=existing_price_usd,
        )
        if outcome == "idempotent_skip":
            emit_bulk_idempotent_skip(
                provider=SOURCE_WESTMETALL,
                instrument=SYMBOL_DAILY,
                settlement_date=settlement_date,
                actor_sub="service:westmetall_ingest",
            )
            return existing_id, 0, 1, evidence
        # outcome == "content_mismatch"
        emit_bulk_content_mismatch_rejection(
            provider=SOURCE_WESTMETALL,
            instrument=SYMBOL_DAILY,
            settlement_date=settlement_date,
            new_price_usd=row.price_usd,
            existing_price_usd=existing_price_usd,
            actor_sub="service:westmetall_ingest",
        )
        raise BulkContentMismatch(
            f"price_usd mismatch for ({SOURCE_WESTMETALL}, {SYMBOL_DAILY}, "
            f"{settlement_date.isoformat()}): new={row.price_usd} "
            f"existing={existing_price_usd}"
        )

    price = CashSettlementPrice(
        source=SOURCE_WESTMETALL,
        symbol=SYMBOL_DAILY,
        settlement_date=settlement_date,
        price_usd=row.price_usd,  # already Decimal — no conversion
        is_canonical=is_canonical(SOURCE_WESTMETALL, SYMBOL_DAILY),
        source_url=evidence.source_url,
        html_sha256=evidence.html_sha256,
        fetched_at=evidence.fetched_at,
    )
    db.add(price)
    db.flush()
    return price.id, 1, 0, evidence
```

Refactor `ingest_westmetall_cash_settlement_bulk` to perform the same row-level comparison per row:

```python
def ingest_westmetall_cash_settlement_bulk(
    db: Session,
    start_date: Optional[date] = None,
    end_date: Optional[date] = None,
) -> tuple[list[uuid.UUID], uuid.UUID, int, int, WestmetallFetchEvidence]:
    html, evidence = fetch_westmetall_html(WESTMETALL_DAILY_URL)
    rows = parse_westmetall_daily_rows(html)

    if start_date:
        rows = [r for r in rows if r.settlement_date >= start_date]
    if end_date:
        rows = [r for r in rows if r.settlement_date <= end_date]

    if not rows:
        batch_uuid = _westmetall_batch_uuid(
            start_date=start_date,
            end_date=end_date,
            html_sha256=evidence.html_sha256,
            inserted_dates=[],
        )
        return [], batch_uuid, 0, 0, evidence

    # Map existing rows by settlement_date for O(1) lookup. Per governance
    # §"Bulk idempotency vs replay distinction": load ONLY (settlement_date,
    # price_usd) columns — html_sha256 (page-level hash) MUST NOT be loaded
    # into memory on the idempotency code path so a later refactor cannot
    # accidentally start reading it for row classification. Column-scoped
    # query enforces the load-guard structurally; resolves PR #87 hook P1
    # on html_sha256 load guard.
    existing_price_by_date: dict[date, Decimal] = {
        settlement_date: price_usd
        for settlement_date, price_usd in db.query(
            CashSettlementPrice.settlement_date, CashSettlementPrice.price_usd
        )
        .filter(
            CashSettlementPrice.source == SOURCE_WESTMETALL,
            CashSettlementPrice.symbol == SYMBOL_DAILY,
            CashSettlementPrice.settlement_date.in_(
                [r.settlement_date for r in rows]
            ),
        )
        .all()
    }

    ingested = 0
    skipped = 0
    inserted_prices: list[CashSettlementPrice] = []
    inserted_dates: list[date] = []
    canonical_flag = is_canonical(SOURCE_WESTMETALL, SYMBOL_DAILY)

    for row in rows:
        existing_price_usd = existing_price_by_date.get(row.settlement_date)
        if existing_price_usd is not None:
            outcome = classify_bulk_row_replay(
                new_price_usd=row.price_usd,
                existing_price_usd=existing_price_usd,
            )
            if outcome == "idempotent_skip":
                emit_bulk_idempotent_skip(
                    provider=SOURCE_WESTMETALL,
                    instrument=SYMBOL_DAILY,
                    settlement_date=row.settlement_date,
                    actor_sub="service:westmetall_ingest",
                )
                skipped += 1
                continue
            # outcome == "content_mismatch": REJECT the whole bulk batch.
            # Partial commit of a batch with a mismatched row would leave the
            # operator with ambiguous audit state (some rows persisted, some
            # not, the mismatch row never persisted).
            emit_bulk_content_mismatch_rejection(
                provider=SOURCE_WESTMETALL,
                instrument=SYMBOL_DAILY,
                settlement_date=row.settlement_date,
                new_price_usd=row.price_usd,
                existing_price_usd=existing_price_usd,
                actor_sub="service:westmetall_ingest",
            )
            raise BulkContentMismatch(
                f"price_usd mismatch for ({SOURCE_WESTMETALL}, {SYMBOL_DAILY}, "
                f"{row.settlement_date.isoformat()}): new={row.price_usd} "
                f"existing={existing_price_usd}"
            )

        price = CashSettlementPrice(
            source=SOURCE_WESTMETALL,
            symbol=SYMBOL_DAILY,
            settlement_date=row.settlement_date,
            price_usd=row.price_usd,  # Decimal — no conversion
            is_canonical=canonical_flag,
            source_url=evidence.source_url,
            html_sha256=evidence.html_sha256,
            fetched_at=evidence.fetched_at,
        )
        db.add(price)
        inserted_prices.append(price)
        inserted_dates.append(row.settlement_date)
        ingested += 1

    if ingested:
        db.flush()

    batch_uuid = _westmetall_batch_uuid(
        start_date=start_date,
        end_date=end_date,
        html_sha256=evidence.html_sha256,
        inserted_dates=inserted_dates,
    )
    return [price.id for price in inserted_prices], batch_uuid, ingested, skipped, evidence
```

**Critical**: the route handlers (`westmetall.py:138-159, :191-218`) MUST catch `BulkContentMismatch` and raise `HTTPException(status_code=409 CONFLICT, detail=str(exc))` so the operator receives a structured rejection. Add to the existing try/except blocks alongside `WestmetallLayoutError` and `CircuitOpenError`.

### 4.6 Route-handler audit metadata expansion (governance §"Audit-trail attribution")

`backend/app/api/routes/westmetall.py`:

Single-date POST (`:120-170`):

```python
from app.services.market_data_governance import (
    BulkContentMismatch,
    MarketDataAuditMetadata,
    is_canonical as is_canonical_provider,
    tier_for_provider,
)


@router.post("/aluminum/cash-settlement/ingest", ...)
@limiter.limit(RATE_LIMIT_SCRAPING)
def ingest_cash_settlement_daily(
    payload: CashSettlementIngestRequest,
    request: Request,
    _: None = Depends(audit_event(entity_type="cash_settlement_price", event_type="market_data_ingested")),
    __: None = Depends(require_service_identity("westmetall_ingest")),
    session: Session = Depends(get_session),
) -> CashSettlementIngestResponse:
    try:
        with unit_of_work(session, request=request):
            # Executor MUST update `ingest_westmetall_cash_settlement_daily_for_date`
            # to return the existing row's ID on skip as the first element instead of None,
            # so we always have a durable anchor for the audit event.
            row_id, ingested_count, skipped_count, evidence = (
                ingest_westmetall_cash_settlement_daily_for_date(
                    session, payload.settlement_date
                )
            )
            
            if row_id is not None:
                metadata = MarketDataAuditMetadata(
                    provider=SOURCE_WESTMETALL,
                    instrument=SYMBOL_DAILY,
                    actor_sub="service:westmetall_ingest",
                    tier_at_ingest_time=tier_for_provider(SOURCE_WESTMETALL),
                    is_canonical=is_canonical_provider(SOURCE_WESTMETALL, SYMBOL_DAILY),
                    provider_timestamp=payload.provider_timestamp,
                    sequence_number=payload.sequence_number,
                    # The single-date POST route MUST enforce live-path checks per governance.
                    # The executor MUST wire check_replay_window and check_sequence_monotonicity
                    # into this path using `payload.provider_timestamp` and `payload.sequence_number`.
                )
                mark_audit_success(
                    request,
                    row_id,
                    metadata=metadata.as_metadata_dict(),
                )
    except BulkContentMismatch as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail=str(exc)
        ) from exc
    except WestmetallLayoutError as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY, detail=str(exc)
        ) from exc
    except CircuitOpenError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(exc)
        ) from exc

    # Keep existing required fields (ingested_count, skipped_count, source, symbol, settlement_date, source_url, html_sha256, fetched_at)
    return CashSettlementIngestResponse(
        ... # existing fields
        is_canonical=is_canonical_provider(SOURCE_WESTMETALL, SYMBOL_DAILY),
    )
```

Bulk POST (`:173-236`): apply the same `MarketDataAuditMetadata` expansion at `:202-218`. For the bulk path, use `batch_replay_id=str(batch_uuid)` (NOT a tuple, NOT `single_date_replay_key` — the bulk path spans multiple settlement_dates and has no single date to attribute). The `as_metadata_dict()` serialization produces `replay_key = {"source": ..., "symbol": ..., "batch_id": ...}` automatically. The `__post_init__` mutual-exclusion check guarantees a single replay-key shape per event across all sibling paths (single-date POST, bulk POST, scheduler). Same `BulkContentMismatch` → HTTP 409 handler addition. The returned `CashSettlementBulkIngestResponse` MUST populate `is_canonical=is_canonical_provider(SOURCE_WESTMETALL, SYMBOL_DAILY)`.

### 4.7 Scheduler audit metadata expansion

`backend/app/tasks/westmetall_task.py`:

Update `AuditTrailService.record_worker_event` call at `:45-58` to use `MarketDataAuditMetadata`:

```python
from app.services.market_data_governance import (
    MarketDataAuditMetadata,
    is_canonical as is_canonical_provider,
    tier_for_provider,
)
from app.services.westmetall_cash_settlement import (
    SOURCE_WESTMETALL,
    SYMBOL_DAILY,
    # ... existing imports ...
)


def run_westmetall_ingestion() -> None:
    logger.info("westmetall_task_start")
    session = SessionLocal()
    try:
        inserted_ids, batch_uuid, ingested, skipped, evidence = (
            ingest_westmetall_cash_settlement_bulk(session)
        )
        metadata = MarketDataAuditMetadata(
            provider=SOURCE_WESTMETALL,
            instrument=SYMBOL_DAILY,
            actor_sub="service:westmetall_ingest",
            tier_at_ingest_time=tier_for_provider(SOURCE_WESTMETALL),
            is_canonical=is_canonical_provider(SOURCE_WESTMETALL, SYMBOL_DAILY),
            # Multi-date batch path: batch_uuid is the stable replay key
            # for the bulk run; no single settlement_date applies because the
            # batch spans multiple dates. as_metadata_dict() serializes this
            # as replay_key={"source", "symbol", "batch_id"} (NOT
            # settlement_date). Per governance §"Audit-trail attribution"
            # stable bulk replay key for batch-spanning paths.
            batch_replay_id=str(batch_uuid),
        )
        audit_meta = metadata.as_metadata_dict()
        audit_meta["inserted_ids"] = [
            str(inserted_id) for inserted_id in inserted_ids
        ]
        audit_meta["source_url"] = evidence.source_url
        audit_meta["html_sha256"] = evidence.html_sha256
        audit_meta["batch_uuid"] = str(batch_uuid)
        AuditTrailService.record_worker_event(
            session,
            entity_type="cash_settlement_price",
            entity_id=batch_uuid,
            event_type="market_data_ingested",
            actor="service:westmetall_ingest",
                source="westmetall_task",
                metadata=audit_meta,
            )
            session.commit()
        logger.info(
            "westmetall_task_success",
            ingested_count=ingested,
            skipped_count=skipped,
            source_url=evidence.source_url,
        )
    except WestmetallLayoutError as exc:
        logger.error("westmetall_task_layout_error", error=str(exc))
    except CircuitOpenError as exc:
        logger.warning("westmetall_task_circuit_open", error=str(exc))
    except Exception as exc:  # pragma: no cover — safety net
        logger.error(
            "westmetall_task_unexpected_error", error=str(exc), exc_info=True
        )
    finally:
        session.close()
```

The scheduler MUST NOT catch `BulkContentMismatch` silently — if it occurs in production the operator needs to see it. Either re-raise it or log it at error-level with the structured event already emitted by `emit_bulk_content_mismatch_rejection`. Recommended: do not add a special-case handler; let the existing `Exception` safety-net catch and log it. The `market_data_replay_rejected` event already emitted by the helper is the persistent signal.

### 4.8 Stale-feed detection task (anomaly #3)

New file `backend/app/tasks/market_data_staleness_task.py`:

```python
"""Background staleness check for market-data feeds.

Per docs/governance.md §"Stale-feed detection invariant" (lines 568-586).
Alerting-only — never blocks ingest.
"""

from __future__ import annotations

from app.core.database import SessionLocal
from app.core.logging import get_logger
from app.models.market_data import CashSettlementPrice
from app.services.market_data_governance import emit_stale_feed_if_breach
from app.services.westmetall_cash_settlement import SOURCE_WESTMETALL, SYMBOL_DAILY

logger = get_logger()


# Pairs to monitor. Extend when a new (provider, instrument) joins the trusted tier.
_MONITORED_PAIRS: list[tuple[str, str]] = [
    (SOURCE_WESTMETALL, SYMBOL_DAILY),
]


def run_market_data_staleness_check() -> None:
    """One pass of the staleness check across every monitored (provider, instrument).

    Emits market_data_stale_feed warning per pair when gap exceeds
    max_gap_hours. Catches all exceptions — scheduler must never crash.
    """
    logger.info("market_data_staleness_check_start")
    session = SessionLocal()
    try:
        for provider, instrument in _MONITORED_PAIRS:
            try:
                last_row = (
                    session.query(CashSettlementPrice)
                    .filter(
                        CashSettlementPrice.source == provider,
                        CashSettlementPrice.symbol == instrument,
                    )
                    .order_by(CashSettlementPrice.fetched_at.desc())
                    .first()
                )
                last_ingest_at = last_row.fetched_at if last_row else None
                emit_stale_feed_if_breach(
                    provider=provider,
                    instrument=instrument,
                    last_ingest_at=last_ingest_at,
                )
            except Exception as exc:  # pragma: no cover — safety net per pair
                logger.error(
                    "market_data_staleness_check_pair_error",
                    provider=provider,
                    instrument=instrument,
                    error=str(exc),
                    exc_info=True,
                )
        logger.info("market_data_staleness_check_end")
    finally:
        session.close()
```

Register the task with the existing scheduler (verify the scheduler init file: `rg -nP "add_job|scheduled_jobs|run_westmetall_ingestion" backend/app/`). The cron cadence is `MARKET_DATA_STALENESS_CHECK_INTERVAL_MINUTES` (default 15). Use the same registration mechanism as `run_westmetall_ingestion`. Per binding: alerting-only, must NOT crash the scheduler if a single pair lookup fails.

### 4.9 Drift-alerting infrastructure scaffold (anomaly #6)

Drift computation lives in `market_data_governance.py` (§4.1). No call-site exists today because no audit-only provider exists. The scaffold MUST be tested via fixture: synthesize a canonical row + an audit-only row for the same `(instrument, settlement_date)` and assert `emit_drift_alert_if_breach` emits the structured event when drift > threshold and does not when drift ≤ threshold (and returns False for zero-canonical-price zero-guard).

If a future PR introduces a second provider, the ingest path for that provider's audit-only rows MUST call `emit_drift_alert_if_breach` after the row insert; the call-site is the responsibility of that future PR. The scaffold's job is to make the helper available and tested.

### 4.10 Tier registry, canonical registry, staleness registry — wiring discipline

All three registries (`_PROVIDER_TIER_REGISTRY`, `_CANONICAL_PROVIDER_FALLBACK`, `_STALENESS_FALLBACK`) live in `market_data_governance.py`. When a new provider/instrument joins, the constitutional amendment to `docs/governance.md` is the contract; updating these registries in the same PR is the implementation half. The dispatch does NOT instantiate any new provider; Westmetall + LME_ALU_CASH_SETTLEMENT_DAILY are the only entries.

## 5. Constitutional Rules

This wave is governed by:

- `docs/governance.md` MARKET-DATA GOVERNANCE (entire section, lines 442-748 at HEAD `05ffa2f8e`) — the canonical market-data contract.
- `docs/governance.md` §"GOVERNANCE HARD FAILS" — "No mutation without evidence" (audit_event + actor_sub on every ingest path).
- `docs/governance.md` §"Audit-trail attribution" (lines 673-688) — expanded metadata contract.
- `docs/governance.md` §"Precision contract invariant" (lines 631-671) — string-first Decimal construction; float-input rejection at parser boundary.
- `docs/governance.md` §"Bulk idempotency vs replay distinction" (lines 535-555) — row-level `price_usd` comparison; `html_sha256` whole-page hash forbidden for row idempotency.

No changes to `docs/governance.md` are part of this wave.

## 6. Acceptance Criteria

A merged PR closes D-4.1 iff every item below is true.

### 6.1 New module + alembic + model

- [ ] `backend/app/services/market_data_governance.py` exists with `tier_for_provider`, `canonical_provider_for_instrument`, `is_canonical`, `check_replay_window`, `check_sequence_monotonicity`, `classify_bulk_row_replay`, `emit_bulk_idempotent_skip`, `emit_bulk_content_mismatch_rejection`, `compute_normalized_drift`, `emit_drift_alert_if_breach`, `max_gap_hours_for`, `emit_stale_feed_if_breach`, `replay_window_minutes_for`, `drift_threshold_for`, `MarketDataAuditMetadata`, `ReplayWindowViolation`, `SequenceMonotonicityViolation`, `BulkContentMismatch`, `_PROVIDER_TIER_REGISTRY`, `_CANONICAL_PROVIDER_FALLBACK`, `_STALENESS_FALLBACK`.
- [ ] `backend/alembic/versions/045_market_data_governance_columns.py` exists; `cd backend ; python -m alembic heads` reports exactly `045_market_data_governance_columns (head)`.
- [ ] `cash_settlement_prices.is_canonical` column exists, NOT NULL, server_default TRUE; existing rows backfilled to TRUE.
- [ ] `market_data_sequence_tracker` table exists with PK `(provider, instrument)`.
- [ ] `CashSettlementPrice.is_canonical` model attribute exists; `CashSettlementPriceRead`, `CashSettlementIngestResponse`, and `CashSettlementBulkIngestResponse` Pydantic schemas at `backend/app/schemas/market_data.py` all expose `is_canonical` per §4.3.
- [ ] **Frontend types regen (PR #87 hook P1):** `frontend-svelte/src/lib/api/schema.d.ts` (or whichever generated client file the project uses; verify with `rg -nP "CashSettlementPriceRead|CashSettlementIngestResponse" frontend-svelte/src/lib/api/`) shows additive `is_canonical: boolean` on each of the three response shapes. The diff is auto-generated; no hand-edited frontend logic changes. If the project commits an `openapi.json` artifact (e.g. `docs/api/openapi_v1.json`), it MUST also show the additive field.
- [ ] `MarketDataSequenceTracker` model exists.

### 6.2 Precision contract (anomaly #5)

- [ ] `westmetall_cash_settlement.py` — `_parse_float` removed. `_parse_price_decimal(value: str) -> Decimal | None` exists with explicit `not isinstance(value, str)` TypeError.
- [ ] `WestmetallDailyRow.price_usd: Decimal` (not `float`).
- [ ] `parse_westmetall_daily_rows` invokes `_parse_price_decimal`.
- [ ] `cash_settlement_prices.py` row constructors at `:46, :125` consume `row.price_usd` directly (no `Decimal(...)` or `float(...)` wrap).
- [ ] Sweep `rg -nP "_parse_float|Decimal\\(float|float\\(.*price" backend/app/services/westmetall_cash_settlement.py backend/app/services/cash_settlement_prices.py backend/app/api/routes/westmetall.py` returns zero matches.

### 6.3 Bulk idempotency hardening (anomaly #2 bulk distinction)

- [ ] `ingest_westmetall_cash_settlement_daily_for_date` invokes `classify_bulk_row_replay` on every existing-key collision; matching → `emit_bulk_idempotent_skip` + return-as-skip; differing → `emit_bulk_content_mismatch_rejection` + raise `BulkContentMismatch`.
- [ ] `ingest_westmetall_cash_settlement_bulk` performs the same per-row classification.
- [ ] `westmetall.py` route handlers catch `BulkContentMismatch` → HTTP 409 CONFLICT with the helper's detail.
- [ ] Neither helper reads `existing.html_sha256` for row idempotency. Sweep `rg -nP "html_sha256" backend/app/services/cash_settlement_prices.py` — every match is either constructor assignment (`html_sha256=evidence.html_sha256`) or batch UUID derivation; none in the idempotency classification branch.
- [ ] **html_sha256 load guard (PR #87 hook P1):** the idempotency lookup query MUST be column-scoped (load only `settlement_date` + `price_usd`), so `html_sha256` is NEVER pulled into memory on the idempotency code path even though it is also never used. Sweep `rg -nP "db\.query\(CashSettlementPrice\)\\." backend/app/services/cash_settlement_prices.py` — every match MUST be a row constructor / `.add(...)` write path, NEVER an idempotency-lookup `.first()` / `.all()` read. The idempotency read path uses `db.query(CashSettlementPrice.price_usd)` or `db.query(CashSettlementPrice.settlement_date, CashSettlementPrice.price_usd)` exclusively.

### 6.4 Canonical-vs-audit segregation (anomaly #4)

- [ ] Row insert in both `daily_for_date` and `bulk` ingest paths sets `is_canonical = is_canonical_provider(SOURCE_WESTMETALL, SYMBOL_DAILY)`.
- [ ] `MARKET_DATA_CANONICAL_PROVIDER_LME_ALU_CASH_SETTLEMENT_DAILY` env-var lookup is the override path; fallback `westmetall`.
- [ ] All existing Westmetall rows post-migration have `is_canonical = True`.
- [ ] Downstream MTM/P&L reads via `price_lookup_service.py` MUST be updated to filter on `is_canonical=True` instead of relying on the legacy `_canonical_source_for_symbol` map.

### 6.5 Stale-feed detection (anomaly #3)

- [ ] `backend/app/tasks/market_data_staleness_task.py` exists with `run_market_data_staleness_check`.
- [ ] Registered on the existing scheduler at `MARKET_DATA_STALENESS_CHECK_INTERVAL_MINUTES` cadence (default 15).
- [ ] `_MONITORED_PAIRS` contains `(westmetall, LME_ALU_CASH_SETTLEMENT_DAILY)`.
- [ ] `max_gap_hours_for("westmetall", "LME_ALU_CASH_SETTLEMENT_DAILY")` returns 96 by default; env-var override works.
- [ ] Per-pair exception in the loop is caught and logged; the loop continues to the next pair.

### 6.6 Drift-alerting scaffold (anomaly #6)

- [ ] `compute_normalized_drift` zero-guards canonical_price == 0 (returns None).
- [ ] `drift_threshold_for(instrument)` honors `MARKET_DATA_DRIFT_THRESHOLD_<INSTRUMENT>` env override; fallback `Decimal("0.01")`.
- [ ] `emit_drift_alert_if_breach` emits `market_data_drift_alert` with all required fields when `drift > threshold`; returns True/False matching the branch taken; never invoked in production today (no audit-only provider).

### 6.7 Audit-trail metadata expansion

- [ ] `mark_audit_success` calls in both POST routes pass `MarketDataAuditMetadata(...).as_metadata_dict()`. Metadata persisted includes: `actor_sub`, `provider`, `instrument`, `tier_at_ingest_time`, `is_canonical`, and `replay_key` (one of two shapes — `{source, symbol, settlement_date}` for single-date POST or `{source, symbol, batch_id}` for bulk POST + scheduler; both shapes round-trip through the same dict key for downstream-consumer uniformity). The `MarketDataAuditMetadata.__post_init__` mutual-exclusion check guarantees `single_date_replay_key` and `batch_replay_id` are never both populated on the same event.
- [ ] Tests MUST explicitly validate the `MarketDataAuditMetadata.__post_init__` hard-fail (raises ValueError) when both `single_date_replay_key` and `batch_replay_id` are populated, ensuring the audit-trail mutual exclusion contract is enforced.
- [ ] `AuditTrailService.record_worker_event` call in `westmetall_task.py` merges `MarketDataAuditMetadata(...).as_metadata_dict()` with the legacy `inserted_ids`, `source_url`, `html_sha256`, `batch_uuid` fields.
- [ ] No regression on Cluster 3 PR-CL3-1 `actor_sub="service:westmetall_ingest"` plumbing.

### 6.8 Forward-looking helpers wired

- [ ] `check_replay_window`, `check_sequence_monotonicity`, `emit_drift_alert_if_breach` exist with the contracts above. Sweep `rg -nP "check_replay_window|check_sequence_monotonicity" backend/app/api/routes/` MUST show call-sites inside the `POST /aluminum/cash-settlement/ingest` single-date route. Only bulk/scheduler paths are exempt from these checks.
- [ ] `MarketDataSequenceTracker` is empty in the running DB (no path writes to it today, unless a test uses the single-date ingest).

### 6.9 Cross-cutting isolation

- [ ] `git diff main -- docs/governance.md` returns empty.
- [ ] `git diff main -- frontend-svelte/` shows ONLY auto-generated OpenAPI types updates with the additive `is_canonical: boolean` field on the three response shapes (no UI / business-logic / formatter / route changes). All non-generated frontend paths are zero-diff.
- [ ] `git diff main -- frontend-svelte/nginx.conf` returns empty (Cluster 3 territory).
- [ ] `git diff main -- backend/app/core/auth.py` returns empty (Cluster 3 territory — `require_service_identity` already landed in PR #81 and is unchanged).
- [ ] Single alembic head: `045_market_data_governance_columns`.
- [ ] No new IdP / no new role / no new service identity. The `westmetall_ingest` actor remains the only market-data ingest identity.

### 6.10 PR-CL4-1 dispatch §3.6 sweep results documented

- [ ] PR body contains a section "Sweep results — additional market-data gaps" with either "zero additional findings" OR an enumerated list of any newly-discovered anomaly with line citations + retirement applied in this PR.
- [ ] PR body contains the output of `rg -nP "Decimal\\(\\s*float" backend/app/` and `rg -nP "float\\(.*price" backend/app/services/` — either empty or with each finding classified as in-scope or deferred.

## 7. Required Tests

### 7.1 New test file `backend/tests/test_market_data_governance.py`

Unit tests on `market_data_governance.py` (no DB required for most):

1. **`test_tier_for_provider_returns_trusted_for_westmetall`** — `tier_for_provider("westmetall") == "trusted"`.
2. **`test_tier_for_provider_raises_on_unknown`** — `tier_for_provider("unknown_provider")` raises `ValueError` with message about constitutional amendment.
3. **`test_canonical_provider_default_lookup`** — `canonical_provider_for_instrument("LME_ALU_CASH_SETTLEMENT_DAILY") == "westmetall"`.
4. **`test_canonical_provider_env_override`** — `monkeypatch.setenv("MARKET_DATA_CANONICAL_PROVIDER_LME_ALU_CASH_SETTLEMENT_DAILY", "fakeprovider")`; assert override returned.
5. **`test_canonical_provider_raises_on_unknown_instrument`** — unknown instrument raises ValueError.
6. **`test_is_canonical_true_for_westmetall`** — `is_canonical("westmetall", "LME_ALU_CASH_SETTLEMENT_DAILY") is True`.
7. **`test_is_canonical_false_for_other_provider`** — `is_canonical("fakeprovider", "LME_ALU_CASH_SETTLEMENT_DAILY") is False`.
8. **`test_replay_window_default_30_minutes`** — `replay_window_minutes_for("westmetall") == 30`.
9. **`test_replay_window_per_provider_override`** — env-var `MARKET_DATA_REPLAY_WINDOW_WESTMETALL_MINUTES=10` returns 10.
10. **`test_replay_window_global_override`** — env-var `MARKET_DATA_REPLAY_WINDOW_MINUTES=5` returns 5 absent per-provider override.
11. **`test_check_replay_window_accepts_within_tolerance`** — `provider_timestamp = now - 15min`, window default 30 → no raise.
12. **`test_check_replay_window_rejects_outside_tolerance`** — `provider_timestamp = now - 45min`, window default 30 → `ReplayWindowViolation`; assert structured log event emitted (use `structlog.testing.capture_logs` or a caplog fixture).
13. **`test_classify_bulk_row_replay_idempotent_skip_on_match`** — same Decimal → `"idempotent_skip"`.
14. **`test_classify_bulk_row_replay_content_mismatch_on_diff`** — different Decimal → `"content_mismatch"`.
15. **`test_classify_bulk_row_replay_rejects_float_new_price`** — passing float as new_price_usd raises TypeError.
16. **`test_classify_bulk_row_replay_rejects_float_existing_price`** — passing float as existing_price_usd raises TypeError.
17. **`test_classify_bulk_row_replay_exact_compare_not_tolerance`** — `Decimal("100.000001")` vs `Decimal("100.000000")` → `"content_mismatch"` (exact equality, no tolerance window).
18. **`test_emit_bulk_idempotent_skip_has_no_reason_field`** — capture structlog event; assert `"reason"` NOT in event fields.
19. **`test_emit_bulk_content_mismatch_rejection_has_reason_bulk_content_mismatch`** — capture event; assert `event["reason"] == "bulk_content_mismatch"`.
20. **`test_compute_normalized_drift_basic`** — `canonical=Decimal("100")`, `audit=Decimal("101")` → `Decimal("0.01")`.
21. **`test_compute_normalized_drift_zero_canonical_returns_none`** — canonical=0 → `None`.
22. **`test_drift_threshold_default_one_percent`** — `drift_threshold_for("LME_ALU_CASH_SETTLEMENT_DAILY") == Decimal("0.01")`.
23. **`test_drift_threshold_env_override`** — env override returns the parsed Decimal.
24. **`test_emit_drift_alert_below_threshold_returns_false`** — drift 0.005 with threshold 0.01 → False, no event.
25. **`test_emit_drift_alert_above_threshold_returns_true_and_emits`** — drift 0.05 with threshold 0.01 → True, event captured.
26. **`test_emit_drift_alert_zero_canonical_returns_false`** — None drift → False, no event.
27. **`test_max_gap_hours_default_westmetall_aluminum`** — `max_gap_hours_for("westmetall", "LME_ALU_CASH_SETTLEMENT_DAILY") == 96`.
28. **`test_max_gap_hours_env_override`** — env-var override honored.
29. **`test_max_gap_hours_raises_on_unknown_pair`** — unknown pair raises ValueError.
30. **`test_emit_stale_feed_below_threshold_returns_false`** — gap 1h, max 96h → False, no event.
31. **`test_emit_stale_feed_above_threshold_returns_true_and_emits`** — gap 100h, max 96h → True, event captured.
32. **`test_emit_stale_feed_no_last_ingest_at_returns_true`** — `last_ingest_at=None` → True (infinite gap).
33. **`test_market_data_audit_metadata_as_dict_live_fields`** — `MarketDataAuditMetadata(provider="westmetall", instrument="LME_ALU_CASH_SETTLEMENT_DAILY", actor_sub="service:westmetall_ingest", tier_at_ingest_time="trusted", is_canonical=True, provider_timestamp=datetime(2026,5,16,tzinfo=timezone.utc), sequence_number=42, single_date_replay_key=None, batch_replay_id=None).as_metadata_dict()` contains `provider_timestamp` and `sequence_number`; `replay_key` is absent.
33a. **`test_market_data_audit_metadata_post_init_rejects_empty_identifiers`** — instantiating with all replay identifiers set to `None` raises `ValueError`.
33b. **`test_market_data_audit_metadata_post_init_rejects_partial_live`** — instantiating with `provider_timestamp` but no `sequence_number` (or vice versa) raises `ValueError`.
34. **`test_market_data_audit_metadata_as_dict_single_date_replay_key`** — with `single_date_replay_key=date(2026,5,16)` → `metadata["replay_key"]` is `{"source": "westmetall", "symbol": "LME_ALU_CASH_SETTLEMENT_DAILY", "settlement_date": "2026-05-16"}`.
34a. **`test_market_data_audit_metadata_as_dict_batch_replay_id`** — with `batch_replay_id="batch-uuid-abc"` → `metadata["replay_key"]` is `{"source": "westmetall", "symbol": "LME_ALU_CASH_SETTLEMENT_DAILY", "batch_id": "batch-uuid-abc"}`; `settlement_date` key absent.
34b. **`test_market_data_audit_metadata_post_init_rejects_both_replay_keys`** — instantiating with BOTH `single_date_replay_key=date(2026,5,16)` AND `batch_replay_id="x"` raises `ValueError` (mutual-exclusion guard per `__post_init__`).

### 7.2 Sequence-monotonicity DB tests `backend/tests/test_market_data_sequence_tracker.py`

Tests that DO require a DB session (use the existing pytest DB fixture):

35. **`test_check_sequence_monotonicity_first_call_creates_tracker_row`** — empty DB, call helper with `sequence_number=10` → tracker row created, last_sequence=10, no exception.
36. **`test_check_sequence_monotonicity_advances_on_higher_sequence`** — tracker at 10, call with 20 → tracker advances to 20, no exception.
37. **`test_check_sequence_monotonicity_duplicate_raises`** — tracker at 10, call with 10 → `SequenceMonotonicityViolation`; structured log event `reason == "sequence_duplicate"`.
38. **`test_check_sequence_monotonicity_out_of_order_raises`** — tracker at 10, call with 5 → `SequenceMonotonicityViolation`; `reason == "sequence_not_monotonic"`.

### 7.3 Westmetall parser tests `backend/tests/test_westmetall_parser_precision.py`

Targeted parser precision tests (NEW file; isolate from existing test_phase4_step1):

39. **`test_parse_price_decimal_rejects_float_input`** — `_parse_price_decimal(2567.5)` raises TypeError.
40. **`test_parse_price_decimal_rejects_int_input`** — `_parse_price_decimal(2567)` raises TypeError.
41. **`test_parse_price_decimal_accepts_basic_decimal_string`** — `_parse_price_decimal("2567.50") == Decimal("2567.50")`.
42. **`test_parse_price_decimal_strips_thousands_separator`** — `_parse_price_decimal("2,567.50") == Decimal("2567.50")`.
43. **`test_parse_price_decimal_strips_nbsp`** — `_parse_price_decimal("2567.50\xa0") == Decimal("2567.50")`.
44. **`test_parse_price_decimal_strips_surrounding_whitespace`** — `_parse_price_decimal("  2567.50  ") == Decimal("2567.50")`.
45. **`test_parse_price_decimal_returns_none_on_empty`** — `_parse_price_decimal("")` and `_parse_price_decimal("   ")` return None.
46. **`test_parse_price_decimal_returns_none_on_garbage`** — `_parse_price_decimal("not a number")` returns None.
47. **`test_parse_price_decimal_preserves_precision`** — `_parse_price_decimal("2567.500001") == Decimal("2567.500001")` (precision preserved, NO truncation to 6dp at parser layer — that's storage concern).
48. **`test_parse_westmetall_daily_rows_returns_decimal_price`** — fixture HTML → rows have `isinstance(row.price_usd, Decimal)` for every row.
49. **`test_parse_westmetall_daily_rows_no_float_anywhere`** — fixture HTML → no row has `isinstance(row.price_usd, float)`.

### 7.4 Bulk idempotency hardening DB tests `backend/tests/test_cash_settlement_bulk_idempotency.py`

DB-required tests for the hardened bulk idempotency (NEW file):

50. **`test_daily_for_date_first_insert_persists_decimal_price`** — fresh DB, ingest one date → row persisted, `isinstance(row.price_usd, Decimal)`, `row.is_canonical is True`.
51. **`test_daily_for_date_matching_existing_emits_idempotent_skip`** — pre-seed DB with one row at `Decimal("2567.50")`; mock fetch to return the same price for that date; ingest → no new row, structured event `market_data_bulk_idempotent_skip` emitted with correct fields, returns `(existing_id, 0, 1, evidence)`.
52. **`test_daily_for_date_differing_existing_raises_bulk_content_mismatch`** — pre-seed DB with row at `Decimal("2567.50")`; mock fetch returning `Decimal("2700.00")` for that date; ingest raises `BulkContentMismatch`; structured event `market_data_replay_rejected` emitted with `reason="bulk_content_mismatch"`; row NOT updated in DB.
53. **`test_bulk_ingest_mixed_existing_and_new_persists_only_new`** — pre-seed DB with 2 rows; mock fetch returning 5 rows (3 new, 2 same-price as existing); ingest persists 3 new rows, emits 2 idempotent_skip events, returns `(3 inserted_ids, batch_uuid, 3, 2, evidence)`.
54. **`test_bulk_ingest_mismatch_in_middle_rejects_entire_batch`** — pre-seed DB with 1 row at `Decimal("2567.50")`; mock fetch returning 5 rows, one with mismatched price for the existing date; bulk ingest raises `BulkContentMismatch`; rolled-back transaction — no new rows persisted.
55. **`test_bulk_ingest_sets_is_canonical_true_for_westmetall`** — fresh DB, bulk ingest → every persisted row has `is_canonical=True`.
56. **`test_html_sha256_not_used_for_row_idempotency`** — pre-seed DB with row at `Decimal("2567.50")` and `html_sha256="hashA"`; mock fetch returning the same date+price but a DIFFERENT html_sha256 (`"hashB"`); ingest emits `market_data_bulk_idempotent_skip` (row prices match) — NOT a rejection. This regression-guards against re-introducing whole-page hash row idempotency.

### 7.5 Route-level integration tests `backend/tests/test_westmetall_routes_governance.py`

End-to-end FastAPI route tests using the existing JWT/service-identity fixtures (NEW file):

57. **`test_post_ingest_persists_audit_metadata_with_governance_fields`** — POST `/aluminum/cash-settlement/ingest` with valid `westmetall_ingest` JWT, `provider_timestamp`, and `sequence_number`; assert persisted audit_event row has `metadata["provider"] == "westmetall"`, `metadata["instrument"] == "LME_ALU_CASH_SETTLEMENT_DAILY"`, `metadata["tier_at_ingest_time"] == "trusted"`, `metadata["is_canonical"] is True`, `metadata["provider_timestamp"]` matches payload, and `metadata["sequence_number"]` matches payload (single-date path uses live fields).
57a. **`test_post_ingest_bulk_persists_batch_replay_id`** — POST `/aluminum/cash-settlement/ingest-bulk` with date range; assert persisted audit_event row has `metadata["replay_key"]["batch_id"]` equal to `str(batch_uuid)` and `metadata["replay_key"]` does NOT contain a `settlement_date` key (bulk path uses `batch_replay_id`).
58. **`test_post_ingest_bulk_mismatch_returns_409`** — pre-seed DB with mismatched row; POST `/ingest` for that date returns HTTP 409 with `bulk_content_mismatch` in detail; no row state change in DB.
59. **`test_post_ingest_bulk_path_persists_audit_metadata`** — POST `/aluminum/cash-settlement/ingest-bulk`; assert `record_worker_event`-or-`mark_audit_success` row metadata contains the governance fields.

### 7.6 Scheduler integration tests `backend/tests/test_westmetall_task_governance.py`

60. **`test_scheduler_ingest_attributes_governance_metadata`** — invoke `run_westmetall_ingestion()` directly with a mocked fetcher; assert the recorded `audit_events` row's metadata contains `provider`, `instrument`, `tier_at_ingest_time`, `is_canonical`, `actor_sub == "service:westmetall_ingest"` AND the legacy fields `inserted_ids`, `source_url`, `html_sha256`, `batch_uuid` (legacy fields preserved per Cluster 3 PR-CL3-1 plumbing).

### 7.7 Stale-feed task tests `backend/tests/test_market_data_staleness_task.py`

61. **`test_staleness_check_emits_alert_when_no_rows`** — fresh DB; run task; assert `market_data_stale_feed` event emitted for the Westmetall pair (infinite gap).
62. **`test_staleness_check_quiet_when_recent_row`** — seed DB with a row at `now - 1h`; run task; no event emitted.
63. **`test_staleness_check_emits_alert_when_gap_exceeds`** — seed DB with a row at `now - 100h`, default threshold 96h; run task; event emitted with `gap_hours ≈ 100`, `max_gap_hours == 96`.
64. **`test_staleness_check_continues_after_per_pair_exception`** — monkeypatch `emit_stale_feed_if_breach` to raise on first pair; assert second pair (if added to `_MONITORED_PAIRS` for test) still processed. (With only one pair today, this test can be skipped or use a temporary patched registry.)

### 7.8 Drift-alerting scaffold tests `backend/tests/test_market_data_drift_scaffold.py`

65. **`test_drift_alert_below_threshold_silent`** — `emit_drift_alert_if_breach(...)` with drift below threshold returns False; no event captured.
66. **`test_drift_alert_above_threshold_emitted`** — drift above threshold → True; event captured with all required fields (`instrument`, `observation_key`, `canonical_provider`, `audit_provider`, `canonical_price`, `audit_price`, `normalized_drift`, `threshold`).
67. **`test_drift_alert_zero_canonical_skipped`** — `canonical_price=Decimal("0")` → False; no event (zero-guard per governance).

### 7.9 Existing test surface

Existing tests touching the ingest path MUST continue to pass:

- `backend/tests/test_phase4_step1_cash_settlement_prices.py` — update fixtures that assert `price_usd` is float; assert Decimal. Update fixtures that send `price_usd=float(...)` in test data; send `Decimal(...)`. Update idempotency assertions: existing-date-with-same-price ingest now produces `market_data_bulk_idempotent_skip` event (capture or ignore), not silent skip; existing-date-with-different-price ingest now raises `BulkContentMismatch`.
- `backend/tests/test_westmetall_task.py` — assert expanded audit metadata fields present.
- `backend/tests/test_pnl_price_evidence.py` — verify Decimal flow.
- `backend/tests/test_price_lookup_service.py` — verify Decimal flow.

Executor MUST sweep `rg -nP "price_usd.*float|float.*price_usd" backend/tests/` and update every match.

## 8. Required Verification

Run from repo root (use Git Bash for the sweeps; PowerShell for pytest/alembic):

```bash
# Module + helper surface
rg -nP "def tier_for_provider|def canonical_provider_for_instrument|def is_canonical|def check_replay_window|def check_sequence_monotonicity|def classify_bulk_row_replay|def emit_bulk_idempotent_skip|def emit_bulk_content_mismatch_rejection|def compute_normalized_drift|def emit_drift_alert_if_breach|def max_gap_hours_for|def emit_stale_feed_if_breach|def replay_window_minutes_for|def drift_threshold_for" backend/app/services/market_data_governance.py
rg -nP "class ReplayWindowViolation|class SequenceMonotonicityViolation|class BulkContentMismatch|class MarketDataAuditMetadata|_PROVIDER_TIER_REGISTRY|_CANONICAL_PROVIDER_FALLBACK|_STALENESS_FALLBACK" backend/app/services/market_data_governance.py

# Precision contract sweeps (every one MUST be zero)
rg -nP "_parse_float" backend/app/
rg -nP "Decimal\(\s*float" backend/app/services/westmetall_cash_settlement.py backend/app/services/cash_settlement_prices.py backend/app/api/routes/westmetall.py backend/app/tasks/westmetall_task.py
rg -nP "float\(.*price" backend/app/services/westmetall_cash_settlement.py backend/app/services/cash_settlement_prices.py
rg -nP "WestmetallDailyRow\(.*price_usd=.*float" backend/

# Bulk idempotency uses classify_bulk_row_replay
rg -nP "classify_bulk_row_replay" backend/app/services/cash_settlement_prices.py

# html_sha256 NOT in idempotency branches (positive assertion: only constructor + batch_uuid)
rg -nP "html_sha256" backend/app/services/cash_settlement_prices.py

# Canonical flag set on every persisted row
rg -nP "is_canonical=" backend/app/services/cash_settlement_prices.py

# Audit metadata governance fields plumbed
rg -nP "MarketDataAuditMetadata\(|as_metadata_dict\(\)" backend/app/api/routes/westmetall.py backend/app/tasks/westmetall_task.py
# replay_key shape mutual-exclusion: every call-site sets exactly one of
# single_date_replay_key / batch_replay_id (or neither for live single-event
# paths). Cross-check that bulk_replay_key (old tuple field) is GONE.
rg -nP "bulk_replay_key" backend/app/  # MUST be zero
rg -nP "single_date_replay_key=|batch_replay_id=" backend/app/api/routes/westmetall.py backend/app/tasks/westmetall_task.py

# html_sha256 load guard: idempotency-path queries are column-scoped
rg -nP "db\.query\(CashSettlementPrice\)\\.filter" backend/app/services/cash_settlement_prices.py
# MUST be zero matches — full-row queries forbidden on idempotency code path

# Parser locale normalization (PR #87 Codex catch 3253047615): both US and EU formats supported
rg -nP "rindex\(|has_comma|has_dot" backend/app/services/westmetall_cash_settlement.py
# MUST find the rindex-based detection per §4.4

# Replay and Sequence helpers MUST be wired in the single-date route
rg -nP "check_replay_window\(|check_sequence_monotonicity\(" backend/app/api/routes/westmetall.py
# MUST find call-sites for both helpers.

# Drift alert helper has NO production call-site today (expected zero)
rg -nP "emit_drift_alert_if_breach\(" backend/app/api/routes/ backend/app/tasks/

# Stale-feed task wired
rg -nP "def run_market_data_staleness_check|_MONITORED_PAIRS" backend/app/tasks/market_data_staleness_task.py
rg -nP "run_market_data_staleness_check|MARKET_DATA_STALENESS_CHECK_INTERVAL_MINUTES" backend/app/

# Cross-wave isolation
git diff main -- frontend-svelte/
git diff main -- frontend-svelte/nginx.conf
git diff main -- docs/governance.md
git diff main -- backend/app/core/auth.py

# Alembic invariant
cd backend && python -m alembic heads && cd ..
# Expected: 045_market_data_governance_columns (head)

# Pydantic schema exposes is_canonical
rg -nP "is_canonical" backend/app/schemas/market_data.py

# Test surface
pytest -q backend/tests/test_market_data_governance.py
pytest -q backend/tests/test_market_data_sequence_tracker.py
pytest -q backend/tests/test_westmetall_parser_precision.py
pytest -q backend/tests/test_cash_settlement_bulk_idempotency.py
pytest -q backend/tests/test_westmetall_routes_governance.py
pytest -q backend/tests/test_westmetall_task_governance.py
pytest -q backend/tests/test_market_data_staleness_task.py
pytest -q backend/tests/test_market_data_drift_scaffold.py
pytest -q backend/tests
```

`docs/governance.md` diff MUST be empty. Frontend + nginx + `backend/app/core/auth.py` diffs MUST be empty. Alembic head MUST be exactly `045_market_data_governance_columns`.

## 9. Out of Scope

- Editing `docs/governance.md` — landed in PR #86, canonical.
- Adding a second `trusted` provider (LME direct, Bloomberg, COMEX, SHFE, etc.). Per governance §"Current providers", new providers require constitutional amendment + tier assignment + ingest code in the same PR; that PR is NOT this one.
- Instantiating an `audit_only` row via production code (no second provider today; drift path remains scaffolded but unreachable in production).
- Changing `Numeric(18, 6)` storage precision.
- Changing the `westmetall_ingest` service identity / JWT minting / role contract (Cluster 3 territory).
- Frontend price-display changes (e.g. `formatPrice` locale tweaks). The binding declares display-layer formatting as the SOLE rounding point but doesn't require a change to existing formatters today.
- Adding new audit event types or columns to `audit_events`. The expansion uses the existing `metadata` JSON field.
- Currency conversion at ingest (governance forbids).
- Migrating historical `cash_settlement_prices` rows to new schema beyond the `is_canonical=True` backfill (already covered by `server_default=true()`).
- nginx CSP / Clerk / cookie / CSRF / RBAC changes (Cluster 3 territory).
- Replacing `html_sha256` in `cash_settlement_prices` (still required as batch-level audit evidence; the governance binding only forbids using it for row idempotency classification).
- Wiring `emit_drift_alert_if_breach` to a live production call-site (no audit-only provider exists today; forward-looking scaffold only).

## 10. PR Requirements

The implementing PR title must be:

```
fix(audit-followup): close Cluster 4 PR-CL4-1 (Westmetall hardening + market-data governance wiring)
```

The PR body must include:

- **Findings closed:** explicit `D-4.1` reference + governance.md MARKET-DATA GOVERNANCE citation (lines 442-748) + the 6 anomalies enumerated under §"Anomalies to be retired" (lines 690-746).
- **Files changed:** inventory grouped by:
  - **New modules**: `market_data_governance.py`, `market_data_staleness_task.py`.
  - **New tests**: 8 new test files listed in §7.
  - **Migrations**: `045_market_data_governance_columns.py`.
  - **Existing modules updated**: `westmetall_cash_settlement.py` (parser precision), `cash_settlement_prices.py` (bulk idempotency + canonical flag), `westmetall.py` (route audit metadata + BulkContentMismatch → HTTP 409), `westmetall_task.py` (audit metadata expansion), `market_data.py` (is_canonical + MarketDataSequenceTracker model), `market_data.py` Pydantic schema.
- **Anomaly retirement table:** §3.5 mapping reproduced inline with line citations + before/after.
- **Sweep results** — §6.10: zero additional findings OR enumerated list of any newly-discovered gap.
- **Verification command output** — §8 sweeps with their actual output (each "MUST be zero" sweep showing zero matches; alembic heads showing `045_market_data_governance_columns (head)`).
- **Hook artifact paths:** `.cache/dispatch_review/audit-followup-cluster-4-westmetall-hardening-{sha}.json` per push.
- **Governance statement:** `docs/governance.md` diff is empty.
- **Alembic statement:** single head `045_market_data_governance_columns`; chain verified.
- **Forward-looking scaffold disclosure**: explicit note that `emit_drift_alert_if_breach` is scaffolded but has no production call-site today (single-provider). A future PR introducing a second `trusted` provider will wire it in.

## 11. Workflow

1. `git checkout -b audit-followup/cluster-4-westmetall-hardening` from `main @ 05ffa2f8e` (post-PR #86).
2. Apply §4.1 (new `market_data_governance.py` module). Write unit tests in §7.1 + §7.2 first if TDD-ing — every helper has a direct test.
3. Apply §4.2 (alembic 045) FIRST in isolation: write the migration file, run `cd backend && python -m alembic upgrade head` against a fresh test DB, verify `cash_settlement_prices.is_canonical` column and `market_data_sequence_tracker` table exist via `\d cash_settlement_prices` / `\d market_data_sequence_tracker` (psql), then `python -m alembic downgrade -1` to verify the downgrade and re-upgrade. Migration-first ordering avoids the model-vs-schema mismatch window flagged by PR #87 hook P1. Only after the migration is validated, apply §4.3 (ORM model updates + Pydantic schema updates including the three response schemas per §4.3 expanded scope) in the same commit OR a follow-up commit on the same branch.
4. Apply §4.4 (precision contract). Run §7.3 tests in isolation.
5. Apply §4.5 (bulk idempotency hardening). Run §7.4 tests. Sweep §8 between steps to confirm the precision contract sweeps stay zero.
6. Apply §4.6 (route audit metadata + BulkContentMismatch → 409). Run §7.5 tests.
7. Apply §4.7 (scheduler audit metadata). Run §7.6 tests.
8. Apply §4.8 (stale-feed task). Run §7.7 tests. Verify scheduler registration with `rg -nP "run_market_data_staleness_check" backend/app/`.
9. Apply §4.9 (drift scaffold tests only; no production call-site change). Run §7.8 tests.
10. Update existing tests (§7.9 sweep): re-run `pytest -q backend/tests` and fix every regression.
11. Run §8 verification locally. Fix every hook v2 P1/P2 in place; do NOT push until clean.
12. Push branch and open PR per §10.
13. Codex Connector review is the final gate. Address every Codex inline catch. **Do not merge** — Andrei merges with explicit text-form authorization only.

## 12. Hook v2 + Codex calibration notes

- **Expected hook v2 surface area:** large (1 new service module ~400 lines + 1 alembic migration + 2 model classes + 2 service modules refactored + 1 route module updated + 1 scheduler module updated + 1 new task module + 8 new test files). Hook may flag prescription-vs-evidence on new symbol names (`tier_for_provider`, `MarketDataAuditMetadata`, `BulkContentMismatch`, `MarketDataSequenceTracker`) before they exist — known FP class per `feedback_hook_v2_documentation_precedes_implementation`.
- **Expected Codex catches** (calibration: governance-implementation PRs receive intense scrutiny; PR #86's 9-cycle absorption is a fair upper bound, but PR-CL4-1 is implementation not governance — likely 8-12 catches):
  - **Bulk idempotency edge case** — partial-batch rejection semantics. The dispatch chooses "reject entire batch on mismatch in the middle"; Codex may surface alternative ("persist preceding rows, log the mismatch, continue"). The chosen behavior follows the binding's "operator review required" framing — partial-commit ambiguity is worse than full rejection. Defend in PR body if Codex surfaces this.
  - **Float-input rejection at TypeError vs ValueError** — `_parse_price_decimal` raises TypeError on non-str input. Codex may prefer ValueError. TypeError is correct here: the input type violates the contract, not its value (governance §"Precision contract" says "Float inputs MUST be rejected at the parser boundary" — the type itself is the violation).
  - **`is_canonical` column server_default vs Python-side default** — using `server_default=true()` is the canonical alembic pattern. Codex may suggest adding a `default=True` mirror on the SQLAlchemy column; harmless to add for safety against migrations being skipped.
  - **`Decimal` exact comparison in `classify_bulk_row_replay`** — exact equality is governance-compliant ("any byte-level difference is a real mismatch"). Codex may flag this as fragile for re-published rows that round differently. Defense: provider re-publishes are byte-identical by construction; if they aren't, the difference IS a real divergence the operator needs to see.
  - **Parser locale detection ambiguity (PR #87 cycle 1 catch 3253047615)** — `_parse_price_decimal` uses the rightmost-of-`,`-or-`.` heuristic to disambiguate US ("2,567.50") vs EU ("2.567,50") formats when both separators are present. When only one is present, the comma is treated as a thousands separator (matches Westmetall's actual US convention, the only provider today). Codex may flag the single-separator branch as ambiguous for a future EU provider emitting "2567,50" (the parser would output `Decimal("2567")` instead of `Decimal("2567.50")`). Defense: future providers using EU decimal-comma convention MUST add a per-provider parser in front of the generic fallback (mirror of `_PROVIDER_TIER_REGISTRY` registration pattern); the dispatch §4.4 comment block makes this extension path explicit. Adding ambiguous heuristics to the generic parser is worse than per-provider explicit parsing.
  - **`MarketDataAuditMetadata` two-field replay key (PR #87 cycle 1 P2 absorption)** — the dataclass replaces the prior single `bulk_replay_key: Optional[tuple]` field with two mutually-exclusive optional fields: `single_date_replay_key: Optional[date]` and `batch_replay_id: Optional[str]`. The `__post_init__` enforces mutual exclusion. Codex may suggest collapsing back to a single discriminated-union field. Defense: two-field shape eliminates the prior bug where the scheduler had to fabricate a settlement_date to satisfy the tuple-element `isoformat()` call (PR #87 catch 3253047614). The per-path semantics now match the audit log shape exactly — `replay_key.settlement_date` for single-date events vs `replay_key.batch_id` for batch events.
  - **Drift normalization zero-guard semantics** — returning None vs raising. None is correct (alerting-only invariant; an undefined drift is not an alertable condition). Codex may prefer raising; defend per governance §"Canonical price reconciliation" which says "zero-guard when canonical_price == 0" not "raise on zero".
  - **`observation_key` representation** — the dispatch uses `settlement_date` for daily LME instruments; the binding mentions `observation_timestamp` for intraday and `tenor + fix_date` for tenor-fixed. Codex may flag that the implementation only covers the daily case. Defense: today only daily exists; the helper's `observation_key: str` parameter accepts any string representation, so future intraday / tenor-fix instruments serialize their own observation_key without code change.
  - **`tier_at_ingest_time` frozen value** — the dispatch reads tier at ingest time via `tier_for_provider(provider)` lookup. Codex may flag that if `_PROVIDER_TIER_REGISTRY` is mutated mid-ingest (impossible today since it's a module constant), the metadata would lie. Defense: the registry is module-level and immutable post-import; the only "transition" path is constitutional amendment (governance edit + code edit), not a runtime mutation.
  - **`market_data_sequence_tracker` table with no caller** — Codex may flag as dead code. Defense: forward-looking per governance binding; the same PR adds the schema and the helper that future PRs invoke. Dead-on-arrival is intentional and documented per §6.8.
  - **Scheduler registration mechanism** — depending on the existing scheduler infrastructure, registration may be via a config file, a function call at startup, or an APScheduler decorator. Whichever it is, Codex will check that the staleness task IS actually registered, not just defined. The executor MUST verify by reading the existing `westmetall_task.py` registration site and mirror it.
  - **PR-CL3-1 actor_sub regression** — Codex will verify `service:westmetall_ingest` actor still attributed correctly after metadata expansion. Defense: the expansion ADDS fields; the actor_sub remains at the same key.
- **Padrão estabelecido por PR #86 (9-cycle absorption, governance):** Cluster 4 territory receives Codex scrutiny on cross-section interdependencies (replay/idempotency/observation-key/precision/canonical/tier cross-reference each other). The implementation MUST cross-reference governance line citations in code comments to make the audit trail self-documenting.
- **8-section sweep checklist from `feedback_dispatch_self_consistency`:** §3 evidence, §4 boundary, §6 acceptance, §7 tests, §8 verification, §11 workflow MUST consistently enumerate the same 6 anomaly categories + the audit-metadata expansion + the 4 structured-log-event types. Drift between sections is the canonical authoring failure mode.
- **The largest authoring risk** is silent reintroduction of `Decimal(float(...))` somewhere in the call chain. The sweep `rg -nP "Decimal\\(\\s*float" backend/app/` is mandatory after every step. The second-largest risk is the bulk idempotency check using `html_sha256` again — the sweep `rg -nP "html_sha256" backend/app/services/cash_settlement_prices.py` MUST be eyeballed to confirm every match is constructor assignment or batch_uuid derivation, NEVER inside an idempotency `if/else` branch.
