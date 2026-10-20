"""The deck's Setup view (c-618): a fresh install clones its repos, writes their tiers and
turns a pack on, in the deck.

`report(cfg, board)` is what the view draws (`GET /api/setup`): per space its tier and its
repos (each with whether the path is there, whether the install cloned it, its tier and any
open tier proposal), every pack with its checks and rules (`keel/packsetup.py`), and
`start`, what the first-run stepper's screens show beyond the state (`firstrun.panels`,
c-632). `fresh` is true while no space lists a repo; the stepper reads it once, to tell a
new install from one that was set up before it existed.

The verbs (`VERBS`, run by `actions.SETUP_VERBS`):

- `setup.repo.clone` {space, key, url}: `git clone` into the layout (`keel/repolayout.py`),
  the space and repo tiers written from `etc/claude-md/` where absent, and the repo listed
  in `[spaces.<space>.repos]`. An existing checkout is never touched or moved.
- `setup.repo.add` {space, url, key?}: Add your repos (c-678). The space is made when it is
  not there, the key filled from the address when none is given, and the repo cloned as
  `setup.repo.clone` clones it. A copy that fails takes the space it made back out, and
  its refusal carries `detail`: the failure sorted into a kind (`keel/cloneerrors.py`).
- `setup.repo.attach` {space, key, path}: an existing checkout listed where it is (c-632),
  as `shipyard import` lists them; nothing is cloned or moved. The space is made when it
  is not there (c-678).
- `setup.repo.remove` {space, key}: the config entry only; the folder stays.
- `setup.space.add` {space}: a plain `[spaces.<space>]` served here, with the install's
  Claude dir and no repos (c-632).
- `setup.pack.on` {pack, space}: `packsetup.pack_on`, a new space or a plain one adopted.
- `setup.pack.off` {space}: `packsetup.pack_off`, the pack and what Turn on wrote for it
  taken off the space, which stays with its repos (c-688). Refused while the space has open
  cards.
- `setup.pack.build` {pack}: `packsetup.build_pack`, a pack cloned into the packs folder
  listed as the personal repo `pack-<name>` for Bosun to build in its own repo (c-740).
- `setup.tier.save` {space, key?, text}: the space tier, or a cloned repo's tier.
- `setup.tier.propose` {space, key?, likes}, `setup.tier.adopt` {card}: the audit card for a
  repo's or the space's tier, and its proposal written in (`keel/tiercards.py`). Adopt is
  his tap and the card's outcome (c-621): the card moves to done and its finished house is
  stopped. Approve outcome on the card is the same tap, through the same function
  (`adopt_proposal`, c-667), as it is for a flow proposal (`setup.flow.adopt`).
- `setup.pack.draft` {space, words, reviews?}: the card on which Bosun drafts a pack for a
  code host Keel ships no connection for (c-678, `draft_connection`), in the import's
  pattern; `reviews` true asks it to bring review requests too (c-730).
- `setup.flow.draft` {space}: the draft card Bosun works with the user for that space's flow
  (c-678, `flowcards.open_draft`), shown back on How work ships once it is at review.
- `setup.tier.draft` {space, key?}: the draft card Bosun works with the user for a tier that
  has none (c-678, `tiercards.open_draft`); a copied repo leaves one by itself.
- `setup.import` {}: "Import my Claude setup" (c-619), a card for the in-app builder that
  reads the user's own `~/.claude` and writes it as `packs/mine/` on its branch. No import
  code: the card's brief is the whole of it, and Approve outcome lands it.
- `setup.settings.save` {changes: [{table, space?, key, value}]}: the Settings view's Save
  (c-633, `keel/settings.py`). Every change is checked first, then all are written in one
  edit; a null value removes the key, so the default applies again.

Each refuses a config that is not an install's (`setupconfig.install_of`).

What touches git and the config for a repo (the copy, the attach, the space, the remove) is
`keel/reposetup.py`, and the connection draft is `keel/packdraft.py`: both were here until
c-678, when this module passed the size one is kept to. `clone_repo` and `add_repo` here are
those of `reposetup` with the draft card a copy leaves (`leave_draft`).
"""

from __future__ import annotations

import subprocess
from pathlib import Path

