"""Speech in and speech out, each behind ONE method, and why that is not tidiness.

    transcribe(pcm16, rate) -> text
    synthesize(text) -> chunks of PCM16 at 24 kHz

THE INTERFACE IS THE VPS SEAM. The measured STT numbers, 114 to 186 ms for 1.5 to 5.3
seconds of audio, depend on Apple silicon twice over: CoreML or MLX, on the Neural
Engine. Neither exists on a Linux VPS, where the same model runs through ONNX or NeMo, or
faster-whisper int8 on CPU at about 0.9 seconds. So this is the one place in the whole
design that has to be rewritten to move machines, and it is one method with one
implementation behind it rather than a model call spread through a turn.

WHICH BACKEND IS CHOSEN BY A CAPABILITY PROBE AT START, never by configuration alone: a
machine that cannot run MLX should degrade rather than fail to boot, and /voice/health
says which one answered so a degraded voice is visible rather than merely different.

THE SEAM HAS BEEN USED ONCE, and it held (c-286, 2026-09-19). The Oracle box runs the
same Parakeet family through sherpa-onnx on two CPU cores, and the 110M there is faster
than MLX here (0.067 s against about 0.45 s for a short utterance). It is one class in
onnx.py behind `make_stt`, selected by `HARBOR_VOICE_STT=sherpa`, which `keel voice
install` writes on Linux; `auto` probes MLX first and sherpa second. The box's local voice
is kokoro-onnx, also in onnx.py, and it is only the fallback there.

## The speech model

Parakeet TDT 0.6b v2, which was already on this machine before any of this was designed,
443 MB since 1 August, because the user dictates with it. Measured here at a real-time
factor of 0.035 to 0.078.

It cannot be vocabulary-biased, and that is documented in this repository already:
`etc/dictation-vocabulary.md` was written on 2026-08-01 because OpenSuperWhisper's
`initialPrompt` is wired only into the Whisper engine and Parakeet silently ignores it.
So it hears "read me the Q". THAT IS HANDLED ONE LAYER UP, not here: `hearing.repair`
holds the observed mishearings, and every turn carries the board digest, which names the
real things, so the model reading the sentence has the names in front of it. Do not add a
correction table here; it would be a second place where the vocabulary lives.

## The voice

A CHAIN rather than a choice, because degrade-never-mute needs a floor that works with no
network and no install:

  kokoro      the plan's default. Local, 24 kHz, `bm_lewis`.
  kokoro-onnx the same voice through onnxruntime, the box's fallback (onnx.py).
  elevenlabs  his own key, read from the Keychain at start and never from a file.
  say         macOS's own synthesiser. Local, offline, already present.
  browser     the page's speechSynthesis. Costs one line and mutes nothing.

KOKORO IS THE VOICE, AS OF 2026-09-03. This paragraph used to say the opposite, at
length: that kokoro does not install here because blis will not build on Python 3.14 and
espeak-ng is missing, and that the voice is therefore `say`. Both halves were fixed by
hand that night (espeak-ng 1.52.0 via brew, and .venv-voice rebuilt on 3.12), kokoro went
live, and /voice/health reports `tts: kokoro` with an empty `tried` list. The paragraph
outlived the problem for a day, which is how a comment becomes a lie, and it was still
being quoted as a constraint after it had stopped being one. Caught by review, 2026-09-04.

The interpreter ceiling that fell out of it is real and is NOT blis, which now ships 3.14
wheels: kokoro 0.9.4 is `Requires-Python >=3.10,<3.13`. `keel voice venv` (keel/voice.py)
carries that ceiling and the evidence for it.

WHY `say` IS STILL IN THE CHAIN. Not as the floor it briefly was, but as the offline one.
espeak-ng is a system package that no requirements file can install, so a fresh machine
has kokoro's python half and not its data half until a person runs one brew command, and
a gateway that goes silent in that window would be worse than one that sounds different.
`say` is local, offline, and already on every mac. The chain reports which link answered,
on /voice/health as `tts`, so a degraded voice is visible rather than merely different.
"""
from __future__ import annotations

import array
import base64
import dataclasses
import http.client
import importlib.util
import io
import json
import math
import os
import re
import shutil
import ssl
import subprocess
import sys
import tempfile
import threading
import time
import urllib.error
import urllib.request
import wave
from datetime import datetime, timezone
from pathlib import Path

from . import config, loginmark, onnx

# What every backend hands back and takes in: signed 16-bit little-endian mono PCM.
# One representation, chosen once, so nothing in this package ever converts a format it
# was not expecting.


def pcm_to_floats(pcm: bytes) -> list[float]:
    a = array.array("h")
    a.frombytes(pcm[:len(pcm) - (len(pcm) % 2)])
    return [float(x) for x in a]


def floats_to_pcm(xs) -> bytes:
    a = array.array("h", (max(-32768, min(32767, int(x))) for x in xs))
    return a.tobytes()


def wav_bytes(pcm: bytes, rate: int) -> bytes:
    import io
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(rate)
        w.writeframes(pcm)
    return buf.getvalue()


# --------------------------------------------------------------------------- #
# The sound under the words (V8, card c-316; one tone since V13).
# --------------------------------------------------------------------------- #

# ONE SHORT NOTE, AND IT IS THE SAME SOUND BOTH WAYS (V13, 2026-09-21). It used to be two,
# rising into a house and falling back to Harbor, and a DIRECTION is only worth hearing
# while the two sides sound different. They do not any more: Harbor enters and leaves in
# one voice, and the line itself says which way it went ("Entering card 272" against
# "Leaving card 272"). A pair of sounds whose meaning he has to remember is a thing to
# learn; one short note is a marker, which is all that is left for it to be.
#
# IT STAYS RATHER THAN GOING, because it is the half that survives what the words do not.
# A tenth of a second of arithmetic with no synthesiser behind it cannot fail the way a
# spoken line can, and on a bad connection it is what says a switch happened at all.
TONE_NOTE_MS = 100
TONE_HZ = 587.0                 # D5, between the two notes it replaces
TONE_LEVEL = 0.18               # well under the speech around it; a signal, not an alarm
TONE_EDGE_MS = 8                # the attack and release that stop a click at each end


def _note(hz: float, ms: int, rate: int) -> list[float]:
    """One sine note with its edges taken off.

    THE ENVELOPE IS NOT DECORATION. A sine that starts at full amplitude is a step, and a
    step through a phone speaker is a click that is louder than the note.
    """
    n = max(1, int(rate * ms / 1000))
    edge = max(1, int(rate * TONE_EDGE_MS / 1000))
    out = []
    for i in range(n):
        gain = min(1.0, i / edge, (n - i) / edge)
        out.append(math.sin(2.0 * math.pi * hz * i / rate) * TONE_LEVEL * gain * 32767.0)
    return out


def tone_pcm(rate: int | None = None) -> bytes:
    """The switch, as sound. One note, the same on the way in and on the way out (V13).

    WHY THERE IS A SOUND AT ALL. The spoken lines say what happened in words, and words
    are what gets lost: a bad connection, a car, the phone in a pocket against a coat. A
    tenth of a second of arithmetic with no synthesiser behind it cannot fail the way a
    line can, and it still says that a switch happened.

    IT GOES DOWN THE SAME AUDIO CHANNEL AS SPEECH (`Gateway._send_audio`) rather than being
    made in the page. One path means it works identically on every engine including the
    browser floor, where the words are spoken by the page and the gateway sends no samples
    at all: the floor is the case where the tone is worth the most, and a page-side tone
    would have been a second implementation for the page to get wrong.
    """
    rate = int(rate or config.TTS_RATE)
    return floats_to_pcm(_note(TONE_HZ, TONE_NOTE_MS, rate))


# --------------------------------------------------------------------------- #
# Speech in.
# --------------------------------------------------------------------------- #

