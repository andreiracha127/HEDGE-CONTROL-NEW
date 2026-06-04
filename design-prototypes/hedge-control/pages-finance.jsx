/* Finance + governance pages: Cashflow, P&L, MTM, MarketData, Approvals, Audit */

(function () {
const M = window.MOCK;

// ============================================================
// CASHFLOW
// ============================================================
function CashflowPage() {
  const byMonth = {};
  M.cashflow.forEach(c => {
    const k = c.date.slice(0, 7);
    if (!byMonth[k]) byMonth[k] = { inflow: 0, outflow: 0, count: 0 };
    if (c.amount_usd > 0) byMonth[k].inflow += c.amount_usd;
    else byMonth[k].outflow += c.amount_usd;
    byMonth[k].count++;
  });
  const months = Object.keys(byMonth).sort();
  const maxAbs = Math.max(...months.map(m => Math.max(byMonth[m].inflow, -byMonth[m].outflow)));

  return (
    <div className="page">
      <div className="page-head">
        <div>
          <h1 className="page-title">Fluxo de caixa projetado</h1>
          <div className="page-sub">Liquidações financeiras de derivativos · próximos 12 meses</div>
        </div>
        <div className="page-actions">
          <button className="btn btn-secondary"><Icon.Download/>Exportar</button>
          <button className="btn btn-primary">Sincronizar com SAP</button>
        </div>
      </div>

      <div className="kpi-row cols-4" style={{ marginBottom: 16 }}>
        <KPI label="Inflow projetado (90d)" value="+US$ 216.865" delta="9 liquidações" deltaKind="pos"/>
        <KPI label="Outflow projetado (90d)" value="−US$ 1.260" delta="1 liquidação" deltaKind="neg"/>
        <KPI label="Net (90d)" value="+US$ 215.605" delta="vs mês anterior +18 %" deltaKind="pos"/>
        <KPI label="Próxima liquidação" value="29/05" delta="CT-2026-0110 · BTG" deltaKind="flat"/>
      </div>

      <div className="grid-7-5" style={{ marginBottom: 16 }}>
        <Card title="Linha do tempo" sub="Líquido por mês · USD">
          <div style={{ position: 'relative', padding: '12px 0' }}>
            <div className="row gap-3" style={{ alignItems: 'flex-end', height: 160 }}>
              {months.map(m => {
                const b = byMonth[m];
                const inH = (b.inflow / maxAbs) * 130;
                const outH = (-b.outflow / maxAbs) * 130;
                const net = b.inflow + b.outflow;
                return (
                  <div key={m} style={{ flex: 1, display: 'flex', flexDirection: 'column', alignItems: 'center', gap: 4 }}>
                    <div style={{ fontSize: 11, color: net>=0?'var(--pos)':'var(--neg)', fontWeight: 500 }} className="tabular">{net>=0?'+':''}{(net/1000).toFixed(1)}k</div>
                    <div style={{ width: '70%', display: 'flex', flexDirection: 'column', alignItems: 'stretch', gap: 1 }}>
                      <div style={{ height: inH, background: 'var(--pos)', borderRadius: '2px 2px 0 0' }}/>
                      {outH > 0 && <div style={{ height: outH, background: 'var(--neg)', borderRadius: '0 0 2px 2px' }}/>}
                    </div>
                    <div style={{ borderTop: '1px solid var(--line-strong)', alignSelf: 'stretch'}}/>
                    <div style={{ fontSize: 11, color: 'var(--muted)' }}>{m.slice(5)+'/'+m.slice(2,4)}</div>
                  </div>
                );
              })}
            </div>
          </div>
        </Card>

        <Card title="Concentração por contraparte" sub="Inflow projetado · 90 dias">
          <div className="stack" style={{ gap: 8 }}>
            {[
              { cp: 'ITAU', v: 40425, pct: 19 },
              { cp: 'JPM', v: 123250, pct: 57 },
              { cp: 'BTG', v: 17000, pct: 8 },
              { cp: 'SANT', v: 15300, pct: 7 },
              { cp: 'BRAD', v: 21148, pct: 10 },
            ].map(r => (
              <div key={r.cp}>
                <div className="row gap-3" style={{ fontSize: 12.5, marginBottom: 4 }}>
                  <span style={{ width: 60, fontWeight: 500 }}>{r.cp}</span>
                  <Bar pct={r.pct*1.5} kind={r.pct>40?'warn':'pos'}/>
                  <span className="tabular" style={{ width: 90, textAlign: 'right' }}>US$ {(r.v/1000).toFixed(1)}k</span>
                  <span className="tabular" style={{ width: 36, textAlign: 'right', color: 'var(--muted)' }}>{r.pct}%</span>
                </div>
              </div>
            ))}
          </div>
          <div className="divider"/>
          <div className="row gap-2" style={{ fontSize: 11.5 }}>
            <Badge kind="warn" dot>Concentração JPM</Badge>
            <span style={{ color: 'var(--muted)' }}>57 % do fluxo · acima do alerta (≥ 50 %)</span>
          </div>
        </Card>
      </div>

      <Card title="Liquidações detalhadas" sub="Eventos de caixa de derivativos · ordenado por data"
        actions={<button className="btn btn-secondary btn-sm"><Icon.Filter/>Filtros</button>} noPad>
        <table className="tbl">
          <thead><tr>
            <th>Data</th>
            <th>Descrição</th>
            <th>Commodity</th>
            <th>Contraparte</th>
            <th className="num">Valor (USD)</th>
            <th className="num">Valor (BRL)</th>
            <th>Direção</th>
            <th>Status</th>
          </tr></thead>
          <tbody>
            {M.cashflow.map((c, i) => (
              <tr key={i}>
                <td className="strong">{c.date.split('-').reverse().join('/')}</td>
                <td>{c.desc}</td>
                <td><CommodityChip code={c.commodity}/></td>
                <td>{c.cp}</td>
                <td className="num strong" style={{ color: c.amount_usd>=0?'var(--pos)':'var(--neg)' }}>{c.amount_usd>=0?'+':''}{c.amount_usd.toLocaleString('en-US', { maximumFractionDigits: 0 })}</td>
                <td className="num">R$ {(c.amount_usd * 5.124).toLocaleString('pt-BR', { maximumFractionDigits: 0 })}</td>
                <td>{c.amount_usd>=0?<Badge kind="pos" dot>Entrada</Badge>:<Badge kind="neg" dot>Saída</Badge>}</td>
                <td><StatePill state={c.status}/></td>
              </tr>
            ))}
          </tbody>
        </table>
      </Card>
    </div>
  );
}

// ============================================================
// P&L
// ============================================================
function PnLPage() {
  return (
    <div className="page">
      <div className="page-head">
        <div>
          <h1 className="page-title">P&amp;L</h1>
          <div className="page-sub">Resultado realizado, não-realizado e atribuição</div>
        </div>
        <div className="page-actions">
          <div className="radio-group">
            <button className="active">MTD</button>
            <button>QTD</button>
            <button>YTD</button>
            <button>Custom</button>
          </div>
          <button className="btn btn-secondary"><Icon.Download/>Exportar</button>
        </div>
      </div>

      <div className="kpi-row cols-4" style={{ marginBottom: 16 }}>
        <KPI label="P&L total MTD" value="+US$ 517.045" delta="+2,4 % vs mês anterior" deltaKind="pos" spark={[100,120,160,180,210,260,300,420,517]} sparkColor="var(--pos)"/>
        <KPI label="Realizado" value="+US$ 312.880" delta="20 contratos liquidados" deltaKind="pos"/>
        <KPI label="Não-realizado (MTM)" value="+US$ 204.165" delta="+US$ 18.460 1d" deltaKind="pos"/>
        <KPI label="Sharpe (anualizado)" value="2,18" delta="+0,21 vs trimestre" deltaKind="pos"/>
      </div>

      <div className="grid-7-5" style={{ marginBottom: 16 }}>
        <Card title="P&L diário · maio/2026" sub="Realizado + variação MTM · USD">
          <PnLChart/>
        </Card>

        <Card title="Atribuição" sub="MTD">
          <table className="tbl tbl-tight">
            <thead><tr>
              <th>Commodity</th>
              <th className="num">Realizado</th>
              <th className="num">MTM</th>
              <th className="num">Total</th>
            </tr></thead>
            <tbody>
              <tr><td className="strong"><CommodityChip code="AL-LME"/></td><td className="num">+248.120</td><td className="num">+128.025</td><td className="num strong" style={{ color: 'var(--pos)' }}>+376.145</td></tr>
              <tr><td className="strong"><CommodityChip code="USDBRL"/></td><td className="num">+58.420</td><td className="num">+85.500</td><td className="num strong" style={{ color: 'var(--pos)' }}>+143.920</td></tr>
              <tr><td className="strong"><CommodityChip code="CU-LME"/></td><td className="num">+6.340</td><td className="num">+3.200</td><td className="num strong" style={{ color: 'var(--pos)' }}>+9.540</td></tr>
              <tr><td className="strong"><CommodityChip code="ZN-LME"/></td><td className="num">0</td><td className="num">−1.260</td><td className="num strong" style={{ color: 'var(--neg)' }}>−1.260</td></tr>
              <tr><td className="strong"><CommodityChip code="NI-LME"/></td><td className="num">0</td><td className="num">−11.300</td><td className="num strong" style={{ color: 'var(--neg)' }}>−11.300</td></tr>
            </tbody>
            <tfoot>
              <tr style={{ borderTop: '2px solid var(--line-strong)' }}>
                <td className="strong">Total</td>
                <td className="num strong">+312.880</td>
                <td className="num strong">+204.165</td>
                <td className="num strong" style={{ color: 'var(--pos)' }}>+517.045</td>
              </tr>
            </tfoot>
          </table>
        </Card>
      </div>

      <Card title="Top contribuintes" sub="Contratos com maior impacto MTD" noPad>
        <table className="tbl">
          <thead><tr>
            <th>Contrato</th>
            <th>Commodity</th>
            <th>Contraparte</th>
            <th className="num">Notional (USD)</th>
            <th className="num">Preço fixo</th>
            <th className="num">Preço atual</th>
            <th className="num">P&L (USD)</th>
            <th style={{ width: 160 }}>Contribuição</th>
          </tr></thead>
          <tbody>
            <tr><td className="mono strong">CT-2026-0111</td><td><CommodityChip code="AL-LME"/></td><td>JPM</td><td className="num">5.204.000</td><td className="num">2.602,00</td><td className="num">2.645,50</td><td className="num strong" style={{ color: 'var(--pos)' }}>+87.000</td><td><Bar pct={100} kind="pos"/></td></tr>
            <tr><td className="mono strong">CT-2026-0112</td><td><CommodityChip code="USDBRL"/></td><td>BRAD</td><td className="num">7.638.000</td><td className="num">5,0920</td><td className="num">5,1240</td><td className="num strong" style={{ color: 'var(--pos)' }}>+48.000</td><td><Bar pct={55} kind="pos"/></td></tr>
            <tr><td className="mono strong">CT-2026-0117</td><td><CommodityChip code="USDBRL"/></td><td>JPM</td><td className="num">15.334.500</td><td className="num">5,1115</td><td className="num">5,1240</td><td className="num strong" style={{ color: 'var(--pos)' }}>+37.500</td><td><Bar pct={43} kind="pos"/></td></tr>
            <tr><td className="mono strong">CT-2026-0118</td><td><CommodityChip code="AL-LME"/></td><td>ITAU</td><td className="num">3.946.500</td><td className="num">2.631,00</td><td className="num">2.645,30</td><td className="num strong" style={{ color: 'var(--pos)' }}>+21.450</td><td><Bar pct={25} kind="pos"/></td></tr>
            <tr><td className="mono strong">CT-2026-0116</td><td><CommodityChip code="AL-LME"/></td><td>SANT</td><td className="num">2.365.650</td><td className="num">2.628,50</td><td className="num">2.645,50</td><td className="num strong" style={{ color: 'var(--pos)' }}>+15.300</td><td><Bar pct={18} kind="pos"/></td></tr>
            <tr><td className="mono strong">CT-2026-0110</td><td><CommodityChip code="AL-LME"/></td><td>BTG</td><td className="num">3.186.000</td><td className="num">2.655,00</td><td className="num">2.645,50</td><td className="num strong" style={{ color: 'var(--neg)' }}>−11.400</td><td><Bar pct={13} kind="neg"/></td></tr>
          </tbody>
        </table>
      </Card>
    </div>
  );
}

function PnLChart() {
  // Simple daily P&L sparkline with bars
  const data = [
    [1, 12], [2, 18], [3, -4], [4, 22], [5, 14], [6, 8], [7, -12], [8, 24], [9, 31], [10, 16],
    [11, 22], [12, 35], [13, 18], [14, -8], [15, 28], [16, 32], [17, 18], [18, 26], [19, 14], [20, 38],
    [21, 28], [22, 16], [23, -6], [24, 42], [25, 38], [26, 21], [27, 18],
  ];
  const maxAbs = Math.max(...data.map(d => Math.abs(d[1])));
  return (
    <div style={{ height: 200, position: 'relative', display: 'flex', alignItems: 'center' }}>
      <div className="row gap-1" style={{ alignItems: 'stretch', height: '100%', flex: 1, padding: '0 4px' }}>
        {data.map(([d, v]) => {
          const h = (Math.abs(v) / maxAbs) * 80;
          return (
            <div key={d} style={{ flex: 1, display: 'flex', flexDirection: 'column', justifyContent: 'center', position: 'relative', minWidth: 0 }}>
              {v >= 0 ? (
                <div style={{ marginTop: 'auto', marginBottom: '50%', height: `${h}%`, background: 'var(--pos)', borderRadius: '1px 1px 0 0' }}/>
              ) : (
                <div style={{ marginTop: '50%', marginBottom: 'auto', height: `${h}%`, background: 'var(--neg)', borderRadius: '0 0 1px 1px' }}/>
              )}
            </div>
          );
        })}
        <div style={{ position: 'absolute', left: 4, right: 4, top: '50%', height: 1, background: 'var(--line)' }}/>
      </div>
    </div>
  );
}

// ============================================================
// MTM
// ============================================================
function MTMPage() {
  return (
    <div className="page">
      <div className="page-head">
        <div>
          <h1 className="page-title">Mark-to-market e cenário</h1>
          <div className="page-sub">Marcação a mercado oficial e simulação what-if</div>
        </div>
        <div className="page-actions">
          <span className="env-badge">Marcação 27/05/2026 11:30 BST</span>
          <button className="btn btn-secondary"><Icon.Refresh/>Re-marcar</button>
        </div>
      </div>

      <div className="kpi-row cols-4" style={{ marginBottom: 16 }}>
        <KPI label="MTM oficial" value="+US$ 204.165" delta="+US$ 18.460 1d" deltaKind="pos"/>
        <KPI label="MTM cenário" value="−US$ 122.840" delta="vs base −US$ 327.005" deltaKind="neg"/>
        <KPI label="VaR 1d (95 %)" value="US$ 84.200" delta="histórico 2y · paramétrico"/>
        <KPI label="Estresse (LME −5 %)" value="−US$ 412.500" delta="cenário Banxico 2008" deltaKind="neg"/>
      </div>

      <div className="detail-grid">
        <Card title="Marcação por contrato" sub="MTM consolidado · marcação oficial 11:30 BST" noPad>
          <table className="tbl">
            <thead><tr>
              <th>Contrato</th>
              <th>Commodity</th>
              <th className="num">Qtd</th>
              <th className="num">Preço fixo</th>
              <th className="num">Preço marcação</th>
              <th className="num">Δ Preço</th>
              <th className="num">MTM (USD)</th>
              <th className="num">MTM cenário</th>
            </tr></thead>
            <tbody>
              {M.contracts.map(c => {
                const mid = c.commodity==='AL-LME'?2645.50: c.commodity==='CU-LME'?9412.00: c.commodity==='ZN-LME'?2812.50: c.commodity==='USDBRL'?5.1240:0;
                const scenarioMid = mid * 0.97;
                const scen = c.fixed_leg==='buy'?(scenarioMid-c.price)*c.qty:(c.price-scenarioMid)*c.qty;
                return (
                  <tr key={c.id}>
                    <td className="strong mono">{c.id}</td>
                    <td><CommodityChip code={c.commodity}/></td>
                    <td className="num">{c.commodity==='USDBRL'?(c.qty/1000000).toFixed(1)+' M':c.qty.toLocaleString('pt-BR')}</td>
                    <td className="num">{c.price.toLocaleString('en-US', { minimumFractionDigits: c.commodity==='USDBRL'?4:2, maximumFractionDigits: c.commodity==='USDBRL'?4:2 })}</td>
                    <td className="num">{mid.toLocaleString('en-US', { minimumFractionDigits: c.commodity==='USDBRL'?4:2, maximumFractionDigits: c.commodity==='USDBRL'?4:2 })}</td>
                    <td className="num" style={{ color: mid>c.price?'var(--pos)':'var(--neg)' }}>{mid>=c.price?'+':''}{(mid-c.price).toFixed(c.commodity==='USDBRL'?4:2)}</td>
                    <td className="num strong" style={{ color: c.mtm>=0?'var(--pos)':'var(--neg)' }}>{c.mtm>=0?'+':''}{c.mtm.toLocaleString('en-US', { maximumFractionDigits: 0 })}</td>
                    <td className="num" style={{ color: scen>=0?'var(--pos)':'var(--neg)' }}>{scen>=0?'+':''}{scen.toLocaleString('en-US', { maximumFractionDigits: 0 })}</td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </Card>

        <div className="stack gap-4" style={{ position: 'sticky', top: 72, alignSelf: 'start' }}>
          <Card title="Simulador de cenário" sub="Ajuste preços e veja o impacto agregado">
            <div className="stack gap-4">
              <ScenarioSlider label="AL-LME" base="2.645,50" delta="−3,0 %" pct={-3}/>
              <ScenarioSlider label="CU-LME" base="9.412,00" delta="0,0 %" pct={0}/>
              <ScenarioSlider label="ZN-LME" base="2.812,50" delta="−2,0 %" pct={-2}/>
              <ScenarioSlider label="USDBRL" base="5,1240" delta="+1,0 %" pct={+1}/>
            </div>
            <div className="divider"/>
            <dl className="kv">
              <dt>MTM base</dt><dd className="tabular">+US$ 204.165</dd>
              <dt>MTM cenário</dt><dd className="tabular strong" style={{ color: 'var(--neg)' }}>−US$ 122.840</dd>
              <dt>Δ cenário</dt><dd className="tabular" style={{ color: 'var(--neg)' }}>−US$ 327.005</dd>
            </dl>
            <button className="btn btn-secondary" style={{ width: '100%', marginTop: 10 }}>Salvar cenário</button>
          </Card>

          <Card title="Cenários históricos">
            <div className="stack" style={{ gap: 0 }}>
              {[
                { name: 'LME −5 % (Lehman 2008)', val: -412500, neg: true },
                { name: 'LME +3 % (rally CN 2024)', val: 246700, neg: false },
                { name: 'USDBRL +8 % (eleição 2022)', val: 142800, neg: false },
                { name: 'CU −10 % (Covid 03/2020)', val: -84300, neg: true },
              ].map(s => (
                <div key={s.name} className="row gap-3" style={{ padding: '9px 0', borderBottom: '1px solid var(--line-soft)' }}>
                  <span style={{ fontSize: 12.5, flex: 1 }}>{s.name}</span>
                  <span className="tabular strong" style={{ color: s.neg?'var(--neg)':'var(--pos)' }}>{s.val>=0?'+':''}{s.val.toLocaleString('en-US')}</span>
                </div>
              ))}
            </div>
          </Card>
        </div>
      </div>
    </div>
  );
}

function ScenarioSlider({ label, base, delta, pct }) {
  const left = 50 + pct * 8;
  return (
    <div>
      <div className="row gap-2" style={{ fontSize: 12, marginBottom: 4 }}>
        <span style={{ fontWeight: 500 }}>{label}</span>
        <span style={{ color: 'var(--muted)' }}>· base {base}</span>
        <span className="tabular" style={{ marginLeft: 'auto', color: pct<0?'var(--neg)':pct>0?'var(--pos)':'var(--muted)', fontWeight: 500 }}>{delta}</span>
      </div>
      <div style={{ height: 6, background: 'var(--surface-sunk)', borderRadius: 999, position: 'relative' }}>
        <div style={{ position: 'absolute', left: '50%', top: -2, bottom: -2, width: 1, background: 'var(--line-strong)' }}/>
        <div style={{ position: 'absolute', left: `${left}%`, top: -4, width: 14, height: 14, background: '#fff', border: '2px solid var(--navy)', borderRadius: '50%', transform: 'translateX(-50%)' }}/>
      </div>
    </div>
  );
}

// ============================================================
// MARKET DATA
// ============================================================
function MarketDataPage() {
  return (
    <div className="page">
      <div className="page-head">
        <div>
          <h1 className="page-title">Dados de mercado</h1>
          <div className="page-sub">Cotações, curvas e provedores · atualizado 09:14</div>
        </div>
        <div className="page-actions">
          <Badge kind="pos" dot>Refinitiv ao vivo</Badge>
          <button className="btn btn-secondary"><Icon.Refresh/>Atualizar</button>
        </div>
      </div>

      <div className="grid-7-5" style={{ marginBottom: 16 }}>
        <Card title="Spot" sub="Última cotação · USD" noPad>
          <table className="tbl">
            <thead><tr>
              <th>Commodity</th>
              <th className="num">Última</th>
              <th className="num">Bid</th>
              <th className="num">Ask</th>
              <th className="num">Spread</th>
              <th className="num">Δ Dia</th>
              <th>Provedor</th>
              <th>Última atualização</th>
            </tr></thead>
            <tbody>
              {M.commodities.map(c => {
                const chg = ((c.last - c.prev) / c.prev) * 100;
                const spread = c.code==='USDBRL'?0.0005:1.50;
                const bid = c.last - spread/2;
                const ask = c.last + spread/2;
                return (
                  <tr key={c.code}>
                    <td className="strong">
                      <CommodityChip code={c.code}/>
                      <div style={{ fontSize: 11, color: 'var(--muted)', fontWeight: 400, marginTop: 1 }}>{c.name}</div>
                    </td>
                    <td className="num strong">{c.last.toLocaleString('en-US', { minimumFractionDigits: c.code==='USDBRL'?4:2, maximumFractionDigits: c.code==='USDBRL'?4:2 })}</td>
                    <td className="num">{bid.toFixed(c.code==='USDBRL'?4:2)}</td>
                    <td className="num">{ask.toFixed(c.code==='USDBRL'?4:2)}</td>
                    <td className="num">{spread.toFixed(c.code==='USDBRL'?4:2)}</td>
                    <td className="num" style={{ color: chg>=0?'var(--pos)':'var(--neg)' }}>{chg>=0?'+':''}{chg.toFixed(2)} %</td>
                    <td><Badge kind="neutral">{c.code==='USDBRL'?'B3':'Refinitiv'}</Badge></td>
                    <td style={{ color: 'var(--muted)', fontSize: 12 }}>27/05 09:14:08</td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </Card>

        <Card title="Status dos provedores" sub="Disponibilidade · 24h">
          <div className="stack" style={{ gap: 8 }}>
            {[
              { p: 'Refinitiv (LSEG)', sla: 99.97, status: 'pos' },
              { p: 'LME oficial', sla: 99.91, status: 'pos' },
              { p: 'B3 (FX)', sla: 99.99, status: 'pos' },
              { p: 'Bloomberg BBG', sla: 98.40, status: 'warn' },
              { p: 'CME Group', sla: 99.85, status: 'pos' },
            ].map(p => (
              <div key={p.p} className="row gap-3" style={{ padding: '8px 0', borderBottom: '1px solid var(--line-soft)' }}>
                <div style={{ flex: 1 }}>
                  <div style={{ fontSize: 12.5, fontWeight: 500 }}>{p.p}</div>
                  <div style={{ fontSize: 11, color: 'var(--muted)' }}>SLA {p.sla.toFixed(2)} %</div>
                </div>
                <Badge kind={p.status} dot>{p.status==='pos'?'Operacional':'Atenção'}</Badge>
              </div>
            ))}
          </div>
        </Card>
      </div>

      <Card title="Curva forward · AL-LME" sub="Preço por janela de entrega · USD/t">
        <table className="tbl tbl-tight">
          <thead><tr>
            <th>Janela</th>
            <th className="num">Bid</th>
            <th className="num">Ask</th>
            <th className="num">Mid</th>
            <th className="num">Contango / Backwardation</th>
            <th>Liquidez</th>
            <th>Aberto na plataforma</th>
          </tr></thead>
          <tbody>
            {[
              ['jun/26', 2643, 2648, 2645.50, '+0,00 %', 'alta', 12],
              ['jul/26', 2651, 2657, 2654.00, '+0,32 %', 'alta', 8],
              ['ago/26', 2659, 2666, 2662.50, '+0,64 %', 'alta', 5],
              ['set/26', 2667, 2675, 2671.00, '+0,96 %', 'média', 3],
              ['out/26', 2675, 2684, 2679.50, '+1,29 %', 'média', 1],
              ['nov/26', 2683, 2693, 2688.00, '+1,61 %', 'baixa', 0],
              ['dez/26', 2691, 2702, 2696.50, '+1,93 %', 'baixa', 0],
            ].map(([w, b, a, m, c, l, n]) => (
              <tr key={w}>
                <td className="strong">{w}</td>
                <td className="num">{Number(b).toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 })}</td>
                <td className="num">{Number(a).toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 })}</td>
                <td className="num strong">{Number(m).toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 })}</td>
                <td className="num" style={{ color: 'var(--info)' }}>{c}</td>
                <td><Badge kind={l==='alta'?'pos':l==='média'?'warn':'neutral'}>{l}</Badge></td>
                <td className="num">{n}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </Card>
    </div>
  );
}

// ============================================================
// APPROVALS
// ============================================================
function ApprovalsPage() {
  return (
    <div className="page">
      <div className="page-head">
        <div>
          <h1 className="page-title">Aprovações</h1>
          <div className="page-sub">Workflow de aprovações pendentes · 2 itens aguardando você</div>
        </div>
        <div className="page-actions">
          <button className="btn btn-secondary">Histórico</button>
        </div>
      </div>

      <div className="kpi-row cols-4" style={{ marginBottom: 16 }}>
        <KPI label="Aguardando você" value="2" delta="SLA médio 2h · 1 vencendo" deltaKind="neg"/>
        <KPI label="Aprovadas (mês)" value="38" delta="taxa de aprovação 95 %" deltaKind="pos"/>
        <KPI label="Tempo médio" value="01:18" unit="h:m" delta="−00:24 vs mês anterior" deltaKind="pos"/>
        <KPI label="Rejeições" value="2" delta="motivo: fora de alçada"/>
      </div>

      <div className="stack gap-3">
        <ApprovalCard
          urgent
          id="APR-2026-0098"
          title="Ordem fora da alçada do trader"
          desc="ORD-2026-0420 · AL-LME 2.500t buy @ 2.638,50 · JPM · Notional US$ 6,6 M (acima do limite trader US$ 5 M)"
          requestor="M. Santos · Trader"
          when="aguardando há 1h 42min"
          policy="Política Hedge §4.2"
        />
        <ApprovalCard
          id="APR-2026-0097"
          title="Novo limite de contraparte"
          desc="Aumento de US$ 6,5 M → US$ 9,0 M · Citi Brasil · revisão semestral"
          requestor="L. Ferreira · Risco"
          when="aguardando há 12h"
          policy="Política Crédito §8.1"
        />
        <ApprovalCard
          approved
          id="APR-2026-0096"
          title="Contrato CT-2026-0118"
          desc="AL-LME 1.500t buy · ITAU · Notional US$ 3,9 M"
          requestor="A. Costa · Aprovador"
          when="aprovada ontem 17:55"
          policy="Política Hedge §4.1"
        />
      </div>
    </div>
  );
}

function ApprovalCard({ urgent, approved, id, title, desc, requestor, when, policy }) {
  return (
    <div className="card" style={{ padding: 18, display: 'grid', gridTemplateColumns: '4px 1fr auto', gap: 16, alignItems: 'center' }}>
      <div style={{ alignSelf: 'stretch', background: urgent ? 'var(--neg)' : approved ? 'var(--pos)' : 'var(--orange)', borderRadius: 2 }}/>
      <div>
        <div className="row gap-3" style={{ marginBottom: 4 }}>
          {urgent && <Badge kind="neg" dot>SLA vencendo</Badge>}
          {approved && <Badge kind="pos" dot>Aprovado</Badge>}
          {!urgent && !approved && <Badge kind="warn" dot>Pendente</Badge>}
          <span className="mono" style={{ fontSize: 11, color: 'var(--muted)' }}>{id}</span>
          <span style={{ fontSize: 11, color: 'var(--muted)' }}>· {policy}</span>
        </div>
        <div style={{ fontSize: 14, fontWeight: 500, marginBottom: 4 }}>{title}</div>
        <div style={{ fontSize: 12.5, color: 'var(--ink-3)' }}>{desc}</div>
        <div style={{ fontSize: 11.5, color: 'var(--muted)', marginTop: 6 }}>{requestor} · {when}</div>
      </div>
      <div className="row gap-2">
        {!approved && <button className="btn btn-secondary">Ver detalhes</button>}
        {!approved && <button className="btn btn-danger">Rejeitar</button>}
        {!approved && <button className="btn btn-primary"><Icon.ShieldCheck/>Aprovar</button>}
        {approved && <button className="btn btn-secondary">Ver registro</button>}
      </div>
    </div>
  );
}

// ============================================================
// AUDIT
// ============================================================
function AuditPage() {
  return (
    <div className="page">
      <div className="page-head">
        <div>
          <h1 className="page-title">Auditoria</h1>
          <div className="page-sub">Trilha imutável de eventos · retenção 7 anos · CVM-compliant</div>
        </div>
        <div className="page-actions">
          <button className="btn btn-secondary"><Icon.Download/>Exportar trilha (CSV)</button>
        </div>
      </div>

      <Card noPad>
        <div className="tbl-tools">
          <button className="chip"><Icon.Filter/>Período · hoje</button>
          <button className="chip"><Icon.Filter/>Usuário · todos</button>
          <button className="chip"><Icon.Filter/>Ação · todas</button>
          <button className="chip"><Icon.Filter/>Entidade</button>
          <div className="sp"/>
          <span style={{ fontSize: 11.5, color: 'var(--muted)' }}>1.247 eventos · 8 usuários ativos</span>
        </div>
        <table className="tbl">
          <thead><tr>
            <th style={{ width: 160 }}>Timestamp</th>
            <th>Usuário</th>
            <th>Papel</th>
            <th>Ação</th>
            <th>Entidade</th>
            <th>Detalhe</th>
            <th>Hash</th>
          </tr></thead>
          <tbody>
            {M.auditLog.map((e, i) => (
              <tr key={i}>
                <td className="mono tabular" style={{ fontSize: 12, color: 'var(--ink-3)' }}>{e.ts}</td>
                <td className="strong">{e.user}</td>
                <td><Badge kind={e.role==='System'?'neutral':e.role==='Risco'?'info':e.role==='Aprovador'?'warn':e.role==='Trader'?'pos':'neutral'}>{e.role}</Badge></td>
                <td className="mono" style={{ fontSize: 12 }}>{e.action}</td>
                <td className="mono">{e.entity}</td>
                <td style={{ color: 'var(--ink-3)' }}>{e.detail}</td>
                <td className="mono" style={{ fontSize: 11, color: 'var(--muted-2)' }}>{('0x'+Math.abs(i*7919+13).toString(16)).padEnd(10,'a')}…</td>
              </tr>
            ))}
          </tbody>
        </table>
        <Pager from={1} to={10} total={1247}/>
      </Card>
    </div>
  );
}

Object.assign(window, { CashflowPage, PnLPage, MTMPage, MarketDataPage, ApprovalsPage, AuditPage });
})();
