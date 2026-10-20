"""Fetch before work, and a Push after a landing, for a space with no pack (c-678).

A space with no pack lands a card by a merge in Keel's own copy of the repo, on this
computer, and until now it never fetched and never pushed: a card built on whatever the copy
held the day it was cloned, and its landing stayed here. The first run's choice to keep
work on this computer ("Keep work on this computer, and push when you say") adds the two moves, each a switch of the
space (both default off, and written on for a space the first run makes):

- **Fetch before work** (`[spaces.<name>] fetch_before_work`, `fetch_first`): when a card's
  worktree is cut (`keel/adapters.py`), Keel fetches the space's remote in its copy and, when
  the copy's branch is strictly behind, fast-forwards it, so the card builds on what the
  team has. It is never a reason to refuse a card: a fetch that fails, or a copy that has
  moved too, is a sentence and the card builds on what this computer has.
- **Offer Push after a landing** (`[spaces.<name>] offer_push`, `offer`, `push`): a done card
  whose landing was a local merge says "Merged into <branch> on this computer." and carries
  one button. The push is the page's verb (`land.push`), so nothing leaves this computer
  without the user's tap, and it is a plain `git push`: never forced. One that is refused
  because the remote has commits this computer has not seen says so, and its fix is the
  same verb with `fetch`: fetch, merge the remote's commits into the copy's branch on a
  temporary tree, run the repo's tests there, and only then move the branch and push.
  That one can take as long as the repo's suite, so it does not run in the tap: the verb
  marks the card (`options.push`) and starts a worker of its own (`start`, `work`,
  `python3 -m keel.landpush <card> --tap <event>`), which answers on the card. `offer` reads
  the mark: `testing` while the worker runs, `refused` with the last refusal, and a mark
  whose worker died reads as a refusal, never as testing for ever.

  **The worker pushes only for the user's tap** (review r2.F2), the way a landing's worker
  needs its relay (`keel/landing.py`). The verb writes the user's own event on the card (a
  note by the human actor, `asked for`) and hands its id to the worker; `work` writes
  nothing and pushes nothing unless that event is on THIS card, the card's mark is `testing`
  for this machine with that event's id, and no worker has written a pid on it yet. Then it
  writes its pid, which makes the tap good for one worker. The command typed by hand, or by
  a session, finds no such event and ends.

Both apply only to a repo the install copied into its own layout (`keel/repolayout.py`): a
folder the user attached is the user's own checkout, and Keel does not move its branch or
push from it.

**The copy cannot be pushed to** (c-729, point 17). Its landing is the merge here, and its
one push is the Push. On the stranger run a house pushed the card's branch by hand, and the
guard's parsing of a shell line kept opening new ways round it. So the mechanism is git's own:
the copy's remote has a push address git cannot reach (`NO_PUSH`, `fence`), set when the copy
is made (`keel/reposetup.py`) and reconciled at every card cut (`keel/adapters.py`), which
covers copies made before and a pack line added by hand: a space with a pack gets its push
address back. A push address the user had set is kept under `SAVED` meanwhile. Every
`git push` to that remote, from the copy or any worktree of it, fails however it is written;
a fetch is untouched. The Push, and a flow move the user tapped (`flowfence.push`), push by
`push_to`: to the user's saved push address, else the remote's own address, and record it in
the copy's remote-tracking branch as a push to the remote would. Whether a landing has been pushed is read from git each time (the landed
commit is in the copy's remote-tracking branch), never stored.

`check` is the screen's one check, "This computer can push to origin": a dry run of the
push per repo, asked by the user's tap, since it reaches the network. `panel` is what the
Where finished work goes screen draws keeping work on this computer from.
"""

from __future__ import annotations

import argparse
import contextlib
import json
import os
import subprocess
import time
from pathlib import Path

from keel import childenv, cloneerrors, merging, receipt, repocommands, repofile
from keel import config as config_module
from keel.board import now, open_board
from keel.config import remote_of
from keel.setupconfig import SetupError

GIT_SECONDS = 120
# The fetch before a card's worktree is cut runs in whoever cuts it (the drain's pass), so it
# gets a short clock of its own (review F6): past it, the card builds on what is here.
FETCH_FIRST_SECONDS = 20
REJECTED = ("[rejected]", "fetch first", "non-fast-forward")
BEHIND = "{remote} has commits this computer has not seen, so the push was refused."
SAME_LINES = ("{remote}'s commits and this computer's change the same lines of {key}, so Shipyard did not "
              "merge them and nothing was pushed. A card on {key} can merge them: file one that says so.")
