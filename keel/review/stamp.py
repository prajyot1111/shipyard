"""The harness's record of a review: written by the `SubagentStop` hook, never by the house.

Review finding 6 (lane E): a file the house writes proves only that the house wrote a file.
So the two agents' answers are taken where the harness hands them over: a `SubagentStop`
hook whose matcher is the agent's name (`bin/keel-review-stamp`) reads the payload's
`last_assistant_message` (probed 2026-09-23 on 2.1.280: the payload carries `agent_type`,
`cwd`, `session_id` and `last_assistant_message`), and records it:

- **The reviewer finishes**: its findings, in the schema, become a new pass in
  `review-findings.json` with the heads, patch ids and bases per worktree root as the
  newest prep saw them (c-581), the session and the base. An answer outside the schema is a pass that counts for nothing.
- **The verifier finishes**: its verdicts are applied to the newest pass by the rules
  (`findings.apply_verdicts`), and the pass is complete.
- **A pass is complete** when it has no findings or the verifier has been through them;
  then `review-stamp.json` names the heads reviewed, one per worktree, and which suite the house ran there
  (`testrun`, c-544: targeted or full, or none recorded at that head). `review.md` is rendered from the JSON
  on every write (`findings.render`), with the house's answers (`review-answers.json`).

The house's editing tools are denied the stamp and the findings file. Its Bash is not, and
nothing running as the same user can be made truly unforgeable, which is what decision E-9
records he accepted in turning the gate on.
"""

from __future__ import annotations

import json
import re
import sys
from datetime import datetime
from pathlib import Path

from keel import settings
from keel.config import Config
from keel.review import agents, findings, repo, risk, testrun

STAMP_FILE = "review-stamp.json"
FINDINGS_FILE = "review-findings.json"
ANSWERS_FILE = "review-answers.json"
REVIEW_FILE = "review.md"
DIFF_FILE = "review.diff"
PREP_FILE = "review-prep.json"
SINCE_FILE = "review-since.diff"
# RD-1 (2026-09-25): one full review per gate trip; fixes get a fix check by the verifier.
# Only a fixed high or critical finding earns a second full review, until the trip has had
# FULL_ROUNDS_MAX of them. The size of the fixes no longer does (2026-09-26, his call: c-530
# ran 14 review passes on 24 findings with no high, its second full pass earned by line count).
# It is the default: a space may name its own (`[spaces.<name>] review_full_rounds`, c-597:
# 1 at work, where a fixed high or critical finding is confirmed by the fix check), and
# `[keel] review_full_rounds` is every other space's (c-633). This is that setting's default.
FULL_ROUNDS_MAX = settings.default("keel", "review_full_rounds")
STAMP_SCRIPT = "keel-review-stamp"
PEER_FLAG = "--peer"
# Bosun's own hook (the builder, c-619): no card on its command line, found per review.
BOSUN_FLAG = "--bosun"
# The card's space's full passes per trip, on the hook's command line from launch (c-597).
FULL_MAX_FLAG = "--full-max"
EDIT_TOOLS = ("Edit", "Write", "MultiEdit", "NotebookEdit")
SAID_MAX = 4000


def now() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


def stamp_path(cfg: Config, card_id: str) -> Path:
    return cfg.cards_dir / card_id / STAMP_FILE


def stamp_deny(cfg: Config, card_id: str) -> list[str]:
    """The editing tools denied the harness's two files (double slash: anchored at root)."""
    card_dir = cfg.cards_dir / card_id
    return [f"{tool}(/{card_dir / name})" for name in (STAMP_FILE, FINDINGS_FILE)
            for tool in EDIT_TOOLS]


def read_json(path: Path, default):
    try:
        return json.loads(Path(path).read_text())
    except (OSError, ValueError):
        return default


def read_stamp(cfg: Config, card_id: str) -> dict:
    return read_json(stamp_path(cfg, card_id), {})


