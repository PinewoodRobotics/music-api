#!/bin/sh
# Classic AirPlay receiver from the distro shairport-sync package (Ubuntu 24.04: 3.3.8, Debian 13: 4.3.7). Both are
# built with PulseAudio output, the metadata pipe, D-Bus/MPRIS and MQTT, which is all the server needs. Also removes
# the AirPlay 2 build (NQPTP + shairport-sync from source) an earlier version of this script installed.
# Idempotent; run from install-linux.sh or by hand:  sh deploy/install-airplay.sh
set -eu

sudo apt-get install -y --no-install-recommends shairport-sync avahi-daemon dbus-user-session

# The package enables a system service that would advertise a second receiver; ours runs as airplay.service.
sudo systemctl disable --now shairport-sync.service 2>/dev/null || true

sudo systemctl disable --now nqptp.service 2>/dev/null || true
sudo rm -f /usr/local/bin/nqptp /usr/local/bin/shairport-sync /etc/systemd/system/nqptp.service \
  /usr/lib/systemd/system/nqptp.service /lib/systemd/system/nqptp.service /usr/local/lib/systemd/system/nqptp.service
sudo systemctl daemon-reload
rm -rf "$HOME/.cache/music-api-src"
hash -r

for feature in pa metadata dbus; do
  if ! shairport-sync -V | grep -q -- "-$feature"; then
    echo "shairport-sync was built without $feature support: $(shairport-sync -V)" >&2
    exit 1
  fi
done
sudo systemctl enable --now avahi-daemon
shairport-sync -V
