"""Bosun's repairs of a card's board mechanics, in every space (c-575; docs/atlas/96-bosun.md).

His rule (2026-09-29): anything stopping the board from behaving as it should is Bosun's to
fix, on any card, in every space, work included. A repair is the ordinary verb with
`--why`: recorded as an `intervene` event signed `bosun` with the reason, and confined to
Keel's own mechanics. Nothing counts them (the three strikes an hour went with driving,
c-593). What a card IS (its title, brief, scope, autonomy, repo, model) and its gates stay
his.

It is an authority path (`authority.AUTHORITY_PATHS`): Bosun's guard refuses it a write
here, and an outcome that touches it is his to approve.
"""

import subprocess
from pathlib import Path

from keel import childenv, views
from keel.authority import BOSUN, options_of, refused

REPAIR = "repair"
# `field`: plan_ref, output_ref or a worktree path; `unblock`, `resume`, `retry`: a house
# whose block Keel wrote; `stage`: the stage the card is already at, replayed.
REPAIR_KINDS = ("field", "unblock", "resume", "retry", "stage")
HOUSE_REPAIRS = ("unblock", "resume", "retry")
REPAIR_REFS = ("plan_ref", "output_ref")
REPAIR_TREES = ("worktree", "worktrees")
# Who may mark a block as Keel's mechanics (`--mark mechanics`, `board.MARKS`): the drain
# and the hook, where a house failed to start, a round could not start, or a landing merged
# and did not move. A block they write without the mark (a failed merge, a quiet house, a
# card with no model) says the fix is his, and is not repaired.
MECHANICS_WRITERS = ("drain", "hook")
# Where a replay may run: no landing or pull request waits there, so re-recording the move
# withdraws nothing of his (review 2.F1, 2.F3); planning only while his plan gate is not
# open (`refuse_restage`, review 3.F5).
REPLAY_STAGES = ("assigned", "planning", "building")
# Who writes a `kb block --keel` a repair may mend: a house saying Keel is in its way. Bosun's
# own `--keel` block is not one, or it could turn any block into a repairable one (3.F1).
KEEL_REQUESTERS = ("house",)
WHY_MAX = 300


def refuse_mechanics_mark(actor: str, mark: str | None) -> None:
    """`--mark mechanics` makes a block repairable by Bosun, so only Keel writes it."""
    if mark == "mechanics" and actor not in MECHANICS_WRITERS:
        raise refused(f"--mark mechanics is Keel's own (the drain's or the hook's), not {actor}'s")


def refuse_why(actor: str, why: str | None) -> None:
    """`--why` asks for a repair, which is Bosun's alone; from Bosun it must say something."""
    if why is None:
        return
    if actor != BOSUN:
        raise refused("--why asks for a Bosun repair; it is Bosun's alone")
    if not why.strip():
        raise refused("a repair says what broke: --why \"<what broke>\"")
    if len(why) > WHY_MAX:
        raise refused(f"--why is at most {WHY_MAX} characters")


def refuse_repair(card, kind: str, actor: str, why: str, events: list[dict]) -> None:
    """A repair by Bosun, on a card in any space: never a held card, and for a house only
    while its block is Keel's mechanics."""
    if actor != BOSUN:
        raise refused("a repair is Bosun's; he changes a card from the deck")
    if kind not in REPAIR_KINDS:
        raise refused(f"a repair is one of {', '.join(REPAIR_KINDS)}, not {kind!r}")
    refuse_why(actor, why)
    options = options_of(card)
    if views.voice_hold(options) or views.dropin_holding(options):
        raise refused(f"{card['id']} is held (a voice conversation or a drop-in): Bosun waits")
    if kind in HOUSE_REPAIRS:
        refuse_unless_mechanics(card, events)


def block_writer(card, events: list[dict]) -> dict | None:
    """The block event that set the card's standing block, or None when none matches it."""
    reason = card["blocked_reason"]
    blocks = [e for e in events if e["kind"] == "block"]
    return blocks[-1] if blocks and reason and blocks[-1].get("text") == reason else None