class NoSTT:
    """No speech model on this machine. Says so, and says it once.

    It does NOT fall back to the browser's SpeechRecognition, which was considered and
    rejected: it is not reliably present in iOS Safari at all, and it ships every word to
    a third party. A missing speech model is a thing a person installs, not a thing this
    quietly routes around.
    """

    name = "none"
    ready = False

    def __init__(self, why: str = ""):
        self.why = why or "no local speech model is installed"

    def transcribe(self, pcm: bytes, rate: int = config.MIC_RATE) -> str:
        raise RuntimeError(self.why)


class ParakeetSTT:
    """Parakeet TDT through MLX, straight from PCM in memory, on ONE thread forever.

    NO TEMPORARY FILE ON THE HOT PATH. `transcribe(path)` is the library's front door and
    it decodes the file itself; going through the mel spectrogram directly saves a write,
    a read and a decoder, none of which the latency table budgeted for.

    EVERYTHING MLX TOUCHES HAPPENS ON THE SAME THREAD, and that is not tidiness. MLX
    streams are thread-local: a model loaded on the main thread and used from a worker
    raises `There is no Stream(cpu, 1) in current thread`, and the failure is invisible
    until a real utterance arrives, because nothing about loading the model goes near a
    stream. The gateway hands each turn to a thread, so this was the shape it hit on the
    very first spoken sentence and on none of the tests before it.

    So the model is loaded and used by one worker that owns it, and callers hand work to
    it through a queue. That is also what the deployment wants regardless: he is one
    person with one mouth, so serialising the model is not a restriction, and two turns
    competing for the Neural Engine would make both slower than either alone.
    """

    name = "parakeet-mlx"
    LOAD_SECONDS = 180.0        # first ever run downloads the weights; after that, ~6 s

    def __init__(self, model_id: str | None = None):
        import queue                                                    # noqa: PLC0415
        import threading                                                # noqa: PLC0415

        self.model_id = model_id or config.STT_MODEL
        self.ready = False
        self._q: "queue.Queue" = queue.Queue()
        self._loaded = threading.Event()
        self._error: BaseException | None = None
        self._worker = threading.Thread(target=self._run, name="voice-stt-model",
                                        daemon=True)
        self._worker.start()
        if not self._loaded.wait(self.LOAD_SECONDS):
            raise RuntimeError("the speech model did not finish loading")
        if self._error is not None:
            raise self._error
        self.ready = True

    def _run(self) -> None:
        try:
            from parakeet_mlx import from_pretrained                    # noqa: PLC0415
            self.model = from_pretrained(self.model_id)
        except BaseException as exc:                                    # noqa: BLE001
            self._error = exc
            self._loaded.set()
            return
        self._loaded.set()
        while True:
            pcm, rate, done = self._q.get()
            try:
                done(("ok", self._transcribe_here(pcm, rate)))
            except BaseException as exc:                                # noqa: BLE001
                done(("error", exc))

    def _transcribe_here(self, pcm: bytes, rate: int) -> str:
        import mlx.core as mx                                           # noqa: PLC0415
        from parakeet_mlx.audio import get_logmel                       # noqa: PLC0415

        if not pcm:
            return ""
        # NUMPY, NOT A PYTHON LOOP. A second of speech is 16,000 samples, and building
        # that list one float at a time cost more than the transcription: measured, a
        # 1.05 s clip took 361 ms end to end against 120 ms for the model alone. numpy is
        # already here as a dependency of the speech model, and the fallback below is for
        # the interpreter that has neither, where correctness matters and speed cannot.
        try:
            import numpy as np                                          # noqa: PLC0415
            xs = np.frombuffer(pcm[:len(pcm) - (len(pcm) % 2)],
                               dtype="<i2").astype(np.float32) / 32768.0
            samples = mx.array(xs)
        except ImportError:
            floats = pcm_to_floats(pcm)
            if not floats:
                return ""
            samples = mx.array([x / 32768.0 for x in floats])
        mel = get_logmel(samples, self.model.preprocessor_config)
        out = self.model.generate(mel)
        return (out[0].text or "").strip() if out else ""

    def transcribe(self, pcm: bytes, rate: int = config.MIC_RATE) -> str:
        import queue                                                    # noqa: PLC0415

        box: "queue.Queue" = queue.Queue(maxsize=1)
        self._q.put((pcm, rate, box.put))
        kind, value = box.get()
        if kind == "error":
            raise value
        return value


STT_BACKENDS = {
    "parakeet": ("parakeet-mlx", lambda: ParakeetSTT(),
                 "build the interpreter it lives in: keel voice venv"),
    "sherpa": ("sherpa-onnx", lambda: onnx.SherpaSTT(),
               "the model directory goes under HARBOR_VOICE_MODELS (~/voice-bench/models)"),
}
STT_ALIASES = {"parakeet-mlx": "parakeet", "mlx": "parakeet", "sherpa-onnx": "sherpa",
               "onnx": "sherpa"}


def make_stt(backend: str | None = None):
    """The capability probe. Never raises: a gateway that will not start because a model
    is missing is worse than one that starts and reports the model as missing.

    `auto` tries MLX, then sherpa-onnx: the Mac has the first and not the second, the box
    the reverse, so each lands on its own without being told. A NAMED backend that will
    not load is NoSTT with the reason, not an exception. It used to raise, which under a
    service manager is a restart loop with nothing on /voice/health to say why.
    """
    name = (backend or config.STT_BACKEND or "auto").strip().lower()
    name = STT_ALIASES.get(name, name)
    if name in ("none", "off"):
        return NoSTT("the speech model is switched off")
    if name != "auto" and name not in STT_BACKENDS:
        raise ValueError(f"unknown STT backend {name!r}")
    whys = []
    for key in (list(STT_BACKENDS) if name == "auto" else [name]):
        label, build, fix = STT_BACKENDS[key]
        try:
            return build()
        except Exception as exc:                                        # noqa: BLE001
            whys.append(f"{label} did not load ({exc.__class__.__name__}: {str(exc)[:160]}); {fix}")
    return NoSTT("; ".join(whys))


# --------------------------------------------------------------------------- #
# Speech out.
# --------------------------------------------------------------------------- #


@dataclasses.dataclass(frozen=True)
class Spoken:
    """Who is speaking, and with which engine, for ONE call. Never module state.

    THIS EXISTS BECAUSE THE VOICE USED TO BE TWO MODULE GLOBALS (`config.TTS_VOICE` and
    `config.GOOGLE_TTS_VOICE`, read once when an engine was constructed), so the process
    had one voice for its whole life. V7 (card c-312) makes the ENGINE his, chosen per
    session on the page; V8 (card c-316) makes the SPEAKER the gateway's, Harbor or a
    connected house, changing between turns. Neither fits in a global, and a chain shared
    by every turn is exactly where per-turn state must not be stashed: `dispatcher._route`
    and `TTSChain.synthesize`'s own `report` both paid for that lesson already.

    `speaker` IS A ROLE AND NOT A VOICE ID, deliberately. `config.voice_id` owns the table,
    so no caller can pair `bm_lewis` with Google by accident.

    AND SINCE V13 IT NO LONGER CHOOSES ONE. Harbor enters and leaves a house rather than
    handing the microphone to it, so there is one voice throughout and the role is carried
    as the RECORD of whose words these are: it reaches the page on the turn, and it reaches
    the synthesiser only through `config.voice_speaker`, which answers Harbor. It is still
    carried per call rather than dropped, because the page and the transcript are the two
    things that still have to say which house said something.

    Both fields default to "nothing in particular", which is exactly today's behaviour:
    the configured chain in its configured order, speaking as Harbor.
    """

    engine: str = ""                            # "google" | "kokoro" | "": no preference
    speaker: str = config.SPEAKER_HARBOR        # whose words; the voice is always Harbor's


