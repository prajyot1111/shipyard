"""Packs on the Setup view (c-618): each pack with its checks, Turn on, and Turn off.

`pack_on` adds the one space a pack's `config.example.toml` shows, under the name the person
gives, to the install's config: `pack` set, `config_dir` the install's own Claude dir, and
the example's `host` and `repos` left out, so the space is served here and its repos are
cloned one at a time after (docs/atlas/62-packs.md).

A space that already exists and names no pack is adopted instead (c-632, decision
space-pack: existing): `pack` is set in its table, and the example's keys are merged in
only where the space has none, so the first run can add a plain space and pick its
integration after. A space that already names a pack is refused.

`pack_off` (c-688) takes back what Turn on wrote: the `pack` line, each key the pack's own
example gives whose value in the space's table is still the example's, and the "Turned on"
note over the table. The space, its repos, its `config_dir` and every key that differs stay,
so the next Turn on, of this pack or another, starts from a plain space. It is refused while
the space has open cards.

A pack that says `demo_only` (the sandbox, whose verbs refuse outside a demo sandbox) is not
listed on an install unless a space there is already on it, so it is never offered where it
cannot run; turned on by name it still serves, as the tests and scratch installs use it.
"""

from __future__ import annotations

import os
import re
import shlex
import tomllib
from pathlib import Path

from keel import builder, configedit, packclones, packs
from keel.config import Config, repo_root
from keel.setupconfig import SetupError, claude_dir, edit, install_of, installed, name_of, space_of

# What a pack's example space carries that a new space here never takes.
PACK_DROPS = ("host", "repos")
# What an adopted space keeps of its own whatever the example says: it is already served here.
ADOPT_DROPS = PACK_DROPS + ("pack", "adapter", "config_dir")


def pack_env(cfg: Config, pack: packs.Pack) -> dict:
    """The env a pack's checks run with: the space on it, if one is, else the install's."""
    space = next((s for s in cfg.spaces.values() if s.adapter == pack.name and s.adapter_dir), None)
    config_dir = space.config_dir if space else claude_dir(cfg)
    repos = space.repos.values() if space else ()
    return {"KEEL_SPACE_CONFIG_DIR": str(config_dir),
            "KEEL_STACK_GUARD_HOOK": str(cfg.stack_guard_hook or ""),
            "KEEL_SPACE_REPOS": os.pathsep.join(str(path) for path in repos),
            # c-735: a pack on the kit imports it through KEEL_HOME, wherever the pack lives
            "KEEL_HOME": str(repo_root())}


def pack_row(cfg: Config, pack: packs.Pack) -> dict:
    return {"name": pack.name, "version": pack.version, "description": pack.description,
            "spaces": sorted(name for name, s in cfg.spaces.items() if s.adapter == pack.name),
            "checks": packs.checks(pack, pack_env(cfg, pack)),
            # the page words Turn off's confirm by it: such a pack leaves this list (c-688)
            "demo_only": pack.demo_only,
            # what it provides (c-730): Where finished work goes asks about review requests
            # only under a pack that can bring them
            "capabilities": sorted(pack.capabilities),
            # c-740 r1.F1: a pack with a repo of its own, and whether Bosun builds it there yet
            "own_repo": own_repo(cfg, pack),
            # c-758: where it was found, for a connection in the install's own packs folder (a
            # shared one cloned there, one Bosun drafted); None for one Shipyard ships
            "folder": install_folder(cfg, pack),
            # the first run's Set up your repos with Bosun step lists them as already read by
            # the pack's houses (c-632, decision pack-rules: list); nothing is copied
            "rules": [str(rule.relative_to(pack.path)) for rule in pack.rules]}


def install_folder(cfg: Config, pack: packs.Pack) -> str | None:
    """The pack's folder when it lies in the install's own packs folder, else None (c-758):
    Where finished work goes lists such a connection first, marked as found there."""
    home = getattr(cfg, "install_home", None)
    if not home:
        return None
    inside = Path(pack.path).resolve().parent == (Path(home) / packs.PACKS).resolve()
    return str(pack.path) if inside else None


def own_repo(cfg: Config, pack: packs.Pack) -> dict | None:
    """`{key, built}` for a pack that is its own clone in the install's packs folder: the
    repo key Bosun builds it under (`pack-<name>`), and whether that is set up, listed as a
    personal repo at the clone and named in `[builder] repos`. None for any other pack."""
    home = getattr(cfg, "install_home", None)
    key = packclones.KEY + pack.name
    path = packclones.own(home).get(key) if home else None
    if path is None or not builder.same(path, pack.path):
        return None
    return {"key": key, "built": own_repo_built(cfg, key, path)}


