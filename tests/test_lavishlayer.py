"""The deck's phone layer for a lavish page: the injection, and the selectors it stands on.

Two halves, and the second is the one that will actually catch something.

1. The injection itself: two tags, once, into an HTML document, and nothing at all to
   anything else. It fails open on every doubt, because the page it is editing is the page
   an attended plan gets approved on.
2. A GUARD OVER LAVISH'S OWN NAMES. The layer is CSS and JavaScript written against a
   bundle nobody here controls (`lavish-axi`, 0.1.48 on this machine). A lavish release that
   renames `.panel` or `#presenceBanner` would not error anywhere: the rules would simply
   stop matching and the panel would take half his screen again, silently. The guard reads
   THE BUNDLE THE DECK ACTUALLY PROXIES TO, the copy on PATH (`vendored`, below), and fails
   by name on the selector that went missing.

   Reading the right copy is not a detail. This machine has 0.1.48 installed globally, which
   is what serves every surface, and 0.1.36 left behind in `~/.npm/_npx`. They disagree about
   the panel: 0.1.48 wraps the conversation and the queued pills in a `.panel-scroll` that
   0.1.36 has never heard of. A guard pointed at the cache would have passed while the layer
   missed the page in front of him.
"""

import re
import shutil
import unittest
from pathlib import Path

from keel import lavishlayer

ROOT = Path(__file__).resolve().parent.parent
APP = ROOT / "app"

PAGE = (b'<!doctype html>\n<html>\n<head>\n<meta charset="utf-8">\n'
        b'<link rel="stylesheet" href="/chrome.css">\n</head>\n'
        b'<body class="lavish">\n<div class="bar"></div>\n'
        b'<div class="layout"><div class="frame"><iframe id="artifact"></iframe></div>'
        b'<aside class="panel"><h2>Conversation</h2><div class="chat" id="chatLog"></div>'
        b'<div class="composer"><div class="presence-banner" id="presenceBanner" hidden>'
        b'Your agent is not listening.</div><div class="annotation-pills" id="annotationPills"></div>'
        b'<textarea id="chatInput"></textarea><div class="actions" id="sendActions">'
        b'<button id="send">Send to Agent</button></div></div></aside></div>\n'
        b'<script src="/chrome-client.js"></script>\n</body>\n</html>\n')

HTML = "text/html; charset=utf-8"


class TheInjection(unittest.TestCase):
    def test_it_adds_the_two_tags_before_the_head_closes(self):
        out = lavishlayer.inject(PAGE, HTML)
        self.assertIn(b"/deck/lavish-phone.css", out)
        self.assertIn(b"/deck/lavish-phone.js", out)
        self.assertLess(out.index(b"/deck/lavish-phone.js"), out.index(b"</head>"))

    def test_it_adds_them_exactly_once(self):
        once = lavishlayer.inject(PAGE, HTML)
        twice = lavishlayer.inject(once, HTML)
        self.assertEqual(once, twice)
        self.assertEqual(once.count(b"/deck/lavish-phone.css"), 1)
        self.assertEqual(once.count(b"/deck/lavish-phone.js"), 1)

    def test_the_rest_of_the_page_is_byte_for_byte(self):
        out = lavishlayer.inject(PAGE, HTML)
        self.assertEqual(out.replace(lavishlayer.LAYER + b"\n", b"", 1), PAGE)

    def test_json_is_left_alone(self):
        payload = b'{"ok": true, "head": "</head>"}'
        self.assertEqual(lavishlayer.inject(payload, "application/json"), payload)


    def test_the_proxy_never_even_reads_an_event_channel(self):
        """`/events/<key>` never ends, so reading it to completion would hang the request
        that is watching the plan. The content type says so too; the path says it first."""
        self.assertFalse(lavishlayer.wants("GET", "/events/abc", "text/html"))
        self.assertFalse(lavishlayer.wants("POST", "/session/abc", HTML))
        self.assertTrue(lavishlayer.wants("GET", "/session/abc", HTML))

    def test_an_oversized_body_is_left_alone(self):
        big = PAGE + b"x" * lavishlayer.MAX_BYTES
        self.assertEqual(lavishlayer.inject(big, HTML), big)

    def test_a_page_missing_an_element_the_layer_works_on_is_left_alone(self):
        """FAIL OPEN. A lavish that has moved on renders unchanged rather than half
        styled: this is the page an attended plan gets approved on."""
        for marker in (b'id="chatInput"', b'id="presenceBanner"', b'class="panel"'):
            spoiled = PAGE.replace(marker, b'id="somethingElse"')
            self.assertEqual(lavishlayer.inject(spoiled, HTML), spoiled, f"{marker!r} was not required")


