"""Which branches are shared, and so never a card's own: nothing on the kit cuts a card on
one, pushes one, or opens a change from one.

A branch is shared when ANY of these says so, asked in this order:

1. **a usual shared name**: `SHARED` exactly, or a name under `release/` or `hotfix/`;
2. **the card's base**: the branch its work merges into;
3. **the host's default branch** of the repository, read from the host (the layer's
   `default_branch`, once a process), never from the clone, whose record of it is missing
   after `git remote add` and stale after a rename;
4. **protected on the host**: the host reports a branch protection on it, whatever its name.

A default branch or a protection that CANNOT be read is a refusal too: nothing is pushed on
a guess, and `main` is never assumed. A branch the host has never heard of (a card's new
branch before its first push) is not protected.

**The base** (`base_in`) is the card's `options.base` when it names one, else the
repository's default branch, and where that is read depends on the verb:

- a verb that WRITES (the cut, the draft, Ship) asks the host and takes no other answer: a
  card is never cut from, and a change never opened into, a branch the host no longer calls
  the default;
- a verb that only READS (the brief, the diff, how far behind) asks the host first, with a
  short clock (`READ_SECONDS`), and when the host cannot say in that time falls back to the
  clone's record, since a stale name there costs a wrong sentence and not a wrong push, and
  a read is never worth waiting half a minute for.

This is the kit's own refusal, before it acts. The hard boundary for a shared branch is
still the repository's own branch protection on the host.
"""

from keel.packkit import card as gc
from keel.packkit import pack
from keel.packkit.errors import HostError

SHARED = frozenset(("main", "master", "trunk", "develop", "development", "staging", "production",
                    "release"))
SHARED_UNDER = ("release/", "hotfix/")
NEVER = "this pack never pushes it, never cuts a card on it and never opens a {change} from it"
ON_A_GUESS = "so nothing is cut, pushed or opened on a guess; try again"
READ_SECONDS = 5                    # how long a verb that only reads waits for the host
SECONDS = 30                        # how long a verb that writes waits: one call's whole clock
_defaults: dict[tuple, str] = {}    # a repository's default branch, asked once a process


def forget() -> None:
    _defaults.clear()


def base_in(card: dict, key: str, writing: bool = False) -> str:
    """The branch a card's work in one repo merges into: `options.base`, else the
    repository's default branch. A verb that writes takes the host's answer or refuses; one
    that only reads may fall back to the clone's record (the module docstring says why)."""
    chosen = gc.base_option(card)
    if chosen:
        return chosen
    try:
        return gc.ref_name(host_default(card, key, SECONDS if writing else READ_SECONDS), "base")
    except HostError:
        recorded = None if writing else gc.default_branch(gc.repo_path(card, key), gc.remote_of(card))
        if not recorded:
            raise
        return gc.ref_name(recorded, "base")


def host_default(card: dict, key: str, seconds: int = SECONDS) -> str:
    repo = gc.host_repo(card, key)
    if (repo.base, str(repo)) not in _defaults:
        try:
            _defaults[repo.base, str(repo)] = pack.layer().default_branch(repo, timeout=seconds)
        except HostError as error:
            raise HostError(f"{pack.host().name} could not say which branch of {repo} is its default "
                            f"({error}), {ON_A_GUESS}") from None
    return _defaults[repo.base, str(repo)]


def why_shared(card: dict, key: str, branch: str) -> str | None:
    """Why `branch` is shared in this repo, or None. Raises when the host cannot be asked."""
    if branch in SHARED or branch.startswith(SHARED_UNDER):
        return "a usual shared name"
    if branch == gc.base_option(card):
        return "the card's base"
    repo, host = gc.host_repo(card, key), pack.host()
    if branch == host_default(card, key):
        return f"{host.name}'s default branch"
    try:
        guarded = pack.layer().protected(repo, branch)
    except HostError as error:
        raise HostError(f"{host.name} could not say whether {branch} is protected in {repo} ({error}), "
                        f"{ON_A_GUESS}") from None
    return f"protected {host.on}" if guarded else None


def refuse(card: dict, key: str, branch: str) -> None:
    """Refuse a branch that is not the card's own to cut, push or open a change from."""
    why = why_shared(card, key, gc.ref_name(branch))
    if why:
        raise HostError(f"{branch} is a shared branch of {key} ({why}): {NEVER.format(**pack.words().fill())}")
