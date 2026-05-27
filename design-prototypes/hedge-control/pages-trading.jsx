/* Trading pages: Orders, RFQ list/new/detail, Contracts, Counterparties */

const M = window.MOCK;

// ============================================================
// ORDERS
// ============================================================
function OrdersPage() {
  const [tab, setTab] = React.useState('all');
  const [dir, setDir] = React.useState('all');
  return (
    <div className="page">
      <div className="page-head">
        <div>
          <h1 className="page-title">Ordens</h1>
          <div className="page-sub">Execução de hedges e fechamento com contrapartes</div>
        </div>
        <div className="page-actions">
          <button className="btn btn-secondary"><Icon.Download/>Exportar</button>
          <button className="btn btn-primary" onClick={() => (window.location.hash = '#/orders/new')}><Icon.Plus/>Nova ordem</button>
        </div>
      </div>

      <div className="kpi-row cols-4" style={{ marginBottom: 16 }}>
        <KPI label="Ordens hoje" value="24" delta="+4 vs ontem" deltaKind="pos"/>
        <KPI label="Volume D" value="US$ 24,1 M" delta="+US$ 3,2 M vs ontem" deltaKind="pos"/>
        <KPI label="Preço médio AL" value="2.632,15" unit="USD/t" delta="vs mid 2.635,00 LME" deltaKind="pos"/>
        <KPI label="Slippage médio" value="−0,11" unit="%" delta="dentro do limite −0,25%" deltaKind="pos"/>
      </div>

      <Card noPad>
        <div className="tbl-tools">
          <div className="tabs-pill">
            {[
              ['all', 'Todas', 47],
              ['filled', 'Liquidadas', 38],
              ['partial', 'Parciais', 3],
              ['pending', 'Pendentes', 4],
              ['cancelled', 'Canceladas', 2],
            ].map(([k, l, c]) => (
              <button key={k} className={"tab " + (tab===k?'active':'')} onClick={()=>setTab(k)}>{l} <span style={{ color: 'var(--muted-2)', marginLeft: 4 }}>{c}</span></button>
            ))}
          </div>
          <div className="sp"/>
          <div className="radio-group">
            <button className={dir==='all'?'active':''} onClick={()=>setDir('all')}>Todas</button>
            <button className={dir==='buy'?'active buy':''} onClick={()=>setDir('buy')}>Compra</button>
            <button className={dir==='sell'?'active sell':''} onClick={()=>setDir('sell')}>Venda</button>
          </div>
          <button className="chip"><Icon.Filter/>Commodity</button>
          <button className="chip"><Icon.Filter/>Contraparte</button>
          <button className="chip"><Icon.Filter/>Período</button>
        </div>

        <table className="tbl">
          <thead><tr>
            <th>Ordem</th>
            <th>RFQ</th>
            <th>Commodity</th>
            <th>Lado</th>
            <th className="num">Quantidade</th>
            <th className="num">Preço (USD)</th>
            <th>Contraparte</th>
            <th>Liquidação</th>
            <th>Status</th>
            <th></th>
          </tr></thead>
          <tbody>
            {M.orders.map(o => (
              <tr key={o.id} onClick={() => (window.location.hash = `#/orders/${o.id}`)} style={{ cursor: 'pointer' }}>
                <td className="strong mono">{o.id}</td>
                <td className="mono"><a href={`#/rfq/${o.rfq}`} onClick={e=>e.stopPropagation()}>{o.rfq}</a></td>
                <td><CommodityChip code={o.commodity}/></td>
                <td><DirectionBadge dir={o.direction}/></td>
                <td className="num">{o.commodity === 'USDBRL' ? 'US$ ' + (o.qty/1000000).toFixed(1) + ' M' : o.qty.toLocaleString('pt-BR') + ' t'}</td>
                <td className="num strong">{o.price.toLocaleString('en-US', { minimumFractionDigits: o.commodity==='USDBRL'?4:2, maximumFractionDigits: o.commodity==='USDBRL'?4:2 })}</td>
                <td>{o.cp}</td>
                <td>{o.settlement ? o.settlement.split('-').reverse().join('/') : '—'}</td>
                <td><StatePill state={o.status}/></td>
                <td><button className="btn btn-ghost btn-sm"><Icon.ChevronRight/></button></td>
              </tr>
            ))}
          </tbody>
        </table>
        <Pager from={1} to={8} total={47}/>
      </Card>
    </div>
  );
}

