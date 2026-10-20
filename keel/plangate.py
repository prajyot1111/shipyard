"""The contract lint on the kb side: `kb lint`, and the refusal on `kb stage`.

A plan in the plan format (a `.md` that opens with frontmatter) is linted where the house
runs, BEFORE the stage move is written: at `kb stage <id> planning --plan <file>`
a plan with any error is refused with one line per finding, so a gate never opens on a plan
that asks nothing (c-208). At `kb stage <id> review` the same is done for the card's
`context.md` when it is in the format. A plan or a record without frontmatter is the old
markdown flow and is left alone: this is a prototype and the old flow must keep working.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

from keel import (adapters, artifacts, boards, config as config_module, merging, planformat, planlint,
                  planoutcome, planstate, repolayout, stacking)
from keel.board import Refused
from keel.review import gate as review_gate, ledger as review_ledger, stagecheck


LINTED_STAGES = ("planning", "review")


def git_root(start: Path) -> Path | None:
    try:
        done = subprocess.run(["git", "-C", str(start), "rev-parse", "--show-toplevel"],
                              capture_output=True, text=True, timeout=10)
    except (OSError, subprocess.SubprocessError):
        return None
    return Path(done.stdout.strip()) if done.returncode == 0 and done.stdout.strip() else None


def resolver_for(card: dict, root: str | None):
    """Refs resolve against the house's own checkout (`--root`, else the git checkout the
    command runs in, for a repo card only: an errand has no code to point at), and, for a
    cross-repo card, against each of its other repos' worktrees too (SH-12).
    A feature card's resolve against every member's worktree (`options.review_worktrees`)."""
    trees = [Path(path) for path in ((card.get("options") or {}).get("review_worktrees") or {}).values()]
    if trees:
        return AnyResolver([planlint.GitResolver(tree) for tree in trees])
    if root:
        return planlint.card_resolver(card, Path(root))
    if not card.get("repo"):
        return None
    return planlint.card_resolver(card, git_root(Path.cwd()))


def card_root(cfg, card: dict) -> str | None:
    """The card's own checkout, so a lint reads the same code whoever runs it (r-23, D1): its
    worktree (`dropin.cwd_of`), else its primary repo's checkout, else None and the caller's
    cwd as before. An errand has none: it has no code to point at."""
    from keel import dropin
    repos = [key.strip() for key in str(card.get("repo") or "").split(",") if key.strip()]
    if not repos:
        return None
    worktree = dropin.cwd_of(cfg, card)
    if worktree is not None:
        return str(worktree)
    space = cfg.spaces.get(card.get("space"))
    repo = space.repo_path(repos[0]) if space is not None else None
    return str(repo) if repo is not None and repo.is_dir() else None


class AnyResolver:
    """A feature card's refs (lane GRP): a `path:line` resolves when it does in any member's
    worktree, since the orientation's reading order runs across the repos."""

    def __init__(self, resolvers: list):
        self.resolvers = resolvers

    def __call__(self, path: str, start: int, end: int) -> str | None:
        reasons = [resolve(path, start, end) for resolve in self.resolvers]
        return None if None in reasons else reasons[0]


def board_resolver(cfg):
    """Board ids resolve against the boards on this machine (P2-7): None, or why not.
    `.pushed(ref)` is when the board was last drawn on, for C33 (c-602)."""
    def board_of(ref: str) -> str | None:
        try:
            boards.read_record(cfg, ref)
        except boards.BoardError as error:
            return str(error).split(":")[0]
        return None

    def pushed(ref: str) -> str | None:
        try:
            return boards.pushed_at(boards.read_record(cfg, ref))
        except boards.BoardError:
            return None
    board_of.pushed = pushed
    return board_of


def review_context(doc: dict, card: dict, path: Path, root: str | None) -> dict | None:
    """What a review card's lint knows beyond the file (lane RC): the core's rounds in the
    card directory beside it and the last round's ledger, against the house's checkout."""
    if doc["kind"] != "review" or not review_gate.is_review_card(card):
        return None
    cwd = Path(root) if root else git_root(Path.cwd())
    return review_ledger.context(card, path.parent, cwd)


