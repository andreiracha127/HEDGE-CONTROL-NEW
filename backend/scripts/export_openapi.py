from __future__ import annotations

import json
import os
import sys

CURRENT_DIR = os.path.dirname(__file__)
BACKEND_DIR = os.path.abspath(os.path.join(CURRENT_DIR, ".."))
sys.path.insert(0, BACKEND_DIR)

# Mark this process as build-time tooling so the auth/audit-signing
# fail-closed gates (J-A1-02, J-A5-06) do not refuse to boot. APP_ENV is
# the canonical environment marker; without this default, the script
# inherits the production-default app_env and the JWT/audit-signing
# validators reject boot. Using setdefault preserves any caller-set
# override (e.g. a real APP_ENV in CI).
os.environ.setdefault("APP_ENV", "test")

from app.main import app  # noqa: E402


def main() -> None:
    spec = app.openapi()
    json.dump(spec, sys.stdout, indent=2, sort_keys=True)


if __name__ == "__main__":
    main()