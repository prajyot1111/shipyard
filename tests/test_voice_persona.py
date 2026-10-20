"""Harbor enters and leaves a house, and the page protocol that re-arms after it (V13).

His own words, 2026-09-21, after living with V8's second voice for a day:

    "the way we should play this out is Harbor entering and exiting a house so that we
    keep the same Harbor voice; the usual flow: hey can you enter this house, I need to
    check some things; Harbor enters, the house responds, but it feels like Harbor is the
    one speaking; similarly it exits."

So the thing that moves is HARBOR, not the microphone, and three things follow: the words
he says to make it happen, the words he hears back, and the fact that one voice says all
of them. The voice half is asserted in `tests/test_voice_handoff.py`, beside the V8 claims
it reverses; the phrases and the protocol are here.

The voice package is Python 3.12 and this suite is 3.14, and nothing under `keel/` may
import it, so it is asked in a subprocess exactly as `tests/test_voice_connect.py` asks
`verbs.py`. `bin/keel-voice-selftest` is what drives the gateway itself, in the voice
interpreter, and it is where the switch is exercised end to end.
"""

import json
import subprocess
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SERVER = ROOT / "voice" / "harbor_voice" / "server.py"
DISPATCHER = ROOT / "voice" / "harbor_voice" / "dispatcher.py"


def ask(module: str, lines: list[str]) -> list:
    """Run `lines` against one voice module and return what they printed."""
    code = ("import json, sys; sys.path.insert(0, %r);"
            "from harbor_voice import %s;"
            "print(json.dumps([%s]))" % (str(ROOT / "voice"), module, ", ".join(lines)))
    out = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True)
    if out.returncode:
        raise unittest.SkipTest("the voice package would not import: " + out.stderr[-300:])
    return json.loads(out.stdout)


class TheWordsHeUsesToGoIn(unittest.TestCase):
    """V4's rule is untouched: an exact opening plus something that reads as a card id,
    never the model. V13 only adds the openings a person reaches for once the thing that
    moves is Harbor."""

    def test_his_own_word_connects(self):
        said = ["enter c-272", "enter card 272", "go into c-272",
                "step into the house on c272", "take me into card two seven two"]
        self.assertEqual(ask("verbs", [f"verbs.connect_target({one!r})" for one in said]),
                         ["c-272"] * len(said))

    def test_the_old_words_still_do_too(self):
        said = ["connect me to c-272", "put me through to c 2 7 2", "talk to c-272"]
        self.assertEqual(ask("verbs", [f"verbs.connect_target({one!r})" for one in said]),
                         ["c-272"] * len(said))

    def test_a_new_opening_still_needs_something_that_reads_as_a_card(self):
        """The half of the rule that makes a short word like "enter" safe to add: whatever
        follows has to parse as an id, and `card_id_in` answers "" the moment it meets a
        word that is not part of a number."""
        said = ["enter 272 into the form", "enter the building", "step into my office",
                "go into more detail", "enter"]
        self.assertEqual(ask("verbs", [f"verbs.connect_target({one!r})" for one in said]),
                         [""] * len(said))

    def test_connecting_by_description_is_untouched(self):
        """c-419: the sentence the table cannot parse still goes to Harbor as an ordinary
        question and comes back with a directive. Adding openings must not make a
        description parse as an id, because a wrong pin is the expensive mistake."""
        said = ["enter the house doing the voice thing",
                "connect me to the house that is doing the voice work"]
        self.assertEqual(ask("verbs", [f"verbs.connect_target({one!r})" for one in said]),
                         ["", ""])


class TheWordsHeUsesToComeOut(unittest.TestCase):
    """Whole utterances, matched in code before anything is dispatched or asked of a
    judge, exactly as V4's table is: a house can never mishear its way into keeping him."""

    def test_the_leaving_words_end_it(self):
        said = ["leave", "leave the house", "exit", "exit the house", "come back",
                "step out", "step outside"]
        self.assertEqual(ask("verbs", [f"verbs.is_disconnect({one!r})" for one in said]),
                         [True] * len(said))

    def test_back_to_harbor_still_does(self):
        said = ["back to harbor", "back to harbour", "disconnect", "hang up"]
        self.assertEqual(ask("verbs", [f"verbs.is_disconnect({one!r})" for one in said]),
                         [True] * len(said))

    def test_a_sentence_that_merely_contains_one_does_not(self):
        said = ["leave that for tomorrow", "exit the loop when it is done",
                "come back to that after lunch", "step out of the way of the drain"]
        self.assertEqual(ask("verbs", [f"verbs.is_disconnect({one!r})" for one in said]),
                         [False] * len(said))


