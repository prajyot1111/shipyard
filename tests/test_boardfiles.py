"""The board's files, both ways (K6, K7, K8).

Four things are held here that nothing else would catch:

1. **The store never opens a path a push named.** The bytes are read by whoever is pushing,
   against roots it is allowed to read, and handed over; a `path` op naming something else
   is refused before anything is drawn, and one that arrives with no bytes behind it is the
   metadata row stage one drew and not a download.
2. **The copy is servable, and only the copy.** A `file` frame's Download is an artifact
   token minted for the copy under the board's own directory, with the board's own ceiling.
3. **His drop is the segments' control.** Same caps, same type table checked against the
   file's own bytes, same generated name, same de-duplication, same same-origin rule, and
   the card is told a file arrived.
4. **A house is held to its own card on the attach too**, or the hop that carries bytes
   would be the hole the push itself is not.
"""

import json
import os
import subprocess
import tempfile
import unittest
from pathlib import Path

from keel import artifacts, boardfiles, boards, serve
from keel.board import Board
from tests import test_serve as deck_tests
from tests.helpers import make_config

ROOT = Path(__file__).resolve().parent.parent
PNG = b"\x89PNG\r\n\x1a\n" + b"a picture of a graph" * 8
PDF = b"%PDF-1.4\n" + b"an invoice" * 16


class FileCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name)
        self.cfg = make_config(self.dir)
        self.cfg.serve_port = 8791
        self.board = Board(self.cfg.db_path)
        self.card = self.board.create("personal", "a card with a file", repo="keel", actor="human")
        self.addCleanup(self.board.close)
        self.addCleanup(self.tmp.cleanup)
        self.source = {"kind": "card", "card": self.card}

    def card_file(self, name: str, text: str = "print('probe')\n") -> Path:
        path = self.cfg.card_dir(self.card) / name
        path.write_text(text)
        return path

    def ops_for(self, path: Path, size: str = "2 KB") -> str:
        return f'path board "{path}" size "{size}" from house'

    def push_with(self, path: Path) -> dict:
        boardfiles.attach(self.cfg, self.source, str(path), path.read_bytes())
        return boards.push(self.cfg, self.ops_for(path), card=self.card)


class ReadingTest(FileCase):
    """What may be read, on the side that has the file."""

    def roots(self) -> list[Path]:
        return [self.dir / "worktree", self.cfg.card_dir(self.card)]

    def setUp(self):
        super().setUp()
        (self.dir / "worktree").mkdir()

    def test_a_file_under_the_card_or_the_worktree_is_read(self):
        inside = self.card_file("probe.py")
        self.assertEqual(boardfiles.read_local(str(inside), self.roots()), inside.read_bytes())
        work = self.dir / "worktree" / "notes.md"
        work.write_text("# notes\n")
        self.assertEqual(boardfiles.read_local(str(work), self.roots()), b"# notes\n")

    def test_a_path_outside_every_root_is_refused_with_the_reason(self):
        outside = self.dir / "elsewhere.txt"
        outside.write_text("not yours")
        with self.assertRaises(boardfiles.BoardFileError) as caught:
            boardfiles.read_local(str(outside), self.roots())
        self.assertIn("outside what may go on a board", str(caught.exception))

    def test_a_symlink_that_leaves_the_roots_is_refused_rather_than_followed(self):
        """Resolution comes FIRST and containment is checked against the result, so a link
        inside the worktree pointing at /etc/passwd fails the check instead of reading
        through it."""
        outside = self.dir / "secret.txt"
        outside.write_text("not yours either")
        link = self.dir / "worktree" / "innocent.txt"
        link.symlink_to(outside)
        with self.assertRaises(boardfiles.BoardFileError) as caught:
            boardfiles.read_local(str(link), self.roots())
        self.assertIn("outside what may go on a board", str(caught.exception))

    def test_a_credential_is_refused_wherever_it_sits(self):
        secret = self.cfg.card_dir(self.card) / "deploy.key"
        secret.write_text("-----BEGIN-----\n")
        with self.assertRaises(boardfiles.BoardFileError) as caught:
            boardfiles.read_local(str(secret), self.roots())
        self.assertIn("credential", str(caught.exception))

    def test_a_file_past_the_cap_is_refused_before_it_is_read(self):
        big = self.cfg.card_dir(self.card) / "dump.bin"
        big.write_bytes(b"x" * (boardfiles.MAX_BYTES + 1))
        with self.assertRaises(boardfiles.BoardFileError) as caught:
            boardfiles.read_local(str(big), self.roots())
        self.assertIn(boardfiles.CAP_SAID, str(caught.exception))

    def test_a_directory_and_a_missing_file_are_refused(self):
        for target in (self.cfg.card_dir(self.card), self.cfg.card_dir(self.card) / "ghost"):
            with self.assertRaises(boardfiles.BoardFileError):
                boardfiles.read_local(str(target), self.roots())


