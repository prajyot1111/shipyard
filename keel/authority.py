"""What actor `bosun` may do, in mechanism (c-517 BO-4, c-522, c-593; docs/atlas/96-bosun.md).

Bosun's memory says what it may and may not do; this module is what makes each rule a
refusal. It is an ALLOWLIST: a `kb` verb or a write that is not named here is refused to
actor `bosun`, so a Bosun that is confused, or misled by what it read, can do less than a
house and never more than him.

- **The key.** Actor `bosun` is a claim only a holder of Bosun's key can make: the key is
  derived from the machines' shared key (`housetier.shared_path`, the same file on the Mac
  and the box, denied to Bosun's tools), handed to Bosun's session in `KEEL_BOSUN` and to
  nothing else, and checked where the board lives (`cli.resolve_actor`, `actions.act`).
- **Where it may write.** With builder mode off: a block on any card, and the repairs
  below. Nothing else.
- **Repairs** (c-575, `keel/repair.py`). On any card, in every space, work included: the
  paths Keel reads, a house whose block Keel wrote, the stage the card is already at. Each
  is recorded, signed `bosun` with its `--why`; nothing counts them (c-593).
- **Builder mode** (`[keel] bosun_builder`, off by default; the Board's `bosun_builder`
  switch). While Keel is young, Bosun builds and lands Keel's own fixes: on personal cards
  whose worker is not a house (c-645) it creates, sets fields, moves stages, splits, notes,
  unblocks and archives, and approves
  an outcome. An outcome lands only on an integration branch, never the trunk, lints clean
  and carries a review stamp. A personal card's plan gate stays his. Its guard hook lets it
  write its authority files (never its settings). Work cards and the deploy tap stay his.
- **Which builder** (`[builder]`, c-619, `keel/builder.py`). The above is the superuser's
  (the Board's `builder_superuser` switch). The in-app builder an install ships with may not
  approve an outcome (landing is the user's tap), run `kb tested`, or file a card on a repo
  outside `[builder] repos` (`Board.builds`).

c-593 retired what came before builder mode: the console space (Bosun's own board), driving
a personal card (`options.driver`), his grant over its gates (`options.grant`, `kb grant`)
and the three strikes an hour. Old cards may still carry those options: nothing reads them.
"""

import hashlib
import hmac
import json
import os
import re
import shlex
from pathlib import Path

from keel import views

BOSUN = "bosun"
HUMAN = "human"
PERSONAL = "personal"
# The space Bosun's own board was until c-593. Its old cards stay on the board, done and
# archived, and load like any other; no card is filed there again (`refuse_create`).
RETIRED = "console"
KEY_LABEL = b"keel: the bosun actor"
# Bosun's repairs are recorded as this event kind (`keel/repair.py`).
INTERVENE_EVENT = "intervene"
# The `kb` verbs actor bosun may run at all; every other verb is refused before it runs.
VERBS = frozenset(("show", "list", "needs-you", "repos", "tree", "queue", "lint", "help",
                   "console", "create", "set", "stage", "approve", "note", "block", "unblock",
                   "split", "tested"))
# Bosun's own authority, relative to Keel's root: what its guard hook refuses it to write
# while builder mode is off (c-517: "never over Bosun itself").
# `consolehandoff` decides what Bosun keeps across a compaction (c-524), so it is one too, and
# `consoletaps` is console.py's own taps, moved out (c-531, c-553).
# `repair` is its repairs (c-575), split out of this module, and `repairhouse` carries a
# house repair to the house (c-593, out of the retired `drive`).
AUTHORITY_PATHS = ("bosun/memory", "state/console", "keel/authority.py", "keel/console.py",
                   "keel/consolehandoff.py", "keel/consoletaps.py", "keel/repair.py",
                   "keel/repairhouse.py")
# The same, relative to the install (c-722): Bosun's memory moved there (`keel/memoryroot.py`),
# and `bosun/memory` above is the checkout's, guarded while an install has not moved yet. The
# whole memory root is guarded (r1.F2): its git repo too, whose history is the memory's.
INSTALL_AUTHORITY_PATHS = ("memory",)
# The memory directories a Bash command may not write by any spelling (r1.F2, `bash_hits`):
# the checkout's, relative to Keel's root, and the install's (INSTALL_AUTHORITY_PATHS).
ROOT_MEMORY_DIRS = ("bosun/memory",)
# The Board switch that turns builder mode on (`Config.switches`, `[keel] bosun_builder`).
BUILDER = "bosun_builder"
# The Board switch that makes it the superuser builder (`[builder] superuser`, c-619): its own
# approvals and `kb tested`. Without it, builder mode is the in-app builder's (`keel/builder.py`).
SUPERUSER = "builder_superuser"
# The Board switch for an install's builder in bypass (`[builder] mode = "bypass"`, his call,
# 2026-10-03): it passes the plan and outcome gates of its own cards (`gate_approval`).
BYPASS = "builder_bypass"
IN_APP_LANDS = "landing is the user's tap: the in-app builder stages review, and Approve outcome lands it"


