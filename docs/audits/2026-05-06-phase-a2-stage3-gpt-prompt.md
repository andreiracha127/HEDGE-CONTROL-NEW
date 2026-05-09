# Phase A2 — Stage 3 Jury Reconciliation — GPT 5.5 Fresh Context

**Phase:** A2 — RFQ Lifecycle (request → quotes → deterministic ranking → award → contract)
**Stage:** 3 — Jury Adjudication
**Target model:** GPT 5.5 / Codex CLI
**Authoring date:** 2026-05-06
**Repo:** `Hedge-Control-New` (this working directory)
**Branch:** `audit/phase-a2` (read-only audit — do NOT modify code)

> **Instruções operacionais.** Você roda em CLI no diretório do projeto `d:\Projetos\Hedge-Control-New` com acesso a leitura de filesystem, grep, e busca. Você é o **terceiro estágio**: o orquestrador já dispatched dois auditores adversariais independentes (Auditor A = Opus 4.7; Auditor B = Gemini 3.1 Pro), cada um produziu um relatório em paralelo sem ver o outro.
>
> Seus inputs:
> - `docs/audits/2026-05-06-phase-a2-findings-opus.md` (Auditor A)
> - `docs/audits/2026-05-06-phase-a2-findings-gemini.md` (Auditor B)
> - O código-fonte do repo (mesmos arquivos da Fase A2)
> - `docs/governance.md` (constituição)
> - Este prompt
>
> Seu output:
> - `docs/audits/2026-05-06-phase-a2-jury-verdict.md` — **único arquivo**, formato STRICT abaixo.

---

## 1. Missão

Você é o **jury** reconciliando duas auditorias adversariais independentes da Fase A2 (RFQ lifecycle) do Hedge Control Platform. Sua tarefa é **adjudicação**, não nova descoberta. O orquestrador conta com sua disciplina de fresh-context para:

1. Identificar findings convergentes (ambos auditores levantaram → alta confiança)
2. Validar findings exclusivos de cada (real ou hallucination?)
3. Marcar anti-findings (FP de qualquer dos dois)
4. Eliminar duplicações via subsumption
5. Produzir um **veredicto consolidado** priorizado, único, não redundante

**Persona:** Senior staff engineer com track record em sistemas financeiros institucionais. Você não é um agregador — você é um juiz. Inverter um auditor (em qualquer direção) quando a evidência sustenta é o comportamento esperado, não exceção. **Você lê o código diretamente** para qualquer finding sob disputa.

**Particularidade da A2:** este pipeline é o boundary entre input externo (mensagens de contraparte) e decisão econômica interna (award/contract). A constituição manda determinismo no lado interno. Findings sobre "tolerar ambiguidade no input" só são T1 se essa tolerância vaza para a decisão (ranking, award, persistência). Pure-input-side concerns (ex: WhatsApp formatting) são fora de escopo (Phase A4).

---

## 2. Constituição aplicável

Mesma da Fase A2: `docs/governance.md`. Cláusulas-chave (já citadas nos prompts dos auditores):

- §2.1 Lifecycle canônico: RFQ → Quotes → Ranking → Award → Contract
- §2.2 Award rules: exactly one canonical action; no award without contract; no contract without RFQ
- §2.3 Message governance: invitations persisted; terms sent = stored; messages are evidence
- §2.4 Correlation: canonical id `RFQ#<rfq_number>`; mandatory in outbound; INBOUND ONLY via canonical id
- §2.5 Ranking: deterministic, spread-based, no ties allowed, incomplete quotes hard-fail
- §2.6 Hard-fails: ranking non-deterministic / ambiguous dates / missing evidence / contracts not reconstructable; no silent fallback, no heuristic correction, no mixed regimes, no mutation without evidence
- §2.7 Output contract: precise, structured, verifiable, audit-friendly, free of speculation

Se um auditor citar uma cláusula que você considera mal-aplicada (e.g., flag um Tier 1 por "violação de §2.5" mas o código respeita), você corrige isso. Cite a cláusula correta no veredicto.

---

## 3. Escopo de revisão

### 3.1 Arquivos auditados (mesmo escopo dos auditores)
- `backend/app/services/rfq_service.py`
- `backend/app/services/rfq_orchestrator.py`
- `backend/app/services/rfq_engine.py`
- `backend/app/services/rfq_message_builder.py`
- `backend/app/api/routes/rfqs.py`
- `backend/app/models/rfqs.py`
- `backend/app/models/quotes.py`
- `backend/app/schemas/rfq.py`

