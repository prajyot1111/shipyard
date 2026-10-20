"""The review fetcher, as a drain upkeep step (lane RC, RC-1 and RC-5).

A pull request that needs his review arrives as a REVIEW CARD in the work inbox, and the
cards flow does the rest: his Review tap moves it to assigned, and the drain starts its
house in the review pool (`options.slot = review`, `reviews_max`, the login hold) like any
card. On the machine that holds the space (the Mac: the code host's credentials never
leave it), every drain pass asks, per space whose adapter has the `review` verb:

1. **Is it time to look?** The pull request watcher's cadence (`shipwatch.poll_every`):
   every 15 minutes in work hours, hourly outside them, and at once when this process has
   not looked yet. When this process last looked is kept in memory (`LAST_SCANNED`), a
   schedule and not state, as `shipping.LAST_POLLED` is.
2. **What needs him?** The adapter's `review scan` says, in the engine's words: each open
   pull request that needs his review (its key `<repo>:<number>`, title, author, when it
   was raised, head, branches, url, description). The two settings, auto review and the
   review model, are the space's own (`keel/reviewsettings.py`: the install's `config.toml`, or the live
   override the deck's gear writes), read here on every filing (lane RETIRE, RT-2).
3. **File what has no card** (`file_card`): ONE card per key, ever (every review card of
   the space is looked at, archived and done included, so a second is never filed), in
   the inbox, or at assigned when auto review is on; kind review, the review pool, the
   review model unless a card says otherwise, `repo` the pull request's repo, titled
   "Review: <title>".
4. **Tend the cards it has** (`tend`): an inbox card whose pull request closed or merged
   before he tapped Review becomes a NOTICE he can dismiss (`options.notice_key`); a
   posted card (`options.review_posted`) whose pull request has a new head shows "new
   commits since your review" (`options.review_new`), which his Re-review answers
   (`Board.rereview`); a posted card whose pull request closed is marked
   (`options.review_closed`) and never looked at again. A card he DISMISSED (archived)
   stays hidden while its pull request is still, and comes back, the same card, when the
   pull request has new activity after the dismissal (`revive`, RC-8).

Everything that means something is written on the card, and only when it changes.
Nothing here posts, pushes or starts a house.
"""

from __future__ import annotations

import json
import traceback
from datetime import datetime

from keel import adapters, readiness, reviewfeature, reviewreap, reviewsettings, reviewwait, shipwatch, terms, views
from keel.config import Config

REVIEW_VERB = "review"
LOG_NAME = "drain.log"
SCAN_SECONDS = 300
KEY_OPTION = "review_key"
PR_OPTION = "review_pr"
POSTED_OPTION = "review_posted"
NEW_OPTION = "review_new"
CLOSED_OPTION = "review_closed"
NOTICE_OPTION = "notice_key"
# c-730 r1.F1: a row the pack says comes from a fork (`fork: true`). Its code is not the
# team's, and on a public host a stranger's fork can ask for the user's review without the
# user, so its card is never started by auto review: it waits for the user's Review tap.
FORK_OPTION = "review_fork"
FORK_WORDS = ("This {change} comes from a fork: its code is not your team's. Its house reads that "
              "code and never runs it, confined in a checkout, without the repo's own settings.")
REVIEW_SLOT = "review"
DEFAULT_MODEL = reviewsettings.DEFAULT_MODEL
TITLE_MAX = 110
ACTOR = "drain"
# When THIS process last looked, by space. A schedule, not a record.
LAST_SCANNED: dict[str, datetime] = {}
CLOSED_WORDS = {"merged": "merged", "declined": "was declined"}


def now() -> datetime:
    return datetime.now().astimezone()


def log(cfg: Config, text: str) -> None:
    cfg.logs_dir.mkdir(parents=True, exist_ok=True)
    with open(cfg.logs_dir / LOG_NAME, "a") as handle:
        handle.write(f"{now().isoformat(timespec='seconds')} reviews: {text}\n")


def due(at: datetime, last: datetime | None, cfg: Config) -> bool:
    return last is None or at - last >= shipwatch.poll_every(at, {}, cfg.ship_hours)


