"""Flows: how a space's work moves from a card's branch to where it ends (c-640, c-639 S1).

A flow names the BRANCHES (and environments) a card's work passes through, and the MOVES
between them, each with who makes it:

- `you`: the owner's tap or word, carried out by the card's house. The ONE thing a flow
  DOES: the card shows a button, and the tap tells the house the move's `prompt`
  (`actions.flow_move`). `pushes` names the branches the house may push to for that move
  only (`keel/flowfence.py`, c-641). `him` is the older spelling of `you` and still loads.
- `house`, `keel`, `colleague`: a PICTURE of what the house's pipeline, Keel's own steps
  (`publish` is Approve outcome, `ship` is Ship, `land` lands the card, `deploy` is the
  deploy) and people on the code host already do. Drawn, and read by nothing else: what
  Approve and Ship do is the space's pack's and Keel's, and writing it differently here
  changes the drawing only (c-664).

Keel ships three (`etc/flows/`, `default_of`): the general one for a space whose pack
declares a code host, one for a space whose every repo lands on an `[integration]` branch
(Keel's own), and a local merge for any other. A team's own flow is IMPORTED, per space
(2026-10-04): `<install>/spaces/<space>/flow.toml`, written by Adopt (`keel/flowcards.py`)
after an agent proposed it from the owner's words. A pack may bring a default
(`packs/<pack>/flow.toml`). The space's own file wins, then the pack's, then Keel's.

Flow text may say `{change}` and `{Change}` (any of the space's `[terms]`), filled when the
flow is read for a space (`of`), so one file reads right for a pull request and a merge
request (c-664). Keel's own flows are DRAWN with a landing branch's name (`drawn`); the
files label it in words, which name no git branch, so the push fence reads nothing new.

A flow file that does not load is a warning (`Config.warnings`-like, `warnings_for`) and
the next source is used: a broken flow never stops the deck. Loading checks the SHAPE;
whether a flow can run is `keel/flowcheck.py`, asked by `keel flow check` and by Adopt. The
rules are Atlas 64.
"""

from __future__ import annotations

import dataclasses
import re
import tomllib
from dataclasses import dataclass, field
from pathlib import Path

from keel import packs, repolayout, terms

FILE = "flow.toml"
HERE = Path(__file__).resolve().parent.parent / "etc" / "flows"
GENERAL = HERE / "general.toml"            # a space whose pack declares a code host
INTEGRATION = HERE / "integration.toml"    # every repo lands on an integration branch
LOCAL = HERE / "local.toml"                # any other space: a local merge

# The key lists ARE the format: the check reads them, and the proposal brief's short form is
# written from them (`flowcards.format_text`), so neither can drift from the other.
TOP_KEYS = ("name", "description", "branch", "move")
BRANCH_KEYS = ("id", "label", "kind")
MOVE_REQUIRED = ("id", "label", "from", "to", "by")
MOVE_OPTIONAL = ("step", "stages", "group", "prompt", "pushes", "opens", "bases", "about")
MOVE_KEYS = (*MOVE_REQUIRED, *MOVE_OPTIONAL)
# `work`: a branch a move makes for the card's work (a cherry-pick onto the trunk, c-641)
BRANCH_KINDS = ("card", "work", "base", "integration", "environment", "trunk")
# The board draws a name up to 48 characters and a label up to 240 (`app/ui.board.js`): a
# checked flow must always draw.
ID_MAX, LABEL_MAX = 48, 120
# `you`: the owner's own move, the only kind that acts. `him` is its older spelling (c-640),
# kept so a pack's file and an adopted one still load; a parsed move always says `you`.
YOU = "you"
WHO = ("house", YOU, "colleague", "keel")
ALIASES = {"him": YOU}
# The steps a `keel` or `house` move may name: what Keel or the house already does.
STEPS = {"keel": ("publish", "ship", "land", "deploy"), "house": ("pr", "push", "rebase")}
STAGES = ("assigned", "planning", "building", "review", "shipping", "done")
ID = re.compile(r"^[a-z][a-z0-9-]*$")
# What a move of yours may name in its prompt, filled in from the card at the tap.
FIELDS = ("id", "base", "branch", "title", "target")
FIELD = re.compile(r"\{([a-z_]+)\}")
SOURCES = ("space", "pack", "keel")
# Keel's own flow for a held space (`held`): no move is drawn. The reason is the state's
# `held`, a whole sentence the panel prints in a line of its own for a flow of any source, so
# the description says only what is true of every case and does not give it a second time.
HELD = "Shipyard draws no flow for this space yet."


