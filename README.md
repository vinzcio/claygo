# CLAYGO

Ownership-aware cleanup for coding agents.

## Why CLAYGO

CLAYGO stands for **Clean As You Go**: the work ethic of cleaning up as part of the work, while ownership and context are still clear, instead of leaving a risky purge for the end.

For coding agents, that means temporary artifacts are accounted for when they are created, kept only while they are useful, and removed at a safe waypoint with proof. The goal is not a spotless machine at any cost. It is disciplined work that does not leave a mess—or destroy live work while trying to clean one.

Coding agents create build trees, screenshots, module caches, review snapshots, and scratch files quickly. Deleting them safely requires more than guessing which folder looks temporary.

CLAYGO gives every temporary artifact:

- an owner
- a lifecycle
- a protected boundary
- compact proof
- an exact-path cleanup gate

In one real-world cleanup, this workflow reduced task-generated temporary storage by 27,804,260 KiB (26.516 GiB) while preserving active builds, source snapshots, proof evidence, repository files, captures, the installed app, and live agent sessions.

## What makes it different

CLAYGO is not a disk cleaner and does not search your machine for things to delete. It manages only roots created by the current task or explicitly authorized by their owner.

The bundled preflight helper creates provenance receipts, checks device and inode identity, rejects symlinks and VCS metadata, detects special files, optionally checks `lsof`, and produces machine-readable proof. It never deletes data.

## Install the Agent Skill

After this repository is published:

```text
$skill-installer install https://github.com/vinzcio/claygo/tree/main/skills/claygo
```

Restart Codex after installation. The repository also includes a skill-only Codex plugin manifest for plugin distribution.

## Use it

Ask Codex:

```text
Use $claygo for the temporary build and test artifacts in this task.
```

For deterministic ownership, create a new scratch root and receipt:

```bash
python3 skills/claygo/scripts/claygo_preflight.py init \
  --path /private/tmp/my-project-task-unique \
  --temp-root /private/tmp \
  --receipt /tmp/my-project-task-receipt.json \
  --owner task-unique \
  --purpose "build and test"
```

Immediately before cleanup:

```bash
python3 skills/claygo/scripts/claygo_preflight.py check \
  --receipt /tmp/my-project-task-receipt.json \
  --check-open-files
```

The helper returns JSON and never performs deletion. The agent must still preserve evidence, obey host approvals, delete only the exact path, and verify absence.

## Safety model

CLAYGO rejects or protects:

- unknown and pre-existing ownership
- repositories, worktrees, VCS metadata, and bare Git repositories
- symlinks and path-identity changes
- special files and optionally open files
- source, user data, credentials, agent history, installed apps, and active work
- permission mutation unless a user explicitly authorizes a bounded repair

This is defense in depth, not a security sandbox. A malicious local process can still race or tamper with filesystem state. Re-run preflight immediately before cleanup and use the operating system and agent host's approval controls.

## Compatibility

- The Agent Skill uses the open `SKILL.md` format.
- The plugin manifest targets Codex.
- The preflight helper uses Python's standard library.
- The optional open-file check currently requires `lsof`, normally available on macOS and many Linux systems.

## Development

Run the adversarial evaluations:

```bash
CLAYGO_TEST_ROOT=/private/tmp/claygo-tests \
  python3 -m unittest discover -s evals -p 'test_*.py' -v
```

The test root must not already exist. Tests create and remove only that exact root.

## License

MIT
