"""What actor bosun may do, each rule a refusal in code (c-517 BO-4, c-522; `keel/authority.py`).

Every test here runs `kb` as Bosun, holding Bosun's key, with builder mode OFF, and is
refused where the design says Bosun may not act: a card created, a field of his changed, a
stage moved, a note written, a block lifted that Keel did not write, and every gate. The
key itself comes first: the flag without the key is not Bosun. Builder mode's own rules are
`tests/test_bosun_builder.py`; driving, grants and strikes are retired (c-593).
"""

import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from keel import authority
from keel.board import Board, Refused
from tests.test_console import ConsoleKbCase

PLAN = """---
kind: plan
card: {card}
title: A small thing
---
# {card} A small thing

A summary of the small thing, short enough for the contract.

## Goal

Do the small thing.

## Now

It is not done.

## Target

It is done.

## Proposal

Do it plainly.

## Decisions

> [!settled] The flag is named quiet
> The house settled it: it matches the other flags.

{decision}

## Risks

None: it is small.

## Out of scope

- Everything else.
"""

DECISION = """```decision D1
q: Which colour?
why: It shows on his deck.
option red: Red
  gets: warm
  cost: loud
option blue: Blue
  gets: calm
  cost: cold
rec: blue
because: calm reads better.
```"""


class BosunCase(ConsoleKbCase):
    def board(self) -> Board:
        board = Board(self.dir / "state" / "board.db")
        self.addCleanup(board.close)
        return board

    def as_bosun(self, *argv):
        return self.kb(*argv, env={"KEEL_BOSUN": self.bosun})

    def as_him(self, *argv):
        self.create() if not (self.dir / "state" / "human.token").exists() else None
        return self.kb(*argv, env={"KEEL_TOKEN": self.token})

    def refused(self, said: str, *argv, env=None):
        code, _, err = self.kb(*argv, env={"KEEL_BOSUN": self.bosun} if env is None else env)
        self.assertEqual(code, 1, f"{argv} was not refused")
        self.assertIn(said, err)
        return err

    def personal(self, title="t", parent=None) -> str:
        extra = ["--parent", parent] if parent else []
        code, out, err = self.as_him("create", "--space", "personal", "--title", title,
                                     "--autonomy", "attended", *extra)
        self.assertEqual(code, 0, err)
        return out

    def at_review(self, card: str) -> None:
        self.at_plan_gate(card)
        board = self.board()
        board.approve(card, "plan", "human")
        board.stage(card, "review", "human", output_ref="keel/branch")

    def at_plan_gate(self, card: str, decision: str = "") -> Path:
        path = self.dir / f"{card}-plan.md"
        path.write_text(PLAN.format(card=card, decision=decision))
        board = self.board()
        board.stage(card, "assigned", "human")
        board.stage(card, "planning", "human", plan_ref=str(path))
        return path


class KeyTest(BosunCase):
    def test_the_flag_without_the_key_is_not_bosun(self):
        card = self.create()
        self.refused("does not hold Bosun's key", "note", card, "hello", env={"KEEL_BOSUN": "1"})

    def test_the_key_is_bosun(self):
        card = self.create()
        code, _, err = self.as_bosun("block", card, "hello")
        self.assertEqual(code, 0, err)
        self.assertEqual(self.board().events(card)[-1]["actor"], "bosun")

    def test_no_shared_key_here_means_no_bosun(self):
        card = self.create()
        (self.dir / "home" / ".config" / "keel" / "credentials" / "house-key").unlink()
        self.refused("does not hold Bosun's key", "note", card, "hello")

    def test_the_key_is_derived_and_differs_by_shared_key(self):
        self.assertNotEqual(authority.key_of("a"), authority.key_of("b"))
        self.assertIsNone(authority.key_of(""))


