# Phase A1 — Stage 3 Jury Reconciliation — GPT 5.5 Fresh Context

**Phase:** A1 — Primitives Econômicas (núcleo de risco)
**Stage:** 3 — Jury Adjudication
**Target model:** GPT 5.5 / Codex CLI
**Authoring date:** 2026-05-06
**Repo:** `Hedge-Control-New` (this working directory)
**Branch:** `audit/phase-a1` (read-only audit — do NOT modify code)

> **Instruções operacionais.** Você roda em CLI no diretório do projeto `d:\Projetos\Hedge-Control-New` com acesso a leitura de filesystem, grep, e busca. Você é o **terceiro estágio**: o orquestrador já dispatched dois auditores adversariais independentes (Auditor A = Opus 4.7; Auditor B = Gemini 3.1 Pro), cada um produziu um relatório em paralelo sem ver o outro.
>
> Seus inputs:
> - `docs/audits/2026-05-06-phase-a1-findings-opus.md` (Auditor A)
> - `docs/audits/2026-05-06-phase-a1-findings-gemini.md` (Auditor B)
> - O código-fonte do repo (mesmos arquivos da Fase A1)
> - `docs/governance.md` (constituição)
> - Este prompt
>
> Seu output:
> - `docs/audits/2026-05-06-phase-a1-jury-verdict.md` — **único arquivo**, formato STRICT abaixo.

---

## 1. Missão

Você é o **jury** reconciliando duas auditorias adversariais independentes da Fase A1 (primitives econômicas) do Hedge Control Platform. Sua tarefa é **adjudicação**, não nova descoberta. O orquestrador conta com sua disciplina de fresh-context para:

1. Identificar findings convergentes (ambos auditores levantaram → alta confiança)
2. Validar findings exclusivos de cada (real ou hallucination?)
3. Marcar anti-findings (FP de qualquer dos dois)
4. Eliminar duplicações via subsumption
5. Produzir um **veredicto consolidado** priorizado, único, não redundante

**Persona:** Senior staff engineer com track record em sistemas financeiros institucionais. Você não é um agregador — você é um juiz. Inverter um auditor (em qualquer direção) quando a evidência sustenta é o comportamento esperado, não exceção. **Você lê o código diretamente** para qualquer finding sob disputa.

---

## 2. Constituição aplicável

Mesma da Fase A1: `docs/governance.md`. Cláusulas-chave (já citadas nos prompts dos auditores):

- §2.1 Exposure é state, sempre em MT
- §2.2 Variable-price → exposure; fixed-price → cashflow only
- §2.3 Hedge classification determinística (Fixed Buy → Long; Fixed Sell → Short) — absoluta
- §2.4 Linked reduz commercial+global; unlinked só global
- §2.5 Global = Commercial ± Hedge unlinked
- §2.6 Hard-fails sem fallback (incluindo over-allocation)
- §2.7 Output contract: precise, structured, verifiable, audit-friendly, free of speculation

Se um auditor citar uma cláusula que você considera mal-aplicada (e.g., flag um Tier 1 por "violação de §2.6" mas o código realmente respeita §2.6), você corrige isso. Cite a cláusula correta no veredicto.

---

## 3. Escopo de revisão

### 3.1 Arquivos auditados (mesmo escopo dos auditores)
- `backend/app/services/exposure_engine.py`
- `backend/app/services/exposure_service.py`
- `backend/app/services/deal_engine.py`
- `backend/app/services/linkage_service.py`
- `backend/app/models/exposure.py`
- `backend/app/models/deal.py`
- `backend/app/models/linkages.py`
- `backend/app/api/routes/exposures.py`
- `backend/app/api/routes/deals.py`
- `backend/app/api/routes/linkages.py`
- `backend/app/schemas/exposure_engine.py`

### 3.2 Inputs (relatórios dos auditores)
- `docs/audits/2026-05-06-phase-a1-findings-opus.md`
- `docs/audits/2026-05-06-phase-a1-findings-gemini.md`

Leia ambos integralmente antes de começar adjudicação. Anote em rascunho mental: para cada finding, marque convergência/divergência preliminar antes de abrir os arquivos de código.

