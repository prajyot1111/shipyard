"""The pull request watcher, as a drain upkeep step (lane SHIP; c-600: the house lives on).

A work card whose outcome he approved is at `shipping` from that Approve until its pull
request merges, and its build house lives on beside it: nothing ends it, rotates it or sends
the card back to building or review. On the machine that holds its house (the Mac: the code
host's credentials are there and never on the box), every drain pass asks, for each such
card of a space it serves:

1. **Is it time to look?** (`shipwatch.poll_due`, the cadence its module states). When it
   is, the adapter's `ship <id> poll` says what the code host shows, and `shipwatch.fold`
   folds it into the card's own record, `options.shipping`, written only when something
   changed. Every comment's whole text is kept in the card's `comments/<handle>.md`
   (`keep_whole`). When this process last looked is kept in memory (`LAST_POLLED`): it is
   a schedule, not state, and a restarted drain simply looks again.
2. **Merged, declined or reopened?** Merged: the card is done and its worktree is reaped
   (`ship <id> reap`, which keeps one with uncommitted work). Declined: a note, and the card
   stays at shipping with nothing to ship (Archive or Talk are his ways on); a pull request
   opened again is noted too.
3. **The worktrees' own facts** (`local_facts`, every pass, written only when they change):
   commits not on the pull request yet, commits the pull request's branch has that the
   worktree lacks (both at once is DIVERGED, c-653: that branch was rewritten outside Keel,
   said on the card with the commands that bring it in line by hand, `keel/shipstep.py`;
   nothing here ever moves a worktree), commits the
   review stamp does not cover, and whether the branch conflicts with its base. The deck's
   Ship says them. His Ship writes them too, read once the Ship is on the record
   (`after_ship`, c-660), and a pass that read the record before that Ship leaves them alone.
4. **Which waiting items are the house's to hear by themselves?** (`shipauto.settle`,
   c-655.) Only the kinds whose automatic handling is on for the card (review comments, and
   failing checks, each its space's setting with the card's own option over it, both off by
   default) stay in the batch; the others are kept on the card as `untold`, told to nobody,
   until he hands them over (the re-offer below) or turns the kind on.
5. **Is a batch due?** (`shipwatch.due`: 5 quiet minutes, 30 at most.) When it is and the
   drain is not paused, the waiting items are TOLD to the card's house (`deliver`): a
   message into its own session when it is idle, a resume when it exited (that needs a
   house slot and the memory gate like any start), and nothing yet when it is working (the
   batch waits; its Stop kicks this drain). A card with no session at all (one the shipping
   sync found) gets a house started with its brief and the batch.

A re-offer asked with `kb ship <id> reoffer` (c-651, `keel/shipreoffer.py`) makes the look
happen at once, whatever the cadence, and is answered on it (`looked`): the review the house
was never told, or was told and never judged (c-654), goes into the batch, due at once, and
the batch is marked as a re-offer. What the house is still on is left out (`offerable`),
and an item it judges before the batch is told is dropped from it (`still_unjudged`). A
look that fails keeps the ask for the next look at the cadence, and the third failed look
clears it with a note naming the failure (`look_failed`).

His own send-back (`kb ship <id> sendback`, c-663, `keel/shipsendback.py`) needs no look:
every pass puts what he sent into the batch as items of his own kind (`keep_sent_back`),
which no switch parks and which are due at once, and takes exactly those asks off the card.
From there it is an ordinary item of the batch: no hand-over mark is written for it.

Nothing here posts or pushes: his Ship does (`keel/shipreplies.py`, `Board.ship`). Nothing
here merges either: the merge is a colleague's, and the watcher only notices it.
"""

import json
import subprocess
import threading
import traceback
from datetime import datetime
from pathlib import Path

from keel import (adapters, dropin, harness, house, housejobs, merging, oldwords, shipauto, shipidle, shipreoffer,
                  shipreplies, shipround, shipsendback, shipwatch, stacking, tellhouse, terms)
from keel.board import REOFFER_OPTION, SENDBACK_OPTION, SHIPPING_OPTION, Refused
from keel.config import DEFAULT_REMOTE, Config, remote_of

SHIP_VERB = "ship"
LOG_NAME = "drain.log"
SHIP_SECONDS = 180
GIT_SECONDS = 60
# The same out-of-step sentence noted this lately is the same finding, made twice (`say_local`)
SAID_LATELY_SECONDS = 60
# His Ship's read of the worktrees after its push (`after_ship`): one deadline over all of it
AFTER_SHIP_SECONDS = 5
# When THIS process last looked at each card, by id. A schedule, not a record: see above.
LAST_POLLED: dict[str, datetime] = {}
# The notes are templates, filled with the card's space's words where they are said (c-630).
DECLINED = ("the {change} was declined: nothing is shipped from this card now; Archive "
            "puts it away, and Talk reaches its house")
REOPENED = "the {change} is open again, so the card is watched as before"
MERGED = "the {change} merged, so the card is done"


def now() -> datetime:
    return datetime.now().astimezone()


def log(cfg: Config, text: str) -> None:
    cfg.logs_dir.mkdir(parents=True, exist_ok=True)
    with open(cfg.logs_dir / LOG_NAME, "a") as handle:
        handle.write(f"{now().isoformat(timespec='seconds')} shipping: {text}\n")


