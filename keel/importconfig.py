"""The choices `shipyard import` carries from the old config into the install's (c-620).

The old config is his `keel.toml` (`--old-config`, by default the checkout's own): it holds
what he chose (repos, models, the pipeline, the test commands, the `[keel]` switches) beside
what two machines needed. Only the first kind is carried, one key at a time through
`keel/configedit.py`, and written once through `setupconfig.edit`, so the backup, the hash
check and the reload apply as they do to every Setup write.

- **personal**: each listed repo whose checkout is on this machine (as an existing checkout,
  not cloned), and `projects_dir`, `model`, `confirm`, `house_review`, `pipeline`.
- **work**: the pack turned on as Setup turns it on (`packsetup.pack_space`), its
  `config_dir` set to `--work-config-dir`, then the old space's repos that are here and its
  own keys.
- **tables**: `[tests]`, `[house_tests]`, `[integration]`, `[retests]`, `[deploy_tests]`,
  and each `[keel]` switch the shipped example has (`drain_paused` excepted: the install
  keeps its own).
- **never**: `[hosts.*]`, `[tenancy]`, `[console]`, `[backup]`, `board_url`, the door's
  `url`, `[recurring.restore-rehearsal]`. docs/atlas/87-import.md.
"""

from __future__ import annotations

import difflib
import tomllib
from pathlib import Path

from keel import configedit, installer, packsetup, setupconfig
from keel.config import Config

CARRIED_TABLES = ("tests", "house_tests", "integration", "retests", "deploy_tests")
PERSONAL_KEYS = ("projects_dir", "model", "confirm", "house_review", "pipeline")
# What the old work space carries that the install sets itself or never takes.
WORK_DROPS = ("host", "adapter", "pack", "config_dir", "repos")
KEEL_KEPT = ("drain_paused",)
NEVER = ("hosts", "tenancy", "console", "backup", "recurring.restore-rehearsal",
         "keel.board_url", "keel.url")
DEFAULT_WORK_DIR = "~/.claude"


class CarryError(Exception):
    """The old config could not be read."""


def load_old(path: Path) -> dict:
    try:
        return tomllib.loads(Path(path).expanduser().read_text())
    except (OSError, tomllib.TOMLDecodeError) as error:
        raise CarryError(f"the old config {path} could not be read ({error})") from None


def old_space(old: dict, name: str) -> dict:
    return dict((old.get("spaces") or {}).get(name) or {})


def default_work_dir(old: dict) -> str:
    """The work space's Claude dir as the old config named it (a-88's recommended answer)."""
    return str(old_space(old, "work").get("config_dir") or DEFAULT_WORK_DIR)


def here(repos: dict) -> tuple[dict, dict]:
    """`(on this machine, not here)`: a repo is here when its checkout is a directory."""
    kept, gone = {}, {}
    for key, path in (repos or {}).items():
        (kept if Path(str(path)).expanduser().is_dir() else gone)[key] = path
    return kept, gone


def switches(root: Path) -> list[str]:
    """The `[keel]` keys the shipped example carries, less the ones an install keeps."""
    example = tomllib.loads((root / installer.EXAMPLE).read_text())
    return [key for key in example.get("keel", {}) if key not in KEEL_KEPT]


def current(text: str, table: str, key: str):
    value = tomllib.loads(text)
    for part in table.split("."):
        value = value.get(part, {}) if isinstance(value, dict) else {}
    return value.get(key) if isinstance(value, dict) else None


def setting(text: str, table: str, key: str, value, notes: list[str]) -> str:
    """`key = value` in `[table]`, left as it is (its comment kept) when it already says so."""
    if current(text, table, key) == value:
        return text
    try:
        return configedit.set_entry(text, table, key, value)
    except configedit.EditError as error:
        notes.append(f"not carried: [{table}] {key} ({error})")
        return text


def personal(text: str, old: dict, notes: list[str]) -> str:
    space = old_space(old, "personal")
    for key in PERSONAL_KEYS:
        if key in space:
            text = setting(text, "spaces.personal", key, space[key], notes)
    kept, gone = here(space.get("repos"))
    for key, path in kept.items():
        text = setting(text, "spaces.personal.repos", key, path, notes)
    notes += [f"not carried: personal repo {key} ({path} is not on this machine)" for key, path in gone.items()]
    return text


