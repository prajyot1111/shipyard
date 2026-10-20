"""The `kb` command line: argparse for every board verb, nothing but parsing and printing.

Every verb prints JSON with `--json`, human text otherwise, and exits 1 with a one-line
reason on refusal. The actor is `house` when `KEEL_CARD` is set, `human` when
`KEEL_TOKEN` matches `state/human.token`, else `cli`. Every verb is one row of `VERBS`:
the parser is built from that table and `kb help` prints it, so the two cannot drift.
Each handler returns its payload and each row renders it.
`keel_main` is the `bin/keel` entry: `keel kb ...` and bare verbs route here; `drain`, `run` and `install` are parsed
here and handed to their modules (`run` threads every built role into one process).
`doctor` is role-less: it reports the setup and exits 1 when something is missing.
`converse`, `talker`, `voice` and `backup` hand their verbs to their own modules.
"""

import argparse
import functools
from contextlib import contextmanager, nullcontext
import json
import os
import sys
import threading
from dataclasses import dataclass, field
from pathlib import Path

from keel import adapters
from keel import config as config_module
from keel.config import human_token  # noqa: F401 - the token lives with the config; kept importable here
from keel import tree as tree_module
from keel import backup, boards, cardspec, console, converse, deckdigest, deployask, deckstate, doctor, drain, fetch, fetchloop, fetchpreview, house, housetier, importer, install, merging, rotate, serve, talker, voice
from keel import authority, flowfence, kick, onboarding, passlock, plangate, readiness, refinescope, repair, shipping, shipreplies, stacking, terms, views
from keel import asks as asks_module
from keel import requests as requests_module
from keel.board import ASSUMING_ACTORS, Board, Refused, checked_count, open_board

ROLES = ("drain", "serve", "fetch", "run", "install")
BUILT_ROLES = ("drain", "serve", "fetch")
# argparse learned `color` in 3.14; the box runs 3.12. See `verb_help`.
NO_COLOUR = {"color": False} if sys.version_info >= (3, 14) else {}


def run_serve(config, port: int | None = None, follow: bool = True) -> None:
    """The deck. `follow`: the deck restarts onto moved code itself, unless the drain shares
    its process (`role_run`) and restarts it between passes (c-637)."""
    serve.run(config, port=port, follow=follow)


RUNNERS = {"drain": drain.run, "serve": run_serve, "fetch": fetchloop.run}
HOOKS = ("Stop", "SessionEnd", "Notification")
# Set in Bosun's session only (`keel/console.py` names it too): its `kb` is actor `bosun`.
BOSUN_ENV = "KEEL_BOSUN"


# ----- actor and token -----

def resolve_actor(requested: str | None, token_path: Path, bosun_key: str | None = None) -> str:
    """`house` under KEEL_CARD, `human` with the right token, else `cli` or `--actor`.

    A house may not name another actor: the environment says which house it is, and some
    fields are refused to it by actor (`board.HOLD_ACTORS`).
    """
    expected = human_token(token_path)
    token = os.environ.get("KEEL_TOKEN") or ""
    is_human = config_module.same_secret(token, expected)
    # BOSUN IS NEVER HIM (c-519), AND ONLY BOSUN IS BOSUN (c-522). Its session is started
    # with Bosun's key in `KEEL_BOSUN` (`keel/console.py`), and that wins over a token and
    # over `--actor`, the way `KEEL_CARD` does for a house. The key is checked here, where
    # the board is opened: a flag without it is refused, never taken as Bosun, because what
    # `bosun` may do (`keel/authority.py`) includes landing an outcome in builder mode.
    if os.environ.get(BOSUN_ENV):
        if os.environ.get("KEEL_CARD"):
            # A house that sets the flag is still a house: Bosun has no card.
            raise Refused(f"{BOSUN_ENV} and KEEL_CARD together: a house is never Bosun")
        if not authority.is_key(os.environ.get(BOSUN_ENV), bosun_key):
            raise Refused(f"{BOSUN_ENV} does not hold Bosun's key here, so this is not Bosun "
                          f"(a new shared key needs a Restart of Bosun)")
        if requested and requested != "bosun":
            raise Refused(f"--actor {requested} is not Bosun's to claim; {BOSUN_ENV} says "
                          f"this is Bosun")
        return "bosun"
    if requested == "bosun":
        raise Refused(f"--actor bosun is Bosun's session's alone ({BOSUN_ENV})")
    if requested == "human" and not is_human:
        raise Refused("--actor human needs KEEL_TOKEN to match state/human.token")
    # A HOUSE STAYS A HOUSE. `KEEL_CARD` is what the harness gives a house's own shell, and
    # `--actor` is not a way out of it: without this, a house could write the fields its
    # actor is refused (`options.voice_hold`, which would make it undrainable) by naming
    # another actor on the line.
    if requested and requested != "house" and os.environ.get("KEEL_CARD"):
        raise Refused(f"--actor {requested} is not a house's to claim; KEEL_CARD says "
                      f"which house this is")
    if requested:
        return requested
    if os.environ.get("KEEL_CARD"):
        return "house"
    return "human" if is_human else "cli"


# ----- parsing helpers -----

def parse_value(raw: str):
    """`null` means None, valid JSON decodes, anything else stays a string."""
    if raw == "null":
        return None
    try:
        return json.loads(raw)
    except ValueError:
        return raw


def parse_assignment(item: str) -> tuple[str, object]:
    name, sep, raw = item.partition("=")
    if not sep or not name:
        raise Refused(f"expected field=value, got {item!r}")
    return name, parse_value(raw)


def parse_fields(items: list[str]) -> dict:
    """`field=value` pairs; `options.k=v` goes into the options dict."""
    fields: dict = {}
    for item in items:
        name, value = parse_assignment(item)
        if name.startswith("options."):
            fields.setdefault("options", {})[name[len("options."):]] = value
        else:
            fields[name] = None if value is None else str(value)
    return fields


def parse_options(items: list[str] | None) -> dict:
    return dict(parse_assignment(item) for item in items or [])


def slice_repo(piece: dict, value: str) -> None:
    piece["repo"] = ",".join(key.strip() for key in value.split(",") if key.strip())


def slice_stack(piece: dict, value: str) -> None:
    piece.setdefault("options", {})[stacking.OPTION] = value


# What a part of a `--slice` after its brief sets, by the marker it starts with: c-718's
# `stack=`, the owner's stacked or independent answer, and c-771's `repo=`, the slice's own
# repos. A new kind of part is a marker and its setter here, and nothing in `parse_slice`.
SLICE_PARTS = {"repo=": slice_repo, "stack=": slice_stack}


def parse_slice(text: str, earlier=()) -> dict:
    """One `--slice`, `title|brief[|after-title|...][|repo=key[,key]][|stack=choice]`.

    The first part is the title and the second the brief, whatever they spell. A part after
    them that is exactly the title of an earlier slice of the same split (`earlier`) is an
    after-title, whatever it spells. Any other one that starts with `repo=` or `stack=`
    (`SLICE_PARTS`) sets that, the last of each winning, and every part left is an
    after-title. So an `=` in a title, a brief or an after-title is only text, and a slice
    titled `repo=api` can still be waited for."""
    parts = text.split("|")
    if not parts[0]:
        raise Refused(f"a slice needs a title: {text!r}")
    piece = {"title": parts[0], "brief": parts[1] if len(parts) > 1 else ""}
    afters = []
    for part in parts[2:]:
        marker = None if part in earlier else next((m for m in SLICE_PARTS if part.startswith(m)), None)
        if marker:
            SLICE_PARTS[marker](piece, part[len(marker):])
        elif part:
            afters.append(part)
    if afters:
        piece["after"] = afters
    return piece


def read_stdin_json() -> dict:
    """The hook payload on stdin; empty or absent stdin is an empty payload."""
    if sys.stdin is None or sys.stdin.isatty():
        return {}
    raw = sys.stdin.read().strip()
    if not raw:
        return {}
    try:
        return json.loads(raw)
    except ValueError:
        return {"raw": raw}


# ----- printing -----

def card_line(card: dict) -> str:
    """One card as a row: id, space, where it is, title, and its flags.

    A TRACKING card says `tracking` where a stage would go, and its flag carries the tally
    of its slices rather than the stage it borrows from them. `building` there reads as a
    house that is working, on a card whose own house has nothing left to do (c-277,
    2026-09-20). `kb show` still prints the card's own stored stage under the line.
    """
    flags = []
    if card["derived"]["needs_you"]:
        flags.append("needs you")
    if card["derived"].get("landing"):
        flags.append("landing")
    if card["blocked_reason"]:
        flags.append("blocked")
    if card["derived"]["backlog"]:
        flags.append("backlog")
    if card["derived"]["tracking"]:
        flags.append(f"tracking: {card['derived']['tracking_tally']}")
    suffix = f"  [{', '.join(flags)}]" if flags else ""
    where = "tracking" if card["derived"]["tracking"] else card["stage"]
    return f"{card['id']}  {card['space']:<8} {where:<9} {card['title']}{suffix}"


def card_text(card: dict, events: list[dict]) -> str:
    lines = [card_line(card)]
    if card["derived"]["tracking"]:
        lines.append(f"  stage: {card['stage']} (its own; a tracking card follows its children)")
    for name in ("autonomy", "repo", "model", "topic", "blocked_reason", "session_id", "plan_ref",
                 "output_ref", "parent", "after", "from", "created_at", "updated_at"):
        if card[name] is not None:
            lines.append(f"  {name}: {card[name]}")
    if card["derived"]["follow_ups"]:
        lines.append(f"  follow-ups: {', '.join(card['derived']['follow_ups'])}")
    if card["options"]:
        lines.append(f"  options: {json.dumps(card['options'])}")
    lines.append(f"  derived: {json.dumps(card['derived'])}")
    if card["brief"]:
        lines.append("")
        lines.append(card["brief"])
    if events:
        lines.append("")
        lines.extend(f"  {e['at']}  {e['kind']:<8} {e['actor']:<7} {e['text'] or ''}" for e in events)
    return "\n".join(lines)


def emit(args, payload, text: str | None) -> None:
    """The payload as JSON under `--json`, else the text; a None text prints nothing.

    The verb's `aside` goes to stderr first, in both forms: stdout is what a caller parses.
    """
    verb = VERB_BY_NAME.get(getattr(args, "verb", None) or "")   # `keel doctor` emits too
    said = verb.aside(args, payload) if verb is not None and verb.aside else None
    if said:
        print(said, file=sys.stderr)
    if getattr(args, "json", False):
        print(json.dumps(payload, indent=2))
    elif text is not None:
        print(text)


