"""Deal models — Deal, DealLink, DealPNLSnapshot (component 1.5)."""

from __future__ import annotations

import decimal
import enum
import re
import uuid as _uuid
from datetime import date, datetime, timezone
from decimal import Decimal


# Codex P2 (2026-05-06): the portable @validates defender for
# ``price_references`` MUST mirror the Postgres CHECK regex byte-for-byte.
# The CHECK function in alembic/versions/030_pnl_provenance.py uses
# ``^-?\d+(\.\d+)?$`` to reject scientific notation, NaN, Infinity,
# leading ``+``, leading/trailing dots, whitespace, and arbitrary text.
# ``Decimal(...)`` alone is too permissive — it accepts ``"5500.0e-2"``,
# ``"+5500"``, and whitespace-padded values that the CHECK rejects, so
# a SQLite ORM write could pass the validator and only fail on
# Postgres commit. Pre-compile once at module load (do NOT compile
# inside the per-entry loop). Use ``fullmatch`` so both ``^`` and
# ``$`` anchors are enforced.
_CANONICAL_DECIMAL_RE = re.compile(r"^-?\d+(\.\d+)?$")

from sqlalchemy import (
    JSON,
    Boolean,
    Date,
    DateTime,
    Enum,
    ForeignKey,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, validates


# Portable JSON column type for DealPNLSnapshot.price_references.
# - PostgreSQL: emits JSONB (efficient, indexable, supports ::jsonb cast,
#   jsonb_typeof, GIN — what production needs).
# - SQLite (test conftest forces sqlite+pysqlite:///:memory: and runs
#   Base.metadata.create_all()): falls back to the generic JSON type
#   (TEXT-backed) so create_all() succeeds and tests can run.
# Postgres-specific syntax (jsonb_typeof / ::jsonb) is reserved for the
# Alembic migration's dialect-guarded CHECK; per-row shape enforcement
# lives on the model via @validates so it runs portably in both dialects.
PriceReferencesType = JSON().with_variant(
    JSONB(astext_type=Text()),
    "postgresql",
)

from app.models.base import Base
from app.core.precision import (
    MT_NUMERIC_PRECISION,
    MT_NUMERIC_SCALE,
    PRICE_NUMERIC_PRECISION,
    PRICE_NUMERIC_SCALE,
)


# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------


class DealStatus(enum.Enum):
    open = "open"
    partially_hedged = "partially_hedged"
    fully_hedged = "fully_hedged"
    settled = "settled"
    closed = "closed"


class DealLinkedType(enum.Enum):
    sales_order = "sales_order"
    purchase_order = "purchase_order"
    hedge = "hedge"
    contract = "contract"


# ---------------------------------------------------------------------------
# Deal
# ---------------------------------------------------------------------------


class Deal(Base):
    __tablename__ = "deals"

    id: Mapped[_uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=_uuid.uuid4
    )
    reference: Mapped[str] = mapped_column(String(50), unique=True, nullable=False)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    commodity: Mapped[str] = mapped_column(String(20), nullable=False)
    status: Mapped[DealStatus] = mapped_column(
        Enum(DealStatus, name="deal_status"), nullable=False, default=DealStatus.open
    )
    total_physical_tons: Mapped[Decimal] = mapped_column(
        Numeric(MT_NUMERIC_PRECISION, MT_NUMERIC_SCALE), nullable=False, default=0
    )
    total_hedge_tons: Mapped[Decimal] = mapped_column(
        Numeric(MT_NUMERIC_PRECISION, MT_NUMERIC_SCALE), nullable=False, default=0
    )
    hedge_ratio: Mapped[Decimal] = mapped_column(
        Numeric(5, 2), nullable=False, default=0
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), onupdate=func.now(), nullable=True
    )
    is_deleted: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    deleted_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True, default=None
    )


# ---------------------------------------------------------------------------
# DealLink (polymorphic)
# ---------------------------------------------------------------------------


