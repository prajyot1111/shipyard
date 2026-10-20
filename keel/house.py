"""Brief assembly, the per-house settings file, the worktree, and the launch itself.

A house is one background Claude Code session on one card. `settings_for` writes the
hooks, the denies and the per-card environment the session runs under, `brief_for`
writes what it is told, `launch` puts the two together with the worktree and starts it
through `harness`, and `resume` continues an exited house with the same settings, or starts
one afresh from the card's own record when the harness no longer holds the old one's
conversation (`keel/afresh.py`, c-654). Every
path written here lives under `state/cards/<id>/`, outside every worktree.

The environment goes in the settings file's `env` block, not the process environment:
`claude --bg` claims a session process a per-config-dir daemon pre-spawned, so the
process env a house sees is the daemon's (the second live house saw the first one's
`KEEL_CARD`). What `--settings` carries is per session.
"""

import fcntl
import functools
import json
import os
import shlex
import time
from contextlib import contextmanager
from pathlib import Path

from keel import (adapters, briefnews, config as config_module, dropin, harness, housejobs,
                  memoryroot, merging, packs, planbrief, prompts, repocommands, repofile, repolayout, sessionorigin, stacking, terms,
                  tiercards, trust, views)
from keel.board import SHIPPING_OPTION, Board, Refused
from keel.config import Config
from keel.review import agents as review_agents, brief as review_brief, gate as review_gate
from keel.review import stamp as review_stamp

GUARD_MATCHERS = ("Bash", "mcp__docker__.*")
NOTIFICATION_MATCHER = "idle_prompt|permission_prompt"
CONTEXT_SECTIONS = planbrief.CONTEXT_SECTIONS
CARD_BLOCK_FIELDS = briefnews.CARD_BLOCK_FIELDS
# An errand's tools: the reading and writing pair `fetch.DEFAULT_TOOLS` already gives an
# ask card, plus Bash. The Bash is the board and nothing else (`bin/keel-board-fence`), so
# an errand can stage, note, block and split its own card. Without it the house is briefed
# with the whole verb list and has no way to run any of it, which is what c-271 hit.
# WebSearch and WebFetch too, in both spaces: they carry no credential, and a research
# errand with no web can only say it knows nothing, which is what c-291 had to say.
ERRAND_TOOLS = "Read,Write,Edit,Glob,Grep,Bash,WebSearch,WebFetch"
# c-730 r2.F3: a fork's review house reads the fork's code and never runs it: the read tools,
# Write and Edit for its record, Agent for the review's two agents, and Bash behind the board
# fence with Keel's review steps (`bin/keel-board-fence --review`). No web.
FORK_REVIEW_TOOLS = "Read,Write,Edit,Glob,Grep,Bash,Agent"
# Claude Code 2.1 refuses a background session's writes inside a git repo until it calls
# EnterWorktree. Every house already runs where it should: a repo card in the worktree
# `placement` cut for it, a confined house in its own card directory (inside the Keel repo).
# So every house runs with the guard off and with EnterWorktree and ExitWorktree denied:
# c-271 blocked itself on the guard (2026-09-18), and in c-605's run two of four repo
# houses called EnterWorktree and sat on its permission prompt, which no Answer and no
# resume could close.
BG_ISOLATION = {"bgIsolation": "none"}
WORKTREE_DENY = ("EnterWorktree", "ExitWorktree")
# The pages the brief tells every house to read. A restricted house's file tools reach its
# cwd and its `--add-dir`s only, so without this the Atlas block names a directory it
# cannot open. Added read-only in fact, not only in intent: `--add-dir` grants writes in
# `--permission-mode auto`, and deny beats it, so the four editing tools are denied there.
ATLAS_DIR = ("docs", "atlas")
ATLAS_DENY_TOOLS = ("Edit", "Write", "MultiEdit", "NotebookEdit")
BASH_TOOL = "Bash"
BASH_MATCHER = "Bash"
FENCE_SCRIPT = "keel-board-fence"
HOUSE_GUARD_SCRIPT = "keel-house-guard"
CONTRACT = "house-contract.md"
DROP_CONTRACT = "house-contract-drop.md"
RESUME_PROMPT = prompts.RESUME
TURN_END_SCRIPT = "keel-turn-end"
THEME_FILE = "theme.css"


# ----- settings -----

def kb_path(cfg: Config) -> Path:
    """The running Keel's `kb`, by absolute path: the hooks must not depend on PATH."""
    return cfg.root / "bin" / "kb"


def turn_end_path(cfg: Config) -> Path:
    """The turn-end hook body, by absolute path for the same reason `kb` is."""
    return cfg.root / "bin" / TURN_END_SCRIPT


def fence_path(cfg: Config) -> Path:
    """The board fence, the PreToolUse(Bash) hook a confined house runs under."""
    return cfg.root / "bin" / FENCE_SCRIPT


def house_guard_path(cfg: Config) -> Path:
    """The house guard, the PreToolUse(Bash) hook every house with an open shell runs under."""
    return cfg.root / "bin" / HOUSE_GUARD_SCRIPT


def pack_guard(cfg: Config, card: dict) -> str:
    """` <guard> <tool>...` for a card whose space pack ships a `guard` verb (c-689), which
    the house guard then asks about each command; nothing for every other pack, so their
    houses' hook command is what it always was."""
    space = cfg.spaces.get(card.get("space") or "")
    if space is None or space.adapter_dir is None:
        return ""
    try:
        pack = packs.at(space.adapter_dir)
    except packs.PackError as error:
        # A pack that does not load and shows a guard (the file, or `[guard]` in its
        # pack.toml) blocks the card, as a failing `deny` verb does: a house is never
        # started without the guard its pack says it has. One with no sign of a guard and
        # a fault of its own starts as it did before there were guards.
        if packs.guard_evidenced(space.adapter_dir):
            raise adapters.AdapterError(f"the {space.adapter} pack declares a guard for its houses and did "
                                        f"not load, so no house is started without it: {error}") from None
        return ""
    if pack is None or not pack.guard_tools:
        return ""
    return "".join(f" {shlex.quote(str(word))}" for word in (space.adapter_dir / packs.GUARD_VERB, *pack.guard_tools))


def command_hook(*commands: str, matcher: str | None = None, timeout: int | None = None) -> dict:
    """One hook group; several commands in a group all run for the same event."""
    entries = [{"type": "command", "command": command} for command in commands]
    if timeout:
        for entry in entries:
            entry["timeout"] = timeout
    group = {"hooks": entries}
    if matcher:
        group["matcher"] = matcher
    return group


def board_prefix(cfg: Config) -> str:
    """`KEEL_HOME=<root> KEEL_CONFIG=<toml|> ` ahead of EVERY hook command: the board this
    house was started from, pinned on the command line (c-601).

    A `claude --bg` house is a spare the harness daemon made, so a hook runs with the
    DAEMON's environment, not the drain's: a stale `KEEL_HOME` or `KEEL_CONFIG` would open
    another board. So both are said here, whatever the settings file's `env` does: the root,
    and the toml `named_toml` names (empty for the checkout's own, which reads as unset).
    """
    return (f"KEEL_HOME={shlex.quote(str(cfg.root))} "
            f"KEEL_CONFIG={shlex.quote(named_toml(cfg) or '')} ")


def guard_hooks(cfg: Config) -> list[dict]:
    """The PreToolUse groups of the stack guard, one per matcher, when this machine has it:
    `[machine] stack_guard_hook`, a script outside every space's config dir, so a session
    gets it only by being handed it: every house, and Bosun (`keel/console.py`)."""
    guard = cfg.stack_guard_hook
    if guard is None or not guard.is_file():
        return []
    return [command_hook(f"python3 {guard}", matcher=matcher, timeout=10) for matcher in GUARD_MATCHERS]


