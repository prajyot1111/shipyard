"""`POST /api/action`: every verb the deck can do, and how each one is carried out.

The board verbs (`create`, `set`, `stage`, `approve`, `note`, `block`, `unblock`,
`split`, `session`, `claim`, `event`, `stop-check`, `backlog`, and the reads `show`,
`list`, `needs-you`) are `bin/kb` run as a subprocess. Every body is the deck page's own
tap: `kb` runs with `KEEL_TOKEN` from `state/human.token`, so the tap is exactly the human's
own command and the board records it as `human`. A body carrying a `caller` (what a `kb` on
another machine sent before c-622) is refused. A hook payload (`event`, `stop-check`) arrives as `payload` and goes to `kb`
on stdin. The house verbs go through `house` and `harness` (`house.resume`,
`house.retry`, `house.stop`, `house.logs`, `house.converse`); `house.stop` and its idle
twin `house.close_idle` (c-607, `keel/idleclose.py`: only a house the harness lists idle, back
at its next batch or his tap) are the only stops in the system, and `house.converse` is one spoken turn into a card's own house, the same
`keel converse` both Harbors run.
`dropin` cannot open an interactive session from a server, so it returns the command to
run at the desk and notes it on the card. `adapter` hands a route or card verb to the
space's adapter (`act do ...`), which owns the vocabulary and the tools it shells.

The gate verbs are the ones that carry the human's answer back to the house. `approve` at
the plan gate and `sendback` both move the card through `kb` and then resume the house with
the prompt `prompts` composes, because the annotations a house needs are queued in lavish
and come back only through one `lavish-axi poll`: a house that waited for them would hold
its slot for nothing. `sendback` with `stay` is the deliberate exception, a discussion on
the surface, and `end_discussion` ends it by ending the lavish session so the house's own
poll returns. Nothing here stops a session.

A tap for a house that is WORKING is held rather than refused: a `resume` relay on the
card (`Board.relay`), which the drain carries once the house's Stop kicks it (c-598).
"""

import json
import re
import os
import sqlite3
import subprocess
import sys
from pathlib import Path

from keel import (adapters, afresh, artifacts, boardfiles, boards, boardtrash, cardtitle, console, consoletaps, converse,
                  drain, dropin, firstrun, flowmoves, harness, house, housejobs, housetier, idleclose, landing, landpush, merging,
                  onboarding, openapp, passlock, pausewake, planactions, planask, prompts, readiness, repocommands, requests, rotate,
                  shipauto, shipsendback, shipcheck, stuckcards, views)
from keel.board import Board, Refused
from keel.config import Config, human_token

KB_VERBS = ("create", "set", "stage", "approve", "note", "block", "unblock", "split", "session",
            "claim", "relay", "carried", "land", "event", "stop-check", "backlog", "show", "list",
            "needs-you", "repos", "tree", "assign", "next", "queue", "mark", "reply", "rereview",
            "console", "tested", "verdict", "flowinfo")
# The verbs that only read: they leave the deck's cached state document alone.
READ_VERBS = ("show", "list", "needs-you", "repos", "tree", "queue", "flowinfo")
# `kb console`'s sub-verbs that only read (c-520): Bosun's hook runs one before every message.
# The hook also marks the answers it tells Bosun as delivered (c-521); that write moves
# `asks.updated_at`, which the deck's own stamp reads, so the cache is not dropped for it.
CONSOLE_READS = ("list", "show", "hook", "gaps", "asks", "pending", "wakes", "plan", "held")


def reads_only(body: dict) -> bool:
    """Does this action leave the board as it was, so the deck's state document stands."""
    verb = body.get("verb")
    return verb in READ_VERBS or (verb == "console" and body.get("sub") in CONSOLE_READS)
SLOW_SECONDS = 180
# A card-scoped pass a tap waits on (Retry, create-and-start) may first wait for the pass
# lock (`passlock.WAIT_SECONDS`), and then has the whole pass budget it had before (r2.F2).
CARD_PASS_SECONDS = passlock.WAIT_SECONDS + SLOW_SECONDS
DISCUSSION_OPTION = "discussion"


class ActionError(Exception):
    """The verb was refused or failed; the message is the one line the page shows. `detail`
    is what a verb sends beside it for the page to draw (c-678: a failed copy's kind)."""

    def __init__(self, said: str = "", detail: dict | None = None):
        super().__init__(said)
        self.detail = detail


def kb_env(cfg: Config) -> dict:
    """The environment of the `kb` the deck runs as him: `deck_env` and his token."""
    env = deck_env(cfg)
    env["KEEL_TOKEN"] = human_token(cfg.token_path)
    return env


def deck_env(cfg: Config) -> dict:
    """What the deck hands a child it runs, WITHOUT his token (c-451, review item 2): the
    `keel drain --once` behind Retry and create-and-start starts houses, and a drain never
    needs him. Only `kb_env`, for the `kb` the deck runs itself, adds the token."""
    env = dict(os.environ)
    env.pop("KEEL_TOKEN", None)
    env.pop("KEEL_CARD", None)
    env["KEEL_HOME"] = str(cfg.root)
    # A scratch config passes no KEEL_CONFIG: a named toml is taken at its word
    # (keel/config.py), so handing the child this worktree's own file would send it to the
    # live board the redirect just refused. KEEL_HOME above gets it the same answer.
    env.pop("KEEL_CONFIG", None)
    if cfg.source is not None and not cfg.scratch:
        env["KEEL_CONFIG"] = str(cfg.source)
    return env


# What kb is told it has for a merged-tree suite (`merging.TAP_ENV`): the deck's own wait,
# less a margin for the merge, the cleanup and the answer, so kb stops the suite itself and
# is never killed mid-test by the timeout below (lane E round 4, finding 4).
TAP_MARGIN = 30


def run_kb(cfg: Config, argv: list[str], timeout: int = SLOW_SECONDS, stdin: str = "",
           voice: bool = False):
    """`bin/kb <argv> --json`, as the human; the decoded output, or ActionError. `voice` is
    the voice page's answer to an ask (`voice_answer`): his token, actor voice."""
    kb = cfg.root / "bin" / "kb"
    env, lead = kb_env(cfg), ["--actor", "voice"] if voice else []
    env[merging.TAP_ENV] = str(max(timeout - TAP_MARGIN, 1))
    result = subprocess.run([str(kb), *lead, *argv, "--json"], capture_output=True, text=True,
                            input=stdin, env=env, timeout=timeout)
    if result.returncode != 0:
        raise ActionError((result.stderr.strip() or result.stdout.strip() or "kb failed").splitlines()[-1])
    try:
        return json.loads(result.stdout or "null")
    except ValueError:
        return result.stdout.strip()


def run_keel(cfg: Config, argv: list[str], timeout: int = SLOW_SECONDS) -> str:
    keel = cfg.root / "bin" / "keel"
    result = subprocess.run([str(keel), *argv], capture_output=True, text=True,
                            env=deck_env(cfg), timeout=timeout)
    if result.returncode != 0:
        raise ActionError((result.stderr.strip() or result.stdout.strip() or "keel failed").splitlines()[-1])
    return result.stdout.strip()


# ----- argument shaping -----

def need(body: dict, name: str) -> str:
    value = body.get(name)
    if value in (None, ""):
        raise ActionError(f"{body.get('verb', 'action')} needs {name}")
    return str(value)


def assignment(key: str, value) -> str:
    return f"{key}={value if isinstance(value, str) else json.dumps(value)}"


def create_argv(body: dict) -> list[str]:
    if body.get("words") and not body.get("title"):
        # c-729: filed from the user's own words (the first card's form): a short title, and
        # the words as the brief (`keel/cardtitle.py`)
        repo = body.get("repo") if isinstance(body.get("repo"), str) else None
        title, brief = cardtitle.from_words(str(body["words"]), str(body.get("brief") or ""), repo)
        body = {**body, "title": title, "brief": brief}
    argv = ["create", "--space", need(body, "space"), "--title", need(body, "title")]
    # `new_project` is the sheet's own field and `kb create` owns what it means (the repo,
    # the option and the attended default), so the deck passes the name and nothing else.
    for name in ("brief", "autonomy", "repo", "model", "parent", "from", "after", "topic",
                 "new_project", "assumed", "worker"):
        value = body.get(name)
        if value not in (None, "", []):
            argv += [f"--{name.replace('_', '-')}",
                     ",".join(value) if isinstance(value, list) else str(value)]
    for key, value in (body.get("options") or {}).items():
        argv += ["--option", assignment(key, value)]
    return argv


