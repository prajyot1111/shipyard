"""Adapter discovery and invocation, and the personal fallbacks.

A space with `pack = "<name>"` owns `packs/<name>/`, or with `adapter = "<name>"` the directory
of that name under `adapters_dir` (`keel/packs.py`, c-617), and its executables (`worktree`,
`brief`, `publish`) take the card id and read the card with `kb show <id> --json`. A space
without an adapter (personal) gets the built-in behaviour: `git worktree add` under
`<state_dir>/worktrees/` (or a cloned repo's own `trees/`, `keel/repolayout.py`), the space contract as the whole space half of the brief, and a
publish that does nothing. Its `repo` is a repo the config lists, or a project
discovered under the space's `projects_dir`, which `options.new_project` opens from
nothing. A cross-repo card (`repo` is a comma list) gets one worktree
per repo; the first is the house's cwd and the rest are `--add-dir`s.
"""

import json
import os
import re
import subprocess
from datetime import date
from pathlib import Path

from keel import config as config_module
from keel import bases, buildout, landpush, merging, packs, repocommands, repolayout, reviewround, settings, shipcheck, shipreplies
from keel.board import SHIPPING_OPTION
from keel.config import Config, Space

SLUG_MAX = 40
# The nonce of the user's tap (Approve outcome, Ship) that `Board.mark_publishing` keeps the digest of
# on the card: handed to the pack's `publish` only by `publisher(..., nonce=)`, so a pack on the
# kit runs `publish` only inside that tap (c-738 r1.F3); never inherited from Keel's own process.
NONCE_ENV = "KEEL_PUBLISH_NONCE"


class AdapterError(Exception):
    """The adapter or its verb is missing, or the verb failed; the message says which."""


# ----- adapter executables -----

def verb_path(space: Space, verb: str) -> Path | None:
    """`<adapter dir>/<verb>` when the space has an adapter and the verb exists."""
    if space.adapter_dir is None:
        return None
    path = space.adapter_dir / verb
    return path if path.is_file() and os.access(path, os.X_OK) else None


def has_verb(space: Space, verb: str) -> bool:
    return verb_path(space, verb) is not None


def adapter_env(space: Space | None = None, nonce: str | None = None) -> dict:
    """The adapter's environment: `KEEL_HOME` set and `kb` on PATH, and `KEEL_SPACE`, the
    space the verb runs for, where one is known (c-730): a pack may serve several spaces, and
    a verb with no card (the review scan, a provider, a route's verb) cannot read it off one.
    `NONCE_ENV` only when a tap's `nonce` is handed (c-738 r1.F3)."""
    home = config_module.repo_root()
    env = dict(os.environ)
    env["KEEL_HOME"] = str(home)
    env["PATH"] = f"{home / 'bin'}{os.pathsep}{env.get('PATH', '')}"
    env.pop("KEEL_SPACE", None)          # never one inherited from whoever started Keel
    env.pop(NONCE_ENV, None)
    if space is not None:
        env["KEEL_SPACE"] = space.name
    if nonce:
        env[NONCE_ENV] = nonce
    return env


def run(space: Space, verb: str, card_id: str, *args: str, timeout: float | None = None,
        stdin: str = "", nonce: str | None = None) -> str:
    """Execute `<adapter dir>/<verb> <card_id> <args...>` and return its stdout. With a
    `timeout`, a verb still running then is killed and refused. `nonce`: the user's tap's, for
    `publish` (c-738 r1.F3)."""
    if space.adapter_dir is None:
        raise AdapterError(f"space {space.name!r} has no adapter")
    if not space.adapter_dir.is_dir():
        raise AdapterError(f"adapter directory {space.adapter_dir} is missing")
    path = verb_path(space, verb)
    if path is None:
        raise AdapterError(f"adapter {space.adapter!r} has no executable {verb!r}")
    try:
        result = subprocess.run([str(path), card_id, *args], capture_output=True, text=True,
                                env=adapter_env(space, nonce), timeout=timeout, input=stdin)
    except subprocess.TimeoutExpired:
        raise AdapterError(f"{space.adapter}/{verb} {card_id} did not finish in {timeout:g} s "
                           f"and was stopped") from None
    if result.returncode != 0:
        raise AdapterError(f"{space.adapter}/{verb} {card_id} exited {result.returncode}: "
                           f"{result.stderr.strip() or result.stdout.strip()}")
    return result.stdout


