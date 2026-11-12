#!/usr/bin/env python3
"""Low-CPU "now playing" screen drawn straight into the Linux framebuffer."""
import argparse
import collections
import concurrent.futures
import fcntl
import hashlib
import http.client
import io
import json
import os
import queue
import sys
import threading
import time
import urllib.parse
import urllib.request

from PIL import Image, ImageChops, ImageDraw, ImageFilter, ImageFont

FB = "/dev/fb0"
SYSFB = "/sys/class/graphics/fb0"
CACHE_DIR = os.path.expanduser("~/.cache/music-display")
CACHE_FILES = 50
SECOND_SLACK = 0.005
SYNC_TOLERANCE_MS = 150
ART_WAIT = 0.3
ART_WORKERS = 4
ART_FAIL_BACKOFF = 30.0
PACK_THREADS = 4
PACK_PARALLEL_MIN = 200_000
WATCHDOG = 45
BLANK_AFTER = 1.5
FBIOBLANK = 0x4611
FB_BLANK_UNBLANK, FB_BLANK_POWERDOWN = 0, 4
FONT_DIRS = ["/usr/share/fonts/opentype/inter", "/usr/share/fonts/truetype/dejavu"]
FONT_FILES = {
    "inter": {400: "Inter-Regular.otf", 600: "Inter-SemiBold.otf", 700: "Inter-Bold.otf"},
    "dejavu": {400: "DejaVuSans.ttf", 600: "DejaVuSans-Bold.ttf", 700: "DejaVuSans-Bold.ttf"},
}

WHITE = (255, 255, 255)


def log(*a):
    print(*a, file=sys.stderr, flush=True)


class Api:
    def __init__(self, base, token):
        self.base = base.rstrip("/")
        self.token = token

    def get(self, path, timeout=8):
        req = urllib.request.Request(self.base + path, headers={"Authorization": "Bearer " + self.token})
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return json.load(r)["result"]


class Fonts:
    def __init__(self):
        self.cache = {}
        self.family = next(
            (f for f, d in zip(("inter", "dejavu"), FONT_DIRS) if os.path.exists(os.path.join(d, FONT_FILES[f][400]))),
            None,
        )

    def get(self, size, weight=400):
        size = max(8, int(size))
        key = (size, weight)
        if key not in self.cache:
            if self.family is None:
                self.cache[key] = ImageFont.load_default(size)
            else:
                d = FONT_DIRS[0 if self.family == "inter" else 1]
                self.cache[key] = ImageFont.truetype(os.path.join(d, FONT_FILES[self.family][weight]), size)
        return self.cache[key]


FONTS = Fonts()


def fit(text, font, width):
    text = text or ""
    if font.getlength(text) <= width:
        return text
    while text and font.getlength(text + "…") > width:
        text = text[:-1]
    return text.rstrip() + "…"


def wrap(text, font, width, lines):
    words, out, cur = text.split(), [], ""
    for w in words:
        trial = (cur + " " + w).strip()
        if font.getlength(trial) <= width or not cur:
            cur = trial
        else:
            out.append(cur)
            cur = w
    out.append(cur)
    if len(out) > lines:
        out = out[:lines]
        out[-1] = fit(out[-1] + " …", font, width)
    return [fit(l, font, width) for l in out if l]