def build_pack(cfg: Config, name: str) -> dict:
    """The tap "Let Bosun build this pack" (c-740 r1.F1, `setup.pack.build` `{pack}`): the
    cloned pack listed as the personal repo `pack-<name>` and named in `[builder] repos`, by
    the path init uses (`builder.list_own`, after `builder.unlist_gone`), and Bosun's clone of
    it made now where it is the install's builder (`builder.ensure_clones`, as its Start
    does). The tap is the user's word, so a pack taken out of `[builder] repos` goes back in.
    Refused for a pack with no repo of its own, and for a key one of the user's repos has."""
    home = install_of(cfg)
    if not builder.in_app(cfg):     # r2.F3: the verb's own refusal, not only the page's
        raise SetupError("Bosun is not this install's builder (bosun_builder is off), so there is no one "
                         "to build this pack in its own repo; nothing was listed")
    key = packclones.KEY + name
    path = packclones.own(home).get(key)
    if path is None:
        raise SetupError(f"{name} has no repo of its own in {home / packs.PACKS}: only a pack cloned "
                         f"into its own folder there, named for the pack, is built in its own repo")
    personal = cfg.spaces.get("personal")
    if personal is None:
        raise SetupError("there is no personal space to list it in")
    if key in personal.repos and not builder.same(personal.repos[key], path):
        raise SetupError(f"one of your repos is already called {key} ({personal.repos[key]}); "
                         f"it keeps the name, so Bosun cannot build this pack under it")

    def change(text: str) -> str:
        text = builder.list_own(builder.unlist_gone(text, cfg, home), cfg, key, path)
        built = builder.built_in(text)       # r2.F1: the list as the text has it after both
        return text if key in built else configedit.set_entry(text, "builder", "repos", built + [key])
    done = edit(cfg, change) if not (own_repo_built(cfg, key, path)) else {"config": str(cfg.source)}
    from keel import config as config_module     # noqa: PLC0415 - as pack_on reads it back
    made = builder.ensure_clones(config_module.load(cfg.source, ensure=False))
    return {**done, "pack": name, "repo": key, "cloned": made,
            "note": f"Bosun builds {name} in its own repo now, as {key}"}


def own_repo_built(cfg: Config, key: str, path) -> bool:
    personal = cfg.spaces.get("personal")
    return (personal is not None and key in personal.repos and builder.same(personal.repos[key], path)
            and key in builder.repos(cfg))


def offered(cfg: Config, pack: packs.Pack) -> bool:
    """Whether Setup lists `pack`: always, but for a `demo_only` one on an install, which is
    listed only while a space is on it (so it can be turned off)."""
    if not pack.demo_only or installed(cfg) is None:
        return True
    return any(space.adapter == pack.name for space in cfg.spaces.values())


def rows(cfg: Config) -> tuple[list[dict], str | None]:
    """`(rows, problem)`. A pack that does not load empties the list and is the problem. A
    folder that is not called what its pack is (c-740: a shared pack cloned under its repo's
    name) is one problem line, and every other pack still lists."""
    found = listing(cfg)
    return found["rows"], found["problem"]


def listing(cfg: Config) -> dict:
    """`{rows, problem, said, install}` (c-758 r1.F7, F13): the rows and the problem as `rows`
    gives them, in the Setup view's own word (pack); `said`, the same problem lines in the
    first run's word (connection), so each page keeps one word; and `install`, true when a
    problem line is about a folder of the install's own packs folder (a misnamed folder
    there, one the packs repo still tracks). A pack that does not load says no folder of its
    own, so `install` is false for it and the page labels it neutrally."""
    misnamed: list[packs.Misnamed] = []
    try:
        found = [pack_row(cfg, pack) for pack in packs.available(cfg.root, misnamed) if offered(cfg, pack)]
    except packs.PackError as error:
        return {"rows": [], "problem": str(error), "said": str(error), "install": False}
    home = getattr(cfg, "install_home", None)
    folder = (Path(home) / packs.PACKS).resolve() if home else None
    tracked = tracked_names(cfg)     # one reading of the packs repo, said in each page's word

    def joined(noun: str) -> str | None:
        lines = [wrong_folder(error, noun) for error in misnamed] + still_tracked(cfg, noun, tracked)
        return "\n".join(one_line(line) for line in lines) or None
    inside = bool(tracked) or any(folder is not None and Path(error.path).resolve().parent == folder
                                  for error in misnamed)
    return {"rows": found, "problem": joined("pack"), "said": joined("connection"), "install": inside}


def one_line(text: str) -> str:
    """`text` as one line whatever a folder's name carries (r1.F8): the page splits the
    problems on line breaks, so none may come from a name."""
    return " ".join(text.splitlines())


def packs_folder(cfg: Config) -> str | None:
    """The install's packs folder as a shell reads it (r1.F8), for the line the page gives to
    copy; None off an install."""
    home = getattr(cfg, "install_home", None)
    return shlex.quote(str(home / packs.PACKS)) if home else None


