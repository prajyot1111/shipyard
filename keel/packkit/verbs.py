"""A pack's entry points: one function per executable, each printing what the engine reads
and exiting 1 with ONE line on stderr when it cannot.

Each executable in a pack on the kit is a shim of a few lines: it puts its own folder and
Keel (`KEEL_HOME`) on the path and calls `run(<verb>, argv, pack=<its folder>, layer=<its
layer module>)`, so the kit runs for that pack (`pack.bind`). The pack's `guard` calls
`guard.main` instead, so that it loads no more than it reads. No failure leaves here as a
traceback: a refusal, the host's or git's own message, a timeout and anything unforeseen are
all one sentence after the verb's name.
"""

import importlib
import json
import subprocess
import sys

from keel.packkit import brief as kit_brief
from keel.packkit import card as gc
from keel.packkit import cut, pulls, review, sight
from keel.packkit import pack as kitpack
from keel.packkit.errors import HostError


def stdin_json(default):
    raw = sys.stdin.read() if not sys.stdin.isatty() else ""
    return json.loads(raw) if raw.strip() else default


def worktree(argv):
    if len(argv) != 1:
        raise HostError("usage: worktree <card-id>")
    for path in cut.worktrees_for(gc.load_card(argv[0])):
        print(path)


def brief(argv):
    if len(argv) != 1:
        raise HostError("usage: brief <card-id>")
    card = gc.load_card(argv[0])
    if not gc.repos_of(card):
        print(kit_brief.compose(card, ["<no worktree>"]))
        return
    trees = [str(path) for path in cut.worktrees_for(card)]
    print(kit_brief.compose(gc.load_card(argv[0]), trees))


def pr(argv):
    if argv[1:] == ["--ready"]:
        # r1.F2, r1.F3: nothing in the engine runs it; Approve outcome's `publish` marks a draft
        # ready in its own process, so the verb refuses it to everyone, guard or no guard
        raise HostError(f"marking a {kitpack.words().change} ready is Approve outcome's, through this pack's "
                        f"`publish`, which Shipyard runs itself: `pr` takes `--draft` or `--body`")
    if not argv or len(argv) > 2 or (len(argv) == 2 and argv[1] not in ("--draft", "--body")):
        raise HostError("usage: pr <card-id> [--draft|--body]")
    card = gc.load_card(argv[0])
    pulls.refuse_unless_shipping_tap(card, "pr")
    if argv[1:] == ["--body"]:
        done = pulls.refresh_bodies(card)
    else:
        result = pulls.open_drafts(card)
        done = result["opened"]
        for one in result["skipped"]:
            print(f"pr: skipped {one['repo']}: {one['why']}", file=sys.stderr)
    for one in done:
        print(one["url"])


def publishable(argv):
    if len(argv) != 1:
        raise HostError("usage: publishable <card-id>")
    card = stdin_json(None) or gc.load_card(argv[0])
    why = pulls.missing(card)
    print(json.dumps({"publishable": True} if why is None else {"publishable": False, "missing": why}))


def publish(argv):
    if len(argv) not in (1, 2) or (len(argv) == 2 and argv[1] != "--answer"):
        raise HostError("usage: publish <card-id> [--answer]")
    nonce = pulls.take_nonce()           # before `kb show` or anything else is started (r2.F2)
    answer = json.loads(sys.stdin.read() or "null") if len(argv) == 2 else None
    print(gc.as_json(pulls.publish(gc.load_card(argv[0]), answer, nonce=nonce)))


# ----- ship -----

def spaces_on_pack(cards: list[dict]) -> list[str]:
    """The spaces `ship mine` reads: the one on this pack, or, with several, the ones that
    list a repo the handed cards name (the verb is told no space)."""
    cfg = gc.keel_config()
    mine = gc.on_pack(cfg)
    if len(mine) <= 1:
        return mine
    named = {key for card in cards if isinstance(card, dict) for key in gc.repos_of(card)}
    return [name for name in mine if named & set(cfg.spaces[name].repos)]


def ship(argv):
    if argv == ["mine"]:
        cards, rows = stdin_json([]), []
        for space in spaces_on_pack(cards):
            rows += sight.mine(cards, space)["prs"]
        print(gc.as_json({"prs": rows}))
        return
    if len(argv) == 2 and argv[1] == "method":
        sys.stdout.write(kit_brief.method())
        return
    actions = {"poll": lambda card: print(gc.as_json(sight.sight(card))),
               "diff": lambda card: sys.stdout.write(sight.diff(card)),
               "down": lambda card: print(gc.as_json(sight.down(card))),
               "reap": lambda card: print(gc.as_json(sight.reap(card)))}
    if len(argv) != 2 or argv[1] not in actions:
        raise HostError(f"usage: ship <card-id> {'|'.join([*actions, 'method'])}, or ship mine")
    actions[argv[1]](gc.load_card(argv[0]))


# ----- act: no card verbs, and the links the deck draws -----

def links_for(card: dict, slugs: dict | None = None) -> dict:
    """`{pr, prs, unpublished}` from the card and its clones' addresses: nothing is asked
    of the host, so the deck's every state build stays off the network. `slugs` keeps each
    repo's address for one `act links`, which is asked for every card on the deck."""
    out, pulled, slugs = {}, [], {} if slugs is None else slugs
    for entry in gc.prs_of(card):
        key = (card.get("space"), entry["repo"])
        if key not in slugs:
            try:
                slugs[key] = gc.host_repo(card, entry["repo"])
            except HostError:
                slugs[key] = None           # a repo with no address on the host has no link
        if slugs[key]:
            pulled.append({"repo": entry["repo"], "pr": entry["pr"],
                           "url": kitpack.host().pr_url(slugs[key], entry["pr"])})
    if pulled:
        out["pr"], out["prs"] = pulled[0]["url"], pulled
    unpublished = pulls.unpublished(card)
    if unpublished:
        out["unpublished"] = unpublished
    return out


