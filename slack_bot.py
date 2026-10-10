"""Slack bot: a live "Now playing" feed in #music, the /music slash command, button interactivity and link unfurls.
Stdlib only. Everything that talks to Slack runs on its own threads; the player never waits for it.

The HTTP routes (/slack/commands, /slack/interactions, /slack/events) are verified with the signing secret
and bypass token/session auth. The feed subscribes to Player events like the SSE endpoint does.
"""
import copy
import hashlib
import hmac
import json
import os
import queue as queuelib
import re
import sys
import threading
import time
import urllib.error
import urllib.parse
import urllib.request

from accounts import AccountError
from player import PlayerError
from spotify import SpotifyError, item, page, to_uri

API = "https://slack.com/api"
DEFAULT_TEAM = "T09DBUR4YER"
DEFAULT_CHANNEL = "C0C80T1DNBF"
DEFAULT_REMOTE = "https://music.pinewoodrobotics.org/"
LINK_RX = re.compile(r"https?://(?:open\.spotify\.com|music\.apple\.com)/\S+|spotify:(?:track|album|playlist):\w{22}")
CARD_LINKS = 3
QUEUE_CAP = 50
PLAY_CAP = 100
MAX_AGE = 300
UPDATE_EVERY = 5
SETTLE = 3  # seconds of silence before the card collapses to "Played"
REUSE = 10  # a track skipped within this many seconds has its card turned into the next one
USER_TTL = 3600
FATAL = {"missing_scope", "not_authed", "invalid_auth", "token_revoked", "account_inactive", "not_in_channel",
         "channel_not_found", "is_archived"}
PLAYING = ("playing", "buffering")
HELP = ("*Robotics Music* (`/music`) controls the lab speakers\n"
        "`/music <song, artist or album>` search and add to the queue\n"
        "`/music now`  what's playing   `/music queue`  what's next\n"
        "`/music play`  `/music pause`  `/music skip`\n"
        "Paste a Spotify or Apple Music song, album or playlist link after `/music` to queue, play or import it.")


def log(msg):
    print("slack: " + msg, file=sys.stderr, flush=True)


def esc(s):
    return (s or "").replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def who(user):
    return esc(user.get("name"))


def spotify_url(uri):
    parts = (uri or "").split(":")
    return f"https://open.spotify.com/{parts[1]}/{parts[2]}" if len(parts) == 3 and parts[0] == "spotify" else None


def duration(ms):
    s = int((ms or 0) / 1000)
    return f"{s // 60}:{s % 60:02d}"


def artists_of(t):
    return ", ".join(a["name"] for a in t.get("artists") or [] if a.get("name")) or (t.get("show") or {}).get("name") or ""


def title_link(t):
    url = spotify_url(t.get("uri"))
    name = esc(t.get("name") or "Unknown")
    return f"<{url}|{name}>" if url else name


def subtitle(t):
    return " · ".join(x for x in (esc(artists_of(t)), esc((t.get("album") or {}).get("name"))) if x)


def verify_signature(secret, timestamp, signature, body, now=None):
    try:
        ts = int(timestamp)
    except (TypeError, ValueError):
        return False
    if not secret or not signature or abs((now if now is not None else time.time()) - ts) > MAX_AGE:
        return False
    mac = hmac.new(secret.encode(), b"v0:" + str(ts).encode() + b":" + body, hashlib.sha256).hexdigest()
    return hmac.compare_digest(("v0=" + mac).encode(), signature.encode("utf-8", "replace"))


def parse_command(text):
    """'/music' text -> (verb, argument)."""
    text = (text or "").strip()
    head, _, rest = text.partition(" ")
    verb = head.lower()
    if not text or verb in ("help", "?"):
        return "help", ""
    if verb in ("now", "queue", "pause", "skip", "play") and not (verb in ("now", "queue", "pause", "skip") and rest):
        return verb, rest.strip()
    if verb == "next" and not rest:
        return "skip", ""
    if verb == "search" and rest.strip():
        return "search", rest.strip()
    return "search", text


# ---------- Block Kit ----------

def button(text, action_id, value=None, style=None, url=None):
    b = {"type": "button", "text": {"type": "plain_text", "text": text}, "action_id": action_id}
    if value is not None:
        b["value"] = value
    if style:
        b["style"] = style
    if url:
        b["url"] = url
    return b


def card(t, accessory=True, by=None):
    text = f"*{title_link(t)}*\n{subtitle(t)}" + (f"\n{who(by)}" if by and by.get("name") else "")
    block = {"type": "section", "text": {"type": "mrkdwn", "text": text}}
    if accessory and t.get("artwork"):
        block["accessory"] = {"type": "image", "image_url": t["artwork"], "alt_text": t.get("name") or "cover"}
    return block


def context(*parts):
    return {"type": "context", "elements": [{"type": "mrkdwn", "text": p} for p in parts]}



def upcoming_blocks(upcoming, n=3):
    rows = []
    for e in (upcoming or [])[:n]:
        it = e.get("item") or e
        if not it.get("name"):
            continue
        text = f"{esc(it['name'])} - {esc(artists_of(it))}" if artists_of(it) else esc(it["name"])
        art = [{"type": "image", "image_url": it["artwork"], "alt_text": it["name"]}] if it.get("artwork") else []
        rows.append({"type": "context", "elements": art + [{"type": "mrkdwn", "text": text}]})
    return [context("*Up next*")] + rows if rows else []



