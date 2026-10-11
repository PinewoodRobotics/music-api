"""What may make sound: the quiet-hours lock and the AirPlay override, layered over the Spotify player.

- Quiet hours (see quiet_hours.py): while locked, anything that would start playback is refused with 423.
- AirPlay: a session pauses Spotify (queue, track and position stay put) and Spotify transport is refused with 409
  until it ends. When it ends, Spotify resumes if it was playing when AirPlay took over (unless quiet hours locked).
"""
import sys
import threading
import time

from player import PlayerError
from spotify import SpotifyError

PLAYING = ("playing", "buffering")
QUIET_BLOCKED = {"play", "next", "previous", "jump", "transfer_play"}
AIRPLAY_BLOCKED = {"play", "pause", "next", "previous", "jump", "seek", "transfer", "transfer_play"}
HANDOFF = 20  # seconds after AirPlay ends during which a pending Spotify resume counts as playing


def log(msg):
    sys.stderr.write(f"guard: {msg}\n")


class Guard:
    def __init__(self, player, quiet, airplay=None, enforce=None, receiver=None, clock=time.time):
        self.player = player
        self.quiet = quiet
        self.airplay = airplay
        self.enforce = enforce or (lambda locked: None)
        self.receiver = receiver or (lambda action: False)
        self.clock = clock
        self.lock = threading.Lock()
        self.resume_after = False
        self.handoff_until = 0
        self._phase = None
        player.guard = self.check
        player.overlay = self.overlay
        if airplay:
            airplay.on_start = self.airplay_started
            airplay.on_end = self.airplay_ended
            airplay.on_change = self.changed

    def _airplay(self):
        return self.airplay.snapshot() if self.airplay else None

    def check(self, action):
        if action in QUIET_BLOCKED and self.quiet.locked():
            q = self.quiet.status()
            raise PlayerError(f"Quiet hours: the speakers are locked until {self.quiet.until_text()}", 423,
                              "quiet_hours", until=q["until"], until_ts=q["until_ts"])
        ap = self._airplay()
        if ap and action in AIRPLAY_BLOCKED:
            sender = ap.get("sender")
            raise PlayerError(f"AirPlay{' from ' + sender if sender else ''} is playing, so Spotify is paused "
                              "until it ends (POST /api/airplay/stop ends it)", 409, "airplay_active", sender=sender)

    def overlay(self, st):
        st = {**st, "quiet_hours": self.quiet.status(), "airplay": None}
        ap = self._airplay()
        if not ap:
            return st
        spotify = {k: st.get(k) for k in ("state", "track", "position_ms", "duration_ms", "context", "source", "credit")}
        out = {k: v for k, v in st.items() if k != "removed"}
        out.update(source="airplay", state=ap["state"], track=ap["track"], position_ms=ap["position_ms"],
                   position=round(ap["position_ms"] / 1000, 3), duration_ms=ap["duration_ms"], context=None,
                   credit=None, skip=None, actions=[], spotify=spotify,
                   airplay={"sender": ap["sender"], "state": ap["state"], "started_at": ap["started_at"],
                            "resume_spotify": self.resume_after})
        return out

    def spotify_playing(self):
        try:
            return self.player.spotify_status().get("state") in PLAYING
        except (PlayerError, SpotifyError):
            return False

    def audio_playing(self):
        if self.clock() < self.handoff_until:
            return True
        ap = self._airplay()
        return bool(ap and ap["state"] == "playing") or self.spotify_playing()

    # ---------- AirPlay session lifecycle ----------

    def airplay_started(self):
        if self.quiet.locked():
            log("AirPlay session during locked quiet hours; stopping the receiver")
            self.enforce(True)
            self.airplay.end_session()
            return
        was = self.spotify_playing()
        with self.lock:
            self.resume_after = was
        if was:
            try:
                self.player.pause(force=True)
            except (PlayerError, SpotifyError) as e:
                log(f"couldn't pause Spotify for AirPlay: {e}")

    def airplay_ended(self):
        with self.lock:
            resume, self.resume_after = self.resume_after, False
        if resume and not self.quiet.locked():
            self.handoff_until = self.clock() + HANDOFF
            try:
                self.player.play({}, force=True)
            except (PlayerError, SpotifyError) as e:
                log(f"couldn't resume Spotify after AirPlay: {e}")

    def stop_airplay(self):
        if not self._airplay():
            raise PlayerError("no AirPlay session", 409, "airplay_inactive")
        if not self.receiver("restart"):
            raise PlayerError("couldn't restart the AirPlay receiver (is airplay.service installed?)", 503)
        self.airplay.end_session()
        return self.player.status(fresh=True)

    def changed(self):
        self.player._emit_status()

    # ---------- quiet hours ----------

    def tick(self):
        change = self.quiet.observe(self.audio_playing())
        locked = self.quiet.locked()
        if change == "locked":
            log("quiet hours: idle long enough, locking")
            self.enforce(True)
            if self.airplay:
                self.airplay.end_session()
        elif change == "unlocked":
            log("quiet hours: over, unlocking")
            self.enforce(False)
        if (locked or self._airplay()) and self.clock() >= self.handoff_until and self.spotify_playing():
            try:
                self.player.pause(force=True)
            except (PlayerError, SpotifyError) as e:
                log(f"couldn't pause Spotify: {e}")
        phase = self.quiet.status()["phase"]
        if change or phase != self._phase:
            self._phase = phase
            self.changed()

    def loop(self, interval=5):
        self.enforce(self.quiet.locked())
        while True:
            try:
                self.tick()
            except Exception as e:  # noqa: BLE001 - enforcement must keep running
                log(f"tick: {e!r}")
            time.sleep(interval)
