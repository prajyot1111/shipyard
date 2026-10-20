"""The settings schema (c-633): every user-facing key of `[keel]`, `[spaces.<name>]` and
`[voice]`, declared once, with its type, its default, a label and a sentence of help. `[builder]`
has one, `mode` (c-632), so the first run's Choose your builder step writes it through the same Save; the
rest of `[builder]` is `keel/builder.py`'s and is not read through `check`.

`keel/config.py` takes every default from here and reads every value through `check`, so the
dataclass defaults, the loader's fallbacks and the Settings view can never disagree. The deck's
Settings view (`app/ui.settings.js`) is drawn from `report`, and its Save is `save`, written
through `setupconfig.edit` like every Setup write.

A KEY THE TABLE DOES NOT KNOW is a warning, not silence (`check`): `house_reveiw = true` used
to turn the pipeline off with no word. `STRUCTURAL` lists the keys each table accepts that are
not settings in the view (paths, repos, the pack, this machine's own keys), so the set of
known keys is complete and a structural key never warns.

A VALUE OF THE WRONG TYPE never stops a config from loading (c-633, Bosun's condition): the
loader warns, naming the key, the value and what it may be, and uses the default, so a typo
can never keep the deck from starting. A setting whose default is not its safe position
names a `fallback` for a wrong value instead: `drain_paused = "true"` pauses the drain, as
the old loader's `bool()` did, rather than starting houses (c-628 review r1.F5). The Settings form refuses the same value on Save
(`parse` raises), so nothing Keel writes is ever wrong.

`model` in `[keel]` is Keel's own default model for a new card (`cardspec`, the keel_default
layer); `model` under a space is that space's (the space_default layer). Keys of the same name
in two tables are two settings: a setting is named by its table and its key.

A help text names a ticket or a change through `{ticket}` and `{change}` (c-630,
`keel/terms.py`): `report` says the schema's help in the core's words and each space's in its
own (`helps`), so the work space reads its pack's nouns.
"""

from __future__ import annotations

import difflib
import math
import re
from dataclasses import dataclass

from keel.bases import bases_rule, integrated
from keel.models import KEEL_MODEL, MODELS, model_problem
from keel.shipwatch import WorkHours

TABLES = ("keel", "space", "voice", "builder")
KINDS = ("bool", "int", "float", "text", "choice", "model", "list")
GROUPS = ("Drain", "New cards", "Review", "Tests and shipping", "Conversations", "Features", "Builder",
          "Voice")
# The values the example turns on that the code keeps off (c-633, decision example-drift: code).
# Each is a feature switch whose off position is the safe one. `record` is not one of them
# since c-722: recording is a privacy choice, so the example ships it off like the code.
EXAMPLE_OPT_INS = (("keel", "merge_queue"), ("keel", "rotate"), ("keel", "multi_after"),
                   ("keel", "bosun_builder"), ("voice", "harbor_kept_alive"))


# A setting whose wrong value falls back to its default (most of them): `Setting.fallback`.
DEFAULT = object()


class SettingError(ValueError):
    """A value a setting may not take; the message names the key, the value and what it may be."""


@dataclass(frozen=True)
class Setting:
    key: str
    table: str                  # keel, space or voice
    kind: str                   # one of KINDS
    default: object             # None: unset, and the layer below decides
    label: str
    help: str
    group: str
    choices: tuple = ()         # a choice's values; a model's extra words (inherit)
    low: float | None = None
    high: float | None = None
    unit: str = ""
    rule: object = None         # a further check: rule(value) raises ValueError
    trim: bool = False          # a list: drop blank items and the spaces round each (c-732, bases)
    fallback: object = DEFAULT  # what a WRONG value falls back to, when the safe position is
                                # not the default (drain_paused: a garbled switch pauses)

    @property
    def scope(self) -> str:
        return "space" if self.table == "space" else "install"

    @property
    def id(self) -> str:
        return f"{self.table}.{self.key}"

    @property
    def attr(self) -> str:
        """The `Config` or `Space` field that holds it."""
        return f"voice_{self.key}" if self.table == "voice" else self.key

    @property
    def if_wrong(self):
        """The value a wrong value is replaced with at load."""
        return self.default if self.fallback is DEFAULT else self.fallback

    def where(self, space: str | None = None) -> str:
        table = f"spaces.{space or '<name>'}" if self.table == "space" else self.table
        return f"[{table}] {self.key}"


