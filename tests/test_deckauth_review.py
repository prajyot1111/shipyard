"""Lane I after its fresh-context review (c-451): the five findings, over real HTTP.

1. A house-written HTML or SVG artifact is served into an opaque origin (a CSP sandbox with
   no `allow-same-origin`), so its script never holds the deck's cookie.
2. `KEEL_TOKEN` never reaches a house: not through the launch environment, and not through
   the deck's own `keel drain --once` (Retry, create-and-start).
3. The voice websocket is the page's: the upgrade needs the cookie, and the voice app's own
   shell hands it out.
4. On the human path, `Origin` must match scheme, host AND port.
5. The deck's cookie never leaves this process for the voice gateway.
"""

import json
import os
import socket
import subprocess
import threading
import urllib.request
from pathlib import Path
from unittest import mock

from keel import actions, artifacts, deckauth, harness, serve
from tests.test_deckauth import PageCase

SANDBOX = artifacts.SANDBOX


class FakeGateway:
    """A socket on a free port that records the first request it is sent and answers it:
    101 for an upgrade, a small JSON body otherwise."""

    def __init__(self):
        self.sock = socket.socket()
        self.sock.bind(("127.0.0.1", 0))
        self.sock.listen(4)
        self.port = self.sock.getsockname()[1]
        self.seen: list[str] = []
        threading.Thread(target=self.serve, daemon=True).start()

    def serve(self):
        while True:
            try:
                conn, _ = self.sock.accept()
            except OSError:
                return
            with conn:
                data = b""
                while b"\r\n\r\n" not in data:
                    chunk = conn.recv(4096)
                    if not chunk:
                        break
                    data += chunk
                head = data.decode("latin-1")
                self.seen.append(head)
                if "upgrade: websocket" in head.lower():
                    conn.sendall(b"HTTP/1.1 101 Switching Protocols\r\nUpgrade: websocket\r\n"
                                 b"Connection: Upgrade\r\n\r\n")
                else:
                    body = b'{"ok": true}'
                    conn.sendall(b"HTTP/1.1 200 OK\r\nContent-Type: application/json\r\n"
                                 b"Content-Length: " + str(len(body)).encode() + b"\r\n\r\n" + body)

    def close(self):
        self.sock.close()


class ArtifactSandboxTest(PageCase):
    def artifact(self, name: str, text: str) -> str:
        path = self.cfg.card_dir(self.review) / name
        path.write_text(text)
        return "/api/artifact/" + artifacts.token(self.cfg, path)

    def headers(self, url: str) -> dict:
        with urllib.request.urlopen(self.base + url, timeout=10) as response:
            response.read()
            return {name.lower(): value for name, value in response.headers.items()}

    def test_a_house_written_page_runs_in_an_opaque_origin_without_the_cookie(self):
        """The finding: a plan.html he opens from the deck ran in the deck's origin, so its
        script could POST /api/action with his cookie and approve its own gate. A sandbox
        with no `allow-same-origin` makes its origin opaque: no cookie, no same-origin."""
        script = "<script>fetch('/api/action',{method:'POST',body:'{\"verb\":\"approve\"}'})</script>"
        for name, text in (("plan.html", script), ("shape.svg", f'<svg xmlns="http://www.w3.org/2000/svg">{script}</svg>'),
                           ("notes.md", "# notes\n\n" + script)):
            got = self.headers(self.artifact(name, text))
            self.assertEqual(got.get("content-security-policy"), SANDBOX, name)
            self.assertNotIn("allow-same-origin", got.get("content-security-policy", ""), name)
            self.assertEqual(got.get("x-content-type-options"), "nosniff", name)

    def test_every_other_artifact_is_not_sniffed_into_a_page(self):
        for name, text in (("plan.html", "<p>x</p>"), ("log.txt", "<script>x</script>")):
            got = self.headers(self.artifact(name, text) + "?raw=1")
            self.assertEqual(got.get("x-content-type-options"), "nosniff", name)

    def test_the_decks_own_shell_is_not_sandboxed(self):
        got = self.headers("/")
        self.assertNotIn("content-security-policy", got)


class NoTokenForAHouseTest(PageCase):
    def test_the_launch_environment_never_carries_his_token(self):
        seen = {}

        def run(argv, **kwargs):
            seen["env"] = kwargs["env"]
            return subprocess.CompletedProcess(argv, 0, stdout="backgrounded · abcd1234 · c-1\n", stderr="")
        with mock.patch.dict(os.environ, {"KEEL_TOKEN": "his", "KEEL_LIVE_STATE": "1"}), \
                mock.patch.object(harness.subprocess, "run", side_effect=run), \
                mock.patch.object(harness, "resolve_session", return_value="abcd1234"):
            harness.start_bg(self.dir, "go", name="c-1", config_dir=self.dir / "cfg",
                             settings_path=self.dir / "s.json", model="opus")
            self.assertNotIn("KEEL_TOKEN", seen["env"])
            self.assertNotIn("KEEL_LIVE_STATE", seen["env"])
            for config_dir in (None, self.dir / "cfg"):
                env = harness.scoped_env(config_dir)
                self.assertIsNotNone(env)
                self.assertNotIn("KEEL_TOKEN", env)
                self.assertNotIn("KEEL_LIVE_STATE", env)
            self.assertNotIn("KEEL_TOKEN", harness.child_env("c-1", self.dir / "cfg"))

    def test_the_decks_retry_runs_the_drain_without_his_token(self):
        """Retry through the deck's own door: the kb it runs is his, the drain it runs is not."""
        calls = []

        def run(argv, **kwargs):
            calls.append((argv, kwargs.get("env") or {}))
            return subprocess.CompletedProcess(argv, 0, stdout="{}", stderr="")
        with mock.patch.object(actions.subprocess, "run", side_effect=run):
            status, answer = self.post("/api/action", {"verb": "house.retry", "id": self.inbox},
                                       self.browser(self.cookie_pair()))
        self.assertEqual(status, 200, answer)
        drains = [env for argv, env in calls if Path(argv[0]).name == "keel"]
        kbs = [env for argv, env in calls if Path(argv[0]).name == "kb"]
        self.assertTrue(drains, calls)
        self.assertTrue(all("KEEL_TOKEN" not in env for env in drains))
        self.assertTrue(kbs and all(env.get("KEEL_TOKEN") == self.token for env in kbs))


