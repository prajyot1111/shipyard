"""The two engines the box speaks and hears with: sherpa-onnx and kokoro-onnx.

WHY A SECOND PAIR AT ALL. speech.py's engines are Apple-silicon builds: parakeet-mlx
runs on MLX and kokoro on torch with the Mac's espeak-ng. The Oracle box (two Neoverse-N1
cores, no GPU, no compiler) runs the SAME model families through ONNX, from prebuilt
wheels with no apt package. Measured there on 2026-09-18 (<install>/history/docs/voice-next.md,
"Benchmark on the Oracle box"):

    Parakeet TDT CTC 110M int8   2 s utterance 0.067 s, 12 s dictation 0.34 s, 251 MB
    Parakeet TDT 0.6B v2 int8    0.25 s and 1.16 s, 1015 MB (the Mac's own family)
    kokoro-onnx                  4.97 s for 12 words, 556 MB, no streaming advantage

So the 110M is the default and it is FASTER than the Mac's 0.45 s; the 0.6B is the
alternative for the day accuracy matters more than a gigabyte. kokoro-onnx is only the
fallback: real time on two cores is far too slow to be the voice, and Google stays first.

THE INTERFACE IS speech.py's, UNCHANGED: `transcribe(pcm16, rate) -> text` and
`synthesize(text) -> PCM16 chunks at 24 kHz`. Nothing past `make_stt` and `TTSChain`
knows which machine it is on, which is the whole point of that seam.

WHERE THE MODELS ARE. Files, not packages: `config.MODELS_DIR` (default
`~/voice-bench/models`, where the benchmark left them). A model is named by an alias from SHERPA_MODELS or by a path, and the
constructor is read off the files in the directory rather than off the name, so a renamed
directory still loads the right way.
"""
from __future__ import annotations

import threading
from pathlib import Path

from . import config

# THE TWO PARAKEETS, by the directory names sherpa-onnx's own releases unpack to. The
# alias is what a person types into HARBOR_VOICE_SHERPA_MODEL; the directory is what the
# release tarball is called, so a fresh download needs no renaming.
SHERPA_MODELS = {
    "parakeet-110m": "sherpa-onnx-nemo-parakeet_tdt_ctc_110m-en-36000-int8",
    "parakeet-0.6b": "sherpa-onnx-nemo-parakeet-tdt-0.6b-v2-int8",
}


def model_dir(name: str | None = None) -> Path:
    """The directory a model name means: an alias, a bare directory under MODELS_DIR, or a
    path. Resolution only; whether the files are there is the constructor's question."""
    name = (name or config.SHERPA_MODEL).strip()
    if name in SHERPA_MODELS:
        return config.MODELS_DIR / SHERPA_MODELS[name]
    path = Path(name).expanduser()
    return path if path.is_absolute() else config.MODELS_DIR / path


def _first(directory: Path, *names: str) -> Path | None:
    for name in names:
        if (directory / name).is_file():
            return directory / name
    return None


def _samples(pcm: bytes):
    """PCM16 to the float32 in [-1, 1] both ONNX engines take. numpy is a dependency of
    both wheels, so it is always here where they are."""
    import numpy as np                                                  # noqa: PLC0415

    return np.frombuffer(pcm[:len(pcm) - (len(pcm) % 2)], dtype="<i2").astype(np.float32) / 32768.0


