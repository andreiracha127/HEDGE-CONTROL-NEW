"""Market-data governance helpers.

Per-provider deviations require constitutional amendment of docs/governance.md,
not silent override in this module.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from decimal import Decimal, ROUND_HALF_UP
from typing import Literal

import structlog

from app.core.utils import now_utc

logger = structlog.get_logger(__name__)

ProviderTier = Literal["trusted", "conditional", "quarantine"]
BulkIdempotencyOutcome = Literal["idempotent_skip", "content_mismatch"]

DEFAULT_REPLAY_WINDOW_MINUTES = 30
MARKET_DATA_STORAGE_SCALE = Decimal("0.000001")

_PROVIDER_TIER_REGISTRY: dict[str, ProviderTier] = {
    "westmetall": "trusted",
}

_CANONICAL_PROVIDER_FALLBACK: dict[str, str] = {
    "LME_ALU_CASH_SETTLEMENT_DAILY": "westmetall",
}

_STALENESS_FALLBACK: dict[tuple[str, str], int] = {
    ("westmetall", "LME_ALU_CASH_SETTLEMENT_DAILY"): 96,
}


class ReplayWindowViolation(Exception):
    """Raised when a live provider timestamp is outside the replay window."""


class SequenceMonotonicityViolation(Exception):
    """Raised when a live provider sequence is duplicate or out of order."""


class BulkContentMismatch(Exception):
    """Raised when a bulk replay collides on key but differs in row content."""


def tier_for_provider(provider: str) -> ProviderTier:
    try:
        return _PROVIDER_TIER_REGISTRY[provider]
    except KeyError as exc:
        raise ValueError(
            f"Provider {provider!r} has no constitutional tier classification. "
            "Tier assignments require amendment of docs/governance.md "
            "Provider trust matrix."
        ) from exc


def canonical_provider_for_instrument(instrument: str) -> str:
    env_key = f"MARKET_DATA_CANONICAL_PROVIDER_{instrument.upper()}"
    override = os.environ.get(env_key)
    if override:
        return override.strip().lower()
    try:
        return _CANONICAL_PROVIDER_FALLBACK[instrument]
    except KeyError as exc:
        raise ValueError(
            f"Instrument {instrument!r} has no canonical provider. "
            f"Set {env_key} or add a registry entry with the ingest path."
        ) from exc


def is_canonical(provider: str, instrument: str) -> bool:
    return provider.lower() == canonical_provider_for_instrument(instrument).lower()


def replay_window_minutes_for(provider: str) -> int:
    env_key = f"MARKET_DATA_REPLAY_WINDOW_{provider.upper()}_MINUTES"
    if override := os.environ.get(env_key):
        return int(override)
    if global_override := os.environ.get("MARKET_DATA_REPLAY_WINDOW_MINUTES"):
        return int(global_override)
    return DEFAULT_REPLAY_WINDOW_MINUTES


def check_replay_window(
    *,
    provider: str,
    instrument: str,
    provider_timestamp: datetime,
    sequence_number: int,
    actor_sub: str,
    now: datetime | None = None,
) -> None:
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


def check_sequence_monotonicity(
    db,
    *,
    provider: str,
    instrument: str,
    sequence_number: int,
    provider_timestamp: datetime,
    actor_sub: str,
) -> None:
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
        reason = None
        if sequence_number == last_seen:
            reason = "sequence_duplicate"
        elif sequence_number < last_seen:
            reason = "sequence_not_monotonic"
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
                f"sequence_number {sequence_number} {reason} (last_seen={last_seen})"
            )

    if tracker is None:
        db.add(
            MarketDataSequenceTracker(
                provider=provider,
                instrument=instrument,
                last_sequence=sequence_number,
            )
        )
        db.flush()
    else:
        tracker.last_sequence = sequence_number


def classify_bulk_row_replay(
    *,
    new_price_usd: Decimal,
    existing_price_usd: Decimal,
) -> BulkIdempotencyOutcome:
    if not isinstance(new_price_usd, Decimal):
        raise TypeError(
            "classify_bulk_row_replay requires Decimal new_price_usd, "
            f"got {type(new_price_usd).__name__}"
        )
    if not isinstance(existing_price_usd, Decimal):
        raise TypeError(
            "classify_bulk_row_replay requires Decimal existing_price_usd, "
            f"got {type(existing_price_usd).__name__}"
        )
    normalized_new = new_price_usd.quantize(
        MARKET_DATA_STORAGE_SCALE, rounding=ROUND_HALF_UP
    )
    normalized_existing = existing_price_usd.quantize(
        MARKET_DATA_STORAGE_SCALE, rounding=ROUND_HALF_UP
    )
    return "idempotent_skip" if normalized_new == normalized_existing else "content_mismatch"


def emit_bulk_idempotent_skip(
    *,
    provider: str,
    instrument: str,
    settlement_date: date,
    actor_sub: str,
) -> None:
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
    settlement_date: date,
    new_price_usd: Decimal,
    existing_price_usd: Decimal,
    actor_sub: str,
) -> None:
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


def drift_threshold_for(instrument: str) -> Decimal:
    env_key = f"MARKET_DATA_DRIFT_THRESHOLD_{instrument.upper()}"
    if override := os.environ.get(env_key):
        return Decimal(override)
    return Decimal("0.01")


def compute_normalized_drift(
    *, canonical_price: Decimal, audit_price: Decimal
) -> Decimal | None:
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
    last_ingest_at: datetime | None,
    now: datetime | None = None,
) -> bool:
    server_now = now or now_utc()
    max_gap = timedelta(hours=max_gap_hours_for(provider, instrument))
    if last_ingest_at is None:
        gap_hours = float("inf")
    else:
        if last_ingest_at.tzinfo is None:
            logger.warning(
                "market_data_stale_feed_timestamp_naive",
                provider=provider,
                instrument=instrument,
                last_ingest_at=last_ingest_at.isoformat(),
                assumed_timezone=str(server_now.tzinfo),
            )
            last_ingest_at = last_ingest_at.replace(tzinfo=server_now.tzinfo)
        gap_hours = (server_now - last_ingest_at).total_seconds() / 3600
    max_gap_hours = max_gap.total_seconds() / 3600
    if gap_hours <= max_gap_hours:
        return False
    logger.warning(
        "market_data_stale_feed",
        provider=provider,
        instrument=instrument,
        gap_hours=gap_hours,
        max_gap_hours=max_gap_hours,
        last_ingest_at=last_ingest_at.isoformat() if last_ingest_at else None,
    )
    return True


@dataclass(frozen=True)
class MarketDataAuditMetadata:
    provider: str
    instrument: str
    actor_sub: str
    tier_at_ingest_time: ProviderTier
    is_canonical: bool
    provider_timestamp: datetime | None = None
    sequence_number: int | None = None
    single_date_replay_key: date | None = None
    batch_replay_id: str | None = None

    def __post_init__(self) -> None:
        if (self.provider_timestamp is not None) ^ (self.sequence_number is not None):
            raise ValueError(
                "MarketDataAuditMetadata: provider_timestamp and sequence_number "
                "must be provided together."
            )

        has_live = (
            self.provider_timestamp is not None and self.sequence_number is not None
        )
        has_single = self.single_date_replay_key is not None
        has_batch = self.batch_replay_id is not None
        if sum(bool(x) for x in (has_live, has_single, has_batch)) != 1:
            raise ValueError(
                "MarketDataAuditMetadata: exactly one of "
                "(provider_timestamp+sequence_number), single_date_replay_key, "
                "or batch_replay_id must be populated."
            )

    def as_metadata_dict(self) -> dict:
        metadata = {
            "actor_sub": self.actor_sub,
            "provider": self.provider,
            "instrument": self.instrument,
            "tier_at_ingest_time": self.tier_at_ingest_time,
            "is_canonical": self.is_canonical,
        }
        if self.provider_timestamp is not None:
            metadata["provider_timestamp"] = self.provider_timestamp.isoformat()
        if self.sequence_number is not None:
            metadata["sequence_number"] = self.sequence_number
        if self.single_date_replay_key is not None:
            metadata["replay_key"] = {
                "source": self.provider,
                "symbol": self.instrument,
                "settlement_date": self.single_date_replay_key.isoformat(),
            }
        elif self.batch_replay_id is not None:
            metadata["replay_key"] = {
                "source": self.provider,
                "symbol": self.instrument,
                "batch_id": str(self.batch_replay_id),
            }
        return metadata
