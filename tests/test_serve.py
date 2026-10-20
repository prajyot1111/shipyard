"""The serve role: the state document against a scratch board and fixture files, every
action verb reaching its kb command with the token, artifact tokens and the denylist, the
drain pill parser, the usage reader, and the HTTP door end to end on a free port."""

import contextlib
import http.client
import http.server as http_server
import io
import itertools
import json
import os
import re
import select
import shutil
import socket
import subprocess
import sys
import tempfile
import threading
import time
import unittest
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timedelta
from pathlib import Path
from unittest import mock

from keel import actions, artifacts, deckstate, deckviews, idleclose, segments, serve, tellhouse
from keel.board import Board
from keel.config import human_token
from tests.helpers import SESSION, FakeHarness, background_row, make_config, serve_in_background, superuser_builder

REVIEW_SESSION = "0abc8888-0000-4000-8000-000000000003"
USAGE = {"rate_limits": {"five_hour": {"used_percentage": 18, "resets_at": 1789593600},
                         "seven_day": {"used_percentage": 66, "resets_at": 1789632000}},
         "model": "Fable 5.1", "captured_at": 1789576598}


class DeckCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name)
        self.cfg = make_config(self.dir)
        self.cfg.host = "mac"
        self.cfg.source = self.dir / "keel.toml"
        self.cfg.source.write_text(
            "[keel]\n"
            f'state_dir = "{self.cfg.state_dir}"\n'
            f'adapters_dir = "{self.cfg.adapters_dir}"\n'
            f'segments_dir = "{self.cfg.segments_dir}"\n'
            'drain_paused = true\nhost = "mac"\n'
            "[spaces.personal]\n"
            f'config_dir = "{self.dir / "cfg-personal"}"\n'
            # c-631: a space served here that lists no repo refuses a repo card, so the
            # personal cards a remote kb files name one it lists
            "[spaces.personal.repos]\n"
            f'keel = "{self.dir / "keel"}"\n'
            "[spaces.work]\n"
            f'config_dir = "{self.dir / "cfg-work"}"\n'
            'adapter = "work"\n')
        self.board = Board(self.cfg.db_path)
        self.token = human_token(self.cfg.token_path)
        self.usage = self.dir / "usage.json"
        self.usage.write_text(json.dumps(USAGE))
        os.environ["KEEL_USAGE_FILE"] = str(self.usage)
        self.addCleanup(os.environ.pop, "KEEL_USAGE_FILE", None)
        self.seed()

    def tearDown(self):
        self.board.close()
        self.tmp.cleanup()

    def seed(self):
        b = self.board
        self.review = b.create("work", "at the outcome gate", repo="api", actor="human")
        b.stage(self.review, "assigned", "human")
        b.stage(self.review, "building", "drain")
        plan = self.cfg.card_dir(self.review) / "plan.md"
        plan.write_text("# Plan\n\n- one\n- two\n\n```sh\nkb show\n```\n")
        (self.cfg.card_dir(self.review) / "context.md").write_text("## Where it stands\n\nfine\n\n## PR body\n\nThe body.\n")
        b.stage(self.review, "review", "house", plan_ref=str(plan), output_ref="https://example.test/pr/1")
        self.blocked = b.create("work", "blocked at building", repo="api", actor="human")
        b.stage(self.blocked, "assigned", "human")
        b.stage(self.blocked, "building", "drain")
        b.set_session(self.blocked, SESSION, "drain", bg_id=SESSION[:8])
        b.record_hook(self.blocked, "Stop", {"last_assistant_message": "I need the credentials", "transcript_path": "/t.jsonl"})
        b.block(self.blocked, "house exited twice at building", "drain")
        self.gate = b.create("work", "plan gate", repo="api", autonomy="attended", actor="human")
        b.stage(self.gate, "assigned", "human")
        b.stage(self.gate, "planning", "drain", plan_ref="https://127.0.0.1:0/s/plan")
        self.live = b.create("personal", "a live house", repo="keel", actor="human", topic="deck")
        b.stage(self.live, "assigned", "human")
        b.stage(self.live, "building", "drain")
        b.set_session(self.live, "0abc9999-0000-4000-8000-000000000002", "drain", bg_id="0abc9999")
        self.inbox = b.create("personal", "an inbox card", actor="human", topic="deck")
        logs = self.cfg.logs_dir / "drain.log"
        stamp = (datetime.now().astimezone() - timedelta(seconds=20)).isoformat(timespec="seconds")
        logs.write_text("junk\n" + stamp + " drain: houses=1 resumed=0 blocked=0 started=0 paused=True\n")
        seg = self.cfg.segments_dir / "alpha"
        (seg / "app").mkdir(parents=True)
        (seg / "summary.json").write_text(json.dumps({"tiles": [{"label": "things", "value": 3}], "generated_at": "2026-09-16T10:00:00+05:30"}))
        (seg / "app" / "index.html").write_text("<!doctype html><title>alpha</title>alpha app\n")
        (self.cfg.segments_dir / "beta").mkdir()

    def rows(self):
        return [background_row(self.live, "0abc9999-0000-4000-8000-000000000002")]


class StateDocumentTest(DeckCase):
    def test_document_shape(self):
        doc = deckstate.build(self.cfg, self.board, rows=self.rows())
        self.assertEqual(sorted(doc), ["backlog", "bosun", "cards", "config", "console", "drain", "firstrun", "houses", "idle",
                                       "needs_you", "now", "providers", "queue", "readiness", "running", "scope", "segments", "spaces",
                                       "usage", "waiting"])
        by_id = {c["id"]: c for c in doc["cards"]}
        self.assertEqual(sorted(doc["needs_you"]), sorted([self.review, self.blocked, self.gate]))
        self.assertEqual(doc["running"], [self.live])
        self.assertEqual(sorted(doc["houses"]), sorted([self.blocked, self.live]))
        self.assertEqual(doc["idle"], [self.live], "c-607: listed, out of a turn, at a live stage")
        for card in doc["cards"]:
            for key in ("derived", "last_event", "links", "house", "last_said", "children"):
                self.assertIn(key, card)
        self.assertEqual(by_id[self.live]["house"]["bg_id"], "0abc9999")
        self.assertIsNone(by_id[self.inbox]["house"])
        self.assertEqual(by_id[self.blocked]["last_said"], "I need the credentials")
        self.assertEqual(by_id[self.inbox]["last_event"]["kind"], "create")
        self.assertEqual(by_id[self.inbox]["topic"], "deck")


    def test_running_is_the_drain_pool_so_an_idle_gate_house_is_not_running(self):
        session = "0def0000-0000-4000-8000-000000000009"
        self.board.set_session(self.gate, session, "drain", bg_id=session[:8])
        idle = self.rows() + [background_row(self.gate, session)]
        doc = deckstate.build(self.cfg, self.board, rows=idle)
        self.assertEqual(doc["running"], [self.live])
        self.assertIn(self.gate, doc["houses"])
        busy = self.rows() + [dict(background_row(self.gate, session), status="busy")]
        doc = deckstate.build(self.cfg, self.board, rows=busy)
        self.assertEqual(sorted(doc["running"]), sorted([self.gate, self.live]))

    def test_a_tracking_card_is_no_house_on_the_now_strip_unless_its_session_is_busy(self):
        """Its stage is its children's, so it read `building` with a running house while its
        own session sat idle (c-277, 2026-09-20). Now is the running indicator."""
        self.board.split(self.live, [{"title": "A"}, {"title": "B"}], "house")
        session = "0abc9999-0000-4000-8000-000000000002"
        doc = deckstate.build(self.cfg, self.board, rows=self.rows())
        self.assertNotIn(self.live, doc["houses"])
        self.assertNotIn(self.live, doc["running"])
        busy = [dict(background_row(self.live, session), status="busy")]
        doc = deckstate.build(self.cfg, self.board, rows=busy)
        self.assertIn(self.live, doc["houses"])
        self.assertIn(self.live, doc["running"])

    def test_a_house_quiet_mid_turn_reads_as_idle_with_how_long_and_when_it_resumes(self):
        """The deck's half of the rate-limit fault: the card still says `building`, so
        without this it drew as a working house (c-311 to c-313, 2026-09-20). The answer is
        the drain's own (`drain.idle_stuck`), so the two cannot disagree."""
        session = "0abc9999-0000-4000-8000-000000000002"
        self.board.record_hook(self.live, "Notification", {
            "hook_event_name": "Notification", "message": "Claude is waiting for your input",
            "notification_type": "idle_prompt", "session_id": session})
        doc = deckstate.build(self.cfg, self.board, rows=self.rows())
        idle = {c["id"]: c for c in doc["cards"]}[self.live]["idle"]
        self.assertEqual((idle["tries"], idle["blocking"]), (0, False))
        self.assertGreater(idle["next_at"], idle["since"], "it says when the drain acts")
        busy = [dict(background_row(self.live, session), status="busy")]
        doc = deckstate.build(self.cfg, self.board, rows=busy)
        self.assertIsNone({c["id"]: c for c in doc["cards"]}[self.live]["idle"],
                          "a busy house is working, whatever the notification said")
        doc = deckstate.build(self.cfg, self.board, rows=self.rows())
        self.assertIsNone({c["id"]: c for c in doc["cards"]}[self.review]["idle"],
                          "a card at its outcome gate is not a quiet house")

    def test_links_are_artifact_tokens_for_files_and_urls_as_is(self):
        doc = deckstate.build(self.cfg, self.board, rows=[])
        card = {c["id"]: c for c in doc["cards"]}[self.review]
        self.assertTrue(card["links"]["plan"].startswith("/api/artifact/"))
        self.assertTrue(card["links"]["context"].startswith("/api/artifact/"))
        self.assertEqual(card["links"]["output"], "https://example.test/pr/1")
        gate = {c["id"]: c for c in doc["cards"]}[self.gate]
        self.assertEqual(gate["links"]["plan"], "https://127.0.0.1:0/s/plan")
        self.assertIsNone(gate["links"]["context"])

    def test_drain_usage_segments_and_spaces(self):
        doc = deckstate.build(self.cfg, self.board, rows=[])
        self.assertEqual(doc["drain"]["host"], "mac")
        self.assertTrue(doc["drain"]["alive"])
        self.assertLess(doc["drain"]["age_seconds"], 60)
        self.assertEqual([w["used"] for w in doc["usage"]["windows"]], [18, 66])
        # The scratch config's root is the repo, so the repo's OWN segments are a second
        # root and legitimately appear beside the scratch one. Only those with a summary
        # are listed, and a summary is gitignored runtime output, so a fresh clone lists
        # none of them and this reads as ["alpha"] there. Computed rather than written
        # out, so adding a segment does not fail a test about the state document.
        own = sorted(path.name for path in (self.cfg.root / "segments").iterdir()
                     if path.is_dir() and (path / "summary.json").exists())
        self.assertEqual([s["name"] for s in doc["segments"]], sorted(["alpha", *own]))
        alpha = {s["name"]: s for s in doc["segments"]}["alpha"]
        self.assertTrue(alpha["has_app"])
        self.assertEqual(alpha["app_url"], "/segments/alpha/app/")
        personal = doc["spaces"]["personal"]
        self.assertIsNone(personal["adapter"])
        self.assertEqual([o["key"] for o in personal["options"]],
                         ["repo", "new_project", "autonomy", "model", "plan_style"])
        self.assertEqual(personal["options"][4]["options"], ["auto", "markdown", "lavish"])
        self.assertEqual(personal["options"][0]["options"], [])
        self.assertEqual(doc["spaces"]["work"]["adapter"], "work")
        self.assertEqual(doc["providers"], {"work": {}})
        self.assertEqual(doc["config"]["houses_max"], 3)

    def test_detail_carries_events_context_and_the_pr_body(self):
        detail = deckstate.detail(self.cfg, self.board, self.review)
        self.assertEqual(detail["card"]["id"], self.review)
        self.assertEqual([e["kind"] for e in detail["events"]][:2], ["create", "stage"])
        self.assertEqual(detail["pr_body"], "The body.")
        self.assertEqual(detail["stands"], "fine")
        self.assertIn("# Plan", detail["plan_text"])

    def test_cache_holds_for_three_seconds_and_drops_on_demand(self):
        deck = deckstate.Deck(self.cfg, board_factory=lambda: Board(self.cfg.db_path))
        self.addCleanup(close_stamp, deck)
        with mock.patch.object(deckstate.harness, "agents_across", return_value=[]):
            first = deck.state()
            self.board.create("personal", "later", actor="human")
            self.assertIs(deck.state(), first)
            deck.drop()
            self.assertEqual(len(deck.state()["cards"]), len(first["cards"]) + 1)


class DrainPillTest(unittest.TestCase):
    def test_parses_age_and_liveness(self):
        at = datetime.fromisoformat("2026-09-16T20:36:07+05:30")
        line = "2026-09-16T20:35:47+05:30 drain: houses=1 resumed=1 blocked=0 started=0 paused=True"
        pill = deckstate.parse_drain_line(line, at=at, host="mac")
        self.assertEqual((pill["host"], pill["age_seconds"], pill["alive"]), ("mac", 20, True))
        self.assertEqual(pill["at"], "2026-09-16T20:35:47+05:30")
        stale = deckstate.parse_drain_line(line, at=at + timedelta(hours=2), host="mac")
        self.assertFalse(stale["alive"])
        self.assertEqual(stale["age_seconds"], 7220)

    def test_host_token_and_empty_log(self):
        at = datetime.fromisoformat("2026-09-16T20:36:07+05:30")
        pill = deckstate.parse_drain_line("2026-09-16T20:36:00+05:30 drain: host=vps houses=0", at=at, host="mac")
        self.assertEqual(pill["host"], "vps")
        empty = deckstate.parse_drain_line("", at=at, host="mac")
        self.assertEqual((empty["host"], empty["at"], empty["alive"]), ("mac", None, False))


