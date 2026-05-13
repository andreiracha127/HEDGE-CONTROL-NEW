from datetime import date, datetime
from enum import Enum
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.schemas._types import MTQuantity, Price, Spread


class RFQIntent(str, Enum):
    commercial_hedge = "COMMERCIAL_HEDGE"
    global_position = "GLOBAL_POSITION"
    spread = "SPREAD"


class RFQDirection(str, Enum):
    buy = "BUY"
    sell = "SELL"


class RFQState(str, Enum):
    created = "CREATED"
    sent = "SENT"
    quoted = "QUOTED"
    awarded = "AWARDED"
    closed = "CLOSED"


class RFQInvitationChannel(str, Enum):
    whatsapp = "whatsapp"


class RFQInvitationStatus(str, Enum):
    queued = "queued"
    sent = "sent"
    failed = "failed"


class RFQInvitationPurpose(str, Enum):
    """Discriminator for invitation kinds. See `app.models.rfqs`."""

    rfq_invite = "rfq_invite"
    refresh = "refresh"
    reject_quote = "reject_quote"
    award_notify = "award_notify"
    reject_notify = "reject_notify"


class QuoteState(str, Enum):
    """Lifecycle marker for `RFQQuote`. See `app.models.quotes`."""

    active = "active"
    rejected = "rejected"


class RFQInvitationCreate(BaseModel):
    counterparty_id: UUID = Field(
        ..., description="Counterparty UUID — phone is looked up from DB"
    )


class RFQInvitationRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    rfq_id: UUID
    rfq_number: str = Field(..., max_length=32)
    counterparty_id: UUID
    recipient_name: str
    recipient_phone: str
    channel: RFQInvitationChannel
    message_body: str
    # NULL while a queued/failed row has not yet reached the WhatsApp
    # provider. Per Phase A2 PR-4 (J-A2-07), outbox rows are persisted
    # before send, so the column relaxed to nullable.
    provider_message_id: str | None = None
    send_status: RFQInvitationStatus
    purpose: RFQInvitationPurpose = RFQInvitationPurpose.rfq_invite
    sent_at: datetime | None = None
    failure_reason: str | None = None
    idempotency_key: str
    created_at: datetime


class RFQCreate(BaseModel):
    intent: RFQIntent
    commodity: str = Field(..., max_length=50)
    quantity_mt: MTQuantity = Field(  # type: ignore[assignment]
        ..., description="Quantity in metric tons (MT)"
    )
    delivery_window_start: date
    delivery_window_end: date
    direction: RFQDirection
    order_id: UUID | None = Field(None, description="Referenced commercial order ID")
    buy_trade_id: UUID | None = Field(
        None, description="Referenced buy trade (RFQ id) for SPREAD"
    )
    sell_trade_id: UUID | None = Field(
        None, description="Referenced sell trade (RFQ id) for SPREAD"
    )
    invitations: list[RFQInvitationCreate] = Field(default_factory=list)

    # Optional preview texts — if provided, used as WhatsApp message body
    # per counterparty type (bank_br → text_pt, others → text_en)
    text_en: str | None = Field(None, description="English LME text for brokers")
    text_pt: str | None = Field(None, description="Portuguese text for BR banks")

    @model_validator(mode="before")
    @classmethod
    def reject_body_user_id(cls, data):
        if isinstance(data, dict) and "user_id" in data:
            raise ValueError(
                "user_id is not accepted on POST /rfqs; actor identity is derived "
                "from the authenticated JWT sub"
            )
        return data

    @model_validator(mode="after")
    def validate_intent(self) -> "RFQCreate":
        if self.quantity_mt <= 0:
            raise ValueError("quantity_mt must be greater than zero")
        if self.intent == RFQIntent.commercial_hedge and self.order_id is None:
            raise ValueError("order_id is required for COMMERCIAL_HEDGE")
        if self.intent == RFQIntent.global_position and self.order_id is not None:
            raise ValueError("order_id must be empty for GLOBAL_POSITION")
        if self.intent == RFQIntent.spread:
            if self.order_id is not None:
                raise ValueError("order_id must be empty for SPREAD")
            if self.buy_trade_id is None or self.sell_trade_id is None:
                raise ValueError(
                    "buy_trade_id and sell_trade_id are required for SPREAD"
                )
            if self.buy_trade_id == self.sell_trade_id:
                raise ValueError("buy_trade_id and sell_trade_id must be different")
        return self


class FloatPricingConvention(str, Enum):
    avg = "avg"
    avginter = "avginter"
    c2r = "c2r"


class RFQQuoteCreate(BaseModel):
    rfq_id: UUID
    counterparty_id: UUID
    fixed_price_value: Price
    fixed_price_unit: str = Field(..., max_length=32)
    float_pricing_convention: FloatPricingConvention
    received_at: datetime


class RFQQuoteRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    rfq_id: UUID
    counterparty_id: UUID
    fixed_price_value: Price
    fixed_price_unit: str = Field(..., max_length=32)
    float_pricing_convention: FloatPricingConvention
    received_at: datetime
    created_at: datetime
    # Per J-A2-08, rejected quotes are preserved as evidence; the read
    # route at /rfqs/{id}/quotes returns both `active` and `rejected`
    # rows so operators can audit the population a trader saw at award
    # time. Rankers and latest-quote selection filter rejected quotes at
    # the upstream query (not in this schema).
    state: QuoteState = QuoteState.active
    rejected_at: datetime | None = None
    rejected_reason: str | None = None
    rejected_by: str | None = None


