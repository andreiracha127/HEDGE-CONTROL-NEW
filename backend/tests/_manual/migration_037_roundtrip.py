"""Manual roundtrip harness for Phase A2 PR-4 migration 037.

Run against an empty Postgres database. This exercises the §3.4
``upgrade()`` / ``downgrade()`` body in isolation, including the §6
queued-row variant where a ``RFQInvitation`` row carrying
``sent_at=NULL`` and ``provider_message_id=NULL`` exists at the moment
``downgrade()`` reasserts NOT NULL — which would fail on Postgres
without the §3.4 backfill UPDATE statements.

Usage::

    docker run --rm -d --name pr4_pg -e POSTGRES_PASSWORD=test \
        -e POSTGRES_DB=hedgectl -p 5544:5432 postgres:16-alpine
    DATABASE_URL='postgresql+psycopg://postgres:test@localhost:5544/hedgectl' \
        python tests/_manual/migration_037_roundtrip.py
"""

from __future__ import annotations

import os
import sys
import uuid
from datetime import datetime, timezone

from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session


def _connect():
    url = os.environ["DATABASE_URL"]
    return create_engine(url, future=True)


def _create_minimal_schema(engine) -> None:
    """Bootstrap just the rows that 037 mutates, skipping the full
    Phase 0..A2 chain (which has env-specific enum-create double-fire
    issues with SQLAlchemy 2.x in this Python).
    """
    with engine.begin() as conn:
        conn.execute(text("DROP SCHEMA IF EXISTS public CASCADE"))
        conn.execute(text("CREATE SCHEMA public"))
        conn.execute(text("CREATE TYPE rfq_invitation_channel AS ENUM ('whatsapp')"))
        conn.execute(
            text(
                "CREATE TYPE rfq_invitation_status "
                "AS ENUM ('queued', 'sent', 'failed')"
            )
        )
        conn.execute(
            text(
                """
                CREATE TABLE rfq_invitations (
                    id uuid PRIMARY KEY,
                    rfq_id uuid NOT NULL,
                    rfq_number varchar(32) NOT NULL,
                    counterparty_id uuid NOT NULL,
                    recipient_name varchar(128) NOT NULL,
                    recipient_phone varchar(50) NOT NULL,
                    channel rfq_invitation_channel NOT NULL,
                    message_body text NOT NULL,
                    provider_message_id varchar(128) NOT NULL,
                    send_status rfq_invitation_status NOT NULL,
                    sent_at timestamptz NOT NULL,
                    idempotency_key varchar(128) NOT NULL,
                    created_at timestamptz NOT NULL DEFAULT now()
                )
                """
            )
        )
        conn.execute(
            text(
                """
                CREATE TABLE rfq_quotes (
                    id uuid PRIMARY KEY,
                    rfq_id uuid NOT NULL,
                    counterparty_id uuid NOT NULL,
                    price_value numeric(18, 6) NOT NULL,
                    price_unit varchar(32) NOT NULL,
                    pricing_convention varchar(64) NOT NULL,
                    received_at timestamptz NOT NULL,
                    created_at timestamptz NOT NULL DEFAULT now()
                )
                """
            )
        )
        # Stamp alembic head as 036.
        conn.execute(
            text(
                """
                CREATE TABLE alembic_version (
                    version_num varchar(32) PRIMARY KEY
                )
                """
            )
        )
        conn.execute(
            text(
                "INSERT INTO alembic_version (version_num) "
                "VALUES ('036_merge_w1_heads')"
            )
        )


def _alembic(direction: str) -> int:
    cmd = f'alembic {direction} head' if direction == 'upgrade' else f'alembic {direction} -1'
    return os.system(cmd)


def _row_count(engine, query: str) -> int:
    with engine.begin() as conn:
        return conn.execute(text(query)).scalar_one()


