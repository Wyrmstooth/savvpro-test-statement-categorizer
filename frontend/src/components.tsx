import { useEffect, useRef, useState, type ReactNode } from 'react';
import {
  ArrowDownLeft,
  ArrowUpRight,
  Check,
  ChevronDown,
  FileUp,
  LoaderCircle,
  X,
} from 'lucide-react';
import { ApiError, dateLabel, json, money, request } from './api';
import type { Category, Flow, History, Transaction } from './types';

export function Modal({
  title,
  children,
  close,
  wide = false,
}: {
  title: string;
  children: ReactNode;
  close: () => void;
  wide?: boolean;
}) {
  const ref = useRef<HTMLDialogElement>(null);
  const closeRef = useRef(close);
  closeRef.current = close;
  useEffect(() => {
    const dialog = ref.current!;
    const previous = document.activeElement as HTMLElement | null;
    dialog.showModal();
    const onCancel = (event: Event) => {
      event.preventDefault();
      closeRef.current();
    };
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key !== 'Tab') return;
      const items = [
        ...dialog.querySelectorAll<HTMLElement>(
          'button:not(:disabled), a[href], input:not(:disabled), select:not(:disabled), textarea:not(:disabled), summary, [tabindex="0"]',
        ),
      ].filter(
        (element) =>
          element.getClientRects().length > 0 &&
          (!element.closest('details:not([open])') || element.tagName === 'SUMMARY'),
      );
      const first = items[0],
        last = items[items.length - 1];
      if (event.shiftKey && document.activeElement === first) {
        event.preventDefault();
        last?.focus();
      } else if (!event.shiftKey && document.activeElement === last) {
        event.preventDefault();
        first?.focus();
      }
    };
    dialog.addEventListener('cancel', onCancel);
    dialog.addEventListener('keydown', onKeyDown);
    return () => {
      dialog.removeEventListener('cancel', onCancel);
      dialog.removeEventListener('keydown', onKeyDown);
      dialog.close();
      previous?.focus();
    };
  }, []);
  return (
    <dialog
      ref={ref}
      className={`modal ${wide ? 'modal-wide' : ''}`}
      aria-label={title}
      onClick={(e) => {
        if (e.target === e.currentTarget) {
          const bounds = e.currentTarget.getBoundingClientRect();
          if (
            e.clientX < bounds.left ||
            e.clientX > bounds.right ||
            e.clientY < bounds.top ||
            e.clientY > bounds.bottom
          )
            close();
        }
      }}
    >
      <div className="modal-header">
        <h2>{title}</h2>
        <button className="icon-button" aria-label="Close dialog" onClick={close}>
          <X size={19} />
        </button>
      </div>
      {children}
    </dialog>
  );
}

export function CategoryPill({
  category,
  categories,
}: {
  category: string;
  categories: Category[];
}) {
  const item = categories.find((c) => c.id === category);
  return (
    <span className={`category-pill category-${category}`}>
      <i style={{ background: item?.color }} />
      {item?.name ?? category}
    </span>
  );
}

