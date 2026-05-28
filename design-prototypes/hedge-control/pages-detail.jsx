/* Detail pages + new-entity forms:
   - OrderNewPage          (PO / SO commercial order)
   - CounterpartyNewPage   (identificação, contato, financeiro & compliance)
   - CounterpartyDetailPage
   - ContractDetailPage
*/

(function () {
const M = window.MOCK;

function FeedItem({ kind, when, who, what }) {
  return (
    <div className={"feed-item " + kind}>
      <div className="icon"/>
      <div>
        <div className="what">{what}</div>
        <div className="row gap-2"><span className="when">{when}</span><span className="who">· {who}</span></div>
      </div>
    </div>
  );
}

function DocLink({ name, size }) {
  return (
    <a href="#" className="row gap-2" style={{ padding: '6px 0', fontSize: 12.5, color: 'var(--ink-2)' }} onClick={e=>e.preventDefault()}>
      <Icon.Doc/>
      <span style={{ flex: 1 }}>{name}</span>
      <span style={{ color: 'var(--muted)', fontSize: 11 }}>{size}</span>
      <Icon.Download/>
    </a>
  );
}

// ============================================================
// ORDER NEW · Purchase / Sales order
// ============================================================
function OrderNewPage() {
  const [orderType, setOrderType] = React.useState('PO');
  const [commodity, setCommodity] = React.useState('ALUMINIUM');
  const [qty, setQty] = React.useState('1500');
  const [priceType, setPriceType] = React.useState('fixed');
  const [pricingConv, setPricingConv] = React.useState('LME-OFFICIAL');
  const [price, setPrice] = React.useState('2631.00');
  const [currency, setCurrency] = React.useState('USD');
  const [cp, setCp] = React.useState('');
  const [delivery, setDelivery] = React.useState('2026-06-30');
  const [reference, setReference] = React.useState('');
  const [notes, setNotes] = React.useState('');

  const isPO = orderType === 'PO';

  return (
    <div className="page">
      <div className="page-head">
        <div>
          <div className="row gap-2" style={{ marginBottom: 4 }}>
            <button className="btn btn-link" onClick={() => (window.location.hash = '#/orders')}><Icon.ArrowLeft/> Ordens</button>
            <span style={{ color: 'var(--muted)' }}>/</span>
            <span style={{ fontSize: 12, color: 'var(--muted)' }}>Nova ordem comercial</span>
          </div>
          <h1 className="page-title">Nova ordem comercial</h1>
          <div className="page-sub">Registra a fonte da exposição · {isPO ? 'compra de matéria-prima (PO)' : 'venda de produto final (SO)'}</div>
        </div>
        <div className="page-actions">
          <button className="btn btn-ghost" onClick={() => (window.location.hash = '#/orders')}>Cancelar</button>
          <button className="btn btn-secondary">Salvar rascunho</button>
          <button className="btn btn-primary"><Icon.ShieldCheck/>Criar ordem</button>
        </div>
      </div>

      <div className="detail-grid">
        <div className="stack gap-4">
          <Card title={<>1. Tipo de ordem <InfoTip>Define se a ordem gera <strong>exposição ativa</strong> (venda futura) ou <strong>passiva</strong> (compra futura).</InfoTip></>}>
            <div className="grid-2">
              <button
                className="card"
                style={{ padding: 14, textAlign: 'left', cursor: 'pointer', borderColor: orderType==='PO'?'var(--navy)':'var(--line-strong)', background: orderType==='PO'?'#F4F7FC':'#fff' }}
                onClick={()=>setOrderType('PO')}>
                <div className="row gap-2">
                  <Badge kind="info" dot>PO · Purchase Order</Badge>
                  <InfoTip>Compra de matéria-prima — gera <strong>exposição passiva</strong>. Hedge se faz com <strong>compra</strong> de derivativo.</InfoTip>
                  {orderType==='PO' && <span style={{ marginLeft: 'auto', color: 'var(--navy)' }}>●</span>}
                </div>
              </button>
              <button
                className="card"
                style={{ padding: 14, textAlign: 'left', cursor: 'pointer', borderColor: orderType==='SO'?'var(--navy)':'var(--line-strong)', background: orderType==='SO'?'#F4F7FC':'#fff' }}
                onClick={()=>setOrderType('SO')}>
                <div className="row gap-2">
                  <Badge kind="pos" dot>SO · Sales Order</Badge>
                  <InfoTip>Venda de produto final — gera <strong>exposição ativa</strong>. Hedge se faz com <strong>venda</strong> de derivativo.</InfoTip>
                  {orderType==='SO' && <span style={{ marginLeft: 'auto', color: 'var(--navy)' }}>●</span>}
                </div>
              </button>
            </div>
          </Card>

          <Card title="2. Identificação">
            <div className="field-grid">
              <div className="field">
                <label className="field-label">Número de referência (PO/SO) <span className="req">*</span> <InfoTip>Espelho do ERP/SAP. Usado para vincular RFQs de hedge a esta ordem comercial.</InfoTip></label>
                <input className="input mono" placeholder={isPO ? "PO-2026-1185" : "SO-2026-0943"} value={reference} onChange={e=>setReference(e.target.value)}/>
              </div>
              <div className="field">
                <label className="field-label">Contraparte <span className="req">*</span></label>
                <select className="select" value={cp} onChange={e=>setCp(e.target.value)}>
                  <option value="">— Selecione —</option>
                  {M.counterparties.map(c => <option key={c.id} value={c.short}>{c.name} ({c.short})</option>)}
                </select>
              </div>
            </div>
          </Card>

          <Card title="3. Volume e precificação">
            <div className="field-grid">
              <div className="field">
                <label className="field-label">Commodity <span className="req">*</span></label>
                <select className="select" value={commodity} onChange={e=>setCommodity(e.target.value)}>
                  <option value="ALUMINIUM">ALUMINIUM</option>
                </select>
              </div>
              <div className="field">
                <label className="field-label">Quantidade <span className="req">*</span></label>
                <div className="input-suffix">
                  <input className="input" value={qty} onChange={e=>setQty(e.target.value)} type="number" step="0.001"/>
                  <span className="suffix">MT</span>
                </div>
              </div>

              <div className="field" style={{ gridColumn: '1 / -1' }}>
                <label className="field-label">Tipo de preço <span className="req">*</span> <InfoTip width={280}><strong>Fixo:</strong> preço definido em contrato — sem exposição a preço, mas pode haver exposição cambial.<br/><br/><strong>Variável:</strong> atrelado ao LME — gera exposição à commodity até a liquidação.</InfoTip></label>
                <div className="radio-group">
                  <button className={priceType==='fixed'?'active':''} onClick={()=>setPriceType('fixed')}>Preço fixo</button>
                  <button className={priceType==='variable'?'active':''} onClick={()=>setPriceType('variable')}>Preço variável (indexado)</button>
                </div>
              </div>

              <div className="field">
                <label className="field-label">Convenção de precificação <span className="req">*</span> <InfoTip width={260}>Define qual cotação LME será usada na liquidação variável (Official, Cash, 3-Month, ou médias mensais).</InfoTip></label>
                <select className="select" value={pricingConv} onChange={e=>setPricingConv(e.target.value)}>
                  <option value="LME-OFFICIAL">LME Official Settlement</option>
                  <option value="LME-CASH">LME Cash</option>
                  <option value="LME-3M">LME 3-Month</option>
                  <option value="LME-AVG-M">LME Average (mês de entrega)</option>
                  <option value="LME-AVG-M1">LME Average M+1</option>
                </select>
              </div>

              <div className="field">
                <label className="field-label">{priceType==='fixed' ? 'Preço fixo' : 'Prêmio / desconto vs LME'} <span className="req">*</span></label>
                <div className="input-suffix">
                  <input className="input" value={price} onChange={e=>setPrice(e.target.value)} type="number" step="0.01"/>
                  <span className="suffix">{currency}/MT</span>
                </div>
              </div>

              <div className="field">
                <label className="field-label">Moeda <span className="req">*</span></label>
                <select className="select" value={currency} onChange={e=>setCurrency(e.target.value)}>
                  <option value="USD">USD</option>
                  <option value="BRL">BRL</option>
                  <option value="EUR">EUR</option>
                </select>
              </div>

              <div className="field">
                <label className="field-label">Data de entrega <span className="req">*</span> <InfoTip>Define a janela de exposição.</InfoTip></label>
                <input className="input" type="date" value={delivery} onChange={e=>setDelivery(e.target.value)}/>
              </div>
            </div>
          </Card>

          <Card title="4. Observações" sub="Visível apenas internamente">
            <textarea className="textarea" value={notes} onChange={e=>setNotes(e.target.value)} placeholder="Notas internas, link com contrato, condições especiais…"/>
          </Card>
        </div>

        <div className="stack gap-4" style={{ position: 'sticky', top: 72, alignSelf: 'start' }}>
          <Card title="Resumo">
            <dl className="kv">
              <dt>Tipo</dt><dd>{isPO ? <Badge kind="info" dot>PO · Compra</Badge> : <Badge kind="pos" dot>SO · Venda</Badge>}</dd>
              <dt>Referência</dt><dd className="mono">{reference || '—'}</dd>
              <dt>Contraparte</dt><dd>{cp || '—'}</dd>
              <dt>Commodity</dt><dd>{commodity}</dd>
              <dt>Quantidade</dt><dd className="tabular">{Number(qty || 0).toLocaleString('pt-BR')} MT</dd>
              <dt>Preço</dt><dd className="tabular">{Number(price || 0).toLocaleString('pt-BR', { minimumFractionDigits: 2 })} {currency}/MT</dd>
              <dt>Notional</dt><dd className="tabular strong">{currency} {(Number(qty)*Number(price)).toLocaleString('pt-BR', { maximumFractionDigits: 0 })}</dd>
              <dt>Entrega</dt><dd>{delivery.split('-').reverse().join('/')}</dd>
            </dl>
          </Card>

          <Card title="Impacto em exposições">
            <dl className="kv">
              <dt>Janela</dt><dd>{new Date(delivery).toLocaleDateString('pt-BR', { month: 'short', year: '2-digit' })}</dd>
              <dt>Comercial atual</dt><dd className="tabular">4.200 MT</dd>
              <dt>+ Esta ordem</dt><dd className="tabular" style={{ color: isPO?'var(--info)':'var(--pos)' }}>{isPO?'+':'+'}{Number(qty||0).toLocaleString('pt-BR')} MT {isPO?'(passiva)':'(ativa)'}</dd>
              <dt>Projetada</dt><dd className="tabular strong">{(4200+Number(qty||0)).toLocaleString('pt-BR')} MT</dd>
              <dt>Hedge ratio</dt><dd className="tabular">{priceType==='variable'?'cai para 67,2 %':'inalterado (preço fixo)'}</dd>
            </dl>
            {priceType==='variable' && (
              <div className="row gap-2" style={{ marginTop: 8, fontSize: 11.5 }}>
                <Badge kind="warn" dot>Sugestão</Badge>
                <span style={{ color: 'var(--muted)' }}>Criar RFQ de hedge para esta ordem após o registro</span>
              </div>
            )}
          </Card>

          <Card title="Pré-validações">
            <div className="stack gap-2">
              <Validation ok={!!reference} label={reference?'Referência informada':'Referência obrigatória'}/>
              <Validation ok={!!cp} label={cp?'Contraparte selecionada':'Sem contraparte'}/>
              <Validation ok={Number(qty)>0} label="Quantidade válida"/>
              <Validation ok={Number(price)>0} label="Preço informado"/>
              <Validation ok label="Convenção de precificação suportada"/>
            </div>
          </Card>
        </div>
      </div>
    </div>
  );
}

// ============================================================
// COUNTERPARTY NEW
// ============================================================
function CounterpartyNewPage() {
  const [type, setType] = React.useState('broker');
  const [name, setName] = React.useState('');
  const [shortName, setShortName] = React.useState('');
  const [taxId, setTaxId] = React.useState('');
  const [country, setCountry] = React.useState('BRA');
  const [city, setCity] = React.useState('');
  const [address, setAddress] = React.useState('');
  const [contactName, setContactName] = React.useState('');
  const [contactEmail, setContactEmail] = React.useState('');
  const [contactPhone, setContactPhone] = React.useState('');
  const [whatsapp, setWhatsapp] = React.useState('');
  const [paymentTerms, setPaymentTerms] = React.useState('30');
  const [creditLimit, setCreditLimit] = React.useState('5000000');
  const [riskRating, setRiskRating] = React.useState('medium');
  const [sanctions, setSanctions] = React.useState('clear');
  const [notes, setNotes] = React.useState('');

  return (
    <div className="page">
      <div className="page-head">
        <div>
          <div className="row gap-2" style={{ marginBottom: 4 }}>
            <button className="btn btn-link" onClick={() => (window.location.hash = '#/counterparties')}><Icon.ArrowLeft/> Contrapartes</button>
            <span style={{ color: 'var(--muted)' }}>/</span>
            <span style={{ fontSize: 12, color: 'var(--muted)' }}>Nova contraparte</span>
          </div>
          <h1 className="page-title">Nova contraparte</h1>
          <div className="page-sub">Cadastro inicial — KYC, sanctions screening e limite serão revisados pelo time de Risco</div>
        </div>
        <div className="page-actions">
          <button className="btn btn-ghost" onClick={() => (window.location.hash = '#/counterparties')}>Cancelar</button>
          <button className="btn btn-secondary">Salvar rascunho</button>
          <button className="btn btn-primary"><Icon.Plus/>Criar contraparte</button>
        </div>
      </div>

      <div className="detail-grid">
        <div className="stack gap-4">
          <Card title="1. Identificação" sub="Dados cadastrais e jurídicos">
            <div className="field-grid">
              <div className="field">
                <label className="field-label">Tipo <span className="req">*</span></label>
                <select className="select" value={type} onChange={e=>setType(e.target.value)}>
                  <option value="broker">Broker / corretora</option>
                  <option value="bank_br">Banco BR</option>
                  <option value="customer">Cliente</option>
                  <option value="supplier">Fornecedor</option>
                </select>
              </div>
              <div className="field">
                <label className="field-label">Razão social <span className="req">*</span></label>
                <input className="input" value={name} onChange={e=>setName(e.target.value)} placeholder="Itaú BBA S.A." maxLength={200}/>
              </div>
              <div className="field">
                <label className="field-label">Abreviação <InfoTip>Sigla curta usada em tabelas e badges (até 6 caracteres).</InfoTip></label>
                <input className="input" value={shortName} onChange={e=>setShortName(e.target.value)} placeholder="ITAU" maxLength={50}/>
              </div>
              <div className="field">
                <label className="field-label">Tax ID</label>
                <input className="input mono" value={taxId} onChange={e=>setTaxId(e.target.value)} placeholder="CNPJ ou VAT internacional"/>
              </div>
              <div className="field">
                <label className="field-label">País <span className="req">*</span> <InfoTip>ISO 3166-1 alfa-3 · 3 letras maiúsculas (BRA, USA, GBR, DEU…).</InfoTip></label>
                <input className="input" value={country} onChange={e=>setCountry(e.target.value.toUpperCase())} placeholder="BRA" maxLength={3} style={{ textTransform: 'uppercase' }}/>
              </div>
              <div className="field">
                <label className="field-label">Cidade</label>
                <input className="input" value={city} onChange={e=>setCity(e.target.value)} placeholder="São Paulo"/>
              </div>
              <div className="field" style={{ gridColumn: '1 / -1' }}>
                <label className="field-label">Endereço</label>
                <input className="input" value={address} onChange={e=>setAddress(e.target.value)} placeholder="Av. Brigadeiro Faria Lima, 3500 — 04538-132"/>
              </div>
            </div>
          </Card>

          <Card title="2. Contato">
            <div className="field-grid">
              <div className="field">
                <label className="field-label">Nome do contato</label>
                <input className="input" value={contactName} onChange={e=>setContactName(e.target.value)} placeholder="Maria Santos"/>
              </div>
              <div className="field">
                <label className="field-label">Email</label>
                <input className="input" value={contactEmail} onChange={e=>setContactEmail(e.target.value)} placeholder="msantos@contraparte.com.br" type="email"/>
              </div>
              <div className="field">
                <label className="field-label">Telefone</label>
                <input className="input" value={contactPhone} onChange={e=>setContactPhone(e.target.value)} placeholder="+55 11 3000-0000"/>
              </div>
              <div className="field">
                <label className="field-label">WhatsApp <InfoTip>Usado para envio de RFQ via mensageria.</InfoTip></label>
                <input className="input" value={whatsapp} onChange={e=>setWhatsapp(e.target.value)} placeholder="+5511999999999"/>
              </div>
            </div>
          </Card>

          <Card title="3. Financeiro & compliance" sub="Limites de crédito, classificação e screening de sanções">
            <div className="field-grid">
              <div className="field">
                <label className="field-label">Prazo de pagamento</label>
                <div className="input-suffix">
                  <input className="input" value={paymentTerms} onChange={e=>setPaymentTerms(e.target.value)} type="number" min={1}/>
                  <span className="suffix">dias</span>
                </div>
              </div>
              <div className="field">
                <label className="field-label">Limite de crédito <InfoTip>Aprovação adicional necessária acima de US$ 10 M.</InfoTip></label>
                <div className="input-suffix">
                  <input className="input" value={creditLimit} onChange={e=>setCreditLimit(e.target.value)} type="number"/>
                  <span className="suffix">USD</span>
                </div>
              </div>
              <div className="field">
                <label className="field-label">Classificação de risco</label>
                <div className="radio-group">
                  <button className={riskRating==='low'?'active':''} onClick={()=>setRiskRating('low')}>Baixo</button>
                  <button className={riskRating==='medium'?'active':''} onClick={()=>setRiskRating('medium')}>Médio</button>
                  <button className={riskRating==='high'?'active':''} onClick={()=>setRiskRating('high')}>Alto</button>
                </div>
              </div>
              <div className="field">
                <label className="field-label">Sanctions screening <InfoTip>Resultado da varredura OFAC / Bacen / EU sanctions.</InfoTip></label>
                <div className="radio-group">
                  <button className={sanctions==='clear'?'active':''} onClick={()=>setSanctions('clear')}>Clear</button>
                  <button className={sanctions==='flagged'?'active':''} onClick={()=>setSanctions('flagged')}>Flagged</button>
                  <button className={sanctions==='blocked'?'active':''} onClick={()=>setSanctions('blocked')}>Blocked</button>
                </div>
              </div>
              <div className="field" style={{ gridColumn: '1 / -1' }}>
                <label className="field-label">Observações</label>
                <textarea className="textarea" value={notes} onChange={e=>setNotes(e.target.value)} placeholder="Histórico, restrições, instruções específicas para a mesa…"/>
              </div>
            </div>
          </Card>
        </div>

        <div className="stack gap-4" style={{ position: 'sticky', top: 72, alignSelf: 'start' }}>
          <Card title="Resumo">
            <dl className="kv">
              <dt>Tipo</dt><dd>{({broker:'Broker',bank_br:'Banco BR',customer:'Cliente',supplier:'Fornecedor'})[type]}</dd>
              <dt>Razão social</dt><dd>{name || '—'}</dd>
              <dt>Abreviação</dt><dd>{shortName || '—'}</dd>
              <dt>País</dt><dd>{country}</dd>
              <dt>Limite</dt><dd className="tabular">US$ {(Number(creditLimit||0)/1000000).toFixed(1)} M</dd>
              <dt>Risco</dt><dd>{riskRating==='low'?<Badge kind="pos" dot>Baixo</Badge>:riskRating==='high'?<Badge kind="neg" dot>Alto</Badge>:<Badge kind="warn" dot>Médio</Badge>}</dd>
              <dt>Sanctions</dt><dd>{sanctions==='clear'?<Badge kind="pos" dot>Clear</Badge>:sanctions==='blocked'?<Badge kind="neg" dot>Blocked</Badge>:<Badge kind="warn" dot>Flagged</Badge>}</dd>
            </dl>
          </Card>

          <Card title="Próximos passos">
            <div className="stack gap-2" style={{ fontSize: 12.5 }}>
              <div className="row gap-2"><span style={{ width: 18, height: 18, borderRadius: '50%', background: 'var(--orange)', color: '#fff', display: 'grid', placeItems: 'center', fontSize: 10, fontWeight: 600 }}>1</span>Time de Risco revisa KYC (até 2 dias úteis)</div>
              <div className="row gap-2"><span style={{ width: 18, height: 18, borderRadius: '50%', background: 'var(--line-strong)', color: '#fff', display: 'grid', placeItems: 'center', fontSize: 10, fontWeight: 600 }}>2</span>Aprovação do limite no comitê</div>
              <div className="row gap-2"><span style={{ width: 18, height: 18, borderRadius: '50%', background: 'var(--line-strong)', color: '#fff', display: 'grid', placeItems: 'center', fontSize: 10, fontWeight: 600 }}>3</span>Habilitação para operar RFQs</div>
            </div>
          </Card>
        </div>
      </div>
    </div>
  );
}

// ============================================================
// COUNTERPARTY DETAIL
// ============================================================
function CounterpartyDetailPage({ id }) {
  const cp = M.counterparties.find(c => c.id === id || c.short === id) || M.counterparties[0];
  const [tab, setTab] = React.useState('resumo');
  const usePct = (cp.used / cp.limit) * 100;
  const contracts = M.contracts.filter(c => c.cp === cp.short);
  const mtm = contracts.reduce((s, c) => s + c.mtm, 0);

  return (
    <div className="page">
      <div className="page-head">
        <div style={{ flex: 1 }}>
          <div className="row gap-2" style={{ marginBottom: 4 }}>
            <button className="btn btn-link" onClick={() => (window.location.hash = '#/counterparties')}><Icon.ArrowLeft/> Contrapartes</button>
            <span style={{ color: 'var(--muted)' }}>/</span>
            <span className="mono" style={{ fontSize: 12, color: 'var(--muted)' }}>{cp.id}</span>
          </div>
          <div className="row gap-3" style={{ alignItems: 'center' }}>
            <div style={{ width: 44, height: 44, borderRadius: 8, background: 'var(--navy)', color: '#fff', display: 'grid', placeItems: 'center', fontSize: 14, fontWeight: 600 }}>{cp.short.slice(0,3)}</div>
            <div>
              <h1 className="page-title" style={{ margin: 0 }}>{cp.name}</h1>
              <div className="row gap-2" style={{ marginTop: 4 }}>
                <Badge kind={cp.rating.startsWith('AA')?'pos':'neutral'}>{cp.rating}</Badge>
                <StatePill state={cp.status}/>
                <Badge kind="neutral">{cp.short}</Badge>
                <span style={{ fontSize: 11.5, color: 'var(--muted)' }}>· Banco BR · São Paulo · BRA</span>
              </div>
            </div>
          </div>
        </div>
        <div className="page-actions">
          <button className="btn btn-secondary">Editar</button>
          <button className="btn btn-secondary">Histórico KYC</button>
          <button className="btn btn-primary" onClick={() => (window.location.hash = '#/rfq/new')}><Icon.Plus/>Nova RFQ</button>
        </div>
      </div>

      <div className="kpi-row cols-4" style={{ marginBottom: 16 }}>
        <KPI label="Limite de crédito" value={`US$ ${(cp.limit/1000000).toFixed(1)}`} unit="M" delta="aprovado 18/03/2026"/>
        <KPI label="Utilização" value={`${usePct.toFixed(0)}`} unit="%" delta={`US$ ${(cp.used/1000000).toFixed(1)} M em uso`} deltaKind={usePct>80?'neg':usePct>60?'flat':'pos'}/>
        <KPI label="Contratos ativos" value={String(contracts.length)} delta={`Notional US$ ${(cp.used/1000000).toFixed(1)} M`}/>
        <KPI label="MTM (USD)" value={(mtm>=0?'+':'')+mtm.toLocaleString('en-US', { maximumFractionDigits: 0 })} delta="marcação 11:30 BST" deltaKind={mtm>=0?'pos':'neg'}/>
      </div>

      <div className="tabs">
        {[['resumo','Resumo'],['contratos','Contratos ('+contracts.length+')'],['limites','Limites & KYC'],['atividade','Atividade']].map(([k,l])=>(
          <button key={k} className={'tab ' + (tab===k?'active':'')} onClick={()=>setTab(k)}>{l}</button>
        ))}
      </div>

      {tab === 'resumo' && (
        <div className="detail-grid">
          <div className="stack gap-4">
            <Card title="Identificação">
              <dl className="kv" style={{ gridTemplateColumns: '160px 1fr 160px 1fr' }}>
                <dt>Razão social</dt><dd>{cp.name} S.A.</dd>
                <dt>Tax ID (CNPJ)</dt><dd className="mono">17.298.092/0001-30</dd>
                <dt>Tipo</dt><dd>Banco BR</dd>
                <dt>País</dt><dd>BRA</dd>
                <dt>Cidade</dt><dd>São Paulo</dd>
                <dt>Endereço</dt><dd>Av. Brigadeiro Faria Lima, 3500</dd>
                <dt>Cadastro</dt><dd>18/03/2026</dd>
                <dt>Última operação</dt><dd>27/05/2026 09:14</dd>
              </dl>
            </Card>

            <Card title="Contato">
              <dl className="kv">
                <dt>Mesa</dt><dd>Mesa de Commodities</dd>
                <dt>Contato principal</dt><dd>Maria Santos · trader@{cp.short.toLowerCase()}.com.br</dd>
                <dt>Telefone</dt><dd>+55 11 3000-0000</dd>
                <dt>WhatsApp</dt><dd>+55 11 99999-0000</dd>
                <dt>Canal RFQ</dt><dd><Badge kind="pos" dot>Email + WhatsApp</Badge></dd>
              </dl>
            </Card>

            <Card title="Operações recentes" noPad>
              <table className="tbl tbl-tight">
                <thead><tr><th>Quando</th><th>Tipo</th><th>Entidade</th><th className="num">Volume</th><th>Status</th></tr></thead>
                <tbody>
                  <tr><td>27/05 09:14</td><td>RFQ</td><td className="mono">RFQ-2026-0184</td><td className="num">1.200 MT</td><td><StatePill state="QUOTED"/></td></tr>
                  <tr><td>27/05 09:04</td><td>Ordem</td><td className="mono">ORD-2026-0419</td><td className="num">1.500 MT</td><td><StatePill state="filled"/></td></tr>
                  <tr><td>26/05 13:02</td><td>Ordem</td><td className="mono">ORD-2026-0415</td><td className="num">700 MT</td><td><StatePill state="filled"/></td></tr>
                  <tr><td>25/05 11:18</td><td>RFQ</td><td className="mono">RFQ-2026-0167</td><td className="num">2.000 MT</td><td><StatePill state="QUOTED"/></td></tr>
                </tbody>
              </table>
            </Card>
          </div>

          <div className="stack gap-4">
            <Card title="Utilização do limite">
              <div className="row gap-3" style={{ alignItems: 'center', marginBottom: 14 }}>
                <div className="donut" style={{ background: `conic-gradient(var(--navy) 0% ${usePct}%, var(--surface-sunk) ${usePct}% 100%)` }}>
                  <div className="donut-label">
                    <div>
                      <div className="v">{usePct.toFixed(0)}%</div>
                      <div className="l">utilizado</div>
                    </div>
                  </div>
                </div>
                <div style={{ flex: 1 }}>
                  <dl className="kv">
                    <dt>Limite</dt><dd className="tabular">US$ {(cp.limit/1000000).toFixed(1)} M</dd>
                    <dt>Em uso</dt><dd className="tabular strong">US$ {(cp.used/1000000).toFixed(1)} M</dd>
                    <dt>Disponível</dt><dd className="tabular" style={{ color: 'var(--pos)' }}>US$ {((cp.limit-cp.used)/1000000).toFixed(1)} M</dd>
                  </dl>
                </div>
              </div>
              <div className="divider" style={{ margin: '6px 0 12px' }}/>
              <div className="section-title" style={{ marginBottom: 8 }}>Concentração por commodity</div>
              <div className="stack gap-2">
                <div className="row gap-3"><span style={{ width: 80, fontSize: 12 }}>AL-LME</span><Bar pct={72} kind="pos"/><span className="tabular" style={{ width: 40, textAlign: 'right', fontSize: 11 }}>72%</span></div>
                <div className="row gap-3"><span style={{ width: 80, fontSize: 12 }}>USDBRL</span><Bar pct={21} kind="pos"/><span className="tabular" style={{ width: 40, textAlign: 'right', fontSize: 11 }}>21%</span></div>
                <div className="row gap-3"><span style={{ width: 80, fontSize: 12 }}>CU-LME</span><Bar pct={7} kind="pos"/><span className="tabular" style={{ width: 40, textAlign: 'right', fontSize: 11 }}>7%</span></div>
              </div>
            </Card>

            <Card title="Compliance">
              <dl className="kv">
                <dt>KYC</dt><dd><Badge kind="pos" dot>Aprovado</Badge> <span style={{ color: 'var(--muted)', fontSize: 11 }}>· renova em 12/09/2026</span></dd>
                <dt>Sanctions</dt><dd><Badge kind="pos" dot>Clear</Badge> <span style={{ color: 'var(--muted)', fontSize: 11 }}>· última varredura 25/05</span></dd>
                <dt>Rating externo</dt><dd>S&P {cp.rating} · Moody's Aa3</dd>
                <dt>Política IFRS</dt><dd>Aprovado para hedge accounting</dd>
              </dl>
            </Card>
          </div>
        </div>
      )}

      {tab === 'contratos' && (
        <Card title="Contratos ativos" sub={`${contracts.length} contratos · notional total US$ ${(cp.used/1000000).toFixed(1)} M`} noPad>
          <table className="tbl">
            <thead><tr>
              <th>Contrato</th><th>Commodity</th><th>Tipo</th><th className="num">Qtd</th><th className="num">Preço</th><th>Vencimento</th><th className="num">MTM (USD)</th><th>Status</th>
            </tr></thead>
            <tbody>
              {contracts.length ? contracts.map(c => (
                <tr key={c.id} onClick={()=>window.location.hash = `#/contracts/${c.id}`} style={{ cursor: 'pointer' }}>
                  <td className="mono strong">{c.id}</td>
                  <td><CommodityChip code={c.commodity}/></td>
                  <td>{c.type}</td>
                  <td className="num">{c.commodity==='USDBRL'?'US$ '+(c.qty/1000000).toFixed(1)+' M':c.qty.toLocaleString('pt-BR')+' t'}</td>
                  <td className="num">{c.price.toLocaleString('en-US', { minimumFractionDigits: c.commodity==='USDBRL'?4:2, maximumFractionDigits: c.commodity==='USDBRL'?4:2 })}</td>
                  <td>{c.settle.split('-').reverse().join('/')}</td>
                  <td className="num strong" style={{ color: c.mtm>=0?'var(--pos)':'var(--neg)' }}>{c.mtm>=0?'+':''}{c.mtm.toLocaleString('en-US', { maximumFractionDigits: 0 })}</td>
                  <td><StatePill state={c.status}/></td>
                </tr>
              )) : <tr><td colSpan={8} className="tbl-empty">Nenhum contrato ativo com esta contraparte</td></tr>}
            </tbody>
          </table>
        </Card>
      )}

      {tab === 'limites' && (
        <div className="grid-2">
          <Card title="Histórico de limites" noPad>
            <table className="tbl tbl-tight">
              <thead><tr><th>Data</th><th className="num">Limite</th><th className="num">Δ</th><th>Aprovador</th></tr></thead>
              <tbody>
                <tr><td>18/03/2026</td><td className="num tabular strong">{(cp.limit/1000000).toFixed(1)} M</td><td className="num" style={{ color: 'var(--pos)' }}>+2,0 M</td><td>Comitê de Risco</td></tr>
                <tr><td>15/09/2025</td><td className="num tabular">{((cp.limit-2000000)/1000000).toFixed(1)} M</td><td className="num">—</td><td>Comitê de Risco</td></tr>
                <tr><td>22/03/2025</td><td className="num tabular">{((cp.limit-4000000)/1000000).toFixed(1)} M</td><td className="num" style={{ color: 'var(--pos)' }}>+1,5 M</td><td>Comitê de Risco</td></tr>
                <tr><td>10/09/2024</td><td className="num tabular">{((cp.limit-5500000)/1000000).toFixed(1)} M</td><td className="num">Inicial</td><td>Comitê de Risco</td></tr>
              </tbody>
            </table>
          </Card>

          <Card title="Trilha KYC">
            <div className="feed">
              <FeedItem kind="pos" when="12/03/2026" who="L. Ferreira" what={<>KYC renovado · documentação atualizada</>}/>
              <FeedItem kind="pos" when="25/05/2026" who="Sistema" what={<>Sanctions screening · clear (OFAC, Bacen, EU)</>}/>
              <FeedItem kind="info" when="18/03/2026" who="Comitê de Risco" what={<>Limite ampliado de US$ 10 M → US$ 12 M</>}/>
              <FeedItem kind="info" when="15/09/2025" who="A. Costa" what={<>Revisão semestral concluída · sem restrições</>}/>
              <FeedItem kind="pos" when="10/09/2024" who="Comitê de Risco" what={<>Habilitação inicial para operar RFQs</>}/>
            </div>
          </Card>
        </div>
      )}

      {tab === 'atividade' && (
        <Card title="Linha do tempo">
          <div className="feed">
            <FeedItem kind="pos" when="hoje 09:14" who="M. Santos" what={<>RFQ <strong>RFQ-2026-0184</strong> enviada · AL-LME 1.200t buy</>}/>
            <FeedItem kind="pos" when="hoje 09:04" who="R. Almeida" what={<>Ordem <strong>ORD-2026-0419</strong> liquidada · 1.500t @ 2.631,00</>}/>
            <FeedItem kind="info" when="ontem 17:55" who="A. Costa" what={<>Contrato CT-2026-0118 aprovado</>}/>
            <FeedItem kind="pos" when="ontem 13:02" who="R. Almeida" what={<>Ordem ORD-2026-0415 liquidada · 700t</>}/>
            <FeedItem kind="info" when="25/05" who="Sistema" what={<>Sanctions screening · clear</>}/>
            <FeedItem kind="warn" when="22/05" who="L. Ferreira" what={<>Limite revisado preventivamente · sem alteração</>}/>
            <FeedItem kind="info" when="20/05" who="M. Santos" what={<>RFQ RFQ-2026-0145 cancelada</>}/>
          </div>
        </Card>
      )}
    </div>
  );
}

// ============================================================
// CONTRACT DETAIL
// ============================================================
function ContractDetailPage({ id }) {
  const c = M.contracts.find(x => x.id === id) || M.contracts[0];
  const [tab, setTab] = React.useState('resumo');
  const mid = c.commodity==='AL-LME'?2645.50:c.commodity==='CU-LME'?9412.00:c.commodity==='ZN-LME'?2812.50:c.commodity==='USDBRL'?5.1240:c.price;
  const settleDate = new Date(c.settle);
  const today = new Date(2026, 4, 27);
  const daysToSettle = Math.round((settleDate - today) / 86400000);
  const notional = c.qty * c.price;

  return (
    <div className="page">
      <div className="page-head">
        <div style={{ flex: 1 }}>
          <div className="row gap-2" style={{ marginBottom: 4 }}>
            <button className="btn btn-link" onClick={() => (window.location.hash = '#/contracts')}><Icon.ArrowLeft/> Contratos</button>
            <span style={{ color: 'var(--muted)' }}>/</span>
            <span className="mono" style={{ fontSize: 12, color: 'var(--muted)' }}>{c.id}</span>
          </div>
          <div className="row gap-3" style={{ alignItems: 'baseline' }}>
            <h1 className="page-title" style={{ margin: 0 }}>{c.id}</h1>
            <Badge kind="neutral">{c.type}</Badge>
            <CommodityChip code={c.commodity}/>
            <StatePill state={c.status}/>
            {daysToSettle <= 7 && daysToSettle >= 0 && <Badge kind="warn" dot>Vence em {daysToSettle}d</Badge>}
          </div>
          <div className="page-sub" style={{ marginTop: 6 }}>
            {c.fixed_leg==='buy'?'Compra':'Venda'} fixa × {c.var_leg==='buy'?'Compra':'Venda'} variável · {c.qty.toLocaleString('pt-BR')} {c.commodity==='USDBRL'?'USD':'MT'} · {c.cp} · liquidação {c.settle.split('-').reverse().join('/')}
          </div>
        </div>
        <div className="page-actions">
          <button className="btn btn-secondary"><Icon.Download/>Confirmação</button>
          <button className="btn btn-secondary">Histórico MTM</button>
          {c.status === 'active' && <button className="btn btn-danger">Unwinding</button>}
          {c.status === 'maturing' && <button className="btn btn-accent">Iniciar liquidação</button>}
        </div>
      </div>

      <div className="kpi-row cols-4" style={{ marginBottom: 16 }}>
        <KPI label="Notional" value={`US$ ${(notional/1000000).toFixed(2)}`} unit="M" delta={c.qty.toLocaleString('pt-BR')+' '+(c.commodity==='USDBRL'?'USD':'MT')+' @ '+c.price}/>
        <KPI label="MTM atual" value={(c.mtm>=0?'+US$ ':'−US$ ')+Math.abs(c.mtm).toLocaleString('en-US', { maximumFractionDigits: 0 })} delta="+US$ 1.420 1d" deltaKind={c.mtm>=0?'pos':'neg'}/>
        <KPI label="P&L desde a contratação" value={(c.mtm>=0?'+':'')+((c.mtm/notional)*100).toFixed(2)+' %'} delta={'preço mid '+mid.toFixed(2)} deltaKind={c.mtm>=0?'pos':'neg'}/>
        <KPI label="Dias até liquidação" value={String(daysToSettle)} unit="d" delta={c.settle.split('-').reverse().join('/')} deltaKind={daysToSettle<=7?'neg':'flat'}/>
      </div>

      <div className="tabs">
        {[['resumo','Resumo'],['legs','Pernas'],['cashflow','Cash flows'],['mtm','Histórico MTM'],['docs','Documentos']].map(([k,l])=>(
          <button key={k} className={'tab ' + (tab===k?'active':'')} onClick={()=>setTab(k)}>{l}</button>
        ))}
      </div>

      {tab === 'resumo' && (
        <div className="detail-grid">
          <div className="stack gap-4">
            <Card title="Termos do contrato">
              <dl className="kv" style={{ gridTemplateColumns: '180px 1fr 180px 1fr' }}>
                <dt>Tipo</dt><dd>{c.type}</dd>
                <dt>Commodity</dt><dd>{c.commodity}</dd>
                <dt>Quantidade</dt><dd className="tabular">{c.qty.toLocaleString('pt-BR')} {c.commodity==='USDBRL'?'USD':'MT'}</dd>
                <dt>Notional</dt><dd className="tabular">US$ {notional.toLocaleString('en-US', { maximumFractionDigits: 0 })}</dd>
                <dt>Preço fixo</dt><dd className="tabular strong">{c.price.toLocaleString('en-US', { minimumFractionDigits: c.commodity==='USDBRL'?4:2 })} USD/{c.commodity==='USDBRL'?'BRL':'MT'}</dd>
                <dt>Preço variável</dt><dd>LME Average · mês de liquidação</dd>
                <dt>Contratação</dt><dd>26/05/2026 09:02</dd>
                <dt>Liquidação</dt><dd>{c.settle.split('-').reverse().join('/')} ({daysToSettle}d)</dd>
                <dt>Contraparte</dt><dd><a href={`#/counterparties/${c.cp}`}>{M.counterparties.find(x=>x.short===c.cp)?.name || c.cp}</a></dd>
                <dt>RFQ origem</dt><dd className="mono"><a href="#/rfq/RFQ-2026-0177">RFQ-2026-0177</a></dd>
                <dt>Política contábil</dt><dd>Hedge accounting (IFRS 9)</dd>
                <dt>Margem inicial</dt><dd className="tabular">US$ {(notional*0.1).toLocaleString('en-US', { maximumFractionDigits: 0 })} (10%)</dd>
              </dl>
            </Card>

            <Card title="Pernas do swap" sub="Visualização do payoff">
              <div className="grid-2">
                <div className="card" style={{ padding: 16, background: c.fixed_leg==='buy'?'var(--pos-soft)':'var(--neg-soft)' }}>
                  <div className="row gap-2" style={{ marginBottom: 10 }}>
                    <Badge kind={c.fixed_leg==='buy'?'pos':'neg'}>{c.fixed_leg==='buy'?'COMPRA':'VENDA'} FIXA</Badge>
                    <span style={{ marginLeft: 'auto', fontSize: 11, color: 'var(--muted)' }}>Leg 1</span>
                  </div>
                  <div style={{ fontSize: 11, color: 'var(--muted)', textTransform: 'uppercase', letterSpacing: '0.05em', marginBottom: 4 }}>Preço fixo</div>
                  <div style={{ fontSize: 22, fontWeight: 600, fontVariantNumeric: 'tabular-nums' }}>{c.price.toLocaleString('en-US', { minimumFractionDigits: c.commodity==='USDBRL'?4:2 })}</div>
                  <div style={{ fontSize: 11.5, color: 'var(--muted)', marginTop: 6 }}>USD/{c.commodity==='USDBRL'?'BRL':'MT'} · contratual</div>
                </div>
                <div className="card" style={{ padding: 16, background: c.var_leg==='buy'?'var(--pos-soft)':'var(--neg-soft)' }}>
                  <div className="row gap-2" style={{ marginBottom: 10 }}>
                    <Badge kind={c.var_leg==='buy'?'pos':'neg'}>{c.var_leg==='buy'?'COMPRA':'VENDA'} VARIÁVEL</Badge>
                    <span style={{ marginLeft: 'auto', fontSize: 11, color: 'var(--muted)' }}>Leg 2</span>
                  </div>
                  <div style={{ fontSize: 11, color: 'var(--muted)', textTransform: 'uppercase', letterSpacing: '0.05em', marginBottom: 4 }}>Preço mid de mercado</div>
                  <div style={{ fontSize: 22, fontWeight: 600, fontVariantNumeric: 'tabular-nums' }}>{mid.toLocaleString('en-US', { minimumFractionDigits: c.commodity==='USDBRL'?4:2 })}</div>
                  <div style={{ fontSize: 11.5, color: 'var(--muted)', marginTop: 6 }}>USD/{c.commodity==='USDBRL'?'BRL':'MT'} · LME 11:30 BST</div>
                </div>
              </div>
              <div className="divider"/>
              <div className="row gap-3" style={{ alignItems: 'baseline' }}>
                <span style={{ fontSize: 12, color: 'var(--muted)' }}>Δ Preço:</span>
                <span className="tabular" style={{ fontSize: 14, fontWeight: 500, color: mid>c.price?'var(--pos)':'var(--neg)' }}>{mid>=c.price?'+':''}{(mid-c.price).toFixed(c.commodity==='USDBRL'?4:2)}</span>
                <span style={{ fontSize: 12, color: 'var(--muted)' }}>·</span>
                <span style={{ fontSize: 12, color: 'var(--muted)' }}>MTM:</span>
                <span className="tabular strong" style={{ fontSize: 14, color: c.mtm>=0?'var(--pos)':'var(--neg)' }}>{c.mtm>=0?'+':''}US$ {c.mtm.toLocaleString('en-US', { maximumFractionDigits: 0 })}</span>
              </div>
            </Card>
          </div>

          <div className="stack gap-4">
            <Card title="Cronograma">
              <div className="feed">
                <FeedItem kind="pos" when="26/05 09:02" who="R. Almeida" what={<>Contrato assinado · ORD-2026-0419 ↘ <strong>{c.id}</strong></>}/>
                <FeedItem kind="pos" when="26/05 13:45" who="A. Costa" what={<>Aprovação concedida · APR-2026-0096</>}/>
                <FeedItem kind="info" when="27/05 09:14" who="Sistema" what={<>MTM atualizado · +US$ 1.420</>}/>
                <FeedItem kind="info" when={c.settle.split('-').reverse().join('/')} who="Agendado" what={<>Liquidação financeira · {c.cp}</>}/>
              </div>
            </Card>

            <Card title="Documentação">
              <div className="stack gap-2">
                <DocLink name="Confirmação ISDA" size="142 KB"/>
                <DocLink name="Term sheet" size="86 KB"/>
                <DocLink name="Anexo de garantia" size="48 KB"/>
                <DocLink name="Marcação MTM diária" size="2,1 MB"/>
              </div>
            </Card>

            <Card title="Aprovação">
              <dl className="kv">
                <dt>Status</dt><dd><Badge kind="pos" dot>Concedida</Badge></dd>
                <dt>ID</dt><dd className="mono">APR-2026-0096</dd>
                <dt>Aprovador</dt><dd>A. Costa · Risco</dd>
                <dt>Em</dt><dd>26/05 13:45</dd>
                <dt>Política</dt><dd>Hedge §4.1 · Notional ≤ US$ 5 M</dd>
              </dl>
            </Card>
          </div>
        </div>
      )}

      {tab === 'legs' && (
        <Card title="Detalhes das pernas">
          <table className="tbl">
            <thead><tr><th>Leg</th><th>Side</th><th>Price type</th><th className="num">Quantidade</th><th className="num">Preço</th><th>Janela / Fixing</th><th>Convenção</th></tr></thead>
            <tbody>
              <tr><td className="strong">Leg 1</td><td><DirectionBadge dir={c.fixed_leg}/></td><td><Badge kind="info">Fix</Badge></td><td className="num">{c.qty.toLocaleString('pt-BR')} MT</td><td className="num strong">{c.price.toLocaleString('en-US', { minimumFractionDigits: 2 })}</td><td>{c.settle.split('-').reverse().join('/')} · fixing</td><td>LME Official Settlement</td></tr>
              <tr><td className="strong">Leg 2</td><td><DirectionBadge dir={c.var_leg}/></td><td><Badge kind="neutral">AVG</Badge></td><td className="num">{c.qty.toLocaleString('pt-BR')} MT</td><td className="num">média {c.settle.slice(5,7)}/{c.settle.slice(2,4)}</td><td>{c.settle.split('-')[0]}-{c.settle.slice(5,7)} · mês completo</td><td>LME Average Month</td></tr>
            </tbody>
          </table>
        </Card>
      )}

      {tab === 'cashflow' && (
        <Card title="Cash flows projetados" noPad>
          <table className="tbl">
            <thead><tr><th>Data</th><th>Descrição</th><th className="num">Valor (USD)</th><th>Direção</th><th>Status</th></tr></thead>
            <tbody>
              <tr><td>{c.settle.split('-').reverse().join('/')}</td><td>Liquidação principal · {c.id}</td><td className="num strong" style={{ color: c.mtm>=0?'var(--pos)':'var(--neg)' }}>{c.mtm>=0?'+':''}{c.mtm.toLocaleString('en-US', { maximumFractionDigits: 0 })}</td><td>{c.mtm>=0?<Badge kind="pos" dot>Entrada</Badge>:<Badge kind="neg" dot>Saída</Badge>}</td><td><StatePill state="projected"/></td></tr>
              <tr><td>15/06/2026</td><td>Margin call (estimado · 30 % do MTM)</td><td className="num">US$ {(Math.abs(c.mtm)*0.3).toLocaleString('en-US', { maximumFractionDigits: 0 })}</td><td><Badge kind="info" dot>Garantia</Badge></td><td><StatePill state="projected"/></td></tr>
              <tr><td>27/05/2026</td><td>Pagamento de margem inicial</td><td className="num">US$ {(notional*0.1).toLocaleString('en-US', { maximumFractionDigits: 0 })}</td><td><Badge kind="info" dot>Garantia</Badge></td><td><StatePill state="confirmed"/></td></tr>
            </tbody>
          </table>
        </Card>
      )}

      {tab === 'mtm' && (
        <Card title="Histórico de marcação" sub="Últimos 30 dias">
          <MTMSparkline mtm={c.mtm}/>
          <table className="tbl tbl-tight" style={{ marginTop: 16 }}>
            <thead><tr><th>Data</th><th className="num">Preço mid</th><th className="num">MTM (USD)</th><th className="num">Δ Dia</th></tr></thead>
            <tbody>
              {[
                ['27/05', mid, c.mtm, 1420],
                ['26/05', mid - 0.5, c.mtm - 1420, -240],
                ['25/05', mid - 0.3, c.mtm - 1180, 820],
                ['22/05', mid - 1.8, c.mtm - 2000, 1100],
                ['21/05', mid - 2.5, c.mtm - 3100, -560],
              ].map(([d, p, m, dDay], i) => (
                <tr key={i}>
                  <td>{d}</td>
                  <td className="num tabular">{p.toFixed(c.commodity==='USDBRL'?4:2)}</td>
                  <td className="num tabular strong" style={{ color: m>=0?'var(--pos)':'var(--neg)' }}>{m>=0?'+':''}{m.toLocaleString('en-US', { maximumFractionDigits: 0 })}</td>
                  <td className="num tabular" style={{ color: dDay>=0?'var(--pos)':'var(--neg)' }}>{dDay>=0?'+':''}{dDay.toLocaleString('en-US')}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </Card>
      )}

      {tab === 'docs' && (
        <div className="grid-2">
          <Card title="Documentos do contrato">
            <div className="stack gap-2">
              <DocLink name="Confirmação ISDA · assinada"  size="142 KB"/>
              <DocLink name="Term sheet"                   size="86 KB"/>
              <DocLink name="Anexo de garantia"            size="48 KB"/>
              <DocLink name="Documentação hedge accounting" size="218 KB"/>
              <DocLink name="Trilha de aprovação"          size="32 KB"/>
            </div>
          </Card>
          <Card title="Histórico de versões">
            <div className="feed">
              <FeedItem kind="pos" when="26/05 13:45" who="A. Costa" what={<>Versão final aprovada · v3</>}/>
              <FeedItem kind="info" when="26/05 11:20" who="R. Almeida" what={<>Ajuste no anexo de garantia · v2</>}/>
              <FeedItem kind="info" when="26/05 09:02" who="R. Almeida" what={<>Confirmação inicial gerada · v1</>}/>
            </div>
          </Card>
        </div>
      )}
    </div>
  );
}

function MTMSparkline({ mtm }) {
  // simple inline 30-day sparkline rendered in pure SVG
  const points = Array.from({ length: 30 }, (_, i) => {
    const noise = Math.sin(i * 0.5) * (Math.abs(mtm) * 0.3) + (i / 29) * mtm;
    return noise;
  });
  const min = Math.min(...points);
  const max = Math.max(...points);
  const range = max - min || 1;
  const w = 720;
  const h = 120;
  const step = w / (points.length - 1);
  const path = points.map((p, i) => `${i*step},${h - ((p - min) / range) * (h - 4) - 2}`).join(' L ');
  const zeroY = h - ((0 - min) / range) * (h - 4) - 2;
  return (
    <svg width="100%" height={h} viewBox={`0 0 ${w} ${h}`} preserveAspectRatio="none">
      <line x1="0" y1={zeroY} x2={w} y2={zeroY} stroke="var(--line)" strokeDasharray="2,3"/>
      <path d={`M ${path}`} fill="none" stroke={mtm>=0?'var(--pos)':'var(--neg)'} strokeWidth="1.8"/>
      <path d={`M 0,${zeroY} L ${path} L ${w},${zeroY} Z`} fill={mtm>=0?'var(--pos-soft)':'var(--neg-soft)'} opacity="0.6"/>
    </svg>
  );
}

Object.assign(window, { OrderNewPage, CounterpartyNewPage, CounterpartyDetailPage, ContractDetailPage });
})();
