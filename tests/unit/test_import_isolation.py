from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
SECRETS = ("GOOGLE_API_KEY", "CACHE_ENCRYPTION_KEY", "API_TOKEN")


@pytest.mark.parametrize("module", ["src.api.app", "src.ui.app", "src.ui.api_client"])
def test_importing_a_module_never_loads_the_real_dot_env(module: str) -> None:
    """Regression: `app = create_app()` at import time read the real .env (every key) into any
    process that merely imported the module, tests included."""
    code = (
        "import os, sys\n"
        f"before = {{k: os.environ.get(k) for k in {SECRETS!r}}}\n"
        f"import {module}\n"
        f"after = {{k: os.environ.get(k) for k in {SECRETS!r}}}\n"
        "sys.exit(0 if before == after else 1)\n"
    )
    result = subprocess.run(
        [sys.executable, "-c", code], cwd=ROOT, capture_output=True, text=True, timeout=120
    )
    assert result.returncode == 0, f"{module} changed the environment on import"
