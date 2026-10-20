"""prompts: the plan-gate resume texts (a surface is polled once, a markdown plan is not),
the discussion loop, and the generated "What you can do" block with and without `kb help`."""

import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from keel import house, prompts
from keel.board import Board
from tests.helpers import make_config, make_repo

SURFACE = "/keel/state/cards/c-001/plan.html"
MARKDOWN = "/keel/state/cards/c-001/plan.md"
HELP = """\
kb, the Keel board
create --space S --title T: files a new card, and prints its id
show <id> [--json]: one card with its recent events
stage <id> <stage> [--plan REF]: move the card, carrying the refs
approve <id> plan|outcome: answers a gate, the human's alone
import-harbor [--ledger PATH]: folds the old ledger in, once
stop-check <id>: the Stop hook body
"""


class SurfaceTest(unittest.TestCase):
    def test_only_an_html_plan_is_a_surface(self):
        for ref in (SURFACE, "plan.HTML", "https://x.test/p.html?token=1", "p.htm"):
            self.assertTrue(prompts.is_surface(ref), ref)
        for ref in (MARKDOWN, "", None, "https://x.test/pr/1", "plan.html.md"):
            self.assertFalse(prompts.is_surface(ref), ref)


class PlanGatePromptTest(unittest.TestCase):
    def test_approve_on_a_surface_collects_the_annotations_first_and_bounds_the_poll(self):
        text = prompts.approve(SURFACE)
        self.assertIn(f"timeout {prompts.COLLECT_SECONDS} lavish-axi poll {SURFACE}", text)
        self.assertLess(text.index("lavish-axi poll"), text.index("Then build"))
        self.assertIn("approved", text)


    def test_every_approve_says_an_unanswered_question_takes_the_recommendation(self):
        """A plain Approve means "go with what you recommended", so it is said once, in the
        prompt, whether or not he typed anything beside the tap."""
        for text in (prompts.approve(MARKDOWN), prompts.approve(SURFACE),
                     prompts.approve(MARKDOWN, said="option two"),
                     prompts.approve(SURFACE, said="option two")):
            self.assertIn(prompts.RECOMMENDED, text)

    def test_approve_carries_what_he_said_quoted_and_applies_it_before_building(self):
        text = prompts.approve(MARKDOWN, said="question one: option two\nquestion two: skip it")
        self.assertIn("> question one: option two", text)
        self.assertIn("> question two: skip it", text)
        self.assertIn("the user's answers", text)
        self.assertIn("context.md", text)
        self.assertLess(text.index("> question one"), text.index("Then build"))

    def test_a_blank_said_is_a_plain_approve(self):
        for blank in (None, "", "   \n "):
            self.assertEqual(prompts.approve(MARKDOWN, said=blank), prompts.approve(MARKDOWN))

    def test_a_surface_reads_the_annotations_and_his_words_together(self):
        text = prompts.approve(SURFACE, said="take the cheaper one")
        self.assertIn("> take the cheaper one", text)
        self.assertIn("lavish-axi poll", text)
        self.assertIn("the annotations and the user's answers", text)
        self.assertLess(text.index("lavish-axi poll"), text.index("Then build"))

    def test_sendback_carries_the_reason_quoted_and_polls_only_for_a_surface(self):
        text = prompts.sendback_plan(SURFACE, "the second option is cheaper\nsay why not")
        self.assertIn("> the second option is cheaper", text)
        self.assertIn("> say why not", text)
        self.assertIn("lavish-axi poll", text)
        self.assertIn("Do not start building", text)
        plain = prompts.sendback_plan(MARKDOWN, "too big")
        self.assertNotIn("lavish", plain.lower())
        self.assertIn("> too big", plain)

    def test_sendback_from_the_outcome_gate_sends_the_house_back_to_review(self):
        text = prompts.sendback_outcome("the test does not fail without the fix")
        self.assertIn("> the test does not fail without the fix", text)
        self.assertIn("kb stage $KEEL_CARD review --output", text)
        self.assertIn("pre-gate pipeline", text)      # a changed branch is reviewed again (HP-2)
        self.assertNotIn("lavish", text.lower())
        self.assertIn("first make the card say so", text)   # RQ-1: a send-back that redirects the card



