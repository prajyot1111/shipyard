"""The demo sandbox (c-569): `demo/sandbox/setup`, `demo/sandbox/run`, the sandbox adapter
(`packs/sandbox/`, the example pack) and the seeded day (`demo/seed`).

Every verb's answer is held to the keys the engine reads, which are the keys the work
adapter's own tests pin for the same verb (named beside each set below), and then handed to
the engine's own reader, so a change on either side that parts them fails here. Each test
builds its sandbox in a temporary directory, outside every checkout, and reaches it only
through `demo/sandbox/run`.

What it covers, by file: `packs/sandbox/sb_card.py`, `sb_host.py`, `sb_tracker.py`,
`sb_cut.py`, `sb_brief.py`, `sb_pulls.py`, `sb_sight.py`, `sb_main.py`; `demo/sandbox/setup`,
`run`, `keel.toml.in`, `space-work.md` and the app under `demo/sandbox/app/` (`store.py`,
`search.py`, `test_reports.py`, `reports.js`, `style.css`); `demo/seed` and
`demo/seeding/code.py`, `day.py`, `parallel.py`, `phases.py`, `run.py`, `texts.py`.
"""

import json
import os
import re
import subprocess
import sys
import tempfile
import unittest
from datetime import datetime
from pathlib import Path
from unittest import mock

from keel import adapters, config, deckstate, deploy, packs, reviewcards, scaffold, shipwatch
from keel.board import open_board

ROOT = Path(__file__).resolve().parent.parent
SETUP = ROOT / "demo" / "sandbox" / "setup"
RUN = ROOT / "demo" / "sandbox" / "run"
ADAPTER = ROOT / "packs" / "sandbox"
PORT = "8893"

# The keys each verb answers with, as the engine reads them and the work adapter's tests pin
# them (packs/work/tests/...).
SIGHT_KEYS = {"state", "draft", "url", "head", "behind", "comments", "reviews", "approvals",
              "ci"}                                                                        # test_shipping.py
PART_KEYS = SIGHT_KEYS | {"repo", "pr", "primary"}                                         # test_shipping_prs.py
MINE_KEYS = {"repo", "pr", "title", "branch", "draft", "updated", "url", "worktree", "cards",
             "matched_by"}                                                                 # test_shipping_prs.py
SCAN_KEYS = {"key", "repo", "pr", "title", "author", "description", "created", "updated", "head",
             "branch", "base", "url", "group"}                                             # test_review_groups.py
PUBLISH_KEYS = {"pr", "url", "draft", "shipping", "prs", "story", "story_state", "heads"}           # test_cross_repo_prs.py
SHIP_KEYS = {"shipping", "shipped", "pr", "pushed", "skipped", "ready", "posted", "sent"}              # test_shipping.py
LINK_KEYS = {"story", "pr", "prs"}                                                         # test_acting.py


def build(home: Path, *extra: str, env: dict | None = None) -> subprocess.CompletedProcess:
    return subprocess.run([sys.executable, str(SETUP), "--home", str(home), "--port", PORT, *extra],
                          capture_output=True, text=True, env=env or dict(os.environ))


def in_sandbox(home: Path, *argv: str, stdin: str = "", env: dict | None = None) -> subprocess.CompletedProcess:
    return subprocess.run([sys.executable, str(RUN), *argv], input=stdin, capture_output=True, text=True,
                          env={**(env or os.environ), "KEEL_SANDBOX": str(home)})


class SandboxCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="keel-sandbox-test-")
        self.home = Path(self.tmp.name) / "sb"

    def tearDown(self):
        self.tmp.cleanup()

    def built(self) -> None:
        made = build(self.home)
        self.assertEqual(made.returncode, 0, made.stderr)

    def verb(self, *argv: str, stdin: str = "") -> str:
        done = in_sandbox(self.home, *argv, stdin=stdin)
        self.assertEqual(done.returncode, 0, f"{argv}: {done.stderr}")
        return done.stdout

    def adapter(self, verb: str, *argv: str, stdin: str = ""):
        return self.verb(str(ADAPTER / verb), *argv, stdin=stdin)

    def json_of(self, verb: str, *argv: str, stdin: str = ""):
        return json.loads(self.adapter(verb, *argv, stdin=stdin))

    def environ(self) -> dict:
        return {"KEEL_CONFIG": str(self.home / "keel.toml"), "KEEL_HOME": str(ROOT),
                "KEEL_SANDBOX": str(self.home), "KEEL_HOST": "box"}

    def cfg(self):
        with mock.patch.dict(os.environ, self.environ()):
            return config.load(self.home / "keel.toml")