def main() -> int:
    engine = _connect()
    print("[1/6] resetting schema and stamping at 036_merge_w1_heads")
    _create_minimal_schema(engine)

    print("[2/6] alembic upgrade head (applies 037)")
    rc = _alembic("upgrade")
    if rc != 0:
        return 1

    # Verify the new columns / enums exist.
    with engine.begin() as conn:
        purpose_default = conn.execute(
            text(
                "SELECT column_default FROM information_schema.columns "
                "WHERE table_name='rfq_invitations' AND column_name='purpose'"
            )
        ).scalar_one_or_none()
        assert purpose_default is not None, "purpose column missing after upgrade"
        sent_at_nullable = conn.execute(
            text(
                "SELECT is_nullable FROM information_schema.columns "
                "WHERE table_name='rfq_invitations' AND column_name='sent_at'"
            )
        ).scalar_one()
        assert sent_at_nullable == "YES", "sent_at not relaxed to NULLABLE"
        prov_nullable = conn.execute(
            text(
                "SELECT is_nullable FROM information_schema.columns "
                "WHERE table_name='rfq_invitations' AND column_name='provider_message_id'"
            )
        ).scalar_one()
        assert prov_nullable == "YES", "provider_message_id not relaxed to NULLABLE"
        quote_state_default = conn.execute(
            text(
                "SELECT column_default FROM information_schema.columns "
                "WHERE table_name='rfq_quotes' AND column_name='state'"
            )
        ).scalar_one_or_none()
        assert quote_state_default is not None, "rfq_quotes.state column missing"

    print("[3/6] inserting queued outbox row with sent_at=NULL + provider_message_id=NULL")
    with engine.begin() as conn:
        conn.execute(
            text(
                """
                INSERT INTO rfq_invitations
                    (id, rfq_id, rfq_number, counterparty_id,
                     recipient_name, recipient_phone, channel,
                     message_body, provider_message_id, send_status,
                     purpose, sent_at, idempotency_key, created_at)
                VALUES
                    (:id, :rfq_id, 'RFQ-RT-0001', :cp_id,
                     'CP-RT', '+5511000000001', 'whatsapp',
                     'RFQ#RFQ-RT-0001 - hello', NULL, 'queued',
                     'rfq_invite', NULL, 'idem-rt-1', now())
                """
            ),
            {
                "id": str(uuid.uuid4()),
                "rfq_id": str(uuid.uuid4()),
                "cp_id": str(uuid.uuid4()),
            },
        )

    queued_count = _row_count(
        engine, "SELECT count(*) FROM rfq_invitations WHERE sent_at IS NULL"
    )
    assert queued_count == 1, f"expected 1 queued row with NULL sent_at, got {queued_count}"
    print(f"       queued rows with sent_at IS NULL: {queued_count}")

    print("[4/6] alembic downgrade -1 (rolls back to 036) — must backfill NULLs first")
    rc = _alembic("downgrade")
    if rc != 0:
        return 2

    # NOT NULLs reasserted; backfill must have run.
    with engine.begin() as conn:
        sent_at_nullable = conn.execute(
            text(
                "SELECT is_nullable FROM information_schema.columns "
                "WHERE table_name='rfq_invitations' AND column_name='sent_at'"
            )
        ).scalar_one()
        assert sent_at_nullable == "NO", "sent_at NOT NULL not reasserted on downgrade"
        prov_nullable = conn.execute(
            text(
                "SELECT is_nullable FROM information_schema.columns "
                "WHERE table_name='rfq_invitations' AND column_name='provider_message_id'"
            )
        ).scalar_one()
        assert prov_nullable == "NO", "provider_message_id NOT NULL not reasserted on downgrade"
        # Backfilled row must have a non-NULL sent_at = created_at and provider_message_id = ''.
        prov_value = conn.execute(
            text(
                "SELECT provider_message_id FROM rfq_invitations LIMIT 1"
            )
        ).scalar_one()
        assert prov_value == "", f"provider_message_id not backfilled to '': {prov_value!r}"

    print("[5/6] alembic upgrade head (re-applies 037)")
    rc = _alembic("upgrade")
    if rc != 0:
        return 3

    with engine.begin() as conn:
        sent_at_nullable = conn.execute(
            text(
                "SELECT is_nullable FROM information_schema.columns "
                "WHERE table_name='rfq_invitations' AND column_name='sent_at'"
            )
        ).scalar_one()
        assert sent_at_nullable == "YES"

    print("[6/6] success: roundtrip clean, queued-row variant survived downgrade backfill")
    return 0


if __name__ == "__main__":
    sys.exit(main())
