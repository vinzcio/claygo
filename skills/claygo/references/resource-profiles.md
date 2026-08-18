# CLAYGO resource profiles

Profiles let the cleanup scanner distinguish expected generated structure from source or ambiguous data. They never weaken ownership, identity, open-file, containment, or exact-path requirements.

## generic

Use for ordinary scratch containing regular files and directories. Any symlink, VCS marker, bare-repository signature, or special file denies finalization.

## swiftpm

Use only for a root passed as SwiftPM's `--scratch-path`, or a task root whose build subtree is used that way.

Allowed:

- Symlinks whose fully resolved targets remain inside the receipted root, including `debug -> <triple>/debug` and framework version links.
- `.git` metadata and bare Git repositories only below a directory named `checkouts` or `repositories`.

Denied:

- Candidate-root or arbitrary nested repositories.
- `.jj`, `.hg`, `.svn`, `.bzr`, and `_darcs` anywhere.
- External or unreadable symlinks and special files.

## xcode-derived-data

Use only for an explicitly selected DerivedData root created for the task.

Allowed:

- Internal generated symlinks.
- Dependency Git metadata below `SourcePackages/checkouts` or `SourcePackages/repositories`.

Do not point this profile at the user's shared Xcode DerivedData directory unless the current task created and exclusively owns the exact descendant root.

## node-test

Use for a task-owned test/build root that may contain `node_modules` and internal package-manager symlinks. VCS markers and external symlinks remain denied.

## deployment

Use for task-created deployment candidates and staging copies. Internal symlinks are allowed; VCS metadata remains denied. Preserve deployment manifests or hashes outside the candidate before marking it disposable.

## screenshot

Use for task-created capture/export roots. Internal symlinks are allowed only for containment consistency; VCS metadata remains denied. Durable deliverables must be moved outside the candidate before finalization.

## git-worktree

Created only through `register-worktree`. Finalization requires:

- The registered path is still listed as a worktree of the recorded repository.
- `git status --porcelain --untracked-files=all` is empty.
- The current `HEAD` is an ancestor of the recorded merged ref.
- No open handle references the worktree.
- `git worktree remove` succeeds without `--force` and exact absence is verified.

Branch deletion is intentionally separate. A merged branch may still be useful and must not be deleted implicitly.
