import type { ManagerId, View } from "./types";

const MANAGERS: ManagerId[] = ["payees", "categories", "tags", "currencies", "fields"];

export function pathToView(pathname: string): View {
  const p = pathname.replace(/\/+$/, "") || "/";
  if (p === "/" || p === "") return { kind: "home" };
  if (p === "/quickadd") return { kind: "quickadd" };
  if (p === "/all") return { kind: "all" };
  if (p === "/favorites") return { kind: "favorites" };
  if (p === "/scheduled") return { kind: "scheduled" };
  if (p === "/budgets") return { kind: "budgets" };
  if (p === "/reports") return { kind: "reports" };
  if (p === "/stocks") return { kind: "stocks" };
  if (p === "/assets") return { kind: "assets" };
  if (p === "/tools") return { kind: "tools" };
  if (p === "/settings") return { kind: "settings" };
  if (p === "/recon") return { kind: "recon" };
  const reconAcc = /^\/account\/(\d+)\/recon\/(\d+)$/.exec(p);
  if (reconAcc) {
    return {
      kind: "reconDoc",
      accountId: Number(reconAcc[1]),
      docId: Number(reconAcc[2]),
    };
  }
  const acc = /^\/account\/(\d+)$/.exec(p);
  if (acc) return { kind: "account", accountId: Number(acc[1]) };
  const type = /^\/type\/(.+)$/.exec(p);
  if (type) return { kind: "type", accountType: decodeURIComponent(type[1]) };
  const mgr = /^\/managers\/([^/]+)$/.exec(p);
  if (mgr && (MANAGERS as string[]).includes(mgr[1])) {
    return { kind: "manager", id: mgr[1] as ManagerId };
  }
  return { kind: "home" };
}

export function viewToPath(view: View): string {
  switch (view.kind) {
    case "home":
      return "/";
    case "quickadd":
      return "/quickadd";
    case "all":
      return "/all";
    case "favorites":
      return "/favorites";
    case "scheduled":
      return "/scheduled";
    case "budgets":
      return "/budgets";
    case "reports":
      return "/reports";
    case "stocks":
      return "/stocks";
    case "assets":
      return "/assets";
    case "tools":
      return "/tools";
    case "settings":
      return "/settings";
    case "recon":
      return "/recon";
    case "reconDoc":
      return `/account/${view.accountId}/recon/${view.docId}`;
    case "account":
      return `/account/${view.accountId}`;
    case "type":
      return `/type/${encodeURIComponent(view.accountType)}`;
    case "manager":
      return `/managers/${view.id}`;
    default:
      return "/";
  }
}