def read_rounds(card_dir: Path) -> list[dict]:
    rounds = read_json(Path(card_dir) / FINDINGS_FILE, {}).get("rounds")
    return rounds if isinstance(rounds, list) else []


def read_answers(card_dir: Path) -> dict:
    answers = read_json(Path(card_dir) / ANSWERS_FILE, {})
    return answers if isinstance(answers, dict) else {}


def render(card_dir: Path, rounds: list[dict] | None = None) -> None:
    rounds = read_rounds(card_dir) if rounds is None else rounds
    text = findings.render(rounds, read_answers(card_dir)) + tests_line(card_dir)
    (Path(card_dir) / REVIEW_FILE).write_text(text)


def tests_line(card_dir: Path) -> str:
    """The stamp's record of the house's own test run, for review.md (c-544)."""
    stamped = read_json(Path(card_dir) / STAMP_FILE, {})
    if not stamped.get("head"):
        return ""
    return (f"\nThe house's tests at the stamped HEAD {str(stamped['head'])[:12]}: "
            f"{testrun.said(stamped.get('tests'))}.\n")


def save_rounds(card_dir: Path, rounds: list[dict]) -> None:
    card_dir = Path(card_dir)
    card_dir.mkdir(parents=True, exist_ok=True)
    (card_dir / FINDINGS_FILE).write_text(json.dumps({"rounds": rounds}, indent=2) + "\n")
    render(card_dir, rounds)


def heads_of(stamped: dict, roots: list[str] | None = None) -> dict[str, dict]:
    """What a pass or the stamp reviewed, by worktree root: `{root: {head, patch_id, base,
    base_sha}}`
    (c-581). An old record with one `head` and no `heads` (or an empty one, from a pass
    opened before c-581 and closed after it) reads as covering its one repo: the worktree
    among `roots` that has that commit, else the only one."""
    if not stamped:
        return {}
    heads = stamped.get("heads")
    if isinstance(heads, dict) and heads:
        ids, bases = stamped.get("patch_ids") or {}, stamped.get("bases") or {}
        shas = stamped.get("base_shas") or {}
        return {root: {"head": head, "patch_id": ids.get(root), "base": bases.get(root) or stamped.get("base"),
                       "base_sha": shas.get(root)}
                for root, head in heads.items()}
    head = stamped.get("head")
    if not head:
        return {}
    roots = list(roots or [])
    home = next((root for root in roots if repo.resolves(root, head)), None)
    home = home or (roots[0] if len(roots) == 1 else None)
    return {home: {"head": head, "patch_id": stamped.get("patch_id"), "base": stamped.get("base")}} if home else {}


def prepared_heads(card_dir: Path, cwd, head: str) -> dict:
    """The heads the newest prep saw, by root (`heads`, `patch_ids`, `bases`, `base_shas`), and `head`,
    the house's own worktree's among them. An old prep file with no heads gives the cwd's."""
    prepped = read_json(Path(card_dir) / PREP_FILE, {})
    seen = [one for one in prepped.get("worktrees") or [] if one.get("root") and one.get("head")]
    own = repo.root_key(cwd)
    if not seen:
        base = prepped.get("base")
        return {"head": head, "heads": {own: head} if own else {},
                "patch_ids": {own: repo.patch_id(cwd, repo.base_ref(cwd, base))} if own else {},
                "bases": {own: base} if own else {}, "base_shas": {}}
    heads = {one["root"]: one["head"] for one in seen}
    return {"head": heads.get(own) or head, "heads": heads,
            "patch_ids": {one["root"]: one.get("patch_id") for one in seen},
            "bases": {one["root"]: one.get("base") or prepped.get("base") for one in seen},
            "base_shas": {one["root"]: one["base_sha"] for one in seen if one.get("base_sha")}}


def touched_of(card_dir: Path) -> dict:
    try:
        return risk.touched((Path(card_dir) / DIFF_FILE).read_text(errors="replace"))
    except OSError:
        return risk.touched("")


# ----- the two agents finishing -----

