"""The builder's one fence: never edit a live checkout (`bin/keel-builder-guard`, PreToolUse).

Bosun builds in its own clones under `<install>/builder/` and its work reaches a live
checkout (the code Keel runs, KEEL_HOME, and every personal repo's checkout) only by the
user's Approve outcome. This hook refuses the one accident that is hard to undo, an edit in a
live checkout, in auto mode and in bypass alike (hooks run in both, ahead of the classifier),
with exit 2 and one line. Its arguments are the live checkouts (`builder.live_checkouts`).

- **The editing tools** (Edit, Write, MultiEdit, NotebookEdit): a target that resolves
  (`realpath`, every link in the existing part followed) inside a live checkout is refused.
  They fail closed: a call it cannot read is refused.
- **Bash**: a speed bump, not a wall (a shell can always say it another way; auto mode's
  `hard_deny` says the same in prose). Each command of the line is read with `shlex`,
  following `cd` and `git -C`: a git verb that changes a repo run in a live checkout, or a
  write (`rm`, `mv`, `cp`'s destination, `tee`, `touch`, `sed -i`, a `>` redirect, ...) to a
  path inside one, is refused. Reading there is fine. A line it cannot parse goes on.
"""

from __future__ import annotations

import json
import os
import shlex
import sys

EDIT_TOOLS = ("Edit", "Write", "MultiEdit", "NotebookEdit")
MATCHER = "|".join((*EDIT_TOOLS, "Bash"))
REFUSED = 2
# git verbs that change the repo they run in.
GIT_WRITES = frozenset(("add", "am", "apply", "checkout", "cherry-pick", "clean", "commit", "merge",
                        "mv", "pull", "push", "rebase", "reset", "restore", "revert", "rm", "stash",
                        "switch", "tag", "worktree", "update-ref", "update-index", "notes"))
BRANCH_WRITES = frozenset(("-d", "-D", "--delete", "-m", "-M", "--move", "-f", "--force",
                           "-c", "-C", "--copy", "-u", "--set-upstream-to", "--unset-upstream"))
# Commands that write every path they name, and the ones that write only their last.
WRITES_ALL = frozenset(("rm", "rmdir", "mv", "touch", "tee", "truncate", "chmod", "chown",
                        "mkdir", "unlink", "shred"))
WRITES_LAST = frozenset(("cp", "ln", "install", "rsync"))
INPLACE = frozenset(("sed", "perl", "gsed"))
SEPARATORS = frozenset((";", "&&", "||", "|", "&", "(", ")"))
REDIRECTS = frozenset((">", ">>", ">|", "&>", "&>>"))


def inside(path: str, roots: list[str]) -> bool:
    real = os.path.realpath(path)
    for root in roots:
        base = os.path.realpath(root)
        if real == base or real.startswith(base.rstrip(os.sep) + os.sep):
            return True
    return False


def absolute(path: str, cwd: str) -> str:
    path = os.path.expanduser(path)
    return path if os.path.isabs(path) else os.path.join(cwd, path)


def edit_target(payload: dict) -> str | None:
    given = payload.get("tool_input")
    if not isinstance(given, dict):
        return None
    path = given.get("file_path") or given.get("notebook_path")
    cwd = payload.get("cwd")
    if not isinstance(path, str) or not path:
        return None
    if not os.path.isabs(path) and not (isinstance(cwd, str) and os.path.isabs(cwd)):
        return None
    return absolute(path, cwd or "/")


def commands(line: str) -> list[list[str]]:
    """The line's commands, each a list of words, split on the shell's separators."""
    lexer = shlex.shlex(line, posix=True, punctuation_chars=";&|()<>")
    lexer.whitespace_split = True
    found, current = [], []
    for word in lexer:
        if word in SEPARATORS:
            if current:
                found.append(current)
            current = []
        else:
            current.append(word)
    return found + ([current] if current else [])


def git_write(words: list[str], cwd: str, roots: list[str]) -> str | None:
    where, rest = cwd, words[1:]
    while rest and rest[0].startswith("-"):
        flag = rest.pop(0)
        if flag == "-C" and rest:
            where = absolute(rest.pop(0), where)
        elif flag in ("--git-dir", "--work-tree", "-c") and rest:
            value = rest.pop(0)
            if flag != "-c":
                where = absolute(value, where)
        elif flag.startswith(("--git-dir=", "--work-tree=")):
            where = absolute(flag.split("=", 1)[1], where)
    if not rest or not inside(where, roots):
        return None
    verb = rest[0]
    if verb in GIT_WRITES or (verb == "branch" and BRANCH_WRITES & set(rest[1:])):
        return f"git {verb} in {where}"
    return None


def written(words: list[str], cwd: str) -> list[str]:
    """The paths one command writes, as far as its words say."""
    paths = []
    for index, word in enumerate(words[:-1]):
        if word in REDIRECTS:
            paths.append(words[index + 1])
    words = [word for index, word in enumerate(words)
             if word not in REDIRECTS and (index == 0 or words[index - 1] not in REDIRECTS)]
    if not words:
        return [absolute(path, cwd) for path in paths]
    name, args = os.path.basename(words[0]), [word for word in words[1:] if not word.startswith("-")]
    if name in WRITES_ALL:
        paths += args
    elif name in WRITES_LAST and args:
        paths.append(args[-1])
    elif name in INPLACE and any(word.startswith("-i") or word == "--in-place" for word in words[1:]):
        paths += args[1:]
    return [absolute(path, cwd) for path in paths]


def bash_verdict(line: str, cwd: str, roots: list[str]) -> str | None:
    try:
        parsed = commands(line)
    except ValueError:
        return None                     # a line it cannot read goes on: the classifier has it
    for words in parsed:
        if words[0] == "cd":
            cwd = absolute(words[1] if len(words) > 1 else "~", cwd)
            continue
        if os.path.basename(words[0]) == "git":
            what = git_write(words, cwd, roots)
            if what:
                return f"{what}: a live checkout is never edited; work in your clone under builder/"
        for path in written(words, cwd):
            if inside(path, roots):
                return f"{path} is in a live checkout, which is never edited; work in your clone"
    return None


def verdict(payload, roots: list[str]) -> str | None:
    """Why this call is refused, or None when it may go on."""
    if not isinstance(payload, dict) or not roots:
        return "the live checkout guard could not read the call, so it is refused"
    if payload.get("tool_name") == "Bash":
        given = payload.get("tool_input") or {}
        cwd = payload.get("cwd") if isinstance(payload.get("cwd"), str) else os.getcwd()
        return bash_verdict(str(given.get("command") or ""), cwd, roots)
    path = edit_target(payload)
    if path is None:
        return "the live checkout guard found no absolute target path, so the edit is refused"
    if inside(path, roots):
        return f"{path} is in a live checkout, which is never edited; work in your clone under builder/"
    return None


def main(argv=None) -> int:
    roots = list(sys.argv[1:] if argv is None else argv)
    try:
        why = verdict(json.loads(sys.stdin.read()), roots)
    except Exception as error:          # fail closed, whatever went wrong
        why = f"the live checkout guard failed ({type(error).__name__}), so the call is refused"
    if why is None:
        return 0
    print(why, file=sys.stderr)
    return REFUSED
