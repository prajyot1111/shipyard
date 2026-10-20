"""The deck's phone layer for a lavish page: one link and one script, injected.

Every lavish page he sees goes through the deck's proxy ([the deck](../docs/atlas/40-deck.md)),
which is the only place a layer can be added at all: lavish is vendored upstream, its
conversation panel has no collapse of its own, and on a phone that panel takes roughly half
the viewport away from the plan he opened.

WHAT IS INJECTED is two tags before `</head>`, pointing at files the deck serves from its
own `app/` directory under `/deck/`, a prefix lavish claims nothing under (its own routes
are `/`, `/health`, `/shutdown`, `/sdk.js`, `/chrome.css`, `/chrome-client.js`, `/api/...`,
`/session/<key>`, `/artifact/<key>/...` and `/events/<key>`). A new deck route is a name
taken away from lavish permanently, so the layer takes one prefix rather than two names.

THE INJECTION FAILS OPEN, which is the only property here that really matters: this is the
page an attended plan gets approved on, and a surface that will not load is the plan gate
going down with no way to fix it from the phone looking at it. A body that is not HTML, is
too large, is missing any element the layer manipulates, or already carries the layer comes
back untouched, byte for byte. The markers are the ELEMENTS the layer works on rather than a
version string, because a version check would refuse a lavish release that changed nothing
the layer touches. `tests/test_lavishlayer.py` holds that list against the lavish bundle the
deck actually proxies to (the copy on PATH, 0.1.48 here), so a lavish that renames one of
them fails `make test` rather than a phone.
"""

MAX_BYTES = 4 * 1024 * 1024        # a lavish page is ~40KB; an artifact inlined into one is not
HEAD = b"</head>"
MARK = b"keel-lavish-phone"        # already carrying the layer: injecting twice is not idempotent

# Served by the deck from `app/`, at a prefix lavish claims nothing under.
PREFIX = "/deck/"
FILES = {"/deck/lavish-phone.css": "lavish-phone.css",
         "/deck/lavish-phone.js": "lavish-phone.js"}

LAYER = (b'<link rel="stylesheet" href="/deck/lavish-phone.css" data-keel="keel-lavish-phone">'
         b'<script src="/deck/lavish-phone.js" defer data-keel="keel-lavish-phone"></script>')

# Every element the layer manipulates, with what it is for. It is the injection's marker
# list AND the guard test's list, so the layer cannot come to depend on something nothing
# is watching. A phrase here is matched against the vendored `chrome.css` and
# `chrome-client.js` by the test, and against the page body on every injection.
SELECTORS = {
    ".layout": "the grid the plan and the conversation panel sit in",
    ".frame": "the plan's own box, which the collapsed bar must not clip",
    ".panel": "the conversation panel the layer collapses into a bar",
    ".composer": "what the sheet holds under the conversation",
    # Deliberately absent: the panel's own scroller, which is `.chat` in lavish 0.1.36 and
    # `.panel-scroll` in 0.1.48. The layer bounds the panel's height and lets lavish's own
    # scroller do the scrolling, so it does not have to know which one this release has.
    ".pill-wrap": "one queued prompt, counted on the bar",
    "#presenceBanner": "lavish saying the agent is not listening",
    "#annotationPills": "the queued prompts",
    "#chatInput": "the message box, which the sheet holds when the agent is listening",
    "#sendActions": "Send, which travels with the message box",
}
# What the page body must contain before anything is inserted into it.
MARKERS = (HEAD, b'class="layout"', b'class="panel"', b'id="presenceBanner"',
           b'id="annotationPills"', b'id="chatInput"', b'id="sendActions"')


def is_html(content_type: str | None) -> bool:
    return "text/html" in (content_type or "").lower()


def wants(method: str, path: str, content_type: str | None) -> bool:
    """Whether this proxied answer is one the layer may be put into.

    A document, never a stream: `/events/<key>` is a channel that never ends, and reading it
    to completion would hang the request that is watching the plan.
    """
    if method not in ("GET", "HEAD"):
        return False
    if path.startswith("/events/"):
        return False
    return is_html(content_type)


def inject(body: bytes, content_type: str | None) -> bytes:
    """The page with the deck's phone layer in it, or the body unchanged on any doubt."""
    if not is_html(content_type):
        return body
    if not body or len(body) > MAX_BYTES:
        return body
    if MARK in body:
        return body
    for marker in MARKERS:
        if marker not in body:
            return body
    return body.replace(HEAD, LAYER + b"\n" + HEAD, 1)