# `options.push` on the card: where the push that brings in the remote's commits stands
PUSH = "push"
TESTING, REFUSED, PUSHED = "testing", "refused", "pushed"
STARTED = "fetching {remote}'s commits and testing them with yours; the card says when it is pushed"
GONE = "The push stopped before it finished, and nothing says why. Try again."
BUSY = "{card} is already being tested for its push; the card says when it is done"
# The user's own event the tap leaves on the card, which the worker must be shown
ASKED = "asked"
ASKED_FOR = "asked for the push, with {remote}'s commits fetched and merged in first"
PROOF = ("SELECT 1 FROM events WHERE id = ? AND card = ? AND kind = 'note' AND actor = 'human' "
         "AND json_extract(data, '$.push') = 'asked'")
UNASKED = ("keel.landpush: {card} was not pushed and nothing was changed. This worker runs only for a "
           "Push pressed on the card, and it found no such press waiting.")
BORN_SLACK = 2.0
# A tap is for the worker the verb starts with it, which reads it within a second. One that
# nobody took in this long is no worker's any more, and the card stops saying testing.
TAP_SECONDS = 60
# The read of the mark and the write of the pid, as ONE conditional write: it changes a row
# only while the mark still is the untaken one for this tap, so two workers cannot both
# take it (fix check r2.D5).
TAKE = ("UPDATE cards SET options = json_set(options, '$.push', json(?)), updated_at = ? WHERE id = ? "
        "AND json_extract(options, '$.push.state') = 'testing' AND json_extract(options, '$.push.tap') = ? "
        "AND json_extract(options, '$.push.host') = ? AND json_extract(options, '$.push.pid') IS NULL")


class PushRefused(SetupError):
    """The push did not happen; `detail` rides to the page beside the sentence."""

    def __init__(self, said: str, detail: dict | None = None):
        super().__init__(said)
        self.detail = detail


def run(repo: Path, *args: str, seconds: float = GIT_SECONDS) -> subprocess.CompletedProcess:
    """One git command that may reach the remote: it never asks for a password, and every
    way it can fail to answer comes back as a result with a reason."""
    env = dict(childenv.own_env(), GIT_TERMINAL_PROMPT="0")
    try:
        return subprocess.run(["git", "-C", str(repo), *args], capture_output=True, text=True, errors="replace",
                              stdin=subprocess.DEVNULL, timeout=seconds, env=env)
    except subprocess.TimeoutExpired:
        return subprocess.CompletedProcess(args, 124, "", f"no answer in {seconds}s")
    except OSError as error:
        return subprocess.CompletedProcess(args, 127, "", str(error))


# Where a copy's remote "pushes" (c-729, point 17): git has no helper for this scheme, so every
# `git push` to the remote from the copy or a worktree of it fails. Set by Shipyard on purpose:
# the copy lands by the merge here, and only the Push sends the landed branch, by the address.
NO_PUSH = "no-push://set-by-shipyard"


# A push address the user had set on the copy, kept here while the copy is fenced (fix check 1)
SAVED = "shipyardPushurl"


def fence(cfg, space_name: str | None, key: str | None) -> None:
    """Reconcile a copied repo with its space, at its copy and every card cut: unpushable
    through its remote in a space with no pack, and pushable again in one with a pack (the
    pack pushes for it, however the pack line got into the config). A push address the user
    had set is kept under `SAVED` while fenced and put back after. A folder the user attached,
    and a remote not set, are left alone."""
    space = (getattr(cfg, "spaces", None) or {}).get(space_name or "")
    first = repocommands.first(key)
    if space is None or first not in space.repos or repofile.tier_of(cfg, space_name, first) is None:
        return
    repo, remote = Path(space.repos[first]), remote_of(cfg, space_name)
    if run(repo, "remote", "get-url", remote).returncode != 0:
        return
    name, saved = f"remote.{remote}.pushurl", f"remote.{remote}.{SAVED}"
    now = values(run(repo, "config", "--get-all", name).stdout)
    if space.adapter_dir is None and now != [NO_PUSH]:
        for value in [one for one in now if one != NO_PUSH]:
            run(repo, "config", "--add", saved, value)
        run(repo, "config", "--unset-all", name)
        run(repo, "config", "--add", name, NO_PUSH)
    elif space.adapter_dir is not None and NO_PUSH in now:
        run(repo, "config", "--unset-all", name)
        for value in [one for one in now if one != NO_PUSH] + kept(repo, remote):
            run(repo, "config", "--add", name, value)
        run(repo, "config", "--unset-all", saved)


