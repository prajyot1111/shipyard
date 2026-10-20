"""A tier proposed by an audit house and adopted by a person (c-618, a-84).

Propose files a personal errand (a card with no repo) that AUDITS the clone (a repo tier)
or every cloned repo of a space (the space tier): the code, config, CI, linters, tests,
commit history and the team's own CLAUDE.md and `.claude`, for the practices the repo
actually follows. It writes the tier from his preferences (his words, carried verbatim,
winning on a conflict) plus what the audit found, to `state/cards/<id>/claude-md.md`,
ending with an "Audit notes" section of each practice and its evidence, then stages
review. READ-ONLY BY MECHANISM: it is handed a disposable `git clone --shared` of each
clone under `state/cards/<id>/audit/<key>` as its add-dirs (`options.add_dirs`,
`house.restricted_add_dirs`), never the clone, and its editing tools are denied the real
clones (`options.tier_reads`, `read_only_deny`). Its cwd stays its card directory, so no
CLAUDE.md of a clone is loaded into it, only read as a file.

A DRAFT CARD (c-678) is the same proposal with another worker: Bosun, in conversation with
the user, in its own session. `open_draft` files it when a repo is copied in (the user's
tap, since only the user may make a proposal card), at `inbox`, so nothing starts on it.
Bosun stages it `building` when it starts and `review` when the draft is written, and
writes the draft in its own card folder, `<install>/builder/cards/<id>/claude-md.md`
(`draft_path`), reading the clone itself, which its guard keeps it from editing
(`builder.live_checkouts`). Setup's Propose takes over a draft card nobody has started.

Adopt, on a proposal at review, writes that file into the tier with its Audit notes
stripped, and removes the copies. Adopt is his tap and the card's outcome (c-621): the
verb (`onboarding.adopt_tier`) then moves the card to done and stops its finished house.
Approve outcome on the card is the same tap (c-667, `onboarding.adopt_proposal`), so the
card never closes without the tier written. Nothing removes the copies of a proposal that
is never adopted: no hook cleans a card's directory when it reaches done (they share their
objects, so they are small).
"""

from __future__ import annotations

import hashlib
import re
import shutil
import subprocess
from pathlib import Path

from keel import atomicfile, builder, pausewake, repofile, repolayout
from keel.config import Config
from keel.setupconfig import SetupError

OPTION = "tier_proposal"
READS = "tier_reads"        # the real clones the audit is about, denied to its editing tools
DRAFT = "tier_draft"        # a proposal Bosun drafts with the user, not an audit house's (c-678)
BOSUN_CARDS = "cards"       # <install>/builder/cards/<id>/: Bosun's own folder per card
AUDIT = "audit"             # state/cards/<id>/audit/<key>: the copies it reads
COPY_SECONDS = 300
DENY_TOOLS = ("Edit", "Write", "MultiEdit", "NotebookEdit")
PROPOSAL = "claude-md.md"
NOTES = "Audit notes"
NOTES_HEAD = re.compile(rf"^#+\s*{NOTES}\s*$", re.MULTILINE)
SUBJECT = {
    "repo": ("the repo tier of the `{key}` repo of the {space} space",
             "A copy of the clone, for you to read, is at {repos}.",
             "what a session working in this repo must know; leave out what applies to every repo of the space"),
    "space": ("the space tier of the {space} space", "Copies of its cloned repos, for you to read, are at {repos}.",
              "what every repo of the space shares; leave out what is true of one repo only"),
}
BRIEF = """Audit and propose {subject}.

{where} READ, never change: no edit, no commit, no command that writes there.

The user's preferences, in the user's words (they win wherever the audit disagrees):

{likes}

THE AUDIT. Do not summarise the team's file: find what the code actually does. Read the
code, its config, CI, linters and formatters, tests and how they run, and the commit
history (`git log`: branch and commit habits), and the team's own CLAUDE.md files and
`.claude/commands` and `.claude/skills` (not loaded into Keel's sessions, which is why this
card reads them). Find the standard practices followed: naming, structure, test commands,
lint and format, branch and commit habits. Note where the team's file disagrees with what
the code does.

THE PROPOSAL. Write it to {out}: {scope}, from the user's preferences plus the audit's findings,
in the pattern of the template below, under about forty lines. Never copy a secret, token
or private hostname, or anything about one session. End the file with a section headed
`## {notes}`: one line per practice found, with its evidence (a file path), and each
disagreement with the team's file. That section is for the user's review and is stripped when the user
adopts the proposal.

When the file is written, run `kb stage {card} review --output {out}`.

The template:

{template}
"""


