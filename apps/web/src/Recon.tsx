import { useEffect, useMemo, useState } from "react";
import { api } from "./api";
import { PayeeField } from "./PayeeField";
import { SortTh, sortBy, toggleSort, type SortState } from "./Sortable";
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
  statement: {
    bank_name: string;
    parser_id: string;
    currency?: string;
    iban?: string | null;
    account_number?: string | null;
    period_start?: string | null;
    period_end?: string | null;
    opening_balance?: string | null;
    closing_balance?: string | null;
  };
  matches: MatchRow[];
  committed?: boolean;
};

type StatementPreview = {
  parser_id: string;
  bank_name: string;
  iban?: string | null;
  account_number?: string | null;
  currency?: string;
  card_last4?: string | null;
  period_start?: string | null;
  period_end?: string | null;
  opening_balance?: string | null;
  closing_balance?: string | null;
  suggested_account_id?: number | null;
  suggested_account_name?: string | null;
  transaction_count?: number;
};

type RowFilter = "all" | "todo" | "linked";

function rowKind(row: MatchRow, t: (key: MessageKey) => string) {
  if (row.selected_trans_id) return t("reconTypePoint");
  if (row.insert_as_transfer) return t("reconTransfer");
  if (row.status === "NO_MATCH" || row.status === "FUZZY_MATCHED" || row.status === "MANUAL") {
    return t("reconTypeTodo");
  }
  return t("reconTypeNew");
}

