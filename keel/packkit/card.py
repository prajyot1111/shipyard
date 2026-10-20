"""A card as every pack on the kit sees it: the board through `kb`, the space's repos and
where each lives on the host, the per-card options every verb reads, and git with a clock.

A card's space is the one it names (`card["space"]`), so two spaces may be on one pack. The
verbs are thin executables over the kit's modules, so a pack's tests drive the modules with
a dict card, a recording board (`KB`) and a stand-in host.
"""

import functools
import json
import os
import subprocess
import sys
from pathlib import Path

from keel.packkit import pack
from keel.packkit.errors import HostError

KIT = Path(__file__).resolve().parent
KEEL_HOME = Path(os.environ.get("KEEL_HOME") or KIT.parent.parent).resolve()
RESEARCH = "research"
GIT_SECONDS = 60
KB_SECONDS = 60


# ----- Keel's config and the board -----

@functools.cache
def keel_config():
    """Keel's loaded config, through Keel's own loader (found via KEEL_HOME)."""
    engine()
    from keel import config  # noqa: PLC0415 - Keel's loader
    return config.load(ensure=False)


def engine():
    """Keel's adapter module: how a card's branch and worktree directory are named
    everywhere else (`adapters.branch_name`, `adapters.worktree_dirs`), so a pack names
    them the same way."""
    if str(KEEL_HOME) not in sys.path:
        sys.path.insert(0, str(KEEL_HOME))
    from keel import adapters  # noqa: PLC0415
    return adapters


class Kb:
    """`kb` by absolute path under `KEEL_HOME`: every verb's only door to the board."""

    def __init__(self, keel_home: Path = KEEL_HOME):
        self.path = keel_home / "bin" / "kb"

    def run(self, *args: str) -> str:
        try:
            done = subprocess.run([str(self.path), *args], capture_output=True, text=True,
                                  timeout=KB_SECONDS)
        except subprocess.TimeoutExpired:
            raise HostError(f"kb {' '.join(args[:2])} gave no answer in {KB_SECONDS} seconds") from None
        if done.returncode != 0:
            raise HostError(f"kb {' '.join(args[:2])}: {done.stderr.strip() or done.stdout.strip()}")
        return done.stdout

    def show(self, card_id: str) -> dict:
        return json.loads(self.run("show", card_id, "--json", "--events", "0"))

    def cards(self) -> list[dict]:
        return json.loads(self.run("list", "--all", "--json"))

    def set_option(self, card_id: str, key: str, value) -> None:
        raw = value if isinstance(value, str) else json.dumps(value)
        self.run("set", card_id, f"options.{key}={raw}")

    def note(self, card_id: str, text: str) -> None:
        self.run("note", card_id, text)


KB = Kb()


def load_card(card_id: str) -> dict:
    return KB.show(card_id)


def space_of(card: dict):
    space = keel_config().spaces.get(card.get("space") or "")
    if space is None:
        raise HostError(f"card {card.get('id')} is in a space this config does not have")
    return space


def card_dir(card_id: str) -> Path:
    return keel_config().card_dir(card_id)


def context_text(card_id: str) -> str:
    path = card_dir(card_id) / "context.md"
    return path.read_text(errors="replace") if path.is_file() else ""


def on_pack(cfg) -> list[str]:
    """The spaces of this config whose pack is the bound one."""
    return [name for name, space in cfg.spaces.items()
            if space.adapter_dir is not None and Path(space.adapter_dir).resolve() == pack.here()]


# ----- options and kinds -----

def option(card: dict, key: str, default=None):
    value = (card.get("options") or {}).get(key)
    return default if value is None else value


def repos_of(card: dict) -> list[str]:
    return [key.strip() for key in (card.get("repo") or "").split(",") if key.strip()]


def primary_repo(card: dict) -> str:
    keys = repos_of(card)
    if not keys:
        raise HostError(f"card {card['id']} has no repo")
    return keys[0]


def is_research(card: dict) -> bool:
    return str(option(card, "kind") or "").lower() == RESEARCH


def is_review(card: dict) -> bool:
    """A review card (c-730): it reviews someone else's change, filed by the drain from
    `review scan`, and opens, readies and pushes none of its own."""
    return bool(option(card, "review_key")) or str(option(card, "kind") or "").lower() == "review"


def is_tracking(card: dict) -> bool:
    return bool((card.get("derived") or {}).get("tracking"))


def code_card(card: dict) -> bool:
    """A card whose outcome is a change of its own."""
    return bool(repos_of(card)) and not (is_research(card) or is_tracking(card) or is_review(card))