DRAFT_BRIEF = """Draft {subject} with the user, in conversation, in Bosun's own session.

This card is Bosun's. No session is started on it: it waits at inbox until Bosun takes it.

{where} READ, never change: the guard refuses an edit there. Read the code, its config, its
tests and how they run, and the CLAUDE.md the team keeps inside the repo (Keel's sessions do
not load that file, which is why you read it once here). Then ASK the user what the code
does not say: how to prepare a fresh copy, how to run the tests, whether sessions may run
the app and how to run it without touching the user's own running copy, and the conventions
you could not infer. Do not ask where finished work lands: no line of this file decides it.

WHAT EACH LINE MAKES SHIPYARD DO, once the user adopts the file. Tell the user this when you
ask for the line, and when an ask's answer moves something (a command that will run, a file
that will be written, a branch), say what it moves in that option's own text:

{lines}

Write the draft to {out}: {scope}, in the shape of the template below. Keep the opening
words of the lines Keel reads (Prepare a fresh copy, Run the tests, Run the app), with each
command in backticks, and leave "Sessions run tests only until this section says how to run
the app." in place until the user has told you how to run it. Never copy a secret, a token
or a private hostname.

If you saw one small, real thing a first card could do in this repo (a README with no setup
section, a function with no test), leave it in one line, which the setup page offers the
user as their first card once this file is adopted:
`kb note {card} "First card: <what to do> (because <what you saw>)"`

Run `kb stage {card} building` when you start, and `kb stage {card} review --output {out}`
when the draft is ready. The user reads it on the setup page and presses Adopt; nothing is
written before that. When the user asks for a change, edit {out}: the page shows the file
as it is now.

The template:

{template}
"""
DRAFT_SUBJECT = {
    "repo": ("the CLAUDE.md of the `{key}` repo of the {space} space", "The repo is at {repos}."),
    "space": ("the workspace CLAUDE.md of the {space} space", "Its repos are at {repos}."),
}


def aim_of(space: str, key: str | None) -> str:
    return f"{space}/{key}" if key else space


def proposals(board) -> dict[str, dict]:
    """The newest open proposal per aim (`space/key`, or `space` for the space tier)."""
    found = {}
    for card in board.list_cards(include_archived=False):
        aim = (card.get("options") or {}).get(OPTION)
        if aim and card.get("stage") != "done":
            found[aim] = {"card": card["id"], "stage": card["stage"], "waiting": bool(card.get("blocked_reason")),
                          "draft": bool((card.get("options") or {}).get(DRAFT))}
    return found


def errand_space(cfg: Config) -> str:
    """Where the proposal card is filed: personal, else the first space with no pack."""
    if "personal" in cfg.spaces:
        return "personal"
    plain = [name for name, space in cfg.spaces.items() if space.adapter_dir is None]
    if not plain:
        raise SetupError("no space without a pack to file the proposal card in")
    return plain[0]


def propose(cfg: Config, board, space: str, key: str | None, repos: list[Path], likes: str) -> dict:
    """File the audit card for the tier of `space` (and `key`), reading `repos`."""
    aim = aim_of(space, key)
    open_one = proposals(board).get(aim)
    if open_one and open_one["draft"] and open_one["stage"] == "inbox":
        # a draft card nobody has started: the audit takes its place (c-678)
        board.set_fields(open_one["card"], {"options": {"archived": True}}, "human")
        board.note(open_one["card"], "set aside: Propose filed an audit of this tier in its place", "human")
        open_one = None
    if open_one:
        raise SetupError(f"{open_one['card']} is already proposing that tier ({open_one['stage']})")
    if not repos:
        raise SetupError(f"{space} has no cloned repo to audit")
    kind = "repo" if key else "space"
    title, where, scope = SUBJECT[kind]
    card = board.create(errand_space(cfg), f"Propose the {aim} tier", brief="", autonomy="autonomous",
                        options={OPTION: aim, READS: [str(r) for r in repos]}, actor="human")
    try:
        copies = [audit_copy(repo, cfg.card_dir(card) / AUDIT / repo.parent.name) for repo in repos]
    except SetupError as error:
        board.note(card, f"no audit copy, so no audit: {error}", "human")
        raise
    words = {"space": space, "key": key or "", "repos": ", ".join(str(c) for c in copies)}
    board.set_fields(card, {"options": {"add_dirs": [str(c) for c in copies]}}, "human")
    out = cfg.card_dir(card) / PROPOSAL
    brief = BRIEF.format(subject=title.format(**words), where=where.format(**words),
                         likes=likes.strip() or "(none given)", out=out, scope=scope,
                         notes=NOTES, card=card,
                         template=repolayout.template(cfg.root, kind, key=key or "", space=space))
    # The template is its plan, as a segment's worker.md is an ask card's (`fetch`): review
    # needs a plan_ref, and an errand has no plan of its own to write.
    plan = cfg.root / repolayout.TEMPLATES / f"{kind}.md"
    board.set_fields(card, {"brief": brief, "plan_ref": str(plan)}, "human")
    board.stage(card, "assigned", "human")
    return {"card": card, "aim": aim}


def bosun_folder(cfg: Config, card_id: str) -> Path | None:
    """Bosun's own folder for a card, `<install>/builder/cards/<id>`, or None off an install."""
    base = builder.clones(cfg)
    return base / BOSUN_CARDS / card_id if base is not None else None


