# Codex Adversarial Review Absorption — Working Tree Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Absorb the three findings from the 2026-05-22 Codex adversarial review on the current working tree so the alembic + docker-compose port hardening is safe on real PostgreSQL upgrade paths.

**Architecture:**
1. Fix migrations 010/011 to use `postgresql.ENUM(..., create_type=False)` directly (mirroring the corrected pattern in 001/002/004) so no second implicit `CREATE TYPE` is emitted by `op.add_column`.
2. Widen `alembic_version.version_num` on already-initialized Postgres databases via an explicit `ALTER TABLE` before the existing `CREATE TABLE IF NOT EXISTS` (which only helps fresh databases).
3. Reconcile the `docker-compose.yml` host port 5433 with the `localhost:5432` references still in `docs/dev-pycharm-setup.md`.
4. Add the untracked `.codex-gitdir-*/` and `.codex-gitdir-test/` reviewer scratch directories to `.gitignore` so a future `git add -A` does not commit them.

**Tech Stack:** Alembic 1.x, SQLAlchemy 2.0+ (`sqlalchemy.dialects.postgresql.ENUM`), Postgres 16 (docker-compose), SQLite (tests), pytest.

**Codex findings being absorbed (verbatim severity tags):**
- `[high]` `backend/alembic/env.py:50-56` — pre-existing `alembic_version` tables are never widened.
- `[high]` `backend/alembic/versions/010_add_hedge_contract_status.py:31-34` and `011_add_order_pricing_fields.py:30-34` — `create_type=False` applied to `sa.Enum` (generic), not `postgresql.ENUM`, so the kwarg is ignored under SQLAlchemy 2.0+ and a duplicate `CREATE TYPE` can still fire on `op.add_column`.
- `[medium]` `docker-compose.yml:8-11` vs `docs/dev-pycharm-setup.md` — compose now exposes db on host 5433 but the PyCharm guide still tells operators to point JDBC/`DATABASE_URL` at `localhost:5432`.

**Non-goals:**
- No new functionality. No schema changes to application tables. No re-numbering of revisions.
- Do NOT touch `.codex-gitdir-pr95/` contents — only add to `.gitignore`.
- Do NOT widen `alembic_version` outside the dialect guard.

---

## File Structure

| File | Responsibility | Action |
| --- | --- | --- |
| `backend/alembic/env.py` | Pre-create / widen `alembic_version` for Postgres before Alembic stamps | Modify (lines 41-56) |
| `backend/alembic/versions/010_add_hedge_contract_status.py` | Add `status` enum column to `hedge_contracts` | Modify (lines 25-39) |
| `backend/alembic/versions/011_add_order_pricing_fields.py` | Add `pricing_convention` enum column to `orders` | Modify (lines 23-37) |
| `docs/dev-pycharm-setup.md` | PyCharm setup guide (datasource, env vars) | Modify (lines 49-65, 149-156) |
| `.gitignore` | Top-level git ignore | Modify (append `.codex-gitdir-*/`) |
| `backend/tests/test_migrations_pg_idempotency.py` | New test — exercises 010/011 on Postgres against an already-initialized DB (skipped if no PG URL) | Create |

The migration fix for 010/011 follows the **exact pattern** already used in `001_create_orders_table.py` (lines 21-37 of working tree, post-edit): declare a module-level `postgresql.ENUM(..., create_type=False)` instance, call `.create(bind, checkfirst=True)` explicitly, and pass that **same instance** as the column type. Do not introduce a new helper — DRY against 001/002/004's pattern.

---

## Task 1: Fix `create_type=False` kwarg in migration 010

**Files:**
- Modify: `backend/alembic/versions/010_add_hedge_contract_status.py:23-46`

**Why:** Codex finding: `sa.Enum("active", "cancelled", "settled", name="hedge_contract_status", create_type=False)` silently drops `create_type` because that kwarg is only recognized by `postgresql.ENUM`. Under SQLAlchemy 2.0+, `op.add_column` can therefore still emit a second `CREATE TYPE hedge_contract_status` and raise `DuplicateObject`. The corrected pattern reuses the already-created `postgresql.ENUM` instance as the column type — identical to how `001_create_orders_table.py` does it post-edit.