def set_argv(body: dict) -> list[str]:
    fields = body.get("fields") or {}
    if not fields:
        raise ActionError("set needs fields")
    argv = ["set", need(body, "id"), *(assignment(k, v) for k, v in fields.items())]
    # A GUESS STAYS A GUESS OVER HTTP (round 2, item B).
    assumed = body.get("assumed")
    if assumed:
        argv += ["--assumed", ",".join(assumed) if isinstance(assumed, list) else str(assumed)]
    return argv + why_argv(body)


def why_argv(body: dict) -> list[str]:
    """Bosun's repair reason (c-575), `=`-joined: a reason may open with a dash."""
    return [f"--why={body['why']}"] if body.get("why") is not None else []


def stage_argv(body: dict) -> list[str]:
    argv = ["stage", need(body, "id"), need(body, "stage")]
    for name in ("plan", "output", "note", "relay", "to"):
        if body.get(name):
            argv += [f"--{name}", str(body[name])]
    return argv + (["--sync"] if body.get("sync") else []) + why_argv(body)


def relay_argv(body: dict) -> list[str]:
    argv = ["relay", need(body, "id"), need(body, "what"), "--to", need(body, "to")]
    argv += ["--prompt", str(body["prompt"])] if body.get("prompt") else []
    argv += [f"--{flag}" for flag in ("gate", "held") if body.get(flag)]
    return argv + (["--sha", str(body["sha"])] if body.get("sha") else [])


def carried_argv(body: dict) -> list[str]:
    argv = ["carried", need(body, "id"), need(body, "relay")]
    if body.get("superseded"):
        argv += ["--superseded", str(body["superseded"])]
    return argv


def land_argv(body: dict) -> list[str]:
    argv = ["land", need(body, "id"), "--relay", str(need(body, "relay"))]
    return argv + (["--published", str(body["published"])] if body.get("published") else [])


SLICE_SEPARATOR = "|"
SLICE_REPO_MARKS = ("|", ",", "=")


def split_argv(body: dict) -> list[str]:
    """`kb split`'s argv from the page's slices. A slice travels as one `|`-separated text
    (`cli.parse_slice`), so a `|` in a title, a brief or an after-title, or a `|`, `,` or `=`
    in a repo key, would be read as another part: refused here, the rule the page states.
    Each of them is text: a null or a number is refused, never spelled into the slice."""
    argv = ["split", need(body, "id")]
    for piece in body.get("slices") or []:
        after = piece.get("after") or []
        after = [after] if isinstance(after, str) else list(after)
        repos = piece.get("repo") or []
        repos = [repos] if isinstance(repos, str) else list(repos)
        title, brief = piece.get("title", ""), piece.get("brief", "")
        for name, values in (("title", [title]), ("brief", [brief]), ("after-title", after), ("repo", repos)):
            if not all(isinstance(value, str) for value in values):
                raise ActionError(f"a slice's {name} is text")
        for name, values in (("title", [title]), ("brief", [brief]), ("after-title", after)):
            if any(SLICE_SEPARATOR in value for value in values):
                raise ActionError(f"a slice's {name} cannot contain `{SLICE_SEPARATOR}`")
        bad = next((key for key in repos if any(mark in key for mark in SLICE_REPO_MARKS)), None)
        if bad is not None:
            raise ActionError(f"a slice's repo is one key each, with no `|`, `,` or `=`: {bad!r}")
        text = "|".join([title, brief, *after])
        if repos:                                       # c-771: the slice's own repos
            text += "|repo=" + ",".join(repos)
        if piece.get("stack"):
            text += "|stack=" + str(piece["stack"])     # c-718: the owner's answer for the slice
        argv += ["--slice", text]
    if len(argv) == 2:
        raise ActionError("split needs slices")
    return argv


def session_argv(body: dict) -> list[str]:
    argv = ["session", need(body, "id"), "--set", need(body, "set")]
    if body.get("transcript"):
        argv += ["--transcript", str(body["transcript"])]
    for name in ("bg_id", "app_link", "expect"):
        if body.get(name):
            argv += [f"--{name.replace('_', '-')}", str(body[name])]
    if body.get("resumed") is not None:
        argv += ["--resumed", str(body["resumed"])]
        if body.get("automatic"):
            argv += ["--automatic"]      # the drain's once-only resume (c-605 review)
    return argv


def claim_argv(body: dict) -> list[str]:
    argv = ["claim", need(body, "id")]
    if body.get("host"):
        argv += ["--host", str(body["host"])]
    if body.get("release"):
        argv.append("--release")
    return argv


def list_argv(body: dict) -> list[str]:
    argv = ["list"]
    for name in ("space", "stage", "topic", "limit"):
        if body.get(name) not in (None, ""):
            argv += [f"--{name}", str(body[name])]
    for name in ("needs_you", "backlog", "all"):
        if body.get(name):
            argv.append(f"--{name.replace('_', '-')}")
    return argv


def repos_argv(body: dict) -> list[str]:
    argv = ["repos"]
    return argv + (["--space", str(body["space"])] if body.get("space") else [])


def needs_you_argv(body: dict) -> list[str]:
    argv = ["needs-you"]
    if body.get("space"):
        argv += ["--space", str(body["space"])]
    return argv + (["--backlog"] if body.get("backlog") else [])


def show_argv(body: dict) -> list[str]:
    argv = ["show", need(body, "id")]
    return argv + (["--events", str(body["events"])] if body.get("events") is not None else [])


def one_id(verb: str, *names: str):
    """An argv builder for `<verb> <id> <each named field>`, every one of them required."""
    return lambda body: [verb, need(body, "id"), *(need(body, name) for name in names)]


def said_of(body: dict) -> str:
    """What he typed beside an Approve, trimmed; a blank one is a plain approve."""
    return str(body.get("said") or "").strip()


def marked(body: dict) -> list[str]:
    """`--mark` on a note or a block, what Bosun's wake reads (c-522)."""
    return [f"--mark={body['mark']}"] if body.get("mark") else []


def approve_argv(body: dict) -> list[str]:
    """`approve <id> <gate> [--said <text>]`. The note is the KB half's, so his words are on
    the card's record before the resume half hands them to the house, and the terminal's own
    `kb approve --said` records them exactly the same way."""
    argv = ["approve", need(body, "id"), need(body, "gate")]
    said = said_of(body)
    checked = str(body.get("checked") or "").strip()
    # One argument with `=`: what he typed may open with a dash (a list of answers does), and
    # argparse would read a separate value like that as an unknown flag.
    return argv + ([f"--said={said}"] if said else []) + ([f"--checked={checked}"] if checked else [])


def unblock_argv(body: dict) -> list[str]:
    """`unblock <id> [--expect=<reason>]`, `=`-joined: a reason may open with a dash."""
    expect = body.get("expect")
    return [*one_id("unblock")(body), *([f"--expect={expect}"] if expect else []), *why_argv(body)]


ARGV_BUILDERS = {
    "create": create_argv, "set": set_argv, "stage": stage_argv, "split": split_argv,
    "session": session_argv, "claim": claim_argv, "relay": relay_argv,
    "carried": carried_argv, "land": land_argv, "list": list_argv,
    "needs-you": needs_you_argv, "show": show_argv, "repos": repos_argv,
    "tested": lambda body: ["tested", str(need(body, "commit")),
                            *(["--repo", str(body["repo"])] if body.get("repo") else []),
                            *(["--space", str(body["space"])] if body.get("space") else [])],
    "approve": approve_argv,
    "note": lambda body: [*one_id("note", "text")(body), *marked(body)],
    "block": lambda body: [*one_id("block", "reason")(body), *(["--keel"] if body.get("keel") else []),
                           *marked(body)],
    "console": requests.argv, "unblock": unblock_argv, "rereview": one_id("rereview"),
    "stop-check": one_id("stop-check"),
    "event": lambda body: ["event", need(body, "id"), "--hook", need(body, "hook")],
    "backlog": lambda body: ["backlog", need(body, "id"), str(body.get("choice") or "auto")],
    "tree": one_id("tree"),
    "flowinfo": one_id("flowinfo"),
    # His answer or note on a plan page (`keel/planstate.py`): one JSON argument, `=`-joined
    # so a value opening with a dash is never read as a flag.
    "mark": lambda body: ["mark", need(body, "id"), "--data=" + json.dumps(body.get("data") or {})],
    # `=`-joined: an answer may open with a dash, as a list does.
    "reply": lambda body: ["reply", need(body, "id"), "--ask", str(need(body, "ask")), "--text=" + need(body, "text")],
    # c-600: the house's verdict, already gathered on its machine: one JSON argument
    "verdict": lambda body: ["verdict", need(body, "id"), need(body, "handle"), "--data=" + need(body, "data")],
    "assign": lambda body: ["assign", need(body, "id"), *(["--dry-run"] if body.get("dry_run") else []),
                            *(["--ids", ",".join(map(str, body["ids"]))] if body.get("ids") else [])],
    "next": lambda body: ["next", need(body, "id"), *(["--clear"] if body.get("clear") else [])],
    "queue": lambda body: ["queue", *(["--space", str(body["space"])] if body.get("space") else [])],
}


