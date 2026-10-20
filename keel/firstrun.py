"""The first run (c-632, c-628 S4): the steps a new install walks, one per screen.

`STEPS` are the core steps in the approved order (c-677, the first-run design of c-668), and
the ONE place that names them: a step is an entry here, how it reads as done is its entry in
`STATE`, and its screen is its entry in the deck's `K.startPanels` (`app/ui.start.js`). The
design has thirteen places; the ones whose screen is not built yet have no entry, so a real
install never shows an empty step (`docs/atlas/89-onboarding.md` lists them and where each
goes). A pack on a space may add its own (`[[setup]]`, `keel/packs.py`): each sits after the
core step it names, Where finished work goes (`integrations`) unless it says, and its id
here is `<pack>:<id>`.

Check this computer and Sign in to Claude are the required steps (one step, Prerequisites,
until c-677); every other may be skipped (but Choose your builder, which has no Skip and is
not required: `Step.skip`, c-678), and a skipped step is not lost: it stays on the
list, and the page that needed it says so with its needs panel (c-631), whose Set it up opens
the step again. Every step from `BOSUN_FROM` (Meet Bosun) on carries `bosun`: the deck heads
those screens with its line to Bosun's session, while that session can run (readiness's
`builder`, `login` and `prerequisites` rows all ready; a login that could not be checked is
ready, an expired or missing one is not).

Whether a step is done is never stored. It is read each time from readiness
(`keel/readiness.py`), the config or the board, so a thing fixed by hand marks its step done
too. `state/firstrun.json` holds only `{"skipped": {step: at}, "finished": at | null}` (and
`reason` when it was written as finished for an install that predates the stepper), and
`seen` (c-729): `{step: at}` for a step with nothing to check the user has gone on past, which
then reads done (`SEEN` says why).

`report(cfg, board, ready)` is what `/api/state` carries as `firstrun`: each step's id,
title, `headline` (what heads its screen: the design's own, else the title), what it is for, whether it is required or optional, `bosun`, done (None
for How work ships, which has nothing to check), skipped and why, plus `finished`,
`redirect` and `untouched` (nobody has acted on a step yet, read from the file and the
steps and never stored: the deck then opens on the first step). The Sign in to Claude step
also carries `sure: False` while its login could not be checked, and `seen` and `stamp`,
whether the sign-in file is in the install's Claude folder and when it last changed (c-678:
the page watches for it). The deck opens Start in
place of Now while `redirect` is true: until Finish, and again whenever a required step
stops being met. A config that is not an install's never redirects and writes nothing.
`panels(cfg)` is what the screens show beyond that, on `/api/setup`.

The verbs (`VERBS`, page-only, run under the setup lock like Setup's):

- `firstrun.skip` {step}: refused for a required step.
- `firstrun.unskip` {step}.
- `firstrun.seen` {step}: the user went on past a step with nothing to check (c-729);
  refused for a step with a check of its own.
- `firstrun.finish` {}: refused while a required step is not done.
- `firstrun.reopen` {}: clears Finish, so the deck opens Start again.
- `firstrun.login.check` {space?}: probes the install's Claude login now (`login.check` with
  `force`), or the named space's (the sign-in banner, c-678), and drops the kept readings so
  the next state reads everything again.
- `firstrun.identity.save` {name, email}: the two fields of Check this computer (c-679).
  Writes git's global `user.name` and `user.email` (`prereqs.save_identity`) and drops the
  kept readings. It is the one verb here that writes outside the install, and only what the
  user typed, on their Save.
- `firstrun.browser.install` {}: starts the download of Keel's browser for sessions
  (`keel/browserinstall.py`), in a process of its own; the step reads how far it is.
- `firstrun.backup.on` {folder}: Back up's one verb (`keel/backupsetup.py`): the folder as
  the store, the keys, the two jobs and the first copy started, or nothing at all. Refused
  on a computer with no gpg (c-757). A config verb.
"""

from __future__ import annotations

import hashlib
import json
import threading
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path

