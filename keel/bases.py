"""Which branches work starts from: a space's bases (c-732).

A team often cuts work from more than one branch (main and staging, say). A card's own base
(`options.base`) was already the engine's: the house cuts from it, its change is taken
against it (`house.target_of`), and a flow move may name the bases it fits (`flows.based`).
Only a pack could offer the choice on the card form, and setup never asked. Now:

- How work ships asks "Where does work start?" with the repo's default branch filled in,
  and the answer is the space's `bases` (`[spaces.<name>] bases`, a setting, `keel/settings.py`).
- `of(space)` is the one list every reader takes: the pack's own base select's options
  first (the work pack's), else the space's own, else none.
- `row(space, entries)` puts Base branch on the card form, a select of the bases with no
  default (empty is the repo's own rule, r1.F7) where a branch the list does not name may be
  typed (`typed`, r1.F2) (`cardspec.sheet`). A pack that declares its own base select keeps it
  exactly as declared (r1.F1); a pack's free-text base field takes the space's bases as its
  choices, still typed into (c-734). A space that names none keeps the form it had.
- `said(cfg, space)` is the sentence both drafts carry (the flow draft, `flowcards`, and the
  provider draft, `packdraft`), so Bosun reads the same list in each.
- `ASKS` are How work ships' questions, in the order the page shows them and Bosun asks them.
"""

from __future__ import annotations

import json
import subprocess

KEY = "base"
BLANK = "the repo's usual branch"        # what the card form says for no base (r1.F7)
# r2.F2: where a card that names no base goes; there is no default base
USUAL = ("A card that names none starts from, and lands on, its repo's usual branch (its integration "
         "branch, else the branch the repo's remote names as its default for a repo Shipyard copied, "
         "else the branch its checkout has out). Never write where work lands into a CLAUDE.md: "
         "Shipyard does not read it.")

# How work ships, one question at a time (c-732). `where` is who it is answered with: the
# page (it is stored as it is) or Bosun's session (it becomes a drawing, which takes a
# conversation). The page and Bosun's brief both read this list.
ASKS = (
    {"id": "starts", "ask": "Where does work start?", "where": "page",
     "example": "main, and staging for work that goes out with the next release"},
    {"id": "lands", "ask": "Which branch does finished work go back into?", "where": "bosun",
     "example": "back into the branch it started from"},
    {"id": "approves", "ask": "Who says it is good?", "where": "bosun",
     "example": "I approve it here, then a teammate reviews it before it is merged"},
    {"id": "after", "ask": "What happens after that?", "where": "bosun",
     "example": "staging is merged into main every Friday"},
    {"id": "live", "ask": "When do people see it live?", "where": "bosun",
     "example": "when main is deployed, which a teammate does by hand"},
)


def branch_problem(name: str) -> str | None:
    """Why `name` is not a branch name, or None: git's own rule (`git check-ref-format
    --branch`), run where no repository is, so nothing like `@{-1}` is read as another
    branch. The ONE rule (r1.F12) for the setting, a card's base at create and at the cut: a
    name git would read as a revision (`main~1`) is refused, never resolved."""
    name = str(name)
    try:
        done = subprocess.run(["git", "check-ref-format", "--branch", name], capture_output=True, text=True,
                              cwd="/", timeout=10)
    except (OSError, subprocess.SubprocessError) as error:
        return f"{name!r} could not be checked as a branch name ({error})"
    if done.returncode != 0 or done.stdout.strip() != name:
        return f"{name!r} is not a branch name git takes (a branch has no spaces, and none of ~ ^ : ? * [)"
    return None


def bases_rule(value) -> None:
    """A space's bases: branch names git takes, each once."""
    for name in value:
        problem = branch_problem(name)
        if problem:
            raise ValueError(problem)
    if len(set(value)) != len(value):
        raise ValueError("each branch is named once")


def pack_row(space) -> dict | None:
    """The space's pack's own base field from its options.json, or None."""
    folder = getattr(space, "adapter_dir", None)
    if folder is None:
        return None
    try:
        entries = json.loads((folder / "options.json").read_text())
    except (OSError, ValueError):
        return None
    return next((entry for entry in entries if isinstance(entry, dict) and entry.get("key") == KEY), None)


def own(row: dict | None) -> bool:
    """A pack's base field that lists its own branches, which the space's list never replaces."""
    return bool(row) and row.get("type") == "select" and bool(row.get("options"))


def of(space) -> list[str]:
    """The space's bases: its pack's own select's first, else its own, else none."""
    found = pack_row(space)
    if own(found):
        return [str(name) for name in found["options"]]
    return list(getattr(space, "bases", ()) or ())


def integrated(cfg, space) -> list[str]:
    """The space's repos whose cards land on an integration branch: they take no base (r1.F4)."""
    return [key for key in space.repos if cfg.integration_of(space.name, key)]


def row(space, entries: list[dict], skip=()) -> list[dict]:
    """The sheet with Base branch as the space's bases (a select, empty unless picked, a branch
    the list does not name may be typed), unless the pack declares a base select of its own,
    which is kept exactly; a pack's free-text base field becomes that select with the pack's
    own words (c-734). A space that names no bases keeps the sheet as it was."""
    names = list(getattr(space, "bases", ()) or ())
    mine = next((entry for entry in entries if entry.get("key") == KEY), None)
    if names and mine is not None and not own(mine) and mine.get("type") == "text":
        # c-734 (12): a pack's free-text base field takes the space's bases as its choices, a
        # select that still takes a typed branch, with the pack's own words; a pack's own select
        # is kept as declared (r1.F1)
        offered = dict(mine, type="select", options=["", *names], default="", typed=True,
                       blank=mine.get("placeholder") or BLANK)
        return [offered if entry is mine else entry for entry in entries]
    if not names or mine is not None:      # r1.F1: a pack's own select, or a field with no bases, is kept
        return entries
    # r2.F4: only for a card on a repo without an integration branch (`skip`, `integrated`)
    allowed = [key for key in space.repos if key not in skip]
    if skip and not allowed:
        return entries
    # r1.F5, F7: no default. Empty is the repo's own rule (its integration branch, else the
    # branch its checkout has out), so a card that picks none is cut and landed as before.
    made = {"key": KEY, "label": "Base branch", "type": "select", "stored": "options",
            "options": ["", *names], "default": "", "blank": BLANK, "typed": True, "when": "repo != none",
            "help": "the branch this card's work starts from and lands on; empty is the repo's usual branch"}
    if skip:
        made["repos"] = allowed            # the card form shows it only for a card on these
    at = next((i + 1 for i, entry in enumerate(entries) if entry.get("key") == "repo"), len(entries))
    return [*entries[:at], made, *entries[at:]]


def said(cfg, space_name: str) -> str:
    """The sentence both drafts carry: the space's bases, or that it names none."""
    space = cfg.spaces.get(space_name)
    skip = integrated(cfg, space) if space is not None else []
    # r2.F4: a space whose repos all land on an integration branch has no bases to draw
    everything = space is not None and bool(space.repos) and len(skip) == len(space.repos)
    names = of(space) if space is not None and not everything else []
    note = (f" {', '.join(skip)} {'lands' if len(skip) == 1 else 'land'} on its integration branch, "
            f"so a card on {'it' if len(skip) == 1 else 'them'} names no base." if skip else "")
    if not names:
        return f"The {space_name} space names no bases: {USUAL}{note}"
    return (f"The {space_name} space's bases, the branches a card's work can start from and land "
            f"on: {', '.join(names)}. {USUAL}{note} Draw each base as a branch of its own, by name, "
            f"and give a move that only fits some of them their names in `bases`.")
