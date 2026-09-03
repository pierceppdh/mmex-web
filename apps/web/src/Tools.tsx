import { FormEvent, useEffect, useState } from "react";
import { api } from "./api";
import type { MessageKey } from "./i18n";
import type { Account } from "./types";

type Meta = {
  formats: string[];
  fields: string[];
  mmex_format: string[];
  date_formats: string[];
  delimiters: string[];
  amount_signs: string[];
};

type PreviewRow = {
  line: number;
  parsed: Record<string, string> | null;
  error: string | null;
};

type ImportResult = {
  format: string;
  dry_run: boolean;
  imported: number;
  errors: { line: number; error: string }[];
  created: { payees: number; categories: number; tags: number };
  preview: PreviewRow[];
};

type Props = {
  accounts: Account[];
  t: (key: MessageKey) => string;
  onChanged: () => void;
};

async function download(path: string, fallback: string) {
  const res = await fetch(path, { credentials: "include", headers: { Accept: "*/*" } });
  if (!res.ok) {
    let detail = `HTTP ${res.status}`;
    try {
      const body = (await res.json()) as { detail?: string };
      if (body.detail) detail = body.detail;
    } catch {
      /* ignore */
    }
    throw new Error(detail);
  }
  const blob = await res.blob();
  const disp = res.headers.get("Content-Disposition") || "";
  const match = /filename="([^"]+)"/.exec(disp);
  const name = match?.[1] || fallback;
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = name;
  a.click();
  URL.revokeObjectURL(url);
}

