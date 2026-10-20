"""Bosun's compaction and its handoff note (c-524, BO-6; docs/atlas/96-bosun.md).

Bosun compacts at `[console] compact_at` percent of `[console] context_window`: the two go in
its settings' `env` (`console.settings`) as `CLAUDE_AUTOCOMPACT_PCT_OVERRIDE` and
`CLAUDE_CODE_AUTO_COMPACT_WINDOW`, never in the launching process's environment, because a
`claude --bg` session is claimed by a daemon's spare process and does not inherit it (probed
2026-09-26 on 2.1.283, `state/cards/c-524/assets/probe-bg/`). Nothing in Keel watches the
meter: the harness compacts, in the same session, so the id and the app link never move.

Before it summarises, the harness runs `keel console handoff`, Bosun's PreCompact hook:

- It writes the HANDOFF NOTE, `state/console/handoff.md`, from the record rather than from a
  model turn (no hook can make Bosun take one first): when and why, the context used, the
  requests and asks the board holds, his last messages and Bosun's last reply. The five
  before it are kept as `handoff-<time>.md`.
- It adds a `compacted` row to `console.json`'s history, which the Journal shows.
- It prints the note, which the harness appends to the compaction's instructions, so the
  summary is told to keep it.

After the compaction the SessionStart hook (source `compact`) prints the memory and then the
note (`keel console memory`, `after_compact`), so Bosun picks up from the record.

It NEVER blocks a compaction (exit 2 would): whatever fails is one line in the note, and the
exit is always 0.
"""

import json
import subprocess
import time
from datetime import datetime, timezone
from pathlib import Path

from keel import atomicfile, console
from keel.config import Config

NOTE = "handoff.md"
KEEP = 5
READ_SECONDS = 5
LOCK_TRIES = 4
LAST_MESSAGES = 3
# What the harness itself puts in a user record: its reminders and slash-command echoes.
HARNESS_WRAPPERS = ("<system-reminder>", "<command-", "<local-command-")
# A note older than this after a compaction was not written for it: the hook runs just
# before the compaction, so its note is seconds old when SessionStart reads it.
FRESH_SECONDS = 600
# What Keel itself types into Bosun's session as a user turn (a relayed drain message is
# recorded as meta, so it is already left out): never his words (c-524 review r2.F3).
KEEL_PROMPTS = (console.START_PROMPT, console.RESUME_PROMPT)
SAID_MAX = 600
# The board reads the note carries, each a `kb` verb whose text is printed as it is.
READS = (("Requests, open and taken", ("console", "list")),
         ("Asks, open", ("console", "asks")))
INSTRUCTIONS = ("Keel's handoff note for Bosun follows. Keep in the summary what the user last asked "
                "and what you were in the middle of, and every request and ask id below with "
                "its state. The note is saved at {path}; after the compaction it is printed "
                "again below your memory.")


def note_dir(cfg: Config) -> Path:
    return Path(cfg.state_dir) / console.SETTINGS_DIR


def note_path(cfg: Config) -> Path:
    return note_dir(cfg) / NOTE


# ----- the transcript's side -----

def text_of(content) -> str:
    """The words in a message's content: a string, or its text blocks (never a tool result)."""
    if isinstance(content, str):
        return content.strip()
    if not isinstance(content, list):
        return ""
    parts = [block.get("text", "") for block in content
             if isinstance(block, dict) and block.get("type") == "text"]
    return "\n".join(part for part in parts if part).strip()


def clipped(text: str) -> str:
    text = " ".join(text.split())
    return text if len(text) <= SAID_MAX else text[:SAID_MAX - 1] + "…"


def said(records: list[dict]) -> tuple[list[str], str]:
    """His last messages, oldest first, and Bosun's last reply, from the main thread. A
    message Keel or the harness put there (a hook's output, a compaction summary) is not his."""
    his, reply = [], ""
    for record in records:
        if record.get("isSidechain") or record.get("isMeta") or record.get("isCompactSummary"):
            continue
        message = record.get("message") if isinstance(record.get("message"), dict) else {}
        text = text_of(message.get("content"))
        if not text or text.startswith(HARNESS_WRAPPERS) or text in KEEL_PROMPTS:
            continue
        if record.get("type") == "user":
            his.append(clipped(text))
        elif record.get("type") == "assistant":
            reply = clipped(text)
    return his[-LAST_MESSAGES:], reply


# ----- the board's side -----

def board_read(cfg: Config, argv: tuple[str, ...], run=subprocess.run) -> str:
    """One `kb` read, as the board prints it, or the line saying why it is missing. On the Mac
    the board is on the box, so this is its `kb` over HTTP, capped at READ_SECONDS."""
    try:
        done = run([str(cfg.root / "bin" / "kb"), *argv], capture_output=True, text=True,
                   timeout=READ_SECONDS)
    except (OSError, subprocess.TimeoutExpired) as error:
        return f"(not read: {type(error).__name__})"
    if done.returncode != 0:
        why = (done.stderr or "").strip().splitlines()
        return f"(not read: {why[-1] if why else f'kb exited {done.returncode}'})"
    return (done.stdout or "").strip() or "(none)"


# ----- the note -----

