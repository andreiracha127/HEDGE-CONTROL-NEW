/* Shell: Sidebar + Topbar + simple hash router + shared icons */

const Icon = {
  Home: () => <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.7" strokeLinecap="round" strokeLinejoin="round"><path d="M3 11l9-8 9 8"/><path d="M5 10v10h14V10"/><path d="M10 20v-6h4v6"/></svg>,
  Layers: () => <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.7" strokeLinecap="round" strokeLinejoin="round"><path d="M12 3l9 5-9 5-9-5 9-5z"/><path d="M3 13l9 5 9-5"/><path d="M3 17l9 5 9-5"/></svg>,
  Clipboard: () => <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.7" strokeLinecap="round" strokeLinejoin="round"><rect x="6" y="5" width="12" height="16" rx="1.5"/><rect x="9" y="3" width="6" height="4" rx="1"/><path d="M9 11h6M9 14h6M9 17h3"/></svg>,
  RFQ: () => <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.7" strokeLinecap="round" strokeLinejoin="round"><path d="M5 4h10l4 4v12H5z"/><path d="M15 4v4h4"/><path d="M9 12l2 2 4-4"/></svg>,
  FileSign: () => <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.7" strokeLinecap="round" strokeLinejoin="round"><path d="M5 4h10l4 4v12H5z"/><path d="M15 4v4h4"/><path d="M8 14l2 2 5-5"/></svg>,
  Users: () => <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.7" strokeLinecap="round" strokeLinejoin="round"><circle cx="9" cy="9" r="3.2"/><path d="M3 20c.6-3.2 3-5 6-5s5.4 1.8 6 5"/><circle cx="17" cy="8" r="2.5"/><path d="M16 14c2 0 4 1 4.5 3.5"/></svg>,
  Coins: () => <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.7" strokeLinecap="round" strokeLinejoin="round"><ellipse cx="8" cy="8" rx="5" ry="2.5"/><path d="M3 8v4c0 1.4 2.2 2.5 5 2.5s5-1.1 5-2.5V8"/><ellipse cx="16" cy="14" rx="5" ry="2.5"/><path d="M11 14v4c0 1.4 2.2 2.5 5 2.5s5-1.1 5-2.5v-4"/></svg>,
  Chart: () => <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.7" strokeLinecap="round" strokeLinejoin="round"><path d="M4 4v16h16"/><path d="M7 14l3-3 3 3 5-7"/></svg>,
  Scale: () => <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.7" strokeLinecap="round" strokeLinejoin="round"><path d="M12 3v18M5 21h14"/><path d="M6 7l-3 6h6z"/><path d="M18 7l3 6h-6z"/><path d="M5 7h14"/></svg>,
  Globe: () => <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.7" strokeLinecap="round" strokeLinejoin="round"><circle cx="12" cy="12" r="9"/><path d="M3 12h18"/><path d="M12 3c2.5 3 4 6 4 9s-1.5 6-4 9c-2.5-3-4-6-4-9s1.5-6 4-9z"/></svg>,
  ShieldCheck: () => <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.7" strokeLinecap="round" strokeLinejoin="round"><path d="M12 3l8 3v6c0 4.5-3.2 8.4-8 9-4.8-.6-8-4.5-8-9V6z"/><path d="M9 12l2 2 4-4"/></svg>,
  Bell: () => <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.7" strokeLinecap="round" strokeLinejoin="round"><path d="M6 9a6 6 0 1112 0c0 5 2 6 2 6H4s2-1 2-6z"/><path d="M10 19a2 2 0 004 0"/></svg>,
  Search: () => <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round"><circle cx="11" cy="11" r="6"/><path d="M16 16l4 4"/></svg>,
  Plus: () => <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round"><path d="M12 5v14M5 12h14"/></svg>,
  ChevronDown: () => <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round"><path d="M6 9l6 6 6-6"/></svg>,
  ChevronRight: () => <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round"><path d="M9 6l6 6-6 6"/></svg>,
  Filter: () => <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.7" strokeLinecap="round" strokeLinejoin="round"><path d="M3 5h18l-7 9v6l-4-2v-4z"/></svg>,
  Download: () => <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.7" strokeLinecap="round" strokeLinejoin="round"><path d="M12 4v12"/><path d="M7 11l5 5 5-5"/><path d="M5 20h14"/></svg>,
  Refresh: () => <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.7" strokeLinecap="round" strokeLinejoin="round"><path d="M3 12a9 9 0 0115-6.7L21 8"/><path d="M21 4v4h-4"/><path d="M21 12a9 9 0 01-15 6.7L3 16"/><path d="M3 20v-4h4"/></svg>,
  More: () => <svg viewBox="0 0 24 24" fill="currentColor"><circle cx="6" cy="12" r="1.5"/><circle cx="12" cy="12" r="1.5"/><circle cx="18" cy="12" r="1.5"/></svg>,
  Up: () => <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round"><path d="M7 14l5-5 5 5"/></svg>,
  Down: () => <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round"><path d="M7 10l5 5 5-5"/></svg>,
  Settings: () => <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.7" strokeLinecap="round" strokeLinejoin="round"><circle cx="12" cy="12" r="3"/><path d="M19.4 15a1.7 1.7 0 00.3 1.8l.1.1a2 2 0 11-2.8 2.8l-.1-.1a1.7 1.7 0 00-1.8-.3 1.7 1.7 0 00-1 1.5V21a2 2 0 01-4 0v-.1a1.7 1.7 0 00-1.1-1.5 1.7 1.7 0 00-1.8.3l-.1.1a2 2 0 11-2.8-2.8l.1-.1a1.7 1.7 0 00.3-1.8 1.7 1.7 0 00-1.5-1H3a2 2 0 010-4h.1a1.7 1.7 0 001.5-1 1.7 1.7 0 00-.3-1.8L4.2 7a2 2 0 112.8-2.8l.1.1a1.7 1.7 0 001.8.3H9a1.7 1.7 0 001-1.5V3a2 2 0 014 0v.1a1.7 1.7 0 001 1.5 1.7 1.7 0 001.8-.3l.1-.1a2 2 0 112.8 2.8l-.1.1a1.7 1.7 0 00-.3 1.8V9c.6.4 1 1 1 1.7"/></svg>,
  Bolt: () => <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.7" strokeLinecap="round" strokeLinejoin="round"><path d="M13 3L4 14h7l-1 7 9-11h-7z"/></svg>,
  ExternalLink: () => <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.7" strokeLinecap="round" strokeLinejoin="round"><path d="M14 4h6v6"/><path d="M20 4l-8 8"/><path d="M19 13v6H5V5h6"/></svg>,
  ArrowLeft: () => <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round"><path d="M15 6l-6 6 6 6"/><path d="M9 12h12"/></svg>,
  ArrowRight: () => <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round"><path d="M9 6l6 6-6 6"/><path d="M15 12H3"/></svg>,
  Lock: () => <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.7" strokeLinecap="round" strokeLinejoin="round"><rect x="5" y="11" width="14" height="9" rx="2"/><path d="M8 11V7a4 4 0 018 0v4"/></svg>,
  Info: () => <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.7" strokeLinecap="round" strokeLinejoin="round"><circle cx="12" cy="12" r="9"/><path d="M12 11v5M12 8v.5"/></svg>,
  Doc: () => <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.7" strokeLinecap="round" strokeLinejoin="round"><path d="M5 4h9l5 5v11H5z"/><path d="M14 4v5h5"/></svg>,
};

