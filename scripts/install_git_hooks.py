"""Bootstrap script: configure git to use the versioned ``.githooks/`` directory.

Run once per fresh clone:

    python scripts/install_git_hooks.py

Idempotent — re-running has no effect beyond restating the config.
"""

from __future__ import annotations

import pathlib
import subprocess
import sys


def main() -> int:
    repo_root = pathlib.Path(__file__).resolve().parent.parent
    hooks_dir = repo_root / ".githooks"
    if not hooks_dir.is_dir():
        print(f"ERROR: {hooks_dir} not found", file=sys.stderr)
        return 1

    try:
        subprocess.check_call(
            ["git", "config", "core.hooksPath", ".githooks"], cwd=repo_root
        )
    except subprocess.CalledProcessError as exc:
        print(f"ERROR: git config failed: {exc}", file=sys.stderr)
        return exc.returncode or 1

    pre_push = hooks_dir / "pre-push"
    if pre_push.is_file():
        try:
            mode = pre_push.stat().st_mode
            pre_push.chmod(mode | 0o111)
        except (OSError, NotImplementedError):
            pass

    print("[install_git_hooks] core.hooksPath set to .githooks")
    print("[install_git_hooks] pre-push hook is now active")
    return 0


if __name__ == "__main__":
    sys.exit(main())
