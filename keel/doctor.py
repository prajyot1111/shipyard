"""`keel doctor`: print the resolved setup and exit 1 when any part of it is missing.

It checks and never repairs: the config is loaded without creating the state
directories, and the board is opened read-only, so a missing `board.db` stays missing
and is reported. Its one write is `sight`: every problem it prints is a sighting for Bosun,
and the same one on three runs inside an hour opens a request (c-520). A space with a `projects_dir` also lists the projects discovered in it,
which is where the answer to "what can a card name as its repo" is printed. `claude` is looked up on PATH and asked for its version through
`keel.harness`, the one module that runs the binary. The deck is asked on `serve_port` how
many descriptors the serve process holds against the limit it runs under, and a count near
that limit is a problem: past it `keel serve` can spawn nothing at all (card c-276). The
voice gateway is asked for its
health on `voice_port`; not answering is reported as missing, since the deck's `/voice/`
tier has nothing to proxy to.
On Linux it reports whether the user lingers (`keel.service`): without it every Keel unit
stops at logout and none starts at boot, so off is a problem. On Windows' WSL it also says
whether systemd runs (`prereqs.wsl_check`, c-804): off, no unit can start, so off is a
problem, said with the setup check's own words and fix.
Every row `claude agents --json` lists as working with no process behind it (`keel.ghosts`,
r-26) is a problem naming its card: the board reads it as not running, and it went two
days unseen on c-561.
On a host that both serves spaces and has a `browsers_max`, it says whether Keel's own
browser is installed through `keel.browser`: without it a card carrying `options.browser`
starts a house with nothing to render with. Elsewhere that line reads "not applicable".
On a Mac that serves spaces it reads Docker Desktop's memory against the machine's through
`keel.dockerroom`: 6 GB or less left for macOS is a problem, since that is what made it swap
(c-532). Elsewhere that line reads "not applicable".
Each segment with a fetcher says how long since its last good fetch (`fetch.staleness`), and
one that has stopped updating is a problem. On an install the fetch role is a service of its
own, so the report also says whether one runs (`drainprobe.fetching`), and none running
while segments have fetchers is a problem (c-742). A voice gateway this machine has not
installed is not reported as down.
Every space this machine serves has its login PROBED (`keel/login.py`): one real `claude
-p` under its config dir, always, even inside the ten minutes the drain keeps an answer,
because he asked. It says `logged in (probed HH:MM)` or `LOGIN EXPIRED (probed HH:MM): run
CLAUDE_CONFIG_DIR=<dir> claude, then /login`, and an expired login is a problem; a probe
that cannot say (`unknown`) is reported and is not. On 2026-09-24 the doctor said "logged
in" for a login that could not refresh, because it only looked for a credential file.
Every other credential on the Logins list (`keel/logins.py`: the talker's dir, Drive, the
voice keys, an adapter's) gets a `login` line as the drain
last checked it, and a red one is a problem with its one-liner.
A machine that writes a backup gets a `backup` line with its last good run, read from the
tool's state file, and a snapshot the drain has counted overdue (two waking hours with a run owed and no
success, `keel/backupdue.py`, c-750) is a problem.
"""

import re
import sqlite3
import subprocess
import tomllib
from pathlib import Path

from keel import config as config_module
from keel import (appservices, backupdue, browser, deckdigest, dockerroom, drainprobe, fetch, ghosts, harness, login,
                  logins, memoryroot, prereqs, segmentspec, service, talker, voice)
from keel.doctorpacks import pack_lines, pack_report
from keel.board import STAGES

# Of the soft limit. Past this the deck is close enough to Errno 24 to be worth saying so,
# and far enough from it to leave a working day to act in.
DESCRIPTOR_SHARE = 0.75


def check(path: Path | None, kind: str = "dir") -> dict:
    """A path and whether it exists as the expected kind (`dir` or `file`)."""
    if path is None:
        return {"path": None, "ok": True}
    ok = path.is_dir() if kind == "dir" else path.is_file()
    return {"path": str(path), "ok": ok}


def claude_report() -> dict:
    path = harness.on_path()
    report = {"path": path, "ok": path is not None, "version": None}
    if path is None:
        return report
    try:
        report["version"] = harness.version()
    except harness.HarnessError as error:
        report.update(ok=False, error=str(error))
    return report


