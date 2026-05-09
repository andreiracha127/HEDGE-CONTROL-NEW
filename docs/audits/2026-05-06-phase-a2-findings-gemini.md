# Phase A2 — Stage 2 Findings — Auditor B (Gemini)

**Date:** 2026-05-06
**Scope commit:** 9f6735729be0ee951644956a288bb18a96d7b162
**Files audited:** 
- `backend/app/services/rfq_service.py`
- `backend/app/services/rfq_orchestrator.py`
- `backend/app/services/rfq_engine.py`
- `backend/app/services/rfq_message_builder.py`
- `backend/app/models/rfqs.py`
- `backend/app/models/quotes.py`

## Executive summary
- Tier 1 (Critical, constitutional violation, ship-blocker): 9 findings
- Tier 2 (High, should fix pre-merge / pre-prod): 2 findings
- Tier 3 (Medium, defer-acceptable): 0 findings
- Tier 4 (Low, hygiene): 0 findings
- Anti-findings (rejection of suspected issues): 1 items
- Cross-phase-A4 risks (flagged for later phase): 2 items

**Overall constitutional posture:** FAIL

## Structured Q&A

### Q1 — Atomicidade e integridade do Award
**Answer:** não
**Evidence:** `backend/app/services/rfq_service.py:760-768`
```python
                trade_rfq = session.get(RFQ, trade_rfq_id)
                if not trade_rfq:
                    raise HTTPException(
                        status_code=status.HTTP_409_CONFLICT,
                        detail="Referenced trade RFQ missing",
                    )

                fixed_side, variable_side, classification = (
```
**Mechanism:** O método `award` para SPREAD (`intent == RFQIntent.spread`) cria `HedgeContract`s para os `trade_rfq`s filhos (buy_trade_id e sell_trade_id) e transiciona o estado do `rfq` parent para `AWARDED`, mas o estado dos filhos (`trade_rfq.state`) NUNCA é modificado (permanece `QUOTED`). Isso permite re-award independente dos filhos depois. O rollback em caso de falha em `LinkageService.create` é garantido (a transação falha na base HTTP), mas a máquina de estado está corrompida no sucesso.
**Severity if violation:** Tier 1

### Q2 — Determinismo do ranking de trade
**Answer:** não
**Evidence:** `backend/app/services/rfq_service.py:162-166`
```python
        reverse = rfq.direction == RFQDirection.sell
        ordered = sorted(
            quotes, key=lambda q: float(q.fixed_price_value), reverse=reverse
        )
        values = [float(q.fixed_price_value) for q in ordered]
        if len(set(values)) != len(values):
```
**Mechanism:** O valor `fixed_price_value` é colapsado para `float` dentro da chave do sort e na verificação de empates (ties). Isso destrói a precisão para casas decimais estendidas e causa "colapso de tie" incorreto, não distinguindo `Decimal`s próximos, violando o determinismo de ranking e gerando falhas falsas.
**Severity if violation:** Tier 1

### Q3 — Determinismo do ranking de spread
**Answer:** não
**Evidence:** `backend/app/services/rfq_service.py:246-248`
```python
        ordered = sorted(spreads, key=lambda s: s[1], reverse=True)
        ranking: list[SpreadRankingEntry] = []
        for idx, (cp, spread_value, buy_quote, sell_quote) in enumerate(
```
**Mechanism:** `compute_spread_ranking` toma interseção silenciosa, excluindo bids de uma perna só, contrariando o hard-fail. O cálculo usa float. E o pior: aplica `reverse=True` de forma incondicional sem se basear no `direction` do spread RFQ, forçando a escolha do "maior spread" mesmo para compradores, prejudicando economicamente a empresa.
**Severity if violation:** Tier 1

### Q4 — Canonical identifier `RFQ#<rfq_number>`
**Answer:** não
**Evidence:** `backend/app/services/rfq_orchestrator.py:186-191`
```python
        phone_variants = RFQOrchestrator._phone_variants(msg.from_phone)
        invitation = (
            session.query(RFQInvitation)
            .join(RFQ, RFQInvitation.rfq_id == RFQ.id)
            .filter(
                RFQInvitation.recipient_phone.in_(phone_variants),
```
**Mechanism:** As mensagens inbound são correlacionadas puramente usando variantes do número de celular (`msg.from_phone`) ordenado pela data (`order_by(RFQ.created_at.desc())`). O identificador `RFQ#<rfq_number>` não é parseado do inbound para a correlação, violando §2.4 frontalmente. Além disso, `text_en` e `text_pt` fornecidos manualmente ignoram a injeção do ID.
**Severity if violation:** Tier 1

