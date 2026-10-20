"""Harbor draws: a ```board block in its own answer, lifted out of it and pushed.

WHAT THIS FIXES, in one sentence. Asked out loud to draw something on the board, Harbor
grepped the Atlas, read "a house pushes... something a house showed him", answered "a house
draws on it, not me, I'll card it", and filed c-421. It had the verb, it had the memory
saying it had the verb, and the shape of a voice turn meant it never ran one: a fenced block
in its answer was read as a code block and thrown away. His words: "the talker needs to call
verbs the same as the house does, by deterministic reading of the answer".

SO THE READING IS THE HOUSE'S READING, LITERALLY. `keel/boardpen.py` is what lifts a block
out of a house's spoken answer, and this imports that same file and hands it a source of
`talker`. There is no second parser, no second dedupe rule and no second sentence: a block
Harbor writes is read exactly as a block a house writes, which is what keeps the two from
drifting the next time either one changes.

THE IMPORT CROSSES THE INTERPRETER BOUNDARY, and it is one file deep, exactly as
`harbor_voice/index.py`'s is. `keel/boardpen.py` imports `keel/sentences.py` and nothing
else; `keel/sentences.py` imports `hashlib` and `re`. Neither holds the store, the config,
the artifact tokens or a line of 3.14 syntax, so this 3.12 process can read them safely.
The dependency still runs ONE WAY: `keel/` never imports this package.

THE PUSH IS THE VERB, NOT THE STORE. `keel board push --talker --file <ops>` is the command
the talker's own typed session runs, and it is run here rather than called because only the
verb knows WHICH board this checkout writes to: `keel.toml` decides scratch or live. A
gateway that imported the
store would write to the local one and be confidently wrong, which is the exact failure
`config.KB` exists to refuse. `--file` rather than stdin, for the reason a confined house
uses `--file`: one plain command, no pipe.

THE PUSH RUNS IN THE TALKER'S OWN FOLDER (C2, 2026-09-23). Harbor's turns run with
`cwd=config.TALKER_CWD`, so a relative `path` op it writes names a file there; the push ran
with the gateway's own working directory (the checkout), so `board-b-002-lines.txt` was
"not a file on this machine" and the whole push was refused (voice.log, 2026-09-21). It
runs from `TALKER_CWD` now, and the store reads a talker's files only under that folder.

WHAT DID NOT LAND IS RECORDED AND CARRIED (C1). A push that was refused, whole or in part,
leaves a `draw-failed` record in the transcript with its turn, and its report waits in
`REPORT_FILE` until the next Harbor turn is built, which reads it once
(`carried_report`), so the model is told and can draw it again correctly.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import threading
import time
from datetime import datetime
from pathlib import Path

from harbor_voice import config

# IT IS THE CHECKOUT THIS FILE IS IN, not `config.KEEL_HOME`: the code that reads a block
# has to be the code this gateway is running, or a worktree's selftest would exercise the
# main checkout's copy and pass on something it is not running. `config.KEEL_HOME` decides
# which BOARD the verb below writes to, which is a different question.
CHECKOUT = Path(__file__).resolve().parents[2]
if str(CHECKOUT) not in sys.path:
    sys.path.append(str(CHECKOUT))

from keel import boardpen, deckdigest, sentences                        # noqa: E402

# A push is a few file writes and a JSON dump. Ten seconds is already ten times what it
# takes, and a turn must not be held open behind one.
PUSH_TIMEOUT = 10.0
# AND ALL OF ONE ANSWER'S PUSHES TOGETHER (review F3): a turn's worst case is what the deck's
# wait is sized against, so the pushes after it share one budget rather than 10 s each.
PUSH_BUDGET = 20.0
# WHERE A TROUBLED DRAWING IS WRITTEN DOWN (C1): the gateway's transcript, which is where
# every other turn record already lives, and one small file the next turn reads and removes.
TRANSCRIPT = config.DATA / "transcript.jsonl"
REPORT_FILE = config.DATA / "board-report.txt"
# THE BOARDS EACH TURN DREW (VP-5), by turn id, until the worker that ran the turn writes
# its answer into the say inbox and takes them with it (`drawn_for`). In memory and
# bounded: it is a hand-off between two calls on one thread, never a record, and a turn
# whose answer is never written leaves at most this many entries behind.
DRAWN: dict[str, list[str]] = {}
DRAWN_KEEP = 32
_DRAWN_LOCK = threading.Lock()


def note_drawn(turn: str, boards: list[str]) -> None:
    """Remember the boards `turn` drew, oldest entries dropped past `DRAWN_KEEP`."""
    if not turn or not boards:
        return
    with _DRAWN_LOCK:
        DRAWN[turn] = list(boards)
        while len(DRAWN) > DRAWN_KEEP:
            DRAWN.pop(next(iter(DRAWN)))


def drawn_for(turn: str) -> list[str]:
    """The boards `turn` drew, taken once: [] when it drew none."""
    with _DRAWN_LOCK:
        return DRAWN.pop(turn, []) if turn else []


# A HOUSE'S DRAWING, READ BACK OFF THE DECK (VP-8). A house draws with `keel board push
# --card` from its own shell, straight into the deck's board store, so the gateway never
# holds the ids the way `note_drawn` holds Harbor's. At the end of a connected turn it asks
# the deck's board list instead, and this is how long the turn will wait for that answer:
# the list is a loopback read of a few dozen small files, so two seconds is a deck that is
# not answering, and the turn ends without a receipt rather than behind it.
HOUSE_LIST_TIMEOUT = 2.0


def card_boards_since(rows: list, card: str, since: float) -> list[str]:
    """The ids of `card`'s open boards updated at or after `since` (epoch seconds), oldest
    first, which is the order they were drawn in. A row whose stamp cannot be read is left
    out: a receipt the list cannot vouch for is not a receipt."""
    if not card:
        return []
    found = []
    for row in rows or []:
        source = row.get("source") or {}
        if source.get("card") != card or row.get("closed"):
            continue
        try:
            at = datetime.fromisoformat(str(row.get("updated") or "")).timestamp()
        except ValueError:
            continue
        if at >= since:
            found.append((at, str(row.get("id") or "")))
    return [board for _at, board in sorted(found) if board]


def house_drew(card: str, since: float, timeout: float = HOUSE_LIST_TIMEOUT,
               fetch=None) -> list[str]:
    """The boards `card`'s house drew since `since`, read off the deck's board list.

    Raises when the deck fails or takes longer than `timeout`. THE WAIT IS A JOIN, NOT ONLY
    THE SOCKET'S TIMEOUT: `urlopen`'s timeout is per socket operation, so a deck that
    trickles its answer could outlast it many times over; the read runs on its own daemon
    thread and the turn stops waiting at `timeout` whatever that thread is doing.
    """
    fetch = fetch or (lambda: deckdigest.fetch_boards(config.SERVE_PORT, timeout=timeout))
    out: dict = {}

    def read():
        try:
            out["rows"] = fetch()
        except Exception as exc:                                        # noqa: BLE001
            out["error"] = exc

    worker = threading.Thread(target=read, name="voice-house-boards", daemon=True)
    worker.start()
    worker.join(timeout)
    if "error" in out:
        raise out["error"]
    if "rows" not in out:
        raise TimeoutError(f"the deck's board list took longer than {timeout:g}s")
    return card_boards_since(out["rows"], card, since)


def push_ops(body: str, timeout: float = PUSH_TIMEOUT) -> dict:
    """One `keel board push --talker`, as JSON. Raises with the verb's own words."""
    handle = tempfile.NamedTemporaryFile("w", suffix=".board", delete=False,
                                         encoding="utf-8")
    try:
        handle.write(body)
        handle.close()
        done = subprocess.run(
            [str(config.KEEL_BIN), "board", "push", "--talker", "--file", handle.name,
             "--json"],
            capture_output=True, text=True, timeout=timeout,
            # THE TALKER'S OWN FOLDER (C2): a relative path Harbor wrote is relative to
            # where its turn ran, and that is `TALKER_CWD`, not the gateway's checkout.
            cwd=str(config.TALKER_CWD),
            # KEEL_HOME EXPLICITLY, the way `snapshot._kb` passes it: the gateway runs
            # under launchd with almost nothing in its environment, and a push that landed
            # on a different checkout's board than the one it reads is the confident wrong
            # answer this package exists to refuse. `KEEL_TALKER` is what makes the store
            # record the actor as the talker rather than as a terminal.
            env={**os.environ, "KEEL_HOME": str(config.KEEL_HOME), "KEEL_TALKER": "1"})
    finally:
        try:
            os.unlink(handle.name)
        except OSError:
            pass
    if done.returncode != 0:
        said = (done.stderr or done.stdout or "").strip().splitlines()
        raise RuntimeError(said[-1] if said else f"keel board push exited {done.returncode}")
    try:
        return json.loads(done.stdout)
    except ValueError as exc:
        raise RuntimeError(f"keel board push answered something that is not JSON: {exc}") from exc


