# CARRIED INTO KEEL WITH THE VOICE PACKAGE, 2026-09-17. verbs.py (the lookup tier, off since
# 2026-09-04 and slated for deletion in the voice plan's phase 5) imports this at module
# load, and the dispatcher imports verbs, so the gateway cannot start without it. It goes
# when verbs.py goes. Otherwise verbatim from the old tree.
"""The one place that decides how the morning queue is grouped, and what folds away.

UNDERSCORES IN THE NAME, unlike every other file in bin/, because this one is IMPORTED
rather than run. `import harbor_queue_fold` needs a legal module name and a dash is not
one. It is deliberately not executable: nothing invokes it directly.

WHY IT IS SHARED. The same rule has to hold in three places at once. view/server.py marks
entries so the dashboard can pin and fold them, view/index.html labels the drawer with the
same number of days, and `harbor-queue list` groups the same way at the desk. Three copies
of "7" is three chances for the phone and the terminal to disagree about what is actually
waiting, which is the exact confusion this change exists to remove. So the number and the
predicate live here once, the CLI and the server import them, and the page is TOLD the
number in its payload rather than carrying a second copy of it.

WHAT FOLDING IS, AND WHAT IT IS NOT. It is display only. Nothing here retires, resolves or
deletes an entry; a folded notice is one line further down the page and is otherwise
untouched, still resolvable, still in the file.
"""
import re
import subprocess
from datetime import datetime, timedelta, timezone

# How long a notice must sit UNCHANGED before it folds into the drawer. Both halves
# matter: an old notice whose wording moved yesterday is news, and a notice staged an
# hour ago is news whatever it says.
NOTICE_FOLD_DAYS = 7

# Sorts before every real timestamp, so an entry nobody can date lands at the far end of
# whichever order it is in rather than crashing the sort. It is never folded (see
# is_folded), so being undateable can only ever make an entry more visible.
_UNDATED = datetime.min.replace(tzinfo=timezone.utc)


def parse_stamp(stamp: str):
    """An ISO stamp as written by harbor-queue, or None if it cannot be read.

    A stamp with no offset is read as local time, which is what wrote it. Returning None
    rather than guessing is what lets every caller above choose to show an entry it cannot
    date instead of hiding it.
    """
    if not stamp:
        return None
    try:
        dt = datetime.fromisoformat(str(stamp))
    except (TypeError, ValueError):
        return None
    return dt.astimezone() if dt.tzinfo is None else dt


def first_seen(rec: dict) -> str:
    """When this subject FIRST appeared, not when the record was last rewritten.

    `at` is the fallback for entries staged before first_seen existed, and for anything
    staged by a caller that does not set it.
    """
    return str(rec.get("first_seen") or rec.get("at") or "")


def changed_at(rec: dict) -> str:
    """When its wording last actually moved. An entry that has never been updated in
    place has only ever said one thing, so that is its first appearance."""
    return str(rec.get("changed_at") or first_seen(rec))


def is_deferred(rec: dict, now: datetime | None = None) -> bool:
    """True while `harbor-queue defer` is deliberately holding this entry back.

    Set by `defer <n> [--until <at>]`, cleared by `wake <n>`. Distinct from `stale`
    (which relabels a wrong entry but keeps it visible) and from `is_folded` (which ages
    an unchanged NOTICE out of view): a defer is a decision the human already made --
    "I choose to wait" -- on an entry that is still `status: pending` the whole time, so
    `resolve`/`close`/`update`/`has` all keep working on it exactly as before. Only the
    two renderers (`harbor-queue list`, `unified/providers.py`) pull a deferred-and-
    still-active row out of the normal decide/desk/fyi view.

    READ-TIME ONLY, no watcher, no rewrite needed to come back: with `deferred_until` set,
    this simply reads False the moment `now` passes it -- the record never changes, the
    same "computed fresh from the stamps, never a second copy of state" posture
    `is_folded` already uses. With no `deferred_until` (an indefinite defer, "until the
    blocking condition clears"), this stays True until `wake` clears `deferred_at`.
    """
    if not rec.get("deferred_at"):
        return False
    until = parse_stamp(str(rec.get("deferred_until") or ""))
    if until is None:
        return True
    return (now or datetime.now(timezone.utc)) < until


