"""The guard: `guard <id>` reads a command a house is about to run and says whether it may.

A house runs as the person it works for. Keel's house guard (`bin/keel-house-guard`, the
PreToolUse hook on every Bash call) hands each command to the pack's `guard` verb, and
refuses it with the sentence printed here. The command is PARSED (`read.Reader`), never
matched as text: a commit message, a path or a grep that only mentions the words is not a
command, and a write is a write however it is spaced, quoted or wrapped.

This is the half every pack's guard shares; a pack's own guard module gives a `GuardPolicy`
(the host tools it judges and how, its sentences), and its shim calls `main` with its own
folder, so the pack's own verbs are known by the folder they are in, never the kit's.

How a line is read: split into simple commands on `;`, `|`, `&`, `&&`, `||`, line ends and
brackets, with quotes, escapes, redirects and here-documents read as a shell reads them. It
looks inside `$( )`, backticks, `<( )`, `${ }`, `bash -c`, `sh -c`, `zsh -c`, `eval`,
`env -S` and a here-document or here-string fed to a shell, and past `env`, `command`,
`sudo`, `xargs`, `time`, `nohup`, `exec`, `nice`, `timeout`, `function`, `coproc` and
leading `NAME=value` words. One rule covers a command word the reader cannot fully know
(`Judge.filled`). A line it cannot read is refused when it names what the policy reads, a
push or the pack's own verbs.

What the kit judges itself, for every pack:

- **git push**: refused with a force (leased or not), delete, mirror, all, branches, tags
  or prune flag, shortened or in any cluster of short flags, with a refspec holding `:`,
  `+` or `*`, with a refspec the shell builds, and with more than one refspec. `git -c`
  setting an alias, a push or credential setting or a remote's push refspec is refused,
  and so is `git credential`. git through xargs with no subcommand written (`xargs git`,
  `xargs -I{} git {}`) is refused, since the feeder would choose it (c-738), and so is git
  whose subcommand the shell fills in (`git "$@"`), fed or not (r1.F4). A shell's `-c` body
  run under xargs is fed as the shell is.
- **The pack's own verbs**: `publish`, and `pr` with `--ready`, however the path is quoted
  or reached (the pack's folder by any path, the `adapters/` link, `cd` then `./publish`,
  `python3 <path>`, and a shell or Python handed it as a script, `bash <path>/pr <id> --ready`,
  judged as the verb itself, c-738). `pr --draft` and `pr --body` stay a building house's.
- **A research card**, and a review card (c-730), loses every push and every form of the
  pack's `pr`. The card is read (`kb show`) only for a command of that shape; a card that
  cannot be read holds it.

A push or the pack's `pr` while the card is at SHIPPING, and a push to a shared branch of
the flow, are the engine hook's own refusals, made after this guard has allowed the command.

This module imports the standard library and the reader only, and reads the pack's words
(`pack.toml`) only for a sentence that says them: it runs on every Bash call.
"""

import fnmatch
import json
import os
import re
import subprocess
import sys
from pathlib import Path

from keel.packkit.read import (DYN, PATTERN, PYTHON, SHELLS, WRAPPERS, Reader, Unreadable, alternatives,
                               bare_after, base, could_be, unwrapped)

KIT_ROOT = Path(__file__).resolve().parent.parent.parent
KB_SECONDS = 3
DEPTH_MAX = 4
OWN = ("publish", "pr")  # the pack's verbs a house never runs as it likes

# ----- git -----
GIT_VALUED = ("-C", "-c", "--git-dir", "--work-tree", "--namespace", "--attr-source")
GIT_CONFIG_NEVER = re.compile(r"^(alias\.|push\.|credential\.|remote\..*\.push)", re.IGNORECASE)
PUSH_VALUED = ("--push-option", "--repo", "--receive-pack", "--exec")
PUSH_NEVER = ("force", "delete", "mirror", "all", "branches", "tags", "prune", "follow-tags")
PLAIN_PUSH = "Push your own branch and nothing else: `git push -u origin HEAD` from its worktree."
PUSHES = r"(?<![\w-])git(?![\w-]).*(?<![\w-])push(?![\w-])"

