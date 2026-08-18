# Security

CLAYGO performs destructive filesystem finalization, so ownership, containment, and identity bypasses are security issues.

Please use GitHub's private vulnerability reporting for:

- deletion outside the exact registered temporary boundary
- external-symlink traversal or root-substitution races
- device/inode, VCS-profile, open-file, or worktree-merge checks that can be bypassed
- unauthorized permission repair
- lifecycle or registry confusion that lets one owner finalize another owner's resource
- stop-hook behavior that deletes a resource not explicitly marked disposable

Do not include credentials, private paths, customer data, or proprietary source in a report. Use a minimal temporary-directory fixture.

## Trust boundary

The finalizer operates only on version-2 records created by `init`, `register-worktree`, or explicit migration of a valid version-1 receipt. It requires the candidate to retain its registered device and inode and to remain a strict descendant of its recorded temporary root.

Profiles may permit expected generated structure, but they never permit an external symlink target:

- `generic` permits no symlinks or VCS metadata.
- `swiftpm` permits Git metadata only under `checkouts` or `repositories`.
- `xcode-derived-data` permits Git metadata only under `SourcePackages/checkouts` or `SourcePackages/repositories`.
- Other generated profiles permit internal symlinks but no VCS metadata.
- Worktrees require clean status and proof that `HEAD` is reachable from the recorded merged ref before non-forced `git worktree remove`.

Permission repair is restricted to generated profiles, the exact registered boundary, and filesystem entries owned by the current user. It runs only in response to `EACCES` or `EPERM` during exact-root removal.

The registry is compact cleanup evidence, not an authorization source for unregistered paths. CLAYGO never adopts a path from its name, age, or apparent contents.

This remains defense in depth rather than a security sandbox. Host approval controls, filesystem permissions, and operating-system protections still apply.
