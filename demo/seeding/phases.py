"""The four phases of the seeded day (`day.py` has the board, the clock and git)."""

from __future__ import annotations

from datetime import timedelta

from seeding.day import (EXPORT_TITLE, BoardKb, Day, SeedError, commit_files, merge, open_pr,
                         push_board, push_branch)  # first: it puts Keel and the adapter on the path

from keel import adapters, deployask, requests, reviewcards  # noqa: E402

import sb_card  # noqa: E402
import sb_cut  # noqa: E402
import sb_host  # noqa: E402
import sb_pulls  # noqa: E402
import sb_tracker  # noqa: E402
from seeding import code, parallel, texts  # noqa: E402

SEARCH_TITLE = "Fix search ignoring case"
PLAN_TITLE = "Paginate the reports list"
CACHE_TITLE = "Cache report queries"
FIX_TITLE = "The publishable check reads each repo's branch in that repo's own clone"
FINISHED = (  # (space, title, repo, days ago): the week behind the morning
    ("work", "Speed up the reports query", "api", 6),
    ("work", "Add the owner column to the reports table", "web", 5),
    ("work", "Sort reports newest first", "api,web", 4),
    ("personal", "Book the physio follow-up", None, 3),
    ("personal", "Plan Sunday's long run", None, 2),
    ("personal", "Pay the electricity bill", None, 2),
)
FIRST_ID = sb_card.ID_FLOOR + 201


# ----- morning -----

def finished(day: Day) -> None:
    """A week of finished cards, numbered from c-9201, so the board has a past and every
    card filed after them is numbered past the live board's (`sb_card.ID_FLOOR`)."""
    for index, (space, title, repo, days) in enumerate(FINISHED):
        if day.card(title):
            continue
        when = day.ago(days=days, hours=3)
        day.at(when)
        stamp = when.isoformat(timespec="seconds")
        day.board.insert_card({"id": f"c-{FIRST_ID + index}", "space": space, "title": title, "repo": repo,
                               "stage": "done", "autonomy": "autonomous", "model": "opus",
                               "options": {}, "created_at": stamp,
                               "updated_at": (when + timedelta(hours=5)).isoformat(timespec="seconds")},
                              "cli", at=stamp)


def stage_of(day: Day, card_id: str) -> str:
    return day.board.get(card_id)["stage"]


def filed(day: Day, space: str, title: str, actor: str = "cli", **fields) -> str:
    """The card of this title, filed once: a phase that failed halfway resumes it by its
    stage rather than filing another or skipping it."""
    card = day.card(title)
    if card:
        return card["id"]
    made = day.board.create(space, title, actor=actor, **fields)
    return made if isinstance(made, str) else made["id"]


def search_fix(day: Day) -> None:
    """His search fix: built yesterday, approved, merged at 02:10, done. Each step is taken
    only from the stage before it, so a run that stopped halfway finishes here."""
    card = day.card(SEARCH_TITLE)
    if card and card["stage"] == "done":
        return
    night = day.overnight()
    start = night - timedelta(hours=10)
    raised = start + timedelta(minutes=40)
    day.at(start)
    cid = filed(day, "work", SEARCH_TITLE, brief="Searching 'revenue' finds nothing: the search is case-sensitive.",
                autonomy="autonomous", repo="api", model="opus",
                options={"kind": "bug", "tracker_ref": "st-98", "branch": code.SEARCH_FIX["branch"]})
    if stage_of(day, cid) == "inbox":
        day.board.stage(cid, "assigned", "cli")
    if stage_of(day, cid) == "assigned":
        day.at(start + timedelta(minutes=2))
        day.board.stage(cid, "building", "drain")
    pr = open_pr(code.SEARCH_FIX, "bug: Fix search ignoring case [st-98]",
                 "Search compares case-folded words, so 'revenue' finds Monthly revenue.", raised,
                 draft=True, number=11)
    if stage_of(day, cid) == "building":
        day.at(raised)
        sb_card.record_pr(day.board.get(cid), "api", pr["number"], kb=BoardKb(day))
        ctx = day.card_dir(cid) / "context.md"
        ctx.write_text(f"---\nkind: outcome\ncard: {cid}\ntitle: {SEARCH_TITLE}\nrepo: api\n---\n"
                       f"# {SEARCH_TITLE}\n\nSearch now ignores case.\n")
        day.board.stage(cid, "review", "house", plan_ref=str(ctx), output_ref=pr["url"])
    if stage_of(day, cid) == "review":
        day.at(raised + timedelta(minutes=35))
        day.board.approve(cid, "outcome", "human", publish=lambda c: approve_search(day, c))
    if stage_of(day, cid) == "shipping":
        sb_host.review("api", pr["number"], "approved", author={"id": "maya", "name": "Maya Chen"})
        day.at(night)
        merge("api", code.SEARCH_FIX["branch"], pr["number"], night)
        sb_host.set_state("api", pr["number"], "merged")
        day.board.note(cid, f"pull request #{pr['number']} merged", "drain")
        day.board.stage(cid, "done", "drain")


