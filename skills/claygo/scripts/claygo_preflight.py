#!/usr/bin/env python3
"""Compatibility entrypoint for the canonical CLAYGO executable."""

from claygo import main


if __name__ == "__main__":
    raise SystemExit(main())