class KokoroTTS:
    """The plan's default voice. Local, 24 kHz, `bm_lewis`.

    First in the chain and it stays first. On a machine where it imports it wins; see the
    module docstring for why it does not import on this one today.

    IT MUST BE TOLD WHERE THE SENTENCES ARE, and that one argument is the difference
    between a voice that answers and a voice that pauses first. `KPipeline` splits its
    input on NEWLINES by default (`split_pattern=r"\n+"`), and every answer this gateway
    produces is one line with no newline in it, so the pipeline yielded exactly ONE
    chunk: the whole clip, synthesised in full before a single sample reached the page.

    Measured on this machine, the same sentence, the same voice:

        as it shipped   first audio 1.422 s   (chunks: 1)
        split on ends   first audio 0.280 s   (chunks: 2)

    That is 1.14 seconds of silence on EVERY spoken turn, and it was the largest single
    hop in a short one: larger than the lookup it replaced (0.32 s) and larger than the
    speech model (0.12 s). `say` had the splitter from the
    start (`_sentences`, below) and kokoro never did, so the regression arrived with
    kokoro itself when espeak-ng was installed and it became the default.

    The pattern splits AFTER a sentence end rather than on one, so the punctuation stays
    with the phrase it belongs to and the synthesiser still hears a full stop. Semicolons
    and colons are in it for the reason `_BREAKS` records: `running` renders one sentence
    with semicolons between the dispatches, and a breath is a place to start speaking.
    """

    name = "kokoro"

    # After a sentence end, not on one: the punctuation belongs to the phrase before it,
    # and a synthesiser handed a clause with its full stop removed reads it as a
    # fragment and drops the falling intonation that makes it sound finished.
    SPLIT = r"(?<=[.!?;:])\s+"

    def __init__(self, voice: str | None = None):
        from kokoro import KPipeline                      # noqa: PLC0415

        self.voice = voice or config.TTS_VOICE
        self.pipeline = KPipeline(lang_code="b")
        self.ready = True

    def synthesize(self, text: str, voice: str = ""):
        # THE VOICE IS THE CALL'S, not the instance's. One built pipeline speaks every
        # speaker: this object is 787 MB and 11.8 s to construct, measured, so a second
        # instance per speaker would put that back for nothing. `self.voice` is the
        # fallback for a caller that names none, which is every caller that predates V7.
        for _gs, _ps, audio in self.pipeline(text, voice=voice or self.voice,
                                             split_pattern=self.SPLIT):
            yield floats_to_pcm(float(s) * 32767.0 for s in audio)


class ElevenLabsTTS:
    """His own key, from the Keychain, never from a file.

    Wired from day one because the fallback chain has to exist either way, and because on
    a weak VPS it is the option that IMPROVES things rather than a luxury. It is the only
    thing in this package that touches the network, it is off unless a key is in the
    Keychain, and it is third in the chain rather than first because a local voice keeps
    everything said in this house inside this house.
    """

    name = "elevenlabs"
    KEYCHAIN_SERVICE = "harbor-voice-elevenlabs"

    def __init__(self):
        self.key = self._keychain()
        if not self.key:
            raise RuntimeError("no ElevenLabs key in the Keychain")
        self.ready = True

    @staticmethod
    def _keychain() -> str:
        try:
            p = subprocess.run(
                ["security", "find-generic-password", "-s",
                 ElevenLabsTTS.KEYCHAIN_SERVICE, "-w"],
                capture_output=True, text=True, timeout=5)
            return p.stdout.strip() if p.returncode == 0 else ""
        except Exception:                                               # noqa: BLE001
            return ""

    def synthesize(self, text: str, voice: str = ""):
        raise RuntimeError(
            "the ElevenLabs backend is wired but not implemented in V1: no key has ever "
            "been present on this machine, so there is nothing to have tested it "
            "against. It is reached only when a key is put in the Keychain, and the "
            "chain falls past it until then.")


class SayTTS:
    """macOS's own synthesiser, at the bus's rate. Local, offline, already installed.

    The floor of the chain on this machine, and the reason stage 1 can be demonstrated at
    all. It writes a whole clip rather than streaming, so the first-chunk number is worse
    than Kokoro's; the sentence is split so at least the first sentence starts early,
    which is the same trick the latency table already assumes.
    """

    name = "say"

    def __init__(self, voice: str | None = None):
        self.voice = voice or config.TTS_SAY_VOICE
        if not shutil.which("say"):
            raise RuntimeError("no `say` on this machine")
        # WHICH VOICES THIS MAC ACTUALLY HAS, asked once, here, and never again (V8).
        # `say -v <a voice this Mac lacks>` exits non-zero and writes no file, which `_one`
        # swallows into b"". That is SILENCE, and silence is the one thing this chain may
        # never produce: the engine above would have handed the sentence down to something
        # that looked like it worked. V8 needed this for the house voice (`Veena` is an
        # en_IN voice macOS offers and does not install), and V13 took the house voice
        # away; the probe stays, because `Daniel` is not guaranteed either.
        self.installed = self._installed()
        self.ready = True

    # A ROW OF `say -v ?`: the name, the locale, then `#` and a sample sentence. THE NAME IS
    # WHATEVER COMES BEFORE THE LOCALE, and that is the only rule that holds. Recent macOS
    # lists names with spaces in them ("Eddy (English (UK))"), and the name column is
    # PADDED to a width, so a long name is followed by a single space and a short one by a
    # run of them. Splitting on a run of spaces reads a long row's name as
    # "Eddy (English (UK)) en_GB", which is a voice nothing has, asked for at the moment
    # the chain is trying not to be silent. Found by the test, not by the Mac.
    SAY_ROW = re.compile(r"^(.+?)\s+([A-Za-z]{2,3}[_-][A-Za-z]{2,4})(?:\s|$)")

    @staticmethod
    def _installed() -> set:
        """Every voice name `say` lists, or an empty set when the probe says nothing."""
        try:
            done = subprocess.run(["say", "-v", "?"], capture_output=True, text=True,
                                  timeout=10)
        except Exception:                                               # noqa: BLE001
            return set()
        if done.returncode != 0:
            return set()
        names = set()
        for line in (done.stdout or "").splitlines():
            match = SayTTS.SAY_ROW.match(line.strip())
            if match and match.group(1).strip():
                names.add(match.group(1).strip())
        return names

    def _resolve(self, voice: str) -> str:
        """The nearest voice this Mac has to the one asked for.

        THE HOUSE BRANCH IS GONE WITH THE HOUSE VOICE (V13): there is one voice now, so
        the only substitution left is the configured one, and an empty answer means `say`
        speaks whatever it is set to rather than nothing at all.
        """
        if not self.installed or voice in self.installed:
            return voice
        return self.voice if self.voice in self.installed else ""

    def synthesize(self, text: str, voice: str = ""):
        for part in _sentences(text):
            pcm = self._one(part, self._resolve(voice or self.voice))
            if pcm:
                yield pcm

    def _one(self, text: str, voice: str = "") -> bytes:
        with tempfile.TemporaryDirectory() as d:
            out = Path(d) / "s.wav"
            cmd = ["say", "-o", str(out),
                   f"--data-format=LEI16@{config.TTS_RATE}", text]
            if voice:
                cmd[1:1] = ["-v", voice]
            try:
                subprocess.run(cmd, capture_output=True, timeout=30, check=True)
                with wave.open(str(out)) as w:
                    return w.readframes(w.getnframes())
            except Exception:                                           # noqa: BLE001
                return b""


class BrowserTTS:
    """The last resort: the page speaks it with its own speechSynthesis.

    Not a synthesiser at all, which is the point. It produces no audio here and tells the
    page to say the words itself, so a gateway with no working voice degrades to a
    different voice rather than to silence.
    """

    name = "browser"
    ready = True

    def synthesize(self, text: str, voice: str = ""):
        return iter(())          # the page is told to speak; see server.py