def change_reader(card: dict, root: str | None, cfg=None):
    """What an outcome's `change:` claim is checked against (c-605): the card's branch over
    each repo's own base (`claim_base`) in every worktree of the card, read from the house's
    checkout (`--root`, else the card's own worktrees, else the one `kb` runs in). None for
    a card with no repo: it has no branch to disagree."""
    if not card.get("repo"):
        return None

    def read():
        first = Path(root) if root else own_tree(cfg, card)
        if first is None and not planlint.card_roots(card, None):
            first = git_root(Path.cwd())    # no tree of its own here: the one `kb` runs in
        return planoutcome.branch_change(card, first, lambda tree: claim_base(cfg, card, tree),
                                         config_module.remote_of(cfg, card.get("space")))
    return read


def repo_key_of(card: dict, root: Path) -> str | None:
    """Which of the card's repos a worktree is: by the recorded worktrees, else by the
    `<id>` / `<id>-<repo>` names `placement` gives them; None when neither says."""
    options, repos = card.get("options") or {}, adapters.repos_of(card)
    where = str(Path(root).resolve())
    recorded = dict(options.get("worktrees") or {}) if isinstance(options.get("worktrees"), dict) else {}
    if options.get("worktree") and repos:
        recorded.setdefault(repos[0], options["worktree"])
    for key, path in recorded.items():
        if str(Path(str(path)).expanduser().resolve()) == where:
            return key
    name = Path(root).name
    if name == card.get("id") and repos:
        return repos[0]
    prefix = f"{card.get('id')}-"
    if name.startswith(prefix) and name[len(prefix):] in repos:
        return name[len(prefix):]
    return repos[0] if len(repos) == 1 else None


def claim_base(cfg, card: dict, root: Path) -> str | None:
    """The branch one worktree's change is taken against (c-605 review: each repo its own):
    the base its pull request records (`options.prs[repo].base`), else the card's
    `options.base`, else that repo's integration branch where this machine has the config,
    else the branch its main checkout has out. None when the integration branch cannot be
    read: the claim is then not verified."""
    from keel.review import repo        # noqa: PLC0415 - git only when a claim is read
    options = card.get("options") or {}
    key = repo_key_of(card, root)
    stacked = stacking.base_of(card, key)
    if stacked:
        # c-718 r1.F7: a stacked card's claims are read on its parent's branch, in a repo the
        # parent names (c-772); in another, on that repo's own base below
        return stacked
    pr = (options.get("prs") or {}).get(key) if isinstance(options.get("prs"), dict) else None
    if isinstance(pr, dict) and pr.get("base"):
        return str(pr["base"])
    if options.get("base"):
        return str(options["base"])
    if key and cfg is not None and hasattr(cfg, "integration_of"):
        try:
            integration = merging.integration_ref(cfg, card.get("space"), key)
        except merging.MergeRefused:
            return None
        if integration:
            return integration
    return repo.main_branch(root)


def lint_file(path: Path, card: dict, root: str | None = None, events=None, board_of=None,
              cfg=None, role: str | None = None) -> dict:
    """`role` is what the file is to the card (`planlint.RECORD` or `PLAN`); without it, a
    `context.md` is the record and the card's `plan_ref` its plan (c-719 r2.F2)."""
    text = path.read_text(errors="replace")
    doc = planformat.parse(text, path.name)
    role = role or role_of(path, card)
    mismatch = planlint.follow_card(doc, card, path.name, role)      # c-719 r1.F1, r2.F2
    answered = planstate.state_of(events or [], "plan" if doc["kind"] == "plan" else "outcome")["answered"]
    result = planlint.lint(doc, repo_card=bool(card.get("repo")),
                           resolve=resolver_for(card, root), answered=answered,
                           board_of=board_of, card_id=card.get("id"),
                           ships=review_gate.started_with_pipeline(card),
                           review=review_context(doc, card, path, root),
                           since=planoutcome.approved_at(events if events is not None else card.get("events")),
                           written=planoutcome.written(card),
                           changed=change_reader(card, root, cfg))
    result = planlint.with_findings(result, mismatch)
    if role == planlint.RECORD:
        result = planlint.strict_record(result)              # c-719 r2.F8
    return dict(result, file=str(path), format=doc["format"])


