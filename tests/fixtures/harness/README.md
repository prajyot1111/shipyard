# Recorded harness output, 2026-09-16, Claude Code 2.1.273

From one real `claude --bg` probe (`bg-start.out`, `agents.json`, `hooks.log`):

- `claude --bg ... --session-id X` warns "--bg manages the session id; ignoring --session-id"
  and prints `backgrounded · <8-hex short id> · <name>`. The short id is the first eight
  characters of the session uuid that `claude agents --json` reports as `sessionId`.
- `claude agents --json` rows: `pid, cwd, kind (interactive|background), startedAt (ms),
  sessionId, name, status (busy|idle)`; background rows add `id` (the short id) and `state`
  (`done` once its turn finished). After `claude stop`, `--all` lists it with `status: null`.
- Printing `{"decision":"block","reason":"..."}`
  made the session continue: two Stop events three seconds apart, the second not blocked.
- `SessionEnd` fired on `claude stop` (31 seconds later, when the process ended).
- `Notification` with matcher `idle_prompt|permission_prompt|agent_needs_input|agent_completed`
  did not fire for a plain turn end; Stop is the turn-end signal.
- `claude logs <id>` returns the raw terminal buffer with ANSI escapes; the transcript
  jsonl named in every hook payload is the clean source for "the last thing it said".

## Second probe: permissions in a background house

`claude --bg --permission-mode auto --permission-prompts none`, asked to `touch` and to
`Write` files OUTSIDE its cwd (under the home directory): both were auto-approved by the
auto-mode classifier, no `PermissionRequest`, `PermissionDenied` or `Notification` hook
fired, the session went `busy/working` then `idle/done` in about twenty seconds, and the
Stop payload's `last_assistant_message` carried the whole answer. So an ordinary house does
not stall on permissions. Keel still registers a `Notification` hook with the
`permission_prompt` matcher on every house: if it ever fires, `kb event` records it and the
card shows "waiting on a permission" under Needs you with an attach hint, which is the
only honest thing to do with a prompt nobody can answer from a phone.

## Third probe: the first live house (c-257, 2026-09-16 17:52)

- `claude agents --json`, `claude logs <id>` and `claude stop <id>` see only the sessions
  of the `CLAUDE_CONFIG_DIR` they run under. A house started under the personal config dir
  is invisible to a listing under `~/.claude`, so the drain lists under each space's
  config dir (`harness.agents_across`) and passes the space's dir to `logs` and `stop`.
- The variadic flags (`--disallowed-tools <tools...>`, `--add-dir <dirs...>`,
  `--tools <tools...>`) take a positional that follows them as one more value: with the
  prompt last on the line the house came up at an empty prompt, `status: idle`,
  `state: blocked`, and nothing ran. The prompt now goes before those flags.
- `state` has a third value, `blocked`: idle with nothing to do (an empty prompt, so a
  session waiting for input). `done` is idle after a finished turn.
- `SessionEnd` fired on the `claude stop` of that promptless house and `kb event` recorded
  it on the card, with `transcript_path` under the personal config dir's `projects/`.

## Fourth probe: three real houses (c-257, c-258, c-259, 2026-09-16 17:56 to 18:10)

- A house on the keel repo went assigned -> building -> review in 2m14s with no human
  touch: plan written at 37s, one commit, `kb stage review --output "branch ... @ sha"`.
  Its Stop hook fired once, at review, and did not need to block. The `idle_prompt`
  Notification fired 60 seconds after the turn ended.
- `claude stop` on a busy house: `SessionEnd` (reason `other`) reached the card within a
  second, and the row was gone from `agents --json` six seconds later.
- `claude --resume <uuid> --bg "<prompt>"` on a stopped session continues the
  conversation but mints a NEW session uuid (c-258: 5d18e1fb became 9a4dc153; c-259:
  f953ddc5, ad1387af, eaa3e567). The card's `session_id` follows the newest one and the
  older ones show under `--all` as `status: null, state: stopped`. The resumed house was
  `busy/working` in its worktree within ten seconds.
