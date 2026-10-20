"""The landing queue: Approve outcome carried to the machine that holds the worktree (E5).

`keel/merging.py` builds the merged tree, tests it and lands it by fast-forward. This module
decides WHERE and WHEN that runs, for a personal repo card:

- **Inside the tap**, as it always did, for a card whose house is on this machine while
  `[keel] merge_queue` is off (the shipped default).
- **Through the drain of the machine that holds the worktree**, for a card whose house is on
  the OTHER machine (c-306: its branch and worktree are there, so a merge here found no
  branch and was reported as "main moved"), and for every card once `merge_queue` is on
  (the tap then returns at once instead of holding the deck's 180 second request for a
  whole test suite, which it can outlast).

The queued path is a `land` relay: the human's tap, recorded with his token, or Bosun's
checked outcome approval in builder mode (c-526, `authority.outcome_approval`), only at
review, one per card (`Board.relay`). The drain that owns the card takes it (`carry`) and
spawns `python3 -m keel.landing <card> --relay <n>` in its own session, because a suite
that runs for minutes cannot run inside a drain pass. The worker holds the checkout's lock
(`state/locks/land-<the repo's path>.lock`, one landing, pre-run or deploy per checkout at a
time, whichever space the card is in), runs `merging.publish` (onto the integration branch
for a repo in `[integration]`), and answers on the card: `kb land` moves it to done naming
the relay (the one way anything but a tap passes the outcome gate, and only on such a
relay), or the card is blocked "outcome not merged: <why>", or, on a conflict, the house is
sent to merge the target branch exactly as the tap would. `options.landing` carries what the deck shows:
`testing` (with the worker's pid), `landed`, `refused`; `queued` is the pending relay.

With the flag on, the drain also PRE-RUNS the merged tree of a card at review (R5, `upkeep`)
and records `options.pretest` (green, red, conflict, the heads it was built from), once per
pair of heads, so the result is on the card before he taps.
"""

import argparse
import fcntl
import os
import re
import subprocess
import sys
import time
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path

from keel import (adapters, childenv, config as config_module, harness, house, housejobs,
                  merging, prompts, repocommands, views)
from keel.board import Refused, now, open_board
from keel.config import Config

LANDING = "landing"
PRETEST = "pretest"
TESTING = "testing"
LANDED = "landed"
REFUSED = "refused"
RUNNING = "running"
NOT_MERGED = "outcome not merged: "
# The mark on a landing's own refusal block (`board.MARKS`): a re-stage to review clears it
# (`Board.stage`), since a new outcome is a new approve (c-575 sat blocked after one).
REFUSED_MARK = "landing-refused"
# A worker that was spawned and never wrote its pid is taken for dead after this long.
UNSTARTED_SECONDS = 300
LOG_NAME = "landing.log"


# ----- where, and whether -----

def mergeable(cfg: Config, card: dict) -> bool:
    """A personal repo card: its outcome is a branch, so approving it is a merge. Never a
    tracking card: each slice landed on its own, so it has no branch of its own to land
    or pre-run, and Approve outcome closes it in the tap (lane X)."""
    space = cfg.spaces.get(card["space"])
    return bool(space and space.adapter_dir is None and card.get("repo")
                and not (card.get("derived") or {}).get("tracking"))


def route(cfg: Config, card: dict, tap: bool = False) -> str | None:
    """The machine that lands this card through its drain, or None to land it in the tap.

    `tap` is the user's Approve outcome asking (`actions.act_approve`): only then is a
    builder's branch read from its clone (`merging.branch_placed`'s `fetch`), so a card
    whose branch already landed under another card (one branch for a stack, c-773) is
    nothing to land and closes in the tap. Unread, it would be queued and then refused for
    having no branch to land."""
    if not cfg.merge_queue or not mergeable(cfg, card):
        return None          # dormant: with the flag off every approve lands in the tap
    if merging.nothing_to_land(cfg, card, fetch=tap):
        return None          # r-24: closed in the tap, with no relay, pretest, merge or suite
    return cfg.host


