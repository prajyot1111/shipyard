"""The corpus: his own utterances on disk, opt in, so the hangover can be measured.

WHY THIS HAD TO BE BUILT FIRST. V1 says to measure the detector on recorded turns from
`state/voice/transcript.jsonl`. That file holds TEXT. Every line is `{at, turn, kind,
tier, mode, said, answer, ...}` and the utterance's PCM is handed to `stt.transcribe` and
dropped (server.py). Nothing in this package wrote a sample to disk, so there was nothing
to measure a hangover against and no number anyone could have defended.

WHAT IT IS FOR, AND WHEN IT STOPS. He agreed to two or three days of recording at c-277's
plan gate. `[voice] record = true` ships with this card so the corpus accrues from the
merge; the follow-up card that writes the two numbers down turns it off and runs
`keel voice corpus --delete`. It is not a permanent feature of the gateway.

THIS IS HIS VOICE, so five guards, and they are mechanism rather than a promise to
remember:

  1. READABLE BY NOBODY ELSE. The directory is 0700 and every wav is 0600, set explicitly
     rather than left to the umask. The first cut of this file set no mode at all, so on
     the box (umask 022) the directory came out 0755 and each recording 0644: his voice,
     world readable, on a machine that runs a web server and other people's code. Caught
     by review, 2026-09-20. The mode is set BEFORE the first byte of audio is written,
     never after, because "after" leaves a window in which the file exists and is
     readable. `_harden` also repairs anything already on disk, since the recordings made
     before this was fixed are still his voice.
  2. NEVER BACKED UP. `state/voice/pcm` is pruned by bin/keel-backup the same way
     `state/voice/cache` is, so no archive anywhere carries a recording of him. Everything
     else under state/ is backed up, which is exactly why this had to be excluded rather
     than merely deleted later.
  3. A CAP. RECORD_MAX_MB total, oldest deleted first, so a flag left on cannot fill the
     disk the voice gateway and the houses share.
  4. AN EXPIRY. RECORD_KEEP_DAYS, so a flag left on cannot quietly hoard months of him
     talking even if the total stays under the cap.
  5. VISIBLE. /voice/health and `keel voice status` both say how many recordings there
     are and how old the oldest is. It is never on without being seen to be on.

WRITTEN BY THE STT THREAD, not the socket thread, and never in its way: the wav is
written after `on_utterance` already has the bytes, and every failure here is swallowed.
A recorder that could cost him an answer would be a worse bug than no corpus.
"""
from __future__ import annotations

import os
import time
import uuid
import wave
from pathlib import Path

from . import config

# HIS VOICE, AND NOBODY ELSE'S BUSINESS. Guard 1 in the note above. Named constants
# rather than literals at three call sites, so the directory and the file cannot drift
# apart and a reader can see what the numbers are meant to be.
DIR_MODE = 0o700
FILE_MODE = 0o600


def new_id() -> str:
    """The name a recording is filed under, and the `pcm` pointer on the transcript line.

    ITS OWN ID RATHER THAN THE TURN'S. The turn does not exist yet: `Dispatcher.begin`
    mints it well after the audio has been transcribed, and a recorder that waited for it
    would be holding the whole utterance in memory across the STT call for no reason. So
    the id is minted here, travels down with the text the way `released_at` already does,
    and lands on the turn as `Turn.pcm`. The transcript line carries both, and
    bin/keel-voice-vad-measure joins on the `pcm` field.
    """
    return uuid.uuid4().hex[:12]


def directory() -> Path:
    return config.RECORD_DIR


def write(pcm: bytes, name: str, rate: int | None = None) -> str:
    """One utterance to `state/voice/pcm/<name>.wav`. Returns the file name, or "".

    BEST EFFORT, ALWAYS. Every path out of here that is not a written file returns the
    empty string, and the caller writes no `pcm` pointer when it gets one. A transcript
    line pointing at a wav that does not exist would send the measurement hunting for
    files that were never written.
    """
    if not config.RECORD_ENABLED or not pcm:
        return ""
    target = directory() / f"{name}.wav"
    try:
        directory().mkdir(parents=True, exist_ok=True)
        os.chmod(directory(), DIR_MODE)
        # A part file and a rename, so a gateway killed mid-write leaves no half wav for
        # the measurement to trip over. The rename carries the part file's mode, so 0600
        # set here is 0600 on the recording.
        part = target.with_suffix(".wav.part")
        # OPENED AT 0600 BY HAND, rather than letting `wave.open` create it. Two reasons,
        # and both are about the window between "the file exists" and "the file is
        # private": `wave.open(str(path))` creates through `builtins.open`, which is 0666
        # masked by the umask, so on the box the audio would be world readable for as long
        # as it took to write it and a chmod afterwards would be closing the door behind
        # the horse. `os.open` takes the mode at creation, and the explicit `fchmod` makes
        # it exact under any umask, not merely no worse than 0600.
        fd = os.open(part, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, FILE_MODE)
        try:
            os.fchmod(fd, FILE_MODE)
            with open(fd, "wb") as raw:
                fd = -1                       # the context manager owns it now
                with wave.open(raw, "wb") as fh:
                    fh.setnchannels(1)
                    fh.setsampwidth(2)
                    fh.setframerate(int(rate or config.MIC_RATE))
                    fh.writeframes(pcm)
        finally:
            if fd >= 0:
                os.close(fd)
        part.replace(target)
    except (OSError, wave.Error):
        return ""
    sweep()
    return target.name


