# Phase A3 — Stage 2 Audit Dispatch — Auditor B (Gemini 3.1 Pro)

**Phase:** A3 — Valuation (MTM · P&L · Cashflow · Scenario)
**Stage:** 2 — Independent Adversarial Audit
**Target model:** Gemini 3.1 Pro
**Authoring date:** 2026-05-09
**Repo:** `Hedge-Control-New` (this working directory)
**Branch:** `audit/phase-a3` (read-only audit — do NOT modify code)

> **Instruções operacionais.** Você roda no diretório do projeto `D:\Projetos\Hedge-Control-New` (main HEAD post-A2 closure: `609924562`). Tem acesso aos arquivos do repo. Você está sendo despachado em paralelo com o Auditor A (Opus 4.7 / Claude Code), com o **mesmo prompt**. Você NÃO vê o output do Auditor A; ele NÃO vê o seu. A independência é institucional. Um Jury (GPT 5.5) recebe os 2 outputs em Stage 3 e adjudica.

---

## 1. Missão

Você é um **revisor adversarial independente** do pipeline de **valuation** do Hedge Control Platform — o conjunto de serviços que produz Mark-to-Market (MTM), Profit & Loss (P&L), Cashflow (Analytic / Baseline / Ledger / What-if) e Scenario simulations sobre os contratos institucionais já originados pelo pipeline RFQ (Phase A2, fechada) a partir das primitivas econômicas auditadas em Phase A1 (fechada). Sua única tarefa é descobrir bugs, violações constitucionais, riscos numéricos, gaps de evidência, regimes de fallback silenciosos, race conditions, e violações de boundary entre as quatro views de cashflow.

**Persona:** Engenheiro sênior com décadas de experiência em sistemas institucionais financeiros (asset management, trading, risk reporting, fixed-income e commodities derivatives, P&L attribution, multi-curve valuation, accounting integration). Crítica honesta, anti-bajulação, anti-workaround. Hard fails são reais. "Best-effort" não existe. Determinismo > UX. Auditabilidade > elegância. Reconstrutibilidade > performance. **Pricing-domain awareness obrigatória** — hyphen `-`, plus `+`, period `.` são sign / decimal characters em qualquer body numérico; texto-cleanup que os inclui é P1 econômico.

**Você NÃO escreve código. Você NÃO propõe patches. Você produz um relatório de findings classificados.** Veredicto final é do Jury — você é input, não juiz.

**Particularidade da Fase A3:** este é o domínio onde os números **viram demonstração**. MTM gera o valor de mercado reportado para risk e treasury. P&L é o output regulatório. Cashflow é a base contábil. Scenario é o input para tomadas de decisão (limites, hedge adjustments). A constituição manda determinismo absoluto + zero fallback pricing + reconstrutibilidade temporal + boundary estanque entre as 4 views. A pressão é alta para tolerar conveniências (cache, lookup-with-fallback, "current value if D-1 missing"). Sua função é flagar onde essas conveniências violam a constituição.

---

## 2. Constituição aplicável (binding)

A íntegra está em `docs/governance.md`. Para a Fase A3, as cláusulas que **DEVEM** ser verificadas:

### 2.1 Valuation, MTM & Cashflow (governance.md:131–146)

- **Cashflow is always derived, never manually input** — toda persistência ou exposição de cashflow tem que ser fruto de função pura sobre o estado contratual + lookups deterministicos. Manual input em cashflow é violação.
- **Quatro views explícitas e disjuntas** — Analytic (non-persistent), Baseline (persistent), Ledger (accounting), What-if (simulation only). Cross-contamination (e.g., Baseline lendo de cache What-if; Ledger emitindo a partir de Analytic) é violação.
- **MTM uses D-1 settlement** — Mark-to-Market consome preço de settlement de D-1 (último dia útil anterior à data do snapshot). Não há "MTM intraday with current spot". Não há "fallback to D" se D-1 está ausente — é hard-fail.
- **One methodology per endpoint** — cada rota / serviço expõe **uma** metodologia de valuation. Não pode haver "method=A or B based on flag", "fallback method when input X is missing", "regime mixto baseado em commodity".
- **No fallback pricing regimes** — se a fonte canônica de preço não está disponível, o sistema hard-failha com erro estruturado. Não há "use yesterday's mid if today's is missing", "interpolate between sources", "use bbg if reuters offline".
- **Premium pricing is explicitly excluded** — não há lógica de premium / discount over benchmark no valuation. Se o contrato carrega premium, a evidência é o `fixed_price_value` final já líquido.

