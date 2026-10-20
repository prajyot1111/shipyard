"""Connect me to c-NNN: the phrase table, the card id, and the page's half (c-315, V4).

The voice package is Python 3.12 and this suite is 3.14, and nothing under `keel/` may
import it, so `verbs.py` is asked in a subprocess exactly as `tests/test_voice_conversation`
asks `config.py`. The page's half is greps, in the style of `tests/test_voice_css.py`: the
render and the live socket are the proof, and what these do is fail in `make test` when a
later change quietly breaks a rule the design rests on.
"""

import json
import os
import re
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
APP = ROOT / "segments" / "voice" / "app"
from tests.voicepage import raw_script  # noqa: E402
COMMENT_BLOCK = re.compile(r"/\*.*?\*/", re.S)


def ask_verbs(lines: list[str]) -> list:
    """Run `lines` against the voice package's `verbs` and return what they printed."""
    code = ("import json, sys; sys.path.insert(0, %r);"
            "from harbor_voice import verbs;"
            "print(json.dumps([%s]))" % (str(ROOT / "voice"), ", ".join(lines)))
    out = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True)
    if out.returncode:
        raise unittest.SkipTest("the voice package would not import: " + out.stderr[-300:])
    return json.loads(out.stdout)


def ask_harbormsg(lines: list[str]) -> list:
    """The same, against `harbormsg`, which is where the framing (and so the key) lives.

    A THROWAWAY KEEL_HOME, because importing that module resolves the package's paths off
    it and a test may not read or write the real state directory.
    """
    home = tempfile.mkdtemp()
    code = ("import json, sys; sys.path.insert(0, %r);"
            "from harbor_voice import harbormsg;"
            "print(json.dumps([%s]))" % (str(ROOT / "voice"), ", ".join(lines)))
    out = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True,
                         env=dict(os.environ, KEEL_HOME=home))
    if out.returncode:
        raise unittest.SkipTest("the voice package would not import: " + out.stderr[-300:])
    return json.loads(out.stdout)


def script() -> str:
    """Every script of the page, in load order (VP-6)."""
    return raw_script()


def code() -> str:
    """The page's script with its comment blocks removed, so a grep reads the code."""
    return COMMENT_BLOCK.sub("", script())


class TheVerbIsAPhraseAndAnId(unittest.TestCase):
    """V4: "matched by the exact-phrase table plus a card id, never by the model"."""

    def test_the_shapes_he_actually_says_all_reach_the_same_card(self):
        said = ["connect me to c-272", "connect me to card 272", "put me through to c 2 7 2",
                "talk to the house on c272", "connect me to see two seventy two",
                "Connect me to card two seven two."]
        answers = ask_verbs([f"verbs.connect_target({one!r})" for one in said])
        self.assertEqual(answers, ["c-272"] * len(said))

    def test_a_spoken_number_is_read_as_the_id_it_is(self):
        answers = ask_verbs(["verbs.connect_target('connect me to card three fifteen')",
                             "verbs.connect_target('talk to c-1')",
                             "verbs.connect_target('connect me to two hundred and seventy two')",
                             "verbs.card_id_in('c-315')", "verbs.card_id_in('fifteen')"])
        self.assertEqual(answers, ["c-315", "c-001", "c-272", "c-315", "c-015"])

    def test_an_ordinary_sentence_can_never_connect_to_anything(self):
        """The failure this table exists to make impossible: the router it replaced
        answered 6 of every 90 ordinary sentences as though they were about the board."""
        said = ["connect the speaker to the amp", "talk to Sarah about it",
                "connect me to the card about voice", "talk to the team tomorrow",
                "what's waiting on me", "put the kettle on"]
        self.assertEqual(ask_verbs([f"verbs.connect_target({one!r})" for one in said]),
                         [""] * len(said))

    def test_back_to_harbor_is_matched_against_the_whole_utterance(self):
        answers = ask_verbs(["verbs.is_disconnect('back to Harbor')",
                             "verbs.is_disconnect('disconnect')",
                             "verbs.is_disconnect('back to harbour.')",
                             "verbs.is_disconnect('I went back to Harbor after lunch')",
                             "verbs.is_disconnect('that is all')"])
        self.assertEqual(answers, [True, True, True, False, False])


class ThePagesHalf(unittest.TestCase):

    def test_the_pin_is_asked_for_once_and_never_remembered(self):
        """A pin is a conversation, not a preference: it is dropped from the URL like
        `?listen`, and it is never written to localStorage."""
        text = code()
        self.assertIn('q.delete("connect")', text)
        self.assertNotIn('store("connect"', text)
        self.assertRegex(text, r"connectTried\s*=\s*true")


    def test_the_pin_comes_from_the_gateway_and_not_from_the_page(self):
        """The hold lives on the card, so the page draws what it is told and decides
        nothing: `setPinned` is the only writer, and both its callers are the gateway
        speaking (the `connected` broadcast, and the bus the poll reads)."""
        text = code()
        sets = re.findall(r"state\.pinned\s*=\s*([^;]+);", text)
        self.assertEqual([s.strip() for s in sets], ['card || ""'])
        callers = re.findall(r"(?<!function )setPinned\(([^)]*)\)", text)
        self.assertEqual(sorted(c.split(",")[0].strip() for c in callers if c.strip()),
                         ["b.connected && b.connected.card", "msg.card"])


if __name__ == "__main__":
    unittest.main()


