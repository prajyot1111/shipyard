"""The config loader: the install's `config.toml`, else an older checkout's `keel.toml`,
else the shipped example.

WHERE THE CONFIG IS (c-610 S1). The install's own file is `<home>/config.toml`, where the
home is `KEEL_HOME` (else the checkout this package is in); it is gitignored, so a user's
choices and a machine's paths never sit in the tracked tree. Without one, an untracked
`keel.toml` an older checkout kept is read, else the shipped defaults,
`etc/shipyard.example.toml`, which the installer copies to `<home>/config.toml`.
`KEEL_CONFIG` still names a file outright. One file holds both concerns, kept apart by
table: what the user chooses (`[keel]` switches, `[spaces.*]`, `[voice]`, `[tests]`,
`[recurring.*]`, `[models]`) and what the machine needs (`[machine]`, `MACHINE_KEYS`). A
`[machine]` key wins over the same key under `[keel]` (or `[voice]`, `VOICE_MACHINE_KEYS`),
which is what lets a pre-split file load unchanged.

Reads the toml once, expands `~`, resolves relative paths against the repo root, and
exposes a `Config` with the keel section, the `[voice]` table and a `Space` per
`[spaces.<name>]` table.
`KEEL_HOME` overrides the repo root; `KEEL_CONFIG` overrides the toml path.

EVERY DEFAULT IS THE SCHEMA'S (c-633). `[keel]`, `[spaces.<name>]` and `[voice]` are read
through `keel/settings.py`: each value typed, each default from the one declaration the
Settings view also draws, and the dataclass defaults below read from it too. A key a table
does not know, and a value of the wrong type, is a line in `Config.warnings` (Now's warning
panel, `keel doctor`), never a refusal: the default is used, so a typo can never keep the
deck from starting. `drain_paused` defaults to false and `house_review` to true, as the
shipped example says.

THE STATE A CHECKOUT MAY OPEN IS ITS OWN (2026-09-20). The config was then the tracked
`keel.toml`, and said `state_dir = "~/keel/state"`, an absolute-by-home path to the LIVE
checkout's state rather than a path relative to the checkout the file sat in. Every house
builds in a git worktree under `<live>/state/worktrees/<card>/`, which carried the same
`keel.toml`, so anything run from a worktree that loaded the worktree's own config resolved `state_dir` to the live board
and wrote to it. That happened five times in one day: four houses ran a scratch voice gateway
from their worktree and the captures they spoke into it were filed as real cards on his
board, and the test fence caught `bin/kb help` doing the same from the other side. So `load`
compares the two: a `state_dir` that resolves OUTSIDE the code root belongs to another
checkout, and this one is given its own `state/` and `segments/` instead.
`Config.scratch` says it happened and `Config.scratch_note` says it in one line. Two things
opt out, both deliberate: `KEEL_CONFIG` (or a path handed to `load`) names a toml on purpose,
and `KEEL_LIVE_STATE=1` asks for the live board from wherever the caller is.

AND THE CODE ROOT IS THE PACKAGE'S, NOT `KEEL_HOME`'S (2026-09-20, later the same day).
The first version of that comparison read the code root off `KEEL_HOME`, and a house's
environment carries `KEEL_HOME=<the live checkout>`: so code running from a WORKTREE
compared the live `state_dir` against the live root, found it inside, and opened his board.
`bin/keel-voice-selftest` files two cards as part of what it proves, and houses run it many
times per card: 84 fake cards in one day. `KEEL_HOME` says where the state and the repos
are; `package_root()` says where the CODE is, and it is the parent of this package's own
directory, which no environment variable can move. So `borrows_state` asks both questions:
a `state_dir` outside the root is another checkout's as before, and a `state_dir` that is
the root's own is another checkout's too when the running package is not that checkout's.
`scratch_root` then puts the scratch where the refused board is not.

ONE MACHINE (c-622). Keel runs on the machine its config is on: one board, one drain, one
deck. The two-machine keys of 2026-09 (`[hosts.<name>]`, `[tenancy]`, `board_url`, a space's
`host` pin) are gone; a file that still carries one loads anyway, the key ignored and named
in `Config.warnings` (`keel/oldconfig.py`), so an old config never keeps the deck from
starting; the old `[hosts.<this host>]` limits and backup keys fill what `[keel]` and
`[backup]` leave out.
`host` is only this machine's name, the one the deck's drain pill shows.

`[backup]` names the snapshot store (`store`, an rclone remote or a directory), the rclone
config holding its token, the sets this machine writes (`sets`) and whether it pulls a
nightly copy (`pull`). `keel/backup.py` hands them to `bin/keel-backup`.
"""

import hmac
import os
import re
import secrets
import socket
import subprocess
import tomllib
import zlib
from dataclasses import dataclass, field
from pathlib import Path

from keel import configpath, oldconfig, packs, settings
from keel.models import TURN_MODELS, model_problem
from keel.settings import MACHINE_KEYS, VOICE_MACHINE_KEYS
from keel.shipwatch import WorkHours


def repo_root() -> Path:
    """The Keel checkout: `KEEL_HOME` if set, else the parent of this package."""
    home = os.environ.get("KEEL_HOME")
    if home:
        return Path(home).expanduser().resolve()
    return Path(__file__).resolve().parent.parent


HOUSE_BIN = "etc/house-bin"     # shims only a house has on PATH; `open` is the one that matters
KEEL_BIN = "bin"                # `kb` and the hook bodies


def house_path(root: Path, inherited: str = "") -> str:
    """A house's PATH: the house shims first, then Keel's `bin`, then what was there.

    `etc/house-bin` is first because its whole point is to WIN: its `open` swallows a
    browser launch (lavish's included) and leaves the URL on the card instead of a tab on a
    desk nobody may be sitting at. Only a house is given this PATH, by the settings file
    (`house.env_for`) and by the launch environment (`harness.child_env`), so a human's own
    `open` is untouched. An empty inherited PATH is dropped rather than left as an empty
    entry, which would mean the current directory.
    """
    parts = [str(root / HOUSE_BIN), str(root / KEEL_BIN)]
    return os.pathsep.join(parts + ([inherited] if inherited else []))


INSTALL_CONFIG, SHIPPED_CONFIG = configpath.INSTALL_CONFIG, configpath.SHIPPED_CONFIG
CONFIG_ENV = configpath.CONFIG_ENV
config_file, own_configs = configpath.config_file, configpath.own_configs


def config_path() -> Path:
    """The toml to load: `KEEL_CONFIG` if set, else the install's (`configpath.config_file`)."""
    return configpath.config_path(repo_root())


def named_toml(cfg) -> str | None:
    """The toml a child or a service of this config is handed as `KEEL_CONFIG`, or None when
    the checkout's own is right (`configpath.named`): the one rule, for a house's hooks
    (`keel/house.py`) and for every service file Keel renders."""
    return configpath.named(cfg.source, cfg.root, cfg.scratch)