def reviewed(card_dir: Path, payload: dict, head: str) -> dict:
    """A new pass from the reviewer's answer, with the heads the prep it read saw."""
    rounds = read_rounds(card_dir)
    said = str(payload.get("last_assistant_message") or "")
    base = read_json(Path(card_dir) / PREP_FILE, {}).get("base")
    heads = prepared_heads(card_dir, payload.get("cwd"), head)
    own = repo.root_key(payload.get("cwd"))
    entry = {"round": len(rounds) + 1, "session_id": payload.get("session_id"),
             "at": now(), "base": base, "said": said[:SAID_MAX], **heads,
             "patch_id": heads["patch_ids"].get(own)}
    raws = findings.parse_answer(said)
    if raws is None:
        entry.update(unparsed=True, findings=[], complete=False)
    else:
        found = findings.normalise_all(raws, entry["round"])
        entry.update(findings=found, complete=not found,
                     risk=risk.score(found, touched_of(card_dir)))
    save_rounds(card_dir, rounds + [entry])
    return entry


def verified(card_dir: Path, payload: dict) -> dict | None:
    """The newest pass after the verifier: None when there is no pass of this session
    for it to verify."""
    rounds = read_rounds(card_dir)
    if not rounds or rounds[-1].get("unparsed") or rounds[-1].get("session_id") != payload.get("session_id"):
        return None
    entry = dict(rounds[-1])
    verdicts = findings.parse_answer(str(payload.get("last_assistant_message") or "")) or []
    entry["findings"] = findings.apply_verdicts(entry.get("findings") or [], verdicts)
    entry.update(complete=True, verified_at=now(),
                 risk=risk.score(entry["findings"], touched_of(card_dir)))
    save_rounds(card_dir, rounds[:-1] + [entry])
    return entry


def delta_lines(card_dir: Path) -> int:
    """The changed lines of the delta the house prepared (`prep --since`)."""
    try:
        text = (Path(card_dir) / SINCE_FILE).read_text(errors="replace")
    except OSError:
        return 0
    return sum(1 for line in text.splitlines()
               if line[:1] in "+-" and not line.startswith(("+++", "---")))


def earned_why(cause: str) -> str:
    """The refusal of a fix check that earned a full review, naming the next step (c-529:
    c-522's house read "a full review is earned" and asked for another delta, six times).
    No trip count in it: the Stop hook repeats it later, when the count may have moved."""
    return (f"a full review is earned ({cause}): no fix check can move the stamp now, however "
            f"many fixes follow. Commit, run the same full `keel-review prep` your brief names "
            f"(every --worktree, --worktree-base or --member it lists) WITHOUT --since, and call ONLY "
            f"{agents.REVIEWER}, then {agents.VERIFIER} on its findings.")


def newest_delta(card_dir: Path) -> dict | None:
    """The newest fix check of the newest closed pass, or None when there is none, or
    when a newer pass has started since (the house already ran the reviewer it named)."""
    rounds = read_rounds(card_dir)
    done = [i for i, entry in enumerate(rounds) if entry.get("complete") and not entry.get("unparsed")]
    if not done or done[-1] != len(rounds) - 1:
        return None
    deltas = rounds[done[-1]].get("deltas") or []
    return deltas[-1] if deltas else None


def open_round(card_dir: Path) -> dict | None:
    """The newest pass when it is not complete: the house has started a review it must finish."""
    rounds = read_rounds(card_dir)
    return rounds[-1] if rounds and not rounds[-1].get("complete") else None


def block_loop(board, card_id: str, why: str) -> None:
    """A second earned refusal at one full-round count: the house is looping, so the card is
    blocked with the step it keeps missing (`review-limit`, which wakes Bosun on a card he
    drives). Never on a card already blocked, and never fatal: a hook does not fail the house."""
    if board is None:
        return
    try:
        if not board.get(card_id).get("blocked_reason"):
            board.block(card_id, f"a second fix check was refused at the same full-round count: "
                                 f"{why}", "hook", mark=LIMIT_MARK)
    except Exception as error:  # noqa: BLE001
        print(f"keel-review-stamp: {error}", file=sys.stderr)


