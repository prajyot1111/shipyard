"""Deploy (c-526): the drain asks once per `next` sha, only his tap or voice says Deploy, and
the worker moves main only after the full suite, every module with voice, is green (or its
failures pass on one rerun, which the ask's record says; c-646)."""

import contextlib
import http.server as http_server
import io
import itertools
import json
import os
import tempfile
import threading
import types
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest import mock

from keel import asks, cli, config, deploy, deployask, drain, kick, landing, merging, refresh
from keel.board import Board, Refused
from tests import selector
from tests.test_integration import IntegrationCase
from tests.test_merging import sh

GREEN = "printf 'ok: selftest\\nvoice: 1.0s, exit 0\\n'"


class DeployCase(IntegrationCase):
    def setUp(self):
        super().setUp()
        self.board = Board(self.cfg.db_path, integrated=self.cfg.integrated)
        self.addCleanup(self.board.close)
        merging.publish(self.cfg, self.card)
        self.cfg.repo_tests["keel"] = GREEN
        venv = self.repo / deploy.VENV / "bin"
        venv.mkdir(parents=True)
        (venv / "python").write_text("#!/bin/sh\n")
        (venv / "python").chmod(0o755)
        # The preflight reads which launch agents are loaded; this machine's are none of a
        # scratch deploy's business (tests/test_deploypreflight.py holds the preflight).
        loaded = mock.patch("keel.deploypreflight.launchd_loaded", return_value=set())
        loaded.start()
        self.addCleanup(loaded.stop)

    def pass_(self):
        with mock.patch.object(deploy, "spawn", return_value=os.getpid()) as spawned:
            deploy.upkeep(self.cfg, self.board)
        return spawned

    def deploy_asks(self):
        return deployask.rows_for(self.board, "keel")

    def said_yes(self) -> str:
        self.pass_()
        aid = self.deploy_asks()[0]["id"]
        asks.answer(self.board, aid, "human", "A")
        return aid

    def moves(self, aid):
        return deployask.moves(self.board, aid)


class AskTest(DeployCase):
    def test_the_drain_asks_once_listing_the_cards(self):
        self.pass_()
        self.pass_()
        rows = self.deploy_asks()
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["actor"], "drain")
        self.assertIn("c-1", rows[0]["question"])
        facts = deployask.facts_of(rows[0])
        self.assertEqual((facts["sha"], facts["cards"]), (merging.ref_head(self.repo, "next"), ["c-1"]))

    def test_next_moving_withdraws_the_ask_and_raises_another(self):
        self.pass_()
        second = self.card_branch("c-2", "second", start="next")
        merging.publish(self.cfg, second)
        self.pass_()
        rows = self.deploy_asks()
        self.assertEqual([row["state"] for row in rows], ["open", "withdrawn"])
        self.assertEqual(deployask.facts_of(rows[0])["cards"], ["c-1", "c-2"])

    def test_not_yet_is_not_asked_again_until_next_moves(self):
        self.pass_()
        asks.answer(self.board, self.deploy_asks()[0]["id"], "human", "B")
        self.pass_()
        self.assertEqual(len(self.deploy_asks()), 1)

    def test_nothing_is_asked_when_main_has_it(self):
        sh(self.repo, "git", "merge", "-q", "--ff-only", "next")
        self.pass_()
        self.assertEqual(self.deploy_asks(), [])

    def test_a_chat_answer_is_refused_and_bosun_cannot_withdraw_it(self):
        self.pass_()
        aid = self.deploy_asks()[0]["id"]
        with self.assertRaises(Refused) as caught:
            asks.answer(self.board, aid, "bosun", "A", by="chat", message="yes deploy")
        self.assertIn("only the user's tap or voice", str(caught.exception))
        with self.assertRaises(Refused):
            asks.withdraw(self.board, aid, "bosun", "not needed")

    def test_his_yes_is_never_handed_to_bosun_to_carry_out(self):
        self.pass_()
        aid = self.deploy_asks()[0]["id"]
        asks.answer(self.board, aid, "voice", "A")
        self.assertNotIn(aid, [row["id"] for row in asks.undelivered(self.board)])

    def test_bosun_s_raise_cannot_make_a_deploy_ask(self):
        row = asks.raise_ask(self.board, "bosun", "approval", "Deploy?", "why",
                             ["Deploy|push main", "No|nothing"])
        self.assertFalse(deployask.is_deploy(row))

    def test_his_yes_starts_one_worker(self):
        aid = self.said_yes()
        spawned = self.pass_()
        spawned.assert_called_once_with(self.cfg, aid)
        self.pass_().assert_not_called()
        self.assertIn(deployask.DEPLOYING, self.moves(aid))

    def test_kb_console_deploy_is_his_alone(self):
        args = mock.Mock(preview=False)
        with self.assertRaises(Refused):
            deployask.command(self.cfg, self.board, args, "bosun")
        with self.assertRaises(Refused):
            deployask.command(self.cfg, self.board, args, "house")
        preview = deployask.command(self.cfg, self.board, mock.Mock(preview=True), "human")
        self.assertEqual(preview["deploy"][0]["cards"], ["c-1"])
        self.assertEqual(self.deploy_asks(), [])
        done = deployask.command(self.cfg, self.board, args, "human")
        row = asks.get(self.board, done["answered"][0])
        self.assertEqual((row["state"], row["answer"]), ("answered", "A"))


