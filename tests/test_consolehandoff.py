"""Bosun's compaction at 70% and its handoff note (c-524, BO-6; `keel/consolehandoff.py`).

Nothing here starts a Claude session. That the harness compacts a `--bg` session at the
threshold its settings' env names, runs PreCompact first and hands SessionStart the source
`compact` was probed on the box on 2026-09-26 (`state/cards/c-524/assets/probe-bg/`).
"""

import io
import json
import os
import subprocess
from pathlib import Path
from unittest import mock

from keel import authority, console, consolehandoff, consoletaps
from tests.test_console import SESSION, LifecycleCase

HOOK_INPUT = {"session_id": SESSION, "hook_event_name": "PreCompact", "trigger": "auto"}


class Stdin(io.StringIO):
    def isatty(self):
        return False


def kb_says(lists: str = "r-4  open  3m  a house: \"stuck\"", asks: str = "no open asks"):
    """A fake `subprocess.run` for the two board reads, recording what it was asked."""
    calls = []

    def run(argv, **kwargs):
        calls.append(argv)
        out = lists if argv[-1] == "list" else asks
        return subprocess.CompletedProcess(argv, 0, stdout=out + "\n", stderr="")
    run.calls = calls
    return run


class ThresholdTest(LifecycleCase):
    def test_the_threshold_rides_in_the_settings_env_where_the_page_draws_it(self):
        self.cfg.console = {"host": "mac", "context_window": 1_000_000, "compact_at": 70}
        env = console.settings(self.cfg)["env"]
        self.assertEqual((env["CLAUDE_CODE_AUTO_COMPACT_WINDOW"], env["CLAUDE_AUTOCOMPACT_PCT_OVERRIDE"]),
                         ("1000000", "70"))
        self.assertEqual(console.status(self.cfg)["context"]["compact_at"], 70,
                         "the page's mark and the harness's threshold are one number")

    def test_start_writes_the_precompact_hook_into_bosuns_settings(self):
        consoletaps.start(self.cfg)
        settings = json.loads(Path(self.fake.starts[0]["settings_path"]).read_text())
        (group,) = settings["hooks"]["PreCompact"]
        self.assertTrue(group["hooks"][0]["command"].endswith("bin/keel console handoff"))
        self.assertEqual(group["hooks"][0]["timeout"], console.HANDOFF_TIMEOUT)
        self.assertIn("CLAUDE_AUTOCOMPACT_PCT_OVERRIDE", settings["env"])

    def test_a_daemons_keel_card_is_emptied_so_bosun_is_never_a_house(self):
        """The process env of a --bg session is the daemon's spare's, which can carry the
        KEEL_CARD of the house that started it; the settings' env empties it."""
        self.assertEqual(console.settings(self.cfg)["env"]["KEEL_CARD"], "")

    def test_the_handoff_module_is_bosuns_own_authority(self):
        self.assertEqual(authority.authority_hit(self.cfg.root, str(self.cfg.root / "keel" / "consolehandoff.py")),
                         "keel/consolehandoff.py")


class HandoffCase(LifecycleCase):
    def transcript(self, records) -> Path:
        path = self.dir / "t.jsonl"
        path.write_text("\n".join(json.dumps(r) for r in records) + "\n")
        return path

    def hook(self, path=None, run=None, **extra) -> str:
        payload = dict(HOOK_INPUT, **extra)
        if path is not None:
            payload["transcript_path"] = str(path)
        return consolehandoff.main_hook(self.cfg, Stdin(json.dumps(payload)), run or kb_says())