export function UploadModal({
  close,
  imported,
}: {
  close: () => void;
  imported: (id: string, message: string, currency?: string) => void;
}) {
  const [file, setFile] = useState<File | null>(null);
  const [dragging, setDragging] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const [currency, setCurrency] = useState('USD');
  const [dateOrder, setDateOrder] = useState('mdy');
  const [convention, setConvention] = useState('bank');
  const [decimal, setDecimal] = useState('.');
  const [statementYear, setStatementYear] = useState('');
  const input = useRef<HTMLInputElement>(null);

  function choose(candidate?: File) {
    setError('');
    if (!candidate) return;
    if (!/\.(csv|pdf)$/i.test(candidate.name)) {
      setError('Choose a CSV or text-based PDF.');
      return;
    }
    if (candidate.size > 10 * 1024 * 1024) {
      setError('File exceeds 10 MB. Split the statement first.');
      return;
    }
    if (!candidate.size) {
      setError('This file is empty.');
      return;
    }
    setFile(candidate);
  }

  async function upload() {
    if (!file) return;
    setBusy(true);
    setError('');
    const data = new FormData();
    data.append('file', file);
    try {
      const params = new URLSearchParams({
        currency,
        date_order: dateOrder,
        convention,
        decimal_separator: decimal,
      });
      if (statementYear && file.name.toLowerCase().endsWith('.pdf')) {
        params.set('statement_year', statementYear);
      }
      const result = await request<{
        statement_id: string;
        row_count: number;
        currency: string;
        warnings: string[];
      }>(`/statements?${params}`, { method: 'POST', body: data });
      imported(result.statement_id, `${result.row_count} transactions imported`, result.currency);
    } catch (err) {
      if (err instanceof ApiError && err.statementId) {
        imported(err.statementId, 'Opened the existing statement');
        return;
      }
      setError((err as Error).message);
    } finally {
      setBusy(false);
    }
  }

  return (
    <Modal title="Import a statement" close={() => !busy && close()}>
      <p className="modal-intro">A fresh start for a messy statement.</p>
      <input
        ref={input}
        type="file"
        accept=".csv,.pdf"
        className="sr-only"
        aria-label="Statement file"
        disabled={busy}
        onChange={(e) => choose(e.target.files?.[0])}
      />
      <button
        className={`dropzone ${dragging ? 'dragging' : ''}`}
        disabled={busy}
        onClick={() => input.current?.click()}
        onDragOver={(e) => {
          e.preventDefault();
          setDragging(true);
        }}
        onDragLeave={() => setDragging(false)}
        onDrop={(e) => {
          e.preventDefault();
          setDragging(false);
          choose(e.dataTransfer.files[0]);
        }}
      >
        <span className="upload-icon">
          <FileUp size={27} strokeWidth={1.5} />
        </span>
        <strong>{file ? file.name : 'Drop your statement here'}</strong>
        <span>
          {file
            ? `${(file.size / 1024).toFixed(1)} KB · Click to change`
            : 'or click to browse · CSV or PDF, up to 10 MB'}
        </span>
      </button>
      <div className="field-row">
        <label>
          Currency
          <select value={currency} onChange={(e) => setCurrency(e.target.value)} disabled={busy}>
            {['USD', 'GBP', 'EUR', 'CAD', 'AUD', 'PKR'].map((c) => (
              <option key={c}>{c}</option>
            ))}
          </select>
        </label>
        <label>
          Date order
          <select value={dateOrder} onChange={(e) => setDateOrder(e.target.value)} disabled={busy}>
            <option value="mdy">Month / day / year</option>
            <option value="dmy">Day / month / year</option>
          </select>
        </label>
      </div>
      <label>
        Signed amount convention
        <select value={convention} onChange={(e) => setConvention(e.target.value)} disabled={busy}>
          <option value="bank">Expenses are negative · bank / signed exports</option>
          <option value="card">Charges are positive · card statements</option>
        </select>
      </label>
      <p className="field-hint">
        Separate Debit / Credit columns work with either setting. ISO dates always work.
      </p>
      <details className="import-details">
        <summary>
          Format details <ChevronDown size={15} />
        </summary>
        <label>
          Decimal separator
          <select value={decimal} onChange={(e) => setDecimal(e.target.value)} disabled={busy}>
            <option value=".">Period · 1,234.56</option>
            <option value=",">Comma · 1.234,56</option>
          </select>
        </label>
        {file?.name.toLowerCase().endsWith('.pdf') && (
          <label>
            Statement year <span className="optional">if dates omit the full year</span>
            <input
              className="year-input"
              type="number"
              min="1900"
              max="2100"
              step="1"
              value={statementYear}
              onChange={(e) => setStatementYear(e.target.value)}
              placeholder="e.g. 2026"
              disabled={busy}
            />
          </label>
        )}
        <p>
          CSV needs Date, Description and Amount, or Debit / Credit columns. PDFs need selectable
          text and a transaction table. Scanned PDFs aren’t supported.
        </p>
        <a href="/api/sample" download>
          Download a sample CSV <ArrowUpRight size={13} />
        </a>
      </details>
      {error && (
        <div className="error-box" role="alert">
          {error}
        </div>
      )}
      <div className="modal-footer">
        <span className="muted small">Processed on your local server</span>
        <button className="button primary" disabled={!file || busy} onClick={upload}>
          {busy ? (
            <>
              <LoaderCircle size={16} className="spin" /> Reading statement…
            </>
          ) : (
            <>
              Import statement <ArrowUpRight size={16} />
            </>
          )}
        </button>
      </div>
    </Modal>
  );
}

