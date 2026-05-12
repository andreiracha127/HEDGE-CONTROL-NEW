# Phase A6 — Stage 1 Audit Findings (Auditor A / Opus 4.7)

**Phase:** A6 — Frontend Svelte institutional control surface
**Stage:** 1 of 3
**Auditor:** Opus 4.7
**Authoring date:** 2026-05-12
**Repository:** `D:/Projetos/Hedge-Control-New`
**Branch:** `audit-a6/frontend-audit-prompts`
**Governance reference:** `docs/governance.md`
**Scope discipline:** Read-only. No code, test, schema, migration, or
governance edits.

## 0. Method and Verification

Workflow executed per §9 of the dispatch:

1. Read `docs/governance.md` (loaded into context). Binding A6 rules:
   auditability/reconstructability are primary; messages and decision artifacts
   are evidence; no mutation without evidence; no silent fallback; no
   zero-defaults; no date substitution; phases must not be broadened.
2. Derived current frontend surface using `Glob` over
   `frontend-svelte/src/**/*.{ts,svelte,js}` and targeted searches for
   `apiFetch(`, raw `fetch(`, `method:`, `as any`, `bind:value=`, role
   gating.
3. Inspected primary scope files plus all routed pages, both stores, all
   format/sanitize utilities, schema scripts, OpenAPI path inventory, and
   Playwright specs.
4. Each finding below cites file:line and is checked against the current
   commit, not memory of prior PRs.
5. Read-only verification commands **not** executed: `npm run check`,
   `npm test`, `npm run build`, `npm run api:types:check`. The audit
   environment has no backend running, so `api:types:check` cannot fetch
   `/openapi.json`. Stage 2/3 auditors may execute these once a backend is
   reachable.

OpenAPI path inventory used for contract cross-checks is the committed
`docs/api/openapi_v1.json` (60 paths). Where a path is absent from that
document, frontend calls to that path are 404 at runtime under the current
backend contract.

---

## 1. Executive Summary

The Svelte frontend is a thin call-site over a non-trivial backend, but the
A6 audit reveals it is **not currently a faithful institutional control
surface** for the contracts closed in Phases A1–A5. Three categories of
failure dominate:

1. **Endpoint contract drift.** At least five routed pages call HTTP paths
   that do not exist in the committed OpenAPI document
   (`docs/api/openapi_v1.json`). Cashflow, MTM, P&L, contract list, and
   contract status mutation are affected. Operators land on broken pages or,
   worse, mutate the wrong path. (J-A6-OPUS-01 .. 05.)
2. **Silent zero-default fallback on analytics fields.** P&L and MTM pages
   use `(e: any) => e.field ?? e.alt ?? 0`, which substitutes `0` for any
   missing/renamed field. This is a direct breach of the governance hard-fail
   on missing economics. (J-A6-OPUS-06.)
3. **Operator identity is fabricated in mutation bodies.** RFQ
   award/reject/cancel/refresh send `user_id: authStore.userName || 'trader'`.
   When the JWT has no `name` claim the literal string `'trader'` is
   submitted as the actor, corrupting the A5 signed audit trail. The token
   subject is never sent. (J-A6-OPUS-07.)

Secondary findings: the generated OpenAPI types are imported but never used
at call sites (every page uses `apiFetch` over raw strings, defeating the
purpose of the typed client); orders — which generate exposure per the
governance Canonical Economic Model — have no UI; audit history is not
surfaced; the schema-drift check requires a live backend and is not gated in
CI as a hard-fail; the login page only accepts a manually pasted JWT.

Tier 1 (Blocking): 7. Tier 2 (High): 4. Tier 3 (Medium): 3. Tier 4: 0.

---

## 2. Findings

## Finding J-A6-OPUS-01 — Cashflow page calls non-existent endpoints

