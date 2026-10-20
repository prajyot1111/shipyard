"""The guard: what `guard <id>` answers for a command a house is about to run.

Three lists, each written out here by hand and none built from the guard's own tables:

- `WRITES`: every way of writing to GitHub, or of taking the sign-in, that must be refused;
- `READS`: what a house may run, the commands the pack's rules name among them;
- `FREE`: lines that only MENTION the words (a commit message, a path, a grep) and must be
  allowed, which is what the text-matching fence before this one could not do.

Each list is held twice: against the reader in this process, and through the real hook
(`bin/keel-house-guard` as a subprocess fed the PreToolUse JSON), which is the contract the
harness runs. The guard knows no stage: a push at shipping is the engine hook's refusal,
held by the engine's own tests.
"""

import json
import os
import shlex
import subprocess
import sys
import time
import unittest

import suitefence

import gh_fence
from keel.packkit import guard

PACK = suitefence.PACK
ROOT = PACK.parent.parent
HOOK = ROOT / "bin" / "keel-house-guard"
BRANCH = "shipyard/c-41-tidy-the-loader"
COMMIT_BY_HEREDOC = ("git commit -m \"$(cat <<'EOF'\nThe draft is opened by the pack\n\n"
                     "gh pr merge is never ours (don't run it), nor is `gh pr ready`.\n"
                     "1) gh pr create goes through the pack's pr verb\nEOF\n)\"")

DEEP = f"{PACK}/publish c-41"
for _ in range(8):
    DEEP = f"bash -c {shlex.quote(DEEP)}"

