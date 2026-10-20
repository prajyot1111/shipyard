"""Where work lands has one source (c-734 C): a card's own base, else the repo's default branch as
its remote names it (`refs/remotes/<remote>/HEAD`), never whichever branch the copy has out.

The second stranger run (2026-10-10): the user answered "staging" to Bosun's question about
where finished work lands, the adopted CLAUDE.md said `Finished work lands on staging`, and
Adopt switched Shipyard's copy of the repo to staging (`repocommands.apply_lands`, c-678). Since
c-732 a card naming no base landed on the branch the copy had out, so every such card would
have gone to staging, and Bosun's next plan read staging as the repo's usual branch. Now
adopting or saving the file checks nothing out, its lands line is retired (the page says so),
and a copied repo's usual branch is the remote's default. A checkout of the user's own and a
repo with an integration branch keep their rules. On a real scratch install from `shipyard
init` with a team remote whose default is main and which has staging; no session is started."""

from tests.test_bases import Cards, git, team_remote
from keel import firstrunsteps, landpush, merging, tiercards
from keel.board import open_board

DRAFT = """# shop

## Prepare and test

- Prepare a fresh copy: `true`
- Run the tests: `true`

## Where work lands

- Finished work lands on `staging`.
"""


class Ready(Cards):
    def setUp(self):
        super().setUp()
        self.repo = self.with_team()

    def draft_ready(self, text=DRAFT) -> str:
        """Bosun's part: the shop draft written and staged for the user's Adopt."""
        cfg = self.cfg()
        with open_board(cfg) as board:
            card = tiercards.proposals(board)["team/shop"]["card"]
            out = tiercards.bosun_folder(cfg, card) / tiercards.PROPOSAL
            out.parent.mkdir(parents=True, exist_ok=True)
            out.write_text(text)
            board.stage(card, "building", "bosun")
            board.stage(card, "review", "bosun", output_ref=str(out))
        return card

    def out(self) -> str:
        return git(self.repo, "branch", "--show-current")


class AdoptTest(Ready):
    def test_adopting_a_file_that_names_another_branch_checks_nothing_out(self):
        done = self.act({"verb": "setup.tier.adopt", "card": self.draft_ready()})
        self.assertEqual(self.out(), "main", "the copy keeps the branch it was cloned on")
        self.assertIn("moves nothing", done["note"])
        self.assertIn("main", done["note"], "and it says where a card naming no base lands")

    def test_the_sentence_names_where_a_card_really_lands(self):
        """r1.F7: the integration branch where there is one; the checkout where the remote names
        no default."""
        from keel import repocommands
        self.act({"verb": "setup.tier.save", "space": "team", "key": "shop", "text": DRAFT})
        git(self.repo, "remote", "set-head", "origin", "-d")
        said = repocommands.lands_said(self.cfg(), "team", "shop")
        self.assertIn("else on main, the branch the copy has out", said)
        path = self.home / "config.toml"
        path.write_text(path.read_text().replace("[integration]\n", '[integration]\nshop = "next"\n', 1))
        said = repocommands.lands_said(self.cfg(), "team", "shop")
        self.assertIn("lands on next, its integration branch, and takes no base", said)
        self.assertNotIn("its own base", said)

    def test_saving_the_file_checks_nothing_out_either(self):
        done = self.act({"verb": "setup.tier.save", "space": "team", "key": "shop", "text": DRAFT})
        self.assertEqual(self.out(), "main")
        self.assertIn("moves nothing", done["note"])


class TemplateTest(Ready):
    def test_the_template_has_no_lands_line_and_a_tier_left_at_the_old_one_is_still_unwritten(self):
        from keel import repolayout, tierdrafts
        cfg = self.cfg()
        self.assertNotIn("Finished work lands on", repolayout.template(cfg.root, "repo", space="team", key="shop"))
        old = repolayout.unwritten(cfg.root, "repo", space="team", key="shop")[1]
        self.assertIn("Finished work lands on", old)
        self.assertNotIn("Where work lands", repolayout.template(cfg.root, "space", space="team"), "r1.F6")
        old_space = repolayout.unwritten(cfg.root, "space", space="team")[1]
        self.assertIn("Where work lands", old_space)
        from keel import readiness
        (self.home / "spaces" / "team" / "CLAUDE.md").write_text(old_space)
        self.assertFalse(readiness.rules_row(cfg, cfg.spaces["team"])["ready"], "a space tier left at it is unwritten")
        (self.home / "spaces" / "team" / "shop" / "CLAUDE.md").write_text(old)
        with open_board(cfg) as board:
            board.conn.execute("UPDATE cards SET stage = 'done'")     # no draft open: the file alone decides
            board.conn.commit()
            self.assertEqual([r["state"] for r in tierdrafts.rows(cfg, board, "team")], ["idle"])