from keel import atomicfile, backupsetup, browserinstall, builder, landpush, login, onboarding, packdraft, packs, prereqs
from keel import readiness, repolayout
from keel.config import Config
# How each step reads as done lives in `keel/firstrunsteps.py`; the two builder forms are
# named there too and are this module's as well (`firstrun.FORMS`, `firstrun.chosen`).
from keel.firstrunsteps import FORM_NAMES, FORMS, LOCAL, STATE, chosen, core_state, pack_state  # noqa: F401
from keel.setupconfig import SetupError, install_of, installed

FILE = "firstrun.json"
# Every read, change and write of the file, and its first write from a state read, hold this
# (c-628 review r1.F8): a Skip on a fresh install racing a GET /api/state never loses its
# skip to the initial record. Re-entrant: Finish reads the report, which reads the file.
_lock = threading.RLock()
EXISTING = "existing install"
@dataclass(frozen=True)
class Step:
    id: str
    title: str
    about: str                  # one line: what the step is for
    required: bool = False      # Next and Finish wait for it, and it has no Skip
    optional: bool = False      # the list says so: nothing else here depends on it
    headline: str = ""          # what heads the screen, where the design gives more than the title
    skip: bool = True           # False: no Skip, though the step is not one Finish waits for


# The approved order (c-677), thirteen places. Phone and voice has no place among them: it
# is on the last screen, under "More to set up later" (c-678).
STEPS = (
    Step("choose-builder", "Choose your builder",
         "Shipyard runs Claude sessions on cards: one card is one piece of work. One session is "
         "different. It is your builder: it stays with this install, guides you through setup, "
         "answers when you are stuck, and can build additions to Shipyard itself. Choose how much it "
         "may do on this computer. You can change this later in Settings, and nothing you set up "
         "is lost.", headline="First, choose how much your builder may do", skip=False),
    Step("prerequisites", "Check this computer",
         "Shipyard needs a few tools on this computer. The installer checked them once; this page keeps "
         "checking, so if one goes missing later you will see it here with its fix.", required=True),
    Step("login", "Sign in to Claude",
         "Shipyard keeps its own Claude sign-in in its own folder, so nothing here reads or changes the "
         "Claude setup you already use. That means one sign-in now, in a terminal, even if you are "
         "signed in to Claude elsewhere. It lasts about 30 days. When it runs out, Shipyard says so on "
         "every page with the way to sign in again.", required=True, headline="Sign Shipyard in to Claude"),
    Step("builder", "Meet Bosun",
         "Bosun is the builder you chose: one Claude session that stays with this install. From "
         "here on you talk to Bosun in its own session, not on this page. This page explains each "
         "step and checks the result. Bosun does the parts that depend on your code.",
         headline="Meet Bosun, your builder"),
    Step("repos", "Add your repos",
         "A repo is one project's code. Add as many as you have: for example an api repo and a web "
         "repo. Shipyard makes its own copy of each repo inside this install and works there, so the "
         "folders you already have are never touched. Your repos are kept together in a space, a "
         "group with its own rules and its own way of shipping. Yours is called work; rename it now "
         "if you like.", headline="Add the code you want worked on"),
    Step("memory", "How Shipyard remembers",
         "Every session Shipyard starts needs to know your code. It reads a small stack of plain files, "
         "top to bottom. This is the whole picture. Nothing on this page needs a decision.", skip=False),
    Step("rules", "Set up your repos with Bosun",
         "Bosun reads each repo and drafts its CLAUDE.md with you. It asks what it cannot see from "
         "the code. Nothing is written until you press Adopt."),
    Step("integrations", "Where finished work goes",
         "When you approve a card, its work has to get from this computer to where your team sees it. "
         "A connection does that: it opens your work on your team's code host, as you. Choose one of "
         "the ways below. This step picks the tool that carries work to your team's code host. Your "
         "team's process (which branches, who approves) is not asked here: that is How work ships, "
         "a later step.",
         headline="Where does finished work go?"),
    Step("defaults", "How work ships",
         "This page follows from the one before: it starts from what you chose there. You answer "
         "question 1 here: which branches work starts from. It applies when you press Save, to new "
         "cards only. The rest is already set by what you chose, and the page shows it. Changing "
         "it is optional: if your team works differently, Bosun asks a few questions and draws it "
         "again, and nothing changes until you press Adopt.",
         headline="How does your team ship its work?"),
    Step("browser", "A browser for sessions",
         "When a card changes a web page, a session can open the result in a private browser and "
         "take a screenshot as proof. That browser has no saved logins or cookies, so it can look at "
         "a page but can never be you on one. It is a one-time download, about 400 MB on disk, and it is "
         "used only in repos whose rules say how to run the app. Skip it if your repos have no web "
         "pages.", optional=True, headline="Give sessions a browser to look with"),
    Step("backup", "Back up",
         "Your board (every card, plan and outcome) lives only in this install. Your code is safe in "
         "git; the board is not. Shipyard can write an encrypted copy to a folder you choose, about "
         "every hour when something has changed. Pick one on another disk or in a synced folder if "
         "you can.", headline="Keep a copy of your board"),
    Step("first-card", "Your first card",
         "A card is one piece of work, written the way you would ask a colleague. Pick something "
         "small and real: a typo, a missing test, a README section. You will watch it go from your "
         "words to a change you approve.", headline="Give Shipyard one small piece of work"),
    Step("set-up", "You are set up",
         "From here you work on the board: file cards, answer plans, approve outcomes.", skip=False, headline="You are set up"),
)
CORE = tuple(step.id for step in STEPS)
BY_ID = {step.id: step for step in STEPS}
REQUIRED = tuple(step.id for step in STEPS if step.required)
BOSUN_FROM = "builder"          # Meet Bosun: from here on a screen points at Bosun's session


