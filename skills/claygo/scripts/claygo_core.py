#!/usr/bin/env python3
"""Own and safely finalize task-created temporary resources."""

from __future__ import annotations

import datetime as dt
import errno
import hashlib
import json
import os
import shutil
import stat
import subprocess
import tempfile
import uuid
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Set, Tuple


FORMAT_VERSION = 2
DEFAULT_MAX_ENTRIES = 300_000
STATES = {"active", "evidence", "disposable", "protected", "removed"}
PROFILES = {
    "generic",
    "swiftpm",
    "xcode-derived-data",
    "node-test",
    "deployment",
    "screenshot",
    "git-worktree",
}
GENERATED_PROFILES = {
    "swiftpm",
    "xcode-derived-data",
    "node-test",
    "deployment",
    "screenshot",
}
VCS_MARKERS = {".git", ".jj", ".hg", ".svn", ".bzr", "_darcs"}


class ClaygoError(Exception):
    pass


def utc_now() -> str:
    return dt.datetime.now(dt.timezone.utc).isoformat()


def absolute_path(value: str) -> Path:
    expanded = os.path.expanduser(value)
    if not os.path.isabs(expanded):
        raise ClaygoError("path must be absolute: {}".format(value))
    return Path(os.path.abspath(expanded))


def lexists(path: Path) -> bool:
    return os.path.lexists(os.fspath(path))


def is_descendant(path: Path, root: Path, *, strict: bool = True) -> bool:
    try:
        path.relative_to(root)
    except ValueError:
        return False
    return path != root if strict else True


def state_root() -> Path:
    configured = os.environ.get("CLAYGO_STATE_DIR")
    root = absolute_path(configured) if configured else Path.home() / ".local/state/claygo"
    root.mkdir(parents=True, exist_ok=True, mode=0o700)
    try:
        os.chmod(root, 0o700)
    except OSError:
        pass
    resources = root / "resources"
    resources.mkdir(parents=True, exist_ok=True, mode=0o700)
    return root


def record_id(owner: str, resolved_path: Path) -> str:
    material = (
        owner.encode("utf-8")
        + b"\0"
        + os.fspath(resolved_path).encode("utf-8")
        + b"\0"
        + uuid.uuid4().hex.encode("ascii")
    )
    return hashlib.sha256(material).hexdigest()


def registry_path(resource_id: str) -> Path:
    return state_root() / "resources" / (resource_id + ".json")


def atomic_write_json(path: Path, payload: Dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    fd, temporary = tempfile.mkstemp(prefix=".claygo-", suffix=".json", dir=os.fspath(path.parent))
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, indent=2, sort_keys=True)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.chmod(temporary, 0o600)
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def read_json(path: Path) -> Dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ClaygoError("cannot read JSON {}: {}".format(path, exc)) from exc
    if not isinstance(value, dict):
        raise ClaygoError("JSON record is not an object: {}".format(path))
    return value


def save_record(record: Dict[str, Any], receipt: Optional[Path] = None) -> None:
    record["updated_at"] = utc_now()
    canonical = registry_path(str(record["resource_id"]))
    record["registry_record"] = os.fspath(canonical)
    atomic_write_json(canonical, record)
    if receipt is not None and receipt.resolve(strict=False) != canonical.resolve(strict=False):
        atomic_write_json(receipt, record)


def remove_external_receipt(record: Dict[str, Any], receipt: Path) -> bool:
    canonical = registry_path(str(record["resource_id"]))
    if receipt.resolve(strict=False) == canonical.resolve(strict=False):
        return False
    try:
        receipt.unlink()
        return True
    except FileNotFoundError:
        return False


def load_record(receipt: Path) -> Dict[str, Any]:
    record = read_json(receipt)
    required = {
        "format_version",
        "resource_id",
        "owner",
        "purpose",
        "profile",
        "state",
        "path",
        "resolved_path",
        "temp_root",
        "resolved_temp_root",
        "device",
        "inode",
        "created_at",
    }
    missing = sorted(required - set(record))
    if missing:
        raise ClaygoError("record is missing fields: {}".format(", ".join(missing)))
    if record["format_version"] != FORMAT_VERSION:
        raise ClaygoError("unsupported record format: {}".format(record["format_version"]))
    if record["profile"] not in PROFILES:
        raise ClaygoError("unsupported profile: {}".format(record["profile"]))
    if record["state"] not in STATES:
        raise ClaygoError("unsupported state: {}".format(record["state"]))
    return record


