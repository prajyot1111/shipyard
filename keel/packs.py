"""Packs: an integration as one directory, on the existing adapter contract (c-617).

A pack is `packs/<name>/`: a `pack.toml` that says what it is and what it provides, the
adapter executables and their modules at its root (one executable per verb, JSON in and
out, the contract the work adapter page states), `rules/` (markdown its brief reads),
`skills/`, a `config.example.toml`, and optionally `drift-terms`, the words only this pack
may say (`make drift`), and `[[setup]]`, its own first-run steps (c-632). The Atlas page
"Packs" is the rules for writing one.

Packs are found under the install's own `packs/` first (the directory of the install's
`config.toml`, which `KEEL_CONFIG` names), then the checkout's `packs/` (c-618). A space names one with `pack = "<name>"`; the older `adapter = "<name>"` under
`adapters_dir` is read exactly as before (`config._space`). This module reads files and
runs a pack's declared checks; it never starts, stops or writes anything.
"""

import os
import re
import subprocess
import tomllib
from dataclasses import dataclass, field
from pathlib import Path

PACKS = "packs"
PACK_FILE = "pack.toml"
NAME = re.compile(r"^[a-z0-9][a-z0-9_-]*$")
DRIFT_TERMS = "drift-terms"
PACKAGE = Path(__file__).resolve().parent.parent
# `repo-command`: a Claude command a repo of the space carries (`.claude/commands/`), checked
# over `KEEL_SPACE_REPOS`, the space's repos joined by the path separator.
KINDS = ("command", "repo-command", "skill", "hook", "secret")
TOP_KEYS = {"name", "version", "description", "adapter", "provides", "space", "requires",
            "capabilities", "terms", "setup", "guard", "demo_only"}
# A pack may read the commands its houses run (c-689): a `guard` executable at its root,
# asked by `bin/keel-house-guard`, and `[guard] tools`, the command words it reads (`gh`).
GUARD_VERB = "guard"
GUARD_KEYS = {"tools"}
# What a `[[requires]]` entry may say about its own fix (c-688), each one line of text: `fix`
# the sentence, `command` the one line the user copies, `done_when` how the user knows it
# worked, `action` a shell line a button may run. The last three belong to a `fix`.
FIX_KEYS = ("fix", "command", "done_when", "action")
PROVIDES_KEYS = {"rules", "skills", "pipeline", "config_example"}
# What a pack may say it provides (c-629), and the executables each claim needs at its root:
# a claim without them refuses the pack, so the deck never shows a feature nothing implements.
# A pack with no [capabilities] provides none of them; nothing is inferred from its verbs.
NEEDS = {"tracker": ("act",), "codehost": ("publish", "publishable", "ship"),
         "reviews": ("review", "providers/reviews"),
         "ci": ("ci",),             # c-642: a card's builds, `ci <id>` (docs/atlas/66-ci.md)
         # c-664: its `pr` takes `--flow <branch> --to <target> --dir <worktree>`, the change
         # a flow move's `opens` asks for; a flow with `opens` is refused where it is not said
         "flow_pr": ("pr",),
         # c-718: its worktree verb cuts a stacked card from its parent's branch, its change
         # aims there, and `ship <id> restack` aims it at the base once the parent lands
         "stacks": ("worktree", "ship"),
         # c-734: its `ship <id> reap` for a REVIEW card removes only the paths it recorded at
         # the cut, with its own teardown; Keel reaps a review tree outside its layout only then
         "review_reap": ("ship",)}
CAPABILITY_KEYS = set(NEEDS) | {"routes"}
# What a pack may call things (c-630): `keel/terms.py` lays these over its neutral defaults.
# Each value is a string as it reads mid-sentence; `ticket_ref` is a ticket's shape, a literal
# prefix and one `<n>` (`options.json`'s `normalise` shape), never a raw regex.
TERM_KEYS = ("ticket", "tickets", "ticket_ref", "change", "changes", "change_short",
             "changes_short", "tracker_name", "codehost_name", "ci_name")