def named_env(cfg) -> dict[str, str]:
    """`KEEL_CONFIG` for a service file of this config, or nothing (c-711): launchd and
    systemd hand a service only what its file says, so a service of an install that was
    given `KEEL_HOME` alone would load the checkout's own toml, another board."""
    named = named_toml(cfg)
    return {CONFIG_ENV: named} if named else {}


def service_reads(cfg) -> str:
    """The line an install command prints after the file it wrote (`configpath.reads_line`)."""
    return configpath.reads_line(named_toml(cfg), cfg.root)


LIVE_STATE_ENV = "KEEL_LIVE_STATE"      # the opt-in: `1` hands a worktree the live board
HOME_ENV = "KEEL_HOME"


def live_state_wanted() -> bool:
    """True when the caller asked for the state the toml names, wherever the code is."""
    return os.environ.get(LIVE_STATE_ENV, "").strip().lower() in ("1", "yes", "true", "on")


def package_root() -> Path:
    """The checkout the RUNNING `keel` package lives in: the parent of this package's
    directory, resolved.

    `bin/kb` puts its own parent's parent first on `sys.path`, so a `kb` started from a
    worktree imports that worktree's package and this answers the worktree, whatever
    `KEEL_HOME` says. That is the difference the second half of the guard is built on.
    """
    return Path(__file__).resolve().parent.parent


SELF = Path(__file__).resolve().relative_to(package_root())     # keel/config.py


def is_checkout(path: Path) -> bool:
    """True when `path` carries this file too, so it is a Keel checkout in its own right
    rather than a scratch directory somebody pointed `KEEL_HOME` at.

    It is what tells the two shapes apart: a `KEEL_HOME` naming another CHECKOUT is naming
    a board that checkout's own code owns, and a `KEEL_HOME` naming a bare directory is
    naming a state nobody else has any claim on.
    """
    return (path / SELF).exists()


def borrows_state(root: Path, state_dir: Path, package: Path | None = None) -> bool:
    """True when `state_dir` belongs to a checkout other than the one whose code is running.

    Two ways that happens, and the second is the one that got past the first version of this
    rule. `~/keel/state` read from a worktree, from a second clone, or from a scratch
    `KEEL_HOME` resolves OUTSIDE the root, which is the first. The second is a `KEEL_HOME`
    naming the live checkout while the code doing the reading is a worktree's: the state is
    the root's own, and the root is not ours.

    The package is compared by equality rather than by containment, because a house's
    worktree sits at `<live>/state/worktrees/<card>/`: it is inside the live checkout on
    disk, and it is emphatically not the live checkout.
    """
    package = (package or package_root()).resolve()
    root, state_dir = root.resolve(), state_dir.resolve()
    if state_dir.is_relative_to(package):
        return False
    if not state_dir.is_relative_to(root):
        return True
    return package != root and is_checkout(root)


def scratch_root(root: Path, state_dir: Path, package: Path | None = None) -> Path:
    """Where a checkout that may not open `state_dir` puts its own state instead.

    The root it was pointed at, which is what a scratch `KEEL_HOME` and a worktree reading
    `~/keel/state` both want. The exception is the shape above: when the refused state is
    the ROOT'S OWN, `root/state` IS the board being kept away from, so the scratch belongs
    to the checkout the running code lives in.
    """
    package = (package or package_root()).resolve()
    return package if state_dir.resolve().is_relative_to(root.resolve()) else root


def missing_toml(path: Path) -> str:
    """Why there is no toml to read, naming whichever of the three said where to look.

    It used to be a bare `FileNotFoundError` out of `load`, which reads as a bug in Keel
    rather than as a scratch directory that was never given the file.
    """
    if os.environ.get(CONFIG_ENV):
        return f"{CONFIG_ENV} names {path}, and there is no file there"
    if os.environ.get(HOME_ENV):
        return (f"{HOME_ENV} names a directory with no config of its own (no config.toml or keel.toml, "
                f"and no shipped example at {path}). "
                f"Point {HOME_ENV} at a Shipyard checkout, or name a toml with {CONFIG_ENV}.")
    return f"no config at {path}; this directory is not a Shipyard checkout"


# THE SHIPPED EXAMPLE IS A WORKTREE'S AND A TEST'S, NEVER A LIVE CHECKOUT'S (c-725 r1.F5).
# A checkout with no config of its own reads `etc/shipyard.example.toml`, which gives a house
# worktree its scratch board. A live checkout whose own config has gone (a service started
# with `KEEL_HOME` alone) would run on the example's defaults instead, an unpaused drain
# among them, so there the load refuses. A house worktree is told apart by what it is, not
# by how its path is spelled: its `.git` is a file (a `git worktree`), or its session carries
# `KEEL_CARD`. The test fence's log variable marks a test run (`tests/fence.py`).
WORKTREE_MARKS = ("KEEL_CARD", "KEEL_TEST_FENCE_LOG")


def example_refused(root: Path, path: Path) -> bool:
    if Path(path).resolve() != (root / configpath.EXAMPLE_CONFIG).resolve():
        return False
    return not ((root / ".git").is_file() or any(os.environ.get(mark) for mark in WORKTREE_MARKS))


def example_refusal(root: Path) -> str:
    return (f"{root} has no config of its own, and the shipped example is only a worktree's or a "
            f"test's: name the install's config with {CONFIG_ENV}=<install>/config.toml")


# `[machine]`: what this machine needs rather than what its user chose (c-610 S1). Each is
# read from `[machine]` first, then from `[keel]` where a pre-split file put it. The key lists
# (`MACHINE_KEYS`, `VOICE_MACHINE_KEYS`) live in `keel/settings.py` beside the keys a table
# knows, and are imported here under their old names.


def machine_split(data: dict) -> tuple[dict, dict]:
    """`[keel]` and `[voice]` with `[machine]` laid over them: a `[machine]` key wins, so
    one file read either way gives one Config. A `[machine]` key this does not know is a
    typo worth refusing, not a setting nobody reads."""
    machine = data.get("machine", {})
    unknown = sorted(set(machine) - set(MACHINE_KEYS)
                     - {f"voice_{key}" for key in VOICE_MACHINE_KEYS})
    if unknown:
        raise ConfigError(f"[machine] has no key {', '.join(unknown)}; "
                          f"the keys are {', '.join(MACHINE_KEYS)} and voice_port, voice_app_url, voice_deck_url")
    keel = {**data.get("keel", {}), **{k: v for k, v in machine.items() if k in MACHINE_KEYS}}
    voice = {**data.get("voice", {}), **{key: machine[f"voice_{key}"]
                                         for key in VOICE_MACHINE_KEYS if f"voice_{key}" in machine}}
    return keel, voice