def tracked_names(cfg: Config) -> list[str]:
    """The folders of the install's packs folder that have a repo of their own while the
    packs repo still tracks them (`packclones.tracked`, one `git ls-files`); none off an install."""
    home = getattr(cfg, "install_home", None)
    return packclones.tracked(home / packs.PACKS) if home else []


def still_tracked(cfg: Config, noun: str = "pack", names: list[str] | None = None) -> list[str]:
    """A line for each folder of the install's packs folder that has a repo of its own while
    the packs repo still tracks it (r1.F3): it is not a clone until the command is run.
    `noun` is the page's word for what the folder holds (r1.F7). `names` is `tracked_names`
    when the caller has read it already (`listing` says the lines in two words from one read)."""
    home = getattr(cfg, "install_home", None)
    if not home:
        return []
    folder = home / packs.PACKS
    return [f"The packs repo still tracks {name}, so {folder / name} is not read as a {noun} with a repo "
            f"of its own: run `git -C {shlex.quote(str(folder))} rm -r --cached {shlex.quote(name)}`, "
            f"commit there, then Look again." for name in (tracked_names(cfg) if names is None else names)]


def wrong_folder(error: packs.Misnamed, noun: str = "pack") -> str:
    """What the folder is, and what it should be called. A name that is no pack name (r1.F8:
    it is whatever the file says) is never shown: the line says what a pack name is. `noun`
    is the page's word (r1.F7): pack on the Setup view, connection on the first run."""
    if not packs.NAME.match(error.name):
        return (f"The folder {error.path} holds a {noun} whose name is not a {noun} name (lower case letters, "
                f"digits, - and _): give it one in its {packs.PACK_FILE}, call the folder the same, then "
                f"Look again.")
    return (f"The folder {error.path} holds the {noun} {error.name}: rename it to "
            f"{error.path.parent / error.name}, then Look again.")


def example_space(pack: packs.Pack) -> dict:
    """The one space the pack's `config.example.toml` shows."""
    example = pack.path / "config.example.toml"
    try:
        spaces = tomllib.loads(example.read_text()).get("spaces", {})
    except (OSError, tomllib.TOMLDecodeError) as error:
        raise SetupError(f"{pack.name} has no readable config.example.toml ({error})") from None
    if len(spaces) != 1:
        raise SetupError(f"{example} shows {len(spaces)} spaces; Setup turns on a pack that shows one")
    return dict(next(iter(spaces.values())))


def pack_space(cfg: Config, pack: str, space: str, how: str = "in the deck's Setup view"):
    """`(change, pack name)`: the text change that adds `space` on `pack`, served on this
    machine with no repos yet. `shipyard import` makes the same change (keel/importconfig.py)."""
    name_of(space, "space name")
    if space in cfg.spaces:
        raise SetupError(f"there is already a space {space!r}")
    try:
        found = packs.find(pack, cfg.root)
    except packs.PackError as error:
        raise SetupError(str(error)) from None
    table = {key: value for key, value in example_space(found).items() if key not in PACK_DROPS}
    table["pack"] = found.name
    table["config_dir"] = str(claude_dir(cfg))
    note = f"Turned on {how}: the {found.name} pack (docs/atlas/62-packs.md)."
    return (lambda text: configedit.append_table(text, f"spaces.{space}", table, note)), found.name


def adopt_space(cfg: Config, pack: str, space: str):
    """`(change, pack name)`: the text change that puts `pack` on the existing `space`, which
    names none; the example's keys are set only where the space's table has none (c-632)."""
    found_space = space_of(cfg, space)
    if found_space.adapter:
        raise SetupError(f"{space} is already on the {found_space.adapter} connection; "
                         f"turn that off first to change it")
    try:
        found = packs.find(pack, cfg.root)
    except packs.PackError as error:
        raise SetupError(str(error)) from None
    merged = {key: value for key, value in example_space(found).items()
              if key not in ADOPT_DROPS and not isinstance(value, dict)}
    table = f"spaces.{space}"

    def change(text: str) -> str:
        own = (tomllib.loads(text).get("spaces") or {}).get(space) or {}
        if "pack" in own or "adapter" in own:
            raise SetupError(f"{space} already names a pack or an adapter in the config")
        for key, value in merged.items():
            if key not in own:
                text = configedit.set_entry(text, table, key, value)
        return configedit.set_entry(text, table, "pack", found.name)
    return change, found.name


def pack_on(cfg: Config, pack: str, space: str) -> dict:
    """`pack` on `space`: a new space served on this machine with no repos yet, or an
    existing space with no pack adopted (c-632)."""
    if space in cfg.spaces:
        change, name = adopt_space(cfg, pack, space)
        done = edit(cfg, change)
        # c-729: the pack pushes for the space now, so its copies may be pushed to again
        from keel import config as config_module, landpush     # noqa: PLC0415 - landpush is heavy
        now = config_module.load(cfg.source, ensure=False)
        for key in now.spaces[space].repos:
            landpush.fence(now, space, key)
        return {**done, "space": space, "pack": name, "adopted": True,
                "note": went_through(space, name)}
    change, name = pack_space(cfg, pack, space)
    return {**edit(cfg, change), "space": space, "pack": name, "note": went_through(space, name)}


