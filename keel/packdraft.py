"""Another provider: Bosun drafts a connection (c-678).

Where finished work goes offers a connection to the code host (a pack) or the merge on this
computer. For a host Keel ships no connection for, the draft choice files a card on which the
in-app builder drafts one, in the pattern of Import my Claude setup: a card on `packs`, at
assigned, whose brief is the whole of it. It is attended, so the user reads its plan before
anything is built, and nothing changes for the space until they turn the connection on.
Since c-735 the brief starts Bosun on the pack kit (`keel new pack --kit`): it writes only
the host's own layer, stand-in and sentences, never a copy of another pack, and the draft is
done when `keel pack check` is green.

`draft_connection` is the verb (`setup.pack.draft` {space, words}); `connection_cards` is
what the Setup report carries on `builder.connection`: the open draft and the newest done
one. Moved out of `keel/onboarding.py` in c-678.
"""

from __future__ import annotations

import json
from pathlib import Path

from keel import bases, builder, pausewake
from keel.config import Config
from keel.setupconfig import SetupError, install_of

CONNECTION_TITLE = "Draft a connection for another provider"
CONNECTION_WORDS_MAX = 8000
TARGET_OPTION = "target_space"      # options.target_space: the space a draft is for (r2.F4)
CONNECTION_ASK = "Which code host, and what should Shipyard do there? Say that first."
CONNECTION_BRIEF = """Draft a connection (a pack) to the user's code host, for the {space} space.

Keel ships no connection for this provider. The user's words, verbatim (they decide: where
they leave something out, ask them in your session before you guess):

{words}

A connection is a pack: its verbs are what Keel calls to open, publish and watch a change
on that host. The format is {atlas} ("The pack kit"); the rules for an extension are
{extending}. Start on the pack kit, in your clone of packs, on a branch
bosun/{card}-connection:

    keel new pack <name> --kit --into <your clone of packs>

That is a pack whose verbs are already the kit's: the card's worktree, its draft, Ship,
review and the guard are shared and tested once for every host. Write only what is this
host's own: the host layer (how to talk to it, in the kit's shapes); its stand-in (the
world the conformance suite runs that layer in, served as the host serves it); and
its sentences (its words in pack.toml, a `why` and a `fix` a person can follow for each
[[requires]], its rules). Never copy another pack, or a part of one: read the GitHub and
Gitea packs as examples, and where the kit lacks something this host needs, say so in your
plan. Never write a token or a password into the pack: a requirement checks for a sign-in
the host's own tool keeps. The draft is done when `keel pack check <your pack>` is green:
the pack's own suite passes and holds it to every contract its capabilities call for.

{reviews}

{bases}

This card shows its plan first: write plan.md in cards/{card}/ under your cwd and stage
planning, so the user reads what the connection will and will not do before you build it.
Then build, write the outcome as context.md, commit, and stage review with that plan and the
branch as the output. The user's Approve outcome lands it. Nothing changes for the {space}
space until they turn the connection on, on Where finished work goes; until then its work
is merged on this computer and pushed when they say."""

# c-730: the draft choice asks whether the drafted pack should also bring the user the pull requests
# that wait on their review; one of these two paragraphs says the answer in the brief.
REVIEWS_YES = """The user also wants the changes that wait on their review on this host brought to them as review
cards. The kit already has the verbs for it (`review scan`, `review <id> poll`, a review
card's `worktree`, `publish --answer` and `providers/reviews`, {atlas}, "Review requests";
{github} shows them in use): your layer's `review_requests` and `post_review` are what they
need. Declare `reviews = true` and `routes = ["reviews"]` under [capabilities], and
`review_scan = false` under [space], so the space is reviewed only once the user turns it
on; `keel pack check` then holds the review card's whole life too."""
REVIEWS_NO = """The user did not ask for review requests: leave review scanning out of the pack (no `reviews`
claim). It can be added later."""


