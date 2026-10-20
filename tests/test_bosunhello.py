"""Whether the user has said anything in Bosun's session (keel/bosunhello.py, c-678): read
from the transcripts of the sessions Bosun has had, never from a terminal. What Keel typed
(the start prompt) and what the harness put there (a reminder, a hook's output, a tool's
result) are not the user's words."""

import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from keel import bosunhello, console
from tests.helpers import make_config


def user(text, **flags):
    return {"type": "user", "message": {"role": "user", "content": text}, **flags}


class HelloTest(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.cfg = make_config(Path(tmp.name))
        self.cfg.host = "mac"
        self.cfg.console = {"host": "mac"}
        bosunhello.forget()
        self.addCleanup(bosunhello.forget)

    def started(self, session="s-1", history=()):
        Path(self.cfg.state_dir).mkdir(parents=True, exist_ok=True)
        console.write_state(self.cfg, {"session_id": session,
                                       "history": [{"what": "start", "session": one} for one in history]})

    def transcript(self, session, records, mode="w"):
        path = console.config_dir(self.cfg) / "projects" / "x" / f"{session}.jsonl"
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, mode) as handle:
            for record in records:
                handle.write(json.dumps(record) + "\n")
        return path

    def test_a_bosun_never_started_has_no_hello(self):
        self.assertFalse(bosunhello.said(self.cfg))

    def test_what_keel_and_the_harness_put_there_is_not_a_hello(self):
        self.started()
        self.transcript("s-1", [
            user(console.START_PROMPT),
            {"type": "assistant", "message": {"role": "assistant", "content": [{"type": "text", "text": "I am up."}]}},
            user("<system-reminder>read your memory</system-reminder>"),
            user("a relayed drain message", isMeta=True),
            user("in a subagent", isSidechain=True),
            user([{"type": "tool_result", "content": "ok"}]),
        ])
        self.assertFalse(bosunhello.said(self.cfg))

    def test_the_prompts_keel_types_name_the_user_and_neither_is_a_hello(self):
        """c-731: the prompt and the check change together, since the check matches the
        prompt word for word."""
        self.assertEqual(console.START_PROMPT,
                         "You are Bosun, started fresh by the user's tap. Your memory is in your "
                         "context above. Say in one line that you are up, then wait for the user.")
        self.assertEqual(console.RESUME_PROMPT,
                         "Started again by the user's tap, after a Stop. Carry on from where you "
                         "were; if nothing was in hand, say in one line that you are back and wait.")
        for prompt in (console.START_PROMPT, console.RESUME_PROMPT):
            self.assertFalse(bosunhello.own(user(prompt)), prompt)

    def test_the_users_own_message_is_a_hello_and_is_found_as_the_file_grows(self):
        self.started()
        self.transcript("s-1", [user(console.START_PROMPT)])
        self.assertFalse(bosunhello.said(self.cfg))
        self.transcript("s-1", [user("hello Bosun")], mode="a")
        self.assertTrue(bosunhello.said(self.cfg))

    def test_a_line_caught_half_written_is_read_once_it_is_whole(self):
        self.started()
        path = self.transcript("s-1", [user(console.START_PROMPT)])
        whole = json.dumps(user("hello")) + "\n"
        with open(path, "a") as handle:
            handle.write(whole[:20])
        self.assertFalse(bosunhello.said(self.cfg))
        with open(path, "a") as handle:
            handle.write(whole[20:])
        self.assertTrue(bosunhello.said(self.cfg))

    def test_a_hello_in_an_earlier_session_still_counts_after_a_restart(self):
        self.started("s-2", history=("s-1", "s-2"))
        self.transcript("s-1", [user("hello Bosun")])
        self.transcript("s-2", [user(console.RESUME_PROMPT)])
        self.assertTrue(bosunhello.said(self.cfg))

    def test_once_a_hello_is_found_no_transcript_is_looked_for_again(self):
        """It is asked on every state: a found hello costs nothing after (review F11)."""
        self.started("s-2", history=("s-1", "s-2"))
        self.transcript("s-1", [user("hello Bosun")])
        self.assertTrue(bosunhello.said(self.cfg))
        with mock.patch.object(console, "transcript_of", side_effect=AssertionError("looked again")):
            self.assertTrue(bosunhello.said(self.cfg))

    def test_a_session_this_user_cannot_read_is_hidden_not_silent(self):
        """A Bosun under another user keeps its transcripts to itself: that is "cannot see",
        which is not "no hello" (review F20)."""
        self.started()
        path = self.transcript("s-1", [user("hello Bosun")])
        self.assertFalse(bosunhello.hidden(self.cfg), "one it can read is not hidden")
        bosunhello.forget()
        with mock.patch("builtins.open", side_effect=PermissionError(13, "Permission denied", str(path))):
            self.assertFalse(bosunhello.said(self.cfg))
            self.assertTrue(bosunhello.hidden(self.cfg))

    def test_a_folder_of_sessions_this_user_cannot_list_is_hidden_too(self):
        self.started()
        projects = console.config_dir(self.cfg) / "projects"
        projects.mkdir(parents=True)
        self.assertFalse(bosunhello.hidden(self.cfg), "an empty folder it can list hides nothing")
        with mock.patch.object(bosunhello.os, "access", return_value=False):
            self.assertTrue(bosunhello.hidden(self.cfg))

    def test_a_bosun_never_started_hides_nothing(self):
        self.assertFalse(bosunhello.hidden(self.cfg))


if __name__ == "__main__":
    unittest.main()
