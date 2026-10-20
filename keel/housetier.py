"""The house tier: `/api/house/` on `keel serve`, and the client that calls it (V12).

A kept-alive conversation is a process that has to outlive the sentence, and `keel converse`
is a CLI run once per sentence. So the process belongs to the one thing on the machine that
is already long-lived: `keel serve`. This module is both halves of that seam, in one file on
purpose, because the two ends of a wire are one decision.

    POST /api/house/open    {"card": "c-272"}                  warm a conversation, no tokens
    POST /api/house/say     {"card", "said", "turn", "seen"}   one turn, STREAMED back
    POST /api/house/close   {"card": "c-272", "wake": true}    end it, and put the house back
    GET  /api/house                                            what is open, for the doctor

The client below calls this machine's `keel serve` on loopback. The machine half does the
busy check, the memory floor, stopping the house's background session, the `claude` itself,
and the WAKE when the conversation ends; the board half is the hold, the notes and the words
he hears (`keel/converse.py`). (Until c-622 the same routes also answered another machine
over its door, with a shared key.)

THESE ROUTES START A `claude`, AND THAT DECIDES EVERYTHING ABOUT THEM. The first cut of
this file took the whole PLACEMENT from the request body (cwd, config dir, settings file,
model, add-dirs, tools, session id) and handed it to a process, with no key, on two servers
reachable from the tailnet. Review round 1 called it correctly: any device on
the tailnet, or any page open in a browser on one, could have started `claude` with its own
prompt in its own directory with its own tools, or resumed any session id it named. A
cross-site POST needs no preflight for a text body and `json.loads` does not care what the
content type claimed. So, four rules, and each one closes a different half of it:

1. **THE BODY NAMES A CARD.** It carries `card`, `said`, `turn`, `seen` and `timeout`, and
   nothing about placement and nothing about the prompt. The SERVER reads that card off its
   own board and builds the plan from its own config (`housetalk.plan`), and the SERVER
   wraps his sentence in `prompts.converse`. A caller that could choose the framing could
   delete the misheard rule, which is the paragraph between a wrong word and something
   irreversible. This also puts the plan where it belongs: on the machine whose worktree it
   names.
2. **THE BOARD DECIDES WHETHER THERE IS A CONVERSATION AT ALL.** A live `options.voice_hold`
   (which only `voice`, `drain` and `human` may write) and a house session. Without both,
   there is no conversation to be having and the request is refused.
3. **THIS MACHINE'S OWN KEY, AND NO HOP.** The key (`<state>/house.key`, 0600, minted once)
   means a LOCAL caller: `keel converse` on this machine talking to 127.0.0.1, and anything
   that reached the port through a proxy carrying it is refused, because that caller has no
   legitimate hop. It travels in `X-Keel-House` and is compared in constant time
   (`config.same_secret`). A custom header is also what makes a cross-site request
   preflight, and the preflight is never answered, so a page in his browser cannot reach
   these routes even on loopback.

The SHARED key (`shared_path`, minted by `shipyard init` and `keel house key mint`) is no
key to these routes any more; Bosun's key is derived from it (`keel/authority.py`).

THE ANSWER TO `say` IS A STREAM, ONE JSON OBJECT PER LINE, which is why the tier exists
rather than a plain request and reply. The events are `action` (what the house is doing,
from `keel/narration.py`'s closed set), `part` (a finished sentence of the house's own
answer, cut by `keel/sentences.py`), `fence` (a code block, never spoken) and `alive` (the
keepalive). The last line is the turn's `result` payload, or an `error`. Nothing on that
stream may be held back by a proxy, so it goes out with no content length, flushed per
line, and with the two headers that tell a proxy not to buffer it.

THE TIMEOUTS NEST, INNERMOST FIRST. The turn itself gets `timeout` (the server ends it), the
HTTP client waits `timeout + 10` overall with a 30 s read timeout, and the gateway kills the
`keel converse` CLI at `timeout + 30`. Each wait ends before the one outside it, so whatever
goes wrong is reported by the layer that knows what it was rather than killed by the layer
above. The keepalive is what makes a 30 s read timeout safe on a turn that thinks for two
minutes. The CONNECT is its own, much shorter wait (`CONNECT_TIMEOUT`): a server that is down
must be heard as away in three seconds, not in thirty.
"""

import argparse
import http.client
import json
import os
import secrets
import socket
import sys
import threading
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import NamedTuple

from keel import config as config_module, harness, house, housetalk, logins, prompts, views
from keel.board import Refused, open_board
from keel.config import Config, same_secret
from keel.housetalk import SESSIONS, Dead, NotSent, plan
from keel.voice import credentials_dir

