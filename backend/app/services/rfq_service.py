"""RFQ business logic extracted from the route layer.

Every public method receives a ``Session`` and returns domain objects or
Pydantic schemas.  The caller (route) is responsible for ``session.commit()``,
audit marking and HTTP-response formatting.
"""

from __future__ import annotations

import json
import uuid as _uuid
from decimal import Decimal
from uuid import UUID

from fastapi import HTTPException, status
from sqlalchemy.orm import Session

from app.core.precision import DECIMAL_ZERO, quantize_mt

from app.models.contracts import HedgeClassification, HedgeContract, HedgeLegSide
from app.models.counterparty import Counterparty, CounterpartyType
from app.models.orders import Order, OrderType, PriceType
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
from app.schemas.rfq import (
    RFQCreate,
    RFQQuoteCreate,
    RFQQuoteRead,
    SpreadRankingEntry,
    SpreadRankingFailureCode,
    SpreadRankingRead,
    TradeRankingEntry,
    TradeRankingFailureCode,
    TradeRankingRead,
)
from app.services.exposure_service import ExposureService
from app.services.linkage_service import LinkageService
from app.services.price_lookup_service import canonical_commodity
from app.services.whatsapp_service import WhatsAppService
from app.core.logging import get_logger
from app.core.utils import now_utc

_logger = get_logger()

# Default WhatsApp messages for per-counterparty actions
_DEFAULT_MESSAGES = {
    "refresh": {
        "pt": "Atualize o preço por favor",
        "en": "Refresh, please",
    },
    "reject": {
        "pt": "Fechamos aqui, muito obrigado pela cotação",
        "en": "Closed here, thanks for the quote",
    },
    "contract": {
        "pt": "Fechado no último preço",
        "en": "Book in the last price",
    },
}


def _pick_action_message(cp: Counterparty | None, action: str) -> str:
    """Return the correct language message for a counterparty action."""
    msgs = _DEFAULT_MESSAGES.get(action, _DEFAULT_MESSAGES["refresh"])
    if cp and cp.type == CounterpartyType.bank_br:
        return msgs["pt"]
    return msgs["en"]


