# The deck

The deck is the surface the human drives Keel from: a stdlib HTTP server bound to
127.0.0.1 and one page with no external resources. Everything the terminal can do, the
page does. One navigation model across breakpoints: a left rail on the desk becomes a
bottom dock on the phone, never a drawer, and every section is a route.

## The server

`keel serve [--port N]`, or `keel run --roles serve`. The tailnet fronts it; it is never
exposed directly. Reads are cached for three seconds, a write drops the cache and moves the
state's revision, and the page is told on the event stream rather than finding out on a poll.

**Its listen backlog is the system's (`serve.BurstServer`, which `DeckServer` uses).** The shell loads some 25 files at once and `tailscale serve` opens a
connection for each. socketserver's default backlog is 5; macOS resets a connection past it
(Linux drops the SYN and the client retries), and the proxy answers the reset 502, so on a
Mac the phone's deck can come up blank with 13 to 19 of its files 502 (measured: 7 of 40
parallel GETs on 127.0.0.1 refused). `tests/test_serve.py` `BurstTest` holds it.

**What a load costs (c-540).** Measured 2026-09-26: the whole state was 2 MB of JSON sent
raw, half of it briefs and a third of the cards archived, a cold build about a second, and
every app file `no-store`, so a switch between the Keel and Bosun PWAs fetched every script
and the whole state again. Now each page asks for its own scope, JSON is gzipped, app files
are kept and revalidated, and the Console has the shell worker. A cold build's floor is the
harness listing (`claude agents --json`, one per config dir, 0.3 to 1 s each on a loaded
box): the listings run side by side, and a cold build runs them beside the board read
(`Deck.listing`, a join). Since c-638 the listing is a kept reading every scope shares (below),
and one build resolves the artifact roots once (`artifacts.roots_held`).

**A build in milliseconds (c-638).** Measured 2026-10-04 on a 638-card board: `/api/state`
took 3.4 s and nearly every request built afresh, since the revision moves with every board
write. Three costs, now gone from the request path:

- **The disk, per card.** Each link resolved its file from `/` up, an lstat per component:
  about 10,500, 2.2 s. Inside one build (`roots_held`) a directory is now resolved once and
  a file costs its own lstat (`artifacts.resolved`, the same answer as `Path.resolve`). A
  path found missing is held too, with everything under it (`artifacts.missing`): 27 refs
  left from an old machine sit under `/home/...`, macOS's automount, where every look cost
  11 ms. Serving a token still resolves afresh (`untoken`), so the memo never decides what
  is served.
- **The subprocesses, per build.** The work pack's `act links` (0.5 s), its verbs and
  provider routes, git for where Bosun's done cards landed, and `claude agents` are the
  deck's kept readings (`keel/readings.py`, `Deck.kept`). The first build in a process
  reads them. After that a build answers from the newest reading at once, and one that is
  old (links and providers 30 s, verbs 60 s, git 5 s, sessions 2 s) is read again on a
  thread of its own. The links reading covers every live card of the space whatever the
  page's scope, so the Bosun page never narrows the deck's; one that covers fewer cards
  than the build asks for (a card just went live) is read again at once. Each read raises
  when it fails (`strict`: `adapters.ReadingFailed`, `harness.HarnessError`, git's
  `MergeRefused`), so a failed refresh keeps the last good reading rather than showing no
  links, no house or no landing for a window. A first read that fails is answered as it
  always was (no links, no verbs) and held as already old (`Kept.seed`), so it is read again
  on a thread rather than in line on every build; while one provider route fails, every
  route stays at its last good reading. A reading lands only if none that started later
  is held. The live strip asks for the listing as it is now (`listing(fresh=True)`), read
  on its own and never kept, so the kept reading's refresh still sees a house that started
  and tells the pages. A closed server's readings start no refresh and land none
  (`Readings.close`, from `DeckServer.server_close`), and `Deck.moved` does nothing once
  the stamp is pinned shut. A refresh that reads something different
  calls `Deck.moved`: the documents drop and the pages are told, so the change is drawn a
  refresh later rather than a poll later. A write (`Deck.drop`) also lists the sessions
  again, so a house that started shows within its own listing time; when it did change,
  the pages are told twice, once for the write and once for the house.
- What remains is the board itself: about 160 ms warm for every card, most of it deriving
  each card's state with a few queries per card (`views.derived`), the next thing to batch
  if a page is still slow. A cold build, the first after a restart, still reads everything
  once, about a second.

**Live cards first, done cards behind the draw (c-549).** Measured 2026-09-27: done cards were
225 of the deck's 294, 510 KB of its 771 KB (88 of 139 KB gzipped), and 14 of the Console's
17. No first screen needs them, so a page asks for its scope's LIVE PART, draws, and only
then asks for the DONE PART and merges it in (`K.load` and `K.afterDraw` in
`app/ui.core.js`; `App.live` is the live part as it came, `App.data` the merge every view
reads, and on an id in both the live copy wins). After that first pair every refresh asks
for both parts at once and draws once, so one part landing before the other never drops a
card reaching done (the two are separate requests, so a write that lands between them shows
at the next refresh).
The done part is tagged on its own cards, so a refresh that moved none of them is a 304 and
a phone refresh moves the live part alone (about 46 KB gzipped against 139). Until the done
part lands (`K.doneHeld`, which reads `scope.done`), the views that show done cards say so:
Include done shows no count, Cards with Include done on and the kanban's Done lane say
"Loading done cards", and a done card opened by link
waits for the done part before it is asked for as `card=`. The tree draws its slices from
`derived.tree`; a follow-up or a slice it waits for that is a done card says "loading" rather
than "not in this space" (`app/ui.tree.js`), and a slice's In its tree section appears once a
done parent has landed. A done part that fails, or answers an error, is never taken as one:
it is asked for again on a backoff (1, 2, 5, then 15 seconds) until it lands, and it never
holds a refresh of the live part back. The page's half runs under node in
`tests/fixtures/deck-done.js`.