class WriteTest(BosunCase):
    def test_bosun_files_no_card_with_builder_mode_off(self):
        self.refused("builder mode is off", "create", "--space", "personal", "--title", "x")
        self.refused("unknown space 'console'", "create", "--space", "console", "--title", "x")

    def test_bosun_changes_no_field_of_a_personal_card(self):
        card = self.personal()
        for field in ("title=new", "brief=new", "autonomy=autonomous", "options.archived=true"):
            with self.subTest(field=field):
                self.refused("Bosun changes no field", "set", card, field)

    def test_bosun_moves_no_personal_stage_and_splits_none(self):
        card = self.personal()
        self.refused("only personal cards in builder mode", "stage", card, "assigned")
        self.refused("splits only personal cards in builder mode", "split", card, "--slice", "a|b")

    def test_verbs_outside_its_list_are_refused(self):
        card = self.personal()
        for argv in (("backlog", card, "backlog"), ("relay", card, "resume", "--to", "box"),
                     ("assign", card), ("rereview", card)):
            with self.subTest(verb=argv[0]):
                self.refused("is not Bosun's", *argv)


    def test_a_block_anywhere_but_no_note_and_no_unblock(self):
        card = self.personal()
        self.assertEqual(self.as_bosun("block", card, "needs him")[0], 0)
        self.refused("writes no note on it", "note", card, "seen")
        self.refused("its block is his", "unblock", card)
        self.assertEqual(self.board().get(card)["blocked_reason"], "needs him")
        work = self.board().create("work", "w", actor="human")
        self.refused("writes no note on it", "note", work, "seen")

    def test_bosun_never_marks_its_own_block(self):
        """r-3: a marked block is the drain's and the review gate's record, so Bosun's own
        would read as Keel's; unmarked, it still goes through."""
        card = self.personal("m")
        for mark in ("failed-resume", "review-limit"):
            with self.subTest(mark=mark):
                self.refused("never marks", "block", card, "needs him", "--mark", mark)
        self.assertEqual(self.as_bosun("block", card, "needs him")[0], 0)


class GateTest(BosunCase):
    def test_every_gate_is_his_with_builder_mode_off(self):
        card = self.personal()
        self.at_plan_gate(card)
        self.refused("gates are the user's", "approve", card, "plan", "--checked", "x")
        self.assertEqual(self.board().get(card)["stage"], "planning")
        other = self.personal("o")
        self.at_review(other)
        self.refused("gates are the user's", "approve", other, "outcome", "--checked", "x")

    def test_a_work_gate_is_never_bosun_s(self):
        board = self.board()
        work = board.create("work", "w", autonomy="attended", actor="human")
        board.stage(work, "assigned", "human")
        self.refused("its gates are the user's", "approve", work, "plan", "--checked", "x")

    def test_his_approval_takes_no_checked(self):
        card = self.personal()
        self.at_plan_gate(card)
        self.refused("--checked is Bosun's", "approve", card, "plan", "--checked", "x",
                     env={"KEEL_TOKEN": self.token})


