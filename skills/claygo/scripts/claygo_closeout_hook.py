#!/usr/bin/env python3
"""User stop hook: finalize disposable CLAYGO resources and block unresolved closeout."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any, Optional


OWNER_KEYS = ("session_id", "thread_id", "conversation_id", "sessionId", "threadId", "conversationId")


def find_owner(value: Any) -> Optional[str]:
    if isinstance(value, dict):
        for key in OWNER_KEYS:
            owner = value.get(key)
            if isinstance(owner, str) and owner.strip():
                return owner.strip()
        for nested in value.values():
            owner = find_owner(nested)
            if owner:
                return owner
    elif isinstance(value, list):
        for nested in value:
            owner = find_owner(nested)
            if owner:
                return owner
    return None


def main() -> int:
    try:
        event = json.load(sys.stdin)
    except Exception:
        print("{}")
        return 0
    owner = find_owner(event)
    if not owner:
        print("{}")
        return 0
    cli = Path(os.environ.get("CLAYGO_CLI", str(Path.home() / ".codex/skills/claygo/scripts/claygo.py")))
    result = subprocess.run(
        [sys.executable, os.fspath(cli), "closeout", "--owner", owner, "--finalize-disposable"],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        check=False,
        env=os.environ.copy(),
    )
    if result.returncode == 0:
        print("{}")
        return 0
    detail = result.stdout.strip() or result.stderr.strip() or "CLAYGO closeout failed"
    sys.stderr.write(
        "CLAYGO blocked successful task closeout. Resolve active/evidence resources, "
        "or mark a genuinely retained resource protected with a concrete reason.\n{}\n".format(detail)
    )
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