WRITES = (
    # r3.F1: a method, a field or an input written BEFORE the word `api`
    "gh -XDELETE api repos/o/r/git/refs/heads/b", "gh --method=DELETE api repos/o/r/x",
    "gh -fbody=hi api repos/o/r/issues/1/comments", "gh --field=body=hi api repos/o/r/issues/1/comments",
    "gh --input=x.json api repos/o/r/issues", "gh -X DELETE api repos/o/r/x", "gh -R o/r api graphql",
    "gh -R o/r -f a=1 api repos/o/r/x",
    # r3.F4: the reader's cheap holes
    "$GH api -X DELETE repos/o/r/x", "$(which gh) auth token", "$GH repo delete o/r", "$GH gist create x",
    '"$GH" issue close 3', "${GH} release create v1", "$GH secret set X", "$GH workflow run ci.yml",
    "$GH ruleset view", "$GH -R o/r pr merge 1",
    "time -p gh pr merge 1", "/usr/bin/time gh pr merge 1", "/usr/bin/time -o t.txt gh pr merge 1",
    "function f { gh pr merge 1; }; f", "coproc gh pr merge 1", "bash <<< 'gh pr merge 1'",
    "echo ${x:-$(gh pr merge 1)}", 'echo "${x:-`gh pr merge 1`}"', "x=$((1 << 3))\ngh pr merge 1",
    "(( n = 1 << 3 ))\ngh pr merge 1", "env -S 'gh pr merge 1'", "env --split-string='gh pr merge 1'",
    "{gh,pr,merge,1}", "/opt/homebrew/bin/g? pr merge 1", "g[h] pr merge 1", "$'\\x67h' pr merge 1",
    "deps=(a $(gh pr merge 1))", "gh pr comment 1 --body --help", DEEP,
    # a pattern as one command word does not stop the rest of the line from being judged
    "./run-*.sh; git credential fill", "./run-*.sh; cd packs/github && ./publish c-41",
    "./run-*.sh && gh pr merge 1", "case $b in\nfeat*) gh pr merge 1 ;;\nesac", "packs/github/p* c-41",
    "packs/git*/publish c-41", "gi? push --force origin b", "/usr/bin/g* credential fill",
    # one rule for a command word the reader cannot fully know: a pattern it cannot match is
    # still gh before one of gh's groups, and git before `push`
    "g[[:alpha:]] pr merge 1", "[^x]h pr merge 1", "$GH* pr merge 1", "gi[[:alpha:]] push --force origin b",
    "{{gh,pr},merge,1}", "{a,{b,gh}} pr merge 1", "g${X}h -R o/r issue close 3", "$G -C . push --force origin b",
    "[^x]it -c x=y push --delete origin b", "/usr/bin/g[[:lower:]] auth token",
    # a short brace word is written out however many pairs it has: one of its words is gh
    "{g,x}{h,y}{,1}{,2} run cancel 1", "{g,a,b,c,d}{h,e,f,i,j} variable set X", "{g,x}{h,y}{,1}{,2}{,3}{,4} x",
    # a brace word too large to write out is unknown, never harmless: refused when it names gh
    "{a,b,c,d,e,f,g,h,gh}{,1,2,3,4,5,6,7} x", "{a,b,c,d,e,f,g,h,git}{,1,2,3,4,5,6,7} status",
    "{" * 20 + "gh" + "}" * 20 + " x", "{" * 5000 + "}" * 5000 + "; git push --force origin b",
    "{" * 5000 + "}" * 5000 + " pr merge 1",
    # help is gh's own only for a group gh ships
    "gh some-extension go --help", "gh some-extension -h",
    # r3.F5: a push by a shortened flag, an alias or a config handed to git
    "git push origin --del b", "git push --mir", "git push --al origin", "git push --pru origin",
    "git push --tag", "git push --bran origin", "git push --forc origin b",
    "git -c alias.p=push p --force origin b", "git -c remote.origin.push=+HEAD:refs/heads/main push",
    "git --attr-source HEAD push --force origin b", "git -c credential.helper=store fetch",
    "git -c push.default=matching push",
    # gh api that writes
    "gh api --method PUT repos/o/r/pulls/1/merge", "gh api -X DELETE repos/o/r/git/refs/heads/b",
    "gh api -XDELETE repos/o/r/git/refs/heads/b", "gh api --method=PATCH repos/o/r/pulls/1",
    "gh api -iX PUT repos/o/r/pulls/1/merge", "gh api repos/o/r/issues/1/comments -f body=hi",
    "gh api repos/o/r/pulls/1 -F draft=false", "gh api repos/o/r/x --field a=1",
    "gh api repos/o/r/x --raw-field a=1", "gh api repos/o/r/x --input -", "gh api repos/o/r/x --input=body.json",
    "gh api graphql -f query='mutation{markPullRequestReadyForReview(input:{}){clientMutationId}}'",
    "gh api graphql", "gh api -H 'Accept: x' repos/o/r/x -fa=1", "gh api -X $METHOD repos/o/r/x",
    # gh pr
    "gh pr merge 1", "gh pr merge", "gh -R o/r pr merge 1", "gh pr -R o/r merge 1 --squash",
    "gh --repo o/r pr merge", "gh pr --repo=o/r merge 1",
    "cd /tmp && gh pr ready 1", "gh pr close 1", "gh pr reopen 1", "gh pr review 1 --approve",
    "gh pr edit 1 --title x", "gh pr comment 1 --body hi", "gh pr create --fill",
    "gh pr create --title x --body y", "gh pr update-branch 12", "gh pr lock 12", "gh pr unlock 12",
    "gh pr checkout 12",
    # the same, spelled around a single space
    "gh pr  merge 1", "gh pr\tready", 'gh pr "merge" 1', "gh pr 'comment' 1 --body hi", "gh pr ready;echo done",
    "gh pr ready|cat", "gh pr ready&&true", "(gh pr ready)", "echo start\ngh pr ready\necho end",
    "gh pr merge;echo done", "gh pr merge>out.txt", "gh pr merge 2>&1 | tail", "gh  repo delete o/r",
    "/opt/homebrew/bin/gh pr merge 1", '"gh" pr merge 1', "g\\h pr merge 1", "gh pr view 12 && gh pr merge 12",
    "git commit -m x; gh pr merge", "gh pr $VERB 1", "$GH pr merge 1",
    # the same, run by something else
    'bash -c "gh pr merge 1"', "sh -c 'gh pr ready'", 'zsh -lc "gh pr close 1"', 'eval "gh pr merge 1"',
    "eval gh pr merge 1", "echo $(gh pr ready)", 'echo "$(gh pr ready 1)"', "echo `gh pr merge 1`",
    'echo "now `gh pr merge 1`"', "env GH_PAGER= gh pr merge 1", "GH_REPO=o/r gh pr merge 1",
    "command gh pr merge 1", "sudo -u dev gh pr merge 1", "time gh pr merge 1", "nohup gh pr merge 1 &",
    "timeout 30 gh pr merge 1", "echo 12 | xargs gh pr merge", "echo merge | xargs -n1 gh pr",
    "if true; then gh pr merge 1; fi", "{ gh pr merge 1; }", "for n in 1 2; do gh pr close $n; done",
    "true || gh pr merge 1", "! gh pr merge 1", "bash <<EOF\ngh pr merge 1\nEOF", "diff <(gh pr merge 1) x",
    'bash -c "sh -c \'gh pr merge 1\'"',
    # gh issue: a pull request's conversation is the issue of the same number
    "gh issue comment 12 --body hi", "gh issue comment 12;true", "gh issue close 12", "gh issue reopen 12",
    "gh issue edit 12 --title x", "gh issue create --title x", "gh issue delete 12", "gh issue lock 12",
    "gh issue unlock 12", "gh issue pin 12", "gh issue unpin 12", "gh issue transfer 12 o/x",
    "gh issue develop 12",
    # every other group and verb that is not a named read
    "gh repo delete o/r --yes", "gh repo edit --visibility public", "gh repo create x", "gh repo fork",
    "gh release create v1", "(gh release create v1)", "gh release delete v1", "gh secret set X",
    "gh variable set X", "gh config set git_protocol ssh", "gh extension install o/x",
    "gh alias set co 'pr checkout'", "gh ssh-key add key.pub", "gh gpg-key add k", "gh gist create notes.txt",
    "gh label create bug", "gh label create bug|cat", "gh cache delete 1", "gh project create",
    "gh codespace create", "gh org list", "gh attestation verify x",
    "gh workflow run ci.yml", "gh workflow enable ci.yml", "gh workflow disable ci.yml",
    "gh run rerun 1", "gh run cancel 1", "gh run delete 1", "gh browse", "gh some-extension go",
    # the sign-in
    "gh auth token", "gh auth git-credential get", "gh auth login", "gh auth logout", "gh auth switch",
    "gh auth refresh", "gh auth setup-git", "gh auth status --show-token", "gh auth status -t",
    "gh auth status -at", "git credential fill", "git credential approve", "git credential-osxkeychain get",
    "git -C . credential fill",
    # a push that is not a plain push of one branch
    "git push -f origin b", "git push --force origin b", "git push --force-with-lease origin b",
    "git push --force-with-lease=b origin b", "git push origin --delete b", "git push -d origin b",
    "git push -uf origin b", "git push -fu origin b", "git push -uqf origin b", "git push --mirror",
    "git push --all origin", "git push --tags", "git push --prune origin", "git push origin +b",
    "git push origin '+b'", "git push origin :b", "git push origin HEAD:main", "git push origin b:other",
    "git push origin 'refs/heads/*'", "git -C . push --force origin b", "/usr/bin/git push -f origin b",
    "git -c push.default=current push --force", "git push -o ci.skip --force origin b",
    f"git push origin {BRANCH} other-branch", 'bash -c "git push -f origin b"',
    "git push origin b --force",
    # the pack's own publishing verbs, however the path is said
    f"{PACK}/publish c-41", "packs/github/publish c-41 --answer", "$KEEL_HOME/adapters/github/publish c-41",
    '"$KEEL_HOME/packs/github/publish" c-41', f"'{PACK}/publish' c-41", f"python3 {PACK}/publish c-41",
    "bash packs/github/publish c-41", "cd packs/github && ./publish c-41", '"${KEEL_HOME}"/packs/github/publish c-41',
    f"{PACK}/pr c-41 --ready", "$KEEL_HOME/packs/github/pr $KEEL_CARD --ready",
    '"$KEEL_HOME/packs/github/pr" "$KEEL_CARD" --ready', f"{PACK}/pr c-41 $MODE",
)
# Refused, and not a write: reads outside the list, and lines the guard cannot see through.
# Each is an honest line a house may type; they are here so the price stays on record.
REFUSED_NOT_WRITES = (
    "gh ruleset view", "gh run download 99", "gh release download v1", "gh repo list",
    "gh api -X GET search/issues -f q=loader", "gh api graphql -f query='{viewer{login}}'",
    'git push origin "$BRANCH"', 'git push -u origin "$(git branch --show-current)"',
    "echo 12 | xargs gh pr view", "./tool-*.sh pr merge 1",
    # a command named by a brace list too large to write out is refused whatever follows it
    "{a,b}{c,d}{e,f}{g,h}{i,j}{k,l}{m,n} status", "{" * 5000 + "}" * 5000 + " status",
    "{a,b,c,d,e,f,g,h,i}{,1,2,3,4,5,6,7}.sh run", "{a,b}" + "x" * 300 + " status",
)
# Open, and they should not be: spellings the reader is known not to see through. They are
# the limit the module, the house text and the Atlas state, held here so it stays on record.
NOT_READ = (
    "$G -C api push --force origin b",          # a directory named like a gh group
    "{g..g}h run cancel 1",                     # a brace sequence
    "{$GH,pr,merge,1}", "{$GH,run,cancel,1}",   # a variable inside a brace list
)
# What a house may run. The first block is what the pack's rules name.
READS = (
    "gh pr view 12", "gh pr checks 12", "gh pr checks <number>", "gh run view 99 --log-failed",
    "gh run view <run> --log-failed", "gh issue view 3", "gh api repos/o/r/pulls/12/comments",
    "gh auth status", "git diff origin/main...HEAD", "git push -u origin HEAD", f"git push -u origin {BRANCH}",
    f"git push origin {BRANCH}", f"{PACK}/pr c-41 --draft", f"{PACK}/pr c-41 --body",
    "$KEEL_HOME/packs/github/pr $KEEL_CARD --draft", '"$KEEL_HOME/packs/github/pr" "$KEEL_CARD" --body',
    # the rest of the list of reads
    "gh pr list", "gh pr diff 12", "gh pr status", "gh issue list", "gh issue status", "gh run list",
    "gh run watch 99", "gh workflow view ci.yml", "gh workflow list", "gh repo view", "gh repo view o/r --json name",
    "gh release view v1", "gh release list", "gh label list", "gh cache list", "gh search prs loader",
    "gh status", "gh auth status --hostname github.com", "gh", "gh --version", "command -v gh",
    # a read with what a house adds to it
    "gh api repos/o/r/pulls/12/comments --paginate --jq '.[].body'",
    "gh api repos/o/r/commits/abc/check-runs --paginate", "gh api -X GET repos/o/r/pulls",
    "gh api --method GET repos/o/r/pulls", "gh api --method=get repos/o/r/pulls", "gh api -XGET repos/o/r/pulls",
    'gh api -H "Accept: application/vnd.github+json" repos/o/r/pulls/12',
    'gh api repos/o/r/pulls/12 -H "X-GitHub-Api-Version: 2022-11-28"', "gh api -i repos/o/r/pulls/12",
    "gh api repos/o/r/pulls/12/comments | cut -f1", "gh api repos/o/r/pulls/12/comments | grep -F x",
    'gh api "repos/$OWNER/$REPO/pulls/12"', "gh api repos/o/r/issues/12/comments", "gh api repos/o/r/releases",
    "gh pr view 12 --comments", "gh issue view 3 --comments", "gh pr view 12 --comments | cat",
    "gh pr view 12 --json mergeable,title", "gh pr view 12 --json mergeable,mergeStateStatus,reviews",
    "gh pr view 12 --json comments,reviews,reviewDecision,closed,isDraft,createdAt,locked,editor",
    "gh pr view 12 --json labels", "gh pr list --json number,labels,projectItems", "gh pr list --label bug",
    "gh pr view 12 --repo o/r", "gh pr view 12 -R o/r", "gh -R o/r pr view 12", "gh pr view 12 --json title | grep merge",
    "gh pr checks 12 --watch", 'gh pr view "$PR"', "/opt/homebrew/bin/gh pr view 12", "gh pr view 12 > pr.txt",
    "gh pr view 12 2>&1 | head", "n=$(gh pr view 12 --json number --jq .number)", 'bash -c "gh pr view 12"',
    "gh run list --status cancelled", "gh workflow view runner.yml", 'gh pr list --search "label:bug"',
    "GH_PAGER=cat gh pr view 12", "gh pr view 12; gh pr checks 12",
    # r3.F6: asking gh for its help runs nothing
    "gh help", "gh help api", "gh version", "gh pr --help", "gh pr merge --help", "gh api --help",
    "gh issue create -h", "gh pr view -h", "gh auth status -h github.com", "gh auth status -hgithub.com",
    "gh auth --help", "time gh pr view 12", "$GH pr view 12", "$GH api repos/o/r/pulls",
    "$(which gh) auth status", "$GH repo view", "$GH workflow list", "gh pr view 12 --help",
    "./tool-*.sh pr view 12", "g[[:alpha:]] pr view 12", "$G push -u origin HEAD",
    "gh extension --help", "gh secret set --help", "./run-*.sh && gh pr view 1",
    "arr[0]=$(gh pr view 12 --json number)", "case $b in\nfeat*) gh pr view 12 ;;\nesac",
    "case $b in\ngh*|g?) gh pr view 12 ;;\nesac",
    "git status", "git commit -m 'tidy the loader'", "git fetch origin", "git -C . push -u origin HEAD",
    "git push", "git push -u -q origin HEAD", "git push -o ci.skip origin HEAD", f"{PACK}/publishable c-41",
)
# Lines that only mention the words. None is a write; all were refused by matching text.
FREE = (
    'git commit -m "never gh pr merge"', 'git commit -m "walk through the pr review path"',
    'git commit -m "tighten the config loader"', "git commit -m 'gh pr merge; gh pr ready'",
    'git commit -m "fix (gh pr merge) path"', COMMIT_BY_HEREDOC, "git push -u origin keel/c-41-tighten-the-config",
    "git push -u origin keel/c-41-fix-the-release-label", f"git push -u origin {BRANCH}; git branch -d old",
    "git branch -d old", "git branch -D old-force", "git tag -d v1", "git -C . stash push", "git log | grep pushed",
    'git log --grep="gh pr merge"', "cat packs/github/pr | grep merge", "cat packs/github/gh_fence.py",
    "ls packs/github/publish", "git add packs/github/publish", "git add packs/github/publishable",
    "git diff -- packs/github/pr", 'grep -rn "gh pr merge" docs/', "rg 'git push --force' docs",
    'echo "gh pr merge"', "echo 'git push -f origin b'", "echo gh pr merge", "sed -n 1,5p README.md # gh pr merge",
    "cat > notes.md <<EOF\ngh pr merge 1\ngit push --force\nEOF", "cat <<'EOF' > notes.md\n$(gh pr merge 1)\nEOF",
    "python3 -c \"print('gh pr merge')\"", "xargs grep -l gh < files.txt", "which gh", "make test",
    "ls /tmp/gh/pr/merge", "cat docs/gh.md", "./scripts/gh-report pr merge", "kb note c-41 'gh pr merge was refused'",
    "git config --get remote.origin.url", "git credentialx", "npm run publish", "bin/publish c-41",
    "echo done > merge", "for f in a b; do echo $f; done", "case $x in a) echo gh;; esac",
    # r3.F6: an array is not a command, and a script of the house's own is not the pack's verb
    "deps=(gh jq)", "args+=(gh pr merge)", "declare -a tools=(gh git push)", "local words=(git push --force)",
    'for tool in "${deps[@]}"; do command -v "$tool"; done', '"$SCRIPTS"/publish', "$(pwd)/publish --dry-run",
    '"$SCRIPTS"/pr 12 --ready', "x=$((1 << 3)); echo $x", "ls *.py", "./run-*.sh", "$EDITOR notes.md",
    "$PY -m unittest tests.test_packs", "echo ${x:-$(date)}",
    # a tool the house names through a variable is not gh because its next word is also a gh group
    "$UV run pytest", "$NPM run build", "$DOCKER run -it x", "$TOOL config set a b", "$X status",
    '"$VENV"/bin/uv run pytest', "$HOME/bin/tool pr merge 1", "${TOOL}ctl api delete x", "$X search y",
    "$X cache clear", "$X label add", "$X project init", "$X variable set a", "$X extension install y",
    "$X alias set a b", "$X browse", "$X org list", "$X codespace create",
    "./run-*.sh; git status", "names[1]=gh", "./p*.sh c-41", "scripts/[a-z]*.sh merge",
    "./run-*.sh push --force", "./tool-?.sh run pr", "{a,b}.sh status", "$X push-images --force",
    "echo {1..100000}", "touch {a,b,c,d,e,f,g,h,i}{,1,2,3,4,5,6,7}.txt", "{a,b}{c,d}.sh status",
    "echo {a,b}{c,d}{e,f}{g,h}{i,j}{k,l}{m,n}", "{a,b}{c,d}{e,f}{g,h}{i,j}{k,l}.sh run",
)