# --------------------------------------------------------------------------- #
# THE SECTION, and it is derived, never declared (c-118).
#
# `kind` (review/authority/restart/approval/notice) is a SITUATION, a free-text label a
# caller picks when it stages an entry. It used to also be read as the SECTION a row
# renders under, and that conflation is exactly what let the same shape of by-hand work
# land in "approval" one morning and "authority" the next (queue entries staged
# 2026-09-11, `authority:harbor/20260911-022012` vs the c-115 CLAUDE.md merge), for no
# reason a person staging either one would have guessed.
#
# The section instead follows from what the entry actually carries:
#
#   decide      a button exists (--choice options, or --on-approve wires a runnable
#               command directly to the approve tap), OR the entry is --by-hand under a
#               decision kind with nothing to tap or run yet: a decision he still owes,
#               even before it has a button. `harbor-card open-gate` stages every plan
#               and outcome gate this way, on-approve or by-hand depending on whether
#               approving actuates something (c-226 wired the plan gate too, alongside
#               the outcome gate), and neither shape is a bug to refuse at staging time
#               -- see is_folded's own reasoning for why refusing it broke
#               bin/harbor-tend-selftest CASE 7.
#   desk        no button, but there is something to run by hand: a shell fence in
#               `why`/body (`commands()`), or a verified `--patch`.
#   fyi         neither, or `kind: notice`: nothing to tap, nothing to run, and the
#               caller said outright this is not a decision.
#
# `kind` keeps rendering as the coloured situation tag on a row; it no longer decides
# which of the three groups a DECISION falls into, but `kind: notice` alone still forces
# `fyi` outright, whatever the record's `why`/body/on_approve otherwise contain. Prose
# routinely quotes or illustrates a command without meaning it to run (harbor-reap's
# stale-worktree notice fences a per-tree EXAMPLE command with a literal `<path>` in
# it), and "the trip plan is ready to read"-shaped notices carry a `by_hand` reason that
# is not a decision either. Without this, either alone was enough to pull a genuine FYI
# into `desk`/`decide` and protect it from ever folding.
#
# THE FOURTH SECTION (c-229). `answers` is a `kind: notice` too (a voice answer is not a
# decision, nothing to tap or run) but it does not belong lumped in with the general FYI
# pile: it is an answer he is owed, staged because a voice turn ran past its own give-up
# mark and the real text had nowhere else honest to land (see
# bin/harbor_voice/harbormsg.py's `queue_answer`). Recognised the same narrow way every
# other `--kind notice`-only signal here is, off the entry's own `key` rather than a new
# field: every caller of `queue_answer` keys its entry `voice-answer-<turn id>`, and
# nothing else in this codebase writes that prefix.
SECTIONS = ("decide", "desk", "answers", "fyi")


def qsection(rec: dict, body: str = "") -> str:
    """`decide` / `desk` / `answers` / `fyi`, from what `rec` actually carries, not its
    `kind` alone.

    `kind: notice` IS STILL DECISIVE IN ONE DIRECTION: never desk, never decide, whatever
    its `why`/body happen to contain. `add` already refuses `--choice` on a notice ("a
    notice is not a decision"); this generalises that same rule to fences and
    `on_approve` too, because a notice is free-form prose and prose routinely quotes or
    illustrates a command without meaning it to run. Real example: bin/harbor-reap's
    stale-worktree notice fences `git -C ~/harbor worktree remove <path>` as a
    per-tree EXAMPLE (a literal `<path>` in it, never meant to be pasted as-is) inside
    text that is otherwise pure advisory; before this line, that alone was enough to
    pull a notice into `desk` and protect it from ever folding. Found by review.

    For anything that IS a decision (`kind != notice`), mirrors `commands()` recognising
    a bare or shell-tagged fence and `choices()`'s own malformed-drops-to-empty posture,
    so a hand-edited or pre-migration record still answers with SOMETHING sane rather
    than raising.
    """
    if (rec.get("kind") or "approval") == "notice":
        if str(rec.get("key") or "").startswith("voice-answer-"):
            return "answers"
        return "fyi"
    if choices(rec) or rec.get("on_approve"):
        return "decide"
    if commands(rec, body) or rec.get("patch_path"):
        return "desk"
    # kind != notice is already established above, so by_hand alone here is always a
    # real decision, never a genuine notice's own reason.
    if rec.get("by_hand"):
        return "decide"
    return "fyi"


