"""`packs.load` (keel/packs.py): a pack's manifest is validated before anything runs it, and a
capability it declares (c-629) is one it implements, so the deck never shows a feature that
nothing behind it provides."""

import os
import tempfile
import unittest
from unittest import mock
from pathlib import Path

from keel import packs

MANIFEST = '''name = "demo"
version = "1"
description = "a pack for the test"
'''


class PackLoadTest(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.path = Path(tmp.name) / "demo"
        self.path.mkdir()

    def write(self, extra: str = "", verbs=()) -> None:
        (self.path / packs.PACK_FILE).write_text(MANIFEST + extra)
        for verb in verbs:
            target = self.path / verb
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text("#!/bin/sh\n")
            target.chmod(0o755)

    def refused(self, pattern: str) -> None:
        with self.assertRaisesRegex(packs.PackError, pattern):
            packs.load(self.path)

    def test_a_pack_with_no_capabilities_table_provides_none(self):
        self.write(verbs=("publish", "publishable", "ship", "act"))
        pack = packs.load(self.path)
        self.assertEqual(pack.capabilities, frozenset())
        self.assertEqual(pack.routes, ())

    def test_each_declared_capability_with_its_verbs_loads(self):
        self.write('[capabilities]\ntracker = true\ncodehost = true\nreviews = true\nroutes = ["reviews"]\n',
                   verbs=("act", "publish", "publishable", "ship", "review", "providers/reviews"))
        pack = packs.load(self.path)
        self.assertEqual(pack.capabilities, frozenset({"tracker", "codehost", "reviews"}))
        self.assertEqual(pack.routes, ("reviews",))

    def test_a_capability_without_its_verbs_is_refused_naming_them(self):
        self.write("[capabilities]\ncodehost = true\n", verbs=("publish",))
        self.refused("declares codehost but has no executable publishable, ship")

    def test_a_verb_that_is_not_executable_does_not_count(self):
        self.write("[capabilities]\ntracker = true\n")
        (self.path / "act").write_text("#!/bin/sh\n")
        os.chmod(self.path / "act", 0o644)
        self.refused("declares tracker but has no executable act")

    def test_a_loaded_pack_is_kept_until_its_shape_moves(self):
        """One /api/state build asks a pack a dozen times: it is read once (c-628 review r1.F4),
        and read again when pack.toml or the files beside it change."""
        self.write(verbs=("act",))
        first = packs.load(self.path)
        self.assertIs(packs.load(self.path), first, "kept")
        self.write("[capabilities]\ntracker = true\n")
        self.assertEqual(packs.load(self.path).capabilities, frozenset({"tracker"}), "pack.toml moved")
        os.chmod(self.path / "act", 0o644)
        self.refused("declares tracker but has no executable act")     # its mode (r2.F5)
        (self.path / "act").unlink()
        self.refused("declares tracker but has no executable act")
        self.write(verbs=("act",))
        again = packs.load(self.path)
        packs.forget()
        self.assertIsNot(packs.load(self.path), again, "forget reads afresh")

    def test_a_pack_with_a_guard_names_the_tools_it_reads_and_ships_the_verb(self):
        """c-689: `[guard] tools`, the words the house guard refuses on when the verb errors."""
        self.write(verbs=("act",))
        self.assertEqual(packs.load(self.path).guard_tools, ())
        self.write('[guard]\ntools = ["gh"]\n', verbs=("guard",))
        self.assertEqual(packs.load(self.path).guard_tools, ("gh",))
        (self.path / "guard").unlink()
        self.refused(r"\[guard\] but has no executable guard")
        self.write('[guard]\ntools = ["gh"]\ncolour = "red"\n', verbs=("guard",))
        self.refused(r"\[guard\] has no key colour")
        self.write('[guard]\ntools = ["two words"]\n', verbs=("guard",))
        self.refused("each tool is one word")

    def test_only_the_code_host_packs_ship_a_guard(self):
        """The packs that were here before them are asked nothing new."""
        guarded = {"github": ("gh",), "gitea": ("git", "tea", "curl", "wget")}
        found = {pack.name: pack.guard_tools for pack in packs.available(packs.PACKAGE)}
        self.assertEqual({name: tools for name, tools in found.items() if tools}, guarded)
        for name in found:
            self.assertEqual(packs.executable(packs.PACKAGE / packs.PACKS / name, "guard"), name in guarded, name)

    def test_an_unknown_capability_is_refused(self):
        self.write("[capabilities]\nwiki = true\n")
        self.refused(r"\[capabilities\] has no key wiki")

    def test_a_capability_must_be_true_or_false(self):
        self.write('[capabilities]\ntracker = "yes"\n', verbs=("act",))
        self.refused("tracker must be true or false")

    def test_a_route_without_its_provider_executable_is_refused(self):
        self.write('[capabilities]\nroutes = ["reviews"]\n')
        self.refused("providers/reviews is not an executable")

    def test_a_route_name_cannot_leave_the_providers_directory(self):
        self.write('[capabilities]\nroutes = ["../act"]\n', verbs=("act",))
        self.refused("is not an executable")

    def test_a_requirement_for_an_undeclared_capability_is_refused(self):
        self.write('[[requires]]\nname = "token"\nkind = "secret"\ncheck = "true"\nwhy = "w"\nfor = ["codehost"]\n')
        self.refused("is for codehost, which \\[capabilities\\] does not declare")

    def test_a_requirement_names_what_it_serves_and_its_check_says_it(self):
        self.write('[capabilities]\ntracker = true\n\n[[requires]]\nname = "token"\nkind = "secret"\n'
                   'check = "false"\nwhy = "w"\nfor = ["tracker"]\n', verbs=("act",))
        pack = packs.load(self.path)
        self.assertEqual(pack.requires[0].serves, ("tracker",))
        self.assertEqual(packs.checks(pack), [{"name": "token", "kind": "secret", "ok": False,
                                               "why": "w", "for": ["tracker"]}])

    def test_a_requirement_keeps_its_fix_and_its_check_returns_it(self):
        """c-688: the sentence, the one line to copy, how the user knows it worked, and the
        command a button may run reach whoever draws the failing check."""
        self.write('[[requires]]\nname = "gh"\nkind = "command"\ncheck = "false"\nwhy = "w"\n'
                   'fix = "Install it."\ncommand = "brew install gh"\n'
                   'done_when = "This row turns green."\naction = "true"\n')
        pack = packs.load(self.path)
        need = pack.requires[0]
        self.assertEqual((need.fix, need.command, need.done_when, need.action),
                         ("Install it.", "brew install gh", "This row turns green.", "true"))
        self.assertEqual(packs.checks(pack), [{
            "name": "gh", "kind": "command", "ok": False, "why": "w", "for": [], "fix": "Install it.",
            "command": "brew install gh", "done_when": "This row turns green.", "action": "true"}])

    def test_a_fix_part_that_is_not_one_line_of_text_is_refused_naming_it(self):
        for key in ("fix", "command", "done_when", "action"):
            for value in ('""', "3", '"  "', '"two\\nlines"'):
                with self.subTest(key=key, value=value):
                    self.write('[[requires]]\nname = "gh"\nkind = "command"\ncheck = "true"\nwhy = "w"\n'
                               f'{key} = {value}\n')
                    self.refused(f"demo/pack.toml: the demo pack's \\[\\[requires\\]\\] 'gh': "
                                 f"{key} must be one line of text")

    def test_a_command_or_a_done_when_needs_the_fix_it_belongs_to(self):
        for key in ("command", "done_when", "action"):
            with self.subTest(key=key):
                self.write('[[requires]]\nname = "gh"\nkind = "command"\ncheck = "true"\nwhy = "w"\n'
                           f'{key} = "x"\n')
                self.refused(f"the demo pack's \\[\\[requires\\]\\] 'gh': {key} needs a fix")

    def test_doctor_says_a_missing_tools_fix_under_the_pack_line(self):
        """c-688: `keel doctor` prints the pack's own fix for a tool that is missing: the
        sentence, the line to run, and how the user knows it worked."""
        from types import SimpleNamespace
        from keel import doctor, doctorpacks
        self.write('[[requires]]\nname = "gh"\nkind = "command"\ncheck = "false"\nwhy = "w"\n'
                   'fix = "Install it."\ncommand = "brew install gh"\ndone_when = "This row turns green."\n'
                   '[[requires]]\nname = "plain"\nkind = "command"\ncheck = "false"\nwhy = "w"\n'
                   '[[requires]]\nname = "found"\nkind = "command"\ncheck = "true"\nwhy = "w"\n'
                   'fix = "Never said."\n')
        space = SimpleNamespace(adapter="demo", adapter_dir=self.path, config_dir=self.path, repos={})
        self.assertIs(doctor.pack_lines, doctorpacks.pack_lines)
        self.assertEqual(doctorpacks.pack_lines(doctorpacks.pack_report(space, True, None)), [
            "  pack        demo 1  (1 of 3 tools found; missing: gh, plain)",
            "    gh: Install it.",
            "      run:  brew install gh",
            "      then: This row turns green."])

    def test_a_requirement_check_is_given_keel_home_so_a_pack_on_the_kit_finds_it(self):
        """c-735: a pack on the kit imports it through `KEEL_HOME`, wherever the pack lives,
        so doctor's run and Setup's run of its checks both hand it over."""
        from types import SimpleNamespace
        from keel import config, doctorpacks, packsetup
        from tests import helpers
        self.write('[[requires]]\nname = "kit"\nkind = "command"\nwhy = "w"\n'
                   'check = "test -f \\"$KEEL_HOME/keel/packkit/__init__.py\\""\n')
        with mock.patch.dict(os.environ):
            os.environ.pop("KEEL_HOME", None)
            space = SimpleNamespace(adapter="demo", adapter_dir=self.path, config_dir=self.path, repos={})
            self.assertEqual([tool["ok"] for tool in doctorpacks.pack_report(space, True, None)["tools"]], [True])
            cfg = helpers.make_config(self.path.parent / "keel")
            self.assertEqual(packsetup.pack_env(cfg, packs.load(self.path))["KEEL_HOME"], str(config.repo_root()))

    def test_a_pack_says_it_is_demo_only_with_true_or_false(self):
        self.write()
        self.assertFalse(packs.load(self.path).demo_only)
        self.write("demo_only = true\n")
        self.assertTrue(packs.load(self.path).demo_only)
        self.write('demo_only = "yes"\n')
        self.refused("demo_only must be true or false")

    def test_an_unknown_top_level_key_is_still_refused(self):
        self.write("[glossary]\nticket = \"story\"\n")
        self.refused("has no key glossary")

    # ----- [[setup]], a pack's own first-run steps (c-632) -----

    SETUP = ('[capabilities]\ntracker = true\n'
             '[[requires]]\nname = "token"\nkind = "secret"\ncheck = "true"\nwhy = "w"\nfor = ["tracker"]\n')

    def setup_step(self, body: str) -> None:
        (self.path / "setup").mkdir(exist_ok=True)
        (self.path / "setup" / "token.md").write_text("Make a token.\n")
        self.write(self.SETUP + "[[setup]]\n" + body, verbs=("act",))

    def test_a_valid_setup_step_loads(self):
        self.setup_step('id = "token"\ntitle = "Connect"\ntext = "setup/token.md"\nfor = ["tracker"]\n'
                        'requires = ["token"]\n')
        [step] = packs.load(self.path).setup
        self.assertEqual((step.id, step.title, step.after, step.serves, step.requires),
                         ("token", "Connect", "integrations", ("tracker",), ("token",)))
        self.assertEqual(step.text, self.path / "setup" / "token.md")

    def test_a_setup_step_after_the_old_spaces_step_follows_add_your_repos(self):
        """c-677: Spaces is part of Add your repos now, so a pack that names it still loads."""
        self.setup_step('id = "token"\ntitle = "Connect"\ntext = "setup/token.md"\nafter = "spaces"\n')
        [step] = packs.load(self.path).setup
        self.assertEqual(step.after, "repos")

    def test_each_broken_setup_step_is_refused_naming_it(self):
        good = 'id = "token"\ntitle = "Connect"\ntext = "setup/token.md"\n'
        for body, pattern in (
                (good + 'colour = "red"\n', "setup 'token' has no key colour"),
                ('id = "token"\ntitle = "Connect"\ntext = "setup/gone.md"\n', "setup/gone.md not in"),
                (good + 'for = ["codehost"]\n', "setup 'token' is for codehost, which \\[capabilities\\] does not declare"),
                (good + 'after = "lunch"\n', "setup 'token': after 'lunch' is not a step"),
                (good + 'requires = ["nothing"]\n', "setup 'token' requires nothing, which no \\[\\[requires\\]\\] names"),
                (good + "[[setup]]\n" + good, "setup 'token': the id is used twice")):
            with self.subTest(pattern=pattern):
                self.setup_step(body)
                self.refused(pattern)


class ConfiguredDriftTermsTest(unittest.TestCase):
    def test_an_installs_pack_terms_are_read_beside_the_trees(self):
        """r1.F7: once an owner's pack lives in the install, the employer-words checks read
        its terms from there, so they check rather than pass with nothing to check."""
        with tempfile.TemporaryDirectory() as tmp:
            install = Path(tmp) / "install"
            (install / "packs" / "mine").mkdir(parents=True)
            (install / "packs" / "mine" / packs.DRIFT_TERMS).write_text("# words\nacmecorp\n")
            (install / "config.toml").write_text("")
            with mock.patch.dict(os.environ, {"KEEL_CONFIG": str(install / "config.toml")}):
                found = packs.configured_drift_terms(Path(tmp) / "tree")
            with mock.patch.dict(os.environ, {"KEEL_CONFIG": ""}):
                none = packs.configured_drift_terms(Path(tmp) / "tree")
        self.assertEqual((found, none), (["acmecorp"], []))


class RealPacksTest(unittest.TestCase):
    """The sandbox, which ships with the core. The work pack's own manifest is held by its
    own suite (`packs/work/tests/test_manifest.py`, c-722), so this passes without it."""

    def test_the_sandbox_loads_and_declares_what_it_provides(self):
        pack = packs.load(packs.PACKAGE / "packs" / "sandbox")
        self.assertEqual(pack.capabilities, frozenset({"tracker", "codehost", "reviews"}))
        self.assertEqual(pack.routes, ("reviews",))

    def test_the_sandbox_is_demo_only_and_says_how_to_get_git(self):
        """c-688: the example runs only inside a demo sandbox, so it says so; and its one
        requirement carries its fix."""
        sandbox = packs.load(packs.PACKAGE / "packs" / "sandbox")
        self.assertTrue(sandbox.demo_only)
        git = sandbox.requires[0]
        self.assertEqual((git.name, git.command), ("git", "xcode-select --install"))
        self.assertTrue(git.fix and git.done_when)

    def test_the_sandbox_brings_one_setup_step(self):
        """c-632: there so a pack step is exercised on a scratch install."""
        sandbox = packs.load(packs.PACKAGE / "packs" / "sandbox").setup
        self.assertEqual([(s.id, s.after, s.requires) for s in sandbox], [("try", "integrations", ("git",))])


if __name__ == "__main__":
    unittest.main()