**Severity:** Tier 1 / Blocking
**Status:** Open
**Evidence:**
- [frontend-svelte/src/routes/(protected)/cashflow/+page.svelte:33-35](frontend-svelte/src/routes/(protected)/cashflow/+page.svelte#L33-L35) —
  page issues parallel GETs to `/cashflow/analytics${qs}`,
  `/cashflow/projections${qs}`, `/cashflow/ledger${qs}`.
- [docs/api/openapi_v1.json](docs/api/openapi_v1.json) — committed contract
  defines `/cashflow/analytic` (singular), `/cashflow/projection` (singular),
  and `/cashflow/ledger`. There is no `/cashflow/analytics` and no
  `/cashflow/projections`.
- [frontend-svelte/src/lib/api/schema.d.ts](frontend-svelte/src/lib/api/schema.d.ts) —
  generated types contain `"/cashflow/analytic"`; the
  `apiFetch(string, init)` helper accepts any string and bypasses these types.

**Failure mode:**
Two of the three cashflow tabs (`analytics`, `projections`) will receive
HTTP 404 under the current backend contract. The page swallows non-2xx into
empty arrays via the early-return pattern, so the operator sees an empty
ledger summary rather than an error. An operator inspecting cashflow status
before settlement or reconciliation receives a silently empty view of
institutional state. This is exactly the "non-2xx as success" anti-pattern
called out in Q3 of the dispatch, and it impairs reconstructability (the
operator cannot tell whether cashflow is empty or whether the page failed).

**Governance impact:**
Hard-fail must be surfaced — "evidence missing, ambiguous dates,
unreconstructible contracts… are hard-fail conditions". An empty render of
two of three tabs is a silent fallback in violation of `docs/governance.md`
§ Governance Hard Fails ("No silent fallback").

**Recommended remediation boundary:**
Rename the three call sites in `cashflow/+page.svelte` to the OpenAPI
canonical paths (`/cashflow/analytic`, `/cashflow/projection`,
`/cashflow/ledger`) **or** change the backend to expose plural aliases —
whichever matches the A3 closed contract. Add a 404→hard-fail branch in
`apiFetch`'s callers for these three tabs at minimum. Do not broaden the
scope into a global refactor of every page in this PR.

---

## Finding J-A6-OPUS-02 — MTM analytics page calls a non-existent endpoint

**Severity:** Tier 1 / Blocking
**Status:** Open
**Evidence:**
- [frontend-svelte/src/routes/(protected)/analytics/mtm/+page.svelte:15](frontend-svelte/src/routes/(protected)/analytics/mtm/+page.svelte#L15) —
  `apiFetch('/mtm/snapshots/latest', { signal })`.
- [docs/api/openapi_v1.json](docs/api/openapi_v1.json) — defines
  `/mtm/snapshots`, `/mtm/hedge-contracts/{contract_id}`,
  `/mtm/orders/{order_id}`. No `/mtm/snapshots/latest` path is published.

**Failure mode:**
MTM page will 404. The page falls back to empty arrays and renders a chart
with no data. Operators cannot distinguish "no MTM snapshot taken today"
from "the page is broken". Closed Phase A3 invariants ("MTM uses D-1
settlement; no fallback pricing regimes") are no longer observable to the
operator at this URL.

**Governance impact:**
`docs/governance.md` § Valuation, MTM & Cashflow — operator must be able to
observe MTM under one methodology per endpoint. An unreachable endpoint
makes that observation impossible.

**Recommended remediation boundary:**
Either query `/mtm/snapshots?limit=1&order=desc` (or whatever filter the A3
endpoint already supports) or add a backend `/mtm/snapshots/latest` alias.
Pick one canonical path and update the page; do not silently retry or fall
back.

---

## Finding J-A6-OPUS-03 — P&L analytics page calls a non-existent endpoint

**Severity:** Tier 1 / Blocking
**Status:** Open
**Evidence:**
- [frontend-svelte/src/routes/(protected)/analytics/pnl/+page.svelte:16](frontend-svelte/src/routes/(protected)/analytics/pnl/+page.svelte#L16) —
  `apiFetch('/pl/snapshot/latest', { signal })`.
- [docs/api/openapi_v1.json](docs/api/openapi_v1.json) — defines
  `/pl/snapshots` (plural) and `/pl/{entity_type}/{entity_id}`. No
  `/pl/snapshot/latest` path exists.

**Failure mode:**
P&L page 404s. The page reads `data.entries`, `data.realized_pnl`,
`data.unrealized_pnl`, and `data.total`; with a 404 body these all evaluate
to `undefined`, which the silent-fallback pattern (J-A6-OPUS-06) converts
into `0`. Operators see a P&L of "R$ 0,00 realized / R$ 0,00 unrealized" —
indistinguishable from a true zero — destroying A3 P&L lifecycle
reconstructability.

**Governance impact:**
`docs/governance.md` § Governance Hard Fails — "Contracts cannot be
reconstructed" is a hard-fail condition. Rendering zero P&L instead of
surfacing the 404 is the textbook silent fallback.

**Recommended remediation boundary:**
Replace with the canonical A3 path (`/pl/snapshots?limit=1` or the
entity-scoped variant) and remove the `?? 0` fallback in the chart-data
projection (see J-A6-OPUS-06).

---

## Finding J-A6-OPUS-04 — Contract list endpoint missing `/hedge/` segment

**Severity:** Tier 1 / Blocking
**Status:** Open
**Evidence:**
- [frontend-svelte/src/routes/(protected)/contracts/+page.svelte:19](frontend-svelte/src/routes/(protected)/contracts/+page.svelte#L19) —
  `apiFetch(\`/contracts?${params}\`, { signal })`.
- [frontend-svelte/src/routes/(protected)/contracts/[id]/+page.svelte:55](frontend-svelte/src/routes/(protected)/contracts/[id]/+page.svelte#L55) —
  `apiFetch(\`/contracts/${contractId}\`, { signal })`.
- [docs/api/openapi_v1.json](docs/api/openapi_v1.json) — only
  `/contracts/hedge`, `/contracts/hedge/{contract_id}`,
  `/contracts/hedge/{contract_id}/archive`,
  `/contracts/hedge/{contract_id}/linkages`,
  `/contracts/hedge/{contract_id}/status` are published. There is no
  `/contracts` index or `/contracts/{contract_id}` endpoint.

**Failure mode:**
The contracts list and contract detail pages both 404 under the committed
contract. Operators cannot view hedge contracts. Per the governance
Canonical Economic Model, hedge contracts are the primary mechanism for
moving Commercial Net Exposure to Global Net — the page that exposes this
state is unreachable.

**Governance impact:**
`docs/governance.md` § Canonical Economic Model — the operator surface must
expose hedge contracts for exposure reconciliation. Q9 (auditability of
operator actions) is breached: an operator cannot reconstruct which hedge
contracts exist before taking award/settle decisions.

**Recommended remediation boundary:**
Update the two call sites to `/contracts/hedge…`. Do not introduce a
client-side "contracts vs hedge contracts" abstraction in this PR.

---

## Finding J-A6-OPUS-05 — Contract status PATCH targets non-existent path

**Severity:** Tier 1 / Blocking
**Status:** Open
**Evidence:**
- [frontend-svelte/src/routes/(protected)/contracts/[id]/+page.svelte:70-72](frontend-svelte/src/routes/(protected)/contracts/[id]/+page.svelte#L70-L72) —
  `apiFetch(\`/contracts/${contractId}/status\`, { method: 'PATCH', body: JSON.stringify({ status: targetStatus }) })`.
- [docs/api/openapi_v1.json](docs/api/openapi_v1.json) — canonical path is
  `/contracts/hedge/{contract_id}/status`.

**Failure mode:**
Operator clicks a status-transition button in the UI (e.g. mark
`partially_settled` or `cancelled`), the call 404s, but the UI optimistic
state may already show success depending on how the page reacts to
non-2xx. Even in the best case the operator believes the action succeeded
when it did not — a misreport of a backend hard-fail as success (Q3
violation) on a state-changing mutation against the A3 lifecycle.

**Governance impact:**
`docs/governance.md` § Governance Hard Fails — "No mutation without
evidence". A 404 on a PATCH presented as ambiguous or successful breaks
mutation evidence integrity.

**Recommended remediation boundary:**
Same fix as J-A6-OPUS-04: prepend `/hedge`. Additionally, confirm the page
reads the response body before showing success; do not show success on
non-2xx.

---

## Finding J-A6-OPUS-06 — Analytics pages substitute zero for missing fields

**Severity:** Tier 1 / Blocking
**Status:** Open
**Evidence:**
- [frontend-svelte/src/routes/(protected)/analytics/pnl/+page.svelte:41](frontend-svelte/src/routes/(protected)/analytics/pnl/+page.svelte#L41) —
  `data: entries.map((e: any) => e.commodity ?? e.label ?? '')`.
- [frontend-svelte/src/routes/(protected)/analytics/pnl/+page.svelte:49](frontend-svelte/src/routes/(protected)/analytics/pnl/+page.svelte#L49) —
  `data: entries.map((e: any) => e.realized_pnl ?? e.realized ?? 0)`.
- [frontend-svelte/src/routes/(protected)/analytics/pnl/+page.svelte:56](frontend-svelte/src/routes/(protected)/analytics/pnl/+page.svelte#L56) —
  `data: entries.map((e: any) => e.unrealized_pnl ?? e.unrealized ?? 0)`.
- [frontend-svelte/src/routes/(protected)/analytics/mtm/+page.svelte:39](frontend-svelte/src/routes/(protected)/analytics/mtm/+page.svelte#L39),
  [:46](frontend-svelte/src/routes/(protected)/analytics/mtm/+page.svelte#L46) —
  `e.date ?? e.snapshot_date ?? e.label ?? ''` and
  `e.mtm_value ?? e.value ?? 0`.

**Failure mode:**
Two compounding violations:

1. `(e: any)` discards the generated OpenAPI types entirely for these
   critical paths. Any backend rename — exactly the kind of A3/A4 evolution
   to expect — silently flips display to `0`.
2. `?? 0` is a zero-default for primary financial values. Governance
   explicitly forbids zero-defaults for missing required economics and
   forbids silent fallback for missing market price.

Combined with the broken endpoints in J-A6-OPUS-02/03, a P&L of literal
`undefined` becomes a displayed P&L of `0`. An operator reading the
dashboard cannot tell "no trades" from "endpoint moved" from "field
renamed".

**Governance impact:**
`docs/governance.md` § Valuation/Projection invariants — "No zero-defaults"
and "No fallback regimes". Same § Governance Hard Fails — "No silent
fallback. No heuristic correction".

**Recommended remediation boundary:**
Drop the `(e: any)` casts; type the response via the generated
`paths['/pl/snapshots']['get']['responses']['200']['content']['application/json']`
or equivalent. If a field is absent, propagate the hard-fail (render an
explicit error card), do not substitute `0` or `''`. Do not introduce a
generic "tolerant analytics renderer"; the rule is strict.

---

## Finding J-A6-OPUS-07 — RFQ mutation `user_id` fabricates operator identity

**Severity:** Tier 1 / Blocking
**Status:** Open
**Evidence:**
- [frontend-svelte/src/lib/stores/auth.svelte.ts:31](frontend-svelte/src/lib/stores/auth.svelte.ts#L31) —
  `readonly userName = $derived(this.#claims?.name ?? this.#claims?.sub ?? '')`.
  When the JWT carries neither `name` nor `sub` the derived value is `''`.
- [frontend-svelte/src/routes/(protected)/rfq/[id]/+page.svelte:116-118](frontend-svelte/src/routes/(protected)/rfq/[id]/+page.svelte#L116-L118) —
  `apiFetch(\`/rfqs/${rfqId}/actions/award\`, { method: 'POST', body: JSON.stringify({ user_id: authStore.userName || 'trader' }) })`.
- Same `user_id: authStore.userName || 'trader'` pattern at
  [:142-144](frontend-svelte/src/routes/(protected)/rfq/[id]/+page.svelte#L142-L144) (reject),
  [:160-162](frontend-svelte/src/routes/(protected)/rfq/[id]/+page.svelte#L160-L162) (cancel),
  [:175-177](frontend-svelte/src/routes/(protected)/rfq/[id]/+page.svelte#L175-L177) (refresh).

**Failure mode:**
The RFQ award/reject/cancel/refresh actions submit a body field `user_id`
derived client-side from a JWT claim, with the literal string `'trader'`
as the fallback. Three discrete failure paths:

1. **Empty-claim → literal `'trader'`.** Any token without a `name` claim
   (the auth store also tries `sub` but a token with neither is possible in
   the existing dev-token format) ends up sending `user_id: 'trader'` for
   every award, regardless of who is logged in. Audit trail records the
   same actor for distinct operators. Closed Phase A5 (signed audit history)
   cannot be reconstructed back to a real user.
2. **`name` is operator-controlled.** The frontend takes the human-readable
   `name` claim and submits it as the canonical actor. A user named "Risk
   Manager — Lucas" becomes the audit identity rather than the immutable
   `sub`/UUID. If a user is renamed, prior audit rows reference a now-stale
   identifier.
3. **Backend trust boundary.** Even if the backend re-derives identity from
   the JWT and ignores `user_id`, sending the field invites future divergence
   and contradicts A2 RFQ canonical-identity discipline ("messages are
   evidence, not UI artifacts").

This is a direct contradiction of the A5 fail-closed guardrails landed in
PR #61 — the audit trail's actor field can be poisoned from the client.

**Governance impact:**
`docs/governance.md` § Governance Hard Fails — "No mutation without
evidence". The mutation is accompanied by an evidence field that is
client-fabricated rather than derived from authenticated identity. § RFQ
System — "Messages are evidence, not UI artifacts" — the `user_id` value is
a UI artifact masquerading as evidence.

**Recommended remediation boundary:**
Stop sending `user_id` from the client for these four endpoints. The backend
must derive the actor from the JWT (sub claim), and the API contract should
not accept a client-supplied `user_id` here. The frontend fix is to remove
the body field; the audit cycle should also check that the backend ignores
the field. If the four endpoints currently *require* `user_id`, this is a
cross-phase deferral to backend (Section 4) and must be fixed before A6
closes.

---

## Finding J-A6-OPUS-08 — Generated OpenAPI types are imported but never enforced at call sites

**Severity:** Tier 2 / High
**Status:** Open
**Evidence:**
- [frontend-svelte/src/lib/api/client.ts:1-7](frontend-svelte/src/lib/api/client.ts#L1-L7) —
  defines a typed `openapi-fetch` `client<paths>(…)` import.
- [frontend-svelte/src/lib/api/fetch.ts:9-24](frontend-svelte/src/lib/api/fetch.ts#L9-L24) —
  exports `apiFetch(path: string, init?: RequestInit): Promise<Response>` —
  accepts any string path and returns an unstructured `Response`.
- Every routed page uses `apiFetch(...)` with a string template literal,
  not `client.GET("/cashflow/analytic", …)`. Grep across
  `frontend-svelte/src/routes` shows zero `client.GET`/`client.POST` calls.
- [frontend-svelte/scripts/check-schema-drift.sh](frontend-svelte/scripts/check-schema-drift.sh) —
  drift detection requires a *running backend* at `${API_BASE_URL}/openapi.json`
  (default `http://localhost:8000`).

**Failure mode:**
The schema-drift safety net is doubly weakened:

- Pages call paths as raw strings; even when `schema.d.ts` is in sync, a
  typo like `/cashflow/analytics` (J-A6-OPUS-01) compiles cleanly.
- `npm run check` and `tsc` cannot catch any of J-A6-OPUS-01..05 because the
  call shape is untyped.
- `api:types:check` and `check-schema-drift.sh` both require a live backend
  serving `/openapi.json` — they cannot run as a pure static CI gate against
  the committed `docs/api/openapi_v1.json`. If CI runs them without a
  backend, they pass vacuously or fail spuriously; either way they do not
  defend against the path mismatches above.

This is precisely the scenario Q8 of the dispatch warns about — drift that
"survives CI or local regeneration".

**Governance impact:**
`docs/governance.md` § Output Contract — outputs must be "precise,
structured, verifiable, audit-friendly". The current call shape is none of
these for the contract surface. § Execution Discipline — A4 closed
"integration trust" but the frontend bypasses the trust mechanism.

**Recommended remediation boundary:**
Two minimum, non-overlapping options (pick one in this PR, do not refactor
the whole codebase):

1. Migrate the five broken call sites (J-A6-OPUS-01..05) to the typed
   `client` helper so the compiler enforces path and body shape, and add an
   ESLint/grep guard that forbids new `apiFetch(<string>)` usages in
   `routes/`.
2. Add a static drift gate that diffs `docs/api/openapi_v1.json` against
   the schema generated from `schema.d.ts` (or equivalent) without requiring
   a running backend, and run it on every PR.

---

## Finding J-A6-OPUS-09 — Order management surface entirely absent

**Severity:** Tier 2 / High
**Status:** Open
**Evidence:**
- `Glob frontend-svelte/src/routes/**/*.svelte` — no `orders` route exists.
- [docs/api/openapi_v1.json](docs/api/openapi_v1.json) — defines `/orders`,
  `/orders/purchase`, `/orders/sales`, `/orders/links`, `/orders/{order_id}`,
  `/orders/{order_id}/archive`.
- `docs/governance.md` § Canonical Economic Model — "Sales Orders (SO)
  generate Commercial Active Exposure / Purchase Orders (PO) generate
  Commercial Passive Exposure" — orders are the *origin* of every exposure
  number the UI displays.

**Failure mode:**
The frontend exposes `Exposures`, `Contracts`, `RFQ`, `Cashflow`, and
analytics views, but provides no way to view, create, archive, or link
orders. An operator can see exposure totals on `/exposures` but cannot drill
into the underlying SO/PO that produced them, nor archive an order, nor
create one. The institutional control surface is incomplete — the upstream
of every exposure number is invisible.

This is not a "missing page" finding rejected by §7 of the dispatch; orders
are a required institutional evidence workflow under governance and they
are unreachable.

**Governance impact:**
`docs/governance.md` § Canonical Economic Model — orders are first-class
exposure-generating primitives that must be reconstructable.

**Recommended remediation boundary:**
Add a read-only orders list + detail route in this wave; defer order
mutations (create/archive/link) to a follow-up wave to keep blast radius
small. The audit cycle should also confirm that the absence is documented
in `docs/audit-protocol/` or roadmap, not silent.

---

## Finding J-A6-OPUS-10 — Audit history is not surfaced in the UI

**Severity:** Tier 2 / High
**Status:** Open
**Evidence:**
- `Glob frontend-svelte/src/routes/**/*.svelte` — no `audit` route, no audit
  panel within RFQ/contract pages.
- [docs/api/openapi_v1.json](docs/api/openapi_v1.json) — defines
  `/audit/events` (list) and `/audit/events/{event_id}/verify`.
- [frontend-svelte/src/lib/stores/auth.svelte.ts:3](frontend-svelte/src/lib/stores/auth.svelte.ts#L3) —
  `UserRole` includes `'auditor'`, implying the role is expected to have a
  workflow.

**Failure mode:**
Phase A5 closed by landing a signed audit trail with HMAC verification
endpoints. The frontend exposes neither the list nor the verification
endpoint. An auditor role exists in the auth store but has no role-specific
landing page or filter — the role is decorative. Reconstructability of
operator actions through the UI (Q9) is not satisfied because the artifact
itself is invisible.

**Governance impact:**
`docs/governance.md` § Institutional Priorities — "auditability" is a
primary optimization target, ranked above UX. A platform that closed A5 but
hides the audit trail from operators violates that ranking.

**Recommended remediation boundary:**
Add a minimal `(protected)/audit/+page.svelte` that lists events with the
A5 filters (entity_type, entity_id, time range) and offers per-row HMAC
verification via `/audit/events/{event_id}/verify`. Gate it to the
`auditor` and `risk_manager` roles. No mutation surface — read-only.

---

## Finding J-A6-OPUS-11 — Login is manual JWT paste with no production flow

**Severity:** Tier 2 / High
**Status:** Open
**Evidence:**
- [frontend-svelte/src/routes/(public)/login/+page.svelte:30](frontend-svelte/src/routes/(public)/login/+page.svelte#L30) —
  copy reads "Cole seu token JWT para acessar a plataforma."
- [:54](frontend-svelte/src/routes/(public)/login/+page.svelte#L54) —
  "Ambiente de desenvolvimento — autenticação via token manual."
- [:19](frontend-svelte/src/routes/(public)/login/+page.svelte#L19) —
  `authStore.login(token.trim())` directly decodes the pasted JWT
  client-side; no backend call to `/auth/login` or equivalent.

**Failure mode:**
There is no production authentication path. Operators must manually obtain a
JWT out-of-band. In Phase A5 the backend gained fail-closed auth, but the
frontend has no flow to acquire a token from an identity provider. In a
production deployment this either (a) blocks all real users, or (b)
encourages operators to share long-lived tokens, defeating session
boundaries. Either way the auth surface is not institutional.

**Governance impact:**
`docs/governance.md` § Institutional Priorities — auditability requires a
real identity behind each mutation. A "paste your token" flow undermines the
A5 fail-closed work.

**Recommended remediation boundary:**
Either (a) keep the manual-paste page only behind an explicit
`VITE_DEV_LOGIN=1` build flag and add a production login form that calls a
backend auth endpoint, or (b) document at the platform-design level that
production auth is delegated to a separate front-door (e.g. a reverse proxy
issuing the JWT). Either way, A6 cannot close with the dev-only paste page
as the only entry point.

---

## Finding J-A6-OPUS-12 — JWT held in `sessionStorage` is reachable by any XSS

**Severity:** Tier 3 / Medium
**Status:** Open
**Evidence:**
- [frontend-svelte/src/lib/stores/auth.svelte.ts:13](frontend-svelte/src/lib/stores/auth.svelte.ts#L13) —
  `const SESSION_TOKEN_KEY = 'hedge-control.auth.token'`.
- [:135-137](frontend-svelte/src/lib/stores/auth.svelte.ts#L135-L137) —
  storage backed by `sessionStorage`.
- [frontend-svelte/src/lib/utils/sanitize.ts](frontend-svelte/src/lib/utils/sanitize.ts) —
  only escapes HTML for chart tooltips; no global CSP, no `{@html}` audit.

**Failure mode:**
Any XSS in any rendered backend string (counterparty name, RFQ comment,
audit event payload) can `sessionStorage.getItem('hedge-control.auth.token')`
and exfiltrate the bearer. The 5-minute warning + auto-logout limits blast
radius but does not eliminate it. This is a localised robustness gap
(Tier 3) under the dispatch taxonomy because the backend enforces
authorization and no concrete XSS sink was located in this audit, but the
combination of operator-controlled fields rendered without DOMPurify and
sessionStorage-backed bearer tokens is a credible operational risk.

**Governance impact:**
`docs/governance.md` § Institutional Priorities — auditability requires
that the bearer of a mutation cannot be forged. A stolen bearer forges the
bearer.

**Recommended remediation boundary:**
Either move the bearer to an HTTP-only cookie + add a CSRF token on
mutating apiFetch calls, or add a strict CSP (`script-src 'self'`) plus an
audit of every `{@html}` site. Out of A6 scope to redesign auth flow;
flagged for cross-phase tracking.

---

## Finding J-A6-OPUS-13 — Playwright suite is smoke-only; no mutation lifecycle assertions

**Severity:** Tier 3 / Medium
**Status:** Open
**Evidence:**
- `frontend-svelte/e2e/rfq-lifecycle.spec.ts` contains four tests, all
  navigation/structure-level: "RFQ board loads and shows list or empty
  state", "navigates to new RFQ form", "RFQ creation form has required
  fields". No `award`, `reject`, `cancel`, or `refresh` assertions; no
  ranking display assertion; no quote handling.
- `frontend-svelte/e2e/contracts.spec.ts` — list loads, status buttons are
  visible for trader. No actual PATCH assertion (which would have caught
  J-A6-OPUS-05).
- No unit tests for `apiFetch` URL composition, no unit tests for analytics
  page response handling, no Playwright test exercising the `?? 0` fallback.

**Failure mode:**
Endpoint mismatches J-A6-OPUS-01..05 and the `user_id` poisoning of
J-A6-OPUS-07 are all behaviours that an honest E2E run against a real
backend would surface. The current suite passes regardless. The suite
covers only invariants that production code already enforces (route
existence, form field presence), which is the case `§7 anti-finding` rules
out only when "production code makes the failure impossible" — but here
production code does *not* make the failure impossible.

**Governance impact:**
`docs/governance.md` § Output Contract — "verifiable". The current tests
do not verify the institutional surface.

**Recommended remediation boundary:**
Add at least three Playwright assertions: (1) a successful RFQ award flow
that asserts the POST URL and body via `page.route(...)`; (2) a contract
status PATCH that asserts the URL; (3) a cashflow page load that asserts
the three GET URLs. Do not attempt full coverage in this PR.

---

## Finding J-A6-OPUS-14 — Quantity in MT submitted as JavaScript `number`

**Severity:** Tier 3 / Medium
**Status:** Open
**Evidence:**
- [frontend-svelte/src/routes/(protected)/rfq/new/+page.svelte:180](frontend-svelte/src/routes/(protected)/rfq/new/+page.svelte#L180) —
  `bind:value={quantityMt}` on `<input type="number" step="0.01">`.
- [:118-120](frontend-svelte/src/routes/(protected)/rfq/new/+page.svelte#L118-L120) —
  the bound value is `JSON.stringify`d into the `/rfqs` body.
- [frontend-svelte/src/lib/utils/format.ts:74-77](frontend-svelte/src/lib/utils/format.ts#L74-L77) —
  display side uses `formatQuantityMT` with 3-decimal NUMERIC(_, 3) string
  arithmetic, indicating quantity is treated as NUMERIC(_, 3) backend-side.

**Failure mode:**
`bind:value` on `<input type="number">` parses to JS `number` (IEEE 754).
For institutional quantities up to ~10⁹ MT this is safe, but the form
allows two-decimal precision while the backend stores three. A user typing
`12345678.987` will see the third decimal silently dropped by the input's
`step="0.01"` (browser-dependent), then submit a `number` that is rounded by
the JSON encoder. The mismatch is a Tier 3 finding because the most likely
production trip is loss of precision, not corruption — but it is a
quantity-direction-units risk per Q4.

**Governance impact:**
`docs/governance.md` § Canonical Economic Model — quantity is always in MT.
Implicit silent rounding at the input is a determinism gap.

**Recommended remediation boundary:**
Either set `step="0.001"` on the quantity input and submit via a
string-typed body field, or document a single canonical quantity precision
(2 or 3 decimals) used by both UI and backend, and assert it in a unit test.
Do not silently coerce.

---

## 3. Anti-findings considered

The following items were inspected and rejected as findings:

- **Raw `fetch(` bypassing `apiFetch`.** None found outside
  `fetch.ts:17` (the centralized wrapper itself). Anti-finding: no
  evidence of bypass.
- **`(row: any)` in `DataTable.svelte:22`.** This is a generic component
  receiving arbitrary row shapes by design; rejected per §7 ("a raw `any`
  cast unless it masks a concrete contract or state failure").
- **WebSocket auth via first-message `authenticate`.** Inspected
  `ws.svelte.ts:55-61`. Events are dispatched only after `auth_ack`
  (line 160), and re-subscriptions are flushed on reconnect (lines
  171-178). No race producing stale-event delivery was located; rejected.
- **Frontend role-gating in `what-if/+page.svelte:10` (risk_manager,
  auditor) and `market-data` ingest button.** Per §7, "client-side role
  gating as a security issue by itself when the backend enforces
  authorization correctly" is not a finding. Rejected — no evidence that
  the backend trusts the UI gate.
- **`Number(`, `parseFloat`, `parseInt`, `toFixed` usage.** Searched.
  Only `toFixed(1)` for percentage display on hedge ratio
  (`exposures/+page.svelte:141`) and `step="0.01"` numeric inputs. Display
  formatting is unaffected by these (display goes through
  `formatDecimalString` with BigInt). Rejected at the display layer.
- **`escapeHtml` in `sanitize.ts`.** Used in chart tooltip formatters per
  the file's own comment. No `{@html}` site discovered that bypasses it.
  Rejected as a localized concern; flagged as part of J-A6-OPUS-12.
- **Missing E2E for login.** `login.spec.ts` exercises both happy and
  unhappy paths. Rejected.

## 4. Cross-phase deferrals

- **Backend acceptance of client-supplied `user_id` in `/rfqs/{id}/actions/*`
  bodies (J-A6-OPUS-07).** If the backend currently requires the field,
  the canonical fix is backend-side (derive actor from JWT, reject the
  body field). Defer the backend half to a Phase A5 cleanup or A6 backend
  paired PR; the frontend half (stop sending the field) is in A6 scope.
- **Production identity provider (J-A6-OPUS-11).** Selecting and wiring an
  IdP is a platform decision beyond A6 frontend scope. Defer the IdP
  choice; the build-flag gating is in scope.
- **Bearer storage redesign (J-A6-OPUS-12).** HTTP-only cookie + CSRF is a
  cross-stack change. Defer to a dedicated security phase; only the
  inventory/audit of `{@html}` and the CSP header are in A6 scope.

## 5. Recommended remediation waves

To preserve small blast radius per A6 discipline:

**Wave 1 — Endpoint contract repair (Tier 1)**
- J-A6-OPUS-01 cashflow path renames
- J-A6-OPUS-02 MTM path
- J-A6-OPUS-03 P&L path
- J-A6-OPUS-04 contracts list/detail `/hedge/` prefix
- J-A6-OPUS-05 contract status PATCH `/hedge/` prefix

Single PR, file-scoped to the five route pages. Add E2E URL assertions for
each (from Wave 3) before merge.

**Wave 2 — Evidence integrity (Tier 1)**
- J-A6-OPUS-06 remove `(e: any)` and `?? 0` from analytics pages
- J-A6-OPUS-07 stop sending `user_id` from RFQ action calls (paired with
  backend confirmation from §4 deferral)

Single PR. Tightly scoped to RFQ detail + analytics.

**Wave 3 — Surface completeness and contract enforcement (Tier 2)**
- J-A6-OPUS-08 typed-client migration for the five Wave 1 endpoints +
  ESLint guard, OR a static drift check against the committed
  `openapi_v1.json`
- J-A6-OPUS-09 read-only orders route
- J-A6-OPUS-10 read-only audit history route
- J-A6-OPUS-11 build-flag gate on dev-only login

Can be split into smaller PRs by route.

**Wave 4 — Operational hardening (Tier 3)**
- J-A6-OPUS-12 CSP + `{@html}` audit
- J-A6-OPUS-13 Playwright URL-assertion tests
- J-A6-OPUS-14 quantity precision alignment

---

## 6. Commands attempted / not attempted

| Command | Status | Note |
|---|---|---|
| `npm run check` | not run | Audit env has no installed deps verified; deferred to Stage 2/3 |
| `npm test` | not run | Same as above |
| `npm run build` | not run | Same as above |
| `npm run api:types:check` | not runnable | Requires live backend at `${API_BASE_URL}/openapi.json` per `regen-schema.mjs` |
| `npm run test:e2e` | not run | Requires backend per `playwright.config.ts` |

All findings above are derived from direct code inspection of the committed
tree and cross-referenced against committed `docs/api/openapi_v1.json`.

---

**End of report.**