class TalkerRootTest(FileCase):
    """C2 (2026-09-23): the talker reads files from its OWN folder, and only there.

    The box's voice.log, 2026-09-21: "keel board: nothing was drawn: board-b-002-lines.txt
    is not a file on this machine". Harbor wrote the file in `talker/` (where its turns run)
    and the push ran from the checkout, so the relative path resolved one level up. And the
    talker's root was the whole checkout, `state/` included.
    """

    def setUp(self):
        super().setUp()
        self.root = self.dir / "checkout"
        (self.root / "talker" / "home" / "3").mkdir(parents=True)
        (self.root / "state").mkdir()
        self.cfg.root = self.root
        self.talker = {"kind": "talker", "card": None}

    def test_the_talkers_root_is_its_own_folder_not_the_checkout(self):
        roots = boardfiles.local_roots(self.cfg, self.talker, cwd=self.root)
        self.assertEqual(roots, [self.root / "talker"])
        kept = self.root / "state" / "board.db"
        kept.write_text("his board")
        with self.assertRaises(boardfiles.BoardFileError) as caught:
            boardfiles.read_local(str(kept), roots)
        self.assertIn("outside what may go on a board", str(caught.exception))

    def test_a_relative_path_is_read_from_the_talkers_folder_whatever_the_cwd(self):
        (self.root / "talker" / "board-b-002-lines.txt").write_text("fifty lines\n")
        roots = boardfiles.local_roots(self.cfg, self.talker, cwd=self.root)
        base = boardfiles.local_base(self.cfg, self.talker, cwd=self.root)
        self.assertEqual(boardfiles.read_local("board-b-002-lines.txt", roots, base=base),
                         b"fifty lines\n")

    def test_a_typed_session_inside_the_talkers_folder_keeps_its_own_cwd(self):
        run = self.root / "talker" / "home" / "3"
        (run / "notes.md").write_text("# here\n")
        base = boardfiles.local_base(self.cfg, self.talker, cwd=run)
        roots = boardfiles.local_roots(self.cfg, self.talker, cwd=run)
        self.assertEqual(boardfiles.read_local("notes.md", roots, base=base), b"# here\n")

    def test_a_house_keeps_its_worktree_and_its_card(self):
        roots = boardfiles.local_roots(self.cfg, self.source, cwd=self.dir)
        self.assertEqual(roots, [self.dir, self.cfg.card_dir(self.card)])


