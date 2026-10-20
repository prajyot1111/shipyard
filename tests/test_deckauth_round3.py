"""Lane I, round 3 (c-451): the paths a verifier found after the lane merged.

1. Every lavish `/artifact/<key>/...` reply and every `/host/<name>/...` reply the deck
   proxies is served sandboxed (html, svg, xml) and never sniffed, error answers included.
2. A segment's data files are served the same way.
3. No test suite, git call or ask the deck's children run inherits his token.

The review's other two items (a machine key on `push` and `segment`, a deck key into the
voice gateway) were not built, by his threat model: decision I-15.
"""

import json
import os
import threading
import unittest
import urllib.error
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from unittest import mock

from keel import artifacts, boardask, childenv, segments
from tests.test_deckauth import PageCase

ROOT = Path(__file__).resolve().parent.parent


class FakeLavish(BaseHTTPRequestHandler):
    """HTML for `.html` paths and the session page, a 404 page for `missing`, JSON else."""

    def log_message(self, *args):
        return

    def do_GET(self):
        path = self.path.split("?", 1)[0]
        if "missing" in path:
            body, kind, status = b"<script>alert(1)</script>not here", "text/html", 404
        elif path.endswith(".svg"):
            body, kind, status = b"<svg xmlns='http://www.w3.org/2000/svg'/>", "image/svg+xml", 200
        elif path.endswith(".html") or path.startswith("/session/"):
            body, kind, status = b"<html><head></head><body>page</body></html>", "text/html", 200
        else:
            body, kind, status = json.dumps({"path": path}).encode(), "application/json", 200
        self.send_response(status)
        self.send_header("Content-Type", kind)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


class ProxiedPagesTest(PageCase):
    def setUp(self):
        super().setUp()
        self.lavish = ThreadingHTTPServer(("127.0.0.1", 0), FakeLavish)
        threading.Thread(target=self.lavish.serve_forever, daemon=True).start()
        self.addCleanup(self.lavish.server_close)
        self.addCleanup(self.lavish.shutdown)
        self.cfg.lavish_port = self.lavish.server_address[1]

    def headers(self, path: str) -> tuple[int, dict]:
        try:
            with urllib.request.urlopen(self.base + path, timeout=10) as response:
                response.read()
                return response.status, {k.lower(): v for k, v in response.headers.items()}
        except urllib.error.HTTPError as error:
            with error:
                error.read()
                return error.code, {k.lower(): v for k, v in error.headers.items()}

    def test_a_lavish_artifact_opened_as_a_whole_page_is_sandboxed(self):
        """The plan lavish renders in its own sandboxed frame is a URL too, and opened by
        itself it ran in the deck's origin with his cookie."""
        for path in ("/artifact/k1/index.html", "/artifact/k1/shape.svg"):
            status, got = self.headers(path)
            self.assertEqual(status, 200, path)
            self.assertEqual(got.get("content-security-policy"), artifacts.SANDBOX, path)
            self.assertNotIn("allow-same-origin", got["content-security-policy"])
            self.assertEqual(got.get("x-content-type-options"), "nosniff", path)

    def test_an_error_page_from_lavish_is_sandboxed_too(self):
        status, got = self.headers("/artifact/k1/missing.html")
        self.assertEqual(status, 404)
        self.assertEqual(got.get("content-security-policy"), artifacts.SANDBOX)
        self.assertEqual(got.get("x-content-type-options"), "nosniff")

    def test_every_artifact_answer_is_never_sniffed(self):
        status, got = self.headers("/artifact/k1/data.json")
        self.assertEqual((status, got.get("x-content-type-options")), (200, "nosniff"))
        self.assertNotIn("content-security-policy", got)

    def test_lavish_own_page_keeps_its_origin_and_its_phone_layer(self):
        """The session page is lavish's own code and talks to lavish same-origin; the
        sandbox is for what a house wrote, never for it."""
        status, got = self.headers("/session/k1")
        self.assertEqual(status, 200)
        self.assertNotIn("content-security-policy", got)


class SegmentDataTest(PageCase):
    def test_a_segments_data_file_is_sandboxed_and_never_sniffed(self):
        data = self.cfg.segments_dir / "alpha" / "data"
        data.mkdir(parents=True, exist_ok=True)
        (data / "page.html").write_text("<script>fetch('/api/action')</script>")
        (data / "pic.svg").write_text("<svg xmlns='http://www.w3.org/2000/svg'/>")
        (data / "daybook.json").write_text("{}")
        for name, sandboxed in (("page.html", True), ("pic.svg", True), ("daybook.json", False)):
            reply = segments.get(self.cfg, f"/segments/alpha/data/{name}")
            self.assertEqual(reply.status, 200, name)
            with urllib.request.urlopen(f"{self.base}/segments/alpha/data/{name}", timeout=10) as response:
                response.read()
                self.assertEqual(response.headers.get("X-Content-Type-Options"), "nosniff", name)
                self.assertEqual(response.headers.get("Content-Security-Policy"),
                                 artifacts.SANDBOX if sandboxed else None, name)


class NoTokenInChildrenTest(unittest.TestCase):
    def test_the_helper_drops_what_no_child_may_inherit(self):
        with mock.patch.dict(os.environ, {"KEEL_TOKEN": "his", "KEEL_LIVE_STATE": "1", "KEEP": "x"}):
            env = childenv.own_env()
        self.assertNotIn("KEEL_TOKEN", env)
        self.assertNotIn("KEEL_LIVE_STATE", env)
        self.assertEqual(env["KEEP"], "x")

    def test_a_boards_ask_does_not_inherit_his_token(self):
        with mock.patch.dict(os.environ, {"KEEL_TOKEN": "his-token-value"}):
            code, out, _ = boardask.run_ask(["env"], 10)
        self.assertEqual(code, 0)
        self.assertNotIn("his-token-value", out)

    def test_the_talker_and_the_voice_children_build_their_env_through_the_helper(self):
        for path in ("keel/talker.py", "voice/harbor_voice/harborlive.py", "voice/harbor_voice/harbormsg.py"):
            text = (ROOT / path).read_text()
            self.assertNotIn("{**os.environ", text, path)
            self.assertNotIn("dict(os.environ)", text, path)
            self.assertIn("own_env(", text, path)


if __name__ == "__main__":
    unittest.main()