def approve_search(day: Day, card: dict) -> dict:
    ready = sb_host.set_draft("api", card["options"]["pr"], False)
    day.board.note(card["id"], f"published: pull request #{ready['number']} ready for review ({ready['url']})", "cli")
    return {"pr": ready["number"], "url": ready["url"], "draft": False, "shipping": True}


REVIEWS = (
    (code.DATE_FILTER, "Add a date range filter to /reports",
     "Adds `from` and `to` to /reports, as ISO days.", 12, 95),
    (code.TOTALS, "Show report totals in the table footer",
     "A footer row with the sum of the Total column.", 31, 50),
)


def reviews(day: Day) -> list[str]:
    """Two colleagues' pull requests, filed by Keel's own review fetcher, each reviewed."""
    for spec, title, description, number, minutes in REVIEWS:
        open_pr(spec, title, description, day.ago(minutes=minutes + 30), reviewers=["me"], number=number)
    parallel.open_reviews(day)
    day.at(day.ago(minutes=80))
    reviewcards.LAST_SCANNED.clear()
    reviewcards.upkeep(day.cfg, day.board, {"work"}, at=day.ago(minutes=80))
    ids = []
    for spec, title, _, number, minutes in REVIEWS:
        card = day.card(f"Review: {title}")
        if card is None:
            raise SeedError(f"the review fetcher filed no card for {spec['repo']}#{number}")
        ids.append(card["id"])
        if card["stage"] == "inbox":
            reviewed(day, card, spec, number, day.ago(minutes=minutes))
    return ids


def reviewed(day: Day, card: dict, spec: dict, number: int, when) -> None:
    day.at(when - timedelta(minutes=12))
    day.board.stage(card["id"], "assigned", "human", note="Review tapped")
    day.board.stage(card["id"], "building", "drain")
    sb_cut.worktrees_for(day.board.get(card["id"]))
    files = spec["files"]
    if spec is code.DATE_FILTER:
        ops = ('board "The date filter\'s code path"\nnode app server "reports_for" "reports/app.py"\n'
               'node dates file "in_range" "reports/dates.py"\nedge app -> dates "from, to"\n'
               'step app "The handler reads from and to, then filters the list."\n'
               'step dates "Each day is parsed, and a report is kept when its day is inside."\n')
        fill = {"app_line": code.line_of(files["reports/app.py"], "in_range(found"),
                "parse_line": code.line_of(files["reports/dates.py"], "fromisoformat"),
                "range_line": code.line_of(files["reports/dates.py"], "r.created < last")}
        template = texts.REVIEW_DATES
    else:
        ops = ('board "The totals footer\'s code path"\nnode draw box "draw" "reports.js"\n'
               'node total box "drawTotal" "reports.js"\nedge draw -> total "the rows shown"\n'
               'step draw "The table is redrawn on every search."\n'
               'step total "The shown rows are summed into the footer."\n')
        fill = {"draw_line": code.line_of(files["reports.js"], "function draw("),
                "total_line": code.line_of(files["reports.js"], "textContent = total")}
        template = texts.REVIEW_TOTALS
    board_id = push_board(card["id"], ops)
    ctx = day.card_dir(card["id"]) / "context.md"
    ctx.write_text(template.format(card=card["id"], pr=number, board=board_id, **fill))
    day.at(when)
    day.board.stage(card["id"], "review", "house", plan_ref=str(ctx), output_ref=sb_host.url(spec["repo"], number))


