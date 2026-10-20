"""The gateway: HTTP and one WebSocket, loopback only, behind the view's proxy.

    GET  /voice/health    is it up, and which speech and filler backends answered
    GET  /voice/state     the bus. Read only. There is no POST anywhere
    GET  /voice/flags.js  the four open questions, so the page has no second copy
    WS   /voice/ws        audio up, audio down, and the turn's events

WHAT THIS PROCESS MAY DO, in full: read GET /api/state over loopback, call a local model,
write inside its own segment directory, and type one verified line into Harbor's pane
through harbor-message. It has no /api/action, no git, no tmux of its own and no ability
to spawn. That is the door, and "voice reads /api/state and never calls /api/action" is
grep-able in this file.

BOUND TO 127.0.0.1, ALWAYS. Tailscale Serve fronts the view, and the view proxies
/voice/ onto its origin. Same origin means `wss://` needs no CORS and no second
certificate, and the phone's `getUserMedia` gets the HTTPS it insists on without a
self-signed anything.

THE SOCKET PROTOCOL, which is small on purpose:

  up    binary  16 kHz mono PCM16, streamed while he holds the button
        text    {"type": "start"|"end"|"cut"|"pause"|"text"|"ping", ...}
                `start` carries `handsFree` (true when the listen was auto-armed rather
                than by a finger on the orb), `conversation` (true when another
                utterance is expected after this turn, V2) and `listen` (the page's own
                number for this listen, echoed back on `endpoint`)
                `end` and `text` carry `mode` ("capture" or "talk"; absent means talk)
                and `text` is TYPED: answered in text only unless it says `aloud` (VP-3)
                and `engine` ("google" or "kokoro"; absent means the configured chain)
                and, for a capture, `space` ("personal" or "work")
                `pause` is {"type": "pause", "why": "tap"|"hidden"|"ended"}: the
                microphone has been CLOSED at his end (V3), so this end stops expecting
                audio and lets go of anything it was holding
                `presence` is {"type": "presence", "visible": bool}: whether the page
                can be seen, sent on every visibility change and socket open (D-2). A
                fact, never a command: it only holds back unprompted speech
                `trace` is {"type": "trace", "event": "arm"|"press"|"frames"|
                "playback-end"|"quiet"|"stalled"|"release"|"repress", "reason": ...,
                "listen": ..., "at": <ms since page load>}: what the page's own watchdog
                saw (V13). It is WRITTEN TO THE TRANSCRIPT AND NEVER ACTED ON
  down  binary  24 kHz mono PCM16, the answer
        text    {"type": "transcript"|"speak"|"error"|"captured"|"endpoint"|"listen"
                        |"listen-now"|"partial"|"conversation"|"connected"|"notice"
                        |"pong", ...}
                (the state itself is read from GET /voice/state, never pushed; the page
                ignores `pong`, which only keeps the proxy's idle timer from closing it)
                `captured` is {"type": "captured", "id": "c-231", "space": ...}: the
                card a capture became, so the page draws the id without waiting for
                its poll
                `endpoint` is {"type": "endpoint", "reason": "hangover"|"quiet",
                "listen": n, "generation": n}: the listen is over, either because he
                stopped talking (V1's detector) or because nobody ever started
                `listen` is {"type": "listen", "reason": "conversation"|"partial"}:
                reopen the microphone, because a conversation is open (V2) or because
                half a sentence is being held and the rest is wanted (V10)
                `listen-now` is {"type": "listen-now", "reason": "connected"|"released",
                "generation": n}: the gateway has finished speaking a switch, so the page
                may press its own orb (V13). Sent once per switch; the page obeys it only
                when a conversation is open and it is not already holding
                `partial` is {"type": "partial", "state": "held"|"joined"|"expired"}:
                what is happening to that half sentence
                `conversation` is {"type": "conversation", "state": "closed"|"paused",
                "why": ...}: he said "that's all" or "hold on", matched in code before
                any turn was spent on it

THE PAGE NUMBERS ITS LISTENS AND THIS END ECHOES THE NUMBER (c-314). Conversation mode
re-arms the microphone after every answer, so for the first time there is such a thing as
an `endpoint` for the listen BEFORE the one in hand, which would end the new one a
syllable after it opened. The number is the page's and this side never reads meaning into
it: it comes in on `start` and goes back out on `endpoint`, and the page decides.

A `quiet` ENDPOINT IS ANSWERED WITH `cut`, NOT `end`. The hangover cannot end a listen
nobody spoke into, because it only arms after `VAD_MIN_SPEECH` of real speech, so a
separate cap closes one instead. Nothing was said, so there is nothing to dispatch: the
page drops the listen with `cut` and `end` stays the only thing that flushes.

`end` IS THE ONLY FLUSH, AND `endpoint` DOES NOT FLUSH. The detector tells the page the
utterance is over and the PAGE replies with the ordinary `end`, exactly as a release
does. Two reasons, and both are worth the one round trip it costs (milliseconds, beside
a hangover measured in whole seconds):

  1. The mode and the space ride on `end`, read at the moment the turn ends, so a toggle
     flipped mid-utterance still means what it shows. A server-side flush would have to
     guess them from whatever the page said when it started.
  2. A page that has never heard of `endpoint` ignores it and waits out its own 20 second
     backstop, which is today's behaviour. That is what makes the detector purely
     additive: if it never fires, or the page is old, nothing about a turn changes.

Slice 3's held partial (V10) needs the same property from the other side: one way to end
a turn, so holding a transcript back does not mean inventing a second one.

THE ENGINE IS THE MESSAGE'S TOO (V7, card c-312), and for the same reason: the page owns
which synthesiser speaks, carries it on every message, and this process keeps no copy that
could disagree with the control he is looking at.

THE MODE IS THE MESSAGE'S, NEVER THE SERVER'S. There is no mode or space state in this
process to drift from the page: each utterance says which path it wants, and the gateway
trusts that and nothing else (<install>/history/docs/voice-two-modes.md, section 3).

The generation number rides on every message in both directions. A message carrying an
older generation is dropped at this boundary, which is the concrete form of the prior
art's hardest-won bug: without it, the cancelled turn's stop signal races in and kills
the new answer.
"""
from __future__ import annotations

import json
import os
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from . import bus as busmod
from . import connected
from . import dispatcher as dispatcher_module
from . import harbormsg
from . import (config, corpus, hearing, judges as judgesmod, record,
               refine as refinemod, snapshot as snapmod, speech, vad as vadmod, verbs,
               ws)
from .dispatcher import QUIET, Dispatcher, new_turn_id
from .harbormsg import SayInbox

VERSION = "1"

# How much audio to hand the speech model at once on the way out. 24 kHz PCM16 is 48
# kB/s, so this is about a quarter second of sound: small enough that the first of it is
# playing while the rest is still being made, large enough not to be a frame per packet.
OUT_CHUNK = 12000
# HOW LONG A CONNECT MAY TAKE BEFORE IT IS WORTH SAYING SO AGAIN (V8). Slice 5 measured the
# stop at about 0.8 s and the whole leg is one `keel converse` subprocess on top of that, so
# this fires rarely and that is the point: it is the line for the connect that went wrong
# somewhere the code cannot see, not a progress report.
CONNECT_SLOW_SECONDS = float(os.environ.get("HARBOR_VOICE_CONNECT_SLOW", "4.0"))


class Conversation:
    """Whether another utterance is expected, and the half sentence that may be held.

    ONE OF THESE FOR THE PROCESS, like the detector and for the same reason: he is one
    person with one microphone. It holds two facts and nothing else, so that the Gateway
    above can stay about sockets and turns.

    THE OPEN FLAG IS THE PAGE'S, KEPT HERE. The gateway answers one utterance at a time
    and has no opinion about whether another is coming; what it needs the flag for is the
    one thing only this side knows, which is when a turn is really over and the
    microphone may reopen. The page says so again on every `start`, so there is nothing
    here that can get out of step with what he last did.

    THE HELD HALF IS V10's `complete: no`: the thought was not finished, so nothing is
    dispatched and the rest of the sentence is waited for. It carries the mode and the
    space it was SPOKEN in, because he may move the toggle between the two halves and a
    half dictated into Capture must not become a question to Harbor.
    """

    def __init__(self):
        self.open = False
        # WHOSE CONVERSATION IT IS, and it is one socket's. Two pages can be open at once
        # (the phone and the desk), and a conversation belongs to the page he is talking
        # into: the one that last said `conversation: true` on a `start`. So the desk tab
        # closing cannot end the conversation he is having on the phone, and the
        # conversation's own messages are sent to the owner rather than broadcast, so the
        # other page never re-arms a microphone nobody is talking into.
        self.owner = None
        self._held: dict | None = None
        self._lock = threading.Lock()
        self._timer: threading.Timer | None = None

    def hold(self, said: str, expire, **fields) -> None:
        """Hold half a sentence, and arm its expiry.

        IT EXPIRES RATHER THAN WAITING FOR EVER. `config.JUDGE_HOLD_SECONDS` of nothing
        and `expire` is called, which dispatches the held text as the ordinary turn it
        would have been. That is what makes a wrong verdict cost a pause and never a
        sentence.
        """
        with self._lock:
            self._cancel()
            self._held = {"said": said, "at": time.time(), **fields}
            timer = threading.Timer(config.JUDGE_HOLD_SECONDS, expire)
            timer.name = "voice-partial"
            timer.daemon = True
            self._timer = timer
            timer.start()

    def take(self) -> dict | None:
        """The held half, if there is one, and it is TAKEN rather than read: two callers
        must never both think they have it."""
        with self._lock:
            held, self._held = self._held, None
            self._cancel()
        return held

    def take_if_owned(self, sock) -> dict | None:
        """The held half only if THIS socket is the one that spoke it.

        A page that is not holding anything must not be able to release another page's
        half sentence by closing its own tab. Under the same lock as `take`, because the
        check and the taking are one decision.
        """
        with self._lock:
            if self._held is None or self._held.get("sock") is not sock:
                return None
            held, self._held = self._held, None
            self._cancel()
        return held

    def holding(self) -> bool:
        """Whether half a sentence is held, waiting for the rest of it."""
        with self._lock:
            return self._held is not None

    def _cancel(self) -> None:
        if self._timer is not None:
            self._timer.cancel()
            self._timer = None


