"""Flows (keel/flows.py, flowcards.py, flowmoves.py, c-640): the format and its refusals,
which flow a space has, a proposal adopted from his words, a move he makes on a card, and
the flow on the state, on a real scratch install."""

import dataclasses
import io
import json
import os
import shutil
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

from keel import actions, deckstate, flowcards, flowcheck, flowfence, flows, harness, house, onboarding
from keel.board import Refused, open_board
from keel import config as config_module
from keel.setupconfig import SetupError
from tests.helpers import SESSION, FakeHarness, make_config
from tests.test_installer import init
from tests.test_needs_refusals import tracker_only
from tests.test_readiness import fake_tailscale

ROOT = Path(__file__).resolve().parent.parent

MINE = '''name = "Ours"
description = "Staging base, dev review on his word."

[[branch]]
id = "card"
label = "card branch"
kind = "card"

[[branch]]
id = "dev"
label = "dev_review"
kind = "environment"

[[move]]
id = "to-dev"
label = "Merge to dev review"
from = "card"
to = "dev"
by = "you"
stages = ["review", "shipping"]
group = "Try it live"
pushes = ["dev"]
prompt = "Merge {branch} into {target} and push it; resolve conflicts yourself."
about = "Puts the work on dev review to try it live."
'''


def toml(text: str, **changes) -> dict:
    import tomllib
    data = tomllib.loads(text)
    data.update(changes)
    return data


class FormatTest(unittest.TestCase):
    def refused(self, data, said):
        with self.assertRaises(flows.FlowError) as caught:
            flows.parse(data, "f.toml")
        self.assertIn(said, str(caught.exception))

    def test_keels_own_flows_load(self):
        for path in (flows.GENERAL, flows.INTEGRATION, flows.LOCAL):
            found = flows.load(path)
            self.assertTrue(found.moves)
            self.assertEqual([one.id for one in found.moves if one.yours], [], "Keel's own add no buttons")

    def test_a_flow_of_his_moves_loads(self):
        found = flows.parse(toml(MINE), "f.toml")
        move = found.move("to-dev")
        self.assertEqual((move.by, move.pushes, move.stages), ("you", ("dev",), ("review", "shipping")))

    def test_the_older_spelling_of_your_move_still_loads(self):
        """c-664: `by = "him"` (a pack's file, a flow adopted before) is `you`, a button."""
        found = flows.parse_text(MINE.replace('by = "you"', 'by = "him"'), "f.toml")
        self.assertTrue(found.move("to-dev").yours)
        self.assertEqual(flows.public(found)["moves"][0]["by"], "you")

    def test_each_mistake_is_refused_by_name(self):
        base = toml(MINE)
        move = dict(base["move"][0])
        cases = [
            (dict(base, colour="red"), "no key colour"),
            (dict(base, name=""), "`name` must be a non-empty string"),
            (dict(base, branch=[dict(base["branch"][1])]), "this has 0"),
            (dict(base, branch=base["branch"] + [dict(base["branch"][1])]), "branch id dev is used twice"),
            (dict(base, branch=[dict(base["branch"][0], kind="planet"), base["branch"][1]]), "kind 'planet'"),
            (dict(base, move=[dict(move, to="prod")]), "names branch prod"),
            (dict(base, move=[dict(move, by="robot")]), "by 'robot'"),
            (dict(base, move=[dict(move, stages=["later"])]), "stages later are not stages"),
            (dict(base, move=[dict(move, pushes=["prod"])]), "pushes prod"),
            (dict(base, move=[{k: v for k, v in move.items() if k != "prompt"}]), "says what the house does"),
            (dict(base, move=[{k: v for k, v in move.items() if k != "stages"}]), "says when it is offered"),
            (dict(base, move=[dict(move, by="colleague")]), "only a move you make"),
            (dict(base, move=[dict(move, prompt="push {secret}")]), "names {secret}"),
            (dict(base, move=[dict(move, by="keel", prompt="", pushes=[], step="")]), "names its step"),
            (dict(base, move=[dict(move, by="keel", prompt="", pushes=[], step="fly")]), "step 'fly'"),
            (dict(base, move=[move, dict(move)]), "move id to-dev is used twice"),
            (dict(base, move=[dict(move, wings=1)]), "no key wings"),
            (dict(base, branch=base["branch"] + [dict(base["branch"][0], id="card2")]), "this has 2"),
            (dict(base, move=[dict(move, step="push")]), "names a step; a move by you has none"),
            (dict(base, move=[dict(move, id="x" * 49)]), "over 48"),
            (dict(base, move=[dict(move, label="x" * 121)]), "over 120"),
        ]
        for data, said in cases:
            with self.subTest(said=said):
                self.refused(data, said)

    def test_the_prompt_is_filled_from_the_card_and_leaves_what_it_cannot(self):
        move = flows.parse(toml(MINE), "f.toml").move("to-dev")
        said = flows.prompt_for(move, {"id": "c-9"}, branch="feature/st-1/x", target="dev_review")
        self.assertEqual(said, "Merge feature/st-1/x into dev_review and push it; resolve conflicts yourself.")
        self.assertIn("{branch}", flows.prompt_for(move, {"id": "c-9"}), "an unknown branch stays as written")


def changed(text: str = MINE, move: dict | None = None, branch: dict | None = None) -> flows.Flow:
    """`text` with keys of its last move, or of its last branch, changed."""
    data = toml(text)
    data["move"][-1].update(move or {})
    data["branch"][-1].update(branch or {})
    return flows.parse(data, "f.toml")