# --------------------------------------------------------------------------- #
# What the hosted voice costs, counted here because nothing else can see it.
# --------------------------------------------------------------------------- #

class CharacterMeter:
    """How many characters have been sent to a hosted synthesiser this month.

    THE FREE ALLOWANCE IS 1,000,000 CHARACTERS A MONTH AND NOTHING WAS WATCHING IT. The
    spend segment he plans to build later should be able to read this off /voice/health
    rather than ask Google, so the count lives beside the transcript in the segment's own
    data/ and survives a restart. It is the gateway's writable surface and nothing else
    writes here.

    IT COUNTS AND IT DOES NOT ENFORCE. A gateway that stopped speaking because it had
    counted to a number would be inventing an outage: a real quota stop arrives as a
    refused call, and TTSChain degrades past it to a local voice. This is a meter, not a
    valve.

    MONTHLY, BY CALENDAR MONTH IN UTC, because that is the unit the allowance is in. The
    month is stored beside the count rather than inferred from the file's mtime, so a
    gateway that has not spoken since August reads August's count and rolls it over on
    the first sentence of September rather than adding to it.
    """

    def __init__(self, path: Path | None = None):
        self.path = Path(path) if path is not None else (config.DATA / "tts-usage.json")
        self._lock = threading.Lock()

    @staticmethod
    def _month() -> str:
        return datetime.now(timezone.utc).strftime("%Y-%m")

    def read(self) -> dict:
        """The current month's totals. Never raises: a meter that cannot be read is
        reported as zero rather than allowed to cost a spoken answer."""
        blank = {"month": self._month(), "characters": 0, "calls": 0, "engine": ""}
        try:
            rec = json.loads(self.path.read_text())
        except Exception:                                               # noqa: BLE001
            return blank
        if not isinstance(rec, dict) or rec.get("month") != blank["month"]:
            return blank
        return {**blank, **{k: rec.get(k, blank[k]) for k in blank}}

    def add(self, characters: int, engine: str = "") -> None:
        """One synthesis call's worth. Best effort, and it never costs the turn."""
        with self._lock:
            rec = self.read()
            rec["characters"] = int(rec["characters"]) + max(0, int(characters))
            rec["calls"] = int(rec["calls"]) + 1
            rec["engine"] = engine or rec.get("engine") or ""
            try:
                self.path.parent.mkdir(parents=True, exist_ok=True)
                tmp = self.path.with_suffix(".part")
                tmp.write_text(json.dumps(rec))
                tmp.rename(self.path)               # atomic: a half-written count never reads
            except Exception:                                           # noqa: BLE001
                pass

    def as_json(self) -> dict:
        rec = self.read()
        allowance = max(1, config.TTS_FREE_ALLOWANCE)
        return {**rec, "freeAllowance": config.TTS_FREE_ALLOWANCE,
                "remaining": max(0, allowance - int(rec["characters"])),
                "percentOfFree": round(100.0 * int(rec["characters"]) / allowance, 2)}


METER = CharacterMeter()


# --------------------------------------------------------------------------- #
# The OTHER ledger. CharacterMeter above is this process's own count, gone at
# the next restart and invisible outside /voice/health. segments/cloud-spend
# is what the user actually looks at, and it reads a second, durable ledger
# that any caller across any process appends to
# (segments/cloud-spend/data/usage.jsonl via record.py). Nothing wired this
# gateway to it, so that card had nothing to show for real voice spend and
# would eventually report "watching nothing" over usage that was real (c-236).
# --------------------------------------------------------------------------- #

# ONE literal, reused by GoogleTTS.URL below: the selftest asserts Google's TTS
# hostname appears exactly once in this file, as its proof that the hosted
# voice is the only vendor this package calls. A second literal of the same
# string would look like a second vendor even though this one names no
# endpoint and calls nothing.
GOOGLE_TTS_SERVICE = "texttospeech.googleapis.com"


def _cloud_spend_record():
    """segments/cloud-spend/record.py's `record`, loaded from the segments tree.

    By path, not as a package: segments/cloud-spend has no __init__.py, and
    the load has to resolve against config.SEGMENTS_DIR (what `keel voice
    install` wrote from keel.toml's segments_dir) rather than a bare relative
    import, for the same reason segments/cloud-spend/fetch.py pins its own
    HOME_DIR: this process must read the ONE segments tree the deck serves,
    never whichever one happens to be on sys.path. Returns None, never
    raises, if the segment is not there.
    """
    path = config.SEGMENTS_DIR / "cloud-spend" / "record.py"
    if not path.exists():
        return None
    spec = importlib.util.spec_from_file_location("cloud_spend_record", path)
    if spec is None or spec.loader is None:
        return None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.record


def _voice_tier(voice: str) -> str:
    """The free-tier bucket a Google voice name falls into, from the name alone.

    Google names a voice `<languageCode>-<Family>-<id>`
    (config.py's own comment: Chirp 3 HD voices are
    `<languageCode>-Chirp3-HD-<name>`). The family is the part
    segments/cloud-spend/allowances.json buckets by, so it is read off the
    name rather than duplicated as a second constant that could silently
    stop matching the day GOOGLE_TTS_VOICE changes.

    "en-IN-Chirp3-HD-Charon" -> "chirp3-hd"; "en-US-Standard-A" -> "standard";
    "en-US-Neural2-A" -> "neural2"; "en-US-Wavenet-A" -> "wavenet";
    "en-US-Polyglot-1" -> "polyglot"; "en-US-Studio-O" -> "studio". Every
    tier allowances.json lists today, derived rather than enumerated.
    """
    parts = [p for p in str(voice or "").split("-") if p]
    if len(parts) <= 3:
        family = parts[2:3]
    else:
        family = parts[2:-1]
    return "-".join(family).lower()


def _record_cloud_spend(characters: int, voice: str) -> None:
    """Tell segments/cloud-spend what one synthesis call cost. Best effort.

    NEVER LETS THE ACCOUNTING BREAK THE CALL IT ACCOUNTS FOR, the same rule
    record.py states for itself: every failure here is swallowed, because a
    spoken turn must not go silent over a ledger write.
    """
    try:
        record = _cloud_spend_record()
        if record is None:
            return
        record(service=GOOGLE_TTS_SERVICE, unit="characters",
               amount=characters, tier=_voice_tier(voice), by="harbor-voice")
    except Exception:                                                   # noqa: BLE001
        pass


# THE FAILURES THAT SAY AN IDLE KEEP-ALIVE WAS CLOSED UNDER US, and nothing else.
STALE_CONNECTION = (http.client.RemoteDisconnected, BrokenPipeError, ConnectionResetError)