# ----- JSON verbs: the providers, `act verbs`, `act links` -----

# The extra deck routes an adapter may ship under `providers/<route>`. A pack declares its own
# (`[capabilities] routes`, c-629); this is what an adapter with no `pack.toml` is asked for.
# One since lane RETIRE (RT-1): `reviews`, the review fetcher's settings for the Reviews
# page's gear. The pull request watcher's `prs` went with the PRs page; a work pull request
# is a card.
PROVIDER_ROUTES = ("reviews",)


def routes_of(space: Space) -> tuple[str, ...]:
    """The provider routes the space's adapter declares: its pack's, else the legacy list.
    A pack that fails to load declares none (the Setup page names its error)."""
    if space.adapter_dir is None:
        return ()
    try:
        pack = packs.at(space.adapter_dir)
    except packs.PackError:
        return ()
    return PROVIDER_ROUTES if pack is None else pack.routes


def run_json(argv: list[str], timeout: int = 60, space: Space | None = None) -> dict | list | None:
    """An adapter executable's JSON, or None when it fails, times out or prints no JSON."""
    try:
        result = subprocess.run(argv, capture_output=True, text=True, timeout=timeout,
                                env=adapter_env(space))
    except (OSError, subprocess.SubprocessError):
        return None
    if result.returncode != 0:
        return None
    try:
        return json.loads(result.stdout or "null")
    except ValueError:
        return None


def providers_for(space: Space, strict: bool = False) -> dict:
    """`providers/<route>` output for each route the adapter ships, keyed by route."""
    out = {}
    if space.adapter_dir is None:
        return out
    for route in routes_of(space):
        path = space.adapter_dir / "providers" / route
        if path.is_file() and os.access(path, os.X_OK):
            data = run_json([str(path)], space=space)
            if isinstance(data, dict):
                out[route] = data
            elif strict:
                # the deck's kept reading keeps its last good one instead (c-638)
                raise OSError(f"{path} answered no JSON object")
    return out


ACT_SECONDS = 180


def run_act(space: Space, route: str, action: str, key: str, args: dict):
    """`act do <route> <action> <key>` with `args` as JSON on stdin: a route or card verb the
    adapter owns. Its decoded answer, or `{"message": <text>}`; AdapterError when refused.

    A route-level verb (the scanner's own settings, say) acts on no row, so `key` may be
    empty; the adapter decides for itself whether it needs one."""
    path = verb_path(space, "act")
    if path is None:
        raise AdapterError(f"adapter {space.adapter!r} has no `act` executable")
    result = subprocess.run([str(path), "do", route, action, key], input=json.dumps(args or {}),
                            capture_output=True, text=True, env=adapter_env(space), timeout=ACT_SECONDS)
    if result.returncode != 0:
        raise AdapterError((result.stderr.strip() or result.stdout.strip() or "refused").splitlines()[-1])
    try:
        return json.loads(result.stdout or "null")
    except ValueError:
        return {"message": result.stdout.strip()}


# ----- the personal fallbacks -----

class ReadingFailed(Exception):
    """An adapter verb that failed, for a caller that keeps its last good reading (c-638)."""


def card_verbs(space: Space, strict: bool = False) -> dict:
    """`act verbs`: the card-level verbs the adapter offers, with their labels. `strict`
    raises `ReadingFailed` where the plain call answers no verbs."""
    path = verb_path(space, "act")
    if path is None:
        return {"card": []}
    data = run_json([str(path), "verbs"], space=space)
    if not isinstance(data, dict) and strict:
        raise ReadingFailed(f"{path} verbs answered no JSON object")
    return data if isinstance(data, dict) else {"card": []}


def card_links(space: Space, card_ids: list[str], strict: bool = False) -> dict:
    """`act links <id>...`: per card, the tracker story, the pull request and the doc.
    `strict` raises `ReadingFailed` where the plain call answers no links."""
    path = verb_path(space, "act")
    if path is None or not card_ids:
        return {}
    data = run_json([str(path), "links", *card_ids], space=space)
    if not isinstance(data, dict) and strict:
        raise ReadingFailed(f"{path} links answered no JSON object")
    return data if isinstance(data, dict) else {}


