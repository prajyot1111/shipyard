"""kb verbs through `keel.cli.main`: actor rule, approve refusals, hook stdin, launchers."""

import io
import json
import os
import re
import subprocess
import sys
from contextlib import redirect_stderr, redirect_stdout
from datetime import datetime, timedelta
from pathlib import Path
from unittest import mock

from keel import actions
from keel import board as board_module
from keel import cli
from tests.helpers import CliCase, own_options

ROOT = Path(__file__).resolve().parent.parent


class KbCase(CliCase):
    def kb(self, *argv, stdin=None, env=None):
        """Run a verb in-process; returns (exit code, stdout, stderr)."""
        out, err = io.StringIO(), io.StringIO()
        saved_stdin, saved_env = sys.stdin, {k: os.environ.get(k) for k in (env or {})}
        os.environ.update(env or {})
        sys.stdin = io.StringIO(stdin) if stdin is not None else None
        try:
            with redirect_stdout(out), redirect_stderr(err):
                code = cli.main(list(argv))
        finally:
            sys.stdin = saved_stdin
            for key, value in saved_env.items():
                os.environ.pop(key, None) if value is None else os.environ.__setitem__(key, value)
        return code, out.getvalue().strip(), err.getvalue().strip()

    def kb_json(self, *argv, **kwargs):
        code, out, err = self.kb(*argv, "--json", **kwargs)
        self.assertEqual(code, 0, err)
        return json.loads(out)

    def create(self, *extra):
        code, out, err = self.kb("create", "--space", "personal", "--title", "t", *extra)
        self.assertEqual(code, 0, err)
        return out


class ActorTest(KbCase):
    def test_token_is_created_on_first_use_with_0600(self):
        self.create()
        path = self.dir / "state" / "human.token"
        self.assertTrue(path.exists())
        self.assertEqual(oct(path.stat().st_mode & 0o777), "0o600")
        self.assertGreaterEqual(len(self.token), 32)

    def test_actor_defaults(self):
        card_id = self.create()
        self.kb("note", card_id, "from cli")
        self.kb("note", card_id, "from house", env={"KEEL_CARD": card_id})
        self.kb("note", card_id, "from human", env={"KEEL_TOKEN": self.token})
        self.kb("note", card_id, "wrong token", env={"KEEL_TOKEN": "nope"})
        events = self.kb_json("show", card_id)["events"]
        self.assertEqual([e["actor"] for e in events if e["kind"] == "note"],
                         ["cli", "house", "human", "cli"])

    def test_card_env_wins_over_token(self):
        card_id = self.create()
        self.kb("note", card_id, "x", env={"KEEL_CARD": card_id, "KEEL_TOKEN": self.token})
        self.assertEqual(self.kb_json("show", card_id)["events"][-1]["actor"], "house")


class TopicTest(KbCase):
    def test_topic_through_create_set_and_list(self):
        first = self.create("--topic", "deck")
        second = self.create()
        self.assertEqual(self.kb_json("show", first)["topic"], "deck")
        self.kb("set", second, "topic=deck")
        listed = self.kb_json("list", "--topic", "deck")
        self.assertEqual([c["id"] for c in listed], [first, second])
        self.kb("set", second, "topic=null")
        self.assertEqual([c["id"] for c in self.kb_json("list", "--topic", "deck")], [first])


class ApproveTest(KbCase):
    def planning_card(self):
        card_id = self.create("--autonomy", "attended")
        self.kb("stage", card_id, "planning", "--plan", "/plans/plan.md")
        return card_id

    def test_approve_refuses_every_actor_but_human(self):
        card_id = self.planning_card()
        for env in ({}, {"KEEL_CARD": card_id}, {"KEEL_TOKEN": "wrong"}):
            code, _, err = self.kb("approve", card_id, "plan", env=env)
            self.assertEqual(code, 1, env)
            self.assertIn("human", err)
        code, out, _ = self.kb("approve", card_id, "plan", env={"KEEL_TOKEN": self.token})
        self.assertEqual(code, 0)
        self.assertIn("building", out)

    def test_said_is_recorded_as_a_note_because_kb_resumes_no_house(self):
        """The terminal's half of approve is the board's half, so `--said` can only be the
        record; the verb's help says so rather than letting it look like it reached a house."""
        card_id = self.planning_card()
        code, _, err = self.kb("approve", card_id, "plan", "--said", "question one: option two",
                               env={"KEEL_TOKEN": self.token})
        self.assertEqual(code, 0, err)
        events = self.kb_json("show", card_id)["events"]
        self.assertEqual([e["kind"] for e in events][-2:], ["approve", "note"])
        self.assertEqual(events[-1]["text"], "question one: option two")
        self.assertEqual(events[-1]["actor"], "human")
        code, out, _ = self.kb("help")
        self.assertIn("--said", out)

    def test_refusal_is_one_line_on_stderr(self):
        card_id = self.planning_card()
        code, out, err = self.kb("stage", card_id, "building")
        self.assertEqual((code, out), (1, ""))
        self.assertEqual(len(err.splitlines()), 1)