- `claude --bg` claims a session process that a per-config-dir daemon
  (`/tmp/cc-daemon-501/<hash>/spare/`, `claude bg-spare` behind a `bg-pty-host`) had
  pre-spawned, so the process environment a house sees is the daemon's, frozen at its
  first start: the c-258 house saw `KEEL_CARD=c-257`. The `env` block of the `--settings`
  file is per session and does reach the house's shell: c-259 recorded
  `KEEL_CARD=c-259 KEEL_HOME=/Users/user/keel kb=/Users/user/keel/bin/kb` with
  `kb note` on its first command. `CLAUDE_CONFIG_DIR` is safe either way because the
  daemon is per config dir.
- A house that is stopped a second time mid-turn has no Stop event, so the block reason
  came from `last_said` on the transcript the SessionEnd hook named; that transcript (of
  the resumed session) carries the whole conversation, earlier sessions included.
- A finished house stays a live process, `idle/done`, after its card reaches done. Nothing
  in the drain ends it; that is the deck's stop.

## `transcript.jsonl`

Shaped from the probe's real transcript (which lives under `~/.claude/projects/` and is
not copied here): `type` is `user`, `assistant`, `system`, `attachment`, `cost-state` and
a few bookkeeping kinds; an assistant line's `message.content` is a list of blocks
(`text`, `tool_use`); a subagent's lines carry `isSidechain: true`. `last_said` keeps only
the non-sidechain assistant `text` blocks, in order, and skips a line that is not JSON.

## Third finding: the background daemon keeps the environment it was spawned with