class SetupTest(SandboxCase):
    def test_builds_the_sandbox_and_clean_takes_it_away(self):
        self.built()
        for path in ("keel.toml", ".keel-sandbox", "origin/api.git", "origin/web.git", "repos/api/.git",
                     "repos/web/.git", "host/api", "tracker"):
            self.assertTrue((self.home / path).exists(), path)
        self.assertEqual(list((self.home / "adapters").iterdir()), [])
        log = subprocess.run(["git", "-C", str(self.home / "repos" / "api"), "log", "--format=%an"],
                             capture_output=True, text=True).stdout.split("\n")
        self.assertIn("Maya Chen", log)
        cleaned = build(self.home, "--clean")
        self.assertEqual(cleaned.returncode, 0, cleaned.stderr)
        self.assertFalse(self.home.exists())

    def test_the_work_space_runs_preship_first_and_its_repos_ignore_pycache(self):
        """c-604: the sandbox ran the serial order the live work space does not, and a house's
        worktree kept `__pycache__/` untracked, so the reap at done never took one."""
        self.built()
        work = self.cfg().spaces["work"]
        self.assertTrue(work.preship_first)
        self.assertEqual(work.review_full_rounds, 1)
        for repo in ("api", "web"):
            clone = self.home / "repos" / repo
            (clone / "__pycache__").mkdir(exist_ok=True)
            (clone / "__pycache__" / "x.cpython-314.pyc").write_bytes(b"")
            status = subprocess.run(["git", "-C", str(clone), "status", "--porcelain"],
                                    capture_output=True, text=True).stdout
            self.assertEqual(status, "", repo)

    def test_refuses_the_live_state_switch_a_live_port_and_a_second_build(self):
        refused = build(self.home, env={**os.environ, "KEEL_LIVE_STATE": "1"})
        self.assertEqual(refused.returncode, 1)
        self.assertIn("KEEL_LIVE_STATE", refused.stderr)
        live = subprocess.run([sys.executable, str(SETUP), "--home", str(self.home), "--port", "8790"],
                              capture_output=True, text=True)
        self.assertIn("live port (8790)", live.stderr)
        self.assertFalse(self.home.exists())
        self.built()
        self.assertIn("exists", build(self.home).stderr)

    def test_refuses_a_home_inside_the_checkout_and_cleans_only_its_own(self):
        inside = subprocess.run([sys.executable, str(SETUP), "--home", str(ROOT / "state" / "sb")],
                                capture_output=True, text=True)
        self.assertIn("inside a Keel checkout", inside.stderr)
        self.home.mkdir(parents=True)
        (self.home / "keep.txt").write_text("not a sandbox")
        self.assertIn("not a sandbox", build(self.home, "--clean").stderr)
        self.assertTrue((self.home / "keep.txt").exists())


class IsolationTest(SandboxCase):
    def test_the_toml_opens_only_the_sandbox_and_reaches_nothing_live(self):
        self.built()
        cfg = self.cfg()
        self.assertTrue(Path(cfg.db_path).resolve().is_relative_to(self.home.resolve()))
        self.assertEqual(cfg.integration, {})
        self.assertEqual(deploy.repos(cfg), [])
        self.assertEqual({space.adapter for space in cfg.spaces.values()}, {"sandbox", None})
        self.assertEqual(cfg.spaces["work"].adapter_dir.resolve(), ADAPTER.resolve())   # the pack (c-617)
        self.assertEqual(len({space.config_dir for space in cfg.spaces.values()}), 1)
        self.assertEqual(cfg.serve_port, int(PORT))

    def test_run_drops_what_could_point_elsewhere_and_refuses_a_non_sandbox(self):
        self.built()
        env = {**os.environ, "KEEL_URL": "http://127.0.0.1:1", "KEEL_CARD": "c-1", "KEEL_TOKEN": "t"}
        said = in_sandbox(self.home, sys.executable, "-c",
                          "import os; print([os.environ.get(k) for k in ('KEEL_URL', 'KEEL_CARD', 'KEEL_TOKEN')])",
                          env=env)
        self.assertEqual(said.stdout.strip(), "[None, None, None]")
        (self.home / ".keel-sandbox").unlink()
        self.assertIn("not a sandbox", in_sandbox(self.home, "kb", "list").stderr)


class ScaffoldedPackTest(SandboxCase):
    def test_a_new_pack_serves_its_own_space_and_never_the_sandboxs(self):
        """`keel new pack acme` (c-634) copies this code; the copy takes its name from its
        directory, so its verbs serve a space that names acme and refuse while only the
        sandbox's space exists (c-628 review r1.F1 and r1.F6)."""
        self.built()
        scaffold.new_pack("acme", ROOT, into=self.home / "adapters")
        acme = self.home / "adapters" / "acme"
        cid = self.verb("kb", "create", "--space", "work", "--title", "Add CSV export", "--repo", "api",
                        "--autonomy", "attended", "--model", "opus").split()[-1]
        refused = in_sandbox(self.home, str(acme / "worktree"), cid)
        self.assertNotEqual(refused.returncode, 0)
        self.assertIn("names the acme adapter", refused.stderr)
        toml = self.home / "keel.toml"
        toml.write_text(toml.read_text().replace('pack = "sandbox"', 'adapter = "acme"', 1))
        trees = self.verb(str(acme / "worktree"), cid).split()
        self.assertEqual([Path(tree).parent.name for tree in trees], ["api"])
        brief = self.verb(str(acme / "brief"), cid)
        named = re.search(rf"`(\S+/pr) {cid}`", brief).group(1)
        self.assertEqual(Path(named).resolve(), (acme / "pr").resolve(), "the copy's own pr, where it is (r2.F3)")
        self.assertTrue(os.access(named, os.X_OK))


