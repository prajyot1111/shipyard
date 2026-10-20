"""The deck acts as him only for its own page (card c-451).

Before this, any process on the machine could POST `/api/action` with no `caller` and the
deck ran the verb as the HUMAN with `state/human.token`, so a house with Bash could approve
its own gate. The page now proves itself with a cookie this process minted and set on the
page's own GET of the shell, and the human path needs it together with a browser's own
same-origin word. A remote `kb` keeps its caller path, and that path never reaches the
verbs only the page may send.
"""

import json
import shutil
import subprocess
import unittest
import urllib.error
import urllib.request
from pathlib import Path
from unittest import mock

from keel import deckauth, deckstate, serve
from tests.test_serve import ServerCase

ROOT = Path(__file__).resolve().parent.parent
# The five the card names, and the other verbs only the page may send.
HUMAN_VERBS = [
    {"verb": "approve", "id": "c-1", "gate": "plan"},
    {"verb": "stage", "id": "c-1", "stage": "done"},
    {"verb": "unblock", "id": "c-1"},
    {"verb": "relay", "id": "c-1", "what": "resume", "to": "box"},
    {"verb": "set", "id": "c-1", "fields": {"title": "mine now"}},
    {"verb": "sendback", "id": "c-1", "said": "again"},
    {"verb": "house.stop", "id": "c-1"},
    {"verb": "house.resume", "id": "c-1"},
    {"verb": "restart"},
]


class PageCase(ServerCase):
    """A client that can be the page (the cookie from `/`, a same-origin browser) or not.

    `restart` is stubbed for every test here: a `restart` that got through would exec the
    test process itself."""

    def setUp(self):
        super().setUp()
        patch = mock.patch.object(serve, "restart_process")
        self.restarted = patch.start()
        self.addCleanup(patch.stop)

    def page_cookie(self, headers=None) -> str:
        request = urllib.request.Request(self.base + "/", headers=headers or {})
        with urllib.request.urlopen(request, timeout=10) as response:
            response.read()
            return response.headers.get("Set-Cookie") or ""

    def cookie_pair(self) -> str:
        return self.page_cookie().split(";", 1)[0]

    def browser(self, cookie: str | None) -> dict:
        headers = {"Origin": self.base, "Sec-Fetch-Site": "same-origin"}
        if cookie:
            headers["Cookie"] = cookie
        return headers

    def post(self, path: str, body, headers: dict | None = None,
             ctype: str = "application/json") -> tuple[int, dict]:
        data = body if isinstance(body, bytes) else json.dumps(body).encode()
        request = urllib.request.Request(self.base + path, data=data, method="POST")
        request.add_header("Content-Type", ctype)
        for name, value in (headers or {}).items():
            request.add_header(name, value)
        try:
            with urllib.request.urlopen(request, timeout=30) as response:
                return response.status, json.loads(response.read())
        except urllib.error.HTTPError as error:
            with error:
                raw = error.read()
            try:
                return error.code, json.loads(raw)
            except ValueError:
                return error.code, {"raw": raw.decode(errors="replace")}


class TheCookieTest(PageCase):
    def test_the_shell_sets_a_strict_http_only_cookie_for_the_whole_origin(self):
        cookie = self.page_cookie()
        name, _, rest = cookie.partition("=")
        self.assertEqual(name, deckauth.cookie_name(self.server.server_address[1]))
        flags = [part.strip().lower() for part in rest.split(";")[1:]]
        self.assertIn("httponly", flags)
        self.assertIn("samesite=strict", flags)
        self.assertIn("path=/", flags)
        self.assertNotIn("secure", flags, "plain http on loopback: a Secure cookie would be dropped")

    def test_it_is_secure_when_the_browser_came_in_over_https(self):
        """`tailscale serve` terminates TLS and says so in `X-Forwarded-Proto`."""
        flags = [part.strip().lower() for part in
                 self.page_cookie({"X-Forwarded-Proto": "https"}).split(";")[1:]]
        self.assertIn("secure", flags)

    def test_the_board_route_is_the_shell_too_and_sets_it(self):
        request = urllib.request.Request(self.base + "/board/b-001?view=outline")
        with urllib.request.urlopen(request, timeout=10) as response:
            response.read()
            self.assertTrue((response.headers.get("Set-Cookie") or "").startswith("keel_deck_"))

    def test_a_script_or_a_read_is_not_handed_the_cookie(self):
        for path in ("/ui.js", "/api/state", "/api/health"):
            with mock.patch.object(deckstate.harness, "agents_across", return_value=self.rows()):
                with urllib.request.urlopen(self.base + path, timeout=10) as response:
                    response.read()
                    self.assertIsNone(response.headers.get("Set-Cookie"), path)

    def test_every_process_mints_its_own_so_a_restart_rotates_it(self):
        other = serve.make_server(self.cfg, port=0)
        try:
            self.assertNotEqual(other.RequestHandlerClass.page_key,
                                self.server.RequestHandlerClass.page_key)
        finally:
            other.server_close()


