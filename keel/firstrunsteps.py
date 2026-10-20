"""How each first-run step reads as done (c-632, c-678): one function per core step.

`keel/firstrun.py` holds the steps, their order, the file a Skip and a Finish are kept in,
the report and the verbs. This is what it asks for each step: `(cfg, ready, board) ->
(done, why)` or `(done, why, extra)`, where `extra` goes onto the step's entry in the
report (`STATE`, `core_state`), and `pack_state` for a step a pack adds. Done is always
read, from the readiness rows and from what is there, never stored. Moved out of
`keel/firstrun.py` in c-678, when it passed the size a module is kept to.

Several of these read something that costs: the tier drafts, the browser's folder, Bosun's
transcripts, the backup's files. `firstrun.report` therefore skips every step that is not
required when the first run is finished and the page asking is not the Start view.
"""

from __future__ import annotations

from datetime import datetime

from keel import backupstatus, bosunhello, browserinstall, builder, login, onboarding, packdraft, packs, readiness
from keel import bases, merging, receipt, tierdrafts
from keel.board import proposals_of
from keel.config import Config

FIRST_CARD_SEEN = 20
# A card the user filed counts for First card once it has reached one of these.
REVIEWED = ("review", "shipping", "done")


def rows_of(ready: dict, names, spaces=None) -> list[dict]:
    """The readiness rows `names` of the install, or of each space in `spaces`."""
    if spaces is None:
        return [ready["install"][name] for name in names if name in ready["install"]]
    return [ready["spaces"][space][name] for space in spaces for name in names
            if name in ready["spaces"].get(space, {})]


def verdict(rows: list[dict], done_why: str) -> tuple[bool, str]:
    missing = [r["why"] for r in rows if not r["ready"]]
    if missing:
        return False, "; ".join(dict.fromkeys(missing))
    return True, done_why


def first_card(board) -> tuple[dict | None, bool]:
    """The newest card the user filed (not a tier proposal, not the import), and
    whether any such card has reached review."""
    if board is None:
        return None, False
    mine = [card for card in board.filed_by("human", FIRST_CARD_SEEN)
            if not proposals_of(card.get("options"))        # a tier's or a flow's, draft cards too
            and card.get("title") not in (onboarding.IMPORT_TITLE, packdraft.CONNECTION_TITLE)]
    return (mine[0] if mine else None), any(card["stage"] in REVIEWED for card in mine)

# The two forms of step 0 (c-678, decision `forms`): how the page names `[builder] mode`.
FORMS = {"bypass": "full", "auto": "guide"}
FORM_NAMES = {"full": "Full builder", "guide": "Guide builder"}


def chosen(cfg: Config) -> str | None:
    """The builder form the config names, `full` or `guide`, or None: builder mode is off,
    or the config's `[builder]` names no `mode` yet. Neither form is preselected (decision
    `preselect`), so a new install's config names none and the step waits for the pick; an
    install whose config already names one is read as having chosen it."""
    if builder.status(cfg) is None:
        return None
    return FORMS.get(str((cfg.builder or {}).get("mode")))


def chosen_state(cfg: Config, ready: dict, board) -> tuple[bool, str, dict]:
    """Choose your builder: done once the config names a form, read as it is."""
    form = chosen(cfg)
    if builder.status(cfg) is None:
        return False, "builder mode is off: choose a builder to turn it on", {"choice": None}
    if form is None:
        return False, "no builder is chosen yet", {"choice": None}
    return True, FORM_NAMES[form], {"choice": form}


def bosun_up(cfg: Config) -> bool:
    """Bosun's session is listed by the harness, as the deck's own entry says it
    (`console.view`, read at most every few seconds)."""
    from keel import console         # noqa: PLC0415 - as readiness's builder row
    try:
        view = console.view(cfg)
    except console.ConsoleError:
        return False
    return bool(view and view.get("up"))


