"""A WebSocket, in the standard library, because everything else here is too.

Harbor's whole surface is stdlib: the view server, the queue, the ledger. A dependency
here would mean the voice gateway is the one thing that cannot start on a fresh checkout,
and RFC 6455's server half is about a hundred lines. This is those hundred lines.

WHAT IT DOES: the handshake, masked frames in, unmasked frames out, continuation frames,
close and ping. WHAT IT DOES NOT: extensions, compression, fragmentation on the way out,
or anything a browser will not ask for. The client is one page this repository also owns,
so the surface is exactly as wide as that page needs and no wider.

TWO THINGS THAT ARE EASY TO GET WRONG AND EXPENSIVE TO DEBUG:

  A CLIENT FRAME IS ALWAYS MASKED and a server frame never is. A browser closes the
  connection with no visible error if a server masks, and the failure looks like a socket
  that drops for no reason.

  THE PAYLOAD LENGTH IS THREE ENCODINGS, not one. 0 to 125 inline, 126 with a two-byte
  length, 127 with an eight-byte one. Audio frames land in the second and third of those
  constantly, so a reader that only handles the first works perfectly on every control
  message and then corrupts the first real utterance.
"""
from __future__ import annotations

import base64
import hashlib
import json
import os
import struct
import threading

GUID = b"258EAFA5-E914-47DA-95CA-C5AB0DC85B11"

CONT, TEXT, BINARY, CLOSE, PING, PONG = 0x0, 0x1, 0x2, 0x8, 0x9, 0xA

# A spoken turn is a few hundred kilobytes of 16 kHz PCM. Anything past this is not
# speech, and refusing it is what stops one client holding the whole process's memory.
MAX_MESSAGE = 8 * 1024 * 1024


def accept_key(key: str) -> str:
    return base64.b64encode(hashlib.sha1(key.encode() + GUID).digest()).decode()


def is_upgrade(headers) -> bool:
    return ("websocket" in (headers.get("Upgrade") or "").lower()
            and bool(headers.get("Sec-WebSocket-Key")))


def host_of(value: str) -> str:
    """The hostname out of an Origin, a Referer or a Host, lower-cased, port dropped."""
    value = str(value or "").strip()
    if "//" in value:
        value = value.split("//", 1)[1]
    value = value.split("/", 1)[0]
    if value.startswith("["):                       # a bracketed IPv6 literal
        return value.split("]", 1)[0].lstrip("[").lower()
    return value.split(":", 1)[0].lower()


def same_origin(headers) -> bool:
    """Did Harbor's own page open this socket, rather than some other page in some tab.

    A WEBSOCKET IS NOT PROTECTED BY THE SAME-ORIGIN POLICY. Any page in any tab can
    open one to any host, with no preflight and no permission, and this socket accepts
    a line that is typed into Harbor's live pane and submitted. So the handshake is the
    only place to stop it, and refusing there is the whole defence.

    The view's proxy makes the same check one hop earlier, and that is the one that
    matters in production because the gateway binds loopback. This is here anyway, for
    the same reason the boundary in harbor-message is enforced on send rather than
    trusted from above: a check that exists in exactly one place is a check that
    disappears the first time something reaches this port another way.

    Neither header present is allowed. Browsers always send at least one, so their joint
    absence is a non-browser client on loopback, and refusing those would break the
    selftest and any future native client while stopping nothing.

    ORIGIN IS COMPARED AGAINST `X-Forwarded-Host`, NOT `Host`, and that is the whole
    correctness of this function. The only way a browser reaches this port is through
    the view's proxy, which REWRITES Host to 127.0.0.1:<port> so the loopback upstream
    accepts it. Comparing Origin against that rewritten value means the phone's
    `https://<machine>.<tailnet>.ts.net` is measured against `127.0.0.1`, which can
    never agree: the check then refuses every real handshake from the phone and passes
    at the desk, where both sides happen to say 127.0.0.1. It works where he is sitting
    and fails where the segment tells him to use it, which is the worst available
    failure. The proxy asserts X-Forwarded-Host itself and drops any inbound copy, so
    it is the browser's own Host and not the client's claim.
    """
    site = (headers.get("Sec-Fetch-Site") or "").strip().lower()
    if site and site not in ("same-origin", "none"):
        return False
    origin = headers.get("Origin")
    asked = headers.get("X-Forwarded-Host") or headers.get("Host")
    if origin and host_of(origin) != host_of(asked):
        return False
    return True