def state_of(card: dict, key: str = LANDING) -> dict:
    return (card.get("options") or {}).get(key) or {}


def mark(board, card_id: str, state: dict, key: str = LANDING) -> None:
    board.set_fields(card_id, {"options": {key: dict(state, at=now())}}, "drain")


def same_repo(card: dict, other: dict) -> bool:
    return other["space"] == card["space"] and other.get("repo") == card.get("repo")


def running_here(cfg: Config, board, card: dict) -> bool:
    """Is a landing or a pre-run of this card's repo already running on this machine."""
    for other in board.list_cards():
        # The card's OWN landing and pre-run count too (review finding 5): a second approve
        # of a card whose worker is still running must not start a second worker.
        if not same_repo(card, other):
            continue
        for key, busy in ((LANDING, TESTING), (PRETEST, RUNNING)):
            state = state_of(other, key)
            if state.get("state") == busy and state.get("host") == cfg.host:
                return True
    return False


# ----- the drain's half -----

def spawn(cfg: Config, card_id: str, *args: str, module: str = "keel.landing") -> int:
    """Start the worker in a session of its own, logging beside the drain; its pid. `module`
    is the worker to run: this one, or the push's (`keel/landpush.py`, c-678)."""
    env = childenv.own_env()      # the worker runs a house's suite; never his token (c-451)
    if cfg.source is not None and not cfg.scratch:
        env["KEEL_CONFIG"] = str(cfg.source)
    cfg.logs_dir.mkdir(parents=True, exist_ok=True)
    with open(cfg.logs_dir / LOG_NAME, "a") as log:
        proc = subprocess.Popen([sys.executable, "-m", module, card_id, *args],
                                cwd=str(cfg.root), env=env, stdin=subprocess.DEVNULL,
                                stdout=log, stderr=subprocess.STDOUT, start_new_session=True)
    return proc.pid


def carry(cfg: Config, board, card: dict, relay: dict, take) -> bool:
    """A `land` relay, carried: taken (`take`, the drain's own, so it is carried once) and
    handed to a worker. Left pending while this repo has a landing running here: one at a
    time, in relay order."""
    if running_here(cfg, board, card):
        return False
    if not take(cfg, board, card, relay):
        return False
    mark(board, card["id"], {"state": TESTING, "host": cfg.host, "relay": relay["id"]})
    try:
        spawn(cfg, card["id"], "--relay", str(relay["id"]))
    except OSError as error:
        refuse_clean(board, board.get(card["id"]), relay["id"],
                     f"the landing worker would not start on {cfg.host}: {error}")
    return True


def alive(pid) -> bool:
    try:
        os.kill(int(pid), 0)
    except (ProcessLookupError, ValueError, TypeError):
        return False
    except PermissionError:
        return True
    return True


def age_seconds(at: str | None) -> float:
    stamp = views.parse_at(at)
    if stamp is None:
        return float("inf")
    return (datetime.now(stamp.tzinfo) - stamp).total_seconds()


def dead(cfg: Config, state: dict) -> bool:
    """A worker of this machine that is no longer there to answer."""
    if state.get("host") != cfg.host:
        return False
    if state.get("pid"):
        return not alive(state["pid"])
    return age_seconds(state.get("at")) > UNSTARTED_SECONDS


def upkeep(cfg: Config, board) -> None:
    """Every pass: answer a worker that died, then (flag on) pre-run one card at review."""
    for card in board.list_cards():
        if state_of(card).get("state") == TESTING and dead(cfg, state_of(card)):
            refuse_clean(board, card, state_of(card).get("relay"),
                         f"the landing on {cfg.host} ended without an answer; approve again")
        pre = state_of(card, PRETEST)
        if pre.get("state") == RUNNING and dead(cfg, pre):
            mark(board, card["id"], {"state": "ended", "why": "the pre-run ended without an answer"},
                 PRETEST)
    if cfg.merge_queue:
        pre_run_one(cfg, board)


