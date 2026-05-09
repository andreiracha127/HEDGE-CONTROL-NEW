# Phase A3 — Stage 3 Jury Adjudication — GPT 5.5

**Phase:** A3 — Valuation (MTM · P&L · Cashflow · Scenario)
**Stage:** 3 — Jury (independent adjudication of Stage 1 + Stage 2 findings)
**Target model:** GPT 5.5 (or strongest available reasoning model)
**Authoring date:** 2026-05-09
**Repo:** `Hedge-Control-New` (this working directory)
**Branch:** `audit/phase-a3` (read-only audit — do NOT modify code)

> **Instruções operacionais.** Você é o Jury independente que adjudica os findings de Phase A3. Você tem acesso aos arquivos do repo (Read/Grep/Glob/Serena disponíveis), à constituição em `docs/governance.md`, e aos dois relatórios de Stage 1 + Stage 2 já produzidos. Sua única tarefa é produzir um **veredicto consolidado** que serve de input para as remediation waves.

---

## 1. Inputs obrigatórios (leia ANTES de adjudicar)

1. **`docs/governance.md`** — constituição completa. Cláusulas centrais para A3: §131–146 (VALUATION/MTM/CASHFLOW), §149–156 (SCENARIO/WHAT-IF), §159–174 (HARD FAILS), §208–217 (OUTPUT CONTRACT).
2. **`docs/audits/2026-05-09-phase-a3-findings-opus.md`** — Stage 1 findings do Auditor A (Opus 4.7).
3. **`docs/audits/2026-05-09-phase-a3-findings-gemini.md`** — Stage 2 findings do Auditor B (Gemini 3.1 Pro).
4. **`docs/audits/2026-05-09-phase-a3-stage1-opus-prompt.md`** — prompt que ambos os auditors receberam (verifique que o escopo deles foi consistente; flag qualquer drift).
5. **Code in scope** — `backend/app/services/{mtm_*,pl_calculation,cashflow_*,scenario_whatif,price_lookup}_service.py` mais os models, routes, schemas e migrations relevantes (per §3 do prompt de Stage 1).

Você tem permissão de **ler código diretamente** para verificar findings disputados, redundantes, ou inconclusivos. Você NÃO modifica código.

---

## 2. Adjudication rules

### 2.1 Severity tier (worst-of)

Para cada finding citado por algum dos auditors, sua severity final é o **MAIOR (mais severo)** entre:
- A severity declarada pelo Auditor A (se citou).
- A severity declarada pelo Auditor B (se citou).
- A severity que VOCÊ atribui após verificar o código.

Você nunca rebaixa abaixo do worst-of declarado. Pode promover (e.g., A disse T2, B disse T2, mas você verifica e é T1 → T1).

### 2.2 Convergence vs divergence

- **Convergent finding** = ambos os auditors citaram o mesmo issue (provavelmente sob nomes diferentes; reconcilie via `path:line`). Mark `convergent`.
- **Auditor-A-only** ou **Auditor-B-only** = só um citou. Verifique no código. Se válido → mark `<auditor>-only`. Se inválido → mark `false-positive` (anti-finding).
- **Subsumption** — finding X é caso especial / sub-instância de finding Y. Mark Y como adjudicado, X como `subsumed-by-Y`.
- **Fresh** — você descobre um issue que NEM A NEM B citaram. Mark `fresh-from-jury`. Esses são valiosos — A3 é maduro mas surfaces novas aparecem.

### 2.3 Anti-findings

Se um auditor cita algo que após verificação você determina NÃO é uma violação, mark `anti-finding`. Documente porque o código está correto. Anti-findings são institucionalmente valiosos — auditors não são infalíveis e o registro do "pensei que era bug, não é" treina o cycle.

### 2.4 Cross-phase deferral

Findings que tocam Phase A4 (`webhook_processor`, `whatsapp_*`, `llm_agent`), Phase A5 (`audit_trail_service`, `core/auth`, `core/rate_limit`), ou Phase A6 (frontend) — mark `deferred-to-phase-XX`. Não conte no total A3 mas liste em §8 do verdict.

### 2.5 Self-bias confession

Você é GPT 5.5 — Auditor B (Gemini) é seu "competitor" mais próximo, Auditor A (Opus) é o "competitor" mais distante. Há risco institucional de viés (favorecer Opus por independência percebida; ser severo com Gemini). **Confesse explicitamente** em §9 do verdict qualquer caso onde você notou hesitação em validar/invalidar finding com base no auditor de origem. Self-bias confession é parte do rigor.

