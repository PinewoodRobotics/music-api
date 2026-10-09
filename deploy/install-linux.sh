#!/bin/sh
# One-shot setup for a headless Debian / Raspberry Pi OS box (Pi 3/4/5/Zero 2 W, or x86_64).
# Run as your normal user from the repo checkout:  sh deploy/install-linux.sh
set -eu
REPO=$(cd "$(dirname "$0")/.." && pwd)
APP="$HOME/.local/share/music-api-v2"
CONF="$HOME/.config/music-api"

if [ "$(uname -m)" = armv6l ]; then
  echo "ARMv6 (Pi Zero W / Pi 1): Soloist won't run here. Installing the API only (connect backend)." >&2
  NO_SOLOIST=1
fi

sudo apt-get update
sudo apt-get install -y python3 curl pipewire pipewire-pulse wireplumber pulseaudio-utils
# user services (PipeWire, Soloist, the API) keep running with nobody logged in
sudo loginctl enable-linger "$USER"

mkdir -p "$APP" "$CONF" "$HOME/.config/systemd/user"
cp -R "$REPO"/server.py "$REPO"/player.py "$REPO"/soloist.py "$REPO"/spotify.py "$REPO"/extras.py \
      "$REPO"/index.html "$REPO"/deploy "$APP"/
chmod +x "$APP"/deploy/*.sh
if [ ! -f "$CONF/env" ]; then
  cp "$REPO/deploy/env.example" "$CONF/env"
  TOKEN=$(python3 -c 'import secrets;print(secrets.token_urlsafe(32))')
  sed -i "s|^MUSIC_API_TOKEN=.*|MUSIC_API_TOKEN=$TOKEN|" "$CONF/env"
fi
chmod 600 "$CONF/env"

cp "$REPO"/deploy/systemd/music-api.service "$HOME/.config/systemd/user/"
if [ -z "${NO_SOLOIST:-}" ]; then
  cp "$REPO"/deploy/systemd/soloist*.service "$REPO"/deploy/systemd/soloist-update.timer "$HOME/.config/systemd/user/"
  "$APP/deploy/update-soloist.sh"
fi
systemctl --user daemon-reload
systemctl --user enable --now pipewire pipewire-pulse wireplumber || true
if [ -z "${NO_SOLOIST:-}" ]; then
  systemctl --user enable soloist.service soloist-update.timer
  systemctl --user start soloist-update.timer
fi
systemctl --user enable music-api.service

cat <<MSG

Installed. Next:
  1. Fill in $CONF/env (SOLOIST_API_KEY, DEVICE_NAME, SPOTIFY_CLIENT_ID).
  2. systemctl --user start soloist music-api
  3. In the Spotify app (same Wi-Fi), pick "\$DEVICE_NAME" once to pair Soloist.
  4. Log in to the Web API: python3 $APP/server.py auth   (or open http://<this-host>:8765/auth/login?token=...)
Your API token is in $CONF/env (MUSIC_API_TOKEN).
MSG