TICKET_REF = re.compile(r"^[A-Za-z0-9_-]+<n>$")
CHECK_SECONDS = 10
# A pack's own first-run steps (c-632): each sits after one of the core steps of
# `keel/firstrun.py` (these are their ids, in order), `integrations` unless it says.
SETUP_KEYS = {"id", "title", "text", "after", "for", "requires"}
SETUP_AFTER = ("choose-builder", "prerequisites", "login", "builder", "repos", "memory", "rules", "integrations",
               "defaults", "browser", "backup", "first-card", "set-up")
# A core step a pack may still name, and where its place is now (c-677: Spaces is part of
# Add your repos).
# Phone and voice is no step either (c-678: it is on the last screen), and a pack that named
# it goes after Your first card, so no pack's step follows You are set up.
SETUP_MOVED = {"spaces": "repos", "phone": "first-card"}


class PackError(Exception):
    """A pack that is missing or whose `pack.toml` is wrong; the message says which."""


class Misnamed(PackError):
    """A folder that is not called what its pack is (c-740): `path` the folder, `name` the
    pack's. A list may set it aside as one problem (`available`); a load still refuses it."""

    def __init__(self, path: Path, name: str, where: str):
        super().__init__(f"{where}: name {name!r} is not its directory's name {path.name!r}")
        self.path, self.name = path, name


@dataclass(frozen=True)
class Requirement:
    """A tool the pack needs on the machine its space runs on, and the shell test for it."""
    name: str
    kind: str
    check: str
    why: str
    serves: tuple[str, ...] = ()            # the capabilities it is checked for (`for`)
    fix: str = ""                           # what to do when the check fails, one sentence
    command: str = ""                       # the one line the user copies to do it
    done_when: str = ""                     # how the user knows it worked
    action: str = ""                        # a shell line a button may run instead


@dataclass(frozen=True)
class SetupStep:
    """One `[[setup]]` entry: a first-run screen the pack brings (c-632). It is done when
    every check it `requires` passes and every capability it is `for` is ready."""
    id: str
    title: str
    text: Path                              # markdown in the pack, shown on the screen
    after: str = "integrations"
    serves: tuple[str, ...] = ()            # `for`: capabilities it sets up
    requires: tuple[str, ...] = ()          # names of the pack's [[requires]] entries


@dataclass(frozen=True)
class Pack:
    name: str
    version: str
    description: str
    path: Path
    spaces: tuple[str, ...] = ()            # the space kinds its adapter serves
    rules: tuple[Path, ...] = ()
    skills: tuple[Path, ...] = ()
    pipeline: Path | None = None            # the space's `pipeline` when it names none
    space: dict = field(default_factory=dict)   # defaults under a `[spaces.<name>]` that names it
    requires: tuple[Requirement, ...] = ()
    capabilities: frozenset = frozenset()   # of NEEDS' keys the pack declares (c-629)
    routes: tuple[str, ...] = ()            # its `providers/<route>` executables, declared
    terms: dict = field(default_factory=dict)   # its `[terms]`, validated (c-630)
    setup: tuple[SetupStep, ...] = ()       # its `[[setup]]` steps, validated (c-632)
    guard_tools: tuple[str, ...] = ()       # `[guard] tools`: it ships a `guard` verb (c-689)
    demo_only: bool = False                 # runs only in a demo; never offered on an install (c-688)


def install_packs(environ=None) -> Path | None:
    """`<install>/packs` when `KEEL_CONFIG` names an install's `config.toml` (one outside
    the code), else None. `environ` is this process's unless one is handed in: behind the
    test fence, the caller's (`tests/installdrift.py`, c-733), whose `HOME` a `~` is then."""
    environ = os.environ if environ is None else environ
    named = environ.get("KEEL_CONFIG")
    if not named:
        return None
    path = expand_home(named, environ).resolve()
    if path.name != "config.toml" or path.parent == PACKAGE:
        return None
    return path.parent / PACKS


def expand_home(named: str, environ) -> Path:
    """`named` with a leading `~` read against `environ`'s `HOME` (c-733 r1.F2: behind the
    test fence this process's own `HOME` is a throwaway); `~user` as the system has it."""
    home = environ.get("HOME")
    if home and (named == "~" or named.startswith("~/")):
        return Path(home) / named[2:]
    return Path(named).expanduser()


