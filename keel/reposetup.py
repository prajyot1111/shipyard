"""Add your repos: the copy, the attach, the space, the remove (c-618, c-632, c-678).

The verbs of the Setup view and the first run that put a repo under a space or take one
off. `keel/onboarding.py` holds the view's report, the tiers and the table of verbs; this is
the part that touches git and the config for a repo (moved out of it in c-678, when the two
together passed the size a module is kept to).

- `clone_repo` (`setup.repo.clone`): `git clone` into the layout (`keel/repolayout.py`), the
  space and repo tiers written from `etc/claude-md/` where absent, the repo listed. A
  failure leaves nothing behind, and its refusal carries the failure sorted into a kind
  (`keel/cloneerrors.py`). An address that carries a password is refused before anything is
  copied, and no refusal echoes the user part of an address.
- `add_repo` (`setup.repo.add`): the space made when it is not there, the key filled from
  the address, then `clone_repo`. A copy that fails takes the space it made back out.
- `attach_repo` (`setup.repo.attach`): an existing checkout listed where it is.
- `add_space` (`setup.space.add`): a plain space, with fetch before work and offer Push
  written on (they default off, so only a space made here gets them).
- `remove_repo` (`setup.repo.remove`): the config entry only, refused while an open card
  names the repo (`naming`).

Each refuses a config that is not an install's (`setupconfig.install_of`). A draft card is
the caller's to file (`drafted`): this module knows no board but the one `remove_repo` and
`naming` are handed.
"""

from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

from keel import atomicfile, cloneerrors, configedit, repolayout
from keel import config as config_module
from keel.config import Config
from keel.setupconfig import SetupError, claude_dir, edit, install_of, name_of, space_of

CLONE_SECONDS = 600
PASSWORD = ("That address carries a password, and Shipyard keeps no password in an address. Sign in with the code "
            "host's own tool or a credential helper, then give the address without it.")
CLONING = ".repo.cloning"


def git_clone(url: str, into: Path) -> None:
    env = {**os.environ, "GIT_TERMINAL_PROMPT": "0"}
    shown = cloneerrors.shown_address(url)      # an address is never echoed with its user part (F13)
    try:
        done = subprocess.run(["git", "clone", "--quiet", "--", url, str(into)], capture_output=True,
                              text=True, timeout=CLONE_SECONDS, env=env)
    except subprocess.TimeoutExpired:
        raise SetupError(f"git clone {shown} took over {CLONE_SECONDS}s and was stopped") from None
    if done.returncode != 0:
        detail = cloneerrors.sort(url, done.stderr)
        raise CloneFailed(f"git clone {shown} failed: {detail['git']}", detail)


class CloneFailed(SetupError):
    """A `git clone` that failed, with the failure sorted into a kind (`keel/cloneerrors.py`):
    `detail` rides to the page beside the sentence (`actions.act_setup`, c-678)."""

    def __init__(self, said: str, detail: dict):
        super().__init__(said)
        self.detail = detail


def ensure_tier(path: Path, root: Path, name: str, **words: str) -> None:
    if not path.exists():
        atomicfile.write_text(path, repolayout.template(root, name, **words))


