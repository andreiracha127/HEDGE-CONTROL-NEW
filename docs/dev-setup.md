# Dev setup

## Pre-push dispatch review hook

This repo runs an LLM-based first-sieve review on dispatch markdown files
(`docs/**/*-dispatch.md`) before they reach the Codex Connector. The hook
catches mechanically-detectable institutional self-consistency violations
locally so the Codex round count per dispatch stays small.

Codex Connector remains the final-line authority on review correctness;
the hook only changes what arrives at Codex's input.

### Install (one-time per fresh clone)

```
python scripts/install_git_hooks.py
```

This sets `git config core.hooksPath .githooks` so the versioned hook
in `.githooks/pre-push` becomes active.

### Configuration

Set `ANTHROPIC_API_KEY` in your environment. The hook reads `.env` at
the repo root via a best-effort loader (no python-dotenv dependency)
and does not log or persist the key in any cache artifact.

### When the hook fires

On every `git push`, the hook checks whether any
`docs/**/*-dispatch.md` file is in the push range. If yes, it invokes
`scripts/pre_push_review.py` which:

1. Builds a cached system prompt from `docs/governance.md`,
   `docs/audit-protocol/dispatch-review-rules.md`, and a fixed persona
   preamble.
2. Inlines the dispatch markdown plus verbatim excerpts of every
   `backend/...` or `docs/...` file path cited in the dispatch (capped
   at 200 lines per file).
3. Calls Anthropic Claude Sonnet 4.6 with `tool_choice` forcing the
   `report_findings` tool, returning a structured `ReviewReport{p1,p2,p3,summary}`.
4. Writes the report JSON to `.cache/dispatch_review/<branch>-<sha>.json`.
5. Exits 1 (block push) if any P1 finding; exits 0 otherwise.

Regular code-only pushes skip the hook in ~100 ms (no LLM call).

### Cost

~R$ 1.50–4.00 per push that triggers the review (Sonnet 4.6 with
prompt caching active). Cache TTL is 5 minutes — consecutive pushes
within the window pay only the variable user payload.

### Bypass

```
git push --no-verify
```

This bypasses the hook for one push. Per
`feedback_dispatch_self_consistency`, bypassing without a deliberate
orchestrator decision is institutional debt. Codex will still catch
the violations the hook would have caught; bypassing only delays them.

### Updating the rules

The rule sheet at `docs/audit-protocol/dispatch-review-rules.md` is
the canonical in-repo rule set. When a new sub-rule is absorbed from
a Codex catch (orchestrator memory `feedback_dispatch_self_consistency`),
append it to this file in the same commit.

## Fresh-Postgres bootstrap discipline

When adding a new migration that introduces a Postgres named ENUM, ensure: (a) if the ENUM is referenced ONLY via `op.create_table(...)`, no explicit `.create()` is needed (SQLAlchemy auto-creates via the table-create cascade); (b) if the ENUM is referenced via `op.add_column(...)` or `op.batch_alter_table(...).add_column(...)`, explicitly call `<enum_name>.create(op.get_bind(), checkfirst=True)` before the column-add (auto-create only fires on `CREATE TABLE`, not on `ALTER TABLE ADD COLUMN`); (c) NEVER mix BOTH an explicit `.create()` AND a subsequent `op.create_table(...)` referencing the same ENUM in the same migration without `create_type=False` on the column metadata (the table-create cascade does NOT respect `checkfirst` and will raise `DuplicateObject`); (d) when issuing an `UPDATE` that sets an ENUM column, **dialect-branch the cast expression**: on Postgres use `CAST('<value>' AS <enum_name>)` (the `SET` is strict at plan-time without an explicit cast); on SQLite use a plain text literal (the `<enum_name>` is unknown to SQLite, which applies NUMERIC type affinity to unknown CAST type names per https://www.sqlite.org/lang_expr.html#castexpr and would coerce `'long'` to `0`, silently corrupting any backfill that touched populated SQLite data). Reuse the `bind.dialect.name == "postgresql"` idiom (the pattern is canonical across the chain — see `026_classification_invariant.py::upgrade()` for the reference implementation). The `::<enum_name>` Postgres shorthand is forbidden in either branch (breaks SQLite parsing). The CI job `alembic-fresh-postgres` enforces (a)–(d) automatically against fresh Postgres; SQLite enforcement happens via the existing `backend/tests/test_alembic_chain.py` + autouse-fixture-empty-tables guarantee.