class TheHumanPathTest(PageCase):
    def test_a_post_without_the_cookie_is_refused_whatever_the_verb(self):
        with mock.patch.object(serve.actions, "act") as act:
            for body in HUMAN_VERBS:
                for caller in ({}, {"caller": None}):
                    status, answer = self.post("/api/action", {**body, **caller}, self.browser(None))
                    self.assertEqual(status, 403, (body, answer))
                    self.assertFalse(answer["ok"])
                    self.assertEqual(len(answer["error"].splitlines()), 1)
                    self.assertTrue(answer.get("renew"), "the page is told it may fetch a new one")
        act.assert_not_called()

    def test_curl_with_no_headers_at_all_is_refused_too(self):
        """The joint absence of Origin and Sec-Fetch-Site is what `same_origin` lets
        through; on the human path it is exactly a process that is not the page."""
        with mock.patch.object(serve.actions, "act") as act:
            status, _ = self.post("/api/action", {"verb": "unblock", "id": self.blocked})
            self.assertEqual(status, 403)
            status, _ = self.post("/api/action", {"verb": "unblock", "id": self.blocked},
                                  {"Cookie": self.cookie_pair()})
            self.assertEqual(status, 403, "a cookie with no browser word is not the page")
        act.assert_not_called()

    def test_a_wrong_or_stale_cookie_is_refused(self):
        name = deckauth.cookie_name(self.server.server_address[1])
        with mock.patch.object(serve.actions, "act") as act:
            for cookie in (f"{name}=not-it", f"{name}=", "keel_deck_1=" + "x" * 43, "other=1"):
                status, answer = self.post("/api/action", {"verb": "unblock", "id": self.blocked},
                                           self.browser(cookie))
                self.assertEqual(status, 403, cookie)
                self.assertTrue(answer.get("renew"))
        act.assert_not_called()

    def test_another_site_is_refused_even_carrying_the_cookie(self):
        cookie = self.cookie_pair()
        with mock.patch.object(serve.actions, "act") as act:
            for headers in ({"Origin": "http://evil.test"}, {"Sec-Fetch-Site": "cross-site"},
                            {"Sec-Fetch-Site": "same-site"}, {"Sec-Fetch-Site": "none"}):
                status, _ = self.post("/api/action", {"verb": "unblock", "id": self.blocked},
                                      {"Cookie": cookie, **headers})
                self.assertEqual(status, 403, headers)
        act.assert_not_called()

    def test_with_the_pages_cookie_the_tap_is_his(self):
        headers = self.browser(self.cookie_pair())
        with mock.patch.object(deckstate.harness, "agents_across", return_value=self.rows()):
            status, answer = self.post("/api/action", {"verb": "note", "id": self.inbox,
                                                       "text": "from the page"}, headers)
            self.assertEqual(status, 200, answer)
            status, answer = self.post("/api/action", {"verb": "unblock", "id": self.blocked}, headers)
            self.assertEqual(status, 200, answer)
        event = self.board.events(self.inbox)[-1]
        self.assertEqual((event["actor"], event["text"]), ("human", "from the page"))
        self.assertIsNone(self.board.get(self.blocked)["blocked_reason"])

    def test_a_browser_that_sends_only_origin_is_still_the_page(self):
        """An older browser with no `Sec-Fetch-Site` still sends `Origin` on every POST."""
        headers = {"Cookie": self.cookie_pair(), "Origin": self.base}
        status, answer = self.post("/api/action", {"verb": "note", "id": self.inbox, "text": "old"},
                                   headers)
        self.assertEqual(status, 200, answer)

    def test_the_boards_drop_and_ask_need_the_page_as_well(self):
        png = b"\x89PNG\r\n\x1a\n" + b"\0" * 16
        with mock.patch.object(serve.boards, "inbox") as inbox, \
                mock.patch.object(serve.boardask, "start") as start:
            status, answer = self.post("/api/board/b-001/inbox?name=x.png", png,
                                       self.browser(None), ctype="image/png")
            self.assertEqual(status, 403, answer)
            status, answer = self.post("/api/board/b-001/ask", {"text": "why"}, self.browser(None))
            self.assertEqual(status, 403, answer)
        inbox.assert_not_called()
        start.assert_not_called()


