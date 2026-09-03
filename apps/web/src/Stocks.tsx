import { FormEvent, useEffect, useMemo, useState } from "react";
import { CustomFields } from "./CustomFields";
import { SortTh, sortBy, toggleSort, type SortState } from "./Sortable";
import { api } from "./api";
import type { MessageKey } from "./i18n";

type Holding = { account_id: number; name: string; account_type: string };

type Stock = {
  stock_id: number;
  held_at: number;
  account_name: string | null;
  purchase_date: string;
  name: string;
  symbol: string;
  num_shares: string;
  purchase_price: string;
  notes: string;
  current_price: string;
  value: string;
  commission: string;
  market: string;
  gain: string;
  lot_count: number;
};

type Lot = {
  share_info_id: number;
  trans_id: number;
  share_number: string;
  share_price: string;
  share_commission: string;
  share_lot: string;
  trans_date: string;
  trans_code: string;
  trans_amount: string;
};

type Hist = { hist_id: number; date: string; price: string };

type Detail = Stock & { lots: Lot[]; history: Hist[] };

type Props = {
  t: (key: MessageKey) => string;
  onChanged?: () => void;
};

const empty = {
  name: "",
  symbol: "",
  held_at: 0,
  purchase_date: new Date().toISOString().slice(0, 10),
  num_shares: "",
  purchase_price: "",
  current_price: "",
  commission: "0",
  notes: "",
};