class FlowError(Exception):
    """A flow file that is wrong; the message says which key and why."""


@dataclass(frozen=True)
class Branch:
    id: str
    label: str
    kind: str


@dataclass(frozen=True)
class Move:
    id: str
    label: str
    source: str             # `from`, a branch id
    target: str             # `to`, a branch id
    by: str
    step: str = ""
    stages: tuple[str, ...] = ()
    group: str = ""
    prompt: str = ""
    pushes: tuple[str, ...] = ()
    opens: tuple[str, ...] = ()     # branch ids it may open a change to (c-641)
    bases: tuple[str, ...] = ()     # offered only on a card whose base is one of these (c-641)
    about: str = ""         # one line for the board and the button's tip

    @property
    def yours(self) -> bool:
        """A move the owner makes: the only kind that is a button and acts."""
        return self.by == YOU


@dataclass(frozen=True)
class Flow:
    name: str
    description: str
    branches: tuple[Branch, ...]
    moves: tuple[Move, ...]
    source: str = "keel"            # space | pack | keel
    path: Path | None = None
    warnings: tuple[str, ...] = field(default=())

    def move(self, move_id: str) -> Move | None:
        return next((one for one in self.moves if one.id == move_id), None)


# ----- reading and checking -----

# Flows read, by path and the file's stamp (mtime, size): a state build asks for each space's
# flow, and a file that has not changed is not parsed again (c-640 review).
_loaded: dict[str, tuple[tuple, "Flow"]] = {}


def read(path: Path) -> str:
    """The file's text, or `FlowError`: a missing file, or one that is not UTF-8."""
    try:
        return Path(path).read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as error:
        raise FlowError(f"{path}: {error}") from None


def load(path: Path, source: str = "keel") -> Flow:
    path = Path(path)
    try:
        stat = path.stat()
        stamp = (stat.st_mtime_ns, stat.st_size, source)
    except OSError as error:
        raise FlowError(f"{path}: {error}") from None
    held = _loaded.get(str(path))
    if held and held[0] == stamp:
        return held[1]
    found = parse_text(read(path), str(path), source, path)
    _loaded[str(path)] = (stamp, found)
    return found


def parse_text(text: str, where: str, source: str = "keel", path: Path | None = None) -> Flow:
    try:
        data = tomllib.loads(text)
    except tomllib.TOMLDecodeError as error:
        raise FlowError(f"{where}: {error}") from None
    return parse(data, where, source, path)


def parse(data: dict, where: str, source: str = "keel", path: Path | None = None) -> Flow:
    """A checked flow, or `FlowError` naming the first thing wrong."""
    stray_keys(data, TOP_KEYS, where)
    for key in ("name", "description"):
        if not isinstance(data.get(key), str) or not data[key].strip():
            raise FlowError(f"{where}: `{key}` must be a non-empty string")
    branches = tuple(branch_of(entry, where) for entry in rows(data, "branch", where))
    ids = [branch.id for branch in branches]
    twice = sorted({one for one in ids if ids.count(one) > 1})
    if twice:
        raise FlowError(f"{where}: branch id {', '.join(twice)} is used twice")
    cards = [branch.id for branch in branches if branch.kind == "card"]
    if len(cards) != 1:
        raise FlowError(f"{where}: exactly one branch has kind \"card\" (the card's own, where a "
                        f"flow starts); this has {len(cards)}. A branch a move makes is kind \"work\"")
    moves = tuple(move_of(entry, where, set(ids)) for entry in rows(data, "move", where))
    move_ids = [move.id for move in moves]
    twice = sorted({one for one in move_ids if move_ids.count(one) > 1})
    if twice:
        raise FlowError(f"{where}: move id {', '.join(twice)} is used twice")
    return Flow(name=data["name"].strip(), description=data["description"].strip(),
                branches=branches, moves=moves, source=source, path=path)


def stray_keys(entry: dict, keys: tuple, what: str) -> None:
    unknown = sorted(set(entry) - set(keys))
    if unknown:
        raise FlowError(f"{what}: no key {', '.join(unknown)}; the keys are {', '.join(sorted(keys))}")


def rows(data: dict, key: str, where: str) -> list[dict]:
    value = data.get(key, [])
    if not isinstance(value, list) or not all(isinstance(item, dict) for item in value):
        raise FlowError(f"{where}: [[{key}]] must be a list of tables")
    return value