`claude --bg` hands the session to a per-config-dir daemon (`claude daemon run --origin
transient`, under `/tmp/cc-daemon-501/<hash>/`) that pre-spawns spare processes. Those
spares carry the environment the daemon was started with. On 2026-09-16 the first work
house was started with `CLAUDE_CONFIG_DIR=~/.claude` set explicitly; that setting selects a
different keychain credential entry (`Claude Code-credentials-<hash>`) from the unset
default (`Claude Code-credentials`), so the house saw "Not logged in" while a plain shell
was logged in. Fixing the variable was not enough on its own: the resumed house still came
from the old daemon's pool. Retiring that daemon and its spares by pid (never by pattern)
and resuming again produced a working house. Two rules follow, both in `harness.py`: the
default profile is addressed with the variable UNSET, and the harness passes a closed stdin
(the heredoc of the shell that called `house.resume` had leaked into the house's prompt).

## Fifth probe: a house reachable from the Claude app (2026-09-17)

Three ways were tried to give a `--bg` house a claude.ai/code link:

- `claude remote-control --session-id <local uuid>` from the house's cwd: "Could not reach
  the server to look up session <uuid>". The id is looked up remotely, so the flag only
  reattaches sessions that already exist on the server. It also refused first with
  "Workspace not trusted" until the directory had a `hasTrustDialogAccepted` entry in
  `.claude.json`; `--bg` itself needs no trust.
- `claude remote-control -c` (reattach the directory's last session): not reached, the
  attempt above already decided it.
- `claude --bg --remote-control <name> "<prompt>" ...`: WORKS. The session is listed by
  `claude agents --json` as an ordinary background row (`kind: background`), its
  `UserPromptSubmit` and `Stop` hooks fire, its log prints
  `/remote-control is active · Continue here, on your phone, or at
  https://claude.ai/code/session_<26 alphanumerics>` within seconds, and a message typed
  in the Claude app (`hello`) ran in the same session: the hook log shows the prompt and
  the Stop's `last_assistant_message` (`olleh`) under the same session id, and the
  transcript jsonl carries both turns. `--remote-control` takes an optional value, so the
  name is always passed explicitly or the prompt would become the name.
- `claude --resume <uuid> --bg --remote-control <name> "resumed"` continued the
  conversation (it answered `demuser`), minted a new local uuid (a24e839f became 6d3575a7)
  AND a new app link (`session_01Q7n8...` became `session_01GGEo...`). Keel re-reads the
  link after every resume. The older row lingered with `status: idle, state: working`
  after the app-driven turn; the drain counts rows by presence, not by `state`.

The three probe sessions were stopped by id afterwards. Consequence in code:
`harness.remote_flags`, `harness.remote_link`, and `remote_control=True` on `start_bg`
and `resume_bg`.

## Sixth probe: what lavish offers for not opening a browser (2026-09-17)

`lavish-axi --help` documents no way to skip the browser launch. The installed binary
(`/opt/homebrew/lib/node_modules/lavish-axi/dist/cli.mjs`, read only) does:

```js
function shouldOpenBrowser(args, env) {
  return !args.includes("--no-open") && env.LAVISH_AXI_NO_OPEN !== "1";
}
```

Both are real, and the package's own security paragraph says so ("LAVISH_AXI_NO_OPEN=1 (or
--no-open) suppresses the local browser launch"); neither reaches `--help`'s output. Lavish
also sets `LAVISH_AXI_NO_OPEN: "1"` itself on the detached server it spawns, so the variable
is a supported path rather than a leftover.

Probed against a throwaway HTML file in a scratch directory, isolated with
`LAVISH_AXI_PORT=4396` and its own `LAVISH_AXI_STATE_DIR` so the human's lavish on 4387 was
never touched, with a logging `open` shim first on PATH as the instrument (counting Chrome
processes is useless: a browser already running gains and loses renderers on its own):

| Run | `open` calls |
|---|---|
| `lavish-axi <file> --no-open` | none |
| `LAVISH_AXI_NO_OPEN=1 lavish-axi <file>` | none |
| `lavish-axi <file>` | one, `open http://127.0.0.1:4396/session/<key>` |

So the third line is the fact that matters for Keel: lavish opens the browser through the
npm `open` package, which on macOS spawns the BARE name `open` (`node_modules/open/index.js`:
`command = 'open'`), and node resolves a bare name through PATH. A PATH shim therefore
catches it whatever lavish decides to do next, which is why `etc/house-bin/open` exists as
well as the two switches. Note that a suppressed launch still reports `status: opened`; the
status is about the session, not about a tab.

The probe's own lavish server was stopped by pid afterwards (never by pattern).


## Terminal join probe: can an SSH terminal join the live Harbor? (2026-09-17)

For `keel talker shell`. The question: while the launchd talker serves Harbor over Remote
Control, can a terminal join the SAME conversation, or only fork a new one? Probed in an
isolated trusted scratch dir under the talker's config dir, with a throwaway
`--name talkerx-probe --capacity 1` server I started and stopped by pid (the human's live
Harbor was never touched). Three facts, all decisive for "fork, do not join":

- **A Remote Control session's local transcript is empty.** The server writes a
  `bridge-pointer.json` (`sessionId`, `environmentId`, `pid`) into its project slug and a
  0-byte `<uuid>.jsonl`. The turns live in the remote `environmentId`, not on disk. The
  human's live session showed the same: `session_...` mapped through `bridge-pointer.json`
  to a 0-byte transcript.
- **`claude remote-control -c` from the run dir refuses.** With the server holding the
  session, a second `-c` printed `Resuming session <id>…` then
  `Error: Session <id> is already being served by another 'claude remote-control' instance
  (pid <server>) in <dir>. Use that terminal, or stop it first.` and exited. It did not join
  and did not disturb the holder.
- **`claude --resume <local uuid>` finds nothing.** Resuming the Remote Control session's
  local uuid answered `No conversation found with session ID: <uuid>` (exit 1), because that
  transcript is empty. (For comparison, a plain headless `claude -p` session DOES resume in
  place: `claude -p --resume <uuid>` kept the same uuid and recalled its codeword, which is
  what the voice gateway relies on. Only Remote Control sessions are unresumable locally.)

So a terminal cannot cleanly join the phone thread. `keel talker shell` therefore FORKS: it
exec's plain `claude` in the run dir under the talker's config, memory and rules, a new
interactive thread that is still fully Harbor (same board via `kb`, same memory, separate
history). The throwaway server and its scratch dir, trust entry and project slug were all
removed afterwards; the live talker (pid unchanged, session unchanged, name Harbor) was
left running.

## Attach probe: does `claude attach` join a live background session? (2026-09-23, Claude Code 2.1.280)

For Drop in (decision N10, E2 of the overnight clearance). Run on the Mac under the default
config dir, on ONE throwaway session started for the purpose in an empty scratch directory
(`claude --bg --name lane-e-attach-probe --model haiku "Reply with the single word PINEAPPLE
and nothing else."`), stopped afterwards by its own short id; no house and no other session
was touched.

- `claude attach <id>` with stdin at `/dev/null` (no TTY) prints `Attaching...`, restores the
  terminal and exits at once: it cannot be driven by a plain pipe.
- Driven through a pseudo-terminal (Python `pty.fork`, 120x40), it draws the session's
  own screen: the earlier `PINEAPPLE` turn, the session's name in the prompt rule, and
  `← for agents`. A line typed there ("Reply with the single word MANGO and nothing else.",
  Enter) ran as a new turn and answered `MANGO`.
- **It is a JOIN.** Before and after, `claude agents --json` listed ONE row for that
  session: the same `pid` (75529), the same `id` and `sessionId` (`690108ea-...`), status
  going `busy` to `idle/done`. The project directory held ONE transcript,
  `690108ea-....jsonl`, carrying both turns, every line under that one `sessionId`. No new
  session was minted, unlike `claude --resume <uuid> --bg` with flags, which starts a copy.
- Ending the attach client (Ctrl+Z, then SIGTERM to the client's own pid) left the session
  running, listed and idle, as the help text says ("The session keeps running either way").
- `claude stop <id>` then stopped it (`stopped 690108ea`); `--all` listed it as
  `state: done` with no `status`.

Consequence in code: `keel/dropin.py` hands a live house `claude attach <bg id>` and never
`--resume`; an exited house is still resumed in its own directory.

## Drop in on an exited house (2026-09-24, Claude Code 2.1.281, Mac)

For U3 (`keel/dropin.py`, the drop-in hold). The script is in the repo,
`docs/probes/dropin-exited-probe.py`, and ran twice: throwaway `CLAUDE_CONFIG_DIR`s in
temporary directories, never logged in (a session starts, and a turn would fail on "Not
logged in", which none of these questions needs), every session stopped and removed by its
own id and every terminal ended by its own pid. Nothing under `~/.claude` was touched.

- **A terminal `claude --resume <uuid>` keeps the uuid and is listed.** `claude agents
  --json` gave `{"kind": "interactive", "sessionId": <the same uuid>, "name": <the
  session's name>, "status": "idle"}` with no `id`, between turns.
- **The house's hooks do not come with it.** A `--bg` session started with a `--settings`
  file whose SessionStart, Stop and SessionEnd hooks log themselves logged SessionStart and
  (on `claude stop`) SessionEnd; the terminal resume of it logged nothing more, not on
  start and not when the terminal was ended. So the listing is the only thing that says
  he left.
- **Keel's own resume forks it.** `claude --resume <uuid> --bg continue --settings <file>`
  while the terminal had the session open printed `note: session d2640506 is open in
  another Claude Code process, so this started a copy as cc538df4. The original
  conversation is unchanged.` and both were listed. The supersede's `claude stop
  <short id>` printed `stopped d2640506` and the terminal process was still running.

Consequence in code: Drop in on an exited house takes `options.dropin_hold`;
`house.refuse_if_in_terminal` refuses any resume of an interactive row or a held card; the
drain skips a held card and ends the hold from the listing (`drain.dropin_upkeep`).

## `--agents` probe: a per-session subagent (2026-09-23, Claude Code 2.1.280)

For the fresh-context reviewer (E6; since HP-1 the review core's reviewer and verifier,
`keel/review/agents.py`, both given the same way). One headless `claude -p --model
haiku` in an empty scratch directory, given `--agents '{"keel-reviewer": {"description":
..., "prompt": "... Answer REVIEWER-OK and nothing else.", "tools": ["Read", "Grep",
"Glob"], "model": "inherit"}}'` and asked to call that subagent by name and repeat its
answer, printed `REVIEWER-OK` and exited 0. So the flag takes a `tools` list and an
`inherit` model, and a session can call an agent it was given this way.

## Seventh probe: is there an in-place Remote Control reset? (2026-09-17)

Asked before building more on the run-dir rotation model: can the SAME directory give a
fresh conversation, making rotation unnecessary? Probed in an isolated trusted scratch dir,
`--name RcTest --capacity 1`, each server stopped by pid, `.claude.json` restored after.

| phase | flags | result |
|---|---|---|
| 1 baseline | (none) | mints session A (`session_01Gc1D...`), Capacity 1/1 |
| 2 plain restart | (none) | RECONNECTS session A, same id: the directory pin, confirmed |
| 3 no-create | `--no-create-session-in-dir` | Capacity 0/1, NO session, prints an `?environment=env_...` URL instead of a session link: the server comes up attached to nothing and hands session creation to the app |
| 4 spawn session | `--spawn session` | refused: "--capacity cannot be used with --spawn=session" |

Conclusion: there is no CLI-only, deterministic in-place reset. A plain restart reconnects
the pinned session. `--no-create-session-in-dir` does not reconnect it but does not mint one
either; it defers to the app via an environment URL, and whether the app then resumes A or
starts fresh is app behavior that cannot be settled headlessly. `--spawn session` conflicts
with single-session capacity. So run-dir ROTATION stays the reset primitive: it is the only
path Keel can drive deterministically without the phone. If an in-place reset is ever wanted,
it needs a manual test of what the app does with the phase-3 environment URL, not a code
change.

## Fourth probe: one connected turn (c-315, 2026-09-20, Claude Code 2.1.278)

Run on the box against a scratch background session in its own directory, under the
personal config dir; no card and no live house was touched. The scripts and the full logs
are on the card, in `state/cards/c-315/probe/`. Recorded here: `turn.json` (a `-p
--output-format json` answer), `turn-refused.err` (the same turn while the background
process is ALIVE), `bg-wake.out` and `bg-wake.err` (the flagless wake).

- **`claude -p --resume <uuid>` is REFUSED while the session's background process is
  alive** (`turn-refused.err`), and it suggests `claude attach`, `claude stop` or
  `--fork-session`. A fork is a copy that diverges, which V4 rejected, so a connected turn
  stops the process first. This confirms the 2026-09-18 probe on 2.1.276.
- **A `-p --resume` turn FIRES the card's Stop hook** (three hook lines: the SessionEnd of
  the process that was stopped, then Stop and SessionEnd for the headless turn). Its Stop
  payload carries `prompt_id`, `permission_mode` and `effort` beside the usual
  `session_id`, `transcript_path` and `cwd`. So guard 3 of V4 is a code change, not a
  paragraph: without it `kb stop-check` would answer a connected turn with
  `{"decision": "block"}`, which sends the house back to work mid-conversation.
