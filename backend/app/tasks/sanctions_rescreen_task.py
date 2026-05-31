"""Scheduled daily sanctions re-screen across both domains."""

from __future__ import annotations

from app.core.config import get_settings
from app.core.database import SessionLocal
from app.core.logging import get_logger
from app.models.commercial_partner import CommercialPartner
from app.models.counterparty import Counterparty
from app.models.sanctions import SanctionsPartnerType
from app.services.sanctions_screening_service import screen

logger = get_logger()

_ACTOR = "service:sanctions_screening"


def run_sanctions_rescreen_daily() -> dict:
    """Re-screen all active, non-deleted partners across both domains.

    Per-entity failures are isolated: the screening service records the
    status=error evidence on its own session and raises; this loop logs and
    continues so one provider hiccup never aborts the whole run.
    """
    if not get_settings().sanctions_screening_enabled:
        logger.info("sanctions_rescreen_skipped_disabled")
        return {"screened": 0, "errors": 0, "skipped": True}
    screened = 0
    errors = 0
    with SessionLocal() as session:
        commercial_ids = [
            row.id
            for row in session.query(CommercialPartner.id.label("id"))
            .filter(CommercialPartner.is_deleted == False, CommercialPartner.is_active == True)  # noqa: E712
            .all()
        ]
        hedge_ids = [
            row.id
            for row in session.query(Counterparty.id.label("id"))
            .filter(Counterparty.is_deleted == False, Counterparty.is_active == True)  # noqa: E712
            .all()
        ]

    targets = [(SanctionsPartnerType.commercial, pid) for pid in commercial_ids] + [
        (SanctionsPartnerType.hedge, cid) for cid in hedge_ids
    ]
    for partner_type, partner_id in targets:
        work = SessionLocal()
        try:
            screen(work, partner_type, partner_id, actor_sub=_ACTOR, commit=True)
            screened += 1
        except Exception as exc:  # provider error already recorded on its own session
            work.rollback()
            errors += 1
            logger.warning(
                "sanctions_rescreen_entity_failed",
                partner_type=partner_type.value,
                partner_id=str(partner_id),
                error=str(exc),
            )
        finally:
            work.close()

    logger.info("sanctions_rescreen_complete", screened=screened, errors=errors)
    return {"screened": screened, "errors": errors}