class PublishTest(KbCase):
    """`approve outcome` hands the space adapter's publish to the board (a fake adapter here)."""

    def fake_adapter(self, body: str) -> Path:
        path = self.dir / "adapters" / "work" / "publish"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("#!/bin/sh\n" + body + "\n")
        path.chmod(0o755)
        return path

    def review_card(self, space="work"):
        code, card_id, err = self.kb("create", "--space", space, "--title", "t", "--repo", "r")
        self.assertEqual(code, 0, err)
        self.kb("stage", card_id, "assigned")
        self.kb("stage", card_id, "building")
        self.kb("stage", card_id, "review", "--plan", "/plans/p.md", "--output", "https://example.invalid/pr/1")
        return card_id

    def test_outcome_runs_the_adapter_which_may_write_through_kb(self):
        self.fake_adapter('kb note "$1" "published by the fake adapter" >/dev/null; echo \'{"pr": 1, "draft": false}\'')
        card_id = self.review_card()
        code, out, err = self.kb("approve", card_id, "outcome", env={"KEEL_TOKEN": self.token})
        self.assertEqual(code, 0, err)
        self.assertIn("done", out)
        events = self.kb_json("show", card_id)["events"]
        self.assertEqual([e["kind"] for e in events][-2:], ["note", "approve"])
        self.assertEqual(events[-2]["text"], "published by the fake adapter")
        self.assertEqual(events[-1]["data"]["published"], '{"pr": 1, "draft": false}')

    def test_outcome_hands_the_adapter_the_nonce_of_the_marker_it_writes_and_clears_it(self):
        """c-738 r1.F3: Approve outcome marks the card as the user's Ship does (`mark_publishing`)
        and hands the pack's `publish` that tap's nonce, which it checks against the marker."""
        self.fake_adapter(
            "python3 -c 'import hashlib, json, os, subprocess, sys\n"
            "card = json.loads(subprocess.run([\"kb\", \"show\", sys.argv[1], \"--json\", \"--events\", \"0\"],"
            " capture_output=True, text=True).stdout)\n"
            "digest = ((card.get(\"options\") or {}).get(\"publishing\") or {}).get(\"digest\")\n"
            "nonce = os.environ.get(\"KEEL_PUBLISH_NONCE\", \"\")\n"
            "sys.exit(0 if nonce and digest == hashlib.sha256(nonce.encode()).hexdigest() else 3)' \"$1\""
            " && echo '{\"pr\": 1, \"draft\": false}'")
        card_id = self.review_card()
        code, out, err = self.kb("approve", card_id, "outcome", env={"KEEL_TOKEN": self.token})
        self.assertEqual(code, 0, err)
        self.assertIn("done", out)
        self.assertNotIn("publishing", self.kb_json("show", card_id).get("options") or {})

    def test_a_publish_that_outruns_the_deck_s_budget_is_stopped_and_its_marker_cleared(self):
        """c-738 r2.F3: the pack's `publish` gets the tap's budget (`merging.TAP_ENV`, which the
        deck sets below its own wait), so kb stops it and clears the marker itself rather than
        being killed with the marker left on the card."""
        self.fake_adapter("sleep 30; echo '{\"pr\": 1}'")
        card_id = self.review_card()
        code, _, err = self.kb("approve", card_id, "outcome", env={"KEEL_TOKEN": self.token, "KEEL_TAP_SECONDS": "1"})
        self.assertEqual(code, 1)
        self.assertIn("did not finish", err)
        shown = self.kb_json("show", card_id)
        self.assertEqual((shown["stage"], "publishing" in (shown.get("options") or {})), ("review", False))

    def test_a_failing_adapter_leaves_the_card_at_review(self):
        self.fake_adapter('echo "host said no" >&2; exit 1')
        card_id = self.review_card()
        code, _, err = self.kb("approve", card_id, "outcome", env={"KEEL_TOKEN": self.token})
        self.assertEqual(code, 1)
        self.assertIn("host said no", err)
        shown = self.kb_json("show", card_id)
        self.assertEqual(shown["stage"], "review")
        # c-738 r2.F4: no stage move dropped the marker here; only the tap's own clear did
        self.assertNotIn("publishing", shown.get("options") or {})

    def test_plan_gate_and_personal_space_never_call_the_adapter(self):
        self.fake_adapter('echo "must not run" >&2; exit 1')
        card_id = self.review_card(space="personal")
        code, out, err = self.kb("approve", card_id, "outcome", env={"KEEL_TOKEN": self.token})
        self.assertEqual((code, "done" in out), (0, True), err)
        code, out, _ = self.kb("create", "--space", "work", "--title", "t", "--autonomy", "attended")
        self.kb("stage", out, "assigned")
        self.kb("stage", out, "planning", "--plan", "/plans/p.md")
        code, out2, err = self.kb("approve", out, "plan", env={"KEEL_TOKEN": self.token})
        self.assertEqual((code, "building" in out2), (0, True), err)


