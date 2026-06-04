/* Shared widgets & primitives for Alcast Hedge pages */

function Badge({ kind = 'neutral', children, dot }) {
  return <span className={"badge " + kind}>{dot && <span className="dot"/>}{children}</span>;
}

function Sparkline({ points, color = 'var(--navy-2)', width = 80, height = 24, fill }) {
  if (!points || !points.length) return null;
  const min = Math.min(...points);
  const max = Math.max(...points);
  const range = max - min || 1;
  const step = width / (points.length - 1);
  const pts = points.map((p, i) => [i * step, height - ((p - min) / range) * (height - 2) - 1]);
  const d = 'M ' + pts.map(p => p.join(',')).join(' L ');
  const closed = d + ` L ${width},${height} L 0,${height} Z`;
  return (
    <svg width={width} height={height} className="kpi-spark">
      {fill && <path d={closed} fill={fill} opacity="0.18"/>}
      <path d={d} fill="none" stroke={color} strokeWidth="1.5" strokeLinejoin="round"/>
    </svg>
  );
}

function KPI({ label, value, unit, delta, deltaKind, hint, spark, sparkColor }) {
  return (
    <div className="kpi">
      <div className="kpi-label">{label}{hint && <span className="hint" title={hint}>·</span>}</div>
      <div className="kpi-value">{value}{unit && <span className="unit">{unit}</span>}</div>
      {delta != null && (
        <div className={"kpi-delta " + (deltaKind || 'flat')}>
          {deltaKind === 'pos' && '▲ '}
          {deltaKind === 'neg' && '▼ '}
          {delta}
        </div>
      )}
      {spark && <Sparkline points={spark} color={sparkColor || 'var(--navy-2)'} fill={sparkColor || 'var(--navy-2)'}/>}
    </div>
  );
}

function Card({ title, sub, actions, children, footer, noPad }) {
  return (
    <div className="card">
      {(title || actions) && (
        <div className="card-head">
          <div>
            {title && <h3 className="card-title">{title}</h3>}
            {sub && <div className="card-sub">{sub}</div>}
          </div>
          {actions}
        </div>
      )}
      {noPad ? children : <div className="card-body">{children}</div>}
      {footer && <div className="card-foot">{footer}</div>}
    </div>
  );
}

function Bar({ pct, kind = 'pos' }) {
  return <div className="bar"><div className={"fill " + kind} style={{ width: `${Math.min(100, Math.max(0, pct))}%` }}/></div>;
}

function Pager({ from = 1, to = 10, total = 47 }) {
  return (
    <div className="pager">
      <div>Mostrando {from}-{to} de {total}</div>
      <div className="ctrls">
        <button className="pg-btn"><Icon.ArrowLeft/></button>
        <button className="pg-btn active">1</button>
        <button className="pg-btn">2</button>
        <button className="pg-btn">3</button>
        <button className="pg-btn"><Icon.ArrowRight/></button>
      </div>
    </div>
  );
}

function FilterChips({ filters, value, onChange }) {
  return (
    <div className="row gap-2">
      {filters.map(f => (
        <button key={f.key} className={"chip " + (value === f.key ? 'active' : '')} onClick={() => onChange && onChange(f.key)}>
          {f.label}{f.count != null && <span style={{ opacity: 0.7, marginLeft: 4 }}>{f.count}</span>}
        </button>
      ))}
    </div>
  );
}

function StatePill({ state }) {
  const map = {
    CREATED: { kind: 'neutral', label: 'Criada' },
    SENT: { kind: 'info', label: 'Enviada' },
    QUOTED: { kind: 'pos', label: 'Cotada' },
    filled: { kind: 'pos', label: 'Liquidada' },
    partial: { kind: 'warn', label: 'Parcial' },
    cancelled: { kind: 'neutral', label: 'Cancelada' },
    pending: { kind: 'warn', label: 'Pendente' },
    active: { kind: 'pos', label: 'Ativo' },
    maturing: { kind: 'warn', label: 'Vencendo' },
    review: { kind: 'warn', label: 'Em análise' },
    projected: { kind: 'info', label: 'Projetado' },
    confirmed: { kind: 'pos', label: 'Confirmado' },
  };
  const e = map[state] || { kind: 'neutral', label: state };
  return <Badge kind={e.kind} dot>{e.label}</Badge>;
}