class TheWordsHeActuallyUsedToComeOut(unittest.TestCase):
    """The lenient reading beside the table, from his second session of 2026-09-21.

    Inside c-302 he said "Okay, you can exit the pouse now" and then "You can go back".
    `is_disconnect` matches the WHOLE utterance against a fixed set, so both went to the
    house as questions; it answered "I can't end my own session, tap Stop on the deck" and
    he had to tap the header. A person does not say a table entry: he says a leave phrase
    wrapped in the words people wrap everything in, and speech recognition mangles the
    noun on the end.

    The table is the floor and is untouched. Every rule in the lenient reading is about a
    QUESTION being unable to trip it, because the expensive mistake is the other one:
    ending a conversation he was in the middle of.
    """

    LEAVES = [
        "Okay, you can exit the pouse now",       # observed 2026-09-21, his own voice
        "You can go back",                        # observed 2026-09-21, his own voice
        "okay you can leave the house now",
        "alright, exit the house",
        "can you go back to harbor",
        "please leave the house",
        "yeah come back now",
        "harbor, get out of here",
        "you can step out now",
        "ok that's all",
        "we're done",
        "hang up please",
        "so exit the mouse",                      # the same noun, misheard again
        "you can leave it now",
    ]
    STAYS = [
        "why did you exit the loop",
        "how do I go back to the previous version",
        "can you leave that file alone",
        "go back to the first decision",
        "leave that for tomorrow",
        "exit the loop when it is done",
        "come back to that after lunch",
        "step out of the way of the drain",
        "I went back to Harbor after lunch",
        "can you exit the house once the tests are green and you have pushed it",
        "what happens when you leave the house",
        "tell me how to get out of this branch",
    ]

    def leave(self, said: list[str]) -> list:
        return ask("verbs", [f"verbs.leave_intent({one!r})" for one in said])

    def test_his_own_two_sentences_are_a_leave(self):
        self.assertEqual(self.leave(self.LEAVES[:2]), [True, True])

    def test_every_way_he_might_wrap_it_is_a_leave(self):
        got = self.leave(self.LEAVES)
        self.assertEqual(got, [True] * len(self.LEAVES),
                         str([s for s, ok in zip(self.LEAVES, got) if not ok]))

    def test_a_question_that_merely_carries_a_leave_word_is_not(self):
        got = self.leave(self.STAYS)
        self.assertEqual(got, [False] * len(self.STAYS),
                         str([s for s, ok in zip(self.STAYS, got) if ok]))

    def test_the_table_is_still_the_floor_underneath_it(self):
        """Every whole utterance that ended a conversation before still does, so the
        lenient reading can only ever add."""
        said = ["back to harbor", "disconnect", "come back out", "step outside",
                "never mind the card"]
        self.assertEqual(self.leave(said), [True] * len(said))

    def test_the_gateway_leaves_on_the_lenient_reading_and_only_while_pinned(self):
        source = SERVER.read_text(encoding="utf-8")
        self.assertIn("verbs.leave_intent(said) and self.dispatcher.pinned()", source)


class TheLinesHeHears(unittest.TestCase):
    """Said by code, never by a model turn, so none of them can be wrong about where he
    is: the gateway is the thing that took the pin."""

    def test_going_in_and_coming_out_are_a_pair(self):
        got = ask("verbs", ["verbs.entering('c-272', 'Voice slice 5: connect me (V4)')",
                            "verbs.leaving('c-272')"])
        self.assertEqual(got[0], "Entering card 272, Voice slice 5.")
        self.assertEqual(got[1], "Leaving card 272. Back with you.")

    def test_a_refusal_says_which_act_it_refused(self):
        """He must never be left unsure whether the switch happened. The verb owns the
        REASON and it never said what was refused, so "c-419 is building right now" landed
        after "Connecting you now" and left him working out which side of the door he was
        on."""
        got, = ask("verbs", ["verbs.cannot_enter('c-419', "
                             "'c-419 is building right now. I have left your question "
                             "on the card.')"])
        self.assertEqual(got, "I cannot enter card 419: it is building right now. "
                              "I have left your question on the card.")

    def test_a_reason_that_does_not_open_with_the_card_is_copied_as_it_is(self):
        got, = ask("verbs", ["verbs.cannot_enter('c-419', "
                             "'The Mac is away, so I cannot reach that house.')"])
        self.assertEqual(got, "I cannot enter card 419: The Mac is away, so I cannot "
                              "reach that house.")

    def test_every_card_id_in_a_reason_is_said_the_way_he_says_it(self):
        """MEASURED, 2026-09-20: read aloud, `c-419` is "c dash four one nine". The verb's
        sentences are written to be read with the eyes too, so the spelling is fixed at the
        one place they become speech."""
        got, = ask("verbs", ["verbs.cannot_enter('c-008', "
                             "'I could not find a card called c-008.')"])
        self.assertNotIn("c-0", got)
        self.assertIn("card 8", got)