class FilingTest(DeployCase):
    def test_a_long_refusal_is_still_filed_open(self):
        aid = self.said_yes()
        row = asks.get(self.board, aid)
        deploy.finish(self.cfg, self.board, row, None, "git worktree add " + "x" * 600 + "\n" + "y" * 5000)
        filed = self.board.conn.execute("SELECT what, detail, state FROM requests").fetchall()
        self.assertEqual([r["state"] for r in filed], ["open"])
        self.assertLessEqual(len(filed[0]["what"]), 240)


class WorkerTest(DeployCase):
    def run_worker(self):
        aid = self.said_yes()
        code = deploy.deploy(self.cfg, self.board, aid)
        return code, aid, asks.get(self.board, aid), self.board.events(aid)[-1]

    def test_green_moves_main_to_next(self):
        next_head = merging.ref_head(self.repo, "next")
        code, aid, _, last = self.run_worker()
        self.assertEqual(code, 0, last)
        self.assertEqual(sh(self.repo, "git", "rev-parse", "main"), next_head)
        self.assertTrue((self.repo / "new.txt").is_file(), "the live checkout runs it now")
        self.assertEqual(last["data"]["move"], deployask.DEPLOYED)
        self.assertIn("voice included", last["text"])

    def keel_itself(self, answer):
        """A deploy of the checkout this Keel runs from (`cfg.root` is the repo), with a deck
        on `cfg.serve_port` whose /api/health says `answer()` as its serve_head (c-637)."""
        class Health(http_server.BaseHTTPRequestHandler):
            def do_GET(self):
                body = json.dumps({"level": "green", "serve_head": answer()}).encode()
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(body)

            def log_message(self, *args):
                pass
        deck = http_server.ThreadingHTTPServer(("127.0.0.1", 0), Health)
        threading.Thread(target=deck.serve_forever, daemon=True).start()
        self.addCleanup(deck.server_close)
        self.addCleanup(deck.shutdown)
        for name, value in (("root", self.repo), ("serve_port", deck.server_address[1])):
            patch = mock.patch.object(self.cfg, name, value)
            patch.start()
            self.addCleanup(patch.stop)

    def test_a_health_reply_the_restart_cut_short_is_no_answer(self):
        """c-662: the deck's exec cuts the reply it was sending, and a body shorter than its
        length reads as `IncompleteRead`, no `OSError`: it would have ended the deploy's wait."""
        class Cut(http_server.BaseHTTPRequestHandler):
            def do_GET(self):
                self.send_response(200)
                self.send_header("Content-Length", "64")
                self.end_headers()
                self.wfile.write(b'{"serve_')

            def log_message(self, *args):
                pass
        deck = http_server.HTTPServer(("127.0.0.1", 0), Cut)
        threading.Thread(target=deck.serve_forever, daemon=True).start()
        self.addCleanup(deck.server_close)
        self.addCleanup(deck.shutdown)
        with mock.patch.object(self.cfg, "serve_port", deck.server_address[1]):
            self.assertIsNone(deploy.serve_head(self.cfg))

    def test_a_deploy_of_keel_says_deployed_once_the_deck_runs_the_new_code(self):
        """2026-10-04: the deck kept 7579bca's server after main moved and sent a blank page;
        a deploy of Keel itself now waits for the deck to answer on what it moved to."""
        next_head = merging.ref_head(self.repo, "next")
        answers = iter([sh(self.repo, "git", "rev-parse", "main"), None])
        self.keel_itself(lambda: next(answers, next_head))
        code, aid, _, last = self.run_worker()
        self.assertEqual(code, 0, last)
        self.assertEqual(last["data"]["move"], deployask.DEPLOYED)
        self.assertIn("the deck restarted onto it", last["text"])
        moves = [(event["data"].get("move"), event["text"]) for event in self.board.events(aid)
                 if event["data"].get("move") in (deployask.DEPLOYING, deployask.DEPLOYED)]
        restarts = [i for i, (move, text) in enumerate(moves) if "the deck restarts onto it" in text]
        self.assertTrue(restarts, moves)
        self.assertEqual(moves[restarts[0]][0], deployask.DEPLOYING)
        self.assertLess(restarts[0], len(moves) - 1, "said before deployed")

    def test_a_deck_that_does_not_restart_in_time_is_said_and_main_stays_moved(self):
        next_head = merging.ref_head(self.repo, "next")
        self.keel_itself(lambda: "0" * 40)
        with mock.patch.object(deploy, "deck_wait", return_value=0.0):
            code, _, _, last = self.run_worker()
        self.assertEqual(code, 0, last)
        self.assertEqual(sh(self.repo, "git", "rev-parse", "main"), next_head)
        self.assertEqual(last["data"]["move"], deployask.DEPLOYED)
        self.assertIn("the deck has not restarted onto it", last["text"])

    def test_the_wait_covers_a_deck_that_restarts_with_the_drain(self):
        """A deck sharing the drain's process restarts between the drain's passes, so the
        wait adds two of its polls (c-637 review r2.F3)."""
        with mock.patch.object(self.cfg, "poll_seconds", 30):
            self.assertEqual(deploy.deck_wait(self.cfg), deploy.DECK_WAIT_SECONDS + 60)

    def test_nothing_after_main_moved_turns_the_deploy_into_a_refusal(self):
        next_head = merging.ref_head(self.repo, "next")
        self.keel_itself(lambda: next_head)
        record = deployask.record

        def failing(board, aid, move, text, **data):
            if "the deck restarts onto it" in text:
                raise RuntimeError("board gone")
            return record(board, aid, move, text, **data)
        with mock.patch.object(deploy.deployask, "record", side_effect=failing):
            code, _, _, last = self.run_worker()
        self.assertEqual(code, 0, last)
        self.assertEqual(sh(self.repo, "git", "rev-parse", "main"), next_head)
        self.assertEqual(last["data"]["move"], deployask.DEPLOYED)
        self.assertIn("the deck could not be checked: RuntimeError: board gone", last["text"])

    def test_the_record_says_the_engine_restarts_and_nothing_else_for_other_code(self):
        code, _, _, last = self.run_worker()
        self.assertEqual(code, 0, last)
        self.assertEqual(last["data"]["refreshes"], [refresh.ENGINE])
        self.assertIn(refresh.ENGINE, last["text"])
        self.assertNotIn("voice gateway", last["text"])

    def test_the_record_says_what_voice_and_memory_changes_refresh(self):
        """r-14, c-538: c-523 changed Harbor's memory and the voice gateway, and the deploy
        said nothing of either; both kept running what they started with."""
        sh(self.repo, "git", "checkout", "-q", "next")
        for name in ("voice/harbor_voice/x.py", "talker/memory/fact.md"):
            (self.repo / name).parent.mkdir(parents=True, exist_ok=True)
            (self.repo / name).write_text("x\n")
        sh(self.repo, "git", "add", "voice", "talker")
        sh(self.repo, "git", "commit", "-q", "-m", "voice and memory")
        sh(self.repo, "git", "checkout", "-q", "main")
        code, _, _, last = self.run_worker()
        self.assertEqual(code, 0, last)
        self.assertEqual(last["data"]["refreshes"], [refresh.ENGINE, refresh.GATEWAY, refresh.MEMORY])
        self.assertIn("voice gateway restarts", last["text"])
        self.assertIn("phone talker rotates", last["text"])

    def test_a_tree_a_landing_ran_green_is_not_tested_again(self):
        """His call, 2026-09-26: approve and deploy both ran the suite on c-530. The deploy of
        the exact tree a landing ran green (voice included) runs nothing."""
        next_head = merging.ref_head(self.repo, "next")
        merging.record_tested(self.cfg, merging.tree_of(self.repo, next_head), "c-530")
        self.cfg.repo_tests["keel"] = "exit 1"          # would refuse, were it run
        code, _, _, last = self.run_worker()
        self.assertEqual(code, 0, last)
        self.assertEqual(sh(self.repo, "git", "rev-parse", "main"), next_head)
        self.assertIn("at c-530's landing, so it was not run again", last["text"])

    def test_his_commit_on_main_makes_a_new_tree_which_is_tested(self):
        merging.record_tested(self.cfg, merging.tree_of(self.repo, merging.ref_head(self.repo, "next")),
                              "c-530")
        (self.repo / "his.txt").write_text("x\n")
        sh(self.repo, "git", "add", "his.txt"); sh(self.repo, "git", "commit", "-q", "-m", "his")
        self.cfg.repo_tests["keel"] = "exit 1"
        code, _, _, last = self.run_worker()
        self.assertEqual(code, 1, "a trunk merged in is a tree nobody tested")

    def test_his_commit_on_main_is_merged_and_next_follows(self):
        (self.repo / "his.txt").write_text("x\n")
        sh(self.repo, "git", "add", "his.txt"); sh(self.repo, "git", "commit", "-q", "-m", "his")
        code, *_ = self.run_worker()
        self.assertEqual(code, 0)
        self.assertEqual(merging.ref_head(self.repo, "next"), sh(self.repo, "git", "rev-parse", "main"))
        self.assertTrue((self.repo / "his.txt").is_file())

    def test_no_voice_venv_is_refused_and_filed_for_bosun(self):
        import shutil
        shutil.rmtree(self.repo / deploy.VENV)
        main = sh(self.repo, "git", "rev-parse", "main")
        code, _, _, last = self.run_worker()
        self.assertEqual(code, 1)
        self.assertEqual(sh(self.repo, "git", "rev-parse", "main"), main)
        self.assertIn(".venv-voice", last["text"])
        filed = self.board.conn.execute("SELECT what, state FROM requests").fetchall()
        self.assertEqual(len(filed), 1)
        self.assertEqual(filed[0]["state"], "open", "Bosun is shown it, not a hidden sighting")
        self.assertIn("refused", filed[0]["what"])

    def test_a_suite_that_skipped_voice_is_refused_even_green(self):
        self.cfg.repo_tests["keel"] = "echo 'voice selftest: skipped, no .venv-voice'"
        code, _, _, last = self.run_worker()
        self.assertEqual(code, 1)
        self.assertIn("skipped the voice selftest", last["text"])

    def test_the_runner_s_echoed_command_is_not_a_skip(self):
        """The first real deploy (2026-09-26) was refused though voice ran and passed: the
        test runner echoes its own command, whose --done pattern holds the skip's words."""
        self.cfg.repo_tests["keel"] = ("printf \"  --done 'voice=^(ok: |voice selftest: skipped)'\\n"
                                       "ok: the selftest\\nvoice: 117.3s, exit 0\\n\"")
        code, _, _, last = self.run_worker()
        self.assertEqual(code, 0, last)

    def test_a_suite_with_no_voice_result_is_refused(self):
        self.cfg.repo_tests["keel"] = "echo 'Ran 3 tests'; echo OK"
        code, _, _, last = self.run_worker()
        self.assertEqual(code, 1)
        self.assertIn("skipped the voice selftest", last["text"])

    def test_the_deploy_runs_its_own_full_suite_not_the_landing_s(self):
        """c-646: the landing's `make test` is narrow; the deploy runs `[deploy_tests]`
        (`make test-all` for Keel), every module with voice."""
        self.cfg.repo_tests["keel"] = "exit 1"          # the landing's command, never run here
        self.cfg.deploy_tests["keel"] = GREEN
        code, _, _, last = self.run_worker()
        self.assertEqual(code, 0, last)
        self.assertIn("voice included", last["text"])

    def test_a_config_with_only_tests_asks_its_make_test_for_every_module(self):
        """An install config written before c-646 names only `[tests]` (`make test`): the
        deploy asks for the full suite (KEEL_FULL_SUITE), which Keel's Makefile honours,
        rather than being refused for a narrow run."""
        self.cfg.deploy_tests.pop("keel", None)
        self.cfg.repo_tests["keel"] = ('[ -n "$KEEL_FULL_SUITE" ] && ' + GREEN
                                       + " || printf 'asked for no full suite\\n'")
        code, _, _, last = self.run_worker()
        self.assertEqual(code, 0, last)

    def test_a_blank_deploy_tests_value_is_none_and_asks_for_every_module(self):
        self.cfg.deploy_tests["keel"] = "  "
        self.cfg.repo_tests["keel"] = ('[ -n "$KEEL_FULL_SUITE" ] && ' + GREEN
                                       + " || printf 'asked for no full suite\\n'")
        code, _, _, last = self.run_worker()
        self.assertEqual(code, 0, last)

    def test_a_deploy_tests_command_is_run_as_it_is(self):
        """`[deploy_tests]` is already the full command: no flag is added to it."""
        self.cfg.deploy_tests["keel"] = '[ -z "$KEEL_FULL_SUITE" ] && ' + GREEN
        code, _, _, last = self.run_worker()
        self.assertEqual(code, 0, last)

    def test_a_run_that_did_not_reach_voice_is_refused(self):
        main = sh(self.repo, "git", "rev-parse", "main")
        self.cfg.repo_tests["keel"] = f"printf '{selector.VOICE_UNREACHED}\\nOK\\n'"
        code, _, _, last = self.run_worker()
        self.assertEqual(code, 1, last)
        self.assertEqual(sh(self.repo, "git", "rev-parse", "main"), main)
        self.assertIn("did not run the voice selftest", last["text"])

    def test_a_run_that_chose_its_modules_is_refused_even_with_voice(self):
        main = sh(self.repo, "git", "rev-parse", "main")
        chose = selector.SELECTED.format(3)
        self.cfg.repo_tests["keel"] = f"printf '{chose}\\nok: x\\nvoice: 1.0s, exit 0\\n'"
        code, _, _, last = self.run_worker()
        self.assertEqual(code, 1, last)
        self.assertEqual(sh(self.repo, "git", "rev-parse", "main"), main)
        self.assertIn("not every module", last["text"])

    def test_red_then_green_on_the_rerun_deploys_and_says_so(self):
        self.cfg.repo_tests["keel"] = ("printf 'FAIL: test_x (tests.test_a.A.test_x)\\nvoice: 90.0s, exit 0\\n'; "
                                       "exit 1")
        self.cfg.repo_retests["keel"] = "grep -q test_x {log}"
        main = sh(self.repo, "git", "rev-parse", "main")
        code, _, _, last = self.run_worker()
        self.assertEqual(code, 0, last)
        self.assertNotEqual(sh(self.repo, "git", "rev-parse", "main"), main)
        self.assertIn("passed when rerun once", last["text"])
        self.assertIn("tests.test_a.A.test_x", last["text"])

    def test_a_rerun_that_skipped_voice_is_refused_though_its_job_exits_0(self):
        self.cfg.repo_tests["keel"] = ("printf 'FAIL: test_x (tests.test_a.A.test_x)\\nvoice: 9.0s, exit 1\\n'; "
                                       "exit 1")
        self.cfg.repo_retests["keel"] = ("printf 'voice selftest: skipped, no .venv-voice\\n"
                                         "voice: 0.1s, exit 0\\n'")
        code, _, _, last = self.run_worker()
        self.assertEqual(code, 1, last)
        self.assertIn("skipped the voice selftest", last["text"])

    def test_red_twice_is_not_deployed(self):
        self.cfg.repo_tests["keel"] = "exit 1"
        self.cfg.repo_retests["keel"] = "exit 1"
        code, _, _, last = self.run_worker()
        self.assertEqual(code, 1)
        self.assertIn("failed again on the rerun", last["text"])

    def test_red_with_no_rerun_command_is_red(self):
        self.cfg.repo_tests["keel"] = "exit 1"
        code, _, _, last = self.run_worker()
        self.assertEqual(code, 1)
        self.assertIn("the suite was red", last["text"])

    def test_main_moved_during_the_suite_lands_nothing(self):
        (self.repo / "late.txt").write_text("x\n")
        self.cfg.repo_tests["keel"] = (f"cd {self.repo} && git add late.txt && "
                                       f"git -c user.email=t@x -c user.name=t commit -qm late && {GREEN}")
        code, _, _, last = self.run_worker()
        self.assertEqual(code, 1)
        self.assertIn("moved while the suite ran", last["text"])

    def test_a_dead_worker_is_answered_on_the_ask(self):
        aid = self.said_yes()
        with mock.patch.object(deploy, "spawn", return_value=999999999):
            deploy.upkeep(self.cfg, self.board)
            deploy.upkeep(self.cfg, self.board)
        self.assertIn(deployask.REFUSED, self.moves(aid))