TOO_LARGE = ("this command's name is a brace list too large to read, so it is refused: write the "
             "command plainly.")
EXPANDS = ("this command's first word is a pattern that could expand to `{tool}`, which cannot be read, "
           "so it is refused: write the command out.")
FILLED = ("this command's first word is one the shell fills in, so it could not be read; followed by "
          "`{word}`, it may be {tool}, so it is read as {tool}: ")
FED = ("this command's first word is one the shell fills in, and the words it runs with come from where "
       "the guard cannot read them (xargs adds them), so it may be {tool} and is refused: "
       "write the command out.")
GIT_FED = ("`git` run through xargs with no subcommand written cannot be read, since xargs adds the words "
           "the guard never sees, so it is refused: write the subcommand out (`xargs git add` is fine).")
GIT_FILLED = ("`git` with a subcommand the shell fills in (`git \"$@\"`, `git \"$SUB\"`) cannot be read, so it is "
              "refused: write the subcommand out (`git add \"$@\"` is fine).")


def placeholders(flags: list[str]) -> tuple:
    """The words xargs puts its input in place of (`-I{}`, `-I %`, `-J%`, `-i`, `--replace=@`),
    read from the flags of the xargs that runs the command (`read.unwrapped`, r1.F5), for git
    under xargs (c-738)."""
    found, rest = [], list(flags)
    while rest:
        flag = rest.pop(0)
        if flag in ("-I", "-J") and rest:
            found.append(rest.pop(0))
        elif flag[:2] in ("-I", "-J"):
            found.append(flag[2:])
        elif flag.startswith("-i") or flag.startswith("--replace"):
            given = flag.partition("=")[2] if flag.startswith("--") else flag[2:]
            found.append(given or "{}")             # GNU's `-i` and `--replace` mean `{}`
        elif flag in WRAPPERS["xargs"] and rest:
            rest.pop(0)
    return tuple(mark for mark in found if mark)


# An interpreter's flags, to find the script file it is handed (`script_at`): the letters that
# mean it reads no script file (`-c`, `-m`, `-s`), the letters that take the next word as their
# value, the long flags that do, and what starts a flag.
SHELL_READS = ("cs", "oO", ("--rcfile", "--init-file"), "-+")
PYTHON_READS = ("cm", "WX", ("--check-hash-based-pycs",), "-")


def script_at(words: list[str], inline: str, valued: str, long_valued: tuple, starts: str) -> int | None:
    """Where the script file stands among an interpreter's words, or None when it runs no
    script file (code on its command line, a module, standard input)."""
    at = 0
    while at < len(words):
        word = words[at]
        if word == "--":
            return at + 1 if at + 1 < len(words) else None
        if word.startswith("--"):
            at += 2 if word in long_valued else 1
            continue
        if len(word) < 2 or word[0] not in starts:
            return None if word == "-" else at
        at += 1
        for index, letter in enumerate(word[1:], start=1):
            if letter in inline:
                return None
            if letter in valued:
                at += index == len(word) - 1        # `-o posix`, `-W ignore`; `-Wignore` holds it
                break
    return None


class GuardPolicy:
    """What a pack's guard reads that the kit does not.

    `tools` maps each host tool's command word to its judge, `judge(args, fed) -> refusal or
    None` (`fed`: xargs adds words to it). `named` is a regex for what else makes a line it
    cannot read worth refusing (a push and the pack's own verbs always do). `unread` is that
    refusal; `sign_in` the refusal of `git credential`, with `{said}`. A command word the
    shell fills in, followed by one of `distinct` (past the `valued` flags), is judged as the
    tool `filled`; with `distinct_anywhere` (off unless a pack asks, r2.D4) any bare word after
    it being one of `distinct` is enough, so a flag the policy does not list, with its value,
    cannot hide the command. A command named by one of `sign_in_names` (a prefix) is the
    sign-in's."""

    def __init__(self, tools: dict, unread: str, sign_in: str, named: str = "", distinct=frozenset(),
                 filled: str = "", valued: tuple = (), sign_in_names: tuple = (), distinct_anywhere: bool = False):
        self.tools, self.unread, self.sign_in, self.named = dict(tools), unread, sign_in, named
        self.distinct, self.filled, self.valued, self.sign_in_names = frozenset(distinct), filled, valued, sign_in_names
        self.distinct_anywhere = distinct_anywhere


