import { FormEvent, useEffect, useMemo, useState } from "react";
import { SortTh, sortBy, toggleSort, type SortState } from "./Sortable";
import { api } from "./api";
import type { MessageKey } from "./i18n";
import type { Category } from "./types";

type Period = { id: string; label_fr: string; label_en: string };

type Year = {
  year_id: number;
  name: string;
  is_monthly: boolean;
  entry_count: number;
};

type Line = {
  categ_id: number;
  path: string;
  kind: string;
  estimated: string;
  actual: string;
  difference: string;
  entry: { period: string; amount: string; notes: string; active: number } | null;
};

type Flow = {
  month: string;
  scheduled_in: string;
  scheduled_out: string;
  scheduled_net: string;
  budget_monthly: string;
  projected: string;
};

type Props = {
  locale: "fr" | "en";
  t: (key: MessageKey) => string;
};

export function Budgets({ locale, t }: Props) {
  const [years, setYears] = useState<Year[]>([]);
  const [periods, setPeriods] = useState<Period[]>([]);
  const [yearId, setYearId] = useState<number | "">("");
  const [lines, setLines] = useState<Line[]>([]);
  const [sort, setSort] = useState<SortState>({ key: "category", dir: "asc" });
  const shownLines = useMemo(
    () =>
      sortBy(lines, sort, (row, k) => {
        const map: Record<string, unknown> = {
          category: row.path,
          period: row.entry?.period ?? "",
          estimated: row.estimated,
          actual: row.actual,
          difference: row.difference,
        };
        return map[k] ?? "";
      }),
    [lines, sort],
  );
  const [totals, setTotals] = useState({ estimated: "0", actual: "0", difference: "0" });
  const [categories, setCategories] = useState<Category[]>([]);
  const [newName, setNewName] = useState("");
  const [copyFrom, setCopyFrom] = useState<number | "">("");
  const [form, setForm] = useState({ categ_id: 0, period: "Monthly", amount: "", notes: "" });
  const [flow, setFlow] = useState<{ opening: string; series: Flow[] } | null>(null);
  const [error, setError] = useState<string | null>(null);

  async function loadYears(selectId?: number) {
    const [list, cats, cf] = await Promise.all([
      api.get<{ years: Year[]; periods: Period[] }>("/api/budgets"),
      api.get<{ categories: Category[] }>("/api/categories"),
      api.get<{ opening: string; series: Flow[] }>("/api/budgets/cashflow?months=12"),
    ]);
    setYears(list.years);
    setPeriods(list.periods);
    setCategories(cats.categories);
    setFlow(cf);
    const ids = list.years.map((y) => y.year_id);
    const keep = typeof yearId === "number" && ids.includes(yearId) ? yearId : undefined;
    const pick = selectId ?? keep ?? list.years[0]?.year_id;
    if (pick) {
      setYearId(pick);
      await loadYear(pick);
    } else {
      setYearId("");
      setLines([]);
      setTotals({ estimated: "0", actual: "0", difference: "0" });
    }
  }

  async function loadYear(id: number) {
    const body = await api.get<{
      lines: Line[];
      totals: { estimated: string; actual: string; difference: string };
    }>(`/api/budgets/${id}`);
    setLines(body.lines);
    setTotals(body.totals);
  }

  useEffect(() => {
    void loadYears().catch((err: Error) => setError(err.message));
  }, []);

  async function onCreate(event: FormEvent) {
    event.preventDefault();
    setError(null);
    try {
      const created = await api.post<{ year_id: number }>("/api/budgets", {
        name: newName.trim(),
        copy_from_id: copyFrom || undefined,
      });
      setNewName("");
      setCopyFrom("");
      await loadYears(created.year_id);
    } catch (err) {
      setError(err instanceof Error ? err.message : t("saveError"));
    }
  }

  async function onSaveEntry(event: FormEvent) {
    event.preventDefault();
    if (yearId === "" || !form.categ_id) return;
    setError(null);
    try {
      await api.put(`/api/budgets/${yearId}/entries`, {
        categ_id: form.categ_id,
        period: form.period,
        amount: form.amount,
        notes: form.notes,
      });
      setForm({ categ_id: 0, period: "Monthly", amount: "", notes: "" });
      await loadYear(yearId);
      const cf = await api.get<{ opening: string; series: Flow[] }>("/api/budgets/cashflow?months=12");
      setFlow(cf);
    } catch (err) {
      setError(err instanceof Error ? err.message : t("saveError"));
    }
  }

  return (
    <section className="scheduled">
      <header className="register-head">
        <h2>{t("budgets")}</h2>
      </header>
      <form className="mgr-form" onSubmit={onCreate}>
        <label>
          {t("newYear")}
          <input value={newName} onChange={(e) => setNewName(e.target.value)} placeholder="2026" required />
        </label>
        <label>
          {t("copyFrom")}
          <select value={copyFrom} onChange={(e) => setCopyFrom(e.target.value ? Number(e.target.value) : "")}>
            <option value="">—</option>
            {years.map((y) => (
              <option key={y.year_id} value={y.year_id}>
                {y.name}
              </option>
            ))}
          </select>
        </label>
        <div className="mgr-actions">
          <button type="submit">{t("newItem")}</button>
        </div>
      </form>
      {years.length > 0 && (
        <div className="mgr-actions" style={{ marginBottom: "0.8rem" }}>
          <label>
            {t("budgets")}
            <select
              value={yearId}
              onChange={(e) => {
                const id = Number(e.target.value);
                setYearId(id);
                void loadYear(id).catch((err: Error) => setError(err.message));
              }}
            >
              {years.map((y) => (
                <option key={y.year_id} value={y.year_id}>
                  {y.name} ({y.entry_count})
                </option>
              ))}
            </select>
          </label>
          {yearId !== "" && (
            <button
              type="button"
              className="ghost danger"
              onClick={() =>
                void api
                  .del(`/api/budgets/${yearId}`)
                  .then(() => loadYears())
                  .catch((err: Error) => setError(err.message))
              }
            >
              ×
            </button>
          )}
        </div>
      )}
      {years.length > 0 && yearId !== "" && (
        <form className="mgr-form" onSubmit={onSaveEntry}>
          <label>
            {t("category")}
            <select
              value={form.categ_id}
              onChange={(e) => setForm({ ...form, categ_id: Number(e.target.value) })}
              required
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
            {t("period")}
            <select value={form.period} onChange={(e) => setForm({ ...form, period: e.target.value })}>
              {periods.map((p) => (
                <option key={p.id} value={p.id}>
                  {locale === "en" ? p.label_en : p.label_fr}
                </option>
              ))}
            </select>
          </label>
          <label>
            {t("amount")}
            <input
              inputMode="decimal"
              value={form.amount}
              onChange={(e) => setForm({ ...form, amount: e.target.value })}
              required
            />
          </label>
          <div className="mgr-actions">
            <button type="submit">{t("save")}</button>
          </div>
        </form>
      )}
      {error && <p className="error-text">{error}</p>}
      {years.length === 0 && <p className="k">{t("noBudgets")}</p>}
      {lines.length > 0 && (
        <table className="mgr-table">
          <thead>
            <tr>
              <SortTh label={t("category")} k="category" sort={sort} onSort={(k) => setSort((s) => toggleSort(s, k))} />
              <SortTh label={t("period")} k="period" sort={sort} onSort={(k) => setSort((s) => toggleSort(s, k))} />
              <SortTh label={t("estimated")} k="estimated" sort={sort} onSort={(k) => setSort((s) => toggleSort(s, k))} className="num" />
              <SortTh label={t("actual")} k="actual" sort={sort} onSort={(k) => setSort((s) => toggleSort(s, k))} className="num" />
              <SortTh label={t("difference")} k="difference" sort={sort} onSort={(k) => setSort((s) => toggleSort(s, k))} className="num" />
            </tr>
          </thead>
          <tbody>
            {shownLines.map((row) => (
              <tr
                key={row.categ_id}
                className={Number(row.difference) < 0 ? "overdue" : ""}
                onClick={() =>
                  setForm({
                    categ_id: row.categ_id,
                    period: row.entry?.period ?? "Monthly",
                    amount: row.entry?.amount ?? "",
                    notes: row.entry?.notes ?? "",
                  })
                }
              >
                <td>
                  <button type="button" className="linkish">
                    {row.path}
                  </button>
                  <div className="k">{row.kind === "income" ? t("income") : t("expense")}</div>
                </td>
                <td>{row.entry?.period ?? "—"}</td>
                <td className="num">{row.estimated}</td>
                <td className="num">{row.actual}</td>
                <td className="num">{row.difference}</td>
              </tr>
            ))}
            <tr>
              <td>{t("estimated")}</td>
              <td />
              <td className="num">{totals.estimated}</td>
              <td className="num">{totals.actual}</td>
              <td className="num">{totals.difference}</td>
            </tr>
          </tbody>
        </table>
      )}
      {flow && (
        <section className="panel" style={{ marginTop: "1.25rem" }}>
          <h2>{t("cashflow")}</h2>
          <p className="k">
            {t("opening")} : {flow.opening}
          </p>
          <table className="mgr-table">
            <thead>
              <tr>
                <th>{t("date")}</th>
                <th className="num">{t("scheduledIn")}</th>
                <th className="num">{t("scheduledOut")}</th>
                <th className="num">{t("budgetMonthly")}</th>
                <th className="num">{t("projected")}</th>
              </tr>
            </thead>
            <tbody>
              {flow.series.map((row) => (
                <tr key={row.month}>
                  <td>{row.month}</td>
                  <td className="num">{row.scheduled_in}</td>
                  <td className="num">{row.scheduled_out}</td>
                  <td className="num">{row.budget_monthly}</td>
                  <td className="num">{row.projected}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </section>
      )}
    </section>
  );
}