class Artwork:
    def __init__(self):
        self.mem = collections.OrderedDict()
        self.tiles = collections.OrderedDict()
        self.minis = collections.OrderedDict()
        self.jobs = {}
        self.failed = {}
        self.lock = threading.RLock()
        self.pool = concurrent.futures.ThreadPoolExecutor(ART_WORKERS)
        self.api = None
        self.notify = None
        os.makedirs(CACHE_DIR, exist_ok=True)

    def fetch(self, url):
        if url.startswith("/") and self.api:
            req = urllib.request.Request(self.api.base + url, headers={"Authorization": "Bearer " + self.api.token})
        else:
            req = url
        with urllib.request.urlopen(req, timeout=10) as r:
            return r.read()

    @staticmethod
    def sized(url, want):
        marker = "ab67616d0000b273"
        if marker in url:
            code = "00004851" if want <= 64 else "00001e02" if want <= 300 else "0000b273"
            return url.replace(marker, "ab67616d" + code)
        return url

    @staticmethod
    def remember(cache, key, value, limit):
        cache[key] = value
        cache.move_to_end(key)
        while len(cache) > limit:
            cache.popitem(last=False)

    def load(self, url, size):
        with self.lock:
            img = self.mem.get(url)
        if img is None:
            path = os.path.join(CACHE_DIR, hashlib.sha1(url.encode()).hexdigest())
            if os.path.exists(path):
                os.utime(path)
                with open(path, "rb") as f:
                    data = f.read()
            else:
                data = self.fetch(url)
                tmp = f"{path}.tmp{threading.get_ident()}"
                with open(tmp, "wb") as f:
                    f.write(data)
                os.replace(tmp, path)
                try:
                    self.prune()
                except OSError:
                    pass
            img = Image.open(io.BytesIO(data)).convert("RGB")
        mini = img.resize((64, 64), Image.BOX)
        tile = square(img, size) if size else None
        with self.lock:
            self.remember(self.mem, url, img, 24)
            self.remember(self.minis, url, mini, 48)
            if tile is not None:
                self.remember(self.tiles, (url, size), tile, 48)

    def submit(self, url, want, size):
        if not url:
            return None
        url = self.sized(url, want)
        key = (url, size)
        with self.lock:
            if (url, size) in self.tiles and url in self.minis:
                return None
            fut = self.jobs.get(key)
            if fut is None:
                if time.monotonic() - self.failed.get(url, -ART_FAIL_BACKOFF) < ART_FAIL_BACKOFF:
                    return None
                fut = self.pool.submit(self.load, url, size)
                self.jobs[key] = fut
                fut.add_done_callback(lambda f, k=key: self.done(k, f))
        return fut

    def done(self, key, fut):
        url = key[0]
        with self.lock:
            self.jobs.pop(key, None)
            err = fut.exception()
            if err is not None:
                self.failed[url] = time.monotonic()
        if err is not None:
            log("artwork failed", url, err)
        elif self.notify:
            self.notify(url)

    def failing(self, url, want):
        return time.monotonic() - self.failed.get(self.sized(url, want), -ART_FAIL_BACKOFF) < ART_FAIL_BACKOFF

    def get(self, url, want, size, deadline=None):
        if not url:
            return None
        sized = self.sized(url, want)
        with self.lock:
            tile = self.tiles.get((sized, size))
            if tile is not None:
                self.tiles.move_to_end((sized, size))
                return tile
        fut = self.submit(url, want, size)
        if fut is None:
            return None
        try:
            fut.result(None if deadline is None else max(0.0, deadline - time.monotonic()))
        except Exception:
            return None
        with self.lock:
            return self.tiles.get((sized, size))

    def mini(self, url, want):
        if not url:
            return None
        with self.lock:
            return self.minis.get(self.sized(url, want))

    @staticmethod
    def prune():
        files = [os.path.join(CACHE_DIR, f) for f in os.listdir(CACHE_DIR) if ".tmp" not in f]
        files.sort(key=os.path.getmtime)
        for f in files[:-CACHE_FILES]:
            try:
                os.unlink(f)
            except OSError:
                pass


ART = Artwork()
_masks = {}


def rounded_mask(size, radius):
    key = (size, radius)
    if key not in _masks:
        big = Image.new("L", (size * 4, size * 4), 0)
        ImageDraw.Draw(big).rounded_rectangle((0, 0, size * 4 - 1, size * 4 - 1), radius * 4, fill=255)
        _masks[key] = big.resize((size, size), Image.LANCZOS)
    return _masks[key]


