"""`keel doctor`'s pack lines (c-617, c-688): the pack behind a space, each tool it declares
with its check run here, and under the pack's line each missing tool's own fix.

`keel/doctor.py` calls `pack_report` for a space's report and `pack_lines` to print it. The
Atlas page "Packs" (docs/atlas/62-packs.md) says what a pack declares.
"""

import os

from keel import config, packs


def pack_report(space, served: bool, guard) -> dict | None:
    """The pack behind the space's adapter (c-617), and where the space is served, each tool
    it declares with its check run here. A missing tool is shown, never a problem: the pack
    says what it uses, and the verb that needs it says so when it runs. A broken `pack.toml`
    is a problem."""
    try:
        pack = packs.at(space.adapter_dir)
    except packs.PackError as error:
        return {"name": space.adapter, "error": str(error), "tools": []}
    if pack is None:
        return None
    env = {"KEEL_SPACE_CONFIG_DIR": str(space.config_dir), "KEEL_STACK_GUARD_HOOK": str(guard or ""),
           "KEEL_SPACE_REPOS": os.pathsep.join(str(path) for path in space.repos.values()),
           # c-735: a pack on the kit imports it through KEEL_HOME, wherever the pack lives
           "KEEL_HOME": str(config.repo_root())}
    return {"name": pack.name, "version": pack.version,
            "tools": packs.checks(pack, env) if served else []}


def pack_lines(pack: dict | None) -> list[str]:
    if not pack:
        return []
    if pack.get("error"):
        return [f"  pack        {pack['name']}  [bad] {pack['error']}"]
    tools = pack["tools"]
    missing = [tool["name"] for tool in tools if not tool["ok"]]
    found = f"{len(tools) - len(missing)} of {len(tools)} tools found" if tools else "tools not checked here"
    return [f"  pack        {pack['name']} {pack['version']}  ({found}"
            + (f"; missing: {', '.join(missing)})" if missing else ")"),
            *(line for tool in tools if not tool["ok"] for line in fix_lines(tool))]


def fix_lines(tool: dict) -> list[str]:
    """A missing tool's own fix, where its pack wrote one (c-688): the sentence, the line to
    run and how the user knows it worked."""
    if not tool.get("fix"):
        return []
    return [f"    {tool['name']}: {tool['fix']}",
            *([f"      run:  {tool['command']}"] if tool.get("command") else []),
            *([f"      then: {tool['done_when']}"] if tool.get("done_when") else [])]