class VoiceSocketTest(PageCase):
    def setUp(self):
        super().setUp()
        self.gateway = FakeGateway()
        self.addCleanup(self.gateway.close)
        self.cfg.voice_port = self.gateway.port

    def upgrade(self, headers: dict) -> str:
        port = self.server.server_address[1]
        lines = [f"GET /voice/ws HTTP/1.1", f"Host: 127.0.0.1:{port}", "Upgrade: websocket",
                 "Connection: Upgrade", "Sec-WebSocket-Version: 13",
                 "Sec-WebSocket-Key: dGhlIHNhbXBsZSBub25jZQ=="]
        lines += [f"{name}: {value}" for name, value in headers.items()]
        with socket.create_connection(("127.0.0.1", port), timeout=10) as client:
            client.sendall(("\r\n".join(lines) + "\r\n\r\n").encode())
            client.settimeout(5)
            return client.recv(4096).decode("latin-1")

    def test_an_upgrade_without_the_cookie_is_refused(self):
        for headers in ({"Origin": self.base}, {"Origin": self.base, "Cookie": "x=1"},
                        {"Cookie": self.cookie_pair()}):
            answer = self.upgrade(headers)
            self.assertTrue(answer.startswith("HTTP/1.0 403") or answer.startswith("HTTP/1.1 403"),
                            (headers, answer[:80]))
        self.assertEqual(self.gateway.seen, [], "nothing reached the gateway")

    def test_the_pages_upgrade_is_spliced_and_the_cookie_stays_here(self):
        answer = self.upgrade({"Origin": self.base, "Cookie": self.cookie_pair()})
        self.assertIn("101", answer.splitlines()[0])
        self.assertEqual(len(self.gateway.seen), 1)
        self.assertNotIn("cookie:", self.gateway.seen[0].lower())

    def test_a_plain_voice_request_does_not_carry_the_cookie_either(self):
        request = urllib.request.Request(self.base + "/voice/state",
                                         headers={"Cookie": self.cookie_pair()})
        with urllib.request.urlopen(request, timeout=10) as response:
            response.read()
        self.assertNotIn("cookie:", self.gateway.seen[0].lower())

    def test_the_voice_apps_own_shell_hands_out_the_cookie(self):
        app = self.cfg.segments_dir / "voice" / "app"
        app.mkdir(parents=True)
        (app / "index.html").write_text("<!doctype html><title>voice</title>")
        (app / "app.js").write_text("// the app")
        with urllib.request.urlopen(self.base + "/segments/voice/app/", timeout=10) as response:
            response.read()
            self.assertTrue((response.headers.get("Set-Cookie") or "").startswith("keel_deck_"))
        with urllib.request.urlopen(self.base + "/segments/voice/app/app.js", timeout=10) as response:
            response.read()
            self.assertIsNone(response.headers.get("Set-Cookie"))


class StrictOriginTest(PageCase):
    def note(self, headers: dict) -> int:
        return self.post("/api/action", {"verb": "note", "id": self.inbox, "text": "o"}, headers)[0]

    def test_origin_must_match_scheme_host_and_port(self):
        port = self.server.server_address[1]
        cookie = {"Cookie": self.cookie_pair()}
        with mock.patch.object(serve.actions, "act", return_value={}) as act:
            for origin in (f"http://127.0.0.1:{port + 1}", f"https://127.0.0.1:{port}",
                           "http://127.0.0.1", f"http://localhost:{port}"):
                self.assertEqual(self.note({**cookie, "Origin": origin}), 403, origin)
            act.assert_not_called()
            self.assertEqual(self.note({**cookie, "Origin": f"http://127.0.0.1:{port}"}), 200)

    def test_behind_tailscale_serve_the_https_origin_is_the_one(self):
        """`tailscale serve` keeps the browser's Host and says https in X-Forwarded-Proto."""
        cookie = {"Cookie": self.cookie_pair(), "Host": "keel.example.ts.net",
                  "X-Forwarded-Proto": "https"}
        with mock.patch.object(serve.actions, "act", return_value={}):
            self.assertEqual(self.note({**cookie, "Origin": "https://keel.example.ts.net"}), 200)
            self.assertEqual(self.note({**cookie, "Origin": "http://keel.example.ts.net"}), 403)
            self.assertEqual(self.note({**cookie, "Origin": "https://keel.example.ts.net:8443"}), 403)


class VoiceAppRenewTest(PageCase):
    def test_the_voice_app_fetches_its_shell_before_every_reconnect(self):
        """After a deck restart the old cookie is refused at the upgrade, which the page
        sees only as a closed socket; a reconnect that did not renew would loop forever."""
        from tests.voicepage import raw_script
        app = raw_script()          # every script the page loads (VP-6)
        self.assertIn("var RECONNECT_MS = 3000;", app)
        self.assertIn("setTimeout(reconnect, RECONNECT_MS)", app)
        self.assertNotIn("setTimeout(connect,", app)
        body = app.split("function reconnect()", 1)[1].split("function connect()", 1)[0]
        self.assertIn("fetch(location.pathname", body)
        self.assertIn('cache: "no-store"', body)