- **`claude --resume <id> --bg`, with no flags and no prompt, WAKES the same session**
  (`bg-wake.err`: "woke session 4e53210b with its saved options (--name, --remote-control,
  --permission-mode, --permission-prompts, --settings, --disallowed-tools, --model)"). The
  session id is unchanged and its `claude.ai/code/session_...` link came back identical
  (`session_01YBGpeg4nBAqUfroyQtR6uR` before and after). Passing ANY flag instead starts a
  copy under a new id, which is what `resume_bg` does on purpose and what the 2026-09-18
  probe saw; the note says so in as many words.
- **The legs, measured.** `claude stop` 0.78 to 0.80s; the headless turn 5.04s on a 237 KB
  transcript and 6.66s (5.38s the second time) on an 889 KB one, the model's own answer
  included; the wake 0.84 to 0.97s; the link readable again 2.6 to 2.8s after it. One whole
  connected turn, stop to relaunched: 6.67s, against 7.81s for the same turn taken the
  `house.resume` way (which also minted a new uuid and a new link).

## Fifth probe: one kept-alive conversation (V12, 2026-09-21, Claude Code 2.1.278)

Run on the Mac from the build worktree, in a scratch directory, on a session the probe
created and threw away; no card and no live house was touched. The script is in the repo,
`docs/probes/conversation-probe.py`, so the measurement can be repeated against a later
build of `claude` rather than taken on trust.