def backup_keys(data: dict, host: str) -> dict:
    """`[backup]` with its `sets` and `pull`, which a file written for two machines kept
    under `[hosts.<this host>]` as `backup_sets` and `backup_pull` (read from there when
    `[backup]` does not say). A set, in `sets` or `extra`, that the backup tool has no facts
    for is refused here (c-722 r1.F4), so no job is ever handed one it would die on."""
    backup = dict(data.get("backup") or {})
    mine = ((data.get("hosts") or {}).get(host) or {})
    if "sets" not in backup and "backup_sets" in mine:
        backup["sets"] = mine["backup_sets"]
    if "pull" not in backup and "backup_pull" in mine:
        backup["pull"] = mine["backup_pull"]
    for key in ("sets", "extra"):
        for name in backup.get(key, []):
            if name not in TOOL_SETS:
                raise ConfigError(f"[backup] {key} names {name!r}; the sets the backup tool knows "
                                  f"are {', '.join(TOOL_SETS)}")
    return backup


def optional_path(table: dict, key: str, root: Path) -> Path | None:
    """A path key that is off when absent: never a default that names somebody's home."""
    value = str(table.get(key) or "").strip()
    return resolve(value, root) if value else None


def resolve(value: str, root: Path) -> Path:
    """Expand `~` and make a relative path relative to the repo root."""
    path = Path(value).expanduser()
    if not path.is_absolute():
        path = root / path
    return path


# Keel's own backup sets (c-722): the install's board and data, and the code as a bundle,
# what a new install backs up.
BACKUP_SETS = ("keel", "code")
# Every set `bin/keel-backup` has facts for: Keel's own two, and the two one owner's install
# names (under `[backup] extra`, which the tool is handed as `KEEL_BACKUP_EXTRA`; an install
# from before `extra` names them in `sets` alone). Any other name is a typo, refused at load,
# until a set can be described by the config.
TOOL_SETS = BACKUP_SETS + ("harbor", "helm")


class ConfigError(ValueError):
    """The config says something that cannot be true: a typo'd key, a space nobody defined."""


PROJECT_NAME = re.compile(r"^[a-z0-9][a-z0-9-]*$")



@dataclass
class Space:
    name: str
    config_dir: Path
    repos: dict[str, Path]
    contract: Path | None
    adapter: str | None
    adapter_dir: Path | None = None
    deny: list[str] = field(default_factory=list)
    # c-769: permission rules a house with an open shell runs under without being asked, the
    # space's own sanctioned commands; a deny still beats one (`house.settings_body`). Read
    # from the space's own table, never from a pack's `[space]` (`space_allow`).
    allow: list[str] = field(default_factory=list)
    projects_dir: Path | None = None   # where a card may open a repo this file does not list
    # Every default below that is a setting is the schema's (`keel/settings.py`, c-633), so a
    # Space built directly agrees with a loaded one.
    # The model a card in this space gets when it names none; None leaves it to `[keel] model`.
    model: str | None = settings.default("space", "model")
    # The fields a card in this space may never be filed with silently: whenever one of them
    # was not stated, the create readback names it and says where it came from.
    confirm: tuple[str, ...] = settings.default("space", "confirm")
    # c-732: the branches a card's work starts from and lands on (`keel/bases.py`); empty is
    # the repo's default branch, as before
    bases: tuple[str, ...] = settings.default("space", "bases")
    # A new card's autonomy, plan style and topic when it names none (c-633): the
    # space_default layer of `keel/cardspec.py`, beside `model`.
    autonomy: str = settings.default("space", "autonomy")
    plan_style: str = settings.default("space", "plan_style")
    topic: str | None = settings.default("space", "topic")
    # A repo card's house runs the pre-gate pipeline before the outcome gate (review with
    # Keel's reviewer and verifier, verify, preship, risk), and the Stop hook and
    # `kb stage review` hold it to that (`keel/review/`). On by default since c-633, as the
    # shipped example always said.
    house_review: bool = settings.default("space", "house_review")
    # The model the house's reviewer and verifier run on (c-633): `inherit` is the house's.
    reviewer_model: str = settings.default("space", "reviewer_model")
    # Lane RC: a review card at the inbox whose pull request has been quiet this long is
    # backlog (`views.review_backlog`); the fetcher writes it on each card it tends.
    review_backlog_days: int = settings.default("space", "review_backlog_days")
    # Lane GRP (GR-3): how long a review card whose story has a branch, but no pull request,
    # in another reviewed repo waits for that sibling before it is reviewed alone.
    review_sibling_hours: int = settings.default("space", "review_sibling_hours")
    # Lane RETIRE (RT-2): the review fetcher's two settings as shipped, auto review (a new
    # review card is filed at assigned rather than the inbox) and the review model. The
    # deck's gear sets a live override under state/ (`keel/reviewsettings.py`).
    # c-730: whether the space files review cards at all, where its pack can (`reviews` in its
    # `[capabilities]`). On unless the space says off; a pack's `[space]` may start it off, as
    # the GitHub pack does, so no space is reviewed without the user's choice.
    review_scan: bool = settings.default("space", "review_scan")
    review_auto: bool = settings.default("space", "review_auto")
    review_model: str | None = settings.default("space", "review_model")
    # The space's own words for the pipeline's verify and preship steps: a markdown file
    # with a `## Verify` and a `## Preship` section, included in the brief (`keel/review/brief.py`).
    pipeline: Path | None = None
    # c-597: the work space runs preship FIRST (fetch, rebase, docs, push, the draft) so the
    # head the reviewer sees is the head that ships, then review and verify side by side on
    # it (`keel/review/brief.py`). Off: review, verify, preship, risk, in that order.
    preship_first: bool = settings.default("space", "preship_first")
    # c-597: the full review passes a gate trip may have before only fix checks remain
    # (`keel/review/stamp.py`, RD-1). A space that names none gets `[keel] review_full_rounds`.
    review_full_rounds: int | None = settings.default("space", "review_full_rounds")
    # c-655: whether a shipping card's new review comments, and its failing checks, go to its
    # house as they arrive or wait on the card for his hand-over (`keel/shipauto.py`). Both
    # off unless the space says; a card's own option of the same name wins.
    ship_auto_comments: bool = settings.default("space", "ship_auto_comments")
    ship_auto_checks: bool = settings.default("space", "ship_auto_checks")
    # c-665: the git remote the space's repos fetch from and push to (`remote_of`), and the
    # name of a card's branch where no pack names it (`keel/adapters.py`). Each default is
    # what Keel always did.
    remote: str = settings.default("space", "remote")
    branch: str = settings.default("space", "branch")
    # c-678: in a space with no pack, fetch the remote before a card's worktree is cut, and
    # offer a Push on a card that landed by a local merge (`keel/landpush.py`). Both on.
    fetch_before_work: bool = settings.default("space", "fetch_before_work")
    offer_push: bool = settings.default("space", "offer_push")
    # r1.F6: the pack's own `[space]` defaults, as `adapter_of` laid them under this space
    # (`pack =` only); the Settings form calls these the space's defaults
    # (`settings.pack_defaults`), so the form and the values in force read one table.
    pack_space: dict = field(default_factory=dict)

    def repo_path(self, name: str) -> Path | None:
        """The directory a card's `repo` names: a listed repo, else a project under
        `projects_dir`, else None.

        A listed repo wins, so a project directory can never shadow one. A name that is
        not a listed repo is a project only when it is a plain directory name: no slash,
        no `..`, no leading dot, which is what keeps a typo from reaching outside the
        projects directory. The path is returned whether or not it exists; who may create
        it is the placement's decision, not the config's.
        """
        if name in self.repos:
            return self.repos[name]
        if self.projects_dir is not None and PROJECT_NAME.match(name):
            return self.projects_dir / name
        return None

    def projects(self) -> list[str]:
        """Every git repo directly under `projects_dir`, by directory name, sorted.

        This is the discovery rule: a project is addressable because it is there, not
        because something listed it. `keel doctor` prints this.
        """
        if self.projects_dir is None or not self.projects_dir.is_dir():
            return []
        return sorted(entry.name for entry in self.projects_dir.iterdir()
                      if entry.is_dir() and (entry / ".git").exists()
                      and PROJECT_NAME.match(entry.name))


