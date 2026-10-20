"""Stacked cards, as a drain step (c-718): what happens to a card stacked on another when that
card lands, moves or is dropped.

A stacked card's branch is cut from its parent's and its change aims at the parent's branch
(`keel/stacking.py`). Each drain pass looks at every stacked card of a space it serves that is
not done or archived, and at what its parent's own card says (`derived.stack`):

- **The parent is DROPPED** (archived, or gone from the board): the card is blocked once,
  with one sentence saying so and the two ways on (`DROPPED`). A card already blocked is left
  as it is, and one the owner unblocked is not blocked again for the same parent.
- **The parent has LANDED** (done): two things, each once.
  1. Its change is aimed at the base: the pack's `ship <id> restack`, for a card that records
     a change (`options.pr` or `options.prs`). The code host is not relied on to do it. A
     restack that fails is logged and tried again on the next pass, and said on the card once.
  2. Its house is told, by a message into its own session, that the parent landed, that its
     change now aims at the base, and how to move the branch onto the base with only its own
     commits (`LANDED`): `git rebase --onto` past the fork point, then a push with a lease.
     That is the same command for a squash merge and a merge commit, so the house need not
     tell them apart. At shipping only the owner's Ship pushes, so the house is told to leave
     the branch alone, and Keel says the commands by hand where it says every other branch out
     of step (`keel/shipstep.py`, the restack entry). A card that never started needs nothing
     here: it is cut from the base when it starts.
- **The parent's branch MOVED** (a review fix the owner's Ship pushed, `options.shipping.heads`)
  and the card's worktree does not hold the new head: its house is told once per head
  (`MOVED`), to merge the parent's branch in, never to rebase what it has pushed.

NOTHING HERE STOPS, RESUMES OR STARTS A HOUSE. A tell goes only into a house the harness lists
idle with a process behind it, and each one takes a house slot as any turn does; a WORKING
house waits for a later pass. An exited house at planning or building waits too, since the
drain puts it back; any other house that is not running is not woken: the card gets the words
as a note instead. Every once-only step is marked by the note or block it writes (its data
carries `stack`), so there is no second record.
"""

from __future__ import annotations

import json
import shlex
import subprocess
import traceback
from datetime import datetime
from pathlib import Path

from keel import adapters, harness, house, housejobs, stacking, tellhouse, terms
from keel.board import Refused
from keel.config import Config, remote_of

SHIP_VERB = "ship"
RESTACK = "restack"
RESTACK_SECONDS = 180
# r1.F11, r2.F7: a restack that fails waits RESTACK_WAIT seconds, doubling each time, and after
# RESTACK_TRIES failures in a row the card is blocked once with the reason. Each failure is a
# mark on the card (`n`, `at`), so the count and the next try survive a restarted drain; the
# owner's unblock after the block starts the count again.
RESTACK_WAIT = 120
RESTACK_TRIES = 3
GIT_SECONDS = 30
LOG_NAME = "drain.log"
MARK = "stack"
# A house that is not running at these stages is put back by the drain: its tell waits for it.
PUT_BACK = ("planning", "building")

DROPPED = ("{parent}, the card this one is stacked on, was dropped, so the branch it is cut "
           "from will not merge. Make it independent (`kb set {id} options.stack=independent`), "
           "or archive it.")
LANDED = ("Keel, for {id}: {parent}, the card this one is stacked on, has merged into {base}. "
          "{aimed}Your branch was cut from {parent}'s branch, so it still carries {parent}'s commits as "
          "they were before the merge. {how}")
HOW_MOVE = ("Move it onto {base} with only your own commits, then push it with a lease, one command "
            "per repo, run in that repo's worktree:\n\n{commands}\n\nEach fetches the base and {parent}'s "
            "last head first, and stops before the rebase when that head still cannot be read (the remote "
            "may have deleted {parent}'s branch): then find the commit where your branch left it (`git log "
            "--oneline`) and run the rebase and the push with that commit in place of \"$fork\". After a merge commit the result is the same as a plain rebase; "
            "after a squash merge it is the only way that keeps {parent}'s old commits out of your {change}.")
