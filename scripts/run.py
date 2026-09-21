"""Start the API and the interface with one command: `python scripts/run.py`.

Options: --no-browser, --api-port N, --ui-port N.
"""

import sys
from pathlib import Path

# This file lives in scripts/: put the project root on sys.path so `src` can be imported.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.launcher import main  # noqa: E402

if __name__ == "__main__":
    sys.exit(main())
