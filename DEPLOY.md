# Deploy from Git with Dockhand

Local change → `git push` → Dockhand pulls this repo, **rebuilds** `mmex-web:latest`, and recreates the container. The `.mmb`, lock file, attachments, and backups stay on the NAS.

The stack is **`mmex-web`**. Host port is **9090** (hardcoded). Do not introduce `${MMEX_WEB_PORT}`: Dockhand has injected a leading space and Docker rejected `" 9080"` on the WebApp stack.

```
laptop  --push-->  GitHub  --LAN webhook or poll-->  Dockhand on OMV  --build-->  mmex-web:9090
```

| | Stack |
|---|---|
| Stack / container | `mmex-web` |
| URL | `http://omv.home:9090/` |
| Files | `/data/mmex-web` |

## 1. Copy a ledger (do not move the live desktop file)

On the OMV host:

```bash
sudo mkdir -p /data/mmex-web/attachments /data/mmex-web/backups

# copy, do not move
sudo cp -a /path/to/copy-of-data.mmb /data/mmex-web/data.mmb

sudo chown -R 1000:1000 /data/mmex-web
```

Keep desktop MMEX closed (or read-only) while this stack holds the write lock.
Yield the lock in the UI before a bank-reconciliation-app commit; take it back afterwards. Same file: `/data/mmex-web/data.mmb.lock`.

Réconciliation inbox: add Dockhand env `PAPERLESS_URL` and `PAPERLESS_TOKEN` (tag `Nouveau-Relevé` by default). Matching/commit of PDF lines is not in this image yet; the menu lists pending statements mapped to accounts.

Phone capture is **Saisie rapide** on 9090. After ingesting leftover `MMEX_New_Transaction.db` from Outils, stop Dockhand stack `webmmxapp` (9080). Optional: `WEBAPP_DB_PATH=/data/webmmxapp/MMEX_New_Transaction.db` if you bind-mount that volume read-only.

## 2. Add the Git repository

1. Dockhand → **Git** → **Repositories** → **Add Repository**
2. URL of this repo
3. Branch: **`main`**
4. Auth: none if public; otherwise a GitHub PAT or deploy key

## 3. Create the Git stack

1. **Stacks** → **From Git**
2. Stack name: `mmex-web`
3. Branch: `main`
4. Compose path: **`compose.yaml`**
5. Enable **Build on deploy**
6. Enable **Force redeploy** / **Re-pull** if available
7. Deploy and open `http://omv.home:9090/`

## 4. Updates

GitHub cannot call `http://omv.home:9011/` from the internet. After `git push`:

```bash
scripts/dockhand-webhook.sh
```

(credentials in `.env.local`). Alternatively enable stack auto-update poll (`*/5 * * * *`) or Redeploy manually.

## 5. Local laptop

```bash
mkdir -p data
# optional: cp /path/to/copy.mmb data/data.mmb
docker compose -f compose.yaml -f compose.local.yaml up --build
# http://localhost:9090/
```