def roots(home: Path) -> list[Path]:
    """Where packs are looked for, in order: the install's, then the code's (`home`, then
    this checkout's)."""
    found = []
    for root in (install_packs(), Path(home) / PACKS, PACKAGE / PACKS):
        if root is None:
            continue
        if root.resolve() not in [seen.resolve() for seen in found]:
            found.append(root)
    return found


def find(name: str, home: Path) -> Pack:
    """The pack called `name`, from the first root that has it. A name that is not a plain
    identifier is refused before any path is built from it (`../x` would leave the root)."""
    if not isinstance(name, str) or not NAME.match(name):
        raise PackError(f"{name!r} is not a pack name: lower case letters, digits, - and _")
    for root in roots(home):
        if (root / name / PACK_FILE).is_file():
            return load(root / name)
    raise PackError(f"no pack {name!r} under {' or '.join(str(root) for root in roots(home))}")


def at(path: Path | None) -> Pack | None:
    """The pack whose directory `path` is (an adapter dir, followed through its link), or
    None when it holds no `pack.toml`."""
    if path is None or not (Path(path) / PACK_FILE).is_file():
        return None
    return load(Path(path))


def available(home: Path, misnamed: list | None = None) -> list[Pack]:
    """Every pack the roots hold, the first of a name winning. Handed a `misnamed` list, a
    folder that is not called what its pack is goes there (its `Misnamed`) and the rest still
    list (c-740); with none, it is refused as any pack that does not load."""
    packs: dict[str, Pack] = {}
    for root in roots(home):
        for entry in sorted(root.glob(f"*/{PACK_FILE}")) if root.is_dir() else ():
            try:
                packs.setdefault(entry.parent.name, load(entry.parent))
            except Misnamed as error:
                if misnamed is None:
                    raise
                misnamed.append(error)
    return list(packs.values())


# Loaded packs by directory, with the stamp they were read at (c-628 review r1.F4): one
# /api/state build asks a space's pack a dozen times, every few seconds.
_loaded: dict[Path, tuple[tuple, Pack]] = {}
SUBDIRS = ("rules", "skills", "setup", "providers")


def stamp(path: Path) -> tuple:
    """What a load depends on, cheaply: `pack.toml`'s mtime and size, the mtimes of the
    pack's directory and its subdirectories, which move when a file there is added, removed
    or renamed, and the mode of each file at its root and in `providers/`, where the verbs
    are (a verb that loses its executable bit is a capability a fresh read refuses). An edit
    inside an existing file other than `pack.toml` (a rule's text) is not the pack's shape and
    needs no reload; `forget` drops everything."""
    spec = (path / PACK_FILE).stat()
    dirs = []
    for sub in ("", *SUBDIRS):
        try:
            dirs.append((path / sub).stat().st_mtime_ns)
        except OSError:
            dirs.append(None)
    modes = []
    for where in (path, path / "providers"):
        try:
            modes += sorted((entry.name, entry.stat().st_mode) for entry in os.scandir(where))
        except OSError:
            continue
    return (spec.st_mtime_ns, spec.st_size, *dirs, tuple(modes))


def forget() -> None:
    _loaded.clear()


def load(path: Path) -> Pack:
    """Read and validate `<path>/pack.toml`, kept while its stamp holds."""
    key = Path(path).resolve()
    try:
        now = stamp(key)
    except OSError as error:
        raise PackError(f"{path / PACK_FILE}: {error}") from None
    held = _loaded.get(key)
    if held and held[0] == now and held[1].path == Path(path):
        return held[1]
    pack = read(Path(path))
    _loaded[key] = (now, pack)
    return pack