class Gateway:
    """Everything the process owns, assembled once so the handler holds no state."""

    # WHETHER HE HAS JUST CUT AN ANSWER OFF (c-552): the `bargein` answer is asked on the
    # first utterance after a cut, and only then. A class default, so a gateway built
    # without `__init__` reads it too. Whether a listen was hands-free is NOT kept here: it
    # travels with its own utterance, like the space does, because the next `start` (or a
    # second page) would overwrite a gateway-wide copy while the first is still in STT.
    cut_pending = False

    def __init__(self):
        self.bus = busmod.Bus()
        self.stt = speech.make_stt()
        self.tts = speech.make_tts()
        # ONE DETECTOR FOR THE PROCESS, not one per connection. It holds a loaded model
        # and a lock, it is reset at the start of every listen, and there is only ever
        # one microphone: he is one person with one mouth. The per-connection state
        # (whether this listen is hands-free, and the hangover so far) lives in the
        # socket loop, which is where a connection's state belongs.
        self.vad = vadmod.make_vad()
        self.inbox = SayInbox()
        self.clients: set = set()
        self._clients_lock = threading.Lock()
        # WHETHER EACH PAGE CAN BE SEEN, as it last said (D-2, c-438). Per socket, and a
        # socket with no entry has said nothing, which is an older page: taken as seen,
        # so nothing changes for a page that predates the message.
        self.visible: dict = {}
        # THE LAST TIME ANY CLIENT SAID ANYTHING AT ALL, including a bare ping. The
        # page pings every 25 s, so this is the most direct "is somebody there" signal
        # available: more direct than the connect count alone, because a socket can
        # sit open on a backgrounded phone for a while after the last real message.
        self.last_activity = time.time()
        # live_fn=self.is_live (c-201): the same presence signal the alert loop and the
        # speak-vs-notify decision already trust is what backs the poll off when nobody
        # is there. Constructed after `clients`/`last_activity` exist, even though
        # nothing calls the bound method until Snapshot.start()'s background thread does,
        # well after __init__ returns.
        self.snapshot = snapmod.Snapshot(live_fn=self.is_live)
        # THE CONVERSATION (V2) AND THE HALF SENTENCE IT MAY BE HOLDING (V10). See the
        # class above for both.
        self.talk = Conversation()
        self.dispatcher = Dispatcher(self.snapshot, self.bus,
                                     self.speak, self.inbox, notify=self.notify,
                                     presence=self.is_live,
                                     attending=self.attending,
                                     clients_fn=lambda: len(self.clients),
                                     captured=self.on_captured,
                                     turn_over=self.turn_over,
                                     pin_changed=self.pin_moved,
                                     connect_asked=self.connect_by_model,
                                     leave_asked=self.leave_by_house,
                                     answer_asked=self.answer_by_model)
        # THE PIN'S OWN EXPIRY, ANNOUNCED (V8). One timer, replaced whenever the pin moves,
        # so a conversation he walks away from ends in a sentence rather than in silence.
        self._expiry: threading.Timer | None = None
        self._expiry_card = ""
        self._expiry_lock = threading.Lock()
        # THE REFINE (refine.py): fed by a capture's own hook, drained on its own thread
        # after he has been quiet. It is handed no way to speak (D-3): a capture never
        # asks back by voice, and what it needs from him goes on the card. Built whether
        # or not it is enabled, so `/voice/health` can say it is off rather than nothing.
        self.refiner = refinemod.Refiner(topics=self.topics_for)
        self.started = time.time()

    # -- lifecycle ---------------------------------------------------------- #

    def start(self):
        self.snapshot.start()
        # Warm the weights before the first person speaks. The 120 ms speech number is a
        # WARM number; a cold first turn pays the model load, and paying it at boot is
        # the difference between a service and a script.
        # ONLY IF SOMETHING ACTUALLY WANTS WARMING. With the lookup tier deleted and the
        # filler reading a rendered corpus, nothing in this process holds a model, and a
        # warm loop that runs anyway is the thing that would quietly pull 4.7 GB back
        # into memory five minutes after boot. Starting the gateway must not do that, so
        # the thread is not started rather than started and made to do nothing.
        if self.resident():
            threading.Thread(target=self._warm_filler, name="voice-warm-filler",
                             daemon=True).start()
        threading.Thread(target=self._warm_stt, name="voice-warm-stt",
                         daemon=True).start()
        threading.Thread(target=self._alert_loop, name="voice-alert",
                         daemon=True).start()
        self.refiner.start()
        return self

    def resident(self) -> list:
        """Which components hold a model in memory on this machine, by name.

        The speech model is not in here and that is deliberate: it is 443 MB that was on
        this machine before any of this was designed, because he dictates with it, and it
        is loaded by the STT backend whether or not voice exists. What this reports is
        what VOICE is holding that voice chose to hold, which since 2026-09-04 (and since
        the lookup tier was deleted on 2026-09-18) should be nothing at all.
        """
        return [name for name in [getattr(self.dispatcher.filler, "name", "")]
                if getattr(self.dispatcher.filler, "resident", False) and name]

    def _warm_filler(self):
        """Keep a RESIDENT filler warm, at boot and on a timer.

        Only reached when something actually holds a model, which the shipped corpus
        filler does not: see `start`. Warming only at boot leaves the cost waiting for
        whenever he next picks the phone up after a gap, which is most of the time, and
        without it the first wait of a session pays a prefill inside its budget and falls
        back to the written table.
        """
        while True:
            try:
                warm = getattr(self.dispatcher.filler, "warm", None)
                if warm:
                    warm()
            except Exception:                                           # noqa: BLE001
                pass
            time.sleep(config.FILLER_WARM_EVERY)

    def _warm_stt(self):
        """One silent second through the speech model, so the first real turn is warm.

        Measured: the first transcription after a start took 1210 ms and every one after
        it took about 450 ms, which is the whole of the cold-start cost the warm-up
        exists for.
        """
        try:
            self.stt.transcribe(b"\x00\x00" * config.MIC_RATE, config.MIC_RATE)
        except Exception:                                               # noqa: BLE001
            pass

    def _alert_loop(self):
        """The alert bar, from the same flag the dashboard's badge goes red on.

        Q4 is built as `static_bar`: it is on screen the moment the app opens, it links
        out, it never acts, and it is never SPOKEN unless he asks. So this only ever
        writes a boolean to the bus. Nothing here can make a sound.
        """
        while True:
            try:
                self.bus.set_alert(self.dispatcher.alert())
            except Exception:                                           # noqa: BLE001
                pass
            time.sleep(3.0)

    # -- the page ----------------------------------------------------------- #

    def add_client(self, sock):
        with self._clients_lock:
            self.clients.add(sock)
        self.last_activity = time.time()
        self._log_presence("connect")
        # COME BACK WARM (c-201): the app opening is presence returning, so fetch now
        # rather than waiting out whatever is left of the idle interval. A turn cannot
        # start until he actually speaks, and that is seconds away at the very least, so
        # this one loopback round trip is comfortably done before the snapshot is read.
        self.snapshot.kick()
        # AND COME BACK WITH A WARM JEV CONNECTION (V10, c-313). A fresh connection was
        # about 850 ms against about 350 ms warm, and the judges' budget is 600 ms, so a
        # cold connection is a guaranteed miss on the first call of a conversation. It is
        # opened here rather than on a timer on purpose: a warmer that runs while nobody is
        # there holds a connection to a third party for nothing. Best effort and never
        # awaited; a judge that finds it closed simply opens one inside its own budget.
        threading.Thread(target=judgesmod.CLIENT.warm, name="jev-warm",
                         daemon=True).start()

    def drop_client(self, sock):
        with self._clients_lock:
            self.clients.discard(sock)
            self.visible.pop(sock, None)
        self._log_presence("disconnect")
        # AND WHATEVER THAT PAGE WAS IN THE MIDDLE OF. Here rather than in the socket
        # handler's `finally`, because this is also where a failed send lands: a page
        # that stopped answering is as gone as one that closed, and both must leave the
        # same way.
        try:
            self.client_gone(sock)
        except Exception as exc:                                        # noqa: BLE001
            print(f"voice: a client going away was not tidied up: "
                  f"{exc.__class__.__name__}: {str(exc)[:200]}", flush=True)

    def _log_presence(self, event: str) -> None:
        """Connect and disconnect, timestamped. Section 6 of findings.md: until now
        neither was recorded anywhere, so it was unknowable after the fact whether he
        was still on the line when an answer arrived. Best effort: presence bookkeeping
        must never be the reason a socket handler dies."""
        try:
            self.dispatcher.log_presence(event, len(self.clients))
        except Exception:                                              # noqa: BLE001
            pass

    # The phases of a turn that is still going somewhere (`dispatcher.py`): being routed,
    # handed to Harbor or a house, waited on, spoken, filed, or kept for an answer to come.
    IN_FLIGHT = ("routing", "delivering", "waiting", "speaking", "capturing", "held")

    def busy(self) -> str:
        """What would be cut if this process restarted now, or "" when nothing would
        (c-538, `codewatch.py`): a turn in flight, a voice hold (the pin), a half sentence
        held, a conversation he has open, a capture waiting for its refine, or a Harbor
        turn or a refine holding the conversation's lock in this process."""
        pinned = self.dispatcher.pinned()
        if pinned:
            return f"voice holds {pinned}"
        turn = self.dispatcher.turn
        if turn is not None and turn.phase in self.IN_FLIGHT:
            return f"a turn is {turn.phase}"
        if harbormsg.in_flight() or harbormsg.turn_running():
            return "Harbor's conversation is taking a turn"
        if self.talk.holding():
            return "half a sentence is held"
        if self.talk.open:
            return "a conversation is open"
        if self.refiner.waiting:
            return "a capture waits for its refine"
        return ""

    def is_live(self) -> bool:
        """Is he actually there to hear an answer: connected now, or connected
        recently enough that a brief drop (a lock screen, a tab switch, the phone
        pinging every 25 s) does not read as gone. Findings.md section 5: he leaves
        after a few lines and comes back later, with zero barge-ins across 27 logged
        turns, so "currently on the socket" is the honest signal to gate speech on."""
        if self.clients:
            return True
        return (time.time() - self.last_activity) < config.PRESENCE_RECENT_SECONDS

    def page_presence(self, sock, visible: bool) -> None:
        """A page said whether it can be seen (D-2). Written down, and nothing else.

        A PRESENCE FACT, NOT A COMMAND (V13-G11's rule, for the same reason: this socket
        is the only write path into the agent). It moves no pin, opens no microphone and
        starts no turn; the one thing that reads it is `attending`, which may only hold
        back speech nobody asked for.
        """
        with self._clients_lock:
            # ONLY FOR A SOCKET STILL HERE (review item 8): a late message from a page that
            # has gone must not bring it back as seen.
            if sock not in self.clients:
                return
            self.visible[sock] = bool(visible)
        try:
            self.dispatcher.log_event("presence", visible=bool(visible))
        except Exception:                                              # noqa: BLE001
            pass

    def attending(self) -> bool:
        """Is a page he can SEE open right now: the gate for unprompted speech (D-2).

        `is_live` answers "is a socket open, or was one lately", and a phone with its
        screen off keeps its socket, so the refine, the announce and the pin's expiry
        line were spoken into his pocket (c-438). This is stricter: some connected page
        that has not said it is hidden. It gates only the lines nobody asked for; an
        answer to the question he just asked still goes by `is_live` and, when he is
        gone, the silent path he already has (V9).
        """
        with self._clients_lock:
            return any(self.visible.get(sock, True) for sock in self.clients)

    def notify(self, turn, text: str, reason: str) -> bool:
        """The best this process can do for "he gets a push notification instead of
        audio nobody hears": tell any page that is CURRENTLY OPEN, so it can raise its
        own notification (see app.js). A fully closed app receives nothing from this,
        because there is no push subscription here to reach it with; that gap is real
        and it is named in the return record rather than papered over. What every case
        gets regardless is the text itself, already in the bus and the transcript by
        the time this is called."""
        return self.broadcast({"type": "notice", "text": text, "reason": reason,
                              "turn": turn.id, "generation": turn.generation})

    def broadcast(self, obj):
        with self._clients_lock:
            targets = list(self.clients)
        for sock in targets:
            if not sock.send_json(obj):
                self.drop_client(sock)
        return bool(targets)

    def speak(self, text: str, generation: int,
              spoken: speech.Spoken | None = None) -> dict:
        """Synthesise and stream, dropping everything the moment he moves on.

        THE GENERATION IS CHECKED PER CHUNK, not once at the top. A four-second answer
        cut after half a second must stop within a chunk, and a check at the top would
        play the whole thing to a person who has already asked something else.

        `spoken` IS THIS CALL'S ENGINE AND SPEAKER (V7), handed down from the turn and
        never held here. It RETURNS the chain's report, whose `engines` key names what
        actually spoke: the engine broadcast below is the one that will START, and a
        demotion mid-answer can change it, so the caller records the truth on the turn.
        """
        spoken = spoken if spoken is not None else speech.Spoken()
        head = self.tts.name_for(spoken)
        # WHOSE VOICE GOES ON THE WIRE, NOT WHOSE WORDS (V8 for the field, V13 for the
        # value). The floor is the reason the field exists: when `head` is `browser` the
        # gateway sends no samples at all and the page says the words with its own
        # synthesiser, so the page is the only thing that can pick a voice, and it can only
        # do that if it is told which one.
        #
        # SO IT CARRIES `voice_speaker`'s ANSWER AND NOT THE ROLE. Since V13 there is one
        # voice: Harbor enters and leaves a house rather than handing it the microphone.
        # Sending the role here would have the floor pick a second system voice off it and
        # the persona would hold on every engine except the one without a voice of its own.
        # Whose words they are still reaches the page, on the TURN, which is what the
        # header and the transcript read.
        self.broadcast({"type": "speak", "text": text, "generation": generation,
                        "engine": head,
                        "speaker": config.voice_speaker(spoken.speaker)})
        self.bus.set_speech(head)
        if head == "browser":
            # Nothing to stream: the page says it with its own synthesiser. Told rather
            # than muted, which is the whole point of the chain having a floor.
            return {"unspoken": text, "engines": ["browser"]}
        self.bus.set_state("speaking")
        heard = False
        failed = False
        # PER CALL, NOT ON THE CHAIN. The chain is shared by every turn, and two
        # overlapping speak calls (a barge-in, an answer arriving while a filler is
        # still going out) would otherwise read each other's leftovers. Same lesson
        # dispatcher._route paid for when it stopped stashing its refusal on `self`.
        report: dict = {}
        try:
            for chunk in self.tts.synthesize(text, report, spoken):
                if generation != self.dispatcher.generation:
                    break
                for i in range(0, len(chunk), OUT_CHUNK):
                    part = chunk[i:i + OUT_CHUNK]
                    if generation != self.dispatcher.generation:
                        break
                    heard = True
                    # WHEN THE FIRST CHUNK LEFT (D-5), for `keel voice latency`.
                    report.setdefault("firstAudioAt", time.time())
                    self.bus.feed_waveform(speech.pcm_to_floats(part))
                    self._send_audio(part, generation)
        except Exception as exc:                                        # noqa: BLE001
            failed = True
            self.broadcast({"type": "error", "where": "tts",
                            "what": f"{exc.__class__.__name__}", "text": text})
        finally:
            if generation == self.dispatcher.generation:
                self.bus.set_state("idle")
        # THE ANSWER IS NEVER SILENT, and the check has to be here rather than at the
        # top. The chain demotes an engine WHILE it is speaking, so a turn can begin on
        # a hosted voice and end with every engine above `browser` demoted; the message
        # broadcast at the top named an engine that has since stopped answering, and a
        # page told "google is speaking" that then receives no samples plays nothing at
        # all. Told again, so the page says it itself.
        #
        # AND THE TAIL IS HANDED OVER RATHER THAN DROPPED. The first version of this only
        # spoke again when NO sample had been sent, on the reasoning that repeating an
        # answer he has half heard is worse than the silence. That reasoning was about
        # the wrong half: the part he has not heard is the part that vanishes, so what
        # the page is given is exactly what was left (`chain.unspoken`), and the whole
        # answer only when nothing was spoken at all. Raised by review, 2026-09-04.
        # AND ONE FRAME PER FAILURE. When synthesize raises before anything is heard the
        # `except` above has already said so, and the block below would have said it
        # again in different words: two error frames on the page for one failure, which
        # is a bug he can see. Raised by review, 2026-09-04.
        left = str(report.get("unspoken") or "")
        if generation == self.dispatcher.generation and (left or not heard):
            say = left if heard else text
            if say and self.tts.name_for(spoken) == "browser":
                # THE FLOOR IS NEVER SUPPRESSED, and the first version of this dedupe
                # closed it. `failed` was meant to stop one failure producing two error
                # frames; it also stopped the page being told to speak, so a raise from
                # outside the per-engine try blocks (the cache read, the splitter) while
                # the chain had fallen to `browser` left the answer silent, and the
                # page's error handler renders only where and what, never the text. The
                # dedupe belongs on the error branch alone. Raised by review, 2026-09-04.
                self.broadcast({"type": "speak", "text": say, "generation": generation,
                                "engine": "browser",
                                "speaker": config.voice_speaker(spoken.speaker)})
                self.bus.set_speech("browser")
            elif say and not failed:
                # Something below the floor is up again, or never went down; either way
                # the tail was not spoken and nothing said so.
                self.broadcast({"type": "error", "where": "tts",
                                "what": "the rest of this answer was not spoken",
                                "text": say})
        return report

    def _send_audio(self, pcm: bytes, generation: int) -> None:
        # Four bytes of generation in front of the samples, so the page can drop a chunk
        # from a turn it has already abandoned without parsing any audio.
        header = generation.to_bytes(4, "big")
        with self._clients_lock:
            targets = list(self.clients)
        for sock in targets:
            if not sock.send_binary(header + pcm):
                self.drop_client(sock)

    def hear(self, endpointer, pcm: bytes) -> bool:
        """One chunk of his audio through the detector. True once, when he has stopped.

        THE DETECTOR MUST NEVER HEAR THE GATEWAY, and this is where that is enforced.
        There is no event in this package that says "speech started": there is only the
        bus state, set to `speaking` in `speak` and back to `idle` at its `finally`. So
        the gate is that state, read in process (bus.state), and while it says `speaking`
        the endpointer is RESET rather than merely paused. Reset is the stronger claim
        and it is the one the brief asked for: after the gateway stops talking, fresh
        speech has to arrive before any hangover can run, so no part of a hangover can
        ever have been built out of the gateway's own voice coming back through the
        microphone.

        The browser's own `echoCancellation: true` (app.js) stays the first line of
        defence. This is the second, not the only one.

        NEVER RAISES, AND THE WHOLE PATH IS INSIDE THE GUARD. A detector that could throw
        inside the socket's read loop would take the connection down and with it the turn
        he is in the middle of speaking. The first cut of this had the arithmetic and the
        `feed` call OUTSIDE the try, so the promise held in practice (neither of them can
        realistically raise) but not in structure, which is not the same thing and is not
        what the comment said. Caught by review, 2026-09-20.

        A FAILURE DISARMS THE LISTEN RATHER THAN REPEATING ITSELF. This is called once per
        audio chunk, roughly every 32 ms, so a detector that raises on every frame would
        write a log line thirty times a second for as long as he kept talking. The
        endpointer is marked failed, which makes it return False from then on, and the
        reason is logged once. The next listen resets it and tries again, because whatever
        went wrong may have been one frame; and a disarmed listen is not a broken turn, it
        is a turn that ends the way it did before this card, on the page's own backstop.
        """
        if endpointer.failed:
            return False
        try:
            if self.bus.state == "speaking":
                endpointer.reset()
                self.vad.reset()
                return False
            speech_now = self.vad.is_speech(pcm)
            # The frame is the chunk the page actually sent, so the hangover is measured
            # in real audio seconds rather than in however many bytes a worklet batched up.
            seconds = len(pcm) / 2 / config.MIC_RATE
            return endpointer.feed(speech_now, seconds)
        except Exception as exc:                                        # noqa: BLE001
            endpointer.failed = True
            print(f"voice: the end-of-utterance detector failed and is off for this "
                  f"listen: {exc.__class__.__name__}: {str(exc)[:200]}", flush=True)
            return False

    # -- the conversation, and the half sentence it may be holding ----------- #

    def set_conversation(self, open_: bool, sock=None) -> None:
        """Whether another utterance is expected after this turn, and whose it is.

        Told by the page on every `start` and cleared on a pause or a socket that went
        away, so there is no state here to get out of step with the page: the answer is
        never older than the last thing he did.

        ONLY THE OWNER MAY CLOSE IT. A `pause` from the desk tab while he is talking on
        the phone would otherwise end the phone's conversation. A call with no socket is
        the gateway's own doing ("that's all", and the tests), and that may always close.
        """
        if open_:
            self.talk.open = True
            self.talk.owner = sock
            return
        if sock is None or self.talk.owner is None or self.talk.owner is sock:
            self.talk.open = False
            self.talk.owner = None

    def outcome(self, turn_id: str, what: str) -> None:
        """What then happened, which is the column that says who was right.

        V10's own four, and each is written where it is KNOWN rather than where it would
        be convenient: `carried-on` when a held half sentence got the rest of itself
        (`on_text`), `abandoned` when it expired instead, `barged-in` when he pressed
        over an answer, and `answered` when a turn finished. Without these the shadow log
        has calls and no verdicts about the calls, and the report it exists to produce
        cannot be read.

        NEVER A FAILED TURN. A log line that cannot be written is not worth one.
        """
        if not turn_id:
            return
        try:
            judgesmod.outcome(turn_id, what)
        except Exception:                                               # noqa: BLE001
            pass

    def barged_in(self) -> None:
        """He pressed over an answer: the outcome line for the turn he cut."""
        turn = self.dispatcher.turn
        if turn is not None and self.bus.state == "speaking":
            self.outcome(turn.id, "barged-in")
            self.cut_pending = True

    def tell(self, sock, obj) -> None:
        """Say something to ONE page, or to every page when there is no one page.

        The conversation's own messages (`listen`, `partial`, `conversation`) are about
        one page's microphone, so they go to that page. Broadcasting them would tell a
        second open tab to arm a microphone nobody is talking into. A `None` socket means
        the gateway does not know which page it is (a `{"type":"text"}` line, or a test),
        and then every page is the honest answer.
        """
        if sock is None:
            self.broadcast(obj)
            return
        if not sock.send_json(obj):
            self.drop_client(sock)

    def client_gone(self, sock) -> None:
        """A page went away: a closed tab, a lost network, a crash.

        THE CONVERSATION GOES WITH IT, which the Atlas has always said and the code did
        not do. Before this, only an explicit `pause` cleared the flag, so a killed tab
        left `Conversation.open` true and a held partial's timer running, and that timer
        would later dispatch: a real Harbor turn, or a card on the board, for a client
        that is gone.

        ONLY ITS OWN. A second page closing is not this page's business: `set_conversation`
        and `take_if_owned` both check the socket, so the desk tab closing cannot end the
        conversation he is having on the phone.

        AND HIS WORDS ARE NOT THROWN AWAY. A held half sentence is his and he did say it,
        so it is kept; what it must not become is a Harbor turn nobody will hear. In
        CAPTURE it is filed, because a capture needs no listener and losing a dictated
        idea is the thing capture exists to prevent. In TALK it becomes a quiet turn: the
        transcript line is kept, no Harbor turn is spent, and nothing is spoken into an
        empty room. Either way the judge's call line gets its `abandoned` outcome, which
        is exactly what happened to it.
        """
        self.set_conversation(False, sock)
        held = self.talk.take_if_owned(sock)
        if held is None:
            return
        self.outcome(held.get("turn_id", ""), "abandoned")
        fields = {k: v for k, v in held.items() if k not in ("said", "at", "sock")}
        if fields.get("mode") == config.MODE_CAPTURE:
            self.dispatch(held["said"], **fields)
            return
        self.dispatcher.quiet(held["said"], heard=fields.get("repairs"),
                              pcm=fields.get("pcm", ""), engine=fields.get("engine", ""),
                              turn_id=fields.get("turn_id", ""),
                              why="the page went away")

    def turn_over(self, turn) -> None:
        """A turn is really over. Reopen the microphone if a conversation is open.

        THIS IS THE ONE PLACE THE MICROPHONE REOPENS BY ITSELF, and it is the gateway's
        rather than the page's because only this side knows the turn has ended: the page
        polls the bus and is up to one poll behind, which cannot tell a gap between two
        audio chunks from the end of an answer.

        IT IS A TURN ENDING, NOT A SPEECH ENDING. `speak` runs for narration lines and
        fillers too, and re-arming on one of those would open the microphone while
        Harbor was still thinking. The dispatcher calls this from the two places a turn
        finishes, which is why the hook is there rather than here.

        THE PAGE STILL DECIDES WHETHER TO OBEY. It knows whether it is paused, whether a
        microphone will open, and how many listens in a row have heard nothing, and it
        drops this on the floor in all three cases.
        """
        # WHAT THIS TURN WAS. A turn that ended quietly (an `addressed: no` verdict, or
        # the words that close a conversation) was not answered, and the report is read
        # to decide a flip, so the two must not look the same in it.
        self.outcome(getattr(turn, "id", ""),
                     "ended-quietly" if getattr(turn, "tier", "") == QUIET else "answered")
        if not self.talk.open:
            return
        self.tell(self.talk.owner, {"type": "listen", "reason": "conversation",
                                    "generation": self.dispatcher.generation,
                                    "turn": getattr(turn, "id", "")})

    def hold_partial(self, said: str, **fields) -> None:
        """Hold half a sentence, ask for the rest, and expire into an ordinary turn.

        V10's `complete: no`: the thought was not finished, so nothing is dispatched, the
        microphone reopens, and the next utterance is joined to this one before anything
        is asked. It is entered only when that answer is `on`, which ships `shadow`, or
        by the fake judge in a test.

        THE MODE AND THE SPACE ARE THE ONES IT WAS SPOKEN IN, and they are kept here
        rather than read again later. He may switch the toggle while the partial is
        held, or pause and come back; a half sentence dictated into Capture must not
        become a question to Harbor because a toggle moved between its two halves.

        IT EXPIRES RATHER THAN WAITING FOR EVER. `config.JUDGE_HOLD_SECONDS` of nothing
        and the held text is dispatched as the ordinary turn it would have been, which
        is what makes a wrong verdict cost a pause and never a sentence.
        """
        self.talk.hold(said, self._expire_partial, **fields)
        sock = fields.get("sock")
        self.tell(sock, {"type": "partial", "state": "held"})
        self.tell(sock, {"type": "listen", "reason": "partial",
                         "generation": self.dispatcher.generation})

    # -- connected to one card's house (V4) --------------------------------- #

    def connect_to(self, card: str, sock=None, spoken: bool = False) -> bool:
        """Take Harbor into a card's house, hold it, and SAY SO (V4, V8, V13).

        `keel converse --connect` owns everything that can go wrong (no such card, a house
        that is building, a machine short of memory, the other machine away) and answers in
        a sentence, so this method decides nothing: it pins on ok and speaks the refusal
        otherwise. A card whose house is on the OTHER machine is not one of those since V12
        slice 2: the conversation is carried over that machine's door, and the only refusal
        left about it is that the machine cannot be reached.

        THE TWO SPOKEN MOMENTS ON THE WAY IN, and the real wait between them. Line 1 lands
        AT ONCE, because it exists to cover a wait that is about to happen: it is a
        pre-rendered clip and it names no card, since a clip cannot be rendered per card
        and a live synthesis is the one thing that cannot promise to be immediate. Line 2
        is "Entering card 272, <a few words of its title>", synthesised while he waits.

        BOTH ARE HARBOR'S, AND SO IS EVERYTHING AFTER THEM (V13). V8 made line 2 the
        house's own voice; his decision on 2026-09-21 is that Harbor ENTERS the house
        instead, keeping one voice throughout, and that the line says where it is rather
        than who it is. `turn.speaker` still records whose words an answer is, for the page
        and the transcript.

        EVERY REFUSAL TAKES NO PIN AND SAYS WHAT IT COULD NOT DO. He must never be left
        unsure whether the switch happened, so the verb's reason is framed with the act it
        refused ("I cannot enter card 419: it is building right now"): the reason alone
        left him working out which side of the door he was on. There is no tone either,
        because the tone means it DID happen.
        """
        card = str(card or "").strip()
        if not card:
            return False
        # LINE 1, BEFORE THE CALL THAT TAKES THE TIME, not after it.
        if spoken:
            self.say_line(corpus.CONNECTING)
        done = threading.Event()
        threading.Thread(target=self._still_connecting, args=(done, spoken),
                         name="voice-connect-nag", daemon=True).start()
        try:
            result = connected.connect(card)
        finally:
            done.set()
        if not result.get("ok"):
            self.tell(sock, {"type": "connected", "card": None, "why": result.get("say")})
            self.say_line(verbs.cannot_enter(card, result.get("say") or ""))
            return False
        self.dispatcher.pin_to(card, self.dispatcher.hold_seconds(result.get("held_until")),
                               str(result.get("title") or ""),
                               str(result.get("space") or ""))
        self.broadcast({"type": "connected", "card": card,
                        "title": result.get("title") or "",
                        "space": result.get("space") or "",
                        "stage": result.get("stage") or ""})
        # LINE 2, BEHIND THE TONE. Said however the pin was taken, by phrase or by the
        # deck's button: "where am I now" is the question this answers, and a tap does not
        # answer it any better than a sentence does.
        self.say_line(verbs.entering(card, str(result.get("title") or "")), tone=True)
        # AND ONLY NOW MAY THE PAGE LISTEN AGAIN (V13, fix 1). `say_line` returns when the
        # audio has been streamed, so this lands after the words rather than under them:
        # on 2026-09-21 the page sat "listening" for sixty-two seconds after a connect with
        # no audio reaching this end at all, and neither end had anything to re-arm on.
        self.rearm(sock, "connected")
        return True

    def connect_by_model(self, card: str) -> bool:
        """The pin Harbor asked for at the end of its answer (c-419).

        THE SAME CALL THE SPOKEN PHRASE MAKES, with `spoken=True`, and that is the whole
        point of routing it through here rather than building a second connect: the guards
        are `keel converse`'s (mid-work refused with his question left on the card, archived
        refused, no session refused with the offer to start it, a machine short of memory or
        away refused, a done card read-only), the refusal is Harbor's own sentence with no
        tone and no pin, and the handoff is heard exactly as it is when he says a card id out
        loud.

        `spoken=True` BECAUSE HE ASKED OUT LOUD. He said "put me through to the house doing
        the voice thing"; that the id was worked out by a model rather than by the phrase
        table changes nothing about what he is owed, which is line 1 over the wait and line
        2 in the house's voice at the end of it.

        IT RUNS ON THE WATCH THREAD, whose turn is already finished. The connect blocks for
        about a second on the board and the nag line has a thread of its own, so there is
        nothing here to hand off to another one, and a thread started here would be a second
        connect racing the one the header already shows.
        """
        return self.connect_to(card, spoken=True)

    def answer_by_model(self, ask: str, letter: str, words: str) -> bool:
        """His answer to one of Bosun's asks, handed to the PAGE to record (c-523, BO-5).

        THE GATEWAY NEVER RECORDS IT, because recording is his and the gateway holds no
        token. The page is him on the deck: it posts the Console's own answer with `voice:
        true`, the deck runs `kb console answer --actor voice` with its token, and the ask
        says it was answered by voice. `words` is his sentence verbatim. Every page gets it
        and the first to post records it; a second is refused by the ask being closed.
        False when no page is open to record it, which the turn's log says."""
        return self.broadcast({"type": "answer", "ask": ask, "choice": letter,
                               "words": words})

    def leave_by_house(self) -> None:
        """The conversation the HOUSE was asked to end (2026-09-21).

        THE SAME CALL THE SPOKEN PHRASE MAKES, `disconnect(spoken=True)`, and that is the
        whole point of routing it through here rather than building a second release: the
        hold goes back through `keel converse --release`, the house is woken, the one
        leaving line names the card, the tone plays and the page is invited to listen
        again. Nothing about the way out is duplicated for it.

        `spoken=True` BECAUSE HE ASKED OUT LOUD. He said "Okay, you can exit the pouse
        now"; that the words reached the house instead of the gateway's own matcher changes
        nothing about what he is owed, which is the line, the tone and an open microphone.

        NO SOCKET, SO THE RE-ARM GOES TO EVERY PAGE. This runs on the watch thread, whose
        turn is already finished, and the turn machine holds no socket; `tell(None, ...)` is
        a broadcast, which is the honest answer when the gateway does not know which page
        it is (the same thing a `{"type": "text"}` line gets).
        """
        self.disconnect(spoken=True)

    def _still_connecting(self, done: threading.Event, spoken: bool) -> None:
        """One "still connecting", and never a second one.

        IT IS A WAIT AND NOT A TIMER ON THE TURN. `done.wait` returns the moment the verb
        comes back, so the line is said only when the connect really is slow; a second
        machine filling silence is the thing the filler corpus exists to avoid doing badly,
        and this is the same rule one layer up.
        """
        if not spoken or done.wait(CONNECT_SLOW_SECONDS) or done.is_set():
            return
        self.say_line(corpus.STILL_CONNECTING)

    def disconnect(self, sock=None, spoken: bool = False, expired: bool = False) -> None:
        """Leave the house: drop the pin, let it go (it is woken, no tokens), and say so.

        ONE SPOKEN MOMENT ON THE WAY OUT, NOT TWO (V13). V8 had the house hand the
        microphone over and then Harbor take it, which is two lines because it was two
        speakers. Harbor leaves a house now, so there is one thing happening and one line
        for it: "Leaving card 272. Back with you.", behind the tone. It is said however he
        asked, by phrase or by the tap on the header, because the question it answers is
        "did the switch happen" and that does not depend on how he asked for it.

        AN EXPIRY NAMES NOTHING. The hold ran out while he was quiet, so nobody asked, and
        the egress split holds unprompted speech to naming no card, which
        `corpus.LEFT_HOUSE` does by construction. The release is left to the drain in that
        case, which is the thing that owns an expired hold; announcing it here and
        releasing it there is not a split of one job but two different jobs that happen at
        the same moment.

        AND AN EXPIRY RE-ARMS NOTHING EITHER (V13, and it is the one place the re-arm does
        not follow the line). A hold runs out because he said nothing for the whole of it,
        so he has walked away: opening a microphone then is a microphone in his pocket. The
        page's own quiet cap would close it a minute later, which is a reason it is not a
        disaster and not a reason to open it. The re-arm goes only after a switch HE ASKED
        FOR, by phrase or by the tap on the header.
        """
        card = self.dispatcher.unpin()
        self.broadcast({"type": "connected", "card": None})
        if card and not expired:
            connected.release(card)
        # SAID EVEN WHEN THERE WAS NO PIN TO DROP, if he asked out loud: answering "back to
        # Harbor" with silence is the one outcome V8 rules out, and a tap on a header that
        # is already gone is not a question.
        if card and not expired:
            self.say_line(verbs.leaving(card), tone=True)
        elif spoken or (card and self.attending()):
            # AN EXPIRY IS UNPROMPTED, so it is said only to a page he can see (D-2);
            # the pin is dropped either way.
            self.say_line(corpus.LEFT_HOUSE, tone=True)
        if (card or spoken) and not expired:
            # THE MICROPHONE MAY OPEN AGAIN, once the words are done and only for a release
            # HE ASKED FOR (V13, fix 1). An expiry is the one release nobody asked for, and
            # it happens because he stopped talking for the whole length of the hold.
            self.rearm(sock, "released")

    def pin_moved(self, state: dict | None) -> None:
        """The pin was taken, extended or dropped: re-arm the expiry announcement (V8).

        WHY THERE IS A TIMER AT ALL. The pin is dropped LAZILY, when something next asks
        whether it is still pinned, so a conversation he walks away from would end without a
        word: the header would clear at his next utterance and the voice would be Harbor's
        again with nothing having said so. This is the one thing in this package that speaks
        on a clock rather than on an event, and it is bounded to exactly one sentence.

        IT IS PROCESS STATE AND A RESTART FORGETS IT, which is the right way round: the
        board's hold expires on its own clock and the drain wakes the house either way, so
        the worst case is a missing announcement and never a stuck house.
        """
        with self._expiry_lock:
            if self._expiry is not None:
                self._expiry.cancel()
                self._expiry = None
            until = (state or {}).get("until")
            self._expiry_card = str((state or {}).get("card") or "") if until else ""
            if not until:
                return
            self._expiry = threading.Timer(max(0.0, until - time.time()) + 0.5,
                                           self.expire_pin)
            self._expiry.daemon = True
            self._expiry.start()

    def expire_pin(self) -> None:
        """The hold ran out while he was quiet: say so, once.

        THE TIMER FIRING IS ITSELF THE ANSWER, and this does not re-read the pin to find
        out. `pin_moved` cancels this timer on every other way a pin can end (a phrase, a
        tap, a turn that took the hold away), so a timer that survives to fire can only
        mean the hold ran out. That matters because the pin is dropped LAZILY, inside
        `Dispatcher.pinned`, so anything that merely ASKED whether he was still connected
        between the expiry and this timer would have cleared it, and a check for "is there
        still a pin" would then say nothing at the one moment it exists to speak.

        THE ONE RACE IT DOES CHECK is the other way round: a connected turn extends the
        hold, and the extension can land in the instant between this timer firing and this
        line. `pin_moved` has already armed the next one by then, so the right thing here
        is to say nothing.
        """
        try:
            with self._expiry_lock:
                self._expiry = None
                card, self._expiry_card = self._expiry_card, ""
            pin = self.dispatcher.pin or {}
            if pin.get("until") and time.time() < pin["until"]:
                return
            if card:
                self.disconnect(expired=True)
        except Exception as exc:                                        # noqa: BLE001
            print(f"voice: the pin expired and could not be announced: "
                  f"{exc.__class__.__name__}", flush=True)

    def rearm(self, sock=None, reason: str = "") -> None:
        """Tell the page it may press its own orb again, once the gateway has stopped
        speaking (V13, fix 1).

        WHAT THIS IS FOR, and it is his own conversation of 2026-09-21. A connect finished
        at 03:47:12, the page showed "listening" for sixty-two seconds, and not one frame
        of audio reached this end before he gave up and pressed the orb himself at
        03:48:15. Nothing re-armed a microphone after a switch, because a switch is not a
        turn and `turn_over` is the only other thing that re-arms.

        IT IS AN INVITATION AND NOT A COMMAND, exactly as `listen` is. The page knows
        whether it is paused, whether it is already holding, and whether a microphone will
        open at all, and it drops this on the floor in all three cases. This end owes the
        message and nothing else.

        SENT AFTER THE WORDS, NEVER UNDER THEM. `say_line` returns when the audio has been
        streamed, so calling this next is what keeps the page from opening a microphone
        into the tail of the gateway's own voice.
        """
        self.dispatcher.log_event("listen-now", reason=reason)
        self.tell(sock, {"type": "listen-now", "reason": reason,
                         "generation": self.dispatcher.generation})

    def say_line(self, text: str, speaker: str = config.SPEAKER_HARBOR,
                 tone: bool = False) -> None:
        """Speak one fixed sentence, outside any turn, optionally behind the switch tone.

        NEVER LETS SPEECH COST THE PIN: a synthesiser that fails here must not leave him
        connected to something the page says he is not, so everything is inside one try.

        THE TONE GOES FIRST AND IT GOES WHOLE. It is queued on the same audio channel as the
        speech, so on every engine that streams samples the page plays them in the order
        they arrived and the sequencing is the queue's. The floor is the case that needs
        saying out loud: there the gateway sends no speech samples at all and the page says
        the words with its own synthesiser, so the page delays that utterance until the
        queued tone has finished (`speakHere` in app.js). Without that the tone and the
        words would come out of two different players at once.
        """
        if not text and not tone:
            return
        generation = self.dispatcher.generation
        try:
            if tone:
                # `speaking` IS SET HERE AND CLEARED BY `speak`, so the tone and the line
                # it introduces are one speaking window. Clearing it between them would
                # open a gap, however small, in the one thing that stops the endpointer
                # hearing the gateway (`hear`, below), and the tone is exactly the kind of
                # sound a detector would take for the start of an utterance.
                self.bus.set_state("speaking")
                self._send_tone(generation)
            if text:
                self.speak(text, generation, speech.Spoken(speaker=speaker))
            elif tone and generation == self.dispatcher.generation:
                self.bus.set_state("idle")
        except Exception as exc:                                        # noqa: BLE001
            print(f"voice: could not speak the switch line: {exc.__class__.__name__}",
                  flush=True)
            if generation == self.dispatcher.generation:
                self.bus.set_state("idle")

    def _send_tone(self, generation: int) -> None:
        """The switch, as sound, down the speech channel (V8; one tone since V13).

        THE CALLER OWNS THE `speaking` STATE, not this method: `say_line` sets it before the
        tone and `speak` clears it after the line, so the two are one window. That state is
        the one thing stopping the endpointer hearing the gateway (`hear`, below), and a
        tone is exactly the kind of sound a detector would take for the start of an
        utterance.
        """
        pcm = speech.tone_pcm()
        for i in range(0, len(pcm), OUT_CHUNK):
            if generation != self.dispatcher.generation:
                return
            part = pcm[i:i + OUT_CHUNK]
            self.bus.feed_waveform(speech.pcm_to_floats(part))
            self._send_audio(part, generation)

    def take_partial(self) -> dict | None:
        """The held half, if there is one, and it is taken rather than read."""
        return self.talk.take()

    def release_partial(self, why: str) -> None:
        """Let a held half go as an ordinary turn. Never silently dropped.

        A pause, an expiry and a socket that went away all arrive here, because all
        three mean the rest of the sentence is not coming. What he said is dispatched
        under the mode and the space he said it in, so the cost of a wrong verdict is
        still a pause.
        """
        held = self.take_partial()
        if held is None:
            return
        self.tell(held.get("sock"), {"type": "partial", "state": "expired", "why": why})
        # THE REST NEVER CAME. That is the outcome for the call that held it, and it is
        # the one that says the verdict was wrong.
        self.outcome(held.get("turn_id", ""), "abandoned")
        self.dispatch(held["said"], **{k: v for k, v in held.items()
                                       if k not in ("said", "at", "sock")})

    def _expire_partial(self) -> None:
        self.release_partial("expired")

    # -- a turn -------------------------------------------------------------- #

    def topics_for(self, space: str) -> list:
        """The topics that space's cards actually use, for the refine to pick from."""
        return list(((self.snapshot.doc.get("topics") or {}).get(space or "") or []))

    def on_captured(self, turn, card: dict) -> None:
        """A capture landed: tell the page which card it became, now rather than at its
        next poll, and queue it for the refine. The id is drawn under the turn and never
        spoken. Neither of these may ever cost the capture, which is why this runs after
        the card exists and inside the dispatcher's own guard."""
        self.broadcast({"type": "captured", "id": card.get("id"),
                        "space": card.get("space"), "turn": turn.id,
                        "generation": turn.generation})
        self.refiner.add(str(card.get("id") or ""), turn.said,
                         str(card.get("space") or ""))

    def on_utterance(self, pcm: bytes, sock, mode: str = "", space: str = "",
                     released_at: float | None = None, engine: str = "",
                     hands_free: bool = False) -> None:
        """He let go of the button. Transcribe, then answer or capture.

        An empty or unreadable transcript is NOT answered and is not guessed at. The
        design's fourth ambiguity case says to say it back as a question; V1 does the
        honest half of that, which is to tell the page it heard nothing, because a
        read-back that mishears twice is worse than one that says so once.
        """
        # THE CORPUS, BEFORE THE TRANSCRIPT AND OFF BY DEFAULT (record.py). Written
        # here because this is the only place in the package that ever holds a whole
        # utterance: `transcribe` is handed these bytes and they are dropped straight
        # after, which is why there was nothing to measure a hangover against until now.
        # Best effort and swallowed: a recorder must never cost him an answer.
        pcm_ref = record.write(pcm, record.new_id()) if config.RECORD_ENABLED else ""
        try:
            said = self.stt.transcribe(pcm, config.MIC_RATE)
        except Exception as exc:                                        # noqa: BLE001
            sock.send_json({"type": "error", "where": "stt",
                            "what": str(exc)[:200]})
            self.bus.set_state("idle")
            return
        said = " ".join(str(said or "").split())
        if not said:
            sock.send_json({"type": "error", "where": "stt",
                            "what": "nothing was heard"})
            self.bus.set_state("idle")
            return
        # SPEECH ONLY, NEVER TYPED TEXT. hearing.repair fixes words the speech model is
        # measured to get wrong on this product's own vocabulary ("Harper" for "Harbor",
        # which cost a 29-second Harbor round trip on 2026-09-03). Typed text is exactly
        # what was meant, so on_text does not go through this: a table that "corrects" a
        # person's own typing is changing their words.
        said, repairs = hearing.repair(said)
        # `sock` RIDES WITH IT, so the conversation and any half sentence it holds know
        # which page they belong to: two pages can be open at once, and a page that goes
        # away must take its own conversation with it and nobody else's.
        self.on_text(said, repairs, mode=mode, space=space, released_at=released_at,
                     pcm=pcm_ref, engine=engine, sock=sock, hands_free=hands_free)

    def on_typed(self, msg: dict) -> None:
        """A line typed on the voice page: a TYPED turn, answered in text only (VP-3).

        His decision of 2026-09-24: the page is a chat you can also talk to, and a turn he
        typed is read, not heard, so nothing of it is spoken, inside a Conversation too.
        The flag rides on the turn from here to the one place a turn becomes sound
        (`Dispatcher._say`). `aloud` is the one way a typed line asks to be heard: the
        desk's `r` key, which types "say that again" on his behalf.
        """
        self.on_text(str(msg.get("text") or ""), mode=str(msg.get("mode") or ""),
                     space=str(msg.get("space") or ""),
                     engine=str(msg.get("engine") or ""),
                     typed=not bool(msg.get("aloud")))

    def on_text(self, said: str, repairs=None, mode: str = "", space: str = "",
                released_at: float | None = None, pcm: str = "",
                engine: str = "", sock=None, typed: bool = False,
                hands_free: bool = False) -> None:
        # THE REPAIRS RIDE ON THE TRANSCRIPT MESSAGE the page already handles, rather
        # than on a message type of their own. A {"type": "heard"} broadcast was tried
        # and the page dropped it silently, because app.js switches on msg.type and knew
        # only transcript, speak and error: the table's safety argument is that its
        # mistakes are visible, and an unhandled message type is the opposite of that.
        # Caught by review, 2026-09-04.
        said = " ".join(str(said or "").split())
        if not said:
            return
        mode = config.normal_mode(mode)
        self.broadcast({"type": "transcript", "text": said, "mode": mode,
                        "generation": self.dispatcher.generation + 1,
                        "repairs": [{"heard": a, "readAs": b} for a, b in (repairs or [])],
                        "typed": bool(typed)})
        # THE ORDER HERE IS THE WHOLE OF THIS CARD'S SERVER HALF, and every step of it
        # happens before anything is dispatched.
        #
        # THE ID IS MINTED FIRST (c-324), because the judge is asked before the turn
        # exists and its shadow-log line has to name the turn that then ran.
        turn_id = new_turn_id()
        # THE FIRST UTTERANCE AFTER A CUT, whatever it turns out to be (c-552): taken here,
        # before any branch can consume the utterance, so a typed line or a connect phrase
        # in between spends it rather than leaving it for a later turn.
        cut = getattr(self, "cut_pending", False)
        if cut:
            self.cut_pending = False
        # A HELD HALF SENTENCE IS JOINED BEFORE THE JUDGE IS ASKED (V10). The judge is
        # then asked about the whole thought rather than about its second half, which is
        # the only way `complete` can be true of it. The join is the two utterances in
        # the order they were spoken, under the mode and the space of the FIRST one,
        # because that is the sentence he started: a half dictated into Capture stays a
        # capture even if the toggle moved while it was held (his risk 5).
        held = self.take_partial()
        joined = held is not None
        if joined:
            self.broadcast({"type": "partial", "state": "joined"})
            said = (held["said"] + " " + said).strip()
            mode = held.get("mode") or mode
            space = held.get("space") or space
            pcm = held.get("pcm") or pcm
            # WHO WAS RIGHT, and this is the line that says so: he carried on speaking,
            # which is exactly what a `complete: no` verdict predicted.
            self.outcome(held.get("turn_id", ""), "carried-on")
        # V10'S `preturn` SEAT (c-324), and this is the whole of where it sits: after the
        # transcript exists and before a Harbor turn is spent. It is after V1's
        # end-of-utterance detector and never replaces it.
        #
        # SPOKEN ONLY. `released_at` is set by the socket for a real utterance and never
        # for the typed box, and V10's words are "after the transcript exists": a typed
        # line has no transcript, `complete` and `addressed` are trivially true for it,
        # and counting them would flatter the very agreement figure the shadow log is
        # kept to produce.
        # THE CONNECT WORDS ARE MATCHED BEFORE THE SEAT (V4), for the same reason the
        # conversation words are matched before dispatch: they are not a question, and the
        # exact-phrase table plus a card id is the whole of how they are recognised. A
        # judge never sees them, so no verdict of any kind can move them.
        if released_at is not None and mode != config.MODE_CAPTURE:
            target = verbs.connect_target(said)
            if target:
                self.dispatcher.quiet(said, heard=repairs, pcm=pcm, engine=engine,
                                      turn_id=turn_id, why=f"connecting to {target}")
                self.connect_to(target, sock=sock, spoken=True)
                return
            # THE LEAVING WORDS ARE READ LENIENTLY, AND ONLY WHILE HE IS PINNED
            # (2026-09-21). `verbs.leave_intent` is the exact table plus the wrappers a
            # person really puts round it ("Okay, you can exit the pouse now"), asked here
            # where the table was asked, so a leave still costs no turn and no judge ever
            # sees it. While pinned it also takes "that's all" out of the end-of-
            # conversation branch below, deliberately: coming out of the house is the
            # narrower act, and saying it again closes the conversation.
            if verbs.leave_intent(said) and self.dispatcher.pinned():
                self.dispatcher.quiet(said, heard=repairs, pcm=pcm, engine=engine,
                                      turn_id=turn_id, why="back to Harbor")
                self.disconnect(sock=sock, spoken=True)
                return
        ruling = None
        route = ""
        if released_at is not None:
            ruling = self._preturn(said, mode, turn_id, space=space, cut=cut,
                                   hands_free=hands_free)
        # THE TWO CONVERSATION WORDS (V2, V3), matched after the judge has seen the
        # utterance (it costs the turn nothing and the log wants every line) and before
        # anything is dispatched. "that's all" closes a conversation and "hold on" pauses
        # it, and neither is a question: matching them here is what stops the words that
        # end a conversation costing a Harbor turn. The tables are whole utterances in
        # `verbs.py`, matched the way the one board question is, so nothing that merely
        # contains the words can trip them.
        if released_at is not None and verbs.is_end_of_conversation(said):
            self.set_conversation(False, sock)
            self.tell(sock, {"type": "conversation", "state": "closed",
                             "why": "you said that was all"})
            self.dispatcher.quiet(said, heard=repairs, pcm=pcm, engine=engine,
                                  turn_id=turn_id, why="that is all")
            return
        if released_at is not None and verbs.is_pause(said):
            self.set_conversation(False, sock)
            self.tell(sock, {"type": "conversation", "state": "paused", "why": "asked"})
            self.dispatcher.quiet(said, heard=repairs, pcm=pcm, engine=engine,
                                  turn_id=turn_id, why="asked to hold on")
            return
        # THE THREE V10 PATHS, AND THEY ARE REACHABLE ONLY FROM A VERDICT THAT DECIDED.
        # Every key ships `shadow`, where `ask` hands back the rule's own answers and
        # `source` is `rule` for all of them, so on day one none of these is entered and
        # the turn goes exactly where it went before. `Ruling.by` is what says which
        # implementation decided, and reading it rather than the value is what keeps
        # "Jev decides nothing today" a mechanism rather than a promise.
        if ruling is not None:
            # `complete: no`: the thought is not finished. HOLD it, reopen the
            # microphone, and join the rest when it arrives.
            #
            # A JOINED SENTENCE IS NEVER HELD AGAIN. One hold, then it goes: that bounds
            # the whole thing at a single pause however the judge answers, which is the
            # property that makes a wrong verdict cheap in every case rather than in the
            # ordinary one.
            if (not joined and ruling.by("complete") == "jev"
                    and ruling.value("complete") is False):
                self.hold_partial(said, repairs=repairs, mode=mode, space=space,
                                  released_at=released_at, pcm=pcm, engine=engine,
                                  turn_id=turn_id, sock=sock)
                return
            # `addressed: no`: he was talking to someone else in the room. The turn ends
            # quietly, no Harbor turn is spent, and the transcript line is kept.
            if (ruling.by("addressed") == "jev"
                    and ruling.value("addressed") is False):
                self.dispatcher.quiet(said, heard=repairs, pcm=pcm, engine=engine,
                                      turn_id=turn_id, why="not addressed to me")
                return
            # `route`: where the utterance goes. A board read is answered off the
            # board, with no model and no Harbor turn, which is the third path V10 asks
            # for. The rule's own route already agrees with what the turn does
            # (`Dispatcher.rule_route`), so this moves a turn only when Jev decided it.
            if ruling.by("route") == "jev" and not self.dispatcher.pinned():
                # NOT WHILE HE IS CONNECTED (V4). A `board_read` verdict would answer off
                # the board a sentence he said to the house he is talking to, which is the
                # one thing a pin must make impossible. The rule's own verdict says
                # `connected` for these turns (`Dispatcher.rule_route`), so the shadow log
                # records what actually happened rather than a route nothing took.
                route = str(ruling.value("route") or "")
                if route == config.MODE_CAPTURE:
                    mode = config.MODE_CAPTURE
                elif route in ("talk", "board_read"):
                    mode = config.MODE_TALK
                # `other` leaves the turn exactly where the page put it: an answer that
                # says "none of these" is not an instruction to do anything.
        self.dispatch(said, repairs=repairs, mode=mode, space=space,
                      released_at=released_at, pcm=pcm, engine=engine, turn_id=turn_id,
                      route=route, typed=typed)

    def dispatch(self, said: str, repairs=None, mode: str = "", space: str = "",
                 released_at: float | None = None, pcm: str = "", engine: str = "",
                 turn_id: str = "", route: str = "", typed: bool = False) -> None:
        """Start the turn: a capture, or a question for Harbor.

        ONE PLACE, because a turn is now reached two ways. An utterance arrives here
        straight from `on_text`, and a held partial (V10) arrives here later, when the
        hold expired with nothing joined to it. The mode and the space travel with the
        words rather than being read again at the moment of dispatch, which is what makes
        the second path honest.

        KWARGS, NOT POSITION, which two cards reached independently and within an hour of
        each other (c-312's `engine`, c-324's `turn_id`). Seven and five defaulted,
        optional values is a positional list one edit away from handing the recording to
        the wrong parameter.
        """
        mode = config.normal_mode(mode)
        if mode == config.MODE_CAPTURE:
            threading.Thread(target=self.dispatcher.capture,
                             kwargs={"said": said, "space": space, "heard": repairs,
                                     "released_at": released_at, "pcm": pcm,
                                     "engine": engine, "turn_id": turn_id, "typed": typed},
                             name="voice-capture", daemon=True).start()
            return
        threading.Thread(target=self.dispatcher.answer,
                         kwargs={"said": said, "heard": repairs, "pcm": pcm,
                                 "engine": engine, "turn_id": turn_id, "route": route,
                                 "typed": typed},
                         name="voice-turn", daemon=True).start()

    def _preturn(self, said: str, mode: str, turn_id: str, space: str = "",
                 cut: bool = False, hands_free: bool = False):
        """Ask the `preturn` judge and hand back its `Ruling`.

        V10, verbatim: on day one Jev decides NOTHING. It is asked beside the path that
        decides, its answer is logged, and the turn goes the way it would have gone
        without it. c-324 kept that guard in this signature, by returning nothing at all
        while there were no paths to read a verdict into. c-314 built the three paths, so
        the guard moved to where it now belongs: the ruling is handed back, and every
        branch that reads it reads `Ruling.by(...) == "jev"` FIRST.

        THAT IS WHY THE GUARD IS STILL A MECHANISM. In `off` and in `shadow`, which is
        what every key ships as, `ask` returns the rule's own answers with `source` set
        to `rule` on all of them, so `by(...)` is never `jev` and not one of the three
        paths can be entered. It takes a key going `on`, which is refused while a judge
        has no floor, or `judges.pretend` in a test. Reading the VALUE without the source
        would be the version of this that decides something on day one.

        THE RULE IS ASKED OF THE DISPATCHER, not written out here: `rule_route` is the
        decision the turn is about to make, so the rule's verdict in the log is what then
        happened rather than a copy of it that can drift.

        WHAT LEAVES THE MACHINE is this utterance and a five-item menu: the four
        `judges.PRETURN` carries, plus one fixed sentence for the place that exists in
        this state (`connected` while pinned, `connect` while not). Both are written out
        in `dispatcher.py` and neither carries a card, a title or a count. Since c-552 the
        `card` answer's menu does: the ids and titles of his PERSONAL cards in the digest,
        unpinned only, and never a work card's (`_preturn_answers`). The other c-552
        answers carry fixed menus written out in `judges.py`.

        THE try/except IS NOT DISTRUST OF `ask`'s CONTRACT (it never raises, never blocks
        past the budget, and every failure is already the rule's verdict and a counted
        miss). It is this path's own rule, the one c-311's hardening round set for
        `hear`: the dispatch of what he just said may never be lost to something that was
        only ever asked beside it.
        """
        try:
            route = self.dispatcher.rule_route(said, mode)
            pinned = self.dispatcher.pinned()
            # WHAT THE RULE DOES TODAY, for the four c-552 seats as well: the talker picks
            # the card, the digest is the only read, the table repair has already run, and
            # a press over an answer cut it.
            rule = judgesmod.rule("preturn", complete=True, addressed=True, route=route,
                                  card="none", prefetch="none", repair="none",
                                  bargein=True)
            # THE FOURTH PLACE, AND ONLY WHILE IT EXISTS (V4). `criteria` is the seam this
            # module already has for a menu the caller owns: while he is connected there is
            # somewhere else an utterance can go, and the judge is told so. Unpinned, the
            # menu is exactly what it was, because offering a choice that cannot happen is
            # how a shadow log starts measuring the wrong thing.
            # AND THE FIFTH, WHILE HE IS NOT (c-419): "put me through to the house
            # doing that work" is a real destination now, so the judge is offered it. It
            # is SHADOW ONLY and nothing reads the verdict: a `connect` route falls
            # through `on_text` untouched and `_instant` sends it to Harbor, which is the
            # model that has the digest and can say WHICH house. The menu is one option
            # wider in each state and never both at once, because a pinned turn cannot
            # ask to be put through and an unpinned one has nowhere to be connected from.
            menu = dict(judgesmod.PRETURN.questions["route"]["criteria"])
            menu.update(dispatcher_module.CONNECTED_CRITERIA
                        if pinned else dispatcher_module.CONNECT_CRITERIA)
            criteria = {"route": menu}
            answers, cards = self._preturn_answers(route, pinned)
            if cards:
                criteria["card"] = cards
            if cut:
                answers.append("bargein")
            facts = {"space": space, "card": pinned, "pinned": bool(pinned),
                     "hands_free": bool(hands_free)}
            return judgesmod.ask("preturn", said, rule, turn=turn_id, criteria=criteria,
                                 answers=answers, facts=facts)
        except Exception as exc:                                        # noqa: BLE001
            print(f"voice: the preturn judge failed and the turn is unaffected: "
                  f"{exc.__class__.__name__}: {str(exc)[:200]}", flush=True)
            return None

    # How many cards the `card` answer is offered. The digest's own sample is capped near
    # this already; the cap is here so a choice can never grow past what it was measured at.
    CARD_MENU_MAX = 40

    def _preturn_answers(self, route: str, pinned: str) -> tuple[list, dict]:
        """(the answers this utterance is asked, the `card` menu) for the `preturn` seat.

        EACH ANSWER IS ASKED ONLY IN THE STATE IT IS ABOUT (c-552). `route` is not asked
        while pinned: the seat ignores it there, and c-542 found it wrong 4 of 6 times,
        once at 0.98, so asking it only made the numbers worse. `card` and `prefetch` are
        about a turn that goes to the talker, so they are asked only unpinned, `prefetch`
        only on a talk turn, and `card` only when there is a card to offer.

        THE CARD MENU IS PERSONAL CARDS ONLY. The verdict counts personal rows only, so a
        work title would leave the machine for no measurement. It is read from the digest
        the turn already holds, so it costs no board read.
        """
        answers = ["complete", "addressed", "repair"]
        if pinned:
            return answers, {}
        answers.append("route")
        if route == "talk":
            answers.append("prefetch")
        cards = {}
        for row in self._digest_cards():
            if len(cards) >= self.CARD_MENU_MAX:
                break
            if (row.get("space") == "personal" and row.get("id")
                    and row.get("stage") not in ("done", "archived")):
                cards[str(row["id"])] = str(row.get("title") or "")[:120] or None
        if cards:
            answers.append("card")
            cards = {**cards, **judgesmod.PRETURN.questions["card"]["criteria"]}
        return answers, cards

    def _digest_cards(self) -> list:
        """The digest's card rows, or none. A menu that cannot be read costs the `card`
        answer and never the call the other answers ride on."""
        try:
            return list(self.snapshot.doc.get("cards") or [])
        except Exception:                                               # noqa: BLE001
            return []

    # -- health --------------------------------------------------------------- #

    def health(self) -> dict:
        return {
            "ok": True,
            "version": VERSION,
            "upSeconds": round(time.time() - self.started, 1),
            # THE LOOKUP TIER IS GONE, said out loud rather than by omission. It was
            # reported here as `router` for a year and read by the page's sheet, the
            # deck's Voice card and `keel voice status`; a key that simply vanished
            # would read to all three as a gateway too old to answer. Deleted
            # 2026-09-18, decision D4.
            "lookupTier": "removed",
            # WHAT THIS PROCESS IS HOLDING IN MEMORY, by name, and empty is the shipping
            # answer. The lookup tier was switched off on 2026-09-04 to stop holding
            # 4.7 GB for it and deleted on 2026-09-18, and a filler that pulled the
            # weights back would be the decision not actually taken. Visible here so it
            # can be read rather than inferred from `top`.
            "resident": self.resident(),
            # WHO IS SPEAKING DURING THE WAIT, reported for the same reason the TTS chain
            # is: a degraded voice should be visible rather than merely different. With
            # ollama down this reads `table`, the wait is still filled, and it is filled
            # by a person's words instead of a model's.
            "filler": (self.dispatcher.filler.as_json()
                       if hasattr(self.dispatcher.filler, "as_json")
                       else {"backend": self.dispatcher.filler.name,
                             "model": getattr(self.dispatcher.filler, "model", ""),
                             "resident": bool(getattr(self.dispatcher.filler,
                                                      "resident", False))}),
            # HOW OFTEN THE WAIT SPEAKS AGAIN, on /voice/health because the constant
            # spent its whole life being documented and never read. A number that is
            # visible on a running service is a number somebody can check.
            "waitRepeatEverySeconds": config.FILLER_REPEAT_EVERY,
            "stt": {"backend": self.stt.name, "ready": getattr(self.stt, "ready", False),
                    "why": getattr(self.stt, "why", "")},
            # WHETHER HANDS-FREE STILL WAITS OUT TWENTY SECONDS, and the number in force
            # if it does not. A detector that has quietly degraded to NullVAD (no wheel,
            # no model file) looks exactly like one that is working, from the outside,
            # right up until a turn takes twenty seconds; this is where that shows.
            "vad": {"backend": self.vad.name,
                    "ready": getattr(self.vad, "ready", False),
                    "why": getattr(self.vad, "why", ""),
                    "hangoverSeconds": config.VAD_HANGOVER,
                    "minSpeechSeconds": config.VAD_MIN_SPEECH},
            # THE CORPUS, so a recorder left on is visible rather than merely running.
            # It is his voice on disk: it is never backed up, it is capped and expired,
            # and this is the line that says how much of it there is.
            "record": record.stats(),
            # THE WHOLE CHAIN, not just the link that is answering: which voice is
            # speaking now, which one is preferred, which are demoted and why, when each
            # is next tried, and what the hosted one has cost this month. The spend
            # segment he plans to build reads the last of those from here rather than
            # asking Google.
            "tts": (self.tts.as_json() if hasattr(self.tts, "as_json")
                    else {"backend": self.tts.name,
                          "tried": getattr(self.tts, "tried", [])}),
            # THE JUDGES (V10): the effective switch, where each value came from, and
            # whether they can reach the key. One document and three readers, `keel
            # doctor`, `keel voice status` and the page's settings sheet, which is what
            # makes a default and an override read as one answer.
            "judges": judgesmod.health(),
            "snapshot": {"healthy": self.snapshot.healthy,
                         "ageSeconds": round(min(self.snapshot.age, 9999), 1),
                         "error": self.snapshot.error},
            "clients": len(self.clients),
            # HOW LONG SINCE ANYTHING WAS HEARD FROM ANY CLIENT, so `is_live`'s
            # judgement can be read rather than trusted. The presence gate itself is
            # in the dispatcher; this is only visibility into what it is looking at.
            "lastActivitySecondsAgo": round(time.time() - self.last_activity, 1),
            # THE TWO MODES, and whether a capture's ack will play from disk or have to be
            # synthesised: a missing clip is a degraded ack, and this is where that shows.
            "modes": {"default": config.MODE_DEFAULT,
                      "captureSpace": config.CAPTURE_SPACE_DEFAULT,
                      "acks": self.tts.cache.stats(corpus.ack_lines())
                      if getattr(self.tts, "cache", None) is not None else {}},
            # WHETHER THE SECOND HALF OF A CAPTURE IS RUNNING AT ALL, and how far behind
            # it is. A queue that stops draining is silent by design (nobody is waiting
            # for a refine), so this is the only surface that would show it.
            "refine": self.refiner.as_json(),
            "env": speech.env_note(),
        }


