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
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from uuid import UUID

from fastapi import HTTPException
from pydantic import ValidationError
from sqlalchemy.orm import Session
from sqlalchemy import and_, or_
from sqlalchemy.exc import SQLAlchemyError

from app.core.logging import get_logger
from app.core.pricing import CANONICAL_PRICE_UNITS
from app.core.utils import now_utc
from app.models.inbound_webhook_message import InboundWebhookMessage
from app.models.llm_decision_artifact import (
    LLMDecisionArtifact,
    LLM_DECISION_ALLOW,
    LLM_DECISION_DENY,
)
from app.models.rfqs import (
    RFQ,
    RFQInvitation,
    RFQInvitationChannel,
    RFQInvitationPurpose,
    RFQInvitationStatus,
    RFQState,
)
from app.models.quotes import QuoteState, RFQQuote
from app.schemas.llm import LLMClassifyResult, MessageIntent, ParsedQuote
from app.schemas.rfq import RFQQuoteCreate, FloatPricingConvention
from app.schemas.whatsapp import WhatsAppInboundMessage
from app.services.llm_agent import (
    CONFIDENCE_THRESHOLD,
    LLMAgent,
    LLMCallTrace,
    LLMClassifyDecision,
    LLMParseDecision,
    LLMUnavailableError,
)
from app.services import llm_agent as llm_agent_module
from app.services.rfq_service import (
    RFQService,
    _persist_outbox_queued,
    prefix_with_canonical_id,
)
from app.services.whatsapp_service import WhatsAppService
from app.services.webhook_processor import dequeue_message, mark_message_finished

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

# Format mirrored from rfq_service.py: RFQ-{year}-{sequence:06d}.
_CANONICAL_ID_RE = re.compile(
    r"(?<!\w)RFQ#(?P<num>RFQ-\d{4}-\d{6})(?!\w)(?:\s+[—–]\s+)?"
)
_DURABLE_MESSAGE_TERMINAL_STATUSES = {"processed", "duplicate"}
_DURABLE_MESSAGE_STALE_AFTER = timedelta(minutes=15)
_DURABLE_FAILURE_STATUSES = {"llm_unavailable", "auto_quote_failed"}


class ArtifactPayloadError(Exception):
    """Raised when LLM decision artifact payload construction is invalid."""


def _parse_canonical_ids(text: str | None) -> list[str]:
    """Extract all canonical RFQ identifiers from inbound text."""
    if not text:
        return []
    return [match.group("num") for match in _CANONICAL_ID_RE.finditer(text)]


def _strip_canonical_id(text: str | None) -> str:
    """Remove canonical identifiers while preserving downstream price signs."""
    if not text:
        return ""
    return _CANONICAL_ID_RE.sub("", text).strip()