class TheCallerPathTest(PageCase):
    def test_a_body_with_a_caller_is_refused_whatever_its_verb(self):
        """c-622: a `caller` was a kb in HTTP mode on another machine. Nothing sends one now,
        so the field is no way round the cookie: refused, and nothing is acted on."""
        with mock.patch.object(serve.actions, "act") as act:
            for body in [{"verb": "note", "id": self.inbox, "text": "x"}, {"verb": "show", "id": self.inbox},
                         {"verb": "house.stop", "id": self.live}, {"verb": "dropin", "id": self.live},
                         {"verb": "approve", "id": self.gate, "gate": "plan"}, {"verb": "restart"}]:
                for caller in ({"actor": "house", "card": self.live}, {"actor": "cli"},
                               {"actor": "human", "token": self.token}, {}):
                    status, answer = self.post("/api/action", {**body, "caller": caller})
                    self.assertEqual(status, 409, (body, caller, answer))
                    self.assertIn("one machine", answer["error"])
        act.assert_not_called()


class TheOtherDoorsTest(PageCase):
    """The segments' drop box, the lavish proxy and the voice tier keep their own guards;
    the cookie is only where a POST acts as him."""

    def test_a_segment_drop_is_still_taken_same_origin_with_no_cookie(self):
        (self.cfg.segments_dir / "alpha" / "data").mkdir(parents=True, exist_ok=True)
        status, answer = self.post("/segments/alpha/decisions", {"decisions": []},
                                   self.browser(None))
        self.assertNotEqual(status, 403, answer)
        status, _ = self.post("/segments/alpha/decisions", {"decisions": []},
                              {"Origin": "http://evil.test"})
        self.assertEqual(status, 403, "its own origin rule is unchanged")

    def test_the_lavish_proxy_and_the_voice_tier_are_not_asked_for_it(self):
        status, answer = self.post("/some-lavish-route", {"x": 1}, self.browser(None))
        self.assertEqual(status, 503, answer)
        with mock.patch.object(self.cfg, "voice_port", 1):
            status, answer = self.post("/voice/api/anything", {"x": 1}, self.browser(None))
        self.assertNotEqual(status, 403, answer)

@unittest.skipUnless(shutil.which("node"), "node is not on this machine")
class ThePageTest(unittest.TestCase):
    """The page's own half, under node (`tests/fixtures/deck-auth.js`): its POSTs go with
    the browser's default credentials, and a refusal that says `renew` fetches the shell
    once and tries again."""

    def test_the_page_posts_with_its_cookie_and_renews_it_once(self):
        result = subprocess.run(
            ["node", str(ROOT / "tests" / "fixtures" / "deck-auth.js"), str(ROOT / "app")],
            capture_output=True, text=True, timeout=60)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(result.stdout), {"ok": True}, result.stdout)

    def test_every_post_the_page_makes_goes_through_the_one_helper(self):
        """A POST written as a bare `fetch` would not renew, and would fail after every
        restart until he reloaded."""
        offenders = []
        for path in sorted((ROOT / "app").glob("ui*.js")):
            text = path.read_text()
            at = text.find("method: 'POST'")
            while at >= 0:
                before = text[max(0, at - 300):at]
                if before.rfind("fetch(") > before.rfind("post("):
                    offenders.append(f"{path.name}:{text.count(chr(10), 0, at) + 1}")
                at = text.find("method: 'POST'", at + 1)
        self.assertEqual(offenders, [], "a POST that is not K.post")


if __name__ == "__main__":
    unittest.main()
