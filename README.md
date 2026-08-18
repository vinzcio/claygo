# CLAYGO

Ownership-aware lifecycle and cleanup for coding-agent resources.

## Why CLAYGO

CLAYGO stands for **Clean As You Go**: temporary resources are owned when created, kept only while useful, and finalized at a safe waypoint instead of accumulating until a risky emergency purge.

Coding agents create build trees, dependency checkouts, screenshots, module caches, deployment candidates, worktrees, browser tabs, and background processes. A useful cleanup system must remove finished resources without guessing which paths are safe.

CLAYGO gives every registered filesystem resource:

- an owner and purpose
- a typed safety profile
- device and inode identity
- a machine-readable lifecycle
- exact-path finalization and absence proof
- a closeout guard that rejects unexplained leftovers

It also keeps task-owned browser tabs and processes in the same lifecycle discipline without treating user-owned resources as task property.

## What changed in 0.3

Earlier CLAYGO releases deliberately stopped at a preflight check. That was safe but operationally incomplete: normal SwiftPM framework symlinks and dependency `.git` metadata blocked cleanup, lifecycle state lived in handwritten Markdown, and agents could finish with gigabytes of disposable output still present.

CLAYGO 0.3 adds:

- profile-aware generated-tree validation
- an atomic `finalize` command that validates, deletes, and verifies the exact resource
- a durable per-resource registry under `~/.local/state/claygo`
- explicit `active`, `evidence`, `disposable`, `protected`, and `removed` states
- owner closeout and disposable-resource reconciliation
- clean, merged Git-worktree finalization without `--force`
- bounded owner-only permission repair inside receipted generated roots
- a deterministic stop-hook helper
- legacy version-1 receipt migration

The strict `generic` profile still rejects every symlink, VCS marker, and special file. Generated profiles allow only their expected internal structure; external symlinks, actual repositories, changed identities, open handles, and ambiguous ownership remain denied.

## Install the Agent Skill

```text
$skill-installer install https://github.com/vinzcio/claygo/tree/main/skills/claygo
```

Restart the agent host after installation.

The optional user-level stop hook can call `skills/claygo/scripts/claygo_closeout_hook.py` on the host's `stop` event. It finalizes resources already marked `disposable` and blocks successful closeout while owned resources remain unexplained.

## Register a resource

```bash
python3 skills/claygo/scripts/claygo.py init \
  --path /private/tmp/my-project-task \
  --temp-root /private/tmp \
  --receipt /tmp/my-project-task-receipt.json \
  --owner "$THREAD_ID" \
  --purpose "Swift build and focused tests" \
  --profile swiftpm
```

Available profiles:

- `generic`
- `swiftpm`
- `xcode-derived-data`
- `node-test`
- `deployment`
- `screenshot`
- `git-worktree` through `register-worktree`

See [resource profiles](skills/claygo/references/resource-profiles.md) for their exact boundaries.

## Finalize a finished resource

```bash
python3 skills/claygo/scripts/claygo.py mark \
  --receipt /tmp/my-project-task-receipt.json \
  --state disposable \
  --reason "tests passed and proof is preserved in the task transcript"

python3 skills/claygo/scripts/claygo.py finalize \
  --receipt /tmp/my-project-task-receipt.json \
  --check-open-files
```

Finalization scans the profile, revalidates device/inode identity immediately before deletion, checks open handles when requested, deletes only the exact candidate, verifies absence, writes compact proof to the registry, and removes the temporary receipt.

## Enforce task closeout

```bash
python3 skills/claygo/scripts/claygo.py closeout \
  --owner "$THREAD_ID" \
  --finalize-disposable
```

Closeout succeeds only when every owned resource is removed or concretely protected. It rejects remaining `active` and `evidence` resources and reports cleanup failures rather than pretending the task is complete.

`reconcile --all-disposable` finalizes only resources already explicitly marked `disposable`. It never infers ownership from age, names, or location.

For a version-1 receipt from CLAYGO 0.2, use `migrate-legacy` only after verifying the recorded owner and path. Supply the correct profile, lifecycle state, and a concrete reason; migration rechecks the original device/inode identity before adding the resource to the registry.

## Git worktrees

Register a task-created clean worktree immediately after `git worktree add`. At finalization CLAYGO requires:

- clean tracked and untracked status
- `HEAD` reachable from the recorded merged ref
- membership in the recorded repository's worktree list
- zero open handles when closeout runs
- successful `git worktree remove` without force

Branch deletion remains a separate explicit decision.

## Safety model

CLAYGO denies cleanup when it finds:

- unknown or pre-existing ownership
- changed device/inode identity
- external or unreadable symlinks
- profile-incompatible VCS metadata or actual repositories
- dirty or unmerged worktrees
- special files or open handles
- source, user data, credentials, databases, agent state, installed apps, or another task's resources
- permission failures outside a receipted generated root owned by the current user

This is defense in depth, not a security sandbox. A malicious local process can still race local filesystem operations. CLAYGO revalidates identity immediately before finalization and uses Python's symlink-resistant `shutil.rmtree` implementation where the platform provides it.

## Browser-tab evidence

In a Codex-wide tab-hygiene case study, one completed task closed 49 task-owned tabs while preserving four user-owned tabs. Vincent observed Activity Monitor CPU fall immediately from about 100% to about 80%. During the same period, the 1-minute load average fell from 36.32 to 9.64 in about three minutes and to 7.65 in about five minutes. Whole-machine figures include concurrent-work effects. Read the [full case study](skills/claygo/references/codex-tab-hygiene-case-study.md).

## Development

Run all evaluations in an exact test-owned root:

```bash
CLAYGO_TEST_ROOT=/private/tmp/claygo-tests \
CLAYGO_STATE_DIR=/private/tmp/claygo-tests-state \
PYTHONDONTWRITEBYTECODE=1 \
  python3 -m unittest discover -s evals -p 'test_*.py' -v
```

The test roots must not already exist. Evaluations cover generic strictness, SwiftPM internal links and dependency metadata, external-link escapes, changed inodes, open handles, permission repair, legacy receipts, reconciliation, merged-worktree removal, and stop-hook behavior.

## License

MIT
