import { useCallback, useEffect, useMemo, useRef, useState, type ReactNode } from 'react';
import {
  ArrowDown,
  ArrowDownLeft,
  ArrowDownToLine,
  ArrowRight,
  ArrowUpRight,
  BookOpen,
  Check,
  CheckCheck,
  ChevronDown,
  ChevronLeft,
  ChevronRight,
  CircleCheck,
  CircleHelp,
  FileText,
  FolderOpen,
  Layers3,
  LayoutDashboard,
  ListFilter,
  LoaderCircle,
  Menu,
  Plus,
  Search,
  ShieldCheck,
  Sparkles,
  Tags,
  Trash2,
  Upload,
  WandSparkles,
  X,
} from 'lucide-react';
import { ApiError, dateLabel, json, money, request } from './api';
import { CategoryPill, Modal, ReviewModal, UploadModal } from './components';
import type { Workspace } from './types';

type View = 'overview' | 'transactions' | 'categories' | 'rules' | 'statements';
type Tab = 'all' | 'review' | 'ready';
const views: View[] = ['overview', 'transactions', 'categories', 'rules', 'statements'];
const viewFromHash = (): View => views.find((v) => window.location.hash === `#${v}`) ?? 'overview';
const expenseIds = ['software', 'travel', 'office', 'marketing', 'professional', 'meals', 'fees'];

function IconTile({ children, tone = '' }: { children: ReactNode; tone?: string }) {
  return <span className={`icon-tile ${tone}`}>{children}</span>;
}