class UsageTest(unittest.TestCase):
    def test_reads_the_two_windows_with_age(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "u.json"
            path.write_text(json.dumps(USAGE))
            usage = deckstate.read_usage(path, at=1789576598 + 300)
            self.assertTrue(usage["available"])
            self.assertEqual(usage["age_seconds"], 300)
            self.assertEqual(usage["model"], "Fable 5.1")
            self.assertEqual([(w["key"], w["used"]) for w in usage["windows"]], [("five_hour", 18), ("seven_day", 66)])
            self.assertTrue(usage["windows"][0]["resets_at"].startswith("2026-09-1"))
            missing = deckstate.read_usage(Path(tmp) / "nope.json")
            self.assertEqual((missing["available"], missing["windows"]), (False, []))


class ArtifactTest(DeckCase):
    def test_token_round_trip_and_tamper(self):
        plan = self.cfg.card_dir(self.review) / "plan.md"
        token = artifacts.token(self.cfg, plan)
        self.assertEqual(artifacts.untoken(self.cfg, token), plan.resolve())
        body, sig = token.split(".")
        self.assertIsNone(artifacts.untoken(self.cfg, body + ".AAAA" + sig[4:]))
        self.assertIsNone(artifacts.untoken(self.cfg, "garbage"))
        self.assertIsNone(artifacts.untoken(self.cfg, ""))
        key = self.cfg.state_dir / "artifact.key"
        self.assertEqual(oct(key.stat().st_mode & 0o777), "0o600")

    def test_only_files_under_the_roots_and_never_credentials(self):
        outside = self.dir / "outside.md"
        outside.write_text("x")
        self.assertIsNone(artifacts.url(self.cfg, outside))
        self.assertIsNone(artifacts.untoken(self.cfg, artifacts.token(self.cfg, outside)))
        self.assertIsNone(artifacts.untoken(self.cfg, artifacts.token(self.cfg, self.cfg.token_path)))
        card_dir = self.cfg.card_dir(self.review)
        for name in (".env", "id_rsa", "cookies.txt", "site.key", "cert.pem", "x.token"):
            path = card_dir / name
            path.write_text("secret")
            self.assertIsNone(artifacts.url(self.cfg, path), name)
        (card_dir / "secrets").mkdir()
        hidden = card_dir / "secrets" / "notes.md"
        hidden.write_text("x")
        self.assertIsNone(artifacts.url(self.cfg, hidden))
        self.assertTrue(artifacts.url(self.cfg, card_dir / "plan.md").startswith("/api/artifact/"))
        self.assertEqual(artifacts.url(self.cfg, "https://x.test/a"), "https://x.test/a")
        self.assertIsNone(artifacts.url(self.cfg, card_dir / "missing.md"))

    def test_markdown_renders_headings_lists_and_code(self):
        html = artifacts.markdown_html("# Title\n\ntext with `code`\n\n- a\n- b\n\n1. one\n\n```\nraw <tag>\n```\n", "t")
        for piece in ("<h1>Title</h1>", "<code>code</code>", "<ul>", "<li>a</li>", "<ol>", "<pre><code>raw &lt;tag&gt;"):
            self.assertIn(piece, html)

    def test_plan_live_is_the_lavish_surface_when_there_is_one(self):
        plan = self.cfg.card_dir(self.review) / "plan.md"
        state = self.dir / "lavish-state.json"
        state.write_text(json.dumps({"sessions": {"k1": {"key": "k1", "file": str(plan),
                                                         "status": "open", "updated_at": "2026-09-17T09:00:00+05:30"}}}))
        self.cfg.lavish_state = state
        artifacts._surface_cache = None
        links = deckstate.links_for(self.cfg, self.board.get(self.review))
        self.assertEqual(links["plan_live"], "/session/k1")
        self.assertTrue(links["plan"].startswith("/api/artifact/"))
        self.assertIsNone(deckstate.links_for(self.cfg, self.board.get(self.gate))["plan_live"])


class ActionTest(DeckCase):
    def setUp(self):
        super().setUp()
        self.calls = []
        patch = mock.patch.object(actions.subprocess, "run", side_effect=self.fake_run)
        patch.start()
        self.addCleanup(patch.stop)
        self.stdout = '{"id": "c-009"}'

    def fake_run(self, argv, **kwargs):
        self.calls.append((argv, kwargs.get("env") or {}))
        return subprocess.CompletedProcess(argv, 0, stdout=self.stdout, stderr="")

    def act(self, **body):
        return actions.act(self.cfg, self.board, body)

    def kb(self):
        return str(self.cfg.root / "bin" / "kb")

    def test_every_kb_verb_reaches_kb_with_the_token(self):
        cases = [
            (dict(verb="create", space="work", title="t", brief="b", repo=["api", "web"], autonomy="attended",
                  topic="tp", options={"kind": "bug", "rich_story": True}),
             ["create", "--space", "work", "--title", "t", "--brief", "b", "--autonomy", "attended", "--repo", "api,web",
              "--topic", "tp", "--option", "kind=bug", "--option", "rich_story=true"]),
            (dict(verb="set", id="c-001", fields={"topic": "x", "options.archived": True}), ["set", "c-001", "topic=x", "options.archived=true"]),
            (dict(verb="stage", id="c-001", stage="building", note="back"), ["stage", "c-001", "building", "--note", "back"]),
            (dict(verb="approve", id="c-001", gate="plan"), ["approve", "c-001", "plan"]),
            (dict(verb="approve", id="c-001", gate="plan", said="go with two"),
             ["approve", "c-001", "plan", "--said=go with two"]),
            (dict(verb="note", id="c-001", text="hi"), ["note", "c-001", "hi"]),
            (dict(verb="block", id="c-001", reason="why"), ["block", "c-001", "why"]),
            (dict(verb="unblock", id="c-001"), ["unblock", "c-001"]),
            (dict(verb="split", id="c-001", slices=[{"title": "a", "brief": "x"}, {"title": "b", "after": "a"}]),
             ["split", "c-001", "--slice", "a|x", "--slice", "b||a"]),
            (dict(verb="session", id="c-001", set="u-1", bg_id="u-1"), ["session", "c-001", "--set", "u-1", "--bg-id", "u-1"]),
        ]
        for body, expected in cases:
            self.calls.clear()
            self.act(**body)
            argv, env = self.calls[0]
            self.assertEqual(argv, [self.kb(), *expected, "--json"], body["verb"])
            self.assertEqual(env["KEEL_TOKEN"], self.token)
            self.assertEqual(env["KEEL_CONFIG"], str(self.cfg.source))
            self.assertNotIn("KEEL_CARD", env)

    def test_kb_is_given_the_tap_s_budget_less_a_margin(self):
        """Round 4 finding 4: kb stops the suite itself before the deck stops waiting."""
        self.act(verb="approve", id=self.review, gate="outcome")
        env = self.calls[0][1]
        self.assertEqual(env[actions.merging.TAP_ENV], str(actions.SLOW_SECONDS - actions.TAP_MARGIN))

    def test_start_files_assigns_and_drains_the_card_while_paused(self):
        self.cfg.drain_paused = True
        self.act(verb="create", space="work", title="t", start=True)
        verbs = [argv[1:3] for argv, _ in self.calls]
        self.assertEqual(verbs[1], ["stage", "c-009"])
        self.assertEqual(self.calls[2][0][:5], [str(self.cfg.root / "bin" / "keel"), "drain", "--once", "--card", "c-009"])

    def test_refusals_are_one_line(self):
        with self.assertRaises(actions.ActionError) as caught:
            self.act(verb="nope")
        self.assertIn("no verb called", str(caught.exception))
        with self.assertRaises(actions.ActionError):
            self.act(verb="note", id="c-001")
        with self.assertRaises(actions.ActionError):
            self.act(verb="set", id="c-001", fields={})
        self.stdout = ""
        with mock.patch.object(actions.subprocess, "run", return_value=subprocess.CompletedProcess([], 1, stdout="", stderr="kb: no card c-999\n")):
            with self.assertRaises(actions.ActionError) as caught:
                self.act(verb="note", id="c-999", text="x")
        self.assertEqual(str(caught.exception), "kb: no card c-999")

    def test_stop_and_logs_on_an_ended_session_are_refused_and_record_nothing(self):
        """Stop noted "stopped from the deck" for a session that had already ended, and Logs
        answered "job not found" (c-601, e2e bug 13)."""
        fake = FakeHarness()
        stopped = []
        fake.stop = lambda bg_id, config_dir=None: stopped.append(bg_id)
        before = len(self.calls)
        with mock.patch.object(actions, "harness", fake):
            for verb in ("house.stop", "house.logs"):
                with self.assertRaises(actions.ActionError) as caught:
                    self.act(verb=verb, id=self.blocked)
                self.assertIn("has already ended", str(caught.exception))
        self.assertEqual(stopped, [])
        self.assertEqual(self.calls[before:], [], "no note that it was stopped")

    def test_a_stale_twin_is_stopped_by_his_tap_and_never_the_cards_own(self):
        """c-601 review: `tellhouse.refuse_twins` asks him to stop the stale session."""
        fake = FakeHarness()
        stale = "bbbbbbbb-0000-4000-8000-000000000002"
        fake.rows = [background_row(self.blocked, SESSION), background_row(self.blocked, stale)]
        stopped = []
        fake.stop = lambda bg_id, config_dir=None: stopped.append(bg_id)
        with mock.patch.object(actions, "harness", fake):
            with self.assertRaises(actions.ActionError):
                self.act(verb="house.stop", id=self.blocked, twin=SESSION[:8])
            with self.assertRaises(actions.ActionError):
                self.act(verb="house.stop", id=self.blocked, twin="cccccccc")
            self.assertEqual(stopped, [])
            self.assertEqual(self.act(verb="house.stop", id=self.blocked, twin=stale[:8]),
                             {"stopped": stale[:8], "twin": True})
        self.assertEqual(stopped, [stale[:8]])
        self.assertIn("stale session bbbbbbbb", " ".join(self.calls[-1][0]))

    def test_retry_refuses_while_the_house_is_still_listed_live(self):
        """c-605: Retry started a second session beside a live one and left both running.
        It refuses, before anything is reset, and stops nothing."""
        fake = FakeHarness()
        fake.rows = [background_row(self.blocked, SESSION)]
        fake.stop = mock.Mock()
        with mock.patch.object(actions, "harness", fake), \
                mock.patch.object(actions, "run_keel") as keel:
            with self.assertRaises(actions.ActionError) as caught:
                self.act(verb="house.retry", id=self.blocked)
        self.assertIn("Stop it first, or use Resume", str(caught.exception))
        keel.assert_not_called()
        fake.stop.assert_not_called()
        self.assertEqual(self.calls, [], "nothing unblocked, staged or noted")

    def test_retry_goes_ahead_when_the_listed_row_has_no_process(self):
        fake = FakeHarness()
        row = background_row(self.blocked, SESSION)
        row["pid"] = None
        fake.rows = [row]
        with mock.patch.object(actions, "harness", fake), \
                mock.patch.object(actions, "run_keel", return_value="started") as keel:
            self.act(verb="house.retry", id=self.blocked)
        keel.assert_called_once()

    def test_a_retry_whose_pass_times_out_reads_the_card(self):
        """c-601 review: `run_keel`'s timeout is `TimeoutExpired`, not an ActionError."""
        def slow(cfg, argv, timeout=None):
            raise subprocess.TimeoutExpired(argv, 30)
        with mock.patch.object(actions, "run_keel", slow), \
                mock.patch.object(actions, "harness", FakeHarness()):
            with self.assertRaises(actions.ActionError) as caught:
                self.act(verb="house.retry", id=self.blocked)
            self.assertIn("did not answer", str(caught.exception))

            def started(cfg, argv, timeout=None):
                self.board.set_session(self.blocked, "dddddddd-0000-4000-8000-000000000004", "drain",
                                       bg_id="dddddddd")
                raise subprocess.TimeoutExpired(argv, 30)
            with mock.patch.object(actions, "run_keel", started):
                self.assertIn("started", self.act(verb="house.retry", id=self.blocked)["drain"])

    def test_house_stop_logs_and_dropin(self):
        fake = FakeHarness()
        fake.rows = [background_row(self.blocked, SESSION)]
        stopped = []
        fake.stop = lambda bg_id, config_dir=None: stopped.append((bg_id, str(config_dir)))
        fake.logs_text = "line one\nline two\n"
        with mock.patch.object(actions, "harness", fake):
            self.assertEqual(self.act(verb="house.stop", id=self.blocked), {"stopped": SESSION[:8]})
            self.assertEqual(stopped, [(SESSION[:8], str(self.cfg.spaces["work"].config_dir))])
            self.assertEqual(self.calls[-1][0][1:3], ["note", self.blocked])
            self.assertIn("human-stop", self.calls[-1][0], "his Stop is marked (c-605)")
            self.assertEqual(self.act(verb="house.logs", id=self.blocked)["logs"], "line one\nline two")
            with self.assertRaises(actions.ActionError):
                self.act(verb="house.logs", id=self.inbox)
        result = self.act(verb="dropin", id=self.inbox)
        self.assertEqual(result["cwd"], str(self.cfg.card_dir(self.inbox)))
        self.assertTrue(result["command"].startswith("cd " + str(self.cfg.card_dir(self.inbox)) + " && CLAUDE_CONFIG_DIR="))
        self.assertTrue(result["command"].endswith("claude"))
        self.assertEqual(self.calls[-1][0][1:3], ["note", self.inbox])

    def close_idle_harness(self, status: str) -> tuple[FakeHarness, list]:
        fake = FakeHarness()
        self.board.set_session(self.review, REVIEW_SESSION, "drain", bg_id=REVIEW_SESSION[:8])
        fake.rows = [background_row(self.review, REVIEW_SESSION, status=status)]
        stopped = []
        fake.stop = lambda bg_id, config_dir=None: stopped.append(bg_id)
        return fake, stopped

    def test_close_idle_house_closes_an_idle_house_with_its_own_mark(self):
        """c-607: a human stop, but marked `closed-idle`, never c-605's `human-stop`."""
        fake, stopped = self.close_idle_harness("idle")
        with mock.patch.object(idleclose, "harness", fake):
            result = self.act(verb="house.close_idle", id=self.review)
        self.assertEqual(stopped, [REVIEW_SESSION[:8]])
        self.assertEqual(result["note"], "closed while idle: your answer at the gate or your Resume brings it "
                                         "back (about 5 to 15 s)")
        argv = self.calls[-1][0]
        self.assertEqual(argv[1:3], ["note", self.review])
        self.assertEqual(argv[-3:-1], ["--mark", "closed-idle"])
        self.assertNotIn("human-stop", argv)

    def test_close_idle_house_refuses_a_working_house_and_stops_nothing(self):
        fake, stopped = self.close_idle_harness("busy")
        with mock.patch.object(idleclose, "harness", fake):
            with self.assertRaises(actions.ActionError) as caught:
                self.act(verb="house.close_idle", id=self.review)
        self.assertIn("the house is working", str(caught.exception))
        self.assertEqual((stopped, self.calls), ([], []))

    def test_close_idle_house_refuses_a_house_the_harness_does_not_list(self):
        fake, stopped = self.close_idle_harness("idle")
        fake.rows = []
        with mock.patch.object(idleclose, "harness", fake):
            with self.assertRaises(actions.ActionError) as caught:
                self.act(verb="house.close_idle", id=self.review)
        self.assertIn("lists no live session", str(caught.exception))
        self.assertEqual(stopped, [])

    def test_close_all_idle_closes_each_it_may_and_names_the_rest(self):
        fake, stopped = self.close_idle_harness("idle")
        with mock.patch.object(idleclose, "harness", fake):
            result = self.act(verb="house.close_idle", ids=[self.review, self.inbox])
        self.assertEqual(stopped, [REVIEW_SESSION[:8]])
        self.assertEqual([one["id"] for one in result["closed"]], [self.review])
        self.assertEqual(list(result["refused"]), [self.inbox])
        self.assertIn("closed 1 idle house; ", result["note"])

    def test_close_idle_house_is_only_offered_at_review_and_shipping(self):
        """c-607 review: at building nothing brings a closed house back by itself."""
        fake, stopped = self.close_idle_harness("idle")
        fake.rows.append(background_row(self.live, "0abc9999-0000-4000-8000-000000000002"))
        with mock.patch.object(idleclose, "harness", fake):
            with self.assertRaises(actions.ActionError) as caught:
                self.act(verb="house.close_idle", id=self.live)
            result = self.act(verb="house.close_idle", ids=[self.live])
        self.assertIn("is at building", str(caught.exception))
        self.assertEqual((stopped, result["closed"]), ([], []))

    def test_close_idle_house_refuses_while_a_message_is_being_sent_to_it(self):
        """c-607 review: a tell's send takes 7 to 17 s and records its turn only after."""
        fake, stopped = self.close_idle_harness("idle")
        tellhouse.mark_telling(self.cfg, self.review)
        with mock.patch.object(idleclose, "harness", fake):
            with self.assertRaises(actions.ActionError) as caught:
                self.act(verb="house.close_idle", id=self.review)
        self.assertIn("a message is being sent to it", str(caught.exception))
        self.assertEqual(stopped, [])
        tellhouse.done_telling(self.cfg, self.review)
        with mock.patch.object(idleclose, "harness", fake):
            self.act(verb="house.close_idle", id=self.review)
        self.assertEqual(stopped, [REVIEW_SESSION[:8]])

    def test_house_resume_and_retry(self):
        with mock.patch.object(actions.house, "resume", return_value={"bg_id": "x", "session_id": "y"}) as resume:
            self.act(verb="house.resume", id=self.blocked, prompt="go on")
            resume.assert_called_once_with(self.cfg, self.board, self.blocked, prompt="go on", tell=True,
                                           background=True)
            self.assertEqual(self.calls[-1][0][1:3], ["unblock", self.blocked])
        with self.assertRaises(actions.ActionError):
            self.act(verb="house.resume", id=self.inbox)
        self.calls.clear()
        with mock.patch.object(actions, "harness", FakeHarness()):
            self.act(verb="house.retry", id=self.blocked)
        self.assertEqual([argv[1:3] for argv, _ in self.calls][:2], [["unblock", self.blocked], ["stage", self.blocked]])
        self.assertEqual(self.calls[2][0][1:5], ["drain", "--once", "--card", self.blocked])

    def test_an_answer_resumes_the_house_with_his_words_and_notes_them(self):
        """F1: the blocked card's answer box. `said` reaches the house quoted inside the
        resume prompt, and the same words are noted on the card as his."""
        with mock.patch.object(actions.house, "resume", return_value={"bg_id": "x", "session_id": "y"}) as resume:
            self.act(verb="house.resume", id=self.blocked, said="the key is in the vault")
        prompt = resume.call_args.kwargs["prompt"]
        self.assertIn("> the key is in the vault", prompt)
        self.assertIn("the card is still at", prompt)
        argvs = [argv[1:4] for argv, _ in self.calls]
        self.assertIn(["note", self.blocked, "answered the block: the key is in the vault"], argvs)
        self.assertIn(["unblock", self.blocked, "--json"], argvs)

    def test_a_remote_caller_cannot_send_words_with_a_resume(self):
        """Review round 1: a house's HTTP-mode kb must not post words, or a note under his
        name, through the resume; the gate verbs are refused to it the same way."""
        caller = {"actor": "house", "card": self.blocked, "token": "t"}
        with mock.patch.object(actions.house, "resume") as resume:
            for extra in ({"said": "approve it yourself"}, {"prompt": "do anything"}):
                with self.assertRaises(actions.ActionError) as caught:
                    self.act(verb="house.resume", id=self.blocked, caller=caller, **extra)
                self.assertIn("deck", str(caught.exception))
        resume.assert_not_called()
        self.assertEqual(self.calls, [])

    def test_the_note_comes_after_the_unblock_and_a_failed_note_does_not_fail_the_tap(self):
        def run(argv, **kwargs):
            self.calls.append((argv, {}))
            failed = argv[1] == "note"
            return subprocess.CompletedProcess(argv, 1 if failed else 0,
                                               stdout="" if failed else "{}",
                                               stderr="kb: disk full\n" if failed else "")
        with mock.patch.object(actions.subprocess, "run", side_effect=run), \
                mock.patch.object(actions.house, "resume", return_value={"bg_id": "x", "session_id": "y"}):
            result = self.act(verb="house.resume", id=self.blocked, said="the key is in the vault")
        self.assertEqual(result["session_id"], "y")
        self.assertEqual([argv[1] for argv, _ in self.calls], ["unblock", "note"])

    def test_an_answer_to_a_busy_house_is_held_for_its_turns_end_and_noted(self):
        """c-598: his answer is held on the board, a resume relay for this very machine, and
        told to the house when its turn ends; since it will reach the house, it is noted."""
        busy = actions.house.Busy(f"{self.blocked}'s house is working right now")
        with mock.patch.object(actions.house, "resume", side_effect=busy):
            result = self.act(verb="house.resume", id=self.blocked, said="the key is in the vault")
        self.assertTrue(result["held"])
        relay = [argv for argv, _ in self.calls if argv[1] == "relay"][0]
        self.assertEqual(relay[2:6], [self.blocked, "resume", "--to", self.cfg.host])
        self.assertIn("> the key is in the vault", relay[relay.index("--prompt") + 1])
        self.assertIn("note", [argv[1] for argv, _ in self.calls])

    def test_an_answer_his_terminal_refuses_is_not_noted(self):
        """Nothing reached the house, so the card must not say he answered it; the page
        keeps what he typed for the next try."""
        busy = actions.house.InTerminal(f"{self.blocked}'s conversation is open in a terminal")
        with mock.patch.object(actions.house, "resume", side_effect=busy):
            with self.assertRaises(actions.ActionError):
                self.act(verb="house.resume", id=self.blocked, said="the key is in the vault")
        self.assertNotIn("note", [argv[1] for argv, _ in self.calls])

    def test_a_resume_of_a_house_in_his_terminal_is_a_one_line_refusal_and_does_not_unblock(self):
        """E1 and U3: the deck shows the reason; nothing was resumed, so nothing is unblocked.
        A house that is merely WORKING is held instead (c-598, above)."""
        busy = actions.house.InTerminal(f"{self.blocked}'s conversation is open in a terminal")
        with mock.patch.object(actions.house, "resume", side_effect=busy):
            with self.assertRaises(actions.ActionError) as caught:
                self.act(verb="house.resume", id=self.blocked)
        self.assertIn("open in a terminal", str(caught.exception))
        self.assertNotIn(["unblock", self.blocked], [argv[1:3] for argv, _ in self.calls])

    def test_a_gate_answer_to_a_busy_house_stands_and_is_held_for_its_turns_end(self):
        """The kb move already landed, so a busy house is never a failure for a move that
        happened; since c-598 his answer is held (a relay for this machine), not dropped."""
        busy = actions.house.Busy(f"{self.blocked}'s house is working right now")
        with mock.patch.object(actions.house, "resume", side_effect=busy):
            answer = actions.gate_answer(self.cfg, self.board, self.blocked, "carry on")
        self.assertIsNone(answer["resumed"])
        self.assertIn("when its turn ends", answer["note"])
        relay = [argv for argv, _ in self.calls if argv[1] == "relay"][0]
        self.assertEqual(relay[2:10], [self.blocked, "resume", "--to", self.cfg.host, "--held", "--gate",
                                       "--prompt", "carry on"])

    def test_his_stop_wins_over_a_voice_hold_and_leaves_the_house_down(self):
        """Stop is the one place a human ends a session on purpose, so a hold is not a
        reason to refuse him. The hold goes with the same tap and nothing is woken."""
        self.board.hold_voice(self.blocked, 300, stopped=True)
        fake = FakeHarness()
        stopped = []
        closed = []
        fake.stop = lambda bg_id, config_dir=None: stopped.append(bg_id)
        with mock.patch.object(actions, "harness", fake), \
                mock.patch.object(actions.housetier, "close_session",
                                  lambda cfg, card, wake=False: closed.append(card["id"])
                                  or actions.housetier.Shut(actions.housetier.CLOSED)):
            result = self.act(verb="house.stop", id=self.blocked)
        # V12: THE CONVERSATION GOES WITH THE HOLD. It is a `claude` holding that session,
        # and leaving it open would occupy a session nobody is talking to any more.
        self.assertEqual(closed, [self.blocked])
        self.assertEqual(result, {"stopped": SESSION[:8], "released": True})
        self.assertEqual(stopped, [SESSION[:8]])
        self.assertIsNone(self.board.voice_hold_of(self.blocked))
        self.assertEqual(getattr(fake, "wakes", []), [], "his stop leaves the house down")
        self.assertIn("while voice was talking to it", " ".join(self.calls[-1][0]))

    def held_close(self, closed: list):
        """`housetier.close_session`, recording the card and whether a wake was asked for."""
        return mock.patch.object(
            actions.housetier, "close_session",
            lambda cfg, card, wake=False: closed.append((card["id"], wake))
            or actions.housetier.Shut(actions.housetier.CLOSED))

    def test_his_resume_ends_the_conversation_first_and_then_resumes(self):
        """The same hole `house.stop` had. A resume is REFUSED while a headless process
        still holds that session, so a Resume tapped mid-conversation would fail for a
        reason nothing on the page could explain. His tap wins over the hold, exactly as
        Stop does, and the conversation goes with it."""
        self.board.hold_voice(self.blocked, 300, stopped=True)
        order, closed = [], []
        with self.held_close(closed), \
                mock.patch.object(actions.house, "resume",
                                  side_effect=lambda *a, **k: order.append("resume")
                                  or {"bg_id": "x", "session_id": "y"}):
            self.act(verb="house.resume", id=self.blocked, prompt="go on")
        self.assertEqual(closed, [(self.blocked, False)],
                         "the live conversation was left holding the session")
        self.assertEqual(order, ["resume"])
        self.assertIsNone(self.board.voice_hold_of(self.blocked),
                          "the hold was left on a house he has just resumed himself")

    def test_a_resume_with_no_conversation_touches_nothing(self):
        """Which is every ordinary Resume: there is no hold, so there is nothing to end and
        no server to ask."""
        closed = []
        with self.held_close(closed), \
                mock.patch.object(actions.house, "resume",
                                  return_value={"bg_id": "x", "session_id": "y"}):
            self.act(verb="house.resume", id=self.blocked)
        self.assertEqual(closed, [])

    def test_house_converse_is_one_turn_and_gives_back_what_was_said(self):
        """The deck's own turn into a card's house, the same `keel converse` the gateway and
        the phone Harbor run. Its button opens voice pinned instead, which is a link."""
        answer = {"ok": True, "say": "It is at review.", "card": self.blocked, "seconds": 6.2}
        with mock.patch.object(actions.converse, "answer", return_value=answer) as spoke:
            result = self.act(verb="house.converse", id=self.blocked, text="where are you")
        self.assertEqual(result["say"], "It is at review.")
        self.assertEqual(spoke.call_args[0][2:4], (self.blocked, "where are you"))
        with self.assertRaises(actions.ActionError):
            self.act(verb="house.converse", id=self.blocked, text="   ")

    def test_a_refused_turn_is_the_one_line_the_page_shows(self):
        refused = {"ok": False, "say": "c-1 is building right now.", "card": self.blocked}
        with mock.patch.object(actions.converse, "answer", return_value=refused):
            with self.assertRaises(actions.ActionError) as caught:
                self.act(verb="house.converse", id=self.blocked, text="hello")
        self.assertIn("building right now", str(caught.exception))

    def test_adapter_verbs_need_an_adapter_with_act(self):
        with self.assertRaises(actions.ActionError) as caught:
            self.act(verb="adapter", space="personal", route="reviews", action="hold", key="k")
        # c-631: refused with the sentence the Reviews panel shows
        self.assertEqual(str(caught.exception), "no connection is turned on for personal")
        with self.assertRaises(actions.ActionError) as caught:
            self.act(verb="adapter", space="work", route="reviews", action="hold", key="k")
        self.assertIn("act", str(caught.exception))


def close_stamp(deck) -> None:
    """Close the board-stamp connection a deck made outside a server keeps open; the
    server does this itself on `server_close` (`serve.DeckServer`)."""
    if deck.stamp_conn is not None:
        deck.stamp_conn.close()
        deck.stamp_conn = None


def held_clock(step: int = 100):
    """`Deck.rev`'s coarse clock held at one step, so a test about the board is not a coin
    toss about the wall clock.

    The third term is `int(time.time() // REV_SECONDS)`, and a test that reads the revision
    twice a few seconds apart on a loaded box crosses a fifteen second boundary between the
    two reads about one run in five (r-22). A test about the clock moving patches it itself.
    """
    return mock.patch.object(deckstate, "clock_step", side_effect=lambda: step)


class ServerCase(DeckCase):
    """The deck served on a free port, with a client for it. `lavish_port` is 1, so every
    proxied route fails to connect unless the test points it somewhere real."""

    def setUp(self):
        super().setUp()
        self.cfg.lavish_port = 1
        self.server = serve.make_server(self.cfg, port=0)
        self.thread = serve_in_background(self.server)
        self.base = f"http://127.0.0.1:{self.server.server_address[1]}"

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        super().tearDown()

    def page_headers(self) -> dict:
        """What the deck's own page sends with a POST that acts as him (c-451): the cookie
        the shell's GET set, and a browser's own word that it is this origin."""
        with urllib.request.urlopen(self.base + "/", timeout=10) as response:
            response.read()
            cookie = (response.headers.get("Set-Cookie") or "").split(";", 1)[0]
        return {"Cookie": cookie, "Origin": self.base, "Sec-Fetch-Site": "same-origin"}

    def fetch(self, path, data=None, method=None, page=False):
        request = urllib.request.Request(self.base + path, data=data, method=method)
        if data is not None:
            request.add_header("Content-Type", "application/json")
        for name, value in (self.page_headers() if page else {}).items():
            request.add_header(name, value)
        try:
            with urllib.request.urlopen(request, timeout=10) as response:
                return response.status, response.headers.get("Content-Type", ""), response.read()
        except urllib.error.HTTPError as error:
            with error:
                return error.code, error.headers.get("Content-Type", ""), error.read()

    def get_json(self, path):
        status, _, body = self.fetch(path)
        self.assertEqual(status, 200, body)
        return json.loads(body)


class AppFilesTest(unittest.TestCase):
    """Every file the page asks for must be one the server will hand over: a script or a
    stylesheet that index.html references but APP_FILES does not name is a blank deck. The
    deck's page is read as the server sends it, filled from app/views.json (c-634)."""

    def references(self) -> set[str]:
        app = Path(serve.__file__).resolve().parent.parent / "app"
        html = (deckviews.rendered(app, "index.html") + (app / serve.PLAN_SHELL).read_text()
                + (app / serve.CONSOLE_SHELL).read_text())
        found = set(re.findall(r'(?:src|href)="([^"]+)"', html))
        return {ref for ref in found if not ref.startswith(("http:", "https:", "data:", "#"))}

    def test_index_references_only_files_the_server_serves(self):
        served = set(serve.APP_FILES)
        for ref in self.references():
            self.assertIn("/" + ref.lstrip("/"), served, f"{ref} is referenced but not in APP_FILES")

    def test_every_served_file_exists(self):
        app_dir = Path(serve.__file__).resolve().parent.parent / "app"
        for name in set(serve.APP_FILES.values()):
            self.assertTrue((app_dir / name).is_file(), name)

    def test_every_manifest_script_is_served_loaded_and_cached(self):
        """The six lists that used to drift are one (c-634): each script the manifest names
        is in APP_FILES, loaded by the page in its order, and in the worker's shell."""
        app = Path(serve.__file__).resolve().parent.parent / "app"
        manifest = deckviews.load(app)
        self.assertEqual(deckviews.check(manifest, app), [])
        html, worker = deckviews.rendered(app, "index.html"), deckviews.rendered(app, "sw.js")
        self.assertEqual(re.findall(r'<script src="/([^"]+)"></script>', html), manifest["scripts"])
        for name in manifest["scripts"]:
            self.assertEqual(serve.APP_FILES.get("/" + name), name, name)
            self.assertIn(f'"/{name}"', worker, f"{name} is not in the service worker's shell")
        for view in manifest["views"]:
            self.assertIn(view["script"], manifest["scripts"], view["key"])


class HttpTest(ServerCase):
    def setUp(self):
        super().setUp()
        with mock.patch.object(deckstate.harness, "agents_across", return_value=self.rows()):
            self.state = self.get_json("/api/state")

    def test_the_console_attach_line_is_this_installs_own(self):
        """c-634: the Console's attach command comes from the state, this install's own
        `bin/keel`, and nothing in the state names a machine to ssh into."""
        bosun = self.state["console"] or self.state["bosun"]
        self.assertEqual(bosun["attach"], f"{self.cfg.install_home or self.cfg.root}/bin/keel console attach")
        self.assertNotIn("keel-box", json.dumps(self.state))

    def test_the_page_and_the_worker_are_filled_from_the_manifest(self):
        """`/` carries the manifest inline and one tag per script in its order; `/sw.js`
        carries every script and the manifest's hash in its cache name, under an ETag that
        a matching If-None-Match answers with a 304 (c-634)."""
        manifest = deckviews.load(self.server.RequestHandlerClass.app_dir)
        status, ctype, body = self.fetch("/")
        page = body.decode()
        self.assertEqual((status, ctype), (200, "text/html; charset=utf-8"))
        self.assertEqual(re.findall(r'<script src="/([^"]+)"></script>', page), manifest["scripts"])
        inline = re.search(r"window\.KEEL_VIEWS = (.*?);</script>", page).group(1)
        self.assertEqual(json.loads(inline), manifest)
        self.assertNotIn(deckviews.INDEX_MARK, page)
        with urllib.request.urlopen(self.base + "/sw.js", timeout=10) as response:
            worker, tag = response.read().decode(), response.headers["ETag"]
            self.assertEqual(response.headers["Cache-Control"], serve.REVALIDATE)
        self.assertIn(f"var DECK = ", worker)
        self.assertIn(f'"hash": "{deckviews.digest(manifest)}"', worker)
        for name in manifest["scripts"]:
            self.assertIn(f'"/{name}"', worker)
        again = urllib.request.Request(self.base + "/sw.js", headers={"If-None-Match": tag})
        with self.assertRaises(urllib.error.HTTPError) as said:
            urllib.request.urlopen(again, timeout=10)
        with said.exception:
            self.assertEqual(said.exception.code, 304)

    def test_state_page_card_and_artifact(self):
        self.assertEqual(sorted(self.state["needs_you"]), sorted([self.review, self.blocked, self.gate]))
        status, ctype, body = self.fetch("/")
        self.assertEqual((status, "text/html" in ctype), (200, True))
        self.assertIn(b"ui.js", body)
        for path in serve.APP_FILES:
            self.assertEqual(self.fetch(path)[0], 200, path)
        detail = self.get_json("/api/card/" + self.review)
        self.assertEqual(detail["pr_body"], "The body.")
        self.assertEqual(self.fetch("/api/card/c-999")[0], 404)
        link = {c["id"]: c for c in self.state["cards"]}[self.review]["links"]["plan"]
        status, ctype, body = self.fetch(link)
        self.assertEqual((status, ctype), (200, "text/html; charset=utf-8"))
        self.assertIn(b"<h1>Plan</h1>", body)
        status, ctype, body = self.fetch(link + "?raw=1")
        self.assertEqual((status, ctype), (200, "text/plain; charset=utf-8"))
        self.assertTrue(body.startswith(b"# Plan"))
        self.assertEqual(self.fetch("/api/artifact/not.a.token")[0], 404)

    def test_health_has_a_route_of_its_own_that_is_never_a_304(self):
        """F4: the verdict does not move the state's revision (A-8), so a page holding a
        current state is answered 304 and would never see a new verdict through it."""
        found = {"level": "red", "reasons": ["talker: stopped"], "services": []}
        with mock.patch.object(serve.health, "current", return_value=found):
            status, ctype, body = self.fetch("/api/health")
        self.assertEqual((status, "application/json" in ctype), (200, True))
        self.assertEqual(json.loads(body), {**found, "serve_head": serve.STARTED_HEAD},
                         "and the code this deck runs, which a deploy waits on (c-637)")

    def test_segment_app_and_traversal(self):
        status, ctype, body = self.fetch("/segments/alpha/app/")
        self.assertEqual((status, body.strip().endswith(b"alpha app")), (200, True))
        self.assertEqual(self.fetch("/segments/alpha/app/index.html")[0], 200)
        self.assertEqual(self.fetch("/segments/alpha/app/../summary.json")[0], 404)
        self.assertEqual(self.fetch("/segments/alpha/app/../../../board.db")[0], 404)
        self.assertEqual(self.fetch("/segments/beta/app/")[0], 404)

    def test_the_repos_own_segments_dir_is_served_ahead_of_segments_dir(self):
        """The deck serves `<root>/segments/<name>` first and falls back to `segments_dir`.
        The shipped config makes those one tree (tests/test_config.py); they differ again
        under a `KEEL_HOME` aimed at a worktree, which is the case exercised here."""
        root = self.dir / "root"
        for base, text in ((root / "segments", "from the repo"), (self.cfg.segments_dir, "from the old tree")):
            (base / "gamma" / "app").mkdir(parents=True)
            (base / "gamma" / "app" / "index.html").write_text(text)
            (base / "gamma" / "summary.json").write_text(json.dumps({"tiles": [{"label": text, "value": 1}]}))
        (self.cfg.segments_dir / "delta" / "app").mkdir(parents=True)
        (self.cfg.segments_dir / "delta" / "app" / "index.html").write_text("delta app")
        self.addCleanup(setattr, self.cfg, "root", self.cfg.root)
        self.cfg.root = root
        self.assertEqual(self.cfg.segment_roots, [(root / "segments").resolve(), self.cfg.segments_dir.resolve()])
        self.assertEqual(self.fetch("/segments/gamma/app/")[2], b"from the repo")
        self.assertEqual(self.fetch("/segments/delta/app/")[2], b"delta app")
        self.assertEqual(self.fetch("/segments/epsilon/app/")[0], 404)
        names = {s["name"]: s for s in deckstate.segments(self.cfg)}
        self.assertEqual(sorted(names), ["alpha", "gamma"])
        self.assertEqual(names["gamma"]["summary"]["tiles"][0]["label"], "from the repo")
        self.cfg.root = self.cfg.segments_dir.parent
        self.assertEqual(len(self.cfg.segment_roots), 1, "the same tree twice is one root")

    def test_actions_and_the_proxy(self):
        status, _, body = self.fetch("/api/action", data=b"{not json")
        self.assertEqual(status, 400)
        status, _, body = self.fetch("/api/action", data=json.dumps({"verb": "nope"}).encode(), page=True)
        self.assertEqual((status, json.loads(body)["error"]), (409, "no verb called 'nope'"))
        with mock.patch.object(deckstate.harness, "agents_across", return_value=self.rows()):
            status, _, body = self.fetch("/api/action", data=json.dumps({"verb": "note", "id": self.inbox, "text": "from the deck"}).encode(), page=True)
            self.assertEqual(status, 200, body)
            self.assertTrue(json.loads(body)["ok"])
            events = self.board.events(self.inbox)
            self.assertEqual((events[-1]["kind"], events[-1]["actor"], events[-1]["text"]), ("note", "human", "from the deck"))
            state = self.get_json("/api/state")
        self.assertEqual({c["id"]: c for c in state["cards"]}[self.inbox]["last_event"]["text"], "from the deck")
        status, _, body = self.fetch("/nothing/here")
        self.assertEqual(status, 503)
        self.assertIn(b"lavish port 1", body)

    def test_a_context_image_is_rendered_and_then_served(self):
        card_dir = self.cfg.card_dir(self.review)
        (card_dir / "assets").mkdir(exist_ok=True)
        shot = card_dir / "assets" / "shot.png"
        shot.write_bytes(bytes.fromhex("89504e470d0a1a0a"))
        context = card_dir / "context.md"
        context.write_text("## Evidence\n\n![the deck at 390](assets/shot.png)\n")
        status, ctype, body = self.fetch(artifacts.url(self.cfg, context))
        self.assertEqual((status, ctype), (200, "text/html; charset=utf-8"))
        page = body.decode()
        self.assertIn('alt="the deck at 390"', page)
        src = page.split('<img src="', 1)[1].split('"', 1)[0]
        status, ctype, body = self.fetch(src)
        self.assertEqual((status, ctype, body), (200, "image/png", shot.read_bytes()))

    def test_lavish_origin_moves_the_check_up_one_hop(self):
        self.assertEqual(serve.lavish_origin(4387, "mac.example.ts.net:8443", "https://mac.example.ts.net:8443", None), "http://127.0.0.1:4387")
        self.assertEqual(serve.lavish_origin(4387, "127.0.0.1:8791", None, "http://127.0.0.1:8791/?view=now"), "http://127.0.0.1:4387")
        self.assertEqual(serve.lavish_origin(4387, "127.0.0.1:8791", "https://evil.test", None), "")
        self.assertEqual(serve.lavish_origin(4387, None, "http://127.0.0.1:8791", None), "")


class BoardRouteTest(ServerCase):
    """The deck's half of the blackboard: the live channel, the three page routes, and the
    board a card's own pane carries. `keel/boards.py` is tested in tests/test_boards.py;
    what is here is what the DOOR does with it."""

    def setUp(self):
        super().setUp()
        from keel import boards
        self.boards = boards
        boards.push(self.cfg, 'board "How Keel is laid out"\n'
                              'node mac laptop "The Mac"\n'
                              'step mac "he stops talking"',
                    card=self.live)

    def test_the_board_api_answers_the_record_and_its_lines(self):
        doc = self.get_json("/api/board/b-001")
        self.assertEqual(doc["title"], "How Keel is laid out")
        self.assertEqual((doc["nodes"], doc["attachments"]), (1, 1))
        self.assertIn('node mac laptop "The Mac"', doc["lines"])
        self.assertEqual(doc["next"], len(doc["lines"]))

    def test_since_asks_only_for_what_arrived_after_it(self):
        first = self.get_json("/api/board/b-001")
        self.boards.push(self.cfg, 'note board "one more"', card=self.live)
        more = self.get_json("/api/board/b-001?since=%d" % first["next"])
        self.assertEqual([line for line in more["lines"] if not line.startswith("#")],
                         ['note board "one more"'])

    def test_a_cursor_that_is_not_a_number_reads_as_the_whole_board(self):
        self.assertEqual(self.get_json("/api/board/b-001?since=soon")["since"], 0)

    def test_an_unknown_board_is_a_404_and_not_the_lavish_proxy(self):
        status, _, body = self.fetch("/api/board/b-404")
        self.assertEqual(status, 404)
        self.assertIn(b"no board", body)

    def test_every_board_page_route_serves_the_page(self):
        """The frames era's `/board/<id>/<n>` still opens its board: the number is matched
        and dropped, so a link he sent himself in September is not a 404."""
        for path in ("/board", "/board/b-001", "/board/b-001?view=outline", "/board/b-001/2"):
            status, ctype, body = self.fetch(path)
            self.assertEqual((status, "text/html" in ctype), (200, True), path)
            self.assertIn(b"/ui.board.js", body, path)

    def test_the_page_asks_for_every_asset_by_an_absolute_path(self):
        """`/board/b-001/2` is a real path, so a relative `src="ui.core.js"` there would be
        fetched from `/board/b-001/ui.core.js` and the deck would come up blank."""
        html = deckviews.rendered(Path(serve.__file__).resolve().parent.parent / "app", "index.html")
        for ref in re.findall(r'(?:src|href)="([^"]+)"', html):
            if ref.startswith(("http:", "https:", "data:", "#")):
                continue
            self.assertTrue(ref.startswith("/"), f"{ref} is relative, and the board route has a path")

    def test_a_board_path_that_is_not_one_is_not_this_routes(self):
        """The prefix is not claimed whole: only the three shapes are the deck's, so
        anything else under it falls through to the proxy (which is down here)."""
        self.assertEqual(self.fetch("/board/nope")[0], 503)
        self.assertEqual(self.fetch("/board/b-001/2/3")[0], 503)

    def test_a_cards_own_pane_carries_its_newest_board_and_the_count(self):
        detail = self.get_json("/api/card/" + self.live)
        self.assertEqual(detail["board"]["id"], "b-001")
        self.assertEqual(detail["board"]["count"], 1)
        self.assertEqual(detail["board"]["nodes"], 1)
        self.assertEqual([row["id"] for row in detail["board"]["boards"]], ["b-001"])

    def test_a_cards_pane_carries_every_board_that_card_has(self):
        """A card has as many boards as it has pictures: a user flow and a database schema
        are one story and two pictures, and the pane lists both."""
        self.boards.push(self.cfg, 'board "The database schema"\nnode t box "cards"',
                         card=self.live)
        detail = self.get_json("/api/card/" + self.live)
        self.assertEqual(detail["board"]["count"], 2)
        self.assertEqual([row["title"] for row in detail["board"]["boards"]],
                         ["The database schema", "How Keel is laid out"])
        self.assertEqual([row["live"] for row in detail["board"]["boards"]], [True, False])
        self.assertIsNone(self.get_json("/api/card/" + self.review)["board"])

    def test_a_push_through_the_action_endpoint_lands_on_the_card_s_board(self):
        body = json.dumps({"verb": "board.push", "card": self.live,
                           "ops": 'note board "from the deck"'}).encode()
        status, _, raw = self.fetch("/api/action", data=body, page=True)
        self.assertEqual(status, 200, raw)
        result = json.loads(raw)["result"]
        self.assertEqual(result["board"], "b-001")
        self.assertTrue(result["url"].endswith("/board/b-001"), result["url"])


class BacklogStateTest(DeckCase):
    """A card that has sat at its outcome gate since July is out of Attention and Now,
    listed on its own, and counted per space so the deck can offer a chip with a number."""

    def backlogged(self, topic: str = "triage") -> str:
        old = (datetime.now().astimezone() - timedelta(days=40)).isoformat(timespec="seconds")
        with mock.patch("keel.board.now", return_value=old):
            card_id = self.board.create("work", "sat since July", repo="api", actor="human", topic=topic)
            self.board.stage(card_id, "assigned", "human")
            self.board.stage(card_id, "building", "drain")
            self.board.stage(card_id, "review", "house", plan_ref="p.md", output_ref="https://x.test/1")
        return card_id

    def test_a_backlog_card_is_listed_apart_and_left_out_of_attention_and_now(self):
        old = self.backlogged()
        doc = deckstate.build(self.cfg, self.board, rows=self.rows())
        by_id = {c["id"]: c for c in doc["cards"]}
        self.assertTrue(by_id[old]["derived"]["backlog"])
        self.assertIsNone(by_id[old]["derived"]["backlog_override"])
        self.assertFalse(by_id[self.review]["derived"]["backlog"])
        self.assertEqual(doc["backlog"], [old])
        self.assertNotIn(old, doc["needs_you"])
        self.assertNotIn(old, doc["houses"])
        self.assertNotIn(old, doc["running"])
        self.assertIn(self.review, doc["needs_you"])
        self.assertEqual(doc["config"]["backlog_days"], 7)

    def test_the_manual_override_rides_on_the_card(self):
        old = self.backlogged()
        self.board.set_backlog(old, "active", "human")
        doc = deckstate.build(self.cfg, self.board, rows=[])
        card = {c["id"]: c for c in doc["cards"]}[old]
        self.assertFalse(card["derived"]["backlog"])
        self.assertEqual(card["derived"]["backlog_override"], "active")
        self.assertEqual(doc["backlog"], [])
        self.assertIn(old, doc["needs_you"])

    def test_each_space_carries_its_counts_and_its_topics(self):
        self.backlogged()
        doc = deckstate.build(self.cfg, self.board, rows=[])
        work, personal = doc["spaces"]["work"], doc["spaces"]["personal"]
        self.assertEqual(work["counts"], {"cards": 4, "needs_you": 3, "backlog": 1})
        self.assertEqual(work["topics"], ["triage"])
        self.assertEqual(personal["counts"], {"cards": 2, "needs_you": 0, "backlog": 0})
        self.assertEqual(personal["topics"], ["deck"])
def free_port() -> int:
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        return probe.getsockname()[1]


class LavishReviveTest(ServerCase):
    """The proxy starts lavish when a person asks for a surface and nothing answers.

    The stand-in for `lavish-axi server` is a stdlib file server over a directory holding
    `health` (what `lavish_up` probes) and `session/k` (what the person asked for), which is
    all this behaviour touches: a connection refused, then a real answer on the retry.
    """

    def setUp(self):
        super().setUp()
        self.port = free_port()
        self.cfg.lavish_port = self.port
        docroot = self.dir / "lavish"
        (docroot / "session").mkdir(parents=True)
        (docroot / "health").write_text("ok")
        (docroot / "session" / "k").write_text("the surface")
        self.bin = self.dir / "bin"
        self.bin.mkdir()
        fake = self.bin / "lavish-axi"
        fake.write_text('#!/bin/sh\nexec python3 -m http.server "$LAVISH_AXI_PORT" '
                        f'--bind 127.0.0.1 --directory "{docroot}"\n')
        fake.chmod(0o755)
        self.path_before = os.environ["PATH"]
        os.environ["PATH"] = str(self.bin) + os.pathsep + self.path_before
        serve._revive_last = 0.0
        serve._lavish_proc = None
        self.addCleanup(self.stop_lavish)

    def stop_lavish(self):
        os.environ["PATH"] = self.path_before
        proc = serve._lavish_proc
        serve._lavish_proc = None
        serve._revive_last = 0.0
        if proc is not None and proc.poll() is None:
            proc.terminate()
            try:
                proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                proc.kill()

    def test_a_surface_request_starts_lavish_and_is_retried_once(self):
        status, _, body = self.fetch("/robots.txt")            # not a person: nothing starts
        self.assertEqual(status, 503)
        self.assertIsNone(serve._lavish_proc)
        status, _, body = self.fetch("/session/k")
        self.assertEqual((status, body), (200, b"the surface"))
        self.assertIsNotNone(serve._lavish_proc)
        self.assertIsNone(serve._lavish_proc.poll(), "the lavish we started must still be running")
        self.assertTrue(serve.lavish_up(self.port))

    def test_with_no_lavish_on_the_path_the_failure_is_honest(self):
        os.environ["PATH"] = str(self.dir / "empty")
        status, _, body = self.fetch("/session/k")
        self.assertEqual(status, 503)
        self.assertIn(f"lavish port {self.port}".encode(), body)
        self.assertIsNone(serve._lavish_proc)

    def test_the_cooldown_stops_a_failed_revive_being_hammered(self):
        os.environ["PATH"] = str(self.dir / "empty")
        self.assertFalse(serve.lavish_revive(self.port))
        serve._revive_last = time.time()
        os.environ["PATH"] = str(self.bin) + os.pathsep + self.path_before
        self.assertFalse(serve.lavish_revive(self.port), "inside the cooldown, nothing is started")
        self.assertIsNone(serve._lavish_proc)

    def test_only_a_person_revives(self):
        self.assertTrue(serve.by_a_person("GET", "/session/abc"))
        self.assertTrue(serve.by_a_person("GET", "/events/abc"))
        self.assertTrue(serve.by_a_person("POST", "/api/abc/prompts"))
        for method, path in (("GET", "/sdk.js"), ("GET", "/favicon.ico"), ("GET", "/robots.txt"),
                             ("GET", "/session/abc/assets/x.png"), ("POST", "/whatever")):
            self.assertFalse(serve.by_a_person(method, path), path)


class ActionBoardSwitchesTest(ServerCase):
    """The board a POST /api/action hands its verb is opened with the `[keel]` switches
    (c-591 review): builder mode lets Bosun note any personal card, and without the switch
    it is refused. Once it was opened bare, so every switch was off over HTTP."""

    def bosun_notes(self):
        def act(cfg, board, body):
            return board.note(body["id"], body["text"], "bosun")
        with mock.patch.object(serve.actions, "act", side_effect=act):
            status, _, raw = self.fetch("/api/action", data=json.dumps(
                {"verb": "note", "id": self.inbox, "text": "from bosun"}).encode(), page=True)
        return status, raw

    def notes(self):
        return [e for e in self.board.events(self.inbox) if e["kind"] == "note" and e["actor"] == "bosun"]

    def test_builder_mode_reaches_the_board_over_http(self):
        superuser_builder(self.cfg)
        status, raw = self.bosun_notes()
        self.assertEqual(status, 200, raw)
        self.assertEqual(len(self.notes()), 1)

    def test_without_the_switch_bosun_is_refused_the_personal_card(self):
        status, raw = self.bosun_notes()
        self.assertNotEqual(status, 200, raw)
        self.assertIn(b"not a card Bosun builds", raw)
        self.assertEqual(self.notes(), [])


class HangupTest(ServerCase):
    """A client that drops a proxied stream mid-reply leaves no traceback and no 503 into
    the void (the BrokenPipe the human saw on 2026-09-17): it is counted and the next
    request is answered as usual."""

    def test_a_client_leaving_a_lavish_stream_is_counted_not_raised(self):
        import http.server
        import socket

        class Slow(http.server.BaseHTTPRequestHandler):
            def do_GET(self):
                self.send_response(200); self.send_header("Content-Type", "text/event-stream"); self.end_headers()
                try:
                    for _ in range(50):
                        self.wfile.write(b"data: tick\n\n"); self.wfile.flush(); time.sleep(0.05)
                except (BrokenPipeError, ConnectionResetError):
                    pass
            def log_message(self, *a): pass

        lavish = http.server.HTTPServer(("127.0.0.1", 0), Slow)
        serve_in_background(lavish)
        self.addCleanup(lavish.server_close)       # cleanups run last registered first
        self.addCleanup(lavish.shutdown)
        self.cfg.lavish_port = lavish.server_address[1]
        errors = []
        self.server.handle_error = lambda request, addr: errors.append(addr)
        before = serve.CLIENT_HANGUPS
        host = self.base.split("//")[1]
        client = socket.create_connection(("127.0.0.1", int(host.split(":")[1])))
        client.sendall(f"GET /events/x HTTP/1.1\r\nHost: {host}\r\nOrigin: http://{host}\r\n\r\n".encode())
        got = b""
        client.settimeout(5)
        while b"tick" not in got:
            got += client.recv(4096)
        client.close()
        for _ in range(60):
            if serve.CLIENT_HANGUPS > before:
                break
            time.sleep(0.05)
        self.assertEqual(serve.CLIENT_HANGUPS, before + 1)
        self.assertEqual(errors, [])
        self.assertEqual(self.fetch("/api/state")[0], 200)


class Quiet(http_server.BaseHTTPRequestHandler):
    """Lavish's `/events/` as it really behaves: quiet between events, for a long time.

    `/events/once` says one thing and then nothing at all, which is the abandoned channel.
    `/events/slow` says three things with a gap longer than the deck's watch tick between
    them, which is a channel with somebody still on it.
    """

    protocol_version = "HTTP/1.1"
    GAP = serve.STREAM_TICK * 1.5

    def log_message(self, *args):
        pass

    def do_GET(self):
        # `/events/chunked` frames its one event the way a node server does. A cut read on
        # a chunked answer ends in `http.client.IncompleteRead`, not in an empty read.
        chunked = self.path.endswith("/chunked")
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        if chunked:
            self.send_header("Transfer-Encoding", "chunked")
        self.end_headers()
        for index in range(3 if self.path.endswith("/slow") else 1):
            if index:
                time.sleep(self.GAP)
            event = f"data: hello {index}\n\n".encode()
            self.wfile.write(b"%x\r\n%s\r\n" % (len(event), event) if chunked else event)
            self.wfile.flush()
        select.select([self.connection], [], [], 30)   # until the deck lets this channel go
        self.close_connection = True


class StreamDescriptorTest(ServerCase):
    """An abandoned stream lets go of both its sockets rather than holding them for an hour.

    Card c-276: a client that closed its tab was noticed only on the next write, and lavish
    can be quiet on `/events/` for minutes, so the handler sat on the client's socket AND
    lavish's until the read timeout an hour away. Two descriptors a channel, and the page
    reopened one on every poll, is how `keel serve` ran out of descriptors and could no
    longer spawn `claude` at all. The count here is this process's own open files, which
    `/dev/fd` carries on macOS and on Linux.
    """

    STREAMS = 12
    SETTLE = 15.0      # generous: the watch ticks every serve.STREAM_TICK
    # The watch's tick, shortened from the deck's two seconds, and `Quiet`'s gap with it, kept
    # longer than a tick as the quiet-channel test needs. What is proved is the watch noticing
    # a hangup between ticks, which does not depend on how long a tick is; the two second
    # tick was a third of this module's run.
    TICK = 0.2

    def setUp(self):
        super().setUp()
        for target, name, value in ((serve, "STREAM_TICK", self.TICK),
                                    (Quiet, "GAP", self.TICK * 1.5)):
            patch = mock.patch.object(target, name, value)
            patch.start()
            self.addCleanup(patch.stop)
        self.lavish = http_server.ThreadingHTTPServer(("127.0.0.1", 0), Quiet)
        self.lavish.daemon_threads = True
        serve_in_background(self.lavish)
        self.addCleanup(self.lavish.server_close)      # cleanups run last registered first
        self.addCleanup(self.lavish.shutdown)
        self.cfg.lavish_port = self.lavish.server_address[1]

    def open_and_leave(self, key: str) -> None:
        """Open a proxied channel, read its first event, then hang up like a closed tab."""
        host = self.base.split("//")[1]
        client = socket.create_connection(("127.0.0.1", int(host.split(":")[1])))
        try:
            client.sendall(f"GET /events/{key} HTTP/1.1\r\nHost: {host}\r\n\r\n".encode())
            client.settimeout(10)
            got = b""
            while b"hello" not in got:
                got += client.recv(4096)
        finally:
            client.close()

    def open_files(self) -> int:
        return len(os.listdir("/dev/fd"))

    def test_abandoned_streams_do_not_pile_up_descriptors(self):
        self.open_and_leave("once")            # the first one pays for whatever is lazy
        time.sleep(serve.STREAM_TICK * 2)      # and is let go of before the count is taken
        before = self.open_files()
        for _ in range(self.STREAMS):
            self.open_and_leave("once")
        deadline = time.monotonic() + self.SETTLE
        while time.monotonic() < deadline and self.open_files() > before:
            time.sleep(0.25)
        self.assertLessEqual(self.open_files(), before,
                             f"{self.STREAMS} abandoned streams left descriptors open")

    def test_an_abandoned_chunked_stream_is_a_hangup_and_not_an_error(self):
        """Lavish frames `/events/` in chunks, and a read cut in the middle of a chunked
        answer raises `IncompleteRead` rather than returning nothing. That is still the
        client having left: it is counted with the other hangups and nothing reaches the
        error log."""
        before = serve.CLIENT_HANGUPS
        errors = io.StringIO()
        with contextlib.redirect_stderr(errors):
            self.open_and_leave("chunked")
            deadline = time.monotonic() + self.SETTLE
            while time.monotonic() < deadline and serve.CLIENT_HANGUPS == before:
                time.sleep(0.25)
        self.assertEqual(serve.CLIENT_HANGUPS, before + 1, errors.getvalue())
        self.assertNotIn("Traceback", errors.getvalue())

    def test_a_quiet_channel_with_somebody_still_on_it_is_not_cut(self):
        """The watch is for a client that left, never for one that is simply waiting: the
        gaps here are longer than a tick, and all three events must still arrive."""
        host = self.base.split("//")[1]
        client = socket.create_connection(("127.0.0.1", int(host.split(":")[1])))
        self.addCleanup(client.close)
        client.sendall(f"GET /events/slow HTTP/1.1\r\nHost: {host}\r\n\r\n".encode())
        client.settimeout(Quiet.GAP * 4)
        got = b""
        while b"hello 2" not in got:
            chunk = client.recv(4096)
            self.assertTrue(chunk, f"the stream ended early on {got!r}")
            got += chunk
        for index in range(3):
            self.assertIn(f"data: hello {index}".encode(), got)


class FakeGateway(http_server.BaseHTTPRequestHandler):
    """Stands in for the voice gateway: `/voice/health` echoes the headers it was given,
    `/voice/ws` answers the upgrade, says hello first, then echoes whatever arrives."""

    protocol_version = "HTTP/1.1"     # what the real gateway speaks
    seen: list[dict] = []

    def log_message(self, *args):
        pass

    def do_GET(self):
        FakeGateway.seen.append({"path": self.path, "host": self.headers.get("Host"),
                                 "forwarded": self.headers.get("X-Forwarded-Host")})
        if self.path == "/voice/ws":
            if "websocket" not in (self.headers.get("Upgrade") or "").lower():
                self.send_response(400)     # what the real gateway's is_upgrade check does
                self.send_header("Content-Length", "0")
                self.end_headers()
                return
            self.send_response(101, "Switching Protocols")
            self.send_header("Upgrade", "websocket")
            self.send_header("Connection", "Upgrade")
            self.end_headers()
            self.wfile.write(b"hello-from-gateway")
            self.wfile.flush()
            while True:
                chunk = self.rfile.read1(4096)
                if not chunk:
                    break
                self.wfile.write(chunk.upper())
                self.wfile.flush()
            self.close_connection = True
            return
        body = json.dumps({"ok": True, "upSeconds": 3.0,
                           "forwardedHost": self.headers.get("X-Forwarded-Host")}).encode()
        self.send_response(200 if self.path.startswith("/voice/health") else 404)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


class VoiceTierTest(ServerCase):
    """`/voice/...` is proxied to the gateway with the browser's Host forwarded, the
    upgrade is spliced byte for byte, and a dead port answers 503 rather than hanging."""

    def setUp(self):
        super().setUp()
        FakeGateway.seen = []
        self.gateway = http_server.ThreadingHTTPServer(("127.0.0.1", 0), FakeGateway)
        serve_in_background(self.gateway)
        self.addCleanup(self.gateway.server_close)   # cleanups run last registered first
        self.addCleanup(self.gateway.shutdown)
        self.cfg.voice_port = self.gateway.server_address[1]

    def request(self, path, headers):
        request = urllib.request.Request(self.base + path, headers=headers)
        try:
            with urllib.request.urlopen(request, timeout=10) as response:
                return response.status, response.read()
        except urllib.error.HTTPError as error:
            with error:
                return error.code, error.read()

    def raw(self, text: str) -> socket.socket:
        client = socket.create_connection(("127.0.0.1", int(self.base.rsplit(":", 1)[1])))
        client.settimeout(10)
        client.sendall(text.encode())
        return client

    @staticmethod
    def read_until(client: socket.socket, marker: bytes) -> bytes:
        got = b""
        while marker not in got:
            chunk = client.recv(4096)
            if not chunk:
                break
            got += chunk
        return got

    def test_health_is_proxied_with_the_browsers_host_forwarded(self):
        status, body = self.request("/voice/health", {"Host": "x.example", "X-Forwarded-Host": "evil.example"})
        self.assertEqual(status, 200)
        self.assertEqual(json.loads(body)["forwardedHost"], "x.example")
        self.assertEqual(FakeGateway.seen[-1]["forwarded"], "x.example")
        self.assertNotEqual(FakeGateway.seen[-1]["host"], "x.example", "the gateway gets a loopback Host, not the browser's")
        status, body = self.request("/voice/nope", {"Host": "x.example"})
        self.assertEqual(status, 404, "the gateway's own answer is relayed, code and all")

    def test_nothing_on_the_port_is_an_honest_503_not_a_hang(self):
        self.cfg.voice_port = free_port()
        started = time.time()
        status, body = self.request("/voice/health", {"Host": "x.example"})
        self.assertEqual(status, 503)
        self.assertIn(b"voice is down", body)
        self.assertLess(time.time() - started, 5)
        # The upgrade is the page's (c-451): its cookie and its origin, or a 403 first.
        cookie = self.page_headers()["Cookie"]
        client = self.raw("GET /voice/ws HTTP/1.1\r\nHost: x.example\r\nUpgrade: websocket\r\n"
                          f"Origin: http://x.example\r\nCookie: {cookie}\r\n"
                          "Connection: Upgrade\r\nSec-WebSocket-Key: abc\r\n\r\n")
        head = self.read_until(client, b"voice is down")
        client.close()
        self.assertTrue(head.startswith(b"HTTP/1.0 503"), head[:40])

    def test_the_upgrade_is_spliced_and_bytes_flow_both_ways(self):
        # The phone's own upgrade through `tailscale serve`: https, and the page's cookie.
        cookie = self.page_headers()["Cookie"]
        client = self.raw("GET /voice/ws HTTP/1.1\r\nHost: x.example\r\nOrigin: https://x.example\r\n"
                          f"X-Forwarded-Proto: https\r\nCookie: {cookie}\r\n"
                          "Upgrade: websocket\r\nConnection: Upgrade\r\nSec-WebSocket-Key: abc\r\n"
                          "X-Forwarded-Host: evil.example\r\n\r\n")
        head = self.read_until(client, b"hello-from-gateway")
        self.assertTrue(head.startswith(b"HTTP/1.1 101 Switching Protocols"), head[:60])
        self.assertIn(b"Upgrade: websocket", head)
        client.sendall(b"ping-bytes")
        self.assertIn(b"PING-BYTES", self.read_until(client, b"PING-BYTES"))
        client.sendall(b"again")
        self.assertIn(b"AGAIN", self.read_until(client, b"AGAIN"))
        client.close()
        self.assertEqual(FakeGateway.seen[-1]["path"], "/voice/ws")
        self.assertEqual(FakeGateway.seen[-1]["forwarded"], "x.example", "the inbound claim was dropped")
        self.assertEqual(FakeGateway.seen[-1]["host"], f"127.0.0.1:{self.cfg.voice_port}")
        for _ in range(100):      # the handler thread lets go once both sides have closed
            if not any(t.name == "voice-splice" and t.is_alive() for t in threading.enumerate()):
                break
            time.sleep(0.05)
        self.assertFalse(any(t.name == "voice-splice" and t.is_alive() for t in threading.enumerate()))
        self.assertEqual(self.fetch("/api/state")[0], 200)


class SegmentTierTest(ServerCase):
    """What the deck serves for a segment beyond its app, and the two drops it accepts.

    The three segment apps were written against the old dashboard's routes and are static
    files nobody is going to rewrite, so these tests pin the contract rather than a design:
    the paths, the names on disk, the caps, and the exact keys each answer carries.
    """

    def setUp(self):
        super().setUp()
        self.seg = self.cfg.segments_dir / "alpha"
        (self.seg / "data").mkdir(parents=True, exist_ok=True)
        (self.seg / "data" / "daybook.json").write_text(json.dumps({"stories": [1, 2, 3]}))
        (self.seg / "data" / ".secret.json").write_text("{}")
        (self.seg / "data" / "creds.pem").write_text("-----BEGIN-----")
        (self.seg / "data" / "inbox").mkdir(exist_ok=True)
        (self.seg / "data" / "inbox-applied").mkdir(exist_ok=True)
        (self.seg / "data" / "asks").mkdir(exist_ok=True)

    # ----- helpers -----

    def post(self, path, body, ctype="application/json", headers=None):
        request = urllib.request.Request(self.base + path, data=body, method="POST")
        request.add_header("Content-Type", ctype)
        for name, value in (headers or {}).items():
            request.add_header(name, value)
        try:
            with urllib.request.urlopen(request, timeout=30) as response:
                return response.status, json.loads(response.read())
        except urllib.error.HTTPError as error:
            with error:
                return error.code, json.loads(error.read())

    def raw_get(self, path):
        """A GET whose path is sent exactly as written, the way `curl --path-as-is` does."""
        client = socket.create_connection(("127.0.0.1", int(self.base.rsplit(":", 1)[1])), timeout=10)
        client.sendall(f"GET {path} HTTP/1.1\r\nHost: deck.test\r\nConnection: close\r\n\r\n".encode())
        got = b""
        while True:
            chunk = client.recv(4096)
            if not chunk:
                break
            got += chunk
        client.close()
        return int(got.split(b" ", 2)[1])

    def dropped(self):
        return sorted(p.name for p in (self.seg / "data" / "inbox").iterdir() if p.is_file())

    def uploaded(self):
        box = self.seg / "inbox"
        return sorted(p.name for p in box.iterdir() if p.is_file()) if box.is_dir() else []

    JOURNAL = {"entries": [{"k": "story:one", "v": {"note": "a"}, "t": "2026-09-18T10:00:00+05:30"},
                           {"k": "story:two", "v": {"note": "b"}, "t": "2026-09-18T10:01:00+05:30"}]}
    PDF = b"%PDF-1.4\nthe bill\n%%EOF\n"

    # ----- reads -----

    def test_a_data_file_and_the_summary_are_served(self):
        status, ctype, body = self.fetch("/segments/alpha/data/daybook.json")
        self.assertEqual((status, ctype), (200, "application/json; charset=utf-8"))
        self.assertEqual(json.loads(body)["stories"], [1, 2, 3])
        status, ctype, body = self.fetch("/segments/alpha/summary.json")
        self.assertEqual((status, ctype), (200, "application/json; charset=utf-8"))
        self.assertEqual(json.loads(body)["tiles"][0]["label"], "things")

    def test_a_read_is_never_cached(self):
        with urllib.request.urlopen(self.base + "/segments/alpha/data/daybook.json", timeout=10) as response:
            self.assertEqual(response.headers.get("Cache-Control"), serve.NO_STORE)

    def test_the_narrow_rules_on_a_data_read(self):
        """Traversal, the segment's own working directories, a dotfile, a credential, and a
        name that is simply not there. Every one of them is the same 404."""
        self.assertEqual(self.raw_get("/segments/alpha/data/../fetch.py"), 404)
        self.assertEqual(self.raw_get("/segments/alpha/app/../data/daybook.json"), 404)
        self.assertEqual(self.raw_get("/segments/alpha/data/../../board.db"), 404)
        for path in ("/segments/alpha/data/inbox", "/segments/alpha/data/inbox/",
                     "/segments/alpha/data/inbox-applied", "/segments/alpha/data/asks",
                     "/segments/alpha/data/.secret.json", "/segments/alpha/data/creds.pem",
                     "/segments/alpha/data/nothing.json", "/segments/beta/data/daybook.json",
                     "/segments/alpha/fetch.py", "/segments/alpha/nonsense"):
            self.assertEqual(self.fetch(path)[0], 404, path)

    def test_the_whole_prefix_is_the_decks_so_nothing_reaches_lavish(self):
        """`lavish_port` is 1 in these tests, so a path that fell through would be a 503."""
        status, _, body = self.fetch("/segments/alpha/whatever")
        self.assertEqual(status, 404)
        self.assertEqual(json.loads(body)["error"], "not a segment route")

    # ----- the decisions drop -----

    def test_a_journal_is_stored_under_the_name_the_fold_expects(self):
        status, answer = self.post("/segments/alpha/decisions", json.dumps(self.JOURNAL).encode())
        self.assertEqual(status, 200)
        self.assertEqual({k: answer[k] for k in ("ok", "entries", "duplicate", "pending")},
                         {"ok": True, "entries": 2, "duplicate": False, "pending": 1})
        self.assertRegex(answer["stored"], r"^\d{8}T\d{6}Z-[0-9a-f]{8}-decisions\.json$")
        self.assertEqual(self.dropped(), [answer["stored"]])
        self.assertEqual(json.loads((self.seg / "data" / "inbox" / answer["stored"]).read_text()),
                         self.JOURNAL)

    def test_the_same_journal_posted_twice_is_stored_once(self):
        first = self.post("/segments/alpha/decisions", json.dumps(self.JOURNAL).encode())[1]
        status, second = self.post("/segments/alpha/decisions", json.dumps(self.JOURNAL).encode())
        self.assertEqual((status, second["duplicate"], second["stored"]), (200, True, first["stored"]))
        self.assertEqual(self.dropped(), [first["stored"]])

    def test_a_journal_already_folded_is_recognised_as_a_duplicate(self):
        stored = self.post("/segments/alpha/decisions", json.dumps(self.JOURNAL).encode())[1]["stored"]
        (self.seg / "data" / "inbox" / stored).replace(self.seg / "data" / "inbox-applied" / stored)
        status, answer = self.post("/segments/alpha/decisions", json.dumps(self.JOURNAL).encode())
        self.assertEqual((status, answer["duplicate"], answer["stored"]), (200, True, stored))
        self.assertEqual(self.dropped(), [])

    def test_a_journal_that_is_not_one_is_refused_with_the_reason(self):
        cases = [(b"{not json", "that is not JSON"),
                 (b"[1, 2]", "a journal is a JSON object"),
                 (b'{"entries": {}}', "a journal needs an entries list"),
                 (b'{"entries": []}', "there is nothing in it to apply"),
                 (b'{"entries": [1]}', "every entry is an object"),
                 (b'{"entries": [{"v": 1, "t": "now"}]}', "every entry needs a key"),
                 (b'{"entries": [{"k": "a", "v": 1}]}', "every entry needs a timestamp")]
        for body, why in cases:
            status, answer = self.post("/segments/alpha/decisions", body)
            self.assertEqual((status, answer["error"]), (400, why), body)
        self.assertEqual(self.dropped(), [])

    def test_a_journal_over_the_cap_or_of_the_wrong_type_is_refused(self):
        status, answer = self.post("/segments/alpha/decisions", b'{"entries": []}', ctype="text/plain")
        self.assertEqual((status, answer["error"]), (415, "a journal must be sent as application/json"))
        # ONE byte over, not sixty kilobytes over. The deck drains up to the cap and answers,
        # and whatever is left unread when it closes resets the connection: a client still
        # writing the tail then fails with a broken pipe instead of reading the 413, which a
        # loaded machine (a parallel run) hit one run in three. Over by one, the tail is sent
        # with the rest before the deck has read enough to answer.
        big = b"{" + b" " * segments.DECISIONS_MAX
        self.assertEqual(len(big), segments.DECISIONS_MAX + 1)
        status, answer = self.post("/segments/alpha/decisions", big)
        self.assertEqual((status, answer["error"]), (413, "too large, the cap is 1024KB"))
        self.assertEqual(self.dropped(), [])

    def test_a_journal_from_a_foreign_page_is_refused(self):
        for headers in ({"Origin": "http://evil.example"}, {"Sec-Fetch-Site": "cross-site"}):
            status, answer = self.post("/segments/alpha/decisions",
                                       json.dumps(self.JOURNAL).encode(), headers=headers)
            self.assertEqual((status, answer["error"]), (403, segments.FOREIGN), headers)
        self.assertEqual(self.dropped(), [])
        status, _ = self.post("/segments/alpha/decisions", json.dumps(self.JOURNAL).encode(),
                              headers={"Sec-Fetch-Site": "same-origin"})
        self.assertEqual(status, 200, "the deck's own page is not the one being stopped")

    # ----- the upload drop -----

    def test_an_upload_is_stored_under_a_name_the_server_generates(self):
        status, answer = self.post("/segments/alpha/inbox?name=" + urllib.parse.quote("my bill.PDF"),
                                   self.PDF, ctype="application/pdf")
        self.assertEqual(status, 200)
        self.assertEqual({k: answer[k] for k in ("ok", "bytes", "duplicate", "pending")},
                         {"ok": True, "bytes": len(self.PDF), "duplicate": False, "pending": 1})
        self.assertRegex(answer["stored"], r"^\d{8}T\d{6}Z-[0-9a-f]{8}-my-bill\.pdf$")
        self.assertEqual(self.uploaded(), [answer["stored"]])
        listing = self.get_json("/segments/alpha/inbox")
        self.assertEqual((listing["count"], listing["pending"][0]["name"]), (1, answer["stored"]))
        self.assertEqual(listing["pending"][0]["bytes"], len(self.PDF))

    def test_the_same_blob_uploaded_twice_is_stored_once(self):
        first = self.post("/segments/alpha/inbox?name=a.pdf", self.PDF, ctype="application/pdf")[1]
        status, second = self.post("/segments/alpha/inbox?name=b.pdf", self.PDF, ctype="application/pdf")
        self.assertEqual((status, second["duplicate"], second["stored"]), (200, True, first["stored"]))
        self.assertEqual(self.uploaded(), [first["stored"]])

    def test_an_upload_whose_bytes_are_not_what_it_claims_is_refused(self):
        status, answer = self.post("/segments/alpha/inbox", b"just words", ctype="application/pdf")
        self.assertEqual((status, answer["error"]), (415, "the bytes are not application/pdf"))
        status, answer = self.post("/segments/alpha/inbox", self.PDF, ctype="text/plain")
        self.assertEqual(status, 415)
        self.assertIn("application/pdf", answer["error"])
        self.assertEqual(self.uploaded(), [])

    def test_an_upload_over_the_cap_is_refused(self):
        status, answer = self.post("/segments/alpha/inbox", b"%PDF-" + b"0" * segments.INBOX_MAX,
                                   ctype="application/pdf")
        self.assertEqual((status, answer["error"]), (413, "too large, the cap is 10MB"))
        self.assertEqual(self.uploaded(), [])

    def test_the_two_hundred_and_first_file_is_refused(self):
        box = self.seg / "inbox"
        box.mkdir(parents=True)
        for number in range(segments.INBOX_MAX_FILES):
            (box / f"waiting-{number:03d}.pdf").write_bytes(b"%PDF-")
        status, answer = self.post("/segments/alpha/inbox", self.PDF, ctype="application/pdf")
        self.assertEqual(status, 429)
        self.assertIn("200 files", answer["error"])
        self.assertEqual(len(self.uploaded()), segments.INBOX_MAX_FILES)

    def test_the_two_hundred_and_first_journal_is_refused(self):
        box = self.seg / "data" / "inbox"
        for number in range(segments.DECISIONS_MAX_FILES):
            (box / f"waiting-{number:03d}.json").write_text("{}")
        status, answer = self.post("/segments/alpha/decisions", json.dumps(self.JOURNAL).encode())
        self.assertEqual(status, 429)
        self.assertIn("200 journals", answer["error"])
        self.assertEqual(len(self.dropped()), segments.DECISIONS_MAX_FILES)

    def test_an_upload_from_a_foreign_page_or_an_unknown_segment_is_refused(self):
        status, answer = self.post("/segments/alpha/inbox", self.PDF, ctype="application/pdf",
                                   headers={"Origin": "http://evil.example"})
        self.assertEqual((status, answer["error"]), (403, segments.FOREIGN))
        status, answer = self.post("/segments/nosuch/inbox", self.PDF, ctype="application/pdf")
        self.assertEqual((status, answer["error"]), (404, "no such segment"))
        status, answer = self.post("/segments/nosuch/decisions", json.dumps(self.JOURNAL).encode())
        self.assertEqual((status, answer["error"]), (404, "no such segment"))
        self.assertEqual(self.uploaded(), [])


class TheMorphTest(unittest.TestCase):
    """The render pass's reconciler, run under node against a DOM stand-in.

    `K.morph` is pure structure (`tests/fixtures/deck-morph.js` says what it checks and
    why it can be checked at all), and it is the one piece of the page that decides
    whether the deck changes or reloads. The rest of the page's behaviour is a grep in
    tests/test_deck_css.py and a browser in <install>/history/tests/live_deck.md; this actually runs it.
    """

    @unittest.skipUnless(shutil.which("node"), "node is not on this machine")
    def test_the_morph_changes_only_what_differs(self):
        root = Path(serve.__file__).resolve().parent.parent
        harness = root / "tests" / "fixtures" / "deck-morph.js"
        result = subprocess.run(["node", str(harness), str(root / "app" / "ui.core.js")],
                                capture_output=True, text=True, timeout=60)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(result.stdout), {"ok": True}, result.stdout)


