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
rsync -a "$REPO/display/" "$HOST:$APP/display/"
ssh "$HOST" "cp $APP/deploy/systemd/soloist.service $APP/deploy/systemd/music-api.service $APP/deploy/systemd/airplay.service $APP/deploy/systemd/quiet-hours.service $APP/deploy/systemd/quiet-hours.timer ~/.config/systemd/user/ && systemctl --user daemon-reload && systemctl --user enable --now quiet-hours.timer && systemctl --user restart music-api && sleep 2 && systemctl --user is-active music-api; if command -v shairport-sync >/dev/null && ! command -v nqptp >/dev/null; then systemctl --user enable --now airplay.service; else echo 'AirPlay receiver not installed (or still the old AirPlay 2 build): run sh $APP/deploy/install-airplay.sh on the Pi once'; fi; if systemctl --user is-enabled -q music-display 2>/dev/null; then cp $APP/deploy/systemd/music-display.service ~/.config/systemd/user/ && systemctl --user daemon-reload && systemctl --user restart music-display; fi"
