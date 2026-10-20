"""The voice conversation retires when Harbor's memory moves (c-538, r-14).

c-523 deployed around 17:25 on 2026-09-26 and taught Harbor to connect to Bosun; the voice
conversation had started at 14:02 and kept its morning memory, so at 17:45 Harbor said
"connecting only works for cards". The record now carries the memory stamp it started on,
and the next Harbor turn opens a new conversation when main's has moved."""

import io
import json
import sys
import threading
import tempfile
import time
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "voice"))
from harbor_voice import config as vconfig                              # noqa: E402
from harbor_voice import codewatch, harbormsg, server                  # noqa: E402


class MemoryRotationTest(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.file = Path(tmp.name) / "voice-session.json"
        for patch in (mock.patch.object(vconfig, "VOICE_SESSION_FILE", self.file),
                      mock.patch.object(vconfig, "VOICE_SESSION_LEGACY", Path(tmp.name) / "old"),
                      mock.patch.object(harbormsg, "last_said", return_value=["connect me to bosun"]),
                      mock.patch.object(harbormsg, "log")):
            patch.start()
            self.addCleanup(patch.stop)

    def started(self, **rec):
        self.file.write_text(json.dumps(dict({"uuid": "u-morning", "turns": 3,
                                              "started_at": 1.0e12}, **rec)))

    def opened(self, memory, spoken=True):
        with mock.patch.object(harbormsg, "memory_stamp", return_value=memory):
            return harbormsg.open_session(for_memory=spoken)

    def test_a_memory_change_retires_the_conversation_at_the_next_turn(self):
        self.started(memory="stamp-morning")
        session, existed, handover = self.opened("stamp-evening")
        self.assertNotEqual(session, "u-morning")
        self.assertFalse(existed)
        self.assertIn("NEW conversation", handover)
        self.assertIn("connect me to bosun", handover)
        self.assertEqual(harbormsg.read_session()["memory"], "stamp-evening")
        self.assertIn("Harbor's memory changed", harbormsg.log.call_args[0][0])

    def test_a_typed_ask_or_a_refine_never_retires_it_for_memory(self):
        """r1.F1: a typed ask from the deck runs in its own process and may arrive while
        voice holds a house; only a spoken turn, which the dispatcher sends to Harbor only
        when nothing is pinned, retires the conversation for memory."""
        self.started(memory="stamp-morning")
        self.assertEqual(self.opened("stamp-evening", spoken=False), ("u-morning", True, ""))
        self.assertNotEqual(self.opened("stamp-evening")[0], "u-morning")

    def test_the_spoken_turn_is_the_one_that_asks(self):
        source = (ROOT / "voice" / "harbor_voice" / "harbormsg.py").read_text()
        self.assertEqual(source.count("open_session(for_memory=True)"), 1)
        self.assertIn("open_session(for_memory=True)", source[source.index("def send("):
                                                            source.index("def run_turn_now(")])

    def test_the_same_memory_keeps_it(self):
        self.started(memory="stamp-morning")
        self.assertEqual(self.opened("stamp-morning"), ("u-morning", True, ""))

    def test_a_record_from_before_the_stamp_takes_it_without_rotating(self):
        self.started()
        self.assertEqual(self.opened("stamp-now"), ("u-morning", True, ""))
        self.assertEqual(harbormsg.read_session()["memory"], "stamp-now")
        self.assertEqual(self.opened("stamp-later")[0] != "u-morning", True)

    def test_a_stamp_git_cannot_give_is_not_a_change(self):
        self.started(memory="stamp-morning")
        self.assertEqual(self.opened(None), ("u-morning", True, ""))

    def test_a_counted_turn_keeps_the_stamp(self):
        self.started(memory="stamp-morning")
        harbormsg.count_turn()
        self.assertEqual(harbormsg.read_session(), {"uuid": "u-morning", "turns": 4,
                                                    "started_at": 1.0e12, "memory": "stamp-morning"})

    def test_the_stamp_is_read_from_main_in_the_voice_home(self):
        with mock.patch("keel.refresh.stamp", return_value="s") as read, \
                mock.patch.object(vconfig, "KEEL_TOML", vconfig.KEEL_HOME / "keel.toml"):
            self.assertEqual(harbormsg.memory_stamp(), "s")
        self.assertEqual(read.call_args[0], (vconfig.KEEL_HOME, ("talker/memory",
                                                                 "templates/memory/talker/CLAUDE.md")))

    def test_an_installs_gateway_reads_the_installs_memory(self):
        """c-722: the gateway of an install (its KEEL_CONFIG names `<install>/config.toml`)
        stamps the install's memory, as the phone talker does."""
        with mock.patch("keel.refresh.memory_stamp", return_value="s") as read, \
                mock.patch.object(vconfig, "KEEL_TOML", Path("/i/config.toml")):
            self.assertEqual(harbormsg.memory_stamp(), "s")
        self.assertEqual(read.call_args[0], (vconfig.KEEL_HOME, Path("/i")))


class CodeWatchTest(unittest.TestCase):
    """r-14: a deploy that changed voice/ left dev.keel.voice on its old code for days. The
    gateway notes its code's stamp at start and restarts on a new one, only once quiet."""

    def watch(self, stamps, busy=""):
        reads = iter(stamps)
        self.stops, self.lines = [], []
        self.busy = busy
        return codewatch.CodeWatch(Path("."), lambda: self.busy, lambda: self.stops.append(1),
                                   self.lines.append, read=lambda: next(reads))

    def test_unmoved_code_does_nothing(self):
        watch = self.watch(["a", "a"])
        self.assertEqual(watch.check(), "")
        self.assertEqual(self.stops, [])

    def test_moved_code_waits_while_busy_and_says_why_once(self):
        watch = self.watch(["a", "b", "b", "b"], busy="voice holds c-277")
        self.assertEqual([watch.check(), watch.check()], ["waiting", "waiting"])
        self.assertEqual(self.stops, [])
        self.assertEqual(len(self.lines), 1)
        self.assertIn("voice holds c-277", self.lines[0])
        self.busy = ""
        self.assertEqual(watch.check(), "restart")
        self.assertEqual(self.stops, [1])
        self.assertTrue(watch.restarting)

    def test_it_stops_the_server_once(self):
        watch = self.watch(["a", "b", "b"])
        self.assertEqual([watch.check(), watch.check()], ["restart", "restart"])
        self.assertEqual(self.stops, [1])

    def test_an_unknown_stamp_never_restarts(self):
        self.assertEqual(self.watch([None, "b"]).check(), "")
        self.assertEqual(self.watch(["a", None]).check(), "")

    def test_an_unknown_start_takes_the_first_readable_stamp_then_watches(self):
        """r1.F2: git away at start must not leave the watch off for days."""
        watch = self.watch([None, None, "a", "a", "b"])
        self.assertEqual([watch.check(), watch.check(), watch.check(), watch.check()],
                         ["", "", "", "restart"])
        self.assertEqual(self.stops, [1])

    def test_the_loop_runs_the_check_and_ends_on_a_restart(self):
        watch = self.watch(["a", "b"])
        watch.interval = 0.01
        watch.start()
        for _ in range(200):
            if self.stops:
                break
            time.sleep(0.01)
        self.assertEqual(self.stops, [1])


class ServeTest(unittest.TestCase):
    """r1.F7: `serve` itself, with the watch it starts, returns once its code moved while
    quiet, which is what hands the process back to its service to start again."""

    def test_serve_returns_after_its_code_moved_while_quiet(self):
        stamps = iter(["a"] + ["b"] * 50)
        gateway = mock.Mock(busy=mock.Mock(return_value=""),
                            health=mock.Mock(return_value={
                                "filler": {"backend": "x", "model": "y"},
                                "stt": {"backend": "x", "ready": True}, "tts": {"backend": "x"}}))
        gateway.start.return_value = gateway
        with mock.patch.object(server, "Gateway", return_value=gateway), \
                mock.patch.object(server, "refuse_live_board", return_value=""), \
                mock.patch.object(vconfig, "HARBOR_KEPT_ALIVE", False), \
                mock.patch.object(vconfig, "PORT", 0), \
                mock.patch.object(codewatch, "CHECK_SECONDS", 0.05), \
                mock.patch.object(codewatch.refresh, "stamp", side_effect=lambda *a: next(stamps)), \
                mock.patch.object(harbormsg, "log"), \
                mock.patch("sys.stdout", new_callable=io.StringIO) as out:
            done = []
            runner = threading.Thread(target=lambda: done.append(server.serve(0)), daemon=True)
            runner.start()
            runner.join(10)
        self.assertEqual(done, [0], "serve returned")
        self.assertIn("stopped for its new code", out.getvalue())
        gateway.snapshot.stop.assert_called_once()


class BusyTest(unittest.TestCase):
    """What would be cut by a restart now: each keeps the gateway from restarting."""

    def gateway(self, **over):
        talk = server.Conversation()
        fake = SimpleNamespace(
            IN_FLIGHT=server.Gateway.IN_FLIGHT, talk=talk,
            dispatcher=SimpleNamespace(pinned=lambda: over.get("pinned", ""),
                                       turn=over.get("turn")),
            refiner=SimpleNamespace(waiting=over.get("waiting", 0)))
        if over.get("open"):
            talk.open = True
        if over.get("held"):
            talk.hold("and then", lambda: None)
            self.addCleanup(talk.take)
        return fake

    def busy(self, **over):
        with mock.patch.object(harbormsg, "in_flight", return_value=over.pop("flight", 0)):
            return server.Gateway.busy(self.gateway(**over))

    def test_quiet_is_empty(self):
        self.assertEqual(self.busy(turn=SimpleNamespace(phase="done")), "")
        self.assertEqual(self.busy(), "")

    def test_each_busy_state_is_named(self):
        self.assertIn("c-277", self.busy(pinned="c-277"))
        for phase in ("routing", "waiting", "speaking", "held"):
            self.assertIn(phase, self.busy(turn=SimpleNamespace(phase=phase)))
        self.assertIn("Harbor", self.busy(flight=1))
        self.assertIn("half a sentence", self.busy(held=True))
        self.assertIn("conversation is open", self.busy(open=True))
        self.assertIn("refine", self.busy(waiting=1))

    def test_the_refiner_s_queue_is_read_as_the_gateway_has_it(self):
        """A property on the real Refiner: the first scratch gateway raised calling it."""
        refiner = server.refinemod.Refiner(topics=lambda space: [])
        fake = self.gateway()
        fake.refiner = refiner
        with mock.patch.object(harbormsg, "in_flight", return_value=0):
            self.assertEqual(server.Gateway.busy(fake), "")
            refiner.queue.append({"card": "c-1"})
            self.assertIn("refine", server.Gateway.busy(fake))

    def test_a_turn_holding_the_lock_is_busy(self):
        with harbormsg._TURN_LOCK:
            self.assertIn("Harbor", self.busy())


if __name__ == "__main__":
    unittest.main()
