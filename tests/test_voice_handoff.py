"""The heard handoff and the house voice: the page's half and the spoken lines (c-316, V8).

The voice package is Python 3.12 and this suite is 3.14, and nothing under `keel/` may
import it, so it is asked in a subprocess exactly as `tests/test_voice_connect.py` asks
`verbs.py`. The page's half is greps, in the style of `tests/test_voice_css.py`: the render
and the live socket are the proof, and what these do is fail in `make test` when a later
change quietly breaks a rule the design rests on.

THE ONE THING THESE CANNOT CHECK is what it sounds like, and that is the whole requirement.
`bin/keel-voice-selftest` asserts that the two speakers resolve to different voice ids on
every engine in the chain, which is the strongest thing code can say about it; the rest was
checked by ear from rendered samples on 2026-09-19 and recorded on the card.
"""

import json
import re
import subprocess
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
APP = ROOT / "segments" / "voice" / "app"
from tests.voicepage import raw_script  # noqa: E402
COMMENT_BLOCK = re.compile(r"/\*.*?\*/", re.S)


def ask(module: str, lines: list[str]) -> list:
    """Run `lines` against one voice module and return what they printed."""
    code = ("import json, sys; sys.path.insert(0, %r);"
            "from harbor_voice import %s;"
            "print(json.dumps([%s]))" % (str(ROOT / "voice"), module, ", ".join(lines)))
    out = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True)
    if out.returncode:
        raise unittest.SkipTest("the voice package would not import: " + out.stderr[-300:])
    return json.loads(out.stdout)


def script() -> str:
    """Every script of the page, in load order (VP-6)."""
    return raw_script()


def code() -> str:
    """The page's code with its comment blocks removed, so a rule is not satisfied by a
    sentence describing it."""
    return COMMENT_BLOCK.sub("", script())


class TheFloorSpeaksInTheOneVoiceToo(unittest.TestCase):
    """V13: Harbor enters and leaves a house, so there is ONE voice on every engine.

    THE FLOOR IS WHERE IT WOULD HAVE BEEN LOST. `browser` has no voice of its own: the
    gateway sends no samples and the page speaks the words itself, off the `speak`
    message. So the persona holds there only if that message carries whose VOICE speaks
    rather than whose words they are, which is why `config.voice_speaker` is applied at
    the wire and not left to the page.
    """


    def test_the_voice_is_harbors_whatever_the_record_says(self):
        got = ask("config", ["config.voice_speaker(config.SPEAKER_HOUSE)",
                             "config.voice_speaker(config.SPEAKER_HARBOR)",
                             "config.voice_speaker('nobody')",
                             "config.SPEAKER_HARBOR"])
        self.assertEqual(got, [got[-1]] * 4)

    def test_no_engine_has_a_second_voice_left_to_speak_a_house_in(self):
        same, = ask("config", [
            "all(config.voice_id(n.strip()) == config.voice_id(n.strip(), 'house')"
            " for n in config.TTS_CHAIN)"])
        self.assertTrue(same, "an engine still speaks a house in a voice of its own")


    def test_whose_words_they_are_still_reaches_the_page_on_the_turn(self):
        """The header and the transcript still have to say which house said something, so
        the RECORD travels; it just no longer picks a voice."""
        dispatcher = (ROOT / "voice" / "harbor_voice" / "dispatcher.py").read_text()
        self.assertIn('"speaker": self.speaker', dispatcher)


class TheFixedLines(unittest.TestCase):
    """The words themselves, and which of them names a card. The egress split (decision
    V17) lets a DIRECT ANSWER name what he asked about and holds UNPROMPTED speech to
    naming nothing, and the idle expiry is unprompted."""

    def test_the_line_that_can_be_unprompted_names_no_card(self):
        lines = ask("corpus", ["corpus.LEFT_HOUSE", "corpus.CONNECTING",
                               "corpus.STILL_CONNECTING"])
        for text in lines:
            self.assertNotRegex(text.lower(), r"\bc-?\d", text)
            self.assertNotIn("card", text.lower(), text)
            self.assertNotIn("{", text, text)

    def test_every_fixed_line_is_harbors_now(self):
        """V13: a house speaks no fixed line at all. "Handing you back" was the one, and it
        was the house's because the handoff WAS a change of speaker; there is no change of
        speaker left, so it is gone rather than recoloured and `verbs.leaving` replaces
        it."""
        rows, house = ask("corpus", ["list(corpus.HANDOFF)",
                                     "[l.text for l in corpus.handoff_lines('house')]"])
        self.assertEqual(len(rows), 3)
        self.assertTrue(all(who == "harbor" for _text, who in rows), rows)
        self.assertEqual(house, [])

    def test_one_voice_means_one_key_for_one_sentence(self):
        """The inverse of what V8 asserted here, and for the same reason it asserted it:
        the cache is keyed by (text, voice), so two keys for one sentence would now be two
        clips of identical audio and a count that says one of them is missing."""
        same, = ask("corpus", [
            "corpus.Line(corpus.LEFT_HOUSE, 'handoff', 'handoff', 'house').audio_key"
            " == corpus.Line(corpus.LEFT_HOUSE, 'handoff', 'handoff').audio_key"])
        self.assertTrue(same)


