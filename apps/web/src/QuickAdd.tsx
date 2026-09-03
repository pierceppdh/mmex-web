import { FormEvent, useEffect, useState } from "react";
import { api } from "./api";
import { PayeeField } from "./PayeeField";
import type { MessageKey } from "./i18n";
import { checkingAccounts } from "./groups";
import type { Account, Category } from "./types";

type Props = {
  accounts: Account[];
  t: (key: MessageKey) => string;
  showClosed?: boolean;
  onChanged: () => void;
};

const LAST_KEY = "mmex-last-account";

function today() {
  return new Date().toISOString().slice(0, 10);
}

export function QuickAdd({ accounts, t, showClosed = false, onChanged }: Props) {
  const stored = Number(localStorage.getItem(LAST_KEY) || 0);
  const [accountId, setAccountId] = useState(stored);
  const checking = checkingAccounts(accounts, showClosed, accountId);
  const [code, setCode] = useState<"Withdrawal" | "Deposit" | "Transfer">("Withdrawal");
  const [amount, setAmount] = useState("");
  const [date, setDate] = useState(today);
  const [payeeQuery, setPayeeQuery] = useState("");
  const [payeeId, setPayeeId] = useState(0);
  const [categId, setCategId] = useState(0);
  const [toAccountId, setToAccountId] = useState(0);
  const [status, setStatus] = useState("");
  const [notes, setNotes] = useState("");
  const [categories, setCategories] = useState<Category[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [saved, setSaved] = useState(false);
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    void Promise.all([
      api.get<{ last_account_id: number | null; default_account_id: number | null }>(
        "/api/quickadd",
      ),
      api.get<{ categories: Category[] }>("/api/categories"),
    ]).then(([meta, cats]) => {
      setCategories(cats.categories);
      const preferred = meta.default_account_id || meta.last_account_id || stored;
      const pool = checkingAccounts(accounts, showClosed, preferred ?? 0);
      if (preferred && pool.some((a) => a.account_id === preferred)) setAccountId(preferred);
      else if (pool[0]) setAccountId(pool[0].account_id);
    });
  }, []);

  async function onSubmit(event: FormEvent) {
    event.preventDefault();
    setBusy(true);
    setError(null);
    setSaved(false);
    try {
      const body = await api.post<{ last_account_id: number }>("/api/quickadd", {
        account_id: accountId,
        trans_code: code,
        trans_amount: amount,
        trans_date: date,
        payee_id: code === "Transfer" ? undefined : payeeId || undefined,
        payee_name: code === "Transfer" ? "" : payeeQuery,
        categ_id: categId || undefined,
        to_account_id: code === "Transfer" ? toAccountId : undefined,
        status,
        notes,
      });
      localStorage.setItem(LAST_KEY, String(body.last_account_id));
      setAmount("");
      setPayeeQuery("");
      setPayeeId(0);
      setNotes("");
      setSaved(true);
      onChanged();
    } catch (err) {
      setError(err instanceof Error ? err.message : t("saveError"));
    } finally {
      setBusy(false);
    }
  }

  return (
    <section className="panel quickadd">
      <h2>{t("quickAdd")}</h2>
      {error && <p className="error-text">{error}</p>}
      {saved && <p className="ok-text">{t("quickAddSaved")}</p>}
      <form className="form-capture" onSubmit={onSubmit}>
        <label className="qa-amount">
          <span>{t("amount")}</span>
          <input
            inputMode="decimal"
            autoComplete="off"
            autoFocus
            value={amount}
            onChange={(e) => setAmount(e.target.value)}
            required
          />
        </label>
        {code !== "Transfer" && (
          <PayeeField
            value={payeeQuery}
            payeeId={payeeId}
            t={t}
            required
            listId="qa-payee"
            onChange={(name, id, match) => {
              setPayeeQuery(name);
              setPayeeId(id);
              if (match?.categ_id && !categId) setCategId(match.categ_id);
            }}
          />
        )}
        <label>
          <span>{t("category")}</span>
          <select value={categId} onChange={(e) => setCategId(Number(e.target.value))}>
            <option value={0}>—</option>
            {categories.map((c) => (
              <option key={c.categ_id} value={c.categ_id}>
                {c.path}
              </option>
            ))}
          </select>
        </label>
        <label>
          <span>{t("account")}</span>
          <select
            value={accountId}
            onChange={(e) => setAccountId(Number(e.target.value))}
            required
          >
            {checking.map((a) => (
              <option key={a.account_id} value={a.account_id}>
                {a.favorite ? "★ " : ""}
                {a.name}
              </option>
            ))}
          </select>
        </label>
        <div className="capture-type">
          <span>{t("type")}</span>
          <div className="type-options" role="radiogroup" aria-label={t("type")}>
            {(
              [
                ["Withdrawal", "typeWithdrawal"],
                ["Deposit", "typeDeposit"],
                ["Transfer", "typeTransfer"],
              ] as const
            ).map(([id, label]) => (
              <label key={id} className={code === id ? "on" : ""}>
                <input
                  type="radio"
                  name="qa-type"
                  checked={code === id}
                  onChange={() => setCode(id)}
                />
                {t(label)}
              </label>
            ))}
          </div>
        </div>
        {code === "Transfer" && (
          <label>
            <span>{t("transferTo")}</span>
            <select
              value={toAccountId}
              onChange={(e) => setToAccountId(Number(e.target.value))}
              required
            >
              <option value={0}>—</option>
              {checking
                .filter((a) => a.account_id !== accountId)
                .map((a) => (
                  <option key={a.account_id} value={a.account_id}>
                    {a.name}
                  </option>
                ))}
            </select>
          </label>
        )}
        <label>
          <span>{t("date")}</span>
          <input type="date" value={date} onChange={(e) => setDate(e.target.value)} required />
        </label>
        <details className="capture-more">
          <summary>{t("moreFields")}</summary>
          <label>
            <span>{t("status")}</span>
            <select value={status} onChange={(e) => setStatus(e.target.value)}>
              <option value="">{t("statusNone")}</option>
              <option value="R">{t("statusR")}</option>
              <option value="V">{t("statusV")}</option>
              <option value="F">{t("statusF")}</option>
              <option value="D">{t("statusD")}</option>
            </select>
          </label>
          <label>
            <span>{t("notes")}</span>
            <textarea value={notes} onChange={(e) => setNotes(e.target.value)} rows={2} />
          </label>
        </details>
        <button type="submit" className="qa-submit" disabled={busy}>
          {t("save")}
        </button>
      </form>
    </section>
  );
}
