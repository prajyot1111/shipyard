# talker

The working directory of the talker: the one long-lived Claude Code conversation the user
speaks to from a phone through Remote Control. `keel talker start` runs
`claude remote-control --name harbor` in a numbered run directory under `home/` with
`CLAUDE_CONFIG_DIR=spaces/harbor/.claude`. Its rulebook and its memory live in the install
(`<install>/memory/talker/`): `keel talker install` links the config dir's `CLAUDE.md` to the
rulebook there and the config dir's auto-memory path for the run directory to the memory.
Nothing else lives here on purpose: the talker files cards with `kb`, reads the board, and
never does the work itself, so there is no code for it to touch. Verbs:
`keel talker install [--load] | start | url | status | stop`.