from keel import atomicfile, builder, cloneerrors, flowcards, house, merging, packclones, packdraft, packsetup, pausewake, repocommands
from keel import repolayout, reposetup
from keel import settings, tiercards, tierdrafts, tierrecord
from keel.board import Refused, open_board, proposals_of
from keel.config import Config, remote_of
from keel.reposetup import add_space, ensure_tier  # noqa: F401 - Setup's own, by their old names too
from keel.setupconfig import SetupError, install_of, installed, space_of

TIER_MAX = 64 * 1024


# ----- the report -----

def read(path: Path | None) -> str | None:
    return path.read_text() if path is not None and path.is_file() else None


FACT_SECONDS = 10


def git_says(path: Path, *args: str) -> str | None:
    """One line git prints about a repo, or None: a fact for the page, never a refusal."""
    try:
        done = subprocess.run(["git", "-C", str(path), *args], capture_output=True, text=True, timeout=FACT_SECONDS)
    except (OSError, subprocess.SubprocessError):
        return None
    return done.stdout.strip() or None if done.returncode == 0 else None


def repo_row(key: str, path: Path, proposal: dict | None, spaces: Path | None, remote: str = "origin") -> dict:
    """`origin` and `branch` (c-678) are the two facts Add your repos checks beside the copy:
    the address of the space's remote, and the branch the copy has out."""
    home = repolayout.home_of(path, spaces)
    ok = (Path(path) / ".git").exists()
    return {"key": key, "path": str(path), "ok": ok,
            "cloned": home is not None,
            # never with the user or password an address may carry (review F13)
            "origin": cloneerrors.shown_address(git_says(path, "config", "--get", f"remote.{remote}.url")) or None
            if ok else None,
            "branch": git_says(path, "symbolic-ref", "--short", "-q", "HEAD") if ok else None,
            "tier": read(home / repolayout.TIER) if home else None, "proposal": proposal}


def space_row(home: Path | None, name: str, space, open_ones: dict, remote: str = "origin") -> dict:
    tier = repolayout.space_dir(home, name) / repolayout.TIER if home else None
    return {"pack": space.adapter, "tier": read(tier) if tier else None, "writable": home is not None,
            "proposal": open_ones.get(name),
            "repos": [repo_row(key, path, open_ones.get(f"{name}/{key}"),
                               home / repolayout.SPACES if home else None, remote)
                      for key, path in space.repos.items()]}


def fresh(cfg: Config) -> bool:
    """No space lists a repo of the user's yet (the install's own packs and memory repos are
    not, `builder.OWN_REPOS`)."""
    home = installed(cfg)
    return not any(key for space in cfg.spaces.values() for key, path in space.repos.items()
                   if not builder.is_own(home, path))


def open_import(board) -> dict | None:
    """The newest import card that is not done (`import_setup`), as an open proposal reads:
    `{card, stage, waiting}`."""
    found = None
    for card in board.list_cards(include_archived=False):
        if card.get("title") == IMPORT_TITLE and card.get("stage") != "done":
            found = {"card": card["id"], "stage": card["stage"], "waiting": bool(card.get("blocked_reason"))}
    return found


def report(cfg: Config) -> dict:
    from keel import firstrun, readiness  # noqa: PLC0415 - firstrun reads this module's `fresh`
    # The report runs every check afresh, so the deck's kept readings go with it: the next
    # state reads them again, and the stepper's marks agree with what this page shows.
    readiness.forget()
    home = installed(cfg)
    with open_board(cfg) as board:
        open_ones = tiercards.proposals(board)
        importing = open_import(board)
        connection = packdraft.connection_cards(board, cfg)   # c-678: a connection Bosun is drafting
        # c-678: what came back from Bosun, per space with a copied repo
        drafts = {name: tierdrafts.rows(cfg, board, name) for name in tierdrafts.spaces(cfg)}
        # c-678: a space's open flow proposal, drawn once it is at review (How work ships)
        flow_drafts = {name: flowcards.shown(cfg, board, name) for name in cfg.spaces}
    packclones.reconcile(cfg)     # c-740: the packs repo ignores a pack cloned into its folder
    listed = packsetup.listing(cfg)
    status = builder.status(cfg)
    return {"install": str(home) if home else None, "config": str(cfg.source),
            "fresh": fresh(cfg),
            # c-664: with the import's open card, so its panel says where the tap went
            "builder": dict(status, importing=importing, connection=connection) if status else status,
            "spaces": {name: dict(space_row(home, name, space, open_ones, remote_of(cfg, name)),
                                  drafts=drafts.get(name, []), flow_draft=flow_drafts.get(name))
                       for name, space in cfg.spaces.items()},
            "packs": listed["rows"], "packs_error": listed["problem"],
            # c-758 r1.F7, F13: the same problem lines in the first run's word, and whether
            # they are about a folder of the install's own packs folder
            "connections_error": listed["said"], "packs_error_install": listed["install"],
            # c-740 r1.F8: where a shared pack is cloned, quoted as a shell reads it
            "packs_folder": packsetup.packs_folder(cfg), "start": firstrun.panels(cfg)}