def upkeep(cfg: Config, board, served: set[str], at: datetime | None = None) -> dict:
    """One pass over the spaces this machine serves whose adapter can scan for reviews: a
    space whose pack does not declare review scanning is skipped before its verb is looked
    for (c-631). Never raises for one card or one space: a failure is logged and the rest
    go on."""
    at = at or now()
    result = {"scanned": 0, "filed": [], "notices": 0, "new": 0, "closed": 0}
    for name in sorted(served):
        space = cfg.spaces.get(name)
        if space is None or readiness.refusal(cfg, space, "reviews"):
            continue
        if not adapters.has_verb(space, REVIEW_VERB):      # an older adapter with no pack.toml
            continue
        try:
            reviewreap.reap(cfg, board, name)               # c-734: every pass, not only a scan's
        except Exception:  # noqa: BLE001 - one space must not stop the pass
            log(cfg, f"{name}: reaping done review cards failed:\n" + traceback.format_exc().strip())
        asked = "asked" in reviewsettings.scan_state(cfg, name)      # his Scan now
        if not (asked or due(at, LAST_SCANNED.get(name), cfg)):
            continue
        LAST_SCANNED[name] = at
        seen = scan(cfg, space)
        if seen is None:
            continue
        reviewsettings.scanned(cfg, name, at)
        result["scanned"] += 1
        try:
            tend_space(cfg, board, name, seen, at, result)
        except Exception:  # noqa: BLE001 - one space must not stop the pass
            log(cfg, f"{name} failed:\n" + traceback.format_exc().strip())
    return result


def scan(cfg: Config, space) -> dict | None:
    try:
        seen = json.loads(adapters.run(space, REVIEW_VERB, "scan", timeout=SCAN_SECONDS))
    except (adapters.AdapterError, ValueError) as error:
        log(cfg, f"could not scan {space.name}: {str(error).splitlines()[0]}")
        return None
    return seen if isinstance(seen, dict) and isinstance(seen.get("prs"), list) else None


def is_review(card: dict) -> bool:
    return bool((card.get("options") or {}).get(KEY_OPTION))


def review_cards(board, space: str) -> dict[str, dict]:
    """Every review card of the space by its key, archived and done included: a key that has
    a card never gets a second one."""
    found = {}
    for card in board.list_cards(space=space):
        if is_review(card):
            found.setdefault(card["options"][KEY_OPTION], card)
    return found


class Pass:
    """One space's pass: what every filing and tending step of it reads (the settings, the
    cards by key, the scan's `open_groups`, the clock) and the one door to the adapter."""

    slot, pr_option, actor = REVIEW_SLOT, PR_OPTION, ACTOR

    def __init__(self, cfg: Config, board, space: str, seen: dict, at: datetime, result: dict):
        conf = cfg.spaces[space]
        self.cfg, self.board, self.space, self.at, self.result = cfg, board, space, at, result
        self.settings = reviewsettings.effective(cfg, space)
        self.auto = self.settings.get("auto") is True
        self.days = getattr(conf, "review_backlog_days", 15)
        self.hours = int(getattr(conf, "review_sibling_hours", 48))
        self.stamp = at.isoformat(timespec="seconds")
        self.cards = review_cards(board, space)
        groups = seen.get("open_groups")
        self.open_groups = groups if isinstance(groups, dict) else {}

    def facts(self, pr: dict, before: dict) -> dict:
        return pr_facts(pr, before, self.at, self.days)

    def ask(self, verb: str, *args: str):
        """`review <verb> <args>`: the adapter's JSON, or None, logged."""
        try:
            return json.loads(adapters.run(self.cfg.spaces[self.space], REVIEW_VERB, verb, *args,
                                           timeout=SCAN_SECONDS))
        except (adapters.AdapterError, ValueError) as error:
            log(self.cfg, f"review {verb} {' '.join(args)} failed: {str(error).splitlines()[0]}")
            return None

    def create(self, title: str, brief: str, repo: str, options: dict) -> str:
        made = self.board.create(self.space, title[:TITLE_MAX], brief=brief, autonomy="autonomous", repo=repo,
                                 model=self.settings.get("model") or DEFAULT_MODEL, options=options,
                                 actor=ACTOR)
        made = made["id"] if isinstance(made, dict) else made
        self.cards[options[KEY_OPTION]] = self.board.get(made)
        self.result["filed"].append(made)
        return made