class RFQService:
    """Pure business-logic for the RFQ lifecycle."""

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    @staticmethod
    def canonicalize_fixed_price_unit(unit: str) -> str | None:
        """Return ``'USD/MT'`` when *unit* is a known variant, else ``None``."""
        normalized = (
            unit.strip().upper().replace("/", "").replace("-", "").replace(" ", "")
        )
        if normalized == "USDMT":
            return "USD/MT"
        return None

    @staticmethod
    def select_latest_quotes_by_counterparty(
        quotes: list[RFQQuote],
    ) -> dict[UUID, RFQQuote]:
        """Given an unordered list of quotes, return the latest per counterparty."""
        ordered = sorted(
            quotes,
            key=lambda q: (
                str(q.counterparty_id),
                q.received_at,
                q.created_at,
                str(q.id),
            ),
        )
        latest: dict[UUID, RFQQuote] = {}
        current_cp: UUID | None = None
        best: RFQQuote | None = None

        for quote in ordered:
            if current_cp is None:
                current_cp = quote.counterparty_id
                best = quote
                continue
            if quote.counterparty_id != current_cp:
                if best is not None:
                    latest[current_cp] = best
                current_cp = quote.counterparty_id
                best = quote
                continue

            if best is None:
                raise ValueError("best_for_counterparty must not be None")

            if (quote.received_at, quote.created_at, str(quote.id)) > (
                best.received_at,
                best.created_at,
                str(best.id),
            ):
                best = quote

        if current_cp is not None and best is not None:
            latest[current_cp] = best
        return latest

    @staticmethod
    def get_latest_trade_quotes(session: Session, rfq_id: UUID) -> dict[UUID, RFQQuote]:
        quotes = session.query(RFQQuote).filter(RFQQuote.rfq_id == rfq_id).all()
        return RFQService.select_latest_quotes_by_counterparty(quotes)

    @staticmethod
    def determine_contract_legs(
        direction: RFQDirection,
    ) -> tuple[HedgeLegSide, HedgeLegSide, HedgeClassification]:
        if direction == RFQDirection.buy:
            return HedgeLegSide.buy, HedgeLegSide.sell, HedgeClassification.long
        return HedgeLegSide.sell, HedgeLegSide.buy, HedgeClassification.short

    # ------------------------------------------------------------------
    # Ranking
    # ------------------------------------------------------------------

    @staticmethod
    def compute_trade_ranking(
        rfq: RFQ, latest_quotes: dict[UUID, RFQQuote]
    ) -> TradeRankingRead:
        if not latest_quotes:
            return TradeRankingRead(
                rfq_id=rfq.id,
                status="FAILURE",
                failure_code=TradeRankingFailureCode.no_eligible_quotes,
                failure_reason="Zero eligible quotes",
                ranking=[],
            )

        quotes = list(latest_quotes.values())
        canonical_units: list[str] = []
        for q in quotes:
            canonical = RFQService.canonicalize_fixed_price_unit(q.fixed_price_unit)
            if not canonical:
                return TradeRankingRead(
                    rfq_id=rfq.id,
                    status="FAILURE",
                    failure_code=TradeRankingFailureCode.non_comparable,
                    failure_reason="Non-canonical fixed_price_unit",
                    ranking=[],
                )
            canonical_units.append(canonical)

        if len(set(canonical_units)) != 1:
            return TradeRankingRead(
                rfq_id=rfq.id,
                status="FAILURE",
                failure_code=TradeRankingFailureCode.non_comparable,
                failure_reason="fixed_price_unit mismatch",
                ranking=[],
            )

        reverse = rfq.direction == RFQDirection.sell
        ordered = sorted(quotes, key=lambda q: q.fixed_price_value, reverse=reverse)
        values = [q.fixed_price_value for q in ordered]
        if len(set(values)) != len(values):
            return TradeRankingRead(
                rfq_id=rfq.id,
                status="FAILURE",
                failure_code=TradeRankingFailureCode.tie,
                failure_reason="Tie detected",
                ranking=[],
            )

        ranking = [
            TradeRankingEntry(rank=i + 1, quote=RFQQuoteRead.model_validate(q))
            for i, q in enumerate(ordered)
        ]
        return TradeRankingRead(rfq_id=rfq.id, status="SUCCESS", ranking=ranking)

    @staticmethod
    def compute_spread_ranking(session: Session, rfq: RFQ) -> SpreadRankingRead:
        if rfq.intent != RFQIntent.spread:
            return SpreadRankingRead(
                rfq_id=rfq.id,
                status="FAILURE",
                failure_code=SpreadRankingFailureCode.not_spread_intent,
                failure_reason="Ranking is only defined for intent=SPREAD",
                ranking=[],
            )

        buy_rfq = session.get(RFQ, rfq.buy_trade_id) if rfq.buy_trade_id else None
        sell_rfq = session.get(RFQ, rfq.sell_trade_id) if rfq.sell_trade_id else None
        if not buy_rfq or not sell_rfq:
            return SpreadRankingRead(
                rfq_id=rfq.id,
                status="FAILURE",
                failure_code=SpreadRankingFailureCode.non_comparable,
                failure_reason="Referenced trade RFQ missing",
                ranking=[],
            )

        if buy_rfq.commodity != sell_rfq.commodity:
            return SpreadRankingRead(
                rfq_id=rfq.id,
                status="FAILURE",
                failure_code=SpreadRankingFailureCode.non_comparable,
                failure_reason="Trade RFQ commodity mismatch",
                ranking=[],
            )

        buy_quotes = session.query(RFQQuote).filter(RFQQuote.rfq_id == buy_rfq.id).all()
        sell_quotes = (
            session.query(RFQQuote).filter(RFQQuote.rfq_id == sell_rfq.id).all()
        )

        buy_latest = RFQService.select_latest_quotes_by_counterparty(buy_quotes)
        sell_latest = RFQService.select_latest_quotes_by_counterparty(sell_quotes)

        buy_keys = set(buy_latest.keys())
        sell_keys = set(sell_latest.keys())
        all_counterparties = buy_keys | sell_keys
        incomplete = sorted(
            (
                cp
                for cp in all_counterparties
                if cp not in buy_keys or cp not in sell_keys
            ),
            key=str,
        )
        if incomplete:
            incomplete_display = [str(cp) for cp in incomplete[:5]]
            suffix = "..." if len(incomplete) > 5 else ""
            return SpreadRankingRead(
                rfq_id=rfq.id,
                status="FAILURE",
                failure_code=SpreadRankingFailureCode.incomplete_quotes,
                failure_reason=(
                    f"{len(incomplete)} counterpart(ies) quoted only one leg: "
                    f"{', '.join(incomplete_display)}{suffix}"
                ),
                ranking=[],
            )

        eligible_counterparties = sorted(buy_keys & sell_keys, key=str)
        if not eligible_counterparties:
            return SpreadRankingRead(
                rfq_id=rfq.id,
                status="FAILURE",
                failure_code=SpreadRankingFailureCode.no_eligible_quotes,
                failure_reason="Zero eligible quotes",
                ranking=[],
            )

        spreads: list[tuple[UUID, Decimal, RFQQuote, RFQQuote]] = []
        for cp in eligible_counterparties:
            buy_quote = buy_latest[cp]
            sell_quote = sell_latest[cp]

            buy_unit = RFQService.canonicalize_fixed_price_unit(
                buy_quote.fixed_price_unit
            )
            sell_unit = RFQService.canonicalize_fixed_price_unit(
                sell_quote.fixed_price_unit
            )
            if not buy_unit or not sell_unit:
                return SpreadRankingRead(
                    rfq_id=rfq.id,
                    status="FAILURE",
                    failure_code=SpreadRankingFailureCode.non_comparable,
                    failure_reason="Non-canonical fixed_price_unit",
                    ranking=[],
                )
            if buy_unit != sell_unit:
                return SpreadRankingRead(
                    rfq_id=rfq.id,
                    status="FAILURE",
                    failure_code=SpreadRankingFailureCode.non_comparable,
                    failure_reason="fixed_price_unit mismatch between trades",
                    ranking=[],
                )

            spreads.append(
                (
                    cp,
                    sell_quote.fixed_price_value - buy_quote.fixed_price_value,
                    buy_quote,
                    sell_quote,
                )
            )

        spread_values = [s[1] for s in spreads]
        if len(set(spread_values)) != len(spread_values):
            return SpreadRankingRead(
                rfq_id=rfq.id,
                status="FAILURE",
                failure_code=SpreadRankingFailureCode.tie,
                failure_reason="Tie detected",
                ranking=[],
            )

        reverse = rfq.direction == RFQDirection.sell
        ordered = sorted(spreads, key=lambda s: s[1], reverse=reverse)
        ranking: list[SpreadRankingEntry] = []
        for idx, (cp, spread_value, buy_quote, sell_quote) in enumerate(
            ordered, start=1
        ):
            ranking.append(
                SpreadRankingEntry(
                    rank=idx,
                    counterparty_id=cp,
                    spread_value=spread_value,
                    buy_quote=RFQQuoteRead.model_validate(buy_quote),
                    sell_quote=RFQQuoteRead.model_validate(sell_quote),
                )
            )

        return SpreadRankingRead(
            rfq_id=rfq.id,
            status="SUCCESS",
            direction=rfq.direction,
            sort_order="max_spread" if reverse else "min_spread",
            ranking=ranking,
        )

    # ------------------------------------------------------------------
    # CRUD + lifecycle
    # ------------------------------------------------------------------

    @staticmethod
    def _convention_value(value: object) -> str:
        return value.value if hasattr(value, "value") else str(value)

    @staticmethod
    def create(session: Session, payload: RFQCreate) -> RFQ:
        """Create an RFQ, its invitations and initial state events.

        The caller must ``session.commit()`` afterwards.
        """
        snapshot_rows = ExposureService.compute_commercial_snapshot(session)
        snapshot_by_commodity = {
            canonical_commodity(row["commodity"]): row for row in snapshot_rows
        }

        def snapshot_for(commodity: str | None) -> dict:
            canonical = canonical_commodity(commodity)
            if canonical is not None and canonical in snapshot_by_commodity:
                return snapshot_by_commodity[canonical]
            return {
                "commodity": canonical or commodity or payload.commodity,
                "pre_reduction_commercial_active_mt": DECIMAL_ZERO,
                "pre_reduction_commercial_passive_mt": DECIMAL_ZERO,
                "commercial_active_mt": DECIMAL_ZERO,
                "commercial_passive_mt": DECIMAL_ZERO,
                "calculation_timestamp": now_utc(),
            }

        order: Order | None = None
        snapshot = snapshot_for(payload.commodity)
        if payload.intent.value == RFQIntent.commercial_hedge.value:
            order = session.get(Order, payload.order_id)
            if not order:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail="Order not found",
                )
            if order.price_type != PriceType.variable:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="Order must be variable-price",
                )
            expected_direction = (
                "SELL" if order.order_type == OrderType.sales else "BUY"
            )
            if payload.direction.value != expected_direction:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="RFQ direction mismatch for order type",
                )
            if canonical_commodity(payload.commodity) != canonical_commodity(
                order.commodity
            ):
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=(
                        "RFQ commodity must match order commodity for "
                        "COMMERCIAL_HEDGE"
                    ),
                )
            snapshot = snapshot_for(order.commodity)
            post_active = quantize_mt(snapshot["commercial_active_mt"])
            post_passive = quantize_mt(snapshot["commercial_passive_mt"])
            residual_side = (
                post_active if order.order_type == OrderType.sales else post_passive
            )
            if quantize_mt(payload.quantity_mt) > residual_side:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="RFQ quantity exceeds residual exposure",
                )
        else:
            post_active = quantize_mt(snapshot["commercial_active_mt"])
            post_passive = quantize_mt(snapshot["commercial_passive_mt"])
        pre_active = quantize_mt(snapshot["pre_reduction_commercial_active_mt"])

        if payload.intent.value == RFQIntent.spread.value:
            buy_trade_rfq = session.get(RFQ, payload.buy_trade_id)
            sell_trade_rfq = session.get(RFQ, payload.sell_trade_id)
            if not buy_trade_rfq or not sell_trade_rfq:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="Referenced trade RFQ not found",
                )
            if (
                buy_trade_rfq.intent == RFQIntent.spread
                or sell_trade_rfq.intent == RFQIntent.spread
            ):
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="Referenced trade RFQ cannot be SPREAD",
                )

        seq = RFQSequence()
        session.add(seq)
        session.flush()
        year = now_utc().year
        rfq_number = f"RFQ-{year}-{int(seq.id):06d}"

        initial_state = RFQState.created

        rfq = RFQ(
            rfq_number=rfq_number,
            intent=RFQIntent(payload.intent.value),
            commodity=payload.commodity,
            quantity_mt=payload.quantity_mt,
            delivery_window_start=payload.delivery_window_start,
            delivery_window_end=payload.delivery_window_end,
            direction=RFQDirection(payload.direction.value),
            text_en=payload.text_en,
            text_pt=payload.text_pt,
            order_id=payload.order_id,
            buy_trade_id=payload.buy_trade_id,
            sell_trade_id=payload.sell_trade_id,
            commercial_active_mt=post_active,
            commercial_passive_mt=post_passive,
            commercial_net_mt=post_active - post_passive,
            commercial_reduction_applied_mt=pre_active - post_active,
            exposure_snapshot_timestamp=snapshot["calculation_timestamp"],
            state=initial_state,
        )
        session.add(rfq)
        session.flush()

        for invitation in payload.invitations:
            # Look up counterparty from DB to get whatsapp_phone
            cp = session.get(Counterparty, invitation.counterparty_id)
            if not cp:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail=f"Counterparty {invitation.counterparty_id} not found",
                )
            if not cp.whatsapp_phone:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=f"Counterparty {cp.name} has no WhatsApp phone number",
                )

            phone = cp.whatsapp_phone
            idem_key = f"{rfq.rfq_number}:{cp.id}"
            send_status = RFQInvitationStatus.queued
            provider_message_id = ""

            # --- Send WhatsApp message ---
            # Use the preview text matching the counterparty language:
            # bank_br → Portuguese, all others → English LME
            fallback_body = (
                f"RFQ {rfq.rfq_number} — {rfq.commodity} "
                f"{rfq.quantity_mt}MT {rfq.direction.value}"
            )
            if cp.type == CounterpartyType.bank_br and payload.text_pt:
                message_body = payload.text_pt
            elif payload.text_en:
                message_body = payload.text_en
            else:
                message_body = fallback_body

            result = WhatsAppService.send_text_message(
                phone=phone,
                text=message_body,
            )
            if result.success:
                send_status = RFQInvitationStatus.sent
                provider_message_id = result.provider_message_id or ""
                _logger.info(
                    "rfq_whatsapp_sent",
                    rfq_number=rfq.rfq_number,
                    recipient=phone,
                )
            else:
                send_status = RFQInvitationStatus.failed
                _logger.error(
                    "rfq_whatsapp_failed",
                    rfq_number=rfq.rfq_number,
                    recipient=phone,
                    error_code=result.error_code,
                    error_message=result.error_message,
                )

            session.add(
                RFQInvitation(
                    rfq_id=rfq.id,
                    rfq_number=rfq.rfq_number,
                    counterparty_id=cp.id,
                    recipient_name=cp.short_name or cp.name,
                    recipient_phone=phone,
                    channel=RFQInvitationChannel.whatsapp,
                    message_body=message_body,
                    provider_message_id=provider_message_id,
                    send_status=send_status,
                    sent_at=now_utc()
                    if send_status == RFQInvitationStatus.sent
                    else None,
                    idempotency_key=idem_key,
                )
            )

        # If any invitation was successfully sent, transition to SENT
        session.flush()  # ensure pending invitation INSERTs are visible
        has_sent = (
            session.query(RFQInvitation)
            .filter(
                RFQInvitation.rfq_id == rfq.id,
                RFQInvitation.send_status == RFQInvitationStatus.sent,
            )
            .first()
            is not None
        )
        if has_sent:
            rfq.state = RFQState.sent
            session.add(
                RFQStateEvent(
                    rfq_id=rfq.id,
                    from_state=RFQState.created,
                    to_state=RFQState.sent,
                    event_timestamp=now_utc(),
                )
            )

        return rfq

    @staticmethod
    def get(session: Session, rfq_id: UUID) -> RFQ:
        """Fetch an RFQ or raise 404. Audit-history loader; does NOT filter archived."""
        rfq = session.get(RFQ, rfq_id)
        if not rfq:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="RFQ not found",
            )
        return rfq

    @staticmethod
    def get_live(session: Session, rfq_id: UUID) -> RFQ:
        """Fetch an active RFQ; reject archived rows.

        Mutation paths must use this loader. Returns 404 if missing,
        409 if archived (``deleted_at`` set). Constitution §2.1 —
        archived RFQs are outside the active lifecycle.
        """
        rfq = session.get(RFQ, rfq_id)
        if not rfq:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="RFQ not found",
            )
        if rfq.deleted_at is not None:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="RFQ is archived",
            )
        return rfq

    @staticmethod
    def archive(session: Session, rfq_id: UUID, user_id: str) -> RFQ:
        """Archive an RFQ. Allowed only from the terminal ``CLOSED`` state.

        ``RFQState.closed`` is the unique terminal state — both
        ``cancel`` and ``reject`` route through it, and ``award`` exits
        ``AWARDED → CLOSED`` automatically. Active states (``created``,
        ``sent``, ``quoted``, ``awarded``) are not archivable; the RFQ
        is still in flight.

        Emits a ``RFQStateEvent`` with ``trigger='archive'`` so the
        archive action is auditable like every other lifecycle event.
        ``deleted_at`` is the lifecycle marker; ``RFQState`` itself
        does not change (the row is already CLOSED).
        """
        rfq = session.get(RFQ, rfq_id)
        if not rfq:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="RFQ not found",
            )
        if rfq.deleted_at is not None:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="RFQ already archived",
            )
        if rfq.state != RFQState.closed:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="RFQ must be in CLOSED state before archiving",
            )
        archive_time = now_utc()
        rfq.deleted_at = archive_time
        session.add(
            RFQStateEvent(
                rfq_id=rfq.id,
                from_state=rfq.state,
                to_state=rfq.state,
                trigger="archive",
                user_id=user_id,
                event_timestamp=archive_time,
            )
        )
        return rfq

    @staticmethod
    def get_invitations(session: Session, rfq_id: UUID) -> list[RFQInvitation]:
        return (
            session.query(RFQInvitation)
            .filter(RFQInvitation.rfq_id == rfq_id)
            .order_by(RFQInvitation.created_at.asc())
            .all()
        )

    @staticmethod
    def submit_quote(
        session: Session, rfq_id: UUID, payload: RFQQuoteCreate
    ) -> RFQQuote:
        """Persist a quote and handle state transitions.

        The caller must ``session.commit()`` afterwards.
        """
        rfq = RFQService.get_live(session, rfq_id)

        if rfq.intent == RFQIntent.spread:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="SPREAD RFQ cannot receive quotes",
            )
        if payload.rfq_id != rfq_id:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="RFQ id mismatch",
            )
        if rfq.state not in (RFQState.sent, RFQState.quoted):
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="RFQ must be SENT before receiving quotes",
            )

        cp = session.get(Counterparty, payload.counterparty_id)
        if not cp:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Counterparty {payload.counterparty_id} not found",
            )

        quote = RFQQuote(
            rfq_id=rfq_id,
            counterparty_id=payload.counterparty_id,
            fixed_price_value=payload.fixed_price_value,
            fixed_price_unit=payload.fixed_price_unit,
            float_pricing_convention=payload.float_pricing_convention.value,
            received_at=payload.received_at,
        )
        session.add(quote)
        session.flush()

        if rfq.state == RFQState.sent:
            rfq.state = RFQState.quoted
            session.add(
                RFQStateEvent(
                    rfq_id=rfq.id,
                    from_state=RFQState.sent,
                    to_state=RFQState.quoted,
                    trigger="FIRST_ELIGIBLE_QUOTE_PERSISTED",
                    triggering_quote_id=quote.id,
                    triggering_counterparty_id=str(quote.counterparty_id),
                    event_timestamp=now_utc(),
                )
            )

        # Propagate to parent SPREAD RFQs
        parent_spreads = (
            session.query(RFQ)
            .filter(
                RFQ.intent == RFQIntent.spread,
                RFQ.state == RFQState.sent,
                (RFQ.buy_trade_id == rfq.id) | (RFQ.sell_trade_id == rfq.id),
            )
            .all()
        )
        for spread_rfq in parent_spreads:
            if spread_rfq.buy_trade_id is None or spread_rfq.sell_trade_id is None:
                continue
            buy_latest = RFQService.get_latest_trade_quotes(
                session, spread_rfq.buy_trade_id
            )
            sell_latest = RFQService.get_latest_trade_quotes(
                session, spread_rfq.sell_trade_id
            )
            if set(buy_latest.keys()) & set(sell_latest.keys()):
                spread_rfq.state = RFQState.quoted
                session.add(
                    RFQStateEvent(
                        rfq_id=spread_rfq.id,
                        from_state=RFQState.sent,
                        to_state=RFQState.quoted,
                        trigger="FIRST_ELIGIBLE_QUOTE_PERSISTED",
                        triggering_quote_id=quote.id,
                        triggering_counterparty_id=str(quote.counterparty_id),
                        event_timestamp=now_utc(),
                    )
                )

        return quote

    @staticmethod
    def reject(session: Session, rfq_id: UUID, user_id: str) -> RFQ:
        """Reject an RFQ (QUOTED → CLOSED).

        The caller must ``session.commit()`` afterwards.
        """
        rfq = RFQService.get_live(session, rfq_id)
        if rfq.state != RFQState.quoted:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="RFQ must be in QUOTED state",
            )

        rfq.state = RFQState.closed
        session.add(
            RFQStateEvent(
                rfq_id=rfq.id,
                from_state=RFQState.quoted,
                to_state=RFQState.closed,
                user_id=user_id,
                reason="USER_REJECTED",
                event_timestamp=now_utc(),
            )
        )
        return rfq

    @staticmethod
    def cancel(session: Session, rfq_id: UUID, user_id: str) -> RFQ:
        """Cancel an RFQ (CREATED/SENT → CLOSED).

        The caller must ``session.commit()`` afterwards.
        """
        rfq = RFQService.get_live(session, rfq_id)
        if rfq.state not in (RFQState.created, RFQState.sent):
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="RFQ must be in CREATED or SENT state to cancel",
            )

        prev_state = rfq.state
        rfq.state = RFQState.closed
        session.add(
            RFQStateEvent(
                rfq_id=rfq.id,
                from_state=prev_state,
                to_state=RFQState.closed,
                user_id=user_id,
                reason="USER_CANCELLED",
                event_timestamp=now_utc(),
            )
        )
        return rfq

    @staticmethod
    def refresh(session: Session, rfq_id: UUID, user_id: str) -> RFQ:
        """Re-send invitations for an RFQ in SENT or QUOTED state.

        The caller must ``session.commit()`` afterwards.
        """
        rfq = RFQService.get_live(session, rfq_id)
        if rfq.state not in (RFQState.sent, RFQState.quoted):
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="RFQ must be in SENT or QUOTED state",
            )

        existing = (
            session.query(RFQInvitation)
            .filter(RFQInvitation.rfq_id == rfq.id)
            .order_by(RFQInvitation.created_at.asc())
            .all()
        )
        recipients: dict[str, RFQInvitation] = {}
        for inv in existing:
            cp_key = (
                str(inv.counterparty_id) if inv.counterparty_id else inv.recipient_phone
            )
            if cp_key not in recipients:
                recipients[cp_key] = inv

        if not recipients:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="No recipients to refresh",
            )

        refresh_header = (
            f"RFQ#{rfq.rfq_number} — REFRESH: please resend your FIXED price quote."
        )
        now = now_utc()
        for recipient in recipients.values():
            # Fetch the current phone from the Counterparty table in case
            # it has been updated since the original invitation was created.
            current_phone = recipient.recipient_phone
            cp = None
            if recipient.counterparty_id:
                cp = session.get(Counterparty, recipient.counterparty_id)
                if cp and cp.whatsapp_phone:
                    current_phone = cp.whatsapp_phone

            # Choose the right language text for this counterparty
            if cp and cp.type == CounterpartyType.bank_br and rfq.text_pt:
                message_body = rfq.text_pt
            elif rfq.text_en:
                message_body = rfq.text_en
            else:
                message_body = refresh_header

            send_status = RFQInvitationStatus.queued
            provider_msg_id = f"refresh-{rfq.rfq_number}-{current_phone}"

            if recipient.channel == RFQInvitationChannel.whatsapp:
                result = WhatsAppService.send_text_message(
                    phone=current_phone,
                    text=message_body,
                )
                if result.success:
                    send_status = RFQInvitationStatus.sent
                    provider_msg_id = result.provider_message_id or provider_msg_id
                    _logger.info(
                        "rfq_refresh_whatsapp_sent",
                        rfq_number=rfq.rfq_number,
                        recipient=current_phone,
                    )
                else:
                    send_status = RFQInvitationStatus.failed
                    _logger.error(
                        "rfq_refresh_whatsapp_failed",
                        rfq_number=rfq.rfq_number,
                        recipient=current_phone,
                        error_code=result.error_code,
                        error_message=result.error_message,
                    )

            session.add(
                RFQInvitation(
                    rfq_id=rfq.id,
                    rfq_number=rfq.rfq_number,
                    counterparty_id=recipient.counterparty_id,
                    recipient_phone=current_phone,
                    recipient_name=recipient.recipient_name,
                    channel=recipient.channel,
                    message_body=message_body,
                    provider_message_id=provider_msg_id,
                    send_status=send_status,
                    sent_at=now if send_status == RFQInvitationStatus.sent else None,
                    idempotency_key=f"refresh-{rfq.rfq_number}-{current_phone}",
                )
            )

        return rfq

    # ------------------------------------------------------------------
    # Per-counterparty actions
    # ------------------------------------------------------------------

    @staticmethod
    def reject_quote(session: Session, rfq_id: UUID, quote_id: UUID) -> None:
        """Remove a specific counterparty quote without closing the RFQ.

        Sends a standardised rejection message to the counterparty via
        WhatsApp before deleting the quote.

        The caller must ``session.commit()`` afterwards.
        """
        rfq = RFQService.get_live(session, rfq_id)
        if rfq.state not in (RFQState.quoted, RFQState.sent):
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="RFQ must be in SENT or QUOTED state",
            )
        quote = session.get(RFQQuote, quote_id)
        if not quote or str(quote.rfq_id) != str(rfq_id):
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Quote not found for this RFQ",
            )

        # Send rejection message to the counterparty
        cp = None
        if quote.counterparty_id:
            cp = session.get(
                Counterparty,
                UUID(quote.counterparty_id)
                if isinstance(quote.counterparty_id, str)
                else quote.counterparty_id,
            )
        if cp and cp.whatsapp_phone:
            msg = _pick_action_message(cp, "reject")
            result = WhatsAppService.send_text_message(
                phone=cp.whatsapp_phone, text=msg
            )
            if result.success:
                _logger.info(
                    "rfq_reject_whatsapp_sent",
                    rfq_number=rfq.rfq_number,
                    recipient=cp.whatsapp_phone,
                )
            else:
                _logger.error(
                    "rfq_reject_whatsapp_failed",
                    rfq_number=rfq.rfq_number,
                    recipient=cp.whatsapp_phone,
                    error_code=result.error_code,
                    error_message=result.error_message,
                )

        session.delete(quote)

        # Check if there are remaining quotes — if none, revert to SENT
        remaining = (
            session.query(RFQQuote)
            .filter(RFQQuote.rfq_id == rfq_id, RFQQuote.id != quote_id)
            .count()
        )
        if remaining == 0 and rfq.state == RFQState.quoted:
            rfq.state = RFQState.sent
            session.add(
                RFQStateEvent(
                    rfq_id=rfq.id,
                    from_state=RFQState.quoted,
                    to_state=RFQState.sent,
                    reason="ALL_QUOTES_REJECTED",
                    event_timestamp=now_utc(),
                )
            )

    @staticmethod
    def refresh_counterparty(
        session: Session, rfq_id: UUID, counterparty_id: str, user_id: str
    ) -> RFQ:
        """Re-send invitation to a specific counterparty.

        The caller must ``session.commit()`` afterwards.
        """
        rfq = RFQService.get_live(session, rfq_id)
        if rfq.state not in (RFQState.sent, RFQState.quoted):
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="RFQ must be in SENT or QUOTED state",
            )

        cp_uuid = (
            UUID(counterparty_id)
            if isinstance(counterparty_id, str)
            else counterparty_id
        )
        existing = (
            session.query(RFQInvitation)
            .filter(
                RFQInvitation.rfq_id == rfq.id,
                RFQInvitation.counterparty_id == cp_uuid,
            )
            .order_by(RFQInvitation.created_at.asc())
            .first()
        )
        if not existing:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="No invitation found for this counterparty",
            )

        message_body = (
            f"RFQ#{rfq.rfq_number} — REFRESH: please resend your FIXED price quote."
        )
        now = now_utc()

        # Fetch the current phone from the Counterparty table in case
        # it has been updated since the original invitation was created.
        current_phone = existing.recipient_phone
        cp = None
        if existing.counterparty_id:
            cp = session.get(Counterparty, existing.counterparty_id)
            if cp and cp.whatsapp_phone:
                current_phone = cp.whatsapp_phone

        # Use the standardised refresh message for the counterparty language
        message_body = _pick_action_message(cp, "refresh")

        # Actually send the WhatsApp message
        send_status = RFQInvitationStatus.queued
        provider_message_id = (
            f"refresh-{rfq.rfq_number}-{current_phone}-{now.isoformat()}"
        )

        if existing.channel == RFQInvitationChannel.whatsapp:
            result = WhatsAppService.send_text_message(
                phone=current_phone,
                text=message_body,
            )
            if result.success:
                send_status = RFQInvitationStatus.sent
                provider_message_id = result.provider_message_id or provider_message_id
                _logger.info(
                    "rfq_refresh_whatsapp_sent",
                    rfq_number=rfq.rfq_number,
                    recipient=current_phone,
                )
            else:
                send_status = RFQInvitationStatus.failed
                _logger.error(
                    "rfq_refresh_whatsapp_failed",
                    rfq_number=rfq.rfq_number,
                    recipient=current_phone,
                    error_code=result.error_code,
                    error_message=result.error_message,
                )

        session.add(
            RFQInvitation(
                rfq_id=rfq.id,
                rfq_number=rfq.rfq_number,
                counterparty_id=existing.counterparty_id,
                recipient_phone=current_phone,
                recipient_name=existing.recipient_name,
                channel=existing.channel,
                message_body=message_body,
                provider_message_id=provider_message_id,
                send_status=send_status,
                sent_at=now if send_status == RFQInvitationStatus.sent else None,
                idempotency_key=f"refresh-{rfq.rfq_number}-{current_phone}-{now.isoformat()}",
            )
        )
        return rfq

    @staticmethod
    def award_quote(
        session: Session, rfq_id: UUID, quote_id: UUID, user_id: str
    ) -> RFQ:
        """Award a specific quote: create contract from it and close the RFQ.

        Unlike ``award()`` which auto-selects the top-ranked quote, this method
        creates a contract from the specific quote chosen by the trader.

        Sends a standardised "contract" confirmation message to the winning
        counterparty via WhatsApp.

        The caller must ``session.commit()`` afterwards.
        """
        rfq = RFQService.get_live(session, rfq_id)
        if rfq.state != RFQState.quoted:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="RFQ must be in QUOTED state",
            )

        quote = session.get(RFQQuote, quote_id)
        if not quote or str(quote.rfq_id) != str(rfq_id):
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Quote not found for this RFQ",
            )

        award_time = now_utc()

        fixed_side, variable_side, classification = RFQService.determine_contract_legs(
            rfq.direction
        )
        contract = HedgeContract(
            commodity=rfq.commodity,
            quantity_mt=rfq.quantity_mt,
            rfq_id=rfq.id,
            rfq_quote_id=quote.id,
            counterparty_id=str(quote.counterparty_id),
            fixed_price_value=quote.fixed_price_value,
            fixed_price_unit=quote.fixed_price_unit,
            float_pricing_convention=RFQService._convention_value(
                quote.float_pricing_convention
            ),
            fixed_leg_side=fixed_side,
            variable_leg_side=variable_side,
            classification=classification,
            reference=f"HC-{_uuid.uuid4().hex.upper()}",
            trade_date=award_time.date(),
            source_type="rfq_award",
            source_id=rfq.id,
        )
        session.add(contract)
        session.flush()

        # Send contract confirmation message to the winning counterparty
        cp = None
        if quote.counterparty_id:
            cp = session.get(
                Counterparty,
                UUID(quote.counterparty_id)
                if isinstance(quote.counterparty_id, str)
                else quote.counterparty_id,
            )
        if cp and cp.whatsapp_phone:
            msg = _pick_action_message(cp, "contract")
            result = WhatsAppService.send_text_message(
                phone=cp.whatsapp_phone, text=msg
            )
            if result.success:
                _logger.info(
                    "rfq_contract_whatsapp_sent",
                    rfq_number=rfq.rfq_number,
                    recipient=cp.whatsapp_phone,
                )
            else:
                _logger.error(
                    "rfq_contract_whatsapp_failed",
                    rfq_number=rfq.rfq_number,
                    recipient=cp.whatsapp_phone,
                    error_code=result.error_code,
                    error_message=result.error_message,
                )

        if rfq.intent == RFQIntent.commercial_hedge and rfq.order_id is not None:
            LinkageService.create(session, rfq.order_id, contract.id, rfq.quantity_mt)

        # State transitions: QUOTED → AWARDED → CLOSED
        rfq.state = RFQState.awarded
        session.add(
            RFQStateEvent(
                rfq_id=rfq.id,
                from_state=RFQState.quoted,
                to_state=RFQState.awarded,
                user_id=user_id,
                winning_quote_ids=json.dumps([str(quote.id)], sort_keys=True),
                winning_counterparty_ids=json.dumps(
                    [str(quote.counterparty_id)], sort_keys=True
                ),
                award_timestamp=award_time,
                event_timestamp=award_time,
            )
        )

        rfq.state = RFQState.closed
        session.add(
            RFQStateEvent(
                rfq_id=rfq.id,
                from_state=RFQState.awarded,
                to_state=RFQState.closed,
                created_contract_ids=json.dumps([str(contract.id)], sort_keys=True),
                event_timestamp=now_utc(),
            )
        )

        return rfq

    @staticmethod
    def award(session: Session, rfq_id: UUID, user_id: str) -> RFQ:
        """Award an RFQ: create contracts, linkages and close.

        The caller must ``session.commit()`` afterwards.
        """
        rfq = RFQService.get_live(session, rfq_id)
        if rfq.state != RFQState.quoted:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="RFQ must be in QUOTED state",
            )

        award_time = now_utc()
        created_contract_ids: list[str] = []
        winning_quote_ids: list[str] = []
        winning_counterparty_ids: list[str] = []
        ranking_snapshot: dict

        if rfq.intent == RFQIntent.spread:
            ranking_payload = RFQService.compute_spread_ranking(session, rfq)
            if ranking_payload.status != "SUCCESS" or not ranking_payload.ranking:
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail="Ranking is not awardable",
                )

            top = ranking_payload.ranking[0]
            winning_counterparty_ids = [str(top.counterparty_id)]
            winning_quote_ids = [str(top.buy_quote.id), str(top.sell_quote.id)]
            ranking_snapshot = ranking_payload.model_dump(mode="json")

            for trade_rfq_id, quote in (
                (rfq.buy_trade_id, top.buy_quote),
                (rfq.sell_trade_id, top.sell_quote),
            ):
                if trade_rfq_id is None:
                    raise HTTPException(
                        status_code=status.HTTP_409_CONFLICT,
                        detail="Referenced trade RFQ ID is None",
                    )
                trade_rfq = session.get(RFQ, trade_rfq_id)
                if not trade_rfq:
                    raise HTTPException(
                        status_code=status.HTTP_409_CONFLICT,
                        detail="Referenced trade RFQ missing",
                    )

                fixed_side, variable_side, classification = (
                    RFQService.determine_contract_legs(trade_rfq.direction)
                )
                contract = HedgeContract(
                    commodity=trade_rfq.commodity,
                    quantity_mt=trade_rfq.quantity_mt,
                    rfq_id=trade_rfq.id,
                    rfq_quote_id=quote.id,
                    counterparty_id=str(top.counterparty_id),
                    fixed_price_value=quote.fixed_price_value,
                    fixed_price_unit=quote.fixed_price_unit,
                    float_pricing_convention=RFQService._convention_value(
                        quote.float_pricing_convention
                    ),
                    fixed_leg_side=fixed_side,
                    variable_leg_side=variable_side,
                    classification=classification,
                    reference=f"HC-{_uuid.uuid4().hex.upper()}",
                    trade_date=award_time.date(),
                    source_type="rfq_award",
                    source_id=trade_rfq.id,
                )
                session.add(contract)
                session.flush()
                created_contract_ids.append(str(contract.id))

                if (
                    trade_rfq.intent == RFQIntent.commercial_hedge
                    and trade_rfq.order_id is not None
                ):
                    LinkageService.create(
                        session,
                        trade_rfq.order_id,
                        contract.id,
                        trade_rfq.quantity_mt,
                    )

        else:
            latest = RFQService.get_latest_trade_quotes(session, rfq.id)
            trade_ranking = RFQService.compute_trade_ranking(rfq, latest)
            if trade_ranking.status != "SUCCESS" or not trade_ranking.ranking:
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail="Ranking is not awardable",
                )

            top_quote = trade_ranking.ranking[0].quote
            winning_counterparty_ids = [str(top_quote.counterparty_id)]
            winning_quote_ids = [str(top_quote.id)]
            ranking_snapshot = trade_ranking.model_dump(mode="json")

            fixed_side, variable_side, classification = (
                RFQService.determine_contract_legs(rfq.direction)
            )
            contract = HedgeContract(
                commodity=rfq.commodity,
                quantity_mt=rfq.quantity_mt,
                rfq_id=rfq.id,
                rfq_quote_id=top_quote.id,
                counterparty_id=str(top_quote.counterparty_id),
                fixed_price_value=top_quote.fixed_price_value,
                fixed_price_unit=top_quote.fixed_price_unit,
                float_pricing_convention=RFQService._convention_value(
                    top_quote.float_pricing_convention
                ),
                fixed_leg_side=fixed_side,
                variable_leg_side=variable_side,
                classification=classification,
                reference=f"HC-{_uuid.uuid4().hex.upper()}",
                trade_date=award_time.date(),
                source_type="rfq_award",
                source_id=rfq.id,
            )
            session.add(contract)
            session.flush()
            created_contract_ids.append(str(contract.id))

            if rfq.intent == RFQIntent.commercial_hedge and rfq.order_id is not None:
                LinkageService.create(
                    session, rfq.order_id, contract.id, rfq.quantity_mt
                )

        # State transitions: QUOTED → AWARDED → CLOSED
        rfq.state = RFQState.awarded
        session.add(
            RFQStateEvent(
                rfq_id=rfq.id,
                from_state=RFQState.quoted,
                to_state=RFQState.awarded,
                user_id=user_id,
                winning_quote_ids=json.dumps(winning_quote_ids, sort_keys=True),
                winning_counterparty_ids=json.dumps(
                    winning_counterparty_ids, sort_keys=True
                ),
                ranking_snapshot=json.dumps(ranking_snapshot, sort_keys=True),
                award_timestamp=award_time,
                event_timestamp=award_time,
            )
        )

        rfq.state = RFQState.closed
        session.add(
            RFQStateEvent(
                rfq_id=rfq.id,
                from_state=RFQState.awarded,
                to_state=RFQState.closed,
                created_contract_ids=json.dumps(created_contract_ids, sort_keys=True),
                event_timestamp=now_utc(),
            )
        )

        return rfq