def compose(cfg: Config, hook: dict, records: list[dict], reads: list[tuple[str, str]],
            now: str) -> str:
    window = int(console.conf(cfg)["context_window"])
    facts = console.turn_facts(records, window)
    used = (f"{facts['used']:,} tokens, {facts['percent']}% of {window:,}"
            if facts["used"] is not None else "not read")
    his, reply = said(records)
    lines = ["# Bosun's handoff note", "",
             f"Written by Keel at {now}, before a compaction ({hook.get('trigger') or 'unknown'}), "
             f"session {hook.get('session_id') or 'unknown'}.",
             f"Context used before it: {used}.", ""]
    for title, text in reads:
        lines += [f"## {title}", "", text, ""]
    lines += ["## The user's last messages, oldest first", ""]
    lines += [f"- {text}" for text in his] or ["(none in the transcript's tail)"]
    lines += ["", "## Your last reply", "", reply or "(none in the transcript's tail)", ""]
    return "\n".join(lines)


def keep(cfg: Config) -> None:
    """The note before this one becomes `handoff-<its time>.md`; only the newest KEEP stay."""
    path = note_path(cfg)
    if path.is_file():
        written = datetime.fromtimestamp(path.stat().st_mtime, timezone.utc)
        path.replace(note_dir(cfg) / f"handoff-{written.strftime('%Y%m%dT%H%M%S.%f')}.md")
    for old in sorted(note_dir(cfg).glob("handoff-*.md"))[:-KEEP]:
        old.unlink(missing_ok=True)


def journal(cfg: Config, hook: dict, percent) -> bool:
    """A `compacted` row in console.json's history, under the tap lock (waited for briefly:
    a tap holds it for seconds). False when the lock stayed held."""
    at = f" at {percent}%" if percent is not None else ""
    what = f"compacted ({hook.get('trigger') or 'unknown'}){at}, handoff written"
    for attempt in range(LOCK_TRIES):
        with console.held_lock(cfg) as held:
            if held:
                data = console.read_state(cfg)
                console.write_state(cfg, console.noted(data, what, "harness", hook.get("session_id")))
                return True
        if attempt + 1 < LOCK_TRIES:
            time.sleep(0.5 * (attempt + 1))
    return False


def handoff(cfg: Config, hook: dict, run=subprocess.run) -> str:
    """Write the note and the Journal's row; the text the hook prints."""
    now = console.now_iso()
    path = Path(hook["transcript_path"]) if hook.get("transcript_path") else None
    records = console.tail_records(path) if path else []
    reads = [(title, board_read(cfg, argv, run)) for title, argv in READS]
    text = compose(cfg, hook, records, reads, now)
    note_dir(cfg).mkdir(parents=True, exist_ok=True)
    keep(cfg)
    atomicfile.write_text(note_path(cfg), text)
    # The row after the note is on disk, so it never says "handoff written" of one that is not.
    try:
        window = int(console.conf(cfg)["context_window"])
        if not journal(cfg, hook, console.turn_facts(records, window)["percent"]):
            text += "\n(The Journal's row was not written: a tap held the console lock.)\n"
    except Exception as error:      # the note is on disk: say so, and hand it over anyway
        text += f"\n(The Journal's row was not written: {type(error).__name__}: {error})\n"
    return INSTRUCTIONS.format(path=note_path(cfg)) + "\n\n" + text


def after_compact(cfg: Config, session_id: str | None) -> str:
    """What SessionStart adds below the memory after a compaction: the note written for THIS
    compaction (this session's, and fresh), or a line saying there is none. An older note
    handed over as current would be worse than none (c-524 review F3)."""
    path = note_path(cfg)
    try:
        text = path.read_text().strip()
        age = time.time() - path.stat().st_mtime
    except OSError:
        text, age = "", None
    # A compaction the harness named no session for owns no note: freshness alone is not proof.
    ours = bool(text and session_id) and f"session {session_id}." in text
    if ours and age is not None and age <= FRESH_SECONDS:
        return ("This session was just compacted. Keel's handoff note, written before it:\n\n"
                + text + "\n")
    return ("This session was just compacted, and Keel wrote no handoff note for it. Re-read "
            "the board (`kb console hook`, `kb show <card>`) before acting on anything "
            "from before the compaction.\n")


def session_start(cfg: Config, stdin) -> str:
    """`keel console memory`, the SessionStart hook: the memory, and after a compaction the
    note below it. A terminal run (no hook input) is the memory alone."""
    text = console.memory_text(cfg)
    hook = {} if stdin is None or stdin.isatty() else read_hook(stdin)
    if hook.get("source") == "compact":
        text += "\n" + after_compact(cfg, hook.get("session_id"))
    return text


def read_hook(stdin) -> dict:
    try:
        payload = json.loads(stdin.read() or "{}")
    except (ValueError, OSError):
        return {}
    return payload if isinstance(payload, dict) else {}


def main_hook(cfg: Config, stdin, run=subprocess.run) -> str:
    """`keel console handoff`: never raises, so a compaction is never blocked."""
    hook = read_hook(stdin)
    try:
        return handoff(cfg, hook, run)
    except Exception as error:      # the hook's one rule: the compaction goes on regardless
        return f"(Keel could not write Bosun's handoff note: {type(error).__name__}: {error})"
