"""A tracking card whose slices are all done is closed by the drain (lane X, c-649).

c-277, "Voice, the next level", was split into nine slices. All nine reached done on
2026-09-20 and the card sat stored at `building` for four days with needs-you false, so the
deck showed it nowhere: nothing moved a tracking card on when its tally completed. Lane X
brought it to his outcome gate; then c-628 sat at that gate with no outcome at all, asking
him to approve again what he had approved slice by slice. His word (2026-10-05): a tracking
card has no outcome gate of its own. Every drain pass runs `upkeep` over the tracking cards
it owns:

- **Every slice done** (archived ones do not count, `views.tracked`): the card moves
  straight to `done`, from wherever it is, review included (a card brought to his gate
  before c-649 closes on the next pass). The move's note says why (`CLOSED`), and its
  `output_ref` is the ROLLUP this module writes first, `state/cards/<id>/outcome.md`: a
  summary line, then per slice its id and title, the first lines of its own outcome, where
  it landed, and a link to that outcome. Nothing is merged, landed or published: each slice
  did that when he approved it.
- **A slice left done while it waits at review, or after it closed** (reopened, sent back,
  taken to shipping by the sync, a new slice filed under it): back to `building` with a note
  naming what is not done, and closed again, with a fresh rollup, once every slice is.
- **He sent it back** (review to building): it stays back until a slice changes, so Send
  back is not undone by the next pass. "Changes" is read from the board: a slice reaching
  done after his move. His Back to your gate brings it to review, and the next pass closes it.
- **He is in the middle of it**: no close while the card is blocked, held by voice or a
  drop-in, or has an open ask; the next pass after that closes it.

The close is the board's (`Board.close_tracking`, and his Approve outcome through the same
`_close_tracking`): it reads the slices again inside its own write, so a slice reopened
since this pass looked refuses it, and the rollup is put in place only once the move is
made. A move refused because he or another drain got there first is left to the next pass;
a disk error is logged for that card and the pass goes on.
"""

import re
from pathlib import Path

from keel import views
from keel.board import Refused

CLOSED = "every slice is done; each passed its own outcome gate"
BACK = "back to tracking until every slice is done"
ROLLUP = "outcome.md"
FIRST_WORDS = 60            # the first lines of a slice's outcome, not the page (C21's wall is 180)
EM_DASH = "\u2014"
# A markdown link (or image), whose target is group 2.
LINK = re.compile(r"(!?\[[^\]\n]*\])\(([^)\s]+)\)")
# One unit the cut never splits: a run of text whose code spans and links count as one piece.
ATOM = re.compile(r"(?:`[^`]*`|!?\[[^\]\n]*\]\([^)\s]*\)|[^\s`\[!]|[`\[!])+")


def upkeep(board, mine, log=None) -> dict:
    """One pass over the tracking cards `mine(card)` says this drain owns. Returns how many
    were closed (`closed`) and how many went back to tracking (`back`). `log(line)` hears
    of a card a disk error stopped; the others are still tended."""
    cards = board.list_cards()
    moved = {"closed": 0, "back": 0}
    for card in cards:
        derived = card["derived"]
        if not derived["tracking"] or derived["archived"] or not mine(card):
            continue
        slices = [c for c in cards
                  if c.get("parent") == card["id"] and not c["derived"]["archived"]]
        try:
            moved["back"] += back_if_left(board, card, slices)
            moved["closed"] += close_if_done(board, card, slices)
        except Refused:
            continue            # he, or another drain, moved it first: the next pass reads again
        except OSError as error:
            if log is not None:
                log(f"tracking close of {card['id']} failed: {error}")
    return moved


def done(slices: list[dict]) -> bool:
    return bool(slices) and all(s["stage"] == "done" for s in slices)


def close_if_done(board, card: dict, slices: list[dict]) -> int:
    """To done with the rollup as its outcome (`Board.close_tracking`), when every slice is
    done, nothing of his holds it, and he has not sent it back since the last of them got
    there (a card at review was brought there, by the drain before c-649 or by his own tap,
    so it closes). 1 when it moved."""
    if card["stage"] == "done" or not done(slices) or held(card):
        return 0
    if card["stage"] != "review" and sent_back_since(board, card, slices):
        return 0
    board.close_tracking(card["id"], "drain", CLOSED)
    return 1