- **One `claude` per sentence is most of the latency, and it is Keel's own.** A
  `claude -p --resume <id> ... "<sentence>"` reaches its first text delta in 3.6 to 4.1s.
  ONE process given `--input-format stream-json --output-format stream-json --verbose
  --include-partial-messages`, with each sentence written to its stdin as
  `{"type":"user","message":{"role":"user","content":[{"type":"text","text":"..."}]}}`,
  reaches the first delta of the same answer in 1.0 to 1.5s.
- **It is the same session.** Every `result` record of the kept-alive process carries the
  session id it was resumed with, so the transcript grows in place exactly as it does for a
  one-shot turn. One `result` per sentence, in order.
- **Closing stdin ends it, cleanly.** Exit 0, and the process group is empty afterwards. A
  process whose OWNER is killed (which is `keel serve` restarting) also ends by itself,
  because its stdin is the owner's pipe: checked with the owner SIGKILLed and the group
  polled for twenty seconds.
- **The Stop hook fires PER SENTENCE here too** (three sentences, three payloads, against
  three for three one-shot turns). So V4's guard 3 is unchanged by V12: both Stop hook
  bodies still have to return early on a held card.
- **The answer really does stream.** A four sentence answer arrived as 37 `content_block_delta`
  records between 1.84s and 2.78s with the `result` at 2.86s, so a sentence cutter reading
  them hands the first finished sentence over about a second before the turn ends. Through
  the built code (`harness.Conversation` and `housetalk.Listener`), the first spoken part of
  a four sentence answer landed at 2.18s with the turn finishing at 3.14s.

