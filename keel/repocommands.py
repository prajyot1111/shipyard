"""A repo's commands, as Keel uses them (c-678): what its adopted CLAUDE.md says, put to work.

`keel/repofile.py` reads four lines out of the file Bosun drafts and the user adopts. This
module is what Keel does with three of them (the fourth, how to run the app, is
`run_rule`, which the brief and the browser tool ask):

- **The test command** (`tests_of`): `[tests]` in the config where it names the repo, since
  an install that wrote one meant it; else the file's "Run the tests" line. A landing
  builds the merged tree and runs it there (`keel/merging.py`), and a house runs it before
  review (`keel/house.py`). A repo with neither lands untested, and `untested` is the
  sentence that says so on the card.
- **The prepare command** (`prepare_of`, `prepare`): the file's "Prepare a fresh copy"
  line. It runs when a card's worktree is cut (`keel/adapters.py`), so a session starts in
  a copy that can run the tests, and in the landing's merged tree before the tests. A
  prepare that fails refuses the cut and the worktree is taken back out, so the next try
  prepares again; in a landing it lands nothing.
- **Where work lands** (`lands_of`, `lands_said`): the file's "Finished work lands on" line
  is RETIRED (c-734). Until then an Adopt put the branch it named out in Keel's copy
  (`apply_lands`, c-678), so the copy's checkout decided where cards landed beside c-732's
  card bases: two sources, and the second stranger run's copy sat on staging after an Adopt.
  Now nothing is checked out by adopting or saving a file; a card lands on its own base, else
  the repo's usual branch (`merging.usual_branch`: the remote's default for a copy), and
  `lands_said` is the sentence the page adds when an adopted file still names a branch.

Both commands run through a shell in the repo's own tree, with the environment a test
suite gets (`childenv.own_env`): they are the user's own lines, adopted by the user's tap.
That is checked, not assumed (review F3): `lines` hands out a file's lines only while the
file is the text the user last adopted or saved there (`keel/tierrecord.py`). A file that
was edited since, by any hand, reads as having no line at all, and `changed` is the one
sentence that says so: on the card when its worktree is cut, and in the house's brief.

THE RULE FOR A FILE THAT CHANGED, stated here once and asked everywhere through `landing`
(c-678 fix check, r2.D1 and r2.D2):

1. A repo file that was adopted or saved and then changed turns off ITS OWN lines, and
   nothing else.
2. Where the config's `[tests]` names the test command for the repo, that command is used
   exactly as it was before this card, at the before-review run and at the landing,
   whatever the file's standing. Nothing is refused.
3. A landing is refused only when the test command would have come from the file (the
   config names none) and the file's record no longer matches. Reading that file as "no
   test command" would fail open: a session could edit it and its card would merge
   untested. Keel cannot know what to test, so it lands nothing and says what to do. It is
   asked of the record, never of what the file names now, so a file with its test line
   taken out, or emptied, is refused too.
4. That refusal, and the brief's "do not report a pass", exist only where Keel lands the
   work itself: a space with no pack. In a space on a pack nothing about the pack's own
   flow changes.

"Lands untested" is left for a file with no record at all and for a held file that names
no test line. `landing` answers the test command and the refusal from ONE reading of the
file, so a file cannot read changed for one and held for the other.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

from keel import childenv, repofile, repolayout, tierrecord
from keel.config import remote_of

PREPARE_SECONDS = 900
SAID_LINES = 8


class PrepareFailed(Exception):
    """The prepare command failed or ran out of time; the message says how."""


class PrepareTimedOut(PrepareFailed):
    """It ran past its time and was stopped, with every process it started."""


def first(key: str | None) -> str:
    return str(key or "").split(",")[0].strip()


# Two sentences, chosen by whether a record exists (`tierrecord.stands`): a file that was
# never adopted or saved did not change since anything.
CHANGED = "{name}'s CLAUDE.md changed since it was adopted or saved"
NEVER = "{name}'s CLAUDE.md has not been adopted or saved yet"
# Where the file is adopted or saved again, named, since the sentence is read on a card and
# the card has no Save of its own (review r2.F12)
WHERE = "(Setup, the {name} repo's file)"
CUT = {tierrecord.CHANGED: CHANGED + ", so Shipyard runs none of its lines: adopt or save it again " + WHERE + ".",
       tierrecord.NEVER: NEVER + ", so Shipyard runs none of its lines: save it to turn them on " + WHERE + "."}
LANDS = {tierrecord.CHANGED: CHANGED + " and none of its lines run until it is adopted or saved again " + WHERE,
         tierrecord.NEVER: NEVER + " and none of its lines run until it is " + WHERE}
# What refuses, and what to do, in order: the file first, then the card (r2.D4)
FROM_FILE = CHANGED + ", and Shipyard takes this repo's test command from that file"
REFUSED = (FROM_FILE + ", so nothing was landed. First adopt or save the file again " + WHERE
           + ". Then press Unblock and land on this card.")
NOT_PUSHED = FROM_FILE + ", so nothing was merged or pushed. Adopt or save the file again " + WHERE + ", then push."
WILL_REFUSE = FROM_FILE + ", so Approve will not land this. Adopt or save the file again " + WHERE + "."
NO_PASS = " No test run of this card counts until then: do not report a pass."


def reading(cfg, space: str | None, key: str | None, board=None) -> tuple[str | None, dict]:
    """`(standing, lines)` of the repo's file, from one read of it (`tierrecord.read`): how it
    stands against what the user adopted or saved, and what that same text names. `(None,
    nothing)` off the layout."""
    tier = repofile.tier_of(cfg, space, key)
    if tier is None:
        return None, dict(repofile.NOTHING)
    how, text = tierrecord.read(cfg, tier, board)
    return how, repofile.parse(text or "")


def lines(cfg, space: str | None, key: str | None, board=None) -> dict:
    """What the repo's file says, while the file is the text the user last adopted or saved;
    all None for any other text, and off the layout."""
    how, found = reading(cfg, space, key, board)
    return found if how == tierrecord.HELD else dict(repofile.NOTHING)


def lands_here(cfg, space: str | None) -> bool:
    """Whether Keel lands this space's work itself: a space with no pack."""
    found = (getattr(cfg, "spaces", None) or {}).get(space or "")
    return found is not None and getattr(found, "adapter_dir", None) is None


