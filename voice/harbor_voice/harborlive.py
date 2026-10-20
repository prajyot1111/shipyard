"""Harbor's own voice turns on ONE kept-alive, streamed `claude` (R2, behind a flag).

WHAT THIS IS FOR. A house's connected turn already runs down one kept-alive process and is
spoken sentence by sentence as it is written (V12): about 1.0 to 1.5 s to the first word.
Harbor's own turns were still one cold `claude -p --resume` per utterance with nothing
spoken until the whole JSON was back: 3.6 to 4.1 s to the first word for a one-sentence
answer, and every sentence of a long one held to the end (`<install>/history/docs/voice-next.md`). This gives
Harbor's voice conversation the house's shape.

IT SHIPS OFF (`[voice] harbor_kept_alive`, `config.HARBOR_KEPT_ALIVE`). With the flag off
nothing imports a line of this into a turn: `harbormsg.send` runs `run_turn` exactly as
before.

THE SAME CONVERSATION, THE SAME RULES. The process is `--resume` (or `--session-id` the
first time) of the uuid in `state/voice-session.json`, under the talker's config dir and
working directory, on `config.CONVERSE_MODEL`. Rotation is V10's, unchanged: `open_session`
still decides the uuid each turn, and a uuid that is not this process's closes it and opens
the new one. The turn lock is Lane C's (`harbormsg.conversation_turn`), taken by the caller
around the whole turn, so a typed ask in another process and a spoken turn here still never
overlap.

ANOTHER PROCESS MAY HAVE SPOKEN IN THE MEANTIME. A typed ask runs its own `-p --resume` on
this same session, and a process that has been holding the conversation in memory would not
see that turn and would fork the history. So the process remembers the session record's
turn count after its own last turn; a count that moved since (someone else answered) closes
it, and the next turn resumes from the transcript that includes the other turn.

THE FALLBACK IS V12-3's. A process that will not open, or dies before any part of the
answer was left to be spoken, is closed and the turn is run one-shot, silently: latency,
never a lost answer. A process that died AFTER a part was left is NOT asked again (he
would hear the start of one answer and the whole of another); the turn ends with
`BROKE_OFF` instead. An overrun raises `subprocess.TimeoutExpired`, as the one-shot does.

HOW A PART REACHES SPEECH is V12-5's: down the progress inbox, marked `part: true`
(`keel/narration.leave_part`), stamped with the turn id, which the dispatcher's watch loop
already claims. A ```board block is drawn as it closes through the house's own pen
(`keel/boardpen.py`, the talker's source), and after a block that REPORTED nothing more is
spoken (N7, C-18); the final `said` and `written` come from the same pen
(`drawing.read_answer(pen=...)`), so the typed and spoken paths keep Lane C's handling.

A LINE BEFORE A TOOL IS A PREAMBLE (lane H, H1, 2026-09-24). The framing asks Harbor to say
one short line ("Let me check the board.") before it reaches for a tool, so he is not left
in silence. That line is spoken as a part like any other, but the `result` record carries
only the LAST message, so compared with it the preamble made a covered answer look
uncovered and he heard the answer twice. So a tool call ends the message it closes: the
cutter is flushed (the preamble's full stop has no whitespace after it until the next
message, and the two would run together), what was left so far becomes the preamble, and
the answer the turn hands back starts with it, which is what he heard.

AND THE TURN KEEPS ITS OWN CLOCK (H2): when the sentence went down (and whether the process
was already warm), when the `result` came back and what its envelope says it did. The
caller writes them as `harbor-*` stamps (`harbor_voice/stamps.py`).
"""
from __future__ import annotations

import atexit
import json
import os
import queue
import signal
import subprocess
import threading
import time

from . import config, drawing, stamps
from . import judges as judgesmod
from .drawing import boardpen, sentences

from keel import narration                                              # noqa: E402
from keel.childenv import own_env                                      # noqa: E402

# What he hears when the process died after part of the answer was already spoken.
BROKE_OFF = "Harbor's answer broke off there, so ask me again for the rest."
# The flags `keel/harness.py` gives a kept-alive house conversation (CONVERSE_FORMAT).
STREAM_FORMAT = ("--input-format", "stream-json", "--output-format", "stream-json",
                 "--verbose", "--include-partial-messages")
QUEUE_TICK = 0.2
CLOSE_GRACE = 5.0
# The connect directive is never spoken; a part that carries it is cut before it.
DIRECTIVE = "<<keel-"


class LiveError(Exception):
    """The kept-alive turn failed. `spoke` says whether any part was already left."""

    def __init__(self, why: str, spoke: bool = False):
        super().__init__(why)
        self.spoke = spoke


def user_line(text: str) -> str:
    """One sentence in the shape `--input-format stream-json` reads (`harness.user_line`)."""
    return json.dumps({"type": "user", "message": {
        "role": "user", "content": [{"type": "text", "text": str(text)}]}}) + "\n"


