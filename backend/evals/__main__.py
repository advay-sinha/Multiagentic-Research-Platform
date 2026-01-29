from __future__ import annotations

import sys

from .run import DEFAULT_API, DEFAULT_DATASET, main


if __name__ == "__main__":
    args = sys.argv[1:]
    if not args:
        args = [str(DEFAULT_DATASET), DEFAULT_API]
    raise SystemExit(main(args))
