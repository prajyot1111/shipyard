"""Conversation mode, pause and resume: the page's half, as greps (c-314, V2 and V3).

A stdlib suite cannot open a microphone or lay out a page, so these are greps in the style
of `tests/test_voice_css.py`, and the same honesty applies: the render and the live socket
are the proof, and what these do is fail in `make test` when a later change quietly breaks
one of the rules the design rests on.

The rules, in the order they are checked:

1. ONE DISPLAY STATE, COMPUTED IN ONE PLACE. `paused` and `partial` sit on top of the bus
   state rather than beside it, so exactly one function decides which word wins, and the
   precedence it uses is the one the Atlas states.
2. EVERY STATE THE MACHINE CAN BE IN HAS A LABEL AND A LOOK. A state the orb cannot say is
   a state he cannot read.
3. THE LISTEN IN HAND IS CARRIED AND CHECKED. `start` sends a listen number and `endpoint`
   is dropped unless it names the same one: this is what stops an endpoint from the
   previous listen ending the next one, which only became possible when the microphone
   started re-arming itself.
4. A PAUSE REALLY CLOSES THE MICROPHONE. Stopped tracks, not a muted gain.
5. THE CONVERSATION CANNOT RUN AWAY. A cap on listens that hear nothing, and an end rather
   than a retry when the microphone will not open.
6. THE PHRASES LIVE IN ONE PLACE. The page reads them from `flags.js`; the table itself is
   `verbs.py`'s.
7. THE PAGE STILL HAS ONE FLUSH PATH. `end` is the only message that dispatches, so a
   quiet endpoint is answered with `cut`.
"""

import json
import re
import subprocess
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
APP = ROOT / "segments" / "voice" / "app"
COMMENT_BLOCK = re.compile(r"/\*.*?\*/", re.S)
COMMENT_LINE = re.compile(r"^\s*//.*$", re.M)


# The page's scripts, read as one text in load order (VP-6), comments stripped: this file's
# comments quote the very code the greps below look for.
from tests.voicepage import css, markup, script  # noqa: E402


def flags() -> dict:
    """The page's flags, built by the gateway's own config in its own interpreter.

    The voice package is Python 3.12 and this suite is 3.14, and nothing under `keel/` may
    import it (the Atlas says so), so it is asked in a subprocess exactly as the selftest
    does it rather than imported here.
    """
    code = ("import json, sys; sys.path.insert(0, %r);"
            "from harbor_voice import config;"
            "print(json.dumps(config.flags_for_page()))" % str(ROOT / "voice"))
    out = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True)
    if out.returncode:
        raise unittest.SkipTest("the voice package would not import: " + out.stderr[-300:])
    return json.loads(out.stdout)


class DisplayState(unittest.TestCase):
    """Rule 1: one machine, one place that decides."""

    def test_one_function_computes_the_display_state(self):
        text = script()
        self.assertEqual(text.count("function displayState()"), 1,
                         "there must be exactly one displayState()")
        # Everything that draws reads its answer rather than the bus directly.
        self.assertIn("var s = displayState();", text,
                      "render() must read displayState(), not state.bus.state")

    def test_the_precedence_is_down_then_stalled_then_paused_then_partial(self):
        """`stalled` joined the order on 2026-09-21 (V13): it is a pause with a fault
        behind it, so it beats `paused` and says which of the two it is. The rest of that
        card's rules, including what beats the bus, live in
        `tests/test_voice_watchdog.py`."""
        body = re.search(r"function displayState\(\)\s*\{(.*?)\n  \}", script(), re.S)
        self.assertIsNotNone(body, "displayState() is not where this test can read it")
        order = re.findall(r'return "(\w+)"|return state\.bus\.state', body.group(1))
        self.assertEqual(order[:4], ["down", "stalled", "paused", "partial"],
                         "down beats stalled beats paused beats partial beats the bus")


