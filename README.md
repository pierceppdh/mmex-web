# MMEX Web

Local-network web client for [Money Manager Ex](https://github.com/moneymanagerex/moneymanagerex).
It opens the official `.mmb` SQLite ledger. It is **not** a remote desktop of the wxWidgets app
and **not** the PHP capture WebApp.

**Status:** LAN ledger. Mobile quick-add writes the real `.mmb`. Réconciliation Paperless (`Nouveau-Relevé`) lists the inbox, parses each PDF, fuzzy-matches ledger rows, and commits (`STATUS=R`) while mmex-web holds the writer lock. The date and amount window is in Settings (defaults: 4 days and 1.00).

There is no login. The app is meant for the home LAN, with remote use through the VPN. Anyone who can open the port can read and write the ledger.

License: [GPL-2.0-or-later](LICENSE).

## Run locally (API tests)

```bash
uv sync --extra dev
uv run pytest
uv run uvicorn mmex_web_api.main:app --host 127.0.0.1 --port 8080 --workers 1
```

`.python-version` pins 3.12, the same interpreter as the image. Do not use the system 3.15: it has no wheels for this stack and no C compiler. `uvicorn[standard]` (httptools) is an optional extra used only by the Docker image, not by tests.

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

On OMV the host bind is `${MMEX_HOST_VOLUME:-/data/mmex-web}:/data`. Homepage.dev discovery labels use group **Compte**.

### Writer lock (`mmex-lock-v1`)

MMEX Web takes `data.mmb.lock` on start. Footer **Céder le verrou** / **Prendre le verrou** yields to (or takes back from) `bank-reconciliation-app`. The recon app acquires the same sidecar only around a real commit. POSIX `flock` + JSON `{protocol, holder, pid, acquired_at}`.

## Dockhand

See [DEPLOY.md](DEPLOY.md). Stack `mmex-web`, port **9090**, data `/data/mmex-web`.

Optional Paperless (inbox tag `Nouveau-Relevé`): set `PAPERLESS_URL` and `PAPERLESS_TOKEN` on the Dockhand stack. Do not use Compose `${VAR}` interpolation (Dockhand leading-space trap).

### Phone / WebApp 9080

Use **Saisie rapide** (FAB on small screens). It writes `CHECKINGACCOUNT_V1`, not `MMEX_New_Transaction.db`.

To empty leftover PHP WebApp reminders: host `/data/webmmxapp` is mounted and `WEBAPP_DB_PATH` points at `MMEX_New_Transaction.db`. Use **Outils → Ancienne WebApp**. After a successful import you can stop the `webmmxapp` stack on **9080**. Do not point this container at the live desktop ledger.

## Layout

```
apps/api          FastAPI
apps/web          Vite + React
packages/mmex-domain   balances, transactions, scheduled, reports
vendor/database   upstream tables.sql
```
