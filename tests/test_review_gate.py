"""The review step of the pre-gate pipeline, and the gate that holds it (N4, E-9, HP-1, HP-2).

A repo card's house is given Keel's two read-only agents (`--agents`, the house's own
model): the reviewer and the verifier. The house prepares the diff and the standards with
`bin/keel-review prep`, calls the reviewer with paths only, then the verifier when there
is anything to verify. The harness's SubagentStop hook records both answers in the finding
schema and writes the stamp when the round is complete, and the Stop hook refuses the
review stage (back to building) unless the stamp is for the CURRENT HEAD, or for the same
change on a newer base. Errands, research and review cards skip it, and so does a space
with `house_review` off.
"""

import contextlib
import io
import json
import subprocess
import tempfile
import tomllib
import unittest
from pathlib import Path
from unittest import mock

from keel import config as config_module, ending, harness, house, settings
from keel.board import Board
from keel.review import agents, brief, gate, prep, stamp, testrun
from tests.helpers import ROOT, SESSION, FakeHarness, make_config, make_repo

GIT = ("git", "-c", "user.name=t", "-c", "user.email=t@x")
HIGH = {"id": "F1", "axis": "spec", "severity": "high", "path": "README", "line": 1,
        "claim": "the thing is not made", "evidence": "README:1 says scratch",
        "suggestion": "make it"}


def sh(cwd, *args):
    return subprocess.run(args, cwd=str(cwd), capture_output=True, text=True, check=True).stdout.strip()


def answer(items) -> str:
    return "```json\n" + json.dumps(items) + "\n```"


class ReviewCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.dir = Path(self.tmp.name)
        self.repo = make_repo(self.dir / "repo")
        self.cfg = make_config(self.dir, repos={"keel": self.repo})
        self.cfg.spaces["personal"].house_review = True
        self.board = Board(self.cfg.db_path)
        self.addCleanup(self.board.close)
        self.fake = FakeHarness()
        patch = mock.patch.object(house, "harness", self.fake)
        patch.start()
        self.addCleanup(patch.stop)

    def card(self, repo="keel", **kwargs) -> str:
        card_id = self.board.create("personal", "Add a thing", brief="make the thing", repo=repo,
                                    actor="human", **kwargs)
        self.board.stage(card_id, "assigned", "human")
        return card_id


class DefinitionTest(ReviewCase):
    def test_session_flags_carry_both_agents_only_when_given(self):
        flags = harness.session_flags("/s.json", model="opus", agents=agents.agents_json())
        defined = json.loads(flags[flags.index("--agents") + 1])
        self.assertEqual(set(defined), {agents.REVIEWER, agents.VERIFIER})
        self.assertNotIn("--agents", harness.session_flags("/s.json", model="opus"))


class WantedTest(ReviewCase):
    def test_a_review_card_is_never_stamped(self):
        """A peer review must never stamp a colleague's branch (HP-3)."""
        mine = self.board.get(self.card())
        self.assertTrue(gate.wanted(self.cfg, mine))
        for options in ({"review_key": "repo#12"}, {"kind": "review"}, {"kind": "research"},
                        {"drop": True}):
            self.assertFalse(gate.wanted(self.cfg, dict(mine, options=options)), options)

    def test_a_personal_card_with_no_repo_runs_no_code_review(self):
        """c-593: research, a plan or an errand (no repo) gets no pipeline in a space whose
        house_review is on; only a card with a repo does."""
        self.cfg.spaces["personal"].house_review = True
        errand = self.board.get(self.board.create("personal", "find a flight", actor="human"))
        self.assertIsNone(errand["repo"])
        self.assertFalse(gate.wanted(self.cfg, errand))
        self.assertTrue(gate.wanted(self.cfg, dict(errand, repo="keel")))

    def test_the_shipped_example_turns_the_review_on(self):
        """c-722: no one's own config is tracked; the example is what a new install gets. A
        pack's space (work) carries its own defaults in its pack."""
        table = tomllib.loads((ROOT / "etc" / "shipyard.example.toml").read_text())
        self.assertTrue(table["spaces"]["personal"].get("house_review"))

    def test_each_space_names_its_pipeline_text_and_the_core_ones_are_there(self):
        """The personal pipeline ships with the core. The work space's pipeline and its review
        defaults (house_review, preship_first, review_full_rounds, and full_rounds_max for the
        work space) are its pack's, in the install's packs repo, so no check here covers them:
        the pack test for them is being added in that repo by c-728, and the adapters job
        runs that suite from the install (tests/packsuites.py, c-726)."""
        table = tomllib.loads((ROOT / "etc" / "shipyard.example.toml").read_text())
        self.assertTrue((ROOT / table["spaces"]["personal"]["pipeline"]).is_file())