function DirectionBadge({ dir }) {
  if (dir === 'BUY' || dir === 'buy') return <Badge kind="pos">COMPRA</Badge>;
  if (dir === 'SELL' || dir === 'sell') return <Badge kind="neg">VENDA</Badge>;
  return <Badge kind="neutral">{dir}</Badge>;
}

function CommodityChip({ code }) {
  const colors = { 'AL-LME': '#7E8AA6', 'CU-LME': '#C2825F', 'ZN-LME': '#6FA89C', 'NI-LME': '#8A86A6', 'USDBRL': '#1E5C36' };
  const c = colors[code] || '#8E94A0';
  return (
    <span className="row gap-2" style={{ fontWeight: 500 }}>
      <span style={{ width: 8, height: 8, borderRadius: 2, background: c, display: 'inline-block' }}/>
      {code}
    </span>
  );
}

// ============================================================
// DASHBOARD
// ============================================================
function DashboardPage() {
  const M = window.MOCK;
  return (
    <div className="page">
      <div className="page-head">
        <div>
          <h1 className="page-title">Visão geral</h1>
          <div className="page-sub">Posições, cobertura de hedge e atividade · atualizado às 09:14</div>
        </div>
        <div className="page-actions">
          <button className="btn btn-secondary"><Icon.Refresh/>Atualizar</button>
          <button className="btn btn-secondary"><Icon.Download/>Exportar</button>
          <button className="btn btn-primary" onClick={() => (window.location.hash = '#/rfq/new')}><Icon.Plus/>Nova RFQ</button>
        </div>
      </div>

      <div className="kpi-row" style={{ marginBottom: 16 }}>
        <KPI label="Exposição comercial" value="36.300" unit="t" delta="+1.420 t vs ontem" deltaKind="pos" spark={[24,26,28,27,29,32,34,36,36.3]} sparkColor="var(--navy-2)"/>
        <KPI label="Hedge ratio" value="49,3" unit="%" delta="+2,1 pp vs ontem" deltaKind="pos" spark={[41,42,44,43,45,46,47,48,49.3]} sparkColor="var(--pos)"/>
        <KPI label="MTM agregado" value="+US$ 204.165" delta="+US$ 18.460 1d" deltaKind="pos" spark={[100,110,140,160,150,170,180,190,204]} sparkColor="var(--pos)"/>
        <KPI label="P&L MTD realizado" value="+US$ 312.880" delta="+1,8 % vs mês anterior" deltaKind="pos"/>
        <KPI label="RFQ abertas" value="3" delta="2 aguardando cotação" deltaKind="flat"/>
      </div>

      <div className="grid-7-5" style={{ marginBottom: 16 }}>
        <Card title="Cobertura por janela" sub="Hedge vs exposição comercial · próximos 8 meses"
          actions={<div className="tabs-pill"><button className="tab active">t</button><button className="tab">US$</button></div>}>
          <CoverageList buckets={M.exposureBuckets}/>
          <div className="row gap-4" style={{ marginTop: 10, fontSize: 11.5, color: 'var(--muted)' }}>
            <span className="row gap-2"><span style={{ width: 8, height: 8, background: 'var(--pos)' }}/>≥ 70% (política)</span>
            <span className="row gap-2"><span style={{ width: 8, height: 8, background: 'var(--orange)' }}/>40–70%</span>
            <span className="row gap-2"><span style={{ width: 8, height: 8, background: 'var(--neg)' }}/>&lt; 40%</span>
          </div>
        </Card>

        <Card title="Atividade recente" sub="Operações dos últimos 24 h"
          actions={<button className="btn-link">Ver tudo</button>}>
          <div className="feed">
            <FeedItem kind="pos" when="09:14" who="M. Santos" what={<>Nova RFQ <strong>RFQ-2026-0184</strong> · AL-LME 1.200t buy</>}/>
            <FeedItem kind="info" when="09:08" who="Sistema" what={<>Snapshot diário de exposições · 4 ajustes detectados</>}/>
            <FeedItem kind="pos" when="09:04" who="R. Almeida" what={<>Ordem <strong>ORD-2026-0419</strong> liquidada · AL-LME 1.500t @ 2.631,00 · ITAU</>}/>
            <FeedItem kind="warn" when="08:55" who="L. Ferreira" what={<>Limite de contraparte <strong>Citi</strong> sob análise · uso 0/6,5M</>}/>
            <FeedItem kind="pos" when="08:21" who="R. Almeida" what={<>Ordem <strong>ORD-2026-0418</strong> liquidada · USDBRL 3M @ 5,1115 · JPM</>}/>
            <FeedItem kind="info" when="08:14" who="Sistema" what={<>Cotações LME atualizadas (open)</>}/>
            <FeedItem kind="pos" when="17:55" who="A. Costa" what={<>Aprovação <strong>APR-2026-0096</strong> concedida · CT-2026-0118</>}/>
          </div>
        </Card>
      </div>

      <div className="grid-8-4">
        <Card title="Exposição por commodity" sub="Saldo comercial líquido por mês · em toneladas">
          <table className="tbl tbl-tight">
            <thead><tr>
              <th>Commodity</th>
              <th className="num">Comercial</th>
              <th className="num">Hedgeado</th>
              <th className="num">Residual</th>
              <th style={{ width: 220 }}>Cobertura</th>
              <th className="num">Δ 1d (MTM)</th>
            </tr></thead>
            <tbody>
              <ExposureRow code="AL-LME" comm="22.400" hed="12.300" res="10.100" pct={55} delta="+US$ 14.820" pos/>
              <ExposureRow code="CU-LME" comm="3.200" hed="1.250" res="1.950" pct={39} delta="+US$ 2.140" pos/>
              <ExposureRow code="ZN-LME" comm="2.450" hed="180" res="2.270" pct={7} delta="−US$ 410" neg/>
              <ExposureRow code="NI-LME" comm="420" hed="0" res="420" pct={0} delta="+US$ 0" flat/>
              <ExposureRow code="USDBRL" comm="US$ 38,2 M" hed="US$ 18,0 M" res="US$ 20,2 M" pct={47} delta="+US$ 1.910" pos/>
            </tbody>
          </table>
        </Card>

        <Card title="Cotações de mercado" sub="LME · Bovespa · 09:14" actions={<Badge kind="pos" dot>ao vivo</Badge>}>
          <div className="stack" style={{ gap: 0 }}>
            {M.commodities.map(c => {
              const chg = ((c.last - c.prev) / c.prev) * 100;
              return (
                <div key={c.code} className="row gap-3" style={{ padding: '11px 0', borderBottom: '1px solid var(--line-soft)' }}>
                  <div style={{ flex: 1 }}>
                    <div style={{ fontSize: 12.5, fontWeight: 500 }}>{c.code}</div>
                    <div style={{ fontSize: 11, color: 'var(--muted)' }}>{c.name}</div>
                  </div>
                  <div style={{ textAlign: 'right' }}>
                    <div className="tabular" style={{ fontWeight: 500 }}>{c.last.toLocaleString('en-US', { minimumFractionDigits: c.code === 'USDBRL' ? 4 : 2, maximumFractionDigits: c.code === 'USDBRL' ? 4 : 2 })}</div>
                    <div className="tabular" style={{ fontSize: 11, color: chg >= 0 ? 'var(--pos)' : 'var(--neg)' }}>
                      {chg >= 0 ? '▲' : '▼'} {Math.abs(chg).toFixed(2)}%
                    </div>
                  </div>
                </div>
              );
            })}
          </div>
        </Card>
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

function ExposureRow({ code, comm, hed, res, pct, delta, pos, neg, flat }) {
  return (
    <tr>
      <td className="strong"><CommodityChip code={code}/></td>
      <td className="num">{comm}</td>
      <td className="num">{hed}</td>
      <td className="num">{res}</td>
      <td>
        <div className="row gap-3">
          <Bar pct={pct} kind={pct >= 70 ? 'pos' : pct >= 40 ? 'warn' : 'neg'}/>
          <span className="tabular" style={{ width: 36, textAlign: 'right', fontSize: 12 }}>{pct}%</span>
        </div>
      </td>
      <td className="num" style={{ color: pos ? 'var(--pos)' : neg ? 'var(--neg)' : 'var(--muted)' }}>{delta}</td>
    </tr>
  );
}

function CoverageList({ buckets }) {
  return (
    <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '4px 24px' }}>
      {buckets.map(b => {
        const kind = b.ratio >= 70 ? 'pos' : b.ratio >= 40 ? 'warn' : 'neg';
        return (
          <div key={b.month} className="row gap-3" style={{ padding: '5px 0', borderBottom: '1px solid var(--line-soft)' }}>
            <span style={{ width: 56, fontSize: 12.5, fontWeight: 500, color: 'var(--ink-2)' }}>{b.month}</span>
            <div style={{ flex: 1 }}><Bar pct={b.ratio} kind={kind}/></div>
            <span className="tabular" style={{ width: 46, textAlign: 'right', fontSize: 12, fontWeight: 500, color: kind==='neg'?'var(--neg)':kind==='warn'?'var(--orange-strong)':'var(--pos)' }}>{b.ratio.toFixed(0)}%</span>
            <span className="tabular" style={{ width: 60, textAlign: 'right', fontSize: 11, color: 'var(--muted)' }}>{b.hedged_mt > 0 ? (b.hedged_mt/1000).toFixed(1) + 'k/' : '0/'}{(b.commercial_mt/1000).toFixed(1)}k t</span>
          </div>
        );
      })}
    </div>
  );
}