def role_of(path: Path, card: dict) -> str | None:
    """The file's role for the card: its record, its plan (`plan_ref`), or neither."""
    if path.name == "context.md":
        return planlint.RECORD
    ref = str(card.get("plan_ref") or "")
    if not ref or ref.startswith("http"):
        return None
    try:
        same = artifacts.local_path(ref, config_module.repo_root()).resolve() == path.resolve()
    except OSError:
        return None
    return planlint.PLAN if same else None


def refuse_on_findings(result: dict, what: str) -> None:
    if result["ok"]:
        return
    lines = [f for f in planlint.lines_of(result) if " error: " in f]
    raise Refused(f"the {what} breaks the contract ({len(lines)}): " + " | ".join(lines)
                  + " (run `kb lint <id>` for the whole report)")


def stage_file(args, cards_dir: Path | None) -> tuple[Path | None, str]:
    """The file a stage move hands over: the `--plan` at planning, the card's record at
    review. Worked out from the arguments alone, so a move with nothing in the format costs
    no read of the card."""
    if args.stage == "planning":
        ref = args.plan
        return (Path(ref).expanduser(), "plan") if ref and str(ref).endswith(".md") else (None, "")
    if args.stage == "review" and cards_dir is not None:
        return cards_dir / args.id / "context.md", "record"
    return None, ""


def check_stage(args, card_of, cards_dir: Path | None, board_of=None, cfg=None) -> str | None:
    """Refuse a stage move whose plan or record is in the format and breaks the contract,
    a move to review that the pre-gate pipeline holds (`keel/review/stagecheck.py`), and a
    move to review of a card his Approve could not publish (`publishable_check`).

    `card_of()` reads the card (with its events) only when there is something to check:
    a file in the format, a card directory where the pipeline's review step has run, or a
    space whose adapter answers `publishable`. `cfg` defaults to the one `kb` loaded."""
    if getattr(args, "verb", "") != "stage" or args.stage not in LINTED_STAGES:
        return None
    cfg = cfg if cfg is not None else getattr(args, "config", None)
    card = contract_checks(args, card_of, cards_dir, board_of, cfg)
    if args.stage != "review":
        return None
    if getattr(args, "nothing_to_land", False):
        return None         # nothing to publish
    # Last: the base check may have sent the house to rebase, and a rebased head is one
    # that has to be pushed again.
    publishable_check(cfg, (lambda: card) if card is not None else card_of)
    return None


def nothing_to_land(cfg, card: dict, cards_dir: Path | None) -> bool:
    """The outcome says `change: none` AND the branch proves it, here on the house's machine:
    no commit over its base in any repo of the card (r-32, r-33: a card that only retargeted
    pull requests had nothing to review or publish, and the stamp, the preship order and the
    draft check left it no way to his gate). An unverifiable claim is not trusted."""
    if cards_dir is None or not card.get("repo"):
        return False
    record = Path(cards_dir) / card["id"] / "context.md"
    if not record.is_file():
        return False
    head = record.read_text(errors="replace")
    if not head.startswith("---"):
        return False
    meta = head.split("---", 2)[1] if head.count("---") >= 2 else ""
    claim = next((line.split(":", 1)[1].strip().lower() for line in meta.splitlines()
                  if line.split(":", 1)[0].strip().lower() == planoutcome.CHANGE_KEY), "")
    if claim != planoutcome.NO_CHANGE:
        return False
    # The card's own trees only, never the caller's checkout (c-622 r1.F3): the deck's `kb`
    # runs in the live one, whose clean branch would vouch for a card whose own is not here.
    facts = planoutcome.branch_change(card, own_tree(cfg, card), lambda tree: claim_base(cfg, card, tree),
                                      config_module.remote_of(cfg, card.get("space")))
    return bool(facts) and not facts.get("unverified") and not facts.get("commits")