class EveryStateIsReadable(unittest.TestCase):
    """Rule 2: a state the orb cannot say is a state he cannot read."""

    STATES = ("down", "paused", "partial", "listening", "thinking", "speaking", "idle")

    def test_every_state_has_a_label(self):
        text = script()
        body = re.search(r"function barLabel\(s\)\s*\{(.*?)\n  \}", text, re.S)
        self.assertIsNotNone(body, "barLabel() is not where this test can read it")
        said = body.group(1)
        for state in ("down", "paused", "partial"):
            self.assertIn('s === "%s"' % state, said,
                          "barLabel says nothing about %s" % state)
        for state in ("idle", "listening", "thinking", "speaking"):
            self.assertIn(state, text, "no label anywhere for %s" % state)


    def test_reduced_motion_stops_everything_that_moves_by_itself(self):
        """VP-7: the CSS animations stop, and the waveform, which is drawn by script,
        paints each state still and schedules nothing."""
        sheet = css()
        block = re.search(r"@media \(prefers-reduced-motion: reduce\)\s*\{(.*?)\n\}",
                          sheet, re.S)
        self.assertIsNotNone(block)
        self.assertIn(".v-dots i", block.group(1))
        self.assertIn(".v-live", block.group(1))
        wave = (APP / "voice.wave.js").read_text(encoding="utf-8")
        self.assertIn("if (V.reducedMotion()) return;", wave,
                      "the waveform's loop must stop under reduced motion")


class TheListenInHand(unittest.TestCase):
    """Rule 3, and it is the one the planner asked for by name."""

    def test_start_carries_the_listen_number(self):
        text = script()
        start = re.search(r'say\(\{ type: "start".*?\}\);', text, re.S)
        self.assertIsNotNone(start, "the start message is not where this test can read it")
        self.assertIn("listen: state.listen", start.group(0))
        self.assertIn("conversation:", start.group(0))


    def test_an_endpoint_for_another_listen_is_dropped(self):
        text = script()
        self.assertIn("if (msg.listen !== undefined && msg.listen !== state.listen) return;",
                      text, "a stale endpoint must not end the listen in hand")

    def test_a_pause_retires_the_listen_before_it_closes_anything(self):
        body = re.search(r"function pauseVoice\(why\)\s*\{(.*?)\n  \}", script(), re.S)
        self.assertIsNotNone(body)
        said = body.group(1)
        self.assertLess(said.index("state.listen += 1;"), said.index("closeMic();"),
                        "the tap wins the race by retiring the listen first")
        self.assertIn("if (state.paused) return;", script(),
                      "and a paused page ignores an endpoint outright")


class PauseReallyCloses(unittest.TestCase):
    """Rule 4: closed, not muted."""

    def test_close_mic_stops_the_tracks(self):
        body = re.search(r"function closeMic\(\)\s*\{(.*?)\n  \}", script(), re.S)
        self.assertIsNotNone(body, "closeMic() is not where this test can read it")
        said = body.group(1)
        self.assertIn("getTracks()", said)
        self.assertIn("tr.stop()", said)
        self.assertIn("mic.ctx.close()", said)
        self.assertNotIn("out.ctx.close", said,
                         "the playback context must survive a pause, or the next answer "
                         "is silent on iOS")


    def test_pause_closes_and_resume_opens_a_fresh_window(self):
        text = script()
        self.assertIn("closeMic();", re.search(
            r"function pauseVoice\(why\)\s*\{(.*?)\n  \}", text, re.S).group(1))
        resume = re.search(r"function resumeVoice\(\)\s*\{(.*?)\n  \}", text, re.S)
        self.assertIn('armListen("resume")', resume.group(1))

    def test_an_interrupted_audio_context_pauses_visibly(self):
        """iOS takes the audio away for a call, Siri or the control centre, and does not
        give it back on its own. A conversation that sat there with a dead context would
        say it was listening while nothing was."""
        text = script()
        self.assertEqual(text.count("function watchContext(ctx)"), 1)
        body = re.search(r"function watchContext\(ctx\)\s*\{(.*?)\n  \}", text, re.S)
        self.assertIsNotNone(body)
        said = body.group(1)
        self.assertIn('"interrupted"', said,
                      "Safari's own state, and the one that matters here")
        self.assertIn('"suspended"', said)
        self.assertIn("pauseVoice(", said,
                      "an interrupted context must reach the SAME pause a tap makes, so "
                      "a tap resumes it")
        self.assertIn("!state.conversation || state.paused", said,
                      "a suspended context before the first press is ordinary")


    def test_leaving_the_foreground_pauses_on_both_events(self):
        text = script()
        self.assertIn('document.addEventListener("visibilitychange"', text)
        self.assertIn('window.addEventListener("pagehide"', text)
        self.assertEqual(text.count('pauseVoice("hidden")'), 2,
                         "both events pause, and for the same reason")