def now_playing_blocks(t, playing, credit=None, upcoming=None, remote=DEFAULT_REMOTE, block_id="feed"):
    blocks = [card(t, by=(credit or {}).get("by"))] + upcoming_blocks(upcoming)
    els = [button("Pause" if playing else "Play", "playpause"), button("Skip", "skip"),
           button("More Controls", "open_remote", url=remote)]
    blocks.append({"type": "actions", "block_id": block_id, "elements": els})
    return blocks


def now_playing_text(t):
    return f"Now playing: {t.get('name')} - {artists_of(t)}"


def played_blocks(t, credit=None, skipped_by=None):
    by = f" · {who(credit['by'])}" if credit and (credit.get("by") or {}).get("name") else ""
    skip = f" · skipped by {who(skipped_by)}" if skipped_by and skipped_by.get("name") else ""
    text = f"Played · *{title_link(t)}* - {esc(artists_of(t))}{by}{skip}"
    els = [{"type": "image", "image_url": t["artwork"], "alt_text": t.get("name") or "cover"}] if t.get("artwork") else []
    return [{"type": "context", "elements": els + [{"type": "mrkdwn", "text": text}]}]


def track_row(t, block_id, label="Add to queue", action="queue_add"):
    sub = f"{subtitle(t)} · {duration(t.get('duration_ms'))}"
    row = {"type": "section", "text": {"type": "mrkdwn", "text": f"*{title_link(t)}*\n{sub}"}}
    if t.get("artwork"):
        row["accessory"] = {"type": "image", "image_url": t["artwork"], "alt_text": t.get("name") or "cover"}
    return [row, {"type": "actions", "block_id": block_id,
                  "elements": [button(label, action, t["uri"], "primary")]}]


def collection_row(c):
    kind = c.get("type")
    sub = esc(artists_of(c)) if kind == "album" else f"playlist · {esc(c.get('owner') or '')}".rstrip(" ·")
    if kind == "album":
        sub = f"album · {sub}"
    row = {"type": "section", "text": {"type": "mrkdwn", "text": f"*{title_link(c)}*\n{sub}"}}
    if c.get("artwork"):
        row["accessory"] = {"type": "image", "image_url": c["artwork"], "alt_text": c.get("name") or "cover"}
    return [row, {"type": "actions", "block_id": "p:" + c["uri"], "elements": [button("Play", "play_uri", c["uri"])]}]


def search_blocks(query, tracks, collections):
    blocks = [context(f"Results for “{esc(query)}”")]
    for t in tracks:
        blocks += track_row(t, "q:" + t["uri"])
    for c in collections:
        blocks += collection_row(c)
    if not tracks and not collections:
        blocks.append(context("Nothing found."))
    return blocks


def queue_blocks(upcoming):
    if not upcoming:
        return [context("The queue is empty.")]
    lines = []
    for i, e in enumerate(upcoming[:10], 1):
        it = e.get("item") or {}
        by = f"  _queued by {esc(e['added_by']['name'])}_" if (e.get("added_by") or {}).get("name") else ""
        lines.append(f"{i}. {title_link(it)} - {esc(artists_of(it))}{by}")
    return [{"type": "section", "text": {"type": "mrkdwn", "text": "*Up next*\n" + "\n".join(lines)}}]


def link_blocks(r):
    kind, apple = r.get("kind"), r.get("source") == "apple"
    name = esc(r.get("name") or "Untitled")
    head = f"*<{r['url']}|{name}>*" if r.get("url") else f"*{name}*"
    sec = {"type": "section", "text": {"type": "mrkdwn", "text": head + (f"\n{esc(r['subtitle'])}" if r.get("subtitle") else "")}}
    if r.get("artwork"):
        sec["accessory"] = {"type": "image", "image_url": r["artwork"], "alt_text": r.get("name") or "cover"}
    notes = []
    if kind == "track" and apple:
        notes.append("Matched from Apple Music" if r.get("spotify_uri") else "Not found on Spotify")
    elif kind != "track" and r.get("total"):
        n = f"{r['total']} songs"
        if r.get("matched") is not None:
            n += f" · {r['matched']} on Spotify"
        notes.append(n + (" (first batch only)" if r.get("truncated") else ""))
    uri = r.get("spotify_uri")
    btns = []
    if kind == "track" and uri:
        btns = [button("Add to queue", "queue_add", uri, "primary"), button("Play", "play_uri", uri)]
    elif kind == "album":
        btns = ([button("Play", "play_uri", uri, "primary"), button("Add to Library", "add_album", r["url"])] if uri
                else [button("Import as playlist", "import_playlist", r["url"])])
    elif kind == "playlist":
        btns = [button("Import as playlist", "import_playlist", r["url"], "primary")] + \
               ([button("Play", "play_uri", uri)] if uri and not apple else [])
    blocks = [sec] + ([context(*notes)] if notes else [])
    return blocks + ([{"type": "actions", "block_id": "link", "elements": btns}] if btns else [])