def own_tree(cfg, card: dict) -> Path | None:
    """The card's own worktree on this disk (`dropin.cwd_of`), or None; its recorded
    worktrees are read beside it (`planlint.card_roots`)."""
    from keel import dropin
    if cfg is None or not hasattr(cfg, "card_dir"):    # a lint with no config to place it
        return None
    try:
        return dropin.cwd_of(cfg, card)
    except KeyError:                       # a space this config does not have
        return None


def contract_checks(args, card_of, cards_dir: Path | None, board_of, cfg) -> dict | None:
    """The pipeline's checks and the format lint; the card when one of them read it."""
    card = None
    if (args.stage == "review" and cards_dir is not None
            and (stagecheck.prepared(cards_dir / args.id) or preship_first_somewhere(cfg))):
        card = card_of()
        if nothing_to_land(cfg, card, cards_dir):
            args.nothing_to_land = True
    if (args.stage == "review" and cards_dir is not None and stagecheck.prepared(cards_dir / args.id)
            and not getattr(args, "nothing_to_land", False)):
        card = card_of()
        try:
            integration = (merging.integration_ref(cfg, card.get("space"), card.get("repo"))
                           if cfg is not None and hasattr(cfg, "integration_of") else None)
        except merging.MergeRefused as error:
            raise Refused(f"{card['id']}: its integration branch could not be read, so the "
                          f"base check cannot run: {str(error).splitlines()[0]}") from None
        # c-732: the card's own base as it applies (none on an integrated repo), never the raw option
        own = merging.card_base(cfg, card) if cfg is not None and hasattr(cfg, "integration_of") else stagecheck.OPTION
        stagecheck.check(card, cards_dir / args.id, integration,
                         config_module.remote_of(cfg, card.get("space")), own)
    # A card that verifiably has nothing to land skips it (r-32), wherever its claim says it
    # was started: since c-622 there is no other machine to defer to (r-51).
    if args.stage == "review" and cards_dir is not None and preship_first_somewhere(cfg):
        card = card or card_of()
        if preship_first(cfg, card) and not getattr(args, "nothing_to_land", False):
            stagecheck.preship_first_check(card, cards_dir / args.id,
                                           config_module.remote_of(cfg, card.get("space")))
    path, what = stage_file(args, cards_dir)
    if path is None or not path.is_file():
        return card
    if not path.read_text(errors="replace")[:4].startswith("---"):
        return card              # not the plan format: the markdown flow, unchanged
    card = card or card_of()
    refuse_on_findings(lint_file(path, card, events=card.get("events"), board_of=board_of,
                                 cfg=cfg, role=planlint.PLAN if what == "plan" else planlint.RECORD), what)
    return card


def preship_first_somewhere(cfg) -> bool:
    return any(getattr(space, "preship_first", False) for space in (getattr(cfg, "spaces", None) or {}).values())


def preship_first(cfg, card: dict) -> bool:
    """The card's space runs preship first (c-597), so `kb stage review` holds its order (c-604)."""
    space = (getattr(cfg, "spaces", None) or {}).get(card.get("space"))
    return bool(getattr(space, "preship_first", False))


def publishable_check(cfg, card_of) -> str | None:
    """c-551: a card reaches his outcome gate only when his Approve could publish it. The
    space's adapter answers (`adapters.publishable`), which holds the clone and the code
    host's credentials; its line names the fix. Reads the card only when some space has an
    adapter that answers. Returns this host when it asked."""
    if cfg is None or not any(adapters.has_verb(space, "publishable") for space in cfg.spaces.values()):
        return None
    card = card_of()
    try:
        missing = adapters.publishable(cfg, card)
    except adapters.AdapterError as error:
        raise Refused(f"{card['id']}: whether it can be published could not be checked, so it "
                      f"does not go to the user's gate: {error}") from None
    if missing:
        raise Refused(missing)
    return cfg.host


