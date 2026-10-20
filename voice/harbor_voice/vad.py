"""End of utterance: when he has stopped talking, on a hands-free listen.

WHY THIS EXISTS. Push to talk ends the utterance on release and STT takes about half a
second after it. Hands-free (`?listen=1`) has no release, so the page arms a 20 second
backstop and sends when it fires: every hands-free turn waited the full twenty seconds,
which was the whole of the slowness (V1 in <install>/history/docs/voice-next.md).

MEASURED ON THIS BOX, 2026-09-20, before a line of this was written. `silero_vad.onnx`
from sherpa-onnx's own `asr-models` release is 629 KB; it loads in 28 ms and runs one
32 ms frame in 0.248 ms on a single Neoverse-N1 core, which is 130x realtime. Fed a real
1.72 s clip followed by 3 s of near-silence, a 700 ms hangover fired 0.70 s after the
last speech frame. The detector costs nothing; only the hangover number needed his voice.

THE SPLIT IS THE DESIGN. Two classes, and the seam between them is what makes this
testable on a machine with no model and no numpy:

    Endpointer   a pure state machine over (is_speech, frame_seconds). Standard library
                 only. tests/test_voice.py drives it with a list of booleans.
    SileroVAD    sherpa-onnx's VoiceActivityDetector, used as a per-frame speech or
                 silence classifier and NOTHING else.

IT NEVER POPS A SEGMENT. sherpa's detector will happily hand back trimmed speech
segments, and taking them would mean the audio going to STT is no longer the audio the
page sent. `is_speech_detected()` only, so the bytes handed to `stt.transcribe` are
byte for byte what they are today and the detector is a timing signal rather than a
filter. If it never fires, today's behaviour is exactly what remains.

THE HANGOVER SHIPPED ON DAY ONE IS 2.5 s, NOT V1's 700 ms, and that is deliberate
(his call at this card's plan gate). 2.5 s is 3.5x the target, chosen from the safe side
so that no plausible measurement could move it up: within-turn pauses in ordinary speech
sit well under half a second, and 2.5 s of silence mid-thought is a pause he would notice
himself. It replaces a 20 second backstop with about 3 seconds from the day it merges,
and the recorded corpus tunes it down. `bin/keel-voice-vad-measure` is what reads that
corpus, and `[voice] vad = "off"` is the one line back to the old behaviour.
"""
from __future__ import annotations

import threading
from pathlib import Path

from . import config


class Endpointer:
    """Has he stopped talking: a hangover timer over a stream of speech or silence.

    NOT sherpa's own `min_silence_duration`, though that would do the same arithmetic.
    Keeping the state machine here is what lets the offline sweep in
    `bin/keel-voice-vad-measure` run the EXACT code the gateway runs, at twenty different
    hangovers over one recording, without reloading a model per candidate. The measurement
    and the live path cannot drift, because they are the same class.

    MIN_SPEECH BEFORE IT MAY FIRE. Without it a cough, a door, or the first frame of noise
    on an empty room arms the timer and ends the turn with nothing said, which the gateway
    then answers with "nothing was heard". Silence that was never preceded by real speech
    is not the end of an utterance, it is a listen nobody has started talking into, and the
    page's own backstop is the right thing to end that.
    """

    __slots__ = ("hangover", "min_speech", "speech_seconds", "silence_seconds", "fired",
                 "failed")

    def __init__(self, hangover: float | None = None, min_speech: float | None = None):
        self.hangover = config.VAD_HANGOVER if hangover is None else float(hangover)
        self.min_speech = (config.VAD_MIN_SPEECH if min_speech is None
                           else float(min_speech))
        self.reset()

    def reset(self) -> None:
        """Start again from nothing.

        RESET, NOT PAUSED, and the brief was explicit about the difference. While the
        gateway is speaking the detector is not merely held: everything it had is thrown
        away, so a hangover can never be part built out of the gateway's own voice
        leaking back through the microphone. After the gateway stops, fresh speech has to
        arrive before anything can fire.
        """
        self.speech_seconds = 0.0
        self.silence_seconds = 0.0
        self.fired = False
        # DISARMED FOR THE REST OF THIS LISTEN, set by `Gateway.hear` when the detector
        # raised. Cleared by `reset`, so the next listen starts with a working detector
        # rather than inheriting a dead one: whatever went wrong may have been one frame.
        self.failed = False

    @property
    def armed(self) -> bool:
        """Has enough real speech arrived for a silence to mean anything."""
        return self.speech_seconds >= self.min_speech

    def feed(self, is_speech: bool, seconds: float) -> bool:
        """One frame. True the first time the utterance is over, once and once only.

        ONCE ONLY, because the caller sends a message on it. A detector that kept
        returning True every frame after the hangover would send one `endpoint` per frame
        for as long as the page took to answer, and the page would then release a turn it
        had already released.
        """
        if self.fired or self.failed:
            return False
        if is_speech:
            self.speech_seconds += seconds
            self.silence_seconds = 0.0
            return False
        if not self.armed:
            # Silence before he has said anything is not the end of an utterance.
            return False
        self.silence_seconds += seconds
        if self.silence_seconds < self.hangover:
            return False
        self.fired = True
        return True


