"""Whether a flow can run (c-664): the check behind `keel flow check` and Adopt.

`flows.parse` checks a flow's SHAPE, and a file of the right shape can still describe
something that never happens. `problems` names each such move and says what to change:

Always:
- a move of yours at a stage with no house (`assigned`, `done`): its tap is always refused;
- `pushes` or `opens` naming the card's own branch, or a branch whose label is words: the
  label IS the git name (`{base}` and `{branch}` filled per card), and a label in words
  names no branch, so `kb flowpush` would have nothing to push;
- a move from a branch to itself.

With the space (`--space`, and always at Adopt):
- a `keel` step the space cannot run: `publish` or `ship` where the space's pack has no
  such verb, `land` where the space has a pack (its Approve publishes instead), any of the
  three in a held space (`flows.held`, whose sentence the refusal carries), `deploy`
  where no repo lands on an `[integration]` branch;
- `opens` where the space's pack does not declare `flow_pr` (`[capabilities]`,
  `keel/packs.py`): its `pr` must take `--flow <branch> --to <target> --dir <worktree>`.

Loading a flow (`flows.of`) never runs this, so a file adopted before the check existed
still loads. It reads and never writes.
"""

from __future__ import annotations

from pathlib import Path

from keel import flowfence, flows, packs

HOUSELESS = ("assigned", "done")
# A keel step, and the pack verb a space needs to run it.
PACK_STEPS = {"publish": "publish", "ship": "ship"}
FLOW_PR = "flow_pr"


def names_branch(label: str) -> bool:
    """Whether a label is a git name once `{base}` and `{branch}` are filled."""
    return flowfence.git_name(label.replace("{base}", "base").replace("{branch}", "branch"))


def problems(found: flows.Flow, cfg=None, space=None) -> list[str]:
    """Every move of the flow that cannot run, each with what to change; with a `space`,
    what that space cannot run too."""
    branches = {one.id: one for one in found.branches}
    out = []
    for move in found.moves:
        out += shape(move, branches)
        if space is not None:
            out += runnable(move, cfg, space)
    return out


def shape(move: flows.Move, branches: dict) -> list[str]:
    what, out = f"move {move.id}", []
    if move.source == move.target:
        out.append(f"{what}: it goes from {move.source} to {move.source}. A move goes from one "
                   f"branch to another: change `from` or `to`")
    idle = ", ".join(stage for stage in move.stages if stage in HOUSELESS)
    if move.yours and idle:
        out.append(f"{what}: it is offered at {idle}, where a card has no house to carry it out, "
                   f"so its tap is always refused. Take {idle} out of `stages`")
    for key in ("pushes", "opens"):
        for branch in (branches[one] for one in getattr(move, key)):
            if branch.kind == "card":
                out.append(f"{what}: {key} names {branch.id}, the card's own branch, which its house "
                           f"pushes itself. Take it out of `{key}`")
            elif not names_branch(branch.label):
                out.append(f"{what}: {key} names {branch.id}, whose label {branch.label!r} is not a git "
                           f"branch name. Make the label the branch's name (it may use {{base}} and "
                           f"{{branch}}), or take {branch.id} out of `{key}`")
    return out


def runnable(move: flows.Move, cfg, space) -> list[str]:
    what = f"move {move.id}"
    path = Path(space.adapter_dir) if getattr(space, "adapter_dir", None) is not None else None
    has = lambda verb: path is not None and packs.executable(path, verb)     # noqa: E731
    out = []
    why = flows.held(cfg, space)        # the predicate `flows.default_of` draws by
    undrawn = f"is not drawn for the {space.name} space. {why} Take the move out"
    if move.by == "keel" and move.step in PACK_STEPS and why:
        out.append(f"{what}: step {move.step} {undrawn}")
    elif move.by == "keel" and move.step in PACK_STEPS and not has(PACK_STEPS[move.step]):
        out.append(f"{what}: step {move.step} needs a pack with the `{PACK_STEPS[move.step]}` verb, and "
                   f"the {space.name} space has none, so Shipyard never runs it here. Take the move out, "
                   f"or draw what does happen (step land: your approval merges the card)")
    if move.by == "keel" and move.step == "land" and why:
        out.append(f"{what}: step land {undrawn}")
    elif move.by == "keel" and move.step == "land" and path is not None:
        out.append(f"{what}: step land merges a card on this machine, and in the {space.name} space "
                   f"your approval publishes through its pack instead. Use step publish")
    if move.by == "keel" and move.step == "deploy" and not flows.landing(cfg, space):
        out.append(f"{what}: step deploy moves a landing branch to the trunk, and no repo of the "
                   f"{space.name} space lands on one ([integration] in the config). Take the move out")
    if move.opens and not flow_pr(path):
        out.append(f"{what}: opens {', '.join(move.opens)}, and the {space.name} space's pack does not "
                   f"say its `pr` opens one for a flow (`{FLOW_PR} = true` under [capabilities] in its "
                   f"pack.toml). Take `opens` out, or use a pack that declares it")
    return out


def flow_pr(path: Path | None) -> bool:
    """Whether the pack at `path` declares that its `pr` takes a flow."""
    if path is None:
        return False
    try:
        pack = packs.at(path)
    except packs.PackError:
        return False
    return pack is not None and FLOW_PR in pack.capabilities


def check(found: flows.Flow, cfg=None, space=None, where: str | None = None) -> None:
    """`FlowError` naming every move that cannot run, one per line; nothing when all can."""
    said = problems(found, cfg, space)
    if said:
        raise flows.FlowError(f"{where or found.path or found.name}: " + "\n".join(said))
