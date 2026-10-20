"""The card defaults: ONE resolver every new card goes through, with where each value came from.

`Board.create` is the seam. The composer, voice capture, the talker, `kb create`, a house's
follow-up and the recurring filer all end there (the deck and the voice through `kb`), and
so does `Board.split`, so nothing can file a card around this module.

Each tracked field is filled from the first layer that has it, and the layer is recorded
as its provenance in the card's own `options.provenance`:

    stated         the creator gave it
    assumed        the creator gave it and said it was a guess (`kb create --assumed repo,topic`)
    inherited      the card it came out of (`--from`), else its parent, had it
    space_default  the space's own (`[spaces.<s>] model`, `autonomy`, `topic`, or its option
                   sheet's default)
    keel_default   Keel's own (`[keel] model`, else `models.KEEL_MODEL`; autonomous, no repo,
                   no topic)

The space and Keel layers are settings (c-633, `keel/settings.py`): a space's `model`,
`autonomy`, `plan_style` and `topic`, and `[keel] model`. A space's plan style is not a
tracked field; it is the default of the sheet's Plan style row, and the brief says it when
the card names none (`keel/planbrief.py`).

The tracked card fields are `repo`, `model`, `autonomy` and `topic`. An option key the
space's `confirm` list names (the work space's `base`, `tracker_mode`, `design_doc`) is
tracked too, but only its provenance is written: a default stays the sheet's, read where
it is used, and is never copied into the options.

A slice starts as its parent would (c-760). A card with a parent and no `--from` also takes
the parent's STATED value of every option key the space's sheet declares, unless the slice
states its own; every key taken that way is `inherited`. Only sheet rows travel, so
none of the parent's bookkeeping does, and four kinds of row stay behind: the parent's own
(`OWN`: its ticket reference, its branch and worktrees), every option a creator could not
state at create (the board's own lists, handed in as `held`), free text written for it (a
`textarea` row), and a row its pack marks `"inherit": false`. `kind` travels, unless the
parent's is research or review (`OWN_KINDS`). "Stated" is "present
in the parent's options": a value the parent never held is not copied, and the default
stays the sheet's. A parent filed from the deck's form holds every row's value, the form's
defaults included, so all of them count as stated and a slice is pinned as its parent is.
A slice that took a mode and not the parent's own row that the mode picks is filed blocked
(`left_behind`, narrow on purpose). A follow-up (`--from`) is new work that came out of a card, so it takes
the four fields and none of the options.

Nothing is left null for the environment to fill. `model` in particular always ends with a
value, which is the c-434 fix: a card with no model reached `claude` with no `--model` and
ran on the account's own default.

`readback` is the one line a creator says back ("Filed c-450 in keel, opus, topic boards
(repo and topic assumed)"). Code writes it from the stored card, so every creator says the
same thing and none of them has to remember which fields may not pass silently: the
space's `confirm` list decides, and a confirm field that was not stated is always named.

`corrections` is the other half. A later `kb set` of a field that was not stated is his
correction of what was assumed, and it is recorded as a `correct` event on the card (the
one store) with the field, the old value, the new one and the provenance it replaced. The
field is then `stated`: it is his.
"""

import json
from dataclasses import dataclass, field

from keel import bases, settings
from keel.models import KEEL_MODEL, MODELS, model_problem

PROVENANCE_OPTION = "provenance"
STATED, ASSUMED, INHERITED, SPACE, KEEL = ("stated", "assumed", "inherited", "space_default",
                                          "keel_default")
# The card fields every card carries a provenance for, in the order a readback names them.
TRACKED = ("repo", "model", "autonomy", "topic")
# Keel's own layer: what a field is when nobody and nothing else says.
KEEL_DEFAULTS = {"repo": None, "model": KEEL_MODEL, "autonomy": "autonomous", "topic": None}
# How a readback says each provenance, in the order the groups are said.
SAID = ((ASSUMED, "assumed"), (INHERITED, "inherited from {source}"),
        (SPACE, "the space default"), (KEEL, "Shipyard's default"))