class AdapterFlowTest(SandboxCase):
    def test_a_two_repo_card_from_its_worktrees_to_shipping(self):
        self.built()
        cid = self.verb("kb", "create", "--space", "work", "--title", "Add CSV export", "--repo", "api,web",
                        "--autonomy", "attended", "--model", "opus").split()[-1]
        self.assertGreater(int(cid[2:]), 9200)
        self.verb("kb", "set", cid, "options.tracker_mode=create at task start")
        trees = self.adapter("worktree", cid).split()
        self.assertEqual([Path(t).parent.name for t in trees], ["api", "web"])
        card = json.loads(self.verb("kb", "show", cid, "--json"))
        self.assertEqual(card["options"]["tracker_ref"], "st-101")
        self.assertIn(f"packs/sandbox/pr {cid}", self.adapter("brief", cid))

        missing = self.json_of("publishable", cid, stdin=json.dumps(card))
        self.assertEqual(set(missing), {"publishable", "missing"})
        self.assertIn("not on origin in api", missing["missing"])
        for tree in trees:
            Path(tree, "export.py").write_text("ROWS = []\n")
            subprocess.run(["git", "-C", tree, "add", "."], check=True, capture_output=True)
            subprocess.run(["git", "-C", tree, "commit", "-qm", "export"], check=True, capture_output=True)
            subprocess.run(["git", "-C", tree, "push", "-q", "-u", "origin", card["options"]["branch"]],
                           check=True, capture_output=True)
        with mock.patch.dict(os.environ, self.environ()):
            self.assertIn("no pull request is open", adapters.publishable(self.cfg(), card))
        urls = self.adapter("pr", cid, "--draft").split()
        self.assertEqual(urls, ["https://code.sandbox.test/api/pull/1", "https://code.sandbox.test/web/pull/1"])
        self.assertEqual(self.json_of("publishable", cid), {"publishable": True})
        with mock.patch.dict(os.environ, self.environ()):
            shown = json.loads(self.verb("kb", "show", cid, "--json"))
            self.assertIsNone(adapters.publishable(self.cfg(), shown))

        links = self.json_of("act", "links", cid)[cid]
        self.assertEqual(set(links), LINK_KEYS)
        self.assertEqual([p["repo"] for p in deckstate.pulls_of(links)], ["api", "web"])
        self.assertEqual(self.json_of("act", "verbs"), {"card": []})

        published = self.json_of("publish", cid)
        self.assertEqual(set(published), PUBLISH_KEYS)
        self.assertTrue(published["shipping"])
        self.assertEqual([p["draft"] for p in published["prs"]], [False, False])

        sight = self.json_of("ship", cid, "poll")
        self.assertEqual(set(sight), {"state", "url", "head", "prs"})
        for part in sight["prs"]:
            self.assertEqual(set(part), PART_KEYS)
        shipped, events = shipwatch.fold({}, sight, datetime.now().astimezone())
        self.assertEqual((events, shipped["pending"]), ([], []))
        pr_file = self.home / "host" / "web" / "1.json"
        pr = json.loads(pr_file.read_text())
        pr["comments"].append({"id": 900, "author": {"id": "tom", "name": "Tom Okafor"}, "at": pr["created"],
                               "path": "export.py", "line": 1, "parent": None, "text": "Name the columns?"})
        pr_file.write_text(json.dumps(pr))
        again, _ = shipwatch.fold(shipped, self.json_of("ship", cid, "poll"), datetime.now().astimezone())
        self.assertEqual([item["text"] for item in again["pending"]], ["Name the columns?"])
        self.assertIn("export.py", self.adapter("ship", cid, "diff"))
        cards = json.loads(self.verb("kb", "list", "--all", "--json"))
        mine = self.json_of("ship", "mine", stdin=json.dumps(cards))["prs"]
        self.assertEqual({row["repo"] for row in mine}, {"api", "web"})
        for row in mine:
            self.assertEqual(set(row), MINE_KEYS)
            self.assertEqual((row["cards"], row["matched_by"]), ([cid], "branch"))
        self.assertEqual(set(self.json_of("ship", cid, "down")), {"down", "failed", "worktrees"})

    def test_the_engine_files_a_review_card_from_the_scan_and_polls_it(self):
        self.built()
        head = subprocess.run(["git", "-C", str(self.home / "repos" / "api"), "rev-parse", "HEAD"],
                              capture_output=True, text=True).stdout.strip()
        subprocess.run(["git", "-C", str(self.home / "repos" / "api"), "push", "-q", "origin",
                        f"{head}:refs/heads/feature/tidy"], check=True, capture_output=True)
        pr = {"repo": "api", "number": 7, "title": "Tidy the store", "description": "",
              "author": {"id": "maya", "name": "Maya Chen"}, "branch": "feature/tidy", "base": "main",
              "state": "open", "draft": False, "head": head, "reviewers": ["me"], "reviews": [],
              "comments": [], "ci": {"state": "passed"}, "created": "2026-09-28T08:00:00+00:00",
              "updated": "2026-09-28T08:00:00+00:00"}
        (self.home / "host" / "api" / "7.json").write_text(json.dumps(pr))
        scan = self.json_of("review", "scan")
        self.assertEqual(set(scan), {"prs", "open_groups"})
        self.assertEqual(set(scan["prs"][0]), SCAN_KEYS)
        cfg = self.cfg()
        with mock.patch.dict(os.environ, self.environ()):
            board = open_board(cfg)
            try:
                reviewcards.LAST_SCANNED.clear()
                reviewcards.upkeep(cfg, board, {"work"})
                filed = [c for c in board.list_cards(space="work") if c["options"].get("review_key")]
            finally:
                board.close()
        self.assertEqual([c["options"]["review_key"] for c in filed], ["api:7"])
        card_id = filed[0]["id"]
        self.assertEqual(self.json_of("review", card_id, "poll"),
                         {"state": "open", "head": head, "url": "https://code.sandbox.test/api/pull/7"})
        tree = self.adapter("worktree", card_id).strip()
        detached = subprocess.run(["git", "-C", tree, "rev-parse", "--abbrev-ref", "HEAD"],
                                  capture_output=True, text=True).stdout.strip()
        self.assertEqual(detached, "HEAD")
        fence = self.json_of("deny", card_id)
        self.assertIn("Bash(git push:*)", fence)
        self.assertIn("Bash(git commit:*)", fence)


