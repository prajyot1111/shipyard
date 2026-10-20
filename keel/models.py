"""The model names Keel hands to `claude --model`, and the defaults behind them.

THE MODEL A HOUSE RUNS ON WHEN NEITHER ITS CARD NOR ITS SPACE SAYS (the overnight
clearance, 2026-09-23). A card with no model used to reach `claude` with no `--model`, and
`claude` then picks the ACCOUNT's own default: c-272 ran five days on Fable that way
(c-434). Every card now leaves create with a model (`keel/cardspec.py`), `KEEL_MODEL` is
the last layer it is filled from, and `harness.session_flags` refuses to build a house's
command line without one.

`known_model` is the one check, used by the config's loader (a space's `model`, a
recurring card's, `[models]`), by the card resolver and by `kb set model=`. It takes the
bare names, the long-context form (`opus[1m]`) and a full model id (`claude-...`), so a
typo is refused where it is typed rather than at the launch that would hand it on.

`[models]` pins Keel's own model turns (`TURN_MODELS`): `converse` is the voice
conversation, and `refine` is the one turn per capture, which shares that conversation's
session but not its model. The talker runs on `converse` too (`talker.environment`, J-4):
Harbor on the phone is the same conversation by another door.
"""

KEEL_MODEL = "opus"
MODELS = ("opus", "sonnet", "haiku", "fable")
LONG_CONTEXT = "[1m]"
FULL_ID = "claude-"
TURN_MODELS = {"converse": "opus", "refine": "sonnet"}
# The login probe's one word (`keel/login.py`): the cheapest turn that proves a login answers.
LOGIN_MODEL = "haiku"


def known_model(name) -> bool:
    """True for a model name `claude --model` is meant to get from Keel."""
    if not isinstance(name, str) or not name.strip():
        return False
    return name.removesuffix(LONG_CONTEXT) in MODELS or (
        name.startswith(FULL_ID) and len(name) > len(FULL_ID))


def model_problem(name) -> str | None:
    """Why `name` cannot be a model, or None when it can."""
    if known_model(name):
        return None
    return (f"{name!r} is not a model; one of {', '.join(MODELS)} (or one of them with "
            f"{LONG_CONTEXT}, or a full {FULL_ID}... id)")