RECORDS = [
    {"type": "user", "message": {"content": "first ask"}},
    {"type": "user", "message": {"content": console.START_PROMPT}},
    {"type": "user", "message": {"content": console.RESUME_PROMPT}},
    {"type": "user", "isMeta": True, "origin": {"kind": "peer", "name": "keel-drain"},
     "message": {"content": "Another Claude session sent a message: Keel drain: his answers to a-31"}},
    {"type": "user", "isMeta": True, "message": {"content": "a hook's output, not his"}},
    {"type": "user", "message": {"content": "<system-reminder>harness words</system-reminder>"}},
    {"type": "user", "message": {"content": [{"type": "tool_result", "content": "a tool's"}]}},
    {"type": "user", "message": {"content": "take r-4"}},
    {"type": "assistant", "isSidechain": True, "message": {"content": [{"type": "text", "text": "a subagent"}]}},
    {"type": "user", "message": {"content": "and file the fix"}},
    {"type": "user", "message": {"content": [{"type": "text", "text": "then tell me"}]}},
    {"type": "assistant", "timestamp": "2026-09-26T17:00:00Z",
     "message": {"model": "claude-opus-5-5", "content": [{"type": "text", "text": "Took r-4; filing k-9."}],
                 "usage": {"input_tokens": 700, "cache_read_input_tokens": 12}}},
]


class NoteTest(HandoffCase):
    def test_the_note_is_written_from_the_record_and_printed_as_the_summarys_instructions(self):
        run = kb_says()
        out = self.hook(self.transcript(RECORDS), run)
        note = consolehandoff.note_path(self.cfg).read_text()
        self.assertTrue(out.startswith("Keel's handoff note for Bosun follows. Keep in the summary what "
                                       "the user last asked and what you were in the middle of, and every "
                                       "request and ask id below"), out[:200])
        self.assertIn(str(consolehandoff.note_path(self.cfg)), out.split("\n\n")[0])
        self.assertIn(note, out)
        self.assertIn("before a compaction (auto)", note)
        self.assertIn("712 tokens, 71% of 1,000", note)
        self.assertIn('r-4  open  3m  a house: "stuck"', note)
        his = note.split("## The user's last messages, oldest first\n\n")[1].split("\n\n")[0].splitlines()
        self.assertEqual(his, ["- take r-4", "- and file the fix", "- then tell me"],
                         "his last three, never Keel's prompts, a hook's, the harness's, a tool's "
                         "or a subagent's")
        self.assertIn("## Your last reply\n\nTook r-4; filing k-9.", note)
        self.assertEqual([argv[1:] for argv in run.calls], [["console", "list"], ["console", "asks"]])

    def test_the_journal_gets_a_compacted_row(self):
        self.hook(self.transcript(RECORDS))
        last = console.read_state(self.cfg)["history"][-1]
        self.assertEqual((last["what"], last["by"], last["session"]),
                         ("compacted (auto) at 71%, handoff written", "harness", SESSION))

    def test_an_away_board_and_no_transcript_still_write_a_note_and_never_raise(self):
        def away(argv, **kwargs):
            raise subprocess.TimeoutExpired(argv, 5)
        out = self.hook(None, away)
        note = consolehandoff.note_path(self.cfg).read_text()
        self.assertIn("(not read: TimeoutExpired)", note)
        self.assertIn("Context used before it: not read.", note)
        self.assertIn(note, out)

    def test_a_failing_kb_says_why(self):
        def refused(argv, **kwargs):
            return subprocess.CompletedProcess(argv, 1, stdout="", stderr="kb: the board is away\n")
        self.hook(None, refused)
        self.assertIn("(not read: kb: the board is away)", consolehandoff.note_path(self.cfg).read_text())

    def test_an_unwritable_state_dir_is_one_line_and_the_compaction_goes_on(self):
        consolehandoff.note_dir(self.cfg).parent.mkdir(parents=True, exist_ok=True)
        consolehandoff.note_dir(self.cfg).write_text("a file where the directory should be")
        out = self.hook(self.transcript(RECORDS))
        self.assertTrue(out.startswith("(Keel could not write Bosun's handoff note: "), out)
        self.assertEqual(len(out.splitlines()), 1)

    def test_no_journal_row_claims_a_note_that_was_not_written(self):
        consolehandoff.note_dir(self.cfg).parent.mkdir(parents=True, exist_ok=True)
        with mock.patch.object(consolehandoff.atomicfile, "write_text", side_effect=OSError("disk full")):
            self.hook(self.transcript(RECORDS))
        self.assertEqual(console.read_state(self.cfg).get("history"), None)

    def test_a_held_tap_lock_skips_the_row_and_says_so(self):
        with console.held_lock(self.cfg) as held, mock.patch.object(consolehandoff.time, "sleep"):
            self.assertTrue(held)
            out = self.hook(None)
        self.assertIn("a tap held the console lock", out, "said in what the summary is given")
        self.assertEqual(console.read_state(self.cfg).get("history"), None)

    def test_only_the_five_before_it_are_kept(self):
        directory = consolehandoff.note_dir(self.cfg)
        for n in range(7):
            self.hook(None)
            path = consolehandoff.note_path(self.cfg)
            os.utime(path, (1_790_000_000 + n * 60, 1_790_000_000 + n * 60))
        kept = sorted(p.name for p in directory.glob("handoff-*.md"))
        self.assertEqual(len(kept), consolehandoff.KEEP)
        self.assertEqual(kept[-1], "handoff-20260921T141820.000000.md",
                         "each named for when it was written (the sixth, n=5)")
        self.assertTrue(consolehandoff.note_path(self.cfg).is_file())