def read(path: Path) -> Pack:
    """Read and validate `<path>/pack.toml`, every time."""
    try:
        data = tomllib.loads((path / PACK_FILE).read_text())
    except (OSError, tomllib.TOMLDecodeError) as error:
        raise PackError(f"{path / PACK_FILE}: {error}") from None
    where = f"{path.name}/{PACK_FILE}"
    unknown = sorted(set(data) - TOP_KEYS)
    if unknown:
        raise PackError(f"{where} has no key {', '.join(unknown)}; the keys are {', '.join(sorted(TOP_KEYS))}")
    for key in ("name", "version", "description"):
        if not isinstance(data.get(key), str) or not data[key]:
            raise PackError(f"{where}: `{key}` must be a non-empty string")
    if data["name"] != path.name:
        raise Misnamed(path, data["name"], where)
    if not isinstance(data.get("demo_only", False), bool):
        raise PackError(f"{where}: demo_only must be true or false")
    provides = table(data, "provides", where)
    if set(provides) - PROVIDES_KEYS:
        raise PackError(f"{where}: [provides] has no key {', '.join(sorted(set(provides) - PROVIDES_KEYS))}")
    pipeline = provides.get("pipeline")
    if provides.get("config_example"):
        files(path, [provides["config_example"]], f"{where} [provides] config_example")
    declared, routes = capabilities(path, table(data, "capabilities", where), where)
    requires = tuple(requirement(entry, where) for entry in data.get("requires", []))
    for need in requires:
        stray = sorted(set(need.serves) - declared)
        if stray:
            raise PackError(f"{where}: requires {need.name!r} is for {', '.join(stray)}, "
                            f"which [capabilities] does not declare")
    return Pack(
        name=data["name"], version=data["version"], description=data["description"], path=path,
        spaces=tuple(strings(table(data, "adapter", where).get("spaces", []), f"{where} [adapter] spaces")),
        rules=files(path, provides.get("rules", []), f"{where} [provides] rules"),
        skills=files(path, provides.get("skills", []), f"{where} [provides] skills"),
        pipeline=files(path, [pipeline], f"{where} [provides] pipeline")[0] if pipeline else None,
        space=table(data, "space", where),
        requires=requires, capabilities=declared, routes=routes,
        terms=terms_of(table(data, "terms", where), where),
        setup=setup_of(path, data.get("setup", []), declared, requires, where),
        guard_tools=guard_of(path, data, where),
        demo_only=data.get("demo_only", False),
    )


def guard_evidenced(path: Path) -> bool:
    """Whether a pack that failed to load shows it has a guard: a `guard` file at its root,
    executable or not, or a `[guard]` table in its pack.toml, parsed or as written."""
    if (path / GUARD_VERB).exists():
        return True
    try:
        text = (path / PACK_FILE).read_text()
    except OSError:
        return False
    try:
        return "guard" in tomllib.loads(text)
    except tomllib.TOMLDecodeError:
        return re.search(r"^\s*\[guard\]", text, re.MULTILINE) is not None


def guard_of(path: Path, data: dict, where: str) -> tuple[str, ...]:
    """`[guard] tools`: the command words the pack's `guard` verb reads. A pack that says
    it has a guard ships the executable, so a house is never started on a promise."""
    if "guard" not in data:
        return ()
    said = table(data, "guard", where)
    if set(said) - GUARD_KEYS:
        raise PackError(f"{where}: [guard] has no key {', '.join(sorted(set(said) - GUARD_KEYS))}")
    tools = tuple(strings(said.get("tools", []), f"{where} [guard] tools"))
    if not tools or not all(NAME.match(tool) for tool in tools):
        raise PackError(f"{where}: [guard] tools names the commands the guard reads, and each tool is one word")
    if not executable(path, GUARD_VERB):
        raise PackError(f"{where}: declares [guard] but has no executable {GUARD_VERB}")
    return tools


def executable(path: Path, name: str) -> bool:
    return (path / name).is_file() and os.access(path / name, os.X_OK)