| Route | What it serves |
|---|---|
| `GET /`, `/ui*.js`, `/ui.css`, `/manifest.json`, `/sw.js` | the page, from `app/` (`serve.APP_FILES`), gzipped for a browser that says it takes gzip (`serve.compressed`, kept per file and mtime). Each file carries an ETag of its mtime, size and encoding (`serve.file_tag`) and `Cache-Control: no-cache` (`serve.REVALIDATE`): the browser keeps it and asks on every use, a match is a `304` with no body, and a deploy moves the mtime so the very next load gets the new file (c-540; they were `no-store`). The shells (`/`, `/index.html`, `/board...`, `/console`, and the plan pages' own shell `app/plan.html` under `/plan`, `/outcome`, `/context`, `/files`, `/ci` and `/comments/<c-id>`, and `/file/<c-id>/<name>`) stay `no-store`: each carries the page's cookie (who may act as the user, below) |
| `GET /comments/<c-id>`, `GET /api/comments/<c-id>` | a card's review comments page on the plan pages' shell and its one answer (`keel/commentsroute.py`): each round its house was told at shipping, with verdicts, commits, replies and the user's marks, read again on every board event for the card, [the comments page](67-comments.md) |
| `GET /ci/<c-id>`, `GET /api/ci/<c-id>` | a card's CI page on the plan pages' shell and its one answer (`keel/ciroute.py`): the card's checks and the builds that carry it, read from its space's pack (`ci`) on the page's first draw and on Refresh, never on a board event, [the CI page](66-ci.md) |
| `GET /files/<c-id>`, `GET /file/<c-id>/<name>`, `GET /api/plan/<c-id>?doc=files|file&name=<name>` | the card's markdown files on the plan pages' shell (c-719, `keel/cardfiles.py`): the list, and one file drawn by the plan's own renderer, read only, served only from inside the card's folder, [plans on the deck](47-plans.md), "The viewer". The card pane lists the same files (`detail.files`) under its boards, each opening its page. Who may read them (r1.F12): whoever can reach the deck, exactly as for the plan and outcome on the same route, which needs no token or cookie for a read; the artifact route's signed token is not asked here, on purpose, because a card file is the card's own writing and the deck's network is its boundary |
| `GET /plan/<c-id>`, `GET /outcome/<c-id>`, `GET /context/<c-id>`, `GET /api/plan/<c-id>[?doc=outcome|context]` | the plan, outcome and context pages (pages of their own, `app/plan.html` booted by `app/ui.planpage.js`, not the deck's shell) and their one answer, [plans on the deck](47-plans.md). Open plan opens a plan in the plan format there (`links.formats`, read where the file is), and a lavish plan or a markdown plan without frontmatter as it always did. View context always opens the viewer: the outcome page for a `context.md` in the format, else the context page, which draws it as plain markdown with no gate (c-644) |
| `GET /theme-work.css`, `/theme-personal.css` | the two space themes, the palette every surface a house writes links ([houses](20-houses.md)). The page itself does not load them: a house links the copy that sits beside its own surface, and these routes are for a surface reached through the deck's origin |
| `GET /api/state[?scope=deck\|bosun[&archived=1][&card=<c-id>][&steps=1][&part=live\|done]]` | the state document, with an `ETag` carrying its revision, the scope and the encoding. `If-None-Match` on it is a `304` with no body, so a page that is up to date renders nothing. Gzipped for a client that takes gzip (`reply_json_tagged`, also `/api/card` and `/api/plan`). With no query it is the whole board, which every machine reader gets (Harbor's digest, the voice gateway). A SCOPE is what a page draws (`deckstate.in_scope`, c-540): `deck` is the unarchived cards, `bosun` the cards Bosun builds (`derived.bosun`, c-591; named `console` until c-593, and an unknown scope is the whole document); each clips a brief to 400 characters with `brief_clipped` (the pane reads the whole one from `/api/card`), and `archived=1` adds the archived ones, which the deck asks for only while Include archived or Include dismissed is on (`K.followScope`); until then those two switches show no count, since the cards they would add are not loaded. The page's asks are run under node in `tests/fixtures/deck-scope.js`. `card=` is the card the page has open when its scope would not hold it (an archived card the user was linked to): it is held whatever the scope and marked `outside`. The Edit dialog never starts from a clipped brief: it reads the whole one from `/api/card` first. Every top-level list (`needs_you`, `queue`, `houses`, the space counts) is the whole board's in every scope, and `scope` says which cards `cards` holds. A PART cuts the scope in two (`deckstate.part_of`, c-549), both from the one cached build: `part=live` is the scope without its done cards, with every top-level list and the revision's ETag; `part=done` is those cards alone, with `now` and `scope` and nothing else, tagged on a hash of its cards (`serve.get_done_part`). A done card stays live when it needs the user, has a house, is blocked, is a review card (Reviews lists a posted review) or is the `card=` (`deckstate.in_done_part`). A part means nothing without a scope, and a scope with no part is whole, as before. `steps=1` is the Start view's ask for the first-run steps (c-678 review): without it, on an install whose first run is finished, only the required steps are read and every other is `{done: null, light: true}` (`firstrun.report`), so no other view's poll reads the tier drafts, the browser's folder, Bosun's transcripts or the backup's files; `scope.steps` says whether every step was read, and the Start view asks again when it was not (`K.followScope`). An install that is not finished reads every step whoever asks, and so does the whole document |
| `GET /api/health` | the health verdict and the services block (`health.current`), never a `304`: the verdict does not move the state's revision, so this is how the page sees a new one.  |
| `GET /api/events[?board=<b-id>]` | the live channel: server-sent events naming what changed (below) |
| `GET /api/card/<id>` | ETagged on the card's own `updated_at` and event count, so a pane that is current is a `304` without the context or the plan text being read at all. One card: every event, the context, the PR body, the plan text, when the plan file was last written (`plan_at`), the newest `board` for that card, its counts and how many it has ([the board](45-board.md)), the children |
| `GET /console`, `/console/queue`, `/console/shipped`, `/console/journal` | the Bosun page, a page of its own (`app/console.html`, [Bosun](96-bosun.md)): one shell, its four sections as routes (`serve.CONSOLE_PATHS`, c-591), installable apart from the deck with `/console.webmanifest` |
| `GET /api/atlas` | this documentation's page list: slug, title, order |
| `GET /api/atlas/<slug>` | one Atlas page as `{title, html}` |
| `GET /api/settings` | the Settings view's report (`settings.report`, c-633): the install (null: read-only), the schema (each setting's label, help, kind, choices, range, unit, group and scope), the models, the warnings, and every value with where it came from: `config`, `pack`, `default`, or `gear` for the Reviews gear's live override |
| `GET /api/hello` | Meet Bosun's hello watch (c-729, `firstrun.hello`): `{hello}`, whether the user has said hello in Bosun's session. A read outside the setup lock; the deck moves only when the answer changed (`Deck.heard`, r1.F6, r1.F7) |
| `GET /api/setup` | the Setup view's report (`onboarding.report`): per space its tier and repos with their tiers and proposals, every pack with its checks, `fresh` while no space lists a repo ([onboarding](89-onboarding.md)) |
| `GET /api/board/<b-id>[?since=<line>]` | one board and the accepted lines after that line: the blackboard's live channel ([the board](45-board.md)). A board the user deleted is a `410` carrying who deleted it and when, so the page offers Restore; an id that never existed is a `404` |
| `GET /board`, `/board/<b-id>[?view=diagram\|outline\|walk]` | the page again. The board is the ONE route with a path of its own, because a board is a link the user sends to themselves; WHICH VIEW rides in the query, because it is a way of looking rather than another thing to open. `/board/<b-id>/<n>` from the frames era still opens its board |
| `GET /api/boards[?q=<words>][&deleted=1]` | every board with its card's title and story, and the boards a search matches, each with its snippet and the node it is on (`keel/boardlist.py`, [the board](45-board.md)). `deleted=1` reads the trash instead, for the Deleted chip |
| `GET /api/boards/uses?ids=<b-id>,...` | the plans and outcomes of open and recent cards that embed those boards, asked by the delete's confirm (`keel/boarduses.py`, [the board](45-board.md)) |
| `POST /api/board/<b-id>/inbox` | one file the user put on that board, the page's own only (the cookie, below): the segments' own upload control, pointed at the board ([the board](45-board.md)) |
| `POST /api/board/<b-id>/ask`, `GET /api/board/<b-id>/ask/<turn>` | one question for that board's house, and the poll for its answer. The POST is the page's own only (the cookie, below) and hands back a turn id, because a turn is tens of seconds ([the board](45-board.md)) |
| `GET /vendor/elk.bundled.js` | the vendored layout engine the board's diagram uses (`app/vendor/README.md`). The shell does not load it: `app/ui.board.js` adds it the first time a graph is drawn, since as a deferred script it held every cold load's first paint |
| `POST /api/action` | `{"verb": ...}`, answering `{"ok": true, "result"}` or 409 with the refusal, or 403 when it acts as the user without the page's proof (below). A body with a `caller` is refused (`actions.CALLER_GONE`) |
| `GET /api/artifact/<token>` | a file under an artifact root, by a token this server minted |
| `GET /segments/<name>/app/...` | a segment's own app, from `Config.segment_roots` (the repo's `segments/`, which is what `segments_dir` names, [segments](70-segments-and-fetch.md)); path traversal refused |
| `GET /segments/<name>/data/<file>` | one data file that app reads, from the segment's `data/`. A plain name, no dotfile, no `inbox`, `inbox-applied`, `asks` or `taken`, nothing the credential denylist names, and it must resolve inside `data/` |
| `GET /segments/<name>/summary.json` | the segment's own summary, by the same rules |
| `GET /segments/<name>/inbox` | what is waiting in the segment's upload inbox: `{ok, pending: [{name, bytes, uploadedAt}], count}` |
| `POST /segments/<name>/decisions` | one journal drop into the segment's `data/inbox/`, same origin only ([segments](70-segments-and-fetch.md)) |
| `POST /segments/<name>/inbox` | one file (PDF, PNG, JPEG) into the segment's `inbox/`, same origin only |
| anything else under `/segments/` | 404. The whole prefix is the deck's, so an unknown segment path is a refusal and never the lavish proxy's 503 |
| `/voice/...` | proxied to the voice gateway on `voice_port`, with `X-Forwarded-Host` set to the browser's Host; 503 "voice is down" when nothing answers ([the talker and voice](50-talker-and-voice.md)) |
| `/voice/ws` | the websocket upgrade, spliced: a raw socket to the gateway, the request line and headers forwarded, bytes pumped both ways until either side closes |
| anything else | proxied to lavish, streamed |

## Who may act as the user

A POST that runs with `state/human.token` acts as THE USER: the board records it as `human`, and
that is what may approve a gate. A test of only "the body
has no `caller`" is not enough: any process on the machine can send such a body to 127.0.0.1, so a
house with Bash could approve its own gate (c-451). The rule, in `keel/deckauth.py`:

- **The page proves itself.** Each `keel serve` process mints a random key when it starts
  (`deckauth.mint`, never written anywhere) and sets it as a cookie on the page's own GET
  of the shell: `keel_deck_<port>`, HttpOnly, SameSite=Strict, Path=/, and Secure when the
  browser came in over https through `tailscale serve` (`X-Forwarded-Proto: https`). The
  name carries the port because cookies ignore ports, so a worktree's deck on the same host
  cannot overwrite the live one's. A script, a read or any other route never sets it.
- **The human path needs the cookie AND a browser's word that it is this origin**
  (`deckauth.from_the_page`): `Sec-Fetch-Site: same-origin`, or, from a browser too old to
  send that, an `Origin`. `same_origin` lets a request with NEITHER header through (decision
  S5, for the segments' drop box and the rest); on the human path that absence is exactly a
  process that is not the page, so here one of the two is required
  (`deckauth.browser_same_origin`). An `Origin`, when sent, must name the scheme, host AND
  port the browser addressed (`deckauth.exact_origin`): the `Host` it sent, https when
  `tailscale serve` says so in `X-Forwarded-Proto`, else http. Comparing the host alone let
  a page on another port of the same host through.
- **Which bodies are the human path** (`actions.human_path`): every body, since every action
  is the user's. A body with a `caller` is refused (`actions.refuse_caller`, the `CALLER_GONE`
  line): it was a `kb` reaching the deck over HTTP from another machine, which Keel no longer
  does (until c-622). `kb` runs here and writes the board directly.
- **What is refused, and how.** 403 with one line, whatever the body's caller field, and
  nothing runs: `/api/action`, `POST /api/board/<b-id>/inbox`, `POST
  /api/board/<b-id>/ask`, and the `/voice/ws` upgrade (the socket carries the user's microphone and
  the user's turns into Harbor, and a websocket is exempt from the same-origin policy). A refusal from this origin carries `renew: true`; one from another
  origin says what the drop box always said and offers nothing.
- **A restart rotates the key, and the page renews by itself.** Every POST the page makes
  goes through `K.post` (`app/ui.core.js`), with fetch's default credentials (same-origin).
  On a 403 that says `renew`, it fetches the shell once past every cache, which sets the new
  cookie, and sends the same POST again: once, never a loop. So a deck restarted under an
  open phone costs one extra round trip on the next tap, and the phone's standalone app,
  which has no reload button, never needs one. The FIRST deploy of this is the exception:
  a page loaded from the old code has no `K.post`, so the phone reloads the deck once.
- **Who hands the cookie out.** The deck's shell, and a segment app's own HTML (a segment
  app is this repo's code): the voice app at `/segments/voice/app/` is its own PWA on this
  origin, and its websocket needs the cookie. The voice app fetches its own shell before
  every reconnect, so a deck restart costs it one reconnect.
- **The cookie never leaves this process.** The lavish proxy passes only a short
  list of request headers, and the voice tier drops `Cookie` (`voicetier.VOICE_DROP`).
- **A page a house wrote runs in an opaque origin.** Every artifact reply carries
  `X-Content-Type-Options: nosniff`, and an HTML, SVG or XML one (a plan, a rendered
  markdown record) also `Content-Security-Policy: sandbox allow-scripts`
  (`artifacts.served_headers`). With no `allow-same-origin` its scripts still run, but its
  origin is opaque, so nothing it sends is same-origin and the user's cookie never goes with it:
  a `plan.html` cannot approve its own gate when the user opens it. A board file is still always a
  download. The lavish proxy does the same (round 3): every answer under lavish's
  `/artifact/<key>/...` (the plan lavish frames in its own sandbox, and a URL the user can open as
  a whole page), error answers included (`Handler.house_written_headers`). The sandbox
  carries lavish's own frame tokens (`artifacts.SANDBOX`: scripts, forms, popups,
  downloads, never same-origin), so a plan inside lavish behaves as before. Lavish's own
  pages (`/session/<key>`, its scripts, `/events/`) are its code, keep their origin, and
  keep the phone layer. A segment's data files get the same headers.
- **What keeps working unchanged.** `kb` at the desk holding `KEEL_TOKEN`, which is the user by
  the token ([cards and gates](10-cards-and-gates.md)). The segments' drop box, the lavish
  proxy, the voice tier's plain HTTP and the house tier keep their own guards and are not
  asked for the cookie.

**What this does not stop, plainly.** A process running as the same Unix user can GET the
shell itself, read the cookie off the answer, and send the headers a browser would. The
cookie closes the one-line `curl -d` and every page in another tab; it is not a boundary
against a determined same-user shell. Neither is the houses' deny on `state/human.token`
([houses](20-houses.md)): a same-user shell can still read any file the user can. The real
boundary is a separate Unix user for the houses, which is a later card.

## The state document

`keel/deckstate.py` builds one document. The page holds its revision and is TOLD when it
moves (the live channel, below); the five second poll is what runs only while that channel
is shut.

`Deck.rev` is THE ONE FUNCTION that names a revision: the ETag on `/api/state`, the `state`
line every publisher sends, and the event stream's own sweep all call it, so what the stream
names is what the route would answer at that moment. Three parts, and only equality is ever
read off the whole: the writes this process has made; what the board CONTAINS (`board_stamp`,
the newest event id and the newest card `updated_at`), so a `kb` at the desk or a house in
another process is seen too; and a coarse fifteen second clock for the two inputs that are
neither (the drain log and the usage tee).

The middle part is read out of the board with a SELECT and is emphatically NOT a file's
mtime. It was one, and on the running deck that was wrong: the board is in WAL mode, so the
stamp had to include `board.db-wal` to see another process's write, but that file exists
only while somebody has the board open and SQLite checkpoints it away when the last
connection closes. A deck opens and closes a connection on every card read, every action and
every `kb`, so the file came and went all day, the revision alternated between two unrelated
magnitudes with nothing written, the sweep told the page the state had changed on every pass,
and no client ever got a 304 from the tag it had just been handed. A read cannot move what
the board contains. The stamp is memoised for `STAMP_TTL`, which is shorter than the stream's
own sweep, so however many streams are open it is a few index seeks a second between them.

The document:

- `cards`: every card with its `derived` block, `last_event`, `last_said` (the newest Stop
  hook's message), `links` (plan, plan_live, output, context, and the adapter's story, pr
  and design doc), `house` (the agents row joined by session id or name, for a card at
  planning, building, review or shipping, or blocked: `deckstate.HOUSE_STAGES`; review joined
  in c-604, where a listed idle house read `not listed` and lost Open in app, Logs and Stop), `children`,
  `idle`, the drain's own answer for a house that has gone quiet mid-turn (below), and
  `jobs`, the background jobs still running under a house outside its turn (below).
- `needs_you` and `running`: ids, neither carrying a backlog card. `running` is the drain's
  pool (`drain.house_ids`), so a house idling at its plan gate is in `houses` but not running. `backlog`: the
  backlogged ids, for the chip. `houses`: what the Now strip shows, and a tracking card is
  in it only while its own session is busy (below).
- `drain`: host, when, age, the log line, alive. From the last `drain:` line of
  `state/logs/drain.log`.
- `usage`: two windows with used percentage, reset time and the file's age, read from the
  status line's tee'd usage file (`[machine] usage_file`, or `KEEL_USAGE_FILE`; none named,
  it reads unavailable).
- `segments`: each segment's `summary.json`, plus whether it has an app and its URL; a segment with a fetcher and no summary yet is listed as `fetched: false` with `fetch_said` ([segments](70-segments-and-fetch.md), c-742).
- `spaces`: per space the adapter, the repos, the `options` schema, the `verbs` the
  inspector offers, the `topics` for grouping, the `counts` a filter chip shows, and
  `login`, the kept answer of the space's login probe (`{state, why, at, fix,
  never_logged_in}` from
  `state/login.json`, `keel/login.py`; null when this machine never probed it). An `expired` one puts a banner at the top
  of Now and Attention, in the critical colour, one line per such space whatever the space
  switch shows: `The <space> login expired, so its houses cannot run. They resume on their
  own once it works`
  (`The <space> space is not logged in, ...` when `never_logged_in`: the dir never held a
  login, so it is not called expired, c-560; the dir is looked at only for an `expired`
  answer, and an unreadable `.claude.json` keeps the expired words), then **Sign in again**,
  which opens the guided sign-in in place (c-678, `K.signIn`, `app/ui.signin.js`,
  [onboarding](89-onboarding.md), "Sign in to Claude"): the four lines with the space's own
  command (the entry's `signin`) and the live status, which probes that space when a
  sign-in appears (the entry's `stamp`). Until c-678 the line ended with a bare command
  (`loginBanner`, `ui.views.js`; the drain's
  side is [the drain](30-drain.md), "A space whose login expired").
- `untested` (per space, c-678): `{repo key: sentence}` for the repos of a space with no
  pack whose landing would run no tests (`repocommands.untested`). A card of such a repo
  says the sentence at its outcome gate, under "lands untested" (`gateEvidence`,
  `app/ui.cards.js`).
- `flow.adopted` (per space, c-678 review): whether a proposal card of the space's flow is
  done (`flowcards.adopted_in`), which is what lets How work ships call a flow of the
  space's own "Bosun's draft".
- `unlandable` (per space, c-678 review): `{repo key: sentence}` for the repos whose
  CLAUDE.md changed since it was adopted or saved and whose test command would have come
  from that file (the config names none), whose landing will be refused
  (`repocommands.will_refuse`). The gate says it under "will not land", in place of the
  untested line. Both are read on the state build's own board (`deckstate.lands_said`).
- `providers`: per space with an adapter, each extra route's output, read here.
- `console`: Bosun's session, as `console.view` reads it (c-519, [Bosun](96-bosun.md)). The
  header's entry and the Bosun page draw it; it
  also carries `shipped` (`deployask.shipped`: the open deploy ask, the last deploy's result,
  what went live lately), which the page's Shipped section reads (c-591), branch names
  included: each is the ask's own `target` and `trunk`, never a name the page spells
  (c-665, [flows](64-flows.md)). Its board half
  (requests, asks, journal, throughput, gaps, shipped, the counts) is
  `deckstate.bosun_board`; with no console session `console` is null and that half comes
  alone as `bosun`, so Shipped, the asks and the Journal never need a console session
  (c-591 review).
  `needs_you` leaves out every card of a space no longer configured (the retired console
  space's old cards, c-593), since Harbor reads that list out loud.
- `waiting`: `{card id: line}` for every card this machine cannot start
  (`where.waiting`, [the drain](30-drain.md) "Where a card starts"). It reads "Cannot start
  this: ..." with the reason ("personal needs keel, and this install does not have it", a
  repo missing from disk). The row's house word says "cannot start", and the inspector's
  facts carry the whole line.

## The routes

Desk rail, in order: Start (until Finish, c-632), Now, Attention, Cards, **Board**, Segments,
Atlas, Setup, Settings, Reviews, on every space (c-631: no view is hidden for what is not set up; it says so on its
page). The one exception is Reviews (c-730, `rail: when-declared` in `app/views.json`): it is
listed, on the rail, under More and as Now's glance row, only while some space can file review
cards at all, every capability it needs `declared` on that space's readiness rows
(`K.declaredSomewhere`: a pack that has them and a space that has not turned review scanning
off; a row held up only by a failing check counts), and while its page is the one open. A
fresh install with nothing that could fill it does not show it. Phone dock: Now, Attention, Cards, Segments, More, with Segments only once a segment is
installed (`K.dockKeys`; `K.DOCK` stays the five). Under More: the Board first, then each view
that declares needs and is not in the dock (Reviews while some space can file review cards, Segments until one is installed),
with a `not set up` badge while its needs are unmet, then Start (always), Setup, Settings (c-633), the Atlas
and the drain line. Every route is `?view=<name>` but the Board, which is `/board/<b-id>` so a board
is a link ([the board](45-board.md)); every other route therefore writes an ABSOLUTE
`/?view=...`, or a move off a board would keep the board's path in front of it, and every
asset in `app/index.html` is referenced absolutely for the same reason. A route carries `&step=<id>` for the stepper's screen, `&card=<id>` for a selected card,
`&key=<row key>` for a selected provider row and `&page=<slug>`
for an Atlas page. `?space=` and `?d=` pin the palette and the density for a screenshot
run (the density is ONLY that pin: nothing on the deck sets another, so nothing stores one);
selecting a row keeps every one of them, so a pinned screenshot stays pinned with the pane
open. A route with a find bar also carries its state (`q`, `f`, `inc`, `sort`, `layout`,
`group`; "The find bar", below).

| Route | What it shows |
|---|---|
| **Now** | The stat tiles (usage, attention, houses running), then one tile per live or blocked house with what it last said (a blocked tile says `blocked` once: in its house word, or in its head when a relay in flight takes the house word; its head is how long it has been blocked, `derived.gate_since` as Attention dates it; its reason and the house's last words are two labelled lines, `why:` and `last said:`, the second left to the live strip only when the strip's own second line is those words, c-606), Logs, Stop, Resume house, Retry and End discussion, then the services block (talker, voice, drain, backup, each with its state and age, below) and At a glance |
| **Attention** | Only what waits on a tap: open gates, blocked cards and open segment notices (Q8). Never a backlog card. A notice's row wears a `notice` chip and says its brief's first line, and its one answer is Dismiss, which archives it (the segment files it again while the condition holds). A row's age is `derived.gate_since`, how long the wait has been OPEN (the event that opened it), never `updated_at`, which a note moves |
| **Cards** | The whole board as a table with a detail pane, or the seven-lane kanban (`shipping` sits between review and done, lane SHIP), its title taking what the fixed columns leave (so under 1400px wide, or beside the pane, the table gives up Topic and Last event, which the pane shows; `columns` in `app/ui.cards.js`, c-553), found through the find bar (below): search with typed filters, the Filter panel (Stage, Needs, Repo, Topic, Kind, Include done, backlog and archived), Sort, and View (Table or Kanban, Group by none, stage, topic, parent or repo). On the phone one list, grouped by stage with a count on each heading by default, so the inbox, where triage starts (F3), is the first heading; no kanban there. A REVIEW CARD (`options.review_key`) is never on Cards, in any layout, count or facet (2026-09-24; `spaceCards` in `app/ui.cards.js`, and the space's card and backlog counts in `deckstate.space_counts`): Reviews is its one list, Attention carries one only at the user's gate, a running review house is on Now like any house, and a link to one (a Now tile, Attention's Open the card, a card id in a plan) opens it on Reviews (`K.cardRoute`). `kb list` and the board are unchanged |
| **Board** | The blackboard: ONE model per board (a diagram with attachments hanging off it) seen three ways, diagram, outline or walk, plus the saved boards in two sections by level. Its own path rather than a `?view=`, with `?view=` meaning which of the three; [the board](45-board.md) has all of it |
| **Segments** | One card per segment with its summary, and a link into its own app |
| **Atlas** | This documentation: the page list, and the selected page rendered |
| **Start** | The first-run stepper (c-632, `app/ui.start.js`, [onboarding](89-onboarding.md), "The first run"): one step per screen, in the approved order (c-677), with Back, Skip, Next and Finish, the steps listed on the left on the desk with each one's state, and on the phone a strip with the counter and the list under Steps. From Meet Bosun on it is headed by the line to Bosun's session, and a requirement that needs you is the stuck line (`app/ui.stuck.js`). A deck loaded with no `?view=` opens here until Finish, and again whenever a required step stops being met |
| **Setup** | This install's spaces: each space's tier, its repos (Remove, which leaves the folder; for a cloned repo its tier, Propose from the repo and Adopt), a Clone form of key and URL and an Attach form of key and path; and its packs with their tool checks (one that fails is the stuck line, c-677, with the fix its pack wrote, c-688), Turn on and Turn off (`app/ui.setup.js`, [onboarding](89-onboarding.md)). The stepper draws its screens from the same parts (`K.setupParts`) |
| **Settings** | How Keel behaves, drawn from the settings schema (`app/ui.settings.js`, `keel/settings.py`, c-633): the panel of the space the deck is in and its flow first, then the install's groups (Drain, New cards, Review, Tests and shipping, Conversations, Features, Builder), then every other space, then Voice, with one Save. Every field shows its help under its label (c-640). Reset takes the key out of the file so its default applies; a value the Reviews gear set says so. Save sends one `setup.settings.save`, which the deck reads in place (`keel/deckreload.py`, c-729; a voice change still re-execs it, and the page then asks again until the new process answers). A config that is not an install's is shown read-only. Now shows the loader's warnings in a panel with Open Settings. Which space a row is for, and what is not saved yet, are said on the page itself: see "Settings: which space, and what is unsaved" below |
| **Reviews** | The REVIEW CARDS (lane RC), and nothing else, found through the find bar (newest raised first by default), as a list or, on the desk, a kanban by review state; a tap opens the card's own pane. The fetcher's two settings behind a gear at the title. See "The Reviews list" below |

Every list honours the space switch. Every route exists in every space.

**The spaces are the config's** (c-629). The switch lists the spaces `/api/state` carries, in
the config's order (`K.spaceNames`), and the header shows the current one's name. A stored or
asked space the config does not have becomes its first once the state arrives
(`settleSpace`), so a fresh install, which has only `personal`, never opens on a `work` it
does not have. With one space there is no switch at all. A space named `work` wears the work
palette and every other the personal one (`K.palette`); the plan page wears its card's the
same way. `tests/test_spaces_deck.py` runs these functions under node.

**What is set up.** The state's `readiness` says, per space and for the install, what is
ready, why not, and which first-run step fixes it (`keel/readiness.py`, [packs](62-packs.md),
"Readiness"). The first-run stepper reads it too (below).

**Pages that say what they need** (c-631). A `VIEWS` entry may name the readiness rows it
needs (`needs`): Cards `repos`, Reviews `codehost` and `reviews`, Segments `segments` (with
`dock: 'when-ready'`). That list is the deck's only gating, and it never hides a view.
`renderBody` (`app/ui.js`) opens the page with `K.needs(view.needs)` when no card is open, so
each page gets its panel from its entry and nowhere else. The component, in `app/ui.core.js`:

- `K.readyRow(cap, space)`: the space's row, else the install's; a state with no `readiness`
  (an older server) reads as ready, so nothing flashes. `K.unmet(caps, space)` is the rows
  that are not ready.
- `K.needs(caps, space, opts)`: null when everything is ready, else one `.waiting.needs`
  panel (`role="status"`, the accent ink, since nothing is broken) with each `why` once, what
  each missing capability unlocks (`UNLOCKS`, through `K.say`, so the space's words read), and
  Set it up to the first row's step. A row with no step (segments) gets no button. `opts.line`
  is the one-line form a form field or a card pane carries; `opts.title` heads the panel.
- `K.stepHref(step, space)`: the one place a step becomes a URL,
  `?view=start&step=<id>&space=<space>` (c-632). Set it up's tap goes through
  `K.openStep(step, space)`, so the page moves without a reload; the href is for a new tab.

**The first-run stepper** (c-632, `app/ui.start.js`, [onboarding](89-onboarding.md), "The
first run"). The `start` route draws one step per screen from the state's `firstrun` and the
Setup report's `start`. A screen may be its own file, loaded before `ui.start.js` and read
by it: `app/ui.startchecks.js` is Check this computer (`K.checkScreen`), and
`app/ui.signin.js` the guided sign-in (`K.signIn`), which the banner and the Logins list
draw too. `readRoute` reads `?step=`, and `K.go` carries it (and the space) in
the address for `start` only. `VIEWS` lists Start with `rail: 'until-finished'`, so the
desk's rail drops it after Finish (`visibleViews`), and More lists it always. A deck loaded
with no `?view=` (and no card or board in the address) opens Start while `firstrun.redirect`
is true: `show` calls `K.stateLanded` once the first state lands, and it replaces the history
entry. `tests/test_start_deck.py` runs it under node.

Where they show: Reviews draws no "nothing to review" line under its panel; Cards says `no
card in this space yet` for an empty space (the space's card count) and `no card matches` only
when a filter hid them; Segments' panel replaces `no segment has a summary`; Now opens with a
`Not set up` panel for the install's `prerequisites`, `voice` and `builder`, and its glance row
for Reviews shows while some space can file review cards (`not set up` while unmet). The New card form draws the repos line in
place of an empty repo chip row and the tracker line under the ticket field, and both stay
usable (a card with no repo is a real errand). The card pane draws the tracker line where Open
story would be, for a card with a ticket ref and no tracker (`need-tracker`), and the shipping
pane the code host line above Ship (`need-codehost`): Ship stays, and the backend refuses with
the same sentence ([packs](62-packs.md), "Readiness"). Both are facts about the card, not
actions: they lead the pane's row, each on a line of its own, on the desk (`STATUS`,
`app/ui.tips.js`, whose order is the row's) and on the phone (`PHONE_NEEDS`, `app/ui.cards.js`, where a line takes
none of the three places). Until c-662 they were in no group and in neither list, so the
pane put them and no row drew them, on either surface. Where the tracker and the code host
are missing for one reason (a space with no pack), the shipping row says it once, on the
code host's line; a blocked card, which draws no code host line, keeps the tracker's.
`tests/test_needs_deck.py` holds the source rules and runs
`tests/fixtures/needs-deck.js` under node, which reads both lines off the row itself.

**Each space's words** (c-630). Every noun for a ticket or a change is the card's space's:
`K.term(space, key)` reads `App.data.spaces[space].terms` (the space entry's, from
`keel/terms.py`, [packs](62-packs.md) "Terms"), or on the plan page `K.cardTerms`, which the
payload's `card.terms` fills. `K.say(space, template)` fills `{key}`, and `{Key}`
capitalises. A site passes its card's space (`c.space`), so "Open {ticket}" reads Open story
on a work card and Open ticket on a personal one; a tip (`K.tip`) is filled for its card's
space, or the deck's. The deck keeps no copy of the defaults: a space with no terms shows the
key itself, so a miss shows rather than guesses. `tests/test_terms_deck.py` runs these and
`shipWord` under node for three spaces, and `make drift`'s noun guard fails on a noun spelled
in a deck string.

## A shipping card on the deck (lane SHIP)

A work card whose pull request is ready sits in the Shipping lane until it merges, and its
build house lives on ([cards and gates](10-cards-and-gates.md), "Shipping", c-600). Its
outcome word is a chip of what the watcher last saw (`shipWord` in `app/ui.cards.js`, from
`options.shipping`, in the space's words): `PR ready · 0 comments` (`PR draft` or `PR declined` first when true),
then `N waiting` while a batch gathers, `N open` for told items the user's Ship has not answered,
`N commits to ship` (the drain's `local.ahead`), `branch diverged` or `branch behind` (the
worktree against its pull request's branch, c-653), `checks failed` and `N behind`; it reads
warn while something waits, is open, the branch is out of step, or a check failed.

**The standing batch** (`keel/shipreplies.py`; the pane reads it from `/api/card/<id>`'s
`shipping`, which `deckstate.shipping_rows` derives). Since c-643 the pane says it in one
line, "4 review items: 3 judged, 2 replies to post" (`K.shipping.countLine`), with **Open
comments** (`open-comments`, among the card's Pages), and the rows are drawn on the card's [review comments
page](67-comments.md), grouped by round, newest first, by the same `K.shipping.row`. Each row shows the handle, the verdict chip
(Valid, Not valid, Valid deferred, Prepared waits on you, or "judging" until the house records one), who said it
and where, the comment's text, the one-line summary, the reasoning ("Why:"), each commit's
diff (folded) and the reply's words, and for a row with a reply the user's Post, Edit and Drop
(`kb mark`, `doc: shipping`): Edit opens a field with the words, and Keep these words
stores the user's. A posted row says posted. Items still waiting say when they go ("after 5 quiet
minutes, 30 at most"); a declined pull request says nothing ships.

**Send back at shipping** (`ship.sendback` `{id, words}`, c-663; the `ship-sendback` button
on the shipping card's row and on the comments page) is `kb ship <id> sendback` run as the user
with the user's words on stdin (`actions.act_send_back`), like every tap of the user's. It opens the
same kind of box the outcome gate's Send back does, a sheet (`K.shipSendbackSheet`, in
`app/ui.shipsendback.js`, a module of its own that the deck and the comments page both
load after `ui.shipping.js`; not in the Cards module, which the comments page does not
load). The button is drawn only where a tell can follow (`K.shipping.sendBackOffered`: at
shipping, not blocked, not declined, not archived). In the box the user's words are required, the draft is kept per card until a send the server accepted,
and the help under the field says what will happen: the house is told this as its next
item, the card stays at shipping, nothing is posted, and any commits go out with the user's next
Ship. What the user sent waits on the card in the user's words, marked "yours" and "waiting"
(`K.shipping.sentBackLines`, from `derived.ship_sendback`), until the house is told. One
the drain is not telling now is marked "held" and says why in the backend's own sentence
(its `held`: declined, archived, blocked, the house stopped by the user, the drain paused, or
a batch the user re-offered still open), never that it is on its way. Then
it is a row of the standing batch marked "yours" (`row.his`): the house's verdict, its
reasoning, its commits and "The house's answer to you", with no Post, Edit or Drop, beside
the reviewers' rows; while the house has recorded no verdict on it the row says so in
words ("told, not judged yet"), which is all an unjudged send-back does: no block, no
stop. The count line says the user's beside the review ("3 review items: 3
judged; 1 send-back of yours: 1 answered"), the card's count of replies to post leaves
the user's out (`openTold`), and one left unjudged is in the hand-over's label ("Hand your
send-back to the house").

**The hand-over** (`ship.handover` `{id, rebase?}`, c-655; the Continue group's `hand-over`
and `hand-base`) is `kb ship <id> reoffer [--rebase]` run as the user (`actions.act_hand_over`),
like every tap of the user's: the page's proof, the user's token, and a body with a caller refused. The
label says what it hands, from `derived.ship_handover` ("Hand 3 comments to the house",
"Hand 3 comments and the failing check to the house", never the verb's name), and it is
drawn only with something to hand; the base is its second entry, drawn only while the
branch is behind its base or conflicts with it. Neither is drawn on a blocked or declined
card, or while a hand-over already waits for the drain (the pane says "Handed over"). The
verb's refusals come back as plain words (`shipauto.plain`): nothing to hand over, already
handed over, the house is still on its batch.

**The list says it too** (c-655 review): a card's shipping chip (`shipWord` in
`app/ui.cards.js`) adds "N not handed over", in the warning colour, beside "N waiting" (the
batch, which goes by itself) and "N open" (told, not shipped). N is the number the card's
hand-over button would give the house (`derived.ship_handover`: its comments plus its
checks, so comments from before the card shipped count too), and it is gone once the user has
asked. The spoken digest says the same (`deckdigest.pr_words`). Such a card is NOT under needs-you:
the count is on its chip and its pages.

**Ship** (`ship`, the Decide group, the phone's first action) is `kb ship`: push the
house's commits, mark a draft ready, post the kept replies once ([cards and
gates](10-cards-and-gates.md), "Review at shipping"). One label for several actions reads
as nothing, and a Ship offered on a card where it can only fail is worse, so
(c-653; `K.shipping.shipState`, `shipLabel`, `app/ui.shipping.js`):

- **The button names what it sends**, from what is waiting, in the space's words: "Push 2
  commits and post 3 replies", "Post 1 reply", "Push 2 commits", "Mark the pull request
  ready for review". It is still ONE tap that sends everything the user accepted, the push first
  (a reply naming a commit never goes out before the push), and its confirm keeps the
  detail and the warnings (commits no review stamp covers, a conflict with the base, a
  branch behind its base, items still being judged). Until the pane's rows have loaded the
  replies are "the replies you kept", never a guessed number, and a card with nothing else
  waiting draws nothing until they have.
- **It is drawn only where the send can succeed.** Otherwise one line says why where the
  button would be (`ship-why`, a fact about the card, drawn before the groups and the full
  width of the row): the branch has diverged from its pull request's branch, in the
  backend's own sentence drawn as given (`options.shipping.local.said`, the same string as
  the card's note and the terminal's refusal), and under it the command that brings each
  worktree in line by hand (`local.by_hand`, `keel/shipstep.py`: one `&&` chain a worktree,
  a line each, the very text the terminal's refusal carries; a long chain wraps in the
  block and copies whole), in the deck's copy
  block (`.lfix`, a code block and `K.copyButton`, as a login's fix is drawn; `ship-by-hand`
  inside the line). There is no button that moves the branch: Keel moves none. When Keel
  cannot give commands the sentence says why and no block is drawn. A
  branch only BEHIND that branch is no refusal: Ship still sends what needs no push, with
  the sentence and its commands beside it. So is a stacked card whose parent was
  squash-merged (c-718, `local.restack`): the sentence and the commands that replay its own
  commits onto the base, drawn the same way, Ship still offered. The house is still in
  its turn on a batch, with **Ship anyway** reachable from the line (the backend's hold,
  the user's explicit yes); items were told and none is judged yet with nothing else to send; or
  nothing is waiting at all. A conflict with the base that the send will not cure is a
  line beside the button, never a refusal.
- **The backend stays the judge** (c-631): `keel/shipcheck.py` refuses and holds with the
  same reasons, so the terminal's `kb ship` says them too; the deck only stops offering a
  tap it knows will be refused.
- **A Ship that went is said, never offered again** (c-660). While the tap is in flight the
  button is the pending one every action button is (`K.actionBtn`: disabled, "Shipping…",
  and every other button on that card with it, Ship anyway included). The answer arrives
  before the state that holds it, and the page then drew the old label from what it still
  held ("Push 23 commits", the user's second tap refused). So the Ship's own line, the card's
  record of it ("shipped: pushed cloud f8e7cb9c34, posted 0 replies"), is drawn where the
  button was (`sentLine`, as the `ship-why` line) until what the page holds is that Ship's
  or newer: the card's `options.shipping.shipped_at` AND the standing batch's
  (`summary.shipped_at`, `shipreplies.summary`), since the pane reads the two apart. Then
  the state says what waits, which the record the user's Ship wrote already has right ([cards and
  gates](10-cards-and-gates.md), "Review at shipping"). The line never outlives what it
  describes: its entry is dropped once the page holds that Ship's state, after thirty
  seconds whatever the page holds (`SENT_MS`, as the bridge word ends), and when the card's
  record is no longer the one the Ship answered on (`since` or `round` moved: a record
  begun afresh by the shipping sync carries no `shipped_at`). The hand-over needs none of this:
  its ask is on the card in the verb's own write (`options.reoffer`, drawn as `asked`).

The comments page draws the same line and button (`K.shipping.bar`). On the phone Ship takes
the row's full width, since its name is now a sentence, and the line takes none of the three
action places.

**The way into the house** is on the row itself, as at every other stage (c-653; the user could
not find it: Open in Claude app and Drop in were only inside the Talk sheet). `waysIn`
(`app/ui.shipping.js`) draws Open in Claude app for a listed house whose link the card
holds, and for a house in its turn with no link on record (the tap then reads the link from
its log without waking or stopping anything, `house.open_app`); Resume and open in app for
an exited house or an idle listed one with no link; Drop in; and the pill while the user is in it
at a terminal. A blocked shipping card draws them too. **Talk** (the Talk group) stays where the health read says voice is
installed: one sheet with every way in (`K.talkSheet`), Talk by voice among them. A card
missing its link is fixed at its cause ([houses](20-houses.md), "Resume and block").

## Controls by phase (c-600: the shipping phase and the outcome pages)

Every control drawn must have a reason to be there. The shipping phase draws its own set
(`K.shipping.gateItems` and `cardItems`), not the general inspector's: Resume house, Retry
and Split have no reason there, and Retry is dangerous (it restarts a shipped card from
scratch). The ways into the house are on the row (`waysIn`): Open in Claude app, or Resume
and open in app for an idle house, Drop in (c-653: with both only inside the Talk sheet
the user cannot find the way into a running house), and Talk, the sheet, where voice is
installed. Other phases are c-601's.

| Phase | Control | Why it is there |
|---|---|---|
| shipping | Ship, named for what it sends (a held answer asks "Ship anyway?", `K.shipping.shipDone`); or the line saying why there is none, with Ship anyway, or the commands that bring a branch left behind in line by hand, where they apply (c-653) | the user's one act: push, ready, post the kept replies, once; held while the house works or no receipt covers the commits, and only the user's second yes sends it as it is |
| shipping | Hand N comments (and the failing check) to the house (`hand-over`), only with something to hand | the user's way to give the house the review that waits: everything, while automatic handling is off (the default, c-655); the backlog, while it is on |
| shipping | Bring the branch up to its base (`hand-base`), only while the branch is behind or conflicts | the same hand-over with the base merged in; its confirm says what else it hands |
| shipping | Send back (`ship-sendback`), on the row and on the comments page | the user's own notes for the house (c-663): a shipping card only goes on to done, so what the user wants changed is told to its house as its next item; the card stays, nothing is posted |
| shipping | The house's question on a prepared fix, with Answer (`ship-prepared`), on the row and on its comments page row | a `prepared` verdict waits on the user's yes (r-55, c-723): the card is in needs you until the user answers, and Answer is Send back with the item's handle leading the words |
| shipping | Turn on / Turn off / Use the space's setting, one row per kind, in the pane's review replies | whether a new comment, and a failing check, goes to the house by itself on this card; said in words either way |
| shipping | Post / Edit / Drop on a row | what each reply says, or that it is not sent |
| shipping | Open in Claude app, Resume and open in app, Drop in (on the row, c-653); Talk, the sheet, where voice is installed | reach the house to discuss a verdict or ask for a change |
| shipping | Open output | read the pull request on the code host |
| shipping | Open story | read the tracker story |
| shipping | View context | read the outcome record the build left |
| shipping | Stop session (only while the house works) | end a batch the user does not want answered |
| shipping | Archive | put away a card the user is done with (a declined pull request) |
| shipping, blocked | Unblock only | the block is Keel's mechanics or the user's; unblocking lets the watcher tell the house again |
| shipping, blocked | Open in Claude app, Resume and open in app, Drop in; Talk where voice is installed | reach the house about the block |
| done after a merge | Logs, Stop session (while the harness lists the house) | the merge made the card done; the drain ends its house once the harness lists it idle (a-72, `keel/shipidle.py`), so while it still works the user's Stop is where it ends (`deckstate.live_house`) |
| outcome page | Approve outcome (confirms, as the pane does) | publish the outcome and move to shipping or done |
| outcome page | Send back with notes (confirms; absent without a note or a changed answer) | send the user's reasons, never an empty send back |
| outcome page | Ask now | a question answered without leaving the gate (the Stop no longer bounces it) |
| outcome page | Note on the whole outcome, a note on a block | the words a send back carries |

## Words and forms the sandbox run corrected (c-604)

An end-to-end run on the sandbox found places where the deck said what was not
so. Each now says what is:

- **The create form's repo chips** (`defaultOf` in `app/ui.modal.js`): no chip is on until the user
  taps one, unless the field has exactly one repo and the sheet's default names it. The
  sandbox's sheet defaulted to `api` of two and filed cards there unasked.
- **Closing the form** blurs a focused field first (`closeModal`): removing it focused fired
  its blur inside the removal, the blur redrew the dialog, and the redraw removed the same
  node again (the console's `removeChild` error on every Create).
- **Counts** are singular at one (`1 note`, `1 decision`), and a done card's line says
  `approved` once: the plan's word is dropped when the outcome's is the same.
- **A held Ship** (`shipcheck.working`) says `c-9's house is working (turn 4m)`, the turn's
  age from the transcript as the live strip reads it, not the harness row's uuid and pid.
- **The page hint** past the gate (shipping, done) offers a note only: there is no Ask there
  and no Send.
- **A done card's refusal** (`house.worktree_state`) says whether its worktree is kept (and
  where), gone, or never cut.
