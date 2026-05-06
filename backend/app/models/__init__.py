"""Model registry.

Economic precision policy:
- MT quantities use Numeric(15, 3).
- Financial prices and monetary values use Numeric(18, 6).
- Runtime arithmetic uses Decimal quantized via app.core.precision.
"""

from app.models.audit import AuditEvent
from app.models.contracts import (
    HedgeClassification,
    HedgeContract,
    HedgeContractStatus,
    HedgeLegSide,
)
from app.models.cashflow import (
    CashFlowBaselineSnapshot,
    CashFlowLedgerEntry,
    HedgeContractSettlementEvent,
)
from app.models.counterparty import (
    Counterparty,
    CounterpartyType,
    KycStatus,
    SanctionsStatus,
    RiskRating,
)
from app.models.deal import Deal, DealLink, DealLinkedType, DealPNLSnapshot, DealStatus
from app.models.finance_pipeline import (
    FinancePipelineRun,
    FinancePipelineStep,
    PipelineRunStatus,
    PipelineStepStatus,
)
from app.models.exposure import (
    ContractExposure,
    Exposure,
    ExposureDirection,
    ExposureSourceType,
    ExposureStatus,
    HedgeExposure,
    HedgeTask,
    HedgeTaskAction,
    HedgeTaskStatus,
)
from app.models.linkages import HedgeOrderLinkage
from app.models.market_data import CashSettlementPrice
from app.models.mtm import MTMObjectType, MTMSnapshot
from app.models.orders import (
    Order,
    OrderPricingConvention,
    OrderType,
    PriceType,
    PricingType,
    SoPoLink,
)
from app.models.pl import PLSnapshot
from app.models.quotes import RFQQuote
from app.models.rfqs import (
    RFQ,
    RFQDirection,
    RFQIntent,
    RFQInvitation,
    RFQInvitationChannel,
    RFQInvitationStatus,
    RFQSequence,
    RFQState,
    RFQStateEvent,
)

__all__ = [
    "AuditEvent",
    "ContractExposure",
    "Counterparty",
    "CounterpartyType",
    "Deal",
    "DealLink",
    "DealLinkedType",
    "DealPNLSnapshot",
    "DealStatus",
    "Exposure",
    "ExposureDirection",
    "ExposureSourceType",
    "ExposureStatus",
    "HedgeClassification",
    "HedgeContract",
    "HedgeContractStatus",
    "HedgeExposure",
    "HedgeLegSide",
    "HedgeOrderLinkage",
    "HedgeTask",
    "HedgeTaskAction",
    "HedgeTaskStatus",
    "KycStatus",
    "SanctionsStatus",
    "RiskRating",
    "CashFlowBaselineSnapshot",
    "CashFlowLedgerEntry",
    "HedgeContractSettlementEvent",
    "CashSettlementPrice",
    "MTMObjectType",
    "MTMSnapshot",
    "Order",
    "OrderPricingConvention",
    "OrderType",
    "PLSnapshot",
    "PriceType",
    "PricingType",
    "SoPoLink",
    "RFQ",
    "RFQDirection",
    "RFQIntent",
    "RFQInvitation",
    "RFQInvitationChannel",
    "RFQInvitationStatus",
    "RFQQuote",
    "RFQSequence",
    "RFQState",
    "RFQStateEvent",
    "FinancePipelineRun",
    "FinancePipelineStep",
    "PipelineRunStatus",
    "PipelineStepStatus",
]