def hours_rule(value: str) -> None:
    WorkHours.parse(value, "mon-fri")


def days_rule(value: str) -> None:
    WorkHours.parse("09:00-19:00", value)


REMOTE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")
BRANCH_FIELDS = ("id", "slug")
BRANCH_FIELD = re.compile(r"\{([^{}]*)\}")
# What git takes no branch name with (`git check-ref-format`), said here so a load never
# runs git: a character it refuses, a doubled dot or slash, `@{`, a part that starts with a
# dot or ends in `.lock`.
BRANCH_BAD = re.compile(r"[\x00-\x20\x7f~^:?*\[\\]|\.\.|//|@\{|(^|/)\.|\.lock(/|$)")


def remote_rule(value: str) -> None:
    if not REMOTE.match(value):
        raise ValueError("a remote is named in letters, digits, dots, dashes and underscores, "
                         "like origin")


# `{id}` standing alone: at the start of the name or right after a separator, and followed by
# one or the end. Then `c-1`'s branch can never be read as `c-10`'s, nor as part of a word.
BRANCH_ID_ALONE = re.compile(r"(?:^|(?<=[-_/.]))\{id\}(?=$|[-_/.])")
# The slugs a pattern is tried with: an ordinary one, one that would end a part in `.lock`,
# one character, and the longest a title gives (`adapters.SLUG_MAX`).
BRANCH_SLUGS = ("a-title", "lock", "a", "x" * 40)
BRANCH_MAX = 200


def branch_rule(value: str) -> None:
    """A card branch pattern (c-665): `{id}` in it and standing alone, so each card has a
    branch of its own and finds it again, and a name git takes whatever slug fills it."""
    rest = BRANCH_FIELD.sub("", value)
    if set(BRANCH_FIELD.findall(value)) - set(BRANCH_FIELDS) or "{" in rest or "}" in rest:
        raise ValueError("a branch pattern fills only {id} and {slug}")
    if "{id}" not in value:
        raise ValueError("a branch pattern must contain {id}, so each card has its own branch")
    if len(BRANCH_ID_ALONE.findall(value)) != value.count("{id}"):
        raise ValueError("{id} must stand at the start of the name or right after -, _, / or ., "
                         "and be followed by one of them or end the name, so one card's branch "
                         "is never taken for another's")
    for slug in BRANCH_SLUGS:
        name = value.replace("{id}", "c-1").replace("{slug}", slug)
        if (BRANCH_BAD.search(name) or name.startswith(("-", "/")) or name.endswith(("/", "."))
                or name == "@" or len(name) > BRANCH_MAX):
            raise ValueError("git would not take that as a branch name")