LIMIT_MARK = "review-limit"


def clear_limit(board, card_id: str) -> None:
    """The stamp is written, so the review step a `review-limit` block asked for is done: clear
    that block (r-16, c-538: c-524 read blocked while building for minutes after its earned
    full review ran). Only when the card's newest block carries that mark AND the card is
    still blocked with its words (`expect`), so his block, a house's own question or any
    later one is never cleared. Never fatal: a hook does not fail the house."""
    if board is None:
        return
    from keel.board import MARKS      # noqa: PLC0415 - only the hook's process needs it
    try:
        reason = board.get(card_id).get("blocked_reason")
        if not reason:
            return
        blocks = [e for e in board.events(card_id, last=0) if e.get("kind") == "block"]
        newest = blocks[-1] if blocks else {}
        if newest.get("data") == MARKS[LIMIT_MARK] and newest.get("text") == reason:
            board.unblock(card_id, "hook", expect=reason)
    except Exception as error:  # noqa: BLE001
        print(f"keel-review-stamp: {error}", file=sys.stderr)


def full_rounds_max(cfg: Config, space_name: str | None) -> int:
    """The full review passes a trip may have in this space: its `review_full_rounds`, else
    `[keel] review_full_rounds` (c-597, c-633)."""
    space = cfg.spaces.get(space_name) if space_name else None
    named = getattr(space, "review_full_rounds", None)
    return int(named) if named else int(getattr(cfg, "review_full_rounds", None) or FULL_ROUNDS_MAX)


def delta_checked(card_dir: Path, payload: dict, head: str, since: str, trip_rounds: int,
                  full_max: int = FULL_ROUNDS_MAX) -> dict | None:
    """The verifier's FIX CHECK (RD-1): the newest pass's fixes, confirmed on the change
    since the heads it reviewed. Only ever on the newest pass, and only when it is closed
    (c-581: on c-272 a fix check landed on an older pass while a newer one was open).
    Recorded on that pass as a `deltas` entry; the answer `{"ok", "head", ...}` says whether
    the stamp may move to the heads the `prep --since` saw. A low or medium regression it
    names is added to the pass as a finding to answer (`r<N>.D<k>`)."""
    rounds = read_rounds(card_dir)
    if not rounds or not rounds[-1].get("complete") or rounds[-1].get("unparsed"):
        return None
    index = len(rounds) - 1
    entry = dict(rounds[index])
    items = findings.parse_answer(str(payload.get("last_assistant_message") or "")) or []
    answers = read_answers(card_dir)
    fixed_ids = {fid for fid, said in answers.items() if (said or {}).get("did") == "fixed"}
    by_id = {one["id"]: one for one in entry.get("findings") or []}
    not_fixed = [str(item.get("id")) for item in items
                 if not item.get("regression") and item.get("fixed") is False]
    regressions = [item for item in items if item.get("regression")]
    serious_regression = any(str(item.get("severity")) in findings.NEVER_DROPPED for item in regressions)
    serious_fixed = any(str((by_id.get(fid) or {}).get("severity")) in findings.NEVER_DROPPED for fid in fixed_ids)
    lines = delta_lines(card_dir)       # recorded for the record; it earns nothing now
    # Once earned at this count, it stays earned: a smaller delta from a newer --since does
    # not undo it (c-529). A record from before the count was kept never counts.
    before = any(one.get("earned") and one.get("full_rounds") == trip_rounds
                 for one in entry.get("deltas") or [])
    cause = ("a high or critical finding was fixed" if serious_fixed
             else "an earlier fix check of this pass already earned it" if before else "")
    earned = bool(cause) and trip_rounds < full_max
    why = (earned_why(cause) if earned
           else "not fixed: " + ", ".join(not_fixed) if not_fixed
           else "a high or critical regression" if serious_regression else "fixed")
    repeat = earned and before
    ok = not (earned or not_fixed or serious_regression)
    added = []
    for item in regressions:
        if str(item.get("severity")) in findings.NEVER_DROPPED:
            continue
        number = sum(1 for one in entry.get("findings") or [] if ".D" in str(one.get("id"))) + len(added) + 1
        added.append({"id": f"r{entry['round']}.D{number}", "axis": "standards",
                      "severity": str(item.get("severity") or "low"), "path": item.get("path"),
                      "line": item.get("line"), "claim": str(item.get("claim") or ""),
                      "evidence": str(item.get("evidence") or ""), "suggestion": str(item.get("suggestion") or ""),
                      "verify": "kept", "reason": "a regression the fix check found"})
    entry["findings"] = list(entry.get("findings") or []) + added
    record = {"from": since, "to": head, "at": now(), "lines": lines, "ok": ok, "why": why,
              "not_fixed": not_fixed, "regressions": len(regressions), "earned": earned,
              "full_rounds": trip_rounds, "repeat": repeat}
    entry["deltas"] = list(entry.get("deltas") or []) + [record]
    rounds[index] = entry
    save_rounds(card_dir, rounds)
    heads = prepared_heads(card_dir, payload.get("cwd"), head)
    return dict(record, **heads, round=entry["round"], base=entry.get("base"),
                session_id=payload.get("session_id"),
                patch_id=heads["patch_ids"].get(repo.root_key(payload.get("cwd"))))