class GoogleTTS:
    """The voice he chose: `en-IN-Chirp3-HD-Charon`, Google Cloud Text-to-Speech.

    CHOSEN FROM RENDERED SAMPLES ON 2026-09-04, not from a description. The samples are
    in artifacts/voice-harbor/voice-samples/ and the one he picked is
    g-en-IN-Chirp3-HD-Charon.wav.

    THE CUSTODY COST IS REAL AND IT IS RECORDED RATHER THAN GLOSSED. This is the first
    thing in the whole design that sends the CONTENT of an answer off this machine, and
    it is the same line findings 11 to 15 refused hosted ROUTING over. He was given the
    tradeoff in three named shapes and chose one voice everywhere; the decision is
    written into artifacts/voice-harbor/design-source.md as a decision rather than a
    drift, and it is on the queue as a notice. It is not this file's to relitigate.
    What this file owes is that the cost is bounded and visible: what goes out is the
    answer text and nothing else, the meter counts every character of it, and kokoro is
    directly beneath so no failure here is silence.

    THE KEY IS NEVER IN A URL. It travels in the X-Goog-Api-Key header precisely so that
    no string this package might print, log or raise can contain it: a urllib exception
    carries the URL, and the URL is the one place an API key gets leaked by accident.

    ONE CALL PER SENTENCE, and TTSChain is what splits. Measured 2026-09-04 over 24
    calls: a whole answer comes back in 1.47 s median and its first sentence alone in
    0.53 s. Handing a synthesiser the whole answer is exactly the fault finding 16 found
    in kokoro, where it cost 1.14 s of silence on every spoken turn.
    """

    name = "google"
    URL = f"https://{GOOGLE_TTS_SERVICE}/v1/text:synthesize"
    PATH = "/v1/text:synthesize"
    # HOW MANY IDLE CONNECTIONS ARE KEPT (D-5). Two, because a filler and an answer can
    # be synthesising at once; a third call in that instant opens one and drops it after.
    POOL = 2

    def __init__(self, voice: str | None = None, language: str | None = None,
                 meter: CharacterMeter | None = None):
        self.voice = voice or config.GOOGLE_TTS_VOICE
        self.language = language or config.GOOGLE_TTS_LANGUAGE
        self.meter = meter if meter is not None else METER
        self.key = self._key()
        if not self.key:
            raise RuntimeError(f"no Google key in {self._source()}")
        # IDLE TLS CONNECTIONS, REUSED ACROSS CLIPS (D-5). `urlopen` per sentence paid a
        # TCP and TLS handshake on every sentence of every answer.
        self._pool: list = []
        self._pool_lock = threading.Lock()
        self.ready = True

    @staticmethod
    def _source() -> str:
        """Where the key is looked for on this machine, for the error. Never the key."""
        if sys.platform == "darwin":
            return f"the login keychain under service {config.GOOGLE_TTS_KEYCHAIN!r}"
        return (f"the systemd credential {config.GOOGLE_TTS_CREDENTIAL!r} "
                f"(`keel voice key set`)")

    @staticmethod
    def _key() -> str:
        """The key, from the one place this machine keeps it, and never returned anywhere else.

        macOS: `security` writes the secret on stdout and nothing else. Linux: the copy the
        unit's LoadCredential= put in the credential directory, and no other path and no
        environment variable. Either way a failure is an empty string rather than an
        exception carrying a command line or a path.
        """
        try:
            if sys.platform == "darwin":
                p = subprocess.run(
                    ["security", "find-generic-password", "-s",
                     config.GOOGLE_TTS_KEYCHAIN, "-w"],
                    capture_output=True, text=True, timeout=5)
                return p.stdout.strip() if p.returncode == 0 else ""
            if not config.CREDENTIALS_DIRECTORY:
                return ""
            return (Path(config.CREDENTIALS_DIRECTORY)
                    / config.GOOGLE_TTS_CREDENTIAL).read_text().strip()
        except Exception:                                               # noqa: BLE001
            return ""

    def _request(self, text: str, voice: str = "") -> bytes:
        body = json.dumps({
            "input": {"text": text},
            "voice": {"languageCode": self.language, "name": voice or self.voice},
            # LINEAR16 at the bus's own rate, so nothing in this package ever converts a
            # format it was not expecting. Google returns it as a RIFF file, so the
            # header is parsed off below rather than assumed to be 44 bytes: it is 44
            # bytes today and a WAV header is not required to be.
            "audioConfig": {"audioEncoding": "LINEAR16",
                            "sampleRateHertz": config.TTS_RATE},
        }).encode()
        payload = json.loads(self._post(body))
        return base64.b64decode(payload.get("audioContent") or "")

    def _post(self, body: bytes) -> bytes:
        """One request on a kept connection (D-5). A REUSED connection that fails before
        an answer came back is closed and the request is sent once more on a fresh one: an
        idle keep-alive the far end has since closed is the ordinary case, not an outage.
        A fresh connection's failure is raised as it is. The key rides in a header only,
        so nothing raised here can carry it."""
        headers = {"Content-Type": "application/json", "X-Goog-Api-Key": self.key}
        conn, reused = self._take()
        try:
            conn.request("POST", self.PATH, body=body, headers=headers)
            response = conn.getresponse()
            raw = response.read()
        except (OSError, http.client.HTTPException) as error:
            conn.close()
            # ONLY A STALE KEEP-ALIVE IS RESENT (review item 6): failures before any byte
            # of an answer moved. A timeout may mean Google has the text, so it is raised.
            if not reused or not isinstance(error, STALE_CONNECTION):
                raise
            conn, _ = self._fresh(), False
            try:
                conn.request("POST", self.PATH, body=body, headers=headers)
                response = conn.getresponse()
                raw = response.read()
            except BaseException:
                conn.close()
                raise
        if response.status != 200:
            conn.close()
            # A bad key is 400 with API_KEY_INVALID, a revoked or restricted one 401 or 403.
            if response.status in loginmark.REFUSED or b"API_KEY_INVALID" in (raw or b""):
                loginmark.refused("google-tts", f"Google TTS answered HTTP {response.status}")
            raise RuntimeError(f"Google TTS answered HTTP {response.status}")
        loginmark.works("google-tts")
        self._give(conn)
        return raw

    def _fresh(self):
        return http.client.HTTPSConnection(GOOGLE_TTS_SERVICE,
                                           timeout=config.GOOGLE_TTS_TIMEOUT,
                                           context=ssl.create_default_context())

    def _take(self):
        """(connection, was it reused): an idle one if there is one, else a new one."""
        with self._pool_lock:
            if self._pool:
                return self._pool.pop(), True
        return self._fresh(), False

    def _give(self, conn) -> None:
        with self._pool_lock:
            if len(self._pool) < self.POOL:
                self._pool.append(conn)
                return
        conn.close()

    def synthesize(self, text: str, voice: str = ""):
        said = " ".join(str(text or "").split())
        if not said:
            return
        # THE VOICE IS THE CALL'S (V7/V8): the request body is built per call anyway, so
        # one built engine speaks as Harbor or as a house at no cost. A call that names
        # none gets the configured one, which is every caller that predates V7.
        voice = voice or self.voice
        audio = self._request(said, voice)
        # COUNTED ONLY ON A CALL THAT CAME BACK. A refused call is not billed and must
        # not be counted, or the meter drifts up every time the network does.
        self.meter.add(len(said), self.name)
        # THE LEDGER IS PER VOICE, so a second speaker's characters are not filed under
        # the first one's tier. `_voice_tier` reads the name, and the name is the call's.
        _record_cloud_spend(len(said), voice)
        if not audio:
            return
        with wave.open(io.BytesIO(audio)) as w:
            yield w.readframes(w.getnframes())


# WHERE A CLIP MAY BE CUT so the first of it starts playing while the rest is still
# being made. Semicolons and colons are in here for a measured reason: the `running` verb
# renders one sentence with semicolons between the dispatches and a single full stop at
# the end, so a splitter that only knew `.!?` handed `say` the whole thing as one clip and
# the first audio arrived 3.3 seconds after he let go of the button rather than 1.4. A
# semicolon is a breath, and a breath is a place to start speaking.
_BREAKS = (".", "!", "?", ";", ":")


def _sentences(text: str) -> list[str]:
    """Split so the first phrase can start playing while the rest is still being made.

    Crude on purpose. A sentence splitter that is clever about abbreviations is a
    dependency and a source of surprises, and the cost of being wrong here is a pause in
    the middle of a sentence, not a wrong word.
    """
    # THE FLOOR IS FOUR CHARACTERS, NOT TWELVE, and the twelve was a real bug. Answers
    # here open with a short verdict and then explain it ("All quiet. One room is open,
    # and it is idle."), which is good spoken English and exactly the shape a streaming
    # voice wants: say the verdict, then keep talking. A twelve-character floor treats
    # "All quiet." as too short to be a phrase and hands the whole paragraph over as one
    # clip, so the answer that most deserved an early first word was the one that never
    # got one. Four is low enough for a real opener and still high enough that "Mr." or a
    # decimal point does not become a phrase boundary.
    out, buf = [], []
    for word in str(text or "").split():
        buf.append(word)
        if word.endswith(_BREAKS) and len(" ".join(buf)) > 4:
            out.append(" ".join(buf))
            buf = []
    if buf:
        out.append(" ".join(buf))
    return out or [""]