# ----- the store -----

def path_of(cfg: Config) -> Path:
    return Path(cfg.state_dir) / FILE


def now() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


def read_file(cfg: Config) -> dict | None:
    try:
        found = json.loads(path_of(cfg).read_text())
    except (OSError, ValueError):
        return None
    if not isinstance(found, dict):
        return None
    skipped, seen = found.get("skipped"), found.get("seen")
    out = {"skipped": dict(skipped) if isinstance(skipped, dict) else {},
           "finished": found.get("finished") if isinstance(found.get("finished"), str) else None}
    if isinstance(seen, dict) and seen:
        out["seen"] = dict(seen)
    if isinstance(found.get("reason"), str):
        out["reason"] = found["reason"]
    return out


def write(cfg: Config, data: dict) -> None:
    if path_of(cfg).parent.is_dir():
        atomicfile.write_text(path_of(cfg), json.dumps(data, indent=2) + "\n")


def stored(cfg: Config) -> dict:
    """What `firstrun.json` says. On an install with no file yet it is written once: as
    finished (`existing install`) when a space already lists a repo, so a deck that was set
    up before the stepper is never sent to Start, else as not finished, so a clone later in
    the first run does not read as an older install."""
    with _lock:
        found = read_file(cfg)
        if found is not None:
            return found
        found = {"skipped": {}, "finished": None}
        if installed(cfg) is None:
            return found
        if not onboarding.fresh(cfg):
            found = {"skipped": {}, "finished": now(), "reason": EXISTING}
        write(cfg, found)
        return found


# ----- the steps -----

def pack_steps(cfg: Config) -> list[tuple[packs.Pack, packs.SetupStep, list[str]]]:
    """Each `[[setup]]` step of a pack a space is on, in pack order, with those spaces. A
    pack that does not load brings none (its readiness rows say why)."""
    found: dict[str, tuple[packs.Pack, list[str]]] = {}
    for name, space in cfg.spaces.items():
        try:
            pack = packs.at(space.adapter_dir)
        except packs.PackError:
            continue
        if pack is not None:
            found.setdefault(pack.name, (pack, []))[1].append(name)
    return [(pack, step, spaces) for pack, spaces in found.values() for step in pack.setup]


