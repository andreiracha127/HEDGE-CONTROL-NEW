from __future__ import annotations

from app.core.database import SessionLocal
from app.core.logging import get_logger
from app.services.workflow_approval_service import sweep_expired

logger = get_logger()


def workflow_approval_sweeper() -> None:
    session = SessionLocal()
    try:
        expired = sweep_expired(session)
        session.commit()
        if expired:
            logger.info("workflow_approval_sweeper_expired", count=len(expired))
    except Exception:
        session.rollback()
        logger.exception("workflow_approval_sweeper_failed")
        raise
    finally:
        session.close()

