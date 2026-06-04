from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel


class LeiValidationRead(BaseModel):
    lei: str | None
    lei_status: str
    lei_legal_name: str | None
    lei_checked_at: datetime | None
    warnings: list[str]
