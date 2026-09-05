import { useEffect, useState } from "react";
import { api } from "./api";
import type { MessageKey } from "./i18n";
import type { Account, ReconDoc, ReconInbox } from "./types";

type Props = {
  t: (key: MessageKey) => string;
  accounts: Account[];
  accountId?: number;
  docId?: number;
  onOpen: (docId: number) => void;
  onBack: () => void;
};

function docLabel(doc: ReconDoc): string {
  return doc.title || doc.original_file_name || `#${doc.id}`;
}

export function Recon({ t, accounts, accountId, docId, onOpen, onBack }: Props) {
  const [inbox, setInbox] = useState<ReconInbox | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [pickedAccount, setPickedAccount] = useState(accountId ?? 0);

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

  if (docId != null) {
    return (
      <section className="panel recon-wizard">
        <button type="button" className="ghost" onClick={onBack}>
          ← {t("reconBack")}
        </button>
        <h2>{t("recon")}</h2>
        {error && <p className="error-text">{error}</p>}
        {!inbox && !error && <p className="k">{t("loading")}</p>}
        {inbox && !selected && <p className="error-text">{t("reconMissingDoc")}</p>}
        {selected && (
          <>
            <h3>{docLabel(selected)}</h3>
            <p className="k">
              {selected.created}
              {selected.tags.length ? ` · ${selected.tags.join(", ")}` : ""}
            </p>
            <p>{t("reconWizardHint")}</p>
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
              </a>
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
