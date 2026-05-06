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

# Codex P2 (2026-05-06, follow-up): the portable @validates defender for
# ``settlement_date`` MUST mirror the Postgres CHECK regex byte-for-byte.
# The CHECK in alembic/versions/030_pnl_provenance.py uses
# ``^\d{4}-\d{2}-\d{2}$`` — a strict ``YYYY-MM-DD`` shape. Without this
# regex, ``date.fromisoformat()`` (Python 3.11+) ALSO accepts compact
# (``"20260505"``), ISO week (``"2026-W19-2"``), and ordinal
# (``"2026-125"``) forms that the PG CHECK rejects, so a SQLite ORM write
# could pass the validator and only fail later at Postgres commit time.
# Pre-compile once at module load. Use ``fullmatch`` so both anchors are
# enforced. The ``date.fromisoformat`` call below remains as
# defense-in-depth — it catches calendar-invalid dates the regex permits
# (``"2026-13-01"``, ``"2026-02-30"``).
_ISO_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")

import sqlalchemy as sa
from sqlalchemy import (
    JSON,
    BigInteger,
    Boolean,
    Date,
    DateTime,
    Enum,
    ForeignKey,
    Integer,
    Numeric,
    Sequence,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy import event
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


# Codex P1 (PR #22 follow-up, 2026-05-06): the previous design wired a
# Python ``default=`` callable that returned ``func.nextval(...)`` on
# PostgreSQL. SQLAlchemy only inlines a ``ClauseElement`` as a SQL
# expression when it is configured directly as the column-level default
# — when the same expression is the *return value* of a Python
# ``default=`` callable, SQLAlchemy treats it as an ordinary Python value
# and binds it as a parameter to the DBAPI, which fails with an adapter
# error on PostgreSQL. The canonical SQLAlchemy 2.0 idiom for "PG
# sequence + portable test fallback" is:
#
#   * Declare ``Sequence("...")`` on the column. SQLAlchemy fires
#     ``nextval('...')`` server-side on PostgreSQL when the column is
#     not otherwise populated (and ``Sequence`` is a no-op on SQLite).
#   * Bind ``server_default = nextval(...)`` in migration 031 so
#     raw-SQL inserts (admin scripts, repair tools, COPY) on PostgreSQL
#     also receive the value.
#   * Use a ``before_insert`` event listener as the SQLite-only fallback
#     (computes ``COALESCE(MAX(sequence), 0) + 1`` inline). The listener
#     early-returns on PostgreSQL so it never interferes with the
#     server-side sequence path. See ``_set_sqlite_sequence`` below.

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
    # Codex P1/P2 (PR #22 follow-ups, 2026-05-06): monotonic insertion
    # counter used by ``compute_deal_pnl``'s outage fallback to
    # deterministically identify the newest reusable snapshot for a
    # given (deal_id, snapshot_date) when timestamps tie. ``id`` is a
    # random UUID and ``created_at`` is second-precision on SQLite —
    # neither is monotonic across rows that land in the same second.
    #
    # No ``default=`` and no ``server_default=`` are declared on the
    # model itself — those are intentionally pushed to the dialect
    # boundary:
    #   * PostgreSQL: the ``Sequence(...)`` declaration causes
    #     SQLAlchemy to auto-fire ``nextval('deal_pnl_snapshots_sequence_seq')``
    #     server-side on every INSERT where the column is not otherwise
    #     populated. Migration 031 ALSO installs
    #     ``server_default = nextval(...)`` on the column so raw-SQL
    #     inserts (COPY, repair scripts) converge on the same sequence.
    #   * SQLite: the ``_set_sqlite_sequence`` ``before_insert`` event
    #     listener (declared after this class) computes
    #     ``COALESCE(MAX(sequence), 0) + 1`` at flush time. SQLAlchemy's
    #     ``Sequence`` is a no-op on SQLite, so the listener is the
    #     portable fallback. SQLite serializes writes — race-free in
    #     single-process pytest.
    # Together these give a multi-worker-safe PG path AND a portable
    # SQLite test path WITHOUT a Python ``default=`` callable that would
    # bind ``func.nextval(...)`` as a parameter (Codex P1 — broken).
    sequence: Mapped[int] = mapped_column(
        BigInteger,
        Sequence("deal_pnl_snapshots_sequence_seq"),
        nullable=False,
        index=True,
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
            # Codex P2 follow-up (2026-05-06): mirror the Postgres CHECK
            # ``jsonb_typeof(entry->'source') = 'string'`` clause. The
            # required-keys check above only verifies the key exists; a
            # direct ORM write could smuggle a non-string ``source``
            # (int, bool, list, dict, None) that would pass the portable
            # validator on SQLite and only fail later at Postgres commit
            # time. The producer always emits a string identifier
            # (e.g. "lme_cash_settlement", "westmetall_cash_settlement"),
            # and ``value`` / ``settlement_date`` already have explicit
            # isinstance(str) guards — this restores parity for ``source``.
            if not isinstance(entry["source"], str):
                raise ValueError(
                    f"price_references[{commodity!r}].source must be a string "
                    f"(got {type(entry['source']).__name__})"
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
            # Codex P2 follow-up (2026-05-06): mirror the Postgres CHECK
            # regex byte-for-byte. ``date.fromisoformat`` (Python 3.11+)
            # ALSO accepts compact (``"20260505"``), ISO week
            # (``"2026-W19-2"``), and ordinal (``"2026-125"``) forms
            # which the PG CHECK rejects. Anchored ``fullmatch`` here
            # restores parity so SQLite tests / repair tools cannot
            # persist provenance shapes that later violate the CHECK
            # in production.
            if not _ISO_DATE_RE.fullmatch(raw_settlement):
                raise ValueError(
                    f"price_references[{commodity!r}].settlement_date "
                    f"must be in strict YYYY-MM-DD format (got "
                    f"{raw_settlement!r}); compact `20260505` and "
                    f"ISO week `2026-W19-2` formats are forbidden — "
                    f"must match the Postgres CHECK regex "
                    f"^\\d{{4}}-\\d{{2}}-\\d{{2}}$."
                )
            # Defense in depth: catches calendar-invalid dates the
            # regex permits (e.g. ``"2026-13-01"``, ``"2026-02-30"``).
            try:
                date.fromisoformat(raw_settlement)
            except ValueError as exc:
                raise ValueError(
                    f"price_references[{commodity!r}].settlement_date "
                    f"is not a valid ISO calendar date: "
                    f"{raw_settlement!r}"
                ) from exc
        return value


# Codex P1 (PR #22 follow-up, 2026-05-06): SQLite-only fallback for the
# monotonic ``DealPNLSnapshot.sequence`` column.
#
# On PostgreSQL the column-level ``Sequence(...)`` declaration plus the
# migration's ``server_default = nextval(...)`` populate the value
# server-side — this listener MUST early-return so it never interferes
# with that path. On SQLite (test envs only) ``Sequence`` is a no-op
# and there is no server_default for raw-SQL inserts, so we compute
# ``COALESCE(MAX(sequence), 0) + 1`` inline against the in-flight
# connection. SQLite serializes writes, so the MAX read is race-free
# in single-process pytest.
#
# This replaces the previous Python ``default=`` callable that returned
# ``func.nextval(...)`` on PG: SQLAlchemy only inlines a SQL expression
# when it is configured directly as the column default, NOT when a
# Python ``default=`` callable returns one — the return value is bound
# as a DBAPI parameter, which fails on PostgreSQL.
@event.listens_for(DealPNLSnapshot, "before_insert")
def _set_sqlite_sequence(mapper, connection, target):
    """Assign ``target.sequence`` on SQLite when not already set.

    Early-returns on PostgreSQL (server-side ``Sequence`` /
    ``server_default`` own that path) and when the caller has already
    supplied a ``sequence`` value.
    """
    if connection.dialect.name == "postgresql":
        return
    if target.sequence is not None:
        return
    result = connection.execute(
        sa.text(
            "SELECT COALESCE(MAX(sequence), 0) + 1 FROM deal_pnl_snapshots"
        )
    ).scalar()
    target.sequence = int(result)
