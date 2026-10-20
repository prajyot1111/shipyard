"""narration: what a streamed house turn is allowed to say, and what it can never say.

The point of most of these is the CLOSED SET. Every sentence the module can produce is a
value in `TEMPLATES`, so the tests that matter are the ones that push a path, a card id and
a secret through a tool call and show that none of them can reach a sentence or a file.

`filler.progress_guard` itself lives in the voice venv on 3.12 and cannot be imported here,
so its rules are restated (the same numbers, from `voice/harbor_voice/filler.py`) and the
real guard is run against the same templates by the narrate section of
`bin/keel-voice-selftest`.
"""

import json
import re
import tempfile
import unittest
from pathlib import Path

from keel import narration

# The shape guard's own ceilings and screens, restated from voice/harbor_voice/filler.py.
PROGRESS_MAX_WORDS = 18
PROGRESS_MAX_CHARS = 140
SENTENCE_START = re.compile(r"(?:^|[.!?]\s+)")


def assistant(*blocks, parent=None):
    """One `stream-json` assistant record, the shape probe/README.md recorded."""
    return {"type": "assistant", "parent_tool_use_id": parent,
            "message": {"content": list(blocks)}}


def tool_use(name, **inputs):
    return {"type": "tool_use", "id": "toolu_x", "name": name, "input": dict(inputs)}


class VocabularyTest(unittest.TestCase):
    def test_every_tool_maps_to_a_sentence(self):
        for tool, action in narration.TOOL_ACTIONS.items():
            if action == narration.BASH:
                continue
            with self.subTest(tool=tool):
                self.assertIn(action, narration.TEMPLATES)

    def test_every_bash_verb_maps_to_a_sentence(self):
        for verb, action in narration.BASH_ACTIONS.items():
            with self.subTest(verb=verb):
                self.assertIn(action, narration.TEMPLATES)
        self.assertIn(narration.BASH_FALLBACK, narration.TEMPLATES)

    def test_an_unknown_tool_says_nothing_at_all(self):
        """Silence beats a wrong word: no sentence, not a vague one."""
        self.assertIsNone(narration.action_of("TodoWrite", {"todos": []}))
        self.assertIsNone(narration.action_of("SomeFutureTool", {}))
        self.assertIsNone(narration.action_of("", {}))


class TemplateShapeTest(unittest.TestCase):
    """Every sentence clears the gateway's shape guard by construction, not by luck."""


    def test_inside_the_word_and_character_ceilings(self):
        for action, text in narration.TEMPLATES.items():
            with self.subTest(action=action):
                self.assertLessEqual(len(text), PROGRESS_MAX_CHARS)
                self.assertLessEqual(len(re.findall(r"[A-Za-z']+", text)),
                                     PROGRESS_MAX_WORDS)


class BashVerbTest(unittest.TestCase):
    def test_the_first_bare_word_decides(self):
        self.assertEqual(narration.bash_action("git commit -m 'the plan'"), "version_control")
        self.assertEqual(narration.bash_action("make test"), "test")
        self.assertEqual(narration.bash_action("kb stage c-317 review"), "card")


    def test_a_directory_change_is_not_the_work(self):
        """`cd x && make test` is the tests, which is the commonest shape a house writes."""
        self.assertEqual(narration.bash_action("cd /home/x/wt && make test"), "test")
        self.assertEqual(narration.bash_action("cd /home/x && git log"), "version_control")


class StreamReadingTest(unittest.TestCase):
    def test_a_tool_call_record_names_its_action(self):
        record = assistant(tool_use("Edit", file_path="/home/x/keel/voice.py"))
        self.assertEqual(narration.actions_in(record), [("Edit", "edit")])

    def test_a_subagents_tool_call_is_not_the_houses_own_work(self):
        record = assistant(tool_use("Read", file_path="/x"), parent="toolu_parent")
        self.assertEqual(narration.actions_in(record), [])


    def test_two_tools_in_one_record_are_both_read(self):
        record = assistant(tool_use("Read", file_path="/a"), tool_use("Edit", file_path="/b"))
        self.assertEqual(narration.actions_in(record), [("Read", "read"), ("Edit", "edit")])

    def test_rubbish_is_not_a_crash(self):
        for record in (None, [], "assistant", {"type": "assistant"},
                       {"type": "assistant", "message": {"content": "hi"}}):
            with self.subTest(record=record):
                self.assertEqual(narration.actions_in(record), [])