def held(card: dict) -> bool:
    """He is in the middle of this card: it is blocked, voice or a drop-in holds it, or an
    ask about it is open. `drain.retire_tracking` skips the same holds."""
    options = card.get("options")
    return bool(card.get("blocked_reason") or views.voice_hold(options)
                or views.dropin_hold(options) or card["derived"].get("ask"))


def back_if_left(board, card: dict, slices: list[dict]) -> int:
    """Back to building with a note when a slice is not done while the card waits at review,
    or after the drain closed it (a slice reopened or shipping, or one filed under it)."""
    left = [s for s in slices if s["stage"] != "done"]
    if not left or card["stage"] not in ("review", "done"):
        return 0
    board.stage(card["id"], "building", "drain")
    said = ", ".join(f"{s['id']} is at {s['stage']}" for s in left)
    board.note(card["id"], f"{said}: {BACK}", "drain")
    return 1


def sent_back_since(board, card: dict, slices: list[dict]) -> bool:
    """The card left review AFTER the newest slice reached done, so nothing has changed
    since, and closing it would undo his Send back."""
    left_review = [e["id"] for e in board.events(card["id"]) if moved(e, frm="review")]
    if not left_review:
        return False
    reached = [e["id"] for s in slices for e in board.events(s["id"]) if moved(e, to="done")]
    return max(reached, default=0) < max(left_review)


def moved(event: dict, to: str | None = None, frm: str | None = None) -> bool:
    """A stage move (a `stage`, or an `approve` that moved it) to `to`, or from `frm`."""
    data = event.get("data") or {}
    if event["kind"] not in ("stage", "approve") or "to" not in data:
        return False
    return (to is None or data["to"] == to) and (frm is None or data.get("from") == frm)


# ----- the rollup: the tracking card's outcome -----

def draft_rollup(board, card: dict, slices: list[dict], cards_dir: Path) -> tuple[Path, Path]:
    """The rollup written whole beside its place, `(draft, place)`: the board's close renames
    the draft over `state/cards/<id>/outcome.md` once its move is made, so a reader never
    sees half of one and a refused close leaves none."""
    path = Path(cards_dir) / card["id"] / ROLLUP
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(".md.tmp")
    try:
        temp.write_text(rollup(board, card, slices, cards_dir))
    except OSError:
        temp.unlink(missing_ok=True)
        raise
    return temp, path


def rollup(board, card: dict, slices: list[dict], cards_dir: Path) -> str:
    """An outcome in the plan format (`kind: outcome`, `change: none`: the card itself lands
    nothing, so C33 does not hold it), with the five sections and the Risk `kb lint` asks of
    one that ships. Evidence is the slices, each linking its own outcome; with no outcome to
    link at all, a text block of the slices is the artifact C26 wants."""
    outcomes = [outcome_of(s, cards_dir) for s in slices]
    entries = [entry(board, s, o) for s, o in zip(slices, outcomes)]
    if not any(outcomes):
        entries += ["", "```text board | where each slice ended", *(f"{s['id']} done" for s in slices), "```"]
    return "\n".join([
        "---", "kind: outcome", f"card: {card['id']}", f"title: {clean(card['title'])}",
        "change: none", "---",
        f"# {clean(card['title'])}", "",
        f"All {len(slices)} slices are done, and each passed its own outcome gate, so the drain "
        f"closed this tracking card with no gate of its own.", "",
        "## Where it stands", "",
        "Done. Each slice landed or was published when you approved it; this card merged, "
        "landed and published nothing.", "",
        "## What is next", "", "Nothing on this card.", "",
        "## Why this shape", "",
        "A tracking card does no work of its own: its slices carry the work, and each one "
        "came to your outcome gate on its own.", "",
        "## Risk", "", "Low: this card changes nothing; each slice's risk was read at its own gate.", "",
        "## Open questions", "", "None.", "",
        "## Evidence", "", *entries, ""])


def entry(board, slice_card: dict, outcome: Path | None) -> str:
    """One slice: id and title, the first lines of its outcome, where it landed, a link."""
    head = f"- **{slice_card['id']} {clean(slice_card['title'])}:** {landed(board, slice_card)}."
    said = first_lines(outcome, outcome.parent if outcome is not None else None)
    if said:
        head += f" {said}"
    if outcome is not None:
        head += f" [Its outcome]({outcome})"
    return head