class DealLink(Base):
    __tablename__ = "deal_links"
    __table_args__ = (
        UniqueConstraint("deal_id", "linked_type", "linked_id", name="uq_deal_link"),
        UniqueConstraint(
            "linked_type",
            "linked_id",
            name="uq_deal_link_entity",
        ),
    )

    id: Mapped[_uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=_uuid.uuid4
    )
    deal_id: Mapped[_uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("deals.id", ondelete="CASCADE"), nullable=False
    )
    linked_type: Mapped[DealLinkedType] = mapped_column(
        Enum(DealLinkedType, name="deal_linked_type"), nullable=False
    )
    linked_id: Mapped[_uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


# ---------------------------------------------------------------------------
# DealPNLSnapshot
# ---------------------------------------------------------------------------


class DealPNLSnapshot(Base):
    __tablename__ = "deal_pnl_snapshots"

    id: Mapped[_uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=_uuid.uuid4
    )
    deal_id: Mapped[_uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("deals.id", ondelete="CASCADE"), nullable=False
    )
    snapshot_date: Mapped[date] = mapped_column(Date, nullable=False)
    physical_revenue: Mapped[Decimal] = mapped_column(
        Numeric(PRICE_NUMERIC_PRECISION, PRICE_NUMERIC_SCALE), default=0
    )
    physical_cost: Mapped[Decimal] = mapped_column(
        Numeric(PRICE_NUMERIC_PRECISION, PRICE_NUMERIC_SCALE), default=0
    )
    hedge_pnl_realized: Mapped[Decimal] = mapped_column(
        Numeric(PRICE_NUMERIC_PRECISION, PRICE_NUMERIC_SCALE), default=0
    )
    hedge_pnl_mtm: Mapped[Decimal] = mapped_column(
        Numeric(PRICE_NUMERIC_PRECISION, PRICE_NUMERIC_SCALE), default=0
    )
    total_pnl: Mapped[Decimal] = mapped_column(
        Numeric(PRICE_NUMERIC_PRECISION, PRICE_NUMERIC_SCALE), default=0
    )
    inputs_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    # Per-commodity price provenance consumed by this snapshot.
    # Shape (when non-NULL):
    #   {
    #     "ALUMINUM": {"value": "5500.123456", "source": "westmetall",
    #                  "settlement_date": "2026-05-05"},
    #     "COPPER":   {"value": "9120.654321", "source": "westmetall",
    #                  "settlement_date": "2026-05-02"},
    #   }
    # NULL means no market price was consulted (fixed-price-only deal,
    # no active hedges) — the honest representation; never a sentinel.
    # Decimal values stored as canonical strings (no float roundtrip);
    # ISO dates as strings; settlement_date may differ from
    # ``snapshot_date - 1`` because of weekend / holiday lookback.
    # Postgres-side CHECK is added by the Alembic migration
    # (dialect-guarded); model-side @validates below provides portable
    # shape enforcement so SQLite tests catch malformed writes too.
    price_references: Mapped[dict | None] = mapped_column(
        PriceReferencesType, nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    @validates("price_references")
    def _validate_price_references(self, _key, value):
        """Portable shape enforcement for ``price_references``.

        Runs in both SQLite (tests) and Postgres (prod). NULL is
        acceptable — no market price consulted. Non-NULL must be a
        non-empty dict; empty {} is ambiguous with NULL and rejected.
        Each entry must be a dict containing the three required keys
        (value, source, settlement_date). The compute_deal_pnl
        algorithm is the canonical producer; this validator is the
        defensive guard against direct ORM misuse.
        """
        if value is None:
            return value
        if not isinstance(value, dict):
            raise ValueError("price_references must be None or a dict")
        if not value:
            raise ValueError(
                "price_references must be None or a non-empty dict — "
                "empty {} is ambiguous with NULL and forbidden"
            )
        for commodity, entry in value.items():
            if not isinstance(entry, dict):
                raise ValueError(
                    f"price_references[{commodity!r}] must be a dict"
                )
            for required in ("value", "source", "settlement_date"):
                if required not in entry:
                    raise ValueError(
                        f"price_references[{commodity!r}] missing required "
                        f"key {required!r}"
                    )
            # Codex P2 (2026-05-06): the producer pipeline is
            # quantize_price() -> str(Decimal); a direct ORM write that
            # smuggles a non-decimal string ("not-a-number", "5500.0e-2",
            # "NaN", "+5500", etc.) would otherwise be persisted and
            # surfaced by the snapshot API. Decimal() rejects all of
            # these except scientific notation and NaN — both of which
            # the producer never emits — so we additionally fail closed
            # if the Decimal isn't finite.
            raw_value = entry["value"]
            if not isinstance(raw_value, str):
                raise ValueError(
                    f"price_references[{commodity!r}].value must be a string"
                )
            # Codex P2 follow-up (2026-05-06): mirror the Postgres CHECK
            # regex byte-for-byte. ``Decimal(...)`` is too permissive — it
            # accepts ``"5500.0e-2"``, ``"+5500"``, ``"  5500  "``, etc.,
            # which the CHECK rejects. Without this regex, SQLite tests
            # (which run @validates but no CHECK) would let malformed
            # audit evidence pass and only fail later in production at
            # commit time. ``fullmatch`` enforces both anchors.
            if not _CANONICAL_DECIMAL_RE.fullmatch(raw_value):
                raise ValueError(
                    f"price_references[{commodity!r}].value must be a "
                    f"canonical fixed-point decimal string (got "
                    f"{raw_value!r}); scientific notation, leading +, "
                    f"leading/trailing dots, NaN/Infinity, and "
                    f"whitespace are forbidden — must match the "
                    f"Postgres CHECK regex ^-?\\d+(\\.\\d+)?$."
                )
            # Defense in depth: keep the Decimal parse as a fallback
            # safety net. The regex above is a strict subset of what
            # Decimal accepts, so this should never trigger today, but
            # it guards against future regex edits that loosen the
            # pattern in ways the producer contract would not allow.
            try:
                parsed = Decimal(raw_value)
            except decimal.InvalidOperation as exc:
                raise ValueError(
                    f"price_references[{commodity!r}].value is not a "
                    f"valid decimal string: {raw_value!r}"
                ) from exc
            if not parsed.is_finite():
                raise ValueError(
                    f"price_references[{commodity!r}].value must be a "
                    f"finite decimal: {raw_value!r}"
                )
            # Codex P2 follow-up (2026-05-06): settlement_date must be
            # a real ISO calendar date (dispatch §3.4.1). The producer
            # always emits ``date.isoformat()`` strings; a direct ORM
            # write could otherwise smuggle ``"not-a-date"`` or
            # ``"2026-13-01"``. ``date.fromisoformat`` (Python 3.11+)
            # is strict-ISO-only — single-digit month/day is rejected,
            # and impossible calendar dates raise ``ValueError`` —
            # which mirrors the PG-side regex + ::date cast pair.
            raw_settlement = entry["settlement_date"]
            if not isinstance(raw_settlement, str):
                raise ValueError(
                    f"price_references[{commodity!r}].settlement_date "
                    f"must be a string"
                )
            try:
                date.fromisoformat(raw_settlement)
            except ValueError as exc:
                raise ValueError(
                    f"price_references[{commodity!r}].settlement_date "
                    f"is not a valid ISO calendar date: "
                    f"{raw_settlement!r}"
                ) from exc
        return value