def repos_of(card: dict) -> list[str]:
    """The card's repo keys: one, or several from a comma list; empty for an errand."""
    return [key.strip() for key in (card.get("repo") or "").split(",") if key.strip()]


def slug(title: str) -> str:
    words = re.sub(r"[^a-z0-9]+", "-", title.lower()).strip("-")
    return words[:SLUG_MAX].rstrip("-") or "card"


def git(repo: Path, *args: str) -> str:
    result = subprocess.run(["git", "-C", str(repo), *args], capture_output=True, text=True)
    if result.returncode != 0:
        raise AdapterError(f"git {' '.join(args)} in {repo}: {result.stderr.strip()}")
    return result.stdout


# A card's branch in a space with no pack: `[spaces.<name>] branch` (c-665), `shipyard/<id>-<slug>`
# unless the space says. `keel/settings.py` holds the pattern to a name git takes with `{id}`
# in it. The default was `keel/<id>-<slug>` until c-729 (a stranger's repo history read
# keel/), and a card cut under it is still found (`card_branch`), so no card is cut twice.
BRANCH = settings.default("space", "branch")
LEGACY_BRANCH = "keel/{id}-{slug}"


def branch_name(pattern: str | None, card_id: str, words: str) -> str:
    """The pattern with the card's id and its slug filled in."""
    return (pattern or BRANCH).replace("{id}", card_id).replace("{slug}", words)


def existing_branch(repo: Path, card_id: str, pattern: str | None = None) -> str | None:
    """A branch already cut for this card under the space's pattern (`keel/<id>-*` by
    default: the slug is any), so a recreate reuses it. The glob asks git. Under a pattern
    of the space's own a name counts only when it is the WHOLE pattern with a slug of one
    path part, since git's glob also takes a name the pattern is a leading directory of
    (`c-1/other` for `{id}`). The default pattern is read as it always was."""
    out = git(repo, "for-each-ref", "--format=%(refname:short)",
              f"refs/heads/{branch_name(pattern, card_id, '*')}")
    names = [line.strip() for line in out.splitlines() if line.strip()]
    if (pattern or BRANCH) != BRANCH:
        whole = re.compile("[^/]+".join(re.escape(part) for part in
                                        pattern.replace("{id}", card_id).split("{slug}")))
        names = [name for name in names if whole.fullmatch(name)]
    return names[0] if names else None


def card_branch(repo: Path, card: dict, pattern: str | None = None) -> str | None:
    """The branch this card already has here: under the pattern in force, then under the
    default when that is not it, so a card cut before its space changed its pattern is found
    (c-665 review), and last under the default before c-729 (`LEGACY_BRANCH`), so a card cut
    as keel/<id>-... keeps its branch. Never cut a second time."""
    found = existing_branch(repo, card["id"], pattern)
    if not found and (pattern or BRANCH) != BRANCH:
        found = existing_branch(repo, card["id"])
    return found or existing_branch(repo, card["id"], LEGACY_BRANCH)


def git_worktree(repo: Path, directory: Path, card: dict, start=None, pattern: str | None = None) -> Path:
    """`git worktree add`, reusing the branch and the directory when they already exist. A
    new branch is named by `pattern` (the space's `branch`) and starts at what `start()`
    names when it is given (the integration branch), else at HEAD; it is asked only when a
    branch is cut, so an existing worktree never waits on a remote."""
    if (directory / ".git").exists():
        merging.link_venv(repo, directory)
        return directory
    git(repo, "worktree", "prune")
    directory.parent.mkdir(parents=True, exist_ok=True)
    branch = card_branch(repo, card, pattern)
    if branch:
        git(repo, "worktree", "add", str(directory), branch)
    else:
        branch = branch_name(pattern, card["id"], slug(card["title"]))
        at = start() if start else None
        git(repo, "worktree", "add", str(directory), "-b", branch, *([at] if at else []))
    # The voice selftest needs the live checkout's venv; linked in, a house's own `make test`
    # runs voice instead of skipping it (2026-09-26: houses learned of a voice break only at
    # the landing or the deploy). A repo without one is untouched.
    merging.link_venv(repo, directory)
    return directory