# LIVE CARDS ONLY, AND A PARENT IS NOT A HOUSE. The count was every stored stage, so the
# box's archived inbox history read as a live inbox of 184, and a tracking card, whose
# stored stage is whatever it was split at, read as a house building. Archived is
# `options.archived` true (`views.archived`); tracking is having a child (`views.card_view`).
BOARD_COUNTS = """
SELECT stage,
       COALESCE(json_extract(options, '$.archived'), 0) = 1 AS archived,
       EXISTS (SELECT 1 FROM cards AS child WHERE child.parent = cards.id) AS tracking
FROM cards
"""


def board_report(db_path: Path) -> dict:
    """Live card counts per stage from a read-only connection; missing file is not ok.
    Archived cards and tracking cards are counted apart from the stages."""
    report = dict(check(db_path, "file"), counts=None, total=None)
    if not report["ok"]:
        return report
    try:
        conn = sqlite3.connect(f"{db_path.as_uri()}?mode=ro", uri=True)
        try:
            rows = conn.execute(BOARD_COUNTS).fetchall()
        finally:
            conn.close()
    except sqlite3.Error as error:
        return dict(report, ok=False, error=str(error))
    counts = dict.fromkeys(STAGES, 0)
    archived = sum(1 for _stage, gone, _tracking in rows if gone)
    tracking = sum(1 for _stage, gone, parent in rows if parent and not gone)
    for stage, gone, parent in rows:
        if not gone and not parent:
            counts[stage] = counts.get(stage, 0) + 1
    return dict(report, counts=counts, total=len(rows), archived=archived, tracking=tracking)


def hangover_said(v: dict) -> str:
    """The configured hangover beside the running one (lane H, H6)."""
    wanted = v.get("hangover_configured")
    if wanted is None:
        return ""
    if voice.hangover_applied(wanted, v.get("hangover")):
        return " (as configured)"
    return f" (configured {voice.seconds(wanted)}s, keel voice install --load)"


def voice_report(port: int, paths=None, hangover: float | None = None) -> dict:
    """Whether the gateway answers on its port, which speech backends it reports, and
    whether the judges can reach their key.

    The key question is answered by the GATEWAY (`/voice/health`), because it is the only
    process that knows whether the unit's `LoadCredential=` actually delivered the copy it
    reads. When nothing answers, the source file is checked instead, so a gateway that is
    down is never reported as a missing key (V10, c-313)."""
    doc = voice.health(port)
    if doc is None:
        return {"port": port, "ok": False, "judges": judges_offline(paths)}
    out = {"port": port, "ok": True, "up_seconds": doc.get("upSeconds"),
           "stt": (doc.get("stt") or {}).get("backend"),
           "tts": (doc.get("tts") or {}).get("backend"),
           "judges": judges_from_health(doc.get("judges"))}
    # THE DETECTOR AND THE CORPUS (c-311), AND ONLY WHEN THE GATEWAY REPORTS THEM. A
    # detector that has quietly degraded to none is invisible from outside until a
    # hands-free turn takes twenty seconds, and a corpus still recording after its few
    # days is his voice accruing on disk with nobody looking, so both belong here.
    #
    # BUT A KEY THAT IS NOT THERE IS NOT A DETECTOR THAT IS NOT THERE, and conflating the
    # two is a mistake this repo has already made once: `keel voice status` read
    # `doc['router']['backend']` by subscript, the gateway stopped reporting a router when
    # that tier was deleted, and a perfectly healthy gateway started raising. The first cut
    # of this made the softer version of the same error, reading an absent `vad` block as
    # "no end-of-utterance detector" and telling the truth about nothing. A gateway that
    # predates c-311 answers just as well as one that follows it; it simply cannot say
    # anything about a detector, and neither should the doctor.
    if isinstance(doc.get("vad"), dict):
        vad = doc["vad"]
        out.update(vad=vad.get("backend"), vad_ready=bool(vad.get("ready")),
                   vad_why=vad.get("why") or "", hangover=vad.get("hangoverSeconds"),
                   hangover_configured=hangover)
    if isinstance(doc.get("record"), dict):
        rec = doc["record"]
        out.update(recording=bool(rec.get("recording")),
                   recordings=int(rec.get("count") or 0),
                   record_days=rec.get("oldestDays") or 0)
    return out


