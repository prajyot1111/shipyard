"""A done review card's worktree taken away (c-734, point 11; docs/atlas/30-drain.md, "Merged").

The box test's review card kept its detached worktree for good: only a merge reaped
(`shipping.reap`), and a review card reaches done without one (its review posted, or closed).
The review fetcher's pass now reaps it, by Keel's own hand and git's own refusal:

- **Only the path the pack recorded when it cut the tree**: `options.worktree`, and the
  per-repo `options.worktrees` and per-member `options.review_worktrees` maps, which every
  pack's review cut writes. Never a path Keel guesses, never a tree found by a branch name
  (a review card's branch is the colleague's, and a worktree of the user's may have it out),
  and a pack's generic `ship <id> reap` is never called for a review card (r1.F3): only one
  that declares review-aware reaping, below.
- **Keel's own layout only**: a recorded tree inside `<install>/spaces/<space>/<key>/trees/`
  (what the GitHub pack and a stranger's install cut) is removed by Keel. One anywhere else
  is a pack's own (the owner's work pack keeps review trees in its tree home): it is reaped
  only through a pack that declares `review_reap` under `[capabilities]`, by its `ship <id>
  reap`, and otherwise left alone, its card said once for its round to be not Keel's to reap
  (`NOT_OURS`), so it is not read again (`plan`, `pack_reaps`). A card none of whose recorded
  trees is left on disk is said so once too (`NO_TREE`); a pack whose `pack.toml` cannot be
  read is asked again on the next pass, and nothing is written.
- **A tree git lists as a linked worktree of its repo**, removed with `git worktree remove`,
  never forced, so one with changes is kept and said.
- **Never under a live session** (r1.F1): a card whose session the harness still lists, idle
  or working, is left; so is a tree any listed session runs in, in any space's config dir
  (r2.F3). A listing that fails reaps nothing. A card under a voice hold or a drop-in hold
  is left too, until the hold is gone (r2.F3).
- **Once a round** (r1.F2): the note it leaves carries `reaped: <round>`, and a Re-review's new
  round (`options.review_round`) is reaped again once it is done.
- **One query a pass** (r1.F9): the candidates are done review cards of the space, updated in
  the last `RECENT_DAYS`, with no reap note for their round, at most `REAPS_MAX` a pass.
- **"Ask me again later"** (c-743): a pack keeping a tree for a passing reason (a session live
  in it, sessions it cannot list, another card still using it) answers `later: true`, and a
  reap command that fails or times out is read the same way. The round gets no `reaped` mark,
  so the card is a candidate again; why it waits is said once, in a note carrying
  `reap_later: <round>`. A pass runs at most `REAPS_MAX` pack commands, whatever each answers
  (r1.F3). A waiting card is asked after the ones not asked yet, and the waiting ones take
  turns, least recently asked first (r1.F1, `ASKED`: this process's memory, no board write).
  A waiting round is exempt from the `RECENT_DAYS` cut (r1.F2): it is asked until it is reaped,
  and the waiting rounds are read by a query of their own (`WAITING`, r2.F2, r2.F3).
"""

from __future__ import annotations

import json
import subprocess
from datetime import datetime, timedelta
from pathlib import Path

from keel import adapters, harness, packs, repolayout, views

KEY_OPTION = "review_key"
ROUND_OPTION = "review_round"
REAPED = "reaped"
LATER = "reap_later"            # the note that says once why a round's tree waits (c-743)
REAPS_MAX = 3
RECENT_DAYS = 14
GIT_SECONDS = 60
NOTED = ("EXISTS (SELECT 1 FROM events AS e WHERE e.card = cards.id AND e.kind = 'note' "
         "AND json_extract(e.data, '$.{}') = COALESCE(json_extract(cards.options, '$.review_round'), 1))")
