"""sentences: cutting a streaming answer into things that can be said out loud (V12).

The cutter is pure, so it is tested as arithmetic is: bytes in, sentences out. Every case
here is a shape a house's answer really takes, and the ones that would be cut WRONGLY (an
abbreviation, a decimal, a version number, a file name, a code span) are the reason the
rule is not "split on a full stop".
"""

import unittest

from keel import sentences


def events(*deltas: str) -> list[dict]:
    """Feed the deltas one at a time and flush; every event, in order."""
    cutter = sentences.Cutter()
    out = []
    for delta in deltas:
        out.extend(cutter.feed(delta))
    out.extend(cutter.flush())
    return out


def cut(*deltas: str) -> list[str]:
    """Only what would be SPOKEN, in order."""
    return [event["text"] for event in events(*deltas) if event["type"] == "part"]


def chopped(text: str, size: int = 5) -> list[str]:
    """`text` as the stream really arrives: small pieces that fall anywhere."""
    return [text[at:at + size] for at in range(0, len(text), size)]


class CleanTest(unittest.TestCase):
    def test_whitespace_collapses_the_way_the_final_answer_s_does(self):
        self.assertEqual(sentences.clean("  two   lines\nof it  "), "two lines of it")

    def test_markdown_is_stripped_because_it_would_be_read_out_loud(self):
        self.assertEqual(sentences.clean("**phase two** is `merged` into *one*"),
                         "phase two is merged into one")
        self.assertEqual(sentences.clean("## Where it stands"), "Where it stands")
        self.assertEqual(sentences.clean("- the tests pass"), "the tests pass")
        self.assertEqual(sentences.clean("1. the tests pass"), "the tests pass")

    def test_a_link_is_read_as_its_words_and_never_as_its_url(self):
        self.assertEqual(sentences.clean("see [the plan](docs/plan.md) first"),
                         "see the plan first")


class SentenceEndTest(unittest.TestCase):
    def test_two_sentences_arrive_as_two(self):
        self.assertEqual(cut("Phase two is merged. The tests pass."),
                         ["Phase two is merged.", "The tests pass."])

    def test_a_sentence_split_across_deltas_is_still_one_sentence(self):
        """Which is the whole point: the deltas are tokens, not sentences."""
        self.assertEqual(cut("Phase two ", "is merged. ", "The tests pass."),
                         ["Phase two is merged.", "The tests pass."])

    def test_a_question_and_a_shout_end_sentences_too(self):
        self.assertEqual(cut("Did you mean phase one? I think so!"),
                         ["Did you mean phase one?", "I think so!"])

    def test_an_abbreviation_is_not_the_end_of_a_sentence(self):
        self.assertEqual(cut("It runs e.g. the tests, i.e. make test, and stops."),
                         ["It runs e.g. the tests, i.e. make test, and stops."])

    def test_a_decimal_is_not_the_end_of_a_sentence(self):
        self.assertEqual(cut("It took 4.2 seconds on version 2.1.278 of the binary."),
                         ["It took 4.2 seconds on version 2.1.278 of the binary."])

    def test_a_file_name_is_not_the_end_of_a_sentence(self):
        self.assertEqual(cut("I changed keel/converse.py and it is green."),
                         ["I changed keel/converse.py and it is green."])

    def test_a_code_span_is_never_cut_through(self):
        """A backtick span can hold a full stop, and half of one is unsayable."""
        self.assertEqual(cut("Run `make test. now` and wait."),
                         ["Run make test. now and wait."])

    def test_a_fenced_block_is_never_spoken(self):
        said = "Here it is:\n\n```\nmake test. run it.\n```\n\nThat is all."
        spoken = cut(said)
        self.assertEqual(spoken[-1], "That is all.")
        self.assertNotIn("make test. run it.", spoken)

    def test_a_list_item_ends_a_part_even_with_no_full_stop(self):
        """Houses answer in lists, and a list read as one run-on sentence is unbearable."""
        self.assertEqual(cut("Two things:\n- the tests pass\n- the branch is pushed\n"),
                         ["Two things:", "the tests pass", "the branch is pushed"])

    def test_a_blank_line_ends_a_part(self):
        self.assertEqual(cut("Where it stands\n\nThe tests pass"),
                         ["Where it stands", "The tests pass"])