# c-760: the parent's own, which a slice never takes even where a sheet declares the key:
# the one ticket it points at, where it was cut, what holds it. The options no creator may
# state at create are held back too, and those the board names (`held`, r1.F6): its own
# constants, so a new one is covered by adding it there and nowhere else.
OWN = ("tracker_ref", "branch", "worktree", "worktrees", "claim", "app_link", "peak_mb",
       PROVENANCE_OPTION)
# r2.F1: a card's `kind` travels (a bug card's slices are bug slices, and nothing at a split
# can say so), except the two that say what the PARENT was for: a research card opens no
# change and a review card reads someone else's, and a slice of either is an ordinary card.
OWN_KINDS = ("research", "review")
# A sheet row type whose value is prose written for the one card: it does not travel.
FREE_TEXT = ("textarea",)


class SpecError(ValueError):
    """A card the resolver will not fill as asked; `Board.create` turns it into `Refused`."""


@dataclass
class SpaceDefaults:
    """One space's layer: its model, autonomy, plan style and topic, its confirm list, and
    its option sheet."""

    model: str | None = None
    confirm: tuple[str, ...] = ("repo", "model")
    sheet: list[dict] = field(default_factory=list)
    autonomy: str | None = None
    plan_style: str | None = None
    topic: str | None = None

    def own(self, name: str):
        """The space's own value of a tracked field, or None: the layer below decides."""
        return getattr(self, name, None) if name in ("model", "autonomy", "topic") else None

    def option_default(self, key: str, options: dict):
        """The sheet's default for an option key, `default_if` evaluated over `options`."""
        entry = next((e for e in self.sheet if e.get("key") == key), None)
        if entry is None:
            return None
        if "default_if" in entry:
            return condition(entry["default_if"], dict(self.static_defaults(), **options))
        return entry.get("default")

    def static_defaults(self) -> dict:
        return {e["key"]: e["default"] for e in self.sheet if "default" in e}

    def label(self, key: str) -> str:
        entry = next((e for e in self.sheet if e.get("key") == key), {})
        return str(entry.get("label") or key.replace("_", " ")).lower()


@dataclass
class Defaults:
    """Every space's layer, and Keel's own model (`[keel] model`). A space it does not know
    gets Keel's own, and nothing more."""

    spaces: dict[str, SpaceDefaults] = field(default_factory=dict)
    keel_model: str = KEEL_MODEL

    def for_space(self, name: str) -> SpaceDefaults:
        return self.spaces.get(name) or SpaceDefaults()

    def keel(self, name: str):
        """Keel's own value of a tracked field."""
        return self.keel_model if name == "model" else KEEL_DEFAULTS[name]


def defaults_from(cfg) -> Defaults:
    """The layer the config and each space's option sheet declare."""
    keel_model = getattr(cfg, "model", None) or KEEL_MODEL
    return Defaults({name: SpaceDefaults(model=space.model, confirm=tuple(space.confirm),
                                         sheet=sheet(space, keel_model),
                                         autonomy=chosen(cfg, name, space, "autonomy"),
                                         plan_style=chosen(cfg, name, space, "plan_style"),
                                         topic=chosen(cfg, name, space, "topic"))
                     for name, space in cfg.spaces.items()}, keel_model=keel_model)


def chosen(cfg, name: str, space, key: str):
    """A space's own value of a setting when its config (or its pack) gave one, or it differs
    from the schema's default; None otherwise, so an untouched space leaves the field to
    Keel's layer and its provenance says so."""
    value = getattr(space, key, None)
    said = f"spaces.{name}.{key}" in (getattr(cfg, "provenance", None) or {})
    return value if said or value != settings.default("space", key) else None


# ----- the option sheet (what the deck's card dialog offers, and the defaults it shows) -----

PLAN_STYLE = {"key": "plan_style", "label": "Plan style", "type": "select", "stored": "options",
              "options": ["auto", "markdown", "lavish"], "default": "auto",
              "help": "auto lets the house choose: a lavish surface for a design choice, a page otherwise"}


