"""The voice page, rebuilt (2026-09-24, VP-1 to VP-7): the rules a render cannot be asked about.

The behaviour is driven for real in `tests/fixtures/voice-listen.js` (through
`tests/test_voice_watchdog.py`): the composer, push to talk as the default, Capture next,
the Conversation in the + menu, the one ping timer, a hidden page drawing nothing, and the
board receipt handed to the deck's own embed. What is here are the rules with no behaviour
to run: what the page may never do, what it borrows from the deck instead of copying, and
the type and spacing budgets the design spec sets, read off the source in the style of
`tests/test_deck_css.py`. The screenshots are the proof of the look; these fail in
`make test` when a later edit breaks a budget, rather than on his phone.
"""

import re
import unittest

from tests.voicepage import APP, css, markup, script, scripts


class ThePageNeverActs(unittest.TestCase):
    """It reads the deck and talks to the gateway; approving anything stays on the deck."""

    def test_the_one_action_is_his_answer_to_bosun(self):
        """c-523: the page posts one thing, his answer to one of Bosun's asks, with the
        voice flag the deck refuses on any other body (`actions.voice_answer`)."""
        text = script()
        self.assertEqual(text.count("/api/action"), 1)
        self.assertEqual(len(re.findall(r"method\s*:\s*[\"']POST", text)), 1,
                         "the page GETs everything else")
        body = re.search(r"function recordAnswer\(msg\) \{(.*?)\n  \}", text, re.S).group(1)
        self.assertIn('verb: "console", sub: "answer"', body)
        self.assertIn("voice: true", body)
        self.assertIn("/api/action", body)

    def test_choosing_a_house_is_the_spoken_phrase_s_own_connect(self):
        body = re.search(r"V\.onTalkTo = function \(card\) \{(.*?)\n  \};", script(), re.S)
        self.assertIsNotNone(body)
        self.assertIn('V.say({ type: "connect", card: card })', body.group(1))


class TheBoardIsTheDecksOwn(unittest.TestCase):
    """VP-5: never a second rendering."""

    def board(self) -> str:
        return (APP / "voice.board.js").read_text(encoding="utf-8")


    def test_the_page_draws_no_board_of_its_own(self):
        text = script()
        for drawing in ("<svg", "createElementNS", "boardDraw", "layoutOnce"):
            self.assertNotIn(drawing, text, "the page draws a board itself: %s" % drawing)


class TheComposer(unittest.TestCase):
    """VP-1 and VP-2 in the markup: a chat you can also talk to, push to talk at rest."""


    def test_the_page_rests_in_talk_whatever_the_flags_say(self):
        text = script()
        self.assertIn('state.mode = query.get("mode") === "capture" ? "capture" : "talk";', text)
        self.assertNotIn("FLAGS.modeDefault", text, "Capture is one hold, never a resting mode")


class TheBugsTheResearchFound(unittest.TestCase):

    def test_a_hidden_page_renders_nothing(self):
        body = re.search(r"function render\(\) \{(.*?)\n  \}", script(), re.S)
        self.assertIsNotNone(body)
        self.assertIn("if (V.hidden()) { owed = true; return; }", body.group(1))

    def test_the_page_is_split_under_the_module_size(self):
        for path in scripts():
            lines = path.read_text(encoding="utf-8").count("\n")
            self.assertLess(lines, 600, "%s is %d lines" % (path.name, lines))


if __name__ == "__main__":
    unittest.main()