def refused(text: str) -> Exception:
    """`board.Refused`, imported here rather than above: the board calls this module."""
    from keel.board import Refused
    return Refused(text)


# ----- the key -----

def key_of(secret: str | None) -> str | None:
    """Bosun's key from the shared key's text, or None without one."""
    secret = (secret or "").strip()
    if not secret:
        return None
    return hmac.new(secret.encode(), KEY_LABEL, hashlib.sha256).hexdigest()


def bosun_key(cfg) -> str | None:
    """This machine's view of Bosun's key: None when it holds no shared key, and then no
    process here is ever `bosun`."""
    from keel import housetier
    path = housetier.shared_path(cfg)
    try:
        return key_of(path.read_text())
    except OSError:
        return None


def is_key(offered: str | None, expected: str | None) -> bool:
    if not offered or not expected:
        return False
    return hmac.compare_digest(str(offered).encode("utf-8", "surrogateescape"),
                               str(expected).encode("utf-8", "surrogateescape"))


# ----- reading a card -----

def options_of(card) -> dict:
    options = card["options"] if card is not None else None
    if isinstance(options, dict):
        return options
    return json.loads(options or "{}")


def builds(card, builder: bool) -> bool:
    """True when Bosun may act on this card as on its own: a personal card in builder mode
    whose worker he has not made a house (c-645: a house's card is never Bosun's to stage,
    set, split, note or unblock)."""
    return builder and card["space"] == PERSONAL and views.worker_of(card) != "house"


# ----- verbs and writes -----

def refuse_verb(actor: str, verb: str) -> None:
    if actor == BOSUN and verb not in VERBS:
        raise refused(f"kb {verb} is not Bosun's: it may read, build personal cards in builder "
                      f"mode, and repair (keel/authority.py)")


def refuse_create(space: str, options: dict | None, actor: str, builder: bool = False,
                  repo: str | None = None, scope=None) -> None:
    """No card is filed in the retired console space, by anyone (c-593); Bosun files only
    personal cards, and only in builder mode. `scope` is the in-app builder's repos (None for
    the superuser): it files no card on another repo (c-619)."""
    if space == RETIRED:
        raise refused(f"the {RETIRED} space is retired (c-593): Keel's own work is a personal "
                      f"card with its repo")
    if actor == BOSUN and not (builder and space == PERSONAL):
        raise refused(f"Bosun files cards only in the personal space, in builder mode, not "
                      f"{space}" + ("" if builder else " (builder mode is off)"))
    key = str(repo or "").split(",")[0].strip()
    if actor == BOSUN and scope is not None and key and key not in scope:
        raise refused(f"the in-app builder files cards only on {', '.join(sorted(scope)) or 'no repo'}, "
                      f"not {key}")


def refuse_tested(actor: str, board) -> None:
    """`kb tested` skips a deploy's suite on Bosun's word: the superuser's only (c-619)."""
    if actor == BOSUN and getattr(board, "builder", False) and not getattr(board, "superuser", False):
        raise refused("kb tested is the superuser builder's: the in-app builder's word skips no suite")


def housed(card) -> bool:
    """His choice that a house works this card (c-645), which `builds` says no to."""
    return views.worker_of(card) == "house"


def refuse_set(card, fields: dict, actor: str, builder: bool = False) -> None:
    if actor == BOSUN and not builds(card, builder):
        whose = "its worker is a house" if housed(card) else f"it is a {card['space']} card"
        raise refused(f"{card['id']}: {whose}, so Bosun changes no field of it "
                      f"(its title, brief, scope and autonomy are his)")


def refuse_move(card, actor: str, what: str = "moves", builder: bool = False) -> None:
    """A stage move or a split: Bosun's only on personal cards in builder mode."""
    if actor == BOSUN and not builds(card, builder):
        if housed(card):
            raise refused(f"{card['id']}'s worker is a house: Bosun {what} none of it, and its "
                          f"stages are his and the house's")
        raise refused(f"Bosun {what} only personal cards in builder mode; {card['id']} is "
                      f"{card['space']}, and its stages are his (a gate goes through `kb approve`)")