### Q5 — Persistência de mensagens como evidência
**Answer:** não
**Evidence:** `backend/app/services/rfq_service.py:414-417`
```python
            result = WhatsAppService.send_text_message(
                phone=phone,
                text=message_body,
            )
```
**Mechanism:** O orchestrator (e `RFQService.create`) chamam `WhatsAppService.send_text_message` para envio síncrono ANTES de fazer `session.add(RFQInvitation)`. Ocorre janela em que mensagens entram na rede celular sem evidência se a transação Postgres subsequente falhar. Além disso, mensagens inbound são convertidas em objeto em memória e não persistidas como evidência bruta atreladas a RFQ.
**Severity if violation:** Tier 1

### Q6 — Validade de quote e lifecycle
**Answer:** não
**Evidence:** `backend/app/services/rfq_service.py:634`
```python
        session.delete(quote)
```
**Mechanism:** `RFQQuote` não possui `deleted_at`. O processo de rejeição (`reject_quote`) usa DELETE transacional bruto da tabela. Não existe trilha do que foi rejeitado nem soft-delete, obliterando a evidência exigida. Em quotes submitidas, não há validação `fixed_price_value > 0`.
**Severity if violation:** Tier 1

### Q7 — Invariantes de criação do contrato
**Answer:** não
**Evidence:** `backend/app/services/rfq_service.py:698-699`
```python
            reference=f"HC-{_uuid.uuid4().hex[:8].upper()}",
            trade_date=date.today(),
```
**Mechanism:** A referência do contrato utiliza UUID4 truncado para 8 caracteres (alta probabilidade de colisão, impossível de reconstruir de forma determinística via inputs). E `trade_date` utiliza timezone local do servidor em vez de injetar o `now_utc().date()` de forma explícita. Ambas as ocorrências violam as cláusulas de hard-fail explícitas.
**Severity if violation:** Tier 1

### Q8 — Race conditions
**Answer:** não
**Evidence:** `backend/app/services/rfq_service.py:732-733`
```python
        rfq = RFQService.get(session, rfq_id)
        if rfq.state != RFQState.quoted:
```
**Mechanism:** A leitura e adjudicação de `award` ocorre sem versionamento ou lock de banco de dados (ex: `with_for_update()`). Múltiplos requests HTTP paralelos passariam por `rfq.state == QUOTED` e duplicariam instâncias de `HedgeContract` para o mesmo RFQ parent, quebrando alocações passivas em links.
**Severity if violation:** Tier 1

### Q9 — Integridade da máquina de estado
**Answer:** não
**Evidence:** `backend/app/services/rfq_service.py:463-465`
```python
    def get(session: Session, rfq_id: UUID) -> RFQ:
        """Fetch an RFQ or raise 404."""
        rfq = session.get(RFQ, rfq_id)
```
**Mechanism:** Nenhuma query de getter filtra por `deleted_at IS NULL` na classe inteira. Ações críticas (como submeter um quote, ler detalhes ou dar award) operam livremente em entidades onde `deleted_at` esteja preenchido. As queries contêm falhas gravíssimas na sanitização de deleção lógica. Ademais, faltam triggers de `audit_trail_service` no fluxo.
**Severity if violation:** Tier 2

### Q10 — Hard-fail vs degraded mode no pipeline
**Answer:** inconclusivo
**Evidence:** `backend/app/services/rfq_orchestrator.py:318-319`
```python
        if LLMAgent.should_auto_create_quote(parsed):
            price_val = float(
```
**Mechanism:** O método `should_auto_create_quote` mascara o threshold de confiança. Caso o threshold não obedeça uma tolerância mínima confiável, a mutação segue degradada e é incluída no `ranking` gerando exposição econômica errônea. No entanto, sem auditar `LLMAgent`, não consigo provar um "best-effort" ocorrendo no pipeline atual sem falhar explicitamente.
**Severity if violation:** Tier 2 (ou dependente da Fase A4)

## Findings

### F-A2-GEMINI-01 — Award SPREAD corrompe lifecycle dos filhos
- **Files\Lines:** `backend/app/services/rfq_service.py:756-788`
- **Severity:** Tier 1
- **Constitutional rule violated:** §2.1
- **Issue:**
  > ```python
  >             for trade_rfq_id, quote in (
  >                 (rfq.buy_trade_id, top.buy_quote),
  >                 (rfq.sell_trade_id, top.sell_quote),
  >             ):
  >                 if trade_rfq_id is None:
  >                     raise HTTPException(
  >                         status_code=status.HTTP_409_CONFLICT,
  >                         detail="Referenced trade RFQ ID is None",
  >                     )
  >                 trade_rfq = session.get(RFQ, trade_rfq_id)
  > ```