# r1.F3: one per repo, with that repo's head, the fork point checked before it is used
# r2.F3: the base fetched by its full refspec, as `shipstep.chain` does, so a clone with a
# narrowed refspec never replays onto a stale ref; r2.F4: the parent's head fetched, by its
# branch or by sha, when the clone lacks it, before the fork point is worked out
FETCH_BASE = "git fetch {remote} {spec}"
ONE_MOVE = ("- {repo}: `{fetch} && {{ git cat-file -e {head}^{{commit}} 2>/dev/null || git fetch {remote} "
            "{parent_spec} || git fetch {remote} {head}; }} && fork=$(git merge-base HEAD {head}) && test -n "
            "\"$fork\" && git rebase --onto {remote}/{base} \"$fork\" && git push --force-with-lease "
            "--force-if-includes {remote} HEAD`")
NO_MOVE = ("- {repo}: Shipyard has no pushed head of {parent} in this repo, so it gives no command: "
           "`{fetch}`, then rebase past the commit where you left {parent}'s branch (`git rebase --onto "
           "{remote}/{base} <that commit>`), then push with `git push --force-with-lease --force-if-includes {remote} HEAD`")
# r2.F6: a pull request the host closed when the parent's branch went (or that was declined)
CLOSED = ("{parent} merged, and this card's {change} {which} {is_} no longer open ({states}), so "
          "nothing was aimed at {base} and the house is told nothing yet. Reopen {it}, or open a new "
          "one from this card's branch against {base}, then unblock the card.")
RESTACK_BLOCKED = ("{parent} merged, and aiming this card's {change} at its base failed {n} times "
                   "({why}). Aim it at {base} on the code host, then unblock the card.")
HOW_SHIPPING = ("This card is at shipping, where only the user's Ship pushes: leave the branch as it is. "
                "Shipyard gives the user the commands that move it, where it says a branch is out of step.")
NO_HEAD = ("Move it onto {base} with only your own commits: `{fetch}`, then rebase past the commit where "
           "you left {parent}'s branch (`git rebase --onto {remote}/{base} <that commit>`), then push it with "
           "`git push --force-with-lease --force-if-includes {remote} HEAD`.")
MOVED = ("Keel, for {id}: {parent}'s branch {branch}, which this card is stacked on, moved (now "
         "{short}), and your branch does not have its new commits yet. Bring them in with a merge, "
         "never a rebase of what you pushed: `git fetch {remote} {branch} && git merge "
         "{remote}/{branch}`, then carry on.{shipping}")
MOVED_SHIPPING = " At shipping, commit the merge and let the user's Ship push it."


def now() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


def log(cfg: Config, text: str) -> None:
    cfg.logs_dir.mkdir(parents=True, exist_ok=True)
    with open(cfg.logs_dir / LOG_NAME, "a") as handle:
        handle.write(f"{now()} stacking: {text}\n")


def upkeep(cfg: Config, board, served: set[str], rows: list[dict], slots: int) -> dict:
    """One pass over the stacked cards. `slots`: how many idle houses a tell may wake into a
    turn (the house pool's room and the memory gate). Never raises for one card."""
    out = {"told": [], "noted": 0, "restacked": 0, "blocked": 0}
    for card in board.list_cards():
        found = stacking.of(card)
        if not (found and found.get("choice") == stacking.STACKED and found.get("on")):
            continue
        if card["stage"] == "done" or card["derived"]["archived"] or card["space"] not in served:
            continue
        try:
            one(cfg, board, card, found, rows, out, slots)
        except Exception:  # noqa: BLE001 - one card must not stop the others
            log(cfg, f"{card['id']} failed:\n" + traceback.format_exc().strip())
    tellhouse.join()
    return out


def one(cfg: Config, board, card: dict, found: dict, rows: list[dict], out: dict, slots: int) -> None:
    if found.get("landed"):         # r1.F5: landed first, whatever became of the parent since
        landed(cfg, board, card, found, rows, out, slots)
    elif found.get("dropped"):
        if dropped(board, card, found):
            out["blocked"] += 1
    elif found.get("heads"):
        moved(cfg, board, card, found, rows, out, slots)


# ----- what the card already says: the once-only marks -----