class SherpaSTT:
    """Parakeet through sherpa-onnx, CPU only, one decode at a time.

    THE CONSTRUCTOR IS CHOSEN FROM THE FILES. The 110M is a CTC model (`model.int8.onnx`,
    `OfflineRecognizer.from_nemo_ctc`); the 0.6B is a transducer (`encoder`, `decoder`,
    `joiner`, `from_transducer(model_type="nemo_transducer")`). Reading the directory
    rather than the alias is what lets a path to either one work.

    ONE LOCK, NOT ONE THREAD. parakeet-mlx needs its own thread because MLX streams are
    thread-local; onnxruntime has no such rule, so a lock is enough. It is there for the
    same reason the MLX queue is: he is one person with one mouth, and two decodes
    competing for two cores would make both slower than either alone.

    NO VOCABULARY BIAS HERE, the same rule speech.py states for the MLX build. The
    transducer does accept a hotwords file, but only under beam search, and the 110M (the
    default) is CTC and accepts none. Mishearings are repaired one layer up, in
    `hearing.repair`, which is the one place the vocabulary lives.
    """

    name = "sherpa-onnx"

    def __init__(self, model: str | None = None, threads: int | None = None):
        import sherpa_onnx                                              # noqa: PLC0415

        self.dir = model_dir(model)
        self.threads = threads or config.SHERPA_THREADS
        tokens = self.dir / "tokens.txt"
        if not tokens.is_file():
            raise FileNotFoundError(f"no sherpa-onnx model at {self.dir}")
        ctc = _first(self.dir, "model.int8.onnx", "model.onnx")
        encoder = _first(self.dir, "encoder.int8.onnx", "encoder.onnx")
        if ctc is not None:
            self.kind = "ctc"
            self.recognizer = sherpa_onnx.OfflineRecognizer.from_nemo_ctc(
                model=str(ctc), tokens=str(tokens), num_threads=self.threads,
                sample_rate=config.MIC_RATE)
        elif encoder is not None:
            self.kind = "transducer"
            self.recognizer = sherpa_onnx.OfflineRecognizer.from_transducer(
                encoder=str(encoder),
                decoder=str(_first(self.dir, "decoder.int8.onnx", "decoder.onnx")),
                joiner=str(_first(self.dir, "joiner.int8.onnx", "joiner.onnx")),
                tokens=str(tokens), num_threads=self.threads,
                sample_rate=config.MIC_RATE, model_type="nemo_transducer")
        else:
            raise FileNotFoundError(f"{self.dir} has tokens.txt but no model file")
        self.model = self.dir.name
        self._lock = threading.Lock()
        self.ready = True

    def transcribe(self, pcm: bytes, rate: int = config.MIC_RATE) -> str:
        if not pcm:
            return ""
        samples = _samples(pcm)
        with self._lock:
            stream = self.recognizer.create_stream()
            stream.accept_waveform(rate, samples)
            self.recognizer.decode_stream(stream)
            return (stream.result.text or "").strip()


class KokoroOnnxTTS:
    """The box's local voice: kokoro v1.0 through onnxruntime, `bm_lewis`, 24 kHz.

    THE FALLBACK, NEVER THE VOICE. Real time on two cores (4.97 s for 12 words) means a
    sentence takes about as long to make as to hear, so it speaks only when Google has
    failed, and TTSChain hands it one sentence at a time so the first one starts before
    the rest is made.

    IT LETS GO OF ITS MEMORY. 556 MB resident is a lot to hold on a 12 GB box for a voice
    that speaks only when the hosted one fails, so `unload_after` tells TTSChain to drop
    it after ten idle minutes (config.TTS_UNLOAD_AFTER); the next failure builds it again
    in the background while `browser` covers the gap, which is the lazy build TTSChain
    already does for every fallback. Until the box has a Google key (c-299: GoogleTTS
    reads the macOS keychain, and Linux has none) it IS the box's voice, and TTSChain
    keeps it loaded for exactly that reason: nothing ahead of it is up to cover for it.

    British English, because `bm_lewis` is a British voice: the torch kokoro on the Mac
    runs `KPipeline(lang_code="b")` for the same reason, so the two sound alike.
    """

    name = "kokoro-onnx"
    LANG = "en-gb"

    def __init__(self, voice: str | None = None):
        from kokoro_onnx import Kokoro                                  # noqa: PLC0415

        model = _first(config.MODELS_DIR, config.KOKORO_ONNX_MODEL)
        voices = _first(config.MODELS_DIR, config.KOKORO_ONNX_VOICES)
        if model is None or voices is None:
            raise FileNotFoundError(f"no kokoro-onnx model and voices under {config.MODELS_DIR}")
        self.voice = voice or config.TTS_VOICE
        self.kokoro = Kokoro(str(model), str(voices))
        self.unload_after = config.TTS_UNLOAD_AFTER
        self.ready = True

    def synthesize(self, text: str, voice: str = ""):
        import numpy as np                                              # noqa: PLC0415

        said = " ".join(str(text or "").split())
        if not said:
            return
        # THE VOICE IS THE CALL'S (V7/V8). `Kokoro.create` takes it per call, so the one
        # built model, 556 MB on this box, speaks Harbor and a house alike; `self.voice`
        # is the fallback for a caller that names none.
        samples, rate = self.kokoro.create(said, voice=voice or self.voice, lang=self.LANG)
        if rate != config.TTS_RATE:
            raise RuntimeError(f"kokoro-onnx spoke at {rate} Hz, the bus is {config.TTS_RATE}")
        yield (np.clip(samples, -1.0, 1.0) * 32767.0).astype("<i2").tobytes()