def model_row(space, keel_model: str = KEEL_MODEL) -> dict:
    """The sheet's model select: real models only, the space's own as the default, else
    Keel's (`[keel] model`).

    It used to offer "" labelled "(default)", which meant the ACCOUNT's default and is how
    a composer card ran on Fable (c-434). The row is built here for both sheets, so an
    adapter's options.json cannot bring that option back.
    """
    default = space.model or keel_model
    names = list(dict.fromkeys([default, *MODELS]))
    return {"key": "model", "label": "Model", "type": "select", "stored": "card",
            "options": names, "default": default,
            "help": f"the model the house runs on; {default} is this space's default"}


def builtin_sheet(space, keel_model: str = KEEL_MODEL) -> list[dict]:
    return [
        {"key": "repo", "label": "Repo", "type": "multiselect", "stored": "card",
         "options": list(space.repos), "default": [],
         "help": "empty: research, a plan or an errand, a house's (no worktree); a repo: code, "
                 "which Bosun builds on a personal card in builder mode"},
        {"key": "new_project", "label": "New project", "type": "text", "stored": "card",
         "when": "repo == none",
         "help": "a name opens a fresh repo of that name under the space's projects "
                 "directory, and the card plans it first"},
        {"key": "autonomy", "label": "Autonomy", "type": "select", "stored": "card",
         "options": ["attended", "autonomous"], "default": "autonomous"},
        model_row(space, keel_model),
        PLAN_STYLE,
    ]


def space_row(entry: dict, space, keel_model: str) -> dict:
    """A sheet row with the space's own default where it has a setting for it (c-633): the
    model row from `model_row`, and the autonomy and plan style rows' defaults from the
    space's `autonomy` and `plan_style`. A pack's repo row that lists no repos of its own
    offers the space's (c-689): a pack for whatever a person clones cannot name them."""
    if entry.get("key") == "model":
        return model_row(space, keel_model)
    if entry.get("key") == "repo" and not entry.get("options"):
        return dict(entry, options=list(space.repos))
    own = getattr(space, entry.get("key") or "", None) if entry.get("key") in ("autonomy", "plan_style") else None
    return dict(entry, default=own) if own else entry


def sheet(space, keel_model: str = KEEL_MODEL, integrated=()) -> list[dict]:
    """The adapter's options.json for a space with one, the built-in subset otherwise,
    with the model, autonomy and plan style rows' defaults the space's (`space_row`), and
    Base branch from the space's bases (`bases.row`, c-732)."""
    if space.adapter_dir is None:
        entries = builtin_sheet(space, keel_model)
    else:
        try:
            entries = json.loads((space.adapter_dir / "options.json").read_text())
        except (OSError, ValueError):
            return []
    # c-732: Base branch, a select of the space's bases, unless its pack keeps its own select
    # (`integrated`: the repos whose cards land on an integration branch, which take no base)
    return bases.row(space, [space_row(entry, space, keel_model) for entry in entries], integrated)


# ----- the sheet's condition language (`key == value and key != value`) -----

def coerce(text: str):
    lowered = text.strip().lower()
    if lowered in ("true", "false"):
        return lowered == "true"
    return None if lowered in ("none", "null", '""', "''") else text.strip()


def clause(text: str, values: dict) -> bool:
    for operator in ("==", "!="):
        key, found, raw = text.partition(operator)
        if found:
            expected, actual = coerce(raw), values.get(key.strip())
            if expected is None:
                same = actual in (None, "", "none", False)
            else:
                same = actual is not None and str(actual).lower() == str(expected).lower()
            return same if operator == "==" else not same
    raise SpecError(f"bad condition clause {text!r}")


def condition(text: str, values: dict) -> bool:
    """The option sheet's `when`/`default_if` rule, as the deck's sheet evaluates it."""
    return all(clause(part, values) for part in text.split(" and ")) if text.strip() else True


# ----- resolve -----

def given(value) -> bool:
    return value not in (None, "", [])