class NoRunaway(unittest.TestCase):
    """Rule 5: the worst failure this slice could have is a microphone that reopens for
    ever in his pocket."""

    def test_a_run_of_quiet_listens_ends_the_conversation(self):
        body = re.search(r"function heardNothing\(\)\s*\{(.*?)\n  \}", script(), re.S)
        self.assertIsNotNone(body, "heardNothing() is not where this test can read it")
        said = body.group(1)
        self.assertIn("state.quiet += 1;", said)
        self.assertIn("FLAGS.quietLimit", said, "the cap comes from the gateway, not here")
        self.assertIn("endConversation(", said)


    def test_the_wake_lock_is_held_only_while_one_is_live(self):
        text = script()
        self.assertIn("dropWake();", re.search(
            r"function pauseVoice\(why\)\s*\{(.*?)\n  \}", text, re.S).group(1))
        self.assertIn("dropWake();", re.search(
            r"function endConversation\(why\)\s*\{(.*?)\n  \}", text, re.S).group(1))
        self.assertIn("holdWake();", re.search(
            r"function openConversation\(why, ev\)\s*\{(.*?)\n  \}", text, re.S).group(1))

    def test_the_wake_lock_is_taken_only_where_a_gesture_took_it(self):
        """Opening a conversation and resuming one are both taps. Nothing else takes the
        lock: coming back to the foreground does not, because coming back does not
        resume, it leaves the page paused for a tap."""
        text = script()
        self.assertEqual(text.count("holdWake();"), 2,
                         "only openConversation and resumeVoice may take it")
        visible = re.search(r'addEventListener\("visibilitychange".*?\}\);', text, re.S)
        self.assertIsNotNone(visible)
        self.assertNotIn("holdWake", visible.group(0),
                         "returning to the foreground must not re-take the lock: it "
                         "leaves the page paused, and his tap is what resumes it")

    def test_a_microphone_that_will_not_open_ends_it_on_the_first_failure(self):
        """Deliberately stricter than the N consecutive failures the review asked for:
        `openMic`'s reject is the platform refusing, and asking a platform that just
        refused is how a retry loop starts."""
        text = script()
        catch = re.search(r"\.catch\(function \(err\) \{(.*?)\n    \}\);",
                          text, re.S)
        self.assertIsNotNone(catch)
        said = catch.group(1)
        self.assertIn('endConversation("the microphone would not open")', said)
        self.assertNotIn("armListen", said, "no retry: one failure ends it")

    def test_the_listen_is_armed_only_after_playback_has_really_ended(self):
        body = re.search(r"function armListen\(reason\)\s*\{(.*?)\n  \}", script(), re.S)
        self.assertIsNotNone(body)
        self.assertIn("whenPlaybackEnds(", body.group(1),
                      "arming before the answer has finished playing means the detector "
                      "hears the gateway's own tail")

    def test_the_guard_is_shorter_than_the_detector_s_minimum_speech(self):
        text = script()
        guard = int(re.search(r"var REARM_GUARD_MS = (\d+);", text).group(1))
        self.assertLess(guard, 300, "the guard must sit under VAD_MIN_SPEECH (0.3 s), so "
                                    "an echo that survives it still cannot arm a hangover")
        self.assertGreater(guard, 0)