class NullVAD:
    """No detector: every frame is silence and nothing ever fires.

    THE DEGRADED PATH IS THE OLD PATH, which is what makes this whole slice additive.
    A machine with no sherpa-onnx (the Mac, until its next `keel voice venv`) or no
    model file gets this, the endpointer never arms, no `endpoint` is ever sent, and
    hands-free waits out the page's 20 second backstop exactly as it did before.
    """

    name = "none"
    ready = False

    def __init__(self, why: str = "no voice activity detector on this machine"):
        self.why = why

    def is_speech(self, pcm: bytes) -> bool:                            # noqa: ARG002
        return False

    def reset(self) -> None:
        pass


class SileroVAD:
    """Silero through sherpa-onnx: is there a voice in these 512 samples.

    ONE LOCK, for the same reason onnx.SherpaSTT has one: he is one person with one
    mouth, and two detectors competing for two cores would make the decode they run
    beside slower for no gain.

    THE WINDOW IS THE MODEL'S. Silero takes exactly 512 samples at 16 kHz (32 ms) and
    sherpa validates it, so `is_speech` buffers whatever it is handed and consumes whole
    windows, keeping the remainder for the next call. The socket hands it whatever a
    browser's audio worklet happened to produce, which is never a neat multiple.
    """

    name = "silero"
    ready = True
    why = ""

    def __init__(self, model: Path | None = None, threads: int = 1):
        import sherpa_onnx                                              # noqa: PLC0415

        path = Path(model or vad_model_path())
        cfg = sherpa_onnx.VadModelConfig()
        cfg.silero_vad.model = str(path)
        cfg.silero_vad.threshold = config.VAD_THRESHOLD
        # THE HANGOVER IS OURS, NOT SHERPA'S. Its own `min_silence_duration` would end a
        # segment for us, but we never take its segments (see the module note), so these
        # two are set low to keep its internal state cheap and out of the way. The number
        # that decides when a turn ends is Endpointer.hangover and nowhere else.
        cfg.silero_vad.min_silence_duration = 0.1
        cfg.silero_vad.min_speech_duration = 0.05
        cfg.silero_vad.window_size = config.VAD_WINDOW
        cfg.sample_rate = config.MIC_RATE
        cfg.num_threads = threads
        cfg.provider = "cpu"
        self._sherpa = sherpa_onnx
        # A small ring: we read a flag per window and never pop a segment, so there is
        # nothing to hold on to. Its size only bounds how much sherpa will keep for us.
        self._vad = sherpa_onnx.VoiceActivityDetector(cfg, buffer_size_in_seconds=5)
        self._lock = threading.Lock()
        self._tail = b""

    def reset(self) -> None:
        with self._lock:
            self._vad.reset()
            self._tail = b""

    def is_speech(self, pcm: bytes) -> bool:
        """True if any whole window in this chunk held speech.

        ANY RATHER THAN THE LAST, because a chunk is a few windows long and a chunk that
        contained a word is not silence. Erring toward speech errs toward a longer
        hangover, which errs toward not cutting him off.
        """
        import numpy as np                                              # noqa: PLC0415

        with self._lock:
            buf = self._tail + pcm
            width = config.VAD_WINDOW * 2                # 16 bit samples
            whole = (len(buf) // width) * width
            self._tail = buf[whole:]
            if not whole:
                return False
            samples = np.frombuffer(buf[:whole], dtype="<i2").astype(np.float32) / 32768.0
            speech = False
            for i in range(0, len(samples), config.VAD_WINDOW):
                self._vad.accept_waveform(samples[i:i + config.VAD_WINDOW])
                if self._vad.is_speech_detected():
                    speech = True
            return speech


def vad_model_path() -> Path:
    """Where silero_vad.onnx is: beside the Parakeet models."""
    name = config.VAD_MODEL
    path = Path(name).expanduser()
    return path if path.is_absolute() else config.MODELS_DIR / path


def make_vad(backend: str | None = None):
    """The detector this machine can actually run, or a null one that never fires.

    THE SAME SHAPE AS speech.make_stt, deliberately: `auto` looks, `off` refuses, and
    anything missing degrades to the floor with a reason on /voice/health rather than
    raising. A gateway must start and answer with no detector at all, because that is
    what it did before this slice and what the Mac will do until its venv is rebuilt.
    """
    backend = (backend or config.VAD_BACKEND).strip().lower()
    if backend in ("off", "none", "0", ""):
        return NullVAD("turned off in keel.toml")
    path = vad_model_path()
    if not path.is_file():
        return NullVAD(f"no model at {path}")
    try:
        return SileroVAD(path)
    except Exception as exc:                                            # noqa: BLE001
        return NullVAD(f"{exc.__class__.__name__}: {str(exc)[:120]}")


# THE TWO-STAGE RULE (D-6, c-323), SCORED ONLY. Nothing live calls these: the gateway
# still ends a hands-free utterance with `Endpointer` at `VAD_HANGOVER`. They exist so
# `bin/keel-voice-vad-measure --two-stage` can replay the rule over his recorded corpus
# before anyone decides to switch it on: at a SHORT pause the buffered audio is
# transcribed, and the turn ends there when the words look finished; otherwise it waits
# for the LONG pause. A wrong early cut is survivable (V10's held partial joins the next
# listen to it), which is why the short stage may be aggressive.
TWO_STAGE_SHORT = 0.7
TWO_STAGE_LONG = 2.0

# A sentence ending on one of these is still going: a conjunction, an article, a
# preposition that wants its object, or a filler.
OPEN_ENDINGS = frozenset((
    "and", "but", "or", "so", "because", "then", "if", "that", "which", "who", "when",
    "the", "a", "an", "to", "of", "for", "with", "in", "on", "at", "from", "about",
    "um", "uh", "er", "erm", "like", "is", "are", "my", "your", "this"))


def looks_complete(text: str) -> bool:
    """Do these words look like a finished sentence. Shape only, no model."""
    said = " ".join(str(text or "").split())
    if not said or said[-1] in ",;:-":
        return False
    last = said.split()[-1].strip(".!?\"'").lower()
    return bool(last) and last not in OPEN_ENDINGS


def two_stage_fire_at(flags, frame: float, heard, short: float = TWO_STAGE_SHORT,
                      long: float = TWO_STAGE_LONG, min_speech: float | None = None):
    """Where the two-stage rule would end this recording: (seconds, "short"|"long"),
    or (None, "") when it never would. `heard(seconds)` is the transcript of the audio
    up to that point; it is asked once per pause, when the pause reaches `short`. The
    arming is `Endpointer`'s: no silence counts before `min_speech` of real speech."""
    floor = config.VAD_MIN_SPEECH if min_speech is None else float(min_speech)
    speech = silence = 0.0
    asked = False
    for i, is_speech in enumerate(flags):
        at = (i + 1) * frame
        if is_speech:
            speech += frame
            silence, asked = 0.0, False
            continue
        if speech < floor:
            continue
        silence += frame
        if not asked and silence >= short - 1e-9:
            asked = True
            if looks_complete(heard(at)):
                return at, "short"
        if silence >= long - 1e-9:
            return at, "long"
    return None, ""