class PreshipFirstTest(ReviewCase):
    """c-597: a space with `preship_first` (work) runs preship, with the push and the draft,
    before the review, verify in the background on that head, one full pass then a fix check."""

    def test_the_shipped_example_leaves_it_off_for_personal(self):
        """The work space's `preship_first` is its pack's own default (c-722: the pack is in
        the install); the shipped example's personal space runs review first."""
        loaded = config_module.load(ROOT / "etc" / "shipyard.example.toml", ensure=False)
        self.assertFalse(loaded.spaces["personal"].preship_first)
        self.assertIsNone(loaded.spaces["personal"].review_full_rounds)
        self.assertEqual(stamp.full_rounds_max(loaded, "personal"), stamp.FULL_ROUNDS_MAX)

    def work_brief(self, full_max=1) -> str:
        return brief.brief_block(self.dir / "card", "staging", Path("/k/bin/keel-review"),
                                 pipeline=ROOT / "tests" / "fixtures" / "pipeline-preship.md",
                                 preship_first=True, full_max=full_max)

    def test_preship_and_the_draft_come_before_the_reviewer(self):
        text = self.work_brief()
        order = [text.index(word) for word in (
            "1. **Preship.**", "`git fetch origin`", "`@api_docs`", "Commit all of it now",
            "git push -u origin HEAD", "packs/demo/pr $KEEL_CARD", "head is FIXED",
            "2. **Verify, in the background.**", "run_in_background", "the full suite, ONCE",
            "3. **Review, while they run.**", f'subagent_type: "{agents.REVIEWER}"',
            "Fixes come after the pass closes", "--since", "4. **Risk.**")]
        self.assertEqual(order, sorted(order))
        self.assertIn("ONE full review pass per trip:", text)
        self.assertNotIn("A second full review is earned", text)
        self.assertNotIn("   > ", text, "the space's words are indented, not quoted")
        self.assertNotIn(chr(0x2014), text)

    def test_the_fixes_are_linted_again_before_the_fix_check(self):
        """c-597 review: lint and docs ran in preship, before the fixes; the fixed head is
        linted again, and its touched endpoints documented, before the fix check."""
        text = self.work_brief()
        again = text.index("linters again on the fixed head")
        self.assertLess(text.index("Fixes come after the pass closes"), again)
        self.assertLess(again, text.index("--since"))
        self.assertIn("docs for any endpoint\n     a fix touched", text)

    def test_a_card_at_shipping_gets_the_serial_form_with_no_push(self):
        """c-597 review, c-600: a house at shipping is refused the push and the draft, so even
        in a preship-first space its brief names neither."""
        self.cfg.spaces["personal"].preship_first = True
        self.cfg.spaces["personal"].pipeline = ROOT / "tests" / "fixtures" / "pipeline-preship.md"
        card_id = self.card()
        text = house.review_block(self.cfg, dict(self.board.get(card_id), stage="shipping"))
        self.assertLess(text.index("1. **Review.**"), text.index("3. **Preship.**"))
        for absent in ("git push", "packs/demo/pr", "force-with-lease", "## Publish"):
            self.assertNotIn(absent, text)
        self.assertTrue(house.at_shipping({"stage": "shipping"}))
        self.assertFalse(house.at_shipping({"stage": "review", "options": {"shipping": {"round": 1}}}))

    def test_the_stamp_hook_carries_the_space_s_limit(self):
        """c-597 review: the limit is on the hook's command line, so a hook that cannot read
        the board never falls back to another."""
        self.cfg.spaces["personal"].review_full_rounds = 1
        card_id = self.card()
        house.launch(self.cfg, self.board, card_id)
        settings = json.loads((self.cfg.card_dir(card_id) / "settings.json").read_text())
        for group in settings["hooks"]["SubagentStop"]:
            self.assertTrue(group["hooks"][0]["command"].endswith(f"{card_id} {stamp.FULL_MAX_FLAG} 1"))
        self.assertEqual(stamp.without_full_max([card_id, "--full-max", "1"]), ([card_id], 1))
        self.assertEqual(stamp.without_full_max([card_id, "--peer"]), ([card_id, "--peer"], None))
        self.assertEqual(stamp.without_full_max([card_id, "--full-max", "0"]), ([card_id], None))

    def test_a_limit_below_one_is_never_taken(self):
        """c-633: the schema reads it. A value below one, or not a whole number, is refused by
        the Settings form and, at load, warned about with the default used instead."""
        rule = settings.find("space", "review_full_rounds")
        self.assertEqual(settings.parse(rule, 1), 1)
        for bad in (0, -1, "1", True, 1.5):
            with self.assertRaisesRegex(settings.SettingError, "review_full_rounds"):
                settings.parse(rule, bad, "work")
        typed, warned = settings.check({"review_full_rounds": 0}, "space", "[spaces.work]", "work")
        self.assertIsNone(typed["review_full_rounds"])
        self.assertIn("[spaces.work] review_full_rounds = 0 is not a whole number", warned[0])

    def test_a_space_that_names_none_takes_keel_s_setting(self):
        self.cfg.review_full_rounds = 3
        self.assertEqual(stamp.full_rounds_max(self.cfg, "personal"), 3)
        self.cfg.spaces["personal"].review_full_rounds = 1
        self.assertEqual(stamp.full_rounds_max(self.cfg, "personal"), 1)

    def test_a_limit_of_two_keeps_the_earned_rule(self):
        text = self.work_brief(full_max=2)
        self.assertIn("never more than 2 per", text)

    def test_the_serial_order_is_unchanged_without_it(self):
        text = brief.brief_block(self.dir / "card", "main", Path("/k/bin/keel-review"),
                                 pipeline=ROOT / "etc" / "pipeline-personal.md", tests="make t")
        order = [text.index(word) for word in ("1. **Review.**", "2. **Verify.**", "3. **Preship.**", "4. **Risk.**")]
        self.assertEqual(order, sorted(order))
        self.assertNotIn("## Publish", text)
        self.assertNotIn("git push", text)
        self.assertNotIn("   > ", text)

    def test_a_work_card_s_brief_is_launched_with_it(self):
        self.cfg.spaces["personal"].preship_first = True
        self.cfg.spaces["personal"].review_full_rounds = 1
        card_id = self.card()
        house.launch(self.cfg, self.board, card_id)
        text = (self.cfg.card_dir(card_id) / "brief.md").read_text()
        self.assertLess(text.index("**Preship.**"), text.index("**Review, while they run.**"))
        self.assertIn("ONE full review pass per trip:", text)


