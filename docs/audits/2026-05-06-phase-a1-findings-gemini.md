# Phase A1 — Stage 2 Findings — Auditor B (Gemini)

**Date:** 2026-05-06
**Scope commit:** f1420524b3436145e5afd47f42589bbc1e43b0f4
**Files audited:** 
- `backend/app/services/exposure_engine.py`
- `backend/app/services/exposure_service.py`
- `backend/app/services/deal_engine.py`
- `backend/app/services/linkage_service.py`
- `backend/app/models/exposure.py`
- `backend/app/models/deal.py`
- `backend/app/models/linkages.py`
- `backend/app/models/orders.py`
- `backend/app/models/contracts.py`

## Executive summary
- Tier 1 (Critical, constitutional violation, ship-blocker): 3 findings
- Tier 2 (High, should fix pre-merge / pre-prod): 2 findings
- Tier 3 (Medium, defer-acceptable): 0 findings
- Tier 4 (Low, hygiene): 0 findings
- Anti-findings (rejection of suspected issues): 1 items

**Overall constitutional posture:** FAIL

## Structured Q&A

### Q1 — Hard-fail em over-allocation
**Answer:** sim
**Evidence:** `backend/app/services/linkage_service.py:47`
```python
        if float(order_linked_qty or 0.0) + quantity_mt > order.quantity_mt:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Linkage exceeds order quantity",
            )
```
**Mechanism:** A alocação é bloqueada lançando `HTTPException` se exceder as quantidades da ordem ou do contrato. A rota intercepta e retorna 400 Bad Request ao invés de usar fallback ou silent capping.
**Severity if violation:** N/A (PASS)

### Q2 — Determinismo da classificação de hedge
**Answer:** sim
**Evidence:** `backend/app/services/contract_service.py:68`
```python
        classification = (
            HedgeClassification.long
            if fixed_leg.side == HedgeLegSideSchema.buy
            else HedgeClassification.short
        )
```
**Mechanism:** A classificação usa um `if/else` explícito derivando deterministicamente do `side` da `fixed_leg` na criação. Ela não depende de strings arbitrárias ou heurísticas externas.
**Severity if violation:** N/A (PASS)

### Q3 — Reconstrutibilidade do cálculo de exposure
**Answer:** sim com ressalvas (snapshot atualizável ao invés de event log)
**Evidence:** `backend/app/services/exposure_engine.py:101`
```python
                if float(existing.open_tons) != open_qty:
                    existing.open_tons = open_qty
                    changed = True
```
**Mechanism:** A `Exposure` é um snapshot persistido (state) que sofre mutações diretas em campos como `open_tons`. No entanto, seu cálculo é reprodutível derivando dos inputs primários (`order.quantity_mt - hedged_qty`) no momento da execução. Não há log de replay interno de eventos de exposure para recalcular, mas pode ser verificado refazendo a consulta a ordens e hedges.
**Severity if violation:** Tier 1 (Audit gap em mutações automáticas abordado no F-A1-GEMINI-05)

### Q4 — Boundary entre commercial e global
**Answer:** sim
**Evidence:** `backend/app/services/exposure_service.py:214`
```python
        commercial_active = float(
            session.query(func.coalesce(func.sum(residual_order_qty), 0.0))
            .outerjoin(linked_by_order, Order.id == linked_by_order.c.order_id)
            .filter(
                Order.order_type == OrderType.sales,
                Order.price_type == PriceType.variable,
            )
```
**Mechanism:** O boundary é preservado estruturalmente nas queries em SQL. `commercial_active` avalia ordens variáveis reduzidas por linkages de ordens. O `global_active` no fim engloba as comerciais e soma separadamente os contratos `short` que não foram atrelados (não linkados ou residuais).
**Severity if violation:** N/A (PASS)

