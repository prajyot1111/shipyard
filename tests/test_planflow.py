"""The gate verbs in `actions`: approve and send back carry the human's answer to the
house, a send back with `stay` opens a discussion on the surface, and `end_discussion`
ends the lavish session rather than the house."""

import json
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from keel import actions, artifacts, cli
from keel.board import Board
from tests.helpers import SESSION, make_config, own_options

RESUMED = {"bg_id": SESSION[:8], "session_id": SESSION}


class GateCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name)
        self.cfg = make_config(self.dir)
        self.board = Board(self.cfg.db_path)
        self.addCleanup(self.tmp.cleanup)
        self.addCleanup(self.board.close)
        self.calls = []
        self.lavish = subprocess.CompletedProcess(["lavish-axi"], 0, stdout="session ended\n", stderr="")
        patch = mock.patch.object(actions.subprocess, "run", side_effect=self.fake_run)
        patch.start()
        self.addCleanup(patch.stop)
        self.resume = mock.patch.object(actions.house, "resume", return_value=dict(RESUMED)).start()
        self.addCleanup(mock.patch.stopall)

    def fake_run(self, argv, **kwargs):
        self.calls.append(list(argv))
        if argv[0] == artifacts.LAVISH:
            if isinstance(self.lavish, BaseException):
                raise self.lavish
            return self.lavish
        return subprocess.CompletedProcess(argv, 0, stdout=json.dumps({"ok": True}), stderr="")

    def act(self, **body):
        return actions.act(self.cfg, self.board, body)

    def kb_calls(self) -> list[list[str]]:
        return [argv[1:-1] for argv in self.calls if argv[0].endswith("/kb")]

    def prompt_given(self) -> str:
        return self.resume.call_args.kwargs["prompt"]

    def plan_gate(self, plan="plan.html", session=SESSION) -> str:
        card_id = self.board.create("personal", "a planned card", repo="keel", autonomy="attended")
        self.board.stage(card_id, "assigned", "human")
        self.board.stage(card_id, "planning", "drain", plan_ref=str(self.cfg.card_dir(card_id) / plan)
                         if plan else None)
        if session:
            self.board.set_session(card_id, session, "drain", bg_id=session[:8])
        return card_id

    def outcome_gate(self) -> str:
        card_id = self.board.create("personal", "a finished card", repo="keel")
        self.board.stage(card_id, "assigned", "human")
        self.board.stage(card_id, "building", "drain")
        self.board.set_session(card_id, SESSION, "drain", bg_id=SESSION[:8])
        self.board.stage(card_id, "review", "house", plan_ref="p.md", output_ref="o.md")
        return card_id


class ApproveTest(GateCase):
    def test_approving_a_surface_plan_resumes_the_house_to_collect_then_build(self):
        card_id = self.plan_gate()
        result = self.act(verb="approve", id=card_id, gate="plan")
        self.assertEqual(self.kb_calls()[0], ["approve", card_id, "plan"])
        self.resume.assert_called_once()
        self.assertEqual(self.resume.call_args.args[2], card_id)
        prompt = self.prompt_given()
        self.assertIn("timeout 20 lavish-axi poll", prompt)
        self.assertIn("approved", prompt)
        self.assertEqual(result["resumed"], RESUMED)
        self.assertEqual(result["prompt"], prompt)
        self.assertEqual(result["card"]["id"], card_id)


    def test_the_outcome_gate_is_the_plain_kb_verb(self):
        result = self.act(verb="approve", id=self.outcome_gate(), gate="outcome")
        self.assertEqual(result, {"ok": True})
        self.resume.assert_not_called()

    def test_a_card_with_no_house_is_approved_anyway_and_says_it_was_not_resumed(self):
        result = self.act(verb="approve", id=self.plan_gate(session=None), gate="plan")
        self.assertIsNone(result["resumed"])
        self.assertIn("no house session", result["note"])
        self.resume.assert_not_called()