class VerbsTest(KbCase):
    def test_create_options_set_and_show(self):
        card_id = self.create("--option", "plan_style=light", "--option", "rich_story=true")
        # c-718 r1.F2: a base is the owner's to change after create, so this set is the owner's
        self.kb("set", card_id, "model=opus", "options.base=main", "repo=null", env={"KEEL_TOKEN": self.token})
        card = self.kb_json("show", card_id)
        self.assertEqual(own_options(card), {"plan_style": "light", "rich_story": True, "base": "main"})
        self.assertEqual((card["model"], card["repo"]), ("opus", None))
        code, _, err = self.kb("set", card_id, "space=work")
        self.assertEqual(code, 1)
        self.assertIn("immutable", err)

    def test_unknown_space_is_refused(self):
        code, _, err = self.kb("create", "--space", "nowhere", "--title", "t")
        self.assertEqual(code, 1)
        self.assertIn("unknown space", err)

    def test_list_filters_and_needs_you(self):
        blocked = self.create()
        self.kb("block", blocked, "stuck")
        self.create()
        self.assertEqual(len(self.kb_json("list")), 2)
        self.assertEqual([c["id"] for c in self.kb_json("list", "--needs-you")], [blocked])
        self.assertEqual([c["id"] for c in self.kb_json("needs-you")], [blocked])
        self.kb("unblock", blocked)
        self.assertEqual(self.kb_json("needs-you"), [])

    def test_list_refuses_an_unknown_stage(self):
        self.create()
        code, out, err = self.kb("list", "--stage", "bogus")
        self.assertEqual((code, out), (1, ""))
        self.assertEqual(len(err.splitlines()), 1)
        self.assertIn("unknown stage bogus", err)
        self.assertEqual(len(self.kb_json("list", "--stage", "inbox")), 1)

    def test_show_events_keeps_the_last_n(self):
        card_id = self.create()
        for n in range(20):
            self.kb("note", card_id, f"note {n}")
        notes = lambda card: [e["text"] for e in card["events"]]
        self.assertEqual(notes(self.kb_json("show", card_id)), [f"note {n}" for n in range(8, 20)])
        self.assertEqual(notes(self.kb_json("show", card_id, "--events", "3")), ["note 17", "note 18", "note 19"])
        self.assertEqual(len(self.kb_json("show", card_id, "--events", "0")["events"]), 21)
        code, out, _ = self.kb("show", card_id, "--events", "2")
        self.assertEqual(code, 0)
        self.assertNotIn("note 17", out)
        self.assertIn("note 18", out)
        self.assertIn("note 19", out)
        code, out, err = self.kb("show", card_id, "--events", "-1")
        self.assertEqual((code, out), (1, ""))
        self.assertEqual(len(err.splitlines()), 1)

    def test_list_limit_keeps_the_first_n_after_filters(self):
        ids = [self.create() for _ in range(4)]
        self.kb("block", ids[1], "stuck")
        self.kb("block", ids[3], "stuck")
        listed = lambda *argv: [c["id"] for c in self.kb_json("list", *argv)]
        self.assertEqual(listed("--limit", "2"), ids[:2])
        self.assertEqual(listed("--limit", "0"), ids)
        self.assertEqual(listed("--limit", "9"), ids)
        self.assertEqual(listed("--needs-you", "--limit", "1"), [ids[1]])
        code, out, _ = self.kb("list", "--limit", "1")
        self.assertEqual((code, out.count("\n")), (0, 0))
        self.assertTrue(out.startswith(ids[0]))
        code, out, err = self.kb("list", "--limit", "-2")
        self.assertEqual((code, out), (1, ""))
        self.assertIn("card limit", err)

    def test_split_and_session(self):
        parent = self.create()
        code, out, _ = self.kb("split", parent, "--slice", "A|do a", "--slice", "B|do b|A")
        self.assertEqual(code, 0)
        a, b = out.splitlines()
        self.assertEqual(self.kb_json("show", b)["after"], a)
        self.assertEqual(self.kb_json("show", parent)["derived"]["parent_stage"], "building")
        card = self.kb_json("session", a, "--set", "u-1", "--transcript", "/t.jsonl", "--bg-id", "0abc1234")
        self.assertEqual(card["session_id"], "u-1")
        self.assertEqual(self.kb_json("show", a)["events"][-1]["data"]["bg_id"], "0abc1234")

    def test_a_slice_names_its_own_repos(self):
        """c-771: `repo=` on a `--slice`; the slice without one takes the parent's."""
        code, parent, err = self.kb("create", "--space", "work", "--title", "p", "--repo", "api,r")
        self.assertEqual(code, 0, err)
        code, out, err = self.kb("split", parent, "--slice", "A|do a|repo=api", "--slice", "B|do b|A",
                                 "--slice", "C|do c|repo= r , api|A", "--json")
        self.assertEqual(code, 0, err)
        a, b, c = json.loads(out)
        self.assertEqual([(one["repo"], one["options"]["provenance"]["repo"]) for one in (a, b, c)],
                         [("api", "stated"), ("api,r", "inherited"), ("api,r", "stated")])      # the parent's order
        self.assertEqual((b["after"], c["after"]), (a["id"], a["id"]))
        self.assertNotRegex(a["readback"], r"repo\b[^()]*inherited from")
        self.assertRegex(b["readback"], r"repo\b[^()]*inherited from " + parent)

    def test_a_slice_repo_the_space_or_the_parent_does_not_name_refuses_the_split(self):
        _, parent, _ = self.kb("create", "--space", "work", "--title", "p", "--repo", "api")
        for part, said in (("repo=nowhere", "nowhere is not a repo the work space can open (api, r)"),
                           ("repo=r", f"slice 'B': r is not a repo of {parent} (api)"),
                           ("repo=", "slice 'B': repo= names no repo")):
            with self.subTest(part=part):
                code, out, err = self.kb("split", parent, "--slice", "A|a", "--slice", "B|b|" + part)
                self.assertEqual((code, out), (1, ""))
                self.assertIn(said, err)
                self.assertTrue(err.startswith("kb: slice 'B': "), err)
        self.assertEqual(self.kb_json("show", parent)["derived"]["tracking"], False)

    def test_only_a_part_after_the_brief_that_is_no_earlier_title_is_read_as_repo(self):
        """c-771: a title and a brief are never read, and an after-title that is an earlier
        slice's exact title is that slice, whatever it spells."""
        parse = cli.parse_slice
        self.assertEqual(parse("repo=api|stack=stacked"), {"title": "repo=api", "brief": "stack=stacked"})
        self.assertEqual(parse("B|set a=b|repo=api|x=y", ["repo=api", "x=y"]),
                         {"title": "B", "brief": "set a=b", "after": ["repo=api", "x=y"]})
        self.assertEqual(parse("B|b|x=y|repo=api|stack=independent|repo=r", ["stack=independent"]),
                         {"title": "B", "brief": "b", "after": ["x=y", "stack=independent"], "repo": "r"})
        self.assertEqual(parse("B|b|Repo=api|repo api"), {"title": "B", "brief": "b",
                                                          "after": ["Repo=api", "repo api"]})
        _, parent, _ = self.kb("create", "--space", "work", "--title", "p", "--repo", "api,r")
        code, out, err = self.kb("split", parent, "--slice", "repo=r|repo=r", "--slice", "B|b|repo=r",
                                 "--slice", "C|c|repo=api", "--json")
        self.assertEqual(code, 0, err)
        first, second, third = json.loads(out)
        self.assertEqual((first["title"], first["brief"], first["repo"]), ("repo=r", "repo=r", "api,r"))
        self.assertEqual((second["after"], second["repo"]), (first["id"], "api,r"))
        self.assertEqual((third["after"], third["repo"]), (None, "api"))