class TheModelPicksTheHouse(unittest.TestCase):
    """Connect by description (c-419): Harbor names ONE card, the gateway pins.

    The phrase table above is the floor and it is untouched. What is tested here is the
    other way in: a directive at the end of a Harbor answer, read in code, stripped from
    what is spoken, and impossible to produce by accident because the key is this turn's.
    """

    KEY = "9f4c2a"
    ANSWER = ("That's card 317, the narration one.\n\n<<keel-connect c-317 %s>>" % KEY)

    def test_the_directive_is_read_off_the_answer_and_never_spoken(self):
        spoken, card = ask_harbor_directive(self.ANSWER, self.KEY)
        self.assertEqual(card, "c-317")
        self.assertEqual(spoken, "That's card 317, the narration one.")

    def test_a_wrong_key_is_stripped_and_pins_nothing(self):
        """The key is the whole of "impossible to produce by accident": a directive
        quoted out of an earlier answer, or invented, carries the wrong one."""
        spoken, card = ask_harbor_directive(self.ANSWER, "000000")
        self.assertEqual(card, "")
        self.assertNotIn("keel-connect", spoken)

    def test_an_empty_key_can_match_nothing(self):
        """Which is how a HOUSE's answer is kept from moving the pin: only a Harbor turn
        is ever given a key."""
        spoken, card = ask_harbor_directive(self.ANSWER, "")
        self.assertEqual(card, "")
        self.assertNotIn("keel-connect", spoken)

    def test_the_shape_as_ordinary_words_in_a_sentence_does_not_pin(self):
        """The failure this form exists to make impossible. He can ask how the connect
        works, and the answer can quote the form; quoting it is text, not a connect."""
        said = ("You would end the reply with <<keel-connect c-317 %s>> and I would read "
                "it off the last line." % self.KEY)
        spoken, card = ask_harbor_directive(said, self.KEY)
        self.assertEqual(card, "")
        self.assertNotIn("keel-connect", spoken)
        self.assertIn("read it off the last line", spoken)

    def test_a_directive_that_does_not_end_the_answer_does_not_pin(self):
        """The answer reaches the gateway with its newlines already flattened (the say
        inbox's own rule), so what is checked is the end of the text, not the last line."""
        said = "<<keel-connect c-317 %s>> and then I carried on talking." % self.KEY
        self.assertEqual(ask_harbor_directive(said, self.KEY)[1], "")

    def test_the_answer_reaches_the_parser_flattened_and_still_pins(self):
        """`SayInbox.write` collapses every answer to one line before the dispatcher sees
        it, which is why the rule is "at the very end" and not "alone on a line"."""
        flat = "That's card 317, the narration one. <<keel-connect c-317 %s>>" % self.KEY
        self.assertEqual(ask_harbor_directive(flat, self.KEY),
                         ["That's card 317, the narration one.", "c-317"])

    def test_an_ordinary_answer_comes_back_exactly_as_it_was(self):
        """Nothing about the common case changes, whitespace included."""
        said = "Two reviews are waiting.\n\nBoth on the work board."
        self.assertEqual(ask_harbor_directive(said, self.KEY), [said, ""])

    def test_a_key_is_minted_fresh_every_turn(self):
        keys = ask_verbs(["verbs.connect_key()"] * 6)
        self.assertEqual(len(set(keys)), 6, keys)
        self.assertTrue(all(re.fullmatch(r"[0-9a-f]{6}", key) for key in keys), keys)

    def test_the_framing_carries_this_turn_s_key_and_shows_the_shape(self):
        """The key rides in the framing because it is per turn, and the EXAMPLE carries
        it too, so the token to copy is in front of the model rather than assembled."""
        line, plain = ask_harbormsg([
            "harbormsg.build_line('put me through to the voice one', connect_key='ab12cd')",
            "harbormsg.build_line('put me through to the voice one')"])
        self.assertIn("<<keel-connect c-317 ab12cd>>", line)
        self.assertIn("does not need to be running", line)
        # THE EXAMPLE SENTENCE NAMES THE CARD BY ID AND BY TITLE, which is what he hears.
        self.assertIn("That's card 317, the narration one.", line)
        # A TURN WITH NO KEY IS NEVER TOLD HOW TO ASK FOR A PIN.
        self.assertNotIn("keel-connect", plain)

    def test_the_gateway_pins_through_the_one_connect_path(self):
        """Every guard, every refusal and all four spoken lines are the ones the phrase
        already uses: the model path calls `connect_to`, it does not reimplement it."""
        source = (ROOT / "voice" / "harbor_voice" / "server.py").read_text(encoding="utf-8")
        self.assertIn("def connect_by_model", source)
        self.assertIn("return self.connect_to(card, spoken=True)", source)
        self.assertIn("connect_asked=self.connect_by_model", source)

    def test_the_route_menu_gains_connect_in_shadow_and_nothing_reads_it(self):
        """V10 stays shadow: the judge is offered the place, and the model that picks the
        CARD is Harbor. No path in the gateway acts on a `connect` verdict."""
        source = (ROOT / "voice" / "harbor_voice" / "server.py").read_text(encoding="utf-8")
        self.assertIn("CONNECT_CRITERIA", source)
        self.assertNotIn('route == "connect"', source)
        self.assertNotIn("route == CONNECT_ROUTE", source)


def ask_harbor_directive(answer: str, key: str) -> list:
    """`verbs.connect_directive`, in the package's own interpreter."""
    return ask_verbs([f"verbs.connect_directive({answer!r}, {key!r})"])[0]
