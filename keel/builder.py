"""Bosun's builder (c-619, c-621; docs/atlas/96-bosun.md, "The builder").

`[keel] bosun_builder` turns Bosun's building on; `[builder]` says what it builds and how.

- **The builder** (every install). Bosun builds the repos `[builder] repos` names (`packs`,
  the install's own `<install>/packs`, plus any personal repo the user lists; the import
  carries keel and harbor), each from its own full clone under `<install>/builder/`, never in
  the live checkout. It runs as the user with the user's reach, in `auto` mode by default
  (Claude Code's classifier, with Keel's `autoMode` block, `keel/builderauto.py`) or in
  `bypass` mode when the user sets `[builder] mode = "bypass"` (the superbuilder). One
  mechanism holds in both: a PreToolUse hook that refuses an edit inside a live checkout
  (`bin/keel-builder-guard`, `keel/builderguard.py`). Everything else is its memory's
  working pattern (`bosun/memory/in-app.md`) and the board's own rules: its work lands only
  by the user's Approve outcome (`keel/merging.py` fetches its branch from the clone), and
  the board refuses it an approval, `kb tested` and a card on another repo
  (`keel/authority.py`).

  Until 2026-10-03 it ran fenced: Claude's sandbox, a door of its own to the board and deny
  lists on every path of the user's. Every gap in that fence cost a round trip with the user,
  who has an unfenced Claude a terminal away anyway, so it went (his call, that day).
- **The superuser** (`superuser = true`, only in an older checkout's own `keel.toml`). The legacy builder of
  Keel's own repo: `[console] permission_mode` (bypass), its own approvals onto the
  integration branch. It does not start: its fence was Bosun as its own Unix user, retired
  in c-648, and no other is decided (`SUPERUSER_UNFENCED`). An install has no superuser
  (`INSTALL_SUPERUSER`): its bypass is `mode = "bypass"`, which approves nothing itself.

This module reads the config and says what the builder is; `keel/console.py` builds the
session from it.
"""

from __future__ import annotations

import json
import shlex
import sys
from pathlib import Path

from keel import builderauto, packclones
from keel.config import Config

DEFAULTS = {"superuser": False, "repos": ["packs"], "mode": "auto"}
SUPERUSER, IN_APP = "superuser", "in-app"
PACKS = "packs"
# The install's own repos (r1.F1): its packs and its memory, each a personal repo the builder
# builds from its own clone, so a change to either is a card that lands by Approve outcome.
# Neither is one of the user's: Setup, readiness and the deck leave both out of "your repos".
MEMORY = "memory"
OWN_REPOS = (PACKS, MEMORY)
CLONES = "builder"
CREDENTIALS = "credentials"
# `[builder] mode` to Claude Code's permission mode: auto by default, bypass for the
# superbuilder (his call, 2026-10-03).
PERMISSION_MODES = {"auto": "auto", "bypass": "bypassPermissions"}
# The user's own secrets under their home: nothing it builds needs to read them.
HOME_SECRETS = (".ssh", ".gnupg", ".aws", ".config/gh", ".config/gcloud", ".kube",
                ".docker/config.json", ".git-credentials", ".netrc", ".npmrc", ".pypirc",
                ".claude/.credentials.json", "Library/Keychains",
                ".config/git/credentials", ".cache/git/credential")
# The `kb` verbs building a card takes, allowed by rule so auto mode's classifier never
# decides whether Bosun may use its own board; the board scopes each (`keel/authority.py`).
BUILD_VERBS = ("create", "set", "stage", "block", "unblock", "split")
INSTALL_SUPERUSER = ("an install has one builder ([builder] superuser = true is refused here); "
                     "for bypass, set [builder] mode = \"bypass\"")
# Off an install. Its permission mode does not fence its editing tools, and the fence it had
# (Bosun as its own Unix user) is retired.
SUPERUSER_UNFENCED = ("[builder] superuser runs Bosun in its own permission mode, which does not "
                      "fence its editing tools; the superuser builder does not start since "
                      "c-648, until its fence is decided")


def conf(cfg: Config) -> dict:
    return {**DEFAULTS, **(getattr(cfg, "builder", None) or {})}