def judges_from_health(block) -> dict:
    """The judges' line, from the one document the page's sheet also reads."""
    if not isinstance(block, dict):
        return {"known": False, "why": "this gateway is older than the judges"}
    jev = block.get("jev") or {}
    keys = block.get("keys") or {}
    modes = {}
    for key, entry in keys.items():
        mode = (entry or {}).get("mode") or "?"
        modes[mode] = modes.get(mode, 0) + 1
    return {"known": True, "asked": True, "key": jev.get("key") or "missing",
            "where": jev.get("where") or "", "ready": bool(jev.get("ready")),
            "why": jev.get("why") or "", "modes": modes,
            "on": modes.get("on", 0), "retention": jev.get("retention") or "undeclared",
            "calls": jev.get("calls"), "misses": jev.get("misses") or {}}


def judges_offline(paths) -> dict:
    """With no gateway answering, the most that can honestly be said is whether the source
    the unit would load is there."""
    if paths is None:
        return {"known": False, "why": "the gateway is not answering"}
    source = paths.credential_for("jev")
    there = source.exists() and source.stat().st_size > 0
    return {"known": False, "asked": False, "key": "set" if there else "missing",
            "where": str(source),
            "why": "the gateway is not answering, so this is the source and not what it reads"}


def deck_report(port: int) -> dict:
    """The serve process's open descriptors against the soft limit it runs under.

    Counted by the deck itself and read off `/api/state` (`serve.descriptors`), because
    this process is not that one and its own count would say nothing. A deck that does not
    answer is not a problem here: the doctor is not its uptime monitor.

    Card c-276: serve held two descriptors per abandoned lavish stream, hit the 256 launchd
    gives it, and could no longer spawn `claude` at all. Nothing anywhere said the number
    was climbing; it only surfaced as a tracebackstorm hours later.
    """
    report = {"port": port, "answering": False, "ok": True, "open": None, "soft": None}
    try:
        state = deckdigest.fetch_state(port)
    except OSError:
        return report
    found = (state.get("config") or {}).get("descriptors") or {}
    report.update(answering=True, open=found.get("open"), soft=found.get("soft"))
    if report["open"] and report["soft"]:
        report["ok"] = report["open"] < report["soft"] * DESCRIPTOR_SHARE
    return report


def projects_report(space) -> dict | None:
    """The space's projects directory and the repos discovered in it, or None.

    It is never a problem: a space may have no projects directory, and one that has a
    directory it has not opened a project in yet is a setup nobody has used, not a broken
    one (the first new-project card creates it).
    """
    if space.projects_dir is None:
        return None
    return {"path": str(space.projects_dir), "exists": space.projects_dir.is_dir(),
            "names": space.projects()}


def origin_of(path: Path, remote: str | None = None) -> str | None:
    """The URL of the clone's remote: the space's own (`[spaces.<name>] remote`), `origin` by default."""
    done = subprocess.run(["git", "-C", str(path), "remote", "get-url", remote or config_module.DEFAULT_REMOTE],
                          capture_output=True, text=True)
    return done.stdout.strip() if done.returncode == 0 and done.stdout.strip() else None


def org_of(url: str) -> str:
    """`git@host:org/repo.git` and `https://host/org/repo.git` both give `host/org`."""
    rest = re.sub(r"^[a-z+]+://", "", url).split("@")[-1].replace(":", "/")
    return "/".join(rest.split("/")[:2]).lower()


def unlisted_repos(space, install: bool = False) -> dict[str, str]:
    """A git clone beside the space's listed repos (in the same directory) whose origin is
    in the same org as one of them, but which the space does not list: a repo a card cannot
    name (c-509). One of another org beside them is not the space's and is left out.

    On an install's config (`install`) the code checkout's own folder is not scanned
    (c-618): an install listing Keel itself did not choose the folder Keel was cloned into,
    whose neighbours are whatever else the user keeps there. The live config's scan is as
    before."""
    listed = {Path(path).expanduser().resolve() for path in space.repos.values()}
    remote = getattr(space, "remote", None)
    orgs = {org_of(url) for url in (origin_of(path, remote) for path in listed if path.is_dir()) if url}
    code = config_module.repo_root()
    found = {}
    for parent in sorted({path.parent for path in listed if not (install and path == code)}):
        for entry in sorted(parent.iterdir()) if parent.is_dir() else ():
            if entry.resolve() in listed or not (entry / ".git").exists():
                continue
            url = origin_of(entry, remote)
            if url and org_of(url) in orgs:
                found[entry.name] = str(entry)
    return found


