# Segments

A segment is an area of life Keel looks after. It is a directory, discovered by globbing,
so adding one needs no change to Keel itself.

    segments/<name>/
      segment.md      frontmatter Keel checks (below), then what it is and may do unasked
      fetch.py        pulls on a schedule, writes data/ and summary.json
      test_fetch.py   its own test: `python3 segments/<name>/test_fetch.py`
      summary.json    the tiles this segment adds to the deck. UNTRACKED, like data/
      app/            optional: static files served at /segments/<name>/app/
      service.json    optional: a long-running service in place of a fetcher (voice)
      worker.md       optional: this segment may ask for a model. See below.
      data/           untracked

That is everything Keel reads. Some segments carry other files of their own (an old
`card.html` or `brief.py`); Keel reads neither.

`segment.md` starts with frontmatter that `keel/segmentspec.py` checks, and `keel doctor`
prints a line for each problem (the fetch role still runs a segment that fails):

    ---
    name: daybook         the directory's own name
    space: personal       a space this config has
    cadence: hourly       hourly, daily or none
    card-span: 2          optional: how many deck columns its tile spans, 1 to 4
    logins: google-tts    optional: the login rows a refused key marks (keel/logins.py)
    ---

`keel new segment <name>` writes a checked starting point: `segment.md`, a stdlib
`fetch.py` that writes one tile, and the `test_fetch.py` that runs it.

[The Atlas page](../docs/atlas/70-segments-and-fetch.md) is the source of truth for how
the fetch role runs all this, and [Extending Shipyard](../docs/atlas/63-extending.md) gives
the rules for a new one. This file is the contract for the inside of a segment.

Generated output is never repo content. `data/`, `inbox/` and `summary.json` are all
rewritten by every fetcher run, so tracking any of them leaves the checkout dirty on a
schedule. That is not theoretical: in the system before this one, on 2026-08-01, an
approved queue entry ran the self-extension tool, hit a tree dirtied only by two
regenerated `summary.json` files, and never ran. A fresh clone therefore has no
`summary.json` until a fetcher runs, and every reader already treats that as an empty
overview rather than an error.

Only `segment.md`, a fetcher, and something to look at are needed. The rest is how a
segment grows from a dashboard into something that actually helps.

## Two rules

**The app never touches the network.** Fetchers write files on a schedule; the app reads
them. That keeps the surface fast, keeps it working offline, and keeps secrets out of the
page. A segment app is static files and nothing else, so it can be written by anyone and
reviewed by reading it.

**Reading is free, writing outward is not.** Display, data, and briefing lines can be
built and changed unattended. The moment a segment wants to write somewhere outside
itself, post to a service, send a message, touch an account, that is authority rather
than capability, and it needs a human decision first.

`space` decides which credentials a segment's tools load under. A personal segment's
tools must never be available inside a work session.

## When a segment needs a model: `worker.md`

Some things a segment wants are not arithmetic. Turning a rambled explanation into a
structured note is the example that forced this; no amount of Python in `fetch.py` will
do it.

The answer is NOT to let `fetch.py` call one. That fetcher has no network, no subprocess
and no credentials on purpose, and the reason is in `instamart/segment.md`: an early
version started a credentialed Gmail session from a cron script, with no record of it,
from a cwd picked so a deny would not apply. A scheduled reduce must never be an authority
question.

So the capability sits one level up, in the fetch role, where it becomes an ordinary card
that can be counted, capped and seen:

    fetch.py        writes an ASK into data/asks/. Deterministic code writing a file.
    keel fetch      drains asks into ONE autonomous errand card per segment per pass.
    fetch.py        folds the answer back in on the next pass.

The segment never spawns anything, and the card never decides what an ask means. Opt in by
writing `worker.md`; a segment without one never causes a session to be started, whatever
happens to be sitting in its `data/asks/`.

`worker.md` gates SPENDING, and nothing else. The fetch role also re-runs every segment's
`fetch.py` every sixty seconds, gated on something having actually changed, whether or not
that segment declares a worker. That is the same deterministic script the hourly pass
runs, run sooner, so an upload lands on the screen in a minute. It used to be gated on
`worker.md` too, which is how an invoice uploaded to instamart at 16:28 on 2026-08-07 sat
in its inbox until 16:44.

    ---
    space: personal
    daily_cap: 20
    timeout: 900
    tools: Read,Write,Edit
    ---

`space` picks the profile the card's house loads. `daily_cap` is cards per day for this
segment. `timeout` is validated and recorded, never enforced: nothing automatic ends a
live session. `tools` is the allowlist: narrow it, never widen it. A trailing `# comment`
is stripped, but the value itself must be a bare number where a number is expected, and a
segment whose `daily_cap` is not one refuses to run rather than running uncapped.

Everything below the frontmatter is the standing brief prepended to every run: what this
segment's asks mean, and what shape the answer must take.

An ask is `data/asks/ask-<id>.json`. Everything in it is the segment's own business.

**The answer comes back as a journal drop**, written into `data/inbox/` in the same shape
the segment's app posts, never into `data/` directly. That keeps `data/` with exactly one
writer, and it means model output arrives through the same door as input from a phone and
gets the same validation a fetcher already applies to something it did not author.

**Rules the fetch role enforces so a segment does not have to:** an ask is consumed
exactly once (moved into `data/asks/taken/` before the card exists, so a house that dies
cannot have it re-run), a card may never author an ask (that loop would run forever), and
a spent cap pauses work rather than discarding it.