class SessionStartTest(HandoffCase):
    def start(self, source, session=SESSION) -> str:
        return consolehandoff.session_start(self.cfg, Stdin(json.dumps(
            {"source": source, "session_id": session})))

    def test_after_a_compaction_the_note_follows_the_memory(self):
        self.hook(self.transcript(RECORDS))
        text = self.start("compact")
        memory = console.memory_text(self.cfg)
        self.assertTrue(text.startswith(memory))
        self.assertIn("This session was just compacted.", text)
        self.assertIn(consolehandoff.note_path(self.cfg).read_text().strip(), text)

    def test_a_start_or_a_resume_is_the_memory_alone(self):
        self.hook(self.transcript(RECORDS))
        for source in ("startup", "resume"):
            self.assertEqual(self.start(source), console.memory_text(self.cfg))

    def test_a_compaction_with_no_note_says_so_and_sends_bosun_to_the_board(self):
        text = self.start("compact")
        self.assertIn("Keel wrote no handoff note for it", text)
        self.assertIn("kb console hook", text)

    def test_a_compaction_with_no_session_owns_no_note(self):
        self.hook(self.transcript(RECORDS), session_id=None)
        self.assertIn("Keel wrote no handoff note for it", consolehandoff.session_start(
            self.cfg, Stdin(json.dumps({"source": "compact"}))))

    def test_a_journal_that_fails_after_the_note_still_hands_the_note_over(self):
        with mock.patch.object(consolehandoff.console, "write_state", side_effect=OSError("disk full")):
            out = self.hook(self.transcript(RECORDS))
        self.assertIn("Took r-4", out)
        self.assertIn("(The Journal's row was not written: OSError: disk full)", out)

    def test_a_note_from_another_session_is_never_handed_over(self):
        self.hook(self.transcript(RECORDS))
        text = self.start("compact", session="e40ffe2f-60a6-4141-b3ef-62abdd02aadc")
        self.assertNotIn("Took r-4", text)
        self.assertIn("Keel wrote no handoff note for it", text)

    def test_an_old_note_left_by_a_hook_that_failed_is_never_handed_over(self):
        self.hook(self.transcript(RECORDS))
        old = consolehandoff.note_path(self.cfg)
        stale = old.stat().st_mtime - consolehandoff.FRESH_SECONDS - 60
        os.utime(old, (stale, stale))
        consolehandoff.note_dir(self.cfg).chmod(0o500)      # the next hook cannot write
        self.addCleanup(consolehandoff.note_dir(self.cfg).chmod, 0o700)
        out = self.hook(self.transcript(RECORDS))
        self.assertTrue(out.startswith("(Keel could not write"), out)
        text = self.start("compact")
        self.assertNotIn("Took r-4", text)
        self.assertIn("Keel wrote no handoff note for it", text)

    def test_the_verb_reads_the_hook_input(self):
        self.hook(self.transcript(RECORDS))
        out = io.StringIO()
        with mock.patch.object(console.config_module, "load", return_value=self.cfg), \
                mock.patch.object(console.sys, "stdin", Stdin(json.dumps({"source": "compact", "session_id": SESSION}))), \
                mock.patch("sys.stdout", out):
            self.assertEqual(console.main(["memory"]), 0)
        self.assertIn("Keel's handoff note", out.getvalue())