def heads(cfg: Config, card: dict) -> dict | None:
    """The two heads a pre-run is keyed on: the target's and the branch's, here. None for an
    in-app builder's card, which is never pre-run (`merging.built_clone`: a card he gave a
    house on a builder repo is a house's, and is pre-run like one)."""
    if merging.built_clone(cfg, card) is not None:
        return None
    try:
        found = merging.placed(cfg, card)
        if found is None:
            return None
        _, repo, _, branch, target = found
        found_heads = {"target_head": merging.target_head(repo, target),
                       "branch": merging.git(repo, "rev-parse", branch)}
        trunk = merging.trunk_of(repo)
        if target != trunk:
            # The trial merges the trunk in too (c-526): his commit to main is a new tree.
            found_heads["trunk_head"] = merging.git(repo, "rev-parse", trunk)
        return found_heads
    except merging.MergeRefused:
        return None


def pre_run_one(cfg: Config, board) -> bool:
    """R5: spawn the pre-run for the first card at review here whose heads it has not seen."""
    for card in board.list_cards(stage="review"):
        # Never an in-app builder's card (c-619): its branch is not fetched, and so not run,
        # before the user's Approve outcome (`merging.branch_placed`).
        if (merging.built_clone(cfg, card) is not None
                or not mergeable(cfg, card) or card["blocked_reason"]
                or card["derived"].get("relays") or running_here(cfg, board, card)):
            continue
        now_heads = heads(cfg, card)
        if now_heads is None:
            continue
        done = state_of(card, PRETEST)
        seen = all(done.get(key) == value for key, value in now_heads.items())
        waits = repocommands.will_refuse(cfg, card.get("space"), card.get("repo"), board)
        if waits:
            # c-678 fix check r2.D4: Keel cannot know what to test while the repo's file
            # stands changed. Nothing is spawned and nothing is called red on a card
            # nobody approved: "not run", with the sentence, once per pair of heads.
            if not seen or done.get("result") != merging.NOT_RUN:
                mark(board, card["id"], dict(now_heads, state="done", result=merging.NOT_RUN, said=waits,
                                             host=cfg.host), PRETEST)
            continue
        if seen and done.get("result") != merging.NOT_RUN:
            continue            # a "not run" is run once the file's record matches again
        mark(board, card["id"], dict(now_heads, state=RUNNING, host=cfg.host), PRETEST)
        try:
            spawn(cfg, card["id"], "--pretest")
        except OSError as error:
            mark(board, card["id"], dict(now_heads, state="ended", why=str(error)), PRETEST)
        return True
    return False


# ----- the worker's half -----

def lock_path(cfg: Config, card: dict) -> Path:
    """One lock per CHECKOUT, not per space: Keel is a repo of the personal and the console
    space alike, and a landing, a pre-run and a deploy of either write the same repo (c-526,
    review F2)."""
    space = cfg.spaces.get(card["space"])
    path = space.repo_path(card["repo"]) if space is not None and card.get("repo") else None
    if path is None:
        return cfg.state_dir / "locks" / f"land-{card['space']}-{card['repo']}.lock"
    name = re.sub(r"[^\w.-]+", "_", str(Path(path).expanduser().resolve()).strip("/"))
    return cfg.state_dir / "locks" / f"land-{name}.lock"