def research() -> dict:
    return {"id": "c-41", "options": {"kind": "research"}}


def building() -> dict:
    return {"id": "c-41", "stage": "building", "options": {}}


def through_hook(command: str, *extra: str, card: str = "c-41") -> subprocess.CompletedProcess:
    """The hook as the harness runs it: the PreToolUse JSON on stdin, the card and (for a
    card on this pack) the pack's guard and its tool as arguments."""
    env = dict(os.environ, KEEL_HOME=str(ROOT), PATH=os.environ.get("PATH", ""))
    for key in ("KEEL_CARD", "KEEL_CONFIG"):
        env.pop(key, None)
    payload = json.dumps({"tool_name": "Bash", "tool_input": {"command": command}, "cwd": str(ROOT)})
    return subprocess.run([sys.executable, str(HOOK), card, *extra], input=payload, text=True,
                          capture_output=True, env=env, timeout=60)


def engine_s(command: str) -> bool:
    """A line the ENGINE hook asks the board about (a push, the pack's `pr`), which these
    tests have no board for: it is held in this process only."""
    return "push" in command or "github/pr" in command or "/publish" in command


class ReaderTest(unittest.TestCase):
    def said(self, command: str, card=building) -> str | None:
        return gh_fence.problem(command, str(ROOT), card)

    def test_every_write_is_refused_however_it_is_spelled(self):
        self.assertEqual([command for command in WRITES if self.said(command) is None], [])

    def test_every_read_is_open(self):
        self.assertEqual({command: self.said(command) for command in READS if self.said(command)}, {})

    def test_a_line_that_only_mentions_the_words_is_open(self):
        self.assertEqual({command: self.said(command) for command in FREE if self.said(command)}, {})

    def test_no_line_is_in_two_of_the_lists(self):
        lists = (WRITES, REFUSED_NOT_WRITES, NOT_READ, READS, FREE)
        self.assertEqual(len(set().union(*lists)), sum(len(one) for one in lists))

    def test_a_read_outside_the_list_and_a_line_it_cannot_see_through_are_refused_too(self):
        """r3.F6: refused, and not writes; kept apart from WRITES so the lists say what they hold."""
        self.assertEqual([command for command in REFUSED_NOT_WRITES if self.said(command) is None], [])
        self.assertIn("xargs", self.said("echo 12 | xargs gh pr view"))
        self.assertNotIn("pull request", self.said("echo 12 | xargs gh run view"))
        self.assertIn("the shell fills in", self.said("$GH pr merge 1"))

    def test_what_the_reader_is_known_not_to_see_through_is_on_record(self):
        self.assertEqual({command: self.said(command) for command in NOT_READ if self.said(command)}, {})

    def test_a_huge_brace_word_is_judged_at_once_and_the_rest_of_the_line_with_it(self):
        """The guard has four seconds in the hook, and one that runs out refuses only a
        line naming gh. Writing out nested braces took time that grew with the square of
        their number (0.17 s for 5,000, 6 s for the 30,000 here, measured on c-689); a word
        that large is not written out at all. Timed on the monotonic clock, with room to
        spare."""
        line = "{" * 30000 + "}" * 30000 + "; git push --force origin b"
        started = time.monotonic()
        said = self.said(line)
        took = time.monotonic() - started
        self.assertIn("brace list too large", said or "")
        self.assertLess(took, 1.0)
        self.assertIn("--force", self.said("true " + line) or "")       # as an argument it is no command
        self.assertIsNone(guard.alternatives("{" * 17 + "}" * 17))
        self.assertIsNone(guard.alternatives("{a,b}" + "x" * 300))
        self.assertIsNone(guard.alternatives("{a,b,c,d,e,f,g,h,gh}{,1,2,3,4,5,6,7}"))      # 72 words
        self.assertEqual(sorted(guard.alternatives("{a,{b,gh}}")), ["a", "b", "gh"])

    def test_a_brace_word_is_sized_by_the_words_it_really_stands_for(self):
        """Each pair's own commas, multiplied: 16 and 25 words are written out, 128 are not."""
        for word, count in (("{g,x}{h,y}{,1}{,2}", 16), ("{g,a,b,c,d}{h,e,f,i,j}", 25),
                            ("{a,b}{c,d}{e,f}{g,h}{i,j}{k,l}", 64), ("{a,b}.sh", 2), ("plain", 1)):
            self.assertEqual(len(guard.alternatives(word)), count, word)
        self.assertIsNone(guard.alternatives("{a,b}{c,d}{e,f}{g,h}{i,j}{k,l}{m,n}"))
        self.assertIn("gh", guard.alternatives("{g,x}{h,y}{,1}{,2}"))
        said = self.said("{a,b}{c,d}{e,f}{g,h}{i,j}{k,l}{m,n} status")
        self.assertIn("write the command plainly", said or "")
        self.assertEqual(len(said.splitlines()), 1)

    def test_the_limits_are_said_the_same_in_the_module_the_house_text_and_the_atlas(self):
        """r3.F7."""
        limits = ("a script file the house writes and runs, an alias, a variable that holds a whole command, "
                  "a command piped into a shell, `find -exec` or another program that runs gh, a `case` pattern "
                  "inside `$( )`, a brace sequence or a variable inside a brace list, and a flag whose value "
                  "is taken for the verb")
        for path in (PACK / "gh_fence.py", ROOT / "docs" / "atlas" / "62-packs.md"):
            self.assertIn(limits, " ".join(path.read_text().split()), path.name)
        yours = limits.replace("the house writes and runs", "you write and run")
        self.assertIn(yours, " ".join((PACK / "rules" / "house.md").read_text().split()))
        for name in ("62-packs.md", "20-houses.md"):
            said = " ".join((ROOT / "docs" / "atlas" / name).read_text().split())
            self.assertIn("first the `pgrep -f` loop, then the pack's guard, then the hook's two push checks", said, name)

    def test_a_refusal_is_one_sentence_naming_the_verb_and_the_way_that_is_the_house_s(self):
        for command, parts in {
                "gh pr merge 1": ("`gh pr merge`", "by a person"),
                "gh pr create --fill": ("`gh pr create`", "/pr $KEEL_CARD --draft"),
                "gh pr ready 12": ("`gh pr ready`", "Approve outcome"),
                "gh pr comment 1 --body hi": ("`gh pr comment`", "kb verdict"),
                "gh issue comment 1 --body hi": ("`gh issue comment`", "kb verdict"),
                "gh pr edit 1 --body x": ("`gh pr edit`", "/pr $KEEL_CARD --body"),
                "gh gist create notes.txt": ("`gh gist create`", "gh pr view"),
                "gh api repos/o/r/x -f a=1": ("`gh api`", "--jq"),
                "gh auth token": ("sign-in",),
                "git credential fill": ("sign-in",),
                "git push --force origin b": ("--force", "git push -u origin HEAD"),
                f"git push origin {BRANCH} other": ("one branch",),
                "git push origin HEAD:main": ("HEAD:main",),
                f"{PACK}/publish c-41": ("Approve outcome",),
                f"{PACK}/pr c-41 --ready": ("Approve outcome",)}.items():
            said = self.said(command)
            self.assertIsNotNone(said, command)
            self.assertEqual(len(said.splitlines()), 1, command)
            for part in parts:
                self.assertIn(part, said, command)

    def test_a_research_card_loses_every_push_and_every_form_of_the_pack_s_pr(self):
        for command in ("git push -u origin HEAD", f"git push origin {BRANCH}", f"{PACK}/pr c-41 --draft",
                        "$KEEL_HOME/packs/github/pr $KEEL_CARD --body", "git -C . push"):
            self.assertIn("research card", self.said(command, research) or "", command)
        for command in ("gh pr view 12", "git status", "git commit -m 'never git push'"):
            self.assertIsNone(self.said(command, research), command)

    def test_the_card_is_read_only_for_a_push_or_the_pack_s_pr_and_an_unread_card_holds_those(self):
        def unread():
            raise guard.CardUnread("the board gave no answer")
        for command in (*FREE[:6], "gh pr view 12", "gh pr merge 1", "git status"):
            gh_fence.problem(command, str(ROOT), unread)            # never asked: nothing raised
        for command in ("git push -u origin HEAD", f"{PACK}/pr c-41 --draft"):
            self.assertIn("could not be read", self.said(command, unread) or "", command)

    def test_a_line_it_cannot_read_is_refused_only_when_it_names_gh_or_a_push(self):
        for command in ("gh pr view 'unclosed", 'echo "unclosed; gh pr merge 1', "git push 'origin b",
                        "x=\x00; gh pr view 1", f"{PACK}/publish c-41 'unclosed",
                        "$KEEL_HOME/packs/github/pr c-41 --ready 'unclosed", "echo ${unclosed; gh pr view 1"):
            self.assertIn("could not be read", self.said(command) or "", command)
        for command in ("echo 'unclosed", 'grep "x', "cat packs/github/gh_fence.py 'x"):
            self.assertIsNone(self.said(command), command)

    def test_every_read_the_rules_name_is_in_the_list_of_reads(self):
        """The house text, the comment method and the pipeline words are READ, and each
        command they tell a house to run is held open above."""
        named = {"rules/house.md": ("gh pr view", "gh pr checks", "gh run view <run> --log-failed", "gh issue view",
                                    "gh api <path>", "gh auth status"),
                 "rules/comments.md": ("gh pr checks <number>", "gh run view <run> --log-failed",
                                       "git diff origin/<base>...HEAD"),
                 "pipeline.md": ("git push -u origin HEAD", "$KEEL_HOME/packs/github/pr $KEEL_CARD --draft")}
        for name, commands in named.items():
            text = (PACK / name).read_text()
            for command in commands:
                self.assertIn(f"`{command}`", text, f"{name} no longer names {command}")
                self.assertIsNone(self.said(command), f"{name} tells a house to run {command}")

    def test_the_house_text_says_what_is_open_what_is_refused_and_that_it_is_no_wall(self):
        said = " ".join((PACK / "rules" / "house.md").read_text().split())
        for part in ("reads each command before it runs", "Everything else on `gh` is refused",
                     "It is a fence, not a wall"):
            self.assertIn(part, said)
        for gone in ("refuse a list of commands as you would type them", "reword it", "as a word of its own"):
            self.assertNotIn(gone, said)

    def test_the_pack_hands_out_no_deny_list_any_more(self):
        self.assertFalse((PACK / "deny").exists())
        self.assertFalse(hasattr(gh_fence, "ALWAYS"))
        self.assertNotIn("Bash(", (PACK / "gh_fence.py").read_text())


