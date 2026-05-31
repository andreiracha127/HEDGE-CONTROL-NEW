"""Thin, mockable boundary to the hosted OpenSanctions match API.

This is the single external-I/O point of the W2 sanctions subsystem. It builds
the OpenSanctions ``EntityMatchQuery`` envelope, POSTs it, and parses the
response into a normalized ``MatchResult``. It NEVER returns a default ``clear``:
any network / HTTP / parse failure raises ``ScreeningProviderError`` so the
service can record fail-closed error evidence.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal, InvalidOperation

import httpx

from app.core.config import get_settings

_MATCH_URL = "https://api.opensanctions.org/match/sanctions"
_ALGORITHM = "logic-v2"
_QUERY_ID = "q1"
_TIMEOUT_SECONDS = 30.0


class ScreeningProviderError(Exception):
    """Raised on any provider failure (missing key, network, non-2xx, parse)."""


@dataclass(frozen=True)
class MatchResult:
    top_score: Decimal
    match_count: int
    matches: list
    dataset_version: str | None
    algorithm: str


def _api_key() -> str:
    return get_settings().opensanctions_api_key


def _build_envelope(name: str, country: str | None, tax_id: str | None, lei: str | None) -> dict:
    # Array-valued properties; omit keys whose source value is absent (a bare or
    # scalar body is rejected by the API).
    props: dict[str, list[str]] = {"name": [name]}
    if country:
        props["jurisdiction"] = [country]
    if tax_id:
        props["registrationNumber"] = [tax_id]
    if lei:
        props["leiCode"] = [lei]
    return {"queries": {_QUERY_ID: {"schema": "Company", "properties": props}}}


def screen_entity(
    *, name: str, country: str | None, tax_id: str | None, lei: str | None
) -> MatchResult:
    key = _api_key()
    if not key or not key.strip():
        raise ScreeningProviderError("OPENSANCTIONS_API_KEY is not configured")
    envelope = _build_envelope(name, country, tax_id, lei)
    try:
        response = httpx.post(
            f"{_MATCH_URL}?algorithm={_ALGORITHM}",
            headers={"Authorization": f"ApiKey {key}"},
            json=envelope,
            timeout=_TIMEOUT_SECONDS,
        )
        response.raise_for_status()
        data = response.json()
    except httpx.HTTPError as exc:
        raise ScreeningProviderError(f"OpenSanctions request failed: {exc}") from exc
    except ValueError as exc:  # JSON decode
        raise ScreeningProviderError(f"OpenSanctions returned unparseable body: {exc}") from exc

    try:
        query_response = data["responses"][_QUERY_ID]
    except (KeyError, TypeError) as exc:
        raise ScreeningProviderError(f"OpenSanctions response missing query: {exc}") from exc

    # The batch /match envelope carries a per-query HTTP-like ``status``. A query
    # that errored (status != 200) can return an HTTP-200 batch with no results;
    # mapping that empty set to top_score=0 -> clear would be a silent fallback.
    # Fail closed: reject any non-200 query status before reading results.
    query_status = query_response.get("status") if isinstance(query_response, dict) else None
    if query_status is not None and query_status != 200:
        raise ScreeningProviderError(
            f"OpenSanctions query status {query_status}: {query_response.get('error')}"
        )

    try:
        results = query_response["results"]
    except (KeyError, TypeError) as exc:
        raise ScreeningProviderError(f"OpenSanctions response missing results: {exc}") from exc

    # Fail closed on a malformed payload (results: null, a dict instead of a list,
    # or a non-object item): these must NOT slip through to a default top_score=0
    # 'clear' — they are provider parse failures.
    if not isinstance(results, list) or not all(isinstance(r, dict) for r in results):
        raise ScreeningProviderError(
            f"OpenSanctions 'results' is malformed (expected a list of objects, "
            f"got {type(results).__name__})"
        )

    # A returned match MUST carry a score. A non-empty result set whose objects omit
    # `score` would otherwise filter to an empty `scores` list -> top_score=0 -> a
    # false `clear` while match_count > 0. Treat a scoreless match as a parse error.
    if any("score" not in r for r in results):
        raise ScreeningProviderError("OpenSanctions match result is missing a 'score'")

    try:
        scores = [Decimal(str(r["score"])) for r in results]
    except (InvalidOperation, TypeError, ValueError) as exc:
        raise ScreeningProviderError(
            f"OpenSanctions returned malformed match results: {exc}"
        ) from exc

    # Decimal(str(...)) accepts "NaN"/"Infinity"/"-0.1" without raising; a NaN would
    # make every threshold comparison False (silently mapping to clear) and an
    # out-of-range value is meaningless. Require each score finite and within 0..1.
    for s in scores:
        if not s.is_finite() or s < Decimal("0") or s > Decimal("1"):
            raise ScreeningProviderError(
                f"OpenSanctions returned a non-finite or out-of-range score: {s}"
            )
    top_score = max(scores) if scores else Decimal("0")

    dataset_version = data.get("responses", {}).get(_QUERY_ID, {}).get("dataset_version")
    return MatchResult(
        top_score=top_score,
        match_count=len(results),
        matches=results,
        dataset_version=dataset_version,
        algorithm=_ALGORITHM,
    )
