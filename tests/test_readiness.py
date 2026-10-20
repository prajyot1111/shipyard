"""Readiness (keel/readiness.py, c-629): per space and for the install, what is set up, why
not, and which first-run step fixes it, on a real scratch install."""

import dataclasses
import json
import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from keel import config as config_module
from keel import deckstate, login, onboarding, packs, packsetup, readiness
from keel.board import open_board
from tests.helpers import no_real_tools
from tests.test_installer import init

ROOT = Path(__file__).resolve().parent.parent
MISSING = {"name": "git", "ok": False, "said": "not found", "fix": "install git", "required": True}


def fake_tailscale(folder: Path, printed: str, code: int = 0) -> None:
    """A `tailscale` first on PATH that prints `printed` for `serve status --json` (c-632).
    The suite's fence refuses the real one; the caller patches `os.environ` first."""
    folder.mkdir(parents=True, exist_ok=True)
    script = folder / "tailscale"
    script.write_text(f"#!/bin/sh\ncat <<'EOF'\n{printed}\nEOF\nexit {code}\n")
    script.chmod(0o755)
    os.environ["PATH"] = f"{folder}{os.pathsep}{os.environ['PATH']}"


def served(port: int, host: str = "mac.tailnet.example") -> str:
    return json.dumps({"TCP": {"443": {"HTTPS": True}},
                       "Web": {f"{host}:443": {"Handlers": {"/": {"Proxy": f"http://127.0.0.1:{port}"}}}}})