def bosun_state(cfg: Config, ready: dict, board) -> tuple[bool, str, dict]:
    """Meet Bosun (c-678): the builder could start, its session runs, and the user has said
    something in it (`keel/bosunhello.py`). The last two ride on the step for its screen."""
    done, why = verdict(rows_of(ready, ("builder",)), "the builder is ready")
    seen = {"running": bosun_up(cfg), "hello": bosunhello.said(cfg)}
    if not done:
        return False, why, seen
    if not seen["running"]:
        return False, "Bosun is not running yet", seen
    if not seen["hello"] and bosunhello.hidden(cfg):
        # review F20: a session Keel cannot read (a Bosun under another user) can never show
        # a hello, so the step is not held on one: done, and not confirmed (`sure` false)
        return True, ("Bosun is running. Shipyard cannot see into its session from here, so it cannot tell "
                      "whether you have said hello"), dict(seen, hidden=True, sure=False)
    if not seen["hello"]:
        return False, "Bosun is running: say hello in its session", seen
    return True, "Bosun is running and has your first message", seen


def login_state(cfg: Config, ready: dict, board) -> tuple[bool, str, dict]:
    """Sign in to Claude: the readiness row itself, its sentence too, so a login that could
    not be checked does not block (as the drain does not) and never reads as one that works.
    Such a step is done for Next and Finish and carries `sure: False`, so the deck says it
    as not confirmed: no "Done", no done colour, and the log-in command still shown."""
    row = ready["install"]["login"]
    space = readiness.login_space(cfg)
    # `seen` and `stamp` (c-678): the sign-in file in the install's Claude folder, and when it
    # last changed. The page watches them on every state, and asks for the one probe when a
    # sign-in appears.
    stamp = login.signin_stamp(cfg.spaces[space].config_dir) if space is not None else None
    return row["ready"], row["why"], dict({"sure": False} if row.get("sure") is False else {},
                                          seen=stamp is not None, stamp=stamp)


def repos_state(cfg: Config, ready: dict, board) -> tuple[bool, str]:
    """Add your repos (c-678): done once any space has a repo of the user's. The repos go in
    a space of their own, so personal, which holds only the install's packs, waits for none."""
    have = [row["why"] for row in rows_of(ready, ("repos",), list(cfg.spaces)) if row["ready"]]
    return (True, "; ".join(have)) if have else (False, "no repo is added yet")


def rules_state(cfg: Config, ready: dict, board) -> tuple[bool, str, dict]:
    """Set up your repos with Bosun (c-678): done once every copied repo's CLAUDE.md is
    adopted (`tierdrafts.verdict`; the workspace file is not required). The light rows ride
    on the step, so the page's list follows Bosun's moves on every state."""
    found = tierdrafts.every(cfg, board, full=False)
    done, why = tierdrafts.verdict(found)
    return done, why, {"drafts": found}


LOCAL = "work is merged on this computer, and pushed when you say"


def integrations_state(cfg: Config, ready: dict, board) -> tuple[bool | None, str]:
    """A space on a pack is done when its pack's rows are ready. A space with none ships by
    the merge on this computer and the Push (c-678, `keel/landpush.py`), which needs nothing
    set up: with no pack anywhere there is nothing to check. A connection Bosun is drafting,
    or one it drafted that is not turned on, is not done and says so (c-758, `draft_waiting`)."""
    waiting = draft_waiting(cfg, board)
    packed = [name for name in cfg.spaces if cfg.spaces[name].adapter_dir is not None]
    if not packed:
        return (False, waiting) if waiting else (None, LOCAL)
    rows = [row for name in packed for row in rows_of(ready, readiness.wanted(cfg.spaces[name]), [name])]
    done, why = verdict(rows, "every connection that is turned on is set up")
    if not waiting:
        return done, why
    # r1.F10: a draft for one space never hides what another space's connection still needs
    return False, waiting if done else f"{waiting}; {why}"