# ----- the stored plan_ref (c-574) -----

def absolute_plan_ref(ref: str, card_id: str, cards_dir: Path | None, home: Path,
                      worktrees: Path | None = None) -> str:
    """A `--plan` or `plan_ref=` as the board should store it: a local path made absolute.

    A relative ref was stored as typed, and every reader then resolved it against its own
    cwd, while the deck serves only an absolute path: c-573's plan existed and the deck showed
    none. So a relative ref is looked for where the house most likely meant it, in order: the
    caller's cwd, the card's own directory (the ref, then its bare name), the Keel home. The
    first that exists is stored; none is a refusal, never a ref that names nothing. A URL and
    an absolute path are stored as given, as before: a flow may set one before it writes it.
    A candidate inside a worktree is passed over: every path a card stores points outside
    every worktree, and a house's cwd is its worktree, where a `plan.md` would be reaped."""
    text = str(ref)
    if not text or "://" in text:
        return text
    path = Path(text).expanduser()
    if path.is_absolute():
        return str(path)
    card_dir = cards_dir / card_id if cards_dir is not None else None
    tried = [Path.cwd() / path, *([card_dir / path, card_dir / path.name] if card_dir else []),
             home / path]
    for candidate in tried:
        if candidate.exists() and not inside(candidate, worktrees) and not repolayout.in_tree(candidate, repolayout.spaces_named()):
            return str(candidate.resolve())
    raise Refused(f"no plan file at {text} outside a worktree: looked in {Path.cwd()}, "
                  f"{card_dir or 'no card directory here'} and {home}; write it in the card's "
                  f"directory or pass an absolute path")


def inside(path: Path, root: Path | None) -> bool:
    return root is not None and path.resolve().is_relative_to(root.resolve())


def normalise_plan_ref(args, cards_dir: Path | None, home: Path, worktrees: Path | None = None) -> None:
    """Rewrite `kb stage --plan` and `kb set plan_ref=` in place, before the move is written."""
    if args.verb == "stage" and getattr(args, "plan", None):
        args.plan = absolute_plan_ref(args.plan, args.id, cards_dir, home, worktrees)
    elif args.verb == "set":
        args.assignments = [assignment_of(item, args.id, cards_dir, home, worktrees)
                            for item in args.assignments]


def assignment_of(item: str, card_id: str, cards_dir: Path | None, home: Path,
                  worktrees: Path | None = None) -> str:
    name, sep, raw = item.partition("=")
    if name != "plan_ref" or not sep or not raw:
        return item
    return f"plan_ref={absolute_plan_ref(raw, card_id, cards_dir, home, worktrees)}"


def lint_payload(args, card: dict, cards_dir: Path | None, events=None, board_of=None) -> dict:
    """`kb lint <id> [--file <path>] [--root <dir>] [--outcome]`."""
    if args.file:
        path = Path(args.file).expanduser()
    elif args.outcome:
        if cards_dir is None:
            raise Refused("no card directory here to find context.md in; pass --file")
        path = cards_dir / card["id"] / "context.md"
    else:
        ref = card.get("plan_ref")
        if not ref:
            raise Refused(f"{card['id']} has no plan_ref yet; pass --file <plan.md>")
        path = artifacts.local_path(ref, config_module.repo_root())
    if not path.is_file():
        raise Refused(f"no file at {path}")
    return lint_file(path, card, root=args.root, events=events, board_of=board_of)


def render(args, result: dict) -> str:
    head = ("ok: the contract holds" if result["ok"] else "refused: the contract does not hold")
    counts = result.get("counts") or {}
    tail = (f" ({counts.get('decisions', 0)} decisions, {counts.get('questions', 0)} questions, "
            f"{counts.get('diagrams', 0)} diagrams)")
    return "\n".join([f"{result['file']}: {head}{tail}", *planlint.lines_of(result)])
