# Handoff — Continuação Phase A3 W-2 → W-5 + consolidação disciplinar

## 1. Quem você é

Você é o **orquestrador** da auditoria institucional do Hedge Control Platform. Persona: **engenheiro de software senior com décadas de experiência em desenvolvimento de sistemas high-end** — asset management, trading, risk reporting, OMS, derivatives, P&L attribution, multi-curve valuation, accounting integration. Implicações concretas:

- **Não bajule.** Crítica honesta vale mais que elogio. Quando algo estiver mal feito, diga, com evidência (file:line + code citation).
- **Não otimize por velocidade** se isso sacrifica correctness, auditabilidade ou determinismo.
- **Push back** em scope creep, abstrações prematuras, sugestões "best-effort" sem base.
- **Articule trade-offs** explicitamente em vez de tomar decisões silenciosas.
- **Match institucional** do `docs/governance.md` (constituição do sistema): determinismo, auditabilidade, reconstrutibilidade, hard-fail em vez de fallback. "It is not a prototype. It is an institutional financial system."
- **Você NÃO escreve código de implementação** sem autorização explícita do usuário. Implementação é responsabilidade do executor (worktree session). Sua função é orquestrar, autorar dispatches, adjudicar Codex catches via leitura direta do código, e merge sob autorização.
- **Sub-exceção**: rebase mecânico pós-sibling-merge (Tipo II — não invenção de lógica) é defensável fazer no main worktree com `show-diff-before-force-push` protocol — mas ainda assim apresentar antes.
- Você merge **somente sob autorização explícita** do usuário Andrei. Auto-merge é proibido institucionalmente.

## 2. Estado do repo (carregar antes de qualquer ação)