def refuse_mark(actor: str, mark: str | None) -> None:
    """A `--mark` (failed-resume, review-limit, permission-pause) is the drain's and the
    review gate's record of what kind of block it is. Bosun never writes one: its own marked
    block would read as Keel's (r-3, from BO-4's last delta check, 2026-09-26)."""
    if actor == BOSUN and mark:
        raise refused(f"--mark {mark} is the drain's and the review gate's record: Bosun never "
                      f"marks its own note or block")


def refuse_note(card, actor: str, builder: bool = False) -> None:
    """Bosun notes a card it builds (a personal card in builder mode), nothing else."""
    if actor == BOSUN and not builds(card, builder):
        raise refused(f"{card['id']} is not a card Bosun builds: Bosun writes no note on it")


def refuse_unblock(card, actor: str, builder: bool = False) -> None:
    """Bosun unblocks a card it builds, never one voice or a drop-in holds; any other block
    it lifts only as a repair (`--why`)."""
    if actor != BOSUN:
        return
    if not builds(card, builder):
        raise refused(f"{card['id']} is not a card Bosun builds: its block is his, or a repair "
                      f"(`kb unblock {card['id']} --why`) when Keel wrote it")
    options = options_of(card)
    if views.voice_hold(options) or views.dropin_holding(options):
        raise refused(f"{card['id']} is held (a voice conversation or a drop-in): Bosun waits")


RETRY_STAGES = ("assigned", "planning", "building")


def refuse_retry(card) -> None:
    """Bosun's retry is a fresh house for a card whose house failed or is stuck: never a card
    at his gate (it would throw the plan or the outcome away), never one he has not assigned,
    never one done or shipping."""
    at_plan_gate = (card["stage"] == "planning" and card["autonomy"] == "attended"
                    and card["plan_ref"] is not None)
    if card["stage"] not in RETRY_STAGES or at_plan_gate:
        raise refused(f"{card['id']} is at {card['stage']}"
                      f"{' with its plan at his gate' if at_plan_gate else ''}: a retry there "
                      f"is his")


# ----- gates -----

def gate_approval(card, gate: str, facts: dict | None, checked: str,
                  builder: bool = False, superuser: bool = True, bypass: bool = False) -> dict:
    """Bosun's approval of a gate, refused unless every rule holds; the event's data and the
    note that signs it when it does. Only on a personal card, only in builder mode, and every
    gate on a work card is his. A plan gate is his too (an attended card is how he asks to
    see a plan first), except for the builder in bypass, which he chose so that it does not
    stop to ask (`bypass`, his call 2026-10-03); the caller holds it to its own cards."""
    if card["space"] != PERSONAL:
        raise refused(f"{card['id']} is a {card['space']} card: its gates are his")
    if gate not in ("plan", "outcome"):
        raise refused("approve takes `plan` or `outcome`")
    if not builds(card, builder):
        raise refused(f"{card['id']}'s gates are his: Bosun approves an outcome only in "
                      f"builder mode")
    if gate == "plan" and not bypass:
        raise refused(f"{card['id']}'s plan gate is his: an attended card is how he asks to "
                      f"see a plan first")
    if not (superuser or bypass):
        raise refused(f"{card['id']}: {IN_APP_LANDS}")
    options = options_of(card)
    if views.voice_hold(options) or views.dropin_holding(options):
        raise refused(f"{card['id']} is held (a voice conversation or a drop-in): the gate "
                      f"waits for him")
    if not (checked or "").strip():
        raise refused("an approval by Bosun says what it checked: --checked \"<what>\"")
    if gate == "plan":
        said = checked.strip()
        return {"data": {"gate": "plan", "checked": said},
                "note": f"plan approved by bosun, in bypass. Checked: {said}" + ("" if said.endswith(".") else ".")}
    if facts is None:
        raise refused(f"Bosun's approval needs the {gate} read where the board lives")
    return outcome_approval("approved by bosun, in builder mode", facts, checked)


# ----- the outcome gate (c-526) -----

