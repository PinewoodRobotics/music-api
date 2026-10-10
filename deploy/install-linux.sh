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
sudo apt-get install -y python3 curl pipewire pipewire-pulse wireplumber pulseaudio-utils python3-pil fonts-inter
# user services (PipeWire, Soloist, the API) keep running with nobody logged in
sudo loginctl enable-linger "$USER"

mkdir -p "$APP" "$CONF" "$HOME/.config/systemd/user"
cp -R "$REPO"/*.py "$REPO"/*.html "$REPO"/*.md "$REPO"/*.txt "$REPO"/deploy "$REPO"/display "$APP"/
chmod +x "$APP"/deploy/*.sh
if [ ! -f "$CONF/env" ]; then
  cp "$REPO/deploy/env.example" "$CONF/env"
  [ -n "${NO_SOLOIST:-}" ] && sed -i "s|^MUSIC_API_BACKEND=.*|MUSIC_API_BACKEND=connect|" "$CONF/env"
fi
chmod 600 "$CONF/env"

cp "$REPO"/deploy/systemd/music-api.service "$REPO"/deploy/systemd/music-display.service "$HOME/.config/systemd/user/"
# HDMI display: free tty1 from getty, let the video group hide its cursor, silence kernel messages on the console
sudo systemctl disable --now getty@tty1.service || true
echo 'KERNEL=="tty1", GROUP="video", MODE="0660"' | sudo tee /etc/udev/rules.d/90-music-display.rules >/dev/null
echo 'kernel.printk = 1 1 1 1' | sudo tee /etc/sysctl.d/90-music-display.conf >/dev/null
sudo sysctl -q -p /etc/sysctl.d/90-music-display.conf || true
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
systemctl --user enable music-display.service

cat <<MSG

Installed. Next:
  1. Fill in $CONF/env (SOLOIST_API_KEY, DEVICE_NAME, SPOTIFY_CLIENT_ID).
  2. systemctl --user start soloist music-api
  3. In the Spotify app (same Wi-Fi), pick "\$DEVICE_NAME" once to pair Soloist.
  4. HDMI display: create a token (POST /api/tokens {"name": "pi display"}) into $CONF/display-token (mode 600), then
     systemctl --user start music-display
  5. Log in to the Web API: python3 $APP/server.py auth   (or open http://<this-host>:8765/auth/login?token=...)
Your first API token is written to ~/.local/share/music-api/token when the API first starts
(cat it once, then manage tokens with /api/tokens; you can delete that file afterwards).
MSG