### Q5 — Variable-price vs fixed-price
**Answer:** sim
**Evidence:** `backend/app/services/exposure_engine.py:68`
```python
            # ── Fixed-price orders have no market-price exposure ──
            if order.price_type == PriceType.fixed:
                continue
```
**Mechanism:** O engine explicitamente descarta instâncias com `PriceType.fixed` usando `continue` durante o loop de processamento. A exposure global service também aplica filtros `Order.price_type == PriceType.variable` rigorosamente.
**Severity if violation:** N/A (PASS)

### Q6 — Unidades (MT consistency)
**Answer:** não (problema de tipo de dado)
**Evidence:** `backend/app/models/exposure.py:75`
```python
    original_tons: Mapped[float] = mapped_column(Numeric(15, 3), nullable=False)
```
**Mechanism:** Em que pese a nomenclatura consistentemente apontar pra MT (toneladas), as colunas estão sendo mapeadas para o tipo primitivo `float` do Python em vez de `Decimal`. O uso de `float` pode gerar aproximações em runtime contrariando a precisão financeira estrita.
**Severity if violation:** Tier 2

### Q7 — Evidence / audit trail
**Answer:** não (violações nas tasks asíncronas)
**Evidence:** `backend/app/services/exposure_engine.py:126`
```python
            else:
                exposure = Exposure(
                    ...
                )
                session.add(exposure)
                created += 1
```
**Mechanism:** O processamento em background/batch `reconcile_from_orders` do `ExposureEngineService` realiza `session.commit()` de mutações econômicas mas não invoca nem emite um evento de auditoria. Todas as rotas o fazem via `Depends`, mas o serviço core que cria as exposições silenciosamente atualiza os dados se rodado fora do Request lifecycle.
**Severity if violation:** Tier 1

### Q8 — Determinismo de ordering / iteração
**Answer:** não
**Evidence:** `backend/app/services/exposure_engine.py:157`
```python
        for row in rows:
            c = row.commodity.upper() if row.commodity else row.commodity
            if c not in agg:
                agg[c] = {
```
**Mechanism:** A agregação de exposição itera resultados de uma `session.query` sem um `ORDER BY` definido (nem no lado commercial, nem no global). Popula um dictionary do Python (`agg`) e converte usando `list(agg.values())`. Em banco de dados relacionais e dictionaries do Python (sem key ordering garantida pre-3.7 ou dependendo das inserções) isso torna as posições e agregação não determinísticas em sua saída ordenada.
**Severity if violation:** Tier 1

### Q9 — Concurrency / race conditions
**Answer:** não
**Evidence:** `backend/app/services/linkage_service.py:41`
```python
        order_linked_qty = (
            session.query(func.coalesce(func.sum(HedgeOrderLinkage.quantity_mt), 0.0))
            .filter(HedgeOrderLinkage.order_id == order_id)
            .scalar()
        )
```
**Mechanism:** Não existe isolamento ou trava na checagem de linkage. A validação lê o banco passivamente. Duas requisições submetidas simultaneamente podem passar ambas na validação de overflow para um restante disponível antes do `session.commit()` da primeira, causando um `over-allocation` não detectado.
**Severity if violation:** Tier 2

### Q10 — Hard-fail vs degraded mode
**Answer:** não (fallback silencioso)
**Evidence:** `backend/app/services/deal_engine.py:90`
```python
    except Exception:
        logger.debug(
            "market_price_unavailable commodity=%s date=%s", commodity, as_of_date
        )
        return None
```
**Mechanism:** Na avaliação do mercado para PNL snapshot, se falhar a obtenção do preço de mercado de `price_lookup_service`, um try/except engole a exceção e retorna `None`. Os links subsequentes recebem isso, convertendo `market_price is None` para um MTM de `0.0`. O sistema cai em fallback assumindo zero variação ao invés de realizar `hard-fail`.
**Severity if violation:** Tier 1

## Findings

### F-A1-GEMINI-01 — Silent fallback on market price prevents Hard-fails
- **Files\Lines:** `backend/app/services/deal_engine.py:90-95`
- **Severity:** Tier 1
- **Constitutional rule violated:** §2.6
- **Issue:**
  ```python
    except Exception:
        logger.debug(
            "market_price_unavailable commodity=%s date=%s", commodity, as_of_date
        )
        return None
  ```