class NewProjectFlagTest(KbCase):
    """`--new-project <name>` is the one place what a new project card IS is decided: the
    repo, the option placement reads, and the autonomy a first card gets."""

    def test_it_sets_the_repo_the_option_and_attended_by_default(self):
        card = self.kb_json("create", "--space", "personal", "--title", "a new thing",
                            "--new-project", "smoke")
        self.assertEqual(card["repo"], "smoke")
        self.assertIs(card["options"]["new_project"], True)
        self.assertEqual(card["autonomy"], "attended")

    def test_an_explicit_autonomy_still_wins(self):
        card = self.kb_json("create", "--space", "personal", "--title", "a new thing",
                            "--new-project", "smoke", "--autonomy", "autonomous")
        self.assertEqual(card["autonomy"], "autonomous")

    def test_an_ordinary_card_is_autonomous_and_carries_no_option(self):
        card = self.kb_json("create", "--space", "personal", "--title", "a card")
        self.assertEqual((card["autonomy"], card["repo"]), ("autonomous", None))
        self.assertNotIn("new_project", card["options"])

    def test_a_repo_and_a_new_project_together_are_refused(self):
        code, _, err = self.kb("create", "--space", "personal", "--title", "x",
                               "--repo", "keel", "--new-project", "smoke")
        self.assertEqual(code, 1)
        self.assertIn("give --repo or --new-project, not both", err)

    def test_the_deck_sends_the_name_and_kb_decides_what_it_means(self):
        """`actions.create_argv` passes the sheet's field through as the flag, so the deck
        never has to know that a new project is a repo plus an option."""
        argv = actions.create_argv({"space": "personal", "title": "x", "new_project": "smoke"})
        self.assertIn("--new-project", argv)
        self.assertEqual(argv[argv.index("--new-project") + 1], "smoke")
        self.assertNotIn("--new_project", argv)


