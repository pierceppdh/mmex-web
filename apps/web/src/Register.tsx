import { FormEvent, useCallback, useEffect, useMemo, useRef, useState } from "react";
import { CustomFields } from "./CustomFields";
import { Editor } from "./Editor";
import { PayeeField } from "./PayeeField";
import { SortTh, sortBy, toggleSort, type SortState } from "./Sortable";
import { api } from "./api";
import { cents } from "./money";
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
  const [filterNet, setFilterNet] = useState<string | null>(null);
  const [filterActive, setFilterActive] = useState(false);
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
  const [sort, setSort] = useState<SortState>({ key: "date", dir: "desc" });
  const [editorAccount, setEditorAccount] = useState(accountId);
  const [selected, setSelected] = useState<Set<number>>(() => new Set());
  const [bulkPayeeQuery, setBulkPayeeQuery] = useState("");
  const [bulkPayeeId, setBulkPayeeId] = useState(0);
  const [bulkCateg, setBulkCateg] = useState("");
  const [bulkAccount, setBulkAccount] = useState("");
  const [bulkBusy, setBulkBusy] = useState(false);
  const [bulkNote, setBulkNote] = useState<string | null>(null);
  const anchorRef = useRef<number | null>(null);
  const shiftRef = useRef(false);
  const selectAllRef = useRef<HTMLInputElement>(null);

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
        filter_net_formatted?: string;
        filter_active?: boolean;
      }>(`${base}?limit=100&offset=${start}${trash}${filterQuery(current)}`);
      setTotal(data.total);
      setAccountTotal(data.account_total);
      setFilterNet(data.filter_net_formatted ?? null);
      setFilterActive(Boolean(data.filter_active));
      setRows((prev) => (append ? [...prev, ...data.transactions] : data.transactions));
      setOffset(start + data.transactions.length);
    },
    [accountId, showDeleted, filter, allAccounts],
  );

  useEffect(() => {
    setRows([]);
    setEditing(undefined);
    setSelected(new Set());
    setBulkNote(null);
    anchorRef.current = null;
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

  function toggleRow(id: number, index: number, shift: boolean) {
    const anchor = anchorRef.current;
    setSelected((prev) => {
      const next = new Set(prev);
      const turningOn = !prev.has(id);
      if (shift && anchor != null) {
        const start = Math.min(anchor, index);
        const end = Math.max(anchor, index);
        for (let i = start; i <= end; i += 1) {
          const row = shown[i];
          if (!row || row.deleted_time) continue;
          if (turningOn) next.add(row.trans_id);
          else next.delete(row.trans_id);
        }
      } else if (turningOn) {
        next.add(id);
      } else {
        next.delete(id);
      }
      return next;
    });
    anchorRef.current = index;
    setBulkNote(null);
  }

  async function runBulk(body: {
    action: "delete" | "set_payee" | "set_category" | "set_account";
    payee_id?: number;
    categ_id?: number;
    account_id?: number;
  }) {
    const trans_ids = [...selected];
    if (!trans_ids.length || bulkBusy) return;
    setBulkBusy(true);
    setError(null);
    try {
      const result = await api.post<{
        updated: number;
        skipped: { trans_id: number; reason: string }[];
      }>("/api/transactions/bulk", { trans_ids, ...body });
      setBulkNote(result.skipped.length ? t("bulkSkipped") : null);
      if (result.updated > 0) {
        setSelected(new Set());
        anchorRef.current = null;
        setBulkPayeeQuery("");
        setBulkPayeeId(0);
        setBulkCateg("");
        setBulkAccount("");
        await load(0, false);
        onChanged();
      }
    } catch (err) {
      const msg = err instanceof Error ? err.message : t("saveError");
      setError(msg.toLowerCase().includes("locked") ? t("statementLocked") : msg);
    } finally {
      setBulkBusy(false);
    }
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
  const selectable = useMemo(() => shown.filter((row) => !row.deleted_time), [shown]);
  const allSelected = selectable.length > 0 && selectable.every((row) => selected.has(row.trans_id));
  const someSelected = selectable.some((row) => selected.has(row.trans_id));
  const colCount = 9;

  useEffect(() => {
    if (selectAllRef.current) {
      selectAllRef.current.indeterminate = someSelected && !allSelected;
    }
  }, [someSelected, allSelected]);

  return (
    <div className="register">
      <header className="register-head">
        <h2>{accountName}</h2>
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
          <div className={filterActive ? undefined : "dim"}>
            <div className="k">{t("filterBalance")}</div>
            <div className="v">{filterNet ?? "—"}</div>
          </div>
        </div>
      )}

      {!allAccounts && locked && (
        <p className="k">
          {t("statementLock")} ≤ {account?.statement_date?.slice(0, 10)}
        </p>
      )}
      {!allAccounts && (
        <details className="fold">
          <summary>{t("customFields")}</summary>
          <CustomFields refType="Bank Account" refId={accountId} t={t} />
        </details>
      )}

      <details className="fold">
        <summary>{t("filters")}</summary>
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
        </form>
      </details>
      <div className="register-tools">
        <p className="k">
          {total} {t("matching")}
          {accountTotal !== total ? ` / ${accountTotal}` : ""}
        </p>
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
        <button type="button" className="ghost" onClick={() => void saveCurrentView()}>
          {t("saveView")}
        </button>
        {viewId !== "" && (
          <button type="button" className="ghost danger" onClick={() => void removeView()}>
            {t("deleteView")}
          </button>
        )}
      </div>

      {selected.size > 0 && (
        <div className="bulk-bar" role="region" aria-label={t("bulkActions")}>
          <p className="k">
            {selected.size} {selected.size > 1 ? t("selectedMany") : t("selected")}
          </p>
          <div className="bulk-field">
            <label>
              {t("account")}
              <select value={bulkAccount} onChange={(e) => setBulkAccount(e.target.value)}>
                <option value="">{t("choose")}</option>
                {accounts.map((a) => (
                  <option key={a.account_id} value={a.account_id}>
                    {a.name}
                  </option>
                ))}
              </select>
            </label>
            <button
              type="button"
              disabled={bulkBusy || bulkAccount === ""}
              onClick={() =>
                void runBulk({ action: "set_account", account_id: Number(bulkAccount) })
              }
            >
              {t("applyChange")}
            </button>
          </div>
          <div className="bulk-field">
            <PayeeField
              value={bulkPayeeQuery}
              payeeId={bulkPayeeId}
              t={t}
              listId="bulk-payee"
              onChange={(name, id) => {
                setBulkPayeeQuery(name);
                setBulkPayeeId(id);
              }}
            />
            <button
              type="button"
              disabled={bulkBusy || bulkPayeeId <= 0}
              onClick={() => void runBulk({ action: "set_payee", payee_id: bulkPayeeId })}
            >
              {t("applyChange")}
            </button>
          </div>
          <div className="bulk-field">
            <label>
              {t("category")}
              <select value={bulkCateg} onChange={(e) => setBulkCateg(e.target.value)}>
                <option value="">{t("choose")}</option>
                <option value="-1">{t("noCategory")}</option>
                {categories.map((c) => (
                  <option key={c.categ_id} value={c.categ_id}>
                    {c.path}
                  </option>
                ))}
              </select>
            </label>
            <button
              type="button"
              disabled={bulkBusy || bulkCateg === ""}
              onClick={() => void runBulk({ action: "set_category", categ_id: Number(bulkCateg) })}
            >
              {t("applyChange")}
            </button>
          </div>
          <button
            type="button"
            className="ghost danger"
            disabled={bulkBusy}
            onClick={() => {
              if (!window.confirm(t("confirmBulkDelete"))) return;
              void runBulk({ action: "delete" });
            }}
          >
            {t("bulkDelete")}
          </button>
          <button
            type="button"
            className="ghost"
            disabled={bulkBusy}
            onClick={() => {
              setSelected(new Set());
              anchorRef.current = null;
              setBulkNote(null);
            }}
          >
            {t("cancel")}
          </button>
        </div>
      )}
      {bulkNote && <p className="k bulk-note">{bulkNote}</p>}
      {error && <p className="error-text">{error}</p>}
      <div className="register-table-wrap">
        <table className="register-table">
          <thead>
            <tr>
              <th className="col-pick">
                <input
                  ref={selectAllRef}
                  type="checkbox"
                  checked={allSelected}
                  disabled={selectable.length === 0}
                  aria-label={t("selectAll")}
                  onClick={(e) => e.stopPropagation()}
                  onChange={() => {
                    setBulkNote(null);
                    setSelected((prev) => {
                      const next = new Set(prev);
                      if (allSelected) {
                        for (const row of selectable) next.delete(row.trans_id);
                      } else {
                        for (const row of selectable) next.add(row.trans_id);
                      }
                      return next;
                    });
                  }}
                />
              </th>
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
            {shown.map((row, index) => (
              <tr
                key={row.trans_id}
                className={`${row.status === "V" ? "void" : ""}${row.deleted_time ? " trashed" : ""}${row.color > 0 ? ` c-${row.color}` : ""}${selected.has(row.trans_id) ? " picked" : ""}`}
                onClick={() => {
                  setEditorAccount(row.account_id);
                  setEditing(row.trans_id);
                }}
              >
                <td
                  className="col-pick"
                  onClick={(e) => {
                    e.stopPropagation();
                    if (e.target !== e.currentTarget || row.deleted_time) return;
                    toggleRow(row.trans_id, index, e.shiftKey);
                  }}
                >
                  <input
                    type="checkbox"
                    checked={selected.has(row.trans_id)}
                    disabled={Boolean(row.deleted_time)}
                    aria-label={t("selectRow")}
                    onPointerDown={(e) => {
                      shiftRef.current = e.shiftKey;
                    }}
                    onClick={(e) => e.stopPropagation()}
                    onChange={() => {
                      if (row.deleted_time) return;
                      toggleRow(row.trans_id, index, shiftRef.current);
                    }}
                  />
                </td>
                <td>{dateLabel(row.trans_date)}</td>
                <td>
                  <button
                    type="button"
                    className={`status-pill s-${row.status || "none"}`}
                    onClick={(e) => {
                      e.stopPropagation();
                      void cycleStatus(row.trans_id);
                    }}
                    aria-label={t(STATUS_LABEL[row.status] ?? "statusNone")}
                    title={t(STATUS_LABEL[row.status] ?? "statusNone")}
                  >
                    {t(STATUS_LABEL[row.status] ?? "statusNone")}
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
                <td className="num">{cents(row.withdrawal)}</td>
                <td className="num">{cents(row.deposit)}</td>
                {!allAccounts && <td className="num col-extra">{cents(row.running_balance)}</td>}
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
        <div
          className="drawer-backdrop"
          role="presentation"
          onClick={() => setEditing(undefined)}
        />
      )}
      {editing !== undefined && (
        <div className="drawer">
          <Editor
            accountId={editorAccount || accountId}
            accounts={accounts}
            transId={editing}
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
