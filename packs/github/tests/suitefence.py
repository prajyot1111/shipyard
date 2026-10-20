"""The suite fence, for this pack's suite.

`python3 -m unittest discover -s packs/github/tests` runs these files as top-level modules,
with no package whose `__init__` is imported first, so every test module here imports this,
which installs the one fence (`tests/fence.py` says what it does and why). The pack's own
directory goes on the path too, so a test imports the modules behind the verbs by name, and
the kit is bound to this pack (`keel/packkit/pack.py`), as each verb's shim binds it.
"""

import sys
from pathlib import Path

PACK = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PACK.parent.parent))
sys.path.insert(0, str(PACK))

from tests import fence  # noqa: E402

fence.install()

from keel.packkit import pack  # noqa: E402

pack.bind(PACK, "gh_layer")