def kb_argv(body: dict) -> list[str]:
    return ARGV_BUILDERS[body["verb"]](body)


def hook_stdin(body: dict) -> str:
    """The hook payload `kb event` and `kb stop-check` read on stdin, as JSON text."""
    payload = body.get("payload")
    return "" if payload in (None, "") else json.dumps(payload)


# ----- the house verbs -----

def card_of(board: Board, body: dict) -> dict:
    try:
        return board.get(need(body, "id"))
    except Refused as refusal:
        raise ActionError(str(refusal)) from None


HELD_NOTE = ("the house is working, so this waits on the board and is told to it when its turn "
             "ends")


def hold_here(cfg: Config, card: dict, prompt: str | None, gate: bool = False) -> dict:
    """His tap for a WORKING house on this machine, held rather than refused (c-598): a
    `resume` relay addressed to this very host, which its drain carries once the house's Stop
    kicks it. The board is the hold; nothing else remembers it."""
    flags = ["--held"] + (["--gate"] if gate else [])
    run_kb(cfg, ["relay", card["id"], "resume", "--to", cfg.host, *flags] + (["--prompt", prompt] if prompt else []))
    return {"relayed": "resume", "to": cfg.host, "held": True, "note": HELD_NOTE}


def bg_and_dir(cfg: Config, board: Board, card: dict) -> tuple[str, Path]:
    bg_id = drain.bg_id_of(board, card["id"]) or (card.get("session_id") or "")[:8]
    if not bg_id:
        raise ActionError(f"{card['id']} has no recorded house session")
    space = cfg.spaces.get(card["space"])
    if space is None:
        raise ActionError(f"unknown space {card['space']!r}")
    return bg_id, space.config_dir


def end_conversation(cfg: Config, board: Board, card: dict) -> bool:
    """Close a live voice conversation on the card and clear its hold.

    WHAT EVERY TAP OF HIS ON A HELD HOUSE DOES FIRST (V12 slice 2): Resume, Stop, and an
    answer at a gate. A resume or a wake is REFUSED while a headless `claude` still holds
    that session, so his tap would fail for a reason nothing on the page could explain. The
    hold is on the board and the conversation is owned by this machine's `keel serve`, so
    both are ended here and what goes out is a tap on a card nobody is talking to.

    THE HOUSE IS NOT WOKEN. Stop leaves it down because he stopped it; a resume and a gate
    answer put it back themselves, with a prompt. None of the three wants a wake in between.
    """
    if not views.voice_hold(card.get("options")):
        return False
    shut = housetier.close_session(cfg, card)
    if shut.status == housetier.FAILED:
        run_kb(cfg, ["note", card["id"],
                     "the live voice conversation would not close, so something may still "
                     "hold this session"])
    board.release_voice(card["id"])
    return True


def act_resume(cfg: Config, board: Board, body: dict, recorded: bool = False) -> dict:
    """`house.resume`: his tap on Resume.

    HIS TAP WINS OVER A VOICE HOLD, and the conversation goes with it (V12 slice 2). It is
    the same rule Stop and a gate answer already follow: a resume is REFUSED while a
    headless `claude` still holds that session, so a Resume tapped mid-conversation would
    fail for a reason nothing on the page could explain. No wake is asked for: the resume is
    what puts the house back.

    `said` is his ANSWER to a blocked house (F1, the blocked card's answer box): it goes to
    the house quoted in the resume prompt (`prompts.answer_resume`), and onto the card as
    his note once it has gone. `prompt`, the whole prompt verbatim, is for a caller that
    composes its own.

    HIS TAP COUNTS, WHATEVER BECAME OF IT (c-673): `house.resume` records the resume under
    the drain, so a Resume leaves an event of his for the backlog clock, written AFTER the
    attempt, by its outcome. Refused because the conversation is open in a terminal
    (`house.InTerminal`, two live sessions for the card included): nothing, it was not a
    Resume of this card. A refusal from the resume, or "resume failed": the ask note
    (`note_asked`), then the same refusal as before. Resumed, told or held: the ask note
    unless the tap already wrote his event (his answer's note, an unblock, the held relay).
    `recorded`: the caller writes its own (the flow move), so never. A tell that fails later
    on its own thread leaves the note standing; nothing waits for it. Still none, as before
    this card: the held relay or the unblock itself failing after the attempt, and a harness
    call that times out.
    """
    card = card_of(board, body)
    if not card.get("session_id"):
        raise ActionError(f"{card['id']} has no house session to resume; use Retry")
    try:
        house.refuse_if_done(card)      # before a held tap goes out, as below
    except Refused as refusal:
        raise ActionError(str(refusal)) from None
    try:
        # Here too, before a held tap goes out, so it never reads as asked (U3).
        house.refuse_if_in_terminal(card, None)
    except house.InTerminal as refusal:
        raise ActionError(str(refusal)) from None
    end_conversation(cfg, board, card)
    said = said_of(body)
    prompt = prompts.answer_resume(card["stage"], said) if said else (body.get("prompt") or None)
    try:
        result = house.resume(cfg, board, card["id"], prompt=prompt, tell=True, background=True)
    except house.InTerminal as refusal:
        raise ActionError(str(refusal)) from None
    except house.Busy:
        result = hold_here(cfg, card, prompt)           # c-598: told when its turn ends
    except Refused as refusal:
        note_asked(board, card, recorded)
        raise ActionError(str(refusal)) from None       # held by voice, or no model: his to read
    except (adapters.AdapterError, harness.HarnessError, OSError) as error:
        note_asked(board, card, recorded)
        raise ActionError(f"resume failed: {error}") from None
    if card["blocked_reason"]:
        run_kb(cfg, ["unblock", card["id"]])
    answered = note_answer(cfg, card, said)
    if not (answered or card["blocked_reason"] or result.get("held")):
        note_asked(board, card, recorded)
    return result


OPENED_NOTE = "woken for the Claude app from the deck, with no turn sent"
NO_LINK = ("{id}'s house is awake, but its claude.ai link has not shown up in its log yet; "
           "try Open in Claude app in a moment")


def act_open_app(cfg: Config, board: Board, body: dict) -> dict:
    """`house.open_app`: Resume and open in app (V2-2, `keel/openapp.py`).

    The house back with no turn and the link the page opens. His tap wins over a voice hold
    exactly as Resume's does (`end_conversation`). With a link in hand a blocked card is unblocked, as a resume would, because he is about to
    answer it in the app; with none the block stays his and the house stays awake.
    """
    card = card_of(board, body)
    if not card.get("session_id"):
        raise ActionError(f"{card['id']} has no house session to open; use Retry")
    try:
        house.refuse_if_in_terminal(card, None)
    except house.InTerminal as refusal:
        raise ActionError(str(refusal)) from None
    end_conversation(cfg, board, card)
    try:
        result = openapp.open_for_app(cfg, board, card["id"])
    except Refused as refusal:
        raise ActionError(str(refusal)) from None
    except (adapters.AdapterError, harness.HarnessError, OSError) as error:
        raise ActionError(f"the house would not wake: {error}") from None
    run_kb(cfg, ["note", card["id"], OPENED_NOTE if result["woken"]
                 else "opened in the Claude app from the deck; the house was already up"])
    if not result["link"]:
        return dict(result, note=NO_LINK.format(id=card["id"]))
    if card["blocked_reason"]:
        run_kb(cfg, ["unblock", card["id"]])
    return result


RESUME_ASKED = "resume asked from the deck"


def note_asked(board: Board, card: dict, recorded: bool = False) -> None:
    """His Resume tap on the card, as his, worded as the ask it is (c-673): true whether the
    house then came back, was told, or the resume failed. Straight onto the board, as
    `flowmoves.asked` writes its own, and never the tap's concern: a note that cannot be
    written is a missing record, and changes neither the tap's answer nor its refusal."""
    if recorded:
        return
    try:
        board.note(card["id"], RESUME_ASKED, "human")
    except (Refused, sqlite3.Error) as error:
        print(f"keel: the Resume of {card['id']} was not noted: {error}", file=sys.stderr)