class CheckTest(unittest.TestCase):
    """c-664: `keel flow check` and Adopt refuse a flow of the right shape that cannot run
    (`keel/flowcheck.py`), naming the move and what to change."""

    def space(self, pack: str | None, **more):
        return SimpleNamespace(name="team", adapter=pack, adapter_dir=ROOT / "packs" / pack if pack else None,
                               repos={}, **more)

    def test_a_move_that_can_never_run_is_refused_by_name(self):
        cases = [(changed(move={"to": "card"}), "from card to card"),
                 (changed(move={"stages": ["review", "done"]}), "offered at done"),
                 (changed(move={"stages": ["assigned"]}), "offered at assigned"),
                 (changed(branch={"label": "dev review"}), "is not a git branch name"),
                 (changed(move={"pushes": ["card"]}), "the card's own branch")]
        for found, said in cases:
            with self.subTest(said=said):
                problems = flowcheck.problems(found)
                self.assertEqual(len(problems), 1, problems)
                self.assertIn("move to-dev", problems[0])
                self.assertIn(said, problems[0])
        self.assertEqual(flowcheck.problems(changed()), [], "the flow as written can run")

    def test_what_the_space_cannot_run_is_refused_when_the_space_is_named(self):
        keel_move = {"by": "keel", "prompt": "", "pushes": [], "stages": ["review"]}
        opens = changed(move={"opens": ["dev"]})
        cfg = SimpleNamespace(integration_of=lambda space, repo: None)
        cases = [(changed(move=dict(keel_move, step="ship")), self.space(None), "needs a pack with the `ship` verb"),
                 (changed(move=dict(keel_move, step="publish")), self.space(None), "needs a pack with the `publish` verb"),
                 (changed(move=dict(keel_move, step="land")), self.space("sandbox"), "Use step publish"),
                 (changed(move=dict(keel_move, step="deploy")), self.space(None), "no repo of the team space lands"),
                 (opens, self.space("sandbox"), "flow_pr = true"),
                 (opens, self.space(None), "flow_pr = true")]
        for found, space, said in cases:
            with self.subTest(said=said):
                problems = flowcheck.problems(found, cfg, space)
                self.assertEqual(len(problems), 1, problems)
                self.assertIn(said, problems[0])
                self.assertEqual(flowcheck.problems(found), [], "shape alone passes: the space refused it")
        # A pack that declares it (c-722: written here, so no pack of anyone's own is needed).
        with tempfile.TemporaryDirectory() as tmp:
            flowing = Path(tmp) / "flowing"
            (flowing / "pr").parent.mkdir(parents=True)
            (flowing / "pack.toml").write_text('name = "flowing"\nversion = "1"\ndescription = "x"\n'
                                               '[capabilities]\nflow_pr = true\n')
            (flowing / "pr").write_text("#!/bin/sh\n")
            (flowing / "pr").chmod(0o755)
            space = SimpleNamespace(name="team", adapter="flowing", adapter_dir=flowing, repos={})
            self.assertEqual(flowcheck.problems(opens, cfg, space), [], "a pack that declares it")

    def test_the_verb_checks_a_file_for_a_space_and_says_what_a_flow_is(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "flow.toml"
            path.write_text(MINE.replace('to = "dev"', 'to = "card"'))
            err, out = io.StringIO(), io.StringIO()
            with redirect_stderr(err):
                self.assertEqual(flows.main(["check", str(path)]), 1)
            self.assertIn("move to-dev", err.getvalue())
            path.write_text(MINE)
            with redirect_stdout(out):
                self.assertEqual(flows.main(["check", str(path)]), 0)
        self.assertIn("1 of them yours", out.getvalue())


class InstallCase(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        patch = mock.patch.dict(os.environ)
        patch.start()
        self.addCleanup(patch.stop)
        self.home = Path(tmp.name).resolve() / "install"
        self.assertEqual(init(self.home), 0)
        self.cfg = config_module.load(self.home / "config.toml", ensure=False)
        self.space = self.cfg.spaces["personal"]
        fake_tailscale(self.home.parent / "bin", "{}")      # the state's phone row asks it

    def own(self, text: str = MINE) -> Path:
        path = flows.space_file(self.cfg, "personal")
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text)
        return path


class WhichFlowTest(InstallCase):
    def test_keels_own_until_the_space_has_its_own(self):
        found = flows.of(self.cfg, self.space)
        self.assertEqual((found.source, found.path), ("keel", flows.default_of(self.cfg, self.space)))
        self.own()
        self.assertEqual((flows.of(self.cfg, self.space).source, flows.of(self.cfg, self.space).name), ("space", "Ours"))

    def test_a_broken_own_flow_is_said_and_the_next_one_used(self):
        self.own("name = 'x'\n")
        found = flows.of(self.cfg, self.space)
        self.assertEqual(found.source, "keel")
        self.assertIn("[spaces.personal] flow:", found.warnings[0])

    def test_a_flow_that_is_not_utf8_is_said_and_the_next_one_used(self):
        self.own().write_bytes(b"name = '\xff\xfe'\n")
        found = flows.of(self.cfg, self.space)
        self.assertEqual(found.source, "keel")
        self.assertIn("[spaces.personal] flow:", found.warnings[0])

    def test_a_packs_flow_is_its_default(self):
        with tempfile.TemporaryDirectory() as tmp:
            (Path(tmp) / flows.FILE).write_text(MINE)
            space = mock.Mock(name="work", adapter_dir=Path(tmp), repos={})
            space.name = "work"
            self.assertEqual(flows.of(self.cfg, space).source, "pack")

    def test_the_state_carries_each_spaces_flow_and_its_warnings(self):
        self.own("name = 'x'\n")
        with open_board(self.cfg) as board, \
                mock.patch.object(deckstate.harness, "agents_across", return_value=[]):
            doc = deckstate.build(self.cfg, board, rows=[])
        flow = doc["spaces"]["personal"]["flow"]
        self.assertEqual(flow["source"], "keel")
        self.assertIsNone(flow["proposal"])
        self.assertNotIn("prompt", flow["moves"][0], "the prompt stays on the server")
        self.assertTrue(any("[spaces.personal] flow:" in line for line in doc["config"]["warnings"]))

    def test_the_state_says_whether_a_draft_of_the_flow_was_adopted(self):
        """The page said "Bosun's draft is how this space ships now" of any flow of the space's
        own, one written in Settings included (c-678 review r2.F13)."""
        from keel import flowcards     # noqa: PLC0415
        with open_board(self.cfg) as board, \
                mock.patch.object(deckstate.harness, "agents_across", return_value=[]):
            self.assertFalse(deckstate.build(self.cfg, board, rows=[])["spaces"]["personal"]["flow"]["adopted"])
            card = board.create("personal", "How personal ships", actor="human", model="opus",
                                options={flowcards.OPTION: "personal"})
            self.assertFalse(deckstate.build(self.cfg, board, rows=[])["spaces"]["personal"]["flow"]["adopted"],
                             "a proposal that is still open adopted nothing")
            board.conn.execute("UPDATE cards SET stage = 'done' WHERE id = ?", (card,))
            board.conn.commit()
            self.assertTrue(deckstate.build(self.cfg, board, rows=[])["spaces"]["personal"]["flow"]["adopted"])


class KeelsOwnFlowTest(InstallCase):
    """c-664: which of Keel's own flows a space draws, in the space's words, and that each
    can run in the space that draws it."""

    def on(self, pack: Path | None, name: str = "team", **more):
        space = dataclasses.replace(self.space, name=name, adapter=pack.name if pack else None,
                                    adapter_dir=pack, **more)
        self.cfg.spaces[name] = space
        return space

    def tracker_only(self) -> Path:
        pack = self.home.parent / "scratch-packs" / "trackeronly"
        shutil.copytree(ROOT / "packs" / "sandbox", pack)
        (pack / "pack.toml").write_text(tracker_only((pack / "pack.toml").read_text()))
        return pack

    def legacy(self, *verbs: str) -> Path:
        """An adapter from before packs: a directory of executables and no pack.toml."""
        path = self.home.parent / "scratch-packs" / ("legacy-" + "-".join(verbs) if verbs else "legacy")
        path.mkdir(parents=True)
        for verb in verbs:
            (path / verb).write_text("#!/bin/sh\n")
            (path / verb).chmod(0o755)
        return path

    def test_the_change_flow_is_only_for_a_space_whose_pack_reaches_a_code_host(self):
        hosted = self.on(ROOT / "packs" / "sandbox")
        plain = self.on(self.tracker_only(), "plain")
        self.assertEqual(flows.default_of(self.cfg, hosted), flows.GENERAL)
        self.assertEqual(flows.default_of(self.cfg, plain), flows.LOCAL)
        self.assertEqual(flows.default_of(self.cfg, self.space), flows.LOCAL)

    def test_a_space_whose_pack_has_no_code_host_draws_no_move_and_says_why(self):
        """c-664 review F1: Approve of a repo card is refused there (`adapters.publish`), and
        nothing is merged locally either, so the flow draws no landing, the state carries the
        refusal's own sentence, and the check refuses a move that says one happens."""
        plain = self.on(self.tracker_only(), "plain")
        drawn = flows.drawn(self.cfg, plain)
        self.assertEqual((drawn["moves"], drawn["held"]), ([], "A repo card cannot be approved in this space until a code host is set up (the trackeronly connection has no code host)."))
        self.assertEqual(drawn["description"], "Shipyard draws no flow for this space yet.")
        self.assertFalse(drawn["handling"]["shipping"], "no card reaches shipping where none is approved")
        self.assertNotIn("trackeronly", drawn["description"], "the panel says the reason once, from `held`")
        self.assertIs(drawn["held_codehost"], True, "c-758 r1.F8: the page's advice is for this reason alone")
        self.assertIsNone(flows.drawn(self.cfg, self.space)["held"])
        self.assertIs(flows.drawn(self.cfg, self.space)["held_codehost"], False)
        self.assertIsNone(flows.drawn(self.cfg, self.on(ROOT / "packs" / "sandbox"))["held"])
        for step in ("land", "publish", "ship"):
            with self.subTest(step=step):
                found = changed(move={"by": "keel", "prompt": "", "pushes": [], "stages": ["review"], "step": step})
                problems = flowcheck.problems(found, self.cfg, plain)
                self.assertEqual(len(problems), 1, problems)
                self.assertIn("until a code host is set up", problems[0])
                self.assertNotIn("never runs", problems[0])

    def test_the_flow_says_the_spaces_own_word_for_a_change(self):
        drawn = flows.drawn(self.cfg, self.on(ROOT / "packs" / "sandbox"))
        said = " ".join([drawn["description"], *(one["label"] + one["about"] for one in drawn["moves"])])
        self.assertIn("merge request", said)
        self.assertNotIn("{change}", said)

    def test_a_landing_branch_is_drawn_by_its_name_and_only_drawn(self):
        here = self.home.parent
        self.cfg.integration = {"keel": "next"}
        every = self.on(None, "every", repos={"keel": here})
        some = self.on(None, "some", repos={"keel": here, "notes": here, "tools": here})
        all_land, mixed = flows.drawn(self.cfg, every), flows.drawn(self.cfg, some)
        self.assertEqual((all_land["name"], [one["label"] for one in all_land["branches"]][1]),
                         ("Integration branch", "next"))
        self.assertEqual(mixed["name"], "Local merge")
        # each repo's landing branch by name, for the deck's own lines (c-665)
        self.assertEqual((all_land["landing"], mixed["landing"]), ({"keel": "next"}, {"keel": "next"}))
        self.assertIn("next for keel", [one["label"] for one in mixed["branches"]][1])
        self.assertIn("keel", mixed["description"])
        # the flow the fence reads still names no git branch for it
        card = {"id": "c-1", "space": "every", "repo": None, "options": {}}
        self.assertNotIn("next", flowfence.shared(self.cfg, card))

    def test_a_landing_is_drawn_as_local_and_not_pushed(self):
        """c-665: Keel's two landing flows never read as shipped."""
        here = self.home.parent
        self.cfg.integration = {"keel": "next"}
        for name, repos in (("local", {"notes": here}), ("every", {"keel": here})):
            with self.subTest(space=name):
                drawn = flows.drawn(self.cfg, self.on(None, name, repos=repos))
                self.assertIn("not pushed", " ".join(one["about"] for one in drawn["moves"] if one["step"] == "land"))

    def test_each_of_keels_own_can_run_in_the_space_that_draws_it(self):
        self.cfg.integration = {"keel": "next"}
        spaces = [self.on(ROOT / "packs" / "sandbox"), self.space,
                  self.on(None, "every", repos={"keel": self.home.parent}),
                  self.on(self.tracker_only(), "plain"), self.on(self.legacy("publish", "ship"), "old"),
                  self.on(self.legacy("publish"), "half"), self.on(self.legacy(), "bare")]
        drawn = set()
        for space in spaces:
            found = flows.of(self.cfg, space)       # the flow the space has, as the deck draws it
            drawn.add(found.path)
            self.assertEqual(found.source, "keel")
            self.assertEqual(flowcheck.problems(found, self.cfg, space), [], space.name)
        self.assertEqual(drawn, {flows.GENERAL, flows.LOCAL, flows.INTEGRATION})

    def test_an_older_adapter_and_a_pack_that_does_not_load(self):
        """c-664 review: an adapter with no pack.toml draws the change flow only when it has
        both the `publish` and the `ship` verbs. Without `publish` its Approve fails; with
        `publish` and no `ship` a card is approved and published and cannot be watched at
        shipping. A
        pack whose pack.toml is broken declares nothing, so its Approve is refused. Each is
        held with a sentence true of its own case, and no move is drawn."""
        broken = self.home.parent / "scratch-packs" / "broken"
        broken.mkdir(parents=True)
        (broken / "pack.toml").write_text("name = ")
        self.assertEqual(flows.default_of(self.cfg, self.on(self.legacy("publish", "ship"), "old")), flows.GENERAL)
        # without both verbs no flow is drawn: held, each in its own words
        half = flows.drawn(self.cfg, self.on(self.legacy("publish"), "half"))
        bare = flows.drawn(self.cfg, self.on(self.legacy(), "bare"))
        self.assertEqual((half["moves"], half["held"]), ([], (
            "A card can be approved and published in this space, but Shipyard cannot watch it at shipping: "
            "the legacy-publish adapter has no ship verb. So Shipyard draws no flow for it.")))
        self.assertEqual((bare["moves"], bare["held"]), ([], (
            "Approve of a repo card fails in this space: the legacy adapter has no publish verb.")))
        self.assertFalse(half["handling"]["shipping"])
        # the check refuses a drawn step in each, in that case's own sentence
        for name, space_of in (("half", "half"), ("bare", "bare")):
            held = {"half": half, "bare": bare}[name]["held"]
            for step in ("land", "publish", "ship"):
                with self.subTest(space=name, step=step):
                    found = changed(move={"by": "keel", "prompt": "", "pushes": [], "stages": ["review"], "step": step})
                    problems = flowcheck.problems(found, self.cfg, self.cfg.spaces[space_of])
                    self.assertEqual(len(problems), 1, problems)
                    self.assertIn(held, problems[0])
        self.assertIn("has no publish verb", bare["held"])
        self.assertIn("cannot watch it at shipping", half["held"])
        # c-758 r1.F8: neither is the no-code-host case, so the page adds no advice about one
        self.assertEqual((bare["held_codehost"], half["held_codehost"]), (False, False))
        drawn = flows.drawn(self.cfg, self.on(broken, "bad"))
        self.assertEqual(drawn["moves"], [])
        self.assertIn("does not load", drawn["held"])
        # r2.F2: a pack that does not load is not the no-code-host case either
        self.assertIs(drawn["held_codehost"], False)

    def test_the_state_says_how_the_space_handles_review_at_shipping(self):
        hosted = self.on(ROOT / "packs" / "sandbox", ship_auto_comments=True)
        self.assertEqual(flows.drawn(self.cfg, hosted)["handling"],
                         {"shipping": True, "comments": True, "checks": False})
        self.assertFalse(flows.drawn(self.cfg, self.space)["handling"]["shipping"])


class CheckVerbTest(InstallCase):
    """c-664 review F9: `keel flow check <file> --space <name>` reads the config the verb
    is run with, checks what that space can run, and names a space that is not there."""

    def run_check(self, text: str, *more: str) -> tuple[int, str]:
        path = self.home.parent / "proposed.toml"
        path.write_text(text)
        said = io.StringIO()
        os.environ["KEEL_CONFIG"] = str(self.home / "config.toml")
        with redirect_stderr(said), redirect_stdout(said):
            code = flows.main(["check", str(path), *more])
        return code, said.getvalue()

    def test_the_space_named_decides_what_can_run(self):
        ship = MINE + '\n[[move]]\nid = "ship"\nlabel = "Ship"\nfrom = "card"\nto = "dev"\nby = "keel"\nstep = "ship"\n'
        self.assertEqual(self.run_check(ship)[0], 0, "shape alone passes")
        code, said = self.run_check(ship, "--space", "personal")
        self.assertEqual(code, 1)
        self.assertIn("move ship", said)
        code, said = self.run_check(MINE, "--space", "personal")
        self.assertEqual(code, 0)
        self.assertIn("for the personal space", said)

    def test_a_space_that_is_not_there_is_said(self):
        code, said = self.run_check(MINE, "--space", "nowhere")
        self.assertEqual(code, 1)
        self.assertIn("no space nowhere", said)


class ProposeAdoptTest(InstallCase):
    def test_the_brief_names_every_key_of_the_format_and_what_a_flow_does(self):
        """c-664: the short form is written from the schema's lists, so `opens` and `bases`
        are in it, with the spelling of the one kind of move that acts."""
        with open_board(self.cfg) as board:
            brief = board.get(flowcards.propose(self.cfg, board, "personal", "as today")["card"])["brief"]
        keys = ("id", "label", "kind", "from", "to", "by", "step", "stages", "group", "prompt",
                "pushes", "opens", "bases", "about", "name", "description")
        self.assertEqual([key for key in keys if f"`{key}`" not in brief], [])
        for said in ('Only a move by `you`', "{base}", "--space personal"):
            self.assertIn(said, brief)

    def test_adopt_refuses_a_proposal_the_space_cannot_run(self):
        with open_board(self.cfg) as board:
            cid = flowcards.propose(self.cfg, board, "personal", "ship it for me")["card"]
            proposal = flowcards.proposal_of(self.cfg, cid)
            proposal.write_text(MINE + '\n[[move]]\nid = "ship"\nlabel = "Ship"\nfrom = "card"\n'
                                       'to = "dev"\nby = "keel"\nstep = "ship"\n')
            board.conn.execute("UPDATE cards SET stage = 'review', output_ref = ? WHERE id = ?", (str(proposal), cid))
            with self.assertRaises(SetupError) as caught:
                flowcards.adopt(self.cfg, board, cid)
        self.assertIn("move ship", str(caught.exception))
        self.assertFalse(flows.space_file(self.cfg, "personal").exists())

    def test_his_words_become_a_card_and_its_checked_file_his_spaces_flow(self):
        with open_board(self.cfg) as board:
            filed = flowcards.propose(self.cfg, board, "personal", "We merge to dev review on my word.")
            card = board.get(filed["card"])
            self.assertIn("We merge to dev review on my word.", card["brief"])
            self.assertEqual(card["options"]["flow_proposal"], "personal")
            self.assertTrue((self.cfg.card_dir(filed["card"]) / flowcards.CURRENT).read_text())
            with self.assertRaises(SetupError):
                flowcards.propose(self.cfg, board, "personal", "again")
            proposal = flowcards.proposal_of(self.cfg, filed["card"])
            proposal.write_text("name = 'broken'\n")
            board.conn.execute("UPDATE cards SET stage = 'review', output_ref = ? WHERE id = ?",
                               (str(proposal), filed["card"]))
            with self.assertRaises(SetupError) as caught:
                flowcards.adopt(self.cfg, board, filed["card"])
            self.assertIn("does not check, so nothing was adopted", str(caught.exception))
            self.assertFalse(flows.space_file(self.cfg, "personal").exists())
            proposal.write_text(MINE)
            adopted = flowcards.adopt(self.cfg, board, filed["card"])
        self.assertEqual(adopted["flow"], "Ours")
        self.assertEqual(flows.of(self.cfg, self.space).source, "space")

    def test_reset_puts_the_space_back_on_keels_flow_and_keeps_the_old_file(self):
        self.own()
        said = flowcards.reset(self.cfg, "personal")
        self.assertEqual(flows.of(self.cfg, self.space).source, "keel")
        self.assertTrue(Path(said["kept"]).is_file())

    def test_adopt_refuses_a_proposal_for_a_space_that_is_not_here(self):
        with open_board(self.cfg) as board:
            cid = board.create("personal", "x", actor="human", options={"flow_proposal": "../../etc"})
            board.conn.execute("UPDATE cards SET stage = 'review' WHERE id = ?", (cid,))
            with self.assertRaises(SetupError) as caught:
                flowcards.adopt(self.cfg, board, cid)
        self.assertIn("which is not a space here", str(caught.exception))

    def test_only_he_names_a_proposal_or_a_grant(self):
        with open_board(self.cfg) as board:
            cid = board.create("personal", "x", actor="human")
            for option in ("flow_proposal", "flow_move"):
                with self.subTest(option=option):
                    with self.assertRaises(Refused):
                        board.set_fields(cid, {"options": {option: "personal"}}, "house")
                    with self.assertRaises(Refused):
                        board.create("personal", "y", actor="house", options={option: "personal"})
            self.assertEqual(flowcards.proposals(board), {})

    def test_adopt_is_his_tap_and_ends_the_card_and_its_house(self):
        with open_board(self.cfg) as board:
            filed = flowcards.propose(self.cfg, board, "personal", "dev review on my word")
            cid = filed["card"]
            proposal = flowcards.proposal_of(self.cfg, cid)
            proposal.write_text(MINE)
            board.conn.execute("UPDATE cards SET stage = 'review', output_ref = ?, session_id = 's-9' "
                               "WHERE id = ?", (str(proposal), cid))
            body = {"verb": "setup.flow.adopt", "card": cid}
            with mock.patch.object(onboarding.house, "retire_finished") as retire:
                with self.assertRaises(actions.ActionError) as caught:
                    actions.act(self.cfg, board, dict(body, caller={"actor": "house", "card": cid, "token": "t"}))
                self.assertIn("one machine", str(caught.exception))
                self.assertFalse(flows.space_file(self.cfg, "personal").exists())
                answer = actions.act(self.cfg, board, body)
                card = board.get(cid)
        self.assertEqual((answer["flow"], card["stage"]), ("Ours", "done"))
        retire.assert_called_once()
        self.assertEqual(flows.of(self.cfg, self.space).source, "space")

    def test_approve_outcome_on_the_proposal_adopts_it(self):
        with open_board(self.cfg) as board:
            cid = flowcards.propose(self.cfg, board, "personal", "dev review on my word")["card"]
            proposal = flowcards.proposal_of(self.cfg, cid)
            proposal.write_text(MINE)
            board.conn.execute("UPDATE cards SET stage = 'review', output_ref = ? WHERE id = ?", (str(proposal), cid))
            body = {"verb": "approve", "id": cid, "gate": "outcome"}
            answer = actions.act(self.cfg, board, dict(body, said="ship it"))
            card = board.get(cid)
            said = [row["text"] for row in board.events(cid) if row["text"] == "ship it"]
        self.assertEqual((answer["flow"], card["stage"]), ("Ours", "done"))
        self.assertEqual(said, ["ship it"])
        self.assertEqual(flows.of(self.cfg, self.space).source, "space")

    def drafted(self, board, text: str = MINE) -> str:
        cid = flowcards.propose(self.cfg, board, "personal", "dev review on my word")["card"]
        proposal = flowcards.proposal_of(self.cfg, cid)
        proposal.write_text(text)
        board.conn.execute("UPDATE cards SET stage = 'review', output_ref = ? WHERE id = ?", (str(proposal), cid))
        return cid

    def test_an_approve_adopt_refuses_leaves_the_card_at_review(self):
        """c-667: Approve outcome makes Adopt's own check, and its refusal is the answer."""
        with open_board(self.cfg) as board:
            cid = self.drafted(board, "name = 'broken'\n")
            with self.assertRaisesRegex(actions.ActionError, "does not check, so nothing was adopted"):
                actions.act(self.cfg, board, {"verb": "approve", "id": cid, "gate": "outcome"})
            self.assertEqual(board.get(cid)["stage"], "review")
        self.assertFalse(flows.space_file(self.cfg, "personal").exists())

    def test_adopt_and_approve_together_write_the_flow_once(self):
        taps = ({"verb": "setup.flow.adopt"}, {"verb": "approve", "gate": "outcome"})
        target = flows.space_file(self.cfg, "personal")
        with open_board(self.cfg) as board:
            for first, second in (taps, taps[::-1]):
                with self.subTest(first=first["verb"]):
                    cid = self.drafted(board)
                    actions.act(self.cfg, board, dict(first, id=cid, card=cid))
                    target.write_text(MINE.replace("Ours", "Edited since"))
                    answer = actions.act(self.cfg, board, dict(second, id=cid, card=cid))
                    self.assertIn("already adopted", answer["note"])
                    self.assertIn("Edited since", target.read_text())

    def test_a_move_refused_after_the_write_is_retried_with_no_second_write(self):
        target = flows.space_file(self.cfg, "personal")
        with open_board(self.cfg) as board:
            cid = self.drafted(board)
            with mock.patch.object(board, "approve", side_effect=Refused("held")):
                answer = actions.act(self.cfg, board, {"verb": "approve", "id": cid, "gate": "outcome"})
            self.assertIn("was not moved to done: held", answer["note"])
            target.write_text(MINE.replace("Ours", "Edited since"))
            answer = actions.act(self.cfg, board, {"verb": "setup.flow.adopt", "card": cid})
            self.assertIn("already adopted", answer["note"])
            self.assertEqual(board.get(cid)["stage"], "done")
        self.assertIn("Edited since", target.read_text())

    def test_a_flow_reset_since_is_written_again(self):
        """Review 2 F4: Adopt wrote, the move was refused, the flow was reset: Adopt writes again."""
        target = flows.space_file(self.cfg, "personal")
        with open_board(self.cfg) as board:
            cid = self.drafted(board)
            with mock.patch.object(board, "approve", side_effect=Refused("held")):
                actions.act(self.cfg, board, {"verb": "setup.flow.adopt", "card": cid})
            flowcards.reset(self.cfg, "personal")
            self.assertFalse(target.exists())
            answer = actions.act(self.cfg, board, {"verb": "setup.flow.adopt", "card": cid})
            self.assertNotIn("already", answer["note"])
            self.assertEqual(board.get(cid)["stage"], "done")
        self.assertEqual(flows.of(self.cfg, self.space).source, "space")

    def test_a_done_proposal_whose_flow_was_reset_since_says_so(self):
        target = flows.space_file(self.cfg, "personal")
        with open_board(self.cfg) as board:
            cid = self.drafted(board)
            actions.act(self.cfg, board, {"verb": "setup.flow.adopt", "card": cid})
            flowcards.reset(self.cfg, "personal")
            for body in ({"verb": "approve", "id": cid, "gate": "outcome"}, {"verb": "setup.flow.adopt", "card": cid}):
                with self.assertRaisesRegex(actions.ActionError, "which is gone since; it is done"):
                    actions.act(self.cfg, board, body)
        self.assertFalse(target.exists())

    def test_a_stage_move_never_closes_a_proposal(self):
        with open_board(self.cfg) as board:
            cid = self.drafted(board)
            with self.assertRaisesRegex(Refused, "closes by Adopt"):
                board.stage(cid, "done", "human")
            self.assertEqual(board.get(cid)["stage"], "review")
        self.assertFalse(flows.space_file(self.cfg, "personal").exists())

    def test_kb_approve_adopts_too_and_only_for_him(self):
        from argparse import Namespace
        from keel import cli
        with open_board(self.cfg) as board:
            cid = self.drafted(board)
            args = Namespace(id=cid, gate="outcome", config=self.cfg, said=None, relay=None, to=None, checked=None)
            for actor in ("house", "drain"):
                with self.assertRaises(Refused):
                    cli.cmd_approve(board, args, actor)
            with self.assertRaises(Refused):
                board.approve(cid, "outcome", "bosun")
            self.assertFalse(flows.space_file(self.cfg, "personal").exists())
            cli.cmd_approve(board, args, "human")
            self.assertEqual(board.get(cid)["stage"], "done")
        self.assertEqual(flows.of(self.cfg, self.space).source, "space")

    def test_empty_words_or_an_unknown_space_are_refused(self):
        with open_board(self.cfg) as board:
            for space, words in (("personal", "  "), ("nowhere", "x")):
                with self.assertRaises(SetupError):
                    flowcards.propose(self.cfg, board, space, words)


class MoveTest(InstallCase):
    def card(self, board, stage="review", session="s-1"):
        cid = board.create("personal", "a card", actor="human", options={"branch": "feature/x"})
        board.conn.execute("UPDATE cards SET stage = ?, session_id = ? WHERE id = ?", (stage, session, cid))
        return cid

    def act(self, board, cid, move="to-dev", **extra):
        return actions.act(self.cfg, board, dict({"verb": "flow.move", "id": cid, "move": move}, **extra))

    def resumed(self, effect):
        return mock.patch.object(actions.house, "resume", side_effect=effect)

    def test_his_tap_records_the_move_and_tells_the_house(self):
        self.own()
        told = []
        with open_board(self.cfg) as board, self.resumed(
                lambda cfg, board, cid, prompt=None, **how: told.append((prompt, how)) or {"resumed": cid}):
            cid = self.card(board)
            answer = self.act(board, cid)
            card = board.get(cid)
            notes = [row["text"] for row in board.events(cid) if "flow move asked" in (row["text"] or "")]
        self.assertEqual(answer["move"], "to-dev")
        self.assertEqual(card["options"]["flow_move"]["id"], "to-dev")
        self.assertEqual(card["options"]["flow_move"]["pushes"], ["dev"])
        prompt, how = told[0]
        self.assertEqual(how, {"tell": True, "background": True})
        self.assertIn("Merge feature/x into dev_review and push it", prompt)
        self.assertIn(f"kb note {cid}", prompt)
        self.assertEqual(len(notes), 1)

    def test_a_working_house_is_told_when_its_turn_ends(self):
        self.own()
        with open_board(self.cfg) as board, self.resumed(house.Busy("working")), \
                mock.patch.object(actions, "run_kb") as kb:
            cid = self.card(board)
            answer = self.act(board, cid)
            self.assertTrue(board.get(cid)["options"]["flow_move"])
        self.assertTrue(answer["held"])
        self.assertIn("--held", kb.call_args.args[1])

    def test_a_tell_that_fails_leaves_no_grant_and_no_note(self):
        self.own()
        with open_board(self.cfg) as board, self.resumed(harness.HarnessError("no claude")):
            cid = self.card(board)
            with self.assertRaises(actions.ActionError) as caught:
                self.act(board, cid)
            card = board.get(cid)
            notes = [row for row in board.events(cid) if "flow move asked" in (row["text"] or "")]
        self.assertIn("resume failed", str(caught.exception))
        self.assertNotIn("flow_move", {k: v for k, v in card["options"].items() if v})
        self.assertEqual(notes, [])

    def test_a_failed_tap_keeps_the_grant_before_it_and_a_stage_move_ends_it(self):
        self.own()
        with open_board(self.cfg) as board:
            cid = self.card(board)
            with self.resumed(lambda *a, **k: {"resumed": cid}):
                self.act(board, cid)
            first = board.get(cid)["options"]["flow_move"]
            with self.resumed(harness.HarnessError("no claude")), self.assertRaises(actions.ActionError):
                self.act(board, cid)
            self.assertEqual(board.get(cid)["options"]["flow_move"], first)
            board.stage(cid, "building", "human")
            self.assertFalse(board.get(cid)["options"].get("flow_move"))

    def test_a_houses_kb_cannot_tap_a_move(self):
        self.own()
        with open_board(self.cfg) as board, self.resumed(None) as resume:
            cid = self.card(board)
            with self.assertRaises(actions.ActionError) as caught:
                self.act(board, cid, caller={"actor": "house", "card": cid, "token": "t"})
            card = board.get(cid)
        self.assertIn("one machine", str(caught.exception))
        self.assertNotIn("flow_move", card["options"])
        resume.assert_not_called()

    def test_a_move_that_is_not_his_now_is_refused(self):
        self.own()
        with open_board(self.cfg) as board, mock.patch.object(actions, "act_resume") as resume:
            building = self.card(board, stage="building")
            houseless = self.card(board, session=None)
            board.conn.execute("UPDATE cards SET session_id = NULL WHERE id = ?", (houseless,))
            cases = [(building, "to-dev", "offered at review, shipping"),
                     (houseless, "to-dev", "has no house"),
                     (building, "nope", "has no move 'nope'")]
            for cid, move, said in cases:
                with self.subTest(said=said), self.assertRaises(actions.ActionError) as caught:
                    self.act(board, cid, move)
                self.assertIn(said, str(caught.exception))
        resume.assert_not_called()

    def test_a_move_that_pushes_is_held_while_the_branch_is_out_of_step(self):
        """c-664 (F7): the shipping record says the worktree has diverged from what was
        pushed, so a move that pushes a shared branch would send that old history there."""
        self.own()
        said = "The branch has diverged from the pull request's branch (2 ahead, 1 behind)."
        with open_board(self.cfg) as board, self.resumed(lambda *a, **k: {"resumed": "x"}) as resume:
            cid = self.card(board, stage="shipping")
            board.conn.execute("UPDATE cards SET options = ? WHERE id = ?", (json.dumps(
                {"branch": "feature/x", "shipping": {"local": {"ahead": 0, "behind": 1, "said": said,
                                                               "diverged": {"ahead": 2, "behind": 1}}}}), cid))
            with self.assertRaises(actions.ActionError) as caught:
                self.act(board, cid)
            self.assertIn(said, str(caught.exception))
            self.assertFalse(board.get(cid)["options"].get("flow_move"))
            resume.assert_not_called()
            board.conn.execute("UPDATE cards SET options = ? WHERE id = ?", (json.dumps(
                {"branch": "feature/x", "shipping": {"local": {"ahead": 1, "behind": 0}}}), cid))
            self.assertEqual(self.act(board, cid)["move"], "to-dev")

    def test_the_out_of_step_record_is_believed_only_at_shipping(self):
        """c-664 review F4: the record is kept fresh only for a shipping card and no stage
        move drops it, so an old one must not hold a move at review; at shipping a record
        with the count and no sentence still holds it, in the fallback words."""
        self.own()
        stale = json.dumps({"branch": "feature/x", "shipping": {"local": {"ahead": 0, "behind": 2}}})
        with open_board(self.cfg) as board, self.resumed(lambda *a, **k: {"resumed": "x"}):
            at_review = self.card(board, stage="review")
            at_shipping = self.card(board, stage="shipping")
            board.conn.execute("UPDATE cards SET options = ? WHERE id IN (?, ?)", (stale, at_review, at_shipping))
            self.assertEqual(self.act(board, at_review)["move"], "to-dev")
            with self.assertRaises(actions.ActionError) as caught:
                self.act(board, at_shipping)
        self.assertIn("out of step with what was pushed", str(caught.exception))

    def test_keels_own_flow_offers_no_move_to_tap(self):
        with open_board(self.cfg) as board:
            cid = self.card(board)
            self.assertEqual(flows.offered(flows.of(self.cfg, self.space), board.get(cid)), [])
            with self.assertRaises(actions.ActionError) as caught:
                self.act(board, cid, "land")
        self.assertIn("made by keel, not by a tap", str(caught.exception))


class HarnessTapTest(unittest.TestCase):
    """His tap through the fake harness (`tests/helpers.FakeHarness`), not a stub of
    `house.resume`: a house the listing no longer shows has exited, so the tap resumes it with
    the move's prompt, as Resume would."""

    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.dir = Path(tmp.name)
        self.cfg = make_config(self.dir)
        self.cfg.drain_paused = True
        mine = self.dir / "flow.toml"
        mine.write_text(MINE)
        self.fake = FakeHarness()
        for patch in (mock.patch.object(flows, "space_file", lambda cfg, space: mine),
                      mock.patch.object(actions, "harness", self.fake),
                      mock.patch.object(house, "harness", self.fake)):
            patch.start()
            self.addCleanup(patch.stop)

    def test_an_exited_house_is_resumed_with_the_moves_prompt(self):
        with open_board(self.cfg) as board:
            cid = board.create("personal", "an errand", actor="human")
            board.stage(cid, "assigned", "human")
            board.stage(cid, "building", "drain")
            board.set_session(cid, SESSION, "drain", bg_id=SESSION[:8])
            board.conn.execute("UPDATE cards SET stage = 'review' WHERE id = ?", (cid,))
            self.fake.rows = []                        # not listed: the house has exited
            answer = actions.act(self.cfg, board, {"verb": "flow.move", "id": cid, "move": "to-dev"})
            card = board.get(cid)
        self.assertEqual(answer["move"], "to-dev")
        self.assertEqual(len(self.fake.resumes), 1)
        self.assertEqual(self.fake.resumes[0]["session_id"], SESSION)
        self.assertIn("Merge to dev review (to-dev)", self.fake.resumes[0]["prompt"])
        self.assertEqual(card["options"]["flow_move"]["pushes"], ["dev"])


if __name__ == "__main__":
    unittest.main()