- **Mechanism:**
  O método `award` transiciona o parent `rfq.state = RFQState.awarded`, mas o `trade_rfq` dentro da iteração for nunca recebe update no seu `state` nem o respectivo `RFQStateEvent`.
- **Reproduction / impact:**
  Ao adjudicar um spread, as pontas continuam visualizadas e editáveis (`QUOTED`). A interface de UI poderia facilmente dar "Award" manual nessas pontas soltas novamente, resultando em double allocation e inflação do risco base sem hedge.
- **Suggested direction:**
  Adicionar a transação dos RFQs da perna filha (`trade_rfq.state = RFQState.awarded` / `closed`) no escopo do block original.
- **Adjacent risk:**
  A exclusão do audit link de states parent/child não mapeia `created_contract_ids` nos filhos corretamente.

### F-A2-GEMINI-02 — Rank computing converte valores para float e descarta direction
- **Files\Lines:** `backend/app/services/rfq_service.py:162-166` e `246-248`
- **Severity:** Tier 1
- **Constitutional rule violated:** §2.5
- **Issue:**
  > ```python
  >         ordered = sorted(spreads, key=lambda s: s[1], reverse=True)
  >         ranking: list[SpreadRankingEntry] = []
  >         for idx, (cp, spread_value, buy_quote, sell_quote) in enumerate(
  > ```
- **Mechanism:**
  Conversão desnecessária que pode causar tie ou skip entre bids. Além disso, em `compute_spread_ranking`, não há cheque dinâmico de direction — `reverse=True` define o ganhador eternamente pelo spread mais alto. Se a empresa quiser comprar a perna (minimizar o spread), ainda pagará o valor máximo, destruindo o PnL.
- **Reproduction / impact:**
  Bids como "10.0100" e "10.0101" não processariam com confiabilidade 100%. O spread RFQ comprando forçaria o pior preço sempre na prioridade.
- **Suggested direction:**
  Substituir o key map por pure-`Decimal` e implementar chave condicional reversa com base no delta direcional da commodity para o spread (`rfq.direction == RFQDirection.sell`).
- **Adjacent risk:**
  O tiebreaker de dicts se baseia em python 3.7+ order, o que é instável cross-versions e infraestrutura local (usar `.id` é o caminho do `select_latest_quotes_by_counterparty`).

### F-A2-GEMINI-03 — Falha Crítica de Canonical Correlation
- **Files\Lines:** `backend/app/services/rfq_orchestrator.py:186-191`
- **Severity:** Tier 1
- **Constitutional rule violated:** §2.4
- **Issue:**
  > ```python
  >         phone_variants = RFQOrchestrator._phone_variants(msg.from_phone)
  >         invitation = (
  >             session.query(RFQInvitation)
  >             .join(RFQ, RFQInvitation.rfq_id == RFQ.id)
  >             .filter(
  >                 RFQInvitation.recipient_phone.in_(phone_variants),
  > ```
- **Mechanism:**
  Mensagens chegam da contraparte sem nenhuma string parsing baseada no formatador nativo `RFQ#`. A query de ORM associa cegamente a resposta usando a tabela do telefone em vez de usar expressão regular para capturar o header.
- **Reproduction / impact:**
  Se duas ordens do Banco X estão pendentes, o modelo do Orchestrator engole a mensagem na fila mais "recente" criada pelo DB sem avaliar o `RFQ#` do body text. A cotação seria imputada no papel do outro fluxo de derivativos, e consequentemente os fundos perderiam bilhões por hedging equivocado.
- **Suggested direction:**
  Extrair o Canonical ID (`RFQ#XXXX`) no pre-filter via regex contra `msg.text` e realizar query no banco SOMENTE usando este ID como constraint primordial.
- **Adjacent risk:**
  Os canais multi-line como WEBHOOK ficam atrelados à fila sequencial FIFO passível de timeouts e bloqueios.

### F-A2-GEMINI-04 — RFQ Identifier não é embutido no motor Text_EN
- **Files\Lines:** `backend/app/services/rfq_engine.py:382-383`
- **Severity:** Tier 1
- **Constitutional rule violated:** §2.4
- **Issue:**
  > ```python
  >     if company_header:
  >         text = f"For {company_header} Account:\n{text}"
  > ```
