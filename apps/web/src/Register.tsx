import { FormEvent, useCallback, useEffect, useMemo, useState } from "react";
import { CustomFields } from "./CustomFields";
import { Editor } from "./Editor";
import { PayeeField } from "./PayeeField";
import { SortTh, sortBy, toggleSort, type SortState } from "./Sortable";
import { api } from "./api";
import type { MessageKey } from "./i18n";
import type { Account, Category, SavedView, Tag, TxnFilter, TxnRow } from "./types";

type Props = {
  accountId?: number;
  accountName: string;
  account?: Account;
  accounts: Account[];
  t: (key: MessageKey) => string;
  newTxnNonce?: number;
  allAccounts?: boolean;
  onChanged: () => void;
  onEditAccount?: () => void;
};

const STATUS_LABEL: Record<string, MessageKey> = {
  "": "statusNone",
  R: "statusR",
  V: "statusV",
  F: "statusF",
  D: "statusD",
};

const EMPTY_FILTER: TxnFilter = {};

function filterQuery(f: TxnFilter): string {
  const p = new URLSearchParams();
  if (f.date_from) p.set("date_from", f.date_from);
  if (f.date_to) p.set("date_to", f.date_to);
  if (f.payee_id) p.set("payee_id", String(f.payee_id));
  if (f.payee_q) p.set("payee_q", f.payee_q);
  if (f.categ_id) p.set("categ_id", String(f.categ_id));
  if (f.trans_code) p.set("trans_code", f.trans_code);
  if (f.status !== undefined && f.status !== "*") p.set("status", f.status);
  if (f.amount_min) p.set("amount_min", f.amount_min);
  if (f.amount_max) p.set("amount_max", f.amount_max);
  if (f.notes) p.set("notes", f.notes);
  if (f.number) p.set("number", f.number);
  if (f.tag_id) p.set("tag_id", String(f.tag_id));
  if (f.followup) p.set("followup", "true");
  const qs = p.toString();
  return qs ? `&${qs}` : "";
}

