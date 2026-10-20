"""A worktree its pull request's branch has left behind: what he does about it BY HAND
(c-653), worked out read-only.

Five cards hit it on 2026-10-05: the pull request's branch was force-pushed outside Keel
(its commits replayed onto another base) while the card's worktree kept the old history, and
a house then committed on top of it. His Ship pushes a fast-forward, so nothing leaves such
a worktree until it is on that branch again. Keel does NOT move a branch for him here: a
tool that rewrites a branch has its own card (c-659). What this module does is say exactly
what to type, and it only ever READS (`rev-parse`, `rev-list`, `reflog`, `merge-base`;
never a fetch, a ref, the index or the worktree).

For each worktree a pull request of the card is on (`shipping.ship_trees`) that is behind
`<remote>/<its branch>` as last fetched (`by_hand`; the remote is the space's,
`[spaces.<name>] remote`, `origin` by default), ONE command: a chain joined with `&&`,
so a paste stops at the first step that fails and nothing after it runs anywhere else
(`chain`). It starts `cd <the worktree>`, then a guard that HEAD is still the commit the
chain was worked out for (`test "$(git rev-parse HEAD)" = <sha>`: a block read before the
house's next commit does nothing at all), then the fetch of that one branch by its full
refspec (a clone with a narrowed refspec would otherwise replay onto a stale ref), then:

- **Only behind** (nothing of its own ahead): one fast-forward merge, which cannot lose a
  commit and refuses to overwrite an untracked file.
- **Diverged** (ahead and behind: that branch was rewritten): the house's OWN commits are
  those after the last position of this history the remote held (`old_head`: of the head
  Keel last recorded as pushed, `options.shipping.heads`, and the newest earlier position
  of the remote-tracking branch in its reflog that is an ancestor of HEAD, the nearer
  winning). When that is known and the range holds no merge: a backup branch of where it
  stands (named for that commit, so typing it again is harmless), and then the replay of
  exactly those commits (`git rebase --onto <remote>/<branch> <old head>`), or, with no
  commit of its own, the move of the branch by `git checkout -B`, which refuses to
  overwrite an untracked file.
- **Diverged, rebuilt HERE** (r-55, c-723: the remote is still at the head Keel last
  recorded as pushed, `published`, so nothing outside rewrote it and the worktree's branch
  is the history to publish): a backup branch of that head, then a push of HEAD leased on
  it exactly (`republish`), which git refuses if anyone pushed since.
- **When it is not known**, or the range holds a merge (c-651's rebase item has the house
  merge its base in, and a replay would flatten the merge and lose its resolution), or git
  could not be read (a count that could not be read is never taken for zero), there is no
  command: the sentence says why, and that it needs a hand.

`shipping.local_facts` keeps the answer on the card as `options.shipping.local.by_hand`
beside the one sentence (`local.said`), so the deck's line, the card's note and the
terminal's refusal all show the same words and the same command. Each entry carries what it
was worked out from (`at`: HEAD, the remote-tracking sha, the recorded head), and an entry
whose three are unchanged is kept as stored, not worked out again: this runs on every
drain pass for every such card. An entry worked out an older way (`v`, `WORKED_OUT`) is
worked out again once.
"""

from __future__ import annotations

import shlex
from pathlib import Path

from keel import shipping, terms

BACKUP = "keel/backup/{card}-{short}"
# How far back the remote-tracking branch's reflog is read for an earlier position: the
# newest that is an ancestor of HEAD is the one, and each entry costs a git call.
REFLOG_MOST = 50
UNKNOWN = ("Shipyard cannot tell which of its commits are this card's own (no head it recorded as "
           "pushed, and no recent earlier position of {ref}, is in this history)")
MERGE = ("its own commits include a merge ({n} after {old}), which a replay would flatten, "
         "losing the merge's resolution")
UNREAD = "git could not be read there"
# The way a by-hand entry is worked out (`one`): 2 since c-723 (a branch rebuilt here).
WORKED_OUT = 2


def out(root: Path, *args: str) -> str | None:
    """What a read-only git call printed, or None when it failed."""
    done = shipping.git(root, *args)
    return done.stdout.strip() if done is not None and done.returncode == 0 else None


def count(root: Path, *spec: str) -> int | None:
    """How many commits, or None when git could not say: never a zero to act on."""
    found = out(root, "rev-list", "--count", *spec)
    return int(found) if found is not None and found.isdigit() else None