def text(entry: dict, key: str, what: str, required: bool = True) -> str:
    value = entry.get(key, "")
    if not isinstance(value, str) or (required and not value.strip()):
        raise FlowError(f"{what}: `{key}` must be a non-empty string")
    return value.strip()


def branch_of(entry: dict, where: str) -> Branch:
    what = f"{where} [[branch]] {entry.get('id', '?')}"
    stray_keys(entry, BRANCH_KEYS, what)
    branch_id = text(entry, "id", what)
    capped(entry, what)
    if not ID.match(branch_id):
        raise FlowError(f"{what}: id {branch_id!r} is lower case letters, digits and -")
    kind = text(entry, "kind", what)
    if kind not in BRANCH_KINDS:
        raise FlowError(f"{what}: kind {kind!r} is one of {', '.join(BRANCH_KINDS)}")
    return Branch(branch_id, text(entry, "label", what), kind)


def move_of(entry: dict, where: str, branches: set[str]) -> Move:
    what = f"{where} [[move]] {entry.get('id', '?')}"
    stray_keys(entry, MOVE_KEYS, what)
    move_id = text(entry, "id", what)
    capped(entry, what)
    if not ID.match(move_id):
        raise FlowError(f"{what}: id {move_id!r} is lower case letters, digits and -")
    ends = {key: text(entry, key, what) for key in ("from", "to")}
    stray = sorted(end for end in ends.values() if end not in branches)
    if stray:
        raise FlowError(f"{what}: names branch {', '.join(stray)}, which no [[branch]] declares")
    by = text(entry, "by", what)
    by = ALIASES.get(by, by)
    if by not in WHO:
        raise FlowError(f"{what}: by {by!r} is one of {', '.join(WHO)}")
    step = step_of(entry, what, by)
    stages = tuple(list_of(entry, "stages", what))
    wrong = sorted(set(stages) - set(STAGES))
    if wrong:
        raise FlowError(f"{what}: stages {', '.join(wrong)} are not stages ({', '.join(STAGES)})")
    pushes, opens = (declared(entry, key, what, branches) for key in ("pushes", "opens"))
    bases = tuple(list_of(entry, "bases", what))
    prompt = text(entry, "prompt", what, required=False)
    if by == YOU:
        if not prompt:
            raise FlowError(f"{what}: a move you make says what the house does: `prompt`")
        if not stages:
            raise FlowError(f"{what}: a move you make says when it is offered: `stages`")
    elif prompt or pushes or opens:
        raise FlowError(f"{what}: only a move you make (by = \"{YOU}\") has a prompt, pushes or opens")
    unknown_fields = sorted(set(FIELD.findall(prompt)) - set(FIELDS) - set(terms.KEYS))
    if unknown_fields:
        raise FlowError(f"{what}: the prompt names {{{', '.join(unknown_fields)}}}; it may name "
                        f"{', '.join('{' + one + '}' for one in FIELDS)}")
    return Move(id=move_id, label=text(entry, "label", what), source=ends["from"], target=ends["to"],
                by=by, step=step, stages=stages, group=text(entry, "group", what, required=False),
                prompt=prompt, pushes=pushes, opens=opens, bases=bases,
                about=text(entry, "about", what, required=False))


def step_of(entry: dict, what: str, by: str) -> str:
    """The move's `step`: one of `STEPS` for a keel or house move, required for keel, and
    none for any other."""
    step = text(entry, "step", what, required=False)
    if step and by not in STEPS:
        raise FlowError(f"{what}: only a keel or house move names a step; a move by {by} has none")
    if by in STEPS and step and step not in STEPS[by]:
        raise FlowError(f"{what}: step {step!r} is one of {', '.join(STEPS[by])} for by = {by}")
    if by == "keel" and not step:
        raise FlowError(f"{what}: a keel move names its step ({', '.join(STEPS['keel'])})")
    return step


def declared(entry: dict, key: str, what: str, branches: set[str]) -> tuple[str, ...]:
    """`pushes` or `opens`: a list of declared branch ids."""
    named = tuple(list_of(entry, key, what))
    stray = sorted(set(named) - branches)
    if stray:
        raise FlowError(f"{what}: {key} {', '.join(stray)}, which no [[branch]] declares")
    return named


def capped(entry: dict, what: str) -> None:
    """An id within 48 characters and a label within 120, so the board draws every one."""
    if isinstance(entry.get("id"), str) and len(entry["id"]) > ID_MAX:
        raise FlowError(f"{what}: id is over {ID_MAX} characters")
    if isinstance(entry.get("label"), str) and len(entry["label"]) > LABEL_MAX:
        raise FlowError(f"{what}: label is over {LABEL_MAX} characters")


