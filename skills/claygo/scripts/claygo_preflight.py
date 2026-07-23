#!/usr/bin/env python3
"""Create ownership receipts and preflight CLAYGO cleanup candidates.

This helper never deletes candidate data.
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import shutil
import stat
import subprocess
import sys
from pathlib import Path
from typing import Any, Iterable

FORMAT_VERSION = 1
VCS_MARKERS = {".git", ".jj", ".hg", ".svn", ".bzr", "_darcs"}
DEFAULT_MAX_ENTRIES = 200_000


class PreflightError(Exception):
    """A safety condition prevented the requested operation."""


def utc_now() -> str:
    return dt.datetime.now(dt.timezone.utc).isoformat()


def absolute_path(value: str) -> Path:
    expanded = os.path.expanduser(value)
    if not os.path.isabs(expanded):
        raise PreflightError(f"path must be absolute: {value}")
    return Path(os.path.abspath(expanded))


def is_strict_descendant(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
    except ValueError:
        return False
    return path != root


def lexists(path: Path) -> bool:
    return os.path.lexists(os.fspath(path))


def ensure_no_vcs_component(path: Path) -> None:
    blocked = [part for part in path.parts if part.casefold() in VCS_MARKERS]
    if blocked:
        raise PreflightError(f"path intersects VCS metadata: {blocked[0]}")


def resolve_candidate(path: Path, temp_root: Path, *, must_exist: bool) -> tuple[Path, Path]:
    ensure_no_vcs_component(path)
    ensure_no_vcs_component(temp_root)

    if not temp_root.exists() or not temp_root.is_dir():
        raise PreflightError(f"temporary root is not an existing directory: {temp_root}")

    resolved_root = temp_root.resolve(strict=True)
    resolved_path = path.resolve(strict=must_exist)
    if not is_strict_descendant(resolved_path, resolved_root):
        raise PreflightError("candidate must be a strict descendant of the temporary root")

    home = Path.home().resolve()
    filesystem_root = Path(resolved_path.anchor).resolve()
    if resolved_path in {home, filesystem_root, resolved_root}:
        raise PreflightError("candidate resolves to a protected broad path")

    cwd = Path.cwd().resolve()
    if cwd == resolved_path or is_strict_descendant(cwd, resolved_path):
        raise PreflightError("current working directory is inside the candidate")

    return resolved_path, resolved_root


def ensure_no_symlink_components(path: Path, temp_root: Path) -> None:
    resolved_root = temp_root.resolve(strict=True)
    cursor = path
    while cursor.resolve(strict=False) != resolved_root:
        if lexists(cursor) and cursor.is_symlink():
            raise PreflightError(f"symlink component is not allowed: {cursor}")
        parent = cursor.parent
        if parent == cursor:
            raise PreflightError("candidate path does not reach the temporary root")
        cursor = parent


def receipt_path_is_safe(receipt: Path, candidate_resolved: Path) -> None:
    receipt_resolved = receipt.resolve(strict=False)
    if receipt_resolved == candidate_resolved or is_strict_descendant(
        receipt_resolved, candidate_resolved
    ):
        raise PreflightError("receipt must live outside the cleanup candidate")
    if receipt.exists():
        raise PreflightError(f"receipt already exists: {receipt}")
    if not receipt.parent.exists() or not receipt.parent.is_dir():
        raise PreflightError(f"receipt parent is not an existing directory: {receipt.parent}")


def write_json_exclusive(path: Path, payload: dict[str, Any]) -> None:
    with path.open("x", encoding="utf-8") as handle:
        json.dump(payload, handle, indent=2, sort_keys=True)
        handle.write("\n")


def load_receipt(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise PreflightError(f"cannot read receipt: {exc}") from exc
    required = {
        "format_version",
        "owner",
        "purpose",
        "path",
        "resolved_path",
        "temp_root",
        "resolved_temp_root",
        "device",
        "inode",
        "created_at",
    }
    missing = sorted(required - payload.keys())
    if missing:
        raise PreflightError(f"receipt is missing fields: {', '.join(missing)}")
    if payload["format_version"] != FORMAT_VERSION:
        raise PreflightError(f"unsupported receipt format: {payload['format_version']}")
    return payload


def looks_like_bare_git(names: set[str]) -> bool:
    folded = {name.casefold() for name in names}
    return {"head", "objects", "refs"}.issubset(folded) or {
        "commondir",
        "gitdir",
    }.issubset(folded)


def scan_candidate(root: Path, max_entries: int) -> dict[str, int]:
    entries = 0
    logical_bytes = 0
    allocated_bytes = 0
    stack = [root]

    while stack:
        current = stack.pop()
        try:
            current_stat = os.stat(current, follow_symlinks=False)
            logical_bytes += current_stat.st_size
            allocated_bytes += getattr(current_stat, "st_blocks", 0) * 512
            children = list(os.scandir(current))
        except OSError as exc:
            raise PreflightError(f"cannot inspect {current}: {exc}") from exc

        names = {entry.name for entry in children}
        marker = sorted(name for name in names if name.casefold() in VCS_MARKERS)
        if marker:
            raise PreflightError(f"VCS metadata found at {current / marker[0]}")
        if looks_like_bare_git(names):
            raise PreflightError(f"bare or linked-worktree Git metadata found at {current}")

        for entry in children:
            entries += 1
            if entries > max_entries:
                raise PreflightError(
                    f"entry limit exceeded ({max_entries}); require a bounded manual audit"
                )
            entry_path = Path(entry.path)
            try:
                entry_stat = entry.stat(follow_symlinks=False)
            except OSError as exc:
                raise PreflightError(f"cannot stat {entry_path}: {exc}") from exc

            if stat.S_ISLNK(entry_stat.st_mode):
                raise PreflightError(f"symlink found: {entry_path}")
            if stat.S_ISDIR(entry_stat.st_mode):
                stack.append(entry_path)
            elif stat.S_ISREG(entry_stat.st_mode):
                logical_bytes += entry_stat.st_size
                allocated_bytes += getattr(entry_stat, "st_blocks", 0) * 512
            else:
                raise PreflightError(f"special file found: {entry_path}")

    return {
        "entries": entries,
        "logical_bytes": logical_bytes,
        "allocated_bytes": allocated_bytes,
    }


def check_open_files(candidate: Path, timeout: int) -> dict[str, Any]:
    executable = shutil.which("lsof")
    if executable is None:
        raise PreflightError("open-file check requested but lsof is unavailable")
    try:
        result = subprocess.run(
            [executable, "+D", os.fspath(candidate)],
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise PreflightError(f"open-file check failed: {exc}") from exc

    output_lines = [line for line in result.stdout.splitlines() if line.strip()]
    data_lines = (
        output_lines[1:]
        if output_lines[:1] and output_lines[0].startswith("COMMAND")
        else output_lines
    )
    if data_lines:
        preview = data_lines[:5]
        raise PreflightError(
            "open files reference the candidate: " + " | ".join(preview)
        )
    if result.returncode not in {0, 1}:
        detail = result.stderr.strip() or f"exit {result.returncode}"
        raise PreflightError(f"lsof could not establish a safe result: {detail}")
    return {"tool": executable, "open_files": 0}


def command_init(args: argparse.Namespace) -> dict[str, Any]:
    candidate = absolute_path(args.path)
    temp_root = absolute_path(args.temp_root)
    receipt = absolute_path(args.receipt)
    if lexists(candidate):
        raise PreflightError(f"candidate already exists and cannot be adopted: {candidate}")

    resolved_candidate, resolved_root = resolve_candidate(
        candidate, temp_root, must_exist=False
    )
    ensure_no_symlink_components(candidate.parent, temp_root)
    receipt_path_is_safe(receipt, resolved_candidate)

    try:
        os.mkdir(candidate, 0o700)
        candidate_stat = os.stat(candidate, follow_symlinks=False)
        payload = {
            "format_version": FORMAT_VERSION,
            "owner": args.owner,
            "purpose": args.purpose,
            "path": os.fspath(candidate),
            "resolved_path": os.fspath(candidate.resolve(strict=True)),
            "temp_root": os.fspath(temp_root),
            "resolved_temp_root": os.fspath(resolved_root),
            "device": candidate_stat.st_dev,
            "inode": candidate_stat.st_ino,
            "created_at": utc_now(),
            "state": "active",
        }
        write_json_exclusive(receipt, payload)
    except Exception:
        try:
            os.rmdir(candidate)
        except OSError:
            pass
        raise

    return {
        "status": "pass",
        "action": "init",
        "candidate": os.fspath(candidate),
        "receipt": os.fspath(receipt),
        "device": candidate_stat.st_dev,
        "inode": candidate_stat.st_ino,
        "note": "Ownership recorded. This helper does not delete data.",
    }


def validate_receipt_identity(
    receipt_path: Path, payload: dict[str, Any]
) -> tuple[Path, Path]:
    candidate = absolute_path(str(payload["path"]))
    temp_root = absolute_path(str(payload["temp_root"]))
    resolved_candidate, resolved_root = resolve_candidate(
        candidate, temp_root, must_exist=True
    )
    ensure_no_symlink_components(candidate, temp_root)

    if os.fspath(resolved_candidate) != payload["resolved_path"]:
        raise PreflightError("candidate resolved path no longer matches the receipt")
    if os.fspath(resolved_root) != payload["resolved_temp_root"]:
        raise PreflightError("temporary root no longer matches the receipt")
    receipt_path_is_outside = receipt_path.resolve(strict=True)
    if receipt_path_is_outside == resolved_candidate or is_strict_descendant(
        receipt_path_is_outside, resolved_candidate
    ):
        raise PreflightError("receipt is inside the cleanup candidate")

    candidate_stat = os.stat(candidate, follow_symlinks=False)
    if (
        candidate_stat.st_dev != payload["device"]
        or candidate_stat.st_ino != payload["inode"]
    ):
        raise PreflightError("candidate device or inode changed after ownership was recorded")
    if not stat.S_ISDIR(candidate_stat.st_mode):
        raise PreflightError("candidate is no longer a directory")
    return candidate, temp_root


def command_check(args: argparse.Namespace) -> dict[str, Any]:
    if args.max_entries < 0:
        raise PreflightError("max entries must be zero or greater")
    if args.open_file_timeout <= 0:
        raise PreflightError("open-file timeout must be greater than zero")
    receipt = absolute_path(args.receipt)
    payload = load_receipt(receipt)
    candidate, _ = validate_receipt_identity(receipt, payload)
    scan = scan_candidate(candidate, args.max_entries)
    open_file_result: dict[str, Any] | None = None
    warnings: list[str] = []
    if args.check_open_files:
        open_file_result = check_open_files(candidate, args.open_file_timeout)
    else:
        warnings.append("open-file check was not requested")

    return {
        "status": "pass",
        "action": "check",
        "candidate": os.fspath(candidate),
        "owner": payload["owner"],
        "purpose": payload["purpose"],
        "identity": {
            "device": payload["device"],
            "inode": payload["inode"],
        },
        "scan": scan,
        "open_file_check": open_file_result,
        "warnings": warnings,
        "eligible_for_host_cleanup": True,
        "note": "Re-run immediately before exact-path cleanup and follow host approval policy.",
    }


def command_verify_removed(args: argparse.Namespace) -> dict[str, Any]:
    receipt = absolute_path(args.receipt)
    payload = load_receipt(receipt)
    candidate = absolute_path(str(payload["path"]))
    temp_root = absolute_path(str(payload["temp_root"]))
    if lexists(candidate):
        raise PreflightError(f"candidate is still present: {candidate}")
    if not temp_root.exists() or not temp_root.is_dir():
        raise PreflightError(f"protected temporary root is missing: {temp_root}")
    if not candidate.parent.exists() or not candidate.parent.is_dir():
        raise PreflightError(f"candidate parent is missing: {candidate.parent}")
    return {
        "status": "pass",
        "action": "verify-removed",
        "candidate": os.fspath(candidate),
        "receipt": os.fspath(receipt),
        "verified_at": utc_now(),
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Record and preflight CLAYGO cleanup candidates without deleting them."
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    init_parser = subparsers.add_parser(
        "init", help="Create a new empty scratch root and ownership receipt."
    )
    init_parser.add_argument("--path", required=True)
    init_parser.add_argument("--temp-root", required=True)
    init_parser.add_argument("--receipt", required=True)
    init_parser.add_argument("--owner", required=True)
    init_parser.add_argument("--purpose", required=True)
    init_parser.set_defaults(handler=command_init)

    check_parser = subparsers.add_parser(
        "check", help="Verify identity and scan a receipted cleanup candidate."
    )
    check_parser.add_argument("--receipt", required=True)
    check_parser.add_argument(
        "--max-entries", type=int, default=DEFAULT_MAX_ENTRIES
    )
    check_parser.add_argument("--check-open-files", action="store_true")
    check_parser.add_argument("--open-file-timeout", type=int, default=30)
    check_parser.set_defaults(handler=command_check)

    verify_parser = subparsers.add_parser(
        "verify-removed", help="Confirm the candidate is absent and parents remain."
    )
    verify_parser.add_argument("--receipt", required=True)
    verify_parser.set_defaults(handler=command_verify_removed)
    return parser


def emit(payload: dict[str, Any]) -> None:
    json.dump(payload, sys.stdout, indent=2, sort_keys=True)
    sys.stdout.write("\n")


def main(argv: Iterable[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        payload = args.handler(args)
    except PreflightError as exc:
        emit({"status": "deny", "error": str(exc)})
        return 2
    except Exception as exc:
        emit({"status": "error", "error": f"{type(exc).__name__}: {exc}"})
        return 3
    emit(payload)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