class RevisionTest(ServerCase):
    """Nothing renders when nothing changed.

    Both documents the page holds carry a revision as an ETag, and a conditional request
    that matches is a 304 with no body. The state's revision has to move on a write and
    has to hold still otherwise, or the page is back to redrawing on every poll.

    The coarse clock is held for every test here (`held_clock`): each one reads the
    revision more than once, and "holds still" must be about the board, never about where
    the wall clock was. The one test about the clock moving patches it again inside.
    """

    def setUp(self):
        super().setUp()
        clock = held_clock()
        clock.start()
        self.addCleanup(clock.stop)

    def conditional(self, path, tag):
        request = urllib.request.Request(self.base + path)
        request.add_header("If-None-Match", tag)
        try:
            with urllib.request.urlopen(request, timeout=10) as response:
                return response.status, response.headers.get("ETag", ""), response.read()
        except urllib.error.HTTPError as error:
            with error:
                return error.code, error.headers.get("ETag", ""), error.read()

    def tag_of(self, path):
        request = urllib.request.Request(self.base + path)
        with urllib.request.urlopen(request, timeout=10) as response:
            self.assertEqual(response.status, 200)
            tag = response.headers.get("ETag")
            response.read()
        self.assertTrue(tag, f"{path} carries no ETag")
        return tag

    def test_a_card_s_revision_holds_still_across_the_clock(self):
        """E3 and c-579 review F1: a card's pane moves only with the board or its record, so
        a clock step alone never makes the pane or the plan stream ask again."""
        deck = deckstate.Deck(self.cfg)
        with mock.patch.object(deckstate, "clock_step", return_value=1):
            then = deck.card_rev(self.blocked)
        with mock.patch.object(deckstate, "clock_step", return_value=2):
            self.assertEqual(deck.card_rev(self.blocked), then)

    def test_the_state_answers_its_own_etag_with_a_304(self):
        with mock.patch.object(deckstate.harness, "agents_across", return_value=self.rows()):
            tag = self.tag_of("/api/state")
            status, back, body = self.conditional("/api/state", tag)
        self.assertEqual(status, 304)
        self.assertEqual(back, tag)
        self.assertEqual(body, b"", "a 304 carried a body")

    def test_a_write_moves_the_revision_so_the_next_poll_is_not_a_304(self):
        with mock.patch.object(deckstate.harness, "agents_across", return_value=self.rows()):
            tag = self.tag_of("/api/state")
            status, _, _ = self.fetch("/api/action", data=json.dumps(
                {"verb": "note", "id": self.inbox, "text": "from the deck"}).encode(), page=True)
            self.assertEqual(status, 200)
            status, fresh, _ = self.conditional("/api/state", tag)
        self.assertEqual(status, 200, "the write did not move the revision")
        self.assertNotEqual(fresh, tag)

    def test_a_cards_revision_is_its_updated_at_and_its_event_count(self):
        path = "/api/card/" + self.inbox
        tag = self.tag_of(path)
        self.assertEqual(self.conditional(path, tag)[0], 304)
        self.board.note(self.inbox, "one more", "human")
        self.assertEqual(self.conditional(path, tag)[0], 200, "a new event left the card's tag alone")

    def test_a_write_from_another_process_moves_the_revision(self):
        """The board runs in WAL mode, so another process's write lands in `board.db-wal`
        and the main file's own mtime does not move until a checkpoint. A revision that
        watched the main file alone would hand that page a 304 while the board underneath
        it had changed, for as long as the coarse clock took to roll."""
        deck = deckstate.Deck(self.cfg)
        self.addCleanup(close_stamp, deck)
        before = deck.rev()
        other = Board(self.cfg.db_path)
        try:
            other.note(self.inbox, "written by another handle", "human")
        finally:
            other.close()
        # Past the stamp's memo, which is what stops the stream's sweep asking the board
        # four times a second per subscriber. It is shorter than that sweep, so this is the
        # test waiting rather than the deck being slow.
        time.sleep(deckstate.STAMP_TTL * 1.5)
        self.assertNotEqual(deck.rev(), before,
                            "a write through a second handle left the revision where it was")

    def test_a_card_that_gained_only_a_context_record_is_not_a_304(self):
        """The pane shows `context.md` (the PR body, where it stands), and a house writes
        that file without the card gaining an event of its own."""
        path = "/api/card/" + self.review
        tag = self.tag_of(path)
        self.assertEqual(self.conditional(path, tag)[0], 304)
        context = self.cfg.card_dir(self.review) / "context.md"
        context.write_text(context.read_text() + "\n\nThe house wrote another paragraph.\n")
        os.utime(context, (time.time() + 2, time.time() + 2))
        status, _, body = self.conditional(path, tag)
        self.assertEqual(status, 200, "a rewritten context record answered a stale 304")
        self.assertIn("another paragraph", json.loads(body)["context"])

    def let_go(self):
        """Close the case's own board handle for the rest of the test.

        It is not reopened. It used to be, in a cleanup, but cleanups run AFTER `tearDown`,
        so the reopened board was never closed and the collector found it later, inside
        some other test (`tests/boardleak.py`). `tearDown` closing an already closed board
        is a no-op, so nothing needs it back.
        """
        self.board.close()

    def churn(self):
        """A board connection opened and closed, which is what a deck does all day.

        Every card read, every action and every `kb` opens one and lets it go. The LAST one
        to close takes the write-ahead log with it (SQLite checkpoints and deletes it), and
        the next connection makes it again, so on a live deck that file comes and goes with
        the traffic.
        """
        Board(self.cfg.db_path).close()

    def test_ten_reads_answer_one_etag(self):
        """A READ MUST NOT MOVE THE REVISION.

        It was a sum over the board files' mtimes, one of which, the write-ahead log,
        exists only while somebody has the board open. A real deck opens and closes
        connections constantly, so that file appeared and vanished under the revision all
        day and the tag moved between one poll and the next: no client ever got a 304 from
        the tag it had just been handed.
        """
        holder = Board(self.cfg.db_path)
        self.addCleanup(holder.close)
        with mock.patch.object(deckstate.time, "time", return_value=1789965000.0):
            with mock.patch.object(deckstate.harness, "agents_across", return_value=self.rows()):
                tags = []
                for turn in range(10):
                    tags.append(self.tag_of("/api/state"))
                    if turn == 4:
                        # the last handle lets go, which is when the log is checkpointed away
                        self.let_go()
                        holder.close()
                    self.churn()
        self.assertEqual(len(set(tags)), 1,
                         f"ten reads answered {len(set(tags))} tags: {sorted(set(tags))}")

    def test_the_write_ahead_log_coming_and_going_does_not_move_it(self):
        """The two magnitudes the box saw alternating, one near the clock and one near the
        board file's mtime, were that log being there and not being there. Who has the
        board open is not a fact about whether anything changed."""
        deck = deckstate.Deck(self.cfg)
        self.addCleanup(close_stamp, deck)
        with mock.patch.object(deckstate.time, "time", return_value=1789965000.0):
            held = deck.rev()
            self.let_go()                            # the last handle lets go, and the log with it
            self.assertEqual(deck.rev(), held,
                             "the revision moved because the write-ahead log was checkpointed away")
            self.churn()
            self.assertEqual(deck.rev(), held, "the revision moved because a board was opened")
            self.churn()
            self.assertEqual(deck.rev(), held, "the revision moved on a second connection")

    def test_the_route_answers_exactly_what_the_one_function_says(self):
        """ONE function computes the revision, and the ETag is it.

        Held against the live handler's own `Deck` rather than against a second one, and
        across the connection churn a deck always has, because the defect was that the
        value the route answered and the value a publisher had just named came out of the
        same expression but not the same reading of the world.
        """
        deck = self.server.RequestHandlerClass.deck
        self.let_go()
        with mock.patch.object(deckstate.harness, "agents_across", return_value=self.rows()):
            first = deck.rev()
            for _ in range(5):
                self.assertEqual(self.tag_of("/api/state"), f'"{deck.rev()}"',
                                 "the route answers something other than deck.rev()")
                self.churn()
                self.assertEqual(deck.rev(), first, "the revision moved under the churn")

    def test_one_cards_tag_never_answers_for_another(self):
        mine = self.tag_of("/api/card/" + self.inbox)
        status, _, body = self.conditional("/api/card/" + self.review, mine)
        self.assertEqual(status, 200)
        self.assertEqual(json.loads(body)["card"]["id"], self.review)