def values(text: str) -> list[str]:
    """A `git config --get-all` list: one value a line, whole (an address may hold a space)."""
    return [line for line in text.splitlines() if line]


def kept(repo: Path, remote: str) -> list[str]:
    return values(run(repo, "config", "--get-all", f"remote.{remote}.{SAVED}").stdout)


def addresses(repo: Path, remote: str) -> list[str]:
    """Where a push the user asked for goes from this copy: the remote itself when it is not
    fenced, else the push addresses the user had set (`SAVED`), else the remote's own address."""
    if values(run(repo, "config", "--get-all", f"remote.{remote}.pushurl").stdout) != [NO_PUSH]:
        return [remote]
    url = run(repo, "config", "--get", f"remote.{remote}.url").stdout.strip()
    return kept(repo, remote) or ([url] if url else [])


def push_to(repo: Path, remote: str, source: str, branch: str, dry: bool = False) -> subprocess.CompletedProcess:
    """Push `source` to `branch` at the remote by `addresses`, never through the fence, and
    record it in the remote-tracking branch, as a push to the remote would. The Push's, and a
    flow move's the user tapped (`flowfence.push`)."""
    where = addresses(repo, remote)
    if not where:
        return subprocess.CompletedProcess(["push"], 2, "", f"{remote} has no address in this copy")
    done = subprocess.CompletedProcess(["push"], 0, "", "")
    for one in where:
        done = run(repo, "push", *(["--dry-run"] if dry else []), one, f"{source}:refs/heads/{branch}")
        if done.returncode != 0:
            return done
    if not dry and where != [remote]:
        run(repo, "update-ref", f"refs/remotes/{remote}/{branch}", source)
    return done


def push_by_address(repo: Path, remote: str, branch: str, dry: bool = False) -> subprocess.CompletedProcess:
    """The Push of the landed branch (`push_to`)."""
    return push_to(repo, remote, f"refs/heads/{branch}", branch, dry)


def said_of(done: subprocess.CompletedProcess) -> str:
    return cloneerrors.last_line(done.stderr or done.stdout) or "git gave no reason"


def applies(cfg, space_name: str | None, key: str | None) -> Path | None:
    """Keel's copy of the repo when fetch and push are Keel's to do there: a space with no
    pack, a repo the install copied, and the space's remote set in it. Else None."""
    space = (getattr(cfg, "spaces", None) or {}).get(space_name or "")
    first = repocommands.first(key)
    if space is None or space.adapter_dir is not None or repofile.tier_of(cfg, space_name, first) is None:
        return None
    repo = Path(space.repos[first])
    if run(repo, "remote", "get-url", remote_of(cfg, space_name)).returncode != 0:
        return None
    return repo


# ----- fetch before work -----

def fetch_first(cfg, space, key: str, base: str | None = None) -> str | None:
    """Fetch the remote and fast-forward the copy before a card's worktree is cut. None when
    the copy is level with the remote (or nothing applies), else why the card builds on what
    this computer has: the caller notes that on the card, and the brief repeats it
    (`adapters.say_on_card`, `house.cut_block`). Never raises: a card is not refused over a
    fetch, and the fetch has `FETCH_FIRST_SECONDS` to answer."""
    if not getattr(space, "fetch_before_work", False):
        return None
    repo = applies(cfg, space.name, key)
    if repo is None:
        return None
    remote = remote_of(cfg, space.name)
    done = run(repo, "fetch", "-q", remote, seconds=FETCH_FIRST_SECONDS)
    if done.returncode != 0:
        return (f"could not fetch {key} from {remote} before the card started, so it builds on what "
                f"this computer has: {said_of(done)}")
    # c-734 r1.F4: a fetch never moves `refs/remotes/<remote>/HEAD`, so the remote's default is
    # asked again here; a remote that will not say leaves the last one, which is checked anyway
    run(repo, "remote", "set-head", remote, "--auto", seconds=FETCH_FIRST_SECONDS)
    # r1.F10: the base is moved whatever happened to the trunk, and what each said is joined
    notes = []
    for step in (lambda: forward(repo, remote, key), lambda: forward_base(repo, remote, key, base)):
        try:
            said = step()
        except merging.MergeRefused as error:
            said = f"{key} was fetched but its copy was not moved: {str(error).splitlines()[0]}"
        if said:
            notes.append(said)
    return "; ".join(notes) or None