# ----- verbs -----

def new_project_fields(args) -> tuple[str | None, dict, str | None, set]:
    """`--new-project <name>`: the repo, the option that lets placement open it, the
    autonomy a first card on a fresh repository gets, and which of them were assumed.

    Attended by default, because the first card on an empty repository decides what the
    project IS and that is his call, not a house's. `--autonomy` still wins when it was
    given, which is why the flag's own default is None; the attended default is recorded
    as ASSUMED, not stated, so the readback says it. With no `--new-project` an absent
    autonomy stays None and the card resolver fills it (`keel/cardspec.py`).
    """
    options = parse_options(args.option)
    if not args.new_project:
        return args.repo, options, args.autonomy, set()
    if args.repo:
        raise Refused("give --repo or --new-project, not both")
    options["new_project"] = True
    return args.new_project, options, args.autonomy or "attended", (
        set() if args.autonomy else {"autonomy"})


def assumed_of(args) -> set:
    """`--assumed repo,topic`: the fields given on the line that were a guess, not his words."""
    return {name.strip() for name in (args.assumed or "").split(",") if name.strip()}


def refuse_unknown_repo(config, space_name: str, value) -> None:
    """Every key in a card's `repo` (a comma list) must be one its space can open: listed in
    `[spaces.<s>.repos]`, or a project under its `projects_dir` (c-509: a house set a key
    nobody had listed, and the card could never cut a worktree). Empty clears it.

    A space that lists no repo and has no projects directory can open none, so any repo is
    refused with the sentence its readiness row says (c-631)."""
    space = (config.spaces or {}).get(space_name) if config else None
    if space is None or not value:
        return
    if not space.repos and space.projects_dir is None:
        raise Refused(readiness.refusal(config, space, "repos"))
    keys = [key.strip() for key in str(value).split(",") if key.strip()]
    unknown = [key for key in keys if space.repo_path(key) is None]
    if unknown:
        known = sorted(space.repos) + [key for key in space.projects() if key not in space.repos]
        # c-631: while no repo is cloned, the Cards panel's sentence leads
        lead = readiness.refusal(config, space, "repos")
        raise Refused(f"{lead + '; ' if lead else ''}{', '.join(unknown)} is not a repo the "
                      f"{space_name} space can open ({', '.join(known) or 'it lists none'}); "
                      f"`kb repos` lists them, and a repo missing there is added to the config first")


def cmd_create(board, args, actor):
    if assumed_of(args) and actor not in ASSUMING_ACTORS:
        raise Refused(f"--assumed is the capture refine's, not {actor}'s")
    repo, options, autonomy, assumed = new_project_fields(args)
    if getattr(args, "worker", None):
        options = dict(options, worker=args.worker)      # c-645: who works it, checked by the board
    if not options.get("new_project"):
        refuse_unknown_repo(args.config, args.space, repo)
    card_id = board.create(
        args.space, args.title, brief=args.brief or "", autonomy=autonomy,
        repo=repo, model=args.model, parent=args.parent, after=args.after or None,
        from_card=args.from_card, options=options, actor=actor, topic=args.topic,
        assumed=assumed | assumed_of(args))
    card = board.get(card_id)
    return dict(card, readback=cardspec.readback(card, board.defaults))


def create_aside(args, card) -> str | None:
    """What `kb create` says on stderr: the readback, the errand line under it, and the
    block of a slice that was filed held (c-760, as `split_aside` says it)."""
    said = [card.get("readback"), stack_aside(card), errand_aside(args, card), blocked_aside(card)]
    return "\n".join(line for line in said if line) or None


def stack_aside(card) -> str | None:
    """c-772: a card stacked in only some of its repos says which under its readback."""
    said = stacking.spread_of(card)
    return f"{card['id']} is {said}" if said else None


def blocked_aside(card) -> str | None:
    return f"{card['id']} is blocked: {card['blocked_reason']}" if card.get("blocked_reason") else None


def errand_aside(args, card) -> str | None:
    """The line `kb create` says about a card with no repo, after its id.

    Three cards filed on 2026-09-19 (c-296, c-297, c-298) named a code fix and carried no
    repo, so none of them could ever have built. It is not a refusal: an errand with no
    repo is a real kind of card. It goes to stderr because the id on stdout is what a
    caller reads (`actions.run_kb` parses it, the tests assert on it).
    """
    if card["repo"] is not None:
        return None
    return (f"{card['id']} is an errand: no repo, so it gets no worktree and cannot change "
            f"code. Pass --repo <name> if it should.")


def cmd_repos(board, args, actor):
    """Every repo key a card may name, per space: the listed ones and the projects.

    A read verb rather than a memory: the talker and the voice have to offer him the
    choices when his words do not settle the repo, and reciting repo names from memory is
    how c-296, c-297 and c-298 were filed with none at all (2026-09-19). The two sources
    are the two `Space.repo_path` resolves: `[spaces.<s>.repos]` in the install's `config.toml`, and the
    git repos sitting under the space's `projects_dir`.
    """
    spaces = args.config.spaces
    if args.space and args.space not in spaces:
        raise Refused(f"unknown space {args.space!r}; one of {', '.join(spaces)}")
    rows = []
    for name, space in spaces.items():
        if args.space and name != args.space:
            continue
        for key in sorted(space.repos):
            rows.append({"space": name, "repo": key, "project": False,
                         "path": str(space.repos[key])})
        for key in space.projects():
            if key not in space.repos:
                rows.append({"space": name, "repo": key, "project": True,
                             "path": str(space.repo_path(key))})
    return rows


def cmd_tested(board, args, actor):
    """Bosun's green `make test-all` (every module, voice passing; c-646) on a commit,
    recorded where the board lives so the deploy of that exact tree runs no suite again
    (`merging.record_tested`, keyed by tree). His or Bosun's word only: a house's run is not
    the merged tree."""
    if actor not in (authority.BOSUN, "human"):
        raise Refused(f"kb tested is Bosun's or the user's, not {actor}'s")
    authority.refuse_tested(actor, board)
    space = args.config.spaces.get(args.space or authority.PERSONAL)
    path = space.repo_path(args.repo or "keel") if space is not None else None
    if path is None:
        raise Refused(f"no repo {args.repo or 'keel'!r} in {args.space or authority.PERSONAL}")
    from keel import merging
    try:
        tree = merging.tree_of(path, args.commit)
        commit = merging.git(path, "rev-parse", f"{args.commit}^{{commit}}")
    except merging.MergeRefused as error:
        raise Refused(f"{args.commit} is not in {path}: push it first ({error})") from None
    refuse_untested(path, commit)
    merging.record_tested(args.config, tree, f"{actor} {args.commit[:12]}")
    return {"commit": args.commit, "tree": tree, "by": actor}


def refuse_untested(path, commit: str) -> None:
    """Refused unless a worktree of the repo recorded a green `make test-all`, voice passing,
    at this exact commit on a clean tree (`keel/review/testrun.py`): the word alone, or a
    narrow `make test`, would let a deploy skip a suite nobody ran."""
    from keel.review import testrun
    if testrun.full_green(path, commit) is None:
        raise Refused(f"no green `make test-all` (voice passing) is recorded at {commit[:12]} "
                      f"on a clean tree in any worktree of {path}; run `make test-all` there "
                      f"at that commit, then `kb tested` again")


def repo_lines(args, rows) -> str:
    return "\n".join(f"{row['space']:<8}  {row['repo']}"
                     + ("  (project)" if row["project"] else "") for row in rows)


def cmd_list(board, args, actor):
    limit = checked_count("card limit", args.limit)
    cards = board.list_cards(space=args.space, stage=args.stage, needs_you=args.needs_you,
                             include_archived=args.all, topic=args.topic,
                             backlog=True if args.backlog else None)
    return cards[:limit] if limit else cards


def cmd_show(board, args, actor):
    card = board.get(args.id)
    return dict(card, events=board.events(args.id, last=args.events))


def cmd_set(board, args, actor):
    fields = parse_fields(args.assignments)
    why = repair_why(args, actor)
    if why is not None:
        # Bosun's repair (c-575): the paths it names are checked where the card's files live.
        facts = repair.repair_facts(args.config, board.get(args.id), fields)
        return board.set_fields(args.id, fields, actor, mend={"why": why, "facts": facts})
    if fields.get("repo"):
        refuse_unknown_repo(args.config, board.get(args.id)["space"], fields["repo"])
    return board.set_fields(args.id, fields, actor, assumed=assumed_of(args))


def repair_why(args, actor) -> str | None:
    """`--why`, Bosun's alone (`keel/repair.py`); None when this is no repair."""
    why = getattr(args, "why", None)
    repair.refuse_why(actor, why)
    if why is not None and (getattr(args, "sync", False) or getattr(args, "assumed", None)):
        raise Refused("a repair takes neither --sync nor --assumed")
    return why


def relay_of(args) -> dict | None:
    """`--relay <prompt> --to <host>` on a move, as the board takes it; None without it."""
    if args.relay is None:
        if args.to:
            raise Refused("--to names the host a --relay is for")
        return None
    return {"prompt": args.relay, "to": args.to}


def cmd_stage(board, args, actor):
    why = repair_why(args, actor)
    if getattr(args, "sync", False):
        # The shipping sync's own move (SH-11, `keel/shipsync.py`): done or review to shipping.
        if args.stage != "shipping" or args.plan or args.output or args.relay:
            raise Refused("--sync is the shipping sync's move to shipping, with at most a --note")
        return board.ship_from_sync(args.id, actor, note=args.note or "")
    return board.stage(args.id, args.stage, actor, plan_ref=args.plan,
                       output_ref=args.output, note=args.note, relay=relay_of(args),
                       why=why)


def bosun_gate(board, args, actor) -> dict | None:
    """What Bosun's approval is checked against, read where the board lives (c-522)."""
    if actor != authority.BOSUN:
        if getattr(args, "checked", None):
            raise Refused("--checked is Bosun's; the user's own approval says what they like with --said")
        return None
    card = board.get(args.id)
    if args.gate == "outcome":
        # Read where the board lives, the landing's host too: an outcome Bosun approves is
        # landed by this machine's drain, never relayed elsewhere (c-526).
        return {"checked": args.checked or "", "to": args.config.host,
                "facts": authority.outcome_facts(args.config, card)}
    # A plan gate is always his (c-593): `authority.gate_approval` refuses it, with no facts.
    return {"checked": args.checked or "", "facts": None}