def start_point(cfg: Config, space: Space, key: str, repo: Path, card: dict | None = None) -> str | None:
    """Where a new card branch starts (c-526, his D1): every card on a repo with an
    integration branch builds from it, so a card sees the approved work it will land beside.
    Before anything has landed on it, the trunk (None, HEAD). A card that names its own base
    starts from that base (c-732), where it will land, unless the repo has an integration
    branch, which a card's own base never overrides (r1.F4, `merging.card_base`). Any other
    card starts from the repo's usual branch (c-734, `merging.usual_branch`): the remote's
    default in a copy whatever it has out, the checkout's own branch elsewhere (None, HEAD)."""
    base = merging.card_base(cfg, card or {}, key)
    if base:
        return base_point(cfg, space, key, repo, base)
    target = cfg.integration_of(space.name, key)
    if not target:
        usual = usual_of(cfg, space, key, repo)
        try:
            out = merging.trunk_of(repo)
        except merging.MergeRefused:
            out = None
        return None if usual in (None, out) else base_point(cfg, space, key, repo, usual)
    try:
        return f"refs/heads/{target}" if merging.ref_head(repo, target) else None
    except merging.MergeRefused as error:
        raise AdapterError(f"{target} could not be read from {repo}, so no card branch is cut "
                           f"from a guess: {str(error).splitlines()[0]}") from None


def cut_point(cfg: Config, space: Space, key: str, repo: Path, card: dict) -> str | None:
    """`start_point`, asked only when a branch is cut, and for a card that starts from the
    repo's usual branch (no base of its own, no integration branch) that branch recorded on
    the card (`options.cut_from`, r2.F1): fetch before work follows a team that moves its
    default, and the card must still land where it was cut (`merging.landing_target`)."""
    point = start_point(cfg, space, key, repo, card)
    if not merging.card_base(cfg, card, key):
        record_cut_from(cfg, card, key, usual_of(cfg, space, key, repo))
    return point


def record_cut_from(cfg: Config, card: dict, key: str, branch: str | None) -> None:
    """`options.cut_from[key] = branch` on the card. Never fails the cut: a card that is not
    on this board, or a branch that was not read (None), records nothing."""
    if not branch:
        return
    from keel.board import Refused, open_board     # noqa: PLC0415 - the board reads this module
    try:
        with open_board(cfg) as board:
            had = (board.get(card["id"]).get("options") or {}).get(merging.CUT_FROM)
            found = {**(had if isinstance(had, dict) else {}), key: branch}
            board.set_fields(card["id"], {"options": {merging.CUT_FROM: found}}, "drain")
    except (Refused, KeyError, OSError):
        pass


def base_point(cfg: Config, space: Space, key: str, repo: Path, base: str) -> str:
    """The card's own base here (c-732): the copy's branch of that name, else the remote's as
    last fetched, else a refusal that names it. Never a guess, and never a name git would read
    as a revision (r1.F12, `bases.branch_problem`)."""
    problem = bases.branch_problem(base)
    if problem:
        raise AdapterError(f"this card's base was not used: {problem}")
    for ref in (f"refs/heads/{base}", f"refs/remotes/{landpush.remote_of(cfg, space.name)}/{base}"):
        if merging.has_ref(repo, ref):
            return ref
    raise AdapterError(f"{key} has no branch called {base}, on this computer or on "
                       f"{landpush.remote_of(cfg, space.name)}, so this card was not started. Pick one of "
                       f"{key}'s branches as its base, or leave Base branch empty.")


# ----- a repo the config does not list: a project under the space's projects_dir -----

DEFAULT_BRANCH = "main"
README = "README.md"


def new_project_wanted(card: dict) -> bool:
    """True when the card asked for a repository that is not there yet.

    It is an explicit option rather than an inference from the missing directory, so a
    misspelt repo name refuses instead of scaffolding a project nobody meant to open.
    """
    return bool((card.get("options") or {}).get("new_project"))


