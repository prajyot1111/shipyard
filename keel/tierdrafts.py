"""What came back from Bosun (c-678, the first run's Set up your repos with Bosun).

Bosun drafts each repo's CLAUDE.md with the user in its own session; the page shows what
came back as a list of files to read and Adopt. `rows(cfg, board, space)` is that list: one
row per repo the install copied into the space, and one for the workspace file when the
space has more than one (`WORKSPACE`), in that order.

A row's state is read, never stored:

| State | Read from | The page says |
|---|---|---|
| `ready` | the tier's open proposal card is at review | ready for you |
| `drafting` | that card is at planning or building | Bosun is drafting |
| `adopted` | the tier is no longer its template, and no card is being drafted or ready | adopted |
| `idle` | anything else: the tier is its template, with no card or one nobody has started | not started |

An adopted row of a repo also says whether its lines RUN (`lines`, c-678 review), from the
record of what the user adopted or saved (`keel/tierrecord.py`): `run` (the file is that
text), `changed` (it is not any more: "Adopt or save it again") or `never` (no record, a
file from before records were kept or written by hand: "Save it to turn its lines on").
None for a file that names no line, for the workspace file, and for a row not adopted.

A full row carries `text` (the draft as Adopt would write it, or the adopted file) and
`commands` (the lines Keel reads from it, with the line each came from, `keel/repofile.py`;
a repo's row only). A light row (`full=False`) carries neither, and a `stamp` instead: when
the draft or the file last changed. The state document carries the light rows on every
poll (`firstrun`'s `rules` step), and the page reads the report again when they moved.

`verdict(rows)` is what the step is done by: every REPO's file adopted. The workspace file
is not required.
"""

from __future__ import annotations

import re
from pathlib import Path

from keel import repofile, repolayout, tiercards, tierrecord
from keel.config import Config

WORKSPACE = "CLAUDE.md (workspace)"
DRAFTING = ("planning", "building")


def copied(cfg: Config, space: str) -> list[tuple[str, Path]]:
    """`(key, home)` of each repo the install copied into `space`, in the config's order."""
    found = cfg.spaces.get(space)
    layout = repolayout.spaces_of(cfg)
    if found is None or layout is None:
        return []
    homes = [(key, repolayout.home_of(path, layout)) for key, path in found.repos.items()]
    return [(key, home) for key, home in homes if home is not None]


def copied_repos(cfg: Config, space: str) -> list[tuple[str, Path]]:
    """`(key, clone)` of each repo the install copied into `space`."""
    return [(key, home / repolayout.REPO) for key, home in copied(cfg, space)]


# The one line of a draft card's notes that suggests a first card (c-678): what to do, and
# optionally what Bosun saw. The draft's brief tells Bosun the form (`tiercards.DRAFT_BRIEF`).
FIRST_CARD = re.compile(r"^\s*first card:\s*(?P<title>.+?)(?:\s*\(because\s+(?P<saw>.+?)\))?\s*$", re.IGNORECASE)
SEEN = 50


def first_card_of(text: str) -> tuple[str, str | None] | None:
    """`(what to do, what Bosun saw or None)` of a note that suggests a first card."""
    found = FIRST_CARD.match(text or "")
    return (found["title"], found["saw"]) if found else None


def suggestion(cfg: Config, board) -> dict | None:
    """The first card Bosun suggested while drafting a repo's file that is now adopted: the
    newest such note on a draft card that is done. `{space, repo, file, title, saw}`, or None.
    It is read from the board each time, so nothing about it is stored anywhere else."""
    for card in board.filed_by("human", SEEN):
        options = card.get("options") or {}
        aim = str(options.get(tiercards.OPTION) or "")
        if card.get("stage") != "done" or not options.get(tiercards.DRAFT) or "/" not in aim:
            continue
        space, key = aim.split("/", 1)
        if space not in cfg.spaces or key not in cfg.spaces[space].repos:
            continue
        for event in reversed(board.events(card["id"])):
            found = first_card_of(event.get("text") or "") if event.get("kind") == "note" else None
            if found:
                return {"space": space, "repo": key, "file": f"{key}/{repolayout.TIER}",
                        "title": found[0], "saw": found[1]}
    return None