def cmd_approve(board, args, actor):
    bosun = bosun_gate(board, args, actor)
    if bosun is not None:
        return board.approve(args.id, args.gate, actor, relay=relay_of(args), bosun=bosun)
    if actor == "human" and args.gate == "outcome" and onboarding.proposes(board.get(args.id)):
        return approve_proposal(board, args)
    space = board.get(args.id)["space"] if args.gate == "outcome" else None
    try:
        with (merging.approve_lock(args.config, args.id) if args.gate == "outcome" else nullcontext()):
            # c-738 r1.F3: a pack's `publish` runs only inside the user's tap, marked as the user's Ship marks it
            marked = space is not None and adapters.publishes_through_pack(args.config, space)
            with publishing_tap(board, args.id, actor, marked) as nonce:
                # r2.F3: the tap's budget, so kb stops a slow publish and clears the marker itself
                publish = (adapters.publisher(args.config, space, nonce=nonce, timeout=merging.tap_budget())
                           if space is not None else None)
                card = board.approve(args.id, args.gate, actor, publish=publish, relay=relay_of(args))
    except merging.Outran as error:
        # The tap's budget ran out, not the merge: nothing is blocked, and the card is told
        # once how to land it (lane E round 4, finding 4).
        said = merging.OUTRAN.format(card=args.id, seconds=merging.tap_budget())
        board.note(args.id, said, "human")
        raise Refused(said) from error
    except merging.MergeRefused as error:
        if str(error).startswith("a test of "):
            raise Refused(str(error)) from error        # the retap: nothing is written

        # The tap stands as a decision, the merge did not happen: block the card with the
        # reason so it is under needs you with Drop in ready, instead of quietly at review.
        board.block(args.id, f"outcome not merged: {error}", "human")
        raise Refused(f"{args.id} not merged, card blocked: {str(error).splitlines()[0]}") from error
    # What he said beside the tap goes on the record here, before anything else reads the
    # card. This half never resumes a house: the deck's `act_approve` does that, and its
    # prompt quotes the same text. From the terminal the note is all there is.
    if args.said:
        board.note(args.id, args.said, actor)
    if args.gate == "plan" and actor == "human":
        record_stacking(args.config, board, args.id)
    if args.gate == "outcome":
        if (card.get("blocked_reason") or "").startswith("outcome not merged"):
            board.unblock(args.id, actor)   # the earlier refusal is answered by this merge
            card = board.get(args.id)
        # c-600: a work card at shipping keeps its house, which answers review there
        if card.get("session_id") and card["stage"] == "done":
            house.retire_finished(args.config, board, card)
    return card


def record_stacking(config, board, card_id: str) -> None:
    """c-718: the owner's Approve plan records the plan's `stack` batch (`stacking.record`): on
    each card waiting for this one, and, for a row naming a slice, on this card for its `kb
    split`. The plan is read whole (`planactions.document`) and the round is the owner's marks
    since the last send, which the deck's `plan.send` closes only after this approve. The
    approve has moved the card already, so NOTHING here fails it (r1.F13): a plan that cannot
    be read, or anything else that goes wrong, is one note on the card."""
    from keel import planactions, planstate     # noqa: PLC0415 - the plan is read only here
    try:
        card = board.get(card_id)
        if card["space"] not in board.stacks:
            return
        doc = planactions.document(config, card, "plan")
        stacking.record(board, card_id, doc, planstate.state_of(board.events(card_id)))
    except Exception as error:  # noqa: BLE001 - the approve stands whatever this does
        try:
            board.note(card_id, f"stacking not recorded at this approval: {str(error).splitlines()[0] if str(error) else type(error).__name__}", "human")
        except Exception:  # noqa: BLE001 - a board that refuses the note too has said enough
            pass


def approve_proposal(board, args) -> dict:
    """His `kb approve <id> outcome` on a tier or flow proposal (c-667): the draft adopted by
    the one function Setup's Adopt and the deck's tap use, never a close with nothing written."""
    try:
        adopted = onboarding.adopt_proposal(args.config, board, args.id)
    except onboarding.SetupError as error:
        raise Refused(str(error)) from None
    if args.said:
        board.note(args.id, args.said, "human")
    return {"card": board.get(args.id), "note": adopted["note"]}


def approve_text(answer: dict) -> str:
    """A card from kb, or over the wire the deck's gate answer ({card, resumed, note}): Bosun's
    approve is the one that crosses (c-522), and its answer says whether the house moved."""
    if "card" not in answer:
        return card_line(answer)
    note = answer.get("note")
    return card_line(answer["card"]) + (f"\n{note}" if note else "")


def cmd_note(board, args, actor):
    # r-3: `--mark` typed by Bosun is refused here, at the verb; Keel's own code still marks
    # a block for Bosun (its failed resume) through Board, which is the wake's signal.
    authority.refuse_mark(actor, getattr(args, "mark", None))
    bulk = dict(views.BULK_DATA) if getattr(args, "bulk", False) else None
    return {"event": board.note(args.id, args.text, actor, data=bulk, mark=getattr(args, "mark", None))}


def cmd_mark(board, args, actor):
    try:
        data = json.loads(args.data)
    except ValueError as error:
        raise Refused(f"--data is not JSON: {error}") from None
    return {"event": board.mark(args.id, data, actor)}


def cmd_reply(board, args, actor):
    return board.reply(args.id, args.ask, args.text, actor, os.environ.get("KEEL_CARD"))


def cmd_verdict(board, args, actor):
    """The house's verdict on one review item (c-600, `keel/shipreplies.py`): its reply file
    and its commits' diffs are read here, where the house's clone is."""
    card = board.get(args.id)
    data = verdict_data(args, card)
    return {"event": board.verdict(args.id, data, actor, os.environ.get("KEEL_CARD"))}


FLOW_PUSHERS = ("house", "human")
FLOW_MOVERS = ("human", "voice")


def refuse_flowpush(args, actor: str) -> None:
    """`kb flowpush` is the card's own house's, or the owner's (c-641)."""
    if actor not in FLOW_PUSHERS:
        raise Refused(f"kb flowpush is a house's on its own card, or the owner's with their token; not {actor}'s")
    if actor == "house" and os.environ.get("KEEL_CARD") != args.id:
        raise Refused(f"kb flowpush {args.id} is {args.id}'s own house's")


def flow_push(args, actor: str, flow_info: dict, say, pack_cfg) -> dict:
    """The push the grant allows from this worktree, then the pull request it names. The
    push is noted on the card as soon as it lands (`say`), so a pull request that then fails
    never hides a push to a shared branch (c-641 review)."""
    refuse_flowpush(args, actor)
    if not flow_info.get("may_push", True):
        raise Refused(f"kb flowpush {args.id} is {args.id}'s own house's, or the owner's with their token (the board said)")
    try:
        flowfence.check_repo(pack_cfg(), flow_info, Path.cwd())
        done = flowfence.push(flow_info, args.branch, Path.cwd())
    except flowfence.FenceError as error:
        raise Refused(str(error)) from None
    say(flowfence.note(done))
    if args.pr is None:
        return done
    try:
        done["pr"] = flowfence.open_pr(pack_cfg(), flow_info, args.pr, done["pushed"], Path.cwd())
    except flowfence.FenceError as error:
        say(f"flow move {done['move']}: {error}")
        raise Refused(f"pushed {done['pushed']}, but {error}") from None
    say(f"flow move {done['move']}: opened {done['pr']}")
    return done


def cmd_flowinfo(board, args, actor):
    """What the guard and `kb flowpush` read, judged where the board is (c-641), with
    `may_push`: whether the one asking may push under the card's grant (its own house, or
    the owner by their token), judged here too, where the token is checked."""
    try:
        found = flowfence.info(args.config, board.get(args.id))
    except flowfence.FenceError as error:
        raise Refused(str(error)) from None
    mine = actor == "house" and os.environ.get("KEEL_CARD") == args.id
    return dict(found, may_push=actor == "human" or mine)


def cmd_flowpush(board, args, actor):
    """A push of a shared branch of the flow under the grant (c-641, `keel/flowfence.py`)."""
    return flow_push(args, actor, cmd_flowinfo(board, args, actor),
                     lambda text: board.note(args.id, text, actor), lambda: args.config)


def cmd_flowmove(board, args, actor):
    """Your word through the talker (c-641): the move your tap would make, made as the tap
    makes it (`actions.act_flow_move`: the grant, then the house told). `--actor voice` is a
    name anyone may type, and this writes the grant, so voice carries your token too, as an
    answer by voice does (`cmd_console`)."""
    if actor not in FLOW_MOVERS:
        raise Refused(f"kb flowmove is your word (your token, or the talker's voice with it), not {actor}'s")
    if actor == "voice" and not config_module.same_secret(os.environ.get("KEEL_TOKEN") or "",
                                                          human_token(args.config.token_path)):
        raise Refused("a flow move by voice carries your token (KEEL_TOKEN), as the talker's tool "
                      "sends it; a bare --actor voice is not you")
    from keel import actions      # noqa: PLC0415 - the deck's verbs, for this one verb
    try:
        return actions.act_flow_move(args.config, board, {"id": args.id, "move": args.move})
    except actions.ActionError as error:
        raise Refused(str(error)) from None


def verdict_data(args, card: dict) -> dict:
    from keel.planlint import card_roots     # noqa: PLC0415 - only this verb needs it
    try:
        return shipreplies.gather(args, card_roots(card, Path.cwd()))
    except shipreplies.VerdictRefused as refused:
        raise Refused(str(refused)) from None


@contextmanager
def publishing_tap(board, card_id: str, actor: str, marked: bool, ship: bool = False):
    """The user's tap's marker on the card for the length of the publish (`Board.mark_publishing`,
    which refuses any actor but the user), and its nonce, which the pack's `publish` checks against
    it (c-738 r1.F3); cleared after, whatever happened. None when nothing is `marked`."""
    if not marked:
        yield None
        return
    nonce = board.mark_publishing(card_id, actor, ship=ship)
    try:
        yield nonce
    finally:
        board.clear_publishing(card_id, nonce)