class HookStdinTest(KbCase):
    def building_card(self):
        card_id = self.create("--repo", "keel")
        self.kb("stage", card_id, "building")
        return card_id

    def test_event_reads_json_and_survives_empty_stdin(self):
        card_id = self.building_card()
        payload = {"session_id": "s", "transcript_path": "/t", "reason": "other"}
        code, _, _ = self.kb("event", card_id, "--hook", "SessionEnd", stdin=json.dumps(payload))
        self.assertEqual(code, 0)
        code, _, _ = self.kb("event", card_id, "--hook", "Notification", stdin="")
        self.assertEqual(code, 0)
        code, _, _ = self.kb("event", card_id, "--hook", "Stop")
        self.assertEqual(code, 0)
        events = [e for e in self.kb_json("show", card_id)["events"] if e["kind"] == "hook"]
        self.assertEqual([e["data"]["hook"] for e in events], ["SessionEnd", "Notification", "Stop"])
        self.assertEqual(events[0]["data"]["transcript_path"], "/t")

    def test_stop_check_prints_decision_twice_then_nothing(self):
        card_id = self.building_card()
        outs = [self.kb("stop-check", card_id, stdin=s)[1] for s in ('{"hook_event_name": "Stop"}', "", None)]
        self.assertEqual(json.loads(outs[0])["decision"], "block")
        self.assertEqual(json.loads(outs[1])["decision"], "block")
        self.assertEqual(outs[2], "")
        self.assertIsNotNone(self.kb_json("show", card_id)["blocked_reason"])


class ResolveActorTest(CliCase):
    """Who a `kb` says it is. `KEEL_CARD` is the harness's own mark on a house's shell."""

    def test_a_house_is_a_house_whatever_it_puts_on_the_line(self):
        """`--actor` is not a way out of being a house: without this, a house could write
        the fields its actor is refused (`board.HOLD_ACTORS`) by naming another one."""
        os.environ["KEEL_CARD"] = "c-001"
        self.addCleanup(os.environ.pop, "KEEL_CARD", None)
        self.assertEqual(cli.resolve_actor(None, self.dir / "token"), "house")
        self.assertEqual(cli.resolve_actor("house", self.dir / "token"), "house")
        for claimed in ("voice", "drain", "cli"):
            with self.assertRaises(board_module.Refused):
                cli.resolve_actor(claimed, self.dir / "token")

    def test_the_gateway_is_still_voice(self):
        """The voice gateway carries no KEEL_CARD, and capture, the refine and the connected
        turn all write as `voice`."""
        os.environ.pop("KEEL_CARD", None)
        self.assertEqual(cli.resolve_actor("voice", self.dir / "token"), "voice")