class TheCapTest(unittest.TestCase):
    RAMBLE = "the branch is green and " * 40 + "that is all."

    def test_nothing_longer_than_the_cap_is_ever_handed_over(self):
        """A model that writes one enormous sentence must not hold the voice silent to
        the end of it, and must not hand the synthesiser a paragraph either."""
        parts = cut(self.RAMBLE)
        self.assertTrue(parts)
        self.assertTrue(all(len(part) <= sentences.MAX_CHARS for part in parts),
                        [len(part) for part in parts])

    def test_the_cap_cuts_at_a_word_and_never_mid_word(self):
        words = set(self.RAMBLE.replace(".", "").split())
        for part in cut(self.RAMBLE):
            for word in part.replace(".", "").split():
                self.assertIn(word, words, part)

    def test_the_whole_text_survives_the_cut(self):
        """Every word he would have heard, he still hears: cutting is not dropping."""
        said = "Phase two is merged. " + self.RAMBLE
        self.assertEqual(" ".join(cut(said)), sentences.clean(said))


class HoldingBackTest(unittest.TestCase):
    """A boundary that cannot be decided yet is WAITED for, not guessed at."""

    def test_a_part_carries_its_type_so_a_fence_can_travel_beside_it(self):
        self.assertEqual(events("Done."), [{"type": "part", "text": "Done."}])

    @staticmethod
    def spoken(events):
        return [event["text"] for event in events if event["type"] == "part"]

    def test_a_trailing_stop_waits_for_what_comes_next(self):
        """Both halves of the rule, in one conversation: the stop after "4" waits and
        turns out to be a decimal, and the stop after "Done" waits too, because the turn
        may not be over. The flush is what says it is."""
        cutter = sentences.Cutter()
        self.assertEqual(cutter.feed("It took 4."), [])
        self.assertEqual(self.spoken(cutter.feed("2 seconds. Done.")),
                         ["It took 4.2 seconds."])
        self.assertEqual(self.spoken(cutter.flush()), ["Done."])

    def test_flush_gives_back_whatever_is_left(self):
        cutter = sentences.Cutter()
        self.assertEqual(cutter.feed("No full stop here"), [])
        self.assertEqual(self.spoken(cutter.flush()), ["No full stop here"])

    def test_flush_twice_says_nothing_twice(self):
        cutter = sentences.Cutter()
        cutter.feed("Done.")
        first = self.spoken(cutter.flush())
        self.assertEqual(cutter.flush(), [])
        self.assertEqual(first, ["Done."])

    def test_whitespace_alone_is_never_a_part(self):
        self.assertEqual(cut("\n\n   \n"), [])


if __name__ == "__main__":
    unittest.main()