# ----- repos (`keel/reposetup.py`) -----

def clone_repo(cfg: Config, space: str, key: str, url: str, board=None) -> dict:
    """Setup's clone (`reposetup.clone_repo`); on an install with a builder the copy leaves a
    draft card for its CLAUDE.md (`leave_draft`, c-678)."""
    return reposetup.clone_repo(cfg, space, key, url, drafts_on(board))


def add_repo(cfg: Config, space: str, url: str, key: str = "", board=None) -> dict:
    """Add your repos (`reposetup.add_repo`), with the same draft card."""
    return reposetup.add_repo(cfg, space, url, key, drafts_on(board))


def drafts_on(board):
    """What a copy calls to leave its draft card, on this board."""
    return lambda cfg, space, key, repos: leave_draft(cfg, board, space, key, repos)


def leave_draft(cfg: Config, board, space: str, key: str | None, repos: list[Path]) -> str | None:
    """The draft card Bosun works with the user for this tier (`tiercards.open_draft`, c-678),
    filed with the copy since the copy is the user's tap. None with no builder, or when the
    tier already has an open proposal. A card that cannot be filed never fails the copy."""
    if not builder.in_app(cfg):
        return None
    try:
        if board is not None:
            return tiercards.open_draft(cfg, board, space, key, repos)
        with open_board(cfg) as own:
            return tiercards.open_draft(cfg, own, space, key, repos)
    except (Refused, SetupError):
        return None


# ----- tiers -----

ADOPTED = "adopted"     # the data of the note a written draft leaves on its card: where it went
WRITERS = {
    tiercards.OPTION: lambda cfg, board, card_id: tiercards.adopt(
        cfg, board, card_id, lambda space, key: tier_path(cfg, space, key)),
    flowcards.OPTION: lambda cfg, board, card_id: flowcards.adopt(cfg, board, card_id),
}
DRAFTS = {tiercards.OPTION: tiercards.draft, flowcards.OPTION: flowcards.draft}
BOTH = "{card} names both a tier and a flow proposal, so nothing is adopted; archive it and propose again"
NEVER = ("{card} is done, and its draft as it is now was never adopted, so nothing was written. "
         "Propose again for a new draft.")
GONE = ("{card} was adopted into {where}, which is gone since; it is done, so nothing is written "
        "again: propose again")
BUSY = "another tap is adopting {card} and is still running; this one wrote nothing"


def proposes(card: dict) -> list[str]:
    """The proposals a card names (`board.proposals_of`): one for a tier or a flow proposal,
    none for any other card. Two is a card `adopt_proposal` refuses."""
    return proposals_of(card.get("options"))


def adopted_into(cfg: Config, board, card: dict, kind: str) -> str | None:
    """Where the card's draft AS IT IS NOW was already written, or None. True only when the
    newest note that says adopted is HIS (a note, by the human) and carries this draft's
    digest: not the card's stage, and not a note anyone else left (review F2, F7). A revised
    draft has another digest, so it is written again. The path may be gone since (a flow
    reset, a tier removed): the caller looks, and then a card at review is written again
    and a done one says so."""
    text = DRAFTS[kind](cfg, card["id"])
    said = [event for event in board.events(card["id"]) if (event.get("data") or {}).get(ADOPTED)]
    if not said or not text.strip():
        return None
    newest = said[-1]
    his = newest["kind"] == "note" and newest["actor"] == "human"
    same = newest["data"].get("digest") == tiercards.digest(text)
    return newest["data"][ADOPTED] if his and same else None


