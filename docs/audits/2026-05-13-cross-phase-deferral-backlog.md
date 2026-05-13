# Cross-Phase Deferral Backlog — Consolidated Inventory

**Compiled:** 2026-05-13 (post-Phase-A6 closure)
**Status of mandatory audits:** A1, A2, A3, A4, A5, A6 all closed.
**Total open deferrals:** 11 across 4 thematic clusters.

This document inventories every cross-phase deferral recorded by the jury verdicts of Phases A1–A6 that remains open after the six mandatory audit cycles closed. Each deferral links back to its source jury verdict, names the constitutional rule it touches, and records the future-audit verification criterion the jury wrote down.

---

## Cluster 1 — A1 follow-up (deal-engine + exposure + scenario boundaries)

Four findings cluster around the deal-level P&L path, soft-delete lifecycle, and scenario-vs-live exposure semantics. The A1 jury accepted these as Tier 3 (deferrable). The A3 jury added two cross-phase deferrals against the same surfaces. Together they form a single coherent A1 follow-up audit scope.

### D-1.1 — Soft-deleted deals can retain invisible DealLink ownership
- **Source:** A1 jury — J-A1-OPUS-07 (Tier 3)
- **Constitutional rule:** §2.7
- **Files:** `backend/app/models/deal.py:80-99`, `backend/app/services/deal_engine.py:261-280`, `backend/app/services/deal_engine.py:722-734`
- **Future-audit verification:** test covers linking an entity after its prior parent deal is deleted/archived; DB constraints and service checks agree on deleted-deal semantics.

### D-1.2 — Exposure soft-delete can create duplicate source snapshots
- **Source:** A1 jury — J-A1-OPUS-08 (Tier 3)
- **Constitutional rule:** §2.1
- **Files:** `backend/app/models/exposure.py:88-97`, `backend/app/services/exposure_engine.py:85-119`
- **Future-audit verification:** soft-delete contract for `Exposure` rows; uniqueness reconciliation across soft-deleted + live state.

### D-1.3 — Deal Engine repair path reuses prior snapshot price references
- **Source:** A3 jury — X-A3-J-01 (cross-phase deferred from A3)
- **Defer to:** Phase A1 / deal P&L follow-up
- **A3 surface:** Gemini J-A3-04 (A3 price-hard-fail policy)
- **Files:** `backend/app/services/deal_engine.py:657-703`
- **Mechanism (jury note):** `deal_engine.py` and `DealPNLSnapshot` are pre-existing deal-level P&L path, not in the Phase A3 target services. The code intentionally searches reusable snapshots when all live price quotes are unavailable, then recomputes the hash against persisted price references before returning.
- **Future-audit verification:** whether total price unavailability may legitimately reuse a sealed snapshot, or whether `PriceReferenceUnprovable` must always propagate even when a stored hash matches.

### D-1.4 — Scenario duplicates A1 exposure aggregation logic
- **Source:** A3 jury — X-A3-J-02 (cross-phase deferred from A3)
- **Defer to:** Phase A1/A3 integration remediation
- **A3 surface:** Opus J-A3-14
- **Files:** `backend/app/services/scenario_whatif_service.py:222-433`
- **Mechanism (jury note):** scenario must run over virtual deltas, so the duplication is not automatically a valuation hard-fail. The durable risk is cross-phase drift from A1 exposure semantics.
- **Future-audit verification:** extraction of shared pure exposure-calculation primitives usable by both live exposure and scenario what-if paths.

**Cluster 1 cohesion:** all four touch the same model layer (`Deal`, `DealLink`, `Exposure`, `DealPNLSnapshot`) and would be audited against the same constitutional sections (§2.1, §2.7) by the same reviewer pairing. Single follow-up audit cycle is the natural shape.

---

## Cluster 2 — Backend hardening (closes A6 dual-layer slices)

Two findings from the A6 jury that the frontend remediation closed only at the frontend boundary. The backend slice is required to make the protection unbypassable.