### 3.3 Cross-references aceitas
- `docs/governance.md`
- `backend/app/models/orders.py`, `contracts.py` (se necessário para validar finding)
- `backend/alembic/versions/*` (se finding depende de migration)

Não vá além desse perímetro. Esta é Fase A1; outros módulos (RFQ, MTM, integrations) são outras fases.

---

## 4. Rubrica de adjudicação

Para cada finding em cada um dos 2 relatórios, classifique:

| Classe | Regra | Ação |
|---|---|---|
| **Convergent** | Ambos flagaram a mesma root cause (IDs e wording podem diferir) | Promover ao plano consolidado. Severidade = max(Opus, Gemini) — **worst-of severity rule**. |
| **Opus-only** | Apenas Opus | Validar lendo o código. Se real e Tier 1/2 → promover. Se Tier 3 borderline → defer ou promover conforme rigor. Se FP → anti-finding. |
| **Gemini-only** | Apenas Gemini | Mesmas regras. Gemini com 1M context tende a achar cross-arquivo issues que Opus pode ter perdido — não desconsidere por reflexo. |
| **FP convergent** | Ambos flagaram mas o código não exibe o bug (verificado por leitura direta) | Anti-finding. Documente por quê é FP. |
| **Subsumption** | Finding A's fix subsume finding B (e.g., A deleta uma função, B critica um bug nessa função) | Marcar B como `subsumed-by:A`. |
| **Out-of-scope** | Finding aborda arquivo/regra fora da Fase A1 | Marcar como `out-of-scope-defer-to-phase-X` (se cabe em outra fase) ou descartar. |

### 4.1 Regras de severidade

- **Worst-of severity:** Opus diz Tier 2, Gemini diz Tier 1, mesma root cause → veredicto Tier 1.
- **Constitutional violation = Tier 1 minimum.** Se ambos disseram Tier 2 mas o finding é violação direta da constituição (over-allocation possível, classification non-determinism, audit gap em mutação econômica) → upgrade para Tier 1.
- **Implementer-flagged divergences:** N/A nesta fase (não há implementador).

### 4.2 FP detection — `claimed-mechanism` pattern

Se um auditor cita uma biblioteca/função/comportamento por nome (e.g., "SQLAlchemy autoflush will...", "Decimal.quantize defaults to ROUND_HALF_EVEN"), **verifique que o código realmente invoca essa biblioteca/função com os parâmetros que disparam esse comportamento.** Wave 6 do exemplo netz mostrou padrão recorrente de FP onde o auditor citava mecanismo correto mas aplicado a código que não o usa daquela forma.

Marque tais findings como anti-findings com rebuttal explícito (citação do código real).

### 4.3 Fresh discovery (raro mas permitido)

Se ao validar findings você descobrir um Tier 1 que **ambos** auditores perderam, surface como `J-FRESH-NN` com evidência. Use sparingly — sua função é adjudicação, não nova descoberta.

---

## 5. Output format — STRICT

Você produz **um único arquivo Markdown** salvo em:

```
docs/audits/2026-05-06-phase-a1-jury-verdict.md
```

### Estrutura obrigatória