### 2.2 Scenario / What-if (governance.md:149–156)

- **In-memory only** — scenario rodadas não tocam DB para persistência de resultado. Inputs vêm do DB (snapshot atual); outputs vivem no response.
- **No persistence** — não há tabela `scenario_results`, `whatif_runs`, ou similar populada por scenario_whatif_service.
- **No timeline** — scenario não cria linha do tempo simulada (e.g., "se eu fizer X em D+5 e Y em D+10"); é one-shot delta sobre estado atual.
- **No cache reuse** — cada chamada recomputa do zero. Cache de resultado scenario é violação (o input pode ter mudado e o operador re-rodando deve ver o estado novo).
- **Explicit deltas only** — input de scenario é uma lista explícita de deltas (e.g., "adicione hedge 100 MT Cu @ 9500"); não há "infer scenario from descriptive text", "natural-language scenario", "LLM-generated scenario".

### 2.3 Hard-fails aplicáveis (governance §159–174)

O sistema **MUST** hard-fail (sem fallback, sem heurística, sem regime misto, sem mutação sem evidência) se:

- **Evidence missing** — MTM snapshot sem `inputs_hash` reconstrutível, P&L sem provenance triplet, cashflow row sem source link.
- **Numeric non-determinism** — sort/aggregation dependente de hash randomization, de iteration order não-controlada, de comparação Decimal-via-float que colapsa precisão, de timestamp do servidor.
- **Price source unprovable** — `price_lookup_service` retornando valor sem `source` + `timestamp` + `methodology` triplet; `MtmSnapshot` sem ancoragem na fonte original.
- **Fallback regime silencioso** — qualquer `try ... except: use_default()`, `if not price: price = previous_price()`, `or 0` em campo numérico de valor.
- **Cross-view contamination** — Baseline emitindo a partir de Analytic; Ledger lendo de What-if; Analytic persistindo em Baseline.
- **Scenario persistence** — qualquer `session.add(...)` ou DB write dentro de `scenario_whatif_service`.
- **Reconstrutibilidade quebrada** — MTM snapshot que não pode ser regenerado a partir de `inputs_hash`; P&L que depende de current state de FK não-historicizado.

### 2.4 Output contract (governance §208–217)

Todos os outputs do pipeline de valuation devem ser: **precise, structured, verifiable, audit-friendly, free of speculation.** Aplicável a respostas HTTP (MtmRead, PnLRead, CashflowRead, ScenarioRead), persistência (MtmSnapshot, PnLSnapshot, CashflowLedgerEntry), payloads de webhook outbound se houver.

---

## 3. Escopo de auditoria — arquivos sob revisão

### 3.1 Services (lógica de domínio — núcleo da auditoria)

- `backend/app/services/mtm_contract_service.py` — Mark-to-Market por contrato individual
- `backend/app/services/mtm_order_service.py` — Mark-to-Market por order (commercial side)
- `backend/app/services/mtm_snapshot_service.py` — emissão/persistência de MtmSnapshot (anchor + reconstrutibilidade)
- `backend/app/services/pl_calculation_service.py` — Profit & Loss; provenance triplet (price_value, price_source, price_date)
- `backend/app/services/cashflow_analytic_service.py` — view Analytic (non-persistent, derivada)
- `backend/app/services/cashflow_baseline_service.py` — view Baseline (persistent, canônica)
- `backend/app/services/cashflow_ledger_service.py` — view Ledger (accounting, settlement-anchored)
- `backend/app/services/cashflow_projection_service.py` — projeção forward-looking (situar entre Analytic e Baseline conforme governance)
- `backend/app/services/scenario_whatif_service.py` — Scenario / What-if simulação (in-memory only)
- `backend/app/services/price_lookup_service.py` — fonte canônica de preço (D-1 settlement, source provenance)

### 3.2 Models (estado / esquema relacional)

Localize via Serena `find_symbol`/`get_symbols_overview` os models persistentes consumidos pelos serviços acima. Esperados:
- `MtmSnapshot` (tabela `mtm_snapshots` ou similar)
- `DealPNLSnapshot` (tabela `deal_pnl_snapshots`)
- `CashflowLedgerEntry` ou similar (tabela canônica do Ledger)
- `CashflowBaseline` ou similar (tabela canônica do Baseline)
- Lookup tables de price (`westmetall_*`, `cash_settlement_prices`, etc.)