class CardUnread(Exception):
    """The board did not say what kind of card this is."""


class Fence:
    """A policy and the pack it guards: the pack's folder and name, and its words."""

    def __init__(self, folder, policy: GuardPolicy):
        self.here, self.policy = Path(folder).resolve(), policy
        own = rf"{re.escape(self.here.name)}/(?:{'|'.join(OWN)})(?![\w./-])"
        self.named = re.compile("|".join(part for part in (policy.named, PUSHES, own) if part), re.DOTALL)
        self.judges = dict(policy.tools)
        self._change = None

    def ours(self) -> str:
        """The pack's `pr`, as a house is told to run it."""
        home = Path(os.environ.get("KEEL_HOME") or KIT_ROOT).resolve()
        if self.here.parent == home / "packs":
            return f"$KEEL_HOME/packs/{self.here.name}/pr $KEEL_CARD"
        return f"{self.here}/pr $KEEL_CARD"

    def change(self) -> str:
        """The pack's word for a change (`pack.toml` [terms]), read once, when a sentence says it."""
        if self._change is None:
            import tomllib  # noqa: PLC0415 - only a refusal that says the word reads it
            try:
                terms = tomllib.loads((self.here / "pack.toml").read_text(encoding="utf-8")).get("terms") or {}
            except (OSError, ValueError):
                terms = {}
            if not terms.get("change"):
                from keel.terms import DEFAULTS  # noqa: PLC0415 - the engine's own word, when the pack says none
                terms = DEFAULTS
            self._change = str(terms["change"])
        return self._change


# ----- judging a simple command -----