Unread = shipping.Unread      # a git read that did not run to an answer: nothing is concluded


def asked(root: Path, *args: str):
    """A git call that ran, whatever it answered; `Unread` when it did not run."""
    done = shipping.git(root, *args)
    if done is None:
        raise Unread(args[0])
    return done


def held(root: Path, sha: str) -> bool:
    """Is this commit in HEAD's history. `Unread` when git could not be asked."""
    return asked(root, "merge-base", "--is-ancestor", sha, "HEAD").returncode == 0


def old_head(root: Path, ref: str, recorded: str | None) -> tuple[str | None, bool]:
    """`(sha, read)`: the last position of THIS history the remote held, or None. Of the
    recorded head and the newest of the remote-tracking branch's last `REFLOG_MOST` reflog
    positions that is an ancestor of HEAD (the walk stops there), the nearer to HEAD. `read`
    is False when ANY read here failed (the reflog, an ancestor check, a distance): then
    nothing is concluded, least of all that there is no earlier position, and the caller's
    entry says unread, which is never kept as stored and so is tried again on the next pass.
    Only a walk that ran and found none answers `(None, True)`."""
    try:
        found = []
        full = asked(root, "rev-parse", "--verify", "--quiet", f"{recorded}^{{commit}}") if recorded else None
        if full is not None and full.returncode == 0 and held(root, full.stdout.strip()):
            found.append(full.stdout.strip())
        log = asked(root, "reflog", "show", "-n", str(REFLOG_MOST), "--format=%H", ref)
        if log.returncode != 0:
            return None, False
        for sha in dict.fromkeys(log.stdout.split()):
            if held(root, sha):
                found.append(sha)
                break
    except Unread:
        return None, False
    far = {sha: count(root, f"{sha}..HEAD") for sha in dict.fromkeys(found)}
    if None in far.values():
        return None, False
    return (min(far, key=far.get) if far else None), True


def chain(root: Path, ref: str, head: str, *steps: str) -> str:
    """ONE command for a worktree: into it, HEAD still where this was worked out, the one
    branch fetched by its full refspec, then `steps`, each only when the one before it
    succeeded. `ref` is the remote-tracking branch, `<remote>/<branch>`. The path and the
    branch are quoted for the shell."""
    remote, branch = ref.split("/", 1)
    spec = shlex.quote(f"+refs/heads/{branch}:refs/remotes/{ref}")
    return " && ".join([f"cd {shlex.quote(str(root))}", f'test "$(git rev-parse HEAD)" = {head}',
                        f"git fetch {remote} {spec}", *steps])


def one(card: dict, repo: str, root: Path, stored: dict | None = None,
        remote: str | None = None) -> dict | None:
    """`{repo, root, at, command}` or `{repo, root, at, why}` for a worktree behind its pull
    request's branch; None for one in step, or with no such branch known. `stored`: the
    entry kept for this worktree, returned as it is when nothing it was worked out from
    (`at`) has changed."""
    ref = shipping.tracked(root, remote=remote)
    ahead, behind = shipping.sides(root, remote=remote)
    if not ref or not behind:
        return None
    branch, onto = ref.split("/", 1)[1], shlex.quote(ref)
    head = out(root, "rev-parse", "HEAD")
    recorded = (((card.get("options") or {}).get("shipping") or {}).get("heads") or {}).get(repo)
    # `v`: how it was worked out; an entry kept from an older way is worked out again once
    # (c-723 review r2.F7: one kept from before the rebuilt-here case gave the replay)
    found = {"repo": repo, "root": str(root), "at": [head, out(root, "rev-parse", ref), recorded],
             "v": WORKED_OUT}
    if (stored and all(found["at"][:2]) and stored.get("why") != UNREAD
            and all(stored.get(key) == found[key] for key in found)):
        return stored
    if not head:
        return dict(found, why=UNREAD)
    if not ahead:
        return dict(found, command=chain(root, ref, head, f"git merge --ff-only {onto}"))
    if published(root, recorded, found["at"][1]):
        # c-723 review r1.F7: what the paste replaces (published, not in HEAD), said before it
        replaced = out(root, "rev-list", found["at"][1], "^HEAD")
        if replaced is None:
            return dict(found, why=UNREAD)
        return dict(found, rebuilt=True, replaces=[sha[:10] for sha in replaced.split()],
                    command=republish(card, root, ref, head, found["at"][1]))
    old, read = old_head(root, ref, recorded)
    if not read:
        return dict(found, why=UNREAD)
    if old is None:
        return dict(found, why=UNKNOWN.format(ref=ref))
    merges, own = count(root, "--merges", f"{old}..HEAD"), count(root, f"{old}..HEAD")
    if merges is None or own is None:
        return dict(found, why=UNREAD)
    if merges:
        return dict(found, why=MERGE.format(n=merges, old=old[:10]))
    backup = f"git branch -f {shlex.quote(BACKUP.format(card=card['id'], short=head[:7]))} {head}"
    move = f"git rebase --onto {onto} {old}" if own else f"git checkout -B {shlex.quote(branch)} {onto}"
    return dict(found, own=own, command=chain(root, ref, head, backup, move))