@dataclass
class Config:
    root: Path
    state_dir: Path
    houses_max: int
    reviews_max: int
    poll_seconds: int
    drain_paused: bool
    segments_dir: Path
    adapters_dir: Path
    serve_port: int
    lavish_port: int
    spaces: dict[str, Space]
    # A card at its outcome gate longer than this backlogs.
    backlog_days: int = settings.default("keel", "backlog_days")
    artifact_roots: list[Path] = field(default_factory=list)   # extra trees the deck may serve
    lavish_state: Path | None = None  # lavish's own session file; `~/.lavish-axi/state.json` by default
    fetch_lock_dir: Path | None = None
    # How long a plan discussion waits on a quiet surface; how long voice holds a card's house
    # after the last thing he said; the talker's auto-reset of a session older than this.
    discussion_idle_seconds: int = settings.default("keel", "discussion_idle_seconds")
    voice_hold_seconds: int = settings.default("keel", "voice_hold_seconds")
    talker_reset_max_age_seconds: int = settings.default("keel", "talker_reset_max_age_seconds")
    host: str = "here"              # the word `default_host` falls back to (c-634)
    # THIS MACHINE'S HOME DIRECTORY, and the one place anything asks for it. The keys a
    # machine holds live under it (`keel/voice.py`'s credentials directory, and with it the
    # shared house key of V12 slice 2). It is a field rather than a `Path.home()` at each
    # site so a test can point a whole Config at a temporary home rather than at his real
    # one: a test that minted the shared key would otherwise write into his credentials.
    home: Path = field(default_factory=Path.home)
    repo_tests: dict[str, str] = field(default_factory=dict)   # [tests]: repo name -> command run before a merge
    # [integration]: repo name -> the branch its approved outcomes land on (c-526): for a repo
    # where merging is deploying, main moves only on his deploy (`keel/deploy.py`).
    integration: dict[str, str] = field(default_factory=dict)
    # [retests]: repo name -> the command a red deploy suite reruns its failures with, once;
    # `{log}` is the red run's output file.
    repo_retests: dict[str, str] = field(default_factory=dict)
    # [deploy_tests]: repo name -> the command a deploy runs before main moves (c-646): the
    # FULL suite with voice (`make test-all` for Keel), where a landing's `[tests]` runs only
    # what its change reaches. A repo without an entry runs its `[tests]`.
    deploy_tests: dict[str, str] = field(default_factory=dict)
    # [house_tests]: repo name -> the command a house runs before review (c-544): targeted,
    # since `make test` runs once, where it lands; `{base}` is the card's base. A repo
    # without an entry runs its `[tests]`.
    house_tests: dict[str, str] = field(default_factory=dict)
    source: Path | None = None       # the toml this was loaded from; a subprocess kb gets it as KEEL_CONFIG
    # [voice]: the gateway's port (what the deck's /voice/ tier proxies to), the page's
    # three defaults (mode, space and which synthesiser speaks), and the detector's two
    # settings; `keel voice install` writes every one into the agent's environment.
    voice_port: int = 4390
    voice_space_default: str = settings.default("voice", "space_default")
    # [voice] app_url / deck_url: Voice's own address (a Tailscale Service, `harbor.<tailnet>`),
    # so a phone installs it as an app beside the deck instead of a shortcut inside the deck's
    # scope, and the deck's address its back link returns to. None: Voice stays under the deck.
    voice_app_url: str | None = None
    voice_deck_url: str | None = None
    voice_mode_default: str = settings.default("voice", "mode_default")
    voice_engine_default: str = settings.default("voice", "engine_default")
    voice_vad: str = settings.default("voice", "vad")
    # The silence that ends an utterance, in seconds (lane H, H6): 2.0, approved on the
    # measured corpus; the gateway reads it from `HARBOR_VOICE_VAD_HANGOVER`.
    voice_vad_hangover: float = settings.default("voice", "vad_hangover")
    # A connected conversation is ONE kept-alive `claude` (V12); false is the one
    # line back to the per-sentence shape, for a build of `claude` that will not
    # take `--input-format stream-json`.
    voice_kept_alive: bool = settings.default("voice", "kept_alive")
    # Harbor's OWN voice turns on one kept-alive streamed process (R2); ships false, and
    # false is today's one `claude -p --resume` per utterance.
    voice_harbor_kept_alive: bool = settings.default("voice", "harbor_kept_alive")
    voice_record: bool = settings.default("voice", "record")
    # This machine's limits, from `[keel]` (`keel/drain.py` reads them).
    browsers_max: int | None = None   # houses whose card declares `options.browser`; None: no cap
    memory_floor_mb: int = 0          # start nothing under this much available memory; 0: off
    house_mb: int = 700               # what one start is assumed to take, within one pass
    house_nice: int = 0               # the nice each house runs at, so voice goes first; 0: off
    # How long a house may sit idle mid-turn, with no Stop, before the drain puts it back
    # (`drain.idle_stuck`); the wait doubles with each attempt. 0: the rule is off.
    idle_resume_minutes: int = 10
    # [backup] (`keel/backup.py`). No store: nothing is set up.
    backup_store: str | None = None
    backup_rclone_config: Path | None = None
    backup_sets: list[str] = field(default_factory=list)   # [backup] sets: what this machine writes
    backup_extra: list[str] = field(default_factory=list)  # [backup] extra: this install's own sets (c-722)
    backup_pull: bool = False         # [backup] pull: this machine pulls a nightly copy of the store
    # [backup] since: when the first run turned this install's backup on (UTC), written by the
    # turn-on beside the store (`keel/backupsetup.py`); `keel/backupstatus.py` reads it (c-757)
    backup_since: str | None = None
    # [recurring.<key>]: cards the fetch role files again every `every_days` (`keel/recurring.py`).
    recurring: dict[str, dict] = field(default_factory=dict)
    # [models]: Keel's own model turns (TURN_MODELS), each pinned in the gateway's environment.
    turn_models: dict[str, str] = field(default_factory=lambda: dict(TURN_MODELS))
    # The state guard (see this module's docstring). `scratch` is true when the toml named
    # another checkout's state and this one was given its own instead; `wanted_state` is
    # the directory that was not opened, kept so a message can name the board it is not.
    scratch: bool = False
    wanted_state: Path | None = None
    # The port the toml gives the deck. A scratch config serves on a port of its own
    # (`scratch_port`), and `guard_port` refuses this one to it even when asked by name.
    live_serve_port: int | None = None
    # [keel] merge_queue: Approve outcome of a personal card on THIS machine lands through
    # the drain rather than inside the tap, and the drain pre-runs the merged tree at review
    # (`keel/landing.py`). Off by default; a card whose house is elsewhere is queued anyway.
    merge_queue: bool = settings.default("keel", "merge_queue")
    # [keel] rotate: the deck's Rotate session and `rotate` relays (`keel/rotate.py`). Off by
    # default: with it off nothing asks a house for a checkpoint and no drain carries one.
    rotate: bool = settings.default("keel", "rotate")
    # [keel] multi_after: a card may wait for several cards (`after=a,b`, c-302). Off by
    # default, because a drain or deck on older code reads the column as one id and fails
    # on the whole board; switched on only once both machines run code that reads a list.
    multi_after: bool = settings.default("keel", "multi_after")
    # [keel] bosun_builder: Bosun builds and lands Keel's own fixes while Keel is young
    # (`keel/authority.py`, "Builder mode"): on personal cards it writes, moves, splits,
    # notes, unblocks and creates, writes its own authority, and approves an outcome onto the
    # integration branch. A personal card with a repo is its to build, never a house's
    # (`views.bosun_builds`). The integration branch and his deploy stay. Off by default.
    bosun_builder: bool = settings.default("keel", "bosun_builder")
    # [keel] plan_pages: every NEW plan and outcome is written in the plan format and read on
    # its own page (`/plan/<id>`, `/outcome/<id>`); the brief carries the format card
    # (`keel/planbrief.py`). ON by default and in the shipped example: false is the one line back, and
    # then the plan styles (`options.plan_style`, lavish or markdown) apply unchanged.
    plan_pages: bool = settings.default("keel", "plan_pages")
    # [machine] stack_guard_hook: a PreToolUse guard script every house and Bosun are handed
    # (`house.guard_hooks`); usage_file: the status line's usage tee the deck's meter reads
    # (`deckstate.usage_file`); harbor_dir: the old Harbor tree, whose `.claude/.claude.json`
    # seeds the talker's and whose ledger `kb import-harbor` reads. None: not on this machine.
    stack_guard_hook: Path | None = None
    usage_file: Path | None = None
    harbor_dir: Path | None = None
    # [backup] legacy_repo: the code-host repo the backup pushed to before the store, named
    # only by `keel-backup migrate`'s record and its closing advice.
    backup_legacy_repo: str | None = None
    # [keel] work_hours and work_days: when he works, which sets how often the pull request
    # watcher looks at a shipping card (`keel/shipwatch.py`): every 5 or 15 minutes inside
    # them, hourly outside. This machine's local time.
    work_hours: str = settings.default("keel", "work_hours")
    work_days: str = settings.default("keel", "work_days")
    # [console]: Bosun's session, as the toml wrote it (c-519); `keel/console.py` reads it and
    # owns its defaults, so this module never has to know what a key means.
    console: dict = field(default_factory=dict)
    # [builder]: which builder Bosun is when `bosun_builder` is on (c-619), as the toml wrote
    # it; `keel/builder.py` reads it and owns its defaults.
    builder: dict = field(default_factory=dict)
    # The promoted constants (c-633), each a `[keel]` setting read where the constant was:
    # Keel's own model for a new card (`cardspec`'s keel_default layer, `house.require_model`),
    # the full review passes a space that names none gets (`review/stamp.py`), the asks for a
    # missing stamp before a block (`review/gate.py`), the merged-tree and deploy test limits
    # (`merging.run_tests`, `deploy.run_suite`) and the idle shipping house's close
    # (`shipidle.close_idle`, `views.ship_idle`).
    model: str = settings.default("keel", "model")
    review_full_rounds: int = settings.default("keel", "review_full_rounds")
    review_asks: int = settings.default("keel", "review_asks")
    merge_test_seconds: int = settings.default("keel", "merge_test_seconds")
    deploy_test_seconds: int = settings.default("keel", "deploy_test_seconds")
    ship_idle_hours: int = settings.default("keel", "ship_idle_hours")
    # What the loader did not take (c-633): a key a table does not know, with the closest
    # real one, and a value of the wrong type with the default used instead. Now's warning
    # panel and `keel doctor` show them.
    warnings: list[str] = field(default_factory=list)
    # Where each setting the toml gave came from, by `keel.<key>`, `voice.<key>` and
    # `spaces.<name>.<key>`: `config` or `pack`. A setting not here is its default.
    provenance: dict[str, str] = field(default_factory=dict)

    @property
    def ship_hours(self) -> WorkHours:
        return WorkHours.parse(self.work_hours, self.work_days)

    @property
    def scratch_note(self) -> str:
        """One line naming the board this config opened and the one it did not.

        The live checkout's `kb` by absolute path is named because that is the supported
        way to the live board and the house contract already says so: a message that only
        refused would teach a house to hunt for the environment variable instead.
        """
        owner = self.wanted_state.parent if self.wanted_state else self.root
        return (f"scratch board at {self.db_path}, because this checkout does not own "
                f"{self.wanted_state}. The live board is reached with {owner / 'bin' / 'kb'}, "
                f"and {LIVE_STATE_ENV}=1 hands it to this one.")

    def integration_of(self, space_name: str | None, repo: str | None) -> str | None:
        """The integration branch a card of this space and repo lands on (`[integration]`),
        or None: its outcome then merges into the branch the checkout has out, as before
        c-526. Never for a space with an adapter: its outcome is a pull request."""
        space = self.spaces.get(space_name or "")
        if space is None or space.adapter_dir is not None or not repo:
            return None
        return self.integration.get(str(repo).split(",")[0].strip())

    @property
    def integrated(self) -> frozenset:
        """`(space, repo)` for every repo whose outcomes land on an integration branch: what a
        Board is opened with (`Board.integrated`), so an `after` on such a card waits for it
        to land (c-526, his D2)."""
        return frozenset((name, repo) for name, space in self.spaces.items()
                         if space.adapter_dir is None
                         for repo in self.integration if self.integration_of(name, repo))

    @property
    def stacking(self) -> frozenset:
        """The spaces whose pack stacks a waiting card on the card it waits for (c-718,
        `stacks = true` under its pack.toml's [capabilities]): what a Board is opened with
        (`Board.stacks`), so `options.stack` is refused in every other space."""
        from keel import packs, stacking    # noqa: PLC0415 - the config loads before either is needed
        out = set()
        for name, space in self.spaces.items():
            try:
                pack = packs.at(space.adapter_dir)
            except packs.PackError:
                continue
            if pack is not None and stacking.CAPABILITY in pack.capabilities:
                out.add(name)
        return frozenset(out)

    @property
    def switches(self) -> frozenset:
        """The `[keel]` switches a Board is opened with (`Board.switches`)."""
        return frozenset(name for name, on in (("merge_queue", self.merge_queue),
                                                ("rotate", self.rotate),
                                                ("multi_after", self.multi_after),
                                                ("bosun_builder", self.bosun_builder),
                                                # never on an install: it has one builder (c-621)
                                                ("builder_superuser",
                                                 bool(self.builder.get("superuser", False))
                                                 and self.install_home is None),
                                                # an install's builder in bypass (his call,
                                                # 2026-10-03): its own gates are its to pass
                                                ("builder_bypass",
                                                 self.builder.get("mode") == "bypass"
                                                 and not self.builder.get("superuser", False)
                                                 and self.install_home is not None)) if on)

    @property
    def install_home(self) -> Path | None:
        """The install this config is (the directory of its own `config.toml`, outside the
        code), else None: a checkout's own config, a scratch or a test config."""
        return configpath.install_of(self.source, self.root)

    @property
    def services_dir(self) -> Path:
        """Where a service this config installs is rendered (c-722): the install's `services/`,
        beside the app's own (`keel/appservices.py`), else the checkout's `etc/` for a
        checkout with no install. An install's service carries its paths, so it is never
        written into the code."""
        home = self.install_home
        return home / "services" if home is not None else self.root / "etc"

    def served_spaces(self) -> list[str]:
        """The spaces this machine's drain serves: every space, in the toml's order."""
        return list(self.spaces)

    @property
    def db_path(self) -> Path:
        return self.state_dir / "board.db"

    @property
    def cards_dir(self) -> Path:
        return self.state_dir / "cards"

    @property
    def token_path(self) -> Path:
        return self.state_dir / "human.token"

    @property
    def logs_dir(self) -> Path:
        return self.state_dir / "logs"

    @property
    def worktrees_dir(self) -> Path:
        return self.state_dir / "worktrees"

    @property
    def lavish_state_file(self) -> Path:
        """Lavish's session file, which records every open surface and the file behind it.
        One server per machine, so one file per machine: `~/.lavish-axi/state.json`."""
        return self.lavish_state or Path.home() / ".lavish-axi" / "state.json"

    @property
    def segment_roots(self) -> list[Path]:
        """Where the deck looks for a segment, in order: the repo's own `segments/` first,
        then `segments_dir`. The first root that has the name wins.

        Since cutover step 8 `segments_dir` IS the repo's tree, so this is one root and the
        de-duplication below is what collapses it. The list shape is kept rather than
        replaced by that one path, because the two legitimately differ again whenever
        `segments_dir` points somewhere else: a test config, or a `KEEL_HOME` aimed at a
        worktree whose own `segments/` should win over the shared tree."""
        own = self.root / "segments"
        roots = [own.resolve(), self.segments_dir.resolve()]
        # An install's own segments (what `shipyard import` copied there, code and data,
        # c-620) win over the checkout's: its fetch role runs `segments_dir` alone.
        if self.install_home is not None:
            roots.reverse()
        return list(dict.fromkeys(roots))

    def segment_dir(self, name: str) -> Path | None:
        """The directory of the segment called `name`, from the first root that has it."""
        for root in self.segment_roots:
            if (root / name).is_dir():
                return root / name
        return None

    @property
    def fetch_locks(self) -> Path:
        """Where a segment's fetch lock lives: `fetch_lock_dir`, else `<segments>/../ledger`.

        The fallback is what the old system's own hourly and minute jobs locked in, which
        is what made running both against one segments tree safe. Those jobs are gone and
        the config names a directory under `state/`, so the fallback is now only what a
        config that omits the key gets."""
        return self.fetch_lock_dir or self.segments_dir.parent / "ledger"

    def card_dir(self, card_id: str) -> Path:
        """`state/cards/<id>/`, created on first use: every path a card stores lives here."""
        path = self.cards_dir / card_id
        path.mkdir(parents=True, exist_ok=True)
        return path

    def ensure_dirs(self) -> None:
        """Create `state_dir`, `state/cards` and `state/logs` when they are missing."""
        self.cards_dir.mkdir(parents=True, exist_ok=True)
        self.logs_dir.mkdir(parents=True, exist_ok=True)


