"""`bin/keel-plan-install` (P4-9) on a scratch store: a card at review with a lavish plan
and a markdown record is given its converted plan and outcome, the way c-272 will be.

Through the real `kb` and `keel board`, with a scratch `keel.toml`, so the pushes, the lint
and the note are the verbs the planner's run will make.
"""

import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from keel import boards, planformat, planinstall
from keel.board import Board
from tests.helpers import make_config

ROOT = Path(__file__).resolve().parent.parent

PLAN = """---
kind: plan
card: c-900
title: Replay a day
repo: keel
---
# c-900 Replay a day

He is deciding how a stored day is replayed.

## Goal

A replay of one day.

## Now

Nothing replays.

## Target

A day replays.

```board Why nothing fires today
b-003
```

## Proposal

Read the day back.

## Decisions

```decision scope
q: Which account?
option sandbox: Sandbox only
  gets: safe
  cost: less real
option any: Any account
  gets: real
  cost: risky
rec: sandbox
because: nothing real is touched
```

## Risks

- A day too long: capped.

## Steps

- Read it.

## Proof

- A test.

## Out of scope

- Live data.
"""

CONTEXT = """---
kind: outcome
card: c-900
title: Replay a day
---
# c-900 Replay a day

## Where it stands

Built.

```board The walk
b-001
```

## What is next

Review.

## Why this shape

Small.

## Open questions

- Ship it? Recommend: yes.

## Evidence

The flow, again:

```board Where it runs
b-002
```

## PR body

````copy PR body
## Intent
Replay a day.

```sql
SELECT 1;
```
````
"""

FLOW = 'board "Why nothing fires today"\nnode a laptop "the day"\nnode b server "the replay"\nedge a -> b\n'