class ApproveSaidTest(GateCase):
    """What he typed beside an Approve: one note on the card through `kb`, then the resume."""

    def test_the_kb_half_records_it_and_the_prompt_carries_it(self):
        card_id = self.plan_gate(plan="plan.md")
        self.act(verb="approve", id=card_id, gate="plan", said="question one: option two")
        self.assertEqual(self.kb_calls(), [["approve", card_id, "plan",
                                            "--said=question one: option two"]])
        prompt = self.prompt_given()
        self.assertIn("> question one: option two", prompt)
        self.assertIn("the user's answers", prompt)

    def test_the_note_is_written_before_the_house_is_resumed(self):
        """`kb approve --said` is one call and it is the call that moves the card, so what
        he said is on the record before anything is resumed to read it."""
        card_id = self.plan_gate(plan="plan.md")
        order = []
        self.resume.side_effect = lambda *a, **k: (order.append("resume"), dict(RESUMED))[1]
        original = actions.run_kb

        def watched(cfg, argv, **kwargs):
            order.append(argv[0])
            return original(cfg, argv, **kwargs)

        with mock.patch.object(actions, "run_kb", watched):
            self.act(verb="approve", id=card_id, gate="plan", said="go with two")
        self.assertEqual(order, ["approve", "resume"])


    def test_words_that_open_with_a_dash_reach_kb_as_his_words_and_not_as_a_flag(self):
        """A list of answers opens with a dash. As a separate argument argparse reads that
        as an unknown flag and the approve fails; as one `--said=` argument it parses."""
        argv = actions.approve_argv({"id": "c-001", "gate": "plan", "said": "-yes\n- and two"})
        args = cli.build_parser().parse_args(argv)
        self.assertEqual(args.said, "-yes\n- and two")

    def test_the_outcome_gate_records_it_and_resumes_nothing(self):
        """Approve outcome publishes and ends the house, so there is no house to hand his
        words to: they are recorded on the card and that is all."""
        card_id = self.outcome_gate()
        self.act(verb="approve", id=card_id, gate="outcome", said="merged, follow up on the index")
        self.assertEqual(self.kb_calls(), [["approve", card_id, "outcome",
                                            "--said=merged, follow up on the index"]])
        self.resume.assert_not_called()


class SendBackTest(GateCase):
    def test_a_plan_sent_back_notes_the_reason_and_resumes_with_it(self):
        card_id = self.plan_gate()
        result = self.act(verb="sendback", id=card_id, reason="option two is cheaper")
        self.assertEqual(self.kb_calls(), [["note", card_id, "option two is cheaper"]])
        prompt = self.prompt_given()
        self.assertIn("> option two is cheaper", prompt)
        self.assertIn("lavish-axi poll", prompt)
        card = self.board.get(card_id)
        self.assertEqual((card["stage"], card["derived"]["plan_gate"]), ("planning", True))
        self.assertEqual(own_options(card), {})
        self.assertEqual((result["gate"], result["stay"]), ("plan", False))

    def test_an_outcome_sent_back_stages_building_again(self):
        card_id = self.outcome_gate()
        self.act(verb="sendback", id=card_id, reason="the test passes without the fix")
        self.assertEqual(self.kb_calls(), [["note", card_id, "the test passes without the fix"],
                                           ["stage", card_id, "building", "--note",
                                            "sent back from the deck"]])
        self.assertIn("kb stage $KEEL_CARD review --output", self.prompt_given())

    def test_a_card_at_no_gate_is_refused(self):
        card_id = self.board.create("personal", "in the inbox")
        with self.assertRaises(actions.ActionError) as caught:
            self.act(verb="sendback", id=card_id, reason="why")
        self.assertIn("no gate open", str(caught.exception))
        with self.assertRaises(actions.ActionError):
            self.act(verb="sendback", id=self.plan_gate())