// ============================================================
// RFQ LIST
// ============================================================
function RFQListPage() {
  const [tab, setTab] = React.useState('all');
  return (
    <div className="page">
      <div className="page-head">
        <div>
          <h1 className="page-title">RFQ · Solicitações de cotação</h1>
          <div className="page-sub">Originar cotações com contrapartes e converter em ordens</div>
        </div>
        <div className="page-actions">
          <button className="btn btn-secondary"><Icon.Download/>Exportar</button>
          <button className="btn btn-primary" onClick={() => (window.location.hash = '#/rfq/new')}><Icon.Plus/>Nova RFQ</button>
        </div>
      </div>

      <div className="kpi-row cols-4" style={{ marginBottom: 16 }}>
        <KPI label="RFQ abertas" value="3" delta="2 aguardando cotação" deltaKind="flat"/>
        <KPI label="Tempo médio à cotação" value="00:18" unit="min" delta="−00:02 vs semana" deltaKind="pos"/>
        <KPI label="Hit ratio (mês)" value="68,4" unit="%" delta="+3,2 pp" deltaKind="pos"/>
        <KPI label="Volume em cotação" value="US$ 4,9 M" delta="3 commodities"/>
      </div>

      <Card noPad>
        <div className="tbl-tools">
          <div className="tabs-pill">
            {[['all','Todas',184],['CREATED','Criadas',1],['SENT','Enviadas',2],['QUOTED','Cotadas',4]].map(([k,l,c]) => (
              <button key={k} className={"tab " + (tab===k?'active':'')} onClick={()=>setTab(k)}>{l} <span style={{ color: 'var(--muted-2)', marginLeft: 4 }}>{c}</span></button>
            ))}
          </div>
          <div className="sp"/>
          <button className="chip"><Icon.Filter/>Commodity</button>
          <button className="chip"><Icon.Filter/>Intenção</button>
          <button className="chip"><Icon.Filter/>Período</button>
        </div>

        <table className="tbl">
          <thead><tr>
            <th>RFQ</th>
            <th>Intenção</th>
            <th>Commodity</th>
            <th>Lado</th>
            <th className="num">Quantidade</th>
            <th>Janela</th>
            <th className="num">Cotações</th>
            <th className="num">Melhor</th>
            <th>Status</th>
            <th>Criada</th>
            <th></th>
          </tr></thead>
          <tbody>
            {M.rfqs.map(r => (
              <tr key={r.id} onClick={() => (window.location.hash = `#/rfq/${r.id}`)} style={{ cursor: 'pointer' }}>
                <td className="strong mono">{r.id}</td>
                <td><Badge kind={r.intent==='COMMERCIAL_HEDGE'?'info':'neutral'}>{r.intent==='COMMERCIAL_HEDGE'?'Hedge comercial':'Posição global'}</Badge></td>
                <td><CommodityChip code={r.commodity}/></td>
                <td><DirectionBadge dir={r.direction}/></td>
                <td className="num">{r.commodity==='USDBRL'?'US$ '+(r.qty/1000000).toFixed(1)+' M':r.qty.toLocaleString('pt-BR')+' t'}</td>
                <td>{r.window}</td>
                <td className="num">{r.quotes}</td>
                <td className="num strong">{r.best ? r.best.toLocaleString('en-US', { minimumFractionDigits: r.commodity==='USDBRL'?4:2, maximumFractionDigits: r.commodity==='USDBRL'?4:2 }) : '—'}</td>
                <td><StatePill state={r.state}/></td>
                <td style={{ color: 'var(--muted)', fontSize: 12 }}>{r.created}</td>
                <td><button className="btn btn-ghost btn-sm"><Icon.ChevronRight/></button></td>
              </tr>
            ))}
          </tbody>
        </table>
        <Pager from={1} to={7} total={184}/>
      </Card>
    </div>
  );
}

// ============================================================
// RFQ NEW — mirrors the real Svelte form structure
// ============================================================
const RFQ_MONTHS_PT = ['Janeiro','Fevereiro','Março','Abril','Maio','Junho','Julho','Agosto','Setembro','Outubro','Novembro','Dezembro'];
const RFQ_MONTHS_EN = ['January','February','March','April','May','June','July','August','September','October','November','December'];
const RFQ_PRICE_TYPES = [
  { value: 'AVG', label: 'AVG · média mensal' },
  { value: 'AVGInter', label: 'AVG Period · média de período' },
  { value: 'Fix', label: 'Fix · preço fixo' },
  { value: 'C2R', label: 'C2R · close-to-result' },
];
const RFQ_ORDER_TYPES = [
  { value: 'At Market', label: 'At Market (a mercado)' },
  { value: 'Limit', label: 'Limit (limitada)' },
  { value: 'Resting', label: 'Resting (em aberto)' },
];
const RFQ_VALIDITIES = ['Day','GTC','3 Hours','6 Hours','12 Hours','Until Further Notice'];

function emptyLeg(side) {
  return { side, priceType: '', monthName: RFQ_MONTHS_EN[4], year: 2026, startDate: '', endDate: '', fixingDate: '', fixingDateInherited: false, orderType: '', orderValidity: '', limitPrice: '' };
}