class AnswerTest(SandboxCase):
    """The stateful verbs: a round sent once however often Approve is retried, a review
    posted once, one missing pull request flipping none, and reap keeping what is not its own."""

    def card_with_drafts(self, title: str, repos: str, push: tuple) -> tuple[dict, list[str]]:
        card_id = self.verb("kb", "create", "--space", "work", "--title", title, "--repo", repos,
                            "--autonomy", "autonomous", "--model", "opus").split()[-1]
        trees = self.adapter("worktree", card_id).split()
        card = json.loads(self.verb("kb", "show", card_id, "--json"))
        for tree in trees:
            if Path(tree).parent.name in push:
                self.commit(tree, "change.py")
                subprocess.run(["git", "-C", tree, "push", "-q", "-u", "origin", card["options"]["branch"]],
                               check=True, capture_output=True)
        self.adapter("pr", card_id, "--draft")
        return json.loads(self.verb("kb", "show", card_id, "--json")), trees

    @staticmethod
    def commit(tree: str, name: str) -> str:
        Path(tree, name).write_text(f"# {name}\n")
        subprocess.run(["git", "-C", tree, "add", "."], check=True, capture_output=True)
        subprocess.run(["git", "-C", tree, "commit", "-qm", name], check=True, capture_output=True)
        return subprocess.run(["git", "-C", tree, "rev-parse", "HEAD"], capture_output=True, text=True).stdout.strip()

    def host(self, repo: str, number: int) -> dict:
        return json.loads((self.home / "host" / repo / f"{number}.json").read_text())

    def test_one_missing_pull_request_flips_none(self):
        self.built()
        card, _ = self.card_with_drafts("Half pushed", "api,web", push=("api",))
        refused = in_sandbox(self.home, str(ADAPTER / "publish"), card["id"])
        self.assertEqual(refused.returncode, 1)
        self.assertIn("no pull request in web", refused.stderr)
        self.assertTrue(self.host("api", 1)["draft"])

    def test_ship_pushes_flips_the_draft_and_posts_each_reply_once(self):
        self.built()
        card, trees = self.card_with_drafts("Ship", "api", push=("api",))
        pr = self.host("api", 1)
        tom = {"id": "tom", "name": "Tom Okafor"}
        pr["comments"] += [
            {"id": 900, "author": tom, "at": pr["created"], "path": "change.py", "line": 1, "parent": None,
             "text": "Rename it?"},
            {"id": 901, "author": tom, "at": pr["created"], "path": None, "line": None, "parent": None,
             "text": "Tidy the imports?"},
            {"id": 902, "author": pr["author"], "at": pr["created"], "path": None, "line": None,
             "parent": 901, "text": "Done."},
            {"id": 903, "author": {"id": "ci", "name": "Checks"}, "at": pr["created"], "path": None,
             "line": None, "parent": None, "text": "Build passed", "bot": True}]
        (self.home / "host" / "api" / "1.json").write_text(json.dumps(pr))
        sight = self.json_of("ship", card["id"], "poll")
        self.assertEqual(set(sight), SIGHT_KEYS)
        self.assertEqual(([c["id"] for c in sight["comments"]], sight["draft"]), ([900, 901], True))
        pr = self.host("api", 1)
        pr["comments"][1]["resolved"] = True
        (self.home / "host" / "api" / "1.json").write_text(json.dumps(pr))
        self.assertEqual([c["id"] for c in self.json_of("ship", card["id"], "poll")["comments"]], [900],
                         "a bot and a resolved thread are not review to answer")
        head = self.commit(trees[0], "renamed.py")
        answer = json.dumps({"ship": True, "replies": [{"handle": "c900", "text": "Renamed, thanks."},
                                                       {"handle": "c901", "text": "Done."}]})
        first = self.json_of("publish", card["id"], "--answer", stdin=answer)
        self.assertEqual(set(first), SHIP_KEYS)
        self.assertEqual((first["pushed"], first["ready"], first["posted"], first["shipping"], first["shipped"]),
                         ({"api": head}, ["api"], ["c900"], True, True))
        self.assertEqual([one["handle"] for one in first["sent"]], ["c900", "c901"], "Done. was already said")
        again = self.json_of("publish", card["id"], "--answer", stdin=answer)
        self.assertEqual((again["ready"], again["posted"], len(again["sent"])), ([], [], 2))
        self.assertFalse(self.host("api", 1)["draft"])
        replies = [c for c in self.host("api", 1)["comments"] if c["text"] == "Renamed, thanks."]
        self.assertEqual([(c["parent"], c["author"]["id"]) for c in replies], [(900, "me")])
        method = self.adapter("ship", card["id"], "method")
        self.assertIn("Valid but deferred", method)

    def test_a_review_is_posted_once_however_often_approve_runs(self):
        self.built()
        head = subprocess.run(["git", "-C", str(self.home / "repos" / "api"), "rev-parse", "HEAD"],
                              capture_output=True, text=True).stdout.strip()
        (self.home / "host" / "api" / "3.json").write_text(json.dumps({
            "repo": "api", "number": 3, "title": "Theirs", "description": "", "author": {"id": "maya", "name": "Maya"},
            "branch": "main", "base": "main", "state": "open", "draft": False, "head": head, "reviewers": ["me"],
            "reviews": [], "comments": [], "ci": {"state": "passed"}, "created": "2026-09-28T08:00:00+00:00",
            "updated": "2026-09-28T08:00:00+00:00"}))
        card_id = self.verb("kb", "create", "--space", "work", "--title", "Review: Theirs", "--repo", "api",
                            "--autonomy", "autonomous", "--model", "opus", "--option", "review_key=api:3",
                            "--option", "pr=3").split()[-1]
        answer = json.dumps({"review": {"round": 1, "head": head, "verdict": "changes", "summary": "One thing.",
                                        "comments": [{"row": "r1-f1", "path": "reports/app.py", "line": 3,
                                                      "text": "Could this be tested?"}], "ledger": []}})
        for _ in range(2):
            posted = self.json_of("publish", card_id, "--answer", stdin=answer)
        self.assertEqual((posted["comments"], posted["verdict"]), (1, "changes"))
        pr = self.host("api", 3)
        self.assertEqual(sorted(c["text"] for c in pr["comments"]), ["Could this be tested?", "One thing."])
        self.assertEqual([r["state"] for r in pr["reviews"]], ["changes_requested"])

    def test_reap_removes_its_worktree_and_keeps_anything_else(self):
        self.built()
        card, trees = self.card_with_drafts("Reap", "api,web", push=("api", "web"))
        other = Path(self.tmp.name) / "not-a-worktree"
        other.mkdir()
        self.verb("kb", "set", card["id"], "options.worktrees=" + json.dumps(
            {"api": trees[0], "web": str(other)}))
        reaped = self.json_of("ship", card["id"], "reap")
        self.assertEqual(reaped["removed"], [trees[0]])
        self.assertEqual([k["path"] for k in reaped["kept"]], [str(other)])
        self.assertTrue(other.exists())
        self.verb("kb", "set", card["id"], "options.worktrees=" + json.dumps(
            {"api": str(self.home / "repos" / "api"), "web": str(other)}))
        again = self.json_of("ship", card["id"], "reap")
        self.assertEqual(again["removed"], [])
        self.assertTrue((self.home / "repos" / "api" / ".git").exists())

    def test_a_ship_on_a_worktree_astray_pushes_and_posts_nothing(self):
        self.built()
        card, trees = self.card_with_drafts("Astray", "api", push=("api",))
        subprocess.run(["git", "-C", trees[0], "checkout", "-q", "-b", "elsewhere"], check=True, capture_output=True)
        self.commit(trees[0], "stray.py")
        answer = json.dumps({"ship": True, "replies": [{"handle": "general", "text": "Done."}]})
        refused = in_sandbox(self.home, str(ADAPTER / "publish"), card["id"], "--answer", stdin=answer)
        self.assertEqual(refused.returncode, 1)
        self.assertIn("nothing was pushed", refused.stderr)
        self.assertEqual(self.host("api", 1)["comments"], [])

    def test_ship_goes_by_the_remote_s_head_not_a_stale_recorded_one(self):
        """c-653: the branch was rewritten outside Shipyard. Diverged, nothing leaves; replayed
        onto it by hand, the Ship is a fast-forward and the stale recorded head refuses nothing."""
        self.built()
        card, trees = self.card_with_drafts("Rewritten", "api", push=("api",))
        tree = trees[0]

        def git(*args):
            return subprocess.run(["git", "-C", tree, "-c", "user.name=t", "-c", "user.email=t@example.invalid", *args],
                                  check=True, capture_output=True, text=True).stdout.strip()

        branch, recorded = git("rev-parse", "--abbrev-ref", "HEAD"), git("rev-parse", "HEAD")
        git("checkout", "-q", "--detach")
        git("commit", "-q", "--amend", "-m", "the same work, rewritten elsewhere")
        git("push", "-q", "-f", "origin", f"HEAD:{branch}")
        git("checkout", "-q", branch)
        self.commit(tree, "own.py")
        answer = json.dumps({"ship": True, "lease": {"api": recorded},
                             "replies": [{"handle": "general", "text": "Done."}]})
        refused = in_sandbox(self.home, str(ADAPTER / "publish"), card["id"], "--answer", stdin=answer)
        self.assertEqual(refused.returncode, 1)
        self.assertIn("diverged", refused.stderr)
        self.assertEqual(self.host("api", 1)["comments"], [])
        git("rebase", "-q", "--onto", f"origin/{branch}", recorded)
        shipped = self.json_of("publish", card["id"], "--answer", stdin=answer)
        self.assertEqual((shipped["pushed"], shipped["posted"]), ({"api": git("rev-parse", "HEAD")}, ["general"]))

    def test_every_worktree_is_looked_at_before_any_is_pushed(self):
        """c-653 review (r4.F8): two repos. One to push and one the remote is ahead of: one
        pushed, one skipped. One to push and one diverged: nothing pushed anywhere, no reply."""
        self.built()
        card, trees = self.card_with_drafts("Two", "api,web", push=("api", "web"))
        api, web = trees
        branch = card["options"]["branch"]

        def git(tree, *args):
            return subprocess.run(["git", "-C", tree, "-c", "user.name=t", "-c", "user.email=t@example.invalid", *args],
                                  check=True, capture_output=True, text=True).stdout.strip()

        def on_the_remote(tree):
            return git(tree, "ls-remote", "origin", f"refs/heads/{branch}").split()[0]

        # web: a colleague's commit on the remote that the worktree lacks
        git(web, "checkout", "-q", "--detach")
        self.commit(web, "theirs.py")
        git(web, "push", "-q", "origin", f"HEAD:{branch}")
        git(web, "checkout", "-q", branch)
        mine = self.commit(api, "mine.py")
        answer = json.dumps({"ship": True, "replies": [{"handle": "general", "text": "Done."}]})
        shipped = self.json_of("publish", card["id"], "--answer", stdin=answer)
        self.assertEqual((shipped["pushed"], shipped["skipped"], shipped["posted"]), ({"api": mine}, ["web"], ["general"]))
        # now web commits on its old history (diverged) while api has one more to push
        self.commit(web, "own.py")
        self.commit(api, "more.py")
        before = on_the_remote(api), on_the_remote(web)
        answer = json.dumps({"ship": True, "replies": [{"handle": "general", "text": "Done again."}]})
        refused = in_sandbox(self.home, str(ADAPTER / "publish"), card["id"], "--answer", stdin=answer)
        self.assertEqual(refused.returncode, 1)
        self.assertIn("diverged", refused.stderr)
        self.assertEqual((on_the_remote(api), on_the_remote(web)), before, "api's push did not go either")
        self.assertNotIn("Done again.", [c["text"] for c in self.host("api", 1)["comments"]])

    def test_a_branch_ahead_of_origin_is_not_publishable(self):
        self.built()
        card, trees = self.card_with_drafts("Ahead", "api", push=("api",))
        self.commit(trees[0], "later.py")
        said = self.json_of("publishable", card["id"])
        self.assertFalse(said["publishable"])
        self.assertIn("has commits origin does not", said["missing"])

    def test_a_feature_review_posts_each_members_own_findings_and_verdict_once(self):
        self.built()
        heads = {}
        for repo, number in (("api", 4), ("web", 5)):
            heads[repo] = subprocess.run(["git", "-C", str(self.home / "repos" / repo), "rev-parse", "HEAD"],
                                         capture_output=True, text=True).stdout.strip()
            (self.home / "host" / repo / f"{number}.json").write_text(json.dumps({
                "repo": repo, "number": number, "title": "One story", "description": "",
                "author": {"id": "maya", "name": "Maya"}, "branch": "main", "base": "main", "state": "open",
                "draft": False, "head": heads[repo], "reviewers": ["me"], "reviews": [], "comments": [],
                "ci": {"state": "passed"}, "created": "2026-09-28T08:00:00+00:00", "updated": "2026-09-28T08:00:00+00:00"}))
        card_id = self.verb("kb", "create", "--space", "work", "--title", "Review: One story", "--repo", "api,web",
                            "--autonomy", "autonomous", "--model", "opus", "--option", "review_key=feature:st-7").split()[-1]
        members = [{"member": "api#4", "repo": "api", "pr": 4, "verdict": "changes",
                    "comments": [{"row": "r1-f1", "path": "reports/app.py", "line": 3, "text": "Test this?"}]},
                   {"member": "web#5", "repo": "web", "pr": 5, "verdict": "approve", "comments": []}]
        answer = json.dumps({"review": {"round": 1, "head": heads["api"], "verdict": "changes", "summary": "Both.",
                                        "members": members, "ledger": []}})
        for _ in range(2):
            posted = self.json_of("publish", card_id, "--answer", stdin=answer)
        self.assertEqual((posted["prs"], posted["comments"]), ([4, 5], 1))
        api, web = self.host("api", 4), self.host("web", 5)
        self.assertEqual(sorted(c["text"] for c in api["comments"]), ["Both.", "Test this?"])
        self.assertEqual([c["text"] for c in web["comments"]], ["Both."])
        self.assertEqual(([r["state"] for r in api["reviews"]], [r["state"] for r in web["reviews"]]),
                         (["changes_requested"], ["approved"]))


