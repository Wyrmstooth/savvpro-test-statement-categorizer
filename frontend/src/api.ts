export class ApiError extends Error {
  status: number;
  statementId?: string;
  constructor(message: string, status: number, statementId?: string) {
    super(message);
    this.status = status;
    this.statementId = statementId;
  }
}

export async function request<T>(path: string, options?: RequestInit): Promise<T> {
  let response: Response;
  try {
    response = await fetch(`/api${path}`, options);
  } catch {
    throw new Error('Cannot reach Folio. Check that the Python server is running, then try again.');
  }
  if (!response.ok) {
    const body = await response.json().catch(() => null);
    const detail = body?.detail;
    const message =
      typeof detail === 'string'
        ? detail
        : (detail?.message ??
          (Array.isArray(detail)
            ? detail.map((d: { msg: string }) => d.msg).join('. ')
            : `Request failed (${response.status}).`));
    throw new ApiError(message, response.status, detail?.statement_id);
  }
  if (response.status === 204) return undefined as T;
  return response.json();
}

export const json = (body: unknown, method = 'POST'): RequestInit => ({
  method,
  headers: { 'Content-Type': 'application/json' },
  body: JSON.stringify(body),
});

export function money(minor: number, currency = 'USD') {
  // API integers are range checked; BigInt formatting preserves cents at large totals.
  const exact = BigInt(minor);
  const whole = exact / 100n;
  const cents = ((exact < 0n ? -exact : exact) % 100n).toString().padStart(2, '0');
  const value = exact < 0n && whole === 0n ? -0 : whole;
  return new Intl.NumberFormat('en-US', { style: 'currency', currency })
    .formatToParts(value)
    .map((part) => (part.type === 'fraction' ? cents : part.value))
    .join('');
}

export const dateLabel = (date: string, options?: Intl.DateTimeFormatOptions) =>
  new Intl.DateTimeFormat('en-US', options ?? { month: 'short', day: 'numeric' }).format(
    new Date(`${date}T12:00:00`),
  );