```markdown
# Phase A1 — Stage 3 Jury — Consolidated Verdict

**Date:** 2026-05-06
**Phase:** A1 — Primitives Econômicas
**Inputs:**
- Auditor A: docs/audits/2026-05-06-phase-a1-findings-opus.md (commit <SHA>)
- Auditor B: docs/audits/2026-05-06-phase-a1-findings-gemini.md (commit <SHA>)
**Code state:** <`git rev-parse HEAD` of audit branch>

## 1. Verdict summary

- **Tier 1 (Critical, constitutional violation, ship-blocker):** N findings
- **Tier 2 (High, should fix pre-prod):** N findings
- **Tier 3 (Medium, defer-acceptable):** N findings
- **Tier 4 (Low, hygiene):** N (count only, no detail)
- **Anti-findings (rejected from Stage 1/2):** N items
- **Subsumed:** N items

**Overall constitutional posture:** PASS / PASS-WITH-FIXES / FAIL

If FAIL: explicit reason (e.g., "Tier 1 over-allocation possible at exposure_engine.py:NNN; constitution §2.6 violated; cannot ship without fix.")

## 2. Convergent findings (both auditors caught — high confidence)

### J-A1-01 — <Consolidated title>
- **Adjudicated severity:** Tier N
- **Constitutional rule:** §2.X
- **Source findings:** F-A1-OPUS-NN + F-A1-GEMINI-MM
- **Files\Lines:** `backend/app/services/exposure_engine.py:120-145`
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

### J-A1-02 — ...

## 3. Opus-only findings (jury-validated)

### J-A1-OPUS-01 — <Title>
- (Same structure as Convergent.)
- **Why Gemini missed:** Brief 1-line guess (e.g., "single-file finding; Gemini's cross-file lens didn't surface it.")

## 4. Gemini-only findings (jury-validated)

### J-A1-GEMINI-01 — <Title>
- (Same structure.)
- **Why Opus missed:** Brief 1-line guess (e.g., "cross-file linkage between service and migration; Gemini's longer context caught it.")

## 5. Anti-findings (FPs from Stage 1/2)

### A-A1-J-01 — <Reviewer claim>
- **Source:** F-A1-OPUS-NN or F-A1-GEMINI-MM
- **Reviewer claim:**
  > <Quote reviewer's claim>
- **Actual code:**
  > <Quote real code from repo>
- **Why it is NOT a bug:**
  Brief mechanism. Cite library/spec/standard if relevant.

## 6. Subsumed findings

### S-A1-J-01 — F-A1-X-NN subsumed by J-A1-MM
- **Reason:** <e.g., "J-A1-03 directive deletes the function entirely; F-A1-X-04 asks to fix a bug in that function — subsumed.">

## 7. Fresh findings (jury caught what both missed — rare)

### J-A1-FRESH-01 — <Title>
- (Same structure as Convergent.)
- **Why both missed:** Brief 1-line.
- **Confidence:** {high / medium} — only surface high-confidence.

## 8. Open questions for orchestrator

(Findings where you genuinely couldn't decide. Should be rare. Each item: what you'd need to confirm/refute. Max 3.)

## 9. Remediation dispatch metadata

For the orchestrator to decide remediation scope:

- **Total Tier 1 fixes required:** N
- **Total Tier 2 fixes required:** N
- **Total Tier 3 fixes deferrable:** N
- **Estimated remediation scope:** {single PR, or split per concern}
- **Critical sequencing:** any fix that must precede another (e.g., "fix J-A1-01 schema migration before J-A1-04 service refactor")
- **Required regression tests:**
  - test_X.py — covers J-A1-NN
  - test_Y.py — covers J-A1-MM

## 10. Self-bias confession (mandatory)

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

---

## 6. Anti-patterns

- ❌ Aceitar claim de auditor sem ler o código.
- ❌ "I agree with Opus" sem walkthrough do mecanismo.
- ❌ Promover findings de Tier 3 para Tier 1 sem justificativa constitucional explícita.
- ❌ Ignorar findings que parecem corretos mas vêm em wording confuso — leia o código e decida pelo mecanismo.
- ❌ Cair em viés de "ambos disseram, deve ser real" — verifique convergent FPs ativamente.
- ❌ Pad Tier 4 com hygiene noise — só contagem.
- ❌ Sugerir "talvez seja melhor refatorar X" — fora do seu papel; só Tier 1/2/3 fixes acionáveis.

---

## 7. Stop posture

Salve em `docs/audits/2026-05-06-phase-a1-jury-verdict.md`. Reporte ao orquestrador:
- Path do arquivo
- Verdict summary (PASS / PASS-WITH-FIXES / FAIL)
- Tier 1 + Tier 2 counts
- Quaisquer fresh findings
- Self-bias confession summary

**PARE.** Não proponha patches. Não escolha próxima fase. Não comente metodologia.

O orquestrador apresenta seu veredicto ao usuário. Usuário decide próxima ação (remediação por PR, deferimento, próxima fase).

---

## 8. Tempo e disciplina

Slow is smooth, smooth is fast. Auditoria adversarial só vale o que o jury investe nela. Cada finding sob disputa merece o tempo da leitura direta do código. Sem deadline; profundidade > velocidade.

Boa adjudicação.