def cmd_ship(board, args, actor):
    """His Ship (c-600): push, ready, post the kept replies; the card stays at shipping.
    `reoffer` (c-651) is his ask instead, which pushes and posts nothing; so is `sendback`
    (c-663), his own notes for the house."""
    if getattr(args, "what", None) == "sendback":
        if getattr(args, "anyway", False) or getattr(args, "rebase", False):
            raise Refused("--anyway is Ship's and --rebase is reoffer's; a send-back takes --words or --words-file")
        return board.send_back(args.id, actor, sendback_words(args))
    if getattr(args, "words", None) is not None or getattr(args, "words_file", None):
        raise Refused("--words and --words-file go with sendback: kb ship <id> sendback --words \"...\"")
    if getattr(args, "what", None) == "reoffer":
        if getattr(args, "anyway", False):
            raise Refused("--anyway is Ship's; a re-offer pushes nothing")
        return board.reoffer(args.id, actor, rebase=args.rebase)
    if getattr(args, "rebase", False):
        raise Refused("--rebase goes with reoffer: kb ship <id> reoffer --rebase")
    card = board.get(args.id)
    with merging.approve_lock(args.config, args.id):
        # the marker the adapter's own publish asks for (c-600 review), exactly as the door
        # path writes it: only the user's tap writes one, its nonce goes to the verb (c-738 r1.F3),
        # and it is gone after
        with publishing_tap(board, args.id, actor, True, ship=True) as nonce:
            publish = adapters.publisher(args.config, card["space"], anyway=getattr(args, "anyway", False),
                                         nonce=nonce, timeout=merging.tap_budget())
            board.ship(args.id, actor, publish)
    # c-660: the Ship is on the record; now the worktrees are read again, so the deck says
    # what waits at once. It never fails or delays the Ship (`shipping.after_ship`).
    return shipping.after_ship(args.config, board, args.id)


def sendback_words(args) -> str:
    """His words for `kb ship <id> sendback`: `--words`, or a file's (`-` is stdin)."""
    if args.words is not None and args.words_file:
        raise Refused("give --words or --words-file, not both")
    if not args.words_file:
        return args.words or ""
    if args.words_file == "-":
        return sys.stdin.read()
    try:
        return Path(args.words_file).expanduser().read_text(errors="replace")
    except OSError as error:
        raise Refused(f"the words file cannot be read: {error}") from None


def render_ship(args, card) -> str:
    if getattr(args, "what", None) == "sendback":
        return (f"sent back on {args.id}: the drain tells its house this as its next item once "
                f"the house is free; the card stays at shipping and nothing is posted")
    if getattr(args, "what", None) == "reoffer":
        return (f"re-offer asked on {args.id}: the drain tells its house at its next pass, and "
                f"stops it once that turn ends")
    return card_line(card)


def render_reply(args, result) -> str:
    """What the house reads back: the answer is on the card, and the next open question."""
    head = f"replied to question {result['ask']} on {args.id}"
    ask = result.get("next")
    if not ask:
        return head + "; no other question is waiting"
    where = f" (on {ask['block']})" if ask.get("block") else ""
    about = f' about "{ask["quote"]}"' if ask.get("quote") else ""
    return (f"{head}. The user asked again meanwhile, question {ask['event']}{where}{about}: "
            f"{ask['text']}\nAnswer it the same way: kb reply {args.id} --ask {ask['event']} "
            f"--text \"<your answer>\"")


def cmd_lint(board, args, actor):
    card = board.get(args.id)
    if not args.root:
        args.root = plangate.card_root(args.config, card)
    return plangate.lint_payload(args, card, args.config.cards_dir,
                                 board.events(args.id), plangate.board_resolver(args.config))


def cmd_block(board, args, actor):
    if getattr(args, "keel", False):
        return requests_module.block_keel(board, args.id, args.reason, actor, args.config.console)
    authority.refuse_mark(actor, getattr(args, "mark", None))
    repair.refuse_mechanics_mark(actor, getattr(args, "mark", None))
    return board.block(args.id, args.reason, actor, mark=getattr(args, "mark", None))


def block_aside(args, payload) -> str | None:
    """`--keel` says which request it filed, on stderr: stdout stays the card id."""
    request = payload.get("request") if isinstance(payload, dict) else None
    return (f"filed with Bosun as {request['id']}; nothing wakes Bosun, the user hands it over "
            f"by saying take {request['id']}") if request else None


def console_plan(board, args) -> dict:
    """`kb console plan <card> [--outcome]`: a card's plan (or outcome) and its lint, read
    where the board lives. Bosun's own user cannot read the cards' files (`state/` is
    another user's), so this is how it reads a plan or an outcome (2026-09-26)."""
    card_id = (args.target or getattr(args, "target_text", None) or "").strip()
    if not card_id:
        raise Refused("plan needs a card: kb console plan c-NNN [--outcome]")
    card = board.get(card_id)
    events = board.events(card_id)
    lint_args = argparse.Namespace(file=None, outcome=args.outcome,
                                   root=plangate.card_root(args.config, card))
    try:
        result = plangate.lint_payload(lint_args, card, args.config.cards_dir, events,
                                       plangate.board_resolver(args.config))
    except Refused as refused:
        raise Refused(f"{card_id}: {refused}") from None
    path = Path(result["file"])
    return {"card": card_id, "doc": "outcome" if args.outcome else "plan", "file": str(path),
            "text": path.read_text(errors="replace"), "ok": result["ok"],
            "lint": plangate.render(lint_args, result)}


def cmd_console(board, args, actor):
    if args.sub == "plan":
        return console_plan(board, args)
    if args.sub in ("answer", "deploy") and actor == "voice":
        # `--actor voice` is a name anyone may type; an answer by voice can approve a deploy,
        # so it carries his token as well, which Harbor's tool sends (c-521, BO-5).
        token = os.environ.get("KEEL_TOKEN") or ""
        if not config_module.same_secret(token, human_token(args.config.token_path)):
            raise Refused("an answer by voice carries the user's token (KEEL_TOKEN), as Harbor's tool "
                          "sends it; a bare --actor voice is not the user")
    if args.sub == "deploy":
        return deployask.command(args.config, board, args, actor)
    return requests_module.command(
        board, args, actor, os.environ.get("KEEL_CARD"), args.config.console,
        check_repo=lambda repo: refuse_unknown_repo(args.config, asks_module.PERSONAL_SPACE, repo))


def cmd_unblock(board, args, actor):
    return board.unblock(args.id, actor, expect=getattr(args, "expect", None),
                         why=repair_why(args, actor))


def cmd_rereview(board, args, actor):
    return board.rereview(args.id, actor)


def cmd_backlog(board, args, actor):
    return board.set_backlog(args.id, args.choice, actor)


def cmd_split(board, args, actor):
    slices = []
    for text in args.slice:
        slices.append(parse_slice(text, [piece["title"] for piece in slices]))
    refuse_unknown_slice_repos(args.config, board, args.id, slices)
    children = [board.get(child) for child in board.split(args.id, slices, actor)]
    # c-760 r1.F2: each slice's readback, as create says it, so what a slice inherited is said
    return [dict(card, readback=cardspec.readback(card, board.defaults)) for card in children]


def refuse_unknown_slice_repos(config, board, card_id: str, slices: list[dict]) -> None:
    """c-771: a slice's stated repos are ones its space can open, as `create` asks of a
    card's, before any slice is filed."""
    stated = [piece for piece in slices if piece.get("repo")]
    space = board.get(card_id)["space"] if stated else None
    for piece in stated:
        try:
            refuse_unknown_repo(config, space, piece["repo"])
        except Refused as error:
            raise Refused(f"slice {piece['title']!r}: {error}") from None


def split_aside(args, cards) -> str | None:
    """What `kb split` says on stderr: each slice's readback, and the block of a slice that
    was filed held (it took a mode from its parent and not what the mode needs)."""
    said = []
    for card in cards:
        said.append(card.get("readback"))
        said.append(stack_aside(card))
        said.append(blocked_aside(card))
    return "\n".join(line for line in said if line) or None


def cmd_tree(board, args, actor):
    return board.get(args.id)


def cmd_assign(board, args, actor):
    expected = [part for part in (args.ids or "").split(",") if part] if args.ids is not None else None
    return tree_module.assign(board, args.id, actor, dry_run=args.dry_run, expected=expected)


def cmd_next(board, args, actor):
    return tree_module.to_front(board, args.id, actor, clear=args.clear)


def cmd_queue(board, args, actor):
    return tree_module.queue_rows(board.list_cards(), space=args.space)


def next_line(args, card) -> str:
    if card["rank"] is None:
        return f"{card['id']} is back in the order it was filed in"
    where = f"of {card['parent']}'s tree" if card.get("parent") else "of the queue"
    return f"{card['id']} is at the front {where}"


def cmd_needs_you(board, args, actor):
    return board.needs_you(space=args.space, backlog=args.backlog)


def cmd_event(board, args, actor):
    return {"event": board.record_hook(args.id, args.hook, read_stdin_json())}


def cmd_stop_check(board, args, actor):
    return board.stop_check(args.id, read_stdin_json())


def cmd_import_harbor(board, args, actor):
    """`--ledger`, else the ledger under `[machine] harbor_dir`; neither is a refusal."""
    harbor = getattr(args.config, "harbor_dir", None)
    ledger = Path(args.ledger) if args.ledger else (harbor / importer.LEDGER if harbor else None)
    if ledger is None:
        raise Refused("no ledger: pass --ledger <path>, or set [machine] harbor_dir")
    return importer.import_ledger(board, ledger.expanduser(), skip_archived=args.skip_archived)


def cmd_session(board, args, actor):
    if args.resumed is not None:
        result = {"session_id": args.set, "bg_id": args.bg_id}
        if getattr(args, "automatic", False):
            result["automatic"] = True
        return board.record_resume(args.id, actor, args.resumed, result, app_link=args.app_link)
    return board.set_session(args.id, args.set, actor, transcript_path=args.transcript,
                             bg_id=args.bg_id, app_link=args.app_link, expect=args.expect)


def cmd_relay(board, args, actor):
    if args.what == "land":
        refuse_adapter_land(args.config, board.get(args.id))
    return board.relay(args.id, args.what, actor, args.to, prompt=args.prompt, sha=args.sha,
                       gate=getattr(args, "gate", False), held=getattr(args, "held", False),
                       bulk=getattr(args, "bulk", False))


def refuse_adapter_land(config, card: dict) -> None:
    """A card whose space has an adapter publishes through it; it never lands by merge."""
    space = config.spaces.get(card["space"])
    if space is not None and space.adapter_dir is not None:
        raise Refused(f"{card['id']} is in the {space.name} space, which publishes through its "
                      f"adapter; there is nothing to land")


def cmd_carried(board, args, actor):
    outcome = "superseded" if args.superseded is not None else "taken"
    return board.carry(args.id, args.relay, actor, outcome, why=args.superseded)


def cmd_land(board, args, actor):
    config = args.config
    refuse_adapter_land(config, board.get(args.id))
    return board.land(args.id, args.relay, actor, published=args.published,
                      merge_queue=config.merge_queue,
                      verify=lambda card, sha: merging.target_has(config, card, sha))


