#!/usr/bin/env python3
"""Command-line interface for CLAYGO resource lifecycle management."""

from __future__ import annotations

import argparse
import json
import os
import stat
import sys
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple

from claygo_core import (
    DEFAULT_MAX_ENTRIES,
    FORMAT_VERSION,
    PROFILES,
    STATES,
    ClaygoError,
    absolute_path,
    check_open_files,
    closeout_owner,
    ensure_no_symlink_components,
    finalize_record,
    initialize_record,
    lexists,
    load_record,
    mark_record,
    receipt_is_outside,
    read_json,
    record_id,
    records_for_owner,
    remove_external_receipt,
    run_git,
    save_record,
    scan_candidate,
    utc_now,
    validate_identity,
    validate_temp_boundary,
    validate_worktree,
)

def command_init(args: argparse.Namespace) -> Dict[str, Any]:
    candidate = absolute_path(args.path)
    temp_root = absolute_path(args.temp_root)
    receipt = absolute_path(args.receipt)
    try:
        record = initialize_record(candidate, temp_root, receipt, args.owner, args.purpose, args.profile, create=True)
    except Exception:
        if candidate.exists():
            try:
                candidate.rmdir()
            except OSError:
                pass
        raise
    return {
        "status": "pass",
        "action": "init",
        "candidate": record["path"],
        "receipt": record["receipt"],
        "device": record["device"],
        "inode": record["inode"],
        "record": record,
    }


def command_migrate_legacy(args: argparse.Namespace) -> Dict[str, Any]:
    receipt = absolute_path(args.receipt)
    legacy = read_json(receipt)
    if legacy.get("format_version") != 1:
        raise ClaygoError("receipt is not a format-version 1 legacy receipt")
    required = {
        "owner", "purpose", "path", "resolved_path", "temp_root",
        "resolved_temp_root", "device", "inode", "created_at",
    }
    missing = sorted(required - set(legacy))
    if missing:
        raise ClaygoError("legacy receipt is missing fields: {}".format(", ".join(missing)))
    candidate = absolute_path(str(legacy["path"]))
    temp_root = absolute_path(str(legacy["temp_root"]))
    resolved_candidate, resolved_root = validate_temp_boundary(candidate, temp_root, must_exist=True)
    ensure_no_symlink_components(candidate, temp_root)
    receipt_is_outside(receipt, resolved_candidate)
    candidate_stat = os.stat(candidate, follow_symlinks=False)
    if candidate_stat.st_dev != legacy["device"] or candidate_stat.st_ino != legacy["inode"]:
        raise ClaygoError("legacy candidate device or inode changed after registration")
    for _, previous in records_for_owner(None):
        if previous.get("resolved_path") == os.fspath(resolved_candidate) and previous.get("state") != "removed":
            raise ClaygoError("an unresolved registry record already owns this path")
    resource_id = record_id(str(legacy["owner"]), resolved_candidate)
    record = dict(legacy)
    record.update({
        "format_version": FORMAT_VERSION,
        "resource_id": resource_id,
        "profile": args.profile,
        "state": args.state,
        "reason": args.reason,
        "path": os.fspath(candidate),
        "resolved_path": os.fspath(resolved_candidate),
        "resolved_temp_root": os.fspath(resolved_root),
        "updated_at": utc_now(),
        "receipt": os.fspath(receipt),
        "evidence": [],
        "cleanup": None,
    })
    save_record(record, receipt)
    return {"status": "pass", "action": "migrate-legacy", "record": record}