KIND_LABEL = {"track": "Song", "album": "Album", "playlist": "Playlist"}


def matched_uris(r):
    return [t["uri"] for t in r.get("tracks") or [] if t.get("uri")]


def reply_card(r, idx, poster):
    """The card the bot posts in the thread of a link shared in the music channel. Block IDs carry the card
    index so one reply can hold several cards: info<i>, rl<i> (buttons), out<i> (accumulated outcomes)."""
    kind, apple, uri = r.get("kind"), r.get("source") == "apple", r.get("spotify_uri")
    name = esc(r.get("name") or "Untitled")
    sec = {"type": "section", "text": {"type": "mrkdwn", "text": (f"*<{r['url']}|{name}>*" if r.get("url") else f"*{name}*")
                                       + (f"\n{esc(r['subtitle'])}" if r.get("subtitle") else "")}}
    if r.get("artwork"):
        sec["accessory"] = {"type": "image", "image_url": r["artwork"], "alt_text": r.get("name") or "cover"}
    label = KIND_LABEL.get(kind, "Link")
    if apple:
        label += " · Apple Music → matched on Spotify" if uri or matched_uris(r) else " · Apple Music, not found on Spotify"
    info = [label]
    if kind != "track" and r.get("total"):
        n = f"{r['total']} songs"
        if r.get("matched") is not None:
            n += f" · {r['matched']} on Spotify"
        info.append(n + (" (first batch only)" if r.get("truncated") else ""))
    if poster:
        info.append(f"shared by {esc(poster)}")
    queue_n = len(matched_uris(r))
    btns = []
    if kind == "track":
        if uri:
            btns = [button("▶ Play now", "rl_play", r["url"], "primary"), button("＋ Add to queue", "rl_queue", r["url"])]
    elif kind == "album":
        if uri:
            btns = [button("▶ Play now", "rl_play", r["url"], "primary")]
            btns += [button("＋ Queue album", "rl_queue", r["url"])] if queue_n else []
            btns.append(button("Add to Library", "rl_library", r["url"]))
        else:
            info.append("No Spotify match, so it can only be imported as a playlist")
            btns = [button("Import as playlist", "rl_import", r["url"])]
    elif kind == "playlist":
        if (uri and not apple) or (apple and queue_n):
            btns.append(button("▶ Play now", "rl_play", r["url"], "primary"))
        if queue_n:
            btns.append(button("＋ Queue songs", "rl_queue", r["url"]))
        btns.append(button("Import to Library", "rl_import", r["url"]))
    blocks = [sec, {"type": "context", "block_id": f"info{idx}",
                    "elements": [{"type": "mrkdwn", "text": " · ".join(info)}]}]
    if btns:
        blocks.append({"type": "actions", "block_id": f"rl{idx}", "elements": btns})
    return blocks


# ---------- the bot ----------