def receipt_is_outside(receipt: Path, candidate: Path) -> None:
    resolved = receipt.resolve(strict=False)
    if resolved == candidate or is_descendant(resolved, candidate):
        raise ClaygoError("receipt must live outside the cleanup candidate")


def validate_temp_boundary(candidate: Path, temp_root: Path, *, must_exist: bool) -> Tuple[Path, Path]:
    if not temp_root.exists() or not temp_root.is_dir():
        raise ClaygoError("temporary root is not an existing directory: {}".format(temp_root))
    resolved_root = temp_root.resolve(strict=True)
    resolved_candidate = candidate.resolve(strict=must_exist)
    if not is_descendant(resolved_candidate, resolved_root):
        raise ClaygoError("candidate must be a strict descendant of the temporary root")
    home = Path.home().resolve()
    filesystem_root = Path(resolved_candidate.anchor).resolve()
    if resolved_candidate in {home, filesystem_root, resolved_root}:
        raise ClaygoError("candidate resolves to a protected broad path")
    cwd = Path.cwd().resolve()
    if cwd == resolved_candidate or is_descendant(cwd, resolved_candidate):
        raise ClaygoError("current working directory is inside the candidate")
    return resolved_candidate, resolved_root


def ensure_no_symlink_components(candidate: Path, temp_root: Path) -> None:
    resolved_root = temp_root.resolve(strict=True)
    cursor = candidate
    while cursor.resolve(strict=False) != resolved_root:
        if lexists(cursor) and cursor.is_symlink():
            raise ClaygoError("candidate path component is a symlink: {}".format(cursor))
        parent = cursor.parent
        if parent == cursor:
            raise ClaygoError("candidate path does not reach temporary root")
        cursor = parent