WAITING_MAX = 200       # waiting rounds read a pass; a pass asks at most REAPS_MAX of them
ROUND = "COALESCE(json_extract(cards.options, '$.review_round'), 1)"
REVIEWED = "cards.space = ? AND cards.stage = 'done' AND json_extract(cards.options, '$.review_key') IS NOT NULL"
# the cards not asked yet in their round: the recent ones, so an old card costs no subquery
CANDIDATES = (
    f"SELECT id FROM cards WHERE {REVIEWED} AND updated_at >= ? AND NOT {NOTED.format(REAPED)} "
    f"AND NOT {NOTED.format(LATER)} ORDER BY updated_at DESC LIMIT ?")
# the waiting rounds, whatever their age (r1.F2), read from their notes through the
# `events_reap_later` index (`keel/board.py`), oldest note first, with a limit of their own
# so the recent cards never hide one (r2.F2, r2.F3)
WAITING = (
    "SELECT cards.id FROM events AS w INDEXED BY events_reap_later JOIN cards ON cards.id = w.card "
    f"WHERE w.kind = 'note' AND json_extract(w.data, '$.{LATER}') > 0 "
    f"AND json_extract(w.data, '$.{LATER}') = {ROUND} AND {REVIEWED} AND NOT {NOTED.format(REAPED)} "
    "ORDER BY w.id LIMIT ?")


def round_of(card: dict) -> int:
    try:
        return int((card.get("options") or {}).get(ROUND_OPTION) or 1)
    except (TypeError, ValueError):
        return 1


def recorded(card: dict) -> list[Path]:
    """The trees the pack recorded for this card, in order, each once."""
    options = card.get("options") or {}
    found = [options.get("worktree")]
    for name in ("worktrees", "review_worktrees"):
        if isinstance(options.get(name), dict):
            found += list(options[name].values())
    out = []
    for value in found:
        if isinstance(value, str) and value and Path(value) not in out:
            out.append(Path(value))
    return out


def git(where: Path, *args: str) -> subprocess.CompletedProcess | None:
    try:
        return subprocess.run(["git", "-C", str(where), *args], capture_output=True, text=True,
                              timeout=GIT_SECONDS)
    except (OSError, subprocess.SubprocessError):
        return None


def owner_of(tree: Path) -> Path | None:
    """The repo whose linked worktree `tree` is (its main working tree), or None when git does
    not list `tree` as a linked worktree of it (the main checkout itself included)."""
    common = git(tree, "rev-parse", "--path-format=absolute", "--git-common-dir")
    if common is None or common.returncode != 0 or not common.stdout.strip():
        return None
    repo = Path(common.stdout.strip()).parent
    listed = git(repo, "worktree", "list", "--porcelain")
    if listed is None or listed.returncode != 0:
        return None
    paths = [line[len("worktree "):] for line in listed.stdout.splitlines() if line.startswith("worktree ")]
    return repo if str(tree.resolve()) in [str(Path(p).resolve()) for p in paths[1:]] else None


def under(cwd: str | None, tree: Path) -> bool:
    if not cwd:
        return False
    try:
        return Path(cwd).resolve().is_relative_to(tree.resolve())
    except OSError:
        return False


def held(card: dict) -> bool:
    """A card under a live voice hold or any drop-in hold, which the drain leaves alone too."""
    options = card.get("options")
    return bool(views.voice_hold(options) or views.dropin_hold(options))


def remove(tree: Path) -> str | None:
    """`git worktree remove`, never forced: None when it went, else why it was kept."""
    repo = owner_of(tree)
    if repo is None:
        return "git does not list it as a linked worktree"
    gone = git(repo, "worktree", "remove", str(tree))
    if gone is None:
        return "git did not answer"
    if gone.returncode != 0:
        said = (gone.stderr or gone.stdout).strip().splitlines()
        return said[-1] if said else "git worktree remove failed"
    return None


def candidates(board, space: str, now: datetime) -> list[tuple[dict, bool]]:
    """`(card, waiting)`: waiting when its round already carries the "asked again later" note."""
    since = (now - timedelta(days=RECENT_DAYS)).isoformat(timespec="seconds")
    fresh = board.conn.execute(CANDIDATES, (space, since, CANDIDATES_MAX)).fetchall()
    waiting = dict.fromkeys(row["id"] for row in board.conn.execute(WAITING, (space, WAITING_MAX)))
    return [(board.get(row["id"]), False) for row in fresh] + [(board.get(each), True) for each in waiting]


