# Agent notes

This laptop talks to Dockhand on the home LAN. GitHub cannot reach `omv.home`.

After **every** code change that should go live:

1. `git commit` on `main`
2. `git push origin main`
3. `scripts/dockhand-webhook.sh`

Do not skip step 3. The webhook secret lives in `.env.local` (gitignored), never in committed files.

Stack: `mmex-web` at `http://omv.home:9090/`
Data: `/data/mmex-web` on the NAS
Host port is hardcoded `9090:8080` in `compose.yaml` (Dockhand leading-space env trap).

Never point the container at the live desktop `data.mmb` until the writer lock and backups are verified on a **copy**.

Shared lock protocol with `bank-reconciliation-app`: `data.mmb.lock` (`mmex-lock-v1`). Do not write both apps at once.

PR 16: quick-add writes the real ledger. Do not retire 9080 until sidecar ingest is done on a copy. Do not point at live `Moneymanager/data.mmb`.
