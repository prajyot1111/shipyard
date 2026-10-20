"""The board fence: what a confined house's Bash may run.

Driven the way Claude Code drives it, as a subprocess with the PreToolUse payload on
stdin, because the protocol (exit 2 and one line on stderr) is half of what is being
tested. The rule is one plain invocation of `bin/kb` or `bin/keel deck`, by absolute path,
and everything else is refused.
"""

import json
import subprocess
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
FENCE = ROOT / "bin" / "keel-board-fence"
KB = str(ROOT / "bin" / "kb")
KEEL = str(ROOT / "bin" / "keel")
CARD = "c-271"
REFUSAL = "this house is confined to the board: kb, keel deck and keel board only"


def run(command, card: str = CARD, payload: dict | None = None) -> subprocess.CompletedProcess:
    body = payload if payload is not None else {"tool_name": "Bash",
                                                "tool_input": {"command": command}}
    return subprocess.run([str(FENCE), card], input=json.dumps(body), capture_output=True,
                          text=True, timeout=30)


REVIEW = str(ROOT / "bin" / "keel-review")


CARD_DIR = "/s/cards/c-271"
CHECKOUT = "/s/worktrees/c-271"


def run_review(command: str) -> subprocess.CompletedProcess:
    """The fence as a fork's review house runs it (c-730 r2.F3): `--review` after the card,
    with the card's own directory and checkout, which the review steps are pinned to."""
    body = {"tool_name": "Bash", "tool_input": {"command": command}}
    return subprocess.run([str(FENCE), CARD, "--review", "--card-dir", CARD_DIR, "--worktree", CHECKOUT],
                          input=json.dumps(body), capture_output=True, text=True, timeout=30)


class ForkReviewTest(unittest.TestCase):
    """c-730 r2.F3: a fork's review house reads the fork's code and never runs it. Its fence is
    the board's, plus Keel's own two review steps by absolute path; an errand's is unchanged."""

    def test_the_review_steps_are_allowed_to_a_fork_s_review_house_only(self):
        for command in (f"{REVIEW} prep --dir {CARD_DIR} --base main",
                        f"{REVIEW} prep --dir {CARD_DIR} --base main --worktree {CHECKOUT} --since",
                        f'{REVIEW} draft --dir {CARD_DIR} F1 --comment "One point."'):
            self.assertEqual(run_review(command).returncode, 0, command)
            self.assertEqual(run(command).returncode, 2, command)
        self.assertEqual(run_review(f"{KB} show c-271").returncode, 0)

    def test_the_review_steps_are_pinned_to_the_card_s_own_directory_and_checkout(self):
        """c-730 fix check: a hijacked fork house cannot point prep or draft at another card's
        directory, another repo, or another remote."""
        for command in (f"{REVIEW} prep --dir /s/cards/c-9 --base main",
                        f"{REVIEW} prep --dir={CARD_DIR}/.. --base main",
                        f"{REVIEW} prep --dir {CARD_DIR} --base main --worktree /Users/x/secret-repo",
                        f"{REVIEW} prep --dir {CARD_DIR} --base main --worktree={CHECKOUT}/../other",
                        f"{REVIEW} prep --dir {CARD_DIR} --base main --remote evil",
                        f"{REVIEW} prep --dir {CARD_DIR} --base main --member a /x main",
                        f"{REVIEW} prep --dir cards/c-271 --base main",
                        f'{REVIEW} draft --dir /s/cards/c-9 F1 --comment "x"',
                        f"{REVIEW} prep --base main"):
            self.assertEqual(run_review(command).returncode, 2, command)

    def test_a_shortened_or_unknown_flag_is_refused_however_it_is_spelled(self):
        """c-730 fix check: argparse would expand `--d` to `--dir`, so only the exact flags a
        review step takes pass, and any other word that starts with a dash is refused."""
        own = f"{REVIEW} prep --dir {CARD_DIR} --base main"
        for tail in ("--d /s/cards/c-9", "--di=/s/cards/c-9", "--wo /any/repo", "--rem evil", "--mem a /x main",
                     "--tw a b", "-d /s/cards/c-9", "--sinc", "--base=main --dirx /s"):
            self.assertEqual(run_review(f"{own} {tail}").returncode, 2, tail)
        draft = f'{REVIEW} draft --dir {CARD_DIR} F1 --comment x --di /s/cards/c-9'
        self.assertEqual(run_review(draft).returncode, 2)
        for allowed in (f"{own} --since", f"{own} --since=stamp", f"{REVIEW} prep --dir={CARD_DIR} --base=main",
                        f"{REVIEW} draft --dir {CARD_DIR} F1 --comment=fine"):
            self.assertEqual(run_review(allowed).returncode, 0, allowed)

    def test_nothing_of_the_fork_s_runs_in_its_house(self):
        for command in ("npm test", "make test", "python3 setup.py", "./run.sh", f"{REVIEW} lint",
                        f"{REVIEW} prep --dir x; npm test", "gh pr view 12", "git status"):
            self.assertEqual(run_review(command).returncode, 2, command)