class AnswerResumePromptTest(unittest.TestCase):
    """F1: his words to a blocked house, with the resume."""

    def test_his_answer_is_quoted_and_the_house_is_told_where_the_card_is(self):
        text = prompts.answer_resume("building", "use the staging key\nand retry the upload")
        self.assertIn("> use the staging key\n> and retry the upload", text)
        self.assertIn("the card is still at building", text)
        self.assertIn("blocked", text)

    def test_a_blank_answer_is_the_plain_resume(self):
        self.assertEqual(prompts.answer_resume("review", "   "),
                         "continue from where you stopped; the card is still at review")

class DiscussionPromptTest(unittest.TestCase):
    def setUp(self):
        self.text = prompts.discussion(SURFACE, "walk me through the trade-off", 900)


    def test_the_card_stays_at_planning_and_the_house_does_not_build(self):
        self.assertIn("stays at planning", self.text)
        self.assertIn("do not start building", self.text.lower())
        self.assertIn("> walk me through the trade-off", self.text)


class AbilitiesTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name)
        self.cfg = make_config(self.dir)
        self.addCleanup(self.tmp.cleanup)

    def run_help(self, stdout="", returncode=0, error=None):
        def runner(argv, **kwargs):
            self.argv, self.env = argv, kwargs.get("env")
            if error:
                raise error
            return subprocess.CompletedProcess(argv, returncode, stdout=stdout, stderr="kb: nope\n")
        return prompts.abilities(self.cfg, {"KEEL_CARD": "c-001"}, run=runner)

    def test_kb_help_lines_become_bullets_without_the_verbs_a_house_may_not_run(self):
        text, warning = self.run_help(stdout=HELP)
        self.assertIsNone(warning)
        self.assertEqual(self.argv[:2], [str(self.cfg.root / "bin" / "kb"), "help"])
        self.assertEqual(self.env, {"KEEL_CARD": "c-001"})
        self.assertIn("- `kb show <id> [--json]`: one card with its recent events", text)
        self.assertIn("- `kb create --space S --title T`: files a new card, and prints its id", text)
        for gone in ("- `kb approve", "- `kb import-harbor", "- `kb stop-check"):
            self.assertNotIn(gone, text, gone)
        self.assertIn("Approvals are the human's alone", text)

    def test_the_block_carries_child_cards_and_what_the_human_can_see(self):
        text, _ = self.run_help(stdout=HELP)
        self.assertTrue(text.startswith("## What you can do"))
        self.assertIn("kb create --space <your space>", text)
        self.assertIn("--from $KEEL_CARD", text)
        self.assertIn("![what it shows](assets/<file>)", text)
        self.assertIn("lavish-axi --no-open <file>", text)

    def test_the_block_separates_a_follow_up_from_a_split_and_asks_for_a_repo(self):
        """The two relations and the repo, the three things c-295 to c-299 got wrong."""
        text, _ = self.run_help(stdout=HELP)
        block = text[text.index("### Splitting the work outward"):]
        self.assertIn("--from $KEEL_CARD", block)
        self.assertIn("kb split $KEEL_CARD", block)
        self.assertIn("state them on\nthe slice (`|repo=<key[,key]>`)", block)      # c-771
        self.assertIn("tracking card", block)
        self.assertIn("--repo <name>", block)
        self.assertNotIn("--parent $KEEL_CARD", block)

    def test_a_missing_kb_help_falls_back_to_the_short_list_and_says_why(self):
        for stdout, code, error, expected in (("", 2, None, "exited 2"),
                                              ("nothing useful\n", 0, None, "no verb lines"),
                                              ("", 0, OSError("no such file"), "could not run")):
            text, warning = self.run_help(stdout=stdout, returncode=code, error=error)
            self.assertIn(expected, warning)
            self.assertIn("- `kb note <id> \"text\"`", text)
            self.assertIn(prompts.FALLBACK_NOTE, text)
            self.assertNotIn("- `kb approve", text)


