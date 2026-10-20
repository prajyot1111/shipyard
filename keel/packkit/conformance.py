"""The conformance suite: what every pack on the kit is held to, as four mixins.

A pack's `tests/test_conformance.py` subclasses each with `unittest.TestCase` and says how
its host is stood in for. `keel pack check <dir>` runs the pack's suite and requires the
subclasses its capabilities call for.

- `HostContract`: the pack's REAL layer, against a `World` its stand-in hook serves as its
  host would (the GitHub pack's as a `gh` on PATH, the Gitea pack's as an API on
  127.0.0.1). Shapes, states, drafts, forks, what was said and in which shape, reply
  placement, a review line outside the change, each error, a write budget that never
  merges, closes, deletes or pushes, and no token ever returned or raised.
- `GuardContract`: the refusals every guard on the kit makes, the pack's own verbs by
  every path form, run in process and through `bin/keel-house-guard`.
- `VerbsContract` (`lifecontract.py`): the pack's real executables through
  `keel/adapters.py`, over a card's whole life.
- `ReviewsContract` (`lifecontract.py`): the same, over a review card's whole life, for a
  pack that claims `reviews`.

A subclass gives the hooks each mixin names (`host_*`, `guard_*`); the defaults suit a
world held in this process.
"""

import json
import os
import subprocess
import sys
import tomllib
from pathlib import Path

from keel.packkit import guard
from keel.packkit.errors import HostError, NotFound, OutsideChange, SignedOut
from keel.packkit.layer import GENERAL, LINES, PARTS, REVIEWS
from keel.packkit.lifecontract import ReviewsContract, VerbsContract  # noqa: F401 - named here with the others
from keel.packkit.world import SECRET, WRITES, World

REPO = "octo/api"
PR_KEYS = {"id", "url", "draft", "title", "state", "head", "branch", "base", "own"}
COMMENT_KEYS = {"kind", "id", "author", "bot", "body", "at", "updated", "path", "line", "parent", "reply_to",
                "resolved"}
REVIEW_KEYS = {"id", "author", "bot", "state", "dismissed", "body", "at"}
ROOT = Path(__file__).resolve().parent.parent.parent