def cmd_claim(board, args, actor):
    host = args.host or args.config.host
    if args.release:
        return board.release(args.id, actor, host=host)
    return board.claim(args.id, host, actor)


def cmd_help(board, args, actor):
    if args.verb_name:
        text = verb_help(args.verb_name)            # refuses an unknown verb first
        return dict(VERB_BY_NAME[args.verb_name].as_dict(), help=text)
    return [verb.as_dict() for verb in VERBS]


# ----- rendering: one text form per payload, whichever end computed it -----

def lines_of(args, cards) -> str:
    return "\n".join(card_line(card) for card in cards)


def one_line(args, card) -> str:
    return card_line(card)


def help_text(args, payload) -> str:
    return payload["help"] if args.verb_name else "\n".join(verb["line"] for verb in payload)


# ----- the verb table -----

@dataclass(frozen=True)
class Verb:
    """One kb verb: what argparse builds, what dispatches, and what `kb help` prints.

    `usage` is the arguments after the id, written the way the help line shows them;
    `arguments` is the same list as argparse takes it, so neither can drift from the other.
    `render` turns the handler's payload into the text printed without `--json` (None
    prints nothing); the payload is the same whether this board or a deck computed it.
    `aside` is what the verb SAYS about the payload, printed on stderr whether or not
    `--json` was asked for, so it never lands in the output a caller parses. It reads the
    payload alone, so it says the same thing for a local board and for a deck's answer.
    """

    name: str
    handler: object
    summary: str
    usage: str = ""
    takes_id: bool = True
    arguments: tuple = field(default_factory=tuple)
    render: object = one_line
    aside: object = None

    @property
    def signature(self) -> str:
        """`<id> --plan <path>`: the id (when the verb takes one) and then the arguments."""
        return " ".join(part for part in (("<id>" if self.takes_id else ""), self.usage) if part)

    def line(self) -> str:
        """`<verb> <usage>: <what it does, one sentence>`, the one shape `kb help` prints."""
        return f"{self.name} {self.signature}: {self.summary}"

    def as_dict(self) -> dict:
        return {"verb": self.name, "usage": self.signature, "summary": self.summary,
                "line": self.line()}


