import { FormEvent, useEffect, useMemo, useState } from "react";
import { api } from "./api";
import { CustomFields } from "./CustomFields";
import { PayeeField, resolvePayeeId } from "./PayeeField";
import { SortTh, sortBy, toggleSort, type SortState } from "./Sortable";
import type { MessageKey } from "./i18n";
import type { Account, Category } from "./types";

type RepeatMeta = { id: number; key: string; label_fr: string; label_en: string };

type Bill = {
  bd_id: number;
  account_id: number;
  account_name: string;
  to_account_id: number;
  to_account_name: string | null;
  payee_id: number;
  payee_name: string | null;
  trans_code: string;
  trans_amount: string;
  categ_id: number;
  next_occurrence_date: string;
  repeat_type: number;
  auto_mode: number;
  num_occurrences: number;
  notes: string;
  repeat_label_fr: string;
  repeat_label_en: string;
  auto_label_fr: string;
  auto_label_en: string;
  days_until: number;
  overdue: boolean;
  category_path: string | null;
};

function formFromBill(bill: Bill): typeof EMPTY {
  const intervalType = bill.repeat_type >= 11 && bill.repeat_type <= 14;
  return {
    account_id: bill.account_id,
    trans_code: bill.trans_code as typeof EMPTY.trans_code,
    trans_amount: bill.trans_amount,
    next_occurrence_date: bill.next_occurrence_date.slice(0, 10),
    payee_id: bill.payee_id > 0 ? bill.payee_id : 0,
    payee_query: bill.payee_name ?? "",
    to_account_id: bill.to_account_id > 0 ? bill.to_account_id : 0,
    categ_id: bill.categ_id > 0 ? bill.categ_id : 0,
    repeat_type: bill.repeat_type,
    auto_mode: bill.auto_mode,
    interval: intervalType ? bill.num_occurrences : 1,
    remaining: intervalType ? -1 : bill.num_occurrences,
    notes: bill.notes || "",
  };
}

type Props = {
  accounts: Account[];
  locale: "fr" | "en";
  t: (key: MessageKey) => string;
  onChanged: () => void;
};

const EMPTY = {
  account_id: 0,
  trans_code: "Withdrawal" as "Withdrawal" | "Deposit" | "Transfer",
  trans_amount: "",
  next_occurrence_date: new Date().toISOString().slice(0, 10),
  payee_id: 0,
  payee_query: "",
  to_account_id: 0,
  categ_id: 0,
  repeat_type: 3,
  auto_mode: 0,
  interval: 1,
  remaining: -1,
  notes: "",
};