class LauncherTest(CliCase):
    def launch(self, *argv):
        return subprocess.run([sys.executable, *argv], cwd=ROOT, capture_output=True, text=True,
                              env=dict(os.environ))

    def test_bin_kb_and_bin_keel(self):
        result = self.launch(ROOT / "bin" / "kb", "create", "--space", "personal", "--title", "via launcher")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.strip(), "c-001")
        result = self.launch(ROOT / "bin" / "keel", "kb", "list")
        self.assertIn("via launcher", result.stdout)
        result = self.launch(ROOT / "bin" / "keel", "show", "c-001")
        self.assertEqual(result.returncode, 0)

    def test_an_unknown_word_falls_through_to_kb(self):
        # "deck" was the unknown word here until `keel deck` became a verb, so this needs
        # a word that is still not one.
        result = self.launch(ROOT / "bin" / "keel", "wharf")
        self.assertEqual(result.returncode, 2)
        self.assertIn("invalid choice: 'wharf'", result.stderr)

    def test_keel_converse_reaches_its_own_module_and_speaks_its_refusal(self):
        """`converse` is a peer of `talker` and `voice`, not a `kb` row, and every refusal
        it makes is a sentence: whoever ran it is holding a microphone open."""
        self.launch(ROOT / "bin" / "kb", "create", "--space", "personal", "--title", "no house")
        result = self.launch(ROOT / "bin" / "keel", "converse", "c-001", "how far are you?")
        self.assertEqual(result.returncode, 1)
        self.assertIn("no house session yet", result.stdout)

    def test_drain_once_prints_one_summary_line(self):
        result = self.launch(ROOT / "bin" / "keel", "drain", "--once")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertRegex(result.stdout.strip(), r"^drain: houses=\d+ reviews=\d+ resumed=0 blocked=0 started=0 paused=False$")
        log = (self.dir / "state" / "logs" / "drain.log").read_text()
        self.assertIn("(once)", log)

    def test_run_refuses_without_drain_and_install_writes_only(self):
        result = self.launch(ROOT / "bin" / "keel", "run", "--roles", "deck")
        self.assertEqual(result.returncode, 1)
        self.assertIn("unknown role", result.stderr)


class HelpTest(KbCase):
    """`kb help` is the house brief's source for what a house can do, so the shape it
    prints (`<verb> <usage>: <one sentence>`) and the table the cli dispatches on have to
    stay the same thing."""

    def dispatchable(self) -> list[str]:
        """The verb names argparse actually accepts, in the order the parser adds them."""
        parser = cli.build_parser()
        action = next(a for a in parser._actions if a.dest == "verb")
        return list(action.choices)

    def subparsers(self) -> dict:
        parser = cli.build_parser()
        return next(a for a in parser._actions if a.dest == "verb").choices

    def test_every_dispatchable_verb_has_a_line_and_every_line_names_a_real_verb(self):
        code, out, err = self.kb("help")
        self.assertEqual(code, 0, err)
        lines = out.splitlines()
        named = [line.split(":", 1)[0].split(" ")[0] for line in lines]
        self.assertEqual(named, self.dispatchable())


    def test_the_signature_says_whether_the_verb_takes_an_id(self):
        subparsers = self.subparsers()
        for verb in cli.VERBS:
            positionals = [a.dest for a in subparsers[verb.name]._actions if not a.option_strings]
            self.assertEqual("id" in positionals, verb.takes_id, verb.name)
            self.assertEqual(verb.signature.startswith("<id>"), verb.takes_id, verb.name)

    def test_the_usage_names_exactly_the_flags_the_parser_takes(self):
        subparsers = self.subparsers()
        for verb in cli.VERBS:
            flags = {flag for action in subparsers[verb.name]._actions
                     for flag in action.option_strings if flag.startswith("--")}
            self.assertEqual(set(re.findall(r"--[a-z-]+", verb.signature)),
                             flags - {"--json", "--help"}, verb.name)

    def test_help_for_one_verb_prints_its_full_usage(self):
        code, out, err = self.kb("help", "stage")
        self.assertEqual(code, 0, err)
        self.assertTrue(out.startswith("stage <id> <stage>"))
        self.assertIn("usage: kb stage", out)
        self.assertIn("--output OUTPUT", out)

    def test_an_unknown_verb_is_refused(self):
        code, _, err = self.kb("help", "sail")
        self.assertEqual(code, 1)
        self.assertIn("no verb 'sail'", err)

    def test_json_carries_the_verb_usage_and_summary(self):
        rows = self.kb_json("help")
        self.assertEqual([row["verb"] for row in rows], self.dispatchable())
        by_verb = {row["verb"]: row for row in rows}
        usage = "<id> <text> [--mark failed-resume|review-limit|human-stop|closed-idle|merged-end] [--bulk]"
        self.assertEqual(by_verb["note"]["usage"], usage)
        self.assertEqual(by_verb["note"]["line"],
                         f"note {usage}: " + by_verb["note"]["summary"])