def capabilities(path: Path, data: dict, where: str) -> tuple[frozenset, tuple[str, ...]]:
    """`[capabilities]`: the claims, each checked against the executables it needs, and the
    provider routes, each an executable `providers/<route>`."""
    unknown = sorted(set(data) - CAPABILITY_KEYS)
    if unknown:
        raise PackError(f"{where}: [capabilities] has no key {', '.join(unknown)}; "
                        f"the keys are {', '.join(sorted(CAPABILITY_KEYS))}")
    declared = set()
    for name in NEEDS:
        value = data.get(name, False)
        if not isinstance(value, bool):
            raise PackError(f"{where}: [capabilities] {name} must be true or false")
        if not value:
            continue
        missing = [verb for verb in NEEDS[name] if not executable(path, verb)]
        if missing:
            raise PackError(f"{where}: declares {name} but has no executable "
                            f"{', '.join(missing)}")
        declared.add(name)
    routes = tuple(strings(data.get("routes", []), f"{where} [capabilities] routes"))
    for route in routes:
        if not NAME.match(route) or not executable(path, f"providers/{route}"):
            raise PackError(f"{where}: [capabilities] routes names {route!r}, "
                            f"but providers/{route} is not an executable")
    return frozenset(declared), routes


def terms_of(data: dict, where: str) -> dict:
    """`[terms]`: known keys only, each a non-empty string, and a `ticket_ref` that is a
    prefix of letters, digits, `-` and `_` followed by one `<n>`."""
    unknown = sorted(set(data) - set(TERM_KEYS))
    if unknown:
        raise PackError(f"{where}: [terms] has no key {', '.join(unknown)}; "
                        f"the keys are {', '.join(TERM_KEYS)}")
    for key, value in data.items():
        if not isinstance(value, str) or not value.strip():
            raise PackError(f"{where}: [terms] {key} must be a non-empty string")
    ref = data.get("ticket_ref")
    if ref is not None and not TICKET_REF.match(ref):
        raise PackError(f"{where}: [terms] ticket_ref {ref!r} must be a prefix of letters, "
                        f"digits, - and _ followed by one <n>, such as abc-<n>")
    return dict(data)


def setup_of(path: Path, entries, declared: frozenset, requires: tuple, where: str) -> tuple:
    """`[[setup]]`: each with a unique `id` and a `title`, a `text` file that exists in the
    pack, an `after` that is a core step, a `for` the pack declares and `requires` that name
    its own `[[requires]]` entries."""
    if not isinstance(entries, list):
        raise PackError(f"{where}: setup must be [[setup]] entries")
    names, steps = {need.name for need in requires}, []
    for entry in entries:
        if not isinstance(entry, dict):
            raise PackError(f"{where}: each [[setup]] is a table")
        label = f"{where} setup {entry.get('id')!r}"
        unknown = sorted(set(entry) - SETUP_KEYS)
        if unknown:
            raise PackError(f"{label} has no key {', '.join(unknown)}; the keys are {', '.join(sorted(SETUP_KEYS))}")
        if not isinstance(entry.get("id"), str) or not NAME.match(entry["id"]):
            raise PackError(f"{label}: id must be lower case letters, digits, - and _")
        if entry["id"] in [step.id for step in steps]:
            raise PackError(f"{label}: the id is used twice")
        for key in ("title", "text"):
            if not isinstance(entry.get(key), str) or not entry[key].strip():
                raise PackError(f"{label}: `{key}` must be a non-empty string")
        text = files(path, [entry["text"]], f"{label} text")[0]
        after = entry.get("after", "integrations")
        after = SETUP_MOVED.get(after, after)
        if after not in SETUP_AFTER:
            raise PackError(f"{label}: after {after!r} is not a step; one of {', '.join(SETUP_AFTER)}")
        serves = tuple(strings(entry.get("for", []), f"{label} for"))
        stray = sorted(set(serves) - declared)
        if stray:
            raise PackError(f"{label} is for {', '.join(stray)}, which [capabilities] does not declare")
        needed = tuple(strings(entry.get("requires", []), f"{label} requires"))
        unknown = sorted(set(needed) - names)
        if unknown:
            raise PackError(f"{label} requires {', '.join(unknown)}, which no [[requires]] names")
        steps.append(SetupStep(entry["id"], entry["title"].strip(), text, after, serves, needed))
    return tuple(steps)


def table(data: dict, key: str, where: str) -> dict:
    value = data.get(key, {})
    if not isinstance(value, dict):
        raise PackError(f"{where}: [{key}] must be a table")
    return value


def strings(value, what: str) -> list[str]:
    if not isinstance(value, list) or not all(isinstance(item, str) and item for item in value):
        raise PackError(f"{what} must be a list of strings")
    return value


