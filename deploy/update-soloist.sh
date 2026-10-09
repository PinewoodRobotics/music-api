#!/bin/sh
# Download the current Soloist build for this machine's architecture and restart it if it changed.
# Soloist builds expire 90 days after they're built (exit code 10), so this runs daily from a timer.
# Downloads straight from Spotify's CDN; Spotify asks that the binary not be redistributed.
set -eu
BIN="${SOLOIST_BIN:-$HOME/.local/bin/soloist}"
case "$(uname -m)" in
  aarch64|arm64) ARCH=arm64 ;;
  armv7l|armv8l) ARCH=arm32 ;;
  x86_64)        ARCH=x86_64 ;;
  armv6l)
    echo "This is an ARMv6 board (Pi Zero / Zero W / Pi 1). Spotify ships Soloist for armv7, arm64 and x86_64 only." >&2
    echo "Use the connect backend with a librespot build instead; see README." >&2
    exit 1 ;;
  *) echo "unsupported architecture: $(uname -m)" >&2; exit 1 ;;
esac
URL="https://soloist-builds.spotifycdn.com/soloist_release_${ARCH}.tar.gz"
TMP=$(mktemp -d); trap 'rm -rf "$TMP"' EXIT
curl -fsSL "$URL" -o "$TMP/soloist.tar.gz"
tar -xzf "$TMP/soloist.tar.gz" -C "$TMP"
NEW=$(find "$TMP" -type f -name soloist | head -n1)
[ -n "$NEW" ] || { echo "no soloist binary in $URL" >&2; exit 1; }
mkdir -p "$(dirname "$BIN")"
if [ -f "$BIN" ] && cmp -s "$NEW" "$BIN"; then
  echo "Soloist up to date: $("$BIN" --version 2>/dev/null || echo unknown)"
  exit 0
fi
install -m 755 "$NEW" "$BIN.new" && mv "$BIN.new" "$BIN"
echo "Installed Soloist: $("$BIN" --version 2>/dev/null || echo unknown)"
systemctl --user try-restart soloist.service 2>/dev/null || true