HOUSE_PREFIX = "/api/house"
OPEN = "/api/house/open"
SAY = "/api/house/say"
CLOSE = "/api/house/close"
HEADER = "X-Keel-House"
KEY_NAME = "house.key"
SHARED_NAME = "house-key"
BOSUN_SETTINGS_NAME = "bosun-settings.json"     # Bosun's settings, its key in their env (c-553)
KEY_BYTES = 32
# WHAT SAYS A REQUEST CAME FROM SOMEWHERE ELSE. Any of these means a hop between the client
# and this server, and a request carrying this machine's key has no business making one,
# since that caller is `keel converse` on this machine talking to 127.0.0.1.
FORWARDED = ("x-forwarded-for", "x-forwarded-host", "x-forwarded-proto", "x-forwarded-port",
             "x-real-ip", "forwarded", "via")
TAILSCALE = "tailscale-"
# A `say` may wait as long as the house takes; the two board-only calls are quick or broken.
# A close may WAKE the house there, which starts a process, so it is given the longer wait.
QUICK_TIMEOUT = 30.0
# HOW LONG THE SERVER HAS TO ANSWER AT ALL. Connecting is not thinking: a refused connection
# comes back at once, and three seconds is far short of a wait he would notice.
CONNECT_TIMEOUT = 3.0
# THE THREE NESTED WAITS. `CLIENT_MARGIN` is how much longer the client waits than the turn
# it asked for, and it is small because the server ends the turn itself at `timeout`; the
# gateway's own margin is 30 s (`voice/harbor_voice/connected.py`).
CLIENT_MARGIN = 10.0
READ_TIMEOUT = 30.0
# HOW OFTEN A QUIET TURN SAYS IT IS STILL THERE. Under the read timeout by a factor of
# three, so two lost keepalives are not enough to end a healthy stream.
ALIVE_EVERY = 10.0

# What `close_session` answers. Four states rather than a boolean, because the caller's next
# move differs: a close that FAILED must not be followed by a wake (the wake would be
# refused and the house left down with its hold gone), while a server that is AWAY owns no
# conversation and nothing is in the way.
CLOSED = "closed"
NONE = "none"
AWAY = "away"
FAILED = "failed"

# WHY A MACHINE WOULD NOT OPEN A CONVERSATION, as a code and never as a sentence. The words
# he hears are the board half's (`keel/converse.py`), which owns every spoken refusal and is
# the only half that knows how to name the card. A code cannot be mistaken for one, and it
# survives the wire without a machine deciding what another machine's owner should hear.
BUSY = "busy"
SHORT = "memory"
UNREACHED = "away"
REFUSED = "refused"
# The one conversation that is not a card's (c-523): "put me through to Bosun".
BOSUN = "bosun"


class Away(Exception):
    """The conversation is not there, and asking the house again is SAFE.

    THE ONE EXCEPTION THAT MEANS "FALL BACK". It is raised only where the sentence cannot
    have reached a `claude`: nothing was listening before the request was accepted, the
    board refused the turn, the conversation would not open, or the process is confirmed
    dead. Every other failure is an ordinary `HarnessError`, which is spoken, because
    falling back on it would ask the house a question it is already answering.
    """


class Unreachable(Away):
    """The server that owns this conversation could not be reached at all.

    Refused, or a connect that ran out. It is an `Away` because nothing can have reached a
    `claude` through a connection that was never made: a `keel serve` that is down, and the
    turn falls back to a one-shot.
    """


class Opened(NamedTuple):
    """What `open` came back with.

    `stopped` is the fact the board half needs and cannot see for itself: whether the
    house's own background session was running and this open is what put it down. It
    decides the release, because a house voice stopped is woken and one that was already
    down is left down.
    """
    ok: bool
    stopped: bool = False
    refused: str = ""
    why: str = ""


class Shut(NamedTuple):
    """What a close came back with: how it went, and whether the house was woken."""
    status: str
    woke: bool = False


# ----- the two keys -----

def key_path(cfg: Config) -> Path:
    return Path(cfg.state_dir) / KEY_NAME


def shared_path(cfg: Config) -> Path:
    """The SHARED key's file: `~/.config/keel/credentials/house-key`, the secret Bosun's
    key is derived from (`keel/authority.py`).

    The credentials directory is `keel/voice.py`'s, reused rather than invented: 0700 under
    `~/.config`, outside the checkout so no `git add -A` commits it, and outside `state/` so
    no backup carries it. An install keeps its own, minted by `shipyard init` (c-619):
    `<install>/credentials/`, 0700, so Bosun's key there is that install's alone.
    """
    install = getattr(cfg, "install_home", None)
    if install is not None:
        return install / "credentials" / SHARED_NAME
    return credentials_dir(cfg.home) / SHARED_NAME