const Logo = ({ size = 26 }) => (
  <svg width={size} height={size} viewBox="0 0 32 32" className="logo-mark">
    <rect x="0" y="0" width="32" height="32" rx="6" fill="var(--orange)"/>
    <path d="M8 22 L14 8 L16 8 L18 12 L13 12 L11 16 L21 16 L18 22 Z" fill="#fff"/>
  </svg>
);

const NAV = [
  {
    label: 'Operação',
    items: [
      { key: 'dashboard', label: 'Visão geral', icon: <Icon.Home/>, badge: null },
      { key: 'exposures', label: 'Exposições',   icon: <Icon.Layers/>, badge: null },
      { key: 'orders',    label: 'Ordens',       icon: <Icon.Clipboard/>, badge: '24' },
      { key: 'rfq',       label: 'RFQ',          icon: <Icon.RFQ/>, badge: '3' },
      { key: 'contracts', label: 'Contratos',    icon: <Icon.FileSign/>, badge: null },
      { key: 'counterparties', label: 'Contrapartes', icon: <Icon.Users/>, badge: null },
    ]
  },
  {
    label: 'Análise',
    items: [
      { key: 'cashflow',  label: 'Fluxo de caixa', icon: <Icon.Coins/>, badge: null },
      { key: 'pnl',       label: 'P&L',           icon: <Icon.Chart/>, badge: null },
      { key: 'mtm',       label: 'MTM e cenário', icon: <Icon.Scale/>, badge: null },
      { key: 'market',    label: 'Dados de mercado', icon: <Icon.Globe/>, badge: null },
    ]
  },
  {
    label: 'Governança',
    items: [
      { key: 'approvals', label: 'Aprovações',  icon: <Icon.ShieldCheck/>, badge: '2' },
      { key: 'audit',     label: 'Auditoria',    icon: <Icon.Doc/>, badge: null },
    ]
  },
];

