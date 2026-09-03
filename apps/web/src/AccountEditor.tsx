import { FormEvent, useEffect, useState } from "react";
import { api } from "./api";
import type { MessageKey } from "./i18n";

type Detail = {
  account_id: number;
  name: string;
  account_type: string;
  account_num: string;
  status: string;
  notes: string;
  held_at: string;
  website: string;
  contact_info: string;
  access_info: string;
  initial_bal: string;
  initial_date: string;
  favorite: boolean;
  currency_id: number;
  statement_locked: number;
  statement_date: string;
  minimum_balance: string;
  credit_limit: string;
  interest_rate: string;
  payment_due_date: string;
  minimum_payment: string;
  account_types: string[];
  account_statuses: string[];
};

type Currency = { currency_id: number; name: string; symbol: string };

const TYPES = [
  "Cash",
  "Checking",
  "Credit Card",
  "Term",
  "Loan",
  "Investment",
  "Asset",
  "Shares",
];

const EMPTY: Detail = {
  account_id: 0,
  name: "",
  account_type: "Checking",
  account_num: "",
  status: "Open",
  notes: "",
  held_at: "",
  website: "",
  contact_info: "",
  access_info: "",
  initial_bal: "0",
  initial_date: "",
  favorite: false,
  currency_id: 0,
  statement_locked: 0,
  statement_date: "",
  minimum_balance: "0",
  credit_limit: "0",
  interest_rate: "0",
  payment_due_date: "",
  minimum_payment: "0",
  account_types: TYPES,
  account_statuses: ["Open", "Closed"],
};

type Props = {
  accountId: number | null;
  t: (key: MessageKey) => string;
  onClose: () => void;
  onSaved: (accountId?: number) => void;
};