class ReadinessTest(unittest.TestCase):
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
        self.cfg = self.load()
        fake_tailscale(self.home.parent / "bin", "{}")

    def load(self):
        return config_module.load(self.home / "config.toml", ensure=False)

    def with_work_on_sandbox(self):
        packsetup.pack_on(self.cfg, "sandbox", "work")
        return self.load()

    def test_a_fresh_install_has_no_repo_and_no_integration(self):
        rows = readiness.space_rows(self.cfg, self.cfg.spaces["personal"])
        self.assertEqual(rows["repos"], {"ready": False, "why": "no repo is cloned for personal yet",
                                         "step": "repos"})
        for name in readiness.CAPABILITIES:
            self.assertEqual(rows[name], {"ready": False, "step": "integrations", "declared": False,
                                          "why": "no connection is turned on for personal"})

    def test_a_repo_with_git_is_ready_and_the_installs_own_packs_repo_is_not_counted(self):
        repo = self.home.parent / "api"
        subprocess.run(["git", "init", "-q", str(repo)], check=True)
        space = self.cfg.spaces["personal"]
        space.repos["api"] = repo
        self.assertEqual(readiness.repos_row(self.cfg, space)["why"], "1 repo: api")
        del space.repos["api"]
        self.assertFalse(readiness.repos_row(self.cfg, space)["ready"])

    def test_the_installs_own_memory_repo_is_not_counted_either(self):
        """r1.F1: the memory repo is the install's own, like packs, never one of the user's."""
        subprocess.run(["git", "init", "-q", str(self.home / "memory")], check=True)
        space = self.cfg.spaces["personal"]
        space.repos["memory"] = self.home / "memory"
        self.assertFalse(readiness.repos_row(self.cfg, space)["ready"])
        self.assertTrue(onboarding.fresh(self.cfg))

    def test_a_space_on_the_sandbox_pack_has_its_three_capabilities(self):
        cfg = self.with_work_on_sandbox()
        rows = readiness.space_rows(cfg, cfg.spaces["work"])
        for name in ("tracker", "codehost", "reviews"):       # the sandbox has no CI (c-642)
            self.assertTrue(rows[name]["ready"], rows[name])
        self.assertEqual(rows["ci"]["why"], "the sandbox connection has no CI builds")
        self.assertEqual(rows["codehost"]["why"], "the sandbox connection provides its code host")

    def test_a_ready_capability_is_named_by_the_packs_own_terms(self):
        """c-630: a pack that names its tracker says "<name> is the tracker"."""
        named = packs.Pack(name="demo", version="1", description="", path=self.home,
                           terms={"tracker_name": "acme"})
        self.assertEqual(readiness.ready_why(named, "tracker"), "Acme is the tracker")
        self.assertEqual(readiness.ready_why(named, "codehost"), "the demo connection provides its code host")

    def test_a_failing_check_holds_back_only_the_capability_it_serves(self):
        cfg = self.with_work_on_sandbox()
        failing = [{"name": "tracker token", "kind": "secret", "ok": False,
                    "why": "the worktree verb mints stories with it", "for": ["tracker"]}]
        with mock.patch("keel.packs.checks", return_value=failing):
            rows = readiness.space_rows(cfg, cfg.spaces["work"])
        self.assertEqual(rows["tracker"]["why"],
                         "tracker token is not set up: the worktree verb mints stories with it")
        self.assertFalse(rows["tracker"]["ready"])
        self.assertTrue(rows["codehost"]["ready"])

    def test_missing_prerequisites_are_named(self):
        with mock.patch("keel.prereqs.gather", return_value=[MISSING]):
            row = readiness.prerequisites_row()
        self.assertEqual(row, {"ready": False, "why": "git: not found", "step": "prerequisites"})

    def test_slow_readings_are_kept_and_fresh_reads_again(self):
        with mock.patch("keel.prereqs.gather", return_value=[]) as gather:
            readiness.prerequisites_row()
            readiness.prerequisites_row()
            self.assertEqual(gather.call_count, 1)
            readiness.prerequisites_row(fresh=True)
            self.assertEqual(gather.call_count, 2)

    def test_a_reading_that_fails_is_a_row_not_a_crash(self):
        with mock.patch("keel.builder.status", side_effect=RuntimeError("boom")):
            rows = readiness.install_rows(self.cfg)
        self.assertEqual(rows["builder"], {"ready": False, "why": "could not be read: boom",
                                           "step": "builder"})

    def test_the_builder_is_ready_only_when_bosun_could_start_as_it(self):
        """The Meet Bosun step is done only when Start would not refuse (c-628 review r1.F2)."""
        from tests.test_builders import install_config
        cfg = install_config(self.home.parent / "built")
        self.assertEqual(readiness.builder_row(cfg), {"ready": True, "why": "Builder, auto mode",
                                                      "step": "builder"})
        cfg.builder = {"mode": "yolo"}
        row = readiness.builder_row(cfg)
        self.assertFalse(row["ready"])
        self.assertIn("[builder] mode is 'yolo'", row["why"])
        cfg.builder = {}
        shutil.rmtree(cfg.install_home / "builder" / "packs")
        self.assertEqual(readiness.builder_row(cfg)["why"], "Builder, auto mode; Start clones packs",
                         "Start makes a clone it has a live checkout for (r2.F2)")
        shutil.rmtree(cfg.install_home / "packs" / ".git")
        row = readiness.builder_row(cfg)
        self.assertFalse(row["ready"])
        self.assertIn("the builder has no clone of packs", row["why"])
        cfg.bosun_builder = False
        self.assertEqual(readiness.builder_row(cfg), {"ready": False, "why": "the builder is off",
                                                      "step": "builder"})

    def test_voice_is_ready_only_when_it_answers(self):
        def services(state, level):
            return {"services": [{"name": "voice", "state": state, "level": level}]}
        for reading, ready, why in ((services("not installed here", "off"), False, "voice is not installed"),
                                    (services("not answering", "red"), False, "voice is installed but not answering"),
                                    (services("answering", "green"), True, "voice is answering")):
            with mock.patch("keel.health.current", return_value=reading):
                row = readiness.voice_row(self.cfg)
            self.assertEqual((row["ready"], row["why"]), (ready, why))

    def scratch_pack(self, name: str, toml) -> Path:
        """A copy of the sandbox pack named `name`, its pack.toml passed through `toml`."""
        path = self.home.parent / "scratch-packs" / name
        shutil.copytree(ROOT / "packs" / "sandbox", path)
        text = (path / "pack.toml").read_text().replace('name = "sandbox"', f'name = "{name}"')
        (path / "pack.toml").write_text(toml(text))
        return path

    def on(self, path: Path | None, adapter: str | None = None):
        space = dataclasses.replace(self.cfg.spaces["personal"], name="work", adapter=adapter or (path and path.name),
                                    adapter_dir=path)
        self.cfg.spaces["work"] = space
        return space

    def test_a_refusal_says_what_the_row_says_for_every_undeclared_shape(self):
        """c-631: the backend refuses with the panel's sentence. No pack, a pack that does not
        load and a pack without the capability each give the row's own `why`."""
        trackeronly = self.scratch_pack("trackeronly", lambda text: text.replace("codehost = true\n", "")
                                        .replace("reviews = true\n", "").replace('routes = ["reviews"]', "routes = []"))
        broken = self.scratch_pack("broken", lambda text: text.replace("tracker = true", "tracker = true\nbogus = true"))
        for space in (self.on(None), self.on(trackeronly), self.on(broken)):
            rows = readiness.capability_rows(self.cfg, space)
            for cap in ("codehost", "reviews"):
                self.assertFalse(rows[cap]["ready"])
                self.assertEqual(readiness.refusal(self.cfg, space, cap), rows[cap]["why"], (space.adapter, cap))
        self.assertEqual(readiness.refusal(self.cfg, self.on(trackeronly), "codehost"),
                         "the trackeronly connection has no code host")
        self.assertIsNone(readiness.refusal(self.cfg, self.on(trackeronly), "tracker"))

    def test_a_refusal_is_declared_only_and_spares_an_older_adapter(self):
        """Decision refusal-basis: a failing check never refuses, only an undeclared claim. An
        adapter with no pack.toml predates packs and keeps today's pass."""
        sandbox = self.on(ROOT / "packs" / "sandbox")
        failing = [{"name": "token", "kind": "secret", "ok": False, "why": "unset", "for": ["codehost"]}]
        with mock.patch("keel.packs.checks", return_value=failing):
            self.assertFalse(readiness.capability_rows(self.cfg, sandbox, fresh=True)["codehost"]["ready"])
        self.assertIsNone(readiness.refusal(self.cfg, sandbox, "codehost"))
        older = self.home.parent / "older"
        older.mkdir()
        self.assertIsNone(readiness.refusal(self.cfg, self.on(older), "codehost"))
        self.assertFalse(readiness.capability_rows(self.cfg, self.on(older))["codehost"]["ready"])

    def test_a_capability_a_failing_check_holds_up_carries_that_checks_fix(self):
        """c-688: the row names each failing requirement with its fix, so the step that shows
        the row draws the pack's own stuck line. A row that fails for another reason, and a
        ready one, carry none."""
        needs = ('\n[[requires]]\nname = "token"\nkind = "secret"\ncheck = "false"\nwhy = "unset"\n'
                 'for = ["codehost"]\nfix = "Make a token."\ncommand = "forge login"\n'
                 'done_when = "It says hello."\n'
                 '\n[[requires]]\nname = "cli"\nkind = "command"\ncheck = "true"\nwhy = "w"\nfor = ["codehost"]\n')
        space = self.on(self.scratch_pack("needy", lambda text: text + needs))
        rows = readiness.capability_rows(self.cfg, space, fresh=True)
        self.assertEqual(rows["codehost"]["needs"], [{
            "name": "token", "kind": "secret", "ok": False, "why": "unset", "for": ["codehost"],
            "fix": "Make a token.", "command": "forge login", "done_when": "It says hello."}])
        self.assertEqual(rows["codehost"]["why"], "token is not set up: unset")
        self.assertNotIn("needs", rows["tracker"])
        self.assertNotIn("needs", rows["ci"])

    def test_a_space_that_turned_review_scanning_off_cannot_file_review_cards(self):
        """c-730: `review_scan` off is the space's own no to a capability its pack declares:
        the drain, the Reviews route and the row all say it, the first run does not wait on
        it, and the row says whether the space can use the capability at all (`declared`)."""
        space = dataclasses.replace(self.on(ROOT / "packs" / "sandbox"), review_scan=False)
        self.cfg.spaces["work"] = space
        rows = readiness.capability_rows(self.cfg, space, fresh=True)
        self.assertEqual(readiness.refusal(self.cfg, space, "reviews"), "review scanning is off for work")
        self.assertEqual((rows["reviews"]["ready"], rows["reviews"]["why"], rows["reviews"]["declared"]),
                         (False, "review scanning is off for work", False))
        self.assertTrue(rows["codehost"]["declared"])
        self.assertNotIn("reviews", readiness.wanted(space))
        on = dataclasses.replace(space, review_scan=True)
        self.assertIsNone(readiness.refusal(self.cfg, on, "reviews"))
        self.assertIn("reviews", readiness.wanted(on))
        self.assertTrue(readiness.capability_rows(self.cfg, on, fresh=True)["reviews"]["declared"])

    def test_a_packs_space_defaults_can_start_review_scanning_off_and_the_space_wins(self):
        """c-730: a pack may start `review_scan` off for every space on it; a space that says
        it wants reviews has them."""
        quiet = self.scratch_pack("quiet", lambda text: text + "\n[space]\nreview_scan = false\n"
                                  if "[space]" not in text else text.replace("[space]\n", "[space]\nreview_scan = false\n", 1))
        packs_dir = self.home / "packs"
        shutil.copytree(quiet, packs_dir / "quiet")
        toml = self.home / "config.toml"
        claude = self.cfg.spaces["personal"].config_dir
        toml.write_text(toml.read_text() + f'\n[spaces.off]\npack = "quiet"\nconfig_dir = "{claude}"\n'
                        f'\n[spaces.wants]\npack = "quiet"\nconfig_dir = "{claude}"\nreview_scan = true\n')
        with mock.patch("keel.packs.install_packs", return_value=packs_dir):
            cfg = self.load()
        self.assertFalse(cfg.spaces["off"].review_scan)
        self.assertTrue(cfg.spaces["wants"].review_scan)
        self.assertTrue(cfg.spaces["personal"].review_scan)      # Shipyard's own default is on

    def test_the_settings_form_and_the_config_read_a_pack_s_space_defaults_alike(self):
        """r1.F6: `pack =` lays the pack's `[space]` under the space and the form calls it the
        default; `adapter =` lays nothing, so the form names no pack default either."""
        from keel import settings
        quiet = self.scratch_pack("quiet", lambda text: text.replace("[space]\n", "[space]\nreview_scan = false\n", 1))
        packs_dir, adapters_dir = self.home / "packs", self.home.parent / "adapters"
        shutil.copytree(quiet, packs_dir / "quiet")
        shutil.copytree(quiet, adapters_dir / "quiet")
        claude = str(self.cfg.spaces["personal"].config_dir)
        with mock.patch("keel.packs.install_packs", return_value=packs_dir):
            spaces = {name: config_module._space(name, dict(table, config_dir=claude), self.home, adapters_dir)
                      for name, table in (("bypack", {"pack": "quiet"}), ("byadapter", {"adapter": "quiet"}))}
        cfg = dataclasses.replace(self.cfg, spaces=spaces)
        bypack = settings.space_values(cfg, "bypack", cfg.spaces["bypack"])["space.review_scan"]
        byadapter = settings.space_values(cfg, "byadapter", cfg.spaces["byadapter"])["space.review_scan"]
        self.assertEqual((cfg.spaces["bypack"].review_scan, bypack.get("default")), (False, False))
        self.assertEqual((cfg.spaces["byadapter"].review_scan, "default" in byadapter), (True, False))

    def test_a_pack_with_no_tracker_is_set_up_without_one(self):
        """c-730: a code host alone (the GitHub pack) can finish Where finished work goes; a
        tracker is needed only where the space's pack declares one."""
        hostonly = self.on(self.scratch_pack("hostonly", lambda text: text.replace("tracker = true\n", "")))
        self.assertNotIn("tracker", readiness.wanted(hostonly))
        self.assertIn("codehost", readiness.wanted(hostonly))
        self.assertIn("tracker", readiness.wanted(self.on(ROOT / "packs" / "sandbox")))

    def test_a_repos_refusal_is_the_repos_row(self):
        personal = self.cfg.spaces["personal"]
        self.assertEqual(readiness.refusal(self.cfg, personal, "repos"), "no repo is cloned for personal yet")
        repo = self.home.parent / "api"
        subprocess.run(["git", "init", "-q", str(repo)], check=True)
        personal.repos["api"] = repo
        self.assertIsNone(readiness.refusal(self.cfg, personal, "repos"))

    def test_the_deck_state_carries_readiness(self):
        with mock.patch("keel.prereqs.gather", return_value=[]), open_board(self.cfg) as board:
            state = deckstate.build(self.cfg, board)
        self.assertEqual(set(state["readiness"]), {"install", "spaces"})
        self.assertEqual(set(state["readiness"]["spaces"]), set(self.cfg.spaces))
        self.assertEqual(set(state["readiness"]["install"]),
                         {"prerequisites", "login", "voice", "builder", "segments", "phone", "browser", "backup"})
        self.assertEqual(set(state["readiness"]["spaces"]["personal"]),
                         {"repos", "tracker", "codehost", "reviews", "ci", "rules"})

    # ----- the rows the first run added (c-632) -----

    def test_phone_is_ready_when_tailscale_serve_proxies_to_the_deck(self):
        port = self.cfg.serve_port
        bin_dir = self.home.parent / "ts"
        fake_tailscale(bin_dir, served(port))
        self.assertEqual(readiness.phone_row(self.cfg, fresh=True),
                         {"ready": True, "why": "the phone reaches the deck at https://mac.tailnet.example",
                          "step": "set-up"})
        (bin_dir / "tailscale").unlink()
        fake_tailscale(bin_dir, served(port + 1))
        self.assertEqual(readiness.phone_row(self.cfg, fresh=True)["why"],
                         f"tailscale serve does not point at the deck (port {port})")
        fake_tailscale(bin_dir, "{}")
        readiness.phone_row(self.cfg, fresh=True)
        self.assertFalse(readiness.phone_row(self.cfg)["ready"])          # kept, not asked again

    def test_phone_says_so_when_tailscale_is_absent_or_fails(self):
        with mock.patch("shutil.which", return_value=None):
            self.assertEqual(readiness.phone_row(self.cfg, fresh=True)["why"], "tailscale is not installed")
        fake_tailscale(self.home.parent / "broken", "", code=1)
        self.assertIn("tailscale serve status failed", readiness.phone_row(self.cfg, fresh=True)["why"])

    def test_login_follows_login_json(self):
        # c-678: no command in the sentence, since the step the row points at shows the one
        self.assertEqual(readiness.login_row(self.cfg)["why"], "Shipyard is not signed in to Claude yet")
        at = login.now()
        for state, ready, why in ((login.GOOD, True, "the install's Claude login works"),
                                  (login.EXPIRED, False, "Shipyard is not signed in to Claude yet"),
                                  (login.UNKNOWN, True, "the install's Claude login could not be checked "
                                                        "last time (exit 2: x); houses try it as they run")):
            login.record(self.cfg, "personal", {"state": state, "why": "exit 2: x" if state == login.UNKNOWN else ""}, at)
            row = readiness.login_row(self.cfg)
            self.assertEqual((row["ready"], row["why"], row["step"]), (ready, why, "login"))
        # a folder that held a sign-in once: it ran out, and is not called "not signed in yet"
        (self.home / "claude").mkdir(parents=True, exist_ok=True)
        (self.home / "claude" / login.CREDENTIALS).write_text("{}")
        login.record(self.cfg, "personal", {"state": login.EXPIRED, "why": ""}, at)
        self.assertEqual(readiness.login_row(self.cfg)["why"], "Shipyard's Claude sign-in ran out, so no session can run")
        # true only while every space signs in there: with a space on its own sign-in, the
        # sentence names the space whose sessions stopped (review F15)
        onboarding.add_space(self.cfg, "team")
        cfg = config_module.load(self.cfg.source, ensure=False)
        cfg.spaces["team"].config_dir = self.home / "claude-team"
        self.assertEqual(readiness.login_row(cfg)["why"],
                         "Shipyard's Claude sign-in ran out, so no session of the personal space can run")

    def test_rules_turn_ready_once_the_space_tier_is_saved(self):
        personal = self.cfg.spaces["personal"]
        self.assertEqual(readiness.rules_row(self.cfg, personal)["why"], "the personal space has no tier yet")
        tier = self.home / "spaces" / "personal" / "CLAUDE.md"
        onboarding.ensure_tier(tier, self.cfg.root, "space", space="personal")
        self.assertEqual(readiness.rules_row(self.cfg, personal)["why"], "the personal tier is still the template")
        with open_board(self.cfg) as board:
            onboarding.save_tier(self.cfg, board, "personal", None, "Use pytest. Keep commits small.")
        self.assertEqual(readiness.rules_row(self.cfg, personal),
                         {"ready": True, "why": "the personal tier is written", "step": "rules"})


if __name__ == "__main__":
    unittest.main()