def lift(raw: str, push=None, log=None, turn: str = "") -> tuple[str, int]:
    """(what he hears, how many blocks were drawn). See `read_answer`."""
    read = read_answer(raw, push=push, log=log, turn=turn)
    return read["said"], read["drew"]


def budgeted():
    """`push_ops` under one budget for all of an answer's pushes (review F3)."""
    deadline = time.monotonic() + PUSH_BUDGET

    def push(body: str) -> dict:
        left = deadline - time.monotonic()
        if left <= 0:
            raise RuntimeError("the board took too long to answer")
        return push_ops(body, timeout=min(PUSH_TIMEOUT, left))
    return push


def read_answer(raw: str, push=None, log=None, turn: str = "", pen=None) -> dict:
    """{said, written, drew}: what he hears, what the record keeps, and the blocks drawn.

    NOTHING CHANGES FOR AN ANSWER WITH NO BLOCK IN IT, byte for byte: it is collapsed to one
    line and handed back, which is what this call site has always done. The pen is only
    reached when there is something to draw, so an ordinary turn does not quietly acquire
    the pen's markdown stripping along the way.

    WHAT WAS WRITTEN IS KEPT (review F6). A drawing turn speaks its lead and the report
    line (N7); the rest of the answer goes into the transcript as an `answer-written`
    record with its turn, and back to a typed ask whole, because that is read, not heard.

    `pen` IS A STREAMED TURN'S OWN (R2, `harborlive.py`): it drew each block as the stream
    closed it, so the final reading reuses it and pushes nothing twice.
    """
    text = str(raw or "")
    _, bodies = sentences.board_blocks(text)
    if not bodies:
        said = " ".join(text.split())
        return {"said": said, "written": said, "drew": 0}
    pen = pen or boardpen.BoardPen(None, boardpen.talker_source(), push=push or budgeted(),
                                   note=log)
    said = pen.take(text)
    note_drawn(turn, [report["board"] for report in pen.reports
                      if report["board"] and report["state"] != boardpen.REFUSED])
    if pen.troubled():
        record_failure(pen, turn)
    if pen.written != said:
        transcript({"turn": turn, "kind": "answer-written", "tier": "harbor",
                    "answer": said, "written": pen.written})
    return {"said": said, "written": pen.written, "drew": pen.count}


def transcript(record: dict) -> None:
    """One line into the gateway's transcript. Best effort: a log never costs the answer."""
    try:
        TRANSCRIPT.parent.mkdir(parents=True, exist_ok=True)
        with TRANSCRIPT.open("a") as handle:
            handle.write(json.dumps({"at": time.time(), **record}) + "\n")
    except OSError:
        pass


def record_failure(pen, turn: str = "") -> None:
    """The transcript record and the waiting report for a drawing that did not land.

    Best effort, like every other side effect of a turn: a record that cannot be written
    never costs the answer.
    """
    transcript({"turn": turn, "kind": "draw-failed", "tier": "harbor", "board": pen.summary()})
    try:
        REPORT_FILE.write_text(pen.repair_note() + "\n")
    except OSError:
        pass


def carried_report() -> str:
    """The last drawing's report, once: read and removed, "" when there is none."""
    try:
        text = REPORT_FILE.read_text().strip()
        REPORT_FILE.unlink()
    except OSError:
        return ""
    return text