# ----- which cards -----

def watched(cfg: Config, card: dict, served: set[str], board=None) -> bool:
    """A shipping card of a space this pass serves, whose adapter can look at pull requests,
    whose house is on this machine, and that is neither archived nor blocked (a blocked
    card is his until he unblocks it). One block is looked past (c-654 review): the drain's
    own, for items a re-offered batch's turn left unjudged (`shipreoffer.awaits_him`). That
    card is still looked at, so a merge still closes it and a decline is still said, and
    nothing is told to its house until he unblocks it (`tend`)."""
    space = cfg.spaces.get(card.get("space"))
    if card.get("stage") != "shipping" or space is None or card["space"] not in served:
        return False
    if card["derived"]["archived"]:
        return False
    if card.get("blocked_reason") and not (
            board is not None and shipreoffer.awaits_him(board.events(card["id"]))):
        return False
    return adapters.has_verb(space, SHIP_VERB)


def upkeep(cfg: Config, board, served: set[str], slots: int, at: datetime | None = None,
           skip=frozenset()) -> dict:
    """One pass over the shipping cards; `slots` is how many houses a batch may wake, told or
    resumed (the house pool's room and the memory gate, which the drain works out). Never raises
    for one card: a card that fails is logged and the next is looked at. `skip`: the cards
    the pass already acted on, whose re-offer is not settled early here (`shipidle.before_batch`);
    `closed` in the answer, when any: the cards whose house that settlement closed."""
    at = at or now()
    result = {"polled": 0, "told": [], "resumed": [], "merged": 0, "declined": 0}
    for card in board.list_cards(stage="shipping"):
        if not watched(cfg, card, served, board):
            continue
        try:
            said = tend(cfg, board, card, at, slots - len(result["told"]) - len(result["resumed"]), result,
                        card["id"] in skip)
        except Exception:  # noqa: BLE001 - one card must not stop the others
            log(cfg, f"{card['id']} failed:\n" + traceback.format_exc().strip())
            continue
        if said in ("told", "resumed"):
            result[said].append(card["id"])
    tellhouse.join()
    return result


# ----- one card -----

def look(cfg: Config, card: dict) -> tuple[dict | None, str]:
    """What the adapter says the code host shows (a sight), or None, logged, when it cannot,
    with why it could not (a re-offer's note says it, c-651)."""
    space = cfg.spaces[card["space"]]
    try:
        seen = json.loads(adapters.run(space, SHIP_VERB, card["id"], "poll", timeout=SHIP_SECONDS))
    except (adapters.AdapterError, ValueError) as error:
        why = (str(error).splitlines() or [type(error).__name__])[0]
        log(cfg, f"could not look at {card['id']}'s {terms.of(cfg, card['space'])['change']}: {why}")
        return None, why
    return (seen, "") if isinstance(seen, dict) else (None, "the adapter's answer is not a sight")


def keep_whole(cfg: Config, card: dict, seen: dict) -> None:
    """Every comment's whole text in the card's `comments/` (the card keeps a cut one), each
    file written only when it is missing or its text changed."""
    folder = cfg.card_dir(card["id"]) / shipwatch.COMMENTS_DIR
    for name, text in shipwatch.whole_texts(seen).items():
        path = folder / name
        try:
            if path.is_file() and path.read_text(errors="replace") == text:
                continue
            folder.mkdir(parents=True, exist_ok=True)
            path.write_text(text)
        except OSError as error:
            log(cfg, f"could not keep {card['id']}'s comment {name}: {error}")


def tend(cfg: Config, board, card: dict, at: datetime, slots: int, result: dict,
         skipped: bool = False) -> str | None:
    shipped = dict((card.get("options") or {}).get(SHIPPING_OPTION) or {})
    asked = (card.get("options") or {}).get(REOFFER_OPTION)
    auto = shipauto.for_card(cfg, card)
    # a fresh ask looks at once; after a failed look it waits for the cadence like any look
    if (asked and not asked.get("failed")) or shipwatch.poll_due(
            at, LAST_POLLED.get(card["id"]), shipauto.as_waiting(shipped, auto), cfg.ship_hours):
        LAST_POLLED[card["id"]] = at
        shipped, said = looked(cfg, board, card, shipped, asked, at, result)
        if said == "merged":
            result["merged"] += 1
            return merged(cfg, board, card)
        if said == "declined":
            result["declined"] += 1
    shipped = keep_local(cfg, board, card, shipped)
    shipped = keep_parked(board, card, shipped, auto)
    # a re-offer whose turn ended is settled before a batch behind it is told (c-666)
    shipped, wait, closed = shipidle.before_batch(cfg, board, card, shipped, at, slots, skipped)
    if wait:
        log(cfg, f"{card['id']}'s batch waits: {wait}")
    if closed:
        result.setdefault("closed", []).append(card["id"])   # the idle step skips it this pass
    shipped = keep_sent_back(cfg, board, card, shipped, at)
    reason = shipwatch.due(shipped, at)
    if reason is None or wait or cfg.drain_paused or shipped.get("state") == "declined":
        return None
    if card.get("blocked_reason"):
        return None                   # looked at for a merge only (`watched`); new review waits for him
    return deliver(cfg, board, card, shipped, reason, at, slots)


