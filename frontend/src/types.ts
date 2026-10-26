export type Category = { id: string; name: string; color: string };
export type Flow = 'expense' | 'refund' | 'income' | 'transfer' | 'neutral';
export type Transaction = {
  id: string;
  statement_id: string;
  date: string;
  description: string;
  merchant_key: string;
  amount_minor: number;
  currency: string;
  category: string;
  flow: Flow;
  confidence: number;
  needs_review: boolean;
  reasons: string[];
  evidence: string[];
  source: string;
  duplicate: boolean;
  included: boolean;
  note: string;
  version: number;
  line: number;
};
export type Statement = {
  id: string;
  name: string;
  currency: string;
  date_start: string;
  date_end: string;
  row_count: number;
  warnings: string[];
  created_at: string;
};
export type MerchantRule = {
  id: string;
  merchant_key: string;
  direction: string;
  category: string;
  created_at: string;
  needs_confirmation: boolean;
};
export type Group = Category & {
  count: number;
  net_minor: number;
  review_count: number;
  confirmed_net_minor: number;
};
type Totals = {
  spending_minor: number;
  income_minor: number;
  transfer_in_minor: number;
  transfer_out_minor: number;
};
export type Summary = {
  currency: string;
  total: number;
  review_count: number;
  ready_count: number;
  excluded_count: number;
  refund_minor: number;
  cash_in_minor: number;
  cash_out_minor: number;
  net_movement_minor: number;
  unresolved_net_minor: number;
  unclassified_credits_minor: number;
  confirmed: Totals;
  provisional: Totals;
  categories: Group[];
};
export type Workspace = {
  statements: Statement[];
  transactions: Transaction[];
  summary: Summary;
  rules: MerchantRule[];
  categories: Category[];
  currencies: string[];
  engine_version: string;
};
export type History = {
  id: string;
  created_at: string;
  action: string;
  before: Transaction;
  after: Transaction;
};
