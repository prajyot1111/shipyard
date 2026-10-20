"""The listen watchdog, the honest orb label and the page's trace (V13, the page half).

On 2026-09-21, after Harbor connected him to a house, the orb read "listening" for 62
seconds in conversation mode while not one audio frame reached the gateway; his push-to-talk
press then worked first time. Nothing the page could see had failed: `openMic` resolved and
`state.holding` was true, so the only untrue thing was the word on the orb.

Two kinds of test here, and the split is deliberate.

**The node run is the real one.** `tests/fixtures/voice-listen.js` loads `app.js` itself with
a stand-in DOM, a stand-in socket and a clock the test owns, and drives the whole path: three
seconds of silence re-press once, a second three seconds says the microphone stalled, a tap
reopens it from the gesture, `listen-now` presses only inside a conversation, the trace comes
out in order, and playback that never reports its end is capped. It runs the real file, so it
fails when the behaviour changes rather than when the wording does. It is skipped where there
is no node, which is the same bargain `tests/test_boards.py` makes for the deck's board.

**The greps are the rules that have no behaviour to run.** The label the orb shows, the
state the CSS paints, and the shape of the message the gateway logs, in the style of
`tests/test_voice_conversation.py`.
"""

import json
import re
import shutil
import subprocess
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
APP = ROOT / "segments" / "voice" / "app"
HARNESS = ROOT / "tests" / "fixtures" / "voice-listen.js"
COMMENT_BLOCK = re.compile(r"/\*.*?\*/", re.S)
COMMENT_LINE = re.compile(r"^\s*//.*$", re.M)


from tests.voicepage import css, script, scripts  # noqa: E402  (VP-6: all of the page)


class TheWatchdogRuns(unittest.TestCase):
    """The one test that proves behaviour rather than wording."""

    @unittest.skipUnless(shutil.which("node"), "node is not on this machine")
    def test_the_page_repairs_a_silent_listen_and_then_says_so(self):
        result = subprocess.run(["node", str(HARNESS)] + [str(p) for p in scripts()],
                                capture_output=True, text=True, timeout=120)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(result.stdout), {"ok": True}, result.stdout)


class TheOrbTellsTheTruth(unittest.TestCase):
    """"Listening" is a claim about audio, so it waits for audio."""

    def test_the_two_new_states_are_decided_in_the_one_place(self):
        body = re.search(r"function displayState\(\)\s*\{(.*?)\n  \}", script(), re.S)
        self.assertIsNotNone(body, "displayState() is not where this test can read it")
        said = body.group(1)
        self.assertIn('return "stalled"', said,
                      "a microphone the page has given up on beats every other word "
                      "except a socket that is gone")
        self.assertIn("state.flowing", said,
                      "listening is shown only while frames are flowing")
        self.assertLess(said.index('return "stalled"'), said.index('return "paused"'),
                        "stalled is a pause with a fault behind it, and it says which")


    def test_the_stalled_orb_is_reopened_from_the_gesture_itself(self):
        body = re.search(r"function onOrbDown\(ev\)\s*\{(.*?)\n  \}", script(), re.S)
        self.assertIsNotNone(body)
        said = body.group(1)
        self.assertIn("if (state.stalled)", said)
        self.assertLess(said.index("if (state.stalled)"), said.index("if (state.paused)"),
                        "a stalled microphone is reopened before the pause branch, or the "
                        "tap resumes through a timer and spends the activation iOS wants")
        self.assertIn('press(ev, "tap-after-stall")', said,
                      "the press must run inside the gesture, not behind whenPlaybackEnds")


