---
name: claygo
description: Manage temporary build, test, review, snapshot, module-cache, scratch, and browser-tab resources with explicit ownership, lifecycle states, compact proof, and exact-path cleanup gates. Use when work will create or audit temporary resources, during disk or host pressure, or at task closeout. Do not trigger for source-only edits that create no disposable resources.
---

# CLAYGO

Keep temporary resource use proportional to active work. Give each artifact or browser tab an owner and lifecycle, preserve compact proof, and remove only exact roots or finalize only tabs that are proven disposable.

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

For browser work, record the stable tab identifier or handle, surface or URL, purpose, ownership evidence, lifecycle state, and keep condition. A tab is task-owned only when the current task opened it or its owner explicitly transferred it. Do not infer ownership from content or recency.

## Track the lifecycle

Use exactly one state per resource:

- `active`: required by running or imminent work.
- `evidence`: compact logs, manifests, hashes, or notes required for closeout.
- `disposable`: purpose ended and useful evidence exists elsewhere.
- `removed`: an exact filesystem path is absent and verification passed, or an owned browser tab was finalized and is no longer open.

Move resources to `disposable` after proof, abort, supersession, or release inclusion. Never interrupt useful active work solely to clean it.

## Keep browser tabs lean

- Keep a task-owned tab open only while it is actively needed or intentionally waiting for user review, approval, or input.
- At safe waypoints and final closeout, audit owned tabs and promptly finalize or close stale and finished tabs through the browser provider's supported mechanism.
- Preserve the URL or durable artifact link when it is useful evidence; an open tab is not durable proof.
- Never close user-owned, unrelated, or another active task's tabs. When ownership is uncertain, leave the tab open and report it.
- Report tabs closed, tabs intentionally kept with reasons, and tabs skipped because ownership was uncertain.
- Do not defer finished-tab cleanup to a special pause. Make it part of each task's normal safe-waypoint and closeout flow.

Read `references/codex-tab-hygiene-case-study.md` when quantifying the observed impact of continuous tab hygiene.

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

Immediately before filesystem deletion, run:

```bash
python3 scripts/claygo_preflight.py check \
  --receipt /absolute/path/to/receipt.json \
  --check-open-files
```

Require a passing result. The helper verifies exact path identity, the recorded temporary boundary, device and inode, symlink absence, VCS absence, special-file absence, and optional `lsof` results. It never deletes and does not operate on browser tabs.

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

Report exact removed paths and pre-cleanup sizes; tabs closed, intentionally kept, or skipped; protected paths and reasons; preserved evidence; process/open-file results; permission changes or their absence; free space and host load before and after when measured; and remaining owner-confirmation candidates. Do not attribute all observed resource change to CLAYGO when APFS behavior or concurrent work can affect the result.