## Structured output for the capture refine (2026-09-24, Claude Code 2.1.281, Mac)

Probed once, headless, from a scratch directory: `claude -p "<prompt>" --tools ""
--no-session-persistence --strict-mcp-config --disable-slash-commands --model sonnet
--output-format json --json-schema '<schema>'`, the schema an object with
`additionalProperties: false`, `maxLength` caps and a repo of `anyOf` an `enum` of keys or
null. What was recorded (`structured.json`, the envelope's own keys with ids blanked):

- **The answer is `structured_output`**, a JSON object beside `result`, on the ordinary
  `--output-format json` envelope (`type: result`, `subtype: success`, `is_error: false`).
  `result` carried the same object as a JSON string. Keel reads `structured_output` and
  treats a missing or non-object one as no answer.
- **`enum` inside `anyOf` with `null` is accepted**, so the repo keys and topics are carried
  in the schema per call, not only checked after.
- The box's probe of the same flags without `--json-schema` (the planner's, 2.1.281) had the
  model write prose and a pretend tool-call transcript before its JSON, which is why the
  schema is required rather than trusted to the prompt.
- **The shipped schema itself was then checked once more** (same machine and version):
  `refineapply.schema(["keel","harbor"], ["voice","boards"])` with the refine's real flags
  and `--tools ""` last came back `subtype: success` with a valid `structured_output`
  (a two-way `split`, `choices` empty), so the array `minItems`/`maxItems` and the per-call
  enums are accepted, not only the first probe's smaller schema.