export default function App() {
  const [view, setView] = useState<View>(viewFromHash);
  const [data, setData] = useState<Workspace | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const [statementId, setStatementId] = useState('');
  const [currency, setCurrency] = useState('USD');
  const [tab, setTab] = useState<Tab>('all');
  const [query, setQuery] = useState('');
  const [category, setCategory] = useState('all');
  const [flow, setFlow] = useState('all');
  const [sort, setSort] = useState('date-desc');
  const [page, setPage] = useState(1);
  const [selected, setSelected] = useState<Set<string>>(new Set());
  const [uploadOpen, setUploadOpen] = useState(false);
  const [helpOpen, setHelpOpen] = useState(false);
  const [reviewId, setReviewId] = useState<string | null>(null);
  const [bulkOpen, setBulkOpen] = useState(false);
  const [bulkCategory, setBulkCategory] = useState('office');
  const [bulkBusy, setBulkBusy] = useState(false);
  const [bulkError, setBulkError] = useState('');
  const [exportOpen, setExportOpen] = useState(false);
  const [mobileOpen, setMobileOpen] = useState(false);
  const [isMobile, setIsMobile] = useState(() => window.matchMedia('(max-width: 760px)').matches);
  const [demoBusy, setDemoBusy] = useState(false);
  const [removeId, setRemoveId] = useState<string | null>(null);
  const [removeBusy, setRemoveBusy] = useState(false);
  const [removeError, setRemoveError] = useState('');
  const [toast, setToast] = useState('');
  const searchRef = useRef<HTMLInputElement>(null);
  const exportRef = useRef<HTMLDivElement>(null);
  const requestSequence = useRef(0);
  const sidebarRef = useRef<HTMLDivElement>(null);
  const menuTriggerRef = useRef<HTMLButtonElement>(null);
  const pageSize = 10;

  const load = useCallback(async () => {
    const sequence = ++requestSequence.current;
    setError('');
    try {
      const params = new URLSearchParams({ currency });
      if (statementId) params.set('statement_id', statementId);
      const result = await request<Workspace>(`/workspace?${params}`);
      if (sequence === requestSequence.current) {
        setData(result);
        return result;
      }
    } catch (err) {
      if (sequence === requestSequence.current) setError((err as Error).message);
    } finally {
      if (sequence === requestSequence.current) setLoading(false);
    }
  }, [statementId, currency]);

  useEffect(() => {
    void load();
  }, [load]);
  useEffect(() => {
    const media = window.matchMedia('(max-width: 760px)');
    const resize = () => {
      setIsMobile(media.matches);
      if (!media.matches) setMobileOpen(false);
    };
    media.addEventListener('change', resize);
    return () => media.removeEventListener('change', resize);
  }, []);
  useEffect(() => {
    if (!isMobile || !mobileOpen) return;
    const sidebar = sidebarRef.current!;
    const controls = () =>
      [...sidebar.querySelectorAll<HTMLElement>('a[href], button:not(:disabled)')].filter(
        (element) => element.getClientRects().length > 0,
      );
    (sidebar.querySelector<HTMLElement>('[aria-current="page"]') ?? controls()[0])?.focus();
    const trap = (event: KeyboardEvent) => {
      if (event.key !== 'Tab') return;
      const items = controls(),
        first = items[0],
        last = items[items.length - 1];
      if (event.shiftKey && document.activeElement === first) {
        event.preventDefault();
        last?.focus();
      } else if (!event.shiftKey && document.activeElement === last) {
        event.preventDefault();
        first?.focus();
      }
    };
    sidebar.addEventListener('keydown', trap);
    return () => {
      sidebar.removeEventListener('keydown', trap);
      menuTriggerRef.current?.focus();
    };
  }, [isMobile, mobileOpen]);
  useEffect(() => {
    const onHash = () => {
      setView(viewFromHash());
      setMobileOpen(false);
    };
    window.addEventListener('hashchange', onHash);
    return () => window.removeEventListener('hashchange', onHash);
  }, []);
  useEffect(() => {
    setPage(1);
    setSelected(new Set());
  }, [statementId, currency, query, category, flow, tab, view]);
  useEffect(() => {
    if (!toast) return;
    const timer = window.setTimeout(() => setToast(''), 4500);
    return () => window.clearTimeout(timer);
  }, [toast]);
  useEffect(() => {
    const keyboard = (event: KeyboardEvent) => {
      if (
        event.key === '/' &&
        !(
          event.target instanceof HTMLInputElement ||
          event.target instanceof HTMLTextAreaElement ||
          event.target instanceof HTMLSelectElement
        ) &&
        !document.querySelector('dialog[open]')
      ) {
        event.preventDefault();
        navigate('transactions');
        window.requestAnimationFrame(() => searchRef.current?.focus());
      }
      if (event.key === 'Escape') {
        setExportOpen(false);
        setMobileOpen(false);
      }
    };
    const click = (event: MouseEvent) => {
      if (!exportRef.current?.contains(event.target as Node)) setExportOpen(false);
    };
    window.addEventListener('keydown', keyboard);
    window.addEventListener('click', click);
    return () => {
      window.removeEventListener('keydown', keyboard);
      window.removeEventListener('click', click);
    };
  }, []);

  const navigate = (next: View) => {
    window.location.hash = next;
    setView(next);
    setMobileOpen(false);
  };
  const scopedStatement = data?.statements.find((s) => s.id === statementId);
  const summary = data?.summary;
  const actualCurrency = summary?.currency ?? currency;
  const reviewRow = data?.transactions.find((t) => t.id === reviewId);
  const percentage = summary?.total ? Math.round((summary.ready_count / summary.total) * 100) : 0;

  const filtered = useMemo(() => {
    const result = (data?.transactions ?? []).filter(
      (t) =>
        (tab === 'all' || (tab === 'review' ? t.needs_review : !t.needs_review)) &&
        (category === 'all' || t.category === category) &&
        (flow === 'all' || t.flow === flow) &&
        (!query ||
          `${t.description} ${t.merchant_key} ${t.note}`
            .toLowerCase()
            .includes(query.toLowerCase())),
    );
    return result.sort((a, b) =>
      sort === 'date-asc'
        ? a.date.localeCompare(b.date)
        : sort === 'amount-desc'
          ? b.amount_minor - a.amount_minor
          : sort === 'amount-asc'
            ? a.amount_minor - b.amount_minor
            : b.date.localeCompare(a.date),
    );
  }, [data, tab, category, flow, query, sort]);
  const maxPage = Math.max(1, Math.ceil(filtered.length / pageSize));
  const currentPage = Math.min(page, maxPage);
  const pageRows = filtered.slice((currentPage - 1) * pageSize, currentPage * pageSize);
  const selectable = pageRows.filter((t) => !t.duplicate && t.amount_minor !== 0);
  const selectedRows = (data?.transactions ?? []).filter((t) => selected.has(t.id));
  const bulkChoices = (data?.categories ?? []).filter(
    (c) =>
      c.id !== 'uncategorized' &&
      (c.id !== 'income' ||
        (selectedRows.length > 0 && selectedRows.every((t) => t.amount_minor > 0))),
  );
  const effectiveBulkCategory = bulkChoices.some((c) => c.id === bulkCategory)
    ? bulkCategory
    : (bulkChoices.find((c) => c.id === 'office')?.id ?? bulkChoices[0]?.id ?? '');
  const validSelection =
    selectedRows.length > 0 && selectedRows.length === selected.size && selected.size <= 200;
  const allSelected = selectable.length > 0 && selectable.every((t) => selected.has(t.id));

  function resetFilters() {
    setQuery('');
    setCategory('all');
    setFlow('all');
    setTab('all');
    setSort('date-desc');
  }
  function openHelp() {
    if (isMobile && mobileOpen) {
      setMobileOpen(false);
      window.requestAnimationFrame(() => setHelpOpen(true));
    } else setHelpOpen(true);
  }
  function openCategory(id: string) {
    resetFilters();
    setCategory(id);
    navigate('transactions');
  }
  function toggle(id: string) {
    setSelected((previous) => {
      const next = new Set(previous);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  }

  async function demo() {
    setDemoBusy(true);
    setError('');
    try {
      const result = await request<{ statement_id: string }>('/demo', { method: 'POST' });
      setCurrency('USD');
      setStatementId(result.statement_id);
      resetFilters();
      setToast('Sample statement ready');
    } catch (err) {
      if (err instanceof ApiError && err.statementId) {
        setCurrency('USD');
        setStatementId(err.statementId);
        resetFilters();
        setToast('Sample statement opened');
      } else setError((err as Error).message);
    } finally {
      setDemoBusy(false);
    }
  }

  async function saved(next: boolean) {
    const result = await load();
    if (!result) return;
    const remaining = result.transactions.filter((t) => t.needs_review && t.id !== reviewId);
    setReviewId(next && remaining.length ? remaining[0].id : null);
    setToast('Transaction confirmed');
  }

  async function bulkSave() {
    if (!validSelection || !effectiveBulkCategory) {
      setBulkError('The selection changed. Close this dialog and select the transactions again.');
      return;
    }
    setBulkBusy(true);
    setBulkError('');
    try {
      const result = await request<{ updated: number }>(
        '/review-batch',
        json({
          category: effectiveBulkCategory,
          items: selectedRows.map((t) => ({ id: t.id, version: t.version })),
        }),
      );
      await load();
      setSelected(new Set());
      setBulkOpen(false);
      setToast(`${result.updated} transactions confirmed`);
    } catch (err) {
      setBulkError((err as Error).message);
    } finally {
      setBulkBusy(false);
    }
  }

  async function removeRule(id: string) {
    try {
      await request(`/rules/${id}`, { method: 'DELETE' });
      await load();
      setToast('Merchant rule removed');
    } catch (err) {
      setError((err as Error).message);
    }
  }

  async function removeStatement() {
    if (!removeId) return;
    setRemoveBusy(true);
    setRemoveError('');
    try {
      await request(`/statements/${removeId}`, { method: 'DELETE' });
      setRemoveId(null);
      setSelected(new Set());
      if (removeId === statementId) setStatementId('');
      else await load();
      setToast('Statement removed');
    } catch (err) {
      setRemoveError((err as Error).message);
    } finally {
      setRemoveBusy(false);
    }
  }

  function download(kind: string, confirmed = false) {
    const params = new URLSearchParams({
      currency: actualCurrency,
      kind,
      confirmed_only: String(confirmed),
    });
    if (statementId) params.set('statement_id', statementId);
    const anchor = document.createElement('a');
    anchor.href = `/api/export?${params}`;
    anchor.download = `folio-${kind}.csv`;
    anchor.click();
    setExportOpen(false);
  }

  const navItems: { id: View; name: string; icon: ReactNode }[] = [
    { id: 'overview', name: 'Overview', icon: <LayoutDashboard size={18} /> },
    { id: 'transactions', name: 'Transactions', icon: <ArrowDownLeft size={19} /> },
    { id: 'categories', name: 'Categories', icon: <Tags size={18} /> },
    { id: 'rules', name: 'Merchant rules', icon: <WandSparkles size={18} /> },
    { id: 'statements', name: 'Statements', icon: <FileText size={18} /> },
  ];

  return (
    <div className="app-shell">
      <a
        className="skip-link"
        href="#main"
        inert={isMobile && mobileOpen}
        onClick={(event) => {
          event.preventDefault();
          document.getElementById('main')?.focus();
        }}
      >
        Skip to content
      </a>
      {mobileOpen && (
        <button
          className="sidebar-backdrop"
          aria-label="Close navigation"
          aria-hidden="true"
          tabIndex={-1}
          onClick={() => setMobileOpen(false)}
        />
      )}
      <div
        ref={sidebarRef}
        className={`sidebar ${mobileOpen ? 'sidebar-open' : ''}`}
        inert={isMobile && !mobileOpen}
        aria-hidden={isMobile && !mobileOpen}
        role={isMobile && mobileOpen ? 'dialog' : 'complementary'}
        aria-modal={isMobile && mobileOpen ? true : undefined}
        aria-label="Workspace navigation"
      >
        <button
          className="icon-button sidebar-close"
          aria-label="Close navigation"
          onClick={() => setMobileOpen(false)}
        >
          <X size={20} />
        </button>
        <a className="brand" href="#overview" aria-label="Folio home">
          <span className="brand-mark">
            <i />
            <i />
            <i />
          </span>
          folio<span className="brand-period">.</span>
        </a>
        <div className="workspace-switch">
          <span className="workspace-avatar">S</span>
          <div>
            <strong>Studio workspace</strong>
            <span>Freelance & creative</span>
          </div>
          <span className="workspace-dot" title="Local workspace" />
        </div>
        <div className="nav-label">WORKSPACE</div>
        <nav aria-label="Main navigation">
          {navItems.map((item) => (
            <a
              key={item.id}
              href={`#${item.id}`}
              aria-current={view === item.id ? 'page' : undefined}
              className={`nav-item ${view === item.id ? 'active' : ''}`}
              onClick={() => navigate(item.id)}
            >
              {item.icon}
              <span>{item.name}</span>
              {item.id === 'transactions' && !!summary?.review_count && (
                <span className="nav-count">{summary.review_count}</span>
              )}
            </a>
          ))}
        </nav>
        <div className="sidebar-bottom">
          <div className="local-note">
            <ShieldCheck size={17} />
            <span>
              Your books stay yours.<small>Processed locally.</small>
            </span>
          </div>
          <button className="nav-item help-link" onClick={openHelp}>
            <CircleHelp size={18} />
            <span>A little help</span>
            <ArrowUpRight size={14} />
          </button>
          <div className="profile">
            <span className="profile-avatar">SC</span>
            <div>
              <strong>Studio Creative</strong>
              <span>Independent by design</span>
            </div>
            <span className="small muted">LOCAL</span>
          </div>
        </div>
      </div>

      <div className="main-shell" inert={isMobile && mobileOpen}>
        <header className="topbar">
          <div className="breadcrumb">
            <button
              className="icon-button mobile-menu"
              ref={menuTriggerRef}
              onClick={() => setMobileOpen(true)}
              aria-label="Open navigation"
              aria-expanded={mobileOpen}
            >
              <Menu size={20} />
            </button>
            <span>Workspace</span>
            <ChevronRight size={13} />
            <strong>{navItems.find((i) => i.id === view)?.name}</strong>
          </div>
          <span className="local-badge">
            <span /> Local workspace
          </span>
        </header>

        <main id="main" tabIndex={-1}>
          <div className="page-heading">
            <div>
              <span className="eyebrow">A LITTLE ORDER. A LOT OF HEADSPACE.</span>
              <h1>
                {view === 'overview'
                  ? 'Good books. Clear mind.'
                  : view === 'transactions'
                    ? 'Every transaction, in its place.'
                    : view === 'categories'
                      ? 'See the bigger picture.'
                      : view === 'rules'
                        ? 'A little less repeat work.'
                        : 'Your paper trail, simplified.'}
              </h1>
              <p>
                {view === 'overview'
                  ? 'Less sorting. More time for what you do best.'
                  : view === 'transactions'
                    ? 'Review, refine, and keep moving.'
                    : view === 'categories'
                      ? 'Your business spending, thoughtfully organized.'
                      : view === 'rules'
                        ? 'Your decisions, remembered for the next statement.'
                        : 'From a bank export to a clearer set of books.'}
              </p>
            </div>
            <button className="button primary upload-main" onClick={() => setUploadOpen(true)}>
              <Plus size={17} /> Import statement
            </button>
          </div>

          {error && (
            <div className="error-box page-error" role="alert">
              <span>{error}</span>
              <button
                className="text-button"
                onClick={() => {
                  setLoading(true);
                  void load();
                }}
              >
                Try again
              </button>
            </div>
          )}
          {loading && !data ? (
            <div className="loading-state" role="status">
              <LoaderCircle size={28} className="spin" />
              <p>Opening your workspace…</p>
            </div>
          ) : (
            data && (
              <>
                {data.statements.length > 0 && (
                  <div className="scope-bar">
                    <div className="scope-controls">
                      <FileText size={15} />
                      <select
                        aria-label="Statement"
                        value={statementId}
                        onChange={(e) => {
                          const id = e.target.value;
                          setStatementId(id);
                          if (id) setCurrency(data.statements.find((s) => s.id === id)!.currency);
                          resetFilters();
                        }}
                      >
                        <option value="">All statements</option>
                        {data.statements.map((s) => (
                          <option key={s.id} value={s.id}>
                            {s.name}
                          </option>
                        ))}
                      </select>
                      {!statementId && (
                        <select
                          aria-label="Currency"
                          className="currency-select"
                          value={currency}
                          onChange={(e) => setCurrency(e.target.value)}
                        >
                          {[...new Set([...data.currencies, currency])].sort().map((c) => (
                            <option key={c}>{c}</option>
                          ))}
                        </select>
                      )}
                    </div>
                    <span className="small muted">
                      {scopedStatement
                        ? `${dateLabel(scopedStatement.date_start)} – ${dateLabel(scopedStatement.date_end, { month: 'short', day: 'numeric', year: 'numeric' })}`
                        : `${data.statements.filter((s) => s.currency === currency).length} statements · ${currency}`}
                    </span>
                  </div>
                )}

                {scopedStatement?.warnings.map((warning, i) => (
                  <div className="warning-box" role="status" key={i}>
                    <CircleHelp size={17} />
                    {warning}
                  </div>
                ))}

                {data.statements.length === 0 ? (
                  <section className="empty-hero">
                    <div className="empty-copy">
                      <span className="empty-badge">
                        <Layers3 size={15} /> YOUR BOOKS, WITH ROOM TO BREATHE
                      </span>
                      <h2>
                        Big ideas deserve
                        <br />a clear desk.
                      </h2>
                      <p>
                        Bring your statement. We’ll sort the familiar,
                        <br className="desktop-only" /> and leave the judgment calls to you.
                      </p>
                      <button className="button primary" onClick={() => setUploadOpen(true)}>
                        <Upload size={17} /> Import your first statement
                      </button>
                      <button className="sample-button" onClick={demo} disabled={demoBusy}>
                        {demoBusy ? (
                          <LoaderCircle className="spin" size={15} />
                        ) : (
                          <Sparkles size={15} />
                        )}{' '}
                        Try a sample statement <ArrowRight size={15} />
                      </button>
                      <span className="small muted">CSV or text-based PDF · No account needed</span>
                    </div>
                    <div className="paper-scene" aria-hidden="true">
                      <div className="paper-back" />
                      <div className="paper-card">
                        <span className="paper-eyebrow">A LITTLE CLARITY</span>
                        <h3>Everything adds up.</h3>
                        <div className="paper-rule" />
                        {[
                          ['Ad', 'Adobe Creative Cloud', 'Software', '#e9e6f5'],
                          ['F', 'Figma', 'Software', '#e9e6f5'],
                          ['↗', 'Uber Trip', 'Travel', '#e2eeea'],
                          ['?', 'A good coffee', 'Your call', '#f4ead5'],
                        ].map(([initial, merchant, cat, color]) => (
                          <div className="paper-row" key={merchant}>
                            <span style={{ background: color }}>{initial}</span>
                            <div>
                              <strong>{merchant}</strong>
                              <small>{cat}</small>
                            </div>
                            <CircleCheck size={17} />
                          </div>
                        ))}
                        <div className="paper-footer">
                          <CheckCheck size={16} /> Less busywork. More good work.
                        </div>
                      </div>
                      <span className="floating-tag">
                        <Check size={14} /> Nicely organized
                      </span>
                      <span className="scene-star" aria-hidden="true">
                        ✳
                      </span>
                    </div>
                  </section>
                ) : (
                  <>
                    {(view === 'overview' || view === 'transactions') && (
                      <>
                        <section className="stats-grid" aria-label="Statement summary">
                          <article className="stat-card">
                            <div>
                              <span className="stat-label">Business spending</span>
                              <IconTile>
                                <ArrowUpRight size={17} />
                              </IconTile>
                            </div>
                            <strong>
                              {money(summary!.confirmed.spending_minor, actualCurrency)}
                            </strong>
                            <span className="stat-foot">Confirmed · refunds deducted</span>
                          </article>
                          <article className="stat-card">
                            <div>
                              <span className="stat-label">Client income</span>
                              <IconTile tone="green">
                                <ArrowDownLeft size={17} />
                              </IconTile>
                            </div>
                            <strong>
                              {money(summary!.confirmed.income_minor, actualCurrency)}
                            </strong>
                            <span className="stat-foot">Transfers kept separate</span>
                          </article>
                          <button
                            className="stat-card stat-clickable"
                            onClick={() => {
                              setTab('review');
                              setCategory('all');
                              setFlow('all');
                              setQuery('');
                              navigate('transactions');
                            }}
                          >
                            <div>
                              <span className="stat-label">Needs your review</span>
                              <IconTile tone="amber">
                                <CircleHelp size={17} />
                              </IconTile>
                            </div>
                            <strong>
                              {summary!.review_count}
                              <small> transactions</small>
                            </strong>
                            <span className="stat-foot amber-text">
                              {summary!.review_count
                                ? 'A little context goes a long way'
                                : 'You’re all caught up'}
                            </span>
                          </button>
                          <article className="stat-card">
                            <div>
                              <span className="stat-label">Nicely organized</span>
                              <IconTile tone="green">
                                <CheckCheck size={18} />
                              </IconTile>
                            </div>
                            <strong>
                              {summary!.ready_count}
                              <small> / {summary!.total}</small>
                            </strong>
                            <span className="stat-foot">
                              <span className="mini-progress">
                                <i style={{ width: `${percentage}%` }} />
                              </span>
                              {percentage}% complete
                            </span>
                          </article>
                        </section>

                        {view === 'overview' && (
                          <div className="insights-grid">
                            <section className="panel spending-panel">
                              <div className="section-heading">
                                <div>
                                  <h2>Where it went</h2>
                                  <p>Confirmed business expenses</p>
                                </div>
                                <button
                                  className="text-button"
                                  onClick={() => navigate('categories')}
                                >
                                  All categories <ArrowUpRight size={14} />
                                </button>
                              </div>
                              <div className="category-bars">
                                {summary!.categories
                                  .filter((g) => expenseIds.includes(g.id) && g.count > 0)
                                  .sort(
                                    (a, b) =>
                                      Math.abs(b.confirmed_net_minor) -
                                      Math.abs(a.confirmed_net_minor),
                                  )
                                  .slice(0, 5)
                                  .map((g) => {
                                    const max = Math.max(
                                      1,
                                      ...summary!.categories
                                        .filter((c) => expenseIds.includes(c.id))
                                        .map((c) => Math.abs(c.confirmed_net_minor)),
                                    );
                                    return (
                                      <button
                                        className="category-bar-row"
                                        key={g.id}
                                        onClick={() => openCategory(g.id)}
                                      >
                                        <span className="bar-label">
                                          <i style={{ background: g.color }} />
                                          {g.name}
                                        </span>
                                        <span className="bar-track">
                                          <i
                                            style={{
                                              width: `${(Math.abs(g.confirmed_net_minor) / max) * 100}%`,
                                              background: g.color,
                                            }}
                                          />
                                        </span>
                                        <strong>
                                          {money(-g.confirmed_net_minor, actualCurrency)}
                                        </strong>
                                      </button>
                                    );
                                  })}
                                {!summary!.categories.some(
                                  (g) => expenseIds.includes(g.id) && g.count > 0,
                                ) && (
                                  <div className="quiet-empty">
                                    Your confirmed spending will appear here.
                                  </div>
                                )}
                              </div>
                            </section>
                            <section
                              className={`review-card ${summary!.review_count === 0 ? 'review-complete' : ''}`}
                            >
                              <div className="review-card-top">
                                <span className="eyebrow">THE FINISHING TOUCHES</span>
                                <span className="leaf-symbol" aria-hidden="true">
                                  ✳
                                </span>
                              </div>
                              <h2>
                                {summary!.review_count ? (
                                  <>
                                    Your context.
                                    <br />
                                    The missing piece.
                                  </>
                                ) : (
                                  <>
                                    A clear desk.
                                    <br />A clearer head.
                                  </>
                                )}
                              </h2>
                              <p>
                                {summary!.review_count
                                  ? `${summary!.review_count} transactions could use your eye. A merchant name doesn’t tell the whole story.`
                                  : 'Everything in this view is organized. Your books are ready for the next step.'}
                              </p>
                              <div className="review-card-bottom">
                                <span className="review-avatars">
                                  <i>?</i>
                                  <i>
                                    <Check size={12} />
                                  </i>
                                  <i>✳</i>
                                </span>
                                <button
                                  className="button"
                                  onClick={() =>
                                    summary!.review_count
                                      ? setReviewId(
                                          data.transactions.find((t) => t.needs_review)!.id,
                                        )
                                      : download('transactions', true)
                                  }
                                >
                                  {summary!.review_count ? 'Let’s review' : 'Export transactions'}{' '}
                                  <ArrowRight size={16} />
                                </button>
                              </div>
                            </section>
                          </div>
                        )}

                        <section className="panel transactions-panel">
                          <div className="section-heading transaction-heading">
                            <div>
                              <h2>
                                Transactions <span className="count-badge">{summary!.total}</span>
                              </h2>
                              <p>
                                {summary!.excluded_count
                                  ? `${summary!.excluded_count} excluded from totals`
                                  : 'The details behind the bigger picture.'}
                              </p>
                            </div>
                            <div ref={exportRef} className="export-wrap">
                              <button
                                className="button secondary"
                                aria-expanded={exportOpen}
                                aria-haspopup="menu"
                                onClick={() => setExportOpen(!exportOpen)}
                              >
                                <ArrowDownToLine size={15} /> Export <ChevronDown size={13} />
                              </button>
                              {exportOpen && (
                                <div
                                  className="dropdown-menu"
                                  role="menu"
                                  aria-label="Export options"
                                >
                                  <button role="menuitem" onClick={() => download('transactions')}>
                                    All transactions <span>Includes review status</span>
                                  </button>
                                  <button
                                    role="menuitem"
                                    onClick={() => download('transactions', true)}
                                  >
                                    Confirmed transactions <span>Only organized rows</span>
                                  </button>
                                  <button role="menuitem" onClick={() => download('summary')}>
                                    Category summary <span>Confirmed & provisional totals</span>
                                  </button>
                                </div>
                              )}
                            </div>
                          </div>
                          <div className="table-toolbar">
                            <div className="tabs" role="tablist" aria-label="Transaction status">
                              {(
                                [
                                  { id: 'all', label: 'All transactions', count: summary!.total },
                                  {
                                    id: 'review',
                                    label: 'Needs review',
                                    count: summary!.review_count,
                                  },
                                  {
                                    id: 'ready',
                                    label: 'Categorized',
                                    count: summary!.ready_count,
                                  },
                                ] as const
                              ).map((t) => (
                                <button
                                  role="tab"
                                  aria-label={`${t.label} ${t.count}`}
                                  aria-selected={tab === t.id}
                                  key={t.id}
                                  className={tab === t.id ? 'selected' : ''}
                                  onClick={() => setTab(t.id)}
                                >
                                  {t.label} <span>{t.count}</span>
                                </button>
                              ))}
                            </div>
                            <div className="search-wrap">
                              <Search size={15} />
                              <input
                                ref={searchRef}
                                aria-label="Search transactions"
                                placeholder="Search transactions…"
                                value={query}
                                onChange={(e) => setQuery(e.target.value)}
                              />
                              <kbd>/</kbd>
                            </div>
                          </div>
                          <div className="table-filters">
                            <span>
                              <ListFilter size={14} /> Filter
                            </span>
                            <select
                              aria-label="Filter category"
                              value={category}
                              onChange={(e) => setCategory(e.target.value)}
                            >
                              <option value="all">All categories</option>
                              {data.categories.map((c) => (
                                <option key={c.id} value={c.id}>
                                  {c.name}
                                </option>
                              ))}
                            </select>
                            <select
                              aria-label="Filter money type"
                              value={flow}
                              onChange={(e) => setFlow(e.target.value)}
                            >
                              <option value="all">All types</option>
                              {['expense', 'refund', 'income', 'transfer', 'neutral'].map((f) => (
                                <option key={f} value={f}>
                                  {f[0].toUpperCase() + f.slice(1)}
                                </option>
                              ))}
                            </select>
                            {(category !== 'all' || flow !== 'all' || query) && (
                              <button className="text-button" onClick={resetFilters}>
                                Clear filters <X size={12} />
                              </button>
                            )}
                            <span className="filter-count">{filtered.length} results</span>
                          </div>
                          {selected.size > 0 && (
                            <div className="selection-bar">
                              <span>
                                <CheckCheck size={16} />
                                {selected.size} selected
                              </span>
                              <button
                                className="text-button"
                                onClick={() => {
                                  setBulkCategory(effectiveBulkCategory);
                                  setBulkOpen(true);
                                  setBulkError('');
                                }}
                              >
                                Categorize selected <ArrowRight size={14} />
                              </button>
                              <button
                                className="icon-button"
                                aria-label="Clear selection"
                                onClick={() => setSelected(new Set())}
                              >
                                <X size={15} />
                              </button>
                            </div>
                          )}
                          <div className="table-scroll">
                            <table>
                              <thead>
                                <tr>
                                  <th className="checkbox-cell">
                                    <input
                                      type="checkbox"
                                      aria-label="Select page"
                                      checked={allSelected}
                                      disabled={!selectable.length}
                                      onChange={() =>
                                        setSelected((previous) => {
                                          const next = new Set(previous);
                                          selectable.forEach((t) => {
                                            if (allSelected) next.delete(t.id);
                                            else next.add(t.id);
                                          });
                                          return next;
                                        })
                                      }
                                    />
                                  </th>
                                  <th>
                                    <button
                                      className="sort-button"
                                      onClick={() =>
                                        setSort(sort === 'date-desc' ? 'date-asc' : 'date-desc')
                                      }
                                    >
                                      Date{' '}
                                      <ArrowDown
                                        size={12}
                                        className={sort === 'date-asc' ? 'rotate' : ''}
                                      />
                                    </button>
                                  </th>
                                  <th>Transaction</th>
                                  <th>Category</th>
                                  <th>Status</th>
                                  <th className="amount-cell">
                                    <button
                                      className="sort-button"
                                      onClick={() =>
                                        setSort(
                                          sort === 'amount-desc' ? 'amount-asc' : 'amount-desc',
                                        )
                                      }
                                    >
                                      Amount{' '}
                                      <ArrowDown
                                        size={12}
                                        className={sort === 'amount-asc' ? 'rotate' : ''}
                                      />
                                    </button>
                                  </th>
                                  <th className="row-arrow">
                                    <span className="sr-only">Details</span>
                                  </th>
                                </tr>
                              </thead>
                              <tbody>
                                {pageRows.map((row) => (
                                  <tr
                                    key={row.id}
                                    className={`${!row.included ? 'excluded-row' : ''} ${selected.has(row.id) ? 'selected-row' : ''}`}
                                  >
                                    <td className="checkbox-cell">
                                      <input
                                        type="checkbox"
                                        aria-label={`Select ${row.description}`}
                                        checked={selected.has(row.id)}
                                        disabled={row.duplicate || row.amount_minor === 0}
                                        title={
                                          row.duplicate
                                            ? 'Review duplicates individually'
                                            : undefined
                                        }
                                        onChange={() => toggle(row.id)}
                                      />
                                    </td>
                                    <td className="date-cell">{dateLabel(row.date)}</td>
                                    <td>
                                      <button
                                        className="merchant-button"
                                        onClick={() => setReviewId(row.id)}
                                      >
                                        <span className={`merchant-avatar avatar-${row.category}`}>
                                          {row.merchant_key.slice(0, 1) || '?'}
                                        </span>
                                        <span>
                                          <strong>{row.description}</strong>
                                          <small>
                                            {!row.included
                                              ? 'Excluded'
                                              : row.duplicate
                                                ? 'Possible duplicate'
                                                : row.flow === 'refund'
                                                  ? 'Refund'
                                                  : row.flow === 'transfer'
                                                    ? 'Account movement'
                                                    : row.note || ''}
                                          </small>
                                        </span>
                                      </button>
                                    </td>
                                    <td>
                                      <button
                                        className="pill-button"
                                        onClick={() => setReviewId(row.id)}
                                        aria-label={`${data.categories.find((c) => c.id === row.category)?.name}. Change category for ${row.description}`}
                                      >
                                        <CategoryPill
                                          category={row.category}
                                          categories={data.categories}
                                        />
                                      </button>
                                    </td>
                                    <td>
                                      <span
                                        className={`status ${row.needs_review ? 'status-review' : 'status-ready'}`}
                                      >
                                        {row.needs_review ? (
                                          <CircleHelp size={12} />
                                        ) : (
                                          <Check size={12} />
                                        )}
                                        {row.needs_review
                                          ? 'Needs review'
                                          : row.source === 'user'
                                            ? 'Confirmed'
                                            : row.source === 'rule'
                                              ? 'Your rule'
                                              : 'Categorized'}
                                      </span>
                                    </td>
                                    <td
                                      className={`amount-cell ${row.amount_minor > 0 && row.flow !== 'transfer' ? 'positive-amount' : ''}`}
                                    >
                                      {row.amount_minor > 0 ? '+' : ''}
                                      {money(row.amount_minor, row.currency)}
                                    </td>
                                    <td className="row-arrow">
                                      <button
                                        className="icon-button"
                                        aria-label={`Review ${row.description}`}
                                        onClick={() => setReviewId(row.id)}
                                      >
                                        <ChevronRight size={15} />
                                      </button>
                                    </td>
                                  </tr>
                                ))}
                              </tbody>
                            </table>
                            {pageRows.length === 0 && (
                              <div className="table-empty">
                                <Search size={25} />
                                <h3>
                                  {summary!.total
                                    ? 'A clean slate for these filters.'
                                    : 'No transactions in this view.'}
                                </h3>
                                <p>
                                  {summary!.total
                                    ? 'Try a different search or clear your filters.'
                                    : 'Choose another currency or import a statement.'}
                                </p>
                                {summary!.total > 0 && (
                                  <button className="button secondary" onClick={resetFilters}>
                                    Clear filters
                                  </button>
                                )}
                              </div>
                            )}
                          </div>
                          <div className="table-footer">
                            <span>
                              {filtered.length
                                ? `${(currentPage - 1) * pageSize + 1}–${Math.min(currentPage * pageSize, filtered.length)} of ${filtered.length} transactions`
                                : '0 transactions'}
                            </span>
                            <div>
                              <button
                                className="icon-button"
                                aria-label="Previous page"
                                disabled={currentPage <= 1}
                                onClick={() => setPage(currentPage - 1)}
                              >
                                <ChevronLeft size={16} />
                              </button>
                              <span>
                                Page {currentPage} of {maxPage}
                              </span>
                              <button
                                className="icon-button"
                                aria-label="Next page"
                                disabled={currentPage >= maxPage}
                                onClick={() => setPage(currentPage + 1)}
                              >
                                <ChevronRight size={16} />
                              </button>
                            </div>
                          </div>
                        </section>
                      </>
                    )}

                    {view === 'categories' && (
                      <>
                        <div className="section-heading categories-heading">
                          <h2>{actualCurrency} overview</h2>
                          <button className="button secondary" onClick={() => download('summary')}>
                            <ArrowDownToLine size={15} /> Export summary
                          </button>
                        </div>
                        <div className="category-grid">
                          {summary!.categories.map((g) => (
                            <button
                              className="panel category-card"
                              key={g.id}
                              onClick={() => openCategory(g.id)}
                            >
                              <span className="category-card-top">
                                <span className="category-dot" style={{ background: g.color }} />
                                <ArrowUpRight size={16} />
                              </span>
                              <h3>{g.name}</h3>
                              <strong>
                                {money(
                                  g.id === 'income'
                                    ? g.confirmed_net_minor
                                    : -g.confirmed_net_minor,
                                  actualCurrency,
                                )}
                              </strong>
                              <span>
                                {g.count} transactions
                                {g.review_count > 0 ? ` · ${g.review_count} to review` : ''}
                              </span>
                              <div className="category-card-footer">
                                <span>Confirmed net{g.id === 'transfer' ? ' outflow' : ''}</span>
                                <span>
                                  {g.review_count > 0 ? (
                                    `${money(g.id === 'income' ? g.net_minor : -g.net_minor, actualCurrency)} provisional`
                                  ) : (
                                    <Check size={14} />
                                  )}
                                </span>
                              </div>
                            </button>
                          ))}
                        </div>
                        <div className="reconciliation panel">
                          <ShieldCheck size={20} />
                          <div>
                            <h3>Every cent accounted for</h3>
                            <p>
                              {money(summary!.cash_in_minor, actualCurrency)} in −{' '}
                              {money(summary!.cash_out_minor, actualCurrency)} out ={' '}
                              {money(summary!.net_movement_minor, actualCurrency)} net movement.
                            </p>
                            <span className="small muted">
                              Included rows only. Categories organize transactions; business
                              deductibility depends on your circumstances.
                            </span>
                          </div>
                        </div>
                      </>
                    )}

                    {view === 'rules' && (
                      <section className="panel">
                        <div className="section-heading">
                          <div>
                            <h2>
                              Merchant rules{' '}
                              <span className="count-badge">{data.rules.length}</span>
                            </h2>
                            <p>Exact merchant, same money direction. Future imports only.</p>
                          </div>
                          <WandSparkles size={20} className="muted" />
                        </div>
                        {data.rules.length === 0 ? (
                          <div className="feature-empty">
                            <IconTile>
                              <WandSparkles size={25} />
                            </IconTile>
                            <h3>Your experience is the best shortcut.</h3>
                            <p>
                              Confirm a transaction and choose “Remember for future imports”.
                              <br />
                              You stay in control of what gets remembered.
                            </p>
                            <button
                              className="button secondary"
                              onClick={() => navigate('transactions')}
                            >
                              View transactions <ArrowRight size={15} />
                            </button>
                          </div>
                        ) : (
                          <div className="table-scroll">
                            <table>
                              <thead>
                                <tr>
                                  <th>Merchant</th>
                                  <th>Direction</th>
                                  <th>Category</th>
                                  <th>Created</th>
                                  <th>
                                    <span className="sr-only">Remove</span>
                                  </th>
                                </tr>
                              </thead>
                              <tbody>
                                {data.rules.map((rule) => (
                                  <tr key={rule.id}>
                                    <td>
                                      <strong>{rule.merchant_key}</strong>
                                      {rule.needs_confirmation && (
                                        <small className="field-hint">
                                          Needs confirmation. Review this merchant and remember it
                                          again.
                                        </small>
                                      )}
                                    </td>
                                    <td>
                                      {rule.direction === 'expense' ? 'Money out' : 'Money in'}
                                    </td>
                                    <td>
                                      <CategoryPill
                                        category={rule.category}
                                        categories={data.categories}
                                      />
                                    </td>
                                    <td>{dateLabel(rule.created_at.slice(0, 10))}</td>
                                    <td className="amount-cell">
                                      <button
                                        className="icon-button delete-button"
                                        aria-label={`Remove rule for ${rule.merchant_key}`}
                                        onClick={() => removeRule(rule.id)}
                                      >
                                        <Trash2 size={16} />
                                      </button>
                                    </td>
                                  </tr>
                                ))}
                              </tbody>
                            </table>
                          </div>
                        )}
                      </section>
                    )}

                    {view === 'statements' && (
                      <section className="panel">
                        <div className="section-heading">
                          <div>
                            <h2>
                              Statement library{' '}
                              <span className="count-badge">{data.statements.length}</span>
                            </h2>
                            <p>Original files aren’t retained. Your transactions are.</p>
                          </div>
                          <FolderOpen size={20} className="muted" />
                        </div>
                        <div className="statement-list">
                          {data.statements.map((s) => (
                            <div key={s.id} className="statement-list-item">
                              <button
                                className="statement-card"
                                onClick={() => {
                                  setStatementId(s.id);
                                  setCurrency(s.currency);
                                  resetFilters();
                                  navigate('transactions');
                                }}
                              >
                                <IconTile>
                                  <FileText size={22} />
                                </IconTile>
                                <div>
                                  <h3>{s.name}</h3>
                                  <p>
                                    {dateLabel(s.date_start)} –{' '}
                                    {dateLabel(s.date_end, {
                                      month: 'short',
                                      day: 'numeric',
                                      year: 'numeric',
                                    })}{' '}
                                    · {s.row_count} transactions · {s.currency}
                                  </p>
                                  {s.warnings.length > 0 && (
                                    <span className="amber-text small">
                                      Extraction needs reconciliation
                                    </span>
                                  )}
                                </div>
                                <span className="small muted">
                                  {new Date(s.created_at).toLocaleDateString('en-US', {
                                    month: 'short',
                                    day: 'numeric',
                                  })}
                                </span>
                                <ArrowUpRight size={18} />
                              </button>
                              <button
                                className="icon-button delete-button"
                                aria-label={`Remove ${s.name}`}
                                onClick={() => {
                                  setRemoveId(s.id);
                                  setRemoveError('');
                                }}
                              >
                                <Trash2 size={16} />
                              </button>
                            </div>
                          ))}
                        </div>
                      </section>
                    )}
                  </>
                )}
                <footer className="page-footer">
                  <span>
                    <span className="tiny-brand">f.</span> A little clarity for your books.
                  </span>
                  <button className="text-button" onClick={openHelp}>
                    Made for independent minds <ArrowUpRight size={12} />
                  </button>
                </footer>
              </>
            )
          )}
        </main>
      </div>

      {uploadOpen && (
        <UploadModal
          close={() => setUploadOpen(false)}
          imported={(id, message, nextCurrency) => {
            setUploadOpen(false);
            setStatementId(id);
            if (nextCurrency) setCurrency(nextCurrency);
            resetFilters();
            navigate('overview');
            setToast(message);
            if (id === statementId) void load();
          }}
        />
      )}
      {reviewRow && data && (
        <ReviewModal
          key={reviewRow.id}
          row={reviewRow}
          categories={data.categories}
          close={() => setReviewId(null)}
          saved={saved}
          reviewCount={summary!.review_count}
        />
      )}
      {removeId && data && (
        <Modal title="Remove this statement?" close={() => !removeBusy && setRemoveId(null)}>
          <p className="modal-intro">{data.statements.find((s) => s.id === removeId)?.name}</p>
          <p className="delete-explanation">
            Its transactions and review history will be removed. You can import the file again with
            different settings. Merchant rules remain in your workspace.
          </p>
          {removeError && (
            <div className="error-box" role="alert">
              {removeError}
            </div>
          )}
          <div className="modal-footer">
            <button
              className="button secondary"
              disabled={removeBusy}
              onClick={() => setRemoveId(null)}
            >
              Keep statement
            </button>
            <button className="button danger" disabled={removeBusy} onClick={removeStatement}>
              {removeBusy ? <LoaderCircle className="spin" size={16} /> : <Trash2 size={15} />}{' '}
              Remove statement
            </button>
          </div>
        </Modal>
      )}
      {bulkOpen && data && (
        <Modal
          title={`Categorize ${selected.size} transactions`}
          close={() => !bulkBusy && setBulkOpen(false)}
        >
          <p className="modal-intro">
            Confirm one category for all selected rows. Money received becomes a refund unless you
            choose Client income or Transfers.
          </p>
          <label>
            Category
            <select
              value={effectiveBulkCategory}
              onChange={(e) => setBulkCategory(e.target.value)}
              disabled={bulkBusy}
            >
              {bulkChoices.map((c) => (
                <option key={c.id} value={c.id}>
                  {c.name}
                </option>
              ))}
            </select>
          </label>
          {bulkError && (
            <div className="error-box" role="alert">
              {bulkError}
            </div>
          )}
          <div className="modal-footer">
            <button
              className="button secondary"
              onClick={() => setBulkOpen(false)}
              disabled={bulkBusy}
            >
              Cancel
            </button>
            <button
              className="button primary"
              disabled={bulkBusy || !validSelection || !effectiveBulkCategory}
              onClick={bulkSave}
            >
              {bulkBusy ? <LoaderCircle className="spin" size={16} /> : <CheckCheck size={16} />}{' '}
              Confirm {selected.size} rows
            </button>
          </div>
          {selected.size > 200 && (
            <p role="alert" className="amber-text">
              Select at most 200 rows at a time.
            </p>
          )}
        </Modal>
      )}
      {helpOpen && (
        <Modal title="A little help" close={() => setHelpOpen(false)}>
          <div className="help-content">
            <IconTile>
              <BookOpen size={24} />
            </IconTile>
            <h3>From statement to a clear set of books.</h3>
            <p>
              Import a CSV or text-based PDF, then give the review queue a little context. Open any
              transaction to see exactly why it was categorized.
            </p>
            <h4>How the brain works</h4>
            <p>
              Original Python rules use specific merchant evidence and money direction. Refunds
              reduce expenses. Explicit transfers stay out of spending and income. Ambiguous rows
              stay in review.
            </p>
            <h4>Your rules, your call</h4>
            <p>
              “Remember” learns an exact normalized merchant and direction for future imports. It
              doesn’t change other existing transactions. Remove rules any time.
            </p>
            <h4>Before you export</h4>
            <p>
              Top-line totals include confirmed rows only. Resolve duplicates individually, check
              your sign convention, and compare PDF imports against the original. Export includes
              review status and exclusions.
            </p>
            <h4>Local by design</h4>
            <p>
              This is a single-user app for a trusted local machine. It doesn’t send your
              transactions to an external service. Categories are bookkeeping suggestions, not a
              determination of tax deductibility.
            </p>
            <a href="/api/sample" className="button secondary" download>
              <ArrowDownToLine size={15} /> Download a sample CSV
            </a>
          </div>
        </Modal>
      )}
      {toast && (
        <div className="toast" role="status">
          <CircleCheck size={17} />
          <span>{toast}</span>
          <button
            className="icon-button"
            onClick={() => setToast('')}
            aria-label="Dismiss notification"
          >
            <X size={14} />
          </button>
        </div>
      )}
    </div>
  );
}
