import { FormEvent, useState } from "react";
import { api } from "./api";
import type { Locale, MessageKey } from "./i18n";

type Props = {
  bootstrap: boolean;
  locale: Locale;
  t: (key: MessageKey) => string;
  onSignedIn: (username: string) => void;
};

export function Login({ bootstrap, locale, t, onSignedIn }: Props) {
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  async function onSubmit(event: FormEvent) {
    event.preventDefault();
    setBusy(true);
    setError(null);
    try {
      const path = bootstrap ? "/api/auth/bootstrap" : "/api/auth/login";
      const body = await api.post<{ username: string }>(path, {
        username,
        password,
      });
      onSignedIn(body.username);
    } catch {
      setError(bootstrap ? t("bootstrapError") : t("loginError"));
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="login-wrap" lang={locale}>
      <form className="panel login-card" onSubmit={onSubmit}>
        <h1>{bootstrap ? t("bootstrapTitle") : t("loginTitle")}</h1>
        {bootstrap && <p className="k">{t("bootstrapHint")}</p>}
        <label>
          {t("username")}
          <input
            autoComplete="username"
            autoFocus
            value={username}
            onChange={(e) => setUsername(e.target.value)}
            required
          />
        </label>
        <label>
          {t("password")}
          <input
            type="password"
            autoComplete={bootstrap ? "new-password" : "current-password"}
            value={password}
            onChange={(e) => setPassword(e.target.value)}
            minLength={bootstrap ? 8 : 1}
            required
          />
        </label>
        {error && <p className="error-text">{error}</p>}
        <button type="submit" disabled={busy}>
          {bootstrap ? t("submitBootstrap") : t("submitLogin")}
        </button>
      </form>
    </div>
  );
}