class SlackBot:
    def __init__(self, slack, player, api, credits, signing_secret, channel=DEFAULT_CHANNEL, team=DEFAULT_TEAM,
                 remote=DEFAULT_REMOTE, resolve=None, importer=None, state_path=None, activity=None, add_album=None,
                 playlist_importer=None):
        self.slack, self.player, self.api, self.credits = slack, player, api, credits
        self.token = slack.bot_token
        self.secret, self.channel, self.team, self.remote = signing_secret, channel, team, remote
        self.resolve = resolve or self.spotify_resolve
        self.importer = importer
        self.add_album = add_album
        self._playlist_importer = playlist_importer
        self.cards, self.card_lock = {}, threading.Lock()
        self.replied, self.bot_user = set(), None
        self.activity = activity
        self.users, self.users_lock = {}, threading.Lock()
        self.warned = set()
        self.pause_until = 0
        self.seen_events = {}
        self.st, self.upcoming = {}, []
        self.state_path = state_path
        self.cur = self.load_cur()
        self.cand = ((self.cur or {}).get("uri"), 0)

    def load_cur(self):
        """The feed message from before a restart, so it gets updated or collapsed instead of duplicated."""
        try:
            with open(self.state_path) as f:
                cur = json.load(f)
        except (TypeError, OSError, ValueError):
            return None
        if not cur or not cur.get("ts"):
            return None
        if cur.get("by") and not cur.get("credit"):
            cur["credit"] = {"by": cur["by"], "how": "queued"}
        return {**cur, "sig": None, "sent": 0}

    def save_cur(self):
        if not self.state_path:
            return
        cur = self.cur if self.cur and self.cur.get("ts") else None
        tmp = self.state_path + ".tmp"
        try:
            with open(tmp, "w") as f:
                json.dump(cur and {k: v for k, v in cur.items() if k != "sig"}, f)
            os.replace(tmp, self.state_path)
        except OSError as e:
            self._warn(("state", str(e)[:60]), f"couldn't save feed state: {e}")

    @property
    def playlist_importer(self):
        return self._playlist_importer or self.importer

    @property
    def enabled(self):
        return bool(self.token and self.secret)

    # ---------- HTTP to Slack ----------

    def http(self, url, payload, token=None):
        headers = {"Content-Type": "application/json; charset=utf-8"}
        if token:
            headers["Authorization"] = "Bearer " + token
        req = urllib.request.Request(url, json.dumps(payload).encode(), headers)
        try:
            with urllib.request.urlopen(req, timeout=10) as r:
                raw, status, hdrs = r.read(), r.status, r.headers
        except urllib.error.HTTPError as e:
            raw, status, hdrs = e.read(), e.code, e.headers
        except (urllib.error.URLError, OSError) as e:
            return 0, {"error": str(e)}, {}
        try:
            return status, json.loads(raw or b"{}"), hdrs
        except ValueError:
            return status, {"error": raw[:100].decode("utf-8", "replace")}, hdrs

    def _warn(self, key, msg):
        if key not in self.warned:
            self.warned.add(key)
            log(msg)

    def call(self, method, **payload):
        for attempt in (0, 1):
            status, res, hdrs = self.http(f"{API}/{method}", payload, self.token)
            if status == 429 and attempt == 0:
                time.sleep(min(float(hdrs.get("Retry-After") or 1), 30))
                continue
            break
        if status != 200 or not res.get("ok"):
            err = res.get("error") or f"HTTP {status}"
            self._warn((method, err), f"{method} failed: {err}")
            if err in FATAL:
                self.pause_until = time.time() + 300
            return None
        self.warned = {k for k in self.warned if k[0] != method}
        return res

    def respond(self, url, payload):
        if not url:
            return
        status, res, _ = self.http(url, payload)
        if status != 200:
            self._warn(("response_url", status), f"response_url failed: HTTP {status} {res.get('error', '')}")

    # ---------- requests ----------

    def handle(self, path, headers, body):
        """Verified entry point for the /slack/* routes. Returns (status, json-able or None)."""
        if not self.enabled:
            return 503, {"error": "Slack bot isn't configured"}
        if not verify_signature(self.secret, headers.get("X-Slack-Request-Timestamp"),
                                headers.get("X-Slack-Signature"), body):
            return 401, {"error": "bad signature"}
        try:
            if path == "/slack/events":
                return self.on_event(json.loads(body or b"{}"), headers)
            form = dict(urllib.parse.parse_qsl(body.decode()))
            if path == "/slack/commands":
                return self.on_command(form)
            if path == "/slack/interactions":
                return self.on_interaction(json.loads(form.get("payload") or "{}"))
        except (ValueError, UnicodeDecodeError):
            return 400, {"error": "bad request"}
        return 404, {"error": "not found"}

    def spawn(self, fn, *args):
        def run():
            try:
                fn(*args)
            except Exception as e:  # noqa: BLE001 - a handler thread must never take the server down
                self._warn(("thread", fn.__name__, str(e)[:60]), f"{fn.__name__}: {e!r}")
        threading.Thread(target=run, daemon=True).start()

    # ---------- users ----------

    def fetch_user(self, uid):
        return self.slack._call("users.info", self.token, user=uid)["user"].get("profile", {})

    def user(self, uid, fallback=None):
        now = time.time()
        with self.users_lock:
            hit = self.users.get(uid)
        if hit and now - hit[1] < USER_TTL:
            return hit[0]
        try:
            p = self.fetch_user(uid)
            u = {"id": uid, "name": p.get("display_name") or p.get("real_name") or fallback or uid,
                 "avatar": p.get("image_72") or p.get("image_192")}
        except (AccountError, KeyError) as e:
            self._warn(("users.info", str(e)[:60]), f"users.info failed: {e}")
            return hit[0] if hit else {"id": uid, "name": fallback or uid, "avatar": None}
        with self.users_lock:
            self.users[uid] = (u, now)
        return u

    # ---------- commands ----------

    def on_command(self, form):
        if form.get("team_id") != self.team:
            return 403, {"error": "wrong workspace"}
        verb, arg = parse_command(form.get("text"))
        if verb == "help":
            return 200, {"response_type": "ephemeral", "text": HELP}
        self.spawn(self.run_command, verb, arg, form.get("user_id"), form.get("user_name"), form.get("response_url"))
        return 200, None

    def ephemeral(self, url, blocks, text, replace=False):
        self.respond(url, {"response_type": "ephemeral", "replace_original": replace, "text": text, "blocks": blocks})

    def run_command(self, verb, arg, uid, uname, url):
        try:
            if verb in ("play", "pause", "skip") and not (verb == "play" and arg):
                text = self.transport(verb, uid)
                return self.respond(url, {"response_type": "ephemeral", "text": text})
            if verb == "now":
                return self.ephemeral(url, *self.now_card())
            if verb == "queue":
                up = self.credits.annotate(self.player.queue(10))["upcoming"]
                return self.ephemeral(url, queue_blocks(up), "Up next")
            if verb == "play":
                arg = arg.strip()
            link = LINK_RX.search(arg)
            if link:
                return self.link_card(link.group(0), url)
            self.ephemeral(url, *self.search(arg))
        except (PlayerError, SpotifyError) as e:
            self.respond(url, {"response_type": "ephemeral", "text": f"Couldn't do that: {e}"})

    def link_card(self, link, url):
        self.respond(url, {"response_type": "ephemeral", "text": "Looking that up..."})
        try:
            r = self.resolve(link)
        except Exception as e:  # noqa: BLE001 - LinkError, Spotify and network errors all end up as a message
            return self.respond(url, {"response_type": "ephemeral", "replace_original": True, "text": f"Couldn't use that link: {e}"})
        self.ephemeral(url, link_blocks(r), r.get("name") or "Link", replace=True)

    def spotify_resolve(self, link):
        uri = to_uri(link)
        it = self.lookup(uri)
        return {"source": "spotify", "kind": it["type"], "name": it["name"], "url": spotify_url(uri),
                "subtitle": " · ".join(x for x in (artists_of(it) or it.get("owner"), (it.get("album") or {}).get("name")) if x),
                "artwork": it.get("artwork"), "spotify_uri": uri, "tracks": [], "total": None, "matched": None,
                "truncated": False}

    def now_card(self):
        st = self.player.status(fresh=True)
        t = st.get("track")
        if not t:
            return [context("Nothing is playing.")], "Nothing is playing."
        up = self.credits.annotate(self.player.queue(4)).get("upcoming", [])
        return (now_playing_blocks(t, st.get("state") in PLAYING, st.get("credit"), up, self.remote,
                                   block_id="card"), now_playing_text(t))

    def search(self, q):
        res = self.api.get("/search", q=q, type="track,album,playlist", limit=5)
        tracks = (page(res.get("tracks")) or {}).get("items", [])[:5]
        albums = (page(res.get("albums")) or {}).get("items", [])[:1]
        playlists = (page(res.get("playlists")) or {}).get("items", [])[:1]
        return search_blocks(q, tracks, albums + playlists), f"Results for {q}"

    def lookup(self, uri):
        kind, sid = uri.split(":")[1:]
        path = {"track": "tracks", "album": "albums", "playlist": "playlists"}.get(kind)
        if not path:
            raise SpotifyError("only tracks, albums and playlists can be played from Slack", 400)
        return item(self.api.get(f"/{path}/{sid}"))

    def log(self, who, action, detail=None, enrich=None):
        """Record a successful action in the activity feed; `who` is a user dict or a Slack user ID."""
        if not self.activity:
            return None
        entry = self.activity.record(who if isinstance(who, dict) else self.user(who), action, detail, "slack")
        if enrich:
            self.activity.enrich(entry, enrich)
        return entry

    def transport(self, verb, uid):
        """Do play/pause/skip for a Slack user (the feed card itself is the channel's feedback)."""
        if verb == "skip":
            user = self.user(uid)
            self.credits.skipped(user)
            name = ((self.player.status().get("track") or {}).get("name")) if self.activity else None
            self.player.next()
            self.log(user, "next", {"from": name} if name else {})
            return "Skipped."
        if verb == "pause":
            self.player.pause()
            self.log(uid, "pause")
            return "Paused."
        self.player.play({})
        self.log(uid, "play")
        return "Playing."

    # ---------- interactions ----------

    def on_interaction(self, p):
        if p.get("type") != "block_actions":
            return 200, None
        if (p.get("team") or {}).get("id") != self.team:
            return 403, {"error": "wrong workspace"}
        self.spawn(self.run_interaction, p)
        return 200, None

    def run_interaction(self, p):
        a = (p.get("actions") or [{}])[0]
        uid = (p.get("user") or {}).get("id")
        url = p.get("response_url")
        ephemeral = bool((p.get("container") or {}).get("is_ephemeral"))
        act = a.get("action_id")
        try:
            if act in ("playpause", "skip"):
                playing = self.player.status(fresh=True).get("state") in PLAYING
                self.transport("skip" if act == "skip" else "pause" if playing else "play", uid)
                if ephemeral:
                    time.sleep(0.7)
                    self.ephemeral(url, *self.now_card(), replace=True)
            elif act == "queue_add":
                u = self.user(uid, (p.get("user") or {}).get("name"))
                uri = to_uri(a.get("value"))
                self.player.enqueue({"uri": uri})
                self.credits.add([uri], u)
                self.log(u, "queue_add", {"uris": [uri], "count": 1}, lambda: {"names": [self.lookup(uri)["name"]]})
                self.done(p, a, ephemeral, "Queued", f"Queued by {esc(u['name'])}")
            elif act == "play_uri":
                u = self.user(uid, (p.get("user") or {}).get("name"))
                uri = to_uri(a.get("value"))
                self.player.play({"uri": uri})
                self.credits.start([uri], u)
                self.log(u, "play_item", {"uri": uri, "type": uri.split(":")[1]}, lambda: {"name": self.lookup(uri)["name"]})
                self.done(p, a, ephemeral, "Playing", "Playing now")
            elif act == "import_playlist":
                self.import_playlist(p, a, ephemeral, a.get("value"))
            elif act == "add_album":
                self.add_to_library(p, a, ephemeral, a.get("value"))
            elif act in ("rl_play", "rl_queue", "rl_library", "rl_import"):
                self.card_action(p, a)
        except (PlayerError, SpotifyError, ValueError) as e:
            self.respond(url, {"response_type": "ephemeral", "replace_original": False, "text": f"Couldn't do that: {e}"})

    def add_to_library(self, p, a, ephemeral, link):
        url, uid = p.get("response_url"), p["user"]["id"]
        if not self.add_album:
            return self.respond(url, {"response_type": "ephemeral", "replace_original": False, "text": "The Library isn't available."})
        u = self.user(uid, p["user"].get("name"))
        try:
            album = self.add_album(link, self.library_user(u))
        except Exception as e:  # noqa: BLE001 - LinkError, AccountError, Spotify and network errors become a message
            return self.respond(url, {"response_type": "ephemeral", "replace_original": False, "text": f"Couldn't add that: {e}"})
        self.log_album(u, album)
        self.done(p, a, ephemeral, "Added", self.album_text(album))

    @staticmethod
    def library_user(u):
        return {"id": u["id"], "name": u["name"], "avatar": u.get("avatar"), "admin": False}

    def log_album(self, u, album):
        if not album.get("already"):
            self.log(u, "album_add", {"id": album.get("id"), "name": album.get("name")})

    def album_text(self, album):
        link = f"<{self.remote.rstrip('/')}/album/{album.get('id')}|{esc(album.get('name'))}>"
        return f"{link} is already in the Library" if album.get("already") else f"Added {link} to the Library"

    def import_playlist(self, p, a, ephemeral, link):
        url, uid = p.get("response_url"), p["user"]["id"]
        if not self.playlist_importer:
            return self.respond(url, {"response_type": "ephemeral", "replace_original": False, "text": "Importing isn't available."})
        self.respond(url, {"response_type": "ephemeral", "replace_original": False, "text": "Importing... this can take a minute."})
        u = self.user(uid, p["user"].get("name"))
        try:
            res = self.playlist_importer(link, self.library_user(u))
        except Exception as e:  # noqa: BLE001 - LinkError, AccountError, Spotify and network errors become a message
            return self.respond(url, {"response_type": "ephemeral", "replace_original": False, "text": f"Couldn't import that: {e}"})
        if res.get("kind") == "album":
            self.log_album(u, res["album"])
            return self.done(p, a, ephemeral, "Added", self.album_text(res["album"]))
        pl = res["playlist"]
        self.log({"id": uid, "name": u["name"], "avatar": u["avatar"]}, "playlist_import",
                 {"id": pl["id"], "name": pl.get("name"), "imported": res.get("imported"), "source": res.get("source")})
        total = res.get("total") or res.get("imported")
        text = (f"Imported {res.get('imported')} of {total} songs as "
                f"<{self.remote.rstrip('/')}/playlist/{pl['id']}|{esc(pl.get('name'))}>")
        miss = [f"{esc(m.get('name'))} - {esc(', '.join(m.get('artists') or []))}" for m in res.get("unmatched") or []][:5]
        if miss:
            text += "\nNot on Spotify: " + "; ".join(miss)
        self.done(p, a, ephemeral, "Imported", text)

    def card_action(self, p, a):
        """A button on a card the bot posted in a thread: do it, then add the outcome to that same message."""
        url, act = p.get("response_url"), a.get("action_id")
        uid = p["user"]["id"]
        idx = (a.get("block_id") or "rl0")[2:]
        u = self.user(uid, p["user"].get("name"))
        who_ = who(u)
        try:
            r = self.resolve(a["value"])
            kind, uri, uris = r["kind"], r.get("spotify_uri"), matched_uris(r)
            names = [t.get("name") for t in r.get("tracks") or [] if t.get("uri")]
            drop, outcome = (), None
            if act == "rl_play":
                if kind == "playlist" and r.get("source") == "apple":
                    plan = {"uris": uris[:PLAY_CAP]}
                    self.player.play(plan)
                    self.credits.start(plan["uris"], u)
                    self.log(u, "play_item", {"uri": plan["uris"][0], "type": "track", "name": r.get("name")})
                else:
                    self.player.play({"uri": uri})
                    self.credits.start([uri], u)
                    self.log(u, "play_item", {"uri": uri, "type": kind, "name": r.get("name")})
                outcome = f"✓ Playing now, started by {who_}"
            elif act == "rl_queue":
                q = ([uri] if kind == "track" else uris[:QUEUE_CAP])
                self.player.enqueue({"uris": q})
                self.credits.add(q, u)
                self.log(u, "queue_add", {"uris": q, "count": len(q)}, lambda: {"names": names[:len(q)]})
                outcome = f"✓ Added {'to queue' if len(q) == 1 else f'{len(q)} songs to queue'} by {who_}"
            elif act == "rl_library":
                if not self.add_album:
                    raise ValueError("the Library isn't available")
                album = self.add_album(r["url"], self.library_user(u))
                self.log_album(u, album)
                outcome, drop = f"✓ {'Already in' if album.get('already') else 'Added to'} Library by {who_}", ("rl_library", "rl_import")
            else:
                if not self.playlist_importer:
                    raise ValueError("importing isn't available")
                res = self.playlist_importer(r["url"], self.library_user(u))
                if res.get("kind") == "album":
                    self.log_album(u, res["album"])
                    outcome = f"✓ Added to Library by {who_}"
                else:
                    pl = res["playlist"]
                    self.log(u, "playlist_import", {"id": pl["id"], "name": pl.get("name"), "imported": res.get("imported"),
                                                    "source": res.get("source")})
                    outcome = f"✓ Imported {res.get('imported')} of {res.get('total') or res.get('imported')} songs to Library by {who_}"
                drop = ("rl_library", "rl_import")
        except Exception as e:  # noqa: BLE001 - failures go to the person who clicked, not the channel
            return self.respond(url, {"response_type": "ephemeral", "replace_original": False, "text": f"Couldn't do that: {e}"})
        self.update_card(p, idx, outcome, drop)

    def update_card(self, p, idx, outcome, drop=()):
        msg = p.get("message") or {}
        ts, ch = msg.get("ts") or (p.get("container") or {}).get("message_ts"), (p.get("channel") or {}).get("id") or self.channel
        with self.card_lock:
            blocks = copy.deepcopy(self.cards.get(ts) or msg.get("blocks") or [])
            out_id = f"out{idx}"
            for i, b in enumerate(blocks):
                if b.get("block_id") == f"rl{idx}":
                    b["elements"] = [e for e in b["elements"] if e.get("action_id") not in drop]
                    if not b["elements"]:
                        blocks[i] = None
                elif b.get("block_id") == f"info{idx}" and drop:
                    t = b["elements"][0]["text"]
                    if "✓ In Library" not in t:
                        b["elements"][0]["text"] = t + " · ✓ In Library"
            blocks = [b for b in blocks if b]
            out = next((b for b in blocks if b.get("block_id") == out_id), None)
            if out:
                if outcome not in out["elements"][0]["text"].split(" · "):
                    out["elements"][0]["text"] += " · " + outcome
            else:
                at = next((i for i, b in enumerate(blocks) if b.get("block_id") == f"rl{idx}"), None)
                if at is None:
                    at = next((i for i, b in enumerate(blocks) if b.get("block_id") == f"info{idx}"), len(blocks) - 1)
                blocks.insert(at + 1, {"type": "context", "block_id": out_id, "elements": [{"type": "mrkdwn", "text": outcome}]})
            if self.call("chat.update", channel=ch, ts=ts, text=msg.get("text") or "Music link", blocks=blocks):
                self.cards[ts] = blocks
                while len(self.cards) > 50:
                    self.cards.pop(next(iter(self.cards)))

    def done(self, p, a, ephemeral, label, text):
        url = p.get("response_url")
        if not ephemeral:
            return self.respond(url, {"response_type": "ephemeral", "replace_original": False, "text": text})
        blocks = (p.get("message") or {}).get("blocks")
        if not blocks:
            return self.respond(url, {"response_type": "ephemeral", "replace_original": True, "text": f"{label}."})
        out = [context("✓ " + text) if b.get("block_id") == a.get("block_id") else b for b in blocks]
        self.respond(url, {"response_type": "ephemeral", "replace_original": True, "text": label, "blocks": out})

    # ---------- events / unfurl ----------

    def on_event(self, ev, headers):
        if ev.get("type") == "url_verification":
            return 200, {"challenge": ev.get("challenge")}
        if ev.get("team_id") != self.team:
            return 403, {"error": "wrong workspace"}
        now = time.time()
        self.seen_events = {k: t for k, t in self.seen_events.items() if now - t < 600}
        eid = ev.get("event_id")
        if headers.get("X-Slack-Retry-Num") or eid in self.seen_events:
            return 200, None
        self.seen_events[eid] = now
        e = ev.get("event") or {}
        if e.get("type") == "link_shared":
            self.spawn(self.thread_reply if e.get("channel") == self.channel else self.unfurl, e)
        return 200, None

    def own_user_id(self):
        if not self.bot_user:
            try:
                self.bot_user = self.slack._call("auth.test", self.token).get("user_id")
            except (AccountError, KeyError) as err:
                self._warn(("auth.test", str(err)[:60]), f"auth.test failed: {err}")
        return self.bot_user

    def thread_reply(self, e):
        """Links posted in the music channel get one threaded card (also sent to the channel) instead of an unfurl."""
        ts = e.get("message_ts")
        if not ts or ts in self.replied or (e.get("user") and e["user"] == self.own_user_id()):
            return
        self.replied.add(ts)
        if len(self.replied) > 200:
            self.replied = set(sorted(self.replied)[100:])
        poster = self.user(e["user"])["name"] if e.get("user") else None
        cards, names = [], []
        for link in e.get("links", [])[:6]:
            if len(names) >= CARD_LINKS:
                break
            try:
                r = self.resolve(link["url"])
            except Exception as err:  # noqa: BLE001 - unsupported links (LinkError) and lookup failures get no card
                self._warn(("reply", str(err)[:60]), f"link {link.get('url')}: {err}")
                continue
            cards += reply_card(r, len(names), poster)
            names.append(r.get("name") or "link")
        if cards:
            self.call("chat.postMessage", channel=self.channel, thread_ts=e.get("thread_ts") or ts, reply_broadcast=True,
                      text="Robotics Music: " + ", ".join(names), blocks=cards, unfurl_links=False, unfurl_media=False)

    def unfurl(self, e):
        unfurls = {}
        for link in e.get("links", [])[:5]:
            try:
                unfurls[link["url"]] = {"blocks": link_blocks(self.resolve(link["url"]))}
            except Exception as err:  # noqa: BLE001 - unsupported links (LinkError) and lookup failures just don't unfurl
                self._warn(("unfurl", str(err)[:60]), f"unfurl {link.get('url')}: {err}")
        if unfurls:
            args = {"unfurl_id": e["unfurl_id"], "source": e.get("source")} if e.get("unfurl_id") else \
                {"channel": e.get("channel"), "ts": e.get("message_ts")}
            self.call("chat.unfurl", unfurls=unfurls, **args)

    # ---------- live feed ----------

    def start(self):
        if not self.enabled:
            log("SLACK_SIGNING_SECRET or SLACK_BOT_TOKEN missing; bot and #music feed are off")
            return
        threading.Thread(target=self.feed_loop, daemon=True).start()
        log(f"bot on; feeding {self.channel}")

    def feed_loop(self):
        q = self.player.subscribe()
        while True:
            try:
                ev, data = q.get(timeout=0.5)
                if ev == "status":
                    self.st = data
                elif ev == "queue":
                    self.upcoming = data.get("upcoming", [])
            except queuelib.Empty:
                pass
            try:
                self.tick(time.time())
            except Exception as e:  # noqa: BLE001 - keep the feed alive
                self._warn(("tick", str(e)[:60]), f"feed: {e!r}")

    def rendered(self, cur):
        return now_playing_blocks(cur["track"], cur["playing"], cur.get("credit"), cur["upcoming"], self.remote)

    def tick(self, now):
        before = (self.cur or {}).get("ts")
        self.step(now)
        if (self.cur or {}).get("ts") != before:
            self.save_cur()

    def step(self, now):
        if now < self.pause_until:
            return
        t = self.st.get("track")
        uri = t.get("uri") if t else None
        playing = self.st.get("state") in PLAYING
        if uri != self.cand[0]:
            self.cand = (uri, now)
        cur = self.cur
        if cur and not t and now - self.cand[1] >= SETTLE:
            self.finish(cur)
            self.cur = None
        elif t and playing and (not cur or cur["uri"] != uri):
            self.rotate(t, now)
        elif cur and cur["uri"] == uri:
            self.refresh(cur, playing, now)

    def finish(self, cur):
        skip = self.st.get("skip") or {}
        skipped_by = skip.get("by") if skip.get("from") == cur["uri"] else None
        self.call("chat.update", channel=self.channel, ts=cur["ts"], text=f"Played: {cur['track'].get('name')}",
                  blocks=played_blocks(cur["track"], cur.get("credit"), skipped_by))

    def rotate(self, t, now):
        try:
            up = self.credits.annotate(self.player.queue(4)).get("upcoming", [])
        except (PlayerError, SpotifyError):
            up = self.upcoming
        cur = {"uri": t["uri"], "track": t, "playing": True, "upcoming": up[:3],
               "credit": self.st.get("credit"), "ts": None, "sig": None, "sent": now, "posted": now}
        old = self.cur
        if old and old.get("ts") and now - old.get("posted", 0) < REUSE:
            cur.update(ts=old["ts"], posted=old.get("posted", now))
            if self.call("chat.update", channel=self.channel, ts=cur["ts"], text=now_playing_text(t),
                         blocks=self.rendered(cur)):
                cur["sig"] = self.sig(cur)
            self.cur = cur
            return
        if old:
            self.finish(old)
            self.cur = None
        res = self.call("chat.postMessage", channel=self.channel, text=now_playing_text(t),
                        blocks=self.rendered(cur), unfurl_links=False, unfurl_media=False)
        if res:
            cur["ts"], cur["sig"] = res["ts"], self.sig(cur)
            self.cur = cur
        else:
            self.cur = {**cur, "ts": None}

    @staticmethod
    def sig(cur):
        return (cur["playing"], tuple((e.get("item") or e).get("uri") for e in cur["upcoming"]))

    def refresh(self, cur, playing, now):
        if not cur["ts"]:
            return
        cur["playing"] = playing
        if self.upcoming:
            cur["upcoming"] = self.upcoming[:3]
        if self.sig(cur) == cur["sig"] or now - cur["sent"] < UPDATE_EVERY:
            return
        cur["sent"] = now
        if self.call("chat.update", channel=self.channel, ts=cur["ts"], text=now_playing_text(cur["track"]),
                     blocks=self.rendered(cur)):
            cur["sig"] = self.sig(cur)


def from_env(slack, player, api, credits, resolve=None, importer=None, state_path=None, activity=None, add_album=None,
             playlist_importer=None):
    return SlackBot(slack, player, api, credits, os.environ.get("SLACK_SIGNING_SECRET"),
                    os.environ.get("SLACK_MUSIC_CHANNEL") or DEFAULT_CHANNEL,
                    slack.team_id or DEFAULT_TEAM, os.environ.get("SLACK_REMOTE_URL") or DEFAULT_REMOTE,
                    resolve, importer, state_path, activity, add_album, playlist_importer)
