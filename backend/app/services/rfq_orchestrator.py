"""RFQ Orchestrator — coordinates the full RFQ lifecycle.

State transitions:
    CREATED → SENT     (auto, after WhatsApp messages dispatched)
    SENT    → QUOTED   (auto, after first quote parsed)
    QUOTED  → AWARDED  (manual, trader confirms)
    QUOTED  → CLOSED   (manual, trader rejects)
    AWARDED → CLOSED   (auto, after contract generated)

The orchestrator is the single coordination point that ties together:
- WhatsApp outbound (5.1)
- Webhook inbound / message queue (5.2)
- LLM Agent parsing (5.3)
- RFQ Service business logic (existing)

It does NOT replace the RFQ Service — it delegates to it.
"""

from __future__ import annotations

import re
from uuid import UUID

from sqlalchemy.orm import Session
from sqlalchemy import func, distinct, or_

from app.core.logging import get_logger
from app.core.utils import now_utc
from app.models.rfqs import (
    RFQ,
    RFQInvitation,
    RFQInvitationChannel,
    RFQInvitationStatus,
    RFQState,
)
from app.models.quotes import RFQQuote
from app.schemas.llm import MessageIntent, ParsedQuote
from app.schemas.rfq import RFQQuoteCreate, FloatPricingConvention
from app.schemas.whatsapp import WhatsAppInboundMessage
from app.services.llm_agent import LLMAgent, LLMUnavailableError
from app.services.rfq_service import RFQService
from app.services.whatsapp_service import WhatsAppService
from app.services.webhook_processor import dequeue_message

logger = get_logger()

# ---------------------------------------------------------------------------
# Trivial-message pre-filter
# ---------------------------------------------------------------------------

_TRIVIAL_PATTERNS: set[str] = {
    # Portuguese greetings / acknowledgments
    "oi",
    "ola",
    "olá",
    "bom dia",
    "boa tarde",
    "boa noite",
    "ok",
    "tudo bem",
    "beleza",
    "sim",
    "nao",
    "não",
    "obrigado",
    "obrigada",
    "valeu",
    "vlw",
    "blz",
    "pode ser",
    "entendi",
    "certo",
    "show",
    "top",
    "legal",
    "perfeito",
    "combinado",
    "fechado",
    # English greetings / acknowledgments
    "hi",
    "hello",
    "hey",
    "good morning",
    "good afternoon",
    "yes",
    "no",
    "thanks",
    "thank you",
    "sure",
    "okay",
    "got it",
    "understood",
    "noted",
    "fine",
    "cool",
    "great",
    "perfect",
    "deal",
    "sounds good",
}

# Minimum length (chars) for a message to be considered a potential quote
_MIN_QUOTE_LENGTH = 3