class BriefTest(Ready):
    """c-734 point 8: Bosun's draft brief says what each line makes Shipyard do, never asks
    where work lands, and an ask whose answer moves something says so in its option."""

    def test_the_draft_brief_says_what_each_line_does(self):
        from keel import repofile
        cfg = self.cfg()
        with open_board(cfg) as board:
            brief = board.get(tiercards.proposals(board)["team/shop"]["card"])["brief"]
        for said in repofile.DOES.values():
            self.assertIn(said, brief)
        self.assertIn("say what it moves in that option's own text", brief)
        self.assertIn("Do not ask where finished work lands", brief)

    def test_bosuns_shipped_asks_say_an_option_that_moves_something_says_so(self):
        asks = (self.cfg().root / "templates" / "memory" / "bosun" / "asks.md").read_text()
        self.assertIn("says what it moves", asks)


class LandTest(Ready):
    def test_a_card_naming_no_base_lands_on_the_remotes_default_whatever_the_copy_has_out(self):
        git(self.repo, "checkout", "-q", "staging")          # what an Adopt before c-734 left
        card = self.card("c-1")
        tree = self.build(card, "plain.txt")
        self.assertFalse((tree / "STAGING.md").exists(), "cut from main, the remote's default")
        staging = git(self.repo, "rev-parse", "staging")
        self.assertIn("merged into main", merging.publish(self.cfg(), card))
        self.assertIn("plain.txt", git(self.repo, "ls-tree", "--name-only", "main"))
        self.assertEqual(git(self.repo, "rev-parse", "staging"), staging, "staging is untouched")
        self.assertEqual(self.out(), "staging", "and nothing switched the copy's checkout")

    def test_a_card_naming_a_base_still_lands_on_it(self):
        git(self.repo, "checkout", "-q", "staging")
        card = self.card("c-1", "main")
        self.build(card, "on-main.txt")
        self.assertIn("merged into main", merging.publish(self.cfg(), card))

    def test_the_page_names_the_remotes_default(self):
        git(self.repo, "checkout", "-q", "staging")
        cfg = self.cfg()
        self.assertEqual([r["branch"] for r in landpush.panel(cfg)["team"]["repos"]], ["main"])
        self.assertEqual(firstrunsteps.bases_of(cfg, cfg.spaces["team"])["suggested"], "main")