def spaces(cfg: Config) -> list[str]:
    """The spaces with a repo the install copied."""
    return [name for name in cfg.spaces if copied(cfg, name)]


def read(path: Path) -> str | None:
    try:
        return path.read_text()
    except OSError:
        return None


def stamp_of(path: Path) -> int | None:
    try:
        return int(path.stat().st_mtime)
    except OSError:
        return None


LINES = {tierrecord.HELD: "run", tierrecord.CHANGED: "changed", tierrecord.NEVER: "never"}


def lines_of(board, tier: Path, text: str | None) -> str | None:
    """Whether an adopted repo file's lines run: `run`, `changed` or `never`; None where
    there is no board to ask, and for a file that names no line unless it CHANGED since its
    record: that one refuses its repo's landings whatever it names now
    (`repocommands.refusal`), so the row says so."""
    if board is None or text is None:
        return None
    how = tierrecord.standing(board, tier)
    if how != tierrecord.CHANGED and not any(repofile.parse(text).values()):
        return None
    return LINES[how]


def row(cfg: Config, aim: str, label: str, tier: Path, templates: list[str], open_one: dict | None,
        full: bool, repo: bool, board=None) -> dict:
    """`templates`: the texts an unwritten tier may hold (`repolayout.unwritten`)."""
    stage = (open_one or {}).get("stage")
    text = read(tier)
    written = text is not None and text.strip() not in {one.strip() for one in templates}
    # a card nobody has started changes nothing yet: a file that was adopted still is
    state = ("ready" if stage == "review" else "drafting" if stage in DRAFTING
             else "adopted" if written else "idle")
    out = {"aim": aim, "label": label, "path": str(tier), "state": state,
           "card": open_one["card"] if open_one else None,
           "lines": lines_of(board, tier, text) if repo and state == "adopted" else None}
    source = tiercards.draft_path(cfg, open_one["card"]) if state == "ready" else tier
    if state == "adopted":
        out["card"] = None          # the row is about the file; a new card shows once it is taken
    if not full:
        return dict(out, stamp=stamp_of(source) if state in ("ready", "adopted") else None)
    shown = None
    if state == "ready":
        draft = tiercards.draft(cfg, open_one["card"])
        shown = tiercards.stripped(draft) if draft.strip() else None
    elif state == "adopted":
        shown = text
    return dict(out, text=shown, commands=repofile.parse(shown) if repo and shown else None)


def rows(cfg: Config, board, space: str, full: bool = True) -> list[dict]:
    """The files of `space` Bosun drafts, each with its state. `board` None reads the tiers
    alone, so nothing is drafting or ready."""
    open_ones = tiercards.proposals(board) if board is not None else {}
    homes = copied(cfg, space)
    out = [row(cfg, f"{space}/{key}", f"{key}/{repolayout.TIER}", home / repolayout.TIER,
               repolayout.unwritten(cfg.root, "repo", space=space, key=key), open_ones.get(f"{space}/{key}"),
               full, True, board)
           for key, home in homes]
    if len(homes) > 1:
        # the workspace file: what is true across the repos, so only with more than one
        out.append(row(cfg, space, WORKSPACE, homes[0][1].parent / repolayout.TIER,
                       repolayout.unwritten(cfg.root, "space", space=space), open_ones.get(space), full, False))
    return out


def every(cfg: Config, board, full: bool = True) -> list[dict]:
    """The rows of every space with a copied repo, each naming its space."""
    return [dict(one, space=name) for name in spaces(cfg) for one in rows(cfg, board, name, full)]


def verdict(found: list[dict]) -> tuple[bool, str]:
    """Done once every repo's file is adopted; the workspace file is not required."""
    repos = [one for one in found if one["label"] != WORKSPACE]
    if not repos:
        return False, "add a repo first: Bosun drafts a CLAUDE.md for each"
    waiting = [one["label"] for one in repos if one["state"] != "adopted"]
    if waiting:
        return False, f"{', '.join(waiting)} {'is' if len(waiting) == 1 else 'are'} not adopted yet"
    return True, "every repo's CLAUDE.md is adopted"