class AllowedTest(unittest.TestCase):
    def test_the_board_and_the_deck_are_allowed_with_their_arguments(self):
        for command in (f"{KB} show c-1",
                        f"{KB} stage c-1 review --output x",
                        f'{KB} note c-1 "one short line"',
                        f"{KB} show $KEEL_CARD",
                        f"{KEEL} deck reviews",
                        f"{KEEL} deck --digest",
                        # A confined house draws too, and it cannot pipe: the fence allows
                        # one plain command with no redirect and no heredoc, so the ops go
                        # in a file in the card directory and `--file` names it.
                        f"{KEEL} board push --card c-271 --file ops.txt",
                        f'{KEEL} board find "the memory system"',
                        f"{KEEL} board show b-004",
                        f"{KEEL} board list --card c-271",
                        # BD-1: a house may delete its own card's boards; the STORE holds
                        # the own-card rule, so the fence only has to let the verb through.
                        f"{KEEL} board delete b-004"):
            result = run(command)
            self.assertEqual(result.returncode, 0, f"{command}: {result.stderr}")
            self.assertEqual(result.stderr, "")


class RefusedTest(unittest.TestCase):
    def refusal(self, command) -> str:
        result = run(command)
        self.assertEqual(result.returncode, 2, f"{command} was allowed")
        lines = [line for line in result.stderr.splitlines() if line.strip()]
        self.assertEqual(len(lines), 1, "the reason is one line the house can read")
        self.assertIn(REFUSAL, lines[0])
        self.assertIn(CARD, lines[0])
        return lines[0]

    def test_anything_that_is_not_the_board_is_refused(self):
        for command in ("ls", "python3 -c 'import os; print(1)'", "cat /etc/hosts", "git status"):
            self.refusal(command)

    def test_a_chain_a_substitution_or_a_pipe_cannot_smuggle_a_second_command(self):
        for command in (f"{KB} show c-1; rm -rf x",
                        f"{KB} show c-1 && rm -rf x",
                        f"{KB} show c-1 || ls",
                        f"{KB} list | sh",
                        f"{KB} show $(whoami)",
                        f"{KB} show `whoami`",
                        f"{KB} list > /tmp/out",
                        f"{KB} list\nrm -rf x"):
            self.refusal(command)

    def test_an_env_prefix_a_cd_and_a_relative_name_are_refused(self):
        self.refusal(f"FOO=1 {KB} list")
        self.refusal(f"cd /tmp && {KB} list")
        self.refusal("kb show c-1")
        self.refusal("bin/kb show c-1")
        self.refusal(f"sudo {KB} list")

    def test_a_board_verb_that_is_not_a_houses_is_refused(self):
        """`open`, `new` and `close` change whose board is live and end somebody's
        sitting. The store refuses a house another source's board either way
        (`keel/boards.py`), and the fence keeps its own claim true: what a confined house
        may run is drawing and reading."""
        for verb in ("open b-004", "close b-004", "new --from b-004", "restore b-004"):
            line = self.refusal(f"{KEEL} board {verb}")
            self.assertIn("push", line)

    def test_only_the_deck_and_board_verbs_of_keel_are_allowed(self):
        self.refusal(f"{KEEL} doctor")
        self.refusal(f"{KEEL} drain --once")
        self.refusal(KEEL)

    def test_a_payload_it_cannot_read_fails_closed(self):
        result = run(None, payload={"tool_name": "Bash", "tool_input": {}})
        self.assertEqual(result.returncode, 2)
        broken = subprocess.run([str(FENCE), CARD], input="not json", capture_output=True,
                                text=True, timeout=30)
        self.assertEqual(broken.returncode, 2)
        self.assertIn(REFUSAL, broken.stderr)



if __name__ == "__main__":
    unittest.main()
