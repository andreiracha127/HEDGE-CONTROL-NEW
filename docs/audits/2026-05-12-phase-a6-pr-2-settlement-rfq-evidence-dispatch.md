# Phase A6 Remediation Dispatch - PR-A6-2 Settlement and RFQ Evidence Integrity

**Phase:** A6 - Frontend Svelte institutional control surface
**Wave:** PR-A6-2
**Authoring date:** 2026-05-12
**Repository:** `D:/Projetos/Hedge-Control-New`
**Base branch:** `main`
**Required branch:** `audit-a6/settlement-rfq-evidence-integrity`
**Source verdict:** `docs/audits/2026-05-12-phase-a6-jury-verdict.md`

## 1. Objective

Close:

- `J-A6-02` - Do not expose settlement as a generic contract status patch.
- `J-A6-04` - Stop fabricating RFQ actor identity in frontend mutation bodies.
- `J-A6-12` - Parse RFQ quotes and state-event responses exactly once.

This wave protects lifecycle evidence around settlement and RFQ decisions. It
must remove frontend paths that can create misleading settlement or actor
evidence and must make RFQ detail evidence loading deterministic.

## 2. Non-Negotiable Constraints

- Do not edit `docs/governance.md`.
- Do not implement PR-A6-1 endpoint repair broadly, except to integrate with
  already-merged path fixes.
- Do not keep "settle" as a generic status patch.
- Do not fabricate a fallback actor such as `trader`, display name, or empty
  string for RFQ mutation evidence.
- Do not read a `Response` body twice.
- Do not broaden into backend actor-derivation unless explicitly chosen,
  tested, and kept within this wave. The default boundary is frontend-only.

Settlement and RFQ actions are institutional decisions. The UI must not create
false evidence about who acted or how a lifecycle transition occurred.

## 3. Findings and Evidence

### J-A6-02 - Settlement exposed as generic status patch

Accepted evidence:

- `frontend-svelte/src/routes/(protected)/contracts/[id]/+page.svelte:17`
  allows `active` to transition to `settled`.
- `frontend-svelte/src/routes/(protected)/contracts/[id]/+page.svelte:35`
  labels that transition as `Liquidar`.
- `frontend-svelte/src/routes/(protected)/contracts/[id]/+page.svelte:70`
  sends `{ status: targetStatus }` through the status endpoint.
- `docs/api/openapi_v1.json:7472` defines the canonical ledger settlement
  endpoint `/cashflow/contracts/{contract_id}/settle`.
- `docs/api/openapi_v1.json:3050` shows `HedgeContractSettlementCreate`
  requires `source_event_id`, `cashflow_date`, and `legs`.
- `backend/app/services/cashflow_ledger_service.py:265` creates settlement
  evidence.
- `backend/app/services/contract_service.py:277` status patch mutates only
  `contract.status`.

### J-A6-04 - Fabricated RFQ actor identity

Accepted evidence:

- `frontend-svelte/src/lib/stores/auth.svelte.ts:31` exposes `userName` as
  `name ?? sub`.
- `frontend-svelte/src/routes/(protected)/rfq/new/+page.svelte:111` sends
  `user_id: authStore.userName || 'trader'`.
- `frontend-svelte/src/routes/(protected)/rfq/[id]/+page.svelte:118` sends
  that fallback on award.
- `frontend-svelte/src/routes/(protected)/rfq/[id]/+page.svelte:144` sends it
  on reject.
- `frontend-svelte/src/routes/(protected)/rfq/[id]/+page.svelte:162` sends it
  on cancel.
- `frontend-svelte/src/routes/(protected)/rfq/[id]/+page.svelte:177` sends it
  on refresh.
- Current generated schemas require client-provided `user_id`.

### J-A6-12 - Double response-body parse

Accepted evidence:

- `frontend-svelte/src/routes/(protected)/rfq/[id]/+page.svelte:68` can call
  `quotesRes.json()` twice.
- `frontend-svelte/src/routes/(protected)/rfq/[id]/+page.svelte:69` can call
  `eventsRes.json()` twice.
- `backend/app/api/routes/rfqs.py:222` returns `list[RFQQuoteRead]`.
- `backend/app/api/routes/rfqs.py:243` returns `list[RFQStateEventRead]`.

## 4. Required Implementation Boundary

### Settlement UI

Default remediation:

- remove `settled` and `partially_settled` from generic contract status
  transition controls;
- keep status-only actions only for lifecycle transitions that are valid as
  status-only transitions;
- show a clear non-mutating message or disabled action if settlement requires a
  future ledger settlement UI.