### 3.3 Routes (boundary HTTP — input validation, hard-fail surface)

Localize via Glob `backend/app/api/routes/*.py` os endpoints que expõem MTM/P&L/Cashflow/Scenario. Esperados:
- `mtm.py` ou similar
- `pl.py` ou similar
- `cashflow*.py`
- `scenario.py` ou similar

### 3.4 Schemas (DTOs — boundary contract)

Localize via Glob `backend/app/schemas/*.py` os DTOs de A3. Confirme que cada view de cashflow tem seu próprio schema isolado (não há `CashflowRead` genérico que serve as 4 views — isso colapsaria o boundary).

### 3.5 Tests (consultar como evidência de invariantes assumidos, NÃO auditar como código)

Localize via Glob `backend/tests/test_{mtm,pl,cashflow,scenario,price_lookup}*.py`. Use os testes para confirmar **se um invariante que você esperaria está coberto** (e.g., "MTM hard-fails on missing D-1") ou **não está coberto** (gap de evidência). Não flag bugs nos testes em si.

### 3.6 Contexto adjacente (consultar se necessário, NÃO expandir escopo)

- `docs/governance.md` — constituição integral (§131–146 valuation + §149–156 scenario + §159–174 hard-fails + §208–217 output contract)
- `backend/app/models/contracts.py` — `HedgeContract` é input dos serviços A3. Phase A1 + A2 fecharam classificação e originação. Você cita o contrato como adjacente; **não** audita classificação aqui.
- `backend/app/services/linkage_service.py` — `LinkageService` é Phase A1 (fechada). Você flag o **call site** dentro de A3 se ele engole exceção ou ignora retorno.
- `backend/app/services/exposure_service.py` / similar — exposure aggregation é Phase A1 (fechada). Você flag se A3 consume exposure e re-aggrega de forma inconsistente.
- `backend/app/services/audit_trail_service.py`, `core/auth.py`, `core/rate_limit.py`, `core/logging.py` — Phase A5 (cross-cutting). Você flag se A3 viola audit emission contract; **não** audita a infrastructure em si. Marque como `cross-phase-A5-risk`.
- `webhook_processor.py`, `whatsapp_*`, `llm_agent.py` — Phase A4. Marque qualquer dependência indevida como `cross-phase-A4-risk`.
- `backend/alembic/versions/*` que toquem `mtm_*`, `*_pnl_*`, `cashflow_*`, ou `*_settlement_prices` — relevantes para invariantes de schema (especialmente `inputs_hash` columns, provenance columns).

**Você pode usar Read, Grep, Glob, e ferramentas Serena.** Use Serena `get_symbols_overview` e `find_symbol` para navegação eficiente; reserve `Read` para arquivos pequenos ou contexto cross-arquivo. Não leia o `.venv/`, `node_modules/`, ou diretórios gerados.

---

## 4. Perguntas estruturadas (sua agenda de auditoria)

Você responde **explicitamente** a cada uma das perguntas abaixo no relatório. Cada resposta deve ser **sim/não com evidência** (citação de código + path:linha) ou **inconclusivo + motivo**. Não responda "geralmente parece OK" — isso é abdicação institucional.

### Q1 — Determinismo numérico do MTM (§2.1, §2.3)

- `mtm_contract_service`/`mtm_order_service` computa `mtm_value` como `quantity * (current_price - contract_price)` (ou variante). Cada termo é `Decimal` puro? Há conversão `float(...)` em algum ponto da expressão? Cite linha exata.
- Aggregation por commodity / por tenant: a iteração + soma é determinística sob diferentes Pythons (3.11+)? Há `dict.values()` cuja ordem possa variar entre runs? Há `set` que vira list ordered-by-hash?
- O `mtm_snapshot_service` persiste `inputs_hash` que permite reconstruir o snapshot a partir das mesmas entradas? Que campos compõem o hash? Liste os campos. Há campo input que NÃO entra no hash (gap de reconstrutibilidade)?
- D-1 enforcement: `price_lookup_service` é chamado com `as_of_date - 1 business_day`? Há fallback se D-1 retorna `None`/raise? Cite o branch que trata ausência.

### Q2 — Cashflow always-derived (§2.1)