TTS_BACKENDS = {"google": GoogleTTS, "kokoro": KokoroTTS, "kokoro-onnx": onnx.KokoroOnnxTTS,
                "elevenlabs": ElevenLabsTTS, "say": SayTTS, "browser": BrowserTTS}


def _release_memory() -> None:
    """Collect, then hand the freed heap back to the OS. Best effort, never raises.

    THE COLLECT ALONE DOES NOT DO IT, measured in a Linux arm64 container (c-286):
    kokoro-onnx loaded and spoke at 529 MB; dropped and collected, 412 MB, because glibc
    keeps freed arenas for reuse; after `malloc_trim(0)`, 78 MB, the import baseline.
    Turning onnxruntime's own CPU arena off changed nothing without the trim, so the trim
    is the step that matters. macOS's counterpart, `malloc_zone_pressure_relief`, is
    called too and measured to return nothing there; the Mac does not run kokoro-onnx, so
    that costs nothing, and the call stays for the day an engine that unloads runs there.
    """
    import ctypes                                                       # noqa: PLC0415
    import gc                                                           # noqa: PLC0415
    import sys                                                          # noqa: PLC0415

    gc.collect()
    try:
        if sys.platform.startswith("linux"):
            ctypes.CDLL("libc.so.6").malloc_trim(0)
        elif sys.platform == "darwin":
            ctypes.CDLL(None).malloc_zone_pressure_relief(None, 0)
    except (OSError, AttributeError):
        pass


