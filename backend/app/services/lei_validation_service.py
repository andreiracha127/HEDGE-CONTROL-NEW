"""LEI validation: offline ISO 7064 MOD 97-10 checksum + online GLEIF lookup.

WARN-not-block: nothing here ever blocks or raises to the caller on a provider
failure — a GLEIF outage records lei_status=error. Mirrors the W2 client/service
split; audit emission lives in this service (not a route dependency).
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

from fastapi import HTTPException, status
from sqlalchemy.orm import Session

from app.models.commercial_partner import CommercialPartner, LeiStatus
from app.services.audit_trail_service import AuditTrailService
from app.services.commercial_partner_service import CommercialPartnerService
from app.services.gleif_client import GleifLookupError, fetch_lei_record

# GLEIF registration.status -> LeiStatus. Any status not listed maps to `lapsed`
# (not currently active) with the raw status surfaced as a warning.
_STATUS_MAP = {"ISSUED": LeiStatus.issued, "LAPSED": LeiStatus.lapsed}


def lei_checksum_ok(lei: str) -> bool:
    """ISO 7064 MOD 97-10: 20 alphanumerics, A-Z->10..35, int(...) % 97 == 1."""
    lei = lei.upper()
    if len(lei) != 20 or not lei.isascii() or not lei.isalnum():
        return False
    try:
        digits = "".join(str(int(c, 36)) for c in lei)
    except ValueError:
        return False
    return int(digits) % 97 == 1


def _names_diverge(legal_name: str | None, partner_name: str | None) -> bool:
    a = (legal_name or "").strip().casefold()
    b = (partner_name or "").strip().casefold()
    if not a or not b:
        return False
    return a not in b and b not in a


def validate_lei(
    session: Session,
    commercial_partner_id,
    *,
    actor_sub: str,
    commit: bool = True,
) -> tuple[CommercialPartner, list[str]]:
    cp = CommercialPartnerService.get_by_id(session, commercial_partner_id)
    if cp is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Commercial partner not found"
        )
    previous_status = cp.lei_status
    warnings: list[str] = []
    now = datetime.now(UTC)

    if not cp.lei or not cp.lei.strip():
        cp.lei_status = LeiStatus.not_provided
        cp.lei_legal_name = None
        cp.lei_checked_at = now
    elif not lei_checksum_ok(cp.lei):
        cp.lei_status = LeiStatus.invalid
        cp.lei_legal_name = None
        cp.lei_checked_at = now
        warnings.append("LEI failed the ISO 17442 checksum")
    else:
        try:
            record = fetch_lei_record(cp.lei)
        except GleifLookupError as exc:
            cp.lei_status = LeiStatus.error
            cp.lei_checked_at = now
            warnings.append(f"GLEIF lookup failed: {exc}")
        else:
            if record is None:
                cp.lei_status = LeiStatus.invalid
                cp.lei_legal_name = None
                cp.lei_checked_at = now
                warnings.append("LEI not found in GLEIF registry")
            else:
                cp.lei_status = _STATUS_MAP.get(record.registration_status, LeiStatus.lapsed)
                if record.registration_status not in _STATUS_MAP:
                    warnings.append(f"GLEIF registration status: {record.registration_status}")
                cp.lei_legal_name = record.legal_name
                cp.lei_checked_at = now
                if _names_diverge(record.legal_name, cp.name):
                    warnings.append(
                        f"LEI legal name '{record.legal_name}' differs from "
                        f"partner name '{cp.name}'"
                    )

    AuditTrailService.record(
        session,
        event_id=uuid.uuid4(),
        entity_type="commercial_partner",
        entity_id=cp.id,
        event_type="commercial_partner_lei_validated",
        payload_raw="",
        payload_obj={
            "commercial_partner_id": str(cp.id),
            "lei": cp.lei,
            "previous_status": previous_status.value,
            "new_status": cp.lei_status.value,
            "lei_legal_name": cp.lei_legal_name,
            "actor_sub": actor_sub,
        },
        commit=False,
    )
    session.flush()
    if commit:
        session.commit()
        session.refresh(cp)
    return cp, warnings