def refuse_unless_mechanics(card, events: list[dict]) -> None:
    """A house repair needs a block Keel marked as its own mechanics (`--mark mechanics`, by
    the drain or the hook), a house's `kb block --keel` (it filed a request), or the drain's
    failed resume. Bosun's own failed resume is his: with no strike limit, a repair that
    failed and re-marked the card repairable would loop on every pass (c-593 review). Everything else is his: a house's question, his
    block, a failed merge, a quiet house, a permission pause, a login hold, the review
    limit."""
    if not card["blocked_reason"]:
        raise refused(f"{card['id']} is not blocked: a house repair mends a block Keel wrote")
    event = block_writer(card, events)
    if event is None:
        raise refused(f"{card['id']}'s block has no block event behind it, so who wrote it "
                      f"cannot be read: it is his")
    data = event.get("data") or {}
    if options_of(card).get("login_hold"):
        raise refused(f"{card['id']} waits for a login, which is his")
    if data.get("paused") == "permission" or data.get("limit") == "review":
        raise refused(f"{card['id']}'s block is a permission pause or the review limit: his, "
                      f"or it clears itself")
    marked = data.get("mechanics") and event["actor"] in MECHANICS_WRITERS
    failed = data.get("failed") == "resume" and event["actor"] in MECHANICS_WRITERS
    requested = data.get("request") and event["actor"] in KEEL_REQUESTERS
    if not (marked or failed or requested):
        raise refused(f"{card['id']}'s block (by {event['actor']}) is not Keel's mechanics: a "
                      f"question or a block that is his to answer")


def repair_paths(card, fields: dict) -> tuple[list[str], list[str], dict[str, list[str]]]:
    """The files and the worktrees a repair `set` names, for the path facts, and the repo
    each tree must belong to: `options.worktree` the card's first, `options.worktrees` by
    its key (c-585)."""
    files = [str(fields[name]) for name in REPAIR_REFS
             if fields.get(name) and not str(fields[name]).startswith("http")]
    options = fields.get("options") or {}
    owners: dict[str, list[str]] = {}
    first = next(iter(card_repos(card)), None)
    if options.get("worktree") and first:
        owners.setdefault(first, []).append(str(options["worktree"]))
    trees = [str(options["worktree"])] if options.get("worktree") else []
    recorded = options.get("worktrees")
    for key, path in (recorded.items() if isinstance(recorded, dict) else ()):
        if path:
            trees.append(str(path))
            owners.setdefault(str(key), []).append(str(path))
    return files, trees, owners


def card_repos(card) -> list[str]:
    """The card's repo keys, in order: `adapters.repos_of`, which imports the board, which
    imports this module."""
    return [key.strip() for key in (card["repo"] or "").split(",") if key.strip()]


def path_facts(cards_dir: Path, card_id: str, files: list[str], trees: list[str]) -> dict:
    """Whether each file is an existing file inside this card's own directory, and each tree
    an existing git worktree, on THIS machine. Existence only: nothing is read."""
    home = (Path(cards_dir) / card_id).resolve()

    def own_file(text: str) -> bool:
        path = Path(text).expanduser()
        try:
            return path.is_absolute() and path.resolve().parent == home and path.is_file()
        except OSError:
            return False

    def worktree(text: str) -> bool:
        path = Path(text).expanduser()
        return path.is_absolute() and path.is_dir() and (path / ".git").exists()

    return {"files": {text: own_file(text) for text in files},
            "trees": {text: worktree(text) for text in trees}}


def git_env() -> dict:
    """This process's environment for a git that reads only the path it is given: no `GIT_`
    variable, since git ranks an inherited `GIT_DIR` (a Keel run under a git hook) above
    `-C` and every tree would answer the same (c-588), and none of `childenv.WITHHELD`."""
    return {name: value for name, value in childenv.own_env().items()
            if not name.startswith("GIT_")}


def git_home(path: Path) -> Path | None:
    """The repository a tree belongs to, as git says it: its common git directory, the same
    for a checkout and every linked worktree of it. None when git cannot say."""
    try:
        result = subprocess.run(["git", "-C", str(path), "rev-parse", "--path-format=absolute",
                                 "--git-common-dir"], capture_output=True, text=True, timeout=10,
                                env=git_env())
    except (OSError, subprocess.SubprocessError):
        return None
    line = result.stdout.strip()
    return Path(line).resolve() if result.returncode == 0 and line else None


def owner_facts(cfg, card, owners: dict) -> dict:
    """For each repo key, whether each tree named for it is a worktree of the checkout that
    key names in the install's config.toml on THIS machine (c-585). Git's answer only: nothing is read."""
    space = cfg.spaces.get(card["space"])
    facts: dict[str, dict[str, bool]] = {}
    for key, paths in (owners or {}).items():
        if not isinstance(key, str) or not isinstance(paths, list):
            continue
        checkout = space.repo_path(key) if space else None
        home = git_home(Path(checkout).expanduser()) if checkout else None
        facts[key] = {str(path): bool(home) and isinstance(path, str) and Path(path).is_absolute()
                      and git_home(Path(path)) == home for path in paths}
    return facts