CANDIDATES_MAX = 50     # read a pass; at most REAPS_MAX of them are reaped
CAPABILITY = "review_reap"      # `[capabilities] review_reap = true` in a pack's pack.toml
NOT_OURS = ("worktree not reaped by Keel: none of its recorded trees is one Keel's layout cut, "
            "and the pack does not reap review trees")
NO_TREE = "no worktree left to reap"
ASKED_AGAIN = "not cleaned up yet, asked again on a later pass"
ASKED: dict[str, datetime] = {}     # card id: the board clock when its pack was last asked (r1.F1)


def in_layout(cfg, space: str, tree: Path) -> bool:
    """A tree Keel's own layout cut: `<install>/spaces/<space>/<key>/trees/<card>`."""
    spaces = repolayout.spaces_of(cfg)
    if spaces is None:
        return False
    try:
        parts = Path(tree).resolve().relative_to((spaces / space).resolve()).parts
    except (OSError, ValueError):
        return False
    return len(parts) >= 3 and parts[1] == repolayout.TREES


def pack_reaps(cfg, space: str) -> bool | None:
    """Whether the space's pack declares review-aware reaping: its `ship <id> reap` for a
    review card removes only that card's recorded paths, with its own teardown. None when its
    `pack.toml` cannot be read: unknown, so the card is asked again on a later pass."""
    try:
        pack = packs.at(cfg.spaces[space].adapter_dir)
    except packs.PackError:
        return None
    return pack is not None and CAPABILITY in pack.capabilities


def plan(cfg, space: str, card: dict) -> tuple[list[Path], bool | None] | str:
    """`(Keel's trees, the pack's)`: the recorded trees still on disk that Keel's layout cut,
    which Keel removes with git, and whether any other is the pack's to reap (only under
    `review_reap`; without it a tree outside the layout is left alone, r2: the owner's work
    pack keeps its review trees in a tree home of its own; None when the pack cannot be
    read). The note to leave instead when there is nothing to reap: `NO_TREE` when no
    recorded tree is on disk, `NOT_OURS` when the ones there are not Keel's or the pack's."""
    trees = [tree for tree in recorded(card) if tree.exists()]
    if not trees:
        return NO_TREE
    own = [tree for tree in trees if in_layout(cfg, space, tree)]
    pack = len(own) < len(trees) and pack_reaps(cfg, space)
    return NOT_OURS if not own and pack is False else (own, pack)


def answered(text: str) -> tuple[list[str], bool]:
    """A pack's reap answer as said lines, and its `later`. ValueError for one that is not
    `{"removed": [<path>], "kept": [{"path", "why"}]}` (r1.F5): no JSON, no object, a
    `removed` that is not a list of strings, a `kept` entry that is not an object."""
    out = json.loads(text or "{}")
    if not isinstance(out, dict):
        raise ValueError("its answer is not an object")
    removed, kept = out.get("removed") or [], out.get("kept") or []
    if not isinstance(removed, list) or not all(isinstance(path, str) for path in removed):
        raise ValueError("its answer's removed is not a list of paths")
    if not isinstance(kept, list) or not all(isinstance(each, dict) for each in kept):
        raise ValueError("its answer's kept is not a list of objects")
    return ([f"worktree reaped: {path}" for path in removed]
            + [f"worktree kept, {each.get('why')}: {each.get('path')}" for each in kept],
            out.get("later") is True)


def by_pack(cfg, space: str, card: dict) -> tuple[list[str], bool | None]:
    """The pack's `ship <id> reap` for a review card: its answer as said lines, and whether to
    ask again on a later pass (c-743): True when it answered `later: true`, None when the
    command failed, timed out or answered something malformed, which waits the same way."""
    try:
        return answered(adapters.run(cfg.spaces[space], "ship", card["id"], "reap", timeout=GIT_SECONDS * 5))
    except (adapters.AdapterError, ValueError) as error:
        return [f"the pack's reap failed ({str(error).splitlines()[0]})"], None


