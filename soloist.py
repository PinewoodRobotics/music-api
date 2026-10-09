"""Client for Spotify Soloist's local WebSocket API. Stdlib only.

Soloist (https://developer.spotify.com/documentation/soloist) is Spotify's headless Connect client for Linux.
Started with `--ws ADDR:PORT`, it serves JSON over WebSocket: we send
{"type": "command", "command": ...} and it pushes events (auth_state, playback_state, track_changed, ...).
The endpoint is either given explicitly or discovered from ws.addr / ws.port in Soloist's data directory.
"""
import base64
import hashlib
import json
import os
import socket
import struct
import threading
import time

WS_GUID = "258EAFA5-E914-47DA-95CA-C5AB0DC85B11"


def default_data_dir():
    """Soloist's own default data directory (where it writes ws.addr / ws.port)."""
    if os.environ.get("STATE_DIRECTORY"):
        return os.environ["STATE_DIRECTORY"]
    base = os.environ.get("XDG_DATA_HOME") or os.path.expanduser("~/.local/share")
    return os.path.join(base, "soloist")


class SoloistError(Exception):
    def __init__(self, msg, status=502):
        super().__init__(msg)
        self.status = status


# ---------- minimal RFC 6455 client ----------

class WebSocket:
    def __init__(self, host, port, timeout=10):
        self.sock = socket.create_connection((host, port), timeout=timeout)
        self.buf = b""
        self.send_lock = threading.Lock()
        key = base64.b64encode(os.urandom(16)).decode()
        self.sock.sendall((
            f"GET / HTTP/1.1\r\nHost: {host}:{port}\r\nUpgrade: websocket\r\nConnection: Upgrade\r\n"
            f"Sec-WebSocket-Key: {key}\r\nSec-WebSocket-Version: 13\r\n\r\n").encode())
        while b"\r\n\r\n" not in self.buf:
            chunk = self.sock.recv(4096)
            if not chunk:
                raise ConnectionError("connection closed during handshake")
            self.buf += chunk
        head, self.buf = self.buf.split(b"\r\n\r\n", 1)
        lines = head.decode("latin-1").split("\r\n")
        if " 101 " not in lines[0] + " ":
            raise ConnectionError(f"handshake refused: {lines[0]}")
        headers = {k.strip().lower(): v.strip() for k, _, v in (l.partition(":") for l in lines[1:])}
        expect = base64.b64encode(hashlib.sha1((key + WS_GUID).encode()).digest()).decode()
        if headers.get("sec-websocket-accept") != expect:
            raise ConnectionError("bad Sec-WebSocket-Accept")
        self.sock.settimeout(None)

    def _read(self, n):
        while len(self.buf) < n:
            chunk = self.sock.recv(max(4096, n - len(self.buf)))
            if not chunk:
                raise ConnectionError("connection closed")
            self.buf += chunk
        out, self.buf = self.buf[:n], self.buf[n:]
        return out

    def _send_frame(self, opcode, payload):
        mask = os.urandom(4)
        n = len(payload)
        if n < 126:
            head = struct.pack("!BB", 0x80 | opcode, 0x80 | n)
        elif n < 65536:
            head = struct.pack("!BBH", 0x80 | opcode, 0x80 | 126, n)
        else:
            head = struct.pack("!BBQ", 0x80 | opcode, 0x80 | 127, n)
        masked = bytes(b ^ mask[i % 4] for i, b in enumerate(payload))
        with self.send_lock:
            self.sock.sendall(head + mask + masked)

    def send(self, obj):
        self._send_frame(0x1, json.dumps(obj).encode())

    def recv(self):
        """Return the next text message as a str. Answers pings; raises ConnectionError on close."""
        parts = []
        while True:
            b0, b1 = self._read(2)
            fin, opcode, n = b0 & 0x80, b0 & 0x0F, b1 & 0x7F
            if n == 126:
                n = struct.unpack("!H", self._read(2))[0]
            elif n == 127:
                n = struct.unpack("!Q", self._read(8))[0]
            mask = self._read(4) if b1 & 0x80 else None
            payload = self._read(n)
            if mask:
                payload = bytes(b ^ mask[i % 4] for i, b in enumerate(payload))
            if opcode == 0x8:
                raise ConnectionError("server closed the connection")
            if opcode == 0x9:
                self._send_frame(0xA, payload)
                continue
            if opcode == 0xA:
                continue
            parts.append(payload)
            if fin:
                return b"".join(parts).decode()

    def close(self):
        try:
            self._send_frame(0x8, b"")
        except OSError:
            pass
        self.sock.close()


# ---------- Soloist session ----------