def is_folded(rec: dict, now: datetime | None = None, body: str = "") -> bool:
    """Old AND unchanged, so it is background rather than news.

    NOTHING IN `decide` OR `desk` EVER FOLDS, at any age. It is a decision or a command
    the human owes and nothing else can make it; hiding one is the only way this whole
    change could do harm, so the refusal is the first line here rather than a condition
    further down. Keyed off `qsection()`, not the raw `kind` label: a `kind: notice`
    record that actually carries a command (see `qsection`'s own docstring) is desk
    work wearing a quiet label, and it does not fold either.
    """
    if qsection(rec, body) != "fyi":
        return False
    seen = parse_stamp(first_seen(rec))
    changed = parse_stamp(changed_at(rec))
    if seen is None or changed is None:
        return False                  # cannot date it, so do not quietly hide it
    cutoff = (now or datetime.now(timezone.utc)) - timedelta(days=NOTICE_FOLD_DAYS)
    return seen < cutoff and changed < cutoff


def partition(rows, now: datetime | None = None, body_of=None):
    """(decide+desk, fresh fyi, folded fyi), each in the order it should be read.

    decide+desk OLDEST first: one that has been owed a week is the most owed, and it
    belongs at the top of a section called "waiting on you". fyi NEWEST first: it is
    news and the freshest news is worth the top line. They are separate lists rather
    than one sorted list precisely so that no fyi row, however new, can ever sit above
    something the human still owes a decision or a command on.

    `body_of`, WHEN GIVEN, is called once per row (`body_of(rec) -> str`) so a command
    that lives only in a record's body (never in `why`) still reads as `desk`, not
    `fyi`: an entry staged with `--body-file` and no fence in `why` at all (the
    `authority card` shape this file's own selftest carries) went straight to a bare
    `qsection(rec)` here, missed its body-only fence, and fell to `fyi` even though
    `harbor-queue list`'s own decide/desk split (which DOES read the body) would have
    called it `desk`. Optional, and defaulting to reading nothing, because most rows
    have no body at all and a caller with no ledger to read one from (nearly every
    existing caller of `is_folded`/`partition` in this file's own selftest) must keep
    working exactly as it did.
    """
    now = now or datetime.now(timezone.utc)
    owed, fresh, folded = [], [], []
    for rec in rows:
        body = body_of(rec) if body_of else ""
        if qsection(rec, body) != "fyi":
            owed.append(rec)
        elif is_folded(rec, now, body):
            folded.append(rec)
        else:
            fresh.append(rec)
    seen_key = lambda r: parse_stamp(first_seen(r)) or _UNDATED   # noqa: E731
    owed.sort(key=seen_key)
    fresh.sort(key=seen_key, reverse=True)
    folded.sort(key=seen_key, reverse=True)
    return owed, fresh, folded


# --------------------------------------------------------------------------- #
# THE SUMMARY LINE, and where it comes from.
#
# A row shows one line under its title saying what the entry is ABOUT. Before this,
# the dashboard rendered the whole of `why` on every card: for the 23 gate notices
# waiting on 2026-08-30 that was the same 128 characters twenty-three times, and for
# an approval it was up to 3,500 characters of unbroken grey text.
#
# The writer supplies it (`harbor-queue add --summary`), because the session staging
# the card is the only thing that knows the one sentence that matters. Everything
# already on disk, and any session that forgets, falls back to the opening of `why`,
# so nothing has to be migrated and no entry ever renders blank.
#
# HERE rather than in the page, for the same reason the fold rule is here: `harbor-queue
# list` at the desk and the dashboard on the phone have to answer "what is this about"
# with the same words, or the two surfaces disagree about the same entry.
# --------------------------------------------------------------------------- #

# A first sentence shorter than this is not a summary, it is a fragment. Entry #776's
# `why` opens "1 comments." and the sentence that carries the meaning is the second one,
# so the derivation keeps taking sentences until it has enough to read as a line.
SUMMARY_MIN = 60
SUMMARY_MAX = 200