class DiscussionTest(GateCase):
    def test_stay_marks_the_card_talking_and_hands_the_house_the_loop(self):
        card_id = self.plan_gate()
        self.cfg.discussion_idle_seconds = 900
        result = self.act(verb="sendback", id=card_id, reason="walk me through it", stay=True)
        self.assertEqual(self.kb_calls(), [["note", card_id, "walk me through it"],
                                           ["set", card_id, "options.discussion=true"]])
        prompt = self.prompt_given()
        self.assertIn("timeout 900 lavish-axi poll", prompt)
        self.assertIn("--agent-reply", prompt)
        self.assertIn("stays at planning", prompt)
        self.assertTrue(result["stay"])
        card = self.board.get(card_id)
        self.assertEqual((card["stage"], card["derived"]["plan_gate"]), ("planning", True))

    def test_a_discussion_needs_a_surface_and_a_plan_gate(self):
        with self.assertRaises(actions.ActionError) as caught:
            self.act(verb="sendback", id=self.plan_gate(plan="plan.md"), reason="talk", stay=True)
        self.assertIn("needs a lavish surface", str(caught.exception))
        with self.assertRaises(actions.ActionError) as caught:
            self.act(verb="sendback", id=self.outcome_gate(), reason="talk", stay=True)
        self.assertIn("outcome gate", str(caught.exception))
        self.assertEqual(self.kb_calls(), [], "a refused discussion writes nothing to the card")

    def test_end_discussion_ends_the_lavish_session_and_never_the_house(self):
        card_id = self.plan_gate()
        plan = self.board.get(card_id)["plan_ref"]
        result = self.act(verb="end_discussion", id=card_id)
        self.assertEqual(self.calls[0], [artifacts.LAVISH, "end", plan])
        self.assertEqual(self.kb_calls(), [["note", card_id, "discussion ended from the deck"]])
        self.assertEqual(result["ended"], plan)
        self.assertNotIn("stop", json.dumps(result).lower())
        self.assertFalse(any("stop" in " ".join(argv) for argv in self.calls))

    def test_an_unreachable_lavish_is_reported_honestly(self):
        card_id = self.plan_gate()
        self.lavish = FileNotFoundError("no lavish-axi on PATH")
        with self.assertRaises(actions.ActionError) as caught:
            self.act(verb="end_discussion", id=card_id)
        self.assertIn("lavish is not reachable", str(caught.exception))
        self.assertIn("nothing was ended", str(caught.exception))
        self.lavish = subprocess.CompletedProcess([], 1, stdout="", stderr="no session for that file\n")
        with self.assertRaises(actions.ActionError) as caught:
            self.act(verb="end_discussion", id=card_id)
        self.assertIn("no session for that file", str(caught.exception))
        self.assertEqual(self.kb_calls(), [], "nothing is noted when the session did not end")


if __name__ == "__main__":
    unittest.main()


