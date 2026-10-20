"""Importer: field mapping, options, notes with original timestamps, idempotence."""

from pathlib import Path

from keel import importer
from tests.helpers import BoardCase

FIXTURE = Path(__file__).parent / "fixtures" / "ledger.jsonl"


class ImportTest(BoardCase):
    def run_import(self, **kwargs):
        return importer.import_ledger(self.board, FIXTURE, **kwargs)

    def test_counts_and_summary(self):
        counts = self.run_import()
        self.assertEqual(counts["imported"], 4)
        self.assertEqual(counts["by_space"], {"work": 2, "personal": 2})
        self.assertEqual(counts["notes"], 2)
        self.assertIn("imported 4 cards", importer.summary(counts))

    def test_ids_timestamps_and_field_mapping(self):
        self.run_import()
        card = self.board.get("c-001")
        self.assertEqual(card["created_at"], "2026-07-08T12:33:04")
        self.assertEqual(card["updated_at"], "2026-07-10T08:00:00")
        self.assertEqual(card["stage"], "building")  # checking folds to building
        self.assertEqual(card["brief"], "Integrate the thing.")
        self.assertEqual(card["autonomy"], "attended")
        self.assertEqual(card["repo"], "alpha,beta")
        self.assertEqual(card["plan_ref"], "/tmp/plans/first.html")
        self.assertEqual(card["blocked_reason"], "needs a human")
        self.assertIsNone(card["output_ref"])
        self.assertIsNone(card["parent"])
        self.assertIsNone(card["after"])
        self.assertEqual(card["options"], {
            "tracker_ref": "st-1", "tracker_mode": "create at task start",
            "branch": "feature/st-1/first", "worktree": "/tmp/wt/first", "archived": False})
        self.assertEqual(self.board.next_id(), "c-005")

    def test_pr_wins_as_output_ref_and_stage_defaults(self):
        self.run_import()
        done = self.board.get("c-002")
        self.assertEqual((done["stage"], done["output_ref"], done["options"]["archived"]),
                         ("done", "4034", True))
        stageless = self.board.get("c-003")
        self.assertEqual((stageless["stage"], stageless["model"], stageless["autonomy"]),
                         ("inbox", "opus", "autonomous"))
        self.assertEqual(stageless["options"]["include_tests"], "False")
        live = self.board.get("c-004")
        self.assertEqual((live["stage"], live["session_id"], live["options"]["guidance"]),
                         ("building", "e849e3c7-090e-4c16-a56d-fa36b2c8f572", "keep it small"))

    def test_notes_keep_their_timestamps_and_order(self):
        self.run_import()
        notes = [e for e in self.board.events("c-001") if e["kind"] == "note"]
        self.assertEqual([(n["at"], n["text"], n["actor"]) for n in notes], [
            ("2026-07-09T20:13:50", "first note", "import"),
            ("2026-07-10T08:00:00", "second note", "import")])
        create = self.board.events("c-001")[0]
        self.assertEqual((create["kind"], create["at"]), ("create", "2026-07-08T12:33:04"))

    def test_second_run_changes_nothing(self):
        self.run_import()
        before = (self.board.list_cards(), sum(len(self.board.events(c)) for c in ("c-001", "c-002", "c-003", "c-004")))
        counts = self.run_import()
        self.assertEqual((counts["imported"], counts["existing"]), (0, 4))
        after = (self.board.list_cards(), sum(len(self.board.events(c)) for c in ("c-001", "c-002", "c-003", "c-004")))
        self.assertEqual(before, after)

    def test_skip_archived(self):
        counts = self.run_import(skip_archived=True)
        self.assertEqual((counts["imported"], counts["archived_skipped"]), (2, 2))
        self.assertEqual({c["id"] for c in self.board.list_cards()}, {"c-001", "c-004"})
        counts = self.run_import()
        self.assertEqual((counts["imported"], counts["existing"]), (2, 2))