export function AccountEditor({ accountId, t, onClose, onSaved }: Props) {
  const creating = accountId == null;
  const [form, setForm] = useState<Detail | null>(creating ? EMPTY : null);
  const [currencies, setCurrencies] = useState<Currency[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    setError(null);
    void api.get<{ currencies: Currency[] }>("/api/currencies").then((c) => {
      setCurrencies(c.currencies);
      if (creating) {
        setForm((prev) =>
          prev && prev.currency_id === 0 && c.currencies[0]
            ? { ...prev, currency_id: c.currencies[0].currency_id }
            : prev,
        );
      }
    });
    if (creating) {
      setForm(EMPTY);
      return;
    }
    void api
      .get<Detail>(`/api/accounts/${accountId}`)
      .then(setForm)
      .catch((err: Error) => setError(err.message));
  }, [accountId, creating]);

  async function onSubmit(event: FormEvent) {
    event.preventDefault();
    if (!form) return;
    setBusy(true);
    setError(null);
    try {
      const payload = { ...form, statement_locked: Boolean(form.statement_locked) };
      if (creating) {
        const created = await api.post<{ account_id: number }>("/api/accounts", payload);
        onSaved(created.account_id);
      } else {
        await api.put(`/api/accounts/${accountId}`, payload);
        onSaved(accountId);
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : t("saveError"));
    } finally {
      setBusy(false);
    }
  }

  if (!form) {
    return (
      <form className="editor" onSubmit={(e) => e.preventDefault()}>
        <header>
          <h2>{creating ? t("newAccount") : t("accountProperties")}</h2>
          <button type="button" className="ghost editor-cancel" onClick={onClose}>
            {t("cancel")}
          </button>
        </header>
        <div className="editor-body">
          <p className="k">{error || t("loading")}</p>
        </div>
      </form>
    );
  }

  return (
    <form className="editor" onSubmit={onSubmit}>
      <header>
        <h2>{t("accountProperties")}</h2>
        <button type="button" className="ghost editor-cancel" onClick={onClose}>
          {t("cancel")}
        </button>
      </header>
      <div className="editor-body">
        {error && <p className="error-text">{error}</p>}
        <label>
          {t("name")}
          <input value={form.name} onChange={(e) => setForm({ ...form, name: e.target.value })} required />
        </label>
        <label>
          {t("accountType")}
          <select
            value={form.account_type}
            onChange={(e) => setForm({ ...form, account_type: e.target.value })}
          >
            {form.account_types.map((ty) => (
              <option key={ty} value={ty}>
                {ty}
              </option>
            ))}
          </select>
        </label>
        <label>
          {t("status")}
          <select value={form.status} onChange={(e) => setForm({ ...form, status: e.target.value })}>
            {form.account_statuses.map((st) => (
              <option key={st} value={st}>
                {st === "Closed" ? t("closed") : t("open")}
              </option>
            ))}
          </select>
        </label>
        <label>
          {t("setBaseCurrency")}
          <select
            value={form.currency_id}
            onChange={(e) => setForm({ ...form, currency_id: Number(e.target.value) })}
          >
            {currencies.map((c) => (
              <option key={c.currency_id} value={c.currency_id}>
                {c.symbol} — {c.name}
              </option>
            ))}
          </select>
        </label>
        <label className="check">
          <input
            type="checkbox"
            checked={form.favorite}
            onChange={(e) => setForm({ ...form, favorite: e.target.checked })}
          />
          {t("favoriteAcct")}
        </label>
        <label>
          {t("accountNum")}
          <input
            value={form.account_num}
            onChange={(e) => setForm({ ...form, account_num: e.target.value })}
          />
        </label>
        <label>
          {t("heldAtBank")}
          <input value={form.held_at} onChange={(e) => setForm({ ...form, held_at: e.target.value })} />
        </label>
        <label>
          {t("website")}
          <input value={form.website} onChange={(e) => setForm({ ...form, website: e.target.value })} />
        </label>
        <label>
          {t("contact")}
          <input
            value={form.contact_info}
            onChange={(e) => setForm({ ...form, contact_info: e.target.value })}
          />
        </label>
        <label>
          {t("accessInfo")}
          <input
            value={form.access_info}
            onChange={(e) => setForm({ ...form, access_info: e.target.value })}
          />
        </label>
        <label>
          {t("initialBal")}
          <input
            inputMode="decimal"
            value={form.initial_bal}
            onChange={(e) => setForm({ ...form, initial_bal: e.target.value })}
          />
        </label>
        <label>
          {t("initialDate")}
          <input
            type="date"
            value={form.initial_date}
            onChange={(e) => setForm({ ...form, initial_date: e.target.value })}
          />
        </label>
        <label>
          {t("notes")}
          <textarea value={form.notes} onChange={(e) => setForm({ ...form, notes: e.target.value })} />
        </label>
        <label>
          {t("creditLimit")}
          <input
            inputMode="decimal"
            value={form.credit_limit}
            onChange={(e) => setForm({ ...form, credit_limit: e.target.value })}
          />
        </label>
        <label>
          {t("interestRate")}
          <input
            inputMode="decimal"
            value={form.interest_rate}
            onChange={(e) => setForm({ ...form, interest_rate: e.target.value })}
          />
        </label>
        <label>
          {t("minPayment")}
          <input
            inputMode="decimal"
            value={form.minimum_payment}
            onChange={(e) => setForm({ ...form, minimum_payment: e.target.value })}
          />
        </label>
        <label>
          {t("minimumBalance")}
          <input
            inputMode="decimal"
            value={form.minimum_balance}
            onChange={(e) => setForm({ ...form, minimum_balance: e.target.value })}
          />
        </label>
        <label>
          {t("statementDate")}
          <input
            type="date"
            value={form.statement_date}
            onChange={(e) => setForm({ ...form, statement_date: e.target.value })}
          />
        </label>
        <label className="check">
          <input
            type="checkbox"
            checked={Boolean(form.statement_locked)}
            onChange={(e) => setForm({ ...form, statement_locked: e.target.checked ? 1 : 0 })}
          />
          {t("statementLock")}
        </label>
      </div>
      <footer className="editor-actions">
        {!creating && (
          <button
            type="button"
            className="ghost danger"
            onClick={() => {
              if (!window.confirm(t("confirmDeleteAccount"))) return;
              void api
                .del(`/api/accounts/${accountId}`)
                .then(() => onSaved())
                .catch((err: Error) => setError(err.message));
            }}
          >
            {t("deleteAccount")}
          </button>
        )}
        <button type="submit" disabled={busy}>
          {t("save")}
        </button>
      </footer>
    </form>
  );
}