def is_install(cfg) -> bool:
    """True when `cfg` is an install's own config (`appservices.install_dir`)."""
    try:
        appservices.install_dir(cfg)
    except appservices.NotAnInstall:
        return False
    return True


def unlisted_problems(name: str, space: dict) -> list[str]:
    if not space.get("served", True):
        return []
    return [f"space {name}: repo {repo} is cloned at {path} but not listed in [spaces.{name}.repos], "
            f"so no card can name it" for repo, path in (space.get("unlisted") or {}).items()]


def space_report(space, served: bool = True, guard=None, install: bool = False) -> dict:
    """`served` is whether this machine's drain serves the space: every space does now (one
    machine, c-622), and one that does not would skip its unlisted repos and pack tools."""
    return {
        "served": served,
        "config_dir": check(space.config_dir),
        "contract": check(space.contract, "file"),
        "adapter": space.adapter,
        "adapter_dir": check(space.adapter_dir),
        "repos": {name: check(path) for name, path in space.repos.items()},
        "unlisted": unlisted_repos(space, install) if served else {},
        "projects": projects_report(space),
        "pack": pack_report(space, served, guard),
    }


def gather(path: Path | None = None, single: bool = False, probe_logins: bool = True) -> dict:
    """The whole report; `config.ok` is false when the toml cannot be read. `single` (or an
    install's own config, `single_machine`) leaves out the checks an install does not have:
    the voice gateway unless it is installed, the talker and Docker Desktop's room. It adds
    the install's fetch role (c-742): whether one runs, and the segments that wait on it."""
    path = path or config_module.config_path()
    report = {"config": {"path": str(path), "ok": True}}
    try:
        cfg = config_module.load(path, ensure=False)
    except (OSError, tomllib.TOMLDecodeError, KeyError, ValueError) as error:
        report["config"].update(ok=False, error=f"{type(error).__name__}: {error}")
        report["claude"] = claude_report()
        return report
    # c-633: what the loader warned about (an unknown key, a wrong value), each a problem
    report["config"]["warnings"] = list(cfg.warnings)
    report["keel"] = {
        "root": str(cfg.root),
        "state_dir": check(cfg.state_dir),
        "houses_max": cfg.houses_max,
        "host": host_report(cfg),
        "drain_paused": cfg.drain_paused,
        "poll_seconds": cfg.poll_seconds,
    }
    served = set(cfg.served_spaces())
    install = is_install(cfg)
    report["spaces"] = {name: space_report(space, name in served, cfg.stack_guard_hook, install)
                        for name, space in cfg.spaces.items()}
    report["claude"] = claude_report()
    report["board"] = board_report(cfg.db_path)
    if probe_logins:
        report["login"] = login_report(cfg)
    # Every other credential (c-558): read as the drain last checked it, never checked here;
    # `keel logins check --all` is the check on demand.
    try:
        report["logins"] = [row for row in logins.public(cfg) if not row["houses"]]
    except Exception as error:  # noqa: BLE001 - one unreadable list must not end the report
        report["logins"] = [{"id": "logins", "state": "unknown", "where": "", "fix": None,
                             "why": f"could not read: {type(error).__name__}: {error}"}]
    report["deck"] = deck_report(cfg.serve_port)
    report["linger"] = service.linger_report()
    if wsl := prereqs.wsl_check():            # c-804: WSL with systemd off runs no unit at all
        report["wsl"] = wsl
    report["browser"] = browser.gather(cfg)
    report["ghosts"] = ghosts.gather(cfg)
    report["backup"] = backupdue.gather(cfg)
    report["builder"] = builder_report(cfg)
    report["bosun_owner"] = bosun_owner(cfg)
    # c-634: each segment's segment.md against keel/segmentspec.py, reported and never skipped
    report["segments"] = segmentspec.report(cfg)
    report["memory"] = memoryroot.report(cfg)        # c-722: information, never a problem
    if single or single_machine(cfg):
        report["single"] = True
        # Another Keel drain as this user here would share this install's houses (c-620).
        others, ours = drainprobe.drains(Path(cfg.source)) if cfg.source else ([], [])
        report["drains"] = {"others": others, "ours": ours}
        # An install's segments are fetched by its own fetch role, a service of its own
        # (c-742): with none running they never refresh, which nothing else would say.
        report["fetch"] = {"running": drainprobe.fetching(Path(cfg.source)) if cfg.source else [],
                           "segments": [path.name for path in fetch.fetchers(cfg)]}
        report["fetches"] = fetch.staleness(cfg)
        # Without it every landing fails at the merge commit (c-621); the box's users have one.
        # With no git there is no identity to read, so the report then carries the git
        # check's own miss instead (`prereqs.git_checks`, the guard `gather` uses, c-679).
        git, *identity = prereqs.git_checks()
        report.update({"git_identity": identity[0]} if identity else {"git": git})
        if service.installed(voice.LABEL):
            report["voice"] = voice_report(cfg.voice_port, voice.paths_from(cfg), cfg.voice_vad_hangover)
        return report
    report["voice"] = voice_report(cfg.voice_port, voice.paths_from(cfg), cfg.voice_vad_hangover)
    report["fetches"] = fetch.staleness(cfg)
    report["talker"] = talker.health(talker.paths_from(cfg))
    report["docker"] = dockerroom.gather(cfg)
    return report