class TheFenceTest(unittest.TestCase):
    """A CODE BLOCK IS ON THE PAGE, NOT IN HIS EAR (V12, review round 2).

    Reading a fenced block aloud is unbearable and cutting one in half is worse, and the
    cap used to do exactly that: fed in small pieces, a long block was split at a space
    and spoken as two parts. So a fence is never spoken and never capped. It leaves the
    cutter as its own `fence` event carrying the info string and the raw body, with one
    short spoken line in its place, and the event is the hook the blackboard will use
    (a fence whose lang is `board`).
    """

    BLOCK = ("```python\n" + "x = 1 + 1  # padding line to make this long\n" * 8 + "```\n")

    def test_a_long_block_arriving_in_small_pieces_is_never_cut_in_half(self):
        """The repro from the review, exactly: the cap fired inside the fence."""
        spoken = cut(*chopped(self.BLOCK))
        self.assertEqual(spoken, [sentences.FENCE_SAID], spoken)

    def test_the_block_travels_as_an_event_with_its_language_and_its_body(self):
        fences = [event for event in events(*chopped(self.BLOCK))
                  if event["type"] == "fence"]
        self.assertEqual(len(fences), 1)
        self.assertEqual(fences[0]["lang"], "python")
        self.assertIn("x = 1 + 1", fences[0]["body"])
        self.assertNotIn("```", fences[0]["body"])
        self.assertEqual(fences[0]["body"].count("\n"), 8)

    def test_the_spoken_line_is_said_once_however_many_blocks_there_are(self):
        said = "First:\n\n```\na\n```\n\nSecond:\n\n```\nb\n```\n\nThat is both."
        spoken = cut(said)
        self.assertEqual(spoken.count(sentences.FENCE_SAID), 1, spoken)
        self.assertEqual([event["type"] for event in events(said)].count("fence"), 2)

    def test_a_board_block_is_never_claimed_by_the_cutter(self):
        """C1 (2026-09-23): the cutter used to speak "I have put that on the board." the
        moment a board fence CLOSED, before anybody knew whether the push landed, which is
        how a refused push was still announced as drawn (B19, B22). The line is built from
        the push report now, by the pen, so the cutter says nothing about a drawing at all."""
        said = 'Here:\n\n```board\nnode a box "a"\n```\n\nAnd that is it.'
        spoken = cut(said)
        self.assertNotIn("I have put that on the board.", spoken)
        self.assertEqual([event["lang"] for event in events(said)
                          if event["type"] == "fence"], ["board"])

    def test_the_cutter_does_not_decide_what_a_board_block_silences(self):
        """F7 of the lane C review: only a block that produced a push REPORT ends speech, and
        an empty block or a repeat does not. Whether a push reported is the pen's to know,
        so the cutter keeps cutting after a block and the pen (and `converse.events_into`)
        drops what follows a block that reported (N7)."""
        said = ('Here is the shape.\n\n```board\nnode a box "a"\n```\n\n'
                'The first box is the card.\n')
        self.assertEqual(cut(said), ["Here is the shape.", "The first box is the card."])

    def test_a_goodbye_after_a_board_block_still_leaves(self):
        said = 'Bye.\n\n```board\nnode a box "a"\n```\n\nTalk soon.\n\n<<keel-leave>>'
        self.assertIn("leave", [event["type"] for event in events(said)])

    def test_two_board_blocks_are_two_fences_and_no_sentence(self):
        said = '```board\nnode a box "a"\n```\n\n```board\nnode b box "b"\n```\n'
        self.assertEqual(cut(said), [])
        self.assertEqual([event["lang"] for event in events(said)
                          if event["type"] == "fence"], ["board", "board"])

    def test_an_unclosed_block_at_the_end_is_dropped_from_speech_the_same_way(self):
        spoken = cut("Here it is:\n\n```python\nx = 1\ny = 2")
        self.assertEqual(spoken, ["Here it is:", sentences.FENCE_SAID], spoken)
        fences = [event for event in events("Here it is:\n\n```python\nx = 1\ny = 2")
                  if event["type"] == "fence"]
        self.assertEqual(len(fences), 1)
        self.assertIn("y = 2", fences[0]["body"])

    def test_a_block_with_no_language_says_so_with_an_empty_one(self):
        fences = [event for event in events("```\nplain\n```\n")
                  if event["type"] == "fence"]
        self.assertEqual(fences[0]["lang"], "")

    def test_the_words_around_a_block_are_spoken_as_usual(self):
        said = "Here is the fix:\n\n```py\nx = 1\n```\n\nIt is on the branch already."
        self.assertEqual(cut(said), ["Here is the fix:", sentences.FENCE_SAID,
                                     "It is on the branch already."])


class BoardBlocksTest(unittest.TestCase):
    """The same grammar read off a FINISHED answer (K3, K10).

    A one-shot turn has no stream to cut, so the board blocks have to come out of the whole
    answer instead. It is the same rule in one pass: a `board` block is taken away to be
    drawn, and every other block is left exactly as it was written, because a code block is
    still part of what he was told.
    """

    def test_a_board_block_is_taken_out_and_the_rest_is_left_alone(self):
        text = ('Here is the shape:\n\n```board\nframe note "n"\ntext "hello"\n```\n\n'
                'And that is it.\n')
        rest, bodies = sentences.board_blocks(text)
        self.assertEqual(bodies, ['frame note "n"\ntext "hello"\n'])
        self.assertNotIn("```", rest)
        self.assertIn("Here is the shape:", rest)
        self.assertIn("And that is it.", rest)

    def test_a_code_block_is_not_a_board_block_and_survives_whole(self):
        text = "Try this:\n\n```python\nx = 1\n```\n"
        rest, bodies = sentences.board_blocks(text)
        self.assertEqual(bodies, [])
        self.assertEqual(rest, text)

    def test_several_board_blocks_come_back_in_order(self):
        text = '```board\nframe note "a"\n```\ntext\n```BOARD\nframe note "b"\n```\n'
        rest, bodies = sentences.board_blocks(text)
        self.assertEqual(bodies, ['frame note "a"\n', 'frame note "b"\n'])
        self.assertEqual(rest.strip(), "text", "the language is read case insensitively")

    def test_an_unclosed_board_block_is_still_a_block(self):
        """A turn cut short mid-fence has a body and no closing ticks. Leaving it in the
        answer would read its lines out loud, which is the one thing that must not happen."""
        rest, bodies = sentences.board_blocks('Drawing:\n\n```board\nframe note "n"\ntext "x"')
        self.assertEqual(bodies, ['frame note "n"\ntext "x"'])
        self.assertEqual(rest.strip(), "Drawing:")

    def test_an_answer_with_nothing_in_it_is_returned_as_it_came(self):
        self.assertEqual(sentences.board_blocks("just words"), ("just words", []))
        self.assertEqual(sentences.board_blocks(""), ("", []))