### D-2.1 — Backend RFQ actor derivation from JWT
- **Source:** A6 jury — cross-phase deferral (closes J-A6-04 backend slice)
- **A6 frontend slice:** PR #65 sent immutable JWT `sub` as `user_id` body field instead of fabricating identity from the mutable display name.
- **Backend gap:** RFQ mutation endpoints still accept a client-supplied `user_id` body field and consume it verbatim. A non-frontend caller can submit any identity.
- **Canonical fix:** derive actor identity from authenticated JWT claims server-side; remove `user_id` from RFQ mutation request bodies; reject requests that supply the field.
- **Files:** `backend/app/api/routes/rfq*.py`, `backend/app/services/rfq_service.py`, `backend/app/schemas/rfq.py` (request schemas).

### D-2.2 — Backend status endpoint refuses generic settled patch
- **Source:** A6 jury — cross-phase deferral (closes J-A6-02 backend slice)
- **A6 frontend slice:** PR #64 removed `settled` and `partially_settled` from frontend `VALID_TRANSITIONS` + added defence-in-depth refusal in `transitionStatus()`.
- **Backend gap:** `/contracts/hedge/{contract_id}/status` still accepts and applies `settled` server-side. A non-frontend caller can settle without ledger evidence.
- **Canonical fix:** backend status endpoint rejects `settled` / `partially_settled` as terminal transitions and forces settlement through `/cashflow/contracts/{contract_id}/settle` with canonical `HedgeContractSettlementCreate` payload (`source_event_id`, `cashflow_date`, `legs`).
- **Files:** `backend/app/api/routes/contracts*.py`, `backend/app/services/contracts_service.py`.

**Cluster 2 cohesion:** both are backend-only patches against existing endpoints; both close A6 jury findings; both need the same kind of fail-closed contract test. Smallest scope, fastest wave to close. The natural shape is a single audit-trail dispatch covering both endpoints together.

---

## Cluster 3 — Security / Platform

Three findings tied to the deployment-time identity / token / authorization story. These were explicitly scoped out of the mandatory audit cycles because they require infrastructure choices, not code changes against current services.

### D-3.1 — Broader IAM design beyond `APP_ENV` / `ENVIRONMENT` startup mismatch
- **Source:** A5 jury — cross-phase deferral
- **A5 closed slice:** PR #61 (J-A5-06) — auth fail-closed on canonical `APP_ENV`; rejects anonymous access on production/staging.
- **Gap:** A5 only canonicalized the startup-time env-var mismatch and the production fail-closed gate. The broader IAM model — RBAC matrix, role-claim provisioning, scope-vs-role distinction, service-account boundaries — is undefined.
- **Future-audit verification:** documented authorization matrix per route × role; per-role acceptance/rejection tests for every mutating endpoint; service-account identity contract.

### D-3.2 — Production identity provider selection
- **Source:** A6 jury — cross-phase deferral
- **A6 closed slice:** PR #67 (J-A6-10) gated the dev paste-token flow behind `runtimeFlags.manualTokenLoginEnabled` with three reason codes; production builds hard-fail config error and refuse submission.
- **Gap:** the production login flow itself is undefined. Auth0/Cognito/Azure-AD/reverse-proxy/SAML/OIDC — none are chosen, configured, or wired.
- **Future-audit verification:** chosen IdP integrated end-to-end with role/scope claims that match the canonical RBAC matrix from D-3.1.

### D-3.3 — Token storage hardening
- **Source:** A6 jury — cross-phase deferral (rejected J-A6-OPUS-12 as scope-out for A6, recorded as platform deferral)
- **Gap:** JWT held in `sessionStorage` is reachable by any XSS sink in the SPA. Full hardening requires HTTP-only secure cookies, CSRF token rotation, Content-Security-Policy header set, and a full XSS-sink inventory across the SPA.
- **Future-audit verification:** session secret never reachable via DOM/JS; CSRF rotates on session lifecycle; CSP rejects inline scripts and unknown origins; XSS-sink inventory documents every `innerHTML`, `eval`, `setAttribute('href'|'src')`, and dynamic-import call.