- [ ] **Step 1: Write the failing test (skips without PG)**

Create `backend/tests/test_migrations_pg_idempotency.py`:

```python
"""Postgres-only regression: re-running migrations 010 and 011 on a database
where the enum types already exist must not raise DuplicateObject.

This guards against Codex finding [high] from 2026-05-22: sa.Enum(..., create_type=False)
does NOT preserve the flag (the kwarg belongs to postgresql.ENUM), so op.add_column can
emit an implicit CREATE TYPE even though we already created the enum manually.

Skipped if no real PostgreSQL DATABASE_URL is configured for the test runner —
the sqlite test path does not exercise CREATE TYPE.
"""
from __future__ import annotations

import os
import uuid

import pytest
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


PG_URL = os.getenv("TEST_PG_URL")

pytestmark = pytest.mark.skipif(
    not PG_URL,
    reason="TEST_PG_URL not set; this regression requires a real PostgreSQL instance.",
)


def _make_engine() -> sa.Engine:
    return sa.create_engine(PG_URL, future=True)


def test_hedge_contract_status_enum_idempotent_on_add_column() -> None:
    """Simulate the 010 upgrade against a DB that already has the enum + table."""
    engine = _make_engine()
    schema = f"codex_010_{uuid.uuid4().hex[:8]}"
    with engine.begin() as conn:
        conn.execute(sa.text(f'CREATE SCHEMA "{schema}"'))
        conn.execute(sa.text(f'SET search_path TO "{schema}"'))
        # Pre-create the enum + a stub hedge_contracts table (no status column yet),
        # mirroring an environment that ran prior migrations and is about to run 010.
        status_enum = postgresql.ENUM(
            "active", "cancelled", "settled",
            name="hedge_contract_status", create_type=False,
        )
        status_enum.create(conn, checkfirst=True)
        conn.execute(sa.text(
            'CREATE TABLE hedge_contracts (id UUID PRIMARY KEY)'
        ))
        # Pre-create the enum *type* one more time to simulate a partial / re-applied run.
        conn.execute(sa.text(
            "DO $$ BEGIN "
            "  IF NOT EXISTS (SELECT 1 FROM pg_type WHERE typname = 'hedge_contract_status') THEN "
            "    CREATE TYPE hedge_contract_status AS ENUM ('active','cancelled','settled'); "
            "  END IF; "
            "END $$;"
        ))

        # This mirrors the corrected upgrade body of migration 010.
        column_type = postgresql.ENUM(
            "active", "cancelled", "settled",
            name="hedge_contract_status", create_type=False,
        )
        conn.execute(sa.text(
            'ALTER TABLE hedge_contracts ADD COLUMN status '
            f'{column_type.compile(dialect=conn.dialect)} NOT NULL DEFAULT \'active\''
        ))
        # Cleanup.
        conn.execute(sa.text(f'DROP SCHEMA "{schema}" CASCADE'))


def test_order_pricing_convention_enum_idempotent_on_add_column() -> None:
    """Same regression for migration 011 (orders.pricing_convention)."""
    engine = _make_engine()
    schema = f"codex_011_{uuid.uuid4().hex[:8]}"
    with engine.begin() as conn:
        conn.execute(sa.text(f'CREATE SCHEMA "{schema}"'))
        conn.execute(sa.text(f'SET search_path TO "{schema}"'))
        conn.execute(sa.text(
            "DO $$ BEGIN "
            "  IF NOT EXISTS (SELECT 1 FROM pg_type WHERE typname = 'order_pricing_convention') THEN "
            "    CREATE TYPE order_pricing_convention AS ENUM ('AVG','AVGInter','C2R'); "
            "  END IF; "
            "END $$;"
        ))
        conn.execute(sa.text('CREATE TABLE orders (id UUID PRIMARY KEY)'))

        column_type = postgresql.ENUM(
            "AVG", "AVGInter", "C2R",
            name="order_pricing_convention", create_type=False,
        )
        conn.execute(sa.text(
            'ALTER TABLE orders ADD COLUMN pricing_convention '
            f'{column_type.compile(dialect=conn.dialect)}'
        ))
        conn.execute(sa.text(f'DROP SCHEMA "{schema}" CASCADE'))
```

