"""The ask box: a question typed under the stage, answered by the board's own house.

K11 of [the blackboard](<install>/history/docs/blackboard.md). Stage one was one way: a house drew and he
read. This is the way back that does not need a microphone, and it is the reason the board
stops being a page he is shown and becomes a place he can work: he taps a node, asks what
it means, and the house that drew it answers underneath, while whatever it draws while
answering arrives live on the board above.

ONE TURN AT A TIME, PER BOARD, and the answer is polled rather than waited for. A turn into
a house is a whole `claude` process and takes tens of seconds, which is longer than any
browser or proxy should be asked to hold a request open, so `POST /api/board/<id>/ask`
answers with a TURN ID in about a millisecond and the page asks
`GET /api/board/<id>/ask/<turn>` until it is done. The turn runs on a thread this process
owns, exactly as the kept-alive conversations do (`keel/housetier.py`), and a second Send
against a board with a turn in flight is refused rather than queued: one board, one
question, the same rule the voice conversation keeps.

THE CARD'S PATH IS THE PHONE HARBOR'S PATH, TAKEN THROUGH THE ACTION TABLE. It is
`house.converse`, unpinned, which is one-shot `keel converse <card> "<text>"`
(`keel/converse.py`): the card's own guards, the hold taken and given straight back, the
exchange recorded on the card. Through `actions.act` rather than around it, so the deck's
caller rules, its refusals and its one-line errors are the ones that apply. A REFUSAL IS AN
ANSWER HERE: "c-301 has no house session yet. Do you want me to start it?" is a sentence
written to be spoken, and it is the right thing to show under the ask box too.

THE TALKER'S PATH IS HARBOR'S OWN TURN, WAITED FOR (c-422, 2026-09-23). A talker board
belongs to Harbor, a long-lived conversation the voice gateway owns and `keel/` never
imports (its runtime is a different interpreter: `keel/voice.py`). So the text goes to the
gateway's own `bin/keel-voice ask --wait --json`, run on this turn's own thread, which holds
Harbor's conversation lock across processes and returns with Harbor's answer. It used to
run the bare `ask`, which started the turn on a daemon thread and exited, killing the turn
mid `claude -p`, and this reply then said "It answers out loud", which was false. The
answer is shown under the box like a house's (B16), and what it drew is already on the
board. No route was added to the gateway, which has no POST by design.
"""

import json
import os
import secrets
import signal
import subprocess
import sys
import threading
import time

from keel import childenv
from keel.config import Config

# How long a finished turn is kept for the page to come and collect, and how many turns are
# kept at all. The page polls every second and a half, so a minute is generous; the bound on
# the number is what stops a long session's turns accumulating in this process for a page
# that closed.
KEEP_SECONDS = 600
KEEP_TURNS = 40
# The poll's own cadence is the page's (`app/ui.board.js`); this is only what the server
# will wait for the two halves it runs itself.
CARD_TIMEOUT = 300
# ABOVE THE TYPED ASK'S WORST CASE (review F3): `harbormsg.TYPED_WORST`, which is the turn
# (120 s under one deadline), the pushes (20 s under one budget) and 15 s of start, 155 s.
# A test holds this above it; `keel/` does not import the gateway to compute it.
TALKER_TIMEOUT = 180
VENV = ".venv-voice/bin/python"
GATEWAY_VERB = "ask"
GATEWAY_FLAGS = ("--wait", "--json")
CONTEXT = "asked from the deck board {board}"

BUSY = "that board is already asking something; wait for the answer before sending another"
NOTHING = "type a question first"
NO_GATEWAY = "Harbor could not be reached from here: {why}"
HARBOR_BUSY = "Harbor is answering something else right now; ask again in a moment."
NO_ANSWER = "Harbor did not answer that one."

_turns: dict[str, dict] = {}
_lock = threading.Lock()


class AskError(Exception):
    """The ask was refused before a turn started; the message is the one line the page shows."""


# ----- the turn store -----

def new_id() -> str:
    return secrets.token_hex(6)


def in_flight(board_id: str) -> str | None:
    """The turn id running for this board, or None. THE LOCK IS THE CALLER'S: this is the
    half `start` asks inside its own hold, and taking the lock again here would reopen the
    very window the hold exists to close."""
    for turn, row in _turns.items():
        if row["board"] == board_id and row["state"] == "running":
            return turn
    return None


def running_on(board_id: str) -> str | None:
    """The same question from outside, under the lock, because the thread that finishes a
    turn writes the same dictionary."""
    with _lock:
        return in_flight(board_id)


def prune() -> None:
    """Forget answers nobody came back for. Oldest first, and never one still running."""
    cutoff = time.time() - KEEP_SECONDS
    stale = [turn for turn, row in _turns.items()
             if row["state"] != "running" and row["at"] < cutoff]
    for turn in stale:
        _turns.pop(turn, None)
    if len(_turns) <= KEEP_TURNS:
        return
    ordered = sorted(_turns.items(), key=lambda pair: pair[1]["at"])
    for turn, row in ordered[:len(_turns) - KEEP_TURNS]:
        if row["state"] != "running":
            _turns.pop(turn, None)


def settle(turn: str, answered: bool, say: str) -> None:
    """The turn is over, one way or the other.

    `answered` is the TURN's own verdict and never the request's: a refusal ("that house
    has no session yet") is a perfectly good answer to show him, and the route's own `ok`
    says only that the poll was understood. Two words for two questions, because one `ok`
    carrying both is how a refusal reads as a broken page.
    """
    with _lock:
        row = _turns.get(turn)
        if row is None:
            return
        row.update(state="done", answered=answered, say=say,
                   seconds=round(time.time() - row["at"], 1))