def resolve(defaults: Defaults, space: str, fields: dict, assumed=(),
            source: dict | None = None, parent: dict | None = None,
            held=()) -> tuple[dict, list[dict]]:
    """The four tracked fields filled and `options` carrying their provenance, and what the
    card now needs that its parent's value did not fill (`left_behind`, empty for a card
    that is no slice).

    `fields` is what the creator gave (`repo`, `model`, `autonomy`, `topic`, `options`);
    `assumed` names the given ones that were guesses; `source` is the card this one
    inherits from (its `from`, else its parent), as a read or a row returns it; `parent`
    is the card it is a slice of, whose stated options it takes too (`taken`, c-760);
    `held` names the option keys the board lets no slice take (`Board._resolve`).
    """
    assumed = set(assumed or ())
    unknown = sorted(name for name in assumed if not given(fields.get(name))
                     and not given((fields.get("options") or {}).get(name)))
    if unknown:
        raise SpecError(f"--assumed names {', '.join(unknown)}, which the card was not given")
    layer = defaults.for_space(space)
    out, tags = {}, {}
    keel = {name: defaults.keel(name) for name in TRACKED}
    for name in TRACKED:
        out[name], tags[name] = pick(name, fields.get(name), assumed, source, layer, keel)
    problem = model_problem(out["model"])
    if problem:
        raise SpecError(problem)
    options = dict(fields.get("options") or {})
    sheet = Sheet(space, layer, tuple(held))
    handed = taken(sheet, dict(out, options=options), parent)
    missing = left_behind(sheet, dict(out, options=options), parent, handed)
    for key in layer.confirm:
        if key not in TRACKED:
            tags[key] = (ASSUMED if key in assumed else STATED) if given(options.get(key)) else SPACE
    # r2.F2: every row a slice took is tagged, on the confirm list or not, so it can be told
    # from one the slice stated, and a later `kb set` of it is recorded as a correction
    tags.update({key: INHERITED for key in handed})
    options.update(handed)
    options[PROVENANCE_OPTION] = tags
    return dict(out, options=options), missing


def pick(name: str, value, assumed: set, source: dict | None, layer: SpaceDefaults,
         keel: dict | None = None):
    """One field's value and provenance: stated or assumed, inherited, space, keel."""
    keel = keel or KEEL_DEFAULTS
    if given(value):
        return value, ASSUMED if name in assumed else STATED
    if source is not None and given(source.get(name)):
        return source[name], INHERITED
    if given(layer.own(name)):
        return layer.own(name), SPACE
    return keel[name], KEEL


# ----- a slice's options (c-760) -----

def options_of(card: dict | None) -> dict:
    """A card's options, from a read (a dict) or a row (the column's JSON)."""
    found = (card or {}).get("options") or {}
    found = json.loads(found) if isinstance(found, str) else found
    return found if isinstance(found, dict) else {}


@dataclass
class Sheet:
    """A space's sheet as a slice's resolve reads it: the space's name (a refusal says it),
    its layer, and the keys the board holds back."""

    space: str
    layer: SpaceDefaults
    held: tuple[str, ...] = ()

    def travels(self, entry: dict) -> bool:
        """Whether a slice takes its parent's value of this sheet row."""
        return (entry.get("stored") == "options" and entry.get("key") not in (None, *OWN, *self.held)
                and entry.get("type") not in FREE_TEXT and entry.get("inherit") is not False)

    def holds(self, entry: dict, values: dict) -> bool:
        """The row's `when` over `values`. One the board cannot read refuses, naming the
        row and the space (r1.F5): a row is never skipped silently."""
        try:
            return condition(entry.get("when") or "", values)
        except SpecError as why:
            raise SpecError(f"the {self.space} sheet's row {entry['key']} has a `when` the board "
                            f"cannot read: {why}") from None

    def seen(self, card: dict, options: dict) -> dict:
        """What a `when` is asked over: the sheet's defaults, the card's fields, its options."""
        fields = {name: card.get(name) for name in TRACKED}
        return {**self.layer.static_defaults(), **fields, **options}


def picked_by(text: str) -> list[str]:
    """The keys whose one value a `when` picks the row for (`key == value`), in its order. A
    clause that only rules a value out (`key != value`) picks nothing: it shows the row for
    every other value, which says nothing about the row being needed."""
    parts = [part.partition("==")[0].strip() for part in text.split(" and ")
             if "==" in part and "!=" not in part]
    return list(dict.fromkeys(part for part in parts if part))