def tend_space(cfg: Config, board, space: str, seen: dict, at: datetime, result: dict) -> None:
    ctx = Pass(cfg, board, space, seen, at, result)
    open_now = {}
    rows = [pr for pr in seen["prs"] if str(pr.get("key") or "")]
    features = {group: members for group, members in reviewfeature.groups(rows).items()
                if reviewfeature.is_unit(ctx.cards, group, members)}
    for group, members in features.items():
        key = reviewfeature.feature_key(group)
        if key in ctx.cards:
            reviewfeature.update_members(ctx, ctx.cards[key], members)
            refresh(board, board.get(ctx.cards[key]["id"]), feature_listing(members, ctx.cards[key]), at, ctx.days)
        else:
            reviewfeature.file_feature(ctx, group, members)
        open_now[key] = {"head": reviewfeature.composite_head(reviewfeature.members_of(members))}
    in_feature = {pr["key"] for members in features.values() for pr in members}
    for pr in rows:
        open_now[pr["key"]] = pr
        if pr["key"] in ctx.cards:
            # A single card folded into a feature card, or one he dismissed for it (c-480),
            # stays archived: the feature card reviews this pull request's new activity, and
            # reviving the single card would review it twice. RC-8 still holds for the rest.
            if not (pr["key"] in in_feature and ctx.cards[pr["key"]]["derived"]["archived"]):
                refresh(board, ctx.cards[pr["key"]], pr, at, ctx.days)
        elif pr["key"] not in in_feature:
            file_single(ctx, pr)
    for key, card in list(ctx.cards.items()):
        try:
            if views.held_wait(board.get(card["id"])):
                reviewwait.tend_held(ctx, board.get(card["id"]), repos_of(card))
            tend(cfg, board, board.get(card["id"]), open_now.get(key), at, result)
        except Exception:  # noqa: BLE001 - one card must not stop the others
            log(cfg, f"{card['id']} failed:\n" + traceback.format_exc().strip())


def repos_of(card: dict) -> list[str]:
    return [r.strip() for r in str(card.get("repo") or "").split(",") if r.strip()]


def feature_listing(members: list[dict], card: dict) -> dict:
    """The feature's facts as one listed pull request's, for `refresh`."""
    title = str(card.get("title") or "").split(" \u00b7 ", 1)[-1]
    row = reviewfeature.feature_row(reviewfeature.members_of(members), title)
    stamps = [m.get("updated") for m in members if m.get("updated")]
    return dict(row, updated=max(stamps) if stamps else None)


composite_head = reviewfeature.composite_head


# ----- filing -----

def brief_of(pr: dict, t=None) -> str:
    """The card's own words: what the reviewer is handed as the change's intent, in the
    space's words (`t`, c-630)."""
    head = (terms.say(t, "Review {change} #") + f"{pr.get('pr')} in {pr.get('repo')}, "
            f"by {pr.get('author') or 'someone'}.")
    fork = terms.say(t, FORK_WORDS) if pr.get("fork") else ""
    parts = [head, fork, str(pr.get("title") or "").strip(), str(pr.get("description") or "").strip()]
    return "\n\n".join(part for part in parts if part)


PR_FIELDS = ("author", "created", "updated", "url", "head", "title")


def latest(*stamps) -> str | None:
    """The latest of some ISO stamps, compared as instants; None when there is none."""
    found = [(shipwatch.parse(s), s) for s in stamps if s]
    found = [(at, s) for at, s in found if at is not None]
    return max(found)[1] if found else None


def pr_facts(pr: dict, before: dict, at: datetime, backlog_days: int) -> dict:
    """What the card keeps about its pull request (`options.review_pr`): the host's own
    fields, and ACTIVITY, the latest of when it was raised, the host's last update (a push,
    a comment, a reviewer requested), and the moment this fetcher first saw a new head. The
    backlog rule reads it (`views.review_backlog`) with the space's `backlog_days`."""
    facts = {name: pr.get(name) for name in PR_FIELDS}
    moved = at.isoformat(timespec="seconds") if before.get("head") and pr.get("head") != before.get("head") else None
    facts["activity"] = latest(pr.get("created"), pr.get("updated"), moved, before.get("activity"))
    facts["backlog_days"] = backlog_days
    return facts


