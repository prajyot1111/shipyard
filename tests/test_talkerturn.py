"""The phone talker rotates for a memory change at a turn boundary (c-538, r-14).

On 2026-09-26 c-523 taught Harbor to connect to Bosun and the phone talker, a day-long
Remote Control conversation, kept the memory it started with until its daily reset. The
drain now rotates it once main's memory stamp moved, when its hooks say every session of
the run has ended its turn, and never while voice holds a house."""

import io
import json
import os
import subprocess
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock

from keel import memoryroot, talker, talkerturn
from tests.helpers import make_config
from tests.test_merging import make_repo, sh

ROOT = Path(__file__).resolve().parent.parent


class TalkerTurnCase(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.dir = Path(tmp.name)
        self.repo = make_repo(self.dir / "repo")
        self.commit("talker/memory/a.md", "a\n")
        self.paths = talker.Paths(root=self.repo, state_dir=self.dir / "state", home=self.dir)
        self.paths.state_dir.mkdir()
        (self.paths.state_dir / talker.POINTER).write_text("3\n")

    def commit(self, name, text):
        (self.repo / name).parent.mkdir(parents=True, exist_ok=True)
        (self.repo / name).write_text(text)
        sh(self.repo, "git", "add", ".")
        sh(self.repo, "git", "commit", "-q", "-m", name)

    def turn(self, event, session="s-phone"):
        talkerturn.hook(self.paths, event, {"session_id": session})


class DueTest(TalkerTurnCase):
    def test_nothing_is_due_while_memory_is_unchanged(self):
        talkerturn.run_memory(self.paths)
        self.turn("start"); self.turn("over")
        self.assertIsNone(talkerturn.due(self.paths, holding=False))

    def test_a_memory_change_is_due_between_turns(self):
        talkerturn.run_memory(self.paths)
        self.turn("start"); self.turn("over")
        self.commit("talker/memory/bosun.md", "Harbor can put him through to Bosun\n")
        self.assertEqual(talkerturn.due(self.paths, holding=False), talkerturn.DUE)

    def test_never_mid_turn(self):
        talkerturn.run_memory(self.paths)
        self.turn("start")
        self.commit("talker/memory/bosun.md", "b\n")
        self.assertIsNone(talkerturn.due(self.paths, holding=False))
        self.turn("over")
        self.assertEqual(talkerturn.due(self.paths, holding=False), talkerturn.DUE)

    def test_never_while_another_session_of_the_run_is_mid_turn(self):
        talkerturn.run_memory(self.paths)
        self.turn("over", "s-one"); self.turn("start", "s-two")
        self.commit("talker/memory/bosun.md", "b\n")
        self.assertIsNone(talkerturn.due(self.paths, holding=False))

    def test_never_during_a_voice_hold(self):
        talkerturn.run_memory(self.paths)
        self.turn("start"); self.turn("over")
        self.commit("talker/memory/bosun.md", "b\n")
        self.assertIsNone(talkerturn.due(self.paths, holding=True))

    def test_no_hook_of_this_run_is_never_idle(self):
        talkerturn.run_memory(self.paths)
        self.turn("over")
        (self.paths.state_dir / talker.POINTER).write_text("4\n")
        talkerturn.record_run(self.paths)
        self.commit("talker/memory/bosun.md", "b\n")
        self.assertIsNone(talkerturn.due(self.paths, holding=False))

    def test_a_run_with_no_record_takes_main_s_and_is_not_due(self):
        self.turn("start"); self.turn("over")
        self.assertIsNone(talkerturn.due(self.paths, holding=False))
        self.assertTrue((self.paths.state_dir / talkerturn.MEMORY_FILE).is_file())

    def test_an_event_without_a_session_writes_nothing(self):
        talkerturn.hook(self.paths, "over", {})
        self.assertFalse((self.paths.state_dir / talkerturn.TURN_FILE).exists())

    def test_status_writes_nothing(self):
        talkerturn.state(self.paths)
        self.assertFalse((self.paths.state_dir / talkerturn.MEMORY_FILE).exists())

    def test_status_says_where_it_stands(self):
        talkerturn.run_memory(self.paths)
        self.assertIn("main's", talkerturn.state(self.paths))
        self.commit("talker/memory/bosun.md", "b\n")
        self.assertIn("next turn boundary", talkerturn.state(self.paths))
        self.turn("over")
        self.assertIn("next pass", talkerturn.state(self.paths))
        self.assertIn("voice hold", talkerturn.state(self.paths, holding=True))


class InstallMemoryTest(TalkerTurnCase):
    """c-722: the talker's memory is the install's `memory/talker`, linked in as its
    auto-memory, and a commit there is what rotates it."""

    def setUp(self):
        super().setUp()
        self.install = self.dir / "install"
        self.memory = make_repo(self.install / "memory")
        (self.memory / "talker").mkdir()
        (self.memory / "talker" / "MEMORY.md").write_text("index\n")
        sh(self.memory, "git", "add", "."); sh(self.memory, "git", "commit", "-q", "-m", "seeded")
        self.paths = talker.Paths(root=self.repo, state_dir=self.paths.state_dir, home=self.dir,
                                  install=self.install)

    def test_the_memory_linked_in_is_the_installs(self):
        self.assertEqual(self.paths.memory_src, self.install / "memory" / "talker")
        bare = talker.Paths(root=self.repo, state_dir=self.paths.state_dir, install=self.dir / "none")
        self.assertEqual(bare.memory_src, self.repo / "talker" / "memory", "the checkout's until the move")

    def test_the_rulebook_linked_in_is_the_installs_else_the_shipped_one(self):
        """c-722 landing B: the config dir's CLAUDE.md is a link to the rulebook beside the
        talker's memory; an install with none of its own reads the code's template, and a
        file of the user's own that is not a link is never replaced."""
        shipped = self.repo / "templates" / "memory" / "talker" / "CLAUDE.md"
        memoryroot.write_seeded(self.install, {"templates/memory/talker/MEMORY.md": "x"})   # init seeded it
        self.assertEqual(self.paths.rules_src, shipped)
        self.assertTrue(talker.link_rules(self.paths))
        self.assertEqual(os.readlink(self.paths.rules_link), str(shipped))
        (self.memory / "talker" / "CLAUDE.md").write_text("the user's own rules\n")
        self.assertTrue(talker.link_rules(self.paths))
        self.assertEqual(self.paths.rules_link.read_text(), "the user's own rules\n")
        self.paths.rules_link.unlink()
        self.paths.rules_link.write_text("written by hand\n")
        self.assertFalse(talker.link_rules(self.paths))
        self.assertEqual(self.paths.rules_link.read_text(), "written by hand\n")

    def test_a_memory_the_shipped_rulebook_was_not_written_for_gets_none(self):
        """r1.F10, r3.F4: the template rulebook is for a memory seeded from the template, told
        by init's seeding record (`memoryroot.SEEDED`), never by a shared file name: an
        owner's own memory that has its own voice.md, as the template does, gets nothing
        linked rather than the wrong rules."""
        template = self.repo / "templates" / "memory" / "talker"
        template.mkdir(parents=True)
        (template / "CLAUDE.md").write_text("the shipped rules\n")
        (template / "voice.md").write_text("x\n")
        (self.memory / "talker" / "voice.md").write_text("the owner's own voice notes\n")
        self.assertIsNone(self.paths.rules_src)
        self.assertFalse(talker.link_rules(self.paths))
        self.assertFalse(self.paths.rules_link.is_symlink())
        memoryroot.write_seeded(self.install, {"templates/memory/talker/voice.md": "x"})
        self.assertEqual(self.paths.rules_src, template / "CLAUDE.md")

    def test_with_no_rulebook_to_link_the_note_says_what_is_in_use_and_why(self):
        """r4.F2: an owner's memory, not seeded from the template, has no rulebook to link. A
        file of the config dir's own is in use and said so; with none, the note says the
        template is not used because the memory was not seeded from it."""
        template = self.repo / "templates" / "memory" / "talker"
        template.mkdir(parents=True)
        (template / "CLAUDE.md").write_text("the shipped rules\n")
        self.assertIsNone(self.paths.rules_src)
        note = talker.rules_note(self.paths)
        self.assertIn("no rulebook linked", note)
        self.assertIn("not seeded from the template", note)
        self.paths.rules_link.parent.mkdir(parents=True, exist_ok=True)
        self.paths.rules_link.write_text("the rules the talker reads today\n")
        self.assertEqual(talker.rules_note(self.paths),
                         f"using {self.paths.rules_link}, the config dir's own; the install holds no rulebook yet")

    def test_a_link_pointed_elsewhere_on_purpose_is_kept_and_said(self):
        """r2.F8: only a missing entry, a dangling link or one Keel made is replaced."""
        (self.memory / "talker" / "CLAUDE.md").write_text("the install's rules\n")
        mine = self.dir / "my-rules.md"
        mine.write_text("mine\n")
        self.paths.rules_link.parent.mkdir(parents=True, exist_ok=True)
        self.paths.rules_link.symlink_to(mine)
        self.assertFalse(talker.link_rules(self.paths))
        self.assertEqual(os.readlink(self.paths.rules_link), str(mine))
        self.assertIn(f"kept {self.paths.rules_link}", talker.rules_note(self.paths))
        mine.unlink()                                          # now dangling: replaced
        self.assertTrue(talker.link_rules(self.paths))
        self.assertIn("linked", talker.rules_note(self.paths))

    def test_the_skill_links_the_install_records_are_made_and_never_over_one_there(self):
        """r1.F3."""
        (self.memory / "talker" / "skills.json").write_text(
            json.dumps({"lavish": "/elsewhere/lavish", "mine": "/elsewhere/mine"}))
        (self.paths.skills_dir / "mine").mkdir(parents=True)
        self.assertEqual(talker.link_skills(self.paths), ["lavish"])
        self.assertEqual(os.readlink(self.paths.skills_dir / "lavish"), "/elsewhere/lavish")
        self.assertFalse((self.paths.skills_dir / "mine").is_symlink())
        self.assertEqual(talker.link_skills(self.paths), [])

    def test_paths_from_an_install_config_name_the_install(self):
        self.install.joinpath("config.toml").write_text(
            "[keel]\n"f'state_dir = "{self.dir / "state"}"\n'"[spaces.personal]\n"'config_dir = "~/x"\n')
        from keel import config as config_module
        self.assertEqual(talker.paths_from(config_module.load(self.install / "config.toml", ensure=False)).install,
                         self.install)

    def test_a_commit_in_the_install_is_due_and_one_in_the_checkout_is_not(self):
        talkerturn.run_memory(self.paths)
        self.turn("start"); self.turn("over")
        self.commit("talker/memory/bosun.md", "the checkout's old copy\n")
        self.assertIsNone(talkerturn.due(self.paths, holding=False))
        (self.memory / "talker" / "bosun.md").write_text("b\n")
        sh(self.memory, "git", "add", "."); sh(self.memory, "git", "commit", "-q", "-m", "b")
        self.assertEqual(talkerturn.due(self.paths, holding=False), talkerturn.DUE)


class UpkeepTest(TalkerTurnCase):
    def upkeep(self, holding=False):
        cfg = make_config(self.dir)
        cfg.talker_reset_max_age_seconds = 86400
        with mock.patch.object(talker, "paths_from", return_value=self.paths), \
                mock.patch.object(talker, "alive", return_value=True), \
                mock.patch.object(talker, "do_fresh") as fresh:
            return talker.upkeep(cfg, now=time.time(), holding=holding), fresh

    def test_the_drain_rotates_for_memory_at_a_boundary(self):
        talkerturn.run_memory(self.paths)
        self.turn("start"); self.turn("over")
        self.commit("talker/memory/bosun.md", "b\n")
        result, fresh = self.upkeep()
        self.assertTrue(result["reset"])
        self.assertIn("memory", fresh.call_args.kwargs["reason"])

    def test_upkeep_waits_unless_told_no_hold_is_live(self):
        talkerturn.run_memory(self.paths)
        self.turn("over")
        self.commit("talker/memory/bosun.md", "b\n")
        cfg = make_config(self.dir)
        with mock.patch.object(talker, "paths_from", return_value=self.paths), \
                mock.patch.object(talker, "alive", return_value=True), \
                mock.patch.object(talker, "do_fresh") as fresh:
            self.assertFalse(talker.upkeep(cfg, now=time.time())["reset"])
        fresh.assert_not_called()

    def test_the_drain_waits_for_a_voice_hold(self):
        talkerturn.run_memory(self.paths)
        self.turn("over")
        self.commit("talker/memory/bosun.md", "b\n")
        result, fresh = self.upkeep(holding=True)
        self.assertFalse(result["reset"])
        fresh.assert_not_called()

    def test_a_rotation_records_the_memory_the_new_run_starts_on(self):
        talkerturn.run_memory(self.paths)
        self.commit("talker/memory/bosun.md", "b\n")
        with mock.patch.object(talker, "restart_agent", return_value={"ok": False, "how": "t"}):
            talker.do_fresh(self.paths, reason="memory")
        record = json.loads((self.paths.state_dir / talkerturn.MEMORY_FILE).read_text())
        self.assertEqual(record["run"], self.paths.run_index())
        self.assertIsNone(talkerturn.due(self.paths, holding=False))


class HookTest(TalkerTurnCase):
    def test_the_verb_reads_the_hook_json_and_always_exits_0(self):
        with mock.patch("sys.stdin", io.StringIO(json.dumps({"session_id": "s-1"}))):
            self.assertEqual(talker.turn(self.paths, "start"), 0)
        with mock.patch("sys.stdin", io.StringIO("not json")):
            self.assertEqual(talker.turn(self.paths, "over"), 0)
        doc = json.loads((self.paths.state_dir / talkerturn.TURN_FILE).read_text())
        self.assertEqual(doc["sessions"]["s-1"]["event"], "start")

    def test_the_hooks_run_only_in_the_talker_s_own_processes(self):
        settings = json.loads((ROOT / "spaces" / "harbor" / ".claude" / "settings.json").read_text())
        for event, word in (("UserPromptSubmit", "start"), ("Stop", "over")):
            command = settings["hooks"][event][0]["hooks"][0]["command"]
            self.assertTrue(command.endswith(f"talker turn {word}"), command)
            env = {"PATH": os.environ["PATH"], "KEEL_HOME": "/nowhere"}
            done = subprocess.run(["sh", "-c", command], env=env, capture_output=True, text=True)
            self.assertEqual((done.returncode, done.stdout), (0, ""), "a voice turn pays nothing")
        self.assertNotIn(talkerturn.ENV, talker.environment(self.paths), "a shell thread is not counted")
        with mock.patch.object(talker.subprocess, "Popen") as popen:
            talker.spawn(self.paths, None)
        self.assertEqual(popen.call_args.kwargs["env"][talkerturn.ENV], "1")


if __name__ == "__main__":
    unittest.main()
