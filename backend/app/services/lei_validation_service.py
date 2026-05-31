"""LEI validation: offline ISO 7064 MOD 97-10 checksum + online GLEIF lookup.

WARN-not-block: nothing here ever blocks or raises to the caller on a provider
failure — a GLEIF outage records lei_status=error. Mirrors the W2 client/service
split; audit emission lives in this service (not a route dependency).
"""

from __future__ import annotations

from app.models.commercial_partner import LeiStatus

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
