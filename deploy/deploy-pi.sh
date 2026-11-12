#!/bin/sh
# Build the web app here and push the server + app to the Pi (which has no Node), then restart the API.
#   sh deploy/deploy-pi.sh [user@host]
set -eu
HOST="${1:-${MUSIC_API_HOST:-ubuntu@music-api.local}}"
REPO=$(cd "$(dirname "$0")/.." && pwd)
APP=.local/share/music-api-v2

(cd "$REPO/web" && npm ci --silent && npm run build --silent)
rsync -a "$REPO"/*.py "$REPO"/*.html "$REPO"/*.md "$REPO"/*.txt "$HOST:$APP/"
# what's deployed, for the admin page's System and Updates tabs (updater.py writes the same from GitHub builds)
python3 -c 'import json, subprocess, sys, time
git = lambda *a: subprocess.check_output(["git", "-C", sys.argv[1], *a], text=True).strip()
print(json.dumps({"commit": git("rev-parse", "HEAD"), "subject": git("log", "-1", "--format=%s"),
                  "date": int(git("log", "-1", "--format=%ct")), "built_at": int(time.time()),
                  "dirty": bool(git("status", "--porcelain", "--untracked-files=no")), "via": "deploy-pi.sh"}))' "$REPO" \
  | ssh "$HOST" "cat > $APP/BUILD.json"
# sound effects: pw-play plays them, ffmpeg normalizes mp3/ogg/flac uploads (wav works without it)
ssh "$HOST" 'command -v pw-play >/dev/null && command -v ffmpeg >/dev/null || sudo -n apt-get install -y --no-install-recommends pipewire-bin ffmpeg || echo "WARNING: could not install pw-play/ffmpeg; sound effects need them (sh deploy/install-linux.sh)" >&2'
ssh "$HOST" "mkdir -p $APP/web/dist"
rsync -a --delete "$REPO/web/dist/" "$HOST:$APP/web/dist/"
rsync -a "$REPO/deploy/" "$HOST:$APP/deploy/"
rsync -a "$REPO/display/" "$HOST:$APP/display/"
ssh "$HOST" "cp $APP/deploy/systemd/soloist.service $APP/deploy/systemd/music-api.service $APP/deploy/systemd/airplay.service $APP/deploy/systemd/quiet-hours.service $APP/deploy/systemd/quiet-hours.timer ~/.config/systemd/user/ && systemctl --user daemon-reload && systemctl --user enable --now quiet-hours.timer && systemctl --user restart music-api && sleep 2 && systemctl --user is-active music-api; if command -v shairport-sync >/dev/null && ! command -v nqptp >/dev/null; then systemctl --user enable --now airplay.service; else echo 'AirPlay receiver not installed (or still the old AirPlay 2 build): run sh $APP/deploy/install-airplay.sh on the Pi once'; fi; if systemctl --user is-enabled -q music-display 2>/dev/null; then cp $APP/deploy/systemd/music-display.service ~/.config/systemd/user/ && systemctl --user daemon-reload && systemctl --user restart music-display; fi"
