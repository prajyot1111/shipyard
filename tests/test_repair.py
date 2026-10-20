"""Bosun's repairs of a card's board mechanics, in every space (c-575; `keel/repair.py`).

Each allowed repair is pinned on a card Bosun does not build (a work card, or a personal one
with builder mode off), and each refusal beside it: the fields that say what a card is, a
path to another document, a block that is his, a stage other than the one the board records,
words into a house, and `--why` from anyone but Bosun. Nothing counts repairs (the three
strikes went with driving, c-593). The refusals the brief
names that live elsewhere (a work card's gate, its house's transcript, a relay) are pinned
again here with a `--why` beside them, so no repair reaches them.
"""

import os
import subprocess
from pathlib import Path
from unittest import mock

from keel import config as config_module
from keel import drain, house, landing, prompts, repair, repairhouse
from tests.test_authority import BosunCase

SESSION = "11111111-2222-3333-4444-555555555555"


class RepairCase(BosunCase):
    def work(self, title="w") -> str:
        return self.board().create("work", title, actor="human")

    def card_dir(self, card: str):
        path = self.dir / "state" / "cards" / card
        path.mkdir(parents=True, exist_ok=True)
        return path

    def own_file(self, card: str, name: str = "plan.md"):
        path = self.card_dir(card) / name
        path.write_text("# plan\n")
        return path

    def repaired(self, *argv):
        code, out, err = self.as_bosun(*argv)
        self.assertEqual(code, 0, err)
        return out

    def repairs(self, card: str) -> list[dict]:
        return [e for e in self.board().events(card)
                if e["kind"] == "intervene" and (e.get("data") or {}).get("what") == "repair"]