def target_of(card: dict) -> str | None:
    """The space a connection draft is for (r2.F4): the card is filed in personal, whatever
    space it is for, so the space is recorded on it at create (`options.target_space`). None
    for a draft filed before it was."""
    target = (card.get("options") or {}).get(TARGET_OPTION)
    return target if isinstance(target, str) and target else None


def connection_cards(board, cfg: Config | None = None) -> dict:
    """`{open, done, pack, space}` of the connection drafts: the newest one not done as an open
    proposal reads (`{card, stage, waiting}`, and c-734: `gate`, the user's gate open on it,
    `told`, whether Bosun has heard of the user's last tap on it, and `space`, the space it is
    for), the id of the newest one that is done, `pack`, the pack that one's landing added
    (`drafted_pack`), and `space`, the space it was drafted for (r2.F4), so Where finished
    work goes draws that pack under the draft choice in that space only."""
    found = {"open": None, "done": None, "pack": None, "space": None}
    done = None
    for card in board.list_cards(include_archived=False):
        if card.get("title") != CONNECTION_TITLE:
            continue
        if card.get("stage") == "done":
            found["done"], found["space"], done = card["id"], target_of(card), card
        else:
            derived = card.get("derived") or {}
            gate = "plan" if derived.get("plan_gate") else "outcome" if derived.get("outcome_gate") else None
            found["open"] = {"card": card["id"], "stage": card["stage"], "waiting": bool(card.get("blocked_reason")),
                             "gate": gate, "told": pausewake.told(board, card["id"]), "space": target_of(card)}
    if done is not None and cfg is not None:
        found["pack"] = drafted_pack(cfg, done)
    return found


# The connection drafts alone, by title, oldest first: what a state build reads (r1.F9).
STANDING = "SELECT id, stage, space, repo, options FROM cards WHERE title = ? ORDER BY created_at, id"


def standing(board, cfg: Config) -> dict:
    """`{open: {card, space} | None, done, pack, space}`: how the connection drafts stand, for
    the first run's step state (`firstrunsteps.draft_waiting`), which is built on every poll
    (c-758 r1.F9). One query by title, as `firstrun.WATCHED` reads its cards, never the whole
    board with its views; an archived card is history and is not read. The pack a landed draft
    added is asked of git and kept as any reading is (`readiness.kept`, `KEEP_SECONDS`), keyed
    by the card and its merge, so the builds between two readings start no process. A read git
    could not make (`MergeRefused`) is kept for `RETRY_SECONDS` only: kept the full time, the
    step would let go for that long while the page shows the landed draft; not kept at all, a
    merge git can never read would start a process on every build."""
    from keel import merging, readiness      # noqa: PLC0415 - both read the setup modules

    def read(card: dict):
        try:
            return (added_pack(cfg, card),)
        except merging.MergeRefused:
            return None
    found = {"open": None, "done": None, "pack": None, "space": None}
    done = None
    for row in board.conn.execute(STANDING, (CONNECTION_TITLE,)).fetchall():
        try:
            options = json.loads(row["options"] or "{}")
        except ValueError:
            options = {}
        if options.get("archived") is True:
            continue
        card = {"id": row["id"], "space": row["space"], "repo": row["repo"], "options": options}
        if row["stage"] == "done":
            found["done"], found["space"], done = card["id"], target_of(card), card
        else:
            found["open"] = {"card": card["id"], "space": target_of(card)}
    if done is not None:
        merge = (done["options"].get("landing") or {}).get("merge")
        answer = readiness.kept(("drafted-pack", str(cfg.state_dir), done["id"], merge),
                                lambda: read(done), retry_failed=True)
        found["pack"] = answer[0] if answer else None
    return found


def drafted_pack(cfg: Config, card: dict) -> str | None:
    """The pack a landed connection draft added (c-734): the folder of a `pack.toml` its
    landing's merge brought into the packs repo (`options.landing.merge`, a merge whose first
    parent is what the repo held before). None when that cannot be read."""
    from keel import merging   # noqa: PLC0415 - merging reads the setup modules
    try:
        return added_pack(cfg, card)
    except merging.MergeRefused:
        return None


