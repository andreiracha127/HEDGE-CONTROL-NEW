# Phase A5 Remediation Dispatch - PR-A5-3 Audit History and Authorization Guardrails

**Phase:** A5 - Audit trail, governance enforcement, and cross-cutting reconstruction  
**Wave:** PR-A5-3  
**Authoring date:** 2026-05-11  
**Repository:** `D:/Projetos/Hedge-Control-New`  
**Base branch:** `main`  
**Required branch:** `audit-a5/audit-history-auth-guardrails`  
**Source verdict:** `docs/audits/2026-05-11-phase-a5-jury-verdict.md`

## 1. Objective

Close:

- `J-A5-04` - Preserve audit history across downgrade paths.
- `J-A5-06` - Align auth startup fail-closed behavior with canonical settings.

This wave hardens the audit table lifecycle and the audit read/verify
authorization boundary. It is intentionally narrower than PR-A5-1 and PR-A5-2:
no route transaction refactor, no checksum redesign, and no worker audit API.

## 2. Non-Negotiable Constraints

- Do not edit `docs/governance.md`.
- Do not drop, truncate, rename away, or otherwise destroy `audit_events` data
  in downgrade paths.
- Do not rely on a secondary environment variable when canonical settings
  already expose `APP_ENV`.
- Do not weaken local/test developer behavior by accident; explicit local/test
  bypasses may remain only when tied to canonical non-production settings.
- Do not broaden this into a general IAM redesign.

Audit history is append-only institutional evidence. Authorization for audit
read/verify surfaces must fail closed in production/staging-like environments.

## 3. Findings and Evidence

### J-A5-04 - Destructive audit downgrade

The jury accepted that migration downgrade can destroy the append-only audit
history:

- `backend/alembic/versions/015_phase7_audit_events_table.py:19`
- `backend/alembic/versions/015_phase7_audit_events_table.py:34`
- `backend/alembic/versions/015_phase7_audit_events_table.py:53`
- `backend/alembic/versions/015_phase7_audit_events_table.py:73`
- `backend/alembic/versions/015_phase7_audit_events_table.py:82`.

### J-A5-06 - Auth fail-closed mismatch

The jury accepted that auth startup validation reads a different environment
marker from canonical settings:

- `backend/app/core/config.py:20`
- `backend/app/core/config.py:127`
- `backend/app/core/auth.py:27`
- `backend/app/core/auth.py:31`
- `backend/app/core/auth.py:38`
- `backend/app/core/auth.py:117`
- `backend/app/core/auth.py:124`
- `backend/app/core/auth.py:162`
- `backend/app/api/routes/audit.py:37`
- `backend/app/api/routes/audit.py:59`.

## 4. Required Implementation Boundary

### Audit Migration Downgrade

Make audit-table downgrade behavior non-destructive.

Minimum acceptable behavior:

- no `op.drop_table("audit_events")` in the audit-events migration downgrade;
- no downgrade operation that deletes existing audit event rows;
- downgrade may remove non-data enforcement objects only if doing so is
  necessary and documented in code comments/tests;
- preserve enough structure/data for an operator to retain audit history even
  after a downgrade.

If the chosen policy is "audit table cannot be downgraded destructively," make
that explicit and testable.

### Auth Startup Validation

Unify auth startup validation on the canonical settings object and environment
marker.

Minimum acceptable behavior:

- production and staging-like `APP_ENV` values fail startup when JWT auth config
  is absent or incomplete;
- local/test/development bypasses remain explicit and tied to canonical
  settings, not an unrelated `ENVIRONMENT` variable;
- audit read/verify endpoints cannot be reached anonymously when production or
  staging auth is expected;
- anonymous fallback role behavior cannot grant `auditor` access under a
  production/staging configuration error.

## 5. Acceptance Criteria

- Static or migration test proves `audit_events` is not dropped by downgrade.
- Any downgrade logic preserves existing `audit_events` data.
- `APP_ENV=production` with missing JWT config fails closed.
- `APP_ENV=staging` with missing JWT config fails closed.
- `APP_ENV=development|local|test` behavior remains explicitly allowed only for
  non-production use.
- Audit list and verify routes reject anonymous access under production/staging
  auth expectations.
- Tests cover the mismatch that previously allowed `APP_ENV=production` with
  unset `ENVIRONMENT`.
- `docs/governance.md` has no diff.

## 6. Required Tests

Add or update focused tests under `backend/tests/`.

Minimum test coverage:

- migration/static assertion that `015_phase7_audit_events_table.py` downgrade
  does not call `op.drop_table("audit_events")`;
- production missing JWT config raises during startup validation;
- staging missing JWT config raises during startup validation;
- development/local/test bypass remains explicit and covered;
- audit list endpoint rejects anonymous access when production/staging auth is
  expected;
- audit verify endpoint rejects anonymous access when production/staging auth is
  expected.

## 7. Required Verification

Run, at minimum:

```bash
python -m pytest backend/tests/test_audit_signing_key_required.py -q
python -m pytest backend/tests/test_audit_signature.py -q
python -m pytest backend/tests/test_auth_role_isolation.py -q
python -m pytest backend/tests/test_audit_query_filters.py -q
python -m alembic heads
git diff --check
```

Also run and report:

```bash
rg -n "drop_table\(\"audit_events\"|ENVIRONMENT|APP_ENV|JWT_ISSUER" backend/app backend/alembic backend/tests
```

If full backend is run and `backend/tests/test_ws.py` fails locally on Python
3.14 with the known `asyncio.get_event_loop()` issue, report it separately and
do not treat it as evidence against this wave.

## 8. Out of Scope

- Audit/mutation atomicity for economic routes. That is PR-A5-1.
- Audit checksum reconstruction. That is PR-A5-1.
- Route coverage and worker audit envelope. That is PR-A5-2.
- Broader IAM redesign outside the concrete `APP_ENV` / auth startup mismatch.
- Frontend audit UX.

## 9. PR Requirements

- Use branch `audit-a5/audit-history-auth-guardrails`.
- Push normally; do not use `--no-verify`.
- Open a PR against `main`.
- Include in the PR body:
  - findings closed;
  - files changed;
  - tests run and results;
  - migration/downgrade evidence;
  - auth startup matrix;
  - hook artifact path;
  - statement that `docs/governance.md` has no diff.