def command_register_worktree(args: argparse.Namespace) -> Dict[str, Any]:
    candidate = absolute_path(args.path)
    repository = absolute_path(args.repository)
    temp_root = absolute_path(args.temp_root)
    receipt = absolute_path(args.receipt)
    top = run_git(["rev-parse", "--show-toplevel"], candidate).stdout.strip()
    if Path(top).resolve() != candidate.resolve():
        raise ClaygoError("path is not a Git worktree top level")
    status_text = run_git(["status", "--porcelain=v1", "--untracked-files=all"], candidate).stdout
    if status_text.strip():
        raise ClaygoError("worktree must be clean when registered")
    head = run_git(["rev-parse", "HEAD"], candidate).stdout.strip()
    branch = run_git(["symbolic-ref", "--quiet", "--short", "HEAD"], candidate, check=False).stdout.strip() or None
    worktree = {
        "repository": os.fspath(repository.resolve()),
        "merged_into": args.merged_into,
        "head_at_registration": head,
        "branch": branch,
    }
    record = initialize_record(
        candidate,
        temp_root,
        receipt,
        args.owner,
        args.purpose,
        "git-worktree",
        create=False,
        worktree=worktree,
    )
    return {"status": "pass", "action": "register-worktree", "record": record}


def command_mark(args: argparse.Namespace) -> Dict[str, Any]:
    receipt = absolute_path(args.receipt)
    record = mark_record(receipt, args.state, args.reason)
    return {"status": "pass", "action": "mark", "record": record}


def command_check(args: argparse.Namespace) -> Dict[str, Any]:
    receipt = absolute_path(args.receipt)
    record = load_record(receipt)
    candidate, _ = validate_identity(record, receipt)
    if record["profile"] == "git-worktree":
        scan: Dict[str, Any] = {"worktree": validate_worktree(candidate, record)}
    else:
        scan = scan_candidate(candidate, str(record["profile"]), args.max_entries)
    open_result = check_open_files(candidate, args.open_file_timeout) if args.check_open_files else None
    return {
        "status": "pass",
        "action": "check",
        "candidate": os.fspath(candidate),
        "profile": record["profile"],
        "state": record["state"],
        "scan": scan,
        "open_file_check": open_result,
        "eligible_for_host_cleanup": True,
    }


def command_finalize(args: argparse.Namespace) -> Dict[str, Any]:
    return finalize_record(absolute_path(args.receipt), require_open_files=args.check_open_files, keep_receipt=args.keep_receipt)


def command_verify_removed(args: argparse.Namespace) -> Dict[str, Any]:
    receipt = absolute_path(args.receipt)
    record = load_record(receipt)
    candidate = absolute_path(str(record["path"]))
    if lexists(candidate):
        raise ClaygoError("candidate is still present: {}".format(candidate))
    record["state"] = "removed"
    record["reason"] = "exact absence verified after host cleanup"
    record["cleanup"] = {
        "removed_at": utc_now(),
        "scan": None,
        "open_file_check": None,
        "permission_repairs": None,
        "worktree": None,
        "verified_absent": True,
        "host_cleanup_compatibility_path": True,
    }
    save_record(record, receipt)
    receipt_removed = remove_external_receipt(record, receipt)
    return {
        "status": "pass",
        "action": "verify-removed",
        "candidate": os.fspath(candidate),
        "receipt_removed": receipt_removed,
        "registry_record": record["registry_record"],
    }


def command_list(args: argparse.Namespace) -> Dict[str, Any]:
    resources = []
    for _, record in records_for_owner(args.owner):
        if args.state and record["state"] != args.state:
            continue
        resources.append({key: record.get(key) for key in ("resource_id", "owner", "path", "profile", "state", "reason", "updated_at")})
    return {"status": "pass", "action": "list", "resources": resources}


def command_closeout(args: argparse.Namespace) -> Tuple[Dict[str, Any], int]:
    return closeout_owner(args.owner, args.finalize_disposable)


def command_reconcile(args: argparse.Namespace) -> Tuple[Dict[str, Any], int]:
    finalized: List[Dict[str, Any]] = []
    failed: List[Dict[str, Any]] = []
    for path, record in records_for_owner(None):
        if record["state"] != "disposable":
            continue
        try:
            finalized.append(finalize_record(path, require_open_files=True))
        except ClaygoError as exc:
            failed.append({"owner": record["owner"], "path": record["path"], "error": str(exc)})
    payload = {
        "status": "deny" if failed else "pass",
        "action": "reconcile",
        "finalized": finalized,
        "failed": failed,
    }
    return payload, 2 if failed else 0


