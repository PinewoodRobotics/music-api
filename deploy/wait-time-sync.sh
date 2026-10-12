#!/bin/sh
# The Pi has no RTC: after a power cut it boots with the clock from shutdown, and Soloist's login
# and the quiet-hours window both break until NTP corrects it. Waits up to 75s (under systemd's
# default 90s start timeout), then carries on. With --check, exits 1 instead of waiting.
synced() { [ "$(timedatectl show -p NTPSynchronized --value 2>/dev/null)" = yes ]; }
if [ "${1:-}" = --check ]; then synced; exit; fi
i=0
while ! synced && [ $i -lt 75 ]; do sleep 1; i=$((i + 1)); done
exit 0