class InstallCase(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.dir = Path(tmp.name)
        self.cfg = make_config(self.dir)
        self.board = Board(self.cfg.db_path)
        self.addCleanup(self.board.close)
        self.card = self.board.create("personal", "replay a day", repo="keel", autonomy="attended",
                                      actor="human")
        self.card_dir = self.cfg.card_dir(self.card)
        self.card_dir.mkdir(parents=True, exist_ok=True)
        self.lavish = self.card_dir / "plan.html"
        self.lavish.write_text("<p>the old plan</p>")
        (self.card_dir / "context.md").write_text("## Where it stands\n\nthe old record\n")
        self.board.stage(self.card, "assigned", "human")
        self.board.stage(self.card, "planning", "drain", plan_ref=str(self.lavish))
        self.board.approve(self.card, "plan", "human")
        self.board.stage(self.card, "review", "house", output_ref="x")
        # The card's own boards, as c-272 has b-006 and b-009: two, plus one of another card.
        boards.push(self.cfg, 'board "Other card"\nnode z box "z"', card="c-999")
        boards.push(self.cfg, 'board "The walk"\nnode w laptop "walk"', card=self.card, new=True)
        boards.push(self.cfg, 'board "Where it runs"\nnode r server "runs"', card=self.card, new=True)
        self.inputs = self.dir / "inputs"
        self.inputs.mkdir()
        (self.inputs / "plan.md").write_text(PLAN)
        (self.inputs / "context.md").write_text(CONTEXT)
        (self.inputs / "flow-1.txt").write_text(FLOW)
        self.verbs = planinstall.Verbs(env=self.env())

    def env(self) -> dict:
        toml = self.dir / "keel.toml"
        toml.write_text("[keel]\n"
                        f'state_dir = "{self.cfg.state_dir}"\n'
                        f'segments_dir = "{self.cfg.segments_dir}"\n'
                        f'adapters_dir = "{self.cfg.adapters_dir}"\n'
                        "serve_port = 8791\n"
                        "[spaces.personal]\n"
                        f'config_dir = "{self.dir / "cfg-personal"}"\n'
                        'contract = "etc/space-personal.md"\n')
        env = dict(os.environ, KEEL_HOME=str(ROOT), KEEL_CONFIG=str(toml))
        for name in ("KEEL_URL", "KEEL_CARD", "KEEL_TOKEN"):
            env.pop(name, None)
        return env

    def run_install(self, *extra) -> tuple[int, str, str]:
        argv = [self.card, "--plan", str(self.inputs / "plan.md"),
                "--context", str(self.inputs / "context.md"),
                "--board", f"b-003={self.inputs / 'flow-1.txt'}",
                "--reuse", "b-001=b-002", "--reuse", "b-002=b-003",
                "--card-dir", str(self.card_dir), *extra]
        done = subprocess.run([sys.executable, str(ROOT / "bin" / "keel-plan-install"), *argv],
                              capture_output=True, text=True, env=self.verbs.env, timeout=120)
        return done.returncode, done.stdout, done.stderr


class DryRunTest(InstallCase):
    def test_a_dry_run_prints_every_step_and_changes_nothing(self):
        code, out, err = self.run_install("--dry-run")
        self.assertEqual(code, 0, err)
        self.assertIn("dry run, nothing changed", out)
        self.assertIn("keel board push --card " + self.card + " --new", out)
        self.assertIn("reuse b-002 for b-001", out)
        self.assertIn("plan.html.lavish", out)
        self.assertIn("context.md.pre-format", out)
        self.assertEqual(len(boards.records(self.cfg)), 3, "nothing was pushed")
        self.assertTrue(self.lavish.is_file())
        self.assertIn("the old record", (self.card_dir / "context.md").read_text())
        self.assertEqual(self.board.get(self.card)["plan_ref"], str(self.lavish))


class InstallTest(InstallCase):
    def test_boards_pushed_and_reused_ids_rewritten_files_kept_and_one_note(self):
        code, out, err = self.run_install()
        self.assertEqual(code, 0, err)
        done = json.loads(out)
        self.assertEqual(done["ids"], {"b-003": "b-004", "b-001": "b-002", "b-002": "b-003"})
        pushed = boards.read_record(self.cfg, "b-004")
        self.assertEqual((pushed["source"]["card"], pushed["title"]), (self.card, "Why nothing fires today"))
        plan = (self.card_dir / "plan.md").read_text()
        context = (self.card_dir / "context.md").read_text()
        self.assertEqual(self.embedded(plan), ["b-004"])
        self.assertEqual(self.embedded(context), ["b-002", "b-003"])
        self.assertIn(f"card: {self.card}", plan)
        self.assertIn(f"# {self.card} Replay a day", context)
        self.assertEqual((self.card_dir / "plan.html.lavish").read_text(), "<p>the old plan</p>")
        self.assertIn("the old record", (self.card_dir / "context.md.pre-format").read_text())
        self.assertFalse(self.lavish.exists())
        card = self.board.get(self.card)
        self.assertEqual(card["plan_ref"], str(self.card_dir / "plan.md"))
        notes = [e["text"] for e in self.board.events(self.card) if e["kind"] == "note"]
        self.assertEqual(len([n for n in notes if n.startswith("plan pages installed")]), 1, notes)
        self.assertEqual(card["stage"], "review", "the card is not moved")

    def test_an_id_that_is_neither_pushed_nor_the_cards_is_refused_before_anything(self):
        code, _, err = self.run_install("--reuse", "b-009=b-001")
        self.assertEqual(code, 1)
        self.assertIn("b-001 is not one of", err)
        self.assertEqual(len(boards.records(self.cfg)), 3)
        self.assertTrue(self.lavish.is_file())

    def test_a_document_that_would_not_lint_pushes_nothing(self):
        (self.inputs / "plan.md").write_text(PLAN.replace("rec: sandbox\n", ""))
        code, _, err = self.run_install()
        self.assertEqual(code, 1)
        self.assertIn("C12", err)
        self.assertEqual(len(boards.records(self.cfg)), 3)

    def test_the_installed_outcome_keeps_the_pr_body_whole(self):
        """c-272's Approve publishes through the space's pack, which reads the draft's body
        from the outcome; the install keeps that body whole. How a pack reads it is the
        pack's own suite's to hold (c-722: the core suite needs no pack of anyone's own)."""
        self.assertEqual(self.run_install()[0], 0)
        self.assertIn("## Intent\nReplay a day.\n\n```sql\nSELECT 1;\n```",
                      (self.card_dir / "context.md").read_text())

    def test_a_board_that_attaches_a_file_is_pushed_from_the_card_s_worktree(self):
        """A `path` op reads its file relative to where the push runs, and a house pushes
        from its worktree; the installer did it from ~/keel, so c-017's boards (2026-09-25)
        failed with "not a file on this machine". It pushes from `--root` now."""
        tree = self.dir / "worktree"
        (tree / "app").mkdir(parents=True)
        (tree / "app" / "routes.py").write_text("x = 1\n")
        (self.inputs / "flow-1.txt").write_text(FLOW + 'path b "app/routes.py" size "1 KB" from HEAD\n')
        code, out, err = self.run_install("--root", str(tree))
        self.assertEqual(code, 0, err)
        pushed = json.loads(out)["ids"]["b-003"]
        self.assertIn("app/routes.py", json.dumps(boards.read_record(self.cfg, pushed)))

    @staticmethod
    def embedded(text: str) -> list[str]:
        return [b["ref"] for b in planformat.all_blocks(planformat.parse(text)["blocks"])
                if b["type"] == "board" and b.get("ref")]


class RewriteTest(unittest.TestCase):
    def test_only_a_board_fence_line_is_rewritten(self):
        text = "b-003 in prose\n```board t\nb-3\n```\n```text\nb-003\n```\n"
        out = planinstall.rewrite(text, {"b-003": "b-010"}, None, "c-1")
        self.assertEqual(out, "b-003 in prose\n```board t\nb-010\n```\n```text\nb-003\n```\n")


if __name__ == "__main__":
    unittest.main()