def order(cfg: Config) -> list[dict]:
    """Every step in the order the stepper shows them: the core steps, each pack step after
    the core step it names. `bosun` is true from Meet Bosun on, a pack's step included."""
    out = []
    extra = pack_steps(cfg)
    for step in STEPS:
        out.append({"id": step.id, "title": step.title, "about": step.about, "required": step.required,
                    "optional": step.optional, "headline": step.headline or step.title,
                    "skip": step.skip and not step.required})
        for pack, own, spaces in extra:
            if own.after == step.id:
                out.append({"id": f"{pack.name}:{own.id}", "title": own.title, "required": False,
                            "optional": False, "skip": True, "headline": own.title,
                            "about": f"From the {pack.name} connection, for {', '.join(spaces)}.",
                            "pack": pack.name, "spaces": spaces,
                            # c-758 r1.F5: the core step it follows, so its screen knows
                            # whether its checks were just shown on Where finished work goes
                            "after": own.after})
    met = False
    for entry in out:
        met = met or entry["id"] == BOSUN_FROM
        entry["bosun"] = met
    return out


def report(cfg: Config, board=None, ready: dict | None = None, steps: bool = True) -> dict:
    """The stepper's state: `{install, finished, reason, redirect, steps: [...]}`.

    `steps` False is a state built for a page that is not the Start view (review F11). On an
    install whose first run is FINISHED that state then reads only the required steps, which
    is all a redirect is decided on: every other step is `{done: None, light: True}`, and
    nothing of theirs is read (the tier drafts, the browser's folder, Bosun's transcripts,
    the backup's files). An install that is not finished reads every step whoever asks, since
    its rail and its redirect follow them."""
    ready = ready or readiness.build(cfg)
    home = installed(cfg)
    kept = stored(cfg)
    light = not steps and kept["finished"] is not None
    extra = {f"{pack.name}:{own.id}": (pack, own, spaces) for pack, own, spaces in pack_steps(cfg)}
    steps = []
    for entry in order(cfg):
        if light and not entry["required"]:
            steps.append({**entry, "done": None, "why": "", "light": True, "skipped": kept["skipped"].get(entry["id"])})
            continue
        try:
            if entry["id"] in extra:
                done, why = pack_state(cfg, *extra[entry["id"]], ready)
                more = {}
            else:
                done, why, more = core_state(cfg, entry["id"], ready, board)
        except Exception as error:  # noqa: BLE001 - one step that cannot be read never takes the state down
            done, why, more = False, f"could not be read: {error}", {}
        been = kept.get("seen", {}).get(entry["id"])
        if done is None and been:
            # c-729: nothing to check, and the user has been through it
            done, why, more = True, SEEN.get(entry["id"], why), {**more, "seen": been}
        steps.append({**entry, **more, "done": done, "why": why,
                      "skipped": kept["skipped"].get(entry["id"])})
    blocked = [step["title"] for step in steps if step["required"] and not step["done"]]
    return {"install": home is not None, "finished": kept["finished"], "reason": kept.get("reason"),
            "redirect": home is not None and (kept["finished"] is None or bool(blocked)),
            "untouched": home is not None and untouched(kept, steps), "steps": steps,
            "watch": watch(board) if board is not None and home is not None else None}   # r1.F8: light too


# c-734: the cards the setup page draws from the Setup report, which the deck's poll does not
# read (it runs the packs' checks): a draft of a tier, a flow or a connection, and the import.
WATCHED = ("SELECT c.id, c.stage, COALESCE(c.blocked_reason, ''), c.updated_at, "
           "(SELECT MAX(e.id) FROM events AS e WHERE e.card = c.id AND e.kind IN ('tell', 'wake')) "
           "FROM cards AS c WHERE (c.stage != 'done' OR c.updated_at >= ?) "
           "AND (c.title IN (?, ?) OR json_extract(c.options, '$.tier_proposal') IS NOT NULL "
           "OR json_extract(c.options, '$.flow_proposal') IS NOT NULL) ORDER BY c.id")