def clone_repo(cfg: Config, space: str, key: str, url: str, drafted=None) -> dict:
    """Clone `url` to `<install>/spaces/<space>/<key>/repo` and list it. A failure leaves
    nothing behind: no half clone, no folder it made, no config entry. `drafted(cfg, space,
    key, repos)` files the draft card for a CLAUDE.md and answers its id or None
    (`onboarding.leave_draft`, c-678): the caller's, since a draft is a card and this
    module knows no board."""
    home = install_of(cfg)
    found = space_of(cfg, space)
    name_of(key, "repo key")
    if key in found.repos:
        raise SetupError(f"{space} already lists {key} at {found.repos[key]}")
    url = (url or "").strip()
    if not url or url.startswith("-"):
        raise SetupError("a clone needs the repo's URL (or a path git can clone)")
    if cloneerrors.has_password(url):
        raise SetupError(PASSWORD)
    folder = repolayout.repo_home(home, space, key)
    repo = folder / repolayout.REPO
    if repo.exists():
        raise SetupError(f"{repo} is already there; pick another key, or remove that folder")
    made = not folder.exists()
    folder.mkdir(parents=True, exist_ok=True)
    try:
        shutil.rmtree(folder / CLONING, ignore_errors=True)
        git_clone(url, folder / CLONING)
        (folder / CLONING).rename(repo)
        done = edit(cfg, lambda text: configedit.set_entry(text, f"spaces.{space}.repos", key, str(repo)))
    except BaseException:
        shutil.rmtree(folder if made else folder / CLONING, ignore_errors=True)
        if not made:
            shutil.rmtree(repo, ignore_errors=True)
        raise
    ensure_tier(repolayout.space_dir(home, space) / repolayout.TIER, cfg.root, "space", space=space)
    ensure_tier(folder / repolayout.TIER, cfg.root, "repo", space=space, key=key)
    # c-729, point 17: a copy lands by the merge here, so its remote is made unpushable
    # (`landpush.fence`); read from the config as written, which lists the new repo
    from keel import buildout, landpush     # noqa: PLC0415 - landpush reads merging, which is heavy
    written = config_module.load(cfg.source, ensure=False)
    landpush.fence(written, space, key)
    buildout.reconcile(written, space, key)     # c-734: build output is never added

    # c-678: with a second repo the space has something to say across them, so its own file
    # gets a draft card too (once: `open_draft` files none while one is open)
    others = [path for one, path in found.repos.items() if one != key and repolayout.home_of(path, home / repolayout.SPACES)]
    draft = drafted or (lambda *_: None)
    return {**done, "cloned": key, "space": space, "repo": str(repo),
            "draft": draft(cfg, space, key, [repo]),
            "workspace": draft(cfg, space, None, [*others, repo]) if others else None}


def with_space(cfg: Config, space: str) -> tuple[Config, str | None]:
    """The config with `space` in it: as it is, or read again after the space was added
    (c-678: a repo's first add names its space). Also the config's text from before, for the
    caller that takes the space back out when what it came for failed; None when the space
    was already there."""
    if space in cfg.spaces:
        return cfg, None
    before = Path(cfg.source).read_text()
    add_space(cfg, space)
    return config_module.load(cfg.source, ensure=False), before


def add_repo(cfg: Config, space: str, url: str, key: str = "", drafted=None) -> dict:
    """Add your repos (c-678): the space made when it is not there, then the repo cloned into
    the layout under `key`, or under the name its address suggests. A copy that fails leaves
    nothing behind, the space it made included."""
    install_of(cfg)
    url = (url or "").strip()
    if not url or url.startswith("-"):
        raise SetupError("a repo needs the repo's address (the URL you would give to git clone)")
    if cloneerrors.has_password(url):
        raise SetupError(PASSWORD)
    if url.startswith("~"):
        # c-729: a folder on this computer, typed as a shell would take it; git does not
        url = str(Path(url).expanduser())
    key = key.strip() or cloneerrors.short_name(url)
    if not key:
        raise SetupError(f"{url} names no repo: give it a short name")
    name_of(key, "short name")
    name_of(space, "space name")
    held, before = with_space(cfg, space)
    try:
        return clone_repo(held, space, key, url, drafted)
    except BaseException:
        if before is not None:
            edit(held, lambda text: before)
        raise


def attach_repo(cfg: Config, space: str, key: str, path: str) -> dict:
    """List an existing checkout under the space's repos, where it is (c-632), as `shipyard
    import` lists them: outside the layout the tiers do not load, and Remove takes it off
    again. Refused for a path with no `.git` and for one inside another install's layout.
    The space is made when it is not there (c-678), and taken back when the attach is refused."""
    install_of(cfg)
    name_of(space, "space name")
    held, before = with_space(cfg, space)
    try:
        return attach_listed(held, space, key, path)
    except BaseException:
        if before is not None:
            edit(held, lambda text: before)
        raise