DEFAULT_REMOTE = settings.default("space", "remote")


def remote_of(cfg, space_name: str | None) -> str:
    """The git remote a card of this space fetches from and pushes to (`[spaces.<name>]
    remote`, c-665): `origin` unless the space says. The ONE place the name is read, so no
    caller spells a remote of its own; a reader with no config at hand is handed the name,
    and takes `DEFAULT_REMOTE` when it is handed none."""
    space = (getattr(cfg, "spaces", None) or {}).get(space_name or "")
    return getattr(space, "remote", None) or DEFAULT_REMOTE


def default_host() -> str:
    """This machine's short name for the deck's drain pill: `scutil` on a Mac (the socket
    name is the IP on a home network), else the first label of the hostname."""
    try:
        result = subprocess.run(["scutil", "--get", "LocalHostName"], capture_output=True, text=True, timeout=5)
        if result.returncode == 0 and result.stdout.strip():
            return result.stdout.strip().split("-")[0].lower()
    except (OSError, subprocess.SubprocessError):
        pass
    name = socket.gethostname().split(".")[0]
    return name if name and not name.replace(".", "").isdigit() else "here"


def _space(name: str, table: dict, root: Path, adapters_dir: Path,
           notes: list[str] | None = None, provenance: dict | None = None) -> Space:
    """One `[spaces.<name>]`. Its settings are read through the schema
    (c-633): a wrong value or an unknown key is a line in `notes`, never a refusal, and a
    pack's `[space]` defaults are checked too, naming the pack."""
    notes = notes if notes is not None else []
    own = dict(table)
    table, adapter, adapter_dir, pack_space = adapter_of(name, table, root, adapters_dir)
    laid = {key: value for key, value in table.items() if key not in own}    # the pack's defaults
    notes += settings.unknown_only(own, "space", f"[spaces.{name}]")
    notes += settings.unknown_only(laid, "space", f"the pack {adapter}'s [space] (for [spaces.{name}])")
    known = settings.known("space")
    typed, said = settings.check({key: value for key, value in table.items() if key in known},
                                 "space", f"[spaces.{name}]", name)
    notes += said
    if provenance is not None:
        provenance.update({f"spaces.{name}.{key}": "config" if key in own else "pack"
                           for key in table if settings.find("space", key)})
    repos = {key: resolve(value, root) for key, value in table.get("repos", {}).items()}
    contract = table.get("contract")
    projects_dir = table.get("projects_dir")
    return Space(
        name=name,
        config_dir=resolve(table["config_dir"], root),
        repos=repos,
        contract=resolve(contract, root) if contract else None,
        adapter=adapter,
        adapter_dir=adapter_dir,
        deny=list(table.get("deny", [])),
        allow=space_allow(name, own, pack_space, adapter, notes),
        projects_dir=resolve(projects_dir, root) if projects_dir else None,
        pipeline=resolve(table["pipeline"], root) if table.get("pipeline") else None,
        pack_space={key: value for key, value in pack_space.items() if key in known},
        **{key: typed[key] for key in typed},
    )