def published(root: Path, recorded: str | None, there: str | None) -> bool:
    """Is the pull request's branch still exactly where Keel last pushed it (r-55, c-723)?
    Then nothing outside Keel rewrote it, and a worktree diverged from it was rebuilt HERE
    (c-240: the house replayed its commits onto a moved base, with the user's yes)."""
    if not recorded or not there:
        return False
    return out(root, "rev-parse", "--verify", "--quiet", f"{recorded}^{{commit}}") == there


def republish(card: dict, root: Path, ref: str, head: str, there: str) -> str:
    """The chain that publishes a branch rebuilt here: a backup branch of the head the
    remote holds (so the published commits are kept), then a push of HEAD leased on that
    exact head, which git refuses if anyone pushed since this was worked out."""
    remote, branch = ref.split("/", 1)
    backup = f"git branch -f {shlex.quote(BACKUP.format(card=card['id'], short=there[:7]))} {there}"
    push = (f"git push --force-with-lease={shlex.quote(f'refs/heads/{branch}:{there}')} {remote} "
            f"{shlex.quote(f'HEAD:refs/heads/{branch}')}")
    return chain(root, ref, head, backup, push)


def restack(card: dict, remote: str | None = None, cfg=None) -> list[dict]:
    """c-718: one entry per worktree of a STACKED card whose parent has merged into the base
    by a SQUASH, so the branch still carries the parent's old commits and its change would
    show them. Read-only like the rest: the fork point is where the worktree left the
    parent's branch (`merge-base HEAD <the parent's last pushed head>`), and the parent was
    squashed when that point is not in `<remote>/<base>` as last fetched. After a merge
    commit it is, and nothing is needed. A base the record still names as the parent's
    branch (the next look has not seen the aim moved yet) waits for that look. A repo the
    parent never named (c-772) has no entry: the card was cut from its own base there. Each
    repo is read against its own base (`shipping.repo_base`, with `cfg` the one rule's)."""
    from keel import stacking     # noqa: PLC0415 - stacking is the engine's, read only here
    found = stacking.of(card) or {}
    if found.get("choice") != stacking.STACKED or not found.get("landed"):
        return []
    whole = shipping.base_of(card)
    out = []
    for repo, root in shipping.ship_trees(card):
        head = (found.get("heads") or {}).get(repo) if stacking.stacked_in(card, repo) else None
        base = shipping.repo_base(cfg, card, repo, whole) if cfg is not None else whole
        if not base or base == found.get("branch"):
            continue
        entry = restack_one(card, repo, root, base, found, head, remote) if head else None
        if entry:
            out.append(entry)
    return out


SQUASHED = ("{parent}, which this card was stacked on, was squash-merged into {base}, so the branch "
            "still carries {parent}'s commits as they were and its {change} would show them. ")
RESTACK_BY_HAND = ("By hand, while its house is in no turn: the command below keeps a backup branch, "
                   "replays only this card's own commits onto {base}, and pushes the branch with a lease.")