class LaunchTest(ReviewCase):
    def test_a_repo_card_gets_both_agents_the_pipeline_and_its_requirements(self):
        card_id = self.card()
        house.launch(self.cfg, self.board, card_id)
        self.assertEqual(set(json.loads(self.fake.starts[0]["agents"])), {agents.REVIEWER, agents.VERIFIER})
        brief = (self.cfg.card_dir(card_id) / "brief.md").read_text()
        for word in (agents.REVIEWER, agents.VERIFIER, "keel-review prep", "keel-review answer",
                     "**Review.**", "**Verify.**", "**Preship.**", "**Risk.**"):
            self.assertIn(word, brief)
        self.assertLess(brief.index("**Review.**"), brief.index("**Verify.**"))
        self.assertLess(brief.index("**Verify.**"), brief.index("**Preship.**"))
        self.assertLess(brief.index("**Preship.**"), brief.index("**Risk.**"))
        requirements = (self.cfg.card_dir(card_id) / gate.REQUIREMENTS_FILE).read_text()
        self.assertIn("make the thing", requirements)

    def test_the_verify_step_names_the_house_s_command_and_not_the_landing_s(self):
        """c-544: the full suite runs once, where it lands; a house runs `[house_tests]`,
        its base filled in, and a repo without one runs its `[tests]`."""
        self.cfg.repo_tests["keel"] = "make test"
        self.cfg.house_tests["keel"] = "make test-changed BASE={base}"
        self.cfg.spaces["personal"].pipeline = ROOT / "etc" / "pipeline-personal.md"
        card_id = self.card()
        house.launch(self.cfg, self.board, card_id)
        brief = (self.cfg.card_dir(card_id) / "brief.md").read_text()
        verify = brief[brief.index("**Verify.**"):brief.index("**Preship.**")]
        self.assertIn(f"`make test-changed BASE={house.target_of(self.cfg, self.board.get(card_id))}`", verify)
        self.assertIn("review stamp records which suite ran", verify)
        self.cfg.house_tests.clear()
        self.assertEqual(house.house_tests(self.cfg, self.board.get(card_id), "main"), "make test")

    def test_the_shipped_toml_has_keel_s_house_run_targeted(self):
        loaded = config_module.load(ROOT / "etc" / "shipyard.example.toml", ensure=False)
        self.assertEqual(loaded.house_tests["keel"], "make test-changed BASE={base}")
        self.assertEqual(loaded.repo_tests["keel"], "make test BASE={base}")

    def test_an_errand_and_a_space_with_it_off_get_neither(self):
        errand = self.card(repo=None)
        house.launch(self.cfg, self.board, errand)
        self.assertIsNone(self.fake.starts[0].get("agents"))
        self.assertNotIn(agents.REVIEWER, (self.cfg.card_dir(errand) / "brief.md").read_text())
        self.cfg.spaces["personal"].house_review = False
        other = self.card()
        house.launch(self.cfg, self.board, other)
        self.assertIsNone(self.fake.starts[1].get("agents"))

    def test_a_resume_carries_it_too(self):
        card_id = self.card()
        house.launch(self.cfg, self.board, card_id)
        house.resume(self.cfg, self.board, card_id)
        self.assertIn(agents.VERIFIER, self.fake.resumes[0]["agents"])

    def test_a_resume_after_his_send_back_gives_the_reviewer_his_words(self):
        """RQ-1 (c-512): his send-back redirected the card, and the reviewer went on judging
        it against the brief it was filed with; now the requirements carry what he said."""
        card_id = self.card()
        house.launch(self.cfg, self.board, card_id)
        self.board.note(card_id, "He sent the outcome back from the outcome page of " + card_id
                        + ". His notes (1): fix the thing ourselves and raise a pull request.", "human")
        self.board.note(card_id, "a note of the house's own", "house")
        house.resume(self.cfg, self.board, card_id)
        requirements = (self.cfg.card_dir(card_id) / gate.REQUIREMENTS_FILE).read_text()
        self.assertIn("make the thing", requirements)
        self.assertIn("What the user has said since", requirements)
        self.assertIn("fix the thing ourselves and raise a pull request", requirements)
        self.assertNotIn("a note of the house's own", requirements)

    def test_a_sent_back_round_is_read_as_it_is_written_now_and_as_boards_recorded_it(self):
        """c-699: the note a sent-back round leaves opens "The user sent the"; a board holds
        older ones that open "He sent the", and the reviewer is given both."""
        from keel import planstate
        now = planstate.compose({}, {"comments": []}, "sendback", "c-1", "outcome")
        events = [{"kind": "note", "actor": "human", "at": "2026-10-08T00:00:00", "text": text}
                  for text in (now, "He sent the plan back from the plan page of c-1.")]
        self.assertEqual([words for _, words in gate.his_words(events)],
                         [now, "He sent the plan back from the plan page of c-1."])


