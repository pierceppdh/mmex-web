import { useEffect, useState } from "react";
import type { Account, Dashboard as DashboardData, Group } from "./types";
import type { Locale, MessageKey } from "./i18n";

type Props = {
  dash: DashboardData;
  locale: Locale;
  t: (key: MessageKey) => string;
  groupFilter?: string;
  favoritesOnly?: boolean;
  groups?: Group[];
  onOpenAccount: (accountId: number) => void;
  onEditAccount?: (accountId: number) => void;
  onNewAccount?: () => void;
  onOpenScheduled?: () => void;
  onQuickAdd?: () => void;
};

export function Dashboard({
  dash,
  locale,
  t,
  groupFilter,
  favoritesOnly,
  groups: groupsProp,
  onOpenAccount,
  onEditAccount,
  onNewAccount,
  onOpenScheduled,
  onQuickAdd,
}: Props) {
  const source = groupsProp ?? dash.groups;
  const groups = favoritesOnly
    ? [
        {
          account_type: "favorites",
          label_fr: t("favorites"),
          label_en: t("favorites"),
          count: dash.favorites.length,
          accounts: dash.favorites,
        } satisfies Group,
      ]
    : groupFilter
      ? source.filter((g) => g.account_type === groupFilter)
      : source;

  return (
    <>
      {!groupFilter && !favoritesOnly && (
        <section className="hero">
          <div>
            <div className="k">{t("netWorth")}</div>
            <div className="net">{dash.net_worth_formatted}</div>
            <div className="k">
              {dash.base_currency
                ? `${t("baseCurrency")} : ${dash.base_currency.name} (${dash.base_currency.symbol})`
                : ""}
            </div>
          </div>
          <div className="home-actions">
            {onNewAccount && (
              <button type="button" className="home-action" onClick={onNewAccount}>
                <strong>{t("newAccount")}</strong>
                <span className="k">{t("homeNewAccountHint")}</span>
              </button>
            )}
            {onQuickAdd && (
              <button type="button" className="home-action primary" onClick={onQuickAdd}>
                <strong>{t("quickAdd")}</strong>
                <span className="k">{t("homeQuickAddHint")}</span>
              </button>
            )}
            {onOpenScheduled ? (
              <button type="button" className="home-action" onClick={onOpenScheduled}>
                <strong>
                  {dash.upcoming_bills} {t("upcoming")}
                </strong>
                <span className="k">{t("homeBillsHint")}</span>
              </button>
            ) : (
              <div className="home-action">
                <strong>
                  {dash.upcoming_bills} {t("upcoming")}
                </strong>
                <span className="k">{t("homeBillsHint")}</span>
              </div>
            )}
          </div>
        </section>
      )}

      {groups.map((group) => (
        <section className="panel" key={group.account_type}>
          <h2>
            {locale === "en" ? group.label_en : group.label_fr}{" "}
            <span className="count">{group.count}</span>
          </h2>
          <AccountList
            accounts={group.accounts}
            t={t}
            onOpen={onOpenAccount}
            onEdit={onEditAccount}
          />
        </section>
      ))}
    </>
  );
}

function AccountList({
  accounts,
  t,
  onOpen,
  onEdit,
}: {
  accounts: Account[];
  t: (key: MessageKey) => string;
  onOpen: (id: number) => void;
  onEdit?: (id: number) => void;
}) {
  const [menu, setMenu] = useState<{ x: number; y: number; id: number } | null>(null);

  useEffect(() => {
    function close() {
      setMenu(null);
    }
    window.addEventListener("click", close);
    window.addEventListener("scroll", close, true);
    return () => {
      window.removeEventListener("click", close);
      window.removeEventListener("scroll", close, true);
    };
  }, []);

  return (
    <ul className="accounts">
      {accounts.map((acc) => (
        <li
          key={acc.account_id}
          className={`account-row${acc.status === "Closed" ? " closed" : ""}`}
          onContextMenu={(e) => {
            if (!onEdit) return;
            e.preventDefault();
            setMenu({ x: e.clientX, y: e.clientY, id: acc.account_id });
          }}
        >
          <button type="button" className="account-link" onClick={() => onOpen(acc.account_id)}>
            <span className="name">
              {acc.name}
              {acc.favorite ? <span className="star">★</span> : null}
              {acc.status === "Closed" ? (
                <span className="closed-tag">{t("closedBadge")}</span>
              ) : null}
            </span>
            <span className="amt">{acc.display_formatted}</span>
          </button>
          {onEdit && (
            <button
              type="button"
              className="icon-btn"
              aria-label={t("accountProperties")}
              onClick={(e) => {
                e.stopPropagation();
                onEdit(acc.account_id);
              }}
            >
              ⋮
            </button>
          )}
        </li>
      ))}
      {menu && onEdit && (
        <div className="ctx-menu" style={{ left: menu.x, top: menu.y }} role="menu">
          <button
            type="button"
            onClick={() => {
              onOpen(menu.id);
              setMenu(null);
            }}
          >
            {t("openRegister")}
          </button>
          <button
            type="button"
            onClick={() => {
              onEdit(menu.id);
              setMenu(null);
            }}
          >
            {t("accountProperties")}
          </button>
        </div>
      )}
    </ul>
  );
}