## Workspace trust (2026-09-24, Claude Code 2.1.281, Mac)

The box updated to 2.1.281 at 2026-09-23 20:54 UTC and a new errand house (c-452, cwd its
card directory) failed with `claude exited 1: Workspace not trusted. Run \`claude\` in
<cwd> once and accept the trust prompt, then retry.` Probed on the Mac (also 2.1.281) with
throwaway `CLAUDE_CONFIG_DIR`s in the session scratchpad, none logged in, so an auth
failure AFTER the trust check means the check passed:

- **An empty config dir refuses `--bg`** in a fresh directory: exit 1, that exact message,
  before any daemon starts. Reproduced the box's failure.
- **`projects[<exact cwd>] = {"allowedTools": [], "mcpServers": {}, "hasTrustDialogAccepted":
  true}` is enough.** `--bg` then backgrounded the session, and its log showed the turn
  failing on "Not logged in", i.e. past the trust check.
- **Trust inherits from a parent directory.** The same entry for the cwd's parent only
  (`.../state/cards` for a cwd of `.../state/cards/c-1`) also let `--bg` start. So trusting `state/` once would cover every card dir and every
  worktree under it on this version. Keel still writes the exact cwd, which is what the
  error asks for and what survives a version that stops inheriting (`keel/trust.py`).
- **`--resume <id> --bg` checks it too:** refused with the same message in an untrusted cwd.
- **`claude -p` does not check it:** in the untrusted cwd it went straight to "Not logged
  in". So a connected turn, a conversation and a voice ask need no entry.

The probe's sessions were stopped with `claude stop` and their transient daemons exited
on their own.

## Messages into a house, and a fork beside it (c-598, 2026-09-30, Claude Code 2.1.285, box)

Throwaway sessions in a scratch directory, messages sent with the real `relay.tell` (a
one-shot `claude -p --model haiku --tools SendMessage` named keel-drain); every session was
stopped by its own id afterwards.

- **Into an IDLE `claude --bg` session a message starts a turn in the same session.** Same
  pid, short id and sessionId in `claude agents --json` before and after; nothing stopped or
  resumed. The receiver sees `<cross-session-message ... from-name="keel-drain"
  from-mode="prompting">`; UserPromptSubmit fires for it and Stop at the end of that turn.
