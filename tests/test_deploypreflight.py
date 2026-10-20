"""The deploy's preflight (keel/deploypreflight.py, c-725 r1.F1, F2, F4): a tree is refused
while the install would read a path it removes or lose one owner's things it held, and passes
once the install holds them. Every tree, install and service file here is a scratch one."""

import os
import plistlib
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from keel import config as config_module, configedit, deploy, deploypreflight, movepersonal


def git(repo: Path, *argv: str) -> None:
    subprocess.run(["git", "-C", str(repo), *argv], check=True, capture_output=True)


def write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text)


def repo_of(path: Path, files: dict, links: dict | None = None) -> Path:
    for name, text in files.items():
        write(path / name, text)
    for name, target in (links or {}).items():
        (path / name).parent.mkdir(parents=True, exist_ok=True)
        (path / name).symlink_to(target)
    git(path.parent, "init", "-q", "-b", "main", str(path))
    git(path, "add", "-A")
    git(path, "-c", "user.name=t", "-c", "user.email=t@example.invalid", "commit", "-qm", "tree")
    return path


SHARED = {"bin/keel": "#!/bin/sh\n", "spaces/harbor/.claude/settings.json": "{}\n", "etc/space-personal.md": "# Personal space\n",
          "etc/pipeline-personal.md": "## Verify\n",
          "etc/shipyard.example.toml": (Path(__file__).resolve().parent.parent / "etc" / "shipyard.example.toml").read_text()}
OWNER = {"keel.toml": "[keel]\n", "packs/work/pack.toml": 'name = "work"\n',
         "packs/work/pipeline.md": "## Verify\nthe pack's own\n",
         "spaces/harbor/.claude/CLAUDE.md": "the owner's talker rules\n",
         "etc/space-personal.md": "# Personal space\n\n## The owner's rules\n"}