class Socket:
    """One connection. Reading is single-threaded; writing is locked, because the
    speaker, the bus and the turn machine all send on it from different threads."""

    def __init__(self, conn):
        self.conn = conn
        self.open = True
        self._wlock = threading.Lock()

    # -- handshake ---------------------------------------------------------- #

    @classmethod
    def upgrade(cls, handler) -> "Socket | None":
        key = handler.headers.get("Sec-WebSocket-Key")
        if not key:
            return None
        handler.send_response(101, "Switching Protocols")
        handler.send_header("Upgrade", "websocket")
        handler.send_header("Connection", "Upgrade")
        handler.send_header("Sec-WebSocket-Accept", accept_key(key))
        handler.end_headers()
        try:
            handler.wfile.flush()
        except OSError:
            return None
        # The handler must stop treating this as HTTP: anything it writes now would be
        # framed as a response into the middle of a websocket stream.
        handler.close_connection = True
        return cls(handler.connection)

    # -- reading ------------------------------------------------------------ #

    def _exact(self, n: int) -> bytes:
        buf = b""
        while len(buf) < n:
            chunk = self.conn.recv(n - len(buf))
            if not chunk:
                raise ConnectionError("closed")
            buf += chunk
        return buf

    def recv(self):
        """(opcode, payload), or None when the peer closed.

        Control frames are answered here rather than handed up: a ping the application
        has to remember to answer is a connection that dies whenever the application is
        busy, which on this socket means whenever a turn is being spoken.
        """
        opcode, chunks, total = None, [], 0
        while True:
            try:
                head = self._exact(2)
            except (ConnectionError, OSError):
                self.open = False
                return None
            fin = bool(head[0] & 0x80)
            op = head[0] & 0x0F
            masked = bool(head[1] & 0x80)
            length = head[1] & 0x7F
            if length == 126:
                length = struct.unpack(">H", self._exact(2))[0]
            elif length == 127:
                length = struct.unpack(">Q", self._exact(8))[0]
            if length > MAX_MESSAGE:
                self.close(1009, "message too big")
                return None
            mask = self._exact(4) if masked else b""
            payload = self._exact(length) if length else b""
            if masked:
                payload = bytes(b ^ mask[i % 4] for i, b in enumerate(payload))

            if op == CLOSE:
                self.close()
                return None
            if op == PING:
                self.send(PONG, payload)
                continue
            if op == PONG:
                continue

            if op != CONT:
                opcode = op
            chunks.append(payload)
            total += len(payload)
            if total > MAX_MESSAGE:
                self.close(1009, "message too big")
                return None
            if fin:
                return opcode, b"".join(chunks)

    # -- writing ------------------------------------------------------------ #

    def send(self, opcode: int, payload: bytes) -> bool:
        """One unmasked frame. False when the peer has gone, never an exception: a turn
        must not die because the phone locked mid-sentence."""
        if not self.open:
            return False
        n = len(payload)
        if n < 126:
            head = struct.pack(">BB", 0x80 | opcode, n)
        elif n < (1 << 16):
            head = struct.pack(">BBH", 0x80 | opcode, 126, n)
        else:
            head = struct.pack(">BBQ", 0x80 | opcode, 127, n)
        try:
            with self._wlock:
                self.conn.sendall(head + payload)
            return True
        except OSError:
            self.open = False
            return False

    def send_json(self, obj) -> bool:
        return self.send(TEXT, json.dumps(obj).encode())

    def send_binary(self, blob: bytes) -> bool:
        return self.send(BINARY, blob)

    def close(self, code: int = 1000, reason: str = "") -> None:
        if self.open:
            self.send(CLOSE, struct.pack(">H", code) + reason.encode()[:120])
            self.open = False
        try:
            self.conn.close()
        except OSError:
            pass


def random_key() -> str:                                            # pragma: no cover
    """Only used by the selftest, which speaks the client half."""
    return base64.b64encode(os.urandom(16)).decode()


def mask_frame(opcode: int, payload: bytes) -> bytes:                # pragma: no cover
    """A CLIENT frame, masked, for the selftest. See the docstring: a server frame that
    is masked is a connection a browser drops silently."""
    mask = os.urandom(4)
    body = bytes(b ^ mask[i % 4] for i, b in enumerate(payload))
    n = len(payload)
    if n < 126:
        head = struct.pack(">BB", 0x80 | opcode, 0x80 | n)
    elif n < (1 << 16):
        head = struct.pack(">BBH", 0x80 | opcode, 0x80 | 126, n)
    else:
        head = struct.pack(">BBQ", 0x80 | opcode, 0x80 | 127, n)
    return head + mask + body