S = Setting
SETTINGS = (
    # ----- [keel], the install's -----
    S("houses_max", "keel", "int", 3, "Houses at once",
      "How many houses the drain runs at the same time. Default 3.",
      "Drain", low=0, high=32),
    S("reviews_max", "keel", "int", 2, "Review houses at once",
      "How many review cards run at the same time, in their own pool beside the houses. Default 2.",
      "Drain", low=0, high=32),
    S("poll_seconds", "keel", "int", 30, "Drain pass every",
      "How often the drain looks at the board. Default 30 seconds.", "Drain", low=1, high=3600, unit="s"),
    S("drain_paused", "keel", "bool", False, "Drain paused",
      "On: the drain keeps the board tidy but starts no house. Default off.", "Drain",
      fallback=True),
    S("model", "keel", "model", KEEL_MODEL, "Shipyard's model",
      "The model a new card runs on when neither the card nor its space names one. Default opus.",
      "New cards"),
    S("backlog_days", "keel", "int", 7, "Backlog after",
      "Days a card may wait at its outcome gate before it moves to the backlog, counted from when "
      "it got there or from your last own action on it. Default 7.",
      "Review", low=1, high=365, unit="days"),
    S("review_full_rounds", "keel", "int", 2, "Full review passes",
      "Full review passes one trip to review may have before only fix checks remain. A space may "
      "set its own. Default 2.", "Review", low=1, high=10),
    S("review_asks", "keel", "int", 2, "Review asks before a block",
      "How many times a house is sent back for a missing review stamp before its card is blocked. "
      "Default 2.", "Review", low=1, high=10),
    S("merge_test_seconds", "keel", "int", 900, "Merge test limit",
      "How long the tests on the merged tree may run before Approve outcome gives up. Default 900 "
      "seconds.", "Tests and shipping", low=10, high=86400, unit="s"),
    S("deploy_test_seconds", "keel", "int", 1800, "Deploy test limit",
      "How long the full suite before a deploy may run. Default 1800 seconds.",
      "Tests and shipping", low=10, high=86400, unit="s"),
    S("ship_idle_hours", "keel", "int", 2, "Close idle shipping houses after",
      "A shipping house idle this long is closed; the next review batch resumes it. Default 2 hours.",
      "Tests and shipping", low=1, high=168, unit="h"),
    S("work_hours", "keel", "text", "09:00-19:00", "Work hours",
      "When you work, as HH:MM-HH:MM in this machine's time. A shipping card is checked more often "
      "inside them. Default 09:00-19:00.", "Tests and shipping", rule=hours_rule),
    S("work_days", "keel", "text", "mon-fri", "Work days",
      "The days the work hours apply, like mon-fri or mon,wed,fri. Default mon-fri.",
      "Tests and shipping", rule=days_rule),
    S("discussion_idle_seconds", "keel", "int", 1200, "Plan discussion ends after",
      "A plan discussion with nothing sent for this long ends. Default 1200 seconds.",
      "Conversations", low=60, high=86400, unit="s"),
    S("voice_hold_seconds", "keel", "int", 300, "Voice holds a house for",
      "How long voice keeps a card's house after the last thing you said. Default 300 seconds.",
      "Conversations", low=10, high=86400, unit="s"),
    S("talker_reset_max_age_seconds", "keel", "int", 86400, "Talker resets after",
      "The talker starts a fresh conversation once its current one is this old. Default 86400 "
      "seconds (a day).", "Conversations", low=3600, high=30 * 86400, unit="s"),
    S("merge_queue", "keel", "bool", False, "Merge queue",
      "On: Approve outcome of a personal card lands through the drain, which tests the merged tree "
      "first. Default off.", "Features"),
    S("rotate", "keel", "bool", False, "Rotate sessions",
      "On: the deck offers Rotate session, which moves a house to a fresh session with a "
      "checkpoint. Default off.", "Features"),
    S("multi_after", "keel", "bool", False, "Wait for several cards",
      "On: a card may wait for several cards (after=a,b). Turn on only once every machine runs "
      "code that reads a list. Default off.", "Features"),
    S("bosun_builder", "keel", "bool", False, "Builder mode",
      "On: Bosun builds personal cards that name a repo, and lands them on your Approve outcome. "
      "Default off.", "Features"),
    S("plan_pages", "keel", "bool", True, "Plan pages",
      "On: every new plan and outcome is written in the plan format and read on its own page. "
      "Default on.", "Features"),
    # ----- [spaces.<name>], each space's -----
    S("model", "space", "model", None, "Model",
      "The model a new card in this space runs on when it names none. Empty: Shipyard's model.",
      "New cards"),
    S("autonomy", "space", "choice", "autonomous", "Autonomy",
      "Attended: a new card stops at its plan for you. Autonomous: it plans and builds on its own. "
      "Default autonomous.", "New cards", choices=("attended", "autonomous")),
    S("plan_style", "space", "choice", "auto", "Plan style",
      "How a new card's house writes its plan when plan pages are off: auto lets it choose. "
      "Default auto.", "New cards", choices=("auto", "markdown", "lavish")),
    # c-732: asked on How work ships ("Where does work start?"); offered on every card form
    S("bases", "space", "list", (), "Where work starts",
      "The branches a card's work can start from and land on, like main, staging, offered on every "
      "new card. A card that names none starts from, and lands on, its repo's usual branch (its "
      "integration branch, else the branch its remote names as its default for a repo Shipyard "
      "copied, else the branch its checkout has out). Default empty.",
      "New cards", rule=bases_rule, trim=True),
    S("topic", "space", "text", None, "Topic",
      "The topic a new card is filed under when it names none. Empty: no topic.", "New cards"),
    S("confirm", "space", "list", ("repo", "model"), "Always say back",
      "The fields a new card's readback always names when you did not state them. Default repo "
      "and model.", "New cards"),
    S("house_review", "space", "bool", True, "Review before the gate",
      "On: a repo card's house runs review, verify, preship and risk before its outcome gate. "
      "Default on.", "Review"),
    S("review_full_rounds", "space", "int", None, "Full review passes",
      "This space's full review passes per trip. Empty: Shipyard's setting.", "Review", low=1, high=10),
    S("reviewer_model", "space", "model", "inherit", "Reviewer and verifier model",
      "The model the house's reviewer and verifier run on: inherit is the house's own. Not the "
      "review model, which is the model of a review card. Default inherit.", "Review",
      choices=("inherit",)),
    S("preship_first", "space", "bool", False, "Preship first",
      "On: preship (rebase, push, the draft) runs before review and verify, on the head that "
      "ships. Default off.", "Review"),
    S("review_scan", "space", "bool", True, "Bring me review requests",
      "On: each {change} that asks for your review becomes a review card on Reviews, where the "
      "space's connection can find them. Off: none is brought. A connection may start it off for its "
      "spaces. "
      "Default on.", "Review"),
    S("review_auto", "space", "bool", False, "Auto review",
      "On: a new review card starts by itself. Off: it waits in the inbox for your Review. The "
      "Reviews gear may override it. Default off.", "Review"),
    S("review_model", "space", "model", None, "Review model",
      "The model a new review card runs on. Empty: sonnet. The Reviews gear may override it.",
      "Review"),
    S("review_backlog_days", "space", "int", 15, "Quiet review backlogs after",
      "A review card whose {change} has been quiet this many days moves to the backlog. "
      "Default 15.", "Review", low=1, high=365, unit="days"),
    S("review_sibling_hours", "space", "int", 48, "Wait for the other repo",
      "How long a review card waits for its {ticket}'s {change} in another repo before it is "
      "reviewed alone. Default 48 hours.", "Review", low=0, high=720, unit="h"),
    S("ship_auto_comments", "space", "bool", False, "Handle review comments automatically",
      "On: each new comment or review asking for changes on a shipping card's {change} goes to its "
      "house as it arrives. Off: it waits on the card until you hand it over. A card may set its "
      "own. Default off.", "Tests and shipping"),
    S("ship_auto_checks", "space", "bool", False, "Handle failing checks automatically",
      "On: a check that fails on a shipping card's {change} goes to its house as it arrives. Off: "
      "it waits on the card until you hand it over. A card may set its own. Default off.",
      "Tests and shipping"),
    S("remote", "space", "text", "origin", "Remote",
      "The git remote this space's repos fetch from and push to. Default origin.",
      "Tests and shipping", rule=remote_rule),
    # Both default off, so an install that was set up before them does not start fetching by
    # itself (c-678 review F1); the first run writes both on for the space it makes
    # (`onboarding.add_space`).
    S("fetch_before_work", "space", "bool", False, "Fetch before work",
      "In a space with no connection: before a card starts on a repo Shipyard copied, Shipyard fetches the "
      "remote and fast-forwards its copy, so the card builds on what your team has. The first "
      "run turns it on for the space it makes. Default off.",
      "Tests and shipping"),
    S("offer_push", "space", "bool", False, "Offer Push after a landing",
      "In a space with no connection: a card whose work was merged on this computer carries a Push "
      "button. Nothing is pushed without your tap. Off: no button. The first run turns it on "
      "for the space it makes. Default off.",
      "Tests and shipping"),
    S("branch", "space", "text", "shipyard/{id}-{slug}", "Card branch",
      "How a new card's branch is named in a space with no pack: {id} is the card's id, {slug} "
      "its title in a few words. A pack names its own branches. A card cut under the default, "
      "or as keel/<id>-... before, keeps its branch. Change it when no card of this space is "
      "in flight. Default shipyard/{id}-{slug}.",
      "Tests and shipping", rule=branch_rule),
    # ----- [voice], the voice gateway's -----
    S("space_default", "voice", "text", "personal", "Capture space",
      "Where a voice capture is filed unless the page says otherwise. Default personal.", "Voice"),
    S("mode_default", "voice", "choice", "capture", "Starting mode",
      "The mode the voice page opens in the first time. Default capture.", "Voice",
      choices=("capture", "talk")),
    S("engine_default", "voice", "choice", "google", "Voice",
      "Which synthesiser speaks: google or kokoro. Default google.", "Voice",
      choices=("google", "kokoro")),
    S("vad", "voice", "choice", "auto", "End of sentence detector",
      "auto: a detector hears when you stop. off: a long pause backstop only. Default auto.",
      "Voice", choices=("auto", "off")),
    S("vad_hangover", "voice", "float", 2.0, "Silence that ends a sentence",
      "How long a silence ends what you are saying. Default 2.0 seconds.", "Voice",
      low=0.2, high=10.0, unit="s"),
    S("kept_alive", "voice", "bool", True, "One process per conversation",
      "On: a conversation with a house is one kept-alive process, which answers sooner. Default on.",
      "Voice"),
    S("harbor_kept_alive", "voice", "bool", False, "Harbor kept alive",
      "On: Harbor's own voice turns run the same way, one process streamed. Default off.", "Voice"),
    S("record", "voice", "bool", False, "Record utterances",
      "On: every utterance is recorded on this machine to tune the detector, kept 14 days. "
      "Default off.", "Voice"),
    # ----- [builder], the install's builder's (c-632) -----
    S("mode", "builder", "choice", "auto", "Builder permissions",
      "auto: Claude's classifier reviews what the builder does. bypass: nothing asks or reviews, "
      "and it approves its own cards onto the integration branch; it still never edits a live "
      "checkout. Read when its session starts. Default auto.", "Builder",
      choices=("auto", "bypass")),
)
del S