HANDBACK = "SubagentHandback"


def agent_transcript(payload: dict) -> Path | None:
    """The agent's own transcript: `agent_transcript_path` when the harness names it, else
    where it keeps it, `<session transcript without .jsonl>/subagents/agent-<agent_id>.jsonl`
    (seen on 2026-09-26, c-521)."""
    named = payload.get("agent_transcript_path")
    if named:
        return Path(named)
    session, agent_id = payload.get("transcript_path"), payload.get("agent_id")
    if not session or not agent_id:
        return None
    return Path(session).with_suffix("") / "subagents" / f"agent-{agent_id}.jsonl"


def handbacks(path: Path | None) -> list[str]:
    """What the agent handed back through `SubagentHandback`, oldest first."""
    if path is None:
        return []
    said = []
    try:
        lines = path.read_text(errors="replace").splitlines()
    except OSError:
        return []
    for line in lines:
        try:
            row = json.loads(line)
        except ValueError:
            continue
        content = (row.get("message") or {}).get("content")
        for part in content if isinstance(content, list) else []:
            if (isinstance(part, dict) and part.get("type") == "tool_use"
                    and part.get("name") == HANDBACK):
                said.append(str((part.get("input") or {}).get("message") or ""))
    return said


def with_answer(payload: dict) -> dict:
    """The payload with the agent's ANSWER as `last_assistant_message` (c-525).

    An agent may hand its answer back through `SubagentHandback` and then end with a prose
    summary, so its last message carries no schema and the pass counted for nothing.
    When the last message has no answer, the newest handback that does is taken instead."""
    if findings.parse_answer(str(payload.get("last_assistant_message") or "")) is not None:
        return payload
    for said in reversed(handbacks(agent_transcript(payload))):
        if findings.parse_answer(said) is not None:
            return {**payload, "last_assistant_message": said, "answer_from": HANDBACK}
    return payload


def write_stamp(cfg: Config, card_id: str, entry: dict, payload: dict) -> Path:
    path = stamp_path(cfg, card_id)
    path.write_text(json.dumps({
        "head": entry["head"], "session_id": entry.get("session_id"), "round": entry["round"],
        "base": entry.get("base"), "patch_id": entry.get("patch_id"),
        "heads": entry.get("heads") or {}, "patch_ids": entry.get("patch_ids") or {},
        "bases": entry.get("bases") or {}, "base_shas": entry.get("base_shas") or {},
        "delta": bool(entry.get("to")), "agent_id": payload.get("agent_id"), "at": now(),
        "tests": testrun.at_head(payload.get("cwd"), entry["head"]),
        "said": str(payload.get("last_assistant_message") or "")[:SAID_MAX]}, indent=2) + "\n")
    return path