def marks(board, card_id: str, parent: str) -> list[dict]:
    """The `stack` data of every note and block on the card about this parent, oldest first."""
    found = []
    for event in board.events(card_id):
        data = event.get("data")
        if isinstance(data, str):
            try:
                data = json.loads(data)
            except ValueError:
                continue
        mark = (data or {}).get(MARK) if isinstance(data, dict) else None
        if isinstance(mark, dict) and mark.get("parent") == parent:
            found.append(mark)
    return found


def marked(board, card_id: str, parent: str, event: str, head: str | None = None) -> bool:
    return any(m.get("event") == event and (head is None or m.get("head") == head)
               for m in marks(board, card_id, parent))


# ----- dropped -----

def dropped(board, card: dict, found: dict) -> bool:
    parent = found["on"]
    if card.get("blocked_reason") or marked(board, card["id"], parent, "dropped"):
        return False
    board.block(card["id"], DROPPED.format(parent=parent, id=card["id"]), "drain",
                data={MARK: {"parent": parent, "event": "dropped"}})
    return True


# ----- landed -----

def has_change(card: dict) -> bool:
    options = card.get("options") or {}
    return bool(options.get("pr") or options.get("prs"))


def landed(cfg: Config, board, card: dict, found: dict, rows: list[dict], out: dict, slots: int) -> None:
    parent = found["on"]
    if not (card.get("session_id") or has_change(card)):
        return                     # never started: it is cut from the base when it starts
    if card.get("blocked_reason"):
        return                     # the owner's to answer first (a failed restack, a closed change)
    answer = None
    if has_change(card) and not marked(board, card["id"], parent, "retargeted"):
        if not restack_due(board, card["id"], parent):
            return                 # r1.F11: backing off
        answer = restack(cfg, board, card, parent)
        if answer is None:
            return                 # tried again later
        out["restacked"] += 1
        if closed_change(cfg, board, card, parent, answer):
            return                 # r2.F6: no rebase tell until the owner answers
    if marked(board, card["id"], parent, "landed"):
        return
    answer = answer or last_answer(board, card["id"], parent)
    text = landed_text(cfg, card, found, answer)
    said = tell(cfg, board, card, rows, text, slots - len(out["told"]))
    if said is None:
        return
    counted(out, card["id"], said)
    board.note(card["id"], f"{parent} merged: " + said_how(said, text), "drain",
               data={MARK: {"parent": parent, "event": "landed"}})


def counted(out: dict, card_id: str, said: str) -> None:
    if said == "told":
        out["told"].append(card_id)
    else:
        out["noted"] += 1


def said_how(said: str, text: str) -> str:
    return ("told the house in its session" if said == "told"
            else "the house is not running, so this note says it: " + text)


def restack(cfg: Config, board, card: dict, parent: str) -> dict | None:
    """The pack's `ship <id> restack`, and one note with its answer (the mark), or None when it
    failed: logged every time, said on the card the first time."""
    space = cfg.spaces[card["space"]]
    change = terms.of(cfg, card["space"])["change"]
    try:
        answer = json.loads(adapters.run(space, SHIP_VERB, card["id"], RESTACK, timeout=RESTACK_SECONDS) or "{}")
    except (adapters.AdapterError, ValueError) as error:
        why = (str(error).splitlines() or [type(error).__name__])[0]
        log(cfg, f"could not aim {card['id']}'s {change} at its base: {why}")
        restack_failed(board, card, parent, change, why)
        return None
    moved_ = answer.get("retargeted") or []
    kept = answer.get("kept") or []
    said = [f"{change} #{one.get('pr')} in {one.get('repo')} now aims at {one.get('to')}" for one in moved_]
    said += [f"{change} #{one.get('pr')} in {one.get('repo')} left: {one.get('why')}" for one in kept]
    board.note(card["id"], f"{parent} merged into {answer.get('base')}: " + ("; ".join(said) or "nothing to aim"),
               "drain", data={MARK: {"parent": parent, "event": "retargeted", "base": answer.get("base"),
                                     "retargeted": moved_}})
    return answer


def failures(board, card_id: str, parent: str) -> list[dict]:
    """r2.F7: the restack failures on the card since its last restack block (the owner's
    unblock after it starts again), each mark carrying `n` and `at`."""
    found = []
    for mark in marks(board, card_id, parent):
        if mark.get("event") == "restack-blocked":
            found = []
        elif mark.get("event") == "restack-failed":
            found.append(mark)
    return found


