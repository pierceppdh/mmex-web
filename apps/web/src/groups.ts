import type { Account, Dashboard, Group } from "./types";

export function visibleGroups(dash: Dashboard, showClosed: boolean): Group[] {
  if (!showClosed || !dash.closed_accounts?.length) return dash.groups;
  const byType = new Map<string, Group>();
  for (const g of dash.groups) {
    byType.set(g.account_type, { ...g, accounts: [...g.accounts] });
  }
  for (const acc of dash.closed_accounts) {
    const existing = byType.get(acc.account_type);
    if (existing) {
      if (!existing.accounts.some((a) => a.account_id === acc.account_id)) {
        existing.accounts.push(acc);
        existing.count = existing.accounts.length;
      }
    } else {
      byType.set(acc.account_type, {
        account_type: acc.account_type,
        label_fr: acc.account_type,
        label_en: acc.account_type,
        count: 1,
        accounts: [acc],
      });
    }
  }
  return [...byType.values()];
}

export function checkingAccounts(accounts: Account[], showClosed: boolean, keepId?: number): Account[] {
  return accounts.filter((a) => {
    if (a.account_type === "Investment" || a.account_type === "Shares") return false;
    if (a.status === "Closed" && !showClosed && a.account_id !== keepId) return false;
    return true;
  });
}