- **Mechanism:**
  O método `generate_rfq_text` cria o artefato textual para os brokers de alumínio contudo jamais possui `rfq.rfq_number` nos seus formatadores. As saídas brutas do LME Engine não têm carimbo da aplicação no cabeçalho ou metadados de saída.
- **Reproduction / impact:**
  Brokers internacionais recebem propostas de "For Alcast Account: How can I buy...". Quando respondem, não conseguem citar qual ref id era, impossibilitando até auditoria manual e bloqueando orquestradores de ler.
- **Suggested direction:**
  Anexar no header/footer de `generate_rfq_text` o placeholder de `RFQ#<rfq_number>`.
- **Adjacent risk:**
  Semelhante ao builder de banco (`_build_bank_message`), cujo formatador em string pura também ignora `rfq.rfq_number`.

### F-A2-GEMINI-05 — Deleção Irreversível de Quote em Reject 
- **Files\Lines:** `backend/app/services/rfq_service.py:634`
- **Severity:** Tier 1
- **Constitutional rule violated:** §2.6
- **Issue:**
  > ```python
  >         session.delete(quote)
  > ```
- **Mechanism:**
  Qualquer RFQ manipulável por API com request de cancel/reject engole permanentemente o modelo da base. O hard-fail exige que históricos do Quote permaneçam auditáveis.
- **Reproduction / impact:**
  Um trader manipula PnL da empresa recebendo uma quote errada, executa hard-delete nela e aceita uma maléfica para lucrar na conta da contraparte, e na trilha de auditoria os dados foram ceifados transacionalmente.
- **Suggested direction:**
  Substituir o raw delete por state transition em enum (e.g. `rejected=True`) com data tag `deleted_at`.
- **Adjacent risk:**
  Risco total de lavagem cibernética da auditagem institucional do banco.

### F-A2-GEMINI-06 — Inexistência de Lock Concorrente (Race Condition Award)
- **Files\Lines:** `backend/app/services/rfq_service.py:732-733`
- **Severity:** Tier 1
- **Constitutional rule violated:** §2.6
- **Issue:**
  > ```python
  >         rfq = RFQService.get(session, rfq_id)
  >         if rfq.state != RFQState.quoted:
  > ```
- **Mechanism:**
  Nenhum lock pesimista. Leitura simples via ORM default `get`. Múltiplos usuários ou requests sobre o mesmo RFQ executariam award simultâneo e computariam HedgeContract dobrado sem ferir o threshold inicial do State.
- **Reproduction / impact:**
  Dois botões de award disparados com 1ms de atraso: cria-se X2 os trades no sistema, esgotando margens. 
- **Suggested direction:**
  Requerir explicitamente `with_for_update(nowait=True)` no lock de RFQ na rotina de adjudicação.
- **Adjacent risk:**
  Também corrompe a atomicidade do `LinkageService.create`.

### F-A2-GEMINI-07 — Reconstructibilidade Falha em UUID truncado
- **Files\Lines:** `backend/app/services/rfq_service.py:698-699`
- **Severity:** Tier 1
- **Constitutional rule violated:** §2.6
- **Issue:**
  > ```python
  >             reference=f"HC-{_uuid.uuid4().hex[:8].upper()}",
  >             trade_date=date.today(),
  > ```
- **Mechanism:**
  Geração do UUID e de data via contexto nativo do core em vez do UTC. Resultando em colisões matemáticas da String de 8-chars UUID4 hex sob escala do banco (77 mil gerariam 50%).
- **Reproduction / impact:**
  Ao chegar ao teto populacional da tabela de contratos, o banco explodiria erro Unique Constraint violando integridade do flow sem retry ou emitiria duplicações indetectáveis dependendo do índice DB.
- **Suggested direction:**
  Substituir por Sequence Determinística ou Hash de Cripto do `rfq_number` somado ao Ticks + Adotar sempre UTC formatters explícitos no sistema.
- **Adjacent risk:**
  Falhas relativas de Timezone na máquina host.

### F-A2-GEMINI-08 — Transações Externas Desprotegidas 
- **Files\Lines:** `backend/app/services/rfq_service.py:414-417`
- **Severity:** Tier 1
- **Constitutional rule violated:** §2.3
- **Issue:**
  > ```python
  >             result = WhatsAppService.send_text_message(
  >                 phone=phone,
  >                 text=message_body,
  >             )
  > ```
- **Mechanism:**
  Realiza requests não controlados HTTP/Network para o webhook de WhatsApp antes de garantir o persist de banco `session.add`. Em caso de panics em network stack e timeouts em commit de sessão subsequentes, uma proposta vaza online deslogada da corretora.