OWNER_FIRST = "Bosun cannot start (the bosun line says why)"


def builder_report(cfg) -> dict | None:
    """Whether Bosun could start as its builder here (c-619, `builder.refusal`): the
    superuser (which does not start, c-648), the in-app builder's install, mode and clones.
    None where builder mode is off or this config has no Bosun. A config dir another Unix
    user owns refuses every Start (`bosun_owner`), so the builder is not ready then either:
    its why points at the `bosun` line, which says the sentence once."""
    from keel import builder, console
    if builder.mode(cfg) is None or not console.configured(cfg):
        return None
    why = OWNER_FIRST if console.other_owner(cfg) else builder.refusal(cfg)
    return {"mode": builder.mode(cfg), "ok": why is None, "why": why}


def bosun_owner(cfg) -> str | None:
    """Why Bosun's Start is refused for its config dir's owner (`console.other_owner`, c-648),
    wherever this config has a Bosun, whatever builder mode is; else None."""
    from keel import console
    return console.other_owner(cfg) if console.configured(cfg) else None


def single_machine(cfg) -> bool:
    """An install made by `shipyard init` (c-616): no voice unless installed, no talker.
    Its checks are only the ones that apply."""
    try:
        appservices.install_dir(cfg)
    except appservices.NotAnInstall:
        return False
    return True


def login_report(cfg) -> dict:
    """`{space: {state, why, at, config_dir}}` for every space this machine serves, each
    probed now."""
    found = {}
    for name in cfg.served_spaces():
        entry = login.check(cfg, name, force=True)
        found[name] = dict(entry, config_dir=str(cfg.spaces[name].config_dir))
    return found


def gone_words(config_dir) -> str:
    """A dir known never to have held a login is not called expired (c-560)."""
    return "not logged in yet" if login.ever_logged_in(config_dir) is False else "the login expired"


def login_problems(found: dict) -> list[str]:
    return [f"space {name}: {gone_words(entry['config_dir'])}, so no house can run "
            f"({login.fix_command(entry['config_dir'])})"
            for name, entry in found.items()
            if entry["state"] == login.EXPIRED]


def login_lines(found: dict) -> list[str]:
    return [f"login         {name}: {login.said(entry, entry['config_dir'])}"
            for name, entry in found.items()]


def host_report(cfg) -> dict:
    """This machine's drain: what it serves, its limits."""
    return {"name": cfg.host, "spaces": cfg.served_spaces(), "reviews_max": cfg.reviews_max,
            "browsers_max": cfg.browsers_max, "memory_floor_mb": cfg.memory_floor_mb,
            "house_nice": cfg.house_nice}


def host_line(host: dict) -> str:
    return (f"host          {host['name']}: serves {', '.join(host['spaces']) or 'nothing'}; "
            f"reviews_max {host['reviews_max']}, browsers_max {host['browsers_max'] or 'any'}, "
            f"memory floor {host['memory_floor_mb'] or 'off'}"
            f"{' MB' if host['memory_floor_mb'] else ''}, house nice {host['house_nice']}")