class RepeatRuleTest(unittest.TestCase):
    """V5: never the same progress line twice in a row, compared by ACTION."""


    def test_two_templates_that_read_alike_are_still_compared_by_key(self):
        """Read and Glob say different sentences, so a string compare would let both
        through; Grep and Glob say the same one, so a string compare would catch that
        pair by accident. The key is what is meant either way."""
        self.assertFalse(narration.same_action("read", "search"))
        self.assertTrue(narration.same_action("search", "search"))


class LeaveTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.dir = Path(self.tmp.name) / "progress"

    def records(self):
        return [json.loads(p.read_text()) for p in sorted(self.dir.glob("*.json"))]

    def test_it_writes_the_inbox_shape_the_gateway_reads(self):
        narration.leave(self.dir, "edit", turn="abc123", tool="Edit")
        rec, = self.records()
        self.assertEqual(rec["text"], narration.TEMPLATES["edit"])
        self.assertEqual(rec["turn"], "abc123")
        self.assertEqual(rec["action"], "edit")
        self.assertEqual(rec["tool"], "Edit")
        self.assertIsInstance(rec["at"], float)

    def test_nothing_half_written_is_ever_left_behind(self):
        narration.leave(self.dir, "read", turn="t")
        self.assertEqual(list(self.dir.glob("*.part")), [])


    def test_no_directory_is_not_an_error(self):
        """The phone Harbor calls the same verb with nobody listening."""
        self.assertIsNone(narration.leave(None, "edit"))
        self.assertIsNone(narration.leave("", "edit"))

    def test_an_unwritable_inbox_is_a_quieter_wait_not_a_failed_turn(self):
        wall = Path(self.tmp.name) / "wall"
        wall.write_text("not a directory")
        self.assertIsNone(narration.leave(wall / "progress", "edit"))


class NarratorTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.dir = Path(self.tmp.name) / "progress"
        self.narrator = narration.Narrator(self.dir, turn="t1")

    def spoken(self):
        return [json.loads(p.read_text())["text"] for p in sorted(self.dir.glob("*.json"))]

    def test_a_run_of_the_same_action_leaves_one_line(self):
        for _ in range(4):
            self.narrator.on_record(assistant(tool_use("Read", file_path="/a")))
        self.assertEqual(self.spoken(), [narration.TEMPLATES["read"]])


    def test_an_action_may_come_round_again_after_another(self):
        """"Twice in a row" is the rule, not "twice in a turn": a read, an edit and a
        read again is three real changes of what it is doing."""
        for tool in ("Read", "Edit", "Read"):
            self.narrator.on_record(assistant(tool_use(tool, file_path="/a")))
        self.assertEqual(len(self.spoken()), 3)


    def test_a_narrator_with_no_inbox_still_tracks_the_repeat_rule(self):
        quiet = narration.Narrator(None)
        self.assertEqual(quiet.on_record(assistant(tool_use("Read", file_path="/a"))), [])
        self.assertEqual(quiet.last, "read")


class EgressTest(unittest.TestCase):
    """Nothing a tool was given can reach a sentence or the inbox. This is the whole of
    the argument for putting the vocabulary in Keel rather than screening it at the edge."""

    SECRETS = ("/home/ubuntu/keel/spaces/personal/.claude/headers.txt",
               "c-317", "ghp_realLookingTokenValue", "someone@example.com",
               "keel/c-317-voice-slice-7", "AKIAIOSFODNN7EXAMPLE")

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.dir = Path(self.tmp.name) / "progress"

    def test_no_input_can_reach_a_sentence(self):
        for secret in self.SECRETS:
            for tool in ("Edit", "Read", "Grep", "WebFetch", "Task"):
                with self.subTest(tool=tool, secret=secret):
                    action = narration.action_of(tool, {"file_path": secret, "url": secret,
                                                        "pattern": secret, "prompt": secret})
                    self.assertIn(narration.sentence(action),
                                  set(narration.TEMPLATES.values()))

    def test_no_shell_command_can_reach_a_sentence(self):
        for secret in self.SECRETS:
            with self.subTest(secret=secret):
                action = narration.bash_action(f"curl -H 'Authorization: {secret}' https://x")
                self.assertIn(narration.sentence(action),
                              set(narration.TEMPLATES.values()))

    def test_nothing_written_to_the_inbox_carries_an_input(self):
        narrator = narration.Narrator(self.dir, turn="t1")
        for secret in self.SECRETS:
            narrator.on_record(assistant(tool_use("Edit", file_path=secret)))
            narrator.on_record(assistant(tool_use("Bash", command=f"echo {secret}")))
        written = "\n".join(p.read_text() for p in sorted(self.dir.glob("*.json")))
        for secret in self.SECRETS:
            with self.subTest(secret=secret):
                self.assertNotIn(secret, written)


if __name__ == "__main__":
    unittest.main()