def card_options(pr: dict, facts: dict) -> dict:
    options = {"kind": "review", KEY_OPTION: pr["key"], "slot": REVIEW_SLOT, "pr": pr.get("pr"),
               "branch": pr.get("branch"), "base": pr.get("base"), "tracker_mode": "none",
               PR_OPTION: facts}
    if pr.get("group"):
        options[reviewfeature.GROUP_OPTION] = pr["group"]
    if pr.get("fork"):
        options[FORK_OPTION] = True
    return options


def file_single(ctx: Pass, pr: dict) -> str:
    """One pull request's card; Held when its story's other side has a branch and no pull
    request yet (GR-3), and then never auto assigned."""
    wait = reviewwait.wait_for(ctx, pr["group"], [pr.get("repo")]) if pr.get("group") else None
    if wait is None:
        return file_card(ctx.board, ctx.space, pr, ctx.settings, ctx.facts(pr, {}), ctx=ctx)
    card_id = file_card(ctx.board, ctx.space, pr, dict(ctx.settings, auto=False), ctx.facts(pr, {}), ctx=ctx,
                        quiet=True)
    reviewwait.hold(ctx, card_id, wait, f"review card for {pr['key']}, by {pr.get('author') or 'someone'}, "
                                        f"filed by the review fetcher")
    return card_id


def file_card(board, space: str, pr: dict, settings: dict, facts: dict, ctx: "Pass | None" = None,
              quiet: bool = False) -> str:
    """ONE review card for one pull request: at the inbox, or at assigned with auto review
    on. The model is the review model unless the setting names none. `quiet` leaves the
    note to the caller (a held card says why it waits)."""
    t = terms.of(ctx.cfg, ctx.space) if ctx is not None else terms.of_board(board, space)
    named = str(pr.get("title") or "").strip() or f"{t['change']} {pr.get('pr')}"
    title = f"Review: {named}"[:TITLE_MAX]
    if ctx is not None:
        card_id = ctx.create(title, brief_of(pr, t), pr.get("repo"), card_options(pr, facts))
    else:
        card_id = board.create(space, title, brief=brief_of(pr, t), autonomy="autonomous", repo=pr.get("repo"),
                               model=settings.get("model") or DEFAULT_MODEL, options=card_options(pr, facts),
                               actor=ACTOR)
        card_id = card_id["id"] if isinstance(card_id, dict) else card_id
    if quiet:
        return card_id
    said = f"review card for {pr['key']}, by {pr.get('author') or 'someone'}, filed by the review fetcher"
    if pr.get("fork"):
        board.note(card_id, said + "; it comes from a fork, so it waits for your Review tap even with "
                                   "auto review on", ACTOR)
    elif settings.get("auto") is True:
        board.stage(card_id, "assigned", ACTOR, note=said + "; auto review is on, so it is assigned")
    else:
        board.note(card_id, said + "; tap Review to start it", ACTOR)
    return card_id


# ----- tending -----

def refresh(board, card: dict, pr: dict, at: datetime, days: int) -> None:
    """Keep the card's pull request facts current, written only when they changed: the
    activity stamp is what takes a quiet card into the backlog and a moving one out. A
    dismissed card's facts stay as they were when he dismissed it, unless the pull request
    has moved since (`revive`)."""
    before = (card.get("options") or {}).get(PR_OPTION) or {}
    facts = pr_facts(pr, before, at, days)
    if card["derived"]["archived"]:
        revive(board, card, facts)
    elif facts != before:
        board.set_fields(card["id"], {"options": {PR_OPTION: facts}}, ACTOR)


def dismissed_at(board, card_id: str) -> datetime | None:
    """When he last dismissed this card: the newest `set` event that archived it (his
    Dismiss review, or Archive). None for a card archived with no such event."""
    for event in reversed(board.events(card_id)):
        data = event.get("data") or {}
        if event["kind"] == "set" and (data.get("options") or {}).get("archived") is True:
            return shipwatch.parse(event["at"])
    return None