class GuardTest(BosunCase):
    def test_the_paths_it_guards(self):
        root = Path("/k")
        for path, hit in (("/k/bosun/memory/needs-you.md", "bosun/memory"),
                          ("/k/state/console/settings.json", "state/console"),
                          ("/k/keel/authority.py", "keel/authority.py"),
                          ("/k/keel/drain.py", None), ("/elsewhere/bosun/memory/x", None)):
            with self.subTest(path=path):
                self.assertEqual(authority.authority_hit(root, path), hit)

    def test_the_hook_refuses_a_write_to_its_authority(self):
        from keel import console
        cfg = type("C", (), {"root": Path("/k"), "bosun_builder": False})
        deny = console.guard_verdict(cfg, {"tool_name": "Edit",
                                           "tool_input": {"file_path": "/k/bosun/memory/authority.md"}})
        self.assertIn("personal card he approves", deny)
        for command in ("echo more >> bosun/memory/needs-you.md", "sed -i s/a/b/ keel/authority.py",
                        "echo x >| bosun/memory/x.md", 'echo x > ./"bosun/memory/x.md"',
                        "cd bosun/memory && echo x >> needs-you.md",
                        "p=bosun/memory/x.md; echo x > $p",
                        "rm -r state/console", "git checkout keel/console.py"):
            with self.subTest(command=command):
                self.assertTrue(console.guard_verdict(cfg, {"tool_name": "Bash",
                                                            "tool_input": {"command": command}}))
        for command in ("cat bosun/memory/authority.md", "git log keel/authority.py", "kb show c-1",
                        "cat bosun/memory/x.md 2>/dev/null"):
            with self.subTest(command=command):
                self.assertIsNone(console.guard_verdict(cfg, {"tool_name": "Bash",
                                                              "tool_input": {"command": command}}))

    def test_the_installs_memory_is_guarded_the_same_way(self):
        """c-722: Bosun's memory lives in the install, and its guard goes with it."""
        from keel import console
        root, install = Path("/k"), Path("/i")
        # r1.F2: the whole memory root, its git repo included
        for path in ("/i/memory/bosun/needs-you.md", "/i/memory/.git/hooks/pre-commit",
                     "/i/memory/talker/x.md", "/i/memory"):
            with self.subTest(path=path):
                self.assertEqual(authority.authority_hit(root, path, install), "memory")
        self.assertIsNone(authority.authority_hit(root, "/i/builder/memory/bosun/x.md", install),
                          "Bosun's own clone of it is where it builds")
        self.assertIsNone(authority.authority_hit(root, "/i/memory/bosun/x.md"), "no install, no guess")
        cfg = type("C", (), {"root": root, "install_home": install, "bosun_builder": False})
        for path in ("/i/memory/bosun/authority.md", "/i/memory/.git/config"):
            deny = console.guard_verdict(cfg, {"tool_name": "Write", "tool_input": {"file_path": path}})
            self.assertIn("is Bosun's own authority", deny)
        for command in ("echo x >> /i/memory/bosun/needs-you.md", "rm /i/memory/bosun/asks.md",
                        "cp /tmp/x /i/memory/bosun/x.md",
                        "git -C /i/memory reset --hard HEAD~3",
                        "git -C /i/memory checkout HEAD~1 -- bosun",
                        "git --git-dir=/i/memory/.git update-ref HEAD abc",
                        "rm -rf /i/memory", "mv /i/memory /tmp/old",
                        "cd /i/memory && echo x > bosun/identity.md",
                        "echo x > /i/memory/.git/hooks/post-commit"):
            with self.subTest(command=command):
                self.assertTrue(console.guard_verdict(cfg, {"tool_name": "Bash",
                                                            "tool_input": {"command": command}}))
        for command in ("cat /i/memory/bosun/asks.md", "git -C /i/memory log --oneline",
                        "echo x > /i/builder/memory/talker/x.md"):
            with self.subTest(command=command):
                self.assertIsNone(console.guard_verdict(cfg, {"tool_name": "Bash",
                                                              "tool_input": {"command": command}}))
        self.assertIn("Edit(//i/memory/**)", console.authority_deny(cfg))

    def test_a_cwd_relative_or_home_spelled_write_to_the_installs_memory_is_refused(self):
        """Fix check 2: the spellings the token match alone let through, relative to the
        session's working directory or through `$HOME`, are refused, and so is any write whose
        text names the memory path, with no exclusion by cwd or by spelling (c-723's lesson).
        A memory card's build steps in Bosun's clone pass: the editing tools on its files,
        and git with relative paths."""
        from unittest import mock
        from keel import console
        cfg = type("C", (), {"root": Path("/k"), "install_home": Path("/i"), "bosun_builder": False})

        def verdict(command, cwd=None):
            payload = {"tool_name": "Bash", "tool_input": {"command": command}}
            return console.guard_verdict(cfg, {**payload, **({"cwd": cwd} if cwd else {})})
        with mock.patch.dict(os.environ, {"HOME": "/i"}):
            for command, cwd in (("echo x > memory/bosun/identity.md", "/i"),
                                 ("cp /tmp/x memory/talker/x.md", "/i"),
                                 ("echo x >> $HOME/memory/bosun/needs-you.md", None),
                                 ("cp /tmp/x ${HOME}/memory/talker/x.md", None),
                                 ("rm -rf ~/memory", None),
                                 ("p=memory/bosun; echo x > $p/identity.md", "/tmp"),
                                 # the two forms the fix check named: no cwd, no spelling exempts
                                 ("cd /i && echo x > memory/bosun/identity.md", "/i/builder"),
                                 ("v=builder/memory/bosun; echo x > /i/${v#builder/}/x.md", "/i/builder"),
                                 # the accepted cost: an absolute spelling through the clone
                                 ("echo x > /i/builder/memory/bosun/identity.md", "/i/builder/memory")):
                with self.subTest(command=command, cwd=cwd):
                    self.assertTrue(verdict(command, cwd))
            clone = "/i/builder/memory"
            for command in ("git status", "git add -A", "git commit -m 'Bosun: a clearer needs-you list'",
                            "git checkout -- bosun/needs-you.md", "git restore talker/x.md",
                            "git diff -- bosun", "echo x > bosun/identity.md",
                            "git switch -c bosun/c-9-needs-you"):
                with self.subTest(command=command):
                    self.assertIsNone(verdict(command, clone))
            # A whole-directory relative checkout of `bosun` is refused in the clone too: Keel's
            # root is always a reading, and there `bosun` holds the checkout's own memory.
            self.assertTrue(verdict("git checkout -- bosun", clone))
        for path in ("/i/builder/memory/bosun/identity.md", "/i/builder/memory/talker/x.md"):
            with self.subTest(path=path):
                self.assertIsNone(console.guard_verdict(cfg, {"tool_name": "Edit",
                                                              "tool_input": {"file_path": path}}))

    def test_a_link_to_or_from_the_memory_is_refused(self):
        """r1.F10's link path: `ln` is a writing verb, so a command that makes a link naming
        the memory, as its target or as the link, is refused, on the install and in the
        checkout. A write through a link made elsewhere is the stated boundary (Atlas 96)."""
        from keel import console
        for install, commands in ((Path("/i"), ("ln -s /i/memory /tmp/m", "ln -s /i/memory/bosun /tmp/b",
                                                "ln -sf /tmp/evil /i/memory/talker/x.md",
                                                "ln /tmp/evil /i/memory/.git/hooks/post-commit",
                                                "ln -s ~/memory/talker /tmp/t")),
                                  (None, ("ln -s /k/bosun/memory /tmp/b", "ln -s /tmp/x bosun/memory/x.md",
                                          "ln -s /tmp/x bosun"))):
            cfg = type("C", (), {"root": Path("/k"), "install_home": install, "bosun_builder": False})
            for command in commands:
                with self.subTest(command=command), mock.patch.dict(os.environ, {"HOME": "/i"}):
                    self.assertTrue(console.guard_verdict(cfg, {"tool_name": "Bash",
                                                                "tool_input": {"command": command}}))

    def test_the_checkouts_memory_is_guarded_in_the_same_forms(self):
        """r1.F2: the forms that never spell `bosun/memory` are closed for the checkout's
        copy too: its directory removed, checked out over, or written from inside."""
        from keel import console
        cfg = type("C", (), {"root": Path("/k"), "install_home": None, "bosun_builder": False})
        for command in ("rm -rf bosun", "rm -rf /k/bosun", "git checkout HEAD~1 -- bosun",
                        "git -C /k restore bosun", "cd bosun && echo x >> memory/needs-you.md",
                        "mv bosun /tmp/b"):
            with self.subTest(command=command):
                self.assertTrue(console.guard_verdict(cfg, {"tool_name": "Bash",
                                                            "tool_input": {"command": command}}))
        for command in ("ls bosun", "git log -- bosun", "kb console status > /tmp/bosun.txt",
                        "echo bosun > /tmp/x"):
            with self.subTest(command=command):
                self.assertIsNone(console.guard_verdict(cfg, {"tool_name": "Bash",
                                                              "tool_input": {"command": command}}))

    def test_the_hook_answers_a_real_pre_tool_use_payload(self):
        import io
        from contextlib import redirect_stdout
        from unittest import mock
        from keel import console
        payload = {"session_id": "s", "hook_event_name": "PreToolUse", "tool_name": "Write",
                   "tool_input": {"file_path": str(Path(authority.__file__).resolve()),
                                  "content": "x"}}
        out = io.StringIO()
        with mock.patch.object(console.sys, "stdin", io.StringIO(json.dumps(payload))), \
                mock.patch.dict(os.environ, {"KEEL_BOSUN": self.bosun}), redirect_stdout(out):
            self.assertEqual(console.main(["guard"]), 0)
        answer = json.loads(out.getvalue())["hookSpecificOutput"]
        self.assertEqual((answer["hookEventName"], answer["permissionDecision"]), ("PreToolUse", "deny"))
        self.assertIn("keel/authority.py", answer["permissionDecisionReason"])


