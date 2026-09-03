import { FormEvent, useEffect, useMemo, useState } from "react";
import { CustomFields } from "./CustomFields";
import { SortTh, sortBy, toggleSort, type SortState } from "./Sortable";
import { api } from "./api";
import type { MessageKey } from "./i18n";
import type {
  CategoryAdmin,
  CurrencyAdmin,
  ManagerId,
  PayeeAdmin,
  TagAdmin,
} from "./types";

type Props = {
  id: ManagerId;
  t: (key: MessageKey) => string;
};

export function Managers({ id, t }: Props) {
  return (
    <section className="manager">
      <h2>{t(id === "payees" ? "payees" : id === "categories" ? "categories" : id === "tags" ? "tags" : "currencies")}</h2>
      {id === "payees" && <PayeeManager t={t} />}
      {id === "categories" && <CategoryManager t={t} />}
      {id === "tags" && <TagManager t={t} />}
      {id === "currencies" && <CurrencyManager t={t} />}
    </section>
  );
}

function PayeeManager({ t }: { t: (key: MessageKey) => string }) {
  const [rows, setRows] = useState<PayeeAdmin[]>([]);
  const [cats, setCats] = useState<CategoryAdmin[]>([]);
  const empty = {
    name: "",
    categ_id: 0,
    number: "",
    website: "",
    notes: "",
    pattern: "",
    active: 1,
  };
  const [form, setForm] = useState(empty);
  const [editId, setEditId] = useState<number | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [sort, setSort] = useState<SortState>({ key: "name", dir: "asc" });
  const [mergeFrom, setMergeFrom] = useState(0);
  const [mergeInto, setMergeInto] = useState(0);
  const [query, setQuery] = useState("");
  const shown = useMemo(() => {
    const needle = query.trim().toLowerCase();
    const filtered = needle
      ? rows.filter((row) =>
          [row.name, row.category_path ?? "", row.pattern, row.notes, row.website]
            .join(" ")
            .toLowerCase()
            .includes(needle),
        )
      : rows;
    return sortBy(
      filtered,
      sort,
      (row, k) =>
        k === "category" ? row.category_path ?? "" : k === "used" ? row.used_count : (row as never)[k],
    );
  }, [rows, sort, query]);

  async function load() {
    const [p, c] = await Promise.all([
      api.get<{ payees: PayeeAdmin[] }>("/api/payees/all"),
      api.get<{ categories: CategoryAdmin[] }>("/api/categories/all?include_inactive=false"),
    ]);
    setRows(p.payees);
    setCats(c.categories);
  }

  useEffect(() => {
    void load().catch((err: Error) => setError(err.message));
  }, []);

  async function onSubmit(event: FormEvent) {
    event.preventDefault();
    setError(null);
    const payload = {
      ...form,
      categ_id: form.categ_id || -1,
    };
    try {
      if (editId == null) await api.post("/api/payees", payload);
      else await api.put(`/api/payees/${editId}`, payload);
      setForm(empty);
      setEditId(null);
      await load();
    } catch (err) {
      setError(err instanceof Error ? err.message : t("saveError"));
    }
  }

  return (
    <>
      <form className="mgr-form mgr-form-create" onSubmit={onSubmit}>
        <label>
          {t("name")}
          <input
            value={form.name}
            onChange={(e) => setForm({ ...form, name: e.target.value })}
            required
          />
        </label>
        <label>
          {t("defaultCategory")}
          <select
            value={form.categ_id}
            onChange={(e) => setForm({ ...form, categ_id: Number(e.target.value) })}
          >
            <option value={0}>—</option>
            {cats.map((c) => (
              <option key={c.categ_id} value={c.categ_id}>
                {c.path}
              </option>
            ))}
          </select>
        </label>
        <label>
          {t("pattern")}
          <input
            value={form.pattern}
            onChange={(e) => setForm({ ...form, pattern: e.target.value })}
          />
        </label>
        <label>
          {t("website")}
          <input
            value={form.website}
            onChange={(e) => setForm({ ...form, website: e.target.value })}
          />
        </label>
        <label>
          {t("notes")}
          <input value={form.notes} onChange={(e) => setForm({ ...form, notes: e.target.value })} />
        </label>
        {error && <p className="error-text">{error}</p>}
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
      <form
        className="mgr-form mgr-form-merge"
        onSubmit={(e) => {
          e.preventDefault();
          if (!mergeFrom || !mergeInto) return;
          if (!window.confirm(t("confirmMerge"))) return;
          setError(null);
          void api
            .post(`/api/payees/${mergeFrom}/merge`, { into_id: mergeInto })
            .then(() => {
              setMergeFrom(0);
              setMergeInto(0);
              setEditId(null);
              setForm(empty);
              return load();
            })
            .catch((err: Error) => setError(err.message));
        }}
      >
        <label>
          {t("merge")}
          <select value={mergeFrom} onChange={(e) => setMergeFrom(Number(e.target.value))}>
            <option value={0}>—</option>
            {rows.map((r) => (
              <option key={r.payee_id} value={r.payee_id}>
                {r.name} ({r.used_count})
              </option>
            ))}
          </select>
        </label>
        <label>
          {t("mergeInto")}
          <select value={mergeInto} onChange={(e) => setMergeInto(Number(e.target.value))}>
            <option value={0}>—</option>
            {rows
              .filter((r) => r.payee_id !== mergeFrom)
              .map((r) => (
                <option key={r.payee_id} value={r.payee_id}>
                  {r.name}
                </option>
              ))}
          </select>
        </label>
        <div className="mgr-actions">
          <button type="submit" disabled={!mergeFrom || !mergeInto}>
            {t("merge")}
          </button>
        </div>
      </form>
      <CustomFields refType="Payee" refId={editId} t={t} />
      <label className="search-bar">
        <span className="k">{t("search")}</span>
        <input
          type="search"
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          placeholder={t("payees")}
        />
      </label>
      <table className="mgr-table">
        <thead>
          <tr>
            <SortTh label={t("name")} k="name" sort={sort} onSort={(k) => setSort((s) => toggleSort(s, k))} />
            <SortTh label={t("category")} k="category" sort={sort} onSort={(k) => setSort((s) => toggleSort(s, k))} />
            <SortTh label={t("pattern")} k="pattern" sort={sort} onSort={(k) => setSort((s) => toggleSort(s, k))} />
            <SortTh label={t("used")} k="used" sort={sort} onSort={(k) => setSort((s) => toggleSort(s, k))} />
            <th />
          </tr>
        </thead>
        <tbody>
          {shown.map((row) => (
            <tr key={row.payee_id} className={row.active ? "" : "inactive"}>
              <td>
                <button
                  type="button"
                  className="linkish"
                  onClick={() => {
                    setEditId(row.payee_id);
                    setForm({
                      name: row.name,
                      categ_id: row.categ_id && row.categ_id > 0 ? row.categ_id : 0,
                      number: row.number,
                      website: row.website,
                      notes: row.notes,
                      pattern: row.pattern,
                      active: row.active,
                    });
                  }}
                >
                  {row.name}
                </button>
              </td>
              <td>{row.category_path ?? ""}</td>
              <td>{row.pattern}</td>
              <td>{row.used_count}</td>
              <td>
                <RowActions
                  t={t}
                  active={row.active === 1}
                  used={row.used_count > 0}
                  onToggle={() =>
                    void api
                      .post(`/api/payees/${row.payee_id}/active`, { active: row.active !== 1 })
                      .then(load)
                  }
                  onDelete={() =>
                    void api
                      .del(`/api/payees/${row.payee_id}`)
                      .then(load)
                      .catch((err: Error) => setError(err.message))
                  }
                />
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </>
  );
}

function CategoryManager({ t }: { t: (key: MessageKey) => string }) {
  const [rows, setRows] = useState<CategoryAdmin[]>([]);
  const [form, setForm] = useState({ name: "", parent_id: 0, active: 1 });
  const [editId, setEditId] = useState<number | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [sort, setSort] = useState<SortState>({ key: "path", dir: "asc" });
  const [mergeFrom, setMergeFrom] = useState(0);
  const [mergeInto, setMergeInto] = useState(0);
  const [query, setQuery] = useState("");
  const shown = useMemo(() => {
    const needle = query.trim().toLowerCase();
    const filtered = needle
      ? rows.filter((row) =>
          `${row.path} ${row.name}`.toLowerCase().includes(needle),
        )
      : rows;
    return sortBy(filtered, sort, (row, k) => (k === "used" ? row.used_count : row.path));
  }, [rows, sort, query]);

  async function load() {
    const data = await api.get<{ categories: CategoryAdmin[] }>("/api/categories/all");
    setRows(data.categories);
  }

  useEffect(() => {
    void load().catch((err: Error) => setError(err.message));
  }, []);

  async function onSubmit(event: FormEvent) {
    event.preventDefault();
    setError(null);
    const payload = { name: form.name, parent_id: form.parent_id || -1, active: form.active };
    try {
      if (editId == null) await api.post("/api/categories", payload);
      else await api.put(`/api/categories/${editId}`, payload);
      setForm({ name: "", parent_id: 0, active: 1 });
      setEditId(null);
      await load();
    } catch (err) {
      setError(err instanceof Error ? err.message : t("saveError"));
    }
  }

  const parentOptions = rows.filter((c) => c.categ_id !== editId);

  return (
    <>
      <form className="mgr-form mgr-form-create" onSubmit={onSubmit}>
        <label>
          {t("name")}
          <input
            value={form.name}
            onChange={(e) => setForm({ ...form, name: e.target.value })}
            required
          />
        </label>
        <label>
          {t("parent")}
          <select
            value={form.parent_id}
            onChange={(e) => setForm({ ...form, parent_id: Number(e.target.value) })}
          >
            <option value={0}>—</option>
            {parentOptions.map((c) => (
              <option key={c.categ_id} value={c.categ_id}>
                {c.path}
              </option>
            ))}
          </select>
        </label>
        {error && <p className="error-text">{error}</p>}
        <div className="mgr-actions">
          <button type="submit">{editId == null ? t("newItem") : t("save")}</button>
          {editId != null && (
            <button
              type="button"
              className="ghost"
              onClick={() => {
                setEditId(null);
                setForm({ name: "", parent_id: 0, active: 1 });
              }}
            >
              {t("cancel")}
            </button>
          )}
        </div>
      </form>
      <form
        className="mgr-form mgr-form-merge"
        onSubmit={(e) => {
          e.preventDefault();
          if (!mergeFrom || !mergeInto) return;
          if (!window.confirm(t("confirmMerge"))) return;
          setError(null);
          void api
            .post(`/api/categories/${mergeFrom}/merge`, { into_id: mergeInto })
            .then(() => {
              setMergeFrom(0);
              setMergeInto(0);
              setEditId(null);
              setForm({ name: "", parent_id: 0, active: 1 });
              return load();
            })
            .catch((err: Error) => setError(err.message));
        }}
      >
        <label>
          {t("merge")}
          <select value={mergeFrom} onChange={(e) => setMergeFrom(Number(e.target.value))}>
            <option value={0}>—</option>
            {rows.map((r) => (
              <option key={r.categ_id} value={r.categ_id}>
                {r.path} ({r.used_count})
              </option>
            ))}
          </select>
        </label>
        <label>
          {t("mergeInto")}
          <select value={mergeInto} onChange={(e) => setMergeInto(Number(e.target.value))}>
            <option value={0}>—</option>
            {rows
              .filter((r) => r.categ_id !== mergeFrom)
              .map((r) => (
                <option key={r.categ_id} value={r.categ_id}>
                  {r.path}
                </option>
              ))}
          </select>
        </label>
        <div className="mgr-actions">
          <button type="submit" disabled={!mergeFrom || !mergeInto}>
            {t("merge")}
          </button>
        </div>
      </form>
      <label className="search-bar">
        <span className="k">{t("search")}</span>
        <input
          type="search"
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          placeholder={t("categories")}
        />
      </label>
      <table className="mgr-table">
        <thead>
          <tr>
            <SortTh label={t("category")} k="path" sort={sort} onSort={(k) => setSort((s) => toggleSort(s, k))} />
            <SortTh label={t("used")} k="used" sort={sort} onSort={(k) => setSort((s) => toggleSort(s, k))} />
            <th />
          </tr>
        </thead>
        <tbody>
          {shown.map((row) => (
            <tr key={row.categ_id} className={row.active ? "" : "inactive"}>
              <td>
                <button
                  type="button"
                  className="linkish"
                  onClick={() => {
                    setEditId(row.categ_id);
                    setForm({
                      name: row.name,
                      parent_id: row.parent_id && row.parent_id > 0 ? row.parent_id : 0,
                      active: row.active,
                    });
                  }}
                >
                  {row.path}
                </button>
              </td>
              <td>{row.used_count}</td>
              <td>
                <RowActions
                  t={t}
                  active={row.active === 1}
                  used={row.used_count > 0 || row.child_count > 0}
                  onToggle={() =>
                    void api
                      .post(`/api/categories/${row.categ_id}/active`, { active: row.active !== 1 })
                      .then(load)
                  }
                  onDelete={() =>
                    void api
                      .del(`/api/categories/${row.categ_id}`)
                      .then(load)
                      .catch((err: Error) => setError(err.message))
                  }
                />
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </>
  );
}

function TagManager({ t }: { t: (key: MessageKey) => string }) {
  const [rows, setRows] = useState<TagAdmin[]>([]);
  const [name, setName] = useState("");
  const [editId, setEditId] = useState<number | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [sort, setSort] = useState<SortState>({ key: "name", dir: "asc" });
  const shown = useMemo(
    () => sortBy(rows, sort, (row, k) => (k === "used" ? row.used_count : row.name)),
    [rows, sort],
  );

  async function load() {
    const data = await api.get<{ tags: TagAdmin[] }>("/api/tags/all");
    setRows(data.tags);
  }

  useEffect(() => {
    void load().catch((err: Error) => setError(err.message));
  }, []);

  async function onSubmit(event: FormEvent) {
    event.preventDefault();
    setError(null);
    try {
      if (editId == null) await api.post("/api/tags", { name, active: 1 });
      else await api.put(`/api/tags/${editId}`, { name, active: 1 });
      setName("");
      setEditId(null);
      await load();
    } catch (err) {
      setError(err instanceof Error ? err.message : t("saveError"));
    }
  }

  return (
    <>
      <form className="mgr-form" onSubmit={onSubmit}>
        <label>
          {t("name")}
          <input value={name} onChange={(e) => setName(e.target.value)} required />
        </label>
        {error && <p className="error-text">{error}</p>}
        <div className="mgr-actions">
          <button type="submit">{editId == null ? t("newItem") : t("save")}</button>
          {editId != null && (
            <button
              type="button"
              className="ghost"
              onClick={() => {
                setEditId(null);
                setName("");
              }}
            >
              {t("cancel")}
            </button>
          )}
        </div>
      </form>
      <table className="mgr-table">
        <thead>
          <tr>
            <SortTh label={t("name")} k="name" sort={sort} onSort={(k) => setSort((s) => toggleSort(s, k))} />
            <SortTh label={t("used")} k="used" sort={sort} onSort={(k) => setSort((s) => toggleSort(s, k))} />
            <th />
          </tr>
        </thead>
        <tbody>
          {shown.map((row) => (
            <tr key={row.tag_id} className={row.active ? "" : "inactive"}>
              <td>
                <button
                  type="button"
                  className="linkish"
                  onClick={() => {
                    setEditId(row.tag_id);
                    setName(row.name);
                  }}
                >
                  {row.name}
                </button>
              </td>
              <td>{row.used_count}</td>
              <td>
                <RowActions
                  t={t}
                  active={row.active === 1}
                  used={row.used_count > 0}
                  onToggle={() =>
                    void api
                      .post(`/api/tags/${row.tag_id}/active`, { active: row.active !== 1 })
                      .then(load)
                  }
                  onDelete={() =>
                    void api
                      .del(`/api/tags/${row.tag_id}`)
                      .then(load)
                      .catch((err: Error) => setError(err.message))
                  }
                />
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </>
  );
}

function CurrencyManager({ t }: { t: (key: MessageKey) => string }) {
  const empty = {
    name: "",
    symbol: "",
    pfx: "",
    sfx: "",
    decimal_point: ".",
    group_separator: " ",
    scale: 100,
    rate: "1",
    currency_type: "Fiat" as "Fiat" | "Crypto",
  };
  const [rows, setRows] = useState<CurrencyAdmin[]>([]);
  const [form, setForm] = useState(empty);
  const [editId, setEditId] = useState<number | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [sort, setSort] = useState<SortState>({ key: "symbol", dir: "asc" });
  const shown = useMemo(
    () =>
      sortBy(rows, sort, (row, k) =>
        k === "used" ? row.used_count : k === "rate" ? row.rate : k === "name" ? row.name : row.symbol,
      ),
    [rows, sort],
  );

  async function load() {
    const data = await api.get<{ currencies: CurrencyAdmin[] }>("/api/currencies/all");
    setRows(data.currencies);
  }

  useEffect(() => {
    void load().catch((err: Error) => setError(err.message));
  }, []);

  async function onSubmit(event: FormEvent) {
    event.preventDefault();
    setError(null);
    try {
      if (editId == null) await api.post("/api/currencies", form);
      else await api.put(`/api/currencies/${editId}`, form);
      setForm(empty);
      setEditId(null);
      await load();
    } catch (err) {
      setError(err instanceof Error ? err.message : t("saveError"));
    }
  }

  return (
    <>
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
          {t("symbol")}
          <input
            value={form.symbol}
            onChange={(e) => setForm({ ...form, symbol: e.target.value })}
            required
          />
        </label>
        <label>
          {t("prefix")}
          <input value={form.pfx} onChange={(e) => setForm({ ...form, pfx: e.target.value })} />
        </label>
        <label>
          {t("suffix")}
          <input value={form.sfx} onChange={(e) => setForm({ ...form, sfx: e.target.value })} />
        </label>
        <label>
          {t("rate")}
          <input
            inputMode="decimal"
            value={form.rate}
            onChange={(e) => setForm({ ...form, rate: e.target.value })}
            required
          />
        </label>
        <label>
          {t("scale")}
          <input
            inputMode="numeric"
            value={String(form.scale)}
            onChange={(e) => setForm({ ...form, scale: Number(e.target.value) || 1 })}
          />
        </label>
        <label>
          {t("currencyType")}
          <select
            value={form.currency_type}
            onChange={(e) =>
              setForm({ ...form, currency_type: e.target.value as "Fiat" | "Crypto" })
            }
          >
            <option value="Fiat">{t("fiat")}</option>
            <option value="Crypto">{t("crypto")}</option>
          </select>
        </label>
        {error && <p className="error-text">{error}</p>}
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
      <table className="mgr-table">
        <thead>
          <tr>
            <SortTh label={t("symbol")} k="symbol" sort={sort} onSort={(k) => setSort((s) => toggleSort(s, k))} />
            <SortTh label={t("name")} k="name" sort={sort} onSort={(k) => setSort((s) => toggleSort(s, k))} />
            <SortTh label={t("rate")} k="rate" sort={sort} onSort={(k) => setSort((s) => toggleSort(s, k))} />
            <SortTh label={t("used")} k="used" sort={sort} onSort={(k) => setSort((s) => toggleSort(s, k))} />
            <th />
          </tr>
        </thead>
        <tbody>
          {shown.map((row) => (
            <tr key={row.currency_id}>
              <td>
                <button
                  type="button"
                  className="linkish"
                  onClick={() => {
                    setEditId(row.currency_id);
                    setForm({
                      name: row.name,
                      symbol: row.symbol,
                      pfx: row.pfx,
                      sfx: row.sfx,
                      decimal_point: row.decimal_point,
                      group_separator: row.group_separator,
                      scale: row.scale,
                      rate: row.rate,
                      currency_type: row.currency_type,
                    });
                  }}
                >
                  {row.symbol}
                </button>
                {row.is_base ? ` (${t("baseCurrencyFlag")})` : ""}
              </td>
              <td>{row.name}</td>
              <td>{row.rate}</td>
              <td>{row.used_count}</td>
              <td>
                <button
                  type="button"
                  className="ghost danger"
                  disabled={row.is_base || row.used_count > 0}
                  onClick={() =>
                    void api
                      .del(`/api/currencies/${row.currency_id}`)
                      .then(load)
                      .catch((err: Error) => setError(err.message))
                  }
                >
                  ×
                </button>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </>
  );
}

function RowActions({
  t,
  active,
  used,
  onToggle,
  onDelete,
}: {
  t: (key: MessageKey) => string;
  active: boolean;
  used: boolean;
  onToggle: () => void;
  onDelete: () => void;
}) {
  return (
    <span className="row-actions">
      <button type="button" className="ghost" onClick={onToggle}>
        {active ? t("hide") : t("show")}
      </button>
      <button type="button" className="ghost danger" disabled={used} onClick={onDelete}>
        ×
      </button>
    </span>
  );
}
