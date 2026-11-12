#!/bin/sh
# Starts Soloist from the settings in ~/.config/music-api/env (see env.example).
set -eu
: "${SOLOIST_API_KEY:?set SOLOIST_API_KEY in ~/.config/music-api/env}"
set -- --device-name "${DEVICE_NAME:-PEARL Speakers}" --api-key "$SOLOIST_API_KEY" --ws "${SOLOIST_WS:-127.0.0.1:0}"
[ -n "${SOLOIST_PIPEWIRE_DEVICE:-}" ] && set -- "$@" --pipewire-device "$SOLOIST_PIPEWIRE_DEVICE"
[ -n "${SOLOIST_INITIAL_VOLUME:-}" ] && set -- "$@" --initial-volume "$SOLOIST_INITIAL_VOLUME"
[ -n "${SOLOIST_CACHE_MB:-}" ] && set -- "$@" --cache-size "$SOLOIST_CACHE_MB"
exec "${SOLOIST_BIN:-$HOME/.local/bin/soloist}" "$@"
