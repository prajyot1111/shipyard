"""`VerbsContract` and `ReviewsContract`: a pack's real executables, run by Keel's own
`keel/adapters.py` on a real board, over a card's whole life (`VerbsContract`, every code
host) and a review card's whole life (`ReviewsContract`, a pack that claims `reviews`), two
of the conformance mixins (`conformance.py`). Both stand on `LifeHarness`, the scratch
install and its hooks.

Each test builds a scratch install: a bare origin with one commit on `main`, a clone whose
remote is the address the host stand-in answers for (git is told to fetch and push it to the
bare origin), a `keel.toml` with a space on the pack, a board, and a PATH that holds only
`sh`, `python3`, git and whatever the stand-in puts there. The verbs are other processes:
they load that config, read the card with `kb show`, and talk to the stand-in as to their
host. Then it says what the host was asked to write (only the contract's writes, each
once), and what git pushed (the card's own branch, and nothing at all for a review card).

Hooks, as `HostContract`'s: `host_world`, `host_serve`, `host_seen`; and `verbs_pack()` (the
pack's folder), `host_remote(name)` (the address a clone of `name` has, ending
`<repo>.git`), `host_bin(folder)` (put the stand-in's executables there), `host_env()` and
`host_git_config()` (more environment, more git config, for the verbs).
"""

import json
import os
import shutil
import subprocess
import sys
import tempfile
import tomllib
from pathlib import Path
from unittest import mock

from keel.packkit.world import World

REPO = "octo/api"
BRANCH_FILE = "change.txt"


def git(repo, *args: str, env=None) -> str:
    done = subprocess.run(["git", "-C", str(repo), "-c", "user.name=t", "-c", "user.email=t@x", *args],
                          capture_output=True, text=True, env=env)
    if done.returncode != 0:
        raise AssertionError(f"git {' '.join(args)}: {done.stderr}")
    return done.stdout.strip()