class Judge:
    """One line's verdict for one card's house on one pack."""

    def __init__(self, fence: Fence, cwd=None, card=None):
        self.fence, self.cwd, self.card, self.kind = fence, Path(cwd) if cwd else None, card, None
        self.feeds = None       # under xargs: the words it puts in place (`-I{}`), else None

    def line(self, text: str, depth: int = 0, feeds: tuple | None = None) -> str | None:
        """`feeds`: a shell's body run under xargs (`xargs sh -c '...'`) is fed as the shell is
        (r1.F4), with the placeholders of the xargs outside it."""
        if depth > DEPTH_MAX:
            raise Unreadable("too deep")
        for command in Reader(text, self.fence.named).read():
            words, flags = unwrapped(command.words)
            own = placeholders(flags) if flags is not None else None
            self.feeds = None if own is None and feeds is None else (*(feeds or ()), *(own or ()))
            fed = self.feeds is not None
            why = self.simple(words, fed, command, depth) if words else None
            if why:
                return why
        return None

    def simple(self, words: list[str], fed: bool, command, depth: int) -> str | None:
        head, rest = words[0], words[1:]
        name = base(head)
        if name == "cd" and rest and DYN not in rest[0]:
            self.cwd = (self.cwd or Path(".")) / rest[0]
            return None
        if name in SHELLS or name == "eval":
            why = None if name == "eval" else self.run_by(rest, SHELL_READS, fed)
            if why:
                return why
            said = [" ".join(rest)] if name == "eval" else [word for word in rest if not word.startswith("-")]
            feeds = self.feeds
            for text in (*said, *command.bodies):
                why = self.line(text.replace(DYN, "$_"), depth + 1, feeds)
                if why:
                    return why
            return None
        if PYTHON.match(name):
            why = self.run_by(rest, PYTHON_READS, fed)
            if why:
                return why
            script = next((word for word in rest if not word.startswith("-")), None)
            if rest[:1] and rest[0] in ("-c", "-m") or script is None:
                return None
            head, rest, name = script, rest[rest.index(script) + 1:], base(script)
        verb = self.own_verb(head)
        if verb:
            return self.own(verb, rest)
        if name in self.fence.judges:
            return self.fence.judges[name](rest, fed)
        if self.fence.policy.sign_in_names and name.startswith(self.fence.policy.sign_in_names):
            return self.fence.policy.sign_in.format(said=name)
        if name == "git":
            return self.git(rest)
        return self.filled(head, name, rest, fed)

    def run_by(self, words: list[str], reads: tuple, fed: bool) -> str | None:
        """A shell or Python handed a script file (c-738): the script and its words are judged
        exactly as running the script itself, so `bash <pack>/pr <id> --ready` is the pack's
        `pr --ready`. A bare name is opened in the working directory first, as both do. This is
        judged beside the reading above, never instead of it: it only ever refuses more."""
        at = script_at(words, *reads)
        if at is None:
            return None
        head, rest = words[at], words[at + 1:]
        if "/" not in head and DYN not in head:
            head = f"./{head}"
        verb = self.own_verb(head)
        if verb:
            return self.own(verb, rest)
        judge = self.fence.judges.get(base(head))
        return judge(rest, fed) if judge else None

    def filled(self, head: str, name: str, rest: list[str], fed: bool) -> str | None:
        """ONE rule for a command word the reader cannot fully know: a variable, a
        substitution, a `$'...'` quote, a pattern (`{`, `?`, `*`, `[`), or a mix of them.

        1. What is written can be SHOWN to be one of the policy's tools or git (a brace
           list written out, a `?` or `*` pattern matched): judged as that tool. The pack's
           own verb under a folder that could be the pack's, and a brace list holding any
           of these, are refused, since which one runs is not known. A brace list too large
           to write out (`alternatives`) is refused outright, whatever follows it.
        2. Otherwise, the next bare word (past the policy's `valued` flags) is one of its
           `distinct` groups: judged as that tool's line, so a read stays open and a write
           is refused.
        3. Otherwise, the word could be git and `push` is the next bare word after git's
           global flags: judged as a git push.
        4. Otherwise, xargs adds its words and the word could be one of the policy's tools
           or git: refused (c-738), since what runs cannot be known. With no feeder it is not
           (r1.F1): `"$PY" "$SCRIPT"` is some other command.
        5. Otherwise it is some other command.

        A word with a written base name (`"$VENV"/bin/uv`) is not unknown: it is judged
        by that name, as any path is. Only this one command is judged here; the rest of
        the line is judged as normal."""
        pattern = head not in ("[", "[[") and any(mark in head for mark in PATTERN)
        if not (DYN in name or pattern):
            return None
        shown = self.shown(head, rest, fed) if pattern else None
        if shown is not None:
            return shown or None                    # "" when it was shown and judged harmless
        policy = self.fence.policy
        group = bare_after(rest, policy.valued)
        if policy.distinct_anywhere and group not in policy.distinct:
            group = next((word for word in rest if word in policy.distinct), group)
        if policy.filled and group in policy.distinct:
            why = self.fence.judges[policy.filled](rest, fed)
            return why and FILLED.format(word=group, tool=policy.filled) + why
        if could_be("git", name) and bare_after(rest, GIT_VALUED) == "push":
            why = self.git(rest)
            if why:
                return FILLED.format(word="push", tool="git") + why
        if fed:
            tool = next((tool for tool in (*self.fence.judges, "git") if could_be(tool, name)), None)
            if tool:
                return FED.format(tool=policy.filled or tool)
        return None

    def shown(self, head: str, rest: list[str], fed: bool) -> str | None:
        """Step 1 for a pattern word: the refusal, `""` when it is shown to be a tool and
        that command may run, or None when nothing can be shown. Only `?` and `*` are
        matched; a bracket or a part the shell fills in shows nothing."""
        words = alternatives(head)
        if words is None:
            return TOO_LARGE                        # unknown, never harmless: nothing after it is asked
        judges = [*((tool, lambda judge=judge: judge(rest, fed)) for tool, judge in self.fence.judges.items()),
                  ("git", lambda: self.git(rest))]
        for word in words:
            name, folder = base(word), word.rsplit("/", 1)[0] if "/" in word else ""
            if DYN in name or "[" in name:
                continue
            for tool, judge in judges:
                if fnmatch.fnmatchcase(tool, name):
                    return EXPANDS.format(tool=tool) if word != head else (judge() or "")
            for verb in OWN:
                if fnmatch.fnmatchcase(verb, name) and "/" in word and self.could_be_here(folder):
                    return EXPANDS.format(tool=f"this pack's {verb}")
        return None

    def could_be_here(self, folder: str) -> bool:
        """Whether a folder, as written, could be this pack's: its last part matches the
        pack's name as a pattern, or it resolves to the pack's directory."""
        here = self.fence.here
        if fnmatch.fnmatchcase(here.name, base(folder)):
            return True
        try:
            path = Path(folder) if folder.startswith("/") else (self.cwd or Path.cwd()) / folder
            return path.resolve() == here
        except OSError:
            return False

    # ----- the pack's own verbs -----

    def own_verb(self, head: str) -> str | None:
        """`publish` or `pr` when the command word is this pack's own, by any path whose
        written part still names the pack's folder, or that resolves to the file."""
        name, here = base(head), self.fence.here
        if name not in OWN or "/" not in head:
            return None
        tail = head.rsplit(DYN, 1)[-1]
        if base(tail.rsplit("/", 1)[0]) == here.name:
            return name                             # .../<pack>/pr, whatever stands before it
        if DYN in head:
            return None                             # `"$SCRIPTS"/publish`: a script of the house's own
        try:
            path = Path(tail) if tail.startswith("/") else (self.cwd or Path.cwd()) / tail
            return name if path.resolve() == here / name else None
        except OSError:
            return None

    def own(self, verb: str, args: list[str]) -> str | None:
        if verb == "publish":
            return ("this pack's `publish` is Approve outcome's, which Keel runs itself: a house never "
                    "runs it. Finish with `kb stage <card> review` and end your turn.")
        if "--ready" in args or any(DYN in word for word in args[1:]):
            return (f"marking a {self.fence.change()} ready is Approve outcome's, which Keel runs itself: this "
                    f"pack's `pr` is yours only as `{self.fence.ours()} --draft` or `--body`, written out in full.")
        if self.feeds is not None:
            # r1.F3: xargs adds words the guard never sees, `--ready` among them
            return (f"this pack's `pr` run through xargs cannot be read, since xargs adds words the guard never "
                    f"sees, so it is refused: run `{self.fence.ours()} --draft` or `--body`, written out in full.")
        return self.research(f"opens no {self.fence.change()}")

    def research(self, what: str) -> str | None:
        """Why a research card may not do this, or None; the card is read once, here."""
        if self.card is None:
            return None
        if self.kind is None:
            try:
                card = self.card()
            except CardUnread as error:
                return (f"the card could not be read ({error}), so this is held: a research card never "
                        f"pushes and {what}. Try again in a moment.")
            options = (card or {}).get("options") or {}
            # r1.F2: a review card as the kit calls one (`card.is_review`): its key, or its kind
            self.kind = "review" if options.get("review_key") else str(options.get("kind") or "work").lower()
        if self.kind == "research":
            return (f"this is a research card: it never commits, never pushes and {what}. Its "
                    f"outcome is its record.")
        if self.kind == "review":
            return (f"this is a review card: it reviews someone else's {self.fence.change()}, never pushes and "
                    f"{what}. Its outcome is the review the user posts.")
        return None

    # ----- git -----

    def git(self, args: list[str]) -> str | None:
        rest = list(args)
        while rest and rest[0].startswith("-"):
            flag = rest.pop(0)
            if flag == "-c" and rest and GIT_CONFIG_NEVER.match(rest[0]):
                return (f"`git -c {rest[0].split('=')[0]}` is refused: an alias, a push or credential setting "
                        f"or a remote's push refspec handed to git changes what a command does. {PLAIN_PUSH}")
            if flag in GIT_VALUED and rest:
                rest.pop(0)
        if self.feeds is not None and (not rest or any(mark in rest[0] for mark in self.feeds)):
            return GIT_FED
        if rest and DYN in rest[0]:
            return GIT_FILLED
        if not rest:
            return None
        if rest[0].startswith("credential-") or rest[0] == "credential":
            return self.fence.policy.sign_in.format(said=f"git {rest[0]}")
        return self.push(rest[1:]) if rest[0] == "push" else None

    def push(self, args: list[str]) -> str | None:
        positional, words = [], list(args)
        while words:
            word = words.pop(0)
            if word.startswith("--"):
                name = word[2:].split("=")[0]
                # git takes any unique start of a long flag (`--del`, `--forc`), and
                # `--force-with-lease` is a force too: matched as a prefix both ways
                if name and any(never.startswith(name) or name.startswith(never) for never in PUSH_NEVER):
                    return f"`git push {word}` is refused: no push is ever forced, deleted or aimed wide. {PLAIN_PUSH}"
                if word in PUSH_VALUED and words:
                    words.pop(0)
            elif word.startswith("-") and len(word) > 1:
                if word[1] == "o":
                    words = words[1:] if word == "-o" else words
                elif "f" in word or "d" in word:
                    return (f"`git push {word}` is refused: no push is ever forced or deleted "
                            f"(`--force`, `--delete`). {PLAIN_PUSH}")
            else:
                positional.append(word)
        refspecs = positional[1:]
        if len(refspecs) > 1:
            return f"`git push` of {len(refspecs)} names is refused: a house pushes one branch, its own. {PLAIN_PUSH}"
        for spec in refspecs:
            if DYN in spec:
                return f"`git push` of a name the shell builds cannot be read, so it is refused. {PLAIN_PUSH}"
            if any(mark in spec for mark in ":+*"):
                return (f"`git push {spec}` is refused: a `:`, `+` or `*` aims the push at another branch, "
                        f"forces it or deletes one. {PLAIN_PUSH}")
        return self.research(f"opens no {self.fence.change()}")


