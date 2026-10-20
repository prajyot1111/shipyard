"""c-599, the live strip: what a house is doing now, read from the harness while he watches.

- The transcript tail (`keel/livetail.py`) on real transcript lines
  (`tests/fixtures/harness/live-tail.jsonl`, one Bosun turn on the box, trimmed), plus the
  todo tools in the same record shape.
- The job record's fields, as probed on 2.1.285.
- The door's lease: it reads nothing without one, sends only what moved, and ends when it
  runs out. The box's watcher: nothing while nobody watches.
- The box's holder: a delta said on the event stream, a read that found nothing new not said,
  a full push dropping what its machine no longer names; never a board write.
- The deck: a card whose house is on another machine takes its house from the strip, and the
  newest Notification of its turn is on the card at once.
"""

import json
import shutil
import subprocess
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest import mock

from datetime import datetime, timedelta

from keel import deckevents, deckstate, harness, livestrip, livetail, serve
from keel.board import Board
from tests.helpers import make_config, serve_in_background

FIXTURE = Path(__file__).resolve().parent / "fixtures" / "harness" / "live-tail.jsonl"
SESSION = "5972cdc3-caa5-4d82-bc4d-d088812b5d04"


def record(kind: str, content, at: str, **extra) -> str:
    """One transcript line in the shape of the fixture's own."""
    return json.dumps(dict({"parentUuid": None, "isSidechain": False, "type": kind,
                            "message": {"role": kind, "content": content}, "timestamp": at,
                            "sessionId": SESSION}, **extra))


def tool_use(name: str, given: dict, at: str, use_id: str) -> str:
    return record("assistant", [{"type": "tool_use", "id": use_id, "name": name, "input": given}], at)


def tool_result(use_id: str, at: str) -> str:
    return record("user", [{"tool_use_id": use_id, "type": "tool_result", "content": "ok"}], at)


class TailTest(unittest.TestCase):
    def lines(self) -> list[str]:
        return FIXTURE.read_text().splitlines()

    def test_the_real_turn_reads_as_it_happened(self):
        facts = livetail.parse(self.lines())
        self.assertEqual(facts["tool"]["name"], "Bash")
        self.assertEqual(facts["tool"]["what"], "Create e2e worktree and read setup's arguments")
        self.assertEqual(facts["tool"]["at"], "2026-09-30T09:28:05.352Z")
        self.assertTrue(facts["tool"]["done"], "its result is the next line")
        self.assertEqual(facts["turn_at"], "2026-09-30T09:27:23.508Z", "his prompt, not the queue line")
        self.assertIsNone(facts["turn_ended_at"], "the turn_duration before the prompt closed the last one")
        self.assertEqual(facts["wrote_at"], "2026-09-30T09:28:05.919Z")
        self.assertIsNone(facts["todos"])

    def test_a_tool_with_no_result_yet_is_running(self):
        lines = self.lines() + [tool_use("Read", {"file_path": "/x/y.py"}, "2026-09-30T09:28:09Z", "t9")]
        tool = livetail.parse(lines)["tool"]
        self.assertEqual((tool["name"], tool["what"], tool["done"]), ("Read", "/x/y.py", False))

    def test_a_turn_duration_closes_the_turn(self):
        lines = self.lines() + [json.dumps({"type": "system", "subtype": "turn_duration",
                                            "timestamp": "2026-09-30T09:29:00Z"})]
        facts = livetail.parse(lines)
        self.assertEqual(facts["turn_ended_at"], "2026-09-30T09:29:00Z")
        self.assertEqual(facts["turn_at"], "2026-09-30T09:27:23.508Z")

    def test_a_subagent_line_is_never_the_house_s(self):
        side = json.loads(tool_use("Grep", {"pattern": "x"}, "2026-09-30T09:29:00Z", "s1"))
        side["isSidechain"] = True
        self.assertEqual(livetail.parse(self.lines() + [json.dumps(side)])["tool"]["name"], "Bash")

    def test_todowrite_is_the_whole_list(self):
        todos = [{"content": "Read the code", "status": "completed", "activeForm": "Reading the code"},
                 {"content": "Write tests", "status": "in_progress", "activeForm": "Writing tests"},
                 {"content": "Commit", "status": "pending", "activeForm": "Committing"}]
        lines = self.lines() + [tool_use("TodoWrite", {"todos": todos}, "2026-09-30T09:29:00Z", "t1"),
                                tool_result("t1", "2026-09-30T09:29:01Z")]
        self.assertEqual(livetail.parse(lines)["todos"], {"done": 1, "total": 3, "active": "Writing tests"})

    def test_task_tools_are_counted_one_at_a_time(self):
        lines = [tool_use("TaskCreate", {"subject": "Parse", "activeForm": "Parsing"}, "2026-09-30T09:00:00Z", "a"),
                 tool_use("TaskCreate", {"subject": "Draw"}, "2026-09-30T09:00:01Z", "b"),
                 tool_use("TaskUpdate", {"taskId": "1", "status": "completed"}, "2026-09-30T09:00:02Z", "c"),
                 tool_use("TaskUpdate", {"taskId": "2", "status": "in_progress"}, "2026-09-30T09:00:03Z", "d")]
        self.assertEqual(livetail.parse(lines)["todos"], {"done": 1, "total": 2, "active": "Draw"})