- **Mechanism:**
  `deal_engine.py:90` tenta obter o preço de mercado. Em qualquer `Exception`, engole o erro e retorna `None`. Em `deal_engine.py:317` ou `469`, a checagem `if market_price is not None:` ignora o MTM atribuindo `pnl = 0.0`. 
- **Reproduction / impact:**
  Se o provedor de price_lookup estiver offline ou os inputs do reference date falharem, em vez do PNL abortar de ser gravado para não consolidar falsas premissas, ele persiste no banco com o mercado omitido.
- **Suggested direction:**
  Remover a cláusula `except Exception` devolvendo `None`, e permitir falhar a transação se `get_cash_settlement_price_d1` gerar falha.
- **Adjacent risk:**
  Pode impactar `scenario_whatif_service.py` se depender de uma função análoga para modelagem de risco.

### F-A1-GEMINI-02 — Non-deterministic ordering in exposure net aggregation
- **Files\Lines:** `backend/app/services/exposure_engine.py:149-158`
- **Severity:** Tier 1
- **Constitutional rule violated:** §2.6
- **Issue:**
  ```python
        for row in rows:
            c = row.commodity.upper() if row.commodity else row.commodity
            if c not in agg:
                agg[c] = {
                    "commodity": c,
  ```
- **Mechanism:**
  `exposure_engine.py:149` traz uma query que não aplica `.order_by()`. Assim, as agregações no dict `agg` de commodities ocorrem em ordem não-determinística. Por fim, `list(agg.values())` converte a saída baseada inteiramente nessa sequência pseudoaleatória.
- **Reproduction / impact:**
  Qualquer export assíncrono que conte com a ordenação da listagem reportará o JSON final em sequências de chaves dinâmicas, impossibilitando verificações idênticas cross-process ao longo do tempo.
- **Suggested direction:**
  Aplicar `order_by(Exposure.commodity)` no banco e/ou fazer a serialização usar ordenação estável explícita antes de retornar do dict.
- **Adjacent risk:**
  A query não linkada na linha 206 (`gq.all()`) também sofre da mesma falta de `.order_by()`.

### F-A1-GEMINI-03 — Missing Audit Trail on asynchronous Exposure mutation
- **Files\Lines:** `backend/app/services/exposure_engine.py:96-108`
- **Severity:** Tier 1
- **Constitutional rule violated:** §2.7
- **Issue:**
  ```python
                if float(existing.open_tons) != open_qty:
                    existing.open_tons = open_qty
                    changed = True
                if existing.status != exp_status:
                    existing.status = exp_status
                    changed = True
  ```
- **Mechanism:**
  Quando `reconcile_from_orders` é convocado, é feito um bypass silencioso de rotas e o estado de exposure e records do BD é ativamente mutado em iteradores (`session.commit()` em `130`). Nenhum `audit_event` é inserido associado à modificação de status da exposure ou creation.
- **Reproduction / impact:**
  Um cronjob chamando engine service não deixa trail, tornando a reconciliação um "buraco negro" de mudança que não assina HMACS e nem diz quem mudou.
- **Suggested direction:**
  Utilizar o serviço `AuditTrailService` localmente no engine para injetar os eventos de modificação se mudarem as propriedades da exposure.
- **Adjacent risk:**
  Mutações no status de tarefas (`cancel_stale_tasks`) também correm silenciosamente sem audit events.

### F-A1-GEMINI-04 — Race condition without locks on Linkage creation
- **Files\Lines:** `backend/app/services/linkage_service.py:38-44`
- **Severity:** Tier 2
- **Constitutional rule violated:** §2.6
- **Issue:**
  ```python
        order_linked_qty = (
            session.query(func.coalesce(func.sum(HedgeOrderLinkage.quantity_mt), 0.0))
            .filter(HedgeOrderLinkage.order_id == order_id)
            .scalar()
        )
  ```