export function ReviewModal({
  row,
  categories,
  close,
  saved,
  reviewCount,
}: {
  row: Transaction;
  categories: Category[];
  close: () => void;
  saved: (next: boolean) => Promise<void>;
  reviewCount: number;
}) {
  const [category, setCategory] = useState(row.category);
  const [note, setNote] = useState(row.note);
  const [remember, setRemember] = useState(false);
  const [included, setIncluded] = useState(row.included);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const [history, setHistory] = useState<History[] | null>(null);
  const [historyError, setHistoryError] = useState('');
  const [showEvidence, setShowEvidence] = useState(false);

  async function save(next: boolean) {
    setBusy(true);
    setError('');
    const flow: Flow =
      category === 'transfer'
        ? 'transfer'
        : category === 'income'
          ? 'income'
          : row.amount_minor > 0
            ? 'refund'
            : row.amount_minor === 0
              ? 'neutral'
              : 'expense';
    try {
      await request(
        `/transactions/${row.id}`,
        json({ category, flow, version: row.version, note, included, remember }, 'PATCH'),
      );
      await saved(next);
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setBusy(false);
    }
  }

  return (
    <Modal
      title={row.needs_review ? 'A little context needed' : 'Transaction details'}
      close={() => !busy && close()}
    >
      <div className="review-merchant">
        <span className={`merchant-avatar avatar-${row.category}`}>
          {row.merchant_key.slice(0, 1)}
        </span>
        <div>
          <h3>{row.description}</h3>
          <p>
            {dateLabel(row.date, { month: 'long', day: 'numeric', year: 'numeric' })} <span>·</span>{' '}
            {row.currency}
          </p>
        </div>
      </div>
      <div className="review-amount">
        <span>
          {row.amount_minor >= 0 ? <ArrowDownLeft size={18} /> : <ArrowUpRight size={18} />}
          {row.amount_minor >= 0 ? 'Money in' : 'Money out'}
        </span>
        <strong>{money(Math.abs(row.amount_minor), row.currency)}</strong>
      </div>
      <div className={`reason-box ${row.needs_review ? 'reason-review' : ''}`}>
        <span className="eyebrow">
          {row.source === 'user' ? 'Your decision' : 'Why this category'}
        </span>
        {row.reasons.map((reason, i) => (
          <p key={i}>{reason}</p>
        ))}
        {row.source !== 'user' && row.confidence > 0 && (
          <span className="small muted">
            Evidence score {row.confidence}/100 · heuristic, not a probability
          </span>
        )}
      </div>
      <label>
        Category
        <select value={category} onChange={(e) => setCategory(e.target.value)} disabled={busy}>
          <option value="uncategorized" disabled>
            Choose a category
          </option>
          {categories
            .filter((c) => c.id !== 'uncategorized' && (c.id !== 'income' || row.amount_minor > 0))
            .map((c) => (
              <option key={c.id} value={c.id}>
                {c.name}
              </option>
            ))}
        </select>
      </label>
      {row.amount_minor > 0 && category !== 'income' && category !== 'transfer' && (
        <p className="field-hint">
          Money received reduces this category’s expenses. Choose Client income or Transfers for
          other credits.
        </p>
      )}
      <label>
        Business context <span className="optional">optional</span>
        <textarea
          value={note}
          onChange={(e) => setNote(e.target.value)}
          placeholder="e.g. Coffee with a client to review their brand direction"
          maxLength={500}
          rows={2}
          disabled={busy}
        />
      </label>
      {row.duplicate && (
        <label className="check-field duplicate-check">
          <input
            type="checkbox"
            checked={included}
            onChange={(e) => setIncluded(e.target.checked)}
            disabled={busy}
          />
          Keep this transaction in totals
        </label>
      )}
      {!row.duplicate && row.amount_minor !== 0 && row.merchant_key && (
        <label className="check-field">
          <input
            type="checkbox"
            checked={remember}
            onChange={(e) => setRemember(e.target.checked)}
            disabled={busy}
          />
          <span>
            Remember for future imports
            <span className="field-hint">
              Exact merchant: {row.merchant_key} · {row.amount_minor < 0 ? 'money out' : 'money in'}
            </span>
          </span>
        </label>
      )}
      <details
        className="import-details"
        onToggle={(e) => {
          if (e.currentTarget.open && history === null)
            request<History[]>(`/transactions/${row.id}/history`)
              .then(setHistory)
              .catch((err) => setHistoryError(err.message));
        }}
      >
        <summary>
          Decision history & source <ChevronDown size={15} />
        </summary>
        <p>
          Original statement row {row.line}. {row.duplicate ? 'Possible duplicate.' : ''}
        </p>
        {historyError && <p role="alert">{historyError}</p>}
        {history?.length === 0 && <p>No manual changes yet.</p>}
        {history?.map((item) => (
          <p key={item.id}>
            {new Date(item.created_at).toLocaleString()} ·{' '}
            {categories.find((c) => c.id === item.before.category)?.name} →{' '}
            {categories.find((c) => c.id === item.after.category)?.name}
            {!item.after.included
              ? ' · Excluded'
              : item.after.needs_review
                ? ' · Needs review'
                : ''}
          </p>
        ))}
        {row.evidence.length > 0 && (
          <>
            <button className="text-button" onClick={() => setShowEvidence(!showEvidence)}>
              {showEvidence ? 'Hide' : 'Show'} rule identifiers
            </button>
            {showEvidence && <code className="evidence">{row.evidence.join('\n')}</code>}
          </>
        )}
      </details>
      {error && (
        <div className="error-box" role="alert">
          {error}
        </div>
      )}
      <div className="modal-footer">
        <button
          className="button secondary"
          disabled={busy || category === 'uncategorized'}
          onClick={() => save(false)}
        >
          {busy ? <LoaderCircle className="spin" size={16} /> : <Check size={16} />} Confirm
        </button>
        {row.needs_review && reviewCount > 1 && (
          <button
            className="button primary"
            disabled={busy || category === 'uncategorized'}
            onClick={() => save(true)}
          >
            Confirm & next <ArrowUpRight size={16} />
          </button>
        )}
      </div>
    </Modal>
  );
}