def note_answer(cfg: Config, card: dict, said: str) -> bool:
    """His answer on the card, as his, LAST: once the house or its held tap has it and the
    card is unblocked. A resume that was refused carried nothing, so nothing says he
    answered; and a note that fails is only a missing record, never a failed tap, because
    the house already has his words. Whether it was written."""
    if not said:
        return False
    try:
        run_kb(cfg, ["note", card["id"], f"answered the block: {said}"])
    except ActionError as error:
        print(f"keel: the answer to {card['id']} reached the house but was not noted: {error}",
              file=sys.stderr)
        return False
    return True


def act_rotate(cfg: Config, board: Board, body: dict) -> dict:
    """`house.rotate`: his Rotate (`keel/rotate.py`). The checkpoint is asked for now; the
    drain starts the fresh session."""
    card = card_of(board, body)
    if not cfg.rotate:
        raise ActionError("rotation is switched off ([keel] rotate = false)")
    try:
        result = rotate.ask(cfg, board, card["id"])
    except Refused as refusal:
        raise ActionError(str(refusal)) from None
    except (adapters.AdapterError, harness.HarnessError, OSError) as error:
        raise ActionError(f"rotate failed: {error}") from None
    return dict(result, note="asked for a checkpoint; the drain starts the fresh session "
                             "when it is written")


def act_converse(cfg: Config, board: Board, body: dict) -> dict:
    """`house.converse`: one turn into this card's house, and the spoken answer back.

    The same verb the voice gateway and the phone Harbor run (`keel/converse.py`), so there
    is one connected turn in Keel and not three. The deck's own "Talk to this house" button
    opens voice already connected rather than posting this, because the microphone is the
    door this was asked for; the verb is here for a turn typed from anywhere else.
    """
    card = card_of(board, body)
    text = str(body.get("text") or "").strip()
    if not text:
        raise ActionError("a turn needs something to say")
    result = converse.answer(cfg, board, card["id"], text,
                             int(body.get("timeout") or harness.TURN_TIMEOUT))
    if not result.get("ok"):
        raise ActionError(result["say"])
    return result


def act_retry(cfg: Config, board: Board, body: dict) -> dict:
    """A fresh house on the card: unblock, back to assigned, then one explicit drain pass.
    Refused, before anything is reset, while the card's house is still listed live (c-605):
    a fresh house beside it is a twin, and nothing automatic stops the old one."""
    card = card_of(board, body)
    refuse_live_house(cfg, card)
    if card["blocked_reason"]:
        run_kb(cfg, ["unblock", card["id"]])
    if card["stage"] != "assigned":
        run_kb(cfg, ["stage", card["id"], "assigned", "--note", "retry from the deck"])
    elif (card.get("options") or {}).get("claim"):
        # Claimed by a drain that never started it: free it.
        run_kb(cfg, ["claim", card["id"], "--release"])
    try:
        return {"drain": run_keel(cfg, ["drain", "--once", "--card", card["id"]], timeout=CARD_PASS_SECONDS)}
    except (ActionError, subprocess.TimeoutExpired) as error:
        # The looping drain on this machine may have started it first (one house per card,
        # `house.launch`), or the pass outran the deck's wait while it started it: either
        # way a card now housed is the retry done, not a failure.
        now = board.get(card["id"])
        if (now["stage"] != "assigned" and now.get("session_id")
                and now.get("session_id") != card.get("session_id")):
            return {"drain": f"{card['id']} started ({now['stage']})"}
        if isinstance(error, subprocess.TimeoutExpired):
            raise ActionError(f"the drain pass for {card['id']} did not answer in "
                              f"{int(error.timeout)}s and the card has not started") from None
        raise


def refuse_live_house(cfg: Config, card: dict) -> None:
    """ActionError when the card's recorded session is listed live (c-605)."""
    if not card.get("session_id"):
        return
    space = cfg.spaces.get(card["space"])
    row = harness.find(card["session_id"], harness.agents(space.config_dir if space else None))
    why = house.live_twin(card, row)
    if why:
        raise ActionError(why)


def act_stop(cfg: Config, board: Board, body: dict) -> dict:
    card = card_of(board, body)
    if body.get("twin"):
        return stop_twin(cfg, card, str(body["twin"]))
    bg_id, config_dir = bg_and_dir(cfg, board, card)
    held = views.voice_hold(card.get("options"))
    if not held:
        refuse_ended(card, bg_id, config_dir, "stopped")
    # HIS TAP WINS OVER A VOICE HOLD, and it leaves the house DOWN. Stop is the one place a
    # human ends a session on purpose, so a hold is not a reason to refuse him and the house
    # is not woken afterwards: he stopped it. The hold goes with the same tap, because
    # leaving it would keep the drain away from a session nobody is talking to any more, and
    # the gateway drops its pin on its next turn (`keel converse` answers "that house was
    # stopped" once the hold it was holding is gone).
    if held:
        # THE CONVERSATION GOES WITH THE HOLD (V12). It is a `claude` holding that session,
        # owned by this machine's `keel serve`, and leaving it open would keep the session
        # occupied by a conversation nobody is in. A close that FAILED is noted rather than
        # refused: his tap stops the house either way, and the record is what makes a
        # session still held by something findable afterwards.
        if housetier.close_session(cfg, card).status == housetier.FAILED:
            run_kb(cfg, ["note", card["id"],
                         "stopped from the deck, but the live voice conversation would "
                         "not close: something may still hold this session"])
        board.release_voice(card["id"])
    try:
        ended = housejobs.stop(bg_id, config_dir, harness.stop)
    except harness.HarnessError as error:
        raise ActionError(str(error).splitlines()[0]) from None
    said = (f"session {bg_id} stopped from the deck while voice was talking to it; the hold "
            f"is released and the house is left down" if held
            else f"session {bg_id} stopped from the deck")
    if housejobs.said(ended):
        said += f"; {housejobs.said(ended)}"
    # Marked (c-605): the drain resumes an exited house once, and this one did not exit,
    # he put it down. The mark keeps it down until his Resume or Retry.
    run_kb(cfg, ["note", card["id"], said, "--mark", "human-stop"])
    # `released` only when there was something to release: the answer a deck reads has said
    # `{"stopped": <id>}` since the button existed, and a key that is always there would
    # make every ordinary stop look like it had ended a conversation.
    return {"stopped": bg_id, "released": True} if held else {"stopped": bg_id}


def act_close_idle(cfg: Config, board: Board, body: dict) -> dict:
    """`house.close_idle` (c-607): his Close idle house, on one card (`id`) or on several at
    once (`ids`, Now's Close all idle). Each is checked idle again NOW (`idleclose.not_idle`)
    and refused with its reason when it is not; one refused card never stops the others.
    One card's refusal is the tap's; with `ids` the answer names each. The many-card form is
    a pass, so each of its notes carries the bulk mark beside `closed-idle` and none restarts
    a card's backlog clock; his close of one house is his action on that card (c-673)."""
    ids = body.get("ids")
    if ids is None:
        return close_idle_one(cfg, board, card_of(board, body))
    if not isinstance(ids, list) or not ids:
        raise ActionError("ids is a list of card ids")
    closed, refused = [], {}
    for card_id in ids:
        try:
            closed.append(close_idle_one(cfg, board, card_of(board, {"id": str(card_id)}), bulk=True))
        except ActionError as error:
            refused[str(card_id)] = str(error)
    n = len(closed)
    note = f"closed {n} idle {'house' if n == 1 else 'houses'}" + "".join(f"; {why}" for why in refused.values())
    return {"closed": closed, "refused": refused, "note": note}


def close_idle_one(cfg: Config, board: Board, card: dict, bulk: bool = False) -> dict:
    """One card's Close idle house, at review or shipping only (`idleclose.STAGES`), under
    the card's lock (`idleclose.close_here`)."""
    if card["stage"] not in idleclose.STAGES:
        raise ActionError(f"{card['id']} is at {card['stage']}, where nothing would bring its house "
                          f"back; Stop session ends it")
    if not card.get("session_id"):
        raise ActionError(f"{card['id']} has no recorded house session")
    try:
        card, bg_id, ended = idleclose.close_here(cfg, board, card["id"])
    except idleclose.NotIdle as why:
        raise ActionError(f"{card['id']} was not closed: {why}") from None
    run_kb(cfg, ["note", card["id"], idleclose.said(bg_id, ended, stage=card["stage"]),
                 "--mark", idleclose.MARK, *(["--bulk"] if bulk else [])])
    return {"closed": bg_id, "id": card["id"], "note": idleclose.closed_said(card["stage"])}