# This machine's keys (c-610 S1): read from `[machine]` first, then from `[keel]` where a
# pre-split file put them. `keel/config.py` reads them under these names.
MACHINE_KEYS = ("state_dir", "segments_dir", "fetch_lock_dir", "adapters_dir", "serve_port",
                "lavish_port", "lavish_state", "host", "artifact_roots",
                "stack_guard_hook", "usage_file", "harbor_dir")
# `[machine] voice_<key>` for the three `[voice]` keys that are this machine's, not a choice.
VOICE_MACHINE_KEYS = ("port", "app_url", "deck_url")
# This machine's limits, under `[keel]` (`keel/drain.py` reads them).
KEEL_LIMITS = ("browsers_max", "memory_floor_mb", "house_mb", "house_nice", "idle_resume_minutes")
# The keys whose value is a path, which `keel/config.py` resolves against the code root when
# it is relative (c-725 r2.F10): the deploy's preflight walks them, so a tree that removes what
# one names is refused (`keel/deploypreflight.py`). A space's `repos` are paths too, each value.
PATH_KEYS = {
    "space": ("config_dir", "contract", "projects_dir", "pipeline"),
    "machine": ("state_dir", "segments_dir", "fetch_lock_dir", "adapters_dir", "lavish_state",
                "artifact_roots", "stack_guard_hook", "usage_file", "harbor_dir"),
}
STRUCTURAL = {
    "keel": MACHINE_KEYS + KEEL_LIMITS,
    "space": ("config_dir", "repos", "contract", "pack", "adapter", "deny", "allow",
              "projects_dir", "pipeline"),
    "voice": VOICE_MACHINE_KEYS + ("judges", "judge_floors"),
    "builder": ("superuser", "repos"),
}