def looked(cfg: Config, board, card: dict, shipped: dict, asked: dict | None, at: datetime,
           result: dict) -> tuple[dict, str | None]:
    """One look at the code host, folded into the record (written only when it changed), and
    a re-offer asked answered on it; the record now, and what the look turned the card to."""
    seen, why = look(cfg, card)
    result["polled"] += 1
    if seen is None:
        if asked:
            look_failed(board, card, asked, why)
        return shipped, None
    keep_whole(cfg, card, seen)
    new, events = shipwatch.fold(shipped, seen, at)
    # what waits untold is held to this look, then each waiting item goes where its kind's
    # switch says: the batch, or kept untold (c-655)
    new = shipauto.reconcile(new, seen)
    left = shipauto.gone(shipped, new)
    new = shipauto.settle(new, shipauto.for_card(cfg, card))
    said = turned(board, card, shipped, new, events)
    items, no_base, busy = None, None, None
    if asked and not said:
        unjudged, busy = offerable(cfg, board, card, new)
        new, items, no_base = shipreoffer.fill(new, seen, asked, base_of(card, new), at, unjudged=unjudged)
    if new != shipped:
        new = board.keep_shipping(card["id"], shipped, new)
    if left and not said:
        board.note(card["id"], shipauto.GONE_NOTE.format(
            handles=", ".join(left), change=terms.of_board(board, card["space"])["change"]), "drain")
    if asked:
        reoffered(board, card, items or [], said, no_base, busy)
    return new, said


def keep_parked(board, card: dict, shipped: dict, auto: dict) -> dict:
    """A kind turned off while its items were in the batch: they leave it at once, with no
    look, and are kept untold (`shipauto.settle`, c-655). Turned on, the untold ones come
    back only on a look, which this pass or the next one at the waiting cadence makes."""
    new = shipauto.settle(shipped, auto, release=False)
    if new is not shipped:
        new = board.keep_shipping(card["id"], shipped, new)
    return new


def keep_sent_back(cfg: Config, board, card: dict, shipped: dict, at: datetime) -> dict:
    """His send-backs waiting on the card (`options.sendback`, c-663), put in the batch as
    items of his own (`shipsendback.fill`), then taken off the card by their handles
    (`Board.take_sendback`), so one he sent while this pass ran is the next pass's. Not on a
    card whose pull request was declined, and not while its house is ON a batch he
    re-offered: that mark is open (`shipreoffer.is_reoffer`, read only) and the harness,
    asked strictly, lists the session with a process behind it (`shipidle.on_its_batch`; a
    listing that fails holds for that pass). The ask stays on the card, said there
    (`shipsendback.held`). A turn that ended is settled before this runs
    (`shipidle.before_batch`, c-666), and a house that is not running is on nothing: his
    item then resumes it the ordinary way. The items are
    ordinary ones from here on: due at once (`shipwatch.due`), told when the house is out of
    its turn, and on no mark."""
    asks = (card.get("options") or {}).get(SENDBACK_OPTION) or []
    if not asks or shipped.get("state") == "declined" or (
            shipreoffer.is_reoffer(shipped) and shipidle.on_its_batch(cfg, card)):
        return shipped
    new, items = shipsendback.fill(shipped, asks)
    if items:
        new = board.keep_shipping(card["id"], shipped, new)
        board.note(card["id"], shipsendback.FILLED_NOTE.format(
            handles=", ".join(item["handle"] for item in items)), "drain")
    board.take_sendback(card["id"], [str(asked.get("handle")) for asked in asks])
    return new


def offerable(cfg: Config, board, card: dict, shipped: dict) -> tuple[list[str], str | None]:
    """What a re-offer may offer again of what the house was told: the handles with no
    verdict since they were told, but for the batch the house is still on, by the board's
    record of that batch's turn or by the harness listing the house in a turn
    (`shipreoffer.held`, c-654 review). And, when that left some out, the sentence saying so."""
    as_now, events = dict(card, options={SHIPPING_OPTION: shipped}), board.events(card["id"])
    row = harness.find(card.get("session_id") or "", harness.agents(cfg.spaces[card["space"]].config_dir))
    on = shipreoffer.held(shipped, events, working=housejobs.working(row))
    out = len(shipreplies.unjudged(as_now, events, batch=on)) if on else 0
    return shipreplies.unjudged(as_now, events, but=on), (shipreoffer.still_on(on, out) if out else None)


def base_of(card: dict, shipped: dict | None = None) -> str | None:
    """The branch the card's pull request merges into: the parent's branch while the card is
    stacked on a card that has not landed (c-718, `stacking.base_of`), else the owner's
    `options.base`, else the destination the pull request itself names, as the last look saw
    it (the record's `base`); None when none says, never a guess (c-651 review).

    This is the card's FIRST repo's: the record's `base` is that repo's pull request's. A
    card with a base per repo (c-772) is asked per repo through `repo_base`."""
    options = card.get("options") or {}
    record = shipped if shipped is not None else options.get(SHIPPING_OPTION) or {}
    return stacking.base_of(card) or options.get("base") or record.get("base") or None