def bosun_settings_path(cfg: Config) -> Path:
    """Bosun's settings file, beside the shared key (c-553): its `env` carries Bosun's key,
    the one place a `claude --bg` session is sure to read (the process environment is the
    daemon's spare's). Here rather than under `state/` for the shared key's reasons: 0600 in
    the 0700 credentials directory, no backup carries it, and whoever can read it could
    already read the shared key the Bosun key is derived from."""
    return shared_path(cfg).parent / BOSUN_SETTINGS_NAME


def house_key(cfg: Config) -> str:
    """This machine's own house key, minted once at 0600. Both halves read it from here.

    Written with `O_EXCL` so two processes starting together cannot each mint one and
    disagree; whichever loses the race reads the winner's.
    """
    path = key_path(cfg)
    try:
        return path.read_text().strip()
    except OSError:
        pass
    path.parent.mkdir(parents=True, exist_ok=True)
    minted = secrets.token_hex(KEY_BYTES)
    try:
        handle = os.open(str(path), os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    except FileExistsError:
        return path.read_text().strip()
    except OSError:
        return minted                  # unwritable state: the key lives for this process
    with open(handle, "w") as writer:
        writer.write(minted + "\n")
    return minted


def shared_key(cfg: Config) -> str:
    """The shared key this machine holds, or "" when there is none (a scratch config never
    holds one). Never minted on demand: `keel house key mint` and `shipyard init` write it."""
    if getattr(cfg, "scratch", False):
        return ""
    try:
        return shared_path(cfg).read_text().strip()
    except OSError:
        return ""


def mint_shared(cfg: Config, force: bool = False) -> Path:
    """Write a new shared key, 0600 in a 0700 directory. Refuses to overwrite without
    `force`, because a new one changes Bosun's key."""
    if getattr(cfg, "scratch", False):
        raise Refused(f"a scratch config does not mint the shared house key ({cfg.scratch_note})")
    path = shared_path(cfg)
    if path.exists() and not force:
        raise Refused(f"{path} is already there; --force replaces it, and Bosun's key with it")
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    path.parent.chmod(0o700)
    # Written beside and moved into place, at 0600 from the first byte, so there is never a
    # moment when a readable half-written key exists: the same shape `keel voice key set`
    # uses for the keys already in this directory.
    tmp = path.with_name(path.name + ".new")
    tmp.unlink(missing_ok=True)
    with os.fdopen(os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600), "w") as out:
        out.write(secrets.token_hex(KEY_BYTES) + "\n")
    os.replace(tmp, path)
    return path


# ----- the plan, kept for the life of the hold -----

class Plans:
    """The plan for a card, built once per conversation rather than once per sentence.

    Building one asks the BOARD, and then asks the card's adapter where its worktree is.
    That is the same answer for every sentence of one conversation, so it is not paid
    before each turn.

    IT IS DROPPED WHENEVER THE CONVERSATION IS NOT THE SAME ONE ANY MORE, which is three
    things: the close (every path that ends a hold calls it, so a hold released early takes
    the plan with it), the hold's own expiry (kept here as the deadline the entry carries),
    and the card's session id changing under it (compared against the live conversation's,
    which is the process actually holding that session).

    `open` never reads it, only writes it: a conversation that is starting asks the board
    the two questions the board alone can answer, and those are also what says this caller
    may be here at all.
    """

    def __init__(self):
        self.lock = threading.Lock()
        self.kept: dict[str, tuple[dict, float]] = {}

    def get(self, card_id: str, entry=None) -> dict | None:
        with self.lock:
            held = self.kept.get(card_id)
        if held is None:
            return None
        made, until = held
        if time.time() >= until:
            return self.drop(card_id)
        if entry is not None and getattr(entry.talk, "session_id", "") != made["session_id"]:
            return self.drop(card_id)
        return made

    def put(self, card_id: str, made: dict, until: float) -> dict:
        with self.lock:
            self.kept[card_id] = (made, until)
        return made

    def drop(self, card_id: str) -> None:
        with self.lock:
            self.kept.pop(card_id, None)
        return None


PLANS = Plans()