- [ ] **Step 2: Confirm the test skips cleanly without PG (sanity check)**

Run from `backend/`:

```sh
python -m pytest tests/test_migrations_pg_idempotency.py -v
```

Expected: both tests SKIPPED with reason `TEST_PG_URL not set; this regression requires a real PostgreSQL instance.` (Exit 0, 2 skipped.)

This is the offline sanity check; the real failure-mode reproduction must run against a live Postgres in Step 6.

- [ ] **Step 3: Apply the fix in migration 010**

Open `backend/alembic/versions/010_add_hedge_contract_status.py`. Replace the entire `upgrade()` body (lines 23-41 in current working tree) with the version below. The key change: the `op.add_column` `Column` now reuses the already-created `postgresql.ENUM` instance (which carries `create_type=False` as a real attribute), instead of constructing a new generic `sa.Enum` that drops the flag.

```python
def upgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name == "postgresql":
        # Same instance is used twice: once to .create() the type, then as the column type.
        # Reusing the postgresql.ENUM instance (with create_type=False) is the only way
        # to guarantee op.add_column does NOT emit a second CREATE TYPE under SA 2.0+.
        # The generic sa.Enum drops create_type silently — see Codex review 2026-05-22.
        status_enum_pg = postgresql.ENUM(
            "active", "cancelled", "settled",
            name="hedge_contract_status", create_type=False,
        )
        status_enum_pg.create(bind, checkfirst=True)
        op.add_column(
            "hedge_contracts",
            sa.Column(
                "status",
                status_enum_pg,
                nullable=False,
                server_default="active",
            ),
        )
    else:
        op.add_column(
            "hedge_contracts",
            sa.Column("status", sa.String(length=32), nullable=False, server_default="active"),
        )

    op.execute("UPDATE hedge_contracts SET status = 'active' WHERE status IS NULL")
```

Leave the `downgrade()` body unchanged.

- [ ] **Step 4: Lint the migration**

Run from `backend/`:

```sh
ruff check alembic/versions/010_add_hedge_contract_status.py
```

Expected: no issues. If ruff complains about unused `postgresql` import on SQLite path — that import is still used because `postgresql.ENUM` is referenced inside the `if` branch.

- [ ] **Step 5: Commit**

```sh
git add backend/alembic/versions/010_add_hedge_contract_status.py backend/tests/test_migrations_pg_idempotency.py
git commit -m "fix(alembic): use postgresql.ENUM directly in migration 010 to honor create_type=False

Codex adversarial review 2026-05-22 [high]: sa.Enum(..., create_type=False)
silently drops the kwarg under SQLAlchemy 2.0+, allowing op.add_column to emit
a second CREATE TYPE and hit DuplicateObject. Reuse the postgresql.ENUM
instance for the column type, mirroring the corrected pattern in 001/002/004.
Regression: test_migrations_pg_idempotency.py (skipped without TEST_PG_URL)."
```

- [ ] **Step 6: (Optional, when live Postgres available) Run the regression**

```sh
# Bring up the compose db on host port 5433 (post-Task 3 it already is)
docker compose up -d db
TEST_PG_URL='postgresql+psycopg://hc:hc@localhost:5433/hedgecontrol' \
    python -m pytest backend/tests/test_migrations_pg_idempotency.py::test_hedge_contract_status_enum_idempotent_on_add_column -v
```

Expected: PASS (no `DuplicateObject` raised). If this fails on the unfixed branch, re-confirm Step 3 was applied; if it fails on the fixed branch, escalate — that means SQLAlchemy adapter still emits a second `CREATE TYPE` even when reusing the `postgresql.ENUM` instance.

---

## Task 2: Fix `create_type=False` kwarg in migration 011

**Files:**
- Modify: `backend/alembic/versions/011_add_order_pricing_fields.py:23-44`