def repo_base(cfg: Config, card: dict, repo: str | None, base: str | None) -> str | None:
    """c-772: `base`, the card's (`base_of`), as ONE repo of the card reads it. Every card but
    one stacked in only some of its repos has the one base. That card keeps `base` in its
    first repo, where the record names the pull request's own destination, and in any other
    repo the one rule answers (`merging.base_in`: the parent's branch only where the parent
    works, else that repo's own base). A repo that cannot be told (None) has no base here:
    None, which every reader takes as nothing known, never another repo's base."""
    if not stacking.split_repos(card)[1]:
        return base
    if repo is None:
        return None
    return base if repo in stacking.repos_of(card.get("repo"))[:1] else merging.base_in(cfg, card, repo)


def tree_base(cfg: Config, card: dict, root: Path, base: str | None) -> str | None:
    """`repo_base` for one worktree of the card, by the repo it is of (`plangate.repo_key_of`)."""
    if not stacking.split_repos(card)[1]:
        return base
    from keel import plangate     # noqa: PLC0415 - only a card with a base per repo reads it
    return repo_base(cfg, card, plangate.repo_key_of(card, root), base)


def look_failed(board, card: dict, asked: dict, why: str) -> None:
    """A re-offer whose look failed: kept for the next look at the cadence, or, the third
    time, cleared with a note naming the failure, so it never waits unseen (c-651). Written
    only while the card is still at shipping with that same ask (`Board.keep_reoffer`), so a
    block, an archive or a move meanwhile is never undone."""
    kept = shipreoffer.failed(asked, why)
    if board.keep_reoffer(card["id"], asked, kept) and kept is None:
        change = terms.of_board(board, card["space"])["change"]
        board.note(card["id"], shipreoffer.FAILED_NOTE.format(
            change=change, n=shipreoffer.FAILED_LOOKS, why=why), "drain")


def reoffered(board, card: dict, items: list[dict], said: str | None, no_base: str | None = None,
              busy: str | None = None) -> None:
    """His re-offer (c-651, `keel/shipreoffer.py`), answered on this look: its ask
    cleared, once the items it put in the batch are written, with a note saying what.
    `no_base` is `shipreoffer.fill`'s why a wanted rebase was not written; `busy`, the
    sentence for items left out because the house is still on them (`offerable`)."""
    board.set_fields(card["id"], {"options": {REOFFER_OPTION: None}}, "drain")
    change = terms.of_board(board, card["space"])["change"]
    if no_base == shipreoffer.REBASE_REFUSED:
        board.note(card["id"], shipreoffer.NO_BASE_NOTE.format(change=change), "drain")
    if items:
        board.note(card["id"], shipreoffer.FILLED_NOTE.format(
            n=len(items), items="item" if len(items) == 1 else "items",
            handles=", ".join(item["handle"] for item in items)), "drain")
        return
    if no_base == shipreoffer.REBASE_REFUSED:
        return                    # the refusal said it; "up to date" would not be known
    if said:
        why = f"the {change} is {said}"
    elif busy:
        why = busy
    elif no_base == shipreoffer.BEHIND_UNKNOWN_BASE:
        why = shipreoffer.BEHIND_NO_BASE.format(change=change)
    else:
        why = "every comment and review was judged or posted, and the branch is up to date with its base"
    board.note(card["id"], shipreoffer.EMPTY_NOTE.format(why=why), "drain")


def turned(board, card: dict, before: dict, new: dict, events: list[str]) -> str | None:
    """Merged; declined (once, with a note, the card staying here); or open again."""
    if "merged" in events:
        return "merged"
    if "declined" in events:
        if before.get("state") != "declined":
            new["state"] = "declined"
            board.note(card["id"], terms.say(terms.of_board(board, card["space"]), DECLINED), "drain")
            return "declined"
        return None
    if before.get("state") == "declined":
        new.pop("state", None)
        board.note(card["id"], terms.say(terms.of_board(board, card["space"]), REOPENED), "drain")
    return None


def merged(cfg: Config, board, card: dict) -> str:
    """The card is done. Its house, once the harness lists it idle, is ended by the drain's
    next step in this same pass (`drain.idle_upkeep`, `keel/shipidle.py`, a-72); a working
    one is left until a later pass finds it idle."""
    t = terms.of(cfg, card["space"])
    # the move itself lifts an unjudged block, in its own write (`Board._clear_stale_block`)
    board.stage(card["id"], "done", "drain", note=terms.say(t, MERGED))
    reap(cfg, board, board.get(card["id"]))
    log(cfg, f"{card['id']}'s {t['change']} merged; the card is done")
    return "merged"


