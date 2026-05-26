# OPS — Postgres Fresh-Bootstrap Migration Fix — Implementation Dispatch

Cycle: Operational hardening (post-HB-3, pre-HB-4)
Wave: OPS-PG-FRESH-1 (single PR)
Constitutional anchor: `docs/systemconstitucion.md` (DDL must be portable across the SQLite test dialect AND the Postgres production dialect — the constitution treats reconstructability as a first-class invariant; a migration chain that cannot bootstrap a fresh production-shaped database from `base` is reconstructability-broken)
Governance anchor: `docs/governance.md` MARKET-DATA GOVERNANCE appendix is not relevant; the relevant constraint is the implicit "fresh-Postgres bootstrap MUST work" invariant that the SQLite-only test matrix has been hiding for the entire A1–HB-3 series
Discovery context: Local dev session on 2026-05-26 ran `cd backend && alembic upgrade head` against a fresh `hedge-control-new-db-1` Postgres 16 container and the chain halted at four independent migrations with `UndefinedObject`, `DatatypeMismatch`, `DatatypeMismatch`, and `DuplicateObject` Postgres errors respectively. SQLite tests pass against all four because SQLite has no named ENUMs (ENUM columns become VARCHAR + CHECK on SQLite).
Prior precedent: PR #33 (alembic chain hygiene merge revision) and dispatch-review rule 16 (DDL portability — Postgres-only types/CHECKs without `with_variant` fallback). This dispatch is the runtime analog of rule 16 applied to ENUM lifecycle inside migrations.
Findings closed by this wave: institutional debt class C-OPS-PG-FRESH (the entire A1–HB-3 chain has been SQLite-validated only; fresh-Postgres bootstrap was untested in CI and broken in four places).
Status: READY

---

## §1 Scope

This dispatch prescribes the implementation contract for a single executor PR that patches four migrations so the full chain `base → 047_finance_pipeline_hb3_hardening` applies cleanly against a fresh Postgres 16 database, AND adds one CI job that gates against re-regression. The executor PR lands: (a) a `pricing_type.create(op.get_bind(), checkfirst=True)` line before the `op.add_column("orders", ...)` call in `backend/alembic/versions/88c13cd6dd8e_fase1_core_domain.py` (the named ENUM is referenced only via `ALTER TABLE ADD COLUMN`, which does NOT auto-create the type in Postgres); (b) explicit `CAST('long' AS hedge_classification)` and `CAST('short' AS hedge_classification)` inside the backfill `UPDATE` statement in `backend/alembic/versions/026_classification_invariant.py` (Postgres rejects text literals against an ENUM column at plan-time, even when the table is empty); (c) switch of the `sa.column("mutation_type", sa.String)` and `sa.column("threshold_dimension", sa.String)` declarations inside the `op.bulk_insert(sa.table("approval_policy", ...))` call in `backend/alembic/versions/046_workflow_approval_gate.py` to use the actual ENUM types `mutation_type_enum` and `threshold_dimension_enum` declared at the top of the same migration (otherwise alembic binds the parameters as `$1::VARCHAR` and Postgres rejects against the ENUM-typed columns); (d) removal of the redundant `risk_flag_type_enum.create(bind, checkfirst=True)` and `risk_flag_severity_enum.create(bind, checkfirst=True)` lines in `backend/alembic/versions/047_finance_pipeline_hb3_hardening.py` (the subsequent `op.create_table("finance_pipeline_risk_flags", ...)` auto-creates those types via the column metadata WITHOUT `checkfirst`, producing `DuplicateObject` after the explicit pre-create); (e) one new GitHub-Actions job `alembic-fresh-postgres` in `.github/workflows/ci.yml` that brings up the `db` service from `docker-compose.yml`, runs `cd backend && alembic upgrade head` against it, and fails the build on non-zero exit; and (f) a one-paragraph addition to `CLAUDE.md` documenting that the migration chain is now CI-validated against both SQLite and Postgres.

The four migration patches MUST land in the same PR — splitting them would leave the chain broken at intermediate revisions, defeating the "fresh-Postgres applies cleanly" invariant. The CI job MUST land in the same PR — adding it after the patches risks merge gaps; adding it before creates an immediate red CI on `main`.

This dispatch itself is documentation-only — no code change lands via the PR shipping this file. The executor PR opens against the post-dispatch-merge HEAD and is the next task in the orchestrator's operational-hardening sequence.

## §2 Boundary

This PR does NOT:

