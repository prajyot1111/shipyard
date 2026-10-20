"""c-551: a card reaches his outcome gate only when his Approve could publish it.

`kb stage <id> review` asks the space's adapter `publishable <id>` (the card on stdin) on the
machine `kb` runs on, before the move is written or sent. The adapter here is a stub, so the
test is about Keel's half: ask it, refuse with its line, and never ask when there is nothing
to ask. The work adapter's own answer is `packs/work/tests/test_readiness.py`.
"""

import json
import sqlite3
from pathlib import Path

from keel import actions, adapters, plangate
from keel import config as config_module
from keel.board import Refused
from tests.helpers import make_config
from tests.test_cli import KbCase

MISSING = "c-001 is not publishable: branch b is not on origin. push first, then `pr c-001 --draft`"


def stub(directory: Path, body: str) -> Path:
    """`adapters/work/publishable` as a shell stub that also records the card it was handed."""
    path = directory / "adapters" / "work" / "publishable"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(f"#!/bin/sh\ncat > {directory}/asked.json\n{body}\n")
    path.chmod(0o755)
    return path


class WorkCardCase(KbCase):
    def work_card(self) -> str:
        code, out, err = self.kb("create", "--space", "work", "--title", "Thing", "--repo", "api",
                                 "--autonomy", "autonomous")
        self.assertEqual(code, 0, err)
        card_id = out.split()[0]
        self.assertEqual(self.kb("set", card_id, "plan_ref=/plans/plan.md")[0], 0)
        self.assertEqual(self.kb("stage", card_id, "building")[0], 0)
        return card_id

    def stage_review(self, card_id):
        return self.kb("stage", card_id, "review", "--output", "branch")

    def stage_of(self, card_id):
        return self.kb_json("show", card_id)["stage"]


class StageTest(WorkCardCase):
    def test_an_unpublishable_card_does_not_reach_his_gate(self):
        """The reproduction: before c-551 this move was written and the card sat at review."""
        stub(self.dir, f"echo '{json.dumps({'publishable': False, 'missing': MISSING})}'")
        card_id = self.work_card()
        code, _, err = self.stage_review(card_id)
        self.assertEqual(code, 1)
        self.assertIn("is not on origin", err)
        self.assertIn("pr c-001 --draft", err)
        self.assertEqual(self.stage_of(card_id), "building")
        self.assertEqual(json.loads((self.dir / "asked.json").read_text())["id"], card_id)

    def test_a_publishable_card_reaches_it(self):
        stub(self.dir, "echo '{\"publishable\": true}'")
        card_id = self.work_card()
        self.assertEqual(self.stage_review(card_id)[0], 0)
        self.assertEqual(self.stage_of(card_id), "review")

    def test_a_check_that_fails_refuses_rather_than_opening_the_gate(self):
        stub(self.dir, "echo 'no credentials' >&2; exit 1")
        card_id = self.work_card()
        code, _, err = self.stage_review(card_id)
        self.assertEqual(code, 1)
        self.assertIn("could not be checked", err)
        self.assertIn("no credentials", err)
        self.assertEqual(self.stage_of(card_id), "building")

    def test_an_answer_that_is_not_the_shape_refuses(self):
        stub(self.dir, "echo '[]'")
        card_id = self.work_card()
        self.assertEqual(self.stage_review(card_id)[0], 1)

    def test_a_space_without_the_verb_is_never_asked(self):
        card_id = self.work_card()
        self.assertEqual(self.stage_review(card_id)[0], 0)
        code, out, err = self.kb("create", "--space", "personal", "--title", "p", "--autonomy", "autonomous")
        stub(self.dir, "exit 1")
        personal = out.split()[0]
        self.kb("set", personal, "plan_ref=/plans/plan.md")
        self.kb("stage", personal, "building")
        self.assertEqual(self.stage_review(personal)[0], 0, "a personal card is not the adapter's")

    def test_other_moves_are_never_asked(self):
        stub(self.dir, "exit 1")
        card_id = self.work_card()
        self.assertEqual(self.kb("stage", card_id, "building")[0], 0)
        self.assertFalse((self.dir / "asked.json").exists())


class ShippedTest(KbCase):
    def test_a_shipped_card_coming_back_from_a_review_round_is_not_asked(self):
        """Its pull request exists, and the round's commits are pushed by his Approve."""
        cfg = make_config(self.dir)
        stub(self.dir, "exit 1")
        card = {"id": "c-9", "space": "work", "options": {"shipping": {"round": 1}}}
        self.assertIsNone(adapters.publishable(cfg, card))
        with self.assertRaises(adapters.AdapterError):
            adapters.publishable(cfg, dict(card, options={}))


class RemoteModeTest(KbCase):
    def test_the_check_uses_the_config_it_is_handed(self):
        """In HTTP mode the board is elsewhere; the house's own config is what is asked."""
        cfg = make_config(self.dir)
        stub(self.dir, f"echo '{json.dumps({'publishable': False, 'missing': MISSING})}'")

        class Args:
            verb, stage, id, plan = "stage", "review", "c-001", None
        card = {"id": "c-001", "space": "work", "options": {}, "events": []}
        with self.assertRaisesRegex(Refused, "is not on origin"):
            plangate.check_stage(Args(), lambda: card, None, cfg=cfg)


class ServedTest(WorkCardCase):
    """c-564: the deck carries a move out as `bin/kb` (`actions.run_kb`), and that kb asks
    the adapter whether the card can publish, as a house's own kb does."""

    NO_CLONE = "echo 'origin of /home/ubuntu/workspace/api could not be read' >&2; exit 1"

    def claim_for(self, card_id: str, host: str) -> None:
        """`options.claim` as a drain on `host` leaves it; `Board.claim` takes only a
        startable card, and this one is building."""
        db = sqlite3.connect(self.dir / "state" / "board.db")
        with db:
            (options,) = db.execute("SELECT options FROM cards WHERE id = ?", (card_id,)).fetchone()
            held = dict(json.loads(options or "{}"), claim={"host": host, "at": "2026-09-28T00:00:00+00:00"})
            db.execute("UPDATE cards SET options = ? WHERE id = ?", (json.dumps(held), card_id))
        db.close()

    def deck_stage(self, card_id: str, **extra):
        """The move as the deck carries it out: `actions.act`, then `bin/kb` for real."""
        cfg = config_module.load(None, ensure=False)
        body = {"verb": "stage", "id": card_id, "stage": "review", "output": "branch", **extra}
        return actions.act(cfg, None, body)

    def test_the_deck_s_move_is_asked(self):
        """His tap on the deck: the deck's own kb asks the adapter, whoever claimed the card."""
        stub(self.dir, self.NO_CLONE)
        card_id = self.work_card()
        self.claim_for(card_id, "laptop")
        with self.assertRaisesRegex(actions.ActionError, "could not be read"):
            self.deck_stage(card_id)
        self.assertEqual(self.stage_of(card_id), "building")

    def test_a_house_here_is_still_asked(self):
        stub(self.dir, "echo 'no credentials' >&2; exit 1")
        card_id = self.work_card()
        self.claim_for(card_id, config_module.load(None, ensure=False).host)
        code, _, err = self.stage_review(card_id)
        self.assertEqual(code, 1)
        self.assertIn("could not be checked", err)
        self.assertIn("no credentials", err)
        self.assertEqual(json.loads((self.dir / "asked.json").read_text())["id"], card_id)
        self.assertEqual(self.stage_of(card_id), "building")

if __name__ == "__main__":
    import unittest
    unittest.main()
