"""Stand-in worker for the isolation tests: `python -m tests.unit._isolated_targets <mode>`.

Each mode reproduces one way a real parser worker can misbehave.
"""

from __future__ import annotations

import json
import os
import sys
import time

from src.core.env import SECRET_ENV_KEYS


def main(mode: str) -> int:
    if mode == "sleep":  # a parser stuck on a hostile file
        time.sleep(60)
    elif mode == "crash":  # a parser that dies without answering (segfault)
        os._exit(3)
    elif mode == "raise":
        raise RuntimeError("boom")
    elif mode == "garbage":
        sys.stdout.write("this is not json")
    elif mode == "empty-list":
        sys.stdout.write("[]")
    elif mode == "huge":
        sys.stdout.write("x" * (6 * 1024 * 1024))
    elif mode == "env":  # report which secrets this process can see
        sys.stdout.write(json.dumps(["ok", {key: os.environ.get(key) for key in SECRET_ENV_KEYS}]))
    else:
        sys.stdout.write(json.dumps(["ok"]))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1] if len(sys.argv) > 1 else "ok"))