def hooks_for(cfg: Config, card_id: str, fenced: bool = False, reviewed: bool = False,
              peer: bool = False, shell: bool = False, full_max: int | None = None,
              guarded: str = "", fork_review: str = "") -> dict:
    kb = board_prefix(cfg) + str(kb_path(cfg))
    hooks = {
        # Two bodies at the end of a turn: `kb stop-check` owns the nudge at building,
        # `keel-turn-end` owns the record at the outcome gate and the discussion flag.
        "Stop": [command_hook(f"{kb} stop-check {card_id}",
                              f"{board_prefix(cfg)}{turn_end_path(cfg)} {card_id}")],
        "SessionEnd": [command_hook(f"{kb} event {card_id} --hook SessionEnd")],
        "Notification": [command_hook(f"{kb} event {card_id} --hook Notification",
                                      matcher=NOTIFICATION_MATCHER)],
    }
    if reviewed or peer:
        # The review's record is the harness's, not the house's (`keel/review/stamp.py`):
        # one group per agent, so each agent's own answer is what the hook reads. A review
        # card's (peer, lane RC) records its rounds and is never stamped.
        stamp = cfg.root / "bin" / review_stamp.STAMP_SCRIPT
        tail = f" {review_stamp.PEER_FLAG}" if peer and not reviewed else ""
        if reviewed and full_max:
            # the space's limit, fixed at launch, so the hook never falls back to another
            # when it cannot read the board (c-597 review)
            tail += f" {review_stamp.FULL_MAX_FLAG} {int(full_max)}"
        hooks["SubagentStop"] = [command_hook(f"{board_prefix(cfg)}{stamp} {card_id}{tail}", matcher=name)
                                 for name in (review_agents.REVIEWER, review_agents.VERIFIER)]
    groups = guard_hooks(cfg)
    if shell:
        # Keel's own guard, whether or not this machine has the stack guard: a wait loop on
        # `pgrep -f` matches its own shell and never ends (c-534). A fenced house needs
        # none, since its fence refuses every loop already.
        # With the card id it also refuses a push while the card is at shipping (c-600).
        # `guarded`: the space pack's own `guard` verb, which it then asks too (c-689).
        groups.append(command_hook(f"{board_prefix(cfg)}python3 {house_guard_path(cfg)} {card_id}{guarded}",
                                   matcher=BASH_MATCHER, timeout=20))
    if fenced:
        # A confined house's Bash reaches the board and nothing else. This is the
        # mechanism; the brief only explains it.
        # A fork's review house (c-730 r2.F3) also runs Keel's two review steps, pinned to
        # its own card directory and checkout (`fork_review_pins`), and still nothing of the
        # fork's; an errand's fence (no `fork_review`) is unchanged.
        groups.append(command_hook(f"python3 {fence_path(cfg)} {card_id}{fork_review}",
                                   matcher=BASH_MATCHER, timeout=10))
    if groups:
        hooks["PreToolUse"] = groups
    return hooks


def fork_review_pins(cfg: Config, card: dict) -> str:
    """The board fence's `--review` for a fork's review house, pinned to the card's own state
    directory and its checkout (c-730 fix check: the recorded `options.worktree`, else where
    Keel puts a card's first worktree), so its review steps reach nothing else."""
    checkout = (card.get("options") or {}).get("worktree") or adapters.worktree_dirs(cfg, card)[0]
    return (f" --review --card-dir {shlex.quote(str(cfg.card_dir(card['id'])))}"
            f" --worktree {shlex.quote(str(checkout))}")


def atlas_dir(cfg: Config) -> Path:
    """The Atlas, which every brief tells a house to read before it reads the code."""
    return cfg.root.joinpath(*ATLAS_DIR)


def atlas_deny(cfg: Config) -> list[str]:
    """Deny rules that make the Atlas add-dir read-only.

    An absolute path in a permission rule carries a DOUBLE leading slash: a single one
    anchors at the settings file instead of the filesystem root, so `Edit(/Users/...)`
    would match nothing and the deny would fail open.
    """
    return [f"{tool}(/{atlas_dir(cfg)}/**)" for tool in ATLAS_DENY_TOOLS]


def tier_files(cfg: Config) -> list[Path]:
    """The files Keel runs lines from, in EVERY space: each space's CLAUDE.md and that of each
    repo the install copied into it."""
    spaces = repolayout.spaces_of(cfg)
    if spaces is None:
        return []
    files = []
    for space in cfg.spaces.values():
        homes = [repolayout.home_of(path, spaces) for path in space.repos.values()]
        files += [spaces / space.name / repolayout.TIER] + [home / repolayout.TIER for home in homes if home is not None]
    return list(dict.fromkeys(files))


def tier_deny(cfg: Config, card: dict) -> list[str]:
    """Deny rules for the files Keel runs lines from (c-678 review F3, r2.F3), whatever
    space the card is in: a house of one space is not handed another space's files either.
    The four editing tools on each file's absolute path (the double leading slash anchors
    it, `atlas_deny`), and Bash on a command that spells that absolute path, as
    `secret_deny` does for the secrets. Never the bare file name: every repo has a CLAUDE.md
    of its own, and a command naming that one is the house's ordinary work.

    THESE RULES ONLY STOP THE PLAIN ATTEMPT. A shell can spell the path another way, and a
    program it runs can open the file. The mechanism is on the other side: a file that is
    no longer the text the user adopted or saved runs none of its lines and REFUSES the
    landing (`repocommands.refusal`, `merging.build_and_test`)."""
    rules = []
    for path in tier_files(cfg):
        rules += [f"{tool}(/{path})" for tool in ATLAS_DENY_TOOLS] + [f"Bash(*{path}*)"]
    return rules


# `housetier.KEY_NAME`, named here rather than imported: `keel/housetier.py` reaches this
# module through `keel/housetalk.py`, and `tests/test_house.py` holds the two to one path.
HOUSE_KEY_NAME = "house.key"


def secret_deny(cfg: Config) -> list[str]:
    """The machine's own secrets, denied to every house (c-451).

    `state/human.token` is him: a `kb` holding it is the human, so a house that read it could
    approve its own gate. `state/house.key` is the voice tier's local key (V12-12). Read gets
    the absolute path with the DOUBLE leading slash H6 requires; Bash gets the path and the
    bare file name anywhere in a command. These are rules for Claude's own tools and nothing
    more: a same-user shell can still spell a path some other way, or a program it runs can
    open the file, and the real boundary is a separate Unix user for the houses (a later
    card). The deny makes the plain attempt fail, and says the file is not the house's.
    """
    rules = []
    for path in (cfg.token_path, Path(cfg.state_dir) / HOUSE_KEY_NAME):
        rules += [f"Read(/{path})", f"Bash(*{path}*)", f"Bash(*{path.name}*)"]
    # The shared key (c-522): Bosun's key is derived from it (`keel/authority.py`), so a
    # house that read it could make its `kb` say `bosun`.
    from keel import housetier      # here: housetier reaches this module at import
    # Bosun's settings file carries Bosun's key itself (c-553).
    for path in (housetier.shared_path(cfg), housetier.bosun_settings_path(cfg)):
        rules += [f"Read(/{path})", f"Bash(*{path}*)", f"Bash(*{path.name}*)"]
    return rules