BY_ID = {setting.id: setting for setting in SETTINGS}


def of(table: str) -> tuple[Setting, ...]:
    return tuple(setting for setting in SETTINGS if setting.table == table)


def find(table: str, key: str) -> Setting | None:
    return BY_ID.get(f"{table}.{key}")


def default(table: str, key: str):
    """A setting's default, which `Config` and `Space` take as their field defaults."""
    return BY_ID[f"{table}.{key}"].default


def known(table: str) -> set[str]:
    return {setting.key for setting in of(table)} | set(STRUCTURAL[table])


# ----- one value -----

def expected(setting: Setting) -> str:
    """What a setting may be, in words."""
    span = ""
    if setting.low is not None and setting.high is not None:
        span = f" from {setting.low:g} to {setting.high:g}"
    elif setting.low is not None:
        span = f" of {setting.low:g} or more"
    if setting.kind == "bool":
        return "true or false"
    if setting.kind == "int":
        return "a whole number" + span
    if setting.kind == "float":
        return "a number" + span
    if setting.kind == "choice":
        return "one of " + ", ".join(setting.choices)
    if setting.kind == "model":
        extra = "".join(f"{word}, " for word in setting.choices)
        return f"a model: {extra}{', '.join(MODELS)}, or a full claude-... id"
    if setting.kind == "list":
        return "a list of words"
    return "text"


