"""Drop in: the one command that puts him in a card's house from the desk (E2, c-443).

A server cannot open an interactive session, so the deck hands back a command to paste.
Which command depends on the house's session, its cwd and its config dir (`facts`).

- **A live house is attached to.** Probed 2026-09-23 on Claude Code 2.1.280
  (`tests/fixtures/harness/README.md`, "Attach probe"): a turn typed through
  `claude attach <id>` landed in the SAME session, same pid and same session id, one
  transcript. `claude --resume <uuid>` on a running session starts a COPY instead, so it is
  never handed out for a live house (decision N10).
- **An exited house is resumed** in its own directory, as before: nothing is running, so a
  resume continues the conversation rather than forking it.
- **A card with no session** opens a fresh `claude` in the house's directory.

**An exited house he resumes is HELD while he is in it** (U3, probed 2026-09-24 on 2.1.281,
`tests/fixtures/harness/README.md`, "Drop in on an exited house"). A terminal
`claude --resume <uuid>` keeps the session id and is listed as `kind: interactive`; Keel's
own `claude --resume <uuid> --bg ...` on it then starts a COPY. So Drop in takes
`options.dropin_hold` (`hold_record`), every resume refuses a held card or an interactive
row (`house.refuse_if_busy`), and the drain leaves a held card alone and ends the hold
(`verdict`): when it runs out with nobody in the session, or when his terminal session,
once seen, leaves the listing. His session carries none of the house's hooks, so the
listing is the only thing that can say he left.
"""

import shlex
from contextlib import contextmanager, suppress
from datetime import datetime, timedelta
from pathlib import Path

from keel import harness, housejobs, prompts, repolayout, terms, views
from keel.config import Config

ATTACH = "attach"
RESUME = "resume"
NEW = "new"
RECORD = "record"
RECORD_NONE = "record-none"        # a `said` key only: `how` is RECORD either way
SAID = {
    ATTACH: "Joins the running house: the same session, what you type lands in its "
            "conversation. Ctrl+Z drops back to your shell and the house keeps running: "
            "it does not close it.",
    RESUME: "The house has exited: this resumes its conversation in its own directory. "
            "Shipyard will not resume it in the background while you are in it. "
            "End it with /exit (or Ctrl+D) when done: Ctrl+Z only suspends it and keeps it open.",
    NEW: "No session on this card yet: this opens a fresh one in the house's directory. "
         "End it with /exit (or Ctrl+D) when done: Ctrl+Z only suspends it and keeps it open.",
    RECORD: "The card is done and its conversation is gone: this opens a fresh session in "
            "the card's record, told to read its plan and context first. "
            "End it with /exit (or Ctrl+D) when done: Ctrl+Z only suspends it and keeps it open.",
    RECORD_NONE: "The card is done and never had a conversation: this opens a fresh session "
                 "in the card's record, told to read its plan and context first. "
                 "End it with /exit (or Ctrl+D) when done: Ctrl+Z only suspends it and keeps "
                 "it open.",
}

# How long a drop-in hold waits for him to paste the command and be listed. Once his
# terminal session is seen the hold lasts while it is listed, however long that is.
HOLD_SECONDS = 15 * 60
# The `kind` `claude agents --json` gives a session running in a terminal (probed).
INTERACTIVE = "interactive"
# What the drain does with a card's hold on this pass (`verdict`).
MARK_SEEN = "seen"
ENDED = "ended"
EXPIRED = "expired"
RELEASE_NOTES = {
    ENDED: "your terminal session on this house has ended; the drop-in hold is cleared",
    EXPIRED: "nobody joined the house within the Drop in hold; it is cleared",
}


class NoPlace(Exception):
    """The house has no directory on this machine to enter, and Drop in creates none."""


class AlreadyOpen(NoPlace):
    """The card's conversation is running in a terminal already: `claude attach` takes a
    BACKGROUND session's id, and a second `--resume` would fork it, so there is nothing to
    hand out. A `NoPlace`, so every caller refuses it the same way."""