def adopt_proposal(cfg: Config, board, card_id: str, kind: str | None = None) -> dict:
    """The ONE way a proposal's draft is written (c-667): Adopt in Setup and the card's own
    outcome tap (the deck's, `kb approve`) all come here, so they make the same checks.

    The check, the write and the move are under the card's approve lock, so two taps never
    both write: the second is refused while the first runs. `kind` is the proposal a Setup
    verb is for; the card's own tap takes the card's."""
    try:
        with merging.approve_lock(cfg, card_id):
            return adopt_locked(cfg, board, card_id, kind)
    except merging.MergeRefused:
        raise SetupError(BUSY.format(card=card_id)) from None


def adopt_locked(cfg: Config, board, card_id: str, kind: str | None) -> dict:
    """The draft written by its kind's writer (`tiercards.adopt`, `flowcards.adopt`), which
    refuses a draft that is missing or does not check: then nothing is written and the card
    stays at review. A written draft leaves his note on the card with where it went and its
    digest, and a tap that finds that note for the draft as it is now writes nothing: it only
    moves the card, when an earlier move was refused, and says it was already adopted."""
    card = board.get(card_id)
    named = proposes(card)
    if len(named) > 1:
        raise SetupError(BOTH.format(card=card_id))
    kind = kind or (named[0] if named else tiercards.OPTION)
    where = adopted_into(cfg, board, card, kind) if kind in named else None
    if where and Path(where).is_file():
        answer = {"card": card_id, "already": True}
        said = f"{card_id} was already adopted into {where}; nothing was written again"
    elif kind in named and card["stage"] == "done":
        raise SetupError((GONE if where else NEVER).format(card=card_id, where=where))
    else:
        answer = WRITERS[kind](cfg, board, card_id)
        where, kept = answer.get("tier") or answer["path"], answer.pop("kept", None)
        said = f"adopted into {where}" + (f", {kept}" if kept else "")
        data = {ADOPTED: where, "digest": answer.pop("digest")}
        if kind == tiercards.OPTION:
            # review F3: the digest of what was WRITTEN (the draft less its audit notes), so
            # the lines Keel runs come only from this text (`keel/tierrecord.py`)
            data.update(tierrecord.data(where, Path(where).read_text()))
        board.note(card_id, said, "human", data=data)
        named = lands_named(cfg, card, board) if kind == tiercards.OPTION else None
        if named:
            said = f"{said}; {named}"
    return closed(cfg, board, card_id, dict(answer, where=where), said)


def lands_named(cfg: Config, card: dict, board=None) -> str | None:
    """A repo's file was just adopted: nothing is checked out (c-734); when it names a branch
    to land on, the answer says the line moves nothing (`repocommands.lands_said`)."""
    space, _, key = str((card.get("options") or {}).get(tiercards.OPTION) or "").partition("/")
    return repocommands.lands_said(cfg, space, key, board) if key else None


def closed(cfg: Config, board, card_id: str, answer: dict, said: str) -> dict:
    """An adopted proposal's card done and its finished house stopped (c-621), since the tap
    is his and is the card's outcome. A move the board refuses leaves the draft written and
    the card at review, and the answer says why; the next tap tries the move again."""
    card = board.get(card_id)
    if card["stage"] != "done":
        try:
            card = board.approve(card_id, "outcome", "human")
        except Refused as refused:
            return dict(answer, stage=board.get(card_id)["stage"],
                        note=f"{said}, but {card_id} was not moved to done: {refused}")
        if card.get("session_id") and card["stage"] == "done":
            house.retire_finished(cfg, board, card)
    return dict(answer, stage=card["stage"], note=said)


def adopt_tier(cfg: Config, board, card_id: str) -> dict:
    """Setup's Adopt for a tier proposal: refuses a card that is not one."""
    return adopt_proposal(cfg, board, card_id, tiercards.OPTION)


def adopt_flow(cfg: Config, board, card_id: str) -> dict:
    """Setup's Adopt for a flow proposal (c-640): refuses a card that is not one."""
    return adopt_proposal(cfg, board, card_id, flowcards.OPTION)