---

## 3. Verdict format

Você produz **um único arquivo markdown** em `docs/audits/2026-05-09-phase-a3-jury-verdict.md` com a estrutura abaixo.

```
# Phase A3 — Stage 3 Jury Verdict — GPT 5.5

## §0 Posture (overall)
PASS / FAIL / FAIL-WITH-CRITICAL-CAVEATS
<one-paragraph rationale>

## §1 Headline statistics
- Stage 1 raw: NN findings (Auditor A — Opus)
- Stage 2 raw: NN findings (Auditor B — Gemini)
- Convergent: NN
- Auditor-A-only validated: NN
- Auditor-B-only validated: NN
- Fresh-from-jury: NN
- Anti-findings: NN
- Subsumed: NN
- Cross-phase deferred: NN
- **Total adjudicated A3 findings: NN** (T1: NN | T2: NN | T3: NN | T4: NN)

## §2 Convergent findings (both auditors caught)

### J-A3-NN — <title>
- Tier: T1/T2/T3/T4
- Convergent (Opus: <their-id>; Gemini: <their-id>)
- Surface: path:line
- Constitutional clause: governance.md:NNN-NNN
- Evidence: code citation + walkthrough
- Suggested remediation surface: file/function

### J-A3-NN+1 — ...

## §3 Auditor-A-only validated

### J-A3-OPUS-NN — <title>
(same shape as §2 + "validated by jury via <code path>")

## §4 Auditor-B-only validated

### J-A3-GEMINI-NN — <title>
(same shape)

## §5 Fresh-from-jury

### J-A3-FRESH-NN — <title>
(same shape + "neither auditor cited; jury discovery")

## §6 Anti-findings

### A3-ANTI-NN — <auditor's claim>
- Auditor: A or B
- Claim: <what they said>
- Why-not: <code citation showing it is correct>

## §7 Subsumed

### A3-SUBSUMED-NN — <subsumed claim> ⊂ J-A3-MM
- Reason: <why finding X is a sub-instance of finding Y>

## §8 Cross-phase deferred

### X-A3-J-NN — <title>
- Defer to: Phase A4 / A5 / A6
- A3 surface: where the boundary touches
- Why deferred: which file is owned by the other phase
- A4/A5/A6 audit must verify: <institutional verifier>

## §9 Self-bias confession
<one paragraph: any case where I hesitated based on auditor origin; confession of viés>

## §10 Remediation plan recommendation

Suggest a wave structure for the executor PRs that close the adjudicated findings. Group by file-locality + dependency graph + scope coherence:
- Wave 1 (foundational, no upstream deps): PR-X (J-A3-NN, J-A3-MM, ...)
- Wave 2 (depends on W1): PR-Y (J-A3-NN, ...)
- Cross-phase: defer X-A3-J-NN to Phase A4 audit
```

---

## 4. Workflow

1. Read all 5 inputs from §1.
2. For each Stage 1 finding: cross-reference against Stage 2; classify as convergent / A-only / B-only.
3. For each B finding not in A's list: classify as B-only.
4. Verify each finding by reading the code. Reject (anti-finding) if false-positive; promote tier if you find evidence A and B both missed.
5. Scan independently for issues neither auditor caught; mark fresh-from-jury.
6. Apply worst-of severity rule.
7. Write the verdict to `docs/audits/2026-05-09-phase-a3-jury-verdict.md`.
8. Final commit message: `docs(audits): Phase A3 Stage 3 jury verdict`.
9. Stop. Orchestrator + remediation waves take over from here.

---

## 5. Anti-flatten rules

- Do NOT collapse two distinct findings into one because they share a surface. Two violations on the same line are two findings.
- Do NOT promote T2/T3 to T1 just to make the verdict look stricter. Severity ladder is real.
- Do NOT dismiss a hard-fail clause violation as "edge case unlikely". Hard-fails are categorical.
- Do NOT accept a finding's reasoning at face value if the cited code path is hand-waved. Verify or reject.

---

## 6. Worth-of-jury principle

Os auditors são adversariais por design. Você é o adjudicador. Sua superpower:
- Você tem acesso aos DOIS reports + ao codebase + à constituição.
- Você pode verificar quando A discorda de B.
- Você pode descobrir o que ambos perderam (fresh-from-jury).
- Você pode confessar viés sem perder credibilidade — viés confesso é viés removido.

Aplique todas. Boa caça.
