"""A batch's words (lane SHIP, c-600): what the card's own house is told when review activity
on its pull request comes back.

The card stays at `shipping` and its build house lives on: nothing is rotated, no fresh
session is started, and the card never goes back to building or review. The drain hands
each batch to that house as a message into its own session when it is idle, or as the
prompt of its resume when it exited (`keel/shipping.py`, `keel/tellhouse.py`). The words
are three parts: the batch, the METHOD (how to judge a review comment, the adapter's own
text from `ship <id> method`, or `METHOD` here for a space without one), and Keel's
protocol (one `kb verdict` per item, `keel check` after a commit, never push or post).
His Ship pushes the commits and posts the replies he keeps (`keel/shipreplies.py`).
"""

from __future__ import annotations

from keel import adapters, shipwatch, stacking, terms
from keel.config import DEFAULT_REMOTE, remote_of

SHIP_VERB = "ship"
METHOD_SECONDS = 30


# ----- the batch, as a house reads it -----

def item_line(item: dict, remote: str | None = None) -> str:
    handle, kind = item.get("handle"), item.get("kind")
    if kind == "comment":
        where = f" on `{item['path']}:{item['line']}`" if item.get("path") and item.get("line") else (
            f" on `{item['path']}`" if item.get("path") else "")
        reply = f", replying to comment {item['parent']}" if item.get("parent") else ""
        text = " ".join(str(item.get("text") or "").split())
        return f"- `{handle}`: {item.get('author')} commented{where}{reply} ({item.get('at')}): {text}"
    if kind == "review":
        return f"- `{handle}`: {item.get('author')} asked for changes ({item.get('at')})"
    if kind == "ci":
        name = item.get("name") or "a check"
        link = f" ({item['url']})" if item.get("url") else ""
        return f"- `{handle}`: {name} failed on the head commit{link}"
    if kind == shipwatch.HIS_KIND:
        return (f"- `{handle}`: THE USER'S OWN send-back ({item.get('at')}): the owner of this card asks you "
                f"in person; the words are under THE USER'S below")
    if kind == "rebase":
        state = "it conflicts with it" if item.get("conflicts") else (
            f"it is {item['behind']} commits behind" if item.get("behind") else "bring it up to date")
        return (f"- `{handle}`: bring your branch up to its base by merging {target_of(item, remote)} into it "
                f"({state}); see REBASE below")
    return f"- `{handle}`: {item}"


def target_of(item: dict, remote: str | None = None) -> str:
    """Where a rebase item brings the branch: its base as last fetched from the space's
    remote (`config.remote_of`), named when known."""
    return f"`{remote or DEFAULT_REMOTE}/{item['base']}`" if item.get("base") else "its base branch"


def merge_of(item: dict, remote: str | None = None) -> str:
    """The one command that brings it: a merge of the base into the branch, never a rebase."""
    return f"git merge {remote or DEFAULT_REMOTE}/{item.get('base') or '<its base branch>'}"


def batch_text(items: list[dict], remote: str | None = None) -> str:
    return "\n".join(item_line(item, remote) for item in items) or "- (nothing)"


# ----- the method -----

METHOD = """\
Judge every item before you touch code. For each: restate what the reviewer asks in one
line; decide Valid (a change improves correctness, maintainability, performance, readability
or consistency), Not valid (the code is right or intentional, or the change would regress
or over-engineer) or Valid but deferred; give the reasoning, checked against the code and
not the comment's framing. Change code ONLY for a valid item: say why it is needed and why
it does not regress, add or adjust a test when it carries logic, and run the tests it
reaches. Otherwise draft a reply: specific, courteous, acknowledging the point, saying why.
Many items, or one that needs checking across files: judge them with subagents in parallel;
they advise, you own the verdict. Report exactly what you ran; never claim a check you did
not run."""


def method_of(cfg, card: dict) -> str:
    """The adapter's method (`ship <id> method`), or Keel's for a space without one."""
    space = adapters.space_of(cfg, card)
    if space.adapter_dir is not None and adapters.has_verb(space, SHIP_VERB):
        try:
            said = adapters.run(space, SHIP_VERB, card["id"], "method", timeout=METHOD_SECONDS)
        except adapters.AdapterError:
            said = ""
        if said.strip():
            return said.strip()
    return METHOD