class EventStreamTest(ServerCase):
    """`GET /api/events`: the page is told what changed rather than asking every five
    seconds. One thread per subscriber, a small cap, and a subscriber that walks away is
    dropped rather than held until a write that may never come."""

    # How long a test listens to prove a silence, and the sweep it listens to. The deck
    # sweeps every quarter second and the tests listened for three, twelve sweeps; here the
    # sweep is a twentieth and the window three quarters, fifteen sweeps, so the silence is
    # proved over more sweeps than before in a quarter of the time.
    SWEEP = 0.05
    HEAR = 0.75

    def setUp(self):
        super().setUp()
        from keel import deckevents
        self.events = deckevents
        deckevents.HUB.drop_all()
        self.addCleanup(deckevents.HUB.drop_all)
        patch = mock.patch.object(deckevents, "SWEEP_SECONDS", self.SWEEP)
        patch.start()
        self.addCleanup(patch.stop)

    def listen(self, query=""):
        """An open stream, and a reader that returns the next line or None."""
        response = urllib.request.urlopen(self.base + "/api/events" + query, timeout=10)
        self.addCleanup(response.close)
        self.assertIn("text/event-stream", response.headers.get("Content-Type", ""))
        return response

    def next_line(self, response, want, seconds=10.0):
        """The next `data:` line whose first word is `want`, or fail."""
        deadline = time.time() + seconds
        while time.time() < deadline:
            raw = response.readline()
            if not raw:
                break
            said = raw.decode().strip()
            if said.startswith("data: ") and said[6:].split(" ")[0] == want:
                return said[6:]
        self.fail(f"no {want} event arrived on the stream")

    def state_line(self, response, rev, seconds=10.0):
        """Read `state` lines until the one naming `rev` arrives, or fail."""
        deadline = time.time() + seconds
        heard = []
        while time.time() < deadline:
            heard.append(self.next_line(response, "state", deadline - time.time()).split(" ")[1])
            if heard[-1] == rev:
                return heard[-1]
        self.fail(f"the stream never said state {rev}: {heard}")

    def until(self, predicate, seconds=5.0):
        deadline = time.time() + seconds
        while time.time() < deadline:
            if predicate():
                return True
            time.sleep(0.05)
        return False

    def test_a_write_through_the_action_route_says_so_on_the_stream(self):
        response = self.listen()
        self.assertTrue(self.until(lambda: self.events.HUB.count() == 1))
        with mock.patch.object(deckstate.harness, "agents_across", return_value=self.rows()):
            status, _, _ = self.fetch("/api/action", data=json.dumps(
                {"verb": "note", "id": self.inbox, "text": "said on the stream"}).encode(), page=True)
        self.assertEqual(status, 200)
        self.assertTrue(self.next_line(response, "state").startswith("state "))
        self.assertEqual(self.next_line(response, "card").split(" ")[1], self.inbox)

    def test_a_board_push_says_so_on_the_stream(self):
        from keel import boards
        boards.push(self.cfg, 'board "b"\nnote board "one"', card=self.live)
        response = self.listen("?board=b-001")
        self.assertTrue(self.until(lambda: self.events.HUB.count() == 1))
        boards.push(self.cfg, 'note board "and another"', card=self.live)
        said = self.next_line(response, "board").split(" ")
        self.assertEqual(said[1], "b-001")
        self.assertGreater(int(said[2]), 0)

    def test_a_subscriber_that_goes_away_is_dropped(self):
        response = urllib.request.urlopen(self.base + "/api/events", timeout=10)
        self.assertTrue(self.until(lambda: self.events.HUB.count() == 1))
        response.close()
        self.assertTrue(self.until(lambda: self.events.HUB.count() == 0, seconds=10.0),
                        "a stream nobody is reading was held open")

    def test_the_cap_holds_and_the_oldest_goes(self):
        """One human's deck: several tabs and a phone is the whole of it, and a ninth
        listener must not be able to grow the list without bound."""
        open_streams = [self.events.HUB.open() for _ in range(self.events.MAX_SUBSCRIBERS)]
        self.assertEqual(self.events.HUB.count(), self.events.MAX_SUBSCRIBERS)
        extra = self.events.HUB.open()
        self.assertEqual(self.events.HUB.count(), self.events.MAX_SUBSCRIBERS)
        self.assertTrue(open_streams[0].closed, "the oldest subscriber was not the one dropped")
        self.assertFalse(extra.closed)

    def test_a_subscriber_too_far_behind_to_read_is_dropped_rather_than_wedging_a_writer(self):
        stream = self.events.HUB.open()
        for _ in range(self.events.QUEUE_DEPTH + 5):
            self.events.HUB.send("state 1")
        self.assertEqual(self.events.HUB.count(), 0)
        self.assertTrue(stream.closed)

    def test_a_burst_does_not_defer_noticing_the_client_left(self):
        """The hangup check used to run only when the queue went quiet, so a busy board
        could hold a stream nobody was reading for as long as the writes kept coming."""
        response = urllib.request.urlopen(self.base + "/api/events", timeout=10)
        self.assertTrue(self.until(lambda: self.events.HUB.count() == 1))
        response.close()
        # A line every few milliseconds: with a queue that never empties, a check that
        # waits for a quiet moment never runs at all.
        stop = time.time() + 8.0
        while time.time() < stop and self.events.HUB.count():
            self.events.HUB.state(1)
            time.sleep(0.01)
        self.assertEqual(self.events.HUB.count(), 0,
                         "a stream nobody is reading survived a burst of writes")

    def test_the_route_and_the_stream_say_the_same_revision(self):
        """ONE function computes it, so what the stream names is what the route would
        answer at that moment. Two formulas alternating is what told the page the state had
        changed on every sweep."""
        # THE PUBLISHER'S LINE, NOT THE FIRST ONE. A sweep can read the board's stamp after
        # the write commits and before the action's own count moves, and say that half-way
        # revision first; the page answers it with a fetch and then hears the publisher's,
        # so nothing is wrong there. This test read that sweep's line as the publisher's and
        # failed whenever the box was loaded enough for it to come first (r-22, 4 runs in 8
        # beside a CPU burner). What the write published is recorded and waited for instead,
        # and the clock is held, so the route cannot answer a later step either.
        published = []
        hub_state = self.events.HUB.state

        def recording(rev):
            published.append(rev)
            return hub_state(rev)
        clock = held_clock()
        clock.start()
        self.addCleanup(clock.stop)
        response = self.listen()
        self.assertTrue(self.until(lambda: self.events.HUB.count() == 1))
        self.board.close()                            # let the board's connections come and go
        with mock.patch.object(deckstate.harness, "agents_across", return_value=self.rows()), \
                mock.patch.object(self.events.HUB, "state", side_effect=recording):
            request = urllib.request.Request(self.base + "/api/state")
            with urllib.request.urlopen(request, timeout=10) as answer:
                before = answer.headers.get("ETag")
                answer.read()
            status, _, _ = self.fetch("/api/action", data=json.dumps(
                {"verb": "note", "id": self.inbox, "text": "so the revision moves once"}).encode(), page=True)
            self.assertEqual(status, 200)
            self.assertTrue(published, "the write published no state line")
            said = self.state_line(response, published[-1])
            # the ordinary traffic of a deck, between the line and the fetch it provokes
            for _ in range(3):
                Board(self.cfg.db_path).close()
            with urllib.request.urlopen(request, timeout=10) as answer:
                after = answer.headers.get("ETag")
                answer.read()
        self.assertNotEqual(after, before, "the write did not move the revision at all")
        self.assertEqual(f'"{said}"', after,
                         f"the stream said {said} and the route answers {after}")

    def heard_for(self, response, seconds: float | None = None) -> list[str]:
        """Every `data:` line that arrives in the next `seconds`, pings included."""
        response.fp.raw._sock.settimeout(seconds or self.HEAR)
        said = []
        try:
            while True:
                raw = response.readline()
                if not raw:
                    break
                line = raw.decode().strip()
                if line.startswith("data: "):
                    said.append(line[6:])
        except (TimeoutError, OSError):
            pass
        return said

    def stepping_clock(self, first: int = 100, then: int = 101):
        """The coarse clock, held at `first` for its FIRST reading and `then` after.

        By call order rather than by wall clock, and that is the whole point: the sweep
        reads the clock once when the stream opens and again on every pass, so a test that
        bumped a variable after the stream was up would be racing that first read. This
        cannot race: whatever the threads do, the stream initialises at `first` and every
        sweep sees `then`.
        """
        readings = itertools.count()
        return mock.patch.object(deckstate, "clock_step",
                                 side_effect=lambda: first if next(readings) == 0 else then)

    def stepping_with_the_write(self, first: int = 100, then: int = 101):
        """The coarse clock steps IN THE SAME READING that first sees a write.

        `Deck.rev_parts` wrapped so its clock half is `first` while its written half is
        still what the served deck held when this was called, and `then` once that differs. `stepping_clock`
        steps on the second reading instead, which is the first sweep's: under load the
        sweep ran before the write had landed, read the stepped clock with nothing written,
        and said `tick 101` (r-22, red 8 runs in 8 beside a CPU burner). Coupled to the
        write, no sweep can see the step without the write, however slow the write is; a
        sweep that dropped the clock a write carried would still say `tick` a pass later.

        THE BASELINE IS TAKEN HERE, BEFORE THE STREAM OPENS, not from the first reading. A
        stream thread starved past the write would otherwise let the publisher's own reading
        be the first, and the write would become the baseline (c-545 review).
        """
        real = deckstate.Deck.rev_parts
        opened, _clock = real(self.server.RequestHandlerClass.deck)

        def rev_parts(deck):
            written, _clock = real(deck)
            return written, str(first if written == opened else then)
        return mock.patch.object(deckstate.Deck, "rev_parts", autospec=True,
                                 side_effect=rev_parts)

    def quiet_clock(self, step: int = 100):
        """The coarse clock held still, so a sweep's silence is about the BOARD.

        `Deck.rev`'s third term is `int(time.time() // REV_SECONDS)` and this test reads
        three seconds of a fifteen second step, so one run in five used to see it tick and
        fail. The tick is real and the page wants it; what it is not is a reason to say the
        STATE changed, and a test about the sweep's silence must not be a coin toss about
        where the wall clock happened to be.
        """
        return held_clock(step)

    def test_a_sweep_with_nothing_written_publishes_nothing(self):
        """The sweep publishes only what differs from the last value it published, so a
        deck nobody is writing to is silent rather than telling the page to refetch four
        times a second."""
        with self.quiet_clock():
            response = self.listen()
            self.assertTrue(self.until(lambda: self.events.HUB.count() == 1))
            self.board.close()                        # let the board's connections come and go
            churn = threading.Thread(target=self.keep_churning, daemon=True)
            churn.start()
            said = self.heard_for(response)
            # Joined HERE, not in a cleanup: cleanups run after tearDown, which removes the
            # state dir, and on a loaded machine the churn outlived the listen and was still
            # creating the board's WAL files in a directory being deleted ("Directory not
            # empty", 2026-09-24, lane F's full run).
            churn.join(10.0)
        self.assertEqual([line for line in said if not line.startswith("ping")], [],
                         f"a quiet window of {self.HEAR}s published {said}")

    def test_the_coarse_clock_ticking_is_a_tick_and_never_a_state(self):
        """THE CLOCK IS NOT NEWS ABOUT THE STATE (2026-09-21).

        `Deck.rev` carries a fifteen second clock so that an idle deck still refreshes the
        two inputs that are neither a write nor the board (the drain log, the usage tee).
        The sweep published that as `state`, and the page answers `state` with a whole
        `/api/state` fetch: an open deck nobody was touching refetched the document four
        times a minute to move some ages by fifteen seconds. It is a `tick` now, which the
        page answers by re-rendering what it already holds.
        """
        with self.stepping_clock():                   # the fifteen seconds pass
            response = self.listen()
            self.assertTrue(self.until(lambda: self.events.HUB.count() == 1))
            said = self.heard_for(response)
        ticks = [line for line in said if line.startswith("tick")]
        self.assertEqual(len(ticks), 1, f"one clock step published {said}")
        self.assertEqual(ticks[0], "tick 101")
        self.assertEqual([line for line in said if line.startswith("state")], [],
                         f"the clock said the state had changed: {said}")

    def test_a_clock_step_is_said_once_however_long_it_stands(self):
        """At most once per step: the sweep runs four times a second and the step lasts
        fifteen, so a tick per sweep would be the poll it replaced, wearing a new word."""
        with self.stepping_clock():
            response = self.listen()
            self.assertTrue(self.until(lambda: self.events.HUB.count() == 1))
            said = self.heard_for(response)
        self.assertEqual(len([line for line in said if line.startswith("tick")]), 1, said)

    def test_a_real_write_is_still_a_state_and_swallows_the_clock_with_it(self):
        """A write carries the new clock in the same line, so the page does not get a
        `state` and then a `tick` about a step the `state` already told it.

        The clock steps with the write (`stepping_with_the_write`), so this holds at the
        shortened sweep however long the write takes to land."""
        with self.stepping_with_the_write():
            response = self.listen()
            self.assertTrue(self.until(lambda: self.events.HUB.count() == 1))
            with mock.patch.object(deckstate.harness, "agents_across", return_value=self.rows()):
                self.fetch("/api/action", data=json.dumps(
                    {"verb": "note", "id": self.inbox, "text": "a real write"}).encode(), page=True)
            said = self.heard_for(response, 3.0)
        state = [line for line in said if line.startswith("state")]
        self.assertTrue(state, f"the write said nothing: {said}")
        self.assertTrue(state[0].endswith(".101"), f"the state line is behind the clock: {state}")
        self.assertEqual([line for line in said if line.startswith("tick")], [],
                         f"the clock was said twice: {said}")

    def keep_churning(self, seconds: float | None = None) -> None:
        """A board opened and closed over and over, which is what a deck under use does.

        It is what used to make the revision oscillate: the last connection to close takes
        the write-ahead log with it and the next one puts it back, and the revision was
        reading that file's mtime.
        """
        stop = time.time() + (seconds or self.HEAR + 0.5)
        while time.time() < stop:
            Board(self.cfg.db_path).close()
            time.sleep(0.01)