GATEWAY: Gateway | None = None


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, *_args):
        pass                                    # a background service, not a terminal

    def _send(self, code, body: bytes, ctype: str):
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def _json(self, code, obj):
        self._send(code, json.dumps(obj).encode(), "application/json; charset=utf-8")

    def do_GET(self):
        path = self.path.split("?", 1)[0]
        if path == "/voice/ws":
            return self._websocket()
        if path in ("/voice/health", "/voice/"):
            return self._json(200, GATEWAY.health())
        if path == "/voice/state":
            return self._json(200, GATEWAY.bus.read())
        if path == "/voice/flags.js":
            return self._send(200, config.flags_js(),
                              "application/javascript; charset=utf-8")
        return self._json(404, {"error": "no such voice route"})

    # THERE IS NO do_POST, AND THAT IS THE DESIGN. The bus is one-way and every input
    # arrives over the socket, which is a channel he opened by holding a button. A POST
    # here would be a second way in, on the dashboard's own origin.

    def _websocket(self):
        if not ws.is_upgrade(self.headers):
            return self._json(400, {"error": "not a websocket upgrade"})
        # THE ONLY WRITE PATH INTO THE AGENT, so it is the one that has to be fenced.
        # A websocket is exempt from the same-origin policy: any page in any tab can
        # open one here with no preflight, send {"type": "text"}, and have that line
        # typed into Harbor's pane and submitted. See ws.same_origin.
        if not ws.same_origin(self.headers):
            return self._json(403, {"error": "this socket may only be opened by "
                                             "Harbor's own page"})
        sock = ws.Socket.upgrade(self)
        if sock is None:
            return
        GATEWAY.add_client(sock)
        buffer = bytearray()
        listening = False
        # PER CONNECTION, beside `listening` and for the same reason: the gateway's own
        # `vad` holds the model, but whether THIS listen is hands-free and how much
        # silence has run since THIS listen's last word are facts about one socket.
        hands_free = False
        # WHICH LISTEN THIS IS, as the page numbered it, echoed back on `endpoint` so a
        # page that has re-armed since can tell an endpoint for the listen it is in from
        # one for the listen before it (c-314). The gateway never invents this number and
        # never reads meaning into it: it is the page's, and this is a mirror.
        listen_id = None
        # WHEN THIS LISTEN OPENED, for the quiet cap below.
        listen_started = 0.0
        # WHETHER ANY AUDIO HAS ARRIVED IN THIS LISTEN (V13, fix 1). Per connection and per
        # listen, and it exists to be written down exactly ONCE: "this listen heard
        # something" is the question, and a transcript line per 32 ms chunk would answer it
        # by drowning it. A `listen` with no `frames` after it is the sixty-two seconds of
        # 2026-09-21, visible instead of inferred.
        had_frames = False
        conversation = False
        endpointer = vadmod.Endpointer()
        try:
            while True:
                frame = sock.recv()
                if frame is None:
                    break
                # ANY MESSAGE AT ALL COUNTS AS PRESENCE, including the ping that fires
                # every 25 s with no other traffic. This is the signal `is_live` reads.
                GATEWAY.last_activity = time.time()
                opcode, payload = frame
                if opcode == ws.BINARY:
                    if listening:
                        buffer += payload
                        if not had_frames:
                            had_frames = True
                            GATEWAY.dispatcher.log_event("frames", listen=listen_id)
                        if hands_free and GATEWAY.hear(endpointer, payload):
                            # HE HAS STOPPED TALKING. Said, not done: the page answers
                            # with the ordinary `end`, which is the only thing that
                            # flushes the buffer (see the protocol note at the top).
                            GATEWAY.dispatcher.log_event("endpoint", reason="hangover",
                                                         listen=listen_id)
                            sock.send_json({"type": "endpoint", "reason": "hangover",
                                            "listen": listen_id,
                                            "generation": GATEWAY.dispatcher.generation})
                        elif (hands_free and not endpointer.armed
                              and time.time() - listen_started > config.VAD_QUIET):
                            # AND NOBODY EVER STARTED TALKING. The hangover cannot end
                            # this listen, because it only arms after `VAD_MIN_SPEECH` of
                            # real speech: silence that was never preceded by a word is
                            # not the end of an utterance, it is an open microphone.
                            # Closing it is the other half of ending a turn, and it is
                            # the half conversation mode made necessary, since nothing
                            # re-armed a microphone on its own before it.
                            #
                            # THE PAGE ANSWERS THIS ONE WITH `cut`, NOT `end`: there is
                            # nothing to dispatch, and `end` is still the only flush.
                            listening = False
                            hands_free = False
                            GATEWAY.dispatcher.log_event("endpoint", reason="quiet",
                                                         listen=listen_id)
                            sock.send_json({"type": "endpoint", "reason": "quiet",
                                            "listen": listen_id,
                                            "generation": GATEWAY.dispatcher.generation})
                    continue
                try:
                    msg = json.loads(payload.decode())
                except Exception:                                       # noqa: BLE001
                    continue
                kind = msg.get("type")
                if kind == "start":
                    # ARMED ONLY ON A HANDS-FREE LISTEN. A finger on the orb is an
                    # explicit statement that he is still talking, so push to talk is
                    # left exactly as it was: it ends on the release and the detector
                    # never sees a frame of it. Conversation mode (slice 3) is
                    # hands-free by definition, so it inherits this seat unchanged.
                    hands_free = bool(msg.get("handsFree"))
                    # WHAT THE PAGE CALLS THIS LISTEN, and whether another utterance is
                    # expected after the answer (c-314). The conversation is the page's
                    # fact, told to the gateway rather than decided by it: the gateway
                    # answers one utterance at a time and its only interest here is
                    # whether to reopen the microphone when the turn is over.
                    listen_id = msg.get("listen")
                    listen_started = time.time()
                    conversation = bool(msg.get("conversation"))
                    GATEWAY.set_conversation(conversation, sock)
                    endpointer.reset()
                    GATEWAY.vad.reset()
                    # HE PRESSED OVER AN ANSWER, which is the outcome that says the
                    # answer was not worth finishing. Recorded before the cut below,
                    # while there is still a turn to name.
                    GATEWAY.barged_in()
                    # A press while it is speaking is an interrupt AND the start of the
                    # next question, in one gesture. That is Q3, built as recommended,
                    # and the two halves are one message rather than two so there is no
                    # window in which the audio has stopped and nothing is listening.
                    GATEWAY.dispatcher.cut()
                    buffer = bytearray()
                    listening = True
                    had_frames = False
                    GATEWAY.bus.set_state("listening")
                    # ON THE RECORD, WITH THE ONE FACT THAT DECIDES WHAT HAPPENS NEXT
                    # (V13, fix 1): whether this listen is hands-free, and so whether the
                    # detector is what will end it. Written here rather than at the first
                    # frame, because a listen that never receives one is the case worth
                    # being able to read back.
                    GATEWAY.dispatcher.log_event("listen", handsFree=hands_free,
                                                 listen=listen_id,
                                                 conversation=conversation)
                elif kind == "level":
                    GATEWAY.bus.feed_waveform(msg.get("samples") or [])
                elif kind == "end":
                    listening = False
                    # THIS LISTEN'S OWN FACT, taken before it is reset (c-552): the verdict
                    # reads a push-to-talk utterance as addressed by definition.
                    was_hands_free = hands_free
                    hands_free = False
                    GATEWAY.bus.set_state("thinking")
                    pcm = bytes(buffer)
                    buffer = bytearray()
                    # BY KEYWORD, like the two dispatcher threads below it. Two slices
                    # added an argument to this tail within a day of each other (c-311's
                    # recording and V7's engine), and a positional tuple is exactly where
                    # that kind of merge goes quietly wrong.
                    threading.Thread(target=GATEWAY.on_utterance,
                                     kwargs={"pcm": pcm, "sock": sock,
                                             "mode": str(msg.get("mode") or ""),
                                             "space": str(msg.get("space") or ""),
                                             "released_at": time.time(),
                                             "engine": str(msg.get("engine") or ""),
                                             "hands_free": was_hands_free},
                                     name="voice-stt", daemon=True).start()
                elif kind == "cut":
                    listening = False
                    hands_free = False
                    GATEWAY.barged_in()
                    GATEWAY.dispatcher.cut()
                elif kind == "pause":
                    # THE MICROPHONE IS CLOSED AT HIS END (V3), so this end stops
                    # expecting audio and stops holding anything back for it. It is
                    # `cut` plus two facts: no conversation is open any more (the page
                    # says so again on the `start` that resumes it, so there is nothing
                    # to remember), and a half sentence held for the rest of itself is
                    # not going to get one. Expiring it here rather than waiting out its
                    # timer is what keeps "a wrong verdict costs a pause, never a lost
                    # sentence" true across a pause as well.
                    listening = False
                    hands_free = False
                    conversation = False
                    GATEWAY.set_conversation(False, sock)
                    GATEWAY.release_partial("paused")
                    GATEWAY.dispatcher.cut()
                elif kind == "text":
                    # TYPED, SO TEXT ONLY (VP-3): the flag is set in `on_typed`.
                    GATEWAY.on_typed(msg)
                elif kind == "connect":
                    # `?connect=c-272` on the page, which is what the deck's "Talk to this
                    # house" button links to (V6). The same call the spoken verb makes, so
                    # a pin taken from a link and a pin taken by voice are one path.
                    threading.Thread(target=GATEWAY.connect_to,
                                     kwargs={"card": str(msg.get("card") or ""), "sock": sock,
                                             "spoken": bool(msg.get("spoken"))},
                                     name="voice-connect", daemon=True).start()
                elif kind == "disconnect":
                    threading.Thread(target=GATEWAY.disconnect, kwargs={"sock": sock},
                                     name="voice-disconnect", daemon=True).start()
                elif kind == "trace":
                    # THE PAGE'S OWN WATCHDOG, WRITTEN DOWN AND NEVER ACTED ON (V13,
                    # fix 1). The page can see things this end cannot: that it armed, that
                    # a press happened, that playback ended, that five seconds went by with
                    # no frames leaving it. On 2026-09-21 all of that was invisible here
                    # and the sixty-two seconds of silence had no cause anybody could name
                    # afterwards.
                    #
                    # IT REACHES THE TRANSCRIPT AND NOTHING ELSE, and that is the whole of
                    # its safety. This socket is the only write path into the agent and it
                    # is already fenced by origin; a message that could arm a microphone,
                    # move a pin or start a turn would be a second way in, on the
                    # dashboard's own origin, for the benefit of a diagnostic. So it is
                    # four fields, copied, and no branch anywhere reads them back.
                    GATEWAY.dispatcher.log_event(
                        "page", event=str(msg.get("event") or "")[:40],
                        reason=str(msg.get("reason") or "")[:200],
                        listen=str(msg.get("listen") or "")[:40],
                        at=msg.get("at"))
                elif kind == "presence":
                    # WHETHER THE PAGE CAN BE SEEN (D-2, c-438): written down per socket,
                    # read only to hold back unprompted speech, never acted on otherwise.
                    GATEWAY.page_presence(sock, bool(msg.get("visible")))
                elif kind == "ping":
                    sock.send_json({"type": "pong", "at": time.time()})
        except Exception:                                               # noqa: BLE001
            pass
        finally:
            GATEWAY.drop_client(sock)
            sock.close()