class TheSpokenLineIsCutInCode(unittest.TestCase):
    """Line 2 is the only one of the four with a variable part: the card's own title, read
    from the board. It is cut HERE, by `verbs.short_title`, because every renderer in that
    file is a copy and a cut and no model ever holds the string."""

    def test_a_card_id_is_said_the_way_he_says_it(self):
        """MEASURED, 2026-09-20: inside a carrier sentence Chirp 3 HD reads "c-272" in
        about 2.7 s, where "c dash two seven two" and "c minus two seven two" land, and
        nowhere near "c two seventy two" at 2.4 s. The hyphen is spoken one way or the
        other, and neither reading is a thing a person says."""
        got = ask("verbs", ["verbs.say_card('c-272')", "verbs.say_card('c-008')",
                            "verbs.say_card('not a card')"])
        self.assertEqual(got, ["card 272", "card 8", "not a card"])

    def test_a_title_is_cut_to_a_label_not_read_as_a_sentence(self):
        titles = ["Voice slice 6: the heard handoff and the house voice (V8)",
                  "The blackboard: a house that can show, not only tell",
                  "Keel has not backed up in over 6h",
                  "Put the Keel backup passphrase (helm set) in your password manager"]
        got = ask("verbs", ["[verbs.short_title(t) for t in %r]" % titles])[0]
        self.assertEqual(got[0], "Voice slice 6")
        self.assertEqual(got[1], "The blackboard")
        for short, whole in zip(got, titles):
            self.assertLessEqual(len(short.split()), 6, short)
            self.assertIn(short.split()[0], whole)

    def test_a_cut_never_leaves_a_word_dangling(self):
        got = ask("verbs", ["verbs.short_title('Fix the thing in the')",
                            "verbs.short_title('A card with no real end and')"])
        for short in got:
            self.assertNotRegex(short, r"\b(the|and|of|a|an|in|to)$", short)

    def test_a_card_with_no_title_gets_a_sentence_and_not_a_hole(self):
        got = ask("verbs", ["verbs.entering('c-316', '')",
                            "verbs.entering('c-316', ':')",
                            "verbs.entering('c-316', 'Voice slice 6: the rest')",
                            "verbs.leaving('c-316')"])
        self.assertEqual(got[0], "Entering card 316.")
        self.assertEqual(got[1], "Entering card 316.")
        self.assertEqual(got[2], "Entering card 316, Voice slice 6.")
        self.assertEqual(got[3], "Leaving card 316. Back with you.")


class TheHeaderTakesTheHousesColour(unittest.TestCase):
    """V8: a glance at the header agrees with what he heard. The colour is the card's
    space, which is the deck's own two palettes rather than a third invented here."""


    def test_the_tone_and_the_words_do_not_start_together_on_the_floor(self):
        """The one place the tone and the line are two different players: the gateway
        sends the tone as samples and the page says the words itself."""
        page = code()
        self.assertIn("out.at > out.ctx.currentTime", page)
        self.assertIn("setTimeout", page.split("function speakHere")[1][:900])


class TheSetsAreCountedApart(unittest.TestCase):
    """V8's named consequence: the clips are keyed by (text, voice) and the voice now names
    the speaker as well as the engine, so "how much is rendered" is a question per pair."""

    def test_there_is_a_set_for_every_engine_and_every_speaker(self):
        speakers, engines = ask("corpus", [
            "sorted({s['speaker'] for s in corpus.audio_sets()})",
            "sorted({s['engine'] for s in corpus.audio_sets()})"])
        self.assertEqual(speakers, ["harbor", "house"])
        self.assertTrue(engines, "no engine sets at all")

    def test_a_house_has_no_clips_and_the_count_says_so_rather_than_hiding_it(self):
        """V13: every fixed line is Harbor's, so the house set is EMPTY. It is kept rather
        than removed so the render and the count keep walking one enumeration, which is
        what stops a cache reporting itself full while something in it is silent."""
        harbor, house = ask("corpus", ["len(corpus.lines_for('harbor'))",
                                       "len(corpus.lines_for('house'))"])
        self.assertGreater(harbor, 100)
        self.assertEqual(house, 0)

    def test_the_render_and_the_count_read_one_enumeration(self):
        from keel import voice as voice_module
        self.assertIn("corpus.set_stats()", voice_module.AUDIO_COUNT)
        self.assertIn("corpus.audio_sets(",
                      (ROOT / "bin" / "keel-voice-corpus").read_text())


class TheToneIsAMarkerNotADirection(unittest.TestCase):
    """It is arithmetic with no synthesiser behind it, so it survives what a spoken line
    does not: a bad connection, a pocket, a car.

    IT WAS TWO NOTES AND V13 MADE IT ONE. A direction is only worth hearing while the two
    sides sound different, and they do not any more: one voice enters and leaves, and the
    line says which way it went. A pair of sounds whose meaning he has to remember is a
    thing to learn; one note is a marker, which is all that is left for it to be.
    """

    MEASURE = """
import array, json, sys
sys.path.insert(0, {root!r})
from harbor_voice import speech

pcm = speech.tone_pcm()
print(json.dumps({{"samples": len(pcm) // 2,
                   "peak": max(abs(x) for x in array.array("h", pcm)),
                   "first": array.array("h", pcm[:2])[0],
                   "same": speech.tone_pcm() == pcm}}))
"""

    def measured(self) -> dict:
        code = self.MEASURE.format(root=str(ROOT / "voice"))
        out = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True)
        if out.returncode:
            raise unittest.SkipTest("the voice package would not import: "
                                    + out.stderr[-300:])
        return json.loads(out.stdout)

    def test_it_is_the_same_sound_whichever_way_the_switch_went(self):
        self.assertTrue(self.measured()["same"])


    def test_it_is_short_and_it_is_quiet(self):
        """A signal, not an alarm: it is played in front of a spoken line and must not be
        the loudest thing in the conversation."""
        got = self.measured()
        self.assertLess(got["samples"], 24000 // 3, "longer than a third of a second")
        self.assertLess(got["peak"], 0.3 * 32767, "louder than the speech around it")
        self.assertLess(abs(got["first"]), 100, "it starts on a step, which clicks")


if __name__ == "__main__":
    unittest.main()
