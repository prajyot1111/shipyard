"""The user's own things are read from the install first (c-722, plan step 4, read side): its
packs and segments win over the checkout's, its config is the only toml read, and the
services it installs are rendered into `<install>/services`, never into the code's `etc/`.

Every name here is a scratch one; nothing assumes the work pack or any personal segment is
in the tree, so the suite passes on a tree without them."""

import builtins
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from keel import backup, configpath, install, packs, service, talker, voice
from keel import config as config_module
from tests.helpers import make_config

ROOT = Path(__file__).resolve().parent.parent
PACK = 'name = "{name}"\nversion = "1"\ndescription = "{where}"\n'
# The pack and the segments an install holds once its owner's things have moved there.
OWN_PACK = "work"
OWN_SEGMENTS = ("daybook", "fathom", "instamart", "cloud-spend", "oci")
INSTALL_TOML = "[keel]\nstate_dir = \"{state}\"\nsegments_dir = \"{segments}\"\n[spaces.personal]\nconfig_dir = \"~/x\"\n"


class InstallCase(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.dir = Path(tmp.name).resolve()
        self.install = self.dir / "install"
        self.code = self.dir / "code"
        self.install.mkdir()
        (self.install / "config.toml").write_text(INSTALL_TOML.format(
            state=self.install / "state", segments=self.install / "segments"))
        env = mock.patch.dict(os.environ, {"KEEL_CONFIG": str(self.install / "config.toml")})
        env.start()
        self.addCleanup(env.stop)
        packs.forget()
        self.addCleanup(packs.forget)

    def cfg(self):
        return config_module.load(self.install / "config.toml", ensure=False)


class PacksAndSegmentsTest(InstallCase):
    def test_the_installs_pack_wins_over_the_checkouts(self):
        for where, root in (("install", self.install), ("checkout", self.code)):
            (root / "packs" / OWN_PACK).mkdir(parents=True)
            (root / "packs" / OWN_PACK / "pack.toml").write_text(PACK.format(name=OWN_PACK, where=where))
        self.assertEqual(packs.roots(self.code)[0], self.install / "packs")
        self.assertEqual(packs.find(OWN_PACK, self.code).description, "install")

    def test_each_of_the_installs_segments_wins_over_the_checkouts(self):
        cfg = self.cfg()
        for name in OWN_SEGMENTS:
            (self.install / "segments" / name).mkdir(parents=True)
        self.assertEqual(cfg.segment_roots[0], (self.install / "segments").resolve())
        for name in OWN_SEGMENTS:
            self.assertEqual(cfg.segment_dir(name), (self.install / "segments").resolve() / name, name)


class ConfigTest(InstallCase):
    def test_the_checkouts_keel_toml_is_never_opened_when_an_install_config_is_named(self):
        opened = []
        real_open = builtins.open

        def spy(file, *args, **kwargs):
            opened.append(Path(file).resolve() if isinstance(file, (str, os.PathLike)) else file)
            return real_open(file, *args, **kwargs)

        shipped = (ROOT / configpath.SHIPPED_CONFIG).resolve()
        with mock.patch("builtins.open", spy):
            cfg = config_module.load()
        self.assertEqual(Path(cfg.source).resolve(), (self.install / "config.toml").resolve())
        self.assertNotIn(shipped, opened)
        self.assertEqual(configpath.config_path(ROOT), (self.install / "config.toml").resolve())
        self.assertEqual(cfg.install_home, self.install)


class ServicesTest(InstallCase):
    def test_every_service_an_install_writes_is_rendered_into_the_install(self):
        cfg = self.cfg()
        services = self.install / "services"
        self.assertEqual(cfg.services_dir, services)
        self.assertEqual(talker.paths_from(cfg).etc, services)
        self.assertEqual(backup.paths_from(cfg, home=self.dir).etc, services)
        self.assertEqual(voice.paths_from(cfg).etc, services)
        written = install.write(cfg, manager=service.Manager(self.dir / "home"))
        self.assertTrue(written and all(path.parent == services for path in written), written)

    def test_a_checkout_with_no_install_keeps_its_etc(self):
        cfg = make_config(self.dir / "plain")
        self.assertEqual(cfg.services_dir, ROOT / "etc")


if __name__ == "__main__":
    unittest.main()
