"""Lane GRP, GR-2: a feature card's review house runs the core on every member's diff as one
change, with the cross-repo contract check on when there is more than one repo; the outcome
names each finding's member and has ONE verdict per member; his Approve hands the adapter
each member's comments, the summary and each member's verdict.

Every pull request, story and repo here is invented.
"""

import contextlib
import io
import json
import subprocess
import tempfile
import unittest
from pathlib import Path

from keel import adapters, house, planlint, planreview, plangate, reviewround
from keel.board import Board
from keel.review import agents, brief, findings, ledger, prep, stamp
from tests.helpers import make_config, make_repo

GIT = ("git", "-c", "user.name=t", "-c", "user.email=t@x")
SAMPLE = (Path(__file__).parent / "fixtures" / "review-feature-sample.md").read_text()
MEMBERS = [{"label": "api#4150", "key": "api:4150", "repo": "api", "pr": 4150, "head": "aaa111",
            "branch": "feature/st-41001/refuse", "base": "main", "url": "https://example.invalid/api/pr/4150"},
           {"label": "web#2200", "key": "web:2200", "repo": "web", "pr": 2200,
            "head": "bbb222", "branch": "feature/st-41001/toast", "base": "main",
            "url": "https://example.invalid/web/pr/2200"}]
FEATURE = {"review_key": "feature:st-41001", "kind": "review", "slot": "review", "review_group": "st-41001",
           "review_members": MEMBERS}


def sh(cwd, *args):
    return subprocess.run(args, cwd=str(cwd), capture_output=True, text=True, check=True).stdout.strip()


def resolve_all(path, start, end):
    return None


def lint(text, review=None):
    return planlint.lint_text(text, "context.md", repo_card=True, resolve=resolve_all, review=review)


def rules(result):
    return sorted({f["rule"] for f in result["findings"] if f["level"] == "error"})


def texts(result):
    return " | ".join(f["text"] for f in result["findings"] if f["level"] == "error")