class TheAnswerIsCheckedAgainstWhatWasSpoken(unittest.TestCase):
    """V13 fix 2. The turn of 2026-09-21 that spoke one sentence of two and then finished
    as "the answer was spoken as it streamed": `spoke_parts` being non-empty reads as
    "some of it was spoken" and was used as "all of it was"."""

    def dispatch(self, lines: list[str]) -> list:
        code = ("import json, sys; sys.path.insert(0, %r);"
                "from harbor_voice import dispatcher;"
                "print(json.dumps([%s]))" % (str(ROOT / "voice"), ", ".join(lines)))
        out = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True)
        if out.returncode:
            raise unittest.SkipTest("the voice package would not import: "
                                    + out.stderr[-300:])
        return json.loads(out.stdout)

    def test_parts_that_cover_the_answer_leave_nothing_to_say(self):
        left, why = self.dispatch([
            "dispatcher.answer_left(['One sentence.', 'And another.'],"
            " 'One sentence. And another.')"])[0]
        self.assertEqual(left, "")
        self.assertEqual(why, "covered")

    def test_a_stream_that_stopped_short_leaves_the_remainder(self):
        left, why = self.dispatch([
            "dispatcher.answer_left(['One sentence.'],"
            " 'One sentence. And another.')"])[0]
        self.assertEqual(left, "And another.")
        self.assertEqual(why, "the stream stopped short")

    def test_nothing_spoken_leaves_the_whole_answer(self):
        left, _why = self.dispatch([
            "dispatcher.answer_left([], 'One sentence. And another.')"])[0]
        self.assertEqual(left, "One sentence. And another.")

    def test_a_divergence_leaves_the_whole_answer_rather_than_a_wrong_remainder(self):
        """Taking a remainder off a prefix that does not match would cut a sentence off at
        its start, which is worse than hearing one twice."""
        left, why = self.dispatch([
            "dispatcher.answer_left(['Let me check.'], 'Actually it is merged.')"])[0]
        self.assertEqual(left, "Actually it is merged.")
        self.assertIn("not the start", why)

    def test_markdown_is_not_a_difference_he_can_hear(self):
        """The cutter strips markdown off every part and the final answer keeps it, so the
        same words reach this comparison spelled two ways. Comparing them raw would call
        every bolded answer a divergence and read the whole thing out again."""
        left, _why = self.dispatch([
            "dispatcher.answer_left(['Phase two is merged.'],"
            " '**Phase two is merged.**')"])[0]
        self.assertEqual(left, "")


class ThePageProtocol(unittest.TestCase):
    """V13 fix 1. On 2026-09-21 a connect finished at 03:47:12, the page showed
    "listening" for sixty-two seconds, and no audio reached the gateway until he pressed
    the orb himself at 03:48:15. Neither end could say afterwards which half had failed,
    because neither end wrote anything down."""

    def source(self) -> str:
        return SERVER.read_text(encoding="utf-8")

    def test_a_trace_is_written_down_and_nothing_reads_it_back(self):
        """The whole of its safety. This socket is the only write path into the agent; a
        diagnostic message that could arm a microphone, move a pin or start a turn would
        be a second way in, on the dashboard's own origin."""
        body = self.source().split('elif kind == "trace":', 1)
        self.assertEqual(len(body), 2, "the gateway does not handle a trace at all")
        handler = body[1].split('elif kind ==', 1)[0]
        self.assertIn('log_event(\n', handler)
        self.assertIn('"page"', handler)
        for forbidden in ("GATEWAY.dispatcher.cut", "connect_to", "on_text", "dispatch(",
                          "listening = ", "hands_free = "):
            self.assertNotIn(forbidden, handler,
                             f"a trace reaches {forbidden}, which makes it an input")


    def test_a_listen_that_heard_nothing_is_visible_as_one_with_no_frames(self):
        """The useful shape of the record is an ABSENCE, so `frames` is written once per
        listen rather than once per chunk: a line every 32 ms would answer the question by
        drowning it."""
        source = self.source()
        self.assertIn("had_frames = False", source)
        self.assertIn("if not had_frames:", source)


    def test_an_expiry_re_arms_nothing_because_he_walked_away(self):
        """The one release nobody asked for. A hold runs out because he said nothing for
        the whole of it, so opening a microphone then is a microphone in his pocket; the
        page's own quiet cap would close it a minute later, which is a reason it is not a
        disaster and not a reason to open it. The selftest drives the real `expire_pin` and
        asserts no message; this is the guard on the branch that decides."""
        self.assertIn("if (card or spoken) and not expired:", self.source())

    def test_it_is_sent_after_the_words_rather_than_under_them(self):
        """`say_line` returns when the audio has been streamed, so the ordering is what
        keeps the page from opening a microphone into the tail of the gateway's own
        voice."""
        source = self.source()
        entering = source.split("verbs.entering(", 1)[1].split("return True", 1)[0]
        self.assertIn("self.rearm(", entering)
        self.assertLess(entering.index("tone=True"), entering.index("self.rearm("))


    def test_a_socket_event_names_the_turn_only_while_one_is_running(self):
        """A socket event usually happens BETWEEN turns, and naming the last finished turn
        would file a listen under the question before it."""
        body = DISPATCHER.read_text(encoding="utf-8").split("def log_event(", 1)[1]
        self.assertIn('turn.phase not in ("done", "held", "abandoned",', body)
        self.assertIn('"turn": turn.id if live else ""', body)


if __name__ == "__main__":
    unittest.main()