- **Mechanism:**
  Nenhuma row lock (como `with_for_update()`) é ativada em cima das alocações existentes antes de comitar a nova inserção na base.
- **Reproduction / impact:**
  Ao receber dois posts HTTP paralelos designados a alocar todo o restante de uma ordem com contratos separados, as variáveis no `session.query` seriam lidas sem as reservas do outro, sobrepondo o quantitativo da linkage e criando um over-allocation.
- **Suggested direction:**
  Enforçar isolation levels de transação otimistas ou `with_for_update()` no resgate de `order` e `contract`.
- **Adjacent risk:**
  Pode se alastrar para criação de DealLink se validações cruzadas forem simultâneas.

### F-A1-GEMINI-05 — Financial precision downgraded via primitives
- **Files\Lines:** `backend/app/models/exposure.py:75`
- **Severity:** Tier 2
- **Constitutional rule violated:** §2.1
- **Issue:**
  ```python
    original_tons: Mapped[float] = mapped_column(Numeric(15, 3), nullable=False)
    open_tons: Mapped[float] = mapped_column(Numeric(15, 3), nullable=False)
  ```
- **Mechanism:**
  Campos declarados como Numéricos para suportar as 3 casas de MT estão trafegando na API de Python associados ao builtin primitivo `float`. Python floats são perigosos por conta de aproximação por mantissa da base binária.
- **Reproduction / impact:**
  Soma e subtração contínuas de hedge partial podem deixar decimais flutuantes (`0.000000001` left overs), corrompendo condicionais de exact threshold em regras de fully_hedged se não explicitamente cortadas.
- **Suggested direction:**
  Modificar hints para `Decimal` originadas do lib python local de matemática, instruindo o SQLAlchemy sobre essa equivalência financeira.
- **Adjacent risk:**
  Os schemas e Deal P&L podem estar agregando o mesmo erro nas tabelas de revenue/cost.

## Anti-findings (issues you considered but rejected)

### A-A1-GEMINI-01 — Exposure update doesn't keep historical event log
- **Initial concern:** Em `Q3`, notei que `Exposure` não mantém histórico da mutação internamente nas propriedades — `open_tons` é sobrescrito no loop de engines e perdemos qual era o status prévio no objeto.
- **Actual code:**
  ```python
                if float(existing.open_tons) != open_qty:
                    existing.open_tons = open_qty
                    changed = True
  ```
- **Why it is NOT a bug:**
  A constituição afirma explicitamente na seção `2.1` "Exposure é state, nunca event. Não pode ser persistida como log de mutações que requer replay para reconstruir o estado atual". Portanto, a decisão de mutar um único registro como `snapshot` do estado presente não transgride o modelo canônico.

## Coverage attestation
- Files I read in full: 
  - `backend/app/models/exposure.py`
  - `backend/app/models/deal.py`
  - `backend/app/models/linkages.py`
  - `backend/app/models/orders.py`
  - `backend/app/models/contracts.py`
  - `backend/app/services/exposure_engine.py`
  - `backend/app/services/exposure_service.py`
  - `backend/app/services/deal_engine.py`
  - `backend/app/services/linkage_service.py`
- Files I scanned via grep but did not read fully:
  - `backend/app/services/contract_service.py`
  - `backend/app/api/routes/*`
- Files I did not examine (out of scope): N/A
- Tools used: `git rev-parse HEAD`, `read_file` file iterators, and `grep_search`.

## Open questions for jury
- [NEEDS JURY VERIFICATION] Should the absence of explicit `ORDER BY` in grouping algorithms without strict arrays inherently trigger a Tier 1 Constitutional block (Q8), or does dict-ordering in modern Python 3.7+ mitigate this for deterministic execution?
- [NEEDS JURY VERIFICATION] Is the use of `float` types instead of `Decimal` considered a Tier 1 or Tier 2 violation according to the exact interpretation of your severity rubric for `institutional risk`?