class TTSChain:
    """Every voice this machine has, in order, and it degrades at SPEAKING time.

    THE BUG THIS SHAPE EXISTS TO PREVENT, and it arrived with the hosted voice. The
    chain used to be resolved once at construction: the first engine that would build
    won, and it was then the voice forever. That is exactly right for the failures the
    chain was designed for, which are all install-time ones (no espeak-ng, no key, no
    `say`). It is exactly wrong for the failures a hosted voice has, which all happen
    LATER: an expired key, a dropped connection, a quota stop on the twenty-eighth of the
    month. Under the old shape any of those raised inside Gateway.speak, which caught it,
    broadcast an error and played nothing, so the turn went SILENT. Degrade-never-mute is
    the rule the whole chain exists for, and it did not hold past construction.

    SO A FAILURE DEMOTES, PER SENTENCE. Each sentence is offered to the best engine that
    is not currently demoted; if that raises, the engine is demoted and the SAME sentence
    is offered to the next one down. Nothing is spoken twice and nothing is skipped,
    which is why the split happens here rather than inside an engine: on a failure
    half-way through an answer, retrying the whole text would repeat the sentences he
    has already heard.

    A DEMOTION IS TEMPORARY AND IT IS VISIBLE. config.TTS_RETRY_AFTER (300 s) later the
    engine is tried once more, because the code cannot tell a quota stop from a dropped
    packet and being wrong in the second direction would mean a local voice for the rest
    of the day after one bad second. /voice/health names the engine, the reason and the
    time it is next tried, so a degraded voice is visible rather than merely different.

    `browser` IS THE FLOOR AND IT CANNOT FAIL: it makes no audio here at all, it tells
    the page to speak, so there is always a last link that says something.

    A FALLBACK THAT IS NOT SPEAKING IS LET GO (c-286). An engine that declares
    `unload_after` (kokoro-onnx: 556 MB on the box) is dropped from `built` once it has
    been idle that long, and the next time it is wanted it is built again lazily, exactly
    as it was the first time. Two conditions, and the second is what makes it safe: never
    mid-sentence, and only while an engine AHEAD of it in the chain is up and not
    demoted. An engine nothing is covering for is the voice, not a fallback, and dropping
    it would cost every turn after a quiet ten minutes; it would also be rebuilt by the
    next read of `name`, since `_best` builds whatever it walks to.
    """

    def __init__(self, chain=None, retry_after: float | None = None, cache=None):
        # RENDERED ONCE, PLAYED FOREVER. The filler corpus is a few hundred fixed lines,
        # and a fixed line has no business being synthesised again every time it is
        # spoken: bin/keel-voice-corpus render writes one WAV per line and this is what
        # plays it. So a filler costs no vendor call, no characters against the free
        # allowance, and no network on the one hop that is supposed to be instant.
        #
        # KEYED ON THE EXACT TEXT AND THE VOICE, so it can only ever hit a line somebody
        # rendered deliberately. A miss is not an error: the sentence is synthesised the
        # ordinary way and the wait is still filled.
        from . import corpus                                            # noqa: PLC0415

        self.cache = cache if cache is not None else corpus.CACHE
        self.tried: list[str] = []
        self.retry_after = (retry_after if retry_after is not None
                            else config.TTS_RETRY_AFTER)
        # THE CHAIN IS A LIST OF NAMES, AND ENGINES ARE BUILT ON DEMAND. The first
        # version of this built all of them at construction, which was a real cost
        # hiding behind a tidy line: kokoro is 787 MB resident and 11.8 seconds to
        # construct, MEASURED, and the whole reason the lookup tier was switched off on
        # 2026-09-04 was to stop this process holding a model it is not using. Building
        # the fallback eagerly would have put most of that back for a voice that speaks
        # only when the hosted one fails.
        self.order = [n.strip() for n in
                      (chain if chain is not None else config.TTS_CHAIN) if n.strip()]
        if not self.order:
            self.order = ["browser"]
        self.built: dict = {}
        self.demoted: dict[str, dict] = {}
        self._lock = threading.Lock()
        self._building: set = set()
        self._used: dict[str, float] = {}       # last time each built engine spoke, or was built
        self._busy: dict[str, int] = {}         # sentences each engine is making right now
        self.unloaded: dict[str, float] = {}    # engine -> when it was last let go
        # WHICH ENGINE SPOKE MOST RECENTLY, and it exists only to keep the janitor's
        # hands off it (V7). `_covered` asks whether something AHEAD in the CONFIGURED
        # order is up, which was the whole truth until a per-call choice could put an
        # engine that is not first in front: with Kokoro chosen, Google is up and ahead,
        # so kokoro-onnx read as covered and was dropped after ten idle minutes, and the
        # next turn he asked to be local opened on `browser` while 556 MB rebuilt. This
        # is not a preference the gateway holds (the page owns that, and sends it on
        # every message); it is an observation about what just spoke, and it changes
        # nothing about WHAT is spoken.
        self._spoke_last = ""
        self._janitor = False
        # THE PREFERRED ONE IS BUILT NOW, because it is what will speak and because its
        # construction is a keychain read rather than a model load. If it will not build,
        # that is an install fact and it belongs on /voice/health at boot rather than on
        # the first thing he says.
        self._build(self.order[0])

    # -- which engine speaks now ------------------------------------------- #

    def _build(self, name: str):
        """Construct one engine, once. None if it will not build, and it says why."""
        with self._lock:
            if name in self.built:
                return self.built[name]
        cls = TTS_BACKENDS.get(name)
        if cls is None:
            with self._lock:
                self.built[name] = None
                self.tried.append(f"{name}: not a backend")
            return None
        try:
            engine = cls()
        except Exception as exc:                                        # noqa: BLE001
            # A CONSTRUCTION FAILURE IS PERMANENT, and that is right: no key in the
            # keychain and no espeak-ng on the machine are facts about the install, not
            # weather. Reported in `tried` exactly as it always was.
            with self._lock:
                self.built[name] = None
                self.tried.append(f"{name}: {exc.__class__.__name__}")
            return None
        with self._lock:
            self.built[name] = engine
            self._used[name] = time.time()
        after = float(getattr(engine, "unload_after", 0) or 0)
        if after > 0:
            self._start_janitor(after)
        return engine

    # -- letting an idle fallback go ------------------------------------------ #

    def _start_janitor(self, after: float) -> None:
        """One daemon thread per chain, started by the first engine that can be unloaded.
        It wakes a tenth of the idle limit apart (between 5 and 60 s), so an engine goes
        within about a tenth of its limit of the moment it could."""
        with self._lock:
            if self._janitor:
                return
            self._janitor = True
        every = max(5.0, min(60.0, after / 10.0))

        def run():
            while True:
                time.sleep(every)
                try:
                    self.unload_idle()
                except Exception:                                       # noqa: BLE001
                    pass

        threading.Thread(target=run, name="voice-tts-janitor", daemon=True).start()

    def _covered(self, index: int, now: float) -> bool:
        """True when an engine ahead of order[index] is up and not demoted. Caller holds
        the lock."""
        for name in self.order[:index]:
            note = self.demoted.get(name)
            if self.built.get(name) is not None and not (note and note["until"] > now):
                return True
        return False

    def unload_idle(self, now: float | None = None) -> list[str]:
        """Drop every engine idle past its own `unload_after` that something ahead of it
        covers, and say which. Called by the janitor; callable directly by a test."""
        now = time.time() if now is None else now
        dropped = []
        with self._lock:
            for index, name in enumerate(self.order):
                engine = self.built.get(name)
                after = float(getattr(engine, "unload_after", 0) or 0)
                if engine is None or after <= 0 or self._busy.get(name):
                    continue
                if name == self._spoke_last:
                    continue            # the voice, not a fallback: see `_spoke_last`
                if now - self._used.get(name, now) < after or not self._covered(index, now):
                    continue
                del self.built[name]
                self._used.pop(name, None)
                self.unloaded[name] = now
                dropped.append(name)
        if dropped:
            _release_memory()
        return dropped

    def _speaking(self, name: str, delta: int) -> None:
        with self._lock:
            self._busy[name] = max(0, self._busy.get(name, 0) + delta)
            self._used[name] = time.time()
            if delta > 0:
                self._spoke_last = name

    def _build_soon(self, name: str) -> None:
        """Start building an engine in the background, once.

        WHY THIS EXISTS RATHER THAN JUST BUILDING IT WHEN IT IS NEEDED. Kokoro takes
        11.8 seconds to construct, measured, and the moment it is needed is the moment
        the hosted voice has just failed mid-answer. Eleven seconds of silence there is
        the failure the whole chain exists to prevent, and it would arrive through the
        fallback. So the build runs on its own thread and the sentence in hand goes to
        whatever is ALREADY up, which on this machine is `say`: local, offline, and
        instant to construct. A few sentences later kokoro is ready and takes over.
        """
        with self._lock:
            if name in self.built or name in self._building:
                return
            self._building.add(name)

        def run():
            try:
                self._build(name)
            finally:
                with self._lock:
                    self._building.discard(name)

        threading.Thread(target=run, name=f"voice-tts-{name}", daemon=True).start()

    # -- the order ONE call walks -------------------------------------------- #

    def _order_for(self, spoken: "Spoken | None") -> list[str]:
        """His chosen engine first, then the configured chain without it.

        THE FLOOR IS REACHED EITHER WAY, which is the property that makes a per-call
        choice safe: a choice reorders the chain, it never truncates it, so a turn he
        asked Kokoro for still falls through to Google and then to `browser` rather than
        going silent when the local model will not build. His call at c-312's plan gate
        (Q2, 2026-09-20): V7's words were about speed and sound, not about keeping a turn
        off the network, so a chosen local engine falls through the cloud one like any
        other. A local-only choice would be one branch here.

        An engine this machine's chain does not have resolves to "" and the configured
        order is used unchanged, so an unhonourable choice degrades to today.
        """
        want = config.resolve_engine(getattr(spoken, "engine", ""), self.order)
        if not want or want == (self.order[0] if self.order else ""):
            return self.order
        return [want] + [n for n in self.order if n != want]

    @property
    def name(self) -> str:
        """The engine that would speak the next sentence with no choice made. Read by
        /voice/health, so it is the CURRENT voice rather than the preferred one."""
        return self.name_for(None)

    def name_for(self, spoken: "Spoken | None") -> str:
        """The engine that would speak the next sentence for THIS call."""
        engine = self._best(self._order_for(spoken))
        return engine.name if engine is not None else "browser"

    def _best(self, order=None):
        """The best engine that is up, and a nudge for anything better that is not.

        `_build_soon` on the way past is what makes lazy construction safe: the first
        time a better engine is wanted it starts loading, and something already up
        speaks in the meantime.
        """
        now = time.time()
        order = self.order if order is None else order
        for name in order:
            note = self.demoted.get(name)
            if note is not None and note["until"] > now:
                continue
            with self._lock:
                known = name in self.built
                engine = self.built.get(name)
            if known:
                if engine is not None:
                    return engine
                continue                       # it will not build; try the next
            self._build_soon(name)
            # `browser` and `say` construct instantly, so waiting for a thread to hand
            # them over would be silence for no reason.
            if name in ("browser", "say"):
                built = self._build(name)
                if built is not None:
                    return built
        with self._lock:
            for name in reversed(order):
                if self.built.get(name) is not None:
                    return self.built[name]
        return self._build("browser")

    def _next_after(self, engine, order=None):
        order = self.order if order is None else order
        try:
            i = order.index(engine.name)
        except ValueError:
            return None
        for name in order[i + 1:]:
            with self._lock:
                known, built = name in self.built, self.built.get(name)
            if known:
                if built is not None:
                    return built
                continue
            self._build_soon(name)
            if name in ("browser", "say"):
                got = self._build(name)
                if got is not None:
                    return got
        return None

    def _demote(self, engine, exc: BaseException) -> None:
        why = f"{exc.__class__.__name__}"
        code = getattr(exc, "code", None)
        if code is not None:
            why += f" {code}"
        with self._lock:
            self.demoted[engine.name] = {
                "why": why, "at": time.time(),
                "until": time.time() + self.retry_after}

    # -- speaking ----------------------------------------------------------- #

    def synthesize(self, text: str, report: dict | None = None,
                   spoken: "Spoken | None" = None):
        """PCM chunks, from whichever voice is working, sentence by sentence.

        `spoken` IS THE CALL'S ENGINE AND SPEAKER (V7), and it is an argument rather than
        chain state for the same reason `report` is: this chain is shared by every turn,
        and two overlapping calls (a barge-in, an answer arriving while a filler is still
        going out) must not read each other's choices. None means the configured chain,
        speaking as Harbor, which is exactly what every caller that predates V7 wants.

        WHAT IT COULD NOT SAY GOES IN `report["unspoken"]`, and both halves of that
        sentence were review findings.

        THE FIRST: this used to `return` when a sentence fell to the floor, which ends
        the generator and discards every REMAINING sentence, while `Gateway.speak`
        suppressed its browser message because it had already heard samples from the
        earlier ones. A silent partial mute inside the method whose rule is
        degrade-never-mute. The same hole was one branch over and stayed open after the
        first fix: `_next_after` returning None exits the inner loop with nothing said
        and nothing recorded, and the loop simply moved on to the next sentence.

        THE SECOND: it was written to `self.unspoken`, and this chain is shared by every
        turn. Two overlapping speak calls (a barge-in, an answer arriving while a filler
        is still going out) would have read each other's leftovers. It is the same lesson
        `dispatcher._route` already paid for when it stopped stashing its refusal reason
        on `self`: one turn at a time by design is not a reason to put per-turn state
        where a second turn can reach it. So the caller passes a dict and gets its own.
        """
        spoken = spoken if spoken is not None else Spoken()
        order = self._order_for(spoken)
        if report is not None:
            report["unspoken"] = ""
            # WHICH ENGINES ACTUALLY SPOKE, in the order they first did. The engine named
            # when a turn starts is a PREDICTION: a demotion mid-answer changes it, which
            # is the whole reason the chain degrades per sentence. So provenance is
            # recorded here, after the fact, rather than read off `name_for` at the top.
            report["engines"] = []
        # THE CACHE KEY IS THE CALL'S VOICE, NOT THE CONFIGURED ONE. A rendered clip
        # belongs to one engine and one voice (`corpus.key_for`, `preferred_voice_id`),
        # so reading under the configured key would open a turn he asked Kokoro for with
        # a clip in Google's Charon and continue it in Lewis, inside one answer.
        head = self.name_for(spoken)
        cached = (self.cache.read(text, voice=voice_id_for(head, spoken.speaker))
                  if self.cache is not None else b"")
        if cached:
            if report is not None:
                report["engines"].append(head)
            yield cached
            return
        parts = [p for p in _sentences(text) if p.strip()]
        for i, part in enumerate(parts):
            engine = self._best(order)
            spoke = False
            while engine is not None:
                if isinstance(engine, BrowserTTS):
                    # NOTHING TO YIELD AND NOTHING TO RETRY: the floor tells the page to
                    # speak. What is left is recorded so the caller can hand the REST of
                    # the answer to the page rather than dropping it.
                    break
                try:
                    produced = False
                    self._speaking(engine.name, +1)
                    try:
                        for chunk in engine.synthesize(
                                part, voice=config.voice_id(engine.name, spoken.speaker)):
                            produced = True
                            yield chunk
                    finally:
                        # IN A FINALLY because a barge-in closes this generator mid-yield,
                        # and an engine left marked busy would never be let go.
                        self._speaking(engine.name, -1)
                    if produced:
                        spoke = True
                        if report is not None and engine.name not in report["engines"]:
                            report["engines"].append(engine.name)
                        break
                    # An engine that yielded nothing is not an error and not a voice
                    # either, so the sentence goes to the next one down rather than
                    # being dropped in silence.
                    engine = self._next_after(engine, order)
                except Exception as exc:                                # noqa: BLE001
                    self._demote(engine, exc)
                    engine = self._next_after(engine, order)
            if not spoke:
                # NOTHING SPOKE THIS SENTENCE, whether because the walk reached the floor
                # or because it ran off the end of the chain. Either way the rest of the
                # answer is the caller's to place, and stopping here is what makes
                # "unspoken" mean the whole remainder rather than one gap in the middle.
                if report is not None:
                    report["unspoken"] = " ".join(parts[i:])
                return

    # -- what /voice/health says -------------------------------------------- #

    def _idle_json(self, now: float) -> dict:
        with self._lock:
            out = {name: {"idleSeconds": round(now - self._used.get(name, now), 1),
                          "unloadAfterSeconds": float(engine.unload_after)}
                   for name, engine in self.built.items()
                   if engine is not None and float(getattr(engine, "unload_after", 0) or 0) > 0}
            for name, at in self.unloaded.items():
                if name not in out:
                    out[name] = {"unloadedSecondsAgo": round(now - at, 1)}
        return out

    def as_json(self) -> dict:
        now = time.time()
        with self._lock:
            started = sorted(n for n, e in self.built.items() if e is not None)
        return {
            "backend": self.name,
            "preferred": self.order[0] if self.order else "",
            "chain": list(self.order),
            # WHAT THE CONTROL ON THE PAGE CAN OFFER ON THIS MACHINE, and which it opens
            # with (V7). The same two values flags.js serves the page, reported here so a
            # control that is missing an engine can be diagnosed from the service rather
            # than from the browser.
            "engines": config.engines_for_page(self.order),
            "engineDefault": config.ENGINE_DEFAULT,
            # WHICH OF THEM THIS PROCESS IS ACTUALLY HOLDING. Empty but the preferred one
            # is the shipping answer, and it is the point: kokoro is 787 MB and it is not
            # loaded until the hosted voice fails.
            "started": started,
            "tried": list(self.tried),
            "voice": getattr(self._best(), "voice", ""),
            "cachedPhrases": (self.cache.stats()["rendered"]
                              if self.cache is not None else 0),
            "demoted": {name: {"why": note["why"],
                               "retryInSeconds": round(max(0.0, note["until"] - now), 1)}
                        for name, note in sorted(self.demoted.items())
                        if note["until"] > now},
            # THE ONES THAT LET GO OF THEIR MEMORY WHEN IDLE: how long each has been idle
            # against its limit, and when an unloaded one was last dropped. Absent from
            # `started` above is how an unloaded engine shows; this says why.
            "idle": self._idle_json(now),
            "characters": METER.as_json(),
        }


