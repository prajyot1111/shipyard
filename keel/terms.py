"""What a space calls a ticket and a change (c-630, c-628 S2).

The words a user reads for a tracker's ticket and a code host's change come from the space's
pack (`[terms]` in `pack.toml`, validated by `keel/packs.py`), laid over the neutral defaults
here: ticket, pull request (PR), the tracker, the code host. This is the one file in core
that may spell those words; `tests/nouns.py` fails on one anywhere else in `app/` or `keel/`.

- `of(cfg, space)` is a space's `Terms` (a space or its name). A space with no pack, an
  older adapter with no `pack.toml`, or a pack that does not load gets the defaults (S1's
  readiness reports the failure).
- `say(t, template)` fills `{key}`; `{Key}` capitalises the first letter, so a sentence can
  open with `{Ticket}`. In an f-string, `t["change"]` and `t["Change"]` read the same.
- `public(t)` is what the deck reads (`/api/state`'s space entry, the plan page's card), and
  `table(cfg)` every space's.
- `refs(t)` is the plan page's reference pattern for a space: cards and paths always, the
  ticket ref from `ticket_ref`, and the change ref as `<change_short> #<n>`.

It reads and never raises.
"""

from __future__ import annotations

import re
from collections.abc import Mapping

from keel import packs, planinline

KEYS = packs.TERM_KEYS
DEFAULTS = {"ticket": "ticket", "tickets": "tickets", "ticket_ref": None,
            "change": "pull request", "changes": "pull requests",
            "change_short": "PR", "changes_short": "PRs",
            "tracker_name": "the tracker", "codehost_name": "the code host",
            "ci_name": "the CI server"}
FIELD = re.compile(r"\{([A-Za-z_]+)\}")


class Terms(Mapping):
    """A space's words: the defaults with its pack's laid over them. `t["Ticket"]` is
    `t["ticket"]` with its first letter capitalised."""

    def __init__(self, words: dict | None = None):
        self._words = {**DEFAULTS, **(words or {})}

    def __getitem__(self, key: str):
        if key in self._words:
            return self._words[key]
        lower = key[:1].lower() + key[1:]
        if lower != key and isinstance(self._words.get(lower), str):
            return upper(self._words[lower])
        raise KeyError(key)

    def __iter__(self):
        return iter(self._words)

    def __len__(self) -> int:
        return len(self._words)

    def __repr__(self) -> str:
        return f"Terms({self._words!r})"


BASE = Terms()


def upper(word: str) -> str:
    return word[:1].upper() + word[1:]


def of(cfg, space) -> Terms:
    """The terms of `space` (a `Space`, or a space's name in `cfg`)."""
    if isinstance(space, str) or space is None:
        space = (getattr(cfg, "spaces", None) or {}).get(space)
    path = getattr(space, "adapter_dir", None)
    if path is None:
        return BASE
    try:
        pack = packs.at(path)
    except packs.PackError:
        return BASE
    return Terms(pack.terms) if pack is not None and pack.terms else BASE


def of_board(board, space: str | None) -> Terms:
    """What `space` calls things, as a board knows it (`Board.words`, which `open_board`
    fills from the config); a board that cannot say (a remote one) gives the defaults."""
    words = getattr(board, "words", None)
    return words(space) if callable(words) else BASE


def table(cfg) -> dict[str, Terms]:
    """Every space's terms, by name."""
    return {name: of(cfg, space) for name, space in (getattr(cfg, "spaces", None) or {}).items()}


def say(t: Mapping | None, template: str) -> str:
    """`template` with each `{key}` (or `{Key}`) filled from `t`; a field that is not a term
    is left as written, so a template can still carry its own `{...}`."""
    t = BASE if t is None else t

    def fill(match):
        try:
            value = t[match.group(1)]
        except KeyError:
            return match.group(0)
        return value if isinstance(value, str) else match.group(0)
    return FIELD.sub(fill, template)


def public(t: Mapping | None) -> dict:
    """The dict the deck reads: every key, `ticket_ref` None when nothing is linked."""
    t = BASE if t is None else t
    return {key: t[key] for key in KEYS}


def ref_pattern(t: Mapping | None) -> str | None:
    """The ticket ref as a regex body (`sc-<n>` is `sc-\\d+`), or None when the space links
    no tickets."""
    shape = (t or BASE).get("ticket_ref")
    if not shape or "<n>" not in shape:
        return None
    prefix = shape.split("<n>", 1)[0]
    return re.escape(prefix) + r"\d+"


def refs(t: Mapping | None) -> re.Pattern:
    """The plan page's reference pattern for a space (`planinline.spans(text, refs)`)."""
    t = BASE if t is None else t
    return planinline.ref_regex(ticket=ref_pattern(t),
                                change=re.escape(t["change_short"]) + r" #\d+")