def stop_twin(cfg: Config, card: dict, twin: str) -> dict:
    """His tap on "Stop stale session" (c-601 review): the OTHER live session named for the
    card, which `tellhouse.refuse_twins` asks him to stop. Only a session listed live under
    the card's name, and never the card's own recorded one, whatever the tap says."""
    space = cfg.spaces.get(card["space"])
    if space is None:
        raise ActionError(f"unknown space {card['space']!r}")
    row = harness.find(twin, harness.agents(space.config_dir))
    if row is None or row.get("name") != card["id"] or not housejobs.has_process(row):
        raise ActionError(f"no live session {twin} is named {card['id']}; nothing was stopped")
    own = card.get("session_id") or ""
    if row.get("sessionId") == own or (own and str(row.get("id")) == own[:8]):
        raise ActionError(f"{twin} is {card['id']}'s own session; Stop session ends that one")
    bg_id = str(row.get("id") or twin)
    try:
        ended = housejobs.stop(bg_id, space.config_dir, harness.stop)
    except harness.HarnessError as error:
        raise ActionError(str(error).splitlines()[0]) from None
    said = f"stale session {bg_id}, also named {card['id']}, stopped from the deck"
    if housejobs.said(ended):
        said += f"; {housejobs.said(ended)}"
    run_kb(cfg, ["note", card["id"], said])
    return {"stopped": bg_id, "twin": True}


def refuse_ended(card: dict, bg_id: str, config_dir, what: str) -> None:
    """Refuse a Stop or a Logs on a recorded session the harness no longer lists (c-601,
    e2e bug 13): Stop used to note "stopped from the deck" for a session that had already
    ended, and Logs answered "job not found". Nothing is written; the refusal says why."""
    if harness.find(card.get("session_id") or bg_id, harness.agents(config_dir)) is None:
        raise ActionError(f"session {bg_id} of {card['id']} has already ended; nothing was {what}")


def act_logs(cfg: Config, board: Board, body: dict) -> dict:
    card = card_of(board, body)
    bg_id, config_dir = bg_and_dir(cfg, board, card)
    refuse_ended(card, bg_id, config_dir, "read")
    return {"bg_id": bg_id, "logs": drain.tail(harness.logs(bg_id, config_dir), int(body.get("lines") or 200))}


def dropin_afresh(cfg: Config, board: Board, card: dict, facts: dict) -> dict | None:
    """c-654 (c-020): the command for an exited house is `claude --resume <id>`, which fails
    at his terminal when the harness no longer holds that conversation. So the harness is
    asked first (`keel/afresh.py`), in the directory that command would enter, and a house
    whose conversation is gone is started afresh from the card's record (`afresh.if_gone`);
    the command handed out is then the one that joins the NEW session. A hold left from an
    earlier try names the old session and is cleared. A done card whose conversation is
    gone, and a fresh start Keel would not make, are refused with the reason: no command,
    no hold. The start, or None when the old conversation is there."""
    try:
        started = afresh.if_gone(cfg, board, card["id"], prompts.JOIN_AFRESH, cwd=facts.get("cwd"))
    except (Refused, adapters.AdapterError, harness.HarnessError, OSError) as error:
        raise ActionError(f"drop in failed: {error}") from None
    if started and views.dropin_hold(card.get("options")):
        run_kb(cfg, ["set", card["id"], f"options.{views.DROPIN_HOLD_OPTION}=null"])
    return started


def dropin_done(cfg: Config, board: Board, card: dict) -> dict:
    """c-787: Drop in on a DONE card, to discuss the finished work. Its conversation first:
    the harness files it under the house directory, so when the worktree was torn down the
    directory is made empty for the gone probe and removed again (`dropin.reopen_place`),
    and the resume command makes it itself and removes it on exit while empty
    (`dropin.remade`, c-789). `facts` is handed that directory, since `cwd_of` reads an
    empty one as absent. Only when the harness says
    the conversation is gone, or the card has no session or no directory, a fresh session
    in the card's record (`dropin.from_record`). No house is started and no hold is taken:
    nothing on a done card resumes in the background."""
    try:
        with dropin.reopen_place(cfg, card) as (place, made):
            facts = dropin.facts(cfg, card, cwd=place) if place is not None else None
            if facts and facts["how"] == dropin.RESUME and afresh.done_gone(cfg, card, facts["cwd"]):
                facts = None
        if facts is None or facts["how"] == dropin.NEW:
            facts = dropin.from_record(cfg, card)
        elif facts["how"] == dropin.RESUME and made:
            facts = dropin.remade(facts, made)
    except dropin.NoPlace as error:
        raise ActionError(str(error)) from None
    except (adapters.AdapterError, harness.HarnessError, OSError) as error:
        raise ActionError(f"drop in failed: {error}") from None
    run_kb(cfg, ["note", card["id"], f"drop-in command handed out from the deck on a done card ({facts['how']})"])
    return {"command": facts["command"], "cwd": facts.get("cwd"), "how": facts["how"],
            "status": facts.get("status"), "said": facts.get("said")}


def act_dropin(cfg: Config, board: Board, body: dict) -> dict:
    """The command that enters the card's house from the desk (`keel/dropin.py`).

    Worked out from the house's cwd, its config dir and whether the session is live."""
    card = card_of(board, body)
    if card["stage"] == "done":
        return dropin_done(cfg, board, card)
    try:
        facts = dropin.facts(cfg, card)
        started = dropin_afresh(cfg, board, card, facts) if facts.get("how") == dropin.RESUME else None
        if started:
            # the new house is joined by its own id, or nothing is handed out (never a resume)
            card = board.get(card["id"])
            facts = dropin.joined(cfg, card, started)
    except dropin.NoPlace as error:
        raise ActionError(str(error)) from None
    command = facts["command"]
    if facts.get("how") == dropin.RESUME:
        # U3: he is about to be in that conversation at a terminal, where a resume from
        # here, his own Resume house included, would start a second copy of it.
        hold = json.dumps(dropin.hold_record(card), separators=(",", ":"))
        run_kb(cfg, ["set", card["id"], f"options.{views.DROPIN_HOLD_OPTION}={hold}"])
    run_kb(cfg, ["note", card["id"], f"drop-in command handed out from the deck ({facts.get('how')})"])
    return {"command": command, "cwd": facts.get("cwd"), "how": facts.get("how"),
            "status": facts.get("status"), "said": facts.get("said")}


# ----- the gate verbs -----

def card_or_none(board: Board, body: dict) -> dict | None:
    """The card, or None when this board cannot read it (the kb call still stands alone)."""
    try:
        return board.get(need(body, "id"))
    except Refused:
        return None


def gate_of(card: dict) -> str | None:
    derived = card["derived"]
    return "plan" if derived["plan_gate"] else ("outcome" if derived["outcome_gate"] else None)


def resume_with(cfg: Config, board: Board, card_id: str, prompt: str,
                actor: str = "human") -> dict | None:
    """Resume the card's house with this prompt; None when it has no session to resume."""
    card = board.get(card_id)
    if not card.get("session_id"):
        return None
    try:
        # His own answer at a gate: it releases a voice hold rather than being refused by
        # one, because a human answering the gate is plainly done talking to the house.
        # The conversation is closed FIRST (V12): a resume is refused while a headless
        # process still holds the session, so the order is what makes the gate answer work
        # mid-conversation at all.
        # Bosun's approval (c-522) is refused on a held card before it gets here, so it
        # never closes his conversation and never forces past a hold: only his tap does.
        if actor != "human":
            try:
                return house.resume(cfg, board, card_id, prompt=prompt, actor=actor, tell=True,
                                    background=True)
            except house.Busy:
                raise
            except Refused as held:
                # A hold that began after the move: the approval stands, the house waits
                # for him, and this may not raise (the move already landed).
                after_move_note(board, card_id, f"approved by Bosun, but the house was not resumed: {held}",
                           actor)
                return None
        if housetier.close_session(cfg, card).status == housetier.FAILED:
            board.note(card_id, "the live voice conversation would not close before your "
                                "answer at the gate; if the resume fails, that is why",
                       "human")
        return house.resume(cfg, board, card_id, prompt=prompt, force=True, tell=True,
                            background=True)
    except (adapters.AdapterError, harness.HarnessError, OSError) as error:
        raise ActionError(f"resume failed: {error}") from None


def after_move_note(board: Board, card_id: str, text: str, actor: str) -> None:
    """A note written after a gate's move landed: it may not raise, so a Bosun note the card
    now refuses (builder mode switched off in between) is dropped rather than failing the tap."""
    try:
        board.note(card_id, text, actor)
    except Refused:
        pass


