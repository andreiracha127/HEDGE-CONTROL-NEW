# Gap Analysis: Legacy Backend vs New Backend

> **Gerado em:** Junho 2025 | **Revisado em:** Março 2026 | **Atualizado em:** Maio 2026 (pós-A1-A6 + Clusters 1-4)
> **Escopo:** Comparação exaustiva entre o backend legacy (`Hedge_Control_Alcast-Backend`) e o novo backend (`HEDGE-CONTROL-NEW`).
> **Método:** Inventário direto do código atual em `backend/app/` (services, routes, models), validação contra `backend/alembic/versions/` e `backend/tests/`, cruzamento com `docs/2026-05-tech-lead-executive-analysis.md` (pilot brief).
> **Baseline desta revisão:** main `d204081dd` (Maio 2026), alembic head `045_market_data_governance_columns`, 94 arquivos de teste backend, 10 páginas protegidas no frontend SvelteKit.

### Decisões de Escopo (revisão Março 2026, mantidas em Maio 2026)

1. **Westmetall é a única fonte canônica de preços para LME aluminium cash settlement** — LME Scraper (Playwright) descartado. Não-canônicos (e.g. histórico Yahoo Finance, ingest rindex US/EU) só entram como tier `audit_only` per `docs/governance.md` MARKET-DATA GOVERNANCE; nunca alimentam Deals/MTM/P&L/Scenarios.
2. **Sem gestão de estoques/locações** — `Warehouse Locations` e `Inventory Management` permanecem fora do escopo.
3. **Deal e Exposure são fundamentais** — base para P&L consolidado e decisões de hedge. **Status (Maio 2026): LANDED via Phase A1 + Cluster 1.**
4. **RFQ apresenta resultados do legacy, orquestrado por LLM** — pipeline `rfq_orchestrator.py` (2.041 linhas) + `llm_agent.py` (558 linhas) entregando os outputs do legacy. **Status (Maio 2026): LANDED via Phase A2 (21/21 jury findings) + Cluster 2 (auth derivation) + Cluster 4 (market-data governance).**

### O que mudou entre Março 2026 e Maio 2026

A revisão de Março 2026 antecedeu o ciclo de auditoria adversarial Phases A1-A6 + Clusters cross-phase 1-4. Durante 2026-05-06 a 2026-05-17, **6 fases mandatórias + 4 clusters cross-phase foram retirados** (~14 PRs nos 5 dias de 13-17 de Maio), fechando os P0 e a maioria dos P1 listados. Esta revisão substitui os status `❌ ausente` por `LANDED` quando suportado por evidência no repositório, mantém `ABSENT` quando o componente continua faltando, e introduz uma nova categoria `HB` para os quatro hard blockers do pilot brief.

---

## Resumo Executivo

| Métrica           | Legacy                        | Novo (Mar 2026 — stale)    | Novo (Mai 2026 — atual)         | Cobertura atual |
| ----------------- | ----------------------------- | -------------------------- | ------------------------------- | --------------- |
| Services          | 48 arquivos                   | 23 arquivos                | **32 arquivos**                 | ~67%            |
| Routes (arquivos) | 47 arquivos                   | 13 arquivos                | **20 arquivos**                 | ~43%            |
| Endpoints         | ~140+                         | 47                         | **86**                          | ~61%            |
| Models/Classes    | 50 classes / 42 tabelas       | 15 classes / 15 tabelas    | **29 classes**                  | ~58% (tabelas)  |
| Alembic head      | n/a                           | n/a                        | **`045_market_data_governance_columns`** | n/a             |
| Test files        | n/a                           | n/a                        | **94 arquivos**                 | n/a             |

O novo backend mantém a **arquitetura superior** (UUID PKs, Pydantic v2, HMAC audit trail, LLM agent, what-if engine), e agora cobre **~55-65% das funcionalidades de negócio** do legacy. **Os P0 críticos (Deal Engine, Exposure Engine, Hedge lifecycle, Finance Pipeline daily, Counterparty CRUD) estão LANDED.** Os gaps remanescentes concentram-se em P1 governance (KYC suite, Workflow Approvals, Timeline) — três dos quais são os hard blockers do pilot brief.

---

## Legenda de Prioridade

| Prioridade           | Significado                                                       |
| -------------------- | ----------------------------------------------------------------- |
| **HB — Pilot Hard Blocker** | Bloqueador explícito para go-decision do pilot Junho 2026 |
| **P0 — Crítico**     | Funcionalidade core de negócio, bloqueia operações diárias        |
| **P1 — Alto**        | Funcionalidade importante, impacta governança/compliance          |
| **P2 — Médio**       | Funcionalidade desejável, melhoria operacional                    |
| **P3 — Baixo**       | Nice-to-have, pode ser adiado                                     |
| **LANDED**           | Implementado no novo backend (com referência de arquivo)          |
| **PARCIAL**          | Parcialmente implementado, com gaps explícitos                    |
| **ABSENT**           | Não implementado; ainda no roadmap ou explicitamente fora de escopo |

---

## 1. STATUS DOS GAPS CRÍTICOS (P0) — Funcionalidades Core

### 1.1 Deal Engine — Gestão de Negócios — LANDED (Phase A1 + Cluster 1)

**Legacy:** `deal_engine.py` (190 linhas) + models `Deal`, `DealLink`, `DealPNLSnapshot` + route `deals.py`
**Novo:** `backend/app/services/deal_engine.py` (1.392 linhas), models `Deal`/`DealLink`/`DealPNLSnapshot` em `backend/app/models/deal.py`, rota `backend/app/api/routes/deals.py` (9 endpoints).

| Funcionalidade                       | Status no Novo                                                 |
| ------------------------------------ | -------------------------------------------------------------- |
| Criação de Deal a partir de SO       | LANDED — POST `/deals`                                          |
| Vinculação PO/Hedge via DealLink     | LANDED — POST `/deals/{id}/links` (links polimórficos via `linkages` table) |
| P&L consolidado por Deal             | LANDED — POST `/deals/{id}/links/{lid}/snapshot` + GET `/deals/{id}/pnl-history` |
| Deal lifecycle status                | PARCIAL — campos descontinuados via alembic `044_drop_deal_lifecycle_fields` (PR-CL1-4, Path A) |