- **A held gate answer's receipt** (`receipt.resumed`) says `held until the house's turn
  ends, then building` while its `resume` relay waits on the board, not `house resumed`.

## What the third sandbox run corrected (c-605)

A later end-to-end run on the sandbox found the deck saying what was not so,
or not drawing what was needed:

- **A gate answer in flight** (`receiptNow` in `app/ui.plan.js`): the gate's move lands
  before the server finds the house working and holds the user's answer, so a plan page that
  loaded in between read `house resumed` for about a second before `held until the house's
  turn ends`. Until the user's send has answered and a load STARTED after it has landed
  (`S.settling`), a receipt saying `house resumed` reads `sending your answer to the
  house…`; a load asked for while one is in flight runs again once it lands (`S.again`),
  so the one after the user's send is never swallowed. The "Cannot set properties of null" the run
  logged came from its own script, which removed every `.toast` before tapping: the toast
  (`toastNode`, `app/ui.core.js`) is now made again when it is missing rather than throwing
  inside the answer's promise.
- **A plan with no decision** says `Approve`, not `Approve with these answers`, and its line
  says there is nothing to decide.
- **The live strip's ages tick** (`tickLive`, `app/ui.live.js`): once a second each strip on
  the page is drawn again from the card it was last drawn for and morphed into place, so
  `turn ended 0s ago` does not stand for sixteen seconds between readings. It is the same
  reading on the clock (`ageOf` adds how long the page has held it); nothing is fetched.
- **A merged card keeps Stop at once** (`stripHouse`): the strip follows a house only at
  planning, building, review and shipping, so the moment a card is done the stream says
  `live <id> null`, which had hidden the document's own house row, and with it Stop, until
  the next state. At any other stage a null is "nothing live to say", and the row stands.
- **A blocked shipping card whose house is listed idle has a Now tile**
  (`deckstate.blocked_shipping`): an idle shipping house is otherwise left off Now, which
  left the tile's one control for it, Unblock only, nowhere on Now. Not a tracking parent,
  whose slices' tile already carries it (one tile per key). Where Open outcome leads, it is
  the pane's one primary, Send back included.
- **Open outcome** leads the review pane where the outcome has its own page (the table
  below). Ship's toast names only a repo whose head moved ([cards and
  gates](10-cards-and-gates.md), "Review at shipping"), and Logs keep the log's carriage
  returns (the Logs paragraph below).

## A tracking card reads as a tracking card

A card that has been cut into slices has no work, no gate and no house of its own: its
stage is its children's ([cards and gates](10-cards-and-gates.md)). A deck that draws
that borrowed stage as if the card itself were at it reads `building` with a house
tile beside it while the card's own session sits idle (c-277). Everywhere the deck says where
a card is, a tracking card says what it is instead:

- **The word** (`trackWord` in `app/ui.cards.js`), which replaces the three words on the
  row, the kanban tile, the phone list, the Now tile and the pane: `tracking · 1 of 8
  building, 7 waiting`. The counts are `derived.tracking_tally`, the board's own sentence
  (`keel/views.py`), so the deck and `kb list` cannot say it differently. It is the one
  `.sw` word allowed to wrap, because it is a sentence of counts rather than two words.
- **The stage chip** in the pane's facts grid says `tracking` in the quiet chip face,
  rather than `building` in the warn face a working house wears.
- **No house indicator** unless its own session is genuinely `busy`: `deckstate.houses_of`
  leaves an idle tracking card out of the Now strip, and `running` already leaves it out
  because it holds no pool slot ([the drain](30-drain.md)). When its SLICES are running,
  Now still draws the parent's tile with those slices gathered under it.

`kb list` and `kb show` follow the same rule: the row says `tracking` where a stage would
go and carries `[tracking: 1 of 8 building, 7 waiting]`, and `kb show` prints the card's own
stored stage under the line so nothing is hidden.

**When every slice is done it is at the outcome gate like any card** (lane X, [cards and
gates](10-cards-and-gates.md)): it is under needs you, with Approve outcome and Send back.
What they do is different, and the deck says so. Approve outcome's line (`app/ui.tips.js`)
reads "Closes the story: every slice is done and already landed. Nothing is merged or
published.", and its confirm says `Close c-277? ... Nothing is published.` rather than
"This publishes it". Send back's line says the card goes back to tracking with the user's reason
as a note and no house is resumed. The gate's evidence is the slices (`slices`: the tally
and one sentence) rather than an output and a PR body it does not have, and the tree above
it lists every slice.

## The card tree on the deck

`app/ui.tree.js` draws the tree and works nothing out: the outline is the card's
`derived.tree` and the order is the state document's `queue`, both from `keel/tree.py`
([cards and gates](10-cards-and-gates.md), "The card tree"), so the deck, `kb tree`, `kb
queue`, the voice and the drain cannot disagree about a tree or an order.

- **The tree first.** A big card's pane opens on its outline, under the head and ABOVE
  every button, so on the phone the tree is the first screen. A flat slice
  list below six buttons, the plan and the brief hides it (c-277, c-302).
  Slices stand in STEPS, not indented under one sibling
  (a slice that waits on two has no single parent row to sit under). Each row: id, title,
  the card's own words (or `not assigned` for an inbox slice), a `next` pill when it could
  start now, `waits for ...`, and `unblocks N`. Done slices fold into one line per step that
  the user can open (kept across the poll like a clipped brief); review stays shown, it is a gate.
  Follow-ups are listed apart, under their own label, never as slices. A node-and-line
  graph was ruled out: it does not read at 390px.
- **A slice knows its place.** A slice's pane shows `In its tree`: its step of how many,
  each card it waits for with that card's own words, and what it unblocks.
- **Assign tree.** A big card with inbox slices has `Assign tree (N)` in the tree's head on
  the desk; on the phone it is the first of the pane's three actions instead (the tree is
  the content above them, and a button in its head would be a fourth primary), with Move
  to front and Back in filing order under More actions.
  It asks the board for a dry run (`assign --dry-run`) and opens a sheet with the counts
  (start now, wait and on what, stop at a plan gate first) before the user confirms with
  `Assign N`, which sends the ids the sheet showed (`assign --ids`): if the set changed in
  between, the board refuses with one line and nothing is assigned. Slices filed later are
  not included.
- **Assigned is the queue.** With the assigned lane (phone) or chip (desk) on, the list is
  in the drain's order and each row carries its number; a startable one says `next`. An
  assigned card, or a big card, has `Move to front of queue` (a slice: `Move to front of
  tree`), and a moved card has `Back in filing order`. Both are `next`, the board's verb.
- **Group by parent** lists a big card's slices in its tree's order (by step), not filing
  order.

## A house that went quiet does not read as working

A house the account's rate limit cut off mid-turn is still at `building` and still listed,
so a deck could draw it exactly like a working house,
while nothing at all is happening ([the drain](30-drain.md)). The house
word says how long it has been quiet and when the drain will put it back: `idle 22m ·
resume in 7m`, and `idle 1h · blocking in 40m` once the attempts have run out. The Now
tile's age says `idle 22m` too, measured from the moment it went quiet rather than from the
start of its session, which used to read `idle 3h` about a house that had worked for most
of those three hours.

The answer is the drain's (`drain.idle_stuck` through `deckstate.idle_of`), not the deck's
own reading of the agents row, for the same reason `running` is: two places deciding whether
a house is working is how they come to disagree. A busy row, a card at a gate and a blocked
card all carry no `idle` block, so they read as they always did.

**Idle, with a job running.** A house the harness lists outside a turn while a background job
of its own is still going is waiting on that job, not on nothing: c-526 idled thirty
minutes behind a wait loop that could never end, and the word said only `idle`. The card's
`jobs` (`deckstate.jobs_of`, read from the harness's job record by `keel/housejobs.py`) is
each such job's `id`, `label` and `started_at`, and the house word says `idle · job
running`, ahead of `working`: the harness lists such a session `busy`. Empty for a house in a turn.

## The live strip (c-599)

The user asked to see what a house is actually doing while a question is in flight, a plan or an
outcome is being rewritten, or it builds. Each live card carries one line of facts, each
with its age, on its Now tile, at the top of its pane, and in the plan and outcome page's
header:

```
working  in turn 4m  Bash: run the unit tests · running 12s  todos 2/4: Writing tests  1 job   read 2s ago
running the unit tests for the parser
```

The status is the listing's (`working` by `housejobs.working`, `idle`, `exited` when its
session is not listed) or `waiting on a prompt`; then how long the turn has run (or when it
ended; an exited session whose transcript never closed its turn shows neither, since it is in no turn, c-606), the last tool with what it was doing and whether its result is in, the todo list's
progress and the task in hand, subagents and background jobs, a tap still in flight (a
pending relay), and how long ago it was read. The second line is the prompt the user is
being asked, else the harness's own line of what the session is doing (the job record's
`detail`), else, its turn over, what Stop last said. **Facts with ages, never a verdict**: a
tool running nine minutes says `running 9m`, and nothing says stuck, hung or wedged
(principle 1).

**Where the facts come from.** This machine reads them from the harness
alone (`keel/livetail.py`): the agents row, the job record
(`<config dir>/jobs/<short id>/state.json`, whose `detail`, `updatedAt`, `inFlight`, `fan`
and `linkScanPath` were probed on 2.1.285), and the LAST 256 KB of the transcript that record
names (else `projects/<cwd with every non-alphanumeric a dash>/<uuid>.jsonl`), parsed again
only when its size or mtime moved. `tests/fixtures/harness/live-tail.jsonl` is real lines of
one turn. `TodoWrite` rewrites the whole todo list; `TaskCreate` and `TaskUpdate` edit it one
task at a time.

**How they travel, and what it costs** (`keel/livestrip.py`). Nothing is read for a live
strip while nobody watches, and nothing is ever written to the board.

- Opening `/api/events` starts the `Watcher` thread (`Deck.watcher`); the last stream
  closing ends it, and so does the server closing (`Watcher.close`, which waits for a read
  in flight, so no `claude agents` outlives the deck). While it runs it reads the houses
  every 3 s, from the listing the deck's builds share (`Deck.listing`).
- The deck holds the newest facts per card in memory (`livestrip.Strip`, on `Deck.strip`) and
  says `live <c-id> <json>` on the event stream for each that moved (a read whose only change
  is its read time says nothing, except once every 30 s, so a page's "read 2s ago" stays true
  of a house doing nothing new). It is the facts themselves: the page patches the card and
  fetches nothing, and the state's revision does not move. The watcher's very first read of
  the deck's own houses is held and not said, since the page's document already carries it.
- The houses are also read when the state document is built, from the listing that build
  already makes. A page with no stream open sees them on its next load.

**What the strip may carry** (c-599 review). Every text is redacted where it is read
(`livetail.safe`: `permpause.redact`'s rules, then any token-shaped literal): a tool call is
its name and a short line from the one field that says what it does (a Bash call's
`description` before its `command`), never another field, and an MCP tool is its name
alone, since its input is another server's body. Todo text, the job record's `detail`, a
subagent's or job's label and a Notification's message go through the same. A tail whose
one newest record is bigger than 256 KB keeps the facts it had.

**The turn clock is the user's turn (c-604).** Only a genuine prompt starts it (`livetail.genuine`:
`origin.kind` `human`, or no origin and neither `isMeta` nor an injection). A
`<task-notification>`, a subagent's hand-back (`origin.kind: peer`), a Stop hook's feedback, a
command's output and a tool's result do not: a notification used to restart the clock, so an
idle house read `in turn 8m`; `[Request interrupted by user]` and a compaction summary start
none either. The turn ends at `turn_duration`, at the assistant's final message (`stop_reason:
end_turn`, no tool in hand) or at an API error record. A notification or hand-back that WAKES
an ended turn (the house answers it) starts a new turn clocked from that record, so a working
house never reads `turn ended` and an idle one never reads an old start.

**The strip and the card.** A notice the house's transcript has moved past
(`livestrip.written_past`) is not on the card. Only a read of the card's CURRENT session
counts (the facts carry `session`), so a read from before a resume says nothing about its
successor. The header's "Houses running" count is not fed from the strip: it is the pool,
by the drain's rule, and agrees with the drain log.

**The newest Notification shows at once.** `Notification` hooks (`idle_prompt`,
`permission_prompt`) reach the board within seconds; the card's `notice` is the newest one
of the current turn (`livestrip.notice`: walked back to the turn's `session` or `resume`,
and none once a Stop or SessionEnd of its own session came after). The house word says
`waiting on a prompt` for anything but the idle prompt, unless the transcript was written
more than two seconds after it (the user answered and it carried on).

**One clock.** Every age is the reading's `at` minus the machine's own time for the fact,
plus how long the page has held it, so a phone a few seconds off the machine never reads a
negative age. The page's half is `app/ui.live.js`, run under node in
`tests/fixtures/deck-live.js`.

**What it holds (c-607).** The facts carry `mem_mb`, the RSS of the house's process tree
(`keel/housemem.py`, [houses](20-houses.md) "Closing an idle house"); the strip says it
beside the house word (`1.4 GB`), and an idle house's word carries its idle age and memory in
one: `idle 42m, 0.8 GB`, the age since its turn ended. A house with no reading shows none.
A card whose house the user closed while idle says `closed while idle` in place of `exited`.

**Idle houses on Now (c-607, `app/ui.idle.js`).** Under the Now tiles, a panel lists every
house the harness lists out of a turn at a live stage (the state document's `idle`,
`deckstate.idle_houses`, which holds the idle shipping houses Now draws no tile for), read
again against the strip's newest row. Its head says `N idle houses holding about X GB` (the
readings there are, and how many when not all were read); each row names its card, its stage
(review and shipping in the warn colour: a house someone left), its idle age and its memory,
with Close idle house where it may be closed. A shipping house says when the drain closes it
(a-72, `derived.ship_idle`): `idle 1h40m, closes at 2h`, on its row and on its card's strip. `Close all idle (N)` sends one
`house.close_idle` with `ids` for the idle review and shipping houses; the server checks each
and names any it refused. A card pane and a Now tile draw Close idle house under the key
`close-idle` ("Controls by phase"), only while `K.closeableIdle` holds.

## Settings: which space, and what is unsaved

Two ways a per-space switch goes wrong (c-661). The user
ticks one and leaves without Save, when nothing says a change is pending and the Save sits at
the top of the page, far from the switches. Or the user saves it onto the wrong space, when the page
lists one space's panel before another's, each with the same rows, under a header that reads
as the other's. What `app/ui.settings.js` does about it:

- **The page opens at the deck's space.** That space's panel and its flow are the first
  sections, then This install, then every other space, then Voice. An arrival and a switch
  of space both open at the top (the stored scroll of the route is set to 0), so a past
  visit's scroll cannot land the user in another space's rows. A line at the top says which
  space comes first and what else the page holds, and the header's hint reads
  "Settings · every space" beside the space's name (`K.headerHint`, which `renderHeader`
  asks; the phone's header has no hint, so the line on the page is what says it there).
- **A space's row names its space in the row.** The board's chip (`.bchip.space-*`) beside
  the label, in that space's own colour whichever space the deck is in, so it is still
  there when the panel's heading has scrolled away. The stepper's embedded space forms
  (`K.settingsForm({space})`) carry it too. An install's row has no chip.
- **A row that is not saved says `unsaved`** beside its label, filled in the accent. A value
  put back to what is stored is no change: the mark goes and nothing is pending. The mark
  is there at the first keystroke in a number, list or text field, not at blur: a keystroke
  redraws when it moves the key into or out of the pending set (and only then), and the
  field being typed in keeps its text and caret, because the morph leaves a focused input's
  value alone. The stepper's asked choice (`opts.choose`, a choice whose stored value is the
  default) is the exception to "put back is no change": picking the default there is the user's
  answer, and it is kept as one even after another engine was picked first.
- **The Save bar** is drawn only while something is pending. It is the last child of
  `.set-main` with `position:sticky; bottom:0`, so the whole column of panels is the room it
  sticks within. (Its first form was a grid item of `.set-page` in a row of its own, which
  is all the room a sticky grid item has; the review of c-661 moved it.) It sticks to the
  bottom of `.body`'s content box, so `.body`'s own bottom padding is the gap under it: 14px
  on the desk, and on the phone the dock's height and the inset, which is what holds it
  above the fixed dock with no rule of its own. Measured mid-page on a scratch deck with a
  change pending: at 1440x900, scrolled 1500 of 8842, the bar at 840 to 886; at 390x844,
  scrolled 2600 of 12144, the bar at 669 to 772 and the dock's top at 787, both buttons
  44px. Its button says how many changes and where they go ("Save 2 changes to work", "Save
  3 changes to work and personal", "to this install and work"), and beside it the settings
  by name, each with its space. Discard drops them.
- **Leaving asks first.** `K.beforeLeave(from, to)` is the seam, and `K.leave.may` in
  `app/ui.leave.js` is its one caller: `go` asks it before any move to another view and
  returns having moved nothing when the answer is no. Settings answers with a `confirm`
  naming the changes; a yes drops them, so they are not waiting unsaved when the user returns. A
  switch of space is not a leave: the page stays, reordered, with its changes and its bar.
  A reload, a closed tab or a link out of the deck's shell gets the browser's own ask
  (`beforeunload`).
- **Back and Forward, refused** (`app/ui.leave.js`, below).

Guarded by `tests/test_settings_deck.py`. On the module alone (`tests/fixtures/settings-deck.js`):
the deck in the config's last space has that space first, every space row named, the
changed rows marked and no others, the exact Save label and the names beside it, the bar
the last child of `.set-main`, the leave refused and the unload stopped, a yes dropping
every change, a keystroke marking its row, a number typed back and a switch turned back
asking nothing, and the stepper's choice keeping the default. On the real routing:
`tests/fixtures/settings-leave.js`, below.

## Leaving a view with something unsaved: `app/ui.leave.js`

One small module, loaded by the deck's page only (`app/views.json`; the plan page and the
Console have no guard and their history is untouched). It holds the question and the way
back, and `app/ui.core.js` calls it in three places: `go` asks `K.leave.may(from, to)`
before it moves anything, the popstate listener hands every pop to `K.leave.popped(from)`
before it reads the route, and `enterRoute` calls `K.leave.note()` on every render pass.
`K.routeView` (core) is the view the address names, read without touching the route, so a
refused Back or Forward reads nothing.

By the time popstate fires the browser is already on the other entry, and the History API
says neither which way the user went nor how far. So every entry the page makes carries a stamp
that only grows along the history (`history.state.k`): the module wraps
`history.pushState` and `history.replaceState` once, for every caller (`go`, a selected
row, the find bar, the Atlas, a board), and stamps the entry the page loaded on as it
loads. A push gets a new stamp; a replace keeps the one its entry has. `note` records the
URL and stamp of the entry each pass drew.

- **A refusal walks back.** The stamp of the entry the user landed on against the noted one says
  the direction, and `history.go` steps that way until the stamp matches. No second copy of
  the entry, what lay ahead of it stays ahead, after a Back or a Forward of any length,
  across entries that have no stamp.
- **A pass during the walk notes nothing.** A browser's `history.go` lands later than its
  call, and a render pass in between would take the entry the user is passing through for the one
  the user is on. `note` is skipped while a walk is in flight, and the walk notes the entry when
  it lands.
- **What is left: an entry with no stamp at either end.** An entry has none only when the
  page did not make it through those two calls: a `#fragment` link, or an entry from a deck
  loaded before this module existed. When the user lands on one, or was on one when the user moved, the
  direction cannot be known, so the entry the user was on is pushed again with the search string
  it had. After a refused Back that drops
  the old entry and everything that lay ahead of it. After a refused Forward it leaves a
  second copy of the entry after the one the user landed on, and drops what lay ahead of that.
