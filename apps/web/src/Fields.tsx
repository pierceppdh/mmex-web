import { FormEvent, useEffect, useMemo, useState } from "react";
import { SortTh, sortBy, toggleSort, type SortState } from "./Sortable";
import { api } from "./api";
import type { MessageKey } from "./i18n";

type PropsIn = {
  tooltip: string;
  regex: string;
  autocomplete: boolean;
  default: string;
  choices: string[];
  digit_scale: number;
  udfc: string;
};

type Field = {
  field_id: number;
  ref_type: string;
  name: string;
  type: string;
  properties: PropsIn;
  used_count: number;
};

type Meta = { ref_types: string[]; field_types: string[]; udfc: string[] };

type Props = { t: (key: MessageKey) => string };

const empty = {
  name: "",
  ref_type: "Transaction",
  type: "String",
  tooltip: "",
  regex: "",
  autocomplete: false,
  default: "",
  choices: "",
  digit_scale: 0,
  udfc: "",
};

export function Fields({ t }: Props) {
  const [rows, setRows] = useState<Field[]>([]);
  const [sort, setSort] = useState<SortState>({ key: "name", dir: "asc" });
  const shown = useMemo(
    () =>
      sortBy(rows, sort, (row, k) =>
        k === "used"
          ? row.used_count
          : k === "cfRefType"
            ? row.ref_type
            : k === "cfFieldType"
              ? row.type
              : k === "cfUdfc"
                ? row.properties.udfc
                : row.name,
      ),
    [rows, sort],
  );
  const [meta, setMeta] = useState<Meta>({ ref_types: [], field_types: [], udfc: [] });
  const [form, setForm] = useState(empty);
  const [editId, setEditId] = useState<number | null>(null);
  const [error, setError] = useState<string | null>(null);

  async function load() {
    const body = await api.get<{ fields: Field[]; meta: Meta }>("/api/custom-fields");
    setRows(body.fields);
    setMeta(body.meta);
  }

  useEffect(() => {
    void load().catch((err: Error) => setError(err.message));
  }, []);

  function payload() {
    return {
      name: form.name,
      ref_type: form.ref_type,
      type: form.type,
      properties: {
        tooltip: form.tooltip,
        regex: form.regex,
        autocomplete: form.autocomplete,
        default: form.default,
        choices: form.choices
          .split(";")
          .map((c) => c.trim())
          .filter(Boolean),
        digit_scale: Number(form.digit_scale) || 0,
        udfc: form.udfc,
      },
    };
  }

  async function onSubmit(event: FormEvent) {
    event.preventDefault();
    setError(null);
    try {
      if (editId == null) await api.post("/api/custom-fields", payload());
      else await api.put(`/api/custom-fields/${editId}`, payload());
      setForm(empty);
      setEditId(null);
      await load();
    } catch (err) {
      setError(err instanceof Error ? err.message : t("saveError"));
    }
  }

  function edit(row: Field) {
    setEditId(row.field_id);
    setForm({
      name: row.name,
      ref_type: row.ref_type,
      type: row.type,
      tooltip: row.properties.tooltip,
      regex: row.properties.regex,
      autocomplete: row.properties.autocomplete,
      default: row.properties.default,
      choices: row.properties.choices.join(";"),
      digit_scale: row.properties.digit_scale,
      udfc: row.properties.udfc,
    });
  }

  async function remove(row: Field) {
    if (!window.confirm(t("confirmDeleteField"))) return;
    setError(null);
    try {
      await api.del(`/api/custom-fields/${row.field_id}`);
      if (editId === row.field_id) {
        setEditId(null);
        setForm(empty);
      }
      await load();
    } catch (err) {
      setError(err instanceof Error ? err.message : t("saveError"));
    }
  }

  const choiceType = form.type === "SingleChoice" || form.type === "MultiChoice";

  return (
    <section className="manager">
      <h2>{t("fields")}</h2>
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
          {t("cfRefType")}
          <select
            value={form.ref_type}
            onChange={(e) => setForm({ ...form, ref_type: e.target.value })}
          >
            {meta.ref_types.map((id) => (
              <option key={id} value={id}>
                {id}
              </option>
            ))}
          </select>
        </label>
        <label>
          {t("cfFieldType")}
          <select value={form.type} onChange={(e) => setForm({ ...form, type: e.target.value })}>
            {meta.field_types.map((id) => (
              <option key={id} value={id}>
                {id}
              </option>
            ))}
          </select>
        </label>
        <label>
          {t("cfTooltip")}
          <input
            value={form.tooltip}
            onChange={(e) => setForm({ ...form, tooltip: e.target.value })}
          />
        </label>
        <label>
          {t("cfRegex")}
          <input value={form.regex} onChange={(e) => setForm({ ...form, regex: e.target.value })} />
        </label>
        <label>
          {t("cfDefault")}
          <input
            value={form.default}
            onChange={(e) => setForm({ ...form, default: e.target.value })}
          />
        </label>
        <label>
          {t("cfChoices")}
          <input
            value={form.choices}
            onChange={(e) => setForm({ ...form, choices: e.target.value })}
            required={choiceType}
            placeholder="A;B;C"
          />
        </label>
        <label>
          {t("cfDigitScale")}
          <input
            type="number"
            min={0}
            max={20}
            value={form.digit_scale}
            onChange={(e) => setForm({ ...form, digit_scale: Number(e.target.value) })}
          />
        </label>
        <label>
          {t("cfUdfc")}
          <select value={form.udfc} onChange={(e) => setForm({ ...form, udfc: e.target.value })}>
            <option value="">—</option>
            {meta.udfc.map((id) => (
              <option key={id} value={id}>
                {id}
              </option>
            ))}
          </select>
        </label>
        <label className="chk">
          <input
            type="checkbox"
            checked={form.autocomplete}
            onChange={(e) => setForm({ ...form, autocomplete: e.target.checked })}
          />
          {t("cfAutocomplete")}
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
      {rows.length === 0 ? (
        <p className="k">{t("noFields")}</p>
      ) : (
        <table className="mgr-table">
          <thead>
            <tr>
              <SortTh label={t("name")} k="name" sort={sort} onSort={(k) => setSort((s) => toggleSort(s, k))} />
              <SortTh label={t("cfRefType")} k="cfRefType" sort={sort} onSort={(k) => setSort((s) => toggleSort(s, k))} />
              <SortTh label={t("cfFieldType")} k="cfFieldType" sort={sort} onSort={(k) => setSort((s) => toggleSort(s, k))} />
              <SortTh label={t("cfUdfc")} k="cfUdfc" sort={sort} onSort={(k) => setSort((s) => toggleSort(s, k))} />
              <SortTh label={t("used")} k="used" sort={sort} onSort={(k) => setSort((s) => toggleSort(s, k))} />
              <th />
            </tr>
          </thead>
          <tbody>
            {shown.map((row) => (
              <tr key={row.field_id}>
                <td>
                  <button type="button" className="linkish" onClick={() => edit(row)}>
                    {row.name}
                  </button>
                </td>
                <td>{row.ref_type}</td>
                <td>{row.type}</td>
                <td>{row.properties.udfc}</td>
                <td>{row.used_count}</td>
                <td>
                  <button type="button" className="ghost" onClick={() => void remove(row)}>
                    ×
                  </button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </section>
  );
}