def forward_base(repo: Path, remote: str, key: str, base: str | None) -> str | None:
    """c-732: a card that names a base the copy does not have out starts from it, so that
    branch is moved up to the remote's too, when it is strictly behind, by `update-ref`, and
    only when no working tree has it out (r1.F9, `merging.checked_out`). A base the copy has
    no branch of is cut from the remote's."""
    if not base or base == merging.trunk_of(repo):
        return None
    mine, theirs = f"refs/heads/{base}", f"refs/remotes/{remote}/{base}"
    if not merging.has_ref(repo, mine) or not merging.has_ref(repo, theirs) or merging.ancestor(repo, theirs, mine):
        return None
    if not merging.ancestor(repo, mine, theirs):
        return (f"{key}'s {base} on this computer and {remote}'s have each moved, so the card builds "
                f"on this computer's")
    where = merging.checked_out(repo, base)
    if where:       # r1.F9: never moved under a working tree that has it out
        return (f"{base} is checked out in {where}, so it was not moved up to {remote}'s and the card "
                f"builds on this computer's {base}")
    merging.git(repo, "update-ref", mine, merging.git(repo, "rev-parse", theirs), merging.git(repo, "rev-parse", mine))
    return None


def forward(repo: Path, remote: str, key: str) -> str | None:
    """Fast-forward the branch the copy has out to the remote's, when it is strictly behind."""
    branch = merging.trunk_of(repo)
    theirs = f"refs/remotes/{remote}/{branch}"
    if branch == "HEAD" or not merging.has_ref(repo, theirs) or merging.ancestor(repo, theirs, branch):
        return None
    if not merging.ancestor(repo, branch, theirs):
        return (f"{key}'s {branch} on this computer and {remote}'s have each moved, so the card builds "
                f"on this computer's; a Push brings the two together")
    if merging.git(repo, "status", "--porcelain", "--untracked-files=no"):
        return f"Shipyard's copy of {key} has changes that were never committed, so {remote}'s commits were not taken"
    merging.git(repo, "merge", "--ff-only", "--quiet", theirs)
    return None


# ----- the push after a landing -----

def landed(cfg, card: dict) -> tuple | None:
    """`(repo, key, branch, remote, sha)` of a done card whose landing was a local merge in a
    copy Keel may push from, with the space's switch on. None for any other card."""
    space = (getattr(cfg, "spaces", None) or {}).get(card.get("space") or "")
    landing = (card.get("options") or {}).get("landing") or {}
    published = str(landing.get("published") or "")
    found = receipt.MERGED_INTO.search(published)
    sha = landing.get("merge") or landing.get("sha")
    if (card.get("stage") != "done" or space is None or not getattr(space, "offer_push", False)
            or landing.get("state") != "landed" or not found or not sha
            or not published.endswith(receipt.NOT_PUSHED)):
        return None
    key = repocommands.first(card.get("repo"))
    repo = applies(cfg, space.name, key)
    return (repo, key, found.group(1), remote_of(cfg, space.name), str(sha)) if repo is not None else None


def offer(cfg, card: dict) -> dict | None:
    """What a landed card says about its push: `{repo, branch, remote, pushed, said}`, or None
    where no push is offered. `pushed` is read from git: the landed commit is in the copy's
    remote-tracking branch, as of the last fetch or push."""
    found = landed(cfg, card)
    if found is None:
        return None
    repo, key, branch, remote, sha = found
    theirs = f"refs/remotes/{remote}/{branch}"
    try:
        pushed = merging.has_ref(repo, theirs) and merging.ancestor(repo, sha, theirs)
    except merging.MergeRefused:
        return None
    said = f"Pushed: {remote} has it." if pushed else f"Merged into {branch} on this computer."
    testing, refused = (False, None) if pushed else standing(cfg, card)
    return {"repo": key, "branch": branch, "remote": remote, "pushed": pushed, "said": said,
            "testing": testing, "refused": refused}