class OneTable(unittest.TestCase):
    """Rule 6: the conversation words are matched in two places and live in one."""


    def test_the_gateway_serves_them(self):
        served = flags()
        self.assertIn("that's all", served["endPhrases"])
        self.assertIn("hold on", served["pausePhrases"])
        self.assertGreaterEqual(served["quietLimit"], 1)

    def test_the_page_matches_whole_utterances_only(self):
        text = script()
        body = re.search(r"function isPhrase\(table, said\)\s*\{(.*?)\n  \}", text, re.S)
        self.assertIsNotNone(body)
        self.assertIn("indexOf(normalise(said))", body.group(1),
                      "a substring match would make this a classifier with no "
                      "measurements behind it")

    def test_the_page_and_the_gateway_normalise_the_same_way(self):
        code = ("import sys; sys.path.insert(0, %r);"
                "from harbor_voice import verbs;"
                "print(verbs.normalise(\"  That's  ALL. \"))" % str(ROOT / "voice"))
        out = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True)
        if out.returncode:
            self.skipTest("the voice package would not import")
        self.assertEqual(out.stdout.strip(), "that's all")


class OneFlushPath(unittest.TestCase):
    """Rule 7: slice 2 left exactly one way to end a turn, and this card keeps it."""

    def test_a_quiet_endpoint_is_answered_with_cut_and_never_with_end(self):
        text = script()
        block = re.search(r'if \(msg\.reason === "quiet"\) \{(.*?)\n      \}', text, re.S)
        self.assertIsNotNone(block, "the quiet endpoint is not where this test can read it")
        said = block.group(1)
        self.assertIn('say({ type: "cut" });', said)
        self.assertNotIn('type: "end"', said,
                         "nothing was said, so there is nothing to dispatch")

    def test_end_is_still_sent_from_exactly_one_place(self):
        text = script()
        self.assertEqual(len(re.findall(r'say\(\{ type: "end"', text)), 1,
                         "one flush path, which is what the held partial needs")


class TheControl(unittest.TestCase):
    """The way in and the way out, and what a tap means."""


    def test_a_tap_pauses_in_a_conversation_and_cuts_in_while_speaking(self):
        body = re.search(r"function onOrbDown\(ev\)\s*\{(.*?)\n  \}", script(), re.S)
        self.assertIsNotNone(body)
        said = body.group(1)
        self.assertIn("resumeVoice();", said)
        self.assertIn('pauseVoice("tap");', said)
        self.assertIn('state.bus.state === "speaking"', said,
                      "barge-in does not change: a tap during speech still cuts in")

    def test_no_detector_means_no_conversation(self):
        body = re.search(r"function openConversation\(why, ev\)\s*\{(.*?)\n  \}",
                         script(), re.S)
        self.assertIn("if (!detectorReady())", body.group(1),
                      "a conversation without a detector is a microphone nothing closes")

    def test_the_launch_url_opens_a_conversation_and_once_stays_one_turn(self):
        text = script()
        body = re.search(r"function maybeAutoListen\(\)\s*\{(.*?)\n  \}", text, re.S)
        said = body.group(1)
        self.assertIn('listen === "once"', said)
        self.assertIn('openConversation("launch")', said)

    def test_the_shortcuts_say_what_they_now_do(self):
        manifest = json.loads((APP / "manifest.webmanifest").read_text(encoding="utf-8"))
        urls = {shortcut["name"]: shortcut["url"] for shortcut in manifest["shortcuts"]}
        self.assertIn("?listen=once", urls["Capture"],
                      "one dictated idea is one utterance")
        self.assertIn("?listen=1", urls["Start a conversation"])


if __name__ == "__main__":
    unittest.main()