def files(path: Path, names, what: str) -> tuple[Path, ...]:
    """Paths inside the pack that must exist; one that does not is a broken pack."""
    found = tuple(path / name for name in strings(names, what))
    missing = [str(item.relative_to(path)) for item in found if not item.exists()]
    if missing:
        raise PackError(f"{what}: {', '.join(missing)} not in {path}")
    return found


def requirement(entry, where: str) -> Requirement:
    if not isinstance(entry, dict) or not all(isinstance(entry.get(k), str) and entry[k]
                                              for k in ("name", "kind", "check", "why")):
        raise PackError(f"{where}: each [[requires]] needs name, kind, check and why")
    if entry["kind"] not in KINDS:
        raise PackError(f"{where}: requires {entry['name']!r} kind must be one of {', '.join(KINDS)}")
    serves = tuple(strings(entry.get("for", []), f"{where} requires {entry['name']!r} for"))
    return Requirement(entry["name"], entry["kind"], entry["check"], entry["why"], serves,
                       **fix_of(entry, f"{where}: the {where.split('/')[0]} pack's [[requires]] "
                                       f"{entry['name']!r}"))


def fix_of(entry: dict, label: str) -> dict:
    """The entry's own fix (`FIX_KEYS`), each one line of text; a `command`, a `done_when` or
    an `action` with no `fix` sentence to stand under is refused. These four were ignored
    until c-688, so the refusal says the pack, the entry and the key: a pack that loaded
    before and does not now is found from the one line."""
    said = {}
    for key in FIX_KEYS:
        if key not in entry:
            continue
        value = entry[key]
        if not isinstance(value, str) or not value.strip() or "\n" in value:
            raise PackError(f"{label}: {key} must be one line of text")
        said[key] = value.strip()
    orphan = [key for key in said if key != "fix"]
    if orphan and "fix" not in said:
        raise PackError(f"{label}: {orphan[0]} needs a fix, the sentence it stands under")
    return said


def fix_said(need: Requirement) -> dict:
    """The fix parts the pack wrote for `need`, and only those."""
    return {key: getattr(need, key) for key in FIX_KEYS if getattr(need, key)}


def checks(pack: Pack, env: dict | None = None) -> list[dict]:
    """Each requirement's check, run by `sh -c` in the pack's directory: `{name, kind, ok,
    why, for}`, and its `fix`, `command`, `done_when` and `action` where the pack wrote them
    (c-688). `env` is laid over this process's (the space's config dir, the stack guard hook)."""
    results = []
    for need in pack.requires:
        try:
            done = subprocess.run(["sh", "-c", need.check], cwd=pack.path, capture_output=True,
                                  env={**os.environ, **(env or {})}, timeout=CHECK_SECONDS)
            ok = done.returncode == 0
        except (OSError, subprocess.SubprocessError):
            ok = False
        results.append({"name": need.name, "kind": need.kind, "ok": ok, "why": need.why,
                        "for": list(need.serves), **fix_said(need)})
    return results


def drift_terms(root: Path = PACKAGE) -> dict[str, list[str]]:
    """Each pack's `drift-terms` under `root/packs`: {pack: [pattern, ...]}, comments and
    blank lines dropped. The words only that pack may say."""
    terms = {}
    for path in sorted((root / PACKS).glob(f"*/{DRIFT_TERMS}")):
        lines = [line.strip() for line in path.read_text().splitlines()]
        terms[path.parent.name] = [line for line in lines if line and not line.startswith("#")]
    return terms


def all_drift_terms(root: Path = PACKAGE) -> list[str]:
    return [term for terms in drift_terms(root).values() for term in terms]


def configured_drift_terms(root: Path = PACKAGE) -> list[str]:
    """The tree's pack terms, then those of the install `KEEL_CONFIG` names (c-722 r1.F7):
    an owner's pack lives in the install once moved, and its words still may not appear
    outside it."""
    terms = all_drift_terms(root)
    own = install_packs()
    if own is not None:
        terms += [term for term in all_drift_terms(own.parent) if term not in terms]
    return terms