def good_until(cfg: Config, held: dict | None) -> float:
    """When a plan built under this hold stops being trustworthy: the hold's own expiry.

    A hold with no readable `until` is treated as live by `views.voice_hold`, so the plan
    gets one hold's worth of time rather than forever."""
    until = views.parse_at((held or {}).get("until"))
    if until is None:
        return time.time() + cfg.voice_hold_seconds
    return until.timestamp()


# ----- the server's half -----

class HouseTier:
    """The `/api/house/` methods of a request handler, mixed into `serve.Handler`.

    The handler supplies `cfg`, `read_body`, `headers` and the reply helpers, exactly as
    `VoiceTier` is given them.
    """

    def forwarded(self) -> bool:
        """Did this request come through a proxy."""
        for name in self.headers.keys():
            low = name.lower()
            if low in FORWARDED or low.startswith(TAILSCALE):
                return True
        return False

    def house_refusal(self) -> tuple[int, str] | None:
        """Why this request may not be answered at all, before its body is even read.

        The machine's own key is loopback's alone: it is `keel converse` on this machine, so
        anything forwarded carrying it is somebody else's.
        """
        offered = self.headers.get(HEADER) or ""
        if same_secret(offered, house_key(self.cfg)):
            if self.forwarded():
                return 403, "this machine's own key may not arrive through a proxy"
            return None
        return 403, "that is not this machine's house key"

    def house(self, method: str) -> None:
        refusal = self.house_refusal()
        if refusal:
            return self.reply_json(refusal[0], {"ok": False, "error": refusal[1]})
        path = self.path_only()
        if method == "GET" and path == HOUSE_PREFIX:
            return self.reply_json(200, {"ok": True, "live": SESSIONS.state()})
        if method != "POST":
            return self.reply_json(405, {"ok": False, "error": "not a house route"})
        try:
            body = json.loads(self.read_body() or b"{}")
        except ValueError:
            return self.reply_json(400, {"ok": False, "error": "the body is not JSON"})
        if not isinstance(body, dict):
            return self.reply_json(400, {"ok": False, "error": "the body must be an object"})
        card_id = str(body.get("card") or "")
        if not card_id:
            return self.reply_json(400, {"ok": False, "error": "no card in the body"})
        if path == CLOSE:
            # NO BOARD QUESTION HERE, because a close is what ENDS a conversation: the
            # hold may have been cleared a moment before it, and a close that needed a
            # live hold would work in one order only.
            return self.house_close(card_id, bool(body.get("wake")))
        if path not in (OPEN, SAY):
            return self.reply_json(404, {"ok": False, "error": "not a house route"})
        try:
            made = self.house_plan(card_id, fresh=path == OPEN)
        except Refused as refused:
            return self.reply_json(409, {"ok": False, "error": str(refused)})
        except Exception as error:                                      # noqa: BLE001
            return self.reply_json(409, {"ok": False, "error": str(error).splitlines()[0]})
        if path == OPEN:
            return self.house_open(made, body)
        self.house_say(made, body)

    def house_plan(self, card_id: str, fresh: bool = False) -> dict:
        """The plan for this card, built HERE, after the board's two questions.

        The board is opened per request rather than held: these calls are a few a minute
        at the busiest, and a long-lived handle in a threaded server is a lock to reason
        about for no gain.

        AND IT IS KEPT FOR THE LIFE OF THE HOLD (`Plans`). A conversation that is STARTING
        asks anyway (`fresh`), since those two questions are also what says the caller may
        be here at all.
        """
        if not fresh:
            kept = PLANS.get(card_id, SESSIONS.entry(card_id))
            if kept is not None:
                return kept
        board = open_board(self.cfg)
        try:
            if card_id == BOSUN:
                # BOSUN HAS NO CARD (c-523): its hold is the board's `holds` row and its plan
                # is its own session's, `keel/bosuntalk.py`. A sentence into a conversation
                # this server no longer has (his tap closed it, or it went idle) is refused
                # rather than reopened past the guards `open` alone asks.
                from keel import bosuntalk
                if not fresh and SESSIONS.entry(card_id) is None:
                    raise Refused("that conversation with Bosun was ended")
                made = bosuntalk.door_plan(self.cfg, board)
                return PLANS.put(card_id, made, good_until(self.cfg, board.bosun_hold()))
            card = board.get(card_id)
        finally:
            board.close()
        held = views.voice_hold(card.get("options"))
        if not held:
            raise Refused(f"{card_id} is not held by voice, so there is no conversation")
        if not card.get("session_id"):
            raise Refused(f"{card_id} has no house session")
        return PLANS.put(card_id, plan(self.cfg, card), good_until(self.cfg, held))

    def house_ready(self, made: dict) -> str | None:
        """The two guards that are facts about this machine, as a refusal code or None.
        They are asked in `open`, which is the one call every conversation starts with, and
        their answer travels as a code the board half turns into one of its spoken
        sentences."""
        if made.get("bosun"):
            from keel import bosuntalk
            refused = bosuntalk.ready(self.cfg, made)
            if refused:
                return refused
        if housetalk.busy(made):
            return BUSY
        if housetalk.memory_short(self.cfg.memory_floor_mb):
            return SHORT
        return None

    def house_open(self, made: dict, body: dict) -> None:
        """Warm this card's conversation, after the machine's own two guards.

        AND STOP THE HOUSE'S BACKGROUND SESSION, HERE. `claude -p --resume` is refused
        while one is alive, so a conversation cannot start until it is down. Whether there
        WAS one to stop
        goes back in the answer, because that is what the board half writes into the hold
        and what decides, at the end, whether the house is woken or left as it was found.
        """
        if made.get("bosun"):
            # BOSUN'S OPEN TAKES HIS TAP LOCK (c-523): a Start carried out at the same moment
            # would launch a Bosun over the session this is about to hold.
            from keel import console
            with console.held_lock(self.cfg) as held:
                if not held:
                    PLANS.drop(made["card"])
                    return self.reply_json(200, {"ok": False, "refused": REFUSED,
                                                 "error": "a tap on Bosun is being carried out"})
                return self.open_here(made, body)
        return self.open_here(made, body)

    def open_here(self, made: dict, body: dict) -> None:
        refused = self.house_ready(made)
        if refused:
            PLANS.drop(made["card"])
            code, why = refused if isinstance(refused, tuple) else (refused, "")
            return self.reply_json(200, {"ok": False, "refused": code, "error": why})
        try:
            # A FAILED STOP IS A REFUSAL, NEVER A 500 (r-17). The harness has already
            # retried the one answer that asks for it; what is left goes back as the reason
            # he hears, and the kept plan goes the way every refusal's does.
            stopped = housetalk.stop_house(made)
        except harness.HarnessError as error:
            PLANS.drop(made["card"])
            return self.reply_json(200, {"ok": False, "refused": REFUSED, "error": str(error)})
        try:
            SESSIONS.open(made, timeout=int(body.get("timeout") or harness.TURN_TIMEOUT))
        except harness.HarnessError as error:
            logins.saw(self.cfg, made.get("config_dir"), str(error))
            return self.reply_json(200, {"ok": False, "refused": REFUSED,
                                         "error": str(error), "stopped": stopped})
        if made.get("bosun"):
            from keel import bosuntalk
            bosuntalk.opened(self.cfg, stopped)
        self.reply_json(200, {"ok": True, "card": made["card"], "stopped": stopped})

    def house_close(self, card_id: str, wake: bool) -> None:
        """End this card's conversation, and put its house back if that was asked for.

        The wake rides on the close because the order is not negotiable: a wake is refused
        while any process still holds the session, so the two must happen here, in this
        order, and the answer says whether the house is up again.
        """
        closed = SESSIONS.close(card_id)
        PLANS.drop(card_id)
        if card_id == BOSUN:
            return self.bosun_close(closed, wake)
        if not wake:
            return self.reply_json(200, {"ok": True, "closed": closed, "woke": False})
        board = open_board(self.cfg)
        try:
            woke = bool(house.wake(self.cfg, board, card_id))
        except Exception as error:                                      # noqa: BLE001
            return self.reply_json(200, {"ok": True, "closed": closed, "woke": False,
                                         "error": str(error).splitlines()[0]})
        finally:
            board.close()
        self.reply_json(200, {"ok": True, "closed": closed, "woke": woke})

    def bosun_close(self, closed: bool, wake: bool) -> None:
        """Bosun's close: the same order (the conversation first, then the wake), with its
        own wake (`bosuntalk.wake`, its environment and no card) and a Journal line."""
        from keel import bosuntalk
        woke, error = False, None
        if wake:
            try:
                woke = bosuntalk.wake(self.cfg)
            except Exception as failed:                                 # noqa: BLE001
                error = str(failed).splitlines()[0] if str(failed) else type(failed).__name__
        bosuntalk.closed(self.cfg, woke, error or "")
        answer = {"ok": True, "closed": closed, "woke": woke}
        self.reply_json(200, dict(answer, error=error) if error else answer)

    def house_say(self, made: dict, body: dict) -> None:
        """One turn, written back as it happens.

        NO CONTENT LENGTH AND NO BUFFER. The body is a sequence of lines whose length
        nobody knows when the headers go out, and every one of them is worth less the
        later it arrives: the answer ends the response, and the client reads to the end.
        The two headers that ask a proxy not to hold a stream back go out with it: a proxy
        that buffered would turn every part back into the whole answer at the end of the
        turn.

        A FAILURE IS A LINE, NEVER A STATUS. By the time a turn can fail the headers have
        usually gone, so there is no status left to send; and the caller is holding a
        microphone open, so what it needs on every path is something it can read off the
        same stream it is already reading. The line says `wrote` and `dead`, which is what
        the client's no-double-delivery rule turns on.
        """
        said = str(body.get("said") or "")
        turn_id = str(body.get("turn") or "")
        timeout = int(body.get("timeout") or harness.TURN_TIMEOUT)
        report = str(body.get("report") or "")
        grammar = bool(body.get("grammar"))
        self.send_response(200)
        self.send_header("Content-Type", "application/x-ndjson; charset=utf-8")
        self.send_header("Cache-Control", "no-store, max-age=0")
        self.send_header("X-Accel-Buffering", "no")
        self.end_headers()
        self.close_connection = True
        lock = threading.Lock()
        last = [time.time()]

        def write(event: dict) -> None:
            with lock:
                last[0] = time.time()
                try:
                    self.wfile.write((json.dumps(event) + "\n").encode())
                    self.wfile.flush()
                except (BrokenPipeError, ConnectionResetError, ValueError, OSError):
                    pass        # he hung up; the turn finishes and the card keeps it

        done = threading.Event()

        def keepalive():
            """SAY SOMETHING EVERY TEN SECONDS OF SILENCE. A house reading a large file
            says nothing for a minute, and a link that has died says nothing forever;
            without this the client cannot tell them apart and would have to wait out the
            whole turn to find out."""
            while not done.wait(min(ALIVE_EVERY, 1.0)):
                if time.time() - last[0] >= ALIVE_EVERY:
                    write({"type": "alive"})

        beat = threading.Thread(target=keepalive, name="house-alive", daemon=True)
        beat.start()
        try:
            framing, plain = self.framed(made, said, report, grammar)
            payload = SESSIONS.say(
                made, said, framing=framing, plain=plain,
                turn_id=turn_id,
                seen=int(body.get("seen") or 0), timeout=timeout, on_event=write)
        except harness.HarnessError as error:
            # The turn ran HERE, under this machine's config dir: a lost login it names is
            # this machine's Logins row to mark (c-558).
            logins.saw(self.cfg, made.get("config_dir"), str(error))
            return write({"type": "error", "error": str(error),
                          "wrote": not isinstance(error, NotSent),
                          "dead": isinstance(error, Dead)})
        finally:
            done.set()
            beat.join(timeout=2.0)
        write({"type": "result", "payload": payload})


    @staticmethod
    def framed(made: dict, said: str, report: str, grammar: bool) -> tuple[str, str]:
        """(the first sentence's framing, every later one's): a house's, or Bosun's."""
        if made.get("bosun"):
            from keel import bosuntalk
            return bosuntalk.framing(said), bosuntalk.framing_more(said)
        return (prompts.converse(said, worktree=bool(made.get("worktree")), report=report),
                prompts.converse_more(said, report=report, grammar=grammar))