def reap(cfg: Config, board, card: dict) -> None:
    """The adapter's `ship <id> reap` for a DONE card, and one note saying what it did.
    Never for a card that is not done: the worktree of a shipping card is its house's."""
    if card.get("stage") != "done":
        return
    try:
        out = json.loads(adapters.run(cfg.spaces[card["space"]], SHIP_VERB, card["id"], "reap",
                                      timeout=SHIP_SECONDS) or "{}")
    except (adapters.AdapterError, ValueError) as error:
        board.note(card["id"], f"the worktree was kept: the reap failed ({str(error).splitlines()[0]})", "drain")
        return
    removed, kept = out.get("removed") or [], out.get("kept") or []
    said = [f"worktree reaped: {', '.join(removed)}"] if removed else []
    said += [f"worktree kept, {k.get('why')}: {k.get('path')}" for k in kept]
    if said:
        board.note(card["id"], "; ".join(said), "drain")


# ----- the worktrees' own facts -----

def git(root: Path, *args: str) -> subprocess.CompletedProcess | None:
    try:
        return subprocess.run(["git", "-C", str(root), *args], capture_output=True, text=True,
                              timeout=GIT_SECONDS)
    except (OSError, subprocess.SubprocessError):
        return None


class Unread(Exception):
    """A git read did not run to an answer (a timeout, an OSError, a repository git cannot
    open): nothing is concluded, and never a zero to act on."""


def answered(done: subprocess.CompletedProcess | None, strict: bool, ok: tuple[int, ...] | None = (0, 1)) -> None:
    """`Unread` for a strict reader when a git call gave no answer; a reader that is not
    strict takes it as nothing known, as the drain's pass always has. `ok` None: any exit
    is an answer, and only a call that did not run (a timeout, an OSError) is unread."""
    if strict and (done is None or (ok is not None and done.returncode not in ok)):
        raise Unread("git did not answer" if done is None else (done.stderr or "").strip()[:200] or "git failed")


def tracked(root: Path, strict: bool = False, remote: str | None = None) -> str | None:
    """The ref HEAD's pull request branch was last fetched at, `<remote>/<the branch HEAD is
    on>` (what his Ship pushes to; `remote` is the space's, `config.remote_of`), or None
    when the remote holds no such branch. NEVER the
    branch's upstream (c-653 review): a worktree cut from its base and not pushed has its
    base as upstream, and "behind" would then mean behind the base, which is no reason to
    refuse a Ship and nothing to bring a branch onto."""
    named = git(root, "symbolic-ref", "--quiet", "--short", "HEAD")
    answered(named, strict)
    branch = named.stdout.strip() if named is not None and named.returncode == 0 else ""
    ref = f"{remote or DEFAULT_REMOTE}/{branch}"
    found = git(root, "rev-parse", "--verify", "--quiet", f"refs/remotes/{ref}") if branch else None
    if branch:
        answered(found, strict)
    return ref if found is not None and found.returncode == 0 else None


def sides(root: Path, strict: bool = False, remote: str | None = None) -> tuple[int, int]:
    """`(ahead, behind)`: commits on HEAD its pull request's branch lacks, and commits that
    branch has that HEAD lacks (c-653), as last fetched; `(0, 0)` when nothing is known.
    `strict` (c-660): a git call that gave no answer is `Unread`, never that zero."""
    ref = tracked(root, strict, remote)
    done = git(root, "rev-list", "--left-right", "--count", f"{ref}...HEAD") if ref else None
    if ref:
        answered(done, strict, ok=(0,))
    found = done.stdout.split() if done is not None and done.returncode == 0 else []
    if len(found) != 2 or not all(part.isdigit() for part in found):
        return 0, 0
    return int(found[1]), int(found[0])


def ship_trees(card: dict) -> list[tuple[str, Path]]:
    """`(repo, worktree)` for each worktree on this machine that a pull request of the card
    is on (c-653 review): the primary repo's `options.worktree`, each `options.worktrees`
    entry, and the `<id>-<repo>` sibling of an `<id>` worktree, every one keyed by its OWN
    repo. When the card records its pull requests (`options.pr`, `options.prs`), a worktree
    of a repo with none is left out: nothing is pushed from it, so it is never "behind"."""
    from keel import adapters      # noqa: PLC0415 - adapters reaches this module through shipcheck
    options = card.get("options") or {}
    repos = adapters.repos_of(card)
    found = [(repos[0], Path(str(options["worktree"])))] if repos and options.get("worktree") else []
    recorded = options.get("worktrees") or {}
    found += [(str(repo), Path(str(path))) for repo, path in (recorded.items() if isinstance(recorded, dict) else ())]
    found += [(key, root.parent / f"{card['id']}-{key}") for _, root in list(found)
              if root.name == card.get("id") for key in repos[1:]]
    prs = options.get("prs") if isinstance(options.get("prs"), dict) else {}
    with_pr = set(prs) | ({repos[0]} if repos and options.get("pr") else set())
    out, seen = [], set()
    for repo, root in found:
        key = str(root.expanduser().resolve())
        if key not in seen and root.is_dir() and (not with_pr or repo in with_pr):
            seen.add(key)
            out.append((repo, root))
    return out


