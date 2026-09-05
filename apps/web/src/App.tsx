import { useCallback, useEffect, useMemo, useState, type ReactNode } from "react";
import { Dashboard } from "./Dashboard";
import { Register } from "./Register";
import { Login } from "./Login";
import { Managers } from "./Managers";
import { Fields } from "./Fields";
import { Scheduled } from "./Scheduled";
import { Budgets } from "./Budgets";
import { Reports } from "./Reports";
import { Stocks } from "./Stocks";
import { Assets } from "./Assets";
import { Tools } from "./Tools";
import { Settings } from "./Settings";
import { Recon } from "./Recon";
import { QuickAdd } from "./QuickAdd";
import { AccountEditor } from "./AccountEditor";
import { Palette, type PaletteCommand } from "./Palette";
import { api } from "./api";
import { visibleGroups } from "./groups";
import { STRINGS, readLocale, writeLocale, type Locale, type MessageKey } from "./i18n";
import { pathToView, viewToPath } from "./routes";
import { applyTheme, readTheme, watchSystemTheme, writeTheme, type ThemePref } from "./theme";
import type {
  AuthStatus,
  Dashboard as DashboardData,
  Health,
  ManagerId,
  ReconInbox,
  View,
} from "./types";

const MANAGERS: ManagerId[] = ["payees", "categories", "tags", "currencies", "fields"];
const SOON = [] as const;