def went_through(space: str, name: str) -> str:
    """What Turn on did, as the page says it (c-758)."""
    return f"Work for {space} now goes through {name}."


def open_cards(board, space: str) -> list[str]:
    """The cards of `space` that are not done and not archived, and whose landing a pack
    could change. A tier or flow proposal is not one (c-678: a copied repo leaves a draft
    card for Bosun in personal): it has no repo and no branch, and closes by Adopt."""
    from keel.board import proposals_of      # noqa: PLC0415 - the board imports nothing of this module
    return [card["id"] for card in board.list_cards(space=space, include_archived=False)
            if card.get("stage") != "done" and not proposals_of(card.get("options"))]


def brought(cfg: Config, pack: str) -> dict:
    """What Turn on may have written for `pack` besides the `pack` line: the keys of its
    example space as they read today (`adopt_space` merges the same ones). Empty when the
    pack or its example no longer reads, so only the `pack` line comes off."""
    try:
        example = example_space(packs.find(pack, cfg.root))
    except (packs.PackError, SetupError):
        return {}
    return {key: value for key, value in example.items()
            if key not in ADOPT_DROPS and not isinstance(value, dict)}


def taken(text: str, space: str, key: str) -> str | None:
    """`text` with `key` out of the space's table, or None when it does not come out cleanly
    as one line (a list written over several lines, a quoted key): the result must parse and
    differ from `text` by that key alone."""
    try:
        after = configedit.remove_entry(text, f"spaces.{space}", key)
        wanted, got = tomllib.loads(text), tomllib.loads(after)
    except (configedit.EditError, tomllib.TOMLDecodeError):
        return None
    wanted["spaces"][space].pop(key, None)
    return after if got == wanted else None


def without_note(text: str, table: str, pack: str) -> str:
    """`text` without the line `pack_space` wrote over `[table]` ("Turned on ...: the <pack>
    pack"), when it is the line directly above the header. Any other comment stays."""
    where = configedit.span(text, table)
    lines = text.splitlines()
    above = where[0] - 1 if where else -1
    said = re.compile(rf"^# Turned on .*: the {re.escape(pack)} pack \(docs/atlas/62-packs\.md\)\.$")
    if above < 0 or not said.match(lines[above]):
        return text
    del lines[above]
    return configedit.joined(lines, True)


def pack_off(cfg: Config, board, space: str) -> dict:
    """The pack taken off `space` (c-688), and with it what Turn on wrote: the `pack` line,
    each key the pack's example gives whose value in the space's table still equals the
    example's, and the "Turned on" note directly over the table. `config_dir`, `host`, the
    repos and any key whose value differs are kept. Two limits, since the config does not
    record who wrote a key: a value the user typed that equals the example's goes too, and
    an example edited since Turn on leaves its old keys behind. A key that was rewritten by
    hand so that it is no longer one plain line is left where it is and named in the answer
    (`left`): that never refuses Turn off.

    Refused for a space on no pack, for one that names an older `adapter` or is written
    inline by hand, and while the space has open cards: a card at review there would land
    as a local merge where the pack would have opened its change for review, and its pack
    verbs would stop."""
    found = space_of(cfg, space)
    if not found.adapter:
        raise SetupError(f"{space} is on no connection, so there is none to turn off")
    held = open_cards(board, space)
    if held:
        raise SetupError(f"{space} still has open cards ({', '.join(held)}): with the connection off, a card "
                         f"at review there would be merged on this computer where the connection would have "
                         f"opened its change for review, and its other steps would stop; finish or "
                         f"archive them first")
    name, table = found.adapter, f"spaces.{space}"
    example = brought(cfg, name)

    def change(text: str) -> str:
        own = (tomllib.loads(text).get("spaces") or {}).get(space) or {}
        if "pack" not in own:
            raise SetupError(f"{space} names the {name} adapter by hand in the config, not a connection; "
                             f"take it off there")
        text = configedit.remove_entry(text, table, "pack")
        for key in sorted(key for key, value in example.items() if key in own and own[key] == value):
            less = taken(text, space, key)
            if less is None:
                left.append(key)
            else:
                text = less
        return without_note(text, table, name)
    left: list[str] = []
    done = edit(cfg, change)
    note = f"Work for {space} stays on this computer now; its repos and its own settings are kept"
    return {**done, "space": space, "pack": name, "left": left,
            "note": note + (f"; left in place: {', '.join(left)}" if left else "")}