def gate_answer(cfg: Config, board: Board, card_id: str, prompt: str, actor: str = "human",
                what: str = "plan", **extra) -> dict:
    """What every gate verb returns: the card, the prompt the house got, and whether it ran.

    A house that is WORKING is not resumed (`house.Busy`, E1): the move already landed, so
    the refusal is the answer's note, never a failure for a move that happened. His own
    answer to a working house on this machine is HELD instead (c-598, `hold_here`), and told
    to it when its turn ends; one in his terminal is still only noted.

    A card Bosun builds has no house to resume (c-734): the user's tap is told to Bosun
    instead (`bosun_told`, `what` names the tap), whatever session the card carries."""
    if merging.bosun_card(board.get(card_id)):
        return bosun_told(board, card_id, what, actor, cfg=cfg, **extra)
    try:
        resumed, busy = (resume_with(cfg, board, card_id, prompt, actor) if actor != "human"
                         else resume_with(cfg, board, card_id, prompt)), None
    except house.Busy as refusal:
        resumed, busy = None, str(refusal)
        if actor == "human" and not isinstance(refusal, house.InTerminal):
            held = hold_here(cfg, board.get(card_id), prompt, gate=True)
            return {"card": board.get(card_id), "prompt": prompt, "resumed": None,
                    "note": held["note"], "held": True, **extra}
        after_move_note(board, card_id, f"your answer at the gate is on the card, but {busy}", actor)
    card = board.get(card_id)
    note = busy or ((resumed or {}).get("note") if resumed else NOT_RESUMED)
    return {"card": card, "prompt": prompt, "resumed": resumed, "note": note, **extra}


NOT_RESUMED = "no house session to resume; use Retry"


def bosun_told(board: Board, card_id: str, what: str, actor: str = "human", cfg=None, **extra) -> dict:
    """A gate tap on a card Bosun builds (c-734): the move already landed; the user's tap is
    recorded as a `tell`, which the drain's next wake tells Bosun (`keel/pausewake.py`), and
    no house is resumed. Bosun's own approval tells nobody: it is Bosun's doing."""
    if actor == "human":
        pausewake.tell(board, card_id, what, cfg=cfg)
    mine = actor == "human"
    return {"card": board.get(card_id), "prompt": None, "resumed": None, "told": what if mine else None,
            "note": pausewake.TOLD_NOTE if mine else "approved; no house is resumed for a card Bosun builds", **extra}


def act_approve(cfg: Config, board: Board, body: dict):
    """`approve`: the human's kb verb, and at the plan gate the resume that starts the build.

    An optional `said` is what he typed beside the tap, his answers to the plan's open
    questions above all. `kb approve --said` notes it on the card, and at the PLAN gate the
    resume prompt quotes it, which is the only way words of his reach a house whose plan is
    markdown. At the outcome gate the tap publishes (a work card then keeps its house at
    shipping, c-600, and a card that is done has it ended), so there is nothing to resume:
    the note is the whole of it, and it is still worth having ("merged, but follow up on X"
    belongs on the card's record).
    """
    gate = need(body, "gate")
    card = card_or_none(board, body)
    if card is not None and gate == "outcome" and onboarding.proposes(card):
        # A proposal's outcome IS its draft, a flow's (c-640 review 2) or a tier's (c-667):
        # his Approve adopts it as Adopt in Setup does, so the card never closes without
        # writing it, and a draft Adopt refuses leaves it at review with that reason.
        try:
            adopted = onboarding.adopt_proposal(cfg, board, card["id"])
        except (onboarding.SetupError, Refused) as error:
            raise ActionError(str(error)) from None
        if said_of(body):
            board.note(card["id"], said_of(body), "human")     # his words beside the tap
        return adopted
    if card is not None and gate == "outcome" and tracking_card(card):
        # Closed, not published (lane X): each slice landed or published on its own, so a
        # tracking card needs no landing, only the move. The drain closes one whose slices
        # are all done (c-649), so a tap that comes after finds it done, and that is the answer.
        if card["stage"] == "done":
            return card
        return run_kb(cfg, kb_argv(body))
    if card is not None and gate == "outcome" and landing.route(cfg, card, tap=True):
        return outcome_told(cfg, board, card, queue_landing(cfg, card, said_of(body), board))
    prompt = (prompts.approve(card.get("plan_ref"), said=said_of(body))
              if card is not None and gate == "plan" else None)
    try:
        result = run_kb(cfg, kb_argv(body))
    except ActionError as error:
        if gate == "outcome" and card is not None and "merge conflict" in str(error):
            return outcome_told(cfg, board, card, merge_conflict(cfg, board, card, str(error)))
        raise
    if gate != "plan" or card is None:
        return outcome_told(cfg, board, card, result) if card is not None else result
    return gate_answer(cfg, board, card["id"], prompt)


BOSUN_STAY = ("{card} is built by Bosun, so it has no house to hold a discussion: talk it over with Bosun "
              "in its session, or Send back without staying")


def outcome_told(cfg, board: Board, card: dict, result):
    """Approve outcome on a card Bosun builds is told to Bosun too (c-734, `bosun_told`):
    the landing, the publish or the merge it asks for goes on as before, and the answer
    says Bosun hears of it."""
    if not merging.bosun_card(card):
        return result
    pausewake.tell(board, card["id"], "outcome", cfg=cfg)
    if isinstance(result, dict):
        return dict(result, told="outcome", note=" ".join(filter(None, [result.get("note"), pausewake.TOLD + "."])))
    return {"card": board.get(card["id"]), "result": result, "told": "outcome", "note": pausewake.TOLD + "."}


def pinned_sha(cfg: Config, card: dict) -> str:
    """The sha of the branch he is approving (finding 1)."""
    try:
        sha = merging.branch_head(cfg, card)
    except merging.MergeRefused as refused:
        raise ActionError(str(refused).splitlines()[0]) from None
    if not sha:
        raise ActionError(f"{card['id']} has no branch to land")
    return sha


def queue_landing(cfg: Config, card: dict, said: str, board=None) -> dict:
    """Approve outcome as a `land` relay (`keel/landing.py`): the drain builds the merged
    tree, tests it and lands it, and the card shows landing, testing, landed. The tap returns
    now rather than after the suite. The drain is asked for one pass at once, so the landing
    starts without waiting for the next poll; a pass that cannot run leaves it to that poll.
    `--no-wait`: while another pass runs it skips at once rather than wait for the pass lock
    (`keel/passlock.py`, c-734), so the tap still returns now."""
    sha = pinned_sha(cfg, card)
    run_kb(cfg, ["relay", card["id"], "land", "--to", cfg.host, "--sha", sha])
    if said:
        run_kb(cfg, ["note", card["id"], said])
    try:
        run_keel(cfg, ["drain", "--once", "--card", card["id"], "--no-wait"])
    except (ActionError, subprocess.SubprocessError, OSError):
        pass
    return {"card": card, "relayed": "land", "to": cfg.host, "note": landing_note(cfg, card, board)}


def landing_note(cfg: Config, card: dict, board=None) -> str:
    """What Approve outcome says it queued: a repo with no test command (`[tests]` in the
    config, or the Run the tests line of its adopted CLAUDE.md, `keel/repocommands.py`)
    lands untested, and the note must not promise a suite that never runs (c-621). A repo
    whose file changed since it was adopted or saved will be refused, and the note says that
    (c-678 review). `board` is the caller's, so the record is read on it."""
    refused = repocommands.refusal(cfg, card.get("space"), card.get("repo"), board)
    if refused:
        return f"queued to land, and it will be refused: {refused}"
    why = repocommands.untested(cfg, card.get("space"), card.get("repo"), board)
    if not why:
        return "queued to land: the merged tree is built and tested, and lands only if it is green"
    return f"queued to land: the merged tree is built and lands untested, since {why}"


def merge_conflict(cfg: Config, board: Board, card: dict, reason: str) -> dict:
    """The approve stood but the merge conflicted because main moved: unblock, back to
    building, and resume the house with the merge as its next task. The human approves
    again when it is back at review; that merge is then clean. A card Bosun builds goes
    back to building with a note for Bosun instead, and nothing is resumed (c-647)."""
    match = re.search(r"merge conflict: (\S+) moved past (\S+)", reason)
    # The branch that moved, as the refusal named it; None when it named none, and then the
    # house, the note and the deck's sentence say "its target branch", never a guessed name
    # (c-665).
    target, branch = (match.group(1), match.group(2)) if match else (None, "your branch")
    if merging.bosun_card(card):
        # c-647: a card Bosun builds goes back to building for Bosun; no house is resumed,
        # whatever session the card carries, and the deck's "merging" word is not set
        note = landing.bosun_merges(target, branch if match else "its branch")
        run_kb(cfg, ["unblock", card["id"]])
        run_kb(cfg, ["stage", card["id"], "building", "--note", note])
        return {"card": board.get(card["id"]), "prompt": None, "resumed": None, "note": note,
                "merge_conflict": True, "target": target, "bosun": True}
    prompt = prompts.merge_main(target or "", branch)
    run_kb(cfg, ["unblock", card["id"]])
    run_kb(cfg, ["stage", card["id"], "building", "--note",
                 f"{target or 'its target branch'} moved; the house merges it first"])
    run_kb(cfg, ["set", card["id"], "options.merging=true"])   # the deck's "merging its target" word
    return gate_answer(cfg, board, card["id"], prompt, merge_conflict=True, target=target)


