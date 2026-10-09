#!/bin/sh
# Build the web app here and push the server + app to the Pi (which has no Node), then restart the API.
#   sh deploy/deploy-pi.sh [user@host]
set -eu
HOST="${1:-${MUSIC_API_HOST:-ubuntu@10.1.10.65}}"
REPO=$(cd "$(dirname "$0")/.." && pwd)
APP=.local/share/music-api-v2

(cd "$REPO/web" && npm ci --silent && npm run build --silent)
rsync -a "$REPO"/*.py "$REPO"/*.html "$REPO"/*.md "$REPO"/*.txt "$HOST:$APP/"
ssh "$HOST" "mkdir -p $APP/web/dist"
rsync -a --delete "$REPO/web/dist/" "$HOST:$APP/web/dist/"
rsync -a "$REPO/deploy/" "$HOST:$APP/deploy/"
ssh "$HOST" "cp $APP/deploy/systemd/music-api.service ~/.config/systemd/user/ && systemctl --user daemon-reload && systemctl --user restart music-api && sleep 2 && systemctl --user is-active music-api"
