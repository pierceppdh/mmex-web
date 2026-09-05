import { useEffect, useState } from "react";
import { api } from "./api";
import { PayeeField } from "./PayeeField";
import type { MessageKey } from "./i18n";
import type { Account, Category, ReconDoc, ReconInbox } from "./types";

type MmexTxn = {
  trans_id: number;
  payee_name: string | null;
  amount: string;
  trans_date: string;
  trans_code: string;
  notes: string;
  is_inbound_transfer: boolean;
  counterpart_account_name: string | null;
  category_name: string | null;
};

type Candidate = {
  score: number;
  amount_match: boolean;
  date_delta_days: number;
  mmex_transaction: MmexTxn;
};

type MatchRow = {
  bank_transaction: { date: string; description: string; amount: string };
  status: string;
  include: boolean;
  selected_trans_id: number | null;
  selected_payee_name: string | null;
  force_new_insert: boolean;
  insert_as_transfer: boolean;
  transfer_counterpart_account_id: number | null;
  transfer_counterpart_account_name: string | null;
  transfer_counterpart_amount: string | null;
  force_trans_code: string | null;
  category_id: number | null;
  category_name: string | null;
  candidates: Candidate[];
};

type ReconSession = {
  id: string;
  account_id: number;
  account_name: string;
  suggested_account_id?: number | null;
  statement: { bank_name: string; parser_id: string; currency?: string };
  matches: MatchRow[];
  committed?: boolean;
};

type Props = {
  t: (key: MessageKey) => string;
  accounts: Account[];
  accountId?: number;
  docId?: number;
  onOpen: (docId: number) => void;
  onBack: () => void;
  onCommitted: () => void;
};

function docLabel(doc: ReconDoc): string {
  return doc.title || doc.original_file_name || `#${doc.id}`;
}

function mmexLabel(tx: MmexTxn, t: (key: MessageKey) => string): string {
  const date = tx.trans_date.slice(0, 10);
  const amt = tx.amount;
  if (tx.trans_code === "Transfer" || tx.is_inbound_transfer) {
    const other = tx.counterpart_account_name || tx.payee_name || "—";
    const arrow = tx.is_inbound_transfer ? t("reconInbound") : t("reconOutbound");
    return `${date} · ${arrow} ${other} · ${amt}`;
  }
  return `${date} · ${tx.payee_name || "—"} · ${amt}`;
}

function candidateLabel(c: Candidate, t: (key: MessageKey) => string): string {
  return `${mmexLabel(c.mmex_transaction, t)} · ${t("reconDelta")}${c.date_delta_days}`;
}

function linkedTxn(row: MatchRow): MmexTxn | null {
  if (!row.selected_trans_id) return null;
  return (
    row.candidates.find((c) => c.mmex_transaction.trans_id === row.selected_trans_id)
      ?.mmex_transaction ?? null
  );
}

