"""The guard: `guard <id>` reads a command a house is about to run and says whether it may.

`gh` in a house's shell is signed in as the person the house works for. Keel's house guard
(`bin/keel-house-guard`, the PreToolUse hook on every Bash call) hands each command to this
pack's `guard` verb, and refuses it with the sentence printed here. The command is PARSED,
never matched as text: a commit message, a path or a grep that only mentions the words is
not a command, and a write is a write however it is spaced, quoted or wrapped.

How a line is read (the kit's reader, `keel/packkit/read.py`): it is split into simple commands on `;`, `|`, `&`, `&&`,
`||`, line ends and brackets, with quotes, escapes, redirects and here-documents read as a
shell reads them. It looks inside `$( )`, backticks, `<( )`, `${ }`, `bash -c`, `sh -c`,
`zsh -c`, `eval`, `env -S` and a here-document or here-string fed to a shell, and past
`env`, `command`, `sudo`, `xargs`, `time`, `nohup`, `exec`, `nice`, `timeout`, `function`,
`coproc` and leading `NAME=value` words. An array (`NAME=(...)`) is not a command, and
`$(( ))` is arithmetic. One rule covers a command word the reader cannot fully know (a
variable, a substitution, `$'...'`, a pattern holding `{`, `?`, `*` or `[`, or a mix): when
what is written can be shown to be gh or git (`g?`, `{gh,x}`) it is judged as that tool,
and a command named by a brace list too large to write out (over 256 characters, 16 pairs
or 64 words) is refused outright; otherwise it is a gh line when the next bare word is one of gh's distinctive groups (`pr`,
`issue`, `api`, `auth`, `repo`, `release`, `secret`, `gist`, `workflow`, `ruleset`; not
`run` or `config`, which other tools share), so a read stays open and a write is refused;
otherwise a git push when it could be git and `push` follows; otherwise, when its words come
from xargs (`xargs "$GH"`), refused, since it may be gh (c-738); otherwise some other command. A word with a written base name (`"$VENV"/bin/uv`) is judged by that name. The
rest of the line is judged either way. A line it cannot read (a quote that never
closes, a nesting too deep) is refused when it names `gh`, a push or this pack's own verbs.

What it judges, in each simple command, by its command word (by any path):

- **gh: only the reads are allowed**, so it is deny by default in fact. After the global
  flags (`-R`, `--repo`, `--hostname` and their values) come the group and the verb, and
  the whole list is `READS` below: `pr` view, list, checks, diff, status; `issue` view,
  list, status; `run` view, list, watch; `workflow` view, list; `repo view`; `release`
  view, list; `label list`; `cache list`; `search`; `status`; `auth status` without the
  token; and `gh api` as a GET (no `-X` or `--method` but GET, no `-f`, `-F`, `--field`,
  `--raw-field` or `--input`, before the word `api` or after it, never `graphql`). Asking
  gh for its help runs nothing and is open: a bare `gh`, `gh --version`, `gh help`,
  `gh version`, and for a group gh ships a `--help` that is no flag's value or a `-h` as
  the last word (an extension's `--help` is the extension's own, and stays refused). Everything
  else on gh is refused, a new gh's new write included, with one sentence that names the
  verb and the way that IS the house's where there is one.
- **git push**: refused with a force (leased or not), delete, mirror, all, branches, tags
  or prune flag, shortened or in any cluster of short flags, with a refspec holding `:`,
  `+` or `*`, with a refspec the shell builds, and with more than one refspec. `git -c`
  setting an alias, a push or credential setting or a remote's push refspec is refused,
  and so is `git credential`.
- **This pack's own verbs**: `publish`, and `pr` with `--ready`, however the path is
  quoted or reached (`$KEEL_HOME/packs/github/...`, the `adapters/` link, `cd` then
  `./publish`, `python3 <path>`, `bash <path>/pr <id> --ready`). `pr --draft` and `pr --body` stay a building house's.
- **A research card**, and a review card (c-730), loses every push and every form of this
  pack's `pr`. The card is read (`kb show`) only for a command of that shape; a card that
  cannot be read holds it.

A push or the pack's `pr` while the card is at SHIPPING, and a push to a shared branch of
the flow, are the engine hook's own refusals, made after this guard has allowed the
command, and are not repeated here.

**What it does not read**: a script file the house writes and runs, an alias, a variable
that holds a whole command, a command piped into a shell, `find -exec` or another program
that runs gh, a `case` pattern inside `$( )`, a brace sequence or a variable inside a
brace list, and a flag whose value is taken for the verb (`gh pr --body view merge 1`). It is a fence for an honest house, not a wall. The walls are
GitHub's: the repository's branch protection, and what the signed-in account is allowed
to do.

This module is GitHub's half of the guard: the gh reads, the hints, and the `GuardPolicy`
the kit's guard (`keel/packkit/guard.py`) judges with; the reader, the git push rules, the
pack's own verbs and the card read are the kit's. It imports the standard library and those
two kit modules only: it runs on every Bash call a house on this pack makes.
"""

