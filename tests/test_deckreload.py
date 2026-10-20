"""A config change the deck reads in place (keel/deckreload.py, c-729).

Before c-729 every setup verb that wrote `config.toml` re-exec'd the deck, and the setup page
went blank through each restart. Now a change the running deck can read is read in place: the
answer says `reloaded`, nothing is exec'd, and the next state is built from the new config. A
change to what the process bound at start (its port, its state, voice) still restarts it, as
before. All on a real scratch install from `shipyard init`, served on a free port."""

import json
import os
import tempfile
import types
import unittest
import urllib.error
import urllib.request
from pathlib import Path
from unittest import mock

from keel import config as config_module
from keel import deckreload, readiness, serve
from tests.helpers import no_real_tools, serve_in_background
from tests.test_installer import init
from tests.test_readiness import fake_tailscale


class ReloadTest(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        patch = mock.patch.dict(os.environ)
        patch.start()
        self.addCleanup(patch.stop)
        no_real_tools(self)
        readiness.forget()
        self.addCleanup(readiness.forget)
        self.home = Path(tmp.name).resolve() / "install"
        self.assertEqual(init(self.home), 0)
        fake_tailscale(self.home.parent / "bin", "{}")
        cfg = config_module.load(self.home / "config.toml", ensure=False)
        cfg.lavish_port = 1
        for name in ("schedule_restart", "restart_process"):
            stub = mock.patch.object(serve, name)
            setattr(self, name, stub.start())
            self.addCleanup(stub.stop)
        self.server = serve.make_server(cfg, port=0)
        self.thread = serve_in_background(self.server)
        self.addCleanup(self.server.server_close)
        self.addCleanup(self.server.shutdown)
        self.base = f"http://127.0.0.1:{self.server.server_address[1]}"

    def act(self, body: dict) -> dict:
        with urllib.request.urlopen(self.base + "/", timeout=10) as response:
            response.read()
            cookie = (response.headers.get("Set-Cookie") or "").split(";", 1)[0]
        request = urllib.request.Request(self.base + "/api/action", data=json.dumps(body).encode(), method="POST")
        for name, value in {"Content-Type": "application/json", "Cookie": cookie, "Origin": self.base,
                            "Sec-Fetch-Site": "same-origin"}.items():
            request.add_header(name, value)
        with urllib.request.urlopen(request, timeout=30) as response:
            answer = json.loads(response.read())
        self.assertTrue(answer["ok"], answer)
        return answer["result"]

    def get(self, path: str) -> dict:
        with urllib.request.urlopen(self.base + path, timeout=30) as response:
            return json.loads(response.read())

    def plans(self) -> dict:
        state = self.get("/api/state?steps=1")
        return next(s for s in state["firstrun"]["steps"] if s["id"] == "defaults")["plans"]

    def test_a_setting_the_deck_can_read_is_read_in_place_with_no_restart(self):
        self.assertEqual(self.plans()["personal"], False)
        result = self.act({"verb": "setup.settings.save",
                           "changes": [{"table": "space", "space": "personal", "key": "autonomy", "value": "attended"}]})
        self.assertEqual((result.get("restarting"), result.get("reloaded")), (False, True), result)
        self.assertEqual(self.plans()["personal"], True, "the next state is the new config's")
        self.schedule_restart.assert_not_called()
        self.restart_process.assert_not_called()

    def test_a_change_to_what_the_process_bound_at_start_still_restarts_it(self):
        result = self.act({"verb": "setup.settings.save",
                           "changes": [{"table": "voice", "key": "mode_default", "value": "talk"}]})
        # the setup lock is held until the exec, which is stubbed here
        self.addCleanup(serve.SETUP_LOCK.release)
        self.assertEqual((result.get("restarting"), result.get("reloaded")), (True, False), result)
        saved = config_module.load(self.home / "config.toml", ensure=False)
        self.assertEqual(deckreload.bound_changes(self.server.deck.cfg, saved), ["voice_mode_default"])
        self.assertEqual(self.server.deck.cfg.voice_mode_default, "capture", "the old process keeps its config")
        self.schedule_restart.assert_called_once()

    def builder_mode(self, mode: str) -> dict:
        return self.act({"verb": "setup.settings.save", "changes": [
            {"table": "keel", "key": "bosun_builder", "value": True}, {"table": "builder", "key": "mode", "value": mode}]})

    def test_two_setup_verbs_in_a_row_both_go_through(self):
        """r1.F9: the setup lock is let go after a change read in place."""
        self.builder_mode("auto")
        result = self.builder_mode("bypass")
        self.assertEqual(result.get("reloaded"), True, result)
        self.assertEqual(self.server.deck.cfg.builder.get("mode"), "bypass")

    def test_a_config_that_does_not_load_is_not_swapped_in_and_the_deck_restarts(self):
        """r1.F9: no half swap; the old config stays until the re-exec reads the file."""
        old = self.server.deck.cfg
        def broken(*args, **kwargs):
            raise config_module.ConfigError("broken")
        reader = types.SimpleNamespace(load=broken, ConfigError=config_module.ConfigError)
        with mock.patch.object(deckreload, "config_module", reader):
            result = self.builder_mode("bypass")
        self.addCleanup(serve.SETUP_LOCK.release)
        self.assertEqual((result.get("restarting"), result.get("reloaded")), (True, False), result)
        self.assertIs(self.server.deck.cfg, old)
        self.schedule_restart.assert_called_once()

    def test_a_pack_turned_on_is_what_the_next_setup_and_state_read(self):
        """r1.F9: the deck's documents and kept readings are the new config's."""
        kept = self.server.deck.kept
        result = self.act({"verb": "setup.pack.on", "pack": "github", "space": "work"})
        self.assertEqual(result.get("reloaded"), True, result)
        self.assertIsNot(self.server.deck.kept, kept, "the old readings are let go")
        self.assertEqual(self.get("/api/setup")["spaces"]["work"]["pack"], "github")
        self.assertEqual(self.get("/api/state")["spaces"]["work"]["adapter"], "github")

    def test_a_bypass_that_cannot_be_recorded_still_saves_and_reloads(self):
        """r1.F5: the acceptance is best effort after the config is written; a Claude folder
        the deck cannot write leaves the save answered, said, and read in place."""
        claude = self.home / "claude"
        claude.chmod(0o500)
        self.addCleanup(claude.chmod, 0o700)
        result = self.builder_mode("bypass")
        self.assertEqual(result.get("reloaded"), True, result)
        self.assertIn("bypass", result.get("note") or "")
        self.assertEqual(self.server.deck.cfg.builder.get("mode"), "bypass")
        self.assertFalse((claude / "settings.json").exists())

    def test_a_verb_that_wrote_the_config_and_then_failed_still_leaves_the_deck_on_it(self):
        """r1.F5: the file holds the new mode, so the running deck does too, whatever the
        answer said."""
        request = {"verb": "setup.settings.save", "changes": [{"table": "builder", "key": "mode", "value": "bypass"}]}
        with mock.patch("keel.builder.record_bypass", side_effect=RuntimeError("after the write")):
            with self.assertRaises(urllib.error.HTTPError) as caught:
                self.act(request)
        caught.exception.close()
        self.assertEqual(caught.exception.code, 500)
        self.assertEqual(self.server.deck.cfg.builder.get("mode"), "bypass")
        self.assertEqual(self.builder_mode("auto").get("reloaded"), True, "and the setup lock was let go")

    def bosun_session(self):
        """Bosun's session up, as the harness lists it; the transcript a hello is written to."""
        from keel import bosunhello, console
        bosunhello.forget()
        self.addCleanup(bosunhello.forget)
        console.forget_view()
        self.addCleanup(console.forget_view)
        cfg = self.server.deck.cfg
        console.write_state(cfg, {"session_id": "s-1", "bg_id": "b-1"})
        row = {"id": "b-1", "sessionId": "s-1", "pid": 7, "status": "idle"}
        for name, value in (("keel.harness.agents", [row]), ("keel.harness.find", row)):
            stub = mock.patch(name, return_value=value)
            stub.start()
            self.addCleanup(stub.stop)
        return console.config_dir(cfg) / "projects" / "x" / "s-1.jsonl"

    @staticmethod
    def say_hello(path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps({"type": "user", "message": {"role": "user", "content": "hello"}}) + "\n")

    def test_a_voice_change_whose_verb_failed_after_the_write_still_reinstalls_the_gateway(self):
        """r2.F6: the restart that follows a failed verb's write reinstalls the voice gateway
        first when the file now differs in a voice field, as a voice change that succeeded
        does."""
        request = {"verb": "setup.settings.save", "changes": [
            {"table": "voice", "key": "mode_default", "value": "talk"},
            {"table": "space", "space": "personal", "key": "review_auto", "value": True}]}
        with mock.patch("keel.reviewsettings.clear", side_effect=RuntimeError("after the write")):
            with self.assertRaises(urllib.error.HTTPError) as caught:
                self.act(request)
        caught.exception.close()
        self.addCleanup(serve.SETUP_LOCK.release)
        self.assertEqual(caught.exception.code, 500)
        saved = config_module.load(self.home / "config.toml", ensure=False)
        self.assertEqual(saved.voice_mode_default, "talk", "the file holds the voice change")
        self.schedule_restart.assert_called_once_with(True)

    def test_a_hello_in_bosuns_session_reaches_a_page_that_asks(self):
        """c-729, Meet Bosun: a message in Bosun's session moves nothing on the board, so the
        state's revision did not move and a page holding the step got a 304 until some write.
        The page asks `/api/hello` while it waits, and the next state carries it."""
        transcript = self.bosun_session()

        def state(tag=None):
            request = urllib.request.Request(self.base + "/api/state?steps=1", headers={"If-None-Match": tag} if tag else {})
            try:
                with urllib.request.urlopen(request, timeout=30) as response:
                    doc = json.loads(response.read())
                    return response.headers["ETag"], next(s for s in doc["firstrun"]["steps"] if s["id"] == "builder")
            except urllib.error.HTTPError as error:
                error.close()
                return error.code, None
        tag, step = state()
        self.assertEqual((step["running"], step["hello"]), (True, False))
        self.say_hello(transcript)
        with mock.patch("keel.deckstate.clock_step", return_value=0):
            tag, step = state()
            self.assertEqual(state(tag), (304, None), "nothing on the board moved, so the page is told nothing")
            self.assertEqual(self.get("/api/hello"), {"hello": True})
            _, step = state(tag)
        self.assertEqual((step["hello"], step["done"]), (True, True))

    def test_the_hello_check_reads_only_and_moves_the_deck_once_when_the_answer_changes(self):
        """r1.F6, r1.F7: the watch asks every few seconds for as long as the step waits, so it
        takes no setup lock (a real setup change at the same moment goes through), and the
        deck's documents are dropped, and every page told, only when the hello arrives."""
        transcript = self.bosun_session()
        deck = self.server.deck
        self.assertTrue(serve.SETUP_LOCK.acquire(blocking=False))
        self.addCleanup(serve.SETUP_LOCK.release)
        writes = deck.writes
        self.assertEqual(self.get("/api/hello"), {"hello": False}, "answered while a setup change runs")
        self.assertEqual(self.get("/api/hello"), {"hello": False})
        self.assertEqual(deck.writes, writes, "no answer changed, so nothing moved")
        self.say_hello(transcript)
        self.assertEqual(self.get("/api/hello"), {"hello": True})
        self.assertEqual(deck.writes, writes + 1, "the hello moved the deck once")
        self.assertEqual(self.get("/api/hello"), {"hello": True})
        self.assertEqual(deck.writes, writes + 1, "and not again")

    def test_going_on_past_a_step_is_recorded_while_a_setup_change_runs(self):
        """r2.F4: Next and Keep this send `firstrun.seen` as the next step opens; an Add repo
        copy holds the setup lock for its whole clone, so seen takes no setup lock
        (`firstrun.change` serialises its write) and reads only its own step, never the
        whole first-run report."""
        from keel import firstrun
        self.assertTrue(serve.SETUP_LOCK.acquire(blocking=False))
        self.addCleanup(serve.SETUP_LOCK.release)
        with mock.patch.object(firstrun, "report", side_effect=AssertionError("the whole report was built")):
            result = self.act({"verb": "firstrun.seen", "step": "memory"})
        self.assertEqual(result["seen"], "memory")
        self.assertIn("memory", firstrun.stored(self.server.deck.cfg).get("seen", {}))
        with self.assertRaises(urllib.error.HTTPError) as caught:
            self.act({"verb": "firstrun.seen", "step": "repos"})
        caught.exception.close()
        self.assertEqual(caught.exception.code, 409, "a step with its own check is still refused")

    def test_the_setup_report_names_the_process_that_answered(self):
        """`boot`: how the page tells a deck that restarted from the one it asked before."""
        self.assertEqual(self.get("/api/setup")["boot"], serve.BOOT)
        self.assertEqual(len(serve.BOOT), 16)


if __name__ == "__main__":
    unittest.main()