# `--why` IS ONE PARAGRAPH (c-185): `bin/harbor-queue add`/`update` refuse a `--why` over
# this many characters with no `--body`/`--body-file` to carry the detail. KEPT IN SYNC BY
# HAND with the bash `WHY_MAX_CHARS` near the top of `bin/harbor-queue`, which cannot
# import this module -- the number is small and stable enough that duplicating it once is
# cheaper than shelling out to python on every add/update just to read a constant.
WHY_MAX_CHARS = 700

# A fenced block, the way a session is asked to write a command it wants run by hand.
# Non-greedy and anchored per line, so several fences in one `why` come out separately
# and prose between them is never swallowed. Group 1 is the info string, group 2 the body.
_FENCE = re.compile(r"^[ \t]*```([^\n]*)\n(.*?)\n?^[ \t]*```[ \t]*$", re.S | re.M)

# WHICH FENCES ARE COMMANDS. Everything used to be, because `why` only ever carried one
# kind of fence and nothing else was allowed in it. A markdown BODY is a document: an
# `authority` card carries its diff in a ```diff fence and its commands in a bare one, and
# offering the diff as something to paste into a shell would be worse than offering
# nothing. So a bare fence is still a command, exactly as before, and a tagged one is a
# command only if the tag says shell.
_SHELL_FENCE = {"", "sh", "bash", "zsh", "shell", "console", "command", "terminal"}

# What `harbor-queue add --by-hand` appends to `why`. It is a reason, not a subject, and
# it is always last, so the summary stops before it rather than quoting it.
_BY_HAND_TAIL = re.compile(r"\s*NEEDS YOUR HAND:.*$", re.S)

# A sentence end: . ! ? or : followed by whitespace. The colon earns its place because
# these are written by agents, and "WHY BY HAND: two commands, at the desk" is a
# sentence boundary in every practical case here.
_SENTENCE = re.compile(r"[.!?:](?=\s|$)")


def without_fences(why: str) -> str:
    """`why` with its fenced blocks taken out, for a reader that renders them separately.

    A fence in `why` is a command, and a surface that shows commands as their own block
    must not also print the raw ``` and the command text in the middle of a paragraph.
    Same reason `summary()` strips them: a command is not prose.
    """
    return " ".join(_FENCE.sub(" ", str(why or "")).split())


def without_by_hand(why: str) -> str:
    """`why` with the "NEEDS YOUR HAND:" tail removed.

    `harbor-queue add --by-hand` appends the reason to `why` so that every reader gets it,
    including the ones that only ever knew about `why`. A reader that shows `by_hand` as
    its own field would then print the same sentence twice on one screen, which is what
    the card detail did before this existed.
    """
    return _BY_HAND_TAIL.sub("", str(why or "")).strip()


def body_text(rec: dict, ledger) -> str:
    """The entry's markdown body, or "" when it has none or it cannot be read.

    `body_path` is relative to ledger/ so a home that moved, or a fixture pointed at some
    other ledger, still resolves. A body that is gone reads as absent rather than raising:
    the row and its summary are still worth showing, and `harbor-queue body` is the thing
    that says out loud which file it wanted.
    """
    rel = str(rec.get("body_path") or "")
    if not rel:
        return ""
    try:
        from pathlib import Path
        return (Path(ledger) / rel).read_text(encoding="utf-8", errors="replace")
    except OSError:
        return ""


def commands(rec: dict, body: str = "") -> list[str]:
    """Every SHELL fence in `why` and then in the body, in order, as text to paste.

    This is the ONLY thing treated as a command. `by_hand` is a reason ("the queue can
    only run scripts under harbor/bin"), never a command, and guessing at indented lines
    was rejected because a wrongly extracted command is worse than none.

    The body is passed in rather than read here so that this module stays a pure rule and
    every caller reads the file once. `harbor-queue list` at the desk and the dashboard on
    a phone both call this with the same body, which is the whole reason the rule lives in
    one place.
    """
    out = []
    for text in (str(rec.get("why") or ""), str(body or "")):
        for m in _FENCE.finditer(text):
            if (m.group(1) or "").strip().lower() not in _SHELL_FENCE:
                continue
            block = m.group(2).strip()
            # DEDUPLICATED, IN ORDER. A card written before this surface could read a body
            # sensibly puts its commands in BOTH: `why` so the dashboard running on the
            # old code still offers them, the body so the new detail renders them under
            # the heading that says what they are for. Listing the same command twice is
            # never useful and reads as two steps.
            if block and block not in out:
                out.append(block)
    return out