def parse(setting: Setting, value, space: str | None = None):
    """`value` as the setting's type, or SettingError naming the key, the value and what it may be."""
    def wrong() -> SettingError:
        return SettingError(f"{setting.where(space)} = {value!r} is not {expected(setting)}")
    kind = setting.kind
    if kind == "bool":
        if not isinstance(value, bool):
            raise wrong()
        return value
    if kind in ("int", "float"):
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise wrong()
        if kind == "int" and not isinstance(value, int):
            raise wrong()
        if isinstance(value, float) and not math.isfinite(value):
            raise wrong()
        if (setting.low is not None and value < setting.low) or (
                setting.high is not None and value > setting.high):
            raise wrong()
        return float(value) if kind == "float" else value
    if kind == "list":
        if not isinstance(value, (list, tuple)) or not all(isinstance(item, str) for item in value):
            raise wrong()
        value = tuple(value)
        if setting.trim:        # c-732 r1.F13: only a list that asks drops blanks and edge spaces
            value = tuple(item.strip() for item in value if item.strip())
        if setting.rule is not None:
            try:
                setting.rule(value)
            except ValueError as error:
                raise SettingError(f"{setting.where(space)} = {list(value)!r}: {error}") from None
        return value
    if not isinstance(value, str):
        raise wrong()
    if kind == "choice" and value not in setting.choices:
        raise wrong()
    if kind == "model" and value not in setting.choices and model_problem(value):
        raise wrong()
    if setting.rule is not None:
        try:
            setting.rule(value)
        except ValueError as error:
            raise SettingError(f"{setting.where(space)} = {value!r}: {error}") from None
    return value


# ----- one table -----

def unknown_line(where: str, key: str, table: str) -> str:
    """`[spaces.personal] house_reveiw is not a key; did you mean house_review?`"""
    near = difflib.get_close_matches(key, sorted(known(table)), n=1, cutoff=0.7)
    return f"{where} {key} is not a key" + (f"; did you mean {near[0]}?" if near else "")


def shown(value) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    if value is None:
        return "unset"
    if isinstance(value, (list, tuple)):
        return ", ".join(value) or "none"
    return str(value)


def check(values: dict, table: str, where: str, space: str | None = None) -> tuple[dict, list[str]]:
    """Every setting of `table` typed, its default where the table leaves it out or gives a
    value it may not take, and the warnings: one per wrong value (what it was, what it may
    be, the default used instead) and one per key the table does not know."""
    typed, warnings = {}, []
    for setting in of(table):
        typed[setting.key] = setting.default
        if setting.key not in values:
            continue
        try:
            typed[setting.key] = parse(setting, values[setting.key], space)
        except SettingError as error:
            typed[setting.key] = setting.if_wrong
            if setting.fallback is DEFAULT:
                warnings.append(f"{error}; the default ({shown(setting.default)}) is used")
            else:
                warnings.append(f"{error}; {shown(setting.if_wrong)} is used, the safe position")
    for key in values:
        if key not in known(table):
            warnings.append(unknown_line(where, key, table))
    return typed, warnings


