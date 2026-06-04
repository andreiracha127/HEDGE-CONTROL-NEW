/* Main app — router + tweaks panel */

const TWEAK_DEFAULTS = /*EDITMODE-BEGIN*/{
  "density": "regular",
  "theme": "default",
  "nav": "expanded"
}/*EDITMODE-END*/;

function App() {
  const [route, navigate] = useRoute();
  const [t, setTweak] = useTweaks(TWEAK_DEFAULTS);

  // Apply tweaks as data-attributes on <html> so CSS variants can hook in.
  React.useEffect(() => {
    const html = document.documentElement;
    html.setAttribute('data-density', t.density || 'regular');
    html.setAttribute('data-theme', t.theme || 'default');
    html.setAttribute('data-nav', t.nav || 'expanded');
  }, [t.density, t.theme, t.nav]);

  const crumbsFor = (route) => {
    const titles = {
      dashboard: ['Operação', 'Visão geral'],
      exposures: ['Operação', 'Exposições'],
      orders: ['Operação', 'Ordens'],
      rfq: ['Operação', 'RFQ'],
      contracts: ['Operação', 'Contratos'],
      counterparties: ['Operação', 'Contrapartes'],
      cashflow: ['Análise', 'Fluxo de caixa'],
      pnl: ['Análise', 'P&L'],
      mtm: ['Análise', 'MTM e cenário'],
      market: ['Análise', 'Dados de mercado'],
      approvals: ['Governança', 'Aprovações'],
      audit: ['Governança', 'Auditoria'],
    };
    let c = titles[route.page] || ['—'];
    if (route.page === 'rfq' && route.sub[0] === 'new') c = ['Operação', 'RFQ', 'Nova'];
    if (route.page === 'rfq' && route.sub[0] && route.sub[0] !== 'new') c = ['Operação', 'RFQ', route.sub[0]];
    if (route.page === 'orders' && route.sub[0] === 'new') c = ['Operação', 'Ordens', 'Nova'];
    if (route.page === 'contracts' && route.sub[0]) c = ['Operação', 'Contratos', route.sub[0]];
    if (route.page === 'counterparties' && route.sub[0] === 'new') c = ['Operação', 'Contrapartes', 'Nova'];
    if (route.page === 'counterparties' && route.sub[0] && route.sub[0] !== 'new') c = ['Operação', 'Contrapartes', route.sub[0]];
    return c;
  };

  let content;
  if (route.page === 'dashboard') content = <DashboardPage/>;
  else if (route.page === 'exposures') content = <ExposuresPage/>;
  else if (route.page === 'orders' && route.sub[0] === 'new') content = <OrderNewPage/>;
  else if (route.page === 'orders') content = <OrdersPage/>;
  else if (route.page === 'rfq' && route.sub[0] === 'new') content = <RFQNewPage/>;
  else if (route.page === 'rfq' && route.sub[0]) content = <RFQDetailPage id={route.sub[0]}/>;
  else if (route.page === 'rfq') content = <RFQListPage/>;
  else if (route.page === 'contracts' && route.sub[0]) content = <ContractDetailPage id={route.sub[0]}/>;
  else if (route.page === 'contracts') content = <ContractsPage/>;
  else if (route.page === 'counterparties' && route.sub[0] === 'new') content = <CounterpartyNewPage/>;
  else if (route.page === 'counterparties' && route.sub[0]) content = <CounterpartyDetailPage id={route.sub[0]}/>;
  else if (route.page === 'counterparties') content = <CounterpartiesPage/>;
  else if (route.page === 'cashflow') content = <CashflowPage/>;
  else if (route.page === 'pnl') content = <PnLPage/>;
  else if (route.page === 'mtm') content = <MTMPage/>;
  else if (route.page === 'market') content = <MarketDataPage/>;
  else if (route.page === 'approvals') content = <ApprovalsPage/>;
  else if (route.page === 'audit') content = <AuditPage/>;
  else content = <DashboardPage/>;

  return (
    <React.Fragment>
      <div className="app">
        <Sidebar route={route} navigate={(k) => navigate('/' + k)}/>
        <div className="main">
          <Topbar crumbs={crumbsFor(route)} mode="homolog"/>
          {content}
        </div>
      </div>

      <TweaksPanel>
        <TweakSection label="Layout"/>
        <TweakRadio
          label="Densidade"
          value={t.density}
          options={[
            { label: 'Compacto', value: 'compact' },
            { label: 'Regular', value: 'regular' },
            { label: 'Confort.', value: 'comfy' },
          ]}
          onChange={(v) => setTweak('density', v)}
        />
        <TweakRadio
          label="Sidebar"
          value={t.nav}
          options={[
            { label: 'Padrão', value: 'expanded' },
            { label: 'Trilho', value: 'rail' },
          ]}
          onChange={(v) => setTweak('nav', v)}
        />

        <TweakSection label="Identidade visual"/>
        <TweakSelect
          label="Tema"
          value={t.theme}
          options={[
            { label: 'Institucional — Netz (navy + laranja)', value: 'default' },
            { label: 'Monocromático — sem laranja, slate + azul aço', value: 'mono' },
            { label: 'Terminal — dark mode trader desk', value: 'terminal' },
          ]}
          onChange={(v) => setTweak('theme', v)}
        />
      </TweaksPanel>
    </React.Fragment>
  );
}

const root = ReactDOM.createRoot(document.getElementById('root'));
root.render(<App/>);