def state_of(card: dict) -> dict:
    return (card.get("options") or {}).get(PUSH) or {}


def mark(board, card_id: str, state: dict) -> None:
    board.set_fields(card_id, {"options": {PUSH: dict(state, at=now())}}, "drain")


def born(pid) -> float | None:
    """When the process `pid` started, as the system says (seconds since the epoch), or None
    where it cannot say (no such process, no `ps`)."""
    try:
        done = subprocess.run(["ps", "-o", "lstart=", "-p", str(int(pid))], capture_output=True, text=True,
                              timeout=5, env=dict(os.environ, LC_ALL="C", LANG="C"))
        said = " ".join(done.stdout.split())
        return time.mktime(time.strptime(said, "%a %b %d %H:%M:%S %Y")) if done.returncode == 0 and said else None
    except (OSError, ValueError, TypeError, subprocess.SubprocessError):
        return None


def stale(state: dict) -> bool:
    """A testing mark with no pid that no worker took in `TAP_SECONDS`: none will now."""
    from keel import landing     # noqa: PLC0415 - see `gone`
    return not state.get("pid") and landing.age_seconds(state.get("at")) > TAP_SECONDS


def gone(cfg, state: dict) -> bool:
    """A push marked testing whose worker is no longer there to answer (`landing.dead`: its
    pid is not running, or it never wrote one in five minutes). A pid alone is not the
    worker (review r2.F10): the number is handed out again, so the worker writes when it
    started beside it, and a process with that pid that started at another time is someone
    else. Where the system cannot say when a process started, the pid is believed."""
    from keel import landing     # noqa: PLC0415 - landing reads adapters, which reads this module
    if state.get("state") != TESTING:
        return False
    if landing.dead(cfg, state) or stale(state):
        return True
    if state.get("host") != cfg.host or not state.get("pid") or state.get("started") is None:
        return False
    started = born(state["pid"])
    return started is not None and abs(started - float(state["started"])) > BORN_SLACK


def standing(cfg, card: dict) -> tuple[bool, dict | None]:
    """`(testing, refused)` as the card's mark stands: a worker that is running, or the last
    refusal (`{error, kind, fetch}`; `fetch` says the try again is the worker's again). A mark
    whose worker died is read as a refusal, so nothing shows as testing for ever."""
    state = state_of(card)
    if state.get("state") == TESTING:
        return (False, {"error": GONE, "kind": "failed", "fetch": True}) if gone(cfg, state) else (True, None)
    if state.get("state") == REFUSED:
        return False, {"error": state.get("why") or "the push was refused", "kind": state.get("kind") or "failed",
                       "fetch": bool(state.get("fetch"))}
    return False, None


def must_have(cfg, card: dict) -> tuple:
    found = landed(cfg, card)
    if found is None:
        raise PushRefused(f"{card['id']} has nothing to push: a Push is for a card whose work was merged "
                          f"on this computer, in a repo Shipyard copied, in a space with no connection")
    return found


def push(cfg, card: dict, fetch: bool = False, board=None) -> dict:
    """Push the branch a card landed on, plainly: `land.push` {id}, inside the tap, since a
    push that needs no merge is one git command. With `fetch` (the worker's, `work`) the
    remote's commits are fetched and merged in first (`bring_in`). With a board, a refusal
    of the plain push is kept on the card, so the page still says it after a reload."""
    repo, key, branch, remote, _ = must_have(cfg, card)
    if fetch:
        bring_in(cfg, card, repo, key, branch, remote, board)
    elif board is not None and state_of(card).get("state") == TESTING and not gone(cfg, state_of(card)):
        # review r2.F10: a worker is on it; a plain push beside it would write over its mark
        raise PushRefused(BUSY.format(card=card["id"]))
    done = push_by_address(repo, remote, branch)
    if done.returncode != 0:
        behind = any(word in (done.stderr or "") for word in REJECTED)
        refused = PushRefused(BEHIND.format(remote=remote), {"kind": "behind"}) if behind else \
            PushRefused(f"git could not push {branch} to {remote}: {said_of(done)}", {"kind": "failed"})
        if board is not None and not fetch:
            mark(board, card["id"], {"state": REFUSED, "kind": refused.detail["kind"], "why": str(refused)})
        raise refused
    if board is not None and not fetch:
        mark(board, card["id"], {"state": PUSHED})
    return {"pushed": branch, "remote": remote, "note": f"{branch} is pushed to {remote}"}


