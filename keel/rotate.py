"""Rotating a house: a fresh session that carries the work on (R6, c-436, decision N9).

His flow, on demand: the house writes a handoff checkpoint, a NEW session starts from the
card's own brief and rehydrates from that checkpoint, the card's session is set to the new
one (so the deck, voice, the relays and every other reader follow it: they all read the
session off the card), the old one is stopped, and the card says so. Two phases, because
the checkpoint is a model turn and a tap may not wait on one:

1. **Ask** (`ask`, the deck's `house.rotate`, `keel rotate <card>`, or a `rotate` relay
   carried by the drain of the machine that holds the house). Refused while voice holds the
   card and while the house is working (`house.Busy`): the checkpoint turn is a resume, and
   a resume of a busy session would copy it. The house is resumed with the checkpoint
   prompt and `options.rotate` records `checkpointing`.
2. **Finish** (`upkeep`, every drain pass on that machine). Once that session is no longer
   working and `state/cards/<id>/handoff.md` was written after the ask, a fresh session is
   started with the card's brief plus the rehydrate prompt, recorded with `set_session`,
   and the checkpointing session is stopped (it is superseded, the same stop a resume
   performs). A turn that ended with no checkpoint, or one that never ended, is noted and
   the rotation is dropped; the house is left as it was.

Nothing here is automatic. What the harness reports about context (the status line's
`context_window.used_percentage`, and the `PreCompact` hook with `trigger: auto`) is
recorded in `<install>/history/docs/decisions.md` (E-rows) for a later, separate decision.
"""

import argparse
import sys
from datetime import datetime

from keel import adapters, config as config_module, harness, house, housejobs, sessionorigin, trust, views
from keel.board import Refused, now, open_board
from keel.config import Config

ROTATE_OPTION = views.ROTATE_OPTION
CHECKPOINTING = "checkpointing"
CHECKPOINT_FILE = "handoff.md"
HANDOFF_SKILL = "~/.claude/skills/handoff/SKILL.md"
GIVE_UP_SECONDS = 1800
# A pass right after the ask may not list the resumed session as working yet.
START_GRACE_SECONDS = 120

CHECKPOINT_PROMPT = """\
Rotate: this session is being replaced by a fresh one, which will carry the card on from a
checkpoint you write now. Do not continue the work in this turn.

1. Commit what is worth keeping on your branch, or say in the checkpoint what you left
   uncommitted and why.
2. Write the checkpoint to `{path}`. Use the handoff skill in checkpoint mode when you have
   it (`{skill}`: `python3 ~/.claude/skills/handoff/scripts/handoff.py checkpoint --out {path}`,
   then fill its sections); without it, write the same sections yourself: Summary, What is
   done, What is left (ordered, concrete next steps), Key decisions and dead-ends, Files
   touched, How to verify, Plan and references.
3. Bring `context.md` up to date too, then end your turn. Keel starts the new session."""

REHYDRATE_PROMPT = """\
## You are continuing this card from a checkpoint

A fresh session, rotated in by Keel on the user's request: the session before you wrote a handoff
checkpoint at `{path}`. Read it first (the handoff skill's resume mode, when you have it),
then `{context}`, then carry on from "What is left". The card is at `{stage}`; its gates and
everything above still govern what you do."""


class NotRotating(Refused):
    """The house cannot be rotated right now; the message says why."""


def state_of(card: dict) -> dict:
    return (card.get("options") or {}).get(ROTATE_OPTION) or {}


def checkpoint_path(cfg: Config, card_id: str):
    return cfg.card_dir(card_id) / CHECKPOINT_FILE


# ----- phase 1: ask for the checkpoint -----