def problems(report: dict) -> list[str]:
    """One line per missing or failing item; empty means healthy."""
    found = []
    if not report["config"]["ok"]:
        found.append(f"config {report['config']['path']}: {report['config']['error']}")
    found += [f"config: {line}" for line in report["config"].get("warnings") or []]
    if not report["claude"]["ok"]:
        found.append(report["claude"].get("error") or "claude is not on PATH")
    found += ghosts.problems(report.get("ghosts") or {})
    if backupdue.problem(report.get("backup") or {}):
        found.append(backupdue.problem(report["backup"]))
    found += [f"another drain: {line}" for line in (report.get("drains") or {}).get("others", [])]
    for check in (report.get("wsl"), report.get("git"), report.get("git_identity")):
        if check and not check["ok"]:
            found.append(f"{prereqs.miss_words(check)} ({prereqs.fix_words(check)})")
    if report.get("bosun_owner"):
        found.append(f"bosun: {report['bosun_owner']}")
    if (report.get("builder") and not report["builder"]["ok"]
            and report["builder"]["why"] != OWNER_FIRST):       # the bosun line is the problem
        found.append(f"builder ({report['builder']['mode']}): {report['builder']['why']}")
    found += segmentspec.problems(report.get("segments") or {})
    if "keel" not in report:
        return found
    if not report["keel"]["state_dir"]["ok"]:
        found.append(f"state_dir missing: {report['keel']['state_dir']['path']}")
    for name, space in report["spaces"].items():
        served = space.get("served", True)
        # The contract and the adapter are in this checkout, served or not; the config dir
        # and the repos are the serving machine's.
        for item in ("config_dir", "contract", "adapter_dir") if served else ("contract", "adapter_dir"):
            if not space[item]["ok"]:
                found.append(f"space {name}: {item} missing: {space[item]['path']}")
        for repo, entry in space["repos"].items() if served else ():
            if not entry["ok"]:
                found.append(f"space {name}: repo {repo} missing: {entry['path']}")
        found += unlisted_problems(name, space)
        if (space.get("pack") or {}).get("error"):
            found.append(f"space {name}: pack: {space['pack']['error']}")
    found += login_problems(report.get("login") or {})
    found += [f"login {row['id']}: {row['state']}: {row['why']}"
              + (f" ({row['fix']})" if row.get("fix") else "")
              for row in report.get("logins") or [] if logins.red(row)]
    board = report["board"]
    if not board["ok"]:
        found.append(f"board: {board.get('error') or 'missing'}: {board['path']}")
    deck = report.get("deck", {})
    if not deck.get("ok", True):
        found.append(f"deck: {deck['open']} open descriptors of the {deck['soft']} it may "
                     f"hold; past that `keel serve` cannot spawn `claude` at all")
    found += voice_problems(report.get("voice"))
    health = report.get("talker") or {}
    if health and not health.get("ok", True):
        found.append(f"talker: {health['state']}, {health['reason']}")
    linger = report.get("linger", {})
    if linger.get("applicable") and not linger.get("on"):
        found.append(f"linger: off for {linger['user']}, so Shipyard's units stop at logout and "
                     f"none starts at boot (sudo loginctl enable-linger {linger['user']})")
    if browser.problem(report.get("browser") or {}):
        found.append(browser.problem(report["browser"]))
    if dockerroom.problem(report.get("docker") or {}):
        found.append(dockerroom.problem(report["docker"]))
    found += fetch_role_problems(report.get("fetch"))
    found += fetch_problems(report.get("fetches") or [])
    return found


def fetch_role_problems(role: dict | None) -> list[str]:
    """An install whose segments have fetchers and no fetch role running (c-742)."""
    if not role or role["running"] or not role["segments"]:
        return []
    return [f"fetch: nothing runs the fetch role, so {appservices.counted(role['segments'])} never "
            f"refresh: `shipyard service install fetch` (or `shipyard fetch` by hand)"]


def fetch_role_line(role: dict) -> str:
    said = "; ".join(role["running"]) or ("NOT RUNNING" if role["segments"]
                                          else "not running (no segment has a fetcher)")
    return f"fetch         {said}"


def fetch_problems(entries: list[dict]) -> list[str]:
    return [f"segment {entry['name']}: "
            + ("no good fetch recorded" if entry["age_seconds"] is None
               else f"last good fetch {int(entry['age_seconds'] // 3600)}h ago")
            + "; it has stopped updating"
            for entry in entries if not entry["ok"]]