def stream_text(record: dict) -> str:
    """The words a `stream_event` adds to the answer; only `text_delta` (`harness`)."""
    if not isinstance(record, dict) or record.get("type") != "stream_event":
        return ""
    event = record.get("event") or {}
    if event.get("type") != "content_block_delta":
        return ""
    delta = event.get("delta") or {}
    return str(delta.get("text") or "") if delta.get("type") == "text_delta" else ""


def spoken_part(text: str) -> str:
    """A part as it may be spoken: everything before a directive, which never is."""
    return text.split(DIRECTIVE, 1)[0].strip()


class Process:
    """One `claude` taking Harbor's sentences down its stdin. The caller holds the lock."""

    def __init__(self, session: str, existed: bool, turns: int):
        self.session = session
        self.turns_seen = turns
        self.last_used = time.monotonic()
        flag = "--resume" if existed else "--session-id"
        argv = ["claude", "-p", flag, session, *STREAM_FORMAT, "--permission-mode", "auto",
                "--model", config.CONVERSE_MODEL]
        # Never his token (c-451): `own_env` drops what no child may inherit.
        env = {**own_env(), "CLAUDE_CONFIG_DIR": str(config.TALKER_CONFIG_DIR),
               "KEEL_HOME": str(config.KEEL_HOME), "HARBOR_DISPATCH_ID": ""}
        # A PROCESS THAT HAS NOT YET ANSWERED IS COLD: its first turn pays the start.
        self.fresh = True
        self.proc = subprocess.Popen(argv, cwd=str(config.TALKER_CWD), env=env,
                                     stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                     stderr=subprocess.PIPE, text=True, errors="replace",
                                     bufsize=1, start_new_session=True)
        self.records: queue.Queue = queue.Queue()
        self.errors: list[str] = []
        self.dead = False
        for target in (self._read_out, self._read_err):
            threading.Thread(target=target, name="harbor-live", daemon=True).start()

    def _read_out(self) -> None:
        try:
            for line in self.proc.stdout:
                try:
                    record = json.loads(line)
                except ValueError:
                    continue
                if isinstance(record, dict):
                    self.records.put(record)
        except (ValueError, OSError):
            pass
        finally:
            self.records.put(None)

    def _read_err(self) -> None:
        try:
            for line in self.proc.stderr:
                self.errors.append(line)
                del self.errors[:-40]
        except (ValueError, OSError):
            pass

    @property
    def alive(self) -> bool:
        return not self.dead and self.proc.poll() is None

    def why(self, what: str) -> str:
        said = "".join(self.errors).strip().splitlines()
        return f"{what}: {said[-1]}" if said else what

    def say(self, text: str, deadline: float, on_record) -> dict:
        """One sentence in; its `result` record out. Every other record goes to
        `on_record` first. Raises LiveError, or TimeoutExpired past `deadline`."""
        try:
            self.proc.stdin.write(user_line(text))
            self.proc.stdin.flush()
        except (BrokenPipeError, ValueError, OSError) as error:
            self.kill()
            raise LiveError(self.why(f"the process would not take the sentence: {error}"))
        self.last_used = time.monotonic()
        while True:
            left = deadline - time.monotonic()
            if left <= 0:
                self.kill()
                raise subprocess.TimeoutExpired("claude (kept alive)", 0)
            try:
                record = self.records.get(timeout=min(QUEUE_TICK, left))
            except queue.Empty:
                continue
            if record is None:
                self.kill()
                raise LiveError(self.why("the process ended mid-turn"))
            if record.get("type") == "result":
                self.last_used = time.monotonic()
                if record.get("is_error"):
                    raise LiveError(str(record.get("result") or "the turn errored"))
                return record
            on_record(record)

    def kill(self) -> None:
        self.dead = True
        try:
            os.killpg(os.getpgid(self.proc.pid), signal.SIGKILL)
        except (ProcessLookupError, PermissionError, OSError):
            pass

    def close(self) -> None:
        """Close stdin (the ordinary end), then kill the group if it lingers."""
        self.dead = True
        try:
            self.proc.stdin.close()
        except (ValueError, OSError):
            pass
        try:
            self.proc.wait(timeout=CLOSE_GRACE)
        except subprocess.TimeoutExpired:
            self.kill()


