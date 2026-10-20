"""A failed copy of a repo, sorted into a kind (c-678, the first run's Add your repos).

`git clone` fails in git's words, which a new user cannot act on. `sort(url, said)` reads
those words and the address and answers what the page needs: the kind, one sentence in
plain words, git's own last line (shown as it came), and what the fix needs.

| Kind | When | The fix the page offers |
|---|---|---|
| `private` | github.com refused to say who is asking (no prompt allowed, or a failed sign-in) | connect GitHub, then try the copy again |
| `host` | the same on any other host | `needs`: what that host wants, then try again |
| `nosuch` | the host says there is no such repo, the host does not resolve, or a path is no repo | edit the address |
| `ssh` | an SSH address the host refused for want of a key ("Permission denied (publickey") | `https`: the same repo's https address, one tap |
| `hostkey` | an SSH address on a host this computer has never met ("Host key verification failed") | `https`, or connect to it once in a terminal |
| `other` | anything else | try again |

The kinds are asked in that order of certainty: a key refused, a host key, a sign-in
refused, no such repo, anything else. git ends EVERY failed SSH copy with "Could not read
from remote repository", so that line decides nothing (review F12): a mistyped repo over SSH
is `nosuch`, not a missing key.

GitHub answers "not found" for a private repo too once this computer is signed in as
somebody who cannot see it, so that one is `nosuch`: the address or the account is wrong,
and the sentence asks for the spelling to be checked.

It reads strings and nothing else: it runs no git and reaches no host. `short_name` is the
key the page fills in from an address.

An address may carry a user and a password (`https://user:token@host/...`), and neither is
ever shown (review F13): `shown_address` is the address without them (an SSH address keeps
its user, which is part of the address and no secret), `scrubbed` takes them out of a line
git printed, and `has_password` is what `onboarding.add_repo` refuses an address for.
"""

from __future__ import annotations

import re

GITHUB = "github.com"
SCP = re.compile(r"^(?:[\w.-]+@)?(?P<host>[\w.-]+):(?!//)(?P<path>.+)$")           # git@host:owner/repo.git
URL = re.compile(r"^(?P<scheme>[a-z][a-z0-9+.-]*)://(?:[^@/]*@)?(?P<host>[^/:]+)(?::\d+)?/(?P<path>.*)$", re.I)
USERINFO = re.compile(r"^(?P<scheme>[a-z][a-z0-9+.-]*)://(?P<user>[^@/:]*)(?::(?P<password>[^@/]*))?@", re.I)
# the same inside a line git printed: any `scheme://user[:password]@`, the SSH forms aside
PRINTED = re.compile(r"\b(?!ssh://)([a-z][a-z0-9+.-]*://)[^@/\s'\"]+@", re.I)
NAME = re.compile(r"[^a-z0-9_-]+")
# git's phrasings, lower case, per kind; the first kind with a match wins
NOSUCH = ("repository not found", "not found", "could not resolve host", "does not appear to be a git repository",
          "no such file or directory", "does not exist")
SSH = ("permission denied (publickey",)
HOSTKEY = ("host key verification failed",)
REFUSED = ("could not read username", "could not read password", "authentication failed", "terminal prompts disabled",
           "invalid username or password", "access denied", "http 401", "http 403", "error: 401", "error: 403")
SENTENCES = {
    "private": "GitHub did not let this computer read {slug}. Private repos need this computer to be signed in to GitHub.",
    "host": "{host} did not let this computer read that repo.",
    "nosuch": "There is no repo at that address. Check the spelling, or open it in your browser to make sure it exists.",
    "ssh": "This address uses SSH, and this computer has no SSH key that host accepts.",
    "hostkey": ("This computer has not connected to {host} over SSH before, so the copy stopped before it "
                "began. Use the https address, or connect to it once in a terminal and say yes when it asks "
                "whether to trust the host."),
    "other": "The copy failed: {git}",
}
NEEDS = "{host} needs a key or a saved password for git. Set one up, then try again."