def plan_at_gate(day: Day) -> str:
    card = day.card(PLAN_TITLE)
    if card and card["stage"] != "inbox":
        return card["id"]
    day.at(day.ago(minutes=40))
    if card is None:
        made = day.board.create("work", PLAN_TITLE, brief="Page the reports list in the api and the table.",
                                autonomy="attended", repo="api,web", model="opus",
                                options={"kind": "feature", "tracker_mode": "create at task start"}, actor="cli")
        card = day.board.get(made if isinstance(made, str) else made["id"])
    day.board.stage(card["id"], "assigned", "cli")
    day.board.stage(card["id"], "building", "drain")
    head = sb_card.git(sb_card.origin_path("api"), "rev-parse", "main").stdout.strip()
    board_id = push_board(card["id"], (
        'board "The paging flow"\nnode page laptop "Reports page" "web"\nnode api server "/reports?page=" "api"\n'
        'node store database "the reports" "api"\nedge page -> api "cursor"\nedge api -> store "25 after the cursor"\n'
        'step page "The page asks for the first page, then the next with the cursor it was given."\n'
        'step api "The api answers 25 reports after the cursor, and the next cursor."\n'))
    plan = day.card_dir(card["id"]) / "plan.md"
    plan.write_text(texts.PLAN_PAGINATE.format(card=card["id"], at=head, board=board_id))
    day.at(day.ago(minutes=25))
    day.board.stage(card["id"], "planning", "house", plan_ref=str(plan))
    return card["id"]


def history(day: Day) -> dict:
    finished(day)
    return {"first": f"c-{FIRST_ID}"}


def morning(day: Day) -> dict:
    finished(day)
    search_fix(day)
    review_ids = reviews(day)
    plan = plan_at_gate(day)
    return {"reviews": review_ids, "plan": plan, "parallel": parallel.morning(day, filed)}


# ----- export (scene 8) -----

def export_card(day: Day) -> str:
    """The stand-in for the live export card, as scenes 4 to 7 leave it: attended, its plan
    approved, building. Only `all` and a bare `export` file it; a recording hands its own."""
    day.at(day.ago(minutes=20))
    cid = filed(day, "work", EXPORT_TITLE, brief="A button on the reports page that downloads the list as CSV.",
                autonomy="attended", repo="api,web", model="opus",
                options={"kind": "feature", "tracker_mode": "create at task start"})
    if stage_of(day, cid) == "inbox":
        day.board.stage(cid, "assigned", "cli")
    if stage_of(day, cid) == "assigned":
        day.board.stage(cid, "building", "drain")
    if stage_of(day, cid) == "building" and not day.board.get(cid).get("plan_ref"):
        plan = day.card_dir(cid) / "plan.md"
        plan.write_text(f"---\nkind: plan\ncard: {cid}\ntitle: {EXPORT_TITLE}\nrepo: api\n---\n# {EXPORT_TITLE}\n")
        day.board.stage(cid, "planning", "house", plan_ref=str(plan))
    if stage_of(day, cid) == "planning":
        day.at(day.ago(minutes=12))
        day.board.approve(cid, "plan", "human")
    return cid


