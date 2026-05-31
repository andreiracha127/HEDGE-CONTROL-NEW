"""Thin, mockable boundary to the public GLEIF LEI-records API.

Single external-I/O point of the W4 LEI subsystem. Fetches a LEI record and
parses the fields needed for validation. A 404 (LEI not registered) is a real
answer (returns None); any transport/parse failure raises GleifLookupError so
the service can record an `error` lei_status. The client never fabricates a
valid record.
"""

from __future__ import annotations

from dataclasses import dataclass

import httpx

from app.core.config import get_settings

_TIMEOUT_SECONDS = 30.0


class GleifLookupError(Exception):
    """Raised on any GLEIF transport / HTTP (non-404) / parse failure."""


@dataclass(frozen=True)
class GleifRecord:
    registration_status: str
    legal_name: str | None
    legal_name_language: str | None
    entity_status: str | None


def _base_url() -> str:
    return get_settings().gleif_api_base_url


def fetch_lei_record(lei: str) -> GleifRecord | None:
    url = f"{_base_url()}/lei-records/{lei}"
    try:
        response = httpx.get(url, timeout=_TIMEOUT_SECONDS)
        if response.status_code == 404:
            return None
        response.raise_for_status()
        data = response.json()
    except httpx.HTTPError as exc:
        raise GleifLookupError(f"GLEIF request failed: {exc}") from exc
    except ValueError as exc:  # JSON decode
        raise GleifLookupError(f"GLEIF returned unparseable body: {exc}") from exc

    try:
        attributes = data["data"]["attributes"]
        registration_status = attributes["registration"]["status"]
        entity = attributes.get("entity") or {}
        legal_name_obj = entity.get("legalName") or {}
        legal_name = legal_name_obj.get("name")
        legal_name_language = legal_name_obj.get("language")
        entity_status = entity.get("status")
    except (KeyError, TypeError) as exc:
        raise GleifLookupError(f"GLEIF response missing expected fields: {exc}") from exc

    if not registration_status:
        raise GleifLookupError("GLEIF response missing registration status")

    return GleifRecord(
        registration_status=registration_status,
        legal_name=legal_name,
        legal_name_language=legal_name_language,
        entity_status=entity_status,
    )