def initialize_record(
    candidate: Path,
    temp_root: Path,
    receipt: Path,
    owner: str,
    purpose: str,
    profile: str,
    *,
    create: bool,
    worktree: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    if not owner.strip() or not purpose.strip():
        raise ClaygoError("owner and purpose must be non-empty")
    if profile not in PROFILES:
        raise ClaygoError("unsupported profile: {}".format(profile))
    if receipt.exists():
        raise ClaygoError("receipt already exists: {}".format(receipt))
    if create and lexists(candidate):
        raise ClaygoError("candidate already exists and cannot be adopted: {}".format(candidate))
    resolved_candidate, resolved_root = validate_temp_boundary(candidate, temp_root, must_exist=not create)
    ensure_no_symlink_components(candidate.parent if create else candidate, temp_root)
    receipt_is_outside(receipt, resolved_candidate)
    if not receipt.parent.exists() or not receipt.parent.is_dir():
        raise ClaygoError("receipt parent is not an existing directory: {}".format(receipt.parent))
    if create:
        os.mkdir(candidate, 0o700)
        resolved_candidate = candidate.resolve(strict=True)
    candidate_stat = os.stat(candidate, follow_symlinks=False)
    if not stat.S_ISDIR(candidate_stat.st_mode):
        raise ClaygoError("candidate is not a directory")
    for _, previous in records_for_owner(None):
        if previous.get("resolved_path") == os.fspath(resolved_candidate) and previous.get("state") != "removed":
            raise ClaygoError("an unresolved registry record already owns this path")
    resource_id = record_id(owner, resolved_candidate)
    record: Dict[str, Any] = {
        "format_version": FORMAT_VERSION,
        "resource_id": resource_id,
        "owner": owner,
        "purpose": purpose,
        "profile": profile,
        "state": "active",
        "reason": "created for active work" if create else "registered after creation",
        "path": os.fspath(candidate),
        "resolved_path": os.fspath(resolved_candidate),
        "temp_root": os.fspath(temp_root),
        "resolved_temp_root": os.fspath(resolved_root),
        "device": candidate_stat.st_dev,
        "inode": candidate_stat.st_ino,
        "created_at": utc_now(),
        "updated_at": utc_now(),
        "receipt": os.fspath(receipt),
        "evidence": [],
        "cleanup": None,
    }
    if worktree is not None:
        record["worktree"] = worktree
    save_record(record, receipt)
    return record


def validate_identity(record: Dict[str, Any], receipt: Path) -> Tuple[Path, Path]:
    candidate = absolute_path(str(record["path"]))
    temp_root = absolute_path(str(record["temp_root"]))
    if record["state"] == "removed":
        raise ClaygoError("resource is already removed")
    resolved_candidate, resolved_root = validate_temp_boundary(candidate, temp_root, must_exist=True)
    ensure_no_symlink_components(candidate, temp_root)
    receipt_is_outside(receipt, resolved_candidate)
    if os.fspath(resolved_candidate) != record["resolved_path"]:
        raise ClaygoError("candidate resolved path no longer matches the receipt")
    if os.fspath(resolved_root) != record["resolved_temp_root"]:
        raise ClaygoError("temporary root no longer matches the receipt")
    candidate_stat = os.stat(candidate, follow_symlinks=False)
    if candidate_stat.st_dev != record["device"] or candidate_stat.st_ino != record["inode"]:
        raise ClaygoError("candidate device or inode changed after registration")
    if not stat.S_ISDIR(candidate_stat.st_mode):
        raise ClaygoError("candidate is no longer a directory")
    return candidate, temp_root


def looks_like_bare_git(names: Set[str]) -> bool:
    folded = {name.casefold() for name in names}
    return {"head", "objects", "refs"}.issubset(folded) or {"commondir", "gitdir"}.issubset(folded)


def vcs_allowed(profile: str, path: Path, root: Path, marker: str) -> bool:
    if marker.casefold() != ".git":
        return False
    try:
        parts = [part.casefold() for part in path.relative_to(root).parts]
    except ValueError:
        return False
    if profile == "swiftpm":
        return "checkouts" in parts or "repositories" in parts
    if profile == "xcode-derived-data":
        return "sourcepackages" in parts and ("checkouts" in parts or "repositories" in parts)
    return False


def validate_internal_symlink(path: Path, root: Path) -> None:
    try:
        target = path.resolve(strict=False)
    except OSError as exc:
        raise ClaygoError("cannot resolve symlink {}: {}".format(path, exc)) from exc
    if target != root and not is_descendant(target, root):
        raise ClaygoError("symlink escapes candidate: {} -> {}".format(path, target))


def scan_candidate(root: Path, profile: str, max_entries: int) -> Dict[str, Any]:
    if max_entries < 0:
        raise ClaygoError("max entries must be zero or greater")
    root = root.resolve(strict=True)
    entries = 0
    logical_bytes = 0
    allocated_bytes = 0
    symlinks = 0
    vcs_markers = 0
    stack = [root]
    while stack:
        current = stack.pop()
        try:
            current_stat = os.stat(current, follow_symlinks=False)
            logical_bytes += current_stat.st_size
            allocated_bytes += getattr(current_stat, "st_blocks", 0) * 512
            children = list(os.scandir(current))
        except OSError as exc:
            raise ClaygoError("cannot inspect {}: {}".format(current, exc)) from exc
        names = {entry.name for entry in children}
        markers = sorted(name for name in names if name.casefold() in VCS_MARKERS)
        for marker in markers:
            marker_path = current / marker
            if not vcs_allowed(profile, marker_path, root, marker):
                raise ClaygoError("profile-incompatible VCS metadata: {}".format(marker_path))
            vcs_markers += 1
        if looks_like_bare_git(names) and not vcs_allowed(profile, current, root, ".git"):
            raise ClaygoError("bare or linked-worktree Git metadata found at {}".format(current))
        for entry in children:
            entries += 1
            if entries > max_entries:
                raise ClaygoError("entry limit exceeded ({}); require a bounded manual audit".format(max_entries))
            entry_path = Path(entry.path)
            try:
                entry_stat = entry.stat(follow_symlinks=False)
            except OSError as exc:
                raise ClaygoError("cannot stat {}: {}".format(entry_path, exc)) from exc
            if stat.S_ISLNK(entry_stat.st_mode):
                if profile == "generic":
                    raise ClaygoError("symlink is not allowed by generic profile: {}".format(entry_path))
                validate_internal_symlink(entry_path, root)
                symlinks += 1
                logical_bytes += entry_stat.st_size
                allocated_bytes += getattr(entry_stat, "st_blocks", 0) * 512
            elif stat.S_ISDIR(entry_stat.st_mode):
                stack.append(entry_path)
            elif stat.S_ISREG(entry_stat.st_mode):
                logical_bytes += entry_stat.st_size
                allocated_bytes += getattr(entry_stat, "st_blocks", 0) * 512
            else:
                raise ClaygoError("special file found: {}".format(entry_path))
    return {
        "entries": entries,
        "logical_bytes": logical_bytes,
        "allocated_bytes": allocated_bytes,
        "symlinks": symlinks,
        "vcs_markers": vcs_markers,
    }


def check_open_files(candidate: Path, timeout: int) -> Dict[str, Any]:
    if timeout <= 0:
        raise ClaygoError("open-file timeout must be greater than zero")
    executable = shutil.which("lsof") or "/usr/sbin/lsof"
    if not os.path.exists(executable):
        raise ClaygoError("open-file check requested but lsof is unavailable")
    try:
        result = subprocess.run(
            [executable, "+D", os.fspath(candidate)],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            timeout=timeout,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise ClaygoError("open-file check failed: {}".format(exc)) from exc
    lines = [line for line in result.stdout.splitlines() if line.strip()]
    data = lines[1:] if lines[:1] and lines[0].startswith("COMMAND") else lines
    if data:
        raise ClaygoError("open files reference candidate: {}".format(" | ".join(data[:5])))
    if result.returncode not in {0, 1}:
        detail = result.stderr.strip() or "exit {}".format(result.returncode)
        raise ClaygoError("lsof could not establish a safe result: {}".format(detail))
    return {"tool": executable, "open_files": 0}


def run_git(arguments: Sequence[str], cwd: Path, *, check: bool = True) -> subprocess.CompletedProcess:
    result = subprocess.run(
        ["/usr/bin/git", "-C", os.fspath(cwd)] + list(arguments),
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        check=False,
    )
    if check and result.returncode != 0:
        raise ClaygoError("git {} failed: {}".format(" ".join(arguments), result.stderr.strip() or result.stdout.strip()))
    return result


def validate_worktree(candidate: Path, record: Dict[str, Any]) -> Dict[str, Any]:
    worktree = record.get("worktree")
    if not isinstance(worktree, dict):
        raise ClaygoError("worktree record is missing worktree metadata")
    repository = absolute_path(str(worktree["repository"]))
    merged_into = str(worktree["merged_into"])
    top = run_git(["rev-parse", "--show-toplevel"], candidate).stdout.strip()
    if Path(top).resolve() != candidate.resolve():
        raise ClaygoError("registered path is not the worktree top level")
    status_text = run_git(["status", "--porcelain=v1", "--untracked-files=all"], candidate).stdout
    if status_text.strip():
        raise ClaygoError("worktree contains uncommitted or untracked work")
    head = run_git(["rev-parse", "HEAD"], candidate).stdout.strip()
    ancestor = run_git(["merge-base", "--is-ancestor", head, merged_into], candidate, check=False)
    if ancestor.returncode != 0:
        raise ClaygoError("worktree HEAD is not reachable from {}".format(merged_into))
    listing = run_git(["worktree", "list", "--porcelain"], repository).stdout
    expected = "worktree {}".format(candidate.resolve())
    if expected not in listing.splitlines():
        raise ClaygoError("registered repository no longer lists this worktree")
    return {"repository": os.fspath(repository), "merged_into": merged_into, "head": head}


def bounded_rmtree(candidate: Path, profile: str) -> int:
    repaired: Set[str] = set()
    current_uid = os.getuid()
    boundary = candidate.resolve(strict=True)

    def onerror(function: Any, path_text: str, exc_info: Any) -> None:
        path = Path(path_text)
        failure = exc_info[1]
        if not isinstance(failure, OSError) or failure.errno not in {errno.EACCES, errno.EPERM}:
            raise failure
        resolved_parent = path.parent.resolve(strict=False)
        if resolved_parent != boundary and not is_descendant(resolved_parent, boundary):
            raise ClaygoError("permission repair escaped candidate: {}".format(path))
        if profile not in GENERATED_PROFILES:
            raise exc_info[1]
        repair_targets = [path]
        cursor = path.parent
        while cursor.resolve(strict=False) != boundary:
            repair_targets.append(cursor)
            cursor = cursor.parent
        repair_targets.append(candidate)
        for target in repair_targets:
            item_stat = os.lstat(target)
            if item_stat.st_uid != current_uid:
                raise ClaygoError("permission repair refused non-owner path: {}".format(target))
            if stat.S_ISLNK(item_stat.st_mode):
                continue
            required = stat.S_IWUSR | (stat.S_IXUSR if stat.S_ISDIR(item_stat.st_mode) else 0)
            if item_stat.st_mode & required != required:
                os.chmod(target, item_stat.st_mode | required)
                repaired.add(os.fspath(target))
        function(path_text)

    shutil.rmtree(candidate, onerror=onerror)
    return len(repaired)


def mark_record(receipt: Path, state_value: str, reason: str) -> Dict[str, Any]:
    if state_value not in STATES - {"removed"}:
        raise ClaygoError("state must be active, evidence, disposable, or protected")
    if not reason.strip():
        raise ClaygoError("state transition requires a concrete reason")
    if state_value == "protected" and len(reason.strip()) < 12:
        raise ClaygoError("protected state requires a specific reason")
    record = load_record(receipt)
    if record["state"] == "removed":
        raise ClaygoError("removed resource cannot transition state")
    record["state"] = state_value
    record["reason"] = reason.strip()
    save_record(record, receipt)
    return record


def finalize_record(receipt: Path, *, require_open_files: bool, keep_receipt: bool = False) -> Dict[str, Any]:
    record = load_record(receipt)
    if record["state"] != "disposable":
        raise ClaygoError("resource must be marked disposable before finalization")
    candidate, _ = validate_identity(record, receipt)
    profile = str(record["profile"])
    open_result = check_open_files(candidate, 30) if require_open_files else None
    repaired = 0
    if profile == "git-worktree":
        worktree_result = validate_worktree(candidate, record)
        validate_identity(record, receipt)
        repository = absolute_path(worktree_result["repository"])
        run_git(["worktree", "remove", os.fspath(candidate)], repository)
        scan: Dict[str, Any] = {"entries": None, "logical_bytes": None, "allocated_bytes": None}
    else:
        worktree_result = None
        scan = scan_candidate(candidate, profile, DEFAULT_MAX_ENTRIES)
        validate_identity(record, receipt)
        repaired = bounded_rmtree(candidate, profile)
    if lexists(candidate):
        raise ClaygoError("candidate remains after finalization: {}".format(candidate))
    cleanup = {
        "removed_at": utc_now(),
        "scan": scan,
        "open_file_check": open_result,
        "permission_repairs": repaired,
        "worktree": worktree_result,
        "verified_absent": True,
    }
    record["state"] = "removed"
    record["reason"] = "exact absence verified"
    record["cleanup"] = cleanup
    save_record(record, receipt)
    receipt_removed = False if keep_receipt else remove_external_receipt(record, receipt)
    return {
        "status": "pass",
        "action": "finalize",
        "candidate": os.fspath(candidate),
        "profile": profile,
        "cleanup": cleanup,
        "receipt_removed": receipt_removed,
        "registry_record": record["registry_record"],
    }


def records_for_owner(owner: Optional[str] = None) -> List[Tuple[Path, Dict[str, Any]]]:
    records: List[Tuple[Path, Dict[str, Any]]] = []
    for path in sorted((state_root() / "resources").glob("*.json")):
        try:
            record = load_record(path)
        except ClaygoError:
            continue
        if owner is None or record["owner"] == owner:
            records.append((path, record))
    return records


def closeout_owner(owner: str, finalize_disposable: bool) -> Tuple[Dict[str, Any], int]:
    finalized: List[Dict[str, Any]] = []
    unresolved: List[Dict[str, Any]] = []
    accepted: List[Dict[str, Any]] = []
    for path, record in records_for_owner(owner):
        state_value = str(record["state"])
        if state_value == "removed":
            accepted.append({"path": record["path"], "state": state_value})
        elif state_value == "protected" and str(record.get("reason", "")).strip():
            accepted.append({"path": record["path"], "state": state_value, "reason": record["reason"]})
        elif state_value == "disposable" and finalize_disposable:
            try:
                finalized.append(finalize_record(path, require_open_files=True))
            except ClaygoError as exc:
                unresolved.append({"path": record["path"], "state": state_value, "error": str(exc)})
        else:
            unresolved.append({"path": record["path"], "state": state_value, "reason": record.get("reason")})
    payload = {
        "status": "pass" if not unresolved else "deny",
        "action": "closeout",
        "owner": owner,
        "finalized": finalized,
        "accepted": accepted,
        "unresolved": unresolved,
    }
    return payload, 0 if not unresolved else 2