class BacklogCliTest(KbCase):
    """`kb backlog`, and the two surfaces that hide a backlog card: `kb needs-you` and
    `kb list`."""

    def at_review(self, days_ago: float = 0) -> str:
        """A card at its outcome gate, staged there `days_ago` days back."""
        card_id = self.create()
        self.kb("stage", card_id, "assigned")
        self.kb("stage", card_id, "building")
        stamp = (datetime.now().astimezone() - timedelta(days=days_ago)).isoformat(timespec="seconds")
        with mock.patch.object(board_module, "now", return_value=stamp):
            code, _, err = self.kb("stage", card_id, "review", "--plan", "/plans/p.md", "--output", "o")
        self.assertEqual(code, 0, err)
        return card_id


    def test_needs_you_hides_a_backlog_card_until_asked(self):
        old, fresh = self.at_review(30), self.at_review()
        self.assertEqual([c["id"] for c in self.kb_json("needs-you")], [fresh])
        self.assertEqual([c["id"] for c in self.kb_json("needs-you", "--backlog")], [old, fresh])

    def test_list_filters_and_tags_the_backlog_cards(self):
        old, fresh = self.at_review(30), self.at_review()
        self.assertEqual([c["id"] for c in self.kb_json("list", "--backlog")], [old])
        lines = {line.split("  ")[0]: line for line in self.kb("list")[1].splitlines()}
        self.assertIn("[backlog]", lines[old])
        self.assertIn("[needs you]", lines[fresh])

    def test_the_verb_sets_and_clears_the_override(self):
        card_id = self.at_review(30)
        card = self.kb_json("backlog", card_id, "active")
        self.assertEqual(card["options"]["backlog"], "active")
        self.assertFalse(card["derived"]["backlog"])
        self.assertTrue(card["derived"]["needs_you"])
        card = self.kb_json("backlog", card_id)
        self.assertNotIn("backlog", card["options"])
        self.assertTrue(card["derived"]["backlog"])
        self.assertEqual([e["kind"] for e in self.kb_json("show", card_id)["events"]][-2:],
                         ["set", "set"])

    def test_the_verb_backlogs_a_fresh_card_outright(self):
        card_id = self.at_review()
        card = self.kb_json("backlog", card_id, "backlog")
        self.assertTrue(card["derived"]["backlog"])
        self.assertEqual(card["derived"]["backlog_override"], "backlog")
        self.assertEqual(self.kb_json("needs-you"), [])

    def test_an_unknown_value_is_refused(self):
        code, _, err = self.kb("backlog", self.at_review(), "later")
        self.assertEqual(code, 1)
        self.assertEqual(err, "kb: backlog takes one of backlog, active, auto, got 'later'")


class LinksCliTest(KbCase):
    """The two relations through `kb`: `--from` for a follow-up, `set parent=` to repair."""

    def test_create_from_prints_both_ends_and_carries_them_in_json(self):
        origin = self.create("--repo", "keel")
        follow_up = self.create("--from", origin)
        card = self.kb_json("show", follow_up)
        self.assertEqual(card["from"], origin)
        self.assertEqual(self.kb_json("show", origin)["derived"]["follow_ups"], [follow_up])
        self.assertIn(f"from: {origin}", self.kb("show", follow_up)[1])
        self.assertIn(f"follow-ups: {follow_up}", self.kb("show", origin)[1])

    def test_a_follow_up_does_not_make_the_origin_a_tracking_card(self):
        origin = self.create("--repo", "keel")
        self.kb("stage", origin, "assigned")
        self.kb("stage", origin, "building")
        self.create("--from", origin)
        code, _, err = self.kb("stage", origin, "review", "--plan", "/plans/p", "--output", "o")
        self.assertEqual(code, 0, err)
        self.assertEqual(self.kb_json("show", origin)["stage"], "review")

    def test_a_tracking_card_reads_as_one_in_list_and_show(self):
        """It printed the stage it borrows from its children, so `kb list` said `building`
        on a card whose own house had nothing left to do (c-277, 2026-09-20)."""
        parent = self.create("--repo", "keel")
        self.kb("stage", parent, "assigned")
        self.kb("stage", parent, "building")
        self.kb("split", parent, "--slice", "A", "--slice", "B")
        line = [row for row in self.kb("list")[1].splitlines() if row.startswith(parent)][0]
        self.assertIn(" tracking ", line)
        self.assertNotIn(" building ", line)
        self.assertIn("[tracking: 2 of 2 waiting]", line)
        shown = self.kb("show", parent)[1]
        self.assertIn("[tracking: 2 of 2 waiting]", shown)
        self.assertIn("stage: building (its own", shown)

    def test_set_moves_and_clears_both_relations(self):
        parent, origin = self.create(), self.create()
        card_id = self.create("--parent", parent, "--from", origin)
        self.kb("set", card_id, "parent=", "from=")
        card = self.kb_json("show", card_id)
        self.assertEqual((card["parent"], card["from"]), (None, None))
        self.assertNotIn("parent:", self.kb("show", card_id)[1])

    def test_create_under_a_worked_card_is_refused_and_says_what_to_use(self):
        origin = self.create("--repo", "keel")
        self.kb("stage", origin, "assigned")
        self.kb("stage", origin, "building")
        self.kb("session", origin, "--set", "0abc1234-0000-4000-8000-000000000009")
        code, out, err = self.kb("create", "--space", "personal", "--title", "t",
                                 "--parent", origin)
        self.assertEqual(code, 1)
        self.assertEqual(out, "")
        self.assertIn("--from", err)
        self.assertIn("kb split", err)


