"""The deck's views from one manifest (keel/deckviews.py, c-634): the shipped app/views.json
passes its check and round-trips through `dump`, a bad one is refused by name, the filled
worker's cache name and ETag move with the manifest, and under node every view's render is
defined by the scripts the manifest lists (tests/fixtures/views-deck.js)."""

import json
import os
import re
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

from keel import deckviews

ROOT = Path(__file__).resolve().parent.parent
APP = ROOT / "app"


def shipped() -> dict:
    return json.loads((APP / deckviews.MANIFEST).read_text(encoding="utf-8"))


class ManifestTest(unittest.TestCase):
    def test_the_shipped_manifest_passes_and_keeps_its_layout(self):
        self.assertEqual(deckviews.check(shipped(), APP), [])
        self.assertEqual(deckviews.dump(shipped()), (APP / deckviews.MANIFEST).read_text(encoding="utf-8"))

    def test_it_carries_what_the_slices_before_it_put_in_views(self):
        """S3's needs and dock rule, S4's Start on the rail until Finish, S5's Settings."""
        rows = {row["key"]: row for row in shipped()["views"]}
        self.assertEqual(rows["cards"]["needs"], ["repos"])
        self.assertEqual(rows["reviews"]["needs"], ["codehost", "reviews"])
        self.assertEqual((rows["segments"]["needs"], rows["segments"]["dock"]), (["segments"], "when-ready"))
        self.assertEqual(rows["start"]["rail"], "until-finished")
        self.assertEqual(rows["settings"]["render"], "viewSettings")
        self.assertEqual((rows["more"]["nav"], rows["more"]["dock"]), (False, True))
        self.assertEqual(rows["reviews"]["arg"], "reviews")

    def test_a_bad_manifest_is_refused_by_name(self):
        def said(change) -> str:
            manifest = shipped()
            change(manifest)
            return "; ".join(deckviews.check(manifest, APP))
        self.assertIn("ui.nope.js is listed and is not in app/",
                      said(lambda m: m["scripts"].insert(1, "ui.nope.js")))
        self.assertIn("end with ui.js", said(lambda m: m["scripts"].remove("ui.js")))
        self.assertIn("view now is listed twice", said(lambda m: m["views"].append(dict(m["views"][1]))))
        self.assertIn("view cards: needs lists readiness rows",
                      said(lambda m: m["views"][3].update(needs=["wifi"])))
        self.assertIn("view board: its script ui.gone.js is not in scripts",
                      said(lambda m: m["views"][4].update(script="ui.gone.js")))
        self.assertIn("view board: colour is not a view key", said(lambda m: m["views"][4].update(colour="red")))
        self.assertIn("view atlas has no render", said(lambda m: m["views"][6].pop("render")))
        self.assertIn("view setup: dock is true, false or when-ready",
                      said(lambda m: m["views"][7].update(dock="sometimes")))
        self.assertIn("view board: render viewCards is view cards's too",
                      said(lambda m: m["views"][4].update(render="viewCards")))
        self.assertIn("view atlas: K.viewOf is already defined in app/ui.core.js, which loads first",
                      said(lambda m: m["views"][6].update(render="viewOf")))
        self.assertIn("view plan: plan is a route the deck answers itself",
                      said(lambda m: m["views"].append(dict(m["views"][1], key="plan"))))

    def test_every_route_the_core_answers_is_a_row_or_reserved(self):
        """A route literal app/*.js branches on that no row names is the core's own: a view
        keyed so would be drawn but answered by the core (c-628 review r2.F1)."""
        said = set()
        for script in APP.glob("*.js"):
            text = script.read_text(encoding="utf-8")
            said |= set(re.findall(r"App\.view\s*[!=]==?\s*'([a-z]+)'", text))
            said |= set(re.findall(r"RETIRED_[A-Z]+\s*=\s*'([a-z]+)'", text))
        rows = {row["key"] for row in shipped()["views"]}
        self.assertEqual(sorted(said - rows), sorted(deckviews.RESERVED))

    def test_the_page_and_the_worker_are_filled(self):
        manifest = shipped()
        page = deckviews.rendered(APP, "index.html")
        self.assertNotIn(deckviews.INDEX_MARK, page)
        self.assertIn("window.KEEL_VIEWS = ", page)
        worker = deckviews.rendered(APP, "sw.js")
        self.assertIn(f'"hash": "{deckviews.digest(manifest)}"', worker)
        self.assertNotIn("var DECK = { scripts: [], hash: '' };", worker)
        with self.assertRaises(deckviews.ManifestError):
            deckviews.index_html("<html></html>", manifest)
        with self.assertRaises(deckviews.ManifestError):
            deckviews.worker_js("var X = 1;", manifest)

    def test_nothing_in_the_manifest_can_close_the_inline_script(self):
        manifest = shipped()
        manifest["views"][1]["name"] = "</script><b>"
        self.assertNotIn("</script><b>", deckviews.inline(manifest))
        self.assertEqual(json.loads(deckviews.inline(manifest)), manifest)

    def test_the_cache_name_and_the_etag_move_with_the_manifest(self):
        with tempfile.TemporaryDirectory() as tmp:
            app = Path(tmp)
            for name in (*shipped()["scripts"], "sw.js", "index.html", deckviews.MANIFEST):
                shutil.copy2(APP / name, app / name)
            before = (deckviews.rendered(app, "sw.js"), deckviews.filled_tag(app, "sw.js", False))
            manifest = shipped()
            manifest["views"][0]["name"] = "Begin"
            (app / deckviews.MANIFEST).write_text(deckviews.dump(manifest), encoding="utf-8")
            stat = (app / deckviews.MANIFEST).stat()
            os.utime(app / deckviews.MANIFEST, ns=(stat.st_atime_ns, stat.st_mtime_ns + 1_000_000_000))
            after = (deckviews.rendered(app, "sw.js"), deckviews.filled_tag(app, "sw.js", False))
            self.assertNotEqual(before[1], after[1])
            self.assertIn(deckviews.digest(manifest), after[0])
            self.assertNotIn(deckviews.digest(shipped()), after[0])
            self.assertNotEqual(deckviews.filled_tag(app, "sw.js", True), after[1])

    @unittest.skipUnless(shutil.which("node"), "node is not on this machine")
    def test_every_view_is_drawn_from_the_manifest_under_node(self):
        done = subprocess.run(["node", str(ROOT / "tests" / "fixtures" / "views-deck.js"), str(APP)],
                              capture_output=True, text=True, timeout=60)
        self.assertEqual(done.returncode, 0, done.stderr)
        self.assertEqual(json.loads(done.stdout), {"ok": True}, done.stdout)


if __name__ == "__main__":
    unittest.main()