def space_allow(name: str, own: dict, pack_space: dict, pack: str | None, notes: list[str]) -> list[str]:
    """A space's `allow` list (c-769), from its own table only: what a house runs unasked is
    the install's to say, so a pack's `[space]` that names one is a line in `notes` and is
    not read. Anything but a list of non-empty strings is a line too, and no rule at all (a
    bare string would otherwise be one rule per character)."""
    if "allow" in pack_space:
        notes.append(f"the pack {pack}'s [space] (for [spaces.{name}]) allow is not read; "
                     f"only [spaces.{name}] itself may allow")
    said = own.get("allow", [])
    if isinstance(said, list) and all(isinstance(rule, str) and rule.strip() for rule in said):
        return list(said)
    notes.append(f"[spaces.{name}] allow = {said!r} is not a list of permission rules; none is used")
    return []


def adapter_of(name: str, table: dict, root: Path, adapters_dir: Path) -> tuple[dict, str | None, Path | None, dict]:
    """The space's adapter: `pack = "<name>"` (c-617) is the pack's directory, its `[space]`
    defaults laid under the table and its pipeline when the table names none; the older
    `adapter = "<name>"` is `adapters_dir/<name>` exactly as before, missing or not (a
    missing one is a space with no verbs). Returns the table to read, the name, the dir and
    the pack's `[space]` defaults it laid (none for `adapter =`, r1.F6)."""
    pack_name, adapter = table.get("pack"), table.get("adapter")
    if pack_name and adapter:
        raise ConfigError(f"[spaces.{name}] names both pack and adapter; a pack is its adapter, name one")
    if adapter:
        return table, adapter, adapters_dir / adapter, {}
    if not pack_name:
        return table, None, None, {}
    try:
        pack = packs.find(pack_name, root)
    except packs.PackError as error:
        raise ConfigError(f"[spaces.{name}] pack: {error}") from None
    table = {**pack.space, **table}
    if pack.pipeline and not table.get("pipeline"):
        table["pipeline"] = str(pack.pipeline)
    return table, pack.name, pack.path, dict(pack.space)


