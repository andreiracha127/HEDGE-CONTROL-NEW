"""Tests for ContractService — unit tests for the contract business logic."""

import uuid
from decimal import Decimal

import pytest
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.models.contracts import (
    HedgeClassification,
    HedgeContract,
    HedgeContractStatus,
    HedgeLegSide,
)
from app.schemas.contracts import (
    HedgeContractCreate,
    HedgeContractRead,
    HedgeContractStatusUpdate,
    HedgeContractUpdate,
    HedgeLeg,
    HedgeLegPriceType,
    HedgeLegSide as HedgeLegSideSchema,
)
from app.services.contract_service import ContractService


# ── Helpers ──────────────────────────────────────────────────────────────

LONG_LEGS = [
    HedgeLeg(side=HedgeLegSideSchema.buy, price_type=HedgeLegPriceType.fixed),
    HedgeLeg(side=HedgeLegSideSchema.sell, price_type=HedgeLegPriceType.variable),
]

SHORT_LEGS = [
    HedgeLeg(side=HedgeLegSideSchema.sell, price_type=HedgeLegPriceType.fixed),
    HedgeLeg(side=HedgeLegSideSchema.buy, price_type=HedgeLegPriceType.variable),
]


def _make_payload(
    *,
    quantity_mt: float = 10.0,
    commodity: str = "LME_AL",
    legs: list[HedgeLeg] | None = None,
    **kwargs,
) -> HedgeContractCreate:
    return HedgeContractCreate(
        commodity=commodity,
        quantity_mt=quantity_mt,
        legs=legs or LONG_LEGS,
        **kwargs,
    )


# ── Create tests ────────────────────────────────────────────────────────


def test_create_contract_long_classification(session: Session) -> None:
    payload = _make_payload(legs=LONG_LEGS)
    contract = ContractService.create(session, payload)

    assert contract.id is not None
    assert contract.classification == HedgeClassification.long
    assert contract.fixed_leg_side == HedgeLegSide.buy
    assert contract.variable_leg_side == HedgeLegSide.sell
    assert contract.status == HedgeContractStatus.active
    assert contract.reference.startswith("HC-")
    read_model = HedgeContractRead.model_validate(contract)
    assert read_model.classification.value == "long"


def test_create_contract_populates_created_by(session: Session) -> None:
    payload = _make_payload(legs=LONG_LEGS)
    contract = ContractService.create(session, payload, created_by="user@example.com")
    assert contract.created_by == "user@example.com"


def test_create_contract_created_by_defaults_none(session: Session) -> None:
    payload = _make_payload(legs=LONG_LEGS)
    contract = ContractService.create(session, payload)
    assert contract.created_by is None
    assert contract.commodity == "LME_AL"
    assert contract.quantity_mt == 10.0


def test_create_contract_short_classification(session: Session) -> None:
    payload = _make_payload(legs=SHORT_LEGS)
    contract = ContractService.create(session, payload)

    assert contract.classification == HedgeClassification.short
    assert contract.fixed_leg_side == HedgeLegSide.sell
    assert contract.variable_leg_side == HedgeLegSide.buy


def test_direct_sql_update_cannot_drift_classification(session: Session) -> None:
    contract = ContractService.create(session, _make_payload(legs=LONG_LEGS))

    with pytest.raises(IntegrityError):
        session.execute(
            text(
                "UPDATE hedge_contracts "
                "SET classification = 'short' "
                "WHERE reference = :reference"
            ),
            {"reference": contract.reference},
        )
        session.commit()

    session.rollback()


def test_orm_update_cannot_drift_classification(session: Session) -> None:
    contract = ContractService.create(session, _make_payload(legs=LONG_LEGS))

    contract.classification = HedgeClassification.short
    with pytest.raises(IntegrityError):
        session.commit()

    session.rollback()


def test_create_contract_default_source_type(session: Session) -> None:
    payload = _make_payload()
    contract = ContractService.create(session, payload)
    assert contract.source_type == "manual"


