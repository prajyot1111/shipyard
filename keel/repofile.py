"""The lines Keel reads out of a repo's CLAUDE.md (c-678, the first-run design).

A repo's prepare command, its test command and how to run its app are not form fields: they
are lines of the file Bosun drafts with the user and the user adopts
(`<install>/spaces/<space>/<key>/CLAUDE.md`, `keel/repolayout.py`). The "Finished work lands
on" line is RETIRED (c-734): it is still parsed, only so the page can say it moves nothing
(`repocommands.lands_said`); where work lands is the card's base, else the repo's usual
branch. `parse(text)` finds each by its opening words and takes the first span in backticks
on that line:

| Key | The line begins | Example |
|---|---|---|
| `prepare` | `Prepare a fresh copy:` | ``- Prepare a fresh copy: `npm ci` `` |
| `test` | `Run the tests:` | ``- Run the tests: `npm test` (about 40 seconds)`` |
| `lands` | `Finished work lands on` | ``- Finished work lands on `main`.`` |
| `run` | `Run the app:` | ``- Run the app: `npm run dev -- --port 0` `` |

Each is `{"value", "line"}` (the line is counted from 1, for the page that shows where a
value came from) or None. A line with nothing in backticks names nothing, so the template
(`etc/claude-md/repo.md`), whose lines say what to write, reads as all None, and a repo
whose Running the app still says "tests only" has no `run`. The first line that begins
with the words counts. Bullets, bold stars and case are ignored.

A branch is held to what a branch name may be, since it reaches git as an argument; a
command is one line as written. `read(path)` is `parse` of a file, and all None when there
is none. This module only reads: whether a line may be RUN is `repocommands.lines`, which
hands them out only for the text the user adopted or saved (`keel/tierrecord.py`).
"""

from __future__ import annotations

import re
from pathlib import Path

from keel import repolayout

OPENERS = {"prepare": "prepare a fresh copy:", "test": "run the tests:", "lands": "finished work lands on",
           "run": "run the app:"}
NOTHING = {key: None for key in OPENERS}
# What each line makes Shipyard do (c-734), said to Bosun in the draft brief (`tiercards`), so
# the text it writes and the user adopts is never a switch nobody named. `lands` is read only
# to say it moves nothing (`repocommands.lands_said`).
DOES = {
    "prepare": ("Prepare a fresh copy: Shipyard runs it in every card's worktree when it is cut, and in a "
                "landing's merged tree before the tests. One that fails stops the card from starting."),
    "test": ("Run the tests: Shipyard runs it before a card goes to review, and on the merged tree before "
             "a landing. A red run lands nothing. A repo with no such line lands untested."),
    "run": ("Run the app: sessions may start the app with this command, and a card may take the "
            "browser. Until it is written, sessions run tests only."),
    "lands": ("Finished work lands on: not read, and never written. A card lands on its own base, else "
              "on the branch the repo's remote names as its default; the bases are set on How work ships."),
}
LEAD = re.compile(r"^[\s>*+\-]*(?:\d+[.)]\s*)?[*_\s]*")
TICKED = re.compile(r"`([^`\n]+)`")
BRANCH = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._/-]{0,199}$")


def value_of(key: str, rest: str) -> str | None:
    found = TICKED.search(rest)
    value = found.group(1).strip() if found else ""
    if not value or value.startswith("-"):
        return None
    if key == "lands" and not BRANCH.match(value):
        return None
    return value


def parse(text: str) -> dict:
    """`{prepare, test, lands, run}`, each `{value, line}` or None."""
    out = dict(NOTHING)
    seen = set()
    for number, line in enumerate((text or "").splitlines(), 1):
        plain = LEAD.sub("", line).replace("*", "").replace("_", " ").lower()
        for key, words in OPENERS.items():
            if key in seen or not plain.startswith(words):
                continue
            seen.add(key)
            value = value_of(key, line)
            out[key] = {"value": value, "line": number} if value else None
    return out


def read(path: Path | None) -> dict:
    try:
        return parse(Path(path).read_text()) if path is not None else dict(NOTHING)
    except OSError:
        return dict(NOTHING)


def tier_of(cfg, space: str | None, key: str | None) -> Path | None:
    """The CLAUDE.md of a repo the install copied into its layout, or None for any other."""
    found = (getattr(cfg, "spaces", None) or {}).get(space or "")
    first = str(key or "").split(",")[0].strip()
    repo = found.repos.get(first) if found is not None and first else None
    home = repolayout.home_of(repo, repolayout.spaces_of(cfg)) if repo is not None else None
    return home / repolayout.TIER if home is not None else None