def scaffold(directory: Path, card: dict) -> Path:
    """`git init -b main`, a README naming the card, and the first commit.

    The identity is the human's global one: a repo-local `user.name` would stamp a name
    nobody owns on every commit this project ever takes.
    """
    directory.mkdir(parents=True, exist_ok=True)
    git(directory, "init", "-b", DEFAULT_BRANCH)
    (directory / README).write_text(
        f"# {directory.name}\n\n{card.get('title') or directory.name}\n\n"
        f"Opened by Keel for card {card['id']} on {date.today().isoformat()}.\n")
    git(directory, "add", README)
    git(directory, "commit", "-m", f"Start {directory.name}: opened for {card['id']}")
    return directory


def project_repo(space: Space, path: Path, key: str, card: dict) -> Path:
    """A discovered project's directory, scaffolded when the card asked for a new one.

    Three answers, and only one of them creates anything: a git repo is used as it is, a
    missing directory is scaffolded when the card carries `options.new_project` and
    refused otherwise, and a directory that is not a repo is always a refusal.
    """
    if (path / ".git").exists():
        return path
    if path.exists():
        raise AdapterError(f"{path} exists but is not a git repository (card {card['id']})")
    if not new_project_wanted(card):
        raise AdapterError(
            f"space {space.name!r} has no repo {key!r} and {path} does not exist; create the "
            f"card with `kb create --new-project {key}` to open it, or fix the name "
            f"(card {card['id']})")
    return scaffold(path, card)


def repo_for(space: Space, key: str, card: dict) -> Path:
    """The repository the card's `repo` key names, opening a new project when it asked."""
    path = space.repo_path(key)
    if path is None:
        if space.projects_dir is None:
            raise AdapterError(f"space {space.name!r} has no repo {key!r} and no projects "
                               f"directory to open one in (card {card['id']})")
        raise AdapterError(f"{key!r} is not a repo of the {space.name} space and not a plain "
                           f"project name (card {card['id']})")
    if key in space.repos:
        return path
    return project_repo(space, path, key, card)


def worktree_dirs(cfg: Config, card: dict) -> list[Path]:
    """`<state_dir>/worktrees/<id>` for the first repo, `<id>-<repo>` for the others; a repo
    an install cloned into its layout cuts at its own `<key>/trees/<id>` (c-618,
    `keel/repolayout.py`), where the repo's tiers sit above the worktree."""
    space = cfg.spaces.get(card.get("space"))
    dirs = []
    for index, key in enumerate(repos_of(card)):
        repo = space.repo_path(key) if space is not None else None
        dirs.append(repolayout.tree_of(repo, card["id"], repolayout.spaces_of(cfg))
                    or cfg.worktrees_dir / (card["id"] if index == 0 else f"{card['id']}-{key}"))
    return dirs


def personal_worktrees(cfg: Config, space: Space, card: dict) -> list[Path]:
    paths = []
    for key, directory in zip(repos_of(card), worktree_dirs(cfg, card)):
        repo = repo_for(space, key, card)
        fresh = not (directory / ".git").exists()
        if fresh:
            # c-678: the card builds on what the team has. Never a refusal: what a fetch
            # could not do is a sentence on the card (and in its brief, review F6), and the
            # card builds on what this computer has.
            say_on_card(cfg, card, landpush.fetch_first(cfg, space, key, merging.card_base(cfg, card, key)
                                                        or usual_of(cfg, space, key, repo)))
        paths.append(git_worktree(repo, directory, card,
                                  lambda: cut_point(cfg, space, key, repo, card), space.branch))
        if fresh:
            prepare_fresh(cfg, space, key, repo, directory, card)
    return paths


def usual_of(cfg: Config, space: Space, key: str, repo: Path) -> str | None:
    """The branch a card naming no base starts from, for fetch before work to move up as it
    moves a base (c-734): None on a repo with an integration branch, or when it is not read."""
    if cfg.integration_of(space.name, key):
        return None
    try:
        return merging.usual_branch(cfg, space.name, repo)
    except merging.MergeRefused:
        return None


CUT = "cut"         # the data of a note left while a card's worktree was cut: the brief repeats it


def say_on_card(cfg: Config, card: dict, said: str | None) -> None:
    """One sentence about the cut, as a note on the card (`house.cut_block` puts it in the
    brief). Saying it never fails the cut: a card that is not on this board gets no note."""
    if not said:
        return
    from keel.board import Refused, open_board     # noqa: PLC0415 - the board reads this module
    try:
        with open_board(cfg) as board:
            board.note(card["id"], said, "drain", data={CUT: True})
    except (Refused, KeyError, OSError):
        pass