def superuser(cfg: Config) -> bool:
    """`[builder] superuser` as written. On an install it is refused (`refusal`), and the
    board never takes it as a switch (`Config.switches`)."""
    return bool(conf(cfg)["superuser"])


def in_app(cfg: Config) -> bool:
    """True when Bosun builds as an install's builder (auto or bypass)."""
    return bool(cfg.bosun_builder) and not superuser(cfg)


def mode(cfg: Config) -> str | None:
    if not cfg.bosun_builder:
        return None
    return SUPERUSER if superuser(cfg) else IN_APP


def permission_mode(cfg: Config) -> str:
    """Claude Code's permission mode for the builder: `[builder] mode`, auto unless the user
    chose bypass. An unknown word is refused at Start (`refusal`) and reads as auto here."""
    return PERMISSION_MODES.get(str(conf(cfg)["mode"]), PERMISSION_MODES["auto"])


def same(path, other) -> bool:
    try:
        return Path(path).expanduser().resolve() == Path(other).expanduser().resolve()
    except OSError:
        return False


def repos(cfg: Config) -> frozenset:
    """The repo keys the builder builds, `[builder] repos`. The superuser is not scoped: it
    builds every personal repo card (`views.bosun_builds`)."""
    return frozenset(str(key) for key in conf(cfg)["repos"])


def own_repos(home: Path) -> dict:
    """`{key: path}` of the install's own repos it has: packs always (init makes it), the
    memory once it is a git repo (seeded by init, or brought in by `move-personal`), and each
    pack that is its own clone in the packs folder, as `pack-<name>` (c-740,
    `keel/packclones.py`): its changes land in the pack's repo, never in the packs repo."""
    home = Path(home)
    base = {key: home / key for key in OWN_REPOS if key == PACKS or (home / key / ".git").exists()}
    return {**base, **packclones.own(home)}


def is_own(home: Path | None, path) -> bool:
    """Whether `path` is one of the install's own repos rather than one of the user's: its
    packs, its memory, or a pack cloned into its packs folder."""
    if not home:
        return False
    own = [Path(home) / key for key in OWN_REPOS] + list(packclones.found(Path(home) / PACKS).values())
    return any(same(path, one) for one in own)


def built_in(text: str) -> list[str]:
    """`[builder] repos` as the config `text` has it now (the default where it writes none):
    read from the text, never from a config loaded before an edit (c-740 r2.F1)."""
    import tomllib
    said = (tomllib.loads(text).get("builder") or {}).get("repos", DEFAULTS["repos"])
    return [str(name) for name in said]


def list_own(text: str, cfg: Config, key: str, path: Path) -> str:
    """The config `text` with an own repo listed: a personal repo, and, when that listing is
    new, a repo `[builder] repos` builds. A repo listed already is kept as it is, so a user who
    took one out of `[builder] repos` is not overruled by the next init."""
    from keel import configedit
    personal = cfg.spaces.get("personal")
    if personal is None or key in personal.repos:
        return text
    text = configedit.set_entry(text, "spaces.personal.repos", key, str(path))
    built = built_in(text)
    if key not in built:
        text = configedit.set_entry(text, "builder", "repos", built + [key])
    return text


def unlist_gone(text: str, cfg: Config, home: Path) -> str:
    """The config `text` without each cloned pack's listing whose clone is gone (c-740 r1.F5,
    `packclones.gone`): its `[spaces.personal.repos]` line, and, in `[builder] repos`, every
    `pack-*` name that no personal repo is listed under any more (r2.F1: the gone keys are
    found once and the list is written once, from the text as it is, so two gone clones both
    go, and a name left there by an older edit goes too). Made where `list_own` lists, so a
    rename or a removal never leaves a path that is not there reading as one of the user's
    repos, nor a repo Bosun is told to build with no checkout to clone. Nothing on disk is
    touched."""
    import tomllib
    from keel import configedit
    personal = cfg.spaces.get("personal")
    listed = ((tomllib.loads(text).get("spaces") or {}).get("personal") or {}).get("repos") or {}
    gone = [key for key in (packclones.gone(home, personal.repos) if personal is not None else ())
            if key in listed]
    for key in gone:
        text = configedit.remove_entry(text, "spaces.personal.repos", key)
    kept = set(listed) - set(gone)
    built = built_in(text)
    wanted = [name for name in built if not name.startswith(packclones.KEY) or name in kept]
    return text if wanted == built else configedit.set_entry(text, "builder", "repos", wanted)