def outcome_of(slice_card: dict, cards_dir: Path) -> Path | None:
    """A slice's own outcome: its `output_ref` when that is a file in its card folder (a
    tracking slice's own rollup, `outcome.md`), else its `context.md`, else an `output_ref`
    that is a file anywhere."""
    own = Path(cards_dir) / slice_card["id"]
    ref = Path(str(slice_card.get("output_ref") or ""))
    found = ref.is_absolute() and ref.is_file()
    # its own folder and a markdown record only: an artifact (a board's ops, an image) there
    # is not prose to quote (review r1 regression)
    if found and ref.suffix == ".md" and ref.resolve().is_relative_to(own.resolve()):
        return ref
    if (slice_card.get("derived") or {}).get("tracking") and (own / ROLLUP).is_file():
        return own / ROLLUP
    if (own / "context.md").is_file():
        return own / "context.md"
    return ref if found else None


def first_lines(path: Path | None, base: Path | None = None) -> str:
    """The outcome's first paragraph under its title (`prose`, relative links read against
    `base`, its folder), cut to `FIRST_WORDS`; "" for none."""
    if path is None:
        return ""
    try:
        text = path.read_text(errors="replace")
    except OSError:
        return ""
    body = re.sub(r"\A---\n.*?\n---\n", "", text, flags=re.S)
    for para in re.split(r"\n\s*\n", body):
        para = " ".join(para.split())
        if para and not para.startswith(("#", "```", "|", ">", "!")):
            return cut(relink(clean(para), base))
    return ""


def clean(text: str) -> str:
    """No markup that would break the one list item the slice is written as, and no
    em-dash, which `kb lint` refuses (C24)."""
    text = re.sub(rf"\s*{EM_DASH}\s*", ", ", text)
    return " ".join(text.replace("**", "").split())


def relink(text: str, base: Path | None) -> str:
    """Each relative link made absolute against `base` (the slice's folder), so it still
    opens from the parent's folder; with no base, the link's words alone."""
    def one(found: re.Match) -> str:
        label, target = found.group(1), found.group(2)
        if re.match(r"[a-z][a-z0-9+.-]*:|/|#", target):
            return found.group(0)
        if base is None:
            return label.lstrip("!")[1:-1]
        return f"{label}({base / target})"
    return LINK.sub(one, text)


def cut(text: str) -> str:
    """At most `FIRST_WORDS` words, cut between whole pieces (`ATOM`), never inside a code
    span or a link: at the last sentence end kept, else with " ...". A backtick left
    unpaired is dropped, so it opens no span in the line after it."""
    kept, words, atoms = [], 0, ATOM.findall(text)
    for atom in atoms:
        words += len(atom.split())
        if words > FIRST_WORDS:
            break
        kept.append(atom)
    if len(kept) < len(atoms):
        ends = [n for n, atom in enumerate(kept) if atom.rstrip(")\"'").endswith((".", "!", "?"))]
        kept = kept[:ends[-1] + 1] if ends else kept + ["..."]
    said = " ".join(kept)
    return said.replace("`", "") if said.count("`") % 2 else said


def landed(board, slice_card: dict) -> str:
    """Where a slice landed: its landing's sha and merge, else how its approve ended it."""
    land = (slice_card.get("options") or {}).get("landing") or {}
    if land.get("state") == "landed" and land.get("sha"):
        said = f"landed `{str(land['sha'])[:7]}`"
        published = str(land.get("published") or "").strip()
        return f"{said}, {clean(published.splitlines()[0])}" if published else said
    return ended(board, slice_card["id"])


def ended(board, card_id: str) -> str:
    """How a slice reached done, from its newest move there."""
    arrived = [e for e in board.events(card_id) if moved(e, to="done")]
    if not arrived:
        return "done"
    data = arrived[-1].get("data") or {}
    if arrived[-1]["kind"] != "approve":
        return f"staged done by {arrived[-1]['actor']}"
    if data.get("sha"):
        return f"approved, landed {str(data['sha'])[:7]}"
    if data.get("tracking"):
        return "approved, closed as a tracking card"
    published = str(data.get("published") or "").strip()
    if published:
        return f"approved, published: {clean(cut(published.splitlines()[0]))}"
    return "approved"