class StatusTest(DeployCase):
    """What the Shipped panel reads (c-636): true at once, from the deploy's own record."""

    def test_his_yes_reads_starting_at_once_not_the_previous_deploy(self):
        first = self.said_yes()
        self.assertEqual(deploy.deploy(self.cfg, self.board, first), 0)
        merging.publish(self.cfg, self.card_branch("c-2", "second", start="next"))
        second = self.said_yes()
        last = deployask.shipped(self.board)["last"]
        self.assertEqual((last["ask"], last["result"]["move"]), (second, deployask.STARTING))

    def advancing_clock(self):
        """The board's clock a second further on every stamp, so an order of times is real."""
        moments = (datetime(2026, 10, 4, 9, 0, 0, tzinfo=timezone.utc) + timedelta(seconds=n)
                   for n in itertools.count())
        patch = mock.patch.object(self.board, "now",
                                  side_effect=lambda: next(moments).isoformat(timespec="seconds"))
        patch.start()
        self.addCleanup(patch.stop)

    def test_each_phase_is_on_the_record_in_order_with_its_time(self):
        self.advancing_clock()
        aid = self.said_yes()
        self.assertEqual(deploy.deploy(self.cfg, self.board, aid), 0)
        steps = deployask.shipped(self.board)["last"]["result"]["steps"]
        self.assertEqual([step["phase"] for step in steps],
                         [deployask.STARTING, deployask.START, deployask.MERGE, deployask.SUITE,
                          deployask.LIVE_PHASE, deployask.DEPLOYED])
        times = [step["at"] for step in steps]
        self.assertNotIn(None, times)
        self.assertEqual(times, sorted(set(times)), "each phase strictly after the one before")

    def test_two_drains_that_both_saw_his_yes_start_one_worker(self):
        """`keel drain --once` is another process with its own lock: the claim is the board's
        (review F2). Both read the ask untaken, then both try to start it."""
        self.said_yes()
        row = deployask.to_start(self.board, "keel")
        other = Board(self.cfg.db_path, integrated=self.cfg.integrated)
        self.addCleanup(other.close)
        with mock.patch.object(deploy, "spawn", return_value=os.getpid()) as spawned:
            deploy.start(self.cfg, self.board, row)
            deploy.start(self.cfg, other, row)
        spawned.assert_called_once_with(self.cfg, row["id"])

    def test_a_yes_held_behind_a_running_deploy_is_not_waiting_for_the_drain(self):
        """The drain holds a second Deploy back while a worker runs the first, on purpose:
        that is not the drain being away (review r1 regression)."""
        first = self.said_yes()
        with mock.patch.object(deploy, "spawn", return_value=os.getpid()):
            deploy.upkeep(self.cfg, self.board)
        self.assertIsNotNone(deployask.deploying(self.board, first))
        merging.publish(self.cfg, self.card_branch("c-2", "second", start="next"))
        said = deployask.command(self.cfg, self.board, types.SimpleNamespace(preview=False), "human")
        second = said["answered"][0]
        later = (datetime.now(timezone.utc) + timedelta(hours=1)).isoformat(timespec="seconds")
        def first_step():
            with mock.patch.object(self.board, "now", return_value=later):
                return deployask.result_of(self.board, asks.get(self.board, second), wait=60)["steps"][0]
        self.assertFalse(first_step()["waiting"], first_step()["text"])
        # that worker gone and no drain to answer it: the held Deploy is waiting for the drain
        with mock.patch.object(landing, "alive", return_value=False):
            self.assertTrue(first_step()["waiting"], first_step()["text"])

    def test_a_worker_that_will_not_start_is_refused_not_left_starting(self):
        aid = self.said_yes()
        with mock.patch.object(deploy, "spawn", side_effect=OSError("no python")):
            deploy.upkeep(self.cfg, self.board)
        steps = deployask.result_of(self.board, asks.get(self.board, aid))["steps"]
        self.assertEqual(steps[0]["move"], deployask.STARTING)
        self.assertEqual(steps[-1]["move"], deployask.REFUSED)

    def answer_by_kb(self, aid) -> dict:
        """`kb console answer <aid> A --json`, as his tap runs it; the payload it printed."""
        token = config.human_token(self.cfg.token_path)
        out = io.StringIO()
        with mock.patch.object(cli, "load_config", return_value=self.cfg), \
                mock.patch.dict(os.environ, {"KEEL_TOKEN": token}), \
                contextlib.redirect_stdout(out):
            self.assertEqual(cli.main(["console", "answer", aid, "A", "--json"]), 0)
        return json.loads(out.getvalue())

    def test_his_tap_with_no_drain_listening_says_nobody_heard_it(self):
        self.pass_()
        payload = self.answer_by_kb(self.deploy_asks()[0]["id"])
        self.assertEqual(payload["kick"], kick.NOBODY)

    def test_his_tap_s_kb_kicks_the_drain_and_the_kick_starts_the_deploy(self):
        """The real wiring: his `kb`, the drain's inbox and its kick thread. Only the worker's
        spawn is faked, and the harness listing, which would run the real `claude` CLI."""
        self.pass_()
        aid = self.deploy_asks()[0]["id"]
        inbox = kick.Inbox.open(self.cfg)
        self.addCleanup(inbox.close)
        started = threading.Event()
        listener = kick.Listener(inbox, lambda: drain.carry_pass(self.cfg), lambda: None)
        with mock.patch.object(drain.harness, "agents_across", return_value=[]), \
                mock.patch.object(deploy, "spawn", side_effect=lambda *a: started.set() or os.getpid()) as spawned:
            listener.start()
            self.addCleanup(listener.stop)
            payload = self.answer_by_kb(aid)
            self.assertTrue(started.wait(10), "the kick started his Deploy")
            listener.stop()
        self.assertEqual(payload["kick"], kick.HEARD)
        spawned.assert_called_once_with(self.cfg, aid)
        self.assertEqual(deployask.result_of(self.board, asks.get(self.board, aid))["phase"],
                         deployask.START)