def draft_waiting(cfg: Config, board) -> str | None:
    """Why Where finished work goes is not done while a connection draft stands (c-758), or
    None: Bosun is still drafting one for a space on no connection, or the one it drafted has
    landed, is still offered, and the space it was for is on none. The user's way past either
    is Skip, which keeps work on this computer, and both sentences say so. It lets go when the
    space is on a connection, is no longer in the config, or (landed) names no space or a
    connection that no longer loads, and for an archived card. Read light (`packdraft.standing`,
    r1.F9): this runs on every state build."""
    if board is None:
        return None
    found = packdraft.standing(board, cfg)
    going = found["open"]
    if going and (going["space"] is None or going["space"] in cfg.spaces) and not on_connection(cfg, going["space"]):
        where = f" for {going['space']}" if going["space"] else ""
        return (f"Bosun is drafting a connection{where} ({going['card']}); until it has landed and you "
                f"turn it on, work is merged on this computer: skip this step to carry on meanwhile")
    space, name = found["space"], found["pack"]
    if (found["done"] and name and space in cfg.spaces and not on_connection(cfg, space)
            and offered(cfg, name)):
        return (f"the connection Bosun drafted ({name}, {found['done']}) has landed and is not turned on "
                f"for {space}: turn it on, or skip this step to keep work on this computer")
    return None


def on_connection(cfg: Config, space: str | None) -> bool:
    found = cfg.spaces.get(space or "")
    return found is not None and found.adapter_dir is not None


def offered(cfg: Config, name: str) -> bool:
    """Whether a connection of that name still loads from where connections are looked for."""
    try:
        packs.find(name, cfg.root)
    except packs.PackError:
        return False
    return True


def ships_state(cfg: Config, ready: dict, board) -> tuple[None, str, dict]:
    """How work ships has nothing to check: the usual path stands until a draft is adopted, and
    the step is done by going on past it (Next, Keep how it works now), never by a conversation.
    It carries `plans`, whether a new card of each space stops at its plan for the user
    (`[spaces.<name>] autonomy` is attended), for the step's one question."""
    plans = {name: space.autonomy == "attended" for name, space in cfg.spaces.items()}
    return None, "question 1 is answered here; the rest is already set by what you chose, and changing it is optional", {
        "plans": plans, "asks": [dict(one) for one in bases.ASKS],
        "bases": {name: bases_of(cfg, space) for name, space in cfg.spaces.items()}}


def bases_of(cfg: Config, space) -> dict:
    """c-732: a space's answer to "Where does work start?": its bases, the branch to suggest
    when it names none (its first repo's usual branch, `merging.usual_branch`: a copy's remote
    default, c-734, never the branch the copy has out), and `pack`, true
    where the space's pack lists its own and the page only shows them. A space whose repos
    all land on an integration branch is offered no bases (r1.F4, F5): `integration` names that
    branch, which is suggested and drawn, since it is where its cards are cut and land. In a
    space where only some do, the others are offered bases, suggested from the first of them
    (r2.F4), and the card form shows the row only for a card on those."""
    skip = bases.integrated(cfg, space)
    if skip and len(skip) == len(space.repos):
        integration = cfg.integration_of(space.name, skip[0])
        return {"bases": [], "suggested": integration, "pack": False, "listed": False, "integration": integration}
    suggested = None
    for path in [path for key, path in space.repos.items() if key not in skip][:1]:
        try:
            suggested = merging.usual_branch(cfg, space.name, path) if (path / ".git").exists() else None
        except merging.MergeRefused:
            suggested = None
    suggested = suggested if suggested and suggested != "HEAD" else None
    # r1.F1: a pack with a base field of its own, whatever its type, keeps it; the page only says so.
    # r2.F5: `listed`, only where that field is a select of its own branches, which the page names
    own = bases.pack_row(space)
    # c-734 (12): a pack's free-text field takes the space's bases, so only a select of its own is the pack's
    return {"bases": bases.of(space), "suggested": suggested, "pack": bases.own(own),
            "listed": bases.own(own), "integration": None}


def browser_state(cfg: Config, ready: dict, board) -> tuple[bool, str, dict]:
    """A browser for sessions (c-678): done when Keel's browser is in its folder. The step
    carries `node` (Node.js 20 or newer) and `install`, the download as it stands now
    (`keel/browserinstall.py`), read on every state so the page shows it moving."""
    found = browserinstall.status(cfg)
    done = found["state"] == "ready"
    # c-757: a download in flight is said as that, not as a browser that is not installed
    why = ("Shipyard's browser is installed" if done else "Shipyard's browser is downloading"
           if found["state"] == "downloading" else "Shipyard's browser is not installed")
    # Node's version is asked of the real tool, so it is kept like the other slow readings;
    # asked through `browserinstall.probe`, the seam the suite's fence replaces
    return done, why, {"install": found, "node": readiness.kept(("browser-node",), lambda: browserinstall.probe())}