function RFQNewPage() {
  const [company, setCompany] = React.useState('Alcast Brasil');
  const [commodity, setCommodity] = React.useState('ALUMINIUM');
  const [intent, setIntent] = React.useState('GLOBAL_POSITION');
  const [tradeType, setTradeType] = React.useState('Swap');
  const [quantity, setQuantity] = React.useState('1200');
  const [orderId, setOrderId] = React.useState('');
  const [buyTradeId, setBuyTradeId] = React.useState('');
  const [sellTradeId, setSellTradeId] = React.useState('');
  const [leg1, setLeg1] = React.useState(emptyLeg('buy'));
  const [leg2, setLeg2] = React.useState(emptyLeg('sell'));
  const [cps, setCps] = React.useState(['ITAU','JPM','SANT','BTG']);
  const [cpSearch, setCpSearch] = React.useState('');
  const showLeg2 = tradeType === 'Swap';

  const toggleCP = (c) => setCps(s => s.includes(c) ? s.filter(x=>x!==c) : [...s, c]);

  const applyTemplate = (tpl) => {
    if (tpl === 'queda') { // Buy AVG + Sell Fix
      setLeg1({ ...emptyLeg('buy'), priceType: 'AVG' });
      setLeg2({ ...emptyLeg('sell'), priceType: 'Fix' });
    } else if (tpl === 'alta') { // Sell AVG + Buy Fix
      setLeg1({ ...emptyLeg('sell'), priceType: 'AVG' });
      setLeg2({ ...emptyLeg('buy'), priceType: 'Fix' });
    } else if (tpl === 'spread') { // Buy AVG + Sell AVG
      setLeg1({ ...emptyLeg('buy'), priceType: 'AVG' });
      setLeg2({ ...emptyLeg('sell'), priceType: 'AVG' });
    }
  };

  const setLegSide = (legKey, side) => {
    const opp = side === 'buy' ? 'sell' : 'buy';
    if (legKey === 'leg1') { setLeg1(l => ({ ...l, side })); setLeg2(l => ({ ...l, side: opp })); }
    else { setLeg2(l => ({ ...l, side })); setLeg1(l => ({ ...l, side: opp })); }
  };

  const direction = leg1.side === 'sell' ? 'SELL' : 'BUY';
  const cpList = M.counterparties.filter(cp => !cpSearch || cp.name.toLowerCase().includes(cpSearch.toLowerCase()) || cp.short.toLowerCase().includes(cpSearch.toLowerCase()));

  return (
    <div className="page">
      <div className="page-head">
        <div>
          <div className="row gap-2" style={{ marginBottom: 4 }}>
            <button className="btn btn-link" onClick={() => (window.location.hash = '#/rfq')}><Icon.ArrowLeft/> RFQ</button>
            <span style={{ color: 'var(--muted)' }}>/</span>
            <span style={{ fontSize: 12, color: 'var(--muted)' }}>Nova solicitação</span>
          </div>
          <h1 className="page-title">Nova RFQ</h1>
          <div className="page-sub">{company} · {commodity} · {tradeType} · <DirectionBadge dir={direction}/></div>
        </div>
        <div className="page-actions">
          <button className="btn btn-ghost" onClick={() => (window.location.hash = '#/rfq')}>Cancelar</button>
          <button className="btn btn-secondary">Pré-visualizar texto</button>
          <button className="btn btn-secondary">Salvar rascunho</button>
          <button className="btn btn-primary" disabled={cps.length===0 || !leg1.priceType}><Icon.Bolt/>Enviar a {cps.length} contraparte{cps.length===1?'':'s'}</button>
        </div>
      </div>

      <div className="detail-grid">
        <div className="stack gap-4">
          {/* SECTION 1 — TRADE SETUP */}
          <Card title="1. Trade setup" sub="Empresa, commodity, intenção e quantidade">
            <div className="field-grid">
              <div className="field" style={{ gridColumn: '1 / -1' }}>
                <label className="field-label">Empresa <span className="req">*</span></label>
                <div className="radio-group">
                  <button className={company==='Alcast Brasil'?'active':''} onClick={()=>setCompany('Alcast Brasil')}>Alcast Brasil</button>
                  <button className={company==='Alcast Trading'?'active':''} onClick={()=>setCompany('Alcast Trading')}>Alcast Trading</button>
                </div>
              </div>

              <div className="field">
                <label className="field-label">Commodity <span className="req">*</span></label>
                <select className="select" value={commodity} onChange={e=>setCommodity(e.target.value)}>
                  <option value="ALUMINIUM">ALUMINIUM</option>
                </select>
              </div>

              <div className="field">
                <label className="field-label">Intenção <span className="req">*</span> <InfoTip width={280}><strong>Posição global:</strong> tomada de posição direcional · sujeita a limites de risco.<br/><br/><strong>Hedge comercial:</strong> vinculada a uma ordem (PO/SO) · reduz exposição da janela.<br/><br/><strong>Spread:</strong> diferença entre duas RFQs (compra × venda).</InfoTip></label>
                <select className="select" value={intent} onChange={e=>setIntent(e.target.value)}>
                  <option value="GLOBAL_POSITION">Posição global</option>
                  <option value="COMMERCIAL_HEDGE">Hedge comercial</option>
                  <option value="SPREAD">Spread</option>
                </select>
              </div>

              <div className="field">
                <label className="field-label">Tipo de trade <span className="req">*</span></label>
                <div className="radio-group">
                  <button className={tradeType==='Swap'?'active':''} onClick={()=>setTradeType('Swap')}>Swap (2 legs)</button>
                  <button className={tradeType==='Forward'?'active':''} onClick={()=>setTradeType('Forward')}>Forward (1 leg)</button>
                </div>
              </div>

              <div className="field">
                <label className="field-label">Quantidade <span className="req">*</span> <InfoTip>Lote LME mínimo: 25 MT · padrão: 250 MT.</InfoTip></label>
                <div className="input-suffix">
                  <input className="input" value={quantity} onChange={e=>setQuantity(e.target.value)} type="number" step="0.001"/>
                  <span className="suffix">MT</span>
                </div>
              </div>

              {intent==='COMMERCIAL_HEDGE' && (
                <div className="field" style={{ gridColumn: '1 / -1' }}>
                  <label className="field-label">Ordem vinculada (PO / SO) <span className="req">*</span></label>
                  <select className="select" value={orderId} onChange={e=>setOrderId(e.target.value)}>
                    <option value="">— Selecione uma ordem comercial —</option>
                    <option value="PO-2026-1184">PO-2026-1184 · 1500 MT · jun/26</option>
                    <option value="PO-2026-1183">PO-2026-1183 · 800 MT · jul/26</option>
                    <option value="SO-2026-0942">SO-2026-0942 · 500 MT · jun/26</option>
                  </select>
                </div>
              )}

              {intent==='SPREAD' && (
                <React.Fragment>
                  <div className="field">
                    <label className="field-label">Buy Trade ID <span className="req">*</span></label>
                    <input className="input mono" value={buyTradeId} onChange={e=>setBuyTradeId(e.target.value)} placeholder="UUID da RFQ de compra"/>
                  </div>
                  <div className="field">
                    <label className="field-label">Sell Trade ID <span className="req">*</span></label>
                    <input className="input mono" value={sellTradeId} onChange={e=>setSellTradeId(e.target.value)} placeholder="UUID da RFQ de venda"/>
                  </div>
                </React.Fragment>
              )}
            </div>
          </Card>

          {/* SECTION 2 — TRADE LEGS */}
          <Card
            title="2. Trade 1"
            sub={showLeg2 ? 'Swap · configure duas pernas (compra fixa × venda variável ou inverso)' : 'Forward · configure uma única perna'}
            actions={
              <div className="row gap-2">
                <span style={{ fontSize: 11, color: 'var(--muted)' }}>Templates:</span>
                <button className="chip" onClick={()=>applyTemplate('queda')} style={{ color: 'var(--neg)', borderColor: 'var(--neg-soft)' }}>↓ Proteção de queda</button>
                <button className="chip" onClick={()=>applyTemplate('alta')} style={{ color: 'var(--pos)', borderColor: 'var(--pos-soft)' }}>↑ Proteção de alta</button>
                <button className="chip" onClick={()=>applyTemplate('spread')} style={{ color: 'var(--info)', borderColor: 'var(--info-soft)' }}>⇄ Spread</button>
              </div>
            }>
            <LegEditor legKey="leg1" leg={leg1} setLeg={setLeg1} setLegSide={setLegSide} label="Leg 1" />
            {showLeg2 && (
              <React.Fragment>
                <div className="divider"/>
                <LegEditor legKey="leg2" leg={leg2} setLeg={setLeg2} setLegSide={setLegSide} label="Leg 2"/>
              </React.Fragment>
            )}
          </Card>

          {/* SECTION 3 — CONTRAPARTES */}
          <Card title="3. Contrapartes" sub={`${cps.length} de ${M.counterparties.length} selecionadas · RFQ será enviada simultaneamente`}
            actions={
              <div className="input-suffix" style={{ width: 220 }}>
                <input className="input" placeholder="Buscar contraparte…" value={cpSearch} onChange={e=>setCpSearch(e.target.value)} style={{ height: 28 }}/>
              </div>
            }>
            <div style={{ display: 'grid', gridTemplateColumns: 'repeat(2, 1fr)', gap: 8 }}>
              {cpList.map(cp => {
                const on = cps.includes(cp.short);
                const usePct = (cp.used / cp.limit) * 100;
                const disabled = cp.status === 'review';
                return (
                  <button
                    key={cp.id}
                    disabled={disabled}
                    onClick={() => toggleCP(cp.short)}
                    className="card"
                    style={{ padding: 12, textAlign: 'left', cursor: disabled?'not-allowed':'pointer', borderColor: on?'var(--navy)':'var(--line-strong)', opacity: disabled?0.5:1, background: on?'#F4F7FC':'#fff' }}
                  >
                    <div className="row gap-3">
                      <span className={"check " + (on?'on':'')}><span className="box"/></span>
                      <div style={{ flex: 1 }}>
                        <div className="row gap-2" style={{ marginBottom: 2 }}>
                          <span style={{ fontWeight: 500, fontSize: 13 }}>{cp.name}</span>
                          <Badge kind="neutral">{cp.rating}</Badge>
                          {disabled && <Badge kind="warn" dot>Em análise</Badge>}
                        </div>
                        <div className="row gap-2" style={{ fontSize: 11, color: 'var(--muted)' }}>
                          <span>Limite</span>
                          <Bar pct={usePct} kind={usePct>80?'neg':usePct>60?'warn':'pos'}/>
                          <span className="tabular">US$ {(cp.used/1000000).toFixed(1)} / {(cp.limit/1000000).toFixed(1)} M</span>
                        </div>
                      </div>
                    </div>
                  </button>
                );
              })}
            </div>
          </Card>

          {/* SECTION 4 — NOTES */}
          <Card title="4. Observações" sub="Visível apenas internamente">
            <textarea className="textarea" placeholder="Notas internas, justificativa, link com aprovação…"/>
          </Card>
        </div>

        {/* SIDE RAIL */}
        <div className="stack gap-4" style={{ position: 'sticky', top: 72, alignSelf: 'start' }}>
          <Card title="Resumo">
            <dl className="kv">
              <dt>Empresa</dt><dd>{company}</dd>
              <dt>Commodity</dt><dd>{commodity}</dd>
              <dt>Intenção</dt><dd>{intent === 'GLOBAL_POSITION' ? 'Posição global' : intent === 'COMMERCIAL_HEDGE' ? 'Hedge comercial' : 'Spread'}</dd>
              <dt>Trade</dt><dd>{tradeType}</dd>
              <dt>Quantidade</dt><dd className="tabular">{Number(quantity || 0).toLocaleString('pt-BR')} MT</dd>
              <dt>Direção</dt><dd><DirectionBadge dir={direction}/></dd>
              {leg1.priceType && <React.Fragment><dt>Leg 1</dt><dd>{leg1.side === 'buy' ? 'Compra' : 'Venda'} · {leg1.priceType}</dd></React.Fragment>}
              {showLeg2 && leg2.priceType && <React.Fragment><dt>Leg 2</dt><dd>{leg2.side === 'buy' ? 'Compra' : 'Venda'} · {leg2.priceType}</dd></React.Fragment>}
            </dl>
          </Card>

          <Card title="Pré-validações">
            <div className="stack gap-2">
              <Validation ok={!!commodity} label="Commodity definida"/>
              <Validation ok={Number(quantity) >= 25} label={Number(quantity)>=25?'Quantidade ≥ lote mínimo (25 MT)':'Quantidade abaixo do lote mínimo'}/>
              <Validation ok={!!leg1.priceType} label={leg1.priceType?'Leg 1 configurada ('+leg1.priceType+')':'Leg 1 sem price type'}/>
              {showLeg2 && <Validation ok={!!leg2.priceType} label={leg2.priceType?'Leg 2 configurada ('+leg2.priceType+')':'Leg 2 sem price type'}/>}
              <Validation ok={cps.length>0} label={cps.length>0?cps.length+' contraparte(s) selecionada(s)':'Sem contrapartes selecionadas'}/>
              <Validation ok={intent!=='COMMERCIAL_HEDGE' || !!orderId} label={intent==='COMMERCIAL_HEDGE'?(orderId?'Ordem comercial vinculada':'Sem ordem vinculada'):'Intenção sem ordem'}/>
            </div>
          </Card>

          <Card title="Governança">
            <dl className="kv">
              <dt>Alçada</dt><dd>Trader · até US$ 5 M</dd>
              <dt>Aprovação</dt><dd><Badge kind="pos" dot>Dentro da alçada</Badge></dd>
              <dt>Política IFRS</dt><dd>Hedge accounting</dd>
              <dt>Mark-to-market</dt><dd>Diário · LME 11:30 BST</dd>
            </dl>
          </Card>
        </div>
      </div>
    </div>
  );
}