def make_tts(chain=None):
    """The whole chain, which is never one engine any more. Never raises: `browser` is at
    the end, it always constructs, and it mutes nothing."""
    return TTSChain(chain)


def voice_id_for(backend: str, speaker: str = config.SPEAKER_HARBOR) -> str:
    """Which voice a rendered clip belongs to, as `<engine>:<voice>`.

    ONE FORMAT, ONE READER OF THE TABLE. `corpus.key_for` hashes this with the text, so
    the render side and the playback side have to agree on it character for character;
    they agree by both calling here. An engine with no voice of its own (`browser`,
    `elevenlabs`) is just its name, which is what this returned before V7.
    """
    backend = str(backend or "").strip()
    voice = config.voice_id(backend, speaker)
    return f"{backend}:{voice}" if voice else backend


def preferred_voice_id(speaker: str = config.SPEAKER_HARBOR) -> str:
    """Which voice a clip rendered for the PREFERRED engine belongs to.

    THE CACHE KEY IS BUILT FROM THIS, and getting it wrong was a real bug found on
    2026-09-04 by reading the character meter rather than trusting it. The corpus render
    went through the chain, Google refused part way (355 calls back to back), the chain
    did exactly what it is built to do and degraded to kokoro, and 205 of the 355 clips
    were written into the cache under a key naming Charon. They would have been played
    back, in the wrong voice, forever, because a cache hit asks no questions.

    So the key names the engine as well as the voice, and it is read from CONFIGURATION
    rather than from a live chain: what a clip belongs to is the voice this gateway is
    set up to speak with, not the one that happened to be answering when it was made.
    A clip made under a different configuration simply misses, and a miss costs one
    ordinary synthesis.

    SINCE V7 THIS IS THE DEFAULT, NOT THE ONLY ANSWER. The control lets him pick another
    engine per session, and `TTSChain.synthesize` reads the cache under THAT engine's key,
    so `bin/keel-voice-corpus render --engine` renders a set per engine the control
    offers. This function stays what it always was: the preferred one.
    """
    chain = list(config.TTS_CHAIN) or ["browser"]
    return voice_id_for(chain[0].strip(), speaker)


def env_note() -> dict:
    """What /voice/health says about speech, so a degraded voice is visible."""
    return {"sttBackend": config.STT_BACKEND, "ttsChain": list(config.TTS_CHAIN),
            "sayAvailable": bool(shutil.which("say")),
            "voiceVenv": str(config.KEEL_HOME / ".venv-voice"),
            "modelsDir": str(config.MODELS_DIR), "sherpaModel": str(onnx.model_dir()),
            "ttsUnloadAfterSeconds": config.TTS_UNLOAD_AFTER}