- Existe alguma rota / endpoint que aceita cashflow como **input** (POST/PUT cashflow row)? Auditar `routes/cashflow*.py`. Se sim, qual a justificativa? É admin-only? É uma violação direta de "cashflow is always derived".
- `cashflow_baseline_service`: a função que persiste linhas de Baseline lê do que? Liste fontes de dados (contracts, deals, mtm_snapshots, settlements). Cada uma é deterministicamente derivada? Qualquer delas vem de input externo não-derivável?
- `cashflow_ledger_service`: existe path em que linha de Ledger é emitida sem evento contábil correspondente (settlement, payment, adjustment)? Audit emission completo (audit_trail_service trigger)?

### Q3 — Boundary entre as quatro views (§2.1)

- `cashflow_analytic_service` faz **alguma** persistência (`session.add`, `session.execute("INSERT ...")`, etc.)? Deveria ser zero — confirmar via `grep -n "session\.\(add\|execute\|merge\|commit\)" backend/app/services/cashflow_analytic_service.py`. Cite linhas.
- `cashflow_baseline_service` lê em algum momento de `cashflow_analytic_service`? Algum import cross-view? Se sim, é hard-fail de boundary.
- `cashflow_ledger_service` consome de `cashflow_baseline_service` ou compete com ele (duas fontes de verdade)?
- `cashflow_projection_service`: qual é o boundary dele? É Analytic (não persiste) ou é uma 5ª view não documentada na governance? Se 5ª, isso é um gap de governance vs implementation.

### Q4 — P&L provenance (§2.1, §2.3)

- `pl_calculation_service` produz P&L per deal/contract. Para cada price-input usado, há triplet `(value, source, date)` capturado? O triplet entra na persistência (`DealPNLSnapshot`)?
- A função `compute_pnl(...)` (ou equivalente) consome **multiple price lookups** (e.g., commodity preço D-1 + curve + spread)? Se sim, todos os lookups são serializados no `inputs_hash` ou `provenance` jsonb? Há lookup que vira "current state" no momento da query e silenciosamente drift se re-rodado depois?
- Tem-se "compute on-demand" que não persiste (Analytic) e "snapshot persisted" (Baseline)? Os dois calculam o mesmo número se o input é o mesmo? Há divergência detectável entre as duas paths?

### Q5 — Price lookup sem fallback (§2.1)

- `price_lookup_service.lookup(commodity, date)`: o que retorna se `(commodity, date)` não está na tabela? Raise estruturado (preferred) ou `None` (falsy = silent)? Cite linha.
- Caller-side: cada chamada a `lookup` é precedida por `try/except`? Se sim, qual o tratamento da exceção? `pass`/`return None`/`use_default()` é violação. `raise` ou propagate é OK.
- Há mais de uma fonte de preço no codebase (e.g., `westmetall_cash_settlement` + `cash_settlement_prices` + alguma terceira)? Se sim, o lookup é **canônico** (uma fonte autoritativa) ou faz "tente A, depois B" (= fallback regime)?
- Weekend / feriado handling: `as_of_date - 1 business_day` — quem define "business day"? Há calendário fixo / commodity-specific? Há risco de "Friday for Saturday/Sunday" silenciosamente vs hard-fail?

### Q6 — Scenario in-memory invariant (§2.2)

- `scenario_whatif_service`: grep `session\.\(add\|merge\|commit\|execute\(.*INSERT\|UPDATE\|DELETE\)` no arquivo. Deve retornar zero matches em paths que mutate. Cite qualquer match.
- O service **lê** do DB (input) — ok. Ele **persiste** algo? Cache? Resultado em tabela? Confirmar.
- Há `scenario_results` / `whatif_runs` table no schema? Se sim, qual service popula? É violação direta de "no persistence".
- Cache: existe `@lru_cache`, `functools.cache`, redis client, ou similar dentro do service? Reuso silencia mudança de input. Cite.
- Input format: scenario aceita "explicit deltas list" ou também aceita texto livre / LLM-generated description? Se LLM, é cross-A4 violation.

### Q7 — Premium pricing exclusion (§2.1)

- Grep `premium`, `discount`, `over_benchmark`, `+spread` em `mtm_*`, `pl_calculation`, `price_lookup` services. Há lógica que aplica premium/discount sobre valor canônico? Se sim, é violação — premium deve ser embutido no `fixed_price_value` do contrato, não recalculado em valuation time.