def choices(rec: dict) -> list[dict]:
    """The entry's tap-able options, or [] when it has none or they are malformed.

    `harbor-queue add --choice` is the only writer and it never stores a shape other
    than {id, label, effect, recommended, run}, but this is read by two renderers
    (`harbor-queue list` at the desk, the dashboard on a phone) and a record hand-edited
    or written by something else must not crash either of them. So this drops anything
    that is not a well-formed list of well-formed options rather than raising, the same
    posture `body_text` takes on a body_path that no longer resolves.

    `run` (c-205) is OPTIONAL, unlike id/label/effect: every choice written before this
    field existed has none, and that must keep reading as "no command", not as
    malformed. A present-but-wrong-typed `run` drops the whole record, same as a bad
    id/label/effect -- a half-trusted command is worse than none.
    """
    raw = rec.get("choices")
    if not isinstance(raw, list) or len(raw) < 2:
        return []
    out = []
    for c in raw:
        if not isinstance(c, dict):
            return []
        cid, label, effect = c.get("id"), c.get("label"), c.get("effect")
        if not (isinstance(cid, str) and cid and isinstance(label, str) and label
                and isinstance(effect, str) and effect):
            return []
        run = c.get("run", "")
        if not isinstance(run, str):
            return []
        out.append({"id": cid, "label": label, "effect": effect,
                    "recommended": bool(c.get("recommended")), "run": run})
    if sum(1 for c in out if c["recommended"]) != 1:
        return []
    return out


