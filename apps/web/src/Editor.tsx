import { FormEvent, useEffect, useMemo, useState } from "react";
import { api } from "./api";
import { CustomFields } from "./CustomFields";
import { PayeeField, resolvePayeeId } from "./PayeeField";
import type { MessageKey } from "./i18n";
import type { Account, Attachment, Category, Tag, TxnDetail } from "./types";

type Props = {
  accountId: number;
  accounts: Account[];
  transId: number | null;
  t: (key: MessageKey) => string;
  pickAccount?: boolean;
  onClose: () => void;
  onSaved: () => void;
};

type Code = "Withdrawal" | "Deposit" | "Transfer";

const EMPTY: {
  trans_code: Code;
  trans_date: string;
  trans_amount: string;
  to_trans_amount: string;
  payee_id: number;
  payee_query: string;
  to_account_id: number;
  categ_id: number;
  status: string;
  transaction_number: string;
  notes: string;
  color: number;
  followup_id: number;
  tag_ids: number[];
  splits: { categ_id: number; amount: string; notes: string; tag_ids: number[] }[];
} = {
  trans_code: "Withdrawal",
  trans_date: new Date().toISOString().slice(0, 10),
  trans_amount: "",
  to_trans_amount: "",
  payee_id: 0,
  payee_query: "",
  to_account_id: 0,
  categ_id: 0,
  status: "",
  transaction_number: "",
  notes: "",
  color: -1,
  followup_id: -1,
  tag_ids: [] as number[],
  splits: [] as { categ_id: number; amount: string; notes: string; tag_ids: number[] }[],
};