def ask(cfg: Config, board, card_id: str, actor: str = "human") -> dict:
    """Resume the house with the checkpoint prompt; `NotRotating` or `house.Busy` when it
    cannot be asked now."""
    card = board.get(card_id)
    if not card.get("session_id"):
        raise NotRotating(f"{card_id} has no house session to rotate")
    if views.voice_hold(card.get("options")):
        raise NotRotating(f"voice is talking to {card_id}; rotate it when the conversation ends")
    if state_of(card).get("state") == CHECKPOINTING:
        raise NotRotating(f"{card_id} is already rotating; the drain finishes it")
    path = checkpoint_path(cfg, card_id)
    prompt = CHECKPOINT_PROMPT.format(path=path, skill=HANDOFF_SKILL)
    result = house.resume(cfg, board, card_id, prompt=prompt,
                          actor="bosun" if actor == "bosun" else "drain")
    board.set_fields(card_id, {"options": {ROTATE_OPTION: {
        "state": CHECKPOINTING, "at": now(), "session": result["session_id"],
        "host": cfg.host}}}, "drain")
    board.note(card_id, f"rotating: asked the house for a checkpoint at {path}", actor)
    return result


# ----- phase 2: the fresh session -----

def written_since(path, at: str | None) -> bool:
    stamp = views.parse_at(at)
    try:
        written = datetime.fromtimestamp(path.stat().st_mtime).astimezone()
    except OSError:
        return False
    return stamp is None or written >= stamp


def age_seconds(at: str | None) -> float:
    stamp = views.parse_at(at)
    return float("inf") if stamp is None else (datetime.now(stamp.tzinfo) - stamp).total_seconds()


def drop(board, card_id: str, why: str) -> None:
    board.set_fields(card_id, {"options": {ROTATE_OPTION: None}}, "drain")
    board.note(card_id, f"rotation dropped: {why}; the house is left as it was", "drain")


def start_fresh(cfg: Config, board, card: dict, expect: str) -> dict:
    """The new session: the card's brief, then the rehydrate prompt, under today's settings.

    RECORDED FIRST (round 3, finding 2): right after `start_bg` the session goes on the card,
    compare-and-swap against `expect` (the rotation's session). If the card moved on meanwhile
    the new session is stopped rather than left running unrecorded. Everything after the
    record (the csr sidecar, the reviewer mark) is a note when it fails, never a failure."""
    model = house.require_model(cfg, board, card)
    space = adapters.space_of(cfg, card)
    where = house.placement(cfg, card)
    settings = house.settings_for(cfg, card)
    brief = house.brief_for(cfg, card)
    path = checkpoint_path(cfg, card["id"])
    prompt = brief + "\n" + REHYDRATE_PROMPT.format(
        path=path, context=cfg.card_dir(card["id"]) / "context.md", stage=card["stage"])
    agents = house.reviewer_of(cfg, card)
    trust.grant(space.config_dir, where["cwd"])        # 2.1.281 refuses an untrusted cwd
    result = harness.start_bg(
        where["cwd"], prompt, name=card["id"], config_dir=space.config_dir,
        settings_path=settings, model=model, agents=agents, **house.harness_flags(where))
    try:
        link = house.app_link(result["bg_id"], space.config_dir)
    except Exception:  # noqa: BLE001 - a link is a convenience; the record is not
        link = None
    try:
        board.set_session(card["id"], result["session_id"], "drain", bg_id=result["bg_id"],
                          app_link=link, expect=expect)
    except Refused as moved:
        try:
            housejobs.stop(result["bg_id"], space.config_dir, harness.stop)   # started by this call, never recorded
        except harness.HarnessError as error:
            board.note(card["id"], f"the fresh session {result['bg_id']} was not recorded and "
                                   f"could not be stopped: {error}", "drain")
        raise Moved(str(moved)) from None
    for after in (lambda: sessionorigin.declare(cfg.home, card, result["session_id"]),
                  lambda: house.record_reviewer(board, card["id"], result["session_id"], agents)):
        try:
            after()
        except Exception as error:  # noqa: BLE001 - the session is recorded; the rest is extra
            board.note(card["id"], f"rotated, but a step after the record failed: {error}", "drain")
    return result