def list_of(entry: dict, key: str, what: str) -> list[str]:
    value = entry.get(key, [])
    if not isinstance(value, list) or not all(isinstance(item, str) and item for item in value):
        raise FlowError(f"{what}: `{key}` must be a list of strings")
    return value


# ----- which flow a space has -----

def space_file(cfg, space: str) -> Path | None:
    """`<install>/spaces/<space>/flow.toml`, where the space's own flow lives; None off an
    install (a checkout's config has no space directories)."""
    home = getattr(cfg, "install_home", None)
    return repolayout.space_dir(home, space) / FILE if home is not None else None


def pack_file(space) -> Path | None:
    adapter_dir = getattr(space, "adapter_dir", None)
    return Path(adapter_dir) / FILE if adapter_dir is not None else None


def held(cfg, space) -> str | None:
    """Why Keel draws no flow for this space, as one whole sentence true of its case, or
    None. Three cases, all of a space WITH a pack or an adapter:
    - its pack declares no code host: `adapters.publish` REFUSES Approve of a repo card
      (`readiness.refusal`, whose words these carry), and nothing is merged locally either;
    - an older adapter (no `pack.toml`, so it declares nothing and is not refused) has no
      `publish` verb: Approve runs it and FAILS on the missing executable;
    - an older adapter has `publish` and no `ship`: a card is approved and published, and
      goes to shipping on the publish answer alone, where Keel cannot watch it (`ship` is
      the watcher's verb: poll, reap, sync).
    The panel prints the sentence as it is, and the check says it too."""
    path = getattr(space, "adapter_dir", None)
    if path is None:
        return None
    from keel import readiness      # noqa: PLC0415 - readiness reads the config this module reads
    why = readiness.refusal(cfg, space, "codehost")
    if why:
        return f"A repo card cannot be approved in this space until a code host is set up ({why})."
    if (Path(path) / packs.PACK_FILE).is_file():
        return None
    name = getattr(space, "adapter", None) or Path(path).name
    if not packs.executable(Path(path), "publish"):
        return f"Approve of a repo card fails in this space: the {name} adapter has no publish verb."
    if not packs.executable(Path(path), "ship"):
        return (f"A card can be approved and published in this space, but Shipyard cannot watch it at "
                f"shipping: the {name} adapter has no ship verb. So Shipyard draws no flow for it.")
    return None


def no_codehost(cfg, space) -> bool:
    """Whether `held`'s reason is its first case: the space's pack declares no code host."""
    from keel import readiness      # noqa: PLC0415 - readiness reads the config this module reads
    if getattr(space, "adapter_dir", None) is None:
        return False
    # r2.F2: a pack that does not load declares nothing, and is not this case
    pack, _ = readiness.declared(space)
    return pack is not None and "codehost" not in pack.capabilities


def hosted(cfg, space) -> bool:
    """Whether a card's Approve publishes through the space's pack and the card then waits
    at shipping: the space has a pack or an adapter, and `held` has nothing against it.
    `held` is the ONE predicate; this is its opposite for a space with a pack, and
    `default_of`, `of` and the check (`keel/flowcheck.py`) read it (c-664 review)."""
    return getattr(space, "adapter_dir", None) is not None and held(cfg, space) is None


def landing(cfg, space) -> dict[str, str]:
    """`{repo: branch}` for each of the space's repos that lands on an `[integration]`
    branch (`Config.integration_of`, which is never for a space with a pack)."""
    found = {key: cfg.integration_of(space.name, key) for key in getattr(space, "repos", {}) or {}}
    return {key: branch for key, branch in found.items() if branch}


def default_of(cfg, space) -> Path:
    """Keel's own for this space (c-664): the change flow only when its pack reaches a code
    host; the integration flow when every repo of it lands on an `[integration]` branch;
    else the local merge (`drawn` names the landing branch of a repo that has one; `of`
    takes its move out for a held space, `held`)."""
    if hosted(cfg, space):
        return GENERAL
    lands = landing(cfg, space)
    return INTEGRATION if lands and len(lands) == len(getattr(space, "repos", {}) or {}) else LOCAL