class BriefTest(unittest.TestCase):
    """The brief's endings and the fence, from the card alone (`sb_brief`, no sandbox)."""

    def setUp(self):
        sys.path.insert(0, str(ADAPTER))
        self.addCleanup(sys.path.remove, str(ADAPTER))
        import sb_brief  # noqa: PLC0415 - the adapter's own module
        self.brief = sb_brief
        patch = mock.patch.object(sb_brief, "card_dir", lambda card_id: Path("/cards") / card_id)
        patch.start()
        self.addCleanup(patch.stop)

    def card(self, **options) -> dict:
        return {"id": "c-9300", "title": "Export", "repo": "api", "options": {"branch": "feature/x", **options}}

    def test_a_build_pushes_and_opens_drafts_and_its_fence_is_empty(self):
        text = self.brief.compose(self.card(), ["/w/api"])
        self.assertIn("git push -u origin feature/x", text)
        self.assertIn("packs/sandbox/pr c-9300", text)
        self.assertEqual(self.brief.deny_for(self.card()), [])

    def test_a_house_at_shipping_never_pushes_and_is_fenced_from_it(self):
        card = dict(self.card(), stage="shipping")
        text = self.brief.compose(card, ["/w/api"])
        self.assertIn("kb verdict c-9300", text)
        self.assertIn("never push", text)
        self.assertNotIn("replies-", text)
        self.assertIn("Bash(git push:*)", self.brief.deny_for(card))
        self.assertIn("Valid but deferred", self.brief.METHOD)

    def test_research_commits_nothing_and_is_fenced_from_the_push(self):
        card = self.card(kind="research")
        self.assertIn("Never commit or push", self.brief.compose(card, ["/w/api"]))
        self.assertIn("Bash(*adapters/sandbox/publish*)", self.brief.deny_for(card))