export function Stocks({ t, onChanged }: Props) {
  const [rows, setRows] = useState<Stock[]>([]);
  const [sort, setSort] = useState<SortState>({ key: "name", dir: "asc" });
  const shown = useMemo(
    () =>
      sortBy(rows, sort, (row, k) => {
        const map: Record<string, unknown> = {
          name: row.name,
          symbol: row.symbol,
          heldAt: row.account_name,
          shares: row.num_shares,
          currentPrice: row.current_price,
          marketValue: row.market,
          gain: row.gain,
        };
        return map[k] ?? "";
      }),
    [rows, sort],
  );
  const [totals, setTotals] = useState({ market: "0", gain: "0" });
  const [accounts, setAccounts] = useState<Holding[]>([]);
  const [form, setForm] = useState(empty);
  const [editId, setEditId] = useState<number | null>(null);
  const [selected, setSelected] = useState<Detail | null>(null);
  const [price, setPrice] = useState({ date: new Date().toISOString().slice(0, 10), price: "" });
  const [lot, setLot] = useState({
    trans_id: "",
    share_number: "",
    share_price: "",
    share_commission: "0",
    share_lot: "",
  });
  const [error, setError] = useState<string | null>(null);

  async function load(selectId?: number) {
    const body = await api.get<{
      stocks: Stock[];
      totals: { market: string; gain: string };
      accounts: Holding[];
    }>("/api/stocks");
    setRows(body.stocks);
    setTotals(body.totals);
    setAccounts(body.accounts);
    const pick = selectId ?? selected?.stock_id;
    if (pick && body.stocks.some((s) => s.stock_id === pick)) {
      await openDetail(pick);
    } else {
      setSelected(null);
    }
  }

  async function openDetail(id: number) {
    const body = await api.get<Detail>(`/api/stocks/${id}`);
    setSelected(body);
  }

  useEffect(() => {
    void load().catch((err: Error) => setError(err.message));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  async function onSubmit(event: FormEvent) {
    event.preventDefault();
    setError(null);
    const payload = {
      ...form,
      held_at: form.held_at || accounts[0]?.account_id,
      current_price: form.current_price || form.purchase_price,
    };
    try {
      const saved =
        editId == null
          ? await api.post<Detail>("/api/stocks", payload)
          : await api.put<Detail>(`/api/stocks/${editId}`, payload);
      setForm(empty);
      setEditId(null);
      await load(saved.stock_id);
      onChanged?.();
    } catch (err) {
      setError(err instanceof Error ? err.message : t("saveError"));
    }
  }

  function edit(row: Stock) {
    setEditId(row.stock_id);
    setForm({
      name: row.name,
      symbol: row.symbol,
      held_at: row.held_at,
      purchase_date: row.purchase_date,
      num_shares: row.num_shares,
      purchase_price: row.purchase_price,
      current_price: row.current_price,
      commission: row.commission,
      notes: row.notes,
    });
  }

  async function remove(row: Stock) {
    if (!window.confirm(t("confirmDeleteStock"))) return;
    setError(null);
    try {
      await api.del(`/api/stocks/${row.stock_id}`);
      if (selected?.stock_id === row.stock_id) setSelected(null);
      await load();
      onChanged?.();
    } catch (err) {
      setError(err instanceof Error ? err.message : t("saveError"));
    }
  }

  async function savePrice(event: FormEvent) {
    event.preventDefault();
    if (!selected) return;
    setError(null);
    try {
      await api.post(`/api/stocks/${selected.stock_id}/price`, price);
      setPrice({ ...price, price: "" });
      await load(selected.stock_id);
      onChanged?.();
    } catch (err) {
      setError(err instanceof Error ? err.message : t("saveError"));
    }
  }

  async function addLot(event: FormEvent) {
    event.preventDefault();
    if (!selected) return;
    setError(null);
    try {
      await api.post(`/api/stocks/${selected.stock_id}/lots`, {
        trans_id: Number(lot.trans_id),
        share_number: lot.share_number,
        share_price: lot.share_price,
        share_commission: lot.share_commission,
        share_lot: lot.share_lot,
      });
      setLot({
        trans_id: "",
        share_number: "",
        share_price: "",
        share_commission: "0",
        share_lot: "",
      });
      await load(selected.stock_id);
      onChanged?.();
    } catch (err) {
      setError(err instanceof Error ? err.message : t("saveError"));
    }
  }

  async function unlinkLot(shareInfoId: number) {
    if (!selected) return;
    setError(null);
    try {
      await api.del(`/api/stocks/${selected.stock_id}/lots/${shareInfoId}`);
      await load(selected.stock_id);
      onChanged?.();
    } catch (err) {
      setError(err instanceof Error ? err.message : t("saveError"));
    }
  }

  const lotsLocked = (selected?.lot_count ?? 0) > 0 && editId === selected?.stock_id;

  return (
    <section className="panel">
      <h2>{t("stocks")}</h2>
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
          {t("symbol")}
          <input
            value={form.symbol}
            onChange={(e) => setForm({ ...form, symbol: e.target.value })}
          />
        </label>
        <label>
          {t("heldAt")}
          <select
            value={form.held_at || accounts[0]?.account_id || 0}
            onChange={(e) => setForm({ ...form, held_at: Number(e.target.value) })}
          >
            {accounts.map((a) => (
              <option key={a.account_id} value={a.account_id}>
                {a.name}
              </option>
            ))}
          </select>
        </label>
        <label>
          {t("purchaseDate")}
          <input
            type="date"
            value={form.purchase_date}
            onChange={(e) => setForm({ ...form, purchase_date: e.target.value })}
            required
            disabled={lotsLocked}
          />
        </label>
        <label>
          {t("shares")}
          <input
            value={form.num_shares}
            onChange={(e) => setForm({ ...form, num_shares: e.target.value })}
            disabled={lotsLocked}
          />
        </label>
        <label>
          {t("purchasePrice")}
          <input
            value={form.purchase_price}
            onChange={(e) => setForm({ ...form, purchase_price: e.target.value })}
            disabled={lotsLocked}
          />
        </label>
        <label>
          {t("currentPrice")}
          <input
            value={form.current_price}
            onChange={(e) => setForm({ ...form, current_price: e.target.value })}
          />
        </label>
        <label>
          {t("commission")}
          <input
            value={form.commission}
            onChange={(e) => setForm({ ...form, commission: e.target.value })}
            disabled={lotsLocked}
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

      {rows.length === 0 ? (
        <p className="k">{t("noStocks")}</p>
      ) : (
        <table className="mgr-table">
          <thead>
            <tr>
              <SortTh label={t("name")} k="name" sort={sort} onSort={(k) => setSort((s) => toggleSort(s, k))} />
              <SortTh label={t("symbol")} k="symbol" sort={sort} onSort={(k) => setSort((s) => toggleSort(s, k))} />
              <SortTh label={t("heldAt")} k="heldAt" sort={sort} onSort={(k) => setSort((s) => toggleSort(s, k))} />
              <SortTh label={t("shares")} k="shares" sort={sort} onSort={(k) => setSort((s) => toggleSort(s, k))} className="num" />
              <SortTh label={t("currentPrice")} k="currentPrice" sort={sort} onSort={(k) => setSort((s) => toggleSort(s, k))} className="num" />
              <SortTh label={t("marketValue")} k="marketValue" sort={sort} onSort={(k) => setSort((s) => toggleSort(s, k))} className="num" />
              <SortTh label={t("gain")} k="gain" sort={sort} onSort={(k) => setSort((s) => toggleSort(s, k))} className="num" />
              <th />
            </tr>
          </thead>
          <tbody>
            {shown.map((row) => (
              <tr
                key={row.stock_id}
                className={selected?.stock_id === row.stock_id ? "selected" : undefined}
              >
                <td>
                  <button type="button" className="linkish" onClick={() => void openDetail(row.stock_id)}>
                    {row.name}
                  </button>
                </td>
                <td>{row.symbol}</td>
                <td>{row.account_name}</td>
                <td className="num">{row.num_shares}</td>
                <td className="num">{row.current_price}</td>
                <td className="num">{row.market}</td>
                <td className="num">{row.gain}</td>
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
              <td colSpan={5}>{t("marketValue")}</td>
              <td className="num">{totals.market}</td>
              <td className="num">{totals.gain}</td>
              <td />
            </tr>
          </tfoot>
        </table>
      )}

      {selected && (
        <>
          <h3>
            {selected.name} {selected.symbol && <span className="k">{selected.symbol}</span>}
          </h3>
          <form className="mgr-form" onSubmit={savePrice}>
            <label>
              {t("date")}
              <input
                type="date"
                value={price.date}
                onChange={(e) => setPrice({ ...price, date: e.target.value })}
                required
              />
            </label>
            <label>
              {t("currentPrice")}
              <input
                value={price.price}
                onChange={(e) => setPrice({ ...price, price: e.target.value })}
                required
              />
            </label>
            <div className="mgr-actions">
              <button type="submit">{t("updatePrice")}</button>
            </div>
          </form>

          <h4>{t("shareLots")}</h4>
          <form className="mgr-form" onSubmit={addLot}>
            <label>
              {t("transId")}
              <input
                value={lot.trans_id}
                onChange={(e) => setLot({ ...lot, trans_id: e.target.value })}
                required
              />
            </label>
            <label>
              {t("shareNumber")}
              <input
                value={lot.share_number}
                onChange={(e) => setLot({ ...lot, share_number: e.target.value })}
                required
              />
            </label>
            <label>
              {t("sharePrice")}
              <input
                value={lot.share_price}
                onChange={(e) => setLot({ ...lot, share_price: e.target.value })}
                required
              />
            </label>
            <label>
              {t("commission")}
              <input
                value={lot.share_commission}
                onChange={(e) => setLot({ ...lot, share_commission: e.target.value })}
              />
            </label>
            <label>
              {t("shareLot")}
              <input
                value={lot.share_lot}
                onChange={(e) => setLot({ ...lot, share_lot: e.target.value })}
              />
            </label>
            <div className="mgr-actions">
              <button type="submit">{t("linkTransaction")}</button>
            </div>
          </form>
          {selected.lots.length === 0 ? (
            <p className="k">{t("noData")}</p>
          ) : (
            <table className="mgr-table">
              <thead>
                <tr>
                  <th>{t("date")}</th>
                  <th>{t("transId")}</th>
                  <th className="num">{t("shareNumber")}</th>
                  <th className="num">{t("sharePrice")}</th>
                  <th className="num">{t("commission")}</th>
                  <th>{t("shareLot")}</th>
                  <th />
                </tr>
              </thead>
              <tbody>
                {selected.lots.map((row) => (
                  <tr key={row.share_info_id}>
                    <td>{row.trans_date}</td>
                    <td>{row.trans_id}</td>
                    <td className="num">{row.share_number}</td>
                    <td className="num">{row.share_price}</td>
                    <td className="num">{row.share_commission}</td>
                    <td>{row.share_lot}</td>
                    <td>
                      <button
                        type="button"
                        className="ghost"
                        onClick={() => void unlinkLot(row.share_info_id)}
                      >
                        {t("unlink")}
                      </button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}

          <h4>{t("priceHistory")}</h4>
          {selected.history.length === 0 ? (
            <p className="k">{t("noData")}</p>
          ) : (
            <table className="mgr-table">
              <thead>
                <tr>
                  <th>{t("date")}</th>
                  <th className="num">{t("currentPrice")}</th>
                </tr>
              </thead>
              <tbody>
                {selected.history.map((row) => (
                  <tr key={row.hist_id}>
                    <td>{row.date}</td>
                    <td className="num">{row.price}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
          <CustomFields refType="Stock" refId={selected.stock_id} t={t} />
        </>
      )}
    </section>
  );
}