def host_name(keel: dict) -> str:
    """`[keel] host` (or `[machine] host`), else this machine's own short name."""
    return str(keel.get("host") or default_host()).strip()


# A `[recurring.<key>]` table's keys: the schedule, then the card it files.
RECURRING_KEYS = ("every_days", "space", "title", "brief", "repo", "autonomy", "model")


def recurring_tables(tables: dict, spaces: dict[str, Space]) -> dict[str, dict]:
    """Every `[recurring.<key>]`, checked like a host table: known keys, a known space, a
    positive whole number of days, and a card that could be filed as written."""
    found = {}
    for key, table in tables.items():
        where = f"[recurring.{key}]"
        unknown = sorted(set(table) - set(RECURRING_KEYS))
        if unknown:
            raise ConfigError(f"{where}: unknown keys {', '.join(unknown)}; known: {', '.join(RECURRING_KEYS)}")
        days = table.get("every_days")
        if not isinstance(days, int) or isinstance(days, bool) or days < 1:
            raise ConfigError(f"{where}: every_days must be a whole number of days, 1 or more")
        if table.get("space") not in spaces:
            raise ConfigError(f"{where}: space {table.get('space')!r} is not a [spaces.<name>] table")
        if not str(table.get("title", "")).strip():
            raise ConfigError(f"{where}: a recurring card needs a title")
        if table.get("autonomy", "autonomous") not in ("attended", "autonomous"):
            raise ConfigError(f"{where}: autonomy is attended or autonomous")
        if "model" in table and model_problem(table["model"]):
            raise ConfigError(f"{where}: model {model_problem(table['model'])}")
        found[str(key)] = {name: table[name] for name in RECURRING_KEYS if name in table}
    return found


def turn_models(table: dict) -> dict[str, str]:
    """`[models]`, checked: only the turns Keel has, only names `claude` takes, and every
    turn it leaves out at its settled default."""
    unknown = sorted(set(table) - set(TURN_MODELS))
    if unknown:
        raise ConfigError(f"[models] has no key {', '.join(unknown)} "
                          f"(it takes {', '.join(TURN_MODELS)})")
    for key, name in table.items():
        if model_problem(name):
            raise ConfigError(f"[models] {key}: {model_problem(name)}")
    return {**TURN_MODELS, **{key: str(name) for key, name in table.items()}}


def optional_int(value) -> int | None:
    return None if value is None else int(value)


def state_paths(root: Path, keel: dict, named: bool) -> tuple[dict, bool, Path | None]:
    """The state, segments and lock directories this process may have, and whether they
    were moved to this checkout's own.

    `named` is a toml the caller pointed at (`KEEL_CONFIG`, or a path handed to `load`),
    which is taken at its word: that is how the scratch deck recipe in `<install>/history/tests/live_deck.md`
    and every test helper run against a board that is deliberately somewhere else.
    """
    paths = {"state_dir": resolve(keel.get("state_dir", "state"), root),
             "segments_dir": resolve(keel.get("segments_dir", "segments"), root),
             "fetch_lock_dir": resolve(keel["fetch_lock_dir"], root) if "fetch_lock_dir" in keel else None}
    if named or live_state_wanted() or not borrows_state(root, paths["state_dir"]):
        return paths, False, None
    wanted = paths["state_dir"]
    own = scratch_root(root, wanted)
    return ({"state_dir": own / "state", "segments_dir": own / "segments",
             "fetch_lock_dir": own / "state" / "fetch-locks"}, True, wanted)


SCRATCH_PORT_OFFSET = 1000
SCRATCH_PORT_SPREAD = 100


def scratch_port(live_port: int, package: Path | None = None) -> int:
    """A scratch config's own deck port: the live one plus 1000, spread by the checkout.

    The same checkout always gets the same port, so a scratch deck and the `kb` beside it
    agree, and two worktrees rarely collide. Never the live port, which is the point: a
    scratch `keel serve` on 8790 either fails against the live deck or, with the deck down,
    answers the phone as if it were the live one (E4, c-415)."""
    spread = zlib.crc32(str((package or package_root()).resolve()).encode()) % SCRATCH_PORT_SPREAD
    return live_port + SCRATCH_PORT_OFFSET + spread


def guard_port(cfg: "Config", port: int) -> None:
    """Refuse the live deck's port to a scratch config, even when `--port` names it."""
    if cfg.scratch and cfg.live_serve_port is not None and port == cfg.live_serve_port:
        raise ConfigError(f"port {port} is the live deck's, and this is a scratch config "
                          f"({cfg.scratch_note}); serve on {cfg.serve_port} or another port")