class CarryTest(FileCase):
    """The push carries what it names, and refuses whole when it cannot."""

    def test_a_pushed_file_is_copied_into_the_boards_own_directory(self):
        probe = self.card_file("probe.py")
        result = self.push_with(probe)
        self.assertEqual(result["files"], 1)
        record = boards.read_record(self.cfg, "b-001")
        entry = record["files"][str(probe)]
        copy = Path(entry["file"])
        self.assertTrue(copy.is_file(), entry)
        self.assertEqual(copy.read_bytes(), probe.read_bytes())
        self.assertEqual(copy.parent, self.cfg.card_dir(self.card) / artifacts.BOARD_FILES)
        self.assertTrue(copy.name.endswith("-probe.py"), copy.name)

    def test_the_copy_is_named_twice_over_for_two_different_readers(self):
        """The name ON DISK carries a fingerprint so two files can share a basename; the
        name on the BOARD is what the house called it, because a fingerprint is right for a
        filename and wrong for a person."""
        probe = self.card_file("probe.py")
        self.push_with(probe)
        entry = boards.api_board(self.cfg, "b-001")["files"][str(probe)]
        self.assertEqual(entry["name"], "probe.py")
        self.assertTrue(entry["stored"].endswith("-probe.py"))
        self.assertNotEqual(entry["name"], entry["stored"])

    def test_the_copy_survives_the_original_being_deleted(self):
        """A board is a RECORD: what he was shown is still there after the worktree it came
        from is reaped."""
        probe = self.card_file("probe.py")
        self.push_with(probe)
        probe.unlink()
        entry = boards.read_record(self.cfg, "b-001")["files"][str(probe)]
        self.assertTrue(Path(entry["file"]).is_file())
        self.assertIsNotNone(boards.api_board(self.cfg, "b-001")["files"][str(probe)]["url"])

    def test_the_same_file_pushed_twice_is_stored_once(self):
        probe = self.card_file("probe.py")
        self.push_with(probe)
        first = Path(boards.read_record(self.cfg, "b-001")["files"][str(probe)]["file"])
        self.push_with(probe)
        directory = self.cfg.card_dir(self.card) / artifacts.BOARD_FILES
        self.assertEqual([p.name for p in directory.iterdir()], [first.name])

    def test_a_path_op_with_no_bytes_behind_it_is_the_row_stage_one_drew(self):
        """An older `keel board`, or a push typed by hand, still gets its metadata row: the
        deck draws it with no download under it rather than refusing the frame."""
        probe = self.card_file("probe.py")
        boards.push(self.cfg, self.ops_for(probe), card=self.card)
        record = boards.read_record(self.cfg, "b-001")
        self.assertEqual(record["files"], {})
        self.assertEqual(record["attachments"], 1)
        self.assertEqual(boards.api_board(self.cfg, "b-001")["files"], {})

    def test_carry_refuses_the_whole_push_when_a_file_cannot_be_read(self):
        """Nothing is drawn: a board that says a file is there when it is not is worse than
        a push that did not happen."""
        outside = self.dir / "elsewhere.txt"
        outside.write_text("not yours")
        with self.assertRaises(boards.BoardError) as caught:
            boards.carry(self.cfg, self.source, self.ops_for(outside),
                         attach=lambda path, blob: boardfiles.attach(self.cfg, self.source, path, blob))
        self.assertIn("nothing was drawn", str(caught.exception))

    def test_path_ops_lists_every_path_once_in_order(self):
        ops = ('path board "/a/one.txt" size "1 KB" from house\n'
               'path board "/a/two.txt" size "1 KB" from house\n'
               'path "/a/one.txt" size "1 KB" from house\nnot an op at all')
        self.assertEqual(boards.path_ops(ops), ["/a/one.txt", "/a/two.txt"])

    def test_a_talker_boards_files_live_under_the_board(self):
        source = {"kind": "talker", "card": None}
        loose = self.dir / "worktree"
        loose.mkdir()
        note = loose / "harbor.md"
        note.write_text("# what I drew\n")
        boardfiles.attach(self.cfg, source, str(note), note.read_bytes())
        boards.push(self.cfg, f'path board "{note}" size "1 KB" from talker',
                    talker=True, actor="talker")
        entry = boards.read_record(self.cfg, "b-001")["files"][str(note)]
        self.assertEqual(Path(entry["file"]).parent,
                         boards.board_dir(self.cfg, "b-001") / artifacts.BOARD_TALKER_FILES)
        self.assertIsNotNone(artifacts.url(self.cfg, entry["file"]),
                             "a talker board's files are servable too")

    def test_a_staged_file_nobody_pushed_is_pruned(self):
        probe = self.card_file("probe.py")
        boardfiles.attach(self.cfg, self.source, str(probe), probe.read_bytes())
        staged = boardfiles.attached_dir(self.cfg, self.source)
        self.assertEqual(len(list(staged.iterdir())), 2)
        for item in staged.iterdir():
            os.utime(item, (0, 0))
        boardfiles.attach(self.cfg, self.source, str(probe) + ".other", b"x")
        names = sorted(p.name for p in staged.iterdir())
        self.assertEqual(len(names), 2, f"the stale pair was kept: {names}")


class CapTest(FileCase):
    """A board's own file is served under the BOARD's ceiling; everything else is not."""

    def test_a_board_file_is_capped_at_sixteen_megabytes_and_a_card_file_at_eight(self):
        probe = self.card_file("probe.py")
        self.push_with(probe)
        copy = Path(boards.read_record(self.cfg, "b-001")["files"][str(probe)]["file"])
        self.assertEqual(artifacts.cap(self.cfg, copy), artifacts.BOARD_MAX_BYTES)
        self.assertEqual(artifacts.cap(self.cfg, probe), artifacts.MAX_BYTES)

    def test_a_segments_own_inbox_is_not_a_boards(self):
        loose = self.cfg.segments_dir / "alpha" / "inbox"
        loose.mkdir(parents=True)
        (loose / "bill.pdf").write_bytes(PDF)
        self.assertEqual(artifacts.cap(self.cfg, loose / "bill.pdf"), artifacts.MAX_BYTES)


