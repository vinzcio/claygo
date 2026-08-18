---
name: claygo
description: Own, classify, finalize, and verify temporary build, test, cache, deployment, screenshot, worktree, browser-tab, and background-process resources. Use whenever a task may create disposable resources, at safe waypoints, during disk pressure, and before task closeout. Skip source-only work that creates no disposable resources.
---

# CLAYGO

CLAYGO is an ownership and lifecycle system, not a generic cache purge. Register every task-created disposable filesystem root before use, use the profile that matches its contents, and finalize it when its purpose ends. Do not let a task report successful completion with an unexplained `disposable`, `active`, or `evidence` resource.

The canonical executable is:

```bash
python3 ~/.codex/skills/claygo/scripts/claygo.py
```

## Register resources before use

Use a unique root for every task or worker. The receipt must live outside the candidate. Use the thread/session ID as `--owner` so the closeout hook can find it.

```bash
python3 ~/.codex/skills/claygo/scripts/claygo.py init \
  --path /private/tmp/<task-unique-root> \
  --temp-root /private/tmp \
  --receipt /tmp/<task-unique-root>-receipt.json \
  --owner <thread-or-session-id> \
  --purpose "focused build and tests" \
  --profile swiftpm
```

Profiles are safety policies, not labels:

- `generic`: strict; rejects every symlink, VCS marker, and special file.
- `swiftpm`: permits internal generated symlinks and dependency Git metadata only below SwiftPM `checkouts` or `repositories` directories.
- `xcode-derived-data`: permits internal generated symlinks and dependency Git metadata only below `SourcePackages/checkouts` or `SourcePackages/repositories`.
- `node-test`, `deployment`, `screenshot`: permit only profile-appropriate generated structure; VCS metadata remains blocked.

Read [references/resource-profiles.md](references/resource-profiles.md) before choosing a generated profile for an unusual tree.

Register temporary Git worktrees immediately after `git worktree add`:

```bash
python3 ~/.codex/skills/claygo/scripts/claygo.py register-worktree \
  --path /private/tmp/<worktree> \
  --temp-root /private/tmp \
  --receipt /tmp/<worktree>-receipt.json \
  --owner <thread-or-session-id> \
  --purpose "isolated implementation" \
  --repository /absolute/path/to/main-checkout \
  --merged-into origin/main
```

## Track lifecycle in the registry

The executable maintains machine-readable state under `~/.local/state/claygo/resources`. A Markdown ledger is optional human-readable context; it is not authoritative control state.

Use exactly one state:

- `active`: needed by current or imminent work.
- `evidence`: contains proof that must first be preserved elsewhere.
- `disposable`: purpose ended; safe finalization is now mandatory.
- `protected`: deliberately retained for a concrete verified reason.
- `removed`: exact absence verified.

Change state explicitly:

```bash
python3 ~/.codex/skills/claygo/scripts/claygo.py mark \
  --receipt /tmp/<receipt>.json \
  --state disposable \
  --reason "tests passed and proof is in the task transcript"
```

`protected` requires a specific reason. Do not use it for ordinary generated symlinks, dependency checkouts, cleanup inconvenience, or uncertainty.

For a version-1 receipt left by CLAYGO 0.2, first verify that the recorded owner and path still belong to the task, then migrate it into the registry with the correct profile and current state:

```bash
python3 ~/.codex/skills/claygo/scripts/claygo.py migrate-legacy \
  --receipt /tmp/<legacy-receipt>.json \
  --profile swiftpm \
  --state disposable \
  --reason "the original task completed and its proof is preserved"
```

Migration preserves and rechecks the original device/inode identity; it does not adopt an arbitrary existing path.

## Finalize at safe waypoints

Finalize a superseded retry root as soon as the replacement is proven. Finalize build/test roots after the last verification that needs them; merge alone is not sufficient if installation or live acceptance still depends on the artifact.

```bash
python3 ~/.codex/skills/claygo/scripts/claygo.py finalize \
  --receipt /tmp/<receipt>.json \
  --check-open-files
```

Finalization validates the receipt identity and profile, checks open handles, measures the root, deletes only the exact owned root, performs a bounded owner-only permission repair for generated profiles when required, verifies absence, persists compact cleanup proof, and removes the temporary receipt. It never follows cleanup globs.

For a registered worktree, `finalize` additionally requires a clean status and proves `HEAD` is reachable from the recorded `--merged-into` ref before calling `git worktree remove` without force. It does not delete branches automatically.

## Close out the owner

Before reporting success, run:

```bash
python3 ~/.codex/skills/claygo/scripts/claygo.py closeout \
  --owner <thread-or-session-id> \
  --finalize-disposable
```

Closeout automatically finalizes receipted `disposable` resources. It fails while any owned resource remains `active` or `evidence`, or when cleanup fails. Resolve each failure or mark a genuinely retained resource `protected` with a concrete reason. The user-level stop hook repeats this guard if the task forgets.

Use `reconcile --all-disposable` only for receipted resources already marked `disposable`; it never adopts unregistered paths or infers ownership from age or naming.

## Browser tabs and processes

Track task-owned tabs and background processes in the task ledger and close or stop them at the same safe waypoints. User-owned browser tabs are never task-owned merely because this task inspected them. The filesystem registry does not grant authority over tabs or processes.

## Hard protections

Never use CLAYGO to remove or mutate:

- Unregistered or pre-existing paths without exact user authorization.
- Repository source, dirty/unmerged worktrees, uncommitted or untracked work, `.jj`, installed apps, app data, documents, credentials, databases, live logs, Codex/Claude state, memories, sessions, or another task's resources.
- A symlink whose resolved target escapes the exact receipted root.
- A root with open handles, changed device/inode identity, unreadable contents, special files, or profile-incompatible VCS metadata.
- OS-managed swap, snapshots, virtual-memory files, or security databases.

Never use `git clean`, `git gc`, `git prune`, `git reset`, `jj abandon`, project-wide deletion, broad globs, or forced worktree removal as CLAYGO cleanup.

If ownership or classification is uncertain, audit and report. Do not convert uncertainty into `protected`; determine the owner or leave the unregistered path untouched.

## Closeout report

Report exact paths and measured sizes removed; worktrees finalized; resources protected and why; open-file/process results; bounded permission repairs; free-space samples when relevant; and any unresolved owner records. Distinguish measured allocations from APFS free-space changes.
