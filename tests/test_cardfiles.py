"""Every markdown file a card writes, read in the viewer (c-719).

End to end on a free port: the card's files listed on its detail and on every page of its
viewer, one opened through `/api/plan/<id>?doc=file&name=` as the same parsed document the
plan and the outcome are (a board, a table), read only, and nothing served from outside the
card's own folder. The page itself is drawn under node on the real plan shell
(`tests/fixtures/cardfiles.js`)."""

import json
import os
import shutil
import subprocess
import tempfile
import unittest
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from unittest import mock

from keel import artifacts, cardfiles, deckstate, planroute, prompts
from tests.test_serve import ServerCase

ROOT = Path(__file__).resolve().parent.parent
FIXTURE = ROOT / "tests" / "fixtures" / "cardfiles.js"
REPORT = """# What the costs come to

The agent costs about a third of what the pilot did.

## The numbers

What each run cost, by model:

| run | model | cost |
|---|---|---|
| r1 | small | [ok] 0.40 |
| r2 | large | [warn] 1.90 |

```board
b-404
```

> [!info] Read with the outcome
> It says what was done with these.
"""


class CardFilesTest(ServerCase):
    def setUp(self):
        super().setUp()
        b = self.board
        self.card = b.create("personal", "a card that wrote a report", autonomy="attended", actor="human")
        self.dir = self.cfg.card_dir(self.card)
        (self.dir / "plan.md").write_text("---\nkind: plan\n---\n# p\n")
        b.stage(self.card, "assigned", "human")
        b.stage(self.card, "planning", "house", plan_ref=str(self.dir / "plan.md"))
        (self.dir / "context.md").write_text("---\nkind: outcome\n---\n# t\n\n## Where it stands\n\nx\n")
        (self.dir / "report.md").write_text(REPORT)
        (self.dir / "results").mkdir()
        (self.dir / "results" / "B0.md").write_text("# B0\n\nthe baseline\n")
        (self.dir / "told").mkdir()
        (self.dir / "told" / "20261008T100000.md").write_text("what the user said")
        (self.dir / "._report.md").write_text("finder junk")
        (self.dir / "notes.txt").write_text("not markdown")

    def names(self):
        return [row["name"] for row in cardfiles.listed(self.cfg, self.board.get(self.card))]

    def test_the_cards_markdown_files_are_listed_and_its_own_pages_are_not(self):
        self.assertEqual(self.names(), ["report.md", "results/B0.md"])

    def test_a_named_output_inside_the_folder_is_listed_and_one_outside_is_not(self):
        deep = self.dir / "a" / "b" / "c"
        deep.mkdir(parents=True)
        (deep / "far.md").write_text("# far\n")
        self.board.set_fields(self.card, {"output_ref": str(deep / "far.md")}, "house")
        self.assertIn("a/b/c/far.md", self.names())
        with tempfile.TemporaryDirectory() as tmp:
            outside = Path(tmp) / "out.md"
            outside.write_text("# out\n")
            self.board.set_fields(self.card, {"output_ref": str(outside)}, "house")
            self.assertNotIn("out.md", " ".join(self.names()))

    def test_a_name_that_leaves_the_folder_is_refused(self):
        card = self.board.get(self.card)
        with tempfile.TemporaryDirectory() as tmp:
            secret = Path(tmp) / "secret.md"
            secret.write_text("# no\n")
            os.symlink(secret, self.dir / "link.md")
            for name in ("../c-1/context.md", str(secret), "link.md", ".hidden.md", "notes.txt",
                         "results/../../x.md", "~/x.md", ""):
                with self.subTest(name=name), self.assertRaises(cardfiles.FileRefused):
                    cardfiles.resolve(self.cfg, card, name)
            self.assertNotIn("link.md", self.names())
            status, _, raw = self.fetch(f"/api/plan/{self.card}?doc=file&name=link.md")
            self.assertEqual(status, 404, raw)
            self.assertNotIn(b"# no", raw)

    def refused(self, name):
        with self.assertRaises(cardfiles.FileRefused, msg=name):
            cardfiles.resolve(self.cfg, self.board.get(self.card), name)
        status, _, raw = self.fetch(f"/api/plan/{self.card}?doc=file&name=" + urllib.parse.quote(name))
        self.assertEqual(status, 404, (name, raw))
        self.assertNotIn(name, self.names())

    def test_r1_f2_a_link_inside_the_folder_to_a_file_not_markdown_or_hidden_is_refused(self):
        (self.dir / "raw.json").write_text('{"secret": 1}')
        (self.dir / ".cache").mkdir()
        (self.dir / ".cache" / "x.md").write_text("# hidden\n")
        os.symlink(self.dir / "raw.json", self.dir / "notes.md")
        os.symlink(self.dir / ".cache" / "x.md", self.dir / "seen.md")
        self.refused("notes.md")
        self.refused("seen.md")

    def test_r1_f3_told_and_the_board_folders_are_refused_by_name(self):
        self.refused("told/20261008T100000.md")
        (self.dir / "board-files").mkdir()
        (self.dir / "board-files" / "a.md").write_text("# a\n")
        self.refused("board-files/a.md")

    def test_r1_f7_the_size_cap_and_a_credential_folder_are_refused(self):
        (self.dir / "credentials").mkdir()
        (self.dir / "credentials" / "x.md").write_text("# key\n")
        self.refused("credentials/x.md")
        with mock.patch.object(artifacts, "MAX_BYTES", 10):
            self.refused("report.md")

    def test_r1_f7_a_linked_folder_that_leaves_the_card_is_refused(self):
        with tempfile.TemporaryDirectory() as tmp:
            (Path(tmp) / "away.md").write_text("# away\n")
            os.symlink(tmp, self.dir / "elsewhere")
            self.refused("elsewhere/away.md")

    def test_r1_f7_an_encoded_name_reaches_its_file_through_the_route(self):
        (self.dir / "my notes.md").write_text("# spaced\n")
        body = self.get_json(f"/api/plan/{self.card}?doc=file&name=" + urllib.parse.quote("my notes.md"))
        self.assertEqual(body["file"], "my notes.md")
        self.assertIn(f"/file/{self.card}/my%20notes.md", [row["url"] for row in body["files"]])
        status, _, _ = self.fetch(f"/api/plan/{self.card}?doc=file&name=" + urllib.parse.quote("results/../../x.md", safe=""))
        self.assertEqual(status, 404)

    def test_r1_f7_the_cards_detail_answers_304_until_a_file_is_written(self):
        status, headers, _ = self.fetch_tagged(f"/api/card/{self.card}")
        tag = headers.get("ETag")
        self.assertEqual(status, 200)
        self.assertEqual(self.fetch_tagged(f"/api/card/{self.card}", tag)[0], 304)
        (self.dir / "appendix.md").write_text("# more\n")
        status, headers, raw = self.fetch_tagged(f"/api/card/{self.card}", tag)
        self.assertEqual(status, 200)
        self.assertIn("appendix.md", [row["name"] for row in json.loads(raw)["files"]])

    def test_r1_f11_a_named_output_deeper_than_the_walk_moves_the_tag(self):
        deep = self.dir / "a" / "b" / "c"
        deep.mkdir(parents=True)
        (deep / "far.md").write_text("# far\n")
        self.board.set_fields(self.card, {"output_ref": str(deep / "far.md")}, "house")
        _, headers, _ = self.fetch_tagged(f"/api/card/{self.card}")
        tag = headers.get("ETag")
        (deep / "far.md").write_text("# far, and longer now\n")
        os.utime(deep / "far.md", ns=(1, 1))
        self.assertEqual(self.fetch_tagged(f"/api/card/{self.card}", tag)[0], 200)

    def test_r2_f5_a_name_outside_latin_1_is_served_and_tagged(self):
        for name in ("注記.md", "it’s.md"):
            (self.dir / name).write_text("# words\n")
            status, headers, raw = self.fetch_tagged(f"/api/plan/{self.card}?doc=file&name=" + urllib.parse.quote(name))
            self.assertEqual(status, 200, (name, raw[:200]))
            self.assertEqual(json.loads(raw)["file"], name)
            self.assertTrue(headers.get("ETag"))

    def test_r2_f6_told_in_any_case_is_refused(self):
        self.refused("Told/20261008T100000.md")
        self.refused("TOLD/20261008T100000.md")

    def test_r2_f7_a_file_reached_by_name_moves_its_pages_tag(self):
        deep = self.dir / "a" / "b" / "c" / "d"
        deep.mkdir(parents=True)
        (deep / "deep.md").write_text("# deep\n")
        url = f"/api/plan/{self.card}?doc=file&name=" + urllib.parse.quote("a/b/c/d/deep.md")
        _, headers, _ = self.fetch_tagged(url)
        tag = headers.get("ETag")
        self.assertEqual(self.fetch_tagged(url, tag)[0], 304)
        (deep / "deep.md").write_text("# deep, edited\n")
        self.assertEqual(self.fetch_tagged(url, tag)[0], 200)

    def test_r2_f11_a_file_gone_between_the_list_and_its_stat_is_skipped(self):
        card = self.board.get(self.card)
        with mock.patch.object(cardfiles, "resolve", return_value=self.dir / "gone.md"):
            self.assertEqual(cardfiles.listed(self.cfg, card), [])
        with mock.patch.object(Path, "is_file", return_value=True), self.assertRaises(cardfiles.FileRefused):
            cardfiles.resolve(self.cfg, card, "gone.md")

    def test_r2_f4_an_output_that_is_the_record_is_the_records_own_page(self):
        self.board.set_fields(self.card, {"output_ref": str(self.dir / "context.md")}, "house")
        self.assertEqual(deckstate.links_for(self.cfg, self.board.get(self.card))["output"], f"/outcome/{self.card}")
        (self.dir / "context.md").write_text("# plain record\n")
        self.assertEqual(deckstate.links_for(self.cfg, self.board.get(self.card))["output"], f"/context/{self.card}")

    def fetch_tagged(self, path, tag=None):
        request = urllib.request.Request(self.base + path)
        if tag:
            request.add_header("If-None-Match", tag)
        try:
            with urllib.request.urlopen(request, timeout=10) as response:
                return response.status, response.headers, response.read()
        except urllib.error.HTTPError as error:
            with error:
                return error.code, error.headers, error.read()

    def test_a_card_file_is_the_viewers_parsed_document_read_only(self):
        status, _, raw = self.fetch(f"/api/plan/{self.card}?doc=file&name=report.md")
        self.assertEqual(status, 200, raw)
        body = json.loads(raw)
        self.assertEqual((body["doc_name"], body["gate"], body["answerable"], body["receipt"], body["file"]),
                         ("file", None, False, None, "report.md"))
        kinds = [block["type"] for block in body["doc"]["blocks"]]
        self.assertIn("table", kinds)
        self.assertIn("board", kinds)
        self.assertIn("callout", kinds)
        self.assertEqual(body["lint"]["findings"], [])
        self.assertIn("files", body["docs"])
        self.assertEqual([row["name"] for row in body["files"]], ["report.md", "results/B0.md"])

    def test_the_files_page_lists_them_on_every_page_of_the_viewer(self):
        body = self.get_json(f"/api/plan/{self.card}?doc=files")
        self.assertEqual(body["doc_name"], "files")
        self.assertEqual([row["url"] for row in body["files"]],
                         [f"/file/{self.card}/report.md", f"/file/{self.card}/results/B0.md"])
        self.assertIn("files", self.get_json(f"/api/plan/{self.card}")["docs"])

    def test_the_file_page_and_the_list_are_on_the_viewers_shell(self):
        for path in (f"/file/{self.card}/results/B0.md", f"/files/{self.card}"):
            status, kind, raw = self.fetch(path)
            self.assertEqual(status, 200, path)
            self.assertIn(b"ui.plan.js", raw)

    def test_the_cards_detail_lists_its_files(self):
        detail = self.get_json(f"/api/card/{self.card}")
        self.assertEqual([row["name"] for row in detail["files"]], ["report.md", "results/B0.md"])

    def test_a_new_file_moves_the_cards_detail(self):
        before = cardfiles.stamp(self.cfg, self.board.get(self.card))
        (self.dir / "appendix.md").write_text("# more\n")
        self.assertNotEqual(cardfiles.stamp(self.cfg, self.board.get(self.card)), before)
        detail = self.get_json(f"/api/card/{self.card}")
        self.assertIn("appendix.md", [row["name"] for row in detail["files"]])

    def test_a_named_markdown_output_opens_in_the_viewer_not_as_an_artifact(self):
        self.board.set_fields(self.card, {"output_ref": str(self.dir / "report.md")}, "house")
        links = deckstate.links_for(self.cfg, self.board.get(self.card))
        self.assertEqual(links["output"], f"/file/{self.card}/report.md")

    def test_an_outcomes_link_to_a_card_file_opens_it_in_the_viewer(self):
        (self.dir / "context.md").write_text("---\nkind: outcome\n---\n# t\n\n## Where it stands\n\n"
                                             "The whole [report](report.md) and the [log](notes.txt).\n")
        body = self.get_json(f"/api/plan/{self.card}?doc=outcome")
        hrefs = [link["href"] for link in planroute.links_in(body["doc"]["blocks"])]
        self.assertIn(f"/file/{self.card}/report.md", hrefs)
        self.assertTrue(any(h and h.startswith("/api/artifact/") for h in hrefs), hrefs)

    def test_the_brief_promises_only_what_the_deck_does(self):
        self.assertIn("rich viewer", prompts.HUMAN_SEES)
        self.assertIn("/file/", prompts.HUMAN_SEES)

    @unittest.skipUnless(shutil.which("node"), "node is not on this machine")
    def test_the_page_draws_the_file_and_the_list(self):
        file_body = self.get_json(f"/api/plan/{self.card}?doc=file&name=" + urllib.parse.quote("report.md"))
        list_body = self.get_json(f"/api/plan/{self.card}?doc=files")
        with tempfile.TemporaryDirectory() as tmp:
            one, two = Path(tmp) / "file.json", Path(tmp) / "files.json"
            one.write_text(json.dumps(file_body))
            two.write_text(json.dumps(list_body))
            done = subprocess.run(["node", str(FIXTURE), str(ROOT / "app"), str(one), str(two)],
                                  capture_output=True, text=True, timeout=30)
        self.assertEqual(done.returncode, 0, done.stderr)
        self.assertEqual(json.loads(done.stdout), {"ok": True})


if __name__ == "__main__":
    unittest.main()