def backup_state(cfg: Config, ready: dict, board) -> tuple[bool, str, dict]:
    """Back up (c-678, c-757): the step carries `backup`, the store and what is observed of
    it (`backupstatus.status`, at the board's clock), read on every state. Done once the
    first copy is written. On with the copy still being written is done for Next and not
    confirmed (`sure: False`, with `word` for the step list); on with a run that failed, or
    a copy that never started, is not done (`backupstatus.verdict`)."""
    now = datetime.fromisoformat(board.now()) if board is not None else None
    return backupstatus.verdict(backupstatus.status(cfg, now))


def first_card_state(cfg: Config, ready: dict, board) -> tuple[bool, str, dict]:
    """Your first card (c-678): done once a card the user filed has reached review. The step
    carries `card`, what the path on the page cannot read off the state's own card (the
    block a refused landing left), and, while no card is filed, `suggestion`: the card Bosun
    noted while drafting an adopted file. The Push a local landing offers is NOT here: it
    reads git, so it comes with the card's own detail (`deckstate`, `landpush.offer`), which
    the screen asks for once the card has landed (review F11)."""
    card, done = first_card(board)
    follow = {"card": {"id": card["id"], "title": card["title"], "stage": card["stage"], "space": card["space"],
                       "blocked": (receipt.refused_block(card) or "").splitlines()[0] or None
                       if receipt.refused_block(card) else None}} if card else {}
    if not card and board is not None:
        found = tierdrafts.suggestion(cfg, board)
        if found:
            follow["suggestion"] = found
    if done:
        return True, "a card you filed has reached review", follow
    if card:
        return False, f"your card {card['id']} is at {card['stage']}; it counts once it reaches review", follow
    return False, "no card filed yet", follow


# How each core step reads as done: `(cfg, ready, board) -> (done, why)` or `(done, why,
# extra)`, where `extra` goes onto the step's entry in the report. A step's entry in `STEPS`
# has one here.
STATE = {
    "choose-builder": chosen_state,
    "prerequisites": lambda cfg, ready, board: verdict(rows_of(ready, ("prerequisites",)),
                                                       "everything Shipyard needs is installed"),
    "login": login_state,
    "builder": bosun_state,
    "repos": repos_state,
    "memory": lambda cfg, ready, board: (None, "nothing to decide here: read it, then go on"),
    "rules": rules_state,
    "integrations": integrations_state,
    "defaults": ships_state,
    "browser": browser_state,
    "backup": backup_state,
    "first-card": first_card_state,
    "set-up": lambda cfg, ready, board: (None, "nothing to check here: this is where to go from now on"),
}


def core_state(cfg: Config, step: str, ready: dict, board) -> tuple[bool | None, str, dict]:
    """`(done, why, extra)` of one core step, from its entry in `STATE`."""
    done, why, *extra = STATE[step](cfg, ready, board)
    return done, why, (extra[0] if extra else {})


def pack_state(cfg: Config, pack: packs.Pack, own: packs.SetupStep, spaces: list[str],
               ready: dict) -> tuple[bool, str]:
    """A pack step is done when every check it names passes and every capability it is for
    is ready, in every space on the pack."""
    missing = []
    for name in spaces:
        results = {check["name"]: check for check in
                   readiness.pack_checks(cfg, cfg.spaces[name], pack)}
        for need in own.requires:
            check = results.get(need)
            if check is None or not check["ok"]:
                missing.append(f"{need} is not set up" + (f": {check['why']}" if check else ""))
        missing += [ready["spaces"][name][cap]["why"] for cap in own.serves
                    if not ready["spaces"][name][cap]["ready"]]
    if missing:
        return False, "; ".join(dict.fromkeys(missing))
    return True, "every check it needs passes"