def fetch_lines(entries: list[dict]) -> list[str]:
    return [f"segment       {entry['name']:<12} "
            + ("never fetched" if entry["age_seconds"] is None
               else f"good fetch {int(entry['age_seconds'] // 60)}m ago")
            + ("" if entry["ok"] else "  STALE")
            for entry in entries]


def voice_problems(v: dict | None) -> list[str]:
    """The voice gateway's lines, none when the report has no gateway in it."""
    found = []
    if v is None:
        return found
    if not v["ok"]:
        found.append(f"voice: not answering on 127.0.0.1:{v['port']}")
    else:
        # `"vad" in report` rather than a truth test on `vad_ready`: see voice_report.
        if "vad" in v and not v["vad_ready"]:
            found.append(f"voice: no end-of-utterance detector "
                         f"({v.get('vad_why') or 'reason not given'}), "
                         f"so a hands-free turn waits out the page's twenty second backstop")
        # NAMED AFTER THE DAYS HE AGREED TO, not the day it was switched on. The corpus
        # is his voice: it is meant to run for two or three days and then be deleted, so
        # the doctor starts saying so once it is past that.
        if v.get("recording") and (v.get("record_days") or 0) > 4:
            found.append(f"voice: still recording the user's utterances after "
                         f"{v['record_days']} days "
                         f"({v['recordings']} of them). Measure with "
                         f"`bin/keel-voice-vad-measure`, then set `record = false` under "
                         f"[voice] and run `keel voice corpus --delete`")
    judges = v.get("judges") or {}
    if judges.get("asked") and not judges.get("ready"):
        # Not a stall and not a spoken error: every judge simply falls through to its rule
        # and counts a miss. Said out loud anyway, because a judge in shadow with no key
        # produces no evidence, and the evidence is the whole point of shadow (V10).
        found.append(f"judges: {judges['why']}, so every call is the rule's verdict and a "
                     f"counted miss, and the shadow log records nothing to read")
    return found


def judges_line(judges: dict) -> str:
    """Whether the judges can reach the key, and what the switch says, in one line."""
    if not judges.get("known"):
        said = judges.get("why") or "unknown"
        if judges.get("asked") is False and judges.get("key"):
            return f"key {judges['key'].upper() if judges['key'] == 'missing' else judges['key']}  ({said})"
        return said
    modes = ", ".join(f"{count} {mode}" for mode, count
                      in sorted(judges.get("modes", {}).items())) or "no keys"
    said = f"{modes}  key {'set' if judges['key'] == 'set' else 'MISSING'}"
    said += f"  retention {judges['retention']}"
    if judges.get("calls"):
        misses = sum((judges.get("misses") or {}).values())
        said += f"  {judges['calls']} calls, {misses} misses"
    return said


def mark(entry: dict) -> str:
    return f"{entry['path']}" + ("" if entry["ok"] else "  MISSING")