def refuse_no_pr(card: dict) -> None:
    w = pack.words()
    if is_research(card):
        raise HostError(f"{card['id']} is a research card: its outcome is its record, not a {w.change}")
    if is_review(card):
        raise HostError(f"{card['id']} is a review card: it reviews someone else's {w.change} and opens none")


def unknown_state(repo, number: int) -> HostError:
    """A change in a state the host does not name: never read as open."""
    w = pack.words()
    return HostError(f"{w.host} did not say whether {w.change} #{int(number)} of {repo} is open, merged "
                     f"or closed, so it is not treated as open; try again")


# ----- git, always with a clock and never with a prompt -----

# c-738 r2.F2: no hook and no fsmonitor command a house could plant in its tree (`.git/hooks`,
# `git config core.hooksPath x`) runs inside a kit git call, which is made with the user's
# credentials, during the user's Approve or Ship among others.
NO_HOOKS = ("-c", "core.hooksPath=/dev/null", "-c", "core.fsmonitor=false")


def git(repo, *args: str, timeout: int = GIT_SECONDS) -> subprocess.CompletedProcess:
    """`git -C <repo> ...`, hooks off (`NO_HOOKS`). It never asks for a password (a push that
    would is refused by git and said), and one that does not finish is a refusal in words,
    never a traceback."""
    env = dict(os.environ, GIT_TERMINAL_PROMPT="0")
    try:
        return subprocess.run(["git", *NO_HOOKS, "-C", str(repo), *args], capture_output=True, text=True,
                              timeout=timeout, env=env)
    except subprocess.TimeoutExpired:
        raise HostError(f"git {args[0]} in {repo} gave no answer in {timeout} seconds") from None
    except OSError as error:
        raise HostError(f"git could not be run: {error.strerror or error}") from None


def fetch(repo, remote: str, *branches: str, timeout: int = GIT_SECONDS) -> subprocess.CompletedProcess:
    """Fetch these branches into the clone's remote-tracking refs, and nothing else: each
    is named in full (`refs/heads/<name>`), so no name can be read as an option or widen
    what is fetched."""
    specs = [f"+refs/heads/{ref_name(name)}:refs/remotes/{remote}/{name}" for name in branches]
    return git(repo, "fetch", "--quiet", remote, *specs, timeout=timeout)


def remote_head(card: dict, key: str, branch: str, timeout: int = GIT_SECONDS) -> str | None:
    """The commit the remote has at `branch` now, or None when it has no such branch."""
    ref = f"refs/heads/{ref_name(branch)}"
    said = git(repo_path(card, key), "ls-remote", remote_of(card), ref, timeout=timeout)
    if said.returncode != 0:
        why = (said.stderr.strip() or said.stdout.strip() or "git gave no reason").splitlines()[-1]
        raise HostError(f"the remote of {key} could not be read: {why}")
    for line in said.stdout.splitlines():
        parts = line.split()
        if len(parts) == 2 and parts[1] == ref:      # ls-remote matches a ref's tail too
            return parts[0]
    return None


# ----- the space's repos, and where each lives on the host -----

def repo_path(card: dict, key: str) -> Path:
    space = space_of(card)
    if key not in space.repos:
        raise HostError(f"the {space.name} space has no repo {key!r}")
    return Path(space.repos[key])


def remote_of(card: dict) -> str:
    """The git remote the space's repos fetch from and push to (`origin` unless it says)."""
    return getattr(space_of(card), "remote", None) or "origin"


def addresses(path: Path, remote: str = "origin") -> list[str]:
    """The remote's address as the clone's config writes it and as git resolves it (an
    `insteadOf` rule may make either the host's). Empty when the clone has no such remote."""
    written = git(path, "config", "--get", f"remote.{remote}.url").stdout.strip()
    resolved = git(path, "remote", "get-url", remote).stdout.strip()
    return [one for one in dict.fromkeys((written, resolved)) if one]


def clone_repo(path: Path, remote: str = "origin"):
    """`(Repo, "")` for a clone whose remote is on the bound pack's host, else `(None, why)`.
    Nothing is asked of the host."""
    if not (Path(path) / ".git").exists():
        return None, f"{path} is not a git clone on this machine"
    found = addresses(Path(path), remote)
    if not found:
        return None, f"{path} has no remote called {remote}"
    host = pack.host()
    repo = next((one for one in (host.address(address, Path(path)) for address in found) if one), None)
    return (repo, "") if repo else (None, host.elsewhere(found[0]))


def host_repo(card: dict, key: str):
    repo, why = clone_repo(repo_path(card, key), remote_of(card))
    if not repo:
        raise HostError(f"no {pack.host().name} repository for {key!r}: {why}")
    return repo


