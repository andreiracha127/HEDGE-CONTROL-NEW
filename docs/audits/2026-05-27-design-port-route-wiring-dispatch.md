# Design Port — Route Wiring & Production Promotion Dispatch

Cycle: Frontend identity replacement (Alcast Hedge design tool handoff)
Wave: DESIGN-PORT-1 (single, exhaustive)
Constitutional anchor: `docs/systemconstitucion.md` §"Frontend is a presenter only" + `docs/governance.md` "AUTHORIZATION MATRIX" §"trader/risk_manager/auditor visibility" (already binding, NOT modified by this PR)
Source design: `design-prototypes/hedge-control/` (verbatim handoff bundle from Claude Design, archived in repo)
Foundation already merged: `frontend-svelte/src/routes/preview/*` (18 routes, mocked data) — proof of concept landed in branch `codex/rfq-create-institutional-ui` HEAD `84d640361`
Findings closed by this wave: none (forward-looking initiative, not a jury finding)
Status: READY

---

## §1 Scope

This dispatch prescribes the implementation contract for the executor PR that will promote the `alcast-design` system from the `/preview/*` staging route family into the production `(protected)/*` route family, replacing the existing dark `bg-surface-*` Tailwind theme as the authoritative frontend identity for Hedge Control Platform.

The executor PR will land, in a single Git commit graph (multiple commits allowed; single PR per Andrei's binding decision 2026-05-27): (a) move the `.alcast-design` CSS layer from `frontend-svelte/src/lib/styles/alcast-design.css` (scoped wrapper) to the canonical global stylesheet at `frontend-svelte/src/app.css` (delete the dark token block, keep the `@import 'tailwindcss'` directive plus a stripped `@theme { --font-sans, --font-mono }` block — Tailwind utilities remain available for the few non-alcast surfaces, but no dark `--color-surface-*` ladder); (b) collapse the `.alcast-design` wrapper class — promote its rules to apply on `body` directly so every page in the app inherits the sober institutional identity without per-route opt-in; (c) replace the existing root `frontend-svelte/src/routes/+layout.svelte` (the one with the dark `bg-surface-900` sidebar at lines 82-138) with an authentication-aware AppShell wrapper that delegates layout chrome to `frontend-svelte/src/lib/components/alcast/AppShell.svelte` while preserving the Clerk session-expiry banner, notifications toast container, and WebSocket lifecycle `$effect`; (d) move every Svelte page file under `frontend-svelte/src/routes/preview/*` into its sibling `frontend-svelte/src/routes/(protected)/*` location, overwriting the existing dark-theme content — see §4.4 binding table; (e) ship a typed `+page.ts` `load()` function per route that calls the existing openapi-fetch typed client at `frontend-svelte/src/lib/api/client.ts` against the backend endpoints catalogued in `frontend-svelte/src/lib/api/schema.d.ts`, replacing every import of mock data from `$lib/alcast/mock` in production pages — see §4.5 binding endpoint map; (f) wire form submissions on the three new-entity pages (`rfq/new`, `orders/new`, `counterparties/new`) to the existing POST endpoints, with success → SvelteKit `goto()` and failure → `notifications.add({ type: 'error', ... })` per the no-silent-fallback rule; (g) wire navigation badges in `Sidebar.svelte` (the `'24'`/`'3'`/`'2'` hardcoded counts at `Sidebar.svelte:23-37`) to real counts threaded through the root layout's `load()` so they reflect actual RFQ open / Orders today / Approvals pending; (h) wire AppShell's footer-name + footer-role + topbar Tweaks panel to `authStore.userName` and `authStore.userRoles` from `frontend-svelte/src/lib/stores/auth.svelte`, replacing the hardcoded "Andrei Rachadel · Risk manager" string at `Sidebar.svelte:81-82` and the dummy "Homologação" env badge at `Topbar.svelte:25` (the env badge instead reads `import.meta.env.MODE` mapped to "Produção" | "Homologação" | "Desenvolvimento"); (i) DELETE the `frontend-svelte/src/routes/preview/` directory tree entirely after the move (post-promotion the duplicated content would lint as dead code); (j) DELETE `frontend-svelte/src/lib/alcast/mock.ts` from production source (move its content into `frontend-svelte/tests/fixtures/alcast-mock-fixtures.ts` for Playwright/vitest fixture use only — the production routes MUST NOT import any symbol from this fixture file at runtime); (k) DELETE the legacy layout components under `frontend-svelte/src/lib/components/layout/` (the `StatusBar.svelte` at `frontend-svelte/src/lib/components/layout/StatusBar.svelte:1-31` is the only file there and references dark Tailwind tokens — confirmed unused after AppShell replaces it); (l) UPDATE the existing Playwright E2E suites under `frontend-svelte/e2e/*` to use the new alcast-design selectors (`.kpi`, `.tbl`, `.sb-item`, `.badge.pos`, etc.) in place of the dark `bg-surface-900` / `text-accent` selectors — full per-spec audit prescribed in §7.

This dispatch is documentation-only — no code change lands via the PR shipping this file. The executor PR is the next task in the orchestrator's design-port sequence and starts after this dispatch PR merges (per `feedback_dispatch_self_consistency` — code PRs follow dispatch PRs in separate executor sessions).

## §2 Boundary

This PR does NOT:

- Introduce any new backend endpoint, schema field, ORM column, alembic migration, RBAC rule, or governance clause. The full set of endpoints consumed by the new pages already exists in `frontend-svelte/src/lib/api/schema.d.ts` (verified by `grep -cE "^\s*['\"]/" frontend-svelte/src/lib/api/schema.d.ts` returning 82 paths); the executor MUST regenerate `schema.d.ts` only if the backend `/openapi.json` is unchanged (drift gate `npm run api:types:check` is REQUIRED to pass; if it fails, fix the cause in source and regenerate via `npm run api:types`, do NOT hand-edit `schema.d.ts`).
- Modify any backend file. The dispatch's scope is strictly under `frontend-svelte/`. Touching `backend/app/**` or `backend/alembic/versions/**` is OUT OF SCOPE and would be flagged by `rbac-matrix-auditor` / `constitution-compliance-reviewer` subagents per `.claude/agents/`. If the executor discovers a frontend integration that requires a backend change (missing endpoint, mis-shaped response, lack of expected field), the executor MUST stop, document the gap, and request a follow-up backend PR — do NOT patch around with frontend-side data massage or float computation.
- Compute economics on the frontend. Per `docs/systemconstitucion.md`, backend is authoritative for economics; frontend is a presenter only. The new pages display server-computed `notional`, `mtm`, `pnl_realized`, `pnl_unrealized`, `coverage_ratio`, `exposure_residual_mt` values verbatim — no `qty * price` multiplication in `+page.svelte` or `+page.ts`. The few places where the prototype DID compute display values (e.g. `pages-trading.jsx:Best price × rfq.qty` for the "Notional (melhor)" cell at `/preview/rfq/[id]`, `pages-finance.jsx:c.amount_usd * 5.124` for the BRL column in `/preview/cashflow`) are mocked-data presentation only — in production those derived values MUST come from server response fields (`rfq.notional_usd_at_best`, `cashflow_entry.amount_brl`); if a field is absent from the backend response, the cell MUST render `—` and the executor MUST file a backend-gap follow-up, NOT recompute with a hardcoded FX rate.
- Add `toFixed()`, `parseFloat()`, or `Number()` coercion on Decimal-typed financial values. The existing helpers at `frontend-svelte/src/lib/utils/format.ts` (`formatQuantityMT`, `formatUSD`, etc.) are the only allowed display path for monetary and tonnage quantities. The dispatch §4.4 explicitly requires that prototype-era `.toLocaleString('en-US', { minimumFractionDigits: 2 })` calls on raw number literals get replaced with `formatUSD(value)` / `formatBRL(value)` calls. New pages MUST NOT invent local formatters.
- Add `process.env`, `import.meta.env` outside of `client.ts` baseUrl and the `env-badge` mode-string. Per `docs/runbook-railway.md` the VITE_* envvar surface is owned by Railway dashboard; the executor MUST NOT introduce new VITE_* vars in this PR.
- Migrate the legacy SAP UI5 frontend under `frontend/`. CLAUDE.md is explicit: "Legacy SAP UI5 frontend, deprecated. Do not extend it." The dispatch does NOT touch `frontend/` (Webapp routes, SAPUI5 controllers, etc.). The SAPUI5 deprecation timeline is a separate operational decision and is OUT OF SCOPE here.
- Add new institutional roles, JWT claim shapes, or Clerk identity provisioning steps. The AppShell consumes the existing `authStore` exactly as the legacy root layout does. The hardcoded "Andrei Rachadel · Risk manager" string replacement uses the EXISTING `authStore.userName` and `authStore.userRoles` accessors — no new accessors are added.
- Modify the existing CSRF double-submit cookie pattern. The new mutation submissions (POST /rfqs, POST /counterparties, POST /orders/purchase, POST /orders/sales, POST /workflow-approvals/{id}/grant, etc.) go through the existing `client.use()` middleware at `frontend-svelte/src/lib/api/client.ts:17-25` which already injects `X-CSRF-Token` from `authStore.getCsrfToken()`. The executor MUST NOT inject CSRF tokens manually in form handlers; the openapi-fetch middleware handles it transparently.
- Modify CSP. The CSP report-only ramp lives at `frontend-svelte/nginx.conf` and is unchanged. The new pages use NO inline scripts (every `<script>` block is in `<script lang="ts">` blocks compiled by Vite, not runtime-injected) and NO inline `style=` attributes with `expression(...)` or `javascript:` URLs. The prototype's inline `style="..."` attributes (used heavily across the 18 ported pages) are static CSS strings and are CSP-compatible under `style-src 'self' 'unsafe-inline'`.
- Introduce the Tweaks panel in the production identity. Per Andrei's design tool transcript ("Trader desk variants are a design-review affordance, not a production feature"), the `TweaksPanel.svelte` MUST be excluded from the production layout. The executor MUST NOT mount `<TweaksPanel/>` inside the new `+layout.svelte`. The component file itself can remain in `frontend-svelte/src/lib/components/alcast/TweaksPanel.svelte` as inert code (it's only ~280 lines), OR be deleted along with `alcastTweaks.svelte.ts` store — executor's choice based on whether they want to preserve the design-review affordance for future Tweaks-only review routes. If preserved, the `data-density` / `data-theme` / `data-nav` attributes on the design root MUST default to `regular`/`default`/`expanded` exactly (no localStorage-persisted user customization in production).
- Add a feature flag for the design rollout. Per Andrei's binding decision 2026-05-27 ("Deletar imediatamente"), the legacy dark theme is removed in this same PR with no fallback toggle. The executor MUST NOT introduce a `VITE_DESIGN_VERSION=alcast|legacy` env var or `?design=...` query-param escape hatch.
- Carry `mock.ts` data into production builds. After the move, `$lib/alcast/mock` MUST be unreachable from any file under `frontend-svelte/src/routes/(protected)/*` AND from any file under `frontend-svelte/src/lib/components/alcast/*` (the components consume props only, never import mock). The dispatch §4.4 binds: every `import { ... } from '$lib/alcast/mock'` line in the ported pages becomes either deleted (if the import was used only for display labels — push the labels into the component itself) or replaced with the corresponding load-function-derived `data.X` reference.