class BurstTest(ServerCase):
    def test_a_page_load_of_many_files_at_once_is_never_refused(self):
        """The shell loads some 25 files at once, and `tailscale serve` opens a connection
        for each. With socketserver's default backlog of 5 macOS reset the rest, which the
        proxy answered 502: a blank deck on his phone (his Mac, 2026-10-03)."""
        barrier, failed = threading.Barrier(48), []

        def one():
            barrier.wait()
            try:
                with socket.create_connection(self.server.server_address[:2], timeout=10) as conn:
                    conn.sendall(b"GET /ui.core.js HTTP/1.0\r\nHost: x\r\n\r\n")
                    if not conn.recv(12).startswith(b"HTTP/1.0 200"):
                        failed.append("not 200")
            except OSError as error:
                failed.append(type(error).__name__)

        threads = [threading.Thread(target=one) for _ in range(48)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(30)
        self.assertEqual(failed, [])


class FollowCodeTest(unittest.TestCase):
    """The deck follows its checkout (c-637). 2026-10-04: a deploy fast-forwarded main, the
    drain re-exec'd, the deck kept the old server, and it sent c-634's new page unfilled: no
    script, a blank deck, until it was restarted by hand."""

    def test_it_waits_while_a_deck_action_is_in_flight_then_restarts_once(self):
        """The real wait (`restart.busy`), not a scripted one: a clone under a deck action
        holds the exec until it ends (c-637 review F2), and the drain's own once-per-reason
        line is left alone (F3)."""
        heads = iter(["a", None, "b"])
        restarted, release = [], threading.Event()

        def action():
            with serve.restart.CALLS.held(serve.restart.DECK_ACTION):
                release.wait(5)
        worker = threading.Thread(target=action)
        worker.start()
        while not serve.restart.busy():
            time.sleep(0.01)
        waits = []

        def sleep(seconds):
            waits.append(seconds)
            if len(waits) == 5:
                self.assertEqual(restarted, [], "nothing restarts while the action runs")
                release.set()
                worker.join(5)
        before = dict(serve.restart._state)
        with contextlib.redirect_stderr(io.StringIO()) as said:
            serve.follow_code(Path("/x"), "a", head=lambda root: next(heads),
                              restart_fn=lambda: restarted.append(1), sleep=sleep)
        self.assertEqual(restarted, [1])
        self.assertEqual(said.getvalue().count("the restart waits: a deck action in flight"), 1)
        self.assertEqual(serve.restart._state, before, "the drain's restart state is untouched")

    def test_with_the_drain_in_its_process_the_deck_leaves_the_restart_to_it(self):
        """An install's default runs drain,serve,fetch in one process: one restart, the
        drain's between passes, never the deck's mid-pass (c-637 review F1)."""
        from keel import cli
        seen = {}
        with mock.patch.object(cli.serve, "run", side_effect=lambda cfg, port=None, follow=True: seen.update(follow=follow)), \
                mock.patch.dict(cli.RUNNERS, {"drain": lambda cfg: None, "fetch": lambda cfg: None}):
            cfg = mock.Mock(remote=False)
            cli.role_run(cfg, mock.Mock(roles="serve,drain"))
            self.assertEqual(seen, {"follow": False})
            cli.role_run(cfg, mock.Mock(roles="serve,fetch"))
            self.assertEqual(seen, {"follow": True})
            cli.role_serve(cfg, mock.Mock(port=None))
            self.assertEqual(seen, {"follow": True})

    def test_a_running_deck_restarts_onto_its_checkouts_new_head(self):
        """End to end, as the deploy does it: a real deck on a checkout, the checkout moves,
        and /api/health's serve_head follows within seconds."""
        # Removed after the deck is killed and waited for (cleanups run newest first), and
        # the deck writes nothing into the copy (`code/`) meanwhile (c-662): a deck still
        # importing wrote bytecode there, and the import system makes a removed folder
        # again, so the folder was "not empty" under its removal. Its stderr file sits
        # beside the copy (c-670) and is closed after the deck is killed and waited for,
        # before the dir goes. The deck stays in the runner's process group, which is what
        # the suite's timeout kills.
        tmp = self.enterContext(tempfile.TemporaryDirectory())
        code, home = Path(tmp) / "code", Path(tmp) / "home"
        for name in sh_lines(CHECKOUT, "git", "ls-files"):
            if (CHECKOUT / name).is_file():
                (code / name).parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(CHECKOUT / name, code / name)
        commit = ["git", "-c", "user.name=t", "-c", "user.email=t@example.com", "commit", "-q"]
        subprocess.run(["git", "init", "-q"], cwd=code, check=True)
        subprocess.run(["git", "add", "-A"], cwd=code, check=True)
        subprocess.run([*commit, "-m", "loaded"], cwd=code, check=True)
        from tests.test_installer import init
        with mock.patch.dict(os.environ):
            for key in ("KEEL_HOME", "KEEL_CONFIG", "KEEL_URL", "KEEL_CARD", "KEEL_BOSUN"):
                os.environ.pop(key, None)
            self.assertEqual(init(home), 0)
        port = free_port()
        env = {k: v for k, v in os.environ.items() if not k.startswith("KEEL_")}
        # the exec onto the moved head keeps the environment, so neither deck compiles to disk
        env.update(KEEL_HOME=str(code), KEEL_CONFIG=str(home / "config.toml"), PYTHONDONTWRITEBYTECODE="1")
        # What the deck says goes to a file beside the copy, not into it, and the exec keeps
        # the descriptor: a wait that fails reads it back (c-670).
        said = self.enterContext(open(Path(tmp) / "deck.stderr", "wb"))
        deck = subprocess.Popen([sys.executable, str(code / "bin" / "keel"), "serve", "--port", str(port)],
                                cwd=code, env=env, stdout=subprocess.DEVNULL, stderr=said)
        self.addCleanup(deck.wait)
        self.addCleanup(deck.kill)
        watch = DeckWatch(deck, port, code, Path(said.name))
        loaded = sh_lines(code, "git", "rev-parse", "HEAD")[0]
        if not watch.until(loaded):
            self.fail(watch.why("the deck came up on its checkout's head", loaded))
        subprocess.run([*commit, "--allow-empty", "-m", "moved"], cwd=code, check=True)
        moved = sh_lines(code, "git", "rev-parse", "HEAD")[0]
        if not watch.until(moved, 15):
            self.fail(watch.why("the deck restarted onto the moved head", moved))
        self.assertIsNone(deck.poll(), "the same process, re-exec'd, still serving")
        self.assertEqual([str(path.relative_to(code)) for path in code.rglob("__pycache__")], [],
                         "neither deck wrote bytecode into the checkout")


CHECKOUT = Path(__file__).resolve().parent.parent


class DeckWatch:
    """A real deck a test started, asked for the head it serves, and what to say when it
    never serves the one waited for (c-670). The restart test refused two landings on
    2026-10-06 and passed on both retries, with the deck's stderr sent nowhere: nothing said
    whether the deck had died, had not come back up yet, or was up on another head."""

    TAIL_LINES = 40

    def __init__(self, deck: subprocess.Popen, port: int, code: Path, stderr: Path):
        self.deck, self.port, self.code, self.stderr = deck, port, code, stderr
        self.began = time.monotonic()
        self.answers: list[list] = []       # [seconds since the start, the answer, how many times running]

    def served(self) -> str | None:
        """The `serve_head` /api/health gives, or None when it gave none. The exec cuts
        whatever answer is on the wire, and a reply cut short is `IncompleteRead`: an
        `HTTPException`, which is no `OSError` (c-662)."""
        head = None
        try:
            with urllib.request.urlopen(f"http://127.0.0.1:{self.port}/api/health", timeout=2) as reply:
                head = json.loads(reply.read()).get("serve_head")
            answer = f"serve_head {head}"
        except (OSError, ValueError, http.client.HTTPException) as error:
            answer = f"no answer, {type(error).__name__}: {error}"
        if self.answers and self.answers[-1][1] == answer:
            self.answers[-1][2] += 1
        else:
            self.answers.append([time.monotonic() - self.began, answer, 1])
        return head

    def until(self, want: str, seconds: float = 30) -> bool:
        deadline = time.monotonic() + seconds
        while time.monotonic() < deadline:
            if self.served() == want:
                return True
            time.sleep(0.2)
        return False

    def why(self, claim: str, want: str) -> str:
        """The failure message: the claim that did not hold, then the deck's side of it."""
        status = self.deck.poll()
        try:
            on = sh_lines(self.code, "git", "rev-parse", "HEAD")[0]
        except (OSError, subprocess.CalledProcessError, IndexError) as error:
            on = f"unreadable ({type(error).__name__})"
        try:
            lines = self.stderr.read_text(errors="replace").splitlines()
        except OSError as error:
            lines = [f"unreadable ({type(error).__name__}: {error})"]
        asked = [f"    at {at:5.1f}s, {times} time(s): {answer}" for at, answer, times in self.answers[-8:]]
        return "\n".join([
            claim,
            f"  waited for serve_head {want}",
            f"  the copy is on {on}",
            f"  the deck process (pid {self.deck.pid}): "
            + ("alive" if status is None else f"exited with {status}"),
            f"  /api/health on port {self.port}, last answer: "
            + (self.answers[-1][1] if self.answers else "never asked"),
            "  its answers, oldest first (the last 8 runs of one answer):", *asked,
            f"  the deck's stderr (the last {self.TAIL_LINES} of {len(lines)} lines):",
            *(f"    {line}" for line in lines[-self.TAIL_LINES:])])


class DeckWatchTest(unittest.TestCase):
    """`DeckWatch.why` runs only when the restart test's wait fails, so nothing else would
    notice it break: it would then raise in place of the failure it was to explain."""

    def test_the_message_names_a_dead_deck_no_answer_and_an_unreadable_stderr(self):
        tmp = Path(self.enterContext(tempfile.TemporaryDirectory()))
        deck = subprocess.Popen([sys.executable, "-c", "raise SystemExit(3)"])
        deck.wait()
        # No network: nothing connects to the port, so no other job of the suite can answer
        # on it, and the refusal is the one a deck that is away gives.
        watch = DeckWatch(deck, 1, tmp, tmp / "no-such-stderr")
        refused = urllib.error.URLError(ConnectionRefusedError(61, "Connection refused"))
        with mock.patch.object(urllib.request, "urlopen", side_effect=refused) as asked:
            self.assertIsNone(watch.served())
        asked.assert_called_once()
        message = watch.why("the deck came up", "a" * 40)
        self.assertTrue(message.startswith("the deck came up\n"), message)
        self.assertIn(f"waited for serve_head {'a' * 40}", message)
        self.assertIn(f"the deck process (pid {deck.pid}): exited with 3", message)
        self.assertIn("last answer: no answer, URLError", message)
        self.assertIn("1 time(s): no answer, URLError", message)
        self.assertIn("unreadable (FileNotFoundError", message)


class ActionHeldTest(ServerCase):
    """An action is held as `restart.DECK_ACTION` from its body to its reply, so a
    code-moved exec never leaves the page without its answer (c-637 review r2.F1)."""

    def test_the_reply_goes_out_while_the_action_is_still_held(self):
        seen = []
        reply = serve.Handler.reply_json

        def watched(handler, status, body, *args, **kwargs):
            seen.append(serve.restart.busy())
            return reply(handler, status, body, *args, **kwargs)
        body = {"verb": "show", "id": self.live}
        with mock.patch.object(serve.Handler, "reply_json", autospec=True, side_effect=watched):
            status, _, raw = self.fetch("/api/action", data=json.dumps(body).encode(), method="POST",
                                        page=True)
        self.assertEqual(status, 200, raw)
        self.assertIn("a deck action in flight", seen[-1])
        # released as the request thread leaves its `with`, which can be just after the client
        # has the reply: on a loaded box (the land's merged-tree run) the client reads first
        deadline = time.monotonic() + 5
        while serve.restart.busy() and time.monotonic() < deadline:
            time.sleep(0.01)
        self.assertEqual(serve.restart.busy(), "", "and released once answered")


def sh_lines(cwd: Path, *argv: str) -> list[str]:
    return subprocess.run(argv, cwd=cwd, capture_output=True, text=True, check=True).stdout.splitlines()
