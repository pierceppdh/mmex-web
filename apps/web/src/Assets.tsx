import { FormEvent, useEffect, useMemo, useState } from "react";
import { CustomFields } from "./CustomFields";
import { SortTh, sortBy, toggleSort, type SortState } from "./Sortable";
import { api } from "./api";
import type { MessageKey } from "./i18n";

type Asset = {
  asset_id: number;
  start_date: string;
  name: string;
  status: string;
  currency_id: number;
  value_change_mode: string;
  value: string;
  value_change: string;
  notes: string;
  value_change_rate: string;
  asset_type: string;
  current_value: string;
  link_count: number;
};

type LinkRow = {
  translink_id: number;
  trans_id: number;
  trans_date: string;
  trans_code: string;
  trans_amount: string;
  status: string;
  notes: string;
  account_name: string | null;
};

type Detail = Asset & { links: LinkRow[] };

type Meta = {
  asset_types: string[];
  asset_statuses: string[];
  value_changes: string[];
  value_modes: string[];
};

type Props = {
  t: (key: MessageKey) => string;
};

const empty = {
  name: "",
  start_date: new Date().toISOString().slice(0, 10),
  status: "Open",
  asset_type: "Other",
  value: "",
  value_change: "None",
  value_change_mode: "Percentage",
  value_change_rate: "0",
  notes: "",
};