function Sidebar({ route, navigate }) {
  return (
    <aside className="sidebar">
      <div className="sidebar-brand">
        <Logo size={26}/>
        <div>
          <div className="sidebar-brand-name">Alcast Hedge</div>
          <div className="sidebar-brand-sub">Hedge Control Platform</div>
        </div>
      </div>

      {NAV.map(section => (
        <div className="sidebar-section" key={section.label}>
          <div className="sidebar-section-label">{section.label}</div>
          <nav className="sidebar-nav">
            {section.items.map(it => (
              <button
                key={it.key}
                data-label={it.label}
                className={"sb-item " + (route.page === it.key ? 'active' : '')}
                onClick={() => navigate(it.key)}
              >
                {it.icon}
                <span>{it.label}</span>
                {it.badge && <span className="sb-pill">{it.badge}</span>}
              </button>
            ))}
          </nav>
        </div>
      ))}

      <div className="sb-foot">
        <div className="sb-foot-avatar">MS</div>
        <div>
          <div className="sb-foot-name">Mariana Santos</div>
          <div className="sb-foot-role">Trader · Mesa Metais</div>
        </div>
      </div>
    </aside>
  );
}

function Topbar({ crumbs, mode }) {
  return (
    <header className="topbar">
      <nav className="crumbs">
        {crumbs.map((c, i) => (
          <React.Fragment key={i}>
            {i > 0 && <span className="sep">/</span>}
            <span className={i === crumbs.length - 1 ? 'cur' : ''}>{c}</span>
          </React.Fragment>
        ))}
      </nav>
      <div className="topbar-search">
        <Icon.Search/>
        <input placeholder="Buscar RFQ, ordem, contrato ou contraparte…"/>
      </div>
      <div className="topbar-actions">
        <span className={"env-badge " + (mode === 'prod' ? 'prod' : '')}>{mode === 'prod' ? 'Produção' : 'Homologação'}</span>
        <button className="icon-btn" title="Notificações"><Icon.Bell/><span className="dot"></span></button>
        <button className="icon-btn" title="Configurações"><Icon.Settings/></button>
      </div>
    </header>
  );
}

// Simple hash-router
function useRoute() {
  const parse = () => {
    const h = (window.location.hash || '#/dashboard').replace(/^#/, '');
    const parts = h.split('/').filter(Boolean);
    const page = parts[0] || 'dashboard';
    const sub = parts.slice(1);
    return { page, sub };
  };
  const [route, setRoute] = React.useState(parse());
  React.useEffect(() => {
    const onChange = () => setRoute(parse());
    window.addEventListener('hashchange', onChange);
    return () => window.removeEventListener('hashchange', onChange);
  }, []);
  const navigate = (path) => {
    if (typeof path === 'string') {
      window.location.hash = path.startsWith('/') ? '#' + path : '#/' + path;
    }
  };
  return [route, navigate];
}

function InfoTip({ children, side = 'top', width = 240 }) {
  const [open, setOpen] = React.useState(false);
  const ref = React.useRef(null);
  React.useEffect(() => {
    if (!open) return;
    const onDoc = (e) => { if (ref.current && !ref.current.contains(e.target)) setOpen(false); };
    document.addEventListener('mousedown', onDoc);
    return () => document.removeEventListener('mousedown', onDoc);
  }, [open]);
  return (
    <span className={"tip " + (open ? 'open' : '')} ref={ref} onClick={(e)=>{ e.stopPropagation(); setOpen(o=>!o); }}>
      <span className="tip-icon" aria-label="Mais informações" role="button" tabIndex={0}>i</span>
      <span className="tip-pop" data-side={side} style={{ width }} onClick={(e)=>e.stopPropagation()}>{children}</span>
    </span>
  );
}

Object.assign(window, { Icon, Logo, Sidebar, Topbar, useRoute, NAV, InfoTip });