class SettingsTest(ReviewCase):
    def test_the_stamp_hooks_and_their_denies_are_in_the_settings(self):
        card_id = self.card()
        house.launch(self.cfg, self.board, card_id)
        settings = json.loads((self.cfg.card_dir(card_id) / "settings.json").read_text())
        groups = settings["hooks"]["SubagentStop"]
        self.assertEqual({g["matcher"] for g in groups}, {agents.REVIEWER, agents.VERIFIER})
        for group in groups:
            self.assertIn(stamp.STAMP_SCRIPT, group["hooks"][0]["command"])
        deny = settings["permissions"]["deny"]
        self.assertIn(f"Write(/{stamp.stamp_path(self.cfg, card_id)})", deny)
        self.assertIn(f"Edit(/{self.cfg.card_dir(card_id) / stamp.FINDINGS_FILE})", deny)
        self.assertEqual(self.board.get(card_id)["options"][gate.SESSION_OPTION], SESSION)

    def test_a_card_the_review_does_not_apply_to_has_neither(self):
        self.cfg.spaces["personal"].house_review = False
        card_id = self.card()
        house.launch(self.cfg, self.board, card_id)
        settings = json.loads((self.cfg.card_dir(card_id) / "settings.json").read_text())
        self.assertNotIn("SubagentStop", settings["hooks"])
        self.assertNotIn(gate.SESSION_OPTION, self.board.get(card_id)["options"])