def landing(cfg, space: str | None, key: str | None, board=None) -> tuple[str | None, bool]:
    """`(test command, refused)` for a landing of this repo, from ONE reading of its file:
    the rule in this module's docstring. The config's command, as it always was; else the
    held file's line; else none, and `refused` where that is because the file changed and
    Keel lands the space's work itself."""
    configured = cfg.repo_tests.get(first(key))
    if configured:
        return configured, False
    how, found = reading(cfg, space, key, board)
    if how == tierrecord.CHANGED:
        return None, lands_here(cfg, space)
    line = found.get("test") if how == tierrecord.HELD else None
    return (line["value"] if line else None), False


def refusal(cfg, space: str | None, key: str | None, board=None) -> str | None:
    """Why a landing of this repo must not go, or None (`landing`)."""
    return REFUSED.format(name=first(key)) if landing(cfg, space, key, board)[1] else None


def will_refuse(cfg, space: str | None, key: str | None, board=None) -> str | None:
    """`refusal`, as the card says it before the tap."""
    return WILL_REFUSE.format(name=first(key)) if landing(cfg, space, key, board)[1] else None


def changed(cfg, space: str | None, key: str | None, board=None) -> str | None:
    """The sentence for a file whose lines do not run: changed since its record (whatever it
    names now), or never recorded while it names a line. None for a held file, for one that
    was never recorded and names nothing (the template), and off the layout."""
    how, found = reading(cfg, space, key, board)
    if how == tierrecord.CHANGED or (how == tierrecord.NEVER and any(found.values())):
        return CUT[how].format(name=first(key))
    return None


def value(cfg, space: str | None, key: str | None, name: str, board=None) -> str | None:
    found = lines(cfg, space, key, board).get(name)
    return found["value"] if found else None


def tests_of(cfg, space: str | None, key: str | None, board=None) -> str | None:
    """The command a landing runs on the merged tree: the config's, else the adopted file's."""
    return landing(cfg, space, key, board)[0]


def prepare_of(cfg, space: str | None, key: str | None, board=None) -> str | None:
    return value(cfg, space, key, "prepare", board)


def lands_of(cfg, space: str | None, key: str | None, board=None) -> str | None:
    return value(cfg, space, key, "lands", board)


def run_rule(cfg, space: str | None, key: str | None, board=None) -> str | None:
    """How to run the repo's app, or None: sessions run tests only until the file says."""
    return value(cfg, space, key, "run", board)