def live(card: dict, rows: list) -> bool:
    """Left for a later pass: the user is on it (a voice or drop-in hold), its house is still
    listed, or a listed session runs in one of its trees."""
    if held(card):
        return True
    if card.get("session_id") and harness.find(card["session_id"], rows) is not None:
        return True
    return any(under(row.get("cwd"), tree) for row in rows for tree in recorded(card))


def turn(card: dict, waiting: bool, at: datetime) -> tuple:
    """A card's place in a pass (r1.F1): the ones not asked yet in their round first, in the
    query's order; then the waiting ones, never asked by this process first, then least
    recently asked. `ASKED` is this process's memory, so the said-once rule holds with no
    write a pass, and a restarted drain simply starts the rotation again."""
    if not waiting:
        return (0, at)
    return (1 + (card["id"] in ASKED), ASKED.get(card["id"], at))


def reap_one(cfg, board, space: str, card: dict, own: list[Path], pack: bool, waiting: bool) -> bool:
    """One card's trees: True when its round is marked reaped, False when its pack said later
    or its command failed. Why a round waits is said once (`waiting`: it was)."""
    said = []
    for tree in own:
        why = remove(tree)
        said.append(f"worktree reaped: {tree}" if why is None else f"worktree kept, {why}: {tree}")
    lines, later = by_pack(cfg, space, card) if pack else ([], False)
    if later is False:
        board.note(card["id"], "; ".join(said + lines) or "no recorded worktree is left to reap", "drain",
                   data={REAPED: round_of(card)})
        return True
    if not waiting:
        board.note(card["id"], "; ".join(said + lines + [ASKED_AGAIN]), "drain", data={LATER: round_of(card)})
    return False


def reap(cfg, board, space: str, now: datetime | None = None) -> list[str]:
    """One pass for `space`: the cards whose recorded tree went or was said kept. A card with
    nothing to reap is said so once for its round, so it is not a candidate again: `NO_TREE`
    when no recorded tree is left, `NOT_OURS` when its trees are outside the layout under a
    pack with no `review_reap`; nothing of its tree is touched. A card whose pack cannot be
    read is left, with nothing written, for a later pass. So is one whose pack answers later
    or whose reap command fails (c-743). A pass runs at most `REAPS_MAX` pack commands,
    whatever each answers (r1.F3: each may run to its timeout), and marks at most `REAPS_MAX`
    cards, as before."""
    work, at = [], now or datetime.fromisoformat(board.now())
    for card, waiting in candidates(board, space, at):
        found = plan(cfg, space, card)
        if isinstance(found, str):
            board.note(card["id"], found, "drain", data={REAPED: round_of(card)})
        elif found[1] is not None:
            work.append((card, *found, waiting))
    if not work:
        return []
    try:
        # every config dir's sessions, as a pass reads them: one the user runs from another
        # space may sit in the tree (r2.F3)
        rows = harness.agents_across((each.config_dir for each in cfg.spaces.values()), strict=True)
    except harness.HarnessError:
        return []          # a listing that failed is never read as "no session is live"
    done, slots, asks = [], REAPS_MAX, REAPS_MAX
    for card, own, pack, waiting in sorted(work, key=lambda each: turn(each[0], each[3], at)):
        if slots == 0:
            break
        if live(card, rows) and waiting:
            ASKED[card["id"]] = at     # it runs nothing, so no slot, and it goes to the back (r2.F1)
            continue
        if live(card, rows):
            slots -= 1     # as before c-743: reaped once the hold is gone and no session is listed
            continue
        if pack and asks == 0:
            continue       # the pass's pack commands are spent: asked on a later pass (r1.F3)
        if pack:
            asks -= 1
            ASKED[card["id"]] = at
        if reap_one(cfg, board, space, card, own, pack, waiting):
            slots -= 1
            done.append(card["id"])
            ASKED.pop(card["id"], None)
    return done