class ConfinementTest(unittest.TestCase):
    """What the brief may promise follows the tool set, because c-270 and c-271 were both
    a brief naming a command the house had no tool for."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name)
        self.cfg = make_config(self.dir)
        self.addCleanup(self.tmp.cleanup)

    def block(self, **kwargs) -> str:
        with mock.patch.object(prompts, "board_verbs", return_value=("- `kb show <id>`: the card", None)):
            text, _ = prompts.abilities(self.cfg, {}, **kwargs)
        return text

    def test_bash_is_read_off_the_tool_list_and_a_repo_card_has_everything(self):
        self.assertTrue(prompts.has_bash(None))
        self.assertTrue(prompts.has_bash("Read, Write, Bash"))
        self.assertTrue(prompts.has_bash(prompts.BASH_TOOL))
        self.assertFalse(prompts.has_bash("Read,Write"))
        self.assertFalse(prompts.has_bash(""))

    def test_web_is_read_off_the_tool_list_and_a_repo_card_is_told_nothing(self):
        self.assertEqual(prompts.web_tools(house.ERRAND_TOOLS), ["WebSearch", "WebFetch"])
        self.assertEqual(prompts.web_tools("Read, WebFetch"), ["WebFetch"])
        self.assertEqual(prompts.web_tools("Read,Bash"), [])
        self.assertEqual(prompts.web_tools(None), [])

    def test_the_web_sentence_appears_exactly_when_the_web_tools_do(self):
        heading = "### The web"
        errand = self.block(tools=house.ERRAND_TOOLS, restricted=True)
        self.assertIn(heading, errand)
        self.assertIn("`WebSearch` and `WebFetch` are yours", errand)
        self.assertNotIn(heading, self.block(tools="Read,Write,Bash", restricted=True))
        self.assertNotIn(heading, self.block(tools=None, restricted=False))
        worker = self.block(tools="Read,Write,WebSearch", restricted=True, drop="/x/w.json")
        self.assertIn("`WebSearch` are yours", worker)
        self.assertNotIn("WebFetch", worker)
        self.assertNotIn(heading, self.block(tools="Read,Write", restricted=True))

    def test_a_house_with_no_bash_is_told_about_its_file_and_no_command(self):
        text = self.block(tools="Read,Write", restricted=True, drop="/x/inbox/worker.json")
        self.assertIn("/x/inbox/worker.json", text)
        self.assertIn("This house has no shell", text)
        self.assertIn("files the card", text)
        for promise in ("kb ", "`kb", "lavish-axi", "$KEEL_CARD planning"):
            self.assertNotIn(promise, text, promise)

    def test_a_no_bash_house_with_no_drop_is_still_told_where_its_output_goes(self):
        text = self.block(tools="Read,Write", restricted=True)
        self.assertIn("the file the brief below names", text)

    def test_a_house_with_a_shell_is_briefed_the_current_board_grammar(self):
        """c-302 drew a grammar two days stale; the card now rides in the generated brief
        (c-603), so every new brief carries the one the parser reads, and only where a
        house can push."""
        from keel import boardgrammar
        card = boardgrammar.grammar_card()
        for kwargs in ({"tools": None, "restricted": False},
                       {"tools": "Read,Write,Edit,Bash", "restricted": True}):
            self.assertIn(card, self.block(**kwargs), kwargs)
        self.assertNotIn(card, self.block(tools="Read,Write", restricted=True))

    def test_a_fenced_house_gets_the_verbs_and_the_fence_in_the_fence_s_own_words(self):
        text = self.block(tools="Read,Write,Edit,Bash", restricted=True)
        self.assertIn("- `kb show <id>`: the card", text)
        self.assertIn(prompts.FENCE_LINE, text)
        self.assertIn(str(self.cfg.root / "bin" / "kb"), text)
        self.assertIn(f"{self.cfg.root / 'bin' / 'keel'} deck", text)
        self.assertNotIn("lavish-axi poll", text)
        self.assertIn("markdown", text)

    def test_the_brief_quotes_the_line_the_fence_actually_prints(self):
        fence = (Path(prompts.__file__).resolve().parent.parent / "bin" / "keel-board-fence").read_text()
        self.assertIn(f'REFUSAL = "{prompts.FENCE_LINE}"', fence,
                      "the brief and the hook must say the same sentence")

    def test_a_repo_card_keeps_the_surface_and_the_poll_and_gets_no_fence(self):
        text = self.block(tools=None, restricted=False, space="personal")
        self.assertIn("lavish-axi --no-open <file>", text)
        self.assertIn("one bounded poll", text)
        self.assertNotIn(prompts.FENCE_LINE, text)


class AtlasAndNewProjectTest(unittest.TestCase):
    """The two blocks that follow the placement: what a house may do with the Atlas, and
    what a card that opens a fresh repository is told."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name)
        self.cfg = make_config(self.dir)
        self.addCleanup(self.tmp.cleanup)

    def abilities(self, **kwargs):
        with mock.patch.object(prompts, "board_verbs", return_value=("- `kb show <id>`: x", None)):
            return prompts.abilities(self.cfg, {}, **kwargs)[0]

    def test_a_repo_card_is_told_to_change_the_page_in_the_same_commit(self):
        text = self.abilities()
        self.assertIn("$KEEL_HOME/docs/atlas/", text)
        self.assertIn("Atlas page in the same commit", text)
        self.assertNotIn("Write and Edit are refused there", text)

    def test_a_confined_house_is_told_the_atlas_is_read_only(self):
        """It gets the directory as an add-dir and the editing tools denied on it
        (`house.atlas_deny`), so the brief says that rather than leaving it to a refusal."""
        text = self.abilities(restricted=True, tools=house.ERRAND_TOOLS)
        self.assertIn("$KEEL_HOME/docs/atlas/", text)
        self.assertIn("Write and Edit are refused there", text)
        self.assertNotIn("in the same commit", text)

    def test_a_new_project_card_is_told_the_path_and_that_the_plan_comes_first(self):
        text = self.abilities(new_project="/Users/x/projects/smoke")
        self.assertIn("/Users/x/projects/smoke", text)
        self.assertIn("fresh repository", text)
        self.assertIn("The plan comes first", text)
        self.assertLess(text.index("This card opens a new project"),
                        text.index("When you do not understand something"))