# ----- the verb -----

def problem(command: str, cwd=None, card=None, fence: Fence | None = None) -> str | None:
    """Why this command is refused to the card's house on `fence`'s pack, or None when it
    may run. `card` is called for the card only when a push or the pack's `pr` needs its kind."""
    try:
        return Judge(fence, cwd, card).line(command)
    except (Unreadable, RecursionError):
        return fence.policy.unread if fence.named.search(command) else None


def card_reader(card_id: str):
    """The card through `kb show`, with a short clock: this runs inside a hook."""
    def read() -> dict:
        home = Path(os.environ.get("KEEL_HOME") or KIT_ROOT)
        try:
            done = subprocess.run([str(home / "bin" / "kb"), "show", card_id, "--json", "--events", "0"],
                                  capture_output=True, text=True, timeout=KB_SECONDS)
            if done.returncode != 0:
                raise CardUnread((done.stderr.strip() or "kb show failed").splitlines()[-1][:160])
            return json.loads(done.stdout)
        except (OSError, subprocess.SubprocessError, ValueError) as error:
            raise CardUnread(f"{type(error).__name__}") from None
    return read


def main(argv: list[str], pack, policy: GuardPolicy) -> int:
    """`guard <id>`, the command and the house's cwd as JSON on stdin: `{"allow": true}` or
    `{"allow": false, "why": <one sentence>}`. Anything else (an error, no answer in time)
    the house guard reads as a guard that fell over (`bin/keel-house-guard` says what then)."""
    if len(argv) != 1:
        print("guard: usage: guard <card-id>", file=sys.stderr)
        return 1
    asked = json.load(sys.stdin)
    why = problem(str(asked.get("command") or ""), asked.get("cwd"), card_reader(argv[0]), Fence(pack, policy))
    print(json.dumps({"allow": True} if why is None else {"allow": False, "why": " ".join(why.split())}))
    return 0
