from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal, InvalidOperation

from app.core.utils import now_utc
import hashlib
import logging
import re
import threading
import time

import httpx
import structlog
from tenacity import (
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
    before_sleep_log,
)


WESTMETALL_DAILY_URL = (
    "https://www.westmetall.com/en/markdaten.php?action=table&field=LME_Al_cash"
)

SYMBOL_DAILY = "LME_ALU_CASH_SETTLEMENT_DAILY"
SOURCE_WESTMETALL = "westmetall"

logger = structlog.get_logger(__name__)

# ── Circuit breaker state ──────────────────────────────────────────────
_CB_LOCK = threading.Lock()
_CB_FAILURE_COUNT = 0
_CB_OPEN_UNTIL: float = 0.0
CB_FAILURE_THRESHOLD = 5
CB_COOLDOWN_SECONDS = 60.0


class CircuitOpenError(RuntimeError):
    """Raised when the circuit breaker is open."""

    pass


def _cb_record_success() -> None:
    global _CB_FAILURE_COUNT, _CB_OPEN_UNTIL  # noqa: PLW0603
    with _CB_LOCK:
        _CB_FAILURE_COUNT = 0
        _CB_OPEN_UNTIL = 0.0


def _cb_record_failure() -> None:
    global _CB_FAILURE_COUNT, _CB_OPEN_UNTIL  # noqa: PLW0603
    with _CB_LOCK:
        _CB_FAILURE_COUNT += 1
        if _CB_FAILURE_COUNT >= CB_FAILURE_THRESHOLD:
            _CB_OPEN_UNTIL = time.monotonic() + CB_COOLDOWN_SECONDS
            logger.warning(
                "circuit_breaker_opened",
                failure_count=_CB_FAILURE_COUNT,
                cooldown_seconds=CB_COOLDOWN_SECONDS,
            )


def _cb_check() -> None:
    with _CB_LOCK:
        if _CB_OPEN_UNTIL and time.monotonic() < _CB_OPEN_UNTIL:
            raise CircuitOpenError(
                f"Circuit breaker open — {CB_FAILURE_THRESHOLD} consecutive failures. "
                f"Try again in {int(_CB_OPEN_UNTIL - time.monotonic())}s."
            )


def reset_circuit_breaker() -> None:
    """Reset circuit breaker state — for testing only."""
    global _CB_FAILURE_COUNT, _CB_OPEN_UNTIL  # noqa: PLW0603
    with _CB_LOCK:
        _CB_FAILURE_COUNT = 0
        _CB_OPEN_UNTIL = 0.0


class WestmetallLayoutError(RuntimeError):
    pass


@dataclass(frozen=True)
class WestmetallFetchEvidence:
    source_url: str
    html_sha256: str
    fetched_at: datetime


@dataclass(frozen=True)
class WestmetallDailyRow:
    settlement_date: date
    price_usd: Decimal


def fetch_westmetall_html(
    url: str, *, timeout_seconds: float = 30.0
) -> tuple[bytes, WestmetallFetchEvidence]:
    """Fetch HTML from Westmetall with retry + circuit breaker.

    * 3 attempts with exponential back-off (1 → 2 → 4 s, capped at 10 s).
    * Circuit breaker opens after 5 consecutive failures for 60 s (HTTP 503).
    """
    _cb_check()  # raises CircuitOpenError if open
    try:
        return _fetch_with_retry(url, timeout_seconds=timeout_seconds)
    except Exception:
        _cb_record_failure()
        raise


@retry(
    retry=retry_if_exception_type((httpx.HTTPStatusError, httpx.TransportError)),
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=1, min=1, max=10),
    before_sleep=before_sleep_log(logging.getLogger(__name__), logging.WARNING),
    reraise=True,
)
def _fetch_with_retry(
    url: str, *, timeout_seconds: float = 30.0
) -> tuple[bytes, WestmetallFetchEvidence]:
    fetched_at = now_utc()
    response = httpx.get(url, timeout=timeout_seconds)
    response.raise_for_status()
    html = response.content
    html_sha256 = hashlib.sha256(html).hexdigest()
    evidence = WestmetallFetchEvidence(
        source_url=url, html_sha256=html_sha256, fetched_at=fetched_at
    )
    _cb_record_success()
    return html, evidence


_DATE_NUMERIC_RE = re.compile(r"^(?P<d>\d{2})\.(?P<m>\d{2})\.(?P<y>\d{4})$")
_DATE_TEXT_RE = re.compile(
    r"^(?P<d>\d{1,2})\.\s*(?P<month>[A-Za-z]+)\s+(?P<y>\d{4})$"
)
_MONTH_MAP: dict[str, int] = {
    "january": 1, "february": 2, "march": 3, "april": 4,
    "may": 5, "june": 6, "july": 7, "august": 8,
    "september": 9, "october": 10, "november": 11, "december": 12,
}


def _parse_settlement_date(value: str) -> date | None:
    """Parse a settlement date in either ``dd.mm.yyyy`` or ``dd. Month yyyy`` format."""
    txt = value.strip()

    # Try numeric format first: 04.03.2026
    m = _DATE_NUMERIC_RE.match(txt)
    if m:
        return date(int(m.group("y")), int(m.group("m")), int(m.group("d")))

    # Try text-month format: 04. March 2026
    m = _DATE_TEXT_RE.match(txt)
    if m:
        month_num = _MONTH_MAP.get(m.group("month").lower())
        if month_num:
            return date(int(m.group("y")), month_num, int(m.group("d")))

    return None


def _parse_price_decimal(value: str) -> Decimal | None:
    if not isinstance(value, str):
        raise TypeError(
            f"_parse_price_decimal accepts str only; got {type(value).__name__}. "
            "Float inputs forbidden at parser boundary."
        )
    cleaned = value.strip().replace("\xa0", " ").replace(" ", "")
    if not cleaned:
        return None
    has_comma = "," in cleaned
    has_dot = "." in cleaned
    if has_comma and has_dot:
        if cleaned.rindex(",") > cleaned.rindex("."):
            cleaned = cleaned.replace(".", "").replace(",", ".")
        else:
            cleaned = cleaned.replace(",", "")
    elif has_comma:
        if len(cleaned) - cleaned.rindex(",") <= 3:
            cleaned = cleaned.replace(",", ".")
        else:
            cleaned = cleaned.replace(",", "")
    try:
        return Decimal(cleaned)
    except InvalidOperation:
        return None


_TD_RE = re.compile(r"<t[dh][^>]*>(?P<content>.*?)</t[dh]>", re.IGNORECASE | re.DOTALL)
_TAG_RE = re.compile(r"<[^>]+>")


def parse_westmetall_daily_rows(html: bytes) -> list[WestmetallDailyRow]:
    text = html.decode("utf-8", errors="replace")

    rows: list[WestmetallDailyRow] = []
    for tr in re.findall(r"<tr[^>]*>.*?</tr>", text, flags=re.IGNORECASE | re.DOTALL):
        cells = []
        for cell in _TD_RE.findall(tr):
            cell_text = _TAG_RE.sub("", cell)
            cell_text = cell_text.strip()
            if cell_text:
                cells.append(cell_text)
        if len(cells) < 2:
            continue
        parsed_date = _parse_settlement_date(cells[0])
        if not parsed_date:
            continue
        parsed_price = _parse_price_decimal(cells[1])
        if parsed_price is None:
            continue
        rows.append(
            WestmetallDailyRow(settlement_date=parsed_date, price_usd=parsed_price)
        )

    if not rows:
        raise WestmetallLayoutError("no_daily_rows_parsed")
    return rows