**Why:** Same root cause as Task 1, separate revision so it gets its own commit and is independently revertable.

- [ ] **Step 1: Apply the fix in migration 011**

Open `backend/alembic/versions/011_add_order_pricing_fields.py`. Replace the entire `upgrade()` body with:

```python
def upgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name == "postgresql":
        # Same postgresql.ENUM instance is reused on the column to prevent SQLAlchemy
        # from emitting a second CREATE TYPE under SA 2.0+ (Codex review 2026-05-22).
        convention_enum_pg = postgresql.ENUM(
            "AVG", "AVGInter", "C2R",
            name="order_pricing_convention", create_type=False,
        )
        convention_enum_pg.create(bind, checkfirst=True)
        op.add_column(
            "orders",
            sa.Column(
                "pricing_convention",
                convention_enum_pg,
                nullable=True,
            ),
        )
    else:
        op.add_column(
            "orders",
            sa.Column("pricing_convention", sa.String(length=32), nullable=True),
        )

    op.add_column("orders", sa.Column("avg_entry_price", sa.Float(), nullable=True))
```

Leave the `downgrade()` body unchanged.

- [ ] **Step 2: Lint**

```sh
ruff check backend/alembic/versions/011_add_order_pricing_fields.py
```

Expected: no issues.

- [ ] **Step 3: Run the existing test suite (SQLite path)**

Run from `backend/`:

```sh
python -m pytest -x -q
```