# ----- the client's half: where, and with which key -----

def base_url(cfg: Config) -> str:
    """Where this conversation's owner is: this machine's `keel serve`, on loopback."""
    return f"http://127.0.0.1:{cfg.serve_port}"


def error_of(raw: bytes) -> str:
    """The server's one line out of an error body."""
    try:
        return str(json.loads(raw).get("error") or "no reason given")
    except (ValueError, AttributeError):
        return raw.decode(errors="replace").strip()[:200] or "no reason given"


# ----- the client's half: the connection -----

class ShortConnect:
    """CONNECT in three seconds, then read for as long as the turn takes.

    The stdlib has ONE timeout for a connection and it covers both, and the two wants are
    opposite: a turn may think for minutes, and a server that is down must be heard as away
    at once. So the short wait goes on while the socket is being made and the caller's own
    wait goes back the moment it is. Mixed in FIRST, so `super().connect()` is the real one.
    """

    def connect(self):
        wanted, self.timeout = self.timeout, CONNECT_TIMEOUT
        try:
            super().connect()
        finally:
            self.timeout = wanted
            if self.sock is not None:
                self.sock.settimeout(wanted)


class ShortHTTP(ShortConnect, http.client.HTTPConnection):
    pass


class ShortHandler(urllib.request.HTTPHandler):
    def http_open(self, req):
        return self.do_open(ShortHTTP, req)


