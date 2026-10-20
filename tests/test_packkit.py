"""The pack kit's own machinery (c-735): the reference stand-in meets the contract it states,
`check_layer` names a layer it cannot run in one sentence, and a bound pack's words are
its own `[terms]`.

The host-independent flows are held through the packs on the kit (each pack's suite, and
its conformance subclasses); this is what holds the kit itself.
"""

import os
import types
import unittest
from pathlib import Path

from keel.packkit import VERSION, pack, rest, standin
from keel.packkit.errors import HostError, NotFound, SignedOut
from keel.packkit.conformance import HostContract
from keel.packkit.layer import OPERATIONS, LayerError, Repo, check_layer, fold_checks
from keel.packkit.world import World

ROOT = Path(__file__).resolve().parent.parent


class StandinHost(HostContract, unittest.TestCase):
    """The contract made runnable: the kit's own stand-in, over a world in this process."""

    def host_layer(self):
        return standin

    def host_repo(self, name: str):
        return Repo(name, standin.BASE, None)

    def host_serve(self, world: World) -> None:
        standin.use(world)


class CheckLayerTest(unittest.TestCase):
    def layer(self, **over) -> types.ModuleType:
        made = types.ModuleType("made_layer")
        made.KIT, made.HOST = VERSION, standin.HOST
        for name in OPERATIONS:
            setattr(made, name, getattr(standin, name))
        for name, value in over.items():
            if value is None:
                delattr(made, name)
            else:
                setattr(made, name, value)
        return made

    def test_the_reference_stand_in_is_a_layer_the_kit_can_run(self):
        check_layer(standin)

    def test_a_layer_without_operations_is_named_in_one_sentence(self):
        with self.assertRaises(LayerError) as said:
            check_layer(self.layer(reply=None, mine=None), "made_layer")
        self.assertEqual(str(said.exception), "the made_layer layer lacks reply and mine, which the kit calls")

    def test_a_layer_for_another_kit_or_with_no_host_is_refused(self):
        with self.assertRaisesRegex(LayerError, f"written for pack kit 99, and this Shipyard's pack kit is {VERSION}"):
            check_layer(self.layer(KIT=99), "made_layer")
        with self.assertRaisesRegex(LayerError, "written for no pack kit"):
            check_layer(self.layer(KIT=None), "made_layer")
        with self.assertRaisesRegex(LayerError, "has no HOST"):
            check_layer(self.layer(HOST=None), "made_layer")


class WordsTest(unittest.TestCase):
    def setUp(self):
        import sys
        bound, path = pack._bound, list(sys.path)

        def put_back():
            pack._bound = bound
            sys.path[:] = path
        self.addCleanup(put_back)

    def test_a_bound_pack_s_words_are_its_own_terms_and_its_host_s_name(self):
        words = pack.bind(ROOT / "packs" / "github", "gh_layer")
        said = pack.words()
        self.assertEqual((said.change, said.changes, said.short, said.host, said.on),
                         ("pull request", "pull requests", "PR", "GitHub", "on GitHub"))
        self.assertEqual(words.dir, (ROOT / "packs" / "github").resolve())

    def test_a_pack_with_no_terms_says_the_engine_s_own_words(self):
        from keel import terms
        self.assertEqual(pack.terms_of(ROOT / "packs" / "nowhere")["change"], terms.DEFAULTS["change"])


class BindingLeftAsFoundTest(unittest.TestCase):
    def test_binding_a_pack_in_a_test_leaves_the_process_as_it_found_it(self):
        """r1.F8: the words test binds the GitHub pack; the binding and the path are put back."""
        import sys
        before, path = pack._bound, list(sys.path)
        result = unittest.TestResult()
        WordsTest("test_a_bound_pack_s_words_are_its_own_terms_and_its_host_s_name").run(result)
        self.assertTrue(result.wasSuccessful(), result.failures + result.errors)
        self.assertIs(pack._bound, before)
        self.assertEqual(sys.path, path)


class ShapesTest(unittest.TestCase):
    def test_the_checks_fold_into_one_word_a_failure_first(self):
        self.assertEqual(fold_checks([]), {"state": "none"})
        self.assertEqual(fold_checks([{"state": "passed"}, {"state": "running"}]), {"state": "running"})
        self.assertEqual(fold_checks([{"state": "running"}, {"state": "failed", "name": "t", "url": "u", "at": "a"}]),
                         {"state": "failed", "name": "t", "url": "u", "at": "a"})