class TheLeaveDirectiveTest(unittest.TestCase):
    """The house may end the conversation itself, and the token is NEVER spoken.

    His own session of 2026-09-21: inside c-302 he asked the house to leave and the house
    answered "I can't end my own session, tap Stop on the deck". `prompts.SPOKEN` now tells
    it to say goodbye and end the answer with `<<keel-leave>>`, so the token travels in the
    one place the answer travels and this is where it is taken back out. It is held back
    exactly as a fence is: stripped by SHAPE wherever it sits, because read aloud it is
    gibberish however it got there, and acted on only at the very END of the answer.
    """

    def test_the_directive_leaves_as_an_event_and_is_never_spoken(self):
        said = "All right, talk later.\n\n<<keel-leave>>"
        self.assertEqual(cut(said), ["All right, talk later."])
        self.assertEqual([event["type"] for event in events(said)],
                         ["part", "leave"])

    def test_it_arrives_in_pieces_like_everything_else_and_still_never_reaches_a_part(self):
        spoken = cut(*chopped("Speak soon.\n\n<<keel-leave>>"))
        self.assertEqual(spoken, ["Speak soon."], spoken)

    def test_an_answer_that_carries_on_after_it_is_not_a_leave(self):
        """Quoting the form is text, not a goodbye: he can ask how leaving works out loud,
        and the answer can say the token. It is stripped either way, because nobody wants
        to hear it."""
        said = "You would end with <<keel-leave>> and I would read it off the end.\n"
        spoken = cut(said)
        self.assertNotIn("keel-leave", " ".join(spoken))
        self.assertEqual([event["type"] for event in events(said)], ["part"])

    def test_an_ordinary_answer_produces_no_leave_at_all(self):
        self.assertEqual([event["type"] for event in events("Phase two is merged.")],
                         ["part"])

    def test_the_same_rule_read_off_a_finished_answer(self):
        """The one-shot path (the phone Harbor's question, a turn typed into the ask box)
        has no stream to cut, so the directive comes off the whole text instead."""
        text, leaving = sentences.leave_directive("Goodbye for now. <<keel-leave>>")
        self.assertTrue(leaving)
        self.assertEqual(text.strip(), "Goodbye for now.")

    def test_a_directive_that_does_not_end_the_answer_leaves_nothing(self):
        text, leaving = sentences.leave_directive("<<keel-leave>> and then I carried on.")
        self.assertFalse(leaving)
        self.assertNotIn("keel-leave", text)

    def test_an_answer_with_no_directive_comes_back_exactly_as_it_was(self):
        self.assertEqual(sentences.leave_directive("Phase two is merged.\n"),
                         ("Phase two is merged.\n", False))


class LeadTest(unittest.TestCase):
    """The prose before the first board block, which is what a drawing turn may say (N7)."""

    def test_the_lead_is_what_comes_before_the_first_board_block(self):
        text = 'Here it is. Look.\n\n```board\nnode a box "a"\n```\n\nAfter.'
        self.assertEqual(sentences.clean(sentences.lead_of(text)), "Here it is. Look.")

    def test_a_code_block_before_the_board_block_stays_in_the_lead(self):
        text = 'Run:\n```python\nx = 1\n```\nThen:\n```board\nnode a box "a"\n```\n'
        self.assertIn("x = 1", sentences.lead_of(text))

    def test_no_board_block_means_the_whole_text_is_the_lead(self):
        self.assertEqual(sentences.lead_of("Just words."), "Just words.")

    def test_the_first_sentences_are_cut_at_real_sentence_ends(self):
        text = "It took 4.2 seconds. Then the drain claimed it. Then it started. Done."
        self.assertEqual(sentences.first_sentences(text, 2),
                         "It took 4.2 seconds. Then the drain claimed it.")
        self.assertEqual(sentences.first_sentences("One only", 2), "One only")

    def test_the_sentences_of_a_text_keep_their_own_words(self):
        self.assertEqual(sentences.sentences_of("A is e.g. this. B! C?"),
                         ["A is e.g. this.", "B!", "C?"])