def tracking_card(card: dict) -> bool:
    """A card cut into slices (`derived.tracking`): closed by the drain when every slice is
    done (or by his Approve while it waits at review), never published, landed or resumed
    (lane X, c-649)."""
    return bool((card.get("derived") or {}).get("tracking"))


TRACKING_SENT_BACK = ("back to tracking with your reason as a note; no house was resumed, "
                      "since its slices carry the work. The drain closes it when a slice "
                      "changes and every slice is done")


def act_sendback(cfg: Config, board: Board, body: dict) -> dict:
    """Send the work back with the human's reason; `stay` opens a discussion instead."""
    card = card_of(board, body)
    reason = need(body, "reason")
    stay = bool(body.get("stay"))
    gate = gate_of(card)
    if gate is None:
        raise ActionError(f"{card['id']} is at {card['stage']} with no gate open to send back from")
    if stay and merging.bosun_card(card):
        # c-734 r1.F16: a discussion is a house's turn on the plan surface, and a card Bosun
        # builds has no house; Bosun's own session is where its plan is talked over, so a
        # second, "discuss" tell would only point there
        raise ActionError(BOSUN_STAY.format(card=card["id"]))
    surface = discussion_surface(card, gate) if stay else None  # refused before anything is written
    run_kb(cfg, ["note", card["id"], reason])
    if stay:
        # The card stays at planning with its gate open: the house holds its slot on purpose.
        run_kb(cfg, ["set", card["id"], f"options.{DISCUSSION_OPTION}=true"])
        prompt = prompts.discussion(surface, reason, cfg.discussion_idle_seconds)
    elif gate == "outcome" and tracking_card(card):
        # Back to tracking (lane X): there is no house of its own to resume, so his reason
        # is the note above and the move is all there is.
        run_kb(cfg, ["stage", card["id"], "building", "--note", "sent back from the deck"])
        return {"card": board.get(card["id"]), "prompt": None, "resumed": None, "gate": gate,
                "stay": stay, "note": TRACKING_SENT_BACK}
    elif gate == "outcome":
        prompt = prompts.sendback_outcome(reason)
        run_kb(cfg, ["stage", card["id"], "building", "--note", "sent back from the deck"])
        return gate_answer(cfg, board, card["id"], prompt, what="sendback", gate=gate, stay=stay)
    else:
        prompt = prompts.sendback_plan(card.get("plan_ref"), reason)
    return gate_answer(cfg, board, card["id"], prompt, what="sendback", gate=gate, stay=stay)


def discussion_surface(card: dict, gate: str) -> str:
    """The plan surface a discussion runs on, or the reason there cannot be one."""
    if gate != "plan":
        raise ActionError(f"stay is a plan discussion; {card['id']} is at the outcome gate")
    plan_ref = card.get("plan_ref") or ""
    if not prompts.is_surface(plan_ref):
        raise ActionError(f"a discussion needs a lavish surface; {card['id']}'s plan is "
                          f"{plan_ref or 'not set'}")
    return plan_ref


def act_end_discussion(cfg: Config, board: Board, body: dict) -> dict:
    """End the lavish session so the house's own poll returns and its loop ends naturally.

    Never `claude stop`: the house is mid-turn by design, and ending its session would
    throw away the discussion. The flag is cleared by the card's turn-end hook.
    """
    card = card_of(board, body)
    plan_ref = card.get("plan_ref") or ""
    if not prompts.is_surface(plan_ref):
        raise ActionError(f"{card['id']} has no lavish surface to end "
                          f"(its plan is {plan_ref or 'not set'})")
    try:
        ended = artifacts.end_surface(plan_ref)
    except artifacts.LavishError as error:
        raise ActionError(str(error)) from None
    run_kb(cfg, ["note", card["id"], "discussion ended from the deck"])
    return dict(ended, house="its poll returns now; the turn-end hook clears options.discussion")


# ----- the board verbs -----

def act_board(cfg: Config, board: Board, body: dict):
    """`board.*`: the blackboard, one action per verb (`keel/boards.py`).

    Every body is the deck page's own tap, which is the human.
    """
    verb = str(body.get("verb") or "").split(".", 1)[-1]
    caller = {"actor": "human", "card": None}
    actor = caller["actor"]
    try:
        if verb == "push":
            return boards.push(cfg, str(body.get("ops") or ""), card=body.get("card"),
                               talker=bool(body.get("talker")), title=body.get("title"),
                               actor=actor, caller=caller,
                               card_title=boards.card_title(cfg, body.get("card")),
                               new=bool(body.get("new")), board_id=body.get("board") or None)
        if verb == "list":
            if body.get("deleted"):
                return boardtrash.trashed(cfg)
            return boards.listing(cfg, card=body.get("card"), limit=int(body.get("limit") or 0))
        if verb == "find":
            return boards.find(cfg, str(body.get("text") or ""), limit=int(body.get("limit") or 0))
        if verb == "show":
            return boards.show(cfg, need(body, "id"))
        if verb == "open":
            return boards.reopen(cfg, need(body, "id"), caller=caller)
        if verb == "new":
            return boards.copy_to_new(cfg, need(body, "from"), body.get("title"), actor,
                                      caller=caller)
        if verb == "close":
            return boards.close(cfg, need(body, "id"), body.get("summary"), caller=caller)
        if verb == "delete":
            # A HOUSE, HARBOR OR HIM, each held to its own boards (`boardtrash.may_delete`),
            # one id or a stack's `ids`, refused whole when one of them is not the caller's.
            ids = body.get("ids") or [need(body, "id")]
            return boardtrash.delete(cfg, [str(i) for i in ids], caller)
        if verb == "restore":
            return boardtrash.restore(cfg, need(body, "id"), caller)
    except (boards.BoardError, boardfiles.BoardFileError) as error:
        raise ActionError(str(error)) from None
    raise ActionError(f"no verb called {body.get('verb')!r}")


# ----- adapter verbs -----

# The capability each adapter route needs (c-631): Reviews' verbs (Scan now, its settings)
# need review scanning, a card's own verbs the tracker.
ROUTE_NEEDS = {"reviews": "reviews", "card": "tracker"}


def act_adapter(cfg: Config, board: Board, body: dict) -> dict:
    """A route or card verb the space's adapter owns. A route whose capability the space does
    not declare is refused with the sentence its readiness row says (c-631)."""
    space = cfg.spaces.get(need(body, "space"))
    args = {"route": need(body, "route"), "action": need(body, "action"),
            "key": str(body.get("key") or ""), "args": body.get("args") or {}}
    refused = space and ROUTE_NEEDS.get(args["route"]) and readiness.refusal(
        cfg, space, ROUTE_NEEDS[args["route"]])
    if refused:
        raise ActionError(refused)
    if space is None or space.adapter_dir is None:
        raise ActionError(f"space {body.get('space')!r} has no adapter")
    try:
        return adapters.run_act(space, args["route"], args["action"], args["key"], args["args"])
    except adapters.AdapterError as error:
        raise ActionError(str(error)) from None


def act_console(cfg: Config, board: Board, body: dict) -> dict:
    """`console.start`, `console.stop`, `console.restart`: his tap on Bosun's session
    (`keel/consoletaps.py`), on this machine."""
    op = str(body.get("verb") or "").partition(".")[2]
    if not console.configured(cfg):
        raise ActionError(console.NO_BOSUN)
    try:
        result = consoletaps.tap(cfg, op, "human")
    except console.ConsoleError as error:
        raise ActionError(str(error)) from None
    console.forget_view()
    return {"console": result, "note": f"Bosun: {op} done"}


def act_flow_move(cfg: Config, board: Board, body: dict) -> dict:
    """`flow.move` {id, move}: his tap on a move of the card's space flow (c-640,
    `keel/flowmoves.py`): checked, recorded, then the house told as Resume tells it."""
    card = card_of(board, body)
    try:
        move = flowmoves.move_of(cfg, card, need(body, "move"))
    except flowmoves.MoveError as error:
        raise ActionError(str(error)) from None
    if not card.get("session_id"):
        raise ActionError(f"{card['id']} has no house to carry {move.label} out; start it first")
    said = flowmoves.prompt(cfg, card, move)
    # The grant goes first, so a house told at once finds it; a tell that is refused or fails
    # takes it back, so no grant outlives a move the house never heard of (c-640 review).
    flowmoves.grant(cfg, board, card, move)
    try:
        # `recorded`: the grant above and the note below are this tap's events of his
        told = act_resume(cfg, board, {"id": card["id"], "prompt": said}, recorded=True)
    except ActionError:
        flowmoves.revoke(board, card)
        raise
    flowmoves.asked(board, card, move)
    return dict(told, move=move.id, note=f"{move.label}: the house was told")