class RefusalTest(SandboxCase):
    """The adapter and the seed hold themselves to the sandbox, not only through `run`."""

    def test_a_verb_and_the_seed_refuse_a_sandbox_the_loaded_toml_is_not(self):
        self.built()
        env = {key: value for key, value in os.environ.items() if key != "KEEL_CONFIG"}
        env.update(KEEL_SANDBOX=str(self.home), KEEL_HOME=str(ROOT), KEEL_HOST="box")
        for argv in ([str(ADAPTER / "review"), "scan"], [str(ROOT / "demo" / "seed"), "morning"]):
            done = subprocess.run(argv, capture_output=True, text=True, env=env)
            self.assertNotEqual(done.returncode, 0, argv)
            self.assertIn("KEEL_CONFIG", done.stderr + done.stdout)
        self.assertEqual(list((self.home / "host" / "api").iterdir()), [])

    def test_run_refuses_a_board_with_a_card_below_the_floor(self):
        self.built()
        cfg = self.cfg()
        with mock.patch.dict(os.environ, self.environ()):
            board = open_board(cfg)
            try:
                board.insert_card({"id": "c-042", "space": "work", "title": "Low", "stage": "inbox",
                                   "autonomy": "autonomous", "options": {}}, "cli")
            finally:
                board.close()
        self.assertIn("below c-9000", in_sandbox(self.home, "kb", "list").stderr)

    def test_setup_refuses_a_port_that_puts_voice_or_lavish_on_a_live_one(self):
        taken = subprocess.run([sys.executable, str(SETUP), "--home", str(self.home), "--port", "8793"],
                               capture_output=True, text=True)
        self.assertIn("live port (4390)", taken.stderr)


