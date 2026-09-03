import { FormEvent, useEffect, useState } from "react";
import { SortTh, sortBy, toggleSort, type SortState } from "./Sortable";
import { api } from "./api";
import type { MessageKey } from "./i18n";
import { writeTheme } from "./theme";

type Currency = {
  currency_id: number;
  name: string;
  symbol: string;
  rate: string;
  used_count: number;
  history_count: number;
  is_base: boolean;
};

type Hist = { hist_id: number; date: string; rate: string; upd_type: number };

type Settings = {
  username: string;
  date_format: string;
  delimiter: string;
  use_currency_history: boolean;
  financial_year_start_day: number;
  financial_year_start_month: number;
  stock_url: string;
  categ_delimiter: string;
  share_precision: number;
  base_currency_id: number;
  base_currency_name: string;
  base_currency_symbol: string;
  currencies: Currency[];
  meta: { date_formats: { id: string }[]; delimiters: string[] };
  theme: "system" | "light" | "dark";
  show_closed_accounts: boolean;
  default_account_id: number | null;
};

type Acct = { account_id: number; name: string; status: string; account_type: string };

type Props = {
  t: (key: MessageKey) => string;
  onChanged: () => void;
};

export function Settings({ t, onChanged }: Props) {
  const [data, setData] = useState<Settings | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [saved, setSaved] = useState(false);
  const [selected, setSelected] = useState<number | null>(null);
  const [history, setHistory] = useState<Hist[]>([]);
  const [rateForm, setRateForm] = useState({
    date: new Date().toISOString().slice(0, 10),
    rate: "",
  });
  const [rateSort, setRateSort] = useState<SortState>({ key: "symbol", dir: "asc" });
  const [histSort, setHistSort] = useState<SortState>({ key: "date", dir: "desc" });
  const [accounts, setAccounts] = useState<Acct[]>([]);

  async function load() {
    const [body, acc] = await Promise.all([
      api.get<Settings>("/api/settings"),
      api.get<{ accounts: Acct[] }>("/api/accounts"),
    ]);
    setData(body);
    setAccounts(acc.accounts);
    return body;
  }

  useEffect(() => {
    void load().catch((err: Error) => setError(err.message));
  }, []);

  async function onSave(event: FormEvent) {
    event.preventDefault();
    if (!data) return;
    setError(null);
    setSaved(false);
    try {
      const body = await api.put<Settings>("/api/settings", {
        username: data.username,
        date_format: data.date_format,
        delimiter: data.delimiter,
        use_currency_history: data.use_currency_history,
        financial_year_start_day: data.financial_year_start_day,
        financial_year_start_month: data.financial_year_start_month,
        stock_url: data.stock_url,
        categ_delimiter: data.categ_delimiter,
        share_precision: data.share_precision,
        theme: data.theme,
        show_closed_accounts: data.show_closed_accounts,
        default_account_id: data.default_account_id ?? 0,
      });
      setData(body);
      writeTheme(body.theme);
      setSaved(true);
      onChanged();
    } catch (err) {
      setError(err instanceof Error ? err.message : t("saveError"));
    }
  }

  async function onBase(currencyId: number) {
    setError(null);
    try {
      const body = await api.put<Settings>("/api/settings/base-currency", {
        currency_id: currencyId,
      });
      setData(body);
      onChanged();
    } catch (err) {
      setError(err instanceof Error ? err.message : t("saveError"));
    }
  }

  async function openHistory(id: number) {
    setSelected(id);
    const body = await api.get<{ history: Hist[]; rate: string }>(
      `/api/currencies/${id}/history`,
    );
    setHistory(body.history);
    setRateForm((f) => ({ ...f, rate: body.rate }));
  }

  async function saveRate(event: FormEvent) {
    event.preventDefault();
    if (selected == null) return;
    setError(null);
    try {
      const body = await api.post<{ history: Hist[]; rate: string }>(
        `/api/currencies/${selected}/history`,
        rateForm,
      );
      setHistory(body.history);
      setRateForm({ date: new Date().toISOString().slice(0, 10), rate: body.rate });
      await load();
      onChanged();
    } catch (err) {
      setError(err instanceof Error ? err.message : t("saveError"));
    }
  }

  async function removeRate(histId: number) {
    if (selected == null) return;
    setError(null);
    try {
      const body = await api.del<{ history: Hist[] }>(
        `/api/currencies/${selected}/history/${histId}`,
      );
      setHistory(body.history);
      await load();
    } catch (err) {
      setError(err instanceof Error ? err.message : t("saveError"));
    }
  }

  if (!data) return <p className="k">{t("loading")}</p>;

  const used = sortBy(
    data.currencies.filter((c) => c.used_count > 0 || c.is_base),
    rateSort,
    (c, k) => (k === "rate" ? c.rate : k === "used" ? c.used_count : k === "name" ? c.name : c.symbol),
  );
  const histShown = sortBy(history, histSort, (h, k) => (k === "rate" ? h.rate : h.date));

  return (
    <section className="panel">
      <h2>{t("settings")}</h2>
      {error && <p className="error-text">{error}</p>}
      <form className="mgr-form" onSubmit={onSave}>
        <label>
          {t("username")}
          <input
            value={data.username}
            onChange={(e) => setData({ ...data, username: e.target.value })}
          />
        </label>
        <label>
          {t("ioDateFormat")}
          <select
            value={data.date_format}
            onChange={(e) => setData({ ...data, date_format: e.target.value })}
          >
            {data.meta.date_formats.map((d) => (
              <option key={d.id} value={d.id}>
                {d.id}
              </option>
            ))}
          </select>
        </label>
        <label>
          {t("ioDelimiter")}
          <select
            value={data.delimiter === "\t" ? "\\t" : data.delimiter}
            onChange={(e) => setData({ ...data, delimiter: e.target.value })}
          >
            <option value=",">,</option>
            <option value=";">;</option>
            <option value={"\\t"}>TAB</option>
            <option value="|">|</option>
          </select>
        </label>
        <label>
          {t("categDelimiter")}
          <input
            value={data.categ_delimiter}
            onChange={(e) => setData({ ...data, categ_delimiter: e.target.value })}
          />
        </label>
        <label>
          {t("fyDay")}
          <input
            type="number"
            min={1}
            max={31}
            value={data.financial_year_start_day}
            onChange={(e) =>
              setData({ ...data, financial_year_start_day: Number(e.target.value) || 1 })
            }
          />
        </label>
        <label>
          {t("fyMonth")}
          <input
            type="number"
            min={1}
            max={12}
            value={data.financial_year_start_month}
            onChange={(e) =>
              setData({ ...data, financial_year_start_month: Number(e.target.value) || 1 })
            }
          />
        </label>
        <label>
          {t("sharePrecision")}
          <input
            type="number"
            min={0}
            max={10}
            value={data.share_precision}
            onChange={(e) =>
              setData({ ...data, share_precision: Number(e.target.value) || 0 })
            }
          />
        </label>
        <label>
          {t("stockUrl")}
          <input
            value={data.stock_url}
            onChange={(e) => setData({ ...data, stock_url: e.target.value })}
          />
        </label>
        <label className="chk">
          <input
            type="checkbox"
            checked={data.use_currency_history}
            onChange={(e) => setData({ ...data, use_currency_history: e.target.checked })}
          />
          {t("useCurrencyHistory")}
        </label>
        <label>
          {t("theme")}
          <select
            value={data.theme}
            onChange={(e) => {
              const theme = e.target.value as Settings["theme"];
              setData({ ...data, theme });
              writeTheme(theme);
            }}
          >
            <option value="system">{t("themeSystem")}</option>
            <option value="light">{t("themeLight")}</option>
            <option value="dark">{t("themeDark")}</option>
          </select>
        </label>
        <label className="chk">
          <input
            type="checkbox"
            checked={data.show_closed_accounts}
            onChange={(e) => setData({ ...data, show_closed_accounts: e.target.checked })}
          />
          {t("showClosed")}
        </label>
        <label>
          {t("defaultQuickAddAccount")}
          <select
            value={data.default_account_id ?? 0}
            onChange={(e) =>
              setData({ ...data, default_account_id: Number(e.target.value) || null })
            }
          >
            <option value={0}>{t("none")}</option>
            {accounts
              .filter((a) => a.account_type !== "Investment" && a.account_type !== "Shares")
              .map((a) => (
                <option key={a.account_id} value={a.account_id}>
                  {a.name}
                  {a.status === "Closed" ? ` (${t("closedBadge")})` : ""}
                </option>
              ))}
          </select>
        </label>
        <div className="mgr-actions">
          <button type="submit">{t("save")}</button>
          {saved && <span className="k">✓</span>}
        </div>
      </form>

      <h3>{t("baseCurrency")}</h3>
      <p className="k">
        {data.base_currency_name} ({data.base_currency_symbol})
      </p>
      <label>
        {t("setBaseCurrency")}
        <select
          value={data.base_currency_id}
          onChange={(e) => void onBase(Number(e.target.value))}
        >
          {data.currencies
            .filter((c) => c.used_count > 0 || c.is_base)
            .map((c) => (
              <option key={c.currency_id} value={c.currency_id}>
                {c.symbol} — {c.name}
              </option>
            ))}
        </select>
      </label>

      <h3>{t("rates")}</h3>
      <p className="k">{t("ratesHint")}</p>
      <table className="mgr-table">
        <thead>
          <tr>
            <SortTh label={t("symbol")} k="symbol" sort={rateSort} onSort={(k) => setRateSort((s) => toggleSort(s, k))} />
            <SortTh label={t("name")} k="name" sort={rateSort} onSort={(k) => setRateSort((s) => toggleSort(s, k))} />
            <SortTh label={t("rate")} k="rate" sort={rateSort} onSort={(k) => setRateSort((s) => toggleSort(s, k))} className="num" />
            <SortTh label={t("used")} k="used" sort={rateSort} onSort={(k) => setRateSort((s) => toggleSort(s, k))} />
            <th />
          </tr>
        </thead>
        <tbody>
          {used.map((row) => (
            <tr key={row.currency_id} className={selected === row.currency_id ? "selected" : undefined}>
              <td>
                {row.symbol}
                {row.is_base ? ` (${t("baseCurrencyFlag")})` : ""}
              </td>
              <td>{row.name}</td>
              <td className="num">{row.rate}</td>
              <td>{row.used_count}</td>
              <td>
                <button type="button" className="ghost" onClick={() => void openHistory(row.currency_id)}>
                  {t("priceHistory")}
                </button>
              </td>
            </tr>
          ))}
        </tbody>
      </table>

      {selected != null && (
        <>
          <h4>{t("priceHistory")}</h4>
          <form className="mgr-form" onSubmit={saveRate}>
            <label>
              {t("date")}
              <input
                type="date"
                value={rateForm.date}
                onChange={(e) => setRateForm({ ...rateForm, date: e.target.value })}
                required
              />
            </label>
            <label>
              {t("rate")}
              <input
                value={rateForm.rate}
                onChange={(e) => setRateForm({ ...rateForm, rate: e.target.value })}
                required
              />
            </label>
            <div className="mgr-actions">
              <button type="submit">{t("save")}</button>
            </div>
          </form>
          {history.length === 0 ? (
            <p className="k">{t("noData")}</p>
          ) : (
            <table className="mgr-table">
              <thead>
                <tr>
                  <SortTh label={t("date")} k="date" sort={histSort} onSort={(k) => setHistSort((s) => toggleSort(s, k))} />
                  <SortTh label={t("rate")} k="rate" sort={histSort} onSort={(k) => setHistSort((s) => toggleSort(s, k))} className="num" />
                  <th />
                </tr>
              </thead>
              <tbody>
                {histShown.map((row) => (
                  <tr key={row.hist_id}>
                    <td>{row.date}</td>
                    <td className="num">{row.rate}</td>
                    <td>
                      <button type="button" className="ghost" onClick={() => void removeRate(row.hist_id)}>
                        ×
                      </button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </>
      )}
    </section>
  );
}
