"""Entry point of the PDF parsing process: parse ONE file, print the result as JSON.

Run as `python -m src.ocr.worker <path> <max_pages> <max_chars>` by the extractor, which
kills it if it takes too long. It is a separate command so that the parent never depends on
its own `__main__` (multiprocessing's "spawn" would re-import it).
"""

from __future__ import annotations

import json
import sys

from src.ocr.extractor import _read_pdf


def main(argv: list[str]) -> int:
    path, max_pages, max_chars = argv[1], int(argv[2]), int(argv[3])
    sys.stdout.write(json.dumps(_read_pdf(path, max_pages, max_chars)))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