VERBS = (
    Verb("create", cmd_create, takes_id=False,
         usage=("--space <space> --title <title> [--brief <text>] [--autonomy attended|autonomous] "
                "[--repo <repo>] [--new-project <name>] [--model <model>] [--parent <id>] "
                "[--from <id>] [--after <id> ...] [--topic <topic>] [--worker house|bosun] "
                "[--option k=v ...] [--assumed <field>,...]"),
         summary=("create a card, print its id and say the readback on stderr; a field not given "
                  "is inherited from the --from card (model, repo, autonomy, topic), else the "
                  "space's default, else Keel's; --assumed names the given fields that were a "
                  "guess; --from records where it came from and changes nothing on that card, "
                  "--parent makes it a slice (which makes that card a tracking card), --after "
                  "makes it wait for one or more cards (it starts when all are at review, shipping or done), and --new-project opens a fresh repo of that "
                  "name under the space's projects directory (attended unless you say otherwise)."),
         arguments=((("--space",), {"required": True}),
                    (("--title",), {"required": True}),
                    (("--brief",), {}),
                    (("--autonomy",), {"help": "attended or autonomous (default autonomous, "
                                              "attended with --new-project)"}),
                    (("--repo",), {}),
                    (("--new-project",), {"metavar": "name",
                                          "help": "open a new repo of this name under the "
                                                  "space's projects_dir"}),
                    (("--model",), {}),
                    (("--parent",), {}),
                    (("--from",), {"dest": "from_card", "metavar": "id",
                                   "help": "the card this one came out of; it leaves that "
                                           "card's stage and gates alone"}),
                    (("--after",), {"action": "append", "metavar": "id",
                                    "help": "a card this one waits for; repeat it (or give "
                                            "ids with commas) to wait for several"}),
                    (("--topic",), {}),
                    (("--worker",), {"choices": ("house", "bosun"),
                                     "help": "who works it (c-645): bosun only on a personal card on a "
                                             "repo it builds, in builder mode; left out, that rule decides"}),
                    (("--option",), {"action": "append", "metavar": "k=v"}),
                    (("--assumed",), {"metavar": "field,...",
                                      "help": "the given fields that were a guess rather than "
                                              "stated (recorded, and said in the readback)"})),
         render=lambda args, card: card["id"], aside=create_aside),
    Verb("list", cmd_list, takes_id=False, render=lines_of,
         usage="[--space <space>] [--stage <stage>] [--topic <topic>] [--needs-you] [--backlog] [--all] [--limit <n>]",
         summary=("list cards oldest first; --backlog is only the backlogged ones, --all includes "
                  "archived ones."),
         arguments=((("--space",), {}),
                    (("--stage",), {}),
                    (("--topic",), {}),
                    (("--needs-you",), {"action": "store_true"}),
                    (("--backlog",), {"action": "store_true", "help": "only cards that have backlogged"}),
                    (("--all",), {"action": "store_true", "help": "include archived cards"}),
                    (("--limit",), {"type": int, "metavar": "N", "help": "only the first N cards (0: all)"}))),
    Verb("repos", cmd_repos, takes_id=False, render=repo_lines,
         usage="[--space <space>]",
         summary=("list every repo key a card may name, per space, both the ones the config "
                  "lists and the projects under the space's projects directory."),
         arguments=((("--space",), {}),)),
    Verb("tested", cmd_tested, takes_id=False,
         render=lambda args, done: f"tree {done['tree'][:12]} of {done['commit'][:12]} recorded green",
         usage="<commit> [--repo <repo>] [--space <space>]",
         summary=("record a green `make test-all` on a commit already in the repo where the "
                  "board lives, so its deploy skips the suite; refused unless that run is "
                  "recorded at the commit; Bosun's or the user's."),
         arguments=((("commit",), {}), (("--repo",), {}), (("--space",), {}))),
    Verb("show", cmd_show, render=lambda args, card: card_text(card, card["events"]),
         usage="[--events <n>]",
         summary="print one card with its fields, its derived flags and its recent events.",
         arguments=((("--events",), {"type": int, "default": 12, "metavar": "N",
                                     "help": "only the last N events (default 12, 0: all)"}),)),
    Verb("set", cmd_set,
         usage="<field>=<value> ... [--assumed <field>,...] [--why <what broke>]",
         summary=("set card fields (title, brief, autonomy, repo, model, topic, plan_ref, output_ref, "
                  "parent, from, after, options.k); after takes ids with commas to wait for "
                  "several; an empty value clears a card it names "
                  "(`parent=`), space is immutable and stage moves go through `stage`; "
                  "--assumed names the fields set as a guess, which are not a correction; "
                  "--why is Bosun's repair of a path Keel reads, on any card."),
         arguments=((("assignments",), {"nargs": "+", "metavar": "field=value"}),
                    (("--assumed",), {"metavar": "field,...",
                                      "help": "the fields set here as a guess rather than "
                                              "stated (tagged assumed, not a correction)"}),
                    (("--why",), {"metavar": "text",
                                   "help": "Bosun's repair (c-575): what broke; see keel/repair.py"}))),
    Verb("stage", cmd_stage,
         usage="<stage> [--plan <path>] [--output <ref>] [--note <text>] [--relay <prompt> --to <host>] [--sync] [--why <what broke>]",
         summary=terms.say(None, "move a card to a stage, recording the plan or output ref (a relative --plan "
                  "is found here and stored absolute, or refused); --relay also asks "
                  "the house's machine to resume it with that prompt; --sync is the shipping "
                  "sync's move of a card whose {changes} are ready to shipping; --why is "
                  "Bosun's repair, a replay of the stage the card is already at."),
         arguments=((("stage",), {}), (("--plan",), {}), (("--output",), {}), (("--note",), {}),
                    (("--relay",), {"metavar": "prompt",
                                  "help": "also record a resume relay with this prompt, in the same write"}),
                    (("--to",), {"metavar": "host", "help": "the host a --relay is for"}),
                    (("--sync",), {"action": "store_true",
                                   "help": "the shipping sync's move: done or review to shipping (SH-11)"}),
                    (("--why",), {"metavar": "text",
                                   "help": "Bosun's repair (c-575): what broke; see keel/repair.py"}))),
    Verb("approve", cmd_approve, render=lambda args, answer: approve_text(answer),
         usage='plan|outcome [--said "<text>"] [--checked "<what>"] [--relay <prompt> --to <host>]',
         summary=("pass a gate, yours alone with the token; plan sends the card to building, "
                  "outcome sends it to done and publishes it."),
         arguments=((("gate",), {"choices": ("plan", "outcome")}),
                    (("--said",), {"metavar": "text",
                                   "help": "what you want to say with the tap (answers to the "
                                           "plan's open questions, say); recorded as a note "
                                           "here, since kb resumes no house, the deck's "
                                           "Approve is what hands it to one"}),
                    (("--checked",), {"metavar": "what",
                                      "help": "Bosun's approval: what it checked (c-522)"}),
                    (("--relay",), {"metavar": "prompt",
                                  "help": "also record a resume relay with this prompt, in the same write"}),
                    (("--to",), {"metavar": "host", "help": "the host a --relay is for"}))),
    Verb("note", cmd_note, render=lambda args, _: f"noted on {args.id}",
         usage="<text> [--mark failed-resume|review-limit|human-stop|closed-idle|merged-end] [--bulk]",
         summary=("add a note to a card's record; --mark says it is the drain's failed resume, "
                  "the user's Stop tap (human-stop, so the drain leaves that house down), an idle "
                  "house closed (closed-idle, back at its next batch or the user's tap), or a merged "
                  "card's idle house ended by the drain (merged-end)."),
         arguments=((("text",), {}), (("--mark",), {"choices": ("failed-resume", "review-limit",
                                                               "human-stop", "closed-idle", "merged-end"),
                                   "help": "what this is: the drain's or the review gate's record"}),
                    (("--bulk",), {"action": "store_true",
                                   "help": "one of a pass over many cards: not your own action on this one"}))),
    Verb("mark", cmd_mark, render=lambda args, result: f"marked on {args.id}",
         usage="--data <json>",
         summary=("record the user's answer or note on a plan or an outcome (the deck's plan page "
                  "sends these; the user's alone, by actor)."),
         arguments=((("--data",), {"required": True, "metavar": "json"}),)),
    Verb("reply", cmd_reply, render=render_reply,
         usage="--ask <id> --text <answer>",
         summary=("answer a question the user asked about your plan on the plan page, without "
                  "revising the plan or moving the card (your own card only)."),
         arguments=((("--ask",), {"required": True, "type": int, "metavar": "id"}),
                    (("--text",), {"required": True, "metavar": "answer"}))),
    Verb("verdict", cmd_verdict, render=lambda args, result: f"verdict on {args.handle} recorded on {args.id}",
         usage=("<handle> --verdict valid|not-valid|deferred|prepared --why <reasoning> [--summary <line>] "
                "[--severity <tag>] [--commit <sha>]... [--reply-file <file> | --reply <text>] [--data <json>]"),
         summary=("record your judgement of one review item you were told at shipping, on your "
                  "own card only; a code change names its commits and a reply its words, the user sees "
                  "it at once, and the user's Ship posts the replies they keep."),
         arguments=((("handle",), {}),
                    (("--verdict",), {"choices": shipreplies.VERDICTS}),
                    (("--why",), {"metavar": "reasoning"}), (("--summary",), {"metavar": "line"}),
                    (("--severity",), {"metavar": "tag"}),
                    (("--commit",), {"action": "append", "metavar": "sha"}),
                    (("--reply-file",), {"metavar": "file"}), (("--reply",), {"metavar": "text"}),
                    (("--data",), {"metavar": "json", "help": "the verdict already gathered (the deck's own kb)"}))),
    Verb("flowinfo", cmd_flowinfo, render=lambda args, found: json.dumps(found),
         summary=("what a house's guard and kb flowpush read about the card's flow: its stage, "
                  "its shared branches, and the flow move tapped on the card that it may carry out now."),
         arguments=()),
    Verb("flowpush", cmd_flowpush,
         render=lambda args, done: flowfence.note(done) + (f", opened {done['pr']}" if done.get("pr") else ""),
         usage="<branch> [--pr <branch>]",
         summary=terms.say(None, "push this worktree's HEAD to a shared branch of the card's space flow (a flow "
                           "branch id: dev, pick), only while a move tapped on the card names it, never forced; "
                           "--pr also opens the {change} the move names; your own card only."),
         arguments=((("branch",), {"help": "the flow branch id the move pushes"}),
                    (("--pr",), {"metavar": "branch",
                                 "help": terms.say(None, "the flow branch id to open a {change} to")}))),
    Verb("flowmove", cmd_flowmove, render=lambda args, done: done.get("note") or f"{args.move} asked on {args.id}",
         usage="<move>",
         summary=("make a move of the card's space flow that is yours (Merge to dev review), on your "
                  "word: what your tap on the card does; your token, or the talker's voice with it."),
         arguments=((("move",), {"help": "the move's id in the flow"}),)),
    Verb("ship", cmd_ship, render=render_ship,
         usage="[--anyway] | reoffer [--rebase] | sendback --words <text> | --words-file <file>",
         summary=terms.say(None, "the user's Ship on a shipping card, the user's alone with the token, pushes the house's "
                  "commits, marks a draft {change} ready and posts the replies they kept, once; "
                  "the card stays at shipping. Held while the house is in a turn or no receipt "
                  "covers the commits, unless --anyway. `reoffer` (the user's alone) "
                  "asks the drain to tell the house the review it was never told, and with "
                  "--rebase to bring its branch up to its base by merging it in; the house is "
                  "stopped once its turn on that batch ends. `sendback` (the user's alone) tells the "
                  "house the user's own words as its next item: the card stays at shipping and nothing "
                  "is posted for it."),
         arguments=((("what",), {"nargs": "?", "choices": ("reoffer", "sendback"),
                                 "help": "reoffer: the review never told, offered to the house again; "
                                         "sendback: the user's own notes, told to the house as its next item"}),
                    (("--words",), {"help": "with sendback: what the user wants changed"}),
                    (("--words-file",), {"metavar": "file", "help": "with sendback: the user's words from a file (- is stdin)"}),
                    (("--anyway",), {"action": "store_true",
                                    "help": "ship although the house is in a turn or the commits are unchecked"}),
                    (("--rebase",), {"action": "store_true",
                                     "help": "with reoffer: also ask the house to merge its base into its branch"}))),
    Verb("lint", cmd_lint, render=plangate.render,
         usage="[--file <plan.md>] [--outcome] [--root <checkout>]",
         summary=("check a plan (or with --outcome the card's context.md) against the "
                  "authoring contract; exits 1 on any error, and `stage` refuses the same."),
         arguments=((("--file",), {}), (("--outcome",), {"action": "store_true"}),
                    (("--root",), {"help": "the checkout path:line refs resolve in"}))),
    Verb("block", cmd_block, aside=block_aside,
         usage="<reason> [--keel] [--mark failed-resume|review-limit|permission-pause|mechanics|landing-refused]",
         summary=("block a card, with the reason it needs a human; --keel says Keel itself is "
                  "in the way, and files it with Bosun as a request in the same write."),
         arguments=((("reason",), {}),
                    (("--keel",), {"action": "store_true",
                                   "help": "Keel is what is in the way: also file a request "
                                           "with Bosun, named in the block"}),
                    (("--mark",), {"choices": ("failed-resume", "review-limit", "permission-pause",
                                               "mechanics", "landing-refused"),
                                   "help": "what this is: the drain's, the hook's or the review "
                                           "gate's record (a permission pause wakes Bosun)"}))),
    Verb("console", cmd_console, takes_id=False, render=requests_module.render,
         usage=requests_module.USAGE, summary=requests_module.SUMMARY,
         arguments=requests_module.ARGUMENTS),
    Verb("unblock", cmd_unblock,
         usage="[--expect <reason>] [--why <what broke>]",
         summary=("clear a card's block so it can move again; --expect clears it only while "
                  "it is still that reason (the drain's own blocks); --why is Bosun's repair "
                  "of a block Keel wrote, on any card."),
         arguments=((("--expect",), {"metavar": "reason",
                                     "help": "clear only while the block is still this reason"}),
                    (("--why",), {"metavar": "text",
                                   "help": "Bosun's repair (c-575): what broke; see keel/repair.py"}))),
    Verb("rereview", cmd_rereview,
         summary=("the user's Re-review of a posted review card with new commits, a new round on the "
                  "same card, back to assigned (the human's alone).")),
    Verb("backlog", cmd_backlog,
         usage="[backlog|active|auto]",
         summary=("set the manual backlog override on a card (backlog always, active never, "
                  "auto hands it back to the date rule)."),
         arguments=((("choice",), {"nargs": "?", "default": "auto",
                                   "metavar": "backlog|active|auto"}),)),
    Verb("split", cmd_split, render=lambda args, cards: "\n".join(card["id"] for card in cards),
         aside=split_aside,
         usage=('--slice "title|brief[|after-title|...][|repo=key[,key]]'
                '[|stack=stacked|stack=independent]" ...'),
         summary=("cut a card into child slices; the parent becomes a tracking card; each "
                  "after-title names an earlier slice this one waits for; `repo=` is the slice's "
                  "own repos, the card's or fewer, kept in the card's order whatever order is "
                  "typed, and a slice without it takes the card's (c-771); `stack=` is the owner's "
                  "stacked or independent answer for the slice "
                  "(c-718). A part after the brief that is an earlier slice's exact title is "
                  "always an after-title, so only another part starting `repo=` or `stack=` is "
                  "read as one."),
         arguments=((("--slice",), {"action": "append", "required": True,
                                    "metavar": "title|brief[|after-title|...][|repo=...][|stack=...]"}),)),
    Verb("tree", cmd_tree, render=lambda args, card: tree_module.render(card),
         summary=("print a card's tree, its slices by step, what each waits for, which could "
                  "start next, what each unblocks, and its follow-ups apart.")),
    Verb("assign", cmd_assign, render=lambda args, result: tree_module.assign_line(result),
         usage="[--dry-run] [--ids <id,id,...>]",
         summary=("assign a card from inbox, or every unassigned slice of a tracking card at "
                  "once (the drain then follows the tree); --dry-run only says how many would "
                  "start now and how many wait; --ids assigns only if the set is still the one "
                  "a preview showed; the user's verb only (actor human or voice)."),
         arguments=((("--dry-run",), {"action": "store_true"}), (("--ids",), {}))),
    Verb("next", cmd_next, render=next_line,
         usage="[--clear]",
         summary=("put a card at the front of the queue (for a slice, the front of its "
                  "tree), or with --clear back in the order it was filed in; a card still "
                  "waiting never starts first; the user's verb only (actor human or voice)."),
         arguments=((("--clear",), {"action": "store_true"}),)),
    Verb("queue", cmd_queue, takes_id=False,
         render=lambda args, rows: "\n".join(tree_module.queue_line(row) for row in rows)
         or "the queue is empty: no card is assigned",
         usage="[--space <space>]",
         summary="list the assigned cards in the order the drain starts them, and why any is not starting.",
         arguments=((("--space",), {}),)),
    Verb("needs-you", cmd_needs_you, takes_id=False, render=lines_of,
         usage="[--space <space>] [--backlog]",
         summary=("list what is waiting on you, the open gates and the blocked cards, with the "
                  "backlogged ones only under --backlog."),
         arguments=((("--space",), {}),
                    (("--backlog",), {"action": "store_true",
                                      "help": "also show cards that have backlogged"}))),
    Verb("event", cmd_event, render=lambda args, _: f"recorded {args.hook} on {args.id}",
         usage="--hook Stop|SessionEnd|Notification",
         summary="record a harness hook on a card, reading the hook JSON on stdin.",
         arguments=((("--hook",), {"required": True, "choices": HOOKS}),)),
    Verb("stop-check", cmd_stop_check,
         render=lambda args, decision: json.dumps(decision) if decision else None,
         summary="the Stop hook body, nudging a house that stopped at building or letting it stop."),
    Verb("import-harbor", cmd_import_harbor, takes_id=False,
         render=lambda args, counts: importer.summary(counts),
         usage="[--ledger <path>] [--skip-archived]",
         summary="fold the old ledger into the board, keeping ids and timestamps; a second run changes nothing.",
         arguments=((("--ledger",), {"default": None}),
                    (("--skip-archived",), {"action": "store_true"}))),
    Verb("session", cmd_session,
         render=lambda args, card: f"{args.id} session {card['session_id']}",
         usage="--set <uuid> [--transcript <path>] [--bg-id <id>] [--app-link <url>] [--resumed <prompt> [--automatic]] [--expect <uuid>]",
         summary=("record the house session the harness minted for a card; --resumed records "
                  "a resume with its prompt (--automatic, the drain's once-only one), and the "
                  "session only when it is a new one."),
         arguments=((("--set",), {"required": True, "metavar": "uuid"}),
                    (("--transcript",), {}),
                    (("--bg-id",), {}),
                    (("--app-link",), {"metavar": "url"}),
                    (("--resumed",), {"metavar": "prompt"}),
                    (("--automatic",), {"action": "store_true"}),
                    (("--expect",), {"metavar": "uuid"}))),
    Verb("claim", cmd_claim,
         usage="[--host <name>] [--release]",
         summary=("take a startable card for one drain's host so no other drain starts it; "
                  "--release hands it back."),
         arguments=((("--host",), {"metavar": "name",
                                   "help": "the drain's host (default: this machine's name)"}),
                    (("--release",), {"action": "store_true"}))),
    Verb("relay", cmd_relay,
         usage="resume|stop|close-idle|start|land|rotate --to <host> [--prompt <text>] [--sha <sha>] [--gate] [--held] [--bulk]",
         summary=("ask the drain on the house's own machine to resume, stop, close while idle, "
                  "start or rotate it, or to land its outcome; yours alone with the token, "
                  "carried once on that drain's next pass."),
         arguments=((("what",), {"choices": ("resume", "stop", "close-idle", "start", "land", "rotate")}),
                    (("--to",), {"required": True, "metavar": "host"}),
                    (("--prompt",), {"metavar": "text"}),
                    (("--sha",), {"metavar": "sha"}),
                    (("--gate",), {"action": "store_true",
                                   "help": "a gate's answer: refused if the card's stage moves first"}),
                    (("--held",), {"action": "store_true",
                                   "help": "held for a house the deck saw working"}),
                    (("--bulk",), {"action": "store_true",
                                   "help": "one of a pass over many cards: not your own action on this one"}))),
    Verb("carried", cmd_carried,
         usage="<relay> [--superseded <why>]",
         summary=("mark a relay carried, before the drain acts on it; --superseded answers "
                  "one it will not act on."),
         arguments=((("relay",), {"type": int, "metavar": "relay"}),
                    (("--superseded",), {"metavar": "why"}))),
    Verb("land", cmd_land,
         usage="--relay <n> [--published <text>]",
         summary=("finish an Approve outcome a drain carried and landed, moving the card "
                  "to done under the land relay it took (the drain's alone)."),
         arguments=((("--relay",), {"type": int, "required": True, "metavar": "n"}),
                    (("--published",), {"metavar": "text"}))),
    Verb("help", cmd_help, takes_id=False, render=help_text,
         usage="[<verb>]",
         summary="print one line per verb, or one verb's full usage.",
         arguments=((("verb_name",), {"nargs": "?", "metavar": "verb"}),)),
)