def test_create_contract_custom_source_type(session: Session) -> None:
    payload = _make_payload(source_type="rfq_award")
    contract = ContractService.create(session, payload)
    assert contract.source_type == "rfq_award"


def test_create_contract_has_trade_date(session: Session) -> None:
    payload = _make_payload()
    contract = ContractService.create(session, payload)
    assert contract.trade_date is not None


def test_create_contract_with_optional_fields(session: Session) -> None:
    payload = _make_payload(
        counterparty_id="CP-001",
        fixed_price_value=2500.0,
        fixed_price_unit="USD/MT",
        float_pricing_convention="LME_CASH",
        premium_discount=5.0,
        notes="Test note",
    )
    contract = ContractService.create(session, payload)
    assert contract.counterparty_id == "CP-001"
    assert contract.fixed_price_value == 2500.0
    assert contract.fixed_price_unit == "USD/MT"
    assert contract.float_pricing_convention == "LME_CASH"
    assert contract.premium_discount == 5.0
    assert contract.notes == "Test note"


# ── List tests ───────────────────────────────────────────────────────────


def test_list_returns_created_contracts(session: Session) -> None:
    ContractService.create(session, _make_payload())
    ContractService.create(session, _make_payload())

    result = ContractService.list(session)
    assert len(result.items) == 2


def test_list_filters_by_commodity(session: Session) -> None:
    ContractService.create(session, _make_payload(commodity="LME_AL"))
    ContractService.create(session, _make_payload(commodity="LME_CU"))

    result = ContractService.list(session, commodity="LME_CU")
    assert len(result.items) == 1
    assert result.items[0].commodity == "LME_CU"


def test_list_filters_by_classification(session: Session) -> None:
    ContractService.create(session, _make_payload(legs=LONG_LEGS))
    ContractService.create(session, _make_payload(legs=SHORT_LEGS))

    result = ContractService.list(session, classification="long")
    assert len(result.items) == 1
    assert result.items[0].classification.value == "long"


def test_list_excludes_deleted_by_default(session: Session) -> None:
    contract = ContractService.create(session, _make_payload())
    ContractService.delete(session, contract.id)

    result = ContractService.list(session)
    assert len(result.items) == 0

    result_with_deleted = ContractService.list(session, include_deleted=True)
    assert len(result_with_deleted.items) == 1


def test_list_respects_limit(session: Session) -> None:
    for _ in range(5):
        ContractService.create(session, _make_payload())

    result = ContractService.list(session, limit=2)
    assert len(result.items) == 2
    assert result.next_cursor is not None


# ── Get by ID tests ──────────────────────────────────────────────────────


def test_get_by_id_returns_contract(session: Session) -> None:
    created = ContractService.create(session, _make_payload())
    fetched = ContractService.get_by_id(session, created.id)
    assert fetched.id == created.id


def test_get_by_id_raises_404(session: Session) -> None:
    from fastapi import HTTPException

    with pytest.raises(HTTPException) as exc:
        ContractService.get_by_id(session, uuid.uuid4())
    assert exc.value.status_code == 404


# ── Archive tests ────────────────────────────────────────────────────────


def test_archive_sets_deleted_at(session: Session) -> None:
    contract = ContractService.create(session, _make_payload())
    archived = ContractService.archive(session, contract.id)
    assert archived.deleted_at is not None


def test_archive_already_archived_raises_409(session: Session) -> None:
    from fastapi import HTTPException

    contract = ContractService.create(session, _make_payload())
    ContractService.archive(session, contract.id)

    with pytest.raises(HTTPException) as exc:
        ContractService.archive(session, contract.id)
    assert exc.value.status_code == 409


def test_archive_nonexistent_raises_404(session: Session) -> None:
    from fastapi import HTTPException

    with pytest.raises(HTTPException) as exc:
        ContractService.archive(session, uuid.uuid4())
    assert exc.value.status_code == 404


# ── Update tests ─────────────────────────────────────────────────────────