def load(path: Path | None = None, ensure: bool = True) -> Config:
    """Load the toml, build the `Config`, and create the state directories unless
    `ensure` is false (`keel doctor` reports what is missing rather than making it).

    A `state_dir` that belongs to another checkout is redirected to this one's own; see
    this module's docstring for why, and `state_paths` for the rule.
    """
    root = repo_root()
    named = path is not None or bool(os.environ.get(CONFIG_ENV))
    path = path or config_path()
    if not path.exists():
        raise ConfigError(missing_toml(path))
    if not named and example_refused(root, path):
        raise ConfigError(example_refusal(root))
    with open(path, "rb") as handle:
        raw = tomllib.load(handle)
    data, gone = oldconfig.retired(raw)
    keel, voice = machine_split(data)
    host = host_name(keel)
    keel, carried = oldconfig.host_limits(raw, keel, host)
    data, elsewhere = oldconfig.console_host(data, host)
    # The settings, typed, with the schema's defaults (c-633): a wrong value or an unknown key
    # is a warning and never a refusal.
    mine, notes = settings.check(keel, "keel", "[keel]")
    notes = gone + carried + elsewhere + oldconfig.env_notes() + notes
    provenance = {f"keel.{key}": "config" for key in keel if settings.find("keel", key)}
    adapters_dir = resolve(keel.get("adapters_dir", "adapters"), root)
    backup = backup_keys(raw, host)
    spaces = {name: _space(name, table, root, adapters_dir, notes, provenance)
              for name, table in data.get("spaces", {}).items()}
    voiced, said = settings.check(voice, "voice", "[voice]")
    notes += said
    provenance.update({f"voice.{key}": "config" for key in voice if settings.find("voice", key)})
    provenance.update({f"builder.{key}": "config" for key in data.get("builder", {})
                       if settings.find("builder", key)})
    paths, scratch, wanted = state_paths(root, keel, named)
    config = Config(
        root=root,
        state_dir=paths["state_dir"],
        houses_max=int(mine["houses_max"]),
        reviews_max=int(mine["reviews_max"]),
        poll_seconds=mine["poll_seconds"],
        drain_paused=mine["drain_paused"],
        segments_dir=paths["segments_dir"],
        adapters_dir=adapters_dir,
        serve_port=(scratch_port(int(keel.get("serve_port", 8790))) if scratch
                    else int(keel.get("serve_port", 8790))),
        live_serve_port=int(keel.get("serve_port", 8790)),
        lavish_port=int(keel.get("lavish_port", 4387)),
        discussion_idle_seconds=mine["discussion_idle_seconds"],
        voice_hold_seconds=mine["voice_hold_seconds"],
        talker_reset_max_age_seconds=mine["talker_reset_max_age_seconds"],
        spaces=spaces,
        backlog_days=mine["backlog_days"],
        artifact_roots=[resolve(str(value), root) for value in keel.get("artifact_roots", [])],
        lavish_state=resolve(keel["lavish_state"], root) if "lavish_state" in keel else None,
        fetch_lock_dir=paths["fetch_lock_dir"],
        host=host,
        repo_tests={str(k): str(v) for k, v in data.get("tests", {}).items()},
        integration={str(k): str(v).strip() for k, v in data.get("integration", {}).items()
                     if str(v).strip()},
        repo_retests={str(k): str(v) for k, v in data.get("retests", {}).items()},
        deploy_tests={str(k): str(v).strip() for k, v in data.get("deploy_tests", {}).items()
                      if str(v).strip()},
        house_tests={str(k): str(v) for k, v in data.get("house_tests", {}).items()},
        source=path,
        voice_port=int(voice.get("port", 4390)),
        voice_space_default=voiced["space_default"],
        voice_app_url=(str(voice["app_url"]).rstrip("/") if voice.get("app_url") else None),
        voice_deck_url=(str(voice["deck_url"]).rstrip("/") if voice.get("deck_url") else None),
        voice_mode_default=voiced["mode_default"],
        voice_engine_default=voiced["engine_default"],
        voice_vad=voiced["vad"],
        voice_vad_hangover=voiced["vad_hangover"],
        voice_kept_alive=voiced["kept_alive"],
        voice_harbor_kept_alive=voiced["harbor_kept_alive"],
        voice_record=voiced["record"],
        browsers_max=optional_int(keel.get("browsers_max")),
        memory_floor_mb=int(keel.get("memory_floor_mb", 0)),
        house_mb=int(keel.get("house_mb", 700)),
        house_nice=int(keel.get("house_nice", 0)),
        idle_resume_minutes=int(keel.get("idle_resume_minutes", 10)),
        backup_store=str(backup["store"]) if backup.get("store") else None,
        backup_rclone_config=resolve(backup["rclone_config"], root) if "rclone_config" in backup else None,
        backup_sets=[str(s) for s in backup.get("sets", [])],
        backup_extra=[str(s) for s in backup.get("extra", [])],
        backup_pull=bool(backup.get("pull", False)),
        backup_since=str(backup["since"]) if backup.get("since") else None,
        recurring=recurring_tables(data.get("recurring", {}), spaces),
        turn_models=turn_models(data.get("models", {})),
        scratch=scratch,
        wanted_state=wanted,
        merge_queue=mine["merge_queue"],
        rotate=mine["rotate"],
        multi_after=mine["multi_after"],
        bosun_builder=mine["bosun_builder"],
        plan_pages=mine["plan_pages"],
        work_hours=mine["work_hours"],
        work_days=mine["work_days"],
        model=mine["model"],
        review_full_rounds=mine["review_full_rounds"],
        review_asks=mine["review_asks"],
        merge_test_seconds=mine["merge_test_seconds"],
        deploy_test_seconds=mine["deploy_test_seconds"],
        ship_idle_hours=mine["ship_idle_hours"],
        warnings=notes,
        provenance=provenance,
        console=dict(data.get("console", {})),
        builder=dict(data.get("builder", {})),
        stack_guard_hook=optional_path(keel, "stack_guard_hook", root),
        usage_file=optional_path(keel, "usage_file", root),
        harbor_dir=optional_path(keel, "harbor_dir", root),
        backup_legacy_repo=str(backup.get("legacy_repo") or "").strip() or None,
    )
    try:
        config.ship_hours
    except ValueError as error:
        raise ConfigError(f"[keel] {error}") from None
    if ensure:
        config.ensure_dirs()
    return config


def same_secret(offered: str | None, expected: str | None) -> bool:
    """A constant-time comparison that never raises: `hmac.compare_digest` refuses a str with
    non-ASCII characters (a TypeError out of a request handler), so both sides are compared
    as UTF-8 bytes. An empty side is never a match (lane E round 4, finding 5)."""
    if not offered or not expected:
        return False
    return hmac.compare_digest(str(offered).encode("utf-8", "surrogateescape"),
                               str(expected).encode("utf-8", "surrogateescape"))


def human_token(path: Path) -> str:
    """Read `state/human.token`, creating it (0600, random) when missing."""
    if not path.exists():
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(secrets.token_hex(32) + "\n")
        path.chmod(0o600)
    return path.read_text().strip()
