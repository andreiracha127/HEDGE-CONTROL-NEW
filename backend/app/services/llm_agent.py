"""LLM Agent for parsing inbound counterparty messages into structured quotes.

Integrates with OpenAI (GPT-4o-mini) to:
1. Classify message intent (QUOTE / REJECTION / QUESTION / OTHER).
2. Extract structured quote data when intent is QUOTE.
3. Generate outbound messages for different RFQ lifecycle events.

Configuration via environment variables:
- ``OPENAI_API_KEY``
- ``OPENAI_MODEL`` (default: ``gpt-4o-mini``)

The agent is designed to be cost-efficient (< $0.001 per call with GPT-4o-mini)
and includes a confidence threshold (0.85) for automatic processing.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from typing import Any

from openai import APIConnectionError, APIError, APIStatusError, APITimeoutError, OpenAI
from tenacity import (
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)

from app.core.config import get_settings
from app.core.logging import get_logger
from app.schemas.llm import LLMClassifyResult, MessageIntent, ParsedQuote

logger = get_logger()

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

CONFIDENCE_THRESHOLD = 0.85

_CLASSIFY_SYSTEM_PROMPT = """You are an expert commodity trading assistant.
Classify the following message from a counterparty responding to an RFQ
(Request for Quote) into one of these intents:
- QUOTE: The message contains a price offer / quotation
- REJECTION: The counterparty declines to quote
- QUESTION: The counterparty is asking for clarification
- OTHER: Anything else (greeting, acknowledgment, etc.)

Respond ONLY with a JSON object: {"intent": "...", "confidence": 0.0-1.0, "reasoning": "..."}
"""

_PARSE_SYSTEM_PROMPT = """You are an expert commodity trading assistant.
Extract the structured quote information from the following message.
The RFQ context is provided so you understand what is being quoted.

Respond ONLY with a JSON object:
{
  "intent": "QUOTE",
  "confidence": 0.0-1.0,
  "fixed_price_value": <number or null>,
  "fixed_price_unit": "<string like USD/MT or null>",
  "float_pricing_convention": "<avg|avginter|c2r or null>",
  "premium_discount": <number or null — premium/discount over LME reference, positive = premium, negative = discount>,
  "counterparty_name": "<name>",
  "notes": "<any additional notes or null>"
}

Rules:
- If the message contains an absolute price (e.g. "2450 USD/MT"), set fixed_price_value.
- If the message contains a premium/discount (e.g. "+15", "-10 USD/MT", "flat"), set premium_discount.
  "flat" means premium_discount = 0.