function statusClass(status: string) {
  const key = status.toLowerCase().replace(/_/g, "-");
  return `recon-chip recon-chip-${key}`;
}

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
  const [sort, setSort] = useState<SortState>({ key: "date", dir: "asc" });
  const [preview, setPreview] = useState<StatementPreview | null>(null);
  const [rowFilter, setRowFilter] = useState<RowFilter>("all");

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
    setPreview(null);
    void api
      .get<StatementPreview>(`/api/recon/documents/${docId}/preview`)
      .then((p) => {
        setPreview(p);
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
  const shownMatches = useMemo(() => {
    if (!session) return [];
    const filtered = session.matches
      .map((m, i) => ({ m, i }))
      .filter(({ m }) => {
        if (rowFilter === "todo") return !m.selected_trans_id && m.include;
        if (rowFilter === "linked") return Boolean(m.selected_trans_id);
        return true;
      });
    return sortBy(
      filtered,
      sort,
      ({ m }, key) => {
        if (key === "include") return m.include ? 1 : 0;
        if (key === "date") return m.bank_transaction.date;
        if (key === "desc") return m.bank_transaction.description;
        if (key === "amount") return m.bank_transaction.amount;
        if (key === "status") return m.status;
        if (key === "mmex") {
          const linked = linkedTxn(m);
          if (linked) return mmexLabel(linked, t);
          if (m.insert_as_transfer) return m.transfer_counterpart_account_name || "";
          return m.selected_payee_name || "";
        }
        if (key === "type") return rowKind(m, t);
        return "";
      },
    );
  }, [session, sort, t, rowFilter]);

  const statusCounts = useMemo(() => {
    const counts: Record<string, number> = {};
    for (const m of session?.matches ?? []) {
      counts[m.status] = (counts[m.status] ?? 0) + 1;
    }
    return counts;
  }, [session]);
  const includedCount = session?.matches.filter((m) => m.include).length ?? 0;
  const stmt = session?.statement;
  const previewCard = preview || stmt;

  if (docId != null) {
    return (
      <section className="panel recon-wizard recon-page">
        <button type="button" className="ghost" onClick={onBack}>
          ← {t("reconBack")}
        </button>
        <header className="review-header">
          <h2>{t("recon")}</h2>
          {selected && <h3>{docLabel(selected)}</h3>}
        </header>
        {error && <p className="error-text">{error}</p>}
        {result && <p className="recon-flash ok">{result}</p>}
        {!inbox && !error && <p className="k">{t("loading")}</p>}
        {inbox && !selected && <p className="error-text">{t("reconMissingDoc")}</p>}
        {selected && (
          <article className="recon-preview">
            <h3>{t("reconPreview")}</h3>
            {previewCard && (
              <div className="preview-grid">
                <div>
                  <div>
                    <strong>{t("reconParser")}:</strong> {previewCard.parser_id} —{" "}
                    {previewCard.transaction_count ?? session?.matches.length ?? "—"} {t("reconTxCount")}
                  </div>
                  <div>
                    <strong>{t("account")}:</strong> {session?.account_name || nameById[pickedAccount] || "—"}
                  </div>
                  <div>
                    <strong>{t("reconPeriod")}:</strong> {previewCard.period_start || "—"} →{" "}
                    {previewCard.period_end || "—"}
                  </div>
                  <div>
                    <strong>{t("baseCurrency")}:</strong> {previewCard.currency || "—"}
                  </div>
                  {previewCard.iban ? (
                    <div>
                      <strong>{t("reconIban")}:</strong> {previewCard.iban}
                    </div>
                  ) : null}
                  {previewCard.account_number ? (
                    <div>
                      <strong>N°</strong> {previewCard.account_number}
                    </div>
                  ) : null}
                  {"card_last4" in previewCard && previewCard.card_last4 ? (
                    <div>
                      <strong>{t("reconCard")}:</strong> ****{previewCard.card_last4}
                    </div>
                  ) : null}
                </div>
                <div>
                  <div>
                    <strong>{t("reconOpening")}:</strong> {previewCard.opening_balance ?? "—"}
                  </div>
                  <div>
                    <strong>{t("reconClosing")}:</strong> {previewCard.closing_balance ?? "—"}
                  </div>
                  {preview?.suggested_account_name ? (
                    <div className="k">
                      {t("reconSuggest")}: {preview.suggested_account_name}
                    </div>
                  ) : null}
                </div>
              </div>
            )}
            {selected.tags.length > 0 && (
              <div className="paperless-doc-tags">
                {selected.tags.map((tag) => (
                  <span className="recon-chip" key={tag}>
                    {tag}
                  </span>
                ))}
              </div>
            )}
            <div className="account-form">
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
              <div className="mgr-actions">
                <a
                  className="ghost recon-pdf"
                  href={`/api/recon/documents/${selected.id}/file`}
                  target="_blank"
                  rel="noreferrer"
                >
                  {t("reconPdf")}
                </a>
                <button type="button" className="recon-btn-primary" disabled={busy} onClick={() => void runMatch()}>
                  {busy ? t("reconBusy") : t("reconRun")}
                </button>
              </div>
            </div>
          </article>
        )}
        {session && (
          <>
            <p className="k">
              <strong>{session.statement.bank_name}</strong> — {session.account_name} · {session.matches.length}{" "}
              {t("matching")}
            </p>
            <ul className="status-counts">
              {Object.entries(statusCounts).map(([st, n]) => (
                <li key={st}>
                  <span className={statusClass(st)}>
                    {st} {n}
                  </span>
                </li>
              ))}
            </ul>
            <div className="review-filters" role="group">
              {(["all", "todo", "linked"] as const).map((f) => (
                <button
                  key={f}
                  type="button"
                  className={`ghost filter-btn${rowFilter === f ? " active" : ""}`}
                  onClick={() => setRowFilter(f)}
                >
                  {f === "all" ? t("reconFilterAll") : f === "todo" ? t("reconFilterTodo") : t("reconFilterLinked")}
                </button>
              ))}
            </div>
            <div className="recon-review">
              <div className="table-wrap recon-grid">
                <table className="register">
                  <thead>
                    <tr>
                      <SortTh
                        label={t("reconInclude")}
                        k="include"
                        sort={sort}
                        onSort={(k) => setSort((s) => toggleSort(s, k))}
                      />
                      <SortTh
                        label={t("date")}
                        k="date"
                        sort={sort}
                        onSort={(k) => setSort((s) => toggleSort(s, k))}
                      />
                      <SortTh
                        label={t("reconBankLine")}
                        k="desc"
                        sort={sort}
                        onSort={(k) => setSort((s) => toggleSort(s, k))}
                      />
                      <SortTh
                        label={t("amount")}
                        k="amount"
                        sort={sort}
                        onSort={(k) => setSort((s) => toggleSort(s, k))}
                        className="num"
                      />
                      <SortTh
                        label={t("reconMatch")}
                        k="status"
                        sort={sort}
                        onSort={(k) => setSort((s) => toggleSort(s, k))}
                      />
                      <SortTh
                        label={t("reconTypeCol")}
                        k="type"
                        sort={sort}
                        onSort={(k) => setSort((s) => toggleSort(s, k))}
                      />
                      <SortTh
                        label={t("reconMmex")}
                        k="mmex"
                        sort={sort}
                        onSort={(k) => setSort((s) => toggleSort(s, k))}
                      />
                    </tr>
                  </thead>
                  <tbody>
                    {shownMatches.map(({ m, i: idx }) => {
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
                          <td>
                            <span className={statusClass(m.status)}>{m.status}</span>
                          </td>
                          <td>{rowKind(m, t)}</td>
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
            <div className="review-footer">
              <div className="footer-balance">
                <span>
                  {includedCount} {t("reconIncluded")} / {session.matches.length}
                </span>
              </div>
              <div className="footer-actions">
                <button type="button" className="ghost" disabled={busy} onClick={() => void doCommit(true)}>
                  {t("reconDryRun")}
                </button>
                <button type="button" className="recon-btn-primary" disabled={busy} onClick={() => void doCommit(false)}>
                  {t("reconCommit")}
                </button>
              </div>
            </div>
          </>
        )}
      </section>
    );
  }

  return (
    <section className="panel recon-page">
      <h2>{t("recon")}</h2>
      <p className="k">{t("reconHint")}</p>
      {error && <p className="error-text">{error}</p>}
      {inbox && !inbox.configured && <p className="k">{t("reconNotConfigured")}</p>}
      {inbox && inbox.configured && inbox.documents.length === 0 && (
        <p className="k">{t("reconEmpty")}</p>
      )}
      {inbox && inbox.documents.length > 0 && (
        <div className="paperless-doc-list">
          {inbox.documents.map((doc) => (
            <article className="paperless-doc" key={doc.id}>
              <div className="paperless-doc-body">
                <span className="paperless-doc-title">{docLabel(doc)}</span>
                <span className="paperless-doc-meta">
                  {doc.created}
                  {doc.correspondent ? ` · ${doc.correspondent}` : ""}
                  {doc.account_id ? ` · ${nameById[doc.account_id] ?? ""}` : ` · ${t("reconUnmapped")}`}
                </span>
                <span className="paperless-doc-tags">
                  {doc.tags.map((tag) => (
                    <span className="recon-chip" key={tag}>
                      {tag}
                    </span>
                  ))}
                </span>
                {doc.original_file_name && doc.original_file_name !== doc.title ? (
                  <span className="k paperless-doc-file">{doc.original_file_name}</span>
                ) : null}
              </div>
              <button type="button" className="recon-btn-primary" onClick={() => onOpen(doc.id)}>
                {t("reconOpen")}
              </button>
            </article>
          ))}
        </div>
      )}
    </section>
  );
}