def restack_due(board, card_id: str, parent: str) -> bool:
    """r1.F11: not before the last failure's back-off has passed, by the board's clock."""
    seen = failures(board, card_id, parent)
    if not seen:
        return True
    last = seen[-1]
    try:
        at = datetime.fromisoformat(str(last.get("at")))
        now_ = datetime.fromisoformat(board.now())
    except ValueError:
        return True
    return (now_ - at).total_seconds() >= RESTACK_WAIT * 2 ** (int(last.get("n") or 1) - 1)


def restack_failed(board, card: dict, parent: str, change: str, why: str) -> None:
    """One mark per failure (`n`, `at`): the first said in full, the next ones short, and the
    card blocked once at `RESTACK_TRIES`."""
    n = len(failures(board, card["id"], parent)) + 1
    mark = {"parent": parent, "event": "restack-failed", "n": n, "at": board.now()}
    if n >= RESTACK_TRIES:
        base = stacking.options_of(card).get("base") or "its base"
        board.note(card["id"], f"aiming this card's {change} at its base failed again ({n} of {RESTACK_TRIES})",
                   "drain", data={MARK: mark})
        board.block(card["id"], RESTACK_BLOCKED.format(parent=parent, change=change, n=RESTACK_TRIES,
                                                       why=why, base=base), "drain",
                    data={MARK: {"parent": parent, "event": "restack-blocked"}})
    elif n == 1:
        board.note(card["id"], f"{parent} merged, and aiming this card's {change} at its base failed "
                               f"({why}); the drain tries again, waiting longer each time", "drain",
                   data={MARK: mark})
    else:
        board.note(card["id"], f"aiming this card's {change} at its base failed again ({n} of {RESTACK_TRIES})",
                   "drain", data={MARK: mark})


def closed_change(cfg: Config, board, card: dict, parent: str, answer: dict) -> bool:
    """r2.F6: a change the restack left because it is not open blocks the card once, with
    the sentence, and holds the rebase tell; True while it does."""
    shut = [one for one in answer.get("kept") or [] if one.get("state") and one["state"] != "open"]
    if not shut or marked(board, card["id"], parent, "closed"):
        return bool(shut) and bool(card.get("blocked_reason"))
    change = terms.of(cfg, card["space"])["change"]
    numbers = ", ".join(f"#{one.get('pr')} in {one.get('repo')}" for one in shut)
    board.block(card["id"], CLOSED.format(
        parent=parent, change=change, which=numbers, is_="is" if len(shut) == 1 else "are",
        states=", ".join(str(one["state"]) for one in shut), base=answer.get("base") or "its base",
        it="it" if len(shut) == 1 else "them"), "drain",
        data={MARK: {"parent": parent, "event": "closed"}})
    return True


def last_answer(board, card_id: str, parent: str) -> dict:
    found = [m for m in marks(board, card_id, parent) if m.get("event") == "retargeted"]
    return {"base": found[-1].get("base"), "retargeted": found[-1].get("retargeted") or []} if found else {}


def landed_text(cfg: Config, card: dict, found: dict, answer: dict) -> str:
    t = terms.of(cfg, card["space"])
    base = answer.get("base") or stacking.options_of(card).get("base") or "its base"
    remote = remote_of(cfg, card["space"])
    aimed = (f"Its {t['change']} now aims at {base}. " if answer.get("retargeted") else "")
    heads = found.get("heads") or {}
    if card["stage"] == "shipping":
        how = HOW_SHIPPING
    elif heads:
        how = HOW_MOVE.format(base=base, parent=found["on"], change=t["change"],
                              commands=move_commands(card, heads, base, remote, found["on"], found.get("branch")))
    else:
        how = NO_HEAD.format(base=base, remote=remote, parent=found["on"],
                             fetch=FETCH_BASE.format(remote=remote, spec=refspec(remote, base)))
    other = stacking.other_base(card)      # c-772: `base` is the one the parent merged into
    return LANDED.format(id=card["id"], parent=found["on"], base=base, aimed=aimed, how=how) + (
        f" {other} A repo {found['on']} never worked in needs nothing here." if other else "")