def step_facts(roots: list[Path], strict: bool = False, remote: str | None = None) -> dict:
    """`{ahead, behind}` over the worktrees, and `diverged` (`{ahead, behind}`, git's own
    counts) when one is both ahead of and behind its pull request's branch (c-653): that
    branch was rewritten outside Keel, and what is ahead there is the old history, not work
    to ship. `ahead` counts only what a fast-forward push would send."""
    each = [sides(root, strict, remote) for root in roots]
    facts = {"ahead": sum(ahead for ahead, behind in each if not behind),
             "behind": sum(behind for _, behind in each)}
    astray = [(ahead, behind) for ahead, behind in each if ahead and behind]
    if astray:
        facts["diverged"] = {"ahead": sum(a for a, _ in astray), "behind": sum(b for _, b in astray)}
    return facts


def conflicts(root: Path, base: str | None, strict: bool = False, remote: str | None = None) -> bool:
    """Does HEAD conflict with `<remote>/<base>` (as last fetched)? `git merge-tree
    --write-tree` exits 1 on a conflict and touches nothing. A base this clone never
    fetched is NO CONFLICT KNOWN, asked first (`rev-parse --verify`) and never read off
    merge-tree's exit: git exits 1 or 128 on the unknown ref by its version, and a card with
    an unfetched base read as conflicting (c-660 review). That is an answer for the strict
    reader too: only a call that did not run is `Unread`."""
    if not base:
        return False
    ref = f"{remote or DEFAULT_REMOTE}/{base}"
    held = git(root, "rev-parse", "--verify", "--quiet", f"refs/remotes/{ref}")
    answered(held, strict, ok=None)
    if held is None or held.returncode != 0:
        return False
    done = git(root, "merge-tree", "--write-tree", "--no-messages", ref, "HEAD")
    answered(done, strict, ok=None)
    return done is not None and done.returncode == 1


def local_facts(cfg: Config, card: dict, base: str | None = None, strict: bool = False) -> dict:
    """`{ahead, behind, unchecked, conflicts}` over the card's worktrees on this machine
    (and `diverged`, `step_facts`): commits a push would send, commits its pull request's
    branch has that the worktree lacks (both over the worktrees a pull request is on,
    `ship_trees`), whether the review stamp covers every worktree's
    HEAD (the receipt `keel check` leads to), and a conflict with the base (`base_of`: never
    a guess; each worktree against its own repo's, `tree_base`). While a worktree is behind,
    `said` is THE sentence for it (`shipstep.said`): the
    card's note, the Ship refusal and the deck's line are all this one string; and `by_hand`
    is what he types to bring each such worktree in line, or why Keel cannot say
    (`keel/shipstep.py`, read-only). `strict` (c-660, his Ship's read): `Unread` when git
    did not answer for a count or the conflict, where the drain's pass reads nothing known."""
    from keel.planlint import card_roots          # noqa: PLC0415 - heavier than a pass needs up front
    from keel.review import gate as review_gate    # noqa: PLC0415
    from keel.review import stamp as review_stamp  # noqa: PLC0415
    roots = card_roots(card, None)
    if not roots:
        return {}
    base = base or base_of(card)
    remote = remote_of(cfg, card.get("space"))
    facts = step_facts([root for _, root in ship_trees(card)], strict, remote)
    stamped = review_stamp.read_stamp(cfg, card["id"])
    checked = bool(stamped) and review_gate.covers(stamped, review_gate.card_heads(card, roots[0]), remote)
    facts = dict(facts, unchecked=bool(facts["ahead"]) and not checked,
                 conflicts=any(conflicts(root, tree_base(cfg, card, root, base), strict, remote) for root in roots))
    from keel import shipstep     # noqa: PLC0415 - shipstep builds on this module
    if not facts["behind"]:
        # c-718: a stacked card whose parent was squash-merged is out of step with its base
        hand = shipstep.restack(card, remote, cfg)
        if not hand:
            return facts
        said = shipstep.restack_said(hand, repo_base(cfg, card, hand[0].get("repo"), base),
                                     terms.of(cfg, card.get("space")))
        return dict(facts, restack=True, said=said, by_hand=hand)
    hand = shipstep.by_hand(card, remote)
    return dict(facts, said=shipstep.said(facts, hand, terms.of(cfg, card.get("space"))), by_hand=hand)


def kind_of(facts: dict) -> str | None:
    """`diverged`, `behind`, `restack` (c-718), or None: which sentence a worktree's facts call for."""
    if facts.get("diverged"):
        return "diverged"
    return "behind" if facts.get("behind") else "restack" if facts.get("restack") else None


def local_note(facts: dict, before: dict) -> str | None:
    """The sentence said on the card each time the worktrees' facts change kind (c-653
    review): a branch that was behind and then diverges must not leave "replies can still be
    sent" as its last word. None while the kind stands, and when no worktree is behind."""
    return facts["said"] if kind_of(facts) and kind_of(facts) != kind_of(before) else None


def say_local(board, card_id: str, facts: dict, before: dict, actor: str) -> None:
    """Say the out-of-step sentence on the card, ONCE per change of kind whoever finds it
    (c-660 review): his Ship's read and a drain pass that read the record between the
    Ship's two writes both see the one change, seconds apart. So the note is skipped only
    when the card's newest out-of-step note (a note carrying `local`, the kind) says this
    same sentence AND was written within `SAID_LATELY_SECONDS`. The same sentence later is
    a second change of kind (behind, brought in line, behind again), and is said."""
    said = local_note(facts, before)
    if not said:
        return
    last = next((event for event in reversed(board.events(card_id))
                 if event["kind"] == "note" and (event.get("data") or {}).get("local")), None)
    if last is None or not oldwords.same(last.get("text"), said) or not lately(last.get("at"), board.now()):
        board.note(card_id, said, actor, data={"local": kind_of(facts)})


