"""`keel doctor`: the report, the exit code, and that it never creates what it checks."""

import io
import json
import subprocess
from contextlib import redirect_stdout
from pathlib import Path
from unittest import mock

from keel import browser, cli, doctor, harness
from keel.board import Board
from tests.helpers import CliCase


def fake_version(argv, **kwargs):
    return subprocess.CompletedProcess(["claude", *argv], 0, stdout="9.9.9 (Claude Code)\n", stderr="")


# `keel.browser` reads `~/.keel-browser`, which under the fence is inside the throwaway HOME
# and so is always absent. Tests that want it present point KEEL_BROWSER_HOME at a tree of
# their own; nothing here ever launches a browser.
LINGER_NA = {"applicable": False}
VOICE_UP = {"ok": True, "upSeconds": 12.5, "stt": {"backend": "parakeet-mlx"}, "tts": {"backend": "google"}}
# What `GET /api/state` carries about the serve process's own descriptors: a healthy count,
# and one close enough to the soft limit to be worth saying (`serve.descriptors`, c-276).
DECK_ROOMY = {"config": {"descriptors": {"open": 40, "soft": 256}}}
DECK_TIGHT = {"config": {"descriptors": {"open": 210, "soft": 256}}}
# `talker.health` reads this machine's service manager and state files; stood in for, so
# the report does not depend on whether the fence's throwaway HOME has a unit in it.
TALKER_NA = {"state": "not-installed", "ok": True, "reason": "no talker service on this machine"}