def repo_key(repo) -> str:
    return str(repo or "").split(",")[0].strip()


# ----- the builder's places on an install -----

def home(cfg: Config) -> Path | None:
    return cfg.install_home


def clones(cfg: Config) -> Path | None:
    """Its cwd: `<install>/builder/`, holding one full clone per repo it builds."""
    return home(cfg) / CLONES if home(cfg) else None


def clone_for(cfg: Config, card: dict) -> Path | None:
    """The builder's clone a card's branch is in, or None (not its card, or not an install's
    builder)."""
    key = repo_key(card.get("repo"))
    if not in_app(cfg) or clones(cfg) is None or card.get("space") != "personal" or key not in repos(cfg):
        return None
    return clones(cfg) / key


def real_clone(cfg: Config, clone: Path) -> Path | None:
    """The clone the landing may fetch from, resolved ONCE: a real directory with a real
    `.git` directory (no link, no gitfile pointing elsewhere), under `<install>/builder`.
    The caller fetches from exactly the path returned; None refuses."""
    base = clones(cfg)
    if base is None or base.is_symlink() or clone.is_symlink() or (clone / ".git").is_symlink():
        return None
    resolved = clone.resolve()
    if not resolved.is_relative_to(base.resolve()) or not (resolved / ".git").is_dir():
        return None
    return resolved


def live_repos(cfg: Config) -> list[Path]:
    """Every personal repo's live checkout on this machine (it builds them only in its
    clones), and every repo the install copied into its layout, in any space (c-678: Bosun
    reads the user's repos to draft their CLAUDE.md, and never edits them). A checkout a
    space lists outside the layout is that space's own business."""
    from keel import repolayout         # noqa: PLC0415 - only this list needs the layout
    space = cfg.spaces.get("personal")
    mine = [Path(path) for _, path in sorted(space.repos.items())] if space is not None else []
    layout = repolayout.spaces_of(cfg)
    copied = [Path(path) for _, one in sorted(cfg.spaces.items()) for _, path in sorted(one.repos.items())
              if repolayout.home_of(path, layout) is not None]
    return list(dict.fromkeys(mine + copied))


def live_checkouts(cfg: Config) -> list[Path]:
    """What the guard keeps its edits out of: the code it runs (KEEL_HOME, his live Keel) and
    every personal repo's live checkout. A path its clones lie under is left out, or it could
    not write its own clone."""
    base = clones(cfg)
    paths = [cfg.root, *live_repos(cfg)]
    kept = [path for path in paths if base is None or not base.is_relative_to(path)]
    return list(dict.fromkeys(kept))


# ----- its session -----

def guard_hook(cfg: Config) -> dict:
    """The PreToolUse hook that refuses an edit inside a live checkout (`keel/builderguard.py`),
    run by this interpreter by its absolute path, so a missing `python3` on the hook's PATH
    cannot turn it into a non-blocking error."""
    from keel import builderguard, house
    argv = [sys.executable, str(cfg.root / "bin" / "keel-builder-guard"),
            *[str(path) for path in live_checkouts(cfg)]]
    return house.command_hook(shlex.join(argv), matcher=builderguard.MATCHER, timeout=10)


def secret_paths(cfg: Config) -> list[Path]:
    """What it never reads: the install's credentials (its keys) and the user's own secrets."""
    paths = [home(cfg) / CREDENTIALS] if home(cfg) else []
    return paths + [Path.home() / name for name in HOME_SECRETS]


def deny_rules(cfg: Config) -> list[str]:
    rules = []
    for path in secret_paths(cfg):      # the file or the tree
        rules += [f"Read(/{path})", f"Read(/{path}/**)"]
    return rules + builderauto.push_deny()


