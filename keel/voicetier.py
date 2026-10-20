"""The voice tier: the deck's `/voice/` routes, the phone's one door onto the voice gateway,
which binds loopback and is reached by nothing else.

HTTP is proxied with `X-Forwarded-Host` set to the browser's own
Host (any inbound copy is dropped), because the gateway's websocket handshake compares
`Origin` against that header and a proxy that rewrote Host would fail every phone. The
upgrade itself is not parsed: a raw socket is opened to the gateway, the request line and
headers are forwarded, and bytes are pumped both ways until either side closes. When
nothing answers on the port the tier says so with a 503 rather than a hang.
"""

import re
import shutil
import socket
import threading
import urllib.error
import urllib.request

VOICE_ROUTE = re.compile(r"^/voice(/.*)?$")
VOICE_WS = "/voice/ws"
VOICE_TIMEOUT = 30.0        # a gateway answer is a health document or a state read, never a stream
VOICE_CONNECT = 5.0         # how long the websocket splice waits for the gateway to accept
SPLICE_CHUNK = 65536
# Not forwarded to the gateway: hop-by-hop headers, the proxied Host (urllib sets its own), the
# length (urllib sets it from the body), and any X-Forwarded-Host a client might claim. The
# splice keeps Connection and Upgrade: they are the handshake.
VOICE_DROP = {"host", "content-length", "keep-alive", "proxy-authenticate", "proxy-authorization",
              "te", "trailers", "transfer-encoding", "x-forwarded-host",
              # THE DECK'S COOKIE NEVER LEAVES THE DECK (c-451): it is the page's proof here,
              # and the gateway has no use for it.
              "cookie"}
VOICE_DROP_HTTP = VOICE_DROP | {"connection", "upgrade"}


class VoiceTier:
    """The `/voice/` methods of the deck's request handler, mixed into `serve.Handler`,
    which supplies `cfg`, the reply helpers and `pass_response` (the headers relayed from an
    upstream answer, the same list its lavish proxy relays)."""

    pass_response: frozenset = frozenset()

    def voice(self, method: str) -> None:
        """A `/voice/...` request: the websocket upgrade is spliced, everything else proxied."""
        if self.path_only() == VOICE_WS and "websocket" in (self.headers.get("Upgrade") or "").lower():
            # THE SOCKET IS THE PAGE'S (c-451, review item 3). A websocket is exempt from the
            # same-origin policy, and what it carries is his microphone and his turns into
            # Harbor, so the upgrade asks for the page's proof exactly as a POST does: the
            # cookie the voice app's own shell sets, and a browser's same-origin word.
            if not self.from_the_page():
                return self.refuse_unproven(unread=True)
            return self.voice_splice()
        self.voice_http(method)

    def voice_down(self, port: int) -> None:
        self.reply_json(503, {"ok": False, "voice": "down",
                              "error": f"voice is down: nothing answers on 127.0.0.1:{port}"})

    def forwarded_headers(self, drop: set[str]) -> list[tuple[str, str]]:
        """The request headers the gateway gets: the inbound ones minus `drop`, then
        `X-Forwarded-Host` set to the browser's Host. Any inbound copy is dropped first, so
        the value is what this server saw and never what a client claimed."""
        kept = [(name, value) for name, value in self.headers.items() if name.lower() not in drop]
        kept.append(("X-Forwarded-Host", self.headers.get("Host") or ""))
        return kept

    def voice_http(self, method: str) -> None:
        port = self.cfg.voice_port
        body = self.read_body() if method in ("POST", "PUT") else None
        request = urllib.request.Request(f"http://127.0.0.1:{port}{self.path}", data=body, method=method)
        for name, value in self.forwarded_headers(VOICE_DROP_HTTP):
            request.add_header(name, value)
        answering = False
        try:
            with urllib.request.urlopen(request, timeout=VOICE_TIMEOUT) as response:
                self.send_response(response.status)
                for name, value in response.headers.items():
                    if name.lower() in self.pass_response:
                        self.send_header(name, value)
                answering = True
                self.end_headers()
                if method != "HEAD":
                    shutil.copyfileobj(response, self.wfile)
        except (BrokenPipeError, ConnectionResetError):
            raise
        except urllib.error.HTTPError as error:
            with error:
                payload = error.read()
            self.reply(error.code, payload, error.headers.get("Content-Type", "text/plain"))
        except (OSError, urllib.error.URLError):
            if answering:
                raise BrokenPipeError("the client left mid-reply")
            self.voice_down(port)

    def voice_splice(self) -> None:
        """The websocket upgrade: a raw socket to the gateway, the request line and headers
        forwarded, then bytes pumped both ways until either side closes. The 101 (or the
        gateway's 403 for a foreign Origin) reaches the client exactly as the gateway wrote it."""
        port = self.cfg.voice_port
        try:
            upstream = socket.create_connection(("127.0.0.1", port), timeout=VOICE_CONNECT)
        except OSError:
            return self.voice_down(port)
        upstream.settimeout(None)
        lines = [f"{self.command} {self.path} HTTP/1.1", f"Host: 127.0.0.1:{port}"]
        lines += [f"{name}: {value}" for name, value in self.forwarded_headers(VOICE_DROP)]
        try:
            upstream.sendall(("\r\n".join(lines) + "\r\n\r\n").encode("latin-1"))
            splice(self.rfile, self.connection, upstream)
        finally:
            upstream.close()
            self.close_connection = True


def pump(read, sink: socket.socket) -> None:
    """Copy `read()` chunks into `sink` until EOF or an error, then half-close the sink so the
    other side sees the end."""
    try:
        while True:
            chunk = read()
            if not chunk:
                break
            sink.sendall(chunk)
    except (OSError, ValueError):
        pass
    finally:
        try:
            sink.shutdown(socket.SHUT_WR)
        except OSError:
            pass


def splice(client_reader, client: socket.socket, upstream: socket.socket) -> None:
    """Pump bytes both ways between a client connection and the gateway until either side
    closes. The client side is read through the handler's buffered reader so bytes that
    arrived behind the headers are not lost; when the gateway is done the client socket is
    shut both ways, which is what ends the other pump."""
    to_upstream = threading.Thread(target=pump, args=(lambda: client_reader.read1(SPLICE_CHUNK), upstream),
                                   name="voice-splice", daemon=True)
    to_upstream.start()
    pump(lambda: upstream.recv(SPLICE_CHUNK), client)
    try:
        client.shutdown(socket.SHUT_RDWR)
    except OSError:
        pass
    to_upstream.join(timeout=5)