def memory_deny(cfg: Config) -> list[str]:
    """The install's memory root, denied to a house's editing tools and to any command that
    names it (c-722, r1.F2), the way `secret_deny` holds the secrets: it lives outside every
    worktree, and Bosun's guard holds it as its authority (`keel/authority.py`), so it changes
    on a card and never by a house writing the live files or rewinding their git history.
    Read stays open to Claude's Read tool; like `secret_deny`, the Bash rule stops only the
    plain spelling."""
    guarded = memoryroot.guarded(cfg)
    return [f"Edit(/{guarded}/**)", f"Bash(*{guarded}*)"] if guarded else []


def env_for(cfg: Config, card_id: str) -> dict:
    """The per-card environment in the settings file: its card, Keel's root, the house PATH.

    This is the environment the house's own shell sees (the process environment is the
    pre-spawning daemon's), so the no-browser rule has to be here as well as in
    `harness.child_env`: `etc/house-bin` first on PATH, where its `open` wins, and
    `LAVISH_AXI_NO_OPEN` for the lavish that reads it.
    """
    # KEEL_BOSUN emptied (c-553): a daemon whose first `--bg` launch carried Bosun's key hands
    # it to every spare it makes, and a house is never Bosun. Empty reads as unset
    # (`cli.resolve_actor`).
    # KEEL_CARD_DIR (c-604): the card's own directory, wherever `state_dir` puts it. The
    # brief guessed the card's directory under KEEL_HOME, wrong in the sandbox, and houses that reset
    # KEEL_HOME to find it broke their `kb` and the adapter's `pr`.
    env = {"KEEL_CARD": card_id, "KEEL_CARD_DIR": str(cfg.cards_dir / card_id),
           "KEEL_HOME": str(cfg.root), "KEEL_BOSUN": "",
           "PATH": config_module.house_path(cfg.root, os.environ.get("PATH", "")),
           "LAVISH_AXI_NO_OPEN": "1"}
    # EMPTIED, not left out, when the checkout's own toml is right: the process env is the
    # pre-spawning daemon's, and a daemon a sandbox's drain started first would hand its
    # sandbox toml to every later house in that config dir (empty reads as unset,
    # `config.config_path`).
    env["KEEL_CONFIG"] = named_toml(cfg) or ""
    return env


def named_toml(cfg: Config) -> str | None:
    """The toml a house's hooks must be handed, or None when the checkout's own is right.

    A Keel run under a toml of its own (the demo sandbox's, `KEEL_CONFIG`) has houses whose
    HOOKS and shell run `$KEEL_HOME/bin/kb` and `keel-review-stamp`. Without this they load
    `<root>`'s own config: a worktree's scratch board, or, run from the live checkout, the LIVE
    board, which is how a sandbox house's review stamp landed on the wrong board (c-570).
    The checkout's own toml is never passed: a named toml is taken at its word, and a house
    working in a Keel worktree must keep getting that worktree's scratch board. A scratch
    config passes nothing, for the reason `house_env` gives, and `env_for` then empties it.
    The rule itself is `config.named_toml`, which every service file is rendered by too.
    """
    return config_module.named_toml(cfg)


def settings_for(cfg: Config, card: dict) -> Path:
    """Write `state/cards/<id>/settings.json` (`settings_body`)."""
    path = cfg.card_dir(card["id"]) / "settings.json"
    path.write_text(json.dumps(settings_body(cfg, card), indent=2) + "\n")
    return path


def settings_current(cfg: Config, card: dict) -> bool:
    """True when the card's settings file already says what `settings_for` would write now
    (c-604: `keel-shipping-upgrade` proposed rewriting ones that were current)."""
    path = cfg.cards_dir / card["id"] / "settings.json"
    try:
        return json.loads(path.read_text()) == json.loads(json.dumps(settings_body(cfg, card)))
    except (OSError, ValueError):
        return False


def settings_body(cfg: Config, card: dict) -> dict:
    """The settings a card's house runs under: hooks, the space's deny list and the
    machine's secrets (`secret_deny`), the space's allow list, the env.

    A confined house with Bash also gets the board fence, which is why this asks the card
    rather than `placement`: `placement` cuts a repo card's worktree, and writing a
    settings file must not. It also gets the Atlas denied to the editing tools, so the
    directory `placement` opens for it stays one it reads.

    Every house runs with `worktree.bgIsolation` off and the two worktree tools denied
    (`WORKTREE_DENY`): its cwd is already where it works (c-605).

    The space's allow list (c-769) goes to a house with an open shell only, and only when
    it names something: under `--permission-mode auto` a command no rule settles is the
    classifier's to refuse, the space's own test command included, and an allow rule is
    read before it. A deny still beats an allow. A confined house gets none: its Bash is
    the board's by the fence, and its tool set and paths are not the space's to widen.
    """
    space = adapters.space_of(cfg, card)
    fenced = is_fenced(card)
    deny = (list(space.deny) + secret_deny(cfg) + list(WORKTREE_DENY)
            + adapters.extra_deny(cfg, card) + memory_deny(cfg))
    reviewed, peer = review_gate.wanted(cfg, card), review_gate.peer_wanted(cfg, card)
    settings = {"hooks": hooks_for(cfg, card["id"], fenced=fenced, reviewed=reviewed, peer=peer,
                                   shell=not is_restricted(card),
                                   full_max=review_stamp.full_rounds_max(cfg, card.get("space")),
                                   guarded=pack_guard(cfg, card),
                                   fork_review=fork_review_pins(cfg, card) if is_fork_review(card) else ""),
                "permissions": {"deny": deny},
                "env": env_for(cfg, card["id"]),
                "worktree": dict(BG_ISOLATION)}
    if reviewed or peer:
        deny += review_stamp.stamp_deny(cfg, card["id"])
    if is_restricted(card):
        deny += atlas_deny(cfg) + tiercards.read_only_deny(card)
    elif space.allow:
        settings["permissions"]["allow"] = list(space.allow)
    deny += tier_deny(cfg, card)
    hidden = repolayout.excludes((space.repo_path(key) for key in adapters.repos_of(card)),
                                 repolayout.spaces_of(cfg))
    if hidden:
        # A repo the install cloned (c-618): its team's CLAUDE.md is not this house's to read;
        # the tiers above the worktree are (`keel/repolayout.py`).
        settings["claudeMdExcludes"] = hidden
    return settings


# ----- brief -----

card_block = briefnews.card_block


def ensure_context(card_dir: Path, card: dict | None = None, plan_pages: bool = False) -> Path:
    """An empty `context.md` with the six headings, unless one is already there; with the
    plan pages on it opens as an outcome in the plan format (`planbrief.context_skeleton`)."""
    path = card_dir / "context.md"
    if not path.exists():
        path.write_text(planbrief.context_skeleton(card, plan_pages))
    return path


def ensure_theme(cfg: Config, card: dict) -> Path | None:
    """Copy the space's theme to `state/cards/<id>/theme.css`, so a surface only has to
    link it.

    The deck is this project's design system and the palette follows the space, so a plan,
    a report or a mockup a house writes should look like the board it belongs to rather
    than like whatever design system the tool that serves it happens to prefer. Making that
    a mechanism (the file is already there) rather than an instruction ("copy this first")
    is the difference between a rule a house follows and a rule a house remembers.

    It is COPIED, not linked: lavish serves a surface's local assets from the surface's own
    directory by a relative path, and an exported copy inlines what sits beside it. Copied
    on every start and resume too, so a palette change reaches a card that is already open.
    A space with no theme file of its own gets None, and the brief then promises nothing.
    """
    source = cfg.root / "app" / f"theme-{adapters.space_of(cfg, card).name}.css"
    if not source.is_file():
        return None
    target = cfg.card_dir(card["id"]) / THEME_FILE
    target.write_text(source.read_text())
    return target


