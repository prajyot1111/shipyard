# The demo video

The Shipyard demo is a 5 minute 40 second film of a day with Keel, rebuilt from nothing by
one command. It is recorded on a sandbox Keel with its own board, and nothing in it touches
the live board. The sandbox, its seeded day and the recorder are on
[the work adapter](60-work-adapter.md) page ("The sandbox", "The seeded day", "Recording the
scenes"). This page is the whole chain, and the edit in detail.

**The edit and the music are not in the public release** (c-804). `.gitattributes` marks
`demo/video/` and `demo/music/` `export-ignore`, so the release, a `git archive` of the
code, leaves them out while this repo keeps them. In that tree `demo/build` refuses at
once ("demo/video is not in this tree"), before a sandbox is made (`--dry-run` still says
what would run), and the tests of the edit and the music skip (below). The sandbox, the
seeded day and the scenes ship as they are.

## The chain

`demo/build --out <dir> --voice <dir>` runs four steps. Each is also a tool of its own:

1. **Setup.** `demo/sandbox/setup` builds `~/keel-sandbox` (or `--home`), unless one is there.
2. **Seed and record, as one day.** Only on a sandbox with no kept take yet, because the day
   is played once, in order. The build starts the sandbox's deck (`keel serve`), drain
   (`keel drain`) and Harbor (`demo/scenes/harbor gateway --fresh`), all under
   `demo/sandbox/run`, and stops each by the pid it started. It makes the user's four lines
   mic-ready, then plays the day:
   - the morning seed, then scenes 1 to 3;
   - scene 4, which files the export card on the deck; the build finds the card's id;
   - scene 5 once the card is at its plan gate, and scene 6 while it builds;
   - scenes 7 and 8 once it is at its outcome gate;
   - the breaks seed and scene 9, then the evening seed and scenes 10 and 11.

   A voice scene's answers are captured and swept before its take can be kept. A scene that
   is not live gets up to three takes; a live one gets one. A sandbox with some takes kept
   and others not is refused: finish it with `demo/scenes/record`, or build a fresh one.
   Every seed writes the day's version (`DAY_VERSION` in `demo/seeding/day.py`, 2 since
   c-807's parallel day) into `recordings/index.json` as `day`, and the recorder notes it on
   each new take (a resweep keeps the take's own). **Takes recorded before c-807 must be
   recorded again:** prepare refuses a kept take whose `day` is not the cut's `DAY`
   (`demo/video/src/cut.js`, which a test holds equal to the seed's), with "recorded before
   c-807's parallel day; record the day again", since the film's chips (api #14, web #33),
   its trace (fix card c-9218) and short-01's board are that day's.
3. **Edit.** `demo/video/prepare.mjs`, then `demo/video/render.mjs` (below).
4. **Evidence.** `demo/video/evidence.mjs` measures the MP4 it just wrote.

`--edit-only` runs steps 3 and 4 from the takes already kept, which is how a change to the
cut is seen. `--dry-run` prints every command and runs none. `--cut <name>` picks what steps 3 and 4 make:
`film` (the default) or a short (below), passed to prepare, render and evidence alike; the
build checks the name against the cuts it knows (`CUTS`) before anything is set up.

## The edit: `demo/video/`

A Remotion project, the one node project in this repo (decided on c-568's plan). Its
`node_modules/`, `public/` and `out/` are ignored; `package-lock.json` pins Remotion 4.0.529,
and `demo/build` runs `npm ci` when `node_modules/` is missing. Remotion brings its own
Chromium and its own ffmpeg, so nothing is installed on the machine.

**The cut is data** (`demo/video/src/cut.js`). Each scene is a list of shots on its own
clock, and nothing in it is a pixel of a recording:

- a shot shows a still by its step label, or a slice of the take's clip between two labels;
- its camera names the element it looks at by the name the scene's steps file gave it, and
  `focus` blurs and dims everything else;
- a time is seconds, or a word of a voice: `{voice: "harbor", word: "drain"}`;
- overlays and captions key to the same clock and the same names.

So a retake moves every push-in, flight and ripple with it. The two places where the steps
file named nothing are built from named boxes, never pixels: `{rows: name, count, pitch, each}`
for Bosun's Journal rows (with `each`, the step's page text must hold exactly `count` lines
matching it, so a retake whose Journal gained a row fails prepare), and `{cross: [column, row]}` for the new card's house cell. The
one `region` is scene 8's last shot, the page under its header, which carries a restart
pill the film must not show; a region camera covers the frame with it, so nothing outside
it is in view. A shot's `crop` shows only its box (scene 9 shows only the Journal rows it
traces). `demo/video/test/` checks both at every frame.

**Prepare** (`node prepare.mjs --recordings <dir> --voice <dir>`) resolves the cut against
each scene's kept take (`recordings/index.json`) into `public/edl.json`. It FAILS on a kept
take of another day (above), and, naming the scene, the step and the name, when a name has no box at that step, when the camera would
look at an element scrolled off the page, when a clip is shorter than its shot, or when the
shots leave a gap. It copies each kept still (2x) with a quarter-size copy for the blur, and
the clip, and redoes a copy only when its source is another file or has changed
(`demo/video/tools/cache.mjs`, so keeping an older take again recopies it). It cleans the audio, with the tools in `demo/video/tools/`:

- the user's lines: 150 ms of lead-in, a light spectral gate (the noise profile is the quietest
  tenth of the frames, and a bin is never cut below 30%), a short fade in and out, then
  ffmpeg's `loudnorm` to -16 LUFS;
- Harbor's captured answers: `loudnorm` to -16 LUFS;
- each voice's words are timed without a recogniser: spread by length over the speech, with
  every clause break pulled onto a real pause (`tools/words.mjs`).

The bundled ffmpeg has no denoise, no fade and no `ebur128`, which is why the gate and a
BS.1770 meter (`tools/audio.mjs`) are Node.

**The motion** is React over the stills: `src/Stage.jsx` (the shots, the camera, the blur
and dim), `src/camera.js`, `src/overlays.jsx` (titles, captions, the orb and the user's words, and
each MOTION item of the script), all on the one ease in `src/ease.js`. `view(scene, t)`
answers where any named element is on screen at any moment, so a word flying to a card or
a ripple leaving Approve lands on the element.

**The mix** (`src/mix.js`, `src/Mix.jsx`). The music bed is levelled to -16 LUFS like the
voices, then set per frame from the cut: -23 dB under any voice (the ask is 15; the bed is true stereo, so it measures louder than its mono fold), -13 in a
scene, -10 across a scene change, -8 on the titles, 400 ms down into a voice and 700 ms back up, and a fade over the
last 1.4 s. The track plays from its start, then an eight second crossfade picks it up again
at 30 s. The music and its licence are `demo/music/` (CC0, credited in its `CREDITS.md`).

**Render** (`node render.mjs --out <dir>`) bundles once, renders each scene muted to
`out/scenes/NN.mp4` (skipped when that scene's edl and the source are unchanged, so a fix
re-renders one scene; the stamp is the scene's own part of the edl, its take, how the next scene enters and the
code, leaving out `src/cut.js` and the soundtrack's `src/mix.js` and `src/Mix.jsx`), renders the soundtrack once as a WAV, and the stems (voices, bed)
beside it. ffmpeg joins the scenes and lays the soundtrack under them:
`<out>/shipyard-demo.mp4` (1920x1080, H.264, AAC) and `<out>/shipyard-demo.srt`: the
titles, the captions, the user's lines in the script's words, and Harbor's answers cut at
sentences. `--check` renders one frame from the middle of every shot instead, for looking.
On a 2-core machine a full render is about 40 minutes.

**Evidence** (`node evidence.mjs --out <dir>`) reads the MP4 back: duration, resolution,
codecs, cue count, integrated loudness, and for every voice window the voice's loudness
against the loudest 400 ms of the bed in it, and exits 1 when any voice is less than 15 dB over the bed or cannot be measured. It writes `evidence.json`, `loudness.png` and
`contact-sheet.png` (one frame per scene, taken from the MP4 itself).

## The short cuts (c-807)

A LinkedIn series of short videos, each under a minute and with few words on screen, about
one idea: Shipyard runs many tasks in parallel and the user only decides. They are cut from
the SAME day's kept takes as the film, so they need no recording of their own: `demo/build
--out <dir> --edit-only --cut short-01` (or the whole build with `--cut`). Each short is data
in `demo/video/src/shorts.js`, beside the film's `cut.js`: a list of SEGMENTS, each a scene of
the film's kind with one key more, `take`, the scene whose kept take it shows. So a segment's
shots, cameras, voices and overlays are written as the film's are and move with a retake.

- **The frame** is 4:5 portrait, 1080x1350, at the film's 30 fps. The recording is shown in
  crops and push-ins of named elements, never squeezed: `cameraAt` takes the frame it draws
  into (`screen`), scales the recording evenly and never below `coverOf`, the scale at which
  it fills the frame, so no frame shows past the recording's edge (a zoom is a multiple of it;
  for the film the frame is the recording's own size and nothing changed).
- **A lapse** (`{lapse: {from, to}}`) plays a slice of the take, step `from`'s start to step
  `to`'s end, in the shot's length: its rate is what that takes, and prepare FAILS when it
  would not be faster than real time.
- **Voices by file name.** `{line: "line-1.wav", text}` is the user's recorded line from
  `--voice` and `text` its subtitle; `{line: "harbor", sentences: n}` is the take's captured
  answer cut after its n-th sentence (a sentence end sits on a real pause, and the mix fades
  the last 250 ms). A voice `at: {after, gap}` starts after the one before ends, and a segment
  `length: {atLeast, pad}` lasts as long as its voices need ("end" is its end), so a long
  answer moves what follows and two voices never overlap (prepare fails if they would).
  **short-01 reuses the film's line-1.wav and line-4.wav**, with the film's words as the
  subtitles, so it needs no new recording; a later short can name new files (say
  short-1.wav) and the build's help says which a cut plays. prepare names a missing one.
- **Overlays** of a short's own (`src/shortlays.jsx`): `subtitles` (the voices, large and
  burned in, in chunks of a clause or about 30 characters, from the word timings, each word lit as it is
  said), `card` (a few words: "6 tasks."), `tapmark` (a "tap N" badge and a ring on an
  Approve, with a soft click the prepare step makes, `audio/click.wav`, laid in the voices'
  stem at `edl.clicks`), `closing` (the last card); the film's `glow` and `fade` work too.
- **Music** per cut: the CC0 bed at the cut's own `levels` (short-01: -28 dB under a voice,
  -20 elsewhere, -16 on the closing), or `music: null` for none.

**short-01**, "Six tasks, three taps", about 35 s (37.8 s with --check's stand-in voice pace,
which its test holds to 30 to 40 s; the real length follows the takes):

| When | Segment | Take | What |
|---|---|---|---|
| 0-3 s | 01-open | 04 | the board's kanban (the export card and the three parallel cards building) then the two reviews, each lit in turn, under "6 tasks." |
| 3-~10 s | 02-ask | 02 | line-1, "Harbor, anything pending on my side?", then Harbor's first sentence, subtitled |
| next 2.4 s | 03-tap1 | 03 | tap 1 on the review's Approve outcome, then the posting as a lapse |
| next 2.2 s | 04-live | 04 | the board as a lapse while the export card's house starts |
| next 2.4 s | 05-tap2 | 05 | tap 2 on the plan's Approve, then the plan approved as a lapse |
| next 4 s | 06-tap3 | 08 | tap 3 on the outcome's Approve, then shipping as a lapse, under the header |
| next ~10 s | 07-evening | 10 | line-4, "Hey Harbor, anything left for today?", then Harbor's first two sentences |
| last 7 s | 08-close | 11 | the day's kanban pulled back to shipping and done, then "Build in parallel. Ship in parallel with Shipyard." and the repo link, set in `demo/video/src/shorts.js` |

The five parallel cards are seeded board state ([the work adapter](60-work-adapter.md), "The
seeded day"); the cards kanban leaves review cards out (Reviews is their list), which is why
the opening shows the two reviews on their own page.

prepare writes the short's edl to the same `public/edl.json` with `cut` in it, and render and
evidence refuse an edl of another cut (`edlOfCut` in `tools/edl.mjs`). Every cut names its
compositions, its scene files and its frames by one rule, the id's number (`sceneKey` and
`compositionOf` in `src/cut.js`, read by `Root.jsx`, render and evidence), and prepare refuses
a cut with two segments of one number. A short's segments cut straight into each other: the
dip from and to the canvas is on its first segment's start and its last one's end only. A short renders under `out/<cut>/` and is written as
`<out>/shipyard-<cut>.mp4` and `.srt`, its evidence as `evidence-<cut>.json`,
`contact-sheet-<cut>.png` and `loudness-<cut>.png`; a short with no bed has no margin to hold.
**`node prepare.mjs --check --cut <name>`** resolves a cut against the kept takes and writes
nothing: the takes it shows are kept and clean, its voice files are there, and every step,
name, slice and time resolves, with the voices timed from their words alone (no audio read),
so it needs no ffmpeg. It prints the resolved timeline as JSON.

## Tests

`tests/test_demo_video.py` runs `node --test` over `demo/video/test/` (the resolver and its
refusals, the ducking, word timing, the subtitles, the meter against a known sine; and
`short.test.mjs`: short-01 through `prepare.mjs --check` against a synthetic recordings index,
its 4:5 frame covered at every frame, the lapse and its refusal, a take of an older day
refused, and an edl of another cut refused), checks
the music's credits and what git must not carry, and holds `demo/build`'s refusals, the
order a dry run plays the day in, a short's `--cut` reaching every edit step, an unknown cut refused before setup, and the build's cuts and the seed's day agreeing with the edit's. Nothing in the suite renders, records or starts a sandbox.
In a tree without `demo/video/` (the public release) the edit's, the music's and the repo
content tests skip, and so do the two refusals the early refusal stands in front of; the
live-state refusal and the dry run still run. `tests/test_thirdparty.py` and
`tests/test_atlas.py` likewise let NOTICE and the Atlas name a path the tree leaves out by
`export-ignore` (`left_out` in `tests/helpers.py`), and only where it is absent.