class FieldTest(RepairCase):
    def test_a_work_card_s_plan_ref_is_normalised_to_its_own_file(self):
        card = self.work()
        self.board().set_fields(card, {"plan_ref": f"/Users/elsewhere/cards/{card}/plan.md"}, "human")
        path = self.own_file(card)
        self.repaired("set", card, f"plan_ref={path}", "--why", "the path named the other machine")
        self.assertEqual(self.board().get(card)["plan_ref"], str(path))
        (event,) = self.repairs(card)
        self.assertEqual((event["actor"], event["data"]["repair"]), ("bosun", "field"))
        self.assertEqual(event["data"]["why"], "the path named the other machine")

    def test_a_personal_card_s_output_ref_and_an_empty_plan_ref(self):
        card = self.personal()
        board = self.board()
        board.set_fields(card, {"output_ref": "~/gone/report.html"}, "human")
        report = self.own_file(card, "report.html")
        plan = self.own_file(card)
        self.repaired("set", card, f"output_ref={report}", "--why", "moved card dir")
        self.assertEqual(self.board().get(card)["output_ref"], str(report))
        # From none there is nothing to normalise: a plan_ref set from none would open his
        # plan gate and end the house's planning, a move rather than a path (review 4.F3).
        self.board().stage(card, "assigned", "human")
        self.board().stage(card, "planning", "drain")
        self.refused("never swaps the document", "set", card, f"plan_ref={plan}", "--why", "x")
        self.assertIsNone(self.board().get(card)["plan_ref"])

    def test_a_path_repair_at_his_plan_gate_does_not_reopen_it(self):
        card = self.personal()
        board = self.board()
        board.stage(card, "assigned", "human")
        board.stage(card, "planning", "drain", plan_ref=f"/Users/him/cards/{card}/plan.md")
        # The gate opened a day ago, so a repair that reopened it would move gate_since.
        board.conn.execute("UPDATE events SET at = '2026-01-01T00:00:00+00:00' WHERE card = ?", (card,))
        since = board.get(card)["derived"]["gate_since"]
        self.assertTrue(since.startswith("2026-01-01"), since)
        plan = self.own_file(card)
        self.repaired("set", card, f"plan_ref={plan}", "--why", "the other machine's path")
        self.assertEqual(self.board().get(card)["derived"]["gate_since"], since)

    def tree(self, *parts):
        path = self.dir.joinpath(*parts)
        subprocess.run(["git", "init", "-q", str(path)], check=True)
        return path

    def setUp(self):
        super().setUp()
        # A second personal repo, so a card can have two (`tests.test_console.console_toml`).
        path = self.dir / "keel.toml"
        path.write_text(path.read_text().replace('keel = "~/keel"\n', 'keel = "~/keel"\napi = "~/api"\n', 1))

    def checkout(self, key: str):
        """The checkout keel.toml names for a repo key, with one commit, so a worktree can be
        cut from it; a second call finds it there."""
        path = self.dir / "home" / key
        if (path / ".git").exists():
            return path
        subprocess.run(["git", "init", "-q", str(path)], check=True)
        subprocess.run(["git", "-C", str(path), "-c", "user.name=t", "-c", "user.email=t@t",
                        "commit", "-q", "--allow-empty", "-m", "root"], check=True)
        return path

    def linked(self, checkout, *parts):
        """A linked worktree of `checkout` at `parts` under the scratch directory."""
        path = self.dir.joinpath(*parts)
        path.parent.mkdir(parents=True, exist_ok=True)
        subprocess.run(["git", "-C", str(checkout), "worktree", "add", "-q", "--detach", str(path)],
                       check=True)
        return path

    def two_repo(self) -> tuple[str, dict]:
        """A card on keel and api whose trees share one name, as a work card's do (one branch
        slug for every repo, `packs/work/cut.py`)."""
        card = self.board().create("personal", "w", repo="keel,api", actor="human")
        trees = {key: self.linked(self.checkout(key), f"{key}-wt", "feature-x") for key in ("keel", "api")}
        self.board().set_fields(card, {"options": {
            "worktree": "/Users/him/keel-wt/feature-x",
            "worktrees": {"keel": "/Users/him/keel-wt/feature-x", "api": "/Users/him/api-wt/feature-x"}}},
            "human")
        return card, trees

    def test_a_worktree_and_a_worktrees_map_that_exist(self):
        card, trees = self.two_repo()
        self.repaired("set", card, f"options.worktree={trees['keel']}", "--why", "the tree moved")
        self.repaired("set", card, f'options.worktrees={{"keel": "{trees["keel"]}", "api": "{trees["api"]}"}}',
                      "--why", "same")
        options = self.board().get(card)["options"]
        self.assertEqual((options["worktree"], options["worktrees"]),
                         (str(trees["keel"]), {"keel": str(trees["keel"]), "api": str(trees["api"])}))

    def test_a_checkout_itself_belongs_to_its_repo(self):
        card = self.board().create("personal", "w", repo="keel", actor="human")
        checkout = self.checkout("keel")
        self.board().set_fields(card, {"options": {"worktree": f"/Users/him/{checkout.name}"}}, "human")
        self.repaired("set", card, f"options.worktree={checkout}", "--why", "the checkout moved")

    def test_a_worktree_repair_never_picks_another_tree_or_changes_the_repos(self):
        card, trees = self.two_repo()
        mine = trees["keel"]
        another = self.linked(self.checkout("keel"), "trees", "c-999")
        for path in (another, self.checkout("keel")):
            with self.subTest(path=path.name):
                self.refused("never picks another tree", "set", card, f"options.worktree={path}",
                             "--why", "x")
        self.refused("keeps options.worktrees' repos", "set", card,
                     f'options.worktrees={{"keel": "{mine}"}}', "--why", "a repo dropped")
        self.refused("keeps options.worktrees' repos", "set", card,
                     f'options.worktrees={{"keel": "{mine}", "api": "{mine}", "web": "{mine}"}}',
                     "--why", "a repo added")
        bare = self.work("bare")
        self.refused("no recorded tree", "set", bare, f"options.worktree={mine}", "--why", "x")

    def test_two_repos_trees_are_never_swapped(self):
        """Reproduced red before c-585: same keys, same names, both git trees, so it passed."""
        card, trees = self.two_repo()
        self.refused("is not a worktree of", "set", card,
                     f'options.worktrees={{"keel": "{trees["api"]}", "api": "{trees["keel"]}"}}', "--why", "swap")
        self.refused("is not a worktree of", "set", card,
                     f'options.worktrees={{"keel": "{trees["keel"]}", "api": "{trees["keel"]}"}}',
                     "--why", "one tree for both")
        self.refused("is not a worktree of", "set", card, f"options.worktree={trees['api']}", "--why", "x")
        self.assertEqual(self.repairs(card), [])

    def test_another_repo_s_tree_under_the_same_name_is_refused(self):
        """Reproduced red before c-585: any git directory of the recorded name passed."""
        card, _ = self.two_repo()
        stranger = self.tree("elsewhere", "keel-wt", "feature-x")
        self.refused("is not a worktree of", "set", card, f"options.worktree={stranger}", "--why", "x")
        errand = self.work("errand")
        self.board().set_fields(errand, {"options": {"worktree": f"/Users/him/{stranger.name}"}}, "human")
        self.refused("is not a worktree of", "set", errand, f"options.worktree={stranger}", "--why", "x")

    def test_what_a_card_is_stays_his(self):
        card = self.work()
        for field in ("title=new", "brief=new", "autonomy=autonomous", "repo=keel", "model=opus",
                      "topic=x", "parent=c-1", "after=c-1", "options.kind=review",
                      "blocked_reason=x"):
            with self.subTest(field=field):
                # an option fixed at create is refused by the board, in its words (c-665)
                said = "is the owner's to change after create" if field.startswith("options.") else "is his"
                self.refused(said, "set", card, field, "--why", "x")
        self.assertEqual(self.repairs(card), [])

    def test_a_path_repair_never_swaps_the_document_or_leaves_the_card(self):
        card = self.work()
        plan = self.own_file(card)
        self.board().set_fields(card, {"plan_ref": str(plan)}, "human")
        other = self.own_file(card, "plan-v2.md")
        self.refused("never swaps the document", "set", card, f"plan_ref={other}", "--why", "x")
        stranger = self.own_file(self.work("s"))
        self.refused("own directory", "set", card, f"plan_ref={stranger}", "--why", "x")
        self.refused("own directory", "set", card, f"plan_ref={plan.parent}/missing.md", "--why", "x")
        self.refused("names a file", "set", card, "output_ref=https://example.test/pr/1", "--why", "x")
        self.refused("never swaps the document", "set", card, f"output_ref={plan}", "--why", "x")

    def test_a_repair_that_changes_nothing_records_none(self):
        card = self.work()
        plan = self.own_file(card)
        self.board().set_fields(card, {"plan_ref": str(plan)}, "human")
        self.repaired("set", card, f"plan_ref={plan}", "--why", "already right")
        self.assertEqual(self.repairs(card), [])

    def test_a_worktree_that_is_not_one_is_refused(self):
        card = self.work()
        self.board().set_fields(card, {"options": {"worktree": f"/Users/him/trees/{card}"}}, "human")
        plain = self.dir / "plain" / card
        plain.mkdir(parents=True)
        self.refused("not an existing git worktree", "set", card, f"options.worktree={plain}",
                     "--why", "x")
        self.refused("not an existing git worktree", "set", card,
                     f"options.worktree={self.dir}/missing/{card}", "--why", "x")