def work(cfg: Config, text: str, old: dict, work_dir: str, notes: list[str]) -> str:
    space = old_space(old, "work")
    if "work" not in cfg.spaces:
        pack = str(space.get("pack") or space.get("adapter") or "work")
        try:
            change, _ = packsetup.pack_space(cfg, pack, "work", "by `shipyard import`")
        except setupconfig.SetupError as error:
            raise CarryError(f"the work space could not be turned on: {error}") from None
        text = change(text)
    text = setting(text, "spaces.work", "config_dir", work_dir, notes)
    for key, value in space.items():
        if key not in WORK_DROPS:
            text = setting(text, "spaces.work", key, value, notes)
    kept, gone = here(space.get("repos"))
    for key, path in kept.items():
        text = setting(text, "spaces.work.repos", key, path, notes)
    notes += [f"not carried: work repo {key} ({path} is not on this machine)" for key, path in gone.items()]
    return text


def builder(text: str, old: dict, notes: list[str]) -> str:
    """The old superuser built every personal repo card, so those repos stay Bosun's: added
    to `[builder] repos`, the drain starts no house on their assigned cards (the real move
    started five of his, 2026-10-03). Superuser itself is not carried: it needs Bosun's own
    Unix user on this machine, which is set up apart."""
    if not (old.get("builder") or {}).get("superuser"):
        return text
    kept, _ = here(old_space(old, "personal").get("repos"))
    repos = list(current(text, "builder", "repos") or [])
    added = [key for key in kept if key not in repos]
    if not added:
        return text
    notes.append(f"builder: {', '.join(added)} stay Bosun's ([builder] repos); superuser not carried")
    return setting(text, "builder", "repos", repos + added, notes)


def carry(cfg: Config, text: str, old: dict, work_dir: str) -> tuple[str, list[str]]:
    """The install's config text with the old choices carried, and a note per thing left."""
    notes: list[str] = []
    text = personal(text, old, notes)
    text = builder(text, old, notes)
    if old_space(old, "work"):
        text = work(cfg, text, old, work_dir, notes)
    for table in CARRIED_TABLES:
        for key, value in (old.get(table) or {}).items():
            text = setting(text, table, key, value, notes)
    for key in switches(cfg.root):
        if key in (old.get("keel") or {}):
            text = setting(text, "keel", key, old["keel"][key], notes)
    notes += [f"never carried: {name}" for name in present(old, NEVER)]
    return text, notes


def present(old: dict, names) -> list[str]:
    found = []
    for name in names:
        value = old
        for part in name.split("."):
            value = value.get(part) if isinstance(value, dict) else None
        if value is not None:
            found.append(name)
    return found


def spaces_after(cfg: Config, old: dict) -> set[str]:
    """The spaces the install has once the old config is carried."""
    return set(cfg.spaces) | ({"work"} if old_space(old, "work") else set())


def personal_repos(cfg: Config, old: dict) -> dict[str, Path]:
    """The personal repos a card may name once carried, by key, as paths on this machine."""
    space = cfg.spaces.get("personal")
    repos = dict(space.repos) if space is not None else {}
    kept, _ = here(old_space(old, "personal").get("repos"))
    repos.update({key: Path(str(path)).expanduser() for key, path in kept.items()})
    return repos


def projects_dir(cfg: Config, old: dict) -> Path | None:
    value = old_space(old, "personal").get("projects_dir")
    if value:
        return Path(str(value)).expanduser()
    space = cfg.spaces.get("personal")
    return space.projects_dir if space is not None else None


def diff(before: str, after: str, name: str = "config.toml") -> str:
    return "".join(difflib.unified_diff(before.splitlines(True), after.splitlines(True),
                                        f"{name} (now)", f"{name} (imported)"))


def apply(cfg: Config, old: dict, work_dir: str) -> dict:
    """The one checked, backed-up write of the carried config."""
    return setupconfig.edit(cfg, lambda text: carry(cfg, text, old, work_dir)[0])