def restack_one(card: dict, repo: str, root: Path, base: str, found: dict, parent_head: str,
                remote: str | None) -> dict | None:
    remote = remote or shipping.DEFAULT_REMOTE
    onto = f"{remote}/{base}"
    head = out(root, "rev-parse", "HEAD")
    if not head or out(root, "rev-parse", "--verify", "--quiet", f"refs/remotes/{onto}") is None:
        return None                # nothing known: no sentence on a guess
    if out(root, "rev-parse", "--verify", "--quiet", f"{parent_head}^{{commit}}") is None:
        # r2.F4: the parent's last head is not in this clone (its branch may be gone from the
        # remote). Read-only here, so no fetch: the sentence gives the one that brings it in.
        return {"repo": repo, "root": str(root), "restack": found.get("on"), "at": [head, None],
                "parent_unread": True, "why": PARENT_UNREAD.format(parent=found.get("on"), short=parent_head[:10],
                                            fetch=f"git -C {shlex.quote(str(root))} fetch {remote} {parent_head}")}
    fork = out(root, "merge-base", "HEAD", parent_head)
    if not fork:
        return None
    try:
        if asked(root, "merge-base", "--is-ancestor", fork, onto).returncode == 0:
            return None            # a merge commit, or moved already: the parent's commits are on the base
    except Unread:
        return None
    entry = {"repo": repo, "root": str(root), "restack": found.get("on"), "at": [head, fork]}
    merges, own = own_merges(root, fork, parent_head), count(root, f"{fork}..HEAD")
    if merges is None or own is None:
        return dict(entry, why=UNREAD)
    if merges:
        return dict(entry, why=MERGE.format(n=merges, old=fork[:10]))
    branch = out(root, "symbolic-ref", "--quiet", "--short", "HEAD")
    if not branch:
        return dict(entry, why=UNREAD)
    lease = out(root, "rev-parse", "--verify", "--quiet", f"refs/remotes/{remote}/{branch}") or ""
    backup = f"git branch -f {shlex.quote(BACKUP.format(card=card['id'], short=head[:7]))} {head}"
    move = f"git rebase --onto {shlex.quote(onto)} {fork}"
    push = (f"git push --force-with-lease={shlex.quote(f'refs/heads/{branch}:{lease}')} {remote} "
            f"{shlex.quote(f'HEAD:refs/heads/{branch}')}")
    return dict(entry, own=own, command=chain(root, onto, head, backup, move, push))


def own_merges(root: Path, fork: str, parent_head: str) -> int | None:
    """The merges in `fork..HEAD` that a replay would flatten, losing their resolution, or None
    when git could not say. A merge that only brought the parent's branch in (each parent but
    the first is in the parent's history: the house was told to merge it when it moved,
    r1.F6) is left out: the replay drops it and leaves out what it brought, which is exactly
    the parent's commits now squashed into the base."""
    listed = out(root, "rev-list", "--merges", "--parents", f"{fork}..HEAD")
    if listed is None:
        return None
    mine = 0
    try:
        for line in listed.splitlines():
            others = line.split()[2:]
            if not all(asked(root, "merge-base", "--is-ancestor", one, parent_head).returncode == 0
                       for one in others):
                mine += 1
    except Unread:
        return None
    return mine


MERGED_UNREAD = "{parent}, which this card was stacked on, merged into {base}. "
PARENT_UNREAD = ("{parent}'s last pushed head {short} is not in this clone, so Shipyard cannot tell "
                 "which commits are this card's own; bring it in with `{fetch}` (or fetch {parent}'s branch "
                 "while the remote still has it), and the next pass gives the command")


def restack_said(hand: list[dict], base: str, t=None) -> str:
    """The sentence for a stacked card whose parent was squashed (c-718): what is so, then the
    by-hand way, or why there is none."""
    parent = next((one.get("restack") for one in hand), "its parent")
    unread = next((one["why"] for one in hand if one.get("parent_unread")), None)
    if unread:      # r2.F4: squashed or not cannot be told yet, so it is not said
        return MERGED_UNREAD.format(parent=parent, base=base) + unread[:1].upper() + unread[1:] + "."
    lead = terms.say(t, SQUASHED).format(parent=parent, base=base)
    stuck = next((one["why"] for one in hand if not one.get("command")), None)
    if stuck:
        return lead + NEEDS_A_HAND.format(why=stuck[:1].upper() + stuck[1:])
    return lead + RESTACK_BY_HAND.format(base=base) + STALE


def by_hand(card: dict, remote: str | None = None) -> list[dict]:
    """One entry per worktree of the card that is behind its pull request's branch on
    `remote` (the space's, handed in by `shipping.local_facts`)."""
    local = ((card.get("options") or {}).get("shipping") or {}).get("local") or {}
    stored = {entry.get("repo"): entry for entry in local.get("by_hand") or [] if isinstance(entry, dict)}
    return [found for found in (one(card, repo, root, stored.get(repo), remote)
                                for repo, root in shipping.ship_trees(card)) if found]