def house_env(cfg: Config, card_id: str) -> dict:
    """The process environment plus the house's own, for a tool run on its behalf.

    A scratch config passes no `KEEL_CONFIG`, because a named toml is taken at its word
    (`keel/config.py`): handing a child this worktree's own file would send it straight to
    the live board the redirect just refused. `KEEL_HOME` is in `env_for`, so the child
    reaches the same decision from the same root.
    """
    env = dict(os.environ, **env_for(cfg, card_id))
    env.pop("KEEL_CONFIG", None)
    if cfg.source is not None and not cfg.scratch:
        env["KEEL_CONFIG"] = str(cfg.source)
    return env


def new_project_path(cfg: Config, card: dict) -> str | None:
    """The repository a new-project card opened, for the brief's own section.

    Read back from the card rather than remembered from the scaffold, so a resume tells
    the house the same thing its first turn was told.
    """
    keys = adapters.repos_of(card)
    if not keys or not adapters.new_project_wanted(card):
        return None
    path = adapters.space_of(cfg, card).repo_path(keys[0])
    return str(path) if path else None


def on_keel_itself(cfg: Config, card: dict) -> bool:
    """True when this card's repo is Keel's own checkout.

    Its worktree is then the only kind that carries Keel's config files, so it is the only kind that
    can load a config naming another checkout's board (`keel/config.py`, 2026-09-20). A house
    on any other repo is told nothing about it, because there is nothing there to tell.
    """
    space = adapters.space_of(cfg, card)
    path = space.repo_path(str(card.get("repo") or "")) if card.get("repo") else None
    return bool(path) and path.resolve() == cfg.root.resolve()


def app_block(cfg: Config, card: dict) -> str | None:
    """What the card's repo says about running its app (c-678): for a repo the install
    copied, the command its adopted CLAUDE.md names, or that its sessions run tests only
    until it names one. None for any other repo, which has no such file."""
    keys = adapters.repos_of(card)
    tier = repofile.tier_of(cfg, card.get("space"), keys[0]) if keys else None
    if tier is None:
        return None
    text = prompts.app_block(str(tier), repocommands.run_rule(cfg, card.get("space"), keys[0]))
    # review F3: a file that changed since it was adopted runs none of its lines, and the
    # brief says so. Where its landing will be refused too (a space with no pack whose test
    # command would have come from the file, `repocommands.landing`), no test run before
    # review counts as a pass. A space on a pack, or a config that names the tests, is told
    # nothing of the kind.
    why = repocommands.changed(cfg, card.get("space"), keys[0])
    if why and repocommands.refusal(cfg, card.get("space"), keys[0]):
        why += repocommands.NO_PASS
    return f"{text}\n{why}\n" if why else text


def abilities_block(cfg: Config, card: dict) -> str:
    """The "What you can do" block: `kb help`'s verbs, child cards, the surface, what the
    human sees. The space's name reaches it because the surface section names the theme
    file the copy came from, and the card's confinement does because a brief may not
    promise what the tool set denies."""
    text, warning = prompts.abilities(cfg, house_env(cfg, card["id"]),
                                      space=adapters.space_of(cfg, card).name,
                                      tools=tools_of(card), restricted=is_restricted(card),
                                      drop=(card.get("options") or {}).get("drop"),
                                      new_project=new_project_path(cfg, card),
                                      keel_repo=on_keel_itself(cfg, card),
                                      review=review_block(cfg, card),
                                      plan_pages=cfg.plan_pages, app=app_block(cfg, card),
                                      waiting=waiting_on(cfg, card))
    if is_fork_review(card):
        text += "\n" + prompts.FORK_REVIEW.format(review=cfg.root / "bin" / "keel-review") + "\n"
    if warning:
        prompts.note_in_log(cfg, f"brief for {card['id']}: {warning}; used the short verb list")
    return text


def waiting_on(cfg: Config, card: dict) -> list[dict]:
    """The cards that wait for this one (c-718 r1.F14), for a card of a stacking space: the
    plan names them and proposes each stacked or independent. Empty anywhere else."""
    if card.get("space") not in cfg.stacking:
        return []
    from keel.board import open_board     # noqa: PLC0415 - the board opens with the config's switches
    with open_board(cfg) as board:
        return stacking.waiting_cards(board, card["id"])


def review_block(cfg: Config, card: dict) -> str | None:
    """The brief's pre-gate pipeline section, and the requirements file it names, for a
    card the pipeline applies to (`keel/review/`); a review card's peer steps (lane RC);
    None for any other card."""
    peer = review_gate.peer_wanted(cfg, card)
    if not (peer or review_gate.wanted(cfg, card)):
        return None
    card_dir = cfg.card_dir(card["id"])
    review_gate.write_requirements(card_dir, card)
    if peer:
        return review_brief.peer_block(card_dir, target_of(cfg, card), cfg.root / "bin" / "keel-review",
                                       card.get("options") or {}, terms.of(cfg, card.get("space")))
    space = adapters.space_of(cfg, card)
    base = target_of(cfg, card)
    block = review_brief.brief_block(card_dir, base, cfg.root / "bin" / "keel-review",
                                     pipeline=space.pipeline, tests=house_tests(cfg, card, base),
                                     preship_first=space.preship_first and not at_shipping(card),
                                     full_max=review_stamp.full_rounds_max(cfg, card.get("space")),
                                     t=terms.of(cfg, card.get("space")),
                                     remote=config_module.remote_of(cfg, card.get("space")))
    return block + stack_apart(cfg, card, base)


def repo_bases(cfg: Config, card: dict) -> dict:
    """c-772: `{repo: base}` over the card's repos (`merging.base_in`, None where unread) when
    they are not all one base AND the card is stacked in only some of its repos; else empty.
    Before the parent lands that is every such card; after, the ones whose repos still differ."""
    if not stacking.split_repos(card)[1]:
        return {}
    found = {key: merging.base_in(cfg, card, key) for key in adapters.repos_of(card)}
    return found if len(set(found.values())) > 1 else {}


def stack_apart(cfg: Config, card: dict, base: str) -> str:
    """The review section's last paragraph for a card with a base per repo (`repo_bases`,
    `review_brief.per_repo_block`), before the card it is stacked on lands and after; else ""."""
    bases = repo_bases(cfg, card)
    if not bases:
        return ""
    stacked, apart = stacking.split_repos(card)
    return review_brief.per_repo_block(stacking.of(card)["on"], stacked, apart, bases, base,
                                       landed=not stacking.stacked_on(card), t=terms.of(cfg, card.get("space")))


def at_shipping(card: dict) -> bool:
    """A card at shipping (c-600): its house lives on and its push, `pr` and `publish` are
    refused there, so a brief written for it gets the serial pipeline, which names neither
    (c-597 review)."""
    return card.get("stage") == "shipping"


def house_tests(cfg: Config, card: dict, base: str) -> str | None:
    """The command the house runs before review: `[house_tests]` (targeted, c-544), else the
    repo's `[tests]`; `{base}` is the branch the card's change is taken against."""
    key = str(card.get("repo") or "").split(",")[0]
    # A command the config names is used whatever the repo file's standing (r2.D1). A file
    # that changed gives none of its own (`repocommands.landing`), and where its landing
    # will be refused the brief says no run counts as a pass (`app_block`).
    command = cfg.house_tests.get(key) or repocommands.tests_of(cfg, card.get("space"), key)
    return command.replace("{base}", base) if command else None


