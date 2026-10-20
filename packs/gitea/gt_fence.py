"""The guard: `guard <id>` reads a command a house is about to run and says whether it may.

A house in this space runs as the person it works for, and git on this machine keeps that
person's sign-in to Gitea. Keel's house guard (`bin/keel-house-guard`, the PreToolUse hook
on every Bash call) hands each command to this pack's `guard` verb, and refuses it with the
sentence printed here. The command is PARSED, never matched as text, by the kit's reader
(`keel/packkit/read.py`) and judged by the kit's guard (`keel/packkit/guard.py`), which own
the push rules, the sign-in rule (`git credential`, and git's credential helpers run by
name, `git-credential-store`), this pack's own verbs (`publish`, `pr --ready`) and the
research and review cards' refusals.

This module is Gitea's half: its command line tool, and a call to its API.

- **tea, Gitea's command line tool, is refused outright** (r2.D3), reads included: a house
  reads with git, the pack's own verbs do the host's writes, and reading tea flag by flag
  kept leaking (the same short flag is a value in one group and a switch in another). Only
  help with no other word but the group runs (`tea`, `tea --help`, `tea -h`, `tea <group>
  --help`), since nothing there is read but the words written. A command word the shell
  fills in, followed by any tea command or alias (`DISTINCT`), is refused as possibly tea, and
  so is one whose words xargs adds (`xargs "$TEA"`, the kit's, c-738).
- **`curl` or `wget` with a word that holds `/api/v1` is refused**, whatever the address
  and whatever the method. A house has nothing to ask Gitea itself: what reviewers said
  arrives in its batches, and everything that writes there goes through this pack's `pr` or
  the user's Ship. (An API of that shape on some other host is refused too: that cost is
  accepted.) Through xargs the address is not written on the line, so it cannot be read and
  is refused.

**What it does not read**, beyond what the kit's guard says: an address the shell builds
whole (`curl "$URL"`), and a program other than curl or wget that speaks HTTP (a Python
one-liner). It is a fence for an honest house, not a wall. The walls are Gitea's: the
repository's branch protection, and what the signed-in account is allowed to do.

It imports the standard library and those two kit modules only: it runs on every Bash call
a house on this pack makes.
"""

import re
from pathlib import Path

from keel.packkit import guard
from keel.packkit.guard import GuardPolicy
from keel.packkit.read import DYN

HERE = Path(__file__).resolve().parent
API = "/api/v1"
HOST_API = ("`{tool}` to the code host's API (`" + API + "`) is refused to a house: what reviewers said arrives "
            "in your batches, a pull request is opened with this pack's `pr <card> --draft`, replies are posted "
            "by Ship from the verdicts you record, and merging is done in Gitea by a person.")
XARGS = ("`{tool}` run through xargs cannot be read, since xargs adds words the guard never sees, so it is "
         "refused: run it with its arguments written out.")
SIGN_IN = ("the sign-in is not yours to read or change: `{said}` is refused. A pull request is opened by this "
           "pack's `pr <card> --draft`, and Ship posts for the user.")
UNREAD = ("this command could not be read (a quote that never closes, or a nesting too deep) and it names a "
          "push, the sign-in, the code host's API or this pack's own verbs, so it is refused: write it as one "
          "plain command.")
NAMED = (rf"(?<![\w-])(?:curl|wget)(?![\w-]).*{re.escape(API)}|(?<![\w-])git-credential"
         r"|(?<![\w-])tea(?![\w-])")

# ----- tea: refused outright (r2.D3) -----
TEA = ("tea is not available to a house: `{said}` is refused. Read with git (`git log`, `git diff`, `git show` "
       "in your worktree); what reviewers said arrives in your batches, a pull request is opened with this "
       "pack's `pr <card> --draft`, and Ship posts the replies.")
HELP = (("--help",), ("-h",))       # help, and nothing else on the line but one group before it
# tea's global flags that take a value: only to find the word after a command word the shell
# fills in (`"$TEA" --login work pr merge 5` is tea's `pr`), never to read a tea line. Any bare
# word after it in `DISTINCT` is enough too (`distinct_anywhere`, r2.D4), so a flag not listed
# here, with its value, cannot hide the command (`"$TEA" --limit 5 pr merge 7`).
GLOBAL_VALUED = ("--repo", "-r", "--login", "-l", "--remote", "-R", "--output", "-o")
# every tea command and alias (r2.F2): after a command word wholly the shell's to fill in
# (`$(which tea)`, `"$TEA"`), one of these means tea, and the line is refused as tea is (r2.D3).
# Short aliases (`c`, `i`, `r`) are in it too, which is the cost of reading every tea. So is this
# (r2.D1): a shell-filled git or docker word followed by a word tea shares (`"$GIT" clone url`,
# `$(which git) branch x`, `"$DOCKER" login`) is refused as possibly tea. That is fail-closed
# on purpose, and the refusal says the command word could not be read and may be tea.
DISTINCT = frozenset((
    "pulls", "pull", "pr", "issues", "issue", "i", "comment", "c", "logins", "login", "logout", "repos", "repo",
    "releases", "release", "r", "branches", "branch", "b", "labels", "label", "milestones", "milestone", "ms",
    "organizations", "organization", "org", "webhooks", "webhook", "hooks", "hook", "admin", "a", "times",
    "time", "t", "open", "o", "clone", "C", "notifications", "notification", "n", "actions", "action", "api",
    "whoami"))


def tea(args: list[str], fed: bool) -> str | None:
    """Every tea line is refused, but help with no other flag: `tea`, `tea --help`, `tea -h`,
    or one group then `--help` or `-h`. Nothing is read flag by flag (r2.D3)."""
    help_only = (not args or tuple(args) in HELP
                 or (len(args) == 2 and not args[0].startswith("-") and (args[1],) in HELP))
    if help_only and not fed and not any(DYN in word for word in args):
        return None
    return TEA.format(said=" ".join(["tea", *args[:2]]).replace(DYN, "$..."))


def http(tool: str):
    """The judge of one HTTP tool: refused when aimed at the API, or through xargs."""
    def judge(args: list[str], fed: bool) -> str | None:
        if fed:
            return XARGS.format(tool=tool)
        if any(API in word.lower() for word in args):
            return HOST_API.format(tool=tool)
        return None
    return judge


POLICY = GuardPolicy(tools={"tea": tea, "curl": http("curl"), "wget": http("wget")}, unread=UNREAD,
                     sign_in=SIGN_IN, named=NAMED, distinct=DISTINCT, filled="tea", valued=GLOBAL_VALUED,
                     sign_in_names=("git-credential",), distinct_anywhere=True)
FENCE = guard.Fence(HERE, POLICY)


def problem(command: str, cwd=None, card=None) -> str | None:
    """Why this command is refused to the card's house, or None when it may run."""
    return guard.problem(command, cwd, card, FENCE)
