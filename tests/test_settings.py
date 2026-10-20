"""One settings schema (c-633, `keel/settings.py`): every setting is declared once with a label
and a help sentence, the loader takes its defaults from it, a typo warns rather than refuses,
the example and the schema agree, the promoted constants are read where they were, and the
Settings view's Save writes through `setupconfig.edit`."""

import json
import os
import tempfile
import textwrap
import tomllib
import unittest
from dataclasses import MISSING, fields
from datetime import datetime, timedelta
from pathlib import Path
from unittest import mock

from keel import (actions, cardspec, configedit, deploy, deckstate, doctor, onboarding, reviewsettings,
                  settings, shipidle, terms, views)
from keel import config as config_module
from keel.config import Config, Space
from keel.board import open_board
from keel.review import agents
from keel.setupconfig import SetupError
from tests.helpers import make_config
from tests.test_installer import init

ROOT = Path(__file__).resolve().parent.parent


def load_text(directory: Path, text: str) -> Config:
    path = directory / "keel.toml"
    path.write_text(textwrap.dedent(text))
    return config_module.load(path, ensure=False)


class SchemaTest(unittest.TestCase):
    def test_every_setting_has_a_label_and_a_help_sentence_that_says_its_default(self):
        for s in settings.SETTINGS:
            with self.subTest(setting=s.id):
                self.assertTrue(s.label.strip())
                self.assertTrue(s.help.endswith("."), "help is a sentence")
                self.assertRegex(s.help, r"Default|Empty|default", "help says what it falls back to")
                self.assertIn(s.kind, settings.KINDS)
                self.assertIn(s.group, settings.GROUPS)
                self.assertIn(s.table, settings.TABLES)

    def test_every_default_passes_its_own_parse_and_its_choices_hold_it(self):
        for s in settings.SETTINGS:
            with self.subTest(setting=s.id):
                if s.default is not None:
                    self.assertEqual(settings.parse(s, s.default), s.default)
                if s.kind == "choice":
                    self.assertIn(s.default, s.choices)

    def test_no_setting_is_also_a_structural_key(self):
        for table in settings.TABLES:
            mine = {s.key for s in settings.of(table)}
            self.assertEqual(mine & set(settings.STRUCTURAL[table]), set(), table)

    def test_bool_takes_only_true_and_false_and_a_wrong_type_names_key_value_and_type(self):
        paused = settings.find("keel", "drain_paused")
        for bad in ("false", 0, 1, None):
            with self.assertRaises(settings.SettingError) as caught:
                settings.parse(paused, bad)
            self.assertIn("[keel] drain_paused", str(caught.exception))
            self.assertIn("true or false", str(caught.exception))
        houses = settings.find("keel", "houses_max")
        with self.assertRaisesRegex(settings.SettingError, r"\[keel\] houses_max = '3' is not a whole number"):
            settings.parse(houses, "3")
        with self.assertRaisesRegex(settings.SettingError, "from 0 to 32"):
            settings.parse(houses, 99)
        self.assertEqual(settings.parse(settings.find("voice", "vad_hangover"), 2), 2.0)
        model = settings.find("space", "reviewer_model")
        self.assertEqual(settings.parse(model, "inherit"), "inherit")
        self.assertEqual(settings.parse(model, "sonnet"), "sonnet")
        with self.assertRaisesRegex(settings.SettingError, "is not a model"):
            settings.parse(model, "gpt", "work")

    def test_the_card_branch_help_says_exactly_which_branches_are_kept(self):
        """r1.F8: `adapters.card_branch` finds a card's branch under the pattern in force, the
        default and the pre-c-729 `keel/<id>-...`; a card cut under another custom pattern is
        not found, so the help says so and asks for a change only when nothing is in flight."""
        help_text = next(s.help for s in settings.SETTINGS if (s.table, s.key) == ("space", "branch"))
        self.assertNotIn("under another name keeps", help_text)
        self.assertIn("A card cut under the default, or as keel/<id>-... before, keeps its branch.", help_text)
        self.assertIn("Change it when no card of this space is in flight.", help_text)

    def test_a_space_names_its_remote_and_its_card_branch_and_a_bad_one_is_refused(self):
        """c-665: each default is what Keel always did (the branch named for the product since
        c-729); a remote git could not name, a branch
        pattern with no `{id}`, or one git would not take, is refused in a sentence."""
        space = Space(name="s", config_dir=Path("/x"), repos={}, contract=None, adapter=None)
        self.assertEqual((space.remote, space.branch), ("origin", "shipyard/{id}-{slug}"))
        remote, branch = settings.find("space", "remote"), settings.find("space", "branch")
        self.assertEqual(settings.parse(remote, "upstream"), "upstream")
        for bad in ("", "my remote", "-f", "a/b"):
            with self.subTest(remote=bad), self.assertRaises(settings.SettingError):
                settings.parse(remote, bad)
        for good in ("{id}", "cards/{id}/{slug}", "feat/{id}_{slug}", "{slug}/{id}", "x.{id}"):
            self.assertEqual(settings.parse(branch, good), good)
        # review F7: `{id}` stands alone between separators, so one card's glob never takes
        # another's or an unrelated branch, and the name holds for any slug a title can give
        for bad, said in (("work/{slug}", "must contain {id}"), ("{id}{slug}", "must stand"),
                          ("card{id}-{slug}", "must stand"), ("{slug}{id}", "must stand"),
                          ("{id}x", "must stand"), ("{id}.{slug}", "git would not take"),
                          ("{id}/.{slug}", "git would not take"),
                          ("a b/{id}", "git would not take"), ("{id}..x", "git would not take"),
                          ("-{id}", "git would not take"), ("{id}.lock", "git would not take"),
                          ("{id}-" + "x" * 240 + "{slug}", "git would not take"),
                          ("{id}-{name}", "only {id} and {slug}")):
            with self.subTest(branch=bad), self.assertRaises(settings.SettingError) as caught:
                settings.parse(branch, bad, "personal")
            self.assertIn(said, str(caught.exception))
            self.assertIn("[spaces.personal] branch", str(caught.exception))