def test_update_partial_fields(session: Session) -> None:
    contract = ContractService.create(session, _make_payload())
    payload = HedgeContractUpdate(quantity_mt=99.9, notes="updated")
    updated = ContractService.update(session, contract.id, payload)
    assert updated.quantity_mt == Decimal("99.900")
    assert updated.notes == "updated"


def test_update_empty_payload_raises_400(session: Session) -> None:
    from fastapi import HTTPException

    contract = ContractService.create(session, _make_payload())
    payload = HedgeContractUpdate()

    with pytest.raises(HTTPException) as exc:
        ContractService.update(session, contract.id, payload)
    assert exc.value.status_code == 400


def test_update_deleted_contract_raises_404(session: Session) -> None:
    from fastapi import HTTPException

    contract = ContractService.create(session, _make_payload())
    ContractService.delete(session, contract.id)

    with pytest.raises(HTTPException) as exc:
        ContractService.update(session, contract.id, HedgeContractUpdate(notes="nope"))
    assert exc.value.status_code == 404


# ── Status transition tests ─────────────────────────────────────────────


def test_generic_transition_active_to_settled_is_rejected(session: Session) -> None:
    from fastapi import HTTPException

    contract = ContractService.create(session, _make_payload())
    with pytest.raises(HTTPException) as exc:
        ContractService.transition_status(
            session, contract.id, HedgeContractStatusUpdate(status="settled")
        )
    assert exc.value.status_code == 409
    assert (
        exc.value.detail
        == "Settlement transitions must go through POST /cashflow/contracts/{contract_id}/settle"
    )
    assert contract.status == HedgeContractStatus.active


def test_generic_transition_active_to_partially_settled_is_rejected(
    session: Session,
) -> None:
    from fastapi import HTTPException

    contract = ContractService.create(session, _make_payload())
    with pytest.raises(HTTPException) as exc:
        ContractService.transition_status(
            session, contract.id, HedgeContractStatusUpdate(status="partially_settled")
        )
    assert exc.value.status_code == 409
    assert contract.status == HedgeContractStatus.active


def test_invalid_transition_settled_to_active(session: Session) -> None:
    from fastapi import HTTPException

    contract = ContractService.create(session, _make_payload())
    contract.status = HedgeContractStatus.settled
    session.flush()

    with pytest.raises(HTTPException) as exc:
        ContractService.transition_status(
            session, contract.id, HedgeContractStatusUpdate(status="active")
        )
    assert exc.value.status_code == 409


def test_invalid_status_value_raises_validation_error(session: Session) -> None:
    """Now that HedgeContractStatusUpdate uses the enum, Pydantic rejects
    invalid values before they reach the service layer."""
    from pydantic import ValidationError

    with pytest.raises(ValidationError):
        HedgeContractStatusUpdate(status="bogus")


def test_transition_on_deleted_raises_404(session: Session) -> None:
    from fastapi import HTTPException

    contract = ContractService.create(session, _make_payload())
    ContractService.delete(session, contract.id)

    with pytest.raises(HTTPException) as exc:
        ContractService.transition_status(
            session, contract.id, HedgeContractStatusUpdate(status="settled")
        )
    assert exc.value.status_code == 404


# ── Delete tests ─────────────────────────────────────────────────────────


def test_delete_cancels_and_soft_deletes(session: Session) -> None:
    contract = ContractService.create(session, _make_payload())
    deleted = ContractService.delete(session, contract.id)
    assert deleted.status == HedgeContractStatus.cancelled
    assert deleted.deleted_at is not None


def test_delete_already_deleted_raises_409(session: Session) -> None:
    from fastapi import HTTPException

    contract = ContractService.create(session, _make_payload())
    ContractService.delete(session, contract.id)

    with pytest.raises(HTTPException) as exc:
        ContractService.delete(session, contract.id)
    assert exc.value.status_code == 409


def test_delete_nonexistent_raises_404(session: Session) -> None:
    from fastapi import HTTPException

    with pytest.raises(HTTPException) as exc:
        ContractService.delete(session, uuid.uuid4())
    assert exc.value.status_code == 404
