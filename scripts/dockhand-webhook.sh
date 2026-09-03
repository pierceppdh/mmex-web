#!/bin/sh
# Trigger Dockhand to pull Git, rebuild, and redeploy mmex-web.
# GitHub cannot reach omv.home; this must run on the LAN/VPN after git push.
set -e

ROOT="$(CDPATH= cd -- "$(dirname "$0")/.." && pwd)"
if [ -f "$ROOT/.env.local" ]; then
    # shellcheck disable=SC1091
    set -a
    . "$ROOT/.env.local"
    set +a
fi

URL="${DOCKHAND_WEBHOOK_URL:?DOCKHAND_WEBHOOK_URL missing (see .env.local)}"
SECRET="${DOCKHAND_WEBHOOK_SECRET:?DOCKHAND_WEBHOOK_SECRET missing (see .env.local)}"

echo "Triggering Dockhand webhook..."
resp="$(curl -sS --fail-with-body --connect-timeout 10 --max-time 180 \
    -G "$URL" --data-urlencode "secret=$SECRET")" || {
    echo "Dockhand webhook request failed." >&2
    echo "$resp" >&2
    exit 1
}

echo "$resp"
if echo "$resp" | grep -q '"success":false'; then
    echo "Dockhand reported a deploy error." >&2
    exit 1
fi
echo "Dockhand deploy triggered."