### 3.2 Inputs (relatórios dos auditores)
- `docs/audits/2026-05-06-phase-a2-findings-opus.md`
- `docs/audits/2026-05-06-phase-a2-findings-gemini.md`

Leia ambos integralmente antes de começar adjudicação. Anote em rascunho mental: para cada finding, marque convergência/divergência preliminar antes de abrir os arquivos de código.

### 3.3 Cross-references aceitas
- `docs/governance.md`
- `backend/app/models/contracts.py` (HedgeContract — para validar `award` invariants)
- `backend/app/services/linkage_service.py` (call site within `award`)
- `backend/alembic/versions/*` que toquem rfqs / rfq_invitations / rfq_state_events / rfq_quotes / rfq_sequences
- `backend/tests/test_rfq*.py`, `test_rfqs_step*.py` (apenas para confirmar invariantes assumidos, não para auditar)

Não vá além desse perímetro. Esta é Fase A2; outros módulos (valuation/MTM, integrations/whatsapp/llm, cross-cutting/security, frontend) são outras fases. Findings que tocam módulos A4 (whatsapp_service, webhook_processor, llm_agent) devem ser tratados:
- **Como `cross-phase-A4-deferred`** se o auditor flag o boundary do A2 dependendo de A4.
- **Descartados** se o auditor auditou A4 internals (fora de escopo).

---

## 4. Rubrica de adjudicação

Para cada finding em cada um dos 2 relatórios, classifique:

| Classe | Regra | Ação |
|---|---|---|
| **Convergent** | Ambos flagaram a mesma root cause (IDs e wording podem diferir) | Promover ao plano consolidado. Severidade = max(Opus, Gemini) — **worst-of severity rule**. |
| **Opus-only** | Apenas Opus | Validar lendo o código. Se real e Tier 1/2 → promover. Se Tier 3 borderline → defer ou promover conforme rigor. Se FP → anti-finding. |
| **Gemini-only** | Apenas Gemini | Mesmas regras. Gemini com 1M context tende a achar cross-arquivo issues que Opus pode ter perdido — não desconsidere por reflexo. |
| **FP convergent** | Ambos flagaram mas o código não exibe o bug (verificado por leitura direta) | Anti-finding. Documente por quê é FP. |
| **Subsumption** | Finding A's fix subsume finding B (e.g., A deleta um caminho, B critica um bug nesse caminho) | Marcar B como `subsumed-by:A`. |
| **Out-of-scope** | Finding aborda arquivo/regra fora da Fase A2 | Marcar como `out-of-scope-defer-to-phase-X` (se cabe em outra fase) ou descartar. |
| **Cross-phase-A4** | Finding correto que descreve dependência de A2 sobre módulos A4 (whatsapp, llm, webhook) | Promover apenas se o **boundary dentro de A2** viola governance assumindo o pior comportamento do módulo A4. Marcar `cross-phase-A4-deferred` para a fase A4 herdar. |

### 4.1 Regras de severidade

- **Worst-of severity:** Opus diz Tier 2, Gemini diz Tier 1, mesma root cause → veredicto Tier 1.
- **Constitutional violation = Tier 1 minimum.** Se ambos disseram Tier 2 mas o finding é violação direta da constituição (ranking não-determinístico em path econômico, correlação por non-canonical-id, audit gap em award, evidência mutável) → upgrade para Tier 1.
- **Implementer-flagged divergences:** N/A nesta fase (não há implementador).

### 4.2 FP detection — `claimed-mechanism` pattern

Se um auditor cita uma biblioteca/função/comportamento por nome (e.g., "Python dict preserves insertion order since 3.7", "Decimal.quantize defaults to ROUND_HALF_EVEN", "asyncpg uses pg's READ COMMITTED"), **verifique que o código realmente invoca essa biblioteca/função com os parâmetros que disparam esse comportamento.** Padrão recorrente: auditor cita mecanismo correto mas aplicado a código que não o usa daquela forma.

Marque tais findings como anti-findings com rebuttal explícito (citação do código real).

### 4.3 Ranking determinism — bias check