class Stream:
    """One turn's streamed answer: deltas cut into parts, parts left for speech, board
    blocks drawn as they close. `spoke` is True once any part has been left."""

    def __init__(self, turn: str, progress, log):
        self.turn = turn
        self.progress = str(progress or "")
        self.cutter = sentences.Cutter()
        self.pen = boardpen.BoardPen(None, boardpen.talker_source(),
                                     push=drawing.budgeted(), note=log)
        self.spoke = False
        # WHAT HAS BEEN LEFT FOR SPEECH in the message being written, and what was left in
        # the messages before a tool call (H1). The answer handed back starts with the
        # preamble, because it was heard.
        self.left: list[str] = []
        self.preamble: list[str] = []
        # THE DECK READS THIS TURN MADE, as section names only (c-552): the truth the
        # `preturn.prefetch` answer is scored against, written as a `reads` outcome.
        self.reads: list[str] = []

    def on_record(self, record: dict) -> None:
        delta = stream_text(record)
        if delta:
            self.events(self.cutter.feed(delta))
        calls = narration.tool_calls(record)
        for tool, given in calls:
            section = judgesmod.read_section(tool, given)
            if section:
                self.reads.append(section)
        if calls:
            self.events(self.cutter.flush())
            self.cutter = sentences.Cutter()
            self.preamble += self.left
            self.left = []

    def finish(self) -> None:
        self.events(self.cutter.flush())

    def events(self, events: list[dict]) -> None:
        for event in events:
            if event.get("type") == "part" and not self.pen.silenced:
                self.leave(spoken_part(str(event.get("text") or "")))
            elif (event.get("type") == sentences.FENCE
                  and str(event.get("lang") or "").strip().lower() == sentences.BOARD_LANG):
                self.leave(self.pen.on_fence(str(event.get("body") or "")))

    def leave(self, text: str) -> None:
        if text and narration.leave_part(self.progress, text, turn=self.turn) is not None:
            self.spoke = True
            self.left.append(text)

    def heard_first(self, said: str) -> str:
        """The answer as he heard it: the preamble, then the last message's words."""
        return " ".join(part for part in (*self.preamble, said) if part)


class LiveHarbor:
    """The one kept-alive Harbor process this gateway holds, opened on demand."""

    def __init__(self):
        self.process: Process | None = None
        self._lock = threading.Lock()
        self._janitor: threading.Timer | None = None

    def process_for(self, session: str, existed: bool, turns: int) -> Process:
        """This session's live process: kept when it is the same conversation and nobody
        else has taken a turn on it since, otherwise closed and opened fresh."""
        with self._lock:
            held = self.process
            if held is not None and not (held.alive and held.session == session
                                         and held.turns_seen == turns):
                held.close()
                held = self.process = None
            if held is None:
                held = self.process = Process(session, existed, turns)
            # STAMPED UNDER THE LOCK (review item 5), so the idle janitor can never close
            # a process between handing it to a turn and the turn's first write.
            held.last_used = time.monotonic()
            return held

    def turn(self, line: str, session: str, existed: bool, turns: int, turn_id: str,
             progress, timeout: float, log) -> dict:
        """One Harbor turn down the kept-alive process: {said, written, drew, raw}.
        Raises LiveError (with `spoke`) or TimeoutExpired; the caller falls back."""
        deadline = time.monotonic() + timeout
        stream = Stream(turn_id, progress, log)
        try:
            process = self.process_for(session, existed, turns)
        except OSError as error:
            raise LiveError(f"the kept-alive process would not start: {error}") from None
        clock = {"warm": not getattr(process, "fresh", False), "spawnAt": time.time()}
        try:
            result = process.say(line, deadline, stream.on_record)
        except LiveError as error:
            error.spoke = stream.spoke
            self.drop()
            raise
        except subprocess.TimeoutExpired:
            self.drop()
            raise
        clock.update(doneAt=time.time(), envelope=stamps.envelope(result))
        process.fresh = False
        stream.finish()
        # WRITTEN ONLY HERE, where every record of the turn was seen: a turn that fell back
        # to the one-shot path writes no `reads`, and the report counts it as unknown
        # rather than as a turn that read nothing.
        try:
            judgesmod.outcome(turn_id, "reads", sections=stream.reads)
        except Exception:                                               # noqa: BLE001
            pass
        raw = str(result.get("result") or "")
        read = drawing.read_answer(raw, log=log, turn=turn_id, pen=stream.pen)
        clock["penAt"] = time.time()
        read["said"] = stream.heard_first(read["said"])
        process.turns_seen = turns + 1
        self.idle_later()
        return {**read, "raw": raw, "streamed": stream.spoke, "clock": clock}

    def drop(self) -> None:
        with self._lock:
            if self.process is not None:
                self.process.close()
            self.process = None

    def idle_later(self) -> None:
        """Close the process once it has sat unused for `HARBOR_LIVE_IDLE`."""
        if self._janitor is not None:
            self._janitor.cancel()
        self._janitor = threading.Timer(config.HARBOR_LIVE_IDLE + 1.0, self.close_if_idle)
        self._janitor.daemon = True
        self._janitor.start()

    def close_if_idle(self) -> None:
        with self._lock:
            held = self.process
            if held is not None and (time.monotonic() - held.last_used
                                     >= config.HARBOR_LIVE_IDLE):
                held.close()
                self.process = None


LIVE = LiveHarbor()


def install_shutdown() -> None:
    """No kept-alive process outlives the gateway (review item 5). The process is in its
    own group (`start_new_session`), so the gateway ending does not end it: an exit, or
    the SIGTERM launchd and systemd stop a service with, drops it first. The SIGTERM
    handler chains to one already installed, else exits as the default would have."""
    atexit.register(LIVE.drop)
    before = signal.getsignal(signal.SIGTERM)

    def on_term(signum, frame):
        LIVE.drop()
        if callable(before):
            before(signum, frame)
        raise SystemExit(128 + signum)
    signal.signal(signal.SIGTERM, on_term)