class Server(ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = True


def refuse_live_board() -> str:
    """Why a gateway whose own code is a worktree's may not write to the live board.

    2026-09-20: four houses ran a scratch gateway from their worktree for a live-socket
    check, each isolated with its own `KEEL_HOME`, port and PATH, and every capture they
    spoke into it was filed as a real card on his board, because the `kb` those launches
    reached was the live checkout's. Nothing in the log said so. The empty string means
    there is nothing to refuse.
    """
    if not config.is_worktree(config.CHECKOUT) or config.board_kind() != "live":
        return ""
    if config.LIVE_STATE:
        return ""
    return (f"voice: this gateway's code is the worktree {config.CHECKOUT}, and {config.KB} "
            f"opens the LIVE board. Point KEEL_HOME at this worktree so it gets its own "
            f"scratch board, or set KEEL_LIVE_STATE=1 if the live board is what you meant.")


def serve(port: int | None = None) -> int:
    global GATEWAY
    # BEFORE ANYTHING IS BUILT OR BOUND, because the whole point is that no capture reaches
    # a board nobody chose. The board line is printed either way, so the first line of a
    # scratch launch's log says `scratch` and the first line of his says `live`.
    print(config.board_line(), flush=True)
    refusal = refuse_live_board()
    if refusal:
        print(refusal, file=sys.stderr, flush=True)
        return 2
    GATEWAY = Gateway().start()
    if config.HARBOR_KEPT_ALIVE:
        # A KEPT-ALIVE HARBOR PROCESS DIES WITH THE GATEWAY (R2, review item 5).
        from . import harborlive
        harborlive.install_shutdown()
    port = port or config.PORT
    # LOOPBACK, and it is an invariant rather than a default. Nothing about this process
    # is safe to expose: it types into Harbor's pane. The phone reaches it through the
    # view's proxy, on the view's certificate, over the tailnet.
    httpd = Server(("127.0.0.1", port), Handler)
    # ITS OWN NEW CODE, AT A QUIET MOMENT (c-538): the watch asks the server to stop, and
    # the service starts it again on what main now says.
    from . import codewatch, drawing
    watch = codewatch.CodeWatch(drawing.CHECKOUT, GATEWAY.busy,
                                lambda: threading.Thread(target=httpd.shutdown, daemon=True).start(),
                                harbormsg.log, interval=codewatch.CHECK_SECONDS).start()
    health = GATEWAY.health()
    print(f"voice gateway on http://127.0.0.1:{port}/voice/health", flush=True)
    print(f"  filler {health['filler']['backend']}:{health['filler']['model']}")
    print(f"  stt {health['stt']['backend']}  tts {health['tts']['backend']}", flush=True)
    if not health["stt"]["ready"]:
        print(f"  NOTE: {health['stt']['why']}", flush=True)
    print(codewatch.stamp_line(watch), flush=True)
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        watch.close()
        GATEWAY.snapshot.stop()
    if watch.restarting:
        print("voice gateway stopped for its new code; its service starts it again", flush=True)
    return 0