def stamp(cfg: Config, card_id: str, payload: dict, peer: bool = False,
          trip_rounds: int | None = None, board=None, full_max: int = FULL_ROUNDS_MAX) -> Path | None:
    """The hook body: record what one of Keel's agents answered; the stamp's path when the
    pass is closed, else None. In PEER mode (a review card, lane RC) the pass is
    recorded the same way and the stamp is never written: a peer review reads a
    colleague's branch, and nothing it does may mark that branch reviewed (HP-8). `board`
    is where a looping fix check is blocked (c-529); None blocks nothing. `full_max` is the
    card's space's limit on full passes per trip (c-597)."""
    agent = payload.get("agent_type")
    if agent not in (agents.REVIEWER, agents.VERIFIER):
        return None
    if payload.get("hook_event_name", "SubagentStop") != "SubagentStop":
        return None
    head = repo.head_of(payload.get("cwd"))
    if head is None:
        return None
    payload = with_answer(payload)
    card_dir = cfg.cards_dir / card_id
    since = read_json(card_dir / PREP_FILE, {}).get("since")
    rounds = read_rounds(card_dir)
    closed = bool(rounds) and bool(rounds[-1].get("complete"))
    if agent == agents.VERIFIER and since and closed and not peer:
        # RD-1: the newest pass is closed and the house prepared a delta (`prep --since`),
        # so this verifier checks fixes. While the newest pass is open, the verifier is
        # verifying THAT pass, whatever prep wrote since (c-581, r-28 item 3).
        done = delta_checked(card_dir, payload, head, since, trip_rounds if trip_rounds is not None else 0,
                             full_max)
        if done and done["repeat"]:
            block_loop(board, card_id, done["why"])
        if not (done and done["ok"]):
            return None
        entry = done
    else:
        entry = reviewed(card_dir, payload, head) if agent == agents.REVIEWER else verified(card_dir, payload)
        if peer or not entry or not entry.get("complete"):
            return None
    path = write_stamp(cfg, card_id, entry, payload)
    render(card_dir)
    clear_limit(board, card_id)
    return path


def stamp_main(argv: list[str] | None = None) -> int:
    """`keel-review-stamp <card> [--peer] [--full-max N]`, or `keel-review-stamp --bosun`: the
    SubagentStop hook. Always exits 0: a hook that fails must not hold a house up. `--peer` is
    a review card's (never stamped); `--full-max` is the card's space's full passes per trip,
    written at launch; `--bosun` is the builder's, whose card is found per review
    (`bosun_review`)."""
    from keel import config as config_module      # the hook's own process loads the config
    argv = list(sys.argv[1:] if argv is None else argv)
    peer = PEER_FLAG in argv
    bosun = BOSUN_FLAG in argv
    argv = [arg for arg in argv if arg not in (PEER_FLAG, BOSUN_FLAG)]
    argv, named_max = without_full_max(argv)
    try:
        payload = json.loads(sys.stdin.read() or "{}")
        if (argv or bosun) and isinstance(payload, dict):
            cfg = config_module.load()
            board = open_board_or_none(cfg)
            try:
                card_id = argv[0] if argv else None
                if bosun:
                    card_id, payload = bosun_review(cfg, payload, board)
                if card_id:
                    stamp(cfg, card_id, payload, peer=peer,
                          trip_rounds=trip_full_rounds(cfg, card_id, board), board=board,
                          full_max=named_max or full_rounds_max(cfg, space_of(card_id, board)))
            finally:
                if board is not None:
                    board.close()
    except Exception as error:  # noqa: BLE001
        print(f"keel-review-stamp: {error}", file=sys.stderr)
    return 0