# The one opener every call here goes through. `build_opener` keeps urllib's own error
# processor, so an HTTP status is still an `HTTPError` and nothing else about the calls
# below changes.
OPENER = urllib.request.build_opener(ShortHandler)


def unreachable(error) -> bool:
    """True when the server could not be reached AT ALL: refused, no such name, or a
    connect that ran out. A server that answered anything, even a refusal, is not this."""
    reason = getattr(error, "reason", None) or error
    return isinstance(reason, (ConnectionRefusedError, socket.gaierror, TimeoutError,
                               ConnectionResetError))


def _post(cfg: Config, card: dict, path: str, body: dict, timeout: float):
    request = urllib.request.Request(base_url(cfg) + path, data=json.dumps(body).encode(),
                                     method="POST")
    request.add_header("Content-Type", "application/json")
    request.add_header(HEADER, house_key(cfg))
    return OPENER.open(request, timeout=timeout)


# ----- the client's half: the three calls -----

def open_session(cfg: Config, card: dict, timeout: int = harness.TURN_TIMEOUT) -> Opened:
    """Warm this card's conversation. NEVER RAISES.

    IT IS THE ONE CALL THAT STARTS A CONVERSATION, so it carries the two guards that are
    facts about this machine (is the house busy, is there memory) and it is where the
    house's own session is stopped.
    """
    body = {"card": card["id"], "timeout": timeout}
    try:
        with _post(cfg, card, OPEN, body, QUICK_TIMEOUT) as answer:
            got = json.loads(answer.read() or b"{}")
    except urllib.error.HTTPError as error:
        with error:
            return Opened(False, refused=REFUSED, why=error_of(error.read()))
    except (OSError, ValueError, urllib.error.URLError) as error:
        if unreachable(error):
            return Opened(False, refused=UNREACHED, why=str(error))
        return Opened(False, refused=REFUSED, why=str(error))
    if not got.get("ok"):
        return Opened(False, stopped=bool(got.get("stopped")),
                      refused=str(got.get("refused") or REFUSED),
                      why=str(got.get("error") or ""))
    return Opened(True, stopped=bool(got.get("stopped")))