def parts(url: str) -> tuple[str | None, str | None, str | None]:
    """`(scheme, host, path)` of an address; a plain path has none of the first two."""
    text = (url or "").strip()
    found = URL.match(text)
    if found:
        return found["scheme"].lower(), found["host"].lower(), found["path"]
    found = SCP.match(text)
    if found and "/" not in text.split(":", 1)[0]:
        return "ssh", found["host"].lower(), found["path"]
    return None, None, text or None


def shown_address(url: str | None) -> str:
    """The address as a page may show it: without the user and password of a URL. An SSH
    address keeps its user (`git@host:...`, `ssh://git@host/...`), which is no secret."""
    text = (url or "").strip()
    found = USERINFO.match(text)
    if not found or found["scheme"].lower() == "ssh" and found["password"] is None:
        return text
    return f"{found['scheme']}://{text[found.end():]}"


def has_password(url: str | None) -> bool:
    found = USERINFO.match((url or "").strip())
    return bool(found and found["password"])


def scrubbed(said: str | None) -> str:
    """A line git printed, with the user and password of any address in it taken out."""
    return PRINTED.sub(r"\1", said or "")


def host_of(url: str) -> str | None:
    return parts(url)[1]


def slug_of(url: str) -> str | None:
    """`owner/repo` of an address on a host, without `.git`."""
    scheme, host, path = parts(url)
    if host is None or not path:
        return None
    return re.sub(r"\.git/?$", "", path.strip("/")) or None


def is_ssh(url: str) -> bool:
    return parts(url)[0] == "ssh"


def https_of(url: str) -> str | None:
    """The https address of the same repo, for an SSH address; None for any other."""
    scheme, host, path = parts(url)
    if scheme != "ssh" or not host or not path:
        return None
    return f"https://{host}/{path.lstrip('/')}"


def short_name(url: str) -> str:
    """The key an address suggests: its last part, without `.git`, in the letters a key may
    have (`setupconfig.NAME`: lower case, digits, `-` and `_`, starting with a letter)."""
    path = parts(url)[2] or ""
    last = re.sub(r"\.git$", "", path.rstrip("/").rsplit("/", 1)[-1], flags=re.I).lower()
    name = NAME.sub("-", last).strip("-_")[:32]
    return name if not name or name[0].isalpha() else f"r{name}"[:32]


def last_line(said: str) -> str:
    lines = [line.strip() for line in (said or "").splitlines() if line.strip()]
    return lines[-1] if lines else ""


def shown(said: str, words: tuple) -> str:
    """git's line to show: the first that carries one of the kind's phrasings, else the last."""
    for line in (said or "").splitlines():
        if any(word in line.lower() for word in words):
            return line.strip()
    return last_line(said)


def sort(url: str, said: str) -> dict:
    """`{kind, sentence, git, host, slug, https, needs}` for a `git clone` of `url` that
    printed `said` and failed. Nothing in it carries a user or a password."""
    said, url = scrubbed(said), shown_address(url)
    lowered = said.lower()
    host, slug = host_of(url), slug_of(url)
    if is_ssh(url) and any(word in lowered for word in SSH):
        kind, git = "ssh", shown(said, SSH)
    elif is_ssh(url) and any(word in lowered for word in HOSTKEY):
        kind, git = "hostkey", shown(said, HOSTKEY)
    elif any(word in lowered for word in REFUSED):
        kind, git = ("private" if host == GITHUB else "host"), last_line(said)
    elif any(word in lowered for word in NOSUCH):
        kind, git = "nosuch", shown(said, NOSUCH)
    else:
        kind, git = "other", last_line(said) or "git gave no reason"
    sentence = SENTENCES[kind].format(slug=slug or "that repo", host=host or "That host", git=git)
    return {"kind": kind, "sentence": sentence, "git": git, "host": host, "slug": slug,
            "https": https_of(url) if kind in ("ssh", "hostkey") else None,
            "needs": NEEDS.format(host=host) if kind == "host" and host else None}