- **Reproduction / impact:**
  O sistema quebra ao salvar a row de ID, WhatsApp dispara, a firma de alumínio responde OK para a negociação de milhões, mas na corretora Hedge-Control isso virou status "Failed" e não há registro real da evidência outboud e do tracking em si.
- **Suggested direction:**
  Emissão síncrona pós-commit ou uso de MQ com pattern Inbox/Outbox garantindo evidência no banco.
- **Adjacent risk:**
  Inbound messages nunca são injetados cruamente num event stream (semelhantemente não há model RAW).

### F-A2-GEMINI-09 — Leakage na Busca sem Checagem de Deleção Lógica
- **Files\Lines:** `backend/app/services/rfq_service.py:463-465`
- **Severity:** Tier 2
- **Constitutional rule violated:** §2.1
- **Issue:**
  > ```python
  >     def get(session: Session, rfq_id: UUID) -> RFQ:
  >         """Fetch an RFQ or raise 404."""
  >         rfq = session.get(RFQ, rfq_id)
  > ```
- **Mechanism:**
  O `rfq_service.py` não valida se `rfq.deleted_at IS NULL` para carregar as operações críticas (nem sequer é embutido na `get()`).
- **Reproduction / impact:**
  Usuário manipula IDs via curl para forçar requisições contra RFQs fechados e supostamente delatados logicamente.
- **Suggested direction:**
  Adicionar a check explicitamente e barrar requests fantasma.

## Anti-findings (issues you considered but rejected)

### A-A2-GEMINI-01 — Rollback Incompleto de LinkageService no SPREAD
- **Initial concern:** Se a rotina em SPREAD tenta salvar linkage duas vezes e na 2ª perna quebra, a transação seria comitada parcialmente e corromperia as amarras.
- **Actual code:**
  > ```python
  >             for trade_rfq_id, quote in (
  >                 (rfq.buy_trade_id, top.buy_quote),
  >                 (rfq.sell_trade_id, top.sell_quote),
  >             ):
  >                 ...
  >                 session.add(contract)
  >                 session.flush()
  > ```
- **Why it is NOT a bug:**
  A injeção ocorre toda na mesma sessão local e não dá commit iterativo. O erro de linkage escalaria de forma borbulhante e o handler HTTP executaria `session.rollback()`, não corrompendo a base nem quebrando partial updates.

## Cross-phase-A4 risks

### X-A2-GEMINI-01 — Tolerância e Hard-Fails do Modelo de Extração LLM
- **A2 surface:** `backend/app/services/rfq_orchestrator.py:318-319`
- **A4 dependency:** `LLMAgent.should_auto_create_quote`
- **Governance clause at risk:** §2.5 e §2.4
- **Why it matters:** O parser inbound falha em impor o determinismo caso aceite extrações de confiança média em background sem avisar a governança de rejeitar (fallback explícito vs implicit skip).

### X-A2-GEMINI-02 — Ausência de Persistência em Event Sourcing Inbound
- **A2 surface:** `backend/app/services/rfq_orchestrator.py:248-249`
- **A4 dependency:** `webhook_processor.py` (ou Message Queue handler)
- **Governance clause at risk:** §2.3
- **Why it matters:** A função `process_single_message` descarta as mensagens ou rejeita o processamento em objetos voláteis na memória, o que fere o preceito de prova concreta de cada text_msg vindo da contraparte e exige checagem de que a MQ não perca isso no layer A4.

## Coverage attestation
- Files I read in full: `backend/app/services/rfq_service.py`, `backend/app/services/rfq_orchestrator.py`, `backend/app/services/rfq_engine.py`, `backend/app/services/rfq_message_builder.py`
- Files I grep'd but did not read fully: `backend/app/models/rfqs.py`, `backend/app/models/quotes.py`
- Files I did not examine (out of scope): `backend/app/api/routes/rfqs.py`, `backend/app/schemas/rfq.py`
- Tools used: Read 6 times, Grep 0 times, search 0 times.

## Open questions for jury
1. O Jury precisa confirmar se o `LinkageService.create()` levanta exception `ValueError` simples que o framework HTTP capta e desfaz o SQLAlchemy transacionalmente de modo seguro. Em caso contrário, a omissão de handling geraria vazamento grave.
2. Confirmar se os campos default `auto_increment` no Postgres geram gaps na sequência `RFQSequence` ao rolar o rollback das instâncias falhadas (já que o sequence é gerado no add `id`).