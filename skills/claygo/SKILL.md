---
name: claygo
description: Manage temporary build, test, review, snapshot, module-cache, and scratch artifacts with explicit ownership, lifecycle states, compact proof, and exact-path cleanup gates. Use when work will create or audit temporary artifacts, during disk-pressure cleanup, or at task closeout. Do not trigger for source-only edits that create no disposable artifacts.
---

# CLAYGO

Keep temporary storage proportional to active work. Give each artifact an owner and lifecycle, preserve compact proof, and remove only exact roots that are proven disposable.

## Establish ownership

1. Give every task and concurrent worker unique scratch, build, cache, and snapshot roots.
2. Record every root immediately in `/tmp/<project>-<task>-claygo.md`. Start from `assets/ledger-template.md`.
3. Prefer deterministic provenance for new scratch roots:

```bash
python3 scripts/claygo_preflight.py init \
  --path /absolute/temp-root/task-unique-name \
  --temp-root /absolute/temp-root \
  --receipt /absolute/path/outside-the-root/receipt.json \
  --owner task-or-thread-id \
  --purpose "build and test"
```

4. Treat a pre-existing or unreceipted path as unowned. Audit and report it; do not adopt or delete it without exact user or coordinator authorization.

## Track the lifecycle

Use exactly one state per root:

- `active`: required by running or imminent work.
- `evidence`: compact logs, manifests, hashes, or notes required for closeout.
- `disposable`: purpose ended and useful evidence exists elsewhere.
- `removed`: exact path is absent and verification passed.

Move roots to `disposable` after proof, abort, supersession, or release inclusion. Never interrupt useful active work solely to clean it.

## Keep artifacts lean

- Prefer source-only snapshots.
- Keep dependency and build caches separate from source snapshots.
- Exclude dependency trees, build outputs, VCS metadata, and unrelated working files unless the proof explicitly requires them.
- Preserve command, result, test counts, relevant hashes, accepted findings, and remaining work instead of entire build trees.

## Choose the cleanup level

Use lightweight closeout for a small, newly created, receipted root with no unusual contents. Record its exact path, size, evidence, and result.

Use full audit for large roots, disk pressure, shared environments, cross-worker cleanup, permission problems, or uncertain classification:

1. Measure free space on the target filesystem.
2. Check for concurrent heavy work without interrupting it.
3. Measure allocated size.
4. Check processes and open files when the platform supports it.
5. Record before/after free space and concurrent-write caveats.

## Run the cleanup gate

Immediately before deletion, run:

```bash
python3 scripts/claygo_preflight.py check \
  --receipt /absolute/path/to/receipt.json \
  --check-open-files
```

Require a passing result. The helper verifies exact path identity, the recorded temporary boundary, device and inode, symlink absence, VCS absence, special-file absence, and optional `lsof` results. It never deletes.

Then:

1. Confirm useful evidence exists outside the candidate.
2. Obtain any approval required by the host environment.
3. Delete only the exact whole root. Never use cleanup globs or cleanup-oriented VCS commands.
4. Do not change permissions by default. If permissions block removal, stop and report unless the user explicitly authorizes a bounded repair.
5. Verify absence:

```bash
python3 scripts/claygo_preflight.py verify-removed \
  --receipt /absolute/path/to/receipt.json
```

## Hard protections

Never delete or mutate these as CLAYGO cleanup:

- Repository source, worktrees, uncommitted work, `.git`, `.jj`, `.hg`, `.svn`, `.bzr`, `_darcs`, linked-worktree pointers, or bare repositories.
- Installed apps, app data, documents, media, recordings, captures, OneDrive placeholders, or user-selected data.
- Active work, current release snapshots, the only evidence copy, manifests, receipts, ledgers, or progress notes.
- Credentials, auth state, keychains, configuration, automations, installed skills, databases, SQLite/WAL state, or live logs.
- Codex chats, threads, sessions, rollouts, memories, prompts, durable history, or another task's paths.
- OS-managed swap, system snapshots, virtual-memory files, or security databases.

Never run `git clean`, `git gc`, `git prune`, `git reset`, `git worktree remove`, `jj abandon`, `jj forget`, project-wide `find -delete`, or an equivalent command as CLAYGO cleanup.

If ownership, classification, path identity, process state, or evidence is uncertain, stop after the audit and report the uncertainty.

## Close out

Report exact removed paths and pre-cleanup sizes, protected or skipped paths and reasons, preserved evidence, process/open-file results, permission changes or the absence of them, free space before and after when measured, and remaining owner-confirmation candidates. Do not attribute all observed free-space change to CLAYGO when APFS clones, hard links, sparse files, concurrent builds, or other writes can affect the result.