Auditores devem flagar Decimal→float collapse no `compute_trade_ranking` / `compute_spread_ranking`. **Se ambos missed isso ou se ambos flagaram mas você considera que não é problema na faixa de preços real do negócio**, justifique explicitamente — não reflexo, leitura. A faixa de preços de commodities (USD/MT em centenas a alguns milhares; cents = 4 dígitos significativos após vírgula) está dentro da precisão de IEEE 754 double (~15-17 dígitos significativos). Mas tie detection sobre `set(floats)` é frágil sob inputs adversariais (uma counterparty enviando price com 18 dígitos de precisão poderia disparar tie falso ou esconder tie real). Exercite julgamento institucional.

### 4.4 Fresh discovery (raro mas permitido)

Se ao validar findings você descobrir um Tier 1 que **ambos** auditores perderam, surface como `J-A2-FRESH-NN` com evidência. Use sparingly — sua função é adjudicação, não nova descoberta.

---

## 5. Output format — STRICT

Você produz **um único arquivo Markdown** salvo em:

```
docs/audits/2026-05-06-phase-a2-jury-verdict.md
```

### Estrutura obrigatória

```markdown
# Phase A2 — Stage 3 Jury — Consolidated Verdict

**Date:** 2026-05-06
**Phase:** A2 — RFQ Lifecycle
**Inputs:**
- Auditor A: docs/audits/2026-05-06-phase-a2-findings-opus.md (commit <SHA>)
- Auditor B: docs/audits/2026-05-06-phase-a2-findings-gemini.md (commit <SHA>)
**Code state:** <`git rev-parse HEAD` of audit branch>

## 1. Verdict summary

- **Tier 1 (Critical, constitutional violation, ship-blocker):** N findings
- **Tier 2 (High, should fix pre-prod):** N findings
- **Tier 3 (Medium, defer-acceptable):** N findings
- **Tier 4 (Low, hygiene):** N (count only, no detail)
- **Anti-findings (rejected from Stage 1/2):** N items
- **Subsumed:** N items
- **Cross-phase-A4 deferred:** N items

**Overall constitutional posture:** PASS / PASS-WITH-FIXES / FAIL

If FAIL: explicit reason (e.g., "Tier 1 ranking non-determinism at rfq_service.py:NNN; constitution §2.5 violated; cannot ship without fix.")

## 2. Convergent findings (both auditors caught — high confidence)

### J-A2-01 — <Consolidated title>
- **Adjudicated severity:** Tier N
- **Constitutional rule:** §2.X
- **Source findings:** F-A2-OPUS-NN + F-A2-GEMINI-MM
- **Files\Lines:** `backend/app/services/rfq_service.py:206-320`
- **Issue:**
  > <Quote actual code from repo at this commit>
- **Mechanism (jury-verified):**
  Walk-through. You read the code; cite path:line for each step.
- **Recommended fix direction:**
  Concrete directive that a remediation agent can implement. NOT a patch.
- **Acceptance criteria for remediation:**
  - [ ] Code change at path:line
  - [ ] Test asserting fix
  - [ ] No regression in adjacent tests
- **Reasoning over reviewers:**
  If you adopted Opus's framing or Gemini's framing, or synthesized — say so. Brief.

### J-A2-02 — ...

## 3. Opus-only findings (jury-validated)

### J-A2-OPUS-01 — <Title>
- (Same structure as Convergent.)
- **Why Gemini missed:** Brief 1-line guess (e.g., "single-file finding in `compute_trade_ranking`; Gemini's cross-file lens didn't surface it.")

## 4. Gemini-only findings (jury-validated)

### J-A2-GEMINI-01 — <Title>
- (Same structure.)
- **Why Opus missed:** Brief 1-line guess (e.g., "cross-file linkage between `award` call site and `linkage_service` boundary; Gemini's longer context caught it.")

## 5. Anti-findings (FPs from Stage 1/2)

### A-A2-J-01 — <Reviewer claim>
- **Source:** F-A2-OPUS-NN or F-A2-GEMINI-MM
- **Reviewer claim:**
  > <Quote reviewer's claim>
- **Actual code:**
  > <Quote real code from repo>
- **Why it is NOT a bug:**
  Brief mechanism. Cite library/spec/standard if relevant.

## 6. Subsumed findings

### S-A2-J-01 — F-A2-X-NN subsumed by J-A2-MM
- **Reason:** <e.g., "J-A2-03 directive replaces the entire `award` transaction boundary; F-A2-X-04 asks to fix a sub-bug in that boundary — subsumed.">

## 7. Fresh findings (jury caught what both missed — rare)

### J-A2-FRESH-01 — <Title>
- (Same structure as Convergent.)
- **Why both missed:** Brief 1-line.
- **Confidence:** {high / medium} — only surface high-confidence.

## 8. Cross-phase-A4 deferred

### X-A2-J-01 — <Boundary issue>
- **A2 surface:** `path:linha` that depends on A4 module
- **A4 dependency:** module / function (whatsapp_service / webhook_processor / llm_agent)
- **Governance clause at risk:** §2.X (typically §2.4 correlation or §2.5 incomplete-quote)
- **Why deferred to A4:** brief reason
- **What A4 audit must verify:** 1-2 sentences for the future Phase A4 prompt author

## 9. Open questions for orchestrator

(Findings where you genuinely couldn't decide. Should be rare. Each item: what you'd need to confirm/refute. Max 3.)

## 10. Remediation dispatch metadata

For the orchestrator to decide remediation scope:

- **Total Tier 1 fixes required:** N
- **Total Tier 2 fixes required:** N
- **Total Tier 3 fixes deferrable:** N
- **Estimated remediation scope:** {single PR, or split per concern — suggested wave/PR breakdown by file/concern}
- **Critical sequencing:** any fix that must precede another (e.g., "fix J-A2-01 ranking determinism before J-A2-04 award path; ranking is dep of award")
- **Required regression tests:**
  - test_X.py — covers J-A2-NN
  - test_Y.py — covers J-A2-MM

## 11. Self-bias confession (mandatory)

Per the 3-model audit pattern:

- **Findings I reversed from my first pass:** N (and which IDs)
- **Findings where I gave benefit-of-doubt to a reviewer:** N (and which IDs)
- **Findings where I overruled both reviewers:** N (and which IDs)
- **Findings where I disagreed with worst-of-severity and downgraded:** N (and which IDs + justification)

If 0 of all four: state explicitly. The orchestrator interprets a 0-0-0-0 confession as either an unusually clean phase or a passive jury — they will look harder at the diff if so.
```