class DoctorTest(CliCase):
    def setUp(self):
        super().setUp()
        self.toml = Path(self.dir / "keel.toml")
        self.write_config(config_dir=self.dir / "cfg", repo=self.dir / "repo")

    def write_config(self, config_dir: Path, repo: Path) -> None:
        self.toml.write_text(
            "[keel]\n"
            f'state_dir = "{self.dir / "state"}"\n'
            # Its own empty tree: left to the default this is the checkout's real segments/,
            # and the suite went red whenever this machine's own fetch stamps were stale.
            f'segments_dir = "{self.dir / "segments"}"\n'
            "houses_max = 2\n"
            "[spaces.personal]\n"
            f'config_dir = "{config_dir}"\n'
            'contract = "etc/space-personal.md"\n'
            "[spaces.personal.repos]\n"
            f'keel = "{repo}"\n'
        )

    def healthy(self) -> None:
        (self.dir / "cfg").mkdir()
        (self.dir / "repo").mkdir()
        board = Board(self.dir / "state" / "board.db")
        board.create("personal", "one")
        second = board.create("personal", "two")
        board.stage(second, "assigned", "human")
        board.close()

    def doctor(self, *argv, claude="/bin/claude", run=fake_version, voice=VOICE_UP,
               linger=LINGER_NA, deck=None, talker=TALKER_NA,
               login_answer=("ok\n", 0)):
        """`deck` is the state document the deck would answer with, None for a silent one.

        It is always stood in for: without this the check would reach the real deck on this
        machine's own `serve_port`, and the suite would be reading a live process. So is the
        login probe (`login_answer`, what `claude -p` prints and its exit code), which would
        otherwise be a real model call under the space's config dir.
        """
        def deck_state(*args, **kwargs):
            if deck is None:
                raise OSError("connection refused")
            return deck

        def probe(argv, **kwargs):
            self.probed = getattr(self, "probed", []) + [kwargs["env"].get("CLAUDE_CONFIG_DIR")]
            return subprocess.CompletedProcess(argv, login_answer[1], login_answer[0], "")

        out = io.StringIO()
        with mock.patch.object(harness.shutil, "which", return_value=claude), \
                mock.patch.object(harness, "run", side_effect=run), \
                mock.patch.object(harness, "run_alone", side_effect=probe), \
                mock.patch.object(doctor.service, "linger_report", return_value=linger), \
                mock.patch.object(doctor.deckdigest, "fetch_state", side_effect=deck_state), \
                mock.patch.object(doctor.talker, "health", return_value=talker), \
                mock.patch.object(doctor.voice, "health", return_value=voice), redirect_stdout(out):
            code = cli.keel_main(["doctor", *argv])
        return code, out.getvalue()

    def test_the_decks_descriptor_count_is_read_off_the_deck_and_flagged_when_high(self):
        """c-276: the serve process leaked descriptors for hours with nothing saying so.
        The doctor runs in another process, so the deck counts itself and this reads it."""
        self.healthy()
        code, out = self.doctor()
        self.assertEqual(code, 0, out)
        self.assertIn("deck          127.0.0.1:8790  not answering", out)
        code, out = self.doctor(deck=DECK_ROOMY)
        self.assertEqual(code, 0, out)
        self.assertIn("deck          127.0.0.1:8790  40 of 256 descriptors", out)
        code, out = self.doctor(deck=DECK_TIGHT)
        self.assertEqual(code, 1)
        self.assertIn("210 of 256 descriptors  HIGH", out)
        self.assertIn("missing: deck: 210 open descriptors of the 256 it may hold", out)

    def test_healthy_setup_prints_config_claude_and_counts(self):
        # c-633: a config that does not say leaves the drain unpaused, as the example ships
        self.healthy()
        code, out = self.doctor()
        self.assertEqual(code, 0, out)
        for text in ("houses_max    2", "drain_paused  False", "space personal",
                     "/bin/claude  (9.9.9 (Claude Code))", "inbox=1  assigned=1",
                     "total=2", str(self.dir / "state" / "board.db"),
                     "voice         127.0.0.1:4390  up 12.5s  stt parakeet-mlx  tts google"):
            self.assertIn(text, out)
        self.assertEqual(out.strip().splitlines()[-1], "ok")

    def test_the_login_is_probed_and_said_with_the_time(self):
        """2026-09-24: the doctor said "logged in" while the personal login could not
        refresh, because it only looked for a file. It asks the login itself now."""
        self.healthy()
        code, out = self.doctor()
        self.assertEqual(code, 0, out)
        self.assertEqual(self.probed, [str(self.dir / "cfg")])
        line = next(l for l in out.splitlines() if l.startswith("login "))
        self.assertRegex(line, r"^login         personal: logged in \(probed \d\d:\d\d\)$")

    def test_an_expired_login_is_a_problem_with_the_command_that_fixes_it(self):
        self.healthy()
        (self.dir / "cfg" / ".claude.json").write_text('{"oauthAccount": {"emailAddress": "x"}}')
        code, out = self.doctor(login_answer=("Login expired \u00b7 Please run /login\n", 1))
        self.assertEqual(code, 1)
        fix = f"run CLAUDE_CONFIG_DIR={self.dir / 'cfg'} claude, then /login"
        self.assertRegex(out, r"login         personal: LOGIN EXPIRED \(probed \d\d:\d\d\): "
                         + fix.replace("/", "\\/"))
        self.assertIn(f"missing: space personal: the login expired, so no house can run ({fix})", out)

    def test_a_probe_that_cannot_say_is_reported_but_is_not_a_problem(self):
        self.healthy()
        code, out = self.doctor(login_answer=("You've hit your session limit\n", 1))
        self.assertEqual(code, 0, out)
        self.assertIn("personal: login unknown (probed", out)

    def test_the_doctor_probes_even_inside_the_ten_minutes(self):
        self.healthy()
        self.doctor()
        self.doctor()
        self.assertEqual(len(self.probed), 2, "he asked, so it asks")

    def test_a_silent_gateway_is_reported_down_and_counts_as_missing(self):
        self.healthy()
        self.toml.write_text(self.toml.read_text() + "[voice]\nport = 4391\n")
        code, out = self.doctor(voice=None)
        self.assertEqual(code, 1)
        self.assertIn("voice         127.0.0.1:4391  DOWN", out)
        self.assertIn("missing: voice: not answering on 127.0.0.1:4391", out)
        code, out = self.doctor("--json", voice=None)
        report = json.loads(out)
        self.assertEqual(report["voice"]["port"], 4391)
        self.assertFalse(report["voice"]["ok"])

    def test_a_silent_gateway_is_never_reported_as_a_missing_judges_key(self):
        """c-313: only the gateway knows whether the unit's LoadCredential= delivered the
        copy it reads, so with nothing answering doctor falls back to the SOURCE file and
        says that is what it did. A gateway that is down must not read as a lost key, and a
        key it cannot ask about must not read as a problem."""
        self.healthy()
        self.toml.write_text(self.toml.read_text() + "[voice]\nport = 4391\n")
        code, out = self.doctor("--json", voice=None)
        judges = json.loads(out)["voice"]["judges"]
        self.assertFalse(judges["known"])
        self.assertFalse(judges["asked"])
        self.assertIn("not answering", judges["why"])
        self.assertTrue(judges["where"].endswith("jev-key"))
        code, out = self.doctor(voice=None)
        self.assertIn("judges        key MISSING", out)
        self.assertNotIn("missing: judges:", out)

    def test_the_judges_line_reads_the_gateways_own_answer_when_it_is_up(self):
        self.healthy()
        self.toml.write_text(self.toml.read_text() + "[voice]\nport = 4391\n")
        health = {"upSeconds": 1.0, "stt": {"backend": "sherpa"}, "tts": {"backend": "google"},
                  "judges": {"keys": {"preturn.route": {"mode": "shadow", "from": "default"},
                                      "narrate": {"mode": "off", "from": "override"}},
                             "jev": {"key": "set", "ready": True, "why": "",
                                     "retention": "accept-default-retention",
                                     "calls": 4, "misses": {"timeout": 1}}}}
        code, out = self.doctor(voice=health)
        self.assertIn("judges        1 off, 1 shadow  key set", out)
        self.assertIn("retention accept-default-retention", out)
        self.assertIn("4 calls, 1 misses", out)
        self.assertNotIn("missing: judges:", out)

    def test_a_judge_that_cannot_reach_the_key_is_said_out_loud(self):
        """In shadow with no key every call is the rule's verdict and a counted miss, which
        costs the turn nothing and produces no evidence. The evidence is the whole point of
        shadow, so it is a problem line rather than a silence."""
        self.healthy()
        self.toml.write_text(self.toml.read_text() + "[voice]\nport = 4391\n")
        health = {"upSeconds": 1.0, "stt": {"backend": "sherpa"}, "tts": {"backend": "google"},
                  "judges": {"keys": {"narrate": {"mode": "shadow", "from": "default"}},
                             "jev": {"key": "missing", "ready": False,
                                     "why": "no key in the systemd credential 'jev-key'",
                                     "retention": "accept-default-retention"}}}
        code, out = self.doctor(voice=health)
        self.assertEqual(code, 1)
        self.assertIn("judges        1 shadow  key MISSING", out)
        self.assertIn("missing: judges: no key in the systemd credential", out)
        self.assertIn("the shadow log records nothing to read", out)

    def test_a_gateway_older_than_the_judges_says_so_rather_than_guessing(self):
        self.healthy()
        self.toml.write_text(self.toml.read_text() + "[voice]\nport = 4391\n")
        health = {"upSeconds": 1.0, "stt": {"backend": "sherpa"}, "tts": {"backend": "google"}}
        code, out = self.doctor(voice=health)
        self.assertEqual(code, 0, out)
        self.assertIn("judges        this gateway is older than the judges", out)

    def test_a_gateway_that_says_nothing_about_a_detector_is_not_a_problem(self):
        """An older gateway simply cannot answer the question, which is not a fault.

        `keel voice status` learned this the hard way when the lookup tier was deleted:
        it read `doc['router']['backend']` by subscript and a healthy gateway started
        raising. The softer version of the same error is reading an ABSENT `vad` block as
        "there is no detector", which would report a problem about a gateway that has
        none. VOICE_UP is exactly that gateway: it predates c-311.
        """
        self.healthy()
        code, out = self.doctor()
        self.assertEqual(code, 0, out)
        self.assertNotIn("end-of-utterance", out)
        self.assertNotIn("vad", out)
        report = json.loads(self.doctor("--json")[1])
        self.assertNotIn("vad", report["voice"])

    def test_the_configured_hangover_is_printed_beside_the_running_one(self):
        """H6 (lane H): `[voice] vad_hangover` is what the unit carries; a gateway still on
        another value says which command applies it."""
        self.healthy()
        doc = dict(VOICE_UP, vad={"backend": "silero", "ready": True, "why": "",
                                  "hangoverSeconds": 2.5})
        code, out = self.doctor(voice=doc)
        self.assertEqual(code, 0, out)
        self.assertIn("vad silero 2.5s (configured 2.0s, keel voice install --load)", out)
        report = json.loads(self.doctor("--json", voice=doc)[1])
        self.assertEqual(report["voice"]["hangover_configured"], 2.0)
        doc["vad"]["hangoverSeconds"] = 2.0
        code, out = self.doctor(voice=doc)
        self.assertIn("vad silero 2.0s (as configured)", out)

    def test_a_gateway_with_no_detector_is_named_as_a_problem(self):
        """Reported and not ready: hands-free is silently back to twenty seconds a turn.

        This is what a missing model or a missing wheel looks like from outside, and it
        is invisible any other way until a turn takes twenty seconds.
        """
        self.healthy()
        doc = dict(VOICE_UP, vad={"backend": "none", "ready": False,
                                  "why": "no model at /models/silero_vad.onnx",
                                  "hangoverSeconds": 2.5})
        code, out = self.doctor(voice=doc)
        self.assertEqual(code, 1)
        self.assertIn("vad none", out)
        self.assertIn("no end-of-utterance detector (no model at "
                      "/models/silero_vad.onnx)", out)
        self.assertIn("twenty second backstop", out)

    def test_a_working_detector_shows_its_hangover_and_is_no_problem(self):
        self.healthy()
        doc = dict(VOICE_UP, vad={"backend": "silero", "ready": True, "why": "",
                                  "hangoverSeconds": 2.5})
        code, out = self.doctor(voice=doc)
        self.assertEqual(code, 0, out)
        self.assertIn("vad silero 2.5s", out)
        self.assertNotIn("end-of-utterance", out)

    def test_a_corpus_still_recording_after_its_few_days_is_named(self):
        """It is his voice on disk, and nothing else will remind anyone it is there.

        Two or three days was what he agreed to at c-277's plan gate, so four is where
        the doctor starts saying so. A corpus that is only a day old is doing its job and
        gets no complaint.
        """
        self.healthy()
        ok = dict(VOICE_UP, vad={"backend": "silero", "ready": True, "hangoverSeconds": 2.5},
                  record={"recording": True, "count": 40, "oldestDays": 1.0})
        self.assertEqual(self.doctor(voice=ok)[0], 0)
        late = dict(ok, record={"recording": True, "count": 400, "oldestDays": 9.0})
        code, out = self.doctor(voice=late)
        self.assertEqual(code, 1)
        self.assertIn("still recording the user's utterances after 9.0 days", out)
        self.assertIn("keel voice corpus --delete", out)
        self.assertIn("recording 400", out)

    def test_linger_is_not_applicable_on_launchd_and_a_problem_when_off_on_linux(self):
        """Without lingering, systemd stops every Keel unit at logout and starts none at
        boot: a box that reboots comes back with no deck, no drain and no talker."""
        self.healthy()
        code, out = self.doctor()
        self.assertEqual(code, 0, out)
        self.assertIn("linger        not applicable (launchd)", out)
        code, out = self.doctor(linger={"applicable": True, "user": "ubuntu", "on": True})
        self.assertEqual(code, 0, out)
        self.assertIn("linger        on for ubuntu", out)
        code, out = self.doctor(linger={"applicable": True, "user": "ubuntu", "on": False})
        self.assertEqual(code, 1)
        self.assertIn("linger        OFF for ubuntu", out)
        self.assertIn("missing: linger: off for ubuntu", out)

    def test_the_talker_has_a_line_and_each_fault_is_a_problem(self):
        """c-444: a talker stopped for two days, and one alive at an unanswered prompt, both
        sat under a clean doctor, because the doctor had no talker line at all."""
        self.healthy()
        code, out = self.doctor()
        self.assertEqual(code, 0, out)
        self.assertIn("talker        not-installed, no talker service on this machine", out)
        serving = {"state": "serving", "ok": True, "reason": "session session_01x"}
        code, out = self.doctor(talker=serving)
        self.assertEqual(code, 0, out)
        self.assertIn("talker        serving, session session_01x", out)
        for state, reason in (("stopped", "installed here and not running"),
                              ("no-session", "running for 300s with no session URL"),
                              ("fault", "unanswered prompt, nothing will answer it: Enable Remote Control? (y/n)")):
            code, out = self.doctor(talker={"state": state, "ok": False, "reason": reason})
            self.assertEqual(code, 1, state)
            self.assertIn(f"missing: talker: {state}, {reason}", out)

    def test_archived_cards_are_not_counted_and_a_tracking_card_is_not_building(self):
        """The doctor counted the stored stage of every card: 184 archived inbox cards read
        as a live inbox, and a parent whose stored stage was building read as a house."""
        self.healthy()
        board = Board(self.dir / "state" / "board.db")
        try:
            gone = board.create("personal", "history")
            board.set_fields(gone, {"options": {"archived": True}}, "human")
            parent = board.create("personal", "parent")
            board.create("personal", "slice", parent=parent)
            # The stored stage a split parent can be left holding (`kb split` at building).
            board.conn.execute("UPDATE cards SET stage = 'building' WHERE id = ?", (parent,))
        finally:
            board.close()
        code, out = self.doctor("--json")
        counts = json.loads(out)["board"]
        self.assertEqual(counts["counts"]["inbox"], 2, counts)       # "one" and "slice"
        self.assertEqual(counts["counts"]["building"], 0, counts)
        self.assertEqual((counts["archived"], counts["tracking"], counts["total"]), (1, 1, 5), counts)
        code, out = self.doctor()
        self.assertIn("building=0", out)
        self.assertIn("total=5  (tracking 1, archived 1 not counted)", out)

    def test_json_report(self):
        self.healthy()
        code, out = self.doctor("--json")
        report = json.loads(out)
        self.assertEqual((code, report["missing"]), (0, []))
        self.assertEqual(report["board"]["counts"]["assigned"], 1)
        self.assertEqual(report["claude"]["version"], "9.9.9 (Claude Code)")
        self.assertEqual(report["spaces"]["personal"]["config_dir"]["path"], str(self.dir / "cfg"))

    def test_missing_pieces_exit_1_and_are_named_without_being_created(self):
        code, out = self.doctor("--json", claude=None)
        report = json.loads(out)
        self.assertEqual(code, 1)
        missing = "\n".join(report["missing"])
        for text in ("claude is not on PATH", "state_dir missing", "config_dir missing",
                     "repo keel missing", "board: missing"):
            self.assertIn(text, missing)
        self.assertFalse((self.dir / "state").exists())

    def test_every_space_is_served_so_its_missing_repos_and_config_dir_are_problems(self):
        """c-622: one machine serves every space, so a space's missing repo and config dir
        are problems here, and a retired `host` key on the space is ignored, not a crash."""
        self.healthy()
        self.toml.write_text(self.toml.read_text() + (
            "[spaces.work]\n"
            'host = "mac"\n'
            f'config_dir = "{self.dir / "no-work-cfg"}"\n'
            'contract = "etc/space-work.md"\n'
            "[spaces.work.repos]\n"
            f'api = "{self.dir / "no-such-repo"}"\n'))
        code, out = self.doctor()
        self.assertEqual(code, 1)
        self.assertIn("space work: repo api missing", out)
        self.assertIn("space work: config_dir missing", out)

    def test_a_config_that_made_bosun_its_own_user_is_flagged(self):
        """c-622 r1.F7, c-648: the keys that made Bosun its own Unix user are ignored, and
        the doctor names each as a config warning."""
        self.healthy()
        self.assertNotIn("its own Unix user", self.doctor()[1])
        self.toml.write_text(self.toml.read_text() + (
            '[console]\nconfig_dir = "/home/bosun/.claude"\ncheckout = "/home/bosun/keel"\n'))
        code, out = self.doctor()
        self.assertEqual(code, 1)
        for key in ("config_dir", "checkout"):
            self.assertIn(f"config: [console] {key}: Bosun as its own Unix user is retired", out)

    def test_a_bosun_config_dir_another_user_owns_is_a_problem_with_builder_mode_off(self):
        """c-648: that owner refuses every Start of Bosun, so the doctor says it wherever the
        config has a Bosun, whatever builder mode is; and never where it has none."""
        import pwd
        from keel import console
        self.healthy()
        other = pwd.struct_passwd(("bosun", "x", 1002, 1002, "", "/home/bosun", "/bin/bash"))
        with mock.patch.object(console, "owner_of", return_value=other):
            self.assertNotIn("belongs to the Unix user", self.doctor()[1], "no Bosun on this config")
            self.toml.write_text(self.toml.read_text() + '[console]\nhost = "here"\n')
            code, out = self.doctor()
        self.assertEqual(code, 1)
        self.assertIn("bosun: Bosun's config dir", out)
        self.assertIn("belongs to the Unix user bosun", out)
        self.assertNotIn("belongs to the Unix user", self.doctor()[1])

    def test_the_builder_line_is_not_ready_while_the_owner_refuses_every_start(self):
        """c-648 review: with builder mode on, the builder line said ready beside the bosun
        line. It points at that line instead, and the sentence is printed once."""
        import pwd
        from keel import console
        self.healthy()
        self.toml.write_text(self.toml.read_text().replace("[keel]\n", "[keel]\nbosun_builder = true\n")
                             + '[console]\nhost = "here"\n')
        other = pwd.struct_passwd(("bosun", "x", 1002, 1002, "", "/home/bosun", "/bin/bash"))
        with mock.patch.object(console, "owner_of", return_value=other):
            code, out = self.doctor()
        self.assertEqual(code, 1)
        self.assertEqual(out.count("belongs to the Unix user bosun"), 1, out)
        built = [line for line in out.splitlines() if line.startswith("builder ")]
        self.assertEqual(len(built), 1, out)
        self.assertIn("the bosun line says why", built[0])
        self.assertNotIn("ready", built[0])

    def test_failing_version_and_unreadable_config(self):
        self.healthy()
        broken = subprocess.CompletedProcess([], 1, stdout="", stderr="boom")
        code, out = self.doctor("--json", run=lambda argv, **kwargs: broken)
        self.assertEqual(code, 1)
        self.assertIn("boom", "\n".join(json.loads(out)["missing"]))
        self.toml.write_text("not = [toml")
        code, out = self.doctor()
        self.assertEqual(code, 1)
        self.assertIn("missing: config", out)

    def test_the_browser_is_reported_where_a_card_could_drive_one(self):
        """A machine with `browsers_max` that serves a space starts a house for a card
        carrying `options.browser`, and that house needs `bin/keel-browser`. With no browser
        slot the line reads not applicable and `keel doctor` does not go red over an install
        it has no use for.
        """
        self.healthy()
        code, out = self.doctor()
        self.assertEqual(code, 0, out)
        self.assertIn("browser       not applicable (no browsers_max for this host)", out)
        self.toml.write_text(self.toml.read_text().replace("houses_max = 2\n",
                                                           "houses_max = 2\nbrowsers_max = 1\n"))
        code, out = self.doctor()
        self.assertEqual(code, 1)
        self.assertIn("browser       MISSING at ", out)
        self.assertIn("missing: browser: playwright-core is not installed", out)
        self.assertIn("bin/keel-browser install", out)
        (self.dir / "pw" / "node_modules" / "playwright-core").mkdir(parents=True)
        (self.dir / "pw" / "browsers" / "chromium-1195").mkdir(parents=True)
        with mock.patch.dict("os.environ", {browser.HOME_VAR: str(self.dir / "pw")}):
            code, out = self.doctor()
        self.assertEqual(code, 0, out)
        self.assertIn(f"browser       {self.dir / 'pw'}  playwright-core "
                      f"{browser.PLAYWRIGHT_VERSION}, 1 chromium build(s)", out)