- **A walk that passes its stamp** without meeting it (the entry is no longer what was
  noted) stops and pushes the entry in the same way, rather than walking on.
- **A walk whose popstate never comes** is forgotten after two seconds (`WALK_MS`), so it
  cannot swallow a later Back; a popstate that arrives after that is read as an ordinary one.

Guarded by `tests/fixtures/settings-leave.js` (run by `tests/test_settings_deck.py`):
`ui.core.js`, `ui.leave.js` and `ui.settings.js` together on a history that has states,
Back, Forward and `go(n)`, can add an entry with no state, and can hold each move until it
is let go. A refused `go`, Back, Forward and two-step Back over an unstamped entry each
leave the view, the URL and the list of entries as they were; a refused Back and a refused
Forward onto an unstamped entry, and a refused Back from one, leave exactly the lists
described above; a walk past its
stamp pushes; a render pass between a refusal and its landing does not move the noted
entry; and a walk landing three seconds late is read as an ordinary pop, with the next
Back asked about.

## The header and the controls row

One control per job, chosen by breakpoint, so no screen offers the same action twice:

- **A Keel card** (c-592, below, "A Keel card on the deck"): the iris Keel · Bosun label
  where it is listed (`K.keelChip`). Driving is retired (c-593; the deck's chip, switches,
  note and May / May not panel went in c-592).
- **Both**: Bosun's entry, left of the drain pill (c-519, [Bosun](96-bosun.md)): a link to
  `/console`. On the desk a pill with Bosun's mark (iris in every space), its name, the
  session's dot, a red count (asks that need the user) and a grey one (open requests); on the
  phone a 44px icon with the red count. The counts show only when above zero.