### Regras de output

- **Quote actual code from repo.** Não cole as citações dos auditores; valide lendo o arquivo no commit corrente.
- **Cite cláusula constitucional por número.**
- **Não duplique. Subsuma sempre que possível.**
- **Tier 4: count only, no detail.**
- **Não proponha features novas. Não amplie escopo.**
- **Não comente sobre o processo do orquestrador.**
- **Não sugira novos despachos** (orquestrador decide).
- **Cross-phase-A4 deferred é uma seção legítima** — o jury que recolhe boundary issues e os encaminha para a Phase A4 future audit. Não promova um cross-phase issue para Tier 1 do veredicto A2 a menos que a violação aconteça **dentro de A2** (call site).

---

## 6. Anti-patterns

- ❌ Aceitar claim de auditor sem ler o código.
- ❌ "I agree with Opus" sem walkthrough do mecanismo.
- ❌ Promover findings de Tier 3 para Tier 1 sem justificativa constitucional explícita.
- ❌ Ignorar findings que parecem corretos mas vêm em wording confuso — leia o código e decida pelo mecanismo.
- ❌ Cair em viés de "ambos disseram, deve ser real" — verifique convergent FPs ativamente.
- ❌ Pad Tier 4 com hygiene noise — só contagem.
- ❌ Sugerir "talvez seja melhor refatorar X" — fora do seu papel; só Tier 1/2/3 fixes acionáveis.
- ❌ Auditar internals de módulos A4 (whatsapp/webhook/llm) — boundary apenas, e em seção dedicada.

---

## 7. Stop posture

Salve em `docs/audits/2026-05-06-phase-a2-jury-verdict.md`. Reporte ao orquestrador:
- Path do arquivo
- Verdict summary (PASS / PASS-WITH-FIXES / FAIL)
- Tier 1 + Tier 2 counts
- Quaisquer fresh findings
- Cross-phase-A4 deferred count
- Self-bias confession summary

**PARE.** Não proponha patches. Não escolha próxima fase. Não comente metodologia.

O orquestrador apresenta seu veredicto ao usuário. Usuário decide próxima ação (remediação por PR, deferimento, próxima fase).

---

## 8. Tempo e disciplina

Slow is smooth, smooth is fast. Auditoria adversarial só vale o que o jury investe nela. Cada finding sob disputa merece o tempo da leitura direta do código. Sem deadline; profundidade > velocidade.

Boa adjudicação.