def close_session(cfg: Config, card: dict, wake: bool = False) -> Shut:
    """End this card's conversation, and wake its house there when asked. NEVER RAISES.

    CALLED BEFORE EVERY WAKE, AND NOW IT IS ALSO HOW THE WAKE HAPPENS. The drain, the
    deck's Stop, a gate answered and "back to Harbor" each run in their own process, and
    none of them owns the conversation; this is how they reach the one that does.

    THE FOUR ANSWERS ARE NOT A BOOLEAN, because the caller's next move differs. `AWAY`
    means nothing was listening, so nothing owns a conversation and the wake is safe.
    `FAILED` means the owner answered and could not close: something still holds that
    session, the wake would be refused, and the caller notes it and leaves the house down
    rather than pretending.
    """
    try:
        with _post(cfg, card, CLOSE, {"card": card["id"], "wake": bool(wake)},
                   QUICK_TIMEOUT) as answer:
            body = json.loads(answer.read() or b"{}")
    except urllib.error.HTTPError as error:
        error.close()          # it holds the answer's body open until closed
        return Shut(FAILED)
    except (OSError, ValueError, urllib.error.URLError):
        return Shut(AWAY)
    if not body.get("ok"):
        return Shut(FAILED)
    return Shut(CLOSED if body.get("closed") else NONE, bool(body.get("woke")))