GOOD = {"integration": "next", "errors": [], "sha": "a" * 40, "trunk": "main", "reviewed": True}


class DeployVerbTest(BosunCase):
    """`kb console deploy` is his alone at the verb itself (c-526, review F11)."""

    def test_bosun_is_refused(self):
        self.refused("the user's alone", "console", "deploy")

    def test_voice_without_his_token_is_refused(self):
        code, _, err = self.kb("--actor", "voice", "console", "deploy")
        self.assertEqual(code, 1)
        self.assertIn("carries the user's token", err)

    def test_a_house_is_refused(self):
        card = self.create()
        code, _, err = self.kb("console", "deploy", env={"KEEL_CARD": card})
        self.assertEqual(code, 1)
        self.assertIn("the user's alone", err)


class OutcomeCheckTest(unittest.TestCase):
    """c-526: each check on Bosun's outcome approval, one refusal each."""

    def refusal(self, **change):
        return authority.outcome_refusal(dict(GOOD, **change))

    def test_all_holding_is_no_refusal(self):
        self.assertIsNone(self.refusal())

    def test_each_check_refuses(self):
        for change, said in (({"integration": None}, "no integration branch"),
                             ({"errors": ["C26 no Evidence"]}, "does not check clean"),
                             ({"trunk": "next"}, "the branch the machines run"),
                             ({"reviewed": False}, "no review stamp covers"),
                             ({"sha": None}, "no branch sha")):
            with self.subTest(change=change):
                self.assertIn(said, self.refusal(**change) or "")