def place_of(cfg: Config, card: dict) -> Path | None:
    """Where the house works, whether or not it is there: an errand's card directory, a
    personal card's worktree, a work card's recorded `options.worktree`."""
    if not card.get("repo"):
        return cfg.card_dir(card["id"])      # the card's own record directory, not a worktree
    if cfg.spaces[card["space"]].adapter_dir is None:
        return repolayout.card_tree(cfg, card)
    recorded = (card.get("options") or {}).get("worktree")
    return Path(recorded) if recorded else None


def cwd_of(cfg: Config, card: dict) -> Path | None:
    """Where the house works, READ, never made (review finding 7). None when that directory
    is not there; recreating it is Retry's, not a read's (a done card's is `reopen_place`).
    A repo card's EMPTY directory is not its worktree either (c-789, `repolayout.holds_tree`):
    a folder a done card's Drop in remade and nobody removed reads as absent, as it would
    were it gone (plangate falls back to the repo's checkout, the ref resolvers to the
    card's other worktrees or none)."""
    path = place_of(cfg, card)
    if path is None or not path.is_dir():
        return None
    return path if not card.get("repo") or repolayout.holds_tree(path) else None


@contextmanager
def reopen_place(cfg: Config, card: dict):
    """A DONE card's house directory for the length of the block, made EMPTY when its
    worktree was torn down and removed again after if still empty (c-787, review F1: an
    empty directory left behind reads as the card's worktree to `cwd_of` and the plan
    pages). The harness files a conversation under the directory it ran in, so the gone
    probe and the resume must both run from there (proven by hand on c-756, 2026-10-15);
    the handed-out command makes it again itself (`remade`). No git worktree is made. Yields
    (the path, the directories made here, deepest first), or (None, []) when it names none."""
    path = place_of(cfg, card)
    made = [] if path is None else [p for p in (path, *path.parents) if not p.exists()]
    if made:
        path.mkdir(parents=True)
    try:
        yield path, list(made)
    finally:
        for each in made:          # the directory, then each parent made for it, while empty
            with suppress(OSError):
                each.rmdir()


def remade(facts: dict, made: list[Path]) -> dict:
    """A resume command that makes its torn-down directory again, empty, first (c-787), and
    once the session exits removes what it made (`made`, deepest first, from
    `reopen_place`) while each is still empty (c-789): a worktree the session made there
    keeps it. In a subshell, so the user's terminal stays where it was. POSIX shells (zsh,
    bash); the other Drop in commands are the same."""
    where = shlex.quote(facts["cwd"])
    gone = " ".join(shlex.quote(str(each)) for each in made)
    return dict(facts, command=f"(mkdir -p {where} && {facts['command']}); rmdir {gone} 2>/dev/null")


def from_record(cfg: Config, card: dict) -> dict:
    """The facts for a DONE card whose conversation is gone (c-787): a fresh session in the
    card's own record directory, told to read the record and wait for the user (`prompts.reopen`).
    It is the user's terminal's, not a house: nothing is recorded on the card as its session."""
    space = cfg.spaces[card["space"]]
    where = cfg.card_dir(card["id"])
    lead = config_prefix(space.config_dir) + harness.claude_bin()
    prompt = prompts.reopen(card, where, card.get("session_id"),
                            change=terms.of(cfg, card.get("space"))["change"], cfg=cfg)
    said = SAID[RECORD] if card.get("session_id") else SAID[RECORD_NONE]
    return {"cwd": str(where), "how": RECORD, "status": None, "said": said,
            "command": f"cd {shlex.quote(str(where))} && {lead} {shlex.quote(prompt)}"}


def config_prefix(config_dir) -> str:
    """`CLAUDE_CONFIG_DIR=<dir> `, or nothing for the machine default (reached UNSET)."""
    if harness.is_default_config_dir(config_dir):
        return ""
    return f"CLAUDE_CONFIG_DIR={shlex.quote(str(config_dir))} "


def live_row(card: dict, config_dir) -> dict | None:
    """The harness's row for this card's session on THIS machine, or None."""
    session_id = card.get("session_id") or ""
    if not session_id:
        return None
    return harness.find(session_id, harness.agents(config_dir))


def row_facts(row: dict | None) -> dict | None:
    """The part of an agents row the deck draws a house from, or None for no row."""
    if row is None:
        return None
    return {"bg_id": row.get("id"), "status": row.get("status"), "state": row.get("state"),
            "started_at": row.get("startedAt"), "cwd": row.get("cwd"),
            "session_id": row.get("sessionId"), "kind": row.get("kind"), "pid": row.get("pid"),
            # the one rule (`housejobs.working`, r-26), so the page holds none of its own
            "working": housejobs.working(row)}