export default function App() {
  const [locale, setLocale] = useState<Locale>(() => readLocale("fr"));
  const [auth, setAuth] = useState<AuthStatus | null>(null);
  const [health, setHealth] = useState<Health | null>(null);
  const [dash, setDash] = useState<DashboardData | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [lockMsg, setLockMsg] = useState<string | null>(null);
  const [view, setView] = useState<View>(() =>
    typeof window !== "undefined" ? pathToView(window.location.pathname) : { kind: "home" },
  );
  const [navOpen, setNavOpen] = useState(false);
  const [navFolded, setNavFolded] = useState(() => {
    try {
      return localStorage.getItem("mmex-nav-folded") === "1";
    } catch {
      return false;
    }
  });
  const [paletteOpen, setPaletteOpen] = useState(false);
  const [newTxnNonce, setNewTxnNonce] = useState(0);
  const [theme, setTheme] = useState<ThemePref>(() => readTheme());
  const [showClosed, setShowClosed] = useState(false);
  const [accountEdit, setAccountEdit] = useState<number | "new" | null>(null);
  const [reconInbox, setReconInbox] = useState<ReconInbox | null>(null);
  const [openNav, setOpenNav] = useState<Record<string, boolean>>(() => {
    try {
      const raw = localStorage.getItem("mmex-nav-open");
      if (raw) return JSON.parse(raw) as Record<string, boolean>;
    } catch {
      /* ignore */
    }
    return { favorites: true };
  });

  const t = useCallback((key: MessageKey) => STRINGS[locale][key], [locale]);

  const toggleNav = useCallback((id: string) => {
    setOpenNav((prev) => {
      const next = { ...prev, [id]: !prev[id] };
      try {
        localStorage.setItem("mmex-nav-open", JSON.stringify(next));
      } catch {
        /* ignore */
      }
      return next;
    });
  }, []);

  const go = useCallback((next: View) => {
    setView(next);
    setNavOpen(false);
    const path = viewToPath(next);
    if (typeof window !== "undefined" && window.location.pathname !== path) {
      window.history.pushState(null, "", path);
    }
  }, []);

  useEffect(() => {
    applyTheme(theme);
    return watchSystemTheme(theme, () => applyTheme(theme));
  }, [theme]);

  useEffect(() => {
    if (view.kind !== "account" || !dash) return;
    const acc = dash.accounts.find((a) => a.account_id === view.accountId);
    if (!acc) return;
    setOpenNav((prev) => {
      if (prev[acc.account_type] && (!acc.favorite || prev.favorites)) return prev;
      const next = { ...prev, [acc.account_type]: true };
      if (acc.favorite) next.favorites = true;
      try {
        localStorage.setItem("mmex-nav-open", JSON.stringify(next));
      } catch {
        /* ignore */
      }
      return next;
    });
  }, [view, dash]);

  useEffect(() => {
    function onPop() {
      setView(pathToView(window.location.pathname));
    }
    window.addEventListener("popstate", onPop);
    return () => window.removeEventListener("popstate", onPop);
  }, []);

  const changeLocale = (next: Locale) => {
    setLocale(next);
    writeLocale(next);
  };

  const loadLedger = useCallback(async () => {
    const [h, d] = await Promise.all([
      api.get<Health>("/api/health"),
      api.get<DashboardData>("/api/dashboard").catch((err: Error & { status?: number }) => {
        if (err.status === 401 || err.status === 409 || err.status === 503) return null;
        throw err;
      }),
    ]);
    setHealth(h);
    setDash(d);
    try {
      const inbox = await api.get<ReconInbox>("/api/recon/inbox");
      setReconInbox(inbox);
    } catch {
      setReconInbox(null);
    }
    try {
      const prefs = await api.get<{
        theme: ThemePref;
        show_closed_accounts: boolean;
      }>("/api/settings");
      setShowClosed(prefs.show_closed_accounts);
      setTheme(prefs.theme);
      writeTheme(prefs.theme);
    } catch {
      /* not signed in or schema */
    }
  }, []);

  useEffect(() => {
    if (!auth?.authenticated) return;
    const id = window.setInterval(() => {
      void api.get<Health>("/api/health").then(setHealth).catch(() => undefined);
    }, 10000);
    return () => window.clearInterval(id);
  }, [auth?.authenticated]);

  async function onYieldLock() {
    setLockMsg(null);
    try {
      await api.post("/api/lock/release");
      await loadLedger();
    } catch (err) {
      setLockMsg(err instanceof Error ? err.message : t("saveError"));
    }
  }

  async function onTakeLock() {
    setLockMsg(null);
    try {
      await api.post("/api/lock/acquire");
      await loadLedger();
    } catch (err) {
      setLockMsg(err instanceof Error ? err.message : t("saveError"));
    }
  }

  useEffect(() => {
    api
      .get<AuthStatus>("/api/auth/status")
      .then((status) => {
        setAuth(status);
        if (status.locale_default === "en" || status.locale_default === "fr") {
          setLocale((current) => {
            try {
              if (localStorage.getItem("mmex-locale")) return current;
            } catch {
              /* ignore */
            }
            return status.locale_default;
          });
        }
        if (status.authenticated) return loadLedger();
        return api.get<Health>("/api/health").then(setHealth);
      })
      .catch((err: Error) => setError(err.message));
  }, [loadLedger]);

  useEffect(() => {
    function onKey(event: KeyboardEvent) {
      const target = event.target as HTMLElement | null;
      const typing =
        target &&
        (target.tagName === "INPUT" ||
          target.tagName === "TEXTAREA" ||
          target.isContentEditable);
      if ((event.key === "k" || event.key === "K") && (event.ctrlKey || event.metaKey)) {
        event.preventDefault();
        setPaletteOpen((open) => !open);
        return;
      }
      if (event.key === "/" && !typing && auth?.authenticated) {
        event.preventDefault();
        setPaletteOpen(true);
      }
      if (event.key === "Escape") {
        setPaletteOpen(false);
        setNavOpen(false);
        setAccountEdit(null);
      }
    }
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [auth?.authenticated]);

  const commands: PaletteCommand[] = useMemo(() => {
    if (!dash) return [];
    const list: PaletteCommand[] = [
      { id: "home", label: t("home"), run: () => go({ kind: "home" }) },
      { id: "quickadd", label: t("quickAdd"), run: () => go({ kind: "quickadd" }) },
      { id: "all", label: t("allTransactions"), run: () => go({ kind: "all" }) },
      { id: "fav", label: t("favorites"), run: () => go({ kind: "favorites" }) },
      ...dash.groups.map((g) => ({
        id: `type-${g.account_type}`,
        label: locale === "en" ? g.label_en : g.label_fr,
        run: () => go({ kind: "type", accountType: g.account_type }),
      })),
      ...(showClosed ? dash.accounts : dash.accounts.filter((a) => a.status !== "Closed")).map((acc) => ({
        id: `acc-${acc.account_id}`,
        label: `${t("account")}: ${acc.name}`,
        run: () => go({ kind: "account", accountId: acc.account_id }),
      })),
      ...(reconInbox?.documents ?? []).map((doc) => ({
        id: `recon-doc-${doc.id}`,
        label: `${t("recon")}: ${doc.title || doc.original_file_name || `#${doc.id}`}`,
        run: () => go({ kind: "reconDoc", docId: doc.id }),
      })),
      {
        id: "new-txn",
        label: t("newTransaction"),
        run: () => {
          if (view.kind === "account") setNewTxnNonce((n) => n + 1);
          else go({ kind: "quickadd" });
        },
      },
      {
        id: "recon",
        label: t("recon"),
        run: () => go({ kind: "recon" }),
      },
      {
        id: "scheduled",
        label: t("scheduled"),
        run: () => go({ kind: "scheduled" }),
      },
      {
        id: "budgets",
        label: t("budgets"),
        run: () => go({ kind: "budgets" }),
      },
      {
        id: "reports",
        label: t("reports"),
        run: () => go({ kind: "reports" }),
      },
      {
        id: "stocks",
        label: t("stocks"),
        run: () => go({ kind: "stocks" }),
      },
      {
        id: "assets",
        label: t("assets"),
        run: () => go({ kind: "assets" }),
      },
      {
        id: "tools",
        label: t("tools"),
        run: () => go({ kind: "tools" }),
      },
      {
        id: "settings",
        label: t("settings"),
        run: () => go({ kind: "settings" }),
      },
      {
        id: "yield-lock",
        label: t("yieldLock"),
        disabled: !health?.lock.acquired,
        run: () => void onYieldLock(),
      },
      {
        id: "take-lock",
        label: t("takeLock"),
        disabled: Boolean(health?.lock.acquired),
        run: () => void onTakeLock(),
      },
      ...MANAGERS.map((id) => ({
        id,
        label: t(id),
        run: () => go({ kind: "manager", id }),
      })),
      ...SOON.map((id) => ({
        id,
        label: t(id),
        run: () => go({ kind: "soon", id }),
      })),
    ];
    return list;
  }, [dash, locale, t, view, health, go, showClosed, reconInbox]);

  async function signOut() {
    await api.post("/api/auth/logout");
    setAuth({
      authenticated: false,
      username: null,
      bootstrap: false,
      locale_default: locale,
    });
    setDash(null);
    setView({ kind: "home" });
  }

  if (error) {
    return (
      <p className="error-text" style={{ padding: "2rem" }}>
        {t("apiDown")} : {error}
      </p>
    );
  }
  if (!auth) return <p className="k" style={{ padding: "2rem" }}>{t("loading")}</p>;

  if (!auth.authenticated) {
    return (
      <Login
        bootstrap={auth.bootstrap}
        locale={locale}
        t={t}
        onSignedIn={async (username) => {
          setAuth({ ...auth, authenticated: true, username, bootstrap: false });
          await loadLedger();
        }}
      />
    );
  }

  const selectedAccount =
    view.kind === "account"
      ? dash?.accounts.find((a) => a.account_id === view.accountId)
      : undefined;
  const navGroups = dash ? visibleGroups(dash, showClosed) : [];

  return (
    <div
      className={`shell${navOpen ? " nav-open" : ""}${navFolded ? " nav-folded" : ""}`}
      lang={locale}
    >
      {navOpen && (
        <button
          type="button"
          className="nav-backdrop"
          aria-label={t("openMenu")}
          onClick={() => setNavOpen(false)}
        />
      )}
      <aside className="nav">
        <div className="nav-brand">
          <strong>{t("appName")}</strong>
          <button
            type="button"
            className="nav-fold"
            aria-label={navFolded ? t("expandMenu") : t("foldMenu")}
            title={navFolded ? t("expandMenu") : t("foldMenu")}
            onClick={() => {
              setNavFolded((prev) => {
                const next = !prev;
                try {
                  localStorage.setItem("mmex-nav-folded", next ? "1" : "0");
                } catch {
                  /* ignore */
                }
                return next;
              });
            }}
          >
            {navFolded ? "›" : "‹"}
          </button>
          <button type="button" className="nav-close" onClick={() => setNavOpen(false)}>
            ×
          </button>
        </div>
        <NavButton active={view.kind === "home"} onClick={() => go({ kind: "home" })}>
          {t("home")}
        </NavButton>
        <NavButton
          active={view.kind === "quickadd"}
          onClick={() => go({ kind: "quickadd" })}
        >
          {t("quickAdd")}
        </NavButton>
        <NavButton active={view.kind === "all"} onClick={() => go({ kind: "all" })}>
          {t("allTransactions")}
        </NavButton>
        <NavGroup
          id="favorites"
          label={t("favorites")}
          count={dash?.favorites.length ?? 0}
          accounts={dash?.favorites ?? []}
          open={Boolean(openNav.favorites)}
          active={view.kind === "favorites"}
          activeAccountId={view.kind === "account" ? view.accountId : undefined}
          onToggle={() => toggleNav("favorites")}
          onOpenGroup={() => go({ kind: "favorites" })}
          onOpenAccount={(id) => go({ kind: "account", accountId: id })}
          statements={reconInbox?.by_account}
          t={t}
          onOpenStatement={(_accountId, docId) => go({ kind: "reconDoc", docId })}
        />
        <div className="nav-label">{locale === "en" ? "Accounts" : "Comptes"}</div>
        {navGroups.map((g) => (
          <NavGroup
            key={g.account_type}
            id={g.account_type}
            label={locale === "en" ? g.label_en : g.label_fr}
            count={g.count}
            accounts={g.accounts}
            open={Boolean(openNav[g.account_type])}
            active={view.kind === "type" && view.accountType === g.account_type}
            activeAccountId={view.kind === "account" ? view.accountId : undefined}
            onToggle={() => toggleNav(g.account_type)}
            onOpenGroup={() => go({ kind: "type", accountType: g.account_type })}
            onOpenAccount={(id) => go({ kind: "account", accountId: id })}
            statements={reconInbox?.by_account}
            t={t}
            onOpenStatement={(_accountId, docId) => go({ kind: "reconDoc", docId })}
          />
        ))}
        <NavButton
          active={view.kind === "recon" || view.kind === "reconDoc"}
          onClick={() => go({ kind: "recon" })}
        >
          {t("recon")}
          {reconInbox && reconInbox.documents.length > 0 ? (
            <span className="count">{reconInbox.documents.length}</span>
          ) : null}
        </NavButton>
        <NavButton
          active={view.kind === "scheduled"}
          onClick={() => go({ kind: "scheduled" })}
        >
          {t("scheduled")}
        </NavButton>
        <NavButton
          active={view.kind === "budgets"}
          onClick={() => go({ kind: "budgets" })}
        >
          {t("budgets")}
        </NavButton>
        <NavButton
          active={view.kind === "reports"}
          onClick={() => go({ kind: "reports" })}
        >
          {t("reports")}
        </NavButton>
        <NavButton
          active={view.kind === "stocks"}
          onClick={() => go({ kind: "stocks" })}
        >
          {t("stocks")}
        </NavButton>
        <NavButton
          active={view.kind === "assets"}
          onClick={() => go({ kind: "assets" })}
        >
          {t("assets")}
        </NavButton>
        <NavButton
          active={view.kind === "tools"}
          onClick={() => go({ kind: "tools" })}
        >
          {t("tools")}
        </NavButton>
        <NavButton
          active={view.kind === "settings"}
          onClick={() => go({ kind: "settings" })}
        >
          {t("settings")}
        </NavButton>
        <div className="nav-label">{t("managers")}</div>
        {MANAGERS.map((id) => (
          <NavButton
            key={id}
            active={view.kind === "manager" && view.id === id}
            onClick={() => go({ kind: "manager", id })}
          >
            {t(id)}
          </NavButton>
        ))}
        {SOON.length > 0 && (
          <>
            <div className="nav-label">{t("comingSoon")}</div>
            {SOON.map((id) => (
              <NavButton
                key={id}
                active={view.kind === "soon" && view.id === id}
                dim
                onClick={() => go({ kind: "soon", id })}
              >
                {t(id)}
              </NavButton>
            ))}
          </>
        )}
      </aside>

      <main className="main">
        {(health?.lock.read_only || lockMsg) && (
          <p className="ro-banner">
            {lockMsg || t("lockReadOnlyHint")}
            {!lockMsg && health?.lock.holder ? ` (${health.lock.holder})` : ""}
          </p>
        )}
        <header className="main-bar">
          <button type="button" className="menu-btn" onClick={() => setNavOpen(true)}>
            {t("openMenu")}
          </button>
          <button type="button" className="ghost palette-btn" onClick={() => setPaletteOpen(true)}>
            {t("commandPalette")}
            <span className="kbd-hint"> ⌘K</span>
          </button>
        </header>

        {view.kind === "home" && dash && (
          <Dashboard
            dash={dash}
            locale={locale}
            t={t}
            groups={navGroups}
            onOpenAccount={(id) => go({ kind: "account", accountId: id })}
            onEditAccount={(id) => setAccountEdit(id)}
            onNewAccount={() => setAccountEdit("new")}
            onOpenScheduled={() => go({ kind: "scheduled" })}
            onQuickAdd={() => go({ kind: "quickadd" })}
          />
        )}
        {view.kind === "quickadd" && dash && (
          <QuickAdd
            accounts={dash.accounts}
            t={t}
            showClosed={showClosed}
            onChanged={() => void loadLedger()}
          />
        )}
        {view.kind === "all" && dash && (
          <Register
            allAccounts
            accountName={t("allTransactions")}
            accounts={dash.accounts}
            t={t}
            onChanged={() => void loadLedger()}
          />
        )}
        {view.kind === "favorites" && dash && (
          <Dashboard
            dash={dash}
            locale={locale}
            t={t}
            favoritesOnly
            onOpenAccount={(id) => go({ kind: "account", accountId: id })}
            onEditAccount={(id) => setAccountEdit(id)}
          />
        )}
        {view.kind === "type" && dash && (
          <Dashboard
            dash={dash}
            locale={locale}
            t={t}
            groups={navGroups}
            groupFilter={view.accountType}
            onOpenAccount={(id) => go({ kind: "account", accountId: id })}
            onEditAccount={(id) => setAccountEdit(id)}
          />
        )}
        {view.kind === "account" && dash && (
          <Register
            accountId={view.accountId}
            accountName={selectedAccount?.name ?? `#${view.accountId}`}
            account={selectedAccount}
            accounts={dash.accounts}
            t={t}
            newTxnNonce={newTxnNonce}
            onChanged={() => void loadLedger()}
            onEditAccount={() => setAccountEdit(view.accountId)}
          />
        )}
        {view.kind === "scheduled" && dash && (
          <Scheduled
            accounts={dash.accounts}
            locale={locale}
            t={t}
            onChanged={() => void loadLedger()}
          />
        )}
        {view.kind === "budgets" && <Budgets locale={locale} t={t} />}
        {view.kind === "reports" && <Reports locale={locale} t={t} />}
        {view.kind === "stocks" && <Stocks t={t} onChanged={() => void loadLedger()} />}
        {view.kind === "assets" && <Assets t={t} />}
        {(view.kind === "recon" || view.kind === "reconDoc") && dash && (
          <Recon
            t={t}
            accounts={dash.accounts}
            accountId={view.kind === "reconDoc" ? view.accountId : undefined}
            docId={view.kind === "reconDoc" ? view.docId : undefined}
            onOpen={(docId) => go({ kind: "reconDoc", docId })}
            onBack={() => go({ kind: "recon" })}
            onCommitted={() => void loadLedger()}
          />
        )}
        {view.kind === "tools" && dash && (
          <Tools accounts={dash.accounts} t={t} onChanged={() => void loadLedger()} />
        )}
        {view.kind === "settings" && (
          <Settings t={t} onChanged={() => void loadLedger()} />
        )}
        {view.kind === "manager" && view.id === "fields" && <Fields t={t} />}
        {view.kind === "manager" && view.id !== "fields" && <Managers id={view.id} t={t} />}
        {view.kind === "soon" && (
          <section className="panel">
            <h2>{t(view.id as MessageKey)}</h2>
            <p className="k">{t("comingSoonBody")}</p>
          </section>
        )}
      </main>

      <footer className="status">
        <span>
          {t("appName")} {health?.version ?? ""}
        </span>
        <span>
          {t("schema")} {health?.db.user_version ?? "—"}
        </span>
        <span>
          {t("lockHeld")}:{" "}
          {health?.lock.acquired
            ? health.lock.holder
            : health?.lock.read_only
              ? t("readOnly")
              : "—"}
        </span>
        {health?.lock.acquired ? (
          <button type="button" className="ghost" onClick={() => void onYieldLock()}>
            {t("yieldLock")}
          </button>
        ) : (
          <button type="button" className="ghost" onClick={() => void onTakeLock()}>
            {t("takeLock")}
          </button>
        )}
        <span>{auth.username}</span>
        <button
          type="button"
          className="ghost"
          onClick={() => changeLocale(locale === "fr" ? "en" : "fr")}
        >
          {locale === "fr" ? "EN" : "FR"}
        </button>
        <button type="button" className="ghost" onClick={() => void signOut()}>
          {t("logout")}
        </button>
      </footer>

      {accountEdit != null && (
        <div className="drawer">
          <AccountEditor
            accountId={accountEdit === "new" ? null : accountEdit}
            t={t}
            onClose={() => setAccountEdit(null)}
            onSaved={(id) => {
              const editing = accountEdit;
              setAccountEdit(null);
              void loadLedger();
              if (id) go({ kind: "account", accountId: id });
              else if (view.kind === "account" && editing !== "new" && view.accountId === editing) {
                go({ kind: "home" });
              }
            }}
          />
        </div>
      )}
      {view.kind !== "quickadd" && auth.authenticated && (
        <button
          type="button"
          className="fab"
          onClick={() => go({ kind: "quickadd" })}
        >
          + {t("quickAdd")}
        </button>
      )}
      <Palette
        open={paletteOpen}
        commands={commands}
        t={t}
        onClose={() => setPaletteOpen(false)}
      />
    </div>
  );
}

function NavButton({
  active,
  dim,
  onClick,
  children,
}: {
  active: boolean;
  dim?: boolean;
  onClick: () => void;
  children: ReactNode;
}) {
  return (
    <button
      type="button"
      className={`nav-item${active ? " active" : ""}${dim ? " dim" : ""}`}
      onClick={onClick}
    >
      {children}
    </button>
  );
}

function NavGroup({
  label,
  count,
  accounts,
  open,
  active,
  activeAccountId,
  onToggle,
  onOpenGroup,
  onOpenAccount,
  statements,
  t,
  onOpenStatement,
}: {
  id: string;
  label: string;
  count: number;
  accounts: { account_id: number; name: string; status: string }[];
  open: boolean;
  active: boolean;
  activeAccountId?: number;
  onToggle: () => void;
  onOpenGroup: () => void;
  onOpenAccount: (id: number) => void;
  statements?: Record<string, { id: number; title: string; original_file_name: string }[]>;
  t: (key: MessageKey) => string;
  onOpenStatement: (accountId: number, docId: number) => void;
}) {
  return (
    <div className="nav-tree">
      <div className="nav-tree-row">
        <button
          type="button"
          className="nav-twist"
          aria-expanded={open}
          aria-label={label}
          onClick={onToggle}
        >
          {open ? "▾" : "▸"}
        </button>
        <NavButton active={active} onClick={onOpenGroup}>
          {label}
          <span className="count">{count}</span>
        </NavButton>
      </div>
      {open &&
        accounts.map((acc) => {
          const docs = statements?.[String(acc.account_id)] ?? [];
          return (
            <div key={acc.account_id} className="nav-leaf-wrap">
              <button
                type="button"
                className={`nav-item nav-leaf${activeAccountId === acc.account_id ? " active" : ""}${acc.status === "Closed" ? " closed" : ""}`}
                onClick={() => onOpenAccount(acc.account_id)}
              >
                {acc.name}
                {docs.length > 0 ? <span className="count">{docs.length}</span> : null}
              </button>
              {docs.length > 0 && (
                <label className="nav-stmt">
                  {t("reconPickStatement")}
                  <select
                    defaultValue=""
                    onChange={(e) => {
                      const id = Number(e.target.value);
                      if (id) onOpenStatement(acc.account_id, id);
                      e.target.value = "";
                    }}
                  >
                    <option value="">{t("reconPickStatement")}</option>
                    {docs.map((doc) => (
                      <option key={doc.id} value={doc.id}>
                        {doc.title || doc.original_file_name || `#${doc.id}`}
                      </option>
                    ))}
                  </select>
                </label>
              )}
            </div>
          );
        })}
    </div>
  );
}
