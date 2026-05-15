# XSS Sink Inventory — Hedge Control Frontend

**Generated:** 2026-05-15 (PR-CL3-4)
**Source:** `frontend-svelte/src/` + `frontend-svelte/static/`
**Methodology:** rg sweep across 4 sink categories per D-3.3 backlog requirement (PR-CL3-4 executor)
**PR:** audit-followup/cluster-3-csp-xss-sink

## Sink categories surveyed

1. `innerHTML` (assignment to .innerHTML or use of `{@html}` in Svelte templates)
2. `eval` (any `eval(...)` call)
3. `setAttribute('href' | 'src')` (potential `javascript:` URL injection)
4. Dynamic `import(...)` with non-literal argument (code-splitting / plugin loader risk)

## Sweeps performed (exact commands from dispatch §4.3 / §8)

```bash
rg -nP "innerHTML|\\{@html|eval\\(|setAttribute\\(['\"](?:href|src)['\"]" frontend-svelte/src/ frontend-svelte/static/
rg -nP "import\\([^'\"`]" frontend-svelte/src/ frontend-svelte/static/
```

Additional manual classification sweeps for test files and data-* attributes.

## Findings

No high-risk input-tainted XSS sinks found in production code paths.

| Site | Category | Snippet | Risk | Status |
|---|---|---|---|---|
| `src/lib/utils/sanitize.ts:13` | innerHTML (comment) | JSDoc: "ECharts tooltip formatters which use innerHTML by default" | None (documentation only) | Accepted-risk (ECharts internal, not our code) |
| `src/lib/clerk.ts:98` | setAttribute (data-*) | `script.setAttribute('data-clerk-publishable-key', publishableKey)` | None (data-* attribute, never href/src, Clerk SDK internal) | Framework-internal (safe) |
| `src/lib/stores/*.test.ts`, `src/lib/api/fetch.test.ts` (12 sites) | dynamic import | `await import('./auth.svelte')`, `import('$app/navigation')` etc. | None (all arguments are static string literals; test-only code not shipped to browser) | Test-only (static) |

**Total production sinks:** 0

**Breakdown (including notes):**
- input-tainted: 0
- static-string (but safe context): 0 in prod
- framework-internal / test-only: 14 (all classified safe above)

## Conclusion

The frontend SPA (post PR-CL3-3 Clerk integration) contains **zero exploitable XSS sinks** in the four categories surveyed. All `innerHTML` references are comments or third-party (ECharts). The single `setAttribute` call is for a Clerk data attribute (not a URL attribute). All dynamic `import()` calls are in test files with compile-time string literals.

This inventory confirms that the strict CSP (with `'unsafe-inline'` for Svelte hydration + Clerk FAPI but no `'unsafe-eval'`) is compatible with the current codebase. No immediate remediation required for D-3.3 closure.

Remediation of any future sinks (or tightening to remove `'unsafe-inline'`) is deferred to post-Cluster-3 follow-up per dispatch §2 / §9.

## Reconciliation cadence

This inventory MUST be re-generated:
- Before every major frontend release
- After any new dependency that ships templates/HTML or uses dynamic evaluation
- During each Phase audit cycle going forward
- After any SvelteKit / Clerk SDK major version bump

**Executable guard:** the sweeps in this file are the source of truth; CI can re-run them and diff the table.

## Cross-references

- D-3.3 backlog item: `docs/audits/2026-05-13-cross-phase-deferral-backlog.md` §85-88
- Cluster 3 platform decisions: orchestrator memory `project_cluster_3_platform_decisions`
- CSP enforcement: `frontend-svelte/nginx.conf` (Content-Security-Policy-Report-Only, PR-CL3-4)
- Clerk SDK integration: `frontend-svelte/src/lib/clerk.ts` (PR-CL3-3)
- Sanitization helper: `frontend-svelte/src/lib/utils/sanitize.ts`