class Moved(Refused):
    """The card moved to another session while the fresh one was starting."""


def finish(cfg: Config, board, card: dict, rows: list[dict]) -> str | None:
    """Phase 2 for one card; a word for the log, or None when it is not time yet."""
    rotating = state_of(card)
    session = rotating.get("session")
    if not session or card.get("session_id") != session:
        drop(board, card["id"], "cancelled: the card moved to another session after it was asked")
        return "dropped"
    row = harness.find(session, rows)
    # `status`: the checkpoint turn's own jobs are still work, so wait them out
    if row is not None and row.get("status") == house.BUSY:
        if age_seconds(rotating.get("at")) > GIVE_UP_SECONDS:
            drop(board, card["id"], "the checkpoint turn did not end in time")
            return "dropped"
        return None
    path = checkpoint_path(cfg, card["id"])
    if not written_since(path, rotating.get("at")):
        if age_seconds(rotating.get("at")) < START_GRACE_SECONDS:
            return None             # the turn may not be listed as working yet
        drop(board, card["id"], f"the checkpoint turn ended without writing {path}")
        return "dropped"
    space = adapters.space_of(cfg, card)
    try:
        result = start_fresh(cfg, board, card, expect=session)
    except Moved as moved:
        drop(board, card["id"], f"cancelled: {moved}")
        return "dropped"
    except (Refused, harness.HarnessError, adapters.AdapterError, OSError) as error:
        return start_failed(board, card, rotating, error)
    board.set_fields(card["id"], {"options": {ROTATE_OPTION: None}}, "drain")
    house.retire_session(board, card["id"], session, space.config_dir, "rotated-out session")
    board.note(card["id"], f"rotated: session {result['session_id'][:8]} carries on from "
                           f"{path}", "drain")
    return "rotated"


START_TRIES = 2


def start_failed(board, card: dict, rotating: dict, error) -> str:
    """A fresh session that would not start: tried once more on the next pass, then the
    rotation ends with a note, so it never loops and the card is never left exempt from the
    Stop nudge (lane E, finding 2)."""
    tries = int(rotating.get("failures") or 0) + 1
    said = str(error).splitlines()[0] if str(error) else type(error).__name__
    if tries >= START_TRIES:
        drop(board, card["id"], f"the fresh session would not start ({said}), twice")
        return "dropped"
    board.set_fields(card["id"], {"options": {ROTATE_OPTION: dict(rotating, failures=tries)}}, "drain")
    board.note(card["id"], f"rotating: the fresh session would not start ({said}); trying once "
                           f"more on the next pass", "drain")
    return "retry"


def upkeep(cfg: Config, board, rows: list[dict]) -> int:
    """Finish every rotation of this machine that is ready; the count finished. Nothing at
    all with `[keel] rotate` off."""
    if not cfg.rotate:
        return 0
    done = 0
    for card in board.list_cards():
        rotating = state_of(card)
        if rotating.get("state") != CHECKPOINTING or rotating.get("host") != cfg.host:
            continue
        with house.card_lock(cfg, card["id"]):
            fresh = board.get(card["id"])        # read again under the lock
            if state_of(fresh).get("state") == CHECKPOINTING and finish(cfg, board, fresh, rows) == "rotated":
                done += 1
    return done


# ----- `keel rotate <card>` -----

def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="keel rotate",
                                     description="rotate a house on this machine into a fresh session")
    parser.add_argument("card")
    args = parser.parse_args(argv)
    cfg = config_module.load()
    board = open_board(cfg)
    try:
        if not cfg.rotate:
            raise NotRotating("rotation is switched off ([keel] rotate = false)")
        ask(cfg, board, args.card, actor="cli")
    except Refused as refused:
        print(f"keel rotate: {refused}", file=sys.stderr)
        return 1
    finally:
        board.close()
    print(f"{args.card}: asked for a checkpoint; the drain starts the fresh session when it is written")
    return 0
