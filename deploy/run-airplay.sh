#!/bin/sh
# Starts the AirPlay receiver with the name from ~/.config/music-api/env (AIRPLAY_NAME).
set -eu
exec "${SHAIRPORT_BIN:-$(command -v shairport-sync)}" -c "$(dirname "$0")/shairport-sync.conf" \
  -a "${AIRPLAY_NAME:-PEARL Speakers}"