def taken(sheet: Sheet, card: dict, parent: dict | None) -> dict:
    """The option values a slice takes from its parent: what the parent stated, for each
    sheet row that travels and the slice did not state, where the row's own `when` holds on
    the slice (a slice that states "no ticket" does not carry the parent's ticket rows)."""
    mine, theirs = options_of(card), options_of(parent)
    rows = {entry["key"]: entry for entry in sheet.layer.sheet
            if sheet.travels(entry) and entry["key"] not in mine and given(theirs.get(entry["key"]))
            and not (entry["key"] == "kind" and str(theirs["kind"]).lower() in OWN_KINDS)}
    found = {key: theirs[key] for key in rows}
    while True:
        values = sheet.seen(card, {**mine, **found})
        off = [key for key in found if not sheet.holds(rows[key], values)]
        if not off:
            return found
        for key in off:
            del found[key]


def left_behind(sheet: Sheet, card: dict, parent: dict | None, handed: dict) -> list[dict]:
    """The parent's own rows a slice is held for, each as `{key, label, shown}`: a row in
    `OWN` (the reference to one ticket), which the parent had and the slice has not, whose
    `when` holds on the slice and picks the row for a value the slice INHERITED (`shown`:
    those keys and values, `picked_by`). A parent linked to one ticket hands its slices the
    mode and not the ticket, so each such slice is held until it has its own
    (`Board._hold_left_behind`).

    Narrow on purpose: a `when` is the form's show-this-field rule, not a requirement. So
    only the parent's own artifact holds a slice, never a row outside the parent's own that
    a pack marks `inherit: false`, nor an owner-only key, and never for a `when` that only
    rules a value out. `inherit` is not read here: one of the parent's own rows holds a
    slice whether or not its pack also marks it."""
    mine, theirs = options_of(card), options_of(parent)
    values, found = sheet.seen(card, {**mine, **handed}), []
    for entry in sheet.layer.sheet:
        key = entry.get("key")
        if (entry.get("stored") != "options" or key not in OWN or key == PROVENANCE_OPTION
                or not entry.get("when") or not given(theirs.get(key)) or given(mine.get(key))
                or not sheet.holds(entry, values)):
            continue
        shown = [{"key": name, "value": handed[name]} for name in picked_by(entry["when"])
                 if name in handed]
        if shown:
            found.append({"key": key, "label": sheet.layer.label(key), "shown": shown})
    return found


def held_reason(row: dict, parent_id: str, card_id: str) -> str:
    """Why a slice is held for one `left_behind` row, claiming no more than is known: whose
    the row was, which inherited value shows it, and the two ways on (r1.F7)."""
    shown = said_list([f"{one['key']}={words(one['value'])}" for one in row["shown"]])
    keys = said_list([one["key"] for one in row["shown"]])
    states = " or ".join(f"`kb set {card_id} options.{one['key']}=<value>`" for one in row["shown"])
    return (f"{row['label']} was {parent_id}'s own and was not inherited, and this card's inherited "
            f"{shown} shows that row. Give this card its own (`kb set {card_id} "
            f"options.{row['key']}=<value>`) or state a different {keys} ({states}), then unblock it")


def slice_repos(stated, parent_repo, parent_id: str) -> tuple[str | None, str | None]:
    """c-771: `(repos, why not)` for the repos a slice states at the split (a comma list or
    a list). `(None, None)` when it states none and takes its parent's. A slice works in its
    parent's repos or fewer, so a key the parent does not name is refused, and so is a `repo`
    that names nothing. The repos kept are in the PARENT's order whatever order was typed
    (c-772): a card's first repo answers its one-base rules, so a slice's first repo is its
    parent's first among those it keeps, and stating repos only ever narrows. That the space
    can open each key is asked where the config is (`cli.cmd_split`, as for `create`)."""
    if stated is None:
        return None, None
    text = ",".join(map(str, stated)) if isinstance(stated, list) else str(stated)
    keys = [one.strip() for one in text.split(",") if one.strip()]
    theirs = [one.strip() for one in str(parent_repo or "").split(",") if one.strip()]
    named = ", ".join(theirs) or "it names none"
    if not keys:
        return None, f"repo= names no repo; leave it off and the slice takes {parent_id}'s ({named})"
    outside = list(dict.fromkeys(key for key in keys if key not in theirs))
    if outside:
        return None, (f"{', '.join(outside)} is not a repo of {parent_id} ({named}); a slice works in its "
                      f"parent's repos or fewer")
    return ",".join(key for key in theirs if key in keys), None


