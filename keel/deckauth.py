"""Who may act through the deck as him: the deck's own page, proved by a cookie (c-451).

`POST /api/action` with no `caller` runs the verb with `state/human.token`, so the board
records it as `human`. Before this card, "no caller" was the whole test, and any process on
the machine could send one: a house with Bash could approve its own gate. The page now
proves itself with two things together.

1. **The cookie.** Each `keel serve` process mints a random key (`mint`) and sets it on the
   page's own GET of the shell (`/`, `/index.html`, `/board...`): HttpOnly, SameSite=Strict,
   Path=/, and Secure when the browser came in over https through `tailscale serve`. A
   restart mints a new one, and the page picks it up by fetching the shell again, which it
   does by itself on a refusal that says `renew` (`app/ui.core.js`, `K.post`). The name
   carries the port, because cookies ignore ports: two decks on one host (the live one and
   a worktree's) would otherwise overwrite each other's on every load.
2. **A browser's own word that it is this origin** (`browser_same_origin`):
   `Sec-Fetch-Site: same-origin`, or, from a browser too old to send that, an `Origin`
   naming this Host. `same_origin` lets a request with NEITHER through, deliberately
   (decision S5); on the human path that absence is exactly a process that is not the
   page, so here one of the two must be present.

WHAT THIS DOES NOT STOP, said plainly: a process running as the same Unix user can GET the
shell itself, read the cookie off the answer, and send both headers. The cookie closes the
one-line `curl -d` a house could be tempted into and every page in another tab; the
boundary against a determined same-user shell is a separate Unix user for the houses,
which is a later card. The houses' settings deny them `state/human.token` for the same
reason and with the same limit (`house.secret_deny`).
"""

import hmac
import secrets
import urllib.parse

COOKIE_PREFIX = "keel_deck_"
# One line, because that is all the page shows; the page acts on `renew`, not on this.
REFUSED = ("this needs the deck's own page: reload the deck (a restart gives it a new key), "
           "or use kb with KEEL_TOKEN at the desk")


def mint() -> str:
    """A new key for this process. Never written anywhere: a restart is a rotation."""
    return secrets.token_urlsafe(32)


def cookie_name(port: int) -> str:
    return f"{COOKIE_PREFIX}{port}"


def cookie_header(port: int, key: str, headers) -> str:
    """The `Set-Cookie` value for the shell's answer."""
    secure = (headers.get("X-Forwarded-Proto") or "").strip().lower() == "https"
    return (f"{cookie_name(port)}={key}; HttpOnly; SameSite=Strict; Path=/"
            + ("; Secure" if secure else ""))


def presented(headers, port: int) -> list[str]:
    """Every value the request's `Cookie` headers give this deck's cookie name."""
    name = cookie_name(port)
    found = []
    for line in headers.get_all("Cookie") or []:
        for pair in line.split(";"):
            key, sep, value = pair.strip().partition("=")
            if sep and key == name:
                found.append(value.strip())
    return found


def has_key(headers, port: int, key: str) -> bool:
    """Does the request carry this process's key, compared in constant time."""
    return bool(key) and any(hmac.compare_digest(value.encode(), key.encode())
                             for value in presented(headers, port))


def host_of(header: str | None) -> str:
    if not header:
        return ""
    if "://" not in header:
        header = "http://" + header
    return (urllib.parse.urlsplit(header).hostname or "").lower()


def same_origin(headers) -> bool:
    """Did the deck's own page send this, rather than some other page in some other tab.

    Two checks, each covering what the other cannot. `Sec-Fetch-Site` is the browser's own
    word for it and a page cannot forge it; `none` means the address was typed. `Origin` is
    the older mechanism, compared against the Host the browser itself addressed, because
    this server is the origin the browser talks to and so the only hop that can tell. It is
    `Host` and never an inbound `X-Forwarded-Host`: the voice tier drops any inbound copy of
    that header for the same reason, a client's claim about which host it reached is the
    client's claim.

    A request with NEITHER header is allowed, and that is deliberate rather than a gap.
    Browsers always send at least one, so their joint absence means a non-browser client,
    which here means curl on loopback or on the tailnet. Refusing those would break the
    selftests and any future native client while stopping nothing, since the threat being
    closed is specifically a page in his browser. The human path is the exception: it asks
    `browser_same_origin`, which requires one of the two.
    """
    site = (headers.get("Sec-Fetch-Site") or "").strip().lower()
    if site and site not in ("same-origin", "none"):
        return False
    origin = headers.get("Origin")
    return not origin or host_of(origin) == host_of(headers.get("Host"))


DEFAULT_PORTS = {"http": 80, "https": 443}


def origin_triple(origin: str) -> tuple[str, str, int] | None:
    """`(scheme, host, port)` of an `Origin`, the port made explicit; None when unreadable."""
    try:
        parts = urllib.parse.urlsplit(origin)
        port = parts.port
    except ValueError:
        return None
    scheme = (parts.scheme or "").lower()
    if scheme not in DEFAULT_PORTS or not parts.hostname:
        return None
    return scheme, parts.hostname.lower(), port or DEFAULT_PORTS[scheme]


def addressed(headers) -> tuple[str, str, int] | None:
    """`(scheme, host, port)` the browser addressed: the `Host` it sent, and https when
    `tailscale serve` says it terminated TLS (`X-Forwarded-Proto`), else http."""
    host = headers.get("Host")
    if not host:
        return None
    https = (headers.get("X-Forwarded-Proto") or "").strip().lower() == "https"
    return origin_triple(("https://" if https else "http://") + host.strip())


def exact_origin(headers) -> bool:
    """Does `Origin` name exactly the scheme, host AND port the browser addressed (review
    item 4): `host_of` alone let a page on another port of the same host through."""
    theirs, ours = origin_triple(headers.get("Origin") or ""), addressed(headers)
    return theirs is not None and theirs == ours


def browser_same_origin(headers) -> bool:
    """The human path's origin rule, stricter than `same_origin` twice over. A browser's word
    is REQUIRED: a POST or an upgrade from the page always carries `Sec-Fetch-Site:
    same-origin` (a typed `none` is never either), or at least `Origin`. And an `Origin`,
    when sent, must match scheme, host and port exactly."""
    site = (headers.get("Sec-Fetch-Site") or "").strip().lower()
    if site and site != "same-origin":
        return False
    if headers.get("Origin"):
        return exact_origin(headers)
    return bool(site)


def from_the_page(headers, port: int, key: str) -> bool:
    """The whole proof the human path asks for: this process's cookie, from this origin."""
    return has_key(headers, port, key) and browser_same_origin(headers)