# ----- the push that brings in the remote's commits: a worker of its own (review F10) -----
#
# Fetching, merging, preparing and testing can take as long as the repo's whole suite. It ran
# inside the deck's request, under the lock every setup verb waits on. Now the verb marks the
# card (`options.push = {state: "testing"}`) and returns, the way Approve hands a landing to
# `keel/landing.py`'s worker; `python3 -m keel.landpush <card>` does the work in a session of
# its own and answers on the card, with a note and the mark.

def spawn(cfg, card_id: str, tap: int) -> int:
    from keel import landing     # noqa: PLC0415 - see `gone`
    return landing.spawn(cfg, card_id, "--tap", str(tap), module="keel.landpush")


def asked(cfg, board, card: dict, tap) -> bool:
    """Whether the user's tap asked for this worker, and no worker has taken it yet: the
    event `tap` is the user's own on this card, and the card's mark is `testing` for this
    machine, names that event, and carries no pid."""
    state = state_of(card)
    try:
        tap = int(tap)
    except (TypeError, ValueError):
        return False
    if (state.get("state") != TESTING or state.get("host") != cfg.host or state.get("pid")
            or state.get("tap") != tap or stale(state)):
        return False
    return board.conn.execute(PROOF, (tap, card["id"])).fetchone() is not None


def take(cfg, board, card_id: str, tap: int, pid: int) -> bool:
    """The worker's pid written on the mark it was started for, in one conditional write
    (`TAKE`). False when the mark is no longer the untaken one: another worker has it."""
    state = {"state": TESTING, "host": cfg.host, "tap": int(tap), "pid": pid, "started": born(pid), "at": now()}
    with board.tx():
        taken = board.conn.execute(TAKE, (json.dumps(state), state["at"], card_id, int(tap), cfg.host)).rowcount == 1
        if taken:
            board.record_event(card_id, "set", "drain", data={"options": {PUSH: state}})
    return taken


def start(cfg, board, card: dict) -> dict:
    """`land.push` {id, fetch: true}: start the worker and return at once."""
    remote = must_have(cfg, card)[3]
    state = state_of(card)
    if state.get("state") == TESTING and not gone(cfg, state):
        raise PushRefused(BUSY.format(card=card["id"]))
    with board.tx():        # the user's own event: what the worker must be shown (review r2.F2)
        tap = board.record_event(card["id"], "note", "human", text=ASKED_FOR.format(remote=remote),
                                 data={PUSH: ASKED})
    mark(board, card["id"], {"state": TESTING, "host": cfg.host, "tap": tap})
    try:
        spawn(cfg, card["id"], tap)
    except OSError as error:
        why = f"the push could not be started on this computer: {error}"
        mark(board, card["id"], {"state": REFUSED, "kind": "failed", "why": why, "fetch": True})
        raise PushRefused(why, {"kind": "failed"}) from None
    return {"push": TESTING, "note": STARTED.format(remote=remote)}