def facts(cfg: Config, card: dict, cwd: Path | None = None) -> dict:
    """What the machine holding the house knows: its cwd, whether its session is live, and
    the command that enters it. `NoPlace` when there is no live session and no directory.
    `cwd`: a done card's remade directory (`reopen_place`), which `cwd_of` reads as absent."""
    space = cfg.spaces[card["space"]]
    cwd = cwd or cwd_of(cfg, card)
    row = live_row(card, space.config_dir)
    lead = config_prefix(space.config_dir) + harness.claude_bin()
    if row is not None and row.get("kind") == INTERACTIVE:
        raise AlreadyOpen(f"{card['id']}'s conversation is already open in a terminal on "
                          f"{cfg.host} (pid {row.get('pid')}); carry on there")
    if row is not None:
        bg_id = row.get("id") or card["session_id"][:8]
        how, command = ATTACH, f"{lead} attach {bg_id}"
    elif cwd is None:
        raise NoPlace(f"{card['id']}'s house has no directory on {cfg.host} any more, and Drop "
                      f"in makes none; Retry recreates it")
    elif card.get("session_id"):
        how, command = RESUME, f"cd {shlex.quote(str(cwd))} && {lead} --resume {card['session_id']}"
    else:
        how, command = NEW, f"cd {shlex.quote(str(cwd))} && {lead}"
    return {"cwd": str(cwd) if cwd else None, "how": how, "status": (row or {}).get("status"),
            "command": command, "said": SAID[how]}


NOT_LISTED = ("{id}'s old conversation was gone, so a new house, {new}, was started from the "
              "card's record, but the harness does not list it yet: nothing was handed out. Tap "
              "again in a moment; if it stays unlisted, Resume house says what became of it")


def joined(cfg: Config, card: dict, started: dict) -> dict:
    """The facts for a house Drop in has just started afresh (c-654): ATTACH to the start's
    own id, and only once the harness lists that session with a process. Never a resume
    command: the house may be in its first turn, and a `claude --resume` of it would start
    a copy (N10). `NoPlace` when it is not listed, so he taps again."""
    space = cfg.spaces[card["space"]]
    row = harness.find(started["session_id"], harness.agents(space.config_dir))
    if not housejobs.has_process(row) or row.get("kind") == INTERACTIVE:
        raise NoPlace(NOT_LISTED.format(id=card["id"], new=started["bg_id"]))
    cwd = cwd_of(cfg, card)
    lead = config_prefix(space.config_dir) + harness.claude_bin()
    return {"cwd": str(cwd) if cwd else None, "how": ATTACH, "status": row.get("status"),
            "command": f"{lead} attach {started['bg_id']}", "said": SAID[ATTACH]}


def hold_record(card: dict, at: datetime | None = None) -> dict:
    """The hold Drop in takes on an exited house: whose session, and how long it waits."""
    now = at or datetime.now().astimezone()
    return {"at": now.isoformat(timespec="seconds"),
            "until": (now + timedelta(seconds=HOLD_SECONDS)).isoformat(timespec="seconds"),
            "session": card.get("session_id"), "seen": False}


def in_terminal(card: dict, rows: list[dict]) -> dict | None:
    """The listing's row for this card's session when it runs in a terminal, else None."""
    row = harness.find(card.get("session_id") or "", rows)
    return row if row is not None and row.get("kind") == INTERACTIVE else None


def verdict(card: dict, rows: list[dict], at: datetime | None = None) -> str | None:
    """What this pass does with the card's hold: mark it seen, end it, or nothing (None).

    Seen and still listed holds; seen and gone is his session ending (`ENDED`); never seen
    is held until `until` and then `EXPIRED`."""
    held = views.dropin_hold(card.get("options"))
    if held is None:
        return None
    listed = in_terminal(card, rows) is not None
    if listed:
        return None if held.get("seen") else MARK_SEEN
    if held.get("seen"):
        return ENDED
    return None if views.dropin_holding(card.get("options"), at) else EXPIRED