def of(cfg, space) -> Flow:
    """The space's flow, in the space's words: its own file, then its pack's, then Keel's. A
    file that does not load is skipped with its reason in `warnings`, so the deck still
    draws a flow."""
    said = []
    for source, path in (("space", space_file(cfg, space.name)), ("pack", pack_file(space))):
        if path is None or not path.is_file():
            continue
        try:
            found = load(path, source)
        except FlowError as error:
            said.append(f"[spaces.{space.name}] flow: {error}; the next flow is used")
            continue
        return worded(dataclasses.replace(found, warnings=tuple(said)), terms.of(cfg, space))
    found = dataclasses.replace(load(default_of(cfg, space), "keel"), warnings=tuple(said))
    why = held(cfg, space)
    if why:
        found = dataclasses.replace(found, description=HELD, moves=())
    return worded(found, terms.of(cfg, space))


def worded(found: Flow, t) -> Flow:
    """The flow with the space's words filled into everything a person or a house reads
    (`{change}`, `{Change}`, any of `[terms]`); a field that is not a term, `{base}` say,
    stays as written."""
    if t is None or not any("{" in one for one in texts(found)):
        return found
    say = lambda words: terms.say(t, words)      # noqa: E731
    return dataclasses.replace(
        found, name=say(found.name), description=say(found.description),
        branches=tuple(dataclasses.replace(one, label=say(one.label)) for one in found.branches),
        moves=tuple(dataclasses.replace(one, label=say(one.label), group=say(one.group),
                                        about=say(one.about), prompt=say(one.prompt))
                    for one in found.moves))


def texts(found: Flow) -> list[str]:
    return [found.name, found.description, *(one.label for one in found.branches),
            *(part for one in found.moves for part in (one.label, one.group, one.about, one.prompt))]


def public(found: Flow) -> dict:
    """A flow as the deck draws it. The prompt stays on the server."""
    return {"name": found.name, "description": found.description, "source": found.source,
            "branches": [dict(one.__dict__) for one in found.branches],
            "moves": [{"id": one.id, "label": one.label, "from": one.source, "to": one.target,
                       "by": one.by, "step": one.step, "stages": list(one.stages),
                       "group": one.group, "pushes": list(one.pushes), "opens": list(one.opens),
                       "bases": list(one.bases), "about": one.about}
                      for one in found.moves],
            "warnings": list(found.warnings)}


def drawn(cfg, space) -> dict:
    """What `/api/state` carries for a space's flow: the flow in the space's words, Keel's
    own with its landing branches by name, and `handling`, how the space treats review at
    shipping (which no flow says): whether Keel publishes and watches a card here at
    shipping (`hosted`, and its pack has the `ship` verb), and the two automatic-handling
    settings (c-664). `held` is why Keel draws no flow for this space, or None; `landing`
    is each repo's landing branch by name, whatever the flow's source."""
    found = of(cfg, space)
    out = public(found)
    lands = landing(cfg, space)
    if found.source == "keel":
        name_landing(out, lands)
    # `{repo: branch}` for each repo that lands on an integration branch: the deck names a
    # card's own landing branch from it (`K.landsOn`, c-665) and never guesses one
    out["landing"] = lands
    path = getattr(space, "adapter_dir", None)
    out["held"] = held(cfg, space)
    # c-758 r1.F8: which of `held`'s cases it is, so the page gives advice that fits: only a
    # connection with no code host is helped by choosing another or by this computer
    out["held_codehost"] = bool(out["held"]) and no_codehost(cfg, space)
    # Keel watches a card at shipping only where Approve publishes (`hosted`) and the pack has `ship`
    out["handling"] = {"shipping": hosted(cfg, space) and packs.executable(Path(path), "ship"),
                       "comments": bool(getattr(space, "ship_auto_comments", False)),
                       "checks": bool(getattr(space, "ship_auto_checks", False))}
    return out


def name_landing(out: dict, lands: dict[str, str]) -> None:
    """Keel's own flow, drawn with the NAME of each landing branch (`lands`, `{repo:
    branch}`): the integration flow's branch is named, and the local merge of a space where
    only some repos land on one says which, so the drawing is true of every repo. The
    drawing only: the flow the fence reads keeps its labels in words."""
    if not lands:
        return
    repos = {branch: ", ".join(sorted(key for key in lands if lands[key] == branch))
             for branch in sorted(set(lands.values()))}
    wide = [one for one in out["branches"] if one["kind"] == "integration"]
    for one in wide:
        one["label"] = (next(iter(repos)) if len(repos) == 1
                        else ", ".join(f"{branch} ({keys})" for branch, keys in repos.items()))
    if wide:
        return
    where = ", ".join(f"{branch} for {keys}" for branch, keys in repos.items())
    for one in out["branches"]:
        if one["kind"] == "base":
            one["label"] = f"{one['label']}, or {where}"
    out["description"] += (f" A card in {', '.join(sorted(lands))} lands on its landing branch "
                           f"instead ({where}), and your deploy takes that live.")