def attach_listed(cfg: Config, space: str, key: str, path: str) -> dict:
    home = install_of(cfg)
    found = space_of(cfg, space)
    name_of(key, "repo key")
    if key in found.repos:
        raise SetupError(f"{space} already lists {key} at {found.repos[key]}")
    text = (path or "").strip()
    if not text:
        raise SetupError("attach needs the checkout's path")
    repo = Path(text).expanduser()
    if not repo.is_absolute():
        raise SetupError(f"{text} is not an absolute path")
    repo = repo.resolve()
    if not (repo / ".git").exists():
        raise SetupError(f"{repo} holds no .git, so it is not a checkout")
    other = foreign_layout(repo, home)
    if other is not None:
        raise SetupError(f"{repo} is inside the install at {other}; attach a checkout of your own")
    if repolayout.in_tree(repo, home / repolayout.SPACES):
        raise SetupError(f"{repo} is a card's worktree, not a checkout")
    done = edit(cfg, lambda text: configedit.set_entry(text, f"spaces.{space}.repos", key, str(repo)))
    note = f"{key} is listed at {repo}"
    if repolayout.home_of(repo, home / repolayout.SPACES) is None:
        note += "; it is outside this install's layout, so the tiers do not load there"
    return {**done, "attached": key, "space": space, "repo": str(repo), "note": note}


def foreign_layout(path: Path, home: Path) -> Path | None:
    """The other install whose `spaces/` holds `path`, or None."""
    for parent in path.parents:
        if parent.name == repolayout.SPACES and (parent.parent / "config.toml").is_file() \
                and parent.parent.resolve() != Path(home).resolve():
            return parent.parent
    return None


def add_space(cfg: Config, space: str) -> dict:
    """A plain space served here (c-632): the install's Claude dir and no repos. A pack is
    put on it after, by Turn on (`packsetup.pack_on` adopts it).

    WHILE THE FIRST RUN IS NOT FINISHED its table says fetch before work and offer Push, both
    on (c-678 review F1, r2.F1): they default off, so that only a space the first run makes
    gets them, and Where finished work goes shows both as switches. A space added from Setup
    on a finished install gets neither, as every other space of that install has neither;
    the note above the table says where it was added from."""
    from keel import firstrun     # noqa: PLC0415 - firstrun reads onboarding, which reads this module
    install_of(cfg)
    name_of(space, "space name")
    if space in cfg.spaces:
        raise SetupError(f"there is already a space {space!r}")
    first = firstrun.stored(cfg).get("finished") is None
    table = {"config_dir": str(claude_dir(cfg))}
    if first:
        table.update(fetch_before_work=True, offer_push=True)
    note = ("Added in the deck's first run" if first else "Added from Setup") + " (docs/atlas/89-onboarding.md)."
    done = edit(cfg, lambda text: configedit.append_table(text, f"spaces.{space}", table, note))
    return {**done, "space": space, "note": f"the {space} space is added"}


def naming(board, space: str, key: str) -> list[str]:
    """The open cards (not done, not archived) of `space` whose repo names `key`."""
    return [card["id"] for card in board.list_cards(space=space, include_archived=False)
            if card.get("stage") != "done"
            and key in [part.strip() for part in str(card.get("repo") or "").split(",")]]


def remove_repo(cfg: Config, board, space: str, key: str) -> dict:
    """Take `key` off the space's repos; the folder and its tier stay where they are. Refused
    while an open card names it: its house, merge and worktree would lose their repo."""
    found = space_of(cfg, space)
    if key not in found.repos:
        raise SetupError(f"{space} lists no repo {key!r}")
    held = naming(board, space, key)
    if held:
        raise SetupError(f"{', '.join(held)} still name {key}; finish or archive them first")
    done = edit(cfg, lambda text: configedit.remove_entry(text, f"spaces.{space}.repos", key))
    return {**done, "removed": key, "space": space,
            "note": f"{key} is no longer listed; its folder {found.repos[key]} stays"}


