from __future__ import annotations

import argparse

from app.core.auth import mint_service_token


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Mint a short-lived internal service-account JWT."
    )
    parser.add_argument("--identity", required=True)
    args = parser.parse_args()
    print(mint_service_token(args.identity))


if __name__ == "__main__":
    main()