# THE sentence for a worktree its pull request's branch has left behind (c-653), computed
# here once (`shipping.local_facts`) and kept as `options.shipping.local.said`: the card's
# note each time it changes kind, the Ship refusal (diverged), and the deck's line are this
# string, never a second wording. Keel moves no branch: the sentence ends with what he does
# by hand.
DIVERGED_NOTE = ("The branch has diverged from the {change}'s branch ({ahead} ahead, {behind} behind): "
                 "that branch was rewritten outside Shipyard, so nothing can be pushed until the worktree "
                 "is on it again. ")
# r-55 (c-723): diverged, with the remote still at the head Keel last pushed. Nothing was
# rewritten outside: the worktree's branch was rebuilt here, and replacing published commits
# is the user's call, so Ship's push (a fast-forward) does not send it.
REBUILT_NOTE = ("The branch was rebuilt here and has diverged from the {change}'s branch ({ahead} ahead, "
                "{behind} behind), which is still where Shipyard last pushed it. Ship only fast-forwards, "
                "and replacing published commits is your call. ")
# Behind only is not a refusal: nothing here needs a push, so kept replies and a draft still
# go (the adapter skips a push of a branch the remote already holds).
BEHIND_NOTE = ("The branch is {behind} behind the {change}'s branch (someone else pushed to it). "
               "Nothing here needs a push, so replies can still be sent. ")
BY_HAND = {"replay": "By hand, while its house is in no turn: the command below keeps a backup branch, "
                     "then replays this card's own commits onto it.",
           "move": "None of its commits are this card's own. By hand, while its house is in no turn: "
                   "the command below keeps a backup branch, then moves the branch onto it.",
           "up": "By hand, while its house is in no turn: the command below brings it up before the "
                 "house's next commit.",
           "publish": "By hand, while its house is in no turn: the command below keeps a backup branch "
                      "of the published head, then pushes the rebuilt branch with a lease, which git "
                      "refuses if anyone pushed to it since."}
# the chain's guard: a block read before the worktree's HEAD moved stops at once, silently
STALE = " If it does nothing, the worktree has moved since: the card has a newer one."
NEEDS_A_HAND = "{why}, so bringing it in line needs a hand: Shipyard gives no command for it."


def said(facts: dict, hand: list[dict], t=None) -> str | None:
    """The sentence for a worktree its pull request's branch has left behind, or None: what
    is so, then the by-hand way (`hand`, `shipstep.by_hand`), or why there is none."""
    if not facts.get("behind"):
        return None
    astray = facts.get("diverged") or {}
    here = bool(astray) and bool(hand) and all(one.get("rebuilt") for one in hand)
    lead = terms.say(t, REBUILT_NOTE if here else DIVERGED_NOTE if astray else BEHIND_NOTE).format(
        ahead=astray.get("ahead"), behind=astray.get("behind") or facts["behind"])
    stuck = next((one["why"] for one in hand if not one.get("command")), None)
    if stuck or not hand:
        why = stuck or "Shipyard could not read its worktree"
        return lead + NEEDS_A_HAND.format(why=why[:1].upper() + why[1:])
    how = ("up" if not astray else "publish" if here
           else "replay" if any(one.get("own") for one in hand) else "move")
    return lead + (replaced_line(hand) if here else "") + BY_HAND[how] + STALE


REPLACES_SHOWN = 8


def replaced_line(hand: list[dict]) -> str:
    """The published commits the paste of a rebuilt branch replaces (c-723 review r1.F7):
    how many, and each one's short sha, so they are seen before the push drops them."""
    shas = [sha for one in hand for sha in one.get("replaces") or []]
    if not shas:
        return ""
    named = ", ".join(sha[:7] for sha in shas[:REPLACES_SHOWN])
    more = f" and {len(shas) - REPLACES_SHOWN} more" if len(shas) > REPLACES_SHOWN else ""
    word = "commit" if len(shas) == 1 else "commits"
    return f"The push replaces {len(shas)} published {word} ({named}{more}), which the backup branch keeps. "


def commands_text(hand: list[dict]) -> str:
    """The commands as he pastes them: one line, one chain, per worktree."""
    return "\n".join(found["command"] for found in hand if found.get("command"))
