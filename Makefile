.PHONY: test test-core test-all test-serial test-changed test-again drift voice-test

# Each pack's own suite (`packs/<name>/tests`, c-689, and the install's own packs when
# KEEL_CONFIG names an install, c-726 r1.F4), one after another, each in a process of its own;
# the first that fails stops the job (tests/packsuites.py). `tests/selector.py` runs the same command.
ADAPTERS_TESTS = python3 tests/packsuites.py
BASE ?= main
ADAPTERS_DONE = adapters=^OK( \(.*\))?$$
VOICE_DONE = voice=^(ok: |voice selftest: skipped)
# Every keel/ module and bin/ script under the box's Python (tests/py312.py): its own line
# says ok, or skipped with a note on a machine with no python3.12.
PY312_CHECK = python3 -m tests.py312
PY312_DONE = py312=^py312: (ok|skipped)

# What runs wherever something lands (c-646): the core suite
# (tests/core.txt, the modules that guard Keel's core promises), every extended module the
# change since BASE can reach, the packs' own suites or the voice selftest when the change
# reaches them, and the Python 3.12 import check (tests/selector.py --core). A change the
# selector cannot place runs `make test-all`. The landing passes BASE, the tree it lands on.
# KEEL_FULL_SUITE set (a deploy whose config names no `[deploy_tests]`, c-646) runs
# `make test-all` instead, so an install config that still says `make test` deploys on the
# full suite rather than being refused.
test: drift
	if [ -n "$(KEEL_FULL_SUITE)" ]; then $(MAKE) --no-print-directory test-all; \
	else python3 -m tests.selector --core --base $(BASE); fi

# The core suite alone, with the Python 3.12 import check: the fastest whole signal.
test-core: drift
	python3 -m tests.parallel --core --job 'py312=$(PY312_CHECK)' --done '$(PY312_DONE)'

# Every module, on demand and at every deploy (`[deploy_tests]`, c-646): the deploy is the
# gate that runs every module, voice included. The stdlib modules go across worker processes
# (tests/parallel.py), with the packs' own suites, the voice selftest and the import
# check beside them as jobs; the output and the verdict mean what the serial run's do.
# A job counts only when its last line says it finished (`--done`): unittest's own verdict
# for the adapters, the selftest's closing `ok:` line (or the skip note) for voice, and the
# check's `py312: ok` (or its skip note) for the Python 3.12 import check.
test-all: drift
	python3 -m tests.parallel --job 'adapters=$(ADAPTERS_TESTS)' --done '$(ADAPTERS_DONE)' \
	  --job 'voice=$(MAKE) --no-print-directory voice-test' --done '$(VOICE_DONE)' \
	  --job 'py312=$(PY312_CHECK)' --done '$(PY312_DONE)'

# A red run's failures once more, and nothing else (c-526): what the deploy worker runs
# when its full suite is red (`[retests]` in keel.toml), deploying only if these pass.
# LOG is the red run's output; the jobs are `make test-all`'s, and only a failed one reruns.
test-again:
	python3 -m tests.parallel --rerun '$(LOG)' --job 'adapters=$(ADAPTERS_TESTS)' --done '$(ADAPTERS_DONE)' \
	  --job 'voice=$(MAKE) --no-print-directory voice-test' --done '$(VOICE_DONE)' \
	  --job 'py312=$(PY312_CHECK)' --done '$(PY312_DONE)'

# The same suites one after another, in one process each, as `make test-all` ran them before.
test-serial: drift
	python3 -m unittest discover -s tests -t . -v
	$(ADAPTERS_TESTS)
	$(MAKE) --no-print-directory voice-test
	$(PY312_CHECK)

# The test modules the change since BASE can reach (tests/selector.py says which and why),
# and every module whenever it cannot tell: for iterating, and what a house runs before
# review (`[house_tests]`, c-544), since `make test` runs once, where the change lands.
test-changed: drift
	python3 -m tests.selector --base $(BASE)

# The voice gateway's own selftest, from its own interpreter (kokoro pins Python below
# 3.13, so the stdlib suite above never imports the package). Skipped with a note when
# the venv has not been built; `keel voice venv` builds it. KEEL_SEGMENTS_DIR is what
# `keel voice install` writes into the agent's environment, so the selftest's one
# cross-segment read (cloud-spend) resolves the same tree the gateway does.
voice-test:
	@if [ -x .venv-voice/bin/python ]; then \
	  KEEL_SEGMENTS_DIR="$$(python3 -c 'from keel import config; print(config.load(ensure=False).segments_dir)')" \
	    .venv-voice/bin/python bin/keel-voice-selftest; \
	else echo "voice selftest: skipped, no .venv-voice (build it with bin/keel voice venv)"; fi

# Five checks. A pack's own words may live only in that pack: each `packs/<name>/drift-terms`
# is grepped against every file outside that pack and docs/ (history), and so is each pack of
# the install KEEL_CONFIG names (tests/installdrift.py, c-722 r1.F7: a work pack, whose terms
# are the employer's, lives in the install; read as the caller set it, before the test fence
# drops it, and it says which install it read or that none was named, c-733), so the guard's own text never trips it (c-617; adapters/ before it, whose
# entries are now links into packs/, which grep skips). The file list comes from git (tracked
# plus untracked-but-not-ignored), so runtime files under gitignored dirs such as a config
# dir's projects/ transcripts never trip it either. And no one person's home path or tailnet
# host outside docs/, with no list of files let through (tests/personal.py, c-610 S1).
# And no ticket or change noun (story, pull request, PR, sc-<n>) spelled out in a string of
# app/ or keel/: they come from the space's pack through keel/terms.py (tests/nouns.py, c-630).
# And no sentence Shipyard says calls its user he, his or him (tests/owner_words.py, c-699).
# Last, STRICT since c-722 landing B: nothing in the tree that is one install's own (its
# names, email, home, hosts and pack terms), docs/ read, and only its two short tables let
# through, each entry with its reason (tests/publiccheck.py, c-699). It prints counts by
# kind, never a term.
drift:
	@for terms in packs/*/drift-terms; do \
	  [ -f "$$terms" ] || continue; pack=$$(dirname "$$terms"); \
	  hits=$$(git ls-files -co --exclude-standard | grep -vE "^($$pack|docs)/" | xargs grep -d skip -IiE -f "$$terms" || true); \
	  if [ -n "$$hits" ]; then echo "drift: $$pack's vocabulary outside $$pack/:"; echo "$$hits"; exit 1; fi; \
	done
	@python3 -m tests.installdrift
	@python3 -m tests.personal
	@python3 -m tests.nouns
	@python3 -m tests.owner_words
	@python3 -m tests.publiccheck --strict