class LoadTest(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.dir = Path(tmp.name)
        self.head = f'[keel]\nstate_dir = "{self.dir}/state"\n'
        self.space = '[spaces.personal]\nconfig_dir = "~/nowhere"\n'

    def load(self, keel: str = "", space: str = "", tail: str = "") -> Config:
        return load_text(self.dir, self.head + keel + self.space + space + tail)

    def test_an_unknown_key_warns_with_the_closest_real_one(self):
        cfg = self.load(space="house_reveiw = true\n")
        self.assertEqual(cfg.warnings, ["[spaces.personal] house_reveiw is not a key; did you mean house_review?"])
        self.assertTrue(cfg.spaces["personal"].house_review)         # the default, not the typo
        self.assertIn("is not a key", self.load("houses_mx = 2\n").warnings[0])
        self.assertIn("[voice] recrd is not a key; did you mean record?",
                      self.load(tail="[voice]\nrecrd = true\n").warnings)

    def test_structural_keys_never_warn(self):
        cfg = self.load('segments_dir = "segs"\nhost = "mac"\nhouse_nice = 10\n',
                        'contract = "etc/space-personal.md"\ndeny = []\nprojects_dir = "~/p"\n'
                        'pipeline = "etc/pipeline-personal.md"\n[spaces.personal.repos]\nkeel = "."\n',
                        '[voice]\nport = 4390\napp_url = "https://v"\n[voice.judges]\n"narrate" = "shadow"\n')
        self.assertEqual(cfg.warnings, [])

    def test_a_wrong_type_at_load_warns_and_uses_the_default_never_refusing(self):
        """Bosun's condition (c-633): a typo can never keep the deck from starting."""
        cfg = self.load('houses_max = "3"\ndrain_paused = "false"\n', 'review_backlog_days = 0\n',
                        '[voice]\nvad_hangover = "fast"\n')
        self.assertEqual((cfg.houses_max, cfg.drain_paused), (3, True), "a garbled pause pauses")
        self.assertEqual(cfg.spaces["personal"].review_backlog_days, 15)
        self.assertEqual(cfg.voice_vad_hangover, 2.0)
        self.assertEqual(len(cfg.warnings), 4)
        said = "\n".join(cfg.warnings)
        self.assertIn("[keel] houses_max = '3' is not a whole number from 0 to 32; the default (3) is used", said)
        self.assertIn("[keel] drain_paused = 'false' is not true or false; true is used, the safe position", said)
        self.assertIn("[spaces.personal] review_backlog_days = 0", said)
        self.assertIn("[voice] vad_hangover = 'fast' is not a number", said)

    def test_a_pack_s_typo_warns_naming_the_pack(self):
        packs_dir = self.dir / "packs" / "mine"
        packs_dir.mkdir(parents=True)
        (packs_dir / "pack.toml").write_text('name = "mine"\nversion = "1"\ndescription = "d"\n'
                                             '[space]\nhouse_reveiw = false\npreship_first = true\n')
        with mock.patch.dict(os.environ, {"KEEL_HOME": str(self.dir)}):
            cfg = self.load(space='pack = "mine"\n')
        self.assertTrue(cfg.spaces["personal"].preship_first)
        self.assertEqual(cfg.provenance["spaces.personal.preship_first"], "pack")
        self.assertEqual(len(cfg.warnings), 1)
        self.assertIn("the pack mine's [space] (for [spaces.personal]) house_reveiw is not a key", cfg.warnings[0])

    def test_the_shipped_example_loads_with_no_warning(self):
        for name in ("etc/shipyard.example.toml",):
            with self.subTest(file=name):
                self.assertEqual(config_module.load(ROOT / name, ensure=False).warnings, [])

    def test_loaded_defaults_equal_the_dataclass_defaults(self):
        cfg = self.load()
        space = cfg.spaces["personal"]
        for f in fields(Space):
            if settings.find("space", f.name):
                self.assertEqual(getattr(space, f.name), f.default, f.name)
        built = {f.name: f.default for f in fields(Config)}
        for s in settings.SETTINGS:
            if s.scope == "install":
                self.assertEqual(settings.plain(settings.value_of(cfg, s)), settings.plain(s.default), s.id)
                if s.table == "builder":                 # read from `Config.builder` as written (c-632)
                    continue
                if built[s.attr] is not MISSING:         # houses_max and its three peers are required
                    self.assertEqual(built[s.attr], s.default, s.id)

    def test_the_two_aligned_defaults(self):
        cfg = self.load()
        self.assertFalse(cfg.drain_paused)
        self.assertTrue(cfg.spaces["personal"].house_review)


class ExampleTest(unittest.TestCase):
    """c-633, decision example-drift (code): the example and the schema agree on every key
    of `[keel]` and `[voice]` the example sets, but for the six deliberate opt-ins."""

    def test_the_example_and_the_schema_agree_but_for_the_opt_ins(self):
        data = tomllib.loads((ROOT / "etc" / "shipyard.example.toml").read_text())
        differ = set()
        for table in ("keel", "voice"):
            for s in settings.of(table):
                if s.key in data.get(table, {}) and settings.parse(s, data[table][s.key]) != s.default:
                    differ.add((table, s.key))
        self.assertEqual(differ, set(settings.EXAMPLE_OPT_INS))
        self.assertTrue(data["spaces"]["personal"]["house_review"])
        self.assertEqual(settings.default("space", "house_review"), True)


class ReadersTest(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.dir = Path(tmp.name)
        self.cfg = make_config(self.dir)

    def test_autonomy_and_topic_come_from_the_space_and_say_so(self):
        space = self.cfg.spaces["personal"]
        space.autonomy, space.topic = "attended", "boards"
        with open_board(self.cfg) as board:
            card = board.get(board.create("personal", "a thing", actor="human"))
            tags = card["options"]["provenance"]
            self.assertEqual((card["autonomy"], card["topic"]), ("attended", "boards"))
            self.assertEqual((tags["autonomy"], tags["topic"]), ("space_default", "space_default"))
            self.assertIn("attended", cardspec.readback(card, board.defaults))
            self.assertIn("the space default", cardspec.readback(card, board.defaults))

    def test_an_untouched_space_leaves_autonomy_to_keel(self):
        with open_board(self.cfg) as board:
            card = board.get(board.create("personal", "a thing", actor="human"))
        self.assertEqual(card["autonomy"], "autonomous")
        self.assertEqual(card["options"]["provenance"]["autonomy"], "keel_default")

    def test_keel_s_model_is_the_keel_default_layer(self):
        self.cfg.model = "sonnet"
        with open_board(self.cfg) as board:
            card = board.get(board.create("personal", "a thing", actor="human"))
        self.assertEqual(card["model"], "sonnet")
        self.assertEqual(card["options"]["provenance"]["model"], "keel_default")
        sheet = deckstate.options_for(self.cfg.spaces["personal"], self.cfg)
        self.assertEqual(next(e for e in sheet if e["key"] == "model")["default"], "sonnet")

    def test_the_sheet_defaults_autonomy_and_plan_style_to_the_space(self):
        space = self.cfg.spaces["personal"]
        space.autonomy, space.plan_style = "attended", "markdown"
        rows = {e["key"]: e for e in deckstate.options_for(space, self.cfg)}
        self.assertEqual((rows["autonomy"]["default"], rows["plan_style"]["default"]), ("attended", "markdown"))
        from keel import planbrief
        self.assertIn("this space's: `markdown`", planbrief.plan_block(False, "markdown"))
        self.assertNotIn("this space's", planbrief.plan_block(False, "auto"))

    def test_reviewer_model_reaches_the_agents(self):
        both = json.loads(agents.agents_json(model="sonnet"))
        self.assertEqual({a["model"] for a in both.values()}, {"sonnet"})
        self.assertEqual({a["model"] for a in json.loads(agents.agents_json()).values()}, {"inherit"})
        from keel import house
        card = {"id": "c-1", "space": "personal", "repo": "keel", "options": {"review_key": "x"}}
        self.cfg.spaces["personal"].reviewer_model = "haiku"
        with mock.patch.object(house.review_gate, "peer_wanted", return_value=True):
            got = json.loads(house.reviewer_of(self.cfg, card))
        self.assertEqual({a["model"] for a in got.values()}, {"haiku"})

    def test_the_deploy_suite_stops_at_its_setting(self):
        out = self.dir / "suite.log"
        self.assertEqual(deploy.run_suite("sleep 5", self.dir, out, seconds=0.2), 124)

    def test_the_idle_close_and_the_deck_agree_on_the_hours(self):
        self.cfg.ship_idle_hours = 5
        ended = datetime.now().astimezone() - timedelta(hours=3)
        with open_board(self.cfg) as board:
            self.assertEqual(board.ship_idle_hours, 5)
            card_id = board.create("personal", "ships", actor="human")
            board.conn.execute("UPDATE cards SET stage = 'shipping', session_id = 's-1' WHERE id = ?", (card_id,))
            board.conn.execute("INSERT INTO events (card, kind, actor, data, at) VALUES (?, 'hook', 'hook', ?, ?)",
                               (card_id, json.dumps({"hook": "Stop", "session_id": "s-1"}), ended.isoformat()))
            row = board.conn.execute("SELECT * FROM cards WHERE id = ?", (card_id,)).fetchone()
            said = views.ship_idle(board, row)
            self.assertEqual(said["hours"], 5)
            self.assertEqual(datetime.fromisoformat(said["close_at"]) - datetime.fromisoformat(said["since"]),
                             timedelta(hours=5))
            card = board.get(card_id)
            with mock.patch.object(shipidle.idleclose, "close_here") as close:
                self.assertFalse(shipidle.close_idle(self.cfg, board, card, datetime.now().astimezone()))
                close.assert_not_called()      # 3 hours idle is under 5


class WarningsShownTest(unittest.TestCase):
    def test_the_state_document_and_doctor_carry_them(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "keel.toml"
            path.write_text(f'[keel]\nstate_dir = "{tmp}/state"\nhouses_mx = 2\n'
                            '[spaces.personal]\nconfig_dir = "~/nowhere"\n')
            report = {"config": {"path": str(path), "ok": True,
                                 "warnings": config_module.load(path, ensure=False).warnings},
                      "claude": {"ok": True}}
            self.assertTrue(any("houses_mx is not a key" in line for line in doctor.problems(report)))
        source = (ROOT / "keel" / "deckstate.py").read_text()
        self.assertIn('"warnings": list(cfg.warnings)', source)


class SaveTest(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        patch = mock.patch.dict(os.environ)
        patch.start()
        self.addCleanup(patch.stop)
        self.home = Path(tmp.name).resolve() / "install"
        self.assertEqual(init(self.home), 0)
        self.path = self.home / "config.toml"
        self.cfg = config_module.load(self.path, ensure=False)

    def save(self, *changes):
        with open_board(self.cfg) as board:
            return actions.act(self.cfg, board, {"verb": "setup.settings.save", "changes": list(changes)})

    def test_save_writes_every_change_in_one_edit_keeping_the_rest_of_the_file(self):
        before = self.path.read_text()
        done = self.save({"table": "keel", "key": "houses_max", "value": 5},
                         {"table": "space", "space": "personal", "key": "autonomy", "value": "attended"},
                         {"table": "voice", "key": "vad_hangover", "value": 1.5})
        self.assertTrue(done["voice"])
        self.assertEqual(Path(done["backup"]).read_text(), before)        # one backup, the old file
        after = config_module.load(self.path, ensure=False)
        self.assertEqual((after.houses_max, after.spaces["personal"].autonomy, after.voice_vad_hangover),
                         (5, "attended", 1.5))
        self.assertEqual(after.warnings, [])
        kept = [line for line in before.splitlines() if line.lstrip().startswith("#")]
        now = self.path.read_text().splitlines()
        self.assertTrue(all(line in now for line in kept), "a comment was lost")
        with open_board(after) as board:
            card = board.get(board.create("personal", "a thing", actor="human"))
            self.assertIn("attended", cardspec.readback(card, board.defaults))
            self.assertEqual(card["options"]["provenance"]["autonomy"], "space_default")

    def test_a_null_value_removes_the_key_so_the_default_applies(self):
        self.save({"table": "keel", "key": "houses_max", "value": 5})
        self.cfg = config_module.load(self.path, ensure=False)
        self.save({"table": "keel", "key": "houses_max", "value": None},
                  {"table": "keel", "key": "review_asks", "value": None})       # absent: nothing to do
        data = tomllib.loads(self.path.read_text())
        self.assertNotIn("houses_max", data["keel"])
        self.assertEqual(config_module.load(self.path, ensure=False).houses_max, 3)

    def test_a_wrong_value_is_refused_by_name_and_nothing_is_written(self):
        """The other half of Bosun's condition: the form refuses what the loader would only warn about."""
        before = self.path.read_text()
        for change, said in (({"table": "keel", "key": "houses_max", "value": "3"}, "[keel] houses_max = '3'"),
                             ({"table": "keel", "key": "drain_paused", "value": "false"}, "true or false"),
                             ({"table": "space", "space": "personal", "key": "model", "value": "opsu"}, "is not a model"),
                             ({"table": "keel", "key": "houses_mx", "value": 2}, "no setting 'houses_mx'"),
                             ({"table": "space", "space": "nowhere", "key": "autonomy", "value": "attended"}, "no space")):
            with self.subTest(change=change), self.assertRaises(actions.ActionError) as caught:
                self.save({"table": "keel", "key": "rotate", "value": True}, change)
            self.assertIn(said, str(caught.exception))
        self.assertEqual(self.path.read_text(), before)

    def test_a_config_that_is_not_an_install_s_is_refused(self):
        cfg = config_module.load(ROOT / "etc" / "shipyard.example.toml", ensure=False)
        with self.assertRaisesRegex(SetupError, "Setup edits an install only"):
            settings.save(cfg, [{"table": "keel", "key": "houses_max", "value": 2}])
        self.assertIsNone(settings.report(cfg)["install"])

    def test_the_save_re_execs_the_deck_once(self):
        self.assertIn("setup.settings.save", onboarding.CONFIG_VERBS)
        self.assertIn("setup.settings.save", actions.SETUP_VERBS)

    def test_the_gear_s_override_is_shown_and_saving_the_key_clears_it(self):
        reviewsettings.write(self.cfg, "personal", "auto", "on")
        values = settings.report(self.cfg)["values"]["spaces"]["personal"]
        self.assertEqual(values["space.review_auto"], {"value": True, "source": "gear"})
        self.assertEqual(values["space.review_model"]["source"], "default")
        self.save({"table": "space", "space": "personal", "key": "review_auto", "value": False})
        self.assertNotIn("personal", reviewsettings.overrides(self.cfg))
        cfg = config_module.load(self.path, ensure=False)
        self.assertEqual(reviewsettings.effective(cfg, "personal")["auto"], False)
        self.assertEqual(settings.report(cfg)["values"]["spaces"]["personal"]["space.review_auto"]["source"], "config")

    def test_the_report_names_every_setting_and_where_each_value_came_from(self):
        got = settings.report(self.cfg)
        self.assertEqual(got["install"], str(self.home))
        self.assertEqual(len(got["schema"]), len(settings.SETTINGS))
        self.assertEqual(set(got["values"]["install"]), {s.id for s in settings.SETTINGS if s.scope == "install"})
        self.assertEqual(got["values"]["install"]["keel.houses_max"]["source"], "config")
        self.assertEqual(got["values"]["spaces"]["personal"]["space.reviewer_model"],
                         {"value": "inherit", "source": "default"})

    def test_a_voice_change_reloads_a_loaded_gateway_before_the_re_exec(self):
        """Decision voice-apply (reload): in the same quiet moment as the deck's own re-exec."""
        from keel import serve
        for changed in (True, False):
            with mock.patch.object(serve.restart, "due", return_value=(True, "")), \
                 mock.patch.object(serve.voice, "reload_if_loaded") as reload, \
                 mock.patch.object(serve, "restart_process") as again:
                serve.restart_when_quiet(voice_changed=changed)
            self.assertEqual(reload.called, changed)
            again.assert_called_once()

    def test_help_says_each_space_s_own_words(self):
        """c-630: a help that names a change is said in the space's words, the schema's in the core's."""
        got = settings.report(self.cfg)
        row = next(r for r in got["schema"] if r["id"] == "space.review_backlog_days")
        self.assertIn("pull request", row["help"])
        self.assertNotIn("{", row["help"])
        with mock.patch("keel.terms.of", return_value=terms.Terms({"change": "merge request"})):
            worded = settings.space_helps(self.cfg)["personal"]["space.review_backlog_days"]
        self.assertIn("whose merge request has been quiet", worded)

    def test_floats_are_written_as_toml(self):
        self.assertEqual(configedit.literal(1.5), "1.5")
        with self.assertRaises(configedit.EditError):
            configedit.literal(float("nan"))


if __name__ == "__main__":
    unittest.main()
