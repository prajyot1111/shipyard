"""The sandbox adapter's entry points: one function per executable, each printing what the
engine reads and exiting 1 with one line on stderr when it cannot.

The executables beside this file (`worktree`, `brief`, `deny`, `pr`, `publishable`,
`publish`, `act`, `ship`, `review`, `providers/reviews`) are three lines each: they put this
directory on the path and call `run(<verb>, argv)`.
"""

import json
import sys

import sb_brief
import sb_cut
import sb_host
import sb_pulls
import sb_sight
import sb_tracker
from sb_card import (KB, SandboxError, as_json, keel_config, load_card, option, prs_of, served_space,
                     story_of)


def stdin_json(default):
    raw = sys.stdin.read() if not sys.stdin.isatty() else ""
    return json.loads(raw) if raw.strip() else default


def worktree(argv):
    if len(argv) != 1:
        raise SandboxError("usage: worktree <card-id>")
    for path in sb_cut.worktrees_for(load_card(argv[0])):
        print(path)


def brief(argv):
    if len(argv) != 1:
        raise SandboxError("usage: brief <card-id>")
    card = load_card(argv[0])
    trees = [str(path) for path in sb_cut.worktrees_for(card)] if card.get("repo") else ["<no worktree>"]
    print(sb_brief.compose(load_card(argv[0]) if card.get("repo") else card, trees))


def deny(argv):
    if len(argv) != 1:
        raise SandboxError("usage: deny <card-id>")
    card = stdin_json(None) or load_card(argv[0])
    print(json.dumps(sb_brief.deny_for(card)))


def pr(argv):
    if not argv or len(argv) > 2 or (len(argv) == 2 and argv[1] not in ("--draft", "--ready")):
        raise SandboxError("usage: pr <card-id> [--draft|--ready]")
    card = load_card(argv[0])
    sb_pulls.refuse_unless_shipping_tap(card, "pr")
    if argv[1:] == ["--ready"]:
        for one in sb_pulls.make_ready(card):
            print(one["url"])
        return
    result = sb_pulls.open_drafts(card)
    for one in result["opened"]:
        print(one["url"])
    for one in result["skipped"]:
        print(f"pr: skipped {one['repo']}: {one['why']}", file=sys.stderr)


def publishable(argv):
    if len(argv) != 1:
        raise SandboxError("usage: publishable <card-id>")
    card = stdin_json(None) or load_card(argv[0])
    why = sb_pulls.missing(card)
    print(json.dumps({"publishable": True} if why is None else {"publishable": False, "missing": why}))


def publish(argv):
    if len(argv) not in (1, 2) or (len(argv) == 2 and argv[1] != "--answer"):
        raise SandboxError("usage: publish <card-id> [--answer]")
    answer = json.loads(sys.stdin.read() or "null") if len(argv) == 2 else None
    print(as_json(sb_pulls.publish(load_card(argv[0]), answer)))


# ----- act -----

def links_for(card: dict) -> dict:
    out = {}
    number = sb_tracker.number_of(story_of(option(card, "tracker_ref")))
    if number:
        out["story"] = sb_tracker.url(number)
    pulls = [{"repo": e["repo"], "pr": e["pr"], "url": sb_host.url(e["repo"], e["pr"])}
             for e in prs_of(card)]
    if pulls:
        out["pr"], out["prs"] = pulls[0]["url"], pulls
    unpublished = sb_pulls.unpublished(card)
    if unpublished:
        out["unpublished"] = unpublished
    return out


def act_do(route: str, verb: str, args: dict) -> dict:
    """The Reviews gear's two settings, written through Keel's own module; nothing else."""
    if route != "reviews" or verb not in ("set_auto_review", "set_review_model"):
        raise SandboxError(f"no verb {verb!r} on route {route!r}")
    from keel import reviewsettings  # noqa: PLC0415 - Keel's module, on the path via keel_config
    cfg = keel_config()
    key = "auto" if verb == "set_auto_review" else "model"
    value = str(args.get("value") or "").strip()
    try:
        after = reviewsettings.write(cfg, served_space(cfg), key, value)
    except ValueError as error:
        raise SandboxError(str(error)) from None
    return {"ok": True, "settings": after, "message": f"{key} set to {value}"}


def act(argv):
    if argv[:1] == ["verbs"]:
        print(json.dumps({"card": []}))
    elif argv[:1] == ["links"]:
        wanted = set(argv[1:])
        found = {card["id"]: links_for(card) for card in KB.cards() if card["id"] in wanted}
        print(json.dumps({key: value for key, value in found.items() if value}))
    elif argv[:1] == ["do"] and len(argv) in (3, 4):
        print(json.dumps(act_do(argv[1], argv[2], stdin_json({}))))
    else:
        raise SandboxError("usage: act verbs | act links <id>... | act do <route> <verb> [key]")


def providers_reviews(argv):
    if argv:
        raise SandboxError("providers/reviews takes no arguments")
    from keel import reviewsettings  # noqa: PLC0415
    cfg = keel_config()
    found = reviewsettings.effective(cfg, served_space(cfg))
    verbs = [{"verb": "set_auto_review", "label": "Auto review", "to": None},
             {"verb": "set_review_model", "label": "Review model", "to": None}]
    settings = {"verbs": verbs, "auto_review": bool(found["auto"]), "review_model": found["model"],
                "models": list(reviewsettings.REVIEW_MODELS)}
    print(json.dumps({"route": "reviews", "settings": settings, "columns": [], "hidden": 0, "items": []}))


# ----- ship and review -----

def ship(argv):
    if argv == ["mine"]:
        print(as_json(sb_sight.mine(stdin_json([]))))
        return
    if len(argv) == 2 and argv[1] == "method":
        sys.stdout.write(sb_brief.METHOD)
        return
    actions = {"poll": lambda c: print(as_json(sb_sight.sight(c))),
               "diff": lambda c: sys.stdout.write(sb_sight.diff(c)),
               "down": lambda c: print(as_json(sb_sight.down(c))),
               "reap": lambda c: print(as_json(sb_sight.reap(c)))}
    if len(argv) != 2 or argv[1] not in actions:
        raise SandboxError(f"usage: ship <card-id> {'|'.join([*actions, 'method'])}, or ship mine")
    actions[argv[1]](load_card(argv[0]))


def review(argv):
    if argv == ["scan"]:
        print(as_json(sb_sight.scan()))
    elif len(argv) >= 2 and argv[0] == "branches":
        print(as_json(sb_sight.branches(argv[1], argv[2:])))
    elif len(argv) == 2 and argv[0] == "story":
        print(as_json(sb_sight.story(argv[1])))
    elif len(argv) == 2 and argv[1] == "poll":
        print(as_json(sb_sight.poll(load_card(argv[0]))))
    else:
        raise SandboxError("usage: review scan | review <card-id> poll | review branches <story> <repo>... "
                           "| review story <story>")


VERBS = {"worktree": worktree, "brief": brief, "deny": deny, "pr": pr, "publishable": publishable,
         "publish": publish, "act": act, "ship": ship, "review": review, "providers/reviews": providers_reviews}


def run(verb: str, argv: list[str]) -> int:
    try:
        VERBS[verb](argv)
    except (SandboxError, ValueError) as error:
        print(f"{verb}: {error}", file=sys.stderr)
        return 1
    return 0