def unknown_only(values: dict, table: str, where: str) -> list[str]:
    """The unknown-key warnings alone: a pack's `[space]`, whose values are checked once
    they are laid under the space's own table."""
    return [unknown_line(where, key, table) for key in values if key not in known(table)]


# ----- the Settings view (`GET /api/settings`, `setup.settings.save`) -----

def plain(value):
    return list(value) if isinstance(value, tuple) else value


def schema_row(setting: Setting) -> dict:
    from keel import terms              # noqa: PLC0415 - terms reads packs, which read the config's paths
    return {"id": setting.id, "key": setting.key, "table": setting.table, "scope": setting.scope,
            "kind": setting.kind, "default": plain(setting.default), "label": setting.label,
            "help": terms.say(None, setting.help), "group": setting.group, "choices": list(setting.choices),
            "low": setting.low, "high": setting.high, "unit": setting.unit}


def value_of(holder, setting: Setting):
    """The value in force: a `[builder]` key from the table as written (`Config.builder`),
    every other from its `Config` or `Space` field."""
    if setting.table == "builder":
        return (getattr(holder, "builder", None) or {}).get(setting.key, setting.default)
    return getattr(holder, setting.attr, setting.default)


def value_row(holder, setting: Setting, source_key: str, provenance: dict) -> dict:
    return {"value": plain(value_of(holder, setting)), "source": provenance.get(source_key, "default")}


def pack_defaults(space) -> dict:
    """The pack's `[space]` defaults the config laid under this space (`Space.pack_space`,
    `config.adapter_of`): the same table the values in force were read from, so an
    `adapter =` space, which gets none laid, names no pack default either (r1.F6)."""
    return dict(getattr(space, "pack_space", None) or {})


def space_values(cfg, name: str, space) -> dict:
    """One space's values, with the Reviews gear's live override shown as the value in force
    (decision gear-override: shown)."""
    from keel import reviewsettings     # noqa: PLC0415 - it reads the state; the schema does not
    provenance = getattr(cfg, "provenance", {}) or {}
    rows = {s.id: value_row(space, s, f"spaces.{name}.{s.key}", provenance) for s in of("space")}
    # c-730: a value the space's pack sets (its `[space]`) is that space's default, so the
    # form says it and goes back to it, not to Shipyard's own default
    laid = pack_defaults(space)
    for s in of("space"):
        if s.key in laid:
            rows[s.id]["default"] = plain(laid[s.key])
    live = reviewsettings.overrides(cfg).get(name)
    if isinstance(live, dict):
        if isinstance(live.get("auto"), bool):
            rows["space.review_auto"] = {"value": live["auto"], "source": "gear"}
        if live.get("model") in reviewsettings.REVIEW_MODELS:
            rows["space.review_model"] = {"value": live["model"], "source": "gear"}
    return rows


def space_helps(cfg) -> dict:
    """Each space's help for the settings whose help names a ticket or a change, in that
    space's own words (`terms.of`)."""
    from keel import terms              # noqa: PLC0415
    worded = [s for s in of("space") if "{" in s.help]
    return {name: {s.id: terms.say(terms.of(cfg, space), s.help) for s in worded}
            for name, space in cfg.spaces.items()}


def report(cfg) -> dict:
    """What the Settings view draws: the install (None: shown read-only, as Setup does), the
    schema, the groups in order, every value with where it came from (`config`, `pack`,
    `default`, or `gear` for a live review override), and each space's worded help."""
    from keel import setupconfig        # noqa: PLC0415 - setupconfig imports config, which imports this
    provenance = getattr(cfg, "provenance", {}) or {}
    home = setupconfig.installed(cfg)
    install = {s.id: value_row(cfg, s, f"{s.table}.{s.key}", provenance)
               for s in SETTINGS if s.scope == "install"}
    return {"install": str(home) if home else None, "config": str(cfg.source),
            "groups": list(GROUPS), "schema": [schema_row(s) for s in SETTINGS], "models": list(MODELS),
            "values": {"install": install,
                       "spaces": {name: space_values(cfg, name, space) for name, space in cfg.spaces.items()}},
            "helps": space_helps(cfg), "warnings": list(getattr(cfg, "warnings", []) or [])}


