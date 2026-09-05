import { useEffect, useState } from "react";
import { api } from "./api";
import type { MessageKey } from "./i18n";
import type { Account, ReconDoc, ReconInbox } from "./types";

type Props = {
  t: (key: MessageKey) => string;
  accounts: Account[];
  accountId?: number;
  docId?: number;
  onOpen: (accountId: number | null, docId: number) => void;
};

function docLabel(doc: ReconDoc): string {
  return doc.title || doc.original_file_name || `#${doc.id}`;
}

export function Recon({ t, accounts, accountId, docId, onOpen }: Props) {
  const [inbox, setInbox] = useState<ReconInbox | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    void api
      .get<ReconInbox>("/api/recon/inbox")
      .then(setInbox)
      .catch((err: Error) => setError(err.message));
  }, []);

  const nameById = Object.fromEntries(accounts.map((a) => [a.account_id, a.name]));
  const selected = inbox?.documents.find((d) => d.id === docId);

  return (
    <section className="panel">
      <h2>{t("recon")}</h2>
      <p className="k">{t("reconHint")}</p>
      {error && <p className="error-text">{error}</p>}
      {inbox && !inbox.configured && <p className="k">{t("reconNotConfigured")}</p>}
      {inbox && inbox.configured && inbox.documents.length === 0 && (
        <p className="k">{t("reconEmpty")}</p>
      )}
      {selected && (
        <div className="panel" style={{ marginTop: "1rem" }}>
          <h3>{docLabel(selected)}</h3>
          <p className="k">
            {selected.created}
            {selected.account_id ? ` · ${nameById[selected.account_id] ?? ""}` : ""}
          </p>
          <p>{t("reconWizardHint")}</p>
        </div>
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
              <tr key={doc.id} className={doc.id === docId ? "active" : undefined}>
                <td>{doc.created}</td>
                <td>{docLabel(doc)}</td>
                <td>
                  {doc.account_id ? nameById[doc.account_id] ?? "—" : t("reconUnmapped")}
                </td>
                <td>
                  <button
                    type="button"
                    className="ghost"
                    onClick={() => onOpen(doc.account_id ?? accountId ?? null, doc.id)}
                  >
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