class MergeConflictTest(unittest.TestCase):
    """An outcome approve whose merge conflicts because main moved sends the house to merge."""

    def test_conflict_unblocks_stages_building_and_resumes_with_the_merge_prompt(self):
        from keel import actions
        calls = []
        def fake_kb(cfg, argv, timeout=0):
            calls.append(argv)
            if argv[0] == "approve":
                raise actions.ActionError("c-9 not merged, card blocked: merge conflict: main moved past keel/c-9-x and the two disagree; the house has to merge main into its branch first")
            return {"id": "c-9"}
        card = {"id": "c-9", "space": "personal", "stage": "review", "plan_ref": None, "session_id": "s"}
        class FakeBoard:
            def get(self, cid): return card
        with mock.patch.object(actions, "run_kb", fake_kb), \
             mock.patch.object(actions, "card_or_none", lambda board, body: card), \
             mock.patch.object(actions, "resume_with", lambda cfg, board, cid, prompt: {"prompt": prompt}):
            here = mock.Mock(host="mac")
            result = actions.act_approve(here, FakeBoard(), {"verb": "approve", "id": "c-9", "gate": "outcome"})
        self.assertTrue(result["merge_conflict"])
        self.assertEqual(result["target"], "main", "the deck says which branch moved (c-665)")
        self.assertEqual([c[0] for c in calls], ["approve", "unblock", "stage", "set"])
        self.assertEqual(calls[3], ["set", "c-9", "options.merging=true"])
        self.assertIn("git merge main", result["prompt"])
        self.assertIn("keel/c-9-x", result["prompt"])

    def test_a_conflict_on_a_card_bosun_builds_resumes_no_house(self):
        """c-647: the card goes back to building for Bosun, whatever session it carries."""
        from keel import actions
        calls, resumed = [], []
        def fake_kb(cfg, argv, timeout=0):
            calls.append(argv)
            if argv[0] == "approve":
                raise actions.ActionError("c-9 not merged, card blocked: merge conflict: next moved past refs/builder/bosun/c-9-x and the two disagree; the house has to merge next into its branch first")
            return {"id": "c-9"}
        card = {"id": "c-9", "space": "personal", "stage": "review", "plan_ref": None, "session_id": "s",
                "derived": {"bosun": True}}
        class FakeBoard:
            def get(self, cid): return card
        told = []
        with mock.patch.object(actions, "run_kb", fake_kb), \
             mock.patch.object(actions, "card_or_none", lambda board, body: card), \
             mock.patch.object(actions, "resume_with", lambda *a, **k: resumed.append(a)), \
             mock.patch.object(actions.pausewake, "tell", lambda board, cid, what, **kw: told.append((cid, what))):
            here = mock.Mock(host="mac")
            result = actions.act_approve(here, FakeBoard(), {"verb": "approve", "id": "c-9", "gate": "outcome"})
        self.assertEqual(([c[0] for c in calls], resumed), (["approve", "unblock", "stage"], []))
        self.assertEqual(told, [("c-9", "outcome")], "c-734: Bosun is told of the tap")
        self.assertEqual((result["merge_conflict"], result["bosun"], result["target"], result["resumed"]),
                         (True, True, "next", None))
        self.assertIn("waiting for Bosun to merge next into bosun/c-9-x", calls[2][calls[2].index("--note") + 1])

    def test_a_conflict_on_bosun_s_card_on_a_real_board_goes_back_to_building_for_bosun(self):
        """c-647: `actions.merge_conflict` on a real board, `kb` routed to it as below."""
        import tempfile
        from pathlib import Path
        from keel import actions, authority
        from keel.board import Board
        from tests.helpers import make_config
        resumed = []
        with tempfile.TemporaryDirectory() as tmp, Board(make_config(Path(tmp)).db_path,
                                                         switches={authority.BUILDER}, builds=["keel"]) as board:
            cid = board.create("personal", "a card", repo="keel", actor="human", stage="review")
            board.set_session(cid, SESSION, "drain", bg_id=SESSION[:8])      # a house's leftover
            board.block(cid, "outcome not merged: merge conflict", "human")
            self.assertTrue(board.get(cid)["derived"]["bosun"])

            def fake_kb(cfg, argv, timeout=0):
                if argv[0] == "approve":
                    raise actions.ActionError(
                        f"{cid} not merged, card blocked: merge conflict: next moved past "
                        f"refs/builder/bosun/c-9-x and the two disagree; the house has to merge next "
                        f"into its branch first")
                if argv[0] == "unblock":
                    return board.unblock(cid, "human")
                if argv[0] == "stage":
                    return board.stage(cid, argv[2], "human", note=argv[argv.index("--note") + 1])
                raise AssertionError(f"kb {argv[0]} is not for a card Bosun builds")
            with mock.patch.object(actions, "run_kb", fake_kb), \
                 mock.patch.object(actions, "resume_with", lambda *a, **k: resumed.append(a)):
                here = mock.Mock(host="mac")
                result = actions.act_approve(here, board, {"verb": "approve", "id": cid, "gate": "outcome"})
            card = board.get(cid)
            moved = [e["text"] for e in board.events(cid) if e["kind"] == "stage"][-1]
        self.assertEqual((card["stage"], card["blocked_reason"], resumed), ("building", None, []))
        self.assertNotIn("merging", card["options"])
        self.assertEqual(moved, "next moved past bosun/c-9-x and the two disagree, so nothing was merged; "
                                "waiting for Bosun to merge next into bosun/c-9-x and stage review again. "
                                "No house was resumed")
        self.assertEqual((result["bosun"], result["resumed"], result["card"]["stage"]), (True, None, "building"))

    def test_a_conflict_that_names_no_branch_guesses_none(self):
        """c-665 review: the house, the note and the card are told "its target branch", never
        a literal `main` the refusal did not say. Read back from a real board."""
        import tempfile
        from pathlib import Path
        from keel import actions, cli
        from keel.board import Board
        from tests.helpers import make_config
        with tempfile.TemporaryDirectory() as tmp, Board(make_config(Path(tmp)).db_path) as board:
            cid = board.create("personal", "a card", actor="human", stage="review")
            board.block(cid, "outcome not merged: merge conflict", "human")

            def fake_kb(cfg, argv, timeout=0):
                if argv[0] == "approve":
                    raise actions.ActionError(f"{cid} not merged, card blocked: merge conflict")
                if argv[0] == "unblock":
                    return board.unblock(cid, "human")
                if argv[0] == "stage":
                    return board.stage(cid, argv[2], "human", note=argv[argv.index("--note") + 1])
                name, value = cli.parse_assignment(argv[2])
                return board.set_fields(cid, {"options": {name.removeprefix("options."): value}}, "human")
            with mock.patch.object(actions, "run_kb", fake_kb), \
                 mock.patch.object(actions, "resume_with", lambda cfg, board, cid, prompt: {"prompt": prompt}):
                here = mock.Mock(host="mac")
                result = actions.act_approve(here, board, {"verb": "approve", "id": cid, "gate": "outcome"})
            card = board.get(cid)
            notes = " ".join(event.get("text") or "" for event in board.events(cid))
        self.assertIsNone(result["target"])
        self.assertEqual((card["stage"], card["blocked_reason"]), ("building", None))
        self.assertIs(card["options"]["merging"], True)
        self.assertIn("its target branch moved; the house merges it first", notes)
        self.assertIn("its target branch", result["prompt"])
        self.assertNotRegex(result["prompt"] + notes.replace("merge conflict", ""), r"\bmain\b")