Alternative remediation:

- implement a complete settlement modal that calls
  `/cashflow/contracts/{contract_id}/settle` with `source_event_id`,
  `cashflow_date`, and `legs`;
- prove the payload is complete and does not use the generic status patch.

Do not implement a partial settlement form that fabricates legs or source
events. If the ledger payload cannot be collected correctly, remove the button
instead.

### RFQ Actor Identity

Minimum acceptable frontend behavior:

- remove every `|| 'trader'` actor fallback;
- add an immutable subject accessor in `authStore` if needed, based on JWT
  `sub`, not display `name`;
- if the current backend still requires `user_id`, send immutable `sub`;
- if no `sub` is available, block the mutation and show an explicit auth error;
- do not use `authStore.userName` for evidence fields.

If the executor chooses the stronger backend contract fix, it must derive actor
identity from authenticated JWT claims server-side and update schemas/OpenAPI.
That is allowed only if kept narrow and fully tested. Otherwise leave backend
actor derivation as the documented cross-phase deferral.

### RFQ Detail Response Parsing

Parse each response once:

```ts
if (!quotesRes.ok) {
  const errorBody = await quotesRes.json().catch(() => null);
  quoteError =
    typeof errorBody?.detail === 'string'
      ? errorBody.detail
      : 'Failed to load RFQ quotes';
  return;
}
const quoteBody = await quotesRes.json();
quotes = Array.isArray(quoteBody) ? quoteBody : (quoteBody.items ?? []);
```

Apply the same pattern to state events. Handle non-2xx with explicit error
state; do not assign `[]` on backend failure and do not replace existing quote
or timeline evidence unless a successful response has been parsed.

## 5. Acceptance Criteria

- No frontend generic status action can mark a contract `settled` or
  `partially_settled`.
- If settlement is exposed, it calls `/cashflow/contracts/{contract_id}/settle`
  with the required ledger payload.
- No frontend RFQ create/award/reject/cancel/refresh body contains
  `authStore.userName || 'trader'` or any literal actor fallback.
- RFQ actor payloads use immutable `sub` or the backend derives identity from
  auth; missing identity hard-fails visibly.
- RFQ quote and state-event response bodies are parsed once.
- RFQ detail works with array responses from `/quotes` and `/state-events`.
- RFQ detail preserves existing quotes and state events on non-2xx evidence
  reload failure while surfacing the backend error.
- `docs/governance.md` has no diff.

## 6. Required Tests

Add or update focused frontend tests.

Minimum coverage:

- contract detail does not render generic `Liquidar` status transition unless a
  ledger settlement flow is implemented;
- settlement action, if present, calls `/cashflow/contracts/{contract_id}/settle`
  and never `/contracts/hedge/{contract_id}/status` for settlement;
- RFQ create/action bodies do not contain literal `trader`;
- RFQ create/action bodies use immutable `sub` when current schema requires
  `user_id`;
- missing `sub` blocks RFQ mutation with an explicit auth error;
- RFQ detail loads quotes and state events when backend returns arrays;
- RFQ detail non-2xx quote/state-event reload shows an error and does not clear
  existing quotes or timeline entries;
- response bodies are not parsed twice in the tested RFQ detail flow.

## 7. Required Verification

Run, at minimum:

```bash
cd frontend-svelte
npm run check
npm test
npm run build
```

Also run and report:

```bash
rg -n "user_id: authStore\\.userName|\\|\\| 'trader'|\\|\\| \"trader\"|quotesRes\\.json\\(\\).*quotesRes\\.json|eventsRes\\.json\\(\\).*eventsRes\\.json|settled|partially_settled|transitionStatus" frontend-svelte/src/routes frontend-svelte/src/lib
git diff --check
```

If backend schema/OpenAPI is changed for actor derivation, also run the backend
focused tests and regenerate frontend schema/types as required by the repo.

## 8. Out of Scope

- General endpoint path cleanup. That is PR-A6-1.
- P&L/MTM/market-data numeric display. That is PR-A6-3.
- Orders/audit read pages and production login. That is PR-A6-4.
- Full IAM redesign.
- Full settlement accounting redesign beyond the canonical endpoint already in
  the backend.

## 9. PR Requirements

- Use branch `audit-a6/settlement-rfq-evidence-integrity`.
- Push normally; do not use `--no-verify`.
- Open a PR against `main`.
- Include in the PR body:
  - findings closed;
  - files changed;
  - tests run and results;
  - actor identity decision;
  - settlement UI decision;
  - hook artifact path;
  - statement that `docs/governance.md` has no diff.
