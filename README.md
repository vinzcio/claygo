# CLAYGO

Ownership-aware cleanup for coding agents.

## Why CLAYGO

CLAYGO stands for **Clean As You Go**: the work ethic of cleaning up as part of the work, while ownership and context are still clear, instead of leaving a risky purge for the end.

For coding agents, that means temporary artifacts are accounted for when they are created, kept only while they are useful, and removed at a safe waypoint with proof. The goal is not a spotless machine at any cost. It is disciplined work that does not leave a mess—or destroy live work while trying to clean one.

Coding agents create build trees, screenshots, module caches, review snapshots, scratch files, and browser tabs quickly. Finalizing them safely requires more than guessing which resource looks temporary.

CLAYGO gives every temporary artifact:

- an owner
- a lifecycle
- a protected boundary
- compact proof
- an exact-path cleanup gate

CLAYGO also gives task-owned browser tabs a lifecycle: close them as soon as their work is finished, without touching user-owned or other-task tabs.

In one real-world cleanup, this workflow reduced task-generated temporary storage by 27,804,260 KiB (26.516 GiB) while preserving active builds, source snapshots, proof evidence, repository files, captures, the installed app, and live agent sessions.

In a Codex-wide tab-hygiene case study, one completed task closed 49 task-owned tabs while preserving four user-owned tabs. Vincent observed Activity Monitor CPU fall immediately from about 100% to about 80%. During the same period, the 1-minute load average fell from 36.32 to 9.64 in about three minutes and to 7.65 in about five minutes. The whole-machine figures include concurrent-work effects, so the case reports them as observed outcomes rather than tabs-only causation. Read the [full case study](skills/claygo/references/codex-tab-hygiene-case-study.md).

## What makes it different

CLAYGO is not a disk cleaner or indiscriminate tab closer. It manages only roots and tabs created by the current task or explicitly authorized by their owner.

The bundled preflight helper creates provenance receipts, checks device and inode identity, rejects symlinks and VCS metadata, detects special files, optionally checks `lsof`, and produces machine-readable proof. It never deletes data.

## Install the Agent Skill

Install it with:

```text
$skill-installer install https://github.com/vinzcio/claygo/tree/main/skills/claygo
```

Restart Codex after installation. The repository also includes a skill-only Codex plugin manifest for plugin distribution.

## Use it

Ask Codex:

```text
Use $claygo for the temporary build and test artifacts in this task.
```

For browser-heavy or resource-contended work:

```text
Use $claygo to close task-owned browser tabs as soon as their work is finished.
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
- user-owned, unrelated, uncertain, or another active task's browser tabs
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