export function Assets({ t }: Props) {
  const [rows, setRows] = useState<Asset[]>([]);
  const [totals, setTotals] = useState({ current: "0", open: "0" });
  const [meta, setMeta] = useState<Meta>({
    asset_types: [],
    asset_statuses: [],
    value_changes: [],
    value_modes: [],
  });
  const [form, setForm] = useState(empty);
  const [editId, setEditId] = useState<number | null>(null);
  const [selected, setSelected] = useState<Detail | null>(null);
  const [showClosed, setShowClosed] = useState(false);
  const [transId, setTransId] = useState("");
  const [error, setError] = useState<string | null>(null);

  async function load(selectId?: number) {
    const [list, m] = await Promise.all([
      api.get<{ assets: Asset[]; totals: { current: string; open: string } }>("/api/assets"),
      api.get<Meta>("/api/investments/meta"),
    ]);
    setRows(list.assets);
    setTotals(list.totals);
    setMeta(m);
    const pick = selectId ?? selected?.asset_id;
    if (pick && list.assets.some((a) => a.asset_id === pick)) {
      await openDetail(pick);
    } else {
      setSelected(null);
    }
  }

  async function openDetail(id: number) {
    const body = await api.get<Detail>(`/api/assets/${id}`);
    setSelected(body);
  }

  useEffect(() => {
    void load().catch((err: Error) => setError(err.message));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  async function onSubmit(event: FormEvent) {
    event.preventDefault();
    setError(null);
    try {
      const saved =
        editId == null
          ? await api.post<Detail>("/api/assets", form)
          : await api.put<Detail>(`/api/assets/${editId}`, form);
      setForm(empty);
      setEditId(null);
      await load(saved.asset_id);
    } catch (err) {
      setError(err instanceof Error ? err.message : t("saveError"));
    }
  }

  function edit(row: Asset) {
    setEditId(row.asset_id);
    setForm({
      name: row.name,
      start_date: row.start_date,
      status: row.status,
      asset_type: row.asset_type,
      value: row.value,
      value_change: row.value_change,
      value_change_mode: row.value_change_mode,
      value_change_rate: row.value_change_rate,
      notes: row.notes,
    });
  }

  async function remove(row: Asset) {
    if (!window.confirm(t("confirmDeleteAsset"))) return;
    setError(null);
    try {
      await api.del(`/api/assets/${row.asset_id}`);
      if (selected?.asset_id === row.asset_id) setSelected(null);
      await load();
    } catch (err) {
      setError(err instanceof Error ? err.message : t("saveError"));
    }
  }

  async function addLink(event: FormEvent) {
    event.preventDefault();
    if (!selected) return;
    setError(null);
    try {
      await api.post(`/api/assets/${selected.asset_id}/links`, {
        trans_id: Number(transId),
      });
      setTransId("");
      await load(selected.asset_id);
    } catch (err) {
      setError(err instanceof Error ? err.message : t("saveError"));
    }
  }

  async function unlink(translinkId: number) {
    if (!selected) return;
    setError(null);
    try {
      await api.del(`/api/assets/${selected.asset_id}/links/${translinkId}`);
      await load(selected.asset_id);
    } catch (err) {
      setError(err instanceof Error ? err.message : t("saveError"));
    }
  }

  const [sort, setSort] = useState<SortState>({ key: "name", dir: "asc" });
  const visible = useMemo(() => {
    const filtered = rows.filter((r) => showClosed || r.status !== "Closed");
    return sortBy(filtered, sort, (row, k) => {
      const map: Record<string, unknown> = {
        name: row.name,
        assetType: row.asset_type,
        startDate: row.start_date,
        initialValue: row.value,
        currentValue: row.current_value,
        valueChange: row.value_change,
      };
      return map[k] ?? "";
    });
  }, [rows, showClosed, sort]);

  return (
    <section className="panel">
      <h2>{t("assets")}</h2>
      {error && <p className="error-text">{error}</p>}
      <form className="mgr-form" onSubmit={onSubmit}>
        <label>
          {t("name")}
          <input
            value={form.name}
            onChange={(e) => setForm({ ...form, name: e.target.value })}
            required
          />
        </label>
        <label>
          {t("startDate")}
          <input
            type="date"
            value={form.start_date}
            onChange={(e) => setForm({ ...form, start_date: e.target.value })}
            required
          />
        </label>
        <label>
          {t("assetType")}
          <select
            value={form.asset_type}
            onChange={(e) => setForm({ ...form, asset_type: e.target.value })}
          >
            {meta.asset_types.map((id) => (
              <option key={id} value={id}>
                {id}
              </option>
            ))}
          </select>
        </label>
        <label>
          {t("assetStatus")}
          <select
            value={form.status}
            onChange={(e) => setForm({ ...form, status: e.target.value })}
          >
            {meta.asset_statuses.map((id) => (
              <option key={id} value={id}>
                {id}
              </option>
            ))}
          </select>
        </label>
        <label>
          {t("initialValue")}
          <input
            value={form.value}
            onChange={(e) => setForm({ ...form, value: e.target.value })}
            required
          />
        </label>
        <label>
          {t("valueChange")}
          <select
            value={form.value_change}
            onChange={(e) => setForm({ ...form, value_change: e.target.value })}
          >
            {meta.value_changes.map((id) => (
              <option key={id} value={id}>
                {id}
              </option>
            ))}
          </select>
        </label>
        <label>
          {t("valueChangeMode")}
          <select
            value={form.value_change_mode}
            onChange={(e) => setForm({ ...form, value_change_mode: e.target.value })}
          >
            {meta.value_modes.map((id) => (
              <option key={id} value={id}>
                {id}
              </option>
            ))}
          </select>
        </label>
        <label>
          {t("valueChangeRate")}
          <input
            value={form.value_change_rate}
            onChange={(e) => setForm({ ...form, value_change_rate: e.target.value })}
          />
        </label>
        <label>
          {t("notes")}
          <input
            value={form.notes}
            onChange={(e) => setForm({ ...form, notes: e.target.value })}
          />
        </label>
        <div className="mgr-actions">
          <button type="submit">{editId == null ? t("newItem") : t("save")}</button>
          {editId != null && (
            <button
              type="button"
              className="ghost"
              onClick={() => {
                setEditId(null);
                setForm(empty);
              }}
            >
              {t("cancel")}
            </button>
          )}
        </div>
      </form>

      <label className="k">
        <input
          type="checkbox"
          checked={showClosed}
          onChange={(e) => setShowClosed(e.target.checked)}
        />{" "}
        {t("showClosed")}
      </label>

      {visible.length === 0 ? (
        <p className="k">{t("noAssets")}</p>
      ) : (
        <table className="mgr-table">
          <thead>
            <tr>
              <SortTh label={t("name")} k="name" sort={sort} onSort={(k) => setSort((s) => toggleSort(s, k))} />
              <SortTh label={t("assetType")} k="assetType" sort={sort} onSort={(k) => setSort((s) => toggleSort(s, k))} />
              <SortTh label={t("startDate")} k="startDate" sort={sort} onSort={(k) => setSort((s) => toggleSort(s, k))} />
              <SortTh label={t("initialValue")} k="initialValue" sort={sort} onSort={(k) => setSort((s) => toggleSort(s, k))} className="num" />
              <SortTh label={t("currentValue")} k="currentValue" sort={sort} onSort={(k) => setSort((s) => toggleSort(s, k))} className="num" />
              <SortTh label={t("valueChange")} k="valueChange" sort={sort} onSort={(k) => setSort((s) => toggleSort(s, k))} />
              <th />
            </tr>
          </thead>
          <tbody>
            {visible.map((row) => (
              <tr key={row.asset_id} className={row.status === "Closed" ? "inactive" : undefined}>
                <td>
                  <button type="button" className="linkish" onClick={() => void openDetail(row.asset_id)}>
                    {row.name}
                  </button>
                </td>
                <td>{row.asset_type}</td>
                <td>{row.start_date}</td>
                <td className="num">{row.value}</td>
                <td className="num">{row.current_value}</td>
                <td>
                  {row.value_change}
                  {row.value_change !== "None" ? ` ${row.value_change_rate}%` : ""}
                </td>
                <td className="row-actions">
                  <button type="button" className="ghost" onClick={() => edit(row)}>
                    {t("edit")}
                  </button>
                  <button type="button" className="ghost" onClick={() => void remove(row)}>
                    ×
                  </button>
                </td>
              </tr>
            ))}
          </tbody>
          <tfoot>
            <tr>
              <td colSpan={4}>{t("currentValue")}</td>
              <td className="num">{showClosed ? totals.current : totals.open}</td>
              <td colSpan={2} />
            </tr>
          </tfoot>
        </table>
      )}

      {selected && (
        <>
          <h3>{selected.name}</h3>
          <p className="k">
            {t("currentValue")}: {selected.current_value} · {selected.link_count}{" "}
            {t("matching")}
          </p>
          <form className="mgr-form" onSubmit={addLink}>
            <label>
              {t("transId")}
              <input value={transId} onChange={(e) => setTransId(e.target.value)} required />
            </label>
            <div className="mgr-actions">
              <button type="submit">{t("linkTransaction")}</button>
            </div>
          </form>
          {selected.links.length === 0 ? (
            <p className="k">{t("noData")}</p>
          ) : (
            <table className="mgr-table">
              <thead>
                <tr>
                  <th>{t("date")}</th>
                  <th>{t("transId")}</th>
                  <th>{t("account")}</th>
                  <th>{t("type")}</th>
                  <th className="num">{t("amount")}</th>
                  <th />
                </tr>
              </thead>
              <tbody>
                {selected.links.map((row) => (
                  <tr key={row.translink_id}>
                    <td>{row.trans_date}</td>
                    <td>{row.trans_id}</td>
                    <td>{row.account_name}</td>
                    <td>{row.trans_code}</td>
                    <td className="num">{row.trans_amount}</td>
                    <td>
                      <button
                        type="button"
                        className="ghost"
                        onClick={() => void unlink(row.translink_id)}
                      >
                        {t("unlink")}
                      </button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
          <CustomFields refType="Asset" refId={selected.asset_id} t={t} />
        </>
      )}
    </section>
  );
}