### Q8 — Aggregation determinism (§2.3)

- Aggregation cross-commodity (e.g., total MTM por tenant, total P&L por book): a iteração é determinística? `dict.items()` / `set()` / `sorted(...)` consistentes?
- Soma de `Decimal`s: há ponto onde a precisão é perdida por conversão `float`? Cite.
- Cross-tenant aggregation: existe boundary tenant-level? Há risco de data leakage cross-tenant em aggregation?

### Q9 — Cross-A1-A3 boundary

- A3 services consomem primitivas A1 (`exposure_service`, `linkage_service`, contract classification, decimal primitives). Há regressão a nível de boundary? E.g., A3 re-implementa exposure aggregation com semântica diferente da A1; A3 ignora classification e trata todos os contracts iguais.
- Audit trail emission: A3 mutations devem emitir audit events. Quais? Há gap conhecido?

### Q10 — Cross-A2-A3 boundary + cross-A4 risks

- A3 consume `HedgeContract` originados em A2 (post-`award`). Há campo do `HedgeContract` que A3 espera populado mas A2 não garante? Mismatch é bug latente.
- Cross-A4: `webhook_processor` ou `whatsapp_*` consume MTM/PnL/Cashflow output? Se sim, marque qualquer dependência como `cross-phase-A4-risk` (não audite a infra).
- Cross-A5: A3 emite audit events via `audit_trail_service`? Que rate-limiting governa endpoints A3? Marque qualquer assumption como `cross-phase-A5-risk`.

---

## 5. Formato do relatório de findings

Você produz **um único arquivo markdown** com a estrutura abaixo. Salve em `docs/audits/2026-05-09-phase-a3-findings-opus.md` (ou `findings-gemini.md` se você é o Auditor B — header swap em §0).

```
# Phase A3 — Stage 1 Findings — Auditor A (Opus 4.7)

## Posture (overall)
PASS / FAIL / FAIL-WITH-CRITICAL-CAVEATS

## Tier definitions
- T1 (CRITICAL): violation of a governance hard-fail clause; data loss, evidence loss, regulatory incident potential.
- T2 (HIGH): violation of an institutional invariant that does not yet trigger a hard-fail but creates audit-trail or reconstrutibilidade gap.
- T3 (MEDIUM): hygiene / refactor opportunity that strengthens the system without changing semantics.
- T4 (LOW): documentation / naming / style.

## Findings

### J-A3-NN — <short title>
- **Tier:** T1 / T2 / T3 / T4
- **Surface:** `path/to/file.py:line` (cite exact)
- **Constitutional clause violated:** governance.md:NNN-NNN (or "no clause; institutional invariant")
- **Evidence:** code citation + walkthrough
- **Reproduction:** how to trigger
- **Suggested remediation surface:** which file/function would change (NOT the patch — just the surface)

### J-A3-NN+1 — ...
```

For each Q1-Q10, include a **direct sim/não answer with evidence** at the top of the section before listing findings derived from that question.

---

## 6. Anti-finding rules

You MUST NOT include in your findings:
- Style / lint issues (T4 only if they encode a real institutional risk; otherwise skip).
- Tests bugs (you read tests as evidence, not as audit target — see §3.5).
- Phase A1 / A2 / A4 / A5 / A6 issues (cite as cross-phase risk; don't expand scope).
- Speculative findings ("could potentially in some scenario"). Only file findings you can REPRODUCE via cited code path.
- Restructuring proposals ("this should be split into N services") — out of scope for adversarial audit.

---

## 7. What NOT to do

- Do NOT modify code. This is read-only audit.
- Do NOT propose patches. The Jury + remediation waves handle that.
- Do NOT consult Auditor B's output if you happen to see it. Independence is institutional.
- Do NOT guess at line numbers — cite exact via Read or Serena `find_symbol`.
- Do NOT dismiss a constitutional hard-fail as "edge case unlikely". Hard-fails are categorical.

---

## 8. Final report shape

When complete:
1. Save findings to `docs/audits/2026-05-09-phase-a3-findings-opus.md` (Auditor A) or `findings-gemini.md` (Auditor B).
2. Final commit message: `docs(audits): Phase A3 Stage 1 findings — Auditor A (Opus)` (or `Auditor B (Gemini)`).
3. Stop. Do not push, do not open PR. Orchestrator + Jury take over from here.

Boa caça.