def revive(board, card: dict, facts: dict) -> None:
    """RC-8: a dismissed review card comes back when its pull request, still listed as
    needing his review, has NEW ACTIVITY after the dismissal: the activity stamp
    (`pr_facts`: the host's update stamp, or a new head this fetcher saw) later than the
    moment he dismissed it. It is the same card, never a second one; its facts are
    refreshed and a note says why it is back."""
    since = dismissed_at(board, card["id"])
    moved = shipwatch.parse(facts.get("activity"))
    if since is None or moved is None or moved <= since:
        return
    board.set_fields(card["id"], {"options": {"archived": None, PR_OPTION: facts}}, ACTOR)
    board.note(card["id"], terms.say(terms.of_board(board, card["space"]),
                                     "the {change} has new activity since you dismissed this review; "
                                     "it is back on Reviews"), ACTOR)

def look(cfg: Config, card: dict) -> dict | None:
    """Where one card's pull request stands (`review <id> poll`), or None, logged."""
    try:
        seen = json.loads(adapters.run(cfg.spaces[card["space"]], REVIEW_VERB, card["id"], "poll",
                                       timeout=SCAN_SECONDS))
    except (adapters.AdapterError, ValueError) as error:
        change = terms.of(cfg, card["space"])["change"]
        log(cfg, f"could not look at {card['id']}'s {change}: {str(error).splitlines()[0]}")
        return None
    if isinstance(seen, dict) and isinstance(seen.get("members"), dict):
        return feature_poll(seen["members"])
    return seen if isinstance(seen, dict) else None


def feature_poll(members: dict) -> dict:
    """A feature card's pull requests as one (lane GRP): open while any member is, else
    merged when any merged, else declined; its head the members' heads together."""
    states = [str((one or {}).get("state") or "open") for one in members.values()]
    state = "open" if "open" in states else ("merged" if "merged" in states else "declined")
    heads = [{"label": label, "head": (one or {}).get("head")} for label, one in members.items()]
    return {"state": state, "head": reviewfeature.composite_head(heads)}


def tend(cfg: Config, board, card: dict, listed: dict | None, at: datetime, result: dict) -> None:
    options = card.get("options") or {}
    if options.get(CLOSED_OPTION) or card["derived"]["archived"]:
        return
    if card["stage"] == "inbox" and not options.get(NOTICE_OPTION):
        if listed is None:
            closed_before_review(cfg, board, card, result)
        return
    posted = options.get(POSTED_OPTION) or {}
    if card["stage"] != "done" or not posted.get("head"):
        return
    seen = {"state": "open", "head": listed.get("head")} if listed else look(cfg, card)
    if seen is None:
        return
    if seen.get("state") in CLOSED_WORDS:
        board.set_fields(card["id"], {"options": {CLOSED_OPTION: seen["state"], NEW_OPTION: None}}, ACTOR)
        change = terms.of(cfg, card["space"])["change"]
        board.note(card["id"], f"the {change} {CLOSED_WORDS[seen['state']]}; the review is finished", ACTOR)
        result["closed"] += 1
    elif seen.get("head") and seen["head"] != posted["head"] and \
            (options.get(NEW_OPTION) or {}).get("head") != seen["head"]:
        board.set_fields(card["id"], {"options": {NEW_OPTION: {"head": seen["head"], "at": at.isoformat(timespec="seconds")}}}, ACTOR)
        if not options.get(NEW_OPTION):
            board.note(card["id"], "new commits since your review: Re-review starts a new round", ACTOR)
        result["new"] += 1


def closed_before_review(cfg: Config, board, card: dict, result: dict) -> None:
    """An inbox card whose pull request no longer needs him: a notice only when it closed
    or merged; one he approved elsewhere, or that dropped him as a reviewer, stays as it is."""
    seen = look(cfg, card)
    if not seen or seen.get("state") not in CLOSED_WORDS:
        return
    board.set_fields(card["id"], {"options": {NOTICE_OPTION: f"review:{card['options'][KEY_OPTION]}",
                                              CLOSED_OPTION: seen["state"]}}, ACTOR)
    change = terms.of(cfg, card["space"])["change"]
    board.note(card["id"], f"the {change} {CLOSED_WORDS[seen['state']]} before you reviewed it; "
                           f"Dismiss puts this card away", ACTOR)
    result["notices"] += 1
