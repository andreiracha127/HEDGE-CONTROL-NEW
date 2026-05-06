# Phase A1 — PR #6 Dispatch — Hedge Classification DB Invariant

**Wave:** 1 (no dependencies)
**Stage:** Remediation (post-jury)
**Authoring date:** 2026-05-06
**Findings covered:** J-A1-OPUS-04 (Tier 1)
**Branch name:** `audit-a1/classification-invariant`
**Base:** `main` (latest)

---

## 1. Mission

Make `HedgeContract.classification` derivable-only from `fixed_leg_side`. Today both columns are independent, persisted, and mutable — there is no DB invariant preventing inconsistent rows (e.g., `fixed_leg_side='buy'` + `classification='short'`). Constitution §2.3 calls this rule "absolute and non-negotiable"; the persistence layer must enforce it.

The deterministic application **create path** is fine (`ContractService.create` derives classification correctly at `contract_service.py:60-78`, schema enforces 1 fixed + 1 variable leg). The bug is **after creation**: a UPDATE statement, a buggy admin tool, or a stray ORM mutation can drift the columns apart.

**Persona:** Senior engineer who treats "absolute" rules as DB-level invariants, not application-level conventions. Constitution §2.3 + §2.7 require the invariant to be reconstructable from any DB snapshot.

---

## 2. Reference docs

- **`docs/audits/2026-05-06-phase-a1-jury-verdict.md`** — finding J-A1-OPUS-04 (§3 Opus-only). Read in full.
- **`docs/governance.md`** — §2.3 (absolute classification rule), §2.7 (audit-friendly).
- **`docs/audits/2026-05-06-phase-a1-findings-opus.md`** — F-A1-OPUS-08 for full mechanism.

---

## 3. Scope IN — choose ONE invariant strategy and ship it

The verdict offers three options. Choose based on Postgres version + project preference:

### Option A — `GENERATED ALWAYS AS` column (Postgres 12+)

Replace `classification` as an independently-stored column with a generated column derived from `fixed_leg_side`:

```sql
ALTER TABLE hedge_contracts
    DROP COLUMN classification,
    ADD COLUMN classification VARCHAR(8)
        GENERATED ALWAYS AS (
            CASE fixed_leg_side
                WHEN 'buy'  THEN 'long'
                WHEN 'sell' THEN 'short'
            END
        ) STORED;
```

- ORM: SQLAlchemy `Computed("...", persisted=True)` annotation
- Pros: impossible to drift; simplest reads
- Cons: backfill needed; reverse migration is a real DROP+ADD

### Option B — `CHECK` constraint

Keep `classification` as a stored column, but add a CHECK that ties it to `fixed_leg_side`:

```sql
ALTER TABLE hedge_contracts
    ADD CONSTRAINT chk_classification_matches_fixed_leg
    CHECK (
        (fixed_leg_side = 'buy'  AND classification = 'long')
        OR (fixed_leg_side = 'sell' AND classification = 'short')
    );
```

- ORM: declared constraint at table level
- Pros: minimal schema change; reversible
- Cons: classification still independently mutable; CHECK rejects updates that drift, which is what we want

### Option C — Hybrid property + DB trigger

Drop persisted `classification`; expose a hybrid property in the ORM derived from `fixed_leg_side`. If queries need to filter by classification, add an index on `fixed_leg_side` and translate at query time.

- Pros: zero drift surface
- Cons: more invasive ORM refactor; existing queries `where classification = 'long'` need rewriting

### Recommendation

**Option A** if Postgres >= 12 (likely) and you confirm SQLAlchemy `Computed` works with the existing `Mapped` ORM pattern. **Option B** otherwise. **Option C** only if you find the existing read path uses `classification` so much that translating queries is cleaner than maintaining the constraint.

Document choice + rationale in PR description.

---

## 4. Files to touch