export function Editor({ accountId, accounts, transId, t, pickAccount, onClose, onSaved }: Props) {
  const [aid, setAid] = useState(accountId);
  const [form, setForm] = useState(EMPTY);
  const [categories, setCategories] = useState<Category[]>([]);
  const [tags, setTags] = useState<Tag[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [deletedTime, setDeletedTime] = useState("");
  const [attachments, setAttachments] = useState<Attachment[]>([]);

  useEffect(() => {
    void Promise.all([
      api.get<{ categories: Category[] }>("/api/categories"),
      api.get<{ tags: Tag[] }>("/api/tags"),
    ]).then(([c, tg]) => {
      setCategories(c.categories);
      setTags(tg.tags);
    });
  }, []);

  useEffect(() => {
    setAid(accountId);
  }, [accountId]);

  useEffect(() => {
    if (transId == null) {
      setForm({ ...EMPTY, trans_date: new Date().toISOString().slice(0, 10) });
      setDeletedTime("");
      setAttachments([]);
      return;
    }
    void api.get<TxnDetail>(`/api/transactions/${transId}`).then((d) => {
      setDeletedTime(d.deleted_time || "");
      setAttachments(d.attachments ?? []);
      setAid(d.account_id);
      setForm({
        trans_code: d.trans_code,
        trans_date: d.trans_date.slice(0, 10),
        trans_amount: d.trans_amount,
        to_trans_amount: d.to_trans_amount,
        payee_id: d.payee_id > 0 ? d.payee_id : 0,
        payee_query: d.payee_name ?? "",
        to_account_id: d.to_account_id > 0 ? d.to_account_id : 0,
        categ_id: d.categ_id > 0 ? d.categ_id : 0,
        status: d.status,
        transaction_number: d.transaction_number,
        notes: d.notes,
        color: d.color,
        followup_id: d.followup_id,
        tag_ids: d.tags.map((x) => x.tag_id),
        splits: d.splits.map((s) => ({
          categ_id: s.categ_id,
          amount: s.amount,
          notes: s.notes,
          tag_ids: s.tags.map((x) => x.tag_id),
        })),
      });
    });
  }, [transId]);

  const splitTotal = useMemo(
    () => form.splits.reduce((s, row) => s + Number(row.amount || 0), 0),
    [form.splits],
  );

  async function onSubmit(event: FormEvent) {
    event.preventDefault();
    setBusy(true);
    setError(null);
    const resolvedPayee =
      form.trans_code === "Transfer"
        ? -1
        : await resolvePayeeId(form.payee_query, form.payee_id);
    const payload = {
      account_id: aid,
      trans_code: form.trans_code,
      trans_amount: form.trans_amount,
      trans_date: form.trans_date,
      payee_id: resolvedPayee,
      to_account_id: form.trans_code === "Transfer" ? form.to_account_id : undefined,
      to_trans_amount:
        form.trans_code === "Transfer" ? form.to_trans_amount || form.trans_amount : undefined,
      categ_id: form.splits.length ? -1 : form.categ_id || -1,
      status: form.status,
      transaction_number: form.transaction_number,
      notes: form.notes,
      color: form.color,
      followup_id: form.followup_id,
      tag_ids: form.tag_ids,
      splits: form.splits.map((s) => ({
        categ_id: s.categ_id,
        amount: s.amount,
        notes: s.notes,
        tag_ids: s.tag_ids,
      })),
    };
    try {
      if (transId == null) await api.post("/api/transactions", payload);
      else await api.put(`/api/transactions/${transId}`, payload);
      onSaved();
    } catch (err) {
      const msg = err instanceof Error ? err.message : t("saveError");
      setError(msg.toLowerCase().includes("locked") ? t("statementLocked") : msg);
    } finally {
      setBusy(false);
    }
  }

  async function onDelete() {
    if (transId == null) return;
    if (!window.confirm(t("confirmDelete"))) return;
    await api.post(`/api/transactions/${transId}/delete`);
    onSaved();
  }

  async function onRestore() {
    if (transId == null) return;
    await api.post(`/api/transactions/${transId}/restore`);
    onSaved();
  }

  return (
    <form className="editor" onSubmit={onSubmit}>
      <header>
        <h2>{transId == null ? t("newTransaction") : t("editTransaction")}</h2>
        <button type="button" className="ghost editor-cancel" onClick={onClose}>
          {t("cancel")}
        </button>
      </header>
      <div className="editor-body">
      {pickAccount && (
        <label>
          {t("account")}
          <select value={aid} onChange={(e) => setAid(Number(e.target.value))} required>
            {accounts.map((a) => (
              <option key={a.account_id} value={a.account_id}>
                {a.name}
              </option>
            ))}
          </select>
        </label>
      )}
      <label>
        {t("type")}
        <select
          value={form.trans_code}
          onChange={(e) =>
            setForm({ ...form, trans_code: e.target.value as Code })
          }
        >
          <option value="Withdrawal">{t("typeWithdrawal")}</option>
          <option value="Deposit">{t("typeDeposit")}</option>
          <option value="Transfer">{t("typeTransfer")}</option>
        </select>
      </label>
      <label>
        {t("date")}
        <input
          type="date"
          value={form.trans_date}
          onChange={(e) => setForm({ ...form, trans_date: e.target.value })}
          required
        />
      </label>
      <label>
        {t("amount")}
        <input
          inputMode="decimal"
          value={form.trans_amount}
          onChange={(e) => setForm({ ...form, trans_amount: e.target.value })}
          required
        />
      </label>
      {form.trans_code === "Transfer" ? (
        <>
          <label>
            {t("transferTo")}
            <select
              value={form.to_account_id}
              onChange={(e) => setForm({ ...form, to_account_id: Number(e.target.value) })}
              required
            >
              <option value={0}>—</option>
              {accounts
                .filter((a) => a.account_id !== aid)
                .map((a) => (
                  <option key={a.account_id} value={a.account_id}>
                    {a.name}
                  </option>
                ))}
            </select>
          </label>
          <label>
            {t("toAmount")}
            <input
              inputMode="decimal"
              value={form.to_trans_amount}
              onChange={(e) => setForm({ ...form, to_trans_amount: e.target.value })}
            />
          </label>
        </>
      ) : (
        <PayeeField
          value={form.payee_query}
          payeeId={form.payee_id}
          t={t}
          required
          listId="payee-list"
          onChange={(name, id, match) =>
            setForm({
              ...form,
              payee_query: name,
              payee_id: id,
              categ_id: match?.categ_id && form.categ_id === 0 ? match.categ_id : form.categ_id,
            })
          }
        />
      )}
      <label>
        {t("status")}
        <select value={form.status} onChange={(e) => setForm({ ...form, status: e.target.value })}>
          <option value="">{t("statusNone")}</option>
          <option value="R">{t("statusR")}</option>
          <option value="V">{t("statusV")}</option>
          <option value="F">{t("statusF")}</option>
          <option value="D">{t("statusD")}</option>
        </select>
      </label>
      <label>
        {t("number")}
        <input
          value={form.transaction_number}
          onChange={(e) => setForm({ ...form, transaction_number: e.target.value })}
        />
      </label>
      {form.splits.length === 0 && (
        <label>
          {t("category")}
          <select
            value={form.categ_id}
            onChange={(e) => setForm({ ...form, categ_id: Number(e.target.value) })}
          >
            <option value={0}>—</option>
            {categories.map((c) => (
              <option key={c.categ_id} value={c.categ_id}>
                {c.path}
              </option>
            ))}
          </select>
        </label>
      )}
      <label>
        {t("notes")}
        <textarea value={form.notes} onChange={(e) => setForm({ ...form, notes: e.target.value })} />
      </label>
      <fieldset>
        <legend>{t("color")}</legend>
        <div className="swatches">
          <button
            type="button"
            className={`swatch none${form.color <= 0 ? " on" : ""}`}
            onClick={() => setForm({ ...form, color: -1 })}
            title={t("colorNone")}
          />
          {[1, 2, 3, 4, 5, 6, 7].map((n) => (
            <button
              key={n}
              type="button"
              className={`swatch s-${n}${form.color === n ? " on" : ""}`}
              onClick={() => setForm({ ...form, color: n })}
            />
          ))}
        </div>
      </fieldset>
      <label className="check">
        <input
          type="checkbox"
          checked={form.followup_id > 0}
          onChange={(e) => setForm({ ...form, followup_id: e.target.checked ? 1 : -1 })}
        />
        {t("followUp")}
      </label>
      {tags.length > 0 && (
        <fieldset>
          <legend>{t("tags")}</legend>
          {tags.map((tag) => (
            <label key={tag.tag_id} className="check">
              <input
                type="checkbox"
                checked={form.tag_ids.includes(tag.tag_id)}
                onChange={() => {
                  const has = form.tag_ids.includes(tag.tag_id);
                  setForm({
                    ...form,
                    tag_ids: has
                      ? form.tag_ids.filter((id) => id !== tag.tag_id)
                      : [...form.tag_ids, tag.tag_id],
                  });
                }}
              />
              {tag.name}
            </label>
          ))}
        </fieldset>
      )}
      <fieldset>
        <legend>
          {t("splits")}{" "}
          {form.splits.length > 0 && (
            <span className="k">
              {t("splitSum")} {splitTotal}
            </span>
          )}
        </legend>
        {form.splits.map((row, i) => (
          <div className="split-row" key={i}>
            <select
              value={row.categ_id}
              onChange={(e) => {
                const next = [...form.splits];
                next[i] = { ...row, categ_id: Number(e.target.value) };
                setForm({ ...form, splits: next });
              }}
            >
              <option value={0}>—</option>
              {categories.map((c) => (
                <option key={c.categ_id} value={c.categ_id}>
                  {c.path}
                </option>
              ))}
            </select>
            <input
              inputMode="decimal"
              value={row.amount}
              onChange={(e) => {
                const next = [...form.splits];
                next[i] = { ...row, amount: e.target.value };
                setForm({ ...form, splits: next });
              }}
            />
            <input
              value={row.notes}
              placeholder={t("notes")}
              onChange={(e) => {
                const next = [...form.splits];
                next[i] = { ...row, notes: e.target.value };
                setForm({ ...form, splits: next });
              }}
            />
            <button
              type="button"
              className="ghost"
              onClick={() =>
                setForm({ ...form, splits: form.splits.filter((_, j) => j !== i) })
              }
            >
              ×
            </button>
          </div>
        ))}
        <button
          type="button"
          className="ghost"
          onClick={() =>
            setForm({
              ...form,
              splits: [...form.splits, { categ_id: 0, amount: "", notes: "", tag_ids: [] }],
            })
          }
        >
          {t("addSplit")}
        </button>
      </fieldset>
      <CustomFields refType="Transaction" refId={transId} t={t} />
      <fieldset>
        <legend>{t("attachments")}</legend>
        {transId == null ? (
          <p className="k">{t("saveToAttach")}</p>
        ) : (
          <>
            {attachments.length === 0 && <p className="k">{t("noAttachments")}</p>}
            <ul className="att-list">
              {attachments.map((a) => (
                <li key={a.attachment_id}>
                  <a href={`/api/attachments/${a.attachment_id}/file`}>{a.description || a.filename}</a>
                  <button
                    type="button"
                    className="ghost danger"
                    onClick={() =>
                      void api.del(`/api/attachments/${a.attachment_id}`).then(() =>
                        setAttachments((prev) => prev.filter((x) => x.attachment_id !== a.attachment_id)),
                      )
                    }
                  >
                    ×
                  </button>
                </li>
              ))}
            </ul>
            <label className="file-btn">
              {t("addAttachment")}
              <input
                type="file"
                onChange={(e) => {
                  const file = e.target.files?.[0];
                  e.target.value = "";
                  if (!file || transId == null) return;
                  const data = new FormData();
                  data.append("file", file);
                  data.append("description", file.name);
                  void api
                    .upload<Attachment>(`/api/transactions/${transId}/attachments`, data)
                    .then((att) => setAttachments((prev) => [...prev, att]))
                    .catch((err: Error) => setError(err.message));
                }}
              />
            </label>
          </>
        )}
      </fieldset>
      {error && <p className="error-text">{error}</p>}
      </div>
      <footer className="editor-actions">
        {transId != null && !deletedTime && (
          <button type="button" className="ghost danger" onClick={() => void onDelete()}>
            {t("deleted")}
          </button>
        )}
        {transId != null && deletedTime && (
          <button type="button" className="ghost" onClick={() => void onRestore()}>
            {t("restore")}
          </button>
        )}
        <button type="submit" disabled={busy}>
          {t("save")}
        </button>
      </footer>
    </form>
  );
}