class LifeHarness:
    """The scratch install a life runs in, and the hooks a pack gives it."""

    def verbs_pack(self) -> Path:
        raise NotImplementedError("the pack's VerbsContract names its folder (verbs_pack)")

    def host_remote(self, name: str) -> str:
        raise NotImplementedError("the pack's VerbsContract says the address a clone has (host_remote)")

    def host_world(self) -> World:
        return World()

    def host_serve(self, world: World) -> None:
        """Make `world` what the host says."""

    def host_seen(self, world: World) -> World:
        return world

    def host_bin(self, folder: Path) -> None:
        """Put the stand-in's executables in `folder`, the whole of the verbs' PATH."""

    def host_env(self) -> dict:
        return {}

    def host_git_config(self) -> list[tuple[str, str]]:
        return []

    # ----- the scratch install -----

    def install(self):
        """The scratch install, its config and its world; everything is undone after the test."""
        from keel import config  # noqa: PLC0415 - Keel's own loader, only when a life runs
        made = tempfile.TemporaryDirectory(prefix="keel-kit-verbs-")
        self.addCleanup(made.cleanup)
        self.dir = Path(made.name).resolve()
        folder = self.dir / "bin"
        folder.mkdir()
        for name, found in (("sh", shutil.which("sh")), ("python3", sys.executable), ("git", shutil.which("git"))):
            os.symlink(found, folder / name)
        self.host_bin(folder)
        remote = self.host_remote(REPO)
        tail = REPO.split("/")[-1] + ".git"
        if not remote.endswith(tail):
            raise AssertionError(f"host_remote must end with {tail}: {remote}")
        self.bare = self.dir / "origin" / tail
        pairs = [(f"url.{self.bare.parent}/.insteadOf", remote[:-len(tail)]), *self.host_git_config()]
        env = {"PATH": str(folder), "GIT_CONFIG_COUNT": str(len(pairs)), **self.host_env()}
        for index, (key, value) in enumerate(pairs):
            env[f"GIT_CONFIG_KEY_{index}"], env[f"GIT_CONFIG_VALUE_{index}"] = key, value
        self.seed_origin()
        clone = self.dir / "repos" / "api"
        subprocess.run(["git", "clone", "-q", remote, str(clone)], check=True, env={**os.environ, **env},
                       capture_output=True)
        toml = self.dir / "keel.toml"
        pack = self.verbs_pack().resolve()
        toml.write_text(
            "[keel]\n"
            f'state_dir = "{self.dir / "state"}"\n'
            f'adapters_dir = "{pack.parent}"\n'
            "[spaces.personal]\n"
            f'config_dir = "{self.dir / "claude"}"\n'
            'contract = "etc/space-personal.md"\n'
            "[spaces.code]\n"
            f'adapter = "{pack.name}"\n'
            f'config_dir = "{self.dir / "claude"}"\n'
            "review_scan = true\n"
            "[spaces.code.repos]\n"
            f'api = "{clone}"\n')
        patcher = mock.patch.dict(os.environ, {**env, "KEEL_CONFIG": str(toml)})
        patcher.start()
        self.addCleanup(patcher.stop)
        self.cfg = config.load(toml)
        self.space = self.cfg.spaces["code"]
        self.world = self.host_world()
        self.world.repo(REPO)
        return self.cfg

    def seed_origin(self) -> None:
        seed = self.dir / "seed"
        seed.mkdir()
        git(seed, "init", "-q", "-b", "main")
        (seed / "loader.py").write_text("".join(f"line {n}\n" for n in range(1, 21)))
        git(seed, "add", "loader.py")
        git(seed, "commit", "-q", "-m", "the loader")
        self.bare.parent.mkdir(parents=True)
        subprocess.run(["git", "clone", "-q", "--bare", str(seed), str(self.bare)], check=True)

    def verb(self, name: str, card_id: str, *args: str, stdin: str = "", nonce: str | None = None) -> str:
        """One verb, the world served before it and read back after; `nonce` is a tap's, as
        Keel hands it to `publish` (c-738 r1.F3)."""
        from keel import adapters  # noqa: PLC0415
        self.host_serve(self.world)
        try:
            return adapters.run(self.space, name, card_id, *args, stdin=stdin, nonce=nonce)
        finally:
            self.world = self.host_seen(self.world)

    def tapped(self, card_id: str, how, ship: bool = False):
        """The user's tap, as `kb approve <id> outcome` and `kb ship <id>` make it: the card marked,
        `how(board, nonce)` run (the board's approve or ship, whose publish runs the verb with
        the nonce), the marker cleared after."""
        from keel.board import Board  # noqa: PLC0415
        with Board(self.cfg.db_path) as board:
            nonce = board.mark_publishing(card_id, "human", ship=ship)
            try:
                return how(board, nonce)
            finally:
                board.clear_publishing(card_id, nonce)

    def published(self, card_id: str, *args: str, stdin: str = "", approve: bool = False) -> dict:
        """The pack's `publish` inside the user's tap, through the board as Keel runs it: the
        user's Approve outcome (`approve`), else the user's Ship. What the verb answered."""
        said = []

        def tap(board, nonce):
            def publish(card):
                said.append(json.loads(self.verb("publish", card_id, *args, stdin=stdin, nonce=nonce)))
                return said[-1]
            if approve:
                board.approve(card_id, "outcome", "human", publish=publish)
            else:
                board.ship(card_id, "human", publish)
        self.tapped(card_id, tap, ship=not approve)
        return said[-1]

    def watch_git_for_nonce(self) -> None:
        """r2.F2: git on the verbs' PATH becomes a wrapper that notes whether it was handed
        the tap's nonce (`nonce_seen`), then runs git; every git a verb starts is a child."""
        self.nonce_seen = self.dir / "nonce-seen"
        wrapper = self.dir / "bin" / "git"
        real = os.path.realpath(wrapper)
        wrapper.unlink()
        wrapper.write_text(f'#!/bin/sh\n[ -n "$KEEL_PUBLISH_NONCE" ] && echo "$*" >> "{self.nonce_seen}"\n'
                           f'exec "{real}" "$@"\n')
        wrapper.chmod(0o755)

    def plant_hooks(self, tree: Path) -> list[Path]:
        """r2.F2: a pre-push hook a house could plant, in the clone's hooks and through
        `core.hooksPath` in its worktree; each writes its file when it runs."""
        planted = []
        common = Path(git(tree, "rev-parse", "--path-format=absolute", "--git-common-dir"))
        for hooks, name in ((common / "hooks", "ran-from-hooks"), (self.dir / "house-hooks", "ran-from-hookspath")):
            hooks.mkdir(parents=True, exist_ok=True)
            hook = hooks / "pre-push"
            hook.write_text(f'#!/bin/sh\necho "$KEEL_PUBLISH_NONCE" > "{self.dir / name}"\n')
            hook.chmod(0o755)
            planted.append(self.dir / name)
        git(tree, "config", "core.hooksPath", str(self.dir / "house-hooks"))   # `git config` the guard lets by
        return planted

    def card(self, card_id: str) -> dict:
        from keel.board import Board  # noqa: PLC0415
        with Board(self.cfg.db_path) as board:
            return board.get(card_id)

    def short(self) -> str:
        terms = tomllib.loads((self.verbs_pack() / "pack.toml").read_text()).get("terms") or {}
        return str(terms.get("change_short") or "change")

    def origin_refs(self) -> dict:
        listed = git(self.bare, "for-each-ref", "--format=%(refname) %(objectname)")
        return dict(line.split(" ", 1) for line in listed.splitlines() if line)