- float_pricing_convention: "avg" for monthly average, "avginter" for inter-month average, "c2r" for cash-to-reference.
- If you cannot reliably parse the quote, set confidence below 0.85.
- Support both Portuguese (PT-BR) and English messages.
"""

_GENERATE_TEMPLATES = {
    "rfq_request": (
        "Prezado(a) {recipient_name},\n\n"
        "Solicitamos cotação para:\n"
        "- Commodity: {commodity}\n"
        "- Quantidade: {quantity_mt} MT\n"
        "- Janela de entrega: {delivery_start} a {delivery_end}\n"
        "- Direção: {direction}\n"
        "- Referência: {rfq_number}\n\n"
        "Aguardamos sua cotação o mais breve possível.\n"
        "Atenciosamente."
    ),
    "rfq_request_en": (
        "Dear {recipient_name},\n\n"
        "We request a quote for:\n"
        "- Commodity: {commodity}\n"
        "- Quantity: {quantity_mt} MT\n"
        "- Delivery window: {delivery_start} to {delivery_end}\n"
        "- Direction: {direction}\n"
        "- Reference: {rfq_number}\n\n"
        "Please submit your quote at your earliest convenience.\n"
        "Best regards."
    ),
    "refresh": (
        "Prezado(a) {recipient_name},\n\n"
        "Solicitamos a renovação da sua cotação para a RFQ {rfq_number}.\n"
        "Favor reenviar sua proposta atualizada.\n"
        "Atenciosamente."
    ),
    "refresh_en": (
        "Dear {recipient_name},\n\n"
        "Please resubmit your updated quote for RFQ {rfq_number}.\n"
        "Best regards."
    ),
    "award": (
        "Prezado(a) {recipient_name},\n\n"
        "Temos o prazer de informar que sua cotação de {price} {unit} "
        "foi aceita para a RFQ {rfq_number}.\n"
        "Entraremos em contato para formalização do contrato.\n"
        "Atenciosamente."
    ),
    "award_en": (
        "Dear {recipient_name},\n\n"
        "We are pleased to inform you that your quote of {price} {unit} "
        "has been accepted for RFQ {rfq_number}.\n"
        "We will contact you for contract formalization.\n"
        "Best regards."
    ),
    "reject": (
        "Prezado(a) {recipient_name},\n\n"
        "Informamos que a RFQ {rfq_number} foi encerrada.\n"
        "Agradecemos sua participação.\n"
        "Atenciosamente."
    ),
    "reject_en": (
        "Dear {recipient_name},\n\n"
        "We inform you that RFQ {rfq_number} has been closed.\n"
        "Thank you for your participation.\n"
        "Best regards."
    ),
}


# ---------------------------------------------------------------------------
# OpenAI client helpers
# ---------------------------------------------------------------------------


_REQUEST_PARAMS: dict[str, Any] = {
    "temperature": 0.1,
    "max_tokens": 500,
    "response_format": {"type": "json_object"},
}


@dataclass(frozen=True)
class LLMCallTrace:
    provider: str
    model: str
    system_prompt: str
    user_prompt: str
    messages: list[dict[str, str]]
    request_params: dict[str, Any]
    raw_response: str | None
    parsed_response: dict[str, Any] | None
    normalized_result: dict[str, Any] | None
    error: str | None = None


@dataclass(frozen=True)
class LLMClassifyDecision:
    result: LLMClassifyResult | None
    trace: LLMCallTrace


@dataclass(frozen=True)
class LLMParseDecision:
    result: ParsedQuote | None
    trace: LLMCallTrace


@retry(
    retry=retry_if_exception_type(
        (APITimeoutError, APIConnectionError, APIStatusError)
    ),
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=1, min=1, max=8),
    reraise=True,
)
def _call_openai_with_retry(
    client: OpenAI,
    model: str,
    messages: list[dict[str, str]],
) -> str:
    """HTTP call with exponential-backoff retry on transient failures."""
    completion = client.chat.completions.create(
        model=model,
        messages=messages,
        **_REQUEST_PARAMS,
    )
    content = completion.choices[0].message.content
    if content is None:
        raise KeyError("choices[0].message.content")
    return content


def _call_openai_with_trace(
    system_prompt: str,
    user_prompt: str,
) -> tuple[dict[str, Any], LLMCallTrace]:
    """Call OpenAI and return parsed JSON plus reconstruction evidence."""
    settings = get_settings()
    api_key = settings.openai_api_key
    model = settings.openai_model or "gpt-4o-mini"
    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_prompt},
    ]

    if not api_key:
        trace = LLMCallTrace(
            provider="openai",
            model=model,
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            messages=messages,
            request_params=dict(_REQUEST_PARAMS),
            raw_response=None,
            parsed_response=None,
            normalized_result=None,
            error="OpenAI not configured",
        )
        raise LLMUnavailableError("OpenAI not configured", trace)

    client = OpenAI(api_key=api_key, timeout=30.0, max_retries=0)

    try:
        raw_response = _call_openai_with_retry(client, model, messages)
        parsed = json.loads(raw_response)
        trace = LLMCallTrace(
            provider="openai",
            model=model,
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            messages=messages,
            request_params=dict(_REQUEST_PARAMS),
            raw_response=raw_response,
            parsed_response=parsed,
            normalized_result=None,
        )
        return parsed, trace
    except APITimeoutError as exc:
        logger.error("llm_timeout_after_retries")
        trace = LLMCallTrace(
            provider="openai",
            model=model,
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            messages=messages,
            request_params=dict(_REQUEST_PARAMS),
            raw_response=None,
            parsed_response=None,
            normalized_result=None,
            error="OpenAI request timed out after retries",
        )
        raise LLMUnavailableError("OpenAI request timed out after retries", trace) from exc
    except (APIError, KeyError, json.JSONDecodeError) as exc:
        logger.error("llm_call_failed_after_retries", error=str(exc), exc_info=True)
        trace = LLMCallTrace(
            provider="openai",
            model=model,
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            messages=messages,
            request_params=dict(_REQUEST_PARAMS),
            raw_response=raw_response if "raw_response" in locals() else None,
            parsed_response=None,
            normalized_result=None,
            error=f"{type(exc).__name__}: {exc}",
        )
        raise LLMUnavailableError(f"OpenAI call failed: {exc}", trace) from exc


def _call_openai(
    system_prompt: str,
    user_prompt: str,
) -> dict[str, Any]:
    """Call OpenAI chat completions and return the parsed JSON response.

    Retries up to 3 times with exponential backoff on transient failures.
    Raises ``LLMUnavailableError`` if all attempts fail.
    """
    try:
        parsed, _trace = _call_openai_with_trace(system_prompt, user_prompt)
        return parsed
    except LLMUnavailableError:
        raise


# ---------------------------------------------------------------------------
# Exceptions
# ---------------------------------------------------------------------------


class LLMUnavailableError(Exception):
    """Raised when the LLM backend is not reachable or not configured."""

    def __init__(self, message: str, trace: LLMCallTrace | None = None) -> None:
        super().__init__(message)
        self.trace = trace


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


class LLMAgent:
    """Stateless LLM-powered agent for RFQ message processing."""

    @staticmethod
    def classify_intent(message: str) -> LLMClassifyResult:
        """Classify a raw message into an intent category.

        Returns a :class:`LLMClassifyResult` with intent, confidence, and
        optional reasoning.
        """
        result = _call_openai(_CLASSIFY_SYSTEM_PROMPT, message)

        intent_str = result.get("intent", "OTHER").upper()
        try:
            intent = MessageIntent(intent_str)
        except ValueError:
            intent = MessageIntent.other

        confidence = float(result.get("confidence", 0.0))
        confidence = max(0.0, min(1.0, confidence))

        return LLMClassifyResult(
            intent=intent,
            confidence=confidence,
            raw_reasoning=result.get("reasoning"),
        )

    @staticmethod
    def classify_intent_with_trace(message: str) -> LLMClassifyDecision:
        """Classify a message and return durable reconstruction evidence."""
        try:
            result, trace = _call_openai_with_trace(_CLASSIFY_SYSTEM_PROMPT, message)
        except LLMUnavailableError as exc:
            if exc.trace is None:
                raise
            return LLMClassifyDecision(result=None, trace=exc.trace)

        intent_str = result.get("intent", "OTHER").upper()
        try:
            intent = MessageIntent(intent_str)
        except ValueError:
            intent = MessageIntent.other

        confidence = float(result.get("confidence", 0.0))
        confidence = max(0.0, min(1.0, confidence))

        normalized = LLMClassifyResult(
            intent=intent,
            confidence=confidence,
            raw_reasoning=result.get("reasoning"),
        )
        trace = LLMCallTrace(
            **{**trace.__dict__, "normalized_result": normalized.model_dump(mode="json")}
        )
        return LLMClassifyDecision(result=normalized, trace=trace)

    @staticmethod
    def parse_quote_message(
        rfq_context: str,
        raw_message: str,
        sender_name: str = "Unknown",
    ) -> ParsedQuote:
        """Parse a raw counterparty message into a structured quote.

        Parameters
        ----------
        rfq_context:
            A textual description of the RFQ being quoted (commodity, qty, etc.).
        raw_message:
            The raw text message received from the counterparty.
        sender_name:
            Name of the counterparty sending the message.
        """
        user_prompt = (
            f"RFQ Context:\n{rfq_context}\n\n"
            f"Counterparty: {sender_name}\n\n"
            f"Message:\n{raw_message}"
        )
        result = _call_openai(_PARSE_SYSTEM_PROMPT, user_prompt)

        intent_str = result.get("intent", "OTHER").upper()
        try:
            intent = MessageIntent(intent_str)
        except ValueError:
            intent = MessageIntent.other

        confidence = float(result.get("confidence", 0.0))
        confidence = max(0.0, min(1.0, confidence))

        fixed_price_value = None
        raw_price = result.get("fixed_price_value")
        if raw_price is not None:
            try:
                fixed_price_value = Decimal(str(raw_price))
            except (InvalidOperation, ValueError):
                fixed_price_value = None

        premium_discount = None
        raw_premium = result.get("premium_discount")
        if raw_premium is not None:
            try:
                premium_discount = Decimal(str(raw_premium))
            except (InvalidOperation, ValueError):
                premium_discount = None

        return ParsedQuote(
            intent=intent,
            confidence=confidence,
            fixed_price_value=fixed_price_value,
            fixed_price_unit=result.get("fixed_price_unit"),
            float_pricing_convention=result.get("float_pricing_convention"),
            premium_discount=premium_discount,
            counterparty_name=result.get("counterparty_name", sender_name),
            notes=result.get("notes"),
        )

    @staticmethod
    def parse_quote_message_with_trace(
        rfq_context: str,
        raw_message: str,
        sender_name: str = "Unknown",
    ) -> LLMParseDecision:
        """Parse a quote message and return durable reconstruction evidence."""
        user_prompt = (
            f"RFQ Context:\n{rfq_context}\n\n"
            f"Counterparty: {sender_name}\n\n"
            f"Message:\n{raw_message}"
        )
        try:
            result, trace = _call_openai_with_trace(_PARSE_SYSTEM_PROMPT, user_prompt)
        except LLMUnavailableError as exc:
            if exc.trace is None:
                raise
            return LLMParseDecision(result=None, trace=exc.trace)

        intent_str = result.get("intent", "OTHER").upper()
        try:
            intent = MessageIntent(intent_str)
        except ValueError:
            intent = MessageIntent.other

        confidence = float(result.get("confidence", 0.0))
        confidence = max(0.0, min(1.0, confidence))

        fixed_price_value = None
        raw_price = result.get("fixed_price_value")
        if raw_price is not None:
            try:
                fixed_price_value = Decimal(str(raw_price))
            except (InvalidOperation, ValueError):
                fixed_price_value = None

        premium_discount = None
        raw_premium = result.get("premium_discount")
        if raw_premium is not None:
            try:
                premium_discount = Decimal(str(raw_premium))
            except (InvalidOperation, ValueError):
                premium_discount = None

        normalized = ParsedQuote(
            intent=intent,
            confidence=confidence,
            fixed_price_value=fixed_price_value,
            fixed_price_unit=result.get("fixed_price_unit"),
            float_pricing_convention=result.get("float_pricing_convention"),
            premium_discount=premium_discount,
            counterparty_name=result.get("counterparty_name", sender_name),
            notes=result.get("notes"),
        )
        trace = LLMCallTrace(
            **{**trace.__dict__, "normalized_result": normalized.model_dump(mode="json")}
        )
        return LLMParseDecision(result=normalized, trace=trace)

    @staticmethod
    def generate_outbound_message(
        action: str,
        language: str = "pt_BR",
        **kwargs: Any,
    ) -> str:
        """Generate a contextual outbound message using templates.

        Parameters
        ----------
        action:
            One of ``rfq_request``, ``refresh``, ``award``, ``reject``.
        language:
            ``pt_BR`` (default) or ``en``.
        **kwargs:
            Template variables (e.g. ``recipient_name``, ``commodity``,
            ``rfq_number``, etc.).
        """
        template_key = action if language == "pt_BR" else f"{action}_en"
        template = _GENERATE_TEMPLATES.get(template_key)

        if not template:
            logger.warning(
                "llm_template_not_found",
                action=action,
                language=language,
            )
            # Fallback to Portuguese
            template = _GENERATE_TEMPLATES.get(action, "")

        if not template:
            return f"[{action}] {kwargs.get('rfq_number', 'N/A')}"

        from string import Formatter

        field_names = {
            fname
            for _, fname, _, _ in Formatter().parse(template)
            if fname is not None
        }
        safe_kwargs = {k: kwargs.get(k, "") for k in field_names}
        safe_kwargs.update(kwargs)

        try:
            return template.format(**safe_kwargs)
        except (KeyError, IndexError) as exc:
            logger.warning(
                "llm_template_missing_var",
                action=action,
                missing_key=str(exc),
            )
            return template

    @staticmethod
    def should_auto_create_quote(parsed: ParsedQuote) -> bool:
        """Return ``True`` if the parsed quote has high enough confidence
        for automatic quote creation (>= 0.85 threshold).

        Accepts either a fixed price or a premium/discount (for spreads).
        """
        return (
            parsed.intent == MessageIntent.quote
            and parsed.confidence >= CONFIDENCE_THRESHOLD
            and (
                parsed.fixed_price_value is not None
                or parsed.premium_discount is not None
            )
        )
