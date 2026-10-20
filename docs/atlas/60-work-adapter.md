# The work adapter

An adapter is the only directory that knows about an employer. It teaches the engine three
things it deliberately does not know: how to cut a worktree for a card, what to tell a
house about the repo it is working in, and how to publish an outcome. Ours is the work
pack, `<install>/packs/work/` (a pack is an adapter plus its rules, skills and config, [packs](62-packs.md)).
It is the install's own and is not in the code (c-722): delete it and a working personal
Keel is left behind.

That is a hard boundary, not a convention: `make drift` greps every tracked file of the code
for each pack's employer vocabulary, the install's packs included (`tests/installdrift.py`),
and fails on a hit. The directory is named for the space, not the employer, so the config
never has to name one either.

## The vocabulary rule, stated once

Nothing outside `<install>/packs/work/` may name the employer, its issue tracker, its code host, or
its work-stack tools. The engine's own words are neutral (ticket, pull request, the tracker,
the code host), and the deck draws no noun of its own for any of it: the words come from the
pack at runtime, its `[terms]` table through `keel/terms.py` (story, `sc-<n>`, pull request,
PR and the vendors' names for this pack, c-630, [packs](62-packs.md) "Terms"), and the rest
through `options.json`, `act verbs` and the providers. `make drift`'s noun guard
(`tests/nouns.py`) fails on a ticket or change noun spelled out in `app/` or `keel/`. This
page follows the same rule, so it says `the tracker` where a reader at the desk would say
a product name.

## The verbs

The adapter directory is found by `spaces.<space>.pack` (`packs/<name>/`, [packs](62-packs.md)) or, as before, by `spaces.<space>.adapter` under `adapters_dir`. Each executable takes a card id
and reads the card with `kb show <id> --json`. Every verb runs with `KEEL_HOME` set, `kb` on
PATH and `KEEL_SPACE`, the space it runs for (`adapters.adapter_env`, c-730): a pack may serve
several spaces, and a verb with no card (`review scan`, a provider, `act do`) reads its space there.

| Verb | What it does |
|---|---|
| `worktree <id>` | Prints the worktree paths, primary first (the rest become `--add-dir`s), creating them when needed. Mints the tracker story at task start, records `options.tracker_ref` and a note, names the branch once from the story and keeps it in `options.branch` so a recreate reuses it, and records the primary path in `options.worktree`. An existing worktree is reused, and git is asked which one (`cut.existing`, c-652): the worktree it has that branch checked out in, wherever under the worktree tool's home its directory is, since a worktree keeps its directory when its branch is renamed; otherwise the tool's own name for the branch, whatever that directory holds now (detached mid-rebase, or renamed while the card still records the old name: it is the worktree the card was cut in). A checkout git has the branch in that a house cannot be given is refused by name instead of failing inside the worktree tool: the repo's own checkout, one outside the tool's home, one whose directory is gone. The shipping match and the reap find a worktree the same way |
| `brief <id>` | Prints the work half of the house brief: the worktree and container facts, the story, the card's options, the ending. A research card gets the scratch house and the record ending instead (below) |
| `pr <id> [--draft\|--ready\|--body]` | Opens the card's DRAFT pull request from `options.branch` against `options.base`, body taken from the `## PR body` section of `context.md` (in an outcome in the plan format, what is inside the ```copy block that opens that section, headings and code blocks included, and nothing after it: `pulls.pr_body_section`), records `options.pr` and prints the URL. A cross-repo card gets one in EACH repo whose branch is on origin (c-565, `pulls.open_drafts`): one URL per line, a repo it skipped said on stderr, each recorded (`workcard.record_pr`: the primary in `options.pr`, every one in `options.prs`), and each repo's body is the ```copy block titled with that repo when the section has one per pull request (`pulls.pick_block`), else the first. `--ready` flips every repo's existing draft. `--body` (c-597, `pulls.refresh_bodies`) puts the house's PR body on every open pull request of the card (`codehost.set_description`): the draft now opens before the review with the card's default body, so the final body goes up at the ending; it refuses while the section is empty or a placeholder, so a draft body is never overwritten with nothing. A house runs this itself, after it has pushed, and `kb stage review` refuses until it has (`publishable`, below). Refuses a research card |
| `pr <id> --flow <branch> --to <target> --dir <worktree>` | c-641, and declared as `flow_pr = true` under `[capabilities]` in `pack.toml` (c-664: a flow with `opens` is refused for a space whose pack does not say so). The pull request a flow move of the user's names (the early merge to master): run by `kb flowpush --pr`, which checked the user's grant and pushed `<branch>` from `<worktree>`. It asks the board whether the grant still stands (`kb flowinfo`, `pulls.standing_grant`, c-664: a flow that renamed a branch after the tap ends the grant without taking it off the card; the question has the guard's 15 second limit, and a board that fails, answers something else or does not answer in time is one plain refusal) and checks the grant itself too: the target must be a git name the grant opens and the source one it pushes (`names`, filled at the user's tap), and never a protected branch. The repo is the one `<worktree>` is a clone of; at shipping it is the one form `fence.refuse_unless_shipping_tap` lets through (`pr-flow`, while `options.flow_move` stands). Found open or opened ready, recorded as `options.flow_prs.<target>`, noted. The pack's flow is `flow.toml` ([flows](64-flows.md)) |
| `ci <id>` | c-642. What the CI page shows for the card, as JSON, read only (`cisight.py`, `ciserver.py`): each pull request's head checks, and the CI server's builds of the shared branches whose commits include the pull requests' commits or name the card's story, with stages and a failed step's last lines; what it cannot read is a note. The server's credentials are its MCP entry in `~/.claude.json` (`CI token`, for `ci`). [A card's CI](66-ci.md) |
| `publishable <id>` | c-551. Run by `kb stage <id> review` (and skipped for a verified nothing-to-land card, r-51), the card as JSON on stdin (`keel/adapters.py publishable`), and prints `{"publishable": true}` or `{"publishable": false, "missing": "<line>"}`. For a code card (not research, tracking, review, nor one with no repo: `readiness.code_card`), in EVERY repo of the card (c-565), each on its own branch (`naming.branch_in`): the branch is on origin (`ls-remote`), origin's tip contains the local branch's tip, and a pull request is open, recorded (`workcard.recorded_pr`) or one found open on the branch (`codehost.existing_open_pr`), which it records (`workcard.record_pr`) as `make_ready` would. Each missing line names the push and `pr <id> --draft`; on a cross-repo card it names the repo, and says to take a repo with no change off the card's repos. A clone or code host that cannot be asked exits 1, and Keel refuses the move with that reason. `publish` stays as it was: it pushes nothing and opens nothing |
| `publish <id>` | Run by `kb approve <id> outcome`: `pr --ready`, then the tracker transition, then one `kb note`. Prints a JSON summary the approve event stores. On a cross-repo card (c-565) every repo's pull request is found first (a repo with none refuses the whole, and nothing is flipped), then each is flipped to ready; the note names each and the summary lists them under `prs`, beside the primary's `pr` and `url`, still `"shipping": true`, and `heads` ({repo: full sha} the host says each pull request is at, resolved in its worktree; `prsend.published_heads`), which Keel keeps as the user's first Ship's lease. For a research card it publishes nothing and reads no credentials: one note, and `{"published": "nothing", "kind": "research"}`. Nor for a tracking card (`workcard.is_tracking`, lane X): each slice published its own, so it writes one note and prints `{"published": "nothing", "kind": "tracking"}`; the board never calls it for one anyway |
| `publish <id> --answer` | For a card at SHIPPING (lane SHIP, c-600), the user's Ship: Keel adds `--answer` and hands `{"ship": true, "replies": [{handle, text}], "lease": {repo: sha}}` on stdin (`keel/shipreplies.py`, only the kept replies not posted yet), and, only inside that Ship's `options.publishing` marker (`fence.refuse_unless_shipping_tap`, which also refuses `pr` at shipping), `prsend.ship` pushes every worktree (a pure fast-forward of the remote's own head, pushed plain, `prsend.standing`; leased against `lease`, the head Keel recorded, only when the remote could not be asked; `prsend.lease_args`), marks a draft ready and posts the replies, answering `{shipping, shipped, pr, pushed, skipped, ready, posted, sent}` (below). A review card's `{"review": ...}` (lane RC, `keel/reviewround.py`) is posted on the colleague's pull request (`reviewpost`): each kept finding inline at its line, one summary comment, then the verdict (approve, request changes, or none for comment only), each recorded on the card as it lands so a retry posts nothing twice, and `options.review_posted` at the end. A feature card's answer carries `members` (lane GRP): each member's findings, the summary and its own verdict go on its own pull request. Without `--answer` stdin is never read |
| `deny <id>` | The card arrives as JSON on stdin. Prints a JSON list of extra permission deny entries for this card's house, which Keel merges into its settings. A research card and a card at shipping (c-600, `fence.at_shipping`) are denied `git push` from the shell, the code host's write tools and this adapter's `pr` and `publish`; a review card the commit as well; every other work card only the code host's MCP write tools, which no build house needs (`pr` and `publish` use the REST API) |
| `ship <id> down` | c-532: the card's OWN containers stopped and removed, its worktrees kept (`teardown.down`), which the drain asks for when the card leaves building ([the drain](30-drain.md)). Over the card's recorded worktrees (`options.worktree` and every path in `options.worktrees`): the preview tools' own `down` first, then every container still BOUND to a worktree: a compose project whose working directory or compose files are inside it goes by `docker compose -p <name> down --remove-orphans`, any other container with a mount or working directory inside it by `docker rm -f`. A path matches as the host names it and as a container does (`/ws/<dir>/<slug>`). The user's shared stack cannot match: it mounts the whole workspace, reaches the active worktree through a pointer file, and keeps its compose files in the main checkout; its project name is refused as well. The test command is never called (given an argument it does not know it would run the suite), and volumes are kept, so the per-worktree test database is there for the next round. Prints `{down, failed, worktrees}` |
| `ship <id> poll\|diff\|reap\|method` | A shipping card's pull requests (lane SHIP; every one of them since SH-10): `poll` prints what the code host says as a SIGHT in the engine's words (`prsight.sight`, read only), one pull request as it always was and several under `prs`; `diff` prints each pull request's diff against its base; `method` prints `comments.md`, how the house judges review (c-600); `reap` takes away the worktrees of a DONE card, each repo's on its pull request's branch, keeping one with uncommitted changes and running the same container sweep as `down` first (`reaping.reap`) |
| `ship <id> restack` | c-718: a STACKED card's pull requests aimed at the base once the card it is stacked on has merged (`restack.restack`, `codehost.set_destination`: a PUT with the new `destination`), asked once by the drain ([the drain](30-drain.md), "Stacked cards"); the code host is not relied on to do it. Only a pull request that is open and still aims at the parent's branch moves; one aimed elsewhere (by hand) or no longer open is left and named in `kept`, a closed one with its `state`, on which Keel blocks the card (r2.F6). Refused for a card that is not stacked, or whose parent has not merged. Prints `{base, retargeted: [{repo, pr, from, to}], kept: [{repo, pr, why}]}`. It moves no branch and pushes nothing |
| `ship mine` | SH-11: reads the space's cards as JSON on stdin and prints `{prs}`, every OPEN pull request THE USER wrote in the work repos (author = `reviewscan.ME`), with its branch, draft flag, the worktree on disk for that branch, and the cards it matches, by branch first and by story otherwise (`shipmatch.mine`). `bin/keel-shipping-sync` decides from it. Reads only |
| `review scan` | Lane RC: prints `{prs, open_groups}`, every open pull request that needs the user's review by the old review scanner's own rule (the user is a reviewer, did not write it, has not approved it), whatever its age. Lane GRP: each row's `group` is its story, the old scanner's `_story_id` rule on the branch name (`sc-NNNNN`, lower case, or null), and `open_groups` is, per story, every repo with an OPEN pull request of it, the user's or not (what tells a branch with no pull request yet from one that is not the user's). c-559: a row into the staging base (`twinrule.STAGING`) that is the same change as its story's row into `master` in the same repo carries `twin_of`, the master row's label (`twinrule.mark`, below). The two settings (auto review, the review model) are not the adapter's: the fetcher reads them from the space (`keel/reviewsettings.py`). Reads only |
| `review <id> poll` | Lane RC: one review card's pull request, `{state, head, url}` (open, merged, declined); a feature card's (lane GRP) is `{members: {<repo>#<number>: {state, head, url}}}` |
| `review branches <story> <repo>...` | Lane GRP (GR-3): the story's branches in every reviewed repo NOT named, `{branches: {repo: [names]}}`: one query per repo (the old scanner's `branches_with_story`, `name ~ "<story>"`, page size 50), keeping only names whose story is exactly this one. The wait's one read per held card per poll. Reads only |
| `review story <story>` | Lane GRP (GR-1): the story's title from the tracker, `{title}`, or null when it cannot say (the feature card then takes its first pull request's title). Read once, when a feature card is filed |
| `act verbs` | The card-level verbs the deck's inspector offers for this space, with the labels it shows. None today: the old "Enroll in PR Watch" verb is gone (2026-09-24), because the user's own pull requests are watched in shipping and review cards are filed on their own, so no card offers it and nothing in Keel calls the watcher's `enroll`. `act do card <verb>` refuses every verb |
| `act links <id>...` | `{id: {story, pr, prs, design_doc, unpublished}}` for the cards that have them. `pr` is the primary pull request's link and `prs` lists every one as `{repo, pr, url}`, primary first (c-565, `acting.pulls_of`): the deck's Open output offers each on a cross-repo card, and the outcome page's header links each. `unpublished` (c-551, `readiness.unpublished`) is a code card at review with a repo that has no pull request recorded (`options.pr` or `options.prs`), naming that repo on a cross-repo card, from the card alone: the deck draws its line in place of Approve outcome |
| `act do <route> <verb> <key>` | Carries out one deck tap. The arguments arrive as JSON on stdin. Prints JSON, or refuses on stderr with one line. The one route is `reviews`, with the gear's two verbs, `set_auto_review` and `set_review_model` (`{"value"}`), which write the space's live override through `keelbridge` (`keel/reviewsettings.py`) |

`kb approve <id> outcome` runs `publish` **before** the transaction that moves the card to
done, because the adapter writes to the board through `kb` and the store is one SQLite
file. A publish that fails leaves the card at `review` with the adapter's stderr as the
refusal.

**`publish` runs on this machine** (lane L). The code host's and the tracker's credentials
are read from this machine's own config. When the user approves a work outcome, the deck's tap runs
this executable here and reads its JSON, then the card moves to done (`Board.approve`,
[cards and gates](10-cards-and-gates.md)). If it fails, nothing moves.

**The push is decided by the remote's own head, asked at that moment** (`prsend.standing`,
c-653; the sandbox adapter's `sb_pulls.standing` is the same). Before anything is pushed,
each worktree's one branch is fetched (`+refs/heads/<branch>:refs/remotes/origin/<branch>`,
on a shorter clock than the push, `FETCH_SECONDS`), and the worktree is one of:

- **forward**: the remote's head is HEAD or an ancestor of it. The push is a pure
  fast-forward and is made PLAIN, with no force flag at all: a push by anyone else between
  the look and the push is rejected by the remote as not a fast-forward. The head Keel
  recorded plays no part: it goes stale when the branch is rewritten outside Keel, and
  after the user has replayed the worktree onto the rewritten branch by hand ([cards and
  gates](10-cards-and-gates.md)) a push leased against it would be refused though it is a
  plain fast-forward of what the remote holds.
- **skip**: the remote holds HEAD and more (a colleague pushed to it). The user's Ship has nothing
  to push from that worktree, and the push it used to make was rejected as behind, so no
  reply was posted. The worktree is left out of `pushed`, so Keel keeps the head it had
  recorded, and named in `skipped`, so the Ship's line says nothing was pushed from it
  (`shipreplies.ship_line`); the user's replies and a draft still go.
- **diverged**: neither holds the other (the branch was rewritten, or moved again after
  the user's by-hand replay). The whole Ship is refused before any worktree is pushed, with the
  counts and the way on, and no reply goes: a reply naming those commits must not be
  posted on a branch that does not hold them.
- **unknown**: the fetch failed or hung (caught, never an error of its own). Nothing is
  decided on it: the push is attempted, leased against the head Keel recorded when there
  is one, and says what is wrong.

The remote-tracking ref as last fetched is never enough: a branch rewritten since then no
longer holds HEAD.

**Which repo on the code host** (`workcard.host_slug`, r-18, c-539). Every call about one
card's pull request (`pr`, `publish`, the user's Ship, the shipping watch's poll, a
review card's poll and post, the deck's link) needs the repo's `workspace/slug`. It is
`workcard.HOST_SLUGS` when that names the repo key (an override: `cloud` and `webapp-react`,
kept so those two link and poll without a clone), else it is read off the
clone's `git remote get-url origin`, ssh or https, and taken only when the remote's host is
`workcard.CODE_HOST`. A slug found that way is kept for the process (`workcard.DERIVED`,
since `act links` asks for every card on the deck); a failure is asked again. Neither gives
one: the error names the repo, and whether its clone is not on this machine, has no origin, or
points elsewhere, and the override to add. The deck's link (`act links`) leaves a link out
rather than failing.
Two scans still iterate only `HOST_SLUGS`, on purpose: the review request scan
(`reviewscan.scan`, `branches`) and the shipping sync's `ship mine` (`shipmatch.mine`), because
widening them polls every work repo and files review cards from repos that filed none before.

