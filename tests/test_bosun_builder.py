"""Builder mode: `[keel] bosun_builder` (`keel/authority.py`, "Builder mode").

With the switch on, Bosun acts on personal cards as on its own: it files, edits, archives,
moves, splits, notes and unblocks them, and approves their outcomes (never a plan gate,
which stays his). An outcome it approves still lands only on an integration branch, lints
clean and carries a review stamp, and may touch Bosun's own authority and the deploy's code.
Its guard lets it write its authority files, never its settings. Work cards stay his. With
the switch off, every one of those is refused.
"""

import tempfile
import unittest
from pathlib import Path

from keel import authority, console
from keel import config as config_module
from keel.board import Board, Refused
from tests.test_authority import GOOD, BosunCase
from tests.test_console import console_toml


def switch_on(path: Path) -> None:
    """Builder mode as the superuser over Keel's repo, the box's own (`keel/builder.py`)."""
    path.write_text(path.read_text().replace("[keel]\n", "[keel]\nbosun_builder = true\n", 1)
                    + '\n[builder]\nsuperuser = true\nrepos = ["keel"]\n')


class SwitchTest(unittest.TestCase):
    def test_off_by_default_and_named_among_the_switches_when_on(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = console_toml(Path(tmp))
            cfg = config_module.load(path, ensure=False)
            self.assertFalse(cfg.bosun_builder)
            self.assertNotIn(authority.BUILDER, cfg.switches)
            switch_on(path)
            cfg = config_module.load(path, ensure=False)
            self.assertTrue(cfg.bosun_builder)
            self.assertIn(authority.BUILDER, cfg.switches)


class BuilderOnTest(BosunCase):
    def setUp(self):
        super().setUp()
        switch_on(self.dir / "keel.toml")

    def test_bosun_files_edits_moves_and_splits_personal_cards(self):
        code, card, err = self.as_bosun("create", "--space", "personal", "--title", "fix",
                                        "--repo", "keel", "--autonomy", "attended")
        self.assertEqual(code, 0, err)
        self.assertEqual(self.as_bosun("set", card, "title=better")[0], 0)
        self.assertEqual(self.as_bosun("stage", card, "assigned")[0], 0)
        self.assertEqual(self.board().get(card)["stage"], "assigned")
        code, _, err = self.as_bosun("split", self.personal("big"), "--slice", "a|x")
        self.assertEqual(code, 0, err)
        self.assertEqual(self.as_bosun("note", self.personal("another"), "seen")[0], 0)

    def test_other_spaces_stay_his(self):
        with self.assertRaises(Refused) as caught:
            authority.refuse_create("work", None, authority.BOSUN, builder=True)
        self.assertIn("only in the personal space", str(caught.exception))
        with self.assertRaises(Refused) as caught:
            authority.refuse_create("console", None, authority.BOSUN, builder=True)
        self.assertIn("retired", str(caught.exception))
        work = self.board().create("work", "w", actor="human")
        self.refused("Bosun changes no field", "set", work, "title=new")
        self.refused("only personal cards in builder mode", "stage", work, "assigned")
        self.refused("writes no note on it", "note", work, "seen")
        self.board().block(work, "stuck", "house")
        self.refused("its block is his", "unblock", work)

    def test_a_gate_still_goes_through_approve(self):
        card = self.personal()
        self.at_plan_gate(card)
        self.refused("only through `approve plan`", "stage", card, "building")

    def test_it_unblocks_its_own_cards_with_no_limit_and_records_no_intervention(self):
        card = self.personal()
        for n in range(5):
            self.board().block(card, f"stuck {n}", "house")
            code, _, err = self.as_bosun("unblock", card)
            self.assertEqual(code, 0, err)
        self.assertFalse([e for e in self.board().events(card) if e["kind"] == "intervene"])

    def test_a_held_card_still_waits(self):
        card = self.personal()
        board = self.board()
        board.block(card, "stuck", "house")
        board.set_fields(card, {"options": {"dropin_hold": {"at": board.now()}}}, "human")
        self.refused("is held", "unblock", card)

    def test_his_attended_plan_gate_stays_his(self):
        """An attended personal card is how he asks to see a plan first: Bosun never passes it."""
        card = self.personal()
        self.at_plan_gate(card)
        self.refused("plan gate is his", "approve", card, "plan", "--checked", "x")
        self.assertEqual(self.board().get(card)["stage"], "planning")

    def test_bosun_archives_and_lands_its_cards(self):
        card = self.personal()
        code, _, err = self.as_bosun("set", card, "options.archived=true")
        self.assertEqual(code, 0, err)
        building = self.board().create("personal", "fix", repo="keel", actor="human",
                                       autonomy="autonomous")
        self.as_bosun("stage", building, "building")
        code, _, err = self.as_bosun("stage", building, "done", "--note", "landed on next as abc")
        self.assertEqual(code, 0, err)
        self.assertEqual(self.board().get(building)["stage"], "done")

    def test_the_drain_leaves_a_personal_repo_card_to_bosun(self):
        board = self.board()
        repo = board.create("personal", "fix", repo="keel", actor="human", autonomy="autonomous")
        errand = board.create("personal", "plan a trip", actor="human", autonomy="autonomous")
        for card in (repo, errand):
            board.stage(card, "assigned", "human")
        live = Board(self.dir / "state" / "board.db", switches={authority.BUILDER, authority.SUPERUSER},
                     builds={"keel"})
        self.addCleanup(live.close)
        self.assertEqual((live.get(repo)["derived"]["startable"], live.get(repo)["derived"]["bosun"]),
                         (False, True))
        self.assertEqual((live.get(errand)["derived"]["startable"], live.get(errand)["derived"]["bosun"]),
                         (True, False))
        self.assertTrue(board.get(repo)["derived"]["startable"], "without the switch it is a house's")


class BuilderOutcomeTest(unittest.TestCase):
    """Bosun's outcome approval on a personal card, with and without the switch."""

    def open(self, *switches):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.board = Board(Path(self.tmp.name) / "board.db",
                           switches={"merge_queue", authority.SUPERUSER, *switches}, builds={"keel"})
        self.addCleanup(self.board.close)
        self.card = self.board.create("personal", "t", repo="keel", actor="human",
                                      autonomy="autonomous")
        self.board.stage(self.card, "assigned", "human")
        self.board.stage(self.card, "building", "human", plan_ref="p.md")
        self.board.stage(self.card, "review", "human", output_ref="keel/b")

    def approve(self, **change):
        return self.board.approve(self.card, "outcome", authority.BOSUN,
                                  bosun={"checked": "lint, review", "to": "box",
                                         "facts": dict(GOOD, **change)})

    def test_on_it_lands_whatever_repairs_came_before(self):
        self.open(authority.BUILDER)
        for _ in range(5):
            self.board.record_event(self.card, authority.INTERVENE_EVENT, authority.BOSUN,
                                    text="repair resume: x", data={"what": "repair"})
        self.approve()
        relay = next(e for e in self.board.events(self.card) if e["kind"] == "relay")
        self.assertEqual((relay["actor"], relay["data"]["what"]), ("bosun", "land"))
        note = [e["text"] for e in self.board.events(self.card) if e["kind"] == "note"][-1]
        self.assertIn("approved by bosun, in builder mode", note)
        self.assertIn("lands on next", note)

    def test_on_the_landing_checks_still_hold(self):
        self.open(authority.BUILDER)
        for change, said in (({"integration": None}, "no integration branch"),
                             ({"trunk": "next"}, "the branch the machines run"),
                             ({"sha": None}, "no branch sha"),
                             ({"errors": ["C26 no Evidence"]}, "does not check clean"),
                             ({"reviewed": False}, "no review stamp covers")):
            with self.subTest(change=change):
                with self.assertRaises(Refused) as caught:
                    self.approve(**change)
                self.assertIn(said, str(caught.exception))
        self.assertFalse([e for e in self.board.events(self.card) if e["kind"] == "relay"])

    def test_on_a_work_card_is_still_his(self):
        work = {"id": "c-9", "space": "work", "options": "{}"}
        for gate in ("plan", "outcome"):
            with self.subTest(gate=gate), self.assertRaises(Refused) as caught:
                authority.gate_approval(work, gate, GOOD, "x", builder=True)
            self.assertIn("its gates are his", str(caught.exception))

    def test_off_the_outcome_is_his(self):
        self.open()
        with self.assertRaises(Refused) as caught:
            self.approve()
        self.assertIn("only in builder mode", str(caught.exception))

    def test_off_old_driver_and_grant_options_change_nothing(self):
        self.open()
        self.board.set_fields(self.card, {"options": {"driver": "bosun",
                                                      "grant": {"by": "human"}}}, "human")
        with self.assertRaises(Refused) as caught:
            self.approve()
        self.assertIn("only in builder mode", str(caught.exception))


class BuilderSettingsTest(unittest.TestCase):
    """Bosun's session: its guard and its allow rules follow the switch."""

    def cfg(self, builder: bool):
        return type("C", (), {"root": Path("/k"), "bosun_builder": builder, "builder": {"superuser": True}})

    def verdict(self, builder: bool, command: str):
        return console.guard_verdict(self.cfg(builder), {"tool_name": "Bash",
                                                         "tool_input": {"command": command}})

    def test_on_its_authority_is_writable_and_its_settings_are_not(self):
        for command in ("sed -i s/a/b/ keel/authority.py",
                        "echo x >> /k/bosun/memory/authority.md",
                        "cp /tmp/x /k/state/worktrees/c-9/keel/repair.py",
                        "git checkout keel/console.py"):
            with self.subTest(command=command):
                self.assertIsNone(self.verdict(True, command))
                self.assertTrue(self.verdict(False, command))
        self.assertTrue(self.verdict(True, "cp /tmp/x ~/.config/keel/credentials/bosun-settings.json"))

    def test_on_the_editing_tools_write_its_authority_but_not_its_settings(self):
        def edit(builder, path):
            return console.guard_verdict(self.cfg(builder), {
                "tool_name": "Edit", "tool_input": {"file_path": path}})
        self.assertIsNone(edit(True, "/k/keel/authority.py"))
        self.assertIn("personal card he approves", edit(False, "/k/keel/authority.py"))
        self.assertTrue(edit(True, "/h/.config/keel/credentials/bosun-settings.json"))

    def test_the_git_and_test_steps_are_allowed_only_when_on(self):
        rules = console.builder_allow()
        self.assertIn("Bash(git commit:*)", rules)
        self.assertIn("Bash(make test-changed:*)", rules)
        self.assertFalse([rule for rule in rules
                          if any(verb in rule for verb in ("push", "merge", "rebase", "reset"))])
        with tempfile.TemporaryDirectory() as tmp:
            path = console_toml(Path(tmp))
            from unittest import mock
            with mock.patch.object(console, "key_of", return_value="k"):
                off = console.settings(config_module.load(path, ensure=False))
                switch_on(path)
                on = console.settings(config_module.load(path, ensure=False))
        self.assertNotIn("Bash(git commit:*)", off["permissions"]["allow"])
        self.assertIn("Bash(git commit:*)", on["permissions"]["allow"])
        with tempfile.TemporaryDirectory() as tmp:
            authority_rules = set(console.authority_deny(config_module.load(console_toml(Path(tmp)),
                                                                            ensure=False)))
        self.assertEqual(set(off["permissions"]["deny"]) - authority_rules,
                         set(on["permissions"]["deny"]))
        self.assertTrue(authority_rules <= set(off["permissions"]["deny"]))


if __name__ == "__main__":
    unittest.main()