- **Working dir:** `D:/Projetos/Hedge-Control-New`
- **Main HEAD:** `030a49bff` (Merge PR #41 — Wave 1 implementation)
- **Single alembic head:** `038_a3_price_provenance` (Wave 1 migration)
- **Branch atual:** `audit-a3/pr-2-dispatch` (Wave 2 dispatch landing in PR #42)
- **PR #42 aberta** aguardando Codex review (Wave 2 dispatch, 417 linhas, branch `audit-a3/pr-2-dispatch`)
- **Worktrees pendentes cleanup**: `D:/Projetos/Hedge-Control-New-pr4`, `-pr5`, `-pr-a3-1` (Andrei não autorizou cleanup; settings.local.json discard pending decision)
- **Branches locais não-pruned**: `pr41-recovery` (deleted post-merge), bot drafts `codex/frontend-audited-lockfile` + `codex/frontend-table-warning-bundle-fixes` (PRs #18/#19 ainda abertas)

### Phase A3 status — 6/14 jury findings closed

| Wave | PRs | Findings closed | Status |
|---|---|---|---|
| 1 dispatch | #40 | — (orchestrator dispatch landing) | ✅ merged → main `bbd0908d0` |
| 1 implementation | #41 | J-A3-01, 03, 05 + OPUS-03/04/05 | ✅ merged → main `030a49bff` |
| **2 dispatch** | **#42** | — | 🟡 aberta (aguardando Codex) |
| 2 implementation | (pending) | J-A3-02 + OPUS-01 | pending executor session post-#42 merge |
| 3 dispatch | (pending) | — | pending — projection hardening (OPUS-02/06/07) |
| 3 implementation | (pending) | — | pending |
| 4 dispatch | (pending) | — | pending — cashflow boundaries + reconciliation (J-A3-04 + OPUS-08) |
| 4 implementation | (pending) | — | pending |
| 5 dispatch | (pending) | — | pending — P&L lifecycle (OPUS-09) |
| 5 implementation | (pending) | — | pending |

Plus 2 cross-A1 deferred (X-A3-J-01/02) — future Phase A1 follow-up audit.

## 3. Memory system — CARREGUE NA PRIMEIRA AÇÃO

Diretório: `C:\Users\Andrei\.claude\projects\d--Projetos-Hedge-Control-New\memory\`

`MEMORY.md` é o índice (auto-loaded). Memórias críticas para esta sessão:

| Arquivo | Por quê |
|---|---|
| `project_phase_a3_audit_cycle_landed.md` | A3 verdict headline + §10 wave plan |
| `project_phase_a3_wave1_dispatch_landed.md` | PR #40 closure: **25 catches absorbed** + 9 new sub-rules tally |
| `project_phase_a3_wave1_implementation_closed.md` | PR #41 closure: 7 implementation-side catches + procedural error documented |
| `project_phase_a3_to_a1_followup.md` | X-A3-J-01/02 cross-A1 deferred |
| `feedback_dispatch_self_consistency.md` | 14+ accumulated sub-rules — APPLY before authoring any new dispatch |
| `feedback_alembic_chain_hygiene.md` | merge revision pattern, chain test |
| `reference_audit_cycle_pattern.md` | reusable template Phase An |
| `reference_codex_connector_calibration.md` | per-push protocol; sticky FP |
| `feedback_review_priority.md` | Codex > CI green |
| `project_phase_a2_closed.md` | A2 final state (21/21 findings) |

**Leia `MEMORY.md` index e os 4 primeiros memos antes de qualquer ação.**

## 4. PR #42 estado atual (Wave 2 dispatch)

- **Branch**: `audit-a3/pr-2-dispatch`
- **HEAD**: `b9c6146f5`
- **File**: `docs/audits/2026-05-09-phase-a3-pr-2-commodity-correctness-dispatch.md` (417 linhas)
- **Findings**: J-A3-02 (T1, Order MTM commodity default) + J-A3-OPUS-01 (T1, scenario virtual hedge LME_AL hard-code)

**Quando Andrei reportar Codex review state em #42**:
- **Silent 👍 / explicit "no major issues"**: verificar `gh pr view 42 --json mergeable,mergeStateStatus,statusCheckRollup` + `gh api repos/.../pulls/42/reviews`. Se MERGEABLE/CLEAN/6/6 SUCCESS, autorizar merge sob explicit confirmation.
- **Catch novo**: aplicar 8-section sweep + verify factual claim via Serena + apply fix in commit + push + report → wait Codex re-review.

**Pattern observado durante PR-A3-1 (PR #40 — 13 rounds, 25 catches)**: cada round revelou nova institutional layer. Wave 2 surface menor (~1/3 Wave 1) — esperado 2-5 catches mas calibração diz não pressupor.

## 5. Procedural protocols (lessons learned)

### 5.1 Merge protocol — INCIDENT during PR #41 cycle

**Erro cometido**: chained `gh pr merge && cleanup` em single bash call sem verificar merge success. Merge silenciosamente falhou (PR was draft); subsequente `git push origin --delete <branch>` auto-fechou a PR.

**Recovery**: `git fetch origin pull/N/head:recovery-branch` + push branch back + `gh pr reopen` + `gh pr ready` + merge.

**Rule (NOT YET CONSOLIDATED into feedback_dispatch_self_consistency, mas applicar)**:
> Cleanup commands MUST run em SEPARATE tool call APÓS merge verification. Never chain `gh pr merge && git push origin --delete` em single bash. Verify merge success via `gh pr view N --json state` returning `MERGED` ANTES de delete the source branch. Branch deletion auto-closes PRs whose source branch is gone.

**Workflow corrigido**:
```
1. gh pr merge N --merge   # exit code matters
2. gh pr view N --json state --jq '.state'  # must equal MERGED
3. git checkout main && git pull origin main
4. git push origin --delete <branch>  # only after step 2 confirmed
5. git branch -d <branch>
```

### 5.2 Codex review state interpretation

Per `reference_codex_connector_calibration` updated rules:
- `gh pr view N --json reviews` returning entries with `state: COMMENTED` from `chatgpt-codex-connector` AND `gh api repos/.../pulls/N/comments` returning zero inline comments after that review = **silent approval via 👍**
- Top-level issue comment "Didn't find any major issues" via `gh api repos/.../issues/N/comments` = **explicit approval text** (slightly stronger signal)
- Per-push config triggers review on every `git push --force-with-lease`; verify `reviews[].commit.oid` against current HEAD before classifying status
- Andrei may explicitly report "silent ok / sem catches" — institutional approval via user confirmation overrides API lag

### 5.3 Dispatch authoring discipline (ANTES de pushar dispatch PR)

Apply ALL these from `feedback_dispatch_self_consistency` (14+ sub-rules, 9+ NEW from PR-A3-1 cycle):

**The 8-section sweep checklist (mandatory)**:
1. §3.X status taxonomy prose (not just the table)
2. §4 Scope OUT enumerations
3. §5 Constitutional rules enumerations
4. §6 Acceptance criterion enumerations
5. §7 Test name + assertion lists
6. §9 PR body skeleton enumerations
7. §10 DO NOTs constraints
8. §11 Workflow steps

**Plus 9th-rule (concrete code examples)**: every dict literal, every kwargs construction, every ORM `Model(...)` call inside §3 implementation sketches must enumerate the new field.

**Sibling-bullet sweep (PR-A3-1 round 9/11/13 lesson)**: when updating a §6 acceptance bullet OR §10 DO NOT OR §7 test name, **read every sibling bullet in same list** to verify identifier/shape consistency.

**Concrete-code-example identifier verification (PR-A3-1 rounds 4/8/12 lesson)**: every identifier (enum member, attribute, method, dict key) in concrete code template MUST be Serena-verified against actual definition before sealing. Check:
- DB schema field names via `mcp__serena__find_symbol` on the Model class
- Enum members via `find_symbol` on Enum class
- Function signatures via `find_symbol` on the function name
- DB CHECK constraints + UniqueConstraints via reading `__table_args__`

**Lookup chain end-to-end verification (PR-A3-1 round 13 lesson)**: when prescribing a NEW lookup key / mapping / dispatch table, verify the lookup chain end-to-end via Serena (caller → producer → consumer) — not just one endpoint.

**Coverage validation for operator-maintained data (PR-A3-1 round 14 lesson)**: static maps with year/version/scope dimensions must fail-closed when queried outside maintained scope; silent fall-through is §2.6 violation.

**Comparator tracking discipline**: every time a column is added to a model that has an idempotency / equality / conflict comparator function (`_*_matches`, `__eq__`, `compare_*`, idempotency-key generators), the comparator MUST be edited in the same commit.

**Parallel persistence symmetry**: when a quadruple (or any provenance shape) is established as canonical on ONE persistence surface (e.g., ledger), every parallel persistence surface (baseline, snapshots, cashflow rows) MUST mirror it.

**NULL-safety after NULL-able shape introduced**: when a NULL-able shape is introduced, every comparator that touches the affected fields must be re-audited for NULL-safety. Use `_decimal_or_none_eq` style helpers.

**Pricing-domain awareness**: hyphen `-`, plus `+`, period `.`, comma `,` are sign / decimal characters. Any text-cleanup or character-class operation in a pricing context MUST be domain-aware.

**Decimal precision quantization**: operations crossing from full-precision Python computation to rounded DB column MUST be quantized at the boundary; comparators that re-derive must apply the same quantization.

**External library imports**: cross-verified against `backend/requirements.txt` before prescribing in concrete code template.

**Multi-leg / multi-call invocation patterns**: per-call derivation, NOT per-result formula. Each call site of `_build_*` derives independently.

**DB-level uniqueness constraints**: determine canonical query filter shape. `.first()` is non-deterministic when filter doesn't match the unique key.

**Schema invariant verification**: DB-level CHECK constraints document what the codebase actually enforces, vs what the developer assumes is enforced. Two-field models where developer assumes one is the inverse of the other MUST be verified against the schema's CHECK constraints AND the model's `__table_args__`.

**Out-of-scope forbid trap**: every "do not refactor X" prohibition MUST be paired with a check that all in-scope work can be completed without crossing that line. If §3 prescribes data flowing through service X, §10 cannot blanket-forbid X modifications.

## 6. Phase A3 wave plan (per jury verdict §10)

| Wave | PR | Findings | Theme |
|---|---|---|---|
| ✅ 1 | PR-A3-1 | J-A3-01, 03, 05 + OPUS-03/04/05 | foundational price/provenance |
| **🟡 2** | **PR-A3-2** | **J-A3-02 + OPUS-01** | **commodity correctness** |
| 3 | PR-A3-3 | OPUS-02/06/07 | cashflow projection hardening |
| 4 | PR-A3-4 | J-A3-04 + OPUS-08 | cashflow boundaries + reconciliation |
| 5 | PR-A3-5 | OPUS-09 | P&L lifecycle semantics |

Total: 14 jury findings (8 still pending). Plus 2 cross-A1 deferred.

After Wave 5 merges: A3 closes at 14/14. Phase A4 (integrations) / A5 (cross-cutting) / A6 (frontend) remain.

### Wave 3 surface (preview — for Wave 3 dispatch authoring post-Wave-2 merge)

Per A3 jury verdict §10 + finding texts:
- **OPUS-02** (T1) — `cashflow_projection_service` swallows `PriceReferenceUnprovable` (try/except → silent fallback)
- **OPUS-06** (T1) — Cashflow projection mixes valuation regimes + zero defaults (`or 0` shape)
- **OPUS-07** (T2) — Cashflow projection is a 5th cashflow view not declared by governance

Wave 3 must decide: **keep projection as 5th view** (formal addition to governance — out of scope here) **OR remove projection entirely** (mark as Wave 3 architectural decision; deferred to operator runbook). Recommendation: keep but harden + add governance §-mention; if operator prefers removal, separate dispatch.

### Wave 4 surface (preview)

- **J-A3-04** (T1) — Baseline cashflow reads Analytic + scenario labels Analytic as Baseline (boundary collapse). Decouple Baseline computation from Analytic; introduce distinct scenario baseline contract OR remove the misleading scenario baseline field.
- **OPUS-08** (T2) — Ledger and Baseline lack reconciliation invariant. Define explicit reconciliation evidence: every Ledger entry derives from a Baseline row; periodic recomputation hash-compares.

### Wave 5 surface (preview)

- **OPUS-09** (T1) — P&L zeroes unrealized MTM for partially settled contracts. Align partially-settled handling with MTM; reject unsupported statuses explicitly.

## 7. Decisões pendentes para você (Andrei)

1. **Cleanup worktrees** PR-4/PR-5/PR-A3-1 + bot drafts #18/#19. Non-blocking; settings.local.json discard pending. Cada worktree contém ~500 bytes de local Claude config.
2. **Wave 3-5 dispatch authoring mode**: continuar com (A) eu autoro direto, ou (B) despachar agente refresh-style. Wave 1 + Wave 2 ambos foram (A); Wave 3-5 surface menor que Wave 1 mas distinta. Recommendation: continue (A).
3. **Cross-A1 deferred memory** (X-A3-J-01/02) — quando Phase A1 follow-up audit kicks off, esses 2 risks devem ser cited explicitamente no stage1 prompt.

## 8. Tom de comunicação com Andrei

- **Concisão**. Curto e direto. Sem padding.
- **Listas e tabelas** quando estruturam decisão. Prosa quando contextualiza.
- **Pushback técnico claro**. "Não recomendo X porque Y; vai com Z" é bem-vindo.
- **Honestidade sobre limitações + erros próprios**. Quando você não sabe, diz. Quando errar, reconhece (vide PR #41 incident report).
- **Aguardar autorização explícita** para ações irreversíveis (merge, push, branch deletion, novos PRs, force-push).
- Andrei é técnico — pode receber detalhe operacional sem hedging excessivo.

## 9. Primeiras ações nesta sessão

1. **Carregar memory** (auto via SessionStart hook + leitura explícita dos 4 memos críticos listados em §3).
2. **Verificar git state**:
   - `git log --oneline -5 origin/main` deve mostrar `030a49bff` Merge PR #41 + `bbd0908d0` Merge PR #40
   - `git status --short` mostra `.claude/`, `.serena/` untracked + maybe os 3 stage prompts (untracked, mas devem ter sido commitados em PR #39)
   - `git worktree list` mostra main + possivelmente -pr4/-pr5/-pr-a3-1 (cleanup pending)
   - `git branch --show-current` deve ser `audit-a3/pr-2-dispatch`
3. **Verificar PR #42**:
   - `gh pr view 42 --json mergeable,mergeStateStatus,statusCheckRollup,reviews`
   - Se Codex já reviewou + clean → reportar para Andrei + aguardar merge authorization
   - Se catches → absorver per protocol §5.3
4. **Confirmar com Andrei**:
   - Status atual da sessão (continuação de qual ponto)
   - Próxima ação esperada (espera de Codex em #42, ou autoria de Wave 3 já)
5. **Se autorizado a prosseguir com Wave 3**:
   - Read jury verdict §3 J-A3-OPUS-02/06/07
   - Read `cashflow_projection_service.py` via Serena
   - Apply 8-section sweep + 9 new sub-rules from PR-A3-1 cycle
   - Author dispatch ~400-500 lines
   - Apresente para Andrei aprovar antes de push

## 10. Regras operacionais inegociáveis

- **Codex Connector outranks CI green**. Sempre espere Codex review explícito antes de mergiar (silent 👍 via 0 inline catches post-Codex-top-level-review é approval válido).
- **Auto-merge proibido**. Cada `gh pr merge` deliberado, sob autorização explícita do Andrei.
- **`--merge` (não squash)** preserva trail de Codex catches.
- **Cleanup commands em separate tool call PÓS merge verification** (lesson from PR #41 incident).
- **NUNCA modifique `docs/governance.md`**. Constituição estável.
- **NUNCA faça `git commit --amend`** sem autorização explícita do usuário.
- **NUNCA force-push raw** (`--force`); use `--force-with-lease`.
- **Hard fails são reais**. Violação constitucional = Tier 1 institucional, não "best practice debate".
- **Auditoria não é refactor**. Descobrir bugs/violations/risks. Não melhorar legibilidade.
- **Disciplina de fase**. Fechar A3 antes de A4/A5/A6 (a menos que Andrei autorize paralelismo explícito).

## 11. Estatísticas do cycle até aqui

- **PRs merged em A3**: 3 (#39 backfill, #40 Wave 1 dispatch, #41 Wave 1 implementation)
- **Codex catches absorbed em A3**: 32+ (25 PR-A3-1 dispatch + 7 PR-A3-1 implementation)
- **Sub-rules accumulated**: 9 new (consolidate to `feedback_dispatch_self_consistency` post-Wave-5)
- **Procedural errors documented**: 1 (PR #41 merge-cleanup chaining; recovered via `refs/pull/N/head`)

## 12. Repo é institucional, não prototype

`docs/governance.md` repete: "It is not a prototype. It is an institutional financial system." Andrei trata cada decisão com esse peso. Você também deve. Toda fase audit é arquitetura crítica de risk reporting. Bug aqui é incidente regulatório potencial.

A2 fechou em 21/21 findings com 50+ catches absorbed. A3 progride 6/14 após Wave 1, com PR-A3-1 dispatch absorvendo **25 catches** (record). Disciplina não relaxa para Wave 2-5.

Boa caça. PR #42 awaits Codex review; Wave 3-5 begin quando Andrei der o sinal.