from pathlib import Path

from keel.packkit import guard
from keel.packkit.guard import GuardPolicy
from keel.packkit.read import DYN, asks_for_help  # noqa: F401 - asks_for_help: the kit's, read by gh() below

HERE = Path(__file__).resolve().parent

# ----- gh: the whole list of reads; a verb that is not here is refused -----
ANY = None
READS = {"pr": ("view", "list", "checks", "diff", "status"), "issue": ("view", "list", "status"),
         "run": ("view", "list", "watch"), "workflow": ("view", "list"), "repo": ("view",),
         "release": ("view", "list"), "label": ("list",), "cache": ("list",), "search": ANY, "status": ANY,
         "help": ANY, "version": ANY}
# every group gh ships, read or write: asking one of these for its help runs nothing
SHIPPED = frozenset((*READS, "api", "auth", "secret", "variable", "gist", "config", "extension", "alias",
                     "ssh-key", "gpg-key", "project", "codespace", "org", "ruleset", "attestation", "browse",
                     "completion"))
# gh's distinctive groups: after a command word that is wholly the shell's to fill in, one of
# these means gh. The groups other tools share (`run`, `config`, `status`, `search`, `cache`,
# `label`, `project` ...) are left out, or `$NPM run build` would be read as gh.
DISTINCT = frozenset(("pr", "issue", "api", "auth", "repo", "release", "secret", "gist", "workflow", "ruleset"))
GH_VALUED = ("-R", "--repo", "--hostname")
API_LONG_VALUED = ("header", "jq", "template", "preview", "hostname", "cache", "method")
API_SHORT_VALUED = "HqtXp"
API_FIELDS = ("field", "raw-field", "input")
OURS = "$KEEL_HOME/packs/github/pr $KEEL_CARD"
THE_READS = ("the reads are `gh pr view`, `list`, `checks`, `diff` and `status`, `gh issue view` and `list`, "
             "`gh run view`, `list` and `watch`, and a GET `gh api <path>`")
HINTS = {("pr", "merge"): "merging is done on GitHub by a person",
         ("pr", "create"): f"open your draft with `{OURS} --draft`",
         ("pr", "ready"): "Approve outcome marks the pull request ready",
         ("pr", "edit"): f"change the body in the card's record and put it up with `{OURS} --body`",
         ("pr", "comment"): "Ship posts the replies from the verdicts you record with `kb verdict`",
         ("pr", "review"): "Ship posts the replies from the verdicts you record with `kb verdict`",
         ("issue", "comment"): "Ship posts the replies from the verdicts you record with `kb verdict`"}
API = ("`gh api` is open for reads only: a GET with no `-f`, `-F`, `--field`, `--raw-field` or `--input`, "
       "and never `graphql`. Put a query in the path (`gh api 'repos/<owner>/<repo>/pulls?state=open'`) "
       "and pick fields with `--jq`.")
SIGN_IN = "the sign-in is not yours to read, change or switch: `{said}` is refused. `gh auth status` says who is signed in."
XARGS = ("gh run through xargs cannot be read, since xargs adds words the guard never sees, so it is "
         "refused: run gh with its arguments written out.")
UNREAD = ("this command could not be read (a quote that never closes, or a nesting too deep) and it names "
          "`gh`, a push or this pack's own verbs, so it is refused: write it as one plain command.")