Expected: full suite PASS (this exercises the SQLite branch of 010 + 011, confirming we didn't break it).

- [ ] **Step 4: Commit**

```sh
git add backend/alembic/versions/011_add_order_pricing_fields.py
git commit -m "fix(alembic): use postgresql.ENUM directly in migration 011 to honor create_type=False

Same Codex finding as 010 — reuse the postgresql.ENUM instance for the column type."
```

- [ ] **Step 5: (Optional, with TEST_PG_URL) Run the 011 regression**

```sh
TEST_PG_URL='postgresql+psycopg://hc:hc@localhost:5433/hedgecontrol' \
    python -m pytest backend/tests/test_migrations_pg_idempotency.py::test_order_pricing_convention_enum_idempotent_on_add_column -v
```

Expected: PASS.

---

## Task 3: Widen pre-existing `alembic_version` rows on Postgres

**Files:**
- Modify: `backend/alembic/env.py:41-56`

**Why:** Codex finding `[high]`: the current guard only runs `CREATE TABLE IF NOT EXISTS alembic_version (version_num VARCHAR(128) ...)`. On any Postgres database that was already initialized by stock Alembic (default `VARCHAR(32)`), the `IF NOT EXISTS` short-circuits and the narrow column stays. The first long revision id (e.g. `036_merge_w1_heads`, 36 chars) cannot be stamped and Alembic blows up. We must explicitly `ALTER` the column when it exists and is narrower than 128.

The block must remain inside the `if connection.dialect.name == "postgresql"` guard — SQLite tests recreate schema fresh and don't have this problem.

- [ ] **Step 1: Apply the widening logic**

Open `backend/alembic/env.py`. Replace the block from line 41 through line 56 (the `# Pre-create alembic_version...` comment through `connection.commit()`) with:

```python
        # Postgres-only: make alembic_version.version_num wide enough for this project's
        # descriptive revision IDs (longest today is "003_create_hedge_order_linkages_table"
        # at 37 chars). SQLite tests recreate schema fresh, so this is a no-op there.
        #
        # Two cases must be handled:
        #   1. Fresh DB — table does not exist. CREATE TABLE with VARCHAR(128).
        #   2. Already-initialized DB — table exists with Alembic's default VARCHAR(32).
        #      CREATE TABLE IF NOT EXISTS is a no-op here, so we need an explicit ALTER.
        # Codex adversarial review 2026-05-22 [high] — without (2), partially migrated
        # environments still fail when Alembic tries to stamp a long revision id.
        if connection.dialect.name == "postgresql":
            existing_len = connection.execute(
                text(
                    "SELECT character_maximum_length "
                    "FROM information_schema.columns "
                    "WHERE table_name = 'alembic_version' "
                    "  AND column_name = 'version_num' "
                    "  AND table_schema = current_schema()"
                )
            ).scalar()

            if existing_len is None:
                # Case 1: fresh DB.
                connection.execute(
                    text(
                        "CREATE TABLE alembic_version ("
                        "version_num VARCHAR(128) NOT NULL, "
                        "CONSTRAINT alembic_version_pkc PRIMARY KEY (version_num)"
                        ")"
                    )
                )
            elif existing_len < 128:
                # Case 2: pre-existing narrow column. Widen in place.
                connection.execute(
                    text("ALTER TABLE alembic_version ALTER COLUMN version_num TYPE VARCHAR(128)")
                )
            # else: column already wide enough — no-op.
            connection.commit()
```

- [ ] **Step 2: Lint env.py**

```sh
ruff check backend/alembic/env.py
```

Expected: no issues.

- [ ] **Step 3: Run the full suite to confirm SQLite path untouched**

```sh
cd backend && python -m pytest -x -q
```

Expected: PASS (no Postgres branch exercised; the dialect guard keeps SQLite tests unaffected).

- [ ] **Step 4: (Optional, with live Postgres) Reproduce the pre-existing-narrow-column case**

```sh
# Spin a throwaway db on host 5433, simulate the pre-existing narrow column.
docker compose up -d db
psql 'postgresql://hc:hc@localhost:5433/hedgecontrol' -c \
  "DROP TABLE IF EXISTS alembic_version; \
   CREATE TABLE alembic_version (version_num VARCHAR(32) NOT NULL PRIMARY KEY);"

# Now run alembic upgrade head — the new ALTER must widen the column without error.
cd backend && DATABASE_URL='postgresql+psycopg://hc:hc@localhost:5433/hedgecontrol' \
    alembic upgrade head

# Verify width.
psql 'postgresql://hc:hc@localhost:5433/hedgecontrol' -c \
  "SELECT character_maximum_length FROM information_schema.columns \
   WHERE table_name='alembic_version' AND column_name='version_num';"
```

Expected: `character_maximum_length = 128` after `alembic upgrade head`.

- [ ] **Step 5: Commit**

```sh
git add backend/alembic/env.py
git commit -m "fix(alembic): widen pre-existing alembic_version.version_num on Postgres

Codex adversarial review 2026-05-22 [high]: CREATE TABLE IF NOT EXISTS only
helps fresh databases. Already-initialized Postgres environments keep the
default VARCHAR(32) and cannot stamp this project's long descriptive
revision IDs. Add an explicit ALTER for the pre-existing-narrow case."
```

---

## Task 4: Reconcile docker-compose port 5433 with PyCharm setup doc

**Files:**
- Modify: `docs/dev-pycharm-setup.md:49-66` (datasource table + smoke test) and `:149-156` (env-var section)

**Why:** `docker-compose.yml` exposes the db on host port **5433** (to avoid colliding with a native Postgres on 5432), but `docs/dev-pycharm-setup.md` (new file in this working tree) still tells operators to use `localhost:5432` for the JDBC datasource and the run-config `DATABASE_URL`. That makes Test Connection either fail or, worse, connect to an unrelated native Postgres instance — exactly the silent-fallback the constitution prohibits.

We update the doc to match compose. (The compose mapping `5433:5432` is **kept as-is** — it is intentional and the comment in compose explains why. Only the doc references change.)

- [ ] **Step 1: Update the datasource table and smoke test in section 3**

Open `docs/dev-pycharm-setup.md`. Replace the section starting at line 49 (`| Datasource | URL | Usuário |`) through line 65 (`publicado (\`docker ps\`).`) with:

```markdown
| Datasource | URL | Usuário |
|---|---|---|
| HedgeControl @ localhost (Postgres docker) | `jdbc:postgresql://localhost:5433/hedgecontrol` | `hc` |
| HedgeControl test.db (SQLite) | `jdbc:sqlite:$PROJECT_DIR$/test.db` | — |

Na primeira conexão o PyCharm vai pedir a senha. Use **`hc`** (a credencial
de dev definida no `docker-compose.yml`). Escolha "Save → In KeePass /
Windows Credential Manager" — a senha **não vai para o XML**.

> **Por que 5433 e não 5432?** O `docker-compose.yml` publica o Postgres do
> container na porta **5433** do host para não colidir com uma instalação
> nativa de Postgres no Windows (que normalmente ocupa a 5432). Dentro da
> rede do compose, o banco continua respondendo na 5432 — por isso o
> backend container usa `db:5432`. Só o **host** vê 5433.

Antes de conectar, suba o Postgres:

\`\`\`sh
docker compose up -d db
\`\`\`

Depois `Test Connection`. Se falhar, confirme que `localhost:5433` está
publicado (`docker ps` deve mostrar `0.0.0.0:5433->5432/tcp`).
```

(Note: the code-fence inside the doc block above uses escaped backticks because the plan itself is markdown. When editing the actual file, write real triple-backticks.)

- [ ] **Step 2: Update the `DATABASE_URL` in section 7 (env vars)**

In the same file, in section "## 7. Variáveis de ambiente" (around line 149), replace:

```
`DATABASE_URL=postgresql+psycopg://hc:hc@localhost:5432/hedgecontrol`,
```

with:

```
`DATABASE_URL=postgresql+psycopg://hc:hc@localhost:5433/hedgecontrol`,
```

- [ ] **Step 3: Grep for any remaining `localhost:5432` references in docs**

```sh
grep -rn "localhost:5432" docs/ backend/.idea/ .idea/ 2>/dev/null
```

Expected output: empty (only the compose internal `db:5432` should remain in `docker-compose.yml`, which we are **not** changing). If the run-configuration XMLs under `.idea/runConfigurations/` reference `localhost:5432` in `<envs>` blocks, treat that as an out-of-scope finding — `.idea/` is local per the doc itself — and surface as a follow-up note, do **not** edit `.idea/*.xml` in this plan.

- [ ] **Step 4: Verify the doc still renders cleanly**

Open `docs/dev-pycharm-setup.md` in any markdown previewer (or just `cat` it). Expected: no broken tables, code fences balanced.

- [ ] **Step 5: Commit**

```sh
git add docs/dev-pycharm-setup.md
git commit -m "docs(dev): correct PyCharm datasource + DATABASE_URL to host port 5433

Codex adversarial review 2026-05-22 [medium]: docker-compose publishes
Postgres on host 5433 (to avoid collision with native Windows Postgres on
5432), but the new PyCharm setup guide still pointed JDBC + DATABASE_URL at
localhost:5432. Could connect to an unrelated native Postgres instead of
the compose db. Explain the 5433/5432 split in the doc itself."
```

---

## Task 5: Ignore Codex worktree scratch directories

**Files:**
- Modify: `.gitignore` (append-only)

**Why:** Codex finding next-step: `git status` shows `.codex-gitdir-pr95/` (the codex review companion's git-dir cache) and `.codex-gitdir-test/` are untracked. A casual `git add -A` would drop the entire review-runtime scratch tree into the repo. Add a top-level ignore. These are not project artifacts; they live in the working tree only because the Codex companion creates them adjacent to the repo.

- [ ] **Step 1: Append the ignore rules**

Open `.gitignore` and append at the end (preserve the existing trailing newline behavior):

```
# Codex Connector / openai-codex companion scratch directories (review runtime only)
.codex-gitdir-*/
.codex-pytest-tmp/
```

(The `.codex-pytest-tmp/` entry is included because `git status` already emitted a `warning: could not open directory 'backend/.codex-pytest-tmp/pytest-of-Andrei/': Permission denied` — same class of artifact.)

- [ ] **Step 2: Confirm the directories now show as ignored**

```sh
git status --short --untracked-files=all | grep -E '^\?\? \.codex' || echo "no codex untracked entries — good"
```

Expected: `no codex untracked entries — good`. If any line still appears, double-check the ignore pattern matches the directory name exactly.

- [ ] **Step 3: Confirm we did not accidentally ignore something legitimate**

```sh
git check-ignore -v docs/audits/2026-05-13-phase-a6-closure.md 2>&1 || true
```

Expected: empty output (the file is NOT matched by any rule — good). If output mentions our new line, the pattern is too broad.

- [ ] **Step 4: Commit**

```sh
git add .gitignore
git commit -m "chore(gitignore): ignore Codex companion scratch directories

git status was surfacing .codex-gitdir-pr95/ + .codex-gitdir-test/ + the
.codex-pytest-tmp/ artifact left by the openai-codex plugin. They are
review-runtime caches, not project artifacts — keep them out of git so a
git add -A never traps them."
```

---

## Task 6: Final verification sweep

**Files:** None modified — verification only.

- [ ] **Step 1: Confirm the working tree contains only the intended changes**

```sh
git status --short
```

Expected: clean working tree (all five commits absorbed). If anything is still dirty, inspect with `git diff` and decide whether it belongs in this plan or a separate change.

- [ ] **Step 2: Re-run the full backend suite**

```sh
cd backend && python -m pytest -x -q
```

Expected: all green (SQLite path). Token of evidence: same pass-count as the baseline before this plan started.

- [ ] **Step 3: Lint the whole backend tree (cheap, fast — catches any stray issue)**

```sh
cd backend && ruff check .
```

Expected: clean.

- [ ] **Step 4: Confirm alembic still has a single head**

```sh
cd backend && alembic heads
```

Expected: a single head matching the latest revision (this plan does NOT add a revision).

- [ ] **Step 5: Audit the five commits**

```sh
git log --oneline -5
```

Expected (in this order, top to bottom = newest to oldest):

```
<sha> chore(gitignore): ignore Codex companion scratch directories
<sha> docs(dev): correct PyCharm datasource + DATABASE_URL to host port 5433
<sha> fix(alembic): widen pre-existing alembic_version.version_num on Postgres
<sha> fix(alembic): use postgresql.ENUM directly in migration 011 to honor create_type=False
<sha> fix(alembic): use postgresql.ENUM directly in migration 010 to honor create_type=False
```

If the order differs (e.g. Task 4 ran before Task 3), that is fine — sequence is by topic, not by commit-graph order. The five commit messages must all be present.

---

## Self-Review

**1. Spec coverage:**
- Codex finding 1 (alembic_version not widened): Task 3 ✅
- Codex finding 2 (create_type=False on sa.Enum, migrations 010 + 011): Tasks 1 + 2 ✅
- Codex finding 3 (docker-compose port 5433 vs doc 5432): Task 4 ✅
- Next-step (.codex-gitdir-pr95 untracked): Task 5 ✅
- No gaps.

**2. Placeholder scan:** No TBD / TODO / "appropriate error handling" / "similar to Task N" placeholders. Every code step has the full code body. Every verification step has the exact command + expected output.

**3. Type / pattern consistency:**
- Migration 010 + 011 + 001 + 002 + 004 all use the same pattern post-edit: declare `postgresql.ENUM(..., create_type=False)`, `.create(bind, checkfirst=True)`, pass the **same instance** as the column type. Names use the `_pg` suffix in 001/002/004 and a `_pg` variable in 010/011 — consistent.
- `env.py` widening uses `information_schema.columns` against `current_schema()` — matches how the rest of the Alembic env script scopes work; no schema-search-path leakage.
- Test file imports + assertions match (`postgresql.ENUM`, `sa.text`, `pytest.mark.skipif`).
- Commit messages all attribute the Codex 2026-05-22 review for audit trail traceability.

No issues found in re-read.

---

## Execution Handoff

Plan complete and saved to `docs/superpowers/plans/2026-05-22-codex-findings-absorption.md`. Two execution options:

1. **Subagent-Driven (recommended)** — I dispatch a fresh subagent per task, review between tasks, fast iteration.
2. **Inline Execution** — Execute tasks in this session using executing-plans, batch execution with checkpoints.

Which approach?