def tier_path(cfg: Config, space: str, key: str | None = None) -> Path:
    """The space tier, or the tier of a repo the install cloned."""
    home = install_of(cfg)
    found = space_of(cfg, space)
    if not key:
        return repolayout.space_dir(home, space) / repolayout.TIER
    folder = repolayout.home_of(found.repos.get(key), home / repolayout.SPACES)
    if folder is None:
        raise SetupError(f"{space}/{key} was not cloned by this install, so it has no repo tier here")
    return folder / repolayout.TIER


def save_tier(cfg: Config, board, space: str, key: str | None, text: str) -> dict:
    """The page's own Save. It is the user's tap, so it is recorded as one (review F3,
    `tierrecord.saved`): the lines Keel runs come from this text until the file changes."""
    if len(text.encode()) > TIER_MAX:
        raise SetupError(f"a tier is kept short: this one is over {TIER_MAX // 1024} KB")
    path = tier_path(cfg, space, key)
    written = text if text.endswith("\n") or not text else text + "\n"
    atomicfile.write_text(path, written)
    tierrecord.saved(board, path, written)
    # a repo's file saved is a repo's file adopted: nothing is checked out, and a lands line
    # is said to move nothing (c-734, `repocommands.lands_said`)
    named = repocommands.lands_said(cfg, space, key, board) if key else None
    return {"tier": str(path), **({"note": f"{path.name} saved; {named}"} if named else {})}


def propose(cfg: Config, board, space: str, key: str | None, likes: str) -> dict:
    """The audit card for a cloned repo's tier, or (no key) for the space tier over every
    repo the install cloned into the space."""
    tier_path(cfg, space, key)          # an install's space, or a cloned repo of it
    repos = space_of(cfg, space).repos
    spaces = repolayout.spaces_of(cfg)
    reading = [repos[key]] if key else [path for path in repos.values() if repolayout.home_of(path, spaces)]
    return tiercards.propose(cfg, board, space, key, reading, likes)


def open_draft(cfg: Config, board, space: str, key: str | None) -> dict:
    """`setup.tier.draft` (c-678): the draft card for a tier that has none, by the user's tap
    on its row, for a repo copied in before draft cards or one whose card was archived."""
    tier_path(cfg, space, key)          # an install's space, or a copied repo of it
    if not builder.in_app(cfg):
        raise SetupError("a draft is Bosun's to write with you: choose a builder first")
    aim = tiercards.aim_of(space, key)
    repos = space_of(cfg, space).repos
    reading = [repos[key]] if key else [path for _, path in tierdrafts.copied_repos(cfg, space)]
    card = tiercards.open_draft(cfg, board, space, key, reading)
    if card is None:
        raise SetupError(f"{aim} already has an open draft or proposal")
    return {"card": card, "aim": aim, "note": f"{card} is open for Bosun to draft {aim}"}


# ----- Import my Claude setup (c-619) -----

IMPORT_TITLE = "Import my Claude setup"
IMPORT_BRIEF = """Bring the user's own Claude setup into this install as the pack `mine`.

Read their ~/.claude: CLAUDE.md, skills/, agents/ and commands/ (your settings allow exactly
these; settings.json and .credentials.json are denied, and you never ask for them). In your
clone of packs, on a branch bosun/{card}-import, write them as mine/: a pack.toml (name
"mine", the Atlas page Packs has its keys), rules/ from CLAUDE.md, and skills/, agents/ and
commands/ as they are.

Settings, hooks and MCP servers are not imported: say so in the outcome, so the user carries
them over by hand. Write the plan and the outcome as plan.md and context.md in
cards/{card}/ under your cwd, commit, then stage review with that plan and the branch as the
output. The user's Approve outcome lands it; it is live on the next deck and drain restart."""


