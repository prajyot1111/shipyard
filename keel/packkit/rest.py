"""A transport for a host reached through its HTTP API, with the sign-in git keeps for its
address: the standard library only, nothing to install.

`Rest(name, prefix)` makes one call at a time to `<base>/<prefix>/<path>`: a clock on it,
never a prompt, never a redirect followed (the sign-in was asked for one address and goes to
no other), its answer read as JSON, or as text when asked (a diff). The sign-in is git's own: `git credential fill` for the
address, which answers from whatever helper the user's git is set up with. It is asked for
when a request needs it, kept in this process's memory for the length of the verb, and
never written, printed or logged; it is never handed back to git either, so nothing here
can change what the helper keeps.

A call that fails is the kit's error (`errors.py`) whose message is ONE sentence: what was
asked and the host's own words. git not installed is `Missing`; no sign-in the host accepts
(or an HTTP 401) is `SignedOut`; a 404 is `NotFound`; anything else is a `HostError` whose
`status` is the HTTP status when there was one and whose `said` is the host's own words, so
a layer may read more into it (Gitea's layer reads a token's missing scope there). The
host's words are never trusted to leave the sign-in out: every password this transport holds
is taken out of them first, with the kit's own mark (`cli.hidden`, r2.F4).

The Gitea pack's layer (`packs/gitea/gt_layer.py`) is on it.
"""

import base64
import json
import os
import re
import subprocess
import urllib.error
import urllib.request
from urllib.parse import quote, urlencode, urlsplit

from keel.packkit.cli import hidden
from keel.packkit.errors import HostError, Missing, NotFound, SignedOut

SECONDS = 30            # one call's clock; a verb makes a handful, each inside the engine's own
CREDENTIAL_SECONDS = 10
SENTENCE_MAX = 240
PAGE = 50               # rows a page
PAGES_MAX = 40          # 2,000 rows of one listing: past that it is refused, never read as whole
ANSI = re.compile(r"\x1b\[[0-9;?]*[A-Za-z]")
MISSING = "git is not installed on this machine, so there is no sign-in to ask for and nothing can be asked of {name}"
SIGNED_OUT = ("git has no sign-in for {host} that {name} accepts: fetch or push once in a terminal so git asks "
              "for it and keeps it, then try again")


class NoRedirect(urllib.request.HTTPRedirectHandler):
    """A redirect is never followed: the sign-in was asked for one address and goes to no other."""

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


OPENER = urllib.request.build_opener(NoRedirect)


def sentence(text: str) -> str:
    """The host's (or git's) own message as one plain sentence: the first line that says
    something, without colour, a leading mark or `error:`, cut to a line's length."""
    lines = [ANSI.sub("", line).strip() for line in str(text or "").splitlines()]
    kept = [line for line in lines if line]
    said = re.sub(r"^(?:X |! |[Ee]rror: |[Ff]atal: |remote: )+", "", kept[0] if kept else "")
    said = re.sub(r"\s+", " ", said).strip().rstrip(".")
    if len(said) > SENTENCE_MAX:
        said = said[:SENTENCE_MAX].rsplit(" ", 1)[0] + " [cut]"
    return said or "it gave no reason"


def host_of(base: str) -> str:
    """`host[:port]` of an address, as a person reads it: never a user name or a password."""
    parts = urlsplit(base)
    return parts.netloc.rsplit("@", 1)[-1] or base


def part(name: str) -> str:
    """One part of a path (a branch may hold `/`, which is read as written)."""
    return quote(str(name), safe="/")


def said_by(raw: bytes) -> str:
    """The host's own words in an error answer: its `message`, else the body's first line."""
    text = raw.decode("utf-8", "replace")
    try:
        found = json.loads(text)
    except ValueError:
        return "" if "<html" in text.lower() else text
    return str(found.get("message") or "") if isinstance(found, dict) else ""


def failure(kind, text: str, status: int | None = None, said: str = "") -> HostError:
    made = kind(text)
    made.status, made.said = status, said
    return made