def result(turn: str) -> dict | None:
    """What the page's poll is handed: the turn as it stands, or None for an id nobody minted."""
    with _lock:
        row = _turns.get(turn)
        if row is None:
            return None
        return {"turn": turn, "board": row["board"], "state": row["state"],
                "answered": row["answered"], "say": row["say"], "seconds": row.get("seconds")}


# ----- starting one -----

def start(cfg: Config, record: dict, text: str) -> dict:
    """Begin a turn for this board; the id the page polls on.

    Refuses an empty question and a board that already has one running, and never waits for
    the answer: that is the poll's job.

    THE CHECK AND THE INSERT ARE ONE HOLD OF THE LOCK. Asking whether a turn is running and
    then recording one under a second hold is a check that was true when it was asked and a
    write that lands anyway: two Sends arriving together both passed, and two `claude`
    processes went at one session, which is precisely what this guard is for. The id is
    minted inside the hold for the same reason, since it is the work that sat in the gap.
    """
    said = " ".join(str(text or "").split())
    if not said:
        raise AskError(NOTHING)
    board_id = record["id"]
    source = record.get("source") or {}
    with _lock:
        if in_flight(board_id):
            raise AskError(BUSY)
        prune()
        turn = new_id()
        _turns[turn] = {"board": board_id, "state": "running", "answered": None, "say": "",
                        "at": time.time(), "said": said}
    worker = threading.Thread(target=run, args=(cfg, source, said, turn, board_id),
                              name=f"board-ask-{turn}", daemon=True)
    worker.start()
    return {"turn": turn, "board": board_id, "state": "running", "said": said}


def run(cfg: Config, source: dict, said: str, turn: str, board_id: str = "") -> None:
    """The thread body: one question, answered or refused, always settled.

    Every path ends in `settle`, including the ones nobody thought of, because a turn left
    running is a Send button that spins forever on a page that cannot know why.
    """
    try:
        if source.get("kind") == "card" and source.get("card"):
            answered, say = ask_card(cfg, str(source["card"]), said)
        else:
            answered, say = ask_talker(cfg, said, board_id=board_id)
    except Exception as error:  # noqa: BLE001 - whatever it was, the page is told
        answered, say = False, f"that question did not come back: {error}"
    settle(turn, answered, say or "")


def ask_card(cfg: Config, card_id: str, said: str) -> tuple[bool, str]:
    """One unpinned turn into the card's own house, through the deck's own action table.

    The refusal sentences (`keel/converse.py`) come back as the answer rather than as an
    error, because they are written to be said to him and they are what he needs to read:
    the house is building, the house is on the other machine, there is no session yet.
    """
    from keel import actions                    # noqa: PLC0415 - see this module's docstring
    from keel.board import open_board
    board = open_board(cfg)
    try:
        answer = actions.act(cfg, board, {"verb": "house.converse", "id": card_id, "text": said,
                                          "timeout": CARD_TIMEOUT})
    except actions.ActionError as refusal:
        return False, str(refusal)
    finally:
        board.close()
    return True, str((answer or {}).get("say") or "")


def ask_talker(cfg: Config, said: str, board_id: str = "") -> tuple[bool, str]:
    """Ask Harbor, wait for its answer, and hand the answer back.

    `bin/keel-voice ask --wait --json` is the gateway's own verb run in the foreground: the
    fast tier when it can answer, otherwise one turn in the voice conversation under the
    conversation lock. The venv's interpreter is used where there is one, because the
    speech stack pins Python below this one's.
    """
    python = cfg.root / VENV
    argv = [str(python) if python.exists() else sys.executable,
            str(cfg.root / "bin" / "keel-voice"), GATEWAY_VERB, *GATEWAY_FLAGS]
    if board_id:
        argv += ["--context", CONTEXT.format(board=board_id)]
    argv.append(said)
    try:
        code, out, err = run_ask(argv, TALKER_TIMEOUT)
    except (OSError, subprocess.SubprocessError) as error:
        return False, NO_GATEWAY.format(why=error)
    reply = parsed(out)
    if reply is None:
        why = (err.strip() or out.strip() or f"it exited {code}").splitlines()[-1]
        return False, NO_GATEWAY.format(why=why)
    if reply.get("busy"):
        return False, HARBOR_BUSY
    # THE WHOLE TEXT (review F6): what he reads under the box is not capped like speech.
    answer = str(reply.get("written") or reply.get("answer") or "").strip()
    if not reply.get("ok"):
        return False, answer or NO_ANSWER
    return True, answer or NO_ANSWER


def run_ask(argv: list[str], timeout: float) -> tuple[int, str, str]:
    """Run the ask in its OWN process group and kill the whole group on timeout (review F3).

    `subprocess.run` kills only the child it started, so a timed-out ask left its
    `claude -p` running after the conversation lock had dropped with its parent, and the
    next turn raced it on the same transcript.
    """
    child = subprocess.Popen(argv, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
                             start_new_session=True,
                             env=childenv.own_env())    # a turn into a house, never his token (c-451)
    try:
        out, err = child.communicate(timeout=timeout)
    except subprocess.TimeoutExpired:
        try:
            os.killpg(child.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
        child.communicate()
        return -9, "", f"the ask took longer than {timeout:.0f}s and was ended"
    return child.returncode, out or "", err or ""


def parsed(output: str) -> dict | None:
    """The one JSON object `keel-voice ask --json` prints last, or None."""
    for line in reversed((output or "").splitlines()):
        line = line.strip()
        if line.startswith("{"):
            try:
                value = json.loads(line)
            except ValueError:
                return None
            return value if isinstance(value, dict) else None
    return None