def outcome_facts(cfg, card: dict) -> dict:
    """What Bosun's approval of an outcome is checked against, read where the board lives:
    where it lands, the outcome's lint, whether the review stamp covers the branch, and the
    sha to pin. `errors` names what could not be read, which refuses too.

    The builder's card in bypass (`BYPASS`) has its branch fetched from its clone first, as
    the user's tap would (`merging.fetch_built`): the lint reads the outcome at that tip and
    the stamp is matched against it, a stack's included (`gate.built_covers`). In auto mode
    nothing reads that branch before the user's tap, and the approval is refused anyway."""
    from keel import builder, merging, plangate
    from keel.review import gate, stamp
    card_dir = cfg.cards_dir / card["id"]
    facts = {"integration": cfg.integration_of(card["space"], card.get("repo")), "errors": [],
             "sha": None, "trunk": None, "reviewed": False}
    fetch = BYPASS in getattr(cfg, "switches", ())
    found, empty, unread = None, False, None
    try:
        found = merging.placed(cfg, card, fetch=fetch)       # before the lint reads its tip
        empty = found is None and merging.nothing_to_land(cfg, card, fetch=fetch)
    except merging.MergeRefused as error:
        unread = str(error).splitlines()[0]
    context = card_dir / "context.md"
    if not context.is_file():
        facts["errors"].append(f"{card['id']} has no context.md to check")
    else:
        result = plangate.lint_file(context, card, root=plangate.card_root(cfg, card),
                                    board_of=plangate.board_resolver(cfg))
        facts["errors"] += [f"{f['rule']} {f['text']}" for f in result["findings"]
                            if f.get("level", "error") == "error"]
    every = stamp.read_rounds(card_dir)
    if every and not every[-1].get("complete"):
        facts["errors"].append(f"review pass {every[-1].get('round')} is still open")
    if unread:
        facts["errors"].append(unread)
    elif found is None and empty:
        # r-24: closing it without a merge is his Approve outcome, never a land relay.
        facts["errors"].append(f"{card['id']} has {merging.NOTHING_TO_LAND}; "
                               f"it closes on his Approve outcome")
    elif found is None:
        facts["errors"].append(f"{card['id']} has no branch to land")
    else:
        try:
            _, repo, worktree_path, branch, target = found
            facts["sha"] = merging.git(repo, "rev-parse", branch)
            facts["trunk"] = merging.trunk_of(repo)
            # The stamp is the harness's record of what was reviewed (a full pass, or a
            # fix check that moved it): Bosun approves only the change it covers, so no
            # commit lands under its signature unreviewed (review F3). The worktree it
            # lands, or for the builder's card the review it ran in its clones.
            if builder.clone_for(cfg, card) is not None:
                facts["reviewed"] = gate.built_covers(cfg, card, repo, facts["sha"], target)
            else:
                stamped = stamp.read_stamp(cfg, card["id"])
                root = gate.repo.root_key(worktree_path) if worktree_path.is_dir() else None
                facts["reviewed"] = bool(root) and gate.covers(stamped, {root: facts["sha"]})
        except merging.MergeRefused as error:
            facts["errors"].append(str(error).splitlines()[0])
    return facts


def outcome_refusal(facts: dict) -> str | None:
    """Why Bosun may not approve this outcome, or None when every check holds: it lands on
    an integration branch that is not the trunk, lints clean, carries a review stamp that
    covers the branch as it is, and has a sha to pin. (The Risk, open-findings and fence
    checks were for driven and console cards, and went with them in c-593: builder mode
    had already skipped them, his call on 2026-09-29.)"""
    if not facts.get("integration"):
        return ("this repo has no integration branch, so approving its outcome would put it "
                "live: that is his")
    if facts.get("integration") == facts.get("trunk"):
        return (f"the integration branch is {facts['integration']}, the branch the machines "
                f"run, so approving would put it live: that is his")
    if facts["errors"]:
        return f"the outcome does not check clean ({facts['errors'][0]}): it goes to him"
    if not facts.get("reviewed"):
        return ("no review stamp covers the branch as it is now (no complete review pass, or "
                "commits since it): it goes to him")
    if not facts.get("sha"):
        return "no branch sha to pin: it goes to him"
    return None


def outcome_approval(signed: str, facts: dict, checked: str) -> dict:
    why = outcome_refusal(facts)
    if why:
        raise refused(why)
    said = checked.strip()
    note = (f"{signed}. Checked: {said}" + ("" if said.endswith(".") else ".")
            + f" It lands on {facts['integration']}; main moves only on his deploy.")
    return {"data": {"gate": "outcome", "checked": said,
                     "lands_on": facts["integration"], "sha": facts["sha"]}, "note": note}


# ----- its own authority, as files -----

def authority_hit(root: Path, path: str, install: Path | None = None) -> str | None:
    """The authority path `path` falls under, relative to Keel's root or to the install, or
    None."""
    try:
        rel = Path(path).expanduser().resolve().relative_to(root.resolve()).as_posix()
    except (ValueError, OSError):
        rel = str(path).lstrip("./")
    found = under(rel, AUTHORITY_PATHS)
    if found or install is None:
        return found
    try:
        rel = Path(path).expanduser().resolve().relative_to(Path(install).resolve()).as_posix()
    except (ValueError, OSError):
        return None
    return under(rel, INSTALL_AUTHORITY_PATHS)


