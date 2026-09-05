export type Health = {
  status: string;
  version: string;
  db: {
    path: string;
    exists: boolean;
    user_version: number | null;
    info_table: Record<string, string>;
    error: string | null;
  };
  schema: { ok: boolean; error: string | null; user_version: number | null } | null;
  lock: {
    acquired: boolean;
    read_only: boolean;
    holder: string | null;
    protocol?: string;
  };
  last_backup: { path: string; mtime_iso: string } | null;
  paperless?: {
    configured: boolean;
    url: string | null;
    inbox_tag: string;
  };
};

export type Account = {
  account_id: number;
  name: string;
  account_type: string;
  status: string;
  favorite: boolean;
  currency_symbol: string | null;
  display_formatted: string;
  reconciled_formatted?: string;
  difference_formatted?: string;
  statement_locked?: number;
  statement_date?: string | null;
  credit_limit?: string;
  minimum_payment?: string;
  payment_due_date?: string | null;
};

export type TxnFilter = {
  date_from?: string;
  date_to?: string;
  payee_id?: number;
  payee_q?: string;
  categ_id?: number;
  trans_code?: string;
  status?: string;
  amount_min?: string;
  amount_max?: string;
  notes?: string;
  number?: string;
  tag_id?: number;
  followup?: boolean;
};

export type SavedView = {
  id: number;
  name: string;
  account_id: number | null;
  filter: TxnFilter;
};

export type Group = {
  account_type: string;
  label_fr: string;
  label_en: string;
  count: number;
  accounts: Account[];
};

export type Dashboard = {
  net_worth_formatted: string;
  upcoming_bills: number;
  base_currency: { name: string; symbol: string } | null;
  groups: Group[];
  closed_accounts?: Account[];
  favorites: Account[];
  accounts: Account[];
};

export type AuthStatus = {
  authenticated: boolean;
  username: string | null;
  bootstrap: boolean;
  locale_default: "fr" | "en";
};

export type ManagerId = "payees" | "categories" | "tags" | "currencies" | "fields";

export type View =
  | { kind: "home" }
  | { kind: "favorites" }
  | { kind: "type"; accountType: string }
  | { kind: "account"; accountId: number }
  | { kind: "manager"; id: ManagerId }
  | { kind: "scheduled" }
  | { kind: "budgets" }
  | { kind: "reports" }
  | { kind: "stocks" }
  | { kind: "assets" }
  | { kind: "tools" }
  | { kind: "settings" }
  | { kind: "quickadd" }
  | { kind: "all" }
  | { kind: "recon" }
  | { kind: "reconDoc"; accountId: number; docId: number }
  | { kind: "soon"; id: string };

export type ReconDoc = {
  id: number;
  title: string;
  created: string;
  original_file_name: string;
  tags: string[];
  account_id: number | null;
};

export type ReconInbox = {
  configured: boolean;
  inbox_tag: string;
  documents: ReconDoc[];
  by_account: Record<string, ReconDoc[]>;
  unmapped: ReconDoc[];
};

export type Tag = { tag_id: number; name: string };

export type SplitRow = {
  split_id?: number;
  categ_id: number;
  category_path?: string | null;
  amount: string;
  notes: string;
  tags: Tag[];
  tag_ids?: number[];
};

export type TxnRow = {
  trans_id: number;
  account_id: number;
  to_account_id: number;
  payee_id: number;
  payee_name: string | null;
  trans_code: "Withdrawal" | "Deposit" | "Transfer";
  trans_amount: string;
  status: string;
  transaction_number: string;
  notes: string;
  categ_id: number;
  category_path: string | null;
  trans_date: string;
  deleted_time: string;
  to_trans_amount: string;
  color: number;
  followup_id: number;
  flow: string;
  running_balance: string;
  split_count: number;
  is_split: boolean;
  attachment_count: number;
  tags: Tag[];
  withdrawal: string | null;
  deposit: string | null;
  from_account_name?: string | null;
  to_account_name?: string | null;
};

export type Attachment = {
  attachment_id: number;
  ref_type: string;
  ref_id: number;
  description: string;
  filename: string;
};

export type TxnDetail = Omit<
  TxnRow,
  "flow" | "running_balance" | "split_count" | "is_split" | "withdrawal" | "deposit" | "attachment_count"
> & {
  splits: SplitRow[];
  attachments: Attachment[];
  attachment_count: number;
};

export type Payee = {
  payee_id: number;
  name: string;
  categ_id: number | null;
  active?: number;
  pattern?: string;
};
export type Category = {
  categ_id: number;
  name: string;
  parent_id: number | null;
  path: string;
  active?: number;
};

export type PayeeAdmin = Payee & {
  number: string;
  website: string;
  notes: string;
  pattern: string;
  active: number;
  used_count: number;
  category_path: string | null;
};

export type CategoryAdmin = Category & {
  active: number;
  used_count: number;
  child_count: number;
};

export type TagAdmin = Tag & { active: number; used_count: number };

export type CurrencyAdmin = {
  currency_id: number;
  name: string;
  symbol: string;
  pfx: string;
  sfx: string;
  decimal_point: string;
  group_separator: string;
  unit_name: string;
  cent_name: string;
  scale: number;
  rate: string;
  currency_type: "Fiat" | "Crypto";
  used_count: number;
  is_base: boolean;
};
