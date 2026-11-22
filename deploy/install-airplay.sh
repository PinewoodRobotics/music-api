#!/bin/sh
# AirPlay 2 receiver: NQPTP (PTP timing daemon, system service on ports 319/320) and shairport-sync built with AirPlay 2,
# PulseAudio output (PipeWire's pulse server), the metadata pipe and D-Bus. Distro packages are classic AirPlay only, and
# remote control of AirPlay 2 senders needs 5.6 or later, so this builds pinned releases from source: ~15 min on a Pi 3.
# The running receiver keeps playing until the build has succeeded.
# Idempotent; run from install-linux.sh or by hand:  sh deploy/install-airplay.sh
set -eu
NQPTP_TAG=1.2.9
SPS_TAG=5.6.2
SRC="$HOME/.cache/music-api-src"

if shairport-sync -V 2>/dev/null | grep -q "^$SPS_TAG.*AirPlay2" && nqptp -V 2>/dev/null | grep -q "$NQPTP_TAG"; then
  echo "shairport-sync $SPS_TAG with AirPlay 2 is already installed"
  sudo systemctl enable --now avahi-daemon nqptp
  exit 0
fi

sudo apt-get install -y --no-install-recommends build-essential git autoconf automake libtool pkg-config \
  libpopt-dev libconfig-dev libasound2-dev libpulse-dev avahi-daemon libavahi-client-dev libssl-dev libsoxr-dev \
  libplist-dev libsodium-dev uuid-dev libgcrypt-dev xxd libplist-utils libavutil-dev libavcodec-dev libavformat-dev \
  libglib2.0-dev dbus-user-session
# nqptp's --with-systemd-startup needs systemd.pc, which moved to systemd-dev in Ubuntu 24.10 / Debian 13
if apt-cache show systemd-dev >/dev/null 2>&1; then
  sudo apt-get install -y --no-install-recommends systemd-dev
fi

fetch() {
  [ -d "$SRC/$1" ] || git clone -q "https://github.com/mikebrady/$1.git" "$SRC/$1"
  git -C "$SRC/$1" fetch -q --tags
  git -C "$SRC/$1" checkout -q "$2"
}
mkdir -p "$SRC"

# -j2: a full -j4 can run a 1 GB Pi 3 out of memory while it's also playing music.
fetch nqptp "$NQPTP_TAG"
(cd "$SRC/nqptp" && autoreconf -fi && ./configure --with-systemd-startup && make -j2)

fetch shairport-sync "$SPS_TAG"
(cd "$SRC/shairport-sync" && autoreconf -fi &&
  ./configure --sysconfdir=/etc --with-pulseaudio --with-soxr --with-avahi --with-ssl=openssl --with-airplay-2 \
    --with-metadata --with-dbus-interface &&
  make clean && make -j2)

# The distro package runs a classic-only system service that would advertise a second receiver.
sudo systemctl disable --now shairport-sync.service 2>/dev/null || true
if dpkg -s shairport-sync >/dev/null 2>&1; then
  sudo apt-get remove -y shairport-sync
fi

# NQPTP and shairport-sync share a versioned memory interface (smi11), so NQPTP has to be replaced and restarted first.
(cd "$SRC/nqptp" && sudo make install)
sudo systemctl daemon-reload
sudo systemctl enable nqptp
sudo systemctl restart nqptp

(cd "$SRC/shairport-sync" && sudo make install)
hash -r

for feature in AirPlay2 PulseAudio metadata dbus; do
  if ! shairport-sync -V | grep -q -- "-$feature"; then
    echo "shairport-sync was built without $feature support: $(shairport-sync -V)" >&2
    exit 1
  fi
done
sudo systemctl enable --now avahi-daemon
# try-restart: quiet hours may have stopped it, and it must stay stopped if so.
systemctl --user try-restart airplay.service 2>/dev/null || true
shairport-sync -V
nqptp -V