function CoverageChart({ buckets }) {
  const maxQty = Math.max(...buckets.map(b => b.commercial_mt));
  return (
    <div className="chart-bars" style={{ height: 180 }}>
      {buckets.map(b => {
        const totalH = (b.commercial_mt / maxQty) * 160;
        const hedgedH = (b.hedged_mt / b.commercial_mt) * totalH;
        const openH = totalH - hedgedH;
        return (
          <div className="group" key={b.month}>
            <div className="stack">
              <div className="seg hedged" style={{ height: hedgedH, minHeight: 1 }}/>
              <div className="seg open" style={{ height: openH }}/>
            </div>
            <div style={{ height: 12 }}/>
            <div className="label">{b.month}</div>
            <div style={{ fontSize: 11, color: 'var(--ink-2)', fontWeight: 500, textAlign: 'center', marginTop: 2 }}>{b.ratio.toFixed(0)}%</div>
          </div>
        );
      })}
    </div>
  );
}

// ============================================================
// EXPOSURES
// ============================================================
function ExposuresPage() {
  const M = window.MOCK;
  const [commodity, setCommodity] = React.useState('AL-LME');
  return (
    <div className="page">
      <div className="page-head">
        <div>
          <h1 className="page-title">Exposições</h1>
          <div className="page-sub">Saldo comercial líquido por janela de entrega · snapshot 27/05/2026 09:12</div>
        </div>
        <div className="page-actions">
          <button className="btn btn-secondary"><Icon.Refresh/>Recalcular</button>
          <button className="btn btn-secondary"><Icon.Download/>Exportar</button>
        </div>
      </div>

      <div className="kpi-row cols-4" style={{ marginBottom: 16 }}>
        <KPI label="Comercial total" value="36.300" unit="t" delta="+1.420 t · 24h" deltaKind="pos"/>
        <KPI label="Hedgeado" value="17.900" unit="t" delta="+700 t · 24h" deltaKind="pos"/>
        <KPI label="Residual" value="18.400" unit="t" delta="+720 t · 24h" deltaKind="neg"/>
        <KPI label="Aderência à política" value="49,3" unit="%" delta="meta ≥ 70 %" deltaKind="neg"/>
      </div>

      <Card title="Exposição por commodity e janela" sub="Drill-down por mês de entrega"
        actions={
          <div className="row gap-2">
            <div className="radio-group">
              {['AL-LME','CU-LME','ZN-LME','NI-LME','USDBRL'].map(c => (
                <button key={c} className={commodity===c?'active':''} onClick={()=>setCommodity(c)}>{c}</button>
              ))}
            </div>
            <button className="btn btn-secondary btn-sm"><Icon.Filter/>Filtros</button>
          </div>
        } noPad>
        <table className="tbl">
          <thead><tr>
            <th>Janela</th>
            <th className="num">Comercial ativa</th>
            <th className="num">Comercial passiva</th>
            <th className="num">Saldo líquido</th>
            <th className="num">Hedgeado</th>
            <th className="num">Residual</th>
            <th style={{ width: 220 }}>Cobertura</th>
            <th>Política</th>
            <th></th>
          </tr></thead>
          <tbody>
            {M.exposureBuckets.map((b, i) => {
              const ok = b.ratio >= 70;
              const warn = b.ratio >= 40 && b.ratio < 70;
              return (
                <tr key={b.month}>
                  <td className="strong">{b.month}</td>
                  <td className="num">{(b.commercial_mt * 0.62).toLocaleString('pt-BR', { maximumFractionDigits: 0 })}</td>
                  <td className="num">{(b.commercial_mt * 0.38).toLocaleString('pt-BR', { maximumFractionDigits: 0 })}</td>
                  <td className="num strong">{b.commercial_mt.toLocaleString('pt-BR')}</td>
                  <td className="num">{b.hedged_mt.toLocaleString('pt-BR')}</td>
                  <td className="num" style={{ color: b.residual_mt > 2000 ? 'var(--neg)' : 'var(--ink-2)' }}>{b.residual_mt.toLocaleString('pt-BR')}</td>
                  <td>
                    <div className="row gap-3">
                      <Bar pct={b.ratio} kind={ok ? 'pos' : warn ? 'warn' : 'neg'}/>
                      <span className="tabular" style={{ width: 42, textAlign: 'right' }}>{b.ratio.toFixed(1)}%</span>
                    </div>
                  </td>
                  <td>{ok ? <Badge kind="pos" dot>OK</Badge> : warn ? <Badge kind="warn" dot>Atenção</Badge> : <Badge kind="neg" dot>Abaixo</Badge>}</td>
                  <td><div className="tbl-actions"><button className="btn btn-ghost btn-sm" onClick={() => (window.location.hash = '#/rfq/new')}>Cobrir →</button></div></td>
                </tr>
              );
            })}
          </tbody>
        </table>
        <Pager from={1} to={8} total={8}/>
      </Card>

      <div className="grid-7-5" style={{ marginTop: 16 }}>
        <Card title="Reconciliação contábil" sub="Comparativo SAP × Plataforma de Hedge · D-1">
          <table className="tbl tbl-tight">
            <thead><tr>
              <th>Janela</th>
              <th className="num">SAP (ECC)</th>
              <th className="num">Plataforma</th>
              <th className="num">Δ</th>
              <th>Status</th>
            </tr></thead>
            <tbody>
              <tr><td>jun/26</td><td className="num">4.215</td><td className="num">4.200</td><td className="num" style={{ color: 'var(--warn)' }}>−15</td><td><Badge kind="warn" dot>Diferença</Badge></td></tr>
              <tr><td>jul/26</td><td className="num">3.800</td><td className="num">3.800</td><td className="num">0</td><td><Badge kind="pos" dot>OK</Badge></td></tr>
              <tr><td>ago/26</td><td className="num">4.100</td><td className="num">4.100</td><td className="num">0</td><td><Badge kind="pos" dot>OK</Badge></td></tr>
              <tr><td>set/26</td><td className="num">3.495</td><td className="num">3.500</td><td className="num" style={{ color: 'var(--warn)' }}>+5</td><td><Badge kind="warn" dot>Diferença</Badge></td></tr>
              <tr><td>out/26</td><td className="num">3.900</td><td className="num">3.900</td><td className="num">0</td><td><Badge kind="pos" dot>OK</Badge></td></tr>
            </tbody>
          </table>
        </Card>

        <Card title="Pendências" sub="Itens que precisam de ação">
          <div className="stack" style={{ gap: 0 }}>
            <PendingItem when="hoje" sev="neg" title="ago/26 abaixo da política" desc="Cobertura em 39 % · meta ≥ 70 %"/>
            <PendingItem when="hoje" sev="neg" title="set/26 abaixo da política" desc="Cobertura em 22,9 % · meta ≥ 70 %"/>
            <PendingItem when="hoje" sev="warn" title="Diferença jun/26 ↔ SAP" desc="15 t de divergência detectadas"/>
            <PendingItem when="d-1" sev="warn" title="3 ajustes de exposição" desc="Pendentes de aprovação no workflow"/>
            <PendingItem when="d-2" sev="info" title="Rebalanceamento sugerido" desc="Reduzir 200 t em ZN-LME para abrir limite"/>
          </div>
        </Card>
      </div>
    </div>
  );
}

function PendingItem({ when, sev, title, desc }) {
  const colors = { neg: 'var(--neg)', warn: 'var(--orange)', info: 'var(--info)' };
  return (
    <div className="row gap-3" style={{ padding: '10px 0', borderBottom: '1px solid var(--line-soft)' }}>
      <div style={{ width: 4, alignSelf: 'stretch', background: colors[sev], borderRadius: 2 }}/>
      <div style={{ flex: 1 }}>
        <div style={{ fontSize: 12.5, fontWeight: 500 }}>{title}</div>
        <div style={{ fontSize: 11.5, color: 'var(--muted)' }}>{desc}</div>
      </div>
      <div style={{ fontSize: 11, color: 'var(--muted)' }}>{when}</div>
      <button className="btn btn-ghost btn-sm">Ver →</button>
    </div>
  );
}

Object.assign(window, { Badge, KPI, Card, Bar, Pager, FilterChips, StatePill, DirectionBadge, CommodityChip, Sparkline, DashboardPage, ExposuresPage });