class HostContract:
    """The layer's contract, against the world. Hooks: `host_layer()` (the layer module),
    `host_repo(name)` (the `Repo` it addresses for a world repository), and, for a world
    served from elsewhere, `host_serve(world)` (make it what the host says) and
    `host_seen(world)` (the world as the host now has it). `host_secret(marker)` puts the
    marker where the host's sign-in would be."""

    def host_layer(self):
        raise NotImplementedError("the pack's HostContract says which layer it holds (host_layer)")

    def host_repo(self, name: str):
        raise NotImplementedError("the pack's HostContract says how a repository is addressed (host_repo)")

    def host_world(self) -> World:
        return World()

    def host_serve(self, world: World) -> None:
        """Make `world` what the host says; nothing to do for one held in this process."""

    def host_seen(self, world: World) -> World:
        return world

    def host_secret(self, marker: str) -> None:
        """Put `marker` where the host's sign-in is kept, when the stand-in has such a place."""

    # ----- the harness -----

    def fresh(self, **repo) -> World:
        world = self.host_world()
        world.repo(REPO, **repo)
        return world

    def ask(self, world: World, how):
        """`how(layer, repo)` against the world as the host serves it; the world after."""
        self.host_serve(world)
        try:
            return how(self.host_layer(), self.host_repo(REPO))
        finally:
            self.seen = self.host_seen(world)

    # ----- one change -----

    def test_a_change_comes_back_in_the_kit_s_shape(self):
        world = self.fresh()
        number = world.add_change(REPO, "feature", draft=True, head="c0ffee")
        found = self.ask(world, lambda layer, repo: layer.get(repo, number))
        self.assertLessEqual(PR_KEYS, set(found))
        self.assertEqual({key: found[key] for key in ("id", "draft", "state", "head", "branch", "base", "own")},
                         {"id": number, "draft": True, "state": "open", "head": "c0ffee", "branch": "feature",
                          "base": "main", "own": True})
        self.assertEqual(found["url"], self.host_layer().HOST.pr_url(self.host_repo(REPO), number))

    def test_states_are_said_in_the_kit_s_words_and_one_it_does_not_name_is_unknown(self):
        world = self.fresh()
        named = {state: world.add_change(REPO, f"b-{state}", state=state)
                 for state in ("open", "merged", "declined", "unknown")}
        found = self.ask(world, lambda layer, repo: {state: layer.get(repo, n)["state"] for state, n in named.items()})
        self.assertEqual(found, {"open": "open", "merged": "merged", "declined": "declined", "unknown": "unknown"})

    def test_find_open_takes_the_repository_s_own_and_never_a_fork_s(self):
        world = self.fresh()
        world.add_change(REPO, "feature", own=False, author="stranger")
        own = world.add_change(REPO, "feature")
        found = self.ask(world, lambda layer, repo: (layer.find_open(repo, "feature"), layer.find_open(repo, "nothing")))
        self.assertEqual((found[0]["id"], found[0]["own"], found[1]), (own, True, None))

    def test_a_draft_is_opened_and_marked_ready_and_its_body_replaced(self):
        world = self.fresh()

        def life(layer, repo):
            made = layer.open_pr(repo, "Tidy the loader", "feature", "main", "The loader is tidy.", draft=True)
            before = layer.get(repo, made["id"])["draft"]
            layer.set_ready(repo, made["id"])
            layer.set_body(repo, made["id"], "Tidier.")
            return made, before, layer.get(repo, made["id"])
        made, before, after = self.ask(world, life)
        self.assertEqual((made["draft"], made["branch"], made["base"], made["own"]), (True, "feature", "main", True))
        self.assertEqual((before, after["draft"]), (True, False))
        self.assertEqual(self.seen.change(REPO, made["id"])["body"], "Tidier.")
        self.assertEqual([one["op"] for one in self.seen.writes], ["open_pr", "set_ready", "set_body"])

    # ----- what was said -----

    def talk(self, world: World) -> dict:
        number = world.add_change(REPO, "feature", author="me")
        ids = {"n": number, "g": world.say(REPO, number, "ana", "Looks close.", at="2026-10-01T10:01:00Z"),
               "bot": world.say(REPO, number, "ci[bot]", "Coverage 91%.", bot=True),
               "l": world.say(REPO, number, "ana", "Why 40?", "loader.py", 7, at="2026-10-01T10:02:00Z"),
               "r": world.add_review(REPO, number, "ben", "approved", "Fine by me."),
               "d": world.add_review(REPO, number, "cy", "changes_requested", "No.", dismissed=True)}
        ids["l2"] = world.say(REPO, number, "me", "Page size.", "loader.py", 7, under=ids["l"],
                              at="2026-10-01T10:03:00Z")
        return ids

    def test_what_was_said_comes_back_in_the_kit_s_shapes(self):
        world = self.fresh()
        ids = self.talk(world)
        said = self.ask(world, lambda layer, repo: layer.said(repo, ids["n"], parts=PARTS))
        general = {one["id"]: one for one in said[GENERAL]}
        lines = {one["id"]: one for one in said[LINES]}
        reviews = {one["author"]: one for one in said[REVIEWS]}
        for one in [*general.values(), *lines.values()]:
            self.assertLessEqual(COMMENT_KEYS, set(one))
        self.assertEqual((general[ids["g"]]["kind"], general[ids["g"]]["author"], general[ids["g"]]["body"],
                          general[ids["g"]]["bot"]), ("g", "ana", "Looks close.", False))
        self.assertTrue(general[ids["bot"]]["bot"])
        self.assertEqual((lines[ids["l"]]["kind"], lines[ids["l"]]["path"], lines[ids["l"]]["line"],
                          lines[ids["l"]]["parent"]), ("l", "loader.py", 7, None))
        self.assertEqual(lines[ids["l2"]]["parent"], ids["l"])
        for one in reviews.values():
            self.assertLessEqual(REVIEW_KEYS, set(one))
        self.assertEqual((reviews["ben"]["state"], reviews["ben"]["dismissed"], reviews["ben"]["body"]),
                         ("approved", False, "Fine by me."))
        self.assertTrue(reviews["cy"]["dismissed"])

    def test_a_resolved_line_comment_is_marked_and_only_the_parts_asked_for_are_read(self):
        world = self.fresh()
        number = world.add_change(REPO, "feature")
        done = world.say(REPO, number, "ana", "Old.", "loader.py", 3, resolved=True)
        live = world.say(REPO, number, "ana", "New.", "loader.py", 9)
        world.say(REPO, number, "ana", "Overall.")

        def both(layer, repo):
            return layer.said(repo, number, parts=PARTS), layer.said(repo, number, parts=(REVIEWS,))
        whole, reviews_only = self.ask(world, both)
        self.assertEqual({one["id"]: one["resolved"] for one in whole[LINES]}, {done: True, live: False})
        self.assertEqual((reviews_only[GENERAL], reviews_only[LINES]), ([], []))

    def test_a_reply_lands_in_the_conversation_of_the_line_comment_it_answers(self):
        world = self.fresh()
        ids = self.talk(world)

        def answer(layer, repo):
            lines = {one["id"]: one for one in layer.said(repo, ids["n"], parts=(LINES,))[LINES]}
            layer.reply(repo, ids["n"], lines[ids["l2"]]["reply_to"], "Named it.")
            layer.comment(repo, ids["n"], "Thanks.")
        self.ask(world, answer)
        change = self.seen.change(REPO, ids["n"])
        mine = [one for one in change["lines"] if one["body"] == "Named it."]
        self.assertEqual(len(mine), 1)
        self.assertEqual((mine[0]["path"], mine[0]["line"], self.seen.root(change, mine[0]["id"])["id"]),
                         ("loader.py", 7, ids["l"]))
        self.assertEqual([one["body"] for one in change["general"] if one["author"] == "me"], ["Thanks."])
        self.assertEqual([one["op"] for one in self.seen.writes], ["reply", "comment"])

    def test_a_review_is_posted_whole(self):
        world = self.fresh()
        number = world.add_change(REPO, "feature", author="ana", requested=["me"])

        def post(layer, repo):
            done = layer.post_review(repo, number, "Summary.\n\n<!-- mark -->", "changes",
                                     [{"path": "loader.py", "line": 7, "text": "Reads twice."}], "abc123")
            return done, layer.said(repo, number, parts=(REVIEWS,))[REVIEWS]
        done, reviews = self.ask(world, post)
        self.assertTrue(done.get("id"))
        mine = [one for one in reviews if one["author"] == "me"]
        self.assertEqual(len(mine), 1)
        self.assertEqual(mine[0]["state"], "changes_requested")
        self.assertIn("<!-- mark -->", mine[0]["body"])
        self.assertEqual([(one["op"], one["inline"]) for one in self.seen.writes], [("post_review", 1)])

    def test_a_finding_outside_the_change_is_refused_whatever_the_host_does_on_its_own(self):
        """A host may refuse a line the change does not touch (GitHub) or post it there (Gitea):
        either way the layer raises `OutsideChange` and writes nothing, so the kit's fallback
        (`review.py`, the findings in the review's own words) runs."""
        world = self.fresh()
        number = world.add_change(REPO, "feature", author="ana", requested=["me"],
                                  changed={"loader.py": [6, 7, 8], "new.py": [1, 2, 3]})
        outside = ({"path": "loader.py", "line": 9}, {"path": "new.py", "line": 99}, {"path": "other.py", "line": 7})

        def post(layer, repo):
            for one in outside:
                with self.assertRaises(OutsideChange, msg=one):
                    layer.post_review(repo, number, "Summary.", "changes", [
                        {"path": "loader.py", "line": 7, "text": "Here."}, dict(one, text="Not here.")], "abc123")
        self.ask(world, post)
        self.assertEqual(self.seen.writes, [])
        self.assertEqual(self.seen.change(REPO, number)["lines"], [])

    def test_checks_come_back_in_the_kit_s_words(self):
        world = self.fresh()
        number = world.add_change(REPO, "feature", head="c0ffee")
        for state in ("passed", "running", "failed"):
            world.add_check(REPO, number, state, f"check-{state}")
        found = self.ask(world, lambda layer, repo: layer.checks(repo, layer.get(repo, number, sight=True)))
        self.assertEqual(sorted((one["name"], one["state"]) for one in found),
                         [("check-failed", "failed"), ("check-passed", "passed"), ("check-running", "running")])

    def test_review_requests_and_the_account_s_own_changes(self):
        world = self.fresh()
        asked = world.add_change(REPO, "ana/faster", author="ana", requested=["me"], body="It reads once.")
        own = world.add_change(REPO, "feature", author="me")
        world.add_change(REPO, "ben/other", author="ben")

        def lists(layer, repo):
            return layer.review_requests(repo), layer.mine(repo)
        requests, mine = self.ask(world, lists)
        self.assertEqual([one["id"] for one in requests], [asked])
        self.assertEqual((requests[0]["author"], requests[0]["branch"], requests[0]["own"]), ("ana", "ana/faster", True))
        self.assertIn("It reads once.", requests[0].get("body") or "")
        self.assertEqual([one["id"] for one in mine], [own])
        self.assertEqual(mine[0]["branch"], "feature")

    # ----- the repository and the account -----

    def test_the_default_branch_protection_and_access(self):
        world = self.fresh(default="trunk")
        world.repo(REPO)["protected"].append("release-x")

        def read(layer, repo):
            return (layer.default_branch(repo, timeout=10), layer.protected(repo, "release-x"),
                    layer.protected(repo, "never-heard-of"), layer.access(repo, timeout=10))
        self.assertEqual(self.ask(world, read), ("trunk", True, False, "push"))
        world.repo(REPO)["access"] = "read"
        self.assertEqual(self.ask(world, lambda layer, repo: layer.access(repo, timeout=10)), "read")
        world.repo(REPO)["access"] = "none"
        with self.assertRaises(NotFound):
            self.ask(world, lambda layer, repo: layer.access(repo, timeout=10))

    def test_the_account_and_a_sign_in_that_is_gone(self):
        world = self.fresh()
        self.assertEqual(self.ask(world, lambda layer, repo: (layer.signed_in(repo, timeout=10),
                                                              layer.account(repo, timeout=10))), (None, "me"))
        world.data["signed_in"] = False
        for how in (lambda layer, repo: layer.account(repo, timeout=10),
                    lambda layer, repo: layer.signed_in(repo, timeout=10),
                    lambda layer, repo: layer.find_open(repo, "feature")):
            with self.assertRaises(SignedOut):
                self.ask(world, how)

    def test_a_change_that_is_not_there_is_not_found_and_every_error_is_the_kit_s(self):
        world = self.fresh()
        with self.assertRaises(NotFound):
            self.ask(world, lambda layer, repo: layer.get(repo, 999))
        world.data["fail"]["all"] = "error"
        with self.assertRaises(HostError) as failed:
            self.ask(world, lambda layer, repo: layer.get(repo, 1))
        self.assertEqual(len(str(failed.exception).splitlines()), 1)

    def test_only_the_contract_s_writes_are_made_and_no_token_is_ever_returned_or_raised(self):
        self.host_secret(SECRET)
        world = self.fresh()
        ids = self.talk(world)
        said = []

        def everything(layer, repo):
            made = layer.open_pr(repo, "T", "feature-2", "main", "B", draft=True, cwd=None)
            for call in (lambda: layer.find_open(repo, "feature-2"), lambda: layer.get(repo, made["id"], sight=True),
                         lambda: layer.set_ready(repo, made["id"]), lambda: layer.set_body(repo, made["id"], "C"),
                         lambda: layer.said(repo, ids["n"]), lambda: layer.comment(repo, ids["n"], "x"),
                         lambda: layer.reply(repo, ids["n"], ids["l"], "y"),
                         lambda: layer.post_review(repo, ids["n"], "z", "comment", [], None),
                         lambda: layer.review_requests(repo), lambda: layer.mine(repo),
                         lambda: layer.default_branch(repo, timeout=10), lambda: layer.protected(repo, "b"),
                         lambda: layer.account(repo, timeout=10), lambda: layer.access(repo, timeout=10),
                         lambda: layer.get(repo, 999)):
                try:
                    said.append(repr(call()))
                except HostError as error:
                    said.append(str(error))
            return made
        self.ask(world, everything)
        self.assertLessEqual({one["op"] for one in self.seen.writes}, set(WRITES))
        for text in said:
            self.assertNotIn(SECRET, text)
        self.assertNotIn(SECRET, json.dumps(self.seen.data))