# ----- the prompt -----

BATCH = """\
## Review came back on your {change} (batch {round})

{reason}. You are this card's own house and it is at `shipping`: the user approved your outcome,
its {change} is ready, and you answer its reviewers here. Nothing leaves this machine
until the user's Ship, which pushes your commits and posts the replies they keep; you never push,
post, or run the adapter's `pr` or `publish` (they are refused at shipping).

### The batch

{batch}

A comment the batch shows cut ends with a marker naming its whole text under
`{card_dir}/comments/`; read it.

### The method

{method}

### Recording each item (Keel)

1. For a valid item that needs code: commit on your branch (end the message with the
   co-author line your harness uses), then `keel check {id}` and do what it says (a fix
   check or a full pass; the review stamp it leads to is the receipt the user's Ship reads).
   Change `{card_dir}/context.md` only when your change alters how the thing works (its
   behaviour, an interface, its risk). A rename, a test, a comment or a style fix is
   recorded in its verdict alone: the user's comments page shows every round's verdicts.
2. Write each reply's exact words to a file under `{card_dir}/replies/`.
3. Record ONE verdict per item, as soon as it is decided (the user sees each on the card at once):
   `kb verdict {id} <handle> --verdict valid|not-valid|deferred --summary "<what they ask>"
   --why "<your reasoning>" [--severity <their tag>] [--commit <sha>]... [--reply-file <file>]`
   A valid item gets a code change that names its commits (and may carry a short reply saying
   what changed); a not-valid or deferred item needs a reply. One you will not change here is
   deferred, never valid. A second verdict for a handle replaces the first.
   A fix that needs the user's yes before it lands (it rewrites commits already pushed, or
   it is otherwise the user's call): prepare it without moving your branch, then
   `kb verdict {id} <handle> --verdict prepared --why "<what you prepared, where, and the
   question>" [--commit <sha>]...`, with no reply. Name the branch and the commits you
   prepared; never quote a push command in --why, the guard refuses it at shipping.
   The card then waits on the user, who
   answers with a send-back told to you as your next item; then do what they said and
   record this item again.
4. End your turn. More review arrives as another batch in this session.
"""


REBASE = """
### REBASE (the `rebase` item: bring the branch up to its base by merging it in)

Bring your branch up to {target} by MERGING it in: `git fetch {remote}`, then `{merge}` on
your branch. Never `git rebase`, never amend or reset a commit already pushed, and never
`git push --force` (or `--force-with-lease`): you never push at all, and the user's Ship's push is a
plain fast-forward of the branch, which rewritten history would break. Resolve every
conflict by reading both sides (keep the base's change and yours; never drop either to make
the conflict go away), run the checks the change reaches, commit the merge, and
`keel check {id}` as for any fix. Nothing is posted for this item. Record it
`kb verdict {id} rebase --verdict valid --commit <the merge commit> --why "<what you brought
in and how each conflict was resolved>"`, with no reply; already up to date, the same with
your HEAD and a why that says so. One you cannot finish here (a conflict that needs the user's call)
is `--verdict deferred --why "<what stops it>"`, again with no reply.
"""

# His own send-back at shipping (c-663, `keel/shipsendback.py`): the rule once, then each
# item's words exactly as he wrote them (`his_text`, laid in after the template is filled, so
# a brace or a term in his words is never read as the template's).
HIS = """
### THE USER'S (the items that are the user's own send-back, not a reviewer's comment)

The user looked at this card at `shipping` and wrote these in person. This is the owner asking, not
a reviewer: do it, or say plainly why not. There is no reviewer to reply to and NOTHING about
these items is posted anywhere: the user reads your verdict and your answer on the card. Record
each `kb verdict {id} <handle> --verdict valid --commit <sha>... --why "<what you did>"` when
you did it (commit and `keel check {id}` as for any fix; the commits go out with the user's next
Ship), or `--verdict not-valid|deferred --why "<plainly why not>"`. `--reply-file` is
optional here: use it only for an answer to THE USER longer than the why.
"""
HIS_ITEM = "\n`{handle}`, the user's words exactly as written, between the two rules:\n\n-----\n{words}\n-----\n"