class ReviewTest(unittest.TestCase):
    """c-599 review: what the strip may carry, and what it must not lose."""

    def test_a_token_in_a_bash_command_never_reaches_the_strip(self):
        command = 'curl -H "Authorization: Bearer sk-live-4f9a8b7c6d5e" https://x.test && GITHUB_TOKEN=ghp_abcdefghijklmnopqrstuvwx gh pr list'
        tool = livetail.parse([tool_use("Bash", {"command": command}, "2026-09-30T09:00:00Z", "t")])["tool"]
        self.assertNotIn("sk-live-4f9a8b7c6d5e", tool["what"])
        self.assertNotIn("ghp_abcdefghijklmnopqrstuvwx", tool["what"])
        bare = livetail.parse([tool_use("Bash", {"command": "deploy --password hunter2secret ghp_abcdefghijklmnopqrstuvwxyz0123"},
                                        "2026-09-30T09:00:00Z", "u")])["tool"]["what"]
        self.assertNotIn("hunter2secret", bare)
        self.assertNotIn("ghp_abcdefghijklmnopqrstuvwxyz0123", bare)

    def test_an_mcp_tool_is_its_name_and_never_its_body(self):
        tool = livetail.parse([tool_use("mcp__mail__send", {"body": "dear sir, the password is x", "to": "a@b.c"},
                                        "2026-09-30T09:00:00Z", "m")])["tool"]
        self.assertEqual((tool["name"], tool["what"]), ("mcp__mail__send", ""))

    def test_an_unknown_tool_s_other_strings_are_not_picked_up(self):
        tool = livetail.parse([tool_use("Weird", {"payload": "anything at all"}, "2026-09-30T09:00:00Z", "w")])["tool"]
        self.assertEqual(tool["what"], "")

    def test_todo_text_and_the_job_record_detail_are_redacted(self):
        todos = [{"content": "x", "status": "in_progress", "activeForm": "Using token=abc123secret to push"}]
        got = livetail.parse([tool_use("TodoWrite", {"todos": todos}, "2026-09-30T09:00:00Z", "t")])["todos"]
        self.assertNotIn("abc123secret", got["active"])
        with tempfile.TemporaryDirectory() as tmp:
            jobs = Path(tmp) / "jobs" / "abcd1234"
            jobs.mkdir(parents=True)
            (jobs / "state.json").write_text(json.dumps({"state": "working", "detail": "running with api_key=zzz999secret",
                                                          "inFlight": {"tasks": 1}, "fan": [
                {"kind": "agent", "label": "call with password=pw1234567", "startedAt": 1}]}))
            got = livetail.job(Path(tmp), "abcd1234")
        self.assertNotIn("zzz999secret", got["detail"])
        self.assertNotIn("pw1234567", got["agents"][0]["label"])

    def test_injected_user_records_do_not_restart_the_turn(self):
        lines = [record("user", "do the thing", "2026-09-30T09:00:00Z"),
                 record("user", "Stop hook feedback: carry on", "2026-09-30T09:05:00Z", isMeta=True),
                 record("user", "<local-command-stdout>ok</local-command-stdout>", "2026-09-30T09:06:00Z")]
        self.assertEqual(livetail.parse(lines)["turn_at"], "2026-09-30T09:00:00Z")

    def test_a_task_notification_starts_a_new_turn_only_when_it_wakes_the_house(self):
        """c-604: a notification on an idle house read `in turn 8m`; one it answers is a new, ended turn."""
        lines = [record("user", "do the thing", "2026-09-30T09:00:00Z", origin={"kind": "human"}),
                 record("assistant", [{"type": "text", "text": "done"}], "2026-09-30T09:10:00Z"),
                 record("user", "<task-notification>\n<task-id>b1</task-id>", "2026-09-30T09:20:00Z",
                        origin={"kind": "task-notification", "producer": "session-task"}),
                 record("assistant", [{"type": "text", "text": "noted"}], "2026-09-30T09:20:02Z")]
        for number in (1, 3):
            lines[number] = json.dumps(dict(json.loads(lines[number]), message={
                "role": "assistant", "content": json.loads(lines[number])["message"]["content"],
                "stop_reason": "end_turn"}))
        facts = livetail.parse(lines)
        self.assertEqual(facts["turn_at"], "2026-09-30T09:20:00Z", "c-604 review: the wake is a new turn")
        self.assertEqual(facts["turn_ended_at"], "2026-09-30T09:20:02Z", "idle, so the turn has ended")
        # with no answer yet the notification alone starts nothing
        self.assertEqual(livetail.parse(lines[:3])["turn_at"], "2026-09-30T09:00:00Z")

    def test_an_interruption_or_a_compaction_summary_starts_no_turn(self):
        lines = [record("user", "build it", "2026-09-30T09:00:00Z", origin={"kind": "human"}),
                 record("user", [{"type": "text", "text": "[Request interrupted by user]"}], "2026-09-30T09:05:00Z"),
                 record("user", "This session is being continued from a previous conversation.",
                        "2026-09-30T09:06:00Z", isCompactSummary=True)]
        self.assertEqual(livetail.parse(lines)["turn_at"], "2026-09-30T09:00:00Z")

    def test_an_api_error_record_ends_the_turn(self):
        error = json.loads(record("assistant", [{"type": "text", "text": "API Error: 529 overloaded"}],
                                  "2026-09-30T09:07:00Z", isApiErrorMessage=True))
        error["message"]["stop_reason"] = "stop_sequence"
        lines = [record("user", "build it", "2026-09-30T09:00:00Z", origin={"kind": "human"}), json.dumps(error)]
        self.assertEqual(livetail.parse(lines)["turn_ended_at"], "2026-09-30T09:07:00Z")

    def test_the_final_message_ends_the_turn_without_a_turn_duration(self):
        final = json.loads(record("assistant", [{"type": "text", "text": "all done"}], "2026-09-30T09:30:00Z"))
        final["message"]["stop_reason"] = "end_turn"
        facts = livetail.parse(FIXTURE.read_text().splitlines() + [json.dumps(final)])
        self.assertEqual(facts["turn_ended_at"], "2026-09-30T09:30:00Z")

    def test_a_house_working_on_a_hand_back_is_in_its_turn_not_ended(self):
        """c-604: a working house read `turn ended`: the hand-back (a peer's isMeta record) is
        not a new turn, and the house acting on it is back in the one he started."""
        ended = json.loads(record("assistant", [{"type": "text", "text": "waiting"}], "2026-09-30T09:10:00Z"))
        ended["message"]["stop_reason"] = "end_turn"
        lines = [record("user", "build it", "2026-09-30T09:00:00Z", origin={"kind": "human"}),
                 json.dumps(ended),
                 json.dumps({"type": "system", "subtype": "turn_duration", "timestamp": "2026-09-30T09:10:01Z"}),
                 record("user", "Another Claude session sent a message: report", "2026-09-30T09:15:00Z",
                        isMeta=True, origin={"kind": "peer", "handback": True}),
                 tool_use("Bash", {"command": "make test"}, "2026-09-30T09:15:03Z", "t1")]
        facts = livetail.parse(lines)
        self.assertEqual(facts["turn_at"], "2026-09-30T09:15:00Z", "c-604 review: a NEW turn, from the hand-back")
        self.assertIsNone(facts["turn_ended_at"])

    def test_a_newest_record_bigger_than_the_tail_keeps_the_last_facts(self):
        livetail.TAILS.clear()
        self.addCleanup(livetail.TAILS.clear)
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "t.jsonl"
            shutil.copy(FIXTURE, path)
            first = livetail.tail(path)
            with open(path, "a") as handle:
                handle.write(record("user", [{"type": "tool_result", "tool_use_id": "x", "content": "y" * 4000}],
                                    "2026-09-30T09:40:00Z") + "\n")
            with mock.patch.object(livetail, "TAIL_BYTES", 3000):
                second = livetail.tail(path)
        self.assertEqual(second["tool"], first["tool"], "one huge record is not an empty house")

    def test_the_transcript_path_is_found_once_per_session(self):
        with tempfile.TemporaryDirectory() as tmp:
            config = Path(tmp)
            path = config / "projects" / "-a" / f"{SESSION}.jsonl"
            path.parent.mkdir(parents=True)
            path.write_text("")
            livetail.PATHS.clear()
            self.addCleanup(livetail.PATHS.clear)
            self.assertEqual(livetail.transcript_path(config, SESSION, "/elsewhere"), path)
            with mock.patch.object(Path, "glob", side_effect=AssertionError("globbed again")):
                self.assertEqual(livetail.transcript_path(config, SESSION, "/elsewhere"), path)