VERB_BY_NAME = {verb.name: verb for verb in VERBS}


def add_arguments(parser: argparse.ArgumentParser, verb: Verb) -> None:
    """The id (when the verb takes one), `--json`, then the verb's own arguments."""
    if verb.takes_id:
        parser.add_argument("id")
    parser.add_argument("--json", action="store_true")
    for flags, options in verb.arguments:
        parser.add_argument(*flags, **options)


def help_lines() -> list[str]:
    return [verb.line() for verb in VERBS]


def verb_help(name: str) -> str:
    """One verb's full usage: its help line, then the arguments argparse would take."""
    verb = VERB_BY_NAME.get(name)
    if verb is None:
        raise Refused(f"no verb {name!r}; `kb help` lists them")
    # No colour: this text goes into JSON and into a house's brief, never only a terminal.
    # `color` arrived in argparse in 3.14 and this also runs on the box's 3.12, where
    # passing it is a TypeError and `kb help <verb>` died (there is no colour there to
    # turn off, since argparse only colours a terminal).
    parser = argparse.ArgumentParser(prog=f"kb {name}", add_help=False, **NO_COLOUR)
    add_arguments(parser, verb)
    return verb.line() + "\n\n" + parser.format_help().rstrip()


# ----- parser -----

def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="kb", description="the Keel board")
    parser.add_argument("--actor", help="override the actor (human needs the token)")
    subs = parser.add_subparsers(dest="verb", required=True)
    for verb in VERBS:
        sub = subs.add_parser(verb.name, help=verb.summary)
        add_arguments(sub, verb)
        sub.set_defaults(handler=verb.handler)
    return parser


def main_help(args) -> int:
    """`help` is the parser answering about itself: no board, no config, no state dir.

    It used to fall through to the load below, which creates `state/`, `state/cards` and
    `state/logs` and writes `state/human.token` wherever the config points. A house's
    brief asks for `kb help` on every start (keel/prompts.py), so during the test suite
    that was the LIVE state directory, whatever temp dir the test had set up
    (2026-09-20). Nothing here reads a board, so nothing here needs one.
    """
    try:
        payload = args.handler(None, args, "cli")
    except Refused as refusal:
        print(f"kb: {refusal}", file=sys.stderr)
        return 1
    emit(args, payload, VERB_BY_NAME[args.verb].render(args, payload))
    return 0


def load_config(prefix: str):
    """The config, or a one-line refusal instead of a traceback.

    A config that is not there is an ordinary mistake (a scratch `KEEL_HOME` that was
    never given the file), and so is one that says something impossible, so both print like
    every other refusal here.
    """
    try:
        return config_module.load()
    except config_module.ConfigError as broken:
        print(f"{prefix}: {broken}", file=sys.stderr)
        raise SystemExit(1) from None


def say_scratch(config, prefix: str) -> None:
    """Name the board this process opened when it is not the one the toml asked for.

    On stderr and unconditional: a house whose capture landed on a board nobody looks at
    should read it in the first line it gets back, not work it out from an empty deck.
    """
    if config.scratch:
        print(f"{prefix}: {config.scratch_note}", file=sys.stderr)



def main_hook(args) -> int:
    """`kb console hook`, Bosun's UserPromptSubmit hook: atop his message, his answers not yet
    told to Bosun, its open asks, and the open requests. It NEVER fails his message: whatever
    goes wrong is one line of context, and exit 0. The answers it claimed are confirmed only
    once they are printed (`asks.confirm`); a confirm that does not land leaves the claim to
    run out, and they are told again, marked as such, rather than lost."""
    told, config = [], None
    try:
        config = load_config("kb")
        with open_board(config) as board:
            args.config = config
            # Bosun's own hook is Bosun: only it takes his answers (`requests.hook`)
            is_bosun = authority.is_key(os.environ.get(BOSUN_ENV), authority.bosun_key(config))
            payload = cmd_console(board, args, "bosun" if is_bosun else "hook")
        text = requests_module.render(args, payload)
        told = list(payload.get("told") or [])
    except (Exception, SystemExit) as error:  # noqa: BLE001 - never block his message
        text = f"Asks and requests: could not read the board, so no answer of the user's was told here ({str(error).splitlines()[0] if str(error) else type(error).__name__})"
    if text:
        print(text, flush=True)
    if told:
        confirm_told(told, config)
    return 0


def confirm_told(told: list[str], config) -> None:
    """The printed answers, recorded as told by the hook. Never fails his message."""
    try:
        with open_board(config) as board:
            asks_module.confirm(board, told, "hook")
    except (Exception, SystemExit):  # noqa: BLE001 - the claim runs out and they are told again
        pass


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.verb == "help":
        return main_help(args)
    # The hook's own door, where Bosun runs it; with --json it is the payload, not the lines.
    if args.verb == "console" and args.sub == "hook" and not args.json:
        return main_hook(args)
    # THE REFINE'S SCOPE, before either door (`keel/refinescope.py`): a capture's refine
    # turn may touch its own card and nothing else, and never a gate.
    try:
        refinescope.check(args)
    except refinescope.OutOfScope as refusal:
        print(f"kb: refine scope: {refusal}", file=sys.stderr)
        return 1
    args.actor = refinescope.actor(args)
    config = load_config("kb")
    say_scratch(config, "kb")
    args.config = config
    board = open_board(config)
    try:
        actor = resolve_actor(args.actor, config.token_path, authority.bosun_key(config))
        authority.refuse_verb(actor, args.verb)
        if args.verb == "create" and args.space not in config.spaces:
            raise Refused(f"unknown space {args.space!r}; one of {', '.join(config.spaces)}")
        plangate.normalise_plan_ref(args, config.cards_dir, config.root, config.worktrees_dir)
        if args.verb == "stage":
            plangate.check_stage(args, lambda: dict(board.get(args.id), events=board.events(args.id)),
                                 config.cards_dir, plangate.board_resolver(config))
        payload = args.handler(board, args, actor)
    except (Refused, adapters.AdapterError) as refusal:
        print(f"kb: {refusal}", file=sys.stderr)
        return 1
    finally:
        board.close()
    # His Deploy just recorded: wake this machine's drain, which starts it, and say in the
    # payload whether one heard (c-636), so it is kicked before the payload is printed.
    kick.after_deploy(config, args, payload)
    emit(args, payload, VERB_BY_NAME[args.verb].render(args, payload))
    # A relay just written: wake the drain that carries it now, not at its next pass (c-598).
    kick.after_verb(config, args)
    return 1 if args.verb == "lint" and not payload["ok"] else 0


# ----- roles -----

def build_role_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="keel", description="Keel's roles")
    subs = parser.add_subparsers(dest="role", required=True)
    sub = subs.add_parser("drain")
    sub.add_argument("--once", action="store_true", help="one pass, then exit")
    sub.add_argument("--card", help="start this card even while the drain is paused")
    sub.add_argument("--no-wait", action="store_true",
                     help="with --card: skip at once while another pass runs, rather than wait for it")
    sub.add_argument("--space", action="append", help="serve only this space (repeatable)")
    sub = subs.add_parser("serve")
    sub.add_argument("--port", type=int, help="override serve_port from the config")
    sub = subs.add_parser("fetch")
    sub.add_argument("--once", action="store_true", help="one pass (every fetcher, then asks), then exit")
    sub.add_argument("--preview", action="store_true",
                     help="print what a full pass would file (asks, recurring cards) and exit; runs and writes nothing")
    sub.add_argument("--segment", help="only this segment")
    sub = subs.add_parser("run")
    sub.add_argument("--roles", default="drain", help="comma list: drain, serve, fetch")
    sub = subs.add_parser("install")
    sub.add_argument("--load", action="store_true", help="also start it: launchd on macOS, a systemd user unit on Linux")
    sub.add_argument("--roles", default=install.DEFAULT_ROLES)
    return parser