def _clip(text: str) -> str:
    """At most SUMMARY_MAX characters, cut on a word boundary."""
    text = text.strip()
    if len(text) <= SUMMARY_MAX:
        return text
    cut = text[:SUMMARY_MAX]
    space = cut.rfind(" ")
    return (cut[:space] if space > SUMMARY_MAX // 2 else cut).rstrip(" ,;:") + "…"


def summary(rec: dict) -> str:
    """The one line a row shows under its title, or "" when it would add nothing.

    Returns "" rather than repeating `what`: a row that says the same thing twice is
    worse than a row with two lines, and some entries genuinely have nothing to add.
    """
    supplied = str(rec.get("summary") or "").strip()
    if supplied:
        return _clip(" ".join(supplied.split()))

    why = _FENCE.sub(" ", str(rec.get("why") or ""))   # a command is not a summary
    why = _BY_HAND_TAIL.sub("", why)
    why = " ".join(why.split())
    if not why:
        return ""

    # Sentences until it reads as a line, so a "1 comments." opener does not become the
    # whole summary.
    out = ""
    for m in _SENTENCE.finditer(why):
        out = why[: m.end()]
        if len(out) >= SUMMARY_MIN:
            break
    else:
        out = out or why
    if len(out) < SUMMARY_MIN:
        out = why

    # A trailing colon is a sentence end here but reads as a truncation, since whatever
    # it introduced is not in the line.
    out = _clip(out).rstrip(":;, ")
    what = " ".join(str(rec.get("what") or "").split())
    if out and what and (out == what or what.startswith(out.rstrip("…"))):
        return ""
    return out


def split_why(text: str, cap: int = WHY_MAX_CHARS) -> tuple[str, str | None]:
    """A row-sized `--why` lead, and the full `text` as a body when it runs past `cap`.

    For a caller whose `--why` is arbitrary-length freeform text rather than its own
    hand-authored prose (`harbor-card verify`'s `--text`, `harbor-return`'s `--note`):
    `bin/harbor-queue add` refuses a `--why` over `cap` with no `--body`, and this is
    what keeps such a caller under that cap without truncating anything, by putting the
    WHOLE text in the body and only a sentence-bounded lead in `--why`. Cut on a
    sentence boundary, not a character count, for the same reason `summary()` is: a
    slice mid-sentence reads as broken, which is exactly what c-185's evidence (entry
    1507) looked like.
    """
    if len(text) <= cap:
        return text, None
    lead = ""
    for m in _SENTENCE.finditer(text):
        candidate = text[: m.end()]
        if len(candidate) >= SUMMARY_MIN:
            lead = candidate
            break
    if not lead or len(lead) > cap:
        lead = _clip(text[: cap + 1])
    return lead.strip(), text


# --------------------------------------------------------------------------- #
# A BY-HAND ENTRY THAT EDITS A FILE MUST CARRY THE FILE, NOT A DESCRIPTION OF IT.
#
# card by-hand:c-101-promote-review-state was staged with three careful paragraphs of
# prose pointing at a markdown file, and one fenced command that only `cat`s that file.
# It was approved while `git status --short bin/harbor-promote` was still empty, and
# nothing said so. `--patch` on `harbor-queue add` exists so a by-hand entry that edits a
# file carries the actual diff, verified to apply, rather than a description a person has
# to translate back into an edit by hand.
# --------------------------------------------------------------------------- #

# THE SAME SHAPE AS A SESSION SCRATCHPAD, because it is one. A plan_ref into /tmp or a
# session's own scratchpad dies with the worktree that wrote it (the c-097 finding); a
# patch path has the identical failure mode, so it is refused for the identical reason.
# /var/folders is macOS's own `mktemp -d` default, which is where this machine's session
# scratchpads actually live (see /private/tmp/claude-501/... in a session's own env), so
# it is named explicitly rather than assumed to be covered by /tmp. BOTH forms of each
# are listed: /var on macOS is itself a symlink to /private/var, so `realpath` resolves
# "/var/folders/..." to "/private/var/folders/...", and checking only the pre-symlink
# spelling would silently stop matching the exact path this check runs realpath for.
_SCRATCH_PREFIXES = ("/tmp/", "/private/tmp/", "/var/folders/", "/private/var/folders/")


def scratch_reason(path: str) -> str | None:
    """Why `path` is not a durable place to keep a patch, or None if it is fine.

    Checked on the REALPATH, not the string as written, because /tmp is a symlink to
    /private/tmp on this machine and a caller writing "/tmp/x" must not slip past a
    prefix check that only ever saw "/private/tmp/x".
    """
    import os
    try:
        real = os.path.realpath(path)
    except OSError:
        real = path
    tmpdir = os.environ.get("TMPDIR", "")
    if tmpdir:
        real_tmpdir = os.path.realpath(tmpdir)
        if real == real_tmpdir.rstrip("/") or real.startswith(real_tmpdir.rstrip("/") + "/"):
            return f"{path} is under $TMPDIR ({tmpdir}), which does not survive this session"
    for prefix in _SCRATCH_PREFIXES:
        if real.startswith(prefix):
            return f"{path} resolves under {prefix}, a scratch directory that does not survive this session"
    return None


# A patch names its targets in its own header, so asking the caller to repeat them
# separately is one more place they could drift from the file actually stored. Matches
# `git diff`'s own two header shapes: `diff --git a/X b/Y` (present on every hunk `git
# diff`/`git format-patch` emits) and the plain `--- a/X` / `+++ b/X` pair (present even
# on a hand-written patch with no `diff --git` line at all, e.g. one made with `diff -u`).
_DIFF_GIT = re.compile(r"^diff --git a/(.+?) b/(.+)$", re.M)
# STOPS AT A TAB (c-167). A plain `diff -u` header (unlike `diff --git`'s) carries a
# tab-and-timestamp suffix after the path (`+++ b/X.md\t2026-09-13 02:27:38 -0700`), and
# `(.+)$` used to swallow it into the captured target, corrupting every path this
# fallback names on exactly the patches it exists to handle (git format-patch/diff never
# hits this branch at all, since it always emits `diff --git`). A path legitimately
# containing a tab is not a case either branch here has ever handled.
_PLUS_HEADER = re.compile(r"^\+\+\+ b/([^\t\n]+)", re.M)


def parse_patch_targets(text: str) -> list[str]:
    """The files a unified diff touches, in the order they first appear.

    Prefers `diff --git`'s own pair (a real target even for a rename, where `+++` and
    `---` name different paths); falls back to `+++ b/X` for a patch with no `diff --git`
    line. `/dev/null` is a deletion's `+++` side and names nothing to apply commands to.
    """
    out: list[str] = []
    for a, b in _DIFF_GIT.findall(text):
        for p in (b, a):
            if p and p not in out:
                out.append(p)
    if out:
        return out
    for p in _PLUS_HEADER.findall(text):
        if p and p != "dev/null" and p not in out:
            out.append(p)
    return out


# --------------------------------------------------------------------------- #
# THE ESCAPE HATCH (c-205): "if the user doesn't agree with any of these, he can come
# to the session chat to discuss further" -- his words, on a choice-shaped decision.
#
# A queue entry's `ref` names a card, and a card carries its dispatch's pane
# (`bin/harbor-attach <ref>` already resolves either a live dispatch or a finished
# card's own recorded tmux/session fields to a phone Remote-Control URL and a local
# `tmux attach` command). This is the ONE place that resolution happens for the
# QUEUE'S OWN renderers, imported by both `harbor-queue list` (the desk) and
# `unified/providers.py` (the phone), so the two surfaces cannot point him at two
# different panes for the same entry.
#
# NOT PURE, unlike everything else in this module: it shells out. Documented here
# rather than hidden, the same posture `add`'s lazy `require_shquote` import takes for
# a dependency only one caller needs -- most of this module never touches a subprocess,
# this one function does because duplicating harbor-attach's dispatch/card resolution
# logic a second time in pure Python would be a second place for it to drift from the
# first.
# --------------------------------------------------------------------------- #

def escape_hatch(ref: str, bindir: str, timeout: float = 3.0) -> dict | None:
    """Where to reach a live conversation about `ref`, or None when there is no ref.

    Always a dict, never raises: `harbor-attach --json` itself always exits 0 and
    always prints one JSON object, `ok: false` (with a `reason`) rather than a
    non-zero exit or stderr prose, precisely so this never has to guess at malformed
    output. The one thing this adds on top is turning "the subprocess itself could not
    be run or its output could not be parsed" (missing binary, a timeout, a corrupted
    write) into the SAME `{"ok": false, "reason": ...}` shape, so a caller renders one
    "no live session" sentence regardless of which of these actually happened.
    """
    import json
    import os
    ref = (ref or "").strip()
    if not ref:
        return None
    try:
        p = subprocess.run([os.path.join(bindir, "harbor-attach"), "--json", ref],
                           capture_output=True, text=True, timeout=timeout)
        return json.loads(p.stdout)
    except Exception:                                          # noqa: BLE001
        return {"ok": False, "ref": ref, "phone": None, "phone_note": None,
                "tmux": None, "tmux_note": None,
                "reason": "could not resolve a session for this entry"}


def find_duplicate(rows: list[dict], ref: str, kind: str, targets: list[str]):
    """(tier, row) for the pending entry this one would duplicate, or None.

    AN OBVIOUS RULE, NOT A SCORE. Two tiers, because "duplicate" and "worth flagging" are
    different confidences and deserve different treatment (merge vs. name-and-still-add):

      strong  another PENDING entry shares this one's non-empty `ref` AND `kind`. A
              second entry against the same card doing the same kind of thing is the
              same subject restated, which is exactly the shape `update` already exists
              to fold into one card instead of a growing pile.
      weak    another PENDING entry's own `patch_targets` overlaps this one's, but ref or
              kind differ (or one side is missing a ref). Two different reasons to touch
              the same file are common and not always the same subject, so this is named
              rather than merged.

    `rows` should already be filtered to pending; passing the raw file is harmless (a
    non-pending row simply never matches) but wasteful for a large queue.
    """
    ref = (ref or "").strip()
    targets = set(targets or [])
    for r in rows:
        if r.get("status", "pending") != "pending":
            continue
        r_ref = (r.get("ref") or "").strip()
        if ref and r_ref and ref == r_ref and (r.get("kind") or "approval") == (kind or "approval"):
            return ("strong", r)
    if targets:
        for r in rows:
            if r.get("status", "pending") != "pending":
                continue
            r_targets = set(r.get("patch_targets") or [])
            if r_targets & targets:
                return ("weak", r)
    return None