export function Scheduled({ accounts, locale, t, onChanged }: Props) {
  const [rows, setRows] = useState<Bill[]>([]);
  const [sort, setSort] = useState<SortState>({ key: "nextDate", dir: "asc" });
  const shown = useMemo(
    () =>
      sortBy(rows, sort, (row, k) =>
        k === "amount"
          ? row.trans_amount
          : k === "payee"
            ? row.payee_name ?? ""
            : k === "frequency"
              ? row.repeat_label_fr
              : row.next_occurrence_date,
      ),
    [rows, sort],
  );
  const [overdue, setOverdue] = useState(0);
  const [meta, setMeta] = useState<{ repeat_types: RepeatMeta[]; auto_modes: RepeatMeta[] }>({
    repeat_types: [],
    auto_modes: [],
  });
  const [categories, setCategories] = useState<Category[]>([]);
  const [form, setForm] = useState(EMPTY);
  const [editId, setEditId] = useState<number | null>(null);
  const [error, setError] = useState<string | null>(null);

  async function load() {
    const [list, m, c] = await Promise.all([
      api.get<{ scheduled: Bill[]; overdue: number }>("/api/scheduled"),
      api.get<{ repeat_types: RepeatMeta[]; auto_modes: RepeatMeta[] }>("/api/scheduled/meta"),
      api.get<{ categories: Category[] }>("/api/categories"),
    ]);
    setRows(list.scheduled);
    setOverdue(list.overdue);
    setMeta(m);
    setCategories(c.categories);
    if (!form.account_id && accounts[0]) {
      setForm((f) => ({ ...f, account_id: f.account_id || accounts[0].account_id }));
    }
  }

  useEffect(() => {
    void load().catch((err: Error) => setError(err.message));
  }, []);

  const needsInterval = form.repeat_type >= 11 && form.repeat_type <= 14;

  async function onSubmit(event: FormEvent) {
    event.preventDefault();
    setError(null);
    const resolvedPayee =
      form.trans_code === "Transfer" ? -1 : await resolvePayeeId(form.payee_query, form.payee_id);
    const payload = {
      account_id: form.account_id,
      trans_code: form.trans_code,
      trans_amount: form.trans_amount,
      next_occurrence_date: form.next_occurrence_date,
      payee_id: resolvedPayee,
      to_account_id: form.trans_code === "Transfer" ? form.to_account_id : undefined,
      categ_id: form.categ_id || -1,
      repeat_type: form.repeat_type,
      auto_mode: form.auto_mode,
      interval: form.interval,
      remaining: form.remaining,
      notes: form.notes,
    };
    try {
      if (editId == null) await api.post("/api/scheduled", payload);
      else await api.put(`/api/scheduled/${editId}`, payload);
      setForm({ ...EMPTY, account_id: form.account_id });
      setEditId(null);
      await load();
      onChanged();
    } catch (err) {
      setError(err instanceof Error ? err.message : t("saveError"));
    }
  }

  async function act(id: number, action: "enter" | "skip" | "delete") {
    setError(null);
    try {
      if (action === "delete") await api.del(`/api/scheduled/${id}`);
      else await api.post(`/api/scheduled/${id}/${action}`);
      if (editId === id) {
        setEditId(null);
        setForm({ ...EMPTY, account_id: form.account_id });
      }
      await load();
      onChanged();
    } catch (err) {
      setError(err instanceof Error ? err.message : t("saveError"));
    }
  }

  return (
    <section className="scheduled">
      <header className="register-head">
        <h2>
          {t("scheduled")} {overdue > 0 ? <span className="count">{overdue}</span> : null}
        </h2>
        <button
          type="button"
          className="ghost"
          onClick={() =>
            void api
              .post("/api/scheduled/process-due")
              .then(() => load())
              .then(onChanged)
              .catch((err: Error) => setError(err.message))
          }
        >
          {t("enterDue")}
        </button>
      </header>
      <form className="mgr-form" onSubmit={onSubmit}>
        <label>
          {t("account")}
          <select
            value={form.account_id}
            onChange={(e) => setForm({ ...form, account_id: Number(e.target.value) })}
            required
          >
            {accounts.map((a) => (
              <option key={a.account_id} value={a.account_id}>
                {a.name}
              </option>
            ))}
          </select>
        </label>
        <label>
          {t("type")}
          <select
            value={form.trans_code}
            onChange={(e) =>
              setForm({ ...form, trans_code: e.target.value as typeof form.trans_code })
            }
          >
            <option value="Withdrawal">{t("typeWithdrawal")}</option>
            <option value="Deposit">{t("typeDeposit")}</option>
            <option value="Transfer">{t("typeTransfer")}</option>
          </select>
        </label>
        <label>
          {t("amount")}
          <input
            inputMode="decimal"
            value={form.trans_amount}
            onChange={(e) => setForm({ ...form, trans_amount: e.target.value })}
            required
          />
        </label>
        <label>
          {t("nextDate")}
          <input
            type="date"
            value={form.next_occurrence_date}
            onChange={(e) => setForm({ ...form, next_occurrence_date: e.target.value })}
            required
          />
        </label>
        {form.trans_code === "Transfer" ? (
          <label>
            {t("transferTo")}
            <select
              value={form.to_account_id}
              onChange={(e) => setForm({ ...form, to_account_id: Number(e.target.value) })}
              required
            >
              <option value={0}>—</option>
              {accounts
                .filter((a) => a.account_id !== form.account_id)
                .map((a) => (
                  <option key={a.account_id} value={a.account_id}>
                    {a.name}
                  </option>
                ))}
            </select>
          </label>
        ) : (
          <PayeeField
            value={form.payee_query}
            payeeId={form.payee_id}
            t={t}
            required
            listId="sched-payee"
            onChange={(name, id) => setForm({ ...form, payee_query: name, payee_id: id })}
          />
        )}
        <label>
          {t("category")}
          <select
            value={form.categ_id}
            onChange={(e) => setForm({ ...form, categ_id: Number(e.target.value) })}
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
          {t("frequency")}
          <select
            value={form.repeat_type}
            onChange={(e) => setForm({ ...form, repeat_type: Number(e.target.value) })}
          >
            {meta.repeat_types.map((r) => (
              <option key={r.id} value={r.id}>
                {locale === "en" ? r.label_en : r.label_fr}
              </option>
            ))}
          </select>
        </label>
        <label>
          {t("autoEnter")}
          <select
            value={form.auto_mode}
            onChange={(e) => setForm({ ...form, auto_mode: Number(e.target.value) })}
          >
            {meta.auto_modes.map((r) => (
              <option key={r.id} value={r.id}>
                {locale === "en" ? r.label_en : r.label_fr}
              </option>
            ))}
          </select>
        </label>
        {needsInterval && (
          <label>
            {t("interval")}
            <input
              inputMode="numeric"
              value={String(form.interval)}
              onChange={(e) => setForm({ ...form, interval: Number(e.target.value) || 1 })}
            />
          </label>
        )}
        {!needsInterval && form.repeat_type !== 0 && (
          <label>
            {t("remaining")}
            <input
              inputMode="numeric"
              value={String(form.remaining)}
              onChange={(e) => setForm({ ...form, remaining: Number(e.target.value) })}
            />
          </label>
        )}
        <div className="mgr-actions">
          <button type="submit">{editId == null ? t("newItem") : t("save")}</button>
          {editId != null && (
            <button
              type="button"
              className="ghost"
              onClick={() => {
                setEditId(null);
                setForm({ ...EMPTY, account_id: form.account_id });
              }}
            >
              {t("cancel")}
            </button>
          )}
        </div>
      </form>
      <CustomFields refType="Repeating Transaction" refId={editId} t={t} />
      {error && <p className="error-text">{error}</p>}
      <table className="mgr-table">
        <thead>
          <tr>
            <SortTh label={t("nextDate")} k="nextDate" sort={sort} onSort={(k) => setSort((s) => toggleSort(s, k))} />
            <SortTh label={t("payee")} k="payee" sort={sort} onSort={(k) => setSort((s) => toggleSort(s, k))} />
            <SortTh label={t("frequency")} k="frequency" sort={sort} onSort={(k) => setSort((s) => toggleSort(s, k))} />
            <SortTh label={t("amount")} k="amount" sort={sort} onSort={(k) => setSort((s) => toggleSort(s, k))} className="num" />
            <th />
          </tr>
        </thead>
        <tbody>
          {rows.length === 0 && (
            <tr>
              <td colSpan={5} className="k">
                {t("noScheduled")}
              </td>
            </tr>
          )}
          {shown.map((row) => (
            <tr key={row.bd_id} className={row.overdue ? "overdue" : ""}>
              <td>
                <button
                  type="button"
                  className="linkish"
                  onClick={() => {
                    setError(null);
                    void api
                      .get<Bill>(`/api/scheduled/${row.bd_id}`)
                      .then((detail) => {
                        setEditId(detail.bd_id);
                        setForm(formFromBill(detail));
                      })
                      .catch((err: Error) => setError(err.message));
                  }}
                >
                  {row.next_occurrence_date.slice(0, 10)}
                </button>
              </td>
              <td>
                {row.trans_code === "Transfer"
                  ? `→ ${row.to_account_name ?? row.account_name}`
                  : (row.payee_name ?? "")}
                <div className="k">{row.category_path}</div>
              </td>
              <td>
                {locale === "en" ? row.repeat_label_en : row.repeat_label_fr}
                <div className="k">{locale === "en" ? row.auto_label_en : row.auto_label_fr}</div>
              </td>
              <td className="num">{row.trans_amount}</td>
              <td>
                <span className="row-actions">
                  <button type="button" onClick={() => void act(row.bd_id, "enter")}>
                    {t("enterNow")}
                  </button>
                  <button type="button" className="ghost" onClick={() => void act(row.bd_id, "skip")}>
                    {t("skip")}
                  </button>
                  <button
                    type="button"
                    className="ghost danger"
                    onClick={() => void act(row.bd_id, "delete")}
                  >
                    ×
                  </button>
                </span>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </section>
  );
}