class Soloist:
    """Keeps a connection to Soloist open, mirrors its state, and sends commands.

    `on_event(name, msg)` is called from the reader thread for every server event.
    """

    def __init__(self, ws=None, data_dir=None, on_event=None):
        self.explicit = ws  # "ADDR:PORT" or None to discover
        self.data_dir = data_dir or default_data_dir()
        self.on_event = on_event or (lambda name, msg: None)
        self.conn = None
        self.connected = False
        self.last_error = None
        self.auth = {"logged_in": False, "is_active": False, "device_name": None}
        self.playback = None
        self.position = None
        self.queue = {"previous": [], "upcoming": []}
        self.lock = threading.Lock()
        self.cmd_lock = threading.Lock()
        self.cond = threading.Condition(self.lock)
        self.pending = None  # (command name, [reply]) for the command awaiting command_result / error

    def endpoint(self):
        if self.explicit:
            host, _, port = self.explicit.rpartition(":")
            return host or "127.0.0.1", int(port)
        try:
            with open(os.path.join(self.data_dir, "ws.addr")) as f:
                host = f.read().strip()
            with open(os.path.join(self.data_dir, "ws.port")) as f:
                port = int(f.read().strip())
        except (OSError, ValueError):
            return None
        if host in ("0.0.0.0", "::", ""):
            host = "127.0.0.1"
        return host, port

    def available(self):
        return self.endpoint() is not None

    def loop(self):
        delay = 1
        while True:
            ep = self.endpoint()
            if ep is None:
                self.last_error = f"Soloist not running with --ws (no ws.port in {self.data_dir})"
                time.sleep(3)
                continue
            try:
                self.conn = WebSocket(*ep)
                self.connected, self.last_error, delay = True, None, 1
                self.on_event("connection", {"connected": True})
                while True:
                    self._handle(json.loads(self.conn.recv()))
            except (OSError, ConnectionError, ValueError) as e:
                self.last_error = f"Soloist connection: {e}"
            finally:
                if self.connected:
                    self.on_event("connection", {"connected": False})
                self.connected = False
                with self.cond:
                    if self.pending:
                        self.pending[1].append({"type": "error", "message": "connection lost"})
                        self.cond.notify_all()
                if self.conn:
                    self.conn.close()
                    self.conn = None
            time.sleep(delay)
            delay = min(delay * 2, 15)

    def _handle(self, msg):
        t = msg.get("type")
        with self.cond:
            if t == "auth_state":
                self.auth = {k: msg.get(k) for k in ("logged_in", "is_active", "device_name")}
                if not self.auth["logged_in"]:
                    self.playback = None
            elif t == "playback_state":
                self.playback = {k: v for k, v in msg.items() if k != "type"}
                self._set_position(msg.get("position"))
                self.auth["is_active"] = msg.get("is_active", self.auth["is_active"])
            elif t == "queue_changed":
                self.queue = {"previous": msg.get("previous", []), "upcoming": msg.get("upcoming", [])}
            elif t == "position_sync":
                self._set_position(msg.get("position"))
            elif self.playback is not None:
                pb = self.playback
                if t == "track_changed":
                    pb["item"] = msg.get("item")
                elif t == "playback_changed":
                    pb["status"] = msg.get("status")
                elif t == "volume_changed":
                    pb["volume"] = msg.get("volume")
                elif t == "context_changed":
                    pb["context"] = msg.get("context")
                elif t == "options_changed":
                    pb["options"] = msg.get("options")
                elif t == "device_changed":
                    pb["is_active"] = msg.get("is_active")
                    self.auth.update(is_active=msg.get("is_active"), device_name=msg.get("device_name"))
            if self.pending and (t == "error" or (t == "command_result" and msg.get("command") == self.pending[0])
                                 or (t, self.pending[0]) in (("playback_state", "get_state"),
                                                             ("queue_changed", "get_queue"),
                                                             ("auth_state", "get_auth_state"))):
                self.pending[1].append(msg)
                self.cond.notify_all()
        self.on_event(t, msg)

    def command(self, name, timeout=5, **fields):
        """Send one command and wait for its command_result / reply event. Raises SoloistError on error."""
        if not self.connected:
            raise SoloistError(self.last_error or "Soloist not connected", 503)
        with self.cmd_lock:
            reply = []
            with self.cond:
                self.pending = (name, reply)
            try:
                self.conn.send({"type": "command", "command": name, **fields})
                with self.cond:
                    if not self.cond.wait_for(lambda: reply, timeout):
                        raise SoloistError(f"Soloist did not answer {name}", 504)
            except OSError as e:
                raise SoloistError(f"Soloist send failed: {e}", 503)
            finally:
                with self.cond:
                    self.pending = None
        msg = reply[0]
        if msg.get("type") == "error":
            text = msg.get("message", "error")
            raise SoloistError(text, 409 if "auth" in text else 400)
        return msg

    def _set_position(self, pos):
        # On login Soloist can send position_sync before the first playback_state, and that state carries a
        # stale position, so keep whichever anchor is newest rather than whichever arrived last.
        if pos and (not self.position or pos.get("timestamp_ms", 0) >= self.position.get("timestamp_ms", 0)):
            self.position = pos

    def position_ms(self):
        """Current position, interpolated from the last anchor."""
        pos = self.position if self.playback else None
        if not pos:
            return 0
        elapsed = time.time() * 1000 - pos.get("timestamp_ms", 0)
        return max(0, int(pos.get("position_ms", 0) + elapsed * pos.get("speed", 0)))