WATCH_DAYS = 2      # a done setup card is read this long after it last moved (r1.F10)


def watch(board) -> str | None:
    """A short stamp of every card the setup page draws from the Setup report (c-734): it
    moves whenever one is filed, staged, blocked, approved or landed, or Bosun is told of it
    (its newest `tell` or `wake`, r1.F5), from anywhere (Bosun's session, the drain, another
    tab), so the open setup step reads the report again with no reload (`K.setupParts.follow`,
    app/ui.setup.js). Only open cards and ones that moved in the last `WATCH_DAYS` are read
    (r1.F10). None where the board cannot say."""
    try:
        since = (datetime.fromisoformat(board.now()) - timedelta(days=WATCH_DAYS)).isoformat(timespec="seconds")
        rows = board.conn.execute(WATCHED, (since, packdraft.CONNECTION_TITLE, onboarding.IMPORT_TITLE)).fetchall()
    except Exception:  # noqa: BLE001 - a stamp that cannot be read only means no follow
        return None
    said = "|".join(":".join(str(value) for value in tuple(row)) for row in rows)
    return hashlib.sha256(said.encode()).hexdigest()[:12]


def untouched(kept: dict, steps: list[dict]) -> bool:
    """Nobody has been through the steps yet, read and never stored (c-677): `firstrun.json`
    holds no skip and no Finish, and no step after Meet Bosun is done (a repo, a tier, a
    pack, a card, the phone: each is the user's doing, where a builder that is on and checks
    that pass are what `shipyard init` leaves). The deck opens such an install on its first
    step, which already reads done, so the choice there is seen. What is chosen ON that step
    does not end it: a builder mode saved there would otherwise take the screen off the
    step, with no tap, on the next state."""
    if kept["finished"] is not None or kept["skipped"]:
        return False
    return not any(step["done"] for step in steps if step["bosun"] and step["id"] != BOSUN_FROM)


# ----- what the screens show beyond the state (`/api/setup`) -----

def panels(cfg: Config) -> dict:
    """Each check of the machine with its fix, the install's login and its fix, the phone's
    command, and each pack step's text."""
    space = readiness.login_space(cfg)
    entry = login.read(cfg).get(space) if space else None
    claude = cfg.spaces[space].config_dir if space else None
    texts = {}
    for pack, own, spaces in pack_steps(cfg):
        try:
            text = own.text.read_text()
        except OSError as error:
            text = f"(the step's text could not be read: {error})"
        texts[f"{pack.name}:{own.id}"] = {"pack": pack.name, "title": own.title, "text": text,
                                          "requires": list(own.requires), "for": list(own.serves),
                                          "spaces": spaces}
    return {"prerequisites": readiness.kept(("prerequisites",), prereqs.gather),
            "bosun": bosun_panel(cfg),
            "memory": memory_panel(cfg),
            # c-678: keeping work on this computer, on Where finished work goes, per space with no pack
            "lands": landpush.panel(cfg),
            "login": {"space": space, "state": (entry or {}).get("state"), "why": (entry or {}).get("why"),
                      "at": (entry or {}).get("at"), "config_dir": str(claude) if claude else None,
                      "fix": login.fix_command(claude) if claude else None,
                      # c-678: the one line the guided sign-in shows, with Copy
                      "command": login.signin_command(claude) if claude else None},
            "phone": {"port": cfg.serve_port, "command": f"tailscale serve --bg {cfg.serve_port}"},
            "pack_steps": texts}


def memory_panel(cfg: Config) -> dict:
    """Where each layer of How Keel remembers lives on this install (c-678): per space with a
    repo the install cloned, its file and each such repo's (`keel/repolayout.py`); Keel's
    house contract; and Bosun's memory, the install's `memory/bosun` (c-722, `console.memory_dir`)."""
    from keel import console         # noqa: PLC0415 - as readiness's builder row
    layout = repolayout.spaces_of(cfg)
    spaces = []
    for name, space in cfg.spaces.items():
        homes = [(key, repolayout.home_of(path, layout)) for key, path in space.repos.items()]
        repos = [{"key": key, "tier": str(home / repolayout.TIER)} for key, home in homes if home is not None]
        if repos:
            spaces.append({"name": name, "tier": str(layout / name / repolayout.TIER), "repos": repos})
    return {"layout": str(layout) if layout else None, "spaces": spaces,
            "rules": str(cfg.root / "etc" / "house-contract.md"),
            "bosun": str(console.memory_dir(cfg))}