class WorkerRefusalTest(DeployCase):
    """The worker's refusals that move nothing (c-526, review 2 F6)."""

    def yes(self):
        aid = self.said_yes()
        return aid, lambda: deploy.deploy(self.cfg, self.board, aid)

    def test_a_dirty_live_checkout_is_refused(self):
        aid, run = self.yes()
        (self.repo / "README").write_text("mid-edit\n")
        main = sh(self.repo, "git", "rev-parse", "main")
        self.assertEqual(run(), 1)
        self.assertEqual(sh(self.repo, "git", "rev-parse", "main"), main)
        self.assertIn("uncommitted changes", self.board.events(aid)[-1]["text"])

    def test_a_checkout_off_main_is_refused(self):
        aid, run = self.yes()
        sh(self.repo, "git", "checkout", "-q", "-b", "elsewhere")
        self.assertEqual(run(), 1)
        self.assertIn("not on main", self.board.events(aid)[-1]["text"])

    def test_his_commit_that_clashes_with_next_is_refused(self):
        aid, run = self.yes()
        (self.repo / "new.txt").write_text("his version\n")
        sh(self.repo, "git", "add", "."); sh(self.repo, "git", "commit", "-q", "-m", "clash")
        self.assertEqual(run(), 1)
        self.assertIn("conflict with next", self.board.events(aid)[-1]["text"])

    def test_a_yes_runs_once(self):
        aid, run = self.yes()
        self.assertEqual(run(), 0)
        self.assertEqual(run(), 1, "a second run of the same Yes deploys nothing")

    def test_next_moving_after_his_yes_deploys_what_he_said_yes_to(self):
        aid, run = self.yes()
        pinned = deployask.facts_of(asks.get(self.board, aid))["sha"]
        merging.publish(self.cfg, self.card_branch("c-2", "later", start="next"))
        moved = merging.ref_head(self.repo, "next")
        self.assertEqual(run(), 0)
        self.assertEqual(sh(self.repo, "git", "rev-parse", "main"), pinned)
        self.assertEqual(merging.ref_head(self.repo, "next"), moved, "next is never moved back")
        self.pass_()
        self.assertEqual(self.deploy_asks()[0]["state"], "open", "the later card gets its own ask")


