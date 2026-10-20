"""What came back from Bosun (keel/tierdrafts.py, c-678): one row per CLAUDE.md of a space,
its state read from the tier and from the draft card's stage, the draft's text and the lines
Keel reads from it once it is ready, and the first-run step that follows them. On a real
scratch install from `shipyard init`, with a local bare repo as the repo's address."""

import os
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from keel import actions, firstrun, onboarding, readiness, tierdrafts
from keel import config as config_module
from keel.board import open_board
from tests.helpers import no_real_tools
from tests.test_installer import init

DRAFT = """# api: how to work in this repo

## Prepare and test
- Prepare a fresh copy: `npm ci`
- Run the tests: `npm test` (about 40 seconds)

## Where work lands
- Finished work lands on `main`.

## Running the app
- Sessions run tests only until this section says how to run the app.
"""


class DraftsTest(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        patch = mock.patch.dict(os.environ)
        patch.start()
        self.addCleanup(patch.stop)
        no_real_tools(self)
        readiness.forget()
        self.addCleanup(readiness.forget)
        gather = mock.patch("keel.prereqs.gather", return_value=[])
        gather.start()
        self.addCleanup(gather.stop)
        # the report reads the machine's readiness too: the phone row never asks the real tool
        phone = mock.patch("keel.readiness.serve_status", return_value={"missing": True})
        phone.start()
        self.addCleanup(phone.stop)
        self.home = Path(tmp.name).resolve() / "install"
        self.assertEqual(init(self.home), 0)

    def cfg(self):
        return config_module.load(self.home / "config.toml", ensure=False)

    def bare(self, name="origin") -> Path:
        work, origin = self.home.parent / f"{name}-work", self.home.parent / f"{name}.git"
        subprocess.run(["git", "init", "-q", "--bare", "-b", "main", str(origin)], check=True)
        subprocess.run(["git", "init", "-q", str(work)], check=True)
        (work / "README").write_text("hello\n")
        for argv in (["add", "."], ["-c", "user.name=t", "-c", "user.email=t@example.com", "commit", "-qm", "one"],
                     ["push", "-q", str(origin), "HEAD:main"]):
            subprocess.run(["git", "-C", str(work), *argv], check=True)
        return origin

    def add(self, key="api"):
        cfg = self.cfg()
        with open_board(cfg) as board:
            return actions.act(cfg, board, {"verb": "setup.repo.add", "space": "work", "url": str(self.bare(key)), "key": key})

    def rows(self, full=True):
        cfg = self.cfg()
        with open_board(cfg) as board:
            return tierdrafts.rows(cfg, board, "work", full=full)

    def drafted(self, card: str, text: str = DRAFT):
        """Bosun's two moves on a draft card: building, then review with the draft written."""
        cfg = self.cfg()
        out = self.home / "builder" / "cards" / card / "claude-md.md"
        with open_board(cfg) as board:
            board.stage(card, "building", "bosun")
            out.parent.mkdir(parents=True, exist_ok=True)
            out.write_text(text)
            board.stage(card, "review", "bosun", output_ref=str(out))
        return out

    def test_a_copied_repo_is_a_row_that_has_not_started(self):
        card = self.add()["draft"]
        [row] = self.rows()
        self.assertEqual((row["aim"], row["label"], row["state"], row["card"]),
                         ("work/api", "api/CLAUDE.md", "idle", card))
        self.assertEqual(row["path"], str(self.home / "spaces" / "work" / "api" / "CLAUDE.md"))
        self.assertEqual((row["text"], row["commands"]), (None, None))

    def test_the_rows_state_follows_bosuns_moves_on_the_card(self):
        card = self.add()["draft"]
        cfg = self.cfg()
        with open_board(cfg) as board:
            board.stage(card, "building", "bosun")
        self.assertEqual(self.rows()[0]["state"], "drafting")
        self.drafted_after_building(card)
        [row] = self.rows()
        self.assertEqual(row["state"], "ready")
        self.assertEqual(row["text"], DRAFT)
        self.assertEqual(row["commands"]["prepare"], {"value": "npm ci", "line": 4})
        self.assertEqual(row["commands"]["test"], {"value": "npm test", "line": 5})
        self.assertEqual(row["commands"]["lands"], {"value": "main", "line": 8})

    def drafted_after_building(self, card):
        cfg = self.cfg()
        out = self.home / "builder" / "cards" / card / "claude-md.md"
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(DRAFT)
        with open_board(cfg) as board:
            board.stage(card, "review", "bosun", output_ref=str(out))

    def test_an_adopted_row_shows_the_file_and_its_commands(self):
        card = self.add()["draft"]
        self.drafted(card)
        cfg = self.cfg()
        with open_board(cfg) as board:
            actions.act(cfg, board, {"verb": "setup.tier.adopt", "card": card})
        [row] = self.rows()
        self.assertEqual((row["state"], row["card"], row["text"]), ("adopted", None, DRAFT))
        self.assertEqual(row["commands"]["test"]["value"], "npm test")

    def test_the_light_rows_carry_no_text_and_a_stamp_that_moves_with_the_draft(self):
        """The state document carries these on every poll: states only, and a stamp the page
        compares, so it reads the report again when a draft changed."""
        card = self.add()["draft"]
        out = self.drafted(card)
        os.utime(out, (1_700_000_000, 1_700_000_000))
        [row] = self.rows(full=False)
        self.assertEqual((row["state"], row["stamp"]), ("ready", 1_700_000_000))
        self.assertNotIn("text", row)
        os.utime(out, (1_700_000_600, 1_700_000_600))
        self.assertEqual(self.rows(full=False)[0]["stamp"], 1_700_000_600)

    def test_a_row_with_no_card_gets_one_by_the_users_tap(self):
        card = self.add()["draft"]
        cfg = self.cfg()
        with open_board(cfg) as board:
            board.set_fields(card, {"options": {"archived": True}}, "human")
            self.assertIsNone(tierdrafts.rows(cfg, board, "work")[0]["card"])
            made = actions.act(cfg, board, {"verb": "setup.tier.draft", "space": "work", "key": "api"})
            self.assertEqual(tierdrafts.rows(cfg, board, "work")[0]["card"], made["card"])
            with self.assertRaisesRegex(actions.ActionError, "already has an open draft"):
                actions.act(cfg, board, {"verb": "setup.tier.draft", "space": "work", "key": "api"})

    # ----- the workspace file, with more than one repo (c-678 step 9) -----

    def test_a_second_repo_brings_the_workspace_row_and_its_draft_card(self):
        self.assertIsNone(self.add("api").get("workspace"))
        self.assertEqual([row["label"] for row in self.rows()], ["api/CLAUDE.md"])
        card = self.add("web")["workspace"]
        rows = self.rows()
        self.assertEqual([row["label"] for row in rows], ["api/CLAUDE.md", "web/CLAUDE.md", "CLAUDE.md (workspace)"])
        last = rows[-1]
        self.assertEqual((last["aim"], last["state"], last["card"], last["path"]),
                         ("work", "idle", card, str(self.home / "spaces" / "work" / "CLAUDE.md")))
        cfg = self.cfg()
        with open_board(cfg) as board:
            found = board.get(card)
        self.assertEqual((found["title"], found["stage"]), ("Draft the work CLAUDE.md", "inbox"))
        for key in ("api", "web"):
            self.assertIn(str(self.home / "spaces" / "work" / key / "repo"), found["brief"])
        self.assertIn("how the repos fit together", found["brief"])
        self.assertIsNone(self.add("docs").get("workspace"), "one workspace card, not one per repo")

    def test_the_workspace_draft_is_adopted_into_the_space_file_and_shows_no_commands(self):
        self.add("api")
        card = self.add("web")["workspace"]
        self.drafted(card, "# work: how the repos fit together\n\n- api serves the data. web reads it.\n")
        last = self.rows()[-1]
        self.assertEqual((last["state"], last["commands"]), ("ready", None))
        cfg = self.cfg()
        with open_board(cfg) as board:
            actions.act(cfg, board, {"verb": "setup.tier.adopt", "card": card})
        self.assertEqual((self.home / "spaces" / "work" / "CLAUDE.md").read_text(),
                         "# work: how the repos fit together\n\n- api serves the data. web reads it.\n")
        self.assertEqual(self.rows()[-1]["state"], "adopted")
        # a third repo opens a new workspace card: until Bosun takes it the file is still adopted
        self.assertIsNotNone(self.add("docs")["workspace"])
        self.assertEqual((self.rows()[-1]["state"], self.rows()[-1]["card"]), ("adopted", None))

    def test_the_workspace_file_is_not_required_for_the_step(self):
        self.add("api")
        self.add("web")
        found = [dict(row, state="adopted") if row["label"] != tierdrafts.WORKSPACE else row for row in self.rows()]
        self.assertEqual(tierdrafts.verdict(found), (True, "every repo's CLAUDE.md is adopted"))

    def test_the_step_is_done_once_every_copied_repos_file_is_adopted(self):
        cfg = self.cfg()
        with open_board(cfg) as board:
            step = next(s for s in firstrun.report(cfg, board)["steps"] if s["id"] == "rules")
        self.assertEqual((step["done"], step["why"]), (False, "add a repo first: Bosun drafts a CLAUDE.md for each"))
        card = self.add()["draft"]
        readiness.forget()
        cfg = self.cfg()
        with open_board(cfg) as board:
            step = next(s for s in firstrun.report(cfg, board)["steps"] if s["id"] == "rules")
            self.assertEqual((step["done"], step["why"]), (False, "api/CLAUDE.md is not adopted yet"))
            self.assertEqual([(row["aim"], row["state"]) for row in step["drafts"]], [("work/api", "idle")])
        self.drafted(card)
        with open_board(cfg) as board:
            actions.act(cfg, board, {"verb": "setup.tier.adopt", "card": card})
            readiness.forget()
            step = next(s for s in firstrun.report(cfg, board)["steps"] if s["id"] == "rules")
        self.assertEqual((step["done"], step["why"]), (True, "every repo's CLAUDE.md is adopted"))


if __name__ == "__main__":
    unittest.main()