class TheWatchdogItself(unittest.TestCase):
    """The pipe is watched, not the speech."""

    def test_a_frame_of_silence_still_counts(self):
        text = script()
        handler = re.search(r"mic\.node\.port\.onmessage = function \(ev\) \{(.*?)\n      \};",
                            text, re.S)
        self.assertIsNotNone(handler, "the worklet handler is not where this can read it")
        said = handler.group(1)
        self.assertIn("onFrame();", said, "every frame counts, speech or not")
        self.assertLess(said.index("onFrame();"), said.index("ws.send"),
                        "what is watched is audio leaving the worklet")

    def test_the_watchdog_is_armed_on_an_automatic_press_only(self):
        body = re.search(r"function press\(ev, why\)\s*\{(.*?)\n  \}", script(), re.S)
        self.assertIsNotNone(body, "press() is not where this test can read it")
        self.assertIn("if (state.autoHeld) watchFrames();", body.group(1),
                      "a finger on the orb is its own watchdog; nobody is watching a "
                      "listen the page armed by itself")

    def test_the_repair_is_spent_once_and_tears_the_stream_down(self):
        body = re.search(r"function rePress\(\)\s*\{(.*?)\n  \}", script(), re.S)
        self.assertIsNotNone(body)
        said = body.group(1)
        self.assertIn("state.repressed = true;", said)
        self.assertIn("closeMic();", said,
                      "openMic returns early while mic.node exists, so a second press "
                      "over a dead stream would rebuild nothing")
        self.assertLess(said.index("closeMic();"), said.index("press(null,"))
        self.assertIn('say({ type: "cut" });', said)
        self.assertNotIn('type: "end"', said,
                         "nothing was heard, so there is nothing to dispatch")

    def test_the_second_failure_stops_the_page_claiming_to_listen(self):
        body = re.search(r"function frameCheck\(\)\s*\{(.*?)\n  \}", script(), re.S)
        self.assertIsNotNone(body)
        said = body.group(1)
        self.assertIn("if (!state.repressed) { rePress(); return; }", said)
        self.assertIn("micStalled(", said)

    def test_a_stall_really_closes_the_microphone(self):
        body = re.search(r"function micStalled\(why\)\s*\{(.*?)\n  \}", script(), re.S)
        self.assertIsNotNone(body)
        said = body.group(1)
        self.assertIn("state.stalled = true;", said)
        self.assertIn('pauseVoice("stalled")', said,
                      "one path closes the microphone, and it is the pause")
        self.assertNotIn("endConversation", said,
                         "one tap repairs this, so the conversation is left open")

    def test_the_watchdog_is_dropped_wherever_the_hold_is(self):
        text = script()
        for name in ("function release(ev, why)", "function pauseVoice(why)",
                     "function endConversation(why)"):
            body = re.search(re.escape(name) + r"\s*\{(.*?)\n  \}", text, re.S)
            self.assertIsNotNone(body, "%s is not where this test can read it" % name)
            self.assertIn("clearFrameWatch();", body.group(1),
                          "%s leaves a timer armed against the next listen" % name)


class ThePlaybackCeiling(unittest.TestCase):
    """Every player is asked, and none of them may hold the conversation open for ever."""

    def test_every_player_is_asked_on_the_one_loop(self):
        body = re.search(r"function playbackBusy\(\)\s*\{(.*?)\n  \}", script(), re.S)
        self.assertIsNotNone(body, "playbackBusy() is not where this test can read it")
        said = body.group(1)
        self.assertIn("out.at > out.ctx.currentTime", said,
                      "the TTS chunks and the tone are the same scheduled queue")
        self.assertIn("speech.out > 0", said,
                      "speechSynthesis.speaking is false in the gap before a queued "
                      "utterance starts, and speakHere can delay its speak by a bufferful")
        self.assertIn("window.speechSynthesis.speaking", said)

    def test_the_ceiling_is_measured_from_the_last_chunk_and_is_logged(self):
        text = script()
        self.assertIn("V.PLAYBACK_CEILING_MS = 20000;", text)
        body = re.search(r"function whenPlaybackEnds\(then\)\s*\{(.*?)\n  \}", text, re.S)
        self.assertIsNotNone(body)
        said = body.group(1)
        self.assertIn("now() - V.out.lastAt > V.PLAYBACK_CEILING_MS", said,
                      "the ceiling is twenty seconds since the last thing to play, not "
                      "twenty seconds of polling")
        self.assertIn('finish("ceiling")', said)
        self.assertIn('trace("playback-end", reason)', said,
                      "the gateway's log is what tells the two failures apart")


