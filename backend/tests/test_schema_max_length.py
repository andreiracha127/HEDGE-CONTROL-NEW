"""Tests that max_length constraints on Pydantic schemas reject oversized strings."""

from datetime import date, datetime, timezone
from decimal import Decimal
from uuid import uuid4

import pytest
from pydantic import ValidationError

from app.schemas.audit import AuditEventRead
from app.schemas.cashflow import (
    CashFlowBaselineSnapshotCreate,
    CashFlowItem,
)
from app.schemas.contracts import HedgeContractCreate
from app.schemas.market_data import CashSettlementPriceRead
from app.schemas.mtm import MTMSnapshotCreate, MTMObjectType
from app.schemas.orders import OrderListResponse
from app.schemas.pl import PLSnapshotCreate
from app.schemas.rfq import (
    RFQCreate,
    RFQInvitationCreate,
    RFQQuoteCreate,
    RFQUserActionBase,
    RFQIntent,
    RFQDirection,
    FloatPricingConvention,
)
from app.schemas.scenario import AddCashSettlementPriceOverrideDelta

_UID = uuid4()
_NOW = datetime.now(timezone.utc)
_TODAY = date.today()
_ERR = "string_too_long"


def _too_long(n: int) -> str:
    return "x" * (n + 1)


class TestAuditEventMaxLength:
    def test_entity_type_too_long(self):
        with pytest.raises(ValidationError, match=_ERR):
            AuditEventRead(
                id=_UID,
                timestamp_utc=_NOW,
                entity_type=_too_long(64),
                entity_id=_UID,
                event_type="created",
                payload={},
                checksum="abc",
            )

    def test_checksum_too_long(self):
        with pytest.raises(ValidationError, match=_ERR):
            AuditEventRead(
                id=_UID,
                timestamp_utc=_NOW,
                entity_type="order",
                entity_id=_UID,
                event_type="created",
                payload={},
                checksum=_too_long(128),
            )


class TestCashFlowItemMaxLength:
    def test_object_type_too_long(self):
        with pytest.raises(ValidationError, match=_ERR):
            CashFlowItem(
                object_type=_too_long(64),
                object_id="abc",
                settlement_date=_TODAY,
                amount_usd=Decimal("100"),
                mtm_value=Decimal("50"),
            )


class TestBaselineSnapshotMaxLength:
    def test_correlation_id_too_long(self):
        with pytest.raises(ValidationError, match=_ERR):
            CashFlowBaselineSnapshotCreate(
                as_of_date=_TODAY,
                correlation_id=_too_long(64),
            )


class TestHedgeContractCreateMaxLength:
    def test_commodity_too_long(self):
        with pytest.raises(ValidationError, match=_ERR):
            HedgeContractCreate(
                commodity=_too_long(50),
                quantity_mt=10.0,
                legs=[
                    {"side": "buy", "price_type": "fixed"},
                    {"side": "sell", "price_type": "variable"},
                ],
            )


class TestMTMSnapshotMaxLength:
    def test_object_id_too_long(self):
        with pytest.raises(ValidationError, match=_ERR):
            MTMSnapshotCreate(
                object_type=MTMObjectType.hedge_contract,
                object_id=_too_long(64),
                as_of_date=_TODAY,
                correlation_id="abc",
            )

    def test_correlation_id_too_long(self):
        with pytest.raises(ValidationError, match=_ERR):
            MTMSnapshotCreate(
                object_type=MTMObjectType.hedge_contract,
                object_id="abc",
                as_of_date=_TODAY,
                correlation_id=_too_long(64),
            )


class TestPLSnapshotMaxLength:
    def test_entity_type_too_long(self):
        with pytest.raises(ValidationError, match=_ERR):
            PLSnapshotCreate(
                entity_type=_too_long(32),
                entity_id=_UID,
                period_start=_TODAY,
                period_end=_TODAY,
            )


class TestRFQInvitationMaxLength:
    def test_counterparty_id_must_be_uuid(self):
        with pytest.raises(ValidationError):
            RFQInvitationCreate(
                counterparty_id="not-a-uuid",
            )

    def test_valid_counterparty_id(self):
        inv = RFQInvitationCreate(counterparty_id=_UID)
        assert inv.counterparty_id == _UID


class TestRFQQuoteMaxLength:
    def test_counterparty_id_must_be_uuid(self):
        # Phase A2 PR-1: counterparty_id is a UUID FK, no longer a free-form string.
        with pytest.raises(ValidationError, match="uuid"):
            RFQQuoteCreate(
                rfq_id=_UID,
                counterparty_id="not-a-uuid",
                fixed_price_value="100.000000",
                fixed_price_unit="USD/MT",
                float_pricing_convention=FloatPricingConvention.avg,
                received_at=_NOW,
            )


class TestRFQUserActionMaxLength:
    def test_user_id_too_long(self):
        with pytest.raises(ValidationError, match=_ERR):
            RFQUserActionBase(user_id=_too_long(64))


class TestRFQCreateMaxLength:
    def test_commodity_too_long(self):
        with pytest.raises(ValidationError, match=_ERR):
            RFQCreate(
                intent=RFQIntent.global_position,
                commodity=_too_long(50),
                quantity_mt=10.0,
                delivery_window_start=_TODAY,
                delivery_window_end=_TODAY,
                direction=RFQDirection.buy,
            )


class TestOrderListResponseMaxLength:
    def test_next_cursor_too_long(self):
        with pytest.raises(ValidationError, match=_ERR):
            OrderListResponse(items=[], next_cursor=_too_long(256))


class TestScenarioDeltaMaxLength:
    def test_symbol_too_long(self):
        with pytest.raises(ValidationError, match=_ERR):
            AddCashSettlementPriceOverrideDelta(
                delta_type="add_cash_settlement_price_override",
                symbol=_too_long(64),
                settlement_date=_TODAY,
                price_usd=Decimal("100"),
            )


class TestCashSettlementPriceMaxLength:
    def test_source_url_too_long(self):
        with pytest.raises(ValidationError, match=_ERR):
            CashSettlementPriceRead(
                id="id1",
                source="westmetall",
                symbol="ZN",
                settlement_date=_TODAY,
                price_usd=100.0,
                source_url=_too_long(512),
                html_sha256="abc",
                fetched_at=_NOW,
                created_at=_NOW,
            )