def space_repos(space) -> list[tuple[str, object]]:
    """`(key, Repo)` for each repo of the space whose remote is on the host."""
    remote = getattr(space, "remote", None) or "origin"
    found = []
    for key, path in space.repos.items():
        repo, _ = clone_repo(Path(path), remote)
        if repo:
            found.append((key, repo))
    return found


def default_branch(path: Path, remote: str = "origin") -> str | None:
    """The branch the remote calls its default, as the clone last recorded it."""
    found = git(path, "symbolic-ref", "--quiet", "--short", f"refs/remotes/{remote}/HEAD")
    name = found.stdout.strip()
    return name.split("/", 1)[1] if found.returncode == 0 and "/" in name else None


# ----- names read from a card, before any of them reaches git -----

@functools.lru_cache(maxsize=512)
def ref_name(value, what: str = "branch") -> str:
    """`value` as a branch name git accepts, or a refusal. Every branch and base a card (or
    the host) names goes through here ONCE, where it is read: a card's base is free text, and
    a name starting `-` would be read by git as an option, `+` or `:` as part of a refspec.
    The rest is git's own rule (`git check-ref-format --branch`)."""
    name = str(value)
    bad = f"{name!r} is not a branch name git accepts, so it cannot be this card's {what}"
    if not name or name[0] in "-:+" or any(char.isspace() for char in name) or name != name.strip():
        raise HostError(bad)
    if git(KIT, "check-ref-format", "--branch", name).returncode != 0:
        raise HostError(bad)
    return name


def base_option(card: dict) -> str | None:
    """The base the card itself names (`options.base`), checked, or None."""
    chosen = option(card, "base")
    return ref_name(chosen, "base") if chosen else None


# ----- the card's branch -----

def branch_for(card: dict) -> str:
    """The card's branch: named once (`options.branch`), by the space's own pattern
    (`[spaces.<name>] branch`, `keel/<id>-<slug>` unless it says)."""
    existing = option(card, "branch")
    if existing:
        return ref_name(existing)
    adapters = engine()
    pattern = getattr(space_of(card), "branch", None)
    return ref_name(adapters.branch_name(pattern, card["id"], adapters.slug(card.get("title") or "")))


def branch_in(card: dict, repo: str) -> str:
    entry = (option(card, "prs") or {}).get(repo)
    named = entry.get("branch") if isinstance(entry, dict) else None
    return ref_name(named) if named else branch_for(card)


# ----- a card's changes, one per repo -----

def prs_of(card: dict) -> list[dict]:
    """Every change the card carries, `{repo, pr, branch, primary}`, primary first:
    `options.prs` ({repo: {pr, branch}}), and `options.pr` for the primary repo."""
    keys, found = repos_of(card), {}
    recorded = option(card, "prs") or {}
    for repo, entry in (recorded.items() if isinstance(recorded, dict) else ()):
        if isinstance(entry, dict) and entry.get("pr"):
            found[repo] = {"pr": int(entry["pr"]), "branch": entry.get("branch")}
    if keys and keys[0] not in found and option(card, "pr"):
        found[keys[0]] = {"pr": int(option(card, "pr")), "branch": None}
    order = [key for key in keys if key in found] + sorted(key for key in found if key not in keys)
    return [{"repo": repo, "pr": found[repo]["pr"], "primary": index == 0,
             "branch": ref_name(found[repo]["branch"]) if found[repo]["branch"] else branch_for(card)}
            for index, repo in enumerate(order)]


def recorded_pr(card: dict, repo: str) -> int | None:
    return next((entry["pr"] for entry in prs_of(card) if entry["repo"] == repo), None)


def record_pr(card: dict, repo: str, number: int) -> dict:
    """The primary's number in `options.pr`; on a cross-repo card every one in
    `options.prs[repo]` with its branch. The card as it now stands."""
    options, keys = dict(card.get("options") or {}), repos_of(card)
    if keys and repo == keys[0] and options.get("pr") != number:
        KB.set_option(card["id"], "pr", number)
        options["pr"] = number
    if len(keys) > 1 or repo not in keys[:1]:
        prs = dict(options.get("prs") or {}) if isinstance(options.get("prs"), dict) else {}
        entry = {"pr": number, "branch": branch_in(card, repo)}
        if prs.get(repo) != entry:
            prs[repo] = entry
            KB.set_option(card["id"], "prs", prs)
            options["prs"] = prs
    return dict(card, options=options)


def worktree_of(card: dict, repo: str) -> Path | None:
    recorded = (option(card, "worktrees") or {}).get(repo)
    if recorded:
        return Path(str(recorded))
    keys = repos_of(card)
    if option(card, "worktree") and (not keys or keys[0] == repo):
        return Path(str(option(card, "worktree")))
    return None


def as_json(value) -> str:
    return json.dumps(value, sort_keys=True)