class ThroughTheHookTest(unittest.TestCase):
    """`bin/keel-house-guard <card> <pack guard> gh`, as a house on this pack runs it."""

    GUARD = (str(PACK / "guard"), "gh")

    def test_every_write_is_refused_with_exit_2_and_one_line(self):
        """Every one, the pushes and the pack's own `publish` and `pr --ready` included: the
        pack refuses them before the board is asked (r3.F3). The wording is held by
        `test_a_refusal_is_one_sentence_naming_the_verb...`, against literals (r3.F10)."""
        for command in (*WRITES, *REFUSED_NOT_WRITES):
            with self.subTest(command=command):
                done = through_hook(command, *self.GUARD)
                self.assertEqual((done.returncode, done.stdout), (2, ""), done.stderr)
                self.assertEqual(len(done.stderr.strip().splitlines()), 1, done.stderr)

    def test_every_read_and_every_line_that_only_mentions_the_words_is_allowed(self):
        for command in (*READS, *FREE):
            if engine_s(command):
                continue
            with self.subTest(command=command):
                done = through_hook(command, *self.GUARD)
                self.assertEqual((done.returncode, done.stderr), (0, ""))

    def test_a_card_on_a_pack_with_no_guard_verb_is_not_read_by_this_one(self):
        for command in ("gh pr merge 1", "gh api -X DELETE repos/o/r/x", "gh auth token"):
            done = through_hook(command)
            self.assertEqual((done.returncode, done.stderr), (0, ""), command)

    def test_the_guard_verb_answers_json_and_reads_the_card_from_its_argument(self):
        for command, allowed in (("gh pr view 12", True), ("gh pr merge 12", False)):
            done = subprocess.run([str(PACK / "guard"), "c-41"], text=True, capture_output=True, timeout=30,
                                  input=json.dumps({"command": command, "cwd": str(ROOT)}))
            self.assertEqual((done.returncode, done.stderr), (0, ""))
            answer = json.loads(done.stdout)
            self.assertEqual(answer["allow"], allowed)
            self.assertEqual("why" in answer, not allowed)


if __name__ == "__main__":
    unittest.main()
