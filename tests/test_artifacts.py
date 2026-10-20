"""Artifacts: the configured roots, the credential denylist inside them, the markdown
renderer's images and sibling links, and the lavish surface lookup."""

import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from keel import artifacts
from tests.helpers import make_config

PNG = bytes.fromhex("89504e470d0a1a0a")  # enough of a header to be a file, not a picture


class RootsCase(unittest.TestCase):
    """A scratch install with one configured root; no tests of its own."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.dir = Path(self.tmp.name)
        self.archive = self.dir / "plan-archive"
        self.archive.mkdir()
        self.cfg = make_config(self.dir)
        self.cfg.artifact_roots = [self.archive]


class RootsTest(RootsCase):
    def test_a_configured_root_is_servable_and_the_implicit_ones_stay(self):
        plan = self.archive / "a-plan.html"
        plan.write_text("<h1>plan</h1>")
        link = artifacts.url(self.cfg, plan)
        self.assertTrue(link.startswith("/api/artifact/"))
        self.assertEqual(artifacts.untoken(self.cfg, link.split("/")[-1]), plan.resolve())
        card = self.cfg.card_dir("c-001") / "context.md"
        card.write_text("x")
        self.assertTrue(artifacts.url(self.cfg, card).startswith("/api/artifact/"))
        self.assertIn(self.cfg.cards_dir.resolve(), artifacts.roots(self.cfg))
        self.assertIn(self.cfg.segments_dir.resolve(), artifacts.roots(self.cfg))

    def test_a_tilde_path_is_expanded_by_the_loader(self):
        from keel import config as config_module
        resolved = config_module.resolve("~/.claude/plan-archive", self.dir)
        self.assertTrue(resolved.is_absolute())
        self.assertNotIn("~", str(resolved))

    def test_the_denylist_applies_inside_a_configured_root(self):
        for name in (".env", "id_rsa", "site.key", "x.token"):
            path = self.archive / name
            path.write_text("secret")
            self.assertIsNone(artifacts.url(self.cfg, path), name)
        (self.archive / "secrets").mkdir()
        buried = self.archive / "secrets" / "notes.md"
        buried.write_text("x")
        self.assertIsNone(artifacts.url(self.cfg, buried))

    # WHAT A CREDENTIAL LOOKS LIKE, as a table, because this list IS the defence and a gap
    # in it is invisible. Every row is a real path a house can name in a `path` op from
    # inside its own worktree (`keel/boardfiles.py`), which is what turned this from a list
    # of files the deck happened to link into a list an agent can reach for.
    DENIED = [
        ".env", ".env.local", ".env.production", "id_rsa", "id_ed25519", "id_ecdsa.pub",
        "site.key", "x.token", "server.pem", "bundle.p12", "bundle.pfx", ".netrc", ".npmrc",
        ".pypirc", "cookies.txt", "human.token", "artifact.key", "house.key",
        "settings.json", "settings.local.json", "credentials",
        "secrets/notes.md", "credentials/google.json", "myproj/credentials/x.json",
        ".git/config", ".claude/settings.json", ".docker/config.json",
        ".ssh/known_hosts", ".aws/credentials", ".config/keel/credentials/google.json",
    ]
    # And what it does NOT look like. A rule that denied every third file would be worked
    # around rather than kept.
    ALLOWED = ["plan.md", "context.md", "probe.py", "notes/design.md", "shot.png",
               "identity.md", "keys.md", "environment.md", "identify.py"]

    def written(self, index: int, name: str) -> Path:
        """Each row in its own directory: `credentials` is a file on one row and a
        directory on the next, and both have to be reachable in one run."""
        path = self.archive / f"row{index}" / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("x")
        return path

    def test_every_shape_of_credential_is_denied_wherever_it_sits(self):
        for index, name in enumerate(self.DENIED):
            path = self.written(index, name)
            with self.subTest(name=name):
                self.assertTrue(artifacts.denied(path), f"{name} is not denied")
                self.assertIsNone(artifacts.url(self.cfg, path), name)

    def test_the_denylist_does_not_eat_what_a_board_is_for(self):
        for index, name in enumerate(self.ALLOWED):
            path = self.written(index + 500, name)
            with self.subTest(name=name):
                self.assertFalse(artifacts.denied(path), f"{name} is denied and should not be")
                self.assertIsNotNone(artifacts.url(self.cfg, path), name)

    def test_untoken_re_checks_the_roots_on_the_way_out(self):
        plan = self.archive / "a-plan.html"
        plan.write_text("<h1>plan</h1>")
        token = artifacts.token(self.cfg, plan)
        self.assertEqual(artifacts.untoken(self.cfg, token), plan.resolve())
        self.cfg.artifact_roots = []        # the root is taken out of keel.toml
        self.assertIsNone(artifacts.untoken(self.cfg, token))

    def test_a_directory_with_an_index_resolves_to_that_file(self):
        folder = self.archive / "surface"
        folder.mkdir()
        index = folder / "index.html"
        index.write_text("<h1>hi</h1>")
        self.assertEqual(artifacts.servable(self.cfg, folder), index.resolve())
        link = artifacts.url(self.cfg, folder)
        self.assertEqual(artifacts.untoken(self.cfg, link.split("/")[-1]), index.resolve())
        empty = self.archive / "nothing"
        empty.mkdir()
        self.assertIsNone(artifacts.url(self.cfg, empty))


class HeldPathsTest(RootsCase):
    """One build resolves each directory once (c-638): the same answers as `Path.resolve`,
    a symlink out of the roots refused as before, and a missing directory asked once."""

    def test_held_resolution_answers_as_resolve_does(self):
        real = self.dir / "real"
        (real / "sub").mkdir(parents=True)
        (real / "sub" / "f.md").write_text("x")
        (self.dir / "linkdir").symlink_to(real)
        (real / "sub" / "alias.md").symlink_to(real / "sub" / "f.md")
        paths = [real / "sub" / "f.md", self.dir / "linkdir" / "sub" / "f.md",
                 real / "sub" / "alias.md", self.dir / "linkdir" / "nope" / "x.md",
                 self.dir / "gone" / "deeper" / "x.md", self.dir / "real" / ".." / "real"]
        with artifacts.roots_held(self.cfg):
            for path in paths:
                self.assertEqual(artifacts.resolved(path), path.resolve(), path)

    def test_a_symlink_out_of_the_roots_is_still_refused(self):
        outside = self.dir.parent / f"{self.dir.name}-outside.md"
        outside.write_text("secret")
        self.addCleanup(outside.unlink)
        card = self.cfg.card_dir("c-001")
        (card / "escape.md").symlink_to(outside)
        with artifacts.roots_held(self.cfg):
            self.assertIsNone(artifacts.url(self.cfg, card / "escape.md"))
            (card / "plain.md").write_text("ok")
            self.assertTrue(artifacts.url(self.cfg, card / "plain.md").startswith("/api/artifact/"))

    def test_a_missing_directory_is_asked_of_the_disk_once(self):
        """Refs left from another machine (`/home/ubuntu/...`) sit under macOS's `/home`
        automount, where each look cost 11 ms: the deck asked several per card per build."""
        gone = self.dir / "home" / "ubuntu" / "keel"
        looked = []
        real_lstat, real_stat = artifacts.os.lstat, artifacts.os.stat

        def watched(real):
            def call(path, *args, **kwargs):
                looked.append(str(path))
                return real(path, *args, **kwargs)
            return call
        with mock.patch.object(artifacts.os, "lstat", side_effect=watched(real_lstat)), \
                mock.patch.object(artifacts.os, "stat", side_effect=watched(real_stat)), \
                artifacts.roots_held(self.cfg):
            for name in ("a.md", "b.md", "c/d.md"):
                self.assertIsNone(artifacts.url(self.cfg, gone / name))
        homes = (str(self.dir / "home"), str(self.dir.resolve() / "home"))   # /var is /private/var
        self.assertEqual(sum(1 for path in looked if path.startswith(homes)), 1, looked)


class MarkdownTest(unittest.TestCase):
    """A card's context file, rendered the way `GET /api/artifact/<token>` renders it."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.dir = Path(self.tmp.name)
        self.cfg = make_config(self.dir)
        self.card = self.cfg.card_dir("c-255")
        (self.card / "assets").mkdir()
        self.shot = self.card / "assets" / "x.png"
        self.shot.write_bytes(PNG)
        self.sibling = self.card / "plan.md"
        self.sibling.write_text("# Plan\n")

    def render(self, text):
        return artifacts.markdown_html(text, "context.md", base_dir=self.card, cfg=self.cfg)

    def src_of(self, html):
        match = __import__("re").search(r'<img src="/api/artifact/([^"]+)" alt="([^"]*)">', html)
        self.assertIsNotNone(match, html)
        return match.group(1), match.group(2)

    def test_a_relative_image_becomes_a_token_that_resolves_to_the_file(self):
        html = self.render("Evidence:\n\n![the shot](assets/x.png)\n")
        token, alt = self.src_of(html)
        self.assertEqual(artifacts.untoken(self.cfg, token), self.shot.resolve())
        self.assertEqual(alt, "the shot")

    def test_an_absolute_image_under_a_root_works_too(self):
        html = self.render(f"![shot]({self.shot})\n")
        token, _ = self.src_of(html)
        self.assertEqual(artifacts.untoken(self.cfg, token), self.shot.resolve())

    def test_an_escape_out_of_the_card_renders_no_image(self):
        html = self.render("![keys](../../.ssh/id_rsa)\n")
        self.assertNotIn("<img", html)
        self.assertIn("keys", html)
        self.assertIn('class="unserved"', html)

    def test_an_absolute_path_outside_the_roots_renders_no_image(self):
        html = self.render("![](/etc/passwd)\n")
        self.assertNotIn("<img", html)
        self.assertIn("/etc/passwd", html)

    def test_a_missing_file_and_a_remote_image_say_why(self):
        self.assertIn("no such file", self.render("![x](assets/gone.png)\n"))
        self.assertNotIn("<img", self.render("![x](https://example.test/a.png)\n"))

    def test_a_relative_link_to_a_sibling_becomes_a_token_link(self):
        html = self.render("See [the plan](plan.md) for the shape.\n")
        match = __import__("re").search(r'<a href="/api/artifact/([^"]+)">the plan</a>', html)
        self.assertIsNotNone(match, html)
        self.assertEqual(artifacts.untoken(self.cfg, match.group(1)), self.sibling.resolve())

    def test_a_clip_a_card_links_is_served_as_sound_and_not_as_a_blob(self):
        """Some work can only be judged by ear, and c-316 is the first of it: a house
        speaks in its own voice, and no test can say whether the handoff is heard. A clip
        beside a context file becomes a token link like any other local asset, and the type
        is what decides whether the phone plays it where he is reading or downloads it."""
        clip = self.card / "assets" / "handoff.wav"
        clip.write_bytes(b"RIFF....WAVEfmt ")
        html = self.render("Hear it: [the handoff](assets/handoff.wav)\n")
        match = __import__("re").search(
            r'<a href="/api/artifact/([^"]+)">the handoff</a>', html)
        self.assertIsNotNone(match, html)
        self.assertEqual(artifacts.untoken(self.cfg, match.group(1)), clip.resolve())
        self.assertEqual(artifacts.mime(clip), "audio/wav")

    def test_an_http_link_is_left_alone_and_a_dead_one_is_muted(self):
        html = self.render("[a pr](https://example.test/pr/1) and [gone](nowhere.md)\n")
        self.assertIn('<a href="https://example.test/pr/1">a pr</a>', html)
        self.assertIn('class="unserved"', html)
        self.assertNotIn('href="None"', html)

    def test_nothing_from_the_document_lands_unescaped_in_the_markup(self):
        html = self.render('![" onerror="alert(1)](assets/x.png)\n\n<script>bad()</script>\n')
        self.assertNotIn('onerror="alert(1)"', html)
        self.assertIn("&quot;", html)
        self.assertNotIn("<script>", html)

    def test_without_a_config_the_picture_is_its_alt_text(self):
        html = artifacts.markdown_html("![a shot](assets/x.png)\n", "t")
        self.assertNotIn("<img", html)
        self.assertIn("a shot", html)