export function Register({
  accountId = 0,
  accountName,
  account,
  accounts,
  t,
  newTxnNonce = 0,
  allAccounts = false,
  onChanged,
  onEditAccount,
}: Props) {
  const [rows, setRows] = useState<TxnRow[]>([]);
  const [total, setTotal] = useState(0);
  const [accountTotal, setAccountTotal] = useState(0);
  const [offset, setOffset] = useState(0);
  const [error, setError] = useState<string | null>(null);
  const [editing, setEditing] = useState<number | null | undefined>(undefined);
  const [showDeleted, setShowDeleted] = useState(false);
  const [filter, setFilter] = useState<TxnFilter>(EMPTY_FILTER);
  const [draft, setDraft] = useState<TxnFilter & { payee_query: string; status: string }>({
    payee_query: "",
    status: "*",
  });
  const [categories, setCategories] = useState<Category[]>([]);
  const [tags, setTags] = useState<Tag[]>([]);
  const [views, setViews] = useState<SavedView[]>([]);
  const [viewId, setViewId] = useState<number | "">("");
  const [stmt, setStmt] = useState({
    statement_locked: false,
    statement_date: "",
    credit_limit: "",
    minimum_payment: "",
  });
  const [sort, setSort] = useState<SortState>({ key: "date", dir: "desc" });
  const [editorAccount, setEditorAccount] = useState(accountId);

  useEffect(() => {
    setStmt({
      statement_locked: Boolean(account?.statement_locked),
      statement_date: account?.statement_date?.slice(0, 10) ?? "",
      credit_limit: account?.credit_limit && account.credit_limit !== "0" ? account.credit_limit : "",
      minimum_payment:
        account?.minimum_payment && account.minimum_payment !== "0" ? account.minimum_payment : "",
    });
  }, [account]);

  const load = useCallback(
    async (start: number, append: boolean, current: TxnFilter = filter) => {
      const trash = showDeleted ? "&include_deleted=true" : "";
      const base = allAccounts
        ? `/api/ledger/transactions`
        : `/api/accounts/${accountId}/transactions`;
      const data = await api.get<{
        transactions: TxnRow[];
        total: number;
        account_total: number;
      }>(`${base}?limit=100&offset=${start}${trash}${filterQuery(current)}`);
      setTotal(data.total);
      setAccountTotal(data.account_total);
      setRows((prev) => (append ? [...prev, ...data.transactions] : data.transactions));
      setOffset(start + data.transactions.length);
    },
    [accountId, showDeleted, filter, allAccounts],
  );

  useEffect(() => {
    setRows([]);
    setEditing(undefined);
    void load(0, false).catch((err: Error) => setError(err.message));
  }, [accountId, load]);

  useEffect(() => {
    void Promise.all([
      api.get<{ categories: Category[] }>("/api/categories"),
      api.get<{ tags: Tag[] }>("/api/tags"),
      api.get<{ views: SavedView[] }>("/api/views"),
    ]).then(([c, tg, v]) => {
      setCategories(c.categories);
      setTags(tg.tags);
      setViews(v.views);
    });
  }, []);

  useEffect(() => {
    if (newTxnNonce > 0) setEditing(null);
  }, [newTxnNonce]);

  function applyDraft(event?: FormEvent) {
    event?.preventDefault();
    const next: TxnFilter = {};
    if (draft.date_from) next.date_from = draft.date_from;
    if (draft.date_to) next.date_to = draft.date_to;
    if (draft.payee_id) next.payee_id = draft.payee_id;
    else if (draft.payee_query) next.payee_q = draft.payee_query.trim();
    if (draft.categ_id) next.categ_id = draft.categ_id;
    if (draft.trans_code) next.trans_code = draft.trans_code;
    if (draft.status !== "*") next.status = draft.status;
    if (draft.amount_min) next.amount_min = draft.amount_min;
    if (draft.amount_max) next.amount_max = draft.amount_max;
    if (draft.notes) next.notes = draft.notes;
    if (draft.number) next.number = draft.number;
    if (draft.tag_id) next.tag_id = draft.tag_id;
    if (draft.followup) next.followup = true;
    setFilter(next);
    setError(null);
  }

  function resetFilter() {
    setDraft({ payee_query: "", status: "*" });
    setFilter(EMPTY_FILTER);
    setViewId("");
  }

  function applyView(id: number) {
    const view = views.find((v) => v.id === id);
    if (!view) return;
    setViewId(id);
    const f = view.filter || {};
    setDraft({
      ...f,
      payee_query: f.payee_q ?? "",
      status: f.status === undefined ? "*" : f.status,
    });
    setFilter(f);
  }

  async function saveCurrentView() {
    const name = window.prompt(t("viewName"));
    if (!name?.trim()) return;
    try {
      const created = await api.post<SavedView>("/api/views", {
        name: name.trim(),
        account_id: accountId,
        filter,
      });
      setViews((prev) => [...prev, created]);
      setViewId(created.id);
    } catch (err) {
      setError(err instanceof Error ? err.message : t("saveError"));
    }
  }

  async function removeView() {
    if (viewId === "") return;
    try {
      await api.del(`/api/views/${viewId}`);
      setViews((prev) => prev.filter((v) => v.id !== viewId));
      setViewId("");
    } catch (err) {
      setError(err instanceof Error ? err.message : t("saveError"));
    }
  }

  async function saveStatement(event: FormEvent) {
    event.preventDefault();
    setError(null);
    try {
      await api.put(`/api/accounts/${accountId}/statement`, {
        statement_locked: stmt.statement_locked,
        statement_date: stmt.statement_date || null,
        credit_limit: stmt.credit_limit || "0",
        minimum_payment: stmt.minimum_payment || "0",
      });
      onChanged();
    } catch (err) {
      setError(err instanceof Error ? err.message : t("saveError"));
    }
  }

  async function cycleStatus(id: number) {
    try {
      const updated = await api.post<TxnRow>(`/api/transactions/${id}/status`);
      setRows((prev) => prev.map((r) => (r.trans_id === id ? { ...r, status: updated.status } : r)));
      onChanged();
    } catch (err) {
      setError(err instanceof Error ? err.message : t("statementLocked"));
    }
  }

  function dateLabel(value: string) {
    return value.slice(0, 10);
  }

  const locked = Boolean(account?.statement_locked) && Boolean(account?.statement_date);
  const shown = useMemo(
    () =>
      sortBy(rows, sort, (row, key) => {
        if (key === "payee") return row.payee_name ?? row.to_account_name ?? "";
        if (key === "account") return row.from_account_name ?? "";
        if (key === "category") return row.category_path ?? "";
        if (key === "date") return row.trans_date;
        if (key === "status") return row.status;
        if (key === "number") return row.transaction_number;
        if (key === "withdrawal") return row.withdrawal ?? "";
        if (key === "deposit") return row.deposit ?? "";
        if (key === "balance") return row.running_balance;
        return "";
      }),
    [rows, sort],
  );
  const colCount = allAccounts ? 8 : 8;

  return (
    <div className="register">
      <header className="register-head">
        <h2
          onContextMenu={(e) => {
            if (!onEditAccount) return;
            e.preventDefault();
            onEditAccount();
          }}
        >
          {accountName}
        </h2>
        <div className="register-actions">
          {onEditAccount && (
            <button type="button" className="ghost" onClick={onEditAccount}>
              {t("accountProperties")}
            </button>
          )}
          <button type="button" className="ghost" onClick={() => setShowDeleted((v) => !v)}>
            {showDeleted ? t("hideDeleted") : t("showDeleted")}
          </button>
          <button
            type="button"
            onClick={() => {
              setEditorAccount(allAccounts ? accounts.find((a) => a.status === "Open")?.account_id ?? 0 : accountId);
              setEditing(null);
            }}
          >
            {t("newTransaction")}
          </button>
        </div>
      </header>

      {!allAccounts && account && (
        <div className="balance-strip">
          <div>
            <div className="k">{t("reconBalance")}</div>
            <div className="v">{account.reconciled_formatted ?? "—"}</div>
          </div>
          <div>
            <div className="k">{t("actualBalance")}</div>
            <div className="v">{account.display_formatted}</div>
          </div>
          <div>
            <div className="k">{t("reconDifference")}</div>
            <div className="v">{account.difference_formatted ?? "—"}</div>
          </div>
        </div>
      )}

      {!allAccounts && (
      <>
      <form className="stmt-bar" onSubmit={saveStatement}>
        <span className="k">{t("statement")}</span>
        <label>
          {t("statementDate")}
          <input
            type="date"
            value={stmt.statement_date}
            onChange={(e) => setStmt({ ...stmt, statement_date: e.target.value })}
          />
        </label>
        <label className="chk">
          <input
            type="checkbox"
            checked={stmt.statement_locked}
            onChange={(e) => setStmt({ ...stmt, statement_locked: e.target.checked })}
          />
          {t("statementLock")}
        </label>
        <label>
          {t("creditLimit")}
          <input
            inputMode="decimal"
            value={stmt.credit_limit}
            onChange={(e) => setStmt({ ...stmt, credit_limit: e.target.value })}
          />
        </label>
        <label>
          {t("minPayment")}
          <input
            inputMode="decimal"
            value={stmt.minimum_payment}
            onChange={(e) => setStmt({ ...stmt, minimum_payment: e.target.value })}
          />
        </label>
        <button type="submit" className="ghost">
          {t("saveStatement")}
        </button>
      </form>
      {locked && (
        <p className="k">
          {t("statementLock")} ≤ {account?.statement_date?.slice(0, 10)}
        </p>
      )}
      </>
      )}
      {!allAccounts && <CustomFields refType="Bank Account" refId={accountId} t={t} />}

      <form className="mgr-form filter-bar" onSubmit={applyDraft}>
        <label>
          {t("dateFrom")}
          <input
            type="date"
            value={draft.date_from ?? ""}
            onChange={(e) => setDraft({ ...draft, date_from: e.target.value })}
          />
        </label>
        <label>
          {t("dateTo")}
          <input
            type="date"
            value={draft.date_to ?? ""}
            onChange={(e) => setDraft({ ...draft, date_to: e.target.value })}
          />
        </label>
        <PayeeField
          value={draft.payee_query}
          payeeId={draft.payee_id ?? 0}
          t={t}
          listId="filter-payee"
          onChange={(q, id) => setDraft({ ...draft, payee_query: q, payee_id: id || undefined })}
        />
        <label>
          {t("category")}
          <select
            value={draft.categ_id ?? 0}
            onChange={(e) => setDraft({ ...draft, categ_id: Number(e.target.value) || undefined })}
          >
            <option value={0}>—</option>
            {categories.map((c) => (
              <option key={c.categ_id} value={c.categ_id}>
                {c.path}
              </option>
            ))}
          </select>
        </label>
        <label>
          {t("type")}
          <select
            value={draft.trans_code ?? ""}
            onChange={(e) => setDraft({ ...draft, trans_code: e.target.value || undefined })}
          >
            <option value="">{t("allTypes")}</option>
            <option value="Withdrawal">{t("typeWithdrawal")}</option>
            <option value="Deposit">{t("typeDeposit")}</option>
            <option value="Transfer">{t("typeTransfer")}</option>
          </select>
        </label>
        <label>
          {t("status")}
          <select
            value={draft.status}
            onChange={(e) => setDraft({ ...draft, status: e.target.value })}
          >
            <option value="*">{t("allStatuses")}</option>
            <option value="">{t("statusNone")}</option>
            <option value="R">{t("statusR")}</option>
            <option value="V">{t("statusV")}</option>
            <option value="F">{t("statusF")}</option>
            <option value="D">{t("statusD")}</option>
          </select>
        </label>
        <label>
          {t("amountMin")}
          <input
            inputMode="decimal"
            value={draft.amount_min ?? ""}
            onChange={(e) => setDraft({ ...draft, amount_min: e.target.value })}
          />
        </label>
        <label>
          {t("amountMax")}
          <input
            inputMode="decimal"
            value={draft.amount_max ?? ""}
            onChange={(e) => setDraft({ ...draft, amount_max: e.target.value })}
          />
        </label>
        <label>
          {t("notes")}
          <input
            value={draft.notes ?? ""}
            onChange={(e) => setDraft({ ...draft, notes: e.target.value })}
          />
        </label>
        <label>
          {t("tags")}
          <select
            value={draft.tag_id ?? 0}
            onChange={(e) => setDraft({ ...draft, tag_id: Number(e.target.value) || undefined })}
          >
            <option value={0}>—</option>
            {tags.map((tag) => (
              <option key={tag.tag_id} value={tag.tag_id}>
                {tag.name}
              </option>
            ))}
          </select>
        </label>
        <label className="chk">
          <input
            type="checkbox"
            checked={Boolean(draft.followup)}
            onChange={(e) => setDraft({ ...draft, followup: e.target.checked })}
          />
          {t("followUpOnly")}
        </label>
        <div className="mgr-actions">
          <button type="submit">{t("apply")}</button>
          <button type="button" className="ghost" onClick={resetFilter}>
            {t("clearFilter")}
          </button>
        </div>
        <label>
          {t("savedViews")}
          <select
            value={viewId}
            onChange={(e) => {
              const v = e.target.value;
              if (!v) {
                setViewId("");
                return;
              }
              applyView(Number(v));
            }}
          >
            <option value="">—</option>
            {views.map((v) => (
              <option key={v.id} value={v.id}>
                {v.name}
              </option>
            ))}
          </select>
        </label>
        <div className="mgr-actions">
          <button type="button" className="ghost" onClick={() => void saveCurrentView()}>
            {t("saveView")}
          </button>
          {viewId !== "" && (
            <button type="button" className="ghost danger" onClick={() => void removeView()}>
              {t("deleteView")}
            </button>
          )}
        </div>
      </form>
      <p className="k">
        {total} {t("matching")}
        {accountTotal !== total ? ` / ${accountTotal}` : ""}
      </p>

      {error && <p className="error-text">{error}</p>}
      <div className="register-table-wrap">
        <table className="register-table">
          <thead>
            <tr>
              <SortTh label={t("date")} k="date" sort={sort} onSort={(k) => setSort((s) => toggleSort(s, k))} />
              <SortTh label={t("status")} k="status" sort={sort} onSort={(k) => setSort((s) => toggleSort(s, k))} />
              <SortTh
                label={t("number")}
                k="number"
                sort={sort}
                onSort={(k) => setSort((s) => toggleSort(s, k))}
                className="col-extra"
              />
              {allAccounts && (
                <SortTh label={t("account")} k="account" sort={sort} onSort={(k) => setSort((s) => toggleSort(s, k))} />
              )}
              <SortTh label={t("payee")} k="payee" sort={sort} onSort={(k) => setSort((s) => toggleSort(s, k))} />
              <SortTh label={t("category")} k="category" sort={sort} onSort={(k) => setSort((s) => toggleSort(s, k))} />
              <SortTh
                label={t("withdrawal")}
                k="withdrawal"
                sort={sort}
                onSort={(k) => setSort((s) => toggleSort(s, k))}
                className="num"
              />
              <SortTh
                label={t("deposit")}
                k="deposit"
                sort={sort}
                onSort={(k) => setSort((s) => toggleSort(s, k))}
                className="num"
              />
              {!allAccounts && (
                <SortTh
                  label={t("balance")}
                  k="balance"
                  sort={sort}
                  onSort={(k) => setSort((s) => toggleSort(s, k))}
                  className="num col-extra"
                />
              )}
            </tr>
          </thead>
          <tbody>
            {rows.length === 0 && (
              <tr>
                <td colSpan={colCount} className="k">
                  {t("emptyRegister")}
                </td>
              </tr>
            )}
            {shown.map((row) => (
              <tr
                key={row.trans_id}
                className={`${row.status === "V" ? "void" : ""}${row.deleted_time ? " trashed" : ""}${row.color > 0 ? ` c-${row.color}` : ""}`}
                onClick={() => {
                  setEditorAccount(row.account_id);
                  setEditing(row.trans_id);
                }}
              >
                <td>{dateLabel(row.trans_date)}</td>
                <td>
                  <button
                    type="button"
                    className={`status-pill s-${row.status || "none"}`}
                    onClick={(e) => {
                      e.stopPropagation();
                      void cycleStatus(row.trans_id);
                    }}
                    title={t(STATUS_LABEL[row.status] ?? "statusNone")}
                  >
                    {row.status || "·"}
                  </button>
                </td>
                <td className="col-extra">{row.transaction_number}</td>
                {allAccounts && <td>{row.from_account_name ?? ""}</td>}
                <td>
                  <button
                    type="button"
                    className="linkish"
                    onClick={(e) => {
                      e.stopPropagation();
                      setEditorAccount(row.account_id);
                      setEditing(row.trans_id);
                    }}
                  >
                    {row.trans_code === "Transfer"
                      ? allAccounts
                        ? `→ ${row.to_account_name ?? ""}`
                        : row.account_id === accountId
                          ? `→ ${row.to_account_name ?? ""}`
                          : `← ${row.from_account_name ?? ""}`
                      : (row.payee_name ?? "")}
                    {row.is_split ? " ▸" : ""}
                    {row.attachment_count > 0 ? " 📎" : ""}
                    {row.followup_id > 0 ? " !" : ""}
                  </button>
                </td>
                <td>{row.category_path ?? (row.is_split ? t("splits") : "")}</td>
                <td className="num">{row.withdrawal ?? ""}</td>
                <td className="num">{row.deposit ?? ""}</td>
                {!allAccounts && <td className="num col-extra">{row.running_balance}</td>}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      {offset < total && (
        <button type="button" className="ghost" onClick={() => void load(offset, true)}>
          {t("loadMore")} ({offset}/{total})
        </button>
      )}
      {editing !== undefined && (
        <div className="drawer">
          <Editor
            accountId={editorAccount || accountId}
            accounts={accounts}
            transId={editing}
            pickAccount={allAccounts && editing === null}
            t={t}
            onClose={() => setEditing(undefined)}
            onSaved={() => {
              setEditing(undefined);
              void load(0, false);
              onChanged();
            }}
          />
        </div>
      )}
    </div>
  );
}
