"""`keel new pack|segment|view` (keel/scaffold.py, c-634), each in a temporary root that holds
what the scaffold copies from: a new pack loads with the sandbox's capabilities, terms and
first-run step; a new segment passes its check and its own test passes when run; a new view
is one manifest row and one file, and the served page then loads it; a taken or malformed
name is refused, and `--install` writes where the install's own packs and segments live."""

import json
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

from keel import deckviews, packs, scaffold, segmentspec

ROOT = Path(__file__).resolve().parent.parent


class ScaffoldCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name) / "code"
        shutil.copytree(ROOT / "packs" / "sandbox", self.root / "packs" / "sandbox",
                        ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
        app = self.root / "app"
        app.mkdir()
        for name in (*deckviews.load(ROOT / "app")["scripts"], "index.html", "sw.js", deckviews.MANIFEST):
            shutil.copy2(ROOT / "app" / name, app / name)


class PackTest(ScaffoldCase):
    def test_a_new_pack_loads_with_the_sandboxs_parts_and_its_own_name(self):
        written = scaffold.new_pack("acme", self.root)
        made = packs.load(self.root / "packs" / "acme")
        sandbox = packs.load(self.root / "packs" / "sandbox")
        self.assertEqual(made.name, "acme")
        self.assertEqual(made.capabilities, sandbox.capabilities)
        self.assertTrue(made.capabilities)
        self.assertEqual(made.terms, sandbox.terms)
        self.assertEqual([step.id for step in made.setup], ["try"])
        self.assertEqual(made.setup[0].title, "Try the acme pack")
        self.assertEqual((sandbox.demo_only, made.demo_only), (True, False), "the copy is offered (c-688)")
        spec = (self.root / "packs" / "acme" / "pack.toml").read_text()
        self.assertTrue(spec.startswith("# The acme pack, made by `keel new pack acme`"))
        self.assertIn('description = "The acme pack: say here what it integrates."', spec)
        example = (self.root / "packs" / "acme" / "config.example.toml").read_text()
        self.assertIn('pack = "acme"', example)
        self.assertNotRegex(example, r'(?m)^(contract|pipeline) = ', "the demo's pipeline runs the sandbox's pr (r2.F4)")
        self.assertTrue((self.root / "packs" / "acme" / "act").stat().st_mode & 0o111, "modes kept")
        self.assertTrue((self.root / "packs" / "acme" / "setup" / "try.md").read_text().startswith("The acme pack, as made,"))
        self.assertFalse(any("__pycache__" in str(path) for path in written))

    def test_a_taken_or_malformed_name_is_refused_and_writes_nothing(self):
        for name, said in (("sandbox", "is taken"), ("../x", "is not a pack name"), ("Acme", "is not a pack name")):
            with self.assertRaises(scaffold.Refused) as refused:
                scaffold.new_pack(name, self.root)
            self.assertIn(said, str(refused.exception))
        self.assertEqual(sorted(p.name for p in (self.root / "packs").iterdir()), ["sandbox"])

    def test_a_copy_that_does_not_load_is_removed(self):
        (self.root / "packs" / "sandbox" / "act").unlink()      # a claim without its verb
        with self.assertRaises(scaffold.Refused) as refused:
            scaffold.new_pack("acme", self.root)
        self.assertIn("does not load", str(refused.exception))
        self.assertFalse((self.root / "packs" / "acme").exists())

    def test_a_pack_toml_it_cannot_rename_is_refused_and_removed(self):
        """No traceback and nothing half made (c-628 review r1.F9)."""
        spec = self.root / "packs" / "sandbox" / "pack.toml"
        spec.write_text(spec.read_text().replace("\nname = ", "\nnom = ", 1))
        with self.assertRaises(scaffold.Refused):
            scaffold.new_pack("acme", self.root)
        self.assertFalse((self.root / "packs" / "acme").exists())


class KitPackTest(ScaffoldCase):
    """c-735: `keel new pack <name> --kit` starts a pack on the pack kit: the shims, a layer
    stub, a guard policy, the requirement checks, a stand-in hook and the conformance file.
    It loads, its layer is one the kit can run, and its check holds every contract and fails
    until the layer is written."""

    def make(self, *argv: str) -> Path:
        args = scaffold.build_parser().parse_args(["pack", "acme", "--kit", *argv])
        scaffold.run(args, load=lambda: None, root=self.root)
        return self.root / "packs" / "acme"

    def test_a_kit_pack_loads_and_each_verb_is_a_shim_over_the_kit(self):
        made = self.make()
        pack = packs.load(made)
        self.assertEqual((pack.capabilities, pack.guard_tools), (frozenset({"codehost"}), ("git",)))
        for verb in ("worktree", "brief", "pr", "publishable", "publish", "ship", "act", "logins", "ready"):
            self.assertIn('verbs.run("' + verb + '", sys.argv[1:], pack=HERE, layer="acme_layer")',
                          (made / verb).read_text(), verb)
        self.assertIn("guard.main(sys.argv[1:], pack=HERE, policy=acme_fence.POLICY)", (made / "guard").read_text())
        for name in ("acme_layer.py", "acme_fence.py", "acme_ready.py", "rules/house.md", "rules/comments.md",
                     "tests/suitefence.py", "tests/standin.py", "tests/test_conformance.py"):
            self.assertTrue((made / name).is_file(), name)
        self.assertNotIn("sandbox", (made / "pack.toml").read_text())

    def test_its_layer_is_one_the_kit_can_run_and_its_ready_runs(self):
        from keel.packkit.layer import check_layer
        made = self.make()
        sys.path.insert(0, str(made))
        self.addCleanup(sys.path.remove, str(made))
        import importlib
        check_layer(importlib.import_module("acme_layer"))
        done = subprocess.run([str(made / "ready"), "git"], capture_output=True, text=True,
                              env={"PATH": f"{Path(sys.executable).parent}:/usr/bin:/bin", "KEEL_HOME": str(ROOT)})
        self.assertEqual(done.returncode, 0, done.stderr)

    def test_its_check_holds_every_contract_and_fails_until_the_layer_is_written(self):
        from keel import packcheck
        found = packcheck.check(self.make())
        self.assertEqual((found["contracts"], found["missing"]), (["HostContract", "GuardContract", "VerbsContract"], []))
        self.assertFalse(found["ok"])
        self.assertIn("not written yet", found["said"])

    def test_a_hyphenated_name_makes_modules_python_can_import(self):
        """r2.F3: `my-forge` writes `my_forge_layer.py` and friends; the guard shim runs and
        allows a plain git command, and the conformance file imports."""
        args = scaffold.build_parser().parse_args(["pack", "my-forge", "--kit"])
        scaffold.run(args, load=lambda: None, root=self.root)
        made = self.root / "packs" / "my-forge"
        for name in ("my_forge_layer.py", "my_forge_fence.py", "my_forge_ready.py"):
            self.assertTrue((made / name).is_file(), name)
        env = {"PATH": f"{Path(sys.executable).parent}:/usr/bin:/bin", "KEEL_HOME": str(ROOT)}
        done = subprocess.run([str(made / "guard"), "c-1"], input=json.dumps({"command": "git status", "cwd": "."}),
                              capture_output=True, text=True, env=env, timeout=60)
        self.assertEqual((done.returncode, json.loads(done.stdout or "{}").get("allow")), (0, True), done.stderr)
        imported = subprocess.run([sys.executable, "-c", "import test_conformance"], cwd=made / "tests",
                                  capture_output=True, text=True, env={**env, "PYTHONPATH": str(ROOT)}, timeout=60)
        self.assertEqual(imported.returncode, 0, imported.stderr)

    def test_a_kit_pack_name_that_starts_with_a_digit_is_refused(self):
        with self.assertRaises(scaffold.Refused) as refused:
            self.make_named("9forge")
        self.assertEqual(str(refused.exception),
                         "9forge cannot start a pack on the kit: its modules are named for it, and a Python "
                         "module cannot start with a digit")
        self.assertFalse((self.root / "packs" / "9forge").exists())

    def make_named(self, name: str) -> Path:
        args = scaffold.build_parser().parse_args(["pack", name, "--kit"])
        scaffold.run(args, load=lambda: None, root=self.root)
        return self.root / "packs" / name

    def test_once_its_layer_and_stand_in_are_written_a_code_host_only_pack_passes(self):
        """r1.F1: passing is reachable. The layer is filled in with the kit's own stand-in over a
        world kept in a file (so the verbs, other processes, see it), and nothing more: the pack
        claims no review requests, so no review card's life is asked of it."""
        from keel import packcheck
        made = self.make()
        (made / "acme_layer.py").write_text(FILLED_LAYER)
        (made / "tests" / "standin.py").write_text(FILLED_STANDIN)
        found = packcheck.check(made)
        self.assertTrue(found["ok"], found["said"])
        self.assertEqual(found["contracts"], ["HostContract", "GuardContract", "VerbsContract"])


FILLED_LAYER = '''"""The acme pack's layer, filled in for the test: the kit's stand-in over a world in a file."""

import os

from keel.packkit import standin
from keel.packkit.layer import OPERATIONS, HostConfig
from keel.packkit.world import World

KIT = standin.KIT
HOST = HostConfig(name="Acme", on="on Acme", address=standin.address, pr_url=standin.pr_url,
                  ready="acme_ready", guard="acme_fence")


def operation(name):
    def call(*args, **kwargs):
        path = os.environ["ACME_WORLD"]
        world = standin.use(World.load(path))
        try:
            return getattr(standin, name)(*args, **kwargs)
        finally:
            world.save(path)
    return call


for _name in OPERATIONS:
    globals()[_name] = operation(_name)
'''

FILLED_STANDIN = '''"""The acme pack's stand-in hook, filled in for the test: the world in a file the layer reads."""

import os
import tempfile
from pathlib import Path
from unittest import mock

from keel.packkit import standin
from keel.packkit.layer import Repo
from keel.packkit.world import World


class StandIn:
    def setUp(self):
        made = tempfile.TemporaryDirectory(prefix="acme-world-")
        self.addCleanup(made.cleanup)
        self.world_file = Path(made.name) / "world.json"
        World().save(self.world_file)
        patcher = mock.patch.dict(os.environ, {"ACME_WORLD": str(self.world_file)})
        patcher.start()
        self.addCleanup(patcher.stop)

    def host_remote(self, name):
        return f"{standin.BASE}/{name}.git"

    def host_repo(self, name):
        return Repo(name, standin.BASE, None)

    def host_serve(self, world):
        world.save(self.world_file)

    def host_seen(self, world):
        return World.load(self.world_file)
'''


class SegmentTest(ScaffoldCase):
    def test_a_new_segment_passes_its_check_and_its_own_test(self):
        written = scaffold.new_segment("demo", "personal", ["personal", "work"], self.root)
        directory = self.root / "segments" / "demo"
        self.assertEqual([path.name for path in written], ["segment.md", "fetch.py", "test_fetch.py"])
        self.assertEqual(segmentspec.check(directory, ["personal"]), [])
        done = subprocess.run([sys.executable, str(directory / "test_fetch.py")],
                              capture_output=True, text=True, timeout=60)
        self.assertEqual(done.returncode, 0, done.stderr)
        self.assertFalse((directory / "summary.json").exists(), "its test runs in a copy")
        subprocess.run([sys.executable, "fetch.py"], cwd=directory, check=True, timeout=60)
        summary = json.loads((directory / "summary.json").read_text())
        self.assertEqual(summary["tiles"], [{"label": "items", "value": 0}])

    def test_a_bad_name_a_taken_one_or_an_unknown_space_is_refused(self):
        scaffold.new_segment("demo", "personal", ["personal"], self.root)
        elsewhere = Path(self.tmp.name) / "installed"
        (elsewhere / "fathom").mkdir(parents=True)
        for name, space, said in (("demo", "personal", "is taken"), ("fathom", "personal", "is taken"),
                                  ("Demo", "personal", "is not a segment name"),
                                  ("other", "home", "space home is not configured")):
            with self.assertRaises(scaffold.Refused) as refused:
                scaffold.new_segment(name, space, ["personal"], self.root, roots=[elsewhere])
            self.assertIn(said, str(refused.exception))
        self.assertFalse((self.root / "segments" / "other").exists())


class ViewTest(ScaffoldCase):
    def test_a_new_view_is_one_row_and_one_file_and_the_page_loads_it(self):
        before = (self.root / "app" / deckviews.MANIFEST).read_text()
        written = scaffold.new_view("demo", self.root)
        app = self.root / "app"
        self.assertEqual(written, [app / deckviews.MANIFEST, app / "ui.demo.js"])
        after = (app / deckviews.MANIFEST).read_text()
        added = [line for line in after.splitlines() if line not in before.splitlines()]
        self.assertEqual(len([line for line in added if '"key": "demo"' in line]), 1)
        manifest = deckviews.load(app)
        self.assertEqual(manifest["scripts"][-2:], ["ui.demo.js", "ui.js"])
        self.assertEqual(len(after.splitlines()) - len(before.splitlines()), 1, "one added row line")
        self.assertEqual(len(added), 2, f"the row and the scripts line it joins: {added}")
        self.assertEqual(manifest["views"][-1]["key"], "more")
        row = manifest["views"][-2]
        self.assertEqual(row, {"key": "demo", "name": "Demo", "icon": scaffold.VIEW_ICON,
                               "render": "viewDemo", "script": "ui.demo.js", "needs": []})
        self.assertIn('<script src="/ui.demo.js"></script>\n<script src="/ui.js"></script>',
                      deckviews.rendered(app, "index.html"))
        self.assertIn('"/ui.demo.js"', deckviews.rendered(app, "sw.js"))
        self.assertIn("K.viewDemo = viewDemo;", (app / "ui.demo.js").read_text())

    @unittest.skipUnless(shutil.which("node"), "node is not on this machine")
    def test_the_new_view_draws_under_node(self):
        scaffold.new_view("demo", self.root)
        done = subprocess.run(["node", str(ROOT / "tests" / "fixtures" / "views-deck.js"), str(self.root / "app")],
                              capture_output=True, text=True, timeout=60)
        self.assertEqual(json.loads(done.stdout), {"ok": True}, done.stdout + done.stderr)

    def test_a_taken_or_malformed_key_is_refused_and_the_manifest_is_untouched(self):
        before = (self.root / "app" / deckviews.MANIFEST).read_text()
        for key, said in (("cards", "is taken"), ("core", "is taken"), ("my-view", "is not a view key"),
                          ("9lives", "is not a view key")):
            with self.assertRaises(scaffold.Refused) as refused:
                scaffold.new_view(key, self.root)
            self.assertIn(said, str(refused.exception))
        self.assertEqual((self.root / "app" / deckviews.MANIFEST).read_text(), before)

    def test_a_key_whose_function_the_deck_already_has_is_refused(self):
        """`of` would have replaced K.viewOf, which draws every view, and `route` the Reviews
        view's own render (c-628 review r1.F3)."""
        before = (self.root / "app" / deckviews.MANIFEST).read_text()
        for key, said in (("plan", "a route the deck answers itself"), ("prs", "a route the deck answers itself"),
                          ("of", "K.viewOf, which app/ui.core.js already defines"),
                          ("route", "K.viewRoute, which view reviews's render already defines")):
            with self.assertRaises(scaffold.Refused) as refused:
                scaffold.new_view(key, self.root)
            self.assertIn(said, str(refused.exception))
        self.assertEqual((self.root / "app" / deckviews.MANIFEST).read_text(), before)
        self.assertFalse((self.root / "app" / "ui.of.js").exists())

    def test_a_manifest_that_does_not_read_is_a_refusal_not_a_traceback(self):
        (self.root / "app" / deckviews.MANIFEST).write_text("{")
        with self.assertRaises(scaffold.Refused) as refused:
            scaffold.new_view("demo", self.root)
        self.assertIn("does not read", str(refused.exception))


class WhereTest(ScaffoldCase):
    def cfg(self, install: bool):
        home = Path(self.tmp.name) / "install"
        return SimpleNamespace(install_home=home if install else None, spaces={"personal": None},
                               segments_dir=home / "segments", segment_roots=[])

    def args(self, kind, name, install=False):
        return scaffold.build_parser().parse_args([kind, name] + (["--install"] if install else []))

    def test_install_puts_a_pack_and_a_segment_in_the_installs_own_directories(self):
        cfg = self.cfg(True)
        pack = scaffold.run(self.args("pack", "acme", True), lambda: cfg, self.root)
        segment = scaffold.run(self.args("segment", "demo", True), lambda: cfg, self.root)
        self.assertTrue(str(pack[0]).startswith(str(cfg.install_home / "packs" / "acme")))
        self.assertEqual(segment[0], cfg.segments_dir / "demo" / "segment.md")
        self.assertFalse((self.root / "packs" / "acme").exists())

    def test_a_pack_or_a_view_in_the_checkout_never_reads_the_config(self):
        """A config that does not load (a space naming a pack that is gone) does not stop the
        builder making the pack it names."""
        def broken():
            raise AssertionError("the config was read")
        scaffold.run(self.args("pack", "acme"), broken, self.root)
        scaffold.run(self.args("view", "demo"), broken, self.root)
        self.assertTrue((self.root / "packs" / "acme" / "pack.toml").is_file())

    def test_install_is_refused_for_a_view_and_without_an_install(self):
        with self.assertRaises(scaffold.Refused):
            scaffold.run(self.args("view", "demo", True), lambda: self.cfg(True))
        with self.assertRaises(scaffold.Refused):
            scaffold.run(self.args("pack", "acme", True), lambda: self.cfg(False))


if __name__ == "__main__":
    unittest.main()
