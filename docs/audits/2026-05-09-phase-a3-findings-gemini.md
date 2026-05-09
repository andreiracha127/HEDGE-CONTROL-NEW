# Phase A3 — Stage 1 Findings — Auditor B (Gemini 3.1 Pro)

## Posture (overall)
FAIL-WITH-CRITICAL-CAVEATS

## Tier definitions
- T1 (CRITICAL): violation of a governance hard-fail clause; data loss, evidence loss, regulatory incident potential.
- T2 (HIGH): violation of an institutional invariant that does not yet trigger a hard-fail but creates audit-trail or reconstrutibilidade gap.
- T3 (MEDIUM): hygiene / refactor opportunity that strengthens the system without changing semantics.
- T4 (LOW): documentation / naming / style.

## Structured Answers

### Q1 — Determinismo numérico do MTM (§2.1, §2.3)
- `mtm_value` computado como Decimal pura? **Sim**. (Evidência: `mtm_contract_service.py:44`, `Decimal(str(contract.fixed_price_value))` garante ausência de `float`).
- Aggregation determinística? **Sim**. (Evidência: `cashflow_analytic_service.py` usa `.order_by(HedgeContract.created_at.asc())` e list appends).
- `mtm_snapshot_service` persiste `inputs_hash`? **Não**. (Evidência: `mtm_snapshot_service.py:46-54`, falta campo hash na instanciação).
- D-1 enforcement com fallback? **Sim (com falha de design/fallback em deal_engine)**. `price_lookup_service.py` recua no tempo e lança `PriceReferenceUnprovable`, mas callers interceptam de modo errôneo.

### Q2 — Cashflow always-derived (§2.1)
- Há endpoint que aceita cashflow como input? **Sim**. (Evidência: `backend/app/api/routes/cashflow_ledger.py:27` com payload manual).
- `cashflow_baseline_service` é derivado deterministicamente? **Não de forma isolada**. Lê a partir da view Analytic, configurando violação de boundary.
- `cashflow_ledger_service` emite sem evento contábil? **Não conclusivo/Ok**. Ele recebe um `HedgeContractSettlementEvent`, porém aceita o valor numerico manual no payload.

### Q3 — Boundary entre as quatro views (§2.1)
- `cashflow_analytic_service` faz persistência? **Não**. (Evidência: zero matches para `session.add/commit/execute`).
- `cashflow_baseline_service` lê do analytic? **Sim**. (Evidência: `cashflow_baseline_service.py:30` importa e executa `compute_cashflow_analytic`).
- `cashflow_ledger_service` compete com baseline? As views se mantêm separadas por schemas e tabelas próprias.

### Q4 — P&L provenance (§2.1, §2.3)
- `pl_calculation_service` produz triplet `(value, source, date)`? **Não**. (Evidência: `pl_calculation_service.py:79-84` só retorna `realized_pl` e `unrealized_mtm`).
- Múltiplos lookups serializados? Em `deal_engine` os lookups são persistidos, mas em `pl_calculation_service` (ordens/contratos avulsos) não há rastro.

### Q5 — Price lookup sem fallback (§2.1)
- Lookup levanta raise sem silent `None`? **Sim**. (Evidência: `price_lookup_service.py:182`, lança `PriceReferenceUnprovable`).
- Caller-side usa fallback ou suppress? **Sim**. (Evidência: `deal_engine.py:656-695` tem "repair scenario" que usa snapshots antigos).

### Q6 — Scenario in-memory invariant (§2.2)
- DB mutations (persiste/cache)? **Não**. (Evidência: não há `session.commit` ou decorators de cache em `scenario_whatif_service.py`).
- Input livre / LLM? **Não**. (Evidência: schema em `scenario.py` exige `delta_type` e deltas numéricos explícitos).

### Q7 — Premium pricing exclusion (§2.1)
- Há lógica que aplica premium sobre benchmark em A3? **Não**. (Evidência: P&L e MTM consumem apenas o `fixed_price_value` ou `avg_entry_price` sem calcular spread).

### Q8 — Aggregation determinism (§2.3)
- Aggregations iteram dicionários de forma variável? **Não**. `cashflow_analytic_service` itera listas (retornadas do DB) e soma com Decimals.

### Q9 — Cross-A1-A3 boundary
- A3 ignora classificação A1? **Sim**. Ordens têm a commodity trocada por um fallback padrão, invalidando a taxonomia.

### Q10 — Cross-A2-A3 boundary + cross-A4 risks
- Dependência incorreta com A2? Contratos originados com preço ausente ou preenchido erradamente afetam MTM de ordem.

## Findings