class StopHookCase(ReviewCase):
    """A card at review with a commit in its worktree, and the two hooks it meets there.
    Its tests are `StopHookTest`'s, so a case built on this one runs only its own."""

    def at_review(self, repo="keel") -> tuple[str, Path]:
        card_id = self.card(repo=repo)
        worktree = self.cfg.worktrees_dir / card_id
        self.cfg.worktrees_dir.mkdir(parents=True, exist_ok=True)
        sh(self.repo, "git", "worktree", "add", "-q", "-b", f"keel/{card_id}", str(worktree))
        (worktree / "thing.txt").write_text("the thing\n")
        sh(worktree, *GIT, "add", "thing.txt")
        sh(worktree, *GIT, "commit", "-q", "-m", "make the thing")
        self.board.stage(card_id, "building", "drain")
        self.board.set_session(card_id, SESSION, "drain", bg_id=SESSION[:8])
        self.board.set_fields(card_id, {"options": {gate.SESSION_OPTION: SESSION}}, "drain")
        self.board.stage(card_id, "review", "house", plan_ref="p.md", output_ref="b @ 1")
        return card_id, worktree

    def stop(self, card_id, worktree):
        return ending.check(self.cfg, self.board, card_id, {"cwd": str(worktree)})

    def finished(self, card_id, worktree, agent, said):
        """What the SubagentStop hook does when one of Keel's agents finishes here."""
        return stamp.stamp(self.cfg, card_id, {
            "hook_event_name": "SubagentStop", "agent_type": agent, "cwd": str(worktree),
            "session_id": SESSION, "last_assistant_message": said})