class ErrandNoticeTest(KbCase):
    """A card with no repo cannot change code, so `kb create` says so, on stderr."""

    def test_a_card_with_no_repo_says_it_is_an_errand_after_the_id(self):
        code, out, err = self.kb("create", "--space", "personal", "--title", "fix the thing")
        self.assertEqual(code, 0, err)
        self.assertEqual(out, "c-001")
        self.assertIn("errand", err)
        self.assertIn("--repo", err)

    def test_a_repo_card_and_a_new_project_say_only_the_readback(self):
        """No errand line: stderr is the create readback alone (`keel/cardspec.py`)."""
        said = self.kb("create", "--space", "personal", "--title", "t", "--repo", "keel")[2]
        self.assertEqual(said, "Filed c-001 in keel, opus (model Shipyard's default)")
        said = self.kb("create", "--space", "personal", "--title", "t", "--new-project", "smoke")[2]
        self.assertEqual(said.splitlines(), [
            "Filed c-002 in smoke, opus, attended (autonomy assumed; model Shipyard's default)"])

    def test_the_json_output_is_still_only_json(self):
        code, out, err = self.kb("create", "--space", "personal", "--title", "t", "--json")
        self.assertEqual(code, 0, err)
        self.assertEqual(json.loads(out)["id"], "c-001")
        self.assertIn("errand", err)


class ReposTest(KbCase):
    """`kb repos`: the read that answers "which repo", so nobody recites them."""

    def projects(self, *names) -> Path:
        directory = self.dir / "projects"
        for name in names:
            (directory / name / ".git").mkdir(parents=True)
        path = self.dir / "keel.toml"
        path.write_text(path.read_text().replace(
            "[spaces.personal.repos]", f'projects_dir = "{directory}"\n[spaces.personal.repos]'))
        return directory

    def test_it_lists_the_listed_repos_of_every_space(self):
        code, out, err = self.kb("repos")
        self.assertEqual(code, 0, err)
        self.assertEqual([line.split() for line in out.splitlines()],
                         [["personal", "keel"], ["personal", "other"], ["personal", "r"],
                          ["work", "api"], ["work", "r"]])

    def test_a_project_directory_is_a_repo_key_too_and_is_marked(self):
        self.projects("jev-bench", "smoke")
        out = self.kb("repos")[1]
        self.assertEqual([line.split()[1] for line in out.splitlines()],
                         ["keel", "other", "r", "jev-bench", "smoke", "api", "r"])
        self.assertIn("jev-bench  (project)", out)
        self.assertNotIn("keel  (project)", out)

    def test_json_carries_the_space_the_key_and_the_path(self):
        self.projects("jev-bench")
        rows = self.kb_json("repos", "--space", "personal")
        self.assertEqual(rows[0], {"space": "personal", "repo": "keel", "project": False,
                                   "path": str(Path("~/keel").expanduser())})
        self.assertEqual(rows[3]["repo"], "jev-bench")
        self.assertTrue(rows[3]["project"])

    def test_it_filters_by_space_and_refuses_an_unknown_one(self):
        self.assertEqual([row["repo"] for row in self.kb_json("repos", "--space", "work")], ["api", "r"])
        code, _, err = self.kb("repos", "--space", "nowhere")
        self.assertEqual(code, 1)
        self.assertIn("unknown space", err)

    def test_the_deck_and_a_remote_kb_build_the_same_argv(self):
        self.assertEqual(actions.kb_argv({"verb": "repos", "space": "work"}),
                         ["repos", "--space", "work"])
        self.assertEqual(actions.kb_argv({"verb": "repos"}), ["repos"])
        self.assertIn("repos", actions.READ_VERBS)