class RemoteHeadTest(Ready):
    """r1.F4, F13: the remote's default is used only while it resolves, and followed when the
    team changes it."""

    def test_a_copy_whose_remote_names_no_default_lands_on_its_checkout(self):
        git(self.dir / "remote.git", "symbolic-ref", "HEAD", "refs/heads/nothing")   # the remote names none
        git(self.repo, "remote", "set-head", "origin", "-d")
        git(self.repo, "branch", "staging", "refs/remotes/origin/staging")
        git(self.repo, "checkout", "-q", "staging")
        card = self.card("c-1")
        self.build(card, "plain.txt")
        self.assertIn("merged into staging", merging.publish(self.cfg(), card))

    def test_a_dangling_default_is_not_used(self):
        git(self.repo, "branch", "gone")                         # a stale local branch of that name
        git(self.repo, "symbolic-ref", "refs/remotes/origin/HEAD", "refs/remotes/origin/gone")
        self.assertIsNone(merging.remote_default(self.repo, "origin"))
        self.assertEqual(merging.usual_branch(self.cfg(), "team", self.repo), "main")

    def test_a_default_only_the_remote_has_lands_through_the_remote_ref(self):
        git(self.repo, "branch", "staging", "refs/remotes/origin/staging")
        git(self.repo, "checkout", "-q", "staging")
        git(self.repo, "branch", "-D", "main")
        card = self.card("c-1")
        tree = self.build(card, "plain.txt")
        self.assertFalse((tree / "STAGING.md").exists(), "cut from origin/main")
        self.assertIn("merged into main", merging.publish(self.cfg(), card))
        self.assertIn("plain.txt", git(self.repo, "ls-tree", "--name-only", "main"))

    def test_a_card_lands_on_the_branch_it_was_cut_from_when_the_default_changes_after(self):
        """r2.F1: the team moves its default between the cut and the publish (the next card's
        fetch before work follows it); this card still lands where it was cut, and never
        carries main's history onto staging."""
        from keel import house
        card = self.card("c-1")
        self.build(card, "plain.txt")                            # cut from main, the default
        staging = git(self.repo, "rev-parse", "refs/remotes/origin/staging")
        git(self.dir / "remote.git", "symbolic-ref", "HEAD", "refs/heads/staging")
        git(self.repo, "remote", "set-head", "origin", "--auto")
        cfg = self.cfg()
        self.assertEqual(merging.usual_branch(cfg, "team", self.repo), "staging", "the default moved")
        with open_board(cfg) as board:
            card = board.get(card["id"])
        self.assertEqual(house.target_of(cfg, card), "main")
        self.assertIn("merged into main", merging.publish(cfg, card))
        self.assertIn("plain.txt", git(self.repo, "ls-tree", "--name-only", "main"))
        self.assertEqual(git(self.repo, "rev-parse", "refs/remotes/origin/staging"), staging,
                         "staging is untouched")
        self.assertEqual(card["options"].get("cut_from"), {"shop": "main"}, "recorded at the cut")

    def test_a_re_cut_after_the_default_moved_records_the_new_branch_and_lands_there(self):
        """r2.D3: the card's branch and worktree are gone and it is cut again, after the team
        moved its default: the drain's new cut overwrites that repo's entry, and the card lands
        where it was cut this time, never by the stale one."""
        card = self.card("c-1")
        tree = self.build(card, "first.txt")                     # cut from main
        branch = git(tree, "branch", "--show-current")
        git(self.repo, "worktree", "remove", "--force", str(tree))
        git(self.repo, "branch", "-D", branch)
        git(self.dir / "remote.git", "symbolic-ref", "HEAD", "refs/heads/staging")
        git(self.repo, "remote", "set-head", "origin", "--auto")
        git(self.repo, "branch", "staging", "refs/remotes/origin/staging")
        cfg = self.cfg()
        with open_board(cfg) as board:
            card = board.get(card["id"])
        self.build(card, "again.txt")                            # cut again, from staging
        with open_board(cfg) as board:
            card = board.get(card["id"])
        self.assertEqual(card["options"].get("cut_from"), {"shop": "staging"})
        self.assertEqual(merging.landing_target(cfg, card, self.repo), "staging")
        self.assertIn("merged into staging", merging.publish(cfg, card))

    def test_a_cut_from_that_is_not_a_branch_name_is_ignored(self):
        """r2.D1: read with the bases' own rule, `bases.branch_problem`; a name git would read
        as a revision falls through to the usual branch."""
        from keel import house
        cfg = self.cfg()
        card = self.card("c-1")
        for bad in ("staging~1", "-x", "a b", "@{-1}"):
            with self.subTest(bad):
                odd = dict(card, options=dict(card["options"], cut_from={"shop": bad}))
                self.assertEqual(merging.landing_target(cfg, odd, self.repo), "main")
                self.assertEqual(house.target_of(cfg, odd), "main")
        good = dict(card, options=dict(card["options"], cut_from={"shop": "staging"}))
        self.assertEqual(merging.landing_target(cfg, good, self.repo), "staging", "a good one still counts")

    def test_fetch_before_work_follows_a_changed_default(self):
        git(self.dir / "remote.git", "symbolic-ref", "HEAD", "refs/heads/staging")
        cfg = self.cfg()
        space = cfg.spaces["team"]
        space.fetch_before_work = True
        landpush.fetch_first(cfg, space, "shop")
        self.assertEqual(merging.usual_branch(cfg, "team", self.repo), "staging")


class OwnRulesTest(Cards):
    """The owner's own spaces keep their rules."""

    def test_a_checkout_of_the_users_own_lands_on_the_branch_it_has_out(self):
        theirs = self.dir / "mine"
        git(self.dir, "clone", "-q", str(team_remote(self.dir / "t")), str(theirs))
        git(theirs, "checkout", "-q", "staging")
        self.act({"verb": "setup.repo.attach", "space": "team", "key": "shop", "path": str(theirs)})
        card = self.card("c-1")
        self.build(card, "plain.txt")
        self.assertIn("merged into staging", merging.publish(self.cfg(), card))

    def test_a_repo_with_an_integration_branch_lands_there_and_takes_no_base(self):
        repo = self.with_team()
        path = self.home / "config.toml"
        path.write_text(path.read_text().replace("[integration]\n", '[integration]\nshop = "next"\n', 1))
        git(repo, "checkout", "-q", "staging")
        card = self.card("c-1")
        self.build(card, "work.txt")
        self.assertIn("merged into next", merging.publish(self.cfg(), card))
        self.assertEqual(merging.card_base(self.cfg(), dict(card, options={"base": "main"})), None)