class TailFileTest(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.dir = Path(tmp.name)
        livetail.TAILS.clear()
        self.addCleanup(livetail.TAILS.clear)

    def test_parsed_again_only_when_the_file_moves(self):
        path = self.dir / "t.jsonl"
        shutil.copy(FIXTURE, path)
        with mock.patch.object(livetail, "parse", wraps=livetail.parse) as parse:
            first = livetail.tail(path)
            livetail.tail(path)
            self.assertEqual(parse.call_count, 1, "an unmoved file is not read again")
            with open(path, "a") as handle:
                handle.write(tool_use("Edit", {"file_path": "a.py"}, "2026-09-30T09:30:00Z", "e") + "\n")
            second = livetail.tail(path)
        self.assertEqual(parse.call_count, 2)
        self.assertEqual((first["tool"]["name"], second["tool"]["name"]), ("Bash", "Edit"))

    def test_only_the_last_bytes_are_read_and_a_cut_line_is_dropped(self):
        path = self.dir / "big.jsonl"
        early = tool_use("Early", {"x": "y"}, "2026-09-30T08:00:00Z", "e0")
        path.write_text(early + "\n" + ("x" * 5000) + "\n" + FIXTURE.read_text())
        with mock.patch.object(livetail, "TAIL_BYTES", len(FIXTURE.read_bytes()) + 100):
            facts = livetail.tail(path)
        self.assertEqual(facts["tool"]["name"], "Bash")
        self.assertEqual(livetail.tail(self.dir / "missing.jsonl"), {})
        self.assertEqual(livetail.tail(None), {})

    def test_the_transcript_is_found_where_the_harness_keeps_it(self):
        config = self.dir / "cfg"
        cwd = "/home/bosun/.claude/jobs/74852630/tmp/probe"
        self.assertEqual(livetail.project_dir(cwd), "-home-bosun--claude-jobs-74852630-tmp-probe")
        by_cwd = config / "projects" / livetail.project_dir(cwd) / f"{SESSION}.jsonl"
        by_cwd.parent.mkdir(parents=True)
        by_cwd.write_text("")
        self.assertEqual(livetail.transcript_path(config, SESSION, cwd), by_cwd)
        self.assertEqual(livetail.transcript_path(config, SESSION, "/elsewhere"), by_cwd, "found by name")
        recorded = self.dir / "named.jsonl"
        recorded.write_text("")
        self.assertEqual(livetail.transcript_path(config, SESSION, cwd, str(recorded)), recorded)
        self.assertIsNone(livetail.transcript_path(config, "0000", cwd))

    def test_the_job_record_says_what_the_harness_says(self):
        jobs = self.dir / "cfg" / "jobs" / "5972cdc3"
        jobs.mkdir(parents=True)
        (jobs / "state.json").write_text(json.dumps({
            "state": "working", "detail": "running baseline E2E card test on sandbox", "tempo": "active",
            "inFlight": {"tasks": 2, "queued": 0, "kinds": ["local_agent"]},
            "fan": [{"id": "a1", "kind": "agent", "label": "Build c-597 work pipeline", "startedAt": 1790760405958},
                    {"id": "b1", "kind": "shell", "label": "sleep 30", "startedAt": 1790760676881}],
            "linkScanPath": "/somewhere/t.jsonl", "updatedAt": "2026-09-30T09:31:16.887Z"}))
        got = livetail.job(self.dir / "cfg", "5972cdc3")
        self.assertEqual(got["detail"], "running baseline E2E card test on sandbox")
        self.assertEqual(got["updated_at"], "2026-09-30T09:31:16.887Z")
        self.assertEqual(got["transcript"], "/somewhere/t.jsonl")
        self.assertEqual(got["agents"], [{"label": "Build c-597 work pipeline", "started_at": 1790760405958}])
        self.assertEqual(livetail.job(self.dir / "cfg", "nothere"), {})
        self.assertEqual(livetail.job(self.dir / "cfg", ""), {})


class Case(unittest.TestCase):
    """A board with one building card whose session is SESSION, and its transcript on disk."""

    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.dir = Path(tmp.name)
        self.cfg = make_config(self.dir)
        self.board = Board(self.cfg.db_path)
        self.addCleanup(self.board.close)
        self.card = self.board.create("personal", "a live one", repo=None, autonomy="autonomous")
        self.board.stage(self.card, "assigned", "human")
        self.board.stage(self.card, "building", "drain")
        self.board.set_fields(self.card, {"session_id": SESSION}, "drain")
        transcript = self.cfg.spaces["personal"].config_dir / "projects" / "-w" / f"{SESSION}.jsonl"
        transcript.parent.mkdir(parents=True)
        shutil.copy(FIXTURE, transcript)
        livetail.TAILS.clear()
        self.addCleanup(livetail.TAILS.clear)
        self.row = {"id": SESSION[:8], "sessionId": SESSION, "cwd": "/w", "kind": "background",
                    "status": "busy", "state": "working", "pid": 42, "startedAt": 1790707707711}

    def cards(self) -> list[dict]:
        return self.board.list_cards()


class FactsTest(Case):
    def test_a_working_house_reads_whole(self):
        facts = livestrip.facts_for(self.cfg, self.cards(), [self.row])[self.card]
        self.assertEqual(facts["status"], "working")
        self.assertEqual(facts["house"]["bg_id"], SESSION[:8])
        self.assertEqual(facts["tool"]["name"], "Bash")
        self.assertEqual(facts["host"], self.cfg.host)
        self.assertTrue(facts["at"])

    def test_idle_and_exited_are_the_listing_s_words(self):
        idle = dict(self.row, status="idle", state="done")
        self.assertEqual(livestrip.facts_for(self.cfg, self.cards(), [idle])[self.card]["status"], "idle")
        gone = livestrip.facts_for(self.cfg, self.cards(), [])[self.card]
        self.assertEqual(gone["status"], "exited")
        self.assertIsNone(gone["house"])
        self.assertEqual(gone["tool"]["name"], "Bash", "an exited house still says what it last did")

    def test_a_done_card_is_not_read(self):
        done = [dict(card, stage="done") for card in self.cards()]
        self.assertEqual(livestrip.facts_for(self.cfg, done, [self.row]), {})

class NoticeTest(Case):
    def hook(self, name: str, kind: str | None = None, session: str = SESSION) -> None:
        payload = {"hook_event_name": name, "session_id": session}
        if kind:
            payload.update(notification_type=kind, message="Claude needs your permission to use Bash")
        self.board.record_hook(self.card, name, payload)

    def notice(self):
        return livestrip.notice(self.board.get(self.card), self.board.events(self.card))

    def test_the_newest_notification_of_the_turn_is_the_notice(self):
        self.assertIsNone(self.notice())
        self.hook("Notification", "permission_prompt")
        got = self.notice()
        self.assertEqual((got["type"], got["message"]), ("permission_prompt", "Claude needs your permission to use Bash"))
        self.assertTrue(got["at"])

    def test_a_stop_ends_it_and_another_session_s_is_not_this_turn_s(self):
        self.hook("Notification", "permission_prompt")
        self.hook("Stop")
        self.assertIsNone(self.notice())
        self.hook("Notification", "idle_prompt", session="another")
        self.assertIsNone(self.notice())


class StripTest(unittest.TestCase):
    def setUp(self):
        self.said = []
        self.clock = [1000.0]
        self.strip = livestrip.Strip(clock=lambda: self.clock[0], publish=self.said.append)

    def test_a_delta_is_said_with_its_facts_and_a_repeat_is_not(self):
        facts = {"at": "t1", "status": "working", "house": {"bg_id": "abc"}}
        self.assertEqual(self.strip.accept("mac", {"c-1": facts}), ["c-1"])
        line = self.said[-1]
        self.assertTrue(line.startswith("live c-1 "))
        self.assertEqual(json.loads(line[len("live c-1 "):])["status"], "working")
        self.assertEqual(self.strip.accept("mac", {"c-1": dict(facts, at="t2")}), [], "only the read time moved")
        self.assertEqual(len(self.said), 1)
        self.assertEqual(self.strip.of("c-1")["at"], "t2", "but the newest read is held")

    def test_a_full_read_drops_what_its_machine_no_longer_names(self):
        self.strip.accept("mac", {"c-1": {"status": "idle"}, "c-2": {"status": "idle"}})
        self.strip.accept("box", {"c-9": {"status": "idle"}})
        self.said.clear()
        self.strip.accept("mac", {"c-1": {"status": "idle"}}, full=True)
        self.assertEqual(self.said, ["live c-2 null"])
        self.assertIsNone(self.strip.of("c-2"))
        self.assertIsNotNone(self.strip.of("c-9"), "another machine's cards are its own")

    def test_a_gone_card_of_another_machine_is_not_dropped(self):
        self.strip.accept("box", {"c-9": {"status": "idle"}})
        self.strip.accept("mac", {}, gone=["c-9"])
        self.assertIsNotNone(self.strip.of("c-9"))

    def test_a_read_is_of_the_card_s_session_and_fresh_only_for_its_seconds(self):
        card = {"id": "c-1", "session_id": "s-2"}
        self.strip.accept("mac", {"c-1": {"status": "exited", "house": None, "session": "s-1"}})
        self.assertIsNone(self.strip.of_session(card), "a read of the session a resume replaced")
        self.strip.accept("mac", {"c-1": {"status": "working", "house": {"bg_id": "b"}, "session": "s-2"}})
        self.assertEqual(self.strip.of_session(card)["status"], "working")
        self.clock[0] += 11
        self.assertIsNone(self.strip.of_session(card, fresh=10))
        self.assertIsNotNone(self.strip.of_session(card))

    def test_unmoved_facts_are_said_again_while_watched_so_their_age_stays_true(self):
        self.strip.accept("mac", {"c-1": {"at": "t1", "status": "idle"}})
        self.clock[0] += livestrip.REPUBLISH_SECONDS - 1
        self.strip.accept("mac", {"c-1": {"at": "t2", "status": "idle"}})
        self.assertEqual(len(self.said), 1)
        self.clock[0] += 2
        self.strip.accept("mac", {"c-1": {"at": "t3", "status": "idle"}})
        self.assertEqual(len(self.said), 2)
        self.assertIn('"at":"t3"', self.said[-1])

    def test_a_quiet_read_is_held_and_not_said(self):
        self.assertEqual(self.strip.accept("box", {"c-1": {"status": "idle"}}, quiet=True), [])
        self.assertEqual(self.said, [])
        self.assertEqual(self.strip.of("c-1")["status"], "idle")


class FakeDeck:
    def __init__(self, cfg, board_path):
        self.cfg = cfg
        self.lock = threading.Lock()
        self.strip = livestrip.Strip(publish=lambda line: None)
        self.path = board_path
        self.listings = 0
        self.rows = []

    def board_stamp(self):
        return "s1"

    def strip_cards(self):
        with Board(self.path) as board:
            return board.list_cards()

    def listing(self, fresh=False):
        self.listings += 1
        return lambda: self.rows


class WatcherTest(Case):
    def test_nobody_watching_is_no_work(self):
        deck = FakeDeck(self.cfg, self.cfg.db_path)
        watcher = livestrip.Watcher(deck, watching=lambda: False, wait=lambda s: None)
        watcher.run()
        self.assertEqual(deck.listings, 0)
        self.assertIsNone(watcher.thread)

    def test_a_watched_step_reads_the_houses(self):
        deck = FakeDeck(self.cfg, self.cfg.db_path)
        deck.rows = [self.row]
        watcher = livestrip.Watcher(deck, watching=lambda: True)
        watcher.step()
        self.assertEqual(deck.strip.of(self.card)["status"], "working")
        self.assertEqual(deck.strip.of(self.card)["session"], SESSION)
        self.assertEqual(deck.listings, 1)

    def test_a_stream_opened_as_the_thread_exits_is_not_left_unwatched(self):
        deck = FakeDeck(self.cfg, self.cfg.db_path)
        answers = iter([False, True, True])        # nobody, then somebody arrives at the exit
        watcher = livestrip.Watcher(deck, watching=lambda: next(answers, False), wait=lambda s: None)
        watcher.thread = "running"
        steps = []
        watcher.step = lambda: steps.append(1)
        watcher.run()
        self.assertEqual(steps, [1], "the stream that arrived as it exited is read")
        self.assertIsNone(watcher.thread)

    def test_close_waits_for_the_read_in_flight(self):
        """A closed deck's watcher has finished: its last `claude agents` wrote into a
        config dir the test was already removing when close only set `stop` (c-599)."""
        deck = FakeDeck(self.cfg, self.cfg.db_path)
        watcher = livestrip.Watcher(deck, watching=lambda: True)
        entered, release, done = threading.Event(), threading.Event(), []

        def step():
            entered.set()
            release.wait(5)
            done.append(1)
        watcher.step = step
        watcher.ensure()
        self.assertTrue(entered.wait(5))
        threading.Timer(0.2, release.set).start()
        watcher.close()
        self.assertEqual(done, [1], "close returned while a read was still running")
        self.assertIsNone(watcher.thread)

class DeckTest(Case):
    def test_the_watcher_s_cards_come_off_the_stamp_s_connection(self):
        deck = deckstate.Deck(self.cfg)
        self.addCleanup(lambda: deck.stamp_conn and deck.stamp_conn.close())
        cards = deck.strip_cards()
        self.assertEqual([c["id"] for c in cards], [self.card])
        self.assertEqual(livestrip.watched(self.cfg, cards)[0]["session_id"], SESSION)
        self.board.set_fields(self.card, {"options": {"archived": True}}, "human")
        self.assertEqual(livestrip.watched(self.cfg, deck.strip_cards()), [], "an archived card is not read")
        deck.stamp_conn.close()
        deck.stamp_conn, deck.stamped_at = None, float("inf")
        self.assertEqual(deck.strip_cards(), [], "a closed server's deck reads nothing")

    def test_a_house_here_is_read_when_the_document_is_built(self):
        state = deckstate.build(self.cfg, self.board, rows=[self.row])
        view = next(c for c in state["cards"] if c["id"] == self.card)
        self.assertEqual(view["live"]["tool"]["name"], "Bash")
        self.assertIsNone(view["notice"])

    def test_a_notice_the_house_wrote_past_is_not_on_the_card(self):
        self.board.record_hook(self.card, "Notification", {"session_id": SESSION, "notification_type": "permission_prompt",
                                                           "message": "Claude needs your permission"})
        at = self.board.events(self.card)[-1]["at"]
        later = (datetime.fromisoformat(at) + timedelta(seconds=30)).isoformat()
        strip = livestrip.Strip(publish=lambda line: None)
        strip.accept(self.cfg.host, {self.card: {"status": "working", "session": SESSION,
                                                 "wrote_at": later}})
        with mock.patch.object(livestrip, "facts_for", return_value={}):
            view = next(c for c in deckstate.build(self.cfg, self.board, rows=[], strip=strip)["cards"]
                        if c["id"] == self.card)
        self.assertIsNone(view["notice"])

    def test_nothing_is_written_to_the_board(self):
        before = len(self.board.events(self.card))
        strip = livestrip.Strip(publish=lambda line: None)
        strip.accept("mac", {self.card: {"status": "working"}})
        livestrip.facts_for(self.cfg, self.cards(), [self.row])
        self.assertEqual(len(self.board.events(self.card)), before)


class ServeTest(Case):
    """Opening the deck's event stream is what starts the strip's reads."""

    def setUp(self):
        super().setUp()
        import urllib.request
        self.urlopen = urllib.request.urlopen
        self.Request = urllib.request.Request
        self.cfg.lavish_port = 1
        self.server = serve.make_server(self.cfg, port=0)
        serve_in_background(self.server)
        self.addCleanup(self.server.server_close)
        self.addCleanup(self.server.shutdown)
        self.base = f"http://127.0.0.1:{self.server.server_address[1]}"
        self.stream = deckevents.HUB.open()
        self.addCleanup(deckevents.HUB.close, self.stream)

    def test_opening_the_stream_starts_the_watcher(self):
        with mock.patch.object(self.server.deck.watcher, "ensure") as ensure:
            response = self.urlopen(self.base + "/api/events", timeout=10)
            try:
                deadline = time.monotonic() + 5
                while not ensure.called and time.monotonic() < deadline:
                    time.sleep(0.02)
            finally:
                response.close()
        ensure.assert_called()


@unittest.skipUnless(shutil.which("node"), "node is not on this machine")
class PageTest(unittest.TestCase):
    def test_the_strip_draws_what_the_facts_say(self):
        root = Path(__file__).resolve().parent.parent
        result = subprocess.run(["node", str(root / "tests" / "fixtures" / "deck-live.js"), str(root / "app")],
                                capture_output=True, text=True, timeout=60)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(result.stdout), {"ok": True}, result.stdout)


if __name__ == "__main__":
    unittest.main()