export function Recon({ t, accounts, accountId, docId, onOpen, onBack, onCommitted }: Props) {
  const [inbox, setInbox] = useState<ReconInbox | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [pickedAccount, setPickedAccount] = useState(accountId ?? 0);
  const [session, setSession] = useState<ReconSession | null>(null);
  const [busy, setBusy] = useState(false);
  const [result, setResult] = useState<string | null>(null);
  const [selectedIdx, setSelectedIdx] = useState<number | null>(null);
  const [categories, setCategories] = useState<Category[]>([]);

  useEffect(() => {
    void api
      .get<ReconInbox>("/api/recon/inbox")
      .then(setInbox)
      .catch((err: Error) => setError(err.message));
    void api.get<{ categories: Category[] }>("/api/categories").then((r) => setCategories(r.categories));
  }, []);

  const nameById = Object.fromEntries(accounts.map((a) => [a.account_id, a.name]));
  const selected = docId != null ? inbox?.documents.find((d) => d.id === docId) : undefined;
  const openAccounts = accounts.filter((a) => a.status !== "Closed");

  useEffect(() => {
    if (selected?.account_id) setPickedAccount(selected.account_id);
    else if (accountId) setPickedAccount(accountId);
  }, [selected?.account_id, accountId]);

  useEffect(() => {
    if (docId == null) return;
    void api
      .get<{ suggested_account_id: number | null }>(`/api/recon/documents/${docId}/preview`)
      .then((p) => {
        if (p.suggested_account_id) setPickedAccount(p.suggested_account_id);
      })
      .catch(() => undefined);
  }, [docId]);

  async function runMatch() {
    if (!selected) return;
    if (!pickedAccount) {
      setError(t("reconNeedAccount"));
      return;
    }
    setBusy(true);
    setError(null);
    setResult(null);
    setSelectedIdx(null);
    try {
      const created = await api.post<ReconSession>("/api/recon/sessions", {
        paperless_id: selected.id,
        account_id: pickedAccount,
      });
      setSession(created);
      if (created.suggested_account_id) setPickedAccount(created.suggested_account_id);
      const firstTodo = created.matches.findIndex((m) => !m.selected_trans_id);
      setSelectedIdx(firstTodo >= 0 ? firstTodo : 0);
    } catch (err) {
      setError(err instanceof Error ? err.message : t("saveError"));
    } finally {
      setBusy(false);
    }
  }

  async function patchRow(index: number, body: Record<string, unknown>) {
    if (!session) return;
    try {
      const next = await api.patch<ReconSession>(
        `/api/recon/sessions/${session.id}/matches/${index}`,
        body,
      );
      setSession(next);
    } catch (err) {
      setError(err instanceof Error ? err.message : t("saveError"));
    }
  }

  async function doCommit(dryRun: boolean) {
    if (!session) return;
    setBusy(true);
    setError(null);
    try {
      const out = await api.post<{ success: boolean; message: string }>(
        `/api/recon/sessions/${session.id}/commit`,
        { dry_run: dryRun },
      );
      setResult(out.message);
      if (out.success && !dryRun) onCommitted();
    } catch (err) {
      setError(err instanceof Error ? err.message : t("saveError"));
    } finally {
      setBusy(false);
    }
  }

  const row = session && selectedIdx != null ? session.matches[selectedIdx] : undefined;

  if (docId != null) {
    return (
      <section className="panel recon-wizard">
        <button type="button" className="ghost" onClick={onBack}>
          ← {t("reconBack")}
        </button>
        <h2>{t("recon")}</h2>
        {error && <p className="error-text">{error}</p>}
        {result && <p>{result}</p>}
        {!inbox && !error && <p className="k">{t("loading")}</p>}
        {inbox && !selected && <p className="error-text">{t("reconMissingDoc")}</p>}
        {selected && (
          <>
            <h3>{docLabel(selected)}</h3>
            <p className="k">
              {selected.created}
              {selected.tags.length ? ` · ${selected.tags.join(", ")}` : ""}
            </p>
            <label>
              {t("reconChooseAccount")}
              <select
                value={pickedAccount || ""}
                onChange={(e) => setPickedAccount(Number(e.target.value))}
              >
                <option value="">{t("reconUnmapped")}</option>
                {openAccounts.map((a) => (
                  <option key={a.account_id} value={a.account_id}>
                    {a.name}
                  </option>
                ))}
              </select>
            </label>
            <p>
              <a
                className="ghost recon-pdf"
                href={`/api/recon/documents/${selected.id}/file`}
                target="_blank"
                rel="noreferrer"
              >
                {t("reconPdf")}
              </a>{" "}
              <button type="button" disabled={busy} onClick={() => void runMatch()}>
                {busy ? t("reconBusy") : t("reconRun")}
              </button>
            </p>
          </>
        )}
        {session && (
          <>
            <p className="k">
              {session.statement.bank_name} — {session.account_name} · {session.matches.length}{" "}
              {t("matching")}
            </p>
            <div className="recon-review">
              <div className="table-wrap recon-grid">
                <table className="register">
                  <thead>
                    <tr>
                      <th>{t("reconInclude")}</th>
                      <th>{t("date")}</th>
                      <th>{t("reconBankLine")}</th>
                      <th>{t("amount")}</th>
                      <th>{t("reconMatch")}</th>
                      <th>{t("reconMmex")}</th>
                    </tr>
                  </thead>
                  <tbody>
                    {session.matches.map((m, idx) => {
                      const linked = linkedTxn(m);
                      return (
                        <tr
                          key={idx}
                          className={idx === selectedIdx ? "active" : undefined}
                          onClick={() => setSelectedIdx(idx)}
                        >
                          <td onClick={(e) => e.stopPropagation()}>
                            <input
                              type="checkbox"
                              checked={m.include}
                              onChange={(e) => void patchRow(idx, { include: e.target.checked })}
                            />
                          </td>
                          <td>{m.bank_transaction.date}</td>
                          <td>{m.bank_transaction.description}</td>
                          <td className="num">{m.bank_transaction.amount}</td>
                          <td>{m.status}</td>
                          <td>
                            {linked
                              ? mmexLabel(linked, t)
                              : m.insert_as_transfer
                                ? `${t("reconOutbound")} ${m.transfer_counterpart_account_name || "—"}`
                                : m.selected_payee_name || t("reconNewInsert")}
                          </td>
                        </tr>
                      );
                    })}
                  </tbody>
                </table>
              </div>
              <aside className="recon-detail">
                {!row && <p className="k">{t("reconSelectRow")}</p>}
                {row && selectedIdx != null && (
                  <article>
                    <h3>
                      {t("reconEditLine")} {selectedIdx + 1}
                    </h3>
                    <p>
                      <strong>{row.bank_transaction.date}</strong> {row.bank_transaction.description}{" "}
                      <span className="num">({row.bank_transaction.amount})</span>
                    </p>
                    <p className="k">{row.status}</p>
                    {row.selected_trans_id && (
                      <p>
                        {t("reconLinked")}
                        {linkedTxn(row) ? ` — ${mmexLabel(linkedTxn(row)!, t)}` : ` #${row.selected_trans_id}`}
                        <button
                          type="button"
                          className="ghost"
                          onClick={() =>
                            void patchRow(selectedIdx, {
                              selected_trans_id: null,
                              force_new_insert: true,
                              status: "MANUAL",
                            })
                          }
                        >
                          {t("reconUnlink")}
                        </button>
                      </p>
                    )}
                    <label className="chk">
                      <input
                        type="checkbox"
                        checked={row.include}
                        onChange={(e) => void patchRow(selectedIdx, { include: e.target.checked })}
                      />
                      {t("reconInclude")}
                    </label>
                    {!row.selected_trans_id && row.status === "FUZZY_MATCHED" && (
                      <label className="chk">
                        <input
                          type="checkbox"
                          checked={row.force_new_insert}
                          onChange={(e) =>
                            void patchRow(selectedIdx, { force_new_insert: e.target.checked, status: "MANUAL" })
                          }
                        />
                        {t("reconForceNew")}
                      </label>
                    )}
                    <fieldset>
                      <legend>{t("reconInsertType")}</legend>
                      <label className="chk">
                        <input
                          type="radio"
                          name={`insert-${selectedIdx}`}
                          checked={!row.insert_as_transfer}
                          onChange={() =>
                            void patchRow(selectedIdx, {
                              insert_as_transfer: false,
                              selected_trans_id: null,
                              force_new_insert: true,
                              status: "MANUAL",
                            })
                          }
                        />
                        {t("reconTxn")}
                      </label>
                      <label className="chk">
                        <input
                          type="radio"
                          name={`insert-${selectedIdx}`}
                          checked={row.insert_as_transfer}
                          onChange={() =>
                            void patchRow(selectedIdx, {
                              insert_as_transfer: true,
                              selected_trans_id: null,
                              force_new_insert: true,
                              status: "MANUAL",
                            })
                          }
                        />
                        {t("reconTransfer")}
                      </label>
                    </fieldset>
                    {row.insert_as_transfer && !row.selected_trans_id && (
                      <>
                        <label>
                          {t("reconCounterpart")}
                          <select
                            value={row.transfer_counterpart_account_id ?? ""}
                            onChange={(e) => {
                              const id = Number(e.target.value) || null;
                              const acc = openAccounts.find((a) => a.account_id === id);
                              void patchRow(selectedIdx, {
                                transfer_counterpart_account_id: id,
                                transfer_counterpart_account_name: acc?.name ?? null,
                                insert_as_transfer: true,
                                status: "MANUAL",
                              });
                            }}
                          >
                            <option value="">—</option>
                            {openAccounts
                              .filter((a) => a.account_id !== session.account_id)
                              .map((a) => (
                                <option key={a.account_id} value={a.account_id}>
                                  {a.name}
                                </option>
                              ))}
                          </select>
                        </label>
                        <label>
                          {t("reconCounterpartAmount")}
                          <input
                            inputMode="decimal"
                            value={row.transfer_counterpart_amount ?? ""}
                            onChange={(e) =>
                              void patchRow(selectedIdx, {
                                transfer_counterpart_amount: e.target.value || null,
                              })
                            }
                          />
                        </label>
                      </>
                    )}
                    {!row.insert_as_transfer && !row.selected_trans_id && (
                      <>
                        <PayeeField
                          value={row.selected_payee_name ?? ""}
                          payeeId={0}
                          t={t}
                          onChange={(query) =>
                            void patchRow(selectedIdx, {
                              selected_payee_name: query,
                              force_new_insert: true,
                              status: "MANUAL",
                            })
                          }
                        />
                        <label>
                          {t("reconTransCode")}
                          <select
                            value={row.force_trans_code || ""}
                            onChange={(e) =>
                              void patchRow(selectedIdx, {
                                force_trans_code: e.target.value || null,
                                status: "MANUAL",
                              })
                            }
                          >
                            <option value="">{t("reconCodeAuto")}</option>
                            <option value="Withdrawal">{t("reconCodeWithdraw")}</option>
                            <option value="Deposit">{t("reconCodeDeposit")}</option>
                          </select>
                        </label>
                      </>
                    )}
                    {!row.selected_trans_id && (
                      <label>
                        {t("category")}
                        <select
                          value={row.category_id ?? ""}
                          onChange={(e) => {
                            const id = Number(e.target.value) || null;
                            const cat = categories.find((c) => c.categ_id === id);
                            void patchRow(selectedIdx, {
                              category_id: id,
                              category_name: cat?.path ?? null,
                              status: "MANUAL",
                            });
                          }}
                        >
                          <option value="">—</option>
                          {categories.map((c) => (
                            <option key={c.categ_id} value={c.categ_id}>
                              {c.path}
                            </option>
                          ))}
                        </select>
                      </label>
                    )}
                    {row.candidates.length > 0 && (
                      <div>
                        <h4>{t("reconCandidates")}</h4>
                        <ul className="recon-cands">
                          {row.candidates.map((c) => (
                            <li key={c.mmex_transaction.trans_id}>
                              <span>
                                {candidateLabel(c, t)}
                                {c.amount_match ? " · =" : ""}
                              </span>
                              <button
                                type="button"
                                className="ghost"
                                onClick={() =>
                                  void patchRow(selectedIdx, {
                                    selected_trans_id: c.mmex_transaction.trans_id,
                                    selected_payee_name: c.mmex_transaction.payee_name,
                                    force_new_insert: false,
                                    insert_as_transfer: false,
                                    status: "MANUAL",
                                  })
                                }
                              >
                                {t("reconLink")}
                              </button>
                            </li>
                          ))}
                        </ul>
                      </div>
                    )}
                  </article>
                )}
              </aside>
            </div>
            <p className="editor-actions">
              <button type="button" className="ghost" disabled={busy} onClick={() => void doCommit(true)}>
                {t("reconDryRun")}
              </button>
              <button type="button" disabled={busy} onClick={() => void doCommit(false)}>
                {t("reconCommit")}
              </button>
            </p>
          </>
        )}
      </section>
    );
  }

  return (
    <section className="panel">
      <h2>{t("recon")}</h2>
      <p className="k">{t("reconHint")}</p>
      {error && <p className="error-text">{error}</p>}
      {inbox && !inbox.configured && <p className="k">{t("reconNotConfigured")}</p>}
      {inbox && inbox.configured && inbox.documents.length === 0 && (
        <p className="k">{t("reconEmpty")}</p>
      )}
      {inbox && inbox.documents.length > 0 && (
        <table className="register">
          <thead>
            <tr>
              <th>{t("date")}</th>
              <th>{t("statement")}</th>
              <th>{t("account")}</th>
              <th />
            </tr>
          </thead>
          <tbody>
            {inbox.documents.map((doc) => (
              <tr key={doc.id}>
                <td>{doc.created}</td>
                <td>{docLabel(doc)}</td>
                <td>{doc.account_id ? nameById[doc.account_id] ?? "—" : t("reconUnmapped")}</td>
                <td>
                  <button type="button" onClick={() => onOpen(doc.id)}>
                    {t("reconOpen")}
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