class PreflightCase(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.dir = Path(tmp.name).resolve()
        self.repo = repo_of(self.dir / "keel", {**SHARED, **OWNER},
                            {"adapters/work": "../packs/work"})
        self.tree = repo_of(self.dir / "tree", dict(SHARED))
        self.home = self.dir / "install"
        (self.home / "services").mkdir(parents=True)
        self.agents = self.dir / "LaunchAgents"
        self.agents.mkdir()
        self.config = self.home / "config.toml"
        self.config.write_text(
            f'[keel]\nstate_dir = "{self.home / "state"}"\nsegments_dir = "{self.home / "segments"}"\n'
            '[spaces.personal]\nconfig_dir = "~/x"\ncontract = "etc/space-personal.md"\n'
            'pipeline = "etc/pipeline-personal.md"\n'
            '[spaces.work]\nconfig_dir = "~/x"\npipeline = "adapters/work/pipeline.md"\n')

    def cfg(self):
        return config_module.load(self.config, ensure=False)

    def problems(self, loaded=()):
        return deploypreflight.problems(self.cfg(), self.repo, self.tree, agents=self.agents,
                                        loaded=None if loaded is None else set(loaded))

    def move(self):
        """The real `shipyard move-personal --checkout <repo>`, run from the new code (r2.F9),
        in the environment every Keel service hands down: KEEL_HOME names the old checkout
        (r3.F3). The code it runs from is the package root, here the tree."""
        said = []
        with mock.patch.dict(os.environ, {"KEEL_CONFIG": str(self.config), "KEEL_HOME": str(self.repo)}), \
                mock.patch.object(config_module, "package_root", return_value=self.tree):
            cfg = config_module.load(ensure=False)
            self.assertEqual(Path(cfg.root).resolve(), self.repo, "KEEL_HOME is the old checkout")
            self.assertEqual(movepersonal.Move(cfg, self.repo, dry=False, say=said.append).run(), 0, said)
        return said

    def plist(self, where: Path, label: str, env: dict) -> Path:
        path = where / f"{label}.plist"
        path.write_bytes(plistlib.dumps({"Label": label, "EnvironmentVariables": env}))
        return path


class OwnerTest(PreflightCase):
    def test_a_tree_that_drops_the_owners_things_waits_for_the_move(self):
        found = self.problems()
        self.assertTrue(found)
        self.assertTrue(all("move-personal --checkout" in line for line in found), found)
        self.assertTrue(all("KEEL_HOME=<new> <new>/bin/shipyard" in line for line in found), found)
        joined = "\n".join(found)
        for wanted in ("the work pack", "the talker's rulebook", "history keel.toml",
                       "[spaces.work] pipeline", "the personal space's contract"):
            self.assertIn(wanted, joined)
        self.move()
        self.assertTrue((self.home / "history" / "keel.toml").is_file())
        self.assertEqual(self.problems(), [])

    def test_a_tree_that_keeps_them_asks_nothing_of_the_install(self):
        same = repo_of(self.dir / "same", {**SHARED, **OWNER}, {"adapters/work": "../packs/work"})
        self.assertEqual(deploypreflight.problems(self.cfg(), self.repo, same, agents=self.agents,
                                                  loaded=set()), [])


class ServicesTest(PreflightCase):
    def setUp(self):
        super().setUp()
        self.move()

    def test_a_loaded_service_with_no_keel_config_waits_for_its_reinstall(self):
        env = {"KEEL_HOME": str(self.repo), "KEEL_ADAPTERS_DIR": str(self.repo / "adapters")}
        self.plist(self.agents, "dev.keel.voice", env)
        found = self.problems(loaded={"dev.keel.voice"})
        self.assertEqual(len(found), 2, found)
        self.assertTrue(all(f"KEEL_CONFIG={self.config} {self.repo}/bin/keel voice install --load" in line
                            for line in found), found)
        self.plist(self.agents, "dev.keel.voice", {**env, "KEEL_CONFIG": str(self.config)})
        self.assertEqual(self.problems(loaded={"dev.keel.voice"}), [])

    def test_an_agent_not_loaded_is_read_too_and_named_with_its_removal(self):
        """r2.F3: it loads at the next login."""
        path = self.plist(self.agents, "dev.shipyard.deck", {"KEEL_HOME": str(self.repo)})
        found = self.problems(loaded=set())
        self.assertEqual(len(found), 1, found)
        self.assertIn("not loaded now but loads at the next login", found[0])
        self.assertTrue(found[0].endswith(f"remove it: `rm {path}`"), found[0])
        self.assertIn("/bin/shipyard service install`; it is not loaded now", found[0], "each command quoted alone")

    def test_the_old_engines_agent_is_named_with_its_bootout_and_removal(self):
        """r3.F8: no install command renders `dev.keel` any more, so `service install` would
        never touch it; its step is to boot it out and remove it, loaded or not."""
        path = self.plist(self.agents, "dev.keel", {"KEEL_HOME": str(self.repo)})
        for loaded, step in (({"dev.keel"}, f"`launchctl bootout gui/$(id -u)/dev.keel && rm {path}`"),
                             (set(), f"`rm {path}`")):
            found = self.problems(loaded=loaded)
            self.assertEqual(len(found), 1, found)
            self.assertIn(f"which this tree removes; run {step} (the old engine", found[0])
            self.assertNotIn("service install", found[0])

    def test_launchd_that_cannot_be_read_refuses_rather_than_passes(self):
        """r2.F3."""
        self.plist(self.agents, "dev.keel.voice", {"KEEL_HOME": str(self.repo), "KEEL_CONFIG": str(self.config)})
        self.assertEqual(self.problems(loaded={"dev.keel.voice"}), [])
        found = self.problems(loaded=None)
        self.assertEqual(len(found), 1, found)
        self.assertIn("launchctl list could not be read", found[0])
        with mock.patch.object(deploypreflight.subprocess, "run", side_effect=OSError("no launchctl")), \
                mock.patch.object(deploypreflight.sys, "platform", "darwin"):
            self.assertIsNone(deploypreflight.launchd_loaded())

    def test_an_agent_with_no_keel_home_is_not_this_checkouts(self):
        """r2.F2: run from the checkout itself, as the deploy worker is, an agent that sets no
        KEEL_HOME is still none of this checkout's."""
        self.plist(self.agents, "homebrew.mxcl.bar", {"PATH": "/usr/bin"})
        before = os.getcwd()
        self.addCleanup(os.chdir, before)
        os.chdir(self.repo)
        self.assertEqual(self.problems(loaded={"homebrew.mxcl.bar"}), [])
        self.assertIsNone(deploypreflight.in_repo("", self.repo))

    def test_an_untracked_path_the_fresh_tree_lacks_is_not_removed_by_it(self):
        """r3.F9: the deploy tree is a fresh checkout of tracked files, so a setting naming an
        untracked or ignored path of the checkout (a venv, a generated dir) is not one the
        tree removes."""
        write(self.repo / ".venv-tools" / "bin" / "python", "#!/bin/sh\n")
        self.config.write_text(self.config.read_text() + '[machine]\nusage_file = ".venv-tools/bin/python"\n')
        self.assertNotIn("usage_file", "\n".join(self.problems()))

    def test_any_path_setting_the_tree_removes_is_refused(self):
        """r2.F10: a space's repos entry and a [machine] path, not only contract and pipeline."""
        write(self.repo / "tools" / "x.md", "x\n")
        git(self.repo, "add", "-A")
        git(self.repo, "-c", "user.name=t", "-c", "user.email=t@example.invalid", "commit", "-qm", "tools")
        text = configedit.set_entry(self.config.read_text(), "spaces.personal.repos", "tools", "tools")
        self.config.write_text(configedit.set_entry(text, "machine", "usage_file", "tools/x.md"))
        found = self.problems()
        self.assertIn("[spaces.personal.repos] tools names tools, which this tree removes", "\n".join(found))
        self.assertIn("[machine] usage_file names tools/x.md, which this tree removes", "\n".join(found))
        machine = next(line for line in found if line.startswith("[machine] usage_file"))
        self.assertIn(f"edit `[machine] usage_file` in {self.config}", machine, "the move never edits a machine key")
        self.assertNotIn("move-personal", machine)
        repos = next(line for line in found if line.startswith("[spaces.personal.repos] tools"))
        self.assertNotIn("move-personal", repos, "nor a space's repos entry")

    def test_a_space_file_spelled_absolute_is_an_edit_since_the_move_leaves_it(self):
        """c-726 r2 fix check: the move points only a relative `contract` or `pipeline`; one
        spelled absolute (or from ~) is the install's own choice, which it leaves, so the fix
        for it is the config edit."""
        value = f"{self.repo}/packs/work/pipeline.md"
        self.config.write_text(configedit.set_entry(self.config.read_text(), "spaces.work", "pipeline", value))
        line = next(line for line in self.problems() if line.startswith("[spaces.work] pipeline names"))
        self.assertIn(f"edit `[spaces.work] pipeline` in {self.config}", line)
        self.assertNotIn("move-personal", line)

    def test_an_adapters_dir_the_tree_still_holds_is_not_refused(self):
        """c-726 r2.F1, the reproduction: the install says `[machine] adapters_dir = "adapters"`
        and the tree drops only `adapters/work`, keeping `adapters/` (its sandbox link): the
        directory still resolves, so nothing is refused for it. A tree that drops the whole
        directory is refused with the config edit that clears it."""
        old = repo_of(self.dir / "old", {**SHARED, **OWNER, "packs/sandbox/pack.toml": 'name = "sandbox"\n'},
                      {"adapters/work": "../packs/work", "adapters/sandbox": "../packs/sandbox"})
        kept = repo_of(self.dir / "kept", {**SHARED, "packs/sandbox/pack.toml": 'name = "sandbox"\n'},
                       {"adapters/sandbox": "../packs/sandbox"})
        self.config.write_text(configedit.set_entry(self.config.read_text(), "machine", "adapters_dir", "adapters"))
        found = deploypreflight.problems(self.cfg(), old, kept, agents=self.agents, loaded=set())
        self.assertFalse([line for line in found if "adapters_dir" in line], found)
        bare = repo_of(self.dir / "bare", {**SHARED, "packs/sandbox/pack.toml": 'name = "sandbox"\n'})
        found = deploypreflight.problems(self.cfg(), old, bare, agents=self.agents, loaded=set())
        line = next(line for line in found if line.startswith("[machine] adapters_dir"))
        self.assertIn(f"edit `[machine] adapters_dir` in {self.config}", line)

    def test_a_rendered_talker_waits_for_its_rulebook_in_the_install(self):
        self.plist(self.home / "services", "dev.keel.talker",
                   {"KEEL_HOME": str(self.repo), "KEEL_CONFIG": str(self.config),
                    "CLAUDE_CONFIG_DIR": str(self.repo / "spaces" / "harbor" / ".claude")})
        self.assertEqual(self.problems(), [])
        (self.home / "memory" / "talker" / "CLAUDE.md").unlink()
        found = self.problems()
        self.assertTrue(any("runs the talker from spaces/harbor/.claude" in line for line in found), found)

    def test_a_config_path_the_tree_removes_is_refused(self):
        self.config.write_text(self.config.read_text().replace(
            f'pipeline = "{self.home / "packs" / "work" / "pipeline.md"}"', 'pipeline = "adapters/work/pipeline.md"'))
        found = self.problems()
        self.assertIn(f"[spaces.work] pipeline names adapters/work/pipeline.md, which this tree removes; "
                      f"run `{deploypreflight.move_command(self.cfg(), self.repo)}`, {deploypreflight.NEW}", found)


class InstallTextTest(PreflightCase):
    """c-726 r1.F1: the install's own text (its memory, identity, space files and the talker's
    rulebook) that names a checkout path the tree drops would send a reader to nothing."""

    def test_a_note_naming_a_dropped_checkout_path_is_refused_until_it_names_the_install(self):
        self.move()
        note = self.home / "memory" / "talker" / "where.md"
        write(note, f"the old config is {self.repo}/keel.toml\nthe engine is {self.repo}/bin/keel\n"
                    f"its config dir is {self.repo}/spaces/harbor/.claude, its rulebook gone\n")
        contract = self.home / "spaces" / "personal" / "space-personal.md"
        write(contract, f"# Personal space\n\nthe pack is at `{self.repo}/packs/work/`.\n")
        found = self.problems(loaded=set())
        self.assertEqual(len(found), 2, found)
        joined = "\n".join(found)
        self.assertIn(f"{note}:1 names {self.repo}/keel.toml, which this tree removes", joined)
        self.assertIn(f"{contract}:3 names {self.repo}/packs/work/, which this tree removes", joined)
        self.assertNotIn("bin/keel", joined, "a path the tree keeps is fine")
        self.assertNotIn("spaces/harbor/.claude", joined, "and so is a directory it keeps, some files gone")
        write(note, f"the old config is {self.home}/history/keel.toml\n")
        write(contract, "# Personal space\n")
        self.assertEqual(self.problems(loaded=set()), [])

    def test_a_pack_s_text_and_brief_code_are_read_too(self):
        """c-726 r2.F6: a work house reads its pack's pipeline and brief text, so the install's
        own packs are read, their nested .md and .py as well, and the fix is a pack card."""
        self.move()
        brief = self.home / "packs" / "work" / "rules" / "house.md"
        write(brief, f"open the pipeline at `{self.repo}/packs/work/pipeline.md`\n")
        code = self.home / "packs" / "work" / "briefing.py"
        write(code, f'PIPE = "{self.repo}/packs/work/pipeline.md"\n')
        found = self.problems(loaded=set())
        joined = "\n".join(found)
        self.assertIn(f"{brief}:1 names {self.repo}/packs/work/pipeline.md, which this tree removes", joined)
        self.assertIn(f"{code}:1 names {self.repo}/packs/work/pipeline.md, which this tree removes", joined)
        self.assertIn("a pack card", joined)
        write(self.home / "packs" / "work" / "tests" / "test_brief.py", f'WANT = "{self.repo}/packs/work/pipeline.md"\n')
        self.assertNotIn("test_brief.py", "\n".join(self.problems(loaded=set())), "a pack's tests instruct no one")

    def test_the_keel_home_spelling_is_read_too(self):
        """c-726 r2.F6: a brief tells houses to run `$KEEL_HOME/packs/work/pr`; KEEL_HOME is the
        live checkout, so that path is gone with the tree. One the tree keeps is fine."""
        self.move()
        brief = self.home / "packs" / "work" / "rules" / "house.md"
        write(brief, "run `$KEEL_HOME/packs/work/pipeline.md` then `${KEEL_HOME}/keel.toml`, and `$KEEL_HOME/bin/keel`\n")
        found = self.problems(loaded=set())
        joined = "\n".join(found)
        self.assertIn(f"{brief}:1 names $KEEL_HOME/packs/work/pipeline.md, which this tree removes", joined)
        self.assertIn(f"{brief}:1 names ${{KEEL_HOME}}/keel.toml, which this tree removes", joined)
        self.assertNotIn("bin/keel", joined)

    def test_each_space_s_config_dir_rulebook_is_read_too(self):
        """c-726 r2.F6: a house of the space reads its config dir's CLAUDE.md as instructions."""
        self.move()
        config_dir = self.dir / "personal-claude"
        self.config.write_text(configedit.set_entry(self.config.read_text(), "spaces.personal",
                                                    "config_dir", str(config_dir)))
        rules = config_dir / "CLAUDE.md"
        write(rules, f"the owner's config is {self.repo}/keel.toml\n")
        found = self.problems(loaded=set())
        self.assertIn(f"{rules}:1 names {self.repo}/keel.toml, which this tree removes", "\n".join(found))

    def test_the_checkout_is_found_however_it_is_spelled(self):
        home = Path("/home/someone")
        self.assertEqual(deploypreflight.spellings(home / "keel", home), [str(home / "keel") + "/", "~/keel/"])
        self.assertEqual(deploypreflight.spellings(Path("/srv/keel"), home), ["/srv/keel/"])


class WorkerTest(unittest.TestCase):
    def test_the_worker_refuses_on_a_problem_and_asks_only_for_its_own_checkout(self):
        cfg = mock.Mock(root=Path("/code"))
        with mock.patch.object(deploypreflight, "problems", return_value=["a missing thing; run `x`"]) as asked:
            with self.assertRaises(deploy.NotDeployed) as caught:
                deploy.preflight(cfg, Path("/code"), Path("/tree"))
            self.assertIn("a missing thing; run `x`", str(caught.exception))
            deploy.preflight(cfg, Path("/elsewhere"), Path("/tree"))
            self.assertEqual(asked.call_count, 1)
        with mock.patch.object(deploypreflight, "problems", return_value=[]):
            deploy.preflight(cfg, Path("/code"), Path("/tree"))


if __name__ == "__main__":
    unittest.main()