class HouseTest(RepairCase):
    def setUp(self):
        super().setUp()
        self.resumed = []
        for name, value in (("resume", lambda cfg, board, card_id, prompt=None, actor="drain":
                                      self.resumed.append((card_id, prompt, actor)) or {"session_id": "s"}),
                            ("refuse_if_busy", lambda card, config_dir: None)):
            patch = mock.patch.object(repairhouse.house, name, value)
            patch.start()
            self.addCleanup(patch.stop)

    def stuck(self, by="drain", card=None, **block) -> str:
        """A house at building, blocked; a drain or hook block is marked Keel's mechanics
        unless the test names another mark."""
        if by in repair.MECHANICS_WRITERS and "mark" not in block:
            block["mark"] = "mechanics"
        card = card or self.work()
        board = self.board()
        board.set_session(card, SESSION, "drain")
        board.stage(card, "assigned", "human")
        board.stage(card, "building", "drain")
        board.block(card, "house failed to start: boom", by, **block)
        return card

    def test_a_block_the_drain_wrote_is_unblocked_on_a_work_card(self):
        card = self.stuck()
        self.repaired("unblock", card, "--why", "the start failure is fixed")
        self.assertIsNone(self.board().get(card)["blocked_reason"])
        self.assertEqual([e["data"]["repair"] for e in self.repairs(card)], ["unblock"])

    def test_a_repair_resume_says_only_the_plain_resume_line(self):
        card = self.stuck(by="hook", card=self.personal())
        self.repaired("console", "resume", card, "--why", "stale harness state")
        (resumed, prompt, actor), = self.resumed
        self.assertEqual((resumed, actor), (card, "bosun"))
        self.assertEqual(prompt, prompts.RESUME.format(stage="building"))
        self.assertNotIn("stale harness state", prompt)
        self.assertIsNone(self.board().get(card)["blocked_reason"])
        self.assertEqual([e["data"]["repair"] for e in self.repairs(card)], ["resume"])
        self.refused("carries no words", "console", "resume", self.stuck(), "--why", "x",
                     "--words", "do it differently")

    def test_a_repair_retry_of_a_keel_block_and_of_a_keel_filed_request(self):
        card = self.stuck(card=self.personal())
        self.repaired("console", "retry", card, "--why", "a fresh house")
        row = self.board().get(card)
        self.assertEqual((row["stage"], row["blocked_reason"]), ("assigned", None))
        keel = self.personal("k")
        self.board().set_session(keel, SESSION, "drain")
        self.assertEqual(self.kb("block", keel, "the move was refused", "--keel",
                                 env={"KEEL_CARD": keel})[0], 0)
        self.board().stage(keel, "assigned", "human")
        self.repaired("console", "retry", keel, "--why", "the refused move was a Keel bug")
        self.assertIsNone(self.board().get(keel)["blocked_reason"])

    def test_bosun_s_own_failed_resume_is_his_so_a_repair_cannot_loop(self):
        """With no strike limit, a repair whose resume failed and re-marked the card would be
        repairable again on every pass (c-593 review): Bosun's own failed resume is his."""
        card = self.stuck()
        self.board().block(card, "Bosun's resume failed: boom", "bosun", mark="failed-resume")
        self.refused("not Keel's mechanics", "unblock", card, "--why", "the harness is back")
        self.board().block(card, "the drain's resume failed: boom", "drain", mark="failed-resume")
        self.repaired("unblock", card, "--why", "the harness is back")

    def test_a_repair_resume_that_fails_leaves_the_card_blocked_and_marked(self):
        card = self.stuck(card=self.personal())
        with mock.patch.object(repairhouse.house, "resume", side_effect=RuntimeError("no daemon")):
            self.refused("the resume of", "console", "resume", card, "--why", "x")
        row = self.board().get(card)
        self.assertIn("Bosun's resume failed: no daemon", row["blocked_reason"])
        self.assertEqual(self.board().events(card)[-1]["data"], {"failed": "resume"})

    def test_a_space_this_machine_has_no_config_for_is_refused_not_crashed(self):
        card = self.stuck()
        self.refused("is not configured on box", "console", "resume", card, "--why", "x")
        self.assertEqual(self.repairs(card), [])

    def test_a_block_that_is_his_is_refused(self):
        question = self.stuck(by="house", card=self.personal())
        self.refused("not Keel's mechanics", "unblock", question, "--why", "x")
        self.refused("not Keel's mechanics", "console", "resume", question, "--why", "x")
        self.refused("not Keel's mechanics", "console", "retry", question, "--why", "x")
        self.refused("not Keel's mechanics", "unblock", self.stuck(by="human"), "--why", "x")
        self.refused("permission pause", "unblock", self.stuck(mark="permission-pause"), "--why", "x")
        self.refused("review limit", "unblock", self.stuck(mark="review-limit"), "--why", "x")
        login = self.stuck()
        self.board().set_fields(login, {"options": {"login_hold": "work"}}, "drain")
        self.refused("login", "unblock", login, "--why", "x")
        self.refused("is not blocked", "unblock", self.work("free"), "--why", "x")

    def test_the_unjudged_and_the_withheld_fresh_start_blocks_are_his(self):
        """c-654 review: each is how the card needs HIM (his re-offer, his word for a fresh
        start), so no repair of Bosun's lifts one or moves its house."""
        for mark in ("unjudged", "afresh-withheld", "afresh-twice"):
            card = self.stuck(card=self.personal(mark), mark=mark)
            for verb in (("unblock", card), ("console", "resume", card), ("console", "retry", card)):
                with self.subTest(mark=mark, verb=verb[-2]):
                    self.refused("not Keel's mechanics", *verb, "--why", "x")
            self.assertEqual(self.repairs(card), [])

    def test_a_drain_block_without_the_mark_is_his(self):
        """A failed merge and a quiet house are written by the drain and say the fix is his."""
        for reason in ("outcome not merged: the suite failed", "quiet for an hour: his to look at"):
            with self.subTest(reason=reason):
                card = self.stuck(card=self.personal(), mark=None)
                self.board().block(card, reason, "drain")
                self.refused("not Keel's mechanics", "unblock", card, "--why", "x")
                self.refused("not Keel's mechanics", "console", "retry", card, "--why", "x")

    def test_the_no_model_and_quiet_blocks_are_his_at_their_call_sites(self):
        """c-577 (c-585): the drain writes both and says the fix is his, so neither carries
        the mechanics mark and no repair verb clears them. Driven through the real writers,
        so marking either one later fails here."""
        cfg = config_module.load(Path(os.environ["KEEL_CONFIG"]), ensure=False)
        board = self.board()
        bare = self.stuck(card=self.personal("no model"), mark=None)
        board.conn.execute("UPDATE cards SET model = NULL, blocked_reason = NULL WHERE id = ?", (bare,))
        board.conn.commit()
        with self.assertRaises(house.NoModel):
            house.require_model(cfg, board, board.get(bare))
        quiet = self.stuck(card=self.personal("quiet"), mark=None)
        with mock.patch.object(drain, "last_output", return_value=""):
            drain.block_quiet(cfg, board, board.get(quiet), {"tries": 3})
        for card in (bare, quiet):
            self.assertNotIn("mechanics", self.board().events(card)[-1].get("data") or {})
            for verb in (("unblock", card), ("console", "resume", card), ("console", "retry", card)):
                with self.subTest(card=card, verb=verb[0] + verb[-2]):
                    self.refused("not Keel's mechanics", *verb, "--why", "x")
        self.assertEqual(self.repairs(bare) + self.repairs(quiet), [])

    def test_only_keel_marks_a_block_as_its_mechanics(self):
        card = self.work()
        self.refused("is Keel's own", "block", card, "a question", "--mark", "mechanics",
                     env={"KEEL_CARD": card})
        self.refused("never marks", "block", card, "a question", "--mark", "mechanics")

    def test_the_round_and_the_landing_mark_their_own_failures_as_mechanics(self):
        """The three Keel call sites that write the mark (house.launch is pinned in
        tests/test_house.py): a review batch that could not reach the house (c-600), a
        landing that merged and did not move to done. Each block they leave is then Bosun's
        to repair."""
        from keel import shipping
        cfg = mock.Mock(host="box", merge_queue=False, spaces={"work": mock.Mock(config_dir=None)})
        round_card = self.work("r")
        board = self.board()
        with mock.patch.object(shipping.shipwatch, "take_batch", return_value=([], {"round": 1})), \
                mock.patch.object(shipping.harness, "agents", return_value=[]), \
                mock.patch.object(shipping.shipround, "batch_prompt", return_value="the batch"), \
                mock.patch.object(shipping.house, "launch", side_effect=OSError("no daemon")), \
                mock.patch.object(shipping, "log"):
            shipping.deliver(cfg, board, board.get(round_card), {}, "a comment", None, slots=1)
        landed = self.work("l")
        with mock.patch.object(landing, "mark"):
            landing.record_landed(cfg, board, board.get(landed), None,
                                  {"pinned": "a" * 40, "sha": "b" * 40, "published": "",
                                   "notes": [], "target": "next"})
        for card in (round_card, landed):
            with self.subTest(card=card):
                self.assertEqual(self.board().events(card)[-1]["data"], {"mechanics": True})
                self.repaired("unblock", card, "--why", "the harness is back")

    def test_a_retry_repair_of_a_work_card_with_no_session(self):
        card = self.work()
        board = self.board()
        board.stage(card, "assigned", "human")
        board.stage(card, "building", "drain")
        board.block(card, "house failed to start: boom", "drain", mark="mechanics")
        self.repaired("console", "retry", card, "--why", "the start failure is fixed")
        row = self.board().get(card)
        self.assertEqual((row["stage"], row["blocked_reason"]), ("assigned", None))

    def test_a_held_card_waits_and_repairs_have_no_limit(self):
        held = self.stuck()
        board = self.board()
        board.set_fields(held, {"options": {"dropin_hold": {"at": board.now()}}}, "human")
        self.refused("is held", "unblock", held, "--why", "x")
        card = self.stuck()
        for n in range(5):
            self.repaired("unblock", card, "--why", f"try {n}")
            self.board().block(card, "house failed to start: boom", "drain", mark="mechanics")
        self.assertEqual(len(self.repairs(card)), 5, "each recorded, none counted against it")

    def test_bosun_s_own_keel_block_is_never_repairable(self):
        """Bosun blocking over his block with --keel would make any block a repair (3.F1)."""
        card = self.stuck(by="human", card=self.personal())
        self.assertEqual(self.as_bosun("block", card, "Keel is in the way", "--keel")[0], 0)
        self.refused("not Keel's mechanics", "unblock", card, "--why", "x")