def prepare_fresh(cfg: Config, space: Space, key: str, repo: Path, directory: Path, card: dict) -> None:
    """The repo's prepare command in a worktree that was just cut (c-678: the "Prepare a fresh
    copy" line of its adopted CLAUDE.md, `keel/repocommands.py`), so a session starts in a
    copy that can run the tests. One that fails refuses the cut, and the worktree is taken
    back out (its branch stays), so the next try cuts and prepares again."""
    command = repocommands.prepare_of(cfg, space.name, key)
    if not command:
        # review F3: a file that changed since it was adopted runs nothing, and the card says so
        say_on_card(cfg, card, repocommands.changed(cfg, space.name, key))
        return
    try:
        repocommands.prepare(command, directory)
    except repocommands.PrepareFailed as failed:
        try:
            git(repo, "worktree", "remove", "--force", str(directory))
        except AdapterError:
            pass
        raise AdapterError(f"could not prepare a fresh copy of {key}: {failed}") from None


# ----- the three verbs, adapter or fallback -----

def space_of(cfg: Config, card: dict) -> Space:
    try:
        return cfg.spaces[card["space"]]
    except KeyError:
        raise AdapterError(f"card {card['id']} is in unknown space {card['space']!r}") from None


def worktree(cfg: Config, card: dict) -> list[Path]:
    """One path per repo; the adapter prints them, the fallback cuts them with git."""
    space = space_of(cfg, card)
    if not repos_of(card):
        return []
    for key in repos_of(card):
        # c-729: each cut reconciles a copy with its space (`landpush.fence`): fenced with no
        # pack, pushable with one, whatever changed the config
        landpush.fence(cfg, space.name, key)
        buildout.reconcile(cfg, space.name, key)     # c-734: build output is never added
    if space.adapter_dir is None:
        return personal_worktrees(cfg, space, card)
    out = run(space, "worktree", card["id"])
    paths = [Path(line.strip()) for line in out.splitlines() if line.strip()]
    if not paths:
        raise AdapterError(f"{space.adapter}/worktree {card['id']} printed no path")
    return paths


def contract_text(space: Space) -> str:
    return space.contract.read_text() if space.contract and space.contract.is_file() else ""


def brief(cfg: Config, card: dict) -> str:
    """The space half of the brief: the contract, then (with an adapter) `brief <id>`."""
    space = space_of(cfg, card)
    parts = [contract_text(space)]
    if space.adapter_dir is not None and has_verb(space, "brief"):
        parts.append(run(space, "brief", card["id"]))
    return "\n\n".join(part.strip() for part in parts if part.strip())


def publish(cfg: Config, card: dict, timeout: float | None = None, anyway: bool = False,
            nonce: str | None = None) -> str | None:
    """`publish <id>` for a space with an adapter; a no-op (None) without one.

    A card at shipping is his Ship (c-600): the adapter is handed `--answer` on stdin with
    the replies he kept and has not posted yet (`shipreplies.ship_answer`), and pushes,
    readies and posts. A review card (lane RC) is handed what to post
    (`reviewround.answer_for`): the findings he kept, the summary and the verdict. His picks
    that cannot go refuse here, before the adapter runs, so nothing is pushed or posted. So
    does a Ship the worktrees do not bear out NOW (`keel/shipcheck.py`): nothing to ship, the
    house in a turn, or commits no receipt covers, the last two unless he said `anyway`.

    In a space whose pack does not declare a code host, a repo card is refused first, with
    the sentence its readiness row says (c-631, decision `publish-without-codehost`), so a
    space with an integration never has a branch merged by surprise; a card with no repo has
    nothing to publish there, and closes. A space with no pack is not refused here: its
    `publisher` merges locally, as it always has."""
    space = space_of(cfg, card)
    if space.adapter_dir is None:
        return None
    from keel import readiness     # noqa: PLC0415 - readiness reaches this module through health
    refused = readiness.refusal(cfg, space, "codehost")
    if refused and repos_of(card):
        raise AdapterError(refused)
    if refused:
        return None
    try:
        answer = reviewround.answer_for(cfg, card) or ship_answer(cfg, card)
    except reviewround.ReviewRefused as refused:
        raise AdapterError(str(refused)) from None
    if answer is not None and answer.get("ship"):
        try:
            shipcheck.check(cfg, card, answer, anyway)
        except shipcheck.ShipRefused as refused:
            raise AdapterError(str(refused)) from None
    if answer is None:
        return run(space, "publish", card["id"], timeout=timeout, nonce=nonce).strip()
    return run(space, "publish", card["id"], "--answer", timeout=timeout,
               stdin=json.dumps(answer), nonce=nonce).strip()