def target_of(cfg: Config, card: dict, key: str | None = None) -> str:
    """The branch the card's change is taken against in one of its repos: `key`, else its
    first, the one a brief's single base is (`merging.base_in`, the one rule: the stacked base
    in that repo, c-718 and c-772; its `options.base` when it names one, as a work card does;
    its repo's integration branch, c-526; the branch its worktree was cut from, r2.F1; its
    repo's usual branch, c-734). Where that rule has no answer, `main`, as it always was for
    a card's one base; a reader that must not guess asks `merging.base_in` itself."""
    found = merging.base_in(cfg, card, key)
    if found:
        return found
    adapters.space_of(cfg, card).repo_path(key or adapters.repos_of(card)[0])   # raises as it did
    return "main"


def reviewer_of(cfg: Config, card: dict) -> str | None:
    """The `--agents` value for this house: the reviewer and the verifier when the
    pipeline applies, or the card is a review card (peer mode, lane RC); a feature card's
    reviewer names its members and checks the cross-repo contract (lane GRP). Both run on
    the space's `reviewer_model`, `inherit` (the house's own) by default (c-633)."""
    wanted = review_gate.wanted(cfg, card) or review_gate.peer_wanted(cfg, card)
    members = (card.get("options") or {}).get("review_members") or []    # a feature card, lane GRP
    space = cfg.spaces.get(card.get("space") or "")
    return review_agents.agents_json(members=[m.get("label") for m in members],
                                     cross_repo=len({m.get("repo") for m in members}) > 1,
                                     t=terms.of(cfg, card.get("space")),
                                     model=getattr(space, "reviewer_model", None) or review_agents.INHERIT) if wanted else None


def refresh_requirements(cfg: Config, board: Board, card_id: str, agents: str | None) -> None:
    """The reviewer's intent brought up to date for this session: the card and his words
    since (RQ-1). Only for a house the review applies to; a failure never stops a launch."""
    if not agents:
        return
    try:
        review_gate.write_requirements(cfg.card_dir(card_id), board.get(card_id), board.events(card_id, last=0))
    except (OSError, Refused):
        pass


def record_reviewer(board: Board, card_id: str, session_id: str, agents: str | None) -> None:
    """Say on the card whether THIS session was started with the reviewer: the review gate
    holds only that session to it, never one started before (lane E, finding 6). Written
    only when it changes, so a card the review does not apply to gains no event."""
    wanted = session_id if agents else None
    if (board.get(card_id).get("options") or {}).get(review_gate.SESSION_OPTION) != wanted:
        board.set_fields(card_id, {"options": {review_gate.SESSION_OPTION: wanted}}, "drain")


def contract_path(cfg: Config, card: dict) -> Path:
    """The contract this house reads.

    The full one is a page of `kb` commands and two gates to walk between. A house with no
    Bash can run none of it, so it gets the drop contract instead: write the file, Keel
    files the card. Same two gates underneath, told in the terms that house has.
    """
    name = CONTRACT if has_bash(tools_of(card)) else DROP_CONTRACT
    return cfg.root / "etc" / name


def cut_block(cfg: Config, card: dict) -> str | None:
    """What was said while the card's worktree was cut (c-678 review F6): the notes
    `adapters.say_on_card` left (a fetch that could not bring in the team's commits, a
    CLAUDE.md whose lines did not run), so the session knows what it is building on. None
    when nothing was said."""
    from keel.board import open_board     # noqa: PLC0415 - the board opens with the config's switches
    with open_board(cfg) as board:
        said = [event["text"] for event in board.events(card["id"])
                if event["kind"] == "note" and (event.get("data") or {}).get(adapters.CUT)]
    if not said:
        return None
    return "### When this worktree was cut\n\n" + "\n".join(f"- {line}" for line in dict.fromkeys(said))


def brief_for(cfg: Config, card: dict) -> str:
    """Contract + what you can do + card block + the space half; written to `brief.md`."""
    contract = contract_path(cfg, card).read_text().strip()
    parts = [contract, abilities_block(cfg, card), card_block(card), cut_block(cfg, card),
             adapters.brief(cfg, card)]
    text = "\n\n".join(part for part in parts if part) + "\n"
    card_dir = cfg.card_dir(card["id"])
    (card_dir / "brief.md").write_text(text)
    ensure_context(card_dir, card, cfg.plan_pages)
    ensure_theme(cfg, card)
    return text


# ----- placement -----

def worktree_for(cfg: Config, card: dict) -> list[Path]:
    """The card's worktrees (adapter or git), recreated when the directory is gone."""
    return adapters.worktree(cfg, card)


def is_fork_review(card: dict) -> bool:
    """A review card of a pull request from a fork (c-730, `options.review_fork`, which the
    drain sets from the pack's row): code from outside the team, read and never run."""
    return review_gate.is_review_card(card) and bool((card.get("options") or {}).get("review_fork"))


def is_restricted(card: dict) -> bool:
    """A card with no repo is an errand: no worktree, and a tool set it does not choose. A
    fork's review card is confined too (c-730 r2.F3), in its checkout."""
    return not card.get("repo") or is_fork_review(card)


def tools_of(card: dict) -> str | None:
    """The card's tool list, or None for a repo card, which gets the full set."""
    if not is_restricted(card):
        return None
    if is_fork_review(card):
        return FORK_REVIEW_TOOLS
    return (card.get("options") or {}).get("tools") or ERRAND_TOOLS


def has_bash(tools: str | None) -> bool:
    """True when this tool list carries Bash. `prompts` owns the rule, because what the
    brief may promise and what the house may run have to be one answer."""
    return prompts.has_bash(tools)


def is_fenced(card: dict) -> bool:
    """A confined house that can run commands at all runs them behind the board fence.

    A worker.md naming Bash gets the fence too; one that names no Bash (the daybook's
    `tools: Read,Write`) has nothing to fence, and its finishing step is the Stop hook's
    (`board.file_drop`)."""
    return is_restricted(card) and has_bash(tools_of(card))


def restricted_add_dirs(cfg: Config, card: dict) -> tuple[Path, ...]:
    """What a confined house may open besides its own card directory.

    Its `options.add_dirs` (an ask card's segment), the segment its brief names and the
    directory its drop belongs in, and the Atlas, which every brief tells it to read. A
    brief may not name what the tool set denies, and `--restricted` denies every path but
    these, so the list is assembled from the same options the brief was written from.
    Missing directories are dropped: `--add-dir` refuses a path that is not there. Each is
    resolved, so a directory reached by two spellings (a card's own `add_dirs` and the
    segment its options name) is handed over once.
    """
    options = card.get("options") or {}
    found = [Path(directory) for directory in options.get("add_dirs") or ()]
    segment = cfg.segment_dir(options["segment"]) if options.get("segment") else None
    if segment:
        found.append(segment)
    if options.get("drop"):
        found.append(Path(options["drop"]).parent)
    found.append(atlas_dir(cfg))
    return tuple(dict.fromkeys(path.resolve() for path in found if path.is_dir()))


# c-730 r1.F1: a review card's house is a checkout of someone else's code (a stranger's fork
# on a public host), so it loads the user's settings and Keel's own `--settings`, never the
# reviewed repo's project or local settings files and the hooks they carry.
REVIEW_SETTING_SOURCES = "user"


def setting_sources(card: dict) -> str | None:
    """`--setting-sources` for the card's house: `user` for a fork's review card, else None
    (every source, as always: a review card of the team's own code, the work pack's among
    them, starts exactly as before c-730, r2.F1)."""
    return REVIEW_SETTING_SOURCES if is_fork_review(card) else None