- **`to` is a session NAME.** A short id or a full uuid is refused ("No agent named ... is
  reachable"). Two live sessions of one name are refused too ("2 agents are named ...
  Re-send with the ref of the one you mean"), `success:false`, nothing delivered.
- **Into a BUSY session (mid foreground tool call) the message is queued, never lost.** The
  relay said success at once; UserPromptSubmit fired for it when the tool call returned and
  it was folded into the SAME turn (one Stop, "DONE-D\n\nPONG-FOUR"). A session idle with a
  background job still running, listed busy, took the message as a new turn at once.
- **Stop to `status: idle`** in the listing: within the same second. A listing costs 0.3 to 1 s.
- **The relay costs 7 to 13 s** of wall time (a `claude -p` start and a haiku turn).
- **`claude -p --resume <id> --fork-session` on a live session is read-only.** On an idle one
  it answered from the session's context under a new id, the original transcript
  byte-identical; on a busy one (with `--no-session-persistence --tools Read,Grep,Glob`) it
  answered in 10 s, saw the pending tool call as interrupted, left no transcript, and the
  original finished its turn normally. It runs none of the session's hooks. A plain `-p
  --resume` on a live session is still refused (`keel/converse.py`).
- **Permission modes.** An auto-mode session took the relay's default-mode messages with no
  hold (haiku cannot run auto and fell back to manual; it took them too). Houses always run
  `--permission-mode auto`. Only a bypassPermissions session holds a peer message from another
  mode (Bosun sets `crossSessionInbound: accept` for that, `keel/console.py`).

## A conversation past its retention (c-654, 2026-10-05, Claude Code 2.1.289, Mac)

The harness keeps a transcript for its retention period only (30 days by default). Three
shipping houses last used 32 or more days before were resumed that day for a review batch
(c-015, c-017, c-037); two last used 23 and 26 days before resumed normally.

- **`claude --resume <id> --bg <flags>` of a conversation that is gone launches normally.**
  It printed `backgrounded · <the same short id> · <name>` and exited 0 (a healthy flagged
  resume mints a NEW id). One `SessionEnd` hook, reason `other`, for that same session id
  arrived four seconds later; no Stop, no turn. `claude agents --json --all` lists the
  session with `"state": "failed"`; the plain listing does not list it at all.
- **`claude -p --resume <id>` with NO prompt takes no turn, and says which it is.** For a
  session id with no conversation: exit 1, stderr `No conversation found with session ID:
  <id>`, 1.6 s. For a conversation that is there: exit 1, stderr `Error: No deferred tool
  marker found in the resumed session. Either the session was not deferred, the marker is
  stale (tool already ran), or it exceeds the tail-scan window. Provide a prompt to continue
  the conversation.`, 1.6 s, no model call. With a prompt, the gone one says the same `No
  conversation found` line.
- **The probe Keel runs carries the login probe's flags, so it can use no tool** (c-654
  review; recorded again the same day under the builder's own config dir, in a scratch
  directory). `harness.conversation_gone` runs `claude -p --resume <uuid>
  --no-session-persistence --model haiku --strict-mcp-config --tools ""`, in its own
  process group, with a 15 second limit. The present session was one made for the probe
  (`claude -p "Reply with the single word ok." --model haiku --strict-mcp-config --tools ""
  --output-format json` in that directory, exit 0, 2.6 s, its `session_id` read from the
  answer). With those flags:
  - that session, asked in the directory it ran in: exit 1, 1.6 s, empty stdout, stderr
    `Error: No deferred tool marker found in the resumed session. Either the session was
    not deferred, the marker is stale (tool already ran), or it exceeds the tail-scan
    window. Provide a prompt to continue the conversation.`
  - a random uuid, same directory: exit 1, 1.5 s, empty stdout, stderr `No conversation
    found with session ID: <uuid>`.
  - that session, asked in a DIFFERENT directory (a sibling scratch directory it never ran
    in): the same `No deferred tool marker` answer, exit 1, 1.5 s. So a wrong directory did
    not turn a present conversation into "No conversation found" here. Keel still asks in
    the directory the resume itself would use, and corroborates the answer with the listing
    and the board before it replaces a session (`keel/afresh.py`).
  - that session's SHORT id (its first eight characters): exit 1, 1.8 s, stderr `Error:
    --resume requires a valid session ID or session title when used with --print. Usage:
    claude -p --resume <session-id|title>. Provided value "<short id>" is not a UUID and
    does not match any session title.` So a short id is never asked as it is: it is
    resolved through `claude agents --json --all` first (`harness.full_session`), whose rows
    for sessions that are not running carry `id`, `sessionId`, `kind`, `name`, `cwd`,
    `startedAt` and `state` (`stopped`, `done`; no `pid`, no `status`).
- Not probed: the promptless call on a session that DID end on a deferred tool call (its
  message says it would look for one). No Keel hook defers a tool, so no house should end
  there, and the flags above are what keeps the probe from acting if one ever does: with
  `--tools ""` it has no tool to run. Whether it would still take a model turn there is not
  known.
- Not probed: the promptless call, with or without the flags, on a session that is RUNNING
  in the background (recorded before for `-p --resume` with a prompt: refused, "is running
  as a background session"). Keel never asks it of a session the harness lists a process
  for.
- Not probed: the two answers on a present conversation whose worktree directory has been
  removed, or that ran under another config dir; and the answers across a harness upgrade
  (one version only, 2.1.289).
- Not probed here: the `--bg` launch of a gone conversation itself, beyond what the three
  cards recorded (the builder's config dir trusts no directory to launch one from).
