"""The suite's one entry point, imported before any test module is.

`tests/fence.py` says what the fence is and why it exists. It is installed here because
both ways a house runs this suite (`make test` and a bare
`python3 -m unittest discover -s tests -t .`) are a discovery over this package, so this
module is imported first, and `load_tests` lets the fence's own check run last, as an
ordinary test with an ordinary failure message.
"""

from pathlib import Path

from tests import boardleak, fence

fence.install()
# A test that leaves a Board open fails, naming where it was opened (`tests/boardleak.py`).
boardleak.install()


def load_tests(loader, standard_tests, pattern):
    """Every test module here, then the fence's check, which goes last so it sees them all.

    Defining `load_tests` on a package takes discovery over from unittest, so the modules
    are gathered by name rather than by recursing back into this directory (which would
    re-enter here). `pattern` is discovery's, so `-p` still chooses.
    """
    here = Path(__file__).resolve().parent
    names = sorted(f"tests.{path.stem}" for path in here.glob(pattern or "test*.py"))
    standard_tests.addTests(loader.loadTestsFromNames(names))
    standard_tests.addTest(fence.FenceCase("test_nothing_reached_the_machine"))
    return standard_tests