class SeedTest(SandboxCase):
    def test_a_phase_stopped_halfway_is_finished_by_the_next_run(self):
        self.built()
        half = in_sandbox(self.home, sys.executable, "-c", (
            f"import sys; sys.path.insert(0, {str(ROOT / 'demo')!r});"
            "from seeding import phases; from seeding.day import Day;"
            "d = Day(); cid = phases.filed(d, 'work', phases.SEARCH_TITLE, repo='api', autonomy='autonomous');"
            "d.board.stage(cid, 'assigned', 'cli'); print(cid)"))
        self.assertEqual(half.returncode, 0, half.stderr)
        done = in_sandbox(self.home, str(ROOT / "demo" / "seed"), "morning")
        self.assertEqual(done.returncode, 0, done.stderr)
        self.assertIn(f"{half.stdout.strip()}  work     done", self.verb("kb", "list", "--all"))

    def test_the_seeded_day_ends_with_nothing_waiting_and_the_export_card_shipping(self):
        self.built()
        done = in_sandbox(self.home, str(ROOT / "demo" / "seed"), "all")
        self.assertEqual(done.returncode, 0, done.stderr)
        said = json.loads(done.stdout)
        self.assertEqual(self.verb("kb", "needs-you").strip(), "")
        shipping = self.verb("kb", "list", "--stage", "shipping")
        self.assertIn("Add CSV export to the reports page", shipping)
        posted = json.loads((self.home / "host" / "api" / "12.json").read_text())
        self.assertEqual([c["line"] for c in posted["comments"] if c["path"]], [9, 15])
        self.assertEqual([r["state"] for r in posted["reviews"]], ["changes_requested"])
        self.assertEqual(said["breaks"]["ask"], "a-1")
        search_fix = json.loads((self.home / "host" / "api" / "11.json").read_text())
        self.assertEqual((search_fix["title"], search_fix["state"]), ("bug: Fix search ignoring case [st-98]", "merged"))
        # the five parallel cards (c-807): worked all day as board state, all done or shipping
        # by evening, and the export card's drafts numbered after the morning's reviews
        rows = [line.split(None, 3) for line in self.verb("kb", "list", "--all").splitlines()]
        stage = {row[3]: row[2] for row in rows if len(row) == 4}
        ids = {row[3]: row[0] for row in rows if len(row) == 4}
        five = ("Add a dark theme to the reports page", "Email a weekly reports digest",
                "Fix totals rounding on large reports", "Review: Add an owner filter to /reports",
                "Review: Show an empty state when no report matches")
        self.assertEqual([stage[t] for t in five], ["shipping", "shipping", "done", "done", "done"])
        # never a house: no session on any of the five, so the drain never started one
        sessions = {t: json.loads(self.verb("kb", "show", ids[t], "--json")).get("session_id") for t in five}
        self.assertEqual(sessions, dict.fromkeys(five))
        # the numbers the film's overlays name (demo/video/src/cut.js): the fix card, both drafts
        self.assertEqual(said["breaks"]["fix"], "c-9218")
        for repo, number in (("api", 14), ("web", 33)):
            draft = json.loads((self.home / "host" / repo / f"{number}.json").read_text())
            self.assertTrue(draft["title"].startswith("feature: Add CSV export"), (repo, draft["title"]))
        again = in_sandbox(self.home, str(ROOT / "demo" / "seed"), "all")
        self.assertEqual(again.returncode, 0, again.stderr)
        self.assertEqual(json.loads(again.stdout)["breaks"]["ask"], "a-1")