# ----- gh -----

def gh(args: list[str]) -> str | None:
    """Why this gh command is refused, or None: only `READS` and a GET `gh api` are open."""
    if asks_for_help(args):
        asked = next((word for index, word in enumerate(args) if not word.startswith("-")
                      and not (index and args[index - 1] in GH_VALUED)), None)
        if asked is None or asked in SHIPPED:
            return None                             # help for a group gh ships; an extension's own is not gh's
    plain, at = [], 0
    while at < len(args) and len(plain) < 2:
        word = args[at]
        at += 2 if word in GH_VALUED else 1
        if not word.startswith("-"):
            plain.append(word)
            if word == "api" and len(plain) == 1:
                return api(args[at:], args[:at - 1])
    if not plain:
        return None                                 # a bare `gh`, `gh --version`: it runs nothing
    group, verb = plain[0], (plain[1] if len(plain) > 1 else "")
    if DYN in group or DYN in verb:
        return (f"`gh` with a group or verb the shell fills in cannot be read, so it is refused: "
                f"write the command out; {THE_READS}.")
    if group == "auth":
        return None if verb == "status" and not shows_token(args) else SIGN_IN.format(said=f"gh auth {verb}".strip())
    if group in READS and (READS[group] is ANY or verb in READS[group]):
        return None
    said = f"gh {group} {verb}".strip()
    hint = HINTS.get((group, verb), THE_READS)
    return f"`{said}` is not a read, and everything else on `gh` is refused to a house: {hint}."


def shows_token(args: list[str]) -> bool:
    """`gh auth status --show-token`, or its `-t` in a cluster (`-h` there takes a value)."""
    for word in args:
        if word.startswith("--show-token"):
            return True
        if word.startswith("-") and not word.startswith("--"):
            for letter in word[1:]:
                if letter == "h":
                    break
                if letter == "t":
                    return True
    return False


def sends(words: list[str]) -> tuple[bool, list[str]]:
    """Whether these words of a `gh api` call send something (a method other than GET, a
    field, an input), and the words among them that are no flag and no flag's value."""
    bare, at = [], 0
    while at < len(words):
        word = words[at]
        at += 1
        if word.startswith("--"):
            name, given, value = word[2:].partition("=")
            if name in API_FIELDS:
                return True, bare
            if name in API_LONG_VALUED and not given:
                value, at = (words[at] if at < len(words) else ""), at + 1
            if name == "method" and value.upper() != "GET":
                return True, bare
        elif word.startswith("-") and len(word) > 1:
            for index, letter in enumerate(word[1:], start=2):
                if letter in "fF":
                    return True, bare
                if letter in API_SHORT_VALUED:
                    value = word[index:]
                    if not value:
                        value, at = (words[at] if at < len(words) else ""), at + 1
                    if letter == "X" and value.lstrip("=").upper() != "GET":
                        return True, bare
                    break
        else:
            bare.append(word)
    return False, bare


def api(after: list[str], before: list[str] = ()) -> str | None:
    """`gh api` is open as a GET that sends nothing. A flag written before the word `api`
    counts as one written after it; the endpoint is the first bare word AFTER it (a bare
    word before it is the value of a global flag, `-R o/r`)."""
    wrote, bare = sends(list(after))
    if wrote or sends(list(before))[0]:
        return API
    return API if (bare[0] if bare else "").strip("/").lower().startswith("graphql") else None


def judge(args: list[str], fed: bool) -> str | None:
    """A gh command the guard reads: through xargs it cannot be read; else `gh`."""
    return XARGS if fed else gh(args)


POLICY = GuardPolicy(tools={"gh": judge}, unread=UNREAD, sign_in=SIGN_IN, named=r"(?<![\w-])gh(?![\w-])",
                     distinct=DISTINCT, filled="gh", valued=GH_VALUED)
FENCE = guard.Fence(HERE, POLICY)


def problem(command: str, cwd=None, card=None) -> str | None:
    """Why this command is refused to the card's house, or None when it may run. `card` is
    called for the card only when a push or the pack's `pr` needs its kind."""
    return guard.problem(command, cwd, card, FENCE)