def bosun_review(cfg: Config, payload: dict, board) -> tuple[str | None, dict]:
    """The card a review by Bosun is for, and the payload as a house's would read. Its session
    runs in `<install>/builder` (no checkout, no card of its own), so the card is the ONE
    card directory the agent's prompt names (`<cards_dir>/<id>/`, the diff or the findings
    it was handed), only a card the builder builds, and the payload's `cwd` becomes the
    worktree its prep read. `(None, payload)` when any of that does not hold: no stamp."""
    from keel import builder     # noqa: PLC0415 - only Bosun's hook needs it
    ids = sorted(set(re.findall(re.escape(str(cfg.cards_dir)) + r"/([A-Za-z0-9_-]+)/",
                                first_prompt(agent_transcript(payload)))))
    if len(ids) != 1 or board is None:
        if len(ids) > 1:
            print(f"keel-review-stamp: the prompt names {', '.join(ids)}; a review is of one card",
                  file=sys.stderr)
        return None, payload
    card = board.get(ids[0])
    if builder.clone_for(cfg, card) is None:
        print(f"keel-review-stamp: {ids[0]} is not a card the builder builds", file=sys.stderr)
        return None, payload
    seen = [one for one in read_json(cfg.cards_dir / ids[0] / PREP_FILE, {}).get("worktrees") or []
            if one.get("path")]
    if not seen:
        print(f"keel-review-stamp: {ids[0]} has no prep to read a head from; run prep first",
              file=sys.stderr)
        return None, payload
    return ids[0], dict(payload, cwd=seen[0]["path"])


def first_prompt(path: Path | None) -> str:
    """The text of the first user message in an agent's transcript: the prompt it was given."""
    if path is None:
        return ""
    try:
        lines = path.read_text(errors="replace").splitlines()
    except OSError:
        return ""
    for line in lines:
        try:
            row = json.loads(line)
        except ValueError:
            continue
        message = row.get("message") if isinstance(row, dict) else None
        if not isinstance(message, dict) or message.get("role") != "user":
            continue
        content = message.get("content")
        if isinstance(content, str):
            return content
        return "\n".join(str(part.get("text") or "") for part in content or []
                         if isinstance(part, dict) and part.get("type") == "text")
    return ""


def without_full_max(argv: list[str]) -> tuple[list[str], int | None]:
    """The arguments without `--full-max N`, and N (None when absent or not a number of 1
    or more: the space is then read from the board)."""
    if FULL_MAX_FLAG not in argv:
        return argv, None
    at = argv.index(FULL_MAX_FLAG)
    value = argv[at + 1] if at + 1 < len(argv) else ""
    rest = argv[:at] + argv[at + 2:]
    return rest, int(value) if value.isdigit() and int(value) >= 1 else None


def space_of(card_id: str, board) -> str | None:
    """The card's space, or None when the board cannot say (the default limit then holds)."""
    try:
        return board.get(card_id).get("space") if board is not None else None
    except Exception:  # noqa: BLE001 - a hook never fails the house
        return None


def open_board_or_none(cfg: Config):
    """This machine's board for the hook, or None when it cannot be opened."""
    try:
        from keel.board import open_board
        return open_board(cfg)
    except Exception:  # noqa: BLE001 - a hook never fails the house
        return None


def trip_full_rounds(cfg: Config, card_id: str, board=None) -> int:
    """The complete full-review passes of this gate trip: since the card last moved to
    building for any reason but the Stop hook's own send-back (a hook bounce is the same
    trip). 0 when the board cannot be read: the fix check then asks for what it earns."""
    if board is None:
        return 0
    try:
        events = board.events(card_id, last=0)
    except Exception:  # noqa: BLE001 - a hook never fails the house
        return 0
    starts = [e["at"] for e in events if e.get("kind") == "stage" and e.get("actor") != "hook"
              and (e.get("data") or {}).get("to") == "building"]
    since = starts[-1] if starts else ""
    return sum(1 for entry in read_rounds(cfg.cards_dir / card_id)
               if entry.get("complete") and not entry.get("unparsed") and str(entry.get("at") or "") >= since[:19])