class StopHookTest(StopHookCase):
    """The mechanism: a Stop at review with no complete review of HEAD sends it back."""

    def test_no_review_is_refused_and_the_card_goes_back_to_building(self):
        card_id, worktree = self.at_review()
        decision = self.stop(card_id, worktree)
        self.assertEqual(decision["decision"], "block")
        self.assertIn(agents.REVIEWER, decision["reason"])
        self.assertEqual(self.board.get(card_id)["stage"], "building")

    def test_a_turn_that_answered_his_ask_at_the_gate_is_never_sent_back(self):
        """c-600 (the e2e run's bug 4): his Ask at the outcome gate is a tell or a resume, a
        new turn; its Stop is not the turn that staged review, so the stamp does not hold it."""
        card_id, worktree = self.at_review()
        self.board.record_resume(card_id, "human", "his question", {"session_id": SESSION, "bg_id": SESSION[:8]})
        held = lambda: gate.check(self.cfg, self.board, self.board.get(card_id), {"cwd": str(worktree)})
        self.assertIsNone(held())
        self.assertEqual(self.board.get(card_id)["stage"], "review")
        self.board.stage(card_id, "building", "human")
        self.board.stage(card_id, "review", "house", plan_ref="p.md", output_ref="b @ 1")
        self.assertEqual(held()["decision"], "block", "a turn that staged review is held")

    def test_a_clean_review_lets_the_card_stay_at_review(self):
        card_id, worktree = self.at_review()
        self.finished(card_id, worktree, agents.REVIEWER, answer([]))
        decision = self.stop(card_id, worktree) or {}
        self.assertNotIn(agents.REVIEWER, decision.get("reason", ""))
        self.assertEqual(self.board.get(card_id)["stage"], "review")

    def test_the_stamp_records_the_house_s_run_at_the_head_it_names(self):
        """c-544: which suite the house ran, targeted or full, travels on the stamp and
        review.md; a run at another head, or on a dirty tree, is not this change's."""
        card_id, worktree = self.at_review()
        testrun.record(worktree, testrun.TARGETED, "3 test module(s)", 0, modules=3)
        self.finished(card_id, worktree, agents.REVIEWER, answer([]))
        stamped = stamp.read_stamp(self.cfg, card_id)
        self.assertEqual((stamped["tests"]["kind"], stamped["tests"]["exit"]), (testrun.TARGETED, 0))
        self.assertEqual(stamped["tests"]["head"], stamped["head"])
        self.assertIn("targeted, 3 test module(s), green",
                      (self.cfg.card_dir(card_id) / stamp.REVIEW_FILE).read_text())
        (worktree / "thing.txt").write_text("a dirty thing\n")
        testrun.record(worktree, testrun.FULL, "make test", 0)
        sh(worktree, "git", "checkout", "--", "thing.txt")
        self.finished(card_id, worktree, agents.REVIEWER, answer([]))
        self.assertEqual(stamp.read_stamp(self.cfg, card_id)["tests"]["kind"], "none",
                         "a run on a dirty tree at the same head is not this change's")
        (worktree / "thing.txt").write_text("a later thing\n")
        testrun.record(worktree, testrun.FULL, "make test", 0)
        sh(worktree, *GIT, "commit", "-q", "-am", "after the run")
        self.finished(card_id, worktree, agents.REVIEWER, answer([]))
        self.assertEqual(stamp.read_stamp(self.cfg, card_id)["tests"]["kind"], "none")
        self.assertIn(testrun.NONE_SAID, (self.cfg.card_dir(card_id) / stamp.REVIEW_FILE).read_text())

    def test_findings_need_the_verifier_before_the_round_counts(self):
        card_id, worktree = self.at_review()
        self.finished(card_id, worktree, agents.REVIEWER, answer([HIGH]))
        self.assertFalse(stamp.stamp_path(self.cfg, card_id).exists())
        self.assertEqual(self.stop(card_id, worktree)["decision"], "block")
        self.board.stage(card_id, "review", "house", plan_ref="p.md", output_ref="b @ 1")
        self.finished(card_id, worktree, agents.VERIFIER,
                      answer([{"id": "r1.F1", "verify": "refuted", "reason": "made elsewhere",
                               "evidence": "thing.txt:1 is the thing"}]))
        rounds = stamp.read_rounds(self.cfg.card_dir(card_id))
        self.assertEqual(rounds[-1]["findings"][0]["verify"], "disputed")
        self.assertIn("r1.F1", (self.cfg.card_dir(card_id) / stamp.REVIEW_FILE).read_text())
        self.assertNotIn(agents.REVIEWER, (self.stop(card_id, worktree) or {}).get("reason", ""))
        self.assertEqual(self.board.get(card_id)["stage"], "review")

    def test_an_answer_outside_the_schema_counts_for_nothing(self):
        card_id, worktree = self.at_review()
        self.finished(card_id, worktree, agents.REVIEWER, "Looks fine to me.")
        self.assertFalse(stamp.stamp_path(self.cfg, card_id).exists())
        self.assertIn("not the finding schema", (self.cfg.card_dir(card_id) / stamp.REVIEW_FILE).read_text())

    def test_a_review_of_an_older_head_is_refused(self):
        card_id, worktree = self.at_review()
        self.finished(card_id, worktree, agents.REVIEWER, answer([]))
        (worktree / "thing.txt").write_text("a different thing\n")
        sh(worktree, *GIT, "commit", "-q", "-am", "after the review")
        self.assertEqual(self.stop(card_id, worktree)["decision"], "block")

    def test_the_same_change_rebased_onto_a_newer_base_needs_no_second_review(self):
        card_id, worktree = self.at_review()
        prep.prepare(self.cfg.card_dir(card_id), "main", [worktree])
        self.finished(card_id, worktree, agents.REVIEWER, answer([]))
        (self.repo / "other.txt").write_text("someone else's work\n")
        sh(self.repo, *GIT, "add", "other.txt")
        sh(self.repo, *GIT, "commit", "-q", "-m", "main moves on")
        sh(worktree, *GIT, "rebase", "-q", "main")
        self.assertNotIn(agents.REVIEWER, (self.stop(card_id, worktree) or {}).get("reason", ""))
        self.assertEqual(self.board.get(card_id)["stage"], "review")

    def test_a_review_md_the_house_wrote_proves_nothing(self):
        card_id, worktree = self.at_review()
        (self.cfg.card_dir(card_id) / stamp.REVIEW_FILE).write_text(
            f"HEAD: {sh(worktree, 'git', 'rev-parse', 'HEAD')}\n\nall good\n")
        self.assertEqual(self.stop(card_id, worktree)["decision"], "block")

    def test_a_house_started_before_the_reviewer_is_never_held_to_it(self):
        card_id, worktree = self.at_review()
        self.board.set_fields(card_id, {"options": {gate.SESSION_OPTION: None}}, "drain")
        decision = self.stop(card_id, worktree) or {}
        self.assertNotIn(agents.REVIEWER, decision.get("reason", ""))
        self.assertEqual(self.board.get(card_id)["stage"], "review")

    def test_only_keel_s_agents_finishing_write_anything(self):
        card_id, worktree = self.at_review()
        self.assertIsNone(self.finished(card_id, worktree, "Explore", answer([])))
        self.assertFalse(stamp.stamp_path(self.cfg, card_id).exists())

    def test_the_third_refusal_blocks_the_card_for_him(self):
        card_id, worktree = self.at_review()
        for _ in range(self.cfg.review_asks):
            self.stop(card_id, worktree)
            self.board.stage(card_id, "review", "house", plan_ref="p.md", output_ref="b @ 1")
        self.assertIsNone(self.stop(card_id, worktree))
        card = self.board.get(card_id)
        self.assertIn(agents.REVIEWER, card["blocked_reason"])
        self.assertEqual(card["stage"], "review")

    def test_review_asks_is_how_many_refusals_come_before_the_block(self):
        """`[keel] review_asks` (c-633): one ask, then the block."""
        self.cfg.review_asks = 1
        card_id, worktree = self.at_review()
        self.assertEqual((self.stop(card_id, worktree) or {}).get("decision"), "block")
        self.board.stage(card_id, "review", "house", plan_ref="p.md", output_ref="b @ 1")
        self.assertIsNone(self.stop(card_id, worktree))
        self.assertIn("after 1 asks", self.board.get(card_id)["blocked_reason"])

    def test_a_space_with_it_off_is_not_checked(self):
        card_id, worktree = self.at_review()
        self.cfg.spaces["personal"].house_review = False
        decision = self.stop(card_id, worktree) or {}
        self.assertNotIn(agents.REVIEWER, decision.get("reason", ""))
        self.assertEqual(self.board.get(card_id)["options"].get(gate.ASKED_OPTION), None)