class WordsTest(unittest.TestCase):
    @staticmethod
    def demo_texts() -> dict[str, str]:
        """Every text file git would carry under the adapter and demo/, as `make drift` reads
        them: tracked or untracked-but-not-ignored, so the edit's node_modules/, its rendered
        media and its public/ copies never count, and binary files (the music) are skipped."""
        listed = subprocess.run(["git", "ls-files", "-co", "--exclude-standard", "--", "packs/sandbox", "demo"],
                                cwd=ROOT, capture_output=True, text=True, check=True).stdout.split()
        texts = {}
        for name in listed:
            try:
                texts[name] = (ROOT / name).read_bytes().decode("utf-8")
            except (UnicodeDecodeError, FileNotFoundError):
                continue
        return texts

    def test_nothing_the_demo_shows_names_the_employer(self):
        terms = packs.configured_drift_terms(ROOT)     # the install's too (r1.F7)
        if not terms:
            self.skipTest("no pack here carries a drift-terms list: none in the tree, and no "
                          "install named whose packs carry one")
        pattern = re.compile("|".join(f"(?:{term})" for term in terms), re.I)
        texts = self.demo_texts()
        self.assertEqual([name for name, text in texts.items() if pattern.search(text)], [])
        self.assertGreater(len(texts), 10)

    def test_nothing_the_demo_shows_carries_an_em_dash(self):
        texts = self.demo_texts()
        self.assertEqual([name for name, text in texts.items() if chr(0x2014) in text], [])
        if (ROOT / "demo" / "video").is_dir():        # the public release leaves it out (c-804)
            self.assertIn("demo/video/src/cut.js", texts)


if __name__ == "__main__":
    unittest.main()
