"""What no child process Keel starts may inherit (c-451).

`KEEL_TOKEN` is him: a `kb` holding it is the human, so a house, a test suite on a merged
tree, a board's ask, the talker or a voice turn that inherited it could approve a gate. The
deck's own `kb` is the one child that is handed it (`actions.kb_env`), on purpose.
`KEEL_LIVE_STATE` hands a worktree the live board. Whoever started a Keel process may carry
either; nothing that process starts does. Stdlib only: the voice package (Python 3.12)
imports this too.
"""

import os

# `KEEL_BOSUN` is Bosun's key (c-522): Bosun's own session is handed it in its settings' env
# (`console.settings`, c-553), and nothing a `kb` holding it starts (a house it resumes) inherits it.
WITHHELD = ("KEEL_TOKEN", "KEEL_LIVE_STATE", "KEEL_BOSUN")


def own_env(base: dict | None = None) -> dict:
    """A copy of `base` (this process's environment by default) without `WITHHELD`."""
    env = dict(os.environ if base is None else base)
    for name in WITHHELD:
        env.pop(name, None)
    return env