class BosunRelayTest(unittest.TestCase):
    """c-648: the one relay Bosun writes is a `land` under its checked approval
    (`BosunLandsTest`). A resume, a start or a stop of a house is his tap, with builder
    mode off, on, and as the superuser alike."""

    def test_bosun_may_not_relay_a_resume_a_start_or_a_stop(self):
        for switches in (set(), {authority.BUILDER}, {authority.BUILDER, authority.SUPERUSER}):
            with tempfile.TemporaryDirectory() as tmp:
                board = Board(Path(tmp) / "board.db", switches=switches, builds={"keel"})
                try:
                    card = board.create("personal", "t", repo="keel", actor="human")
                    board.stage(card, "assigned", "human")
                    for what in ("resume", "start", "stop"):
                        with self.subTest(switches=sorted(switches), what=what):
                            with self.assertRaises(Refused) as caught:
                                board.relay(card, what, authority.BOSUN, "here")
                            self.assertIn("a relay is the human's tap", str(caught.exception))
                    self.assertEqual([e for e in board.events(card) if e["kind"] == "relay"], [])
                finally:
                    board.close()


class BosunLandsTest(unittest.TestCase):
    """Bosun's approved outcome is a `land` relay the drain carries, and `land` finishes it."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.board = Board(Path(self.tmp.name) / "board.db",
                           switches={"merge_queue", authority.BUILDER, authority.SUPERUSER},
                           builds={"keel"})
        self.addCleanup(self.board.close)
        self.card = self.board.create("personal", "t", repo="keel", actor="human",
                                      autonomy="autonomous")
        self.board.stage(self.card, "assigned", "human")
        self.board.stage(self.card, "building", "human", plan_ref="p.md")
        self.board.stage(self.card, "review", "human", output_ref="keel/b")

    def approve(self, facts=GOOD):
        return self.board.approve(self.card, "outcome", authority.BOSUN,
                                  bosun={"checked": "lint, review, risk", "to": "box", "facts": facts})

    def test_the_approval_is_a_signed_land_relay_and_lands_the_card(self):
        self.approve()
        relay = next(e for e in self.board.events(self.card) if e["kind"] == "relay")
        self.assertEqual((relay["actor"], relay["data"]["what"], relay["data"]["sha"]),
                         ("bosun", "land", GOOD["sha"]))
        note = [e["text"] for e in self.board.events(self.card) if e["kind"] == "note"][-1]
        self.assertIn("in builder mode", note)
        self.assertIn("lands on next", note)
        self.assertEqual(self.board.get(self.card)["stage"], "review", "nothing moves until it lands")
        self.board.carry(self.card, relay["id"], "drain")
        self.board.set_fields(self.card, {"options": {"landing": {
            "state": "landed", "relay": relay["id"], "sha": GOOD["sha"]}}}, "drain")
        self.board.land(self.card, relay["id"], "drain", published="x merged into next",
                        merge_queue=True, verify=lambda card, sha: None)
        self.assertEqual(self.board.get(self.card)["stage"], "done")

    def test_a_proposals_outcome_is_never_bosuns(self):
        """c-667: the ordinary card above is approved with these very facts; a card that
        proposes a tier or a flow is refused, and no relay is recorded."""
        for option in ("tier_proposal", "flow_proposal"):
            with self.subTest(option=option):
                card = self.board.create("personal", "p", repo="keel", actor="human",
                                         autonomy="autonomous", options={option: "personal"})
                self.board.stage(card, "assigned", "human")
                self.board.stage(card, "building", "human", plan_ref="p.md")
                self.board.stage(card, "review", "human", output_ref="keel/b")
                with self.assertRaisesRegex(Refused, "is a proposal: approving its outcome adopts its draft"):
                    self.board.approve(card, "outcome", authority.BOSUN,
                                       bosun={"checked": "lint, review, risk", "to": "box", "facts": GOOD})
                with self.assertRaisesRegex(Refused, "is a proposal"):
                    self.board.relay(card, "land", "human", to="box", sha=GOOD["sha"])
                self.assertEqual([e["kind"] for e in self.board.events(card) if e["kind"] == "relay"], [])
                self.assertEqual(self.board.get(card)["stage"], "review")
        self.approve()
        self.assertEqual([e["data"]["what"] for e in self.board.events(self.card) if e["kind"] == "relay"], ["land"])

    def test_a_proposals_plan_gate_is_never_bosuns(self):
        card = self.board.create("personal", "p", repo="keel", actor="human",
                                 options={"flow_proposal": "personal"})
        self.board.stage(card, "assigned", "human")
        self.board.stage(card, "planning", "human", plan_ref="p.md")
        with self.assertRaisesRegex(Refused, "is a proposal: its plan gate is the user's"):
            self.board.approve(card, "plan", authority.BOSUN, bosun={"checked": "read it", "facts": None})
        self.assertEqual(self.board.get(card)["stage"], "planning")

    def test_a_refused_check_writes_nothing(self):
        with self.assertRaises(Refused):
            self.approve(dict(GOOD, reviewed=False))
        self.assertFalse([e for e in self.board.events(self.card) if e["kind"] == "relay"])

    def test_bosun_cannot_write_a_land_relay_by_the_relay_verb(self):
        with self.assertRaises(Refused):
            self.board.relay(self.card, "land", authority.BOSUN, "box", sha=GOOD["sha"])