class TwoReposCase(unittest.TestCase):
    """Two real repos, each with a change on a branch against main."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.dir = Path(self.tmp.name)
        self.trees = {}
        for name, path, words in (("api", "app/routes.py", "refuse = True\n"),
                                  ("web", "src/Details.js", "const toast = 1;\n")):
            repo = make_repo(self.dir / name)
            sh(repo, "git", "checkout", "-q", "-b", "feature/st-41001/x")
            (repo / path).parent.mkdir(parents=True, exist_ok=True)
            (repo / path).write_text(words)
            sh(repo, *GIT, "add", "-A")
            sh(repo, *GIT, "commit", "-q", "-m", f"the {name} half")
            self.trees[name] = repo
        self.card_dir = self.dir / "card"


class PrepTest(TwoReposCase):
    def test_every_member_s_diff_is_one_change_each_under_its_label(self):
        main = "main"
        done = prep.prepare(self.card_dir, main, [], members=[
            ("api#4150", str(self.trees["api"]), main), ("web#2200", str(self.trees["web"]), main)])
        diff = (self.card_dir / stamp.DIFF_FILE).read_text()
        self.assertIn("# repo: api member api#4150", diff)
        self.assertIn("# repo: web member web#2200", diff)
        self.assertIn("app/routes.py", diff)
        self.assertIn("src/Details.js", diff)
        self.assertEqual(sorted(done["touched"]), ["api", "web"])
        self.assertIn("Cross-repo contract", (self.card_dir / prep.STANDARDS_FILE).read_text())

    def test_the_command_line_takes_members(self):
        main = "main"
        with contextlib.redirect_stdout(io.StringIO()):
            code = prep.main(["prep", "--dir", str(self.card_dir), "--base", main,
                              "--member", "api#4150", str(self.trees["api"]), main,
                              "--member", "web#2200", str(self.trees["web"]), main])
        self.assertEqual(code, 0)
        self.assertIn("member web#2200", (self.card_dir / stamp.DIFF_FILE).read_text())

    def test_one_repo_gets_no_contract_section(self):
        main = "main"
        prep.prepare(self.card_dir, main, [str(self.trees["api"])])
        self.assertNotIn("Cross-repo contract", (self.card_dir / prep.STANDARDS_FILE).read_text())


class AgentsTest(unittest.TestCase):
    def test_the_contract_check_switches_on_with_more_than_one_repo(self):
        plain = json.loads(agents.agents_json())[agents.REVIEWER]["prompt"]
        both = json.loads(agents.agents_json(members=["api#4150", "web#2200"], cross_repo=True))
        prompt = both[agents.REVIEWER]["prompt"]
        for words in ("Cross-repo contract", "path", "HTTP method", "field names", "casing", "error",
                      "one side changed without the other", '"member"', "api#4150", '"contract"'):
            self.assertIn(words, prompt)
        self.assertNotIn("Cross-repo contract", plain)
        self.assertNotIn('"member"', plain)
        same_repo = json.loads(agents.agents_json(members=["api#4143", "api#4144"], cross_repo=False))
        self.assertIn('"member"', same_repo[agents.REVIEWER]["prompt"])
        self.assertNotIn("Cross-repo contract", same_repo[agents.REVIEWER]["prompt"])

    def test_the_house_asks_for_it_on_a_feature_card_across_two_repos(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        cfg = make_config(Path(tmp.name))
        card = {"id": "c-901", "space": "work", "repo": "api,web", "options": FEATURE}
        prompt = json.loads(house.reviewer_of(cfg, card))[agents.REVIEWER]["prompt"]
        self.assertIn("Cross-repo contract", prompt)
        single = {"id": "c-902", "space": "work", "repo": "api",
                  "options": {"review_key": "api:4150", "kind": "review", "pr": 4150}}
        self.assertNotIn("Cross-repo contract", json.loads(house.reviewer_of(cfg, single))[agents.REVIEWER]["prompt"])


class FindingsTest(unittest.TestCase):
    def test_a_finding_keeps_its_member_and_a_contract_axis(self):
        [one] = findings.normalise_all([{"id": "F1", "axis": "contract", "member": "api#4150", "severity": "high",
                                         "path": "app/routes.py", "line": 40, "claim": "names differ"}], 1)
        self.assertEqual((one["axis"], one["member"]), ("contract", "api#4150"))
        text = findings.render([{"round": 1, "head": "abc", "findings": [one]}])
        self.assertIn("### Cross-repo contract", text)
        self.assertIn("api#4150", text)


class PeerBriefTest(unittest.TestCase):
    def test_a_feature_card_s_steps_name_every_member_and_the_contract(self):
        text = brief.peer_block(Path("/tmp/c-901"), "main", Path("/k/bin/keel-review"), FEATURE)
        for words in ("api#4150", "web#2200", "--member", "one change", "Cross-repo contract",
                      "names its member", "ONE verdict per pull request"):
            self.assertIn(words, text)


class LintTest(unittest.TestCase):
    REVIEW = {"reviewed": True, "surviving": [], "ledger": [], "members": ["api#4150", "web#2200"]}

    def test_the_feature_sample_passes(self):
        result = lint(SAMPLE, self.REVIEW)
        self.assertTrue(result["ok"], planlint.lines_of(result))

    def test_the_members_come_from_the_frontmatter_when_the_caller_knows_none(self):
        self.assertTrue(lint(SAMPLE)["ok"], planlint.lines_of(lint(SAMPLE)))

    def test_a_member_with_no_verdict_is_refused(self):
        text = SAMPLE.split("```decision verdict-web-2200")[0]
        found = lint(text, self.REVIEW)
        self.assertIn("C32", rules(found))
        self.assertIn("web#2200 has no verdict", texts(found))

    def test_two_verdicts_for_one_member_or_a_plain_verdict_is_refused(self):
        twice = SAMPLE + "\n" + SAMPLE[SAMPLE.index("```decision verdict-api-4150"):SAMPLE.index("```decision verdict-web")]
        self.assertIn("C32", rules(lint(twice, self.REVIEW)))
        plain = SAMPLE.replace("```decision verdict-api-4150", "```decision verdict")
        self.assertIn("C32", rules(lint(plain, self.REVIEW)))

    def test_a_verdict_for_a_pull_request_that_is_not_a_member_is_refused(self):
        text = SAMPLE.replace("verdict-web-2200", "verdict-web-2201")
        self.assertIn("C32", rules(lint(text, self.REVIEW)))

    def test_a_single_review_is_unchanged(self):
        single = (Path(__file__).parent / "fixtures" / "review-sample.md").read_text()
        self.assertTrue(lint(single, {"reviewed": True, "surviving": [], "ledger": []})["ok"])

    def test_the_ledger_rule_matches_the_member_too(self):
        ledger_lines = [{"id": "r1-f9", "member": "api#4150", "path": "src/Details.js", "line": 88, "choice": "drop"}]
        self.assertTrue(lint(SAMPLE, dict(self.REVIEW, ledger=ledger_lines))["ok"])
        ledger_lines[0]["member"] = "web#2200"
        self.assertIn("C31", rules(lint(SAMPLE, dict(self.REVIEW, ledger=ledger_lines))))


class ContextTest(TwoReposCase):
    def test_the_lint_knows_the_members_and_the_carried_ledger_by_member(self):
        head = sh(self.trees["web"], "git", "rev-parse", "HEAD")
        options = dict(FEATURE, review_worktrees={"api#4150": str(self.trees["api"]),
                                                  "web#2200": str(self.trees["web"])},
                       review_carried=[{"member": "web#2200", "head": head, "ledger": [
                           {"id": "r1-f1", "member": "web#2200", "path": "src/Details.js", "line": 1,
                            "choice": "drop"}]}])
        self.card_dir.mkdir(parents=True, exist_ok=True)
        found = ledger.context({"id": "c-901", "options": options}, self.card_dir, self.trees["api"])
        self.assertEqual(found["members"], ["api#4150", "web#2200"])
        self.assertEqual([(one["member"], one["line"]) for one in found["ledger"]], [("web#2200", 1)])

    def test_a_path_resolves_in_any_member_s_worktree(self):
        options = dict(FEATURE, review_worktrees={"api#4150": str(self.trees["api"]),
                                                  "web#2200": str(self.trees["web"])})
        resolve = plangate.resolver_for({"id": "c-901", "repo": "api,web", "options": options},
                                        str(self.trees["api"]))
        self.assertIsNone(resolve("app/routes.py", 1, 1))
        self.assertIsNone(resolve("src/Details.js", 1, 1))
        self.assertIsNotNone(resolve("src/Nowhere.js", 1, 1))


def script(path: Path, body: str) -> None:
    path.write_text("#!/bin/sh\n" + body)
    path.chmod(0o755)


class ApproveTest(unittest.TestCase):
    """His Approve of a feature card: each member's comments, the summary, each verdict."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.dir = Path(self.tmp.name)
        self.cfg = make_config(self.dir)
        self.board = Board(self.cfg.db_path)
        self.addCleanup(self.board.close)
        work = self.cfg.adapters_dir / "work"
        work.mkdir(parents=True, exist_ok=True)
        self.answers = self.dir / "answers.log"
        script(work / "publish", f'if [ "$2" = "--answer" ]; then cat >> {self.answers}; echo >> {self.answers}; fi\n'
                                 f'echo \'{{"published": "review"}}\'\n')
        options = dict(FEATURE, review_head="api#4150@aaa111,web#2200@bbb222",
                       review_heads={"api#4150": "aaa111", "web#2200": "bbb222"})
        self.card = self.board.create("work", "Review: st-41001", repo="api,web", actor="drain",
                                      options=options)
        self.board.stage(self.card, "assigned", "human")
        self.board.stage(self.card, "building", "drain")
        self.board.stage(self.card, "review", "house", plan_ref="p.md", output_ref="https://example.invalid/pr")
        card_dir = self.cfg.card_dir(self.card)
        card_dir.mkdir(parents=True, exist_ok=True)
        (card_dir / "context.md").write_text(SAMPLE)
        stamp.save_rounds(card_dir, [{"round": 1, "head": "aaa111", "complete": True, "findings": [
            {"id": f"r1.F{n}", "axis": "standards", "severity": level, "verify": "kept", "claim": "x",
             "path": "p", "line": 1} for n, level in ((1, "high"), (2, "medium"), (3, "low"))]}])

    def answer(self):
        self.board.approve(self.card, "outcome", "human", publish=adapters.publisher(self.cfg, "work"))
        return json.loads(self.answers.read_text().splitlines()[-1])["review"]

    def test_each_member_gets_its_own_comments_and_verdict(self):
        review = self.answer()
        members = {m["member"]: m for m in review["members"]}
        self.assertEqual(sorted(members), ["api#4150", "web#2200"])
        self.assertEqual([c["row"] for c in members["api#4150"]["comments"]], ["r1-f1"])
        self.assertEqual([c["row"] for c in members["web#2200"]["comments"]], ["r1-f2"])
        self.assertEqual((members["api#4150"]["verdict"], members["api#4150"]["pr"],
                          members["api#4150"]["repo"], members["api#4150"]["head"]),
                         ("changes", 4150, "api", "aaa111"))
        self.assertIn("api#4150", review["summary"])
        self.assertIn("web#2200", review["summary"])
        self.assertEqual({(e["id"], e["member"]) for e in review["ledger"]},
                         {("r1-f1", "api#4150"), ("r1-f2", "web#2200"), ("r1-f3", "web#2200")})

    def test_his_verdict_per_member_wins(self):
        self.board.mark(self.card, {"what": "answer", "doc": "outcome", "block": "verdict-web-2200",
                                    "option": "approve"}, "human")
        members = {m["member"]: m for m in self.answer()["members"]}
        self.assertEqual((members["api#4150"]["verdict"], members["web#2200"]["verdict"]),
                         ("changes", "approve"))

    def test_nothing_is_handed_on_for_a_feature_with_a_member_left_out(self):
        (self.cfg.card_dir(self.card) / "context.md").write_text(SAMPLE.split("```decision verdict-web-2200")[0])
        with self.assertRaisesRegex(adapters.AdapterError, "web#2200 has no verdict"):
            self.answer()
        self.assertFalse(self.answers.exists())

    def test_the_verdict_id_rule_is_one(self):
        self.assertEqual(planreview.verdict_id("web#2200"), "verdict-web-2200")
        self.assertIsNone(reviewround.answer_for(self.cfg, dict(self.board.get(self.card), stage="building")))


if __name__ == "__main__":
    unittest.main()