class Rest:
    """One host's API: `name` is every sentence's word for it, `prefix` where its API is."""

    def __init__(self, name: str, prefix: str = "api/v1"):
        self.name, self.prefix = name, prefix.strip("/")
        self.credentials: dict[str, tuple[str, str]] = {}      # per address, for this process only

    def forget(self) -> None:
        self.credentials.clear()

    # ----- the sign-in, from git -----

    def credential(self, base: str, cwd=None) -> tuple[str, str]:
        """The user name and password (or token) git keeps for this address, asked of git's
        own credential helpers and kept only in memory. git is told never to prompt, so an
        address it keeps nothing for is `SignedOut`, never a question nobody is there for."""
        if base in self.credentials:
            return self.credentials[base]
        parts = urlsplit(base)
        asked = f"protocol={parts.scheme}\nhost={parts.netloc.rsplit('@', 1)[-1]}\n"
        if parts.path.strip("/"):
            asked += f"path={parts.path.strip('/')}\n"
        env = {key: value for key, value in os.environ.items() if key not in ("GIT_ASKPASS", "SSH_ASKPASS")}
        env["GIT_TERMINAL_PROMPT"] = "0"
        where = ["-C", str(cwd)] if cwd else []
        try:
            done = subprocess.run(["git", *where, "-c", "core.askPass=", "credential", "fill"], input=asked + "\n",
                                  capture_output=True, text=True, timeout=CREDENTIAL_SECONDS, env=env)
        except FileNotFoundError:
            raise Missing(MISSING.format(name=self.name)) from None
        except subprocess.TimeoutExpired:
            raise HostError(f"git gave no answer in {CREDENTIAL_SECONDS} seconds when asked for the sign-in "
                            f"for {host_of(base)}; try again") from None
        except OSError as error:
            raise HostError(f"git could not be run: {error.strerror or error}") from None
        found = dict(line.split("=", 1) for line in done.stdout.splitlines() if "=" in line)
        if done.returncode != 0 or not found.get("password"):
            raise SignedOut(SIGNED_OUT.format(host=host_of(base), name=self.name))
        self.credentials[base] = (found.get("username") or "", found["password"])
        return self.credentials[base]

    def without_secrets(self, text: str) -> str:
        """`text` with every password this transport holds taken out."""
        return hidden(text, [password for _, password in self.credentials.values()])

    def authorization(self, base: str, cwd=None) -> str:
        user, password = self.credential(base, cwd)
        return "Basic " + base64.b64encode(f"{user}:{password}".encode()).decode()

    # ----- one request -----

    def call(self, base: str, method: str, path: str, body=None, query: dict | None = None,
             timeout: float = SECONDS, cwd=None, text: bool = False):
        """One request to `<base>/<prefix>/<path>` as the signed-in account: its JSON answer,
        or None when the host sends no body (with `text`, its answer as text, a diff). `body`
        is sent as JSON."""
        url = f"{base.rstrip('/')}/{self.prefix}/{path.strip('/')}" + (f"?{urlencode(query)}" if query else "")
        headers = {"Authorization": self.authorization(base, cwd),
                   "Accept": "text/plain" if text else "application/json"}
        data = None
        if body is not None:
            data, headers["Content-Type"] = json.dumps(body).encode(), "application/json"
        what, host = f"{method} {path.split('?', 1)[0].strip('/')}", host_of(base)
        slow = HostError(f"{what} gave no answer in {timeout:g} seconds: {self.name} may be slow or out of "
                         f"reach, so try again")
        try:
            with OPENER.open(urllib.request.Request(url, data=data, headers=headers, method=method),
                             timeout=timeout) as answer:
                raw = answer.read()
        except urllib.error.HTTPError as error:
            with error:
                said = sentence(self.without_secrets(said_by(error.read() or b"")))
            raise self.refused(what, host, error.code, said) from None
        except TimeoutError:
            raise slow from None
        except (urllib.error.URLError, OSError) as error:
            why = getattr(error, "reason", None) or error
            if isinstance(why, TimeoutError) or "timed out" in str(why):
                raise slow from None
            raise HostError(f"{what} could not reach {self.name} at {host}: "
                            f"{sentence(self.without_secrets(str(why)))}") from None
        if text:
            return raw.decode("utf-8", "replace")
        if not raw.strip():
            return None
        try:
            return json.loads(raw)
        except ValueError:
            raise HostError(f"{what} answered something that is not JSON: is {host} a {self.name}?") from None

    def refused(self, what: str, host: str, status: int, said: str) -> HostError:
        if status == 401:
            return failure(SignedOut, SIGNED_OUT.format(host=host, name=self.name), status, said)
        if 300 <= status < 400:
            return failure(HostError, f"{what} was answered with a redirect, which is not followed: is {host} "
                                      f"the address {self.name} is served at?", status, said)
        return failure(NotFound if status == 404 else HostError, f"{what} failed (HTTP {status}): {said}", status, said)

    def get(self, base: str, path: str, **kwargs):
        return self.call(base, "GET", path, **kwargs)

    def rows(self, base: str, path: str, **kwargs) -> list[dict]:
        """A listing the host answers whole (it takes no page)."""
        found = self.get(base, path, **kwargs)
        return [row for row in found if isinstance(row, dict)] if isinstance(found, list) else []

    def pages(self, base: str, path: str, query: dict | None = None, **kwargs) -> list[dict]:
        """Every row of a paged listing, read to the end. A listing that does not end within
        `PAGES_MAX` pages is refused, never read as whole. A page of rows all seen before ends
        it too: an address that ignores the page would otherwise be read for ever."""
        out, seen = [], set()
        for page in range(1, PAGES_MAX + 1):
            found = self.rows(base, path, query={**(query or {}), "page": page, "limit": PAGE}, **kwargs)
            fresh = [row for row in found if row.get("id") is None or row.get("id") not in seen]
            seen |= {row.get("id") for row in found}
            out += fresh
            if len(found) < PAGE or not fresh:
                return out
        raise HostError(f"GET {path.strip('/')} has more rows than can be read ({PAGES_MAX * PAGE})")