function LegEditor({ legKey, leg, setLeg, setLegSide, label }) {
  const update = (k, v) => setLeg(l => ({ ...l, [k]: v }));
  const showAVG = leg.priceType === 'AVG';
  const showAVGInter = leg.priceType === 'AVGInter';
  const showFix = leg.priceType === 'Fix' || leg.priceType === 'C2R';
  return (
    <div>
      <div className="row gap-2" style={{ marginBottom: 12 }}>
        <Badge kind="info" outlined>{label}</Badge>
        {leg.priceType && <span style={{ fontSize: 11.5, color: 'var(--muted)' }}>{leg.side==='buy'?'Compra':'Venda'} {leg.priceType}</span>}
      </div>

      <div className="field-grid">
        <div className="field">
          <label className="field-label">Side <span className="req">*</span></label>
          <div className="radio-group">
            <button className={leg.side==='buy'?'active buy':''} onClick={()=>setLegSide(legKey,'buy')}>Compra</button>
            <button className={leg.side==='sell'?'active sell':''} onClick={()=>setLegSide(legKey,'sell')}>Venda</button>
          </div>
        </div>

        <div className="field">
          <label className="field-label">Price type <span className="req">*</span></label>
          <select className="select" value={leg.priceType} onChange={e=>update('priceType', e.target.value)}>
            <option value="">— Selecione —</option>
            {RFQ_PRICE_TYPES.map(pt => <option key={pt.value} value={pt.value}>{pt.label}</option>)}
          </select>
        </div>

        {showAVG && (
          <React.Fragment>
            <div className="field">
              <label className="field-label">Mês de média <span className="req">*</span></label>
              <select className="select" value={leg.monthName} onChange={e=>update('monthName', e.target.value)}>
                {RFQ_MONTHS_EN.map((m, i) => <option key={m} value={m}>{RFQ_MONTHS_PT[i]}</option>)}
              </select>
            </div>
            <div className="field">
              <label className="field-label">Ano <span className="req">*</span></label>
              <select className="select" value={leg.year} onChange={e=>update('year', Number(e.target.value))}>
                {[2026,2027,2028,2029,2030].map(y => <option key={y} value={y}>{y}</option>)}
              </select>
            </div>
          </React.Fragment>
        )}

        {showAVGInter && (
          <React.Fragment>
            <div className="field">
              <label className="field-label">Data início <span className="req">*</span></label>
              <input className="input" type="date" value={leg.startDate} onChange={e=>update('startDate', e.target.value)}/>
            </div>
            <div className="field">
              <label className="field-label">Data fim <span className="req">*</span></label>
              <input className="input" type="date" value={leg.endDate} onChange={e=>update('endDate', e.target.value)} min={leg.startDate}/>
            </div>
          </React.Fragment>
        )}

        {showFix && (
          <React.Fragment>
            <div className="field">
              <label className="field-label">Fixing date</label>
              <input className="input" type="date" value={leg.fixingDate} onChange={e=>update('fixingDate', e.target.value)} readOnly={leg.fixingDateInherited}/>
              {leg.fixingDateInherited && <div className="field-help">Herdado da leg variável (oposta)</div>}
            </div>
            <div className="field">
              <label className="field-label">Tipo de ordem</label>
              <select className="select" value={leg.orderType} onChange={e=>update('orderType', e.target.value)}>
                <option value="">—</option>
                {RFQ_ORDER_TYPES.map(o => <option key={o.value} value={o.value}>{o.label}</option>)}
              </select>
            </div>
            {leg.orderType && leg.orderType !== 'At Market' && (
              <div className="field">
                <label className="field-label">Validade</label>
                <select className="select" value={leg.orderValidity} onChange={e=>update('orderValidity', e.target.value)}>
                  {RFQ_VALIDITIES.map(v => <option key={v} value={v}>{v}</option>)}
                </select>
              </div>
            )}
            {leg.orderType === 'Limit' && (
              <div className="field">
                <label className="field-label">Preço limite (USD) <span className="req">*</span></label>
                <div className="input-suffix">
                  <input className="input" value={leg.limitPrice} onChange={e=>update('limitPrice', e.target.value)} placeholder="2.645,00"/>
                  <span className="suffix">USD</span>
                </div>
              </div>
            )}
          </React.Fragment>
        )}
      </div>
    </div>
  );
}

