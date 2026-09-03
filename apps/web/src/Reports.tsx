import { FormEvent, useEffect, useMemo, useState } from "react";
import { Chart } from "./Chart";
import { SortTh, sortBy, toggleSort, type SortState } from "./Sortable";
import { api } from "./api";
import type { MessageKey } from "./i18n";

type Meta = { id: string; label_fr: string; label_en: string };

type Report = {
  id: string;
  date_from: string;
  date_to: string;
  totals?: { income?: string; expense?: string; net?: string };
  series?: Record<string, string | number>[];
  rows?: Record<string, string | number | null>[];
  net_worth_formatted?: string;
  year?: { lines?: { path: string; estimated: string; actual: string }[] } | null;
};

type GrmItem = {
  report_id: number;
  name: string;
  group_name: string;
  has_lua: boolean;
  has_sql: boolean;
};

type GrmRun = {
  html: string;
  name: string;
  lua_skipped: boolean;
  row_count: number;
};

type Props = {
  locale: "fr" | "en";
  t: (key: MessageKey) => string;
};

function yearStart() {
  return `${new Date().getFullYear()}-01-01`;
}

function today() {
  return new Date().toISOString().slice(0, 10);
}

export function Reports({ locale, t }: Props) {
  const [list, setList] = useState<Meta[]>([]);
  const [id, setId] = useState("income_expenses");
  const [dateFrom, setDateFrom] = useState(yearStart);
  const [dateTo, setDateTo] = useState(today);
  const [report, setReport] = useState<Report | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [grm, setGrm] = useState<GrmItem[]>([]);
  const [grmId, setGrmId] = useState<number | "">("");
  const [grmRun, setGrmRun] = useState<GrmRun | null>(null);

  async function load(reportId = id) {
    setError(null);
    const qs = new URLSearchParams({ date_from: dateFrom, date_to: dateTo });
    const body = await api.get<Report>(`/api/reports/${reportId}?${qs.toString()}`);
    setReport(body);
  }

  async function loadGrm() {
    const body = await api.get<{ reports: GrmItem[] }>("/api/grm");
    setGrm(body.reports);
  }

  useEffect(() => {
    void api
      .get<{ reports: Meta[] }>("/api/reports")
      .then((c) => {
        setList(c.reports);
        return load("income_expenses");
      })
      .then(() => loadGrm())
      .catch((err: Error) => setError(err.message));
  }, []);

  function onRun(event: FormEvent) {
    event.preventDefault();
    void load(id).catch((err: Error) => setError(err.message));
  }

  const chart = chartProps(id, report);

  return (
    <section className="scheduled">
      <header className="register-head">
        <h2>{t("reports")}</h2>
      </header>
      <form className="mgr-form" onSubmit={onRun}>
        <label>
          {t("reports")}
          <select
            value={id}
            onChange={(e) => {
              setId(e.target.value);
              void load(e.target.value).catch((err: Error) => setError(err.message));
            }}
          >
            {list.map((r) => (
              <option key={r.id} value={r.id}>
                {locale === "en" ? r.label_en : r.label_fr}
              </option>
            ))}
          </select>
        </label>
        <label>
          {t("dateFrom")}
          <input type="date" value={dateFrom} onChange={(e) => setDateFrom(e.target.value)} />
        </label>
        <label>
          {t("dateTo")}
          <input type="date" value={dateTo} onChange={(e) => setDateTo(e.target.value)} />
        </label>
        <div className="mgr-actions">
          <button type="submit">{t("runReport")}</button>
        </div>
      </form>
      {error && <p className="error-text">{error}</p>}
      {report?.totals && (
        <p className="k">
          {t("income")} {report.totals.income} · {t("expense")} {report.totals.expense} · {t("net")}{" "}
          {report.totals.net}
        </p>
      )}
      {report?.net_worth_formatted && (
        <p className="k">
          {t("netWorth")} : {report.net_worth_formatted}
        </p>
      )}
      {chart ? <Chart {...chart} /> : <p className="k">{t("noData")}</p>}
      {table(id, report)}

      <section className="panel" style={{ marginTop: "1.5rem" }}>
        <h2>{t("grm")}</h2>
        <div className="mgr-actions" style={{ marginBottom: "0.75rem" }}>
          <label className="ghost">
            {t("importGrm")}
            <input
              type="file"
              accept=".grm,.zip"
              style={{ display: "none" }}
              onChange={(e) => {
                const file = e.target.files?.[0];
                if (!file) return;
                const data = new FormData();
                data.append("file", file);
                void api
                  .upload<GrmItem>("/api/grm/import", data)
                  .then((item) => {
                    setGrmId(item.report_id);
                    return loadGrm();
                  })
                  .catch((err: Error) => setError(err.message));
                e.target.value = "";
              }}
            />
          </label>
        </div>
        {grm.length === 0 && <p className="k">{t("noGrm")}</p>}
        {grm.length > 0 && (
          <form
            className="mgr-form"
            onSubmit={(event) => {
              event.preventDefault();
              if (grmId === "") return;
              void api
                .post<GrmRun>(`/api/grm/${grmId}/run`, {
                  begin_date: dateFrom,
                  end_date: dateTo,
                  single_date: dateTo,
                  date_from: dateFrom,
                  date_to: dateTo,
                })
                .then(setGrmRun)
                .catch((err: Error) => setError(err.message));
            }}
          >
            <label>
              {t("grm")}
              <select value={grmId} onChange={(e) => setGrmId(e.target.value ? Number(e.target.value) : "")}>
                <option value="">—</option>
                {grm.map((r) => (
                  <option key={r.report_id} value={r.report_id}>
                    {r.group_name ? `${r.group_name} / ${r.name}` : r.name}
                  </option>
                ))}
              </select>
            </label>
            <div className="mgr-actions">
              <button type="submit">{t("runGrm")}</button>
            </div>
          </form>
        )}
        {grmRun?.lua_skipped && <p className="k">{t("luaSkipped")}</p>}
        {grmRun?.html && (
          <iframe
            className="grm-frame"
            title={grmRun.name}
            sandbox="allow-scripts"
            srcDoc={grmRun.html}
          />
        )}
      </section>
    </section>
  );
}