def square(img, size):
    w, h = img.size
    s = min(w, h)
    img = img.crop(((w - s) // 2, (h - s) // 2, (w - s) // 2 + s, (h - s) // 2 + s))
    return img.resize((size, size), Image.LANCZOS)


def blend(fg, alpha):
    return tuple(int(c * alpha) for c in fg)


def clock(unix=None, hhmm=None):
    if hhmm:
        h, m = (int(v) for v in hhmm.split(":"))
    else:
        t = time.localtime(unix)
        h, m = t.tm_hour, t.tm_min
    return f"{(h % 12) or 12}:{m:02d} {'AM' if h < 12 else 'PM'}"


def is_playing(st):
    return (st or {}).get("state") in ("playing", "buffering")


class Blanker:
    """Idle debounce: blank only after BLANK_AFTER seconds of continuous silence, wake on the first sound."""

    def __init__(self, delay=BLANK_AFTER, now=0.0):
        self.delay = delay
        self.blanked = False
        self.since = now

    def update(self, playing, now):
        if playing:
            self.since = None
            if self.blanked:
                self.blanked = False
                return "wake"
            return None
        if self.since is None:
            self.since = now
        if not self.blanked and now - self.since >= self.delay:
            self.blanked = True
            return "blank"
        return None

    def remaining(self, now):
        if self.blanked or self.since is None:
            return None
        return max(0.0, self.delay - (now - self.since))


class Playhead:
    """Playback position interpolated from the last status event, so the clock can tick on whole seconds."""

    def __init__(self):
        self.pos, self.at, self.running, self.dur = 0.0, 0.0, False, 0

    def sync(self, pos_ms, now, running, dur_ms, force=False):
        pos_ms = pos_ms or 0
        if not force and running and self.running and abs(pos_ms - self.position(now)) <= SYNC_TOLERANCE_MS:
            self.dur = dur_ms or 0
            return
        self.pos, self.at, self.running, self.dur = pos_ms, now, running, dur_ms or 0

    def position(self, now):
        pos = self.pos + (now - self.at) * 1000 if self.running else self.pos
        return min(pos, self.dur) if self.dur else pos

    def second(self, now):
        return int(self.position(now) // 1000)

    def until_next_second(self, now):
        pos = self.position(now)
        if not self.running or (self.dur and pos >= self.dur):
            return None
        return (1000 - pos % 1000) / 1000 + SECOND_SLACK


class Scene:
    def __init__(self, w, h):
        self.w, self.h = w, h
        self.u = h / 1080
        self.backgrounds = collections.OrderedDict()
        self.bg_lock = threading.Lock()
        self.shadows = {}
        self.pending = set()

    def px(self, n, lo=1):
        return max(lo, round(n * self.u))

    def background(self, art_url, mini):
        key = (art_url, mini is None)
        with self.bg_lock:
            bg = self.backgrounds.get(key)
        if bg is None:
            if mini is None:
                bg = Image.new("RGB", (self.w, self.h), (18, 18, 22))
            else:
                small = mini.filter(ImageFilter.GaussianBlur(5))
                small = small.point([int(v * 0.42) for v in range(256)] * 3)
                mid = small.resize((max(1, self.w // 4), max(1, self.h // 4)), Image.BICUBIC)
                mid = mid.filter(ImageFilter.GaussianBlur(3))
                bg = ImageChops.add_modulo(mid.resize((self.w, self.h), Image.BICUBIC), dither(self.w, self.h))
            with self.bg_lock:
                Artwork.remember(self.backgrounds, key, bg, 4)
        return bg.copy()

    def warm(self, art_url, want):
        mini = ART.mini(art_url, want)
        if mini is not None:
            self.background(art_url, mini)

    def idle(self):
        img = Image.new("RGB", (self.w, self.h), (16, 16, 20))
        d = ImageDraw.Draw(img)
        big, small = FONTS.get(self.px(96), 700), FONTS.get(self.px(34), 400)
        name, url = "Robotics Music", "music.pinewoodrobotics.org"
        cy = self.h // 2
        d.text((self.w // 2, cy - self.px(20)), name, font=big, fill=WHITE, anchor="ms")
        d.text((self.w // 2, cy + self.px(50)), url, font=small, fill=(140, 140, 150), anchor="ms")
        return img, None

    def geometry(self):
        w, h, u = self.w, self.h, self.u
        art = int(min(h * 0.5, w * 0.38))
        x0 = int(w * 0.07)
        tx = x0 + art + self.px(64)
        return art, x0, tx, w - tx - x0

    def thumb_size(self):
        return self.px(64, 40)

    def avatar_size(self):
        return self.px(34)

    def tile(self, url, size, deadline):
        if not url:
            return None
        tile = ART.get(url, size, size, deadline)
        if tile is None and not ART.failing(url, size):
            self.pending.add(ART.sized(url, size))
        return tile

    def shadow(self, art_size):
        if art_size not in self.shadows:
            sp = self.px(100)
            shadow = Image.new("L", (art_size + 2 * sp, art_size + 2 * sp), 0)
            shadow.paste(150, (sp, sp + self.px(14), sp + art_size, sp + art_size + self.px(14)))
            self.shadows[art_size] = shadow.filter(ImageFilter.GaussianBlur(self.px(22)))
        return self.shadows[art_size]

    def track(self, st, upcoming, paused, wait=ART_WAIT):
        w, h, u = self.w, self.h, self.u
        tr = st["track"]
        art_size, x0, tx, tw = self.geometry()
        av = self.avatar_size()
        thumb = self.thumb_size()
        credit = st.get("credit")
        airplay = st.get("source") == "airplay"
        avatar_url = None if airplay else ((credit or {}).get("by") or {}).get("avatar")
        art_url = tr.get("artwork")
        thumbs = [] if airplay else [it["item"].get("artwork") for it in upcoming[:3]]
        for url, size in [(art_url, art_size), (avatar_url, av), *((t, thumb) for t in thumbs)]:
            ART.submit(url, size, size)
        deadline = None if wait is None else time.monotonic() + wait
        self.pending = set()
        art = self.tile(art_url, art_size, deadline)
        mini = ART.mini(art_url, art_size)
        img = self.background(art_url, mini)
        d = ImageDraw.Draw(img)

        f_title, f_meta, f_small = FONTS.get(self.px(60), 700), FONTS.get(self.px(30)), FONTS.get(self.px(24))
        f_head, f_row, f_rowsub = FONTS.get(self.px(30), 600), FONTS.get(self.px(26), 600), FONTS.get(self.px(22))
        dim, faint = blend(WHITE, 0.72), blend(WHITE, 0.55)

        title_lines = wrap(tr.get("name") or "", f_title, tw, 2)
        artists = ", ".join(a["name"] for a in tr.get("artists") or [] if a.get("name"))
        album = (tr.get("album") or {}).get("name") or ""
        meta = fit(" · ".join(p for p in (artists, album) if p), f_meta, tw)
        credit_text = None
        if airplay:
            sender = (st.get("airplay") or {}).get("sender")
            credit_text = f"AirPlay from {sender}" if sender else "AirPlay"
            upcoming = []
        elif credit and credit.get("by"):
            by = credit["by"]
            credit_text = "Autoplay" if credit.get("how") == "autoplay" else (
                by.get("name") or ""
            )

        title_lh = int(self.px(60) * 1.2)
        pitch = thumb + self.px(16)
        prog_h = self.px(6, 3)
        times_h = self.px(46)
        pad = self.px(44)

        label = "PAUSED" if paused else None

        def column_height(rows):
            ht = 0
            if label:
                ht += self.px(48)
            ht += len(title_lines) * title_lh + self.px(10) + self.px(40)
            if credit_text:
                ht += self.px(14) + av
            ht += pad + prog_h + times_h
            if rows:
                ht += pad + self.px(44) + rows * pitch
            return ht

        rows = min(3, len(upcoming))
        while rows and column_height(rows) > h - 2 * self.px(60):
            rows -= 1
        y = max(self.px(60), (h - column_height(rows)) // 2)

        ay = (h - art_size) // 2
        if art is not None:
            sp = self.px(100)
            img.paste((0, 0, 0), (x0 - sp, ay - sp), self.shadow(art_size))
            img.paste(art, (x0, ay), rounded_mask(art_size, self.px(18)))
        else:
            d.rounded_rectangle((x0, ay, x0 + art_size, ay + art_size), self.px(18), fill=(40, 40, 48))

        if label:
            d.text((tx, y), fit(label, FONTS.get(self.px(24), 600), tw), font=FONTS.get(self.px(24), 600),
                   fill=(255, 190, 90))
            y += self.px(48)
        for line in title_lines:
            d.text((tx, y), line, font=f_title, fill=WHITE)
            y += title_lh
        y += self.px(10)
        d.text((tx, y), meta, font=f_meta, fill=dim)
        y += self.px(40)
        if credit_text:
            y += self.px(14)
            ax = tx
            if avatar_url:
                im = self.tile(avatar_url, av, deadline)
                if im is not None:
                    img.paste(im, (tx, y), rounded_mask(av, av // 2))
                    ax = tx + av + self.px(12)
            d.text((ax, y + av // 2), fit(credit_text, f_small, tw - (ax - tx)), font=f_small, fill=faint, anchor="lm")
            y += av
        y += pad
        box = (tx, y, tx + tw, y + prog_h + times_h)
        y += prog_h + times_h

        if rows:
            y += pad
            d.text((tx, y), "Playing Next", font=f_head, fill=WHITE)
            y += self.px(44)
            for item in upcoming[:rows]:
                it = item["item"]
                im = self.tile(it.get("artwork"), thumb, deadline)
                if im is not None:
                    img.paste(im, (tx, y), rounded_mask(thumb, self.px(8)))
                else:
                    d.rounded_rectangle((tx, y, tx + thumb, y + thumb), self.px(8), fill=(40, 40, 48))
                textx = tx + thumb + self.px(18)
                names = ", ".join(a["name"] for a in it.get("artists") or [] if a.get("name"))
                d.text((textx, y + thumb // 2 - self.px(3)), fit(it.get("name") or "", f_row, tw - textx + tx),
                       font=f_row, fill=WHITE, anchor="ls")
                d.text((textx, y + thumb // 2 + self.px(4)), fit(names, f_rowsub, tw - textx + tx),
                       font=f_rowsub, fill=faint, anchor="lt")
                y += pitch

        if paused:
            img = img.point([int(v * 0.6) for v in range(256)] * 3)
        return img, box

    def progress(self, base, box, pos_ms, dur_ms, paused):
        region = base.crop(box).convert("RGBA")
        w, h = region.size
        bar_h = self.px(6, 3)
        over = Image.new("RGBA", region.size, (0, 0, 0, 0))
        d = ImageDraw.Draw(over)
        d.rounded_rectangle((0, 0, w - 1, bar_h - 1), bar_h // 2, fill=(255, 255, 255, 70))
        frac = min(1.0, pos_ms / dur_ms) if dur_ms else 0
        if frac > 0:
            d.rounded_rectangle((0, 0, max(bar_h - 1, int((w - 1) * frac)), bar_h - 1), bar_h // 2, fill=(255, 255, 255, 235))
        f = FONTS.get(self.px(22))
        ty = bar_h + self.px(12)
        fill = (255, 255, 255, 150)
        d.text((0, ty), fmt_time(pos_ms), font=f, fill=fill)
        d.text((w, ty), "-" + fmt_time(max(0, dur_ms - pos_ms)), font=f, fill=fill, anchor="ra")
        if paused:
            over.putalpha(over.getchannel("A").point([int(v * 0.7) for v in range(256)]))
        return Image.alpha_composite(region, over).convert("RGB")


def fmt_time(ms):
    s = int(ms // 1000)
    return f"{s // 60}:{s % 60:02d}"


_LUT = {
    "r": [v & 0xF8 for v in range(256)],
    "g_hi": [v >> 5 for v in range(256)],
    "g_lo": [((v >> 2) & 7) << 5 for v in range(256)],
    "b": [v >> 3 for v in range(256)],
}


_BAYER = [0, 8, 2, 10, 12, 4, 14, 6, 3, 11, 1, 9, 15, 7, 13, 5]
_dither = {}


def dither(w, h):
    """4x4 ordered-dither offsets sized to one RGB565 step (8 for red/blue, 4 for green), so the darkened
    blurred background doesn't band on the 16-bit framebuffer."""
    if (w, h) not in _dither:
        tile = Image.new("RGB", (4, 4))
        tile.putdata([(v // 2, v // 4, v // 2) for v in _BAYER])
        row = Image.new("RGB", (w, 4))
        for x in range(0, w, 4):
            row.paste(tile, (x, 0))
        img = Image.new("RGB", (w, h))
        for y in range(0, h, 4):
            img.paste(row, (0, y))
        _dither[(w, h)] = img
    return _dither[(w, h)]


PACK_POOL = concurrent.futures.ThreadPoolExecutor(PACK_THREADS)


def pack565(img):
    """Little-endian RGB565: low byte is G[2:0] B[4:0], high byte is R[4:0] G[5:3]. The two halves of each
    byte share no bits, so a modulo add is the same as an OR."""
    r, g, b = img.split()
    hi = ImageChops.add_modulo(r.point(_LUT["r"]), g.point(_LUT["g_hi"]))
    lo = ImageChops.add_modulo(g.point(_LUT["g_lo"]), b.point(_LUT["b"]))
    return Image.merge("LA", (lo, hi)).tobytes()


def pack(img, bpp):
    if bpp == 32:
        return img.tobytes("raw", "BGRX")
    w, h = img.size
    if w * h < PACK_PARALLEL_MIN:
        return pack565(img)
    step = -(-h // PACK_THREADS)
    return b"".join(PACK_POOL.map(pack565, [img.crop((0, y, w, min(h, y + step))) for y in range(0, h, step)]))


class Framebuffer:
    def __init__(self, path=FB):
        self.fd = os.open(path, os.O_RDWR)
        self.geometry = None
        self.refresh()

    def read_geometry(self):
        def rd(n):
            return open(f"{SYSFB}/{n}").read().strip()
        w, h = (int(v) for v in rd("virtual_size").split(","))
        bpp = int(rd("bits_per_pixel"))
        return w, h, bpp, int(rd("stride"))

    def refresh(self):
        g = self.read_geometry()
        changed = g != self.geometry
        self.geometry = g
        return changed

    @property
    def size(self):
        return self.geometry[:2]

    def power(self, on):
        try:
            fcntl.ioctl(self.fd, FBIOBLANK, FB_BLANK_UNBLANK if on else FB_BLANK_POWERDOWN)
        except OSError as e:
            log("fb blank failed:", e)

    def black(self):
        w, h = self.size
        self.write(Image.new("RGB", (w, h)))

    def write(self, img, x=0, y=0):
        _, _, bpp, stride = self.geometry
        bytespp = bpp // 8
        data = pack(img, bpp)
        w, h = img.size
        rb = w * bytespp
        if x == 0 and rb == stride:
            os.pwrite(self.fd, data, y * stride)
            return
        for r in range(h):
            os.pwrite(self.fd, data[r * rb:(r + 1) * rb], (y + r) * stride + x * bytespp)


def hide_console():
    try:
        fd = os.open("/dev/tty1", os.O_WRONLY | os.O_NOCTTY)
        os.write(fd, b"\033[?25l\033[9;0]")
        os.close(fd)
    except OSError as e:
        log("console setup skipped:", e)


def stream_events(api, out):
    delay = 1
    while True:
        try:
            out.put(("status", api.get("/api/status")))
            out.put(("queue", api.get("/api/queue?limit=3")))
            u = urllib.parse.urlsplit(api.base)
            conn = http.client.HTTPConnection(u.hostname, u.port, timeout=WATCHDOG)
            conn.request("GET", "/api/events", headers={"Authorization": "Bearer " + api.token, "Accept": "text/event-stream"})
            resp = conn.getresponse()
            if resp.status != 200:
                raise OSError(f"events: HTTP {resp.status}")
            delay = 1
            event, data = None, []
            while True:
                line = resp.readline()
                if not line:
                    raise OSError("event stream closed")
                line = line.decode("utf-8", "replace").rstrip("\r\n")
                if line.startswith("event:"):
                    event = line[6:].strip()
                elif line.startswith("data:"):
                    data.append(line[5:].lstrip())
                elif line == "":
                    if event in ("status", "queue") and data:
                        out.put((event, json.loads("\n".join(data))))
                    event, data = None, []
        except Exception as e:
            log(f"event stream: {e}; retrying in {delay}s")
            time.sleep(delay)
            delay = min(delay * 2, 30)


class Display:
    def __init__(self, api, fb):
        self.api, self.fb = api, fb
        self.status = None
        self.upcoming = []
        self.playhead = Playhead()
        self.events = None
        self.pending = set()
        self.art_dirty = False
        self.base = None
        self.box = None
        self.scene = None
        self.shown_key = None
        self.shown_second = None
        self.blanker = Blanker(now=time.monotonic())

    def position(self):
        return self.playhead.position(time.monotonic())

    def get_scene(self):
        w, h = self.fb.size
        if self.scene is None or (self.scene.w, self.scene.h) != (w, h):
            self.scene = Scene(w, h)
        return self.scene

    def prefetch(self):
        scene = self.get_scene()
        art, thumb = scene.geometry()[0], scene.thumb_size()
        for i, entry in enumerate(self.upcoming[:3]):
            url = entry["item"].get("artwork")
            ART.submit(url, thumb, thumb)
            if i == 0:
                fut = ART.submit(url, art, art)
                if fut is None:
                    ART.pool.submit(scene.warm, url, art)
                else:
                    fut.add_done_callback(lambda f, u=url: ART.pool.submit(scene.warm, u, art))

    def ticking(self):
        st = self.status
        return bool(self.box and self.base is not None and st and st.get("track") and not self.blanker.blanked)

    def refresh_queue(self):
        try:
            self.events.put(("queue", self.api.get("/api/queue?limit=3")))
        except Exception as e:
            log("queue fetch failed:", e)

    @staticmethod
    def key(st, upcoming):
        tr = (st or {}).get("track")
        if not tr:
            return None
        credit = st.get("credit") or {}
        if st.get("source") == "airplay":
            return ("airplay", tr.get("name"), tr.get("artwork"), st.get("state") == "paused",
                    (st.get("airplay") or {}).get("sender"))
        return (tr["uri"], st.get("state") == "paused", credit.get("how"), (credit.get("by") or {}).get("name"),
                tuple(i["item"]["uri"] for i in upcoming))

    def render(self):
        started = time.monotonic()
        scene = self.get_scene()
        st = self.status
        self.art_dirty = False
        if st and st.get("track"):
            self.base, self.box = scene.track(st, self.upcoming, st.get("state") == "paused")
            self.pending = scene.pending
        else:
            self.base, self.box = scene.idle()
            self.pending = set()
        self.shown_key = self.key(st, self.upcoming)
        self.fb.write(self.base)
        self.draw_progress()
        log(f"render {(time.monotonic() - started) * 1000:.0f} ms, {len(self.pending)} art pending")

    def draw_progress(self):
        now = time.monotonic()
        self.shown_second = self.playhead.second(now)
        st = self.status
        if not self.box or not st or not st.get("track"):
            return
        region = self.scene.progress(self.base, self.box, self.playhead.position(now), st.get("duration_ms") or 0,
                                     st.get("state") == "paused")
        self.fb.write(region, self.box[0], self.box[1])

    def handle(self, kind, data):
        if kind == "art":
            if data in self.pending:
                self.art_dirty = True
            return
        if kind == "queue":
            ups = (data or {}).get("upcoming", [])[:3]
            if [i["item"]["uri"] for i in ups] != [i["item"]["uri"] for i in self.upcoming]:
                self.upcoming = ups
                self.prefetch()
                if self.blanker.blanked and not is_playing(self.status):
                    return
                if self.key(self.status, ups) != self.shown_key:
                    self.render()
            return
        if data.get("removed"):
            return
        old_uri = ((self.status or {}).get("track") or {}).get("uri")
        new_uri = (data.get("track") or {}).get("uri")
        self.status = data
        self.playhead.sync(data.get("position_ms"), time.monotonic(), data.get("state") == "playing",
                           data.get("duration_ms"), force=new_uri != old_uri)
        if self.blanker.blanked and not is_playing(data):
            return
        if new_uri != old_uri and new_uri:
            self.upcoming = [i for i in self.upcoming if i["item"]["uri"] != new_uri]
            if len(self.upcoming) < 3:
                threading.Thread(target=self.refresh_queue, daemon=True).start()
        if self.key(data, self.upcoming) != self.shown_key or self.base is None:
            self.render()
        if new_uri != old_uri and new_uri:
            self.prefetch()

    def apply_blank(self, action):
        if action == "blank":
            self.base = None
            self.fb.black()
            self.fb.power(False)
        elif action == "wake":
            if self.base is None:
                self.render()
            self.fb.power(True)

    def run(self, events):
        self.events = events
        ART.notify = lambda url: events.put(("art", url))
        while True:
            now = time.monotonic()
            wait = WATCHDOG
            if self.ticking():
                until = self.playhead.until_next_second(now)
                if until is not None:
                    wait = until
            left = self.blanker.remaining(now)
            if left is not None:
                wait = min(wait, left + 0.01)
            try:
                kind, data = events.get(timeout=wait)
            except queue.Empty:
                kind = None
            if kind:
                self.handle(kind, data)
            action = self.blanker.update(is_playing(self.status), time.monotonic())
            if action:
                self.apply_blank(action)
            elif self.fb.refresh() and not self.blanker.blanked:
                self.base = None
                self.render()
            if self.art_dirty and events.empty() and not self.blanker.blanked:
                self.render()
            if self.ticking() and self.playhead.second(time.monotonic()) != self.shown_second:
                self.draw_progress()


def render_png(api, path, size):
    w, h = (int(v) for v in size.split("x"))
    st = api.get("/api/status")
    ups = api.get("/api/queue?limit=3").get("upcoming", [])[:3]
    scene = Scene(w, h)
    if st.get("track"):
        img, box = scene.track(st, ups, st.get("state") == "paused", wait=None)
        reg = scene.progress(img, box, st.get("position_ms") or 0, st.get("duration_ms") or 0, st.get("state") == "paused")
        img.paste(reg, box[:2])
    else:
        img, _ = scene.idle()
    img.save(path)


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--api", default=os.environ.get("MUSIC_API_URL", "http://127.0.0.1:8765"))
    p.add_argument("--token-file", default=os.environ.get("MUSIC_DISPLAY_TOKEN_FILE",
                                                           os.path.expanduser("~/.config/music-api/display-token")))
    p.add_argument("--render-png", metavar="PATH")
    p.add_argument("--size", default="1920x1080")
    args = p.parse_args()
    api = Api(args.api, open(args.token_file).read().strip())
    ART.api = api
    if args.render_png:
        render_png(api, args.render_png, args.size)
        return

    hide_console()
    events = queue.Queue()
    threading.Thread(target=stream_events, args=(api, events), daemon=True).start()
    try:
        Display(api, Framebuffer()).run(events)
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