class HttpFileTest(deck_tests.ServerCase):
    """The door's half: a Download that serves the copy, and the drop box that takes his."""

    def setUp(self):
        super().setUp()
        self.probe = self.cfg.card_dir(self.live) / "probe.py"
        self.probe.write_text("print('probe')\n")
        source = {"kind": "card", "card": self.live}
        boardfiles.attach(self.cfg, source, str(self.probe), self.probe.read_bytes())
        boards.push(self.cfg, f'path board "{self.probe}" '
                              f'size "16 B" from house', card=self.live)

    def post(self, path, data, content_type, origin=True):
        import urllib.error
        import urllib.request
        request = urllib.request.Request(self.base + path, data=data, method="POST")
        request.add_header("Content-Type", content_type)
        request.add_header("Host", request.host)
        if not origin:
            request.add_header("Origin", "http://evil.test")
        else:
            for name, value in self.page_headers().items():
                request.add_header(name, value)
        try:
            with urllib.request.urlopen(request, timeout=10) as response:
                return response.status, json.loads(response.read())
        except urllib.error.HTTPError as error:
            with error:
                return error.code, json.loads(error.read())

    def test_the_board_answer_carries_a_token_url_that_serves_the_copy(self):
        doc = self.get_json("/api/board/b-001")
        entry = doc["files"][str(self.probe)]
        self.assertEqual(entry["from"], "house")
        self.assertTrue(entry["url"].startswith("/api/artifact/"), entry)
        status, _, body = self.fetch(entry["url"])
        self.assertEqual(status, 200, body)
        self.assertEqual(body, b"print('probe')\n")

    def headers_of(self, path):
        """Every response header, which is what the three rules below are about."""
        import urllib.request
        with urllib.request.urlopen(self.base + path, timeout=10) as response:
            return response.status, dict(response.headers), response.read()

    def pushed(self, name: str, text: str):
        """One more board file on b-001, and its entry as the deck is handed it."""
        path = self.cfg.card_dir(self.live) / name
        path.write_text(text)
        source = {"kind": "card", "card": self.live}
        boardfiles.attach(self.cfg, source, str(path), path.read_bytes())
        boards.push(self.cfg, f'path board "{path}" size "1 KB" from house',
                    card=self.live)
        return self.get_json("/api/board/b-001")["files"][str(path)]

    def test_a_board_file_is_handed_over_as_an_attachment_and_never_rendered(self):
        """THE ONE THAT MATTERS. A house writes what it likes into its own worktree, so
        `path "note.html"` would otherwise be a script served under a token in the deck's
        OWN origin, the origin the approve verbs live in. Every board file is a download:
        the type forced, sniffing off, an attachment disposition."""
        entry = self.pushed("note.html", "<script>fetch('/api/action',{method:'POST'})</script>")
        status, headers, body = self.headers_of(entry["url"])
        self.assertEqual(status, 200)
        self.assertEqual(headers["Content-Type"], "application/octet-stream")
        self.assertEqual(headers["X-Content-Type-Options"], "nosniff")
        self.assertIn("attachment", headers["Content-Disposition"])
        self.assertIn('filename="note.html"', headers["Content-Disposition"])
        self.assertIn(b"<script>", body, "the bytes are still his to download")

    def test_an_svg_is_an_attachment_too_because_an_svg_carries_script(self):
        entry = self.pushed("shape.svg", '<svg xmlns="http://www.w3.org/2000/svg"><script/></svg>')
        _, headers, _ = self.headers_of(entry["url"])
        self.assertEqual(headers["Content-Type"], "application/octet-stream")
        self.assertIn("attachment", headers["Content-Disposition"])

    def test_a_markdown_board_file_is_not_rendered_into_the_decks_origin_either(self):
        """The artifact route renders markdown as a page. A board file skips that: one rule
        for every board file, because a renderer is a second thing to have to be sure of."""
        entry = self.pushed("notes.md", "# a heading\n")
        _, headers, body = self.headers_of(entry["url"])
        self.assertEqual(headers["Content-Type"], "application/octet-stream")
        self.assertEqual(body, b"# a heading\n")
        self.assertNotIn(b"<h1>", body)

    def test_a_file_he_dropped_is_an_attachment_too(self):
        status, body = self.post("/api/board/b-001/inbox?name=graph.png", PNG, "image/png")
        self.assertEqual(status, 200, body)
        landed = self.cfg.card_dir(self.live) / artifacts.BOARD_INBOX / body["stored"]
        entry = self.get_json("/api/board/b-001")["files"][str(landed)]
        _, headers, _ = self.headers_of(entry["url"])
        self.assertEqual(headers["Content-Type"], "application/octet-stream")
        self.assertIn("attachment", headers["Content-Disposition"])
        # the stamp and the fingerprint are right on disk and wrong in a Save dialog
        self.assertIn('filename="graph.png"', headers["Content-Disposition"])

    def test_a_plan_the_deck_links_is_still_the_page_it_always_was(self):
        """The rule is the BOARD's directories and not the artifact route's whole surface:
        a card's plan is still a page the deck opens."""
        detail = self.get_json("/api/card/" + self.review)
        self.assertTrue(detail["card"]["plan_ref"])
        link = "/api/artifact/" + artifacts.token(self.cfg, detail["card"]["plan_ref"])
        _, headers, body = self.headers_of(link)
        self.assertEqual(headers["Content-Type"], "text/html; charset=utf-8")
        self.assertNotIn("Content-Disposition", headers)
        self.assertIn(b"<h1>Plan</h1>", body)

    def test_a_body_bigger_than_the_doors_ceiling_is_refused_before_it_is_read(self):
        """`read_body` read `Content-Length` whole, with nothing above it: one POST with a
        large header was as much memory as it cared to name. The attach makes a 22MB body
        legitimate, so the ceiling above it is now a number rather than an absence. The
        body is never sent here: the refusal comes off the HEADER."""
        import http.client
        host, port = self.server.server_address[0], self.server.server_address[1]
        connection = http.client.HTTPConnection(host, port, timeout=10)
        connection.putrequest("POST", "/api/action")
        connection.putheader("Content-Type", "application/json")
        connection.putheader("Content-Length", str(serve.MAX_BODY + 1))
        connection.endheaders()
        response = connection.getresponse()
        body = json.loads(response.read())
        connection.close()
        self.assertEqual(response.status, 413)
        self.assertIn("larger than", body["error"])

    def test_a_body_inside_the_ceiling_is_read_as_it_always_was(self):
        status, _, raw = self.fetch("/api/action", data=json.dumps(
            {"verb": "board.list"}).encode(), page=True)
        self.assertEqual(status, 200, raw)

    def test_a_token_is_only_ever_minted_for_the_copy_and_not_for_the_ops_log(self):
        """The boards tree is a root now, so the log and the record are inside it. Nothing
        mints a token for them, and the route serves only what was minted."""
        doc = self.get_json("/api/board/b-001")
        self.assertEqual(list(doc["files"]), [str(self.probe)])
        self.assertEqual(self.fetch("/api/artifact/not-a-token")[0], 404)

    def test_a_file_he_drops_lands_in_the_cards_inbox_and_appears_as_a_frame(self):
        status, body = self.post("/api/board/b-001/inbox?name=graph.png", PNG, "image/png")
        self.assertEqual(status, 200, body)
        self.assertFalse(body["duplicate"])
        landed = self.cfg.card_dir(self.live) / artifacts.BOARD_INBOX / body["stored"]
        self.assertTrue(landed.is_file())
        self.assertEqual(landed.read_bytes(), PNG)
        doc = self.get_json("/api/board/b-001")
        self.assertEqual(doc["attachments"], 2)
        self.assertIn(f'path board "{landed}" size "168 B" from you', doc["lines"])
        entry = doc["files"][str(landed)]
        self.assertEqual(entry["from"], "you")
        self.assertEqual(self.fetch(entry["url"])[2], PNG)

    def test_the_row_is_named_what_he_called_it_not_what_the_store_called_it(self):
        status, body = self.post("/api/board/b-001/inbox?name=graph.png", PNG, "image/png")
        self.assertEqual(status, 200, body)
        files = self.get_json("/api/board/b-001")["files"]
        landed = self.cfg.card_dir(self.live) / artifacts.BOARD_INBOX / body["stored"]
        self.assertEqual(files[str(landed)]["name"], "graph.png")

    def test_the_card_is_told_a_file_arrived_so_its_house_reads_it_next_turn(self):
        self.post("/api/board/b-001/inbox?name=graph.png", PNG, "image/png")
        events = self.board.events(self.live, last=5)
        said = [event["text"] for event in events if event["kind"] == "note"]
        self.assertTrue(any("the user put a file on the board" in text for text in said), said)
        self.assertTrue(any(artifacts.BOARD_INBOX in text for text in said), said)

    def test_the_same_file_dropped_twice_is_stored_once(self):
        first = self.post("/api/board/b-001/inbox?name=graph.png", PNG, "image/png")[1]
        again = self.post("/api/board/b-001/inbox?name=graph.png", PNG, "image/png")[1]
        self.assertTrue(again["duplicate"])
        self.assertEqual(again["stored"], first["stored"])
        box = self.cfg.card_dir(self.live) / artifacts.BOARD_INBOX
        self.assertEqual(len([p for p in box.iterdir() if p.is_file()]), 1)

    def test_a_drop_from_another_page_is_refused(self):
        status, body = self.post("/api/board/b-001/inbox", PNG, "image/png", origin=False)
        self.assertEqual(status, 403)
        self.assertIn("did not come from the deck", body["error"])

    def test_a_type_outside_the_table_and_bytes_that_belie_it_are_both_refused(self):
        status, body = self.post("/api/board/b-001/inbox", b"hello", "text/plain")
        self.assertEqual(status, 415, body)
        status, body = self.post("/api/board/b-001/inbox", b"hello", "image/png")
        self.assertEqual((status, "the bytes are not image/png"), (415, body["error"]))

    def test_a_drop_on_a_board_that_is_not_there_is_a_404(self):
        self.assertEqual(self.post("/api/board/b-404/inbox", PNG, "image/png")[0], 404)

    def test_a_drop_on_a_board_that_is_not_live_is_refused_rather_than_filed_elsewhere(self):
        """A push lands on its source's LIVE board, so a drop on an older one would file the
        it somewhere he is not looking and report success."""
        boards.close(self.cfg, "b-001")
        status, body = self.post("/api/board/b-001/inbox?name=graph.png", PNG, "image/png")
        self.assertEqual(status, 409, body)
        self.assertIn("not the live board", body["error"])
        self.assertFalse((self.cfg.card_dir(self.live) / artifacts.BOARD_INBOX).exists())