class RestageTest(RepairCase):
    def test_the_stage_it_is_at_is_replayed_and_signed(self):
        card = self.work()
        self.board().stage(card, "assigned", "human")
        stages = [e["id"] for e in self.board().events(card) if e["kind"] == "stage"]
        self.repaired("stage", card, "assigned", "--why", "the drain missed the move")
        (event,) = self.repairs(card)
        self.assertEqual((event["actor"], event["data"]["repair"], event["data"]["why"]),
                         ("bosun", "stage", "the drain missed the move"))
        self.assertEqual([e["id"] for e in self.board().events(card) if e["kind"] == "stage"],
                         stages, "a replay writes no stage event, so no move reader sees one")

    def at(self, card: str, last: str) -> None:
        board = self.board()
        for stage in ("assigned", "planning", "building", "review"):
            board.stage(card, stage, "human", plan_ref="/p.md" if stage == "planning" else None,
                        output_ref="keel/branch" if stage == "review" else None)
            if stage == last:
                return

    def test_no_replay_where_a_gate_a_landing_or_a_pull_request_waits(self):
        card = self.work()
        self.at(card, "review")
        self.refused("a replay runs only at", "stage", card, "review", "--why", "x")
        self.assertEqual(self.repairs(card), [])

    def test_a_replay_at_building_resets_no_clock_that_reads_moves(self):
        """The drain's quiet streak and the landing guard read `stage` events; a replay
        writes none (reviews 2.F1, 4.F4)."""
        card = self.work()
        self.at(card, "building")
        board = self.board()
        before = board.events(card)[-1]["id"]
        board.record_event(card, "resume", "drain", text=f"{drain.STUCK_MARK} go on")
        self.repaired("stage", card, "building", "--why", "the drain missed the move")
        self.assertEqual(drain.stuck_tries(self.board(), self.board().get(card)), 1)
        self.assertFalse(landing.moved_since(self.board(), card, before))

    def test_a_tracking_card_is_never_replayed(self):
        card = self.personal()
        self.at(card, "assigned")
        self.board().create("personal", "slice", actor="human", parent=card)
        self.refused("tracking card", "stage", card, "assigned", "--why", "x")

    def test_a_replay_at_assigned_keeps_the_drain_s_claim(self):
        card = self.work()
        board = self.board()
        board.stage(card, "assigned", "human")
        board.claim(card, "mac", "drain")
        self.repaired("stage", card, "assigned", "--why", "x")
        self.assertEqual(self.board().get(card)["options"]["claim"]["host"], "mac")

    def test_a_personal_card_is_replayed_too_but_never_at_his_plan_gate(self):
        card = self.personal()
        self.at(card, "assigned")
        self.repaired("stage", card, "assigned", "--why", "x")
        self.at(card, "planning")
        self.refused("at his gate", "stage", card, "planning", "--why", "x")

    def test_another_stage_a_ref_or_a_relay_is_his(self):
        card = self.work()
        self.board().stage(card, "assigned", "human")
        self.refused("is his", "stage", card, "building", "--why", "x")
        self.refused("carries no", "stage", card, "assigned", "--plan", "/x.md", "--why", "x")
        self.refused("carries no", "stage", card, "assigned", "--relay", "go", "--to", "mac",
                     "--why", "x")
        self.refused("carries no", "stage", card, "assigned", "--note", "free text", "--why", "x")
        self.refused("only personal cards in builder mode", "stage", card, "assigned")