def added_pack(cfg: Config, card: dict) -> str | None:
    """`drafted_pack`, telling an answer from a read that failed: None is an answer (no
    landing recorded, or the landing added no one pack), and `MergeRefused` is git unable to
    say, which a caller that keeps answers keeps only briefly."""
    from keel import merging, packs   # noqa: PLC0415 - merging reads the setup modules
    merge = ((card.get("options") or {}).get("landing") or {}).get("merge")
    space = cfg.spaces.get(card.get("space") or "")
    repo = space.repos.get(card.get("repo") or "") if space is not None else None
    if not merge or repo is None:
        return None
    names = merging.git(repo, "diff", "--name-only", "--diff-filter=A", f"{merge}^1", merge).splitlines()
    added = [Path(name).parent.name for name in names if Path(name).name == packs.PACK_FILE and len(Path(name).parts) == 2]
    return added[0] if len(added) == 1 else None


def reviews_said(cfg: Config, reviews: bool) -> str:
    """The brief's paragraph on review requests: build them (`reviews` true, the user ticked
    it on the draft choice), or leave them out."""
    if not reviews:
        return REVIEWS_NO
    return REVIEWS_YES.format(github=cfg.root / "packs" / "github", atlas=cfg.root / "docs" / "atlas" / "62-packs.md")


def bases_said(cfg: Config, space: str) -> str:
    """c-732: the space's bases, as the flow draft says them (`bases.said`), and what the
    connection does with them: a card's change is taken against its own base."""
    return (bases.said(cfg, space) + " A card's own base is `options.base`: its change is opened "
            "against it, so the pack's `worktree` cuts from it and its `pr` aims at it.")


def draft_connection(cfg: Config, board, space: str, words: str, reviews: bool = False) -> dict:
    """`setup.pack.draft` {space, words, reviews}: file the card on which the in-app builder
    drafts a pack for a code host Keel ships no connection for, in the pattern of the import:
    a card on `packs`, at assigned, whose brief is the whole of it. It is attended, so the
    user reads its plan before anything is built. `reviews` (c-730) is the user's answer to
    whether the pack should also bring the pull requests that wait on their review."""
    install_of(cfg)
    if space not in cfg.spaces:
        raise SetupError(f"there is no space {space!r}")
    if not builder.in_app(cfg) or builder.PACKS not in builder.repos(cfg):
        raise SetupError("A connection is Bosun's to draft: choose a builder first, with packs in [builder] repos")
    words = (words or "").strip()
    if not words:
        raise SetupError(CONNECTION_ASK)
    if len(words) > CONNECTION_WORDS_MAX:
        raise SetupError(f"keep it under {CONNECTION_WORDS_MAX // 1000}k characters")
    open_one = connection_cards(board)["open"]
    if open_one:
        raise SetupError(f"{open_one['card']} is already drafting a connection ({open_one['stage']})")
    card = board.create("personal", CONNECTION_TITLE, brief="", repo=builder.PACKS, autonomy="attended",
                        options={TARGET_OPTION: space}, actor="human")
    atlas = cfg.root / "docs" / "atlas"
    board.set_fields(card, {"brief": CONNECTION_BRIEF.format(
        space=space, words=words, card=card, atlas=atlas / "62-packs.md",
        extending=atlas / "63-extending.md", reviews=reviews_said(cfg, reviews),
        bases=bases_said(cfg, space))}, "human")
    board.stage(card, "assigned", "human")
    pausewake.tell(board, card, "filed", cfg=cfg)   # c-734: asks the drain for one pass, whose wake tells Bosun
    return {"card": card, "space": space,
            "note": f"{card} filed: Bosun drafts the connection, and shows you its plan first. {pausewake.TOLD}."}