function chartProps(id: string, report: Report | null) {
  if (!report) return null;
  if (id === "income_expenses" && report.series?.length) {
    return {
      kind: "bar" as const,
      categories: report.series.map((s) => String(s.month)),
      series: [
        { name: "income", data: report.series.map((s) => Number(s.income)) },
        { name: "expense", data: report.series.map((s) => Number(s.expense)) },
      ],
    };
  }
  if ((id === "categories" || id === "payees") && report.series?.length) {
    const key = id === "payees" ? "name" : "path";
    return {
      kind: "donut" as const,
      labels: report.series.map((s) => String(s[key] ?? "")),
      values: report.series.map((s) => Number(s.expense) || Number(s.income) || 0),
    };
  }
  if (id === "cashflow" && report.series?.length) {
    return {
      kind: "line" as const,
      categories: report.series.map((s) => String(s.month)),
      series: [
        { name: "projected", data: report.series.map((s) => Number(s.projected)) },
        { name: "out", data: report.series.map((s) => Number(s.scheduled_out)) },
      ],
    };
  }
  if (id === "accounts" && report.series?.length) {
    return {
      kind: "bar" as const,
      categories: report.series.map((s) => String(s.name)).slice(0, 18),
      series: [
        {
          name: "value",
          data: report.series.slice(0, 18).map((s) => Number(s.value)),
        },
      ],
    };
  }
  if (id === "budget" && report.year?.lines?.length) {
    const lines = report.year.lines.filter((l) => Number(l.estimated) || Number(l.actual)).slice(0, 16);
    return {
      kind: "bar" as const,
      categories: lines.map((l) => l.path),
      series: [
        { name: "estimated", data: lines.map((l) => Number(l.estimated)) },
        { name: "actual", data: lines.map((l) => Number(l.actual)) },
      ],
    };
  }
  if (id === "stocks" && report.rows?.length) {
    return {
      kind: "bar" as const,
      categories: report.rows.map((r) => String(r.symbol || r.name)),
      series: [{ name: "market", data: report.rows.map((r) => Number(r.market_base ?? r.market)) }],
    };
  }
  if (id === "usage" && report.series?.length) {
    return {
      kind: "bar" as const,
      categories: report.series.map((s) => String(s.month)),
      series: [{ name: "count", data: report.series.map((s) => Number(s.count)) }],
    };
  }
  return null;
}

function table(_id: string, report: Report | null) {
  if (!report) return null;
  const rows = (report.rows ?? report.series ?? report.year?.lines) as
    | Record<string, string | number | null>[]
    | undefined;
  if (!rows?.length) return null;
  return <ReportTable rows={rows} />;
}

function ReportTable({ rows }: { rows: Record<string, string | number | null>[] }) {
  const keys = Object.keys(rows[0]).filter((k) => k !== "categ_id" && k !== "stock_id" && k !== "payee_id");
  const [sort, setSort] = useState<SortState>({ key: keys[0] ?? "name", dir: "asc" });
  const shown = useMemo(
    () => sortBy(rows, sort, (row, k) => row[k]),
    [rows, sort],
  );
  return (
    <div className="table-scroll">
    <table className="mgr-table">
      <thead>
        <tr>
          {keys.map((k) => (
            <SortTh
              key={k}
              label={k}
              k={k}
              sort={sort}
              onSort={(col) => setSort((s) => toggleSort(s, col))}
              className={k === "name" || k === "path" || k === "month" ? "" : "num"}
            />
          ))}
        </tr>
      </thead>
      <tbody>
        {shown.slice(0, 40).map((row, i) => (
          <tr key={i}>
            {keys.map((k) => (
              <td key={k} className={k === "name" || k === "path" || k === "month" ? "" : "num"}>
                {String(row[k] ?? "")}
              </td>
            ))}
          </tr>
        ))}
      </tbody>
    </table>
    </div>
  );
}