### J-A3-01 — MTM Snapshot lacks inputs_hash entirely (Reconstructibility gap)
- **Tier:** T1
- **Surface:** `backend/app/services/mtm_snapshot_service.py:46-54`
- **Constitutional clause violated:** governance.md:159-174 (Evidence missing / Reconstrutibilidade quebrada)
- **Evidence:** `create_mtm_snapshot_for_contract` and `create_mtm_snapshot_for_order` construct and persist an `MTMSnapshot` without computing or saving an `inputs_hash`. This makes it impossible to cryptographically verify or reconstruct the snapshot later.
- **Reproduction:** Call `create_mtm_snapshot_for_contract()`, check the returned object/DB; no hash is present or generated.
- **Suggested remediation surface:** `backend/app/services/mtm_snapshot_service.py` must compute a SHA256 hash of the inputs (`contract_id`, `as_of_date`, `price_d1`, `quantity_mt`) and the model must persist it.

### J-A3-02 — Manual Cashflow Input via Settle Endpoint
- **Tier:** T1
- **Surface:** `backend/app/api/routes/cashflow_ledger.py:27` and `backend/app/services/cashflow_ledger_service.py:108`
- **Constitutional clause violated:** governance.md:131-146 ("Cashflow is always derived, never manually input")
- **Evidence:** The route `POST /contracts/{contract_id}/settle` accepts a `HedgeContractSettlementCreate` payload containing `legs` with manually provided `amount` and `direction`. The service blindly iterates and inserts `CashFlowLedgerEntry(amount=expected["amount"])`. Arbitrary numbers can enter the ledger instead of deriving from contract facts.
- **Reproduction:** Send POST to `/contracts/<id>/settle` with an arbitrary leg amount. It persists directly to the ledger.
- **Suggested remediation surface:** `backend/app/services/cashflow_ledger_service.py:ingest_hedge_contract_settlement` must derive settlement amounts directly from contract and settlement price, ignoring payload amounts.

### J-A3-03 — Cross-view contamination: Baseline directly reads from Analytic
- **Tier:** T1
- **Surface:** `backend/app/services/cashflow_baseline_service.py:30`
- **Constitutional clause violated:** governance.md:131-146 ("Cross-contamination (e.g., Baseline lendo de cache What-if; Ledger emitindo a partir de Analytic) é violação")
- **Evidence:** `create_cashflow_baseline_snapshot` calls `compute_cashflow_analytic(db, as_of_date=as_of_date)` and uses `analytic.model_dump()` to build its `payload`. This couples the Baseline view tightly to the Analytic logic, collapsing the boundary.
- **Reproduction:** Read `cashflow_baseline_service.py` implementation.
- **Suggested remediation surface:** `backend/app/services/cashflow_baseline_service.py` must decouple and read directly from persistence instead of proxying through the analytic service.

### J-A3-04 — Deal Engine implements silent fallback pricing via snapshot cache
- **Tier:** T1
- **Surface:** `backend/app/services/deal_engine.py:656-695`
- **Constitutional clause violated:** governance.md:159-174 ("Fallback regime silencioso", "No fallback pricing regimes")
- **Evidence:** When all `_get_market_quote` lookups raise `PriceReferenceUnprovable` (total unavailability), the `deal_engine` enters a "repair scenario" block (`if unprovable_errors:` with no quotes). It queries the latest `DealPNLSnapshot` from the database and implicitly reuses its cached `price_references`.
- **Reproduction:** Trigger a deal P&L calculation on a weekend/holiday where 5-day lookback fails. Instead of propagating the hard-fail, it recycles the last snapshot's price.
- **Suggested remediation surface:** `backend/app/services/deal_engine.py:637-700` must drop the repair block and let `PriceReferenceUnprovable` propagate.

### J-A3-05 — P&L calculation service drops provenance triplet (Evidence missing)
- **Tier:** T1
- **Surface:** `backend/app/services/pl_calculation_service.py:79-84`
- **Constitutional clause violated:** governance.md:159-174 ("P&L sem provenance triplet")
- **Evidence:** `compute_pl` calculates P&L per-contract/order, utilizing `compute_mtm_for_contract` to fetch the MTM value. It returns a `PLResultResponse` that only contains `realized_pl` and `unrealized_mtm`. The underlying price value, source string, and settlement date are lost and never emitted.
- **Reproduction:** Call `compute_pl()`. Observe that no provenance data is returned, meaning downstream users of this generic P&L calculation cannot trace the number.
- **Suggested remediation surface:** `backend/app/services/pl_calculation_service.py` and `app/schemas/pl.py` must include the provenance triplet.

### J-A3-06 — MTM Order Service silently overrides order commodity
- **Tier:** T1
- **Surface:** `backend/app/services/mtm_order_service.py:24` and `:55`
- **Constitutional clause violated:** governance.md:159-174 ("Fallback regime silencioso")
- **Evidence:** `compute_mtm_for_order` declares `commodity: str = DEFAULT_COMMODITY`. Inside, it runs `resolve_symbol(commodity)` instead of reading `order.commodity`. Consequently, if a caller omits the `commodity` kwarg, it incorrectly prices a Zinc or Copper order against Aluminum.
- **Reproduction:** Call `compute_mtm_for_order(db, order_id=cu_order.id, as_of_date)`. It retrieves LME_AL settlement price instead of CU.
- **Suggested remediation surface:** `backend/app/services/mtm_order_service.py` must drop the `commodity` kwarg and use `order.commodity` internally.