def planned(cfg, changes) -> list[tuple[Setting, str | None, object]]:
    """Each change checked before anything is written: a known setting, a space that exists,
    and a value it may take (null removes the key, so the default applies again)."""
    from keel.setupconfig import SetupError, space_of     # noqa: PLC0415
    if not isinstance(changes, list) or not changes:
        raise SetupError("nothing to save: changes is a list of {table, space?, key, value}")
    out = []
    for change in changes:
        if not isinstance(change, dict):
            raise SetupError(f"a change is {{table, space?, key, value}}, not {change!r}")
        setting = find(str(change.get("table") or ""), str(change.get("key") or ""))
        if setting is None:
            raise SetupError(f"there is no setting {change.get('key')!r} in {change.get('table')!r}")
        space = str(change.get("space") or "") or None
        if setting.scope == "space":
            space_of(cfg, space or "")
        value = change.get("value")
        if value is not None:
            try:
                value = parse(setting, value, space)
            except SettingError as error:
                raise SetupError(str(error)) from None
        if setting.id == "space.bases" and value:
            found = cfg.spaces.get(space or "")
            if found is not None and found.repos and len(integrated(cfg, found)) == len(found.repos):
                # c-732 r2.F4: its cards land on an integration branch, which no base overrides
                raise SetupError(f"every repo of {space} lands on its integration branch, so a card there "
                                 f"names no base: nothing to save")
        out.append((setting, space, value))
    return out


def section(setting: Setting, space: str | None) -> str:
    return f"spaces.{space}" if setting.scope == "space" else setting.table


# The settings that decide whether the builder is the Full builder (`builder.bypass_chosen`).
BUILDER_FORM = ("builder.mode", "keel.bosun_builder")


def save(cfg, changes) -> dict:
    """Write every change in one `setupconfig.edit`: one backup, one reload, one re-exec. A
    saved `review_auto` or `review_model` clears the Reviews gear's override of it, so the
    value just saved is the one in force."""
    import tomllib                                       # noqa: PLC0415
    from keel import configedit, reviewsettings, setupconfig     # noqa: PLC0415
    setupconfig.install_of(cfg)
    steps = planned(cfg, changes)

    def apply(text: str) -> str:
        for setting, space, value in steps:
            table = section(setting, space)
            if value is not None:
                text = configedit.set_entry(text, table, setting.key, value)
                continue
            found = tomllib.loads(text)
            for part in table.split("."):
                found = found.get(part, {}) if isinstance(found, dict) else {}
            if isinstance(found, dict) and setting.key in found:
                text = configedit.remove_entry(text, table, setting.key)
        return text

    done = setupconfig.edit(cfg, apply)
    for setting, space, _ in steps:
        if setting.id in ("space.review_auto", "space.review_model"):
            reviewsettings.clear(cfg, space, "auto" if setting.key == "review_auto" else "model")
    note = bypass_after(cfg) if any(s.id in BUILDER_FORM for s, _, _ in steps) else None
    return {**done, "saved": [f"{section(s, space)}.{s.key}" for s, space, _ in steps],
            "voice": any(s.table == "voice" for s, _, _ in steps), **({"note": note} if note else {})}


def bypass_after(cfg) -> str | None:
    """c-729: Full builder is the acceptance of bypass mode, read off the config as saved
    (`builder.record_bypass`). Best effort (r1.F5): the config is already written, so a
    Claude folder that cannot be written, or a config that does not load, is said in the
    save's answer and never undoes or fails the save."""
    from keel import builder, config as config_module     # noqa: PLC0415
    try:
        builder.record_bypass(config_module.load(cfg.source, ensure=False))
    except (OSError, config_module.ConfigError) as error:
        return (f"saved; Claude Code's acceptance of bypass mode could not be recorded ({error}), "
                f"so Bosun in bypass may ask for it once")
    return None
