"""Lane RETIRE, RT-2: the review fetcher's two settings live in keel.toml, with a live
override the deck's gear writes under state/, and nothing reads the old scanner's files."""

import json
import tempfile
import textwrap
import unittest
from pathlib import Path

from keel import config, reviewsettings
from tests.helpers import make_config

ROOT = Path(__file__).resolve().parent.parent


class ConfigTest(unittest.TestCase):

    def test_a_space_that_names_neither_is_off_and_sonnet(self):
        with tempfile.TemporaryDirectory() as tmp:
            cfg = make_config(Path(tmp))
            self.assertEqual(reviewsettings.effective(cfg, "work"), {"auto": False, "model": "sonnet"})

    def test_a_review_model_that_is_not_a_model_is_a_config_warning(self):
        with tempfile.TemporaryDirectory() as tmp:
            toml = Path(tmp) / "keel.toml"
            toml.write_text(textwrap.dedent(f"""\
                [keel]
                state_dir = "{tmp}/state"
                [spaces.work]
                config_dir = "{tmp}/cfg"
                review_model = "gpt"
                """))
            cfg = config.load(toml, ensure=False)       # c-633: warned, never refused
            self.assertIsNone(cfg.spaces["work"].review_model)
            self.assertIn("review_model = 'gpt' is not a model", cfg.warnings[0])


class OverrideTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.cfg = make_config(Path(self.tmp.name))
        self.cfg.spaces["work"].review_auto = False
        self.cfg.spaces["work"].review_model = "opus"

    def test_the_toml_values_hold_until_the_gear_sets_one(self):
        self.assertEqual(reviewsettings.effective(self.cfg, "work"), {"auto": False, "model": "opus"})

    def test_the_gear_writes_an_override_under_state_never_the_toml(self):
        after = reviewsettings.write(self.cfg, "work", "auto", "on")
        self.assertEqual(after, {"auto": True, "model": "opus"})
        after = reviewsettings.write(self.cfg, "work", "model", "sonnet")
        self.assertEqual(after, {"auto": True, "model": "sonnet"})
        stored = json.loads((self.cfg.state_dir / "review-settings.json").read_text())
        self.assertEqual(stored, {"work": {"auto": True, "model": "sonnet"}})
        self.assertEqual(reviewsettings.effective(self.cfg, "work"), {"auto": True, "model": "sonnet"})

    def test_a_value_it_may_not_set_is_refused_and_nothing_is_written(self):
        for key, value in (("auto", "maybe"), ("model", "gpt"), ("model", ""), ("colour", "on")):
            with self.assertRaises(reviewsettings.SettingError):
                reviewsettings.write(self.cfg, "work", key, value)
        self.assertFalse((self.cfg.state_dir / "review-settings.json").exists())

    def test_a_hand_edited_bad_override_falls_back_to_the_toml(self):
        (self.cfg.state_dir / "review-settings.json").write_text(
            json.dumps({"work": {"auto": "yes", "model": "gpt"}}))
        self.assertEqual(reviewsettings.effective(self.cfg, "work"), {"auto": False, "model": "opus"})


if __name__ == "__main__":
    unittest.main()