class LavishSurfaceTest(unittest.TestCase):
    """The lookup reads lavish's own session file. The shape below was copied from the real
    `~/.lavish-axi/state.json` on 2026-09-17: a `sessions` object keyed by session key, each
    with `key`, `file`, `url` (lavish's own loopback port), `status` and `pending_prompts`."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.dir = Path(self.tmp.name)
        self.cfg = make_config(self.dir)
        self.plan = self.cfg.card_dir("c-300") / "plan.html"
        self.plan.write_text("<h1>plan</h1>")
        self.ended = self.cfg.card_dir("c-301") / "plan.html"
        self.ended.write_text("<h1>old</h1>")
        self.state = self.dir / "lavish-state.json"
        self.cfg.lavish_state = self.state
        self.write({
            "dc769d711716cc0a": {
                "key": "dc769d711716cc0a", "file": str(self.plan),
                "url": "http://127.0.0.1:4387/session/dc769d711716cc0a",
                "status": "feedback", "pending_prompts": 1, "updated_at": "2026-09-17T09:00:00+05:30"},
            "0bd161f77204f8df": {
                "key": "0bd161f77204f8df", "file": str(self.ended),
                "url": "http://127.0.0.1:4387/session/0bd161f77204f8df",
                "status": "ended", "pending_prompts": 0, "updated_at": "2026-09-16T22:04:00+05:30"},
        })

    def write(self, sessions):
        artifacts._surface_cache = None
        self.state.write_text(json.dumps({"sessions": sessions}))

    def test_a_live_session_is_a_path_on_this_origin(self):
        self.assertEqual(artifacts.lavish_surface(self.cfg, self.plan), "/session/dc769d711716cc0a")
        self.assertNotIn("127.0.0.1", artifacts.lavish_surface(self.cfg, self.plan))

    def test_an_ended_session_a_stranger_and_a_url_are_all_none(self):
        self.assertIsNone(artifacts.lavish_surface(self.cfg, self.ended))
        self.assertIsNone(artifacts.lavish_surface(self.cfg, self.cfg.card_dir("c-300") / "other.html"))
        self.assertIsNone(artifacts.lavish_surface(self.cfg, "https://example.test/plan"))
        self.assertIsNone(artifacts.lavish_surface(self.cfg, None))

    def test_the_newest_session_wins_when_a_file_was_opened_twice(self):
        self.write({
            "aaa": {"key": "aaa", "file": str(self.plan), "status": "open", "updated_at": "2026-09-15T10:00:00+05:30"},
            "bbb": {"key": "bbb", "file": str(self.plan), "status": "open", "updated_at": "2026-09-17T10:00:00+05:30"},
        })
        self.assertEqual(artifacts.lavish_surface(self.cfg, self.plan), "/session/bbb")

    def test_a_missing_or_broken_state_file_is_not_an_error(self):
        self.cfg.lavish_state = self.dir / "nowhere.json"
        self.assertIsNone(artifacts.lavish_surface(self.cfg, self.plan))
        self.cfg.lavish_state = self.state
        artifacts._surface_cache = None
        self.state.write_text("{not json")
        self.assertIsNone(artifacts.lavish_surface(self.cfg, self.plan))


if __name__ == "__main__":
    unittest.main()