class VerbsContract(LifeHarness):
    """A card's whole life, which every code host pack lives."""

    def test_publish_run_by_a_house_is_refused_by_the_verb_at_every_stage(self):
        """r1.F2, r1.F3: `publish` runs only inside the user's tap (Approve outcome, Ship), whose
        nonce Keel hands the verb and whose digest the board keeps on the card. Run by a house,
        with no nonce, a made-up one, or one from a tap that is over, it is refused at
        building, review and shipping, and nothing is written to the host."""
        from keel import adapters  # noqa: PLC0415
        from keel.board import Board  # noqa: PLC0415
        cfg = self.install()
        with Board(cfg.db_path) as board:
            card_id = board.create("code", "Tidy the loader", repo="api")
            board.stage(card_id, "assigned", "human")
            board.stage(card_id, "building", "human")
        made_up = "0" * 32

        def refused(*nonces, why: str):
            for nonce in nonces:
                with self.assertRaises(adapters.AdapterError, msg=f"{why} {nonce}") as caught:
                    self.verb("publish", card_id, nonce=nonce)
                self.assertIn("your Ship", str(caught.exception), f"{why} {nonce}")
        refused(None, made_up, why="building")
        with Board(cfg.db_path) as board:
            board.stage(card_id, "review", "human", plan_ref="plan.md", output_ref="change 1")
        stale = self.tapped(card_id, lambda board, nonce: nonce)
        refused(None, made_up, stale, why="review")
        self.tapped(card_id, lambda board, nonce: refused(None, made_up, stale, why="review, the user's tap open"))
        with Board(cfg.db_path) as board:                               # r2.F3: a marker a killed kb left
            board.now = lambda: "2026-01-01T09:00:00+00:00"
            left = board.mark_publishing(card_id, "human")
        refused(left, why="review, a marker older than a tap")
        with Board(cfg.db_path) as board:
            board.clear_publishing(card_id, left)
        with Board(cfg.db_path) as board:
            board.ship_from_sync(card_id, "drain", "synced")
        stale = self.tapped(card_id, lambda board, nonce: nonce, ship=True)
        refused(None, made_up, stale, why="shipping")
        self.tapped(card_id, lambda board, nonce: refused(None, made_up, stale, why="shipping, the user's Ship open"),
                    ship=True)
        self.assertEqual(self.world.writes, [])

    def test_pr_ready_is_refused_by_the_verb_itself_at_every_stage(self):
        """r1.F2, r1.F3: nothing in the engine runs `pr --ready` (Approve outcome's `publish`
        marks a draft ready in its own process), so the verb refuses it, run directly with no
        guard in front of it, and asks the host nothing."""
        from keel import adapters  # noqa: PLC0415
        from keel.board import Board  # noqa: PLC0415
        cfg = self.install()
        with Board(cfg.db_path) as board:
            card_id = board.create("code", "Tidy the loader", repo="api")
            board.stage(card_id, "assigned", "human")
            board.stage(card_id, "building", "human")
        for stage in ("building", "review"):
            if stage == "review":
                with Board(cfg.db_path) as board:
                    board.stage(card_id, "review", "human", plan_ref="plan.md", output_ref="change 1")
            with self.assertRaises(adapters.AdapterError) as refused:
                self.verb("pr", card_id, "--ready")
            self.assertIn("Approve outcome", str(refused.exception), stage)
        self.assertEqual(self.world.writes, [])

    def test_a_card_s_whole_life_writes_only_the_contract_s_writes_and_pushes_only_its_branch(self):
        from keel import adapters  # noqa: PLC0415
        from keel.board import Board  # noqa: PLC0415
        cfg = self.install()
        self.watch_git_for_nonce()
        with Board(cfg.db_path) as board:
            card_id = board.create("code", "Tidy the loader", repo="api")
            board.stage(card_id, "assigned", "human")
            board.stage(card_id, "building", "human")
        self.host_serve(self.world)
        (tree,) = adapters.worktree(cfg, self.card(card_id))
        branch = self.card(card_id)["options"]["branch"]
        self.assertEqual(git(tree, "rev-parse", "--abbrev-ref", "HEAD"), branch)
        self.assertIn(f"{self.verbs_pack().resolve() / 'pr'} {card_id} --draft", adapters.brief(cfg, self.card(card_id)))
        (tree / BRANCH_FILE).write_text("tidy\n")
        git(tree, "add", BRANCH_FILE)
        git(tree, "commit", "-q", "-m", "tidy the loader")
        git(tree, "push", "-q", "-u", "origin", branch)                 # the house's own push
        folder = cfg.card_dir(card_id)
        folder.mkdir(parents=True, exist_ok=True)
        (folder / "context.md").write_text(f"## {self.short()} body\n\n```copy\nThe loader is tidy.\n```\n")
        self.verb("pr", card_id, "--draft")
        (number,) = [int(n) for n, one in self.world.data["repos"][REPO]["changes"].items() if one["branch"] == branch]
        change = self.world.change(REPO, number)
        self.assertEqual((change["draft"], change["base"], change["body"]), (True, "main", "The loader is tidy."))
        self.host_serve(self.world)
        self.assertIsNone(adapters.publishable(cfg, self.card(card_id)))
        with Board(cfg.db_path) as board:
            board.stage(card_id, "review", "human", plan_ref="plan.md", output_ref=f"change {number}")
        said = self.published(card_id, approve=True)                   # the user's Approve outcome
        self.assertEqual((said["pr"], said["shipping"], said["draft"]), (number, True, False))
        self.assertEqual(self.card(card_id)["stage"], "shipping")
        line = self.world.say(REPO, number, "ana", "Why 40?", "loader.py", 7)
        sight = json.loads(self.verb("ship", card_id, "poll"))
        self.assertEqual((sight["state"], [one["id"] for one in sight["comments"]]), ("open", [f"l{line}"]))
        (tree / "fix.txt").write_text("fix\n")
        git(tree, "add", "fix.txt")
        git(tree, "commit", "-q", "-m", "a fix")
        head = git(tree, "rev-parse", "HEAD")
        planted = self.plant_hooks(tree)                                # r2.F2: the house's hooks
        ship = {"ship": True, "replies": [{"handle": f"cl{line}", "text": "It is the page size."},
                                          {"handle": "ci", "text": "Rerun is green."}]}
        shipped = self.published(card_id, "--answer", stdin=json.dumps(ship))     # the user's Ship
        self.assertEqual((shipped["pushed"], shipped["posted"]), ({"api": head}, [f"cl{line}", "ci"]))
        self.assertEqual([path.name for path in planted if path.exists()], [], "a hook the house planted ran")
        self.assertFalse(self.nonce_seen.exists(), "a child of publish was handed the tap's nonce")
        again = self.published(card_id, "--answer", stdin=json.dumps(ship))
        self.assertEqual(again["posted"], [])                           # a second Ship posts nothing twice
        links = json.loads(self.verb("act", "links", card_id))
        self.assertIn(str(number), links[card_id]["pr"])
        with Board(cfg.db_path) as board:
            board.stage(card_id, "done", "human")
        self.assertEqual(json.loads(self.verb("ship", card_id, "reap"))["removed"], [str(tree)])
        self.assertEqual([one["op"] for one in self.world.writes], ["open_pr", "set_ready", "reply", "comment"])
        self.assertEqual({ref: sha for ref, sha in self.origin_refs().items() if ref != "refs/heads/main"},
                         {f"refs/heads/{branch}": head})