def runs(cfg, space: str | None, key: str | None, board=None) -> bool | None:
    """Whether a repo's file says how to run its app: None for a repo the install did not
    copy (it has no file, and no rule to meet), else whether `run_rule` names a command.
    The board asks this before a card may take the browser (`Board._refuse_browser`)."""
    if repofile.tier_of(cfg, space, key) is None:
        return None
    return run_rule(cfg, space, key, board) is not None


def untested(cfg, space: str | None, key: str | None, board=None) -> str | None:
    """Why a landing of this repo runs no tests, or None when it runs some."""
    if tests_of(cfg, space, key, board):
        return None
    name = first(key) or "its repo"
    if repofile.tier_of(cfg, space, key) is None:
        return f"{name} has no test command"
    how, found = reading(cfg, space, key, board)
    if how == tierrecord.CHANGED or (how == tierrecord.NEVER and any(found.values())):
        return LANDS[how].format(name=name)
    return f"{name}'s CLAUDE.md has no Run the tests line"


def prepare(command: str, tree: Path, seconds: float = PREPARE_SECONDS) -> None:
    """Run the prepare command in `tree`; `PrepareFailed` with its last lines when it fails.

    It runs as the suite does (`merging.run_tests`, review F5): in a process group of its
    own, and one that runs past `seconds` is ended as a group (`merging.kill_suite`), so an
    installer it started is not left running with the pipes open (`PrepareTimedOut`)."""
    from keel import merging     # noqa: PLC0415 - merging reads this module
    try:
        proc = subprocess.Popen(command, shell=True, cwd=str(tree), stdout=subprocess.PIPE,
                                stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL, text=True,
                                errors="replace", start_new_session=True, env=childenv.own_env())
    except OSError as error:
        raise PrepareFailed(f"`{command}` could not run: {error}") from None
    try:
        out, _ = proc.communicate(timeout=seconds)
    except subprocess.TimeoutExpired:
        merging.kill_suite(proc)
        raise PrepareTimedOut(f"`{command}` did not finish in {int(seconds)}s") from None
    if proc.returncode != 0:
        tail = "\n".join((out or "").strip().splitlines()[-SAID_LINES:])
        raise PrepareFailed(f"`{command}` exited {proc.returncode}" + (f":\n{tail}" if tail else ""))


LANDS_RETIRED = "its \"Finished work lands on `{named}`\" line moves nothing: a card on {key} {lands}"
# r1.F7: where a card naming no base really lands, said as it is
LANDS_INTEGRATION = "lands on {branch}, its integration branch, and takes no base"
LANDS_DEFAULT = ("lands on its own base, else on {branch}, the branch {remote} names as its default. "
                 "To start work from {named}, add it as a base on How work ships")
LANDS_CHECKOUT = ("lands on its own base, else on {branch}, the branch the copy has out. To start work "
                  "from {named}, add it as a base on How work ships")


def lands_said(cfg, space: str, key: str, board=None) -> str | None:
    """The sentence for an adopted or saved file that names a branch to land on (c-734): the
    line is retired, and nothing is checked out. Where work lands has one source: the repo's
    integration branch where it has one, else the card's own base, else the repo's usual
    branch (`merging.usual_branch`: the remote's default, else the copy's checkout), and the
    sentence names whichever applies (r1.F7). Until c-734 an Adopt put the named branch out in
    Keel's copy (`apply_lands`, c-678), which made the copy's checkout a second source. None
    when the file names no branch, or the repo is not one the install copied."""
    from keel import merging     # noqa: PLC0415 - merging reads this module
    named = lands_of(cfg, space, key, board)
    tier = repofile.tier_of(cfg, space, key)
    if not named or tier is None:
        return None
    remote, repo = remote_of(cfg, space), tier.parent / repolayout.REPO
    integration = cfg.integration_of(space, key)
    if integration:
        return LANDS_RETIRED.format(named=named, key=key, lands=LANDS_INTEGRATION.format(branch=integration))
    try:
        default = merging.remote_default(repo, remote)
        branch = default or merging.trunk_of(repo)
    except (merging.MergeRefused, OSError):
        default, branch = None, "its usual branch"
    lands = (LANDS_DEFAULT if default else LANDS_CHECKOUT).format(branch=branch, remote=remote, named=named)
    return LANDS_RETIRED.format(named=named, key=key, lands=lands)