class LockTest(DeployCase):
    def test_one_checkout_is_one_lock_whatever_the_space(self):
        from keel import landing
        from keel.config import Space
        self.cfg.spaces["other"] = Space(name="other", config_dir=self.dir / "cfg-other",
                                           repos={"keel": self.repo}, contract=None, adapter=None)
        self.assertEqual(landing.lock_path(self.cfg, {"space": "personal", "repo": "keel"}),
                         landing.lock_path(self.cfg, {"space": "other", "repo": "keel"}))



class LandingRecordTest(unittest.TestCase):
    def test_a_green_landing_with_voice_records_its_tree_and_one_without_does_not(self):
        with tempfile.TemporaryDirectory() as tmp:
            cfg = mock.Mock(state_dir=Path(tmp))
            merging.record_tested(cfg, "tree-a", "c-1")
            self.assertEqual(merging.tested_whole(cfg, "tree-a")["card"], "c-1")
            self.assertIsNone(merging.tested_whole(cfg, "tree-b"))
            self.assertTrue(merging.VOICE_PASSED.search("ok: x\nvoice: 117.3s, exit 0\n"))
            self.assertFalse(merging.VOICE_PASSED.search("voice selftest: skipped, no .venv-voice\n"))


class LandingReachTest(IntegrationCase):
    """c-646: the landing runs `make test BASE={base}`, `{base}` the commit the merge is
    built on (next's head), and only a run of every module with voice passing records its
    tree, so the deploy skips its full suite only on a tree a full run proved."""

    def setUp(self):
        super().setUp()
        venv = self.repo / deploy.VENV / "bin"
        venv.mkdir(parents=True)
        (venv / "python").write_text("#!/bin/sh\n")
        (venv / "python").chmod(0o755)                 # the Makefile's `-x`
        merging.publish(self.cfg, self.card)            # next is ahead of main from here
        self.second = self.card_branch("c-2", "second", start="next")

    def land(self, command: str) -> str | None:
        self.cfg.repo_tests["keel"] = command
        merging.publish(self.cfg, self.second)
        landed = merging.tree_of(self.repo, merging.ref_head(self.repo, "next"))
        return (merging.tested_whole(self.cfg, landed) or {}).get("card")

    def test_base_is_next_s_head_and_a_full_run_records_the_tree(self):
        next_head = merging.ref_head(self.repo, "next")
        self.assertNotEqual(next_head, sh(self.repo, "git", "rev-parse", "main"))
        self.assertEqual(self.land(f"test {{base}} = {next_head} && {GREEN}"), "c-2")

    def test_a_run_with_neither_voice_line_records_nothing(self):
        self.assertIsNone(self.land("printf 'Ran 3 tests\\nOK\\n'"))

    def test_a_narrow_make_test_records_nothing_even_with_voice(self):
        chose = selector.SELECTED.format(3)
        self.assertIsNone(self.land(f"printf '{chose}\\nok: x\\nvoice: 1.0s, exit 0\\n'"))

    def test_a_skipped_selftest_records_nothing_though_its_job_exits_0(self):
        self.assertIsNone(self.land("printf 'voice selftest: skipped, no .venv-voice\\n"
                                    "voice: 0.1s, exit 0\\n'"))

    def test_a_venv_python_that_is_not_executable_is_not_linked(self):
        (self.repo / deploy.VENV / "bin" / "python").chmod(0o644)
        self.assertIsNone(self.land(GREEN))


if __name__ == "__main__":
    unittest.main()