def build_allow(cfg: Config) -> list[str]:
    kb, keel = cfg.root / "bin" / "kb", cfg.root / "bin" / "keel"
    rules = [f"Bash({prefix} {verb}:*)" for verb in BUILD_VERBS for prefix in ("kb", str(kb))]
    return rules + [f"Bash({prefix} board push:*)" for prefix in ("keel", str(keel))]


def auto_mode(cfg: Config) -> dict:
    """The `autoMode` block its settings carry (`keel/builderauto.py`)."""
    return builderauto.block(clones(cfg), sorted(repos(cfg)), live_checkouts(cfg))


def review_hooks(cfg: Config) -> list[dict]:
    """The SubagentStop hook per review agent, as a house has (`house.hooks_for`), with no card
    on its line: `--bosun` finds the card each review is for (`stamp.bosun_review`). What
    lets Bosun's own approval in bypass see its cards reviewed (`gate.built_covers`)."""
    from keel import house
    from keel.review import agents, stamp
    line = f"{cfg.root / 'bin' / stamp.STAMP_SCRIPT} {stamp.BOSUN_FLAG}"
    return [house.command_hook(line, matcher=name) for name in (agents.REVIEWER, agents.VERIFIER)]


def review_agents() -> str:
    """The `--agents` value its session starts with: the reviewer and the verifier a house
    gets (`keel/review/agents.py`)."""
    from keel.review import agents
    return agents.agents_json()


def settings(cfg: Config, made: dict) -> dict:
    """The builder's settings from the session's common ones (`console.settings`): the live
    checkout guard first, its secrets and the pushes it never makes denied, its build verbs
    allowed, its `autoMode` block (in this file, which only Bosun's session reads), and the
    drain's wake accepted: a peer message from a session in another permission mode, which a
    session not in default mode holds unless it accepts (seen in bypass, 2026-09-29). Its
    review agents' answers are recorded by the stamp hook a house has (`review_hooks`)."""
    deny = made["permissions"]["deny"] + deny_rules(cfg)
    allow = made["permissions"]["allow"] + build_allow(cfg)
    env = dict(made["env"], KEEL_CONFIG=str(cfg.source))
    hooks = dict(made["hooks"], PreToolUse=[guard_hook(cfg), *made["hooks"].get("PreToolUse", [])],
                 SubagentStop=review_hooks(cfg))
    return dict(made, hooks=hooks, permissions={"deny": deny, "allow": allow}, env=env,
                autoMode=auto_mode(cfg), crossSessionInbound="accept")


# ----- its clones -----

def clone_source(cfg: Config, key: str) -> Path | None:
    """The live checkout a repo's clone is made from: the personal repo of that key."""
    space = cfg.spaces.get("personal")
    path = space.repo_path(key) if space is not None else None
    return path if path is not None and (path / ".git").exists() else None


def to_clone(cfg: Config) -> list[str]:
    """The repo keys `ensure_clones` would clone now: no clone yet, nothing in the way, and a
    live checkout to clone from."""
    if not in_app(cfg) or clones(cfg) is None:
        return []
    return [key for key in sorted(repos(cfg)) if not (clones(cfg) / key).exists()
            and clone_source(cfg, key) is not None]


def ensure_clones(cfg: Config) -> list[str]:
    """A full clone (`--no-hardlinks`: no object file shared with the live repo) of each repo
    it builds that has none yet, under `<install>/builder/<key>`: by init, or by Start on the
    first card of a newly listed repo. Never a worktree of the live checkout. The keys made;
    a repo with no live checkout here is left for `refusal` to name."""
    import subprocess
    if not in_app(cfg) or clones(cfg) is None:
        return []
    made = []
    for key in to_clone(cfg):
        target, source = clones(cfg) / key, clone_source(cfg, key)
        target.parent.mkdir(parents=True, exist_ok=True)
        subprocess.run(["git", "clone", "--quiet", "--no-hardlinks", str(source), str(target)],
                       capture_output=True, text=True, check=True, timeout=600)
        made.append(key)
    return made


# ----- may it start -----