def act(argv):
    if argv[:1] == ["verbs"]:
        print(json.dumps({"card": []}))
    elif argv[:1] == ["links"]:
        wanted, slugs = set(argv[1:]), {}
        found = {card["id"]: links_for(card, slugs) for card in gc.KB.cards() if card["id"] in wanted}
        print(json.dumps({key: value for key, value in found.items() if value}))
    elif argv[:1] == ["do"] and len(argv) in (3, 4) and argv[1] == "reviews":
        print(json.dumps(review_route(argv[2], stdin_json({}))))
    elif argv[:1] == ["do"]:
        raise HostError("this pack has no card verbs")
    else:
        raise HostError("usage: act verbs | act links <id>... | act do reviews <verb>")


# ----- review: the drain's review cards (c-730, review.py) -----

def review_verb(argv):
    if argv == ["scan"]:
        print(gc.as_json(review.scan()))
    elif len(argv) == 2 and argv[1] == "poll":
        print(gc.as_json(review.poll(gc.load_card(argv[0]))))
    else:
        raise HostError("usage: review scan | review <card-id> poll")


REVIEW_VERBS = (("set_auto_review", "Auto review", "auto"), ("set_review_model", "Review model", "model"),
                ("scan_now", "Scan now", None))


def review_settings() -> tuple:
    cfg = gc.keel_config()           # first: it puts Keel on the path (KEEL_HOME)
    from keel import reviewsettings  # noqa: PLC0415 - Keel's own module
    return reviewsettings, cfg, review.space_named()


def providers_reviews(argv):
    """The Reviews page's gear: the space's two settings, as Keel's drain reads them."""
    if argv:
        raise HostError("providers/reviews takes no arguments")
    module, cfg, space = review_settings()
    found, scans = module.effective(cfg, space), module.scan_state(cfg, space)
    settings = {"verbs": [{"verb": verb, "label": label, "to": None} for verb, label, _ in REVIEW_VERBS],
                "auto_review": bool(found["auto"]), "review_model": found["model"],
                "models": list(module.REVIEW_MODELS), "scan_asked": "asked" in scans}
    if scans.get("last"):
        settings["last_scan"] = scans["last"]
    print(json.dumps({"route": "reviews", "settings": settings, "columns": [], "hidden": 0, "items": []}))


def review_route(verb: str, args: dict) -> dict:
    """The gear's two settings and Scan now, written through Keel's own module."""
    module, cfg, space = review_settings()
    key = next((key for name, _, key in REVIEW_VERBS if name == verb), "")
    if key == "":
        raise HostError(f"no review verb {verb!r}; one of {', '.join(name for name, _, _ in REVIEW_VERBS)}")
    if key is None:
        module.ask_scan(cfg, space)
        return {"ok": True, "message": f"scan asked: the next drain pass looks for {kitpack.words().changes} "
                                       f"that wait on you"}
    value = str(args.get("value") or "").strip()
    return {"ok": True, "settings": module.write(cfg, space, key, value), "message": f"{key} set to {value}"}


# ----- what it needs, and its sign-in -----

def ready_module():
    """The pack's own requirement checks (`HostConfig.ready`): `NAMES`, `CHECKS`, `rows()`
    and `login_rows()`."""
    named = kitpack.host().ready
    if not named:
        raise HostError("this pack names no requirement checks (its HostConfig has no `ready`)")
    return importlib.import_module(named)


def logins(argv):
    if argv != ["check"]:
        raise HostError("usage: logins check")
    print(json.dumps({"logins": ready_module().login_rows()}))


def ready(argv) -> int:
    """`ready`: every requirement as JSON. `ready <name>`: that one, exit 0 when it is
    ready and 1 with its row when it is not (a `[[requires]]` check)."""
    checks = ready_module()
    if not argv:
        print(json.dumps(checks.rows(), indent=2))
        return 0
    if len(argv) != 1 or argv[0] not in checks.CHECKS:
        raise HostError(f"usage: ready [{'|'.join(checks.NAMES)}]")
    found = checks.CHECKS[argv[0]]()
    print(json.dumps(found))
    return 0 if found["ok"] else 1


VERBS = {"worktree": worktree, "brief": brief, "pr": pr, "publishable": publishable,
         "publish": publish, "ship": ship, "act": act, "logins": logins, "ready": ready,
         "review": review_verb, "providers/reviews": providers_reviews}


def run(verb: str, argv: list[str], pack=None, layer: str | None = None) -> int:
    """One verb for the pack in the folder `pack`, whose host layer is the module `layer`
    there; with neither, for the pack already bound (a pack's own tests bind theirs)."""
    try:
        if pack is not None:
            kitpack.bind(pack, layer or "")
        return VERBS[verb](argv) or 0
    except (HostError, ValueError) as error:
        print(f"{verb}: {' '.join(str(error).split())}", file=sys.stderr)
    except (OSError, subprocess.SubprocessError) as error:
        print(f"{verb}: {type(error).__name__}: {' '.join(str(error).split())[:200]}", file=sys.stderr)
    except Exception as error:  # noqa: BLE001 - a verb answers in one line, never a traceback
        print(f"{verb}: stopped on {type(error).__name__}: {' '.join(str(error).split())[:200]}",
              file=sys.stderr)
    return 1
