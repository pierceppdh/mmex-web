# MMEX Web

Local-network web client for [Money Manager Ex](https://github.com/moneymanagerex/moneymanagerex).
It opens the official `.mmb` SQLite ledger. It is **not** a remote desktop of the wxWidgets app
and **not** the PHP capture WebApp.

**Status:** PR 16 — mobile quick-add (writes the real `.mmb`) and optional ingest of the PHP WebApp sidecar so port **9080** can be retired. Réconciliation Paperless (`Nouveau-Relevé`): list inbox, parse PDF, fuzzy-match, and commit (`STATUS=R`) while mmex-web holds the writer lock.

First visit with no `AUTH_USERNAME`/`AUTH_PASSWORD` shows a local account bootstrap
(stored as `data/auth.json`). Ledger APIs require the session cookie.

License: [GPL-2.0-or-later](LICENSE).

## Run locally (API tests)

```bash
uv sync --extra dev
uv run pytest
uv run uvicorn mmex_web_api.main:app --host 127.0.0.1 --port 8080 --workers 1
```

UI (optional, proxies `/api` to 8080):

```bash
cd apps/web && npm ci && npm run dev
```

## Docker

```bash
docker compose -f compose.yaml -f compose.local.yaml up --build
# http://localhost:9090/   health: http://localhost:9090/api/health
```

`compose.local.yaml` runs the process as container root so rootless Podman can write `./data`. On OMV (rootful Docker) use `compose.yaml` only and `chown -R 1000:1000 /data/mmex-web`.

Put a **copy** of `data.mmb` in `./data/data.mmb`. Do not mount the live desktop file until the lock is proven.

### Writer lock (`mmex-lock-v1`)

MMEX Web takes `data.mmb.lock` on start. Footer **Céder le verrou** / **Prendre le verrou** yields to (or takes back from) `bank-reconciliation-app`. The recon app acquires the same sidecar only around a real commit. POSIX `flock` + JSON `{protocol, holder, pid, acquired_at}`.

## Dockhand

See [DEPLOY.md](DEPLOY.md). Stack `mmex-web`, port **9090**, data `/data/mmex-web`.

Optional Paperless (inbox tag `Nouveau-Relevé`): set `PAPERLESS_URL` and `PAPERLESS_TOKEN` on the Dockhand stack. Do not use Compose `${VAR}` interpolation (Dockhand leading-space trap).

### Phone / WebApp 9080

Use **Saisie rapide** (FAB on small screens). It writes `CHECKINGACCOUNT_V1`, not `MMEX_New_Transaction.db`.

To empty leftover PHP WebApp reminders: copy `MMEX_New_Transaction.db` into the mmex-web data dir (or set `WEBAPP_DB_PATH`), then **Outils → Ancienne WebApp**. After a successful import you can stop the `webmmxapp` stack on **9080**. Do not point this container at the live desktop ledger.

## Layout

```
apps/api          FastAPI
apps/web          Vite + React
packages/mmex-domain   schema inspection (later: balances, repeats)
vendor/database   upstream tables.sql
```