class PreshipFirstSequenceTest(StopHookCase):
    """c-597, the work order at the level Keel can run it: fetch and rebase, the docs commit,
    the push, THEN the review. The stamp taken after them stays good through the push and a
    later clean rebase with its force push, so the Stop hook never sends the card back. The
    old order (review, then a docs commit) is what bounced."""

    def origin(self) -> Path:
        bare = self.dir / "origin.git"
        sh(self.dir, "git", "init", "-q", "--bare", "-b", "main", str(bare))
        sh(self.repo, "git", "remote", "add", "origin", str(bare))
        sh(self.repo, "git", "push", "-q", "origin", "main")
        return bare

    def main_moves(self, name):
        (self.repo / name).write_text("someone else's work\n")
        sh(self.repo, *GIT, "add", name)
        sh(self.repo, *GIT, "commit", "-q", "-m", f"main moves on: {name}")
        sh(self.repo, "git", "push", "-q", "origin", "main")

    def on_origin(self, worktree, branch) -> str:
        return sh(worktree, "git", "ls-remote", "origin", f"refs/heads/{branch}").split()[0]

    def test_a_stamp_after_preship_holds_through_the_push_and_a_clean_rebase(self):
        card_id, worktree = self.at_review()
        branch = f"keel/{card_id}"
        self.origin()
        self.main_moves("other.txt")
        sh(worktree, "git", "fetch", "-q", "origin")
        sh(worktree, *GIT, "rebase", "-q", "origin/main")
        (worktree / "docs.md").write_text("the thing's endpoint, documented\n")
        sh(worktree, *GIT, "add", "docs.md")
        sh(worktree, *GIT, "commit", "-q", "-m", "docs and swagger")
        sh(worktree, "git", "push", "-q", "-u", "origin", branch)
        head = sh(worktree, "git", "rev-parse", "HEAD")
        self.assertEqual(self.on_origin(worktree, branch), head, "the draft's branch is the head reviewed")
        prep.prepare(self.cfg.card_dir(card_id), "main", [worktree])
        self.finished(card_id, worktree, agents.REVIEWER, answer([]))
        self.assertNotIn(agents.REVIEWER, (self.stop(card_id, worktree) or {}).get("reason", ""))
        self.assertEqual(self.board.get(card_id)["stage"], "review")
        # the base moves during the review: a clean rebase and a force push keep the stamp
        self.main_moves("more.txt")
        sh(worktree, "git", "fetch", "-q", "origin")
        sh(worktree, *GIT, "rebase", "-q", "origin/main")
        sh(worktree, "git", "push", "-q", "--force-with-lease", "origin", branch)
        self.assertEqual(self.on_origin(worktree, branch), sh(worktree, "git", "rev-parse", "HEAD"))
        self.assertNotIn(agents.REVIEWER, (self.stop(card_id, worktree) or {}).get("reason", ""))
        self.assertEqual(self.board.get(card_id)["stage"], "review")

    def test_a_docs_commit_after_the_review_is_what_bounced(self):
        card_id, worktree = self.at_review()
        prep.prepare(self.cfg.card_dir(card_id), "main", [worktree])
        self.finished(card_id, worktree, agents.REVIEWER, answer([]))
        (worktree / "docs.md").write_text("documented after the review\n")
        sh(worktree, *GIT, "add", "docs.md")
        sh(worktree, *GIT, "commit", "-q", "-m", "docs and swagger, late")
        self.assertEqual(self.stop(card_id, worktree)["decision"], "block")
        self.assertEqual(self.board.get(card_id)["stage"], "building")