class GuardContract:
    """The guard every pack on the kit has. Hooks: `guard_pack()` (the pack's folder) and
    `guard_policy()` (its `GuardPolicy`)."""

    def guard_pack(self) -> Path:
        raise NotImplementedError("the pack's GuardContract names its folder (guard_pack)")

    def guard_policy(self):
        raise NotImplementedError("the pack's GuardContract names its policy (guard_policy)")

    def said(self, command: str, card=None) -> str | None:
        fence = guard.Fence(self.guard_pack(), self.guard_policy())
        return guard.problem(command, str(self.guard_pack().parent), card or (lambda: {"options": {}}), fence)

    def own_forms(self, verb: str) -> list[str]:
        """The pack's own verb, by every path form a house might write."""
        pack = self.guard_pack()
        name = pack.name
        return [f"{pack}/{verb}", f"'{pack}/{verb}'", f'"{pack}/{verb}"', f"python3 {pack}/{verb}",
                f"bash {pack}/{verb}", f"cd {pack} && ./{verb}", f"cd {pack.parent} && {name}/{verb}",
                f'"$KEEL_HOME/packs/{name}/{verb}"', f'"${{KEEL_HOME}}"/packs/{name}/{verb}',
                f"$KEEL_HOME/adapters/{name}/{verb}", *self.run_by_forms(verb)]

    def run_by_forms(self, verb: str) -> list[str]:
        """The pack's own verb handed to a shell or to Python as a script, by every path
        form (c-738): judged exactly as running the verb itself."""
        pack = self.guard_pack()
        name = pack.name
        return [f"bash {pack}/{verb}", f"sh {pack}/{verb}", f"zsh {pack}/{verb}", f"env bash {pack}/{verb}",
                f"bash -x {pack}/{verb}", f"bash -o posix {pack}/{verb}", f"bash -- {pack}/{verb}",
                f"sudo -u me sh {pack}/{verb}", f"cd {pack.parent.parent} && bash packs/{name}/{verb}",
                f"cd {pack} && bash ./{verb}", f"cd {pack} && sh {verb}", f"cd {pack}/tests && bash ../{verb}",
                f"cd {pack} && python3 {verb}", f"python3 -W ignore {pack}/{verb}",
                f"cd {pack}/tests && python3 ../{verb}", f'bash "$KEEL_HOME/packs/{name}/{verb}"']

    def filled_fed_forms(self) -> list[str]:
        """A command word the shell fills in, whose words come from where the guard cannot
        read them (c-738): it may be the pack's tool, so the line is refused."""
        tool = self.guard_policy().filled or "gh"
        return [f"printf 'pr merge 5' | xargs \"${tool.upper()}\"", f"printf 'pr merge 5' | xargs $(which {tool})",
                f"printf 'pr merge 5' | xargs `which {tool}`", "echo 'pr merge 5' | xargs -n3 \"$TOOL\"",
                "xargs \"$TOOL\" < words.txt", "echo 5 | xargs -I{} \"$TOOL\"", "xargs \"$TOOL\" --repo o/r < w",
                "printf 'pr merge 5' | env xargs \"$TOOL\"", "echo 'push --force origin b' | xargs \"$GIT\"",
                "printf 'pr merge 5' | xargs g[a-z]", "printf 'pr merge 5' | xargs \"$TOOL\" \"$WHAT\""]

    # r1.F1: with no feeder, a filled command word and a filled word after it is some other
    # command, as before c-738; the rule above is for words that come from xargs only
    FILLED_OPEN = ('"$PY" "$SCRIPT"', '$EDITOR "$file"', '"$CMD" "$@"', '"$TOOL" "$GROUP" view 5',
                   '"$PYTHON" -m unittest', '"$TOOL"')

    def test_the_pack_s_own_publish_is_refused_by_every_path_form(self):
        for form in self.own_forms("publish"):
            self.assertIn("Approve outcome", self.said(f"{form} c-1") or "", form)

    def test_pr_ready_is_refused_and_draft_and_body_stay_a_building_house_s(self):
        for form in self.own_forms("pr"):
            self.assertIn("Approve outcome", self.said(f"{form} c-1 --ready") or "", form)
            for allowed in ("--draft", "--body"):
                self.assertIsNone(self.said(f"{form} c-1 {allowed}"), f"{form} {allowed}")

    def test_a_forced_deleted_or_wide_push_is_refused_and_a_plain_one_is_open(self):
        for command in ("git push --force origin b", "git push -f origin b", "git push --force-with-lease origin b",
                        "git push origin --delete b", "git push --mirror", "git push --all origin",
                        "git push origin +b", "git push origin HEAD:main", "git push origin a b",
                        'git push origin "$BRANCH"', "git -c alias.p=push p --force origin b"):
            self.assertIsNotNone(self.said(command), command)
        for command in ("git push -u origin HEAD", "git push origin feature", "git status",
                        'git commit -m "never git push --force"'):
            self.assertIsNone(self.said(command), command)

    def test_the_sign_in_is_refused(self):
        for command in ("git credential fill", "git -C . credential approve", "git credential-osxkeychain get"):
            self.assertIsNotNone(self.said(command), command)

    def test_a_research_or_review_card_loses_every_push_and_every_form_of_the_pack_s_pr(self):
        for kind, options in (("research", {"kind": "research"}), ("review", {"review_key": "api:12"})):
            for command in ("git push -u origin HEAD", f"{self.guard_pack()}/pr c-1 --draft"):
                self.assertIn(f"{kind} card", self.said(command, lambda options=options: {"options": options}) or "")

    def test_a_card_that_cannot_be_read_holds_a_push_and_nothing_else(self):
        def unread():
            raise guard.CardUnread("the board gave no answer")
        self.assertIn("could not be read", self.said("git push -u origin HEAD", unread) or "")
        self.assertIsNone(self.said("git status", unread))

    def test_a_line_it_cannot_read_is_refused_only_when_it_names_a_push_or_the_pack_s_verbs(self):
        for command in ("git push 'origin b", f"{self.guard_pack()}/publish c-1 'unclosed"):
            self.assertIn("could not be read", self.said(command) or "", command)
        self.assertIsNone(self.said("echo 'unclosed"))

    def hook(self, command: str) -> subprocess.CompletedProcess:
        tools = tomllib.loads((self.guard_pack() / "pack.toml").read_text()).get("guard", {}).get("tools", [])
        env = dict(os.environ, KEEL_HOME=str(ROOT))
        for key in ("KEEL_CARD", "KEEL_CONFIG"):
            env.pop(key, None)
        payload = json.dumps({"tool_name": "Bash", "tool_input": {"command": command}, "cwd": str(ROOT)})
        return subprocess.run([sys.executable, str(ROOT / "bin" / "keel-house-guard"), "c-1",
                               str(self.guard_pack() / "guard"), *tools], input=payload, text=True,
                              capture_output=True, env=env, timeout=60)

    def test_through_the_hook_a_refusal_is_exit_2_and_one_line_and_a_plain_line_runs(self):
        for command in (f"{self.guard_pack()}/publish c-1", f"{self.guard_pack()}/pr c-1 --ready",
                        "git push --force origin b", "git credential fill"):
            done = self.hook(command)
            self.assertEqual((done.returncode, len(done.stderr.strip().splitlines())), (2, 1), command)
        for command in ("git status", 'git commit -m "tidy the loader"'):
            self.assertEqual(self.hook(command).returncode, 0, command)

    GIT_FED_OPEN = ("git ls-files -z | xargs -0 git add", "xargs git rm < gone.txt", "xargs -I{} git add {} < w",
                    "xargs -n1 git -C . add < w", "git status")

    def git_fed_forms(self) -> list[str]:
        """git run through xargs with no subcommand written (c-738): the subcommand would come
        from the feeder, so the guard cannot read it."""
        return ["echo 'push --force origin b' | xargs git", "printf 'push\\0-f\\0' | xargs -0 git",
                "xargs -I{} git {} < words.txt", "xargs -I % git % origin b < w", "xargs -J% git % origin b < w",
                "xargs -i git {} < w", "xargs --replace=@ git @ < w", "xargs -n3 git -C . < w",
                "echo push | env xargs git", "echo push | xargs /usr/bin/git",
                # r1.F5: the placeholders are the xargs that runs git's, not a word named like it
                "env -u xargs xargs -I@ git @ < w", "sudo -u xargs xargs -I@ git @ < w",
                "A=/bin/xargs xargs -I@ git @ < w"]

    # r1.F4: git whose subcommand the shell fills in, fed or not, and xargs carried into a
    # shell's -c body; a filled word after a written subcommand stays open
    GIT_FILLED = ("echo push -f origin main | xargs sh -c 'git \"$@\"' _", 'git "$@"', 'git "$SUB" -f origin main',
                  "git $1 origin b", "git -C . \"$SUB\"", "bash -c 'git \"$@\"' _ push -f origin main",
                  "echo push | xargs sh -c git", "echo push | xargs bash -c 'git -C .'", 'git "${CMD}"')
    GIT_FILLED_OPEN = ('git -C "$DIR" status', 'git commit -m "$MSG"', 'git log "$REF"',
                       "git ls-files | xargs sh -c 'git add \"$@\"' _", 'git diff "$@"')

    def honest_interpreter_lines(self) -> list[str]:
        """r1.F6: interpreter lines an honest house runs, which the script reading (`run_by`)
        must leave open; `pr` run by a bare name outside the pack's folder is some other `pr`."""
        return ["bash ./build.sh x", "bash scripts/x.sh", "python3 manage.py test", "python3 -m pytest",
                "sh ./configure", "sh -c 'echo pr'", "cd /tmp && bash pr c-1 --ready",
                "cd /tmp && python3 pr c-1 --ready", "bash -c 'echo publish' x", "python3 -c 'print(1)' pr"]

    def fed_own_verb_forms(self) -> list[str]:
        """r1.F3, r1.F6: the pack's `pr` with words xargs adds, which the guard cannot read."""
        pack = self.guard_pack()
        return [f"echo --ready | xargs {pack}/pr c-1", f"echo c-1 --ready | xargs {pack}/pr",
                f"echo --ready | xargs bash {pack}/pr c-1", f"echo c-1 | xargs -I@ {pack}/pr @ --draft"]

    def test_honest_interpreter_lines_stay_open(self):
        for command in self.honest_interpreter_lines():
            self.assertIsNone(self.said(command), command)

    def test_through_the_hook_honest_interpreter_lines_run(self):
        for command in self.honest_interpreter_lines():
            self.assertEqual(self.hook(command).returncode, 0, command)

    def test_the_pack_s_pr_fed_by_xargs_is_refused(self):
        for command in self.fed_own_verb_forms():
            self.assertIn("xargs", self.said(command) or "", command)
            done = self.hook(command)
            self.assertEqual(done.returncode, 2, command)
            self.assertIn("xargs", done.stderr, command)

    def test_git_with_a_subcommand_the_shell_fills_in_is_refused(self):
        for command in self.GIT_FILLED:
            self.assertIn("subcommand", self.said(command) or "", command)
        for command in self.GIT_FILLED_OPEN:
            self.assertIsNone(self.said(command), command)

    def test_through_the_hook_git_with_a_subcommand_the_shell_fills_in_is_refused(self):
        for command in self.GIT_FILLED:
            done = self.hook(command)
            self.assertEqual((done.returncode, len(done.stderr.strip().splitlines())), (2, 1), command)
            self.assertIn("subcommand", done.stderr, command)
        for command in self.GIT_FILLED_OPEN:
            self.assertEqual(self.hook(command).returncode, 0, command)

    def test_git_fed_by_xargs_with_no_subcommand_written_is_refused(self):
        for command in self.git_fed_forms():
            self.assertIn("no subcommand written", self.said(command) or "", command)
        for command in self.GIT_FED_OPEN:
            self.assertIsNone(self.said(command), command)

    def test_through_the_hook_git_fed_by_xargs_with_no_subcommand_is_refused(self):
        for command in self.git_fed_forms():
            done = self.hook(command)
            self.assertEqual((done.returncode, len(done.stderr.strip().splitlines())), (2, 1), command)
            self.assertIn("no subcommand written", done.stderr, command)
        for command in self.GIT_FED_OPEN:
            self.assertEqual(self.hook(command).returncode, 0, command)

    def test_a_filled_command_word_fed_words_the_guard_cannot_read_is_refused(self):
        for command in self.filled_fed_forms():
            self.assertIn("the guard cannot read", self.said(command) or "", command)
        for command in ("printf 'a b' | xargs ./run-*.sh", 'printf x | xargs "$VENV"/bin/uv', "xargs grep -l x < f",
                        'echo "$TOOL" | xargs echo', *self.FILLED_OPEN):
            self.assertIsNone(self.said(command), command)

    def test_through_the_hook_a_filled_command_word_with_no_feeder_runs(self):
        for command in self.FILLED_OPEN:
            self.assertEqual(self.hook(command).returncode, 0, command)

    def test_through_the_hook_a_verb_run_by_a_shell_and_a_fed_filled_word_are_refused(self):
        # the sentence is checked, not only the exit: through the hook the card cannot be read,
        # which holds every form of the pack's `pr` whatever the guard made of its flags
        for command, said in [*((f"{form} c-1 --ready", "Approve outcome") for form in self.run_by_forms("pr")),
                              *((f"{form} c-1", "Approve outcome") for form in self.run_by_forms("publish")),
                              *((form, "the guard cannot read") for form in self.filled_fed_forms())]:
            done = self.hook(command)
            self.assertEqual((done.returncode, len(done.stderr.strip().splitlines())), (2, 1), command)
            self.assertIn(said, done.stderr, command)
        self.assertEqual(self.hook("printf 'a b' | xargs ./run-*.sh").returncode, 0)