def refspec(remote: str, branch: str) -> str:
    """A branch's full refspec, quoted for the shell, as `shipstep.chain` fetches it."""
    return shlex.quote(f"+refs/heads/{branch}:refs/remotes/{remote}/{branch}")


def move_commands(card: dict, heads: dict, base: str, remote: str, parent: str,
                  parent_branch: str | None = None) -> str:
    """r1.F3: one line per repo of the card, each with THAT repo's pushed head of the parent.
    c-772: none for a repo the parent never named, where the card was cut from its own base
    and there is nothing of the parent's to move past."""
    lines = []
    fetch = FETCH_BASE.format(remote=remote, spec=refspec(remote, base))
    for repo in stacking.repos_of(card.get("repo")) or sorted(heads):
        if not stacking.stacked_in(card, repo):
            continue
        head = heads.get(repo)
        fill = {"repo": repo, "remote": remote, "base": shlex.quote(base), "parent": parent, "fetch": fetch}
        if head:
            spec = refspec(remote, parent_branch) if parent_branch else head
            lines.append(ONE_MOVE.format(head=head, parent_spec=spec, **fill))
        else:
            lines.append(NO_MOVE.format(**fill))
    return "\n".join(lines)


# ----- moved -----

def moved(cfg: Config, board, card: dict, found: dict, rows: list[dict], out: dict, slots: int) -> None:
    """The parent's branch pushed past what the card's worktree holds: told once per head."""
    parent = found["on"]
    for repo, head in sorted((found.get("heads") or {}).items()):
        root = worktree_of(card, repo)
        if root is None or holds(root, head) or marked(board, card["id"], parent, "moved", head):
            continue
        text = MOVED.format(id=card["id"], parent=parent, branch=found.get("branch"), short=head[:10],
                            remote=remote_of(cfg, card["space"]),
                            shipping=MOVED_SHIPPING if card["stage"] == "shipping" else "")
        said = tell(cfg, board, card, rows, text, slots - len(out["told"]))   # r1.F10: once
        if said is None:
            return
        counted(out, card["id"], said)
        board.note(card["id"], f"{parent}'s branch moved to {head[:10]}: " + said_how(said, text), "drain",
                   data={MARK: {"parent": parent, "event": "moved", "head": head}})


def worktree_of(card: dict, repo: str) -> Path | None:
    options = card.get("options") or {}
    recorded = (options.get("worktrees") or {}).get(repo) if isinstance(options.get("worktrees"), dict) else None
    primary = (card.get("repo") or "").split(",")[0].strip()
    path = recorded or (options.get("worktree") if repo == primary else None)
    return Path(str(path)) if path and Path(str(path)).is_dir() else None


def holds(root: Path, sha: str) -> bool:
    """Is `sha` in the worktree's history. A read that fails says yes: nothing is told on a
    guess."""
    try:
        done = subprocess.run(["git", "-C", str(root), "merge-base", "--is-ancestor", sha, "HEAD"],
                              capture_output=True, text=True, timeout=GIT_SECONDS)
    except (OSError, subprocess.SubprocessError):
        return True
    return done.returncode != 1


# ----- the tell -----

def tell(cfg: Config, board, card: dict, rows: list[dict], text: str, slots: int) -> str | None:
    """`told` when an idle running house was told `text` in its own session; `noted` when its
    house is not running and will not be put back (the caller notes the words); None when it
    must wait: a house in a turn, one the drain puts back, no room for a turn, or a tell refused."""
    row = harness.find(card.get("session_id") or "", rows)
    if housejobs.has_process(row):
        if housejobs.working(row) or slots <= 0:
            return None
        try:
            # r1.F4: tell only. The house is listed again at the tell, and one that exited
            # since the pass's snapshot is refused (`tellhouse.NotRunning`), never resumed; the
            # send runs in line, so the caller's mark is written only once it went
            tellhouse.deliver(cfg, board, card["id"], text, exited=tellhouse.REFUSE)
        except (house.Busy, house.InTerminal, Refused, harness.HarnessError, adapters.AdapterError, OSError) as error:
            log(cfg, f"{card['id']}'s house was not told: {error}")
            return None
        return "told"
    if card.get("session_id") and card["stage"] in PUT_BACK:
        return None
    return "noted"