class StillRefusedTest(RepairCase):
    def test_why_is_bosun_s_alone(self):
        self.create()       # his token
        card = self.work()
        self.board().stage(card, "assigned", "human")
        self.refused("Bosun's alone", "stage", card, "assigned", "--why", "x",
                     env={"KEEL_TOKEN": self.token})
        self.refused("Bosun's alone", "unblock", card, "--why", "x", env={"KEEL_CARD": card})
        self.refused("says what broke", "stage", card, "assigned", "--why", "  ")
        self.refused("neither --sync nor --assumed", "stage", card, "shipping", "--sync", "--why", "x")
        self.refused("neither --sync nor --assumed", "set", card, "plan_ref=/p", "--assumed",
                     "plan_ref", "--why", "x")

    def test_a_work_card_s_gate_its_house_and_its_relays_stay_his(self):
        card = self.work()
        self.refused("is not Bosun's", "mark", card, "--data", '{"what": "answer"}')
        self.refused("its gates are the user's", "approve", card, "plan", "--checked", "all of it")
        self.refused("is not Bosun's", "relay", card, "resume", "--to", "mac")
        self.refused("writes no note on it", "note", card, "seen")

    def test_bosun_s_guard_covers_the_repair_rules(self):
        from keel import authority
        self.assertIn("keel/repair.py", authority.AUTHORITY_PATHS)
        self.assertIn("keel/repairhouse.py", authority.AUTHORITY_PATHS)


