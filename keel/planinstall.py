"""`bin/keel-plan-install`: put a converted plan and outcome on a real card (P4-9).

A card already at a gate when the plan pages ship has a lavish `plan.html` and a markdown
`context.md`. Converting them to the plan format is a house's job, done on a scratch deck;
this puts the result on the real card, the way a house would have if it had written the
format in the first place:

1. Every board the documents embed is either PUSHED from a line file (`--board
   b-003=flow-1.txt`, one `keel board push --card <id> --new` each, so it lands on the
   card's own store and is listed under the card) or REUSED from the boards the card already
   has (`--reuse b-001=b-006`, or an id the documents already spell that the card has).
2. The documents' board ids are rewritten to the ids the store answered, and their
   frontmatter `card:` (and a title heading led by the old id) to the real card.
3. Nothing is pushed until the documents lint clean with the planned ids counted as
   resolved, and after the pushes `kb lint` runs on the rewritten files, as a stage would.
4. The old files are KEPT beside the new ones, renamed (`plan.html.lavish`,
   `context.md.pre-format`), never deleted; the card's `plan_ref` names the new plan; and
   one note on the card says what was done.

It runs where the card's files are (the Mac, for a work card), through `kb` and `keel
board`, so a board elsewhere is reached over HTTP exactly as a house reaches it. `--dry-run`
prints every step and changes nothing.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
from pathlib import Path

from keel import artifacts, boards, config as config_module, planformat, plangate, planlint

ROOT = Path(__file__).resolve().parent.parent
FENCE = re.compile(r"^(?P<ticks>`{3,}|~{3,})\s*board\b")
REF_LINE = re.compile(r"^(?P<lead>\s*)(?:board\s+)?b-(?P<n>\d+)\s*$")
LAVISH_SUFFIX, PRE_FORMAT_SUFFIX = ".lavish", ".pre-format"


def suffix_of(old: Path) -> str:
    """A lavish page is kept as `.lavish`; any other old file as `.pre-format`."""
    return LAVISH_SUFFIX if old.suffix.lower() in (".html", ".htm") else PRE_FORMAT_SUFFIX


class InstallError(Exception):
    """A refusal, said in one line; nothing after it ran."""


# ----- the verbs this runs, as a house would run them -----

class Verbs:
    """`kb` and `keel board` by absolute path, with the caller's environment (a board
    elsewhere is reached over HTTP by the verbs themselves)."""

    def __init__(self, root: Path = ROOT, env: dict | None = None):
        self.kb, self.keel = root / "bin" / "kb", root / "bin" / "keel"
        self.env = dict(env if env is not None else os.environ)
        self.env.pop("KEEL_CARD", None)          # this is him, not a house

    def run(self, argv: list, check: bool = True, cwd: str | None = None) -> subprocess.CompletedProcess:
        done = subprocess.run([str(a) for a in argv], capture_output=True, text=True,
                              env=self.env, timeout=120, cwd=cwd)
        if check and done.returncode != 0:
            said = (done.stderr or done.stdout).strip().splitlines()
            raise InstallError(said[-1] if said else f"{argv[0]} exited {done.returncode}")
        return done

    def card(self, card_id: str) -> dict:
        return json.loads(self.run([self.kb, "show", card_id, "--json"]).stdout)

    def boards_of(self, card_id: str) -> list[str]:
        return [row["id"] for row in json.loads(
            self.run([self.keel, "board", "list", "--card", card_id, "--json"]).stdout)]

    def board_exists(self, ref: str) -> bool:
        return self.run([self.keel, "board", "show", ref], check=False).returncode == 0

    def push_new(self, card_id: str, path: Path, cwd: str | None = None) -> list[str]:
        """Pushed from the card's worktree (`cwd`), where a house pushes from: a `path` op
        reads its file relative to where the push runs."""
        result = json.loads(self.run([self.keel, "board", "push", "--card", card_id, "--new",
                                      "--file", Path(path).resolve(), "--json"], cwd=cwd).stdout)
        return list(result.get("boards") or [result["board"]])

    def lint(self, card_id: str, path: Path, outcome: bool, root: str | None) -> subprocess.CompletedProcess:
        argv = [self.kb, "lint", card_id, "--file", path]
        if root:
            argv += ["--root", root]
        return self.run(argv, check=False)

    def set_plan(self, card_id: str, path: Path) -> None:
        self.run([self.kb, "set", card_id, f"plan_ref={path}"])

    def note(self, card_id: str, text: str) -> None:
        self.run([self.kb, "note", card_id, text])


# ----- the documents -----

def embedded(text: str) -> list[str]:
    """The board ids a document embeds, in order, each once, as the store spells them."""
    doc = planformat.parse(text)
    out = []
    for block in planformat.all_blocks(doc["blocks"]):
        if block["type"] == "board" and block.get("ref") and block["ref"] not in out:
            out.append(block["ref"])
    return out


def norm(ref: str) -> str:
    match = re.fullmatch(r"b-(\d+)", ref.strip())
    if not match:
        raise InstallError(f"not a board id: {ref!r}")
    return f"b-{int(match.group(1)):03d}"


def rewrite(text: str, ids: dict, old_card: str | None, card_id: str) -> str:
    """The document with every embedded board id mapped, and its card named."""
    out, inside = [], None
    for line in text.split("\n"):
        if inside is None:
            opened = FENCE.match(line.strip())
            if opened:
                inside = opened["ticks"]
        elif line.strip() == inside:
            inside = None
        else:
            ref = REF_LINE.match(line)
            if ref:
                line = ref["lead"] + ids.get(f"b-{int(ref['n']):03d}", f"b-{int(ref['n']):03d}")
        out.append(line)
    text = "\n".join(out)
    return renamed(text, old_card, card_id)


def renamed(text: str, old_card: str | None, card_id: str) -> str:
    """Frontmatter `card:` and a `# <old id> ...` title heading, moved to the real card."""
    if not old_card or old_card == card_id:
        return re.sub(r"(?m)^card:.*$", f"card: {card_id}", text, count=1) if text.startswith("---") else text
    text = re.sub(r"(?m)^card:\s*" + re.escape(old_card) + r"\s*$", f"card: {card_id}", text, count=1)
    return re.sub(r"(?m)^# " + re.escape(old_card) + r"\b", f"# {card_id}", text, count=1)


def board_lines(path: Path) -> int:
    """How many `board` lines a line file has: one file is one board here."""
    count = 0
    for raw in path.read_text(errors="replace").splitlines():
        try:
            op = boards.parse_line(raw)
        except boards.BadLine:
            continue
        if op and op.get("op") == "board" and op.get("mode") != "rename":
            count += 1
    return count


# ----- the plan of work -----

def plan_work(args, verbs: Verbs) -> dict:
    """Everything decided before anything is changed: which ids push, which reuse, where
    each file goes. Refuses with one line when an input does not add up."""
    card = verbs.card(args.card)
    docs = {}
    for doc, given in (("plan", args.plan), ("outcome", args.context)):
        if given:
            path = Path(given).expanduser()
            if not path.is_file():
                raise InstallError(f"no {doc} file at {path}")
            text = path.read_text(errors="replace")
            if not text.startswith("---"):
                raise InstallError(f"{path} is not in the plan format (no frontmatter)")
            docs[doc] = {"source": path, "text": text}
    if not docs:
        raise InstallError("nothing to install: give --plan and/or --context")
    pushes = {norm(a): Path(b).expanduser() for a, b in pairs(args.board, "--board")}
    reuses = {norm(a): norm(b) for a, b in pairs(args.reuse, "--reuse")}
    have = verbs.boards_of(args.card)
    for ref, path in pushes.items():
        if not path.is_file():
            raise InstallError(f"no line file for {ref} at {path}")
        if board_lines(path) > 1:
            raise InstallError(f"{path} would draw more than one board; one file is one board here")
    for ref, target in reuses.items():
        if target not in have:
            raise InstallError(f"{target} is not one of {args.card}'s boards ({', '.join(have) or 'none'})")
    for doc in docs.values():
        for ref in embedded(doc["text"]):
            if ref not in pushes and ref not in reuses and ref not in have:
                raise InstallError(f"{ref} is embedded but not given: --board {ref}=<file> or "
                                   f"--reuse {ref}=<one of {args.card}'s boards>")
    card_dir = Path(args.card_dir).expanduser() if args.card_dir else card_dir_of(args.card)
    return {"card": card, "docs": docs, "pushes": pushes, "reuses": reuses, "have": have,
            "card_dir": card_dir, "root": args.root or (card.get("options") or {}).get("worktree")}


def pairs(values, flag: str) -> list[tuple[str, str]]:
    out = []
    for value in values or []:
        left, sep, right = value.partition("=")
        if not sep or not left or not right:
            raise InstallError(f"{flag} takes <id>=<value>, got {value!r}")
        out.append((left, right))
    return out


def card_dir_of(card_id: str) -> Path:
    return config_module.load(ensure=False).card_dir(card_id)


def prelint(work: dict, verbs: Verbs) -> list[str]:
    """Every error the documents would be refused for, with the ids still to push counted
    as resolved, before anything is pushed."""
    planned = set(work["pushes"]) | set(work["reuses"])

    def board_of(ref: str) -> str | None:
        if ref in planned or ref in work["have"] or verbs.board_exists(ref):
            return None
        return "no such board"

    errors = []
    for doc, entry in work["docs"].items():
        scratch = work["card_dir"] / f".install-{doc}.md"
        scratch.parent.mkdir(parents=True, exist_ok=True)
        scratch.write_text(entry["text"])
        try:
            result = plangate.lint_file(scratch, work["card"], root=work["root"],
                                        events=work["card"].get("events"), board_of=board_of,
                                        role=planlint.PLAN if doc == "plan" else planlint.RECORD)
        finally:
            scratch.unlink(missing_ok=True)
        errors += [f"{doc}: {f['rule']} {f['text']}" for f in result["findings"] if f["level"] == "error"]
    return errors


def target_of(work: dict, doc: str) -> Path:
    return work["card_dir"] / ("plan.md" if doc == "plan" else "context.md")


def old_of(work: dict, doc: str) -> Path | None:
    """The file the new one replaces, which is kept under a new name."""
    if doc == "outcome":
        path = work["card_dir"] / "context.md"
        return path if path.is_file() else None
    ref = work["card"].get("plan_ref") or ""
    path = (artifacts.local_path(ref, config_module.repo_root())
            if ref and not ref.startswith("http") else None)
    if path is None or not path.is_file():
        return None
    # A plan kept somewhere other than the card's directory is left where it is: the card
    # stops pointing at it, and nothing outside the card's own directory is renamed.
    return path if path.resolve().parent == work["card_dir"].resolve() else None


def steps(work: dict) -> list[str]:
    """What a run does, one line each: what the dry run prints."""
    card_id = work["card"]["id"]
    out = [f"push {path} with keel board push --card {card_id} --new, for {ref}"
           for ref, path in work["pushes"].items()]
    out += [f"reuse {target} for {ref}" for ref, target in work["reuses"].items()]
    for doc in work["docs"]:
        old = old_of(work, doc)
        if old is not None:
            out.append(f"keep {old} as {old.name}{suffix_of(old)}")
        out.append(f"write {target_of(work, doc)}, board ids rewritten, card {card_id}")
        out.append(f"kb lint {card_id} --file {target_of(work, doc)}")
    if "plan" in work["docs"]:
        out.append(f"kb set {card_id} plan_ref={target_of(work, 'plan')}")
    out.append(f"kb note {card_id} (one line: what was installed, the boards, the kept files)")
    return out


def install(work: dict, verbs: Verbs) -> dict:
    """Push, rewrite, lint, keep the old files, point the card at the new plan, note it."""
    card_id = work["card"]["id"]
    ids = dict(work["reuses"])
    for ref, path in work["pushes"].items():
        ids[ref] = verbs.push_new(card_id, path, work["root"])[0]
    staged = {}
    for doc, entry in work["docs"].items():
        old_card = planformat.parse(entry["text"])["meta"].get("card")
        text = rewrite(entry["text"], ids, old_card, card_id)
        staged[doc] = work["card_dir"] / (target_of(work, doc).name + ".new")
        staged[doc].write_text(text)
        linted = verbs.lint(card_id, staged[doc], doc == "outcome", work["root"])
        if linted.returncode != 0:
            raise InstallError(f"the rewritten {doc} does not lint, left at {staged[doc]}: "
                               + " | ".join(linted.stdout.strip().splitlines()[1:4]))
    kept = []
    for doc, new in staged.items():
        old = old_of(work, doc)
        if old is not None:
            keep = old.with_name(old.name + suffix_of(old))
            old.rename(keep)
            kept.append(keep.name)
        new.rename(target_of(work, doc))
    if "plan" in staged:
        verbs.set_plan(card_id, target_of(work, "plan"))
    pushed = [ids[ref] for ref in work["pushes"]]
    reused = sorted(set(work["reuses"].values()))
    verbs.note(card_id, "plan pages installed: " + " and ".join(
        target_of(work, doc).name for doc in staged) + " in the plan format"
        + (f"; boards pushed {', '.join(pushed)}" if pushed else "")
        + (f"; reused {', '.join(reused)}" if reused else "")
        + (f"; the old files are kept as {', '.join(kept)}" if kept else ""))
    return {"ids": ids, "kept": kept, "files": [str(target_of(work, d)) for d in staged]}


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="keel-plan-install", description=__doc__.split("\n\n")[0])
    parser.add_argument("card", help="the card, c-NNN")
    parser.add_argument("--plan", help="the converted plan.md")
    parser.add_argument("--context", help="the converted context.md (the outcome)")
    parser.add_argument("--board", action="append", metavar="b-NNN=<file>",
                        help="a board the documents embed, pushed from this line file")
    parser.add_argument("--reuse", action="append", metavar="b-NNN=b-MMM",
                        help="a board the documents embed that is one the card already has")
    parser.add_argument("--root", help="the card's worktree, for the path:line refs")
    parser.add_argument("--card-dir", help="the card's directory (default: this checkout's state)")
    parser.add_argument("--dry-run", action="store_true", help="print what it would do, change nothing")
    return parser


def main(argv: list[str], verbs: Verbs | None = None) -> int:
    args = build_parser().parse_args(argv)
    verbs = verbs or Verbs()
    try:
        work = plan_work(args, verbs)
        errors = prelint(work, verbs)
        if errors:
            print("keel-plan-install: the documents do not lint, nothing was done:\n  "
                  + "\n  ".join(errors), file=sys.stderr)
            return 1
        if args.dry_run:
            print("\n".join(["dry run, nothing changed; a run would:", *("  " + s for s in steps(work))]))
            return 0
        done = install(work, verbs)
    except InstallError as refusal:
        print(f"keel-plan-install: {refusal}", file=sys.stderr)
        return 1
    print(json.dumps(done, indent=2))
    return 0