class ReviewsContract(LifeHarness):
    """A review card's whole life, for a pack that claims `reviews`."""

    def test_a_review_card_s_whole_life_writes_one_review_and_pushes_nothing(self):
        from keel import adapters  # noqa: PLC0415
        from keel.board import Board  # noqa: PLC0415
        cfg = self.install()
        other = self.dir / "colleague"
        subprocess.run(["git", "clone", "-q", str(self.bare), str(other)], check=True, capture_output=True)
        (other / "loader.py").write_text("faster\n")
        git(other, "commit", "-q", "-am", "a faster loader")
        head = git(other, "rev-parse", "HEAD")
        number = self.world.add_change(REPO, "ana/faster", author="ana", requested=["me"], head=head,
                                       changed={"loader.py": [1]}, body="It reads the file once.")
        git(other, "push", "-q", "origin", f"HEAD:refs/pull/{number}/head")
        before = self.origin_refs()
        rows = json.loads(self.verb("review", "scan"))["prs"]
        self.assertEqual([(row["key"], row["author"], row["head"]) for row in rows], [(f"api:{number}", "ana", head)])
        with Board(cfg.db_path) as board:
            card_id = board.create("code", "Review: Faster loader", repo="api")
            board.set_fields(card_id, {"options": {"kind": "review", "review_key": f"api:{number}", "pr": number,
                                                   "branch": "ana/faster", "base": "main"}}, "human")
            board.stage(card_id, "assigned", "human")
        self.host_serve(self.world)
        (tree,) = adapters.worktree(cfg, self.card(card_id))
        self.assertEqual(git(tree, "rev-parse", "HEAD"), head)
        self.assertIn("Never edit, commit or push", adapters.brief(cfg, self.card(card_id)))
        self.assertEqual(json.loads(self.verb("review", card_id, "poll"))["head"], head)
        kept = {"review": {"round": 1, "head": head, "verdict": "approve", "summary": "Good.",
                           "comments": [{"row": "f1", "path": "loader.py", "line": 1, "text": "Nice."}]}}
        with Board(cfg.db_path) as board:
            board.stage(card_id, "building", "human")
            board.stage(card_id, "review", "human", plan_ref="plan.md", output_ref=f"review {number}")

        def twice(board, nonce):                                        # the user's Approve outcome, run twice
            return [json.loads(self.verb("publish", card_id, "--answer", stdin=json.dumps(kept), nonce=nonce))
                    for _ in range(2)]
        posted, again = self.tapped(card_id, twice)
        self.assertEqual((posted["published"], posted["pr"], posted["verdict"]), ("review", number, "approve"))
        self.assertEqual(again["published"], "review")                  # it found the review that landed
        self.assertEqual([(one["op"], one["inline"]) for one in self.world.writes], [("post_review", 1)])
        self.assertEqual(self.origin_refs(), before)