def without(options: dict, key: str) -> dict:
    """The options with an inherited value given up: the key gone, its provenance the sheet's."""
    tags = dict(options.get(PROVENANCE_OPTION) or {})
    if key in tags:
        tags[key] = SPACE
    kept = {name: value for name, value in options.items() if name != key}
    return {**kept, PROVENANCE_OPTION: tags}


# ----- the readback -----

def shown(card: dict, layer: SpaceDefaults) -> list[tuple[str, str, str]]:
    """(field, its words in the line, its label in the parenthesis), in the line's order."""
    options = card.get("options") or {}
    rows = [("repo", f"in {card['repo']}" if card.get("repo")
             else f"in {card['space']} as an errand", "repo"),
            ("model", str(card.get("model")), "model")]
    if "autonomy" in layer.confirm or card.get("autonomy") == "attended":
        rows.append(("autonomy", str(card.get("autonomy")), "autonomy"))
    if card.get("topic"):
        rows.append(("topic", f"topic {card['topic']}", "topic"))
    for key in layer.confirm:
        if key in TRACKED:
            continue
        value = options.get(key) if key in options else layer.option_default(key, options)
        rows.append((key, f"{layer.label(key)} {words(value)}", layer.label(key)))
    return rows


def words(value) -> str:
    if value is True:
        return "on"
    if value in (False, None, ""):
        return "off"
    return ",".join(value) if isinstance(value, list) else str(value)


def said_list(names: list[str]) -> str:
    return names[0] if len(names) == 1 else f"{', '.join(names[:-1])} and {names[-1]}"


def readback(card: dict, defaults: Defaults) -> str:
    """The one line a creator says back: where it went, what it runs on, and which of
    what it named were not his words (grouped by where they came from)."""
    layer = defaults.for_space(card["space"])
    rows = shown(card, layer)
    line = f"Filed {card['id']} " + ", ".join(text for _, text, _ in rows)
    tags = (card.get("options") or {}).get(PROVENANCE_OPTION) or {}
    source = card.get("from") or card.get("parent") or "its source"
    groups = []
    named = {key for key, _, _ in rows} | set(TRACKED)
    for tag, phrase in SAID:
        names = [label for key, _, label in rows if tags.get(key) == tag]
        if tag == INHERITED:      # r2.F2: and the rows off the confirm list a slice took
            names += [layer.label(key) for key in tags if tags[key] == tag and key not in named]
        if names:
            groups.append(f"{said_list(names)} {phrase.format(source=source)}")
    return f"{line} ({'; '.join(groups)})" if groups else line


# ----- corrections -----

def corrections(row: dict, fields: dict, layer: SpaceDefaults) -> tuple[list[dict], dict | None]:
    """What a `set` corrects: one record per changed field that was not stated, and the
    provenance map with those fields now `stated` (None when nothing was corrected).

    `row` is the card as stored (options decoded); `fields` the update as `set_fields`
    takes it, with option keys under `options`.
    """
    options = row.get("options") or {}
    tags = dict(options.get(PROVENANCE_OPTION) or {})
    found = []
    changes = {name: fields[name] for name in TRACKED if name in fields}
    changes.update({key: value for key, value in (fields.get("options") or {}).items()
                    if key in tags and key not in TRACKED})
    for name, value in changes.items():
        tag = tags.get(name)
        if tag in (None, STATED):
            continue
        was = row.get(name) if name in TRACKED else (
            options[name] if name in options else layer.option_default(name, options))
        if value == was or (value in (None, "") and was in (None, "")):
            continue
        found.append({"field": name, "from": was, "to": value, "provenance": tag})
        tags[name] = STATED
    return found, (tags if found else None)


def correction_text(found: dict) -> str:
    return f"{found['field']}: {json.dumps(found['from'])} ({found['provenance']}) -> {json.dumps(found['to'])}"
