#!/bin/sh
# Starts the AirPlay 2 receiver with the name from ~/.config/music-api/env (AIRPLAY_NAME).
set -eu
exec "${SHAIRPORT_BIN:-/usr/local/bin/shairport-sync}" -c "$(dirname "$0")/shairport-sync.conf" \
  -a "${AIRPLAY_NAME:-Pinewood Music}"