- **Both**: the drain pill, whose dot is the health verdict (green, amber, red) and whose
  word is the drain's ("drain: polled 3s ago"; the host is not named, c-634); a tap opens the services sheet (below, "The one health verdict"). On
  the phone it is the dot alone in a 44px box (the user's pick, c-519): the word stays in its
  accessible name, and the tap still opens the sheet.
- **Both**: the Voice button, right of the drain pill (and of the code pill when it shows):
  the voice app's bare mark (no tile) in the button's own ink like its neighbours, as a
  plain link to `/segments/voice/app/`, so the app opens in this window and its back link
  returns. 28px on the desk, 44px on the phone. Absent where voice is not installed on this
  machine (`K.voiceHere`, the services block's `off`): the link opened nothing there (c-604).
- **Both**: Keel's mark at the left of the header and of the rail's brand, the hull and fin.
  It is `.mark` in `ui.css`: the glyph is a CSS mask and the paint is the space's accent,
  so it still tells work from personal, as the 8px square it replaced did (c-518).
- **Phone** (the dock layout): the header carries five 44px controls, Bosun and the drain
  dot (above), Voice (above), `⇄` (steps to the config's next space, and the header title with it; absent with one space)
  and `+` (opens the card sheet). The last two carry the `phone-only` class, which `ui.css`
  hides at 900px and up. A sixth joins them only when the code has moved: `↻`, the
  restart, which is a worded pill on the desk (below). The header's items sit 4px apart on
  the phone and the view name is not shown there (the dock already says it), so the space
  name keeps its full width at 390px. The space name shrinks and ellipsises when the
  restart joins, so the row cannot overflow whatever is put in it.
- **Desk** (the rail layout): the controls row, which only exists at 900px and up, carries
  the worded switch of the config's spaces with their dots (absent with one space) and the
  New card button with its key.
  The header shows neither icon.

More has no space switch of its own: its last panel is the drain line.

## A Keel card on the deck

c-592, [Bosun](96-bosun.md), "Keel cards on the user's board". A personal card with a repo is
Bosun's to build, and its `derived.keel_card` says who filed it, Bosun's state and whether
the user's board shows it.

- **The user's personal board** (the Cards list, kanban and phone list, `spaceCards` in
  `app/ui.cards.js`) leaves out a Keel card whose `shown` is false: one Bosun filed that
  does not need the user, or one gone live (the user's come back with Include done). A link to one still
  opens it, since the pane reads the whole board. The find table's `hidden` does not call a
  shown card at done (on next) `done`.
- **The label** (`K.keelChip`, `.kchip`): the iris Bosun mark and "Keel · Bosun", in the
  table's title, the kanban tile, the phone row and Attention.
- **Its words** (`keelWords`): held (a block) and Bosun asks (an open ask) first, then the
  state: plan waiting for you, queued, building, on next, live. In the table they span the
  House, Plan and Outcome columns, as a tracking card's tally does.
- **Its pane** (`keelSection`, `.keelview`, data-key `keel`) is Bosun's view: under the title
  on the desk and first in the content on the phone, with the label, the state, the batch
  and branch, the landed sha (from the done note, once the events are loaded), who filed it
  and Open the Bosun page. The card items add `open-bosun` and leave out every house control
  (`live` is false for it); a held Keel card's gate row is Unblock only (the phone's `held`
  state: the Bosun page, Unblock, Edit), and one waiting on nothing is the phone's `keel`
  state (the Bosun page, Assign, Open plan). The facts grid does not list `options.bosun`,
  nor the retired `driver` and `grant` an old card may carry, and the list gives a Keel card no queue number (the drain's queue
  never starts one). On the phone row the label leads the words line, so the title keeps
  the row.

### Research on the deck

A personal card with no repo, or any card whose `options.kind` is `research` in either
space (`K.research`: not tracking, not a review, not a notice; c-719 added the kind, so a
work research card is no longer labelled PR body or confirmed with "This publishes it",
and its approve publishes nothing), is research, a plan, an errand or a capture, and draws no code pipeline: no PR body, review
round, landing, merged-tree test or shipping word. At its outcome gate the user looks at the
result: **Open result** (the outcome on its own page, `/outcome/<id>`, or its output),
**Done** (the outcome approve, which publishes nothing for it, with one confirm) and **Send
back with a note** (the same `sendback`, which returns it to building with the user's words); the
phone's `result` state leads with those three. **A named output file is never hidden behind
Open result** (c-719): where the card's `output_ref` is a markdown file in its folder, the
deck's `links.output` is that file's viewer page (`/file/<id>/<name>`,
`cardfiles.output_page`) rather than an artifact token, and where Open result opens the
outcome page, the gate row also offers **Open <name>** (`namedOutput`, the `open-named` key,
at every phase) and the result line links both. Any other declared output is offered the same
way under its own name (r1.F6): a work research card's findings board link (its brief stages
with it) is **Open findings board**, anything else **Open output**. It sits in the Links group
right after Open result, with its own tip (r2.F1), so the desk pane draws it and the phone's
More actions sheet lists it; the phone's three are Open result, Done and Send back with a note.
When the output is the card's own record (`context.md`), `links.output` is that record's page
(`/outcome/<id>`, or `/context/<id>` for a record not in the format), the same as Open result,
so no second link is drawn (r2.F4). The outcome stays the one Open result, because it is what
Done accepts; the file is named by its own name so the two are never confused. With no
outcome page, Open result is the file, offered once. Any card's Open output opens such a
file in the viewer too. The evidence is the result's link and "what
it says" (the context's Where it stands, else a research outcome's lede in plain words, `deckstate.research_said`: the paragraph under its title, or the first of its Findings; else the house's last words). Its outcome word is
result ready at the gate and done after. A card that proposes a tier or a flow says **Adopt** in place of Done, with a confirm naming what its draft is written into (c-667, [onboarding](89-onboarding.md)). The plan page's Approve says Done for it
(`sendPanel` in `app/ui.plan.js`, `isResearch`, from the payload's `card.kind`), and not for a tracking card, which keeps its own
outcome gate. Drop in and the house controls stay.

**The create form** (`app/ui.modal.js`, `personalRows`): no Driven by Bosun; on a personal
card Plan style is left out while `[keel] plan_pages` is on (the state document's
`config.plan_pages`), since a plan is always a page then, and Model is asked only of a card
with no repo (a Keel card has no house). The Repo field's help says what empty and a repo
mean (`cardspec.builtin_sheet`). **Worker** (c-645, `workerRows`), in builder mode on a new
personal card: while the chosen repo is one Bosun builds (`config.builder`), a choice of
`bosun` (the default, as before) or `house`, its help saying who approves what in this mode;
on any other card one line, "A house: ...", so where the card goes always shows. An edit
leaves the worker alone: Give to a house and Give to Bosun move it on the pane ([Bosun](96-bosun.md), "Who works a card").

## Answering a gate

The three gate verbs carry the human's answer to the house and are the deck's only way to
answer a gate:

- **`approve`** `{id, gate, said}` runs `kb approve`, and at the plan gate then resumes the
  house with the approval prompt. `said` is optional and is what the user typed beside the tap: it
  travels as `kb approve --said`, so the kb half records it as one note by the human actor
  before the resume half quotes it in the prompt ([cards and gates](10-cards-and-gates.md)).
  At the outcome gate it is recorded and nothing is resumed. Dropping a plan-gate card on
  `building` in the kanban is the same verb with no `said`; dropping a review card on `done`
  or on `shipping` is `approve outcome` (the board decides which of the two it lands in).
- **`sendback`** `{id, reason, stay}` notes the reason and resumes with it. At the outcome
  gate it also stages `building`. With `stay` it opens a discussion ([houses](20-houses.md)).
- **`end_discussion`** `{id}` runs `lavish-axi end` on the plan so the house's own poll
  returns and its loop ends naturally. It says so honestly when lavish is unreachable, and
  it never stops a session.

### The field the user types all three into

One field answers all three, in a SHEET rather than a line in the card: `Approve with a
note` at the plan gate, `Send back`, and `Send back and stay`. Approve itself is untouched
and still one tap; the note is the quiet control beside it and its field may be left empty,
which is that plain approve again. A send back still needs a non-blank reason.

The field it replaced was a one-line `input` in the card where Enter submitted, so on the
phone the user could see about thirty characters of what the user had typed. It is a textarea now: four
lines when it opens, grown with the text by `K.growDraft` up to 40% of the VISIBLE viewport
and scrolling inside itself past that, full width, and 16px, which is not a fifth type size
but iOS's floor (under it, taking focus zooms the whole page). **Enter is a new line.** The
button is what sends, and on a desk keyboard Cmd or Ctrl with Enter does too.

Why the sheet and not a field grown in place, which is the other shape the deck could have
taken:

- **The keyboard.** It covers roughly the bottom 40% of an 844px phone, and the layout
  viewport does not shrink for it, so an in-card field near the bottom of a long pane goes
  under it taking its button with it. The sheet is pinned to the viewport and lifts its
  bottom edge by `--kbd`, which `K.markKeyboard` reads off `visualViewport` whenever it
  moves (0 on every desk browser, so nothing moves there), and it puts the field back on
  screen when the viewport shrinks under it. Measured at 390x500, which stands in for the
  keyboard: field and button both fully visible.
- **A redraw.** The sheet is morphed rather than rebuilt, so what the user typed, the caret and
  the open field survive by construction rather than by a rule the next edit must remember.
- **One idiom.** The create form, the logs and the drop-in command already open this way.

The draft is page state, not DOM state, for the same reason `keepFlag` is: `K.draft`,
`K.setDraft` and `K.clearDraft` hold one draft per CARD and GATE in `App.drafts`, mirrored
into sessionStorage in a try/catch so a reload or the app being killed comes back to it.
Opening Send back after Approve with a note finds the same half-written answer rather than a
second one. Only a submit that was accepted clears it; a refusal leaves everything typed,
and while the send is in flight the button carries the progress verb and the field is
read-only.

When the plan is a markdown page the deck is already carrying its text (`plan_text`, through
`/api/card/<id>`), so the sheet shows the plan's own `Open questions` section above the
field, cut from one heading to the next the way `deckstate.section` cuts context.md and
clipped to a 180px preview with one `Show all`. It is plain text: nothing here parses
markdown, and a plan with no such heading simply has no block.

### Answering a blocked house

A house that stops to ask the user something ends up blocked, and the blocked row used to offer
Resume, Retry and Unblock (now Resume house and Unblock only), where Resume sends the plain `continue from where you stopped;
the card is still at <stage>` (`prompts.RESUME`). The question was never answered; the user's only
ways to answer were voice and Drop in at the desk. The row now leads with **Answer and
resume** (F1) whenever the card has a session: the same sheet the gate answers use, with
what the house said (its block reason, and its last output when that says more) above a
field that must not be empty. It sends `house.resume` with `said`, and the server wraps
the user's words in `prompts.answer_resume` (quoted, then the plain resume line) for the house,
and notes them on the card as the user's (`answered the block: ...`) LAST: the resume is
done first, then the unblock, then the note, and a note that fails is only a missing
record, never a failed tap, since the house already has the user's words. A busy house that refused
the resume carried nothing, so the card does not claim the user answered, and the sheet keeps what
the user typed. Words are the deck's alone: a body with a `caller` is refused (`CALLER_GONE`), so a
house's own `kb` cannot put words into a resume or a note under the user's name. Plain **Resume house** stays
beside it for a block that needs no words: the same verb and the same name as the card
menu's (U1: "Resume" here and "Resume house" there would not read as
one), so the menu leaves its own out of a blocked card. **Unblock only** clears the
block and starts nothing; it was "Unblock", which read as a resume. Both keep their keys
(`resume`, `unblock`), which is what the phone picks by. A card blocked by a refused landing
stays at its outcome gate (`gateOf`: a block opening "outcome not merged" is the merge
refusing, not the house), and its gate row adds **Unblock only** beside Approve outcome and
Send back (without it the only way out is a `kb unblock` typed by hand); Resume
house is in the card's menu, which draws it for any gate but `blocked`. Whether a house is
working is the server's one rule: `row_facts` carries `working` (`housejobs.working`) and
`houseBusy` reads it, falling back to `status` only for a row without it.

Everything else is a plain verb. The kb verbs (`create`, `set`, `stage`, `approve`, `note`,
`block`, `unblock`, `split`, `session`, the tree's `assign` and `next`, a review card's
`rereview` (lane RC), and `claim`, `relay`, `carried`, `land`, `event`, `stop-check`,
`backlog`, `mark`, `reply`, `console`, `tested`, `verdict`, `flowinfo` and the reads `show`,
`list`, `needs-you`, `repos`, `tree`, `queue`) run `bin/kb` as a
subprocess. Every body is the page's own tap, and must carry the page's
cookie (who may act as the user, above): `KEEL_TOKEN` comes from `state/human.token`, so the
board records it as `human`. A body with a `caller` is refused. A hook's
`payload` goes to `kb` on stdin. A read verb leaves the state cache alone; every other verb
drops it. The house verbs are
`house.resume`, `house.retry`, `house.stop`, `house.rotate` (a fresh session from a
checkpoint, [houses](20-houses.md)), `house.logs`, `dropin` and `adapter`, and the
blackboard's nine are `board.push`, `board.list`, `board.find`,
`board.show`, `board.open`, `board.new`, `board.close`, `board.delete` and `board.restore`
([the board](45-board.md), "Deleting a board": a house its own card's boards, Harbor its own,
the user any; restore is the user's alone).
`house.stop` is the only stop in the system. `dropin` cannot open an interactive session
from a server, so it hands back the exact command to run at the desk (`keel/dropin.py`, E2
of the overnight clearance), worked out from the house's own record because only
it knows the cwd, the config dir and whether the session is live:

- a LIVE house (listed, busy or idle) gets `claude attach <bg id>`, which JOINS it: probed
  2026-09-23 on 2.1.280, a turn typed there landed in the same session, same pid and one
  transcript (`tests/fixtures/harness/README.md`). Never `--resume`, which on a running
  session starts a copy (decision N10);
- an exited house gets `cd <cwd> && claude --resume <uuid>`, and a card with no session a
  fresh `claude` in the house's directory;

The answer carries `how` (`attach`, `resume` or `new`) and `said`, the sentence the sheet
prints under the command. Drop in only READS where the house works (`dropin.cwd_of`: the
card's directory, the personal worktree, the work card's recorded `options.worktree`, a
repo card's only when it is not empty, c-789) and never creates one; a house with no live session and no directory is refused with "Retry
recreates it".

**On a done card** (c-787) Drop in is for discussing the finished work. The harness files a
conversation under the directory it ran in, so `claude --resume` finds it only from there:
when the worktree was torn down, the directory is made EMPTY for the gone probe and removed
again (`dropin.reopen_place`, so it is never read as the card's worktree), and the command
handed out is `(mkdir -p <dir> && cd <dir> && claude --resume <id>); rmdir <dir> <parents made> 2>/dev/null`
(`dropin.remade`): the folders it made go again when the session exits, unless the session
made a worktree there (c-789). A leftover empty folder still reads as absent: `cwd_of` and
the ref resolvers' `planlint.card_roots` take a repo card's directory only when it is not
empty (`repolayout.holds_tree`). When the
harness says the conversation is gone (`afresh.done_gone`), or the card has no session or
no directory, the command opens a fresh session in the card's record directory with
`prompts.reopen` as its first prompt: the plan, `context.md`, the outcome and the branch,
and that no worktree is open (`how: record`). No git worktree is made; the session makes one
itself if the discussion comes to a code change. Nothing is started in the background and
no hold is taken, so nothing on a done card is resumed behind the user.

## A tap on a working house is held

The user's tap for a WORKING house (a gate answer, Resume, Answer and resume) is not refused: it is
held (`actions.hold_here`, c-598), a `resume` relay addressed to this machine's own host
that the drain carries once the house's Stop kicks it (`keel/kick.py`). The board is the
hold, and the answer's note says it waits for the turn to end. An idle house is told in its
own session at once, and a house in the user's terminal is only noted. Approve outcome of a work
card is a `land` relay the same way (`keel/landing.py`, [cards and
gates](10-cards-and-gates.md), "the landing queue"). How the drain carries a relay is [the
drain](30-drain.md), "Relays".

## The card dialog and the inspector

The dialog is the new-card form and the same form editing a card. A space with no adapter
draws the built-in fields (`keel/deckstate.py`): Repo, then **New project**, a name that
opens a fresh repo of that name under the space's projects directory ([houses](20-houses.md)),
shown only while no repo is chosen and inferring `attended` the moment it is typed, then
Autonomy, Model and Plan style. The page sends the name and `kb create` decides what it
means, so the deck never has to know that a new project is a repo plus an option.

It draws every field of
the space's `options` schema in order, honouring `when` and `default_if`, with a run of
checkboxes as one row of toggles. Typing the title infers the story, the repo, the autonomy
and the kind from words the schema itself carries. Enter files to inbox; Create and start
also stages `assigned`.

The inspector puts EVERY action in one sticky row under the title, in groups, each split button's caret
carrying its group's name ("Open plan | Pages ▾", c-644; not on the Now tile, which is too tight) (V2-1,
a long list of options makes the item hard to find), then the
gate's evidence, the details, the notes with a one-line composer, and the events. The groups
are one table, `GROUPS` in `app/ui.tips.js`, and every action a card draws is in exactly one
of them (`tests/test_card_groups.py`):

| Group | Its actions, the button's first |
|---|---|
| Decide | Approve plan or Approve outcome, Approve with a note, Send back, Send back and stay (a lavish plan only: a plan in the format has Ask on its own page instead, [plans on the deck](47-plans.md)), Answer Bosun (an open ask of Bosun's about the card: it opens the Bosun page's Now at the ask, `/console#a-N`, [Bosun](96-bosun.md)), Ship at shipping |
| Continue | Answer and resume, Resume house, Resume and open in app, Retry (fresh house), Rotate session, Unblock only |
| Talk to it | Open in Claude app, Drop in, Talk to this house |
| Pages | the card's own pages, each opening its viewer (c-644, [plans on the deck](47-plans.md), "The viewer"): Open outcome where there is one, then whichever the stage is about: Open plan while planning, View context while building and at review, Open comments at shipping ([a card's review comments](67-comments.md)), CI ([a card's CI](66-ci.md)) |
| Links | what leaves the card: Open result (a research card's result, its gate's primary), Open the Bosun page, Open output or Open PR (the output first once there is one; on a card with a pull request in each of its repos, `links.prs`, Open output opens a sheet with one link per repo, c-565), Open story, Open design doc, Logs |
| the flow's own | the moves of the space's flow the user makes at the card's stage (c-640, [flows](64-flows.md)), one group per `group` its moves name, in the order the flow first names them ("Try it live", "Early to master"), each a split button named for it; a move named into "Decide" joins Decide after the gate's own actions, and one that names no group is drawn under **Flow** (`flowGroupsOf`, `groupsOf`, c-644) |
| Card | Dismiss, Assign, Assign tree, Edit, Split, End discussion, Stop session, the adapter's verbs, Move to front, Back in filing order, the backlog controls, Give to a house or Give to Bosun (c-645), Archive |

**The receipt of the last gate answer** (c-537) sits under the card's tree, above the plan
block: who answered which gate and when, and what is happening now (house resumed, or
"held until the house's turn ends" while the user's tap waits for a working house, c-604,
landing on a host, landed on next at a sha, refused with the log), with Plan and Outcome
links. An adapter's answer that is a record (a review round's `{"posted": [...], "pr": 1}`)
reads as a sentence, "published: pull request #1, 3 replies posted" (`receipt.published_line`,
c-601), never as raw JSON. The logs sheet reads `claude logs` as the terminal would show it
(`harness.screen`, c-604): the TUI redraws only the cells that changed and jumps over the rest
by cursor moves (`ESC [ n G`, `ESC [ r ; c H`), so stripping the escapes lost the spaces and the
unchanged letters ("held-tap t st in"); the moves are replayed onto a grid (the log's last
256 KB, a wide character as two cells, DCS strings and private parameters read as escapes), and the sheet's
`pre.logs` keeps every space (`white-space: pre-wrap`). The TUI returns to column 0 with a
carriage return and makes its own row move after it (`ESC [ 1 B`); `claude logs` hands the
`\r` back as it is, but read with newline translation (`text=True`) each one became a line
feed, every line slid one row further down per redraw, and the spinner's letters and
counters landed in finished text ("one-line1docstring2on9all_reports"). So `harness.logs`
reads it `raw` (bytes, decoded with no translation, c-605 review), and stdout and stderr
are each their own screen, joined by a line. `tests/fixtures/harness/logs-redraw.out` is a
real capture (1144 returns, no line feed), read as bytes and held to its 57 clean rows.
It is `keel/receipt.py`'s answer, carried on `/api/card/<id>` beside the events, and
drawn by `app/ui.receipt.js` exactly as the plan page's send panel draws it
([plans on the deck](47-plans.md)). The Bosun page has no Inspector of its own (c-591, which
removed c-537's console-card drawer): a card there opens here, and an old
`/console?card=<id>` link comes here too ([Bosun](96-bosun.md)).

A group with more than one live action is a **split button** (`K.splitButton`,
`app/ui.core.js`): the first action the card has in the group's order is the button, and a
caret opens the rest. **A critical action is never the lead of a split group** (c-653,
`critLead` in `app/ui.tips.js`): every split group overlaps its caret by 1px to share a
border, so with Stop session leading the Card group at shipping (c-240, 1440 wide) the
caret was drawn over the stop's red right edge and the two read as one cut control. A
critical action that would lead stands alone on the row with the row's own gap, and the
rest of its group is that group's own control (a plain button when one is left). On the
phone Stop session is under More actions, in its Card section. The order is the preference, so the gate's primary (Approve plan,
Approve outcome, Answer and resume, Retry on a blocked card that never started, Dismiss,
Assign) is always a group's button and never inside a menu. Read's order follows the stage:
the plan while planning, the output at review and after, the context while building (a
review card's Read leads with its page at the gate and with Open PR otherwise; its Card
group leads with Review, then Review settings, then Dismiss review, and has no Edit). A group
with one live action is a plain button, and one with none is not drawn. The two pills (**on
voice**, **in a terminal**) are facts, not actions, and sit before the groups. The menu is a
real one: `aria-haspopup="menu"` and `aria-expanded` on the caret, `role="menu"` and
`menuitem`, the arrow keys, Home and End to move, Escape to close with focus back on the
caret, Tab or a click elsewhere to close. Which menu is open is page state (`App.menu`), so a
redraw draws it open again with the same entry focused. **Every entry shows its name and,
under it, its hover line** without the name it starts with, so what the desk hovers is
readable in the menu too.

**A button that cannot act is not drawn**: Logs and Stop want the card's OWN session listed
live (`house.recorded`: a row the listing matched only by the card's name, an orphan of an
earlier start, is not the session they act on, and the server refuses both on a session the
harness no longer lists, `actions.refuse_ended`, writing nothing, c-601), Resume
house wants a session whose house is not working (N10; the server refuses a busy one
anyway, [houses](20-houses.md)), and each link wants its own key. A card the user dropped into
from a terminal (`options.dropin_hold`, [houses](20-houses.md)) shows an **in a terminal**
pill and draws no Resume house, Answer and resume, Resume and open in app or Rotate session:
the server refuses all of them while the hold is there, and the pill goes when the drain
ends it.

### Controls by phase

**Which phase may show a control is one table** (c-601, "every button and behaviour that is
shown now should be justified"): `CONTROL_PHASES` in `app/ui.cards.js`, keyed by the key
every action carries, listing the stages (`K.stageOf`) it may be drawn in. Both `put`s of
the pane (`gateActions`, `cardItems`) ask it (`K.shownIn`) before anything else, so the
condition written beside a control (a session, a live house, a link, voice here) only
narrows it; a key the table does not name is never drawn. `tests/test_deck_phases.py` holds
the table equal to this one and renders the pane in every phase
(`tests/fixtures/deck-phases.js`). A Now tile's buttons ask the same table
(`houseActionNodes`, `app/ui.views.js`). The shipping column is card c-600's (after-gate). The
pane's shipping phase draws its own set (`K.shipping`), but the table still decides at shipping
for two callers: the Now tile, which asks it for Open in app, Logs and Stop of a shipping house
that works, and a Keel card, which skips the shipping branch (c-604 review). So were the
outcome and round pages' own controls.

| Control | Key | Shown in | Why there |
|---|---|---|---|
| Answer Bosun | `answer-ask` | every phase | Bosun's open ask about the card can be about any stage |
| Unblock only | `unblock` | every phase | a block can sit on a card anywhere, and lifting it starts nothing |
| Dismiss | `dismiss` | every phase | a segment's notice closes from wherever it sits |
| End discussion | `end-discussion` | every phase | drawn only while a discussion is open, and ending one is always the user's |
| Edit | `edit` | every phase | the card's fields are the user's at every stage |
| Open the Bosun page | `open-bosun` | every phase | a Keel card's way in is Bosun, at any stage |
| on voice (pill) | `on-voice` | every phase | a fact about the house, not an action |
| in a terminal (pill) | `in-terminal` | every phase | a fact about the house, not an action |
| Open story | `story` | every phase | a read |
| Open PR | `open-pr` | every phase | a read (a review card) |
| Open design doc | `design-doc` | every phase | a read |
| Open plan | `open-plan` | every phase | a read |
| CI | `open-ci` | building, review, shipping, done | a read: the card's CI page ([a card's CI](66-ci.md)), on a card with a repo whose space has `ci` ready |
| Give to a house, Give to Bosun | `worker` | inbox, assigned | the user's move of who works the card (c-645), on a card Bosun may build, before anything starts on it (no session); the board refuses it later ([Bosun](96-bosun.md), "Who works a card") |
| Open comments | `open-comments` | shipping, done | a read: the card's review comments page (read only once done) ([a card's review comments](67-comments.md)), among the card's Pages once the house was told an item (c-643; a Pages button since c-644) |
| Open output, Open result | `open-output` | every phase | a read |
| Open <file name>, Open findings board | `open-named` | every phase | a read: a research card's declared output beside its result, named for what it is (c-719 r1.F6) |
| View context | `context` | every phase | a read |
| an adapter verb | `verb` | every phase | each verb carries its own `when` in the space's verbs table |
| a flow move the user makes (c-640) | `flow` | every phase | each move carries its own `stages` in the space's flow, and shows only on a card with a house |
| Review settings | `review-settings` | every phase | its own rule (`reviewSettable`) says when |
| Move to active, Back to auto | `backlog-active`, `backlog-auto` | every phase | the backlog override is a field, settable anywhere |
| Send to backlog | `backlog-send` | review | an outcome the user will not answer yet |
| Archive | `archive` | every phase | putting a card away is always the user's |
| Approve plan | `approve-plan` | planning | the plan gate's answer |
| Approve with a note | `approve-note` | planning | the plan gate's answer, with words |
| Send back and stay | `sendback-stay` | planning | a discussion on a lavish plan |
| Send back | `sendback` | planning, review | the two gates' other answer |
| Open result | `open-result` | review | research's outcome, read before Done |
| Open outcome | `open-outcome` | review | the outcome's own page (`/outcome/<id>`, where it has one), read, noted and answered there; the primary beside Approve outcome, as Open result is beside Done (c-605: it was reachable only through More, then View context) |
| Approve outcome, Done | `approve-outcome` | review | the outcome gate's answer |
| Answer and resume | `answer` | planning, building, review, shipping | the user's words to a blocked house that has a session; a done card has no house |
| Resume house (blocked row) | `resume` | planning, building, review, shipping | a blocked house with a session; never on a card that never started (Retry starts it) |
| Retry | `retry` | every phase but done | a fresh house; a done card is not restarted from scratch |
| Back to your gate | `regate` | inbox, assigned, planning, building, review | a tracking card the user sent back with every slice done; it reads at review (`parent_stage`) once they are, and the drain closes it from review on its next pass (c-649) |
| Split | `split` | inbox, assigned, planning, building, shipping | cutting work that has not reached the user's outcome gate; at review the answer is Send back. In a stacking space a slice that waits for an earlier one also asks stacked on it or independent (c-718, [cards and gates](10-cards-and-gates.md), "Stacked or independent") |
| Open in Claude app | `open-app` | planning, building, review, shipping | a listed house; a done card's house is finished and its worktree reaped |
| Talk to this house | `talk-voice` | planning, building, review | voice connected to a house with a session, and only where voice is installed on this machine (`K.voiceHere`); at shipping the Talk sheet carries voice among the other ways in |
| Talk (the sheet) | `talk` | shipping | every way into the house's own session in one sheet (the app, Drop in, voice), drawn where voice is installed since the app and Drop in are on the row itself (c-653), to discuss a verdict or ask for a change (c-600); one key had meant both until c-604 |
| Resume house | `resume-house` | planning, building, review, shipping | an idle house to continue; never at done (the server refuses it too, `house.refuse_if_done`), and not at an open plan gate, where the user's answer is the gate's (c-604) |
| Resume and open in app | `resume-app` | planning, building, review, shipping | the same house with no turn; never at done |
| Rotate session | `rotate` | planning, building, review, shipping | a house long enough to need a fresh session |
| Logs | `logs` | every phase | the card's own session, listed live; at done only while the harness still lists it (`lingering`), as a post-mortem read |
| Stop stale session | `stop-twin` | every phase | a second live session named for the card (`house.twins`), which `tellhouse.refuse_twins` asks the user to stop; never the card's own (`actions.stop_twin`) |
| Stop session | `stop` | planning, building, review, shipping, done | the card's own session, listed live (a merged card's house stays listed until it is stopped, c-600) |
| Close idle house | `close-idle` | review, shipping | a listed house the harness says is idle, holding memory while nobody needs it (c-607); only where something brings it back by itself (the user's gate answer at review, the next batch at shipping; at planning and building nothing would, so Stop session is the user's way there, c-607 review), only while idle (`K.closeableIdle`), never with a job of its own running, and the server checks again at the tap, under the card's lock (`keel/idleclose.py`) |
| Drop in | `dropin` | every phase | a terminal into the house, or a fresh session in the card's directory before it starts; on a done card its conversation, else a fresh session in its record (c-787) |
| Re-review | `rereview` | done | new commits on a pull request the user reviewed |
| Review now anyway | `review-now` | inbox, assigned | a held review card waiting for its story's other side |
| Ship | `ship` | shipping | the one door out after the gate: push, ready, post the kept replies (c-600); named for what it sends, and drawn only where the send can succeed (c-653) |
| the line where Ship would be | `ship-why` | shipping | why nothing is sent from here now (the branch diverged or behind, with the by-hand commands in a copy block; the house in its turn with Ship anyway; nothing waiting), or a conflict the send will not cure (c-653) |
| Hand N comments (and the failing check) to the house | `hand-over` | shipping | the waiting review, told to the house on the drain's next pass (c-655); in Continue, so it is its own button beside Ship |
| Bring the branch up to its base | `hand-base` | shipping | the base merged into the branch by the house, with whatever review waits; in Continue's menu, or its button with nothing else to hand |
| Send back | `ship-sendback` | shipping | the user's own notes for the card's house (c-663): a sheet for the user's words, told as the house's next item once it is free; the card stays at shipping and nothing is posted |
| The house's question, with Answer | `ship-prepared` | shipping | a fix the house prepared that waits on the user's yes (r-55, c-723): its question in its words, and Answer, which opens Send back with the item's handle leading the user's words |
| Assign, Review | `assign` | inbox | starting a card is the inbox's one act |
| Assign tree | `assign-tree` | every phase but done | a big card's slices to start |
| Move to front, Back in filing order | `next-front`, `next-filing` | every phase but done | a card or a tree waiting its turn |
| the tracker's line (`K.needs`, one line) | `need-tracker` | every phase | a line leading the row, for a card with a ticket ref (so no Open story) and no tracker set up: why, and Set it up (c-631); at shipping not repeated under a code host line that says the same reason (c-662) |
| the code host's line | `need-codehost` | shipping | the row's first line, above Ship, while the space's pack declares no code host: what Ship will be refused with; Ship stays and the backend decides (c-631) |

