import { useEffect, useState } from "react";
import { api } from "./api";
import type { MessageKey } from "./i18n";

export type FieldValue = {
  field_id: number;
  name: string;
  type: string;
  properties: {
    tooltip: string;
    regex: string;
    autocomplete: boolean;
    default: string;
    choices: string[];
    digit_scale: number;
    udfc: string;
  };
  content: string | null;
  default: string;
};

type Props = {
  refType: string;
  refId: number | null;
  t: (key: MessageKey) => string;
};

function initialContent(row: FieldValue): string {
  if (row.content != null && row.content !== "") return row.content;
  return row.default || "";
}

export function CustomFields({ refType, refId, t }: Props) {
  const [rows, setRows] = useState<FieldValue[]>([]);
  const [draft, setDraft] = useState<Record<number, string>>({});
  const [error, setError] = useState<string | null>(null);
  const [saved, setSaved] = useState(false);

  async function load() {
    if (refId == null) {
      const body = await api.get<{ fields: FieldValue[] }>(
        `/api/custom-fields?ref_type=${encodeURIComponent(refType)}`,
      );
      const fields = body.fields as unknown as FieldValue[];
      setRows(
        fields.map((f) => ({
          ...f,
          content: null,
          default: f.properties?.default ?? "",
        })),
      );
      const next: Record<number, string> = {};
      for (const f of fields) next[f.field_id] = f.properties?.default ?? "";
      setDraft(next);
      return;
    }
    const body = await api.get<{ values: FieldValue[] }>(
      `/api/custom-fields/values?ref_type=${encodeURIComponent(refType)}&ref_id=${refId}`,
    );
    setRows(body.values);
    const next: Record<number, string> = {};
    for (const row of body.values) next[row.field_id] = initialContent(row);
    setDraft(next);
  }

  useEffect(() => {
    setError(null);
    setSaved(false);
    void load().catch((err: Error) => setError(err.message));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [refType, refId]);

  async function onSave() {
    if (refId == null) return;
    setError(null);
    setSaved(false);
    try {
      const body = await api.put<{ values: FieldValue[] }>("/api/custom-fields/values", {
        ref_type: refType,
        ref_id: refId,
        values: rows.map((row) => ({
          field_id: row.field_id,
          content: draft[row.field_id] ?? "",
        })),
      });
      setRows(body.values);
      const next: Record<number, string> = {};
      for (const row of body.values) next[row.field_id] = initialContent(row);
      setDraft(next);
      setSaved(true);
    } catch (err) {
      setError(err instanceof Error ? err.message : t("saveError"));
    }
  }

  if (rows.length === 0) return null;

  return (
    <fieldset className="cf-box">
      <legend>{t("customFields")}</legend>
      {refId == null ? (
        <p className="k">{t("saveToCustom")}</p>
      ) : (
        <div className="cf-form">
          {rows.map((row) => (
            <FieldInput
              key={row.field_id}
              row={row}
              value={draft[row.field_id] ?? ""}
              onChange={(v) => setDraft({ ...draft, [row.field_id]: v })}
              t={t}
            />
          ))}
          {error && <p className="error-text">{error}</p>}
          <div className="mgr-actions">
            <button type="button" onClick={() => void onSave()}>
              {t("save")}
            </button>
            {saved && <span className="k">✓</span>}
          </div>
        </div>
      )}
    </fieldset>
  );
}

function FieldInput({
  row,
  value,
  onChange,
  t,
}: {
  row: FieldValue;
  value: string;
  onChange: (v: string) => void;
  t: (key: MessageKey) => string;
}) {
  const tip = row.properties.tooltip;
  if (row.type === "Boolean") {
    return (
      <label title={tip}>
        {row.name}
        <select value={value} onChange={(e) => onChange(e.target.value)}>
          <option value="">—</option>
          <option value="FALSE">{t("cfFalse")}</option>
          <option value="TRUE">{t("cfTrue")}</option>
        </select>
      </label>
    );
  }
  if (row.type === "SingleChoice") {
    return (
      <label title={tip}>
        {row.name}
        <select value={value} onChange={(e) => onChange(e.target.value)}>
          <option value="">—</option>
          {row.properties.choices.map((c) => (
            <option key={c} value={c}>
              {c}
            </option>
          ))}
        </select>
      </label>
    );
  }
  if (row.type === "MultiChoice") {
    const selected = new Set(value ? value.split(";") : []);
    return (
      <div className="cf-multi" title={tip}>
        <span>{row.name}</span>
        <div>
          {row.properties.choices.map((c) => (
            <label key={c} className="chk">
              <input
                type="checkbox"
                checked={selected.has(c)}
                onChange={(e) => {
                  const next = new Set(selected);
                  if (e.target.checked) next.add(c);
                  else next.delete(c);
                  onChange(row.properties.choices.filter((x) => next.has(x)).join(";"));
                }}
              />
              {c}
            </label>
          ))}
        </div>
      </div>
    );
  }
  if (row.type === "Date") {
    return (
      <label title={tip}>
        {row.name}
        <input type="date" value={value.slice(0, 10)} onChange={(e) => onChange(e.target.value)} />
      </label>
    );
  }
  if (row.type === "Time") {
    return (
      <label title={tip}>
        {row.name}
        <input type="time" step={1} value={value.slice(0, 8)} onChange={(e) => onChange(e.target.value)} />
      </label>
    );
  }
  return (
    <label title={tip}>
      {row.name}
      <input
        value={value}
        onChange={(e) => onChange(e.target.value)}
        inputMode={row.type === "Integer" || row.type === "Decimal" ? "decimal" : undefined}
      />
    </label>
  );
}