def render(report: dict) -> str:
    lines = [f"config        {report['config']['path']}"]
    if "keel" in report:
        keel = report["keel"]
        lines += [
            f"root          {keel['root']}",
            f"state_dir     {mark(keel['state_dir'])}",
            f"houses_max    {keel['houses_max']}",
            host_line(keel["host"]),
            f"drain_paused  {keel['drain_paused']}",
            f"poll_seconds  {keel['poll_seconds']}",
        ]
        for name, space in report["spaces"].items():
            lines.append(f"space {name}" + ("" if space.get("served", True) else
                                            "  (not served here: its config dir and repos are not checked)"))
            lines.append(f"  config_dir  {mark(space['config_dir'])}")
            if space["contract"]["path"]:
                lines.append(f"  contract    {mark(space['contract'])}")
            if space["adapter"]:
                lines.append(f"  adapter     {space['adapter']}  {mark(space['adapter_dir'])}")
            lines += pack_lines(space.get("pack"))
            lines += [f"  repo {repo}  {mark(entry)}" for repo, entry in space["repos"].items()]
            if space["projects"]:
                found = space["projects"]
                names = ", ".join(found["names"]) or ("none yet" if found["exists"]
                                                      else "not made yet")
                lines.append(f"  projects    {found['path']}  ({names})")
    if report.get("builder"):
        built = report["builder"]
        lines.append(f"builder       {built['mode']}: " + ("ready" if built["ok"] else built["why"]))
    claude = report["claude"]
    lines.append(f"claude        {claude['path'] or 'not on PATH'}"
                 + (f"  ({claude['version']})" if claude["version"] else ""))
    lines += login_lines(report.get("login") or {})
    lines += [f"login         {logins.line(row)}" for row in report.get("logins") or []]
    if "board" in report:
        board = report["board"]
        lines.append(f"board         {mark(board)}")
        if board["counts"] is not None:
            counts = "  ".join(f"{stage}={n}" for stage, n in board["counts"].items())
            lines.append(f"  cards       {counts}  total={board['total']}  "
                         f"(tracking {board.get('tracking', 0)}, archived "
                         f"{board.get('archived', 0)} not counted)")
    if "deck" in report:
        deck = report["deck"]
        said = (f"{deck['open']} of {deck['soft']} descriptors" if deck["open"]
                else "answering") if deck["answering"] else "not answering"
        lines.append(f"deck          127.0.0.1:{deck['port']}  {said}"
                     + ("" if deck["ok"] else "  HIGH"))
    if "voice" in report:
        v = report["voice"]
        lines.append(f"voice         127.0.0.1:{v['port']}  "
                     + (f"up {v['up_seconds']}s  stt {v['stt']}  tts {v['tts']}"
                        + (f"  vad {v['vad'] or 'none'}" if "vad" in v else "")
                        + (f" {v['hangover']}s{hangover_said(v)}" if v.get("vad_ready") else "")
                        + (f"  recording {v['recordings']}" if v.get("recording") else "")
                        if v["ok"] else "DOWN"))
        lines.append("judges        " + judges_line(v.get("judges") or {}))
    if "talker" in report:
        lines.append(f"talker        {report['talker']['state']}, {report['talker']['reason']}")
    if "linger" in report:
        linger = report["linger"]
        lines.append("linger        " + (("on" if linger["on"] else "OFF") + f" for {linger['user']}"
                                         if linger["applicable"] else "not applicable (launchd)"))
    if "wsl" in report:
        wsl = report["wsl"]
        lines.append("wsl systemd   " + ("on" if wsl["ok"] else prereqs.miss_words(wsl)))
    if "browser" in report:
        lines.append(browser.line(report["browser"]))
    if "docker" in report:
        lines.append(dockerroom.line(report["docker"]))
    if "fetch" in report:
        lines.append(fetch_role_line(report["fetch"]))
    if "fetches" in report:
        lines += fetch_lines(report["fetches"])
    if "ghosts" in report:
        lines.append(ghosts.line(report["ghosts"]))
    if "backup" in report:
        lines.append(backupdue.line(report["backup"]))
    if "segments" in report:
        lines.append(segmentspec.line(report["segments"]))
    if "memory" in report:
        lines += memoryroot.lines(report["memory"])
    if "drains" in report:
        ours = report["drains"]["ours"]
        lines.append("drain         " + ("; ".join(ours) if ours else "this install's is not running"))
    if "git" in report:
        lines.append("git           " + prereqs.miss_words(report["git"]))
    if "git_identity" in report:
        identity = report["git_identity"]
        lines.append("git identity  " + (identity["said"] if identity["ok"] else prereqs.miss_words(identity)))
    found = problems(report)
    lines.append("")
    lines += [f"missing: {item}" for item in found] or ["ok"]
    return "\n".join(lines)


def sight(found: list[str], path: Path | None = None) -> list[str]:
    """Each problem this run printed, as a sighting for Bosun (`keel/requests.py`, c-520):
    the same problem on `[console] repeat_after` runs inside `repeat_minutes` opens a
    request. Keyed by the line with its numbers and times taken out, so "probed 14:02" and
    "probed 14:32" are one problem. The doctor's only write, and it never creates a board
    that is not there or fails the report: the ids it opened, or nothing."""
    from keel import requests
    from keel.board import open_board
    try:
        cfg = config_module.load(path or config_module.config_path(), ensure=False)
        if not found or not Path(cfg.db_path).is_file():
            return []
        board = open_board(cfg)
    except Exception:  # noqa: BLE001 - a doctor that cannot file still reports
        return []
    opened = []
    try:
        for line in found:
            try:
                row = requests.sight_on(board, cfg.console, "doctor:" + requests.key_of(line),
                                        line, "doctor")
            except Exception:  # noqa: BLE001 - one sighting is not the report
                continue
            if isinstance(row, dict) and row.get("filed"):
                opened.append(row["id"])
    finally:
        board.close()
    return opened