class SpreadRankingFailureCode(str, Enum):
    no_eligible_quotes = "NO_ELIGIBLE_QUOTES"
    non_comparable = "NON_COMPARABLE"
    incomplete_quotes = "INCOMPLETE_QUOTES"
    tie = "TIE"
    not_spread_intent = "NOT_SPREAD_INTENT"


class SpreadRankingEntry(BaseModel):
    rank: int
    counterparty_id: UUID
    spread_value: Spread
    buy_quote: RFQQuoteRead
    sell_quote: RFQQuoteRead


class SpreadRankingRead(BaseModel):
    rfq_id: UUID
    status: str = Field(..., max_length=32)
    failure_code: SpreadRankingFailureCode | None = None
    failure_reason: str | None = Field(None, max_length=500)
    direction: RFQDirection | None = None
    sort_order: str | None = None
    ranking: list[SpreadRankingEntry] = Field(default_factory=list)


class TradeRankingFailureCode(str, Enum):
    no_eligible_quotes = "NO_ELIGIBLE_QUOTES"
    non_comparable = "NON_COMPARABLE"
    tie = "TIE"
    not_trade_intent = "NOT_TRADE_INTENT"


class TradeRankingEntry(BaseModel):
    rank: int
    quote: RFQQuoteRead


class TradeRankingRead(BaseModel):
    rfq_id: UUID
    status: str = Field(..., max_length=32)
    failure_code: TradeRankingFailureCode | None = None
    failure_reason: str | None = Field(None, max_length=500)
    ranking: list[TradeRankingEntry] = Field(default_factory=list)


class RFQUserActionBase(BaseModel):
    model_config = ConfigDict(extra="forbid")


class RFQRejectRequest(RFQUserActionBase):
    pass


class RFQRefreshRequest(RFQUserActionBase):
    pass


class RFQAwardRequest(RFQUserActionBase):
    pass


class RFQRejectQuoteRequest(RFQUserActionBase):
    """Reject a specific counterparty quote without closing the RFQ."""

    pass


class RFQCancelRequest(RFQUserActionBase):
    """Cancel an RFQ in CREATED or SENT state."""

    pass


class RFQRefreshCounterpartyRequest(RFQUserActionBase):
    """Re-send invitation to a specific counterparty."""

    counterparty_id: str = Field(..., max_length=100)


class RFQRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    rfq_number: str = Field(..., max_length=32)
    intent: RFQIntent
    commodity: str = Field(..., max_length=50)
    quantity_mt: MTQuantity
    delivery_window_start: date
    delivery_window_end: date
    direction: RFQDirection
    order_id: UUID | None
    buy_trade_id: UUID | None
    sell_trade_id: UUID | None
    commercial_active_mt: MTQuantity
    commercial_passive_mt: MTQuantity
    commercial_net_mt: MTQuantity
    commercial_reduction_applied_mt: MTQuantity
    exposure_snapshot_timestamp: datetime
    state: RFQState
    created_at: datetime
    deleted_at: datetime | None = None
    invitations: list[RFQInvitationRead] = Field(default_factory=list)


class RFQStateEventRead(BaseModel):
    """Read schema for RFQ state transition events (timeline)."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    rfq_id: UUID
    from_state: RFQState | None = None
    to_state: RFQState
    trigger: str | None = None
    triggering_quote_id: UUID | None = None
    triggering_counterparty_id: str | None = None
    event_timestamp: datetime | None = None
    user_id: str | None = None
    reason: str | None = None
    ranking_snapshot: str | None = None
    winning_quote_ids: str | None = None
    winning_counterparty_ids: str | None = None
    award_timestamp: datetime | None = None
    created_contract_ids: str | None = None
    created_at: datetime


class RFQListResponse(BaseModel):
    items: list[RFQRead]
    next_cursor: str | None = Field(None, max_length=256)


# ─────────────────────────────────────────────────────────────────────────────
# Preview-text (RFQ engine integration)
# ─────────────────────────────────────────────────────────────────────────────


class RFQPriceTypeEnum(str, Enum):
    avg = "AVG"
    avginter = "AVGInter"
    fix = "Fix"
    c2r = "C2R"


class RFQSideEnum(str, Enum):
    buy = "buy"
    sell = "sell"


class RFQTradeTypeEnum(str, Enum):
    swap = "Swap"
    forward = "Forward"


class RFQOrderTypeEnum(str, Enum):
    at_market = "At Market"
    limit = "Limit"
    range = "Range"
    resting = "Resting"


class RFQLegInput(BaseModel):
    side: RFQSideEnum
    price_type: RFQPriceTypeEnum
    quantity_mt: MTQuantity = Field(..., gt=0)  # type: ignore[assignment]

    # AVG
    month_name: str | None = Field(None, max_length=20)
    year: int | None = None

    # AVGInter
    start_date: date | None = None
    end_date: date | None = None

    # Fix / C2R
    fixing_date: date | None = None

    # Order instruction (optional)
    order_type: RFQOrderTypeEnum | None = None
    order_validity: str | None = Field(None, max_length=30)
    order_limit_price: str | None = Field(None, max_length=30)


class RFQTextPreviewRequest(BaseModel):
    """Request body for the RFQ text preview endpoint."""

    trade_type: RFQTradeTypeEnum
    leg1: RFQLegInput
    leg2: RFQLegInput | None = None
    sync_ppt: bool = False
    company_header: str | None = Field(None, max_length=200)
    company_label_for_payoff: str = Field("Alcast", max_length=100)
    channel_type: str = Field("BROKER_LME", max_length=30)


class RFQTextPreviewResponse(BaseModel):
    """Response from the RFQ text preview endpoint."""

    text: str
    text_en: str | None = None
    text_pt: str | None = None
    leg1_ppt: date | None = None
    leg2_ppt: date | None = None
    trade_ppt: date | None = None