# ----- a move you make, on a card -----

def offered(found: Flow, card: dict, cfg=None) -> list[Move]:
    """The moves the owner may make on this card now: their moves at the card's stage, and
    for a move that names `bases`, on a card whose base is one of them."""
    return [one for one in found.moves if one.yours and card.get("stage") in one.stages
            and based(one, card, cfg)]


def based(move: Move, card: dict, cfg=None) -> bool:
    """A move with no `bases` fits any card; one with them, a card whose `options.base` is
    one (the deck reads the same option, `K.flowMoves`). A stacked card's moment on its
    parent's branch is not read here (c-718 r1.F7, decided): `bases` names the team bases a
    move fits (an early merge for a card that lands on the staging base), and a stacked card
    lands on its own base once its parent has, so its own option is the one that fits."""
    if not move.bases:
        return True
    if cfg is None:
        return str((card.get("options") or {}).get("base") or "") in move.bases
    from keel import merging      # noqa: PLC0415 - merging reads the config this module is read by
    # c-732 r2.F1: by the integration rule, so a card on an integrated repo fits no base's move
    return str(merging.card_base(cfg, card) or "") in move.bases


def prompt_for(move: Move, card: dict, base: str = "", branch: str = "", target: str = "") -> str:
    """The move's prompt with the card's facts filled in; a field it cannot fill stays as
    written, so the house sees what it was not told rather than an empty word."""
    facts = {"id": card.get("id", ""), "title": card.get("title", ""), "base": base,
             "branch": branch, "target": target}

    def fill(match):
        return facts.get(match.group(1)) or match.group(0)
    return FIELD.sub(fill, move.prompt)


def check_file(path: Path, cfg=None, space=None) -> Flow:
    """`keel flow check <file> [--space <name>]`: the file loaded, and checked for what
    cannot run (`keel/flowcheck.py`), with the space when one is named; or `FlowError`."""
    from keel import flowcheck      # noqa: PLC0415 - flowcheck builds on this module
    found = load(Path(path), "space")
    flowcheck.check(found, cfg, space)
    return found


# ----- `keel flow check <file> [--space <name>]` and `keel flow show [space]` -----

def main(argv: list[str]) -> int:
    import argparse     # noqa: PLC0415 - only the verb needs it
    import json         # noqa: PLC0415
    import sys          # noqa: PLC0415
    parser = argparse.ArgumentParser(prog="keel flow", description="a space's flow (docs/atlas/64-flows.md)")
    sub = parser.add_subparsers(dest="op", required=True)
    check = sub.add_parser("check", help="check a flow file")
    check.add_argument("file")
    check.add_argument("--space", help="the space it is for: also checks what that space can run")
    sub.add_parser("show", help="the flow each space has, or one").add_argument("space", nargs="?")
    args = parser.parse_args(argv)
    from keel import config as config_module    # noqa: PLC0415
    cfg = config_module.load(ensure=False) if args.op == "show" or args.space else None
    names = [args.space] if args.space else list(cfg.spaces) if cfg else []
    unknown = [name for name in names if name not in cfg.spaces]
    if unknown:
        print(f"keel flow {args.op}: no space {', '.join(unknown)}", file=sys.stderr)
        return 1
    if args.op == "show":
        print(json.dumps({name: drawn(cfg, cfg.spaces[name]) for name in names}, indent=2))
        return 0
    try:
        found = check_file(Path(args.file), cfg, cfg.spaces[args.space] if args.space else None)
    except FlowError as error:
        print(f"keel flow check: {error}", file=sys.stderr)
        return 1
    print(said_ok(found, args.space))
    return 0


def said_ok(found: Flow, space: str | None) -> str:
    """The check's last line: what passed, and what a flow is and is not."""
    yours = [one.label for one in found.moves if one.yours]
    buttons = (f"{len(yours)} of them yours, each a button on a card ({', '.join(yours)})" if yours
               else "none of them a move of your own, so it adds no button (Approve and Ship stay the card's own)")
    scope = f"for the {space} space" if space else "shape only: name the space with --space to check what it can run"
    return (f"ok: {found.name}, {len(found.branches)} branches, {len(found.moves)} moves, {buttons}. "
            f"Every other move is a picture of what the space's pack and Shipyard already do. Checked {scope}.")