class PrepTest(ReviewCase):
    def test_prep_writes_the_diff_per_repo_and_the_standards_of_touched_repos_only(self):
        wt = self.dir / "wt"
        sh(self.repo, "git", "worktree", "add", "-q", "-b", "feature", str(wt))
        (wt / "CLAUDE.md").write_text("# R\n\n## Coding Standards\n\n- Short functions.\n")
        sh(wt, *GIT, "add", "CLAUDE.md")
        sh(wt, *GIT, "commit", "-q", "-m", "rules")
        quiet = make_repo(self.dir / "quiet")
        (quiet / "CLAUDE.md").write_text("# Q\n\n## Coding Standards\n\n- Untouched rule.\n")
        card_dir = self.dir / "card"
        card_dir.mkdir()
        done = prep.prepare(card_dir, "main", [wt, quiet])
        diff = (card_dir / prep.DIFF_FILE).read_text()
        self.assertIn("# repo: repo", diff)
        self.assertIn("diff --git a/CLAUDE.md", diff)
        text = (card_dir / prep.STANDARDS_FILE).read_text()
        self.assertIn("Short functions", text)
        self.assertNotIn("Untouched rule", text)
        self.assertEqual(done["touched"], ["repo"])

    def test_a_worktree_with_a_base_of_its_own_is_read_against_it(self):     # c-772
        wt = self.dir / "wt"
        sh(self.repo, "git", "worktree", "add", "-q", "-b", "feature", str(wt))
        sh(self.repo, "git", "branch", "parent")
        other = make_repo(self.dir / "other")
        card_dir = self.dir / "card"
        with self.assertRaises(prep.PrepError):          # the other repo has no such branch
            prep.prepare(card_dir, "parent", [wt, other])
        prep.prepare(card_dir, "parent", [wt, other], bases={other: "main"})
        seen = json.loads((card_dir / stamp.PREP_FILE).read_text())["worktrees"]
        self.assertEqual([one["base"] for one in seen], ["parent", "main"])
        (card_dir / stamp.PREP_FILE).unlink()               # and as the house types it
        with contextlib.redirect_stdout(io.StringIO()):
            done = prep.main(["prep", "--dir", str(card_dir), "--base", "parent", "--worktree", str(wt),
                              "--worktree", str(other), "--worktree-base", str(other), "main"])
        self.assertEqual(done, 0)
        seen = json.loads((card_dir / stamp.PREP_FILE).read_text())["worktrees"]
        self.assertEqual([one["base"] for one in seen], ["parent", "main"])

    def test_an_answer_is_recorded_and_rendered(self):
        card_dir = self.dir / "card"
        card_dir.mkdir()
        stamp.save_rounds(card_dir, [{"round": 1, "head": "abc", "complete": True, "findings": [
            dict(HIGH, id="r1.F1", verify="kept", verify_reason="holds", verify_evidence="",
                 public_comment=None)]}])
        prep.answer(card_dir, "r1.F1", "declined", "the plan says so")
        self.assertIn("declined, the plan says so", (card_dir / stamp.REVIEW_FILE).read_text())
        with self.assertRaises(prep.PrepError):
            prep.answer(card_dir, "r1.F9", "fixed", "")


class StandaloneTest(ReviewCase):
    """HP-4: outside Keel (the standalone skill) there is no `--agents` and no hook, so the
    same prompts and the same recording are commands."""


    def test_record_applies_the_schema_and_the_rules_without_a_hook(self):
        card_dir = self.dir / "scratch-review"
        said = self.dir / "answer.txt"
        said.write_text(answer([HIGH]))
        import contextlib, io
        quiet = contextlib.redirect_stdout(io.StringIO())
        quiet.__enter__()
        self.addCleanup(quiet.__exit__, None, None, None)
        self.assertEqual(prep.main(["record", "--dir", str(card_dir), "--agent", "reviewer",
                                    "--answer-file", str(said), "--worktree", str(self.repo)]), 0)
        said.write_text(answer([{"id": "r1.F1", "verify": "refuted", "reason": "no"}]))
        self.assertEqual(prep.main(["record", "--dir", str(card_dir), "--agent", "verifier",
                                    "--answer-file", str(said), "--worktree", str(self.repo)]), 0)
        found = stamp.read_rounds(card_dir)[-1]["findings"][0]
        self.assertEqual(found["verify"], "unverified")      # refuted without evidence: kept



if __name__ == "__main__":
    unittest.main()