class BriefBlockTest(unittest.TestCase):
    """The block reaches the real brief, between the contract and the card block."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name)
        self.cfg = make_config(self.dir, repos={"keel": make_repo(self.dir / "repo")})
        self.board = Board(self.cfg.db_path)
        self.addCleanup(self.tmp.cleanup)
        self.addCleanup(self.board.close)

    def test_the_brief_holds_the_block_in_order(self):
        card_id = self.board.create("personal", "A card", repo="keel", autonomy="attended")
        with mock.patch.object(prompts, "board_verbs", return_value=("- `kb show <id>`: the card", None)):
            text = house.brief_for(self.cfg, self.board.get(card_id))
        self.assertLess(text.index("# You are the house"), text.index("## What you can do"))
        self.assertLess(text.index("## What you can do"), text.index("## The card"))
        self.assertIn("- `kb show <id>`: the card", text)

    def test_each_house_is_briefed_the_board_in_the_form_it_may_use(self):
        """c-603: the grammar left the contract for a generated section. A house with a shell
        pipes its ops; a fenced errand names `keel` by its absolute path and passes --file,
        which is all its fence lets through (`bin/keel-board-fence`)."""
        keel = str(self.cfg.root / "bin" / "keel")
        with mock.patch.object(prompts, "board_verbs", return_value=("- `kb show <id>`: x", None)):
            repo_id = self.board.create("personal", "A card", repo="keel")
            errand_id = self.board.create("personal", "An errand")
            repo = house.brief_for(self.cfg, self.board.get(repo_id))
            errand = house.brief_for(self.cfg, self.board.get(errand_id))
        for text in (repo, errand):
            self.assertIn("Board grammar v", text)
            self.assertIn("There is no erase", text)
        # r-56 (c-723): the card and its folder written literally (`prompts.literal_board_push`)
        self.assertIn(f"keel board push --card {repo_id}    # the ops on stdin", repo)
        board = errand[errand.index("### Drawing on your card's board"):]
        self.assertIn(f"{keel} board push --card {errand_id} --file {self.cfg.cards_dir / errand_id}/<ops file>", board)
        self.assertNotIn("ops on stdin", board)

    def test_the_fallback_is_logged_for_the_operator(self):
        card_id = self.board.create("personal", "A card", repo="keel")
        with mock.patch.object(prompts, "board_verbs", return_value=("- `kb show <id>`: x", "kb help exited 2")):
            house.brief_for(self.cfg, self.board.get(card_id))
        log = (self.cfg.logs_dir / "drain.log").read_text()
        self.assertIn(f"brief for {card_id}: kb help exited 2", log)
        self.assertIn("short verb list", log)


if __name__ == "__main__":
    unittest.main()



class SpokenFramingTest(unittest.TestCase):
    """What a house is told when he is TALKING to it, and the one thing it could not do
    until 2026-09-21: end the conversation itself when he asks it to.

    In his own session that day he said "Okay, you can exit the pouse now"; the house
    answered "I can't end my own session, tap Stop on the deck", which was true and is the
    fault this sentence closes. It is the second net behind the gateway's own matcher.
    """


    def test_every_connected_conversation_carries_it_on_its_first_sentence(self):
        self.assertIn("<<keel-leave>>", prompts.converse("you can go back"))

    def test_and_a_later_sentence_carries_only_his_words(self):
        """A kept-alive conversation is told the rules once; the transcript holds them
        after that, and repeating them is tokens spent saying what it already knows."""
        self.assertNotIn("keel-leave", prompts.converse_more("you can go back"))