def lately(stamp: str | None, at: str) -> bool:
    """Was `stamp` within `SAID_LATELY_SECONDS` before `at` (the board's clock, both)."""
    try:
        return (datetime.fromisoformat(at) - datetime.fromisoformat(stamp or "")).total_seconds() <= SAID_LATELY_SECONDS
    except (TypeError, ValueError):
        return False


def read_within(cfg: Config, card: dict, seconds: float) -> dict | None:
    """The worktrees' facts, read strictly and within ONE deadline over the whole read, or
    None: unread (git did not answer, the read failed, or it ran past the deadline). The
    read runs on a thread of its own that nothing waits for past the deadline."""
    found: list[dict] = []

    def read() -> None:
        try:
            found.append(local_facts(cfg, card, base_of(card), strict=True))
        except Exception as error:  # noqa: BLE001 - unread, whatever stopped it
            log(cfg, f"{card['id']}'s worktrees unread after its Ship: {error}")
    thread = threading.Thread(target=read, daemon=True, name=f"after-ship-{card['id']}")
    thread.start()
    thread.join(seconds)
    return found[0] if found else None


def after_ship(cfg: Config, board, card_id: str) -> dict:
    """What `kb ship` does once `Board.ship` has RECORDED the Ship (c-660): read the
    worktrees again and lay their facts over the record as `local`, in a second short write
    (`Board.keep_shipping`), so the deck says what waits now and never offers a send that was
    just made. A read, never a sum worked out from the adapter's answer: `ahead` is one
    count over every worktree, and a commit the house made while the push ran still waits.

    It can never fail, delay past `AFTER_SHIP_SECONDS` or repeat the Ship, which is already
    on the record. UNREAD (`read_within`) writes nothing: the record keeps what `Board.ship`
    left, no send offered and whatever was known of a branch behind, and the drain's next
    pass reads the rest without saying its sentence again. A worktree this read finds newly
    behind or diverged is said on the card as his Ship's own finding (a note of his, in the
    one sentence, `say_local`), which that pass does not repeat either. The card."""
    try:
        facts = read_within(cfg, board.get(card_id), AFTER_SHIP_SECONDS)
        held = dict((board.get(card_id).get("options") or {}).get(SHIPPING_OPTION) or {})
        if facts is not None and held:
            board.keep_shipping(card_id, held, dict(held, local=facts), actor="human")
            say_local(board, card_id, facts, held.get("local") or {}, "human")
    except Exception as error:  # noqa: BLE001 - the Ship went and is recorded; this is its afterword
        log(cfg, f"{card_id}'s worktrees not kept after its Ship: {error}")
    return board.get(card_id)


def keep_local(cfg: Config, board, card: dict, shipped: dict) -> dict:
    try:
        facts = local_facts(cfg, card, base_of(card, shipped))
    except Exception as error:  # noqa: BLE001 - a read of git is a convenience, never the pass
        log(cfg, f"could not read {card['id']}'s worktrees: {error}")
        return shipped
    before = shipped.get("local") or {}
    if facts == before:
        return shipped
    # not when his Ship landed since this pass read the record (c-660): this read of git may
    # be from before its push. The write's own transaction decides, and the pass goes on from
    # the board's record; the next pass reads the worktrees again.
    new = board.keep_shipping(card["id"], shipped, dict(shipped, local=facts), unless_moved=("shipped_at",))
    if new.get("shipped_at") != shipped.get("shipped_at"):
        return new
    say_local(board, card["id"], facts, before, "drain")
    return new


# ----- the batch -----

def put_back(card_id: str, before: dict, taken: dict | None = None):
    """What a batch that could not reach its house does, in line or on the tell's thread: the
    record as it was before the batch was taken (so the items wait again), and the card
    blocked for him with the reason, marked as Keel's mechanics. `taken` is the record as
    the take made it (never the record as written, which holds other writers' keys too): only
    what taking the batch changed goes back (`Board.keep_shipping`)."""
    def undo(board, error: BaseException) -> None:
        board.keep_shipping(card_id, taken, before)
        if getattr(error, "said", False):
            return        # the card's block is this refusal already, under its own mark (`keel/afresh.py`)
        why = (str(error).splitlines() or [type(error).__name__])[0]
        board.block(card_id, f"the review batch could not reach the house: {why}", "drain",
                    mark="mechanics")
    return undo


# Said on the card once per Stop (c-605 review): the drain log alone left him no way to see it.
HELD_BATCH_NOTE = ("review items are waiting for this house, and you stopped it: they go to "
                   "it with your Resume")
# And once for a house open in his terminal, which nothing tells anything (c-666): until
# that house is next resumed or told.
IN_TERMINAL_NOTE = ("review items are waiting for this house, and it is open in your terminal: "
                    "they are told once you quit it there")