def say(cfg: Config, card: dict, said: str, *, turn_id: str,
        timeout: int = harness.TURN_TIMEOUT, on_event=None, report: str = "",
        grammar: bool = False) -> dict:
    """One sentence into the kept-alive conversation; the turn's own result payload.

    `on_event` is called with each event AS IT ARRIVES, on this thread, which is the whole
    point of the stream: the caller writes the parts into the gateway's progress inbox
    while the house is still writing the answer.

    A BROKEN STREAM IS RETRIED ON THE SAME TURN ID, ONCE, AND NEVER RE-ASKED (review round
    1, finding B). The sentence is already inside the process by then, so a second `say`
    would spend a second turn and he would hear the answer twice; instead the retry names
    the same turn and says how many events it has already had, and the server ATTACHES it
    to the turn that is still running. A second break is a failure, out loud.

    `Away` is raised only where asking the house again is SAFE: nothing listening before
    the request was accepted, the board refusing, or the server saying the sentence never
    reached the process (`wrote: false`) or that the process is dead. `Unreachable` is the
    narrower one: the server itself did not answer. Everything else is a `HarnessError`,
    which is spoken.
    """
    seen = 0
    for attempt in (1, 2):
        got: list = []
        try:
            return _stream(cfg, card, said, turn_id, timeout, seen, got, on_event, report,
                           grammar)
        except (Away, harness.HarnessError):
            raise
        except (OSError, urllib.error.URLError, ValueError) as error:
            if isinstance(error, urllib.error.HTTPError):
                error.close()      # a refusal holds its body open until closed
            if not got:
                # NOTHING CAME BACK AT ALL, so nothing was accepted and nothing can have
                # been written: the one transport failure it is safe to fall back on.
                if unreachable(error):
                    raise Unreachable(f"{base_url(cfg)} did not answer: "
                                      f"{error}") from None
                raise Away(f"the server did not answer: {error}") from None
            if attempt == 2:
                if unreachable(error):
                    # THE LINK WENT AND STAYED GONE. His sentence did reach a `claude`, so
                    # nothing may be asked again; what is left is to say so.
                    raise Unreachable(f"the answer stopped coming back: {error}") from None
                raise harness.HarnessError(
                    f"the answer stopped coming back: {error}") from None
            seen = len(got)
    raise harness.HarnessError("the answer stopped coming back")


def _stream(cfg: Config, card: dict, said: str, turn_id: str, timeout: int, seen: int,
            got: list, on_event, report: str = "", grammar: bool = False) -> dict:
    """One attempt at one turn. Appends every event it received to `got`.

    `report` is the last turn's board report (C1) and `grammar` asks for the board's grammar
    card on a later sentence (C4), both framed by the server around his words; a server that
    predates them ignores the fields, which costs the framing and nothing else.
    """
    body = {"card": card["id"], "said": said, "turn": turn_id, "seen": seen,
            "timeout": timeout, "report": report, "grammar": grammar}
    payload = None
    deadline = time.time() + timeout + CLIENT_MARGIN
    with _post(cfg, card, SAY, body, READ_TIMEOUT) as answer:
        for raw in answer:
            if time.time() > deadline:
                raise harness.HarnessError(
                    f"the turn took longer than {timeout}s, and it was ended")
            line = raw.decode("utf-8", "replace").strip()
            if not line:
                continue
            try:
                event = json.loads(line)
            except ValueError:
                continue
            if not isinstance(event, dict):
                continue
            kind = event.get("type")
            if kind == "alive":
                continue                  # the link is fine; there is nothing to say
            got.append(event)
            if kind == "result":
                payload = event.get("payload") or {}
            elif kind == "error":
                why = str(event.get("error") or "the turn failed")
                if event.get("dead") or not event.get("wrote", True):
                    raise Away(why)
                raise harness.HarnessError(why)
            elif on_event is not None:
                on_event(event)
    if payload is None:
        raise OSError("the stream ended with no result")
    return payload


# ----- the verb -----

def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="keel house", description=(
        "the shared key Bosun's key is derived from; `key` says whether it is set up"))
    subs = parser.add_subparsers(dest="verb", required=True)
    key = subs.add_parser("key", help="the shared house key")
    key.add_argument("action", nargs="?", default="check", choices=("check", "mint"),
                     help="check (the default) says whether it is there; mint writes one")
    key.add_argument("--force", action="store_true",
                     help="replace a key that is already there (Bosun's key changes with it)")
    return parser


def main(argv: list[str] | None = None) -> int:
    """`keel house key [mint]`: whether the shared key is set up.

    IT NEVER PRINTS THE KEY. The whole of what a person needs to know is whether the file
    is there and where it is, so that it can be copied; printing it would put a shared
    secret into a terminal's scrollback for no gain.
    """
    args = build_parser().parse_args(list(sys.argv[1:] if argv is None else argv))
    cfg = config_module.load()
    path = shared_path(cfg)
    if args.action == "mint":
        try:
            mint_shared(cfg, force=args.force)
        except Refused as refused:
            print(refused, file=sys.stderr)
            return 1
        print(f"wrote a new shared house key to {path}; restart `keel serve` and Bosun")
        return 0
    if not path.is_file():
        print(f"no shared house key: {path} is not there (`keel house key mint` writes one)")
        return 1
    mode = path.stat().st_mode & 0o777
    print(f"the shared house key is at {path} ({oct(mode)})")
    return 0 if mode == 0o600 else 1