## A stacked card (c-718)

The pack declares `stacks = true` under `[capabilities]`, so the owner may stack a card on
the one card it waits for ([cards and gates](10-cards-and-gates.md), "Stacked or
independent"). Keel hands the card in with `derived.stack` (the parent's id, its branch,
the `repos` the parent works in, whether it has landed, the base the parent merges into),
and the pack reads it in one place, `workcard.base_of`: while the card is stacked on a
parent that has not merged, its base is the parent's branch; after, `options.base`, else
the base its parent merged into (c-718 r1.F12: the board refuses a stacked card whose own
base differs from its parent's), else the default. So `ship <id> restack` aims a pull
request where the parent's commits are.

The base is PER REPO (c-772). A stacked card may name a repo its parent does not, as long
as the two share one, and the parent has no branch there. `derived.stack.repos` says which
repos the parent names, so the pack does not read the parent's card: in one of those, every
verb that reads the base follows the parent's branch (the draft `pr` opens against it,
`poll`'s `behind` and `diff` count against it, the brief names it); in any other repo of
the card, the worktree is cut from the base and the pull request aims at the base, before
the parent lands and after (c-770). `workcard.stacked_on` is the test. The core reads the
base the same way (`stacking.base_of(card, repo)`, [cards and gates](10-cards-and-gates.md)).

- **The cut** (`cut.worktrees_for`, `cut.parent_ref`): a stacked card is cut from the
  parent's branch AS THE REMOTE HAS IT, fetched by its full refspec first, never from the
  base and never from a stale copy. A parent with no branch recorded, or one the remote does
  not hold, cuts nothing and says so; the board starts a stacked card only once its parent
  records a pull request anyway. An existing worktree is reused as always.
- **The parent merges**: the drain runs `ship <id> restack` once (the verbs table), which
  aims each open pull request still aimed at the parent's branch at the base. A merge
  commit leaves the child's branch with the parent's commits already on the base, so the
  pull request shows only the child's own. A squash merge does not, and what the branch
  then needs is said by Keel, never moved by this pack ([the drain](30-drain.md), "Stacked
  cards").
- **Independent** needs nothing here: it is cut from the base and aims at it, as a card
  with no choice is.

**Twin pull requests** (`twinrule.py`) are not touched by stacking, and stacking does not
reach them. The twin rule is read only over the review scan's rows, colleagues' pull
requests that need the user's review, pairing one into `master` with one into the staging
base by story and change. A card's own pull request is never one of those rows. A stacked
child's pull request aims at its parent's branch, which is neither base, so even were it a
row it would pair with nothing and be reviewed as itself. A card's own second pull request
into `master` is the flow's early merge (`pr --flow`, `options.flow_prs`), cut by the
owner's flow move from `{branch}-master`; aiming a stacked child's at its parent's pick
branch would need the flow to name that branch, which it does not, so that is not built
(c-718's report says so).

## A work house runs Keel's pre-gate pipeline (HP-3)

A work repo house runs the same four steps as a personal one before its outcome gate,
preship first ([houses](20-houses.md), "The pre-gate pipeline" and "Preship first"):
`[spaces.work] preship_first = true` and `review_full_rounds = 1` (c-597). Since
2026-09-24 `[spaces.work] house_review` is on, so a work house is given Keel's reviewer and
verifier, its Stop hook holds the review stamp, and `kb stage review` holds the base, the
answers and the risk. The work skill that used to carry its own review is no longer in the
house path, so no work change is reviewed twice.

- **The words are this adapter's.** `[spaces.work] pipeline` names `<install>/packs/work/pipeline.md`,
  whose `## Verify` (the family's own test container ONCE per trip on the head that ships,
  started in the background beside the reviewer and restarted on the fixed head only when
  the review brings code fixes; screenshots with `--backend auto` on a cross-repo card; a
  preview; never the shared stack; evidence copied into the card directory), `## Preship`
  (docs and swagger for changed endpoints) and `## Publish` (the push from every worktree,
  the draft through `pr`, and `--force-with-lease --force-if-includes` for a rebase after it) Keel puts in the
  brief under the steps of the same name.
- **The ending** (`briefing.ENDING`, c-597) is build with a TARGETED test, the pipeline in
  its work order (preship with the push and the DRAFT pull request, so the code host's CI
  runs beside the rest; verify in the background; the review and one fix check with the one
  full test run beside it; risk), the pull request body in the record, the push of what came
  after the draft, `pr <id> --body`, and `kb stage <id> review`.
- **Pushing before the review needs no new permission.** A build house could always push
  its own branch (the fence denies the push only to research, review cards and review
  rounds), and `publishable` still refuses the stage until origin has the head and every
  draft is open, so a fix after the draft is pushed again before the gate. No gated review skill, no context file of the old tooling, no PR
  watch enrolment: the draft is the adapter's, and the user's Approve outcome is the only go-ahead.
- **The base** is `options.base`: the brief's diff and the stage's rebase check are taken
  against its current head on the code host (`origin/<base>`, fetched first).

## A review card (lane RC)

A pull request that needs the user's review is a card of its own (decisions RC-1 onward): kind
`review`, `options.review_key` (`<repo>:<number>`), `options.slot = review` (the review
pool), the pull request's number, source branch and target in `options.pr`,
`options.branch` and `options.base`. `workcard.is_review` says so. The adapter's part:

- **The house is a read-only checkout** (`reviewing.py`). `worktree` fetches the pull
  request's branch and its target, cuts a worktree through the worktree tool on a LOCAL
  scratch branch `review/<repo>-<number>` (the seed files make the repo readable and its
  tests runnable), and DETACHES it at the pull request's head on the remote, recording
  `options.worktree` and `options.review_head`. Nothing there is a branch of the
  colleague's. On a re-review the same worktree moves to the new head, and the last round's
  `context.md` is kept as `context-round-<n>.md` before the new round starts.
- **The fence** (`fence.deny_for`) is the research card's (the push, the code host's write
  tools, `pr`, `publish`) plus the commit; `pr` refuses a review card
  (`workcard.refuse_research`), so none of its own is opened or readied.
- **The brief** (`briefing.review_compose`): the read-only house, and the ending, which is
  the review kind (`docs/plan-format.md`): a code-path board pushed with `keel board push
  --new --card`, the orientation, one ```finding block per surviving finding (severity,
  `at: path:line`, claim, evidence, the verifier's word, suggestion, the drafted `comment:`
  and the `choice:`; never code, which the deck reads from the worktree), the verdict
  decision, then `kb stage <id> review --plan
  <context.md> --output <the pull request's url>`. The review core's own steps are Keel's
  section of the brief ([houses](20-houses.md), "Peer mode").
- **A feature card** (lane GRP, `options.review_members`: one story's pull requests,
  filed by the fetcher) is the same, per member. `reviewing.cut_feature` cuts one detached
  worktree per member on its own scratch branch, primary first, and records
  `options.review_worktrees` and `options.review_heads` by label and the heads together as
  `options.review_head`. Its brief is `featurebrief.compose`: every member's pull request
  and worktree, the ONE prep command with a `--member` per pull request, and the feature's
  review kind (a member on every finding row, a `decision verdict-<repo>-<number>` each).
  `reviewpost.post_feature` posts each kept finding on ITS member's pull request, the
  summary on every member and each member's own verdict, recorded per member as it lands
  (`review_posting.members`), so a retry says nothing twice on any of them; the card then
  carries `review_posted.members`. `review <id> poll` answers per member.
- **Twin pull requests** (c-559, decision TW-3, `twinrule.py`): one story's change raised
  into both `master` and the staging base (`twinrule.STAGING`) is reviewed on the master one only. The rule is
  the adapter's, so the two base names never reach Keel: at `review scan`, two rows of ONE
  repo and ONE story, exactly one into each base, whose change is the same, by the SAME
  COMMITS (the non-merge commits each adds to its base, by author and subject in order: a
  cherry-pick keeps both, so a staging twin that also bumps package.json in its commit, as
  c-500's webapp-react#2200 did, is still one) or an EQUAL DIFF (against its base with no
  context lines, without the `index` lines and the hunk headers' line numbers). It is read
  with local git in the user's checkout of the repo, both bases fetched on every look (a stale base
  would hide a real twin) and each head only when the checkout lacks it. The staging row
  gets `twin_of: <repo>#<master number>`. Two rows on one
  base, a checkout that cannot answer, or a master pull request no longer needing the user (so
  not a row) marks nothing, and both are reviewed as members. `featurebrief.compose` shows
  the twin's row as the master's TWIN, adds `--twin <twin> <master>` to the prep line, asks
  no verdict for it and has the orientation name it; `reviewpost.member_summary` posts the
  twin's pointer (`pointer` in the answer: the master pull request, reviewed there) in place
  of the summary, with no inline comment and the master's verdict.

## A research card publishes nothing (c-433)

`options.kind = research` is the one kind whose outcome is not a pull request. Before
c-433 the brief told every work house to branch, test, push and open a draft, so a
research card opened one (PR 4138, declined). Now, keyed on the kind in `workcard.is_research`:

- **The worktree is scratch.** `worktree` still cuts it through the worktree tool (the seed files
  are what make the repo readable and runnable), on a local `research/<story>/<slug>`
  branch that exists only because the tool needs one. `naming.PREFIX` maps research to
  `research`, not `chore`; the tracker story type is still `chore`, since the tracker has
  no research type, and a story is still minted when the card asks.
- **The brief** (`briefing.RESEARCH_HOUSE`, `RESEARCH_ENDING`) says never commit, never
  push, and names no test step, no pre-gate pipeline, no pull request. The ending is the
  record (`context.md`) plus ONE findings board (what was looked at, what was found, how
  it connects), and `kb stage <id> review --output <the board link>`. **The outcome IS the
  research** (c-719): the record is a research outcome (`kind: research`, which Keel's
  skeleton opens it as, `planbrief.context_skeleton`) whose sections are Findings, What it
  means, What is next and Evidence, the findings written there whole and explained; the
  ending says no separate report file and no link to one, and `RECORD_PAGES` has the board
  embedded under Findings with a sentence or two saying what it shows. On the deck a work
  research card is research by its kind (`K.research`, [the deck](40-deck.md), "Research on
  the deck"): Done, never "PR body" or "This publishes it".
- **The mechanism** is in the verbs and the house's permissions, not the prose: `deny`
  (`fence.py`) denies a research card's house `Bash(git push:*)`, `Bash(*git push*)`, the
  code host's MCP write tools and `Bash(*packs/work/pr*)`; only the user changes `options.kind`
  after create (the user's token or the deck's human path; `Board.set_fields` refuses every other
  actor), so nothing else can lift it. **The Bash patterns are a partial fence:** they match
  the command as written, so `git -C . push`, a shell alias or a script that pushes passes
  them. The real guard is the verbs: `pr` (open and `--ready`) refuses a
  research card, and `publish` for one writes one note and touches neither the code host
  nor the tracker, so Approve outcome needs no credentials and moves the card to done.

## A shipping card (lane SHIP)

The user's Approve outcome's `publish` answers `"shipping": true` beside the ready pull request,
which is what moves a work card to `shipping` rather than `done`
([cards and gates](10-cards-and-gates.md)). From there the adapter does four things for
the engine, each one a verb the engine calls and never a word it learns:

- **It looks** (`ship <id> poll`, `prsight.py`). One GET of the pull request (state, author,
  head commit, each participant's review), its comments (paged; deleted ones and the
  author's own left out, and an app's (user `type` `app_user`) and every comment of a
  resolved thread (its root's `resolution`); each carries its `updated` time, so an edit is
  told again; these field shapes are the host's documented ones, to be checked against a
  live response), and the head commit's build statuses; plus the branch's count
  behind its base from the repo's own checkout after fetching the two branches (remote
  tracking refs only, the checkout is not touched). The host's `OPEN`, `MERGED`,
  `DECLINED` and `SUPERSEDED` are said as open, merged, declined and declined. **The
  checks** are the commit statuses on the head: the cloud repo's pull request pipeline
  (a migration heads check) reports there; the CI builds of both repos report to a chat
  channel and not to the host, so for the frontend repo the checks read `none`, which is
  the truth rather than a gap in the reader. Any failed or stopped status is `failed`, any
  running one `running`, all passed `passed`.
- **It gives the house the method** (`ship <id> method`, `<install>/packs/work/rules/comments.md`, c-600):
  the colleague's review-comments method adapted, with its employer specifics kept here:
  understand the change first (the diff, code outside it a comment points at), the stack's
  gotchas per repo, each thread read as a conversation, then per comment a one-line summary,
  a verdict (valid, not valid, valid deferred) with reasoning checked against the code, and
  exactly one outcome (a code change only when valid, with tests where it carries logic; a
  reply otherwise); specialist subagents in parallel when there are many or a claim needs
  checking across files, advising only; verify before recording, saying exactly what ran.
  That skill's own `pr.py`, its credentials and its approval gate are not used: Keel's deck
  is the gate, and `codehost` and `prsend` already read and post.
- **It looks without noise**: `prsight` leaves out deleted comments, the author's own, bot
  comments (`user.type` `app_user`, or a name ending `[bot]`), the tracker's link comment
  (its integration posts it under a person-typed admin account and signs it with the
  tracker's bot name in brackets, `prsight.is_tracker_link`, c-651: c-239's was kept as
  review) and every comment of a
  RESOLVED thread (the root carrying `resolution`, and each reply under it), and says
  whether the pull request is still a draft and the branch it merges into (`base`, its
  destination, which the engine uses when the card names no `options.base`, c-651).
  `behind` counts against the base in the engine's own order (`shipping.base_of`): the card's
  `options.base` first, then that destination, then the default.
- **It sends the user's Ship** (`publish <id> --answer`, `prsend.ship`): every reply's handle is
  checked against the card's pull requests first (a dotted handle naming none refuses the
  whole), every worktree must be on its pull request's branch, then each branch is pushed
  as a plain fast-forward (above; a protected branch is refused), each pull request still a
  draft is marked ready, and only then each reply is posted, under comment `<n>` for a
  `c<n>` handle and as a general comment otherwise. A reply already on the pull request word
  for word under the same comment by its author is not posted again. A push that fails
  posts nothing. It answers `{"shipping": true, "shipped": true, "pr", "pushed": {repo: sha},
  "ready": [repos], "posted": [handles], "sent": [{handle, text}]}`, where `sent` is every
  reply now on the host, which the engine keeps so a second Ship says nothing twice. The
  card stays at shipping. The house is fenced from all of it (`fence.at_shipping`, and the
  engine's house guard, read live).
- **It briefs a house started at shipping** (`briefing.SHIPPED_ENDING`, for a card the
  shipping sync found with no house): the card has shipped, batches will come with the
  method, never push. The build's `ENDING` is untouched.

**A card may carry one pull request per repo** (SH-10). `options.prs` is `{repo: {pr,
branch}}`; the old `options.pr` (with `options.branch`) is still read for the card's primary
repo when `prs` does not name it (`workcard.prs_of`, primary first). Every verb above works
over all of them: `poll` looks at each (its own comments, reviews, checks and behind count)
and prints them under `prs`, each with its `repo`, `pr` and `primary`; `diff` prints each
under a line naming its repo; the user's Ship checks EVERY worktree is on its pull
request's branch before the first push, pushes each, and sends a reply to the pull request
its handle names (`<repo>.<handle>` for any but the primary, which is how the engine names
an item from another repo); the reap takes each repo's worktree on its own branch. A
worktree per repo is recorded in `options.worktrees` (`cut.record_worktrees`, for a
cross-repo card), which is where the push and the lint's `path:line` check find the ones
that are not the primary. **No comment is cut silently** (c-580): the card's record keeps a
comment's text to 2,000 characters (`shipwatch.TEXT_MAX`), and a longer one ends
`[cut: full text in comments/<handle>.md]`; on every look the watcher writes each
comment's whole text, with a line naming who, when and where, to
`state/cards/<id>/comments/<handle>.md` (`shipping.keep_whole`, only when it changed).
A repo whose pull request is on a branch of its own is cut on
that branch (`cut.branch_of`).

Before it ships, the same holds (c-565, found on c-272, whose Approve flipped only cloud's
draft): `pr --draft` opens a draft in each repo, `publishable` checks each, `publish` flips
each, and `act links` links each. A single-repo card writes, checks and publishes exactly
what it did before: `options.pr` and nothing else.

A card that shipped before its worktree was cut here gets its REAL branch back first:
`cut.ensure_local_branch` fetches a branch only the remote has before the worktree tool
sees the name, because given an unknown name it would start a new branch from the base,
and a push of that would overwrite the pull request.

## options.json

The per-card option schema the deck's card dialog draws: a list of
`{key, label, type, stored, options, default or default_if, when}`. `stored` is `card`
(a real column) or `options` (a key in the JSON column). `when` and `default_if` are
`key == value` and `key != value` clauses joined by ` and `, with values unquoted.

A row may also carry `"inherit": false` (c-760). A slice takes its parent's stated value
of every row stored in `options` ([cards and gates](10-cards-and-gates.md), "A slice starts
as its parent would"), and the mark is how a pack says a row belongs to the one card: a
reference to one ticket under a key of the pack's own, an estimate, a link. The core
already holds back `tracker_ref`, a `kind` of research or review, and every `textarea`
row, so a pack marks only what those do not cover.

Since c-760 the board reads a row's `when` itself, when a slice is filed under a parent
that stated the row (before, only the deck's form did). A `when` it cannot read (a clause
with neither `==` nor `!=`) refuses that split or `kb create --parent` with "the <space>
sheet's row <key> has a `when` the board cannot read: ...": fix the row in the pack.

The work schema's fields, in the order the dialog draws them: repo (multiselect, the first
is the primary worktree), autonomy, kind (bug, feature, chore, research; it names the
branch type, and research hides the test and story-writing rows), model, the story reference and story mode (create at task start, link an
existing one, or none), the base branch, rich story, design doc, link doc to story, unit
tests in the pull request, test doc, model strategy, plan style, and a free-text guidance
steer for the house.

A pack's `repo` row that lists no repos offers the space's own (`cardspec.space_row`, c-689):
the work pack and the example list theirs, and a pack for whatever a person clones (the
GitHub pack) cannot, so it writes `"options": []`.

This is where a retired control center's per-card settings form was kept exactly as it
was. The engine stores all of it in one `options` column and never learns a single one of
these words.

## Providers: the extra deck routes

`providers/<route>` prints JSON for a deck route that only exists when an adapter declares
it. The work adapter declares one, `reviews` (`<install>/packs/work/providers/reviews`), and it
carries no rows: the Reviews page draws the review cards, which are board cards, and reads
from this route only its `settings`, the gear's facts. Those are auto review, the review
model and the models the gear may offer, as this machine will read them
(`keel/reviewsettings.py`, reached through `keelbridge`), and the gear's two route verbs.
Settings that cannot be read leave the toggle out and `models` empty, so the deck draws no
control rather than inventing one. With no adapter, the route is not in the rail.

Lane RETIRE (2026-09-24) removed the rest. The old review scanner's rows and verbs (its
`state.json`, overlay, dismiss file, scan log and launchd job, and Scan now, the lane moves,
Lavish, Terminal and Launch review, Generate orientation) went with the scanner, and the
pull request watcher's `prs` route and its PRs page went with the watcher: a work pull
request Keel's house built is a card in `shipping` ([the drain](30-drain.md), "Shipping"),
and the Cards page's Shipping view is where it is found.

The provider shape is still general, for a route an adapter adds later: it prints `{route,
columns, items, hidden}`.

- **`columns`** is the route's lanes in the order the deck draws them, empty ones
  included, because an empty lane is still a drop target.
- Every **row** carries **`kanbanState`**, the lane it sits in, decided in the provider and
  never on the page; and **`verbs`**, a list of `{verb, label, to}` where `to` is the lane
  running that verb lands the row in, or null when it moves nothing. `to` is what makes
  drag-to-move general, in place of the page guessing that a verb named "hold" means the
  "held" lane. A lane no verb names is simply static.
- Every row also carries **`repos`**, the repos it touches, as a LIST, because a cross-repo
  review touches two. The deck builds its repo chips from the union of those lists and
  matches a row to a chip by membership, so a cross-repo row answers to both of its repos
  rather than to a chip of its own. `<install>/history/docs/deck-mobile-audit.md` recommended the fix here
  rather than in the deck's filter.

The providers run on this machine: the deck reads them through `keel/deckstate.py`, and a
route verb from the deck runs here through the `adapter` action. That is why the gear's two
verbs are the adapter's rather than the deck's own: the override they write is the one this
machine's drain reads.

The deck runs a route verb through the `adapter` action, which shells `act do`. See [the
deck](40-deck.md) for the gear.

## Where it lives

`<install>/packs/work/` is Python modules behind thin executables, so the logic is testable and
the entry points stay small:

- executables: `act`, `brief`, `deny`, `pr`, `publish`, `publishable`, `review`, `ship`, `worktree`
- modules: `workcard`, `naming`, `cut`, `briefing`, `fence`, `tracker`, `codehost`, `pulls`,
  `prsight`, `prsend`, `shipmatch`, `reaping`, `teardown`, `reviewing`, `reviewscan`, `reviewpost`, `featurebrief`, `optionsheet`,
  `providers`, `acting`, `readiness`, `twinrule`, `restack`
- `options.json`, `providers/<route>`
- `pack.toml`, `config.example.toml`, and `rules/`: the house texts (`house.md`, `research-house.md`,
  `review-house.md`, `feature-house.md`, each taking `shared-stack.md` through its `@` line) that
  `briefing.rule` reads, and `comments.md`, which `ship <id> method` prints ([packs](62-packs.md))
- `<install>/packs/work/drift-terms`: the employer term list the `make test` grep uses. It lives
  inside the pack it guards, the one directory the grep exempts besides `docs/`, so the guard's own text cannot trip it.
- its tests and fixtures under `<install>/packs/work/tests/`: the pack is an install's own,
  so the adapters job (`make test-all`, and `make test` when it reaches the packs) runs its
  suite from the install `KEEL_CONFIG` names, after the tree's packs' own `tests/`, each in a
  process of its own (`tests/packsuites.py`, c-689, c-726 r1.F4).

`keel/adapters.py` is the engine's half: discovery and invocation, and nothing else.

## The sandbox adapter (the demo, c-569)

`packs/sandbox/` (the example pack, c-617) is a second adapter that answers every verb above in the same JSON
shapes, with no credential and no network: its code host and its tracker are JSON files
under a sandbox directory, and its repos are clones of bare origins on the same disk. It
exists for the demo video (c-568), which is recorded on a Keel of its own, and it is the
example of an adapter an open-source Keel can ship. Its tests (`tests/test_sandbox.py`) hold
each verb to the keys the work adapter's tests pin (copied there as literals, so a key the work
adapter adds is not noticed), then hand the answer to the engine's own reader
(`deckstate.pulls_of`, `adapters.publishable`, `shipwatch.fold`, `reviewcards.upkeep`), so a
change on the ENGINE's side that parts them fails there.

**The sandbox.** `demo/sandbox/setup` builds `~/keel-sandbox` from nothing (`--config-dir` names the logged-in config dir its houses run in, default the personal space's), and `--clean`
removes it (only a directory carrying its `.keel-sandbox` marker). It holds:

- `keel.toml`, from `demo/sandbox/keel.toml.in`: its own `state_dir`, `segments_dir`,
  `adapters_dir`, `serve_port` (8890), lavish and voice ports; three spaces, `work` on
  the sandbox pack (`pack = "sandbox"`) with repos `api` and `web` and the pre-gate pipeline in the sandbox's own
  words (`demo/sandbox/pipeline-work.md`, with a `## Publish` of its own), run as the live
  work space runs it (`preship_first = true`, `review_full_rounds = 1`, c-604), `personal`,
  and `console`, every one in the
  personal config dir. It names no `[integration]` and no
  real repo, so a Deploy tap there has nothing to move (`deploy.repos` is empty);
- `adapters/`, its `adapters_dir`, EMPTY: the work space is the sandbox pack, so no other
  adapter (and no other adapter's `hearing.json`) can be reached from the sandbox at all;
- `repos/api`, `repos/web` (a tiny reports app, its history by made-up colleagues, whose
  first commit adds a `.gitignore` of `__pycache__/` and `*.pyc`: without it a house's
  worktree kept them untracked and the reap at done never took one, c-604) and
  their bare `origin/<repo>.git`; `host/<repo>/<n>.json`, one per pull request;
  `tracker/<n>.json`, one per story; `worktrees/`.

Setup refuses `KEEL_LIVE_STATE`, a home inside any Keel checkout, and the live deck's,
lavish's and voice's ports. **Everything reaches the sandbox through `demo/sandbox/run
<command>`**: it sets `KEEL_CONFIG` to the sandbox's toml, keeps `KEEL_HOME` at the checkout,
drops `KEEL_LIVE_STATE`, `KEEL_CARD`, `KEEL_TOKEN` and `KEEL_BOSUN` (and the retired `KEEL_URL`), and loads
the toml through Keel's own loader first, refusing unless the board it opens is inside the
sandbox, or any card numbered below c-9000. The adapter holds itself to the same: it
refuses unless the marker is there, `KEEL_CONFIG` is the sandbox's own toml and the loaded board is inside the sandbox (`sb_card.home`), and its `kb` is always
handed that toml; the seed checks it first.

**Card ids never meet the live board's.** A house is a harness session named after its card
id, and the sandbox's houses share the personal config dir, so the live drain would take a
sandbox house named `c-042` for its own `c-042` (and the other way round). `setup` files the
week of finished cards (`demo/seed history`) at c-9201 onward, so every later card is numbered
past them (`sb_card.ID_FLOOR`), and `run` refuses a board holding a lower id.

**The verbs**, over `sb_host` (pull requests) and `sb_tracker` (stories):

| Verb | In the sandbox |
|---|---|
| `worktree` | `git worktree add` per repo under `worktrees/<repo>/`, on the card's branch (`<kind>/st-<n>/<slug>`), after minting the story when `tracker_mode` asks; a review card is DETACHED at its pull request's head, `options.review_head` recorded |
| `brief` | the house, the story, the ending: push to the bare origin, `packs/sandbox/pr <id>`, stage review; the review and shipped endings as the work adapter's, shorter |
| `pr`, `publishable`, `publish` | the work adapter's rules over the JSON host: a draft per repo whose branch is on origin, the body from the repo's ```copy block; the publishable check in every repo; Approve flips each ready and moves the story to `in review` |
| `publish --answer` | the user's Ship: pushed, drafts readied, then the kept replies posted, in the work adapter's answer shape; a review card's kept findings inline, the summary and the verdict, recorded as they land so a retry says nothing twice |
| `deny` | the push and this adapter's `pr` and `publish` for a research card and a card at shipping; the commit as well for a review card |
| `ship poll`, `diff`, `method`, `mine`, `down`, `reap` | the sight from the JSON host (checks read `passed`; a comment marked `bot`, and a resolved thread, left out; `draft` said), a short method of its own (no employer words), the diff from the clone, the user's open pull requests matched by branch then story, no containers to stop, and only a clean worktree under the sandbox's `worktrees/` removed (anything else is kept and said why, never deleted by hand) |
| `review scan`, `poll`, `branches`, `story` | open pull requests where `me` is a reviewer and not the author; their state; branches from the bare origins; a story's title |
| `act`, `providers/reviews` | no card verbs; links with `story`, `pr`, `prs`, `unpublished`; the Reviews gear's two settings |

A pull request's link is `https://code.sandbox.test/<repo>/pull/<n>` and a story's
`https://tracker.sandbox.test/story/<n>`: `.test` is reserved and resolves nowhere.

**The seeded day** (`demo/sandbox/run demo/seed <phase>`, `demo/seeding/`): each phase
brings the sandbox board to what a scene of the script starts from, through Keel's own
Board (and the review fetcher and the adapter's verbs), each move by the actor who would
really make it, on a clock the phase sets. `history` (run by `setup`) files a week of
finished cards from c-9201; `morning` files the search fix merged at 02:10, two colleagues' pull requests filed as review cards
by the real fetcher and reviewed, and a plan at the gate, and five cards working beside them
all day (`demo/seeding/parallel.py`, c-807: two features, a bug fix and two more colleagues'
pull requests under review, so the board shows six tasks moving at once with the export
card); `export <card>` gives the live
export card its change in both repos, a draft in each and its outcome; `breaks` files a
card Keel refused at review, Bosun's request, its fix card and one deploy ask ("Deploy next
to main?"); `evening` answers every gate (the reviews through the real Approve, so the
comments land on the JSON host), and takes the five parallel cards through theirs: each
feature's draft opened and approved (shipping), the bug fix approved and merged (done), each
review's findings at the gate and approved with the rest. The parallel cards are BOARD STATE
with their records (a branch, a draft, an outcome or a review on the card), never houses: the
drain starts only a card at `assigned` and puts back only one that carries a session, and the
pools count only listed houses, so the export card's is still the day's one real session.
None of the five ever sits at `assigned`, where the sandbox's running drain would start one:
each feature card is filed straight at `building`, and each review card goes from the
fetcher's `inbox` to `building` in one move, the user's tap.
Their two pull requests take api #13 and web #32, so the export card's drafts are api #14 and
web #33, and Bosun's fix card is c-9218: the film's cut names those. After `morning` and after `evening` it checks what Harbor
would read (the two reviews and the plan; then nothing, with the export card and the two parallel
features shipping) and
fails if it is not that. Run again, a phase changes nothing it already did, and one that
stopped halfway is finished: each step is taken only from the stage before it.

**Recording the scenes** (c-570, `demo/scenes/`). One steps file per scene of the script,
`NN-name.json`, which is a `keel-browser video` file ([houses](20-houses.md), "The one
browser tool") with three keys more: `start` (the deck path it opens on), `seed` (the phase
the board must be at) and `harbor` (the lines the user says in it). Desktop scenes are 1920x1080,
the phone scenes (2, 6, 7, 10) 390x844, all at 2x. Scenes 4 and 11 end with steps the film
does not show and the short cuts do (c-807): the board as a kanban and the reviews after the
export card starts ("the board", "the reviews"), and the day's kanban, done included ("the day").

- `demo/sandbox/run demo/scenes/record <NN> [--set card=c-92NN]` plays one take into
  `recordings/NN-name/take-K/` (clip, stills, timeline, the filled `steps.json`), SWEEPS it
  and indexes it in `recordings/index.json`. The sweep matches every step's page text and
  every Harbor answer against `<install>/packs/work/drift-terms`, the list `make drift` greps, and
  against the shapes of this machine's own paths (a home directory, a config dir, a
  credential: Bosun's Logins panel prints them); a hit rejects the take, and the index says
  which pattern by number, never the words. The first clean take is kept unless `--keep
  take-K` says another; a scene where Harbor speaks is kept only once its answers are
  captured and swept, and a kept take that a later sweep finds dirty stops being kept.
- `demo/sandbox/run demo/scenes/harbor gateway [--fresh]` is the sandbox's Harbor: the real
  gateway (`harbor_voice.server.serve`) on the toml's voice port, behind the sandbox deck,
  with its state and conversation under `<sandbox>/harbor/state`, its turns run in
  `<sandbox>/harbor/` (whose `CLAUDE.md` is `demo/scenes/harbor-memory.md`, a memory of the
  sandbox's facts only, and whose `.claude/settings.json` denies the live state, `claude
  agents` and a `KEEL_CONFIG` of its own choosing: the fence is a rule, not the memory's
  prose), and Harbor's config dir from this machine, the one that holds the user's
  login and rulebook. A worktree's own Harbor dir has no login, which is why this is a
  launcher and not `bin/keel-voice-gateway`. `harbor mic` turns the user's recorded line into the
  16-bit WAV a scene's `mic` plays (padded and lifted to speaking level; only for the mic),
  so scenes 2, 6, 7 and 10 are real voice turns through the recogniser. `harbor capture <NN>
  <take>` writes each answer of the take's window as text and as audio in `harbor/`. The
  gateway keeps no copy of what it streamed, so the audio is the answer SYNTHESIZED AGAIN,
  pinned to the engine the page's provenance line says spoke live (Google or kokoro-onnx),
  and refused rather than spoken in another voice; a page that names none gets no audio.
  Both the written answer (`NN.txt`) and the spoken one (`NN.said.txt`) are swept.
- The recordings are edited into the film by `demo/video/`, and `demo/build` plays the
  whole day in order: [the demo video](65-demo.md). The public release leaves `demo/video/`
  and `demo/music/` out, so there the film cannot be built.
- `demo/sandbox/run demo/scenes/sheet <dir>` draws a contact sheet, one frame per scene
  from each kept take (the still the scene file names as `hero`), and `recordings/index.md`
  says the same index for a person.
- Two sandbox quirks the recorder works around: the sandbox drain probes this checkout's
  talker login, finds none and raises a login ask on the sandbox's Bosun list (answer it
  Later on the sandbox deck, or Harbor reads it out); and a connected turn (`keel converse`,
  scene 7) is taken only while the house is idle, so scene 7 is recorded at an idle moment.

## How to change it

- A new option: one entry in `options.json`. The deck draws it, `kb set` stores it, no
  engine change and no migration.
- A new card verb in the inspector: add it to `act verbs` and handle it in `act do`. The
  deck takes the label from the adapter, so there is nothing to change on the page.
- A new provider route: a `providers/<route>` executable printing the shape above, plus a
  `VIEWS` entry on the page. Give every row a `kanbanState` and give a verb that moves a
  row a `to`, or the lane will not accept a drop.
- A second employer, or a second job: a second adapter directory and a second space. The
  engine does not change.
- The sandbox adapter follows the work adapter: a verb or a key added there is added here
  too, by hand; `tests/test_sandbox.py` holds the sandbox to the engine's readers, not to the
  work adapter's code.
- What was proven live, and what was not, is recorded in `<install>/history/tests/live_work_card.md`. The
  build, the review gate, the push and the draft pull request are covered by the adapter's
  own unit tests against a fake HTTP seam rather than by a live run.