- **Modify alembic chain ancestry.** No new revision file, no edited `down_revision`, no new merge revision. The chain test `backend/tests/test_alembic_chain.py` MUST continue to pass with `047_finance_pipeline_hb3_hardening` as the single head. The four patched migrations keep their existing `revision`/`down_revision` tuples verbatim.
- **Change ENUM membership.** No new ENUM members, no removed members, no renamed members. The patches change ENUM **lifecycle** (when the type is created relative to when columns reference it), not ENUM **content**.
- **Backfill or migrate any data.** Migration `026` already runs an idempotent backfill that the patch preserves intact — the patch ONLY adds `CAST(... AS hedge_classification)` around two literal strings inside the existing `CASE` expression. Migration `88c13cd6dd8e` adds a `nullable=True` column; the patch does NOT change that nullability. Migration `046`'s seed data (`deal_create`, `deal_award`, `hedge_contract_settle` rows) is unchanged — the patch ONLY swaps the type metadata on the `sa.column(...)` declarations inside the `sa.table(...)` wrapper so alembic emits the right bind cast. Migration `047` keeps its `create_table` + `bulk_insert` + `add_column` calls unchanged.
- **Touch any application code.** No model, service, route, schema, or test outside `backend/tests/test_alembic_*` is edited. The patches are scoped strictly to four migration files + one CI yaml file + one CLAUDE.md paragraph + one `docs/dev-setup.md` paragraph.
- **Re-run downstream migrations to "verify" the patches retroactively.** Operators with existing Postgres production/staging deployments have already run the unpatched migrations past these revisions; the patches use `checkfirst=True` (88c13cd6dd8e) and `CAST` (026 — a no-op rewrite on empty tables AND on populated tables since the rewrite is plan-stage Postgres rejecting an untyped literal). Migration `046`'s patch is a parameter-binding metadata change that produces the same network-protocol INSERT statement once the values are correctly cast — operators who somehow got past `046` (which they could not, given the unconditional `bulk_insert` shape) would observe no row difference. Migration `047`'s patch removes redundant explicit creates whose outputs were ALREADY satisfied by the subsequent `create_table` auto-create — operators who applied `047` against the unpatched code only "succeeded" because Postgres failed AFTER the type already existed (i.e. they didn't actually succeed; the chain rolled back). **There is no live database that has `046` or `047` applied where these patches would observe drift**, because every fresh-Postgres apply against the unpatched code rolled back. Existing Postgres deployments that applied earlier migrations (`88c13cd6dd8e` through `045`) are NOT affected by the `046`/`047` patches since those would only run on a forward-upgrade.
- **Add the migration chain to the local `pytest` invocation.** The chain integration test belongs to CI (where docker is available), not to the SQLite-in-memory unit suite. The executor MUST NOT add a `pytest_postgresql` fixture, a `docker-py` invocation, or any Postgres-requiring fixture to the local `backend/tests/conftest.py`. The CI job is the regression gate.
- **Bump alembic, SQLAlchemy, or psycopg.** No dependency changes. The patches are pure-Python edits using primitives that all three libraries have shipped since the relevant minor versions (alembic 1.x, SQLAlchemy 2.0, psycopg 3.x — all already in `backend/requirements.txt`).
- **Document the institutional-debt class C-OPS-PG-FRESH as resolved.** Three migrations have been patched; rule 16 (DDL portability) catches CHECK constraints and column types but not ENUM lifecycle, so a future SQLite-passing migration with an `ALTER TABLE ADD COLUMN <enum_type>` shape can still slip through. The CI job is the durable gate; a future enhancement to rule 16 (or a new rule 38 specifically covering ENUM-in-`add_column`) belongs to the dispatch-review-rules.md amendment cycle, NOT to this PR.

## §3 Pre-step (manual)

Empty for the code PR itself. The executor's branch opens against current `main` HEAD post-dispatch-merge and runs without infrastructure changes.

Two operational pre-conditions exist BUT they belong to the executor's local validation, not to the PR contents:

1. **Docker stack must be running locally for the executor's smoke validation.** Before pushing, the executor MUST run `docker compose up -d db` from the repo root (NOT from `backend/`; the docker-compose.yml is at root) and verify the container is `healthy` via `docker ps`. Then `cd backend && python -m alembic upgrade head` MUST complete with exit 0 and `python -m alembic current` MUST return `047_finance_pipeline_hb3_hardening (head)`. If either fails, the patches are incomplete or wrong — debug locally before pushing.

2. **The unpatched chain leaves a partial `alembic_version` row on failure.** SQLAlchemy/alembic wraps each migration in its own transaction; when `026` or `047` fails, all preceding migrations have already committed. The executor's local validation must either (a) drop and recreate the database between attempts (`docker compose down -v && docker compose up -d db`), OR (b) confirm the docker volume was empty before the first attempt. Skipping this leads to false-passes ("the chain ran cleanly" when in fact some revisions were already at head before the run).

## §4 Backend changes

The four migration patches are listed verbatim below. The executor copies them exactly; deviations are forbidden except as enumerated in §4.6.

### §4.1 Patch 1 — `backend/alembic/versions/88c13cd6dd8e_fase1_core_domain.py`

**Locus:** the `upgrade()` function, immediately before the `op.add_column("orders", sa.Column("pricing_type", pricing_type, nullable=True))` call (currently around line 112, just before the "2. orders — add Phase-1 columns" block's first `add_column`).

**Patch shape:**

```python
    # ------------------------------------------------------------------
    # 2. orders — add Phase-1 columns
    # ------------------------------------------------------------------
    # pricing_type is only referenced via ALTER TABLE ADD COLUMN below — SQLAlchemy's
    # auto-create only fires on CREATE TABLE, so create the enum explicitly first.
    pricing_type.create(op.get_bind(), checkfirst=True)
    op.add_column(
        "orders", sa.Column("counterparty_id", sa.UUID(as_uuid=True), nullable=True)
    )
    op.add_column("orders", sa.Column("pricing_type", pricing_type, nullable=True))
```

**Rationale (binding for §10 acceptance):** all OTHER ENUMs declared at the top of this migration (`counterparty_type`, `kyc_status`, `sanctions_status`, `risk_rating`, `exposure_*`, `hedge_*`, `deal_*`, `pipeline_*`) are first referenced inside `op.create_table(...)` calls. SQLAlchemy's `CreateTable` DDL visitor walks the column metadata and emits a `CREATE TYPE ... AS ENUM` for each named ENUM BEFORE the `CREATE TABLE`, with `checkfirst=True` driven by the table-create flow. `pricing_type` is the only ENUM that is first referenced via `op.add_column("orders", ...)`, which lowers to `ALTER TABLE orders ADD COLUMN pricing_type pricing_type` — and `ALTER TABLE ADD COLUMN` does NOT trigger the type-create cascade. Hence the explicit `.create(..., checkfirst=True)` immediately before.

The `checkfirst=True` keyword makes the call idempotent for any operator who somehow has the type pre-created (e.g. a manual hotfix before this PR landed). No operator should be in that state, but the keyword costs nothing and preserves the "patches are safe to apply to any DB state" property.

**`downgrade()` left untouched.** The existing downgrade already drops `pricing_type` via `pricing_type.drop(op.get_bind(), checkfirst=True)` at the end of the function (currently around line 487). The patch does NOT add a symmetric explicit drop in downgrade because the existing drop already handles it.

### §4.2 Patch 2 — `backend/alembic/versions/026_classification_invariant.py`

**Locus:** the `_backfill_inconsistent_classifications()` helper, inside the `sa.text(...)` block at the `SET classification = CASE ... END` portion (currently around lines 38–46).

**Patch shape:**

```python
    result = bind.execute(
        sa.text(
            """
            UPDATE hedge_contracts
            SET classification = CASE fixed_leg_side
                WHEN 'buy' THEN CAST('long' AS hedge_classification)
                WHEN 'sell' THEN CAST('short' AS hedge_classification)
            END
            WHERE (fixed_leg_side = 'buy' AND classification <> 'long')
               OR (fixed_leg_side = 'sell' AND classification <> 'short')
            """
        )
    )
```

**Rationale (binding for §10 acceptance):** Postgres rejects `SET <enum_col> = <text_literal>` at plan-time (the planner cannot infer the cast direction across a `CASE` whose result type derives from a union of branch types). The fix is to make the cast explicit on the branch literals. The `WHERE` clause comparisons (`classification <> 'long'`, `fixed_leg_side = 'buy'`) are NOT changed because Postgres applies implicit text-to-enum coercion in equality predicates (the column is the enum side, the literal is text; the planner promotes the literal). Only the `SET` is strict.

**Identifier scope note (institutional clarification):** the bare ENUM name `hedge_classification` inside the `sa.text(...)` raw SQL string is a **Postgres-resolved identifier**, not a Python identifier. Migration `026` does NOT import or declare `hedge_classification = sa.Enum(...)` at the Python level, and it does NOT need to: SQLAlchemy passes the SQL string through to psycopg, which sends it verbatim to Postgres, which looks up the type via the `pg_type` catalog. The type was created by an earlier migration (specifically the `CREATE TYPE hedge_classification AS ENUM (...)` emitted by SQLAlchemy's auto-create cascade when an earlier migration first referenced it inside an `op.create_table(...)` call referencing the `hedge_classification` named ENUM, around the early-Phase-A1 cycle) and persists across migration boundaries within the same database. The patch was validated end-to-end against a fresh Postgres 16 container at dispatch-authoring time: `alembic upgrade head` runs through `026` cleanly with the `CAST(... AS hedge_classification)` form, and `psql -d hedgecontrol -c "SELECT typname FROM pg_type WHERE typname = 'hedge_classification';"` returns the type at the moment `026` executes. The executor MUST NOT add `hedge_classification = sa.Enum(..., create_type=False)` at the top of `026` to "make the identifier explicit at the Python level" — that would create a fresh Python type instance whose only role would be to mislead a future reader into thinking the migration creates or owns the type. The cross-migration dependency on `hedge_classification` existing in `pg_type` is INTENTIONAL and is the same pattern every alembic chain uses for raw-SQL-against-named-types references (see also Postgres' `CREATE TYPE` persistence semantics: types live in the schema catalog independent of any migration's transactional boundary, except for the rare DROP TYPE case).

The SQLite test dialect ignores the `CAST(... AS hedge_classification)` because SQLite resolves the cast to the value itself (SQLite has no `hedge_classification` type; it stores ENUM values as text). The test suite continues to pass; this is the same `with_variant`-style safety that DDL rule 16 already prescribes for `JSONB`, `INET`, etc.

**Empty-table sanity check:** on a fresh DB, `hedge_contracts` has zero rows. Postgres still plans the UPDATE (planning happens before row scan), so the type mismatch is rejected regardless of row count. The patch fixes both the empty-table and populated-table paths.

**`downgrade()` left untouched.** The downgrade drops the CHECK constraint; it does NOT touch the backfill (backfill is inherently one-directional).

### §4.3 Patch 3 — `backend/alembic/versions/046_workflow_approval_gate.py`

**Locus:** the `upgrade()` function, inside the `op.bulk_insert(sa.table("approval_policy", ...))` call (currently lines 131–138). The `sa.table()` wrapper declares column types that alembic uses to bind INSERT parameters. The unpatched declarations use `sa.String` / `sa.JSON`, which Postgres binds as `$1::VARCHAR` / `$2::JSON` — and the real `approval_policy` table columns are typed `workflow_approval_mutation_type` (ENUM), `JSONB`, `JSONB`, `workflow_approval_threshold_dimension` (ENUM). Postgres rejects the VARCHAR-to-ENUM assignment at executemany time with `DatatypeMismatch`.

**Patch shape:**

```python
    op.bulk_insert(
        sa.table(
            "approval_policy",
            sa.column("mutation_type", mutation_type_enum),
            sa.column("required_approver_roles", _json_type()),
            sa.column("fallback_when_requester_is", _json_type()),
            sa.column("threshold_dimension", threshold_dimension_enum),
        ),
        [
            {
                "mutation_type": "deal_create",
                "required_approver_roles": ["risk_manager"],
                "fallback_when_requester_is": {},
                "threshold_dimension": "notional_usd",
            },
            {
                "mutation_type": "deal_award",
                "required_approver_roles": ["risk_manager"],
                "fallback_when_requester_is": {},
                "threshold_dimension": "notional_usd",
            },
            {
                "mutation_type": "hedge_contract_settle",
                "required_approver_roles": ["auditor"],
                "fallback_when_requester_is": {},
                "threshold_dimension": "settlement_amount_usd",
            },
        ],
    )
```

**Rationale (binding for §10 acceptance):** the `sa.table(...)` / `sa.column(...)` primitives in alembic are lightweight Column descriptors used ONLY for SQL composition — they do NOT trigger DDL, do NOT call the ENUM's `.create()`, and do NOT bind the column to any metadata. Passing the ENUM type instance through `sa.column("mutation_type", mutation_type_enum)` informs the executemany binding layer to emit `$1::workflow_approval_mutation_type` instead of `$1::VARCHAR`, so the INSERT statement is plannable against the real table column type.

The same logic applies to `_json_type()` — passing the variant-aware JSONB/JSON type makes the parameter bind as `JSONB` on Postgres and `JSON` on SQLite, matching the table's column type produced by `op.create_table("approval_policy", ..., sa.Column(..., _json_type(), ...))` earlier in the same migration. The `_json_type()` helper is **pre-existing** in `046` (currently defined at line 53 of the unpatched file as `def _json_type() -> sa.types.TypeEngine: return postgresql.JSONB(astext_type=sa.Text()).with_variant(sa.JSON(), "sqlite")`); the patch does NOT introduce a new helper, it only references the existing one from the `sa.column(...)` call site. Same applies to `mutation_type_enum` and `threshold_dimension_enum` (pre-existing module-level declarations at lines 19–24 and 34–38 respectively).

The row data dict literals are unchanged. `mutation_type` values (`"deal_create"`, `"deal_award"`, `"hedge_contract_settle"`) and `threshold_dimension` values (`"notional_usd"`, `"settlement_amount_usd"`) remain string literals — Postgres accepts string values bound through an ENUM-typed parameter as long as the value is a valid ENUM member. The cast direction is what matters; the literal shape is fine.

**SQLite compatibility:** on SQLite, the `mutation_type_enum`-bound parameter falls through to TEXT (SQLite's ENUM-to-TEXT degradation). The INSERT continues to work. The test suite's SQLite chain test is unaffected.

**`downgrade()` left untouched.** The downgrade drops the table; no bulk_insert reversal needed.

### §4.4 Patch 4 — `backend/alembic/versions/047_finance_pipeline_hb3_hardening.py`

**Locus:** the `upgrade()` function, the explicit ENUM `.create(...)` block at the start (currently lines 50–53).

**Patch shape:**

```python
def upgrade() -> None:
    bind = op.get_bind()
    # trigger_source_enum is needed for the ALTER TABLE ADD COLUMN below
    # (auto-create only fires on CREATE TABLE). The other two enums are only
    # referenced in create_table("finance_pipeline_risk_flags") and would
    # double-create here without checkfirst.
    trigger_source_enum.create(bind, checkfirst=True)
```

**Rationale (binding for §10 acceptance):** the unpatched migration pre-creates all three ENUMs (`trigger_source_enum`, `risk_flag_type_enum`, `risk_flag_severity_enum`) explicitly with `checkfirst=True`. Then `op.batch_alter_table("finance_pipeline_runs")` adds a `triggered_by` column typed `trigger_source_enum` (this needs the explicit pre-create because `ADD COLUMN` does not auto-create). Then `op.create_table("finance_pipeline_risk_flags", ...)` references `risk_flag_type_enum` and `risk_flag_severity_enum` — and the `CreateTable` DDL visitor emits `CREATE TYPE` for each WITHOUT `checkfirst`, producing `DuplicateObject` because the explicit pre-creates already ran.

The patch keeps the explicit pre-create for `trigger_source_enum` (needed for the `ADD COLUMN` path) and removes the explicit pre-creates for the other two (their auto-create via `create_table` is sufficient on fresh DBs and is the canonical pattern). This matches the same pattern in patch 1: explicit pre-create ONLY for ENUMs first referenced by `add_column`/`alter_column`; rely on `create_table` auto-create for ENUMs first referenced in `create_table`.

**Downgrade left untouched.** The downgrade drops all three ENUMs symmetrically with `checkfirst=True`. The patch does NOT change downgrade because downgrade is the reverse direction and the asymmetry is intentional.

### §4.5 Patch 5 — `.github/workflows/ci.yml`

**Locus:** a new top-level job under `jobs:`, placed AFTER the existing `backend-test` job (placement within the file is non-binding as long as the job key is exactly `alembic-fresh-postgres`; the existing file groups jobs by domain — frontend, backend, e2e — so backend-adjacent placement is the natural fit).

**Patch shape:**

```yaml
  alembic-fresh-postgres:
    name: alembic upgrade head against fresh Postgres
    runs-on: ubuntu-latest
    services:
      postgres:
        image: postgres:16
        env:
          POSTGRES_USER: hc
          POSTGRES_PASSWORD: hc
          POSTGRES_DB: hedgecontrol
        ports:
          - 5433:5432
        options: >-
          --health-cmd "pg_isready -U hc -d hedgecontrol"
          --health-interval 5s
          --health-timeout 5s
          --health-retries 10
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: "3.12"
          cache: pip
          cache-dependency-path: backend/requirements.txt
      - name: Install backend deps
        working-directory: backend
        run: |
          python -m pip install --upgrade pip
          pip install -r requirements.txt
      - name: Apply migrations to fresh Postgres
        working-directory: backend
        env:
          DATABASE_URL: postgresql+psycopg://hc:hc@localhost:5433/hedgecontrol
        run: |
          python -m alembic upgrade head
      - name: Verify single head reached
        working-directory: backend
        env:
          DATABASE_URL: postgresql+psycopg://hc:hc@localhost:5433/hedgecontrol
        run: |
          python -m alembic current | grep -F "047_finance_pipeline_hb3_hardening (head)"
```

**Rationale (binding for §10 acceptance):** the existing CI matrix (`backend-test` job) runs against SQLite-in-memory. The institutional debt class C-OPS-PG-FRESH (chain works on SQLite but not on fresh Postgres) was invisible because no CI job exercises the fresh-Postgres bootstrap path. This job is the durable gate: any future migration that adds an ENUM via `add_column` without an explicit `.create(checkfirst=True)`, or that uses untyped literals against ENUM columns, will fail this job on PR and never reach `main`.

The job uses Postgres 16 (matching `docker-compose.yml`'s `image: postgres:16`). The `DATABASE_URL` env var uses `postgresql+psycopg://` (matching the production driver, not `postgresql://` which would default to `psycopg2`). The `5433` host port matches the docker-compose convention for local dev to avoid conflict with a host-resident Postgres.

The `grep -F "047_finance_pipeline_hb3_hardening (head)"` assertion is binding: the executor MUST keep the literal head revision string current. When a future migration lands (e.g. HB-4 introduces `048_audit_daily_report`), THAT PR's executor MUST update both the head revision in this grep AND the chain test in `backend/tests/test_alembic_chain.py` — those updates land in the migration-introducing PR, not retroactively. This is the standard chain-test-update pattern already in place for the SQLite chain.

### §4.6 Allowed adjustments

The executor MUST adjust the following IF the actual codebase state at branch-open time differs from what the dispatch assumed:

1. **Line numbers in the locus citations.** Auto-formatting or comment changes between dispatch authorship (2026-05-26) and executor branch open may shift the cited line numbers (e.g. "around line 112"). The executor uses the surrounding code context (the `# 2. orders — add Phase-1 columns` comment block, the `_backfill_inconsistent_classifications` function name, the `def upgrade()` function in `047_*`) as the anchor, NOT the line number. Line numbers in this dispatch are advisory.

2. **CI yaml job placement.** The executor places `alembic-fresh-postgres` adjacent to the existing `backend-test` job (logical grouping by domain — the file currently orders jobs as `frontend-check`, `frontend-test`, `frontend-build`, `backend-test`, `e2e-smoke`, `e2e-playwright`, `e2e-full-post-merge`; the new job is backend-adjacent, so right after `backend-test` is the natural slot). The key MUST be `alembic-fresh-postgres` exactly; renaming is forbidden. Placement is non-binding beyond "anywhere under `jobs:`"; the alphabetic-key convention does NOT apply (the existing file does not use it).

3. **The `python-version: "3.12"` value.** If the existing `backend-test` job uses `"3.11"`, the executor MUST match the existing version (both jobs run the same backend code; version drift is a separate concern). If both `"3.11"` and `"3.12"` are in the matrix, the new job uses `"3.12"` (matching the dispatch author's local environment).

### §4.7 Forbidden adjustments

- Replacing `CAST(... AS hedge_classification)` with `'long'::hedge_classification` (Postgres shorthand). The `CAST(... AS ...)` form is portable to SQLite (which ignores it); the `::` shorthand raises a parse error in SQLite and breaks the test dialect.
- Adding `or_create_type=True` / `create_type=False` flags to the ENUM constructors at the top of any patched migration. The patches operate on the ENUM lifecycle (when `.create()` is called) and on the parameter-binding column metadata (which ENUM type to pass to `sa.column(...)`), not on the ENUM constructor itself. Changing the constructor flags would alter the SQLAlchemy auto-create behavior in ways that may break other code paths (`reflect`, `metadata.create_all`, etc.).
- Replacing the explicit `pricing_type.create(op.get_bind(), checkfirst=True)` in patch 1 with a no-op like `if bind.dialect.name == "postgresql": pricing_type.create(bind, checkfirst=True)`. The `checkfirst=True` keyword already short-circuits on SQLite (SQLite has no `pg_type` catalog; SQLAlchemy's ENUM-create on SQLite is a no-op anyway — it stores ENUMs as TEXT with a CHECK constraint). The dialect guard adds line noise without changing behavior.
- Moving the explicit pre-creates in patch 4 to OUTSIDE the `def upgrade()` function (e.g. at module-import time). Migration ENUM creation MUST happen inside `upgrade()` so it participates in the migration transaction.
- In patch 3, rewriting the `op.bulk_insert(...)` call as `op.execute(sa.text("INSERT INTO approval_policy ... VALUES (...)"))` with hand-written ENUM casts. The `bulk_insert` form is the canonical alembic pattern; switching to raw SQL would require manual SQLite/Postgres dialect branching and lose alembic's metadata-tracked binding. The patch is intentionally minimal — only the four `sa.column(..., <type>)` declarations change.
- In patch 3, declaring a NEW local ENUM type instance (e.g. `mutation_type_for_seed = sa.Enum(..., create_type=False)`) and passing IT to `sa.column(...)`. The existing module-level `mutation_type_enum` and `threshold_dimension_enum` are the canonical references; introducing a second instance with the same `name=` would create confusion about which one drives DDL.
- Splitting any of patches 1/2/3/4 into a follow-up PR. The chain MUST land atomically; partial application leaves the chain broken at one of the four revisions.

## §5 Frontend changes

None. This dispatch is entirely backend + CI.

## §6 Tests

No new pytest tests land in `backend/tests/`. The CI job in patch 4 IS the test — it exercises the full chain end-to-end against real Postgres, which no unit test can replicate (running alembic inside pytest would require a Postgres-aware fixture, which conflicts with the SQLite-in-memory autouse fixture in `backend/tests/conftest.py`).

The executor MUST verify locally before pushing:

1. `cd backend && python -m pytest -x -q` — full backend suite continues to pass (1494+ tests on SQLite). Regression here is blocking.
2. `cd backend && python -m pytest tests/test_alembic_chain.py -v` — chain test continues to pass (single head invariant). Regression here is blocking.
3. Local docker stack: `docker compose down -v && docker compose up -d db` (fresh volume), then `cd backend && python -m alembic upgrade head` returns exit 0 with no errors in output, then `python -m alembic current` reports `047_finance_pipeline_hb3_hardening (head)`.
4. The new CI job runs green on the executor's PR.

The pre-existing backend test suite MUST NOT be edited. The executor MUST NOT add a `test_alembic_postgres_fresh.py` to `backend/tests/` — it would either require docker (breaks unit-test isolation) or duplicate the CI job at higher cost.

## §7 Documentation

Two updates land in this PR:

1. **`CLAUDE.md`** — append one paragraph under the existing "CI / Deployment" section (immediately after the existing "GitHub Actions" paragraph). Exact text:

   > A second backend job `alembic-fresh-postgres` brings up a Postgres 16 service and applies the full migration chain end-to-end via `alembic upgrade head` to gate against fresh-bootstrap regressions. SQLite-in-memory unit tests cannot catch Postgres-strict ENUM lifecycle issues (named ENUMs that must be explicitly created before `ALTER TABLE ADD COLUMN`, text literals that need explicit `CAST(... AS <enum_name>)` against ENUM columns, double-create from `op.create_table` auto-cascade after an explicit `.create()`); this job is the durable regression gate for that class.

2. **`docs/dev-setup.md`** — append one paragraph at the end (or under the existing "Local Postgres" section if one exists). Exact text:

   > **Fresh-Postgres bootstrap discipline.** When adding a new migration that introduces a Postgres named ENUM, ensure: (a) if the ENUM is referenced ONLY via `op.create_table(...)`, no explicit `.create()` is needed (SQLAlchemy auto-creates via the table-create cascade); (b) if the ENUM is referenced via `op.add_column(...)` or `op.batch_alter_table(...).add_column(...)`, explicitly call `<enum_name>.create(op.get_bind(), checkfirst=True)` before the column-add (auto-create only fires on `CREATE TABLE`, not on `ALTER TABLE ADD COLUMN`); (c) NEVER mix BOTH an explicit `.create()` AND a subsequent `op.create_table(...)` referencing the same ENUM in the same migration without `create_type=False` on the column metadata (the table-create cascade does NOT respect `checkfirst` and will raise `DuplicateObject`); (d) when issuing an `UPDATE` that sets an ENUM column, wrap text literals in `CAST('<value>' AS <enum_name>)` (the `::<enum_name>` Postgres shorthand breaks SQLite tests). The CI job `alembic-fresh-postgres` enforces (a)–(d) automatically.

The CLAUDE.md and dev-setup.md updates are NOT optional; without them, the next contributor will re-introduce the same defect class. The dispatch-review-rules.md amendment to formally add this as rule 38 is OUT of scope for this PR (it belongs to the orchestrator's audit-protocol cycle).

## §8 Audit trail

This wave introduces NO new HMAC-signed audit event types. The patches mutate migration files (one-time DDL execution) and CI configuration; neither is a runtime mutation surface. No `AuditTrailService.record(...)` calls are added or modified.

The pre-existing migration audit trail (alembic's own `alembic_version` table) is the canonical record of which revisions have been applied to a given DB. The patches do NOT alter that audit (revisions keep their existing IDs and ancestry).

## §9 Migration plan

**No new alembic revisions land in this PR.** The chain head remains `047_finance_pipeline_hb3_hardening`. The four patched migrations keep their existing `revision` and `down_revision` tuples verbatim:

- `88c13cd6dd8e_fase1_core_domain.py`: `revision = "88c13cd6dd8e"`, `down_revision = "016"` (unchanged)
- `026_classification_invariant.py`: `revision = "026_classification_invariant"`, `down_revision = "025_decimal_primitives"` (unchanged)
- `046_workflow_approval_gate.py`: `revision = "046_workflow_approval_gate"`, `down_revision = "045_market_data_governance_columns"` (unchanged)
- `047_finance_pipeline_hb3_hardening.py`: `revision = "047_finance_pipeline_hb3_hardening"`, `down_revision = "046_workflow_approval_gate"` (unchanged)

`backend/tests/test_alembic_chain.py` is NOT edited. The single-head assertion (`047_finance_pipeline_hb3_hardening`) remains valid.

**Existing Postgres operators (production/staging):** the patches are safe. There are no known live Postgres deployments past revision `045` — `046` and `047` were authored as part of the HB-2 / HB-3 dispatch cycle, validated only on SQLite-in-memory unit tests, and never bootstrapped end-to-end against fresh Postgres in CI (the institutional debt class this PR retires). If a deployment somehow ran the unpatched `046` to completion (which is not reproducible — the `bulk_insert` rejection is unconditional on Postgres), the patched `046` produces the same three seed rows; idempotency at the bulk-insert level is guaranteed by the table's primary key on `mutation_type` (re-running would conflict, but the migration is one-shot per `alembic_version` row, so re-execution does not happen). Operators have NOT applied `047` because the unpatched `047` rolls back on fresh AND on populated Postgres (the `DuplicateObject` fires in both cases — the redundant pre-create vs. the create_table cascade is unconditional). The `046` and `047` patches remove bugs that nobody could have shipped past; there is no live database that needs cleanup.

**Operators who somehow have a stuck state** (partial `047` apply via manual SQL surgery) need to manually `DROP TYPE pipeline_risk_flag_type, pipeline_risk_flag_severity` and re-run `alembic upgrade head`. This is a one-line note in the PR description; it is NOT a migration-shipped fix because the dispatch's §2 boundary forbids backfill, and because such operators (if they exist) are at zero count.

## §10 Acceptance criteria

The PR is mergeable iff ALL of the following are simultaneously true:

1. **Fresh-Postgres bootstrap succeeds.** A clean `docker compose down -v && docker compose up -d db && cd backend && python -m alembic upgrade head` sequence returns exit 0 and `python -m alembic current` reports `047_finance_pipeline_hb3_hardening (head)`.

2. **The new CI job runs green on the PR.** The `alembic-fresh-postgres` job in `.github/workflows/ci.yml` completes successfully on the PR's head SHA. The job's `Verify single head reached` step matches `047_finance_pipeline_hb3_hardening (head)` literally.

3. **Pre-existing CI matrix continues to pass.** Every job under `.github/workflows/ci.yml` that exists on `main` immediately before this PR remains green on the PR's head SHA. Current full set: `frontend-check`, `frontend-test`, `frontend-build`, `backend-test`, `e2e-smoke`, `e2e-playwright`, `e2e-full-post-merge` (the `e2e-full-post-merge` job is the post-merge-only one and may show as `SKIPPED` on the PR — that is its expected state per its `on: push` trigger; SKIPPED counts as passing for the gate). The new `alembic-fresh-postgres` job is verified separately by criterion #2.

4. **`backend/tests/test_alembic_chain.py` passes.** Single-head invariant preserved. No revision file added or renamed.

5. **`git diff --stat <base>..HEAD` shows exactly 7 files modified:** the four migration files (`88c13cd6dd8e_fase1_core_domain.py`, `026_classification_invariant.py`, `046_workflow_approval_gate.py`, `047_finance_pipeline_hb3_hardening.py`), `.github/workflows/ci.yml`, `CLAUDE.md`, `docs/dev-setup.md`. No other files. If an 8th file shows up (other than this dispatch's parent file at `docs/audits/2026-05-26-ops-postgres-fresh-bootstrap-fix-dispatch.md` which is OUT of the executor's diff because it landed in the dispatch PR), the executor MUST justify it in the PR body or revert.

6. **The `CAST(... AS hedge_classification)` form is used in patch 2**, not the `::hedge_classification` Postgres shorthand. Grep verification: `grep -F "CAST(" backend/alembic/versions/026_classification_invariant.py` returns 2 lines; `grep -F "::hedge_classification" backend/alembic/versions/026_classification_invariant.py` returns 0 lines.

7. **Patch 3 swaps exactly four `sa.column(...)` declarations in `046`'s `bulk_insert`.** Grep verification targets ONLY the four lines inside the `op.bulk_insert(sa.table("approval_policy", ...))` block — `046` also contains multiple legitimate `sa.String(length=...)` calls in `op.create_table(...)` column definitions (e.g. `requested_by`, `approved_by`, `mutation_payload_hash`, `_uuid_type`'s sqlite variant) which the patch does NOT touch. Required: `grep -F 'sa.column("mutation_type", mutation_type_enum)' backend/alembic/versions/046_workflow_approval_gate.py` returns 1 line; `grep -F 'sa.column("threshold_dimension", threshold_dimension_enum)' backend/alembic/versions/046_workflow_approval_gate.py` returns 1 line; `grep -F 'sa.column("required_approver_roles", _json_type())' backend/alembic/versions/046_workflow_approval_gate.py` returns 1 line; `grep -F 'sa.column("fallback_when_requester_is", _json_type())' backend/alembic/versions/046_workflow_approval_gate.py` returns 1 line. Forbidden: `grep -F 'sa.column("mutation_type", sa.String)' backend/alembic/versions/046_workflow_approval_gate.py` returns 0 lines; `grep -F 'sa.column("threshold_dimension", sa.String)' backend/alembic/versions/046_workflow_approval_gate.py` returns 0 lines; `grep -F 'sa.column("required_approver_roles", sa.JSON)' backend/alembic/versions/046_workflow_approval_gate.py` returns 0 lines; `grep -F 'sa.column("fallback_when_requester_is", sa.JSON)' backend/alembic/versions/046_workflow_approval_gate.py` returns 0 lines. The executor MUST NOT widen the patch to remove `sa.String` from the `op.create_table(...)` column definitions — those are legitimate VARCHAR columns and out of scope.

8. **Patch 4 keeps exactly one explicit `.create(` call in `047`'s `upgrade()`.** Grep verification: `grep -cE "\.create\(bind.*checkfirst=True\)" backend/alembic/versions/047_finance_pipeline_hb3_hardening.py` returns `1` (only `trigger_source_enum.create(bind, checkfirst=True)` remains in upgrade; downgrade keeps its three `.drop()` calls).

9. **No new alembic revision files.** `find backend/alembic/versions/ -name '*.py' -newer <branch-base>` returns empty.

10. **No model, service, route, or schema file modified.** `git diff --stat <base>..HEAD -- backend/app/` is empty (no entries under `backend/app/`).

11. **No frontend file modified.** `git diff --stat <base>..HEAD -- frontend-svelte/` is empty.

12. **Pre-push hook v2 passes.** This dispatch and the executor PR's content are within the hook's purview (dispatch markdown for the dispatch PR; code+migrations for the executor PR). Any P1 surfaced is absorbed before merge.

13. **CLAUDE.md and docs/dev-setup.md** carry the exact paragraphs from §7. The executor MUST NOT paraphrase — the wording is institutional documentation and binding for the next contributor.

## §11 PR shape

**Branch name:** `fix/ops-postgres-fresh-bootstrap`

**Commit history (preserved on PR, squashed on merge):** five commits.

```
fix(alembic): create pricing_type enum before add_column on orders         # patch 1
fix(alembic): cast text literals to hedge_classification in 026 backfill   # patch 2
fix(alembic): bind bulk_insert columns to enum types in 046                # patch 3
fix(alembic): drop redundant enum pre-creates in 047                       # patch 4
ci(alembic): gate fresh-Postgres bootstrap via alembic-fresh-postgres job  # patch 5 + docs
```

**PR title:** `fix(ops): patch four migrations so fresh-Postgres bootstrap is clean`

**PR body (template):**

```markdown
## Summary
Patches four alembic migrations that silently relied on SQLite-only test
coverage and broke `alembic upgrade head` against a fresh Postgres 16
database. Adds a new CI job that exercises the full chain end-to-end
against real Postgres to gate against re-regression.

Per dispatch `docs/audits/2026-05-26-ops-postgres-fresh-bootstrap-fix-dispatch.md`.

- **88c13cd6dd8e_fase1_core_domain**: explicitly create `pricing_type`
  ENUM before `op.add_column("orders", ...)` (ALTER TABLE ADD COLUMN
  does not auto-create named ENUMs in Postgres).
- **026_classification_invariant**: wrap `'long'`/`'short'` in
  `CAST(... AS hedge_classification)` inside the backfill `UPDATE`
  (Postgres rejects untyped text against ENUM columns at plan-time).
- **046_workflow_approval_gate**: bind the `bulk_insert(sa.table(...))`
  column declarations to the real ENUM / JSONB types instead of
  `sa.String` / `sa.JSON` (otherwise alembic emits `$1::VARCHAR` and
  Postgres rejects against the ENUM-typed columns at executemany).
- **047_finance_pipeline_hb3_hardening**: drop the explicit pre-creates
  for `risk_flag_type_enum` and `risk_flag_severity_enum` (subsequent
  `create_table` auto-creates them without `checkfirst`, producing
  `DuplicateObject` after the redundant pre-create).
- **CI**: new `alembic-fresh-postgres` job applies the full chain
  against a Postgres 16 service container and asserts the head revision.

No chain ancestry changes, no new migration files, no application code
touched. Chain head remains `047_finance_pipeline_hb3_hardening`.

## Test plan
- [ ] `docker compose down -v && docker compose up -d db` (fresh volume)
- [ ] `cd backend && python -m alembic upgrade head` returns exit 0
- [ ] `python -m alembic current` reports `047_finance_pipeline_hb3_hardening (head)`
- [ ] `cd backend && python -m pytest -x -q` — full suite passes
- [ ] `python -m pytest backend/tests/test_alembic_chain.py -v` — chain test passes
- [ ] CI `alembic-fresh-postgres` job green
- [ ] All pre-existing CI jobs remain green

🤖 Generated with [Claude Code](https://claude.com/claude-code)
```

**Reviewers:** orchestrator (Andrei) + Greptile auto-trigger + AugmentCode auto-trigger. Codex review is RECOMMENDED but not mandatory given the surface size (six files, ~50 net lines added/removed); the orchestrator may waive Codex if Greptile and AugmentCode are both silent.

**Expected absorption volume:** based on prior precedent for surgical-fix PRs (PR #33 alembic chain hygiene merged with 1 absorption iteration; PR #88 PR-CL4-2 first PR under new gates landed Greptile-silent), expect **0–2 absorption iterations**. Pattern-completion-sweep risk is low (each patch is independent and localized); the most likely catch classes are (i) documentation-precedes-implementation false-positives on the dev-setup.md addition, which can be deflected with a "no implementation needed beyond the existing patches" reply, and (ii) the reviewer asking why `046`'s patch uses `mutation_type_enum` (which has `create=True` default) rather than a sibling `create_type=False` variant — the answer is in §4.3 rationale and §4.7 forbidden adjustments (the `sa.column(...)` primitive does NOT trigger DDL, so the constructor's `create_type` flag is irrelevant here; introducing a sibling variant would create two type instances with the same `name=`, which is more fragile than passing the existing one).

**Hook v2 behavior:** the dispatch text in this file will trigger the pre-push LLM review hook when the dispatch PR (i.e. THIS file) is pushed. The hook is expected to be green on this dispatch — no P1-shaped patterns (no FLOAT_LITERAL on ingest, no DELETE on audit, no role-bypass, no schema mutation, no silent fallback, no mixed pricing regimes). Any P1 the hook surfaces against THIS dispatch is itself a dispatch defect to absorb pre-merge.

**Post-merge:** the executor PR opens immediately against the post-dispatch-merge HEAD. The orchestrator does NOT batch the institutional-debt-class C-OPS-PG-FRESH retirement (a future addition to dispatch-review-rules.md as rule 38) into the same executor session; that is a separate orchestrator-cycle task.