def bosun_panel(cfg: Config) -> dict:
    """What Meet Bosun's checks read (c-678): the builder is on, the form chosen, and whether
    its workspace (its own clone of each repo it builds) is there or Start would make it.
    `missing` names the clones Start could not make; `refusal` is Start's own sentence."""
    from keel import console         # noqa: PLC0415 - as readiness's builder row
    on = builder.status(cfg) is not None
    why = console.start_refusal(cfg, cloned_at_start=True) if on else None
    base = builder.clones(cfg)
    coming = set(builder.to_clone(cfg))
    missing = [key for key in sorted(builder.repos(cfg))
               if base is not None and not (base / key / ".git").exists() and key not in coming] if on else []
    return {"on": on, "form": chosen(cfg), "workspace": on and why is None, "refusal": why,
            "missing": missing}


def change(cfg: Config, edit) -> dict:
    """Read the file, `edit` it in place and write it back, as one step under the lock."""
    with _lock:
        data = stored(cfg)
        edit(data)
        write(cfg, data)
        return data


# ----- the verbs -----

def known(cfg: Config, step: str) -> dict:
    found = next((entry for entry in order(cfg) if entry["id"] == step), None)
    if found is None:
        raise SetupError(f"there is no first-run step {step!r}")
    return found


def skip(cfg: Config, step: str) -> dict:
    install_of(cfg)
    found = known(cfg, step)
    if found["required"]:
        raise SetupError(f"{found['title']} cannot be skipped: Shipyard cannot run a card without it")
    if not found["skip"]:
        raise SetupError(f"{found['title']} cannot be skipped: it has no Skip")
    change(cfg, lambda data: data["skipped"].__setitem__(step, now()))
    return {"skipped": step, "note": f"{found['title']} skipped; it stays on the list, and the page that needs it says so"}


def unskip(cfg: Config, step: str) -> dict:
    install_of(cfg)
    found = known(cfg, step)
    change(cfg, lambda data: data["skipped"].pop(step, None))
    return {"unskipped": step, "note": f"{found['title']} is open again"}


# What a step with nothing to check says once the user has been through it (c-729).
SEEN = {"memory": "you have read how Shipyard remembers", "defaults": "you kept the usual path",
        "integrations": LOCAL}


def seen(cfg: Config, step: str, board=None) -> dict:
    """The user went on past a step with nothing to check (Next, Keep this): recorded, so the
    step reads done from then on (c-729). A step with a check of its own is refused, since
    its check is what says it is done. It takes no setup lock (`UNLOCKED`, r2.F4): the page
    sends it as the next step opens, maybe while an Add repo copy holds the lock, and its one
    write is serialised by `change`. It reads only this step, never the whole report."""
    install_of(cfg)
    found = known(cfg, step)
    if checked(cfg, step, board) and step not in stored(cfg).get("seen", {}):
        raise SetupError(f"{found['title']} has its own check: it is done when that passes")
    change(cfg, lambda data: data.setdefault("seen", {}).setdefault(step, now()))
    return {"seen": step, "note": f"{found['title']}: done"}


def checked(cfg: Config, step: str, board=None) -> bool:
    """`step` has a check of its own: its state reads a verdict, not None. A pack's step
    always has one. Read with no readiness first, which every step with nothing to check
    needs none of, and with the whole readiness only for a step that reads it."""
    if step not in STATE:
        return True
    try:
        done = core_state(cfg, step, {}, board)[0]
    except Exception:  # noqa: BLE001 - a step that needs the readiness reads it
        done = core_state(cfg, step, readiness.build(cfg), board)[0]
    return done is not None


