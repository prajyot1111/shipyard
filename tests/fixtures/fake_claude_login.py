"""A stand-in `claude` for the login reproduction (tests/test_login_repro.py).

It answers the calls one drain pass makes, from files in FAKE_CLAUDE_DIR, and records
every call it gets in `calls.jsonl`:

- `agents --json`: the rows in `rows.json`;
- `logs <id>`: the text in `logs.txt`;
- `stop <id>`: drops that row;
- `--resume <id> --bg --name <card> ...` and `--bg --name <card> ...`: a new session,
  listed idle under the card's name, and the `backgrounded` line the harness parses;
- `-p --resume <id> <the login probe's flags>` with no prompt (c-654, is the conversation
  still there?): what a real 2.1.289 prints for one that is, on stderr, exit 1, and no turn;
- `-p ...` (the login probe): while `login-ok` does NOT exist, the text a real Claude
  Code 2.1.281 prints for a login that cannot refresh, on stdout, exit 1 (recorded from
  the binary and from a real `-p` under a config dir with no login, 2026-09-24); once it
  exists, `ok` and exit 0.
"""

import json
import os
import sys
import uuid
from pathlib import Path

EXPIRED = "Login expired · Please run /login"
THERE = ("Error: No deferred tool marker found in the resumed session. Either the session was not "
         "deferred, the marker is stale (tool already ran), or it exceeds the tail-scan window. "
         "Provide a prompt to continue the conversation.")
HOME = Path(os.environ["FAKE_CLAUDE_DIR"])


def rows() -> list:
    path = HOME / "rows.json"
    return json.loads(path.read_text()) if path.exists() else []


def save(listed: list) -> None:
    (HOME / "rows.json").write_text(json.dumps(listed))


def flag(argv: list, name: str):
    return argv[argv.index(name) + 1] if name in argv else None


def main(argv: list) -> int:
    with open(HOME / "calls.jsonl", "a", encoding="utf-8") as log:
        log.write(json.dumps({"argv": argv,
                              "config_dir": os.environ.get("CLAUDE_CONFIG_DIR")}) + "\n")
    if argv[:1] == ["--version"]:
        print("2.1.281 (Claude Code)")
        return 0
    if argv[:1] == ["agents"]:
        print(json.dumps(rows()))
        return 0
    if argv[:1] == ["logs"]:
        path = HOME / "logs.txt"
        print(path.read_text() if path.exists() else "")
        return 0
    if argv[:1] == ["stop"]:
        save([row for row in rows() if not row["sessionId"].startswith(argv[1])])
        return 0
    if argv[:2] == ["-p", "--resume"]:
        print(THERE, file=sys.stderr)
        return 1
    if "-p" in argv:
        if (HOME / "login-ok").exists():
            print("ok")
            return 0
        print(EXPIRED)
        return 1
    if "--bg" in argv:
        name = flag(argv, "--name")
        session = str(uuid.uuid4())
        save(rows() + [{"pid": 4242, "id": session[:8], "cwd": os.getcwd(),
                        "kind": "background", "sessionId": session, "name": name,
                        "status": "idle"}])
        print(f"backgrounded · {session[:8]} · {name}")
        return 0
    print(f"fake claude: unexpected {argv}", file=sys.stderr)
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