**Mudança de escopo institucional (PR #78 / Cluster 1 PR-CL1-4):** o lifecycle status detalhado (`open → partially_hedged → fully_hedged → settled → closed`) foi removido como "código morto" — não havia escritores nem consumidores em produção. O Deal hoje deriva lifecycle implicitamente do estado dos `DealLink`s e dos `HedgeContract`s vinculados. Se o pilot precisar de lifecycle materializado, é trabalho novo (não restauração).

**Cobertura de testes:** `test_deal_engine.py`, `test_deal_engine_archived_link_traversal.py`.

---

### 1.2 Exposure Engine — Motor de Exposição — LANDED (Phase A1)

**Legacy:** `exposure_engine.py` (225) + `exposure_aggregation.py` (100) + `exposure_timeline.py` (115) + models `Exposure`/`ContractExposure`/`HedgeExposure`/`HedgeTask`
**Novo:** `backend/app/services/exposure_engine.py` (647 linhas) + `exposure_service.py` (384 linhas), models em `backend/app/models/exposure.py` (`Exposure`/`ContractExposure`/`HedgeExposure`/`HedgeTask`), rota `backend/app/api/routes/exposures.py` (8 endpoints).

| Funcionalidade                              | Status                                                    |
| ------------------------------------------- | --------------------------------------------------------- |
| Snapshot de exposição comercial/global      | LANDED — GET `/exposures/commercial`, GET `/exposures/global` |
| Reconciliação automática SO/PO → Exposure   | LANDED — POST `/exposures/reconcile`                      |
| Persistência de exposições no banco         | LANDED — tabela `exposures` + invariante de over-allocation (alembic `029`) |
| HedgeTask auto-creation/cancellation        | LANDED — GET `/exposures/tasks` + POST `/exposures/tasks/{id}/execute` |
| ContractExposure / HedgeExposure links      | LANDED — tabelas em `backend/app/models/exposure.py`       |
| Net exposure aggregation                    | LANDED — GET `/exposures/net`                             |
| CRUD de exposições                          | LANDED — GET `/exposures`, GET `/exposures/{id}`          |

**What-if parity:** `scenario_whatif_service.py` (498 linhas) consome o mesmo engine in-memory para garantir consistência analítica live↔scenario; `test_scenario_live_exposure_parity.py` guarda o invariante.

---

### 1.3 Hedge Lifecycle — Gestão de Hedges — LANDED (consolidado em `HedgeContract`)

**Legacy:** routes `hedges.py` + `hedge_manual.py` + `hedge_tasks.py` + model `Hedge` (15+ colunas)
**Novo:** decisão arquitetural — `HedgeContract` (`backend/app/models/contracts.py`) é o registro autoritativo de hedge desde alembic `015_unify_hedge_into_hedge_contract`. CRUD via `contract_service.py` (336 linhas) + rota `contracts.py` (8 endpoints incluindo PUT `/{id}/status`); tasks de execução em `/exposures/tasks` (ver §1.2).

| Funcionalidade            | Status                                                                  |
| ------------------------- | ----------------------------------------------------------------------- |
| CRUD de Hedges            | LANDED — via `/contracts` (GET/POST/PUT/DELETE + `/status` lifecycle)   |
| Hedge Manual              | PARCIAL — sem fluxo dedicado, covered pelo POST `/contracts` direto (workflow approval ainda pendente, ver §2.2) |
| Hedge Tasks               | LANDED — via `/exposures/tasks`                                         |
| Hedge status machine      | LANDED — `active → settled → cancelled` enforced pelo route guard       |
| Vínculo Hedge ↔ Exposure  | LANDED — via `HedgeExposure` table + `HedgeOrderLinkage`                |
| Settlement events         | LANDED — GET `/contracts/{id}/settlement-events`                        |

**KYC gate na criação manual:** ainda ABSENT — esse é exatamente o conteúdo do **HB-1** (ver §2.1 e §9.HB).

---

### 1.4 Sales Orders & Purchase Orders — LANDED (CRUD + reconciliação)

**Legacy:** `sales_orders.py`, `purchase_orders.py` com exposure reconciliation triggers
**Novo:** modelo unificado `Order` (`backend/app/models/orders.py`) com discriminador `type` (SO/PO), serviço `order_service.py` (280 linhas), rota `orders.py` (7 endpoints incluindo POST `/{id}/enrich`).

| Funcionalidade                        | Status                                                              |
| ------------------------------------- | ------------------------------------------------------------------- |
| Criar / listar / detalhar SO/PO       | LANDED                                                              |
| Soft-delete                           | LANDED                                                              |
| Trigger de reconciliação de exposição | LANDED — via `exposure_engine.reconcile()` chamado downstream       |
| SoPoLink (SO↔PO direto)               | LANDED — `backend/app/models/orders.py::SoPoLink`                    |
| Pricing types diferenciados           | LANDED — `Order.price_type` (fixed/variable) + alembic `028_price_type_field` |
| Multi-commodity                       | LANDED — coberto por `test_multi_commodity.py`                      |

---

### 1.5 Finance Pipeline Daily — Orquestrador Diário — LANDED (parcialmente operacional) — HB-3

**Legacy:** `finance_pipeline_daily.py` (698 linhas) + `finance_pipeline_run_service.py` (258 linhas)
**Novo:** `backend/app/services/finance_pipeline_service.py` (242 linhas) + models `FinancePipelineRun`/`FinancePipelineStep` (`backend/app/models/finance_pipeline.py`) + rota `finance_pipeline.py` (3 endpoints: POST `/run`, GET `/runs`, GET `/runs/{id}`).

**Pipeline de 6 etapas (confirmado em `finance_pipeline_service.py:138-143`):**

| Step  | Função                                               |
| ----- | ---------------------------------------------------- |
| 1     | `market_snapshot` — captura preços Westmetall       |
| 2     | `mtm_computation` — MTM de todos os contratos       |
| 3     | `pl_snapshot` — materializa P&L                     |
| 4     | `cashflow_baseline` — projeções de fluxo de caixa   |
| 5     | `risk_flags` — sinaliza problemas de data quality   |
| 6     | `summary` — agregação final                          |

**Cobertura:** `test_finance_pipeline.py`.

**Gap remanescente (= HB-3 do pilot brief, ver §9.HB):** o pipeline executa sob demanda via POST mas **não está agendado no Railway scheduler service** para execução diária idempotente. Hardening necessário antes do pilot: idempotência por `(run_date, step_name)`, runbook expansion em `docs/runbook-railway.md`, wiring no `app.scheduler_main`, validação end-to-end com dados de 2-3 counterparties.

---

### 1.6 Contracts — Enriquecimento de Dados — LANDED

**Legacy:** `contracts.py` com trade leg enrichment, settlement adjustment, exposure allocations + JSON `trade_snapshot`, `@validates`, status enum
**Novo:** `HedgeContract` em `backend/app/models/contracts.py` + `contract_service.py` (336 linhas) + rota `contracts.py` (8 endpoints).

| Funcionalidade                  | Status                                                          |
| ------------------------------- | --------------------------------------------------------------- |
| CRUD básico                     | LANDED                                                          |
| FK para RFQ/Counterparty/Order  | LANDED — via tabela `linkages`                                  |
| Soft delete                     | LANDED                                                          |
| Settlement date/value computation | LANDED — GET `/contracts/{id}/settlement-events`              |
| Settlement adjustment           | LANDED — via `mtm_contract_service.py`                          |
| Status transitions auditadas    | LANDED — PUT `/contracts/{id}/status` + audit event emission    |
| Invariant checks                | LANDED — `test_contract_hygiene.py`, `test_contract_status_settlement_guard.py` |

---

## 2. STATUS DOS GAPS ALTOS (P1) — Governança e Compliance

### 2.1 KYC & Compliance Suite — ABSENT — HB-1

**Legacy:** `kyc.py` (40) + `kyc_gate.py` (120) + `so_kyc_gate.py` (91) + models `KycDocument`, `CreditCheck`, `KycCheck`
**Novo:** ABSENT — busca por `kyc` em `backend/app/` retorna zero matches.

**Implicação institucional para o pilot:** este é o conteúdo exato de **HB-1** do pilot brief (`docs/2026-05-tech-lead-executive-analysis.md` §2 HB-1). Sem o gate, qualquer counterparty pode entrar em RFQ — risco de compliance event no Day 1 do pilot. Sequência prevista: governance amendment em `docs/governance.md` → implementation dispatch → executor session → PR.

**Cobertura mínima esperada para fechar HB-1:**
- Guard em `backend/app/services/rfq_service.py` na criação de `RFQInvitation` (e idealmente também no path de quote/award para defense-in-depth)
- Audit event `rfq_invitation_rejected_kyc_not_approved` com payload assinado HMAC
- Test file `backend/tests/test_rfq_kyc_gate.py` cobrindo positive + negative cases
- Schema validation no `RFQInvitation` impedindo persistência se `Counterparty.kyc_status != approved`

**Modelos necessários:** mínimo viável para o pilot é apenas o campo `kyc_status` na `Counterparty` (não exige `KycDocument`/`CreditCheck`/`KycCheck` completos). A suite completa é P1 pós-pilot.

---

### 2.2 Workflow Approvals — ABSENT — HB-2

**Legacy:** `workflow_approvals.py` (281) + models `WorkflowRequest`, `WorkflowDecision` + rota `workflows.py`
**Novo:** ABSENT — sem `workflow_approval` em services/routes/models.

**Implicação institucional para o pilot:** este é o conteúdo exato de **HB-2** do pilot brief (`docs/2026-05-tech-lead-executive-analysis.md` §2 HB-2). Hoje `risk_manager` pode criar/award/settle sem second-signatory. Threshold-based approval é institutional minimum para multi-counterparty.

**Cobertura mínima esperada para fechar HB-2:**
- Nova migração `046_workflow_approvals` introduzindo `WorkflowApprovalRequest` (status, requested_by, approved_by, threshold_at_request, audit_event_id linkage)
- Decorator de approval gate em rotas de mutação Deal/HedgeContract acima de threshold configurável
- Frontend approval-pending panel em `frontend-svelte/src/routes/(protected)/`
- Backend tests: threshold breach → approval required, single-role rejection, two-signatory acceptance, audit trail completeness
- E2E Playwright sobre Deal award

---

### 2.3 Treasury Decisions — ABSENT (deferred pós-pilot)

**Legacy:** `treasury_decisions_service.py` (210) + route `treasury_decisions.py` + models `TreasuryDecision`, `TreasuryKycOverride`
**Novo:** ABSENT.

**Implicação:** não está nos hard blockers do pilot — pode ser deferido para depois de HB-1/HB-2/HB-3/HB-4 estarem fechados. KYC override audit é parcialmente coberto pelo audit_trail_service genérico se necessário.

---

### 2.4 Document Numbering — PARCIAL

**Legacy:** `document_numbering.py` (85) + model `DocumentMonthlySequence` — formato `RFQ_001-03.25` (mensal, reseta por mês), `SELECT FOR UPDATE` (concurrency-safe)
**Novo:** `RFQSequence` (`backend/app/models/rfqs.py`) é autoincrement simples → formato `RFQ#<number>` global, sem reset mensal.

**Gap:** se o pilot exigir o formato legacy `RFQ_001-MM.YY`, é trabalho novo (~100 linhas). Caso contrário, é cosmético.

---

### 2.5 Timeline System — ABSENT (deferred pós-pilot)

**Legacy:** `timeline_emitters.py` (97) + `timeline_attachments_storage.py` (64) + model `TimelineEvent` + rota `timeline.py` (8 endpoints)
**Novo:** ABSENT (o `AuditEvent` em `backend/app/models/audit.py` é audit-trail, não timeline). Sem comments/attachments/@mentions/RBAC visibility filter.

**Implicação:** parte do "audit fatigue" risk no pilot brief §6 — pode ser deferido com compensating control (auditor consome `/audit/events` diretamente).

---

### 2.6 Finance Risk Flags — PARCIAL (step do pipeline existe; modelos materializados não)

**Legacy:** `finance_risk_flags_service.py` (185) + models `FinanceRiskFlagRun`, `FinanceRiskFlag`
**Novo:** o step `risk_flags` existe no `finance_pipeline_service.py` mas não materializa em tabela dedicada (vai para summary inline). Para o pilot, é suficiente; para produção full, falta a persistência por flag.

---

## 3. STATUS DOS GAPS MÉDIOS (P2) — Funcionalidades Operacionais

### 3.1 Counterparties — LANDED (Phase A1 + Cluster 3)

**Legacy:** routes `customers.py`, `suppliers.py`, `counterparties.py` + models `Customer`/`Supplier`/`Counterparty` (30+ colunas cada)
**Novo:** modelo unificado `Counterparty` (`backend/app/models/counterparty.py`) com discriminador `type` (trader/bank/producer/etc.), serviço `counterparty_service.py` (114 linhas), rota `counterparties.py` (5 endpoints).

**RBAC institucional (PR #79 / Cluster 3):** `trader` tem per-type access — vê apenas customer + supplier, broker/bank são invisíveis (GET retorna 404, nunca 403, para não vazar existência). Coberto por `test_rbac_matrix_enforcement.py`.

**Gap remanescente:** o legacy tinha 3 modelos com 30+ colunas cada (bank_info, payment_terms, credit_limit, KYC docs). O novo tem o subset operacional necessário. Campos adicionais (e.g. `kyc_status` para HB-1) podem ser adicionados via migration 046 ou no escopo do HB-1.

---

### 3.2 Dashboard — ABSENT (deferred pós-pilot)

**Legacy:** route `dashboard.py` — 6 widgets com TTL cache in-memory
**Novo:** ABSENT — análises individuais (`/analytics/mtm`, `/analytics/pnl`, `/analytics/what-if`) existem mas sem widget consolidado.

**Implicação:** "Nice-to-have / stretch" do pilot brief §1 — aceitável para pilot com compensating control (auditor consome as páginas analíticas individualmente).

---

### 3.3 Exports Suite — ABSENT (deferred pós-pilot)

**Legacy:** 9 services (~2.240 linhas total) + route `exports.py`
**Novo:** ABSENT — chain export, state-at-time, audit log export, manifest, PDF generation, async job queue: todos ausentes.

**Compensating controls para o pilot:** `/audit/events` cursor-paginated + GET `/cashflow/baseline-archive` + verify endpoint (`/audit/events/{id}/verify`) permitem auditoria manual mínima.

---

### 3.4 Reports — ABSENT (deferred pós-pilot)

**Legacy:** route `reports.py` — 5 endpoints (cashflow ledger JSON/CSV, RFQ por counterparty, RFQ attempts, unified export)
**Novo:** ABSENT.

**Audit Daily Report (=HB-4)** é parcialmente neste domínio mas tem identidade institucional própria — ver §9.HB.

---

### 3.5 Inbox / Workbench View — ABSENT (deferred pós-pilot)

**Legacy:** route `inbox.py` — workbench com counts, net exposure matrix, exposure decisions
**Novo:** ABSENT.

---

### 3.6 Scheduler — PARCIAL — bloqueia HB-3

**Legacy:** `scheduler.py` (185) — Background daemon com Westmetall scraper @ 09:00 UTC + Finance pipeline @ 10:00 UTC + advisory lock
**Novo:** scheduler service existe (Railway service separado, `python -m app.scheduler_main`), `SCHEDULER_DISABLED=true` em web workers. **Jobs concretos para Finance Pipeline daily ainda precisam ser wired** — esse é parte do HB-3.

**Coberto por:** `test_scheduler_main.py`.

---

### 3.7 Users & Auth CRUD — ABSENT por design / PARCIAL

**Legacy:** route `users.py` (CRUD + bootstrap) + `auth.py` (token login, /me, signup + Entra ID gate) + models `User`, `Role`
**Novo:** decisão arquitetural (Cluster 3) — **auth delegada ao Clerk SDK**, identidade vem do JWT (issuer = Clerk), sem User/Role no banco. Endpoints `/auth/login`, `/auth/refresh`, `/auth/me`, `/auth/logout` (4 endpoints em `backend/app/api/routes/auth.py`).

| Funcionalidade               | Status no Novo                            |
| ---------------------------- | ----------------------------------------- |
| `/me` endpoint               | LANDED — GET `/auth/me`                   |
| Token login                  | LANDED — via Clerk + httpOnly session cookie |
| Logout                       | LANDED — POST `/auth/logout`              |
| Role assignment              | LANDED — via JWT claims (trader/risk_manager/auditor) |
| User CRUD                    | ABSENT por design — owned pelo Clerk dashboard, fora do app |
| Signup                       | ABSENT por design — owned pelo Clerk dashboard |

**Tests:** `test_clerk_jwt_validation.py`, `test_auth_role_isolation.py`, `test_cookie_session.py`, `test_csrf_middleware.py`.

---

## 4. STATUS DOS GAPS BAIXOS (P3) — Nice-to-have

### ~~4.1 LME Public Scraper (Playwright)~~ — fora do escopo
### ~~4.2 Market Data Hub (multi-source)~~ — escopo reduzido
### ~~4.3 Warehouse Locations~~ — fora do escopo
### ~~4.4 Inventory Management~~ — fora do escopo

### 4.1 FX Policies — ABSENT

**Legacy:** route `fx_policies.py` + model `FxPolicyMap`
**Novo:** ABSENT. ~100 linhas se necessário pós-pilot.

### 4.2 Analytics — Entity Tree — ABSENT

**Legacy:** route `analytics.py` — Entity tree (Deals → SOs/POs/Contracts hierarchy)
**Novo:** páginas analíticas frontend existem (`/analytics/mtm`, `/analytics/pnl`, `/analytics/what-if`) mas sem entity tree.

### 4.3 MTM/P&L Enhancements — PARCIAL

**Legacy:** `mtm_service.py` com FX conversion + scenario adjustments; `mtm_snapshot_service.py` com snapshots multi-object; `pnl_engine.py` com trade spec parsing (avg/avginter/fix/c2r); models `MtmRecord`, `MtmContractSnapshot`, `PnlSnapshotRun`, `PnlContractSnapshot`, `PnlContractRealized`
**Novo:** MTM e P&L básicos (`mtm_snapshot_service.py` 194 linhas + `pl_snapshot_service.py` 142 linhas + `pl_calculation_service.py` 162 linhas):
- LANDED — snapshot pattern (MTMSnapshot)
- LANDED — provenance tracking (`test_pnl_provenance.py`, `test_pnl_price_evidence.py`)
- LANDED — realized P&L via POST `/pl/compute-realized` (`test_pl_snapshot_realized_from_ledger.py`)
- ABSENT — FX conversion
- ABSENT — scenario adjustments inline (separado em `scenario_whatif_service.py`)

---

## 5. FUNCIONALIDADES ONDE O NOVO SUPERA O LEGACY

| Funcionalidade                                                | Novo                                                                                | Legacy                              |
| ------------------------------------------------------------- | ----------------------------------------------------------------------------------- | ----------------------------------- |
| **LLM Agent** (`llm_agent.py`, 558 linhas)                    | OpenAI GPT-4o-mini para parsing de mensagens WhatsApp inbound + structured quotes | Inexistente                      |
| **RFQ Orchestrator** (`rfq_orchestrator.py`, 2.041 linhas)    | Pipeline LLM-powered com 16 endpoints de lifecycle / state-machine / award       | Inexistente                      |
| **Scenario What-If** (`scenario_whatif_service.py`, 498)      | Engine sandboxed com shifts de preço + parity test contra exposure_engine        | Inexistente                      |
| **HMAC Audit Trail** (`audit_trail_service.py`, 220 linhas)   | HMAC com `AUDIT_SIGNING_KEY` (validador fail-closed em prod/staging) + verify endpoint | Auditoria simples sem assinatura |
| **Market Data Governance** (`market_data_governance.py`, 403) | 3-tier provider trust (canonical/trusted/audit_only), replay-window invariants, drift detection, sequence tracker (alembic `045`) | Sem governance constitutional   |
| **Webhook Processor** (`webhook_processor.py`, 333 linhas)    | Queue estruturada + HMAC verification + idempotency em `InboundWebhookDelivery`  | Parsing direto na rota           |
| **WhatsApp Cloud API** (`whatsapp_service.py` + `whatsapp_providers.py`, 708 linhas total) | Provider abstraction (Meta + Twilio) com canonical `RFQ#<number>` no outbound | Stub/mock |
| **RFQ Engine** (`rfq_engine.py`, 720 linhas + `lme_calendar.py`, 169) | Holiday-aware text generation + 10 formatos + execution evidence (alembic `037`)  | Engine mais simples              |
| **Westmetall Scraper** (`westmetall_cash_settlement.py`, 226) | Circuit breaker + retry + governance hooks (Cluster 4 PR-CL4-1)                  | Scraper simples                  |
| **UUID Primary Keys**                                         | Todos os models                                                                  | Misto (Integer + UUID)           |
| **Pydantic v2 Schemas**                                       | Validação rigorosa em `backend/app/schemas/`                                     | Schemas mais simples             |
| **Healthcheck duplo**                                         | `/health` (liveness) + `/ready` (readiness com DB + JWKS)                        | Apenas `/health`                 |
| **RBAC Authorization Matrix** (constitutional, `docs/governance.md` linhas 189-340) | 3 human roles (trader/risk_manager/auditor) + 4 service identities; per-type Counterparty access; auditor exclusivity enforced at JWT validator | Sem matriz constitucional |
| **Pre-push hook v2** (Sonnet 4.6 multi-turn tool-use)         | `.githooks/pre-push` + `scripts/pre_push_review.py` (PR #45 — 2026-05-10)         |                                  |
| **Audit cycle protocol** (institucional)                      | 6 phases A1-A6 + 4 clusters cross-phase fechados (~14 PRs em 5 dias 13-17 Mai)   |                                  |

---

## 6. MODELOS — Comparação Detalhada (atualizada Maio 2026)

### Tabelas legacy que **AGORA EXISTEM** no novo backend (progresso Mar→Mai 2026)

| Tabela                  | Domínio       | Antes (Mar) | Agora (Mai) | Arquivo                                          |
| ----------------------- | ------------- | ----------- | ----------- | ------------------------------------------------ |
| `deals`                 | Deal Engine   | ABSENT      | LANDED      | `backend/app/models/deal.py`                     |
| `deal_links`            | Deal Engine   | ABSENT      | LANDED      | `backend/app/models/deal.py` (+ `linkages.py`)    |
| `deal_pnl_snapshots`    | Deal Engine   | ABSENT      | LANDED      | `backend/app/models/deal.py`                     |
| `exposures`             | Exposure      | ABSENT      | LANDED      | `backend/app/models/exposure.py`                 |
| `contract_exposures`    | Exposure      | ABSENT      | LANDED      | `backend/app/models/exposure.py`                 |
| `hedge_exposures`       | Exposure      | ABSENT      | LANDED      | `backend/app/models/exposure.py`                 |
| `hedge_tasks`           | Exposure      | ABSENT      | LANDED      | `backend/app/models/exposure.py`                 |
| `counterparties`        | Entity        | ABSENT      | LANDED      | `backend/app/models/counterparty.py`             |
| `finance_pipeline_runs` | Pipeline      | ABSENT      | LANDED      | `backend/app/models/finance_pipeline.py`         |
| `finance_pipeline_steps`| Pipeline      | ABSENT      | LANDED      | `backend/app/models/finance_pipeline.py`         |
| `so_po_links`           | Orders        | ABSENT      | LANDED      | `backend/app/models/orders.py`                   |

### Tabelas legacy **AINDA AUSENTES** no novo backend

| Tabela                       | Domínio       | Prioridade                                       |
| ---------------------------- | ------------- | ------------------------------------------------ |
| `users` / `roles`            | Auth          | Out of scope (Clerk-owned)                       |
| `hedges`                     | Hedge         | Consolidado em `hedge_contracts` (decisão A1)    |
| `customers` / `suppliers`    | Entity        | Consolidado em `counterparties` (decisão arq)    |
| `kyc_documents`              | Compliance    | HB-1 (mínimo viável = campo `kyc_status` em Counterparty) |
| `credit_checks`              | Compliance    | P1 pós-pilot                                     |
| `kyc_checks`                 | Compliance    | P1 pós-pilot                                     |
| `workflow_requests`          | Governance    | HB-2                                             |
| `workflow_decisions`         | Governance    | HB-2                                             |
| `treasury_decisions`         | Treasury      | P1 pós-pilot                                     |
| `treasury_kyc_overrides`     | Treasury      | P1 pós-pilot                                     |
| `timeline_events`            | Timeline      | P1 pós-pilot (compensating: `/audit/events`)     |
| `document_monthly_sequences` | Doc Numbering | P1 (cosmético se pilot aceita formato atual)     |
| `finance_risk_flag_runs`     | Risk          | P1 (step inline existe, materialização pós-pilot) |
| `finance_risk_flags`         | Risk          | P1                                               |
| `export_jobs`                | Exports       | P2 pós-pilot                                     |
| `fx_policy_map`              | FX            | P3 pós-pilot                                     |
| `mtm_records`                | MTM           | P3 (atual MTMSnapshot é suficiente)              |
| `pnl_snapshot_runs`          | P&L           | Coberto via `PLSnapshot` (run-pattern simplificado) |
| `pnl_contract_snapshots`     | P&L           | Coberto via `PLSnapshot.entries`                 |
| `pnl_contract_realized`      | P&L           | Coberto via POST `/pl/compute-realized`          |
| `mtm_contract_snapshot_runs` | MTM           | P3                                               |
| `cashflow_baseline_runs`     | Cashflow      | Coberto via `CashFlowBaselineSnapshot`           |
| `whatsapp_messages`          | Messaging     | Coberto via `InboundWebhookMessage` + `InboundWebhookDelivery` |

### Tabelas no Novo **sem equivalente no Legacy** (deltas arquiteturais)

| Tabela                            | Domínio       | Origem                              |
| --------------------------------- | ------------- | ----------------------------------- |
| `rfq_state_events`                | RFQ           | Event-sourcing de estados (Phase A2) |
| `cash_settlement_prices`          | Market Data   | Westmetall persistido (Phase A1)    |
| `market_data_sequence_tracker`    | Market Data   | Replay-window invariant (alembic `045`, Cluster 4) |
| `inbound_webhook_deliveries`      | Webhook       | Idempotency (Phase A2/A4)           |
| `inbound_webhook_messages`        | Webhook       | Inbound queue                       |
| `llm_decision_artifacts`          | LLM           | Audit trail de decisões LLM (Phase A4) |
| `reconciliation_runs`             | Reconciliação | Run pattern para exposures          |
| `linkages` (HedgeOrderLinkage)    | Linkage       | Invariante over-allocation (alembic `029`) |
| `quotes` (RFQQuote)               | RFQ           | Quote tracking estruturado          |

---

## 7. ROUTES — Comparação por Domínio (Maio 2026)

| Domínio                   | Endpoints Legacy                 | Endpoints Novo (Mai 2026)         | Gap                  |
| ------------------------- | -------------------------------- | --------------------------------- | -------------------- |
| Counterparties            | ~4 (CRUD + KYC docs)             | 5 (CRUD completo)                 | Coberto              |
| Orders                    | ~6 (SO + PO + reconciliação)     | 7 (CRUD + enrich)                 | Coberto              |
| Exposures                 | ~8 (CRUD + links + net)          | 8 (CRUD + reconcile + tasks + net) | Coberto             |
| Deals                     | ~5 (CRUD + links)                | 9 (CRUD + links + snapshots + pnl-history) | Coberto      |
| Hedges (=Contracts)       | ~8 (CRUD + manual + tasks)       | 8 (CRUD + status + MTM + settlement) + tasks em `/exposures/tasks` | Coberto |
| Linkages                  | (não tinha)                      | 3 (CRUD)                          | Novo                 |
| RFQs                      | ~10 (CRUD + lifecycle)           | 16 (CRUD + lifecycle + quotes + invitations + evidence + counterparty refresh) | Supera |
| Cashflow                  | ~6 (baseline + projeção)         | 4 + 3 ledger (`/cashflow` + `/cashflow/ledger`) | Coberto       |
| P&L                       | ~3 (snapshot + realized)         | 3 (list + detail + compute-realized) | Coberto           |
| Scenario                  | (não tinha)                      | 1 (POST /whatif)                  | Novo                 |
| Audit                     | (não tinha consolidado)          | 2 (GET /events + verify)          | Novo (HMAC)          |
| Market Data Westmetall    | ~6 (LME + Yahoo)                 | 3 (upload + price-sequence + staleness-check) | Foco canônico |
| MTM                       | ~4 (snapshot + records)          | 4 (contracts + orders + snapshot CRUD) | Coberto          |
| Webhooks                  | ~2 (inbound + status)            | 2 (`/whatsapp/inbound` + `/whatsapp/status`) | Coberto       |
| Auth                      | 3 (login + me + signup)          | 4 (login + refresh + me + logout) | Coberto (Clerk-backed) |
| Finance Pipeline          | 2 (run + status)                 | 3 (run + runs + runs/{id})        | Coberto (HB-3 = wiring) |
| CSP Reporter              | (não tinha)                      | 1 (POST `/csp/`)                  | Novo                 |
| WebSocket                 | (não tinha)                      | 1 (`/ws`)                         | Novo                 |
| **Domínios ABSENT**       | dashboards, exports, reports, inbox, FX policies, analytics entity tree, KYC dedicado, workflow approvals, timeline, treasury, users CRUD | — | Pós-pilot (e HB-1/HB-2/HB-4) |

**Total endpoints novos:** 86 (vs ~140+ legacy = ~61% cobertura; +83% vs Mar 2026).

---

## 8. SERVIÇOS — Comparação por Função (Maio 2026)

### Services legacy que **agora têm equivalente** no novo (progresso Mar→Mai 2026)

| Service Legacy                    | Linhas | Service Novo                              | Linhas |
| --------------------------------- | ------ | ----------------------------------------- | ------ |
| `deal_engine.py`                  | 190    | `deal_engine.py`                          | 1.392  |
| `exposure_engine.py`              | 225    | `exposure_engine.py`                      | 647    |
| `exposure_aggregation.py`         | 100    | (consolidado em `exposure_service.py`)    | 384    |
| `exposure_timeline.py`            | 115    | (parcial via `audit_trail_service.py`)    | 220    |
| `finance_pipeline_daily.py`       | 698    | `finance_pipeline_service.py`             | 242    |
| `finance_pipeline_run_service.py` | 258    | (consolidado no service acima)            | —      |
| `counterparty` CRUD               | —      | `counterparty_service.py`                 | 114    |
| `order` CRUD                      | —      | `order_service.py`                        | 280    |
| `contract` CRUD                   | —      | `contract_service.py`                     | 336    |
| `linkage` CRUD                    | —      | `linkage_service.py`                      | 258    |

### Services legacy **ainda ausentes**

| Service Legacy                    | Linhas    | Prioridade                                       |
| --------------------------------- | --------- | ------------------------------------------------ |
| `kyc.py`                          | 40        | HB-1 (mínimo viável)                             |
| `kyc_gate.py`                     | 120       | HB-1 (mínimo viável)                             |
| `so_kyc_gate.py`                  | 91        | HB-1 (mínimo viável)                             |
| `workflow_approvals.py`           | 281       | HB-2                                             |
| `treasury_decisions_service.py`   | 210       | P1 pós-pilot                                     |
| `document_numbering.py`           | 85        | P1 (cosmético)                                   |
| `timeline_emitters.py`            | 97        | P1 pós-pilot                                     |
| `timeline_attachments_storage.py` | 64        | P1 pós-pilot                                     |
| `finance_risk_flags_service.py`   | 185       | P1 pós-pilot (step inline existe)                |
| `scheduler.py`                    | 185       | Scheduler service existe; jobs específicos em HB-3 |
| `pnl_engine.py`                   | 235       | Coberto via `pl_calculation_service.py` (162)    |
| `pnl_snapshot_service.py`         | 263       | Coberto via `pl_snapshot_service.py` (142)       |
| `pnl_timeline.py`                 | 40        | P2 pós-pilot                                     |
| `exports_chain_export.py`         | 1.058     | P2 pós-pilot                                     |
| `exports_state_at_time.py`        | 483       | P2 pós-pilot                                     |
| 7× exports auxiliares             | ~600      | P2 pós-pilot                                     |
| ~~`lme_public.py`~~               | ~~248~~   | Out of scope (Westmetall = canonical)            |
| ~~`lme_price_service.py`~~        | ~~111~~   | Funcionalidade absorvida por `price_lookup_service.py` (157) |

### Services novos sem equivalente no legacy

| Service Novo                       | Linhas | Domínio                                          |
| ---------------------------------- | ------ | ------------------------------------------------ |
| `rfq_orchestrator.py`              | 2.041  | RFQ lifecycle LLM-powered                        |
| `rfq_service.py`                   | 1.620  | RFQ business logic                               |
| `rfq_engine.py`                    | 720    | RFQ state machine                                |
| `rfq_message_builder.py`           | 199    | WhatsApp message composition                     |
| `llm_agent.py`                     | 558    | OpenAI parsing                                   |
| `scenario_whatif_service.py`       | 498    | What-if engine                                   |
| `market_data_governance.py`        | 403    | 3-tier provider trust + replay invariants        |
| `cashflow_projection_service.py`   | 237    | Forward-looking settlement timeline              |
| `cashflow_baseline_service.py`     | 294    | Baseline snapshots                               |
| `cashflow_ledger_service.py`       | 336    | Cashflow ledger reconciliation                   |
| `audit_trail_service.py`           | 220    | HMAC audit                                       |
| `whatsapp_providers.py`            | 575    | Provider abstraction (Meta + Twilio)             |
| `webhook_processor.py`             | 333    | Inbound queue + idempotency                      |
| `westmetall_cash_settlement.py`    | 226    | Westmetall scraper + circuit breaker             |
| `lme_calendar.py`                  | 169    | LME business-day calendar                        |
| `mtm_snapshot_service.py`          | 194    | MTM snapshots                                    |

---

## 9. ROADMAP DE IMPLEMENTAÇÃO ATUALIZADO

### 9.HB — Pilot Hard Blockers (Junho 2026)

Substituem a Fase 1 do roadmap anterior (que está fechada). Sequência prescrita pelo handoff `.handoffs/orchestrator-handoff-2026-05-17.md` + pilot brief.

| Ordem | Hard Blocker                                          | Deps               | Estimativa     | Status         |
| ----- | ----------------------------------------------------- | ------------------ | -------------- | -------------- |
| HB-0  | GAP_ANALYSIS refresh (este documento)                 | —                  | 1 dia          | Em curso       |
| HB-1  | KYC gate at RFQ + governance amendment                | HB-0               | Semana 1-2     | Próximo        |
| HB-2  | Workflow Approvals (state machine + alembic 046 + frontend) | HB-1         | Semana 1-3     | Pendente       |
| HB-3  | Finance Pipeline daily hardening + Railway wiring     | (HB-1 não bloqueia) | Semana 2-4     | Pendente      |
| HB-4  | Audit Daily Report (`/audit/reports/daily/{date}` + Svelte page + auditor sign-off) | HB-1, HB-2, HB-3 | Semana 3-4 | Pendente |

### Fase 1 — Core Domain (P0) — **CLOSED**

Originalmente estimada em ~2.500 linhas; entregue como parte de Phases A1-A6 + Clusters 1-4. **Estado:** retirado do roadmap pós-pilot — material no Resumo Executivo e §1.

### Fase 2 — Governance (P1) — parcialmente em HB-1/HB-2/HB-4, restante deferred pós-pilot

| Componente                   | Status no roadmap atual                           |
| ---------------------------- | ------------------------------------------------- |
| KYC suite                    | HB-1 (mínimo viável) + P1 pós-pilot (suite completa) |
| Workflow approvals           | HB-2                                              |
| Treasury decisions           | P1 pós-pilot                                      |
| Timeline system              | P1 pós-pilot                                      |
| Document numbering (monthly) | P1 (cosmético, decisão go/no-go = formato atual aceito?) |
| Finance risk flags (materialização) | P1 pós-pilot                               |

### Fase 3 — Operations (P2) — deferred pós-pilot

| Componente                | Compensating control no pilot                          |
| ------------------------- | ------------------------------------------------------ |
| Dashboard (6 widgets)     | Auditor consome páginas individuais `/analytics/*`     |
| Reports (5 endpoints)     | Auditor consome `/cashflow/ledger` + `/audit/events`   |
| Exports suite             | `/audit/events` + verify endpoint para reconstrução    |
| Scheduler jobs específicos | Coberto por HB-3                                       |
| Users + Auth CRUD         | Owned pelo Clerk dashboard                             |
| Inbox / Workbench         | Páginas individuais existem (`/exposures`, `/contracts`, `/cashflow`) |

### Fase 4 — Enhancements (P3) — deferred pós-pilot

| Componente                                   | Estimativa pós-pilot |
| -------------------------------------------- | -------------------- |
| FX policies                                  | ~100 linhas          |
| Analytics entity tree                        | ~150 linhas          |
| MTM/P&L enhancements (FX, scenario inline)   | ~100 linhas          |

---

## 10. ESTIMATIVA ATUALIZADA

| Fase            | Prioridade | Linhas Estimadas | Tabelas Novas | Status               |
| --------------- | ---------- | ---------------- | ------------- | -------------------- |
| HB-0 → HB-4     | Pilot      | ~2.500           | ~2 (workflow + opcional KYC mínima) | Em curso |
| ~~Fase 1 (P0)~~ | (concluída) | entregue         | entregue      | **CLOSED**           |
| Fase 2 restante | P1         | ~1.300           | ~7 (KYC suite + Treasury + Timeline + DocNum + RiskFlags materialização) | Pós-pilot |
| Fase 3          | P2         | ~1.600           | ~1 (ExportJobs) | Pós-pilot           |
| Fase 4          | P3         | ~350             | ~1 (FxPolicy) | Pós-pilot             |
| **TOTAL restante para paridade com legacy** | | **~5.750** | **~11** | |

> **Itens removidos do escopo (decisões Mar 2026, mantidas Mai 2026):** LME Scraper, Inventory Management, Warehouse Locations, Market Data Hub multi-source.

> **Itens consolidados arquiteturalmente (sem perda de funcionalidade):** Customer + Supplier + Counterparty → tabela unificada `counterparties`; Hedge + HedgeContract → `hedge_contracts`; User + Role → Clerk-owned; SO + PO → `Order.type`.

---

## 11. RECOMENDAÇÕES ARQUITETURAIS (revisadas Maio 2026)

1. **Manter o padrão UUID PK** — confirmado em todos os models novos.
2. **Manter consolidação Counterparty unificada** (vs 3 modelos legacy) — decisão arquitetural validada por Cluster 3 RBAC matrix (per-type access via `type` discriminator).
3. **AuditEvent NÃO é Timeline** — não estender `AuditEvent` com campos de timeline (comments, attachments, @mentions). Se Timeline entrar no roadmap pós-pilot, criar tabela `timeline_events` dedicada.
4. **Finance Pipeline = Railway scheduler service**, não daemon in-process — `SCHEDULER_DISABLED=true` em web workers; única instância autoritativa em `python -m app.scheduler_main` no service `scheduler` do Railway. HB-3 fecha o wiring para Finance Pipeline daily.
5. **LLM Agent como parser canônico de WhatsApp inbound** — `webhook_processor.py` já delega para `llm_agent.py`; não restaurar regex parsing legacy.
6. **Pydantic v2 + openapi-fetch + schema regeneration** — pipeline `npm run api:types` mantém `frontend-svelte/src/lib/api/schema.d.ts` em sincronia com backend; CI guard `npm run api:types:check` detecta drift.
7. **Run → Items pattern para snapshots** — confirmado em FinancePipelineRun/Step, MTMSnapshot, PLSnapshot, CashFlowBaselineSnapshot.
8. **Westmetall como única fonte canônica** — `docs/governance.md` MARKET-DATA GOVERNANCE (linhas 442-748) institucionaliza 3-tier provider trust; não introduzir segundo provider canônico sem governance amendment.
9. **RFQ outputs do legacy via LLM orchestration** — `rfq_orchestrator.py` (2.041 linhas) entrega outputs do legacy com parsing LLM; mantém 16 endpoints (parity + supera).
10. **Deal + Exposure são pilares LANDED** — toda decisão de hedge flui pela cadeia Deal → Exposure → Hedge → Contract. Implementado, persistido, e governado.
11. **RBAC matrix é constitucional** — `docs/governance.md` AUTHORIZATION MATRIX (linhas 189-340) é fonte da verdade; rotas usam `@require_role`/`@require_any_role` (`backend/app/core/auth.py`); teste `test_rbac_matrix_enforcement.py` é guard.
12. **Audit trail HMAC fail-closed** — `AUDIT_SIGNING_KEY` validator gateado por `APP_ENV` em prod/staging (`test_audit_signing_key_required.py`); verify endpoint público para auditor.
13. **Cluster 4 market-data governance é load-bearing** — `market_data_governance.py` + `market_data_sequence_tracker` + alembic `045` são pré-requisito para HB-3 (Finance Pipeline daily depende de market_snapshot estável).
14. **Pre-push hook v2 é review gate ativo** — `.githooks/pre-push` + `scripts/pre_push_review.py`; trata achados como sieve, valida P1 contra diff antes de absorver (false-positives empíricos documentados em `.handoffs/orchestrator-handoff-2026-05-17.md` §3).

---

## 12. APÊNDICE — Histórico de Revisões

| Data         | Revisão                                                                                | PRs / Commits                                                 |
| ------------ | -------------------------------------------------------------------------------------- | ------------------------------------------------------------- |
| Junho 2025   | Versão inicial                                                                         | —                                                             |
| Março 2026   | Revisão de escopo: Westmetall canonical, sem inventory/warehouse, Deal+Exposure priori | —                                                             |
| Maio 2026    | **Esta revisão** — pós-A1-A6 + Clusters 1-4, baseline para pilot brief HB-0…HB-4       | Phases A1-A6 + Clusters 1-4 (~14 PRs em 5 dias 13-17 Mai 2026); pilot brief PR #89; Claude Code automation PR #90; alembic head `045` |

**Próxima revisão prevista:** pós-pilot (após go-decision Junho 2026 + 30 dias de operação), incorporando aprendizados operacionais e ajustando estimativas pós-pilot.