## §3 Pre-step (manual)

Empty for the code PR itself. The executor's branch opens against current main HEAD (`84d640361` post-design-port-foundation-merge — confirm by `git log -1 --pretty=%H main`) and runs without infrastructure changes.

Three operational pre-conditions exist for the executor's local dev loop, NOT for the PR's scope:

1. **Backend running on `:8000`**: the `+page.ts` load functions hit `import.meta.env.VITE_API_BASE_URL ?? 'http://localhost:8000'`. For local dev, `cd backend && uvicorn app.main:app --reload` must be running before `npm run dev` so that `load()` can fetch real data. If the executor runs `npm run check` (which doesn't execute load functions) or `npm run build` (which can SSR with empty data in dev), the backend is not required. CI runs against the docker-compose stack which DOES start backend (see `.github/workflows/ci.yml` E2E job).

2. **Postgres + minimum seed data**: the executor's local dev requires at least one RFQ, one Order, one Contract, one Counterparty in the DB so that list-page render isn't empty. The existing `backend/scripts/dev_seed.py` (verify path; if absent, the executor uses `docker compose exec backend python -m app.seed_dev` or the equivalent for the docker stack — out of scope to author a new seeder in this PR).

3. **Clerk dev tenant configured**: per `docs/dev-setup.md`, `VITE_CLERK_PUBLISHABLE_KEY` and `JWKS_URL` must be set in `frontend-svelte/.env` (frontend) and `backend/.env` (backend) respectively. The new AppShell delegates to the same Clerk init pattern as the legacy layout — no new keys required.

## §4 Frontend changes

### §4.1 `frontend-svelte/src/app.css` — global identity replacement

Replace the entire current file content (50 lines, dark Tailwind theme) with a unified file that: (a) keeps the `@import 'tailwindcss';` directive at line 1 (Tailwind preflight + utilities remain available); (b) keeps a stripped `@theme` block declaring ONLY `--font-sans: 'IBM Plex Sans', system-ui, -apple-system, sans-serif;` and `--font-mono: 'IBM Plex Mono', 'Fira Code', monospace;` (drop every `--color-surface-*`, `--color-accent*`, `--color-gold`, `--color-teal*`, `--color-success*`, `--color-danger*`, `--color-warning*`, `--color-blue` token — they are unused after the alcast promotion); (c) deletes the `:root { color-scheme: dark; }` block (the new design is light-default); (d) deletes the `body { @apply bg-surface-950 text-surface-200 ... }` block; (e) deletes the `* { @apply leading-tight; }` rule (alcast-design has its own line-height set on `body`); (f) INLINES the full content of `frontend-svelte/src/lib/styles/alcast-design.css` (currently scoped under `.alcast-design`) with one structural change: every `.alcast-design` selector becomes `body` (for the rules that set background, font, color, etc.) or is dropped entirely (for the rules that only need to be inside the design surface, since now the entire app IS that surface). The `:root[data-density="..."]`, `:root[data-theme="..."]`, `:root[data-nav="..."]` selectors from the prototype CSS — which were rewritten to `.alcast-design[data-density="..."]` in the staging port — must be REMOVED entirely (Tweaks panel is OUT of production per §2).

After this rewrite, the `frontend-svelte/src/lib/styles/alcast-design.css` source file is DELETED — the canonical location is now `frontend-svelte/src/app.css`. The CSS data-URL fragments for the `.select` dropdown arrow are preserved verbatim (they don't reference any prototype-only identifier).

The executor MUST verify post-rewrite that `npm run build` produces zero CSS warnings about undefined Tailwind tokens — the `@apply bg-surface-950` and similar utility classes used in 20 legacy files will be removed in §4.4 along with the page rewrites, but the executor MUST land the page rewrites and the CSS rewrite IN THE SAME PR to avoid a transient build-broken state.

### §4.2 `frontend-svelte/src/routes/+layout.svelte` — root shell replacement

Replace the entire current file content (173 lines) with a new shell that preserves the institutional invariants (auth init, WebSocket lifecycle, session expiry banner, notifications toast container) while delegating layout chrome to `AppShell.svelte`. The new file's `<script lang="ts">` block contains:

```svelte
<script lang="ts">
	import '../app.css';
	import { authStore } from '$lib/stores/auth.svelte';
	import { wsStore } from '$lib/stores/ws.svelte';
	import { notifications, type Notification } from '$lib/stores/notifications.svelte';
	import { page } from '$app/state';
	import { clerk, initClerk } from '$lib/clerk';
	import AppShell from '$lib/components/alcast/AppShell.svelte';

	let { children, data } = $props();

	$effect(() => {
		if (authStore.isAuthenticated) {
			wsStore.connect();
			void initClerk().catch(() => {
				/* Restored cookie sessions can render before Clerk loads; refresh remains best-effort. */
			});
		} else {
			wsStore.disconnect();
		}
	});

	async function logout() {
		wsStore.disconnect();
		try {
			await initClerk();
			await clerk.signOut();
		} catch {
			/* Local logout must not depend on Clerk CDN availability. */
		} finally {
			authStore.logout();
		}
	}

	function typeColor(type: Notification['type']): string {
		if (type === 'success') return 'badge pos';
		if (type === 'error') return 'badge neg';
		if (type === 'warning') return 'badge warn';
		return 'badge info';
	}

	const crumbs = $derived(crumbsFor(page.url.pathname));
	const navBadges = $derived(data?.navBadges ?? { rfqOpen: null, ordersToday: null, approvalsPending: null });

	function crumbsFor(pathname: string): string[] {
		/* full mapping table — see §4.3 binding */
	}
</script>

{#if authStore.isAuthenticated}
	<AppShell {crumbs} {navBadges} userName={authStore.userName} userRoles={authStore.userRoles} onLogout={logout}>
		{@render children()}
	</AppShell>
{:else}
	{@render children()}
{/if}

{#if authStore.showExpiryWarning}
	<div class="env-badge neg" style="position: fixed; top: 0; left: 0; right: 0; z-index: 50; text-align: center; padding: 8px;">
		Sessão expira em breve — faça login novamente para continuar.
		<button onclick={logout} class="btn-link" style="margin-left: 8px;">Renovar agora</button>
	</div>
{/if}

<div style="position: fixed; bottom: 16px; right: 16px; z-index: 50; display: flex; flex-direction: column; gap: 8px;">
	{#each notifications.items as notification (notification.id)}
		<div class={typeColor(notification.type)} style="padding: 10px 14px; box-shadow: var(--sh-pop);">
			{notification.message}
			<button onclick={() => notifications.remove(notification.id)} class="btn-ghost btn-sm" style="margin-left: 8px;">✕</button>
		</div>
	{/each}
</div>
```

Two structural deltas from the legacy file:

- The dark sidebar nav (lines 82-138 of the current file) is GONE. `AppShell` provides its own sidebar via `Sidebar.svelte`. The `navItems` derived array, `sidebarCollapsed` state, `isActive(href)` helper, `wsStatusDot(status)` helper are all DELETED in this rewrite — they have no replacement; AppShell handles its own active-route logic via `$app/state.page`.
- The toast and expiry-banner markup is rewritten to use alcast `.badge` / `.env-badge` semantic classes instead of Tailwind `bg-success/90 text-white`. The TS handler `typeColor` returns a className string usable directly by alcast CSS.

The executor MUST add `+layout.ts` (sibling file) that fetches the nav-badge counts in a single batched call:

```ts
// frontend-svelte/src/routes/+layout.ts
import { client } from '$lib/api/client';

export const load = async () => {
	const [rfqs, orders, approvals] = await Promise.allSettled([
		client.GET('/rfqs', { params: { query: { state: 'SENT,QUOTED', limit: 1 } } }),
		client.GET('/orders', { params: { query: { traded_on: 'today', limit: 1 } } }),
		client.GET('/workflow-approvals', { params: { query: { state: 'pending', limit: 1 } } }),
	]);
	const safeCount = (r: PromiseSettledResult<{ data?: { total?: number } | null }>): number | null =>
		r.status === 'fulfilled' && r.value.data ? r.value.data.total ?? null : null;
	return {
		navBadges: {
			rfqOpen:           safeCount(rfqs),
			ordersToday:       safeCount(orders),
			approvalsPending:  safeCount(approvals),
		},
	};
};
```

The executor MUST verify each `query` parameter against `frontend-svelte/src/lib/api/schema.d.ts` before committing — the prescribed `state: 'SENT,QUOTED'` and `traded_on: 'today'` and `state: 'pending'` shapes are EXAMPLES; if the actual backend `/rfqs`, `/orders`, `/workflow-approvals` GET endpoints don't accept those exact parameter names, the executor uses the closest available filter (`/rfqs?state=SENT` repeated for QUOTED, or post-fetch filter on the client). Whatever pattern is chosen, the load function MUST NOT throw on partial failure (use `Promise.allSettled` not `Promise.all`) — a backend hiccup on one endpoint cannot block the entire layout from rendering. Failed endpoints surface as `null` badges, which Sidebar renders as no-badge.

### §4.3 `Sidebar.svelte` + `Topbar.svelte` + `AppShell.svelte` — adapt to real data

Update `frontend-svelte/src/lib/components/alcast/Sidebar.svelte` to consume real nav-badge counts via props instead of the hardcoded `'24'`/`'3'`/`'2'` literals:

- Add `navBadges` prop typed as `{ rfqOpen: number | null; ordersToday: number | null; approvalsPending: number | null }`.
- Replace the literal `badge: '24'` at the `orders` NAV entry with `badge: navBadges.ordersToday !== null ? String(navBadges.ordersToday) : null`.
- Replace the literal `badge: '3'` at the `rfq` NAV entry with `badge: navBadges.rfqOpen !== null ? String(navBadges.rfqOpen) : null`.
- Replace the literal `badge: '2'` at the `approvals` NAV entry with `badge: navBadges.approvalsPending !== null ? String(navBadges.approvalsPending) : null`.
- Add `userName` and `userRoles` props typed `string` and `string[]`, replacing the hardcoded `'Andrei Rachadel'` and `'Risk manager'` at the `.sb-foot` block. The role display picks the highest-privilege role from the array using the precedence `auditor > risk_manager > trader > unknown` (institutional ordering already binding via `docs/governance.md` AUTHORIZATION MATRIX).
- Add `onLogout: () => void | Promise<void>` prop; wire it to a new "Sair" button at the bottom of `.sb-foot` (replace the current avatar-only block with avatar + name + small "Sair" link).
- All NAV entry `href` attributes change from `/preview/...` to `/...` (the route paths after promotion — `/preview/exposures` → `/exposures`, etc.). Full table in §4.4.

Update `frontend-svelte/src/lib/components/alcast/Topbar.svelte`:

- Replace the hardcoded `<span class="env-badge">Homologação</span>` at line 25 with a dynamic env badge based on `import.meta.env.MODE` (Vite default — `'production'` | `'development'` | `'test'`) plus a Railway-environment fallback if available. Map: `mode === 'production'` → `Produção` (with `.env-badge.prod` modifier for the red-tinted variant); `mode === 'development'` → `Desenvolvimento`; anything else → `Homologação`. The mode string is read at module top-level once (no runtime reactivity needed).
- The search input is non-functional in this PR — leave the placeholder text but the input MUST be disabled (`disabled` attribute) with a tooltip-style title `"Busca global disponível na próxima wave"` to signal it's a known gap, not a bug.

Update `frontend-svelte/src/lib/components/alcast/AppShell.svelte`:

- Add props matching the new layout interface: `crumbs: string[]`, `navBadges: { ... }`, `userName: string`, `userRoles: string[]`, `onLogout: () => void | Promise<void>`.
- Pass `navBadges`, `userName`, `userRoles`, `onLogout` to the embedded `<Sidebar>`.
- Pass `crumbs` to the embedded `<Topbar>` (already present, no change).
- Remove the data-attributes `data-density={tweaks.density}` / `data-theme={tweaks.theme}` / `data-nav={tweaks.nav}` from the AppShell root `<div>` — per §2 the Tweaks panel is OUT of production, so the tweaks store is unused. The root div becomes `<div class="app">` only (without the `alcast-design` wrapper, since CSS is now global on body).
- Delete the import of `tweaks` from `$lib/stores/alcastTweaks.svelte`. Delete the unused store file `$lib/stores/alcastTweaks.svelte.ts` (and `frontend-svelte/src/lib/components/alcast/TweaksPanel.svelte` if Andrei confirms — flag this as an executor-judgment call; default is to delete both since the prototype-era Tweaks affordance has no production purpose).

### §4.4 Route move table — `/preview/*` → `(protected)/*`

Every file in the table below is MOVED (`git mv`) from the staging route family to the production route family. The destination file OVERWRITES the existing (protected) page; the source file is deleted as a result of `git mv`. The mock-data load function and any data-shape adapter prescribed in §4.5 is added in the destination location. The route group `(protected)` (in parens) is an existing SvelteKit route-group; the move does NOT create new route groups.

| Source (delete after move)                                                                   | Destination (overwrites existing)                                                                          | Old (protected) file action |
|----------------------------------------------------------------------------------------------|------------------------------------------------------------------------------------------------------------|-----------------------------|
| `frontend-svelte/src/routes/preview/+layout@.svelte`                                          | (none — layout consolidates into the new root `+layout.svelte` per §4.2)                                   | n/a                         |
| `frontend-svelte/src/routes/preview/+page.svelte`                                             | `frontend-svelte/src/routes/(protected)/+page.svelte`                                                       | overwrite (30 lines → ~210) |
| `frontend-svelte/src/routes/preview/exposures/+page.svelte`                                   | `frontend-svelte/src/routes/(protected)/exposures/+page.svelte`                                             | overwrite                   |
| `frontend-svelte/src/routes/preview/orders/+page.svelte`                                      | `frontend-svelte/src/routes/(protected)/orders/+page.svelte`                                                | overwrite                   |
| `frontend-svelte/src/routes/preview/orders/new/+page.svelte`                                  | `frontend-svelte/src/routes/(protected)/orders/new/+page.svelte`                                            | new dir, new file           |
| `frontend-svelte/src/routes/preview/rfq/+page.svelte`                                         | `frontend-svelte/src/routes/(protected)/rfq/+page.svelte`                                                   | overwrite                   |
| `frontend-svelte/src/routes/preview/rfq/new/+page.svelte`                                     | `frontend-svelte/src/routes/(protected)/rfq/new/+page.svelte`                                               | overwrite                   |
| `frontend-svelte/src/routes/preview/rfq/[id]/+page.svelte`                                    | `frontend-svelte/src/routes/(protected)/rfq/[id]/+page.svelte`                                              | overwrite                   |
| `frontend-svelte/src/routes/preview/contracts/+page.svelte`                                   | `frontend-svelte/src/routes/(protected)/contracts/+page.svelte`                                             | overwrite                   |
| `frontend-svelte/src/routes/preview/contracts/[id]/+page.svelte`                              | `frontend-svelte/src/routes/(protected)/contracts/[id]/+page.svelte`                                        | overwrite                   |
| `frontend-svelte/src/routes/preview/counterparties/+page.svelte`                              | `frontend-svelte/src/routes/(protected)/counterparties/+page.svelte`                                        | overwrite                   |
| `frontend-svelte/src/routes/preview/counterparties/new/+page.svelte`                          | `frontend-svelte/src/routes/(protected)/counterparties/new/+page.svelte`                                    | overwrite                   |
| `frontend-svelte/src/routes/preview/counterparties/[id]/+page.svelte`                         | `frontend-svelte/src/routes/(protected)/counterparties/[id]/+page.svelte`                                   | overwrite                   |
| `frontend-svelte/src/routes/preview/cashflow/+page.svelte`                                    | `frontend-svelte/src/routes/(protected)/cashflow/+page.svelte`                                              | overwrite                   |
| `frontend-svelte/src/routes/preview/pnl/+page.svelte`                                         | `frontend-svelte/src/routes/(protected)/analytics/pnl/+page.svelte`                                         | overwrite (path differs!)   |
| `frontend-svelte/src/routes/preview/mtm/+page.svelte`                                         | `frontend-svelte/src/routes/(protected)/analytics/mtm/+page.svelte`                                         | overwrite (path differs!)   |
| `frontend-svelte/src/routes/preview/market/+page.svelte`                                      | `frontend-svelte/src/routes/(protected)/market-data/+page.svelte`                                           | overwrite (path differs!)   |
| `frontend-svelte/src/routes/preview/approvals/+page.svelte`                                   | `frontend-svelte/src/routes/(protected)/workflow-approvals/+page.svelte`                                    | overwrite (path differs!)   |
| `frontend-svelte/src/routes/preview/audit/+page.svelte`                                       | `frontend-svelte/src/routes/(protected)/audit/+page.svelte`                                                 | overwrite                   |

Path-difference call-outs (existing protected route paths take precedence — the executor MUST update `Sidebar.svelte` NAV entries to match):

- P&L: legacy `/analytics/pnl`, new alcast Sidebar has `/preview/pnl` — Sidebar entry MUST change to `/analytics/pnl`.
- MTM: legacy `/analytics/mtm`, alcast Sidebar has `/preview/mtm` — Sidebar entry MUST change to `/analytics/mtm`.
- Market data: legacy `/market-data`, alcast Sidebar has `/preview/market` — Sidebar entry MUST change to `/market-data`.
- Approvals: legacy `/workflow-approvals`, alcast Sidebar has `/preview/approvals` — Sidebar entry MUST change to `/workflow-approvals`.

The executor MUST also delete the legacy `frontend-svelte/src/routes/(protected)/analytics/+layout.svelte` and `frontend-svelte/src/routes/(protected)/analytics/what-if/+page.svelte` (the second is a separate scenario route not covered by the new design family — flag this with Andrei: option A delete it (assume what-if is dead), option B carry it forward (still mock data via `apiFetch('/scenario/what-if/run')` line 22 of original file)). DEFAULT is to PRESERVE `what-if` as-is, marked as "design-deferred" inline comment at the top of the file — it's the only legacy page surviving the cleanup, since it has no alcast equivalent. Sidebar gets a new entry under `Análise` group: `{ key: 'whatif', label: 'What-if', icon: 'bolt', badge: null, href: '/analytics/what-if' }` placed after `mtm`.

After all moves, `git rm -r frontend-svelte/src/routes/preview/` removes the now-empty source tree.

After all moves, the executor MUST sweep `frontend-svelte/src/routes/(protected)/` for any leftover dark-theme files: `analytics/+layout.svelte` (if it references `bg-surface-*`), `+layout.svelte` (a possible (protected)-only child layout — at the time of dispatch authoring, only the root `+layout.svelte` is referenced as the source of the dark sidebar). `grep -rln "bg-surface-\|text-accent\|text-surface" frontend-svelte/src/routes/(protected)` AFTER the rewrite MUST return ZERO matches.

### §4.5 Real API binding — per-route `+page.ts` load functions

Each ported page gets a sibling `+page.ts` (or `+page.server.ts` if the route should be SSR-only — defer SSR/CSR choice to executor based on whether the endpoint requires the user's JWT; default CSR via `+page.ts` since auth happens via Clerk cookie). The load function calls the typed openapi-fetch `client` from `frontend-svelte/src/lib/api/client.ts` and returns a flat data shape that the matching `+page.svelte` consumes via `let { data } = $props();`.

The binding endpoint map. Endpoints listed are verified against `frontend-svelte/src/lib/api/schema.d.ts` (the 82-path catalog from `grep -E "^\s*['\"]/" frontend-svelte/src/lib/api/schema.d.ts`):

| Route                                                | Load endpoint(s)                                                                                                                                                                                          |
|------------------------------------------------------|-----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------|
| `(protected)/+page.svelte` (Dashboard)               | `GET /exposures/global`, `GET /pl/snapshots?limit=1`, `GET /rfqs?state=SENT,QUOTED&limit=5`, `GET /market-data/westmetall/aluminum/cash-settlement/prices?limit=2`                                          |
| `(protected)/exposures/+page.svelte`                 | `GET /exposures/list?limit=200`, `GET /exposures/net`, `GET /exposures/tasks`, `GET /exposures/reconcile`                                                                                                  |
| `(protected)/orders/+page.svelte`                    | `GET /orders?limit=200` with query params for tab filter (`status=filled` etc.)                                                                                                                            |
| `(protected)/orders/new/+page.svelte`                | load: `GET /counterparties?limit=200` (for the select dropdown) · submit: `POST /orders/purchase` (if `orderType === 'PO'`) OR `POST /orders/sales` (if `orderType === 'SO'`)                              |
| `(protected)/rfq/+page.svelte`                       | `GET /rfqs?limit=200` with query params for tab filter (`state=QUOTED` etc.)                                                                                                                               |
| `(protected)/rfq/new/+page.svelte`                   | load: `GET /counterparties?limit=200` · submit: `POST /rfqs` with body shape matching the existing RFQ creation request schema (per `schema.d.ts` `paths['/rfqs']['post']['requestBody']`)                  |
| `(protected)/rfq/[id]/+page.svelte`                  | `GET /rfqs/{rfq_id}`, `GET /rfqs/{rfq_id}/quotes`, `GET /rfqs/{rfq_id}/ranking`, `GET /rfqs/{rfq_id}/state-events`                                                                                          |
| `(protected)/contracts/+page.svelte`                 | `GET /contracts/hedge?limit=200` with query params for tab filter (`status=active` etc.)                                                                                                                   |
| `(protected)/contracts/[id]/+page.svelte`            | `GET /contracts/hedge/{contract_id}`, `GET /contracts/hedge/{contract_id}/linkages`, `GET /mtm/hedge-contracts/{contract_id}`, `GET /cashflow/ledger/hedge-contracts/{contract_id}`                          |
| `(protected)/counterparties/+page.svelte`            | `GET /counterparties?limit=200`                                                                                                                                                                            |
| `(protected)/counterparties/new/+page.svelte`        | (no load) · submit: `POST /counterparties`                                                                                                                                                                 |
| `(protected)/counterparties/[id]/+page.svelte`       | `GET /counterparties/{counterparty_id}`, `GET /contracts/hedge?counterparty_short={id}` (or the equivalent filter the schema accepts — verify against schema.d.ts before committing)                        |
| `(protected)/cashflow/+page.svelte`                  | `GET /cashflow/analytic`, `GET /cashflow/projection`, `GET /cashflow/ledger?limit=200`                                                                                                                     |
| `(protected)/analytics/pnl/+page.svelte`             | `GET /pl/snapshots?limit=30` (last 30 days), `GET /deals/pnl-breakdown`                                                                                                                                    |
| `(protected)/analytics/mtm/+page.svelte`             | `GET /mtm/snapshots?limit=200`, plus `GET /contracts/hedge?limit=200` for the marcação table                                                                                                                |
| `(protected)/market-data/+page.svelte`               | `GET /market-data/westmetall/aluminum/cash-settlement/prices?limit=90`                                                                                                                                     |
| `(protected)/workflow-approvals/+page.svelte`        | `GET /workflow-approvals?state=pending&limit=50`                                                                                                                                                           |
| `(protected)/audit/+page.svelte`                     | `GET /audit/events?limit=200` (auditor role only — the page MUST render an inline notice if `authStore.userRoles` lacks `'auditor'`, NOT silently fall back to mock data)                                  |

Each `+page.ts` MUST follow this exact pattern (this is a canonical template; the executor adapts the endpoint and shape per route):

```ts
// frontend-svelte/src/routes/(protected)/rfq/+page.ts
import type { PageLoad } from './$types';
import { client } from '$lib/api/client';
import { error } from '@sveltejs/kit';

export const load: PageLoad = async ({ url }) => {
	const tab = url.searchParams.get('tab') ?? 'all';
	const params = tab === 'all'
		? { query: { limit: 200 } }
		: { query: { state: tab, limit: 200 } };
	const { data, error: apiError } = await client.GET('/rfqs', { params });
	if (apiError) throw error(502, 'Failed to load RFQs');
	return {
		rfqs: data?.items ?? [],
		total: data?.total ?? 0,
		tab,
	};
};
```

Three binding rules for every load function:

1. **No silent fallback**: if `apiError` is truthy, `throw error(status, message)` from `@sveltejs/kit`. The SvelteKit `+error.svelte` (existing file `frontend-svelte/src/routes/+error.svelte` — verify it exists at PR time, if not the executor adds one alongside) catches and surfaces the error. Returning empty `{ rfqs: [] }` on apiError is a P1 governance violation (silent fallback).

2. **No client-side recomputation**: the load function returns the server response shape verbatim. The page component uses `data.rfqs[i].notional_usd_at_best` directly. If a field is absent from the server response, the page renders `—` for that cell. The executor MUST NOT add a `notional = qty * price` calculation in the load function or the page component.

3. **No mock-data import in production routes**: every `+page.ts` MUST NOT import from `$lib/alcast/mock`. The original ported pages (under `/preview/*`) DID import mock data; the executor's job is to replace every `import { rfqs, contracts, counterparties, ... } from '$lib/alcast/mock'` line in the destination `+page.svelte` with the corresponding `data.rfqs`, `data.contracts`, etc. from `let { data } = $props();`. After the rewrite, `grep -rln "from '\\\$lib/alcast/mock'" frontend-svelte/src/routes` MUST return ZERO matches.

### §4.6 Form submission handlers — three new-entity pages

The three new-entity pages currently have button click handlers that do nothing (the prototype was display-only). The executor adds real submission logic. The pattern is identical across the three; below is the template for `rfq/new/+page.svelte`:

```svelte
<script lang="ts">
	import { goto } from '$app/navigation';
	import { client } from '$lib/api/client';
	import { notifications } from '$lib/stores/notifications.svelte';

	let submitting = $state(false);
	let { data } = $props();
	const counterparties = data.counterparties; // from +page.ts load

	async function submit() {
		submitting = true;
		const { data: created, error: apiError } = await client.POST('/rfqs', {
			body: {
				company,
				commodity,
				intent,
				trade_type: tradeType,
				quantity_mt: Number(quantity),
				legs: showLeg2 ? [leg1, leg2] : [leg1],
				counterparty_shorts: cps,
				/* order_id is conditional on intent === 'COMMERCIAL_HEDGE' */
				...(intent === 'COMMERCIAL_HEDGE' && orderId ? { order_id: orderId } : {}),
				...(intent === 'SPREAD' && buyTradeId && sellTradeId ? { buy_trade_id: buyTradeId, sell_trade_id: sellTradeId } : {}),
			},
		});
		submitting = false;
		if (apiError) {
			notifications.add({ type: 'error', message: `Falha ao enviar RFQ: ${apiError.detail ?? 'erro desconhecido'}` });
			return;
		}
		notifications.add({ type: 'success', message: `RFQ ${created?.id} enviada a ${cps.length} contraparte(s)` });
		await goto(`/rfq/${created?.id}`);
	}
</script>

<!-- ... -->
<button type="button" class="btn btn-primary" onclick={submit} disabled={submitting || cps.length === 0 || !leg1.priceType}>
	<Icon name="bolt"/>{submitting ? 'Enviando…' : `Enviar a ${cps.length} contraparte${cps.length === 1 ? '' : 's'}`}
</button>
```

The body shape `{ company, commodity, intent, trade_type, quantity_mt, legs, counterparty_shorts, ... }` is the EXAMPLE shape — the executor MUST verify the actual request body shape against `frontend-svelte/src/lib/api/schema.d.ts`'s `paths['/rfqs']['post']['requestBody']['content']['application/json']` definition AND adapt the form's state shape to match. If the existing backend `POST /rfqs` body schema does NOT accept `counterparty_shorts` and instead expects `counterparty_ids: string[]`, the executor adapts (either by name or by re-mapping `short` → `id` via the loaded counterparties list). DO NOT invent body fields; if the backend schema diverges from what the form needs, file a backend-gap follow-up per §2.

Same pattern for `counterparties/new` (`POST /counterparties`) and `orders/new` (`POST /orders/purchase` or `POST /orders/sales` depending on `orderType`). All three pages MUST set `disabled={submitting}` on the submit button and disable form fields while in-flight to prevent double-submission.

### §4.7 Decimal precision in display — replace prototype's `toLocaleString` with `formatUSD`/`formatBRL`

The existing helpers at `frontend-svelte/src/lib/utils/format.ts` are the canonical display path. The dispatch §2 binding rule is: every `.toLocaleString('en-US', { minimumFractionDigits: 2 })` or `.toFixed(2)` call on a financial value in the ported pages MUST be replaced with the matching helper. Specifically (full catalog, audit by `grep -rn "toLocaleString\|toFixed" frontend-svelte/src/routes/(protected)` after the move):

- USD amounts (P&L, MTM, notional, prices): use `formatUSD(n)` if exists, otherwise add a new helper to `format.ts` named `formatUSDPlain(n)` returning `'US$ ' + n.toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 })` (this MUST be added to the shared helper, not inlined per page).
- BRL amounts: `formatBRL(n)` analogous shape.
- Tonnage (`MT`): `formatQuantityMT(n)` — already exists.
- Percentages with 1 decimal: `formatPct1(n)` — add if not present.
- USD/BRL prices (4 digits): `formatFxRate(n)` — add if not present.
- Commodity prices with 2 digits (`2.645,50` style): `formatCommodityPrice(n, commodity)` — add helper that picks 4 digits for `USDBRL`, 2 digits otherwise.

The mock-data file's local `fmtUSD`, `fmtBRL`, `fmtMT`, `fmtPct`, `fmtNum` helpers (at `frontend-svelte/src/lib/alcast/mock.ts:226-243`) are MOVED to `format.ts` as named exports and the call sites in the ported pages update accordingly. After the move, the mock file's helper exports are deleted (the fixtures-only copy under `tests/fixtures/` does NOT need them — fixtures use raw numbers).

### §4.8 Mock file relocation to fixtures

`frontend-svelte/src/lib/alcast/mock.ts` (current location, ~260 lines) is MOVED to `frontend-svelte/tests/fixtures/alcast-mock-fixtures.ts`. The destination file is referenced ONLY by Playwright E2E tests (to set up MSW mocks) and vitest unit tests (to seed page-component test fixtures). Production routes MUST NOT import from this file. The executor MUST add a vitest test at `frontend-svelte/src/lib/api/client.spec.ts` (or similar location) that asserts (via static-grep AssertionError) that `grep -rln "from '\\\$lib/alcast/mock'" frontend-svelte/src/routes` returns ZERO matches — this is a regression guard against accidental re-introduction of mock imports in production code.

Alternative: the executor adds an ESLint rule under `frontend-svelte/eslint.config.js` (if the project uses flat ESLint config) banning `$lib/alcast/mock` imports from `src/routes/**` — same enforcement, different mechanism. Either is acceptable; the executor picks based on which tooling is already wired into the CI gate.

## §5 Constitutional rules

The following rules are EXISTING institutional bindings and MUST be respected by the executor PR:

- **Frontend is a presenter only** (`docs/systemconstitucion.md`). The new pages display server-computed economics verbatim; they do not multiply, sum, percentage, or otherwise derive financial quantities client-side. The two unavoidable client-side derivations remaining after the port — Sidebar's navBadges counts (3 integers from `/total` server fields), and the dashboard's manual `((c.last - c.prev) / c.prev) * 100` for "Δ Dia" market quote — both consume server-provided primitives. Δ Dia computation MUST be removed; if the backend market-data response doesn't already include a `pct_change_1d` field, the executor files a backend-gap follow-up and the page renders `—` for that cell in the interim.
- **No mutation without evidence** (`docs/governance.md` AUDIT-TRAIL section). Every mutation in §4.6 (POST /rfqs, POST /counterparties, POST /orders/purchase, POST /orders/sales) is already served by a backend route that emits an HMAC-signed audit event via `audit_trail_service`. The frontend does not add audit emissions — it surfaces server-emitted error responses via notifications (per §4.6 template). The executor MUST NOT add client-side "audit logging" of any form (no `console.log(action)`, no fire-and-forget `/audit/events` POSTs from the frontend).
- **No silent fallback, no implicit inference, no heuristic correction** (`docs/systemconstitucion.md`). Every load function uses `throw error(status, message)` from `@sveltejs/kit` on apiError, never returns empty `{ items: [] }`. Every mutation surfaces the backend's `apiError.detail` to the user via `notifications.add({ type: 'error', ... })`, never swallows.
- **Pricing must come from the canonical provider for the instrument** (`docs/governance.md` MARKET-DATA GOVERNANCE). The frontend does not select a provider; it consumes whatever the backend returns. The market-data page displays the `provider` field as a Badge — the prototype's hardcoded "Refinitiv" / "B3" badge values MUST be replaced with the server-response field; if the server response lacks a `provider` field, render `—` and file a backend-gap follow-up. **DO NOT** hardcode "Refinitiv" in the page.
- **Decimal end-to-end** (`docs/governance.md` precision contract). The display layer formats Decimal-shaped JSON strings (the backend serializes Decimal as quoted JSON strings to preserve precision). The executor MUST verify that `formatUSD`/`formatBRL`/`formatCommodityPrice` accept `string | number` and parse via `Decimal.js` or pass through `Number(...)` only at the very last step. If `format.ts` currently does `Number(v).toLocaleString(...)` it's likely already correct, but the executor MUST re-verify against the backend JSON shape for `notional_usd`, `mtm_usd`, `pnl_realized_usd` — if those come as quoted strings, `parseFloat` precision-loss is acceptable for display BUT must be flagged inline at the page where the float boundary happens, per the existing `frontend-svelte/src/lib/api/financial-display-precision.test.ts` regression suite.
- **No prototype-era Tweaks persistence** (per §2). The `data-density` / `data-theme` / `data-nav` attributes on the design root are NEVER present in production. The localStorage key `alcast.tweaks.v1` is not read or written in production. The Tweaks store and panel files are deleted.

## §6 Acceptance criteria

After the executor PR merges, the following must hold (each bullet is independently verifiable; the executor MUST close each one explicitly in the PR description before requesting review):

1. `grep -rln "bg-surface-\|text-accent\|text-surface\|color-accent\|color-surface\|color-gold\|color-teal\|color-danger\|color-success\|color-warning" frontend-svelte/src` returns ZERO matches. (Dark Tailwind theme completely removed.)
2. `grep -rln "from '\\\$lib/alcast/mock'" frontend-svelte/src/routes frontend-svelte/src/lib/components` returns ZERO matches. (Production code does not import mock data.)
3. `find frontend-svelte/src/routes/preview -type f` returns ZERO results. (Staging route family deleted.)
4. `find frontend-svelte/src/lib/styles -name "alcast-design.css"` returns ZERO results. (CSS file consolidated into `app.css`.)
5. `find frontend-svelte/src/lib/stores -name "alcastTweaks.svelte.ts"` returns ZERO results. (Tweaks store deleted per §2.)
6. `npm --prefix frontend-svelte run check` exits 0 with ZERO errors. (Warnings about a11y_label_has_associated_control are acceptable but the executor MUST add `<!-- svelte-ignore a11y_label_has_associated_control -->` comments above each radio-group label per the existing institutional pattern — see `frontend-svelte/src/routes/(protected)/exposures/+page.svelte` pre-rewrite for prior art.)
7. `npm --prefix frontend-svelte run build` exits 0 and produces a `build/` directory with ZERO CSS warnings about undefined Tailwind tokens.
8. `npm --prefix frontend-svelte run api:types:check` exits 0. (Schema drift gate.)
9. `npm --prefix frontend-svelte run test` (vitest) exits 0. All existing component tests pass; new tests added per §7 pass.
10. `npm --prefix frontend-svelte run test:e2e:smoke` exits 0. (Backend E2E smoke gate.)
11. `npm --prefix frontend-svelte run test:e2e` exits 0 against the docker-compose stack. (Full Playwright suite passes with updated selectors per §7.)
12. The 18 routes in §4.4's destination column each return HTTP 200 when fetched against a dev server (`npm run dev`) with the backend stack running.
13. Authenticated user navigating to `/` (Dashboard) sees the navy/orange institutional identity (Sidebar fixed at 232px width, IBM Plex Sans font, sober institutional palette) — NOT the dark `bg-surface-950` theme. Verified by manual operator walkthrough OR by Playwright screenshot diff against the design tool's exported screenshot at `design-prototypes/hedge-control/project/.thumbnail`.
14. Unauthenticated user navigating to any `(protected)/*` route is redirected to `/login` exactly as before this PR. (Auth gate preserved.)
15. Sidebar's nav-badges show real counts from the backend (not the prototype's hardcoded `'24'`/`'3'`/`'2'`). When the backend returns `total: 0`, the badge is hidden (not rendered as `'0'`). When the backend errors, the badge is hidden (not rendered as `'?'` or `'—'`).
16. AppShell's footer shows the actual Clerk-authenticated user's name and highest-precedence role (`auditor > risk_manager > trader`). Logout button works (calls `clerk.signOut()` + `authStore.logout()`).
17. Topbar's env badge shows `Produção` (red-tinted) in production builds, `Desenvolvimento` in dev, `Homologação` otherwise.
18. The three new-entity forms (`rfq/new`, `orders/new`, `counterparties/new`) submit successfully: on 200/201, the user is navigated to the new entity's detail page (`goto('/rfq/{id}')`, etc.); on 4xx/5xx, a toast notification surfaces the backend's `detail` field.
19. `frontend-svelte/src/routes/(protected)/analytics/what-if/+page.svelte` is PRESERVED unchanged (per §4.4 default decision). The Sidebar has a "What-if" entry pointing to `/analytics/what-if`.
20. CSP report-only ramp at `frontend-svelte/nginx.conf` is UNCHANGED (no new `script-src` or `style-src` exceptions needed).
21. ECharts bundle-size budget in `frontend-svelte/scripts/check-bundle-size.sh` passes. (The new pages don't add ECharts usage beyond what's already there — the alcast Sparkline and MtmSparkline components are hand-rolled SVG, not ECharts; ECharts is still used only by the existing analytics page if any. Verify the bundle-size budget config doesn't need adjustment.)
22. `cd frontend-svelte && grep -rn "toFixed\|toLocaleString" src/routes/(protected)` returns matches ONLY in non-financial display contexts (e.g. formatting a percentage label, formatting a date string). Every financial-value formatting call uses one of the `format.ts` helpers.
23. `git log --diff-filter=D --name-only --pretty=format: HEAD~1..HEAD | grep -c "preview/"` returns a non-zero count. (Confirms the `/preview/*` files were deleted as part of this PR, not just renamed.)

## §7 Tests

- Update every Playwright E2E spec under `frontend-svelte/e2e/*` that selects elements by Tailwind dark-theme class names. Audit by `grep -rln "bg-surface\|text-accent\|text-surface" frontend-svelte/e2e/`. Each match becomes a new alcast selector (e.g. `.sb-item.active`, `.kpi-value`, `.btn-primary`, `[class*="badge"]`). The full sweep applies to: the smoke gate (`frontend-svelte/e2e/smoke.spec.ts` if exists), the RFQ create flow, the orders flow, the contracts flow, the cashflow flow, the audit gate test, the workflow-approvals test. Each spec MUST exit 0 against the docker-compose stack after the rewrite.
- Add a static-grep regression test at `frontend-svelte/src/lib/api/no-mock-imports.test.ts` (vitest) that fails if any `import.*from.*'\$lib/alcast/mock'` appears under `src/routes/` or `src/lib/components/`. This is institutional debt protection per §4.8.
- Add a vitest test per load function at `frontend-svelte/src/routes/(protected)/<route>/+page.test.ts`. The test mocks the `client.GET` call (via MSW or `vi.mock` of `$lib/api/client`) and asserts the load function returns the expected flat shape AND surfaces apiError via `throw error(...)`. Minimum coverage: 4 load functions tested (Dashboard, RFQ list, Contract detail, Audit) — the other 14 are pattern-equivalent and the executor's discretion whether to test exhaustively.
- The existing `frontend-svelte/src/lib/api/contracts-settlement-guard.test.ts`, `financial-display-precision.test.ts`, `analytics-response-shape.test.ts`, `page-contracts.test.ts`, `rfq-create-institutional-flow.test.ts`, `rfq-evidence-integrity.test.ts` test files MUST continue to pass after the rewrite. If any of them fail because they encode an assumption about the legacy dark Tailwind markup, the executor updates the selectors in-place rather than disabling the test.
- DO NOT add tests that lock in the prototype's mocked-data values (e.g. `expect(rfqs[0].id).toBe('RFQ-2026-0184')`). The mock IDs are fixture-only; tests that reference them must be in `frontend-svelte/tests/fixtures/*.test.ts` not in component or route specs.

## §8 Audit / Observability

This is a frontend-only PR. The executor adds ZERO new HMAC audit events. The mutations submitted from the three new-entity forms (RFQ, Counterparty, Order) trigger existing backend audit emissions via the existing service-layer audit_trail_service — these are already in place from PR #75 (J-CL1-01 closure), PR #87 (PR-CL4-1), PR #94 (HB-1), PR #99 (HB-2), and PR #100 (HB-3) merges per the orchestrator memory entries.

The executor MUST verify (by manual operator walkthrough on staging) that:

- Submitting a new RFQ from `/rfq/new` causes one `rfq.create` audit event to land in the `/audit/events` table with the actor's Clerk subject ID, HMAC signature, and `entity_type='rfq'`.
- Submitting a new Counterparty causes a `counterparty.create` event.
- Submitting a new Order causes an `order.create` (or whatever event type the backend currently emits — verify by reading the backend route handler before declaring the manual test passed).

If any of these emissions are MISSING after submission, the executor files a backend-gap follow-up — DO NOT attempt to backfill the audit emission from the frontend.

## §9 Rollout

Single PR, single Railway deploy. The PR's merge → Railway's `frontend-svelte` service rebuilds the nginx-served bundle automatically. The backend service is unchanged, so no separate backend deploy is required. The scheduler service is unchanged (frontend port has zero backend interaction beyond HTTP API calls).

Pre-deploy gate per `docs/runbook-railway.md`:

- Manual operator walkthrough on the Railway staging environment (`hedge-frontend-staging` if such a service exists, otherwise the executor coordinates with Andrei to spin up a temporary staging URL via Railway's preview-deploy feature).
- Walkthrough checklist (Andrei executes): (a) login flow lands on the new identity, (b) all 18 routes render, (c) Sidebar nav-badges show real counts, (d) creating an RFQ from `/rfq/new` against a real backend results in a new row visible at `/rfq` after the redirect, (e) the env badge shows the correct environment string, (f) logout → re-login round-trips work.
- Sign-off: Andrei posts a thumbs-up comment on the PR after the walkthrough.

Rollback plan: this PR removes the legacy theme without a feature flag (per Andrei's binding). If the deploy fails or a critical regression surfaces in production, the rollback is `git revert <merge-commit-sha>` + Railway redeploy. The reverted state is exactly the pre-PR state (legacy dark Tailwind theme + dark sidebar). The executor MUST verify before merge that the PR is revertable as a single commit (Squash merge OR a clean revert path exists).

Pilot brief alignment: per Andrei's pilot brief §4 (`docs/2026-05-tech-lead-executive-analysis.md`), the pilot launches with the production frontend identity that lands via this PR. The brief's binding scope is 8 counterparties × 140k t/year operating under the new identity from pilot day 1. This PR MUST merge before pilot day 1.

## §10 DO NOTs

Concrete forbidden actions, in addition to §2's high-level boundary:

- DO NOT introduce a `?legacy=1` query-string escape hatch or a `VITE_DESIGN_VERSION=legacy` environment override that re-enables the dark theme. Per Andrei's binding decision, the legacy theme is removed in this same PR with no fallback.
- DO NOT leave `console.log` / `console.warn` / `console.debug` calls in the production routes after the rewrite. The existing `notifications.add(...)` is the channel for user-visible diagnostics; the existing Sentry/Prometheus wiring (if any) is the channel for ops-side observability.
- DO NOT add `try { ... } catch (e) { /* empty */ }` blocks anywhere. Errors propagate to `+error.svelte` (via `throw error(...)`) or to `notifications.add({ type: 'error', ... })`. Silent catch is a P1 governance violation.
- DO NOT inline the prototype's prototype-era `style={{ ... }}` JSX-flavor objects when rewriting from JSX → Svelte (the JSX-to-Svelte translation is already done in the `/preview/*` files; the executor's job is just to move them, not retranslate). All inline styles in the Svelte files MUST be string-literal `style="..."` attributes, which they already are.
- DO NOT add reactive `$effect(() => { ... })` blocks that re-trigger load function calls on every state change. Load functions are SvelteKit's primary data-loading primitive; component-level fetching is reserved for mutations and live polling. If a page needs live data refresh (e.g. RFQ detail polling for new quotes), the executor wires it via `setInterval(() => invalidate('/rfqs/' + id), 5000)` using SvelteKit's `invalidate()` — NOT a parallel `$effect` that bypasses the load function.
- DO NOT add a "Refresh" button that calls `window.location.reload()`. Use SvelteKit's `invalidateAll()` to re-run all active load functions without a full page reload.
- DO NOT introduce any inline `<script>` element in `app.html` or in any `+layout.svelte` (the existing `app.html` has `display: contents` div wrapping `%sveltekit.body%` — that's the only allowed inline content). CSP report-only is monitoring violations; new inline scripts would be flagged.
- DO NOT preserve any `.alcast-design` class wrapper in production HTML. The class is dissolved into `body` in §4.1; pages do not need to opt into the design surface.
- DO NOT keep the `frontend-svelte/src/lib/styles/` directory if `alcast-design.css` is its only file. After deletion, the parent directory is empty and MUST also be removed (`rmdir` semantics — Git removes empty dirs automatically when the last file is `git rm`'d).
- DO NOT modify `frontend-svelte/vite.config.ts` manual-chunk split unless the new bundle composition requires it. The bundle-size budget script (§6 #21) will catch a regression; if it triggers, the executor adjusts the chunk split in a focused commit within this PR.
- DO NOT add a "Tweaks" button or settings menu to the production AppShell. Per §2 the Tweaks panel is excluded; the production identity is single-flavor (regular density, default theme, expanded nav).
- DO NOT change the AppShell sidebar's hardcoded "Alcast Hedge" / "Hedge Control Platform" brand strings to read from `$lib/config` or an env var. The strings are intentional and bound to the platform's institutional identity per the design tool transcript. A future amendment would handle white-label scenarios; out of scope here.

## §11 Workflow

1. **Executor opens a branch off `main` HEAD** (post-dispatch merge): `git checkout -b codex/design-port-route-wiring main`.
2. **Executor implements §4.1 through §4.8 in the order prescribed**, with intermediate commits permissible — final PR has at most a handful of commits (squash on merge is acceptable per `docs/runbook-railway.md`).
3. **Executor runs the full local gate sequence before pushing**:
   - `cd frontend-svelte && npm run check` → 0 errors
   - `cd frontend-svelte && npm run build` → 0 CSS warnings about undefined tokens
   - `cd frontend-svelte && npm run api:types:check` → 0 drift
   - `cd frontend-svelte && npm run test` → all pass
   - `npm run test:e2e:smoke` (from repo root) → 0 errors against the docker-compose stack
4. **Executor runs the full local manual walkthrough**: `docker compose up -d` + `cd frontend-svelte && npm run dev`. Visits all 18 routes. Submits one RFQ, one Counterparty, one Order. Logs out, logs back in.
5. **Pre-push LLM dispatch-review hook (Sonnet 4.6) fires**: per `.githooks/pre-push`, if the diff touches any file under `docs/audits/*-dispatch.md`, the hook runs. This PR's commit graph does NOT touch any dispatch file (this dispatch file already merged in a separate PR per the institutional workflow), so the hook skips in ~100ms. If the executor accidentally includes a dispatch edit, the hook gates per the rules in `docs/audit-protocol/dispatch-review-rules.md`.
6. **Executor pushes and opens the PR** with the §6 acceptance checklist filled in. PR title: `feat(frontend): promote alcast-design as production identity (route wiring)`. PR body references this dispatch file path.
7. **Codex Connector adversarial review runs automatically** on the PR. Per `reference_review_gates_2026_05_17` memory entry, Codex Connector is the sole review gate as of 2026-05-26 (Greptile + AugmentCode decommissioned). The `+1` reaction on the PR is the acceptance signal; the `eyes` reaction is processing-only and NOT acceptance.
8. **Executor absorbs Codex catches in additional commits**, re-pushing until Codex's silent `+1` reaction lands AND the orchestrator-side independent verification (3-endpoint check per `feedback_executor_false_completion_pattern`) confirms: (a) CI green on the final SHA, (b) all unresolved review threads closed, (c) Codex `+1` reaction present on the PR-level reactions endpoint (`/issues/{N}/reactions`).
9. **Andrei executes the §9 staging walkthrough** and posts a thumbs-up comment on the PR.
10. **Andrei merges the PR.** Railway auto-deploys.
11. **Post-merge memory entry** is created by the orchestrator per the institutional pattern (e.g. `project_design_port_route_wiring_landed.md` under `<memory>/`), referencing the merge commit SHA, the final state of dark-theme references (ZERO), and the mock-import audit result (ZERO production imports).

No deferred waves are declared after this PR — the single-mega-dispatch decision means everything lands in one PR. If Codex catches surface issues that require a follow-up PR (e.g. a backend-gap discovered during integration testing), the orchestrator authors a NEW dispatch for that follow-up; it is not pre-committed here.

---

### Annex A — Sibling-bullet sweep checklist (executor self-audit before push)

Before pushing the final SHA, the executor MUST verify the following sibling-bullet sweeps for cross-section consistency (per `docs/audit-protocol/dispatch-review-rules.md` Rule 6 and Rule 7):

- §1 prescribes 12 lettered actions (a)-(l). §6 acceptance criteria MUST cover each — verify by `grep -E "^[0-9]+\. " §6` returning ≥ 12 bullets and reading each to confirm coverage of the 12 lettered actions.
- §4.4 lists 18 source routes. §6 #12 asserts "18 routes return HTTP 200" — the count MUST match. If a route is added or removed from §4.4, §6 #12 updates correspondingly.
- §4.5 lists 17 destination route load configurations (the dashboard counts as one). §6 #18 asserts the three new-entity submission flows — the count MUST match the new-entity routes in §4.5 (`orders/new`, `rfq/new`, `counterparties/new`).
- §10 lists 13 DO NOTs. §2 lists 12 boundary clauses. There is NO required count parity between §2 and §10 — they cover different concerns (§2 = scope, §10 = forbidden implementation tactics).
- Path-difference call-outs in §4.4 (`/preview/pnl` → `/analytics/pnl`, etc.) MUST be reflected in §4.3's Sidebar update prescription. Verify each path difference is listed both in the table and in the bullet list following the table.
- §5 Constitutional rules enumerate 7 binding clauses. Each MUST tie back to either §2 (a boundary) or §10 (a forbidden tactic). No "orphan" constitutional rule that doesn't appear elsewhere.

### Annex B — Self-defeat check (executor self-audit before push)

For each §3-style directive, ask: "could an executor follow this literally AND leave the design-port intent (replace dark theme with sober institutional identity) intact?" Specifically:

- §4.2 prescribes wrapping `{@render children()}` inside `<AppShell>` only when `authStore.isAuthenticated` is true. The unauthenticated branch (login page) renders `children` directly without AppShell. This is CORRECT because the login page lives under `(public)/login` and the SvelteKit route group means it does not inherit the (protected) AppShell context. Verify: visiting `/login` while logged out shows the bare login form, NOT the alcast Sidebar. (Login page CSS is independent and not part of this PR's scope.)
- §4.5 prescribes `throw error(502, '...')` on apiError. This is CORRECT and not a self-defeat: the SvelteKit error boundary surfaces a sober error page (the existing `frontend-svelte/src/routes/+error.svelte`) without falling back to fake data. If the error boundary itself uses dark Tailwind tokens, the executor updates `+error.svelte` to use alcast classes within the same PR.
- §4.6 prescribes submit handlers that call `notifications.add(...)` on apiError. This is CORRECT and not a self-defeat: the notification surfaces the backend's `detail` field, the user knows the action failed, the form state is preserved for retry. The submit button is re-enabled (`submitting = false` after the await) so the user can fix and retry.

### Annex C — Constitutional alignment table

| Constitutional clause                                            | Anchor                                                              | §-binding in this dispatch |
|------------------------------------------------------------------|---------------------------------------------------------------------|----------------------------|
| Frontend is a presenter only                                     | `docs/systemconstitucion.md`                                        | §2, §5, §10                |
| No silent fallback                                               | `docs/systemconstitucion.md`                                        | §4.5 rule 1, §5, §10       |
| No mutation without evidence (HMAC audit)                        | `docs/governance.md` AUDIT-TRAIL                                    | §5, §8                     |
| Pricing canonical provider                                       | `docs/governance.md` MARKET-DATA GOVERNANCE                          | §5, §4.5 market-data row   |
| Decimal end-to-end                                               | `docs/governance.md` precision contract                              | §4.7, §5                   |
| RBAC matrix (trader visibility, auditor exclusivity)             | `docs/governance.md` AUTHORIZATION MATRIX                            | §2, §4.5 audit-row         |
| CSP report-only (frame-ancestors, no unsafe-eval)                | `frontend-svelte/nginx.conf` + `docs/audits/...cluster-3-pr-4-csp`   | §2, §6 #20, §10           |