def import_setup(cfg: Config, board) -> dict:
    """File the card that asks the in-app builder to import the user's own Claude setup."""
    install_of(cfg)
    if not builder.in_app(cfg) or builder.PACKS not in builder.repos(cfg):
        raise SetupError("Import is the in-app builder's: turn bosun_builder on, with packs in [builder] repos")
    card = board.create("personal", IMPORT_TITLE, brief="", repo=builder.PACKS, autonomy="autonomous",
                        actor="human")
    board.set_fields(card, {"brief": IMPORT_BRIEF.format(card=card)}, "human")
    board.stage(card, "assigned", "human")
    pausewake.tell(board, card, "filed", cfg=cfg)   # c-734: asks the drain for one pass, whose wake tells Bosun
    return {"card": card, "note": f"{card} filed: Bosun imports your Claude setup. {pausewake.TOLD}."}


def text_of(body: dict, name: str) -> str:
    return str(body.get(name) or "")


VERBS = {
    "setup.repo.clone": lambda cfg, body, board: clone_repo(cfg, text_of(body, "space"), text_of(body, "key"),
                                                            text_of(body, "url"), board),
    "setup.repo.add": lambda cfg, body, board: add_repo(cfg, text_of(body, "space"), text_of(body, "url"),
                                                        text_of(body, "key"), board),
    "setup.repo.attach": lambda cfg, body, board: reposetup.attach_repo(cfg, text_of(body, "space"), text_of(body, "key"),
                                                              text_of(body, "path")),
    "setup.repo.remove": lambda cfg, body, board: reposetup.remove_repo(cfg, board, text_of(body, "space"),
                                                              text_of(body, "key")),
    "setup.space.add": lambda cfg, body, board: add_space(cfg, text_of(body, "space")),
    "setup.pack.on": lambda cfg, body, board: packsetup.pack_on(cfg, text_of(body, "pack"), text_of(body, "space")),
    "setup.pack.off": lambda cfg, body, board: packsetup.pack_off(cfg, board, text_of(body, "space")),
    # c-740 r1.F1: a pack cloned into the packs folder, listed for Bosun to build in its own repo
    "setup.pack.build": lambda cfg, body, board: packsetup.build_pack(cfg, text_of(body, "pack")),
    "setup.tier.save": lambda cfg, body, board: save_tier(cfg, board, text_of(body, "space"),
                                                          text_of(body, "key") or None, text_of(body, "text")),
    "setup.tier.propose": lambda cfg, body, board: propose(cfg, board, text_of(body, "space"), text_of(body, "key") or None,
                                                           text_of(body, "likes")),
    "setup.tier.adopt": lambda cfg, body, board: adopt_tier(cfg, board, text_of(body, "card")),
    "setup.tier.draft": lambda cfg, body, board: open_draft(cfg, board, text_of(body, "space"),
                                                            text_of(body, "key") or None),
    "setup.import": lambda cfg, body, board: import_setup(cfg, board),
    # c-678: a connection for a code host Keel ships none for, drafted by Bosun on its own card
    "setup.pack.draft": lambda cfg, body, board: packdraft.draft_connection(cfg, board, text_of(body, "space"),
                                                                 text_of(body, "words"), body.get("reviews") is True),
    # c-640: a space's flow, proposed from his words, adopted by his tap, or reset
    "setup.flow.propose": lambda cfg, body, board: flowcards.propose(cfg, board, text_of(body, "space"),
                                                                     text_of(body, "words")),
    "setup.flow.adopt": lambda cfg, body, board: adopt_flow(cfg, board, text_of(body, "card")),
    # c-678: the card on which Bosun drafts a space's flow with the user, by the user's tap
    "setup.flow.draft": lambda cfg, body, board: flowcards.open_draft(cfg, board, text_of(body, "space")),
    "setup.flow.reset": lambda cfg, body, board: flowcards.reset(cfg, text_of(body, "space")),
    "setup.settings.save": lambda cfg, body, board: settings.save(cfg, body.get("changes")),
}
# The verbs that change the config, after which the deck re-execs to read it.
CONFIG_VERBS = ("setup.repo.clone", "setup.repo.add", "setup.repo.attach", "setup.repo.remove", "setup.space.add",
                "setup.pack.on", "setup.pack.off", "setup.pack.build", "setup.settings.save",
                # c-678: the Back up step's Turn on writes `[backup]` (`keel/backupsetup.py`)
                "firstrun.backup.on",
                # c-678: an unknown key's line removed or renamed (`keel/stuckcards.py`)
                "setup.config.remove", "setup.config.rename")