CONSOLE_VERBS = {f"console.{op}": act_console for op in console.OPS}
HOUSE_VERBS = {"house.resume": act_resume, "house.retry": act_retry, "house.stop": act_stop,
               idleclose.VERB: act_close_idle,
               "house.rotate": act_rotate, "house.open_app": act_open_app,
               "house.logs": act_logs, "house.converse": act_converse, "dropin": act_dropin,
               "adapter": act_adapter, flowmoves.VERB: act_flow_move, **CONSOLE_VERBS}
# The gate verbs are tried first: `approve` is a kb verb whose argv `kb_argv` still builds,
# but at the plan gate it has a second half (the resume) that plain kb knows nothing about.
def act_plan_send(cfg: Config, board: Board, body: dict) -> dict:
    """`plan.send` {id, mode: approve|sendback, doc}: his whole round on the plan page,
    composed on the server and carried by the gate verbs above (`keel/planactions.py`)."""
    try:
        return planactions.send(cfg, board, body, approve=act_approve, sendback=act_sendback,
                                run_kb=run_kb, gate_of=gate_of)
    except (planactions.SendError, Refused) as error:
        raise ActionError(str(error)) from None


def act_plan_ask(cfg: Config, board: Board, body: dict) -> dict:
    """`plan.ask` {id, doc, block, quote, text}: his question on the plan page, sent to the
    house at once without sending the plan back (`keel/planask.py`)."""
    try:
        return planask.ask(cfg, board, body, run_kb=run_kb, gate_of=gate_of, hold=hold_here)
    except (planask.AskError, Refused) as error:
        raise ActionError(str(error)) from None


def act_ship(cfg: Config, board: Board, body: dict) -> dict:
    """His Ship on a shipping card (c-600): the adapter pushes the house's commits, marks a
    draft ready and posts the replies he kept, once (`Board.ship`). The card stays at
    shipping."""
    card = card_of(board, body)
    anyway = body.get("anyway") is True
    try:
        result = run_kb(cfg, ["ship", card["id"], *(["--anyway"] if anyway else [])])
    except (Refused, ActionError) as refused:
        said = str(refused)
        if shipcheck.HELD in said:
            # held, not refused (c-600 review): the page asks him "Ship anyway?" with this line
            return {"card": board.get(card["id"]), "held": said[said.index(shipcheck.HELD):],
                    "note": said[said.index(shipcheck.HELD):]}
        raise ActionError(said) from None
    said = next((e.get("text") for e in reversed(board.events(card["id"], last=20)) if e["kind"] == "ship"), None)
    return {"card": result, "note": said or "shipped"}


def act_hand_over(cfg: Config, board: Board, body: dict) -> dict:
    """`ship.handover` {id, rebase?}: his tap that hands a shipping card's waiting review to
    its house (c-655), which is `kb ship <id> reoffer [--rebase]` run as him, so the verb's
    own refusals hold and are said in plain words (`shipauto.plain`)."""
    card = card_of(board, body)
    rebase = body.get("rebase") is True
    try:
        result = run_kb(cfg, ["ship", card["id"], "reoffer", *(["--rebase"] if rebase else [])])
    except (Refused, ActionError) as refused:
        raise ActionError(shipauto.plain(str(refused))) from None
    return {"card": result, "note": shipauto.HANDED_BASE if rebase else shipauto.HANDED}


def act_send_back(cfg: Config, board: Board, body: dict) -> dict:
    """`ship.sendback` {id, words}: his own notes on a shipping card (c-663), which is
    `kb ship <id> sendback` run as him with his words on stdin, so the verb's own refusals
    hold. The card stays at shipping, and the drain tells its house on its next pass."""
    card = card_of(board, body)
    words = str(body.get("words") or "")
    if not words.strip():
        raise ActionError("a send back needs your words: what you want changed")
    try:
        result = run_kb(cfg, ["ship", card["id"], "sendback", "--words-file", "-"], stdin=words)
    except (Refused, ActionError) as refused:
        raise ActionError(shipauto.plain(str(refused))) from None
    return {"card": result, "note": shipsendback.SENT}


# The Setup view's verbs and the first-run stepper's (c-632), one table.
SETUP_TABLE = {**onboarding.VERBS, **firstrun.VERBS, **landpush.VERBS, **stuckcards.VERBS}


def act_setup(cfg: Config, board: Board, body: dict) -> dict:
    """The Setup view's verbs (`keel/onboarding.py`): clone a repo, attach or remove one, add
    a space, turn a pack on, save a tier, propose and adopt a repo tier; and the first-run
    stepper's (`keel/firstrun.py`): skip, finish, check the login; and the push of a card that
    landed by a local merge (`keel/landpush.py`, c-678), and the fixes of the stuck states
    (`keel/stuckcards.py`, c-678). The deck re-execs after
    one that changed the config (`keel/serve.py`)."""
    try:
        return SETUP_TABLE[str(body.get("verb"))](cfg, body, board)
    except (onboarding.SetupError, Refused) as error:
        raise ActionError(str(error), getattr(error, "detail", None)) from None


# His taps on the Setup view and the stepper: the page's alone, like the house verbs.
SETUP_VERBS = {verb: act_setup for verb in SETUP_TABLE}
GATE_VERBS = {"approve": act_approve, "sendback": act_sendback, "end_discussion": act_end_discussion,
              "plan.send": act_plan_send, "plan.ask": act_plan_ask, "ship": act_ship,
              "ship.handover": act_hand_over, "ship.sendback": act_send_back}
# The blackboard's verbs, all through one handler: they share their gating and their store.
BOARD_VERBS = {name: act_board for name in
               ("board.push", "board.list", "board.find", "board.show",
                "board.open", "board.new", "board.close", "board.delete", "board.restore")}
CALLER_GONE = ("a body with a caller was a kb reaching this deck over HTTP, which Keel no "
               "longer does: it runs on one machine now (c-622); run kb here")


def refuse_caller(body: dict) -> None:
    """A `caller` was what a `kb` in HTTP mode sent from another machine. Nothing sends one
    now, and a body that does is refused rather than run as somebody it only says it is."""
    if body.get("caller") is not None:
        raise ActionError(CALLER_GONE)


def human_path(body: dict) -> bool:
    """Does this body act as him: every body does, so the deck asks each for its page's
    proof (`keel/deckauth.py`)."""
    return True


def voice_answer(body: dict) -> bool:
    """The voice page recording his answer to one of Bosun's asks (c-523, BO-5): `voice:
    true` on the page's own `console answer`. The page has already proved it is him (the
    human path's cookie and origin, `keel/deckauth.py`), so the deck runs `kb` with its own
    token and `--actor voice`, and the ask records the channel voice. The gateway never
    holds the token; only the page, which is him, sends this. Anything else carrying the
    flag is refused, so it can never make another verb a voice one."""
    if not body.get("voice"):
        return False
    if (body.get("caller") is not None or str(body.get("verb") or "") != "console"
            or body.get("sub") != "answer"):
        raise ActionError("only the voice page's answer to an ask is recorded as voice")
    return True


def act(cfg: Config, board: Board, body: dict):
    """Carry out one action; the decoded result, or ActionError with the reason."""
    verb = str(body.get("verb") or "")
    refuse_caller(body)
    voice = voice_answer(body)      # refused on every body but the page's own answer
    if verb in GATE_VERBS:
        return GATE_VERBS[verb](cfg, board, body)
    if verb in SETUP_VERBS:
        return SETUP_VERBS[verb](cfg, board, body)
    if verb in KB_VERBS:
        result = run_kb(cfg, kb_argv(body), stdin=hook_stdin(body), voice=voice)
        if verb == "create" and body.get("start") and isinstance(result, dict):
            run_kb(cfg, ["stage", result["id"], "assigned"])
            if cfg.drain_paused:
                run_keel(cfg, ["drain", "--once", "--card", result["id"]], timeout=CARD_PASS_SECONDS)
            result = run_kb(cfg, ["show", result["id"], "--events", "0"])
        return result
    if verb in HOUSE_VERBS:
        return HOUSE_VERBS[verb](cfg, board, body)
    if verb in BOARD_VERBS:
        return BOARD_VERBS[verb](cfg, board, body)
    raise ActionError(f"no verb called {verb!r}" if verb else "an action needs a verb")