def harness_flags(where: dict) -> dict:
    """`placement` as the keyword arguments every door into a card's house passes the harness
    (c-730 r2.F2): the start, the resume, the rotation's fresh start, the one-shot and streamed
    turns and the kept-alive conversation (through `housetalk.plan`). One place, so no door
    can leave a flag out."""
    return {"add_dirs": where["add_dirs"], "restricted": where["restricted"], "tools": where["tools"],
            "setting_sources": where.get("sources")}


def placement(cfg: Config, card: dict) -> dict:
    """Where and how the house runs: cwd, add_dirs, the errand confinement, and the setting
    sources it loads."""
    if is_fork_review(card):
        # c-730 r2.F3: confined in the fork's checkout, its card directory added for its record
        paths = worktree_for(cfg, card)
        record = cfg.card_dir(card["id"])
        record.mkdir(parents=True, exist_ok=True)
        extra = tuple(dict.fromkeys(Path(path).resolve() for path in
                                    (*paths[1:], record, *restricted_add_dirs(cfg, card))))
        return {"cwd": paths[0], "add_dirs": extra, "restricted": True, "tools": FORK_REVIEW_TOOLS,
                "sources": setting_sources(card)}
    if not is_restricted(card):
        paths = worktree_for(cfg, card)
        return {"cwd": paths[0], "add_dirs": tuple(paths[1:]), "restricted": False, "tools": None,
                "sources": setting_sources(card)}
    return {"cwd": cfg.card_dir(card["id"]), "add_dirs": restricted_add_dirs(cfg, card),
            "restricted": True, "tools": tools_of(card), "sources": setting_sources(card)}


def first_stage(card: dict) -> str:
    return "planning" if card["autonomy"] == "attended" else "building"


# ----- launch and resume -----

class SessionMoved(Refused):
    """The card's session is no longer the one the caller saw: someone else (the kick's
    carry, c-608 review) resumed it since, so a second resume would run it twice."""


class NoModel(Refused):
    """The card names no model, so its house is not started (or resumed) at all."""


def stopped_by_him(board, card_id: str) -> bool:
    """True when the card's house is down because HE stopped it (`views.stop_holds`): the
    drain resumes a house that exited on its own (a rate limit, a crash), never one he put
    down (c-605: it resumed one 11 s after his tap). His Resume or Retry ends it."""
    return views.stop_holds(reversed(board.events(card_id)))


def closed_while_idle(board, card_id: str) -> bool:
    """True when he closed the card's house while it was idle (`views.closed_idle`, c-607):
    the drain's resume of an exited house passes it over as it does his Stop, but a review
    batch, his gate tap or his Resume brings it back, with its conversation."""
    return views.closed_idle(reversed(board.events(card_id)))


def auto_resume_spent(board, card_id: str) -> bool:
    """The drain's one automatic resume of an exited house is spent: the newest turn start
    on record is that resume (`automatic` in its data). Any other start since (his Resume,
    a gate answer, a batch told) or his Retry gives the house its one again. Before c-605's
    review any `resume` spent it, so a house that exited after his Resume was blocked
    rather than put back once. A resume that started the house afresh, its conversation
    gone, spends it the same way (the note `afresh.start` leaves, c-654 review): a fresh
    house that dies too is blocked on the next pass, never started again every pass."""
    for event in reversed(board.events(card_id)):
        data = event["data"] or {}
        if event["kind"] == "note" and isinstance(data.get("afresh"), dict):
            return bool(data["afresh"].get("automatic"))
        if event["kind"] == "resume":
            return bool(data.get("automatic"))
        if event["kind"] == "stage" and data.get("to") == "assigned":
            return False
    return False


class AlreadyStarted(Refused):
    """Another starter on this machine got to the card first: not an error, not a block."""


class LiveHouse(AlreadyStarted):
    """The card's recorded session is still listed with a process: a start would be its
    twin, and nothing automatic stops the old one (c-605)."""


def live_twin(card: dict, row: dict | None) -> str | None:
    """Why a fresh house must not start beside `row`, the listing's row (or a door's facts)
    for the card's recorded session; None when there is no live one. Retry did (c-605): it
    started a second session and left the first alive."""
    if not card.get("session_id") or not housejobs.has_process(row):
        return None
    bg_id = row.get("id") or row.get("bg_id") or card["session_id"][:8]
    return (f"{card['id']}'s house {bg_id} is still live, so no second house was started: "
            f"Stop it first, or use Resume to carry on in it")


class Busy(Refused):
    """The card's session is working right now, so it is not resumed (E1, c-443)."""


class InTerminal(Busy):
    """He is in the card's conversation at a terminal, or Drop in has just handed him the
    command to be (U3), so it is not resumed. A `Busy` for every caller: a gate answer's
    move still lands, and a relayed or drain resume notes it rather than blocking."""


BUSY = "busy"


def refuse_if_busy(card: dict, config_dir) -> dict | None:
    """Raise `Busy` when the harness lists this card's session as working; else the row the
    listing holds for it (None for a session it does not list), which the resume reads once.

    A resume passes flags, and `claude --resume --bg` with flags on a RUNNING session starts
    a copy (2.1.280's help says so); the supersede rule would then stop the original in the
    middle of its turn, which is the one thing nothing automatic may do. So the listing is
    asked first, here, because every resume comes through here: the deck's tap, a relayed
    tap, a gate answer and the drain. The rule is `housejobs.working`, the one landing asks
    too (r-26): an idle live session, even one with a leftover background job, is resumed
    and superseded, and the supersede ends that job (`housejobs.stop`); only one in a turn
    is refused, and not even his gate answer (`force`) overrides
    it, since the stop would land on work in progress either way.
    """
    row = harness.find(card.get("session_id") or "", harness.agents(config_dir))
    refuse_if_in_terminal(card, row)
    if housejobs.working(row):
        raise Busy(f"{card['id']}'s house is working right now; a resume would copy it and stop "
                   f"the original mid-turn. Drop in to join it, or resume once its turn ends "
                   f"(the harness lists {housejobs.row_said(row)})")
    return row


def refuse_if_in_terminal(card: dict, row: dict | None) -> None:
    """Raise `InTerminal` when the session is running in a terminal, or a drop-in hold holds.

    Probed 2026-09-24 on 2.1.281: `claude --resume <uuid> --bg ...` on a session a terminal
    has open answers "started a copy", so the resume would fork the conversation he is
    typing into, and the supersede's `claude stop` does not reach his terminal. The row is
    the fact; the hold covers the minutes before his paste, when nothing is listed yet."""
    if row is not None and row.get("kind") == dropin.INTERACTIVE:
        raise InTerminal(f"{card['id']}'s conversation is open in a terminal; a resume would "
                         f"start a second copy of it. Carry on there, or quit it first")
    if views.dropin_holding(card.get("options")):
        raise InTerminal(f"Drop in handed you {card['id']}'s conversation to resume in a "
                         f"terminal, so it is not resumed here as well. Quit that session, "
                         f"or wait for the hold to run out if you never opened it")


def require_model(cfg: Config, board: Board, card: dict) -> str:
    """The card's model, or the card blocked with the reason and `NoModel` raised.

    Every card leaves create with a model now (`keel/cardspec.py`); one filed before that,
    or imported, can still carry none, and `claude` given no `--model` runs on the ACCOUNT's
    default: c-272 ran five days on Fable that way (c-434). Such a card is never started on
    a guess, not even the space's default: it is blocked, and naming the model is his.
    """
    if card.get("model"):
        return card["model"]
    space = cfg.spaces.get(card["space"])
    default = (space.model if space else None) or cfg.model
    reason = (f"no model on {card['id']}, and a house never runs on the account's default. "
              f"Name one (`kb set {card['id']} model={default}`, the space's default) and unblock it.")
    board.block(card["id"], reason, "drain")
    raise NoModel(reason)