def vendored() -> Path | None:
    """The lavish bundle THE DECK ACTUALLY PROXIES TO.

    `serve.LAVISH_BINARY` is what the proxy starts when lavish has gone to sleep, so the
    copy on PATH is the copy answering on `lavish_port` and the copy whose names the layer
    has to match. It is not the npx cache: this machine has `lavish-axi` 0.1.48 installed
    globally and 0.1.36 left in `~/.npm/_npx`, and they disagree about the panel's markup.
    The cache is the fallback, for a machine that only ever npx'd it.
    """
    binary = shutil.which("lavish-axi")
    if binary:
        dist = Path(binary).resolve().parent
        if (dist / "chrome.css").is_file():
            return dist
    root = Path.home() / ".npm" / "_npx"
    found = sorted(root.glob("*/node_modules/lavish-axi/dist")) if root.is_dir() else []
    return found[-1] if found else None


class TheSelectorsTheLayerStandsOn(unittest.TestCase):
    """Every name in `lavishlayer.SELECTORS` is lavish's, and this is what watches them.

    Skipped, loudly, when no lavish is installed on this machine: an absent lavish is not a
    lavish that renamed something.
    """

    def setUp(self):
        self.dist = vendored()
        if not self.dist:
            self.skipTest("no lavish-axi on PATH or under ~/.npm/_npx to hold the layer against")
        self.css = (self.dist / "chrome.css").read_text(encoding="utf-8")
        # An id may be declared in the page template rather than read by the client script
        # (`#sendActions` is markup only in 0.1.48), so the whole bundle is the haystack.
        self.bundle = "".join((self.dist / name).read_text(encoding="utf-8", errors="replace")
                              for name in ("chrome-client.js", "chrome.css", "cli.mjs")
                              if (self.dist / name).is_file())

    def test_every_class_the_layer_uses_is_still_a_rule_in_chrome_css(self):
        for selector, why in lavishlayer.SELECTORS.items():
            if not selector.startswith("."):
                continue
            pattern = r"(^|[\s,])" + re.escape(selector) + r"(?=[\s,{:.>])"
            self.assertRegex(self.css, re.compile(pattern, re.M),
                             f"lavish no longer styles {selector} ({why}); the phone layer's "
                             f"rules for it match nothing. Check app/lavish-phone.css.")

    def test_every_id_the_layer_uses_is_still_in_the_lavish_bundle(self):
        for selector, why in lavishlayer.SELECTORS.items():
            if not selector.startswith("#"):
                continue
            name = selector[1:]
            self.assertIn(f'"{name}"', self.bundle,
                          f"lavish no longer knows {selector} ({why}); the phone layer reads it "
                          "by that id. Check app/lavish-phone.js.")

    def test_every_marker_the_injection_requires_is_still_in_the_page_lavish_serves(self):
        """The injection refuses a page missing any of them, so a rename here is not a broken
        layer, it is no layer at all, silently."""
        for marker in lavishlayer.MARKERS:
            if marker == lavishlayer.HEAD:
                continue
            text = marker.decode()
            self.assertIn(text, self.bundle,
                          f'lavish no longer writes {text} into the page; the injection will '
                          "now refuse every lavish page. Check keel/lavishlayer.py MARKERS.")

    def test_the_layer_still_uses_every_selector_it_declares(self):
        """The list is the injection's markers AND this guard's subject, so a selector that
        left the layer must leave the list with it, or the guard watches nothing."""
        text = (APP / "lavish-phone.css").read_text(encoding="utf-8") + (APP / "lavish-phone.js").read_text(encoding="utf-8")
        for selector in lavishlayer.SELECTORS:
            body = selector[1:]
            self.assertIn(body, text, f"{selector} is declared in SELECTORS but the layer never uses it")


class WhatTheDeckServes(unittest.TestCase):
    def test_both_files_exist_where_the_injected_tags_point(self):
        for route, name in lavishlayer.FILES.items():
            self.assertTrue(route.startswith(lavishlayer.PREFIX), f"{route} is outside the layer's prefix")
            self.assertTrue((APP / name).is_file(), f"{route} points at app/{name}, which is not there")


    def test_the_proxy_relays_lavish_s_cors_headers(self):
        """The artifact is a SANDBOXED iframe with no `allow-same-origin`, so its origin is
        `null` and every font it fetches from lavish is a cross origin request. Lavish sends
        `access-control-allow-origin: *` for it; while the proxy ate that header the fonts
        failed, lavish's layout gate never lifted, and a whiteboard plan opened through the
        deck said "Checking layout. One moment." instead of being the plan."""
        from keel import serve
        for header in ("access-control-allow-origin", "access-control-allow-headers",
                       "access-control-allow-methods", "access-control-expose-headers", "vary"):
            self.assertIn(header, serve.PASS_RESPONSE, f"the lavish proxy drops {header}")


if __name__ == "__main__":
    unittest.main()