- `backend/app/models/contracts.py:110-121` — `classification` column definition
- `backend/app/services/contract_service.py:60-78` — verify `create()` no longer needs to write `classification` separately if Option A; minor update if Options B/C
- `backend/app/schemas/contracts.py:57-73` — `HedgeContractRead` should still expose `classification` (it's read-only either way)
- `backend/alembic/versions/<NNNN>_classification_invariant.py` — schema + data migration
- Backfill (Option A or B): scan existing `hedge_contracts` rows for drift; if any are inconsistent, fix per `fixed_leg_side` (canonical source of truth) and log loudly. Document count of fixed rows in migration log.

---

## 5. Scope OUT

- Refactoring the `HedgeLegSide` / `HedgeClassification` enums themselves
- Changing `ContractService.create` derivation logic (it's correct — the bug is downstream persistence)
- Decimal primitives (PR-1)
- Other constitutional fixes

---

## 6. Constitutional rules (binding)

- **§2.3** — "Classification is deterministic … This rule is absolute and non-negotiable." DB-level enforcement is the only way to make "absolute" actually absolute.
- **§2.7** — Auditability requires that any persisted row is reconstructable / consistent.

---

## 7. Acceptance criteria (from jury §3 J-A1-OPUS-04)

- [ ] Database **cannot** store `fixed_leg_side='buy'` with `classification='short'` (or `sell` with `long`). Test attempts a direct SQL INSERT/UPDATE that violates the rule and asserts it fails with constraint error.
- [ ] Test attempts the same via ORM and asserts `IntegrityError` (or equivalent)
- [ ] Existing `ContractService.create` happy-path tests still pass
- [ ] Read models (`HedgeContractRead`) still serialize `classification`
- [ ] Backfill migration: any pre-existing inconsistent rows are detected and either auto-corrected per `fixed_leg_side` (with explicit log) or surfaced as a migration failure for operator review (operator decision; default: auto-correct + log)
- [ ] Migration up/down/up roundtrip clean
- [ ] PR description documents Option chosen + count of backfilled rows (if any)

---

## 8. Test coverage required

- `backend/tests/test_contract_service.py` — extend:
  - Happy path still works
  - Direct SQL UPDATE that drifts → fails
  - ORM update that drifts → fails (raises constraint error)
- Migration test: fixture DB with one inconsistent row → migration detects + auto-corrects + logs (or fails per chosen policy)

---

## 9. Critical sequencing

- **Wave 1, no upstream dependencies.** Runs in parallel with PR-1, PR-2, PR-3.
- No downstream Phase A1 PR depends on this directly.

---

## 10. PR shape

**Title:** `fix(audit-a1): PR-6 — Hedge classification DB invariant (J-A1-OPUS-04)`

**Body skeleton:**

```markdown
## Summary

Make `HedgeContract.classification` derivable-only from `fixed_leg_side`,
removing the drift surface where the two columns can disagree. Phase A1
jury Tier 1 fix per finding J-A1-OPUS-04 (constitutional §2.3, §2.7).

## Invariant strategy chosen
- Option {A / B / C}
- Rationale: <why>

## Files changed
- Models: contracts.py
- Schemas: contracts.py
- Service: contract_service.py (minor)
- Alembic: migration `XXXX_classification_invariant.py`

## Backfill report
- Pre-existing inconsistent rows: N
- Resolution: auto-corrected per `fixed_leg_side` / surfaced for operator
- Log line: `<paste sample log>`

## Acceptance evidence
- Direct SQL drift INSERT fails
- ORM drift UPDATE raises IntegrityError
- Happy-path tests pass

## Out of scope
- Decimal primitives (PR-1)
- ContractService.create logic (already correct; this PR enforces persistence)

## Closes
J-A1-OPUS-04.
```

---

## 11. Constraints

- DO NOT relax the constraint to allow drift "for legacy reasons" — fix the legacy data, don't loosen the rule
- DO NOT make `classification` nullable
- DO NOT silently auto-correct without logging — every backfill correction must be traceable
- DO NOT use `--no-verify`, no force-push, no auto-merge

---

## 12. Workflow

1. `git fetch origin && git checkout -b audit-a1/classification-invariant origin/main`
2. Read jury verdict §3 J-A1-OPUS-04 + Opus F-A1-OPUS-08
3. Verify Postgres version (`SELECT version()`); confirm Option A viability
4. Implement: model → migration (with backfill if needed) → schema/service touchups → tests
5. Run migration locally; capture backfill log
6. `git push -u origin audit-a1/classification-invariant`
7. `gh pr create --base main`
8. **STOP. Wait for Codex review.**
9. Address feedback in new commits

---

## 13. Final report shape

- Branch + PR URL + final SHA
- Invariant option chosen + rationale
- Backfill row count + sample log
- Test results
- Codex verdict

Under 500 words.

Boa caça.