class LockBusy(Exception):
    """The card's lock is held by someone else right now (`card_lock(..., wait=False)`)."""


@contextmanager
def card_lock(cfg: Config, card_id: str, wait: bool = True):
    """One per-card lock on this machine, `state/locks/card-<id>.lock`, around anything that
    starts a session for the card and records it (lane E round 3, finding 2): a resume and a
    rotation's fresh start can never interleave between the start and the `set_session`.
    `wait` False: `LockBusy` at once when it is held, for a drain step that must not sit
    behind a resume (`shipidle.settle_gone`, c-666)."""
    path = cfg.state_dir / "locks" / f"card-{card_id}.lock"
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "a") as handle:
        try:
            fcntl.flock(handle, fcntl.LOCK_EX if wait else fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise LockBusy(f"{card_id}'s lock is held") from None
        try:
            yield
        finally:
            fcntl.flock(handle, fcntl.LOCK_UN)


def launch(cfg: Config, board: Board, card_id: str, extra: str | None = None) -> dict:
    """Cut the worktree, write settings and brief, start the house, record and stage it.
    `extra` follows the brief in the first prompt: a shipping card with no house yet gets
    its first review batch that way (`keel/shipping.py`, c-600).

    A start that fails blocks the card with the reason, so it is neither retried every
    pass nor left silently at assigned.
    """
    card = board.get(card_id)
    model = require_model(cfg, board, card)
    space = adapters.space_of(cfg, card)
    agents = reviewer_of(cfg, card)
    try:
        where = placement(cfg, card)
        settings = settings_for(cfg, card)
        brief = brief_for(cfg, card) + (f"\n{extra}" if extra else "")
        trust.grant(space.config_dir, where["cwd"])     # 2.1.281 refuses an untrusted cwd
        result = harness.start_bg(
            where["cwd"], brief, name=card_id, config_dir=space.config_dir,
            settings_path=settings, model=model, agents=agents, **harness_flags(where))
    except (adapters.AdapterError, harness.HarnessError, OSError) as error:
        board.block(card_id, f"house failed to start: {error}", "drain", mark="mechanics")
        raise
    board.set_session(card_id, result["session_id"], "drain", bg_id=result["bg_id"],
                      app_link=app_link(result["bg_id"], space.config_dir))
    sessionorigin.declare(cfg.home, card, result["session_id"])
    record_reviewer(board, card_id, result["session_id"], agents)
    refresh_requirements(cfg, board, card_id, agents)
    if board.get(card_id)["stage"] == "assigned":
        board.stage(card_id, first_stage(card), "drain")
    return result


def one_house(start):
    """`launch` under the card's lock (`card_lock`): ONE house per card, whichever path
    starts it (c-601). The board's claim keeps two machines apart, but a claim from the same
    host is a no-op, so Retry's own `keel drain --once --card` and the looping drain on the
    same machine both passed it and started two houses. Under the lock the card is read
    again, and one no longer at the stage its caller EXPECTS (`expect`, `assigned` for the
    drain; a caller starting a house at another stage says which) or blocked is
    `AlreadyStarted`, and nothing is started. Wrapped rather than rewritten, so `launch`'s
    own text stays what other cards change."""
    @functools.wraps(start)
    def once(cfg: Config, board: Board, card_id: str, *args, expect: str = "assigned", **kwargs) -> dict:
        with card_lock(cfg, card_id):
            card = board.get(card_id)
            if card["stage"] != expect or card["blocked_reason"]:
                raise AlreadyStarted(f"{card_id} was started by another pass "
                                     f"(it is at {card['stage']} now, not {expect})")
            space = cfg.spaces.get(card["space"])
            twin = card.get("session_id") and live_twin(card, harness.find(
                card["session_id"], harness.agents(space.config_dir if space else None)))
            if twin:
                raise LiveHouse(twin)
            return start(cfg, board, card_id, *args, **kwargs)
    return once


# The start itself, for a caller that already holds the card's lock and has decided a house
# must start: a resume whose conversation is gone (`afresh.start`).
launch_here = launch
launch = one_house(launch)


def refuse_if_done(card: dict) -> None:
    """A done card has no house to resume, whoever asks (c-601, e2e bug 6): its worktree is
    reaped, and a resume ran a real turn there, recreating the directory, with nothing on the
    board to say so. A done card that needs more work is reopened, not resumed."""
    if card["stage"] == "done":
        raise Refused(f"{card['id']} is done; its house is not resumed ({worktree_state(card)})")


def worktree_state(card: dict) -> str:
    """Where a done card's worktree stands, as it is (c-604): the refusal said "gone" of a
    worktree the teardown had kept, which sent him looking for a loss that was not there."""
    from keel import teardown    # noqa: PLC0415 - teardown reaches the adapters, as this does
    kept = sorted(path for path in teardown.paths_of(card) if Path(path).is_dir())
    if kept:
        return f"its worktree is kept at {kept[0]}" + (f" and {len(kept) - 1} more" if len(kept) > 1 else "")
    return "its worktree is gone" if teardown.paths_of(card) else "it has no worktree"


def resume(cfg: Config, board: Board, card_id: str, prompt: str | None = None,
           force: bool = False, actor: str = "drain", tell: bool = False,
           when_busy: str = "refuse", background: bool = False, on_error=None,
           automatic: bool = False, expect_session: str | None = None) -> dict:
    """`resume_card` under the card's lock (`card_lock`). With `tell`, his tap: an idle live
    house is told `prompt` in its own session instead, and only an exited one is resumed
    (`keel/tellhouse.py`, c-598). `expect_session` is the session the caller's snapshot
    holds: the resume is refused (`SessionMoved`) when the card has moved on since."""
    if tell:
        from keel import tellhouse      # noqa: PLC0415 - tellhouse builds on this module
        return tellhouse.deliver(cfg, board, card_id, prompt, actor=actor, force=force,
                                 when_busy=when_busy, background=background, on_error=on_error)
    with card_lock(cfg, card_id):
        return resume_card(cfg, board, card_id, prompt=prompt, force=force, actor=actor,
                           automatic=automatic, expect_session=expect_session)


def resume_card(cfg: Config, board: Board, card_id: str, prompt: str | None = None,
                force: bool = False, actor: str = "drain", automatic: bool = False,
                expect_session: str | None = None) -> dict:
    """Continue the card's exited house with the same settings file; records `resume`.

    Refused while voice holds the card (`options.voice_hold`): a resume mid-conversation
    would take a turn into the same transcript he is talking into, which is the race the
    voice lock exists to stop. That covers the deck's Resume button and a relayed resume as
    well as the drain, because all three come through here. `force` is the human's own gate
    answer (Approve, Send back): he is plainly finished talking, so the hold is released as
    part of the tap rather than standing in its way.

    Refused too while the harness lists the session as BUSY (`refuse_if_busy`), whoever
    asks: a resume of a working session would copy it and then stop the original.

    A session whose conversation the harness says it no longer holds is not resumed at all:
    the launch would succeed and the session end with no turn (`harness.conversation_gone`,
    c-654). The house is started afresh from the card's record instead, or the card is
    blocked for him when the board contradicts the harness (`keel/afresh.py`).
    """
    card = board.get(card_id)
    if expect_session is not None and card.get("session_id") != expect_session:
        raise SessionMoved(f"{card_id} moved from session {expect_session} to "
                           f"{card.get('session_id')} since it was read; not resumed again")
    refuse_if_done(card)
    space = adapters.space_of(cfg, card)
    row = refuse_if_busy(card, space.config_dir)      # before the hold is touched: a refusal changes nothing
    held = views.voice_hold(card.get("options"))
    if held and not force:
        raise Refused(f"voice is talking to {card_id} until {held.get('until')}; "
                      f'say "back to Harbor" or wait for the hold to run out')
    if held:
        board.release_voice(card_id)
        board.note(card_id, "voice was holding this house; your answer at the gate "
                            "released it", "human")
    model = require_model(cfg, board, card)
    prompt = prompt or RESUME_PROMPT.format(stage=card["stage"])
    where = placement(cfg, card)
    from keel import afresh      # noqa: PLC0415 - afresh builds on this module
    if afresh.wanted(board, card, row, where["cwd"], space.config_dir):
        return afresh.start(cfg, board, card, prompt, actor, automatic=automatic)
    # A field changed since the house was briefed goes with the prompt, and the brief's card
    # block is rewritten once the resume took, so it is said once (c-533).
    card_dir = cfg.card_dir(card_id)
    news = briefnews.news(card_dir, card, board.events(card_id))
    if news:
        prompt = f"{prompt}\n\n{news}"
    # The settings file is REWRITTEN, not reused. Its hooks and its confinement are Keel's
    # own, so a card that is already open should be resumed under the current ones, the
    # same reason `ensure_theme` copies the theme again. c-271 was started before the board
    # fence existed and would otherwise have been resumed without it, forever.
    settings = settings_for(cfg, card)
    ensure_theme(cfg, card)
    agents = reviewer_of(cfg, card)
    trust.grant(space.config_dir, where["cwd"])
    result = harness.resume_bg(
        card["session_id"], prompt, cwd=where["cwd"], config_dir=space.config_dir,
        settings_path=settings, name=card_id, model=model, agents=agents, **harness_flags(where))
    fresh = result["session_id"] != card["session_id"]
    link = app_link(result["bg_id"], space.config_dir) if fresh else None
    # The resume is the drain's unless Bosun asked for it (a repair, c-575): the record
    # says who moved the house.
    # `automatic`: the drain's own resume of a house that exited (`drain.reconcile`), the
    # once-only one; his Resume, a gate answer or a batch is not, so it never spends it.
    record = dict(result, automatic=True) if automatic else result
    board.record_resume(card_id, actor, prompt, record, app_link=link)
    briefnews.refresh(card_dir, card)
    record_reviewer(board, card_id, result["session_id"], agents)
    refresh_requirements(cfg, board, card_id, agents)
    end_rotation(board, card)
    if fresh:
        sessionorigin.declare(cfg.home, card, result["session_id"])
        retire_superseded(board, card_id, card["session_id"], space.config_dir)
    return result


def end_rotation(board: Board, card: dict) -> None:
    """A resume after a rotation was asked moves the house on: the checkpoint it asked for is
    no longer the house's last word, so the rotation ends here (lane E, finding 2)."""
    if views.rotating(card.get("options")):
        board.set_fields(card["id"], {"options": {views.ROTATE_OPTION: None}}, "drain")
        board.note(card["id"], "rotation cancelled: the house was resumed after it was asked", "drain")


def wake(cfg: Config, board: Board, card_id: str) -> dict | None:
    """Put a stopped house back in the background with its own saved options, no prompt.

    What ends a voice conversation, and what the drain's repair runs on a hold that ran out.
    It is NOT a resume: no prompt, so no model turn and no tokens, and on 2.1.278 the session
    keeps its uuid and its claude.ai link, so the card needs no new session recorded. None
    when the harness already lists the session (nothing to do).

    A build of `claude` that does not keep a session's saved options answers with a COPY
    under a new id instead. That is a resume in all but name, so it is recorded like one and
    the card follows the session it actually has.
    """
    card = board.get(card_id)
    session_id = card.get("session_id")
    if not session_id:
        return None
    space = adapters.space_of(cfg, card)
    if harness.find(session_id, harness.agents(space.config_dir)):
        return None
    cwd = wake_cwd(cfg, card)
    trust.grant(space.config_dir, cwd)
    result = harness.wake(session_id, cwd=cwd, config_dir=space.config_dir, name=card_id)
    if result["session_id"] != session_id:
        board.set_session(card_id, result["session_id"], "drain", bg_id=result["bg_id"],
                          app_link=app_link(result["bg_id"], space.config_dir))
    return result


def wake_cwd(cfg: Config, card: dict):
    """Where a wake runs: the house's own directory, or the card's when that one is gone."""
    where = placement(cfg, card)
    return where["cwd"] if Path(where["cwd"]).is_dir() else cfg.card_dir(card["id"])


def retire_session(board: Board, card_id: str, session_id: str | None, config_dir,
                   why: str, actor: str = "drain") -> bool:
    """Stop a session that has nothing left to do, if the harness still lists it, and note
    it on the card, with the background jobs the stop ended (`keel/housejobs.py`). A session
    the harness no longer lists needs nothing. A failed stop is noted, never raised:
    whatever the caller did already succeeded."""
    if not session_id or not harness.find(session_id, harness.agents(config_dir)):
        return False
    bg_id = session_id[:8]
    try:
        ended = housejobs.stop(bg_id, config_dir, harness.stop)
    except harness.HarnessError as error:
        board.record_event(card_id, "note", actor, text=f"{why} {bg_id} could not be stopped: {error}")
        return False
    board.record_event(card_id, "note", actor, text=f"{why} {housejobs.stopped(bg_id, ended)}")
    return True


def retire_superseded(board: Board, card_id: str, old_session_id: str, config_dir) -> bool:
    """Stop the session a resume just replaced.

    `claude --resume --bg` mints a new session and leaves the old process idle; after a few
    send-backs a card trailed several of them (seen live on c-262, 2026-09-17). The old
    session is not live work: its conversation continued in the new one, so ending it is
    part of the resume, not an automatic stop of anything that was doing something."""
    return retire_session(board, card_id, old_session_id, config_dir, "superseded session")


def retire_finished(cfg: Config, board: Board, card: dict) -> bool:
    """Approve outcome accepted the work, so the card's house has nothing left: end it as
    part of that tap (seen live on c-262, 2026-09-17: the house sat idle after the merge).
    Never called by the drain; the tap is the human's. An errand's card directory is not
    its cwd again unless a later start trusts it again, so its trust entry goes too; a
    worktree's goes with the worktree (`merging.land_card`)."""
    space = adapters.space_of(cfg, card)
    trust.forget(space.config_dir, cfg.card_dir(card["id"]), cfg.state_dir)
    return retire_session(board, card["id"], card.get("session_id"), space.config_dir,
                          "finished house", actor="human")


APP_LINK_TRIES = 6
APP_LINK_PAUSE = 1.0


def app_link(bg_id: str, config_dir, tries: int = APP_LINK_TRIES) -> str | None:
    """Every house starts with `--remote-control`, so its log prints a claude.ai/code link
    a few seconds in; poll for it so `set_session` can keep it as `options.app_link`. A
    resume mints a new link with its new session, which is why a resume asks again. No
    link within the tries is not an error: the card just has no button this time."""
    for attempt in range(tries):
        try:
            link = harness.remote_link(bg_id, config_dir)
        except harness.HarnessError:
            link = None
        if link:
            return link
        if attempt + 1 < tries:
            time.sleep(APP_LINK_PAUSE)
    return None