export function Tools({ accounts, t, onChanged }: Props) {
  const checking = accounts.filter(
    (a) => a.account_type !== "Investment" && a.account_type !== "Shares",
  );
  const [meta, setMeta] = useState<Meta | null>(null);
  const [accountId, setAccountId] = useState(checking[0]?.account_id || 0);
  const [fmt, setFmt] = useState("csv");
  const [dateFrom, setDateFrom] = useState("");
  const [dateTo, setDateTo] = useState("");
  const [delimiter, setDelimiter] = useState(",");
  const [dateFormat, setDateFormat] = useState("YYYY-MM-DD");
  const [amountSign, setAmountSign] = useState("deposit");
  const [skipFirst, setSkipFirst] = useState(1);
  const [fields, setFields] = useState("");
  const [file, setFile] = useState<File | null>(null);
  const [result, setResult] = useState<ImportResult | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [webapp, setWebapp] = useState<{
    exists: boolean;
    pending: number;
    path: string | null;
  } | null>(null);
  const [webappDelete, setWebappDelete] = useState(false);
  const [webappResult, setWebappResult] = useState<{
    imported: number;
    errors: { sidecar_id: number; error: string }[];
    dry_run: boolean;
    pending: number;
  } | null>(null);

  useEffect(() => {
    void api.get<Meta>("/api/io/meta").then((m) => {
      setMeta(m);
      setFields(m.mmex_format.join(","));
    });
    if (!accountId && checking[0]) setAccountId(checking[0].account_id);
    void api
      .get<{ exists: boolean; pending: number; path: string | null }>("/api/webapp")
      .then(setWebapp)
      .catch(() => undefined);
  }, []);

  function formData(dry: boolean) {
    const data = new FormData();
    if (!file) throw new Error("file");
    data.append("file", file);
    data.append("account_id", String(accountId));
    data.append("fmt", fmt);
    data.append("delimiter", delimiter);
    data.append("date_format", dateFormat);
    data.append("amount_sign", amountSign);
    data.append("skip_first", String(fmt === "qif" ? 0 : skipFirst));
    data.append("skip_last", "0");
    if (fmt !== "qif") data.append("fields", fields || (meta?.mmex_format.join(",") ?? ""));
    void dry;
    return data;
  }

  async function onExport(event: FormEvent) {
    event.preventDefault();
    setError(null);
    const qs = new URLSearchParams({
      account_id: String(accountId),
      fmt,
      delimiter,
      date_format: dateFormat,
      titles: "true",
    });
    if (dateFrom) qs.set("date_from", dateFrom);
    if (dateTo) qs.set("date_to", dateTo);
    if (fmt !== "qif") qs.set("fields", fields || (meta?.mmex_format.join(",") ?? ""));
    try {
      await download(`/api/io/export?${qs.toString()}`, `mmex.${fmt}`);
    } catch (err) {
      setError(err instanceof Error ? err.message : t("saveError"));
    }
  }

  async function onPreview(event: FormEvent) {
    event.preventDefault();
    setError(null);
    setResult(null);
    if (!file) {
      setError(t("ioNeedFile"));
      return;
    }
    try {
      const body = await api.upload<ImportResult>("/api/io/preview", formData(true));
      setResult(body);
    } catch (err) {
      setError(err instanceof Error ? err.message : t("saveError"));
    }
  }

  async function onImport() {
    setError(null);
    if (!file) {
      setError(t("ioNeedFile"));
      return;
    }
    try {
      const body = await api.upload<ImportResult>("/api/io/import", formData(false));
      setResult(body);
      onChanged();
    } catch (err) {
      setError(err instanceof Error ? err.message : t("saveError"));
    }
  }

  return (
    <section className="panel">
      <h2>{t("tools")}</h2>
      {error && <p className="error-text">{error}</p>}

      <h3>{t("ioExport")}</h3>
      <form className="mgr-form" onSubmit={onExport}>
        <label>
          {t("account")}
          <select value={accountId} onChange={(e) => setAccountId(Number(e.target.value))}>
            {checking.map((a) => (
              <option key={a.account_id} value={a.account_id}>
                {a.name}
              </option>
            ))}
          </select>
        </label>
        <label>
          {t("ioFormat")}
          <select value={fmt} onChange={(e) => setFmt(e.target.value)}>
            {(meta?.formats ?? ["csv", "qif", "xml"]).map((id) => (
              <option key={id} value={id}>
                {id.toUpperCase()}
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
        {fmt === "csv" && (
          <label>
            {t("ioDelimiter")}
            <select value={delimiter} onChange={(e) => setDelimiter(e.target.value)}>
              <option value=",">,</option>
              <option value=";">;</option>
              <option value={"\\t"}>TAB</option>
              <option value="|">|</option>
            </select>
          </label>
        )}
        <label>
          {t("ioDateFormat")}
          <select value={dateFormat} onChange={(e) => setDateFormat(e.target.value)}>
            {(meta?.date_formats ?? ["YYYY-MM-DD"]).map((id) => (
              <option key={id} value={id}>
                {id}
              </option>
            ))}
          </select>
        </label>
        {fmt !== "qif" && (
          <label>
            {t("ioFields")}
            <input value={fields} onChange={(e) => setFields(e.target.value)} />
          </label>
        )}
        <div className="mgr-actions">
          <button type="submit">{t("ioDownload")}</button>
        </div>
      </form>

      <h3>{t("ioImport")}</h3>
      <p className="k">{t("ioImportHint")}</p>
      <form className="mgr-form" onSubmit={onPreview}>
        <label>
          {t("ioFile")}
          <input
            type="file"
            accept=".csv,.qif,.xml,text/csv,application/xml,text/xml"
            onChange={(e) => setFile(e.target.files?.[0] ?? null)}
          />
        </label>
        <label>
          {t("account")}
          <select value={accountId} onChange={(e) => setAccountId(Number(e.target.value))}>
            {checking.map((a) => (
              <option key={a.account_id} value={a.account_id}>
                {a.name}
              </option>
            ))}
          </select>
        </label>
        <label>
          {t("ioFormat")}
          <select value={fmt} onChange={(e) => setFmt(e.target.value)}>
            {(meta?.formats ?? ["csv", "qif", "xml"]).map((id) => (
              <option key={id} value={id}>
                {id.toUpperCase()}
              </option>
            ))}
          </select>
        </label>
        {fmt !== "qif" && (
          <label>
            {t("ioSkipFirst")}
            <input
              type="number"
              min={0}
              value={skipFirst}
              onChange={(e) => setSkipFirst(Number(e.target.value) || 0)}
            />
          </label>
        )}
        <label>
          {t("ioAmountSign")}
          <select value={amountSign} onChange={(e) => setAmountSign(e.target.value)}>
            <option value="deposit">{t("ioPositiveDeposit")}</option>
            <option value="withdrawal">{t("ioPositiveWithdrawal")}</option>
          </select>
        </label>
        {fmt !== "qif" && (
          <label>
            {t("ioFields")}
            <input value={fields} onChange={(e) => setFields(e.target.value)} />
          </label>
        )}
        <div className="mgr-actions">
          <button type="submit">{t("ioPreview")}</button>
          <button type="button" className="ghost" onClick={() => void onImport()}>
            {t("ioRunImport")}
          </button>
        </div>
      </form>

      {result && (
        <div>
          <p>
            {t("ioImported")}: {result.imported} · {t("ioErrors")}: {result.errors.length}
            {result.dry_run ? ` · ${t("ioDryRun")}` : ""}
          </p>
          {result.preview.length > 0 && (
            <table className="mgr-table">
              <thead>
                <tr>
                  <th>#</th>
                  <th>{t("date")}</th>
                  <th>{t("payee")}</th>
                  <th>{t("type")}</th>
                  <th className="num">{t("amount")}</th>
                  <th>{t("status")}</th>
                </tr>
              </thead>
              <tbody>
                {result.preview.map((row) => (
                  <tr key={row.line} className={row.error ? "overdue" : undefined}>
                    <td>{row.line}</td>
                    <td>{row.parsed?.date ?? ""}</td>
                    <td>{row.parsed?.payee ?? ""}</td>
                    <td>{row.parsed?.type ?? ""}</td>
                    <td className="num">{row.parsed?.amount ?? ""}</td>
                    <td>{row.error || "OK"}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </div>
      )}

      <h3>{t("webappIngest")}</h3>
      <p className="k">{t("webappHint")}</p>
      {webapp && !webapp.exists && <p className="k">{t("webappMissing")}</p>}
      {webapp && webapp.exists && (
        <p className="k">
          {t("webappPending")}: {webapp.pending}
          {webapp.path ? ` · ${webapp.path}` : ""}
        </p>
      )}
      <div className="mgr-actions">
        <label className="chk">
          <input
            type="checkbox"
            checked={webappDelete}
            onChange={(e) => setWebappDelete(e.target.checked)}
          />
          {t("webappDeleteSidecar")}
        </label>
        <button
          type="button"
          className="ghost"
          onClick={() =>
            void api
              .post<{
                imported: number;
                errors: { sidecar_id: number; error: string }[];
                dry_run: boolean;
                pending: number;
              }>("/api/webapp/import", { dry_run: true, delete_imported: false })
              .then(setWebappResult)
              .catch((err: Error) => setError(err.message))
          }
        >
          {t("ioPreview")}
        </button>
        <button
          type="button"
          onClick={() =>
            void api
              .post<{
                imported: number;
                errors: { sidecar_id: number; error: string }[];
                dry_run: boolean;
                pending: number;
              }>("/api/webapp/import", { dry_run: false, delete_imported: webappDelete })
              .then((body) => {
                setWebappResult(body);
                onChanged();
                void api
                  .get<{ exists: boolean; pending: number; path: string | null }>("/api/webapp")
                  .then(setWebapp);
              })
              .catch((err: Error) => setError(err.message))
          }
        >
          {t("ioRunImport")}
        </button>
      </div>
      {webappResult && (
        <p>
          {t("ioImported")}: {webappResult.imported} · {t("ioErrors")}: {webappResult.errors.length}
          {webappResult.dry_run ? ` · ${t("ioDryRun")}` : ""}
        </p>
      )}
    </section>
  );
}