@contextmanager
def repo_lock(cfg: Config, card: dict):
    """One landing or pre-run per repo on this machine, whatever the board says."""
    path = lock_path(cfg, card)
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "a") as handle:
        fcntl.flock(handle, fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(handle, fcntl.LOCK_UN)


def run(cfg: Config, board, card_id: str, relay: int | None = None, pretest: bool = False) -> int:
    """The worker: 0 when it landed (or pre-ran), 1 when it refused. Never a traceback.

    Its pid goes on the card BEFORE it waits on the repo's lock (review finding 5), so a
    worker queued behind another is never taken for dead while it waits. With the queue off
    it does nothing at all (round 4, finding 2): a hand-run worker writes nothing."""
    if not cfg.merge_queue:
        print(f"keel.landing: the merge queue is off ([keel] merge_queue = false); nothing done",
              file=sys.stderr)
        return 1
    card = board.get(card_id)
    if pretest:
        mark(board, card_id, dict(state_of(card, PRETEST), state=RUNNING, host=cfg.host,
                                  pid=os.getpid()), PRETEST)
    else:
        mark(board, card_id, {"state": TESTING, "host": cfg.host, "relay": relay, "pid": os.getpid()})
    try:
        with repo_lock(cfg, card):
            fresh = board.get(card_id)          # re-read under the lock: it may have moved
            return pre_run(cfg, board, fresh) if pretest else land(cfg, board, fresh, relay)
    except Exception as error:  # noqa: BLE001 - the worker answers on the card, never in a traceback
        why = f"the landing on {cfg.host} failed: {str(error).splitlines()[0] if str(error) else type(error).__name__}"
        if pretest:
            mark(board, card_id, {"state": "ended", "why": why, "host": cfg.host}, PRETEST)
        else:
            refuse_clean(board, board.get(card_id), relay, why)
        return 1


def pre_run(cfg: Config, board, card: dict) -> int:
    now_heads = heads(cfg, card) or {}
    try:
        record = merging.trial(cfg, card) or {"result": "nothing", "said": "nothing to merge"}
    except merging.MergeRefused as refused:
        record = {"result": "red", "said": str(refused)}
    record["said"] = record["said"].splitlines()[0]
    mark(board, card["id"], dict(now_heads, **record, state="done", host=cfg.host), PRETEST)
    return 0 if record["result"] == "green" else 1


def pinned(board, card_id: str, relay: int | None) -> str | None:
    """The branch sha the `land` relay pinned when he approved."""
    for event in board.events(card_id):
        if event.get("id") == relay and event.get("kind") == "relay":
            return (event.get("data") or {}).get("sha")
    return None


def refuse_clean(board, card: dict, relay: int | None, why: str) -> None:
    """A landing that will not happen, answered on the card: the landing marked refused for
    THIS relay (so `kb land` can never finish it), and the card blocked only when it is
    still waiting at review and not blocked already."""
    mark(board, card["id"], {"state": REFUSED, "relay": relay, "why": why.splitlines()[0]})
    if card["stage"] == "review" and not card.get("blocked_reason"):
        board.block(card["id"], NOT_MERGED + why, "drain", mark=REFUSED_MARK)
    else:
        board.note(card["id"], f"the landing did not happen: {why.splitlines()[0]}", "drain")


def still_approved(card: dict) -> str | None:
    """Why the approve no longer stands, or None: the card must still be at review and not
    blocked (a Send back after the tap, and a block, both withdraw it), and its landing not
    cancelled (`Board.stage` marks it when the card leaves review)."""
    if card["stage"] != "review":
        return f"the card is at {card['stage']} now, not review, so the approve no longer stands"
    if card.get("blocked_reason"):
        return "the card was blocked after the approve"
    if state_of(card).get("state") == "cancelled":
        return "the landing was cancelled by a Send back"
    return None


def moved_since(board, card_id: str, relay: int | None) -> bool:
    """A stage move after the tap: a Send back and a return to review in between still
    withdraws what he approved."""
    return any(event.get("kind") == "stage" and relay is not None and event.get("id", 0) > relay
               for event in board.events(card_id))


def listed(cfg: Config, card: dict) -> dict | None:
    space = adapters.space_of(cfg, card)
    return harness.find(card.get("session_id") or "", harness.agents(space.config_dir))


def guard_for(cfg: Config, board, card_id: str, relay: int | None):
    """What is asked right before the fast-forward and right before cleanup (round 3,
    finding 1): the card, read again, still approved with no move since the tap, and its
    house not live."""
    def guard() -> str | None:
        card = board.get(card_id)
        why = still_approved(card)
        if why:
            return why
        if moved_since(board, card_id, relay):
            return "the card moved after the approve"
        row = listed(cfg, card)
        if row is not None and housejobs.has_process(row):
            return f"the card's house is live ({housejobs.row_said(row)})"
        return None
    return guard


STOP_WAIT = 20.0


def finish_house(cfg: Config, board, card: dict) -> str | None:
    """End the card's finished house BEFORE landing, as the tap ends it after (`house.
    retire_finished`), and wait for the listing to let it go. A house that is WORKING (in a
    turn, `housejobs.working`) is a reason not to land at all, never a stop, and the reason
    names the row and says what he can do (r-26); an idle one with only a leftover background
    job is stopped like any finished house, and the stop ends the job (`housejobs.stop`,
    c-535). A row the harness keeps listing with no process behind it (`housejobs.ghost`) is
    stopped too, and landed past with a note: there is nothing there to interrupt."""
    row = listed(cfg, card)
    if row is None:
        return None
    if housejobs.working(row):
        return working_refusal(card, row)
    space = adapters.space_of(cfg, card)
    house.retire_session(board, card["id"], card.get("session_id"), space.config_dir,
                         "finished house", actor="drain")
    deadline = time.time() + STOP_WAIT
    while (row := listed(cfg, card)) is not None and housejobs.has_process(row):
        if time.time() > deadline:
            return f"the card's house did not stop ({housejobs.row_said(row)})"
        time.sleep(0.5)
    if row is not None:
        board.note(card["id"], f"the harness still lists {housejobs.row_said(row)} with no "
                               f"process behind it; landed past it (`keel doctor` names it)",
                   "drain")
    return None


def working_refusal(card: dict, row: dict) -> str:
    """The landing refused for a house in a turn, in one line: what he can do first, then the
    row that stopped it (r-26: "the card's house is working" named nothing)."""
    return (f"the card's house is working. Stop session on {card['id']} (or let its turn end), "
            f"then Approve again; the harness lists {housejobs.row_said(row)}")


def land(cfg: Config, board, card: dict, relay: int | None) -> int:
    if not cfg.merge_queue:
        return 1
    withdrawn = still_approved(card) or ("the card moved after the approve"
                                         if moved_since(board, card["id"], relay) else None)
    sha = pinned(board, card["id"], relay)
    if withdrawn or not sha:
        refuse_clean(board, card, relay, withdrawn or "the land relay pinned no branch sha")
        return 1
    busy = finish_house(cfg, board, card)
    if busy:
        refuse_clean(board, card, relay, busy)
        return 1
    try:
        landed = merging.land_card(cfg, card, expect=sha,
                                   guard=guard_for(cfg, board, card["id"], relay))
    except merging.MergeRefused as refused:
        return refused_here(cfg, board, card, str(refused), relay)
    if landed is None:
        if merging.target_has(cfg, card, sha) is None:
            # r-24: a relay queued before its branch was known to add nothing: the sha he
            # approved is already in the target, so it closes as done with nothing merged.
            return record_landed(cfg, board, card, relay, {
                "pinned": sha, "sha": sha, "published": None,
                "notes": [merging.NOTHING_TO_LAND, *merging.close_unlanded(cfg, card)]})
        refuse_clean(board, card, relay, "there was nothing to merge")
        return 1
    return record_landed(cfg, board, card, relay, landed)


def record_landed(cfg: Config, board, card: dict, relay: int | None, landed: dict) -> int:
    """The merge happened: record it, and move the card to done. A refusal from the board
    now is never reported as "not merged" (round 3, NEW-a): the card says it was merged and
    why it was not moved, and is blocked for him with exactly that."""
    mark(board, card["id"], {"state": LANDED, "host": cfg.host, "relay": relay,
                             "sha": landed["pinned"], "merge": landed["sha"],
                             "published": landed["published"]})
    for note in landed["notes"]:
        board.note(card["id"], note, "drain")
    try:
        board.land(card["id"], relay, "drain", published=landed["published"],
                   merge_queue=cfg.merge_queue,
                   verify=lambda found, sha: merging.target_has(cfg, found, sha))
    except Refused as refused:
        board.block(card["id"], f"merged into {landed.get('target') or 'its target'} at {landed['sha'][:12]}, but not moved to done "
                                f"because {refused}", "drain", mark="mechanics")
        return 1
    return 0


def refused_here(cfg: Config, board, card: dict, why: str, relay: int | None = None) -> int:
    """A refusal: the card is blocked with it, except a conflict, which sends the house to
    merge the target first, as the tap does (`actions.merge_conflict`)."""
    if not why.startswith("merge conflict"):
        refuse_clean(board, card, relay, why)
        return 1
    target, branch = conflict_names(why)
    if merging.bosun_card(card):
        # c-647: no house is resumed on a card Bosun builds, whatever session it carries,
        # and `options.merging` (the deck's word for a house merging) is not set. The
        # receipt reads `why`, so it is Bosun's sentence, not the house's.
        mark(board, card["id"], {"state": REFUSED, "relay": relay, "why": bosun_why(target, branch)})
        board.stage(card["id"], "building", "drain", note=bosun_merges(target, branch))
        return 1
    mark(board, card["id"], {"state": REFUSED, "relay": relay, "why": why.splitlines()[0]})
    board.stage(card["id"], "building", "drain", note=f"{target} moved; the house merges it first")
    board.set_fields(card["id"], {"options": {"merging": True}}, "drain")
    try:
        house.resume(cfg, board, card["id"], prompt=prompts.merge_main(target, branch))
    except (Refused, harness.HarnessError, adapters.AdapterError, OSError) as error:
        if getattr(error, "said", False):
            return 1      # a fresh start Keel would not make: its own block stands (`keel/afresh.py`)
        board.block(card["id"], f"{NOT_MERGED}{why.splitlines()[0]}; the house could not be "
                                f"resumed to merge it: {error}", "drain")
    return 1


# A conflict on a card Bosun builds (c-647). Nothing wakes Bosun for it, so every sentence
# says the card WAITS on Bosun, never that the merge is in hand; the branch is named as it
# was staged, without the landing's own `refs/builder/`.
BOSUN_WAITS = "waiting for Bosun to merge {target} into {branch} and stage review again"
BOSUN_MERGES = ("{target} moved past {branch} and the two disagree, so nothing was merged; "
                + BOSUN_WAITS + ". No house was resumed")
BOSUN_WHY = "merge conflict: {target} moved past {branch} and the two disagree; " + BOSUN_WAITS


def bosun_names(target: str | None, branch: str) -> dict:
    return {"target": target or "its target branch", "branch": branch.removeprefix(merging.BUILT_REFS)}


def bosun_merges(target: str | None, branch: str) -> str:
    """The note a conflict moves a card Bosun builds back to building with."""
    return BOSUN_MERGES.format(**bosun_names(target, branch))


def bosun_why(target: str | None, branch: str) -> str:
    """The refusal the landing records for it, which the receipt prints (`keel/receipt.py`)."""
    return BOSUN_WHY.format(**bosun_names(target, branch))


def conflict_names(why: str) -> tuple[str, str]:
    words = why.split()
    try:
        return words[2], words[5]
    except IndexError:
        return "main", "your branch"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="keel.landing",
                                     description="land (or pre-run) one card's merged tree")
    parser.add_argument("card")
    what = parser.add_mutually_exclusive_group(required=True)
    what.add_argument("--relay", type=int, help="the land relay the drain took")
    what.add_argument("--pretest", action="store_true", help="build and test, land nothing")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    cfg = config_module.load()
    board = open_board(cfg)
    try:
        return run(cfg, board, args.card, relay=args.relay, pretest=args.pretest)
    finally:
        board.close()


if __name__ == "__main__":
    raise SystemExit(main())