function Validation({ ok, warn, label }) {
  const color = warn ? 'var(--orange)' : ok ? 'var(--pos)' : 'var(--neg)';
  return (
    <div className="row gap-2" style={{ fontSize: 12.5 }}>
      <span style={{ width: 14, height: 14, borderRadius: '50%', display: 'grid', placeItems: 'center', background: color, color: '#fff', fontSize: 10 }}>{warn ? '!' : '✓'}</span>
      <span style={{ color: 'var(--ink-2)' }}>{label}</span>
    </div>
  );
}

// ============================================================
// RFQ DETAIL — quote comparison
// ============================================================
function RFQDetailPage({ id }) {
  const rfq = M.rfqs.find(r => r.id === id) || M.rfqs[0];
  const quotes = M.sampleQuotes;
  const best = quotes.find(q => q.status === 'best');
  return (
    <div className="page">
      <div className="page-head">
        <div>
          <div className="row gap-2" style={{ marginBottom: 4 }}>
            <button className="btn btn-link" onClick={() => (window.location.hash = '#/rfq')}><Icon.ArrowLeft/> RFQ</button>
            <span style={{ color: 'var(--muted)' }}>/</span>
            <span className="mono" style={{ fontSize: 12, color: 'var(--muted)' }}>{rfq.id}</span>
          </div>
          <h1 className="page-title">{rfq.id}</h1>
          <div className="page-sub">{rfq.commodity} · <DirectionBadge dir={rfq.direction}/> · {rfq.qty.toLocaleString('pt-BR')} t · janela {rfq.window}</div>
        </div>
        <div className="page-actions">
          <StatePill state={rfq.state}/>
          <button className="btn btn-secondary">Cancelar RFQ</button>
          <button className="btn btn-secondary">Reenviar</button>
          <button className="btn btn-accent"><Icon.Bolt/>Fechar com melhor cotação</button>
        </div>
      </div>

      <div className="card" style={{ marginBottom: 16, padding: '12px 18px' }}>
        <div className="steps">
          <div className="step done"><span className="dot"/>Criada · 09:14</div>
          <div className="step done"><span className="dot"/>Enviada · 09:18</div>
          <div className="step current"><span className="dot"/>Cotada · 09:19 — 4/5</div>
          <div className="step"><span className="dot"/>Aprovada</div>
          <div className="step"><span className="dot"/>Executada</div>
        </div>
      </div>

      <div className="detail-grid">
        <div className="stack gap-4">
          <Card title="Cotações recebidas" sub="Janela de cotação válida até 09:34 · 16 min restantes"
            actions={<button className="btn-link">Reenviar pendentes</button>} noPad>
            <table className="tbl">
              <thead><tr>
                <th>Contraparte</th>
                <th className="num">Preço (USD/t)</th>
                <th className="num">Spread vs melhor</th>
                <th className="num">vs Mid LME</th>
                <th>Validade</th>
                <th>Recebida</th>
                <th>Status</th>
                <th></th>
              </tr></thead>
              <tbody>
                {quotes.map((q, i) => {
                  const isBest = q.status === 'best';
                  const isPending = q.status === 'pending';
                  const mid = 2645.50;
                  const vsMid = q.price ? ((q.price - mid) / mid) * 100 : null;
                  return (
                    <tr key={q.cp} className={isBest ? 'selected' : ''}>
                      <td className="strong">{q.cp} {isBest && <span style={{ marginLeft: 6, color: 'var(--orange)', fontSize: 10, fontWeight: 600, textTransform: 'uppercase', letterSpacing: '0.05em' }}>Melhor</span>}</td>
                      <td className="num strong">{q.price ? q.price.toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 }) : '—'}</td>
                      <td className="num" style={{ color: q.spread === 0 ? 'var(--pos)' : 'var(--ink-2)' }}>{q.spread != null ? (q.spread === 0 ? '—' : '+' + q.spread.toFixed(2)) : '—'}</td>
                      <td className="num" style={{ color: vsMid != null ? (vsMid < 0 ? 'var(--pos)' : 'var(--neg)') : 'var(--muted)' }}>{vsMid != null ? (vsMid >= 0 ? '+' : '') + vsMid.toFixed(2) + ' %' : '—'}</td>
                      <td style={{ fontSize: 12, color: 'var(--muted)' }}>{q.valid ?? '—'}</td>
                      <td style={{ fontSize: 12, color: 'var(--muted)' }}>{q.received ?? '—'}</td>
                      <td><StatePill state={q.status}/></td>
                      <td>
                        {!isPending && !isBest && <button className="btn btn-secondary btn-sm">Fechar</button>}
                        {isBest && <button className="btn btn-accent btn-sm">Fechar →</button>}
                        {isPending && <button className="btn btn-ghost btn-sm">Lembrar</button>}
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </Card>

          <div className="grid-2">
            <Card title="Resumo da operação">
              <dl className="kv">
                <dt>RFQ</dt><dd className="mono">{rfq.id}</dd>
                <dt>Intenção</dt><dd>{rfq.intent === 'COMMERCIAL_HEDGE' ? 'Hedge comercial' : 'Posição global'}</dd>
                <dt>Tipo</dt><dd>Forward (futuro a termo)</dd>
                <dt>Lado</dt><dd><DirectionBadge dir={rfq.direction}/></dd>
                <dt>Quantidade</dt><dd className="tabular">{rfq.qty.toLocaleString('pt-BR')} t</dd>
                <dt>Janela</dt><dd>{rfq.window} · {rfq.delivery_start.split('-').reverse().join('/')} → {rfq.delivery_end.split('-').reverse().join('/')}</dd>
                <dt>Mid LME (ref.)</dt><dd className="tabular">2.645,50</dd>
                <dt>Solicitante</dt><dd>{rfq.requester} · Mesa Metais</dd>
              </dl>
            </Card>
            <Card title="Notional & impacto">
              <dl className="kv">
                <dt>Notional (melhor)</dt><dd className="tabular strong">US$ {(rfq.qty * best.price).toLocaleString('en-US', { maximumFractionDigits: 0 })}</dd>
                <dt>Notional em BRL</dt><dd className="tabular">R$ {(rfq.qty * best.price * 5.124).toLocaleString('pt-BR', { maximumFractionDigits: 0 })}</dd>
                <dt>P&L vs mid</dt><dd className="tabular" style={{ color: 'var(--pos)' }}>+US$ {(((2645.50 - best.price)) * rfq.qty).toLocaleString('en-US', { maximumFractionDigits: 0 })}</dd>
                <dt>Δ cobertura jun/26</dt><dd className="tabular" style={{ color: 'var(--pos)' }}>+28,6 pp → 116,7 %</dd>
                <dt>Margem inicial</dt><dd className="tabular">US$ 158.310 (10 %)</dd>
              </dl>
            </Card>
          </div>
        </div>

        <div className="stack gap-4" style={{ position: 'sticky', top: 72, alignSelf: 'start' }}>
          <Card title="Histórico" sub="Trilha completa de auditoria">
            <div className="feed">
              <FeedItem kind="info" when="09:14" who="M. Santos" what={<>RFQ criada · rascunho aprovado</>}/>
              <FeedItem kind="info" when="09:18" who="Sistema" what={<>Enviada a 5 contrapartes</>}/>
              <FeedItem kind="pos" when="09:18" who="ITAU" what={<>Cotou 2.638,50</>}/>
              <FeedItem kind="info" when="09:18" who="JPM" what={<>Cotou 2.639,25</>}/>
              <FeedItem kind="info" when="09:19" who="SANT" what={<>Cotou 2.641,00</>}/>
              <FeedItem kind="info" when="09:19" who="BTG" what={<>Cotou 2.642,75</>}/>
              <FeedItem kind="warn" when="agora" who="BRAD" what={<>Cotação pendente · 15 min</>}/>
            </div>
          </Card>

          <Card title="Documentos">
            <div className="stack gap-2">
              <DocLink name="Confirmação de RFQ" size="48 KB"/>
              <DocLink name="Snapshot de exposição #EXP-091200" size="172 KB"/>
              <DocLink name="Política de hedge · v3.2" size="2,1 MB"/>
            </div>
          </Card>
        </div>
      </div>
    </div>
  );
}

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
// CONTRACTS
// ============================================================
function ContractsPage() {
  const [tab, setTab] = React.useState('active');
  return (
    <div className="page">
      <div className="page-head">
        <div>
          <h1 className="page-title">Contratos</h1>
          <div className="page-sub">Posições derivativas ativas e vencendo</div>
        </div>
        <div className="page-actions">
          <button className="btn btn-secondary"><Icon.Download/>Exportar</button>
        </div>
      </div>

      <div className="kpi-row cols-4" style={{ marginBottom: 16 }}>
        <KPI label="Contratos ativos" value="84" delta="9 vencendo em 30d" deltaKind="flat"/>
        <KPI label="Notional total" value="US$ 192,4 M" delta="+US$ 24,1 M MTD" deltaKind="pos"/>
        <KPI label="MTM agregado" value="+US$ 204.165" delta="+US$ 18.460 1d" deltaKind="pos"/>
        <KPI label="Contratos no vencimento (30d)" value="9" delta="Notional US$ 14,2 M" deltaKind="flat"/>
      </div>

      <Card noPad>
        <div className="tbl-tools">
          <div className="tabs-pill">
            {[['active','Ativos',84],['maturing','Vencendo',9],['settled','Liquidados',412]].map(([k,l,c]) => (
              <button key={k} className={"tab " + (tab===k?'active':'')} onClick={()=>setTab(k)}>{l} <span style={{ color: 'var(--muted-2)', marginLeft: 4 }}>{c}</span></button>
            ))}
          </div>
          <div className="sp"/>
          <button className="chip"><Icon.Filter/>Commodity</button>
          <button className="chip"><Icon.Filter/>Contraparte</button>
          <button className="chip"><Icon.Filter/>Vencimento</button>
        </div>

        <table className="tbl">
          <thead><tr>
            <th>Contrato</th>
            <th>Commodity</th>
            <th>Tipo</th>
            <th>Pernas</th>
            <th className="num">Qtd</th>
            <th className="num">Preço fixo</th>
            <th>Contraparte</th>
            <th>Vencimento</th>
            <th className="num">MTM (USD)</th>
            <th>Status</th>
            <th></th>
          </tr></thead>
          <tbody>
            {M.contracts.map(c => (
              <tr key={c.id} onClick={() => (window.location.hash = `#/contracts/${c.id}`)} style={{ cursor: 'pointer' }}>
                <td className="strong mono">{c.id}</td>
                <td><CommodityChip code={c.commodity}/></td>
                <td>{c.type}</td>
                <td><LegsBadge fixed={c.fixed_leg} variable={c.var_leg}/></td>
                <td className="num">{c.commodity==='USDBRL'?'US$ '+(c.qty/1000000).toFixed(1)+' M':c.qty.toLocaleString('pt-BR')+' t'}</td>
                <td className="num strong">{c.price.toLocaleString('en-US', { minimumFractionDigits: c.commodity==='USDBRL'?4:2, maximumFractionDigits: c.commodity==='USDBRL'?4:2 })}</td>
                <td>{c.cp}</td>
                <td>{c.settle.split('-').reverse().join('/')}</td>
                <td className="num strong" style={{ color: c.mtm>=0?'var(--pos)':'var(--neg)' }}>{c.mtm>=0?'+':''}{c.mtm.toLocaleString('en-US', { maximumFractionDigits: 0 })}</td>
                <td><StatePill state={c.status}/></td>
                <td><button className="btn btn-ghost btn-sm"><Icon.ChevronRight/></button></td>
              </tr>
            ))}
          </tbody>
        </table>
        <Pager from={1} to={9} total={84}/>
      </Card>
    </div>
  );
}

function LegsBadge({ fixed, variable }) {
  return (
    <span className="row gap-2" style={{ fontSize: 11 }}>
      <Badge kind={fixed==='buy'?'pos':'neg'}>{fixed==='buy'?'Compra':'Venda'} fixa</Badge>
      <span style={{ color: 'var(--muted)' }}>×</span>
      <Badge kind="neutral">{variable==='buy'?'Compra':'Venda'} var.</Badge>
    </span>
  );
}

// ============================================================
// COUNTERPARTIES
// ============================================================
function CounterpartiesPage() {
  return (
    <div className="page">
      <div className="page-head">
        <div>
          <h1 className="page-title">Contrapartes</h1>
          <div className="page-sub">Limites de crédito, rating e exposição corrente</div>
        </div>
        <div className="page-actions">
          <button className="btn btn-secondary"><Icon.Download/>Exportar</button>
          <button className="btn btn-primary" onClick={() => (window.location.hash = '#/counterparties/new')}><Icon.Plus/>Nova contraparte</button>
        </div>
      </div>

      <div className="kpi-row cols-4" style={{ marginBottom: 16 }}>
        <KPI label="Contrapartes ativas" value="6" delta="1 em análise" deltaKind="flat"/>
        <KPI label="Limite agregado" value="US$ 62,0 M" delta="utilizado 53 %" deltaKind="flat"/>
        <KPI label="Concentração top-1" value="24,1" unit="%" delta="JPMorgan · dentro do limite (≤ 30 %)" deltaKind="pos"/>
        <KPI label="Spread médio" value="2,1" unit="bps" delta="−0,4 bps vs mês"/>
      </div>

      <Card noPad>
        <table className="tbl">
          <thead><tr>
            <th>Contraparte</th>
            <th>Rating</th>
            <th className="num">Limite</th>
            <th className="num">Utilizado</th>
            <th style={{ width: 200 }}>Utilização</th>
            <th className="num">Contratos</th>
            <th className="num">MTM (USD)</th>
            <th className="num">Spread médio</th>
            <th>Status</th>
            <th></th>
          </tr></thead>
          <tbody>
            {M.counterparties.map(cp => {
              const pct = (cp.used / cp.limit) * 100;
              return (
                <tr key={cp.id} onClick={() => (window.location.hash = `#/counterparties/${cp.short}`)} style={{ cursor: 'pointer' }}>
                  <td className="strong">
                    <div>{cp.name}</div>
                    <div style={{ fontSize: 11, color: 'var(--muted)', fontWeight: 400 }}>{cp.short} · {cp.id}</div>
                  </td>
                  <td><Badge kind={cp.rating.startsWith('AA')?'pos':'neutral'}>{cp.rating}</Badge></td>
                  <td className="num">US$ {(cp.limit/1000000).toFixed(1)} M</td>
                  <td className="num strong">US$ {(cp.used/1000000).toFixed(1)} M</td>
                  <td>
                    <div className="row gap-3">
                      <Bar pct={pct} kind={pct>80?'neg':pct>60?'warn':'pos'}/>
                      <span className="tabular" style={{ width: 42, textAlign: 'right' }}>{pct.toFixed(0)}%</span>
                    </div>
                  </td>
                  <td className="num">{Math.floor(cp.used/600000)}</td>
                  <td className="num strong" style={{ color: 'var(--pos)' }}>+{Math.floor(cp.used*0.004).toLocaleString('en-US')}</td>
                  <td className="num">{(1.4 + Math.random()*1.8).toFixed(1)} bps</td>
                  <td><StatePill state={cp.status}/></td>
                  <td><button className="btn btn-ghost btn-sm"><Icon.ChevronRight/></button></td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </Card>
    </div>
  );
}

Object.assign(window, { OrdersPage, RFQListPage, RFQNewPage, RFQDetailPage, ContractsPage, CounterpartiesPage });