def note_held_batch(board, card_id: str, text: str = HELD_BATCH_NOTE) -> None:
    """The waiting batch, noted once: since his newest Stop, or until the house is next
    resumed or told (a `resume` on the card). The card may hold the note in the earlier
    release's words (`oldwords.same`, c-699 review F9)."""
    for event in reversed(board.events(card_id)):
        if event["kind"] == "note" and oldwords.same(event.get("text"), text):
            return
        if event["kind"] == "resume" or (event["kind"] == "note" and (event["data"] or {}).get("stop") == "human"):
            break
    board.note(card_id, text, "drain")


def still_unjudged(board, card: dict, shipped: dict) -> dict:
    """The record about to be told, without the re-offered items the house judged between
    the fill and now (`shipreoffer.drop_judged`, c-654 review), written and noted when any
    were dropped."""
    again = set((shipped.get(shipreoffer.RECORD_KEY) or {}).get("again") or [])
    if not again:
        return shipped
    left = shipreplies.unjudged(dict(card, options={SHIPPING_OPTION: shipped}), board.events(card["id"]))
    new, gone = shipreoffer.drop_judged(shipped, again - set(left))
    if gone:
        new = board.keep_shipping(card["id"], shipped, new)
        board.note(card["id"], shipreoffer.JUDGED_NOTE.format(
            handles=", ".join(gone), them="it" if len(gone) == 1 else "them"), "drain")
    return new


def deliver(cfg: Config, board, card: dict, shipped: dict, reason: str, at: datetime,
            slots: int) -> str | None:
    """Tell the house the waiting items (`keel/tellhouse.py`): its own session when it is
    listed, a resume when it exited and there is room, a fresh house when it never had one
    or when the harness no longer holds its conversation (`keel/afresh.py`, c-654).
    A working house waits (its Stop kicks this drain); one that cannot be reached puts the
    batch back and blocks the card with the reason, on the tell's own thread too.

    Every batch takes a house slot and the memory gate, a tell into a live idle house as much
    as a resume (c-600 review): each one starts a turn, and a burst across many shipping cards
    would otherwise run more houses than the pool allows. With no room the batch WAITS where it
    is (pending, its timers kept) for a later pass; it is never dropped."""
    space = cfg.spaces[card["space"]]
    row = harness.find(card.get("session_id") or "", harness.agents(space.config_dir))
    if housejobs.working(row):
        return None
    if row is None and card.get("session_id") and house.stopped_by_him(board, card["id"]):
        log(cfg, f"{card['id']}'s batch waits: the user stopped its house, so it waits for the user's Resume")
        note_held_batch(board, card["id"])
        return None
    if slots <= 0:
        log(cfg, f"{card['id']}'s batch waits: the house pool is full or the memory gate shut")
        return None
    kept = still_unjudged(board, card, shipped)
    if kept is not shipped:
        shipped, reason = kept, shipwatch.due(kept, at)
        if reason is None:
            return None               # the house judged every item meanwhile: nothing to tell
    items, taken = shipwatch.take_batch(shipped, at)
    newest = board.events(card["id"], last=1)
    taken = shipreoffer.on_batch(taken, at, after=newest[-1]["id"] if newest else 0)
    # `taken` is the record as the take made it, `told` the record as written: the undo of a
    # batch that cannot reach its house goes back from `taken` to `shipped`, so only the keys
    # the take changed are put back and nothing another writer wrote meanwhile (c-653 review)
    told = board.keep_shipping(card["id"], shipped, taken)
    prompt = shipround.batch_prompt(cfg, card, items, reason, told["round"],
                                    reoffer=shipreoffer.is_reoffer(told), astray=told.get("local"))
    try:
        if card.get("session_id"):
            # on a thread of its own (c-598): the relay's 7 to 17 s never hold up the pass's
            # other cards; `upkeep` joins them before it returns
            result = house.resume(cfg, board, card["id"], prompt=prompt, tell=True, background=True,
                                  on_error=put_back(card["id"], shipped, taken))
        else:
            result = house.launch(cfg, board, card["id"], extra=prompt, expect="shipping")
    except tellhouse.Twinned as twins:
        # two live sessions carry the card's name: said on the card, and held for him
        board.keep_shipping(card["id"], taken, shipped)
        board.block(card["id"], f"the review batch waits: {twins}", "drain", mark="mechanics")
        return None
    except house.Busy as busy:
        board.keep_shipping(card["id"], taken, shipped)
        log(cfg, f"{card['id']}'s batch waits: {busy}")
        if (row or {}).get("kind") == dropin.INTERACTIVE:
            note_held_batch(board, card["id"], IN_TERMINAL_NOTE)
        return None
    except (Refused, harness.HarnessError, adapters.AdapterError, OSError) as error:
        put_back(card["id"], shipped, taken)(board, error)
        return None
    how = ("told in its session" if result.get("told") else "started afresh" if result.get("afresh")
           else "resumed" if card.get("session_id") else "started")
    board.note(card["id"], f"batch {told['round']} ({len(items)} "
                           f"{'item' if len(items) == 1 else 'items'}: {reason}) {how}", "drain")
    log(cfg, f"{card['id']} batch {told['round']} {how} ({len(items)} items: {reason})")
    return "told" if result.get("told") else "resumed"