def finish(cfg: Config, board) -> dict:
    install_of(cfg)
    open_ones = [step["title"] for step in report(cfg, board)["steps"] if step["required"] and not step["done"]]
    if open_ones:
        raise SetupError(f"Finish waits for {', '.join(open_ones)}")
    data = change(cfg, lambda data: (data.update(finished=now()), data.pop("reason", None)))
    return {"finished": data["finished"], "note": "set up: the deck opens on Now from here"}


def reopen(cfg: Config) -> dict:
    install_of(cfg)
    change(cfg, lambda data: (data.update(finished=None), data.pop("reason", None)))
    return {"finished": None, "note": "the deck opens on Start again until you finish"}


def check_login(cfg: Config, space: str = "") -> dict:
    """Probe a login now, and read every kept reading again on the next state: the install's
    own (the sign-in step), or `space`'s (the sign-in banner's Check again, c-678)."""
    install_of(cfg)
    space = space or readiness.login_space(cfg)
    if space is None:
        raise SetupError("there is no space to log in")
    if space not in cfg.spaces:
        raise SetupError(f"there is no space {space!r}")
    entry = login.check(cfg, space, force=True)
    readiness.forget()
    said = {login.GOOD: "the Claude login works",
            login.EXPIRED: "Claude says this sign-in does not work: paste the command into a terminal, "
                           "then come back"}
    return {"login": entry, "note": said.get(entry["state"], f"the login could not be checked: {entry.get('why')}")}


def hello(cfg: Config) -> bool:
    """Meet Bosun's watch (c-729): whether the user has said hello in Bosun's session. A
    message there writes nothing on the board, so the state's revision does not move and a
    page waiting on the step would hold its old verdict. The page asks `GET /api/hello`
    while it waits: a read, outside the setup lock, which moves the deck only when the
    answer changed (`Deck.heard`, r1.F6, r1.F7), so the next state read carries it."""
    from keel import bosunhello      # noqa: PLC0415 - it imports console, which imports a lot
    return bosunhello.said(cfg)


def save_identity(cfg: Config, name: str, email: str) -> dict:
    """Check this computer's Save: git's global name and email, then every kept reading
    read again, so the row and the step turn on the next state."""
    install_of(cfg)
    try:
        check = prereqs.save_identity(name, email)
    except ValueError as refusal:
        raise SetupError(str(refusal)) from None
    readiness.forget()
    return {"identity": check, "note": f"git will record your merges as {check['said']}"}


def install_cfg(cfg: Config) -> Config:
    """The config, for a verb that only an install may run."""
    install_of(cfg)
    return cfg


# The verbs that take no setup lock (r2.F4): their one write is `change`'s, under its own lock.
UNLOCKED = ("firstrun.seen",)

VERBS = {
    "firstrun.identity.save": lambda cfg, body, board: save_identity(cfg, str(body.get("name") or ""),
                                                                     str(body.get("email") or "")),
    "firstrun.skip": lambda cfg, body, board: skip(cfg, str(body.get("step") or "")),
    "firstrun.unskip": lambda cfg, body, board: unskip(cfg, str(body.get("step") or "")),
    "firstrun.seen": lambda cfg, body, board: seen(cfg, str(body.get("step") or ""), board),
    "firstrun.finish": lambda cfg, body, board: finish(cfg, board),
    "firstrun.reopen": lambda cfg, body, board: reopen(cfg),
    "firstrun.login.check": lambda cfg, body, board: check_login(cfg, str(body.get("space") or "")),
    # c-678: the browser step's Install and Try again, one download at a time
    "firstrun.browser.install": lambda cfg, body, board: browserinstall.start(install_cfg(cfg)),
    # c-678: Back up's one verb: a folder as the store, the keys, the jobs, the first copy
    "firstrun.backup.on": lambda cfg, body, board: backupsetup.turn_on(cfg, str(body.get("folder") or ""), board),
}