def repair_facts(cfg, card: dict, fields: dict) -> dict:
    """The path facts a repair `set` is checked against, read from this machine's disk,
    where every card's files live."""
    files, trees, owners = repair_paths(card, fields)
    if not (files or trees):
        return {"files": {}, "trees": {}, "repos": {}}
    return dict(path_facts(cfg.cards_dir, card["id"], files, trees),
                repos=owner_facts(cfg, card, owners))


def refuse_repair_set(card, fields: dict, facts: dict) -> None:
    """A repair `set` changes only the paths Keel reads, each to a path that is there: a ref
    to this card's own file under the same name (normalising, never another document), a
    worktree that exists."""
    options = fields.get("options") or {}
    others = [name for name in fields if name not in (*REPAIR_REFS, "options")]
    others += [f"options.{name}" for name in options if name not in REPAIR_TREES]
    if others or not fields:
        raise refused(f"a repair changes only plan_ref, output_ref, options.worktree and "
                      f"options.worktrees; {', '.join(others) or 'nothing'} is his")
    for name in REPAIR_REFS:
        if name in fields:
            refuse_ref(card, name, fields[name], facts)
    for name in REPAIR_TREES:
        if name in options:
            refuse_trees(card, name, options[name], facts)


def refuse_ref(card, name: str, value, facts: dict) -> None:
    text = str(value or "")
    if not text or text.startswith("http"):
        raise refused(f"a repaired {name} names a file of {card['id']}, not {text or 'nothing'}")
    if not (facts.get("files") or {}).get(text):
        raise refused(f"{text} is not an existing file in {card['id']}'s own directory")
    old = card[name] or ""
    # From an empty ref there is nothing to normalise: a plan_ref set from none opens his
    # plan gate and ends the house's planning, which is a move, not a path (review 4.F3).
    wanted = Path(old).name if old and not old.startswith("http") else None
    if wanted is None or Path(text).name != wanted:
        raise refused(f"a repair normalises {name}'s path, it never swaps the document: the "
                      f"file must still be {wanted or 'the one it names'}, not {Path(text).name}")


def refuse_trees(card, name: str, value, facts: dict) -> None:
    """A worktree repair normalises the path the card already records, as a ref repair does:
    the same repos (the map's keys), each tree under the same directory name, each one there,
    and each a worktree of its own repo's checkout (c-585: work cards name every repo's tree
    after one branch, so a name alone would let two repos' trees swap). A new repo, a
    dropped one or another tree is his (review 3.F2, 3.F3)."""
    old = options_of(card).get(name)
    if name == "worktrees":
        if not isinstance(value, dict) or not isinstance(old, dict) or set(value) != set(old):
            raise refused(f"a repair keeps options.worktrees' repos as they are "
                          f"({', '.join(sorted(old)) if isinstance(old, dict) else 'none recorded'})")
        triples = [(str(value[key]), str(old[key] or ""), str(key)) for key in value]
    else:
        triples = [(str(value or ""), str(old or ""), next(iter(card_repos(card)), ""))]
    for path, was, key in triples:
        if not was or Path(path).name != Path(was).name:
            raise refused(f"a repair normalises a worktree's path, it never picks another tree: "
                          f"{path or 'nothing'} is not named as {was or 'no recorded tree'}")
        if not (facts.get("trees") or {}).get(path):
            raise refused(f"{path} is not an existing git worktree")
        if not ((facts.get("repos") or {}).get(key) or {}).get(path):
            raise refused(f"{path} is not a worktree of {card['id']}'s {key or 'repo'} checkout "
                          f"(or its machine did not say which repo it is)")


def refuse_restage(card, new_stage: str, refs: dict, relay: dict | None,
                   note: str | None = None) -> None:
    """A replay of a failed move: to the stage the board already records, nothing else in
    the same write (a ref is a repair `set`, a relay is his, and the note is the fixed
    replay line: Bosun writes no free text on a card it does not build)."""
    if new_stage != card["stage"]:
        raise refused(f"a repair re-stages {card['id']} only to {card['stage']}, the stage the "
                      f"board records; {new_stage} is his")
    if new_stage not in REPLAY_STAGES:
        raise refused(f"a replay runs only at {', '.join(REPLAY_STAGES)}; at {new_stage} a gate, "
                      f"a landing or a pull request waits, and that is his")
    if (new_stage == "planning" and card["autonomy"] == "attended"
            and card["plan_ref"] is not None):
        raise refused(f"{card['id']}'s plan is at his gate: a replay there is his")
    if refs or relay is not None or note:
        raise refused("a repair re-stage carries no --plan, --output, --relay or --note")


def refuse_words(words: str | None) -> None:
    """A repair resume or retry says nothing of Bosun's to the house (his D3): the house
    hears the plain resume line, and the why stays on the card."""
    if (words or "").strip():
        raise refused("a repair resume carries no words: the house hears the plain resume line")
