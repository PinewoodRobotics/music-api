#!/bin/sh
# AirPlay 2 receiver: NQPTP (PTP timing daemon, system service on ports 319/320) and shairport-sync built with
# AirPlay 2, PulseAudio output (PipeWire's pulse server) and the metadata pipe. Ubuntu's shairport-sync package is
# classic AirPlay only through 24.04 (3.3.8), so this builds pinned releases from source: ~15 min on a Pi 3.
# Idempotent; run from install-linux.sh or by hand:  sh deploy/install-airplay.sh
set -eu
NQPTP_TAG=1.2.4
SPS_TAG=4.3.7
SRC="$HOME/.cache/music-api-src"

if shairport-sync -V 2>/dev/null | grep -q "^$SPS_TAG.*AirPlay2" && command -v nqptp >/dev/null; then
  echo "shairport-sync $SPS_TAG with AirPlay 2 is already installed"
  sudo systemctl enable --now avahi-daemon nqptp
  exit 0
fi

sudo apt-get install -y --no-install-recommends build-essential git autoconf automake libtool pkg-config \
  libpopt-dev libconfig-dev libasound2-dev libpulse-dev avahi-daemon libavahi-client-dev libssl-dev libsoxr-dev \
  libplist-dev libsodium-dev uuid-dev libgcrypt-dev xxd libplist-utils libavutil-dev libavcodec-dev libavformat-dev
# nqptp's --with-systemd-startup needs systemd.pc, which moved to systemd-dev in Ubuntu 24.10 / Debian 13
if apt-cache show systemd-dev >/dev/null 2>&1; then
  sudo apt-get install -y --no-install-recommends systemd-dev
fi

# The distro package runs a classic-only system service that would advertise a second receiver.
sudo systemctl disable --now shairport-sync.service 2>/dev/null || true
if dpkg -s shairport-sync >/dev/null 2>&1; then
  sudo apt-get remove -y shairport-sync
fi

fetch() {
  [ -d "$SRC/$1" ] || git clone -q "https://github.com/mikebrady/$1.git" "$SRC/$1"
  git -C "$SRC/$1" fetch -q --tags
  git -C "$SRC/$1" checkout -q "$2"
}
mkdir -p "$SRC"

fetch nqptp "$NQPTP_TAG"
(cd "$SRC/nqptp" && autoreconf -fi && ./configure --with-systemd-startup && make -j"$(nproc)" && sudo make install)
sudo systemctl daemon-reload
sudo systemctl enable --now nqptp

fetch shairport-sync "$SPS_TAG"
(cd "$SRC/shairport-sync" && autoreconf -fi &&
  ./configure --sysconfdir=/etc --with-pa --with-soxr --with-avahi --with-ssl=openssl --with-airplay-2 --with-metadata &&
  make -j"$(nproc)" && sudo make install)
sudo systemctl enable --now avahi-daemon

shairport-sync -V