**Resume and open in app** (V2-2, `house.open_app`, `keel/openapp.py`) is for typing into a
house in the Claude app with no "continue" turn going in first. The server brings the house
back WITHOUT a turn: an exited house is woken (`house.wake`: no prompt, no model turn, the
same session and the same claude.ai link) and a listed one is left exactly as it is. It is
refused wherever a resume is (`house.refuse_if_busy`: a working house, a session open in the user's
terminal, a Drop in hold), The link it answers with is the one the card's CURRENT session recorded
(`openapp.current_link`, read back from the events, since `options.app_link` can still hold
an older session's link after a resume that found none); a card with none polls the log for
four seconds and keeps what it finds. With a link a blocked card is unblocked, as a resume
would; with none the answer says so in one line, the block stays, and the house stays awake.
The page opens an empty tab ON THE TAP and points it at the link when it arrives, because a
tab opened after a network answer is a popup the browser blocks. It is drawn for a card with
a session that is not working or held, except where Open in Claude app
already does the same (a listed house whose link the card has).

**Every action says what it does on hover** (U2, 2026-09-24): one line that says what
happens and what does NOT ("Retry: starts a fresh house from scratch. The current
conversation is dropped."), from ONE table in `app/ui.tips.js` keyed by the action's
data-key, so the wording is edited in one place. It is put on in the one place every
action of the inspector is keyed (`put` in `gateActions` and `cardItems`, plus the phone's
Assign tree and More actions) and on the Now tile's buttons, as a `title`, never an
`aria-label` (which would replace the visible name for a screen reader).
`tests/test_card_tips.py` fails on a drawn key with no line and on a line nothing draws.
Drop in's line names the case it will act on, in `keel/dropin.py`'s own `SAID` sentences
(a test holds them equal): attach to a listed house, resume an exited one, a fresh session
on a card with none, and all three together when this deck cannot tell (a house on another
machine not yet asked, or a stage this deck's listing does not carry). An adapter verb's
line is the verb's own `help` from the space's verbs table, so its vocabulary stays in
its pack. The phone has no hover, so its More actions sheet shows the same line under
each action's name (V2-1).

**On the phone the pane is content first** (F2). The desk row above sits under a title with
the whole pane beside the list; on a 390px screen the same order was about twelve buttons
(the gate verbs, then six full-width link rows) before a line of the card, and c-302 at its
plan gate showed its plan at y 770 of 844. The phone pane now goes: the title and its
words, the CONTENT (a big card's tree or a slice's place in it, the plan block, the gate's evidence, the brief), then ONE row of at most
three actions picked for the card's state plus **More actions**, which opens every other
action in a sheet (`actionsSheet`), under the desk's group headings in the desk's order,
each action's line under its name (V2-1), then the boards, the slices, the facts, the notes
and the events. The picks are a table keyed by state (`PHONE_PRIMARY` in `app/ui.cards.js`),
naming actions by the key every action button carries:

| State | The three |
|---|---|
| plan gate | Open plan, Approve plan, Send back (a plan the user cannot reach in one tap is not one to approve; Approve with a note is under More actions) |
| outcome gate | Approve outcome, Send back, Open output |
| blocked | Answer and resume, Resume house, Retry |
| notice | Dismiss, Edit |
| an open ask of Bosun's, nothing else waiting | Answer Bosun, Open plan, Open output |
| a review card in the inbox | Review, Open PR, Review settings |
| a review card posted (new commits) | Re-review, Open PR, Review settings |
| a review card posted | Open PR, Review settings, Open output |
| inbox | Assign, Edit, Archive |
| a big card (tracking) | Assign tree (N), Open plan, Edit |
| a listed house | Open in Claude app, Talk to this house, Logs |
| anything else | Open plan, Open output, Resume house |

An action the card does not have is skipped rather than replaced, so a state never shows a
button that cannot act. The row is two to a line and does not stick to the top: it follows
the content, so reading leads to it. A tap on anything in the More actions sheet closes the
sheet first, so a verb's answer lands on the pane and a control with its own sheet or the
dialog is not drawn under it. The desk keeps its one sticky row of groups.

**Now's tiles group too** (V2-1): a house tile that draws more than two actions draws them
in the same groups (`houseActions` in `app/ui.views.js`), so a blocked house reads
`Resume house ▾` (Resume and open in app, Retry) and a house in a plan discussion reads Open
in app, Logs, `End discussion ▾` (Stop). Two or fewer stay plain buttons. On the phone a
tile's caret opens its group as a sheet (`K.menuSheet`), because the Now strip scrolls
sideways and would clip a menu.

The facts grid lists every option key the space's schema does not name as a raw row, so a
key a house or a segment set is never invisible. The board's own bookkeeping is the
exception (`HIDDEN_OPTIONS` in `app/ui.cards.js`: archived, backlog, branch, worktree and
the rest, each drawn somewhere else), and so is `options.provenance` (F7), the per-field
map `keel/cardspec.py` writes on every card ([cards and gates](10-cards-and-gates.md)):
listed raw it was one row of JSON on every pane. Its visible form is a chip that is still
to come.

**No raw JSON in the facts grid, for any card kind** (lane FC, FC-9). An option that holds
an object is drawn as the facts it carries, or not at all (`optionFacts` in
`app/ui.cards.js`). A review card's are named: `review_pr` is its author, the pull request
as a link, when it was raised and its head, short; `review_focus` is the user's words;
`review_members`, `review_heads`, `review_posted`, `review_new` and `review_wait` are one
line each; what posting records as it goes, the members' checkouts and the carried ledgers
are bookkeeping and hidden. Any other object is flattened to its plain values ("state
testing · mode quick"), a list to its items or its labels, and one with nothing plain in it
is left out. `tests/fixtures/deck-pane.js` walks every option a fixture card can carry and
fails on a `{` or a `[` drawn in the grid.

A review card at its outcome gate (lane FC, FC-8) has no PR body of its own (it posts
comments on someone else's pull request), so its gate evidence is one line saying the
findings wait on the outcome page, never "context.md has no PR body yet".

The renderers themselves are run under node by `tests/fixtures/deck-pane.js` (from
`tests/test_deck_pane.py`), against the DOM stand-in `tests/fixtures/deck-dom.js`, at a
phone and a desk width: what the pane draws, in what order, and which actions it offers.

**The pane's house row.** `K.houseOf` in `app/ui.core.js` reads the card's own row (`c.house`,
from this machine's listing) first and the detail's second, and the page asks again on each
`tick`, because an app-typed turn changes the house with no board event.

Its frame is `K.paneFrame` in `app/ui.core.js`: the title with the ✕, the identity line,
the words, then the sticky action row, then the sections. `K.phonePane` is the same pane
as a phone route, with the back control above it. Both are shared, so a route that opens a
pane cannot invent a second shape for one.

### The pane keeps its place

A pane rebuilt from scratch loses what the DOM was holding for the reader: the scroll
offset of every block inside it above all. A long brief, a PR body and a blocked house's
last output all jumped back to their first line every five seconds, which is what "it looks
like the content is refreshing" was.

Nothing is rebuilt now. The render pass morphs (below), and every section of the pane
carries a `data-key`, so a section that appears or goes (a plan block on a card that has
just been given a plan, the slice list) moves nothing around it and each one is the same
node, holding the same offset, from one pass to the next. The node cache that used to sit
here (`K.keep`, one node per key while a hash of its input held) is gone: it existed to
avoid work that is no longer done.

`K.keepFlag(key)` stays, and it stays for a reason the morph cannot cover. Whether a long
block is expanded is PAGE state: nothing in the tree a renderer builds says it, so a redraw
recomputes `.clip` from whatever the page remembers, and a page that remembers nothing
would fold the block shut under the user. `K.keepPane(name)` names that map and drops it whole
when another card or provider row is opened.

On the PHONE the pane has no nested scroller at all. `.reading` and `.rendered` are
`max-height:320px; overflow:auto`, which is a desk arrangement: a window onto a long block.
On a page-scrolled phone that is a scroll inside a scroll (`<install>/history/docs/deck-mobile-audit.md`,
recommendation 3), so the block hands its axis back to the page and a long one is clipped
to a 180px preview with one `Show all` under it that expands it into the page's own scroll.
Open lives in the pane's flag map, because it is the one thing the morph cannot keep: no
part of the built tree says it. The desk keeps its 320px windows.

### The plan block, where the frame was

The pane used to put the live lavish session in an `<iframe>`: the poll rebuilt it, so the
plan reloaded every five seconds, and lavish's whole chrome (the bar, the annotate switch,
the conversation panel) sat in a box a few hundred pixels tall. There is no iframe in the
pane at any width now. In its place `K.planBlock` says what the deck actually knows about
the plan: the plan document's own first heading when the deck is carrying the text (a
markdown plan, through `/api/card/<id>`) and the card's title when it is not, the plan word
the rest of the page already draws (`gate open`, `approved`, `written`), a `live` chip when
lavish still has a session for it, and when it was last touched (the file's mtime from
`plan_at`, and the newest approve or `plan_ref` set when there is no mtime to read). The
Attention pane draws the same block, because it draws the same gate evidence.

The count of decisions a plan is waiting on is deliberately NOT in it: that number lives
inside lavish's own session, the deck does not carry it, and fetching it on every poll
would be the deck reading another tool's state to print a number.

Open plan (live) stays in the action row and opens the plan FULL SCREEN: a tab beside the
deck on the desk, and on the phone a top level navigation in the surface the user is already
holding, so lavish gets the whole viewport and Back is the way out of it.

## Talking to a card's house

The inspector's actions carry **Talk to this house**, beside Open in Claude app, Resume
house and Drop in. It is a LINK, not a verb: it opens the voice page already connected to
that card (`/segments/voice/app/?connect=<id>`), because a microphone is the door this was
asked for ([the talker and voice](50-talker-and-voice.md)). `house.converse` is the same
turn as a deck verb, `{verb, id, text}` answering with what the house said, for a turn
typed from somewhere without a microphone.

While voice holds a card (`derived.voice_hold`, which the state document carries), the card
shows an **on voice** pill where "Open in Claude app" sits and Resume house is absent:
voice stopped that session on purpose, so the app link cannot open until the house is woken,
and a resume would be refused anyway. Both go the moment the hold does.

**Stop still wins.** `house.stop` is not refused by a hold: it releases it, stops the
session and leaves the house DOWN, because the user is the one who stopped it. The note says it
was stopped while voice was talking to it, and the gateway drops its pin on its next turn.

## The Reviews list (lane RC)

Reviews is the list of REVIEW CARDS, one per pull request that needs the user's review
(`keel/reviewcards.py` files them), and nothing else: the old scanner's rows are not drawn,
and neither are its row verbs (Lavish review, Terminal review, Launch review, Generate
orientation, the lane moves) nor its Scan now. Each has a card-side equivalent: the user's Review
tap is the card's move to assigned, and the outcome page is where the findings are read,
edited and posted.

- **A row** says the card, its title, its COLUMN in the old review board's word (below,
  with what it means on hover), a **new commits** or **closed** badge when that is so, the
  severity the user posted, the repo, the author, the pull request's number and when it was
  raised. A tap selects the CARD (`&card=`): its own pane opens beside the list on the desk
  and as a route on the phone, in the grouped actions every card has.
- **A review card's actions are a review's** (2026-09-24). No Split (it reviews one pull
  request) and no Edit (the generic form was a house card's, whose fields a review card
  takes from its pull request). By where it stands: in the inbox **Review** (the move to
  assigned) is the Card group's button, with **Open PR**, **Review settings** and **Dismiss
  review**; while it reviews, the usual Continue and Talk to it groups; at the gate
  **Approve** (it posts) and **Send back**, with the page (Read's Open output) where the Ask
  is; after posting, **Re-review** when new commits came, **Open PR** and **Review
  settings**. Outside its review round a
  review card draws no Drop in, Talk to this house, Open in Claude app, Resume house,
  Resume and open in app or Rotate session (`houseActs` in `app/ui.cards.js`).
  **Dismiss review** is Archive under its review name: "Hides this review. It is not filed
  again unless the pull request gets new activity." That is the fetcher's rule
  (`reviewcards.revive`, RC-8): a dismissed card stays hidden while its pull request is
  still, and the SAME card comes back when the pull request, still listed as needing the user's
  review, has activity after the dismissal (the host's update stamp, or a new head). A
  dismissed card reads **Restore review**. A closed card's notice already draws Dismiss, so
  Dismiss review is not drawn beside it.
- **Review settings** (Card group; "The model this review runs on, and an optional focus
  note for the reviewer.") opens a sheet with exactly two fields: **Model**, Sonnet or Opus,
  starting from the card's own (the fetcher's review model when it was filed), and
  **Focus**, optional words kept on the card as `options.review_focus`. One `set` writes
  both; an empty focus clears it. The reviewer is handed the focus with the diff: the brief
  quotes it and `review-focus.md` is among the only paths the reviewer gets
  (`brief.write_focus`, [houses](20-houses.md)). It is drawn only while nothing reviews: in
  the inbox, at assigned before the house starts, and after posting, where it applies to the
  next Re-review; never while it reviews or at the gate (`reviewSettable` in
  `app/ui.cards.js`; the sheet is `app/ui.reviews.js`).
- **The backlog** (a review card in the inbox whose pull request has gone quiet, [cards and
  gates](10-cards-and-gates.md)), the old board's **Held**, is counted in the title and not
  listed, as backlog cards are kept out of Cards and Attention; the find bar's Include
  backlog (or its Held view) adds them to the list, the kanban always draws them in Held,
  and Review on one works as for any card.
- **The columns** are the OLD REVIEW BOARD's, the same names and order, and the State facet
  uses the same six so the filter and the columns agree (`lanes` and `laneOf` in the
  `reviews` table, `app/ui.findpages.js`): **Detected** (in the inbox, waiting for the user's
  Review tap), **Assigned** (queued for the review pool, or being reviewed), **Inbox**
  (reviewed: the findings wait at the user's gate for Approve to post them), **Held** (the derived
  backlog: quiet past `review_backlog_days`, or the user's backlog override, the old Hold),
  **Posted** (the user's review is on the pull request; one with new commits stays here with a
  badge and Re-review) and **Dismissed** (archived; back on new activity). A closed card
  (its pull request merged or was declined) sits where it stopped: Posted when the user had
  posted, else Detected, with a closed badge.
- **Finding** is the deck's one find bar ("The find bar", above; lane FIND): facets State
  (the six columns), New commits (since your review), Author, Repo, Highest finding
  (critical, high, medium, low) and Raised (today, this week, older); Include backlog,
  Include closed (its pull request merged or was declined) and Include dismissed (a
  dismissed review card is an archived one), each out of the list until its switch is on;
  sorts Newest raised (the default), Oldest raised and Latest activity; built-in views
  Waiting for me (Detected), At my gate (Inbox), New commits and Held. It reads the
  facts on the card, `derived.review`, `derived.review_severity` and `options.review_pr`
  (the author, when it was raised, updated and last active), so finding asks the code host
  nothing.
- **List or Kanban** (2026-09-24): the find bar's View button on the desk offers the layout,
  remembered and in the URL (`layout=`) like Cards' (`modes` in the `reviews` table,
  `app/ui.findpages.js`). The kanban draws the columns above in order, each with what it
  means under its name: Held always (its count tells the user how many went quiet, whatever
  Include backlog says), Dismissed only with Include dismissed. The columns are the found
  list cut by column, so every other filter and the sort apply within them, and an empty
  column is still drawn. A tile says the id, the title, its badges (new commits, closed, the
  severity the user posted), the author and number and when it was raised; a tap opens the card's
  pane beside the columns. Tiles are not dragged: a review moves by its own actions. Desk
  only: the phone stays a list and has no View button, as Cards' kanban is desk only.
- **Scan now** sits beside the gear (2026-09-25), only when the adapter offers the verb: the user's
  tap sends `act do reviews scan_now`, which leaves an ask in `state/review-scan.json` for this
  machine's drain, whose next pass scans at once instead of
  waiting out the fetcher's 15-minute cadence. Its tip says when the fetcher last looked; a
  scan already asked reads Scanning and cannot be asked twice. The scan clears the ask as soon
  as it has run (`reviewsettings.scanned`), and the deck's kept provider reading (30 seconds)
  is read again at once when the scan file changes (`deckstate.scan_moved`, c-734): the box
  test saw Scanning for a while after the scan had filed its card.
- **The two settings** sit behind a small gear at the title, on the desk and the phone
  alike: auto review (a new review card is filed at assigned, not the inbox) and the review
  model (the model a new review card carries). Both are the space's own (`review_auto` and
  `review_model` in the install's `config.toml`, with the gear's live override under `state/`,
  `keel/reviewsettings.py`); the adapter's `reviews` provider carries them to the page and
  its route verbs set them. The orientation mode is gone, since a review card's outcome
  always carries its orientation.
- **The counts**: the rail's Reviews number and Now's `reviews` line are the review cards
  waiting on the user (the user's Review tap or gate, new commits); a review card at its gate is in
  Attention like any card at a gate, and one whose pull request closed before the user's Review is
  a notice there.
- **A feature card** (lane GRP: one story's pull requests reviewed as one card,
  `options.review_members`) shows its members on the row instead of one repo: a chip per
  pull request saying its repo and number (`cloud #4150`), each opening its own pull request
  on the code host (`K.reviewMembers` in `ui.reviews.js`, a link-role span because the row
  is itself a button, and a tap on it does not select the row). The Repo facet matches it
  for EACH of its repos (its `repo` is the comma list), and the search reads every member's
  label. The Reviews kanban's tile (lane RV) takes the same chips from `K.reviewMembers`.
- **A held card** (lane GRP, `derived.review` held: its story has a branch and no pull
  request yet in the other repo) says why on the row, in the pane's outcome word and on a
  kanban tile in the Held column (lane RV), one line from `K.reviewWaitLine` (`ui.cards.js`): "waiting for the cloud PR
  (sc-41001 has a branch there), 31h left", from `derived.review_wait`; it WRAPS in the
  desk pane's head rather than running off its right edge (lane FC, FC-10: the word is a
  `tally`), and its title carries the whole line. The State facet has
  Held. Its one way out is **Review now anyway** in the Continue group (`review-now`, its
  line in `ui.tips.js`, first on the phone's inbox row): a `set` of `options.review_wait` to
  null and `options.review_alone` to true, so the fetcher never holds it again. Review is
  not drawn on a held card, so the wait ends one way; after Review now anyway it is.

## No PRs page (lane RETIRE)

The PRs page is gone with the pull request watcher that fed it (2026-09-24). A work pull
request Keel's house built is a card in `shipping`: its chip says the pull request's state,
and the Cards page's Shipping view lists every one. An old link to the PRs route, or a
remembered one, lands on Cards with that view applied and says so in the URL (`readRoute`
and `landOnShipping` in `ui.core.js`, `K.find.preset` in `ui.find.js`). The rail, the dock's
More count and Now's At a glance no longer count watched pull requests.

## Code moved, restart

The state document's `config` block carries `code_head` (the checkout's commit),
`serve_head` (the commit this serve process loaded) and `code_moved`. When they differ the
header offers Restart, which sends the verb `restart`: serve answers, then execs itself with
the same arguments half a second later (under launchd that is an ordinary exit with
KeepAlive). The drain does the same on its own between passes ([the drain](30-drain.md)),
and so does a deck that runs without the drain in its process (c-637), as `keel serve` or
its own launchd job: a thread looks at the checkout's head every two seconds
(`serve.follow_code`, `CODE_POLL_SECONDS`) and, once it moved, execs onto it at the first
moment nothing it holds would be cut (`restart.busy`: a conversation, a house call,
or a deck action, which `post_action` holds as `restart.DECK_ACTION` while `actions.act`
runs). Where the roles share one process (`keel run --roles drain,serve,fetch`, an
install's default) `cli.role_run` turns that thread off: the drain's restart between its
passes is the whole process's, and a deck thread could have cut a pass. So the pill is
seen only while a wait lasts on a deck of its own, and in a shared process until the drain's
next pass restarts it (up to `poll_seconds` and a pass). Without it, a deploy moves main, the drain
restarts, the deck does not, and the old server sends the new page with its scripts
unfilled: a blank deck until it is restarted by hand (c-634). `/api/health` carries `serve_head`
too, which the deploy waits on. The exec waits for nothing a plain read holds, so it can cut
a `/api/health` reply half sent: the reader gets a refused connection (an `OSError`) or a
body shorter than its length (`http.client.IncompleteRead`, an `HTTPException` and no
`OSError`), and `deploy.serve_head` reads both as "no answer yet" (c-662). The end to end test
(`tests/test_serve.py`, `FollowCodeTest`) runs its deck on a copy of the checkout in a
temporary folder with `PYTHONDONTWRITEBYTECODE=1`, which the exec keeps with the rest of
the environment, and asserts that no `__pycache__` appeared: a deck still importing wrote
bytecode there, and the import system makes a removed folder again under the removal
("Directory not empty"). The deck stays in the runner's process group, so the suite's
timeout (`merging.kill_suite`) ends it with the runner.
The setup verbs that change the config (`setup.repo.clone`, `setup.repo.remove`,
`setup.pack.on`, `setup.pack.off`, `setup.pack.build`, `setup.settings.save`, `onboarding.CONFIG_VERBS`) end the same way: once the install's config is written, serve answers with `restarting` and execs itself, so
the deck reads the new config ([onboarding](89-onboarding.md)).
It is the worded `code moved · restart` pill on the desk and the `↻` icon on the phone,
where twenty characters cost the header 166px of a 390px row.

## The find bar

ONE find system on every page that lists things (Cards, the board list and Reviews), built 2026-09-24 (lane FIND) to replace what each page had grown for itself:
stage chips, a topic select inside a chip, group-by chips that did nothing on the kanban, a
second stage strip on the phone, board chips that ignored the space switch. Nothing was
multi-select, nothing had a sort, nothing was remembered, and the same idea had different
words on different pages.

```
[Views ▾] [ search, or stage:review repo:keel ] [Filter 2 ▾] [Sort ▾] [View ▾]
Needs me · Queue order   Stage: Review, Building ×   Repo: keel ×   Clear all
```

- **The search** takes free words (every word somewhere in the item) AND typed filters in
  one grammar, `stage:review,building repo:keel topic:"big ideas" include:done`, with a
  suggestion list under the field while the user types: the fields it starts, then that field's
  values with their counts. Arrows move, Enter takes, Escape closes. A filter the user has
  finished (a space after it, or Enter) leaves the field and becomes a token; one the user is
  still typing does not filter the list as a word. A field the page does not have, a url,
  `c-12:`, are all just words.
- **Filter** opens the panel: every facet MULTI-select with a count beside each value (the
  count is what the list would hold with that value, every other facet as it is), a value
  that would give nothing DIMMED and never hidden, and an **Include** group at the bottom
  with the same words on every page: Include done, Include backlog, Include archived,
  Include deleted, Include review boards, Include closed, Include dismissed. An include switch ADDS what it names to the list; it never swaps the
  list for it (archived and deleted used to). The desk's panel drops from the button and
  applies live; the phone's is a bottom sheet (80% of the screen, a grabber, the facets
  scrolling, a sticky Clear and "Show N cards").
- **Sort** is a small menu with one tick; **View** holds the layout and the grouping, and
  offers only what works in the layout in force (the kanban IS a grouping by stage, so it
  offers none; the phone has no kanban). A page with no modes has no View button.
- **Views** holds the page's built-in presets (Cards: Needs me, In flight, Shipping,
  Backlog; boards: Mine this week, From houses, From Harbor, Review boards; Reviews: Waiting for me, At my
  gate, New commits, Backlog), the user's own, each with a delete,
  and "Save current view..." with a name field. A view is a saved search, filters, includes
  and sort; the layout is left as the user has it.
- **The token line** starts with a quiet item naming the chosen view and the sort ("Needs
  me · Queue order"), then one removable token per facet and per include switch, then Clear
  all. On the phone it is the one row that may scroll sideways, with a fade on the edge that
  holds more (`K.markStrips` marks `.find-tokens` as it marks `.lanechips`).
- **NOTHING IN A CONTROL IS CLIPPED.** The buttons carry short fixed labels (Views, Filter,
  Sort, View) on the desk and the phone alike: the current choice is never crammed into a
  button, where the mockups showed it cut off at 390. On the phone the search owns the
  first row and the four buttons share the second, each as wide as its label needs, never a
  sideways scroller. Menu items, facet values and suggestions wrap onto a second line; a
  facet value's count is its own box and cannot be overlapped. A token's value is the one
  designed ellipsis, with the whole text in its title and aria-label.
- **The URL and the memory.** The state (`q`, `f` in the typed grammar, `inc`, `sort`, and
  the page's modes such as `layout` and `group`) is in the URL on every route that draws a
  bar, so a view can be sent, bookmarked and walked with Back: a change of filter, sort or
  view pushes history, typing replaces it. `sort` is always written, so a URL with none of
  these says nothing and the page's remembered state is used (`keel.find.<page>` in
  localStorage, in try/catch; the user's own views are `keel.find.<page>.views`). The chosen view
  needs no parameter of its own: it is whichever view the state IS.
- **Accessible as real controls**: the search is a `combobox` over a `listbox`, the buttons
  carry `aria-haspopup` and `aria-expanded`, Sort, View and Views are `role="menu"` with
  `menuitemradio` entries and arrow keys, the panel is a `dialog` (the phone's sheet
  `aria-modal`, Tab kept inside it), facet values are `checkbox`es and include switches
  `switch`es. Escape closes the innermost open thing and hands focus back to its button; a
  click outside closes it.

The engine is `app/ui.findcore.js` (pure, no DOM: the grammar, the URL, the counts, the
views, the memory), every page's table is `app/ui.findpages.js` (its facets, include
switches, sorts, views and modes, in one place so the pages cannot drift), and the bar is
`app/ui.find.js` with its styles in `app/ui.find.css`. A page calls `K.find.run(page,
items)` and draws `K.find.bar(page, found)` over what came back.


A strip says which way it holds more: `K.markStrips` (in `app/ui.core.js`, called at the end
of the render pass and on each strip's own scroll) puts `data-edge` = `start`, `end`, `both`
or `none` on every `.lanechips` and `.find-tokens`, and the stylesheets fade that edge with a
mask. Without it a chip cut flat by the box's edge reads as broken rather than as
scrollable. A strip is clamped to its row (`max-width:100%`) and bleeds by its container's
own `--padx`, never past the border drawn around it.

**How it is held.** `tests/test_find.py` runs the engine and every page's table under node
(`tests/fixtures/find-core.js`: the parser, the URL round trip, multi-select with counts,
Include adding, views saved and deleted, the memory, the suggestions) and the pages that draw
the bar against the deck's DOM stand-in (`tests/fixtures/find-ui.js`). What only a browser
can see is `bin/keel-find-audit`: it serves the deck in its own process against a scratch
board it seeds, opens every surface of the bar (the panel or sheet, Sort, View, Views and its
save form, the suggestions) on Cards, the board list and Reviews at 390x844, 900x800 and 1440x900 with
filters applied, and fails on any control whose text overflows or is cut without its title,
any box reaching past its control, a page wider than the window, more than four type sizes
or two weights in the bar, a length off the 4px grid, or a phone target under 44px
(`tests/fixtures/find-measure.js`). It starts a browser, so it is not part of `make test`;
`--shots <dir>` writes each page at each width with the panel open and with the tokens.

## Artifacts and tokens

The page never sends a filesystem path. It sends a token the server minted: the absolute
path plus an HMAC over it, keyed by `state/artifact.key` (0600, created on first use), and
checked again before a byte is served. A token is minted only for a file under one of the
roots (`state/cards/`, the segments directory, and every `artifact_roots` entry in
the install's `config.toml`) that is not a credential by directory, name or suffix.

`artifact_roots` is a configured list rather than two fixed roots because a card's
`plan_ref` points wherever the tool that wrote the plan put it. Adding a root is a config
change, never a code change.

`artifacts.markdown_html` renders headings, fenced code, lists, rules and paragraphs, and
turns a relative markdown image into an `<img>` and a relative markdown link into an `<a>`
when the path resolves under those same rules against the document's own directory. What
lands in `src` is always a token this server minted, never a string from the document. Anything that
fails renders as its words in a muted span whose title says why. That is how a house's
screenshot, embedded beside `context.md` as `assets/shot.png`, is a picture on a phone,
and it is the same renderer this Atlas page is going through. A clip linked the same way
(`.wav`, `.mp3`, `.m4a`) plays where the user is reading rather than downloading as a blob, which
is what makes work that can only be judged by ear reviewable at all: c-316 is the first of
it, a house speaking in its own voice, where no test can say whether the handoff is heard. A path this renderer will
not serve is deliberately loud rather than silent, so if you see muted words with a
tooltip in a page, that is it saying so.

## The lavish proxy

Anything the deck does not route is streamed to lavish on `lavish_port`. Lavish checks
Origin against its own host, which behind a proxy never matches, so the check moves up one
hop: the deck compares the browser's claimed origin against its own Host and, only on a
match, hands lavish a loopback origin.

Lavish exits about thirty minutes after the last browser and poll disconnect, so a surface
left overnight is a connection refused at exactly the hour it is wanted. A connection
failure on a request **a person makes** (opening a surface, its event channel, answering on
it) starts lavish once, detached, with a twenty second cooldown after a failure and an
honest 503 when it will not come up. A page's own asset or a scanner never wakes it.

A card whose plan lavish still has a session for carries `links.plan_live`, a path on the
deck's own origin (`/session/<key>`), never lavish's loopback URL, because the phone is not
this machine. Open plan prefers it and says "(live)".

### A relayed answer watches its own client

Every proxied answer is pumped to the browser by `serve.relay`, which watches the client's
socket for the whole relay and, when it closes, shuts the upstream socket down so the read
waiting on lavish returns at once.

That watch is not housekeeping. `/events/<key>` is a channel that never ends and lavish can
be quiet on it for minutes, so without it a client that closed its tab is noticed only on the
next write, and until then the handler sits on the browser's socket AND lavish's, until the
read timeout an hour away. Two descriptors per abandoned channel, and the page reopens one
on every poll: `keel serve` runs through the 256 descriptors launchd gives it
in about ten minutes and can then spawn nothing at all, which comes out as `Errno 24`
tracebacks under `harness.agents` (146 of them in the run that showed it). Restarting onto a new commit clears it every time,
which is why it takes a quiet evening to show. Card c-276.

The number itself is now on the state document as `config.descriptors` (`{open, soft}`),
counted by the serve process for itself, and `keel doctor` reads it from there and calls it
a problem past three quarters of the limit. The doctor runs in its own process, where its
own count would say nothing about the deck's.

### The one health verdict (`health`)

The state document carries `health`, `{"level": "green"|"amber"|"red", "reasons": [...]}`,
from `keel/health.py` (added by `serve.with_code_state`). It is the doctor's facts read the
cheap way and folded into one level: a talker fault, a voice gateway installed here and
silent, a drain with no pass in 15 minutes and a backup set with no successful run in 6
hours are red, and so is an expired login a served space's houses run under (`login: <host>
<label> expired`); a talker still starting, a drain quiet over 5 minutes, a nightly pull over 48
hours old, any other row of the Logins list that reads expired or missing, a Claude login
within two days of its 30 days ending, and any fact that could not be read are amber. The verdict reads the Logins rows (below) and never checks one. The reasons are words,
never ages.
A service this machine has not installed is not asked. The serve process rebuilds it at most
once a minute (the idle reading at most once an hour), and nothing pushes it: the deck draws
it. It does not move the state's revision, so a page holding a current state would never see
a new verdict through `/api/state` (it is answered `304`); the page asks `GET /api/health`
once a minute while it is visible, and when it comes back to the front, and draws the newer
of the two.

Beside the verdict rides `services` (F4, `health.services`): one row each for the talker,
voice, the drain and the backup, in that order, with the service's own word for its state
(`serving`, `answering`, `passing` or `quiet`, `last good run` or `last pull`), the level the
verdict gives it, and `at`, the INSTANT its age counts from (the talker's last start, the
moment voice was asked, the drain's last pass, the backup's last good run or pull), never an
age, so the page ages it on its own clock between readings. A service this machine does not
run says `not installed here` or `not set up here` at level `off`, with no instant.

The deck draws both in two places. **The drain pill's dot**: the pill in the header keeps
its drain word, and its dot IS the verdict's colour (`drainPill` in `app/ui.core.js`); its
name is the verdict and its reasons in words, then the drain word. It was a separate 44px dot
in a box beside the pill for one round, and on a 390px phone that drew two red dots saying
one thing and squeezed the space name to "Pers...": merged, "Personal" and "Work" read in
full (lane F review, re-shot). Without a verdict yet the dot says the drain's liveness as it
always did. A tap on the pill opens the **services sheet**: "Shipyard is red", the reasons, then the
services block. **Now** carries the same block as its own panel, between the houses and At a
glance, so the talker being down is on the home route rather than found out when the app's
Code tab is empty (c-444).

### The Logins list (`health.logins`, c-558)

Beside `services` rides `logins`: one row per credential Keel depends on, from
`keel/logins.py`, which [the drain](30-drain.md) keeps current. It builds this machine's
rows (its Claude config dirs, Drive, the voice keys, an adapter's). A row is `{id, host,
label, where, state, why, at, expires, ending, houses, fix, good_at, marked, unverified}`;
`state` is `good`, `expired`, `missing`, `unknown` or (a voice key never set, which is not
red) `unset`, `unverified` a red that rests only on a mark no check has settled yet (an
`unknown` answer settles none) and that is under two `RED_EVERY` periods old, `at`
the instant it was last checked (or marked), `expires` when a Claude login's 30 days end,
and `fix` the one-liner that logs it back in (`CLAUDE_CONFIG_DIR=<dir> claude auth login`
for a dir that is not the default profile). A Claude row also carries `spaces`, the spaces
that run under its dir, and `stamp`, when the sign-in file there last changed (c-678).

The same block (`K.loginsBlock` in `app/ui.core.js`, so the Console draws it too) sits in
three places: under the services on the **services sheet**, as its own **Logins** panel on
**Now** after Services, and on the Bosun page's Now. Its label carries a red count badge
when any row is red. Red rows sort first, each with its one-liner and a **Copy** button
(`K.copyButton`): the command goes on the clipboard and nothing types it anywhere. A red
Claude row's fix is the guided sign-in instead (c-678, `K.signIn.again`): **Sign in again**
opens the four lines with that row's command and the live status. Its Check again and its
watch probe the first space of `spaces`; a dir no space runs under (the talker's) has
neither, and says Keel's own upkeep checks it. The Console, which does not load
`app/ui.signin.js`, keeps the one-liner. A red row
also raises a login ask on the Console ([the drain](30-drain.md), `keel/loginask.py`), whose
card shows the same one-liner with its own Copy button.

The space banner (`loginBanner`, above) stays: it is the one line that says a whole space's houses are
blocked.

### The phone layer the proxy injects

Lavish is vendored upstream and its conversation panel has no collapse of its own. At
lavish's own phone breakpoint (860px) the panel takes `min(42vh, 360px)` of an 844px screen,
so a plan opened full screen on the phone gets a little over half of it, with the "Your agent
is not listening" bubble and a message box underneath. Every lavish page the user sees goes through
this proxy, which is the one place a layer can be added at all.

`keel/lavishlayer.py` puts two tags before `</head>` of a proxied HTML answer: a link and a
script pointing at `/deck/lavish-phone.css` and `/deck/lavish-phone.js`, which the deck
serves from `app/` (`serve.APP_FILES`). The prefix is `/deck/`, which lavish claims nothing
under; a new deck route is a name taken away from lavish permanently, so the layer takes one
prefix rather than two names. The deck's own page never loads either file, so neither is in
the service worker's `SHELL` list, for the same reason the two themes are not.

THE INJECTION FAILS OPEN. A body that is not `text/html`, is over 4MB, is missing any element
the layer manipulates, or already carries the layer comes back byte for byte. `/events/<key>`
is refused by path before the content type is even read: it is a channel that never ends, and
reading it whole would hang the request watching the plan. Everything else still streams.
This is the page an attended plan gets approved on, so a lavish that has moved on renders
unchanged rather than half styled.

What the layer does, under 860px and nowhere else:

- The plan takes the viewport. The panel comes out of lavish's grid and the plan keeps the
  row that is left, with `44px + env(safe-area-inset-bottom)` of bottom padding so the bar
  does not clip it.
- The conversation is a 44px bar pinned at the bottom, reading `Conversation` plus the queued
  prompt count when there is one, with a chevron. It carries the safe area itself, and the
  44px is content box, so the thumb target is 44px whatever the inset is.
- Tapping the bar opens the panel as a sheet over the plan, never taller than 60% of the
  viewport and scrolling inside itself. Tapping the bar or the plan closes it. A click inside
  the artifact's iframe never reaches this document, so the sheet's own scrim is what hears
  the tap on the plan; it covers the plan only, so lavish's Annotate switch stays reachable,
  and with the sheet CLOSED there is no scrim at all, which is what leaves element annotation
  exactly as it was.
- Closed is the state on every load. A conversation left open is not what the user opened the plan
  to look at, and the bar is one tap away.
- While lavish says the agent is not listening the bar says `Not listening` in one line (no
  count beside it: the bar is 44px and is reporting that nothing is reading the queue), and
  the sheet keeps lavish's own banner but swaps the message box and Send for one sentence,
  "Send back from the deck to resume the house." When lavish is listening they are both back.

Nothing of lavish's is renamed and no listener is added to anything of lavish's: the layer
reads lavish's elements, appends two of its own (all prefixed `keel-`) and sets two data
attributes on the body. The names it stands on are declared once, in
`lavishlayer.SELECTORS`, which is both the injection's marker list and the subject of
`tests/test_lavishlayer.py`'s guard: the guard reads the vendored bundle (the newest
`lavish-axi` under the npx cache, 0.1.36 when this was written) and fails by name on a
selector lavish has renamed, because nothing else would. A rename does not error, it simply
stops matching, and the panel takes half the user's screen again in silence.

## The page

Seven script modules in load order, sharing `window.Keel`, plus the Atlas and Board
modules:
`ui.core.js` (state, helpers, THE MORPH, the state document, the event stream, routing,
the pane frame, the rail, header, controls, dock and the chip strips' edge), `ui.findcore.js`,
`ui.findpages.js` and `ui.find.js` (the find bar: its engine, every page's table, the bar),
`ui.leave.js` (the question a view with something unsaved asks before a move, and the walk back onto its entry when Back or Forward is refused, c-661), `ui.modal.js`
(the card dialog), `ui.receipt.js` (a gate's receipt, c-537), `ui.shipping.js` (a shipping card's standing batch, its row and Ship drawn for the pane and the comments page, and Talk, c-600, c-643), `ui.shipsendback.js` (Send back at shipping, c-663: its button, its box and what the user sent that still waits, for the pane and the comments page), `ui.landpush.js` (the Push on a card that landed by a merge on this computer, c-678: `K.pushBlock`, [flows](64-flows.md)), `ui.stuckcard.js` (the stuck states outside setup, c-678: a blocked card's reading, the services, an unknown config key, [onboarding](89-onboarding.md)), `ui.comments.js` (the review comments page, c-643), `ui.cards.js` (the list, the
kanban, the inspector), `ui.views.js` (Now, Attention, Segments, More), `ui.reviews.js`
(Reviews, the review cards and the fetcher's two settings behind a gear), `ui.atlas.js`
(this documentation), `ui.boardlayout.js` (which of two diagram layouts is drawn, and why),
`ui.board.js` (the blackboard: the line language parsed again for
rendering, one model per board, the ELK diagram, pan and zoom, and the three views),
`ui.boardlist.js` (the board list: grouped by card and by topic, the search behind the find bar),
`ui.boardfull.js` (the full-screen board), `ui.boardcallout.js` (the walk's step as a callout
from its lit node, and the arrows and Escape), `ui.boarddelete.js` (deleting a board: the
header, row and stack menus, the confirm that names where it is embedded, the Deleted chip's
trash with Restore) and `ui.js` (the boot, the one
render pass and the fallback poll). Every one of them is
in `serve.APP_FILES` and in the service worker's shell list.

### The page changes rather than reloads

Every five seconds `K.load()` fetched the state and `render()` rebuilt everything: `#body`
was emptied and built again, and so were the rail, the header, the controls and the dock.
Everything the DOM held went with it each pass (scroll offsets, focus, selection, a CSS
transition part way through, an SVG's transform, an open `<details>`), and each kind had
a patch putting it back afterwards. That is what "the page looks reloaded" was.

The render pass MORPHS now. `K.morph(live, next)` in `app/ui.core.js` is about 120 lines
and walks the freshly built tree against the live one, writing only the difference:

- A child is matched by `data-key` when it has one and by position and tag when it does
  not. A keyed row that MOVED is the same node in its new place; a row that went is
  removed and one that arrived is inserted, and nothing between them is touched. Rows,
  tiles, lanes, attachments, chips, pane sections and grid pairs all carry keys.
- Handlers are carried from the new node onto the kept one on every pass. `K.el` assigns
  them as PROPERTIES (`node.onclick`) rather than through `addEventListener` precisely so
  they can be: a listener added that way cannot be read back off a node, and a kept node
  still holding last pass's closure would act on last pass's card. A listener attached
  imperatively (a tile's dragstart, a strip's own scroll) stays on the live node and is
  never re-attached, so what such a closure captures has to be stable for that node's key.
- `value`, `checked`, `selected` and `open` are written only when the new tree names them
  AND the element is not the one the user is typing in. What is half typed is the user's.
- A subtree marked `data-morph="skip"` is left whole, the node's own attributes as well
  as its children, and only its handlers are carried. The board's diagram stage is the one
  that uses it: ELK lays that graph out and the user's finger pans and zooms it, and neither
  belongs to a render pass. There is no condition on it, because the pass builds that node
  EMPTY: a pass that decided to morph it after all would delete the diagram and leave a
  blank stage. Whoever draws into a skip subtree owns keeping it current, which for the
  board is `stageHost` off the model's own version.
- An UNKEYED child takes the next unkeyed old node by ordinal and spends that slot whether
  or not the tag matched, so a tag that flips in one slot (the `panel-head` whose first
  child is a button on the phone and a span elsewhere) does not slide every sibling after
  it onto its neighbour's node. A genuine insert in the middle of an unkeyed list rebuilds
  the tail under that rule, which is what `data-key` is for.

The live node never leaves the document, so the scroll offsets, the caret, the selection,
a transition mid-flight, the graph's transform and ELK's layout all survive by
construction. FIVE PATCHES WENT WITH IT: the sessionStorage scroll map over every
`data-sk` scroller and its apply-after-every-pass, `focusMark`/`focusRestore`, the pane's
node cache, the `setTimeout(renderBody, 200)` the board used to retry an ELK layout, and
the `scrollIntoView` that slid the phone's stage strip under the user on every pass (it ran
once, when a route was entered, until the strip itself went with the find bar).

Two things are kept, and each is kept because the morph cannot cover it:

- **One scroll number per route**, in sessionStorage, read back ONLY on the pass that
  enters a route (`K.enterRoute`). The morph covers a redraw; it cannot cover a real
  reload, where the DOM is gone, or a Back into a route whose body it has just replaced.
  A poll never touches it, which is what the five second jump to the top used to be.
- **`K.keepFlag`**, the pane's expanded state, for the reason given above.

`tests/fixtures/deck-morph.js` runs the morph under node against a DOM stand-in: a text
change, an attribute added and removed, a keyed reorder keeping the same nodes, an unkeyed
insert, a removal, a skip with an unchanged hash, the handler carry-over, and a focused
field's value not being clobbered. `tests/test_deck_css.py` holds that the page actually
goes through it and that the patches did not come back.

### The live channel

`GET /api/events` is a server-sent event stream, and the page opens exactly one while the
tab is visible. One event per line:

```
state <rev>          the state document moved
card <c-id> <rev>    that card gained an event or was written to
board <b-id> <line>  that board's ops.log reached that many lines
tick <step>          fifteen seconds passed and nothing else did
live <c-id> <json>   what that card's house is doing now, or null (the live strip)
ping                 nothing happened; the channel is still here
```

The page fetches only what an event NAMES: `state` refetches with its ETag, `card` only
when that card's pane is open, `board` only when that board is open, `live` carries its
facts and fetches nothing ("The live strip" above), and everything else is a line read and
dropped. Opening the stream is also what starts the live strip's reads.

**`tick` is the clock, said on its own** (2026-09-21). `Deck.rev` carries a coarse fifteen
second term so that an idle deck still refreshes the two inputs that are neither a write nor
the board (the drain log, the usage tee). The sweep published that as `state`, and the page
answers `state` with a whole `/api/state` fetch: a deck nobody was touching refetched the
document four times a minute to move some ages by fifteen seconds, and the test that says a
quiet sweep is silent failed one run in five, on nothing but where the wall clock happened to
be. The sweep reads `Deck.rev_parts()` now and tells the two apart: what was WRITTEN is a
`state`, the clock alone is a `tick`, and the page answers a tick by re-rendering what it
already holds (`K.render`, and the morph writes only the age strings that moved). A `state`
carries the new clock with it, so the page is never told both about one step. `rev` itself is
unchanged and is still the only thing that names a revision, which is what keeps the stream's
line and the route's ETag the same function.

**A sweep may say a half-way `state` first, and that is not a bug** (c-545). A sweep can
read the board's stamp after a write commits and before the action's own count moves, and
say `state 0.X` just ahead of the publisher's `1.X`; the page fetches, then hears `1.X`,
and ends where the route is. So the tests read signals, never moments: every revision
test holds the clock (`held_clock` in `tests/test_serve.py`), the route-and-stream test
waits for the line the publisher named, and the swallow test steps the clock in the same
`rev_parts` reading that first sees the write. Each had been red on a loaded box (r-22).

The five second poll is the FALLBACK, running only while the
stream is shut (a reconnect in flight with backoff, or a browser with no `EventSource`). The board's own five second poll is the same: a node a house draws while it is
speaking lands as it is written rather than up to five seconds later.

Two things feed the stream, and each covers what the other cannot (`keel/deckevents.py`).
The writers publish: every place that drops the state cache, appends a card event or folds
a board push calls the hub, so a write made in the serve process reaches the page as it
lands. And the thread holding each stream open sweeps four times a second for the two
numbers another PROCESS could have moved: the deck's revision (a stat on the board file)
and the size of the one board that page has open, named in `?board=`. That is what has a
`keel board push` from a house's shell reach the user's phone in well under a second. The hub
holds no lock a writer needs, a subscriber too far behind to read is dropped rather than
allowed to wedge the writer that found it, and the cap is eight, oldest first.

## While an action is in flight

Answering a gate is not instant: the resume starts a session, waits for the harness to
list it, polls for the app link and stops the session it superseded, which is five to
fifteen seconds. Until that answer lands the page used to say nothing at all, and nothing
on success either, so a tap looked like nothing happening. It says it in five ways now,
all of them driven from `app/ui.core.js`:

- **The pressed button is the indicator.** Every action goes through one wrapper, which
  takes the element that was pressed (or, with none, the pending key of the verb and the
  card). While the request is in flight that button carries the progress verb (Approving…,
  Sending back…, Starting…, Splitting…, Stopping…, Scanning…, and "Working…" for anything
  with no word of its own) and breathes, and every other button on the same card or row is
  disabled, so a second tap cannot fire the same action twice. It covers the gate answers,
  Resume house, Retry, Unblock only, End discussion, Split, Drop in, Stop, Assign, Archive, the
  backlog controls, Create and Save in the dialog, the adapter's card and row verbs, the
  Reviews settings, and a tile dragged onto a lane (there the tile breathes, since a drag has no
  button to press).
- **Pending survives a redraw.** What is in flight is page state keyed by the VERB and the
  CARD (an adapter verb by its route, its action and the row key), never by a DOM node, so
  a state that lands mid-flight repaints the button still pending. The key is cleared when
  the response arrives, success or error.
- **Every answer says one sentence**, read from the result rather than from the button:
  "plan approved, house resumed", or the result's `note` when nothing was resumed; "sent
  back, house resumed", and "sent back and staying" with `stay`; the message
  `end_discussion` came back with; "fresh house started"; the ids a split made; an adapter
  verb's own first line; and "done" for anything with nothing better to say. A refusal
  keeps the red toast it always had. A caller that has already answered on screen (the logs
  sheet, the drop-in command, a surface opened in a tab) says nothing on top of it. Once the
  server has answered ok, a failure after it is the page's own redraw, and the toast says
  the action's sentence and that the page did not redraw, never "the action did not reach
  the server" (c-601: a Create that landed said it had not).
- **A bridge covers the gap until the board catches up.** The server answers as soon as the
  harness LISTS the new session, which is before it is busy, so the next state document
  would still say idle and the card would look untouched. After a gate answer, a Resume or
  a Retry, the card's house word says "resuming the house…" (or "starting the house…")
  instead, which puts it on the row, the card head and the Now tile at once, and the state
  is fetched once three seconds later rather than waiting on the next event. It ends
  on the first state that shows the house busy or a session that is not the one it opened
  on, and after thirty seconds regardless, so a house that never started does not claim to
  be starting forever.
- **The header pulses** while anything at all is in flight: the drain pill's dot takes the
  accent and breathes, so on a phone, where the sheet that carried the button may have
  closed behind it, something visible is still moving.

The pulse is opacity and colour, never a spinner glyph: the page loads no icon font, and
the type budget stays four sizes and two weights. The confirm() dialogs are unchanged.

Density is `?d=glance|work|deep`, which changes only the padding and the grid. The palette
follows the space. The page names no employer: every such label comes from the adapter at
runtime.

## The icons

Every icon Keel installs or draws comes from five glyphs the user picked on the canvas (c-518,
board "Icons: round 2"), kept exactly as they were picked in `app/icons/src/`: `keel.svg`
(the hull and fin), `harbor.svg` (the lighthouse), `voice.svg` (the lighthouse with sound
arcs), `bosun.svg` (the raised boatswain's call) and `bosun-small.svg` (the call without its
ring, for 24px and below). Each is a 64 grid in `currentColor`; the lighthouse's band is drawn
in its navy ground.

**A tile outside, no tile inside.** An installed app's icon is the mark on its ground. In
the app a mark has no tile (the user's call when the tiles read as a mismatch on the deck): the
page paints a bare glyph, `app/icons/<mark>-glyph.svg`, in its own palette through a CSS
mask. The header's hull and fin and Harbor's name beside them take the accent, the Voice button
takes its ink like the icons beside it. The bare glyph turns the navy band into a real hole
(an SVG mask), so it reads on any page.

| Mark | Glyph | Ground | Installs as |
|---|---|---|---|
| Keel | #5BD6C0 | #101418 | the deck, `app/manifest.json` |
| Harbor | #F2C879 | #0E1726 | nothing in Keel: Harbor's name in the voice app |
| Voice | #F2C879 | #0E1726 | the voice app, `segments/voice/app/manifest.webmanifest` |
| Bosun | #A59BFF | #0B0B0C | the console, `app/console.webmanifest`, scoped to `/console` |

`python3 app/icons/build.py` derives everything else and is the only way anything else
changes: the rounded tile (radius 14 of 64), the maskable tile (full bleed, the glyph at
70% so it sits inside the 80% safe circle), PNGs at 192 and 512 of each, the 180px Apple
touch icon (full bleed, not maskable, because iOS rounds it itself), a 32px PNG, and an
`.ico` holding a 16 and a 32, whose 16 is `bosun-small` for Bosun, and each bare glyph. The PNGs are committed:
the server is stdlib-only and has no rasteriser. `bin/keel-browser` draws each tile onto a
canvas in one run, which keeps a rounded tile's corners transparent where a screenshot
would paint them white. Voice's files keep the names its page and manifest already used;
its old `build.sh`, which called Harbor's browser, is gone.

The deck serves them from `serve.APP_FILES`: `/icons/<name>` for each name in
`serve.ICONS`, `/favicon.ico` (Keel's; it was a 204; served as `image/vnd.microsoft.icon` on every OS, since
`serve.py` pins the type where macOS's table says `image/x-icon`, c-635)
and `/console.webmanifest`. The shell cache (`app/sw.js`) holds the ones the deck's own page
draws, and Bosun's, since the Console registers the same worker (c-540). An installed app keeps the icon it was installed with until it is added again.
`tests/test_icons.py` holds the tiles and bare glyphs to what the build derives, no in-app mark to a tile, every manifest icon to a
file of the size it claims, and every served icon to a file on disk.

## Where it lives

- `keel/serve.py`: the routes, the static files, the segment apps, the lavish proxy, and
  the hand-off of the voice and lavish requests.
- `keel/voicetier.py`: the `/voice/` routes, mixed into the request handler.
- `keel/deckstate.py`: the state document, one card's detail, and the two revisions the
  page's ETags carry.
- `keel/deckevents.py`: the event hub behind `/api/events`: who is subscribed, what a
  writer publishes, the cap and the depth.
- `keel/livestrip.py`, `keel/livetail.py`, `app/ui.live.js`: the live strip, from the
  harness's files to the line on the card (above).
- `keel/housemem.py`, `keel/idleclose.py`, `app/ui.idle.js`: what a live house holds, Now's
  idle houses and Close idle house (c-607).
- `keel/actions.py`: every deck verb.
- `keel/openapp.py`: Resume and open in app, the house back with no turn and its current link.
- `keel/deckauth.py`: who may act as the user: the page's cookie, the browser's same-origin word,
  and the origin rules the routes share.
- `keel/artifacts.py`: tokens, the roots, the denylist, the markdown renderer, the lavish
  surface lookup, and `local_path`, which reads a relative `plan_ref` against the Keel home
  rather than the cwd (c-574).
- `keel/lavishlayer.py`: the phone layer injected into a proxied lavish page, and the
  lavish selectors it stands on.
- `keel/atlas.py`: this documentation's page list and one rendered page.
- `keel/boards.py`: the blackboard's grammar, store and index ([the board](45-board.md)).
- `keel/boardfiles.py`, `keel/boardask.py`: a board's files both ways, and its ask box.
- `keel/boardpen.py`: a ```board block lifted out of an answer, for a house and for Harbor.
- `app/ui.findcore.js`, `app/ui.findpages.js`, `app/ui.find.js`, `app/ui.find.css`: the
  find bar (above).
- `bin/keel-find-audit`, `tests/fixtures/find-measure.js`: the find bar measured in a real
  browser on the real pages.
- `app/icons/`: the picked glyphs in `src/`, `build.py`, and what it derives (above).
- `app/`: `index.html`, `ui.css`, `manifest.json`, `sw.js` and the script modules, plus
  `app/theme-work.css` and `app/theme-personal.css`, which mirror `ui.css`'s two palette
  blocks for the surfaces houses write. A colour changed in one is changed in both, and
  `tests/test_theme.py` fails when it is not.
- `<install>/history/docs/deck-shots/`: the render evidence, and `<install>/history/tests/live_deck.md` the audit behind it.

## How to change it

- A new route: `keel new view <key>` (c-634). It adds one row to `app/views.json` and
  writes `app/ui.<key>.js` with the view's render function, and nothing else is edited: the
  rail, the dock, the body's dispatch (the row's `render` called with its `arg`, in `app/ui.js`), the page's script
  tags, the worker's shell and the served files are all drawn from that manifest
  (`keel/deckviews.py`). Name its readiness rows in the row's `needs`. Add it to the table
  above. [Extending Shipyard](63-extending.md) has the row's keys and the rules.
- A list that needs finding: a table in `app/ui.findpages.js` (facets, include switches with
  the same "Include ..." words, sorts, views, modes), `K.find.route(view, page)` when its
  route is not already in `ui.find.js`'s `ROUTES`, and `K.find.run` then `K.find.bar` in its
  view. Never a chip row of its own. Run `bin/keel-find-audit` with the page added to its
  `PAGES`.
- A new verb: `keel/actions.py`, a test in `tests/test_serve.py` proving it reaches its `kb`
  command with the token, and a line here. Give it a progress word and a sentence in
  `app/ui.core.js` too, or the deck says "Working…" and then "done" for it.
- A new script file the deck's page loads: its name in `app/views.json`'s `scripts`, in
  load order, and nothing else. The server writes the page's script tags at the
  `<!-- keel:views -->` mark in `app/index.html`, fills the `var DECK` line of `app/sw.js`
  with the scripts and a hash of the manifest (so the worker's cache name moves by itself),
  and serves every listed script (`deckviews.served`). A script of another page
  (`app/console.html`, `app/plan.html`) goes into `serve.APP_FILES`, `app/sw.js`'s own list
  (bump its `v`) and that page. The worker is network first, which costs a `304` per file
  now that app files revalidate; both pages register it. A file the deck's own page does NOT
  load (the two themes, the lavish phone layer) goes into `APP_FILES` alone, never into
  `SHELL`.
- A palette change: `app/ui.css` AND both `app/theme-*.css` files, in the same commit. The
  page's own palette is the one on `html[data-mode="..."]`; the themes carry a copy because
  a plan has to render standing alone. The theme files are deliberately NOT in the service
  worker's `SHELL` list: the page never loads them.
- A PHONE change is shaped before it is styled: `~/.claude/skills/mobile-first-design`
  decides the navigation, the sections and the four sizes / two weights / 4px grid / 44px
  budgets, and it is read before the CSS rather than during it.
- Any HTML or CSS change is verified by rendering it: `bin/keel-browser shot` at 1440x900
  ([the browser tool](20-houses.md)), and a REAL phone context at 390x844 (`playwright-core`
  with `deviceScaleFactor 3`,
  `isMobile` and `hasTouch`, which `--width 390` alone is not), then the contrast, overflow
  and 44px tap audit recorded in `<install>/history/tests/live_deck.md`. Screenshots land in
  `<install>/history/docs/deck-shots/`, the phone sweep in `<install>/history/docs/deck-shots/mobile/`.
- The overflow half of that audit measures THREE things, because two of them passed while
  the surface was broken (`<install>/history/docs/deck-mobile-audit.md`): the document's `scrollWidth`, the
  `#body` scroller's own `scrollWidth` (which is what actually drags the reader sideways),
  and whether every element that DRAWS a border contains what is inside it. On the phone the
  page is the scroller, so `.panel.grow` must not take the viewport's height, which only
  this sweep can see: no stdlib test lays out CSS.