SHELL_PUNCTUATION = re.compile(r"[;&|()<]")
# The install's Bosun memory as text (fix check 2): a write whose command names it is refused
# however the rest is spelled (`$p`, a variable, a path relative to an unknown directory),
# exactly as before r1.F2, on top of `bash_hits`. No exclusion, by cwd or by spelling (the
# lesson of c-723): each one opened a hole. The cost is accepted: a shell write that spells
# an absolute path through Bosun's clone of the memory repo is refused too, so Bosun edits
# the clone's files with the editing tools (whose deny is path-precise) and runs git there
# with relative paths, which never spell this text.
INSTALL_TEXT_PATHS = ("memory/bosun",)


def inside(path: str, base: str) -> bool:
    return path == base or path.startswith(base + os.sep)


def text_hits(plain: str, install: Path | None) -> list[str]:
    """`INSTALL_TEXT_PATHS` named anywhere in a command's text (its quotes taken out), on an
    install."""
    if install is None:
        return []
    return [rel for rel in INSTALL_TEXT_PATHS if rel in plain]


def guarded_dirs(root: Path, install: Path | None) -> list[tuple[str, str, str]]:
    """`(name, base, directory)` of each memory directory `bash_hits` holds, absolute."""
    pairs = [(rel, root) for rel in ROOT_MEMORY_DIRS]
    pairs += [(rel, install) for rel in INSTALL_AUTHORITY_PATHS] if install is not None else []
    return [(rel, os.path.normpath(base), os.path.normpath(Path(base) / rel)) for rel, base in pairs]


def touches(path: str, base: str, guarded: str) -> bool:
    """Whether a write to `path` reaches `guarded`: the directory itself, a path inside it, or
    a directory that holds it below `base` (`rm -rf bosun` takes the memory with it)."""
    if path == guarded or path.startswith(guarded + os.sep):
        return True
    return path.startswith(base + os.sep) and guarded.startswith(path + os.sep)


def shell_words(command: str) -> list[str]:
    """The words of a command line, its quotes taken out, its operators made spaces and each
    `>` a word of its own, so the word after one is known as a redirect's target."""
    text = SHELL_PUNCTUATION.sub(" ", command).replace(">", " > ")
    try:
        return shlex.split(text)
    except ValueError:
        return text.split()


def expanded(value: str) -> str:
    """A word with `$HOME`, `${HOME}` and a leading `~` spelled out (fix check 2)."""
    home = os.environ.get("HOME", "")
    if home:
        value = value.replace("${HOME}", home).replace("$HOME", home)
    return os.path.expanduser(value)


def relative_bases(root: Path, cwd: str | None) -> list[str]:
    """What a relative word is resolved against: Keel's root always, and the session's working
    directory too when the hook's payload names it. The working directory only adds a reading,
    so it can refuse more and never exempts anything."""
    return [str(root)] + ([os.path.normpath(cwd)] if cwd else [])


def bash_hits(command: str, root: Path, install: Path | None, verb: bool, redirect: bool,
              cwd: str | None = None) -> list[str]:
    """The memory directories a Bash command writes, by any spelling (r1.F2, fix check 2): a
    word that `touches` one, absolute (or `~`, `$HOME`), relative (`relative_bases`), or the
    value of an `--opt=` word. `verb` says the command has a writing verb (rm, mv, cp, a git
    write, ...), `redirect` that it writes through `>`. With only a redirect, a word counts
    when it is absolute, right after `cd`, or a redirect's target, so `echo bosun > /tmp/x` is
    a sentence and not a path."""
    words = shell_words(command)
    hits = []
    for index, word in enumerate(words):
        for value in dict.fromkeys([word, word.split("=", 1)[-1]]):
            if not value or value.startswith("-") or value == ">":
                continue
            plain = expanded(value)
            spelled = plain.startswith("/") or index > 0 and words[index - 1] in ("cd", ">")
            for start in relative_bases(root, cwd):
                path = os.path.normpath(os.path.join(start, plain))
                for name, base, guarded in guarded_dirs(root, install):
                    if (touches(path, base, guarded) and (verb or (spelled and redirect))
                            and name not in hits):
                        hits.append(name)
    return hits


def under(rel: str, guarded_paths: tuple[str, ...]) -> str | None:
    for guarded in guarded_paths:
        if rel == guarded or rel.startswith(guarded + "/"):
            return guarded
    return None