def export(day: Day, card_id: str) -> str:
    """The export card's change on its own branch in both repos, a draft in each, and its
    outcome at his gate: what scene 8 opens."""
    day.live()
    card = day.board.get(card_id)
    if card["stage"] in ("review", "shipping", "done"):
        return card_id
    if card["stage"] != "building":
        raise SeedError(f"{card_id} is at {card['stage']}; the export phase takes a card at building")
    trees = sb_cut.worktrees_for(card)
    card = day.board.get(card_id)
    for repo, tree in zip(sb_card.repos_of(card), trees):
        change = code.EXPORT[repo]
        commit_files(tree, change["files"], change["subject"], "Robin", day.now)
        sb_card.git(tree, "push", "--quiet", "-u", "origin", sb_card.branch_in(card, repo))
    story = sb_tracker.url(sb_tracker.number_of(card["options"].get("tracker_ref")) or 0)
    ctx = day.card_dir(card_id) / "context.md"
    rows_line = code.line_of(code.EXPORT["api"]["files"]["reports/export.py"], "def rows(")
    ctx.write_text(texts.EXPORT_OUTCOME.format(card=card_id, story=story, rows_line=rows_line))
    opened = sb_pulls.open_drafts(card)["opened"]
    why = sb_pulls.missing(day.board.get(card_id))
    if why:
        raise SeedError(why)
    day.board.stage(card_id, "review", "house", plan_ref=card.get("plan_ref") or str(ctx),
                    output_ref=opened[0]["url"])
    return card_id


# ----- breaks (scene 9) -----

def refused(day: Day) -> str:
    """A card whose move to review Keel refused, filed with Bosun as a request."""
    day.at(day.ago(hours=2))
    cid = filed(day, "work", CACHE_TITLE, brief="Keep the reports list for a minute, and say how fresh it is.",
                autonomy="autonomous", repo="api,web", model="opus",
                options={"kind": "feature", "tracker_ref": "st-104", "branch": code.CACHE["branch"]})
    if stage_of(day, cid) == "inbox":
        day.board.stage(cid, "assigned", "cli")
    if stage_of(day, cid) == "assigned":
        day.board.stage(cid, "building", "drain")
    for spec in (code.CACHE, code.CACHE_WEB):
        push_branch(spec, day.ago(minutes=50))
    if stage_of(day, cid) == "building" and not request_of(day, cid):
        day.at(day.ago(minutes=45))
        requests.block_keel(day.board, cid, texts.CACHE_BLOCK, "house", day.cfg.console)
    return cid


def request_of(day: Day, card_id: str) -> dict | None:
    """The request filed about this card, in whatever state it is now."""
    return next((row for row in requests.listing(day.board, everything=True) if row.get("card") == card_id), None)


def bosun_fix(day: Day, blocked: str) -> str:
    """Bosun takes the request, files the fix as a personal card in Keel's repo, and it
    lands; each step
    only from the state before it."""
    request = request_of(day, blocked)
    if request is None:
        raise SeedError(f"{blocked} has no request for Bosun to take")
    day.at(day.ago(minutes=40))
    if request["state"] == "open":
        requests.take(day.board, request["id"], "bosun")
    cid = filed(day, "personal", FIX_TITLE, actor="bosun", brief=f"From {request['id']}: {texts.CACHE_BLOCK}",
                autonomy="autonomous", repo="keel", model="opus")
    if requests.get(day.board, request["id"])["state"] == "taken":
        requests.resolve(day.board, request["id"], "bosun", "filed", "publishable-clone",
                         "the check asked api's clone for web's branch", card=cid)
    if stage_of(day, cid) == "inbox":
        day.board.stage(cid, "assigned", "bosun")
    if stage_of(day, cid) == "assigned":
        day.board.stage(cid, "building", "drain")
    if stage_of(day, cid) == "building":
        ctx = day.card_dir(cid) / "context.md"
        ctx.write_text(texts.BOSUN_FIX.format(card=cid))
        day.at(day.ago(minutes=22))
        day.board.stage(cid, "review", "house", plan_ref=str(ctx), output_ref="next")
    if stage_of(day, cid) == "review":
        day.at(day.ago(minutes=15))
        day.board.stage(cid, "done", "human", note="approved and landed on next")
    return cid