def role_drain(config, args) -> int:
    if not args.once:
        drain.run(config)
        return 0
    try:
        summary = drain.once(config, spaces=args.space, card=args.card,
                             wait=not getattr(args, "no_wait", False))
    except passlock.Busy as busy:     # a card-scoped pass never skips silently (c-734)
        drain.log(config, f"drain: {busy} (once)")
        print(busy, file=sys.stderr)
        return 1
    line = drain.summary_line(summary)
    drain.log(config, line + " (once)")
    print(line)
    return 0


def role_fetch(config, args) -> int:
    if args.preview:
        print("\n".join(fetchpreview.lines(config)))
        return 0
    if not args.once:
        fetchloop.run(config, segment=args.segment)
        return 0
    results = fetch.once(config, segment=args.segment)
    created, due, unfiled = fetchloop.file_cards(config, args.segment)    # under the filing lock
    line = fetch.summary_line(results, created)
    fetch.log(config, line + " (once)")
    print(line)
    for key, card_id in due.items():
        print(f"recurring {key}: {card_id} filed")
    if unfiled:
        # `cards=0` alone would read as nothing to file (c-742 r2.F3).
        print(f"keel fetch: the fetchers ran, but no card was filed: {unfiled}. Asks and "
              f"recurring cards wait for the next pass", file=sys.stderr)
        return 1
    return 0


def role_serve(config, args) -> int:
    run_serve(config, port=args.port)
    return 0


def parse_roles(text: str) -> list[str]:
    """The built roles named in a comma list, in order and once each; unknown ones refused,
    unbuilt ones reported and dropped."""
    roles = list(dict.fromkeys(role.strip() for role in text.split(",") if role.strip()))
    unknown = [role for role in roles if role not in ("drain", "serve", "fetch")]
    if unknown:
        raise Refused(f"unknown role(s): {', '.join(unknown)}")
    for role in roles:
        if role not in BUILT_ROLES:
            print(f"keel {role}: not built yet, skipped", file=sys.stderr)
    live = [role for role in roles if role in BUILT_ROLES]
    if not live:
        raise Refused(f"nothing to run: the built roles are {', '.join(BUILT_ROLES)} (the rest are not built yet)")
    return live


def role_run(config, args) -> int:
    """One process: every built role but the first on its own thread, the first here."""
    roles = parse_roles(args.roles)
    runners = dict(RUNNERS)
    if "drain" in roles:
        # One process, one restart: the drain's, between its passes (c-637 review F1).
        runners["serve"] = functools.partial(run_serve, follow=False)
    if len(roles) > 1:
        # The fetch role's own restart waits for nothing but its pass, so it is for a process
        # of its own: beside the deck or the drain, theirs is the process's (c-742 r1.F5).
        runners["fetch"] = functools.partial(fetchloop.run, follow=False)
    for role in roles[1:]:
        threading.Thread(target=runners[role], args=(config,), name=role, daemon=True).start()
    runners[roles[0]](config)
    return 0


def role_install(config, args) -> int:
    for path in install.write(config, args.roles):
        print(f"wrote {path}")
    print(config_module.service_reads(config))
    if args.load:
        return install.load(config, args.roles)
    print("not loaded (pass --load to start it under launchd or systemd)")
    return 0


ROLE_HANDLERS = {"drain": role_drain, "serve": role_serve, "fetch": role_fetch, "run": role_run,
                 "install": role_install}


def run_role(argv: list[str]) -> int:
    args = build_role_parser().parse_args(argv)
    config = load_config(f"keel {args.role}")
    say_scratch(config, f"keel {args.role}")
    try:
        if args.role in ("run", "install"):
            parse_roles(args.roles)
        return ROLE_HANDLERS[args.role](config, args)
    except Refused as refusal:
        print(f"keel {args.role}: {refusal}", file=sys.stderr)
        return 1


def run_doctor(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(prog="keel doctor", description="report the resolved setup")
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--single", action="store_true",
                        help="this one machine's checks only (an install's config implies it)")
    args = parser.parse_args(argv)
    report = doctor.gather(single=args.single)
    report["missing"] = doctor.problems(report)
    report["filed"] = doctor.sight(report["missing"])
    emit(args, report, doctor.render(report))
    if report["filed"]:
        print(f"doctor kept finding the same problem, so it is filed with Bosun: "
              f"{', '.join(report['filed'])}", file=sys.stderr)
    return 1 if report["missing"] else 0


# ----- the deck, read -----

def build_deck_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="keel deck", description="read what the deck shows, in either space")
    parser.add_argument("section", nargs="?", choices=deckdigest.SECTIONS,
                        help="one section as a table")
    parser.add_argument("--space", help="only this space")
    parser.add_argument("--json", action="store_true", help="the whole state document")
    parser.add_argument("--digest", action="store_true",
                        help="the reduced digest a voice turn carries")
    parser.add_argument("--port", type=int, help="override serve_port from the config")
    return parser


def deck_document(config, port: int | None = None) -> tuple[dict, str]:
    """The deck's state document and where it came from: `deck`, or `board`.

    THE DECK FIRST because it is the running process's own answer, cache and providers
    included, and it is up whenever anything else here is. THE BOARD SECOND rather than
    nothing: `deckstate.build` is the same builder the deck runs, so a deck that is down
    costs freshness and a few subprocesses, not the answer.
    """
    try:
        return deckdigest.fetch_state(port or config.serve_port), "deck"
    except Exception:                                   # noqa: BLE001 - down is down
        board = open_board(config)
        try:
            return deckstate.build(config, board), "board"
        finally:
            board.close()


def talker_running(config) -> bool:
    """Whether the phone talker is up. The deck cannot say: a Remote Control session is
    not a kind `claude agents --json` lists, so its pid file is the only honest signal."""
    return talker.alive(talker.recorded_pid(talker.paths_from(config)))


def run_deck(argv: list[str]) -> int:
    args = build_deck_parser().parse_args(argv)
    config = config_module.load()
    if args.space and args.space not in config.spaces:
        print(f"keel deck: unknown space {args.space!r}; one of {', '.join(config.spaces)}",
              file=sys.stderr)
        return 1
    try:
        state, source = deck_document(config, args.port)
    except Refused as refusal:
        print(f"keel deck: {refusal}", file=sys.stderr)
        return 1
    if source == "board":
        print(f"keel deck: nothing answered on {deckdigest.state_url(args.port or config.serve_port)}, "
              "so this was built from the board in this process instead", file=sys.stderr)
    if args.json:
        print(json.dumps(state, indent=1))
        return 0
    doc = deckdigest.fold(state, harbor_running=talker_running(config))
    doc["source"] = source
    if args.digest:
        print(deckdigest.as_json(doc))
        return 0
    if args.section:
        print(deckdigest.render_section(doc, args.section, args.space or ""))
        return 0
    print(deckdigest.overview(doc))
    return 0


def keel_main(argv: list[str] | None = None) -> int:
    """`shipyard init <dir>`, `shipyard service <verb>`, `shipyard import <dir>`,
    `shipyard move-personal`, `keel <role>`, `keel doctor`,
    `keel deck ...`, `keel converse <card> "<text>"`,
    `keel house key`, `keel board <verb>`, `keel console <verb>`, `keel talker <verb>`,
    `keel voice <verb>`, `keel backup <verb>`, `keel logins [verb]`, `keel new <kind> <name>`,
    `keel pack check <dir>`, `keel kb <verb> ...`, or `keel <verb> ...`."""
    argv = list(sys.argv[1:] if argv is None else argv)
    if not argv:
        print("usage: shipyard init <dir> | shipyard service <verb> | shipyard import <dir> | "
              "shipyard move-personal [--dry-run] | "
              "keel <drain|serve|fetch|run|install> | keel doctor | keel deck [section] | "
              "keel converse <card> \"<text>\" | keel house key | keel board <verb> | keel console <verb> | "
              "keel talker <verb> | keel voice <verb> | keel backup <verb> | "
              "keel logins [check|mark] | keel new pack|segment|view <name> | keel pack check <dir> | "
              "keel kb <verb> ...",
              file=sys.stderr)
        return 2
    if argv[0] == "doctor":
        return run_doctor(argv[1:])
    if argv[0] == "init":
        from keel import installer      # noqa: PLC0415 - `shipyard init`, once per machine (c-616)
        return installer.main(argv[1:])
    if argv[0] == "service":
        from keel import appservices    # noqa: PLC0415 - `shipyard service <verb>` (c-616)
        return appservices.main(argv[1:])
    if argv[0] == "import":
        from keel import stateimport    # noqa: PLC0415 - `shipyard import <dir>`, once (c-620)
        return stateimport.main(argv[1:])
    if argv[0] == "move-personal":
        from keel import movepersonal   # noqa: PLC0415 - `shipyard move-personal`, once (c-722)
        return movepersonal.main(argv[1:])
    if argv[0] == "deck":
        return run_deck(argv[1:])
    if argv[0] == "converse":
        return converse.main(argv[1:])
    if argv[0] == "house":
        return housetier.main(argv[1:])
    if argv[0] == "rotate":
        return rotate.main(argv[1:])
    if argv[0] == "check":
        from keel import fixcheck      # noqa: PLC0415 - a house's one command after a commit (c-600)
        return fixcheck.main(argv[1:])
    if argv[0] == "board":
        return boards.main(argv[1:])
    if argv[0] == "console":
        return console.main(argv[1:])
    if argv[0] == "talker":
        return talker.main(argv[1:])
    if argv[0] == "voice":
        return voice.main(argv[1:])
    if argv[0] == "backup":
        return backup.main(argv[1:])
    if argv[0] == "logins":
        from keel import logins
        return logins.main(argv[1:])
    if argv[0] == "new":
        from keel import scaffold      # noqa: PLC0415 - a builder's verb (c-634)
        return scaffold.main(argv[1:])
    if argv[0] == "pack":
        from keel import packcheck     # noqa: PLC0415 - a builder's verb (c-735)
        if argv[1:2] != ["check"]:
            print("usage: keel pack check <pack folder>", file=sys.stderr)
            return 2
        return packcheck.main(argv[2:])
    if argv[0] == "flow":
        from keel import flows          # noqa: PLC0415 - c-640
        return flows.main(argv[1:])
    if argv[0] in ROLE_HANDLERS:
        return run_role(argv)
    if argv[0] in ROLES:
        print(f"keel {argv[0]}: not built yet", file=sys.stderr)
        return 2
    if argv[0] == "kb":
        argv = argv[1:]
    return main(argv)
