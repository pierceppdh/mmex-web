import { useEffect, useState } from "react";
import { api } from "./api";
import type { MessageKey } from "./i18n";
import type { Account, ReconDoc, ReconInbox } from "./types";

type MatchRow = {
  bank_transaction: { date: string; description: string; amount: string };
  status: string;
  include: boolean;
  selected_trans_id: number | null;
  selected_payee_name: string | null;
  candidates: {
    score: number;
    amount_match: boolean;
    mmex_transaction: {
      trans_id: number;
      payee_name: string | null;
      amount: string;
      trans_date: string;
    };
  }[];
};

type ReconSession = {
  id: string;
  account_id: number;
  account_name: string;
  statement: { bank_name: string; parser_id: string; transactions: unknown[] };
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

export function Recon({ t, accounts, accountId, docId, onOpen, onBack, onCommitted }: Props) {
  const [inbox, setInbox] = useState<ReconInbox | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [pickedAccount, setPickedAccount] = useState(accountId ?? 0);
  const [session, setSession] = useState<ReconSession | null>(null);
  const [busy, setBusy] = useState(false);
  const [result, setResult] = useState<string | null>(null);

  useEffect(() => {
    void api
      .get<ReconInbox>("/api/recon/inbox")
      .then(setInbox)
      .catch((err: Error) => setError(err.message));
  }, []);

  const nameById = Object.fromEntries(accounts.map((a) => [a.account_id, a.name]));
  const selected = docId != null ? inbox?.documents.find((d) => d.id === docId) : undefined;

  useEffect(() => {
    if (selected?.account_id) setPickedAccount(selected.account_id);
    else if (accountId) setPickedAccount(accountId);
  }, [selected?.account_id, accountId]);

  async function runMatch() {
    if (!selected) return;
    if (!pickedAccount) {
      setError(t("reconNeedAccount"));
      return;
    }
    setBusy(true);
    setError(null);
    setResult(null);
    try {
      const created = await api.post<ReconSession>("/api/recon/sessions", {
        paperless_id: selected.id,
        account_id: pickedAccount,
      });
      setSession(created);
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
                {accounts
                  .filter((a) => a.status !== "Closed")
                  .map((a) => (
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
              {session.statement.bank_name} · {session.matches.length} {t("matching")}
            </p>
            <div className="table-wrap">
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
                  {session.matches.map((row, idx) => (
                    <tr key={idx}>
                      <td>
                        <input
                          type="checkbox"
                          checked={row.include}
                          onChange={(e) =>
                            void patchRow(idx, { include: e.target.checked })
                          }
                        />
                      </td>
                      <td>{row.bank_transaction.date}</td>
                      <td>{row.bank_transaction.description}</td>
                      <td className="num">{row.bank_transaction.amount}</td>
                      <td>{row.status}</td>
                      <td>
                        <select
                          value={row.selected_trans_id ?? ""}
                          onChange={(e) => {
                            const v = e.target.value;
                            void patchRow(
                              idx,
                              v
                                ? { selected_trans_id: Number(v), force_new_insert: false }
                                : { selected_trans_id: null, force_new_insert: true },
                            );
                          }}
                        >
                          <option value="">{t("reconNewInsert")}</option>
                          {row.candidates.map((c) => (
                            <option key={c.mmex_transaction.trans_id} value={c.mmex_transaction.trans_id}>
                              #{c.mmex_transaction.trans_id} {c.mmex_transaction.payee_name ?? ""}{" "}
                              {c.mmex_transaction.amount}
                            </option>
                          ))}
                        </select>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
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
                <td>
                  {doc.account_id ? nameById[doc.account_id] ?? "—" : t("reconUnmapped")}
                </td>
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