def work(cfg, board, card_id: str, tap=None) -> int:
    """The worker: fetch, merge, prepare, test and push, under the checkout's lock (one
    landing, pre-run or push per checkout at a time, `landing.repo_lock`). 0 when it pushed,
    1 when it did not; either way the card says so and the mark is no longer `testing`. Its
    pid goes on the card before it waits on the lock, so a queued one is not taken for dead.

    It runs only for the user's tap (`asked`): shown none, it writes nothing and pushes
    nothing. Every read of the card is inside the `try`, so a card that cannot be read ends
    the worker with a line in its log and no traceback."""
    from keel import landing     # noqa: PLC0415 - see `gone`
    taken = False
    try:
        card = board.get(card_id)
        if not asked(cfg, board, card, tap):
            print(UNASKED.format(card=card_id), flush=True)
            return 1
        if not take(cfg, board, card_id, tap, os.getpid()):
            print(UNASKED.format(card=card_id), flush=True)
            return 1
        taken = True
        with landing.repo_lock(cfg, card):
            done = push(cfg, board.get(card_id), fetch=True, board=board)
    except PushRefused as refused:
        kind = (refused.detail or {}).get("kind") or "failed"
        return answer(board, card_id, {"state": REFUSED, "kind": kind, "why": str(refused), "fetch": True},
                      f"the push did not happen: {refused}")
    except Exception as error:      # noqa: BLE001 - whatever stopped it, the card must not say testing
        why = f"the push stopped: {type(error).__name__}: {str(error).splitlines()[0] if str(error) else 'no reason'}"
        print(f"keel.landpush: {card_id}: {why}", flush=True)
        if not taken and not retaken(cfg, board, card_id, tap):
            return 1        # it was never shown the tap, so the card is not this worker's to write
        return answer(board, card_id, {"state": REFUSED, "kind": "failed", "why": why, "fetch": True}, why)
    mark(board, card_id, {"state": PUSHED})
    board.note(card_id, f"{done['note']}, with {done['remote']}'s commits merged in", "drain")
    return 0


def retaken(cfg, board, card_id: str, tap) -> bool:
    """A worker stopped before it took its tap asks once more whether the tap is its own, so
    a card it could not read the first time is still answered and does not say testing for
    five minutes."""
    with contextlib.suppress(Exception):
        return asked(cfg, board, board.get(card_id), tap)
    return False


def answer(board, card_id: str, state: dict, said: str) -> int:
    """The worker's refusal, on the mark and as a note; 1. Neither write may raise out of
    the worker."""
    with contextlib.suppress(Exception):
        mark(board, card_id, state)
    with contextlib.suppress(Exception):
        board.note(card_id, said, "drain")
    return 1


def bring_in(cfg, card: dict, repo: Path, key: str, branch: str, remote: str, board=None) -> None:
    """Fetch, and merge the remote's commits into the copy's branch when it lacks them: built
    on a temporary tree and tested there, and the branch moves only if it has not moved
    meanwhile. `PushRefused` says why nothing was merged; the copy is then as it was."""
    done = run(repo, "fetch", "-q", remote)
    if done.returncode != 0:
        raise PushRefused(f"git could not fetch from {remote}: {said_of(done)}", {"kind": "failed"})
    theirs = f"refs/remotes/{remote}/{branch}"
    try:
        out = merging.trunk_of(repo)
        if out != branch:
            raise PushRefused(f"Shipyard's copy of {key} has {out} out, not {branch}, so nothing was merged or pushed")
        base = merging.base_of(repo, branch)
        if not merging.has_ref(repo, theirs) or merging.ancestor(repo, theirs, base):
            return
        if merging.git(repo, "status", "--porcelain", "--untracked-files=no"):
            raise PushRefused(f"Shipyard's copy of {key} has changes that were never committed, so {remote}'s "
                              f"commits were not merged in and nothing was pushed")
        merged = merge_theirs(cfg, card, repo, key, base, theirs, branch, remote, board)
        if not merging.settle(repo, branch, base, merged):
            raise PushRefused(f"{branch} moved while {remote}'s commits were being merged in, so nothing "
                              f"was pushed; try again")
    except merging.MergeRefused as error:
        raise PushRefused(f"{remote}'s commits were not merged in, so nothing was pushed: "
                          f"{str(error).splitlines()[0]}") from None


def merge_theirs(cfg, card: dict, repo: Path, key: str, base: str, theirs: str, branch: str, remote: str,
                 board=None) -> str:
    """The merge of the remote's branch onto `base`, on a temporary tree, with the repo's
    tests run on it. Its sha; the tree is gone when this returns, either way. `board` is the
    worker's, so the repo file's record is read on it (review r2.F8)."""
    command, refused = repocommands.landing(cfg, card.get("space"), key, board)     # one reading
    if refused:         # as a landing is refused: Keel cannot know what to test on the merged tree
        raise PushRefused(repocommands.NOT_PUSHED.format(name=key), {"kind": "failed"})
    tree = merging.trial_path(cfg, card["id"])
    merging.drop_tree(repo, tree)
    tree.parent.mkdir(parents=True, exist_ok=True)
    merging.git(repo, "worktree", "add", "--detach", str(tree), base)
    try:
        try:
            merging.git(tree, "merge", theirs, "-m", f"Merge {remote}/{branch} into {branch}")
        except merging.MergeRefused as error:
            real = merging.conflicted(tree, error)
            merging.abort_merge(tree)
            if not real:
                raise
            raise PushRefused(SAME_LINES.format(remote=remote, key=key), {"kind": "conflict"}) from None
        merged = merging.git(tree, "rev-parse", "HEAD")
        if command:
            try:
                merging.prepare_merged(cfg, card, tree)
                merging.run_tests(command, tree, base, seconds=cfg.merge_test_seconds)
            except merging.MergeRefused as error:
                raise PushRefused(f"the tests failed with {remote}'s commits merged in (`{command}`), so "
                                  f"nothing was merged or pushed: {str(error).splitlines()[0]}",
                                  {"kind": "tests"}) from None
        return merged
    finally:
        merging.drop_tree(repo, tree)