**Cluster 3 cohesion:** all three depend on platform choices (IdP, cookie domain, CSP origin allow-list). Sequence: D-3.1 (RBAC matrix) → D-3.2 (IdP selection) → D-3.3 (token storage). The three cannot be remediated in parallel by independent waves; they share a single architectural decision tree.

---

## Cluster 4 — Data ingestion governance

### D-4.1 — Market-data governance beyond signed evidence
- **Source:** A5 jury — cross-phase deferral
- **A5 closed slice:** PR-A5-2 (J-A5-05) added a non-HTTP signed audit API for worker mutations including the Westmetall ingest path.
- **Gap:** the broader market-data ingest contract — provider-trust matrix, replay-window invariants, cross-provider canonical price reconciliation, stale-feed detection, ingest-vs-display precision contract — is undefined beyond the per-mutation signed evidence already in place.
- **Future-audit verification:** documented trust matrix for every market-data provider; replay-window enforced at ingest; canonical price reconciliation across providers; stale-feed alerts; precision contract from raw bytes through `formatPrice(price_usd, 'USD/MT')` end-to-end.

**Cluster 4 cohesion:** single finding, but scope is wide enough to support its own audit cycle if priority warrants. Otherwise it can be folded into a future "ingestion + LLM" cluster.

---

## Cross-cluster sequencing notes

1. **Clusters 1 and 2 are remediation work**, not platform work. Both can be executed against the existing service set without new infrastructure decisions. Both will produce closeable jury findings via the standard 3-stage audit cycle protocol.

2. **Cluster 3 is platform work.** It cannot be executed without first answering: "Which IdP?" and "Which cookie domain / CSP origin?". These are decisions for Andrei, not for the audit cycle. Once decided, the cluster will produce a single integration phase (not a jury audit cycle).

3. **Cluster 4 is intermediate.** It is data-ingestion hardening that could either be executed as a standalone audit cycle (if Westmetall + future providers warrant a dedicated phase) or folded into a wider "external systems + LLM" follow-up.

4. **Closed deferral chains (no work required):**
   - Phase A2 → A4 (X-A2-J-01, X-A2-J-02, X-A2-J-03) — explicitly absorbed by A4 jury (verdict `## Cross-Phase Deferrals` reads "None").
   - Phase A5 → A6 frontend visibility — closed by A6 PR #67 (`/audit` route, `/orders` route).

---

## Recommended first frente (post-A6)

**Start with Cluster 2 (backend hardening).** Rationale:

- **Smallest scope, highest closure density.** Two backend-only patches that each unbypass a current A6 frontend-only slice. No new infrastructure decisions.
- **Closes audit-cycle dual-layer debt.** PR #64 and PR #65 carry explicit "frontend slice; backend slice deferred" language. Closing the backend slice retires the deferral cleanly and restores the institutional invariant that no jury finding has a permanent half-fix.
- **Validates the dual-layer remediation pattern.** A6 was the first phase to surface dual-layer remediations as a recurring shape. Closing Cluster 2 verifies the pattern in production and feeds back into the dispatch template for future phases.
- **Cheapest to dispatch.** No new adversarial pairing needed; the existing A6 jury verdict already cited the canonical fix direction for both findings. A single dispatch can drive a single backend PR that closes both D-2.1 and D-2.2.

**After Cluster 2, recommend Cluster 1 (A1 follow-up audit cycle)** as a full 3-stage adversarial audit with newer pairings — four deferrals across deal-engine / exposure / scenario warrants the full institutional protocol.

**Cluster 3 (platform / IAM) and Cluster 4 (market-data governance) wait** until Andrei chooses the IdP/cookie/provider model — they are decision-blocked, not work-blocked.
