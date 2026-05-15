from __future__ import annotations

import argparse
import os
import sys

CURRENT_DIR = os.path.dirname(__file__)
BACKEND_DIR = os.path.abspath(os.path.join(CURRENT_DIR, ".."))
sys.path.insert(0, BACKEND_DIR)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Mint a short-lived internal service-account JWT."
    )
    parser.add_argument("--identity", required=True)
    args = parser.parse_args()

    from app.core.auth import mint_service_token

    print(mint_service_token(args.identity))


if __name__ == "__main__":
    main()