def _harden() -> int:
    """Put the directory and every recording back to 0700 and 0600. Returns how many moved.

    REPAIR, NOT ONLY PREVENTION, and it is why this is a function rather than two lines in
    `write`. The recordings made before the mode was set are still his voice sitting at
    0644, and a fix that only covers files written from now on would leave them there. Run
    from `write`, `sweep` and `stats`, so any of the three paths that touch the corpus
    tidies it.

    CHEAP ENOUGH TO RUN FROM `stats`, which /voice/health calls on every poll: it only
    chmods a file whose mode is actually wrong, and the stat it needs to find that out is
    one `stats` was making anyway.
    """
    fixed = 0
    try:
        if (directory().stat().st_mode & 0o777) != DIR_MODE:
            os.chmod(directory(), DIR_MODE)
            fixed += 1
    except OSError:
        return fixed
    try:
        files = list(directory().glob("*.wav"))
    except OSError:
        return fixed
    for path in files:
        try:
            if (path.stat().st_mode & 0o777) != FILE_MODE:
                os.chmod(path, FILE_MODE)
                fixed += 1
        except OSError:
            continue
    return fixed


def sweep() -> int:
    """The cap and the expiry, run after every write. Returns how many were deleted.

    AFTER THE WRITE, NOT BEFORE, so the utterance just spoken is never the one thrown
    away to make room for itself.
    """
    _harden()
    try:
        files = sorted(directory().glob("*.wav"), key=lambda p: p.stat().st_mtime)
    except OSError:
        return 0
    # THE NEWEST IS NEVER A CANDIDATE. This runs straight after a write, and a cap set
    # smaller than one utterance would otherwise delete the recording that just triggered
    # it: the corpus would stay empty forever and nothing would say why. A cap overshot
    # by one utterance is the right failure; a cap that eats its own input is not.
    files = files[:-1]
    gone = 0
    cutoff = time.time() - config.RECORD_KEEP_DAYS * 86400
    budget = config.RECORD_MAX_MB * 1024 * 1024
    total = 0
    for path in files:
        try:
            total += path.stat().st_size
        except OSError:
            pass
    for path in files:
        try:
            size = path.stat().st_size
            old = path.stat().st_mtime < cutoff
        except OSError:
            continue
        if not old and total <= budget:
            break
        try:
            path.unlink()
        except OSError:
            continue
        total -= size
        gone += 1
    return gone


def stats() -> dict:
    """What /voice/health and `keel voice status` say about the corpus.

    ON WHETHER IT IS RECORDING, not merely on what is there: a directory with files in it
    and the flag now off reads very differently from one that is still filling, and the
    difference is the thing he would want to see at a glance.
    """
    out = {"recording": bool(config.RECORD_ENABLED), "count": 0, "megabytes": 0.0,
           "oldestDays": 0.0, "keepDays": config.RECORD_KEEP_DAYS,
           "maxMegabytes": config.RECORD_MAX_MB}
    _harden()
    try:
        files = list(directory().glob("*.wav"))
    except OSError:
        return out
    total = 0
    oldest = time.time()
    for path in files:
        try:
            st = path.stat()
        except OSError:
            continue
        total += st.st_size
        oldest = min(oldest, st.st_mtime)
    out["count"] = len(files)
    out["megabytes"] = round(total / (1024 * 1024), 1)
    out["oldestDays"] = round((time.time() - oldest) / 86400, 1) if files else 0.0
    return out


def delete_all() -> int:
    """Every recording, gone. What the follow-up card runs once the numbers are written.

    THE RECORDINGS ONLY. It globs `*.wav` rather than removing the directory, so a
    mistyped RECORD_DIR cannot take anything else with it.
    """
    gone = 0
    try:
        files = list(directory().glob("*.wav"))
    except OSError:
        return 0
    for path in files:
        try:
            path.unlink()
        except OSError:
            continue
        gone += 1
    return gone