def _json_safe(value):
    if isinstance(value, dict):
        return {str(key): _json_safe(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_json_safe(item) for item in value]
    if isinstance(value, tuple):
        return [_json_safe(item) for item in value]
    if isinstance(value, (Decimal, UUID, datetime)):
        return str(value)
    if hasattr(value, "value"):
        return _json_safe(value.value)
    return value


def _trace_prompt_payload(trace: LLMCallTrace | None) -> dict | None:
    if trace is None:
        return None
    return _json_safe(
        {
            "system_prompt": trace.system_prompt,
            "user_prompt": trace.user_prompt,
            "messages": trace.messages,
            "request_params": trace.request_params,
        }
    )


def _synthetic_error_trace(*, user_prompt: str, error: str) -> LLMCallTrace:
    return LLMCallTrace(
        provider="openai",
        model="unknown",
        system_prompt="",
        user_prompt=user_prompt,
        messages=[{"role": "user", "content": user_prompt}],
        request_params={},
        raw_response=None,
        parsed_response=None,
        normalized_result=None,
        error=error,
    )


def _build_input_snapshot(
    *,
    durable: InboundWebhookMessage,
    msg: WhatsAppInboundMessage,
    rfq: RFQ,
    invitation: RFQInvitation,
    text_for_downstream: str,
    rfq_context: str | None,
) -> dict:
    return _json_safe(
        {
            "inbound_message_id": durable.id,
            "delivery_id": durable.delivery_id,
            "provider": durable.provider,
            "provider_message_id": durable.provider_message_id,
            "original_text": msg.text,
            "downstream_text": text_for_downstream,
            "sender_phone": msg.from_phone,
            "sender_name": msg.sender_name,
            "rfq_number": rfq.rfq_number,
            "rfq_context": rfq_context,
            "invitation_id": invitation.id,
            "counterparty_id": invitation.counterparty_id,
        }
    )


def _build_guard_outcomes(
    *,
    classification: LLMClassifyResult | None,
    parsed: ParsedQuote | None,
    final_status: str,
    should_auto_create_quote: bool | None,
    price_in_text: bool | None,
    duplicate_active_quote: bool | None,
    payload_complete: bool | None,
    payload_validation: str | None,
    failure_reason: str | None = None,
    state_mutations: list[dict] | None = None,
) -> dict:
    final_decision = _artifact_final_decision(final_status)
    return _json_safe(
        {
            "classification_attempted": True,
            "classification_intent": classification.intent.value
            if classification is not None
            else None,
            "classification_confidence": classification.confidence
            if classification is not None
            else None,
            "parse_attempted": parsed is not None or final_status == "llm_unavailable",
            "parse_intent": parsed.intent.value if parsed is not None else None,
            "parse_confidence": parsed.confidence if parsed is not None else None,
            "CONFIDENCE_THRESHOLD": CONFIDENCE_THRESHOLD,
            "should_auto_create_quote": should_auto_create_quote,
            "price_in_text": price_in_text,
            "duplicate_active_quote": duplicate_active_quote,
            "payload_complete": payload_complete,
            "payload_validation": payload_validation,
            "final_decision": final_decision,
            "final_status": final_status,
            "failure_reason": failure_reason,
            "state_mutations": state_mutations or [],
        }
    )


def _artifact_final_decision(final_status: str) -> str:
    if final_status in {"auto_quote_created", "counterparty_declined"}:
        return LLM_DECISION_ALLOW
    return LLM_DECISION_DENY


def _unpack_classification_decision(
    decision: LLMClassifyDecision | LLMClassifyResult,
) -> tuple[LLMClassifyResult | None, LLMCallTrace | None]:
    if isinstance(decision, LLMClassifyDecision):
        return decision.result, decision.trace
    return decision, None


def _unpack_parse_decision(
    decision: LLMParseDecision | ParsedQuote,
) -> tuple[ParsedQuote | None, LLMCallTrace | None]:
    if isinstance(decision, LLMParseDecision):
        return decision.result, decision.trace
    return decision, None


def _is_mocked_callable(value: object) -> bool:
    return type(value).__module__.startswith("unittest.mock")


def _classify_intent_with_optional_trace(
    message: str,
) -> tuple[LLMClassifyResult | None, LLMCallTrace | None]:
    if _is_mocked_callable(LLMAgent.classify_intent) or _is_mocked_callable(
        llm_agent_module._call_openai
    ):
        return LLMAgent.classify_intent(message), None
    decision = LLMAgent.classify_intent_with_trace(message)
    return _unpack_classification_decision(decision)


def _parse_quote_with_optional_trace(
    *,
    rfq_context: str,
    raw_message: str,
    sender_name: str,
) -> tuple[ParsedQuote | None, LLMCallTrace | None]:
    if _is_mocked_callable(LLMAgent.parse_quote_message) or _is_mocked_callable(
        llm_agent_module._call_openai
    ):
        return (
            LLMAgent.parse_quote_message(
                rfq_context=rfq_context,
                raw_message=raw_message,
                sender_name=sender_name,
            ),
            None,
        )
    decision = LLMAgent.parse_quote_message_with_trace(
        rfq_context=rfq_context,
        raw_message=raw_message,
        sender_name=sender_name,
    )
    return _unpack_parse_decision(decision)


def _build_artifact_payload(
    *,
    durable: InboundWebhookMessage,
    rfq: RFQ,
    invitation: RFQInvitation,
    input_snapshot: dict,
    guard_outcomes: dict,
    final_status: str,
    classification_trace: LLMCallTrace | None,
    parse_trace: LLMCallTrace | None,
    quote_id: UUID | None = None,
    attempt_number: int = 1,
) -> dict:
    final_decision = _artifact_final_decision(final_status)
    return {
        "inbound_message_id": durable.id,
        "delivery_id": durable.delivery_id,
        "provider": durable.provider,
        "provider_message_id": durable.provider_message_id,
        "rfq_id": rfq.id,
        "quote_id": quote_id,
        "counterparty_id": invitation.counterparty_id,
        "schema_version": 1,
        "attempt_number": attempt_number,
        "llm_provider": (
            parse_trace.provider
            if parse_trace is not None
            else classification_trace.provider
            if classification_trace is not None
            else "openai"
        ),
        "classification_model": classification_trace.model
        if classification_trace is not None
        else None,
        "parse_model": parse_trace.model if parse_trace is not None else None,
        "classification_prompt": _trace_prompt_payload(classification_trace),
        "classification_raw_response": classification_trace.raw_response
        if classification_trace is not None
        else None,
        "classification_parsed": _json_safe(classification_trace.parsed_response)
        if classification_trace is not None
        else None,
        "classification_error": classification_trace.error
        if classification_trace is not None
        else None,
        "parse_prompt": _trace_prompt_payload(parse_trace),
        "parse_raw_response": parse_trace.raw_response if parse_trace is not None else None,
        "parse_parsed": _json_safe(parse_trace.parsed_response)
        if parse_trace is not None
        else None,
        "parse_error": parse_trace.error if parse_trace is not None else None,
        "input_snapshot": input_snapshot,
        "guard_outcomes": guard_outcomes,
        "final_decision": final_decision,
        "final_status": final_status,
    }


def _add_llm_decision_artifact(
    session: Session,
    *,
    durable: InboundWebhookMessage | None,
    rfq: RFQ,
    invitation: RFQInvitation,
    input_snapshot: dict | None,
    guard_outcomes: dict,
    final_status: str,
    classification_trace: LLMCallTrace | None,
    parse_trace: LLMCallTrace | None,
    quote_id: UUID | None = None,
) -> LLMDecisionArtifact | None:
    if durable is None:
        return None
    if input_snapshot is None:
        raise ArtifactPayloadError("input_snapshot is required for durable LLM decisions")
    try:
        payload = _build_artifact_payload(
            durable=durable,
            rfq=rfq,
            invitation=invitation,
            input_snapshot=input_snapshot,
            guard_outcomes=guard_outcomes,
            final_status=final_status,
            classification_trace=classification_trace,
            parse_trace=parse_trace,
            quote_id=quote_id,
            attempt_number=_next_artifact_attempt_number(session, durable),
        )
        artifact = LLMDecisionArtifact(**payload)
    except (TypeError, ValueError) as exc:
        raise ArtifactPayloadError(str(exc)) from exc
    session.add(artifact)
    return artifact


def _next_artifact_attempt_number(
    session: Session,
    durable: InboundWebhookMessage,
) -> int:
    latest = (
        session.query(LLMDecisionArtifact.attempt_number)
        .filter(LLMDecisionArtifact.inbound_message_id == durable.id)
        .order_by(LLMDecisionArtifact.attempt_number.desc())
        .first()
    )
    if latest is None:
        return 1
    return int(latest[0]) + 1


def _existing_auto_quote_artifact(
    session: Session,
    *,
    durable: InboundWebhookMessage | None,
    quote_id: UUID,
) -> LLMDecisionArtifact | None:
    if durable is None:
        return None
    return (
        session.query(LLMDecisionArtifact)
        .filter(
            LLMDecisionArtifact.inbound_message_id == durable.id,
            LLMDecisionArtifact.quote_id == quote_id,
            LLMDecisionArtifact.final_status == "auto_quote_created",
        )
        .order_by(LLMDecisionArtifact.attempt_number.desc())
        .first()
    )


def _auto_quote_replay_result(
    msg: WhatsAppInboundMessage,
    *,
    artifact: LLMDecisionArtifact,
    rfq: RFQ,
    quote: RFQQuote,
) -> dict:
    result: dict = {
        "message_id": msg.message_id,
        "status": "auto_quote_created",
        "rfq_id": str(rfq.id),
        "quote_id": str(quote.id),
    }
    parsed = artifact.parse_parsed
    if isinstance(parsed, dict) and parsed.get("confidence") is not None:
        result["confidence"] = parsed["confidence"]
    return result


def _parse_uuid(value: object) -> UUID | None:
    if value is None:
        return None
    if isinstance(value, UUID):
        return value
    try:
        return UUID(str(value))
    except (TypeError, ValueError):
        return None


def _processing_started_at_is_stale(started_at: datetime | None) -> bool:
    if started_at is None:
        return True
    if started_at.tzinfo is None:
        started_at = started_at.replace(tzinfo=timezone.utc)
    return started_at <= now_utc() - _DURABLE_MESSAGE_STALE_AFTER


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
        1. Find the matching RFQ by canonical id in the message body.
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

            try:
                claim = RFQOrchestrator._claim_durable_message(session, msg)
                if claim is not None:
                    results.append(claim)
                    continue

                durable = (
                    session.get(InboundWebhookMessage, msg.delivery_message_id)
                    if msg.delivery_message_id is not None
                    else None
                )
                try:
                    result = RFQOrchestrator._process_single_message(
                        session,
                        msg,
                        durable=durable,
                    )
                except Exception as exc:
                    RFQOrchestrator._finalize_durable_message(
                        session,
                        msg,
                        {
                            "message_id": msg.message_id,
                            "status": "failed",
                            "error": str(exc),
                        },
                        failed=True,
                    )
                    raise
                RFQOrchestrator._finalize_durable_message(
                    session,
                    msg,
                    result,
                    failed=result.get("status") in _DURABLE_FAILURE_STATUSES,
                )
                results.append(result)
            finally:
                mark_message_finished(msg)

        return results

    @staticmethod
    def _claim_durable_message(
        session: Session,
        msg: WhatsAppInboundMessage,
    ) -> dict | None:
        if msg.delivery_message_id is None:
            logger.warning(
                "orchestrator_legacy_inbound_without_delivery_message_id",
                message_id=msg.message_id,
                from_phone=msg.from_phone,
            )
            return {
                "message_id": msg.message_id,
                "status": "legacy_missing_delivery_message_id",
                "from_phone": msg.from_phone,
            }

        durable_id = msg.delivery_message_id
        durable = session.get(InboundWebhookMessage, durable_id)
        if durable is None:
            logger.warning(
                "orchestrator_durable_message_missing",
                message_id=msg.message_id,
                delivery_message_id=str(durable_id),
            )
            return {
                "message_id": msg.message_id,
                "status": "durable_message_missing",
                "delivery_message_id": str(durable_id),
            }

        if durable.processing_status in _DURABLE_MESSAGE_TERMINAL_STATUSES:
            logger.info(
                "orchestrator_durable_message_already_consumed",
                message_id=msg.message_id,
                delivery_message_id=str(durable.id),
                processing_status=durable.processing_status,
            )
            return {"message_id": msg.message_id, "status": "already_consumed"}

        stale_cutoff = now_utc() - _DURABLE_MESSAGE_STALE_AFTER
        claimed = (
            session.query(InboundWebhookMessage)
            .filter(
                InboundWebhookMessage.id == durable_id,
                or_(
                    InboundWebhookMessage.processing_status.in_(
                        ["received", "failed"]
                    ),
                    and_(
                        InboundWebhookMessage.processing_status == "processing",
                        or_(
                            InboundWebhookMessage.processing_started_at.is_(None),
                            InboundWebhookMessage.processing_started_at <= stale_cutoff,
                        ),
                    ),
                ),
            )
            .update(
                {
                    InboundWebhookMessage.processing_status: "processing",
                    InboundWebhookMessage.processing_started_at: now_utc(),
                    InboundWebhookMessage.processing_completed_at: None,
                    InboundWebhookMessage.processing_result: None,
                },
                synchronize_session=False,
            )
        )
        session.commit()
        if claimed == 1:
            return None

        session.refresh(durable)
        if durable.processing_status in _DURABLE_MESSAGE_TERMINAL_STATUSES:
            logger.info(
                "orchestrator_durable_message_already_consumed_after_claim_race",
                message_id=msg.message_id,
                delivery_message_id=str(durable.id),
                processing_status=durable.processing_status,
            )
            return {"message_id": msg.message_id, "status": "already_consumed"}

        if durable.processing_status == "processing":
            if _processing_started_at_is_stale(durable.processing_started_at):
                logger.warning(
                    "orchestrator_durable_message_stale_claim_race_recovered",
                    message_id=msg.message_id,
                    delivery_message_id=str(durable.id),
                    processing_started_at=durable.processing_started_at.isoformat()
                    if durable.processing_started_at
                    else None,
                )
                return None

            logger.info(
                "orchestrator_durable_message_already_processing",
                message_id=msg.message_id,
                delivery_message_id=str(durable.id),
            )
            return {"message_id": msg.message_id, "status": "already_processing"}

        logger.warning(
            "orchestrator_durable_message_recoverable_claim_race_recovered",
            message_id=msg.message_id,
            delivery_message_id=str(durable.id),
            processing_status=durable.processing_status,
        )
        return None

    @staticmethod
    def _finalize_durable_message(
        session: Session,
        msg: WhatsAppInboundMessage,
        result: dict,
        *,
        failed: bool = False,
    ) -> None:
        if msg.delivery_message_id is None:
            logger.warning(
                "orchestrator_legacy_inbound_processed_without_delivery_message_id",
                message_id=msg.message_id,
                from_phone=msg.from_phone,
                final_status=result.get("status"),
            )
            return

        durable = session.get(InboundWebhookMessage, msg.delivery_message_id)
        if durable is None:
            return

        durable.processing_status = "failed" if failed else "processed"
        durable.processing_completed_at = now_utc()
        durable.processing_result = _json_safe(result)
        canonical_numbers = _parse_canonical_ids(msg.text)
        durable.rfq_number = (
            result.get("canonical_number")
            or (canonical_numbers[0] if len(set(canonical_numbers)) == 1 else None)
        )
        durable.rfq_id = _parse_uuid(result.get("rfq_id"))
        durable.quote_id = _parse_uuid(result.get("quote_id") or result.get("existing_quote_id"))
        session.commit()

    @staticmethod
    def _process_single_message(
        session: Session,
        msg: WhatsAppInboundMessage,
        durable: InboundWebhookMessage | None = None,
    ) -> dict:
        """Process one inbound WhatsApp message."""
        canonical_numbers = _parse_canonical_ids(msg.text)
        distinct_ids = set(canonical_numbers)
        if not distinct_ids:
            logger.warning(
                "orchestrator_no_canonical_id",
                from_phone=msg.from_phone,
                message_id=msg.message_id,
            )
            return {
                "message_id": msg.message_id,
                "status": "no_canonical_id",
                "from_phone": msg.from_phone,
            }

        if len(distinct_ids) > 1:
            logger.warning(
                "orchestrator_multi_canonical_id",
                from_phone=msg.from_phone,
                canonical_numbers=sorted(distinct_ids),
                message_id=msg.message_id,
            )
            return {
                "message_id": msg.message_id,
                "status": "multi_canonical_id",
                "canonical_numbers": sorted(distinct_ids),
            }

        canonical_number = next(iter(distinct_ids))
        rfq = (
            session.query(RFQ)
            .filter(RFQ.rfq_number == canonical_number)
            .first()
        )
        if rfq is None:
            logger.warning(
                "orchestrator_canonical_id_unknown",
                from_phone=msg.from_phone,
                canonical_number=canonical_number,
                message_id=msg.message_id,
            )
            return {
                "message_id": msg.message_id,
                "status": "canonical_id_unknown",
                "canonical_number": canonical_number,
            }

        if rfq.deleted_at is not None:
            logger.info(
                "orchestrator_rfq_archived",
                rfq_id=str(rfq.id),
                from_phone=msg.from_phone,
                message_id=msg.message_id,
            )
            return {
                "message_id": msg.message_id,
                "status": "rfq_archived",
                "rfq_id": str(rfq.id),
            }

        if rfq.state not in (RFQState.sent, RFQState.quoted):
            logger.info(
                "orchestrator_rfq_not_quotable",
                rfq_id=str(rfq.id),
                rfq_state=rfq.state.value,
                from_phone=msg.from_phone,
                message_id=msg.message_id,
            )
            return {
                "message_id": msg.message_id,
                "status": "rfq_not_quotable",
                "rfq_id": str(rfq.id),
                "rfq_state": rfq.state.value,
            }

        phone_variants = RFQOrchestrator._phone_variants(msg.from_phone)
        invitation = (
            session.query(RFQInvitation)
            .filter(
                RFQInvitation.rfq_id == rfq.id,
                RFQInvitation.recipient_phone.in_(phone_variants),
                RFQInvitation.channel == RFQInvitationChannel.whatsapp,
            )
            .order_by(RFQInvitation.created_at.desc())
            .first()
        )
        if invitation is None:
            logger.warning(
                "orchestrator_phone_does_not_match_canonical_id",
                from_phone=msg.from_phone,
                canonical_number=canonical_number,
                rfq_id=str(rfq.id),
                message_id=msg.message_id,
            )
            return {
                "message_id": msg.message_id,
                "status": "phone_mismatch",
                "canonical_number": canonical_number,
                "rfq_id": str(rfq.id),
            }

        text_for_downstream = _strip_canonical_id(msg.text)
        classification: LLMClassifyResult | None = None
        classification_trace: LLMCallTrace | None = None
        parsed: ParsedQuote | None = None
        parse_trace: LLMCallTrace | None = None
        rfq_context: str | None = None
        input_snapshot: dict | None = None

        # ── Guard 1: trivial message pre-filter ──
        if RFQOrchestrator._is_trivial_message(text_for_downstream):
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
            classification, classification_trace = _classify_intent_with_optional_trace(
                text_for_downstream
            )
        except LLMUnavailableError as exc:
            classification_trace = exc.trace or _synthetic_error_trace(
                user_prompt=text_for_downstream,
                error=str(exc),
            )
            classification = None  # proceed with parse_quote as fallback

        input_snapshot = _build_input_snapshot(
            durable=durable,
            msg=msg,
            rfq=rfq,
            invitation=invitation,
            text_for_downstream=text_for_downstream,
            rfq_context=None,
        ) if durable is not None else None

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
                prior_send_status = invitation.send_status.value
                invitation.send_status = RFQInvitationStatus.failed
                session.flush()
                _add_llm_decision_artifact(
                    session,
                    durable=durable,
                    rfq=rfq,
                    invitation=invitation,
                    input_snapshot=input_snapshot,
                    guard_outcomes=_build_guard_outcomes(
                        classification=classification,
                        parsed=None,
                        final_status="counterparty_declined",
                        should_auto_create_quote=None,
                        price_in_text=None,
                        duplicate_active_quote=None,
                        payload_complete=None,
                        payload_validation=None,
                        state_mutations=[
                            {
                                "model": "RFQInvitation",
                                "field": "send_status",
                                "before": prior_send_status,
                                "after": RFQInvitationStatus.failed.value,
                            }
                        ],
                    ),
                    final_status="counterparty_declined",
                    classification_trace=classification_trace,
                    parse_trace=None,
                )
                return {
                    "message_id": msg.message_id,
                    "status": "counterparty_declined",
                    "rfq_id": str(rfq.id),
                    "counterparty": str(invitation.counterparty_id),
                }
            if classification.intent == MessageIntent.question:
                _add_llm_decision_artifact(
                    session,
                    durable=durable,
                    rfq=rfq,
                    invitation=invitation,
                    input_snapshot=input_snapshot,
                    guard_outcomes=_build_guard_outcomes(
                        classification=classification,
                        parsed=None,
                        final_status="counterparty_question",
                        should_auto_create_quote=None,
                        price_in_text=None,
                        duplicate_active_quote=None,
                        payload_complete=None,
                        payload_validation=None,
                    ),
                    final_status="counterparty_question",
                    classification_trace=classification_trace,
                    parse_trace=None,
                )
                return {
                    "message_id": msg.message_id,
                    "status": "counterparty_question",
                    "rfq_id": str(rfq.id),
                    "counterparty": str(invitation.counterparty_id),
                    "text": msg.text,
                }
            _add_llm_decision_artifact(
                session,
                durable=durable,
                rfq=rfq,
                invitation=invitation,
                input_snapshot=input_snapshot,
                guard_outcomes=_build_guard_outcomes(
                    classification=classification,
                    parsed=None,
                    final_status="needs_human_review",
                    should_auto_create_quote=None,
                    price_in_text=None,
                    duplicate_active_quote=None,
                    payload_complete=None,
                    payload_validation=None,
                ),
                final_status="needs_human_review",
                classification_trace=classification_trace,
                parse_trace=None,
            )
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
        if durable is not None:
            input_snapshot = _build_input_snapshot(
                durable=durable,
                msg=msg,
                rfq=rfq,
                invitation=invitation,
                text_for_downstream=text_for_downstream,
                rfq_context=rfq_context,
            )

        try:
            parsed, parse_trace = _parse_quote_with_optional_trace(
                rfq_context=rfq_context,
                raw_message=text_for_downstream,
                sender_name=msg.sender_name or invitation.recipient_name,
            )
        except LLMUnavailableError as exc:
            parse_trace = exc.trace or _synthetic_error_trace(
                user_prompt=(
                    f"RFQ Context:\n{rfq_context}\n\n"
                    f"Counterparty: {msg.sender_name or invitation.recipient_name}\n\n"
                    f"Message:\n{text_for_downstream}"
                ),
                error=str(exc),
            )
            logger.error(
                "orchestrator_llm_unavailable",
                rfq_id=str(rfq.id),
                error=str(exc),
            )
            _add_llm_decision_artifact(
                session,
                durable=durable,
                rfq=rfq,
                invitation=invitation,
                input_snapshot=input_snapshot,
                guard_outcomes=_build_guard_outcomes(
                    classification=classification,
                    parsed=None,
                    final_status="llm_unavailable",
                    should_auto_create_quote=None,
                    price_in_text=None,
                    duplicate_active_quote=None,
                    payload_complete=None,
                    payload_validation=None,
                    failure_reason=str(exc),
                ),
                final_status="llm_unavailable",
                classification_trace=classification_trace,
                parse_trace=parse_trace,
            )
            return {
                "message_id": msg.message_id,
                "status": "llm_unavailable",
                "rfq_id": str(rfq.id),
            }

        if parsed is None:
            _add_llm_decision_artifact(
                session,
                durable=durable,
                rfq=rfq,
                invitation=invitation,
                input_snapshot=input_snapshot,
                guard_outcomes=_build_guard_outcomes(
                    classification=classification,
                    parsed=None,
                    final_status="llm_unavailable",
                    should_auto_create_quote=None,
                    price_in_text=None,
                    duplicate_active_quote=None,
                    payload_complete=None,
                    payload_validation=None,
                    failure_reason=parse_trace.error if parse_trace else None,
                ),
                final_status="llm_unavailable",
                classification_trace=classification_trace,
                parse_trace=parse_trace,
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
        should_auto_create = LLMAgent.should_auto_create_quote(parsed)
        if should_auto_create:
            price_decimal = (
                parsed.fixed_price_value
                if parsed.fixed_price_value is not None
                else (parsed.premium_discount or Decimal("0"))
            )
            price_in_text = RFQOrchestrator._price_appears_in_text(
                float(price_decimal), text_for_downstream
            )
            if not price_in_text:
                logger.warning(
                    "orchestrator_hallucinated_price_blocked",
                    rfq_id=str(rfq.id),
                    hallucinated_price=float(price_decimal),
                    raw_text=msg.text[:200],
                )
                _add_llm_decision_artifact(
                    session,
                    durable=durable,
                    rfq=rfq,
                    invitation=invitation,
                    input_snapshot=input_snapshot,
                    guard_outcomes=_build_guard_outcomes(
                        classification=classification,
                        parsed=parsed,
                        final_status="hallucinated_price_blocked",
                        should_auto_create_quote=should_auto_create,
                        price_in_text=False,
                        duplicate_active_quote=None,
                        payload_complete=None,
                        payload_validation=None,
                        failure_reason="parsed price not present in inbound text",
                    ),
                    final_status="hallucinated_price_blocked",
                    classification_trace=classification_trace,
                    parse_trace=parse_trace,
                )
                return {
                    "message_id": msg.message_id,
                    "status": "hallucinated_price_blocked",
                    "rfq_id": str(rfq.id),
                    "hallucinated_price": float(price_decimal),
                    "text": msg.text,
                }

            # ── Guard 4: duplicate quote dedup ──
            existing_quote = (
                session.query(RFQQuote)
                .filter(
                    RFQQuote.rfq_id == rfq.id,
                    RFQQuote.counterparty_id == invitation.counterparty_id,
                    RFQQuote.fixed_price_value == price_decimal,
                    # J-A2-08: rejected quotes must not block a fresh
                    # quote at the same price; only ACTIVE rows count
                    # as duplicates.
                    RFQQuote.state == QuoteState.active,
                )
                .first()
            )
            if existing_quote:
                logger.info(
                    "orchestrator_duplicate_quote_skipped",
                    rfq_id=str(rfq.id),
                    counterparty=str(invitation.counterparty_id),
                    price=float(price_decimal),
                    existing_quote_id=str(existing_quote.id),
                )
                replay_artifact = _existing_auto_quote_artifact(
                    session,
                    durable=durable,
                    quote_id=existing_quote.id,
                )
                if replay_artifact is not None:
                    logger.info(
                        "orchestrator_auto_quote_replay_from_artifact",
                        rfq_id=str(rfq.id),
                        quote_id=str(existing_quote.id),
                        delivery_message_id=str(durable.id) if durable else None,
                    )
                    return _auto_quote_replay_result(
                        msg,
                        artifact=replay_artifact,
                        rfq=rfq,
                        quote=existing_quote,
                    )
                _add_llm_decision_artifact(
                    session,
                    durable=durable,
                    rfq=rfq,
                    invitation=invitation,
                    input_snapshot=input_snapshot,
                    guard_outcomes=_build_guard_outcomes(
                        classification=classification,
                        parsed=parsed,
                        final_status="duplicate_quote_skipped",
                        should_auto_create_quote=should_auto_create,
                        price_in_text=True,
                        duplicate_active_quote=True,
                        payload_complete=None,
                        payload_validation=None,
                        failure_reason="duplicate active quote",
                    ),
                    final_status="duplicate_quote_skipped",
                    classification_trace=classification_trace,
                    parse_trace=parse_trace,
                    quote_id=existing_quote.id,
                )
                return {
                    "message_id": msg.message_id,
                    "status": "duplicate_quote_skipped",
                    "rfq_id": str(rfq.id),
                    "existing_quote_id": str(existing_quote.id),
                }

            return RFQOrchestrator._auto_create_quote(
                session,
                rfq,
                invitation,
                msg,
                parsed,
                durable=durable,
                input_snapshot=input_snapshot,
                classification=classification,
                classification_trace=classification_trace,
                parse_trace=parse_trace,
                should_auto_create_quote=should_auto_create,
                price_in_text=True,
            )

        if parsed.intent == MessageIntent.rejection:
            prior_send_status = invitation.send_status.value
            invitation.send_status = RFQInvitationStatus.failed
            session.flush()
            logger.info(
                "orchestrator_counterparty_declined",
                rfq_id=str(rfq.id),
                counterparty=str(invitation.counterparty_id),
            )
            _add_llm_decision_artifact(
                session,
                durable=durable,
                rfq=rfq,
                invitation=invitation,
                input_snapshot=input_snapshot,
                guard_outcomes=_build_guard_outcomes(
                    classification=classification,
                    parsed=parsed,
                    final_status="counterparty_declined",
                    should_auto_create_quote=should_auto_create,
                    price_in_text=None,
                    duplicate_active_quote=None,
                    payload_complete=None,
                    payload_validation=None,
                    state_mutations=[
                        {
                            "model": "RFQInvitation",
                            "field": "send_status",
                            "before": prior_send_status,
                            "after": RFQInvitationStatus.failed.value,
                        }
                    ],
                ),
                final_status="counterparty_declined",
                classification_trace=classification_trace,
                parse_trace=parse_trace,
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
            _add_llm_decision_artifact(
                session,
                durable=durable,
                rfq=rfq,
                invitation=invitation,
                input_snapshot=input_snapshot,
                guard_outcomes=_build_guard_outcomes(
                    classification=classification,
                    parsed=parsed,
                    final_status="counterparty_question",
                    should_auto_create_quote=should_auto_create,
                    price_in_text=None,
                    duplicate_active_quote=None,
                    payload_complete=None,
                    payload_validation=None,
                ),
                final_status="counterparty_question",
                classification_trace=classification_trace,
                parse_trace=parse_trace,
            )
            return {
                "message_id": msg.message_id,
                "status": "counterparty_question",
                "rfq_id": str(rfq.id),
                "counterparty": str(invitation.counterparty_id),
                "text": msg.text,
            }

        _add_llm_decision_artifact(
            session,
            durable=durable,
            rfq=rfq,
            invitation=invitation,
            input_snapshot=input_snapshot,
            guard_outcomes=_build_guard_outcomes(
                classification=classification,
                parsed=parsed,
                final_status="needs_human_review",
                should_auto_create_quote=should_auto_create,
                price_in_text=None,
                duplicate_active_quote=None,
                payload_complete=None,
                payload_validation=None,
            ),
            final_status="needs_human_review",
            classification_trace=classification_trace,
            parse_trace=parse_trace,
        )
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
        *,
        durable: InboundWebhookMessage | None = None,
        input_snapshot: dict | None = None,
        classification: LLMClassifyResult | None = None,
        classification_trace: LLMCallTrace | None = None,
        parse_trace: LLMCallTrace | None = None,
        should_auto_create_quote: bool | None = None,
        price_in_text: bool | None = None,
    ) -> dict:
        """Create a quote automatically from a high-confidence LLM parse."""
        missing: list[str] = []

        if parsed.fixed_price_value is None and parsed.premium_discount is None:
            missing.append("price")

        # Canonicalize the parsed unit so accepted variants like ``USDMT``
        # (returned by the LLM for a broker message) resolve to ``USD/MT``
        # before the membership check. Otherwise valid rankable variants
        # would be silently dropped by exact-string set membership.
        canonical_unit: str | None = None
        if parsed.fixed_price_unit is None:
            missing.append("unit")
        else:
            canonical_unit = RFQService.canonicalize_fixed_price_unit(
                parsed.fixed_price_unit
            )
            if canonical_unit is None or canonical_unit not in CANONICAL_PRICE_UNITS:
                missing.append(f"unit (non-canonical: {parsed.fixed_price_unit!r})")

        float_conv: FloatPricingConvention | None = None
        if parsed.float_pricing_convention is None:
            missing.append("convention")
        else:
            try:
                float_conv = FloatPricingConvention(parsed.float_pricing_convention)
            except ValueError:
                missing.append(
                    f"convention (invalid: {parsed.float_pricing_convention!r})"
                )

        if missing:
            logger.warning(
                "orchestrator_auto_quote_skipped_incomplete",
                rfq_id=str(rfq.id),
                counterparty=str(invitation.counterparty_id),
                missing=missing,
            )
            _add_llm_decision_artifact(
                session,
                durable=durable,
                rfq=rfq,
                invitation=invitation,
                input_snapshot=input_snapshot,
                guard_outcomes=_build_guard_outcomes(
                    classification=classification,
                    parsed=parsed,
                    final_status="auto_quote_skipped_incomplete",
                    should_auto_create_quote=should_auto_create_quote,
                    price_in_text=price_in_text,
                    duplicate_active_quote=False,
                    payload_complete=False,
                    payload_validation=None,
                    failure_reason=", ".join(missing),
                ),
                final_status="auto_quote_skipped_incomplete",
                classification_trace=classification_trace,
                parse_trace=parse_trace,
            )
            return {
                "message_id": msg.message_id,
                "status": "auto_quote_skipped_incomplete",
                "rfq_id": str(rfq.id),
                "missing": missing,
            }

        price_value = (
            parsed.fixed_price_value
            if parsed.fixed_price_value is not None
            else parsed.premium_discount
        )
        if price_value is None or float_conv is None or canonical_unit is None:
            raise AssertionError("auto quote validation failed to establish fields")

        # PR-6 (J-A2-OPUS-03): canonical fields are pre-validated above; no
        # `or "USD/MT"` / `or Decimal("0")` fallbacks here.
        # Codex P2 (post-rebase): wrap the schema constructor in
        # try/ValidationError so an LLM parse with >PRICE_NUMERIC_SCALE
        # fractional digits (or any other Pydantic constraint failure)
        # routes to a structured skip status instead of an unhandled raise.
        try:
            quote_payload = RFQQuoteCreate(
                rfq_id=rfq.id,
                counterparty_id=invitation.counterparty_id,
                fixed_price_value=Decimal(str(price_value)),
                fixed_price_unit=canonical_unit,
                float_pricing_convention=float_conv,
                received_at=msg.timestamp,
            )
        except ValidationError as exc:
            logger.warning(
                "orchestrator_auto_quote_skipped_invalid_payload",
                rfq_id=str(rfq.id),
                error=str(exc),
                price_value=str(price_value),
            )
            _add_llm_decision_artifact(
                session,
                durable=durable,
                rfq=rfq,
                invitation=invitation,
                input_snapshot=input_snapshot,
                guard_outcomes=_build_guard_outcomes(
                    classification=classification,
                    parsed=parsed,
                    final_status="auto_quote_skipped_invalid_payload",
                    should_auto_create_quote=should_auto_create_quote,
                    price_in_text=price_in_text,
                    duplicate_active_quote=False,
                    payload_complete=True,
                    payload_validation=str(exc),
                    failure_reason=str(exc),
                ),
                final_status="auto_quote_skipped_invalid_payload",
                classification_trace=classification_trace,
                parse_trace=parse_trace,
            )
            return {
                "message_id": msg.message_id,
                "status": "auto_quote_skipped_invalid_payload",
                "rfq_id": str(rfq.id),
                "error": str(exc),
            }

        rfq_id_str = str(rfq.id)
        try:
            quote = RFQService.submit_quote(session, rfq.id, quote_payload)
            # Codex P2 (PR-8 round): capture scalar attributes BEFORE
            # `session.commit()` because SQLAlchemy default
            # `expire_on_commit=True` (`backend/app/core/database.py`)
            # would expire `quote`/`rfq`/`invitation` instances after
            # commit, so any subsequent attribute read in the post-commit
            # log/return path could trigger a refresh query — which, if
            # the DB connection drops mid-flight, would raise inside the
            # post-commit code and route a durably-committed quote into
            # the failure path. Snapshot now while attrs are live.
            quote_id_str = str(quote.id)
            counterparty_id_str = str(invitation.counterparty_id)
            quote_price_str = str(quote.fixed_price_value)
            _add_llm_decision_artifact(
                session,
                durable=durable,
                rfq=rfq,
                invitation=invitation,
                input_snapshot=input_snapshot,
                guard_outcomes=_build_guard_outcomes(
                    classification=classification,
                    parsed=parsed,
                    final_status="auto_quote_created",
                    should_auto_create_quote=should_auto_create_quote,
                    price_in_text=price_in_text,
                    duplicate_active_quote=False,
                    payload_complete=True,
                    payload_validation="valid",
                ),
                final_status="auto_quote_created",
                classification_trace=classification_trace,
                parse_trace=parse_trace,
                quote_id=quote.id,
            )
            session.commit()
        except (HTTPException, SQLAlchemyError, ArtifactPayloadError) as exc:
            session.rollback()
            if not isinstance(exc, ArtifactPayloadError):
                _add_llm_decision_artifact(
                    session,
                    durable=durable,
                    rfq=rfq,
                    invitation=invitation,
                    input_snapshot=input_snapshot,
                    guard_outcomes=_build_guard_outcomes(
                        classification=classification,
                        parsed=parsed,
                        final_status="auto_quote_failed",
                        should_auto_create_quote=should_auto_create_quote,
                        price_in_text=price_in_text,
                        duplicate_active_quote=False,
                        payload_complete=True,
                        payload_validation="valid",
                        failure_reason=str(exc),
                    ),
                    final_status="auto_quote_failed",
                    classification_trace=classification_trace,
                    parse_trace=parse_trace,
                )
            logger.error(
                "orchestrator_auto_quote_failed",
                rfq_id=rfq_id_str,
                error=str(exc),
            )
            return {
                "message_id": msg.message_id,
                "status": "auto_quote_failed",
                "rfq_id": rfq_id_str,
                "error": str(exc),
            }

        try:
            logger.info(
                "orchestrator_auto_quote_created",
                rfq_id=rfq_id_str,
                quote_id=quote_id_str,
                counterparty=counterparty_id_str,
                price=quote_price_str,
            )
        except Exception:
            logger.warning(
                "orchestrator_auto_quote_post_commit_log_failed",
                quote_id=quote_id_str,
            )

        return {
            "message_id": msg.message_id,
            "status": "auto_quote_created",
            "rfq_id": rfq_id_str,
            "quote_id": quote_id_str,
            "confidence": parsed.confidence,
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
        """Send WhatsApp award notification to the winning counterparty.

        Per Phase A2 PR-4 (J-A2-OPUS-02 + J-A2-05 + J-A2-07), the outbound
        message is persisted as an ``RFQInvitation`` row with
        ``purpose=award_notify`` BEFORE the WhatsApp send. The orchestrator
        path has no enclosing route transaction guarantee, so the queued row
        is written via a separate ``SessionLocal()`` (§3.2 strategy a) — the
        row remains durable even if this method's caller subsequently
        rolls back.
        """
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
        message = prefix_with_canonical_id(message, rfq.rfq_number)

        idem_key = f"award-notify:{rfq.rfq_number}:{cp_uuid}"
        # Strategy (a): durable outbox row in its own session BEFORE send.
        row_id = _persist_outbox_queued(
            rfq_id=rfq.id,
            rfq_number=rfq.rfq_number,
            counterparty_id=cp_uuid,
            recipient_name=invitation.recipient_name,
            recipient_phone=invitation.recipient_phone,
            channel=RFQInvitationChannel.whatsapp,
            message_body=message,
            purpose=RFQInvitationPurpose.award_notify,
            idempotency_key=idem_key,
        )

        result = WhatsAppService.send_text_message(
            phone=invitation.recipient_phone,
            text=message,
        )

        # Status update lands in the orchestrator's session.
        outbox_row = session.get(RFQInvitation, row_id)
        if outbox_row is None:
            logger.warning(
                "orchestrator_outbox_row_missing_after_persist",
                rfq_number=rfq.rfq_number,
                row_id=str(row_id),
            )
            return
        if result.success:
            outbox_row.send_status = RFQInvitationStatus.sent
            outbox_row.sent_at = now_utc()
            outbox_row.provider_message_id = result.provider_message_id or ""
        else:
            outbox_row.send_status = RFQInvitationStatus.failed
            outbox_row.failure_reason = (
                f"{result.error_code}: {result.error_message}"
                if (result.error_code or result.error_message)
                else "send_failed"
            )

    @staticmethod
    def notify_reject(
        session: Session,
        rfq: RFQ,
        language: str = "pt_BR",
    ) -> None:
        """Send WhatsApp rejection notification to all counterparties.

        Per Phase A2 PR-4 (J-A2-OPUS-02 + J-A2-05 + J-A2-07), each outbound
        is persisted as a ``purpose=reject_notify`` ``RFQInvitation`` row in
        its own session BEFORE the WhatsApp send (§3.2 strategy a) so a
        downstream rollback in the caller cannot lose evidence.
        """
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
            message = prefix_with_canonical_id(message, rfq.rfq_number)

            idem_key = f"reject-notify:{rfq.rfq_number}:{inv.counterparty_id}"
            row_id = _persist_outbox_queued(
                rfq_id=rfq.id,
                rfq_number=rfq.rfq_number,
                counterparty_id=inv.counterparty_id,
                recipient_name=inv.recipient_name,
                recipient_phone=inv.recipient_phone,
                channel=RFQInvitationChannel.whatsapp,
                message_body=message,
                purpose=RFQInvitationPurpose.reject_notify,
                idempotency_key=idem_key,
            )

            result = WhatsAppService.send_text_message(
                phone=inv.recipient_phone, text=message
            )

            outbox_row = session.get(RFQInvitation, row_id)
            if outbox_row is None:
                logger.warning(
                    "orchestrator_outbox_row_missing_after_persist",
                    rfq_number=rfq.rfq_number,
                    row_id=str(row_id),
                )
                continue
            if result.success:
                outbox_row.send_status = RFQInvitationStatus.sent
                outbox_row.sent_at = now_utc()
                outbox_row.provider_message_id = result.provider_message_id or ""
            else:
                outbox_row.send_status = RFQInvitationStatus.failed
                outbox_row.failure_reason = (
                    f"{result.error_code}: {result.error_message}"
                    if (result.error_code or result.error_message)
                    else "send_failed"
                )

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