def refusal(cfg: Config, cloned_at_start: bool = False) -> str | None:
    """Why Bosun may not start as this builder, or None. With `cloned_at_start`, a clone
    Start would make first (`to_clone`) is not missing: the readiness row asks so, before
    Start has run. The superuser never starts: its fence was Bosun as its own Unix user,
    which is retired (c-648), and what fences it instead is not decided."""
    if mode(cfg) == SUPERUSER and home(cfg) is not None:
        return INSTALL_SUPERUSER
    if mode(cfg) == SUPERUSER:
        return SUPERUSER_UNFENCED
    if mode(cfg) != IN_APP:
        return None
    if home(cfg) is None:
        return "the builder runs on an install (`shipyard init <dir>`), not on this config"
    if str(conf(cfg)["mode"]) not in PERMISSION_MODES:
        return f"[builder] mode is {conf(cfg)['mode']!r}; it is one of {', '.join(PERMISSION_MODES)}"
    coming = set(to_clone(cfg)) if cloned_at_start else set()
    missing = [key for key in sorted(repos(cfg))
               if not (clones(cfg) / key / ".git").exists() and key not in coming]
    if missing:
        return (f"the builder has no clone of {', '.join(missing)} under {clones(cfg)}, and none "
                f"could be made from a live checkout (a personal repo of that key, a git repo); "
                f"Start makes one, as `shipyard init {home(cfg)}` does")
    return None


def status(cfg: Config) -> dict | None:
    """What the Bosun page's badge says: the mode."""
    found = mode(cfg)
    if found is None:
        return None
    if found == SUPERUSER:
        return {"mode": found, "label": "Superuser"}
    bypass = permission_mode(cfg) == PERMISSION_MODES["bypass"]
    return {"mode": found, "label": "Builder, bypass" if bypass else "Builder, auto mode",
            "repos": sorted(repos(cfg))}


# Claude Code's own record that its bypass mode warning was accepted, in a config dir's user
# settings (`settings.json`). Read off Claude Code 2.1.295 (c-729): a background session in
# bypass needs it there, and neither `--settings` nor `settings.local.json` counts. Without it
# Bosun in bypass waits on a dialog nobody sees.
BYPASS_ACCEPTED = "skipDangerousModePermissionPrompt"


def bypass_chosen(cfg: Config) -> bool:
    """The install's builder is the Full builder: in-app, in bypass."""
    return in_app(cfg) and permission_mode(cfg) == PERMISSION_MODES["bypass"]


def owned(cfg: Config, folder: Path) -> bool:
    """`folder` is inside the install (`setupconfig.install_of`), as its own Claude folder is."""
    from keel import setupconfig     # noqa: PLC0415 - setupconfig reads appservices
    try:
        home = setupconfig.install_of(cfg).resolve()
        Path(folder).expanduser().resolve().relative_to(home)
    except (setupconfig.SetupError, ValueError, OSError):
        return False
    return True


def record_bypass(cfg: Config) -> bool | None:
    """Choosing Full builder is the acceptance of bypass mode (c-729): the setup page explains
    the risk, so the choice writes Claude Code's acceptance into Bosun's config dir, and any
    other choice (Guide, builder mode off) takes it out again. Every other key of the file is
    kept. Answers whether the acceptance is now recorded, or None when nothing is touched: a
    file that cannot be read as a JSON object, a Claude folder outside the install (the
    user's own, r1.F1: never Shipyard's to edit), or a settings.json that is a link, which a
    rename would turn into a plain file."""
    from keel import atomicfile, console     # noqa: PLC0415 - console imports this module
    folder = Path(console.config_dir(cfg))
    if not owned(cfg, folder):
        return None
    path = folder / "settings.json"
    if path.is_symlink():
        return None
    want = bypass_chosen(cfg)
    try:
        held = json.loads(path.read_text()) if path.exists() else {}
    except (OSError, ValueError):
        return None
    if not isinstance(held, dict):
        return None
    if want and held.get(BYPASS_ACCEPTED) is not True:
        held[BYPASS_ACCEPTED] = True
    elif not want and BYPASS_ACCEPTED in held:
        del held[BYPASS_ACCEPTED]
    else:
        return want
    atomicfile.write_text(path, json.dumps(held, indent=2) + "\n")
    return want