def add_common_registration(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--path", required=True)
    parser.add_argument("--temp-root", required=True)
    parser.add_argument("--receipt", required=True)
    parser.add_argument("--owner", required=True)
    parser.add_argument("--purpose", required=True)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Own and safely finalize task-created temporary resources.")
    commands = parser.add_subparsers(dest="command", required=True)

    init_parser = commands.add_parser("init", help="Create and register a new temporary directory.")
    add_common_registration(init_parser)
    init_parser.add_argument("--profile", choices=sorted(PROFILES - {"git-worktree"}), default="generic")
    init_parser.set_defaults(handler=command_init)

    migrate_parser = commands.add_parser("migrate-legacy", help="Migrate a proven format-version 1 receipt into the lifecycle registry.")
    migrate_parser.add_argument("--receipt", required=True)
    migrate_parser.add_argument("--profile", required=True, choices=sorted(PROFILES - {"git-worktree"}))
    migrate_parser.add_argument("--state", required=True, choices=("active", "evidence", "disposable", "protected"))
    migrate_parser.add_argument("--reason", required=True)
    migrate_parser.set_defaults(handler=command_migrate_legacy)

    worktree_parser = commands.add_parser("register-worktree", help="Register a clean task-created Git worktree.")
    add_common_registration(worktree_parser)
    worktree_parser.add_argument("--repository", required=True)
    worktree_parser.add_argument("--merged-into", required=True)
    worktree_parser.set_defaults(handler=command_register_worktree)

    mark_parser = commands.add_parser("mark", help="Update lifecycle state.")
    mark_parser.add_argument("--receipt", required=True)
    mark_parser.add_argument("--state", required=True, choices=sorted(STATES - {"removed"}))
    mark_parser.add_argument("--reason", required=True)
    mark_parser.set_defaults(handler=command_mark)

    check_parser = commands.add_parser("check", help="Validate identity and profile without deleting.")
    check_parser.add_argument("--receipt", required=True)
    check_parser.add_argument("--max-entries", type=int, default=DEFAULT_MAX_ENTRIES)
    check_parser.add_argument("--check-open-files", action="store_true")
    check_parser.add_argument("--open-file-timeout", type=int, default=30)
    check_parser.set_defaults(handler=command_check)

    finalize_parser = commands.add_parser("finalize", help="Delete an exact disposable resource and verify absence.")
    finalize_parser.add_argument("--receipt", required=True)
    finalize_parser.add_argument("--check-open-files", action="store_true")
    finalize_parser.add_argument("--keep-receipt", action="store_true")
    finalize_parser.set_defaults(handler=command_finalize)

    verify_parser = commands.add_parser("verify-removed", help="Confirm a registry record's path is absent.")
    verify_parser.add_argument("--receipt", required=True)
    verify_parser.set_defaults(handler=command_verify_removed)

    list_parser = commands.add_parser("list", help="List registry resources.")
    list_parser.add_argument("--owner")
    list_parser.add_argument("--state", choices=sorted(STATES))
    list_parser.set_defaults(handler=command_list)

    closeout_parser = commands.add_parser("closeout", help="Enforce owner closeout and optionally finalize disposable resources.")
    closeout_parser.add_argument("--owner", required=True)
    closeout_parser.add_argument("--finalize-disposable", action="store_true")
    closeout_parser.set_defaults(handler=command_closeout)

    reconcile_parser = commands.add_parser("reconcile", help="Finalize all explicitly disposable registered resources.")
    reconcile_parser.add_argument("--all-disposable", action="store_true", required=True)
    reconcile_parser.set_defaults(handler=command_reconcile)
    return parser


def emit(payload: Dict[str, Any]) -> None:
    json.dump(payload, sys.stdout, indent=2, sort_keys=True)
    sys.stdout.write("\n")


def main(argv: Optional[Iterable[str]] = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        result = args.handler(args)
        if isinstance(result, tuple):
            payload, code = result
        else:
            payload, code = result, 0
    except ClaygoError as exc:
        emit({"status": "deny", "error": str(exc)})
        return 2
    except Exception as exc:
        emit({"status": "error", "error": "{}: {}".format(type(exc).__name__, exc)})
        return 3
    emit(payload)
    return code


if __name__ == "__main__":
    raise SystemExit(main())