# ----- the screen: keeping work on this computer, on Where finished work goes -----

def copied(cfg, space_name: str) -> list[tuple]:
    """`(key, repo)` of each repo of a space that Keel may fetch and push."""
    space = cfg.spaces.get(space_name)
    return [(key, repo) for key in (space.repos if space else ())
            if (repo := applies(cfg, space_name, key)) is not None]


def check(cfg, space_name: str) -> list[dict]:
    """`land.push.check` {space}: "This computer can push to origin", per copied repo, by a
    dry run of the push. It changes nothing at the remote."""
    if space_name not in cfg.spaces:
        raise SetupError(f"there is no space {space_name!r}")
    remote = remote_of(cfg, space_name)
    rows = []
    for key, repo in copied(cfg, space_name):
        try:
            branch = merging.usual_branch(cfg, space_name, repo)
        except merging.MergeRefused as error:
            rows.append({"key": key, "ok": False, "why": str(error).splitlines()[0]})
            continue
        done = push_by_address(repo, remote, branch, dry=True)
        ok = done.returncode == 0 or any(word in (done.stderr or "") for word in REJECTED)
        rows.append({"key": key, "ok": ok, "host": host_of(repo, remote),
                     "why": f"{key} can push {branch} to {remote}" if ok
                     else f"git could not reach {remote} to push {key}: {said_of(done)}"})
    return rows


def host_of(repo: Path, remote: str) -> str | None:
    done = run(repo, "remote", "get-url", remote)
    return cloneerrors.host_of(done.stdout.strip()) if done.returncode == 0 else None


def panel(cfg) -> dict:
    """`start.lands` on the Setup report: for each space with no pack, its remote, its two
    switches and each copied repo with the host its address is on and the branch a card naming
    no base lands on (`merging.usual_branch`, c-734: the remote's default, not the checkout)."""
    found = {}
    for name, space in cfg.spaces.items():
        if space.adapter_dir is not None:
            continue
        remote, repos = remote_of(cfg, name), []
        for key, repo in copied(cfg, name):
            try:
                branch = merging.usual_branch(cfg, name, repo)
            except merging.MergeRefused:
                branch = None
            repos.append({"key": key, "host": host_of(repo, remote), "branch": branch})
        found[name] = {"remote": remote, "repos": repos, "fetch": bool(getattr(space, "fetch_before_work", False)),
                       "push": bool(getattr(space, "offer_push", False))}
    return found


def card_of(board, body: dict) -> dict:
    return board.get(str(body.get("id") or ""))


def tap(cfg, board, body: dict) -> dict:
    """`land.push` {id, fetch?}: the plain push in the tap, or the worker started."""
    card = card_of(board, body)
    return start(cfg, board, card) if body.get("fetch") else push(cfg, card, board=board)


VERBS = {
    "land.push": lambda cfg, body, board: tap(cfg, board, body),
    "land.push.check": lambda cfg, body, board: {"checks": check(cfg, str(body.get("space") or ""))},
}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="keel.landpush", description="bring in the remote's commits and push one card's landing")
    parser.add_argument("card")
    parser.add_argument("--tap", type=int, default=None,
                        help="the id of the event the user's Push left on the card; without it nothing is pushed")
    args = parser.parse_args(argv)
    cfg = config_module.load()
    with open_board(cfg) as board:
        return work(cfg, board, args.card, args.tap)


if __name__ == "__main__":
    raise SystemExit(main())