class PathFactsTest(RepairCase):
    def repos(self):
        """A checkout, a linked worktree of it, and a stranger repo, made by real git."""
        root = self.dir / "repos"
        root.mkdir()
        env = repair.git_env()
        for args in (["init", "-q", "checkout"], ["init", "-q", "stranger"],
                     ["-C", "checkout", "-c", "user.name=t", "-c", "user.email=t@t",
                      "commit", "-q", "--allow-empty", "-m", "x"],
                     ["-C", "checkout", "worktree", "add", "-q", "../linked"]):
            subprocess.run(["git", *args], cwd=root, env=env, check=True, capture_output=True)
        return root / "checkout", root / "linked", root / "stranger"

    def test_an_inherited_git_variable_never_passes_a_stranger_tree(self):
        # Git ranks GIT_DIR and its kin above -C, so a Keel run under a git hook asked every
        # tree the same question (c-588).
        card = {"id": self.work(), "space": "work"}
        checkout, linked, stranger = self.repos()
        cfg = mock.Mock()
        cfg.spaces = {"work": mock.Mock(repo_path=lambda key: str(checkout))}
        git_dir = str(checkout / ".git")
        for name, value in (("GIT_DIR", git_dir), ("GIT_COMMON_DIR", git_dir),
                            ("GIT_WORK_TREE", str(checkout))):
            with self.subTest(name), mock.patch.dict(os.environ, {name: value}):
                facts = repair.owner_facts(cfg, card, {"api": [str(linked), str(stranger)]})
                self.assertEqual(facts, {"api": {str(linked): True, str(stranger): False}})

    def test_a_link_out_of_the_card_directory_is_not_the_card_s_file(self):
        card = self.work()
        outside = self.dir / "secret.md"
        outside.write_text("x")
        link = self.card_dir(card) / "plan.md"
        link.symlink_to(outside)
        facts = repair.path_facts(self.dir / "state" / "cards", card, [str(link)], [])
        self.assertEqual(facts["files"], {str(link): False})

    def test_facts_are_read_here_for_a_card_that_lives_here(self):
        card = self.work()
        plan = self.own_file(card)
        facts = repair.path_facts(self.dir / "state" / "cards", card, [str(plan), "plan.md"], [])
        self.assertEqual(facts["files"], {str(plan): True, "plan.md": False})


class ArgvTest(RepairCase):
    def test_why_reaches_kb_on_each_repair_verb(self):
        from keel import actions, requests
        for verb in ("set", "stage", "unblock"):
            with self.subTest(verb=verb):
                body = {"verb": verb, "id": "c-1", "why": "-dash first",
                        "fields": {"plan_ref": "/p"}, "stage": "review"}
                self.assertIn("--why=-dash first", actions.ARGV_BUILDERS[verb](body))
        console = requests.argv({"sub": "resume", "target": "c-1", "why": "-x"})
        self.assertIn("--why=-x", console)