class ShipAccountsTest(unittest.TestCase):
    """r1.F6: a card with changes on two hosts whose signed-in accounts differ. Each change's
    markers are matched against the account of its own host, so a marker another account left
    is not taken as this one's reply."""

    def test_each_repo_s_markers_are_matched_against_its_own_account(self):
        from unittest import mock
        from keel.packkit import ship
        a, b = Repo("o/a", "https://a.example", None), Repo("o/b", "https://b.example", None)
        accounts = {a.base: "me-a", b.base: "me-b"}
        said = {"o/a": [{"author": "me-a", "body": "Thanks.\n\n" + ship.marker("cg1", "Thanks.")}],
                "o/b": [{"author": "me-a", "body": "Fixed.\n\n" + ship.marker("cg2", "Fixed.")}]}
        posted = []
        layer = types.SimpleNamespace(
            account=lambda repo, timeout=30: accounts[repo.base],
            said=lambda repo, number, parts: {"general": said[str(repo)], "lines": []},
            comment=lambda repo, number, text: posted.append(str(repo)),
            reply=lambda repo, number, under, text: posted.append(str(repo)))
        repos = {"a": a, "b": b}
        replies = [{"handle": "cg1", "text": "Thanks."}, {"handle": "b.cg2", "text": "Fixed."}]
        with mock.patch.object(pack, "layer", lambda: layer), mock.patch.object(pack, "host", lambda: standin.HOST), \
                mock.patch.object(ship.gc, "host_repo", lambda card, key: repos[key]):
            me = ship.signed_in_as(repos)
            done, _ = ship.post({"id": "c-1"}, [{"repo": "a", "pr": 1}, {"repo": "b", "pr": 2}], replies, me)
        self.assertEqual(me, {"a": "me-a", "b": "me-b"})
        self.assertEqual((done, posted), (["b.cg2"], ["o/b"]))


class RestTest(unittest.TestCase):
    """The kit's HTTP transport (`rest.py`), against a server that answers each path one way,
    with git's sign-in from a helper that hands over a marker."""

    ANSWERS = {"/api/v1/moved": (302, b"", {"Location": "http://elsewhere.example/"}),
               "/api/v1/html": (200, b"<html>a login page</html>", {}),
               "/api/v1/out": (401, b'{"message": "token is required"}', {}),
               "/api/v1/gone": (404, b'{"message": "The target couldn\'t be found."}', {}),
               "/api/v1/ok": (200, b'{"login": "me"}', {})}

    def setUp(self):
        import tempfile
        import threading
        from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
        from unittest import mock
        answers, self.heard = self.ANSWERS, []

        class Handler(BaseHTTPRequestHandler):
            def do_GET(self):
                outer.heard.append(self.headers.get("Authorization"))
                status, body, headers = answers.get(self.path.split("?")[0], (500, b"", {}))
                self.send_response(status)
                for key, value in headers.items():
                    self.send_header(key, value)
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def log_message(self, *args):
                pass
        outer = self
        server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        threading.Thread(target=server.serve_forever, daemon=True).start()
        self.addCleanup(server.server_close)
        self.addCleanup(server.shutdown)
        self.base = f"http://127.0.0.1:{server.server_address[1]}"
        folder = tempfile.TemporaryDirectory(prefix="keel-rest-")
        self.addCleanup(folder.cleanup)
        self.helper = Path(folder.name) / "helper"
        self.helper.write_text("#!/bin/sh\ntest \"$1\" = get || exit 0\nprintf 'username=me\\npassword=marker\\n'\n")
        self.helper.chmod(0o755)
        env = {"GIT_CONFIG_COUNT": "2", "GIT_CONFIG_KEY_0": "credential.helper", "GIT_CONFIG_VALUE_0": "",
               "GIT_CONFIG_KEY_1": "credential.helper", "GIT_CONFIG_VALUE_1": str(self.helper)}
        patcher = mock.patch.dict(os.environ, env)
        patcher.start()
        self.addCleanup(patcher.stop)
        self.api = rest.Rest("Host")

    def test_an_answer_is_read_as_json_with_git_s_sign_in(self):
        import base64
        self.assertEqual(self.api.get(self.base, "ok"), {"login": "me"})
        self.assertEqual(self.heard, ["Basic " + base64.b64encode(b"me:marker").decode()])

    def test_each_failure_is_the_kit_s_error_in_one_sentence(self):
        cases = (("moved", HostError, "answered with a redirect, which is not followed"),
                 ("html", HostError, "answered something that is not JSON"),
                 ("out", SignedOut, "git has no sign-in for 127.0.0.1"),
                 ("gone", NotFound, "GET gone failed (HTTP 404): The target couldn't be found"))
        for path, kind, words in cases:
            with self.assertRaises(kind, msg=path) as said:
                self.api.get(self.base, path)
            self.assertIn(words, str(said.exception))
            self.assertEqual(len(str(said.exception).splitlines()), 1)
            self.assertNotIn("marker", str(said.exception))
        self.assertEqual(len(self.heard), 4)               # the redirect was never followed

    def test_no_sign_in_kept_for_the_address_is_signed_out_before_anything_is_asked(self):
        self.helper.write_text("#!/bin/sh\nexit 0\n")
        with self.assertRaises(SignedOut):
            self.api.get(self.base, "ok")
        self.assertEqual(self.heard, [])


if __name__ == "__main__":
    unittest.main()