class RFQOrchestrator:
    """Coordinates the automated RFQ flow end-to-end."""

    # ------------------------------------------------------------------
    # Helpers — anti-hallucination guards
    # ------------------------------------------------------------------

    @staticmethod
    def _phone_variants(phone: str) -> list[str]:
        """Return a list of phone number variants to match against.

        Brazilian mobiles can be stored as 9-digit (+55XX9XXXXXXXX)
        but the Twilio sandbox sends replies from 8-digit (+55XXXXXXXXXX).
        This generates both variants so the DB lookup succeeds.
        """
        variants = [phone]
        raw = phone.lstrip("+")
        if raw.startswith("55") and len(raw) >= 12:
            area_code = raw[2:4]
            digits = raw[4:]
            if len(digits) == 9 and digits[0] == "9":
                # 9-digit → also try 8-digit
                variants.append(f"+55{area_code}{digits[1:]}")
            elif len(digits) == 8:
                # 8-digit → also try 9-digit
                variants.append(f"+55{area_code}9{digits}")
        return variants

    @staticmethod
    def _is_trivial_message(text: str) -> bool:
        """Return True if *text* is a common greeting / acknowledgment
        that should NOT be sent to the LLM for quote extraction.

        Checks:
        1. Very short messages (< _MIN_QUOTE_LENGTH chars after strip).
        2. Exact match against a curated set of trivial phrases.
        """
        cleaned = text.strip()
        if len(cleaned) < _MIN_QUOTE_LENGTH:
            return True
        normalised = cleaned.lower().rstrip(".!?")
        if normalised in _TRIVIAL_PATTERNS:
            return True
        return False

    @staticmethod
    def _price_appears_in_text(price_value: float, raw_text: str) -> bool:
        """Return True if *price_value* (or its integer part) actually
        appears somewhere in *raw_text*.

        This prevents the LLM from hallucinating prices that the
        counterparty never typed.
        """
        if price_value is None:
            return False
        # Check both the full value and the integer part
        candidates = {
            str(price_value),
            str(int(price_value)),
        }
        # Also handle comma-decimal (e.g. "2729,50" for BR locale)
        if price_value != int(price_value):
            candidates.add(f"{int(price_value)},{str(price_value).split('.')[1]}")

        for c in candidates:
            if c in raw_text:
                return True
        return False

    # ------------------------------------------------------------------
    # 1. Dispatch outbound WhatsApp for all whatsapp invitations
    # ------------------------------------------------------------------

    @staticmethod
    def dispatch_whatsapp_invitations(session: Session, rfq_id: UUID) -> dict[str, str]:
        """Send WhatsApp messages for all pending whatsapp invitations.

        Returns a dict mapping ``recipient_phone → send_status``.
        """
        invitations = (
            session.query(RFQInvitation)
            .filter(
                RFQInvitation.rfq_id == rfq_id,
                RFQInvitation.channel == RFQInvitationChannel.whatsapp,
                RFQInvitation.send_status == RFQInvitationStatus.queued,
            )
            .all()
        )

        results: dict[str, str] = {}
        for inv in invitations:
            result = WhatsAppService.send_text_message(
                phone=inv.recipient_phone,
                text=inv.message_body,
            )
            if result.success:
                inv.send_status = RFQInvitationStatus.sent
                inv.provider_message_id = (
                    result.provider_message_id or inv.provider_message_id
                )
                results[inv.recipient_phone] = "sent"
            else:
                inv.send_status = RFQInvitationStatus.failed
                results[inv.recipient_phone] = "failed"

            logger.info(
                "orchestrator_whatsapp_dispatch",
                rfq_id=str(rfq_id),
                recipient=inv.recipient_phone,
                status=results[inv.recipient_phone],
            )

        session.flush()
        return results

    # ------------------------------------------------------------------
    # 2. Process inbound messages from the webhook queue
    # ------------------------------------------------------------------

    @staticmethod
    def process_inbound_queue(session: Session) -> list[dict]:
        """Drain the inbound message queue and process each message.

        For each message:
        1. Find the matching RFQ by looking up invitations by sender phone.
        2. Parse the message via LLM Agent.
        3. If confidence >= 0.85 and intent is QUOTE, auto-create a quote.
        4. Otherwise, flag for human review.

        Returns a list of processing results for observability.
        """
        results: list[dict] = []

        while True:
            msg = dequeue_message()
            if msg is None:
                break

            result = RFQOrchestrator._process_single_message(session, msg)
            results.append(result)

        return results

    @staticmethod
    def _process_single_message(
        session: Session,
        msg: WhatsAppInboundMessage,
    ) -> dict:
        """Process one inbound WhatsApp message."""
        # Find the RFQ by matching sender phone to invitation recipient_phone.
        # Brazilian mobiles can appear in 8-digit or 9-digit format, so we
        # check both variants.
        # Join with RFQ to only match invitations whose RFQ is in a quotable
        # state (SENT or QUOTED), preventing replies from being attributed
        # to stale/old RFQs.
        # ORDER BY RFQ.created_at DESC (not invitation.created_at) so the
        # NEWEST RFQ wins — refresh actions create many invitation rows and
        # would otherwise cause the wrong RFQ to be selected.
        phone_variants = RFQOrchestrator._phone_variants(msg.from_phone)
        invitation = (
            session.query(RFQInvitation)
            .join(RFQ, RFQInvitation.rfq_id == RFQ.id)
            .filter(
                RFQInvitation.recipient_phone.in_(phone_variants),
                RFQInvitation.channel == RFQInvitationChannel.whatsapp,
                RFQ.state.in_([RFQState.sent, RFQState.quoted]),
                RFQ.deleted_at.is_(None),
            )
            .order_by(RFQ.created_at.desc(), RFQInvitation.created_at.desc())
            .first()
        )

        if not invitation:
            logger.warning(
                "orchestrator_no_matching_rfq",
                from_phone=msg.from_phone,
                message_id=msg.message_id,
            )
            return {
                "message_id": msg.message_id,
                "status": "no_matching_rfq",
                "from_phone": msg.from_phone,
            }

        # ── Guard: warn when multiple active RFQs match the same phone ──
        active_rfq_count = (
            session.query(func.count(distinct(RFQ.id)))
            .join(RFQInvitation, RFQInvitation.rfq_id == RFQ.id)
            .filter(
                RFQInvitation.recipient_phone.in_(phone_variants),
                RFQInvitation.channel == RFQInvitationChannel.whatsapp,
                RFQ.state.in_([RFQState.sent, RFQState.quoted]),
                RFQ.deleted_at.is_(None),
            )
            .scalar()
        )
        if active_rfq_count > 1:
            logger.warning(
                "orchestrator_multi_rfq_same_phone",
                from_phone=msg.from_phone,
                active_rfq_count=active_rfq_count,
                selected_rfq_id=str(invitation.rfq_id),
                selected_rfq_number=invitation.rfq_number,
            )

        rfq = session.get(RFQ, invitation.rfq_id)
        if not rfq or rfq.state not in (RFQState.sent, RFQState.quoted):
            logger.info(
                "orchestrator_rfq_not_quotable",
                rfq_id=str(invitation.rfq_id) if rfq else None,
                state=rfq.state.value if rfq else None,
            )
            return {
                "message_id": msg.message_id,
                "status": "rfq_not_quotable",
                "rfq_id": str(invitation.rfq_id),
            }

        # ── Guard 1: trivial message pre-filter ──
        if RFQOrchestrator._is_trivial_message(msg.text):
            logger.info(
                "orchestrator_trivial_message_skipped",
                rfq_id=str(rfq.id),
                text=msg.text[:100],
            )
            return {
                "message_id": msg.message_id,
                "status": "trivial_message_skipped",
                "rfq_id": str(rfq.id),
                "text": msg.text,
            }

        # ── Guard 2: classify intent FIRST ──
        try:
            classification = LLMAgent.classify_intent(msg.text)
        except LLMUnavailableError:
            classification = None  # proceed with parse_quote as fallback

        if classification and classification.intent != MessageIntent.quote:
            logger.info(
                "orchestrator_classified_non_quote",
                rfq_id=str(rfq.id),
                intent=classification.intent.value,
                confidence=classification.confidence,
                text=msg.text[:100],
            )
            # Handle rejection and question from classification
            if classification.intent == MessageIntent.rejection:
                invitation.send_status = RFQInvitationStatus.failed
                session.flush()
                return {
                    "message_id": msg.message_id,
                    "status": "counterparty_declined",
                    "rfq_id": str(rfq.id),
                    "counterparty": str(invitation.counterparty_id),
                }
            if classification.intent == MessageIntent.question:
                return {
                    "message_id": msg.message_id,
                    "status": "counterparty_question",
                    "rfq_id": str(rfq.id),
                    "counterparty": str(invitation.counterparty_id),
                    "text": msg.text,
                }
            return {
                "message_id": msg.message_id,
                "status": "needs_human_review",
                "rfq_id": str(rfq.id),
                "intent": classification.intent.value,
                "confidence": classification.confidence,
            }

        # Build RFQ context for the LLM
        rfq_context = (
            f"RFQ: {rfq.rfq_number}\n"
            f"Commodity: {rfq.commodity}\n"
            f"Quantity: {rfq.quantity_mt} MT\n"
            f"Direction: {rfq.direction.value}\n"
            f"Delivery: {rfq.delivery_window_start} to {rfq.delivery_window_end}"
        )

        try:
            parsed = LLMAgent.parse_quote_message(
                rfq_context=rfq_context,
                raw_message=msg.text,
                sender_name=msg.sender_name or invitation.recipient_name,
            )
        except LLMUnavailableError as exc:
            logger.error(
                "orchestrator_llm_unavailable",
                rfq_id=str(rfq.id),
                error=str(exc),
            )
            return {
                "message_id": msg.message_id,
                "status": "llm_unavailable",
                "rfq_id": str(rfq.id),
            }

        logger.info(
            "orchestrator_llm_parsed",
            rfq_id=str(rfq.id),
            intent=parsed.intent.value,
            confidence=parsed.confidence,
        )

        # ── Guard 3: price-in-text validation ──
        if LLMAgent.should_auto_create_quote(parsed):
            price_val = float(
                parsed.fixed_price_value
                if parsed.fixed_price_value is not None
                else (parsed.premium_discount or 0)
            )
            if not RFQOrchestrator._price_appears_in_text(price_val, msg.text):
                logger.warning(
                    "orchestrator_hallucinated_price_blocked",
                    rfq_id=str(rfq.id),
                    hallucinated_price=price_val,
                    raw_text=msg.text[:200],
                )
                return {
                    "message_id": msg.message_id,
                    "status": "hallucinated_price_blocked",
                    "rfq_id": str(rfq.id),
                    "hallucinated_price": price_val,
                    "text": msg.text,
                }

            # ── Guard 4: duplicate quote dedup ──
            existing_quote = (
                session.query(RFQQuote)
                .filter(
                    RFQQuote.rfq_id == rfq.id,
                    RFQQuote.counterparty_id == str(invitation.counterparty_id),
                    RFQQuote.fixed_price_value == price_val,
                )
                .first()
            )
            if existing_quote:
                logger.info(
                    "orchestrator_duplicate_quote_skipped",
                    rfq_id=str(rfq.id),
                    counterparty=str(invitation.counterparty_id),
                    price=price_val,
                    existing_quote_id=str(existing_quote.id),
                )
                return {
                    "message_id": msg.message_id,
                    "status": "duplicate_quote_skipped",
                    "rfq_id": str(rfq.id),
                    "existing_quote_id": str(existing_quote.id),
                }

            return RFQOrchestrator._auto_create_quote(
                session, rfq, invitation, msg, parsed
            )

        if parsed.intent == MessageIntent.rejection:
            invitation.send_status = RFQInvitationStatus.failed
            session.flush()
            logger.info(
                "orchestrator_counterparty_declined",
                rfq_id=str(rfq.id),
                counterparty=str(invitation.counterparty_id),
            )
            return {
                "message_id": msg.message_id,
                "status": "counterparty_declined",
                "rfq_id": str(rfq.id),
                "counterparty": str(invitation.counterparty_id),
            }

        if parsed.intent == MessageIntent.question:
            logger.info(
                "orchestrator_counterparty_question",
                rfq_id=str(rfq.id),
                counterparty=str(invitation.counterparty_id),
                text=msg.text[:200],
            )
            return {
                "message_id": msg.message_id,
                "status": "counterparty_question",
                "rfq_id": str(rfq.id),
                "counterparty": str(invitation.counterparty_id),
                "text": msg.text,
            }

        return {
            "message_id": msg.message_id,
            "status": "needs_human_review",
            "rfq_id": str(rfq.id),
            "intent": parsed.intent.value,
            "confidence": parsed.confidence,
            "parsed": parsed.model_dump(mode="json"),
        }

    @staticmethod
    def _auto_create_quote(
        session: Session,
        rfq: RFQ,
        invitation: RFQInvitation,
        msg: WhatsAppInboundMessage,
        parsed: ParsedQuote,
    ) -> dict:
        """Create a quote automatically from a high-confidence LLM parse."""
        convention = parsed.float_pricing_convention or "avg"
        try:
            float_conv = FloatPricingConvention(convention)
        except ValueError:
            float_conv = FloatPricingConvention.avg

        price_value = parsed.fixed_price_value
        if price_value is None and parsed.premium_discount is not None:
            price_value = parsed.premium_discount

        quote_payload = RFQQuoteCreate(
            rfq_id=rfq.id,
            counterparty_id=str(invitation.counterparty_id),
            fixed_price_value=float(price_value or 0),
            fixed_price_unit=parsed.fixed_price_unit or "USD/MT",
            float_pricing_convention=float_conv,
            received_at=msg.timestamp,
        )

        try:
            quote = RFQService.submit_quote(session, rfq.id, quote_payload)
            session.commit()
            logger.info(
                "orchestrator_auto_quote_created",
                rfq_id=str(rfq.id),
                quote_id=str(quote.id),
                counterparty=str(invitation.counterparty_id),
                price=float(parsed.fixed_price_value or 0),
            )
            return {
                "message_id": msg.message_id,
                "status": "auto_quote_created",
                "rfq_id": str(rfq.id),
                "quote_id": str(quote.id),
                "confidence": parsed.confidence,
            }
        except Exception as exc:
            logger.error(
                "orchestrator_auto_quote_failed",
                rfq_id=str(rfq.id),
                error=str(exc),
            )
            return {
                "message_id": msg.message_id,
                "status": "auto_quote_failed",
                "rfq_id": str(rfq.id),
                "error": str(exc),
            }

    # ------------------------------------------------------------------
    # 3. Notify counterparties of award/reject via WhatsApp
    # ------------------------------------------------------------------

    @staticmethod
    def notify_award(
        session: Session,
        rfq: RFQ,
        winning_counterparty_id: str,
        price: float,
        unit: str = "USD/MT",
        language: str = "pt_BR",
    ) -> None:
        """Send WhatsApp award notification to the winning counterparty."""
        from uuid import UUID as _UUID

        try:
            cp_uuid = _UUID(winning_counterparty_id)
        except (ValueError, AttributeError):
            logger.warning(
                "orchestrator_invalid_counterparty_id",
                winning_counterparty_id=winning_counterparty_id,
            )
            return

        invitation = (
            session.query(RFQInvitation)
            .filter(
                RFQInvitation.rfq_id == rfq.id,
                RFQInvitation.counterparty_id == cp_uuid,
                RFQInvitation.channel == RFQInvitationChannel.whatsapp,
            )
            .first()
        )
        if not invitation:
            logger.info("orchestrator_no_whatsapp_for_award", rfq_id=str(rfq.id))
            return

        message = LLMAgent.generate_outbound_message(
            action="award",
            language=language,
            recipient_name=invitation.recipient_name,
            rfq_number=rfq.rfq_number,
            price=price,
            unit=unit,
        )
        WhatsAppService.send_text_message(
            phone=invitation.recipient_phone,
            text=message,
        )

    @staticmethod
    def notify_reject(
        session: Session,
        rfq: RFQ,
        language: str = "pt_BR",
    ) -> None:
        """Send WhatsApp rejection notification to all counterparties."""
        invitations = (
            session.query(RFQInvitation)
            .filter(
                RFQInvitation.rfq_id == rfq.id,
                RFQInvitation.channel == RFQInvitationChannel.whatsapp,
            )
            .all()
        )

        # Deduplicate by recipient_phone (keep latest)
        seen: dict[str, RFQInvitation] = {}
        for inv in invitations:
            seen[inv.recipient_phone] = inv

        for inv in seen.values():
            message = LLMAgent.generate_outbound_message(
                action="reject",
                language=language,
                recipient_name=inv.recipient_name,
                rfq_number=rfq.rfq_number,
            )
            WhatsAppService.send_text_message(phone=inv.recipient_phone, text=message)

    # ------------------------------------------------------------------
    # 4. Check timeouts — called by the scheduled task
    # ------------------------------------------------------------------

    @staticmethod
    def check_rfq_timeouts(
        session: Session,
        timeout_hours: int = 24,
    ) -> list[dict]:
        """Find RFQs past their response deadline and flag them.

        Does NOT auto-transition state — the trader decides.
        Returns a list of dicts with rfq_id, rfq_number, quotes_count
        for observability and UI alerting.
        """
        from datetime import timedelta

        cutoff = now_utc() - timedelta(hours=timeout_hours)

        stale_rfqs = (
            session.query(RFQ)
            .filter(
                RFQ.state == RFQState.sent,
                RFQ.created_at <= cutoff,
                RFQ.deleted_at.is_(None),
            )
            .all()
        )

        flagged: list[dict] = []
        for rfq in stale_rfqs:
            latest_quotes = RFQService.get_latest_trade_quotes(session, rfq.id)
            flagged.append(
                {
                    "rfq_id": str(rfq.id),
                    "rfq_number": rfq.rfq_number,
                    "quotes_count": len(latest_quotes),
                    "has_quotes": bool(latest_quotes),
                    "hours_elapsed": timeout_hours,
                }
            )

        if flagged:
            logger.warning(
                "orchestrator_timeout_flagged",
                flagged_count=len(flagged),
                rfq_numbers=[f["rfq_number"] for f in flagged],
            )

        return flagged

    # ------------------------------------------------------------------
    # 5. Send reminders for RFQs with low response rate
    # ------------------------------------------------------------------

    @staticmethod
    def check_low_response_rfqs(
        session: Session,
        min_response_rate: float = 0.5,
    ) -> list[dict]:
        """Identify SENT RFQs where < 50% of counterparties have responded.

        Does NOT auto-send reminders — the trader decides via the
        Refresh action in the UI.  Returns observability data.
        """
        sent_rfqs = (
            session.query(RFQ)
            .filter(
                RFQ.state == RFQState.sent,
                RFQ.deleted_at.is_(None),
            )
            .all()
        )

        flagged: list[dict] = []
        for rfq in sent_rfqs:
            invitations = (
                session.query(RFQInvitation)
                .filter(RFQInvitation.rfq_id == rfq.id)
                .all()
            )
            if not invitations:
                continue

            unique_recipients = {inv.recipient_phone for inv in invitations}
            quotes = RFQService.get_latest_trade_quotes(session, rfq.id)
            responded = set(quotes.keys())
            response_rate = (
                len(responded) / len(unique_recipients) if unique_recipients else 0
            )

            if response_rate >= min_response_rate:
                continue

            flagged.append(
                {
                    "rfq_id": str(rfq.id),
                    "rfq_number": rfq.rfq_number,
                    "total_recipients": len(unique_recipients),
                    "responded": len(responded),
                    "response_rate": round(response_rate, 2),
                    "non_responders": len(unique_recipients - responded),
                }
            )

        if flagged:
            logger.info(
                "orchestrator_low_response_flagged",
                flagged_count=len(flagged),
                rfq_numbers=[f["rfq_number"] for f in flagged],
            )

        return flagged