FAKE_SHA = "5c1d0e7a9b24f3c68e1a0d9f7b3c2e4a6d8f0b1c"


def deploy_question(day: Day, fix: str) -> dict:
    for row in deployask.rows_for(day.board, "keel"):
        return row          # the newest: open, or answered on an earlier run of the day
    day.at(day.ago(minutes=12))
    return deployask.raise_deploy(day.board, {"repo": "keel", "space": "personal", "target": "next",
                                              "trunk": "main", "sha": FAKE_SHA, "cards": [fix]})


def breaks(day: Day) -> dict:
    blocked = refused(day)
    fix = bosun_fix(day, blocked)
    ask = deploy_question(day, fix)
    return {"refused": blocked, "fix": fix, "ask": ask["id"]}


# ----- evening (scene 10) -----

def approve_outcome(day: Day, card_id: str) -> None:
    card = day.board.get(card_id)
    if card["stage"] == "review":
        day.board.approve(card_id, "outcome", "human", publish=adapters.publisher(day.cfg, card["space"]))


def evening(day: Day) -> dict:
    day.live()
    parallel.reviews_at_gate(day)
    for card in day.board.list_cards(space="work", stage="review"):
        if (card["options"] or {}).get("review_key"):
            approve_outcome(day, card["id"])
    plan = day.card(PLAN_TITLE)
    if plan and plan["stage"] == "planning":
        day.board.approve(plan["id"], "plan", "human")
    for row in deployask.rows_for(day.board, "keel"):
        if row["state"] == "open":
            asks_answer(day, row["id"])
    cache = day.card(CACHE_TITLE)
    if cache and cache["stage"] not in ("done", "shipping"):
        cache_ships(day, cache)
    export = day.card(EXPORT_TITLE)
    if export:
        approve_outcome(day, export["id"])
    parallel.cards_through(day)
    return {}


def evening_done(day: Day) -> bool:
    """The day already reached the evening: the deploy question was answered."""
    return any(row["state"] == "answered" for row in deployask.rows_for(day.board, "keel"))


def asks_answer(day: Day, aid: str) -> None:
    from keel import asks  # noqa: PLC0415
    asks.answer(day.board, aid, "human", letter="A")
    deployask.record(day.board, aid, deployask.DEPLOYED, "deployed: main is at next", sha=FAKE_SHA)


def cache_ships(day: Day, card: dict) -> None:
    """After the deploy the refused card reaches review, is approved, and both merge."""
    if card.get("blocked_reason"):
        day.board.unblock(card["id"], "human")
    card = day.board.get(card["id"])
    if card["stage"] == "building":
        for repo in ("api", "web"):
            spec = code.CACHE if repo == "api" else code.CACHE_WEB
            pr = sb_host.find_open(repo, spec["branch"]) or sb_host.open_pr(
                repo, f"feature: {CACHE_TITLE} [st-104]", spec["branch"], "main", CACHE_TITLE)
            card = sb_card.record_pr(card, repo, pr["number"], kb=BoardKb(day))
        ctx = day.card_dir(card["id"]) / "context.md"
        ctx.write_text(f"---\nkind: outcome\ncard: {card['id']}\ntitle: {CACHE_TITLE}\nrepo: api, web\n---\n"
                       f"# {CACHE_TITLE}\n\nThe list is cached for a minute, and the page says when it loaded.\n")
        day.board.stage(card["id"], "review", "house", plan_ref=str(ctx), output_ref=sb_host.url("api", card["options"]["pr"]))
        approve_outcome(day, card["id"])
    card = day.board.get(card["id"])
    for entry in sb_card.prs_of(card):
        merge(entry["repo"], entry["branch"], entry["pr"], day.now)
        sb_host.set_state(entry["repo"], entry["pr"], "merged")
    if card["stage"] == "shipping":
        day.board.note(card["id"], "both pull requests merged", "drain")
        day.board.stage(card["id"], "done", "drain")