def open_draft(cfg: Config, board, space: str, key: str | None, repos: list[Path]) -> str | None:
    """File the card on which Bosun drafts the tier of `space` (and `key`) with the user
    (c-678), or None when that tier already has an open proposal. At `inbox`, so the drain
    starts nothing on it; filed as the human, who alone may make a proposal card."""
    aim = aim_of(space, key)
    folder_of = bosun_folder(cfg, "x")
    if proposals(board).get(aim) or folder_of is None or not repos:
        return None
    kind = "repo" if key else "space"
    card = board.create(errand_space(cfg), f"Draft the {aim} CLAUDE.md", brief="", autonomy="autonomous",
                        options={OPTION: aim, READS: [str(r) for r in repos], DRAFT: True}, actor="human")
    title, where = DRAFT_SUBJECT[kind]
    words = {"space": space, "key": key or "", "repos": ", ".join(str(r) for r in repos)}
    brief = DRAFT_BRIEF.format(subject=title.format(**words), where=where.format(**words),
                               out=bosun_folder(cfg, card) / PROPOSAL, scope=SUBJECT[kind][2], card=card,
                               lines="\n".join(f"- {said}" for said in repofile.DOES.values()),
                               template=repolayout.template(cfg.root, kind, key=key or "", space=space))
    plan = cfg.root / repolayout.TEMPLATES / f"{kind}.md"
    board.set_fields(card, {"brief": brief, "plan_ref": str(plan)}, "human")
    pausewake.tell(board, card, "filed", cfg=cfg)   # c-734: asks the drain for one pass, whose wake tells Bosun
    return card


def audit_copy(repo: Path, into: Path) -> Path:
    """A disposable copy of a clone for the audit to read (`git clone --shared`: its objects
    are the clone's, and the clone gets no worktree entry). The audit house is handed this,
    never the clone, so nothing it runs can change the user's clone."""
    shutil.rmtree(into, ignore_errors=True)
    into.parent.mkdir(parents=True, exist_ok=True)
    done = subprocess.run(["git", "clone", "--quiet", "--shared", str(repo), str(into)],
                          capture_output=True, text=True, timeout=COPY_SECONDS)
    if done.returncode != 0:
        raise SetupError(f"could not copy {repo} for the audit: {done.stderr.strip()}")
    return into


def read_only_deny(card: dict) -> list[str]:
    """Deny rules that keep an audit house's editing tools off the real clones it was
    proposed for (the copies are what it reads); `house.settings_body` adds them. The
    double leading slash anchors an absolute path (`house.atlas_deny`)."""
    reads = (card.get("options") or {}).get(READS) or []
    return [f"{tool}(/{path}/**)" for path in reads for tool in DENY_TOOLS]


def stripped(text: str) -> str:
    """The proposal without its Audit notes section."""
    found = NOTES_HEAD.search(text)
    return (text[:found.start()] if found else text).rstrip() + "\n"


def draft_path(cfg: Config, card_id: str) -> Path:
    """Where a card's proposal is: the card's own directory (an audit house's), else Bosun's
    folder for the card (a draft Bosun wrote, c-678). Two fixed places and nothing a card
    names, so no card can point Adopt at a file of its choosing."""
    mine = cfg.card_dir(card_id) / PROPOSAL
    bosun = bosun_folder(cfg, card_id)
    if not mine.is_file() and bosun is not None and (bosun / PROPOSAL).is_file():
        return bosun / PROPOSAL
    return mine


def draft(cfg: Config, card_id: str) -> str:
    """The proposal a card holds now, or "" when it has none."""
    source = draft_path(cfg, card_id)
    return source.read_text() if source.is_file() else ""


def digest(text: str) -> str:
    """What names one draft: `onboarding.adopt_proposal` notes it, and skips a second write of it."""
    return hashlib.sha256(text.encode()).hexdigest()


def adopt(cfg: Config, board, card_id: str, tier_of) -> dict:
    """Write the proposal of `card_id` into the tier `tier_of(space, key)` names."""
    card = board.get(card_id)
    aim = (card.get("options") or {}).get(OPTION)
    if not aim:
        raise SetupError(f"{card_id} is not a tier proposal")
    if card.get("stage") != "review":
        raise SetupError(f"{card_id} is at {card.get('stage')}; a proposal is adopted at review")
    text = draft(cfg, card_id)      # read ONCE: the digest returned is of what is written
    if not text.strip():
        raise SetupError(f"{card_id} has no proposal at {draft_path(cfg, card_id)}")
    space, _, key = aim.partition("/")
    path = tier_of(space, key or None)
    atomicfile.write_text(path, stripped(text))
    shutil.rmtree(cfg.card_dir(card_id) / AUDIT, ignore_errors=True)
    return {"card": card_id, "tier": str(path), "digest": digest(text),
            "kept": "its audit notes left on the card"}