def ship_answer(cfg: Config, card: dict) -> dict | None:
    """His Ship's answer for a card at shipping, from the board's own record; None otherwise."""
    if card.get("stage") != "shipping":
        return None
    from keel.board import open_board
    board = open_board(cfg)
    try:
        events = board.events(card["id"], last=0)
        fresh = board.get(card["id"])
    finally:
        board.close()
    return shipreplies.ship_answer(fresh, events)


DENY_SECONDS = 30


def extra_deny(cfg: Config, card: dict) -> list[str]:
    """`deny <id>` (the card as JSON on stdin): permission deny entries the adapter adds for
    THIS card, merged into its house's settings (`house.settings_for`). The work adapter
    uses it to take pushing and pull requests away from a research card. Empty when the
    space has no adapter or the adapter has no such verb; a verb that fails or prints
    something other than a list of strings is refused, so a house is never started without
    the fence it was meant to have."""
    space = space_of(cfg, card)
    if not has_verb(space, "deny"):
        return []
    out = run(space, "deny", card["id"], timeout=DENY_SECONDS, stdin=json.dumps(card))
    try:
        entries = json.loads(out or "[]")
    except ValueError:
        entries = None
    if not isinstance(entries, list) or not all(isinstance(entry, str) for entry in entries):
        raise AdapterError(f"{space.adapter}/deny {card['id']} did not print a list of deny entries")
    return entries


PUBLISHABLE_SECONDS = 90


def publishable(cfg: Config, card: dict) -> str | None:
    """`publishable <id>` (the card as JSON on stdin), asked before a card reaches his outcome
    gate (c-551): None when his Approve could publish it, else the adapter's one line saying
    what is missing. Always None for a space with no adapter or no such verb, and for a card
    that has already shipped: its pull request exists, and what the house commits at shipping
    is pushed by his Ship. A verb that fails or answers something else is refused, so a
    gate is never opened on a check that did not run."""
    space = space_of(cfg, card)
    if not has_verb(space, "publishable") or (card.get("options") or {}).get(SHIPPING_OPTION):
        return None
    out = run(space, "publishable", card["id"], timeout=PUBLISHABLE_SECONDS, stdin=json.dumps(card))
    try:
        answer = json.loads(out or "null")
    except ValueError:
        answer = None
    if not isinstance(answer, dict) or not isinstance(answer.get("publishable"), bool):
        raise AdapterError(f"{space.adapter}/publishable {card['id']} did not answer publishable")
    return None if answer["publishable"] else str(answer.get("missing") or "not publishable")


def publisher(cfg: Config, space_name: str, anyway: bool = False, nonce: str | None = None,
              timeout: float | None = None):
    """The `publish` callable `Board.approve` takes: the adapter's `publish` for a space
    with one, handed the user's tap's `nonce` (c-738 r1.F3) and stopped after `timeout`
    seconds (the tap's budget, r2.F3), the merge of the card's branch (`keel.merging`) for
    a personal repo card."""
    space = cfg.spaces.get(space_name)
    if space is None:
        return None
    if space.adapter_dir is None:
        return lambda card: merging.publish(cfg, card)
    return lambda card: publish(cfg, card, timeout=timeout, anyway=anyway, nonce=nonce)


def publishes_through_pack(cfg: Config, space_name: str) -> bool:
    """Whether Approve outcome in this space runs a pack's `publish`, so the user's tap is marked
    on the card first and its nonce handed to the verb (c-738 r1.F3)."""
    space = cfg.spaces.get(space_name)
    return space is not None and space.adapter_dir is not None
