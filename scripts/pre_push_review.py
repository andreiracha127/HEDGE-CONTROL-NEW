"""CLI entrypoint for the pre-push review hook.

Invoked by ``.githooks/pre-push`` with changed paths from the pushed
range (via ``--changed-paths`` or stdin). Dispatch markdown files can be
passed via ``--dispatch-paths`` as optional canonical context. Calls the
Anthropic API, writes a JSON cache artifact, and decides exit code:

* P1 finding(s): exit 1 (block the push)
* P2 / P3 only or none: exit 0 (warn / continue)

Bypass with ``git push --no-verify`` (consciously opt-out).
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

# Windows console default cp1252 cannot encode characters Sonnet routinely
# emits in finding text (em-dash, arrows, smart quotes). Force UTF-8 with
# replacement-on-error before any print so the hook never crashes mid-report.
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[attr-defined]
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[attr-defined]

from anthropic import APIError as _AnthropicAPIError

from dispatch_review.cache import write_cache_artifact, write_parse_error_artifact
from dispatch_review.client import ReviewReportParseError, call_review
from dispatch_review.prompt_builder import (
    build_cached_system_blocks,
    build_user_payload,
)
from dispatch_review.schema import Finding, ReviewReport

_DEFAULT_MODEL = "claude-sonnet-4-6"


def _load_repo_dotenv(repo_root: Path) -> None:
    """Best-effort load of repo-root .env so ANTHROPIC_API_KEY is available.

    Avoids hard-depending on python-dotenv to keep scripts/ deps minimal.
    Only sets keys that are not already in os.environ.
    """
    env_path = repo_root / ".env"
    if not env_path.is_file():
        return
    try:
        for raw_line in env_path.read_text(encoding="utf-8").splitlines():
            line = raw_line.strip()
            if not line or line.startswith("#"):
                continue
            if "=" not in line:
                continue
            key, _, value = line.partition("=")
            key = key.strip()
            if not key or key in os.environ:
                continue
            value = value.strip().strip('"').strip("'")
            os.environ[key] = value
    except OSError:
        pass


def _read_paths_from_stdin() -> list[str]:
    if sys.stdin.isatty():
        return []
    return [line.strip() for line in sys.stdin if line.strip()]


def _normalize_changed_path(raw: str, repo_root: Path) -> str | None:
    raw = raw.strip()
    if not raw:
        return None
    candidate = Path(raw)
    if candidate.is_absolute():
        try:
            return candidate.resolve().relative_to(repo_root).as_posix()
        except ValueError:
            return candidate.as_posix()
    return candidate.as_posix()


def _is_dispatch_path(path: str) -> bool:
    normalized = path.replace("\\", "/")
    return normalized.startswith("docs/") and normalized.endswith("-dispatch.md")


def _resolve_existing_dispatch_paths(raw_paths: list[str], repo_root: Path) -> list[Path]:
    dispatch_paths: list[Path] = []
    for raw in raw_paths:
        candidate = Path(raw)
        if not candidate.is_absolute():
            candidate = (repo_root / candidate).resolve()
        if candidate.is_file():
            dispatch_paths.append(candidate)
    return dispatch_paths


def _parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="pre_push_review",
        description="Pre-push LLM review of changed files (Sonnet 4.6 first sieve before Codex).",
    )
    parser.add_argument(
        "--changed-paths",
        nargs="*",
        default=None,
        help="Explicit list of changed paths in the pushed range. If omitted, paths are read from stdin.",
    )
    parser.add_argument(
        "--dispatch-paths",
        nargs="*",
        default=None,
        help=(
            "Optional list of dispatch markdown paths to include as canonical context. "
            "If omitted, dispatch paths are derived from changed paths."
        ),
    )
    parser.add_argument("--branch", default="unknown")
    parser.add_argument("--head-sha", default="unknown")
    parser.add_argument("--remote-name", default="origin")
    parser.add_argument(
        "--model",
        default=_DEFAULT_MODEL,
        help=f"Anthropic model identifier. Default: {_DEFAULT_MODEL}",
    )
    parser.add_argument(
        "--repo-root",
        default=None,
        help="Repository root. Defaults to the parent of this script's directory.",
    )
    return parser.parse_args(argv)


def _print_findings(findings: list[Finding], level: str) -> None:
    for finding in findings:
        print(f"\n[{level}] {finding.rule}  ({finding.section})")
        print(f"  snippet : {finding.snippet}")
        print(f"  why     : {finding.why}")
        print(f"  fix     : {finding.fix_suggestion}")


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(list(argv) if argv is not None else sys.argv[1:])

    if args.repo_root:
        repo_root = Path(args.repo_root).resolve()
    else:
        repo_root = Path(__file__).resolve().parent.parent

    _load_repo_dotenv(repo_root)

    if args.changed_paths is not None:
        raw_changed_paths = args.changed_paths
    elif args.dispatch_paths is not None:
        # Backward-compatible direct invocation: old callers only supplied
        # dispatch paths, which are also changed paths for review purposes.
        raw_changed_paths = args.dispatch_paths
    else:
        raw_changed_paths = _read_paths_from_stdin()

    changed_paths = [
        normalized
        for raw in raw_changed_paths
        if (normalized := _normalize_changed_path(raw, repo_root)) is not None
    ]

    if not changed_paths:
        print("[pre-push-review] no changed files in push range -skipping")
        return 0

    raw_dispatch_paths = (
        args.dispatch_paths
        if args.dispatch_paths is not None
        else [path for path in changed_paths if _is_dispatch_path(path)]
    )
    dispatch_paths = _resolve_existing_dispatch_paths(raw_dispatch_paths, repo_root)

    print(
        f"[pre-push-review] reviewing {len(changed_paths)} changed file(s) "
        f"with {len(dispatch_paths)} dispatch context file(s) "
        f"on branch {args.branch} @ {args.head_sha[:12]}..."
    )

    cached_system = build_cached_system_blocks(repo_root)
    user_payload = build_user_payload(
        dispatch_paths=dispatch_paths,
        changed_paths=changed_paths,
        repo_root=repo_root,
        branch=args.branch,
        head_sha=args.head_sha,
    )

    try:
        report, tool_call_log = call_review(
            model=args.model,
            cached_system_blocks=cached_system,
            user_payload=user_payload,
            repo_root=repo_root,
        )
    except ReviewReportParseError as exc:
        artifact_path = write_parse_error_artifact(
            repo_root=repo_root,
            branch=args.branch,
            head_sha=args.head_sha,
            error_type=type(exc).__name__,
            error_message=str(exc),
            raw_report_input=exc.raw_report_input,
            tool_calls=exc.tool_calls,
        )
        print(
            f"[pre-push-review] review report parse failed: {exc}",
            file=sys.stderr,
        )
        print(
            f"[pre-push-review] artifact written: {artifact_path.relative_to(repo_root)}",
            file=sys.stderr,
        )
        return 1
    except (RuntimeError, _AnthropicAPIError) as exc:
        print(
            f"[pre-push-review] API call failed: {type(exc).__name__}: {exc}",
            file=sys.stderr,
        )
        return 1

    artifact_path = write_cache_artifact(
        report,
        repo_root=repo_root,
        branch=args.branch,
        head_sha=args.head_sha,
        tool_calls=tool_call_log,
    )
    print(f"[pre-push-review] artifact written: {artifact_path.relative_to(repo_root)}")
    print(f"[pre-push-review] summary: {report.summary}")

    if report.p1_blocking:
        _print_findings(report.p1_blocking, level="P1 BLOCKING")
        print(
            f"\n[pre-push-review] {len(report.p1_blocking)} P1 finding(s) -push blocked. "
            "Use `git push --no-verify` to override (not recommended)."
        )
        return 1
    if report.p2_warn:
        _print_findings(report.p2_warn, level="P2 WARNING")
    if report.p3_info:
        _print_findings(report.p3_info, level="P3 INFO")

    print(
        f"\n[pre-push-review] no P1 findings. "
        f"P2={len(report.p2_warn)}, P3={len(report.p3_info)} -push proceeds."
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
