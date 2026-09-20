"""Picklable, importable targets for the process-isolation tests (spawn needs importable code)."""

from __future__ import annotations

import os
import time


def sleep_forever() -> tuple:
    time.sleep(60)
    return ("ok",)


def hard_crash() -> tuple:
    os._exit(1)  # simulates a parser segfault: the process dies without answering


def raise_error() -> tuple:
    raise RuntimeError("boom")
