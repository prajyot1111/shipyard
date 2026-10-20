"""adapters: the personal git fallback on a throwaway repo, cross-repo, and adapter verbs."""

import json
import os
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from keel import adapters
from tests.helpers import make_config, make_repo


def branches(repo: Path) -> list[str]:
    out = subprocess.run(["git", "-C", str(repo), "for-each-ref", "--format=%(refname:short)",
                          "refs/heads/"], capture_output=True, text=True, check=True).stdout
    return sorted(out.split())


def current_branch(worktree: Path) -> str:
    return subprocess.run(["git", "-C", str(worktree), "branch", "--show-current"],
                          capture_output=True, text=True, check=True).stdout.strip()


class PersonalWorktreeTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name)
        self.repo = make_repo(self.dir / "repo")
        self.other = make_repo(self.dir / "other")
        self.cfg = make_config(self.dir, repos={"repo": self.repo, "other": self.other})

    def tearDown(self):
        self.tmp.cleanup()

    def card(self, card_id="c-900", repo="repo", title="Add `keel doctor`: a role-less verb!"):
        return {"id": card_id, "space": "personal", "title": title, "repo": repo, "options": {}}

    def test_worktree_is_cut_under_state_on_a_card_branch(self):
        paths = adapters.worktree(self.cfg, self.card())
        self.assertEqual(paths, [self.cfg.worktrees_dir / "c-900"])
        self.assertEqual(current_branch(paths[0]), "shipyard/c-900-add-keel-doctor-a-role-less-verb")
        self.assertTrue((paths[0] / "README").exists())

    def test_a_worktree_gets_the_voice_venv_so_its_suite_runs_voice(self):
        """2026-09-26: house worktrees had no .venv-voice, so a house's own make test skipped
        voice and a voice break showed only at the landing or the deploy."""
        venv = self.repo / ".venv-voice" / "bin"
        venv.mkdir(parents=True)
        (venv / "python").write_text("#!/bin/sh\n")
        (venv / "python").chmod(0o755)      # the Makefile and link_voice ask for -x (c-646)
        path = adapters.worktree(self.cfg, self.card())[0]
        self.assertTrue((path / ".venv-voice").is_symlink())
        self.assertEqual((path / ".venv-voice").resolve(), (self.repo / ".venv-voice").resolve())
        status = subprocess.run(["git", "-C", str(path), "status", "--porcelain"],
                                capture_output=True, text=True).stdout
        self.assertNotIn(".venv-voice", status, "the link is ignored, never committed")

    def test_recreate_reuses_the_branch_even_when_the_title_changed(self):
        first = adapters.worktree(self.cfg, self.card())[0]
        self.assertEqual(adapters.worktree(self.cfg, self.card())[0], first)
        subprocess.run(["git", "-C", str(self.repo), "worktree", "remove", "--force", str(first)],
                       check=True)
        self.assertFalse(first.exists())
        again = adapters.worktree(self.cfg, self.card(title="renamed"))[0]
        self.assertEqual(again, first)
        self.assertEqual(current_branch(again), "shipyard/c-900-add-keel-doctor-a-role-less-verb")
        self.assertEqual(branches(self.repo), ["main", "shipyard/c-900-add-keel-doctor-a-role-less-verb"])

    def test_a_space_s_own_branch_pattern_names_the_branch_and_finds_it_again(self):
        """c-665: `[spaces.<name>] branch` names a card's branch in a space with no pack, and
        a recreate finds the branch by the same pattern."""
        self.cfg.spaces["personal"].branch = "cards/{id}/{slug}"
        first = adapters.worktree(self.cfg, self.card())[0]
        self.assertEqual(current_branch(first), "cards/c-900/add-keel-doctor-a-role-less-verb")
        subprocess.run(["git", "-C", str(self.repo), "worktree", "remove", "--force", str(first)],
                       check=True)
        again = adapters.worktree(self.cfg, self.card(title="renamed"))[0]
        self.assertEqual(current_branch(again), "cards/c-900/add-keel-doctor-a-role-less-verb")
        self.assertEqual(branches(self.repo), ["cards/c-900/add-keel-doctor-a-role-less-verb", "main"])

    def test_a_changed_pattern_does_not_strand_a_card_already_cut(self):
        """c-665 review: a card cut under the default keeps its branch when the space's
        pattern changes."""
        first = adapters.worktree(self.cfg, self.card())[0]
        subprocess.run(["git", "-C", str(self.repo), "worktree", "remove", "--force", str(first)], check=True)
        self.cfg.spaces["personal"].branch = "cards/{id}/{slug}"
        again = adapters.worktree(self.cfg, self.card())[0]
        self.assertEqual(current_branch(again), "shipyard/c-900-add-keel-doctor-a-role-less-verb")
        self.assertEqual(branches(self.repo), ["main", "shipyard/c-900-add-keel-doctor-a-role-less-verb"])

    def test_a_branch_the_card_records_is_never_adopted(self):
        """c-665 review pass 2: `options.branch` naming another branch changes nothing, under
        the default pattern or a custom one: the card gets its own branch, as it always did."""
        subprocess.run(["git", "-C", str(self.repo), "branch", "-q", "by-hand/thing"], check=True)
        named = dict(self.card("c-901"), options={"branch": "by-hand/thing"})
        self.assertEqual(current_branch(adapters.worktree(self.cfg, named)[0]),
                         "shipyard/c-901-add-keel-doctor-a-role-less-verb")
        self.cfg.spaces["personal"].branch = "cards/{id}/{slug}"
        other = dict(self.card("c-902"), options={"branch": "by-hand/thing"})
        self.assertEqual(current_branch(adapters.worktree(self.cfg, other)[0]),
                         "cards/c-902/add-keel-doctor-a-role-less-verb")

    def test_under_the_default_pattern_only_it_and_the_old_default_are_looked_under(self):
        """c-665 review pass 2: with nothing set, the lookup is the default pattern's; since
        c-729 the default before it too, so a card cut under it is found."""
        with mock.patch.object(adapters, "existing_branch", wraps=adapters.existing_branch) as looked:
            self.assertIsNone(adapters.card_branch(self.repo, self.card()))
            self.assertIsNone(adapters.card_branch(self.repo, self.card(), adapters.BRANCH))
        self.assertEqual([call.args[1:] for call in looked.call_args_list],
                         [("c-900", None), ("c-900", adapters.LEGACY_BRANCH),
                          ("c-900", adapters.BRANCH), ("c-900", adapters.LEGACY_BRANCH)])

    def test_a_new_card_branch_says_shipyard_and_one_cut_as_keel_before_is_kept(self):
        """c-729: the stranger run's repo history read keel/c-5-...; a new card's branch is
        named for the product, and a card cut under the old prefix keeps its branch."""
        self.assertEqual(adapters.BRANCH, "shipyard/{id}-{slug}")
        subprocess.run(["git", "-C", str(self.repo), "branch", "-q", "keel/c-900-cut-before"], check=True)
        path = adapters.worktree(self.cfg, self.card())[0]
        self.assertEqual(current_branch(path), "keel/c-900-cut-before")
        self.assertEqual(current_branch(adapters.worktree(self.cfg, self.card("c-901"))[0]),
                         "shipyard/c-901-add-keel-doctor-a-role-less-verb")
        self.cfg.spaces["personal"].branch = "cards/{id}/{slug}"
        subprocess.run(["git", "-C", str(self.repo), "branch", "-q", "keel/c-902-cut-before"], check=True)
        self.assertEqual(current_branch(adapters.worktree(self.cfg, self.card("c-902"))[0]), "keel/c-902-cut-before",
                         "and under a pattern of the space's own too")

    def test_one_card_s_pattern_never_finds_another_card_s_branch(self):
        """c-665 review F8: c-1 and c-10 under a custom pattern."""
        pattern = "work/{id}-{slug}"
        for name in ("work/c-10-ten", "work/c-1-one"):
            subprocess.run(["git", "-C", str(self.repo), "branch", "-q", name], check=True)
        self.assertEqual(adapters.existing_branch(self.repo, "c-1", pattern), "work/c-1-one")
        self.assertEqual(adapters.existing_branch(self.repo, "c-10", pattern), "work/c-10-ten")
        self.assertIsNone(adapters.existing_branch(self.repo, "c-100", pattern))
        # review pass 2: the name must match the WHOLE pattern, a slug being one path part
        subprocess.run(["git", "-C", str(self.repo), "branch", "-q", "c-1/other"], check=True)
        self.assertIsNone(adapters.existing_branch(self.repo, "c-1", "{id}"))
        self.assertIsNone(adapters.existing_branch(self.repo, "c-1", "{id}/{slug}/x"))
        self.assertEqual(adapters.existing_branch(self.repo, "c-1", "{id}/{slug}"), "c-1/other")
        self.assertEqual(adapters.existing_branch(self.repo, "c-1.5", "work/{id}-{slug}"), None)

    def test_recreate_survives_a_directory_deleted_behind_gits_back(self):
        first = adapters.worktree(self.cfg, self.card())[0]
        subprocess.run(["rm", "-rf", str(first)], check=True)
        self.assertEqual(adapters.worktree(self.cfg, self.card())[0], first)
        self.assertTrue((first / ".git").exists())

    def test_cross_repo_card_gets_one_worktree_per_repo(self):
        paths = adapters.worktree(self.cfg, self.card(card_id="c-901", repo="repo, other"))
        self.assertEqual(paths, [self.cfg.worktrees_dir / "c-901", self.cfg.worktrees_dir / "c-901-other"])
        self.assertEqual(current_branch(paths[1]), "shipyard/c-901-add-keel-doctor-a-role-less-verb")

    def test_errand_has_no_worktree_and_unknown_repo_is_clear(self):
        self.assertEqual(adapters.worktree(self.cfg, self.card(repo=None)), [])
        with self.assertRaises(adapters.AdapterError) as caught:
            adapters.worktree(self.cfg, self.card(repo="nowhere"))
        self.assertIn("nowhere", str(caught.exception))

    def test_brief_is_the_space_contract_and_publish_is_a_noop(self):
        text = adapters.brief(self.cfg, self.card())
        self.assertTrue(text.startswith("# Personal space"))
        self.assertIsNone(adapters.publish(self.cfg, self.card()))


class AdapterVerbTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name)
        self.cfg = make_config(self.dir)
        self.space = self.cfg.spaces["work"]
        self.card = {"id": "c-7", "space": "work", "title": "t", "repo": "api", "options": {}}

    def tearDown(self):
        self.tmp.cleanup()

    def verb(self, name: str, body: str) -> Path:
        path = self.space.adapter_dir / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("#!/bin/sh\n" + body + "\n")
        path.chmod(0o755)
        return path

    def test_missing_adapter_directory_and_verb_are_clear_errors(self):
        with self.assertRaises(adapters.AdapterError) as caught:
            adapters.run(self.space, "worktree", "c-7")
        self.assertIn("missing", str(caught.exception))
        self.verb("brief", 'echo "brief for $1"')
        with self.assertRaises(adapters.AdapterError) as caught:
            adapters.run(self.space, "worktree", "c-7")
        self.assertIn("worktree", str(caught.exception))
        with self.assertRaises(adapters.AdapterError):
            adapters.run(self.cfg.spaces["personal"], "brief", "c-7")

    def test_verb_runs_with_keel_home_and_kb_on_path(self):
        self.verb("brief", 'echo "brief for $1 $2 from $KEEL_HOME"; command -v kb')
        out = adapters.run(self.space, "brief", "c-7", "extra")
        self.assertIn("brief for c-7 extra from", out)
        self.assertIn("/bin/kb", out)

    def test_every_verb_is_told_the_space_it_runs_for(self):
        """c-730: a pack may serve several spaces, and a verb with no card (the review scan,
        a provider, a route's verb) could not tell which one it answers for; `KEEL_SPACE`
        says it."""
        self.verb("review", 'echo "{\\"space\\": \\"$KEEL_SPACE\\"}"')
        self.verb("providers/reviews", 'echo "{\\"space\\": \\"$KEEL_SPACE\\"}"')
        self.verb("act", 'echo "{\\"space\\": \\"$KEEL_SPACE\\"}"')
        self.space.adapter_dir.joinpath("pack.toml").unlink(missing_ok=True)   # an older adapter: routes are fixed
        self.assertEqual(json.loads(adapters.run(self.space, "review", "scan")), {"space": "work"})
        self.assertEqual(adapters.providers_for(self.space)["reviews"], {"space": "work"})
        self.assertEqual(adapters.run_act(self.space, "reviews", "scan_now", "", {}), {"space": "work"})

    def test_act_verbs_and_links_are_told_it_too_and_an_inherited_one_never_leaks(self):
        """r1.F5, r1.F7 (3): `act verbs` and `act links` run with the space as well, and a
        `KEEL_SPACE` in Keel's own environment never reaches a verb in place of the real one."""
        self.verb("act", 'if [ "$1" = verbs ]; then echo "{\\"card\\": [], \\"space\\": \\"$KEEL_SPACE\\"}"; '
                         'else echo "{\\"c-7\\": {\\"space\\": \\"$KEEL_SPACE\\"}}"; fi')
        with mock.patch.dict(os.environ, {"KEEL_SPACE": "stale"}):
            self.assertEqual(adapters.card_verbs(self.space)["space"], "work")
            self.assertEqual(adapters.card_links(self.space, ["c-7"])["c-7"]["space"], "work")
            self.assertNotIn("KEEL_SPACE", adapters.adapter_env())

    def test_worktree_and_brief_and_publish_go_through_the_adapter(self):
        target = self.dir / "wt"
        self.verb("worktree", f'mkdir -p "{target}"; echo "{target}"')
        self.verb("brief", 'echo "work half for $1"')
        self.verb("publish", 'echo "https://example.invalid/pr/1"')
        self.space.branch = "cards/{id}/{slug}"      # c-665: a pack names its own branches
        self.assertEqual(adapters.worktree(self.cfg, self.card), [target])
        self.assertFalse((target / ".git").exists(), "Keel cut nothing: the worktree is the pack's")
        text = adapters.brief(self.cfg, self.card)
        self.assertTrue(text.startswith("# Work space"))
        self.assertTrue(text.endswith("work half for c-7"))
        self.assertEqual(adapters.publish(self.cfg, self.card), "https://example.invalid/pr/1")

    def test_publish_is_handed_the_tap_s_nonce_and_an_inherited_one_never_leaks(self):
        """c-738 r1.F3: the nonce of the user's tap reaches the pack's `publish` only when Keel hands
        it (`adapters.publisher(..., nonce=)`), and one in Keel's own environment never does."""
        from keel.packkit import pulls       # the kit reads it under the same name
        self.assertEqual(pulls.NONCE_ENV, adapters.NONCE_ENV)
        self.verb("publish", 'echo "nonce=$KEEL_PUBLISH_NONCE"')
        with mock.patch.dict(os.environ, {adapters.NONCE_ENV: "inherited"}):
            self.assertEqual(adapters.publisher(self.cfg, "work", nonce="n0nce")(self.card), "nonce=n0nce")
            self.assertEqual(adapters.publish(self.cfg, self.card), "nonce=")
            self.assertNotIn(adapters.NONCE_ENV, adapters.adapter_env())

    def test_failing_verb_reports_its_stderr(self):
        self.verb("worktree", 'echo "no such repo" >&2; exit 3')
        with self.assertRaises(adapters.AdapterError) as caught:
            adapters.worktree(self.cfg, self.card)
        self.assertIn("exited 3", str(caught.exception))
        self.assertIn("no such repo", str(caught.exception))

    def test_non_executable_verb_is_absent(self):
        path = self.verb("brief", "echo x")
        path.chmod(0o644)
        self.assertFalse(adapters.has_verb(self.space, "brief"))
        self.assertTrue(os.access(path, os.R_OK))