class CliFileTest(unittest.TestCase):
    """`keel board push` end to end, as a house on this machine runs it: the file it names
    travels with the push, and a file it may not read stops the push."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name)
        self.cfg = make_config(self.dir)
        self.board = Board(self.cfg.db_path)
        self.card = self.board.create("personal", "a card with a file", actor="human")
        self.addCleanup(self.board.close)
        self.addCleanup(self.tmp.cleanup)
        self.toml = self.dir / "keel.toml"
        self.toml.write_text("[keel]\n"
                             f'state_dir = "{self.cfg.state_dir}"\n'
                             f'segments_dir = "{self.cfg.segments_dir}"\n'
                             f'adapters_dir = "{self.cfg.adapters_dir}"\n'
                             "serve_port = 8791\n"
                             "[spaces.personal]\n"
                             f'config_dir = "{self.dir / "cfg-personal"}"\n')
        self.worktree = self.dir / "worktree"
        self.worktree.mkdir()

    def run_keel(self, argv, stdin="", cwd=None):
        env = dict(os.environ, KEEL_HOME=str(ROOT), KEEL_CONFIG=str(self.toml))
        env.pop("KEEL_URL", None)
        env.pop("KEEL_CARD", None)
        return subprocess.run([str(ROOT / "bin" / "keel"), "board", *argv], input=stdin,
                              capture_output=True, text=True, env=env, timeout=60,
                              cwd=str(cwd or self.worktree))

    def test_a_file_in_the_houses_own_worktree_travels_with_the_push(self):
        probe = self.worktree / "probe.py"
        probe.write_text("print('probe')\n")
        result = self.run_keel(["push", "--card", self.card],
                               stdin=f'path board "{probe}" size "16 B" from house')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("1 file", result.stdout)
        entry = boards.read_record(self.cfg, "b-001")["files"][str(probe)]
        self.assertEqual(Path(entry["file"]).read_bytes(), b"print('probe')\n")

    def test_a_file_outside_the_worktree_stops_the_push_with_one_line(self):
        outside = self.dir / "elsewhere.txt"
        outside.write_text("not yours")
        result = self.run_keel(["push", "--card", self.card],
                               stdin=f'path board "{outside}" size "9 B" from house')
        self.assertEqual(result.returncode, 1)
        self.assertEqual(len(result.stderr.strip().splitlines()), 1, result.stderr)
        self.assertIn("nothing was drawn", result.stderr)
        self.assertEqual(boards.records(self.cfg), [], "no board was made")


if __name__ == "__main__":
    unittest.main()