REOFFERED = """
This batch is a re-offer the owner asked for: when your turn on it ends, Keel stops this
session, since an idle house does not hold memory. The next batch resumes it, this conversation
kept; nothing you leave in your worktree is lost.
"""


ASTRAY = """
### Your branch is out of step with the {change}'s branch

The {change}'s branch was changed outside Keel ({how}), so your worktree does not show what
the {change} now holds. The user brings it in line by hand (the card shows the
commands). Until the card stops saying the branch is out of step: never rebase, reset, pull
or merge to fix it yourself (your fence refuses a rewrite, and merging the two histories in
doubles every commit); keep each commit small and to its item, since the user replays it; and say
in each verdict's why that the branch waits for the user.
"""

# r-55 (c-723): the branch was rebuilt in this worktree (with the user's yes) and the
# {change}'s branch still holds what was last pushed: only the user publishes it, by hand.
REBUILT = """
### Your branch was rebuilt here and is not published yet

Your worktree's branch was rebuilt here, and the {change}'s branch still holds the history
that was last pushed. The user publishes the rebuilt branch by hand (the card shows the
command, a push with a lease). Until the card stops saying so: never rebuild, rebase, reset,
pull or merge it again; keep each commit small and on top of the rebuilt branch; and say in
each verdict's why that the branch waits for the user.
"""

# In place of REBASE while the worktree is out of step with its own branch on the remote: the
# two instructions would contradict each other (merge the base in; never merge).
REBASE_HELD = """
### REBASE (the `rebase` item: not now)

Do NOT merge the base in while your branch is out of step with the {change}'s branch (below):
a merge on top of that history is one more thing to untangle. Record it
`kb verdict {id} rebase --verdict deferred --why "the branch is out of step with the
{change}'s branch; the user brings it in line first"`, with no reply.
"""


def astray_text(local: dict | None) -> str:
    """The paragraph for a worktree its pull request's branch has left behind (c-653,
    `shipping.step_facts`), or nothing."""
    local = local or {}
    if not local.get("behind"):
        return ""
    both = local.get("diverged") or {}
    hand = [one for one in local.get("by_hand") or [] if isinstance(one, dict)]
    if both and hand and all(one.get("rebuilt") for one in hand):
        return REBUILT
    how = (f"you are {both['ahead']} ahead of it and {both['behind']} behind: it was rewritten" if both
           else f"you are {local['behind']} behind it: someone else pushed to it")
    return ASTRAY.replace("{how}", how)


def batch_prompt(cfg, card: dict, items: list[dict], reason: str, number: int,
                 reoffer: bool = False, astray: dict | None = None) -> str:
    # The card's directory by its absolute path, never `$KEEL_CARD_DIR`: a batch is told to a
    # LIVE session, and a settings-file env rewrite does not reach a live session's shell
    # (probed 2026-09-30 on 2.1.285, c-604 review), so a house started before the variable
    # existed would find it empty.
    rebase = next((item for item in items if item.get("kind") == "rebase"), None)
    held = bool(rebase) and bool((astray or {}).get("behind"))
    remote = remote_of(cfg, card.get("space"))
    text = BATCH + (REBASE_HELD if held else
                    REBASE.format(target=target_of(rebase, remote), merge=merge_of(rebase, remote),
                                  remote=remote, id="{id}") if rebase else "")
    if rebase and not held and stacking.other_base(card):
        # c-772: the item names one base, the first repo's
        text += stacking.other_base(card) + " This item's base is the one named above.\n"
    his = [item for item in items if item.get("kind") == shipwatch.HIS_KIND]
    text += HIS + "{his}" if his else ""
    text += REOFFERED if reoffer else ""
    text += astray_text(astray)
    return terms.say(terms.of(cfg, card.get("space")), text).format(round=number, reason=reason[:1].upper() + reason[1:], id=card["id"],
                        batch=batch_text(items, remote), method=method_of(cfg, card),
                        card_dir=cfg.cards_dir / card["id"], his=his_text(his))


def his_text(items: list[dict]) -> str:
    """Each of his send-backs under its handle, his words exactly as he wrote them."""
    return "".join(HIS_ITEM.format(handle=item.get("handle"), words=str(item.get("text") or ""))
                   for item in items)