class TheTrace(unittest.TestCase):
    """A log line, a fixed shape, and nothing branches on it."""

    EVENTS = ("arm", "press", "frames", "playback-end", "quiet", "stalled",
              "release", "repress")

    def test_the_message_is_the_shape_the_gateway_logs(self):
        body = re.search(r"function trace\(event, reason\)\s*\{(.*?)\n  \}", script(), re.S)
        self.assertIsNotNone(body, "trace() is not where this test can read it")
        said = body.group(1)
        self.assertIn('type: "trace"', said)
        self.assertIn("event: event", said)
        self.assertIn("reason:", said)
        self.assertIn("listen:", said)
        self.assertIn("at: Math.round(now())", said,
                      "at is milliseconds since this page loaded, from one monotonic clock")

    def test_every_transition_in_the_protocol_is_traced(self):
        text = script()
        for event in self.EVENTS:
            self.assertIn('trace("%s"' % event, text,
                          "nothing sends the %s trace" % event)

    def test_the_frames_trace_is_sent_once_per_listen(self):
        body = re.search(r"function onFrame\(\)\s*\{(.*?)\n  \}", script(), re.S)
        self.assertIsNotNone(body)
        said = body.group(1)
        self.assertIn("if (state.flowing) return;", said,
                      "the point is that audio started, not how much of it there is")
        self.assertIn('trace("frames"', said)

    def test_nothing_waits_on_a_trace(self):
        text = script()
        self.assertNotIn('msg.type === "trace"', text,
                         "the trace goes one way: the gateway logs it and answers nothing")


class ListenNow(unittest.TestCase):
    """The gateway may ask for the microphone, inside a conversation and nowhere else."""

    def test_it_is_ignored_outside_a_conversation_and_over_a_pause(self):
        block = re.search(r"function onListenNow\(msg\)\s*\{(.*?)\n  \}", script(), re.S)
        self.assertIsNotNone(block, "listen-now is not where this test can read it")
        said = block.group(1)
        self.assertIn("if (!state.conversation || state.paused || state.stalled) return;",
                      said, "paused means CLOSED, and his tap is what reopens it")
        self.assertIn("if (state.holding) return;",
                      said, "a listen already in hand is not restarted, which would "
                            "silently reset the gateway's buffer")
        self.assertIn("msg.generation < state.generation", said,
                      "a turn he has already moved on from is dropped, exactly as its "
                      "audio would be")

    def test_it_goes_through_the_one_automatic_press(self):
        block = re.search(r"function onListenNow\(msg\)\s*\{(.*?)\n  \}", script(), re.S)
        said = block.group(1)
        self.assertIn("state.autoHeld = true;", said)
        self.assertIn('press(null, "listen-now");', said,
                      "one way the microphone opens by itself, not two")


class TheTestDoor(unittest.TestCase):
    """The hook the node run drives, and the fact that it is shut on his phone."""

    def test_the_door_is_shut_unless_it_is_asked_for(self):
        text = script()
        self.assertIn("V.SELFTEST =", text)
        self.assertIn("selftest=1", text)
        hook = re.search(r"if \(V\.SELFTEST\) \{(.*?)\n  \}", text, re.S)
        self.assertIsNotNone(hook, "the hook is not guarded by SELFTEST")
        self.assertEqual(text.count("window.__voiceTest"), 1,
                         "one door, and it is behind the flag")

    def test_the_door_adds_no_power_the_socket_does_not_have(self):
        hook = re.search(r"if \(V\.SELFTEST\) \{(.*?)\n  \}", script(), re.S).group(1)
        self.assertNotIn("fetch(", hook)
        self.assertNotIn("/api/", hook,
                         "this page cannot act, and a test door may not be the exception")


if __name__ == "__main__":
    unittest.main()
