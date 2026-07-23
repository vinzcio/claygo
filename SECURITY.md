# Security

CLAYGO influences destructive filesystem operations, so path-safety bypasses are security issues.

Please use GitHub's private vulnerability reporting for:

- deletion eligibility outside the recorded temporary boundary
- VCS, symlink, device, or inode checks that can be bypassed
- receipt confusion or path substitution
- behavior that mutates or deletes data from the preflight helper

Do not include real credentials, private paths, customer data, or proprietary source in a report. A minimal temporary-directory fixture is preferred.

The preflight helper deliberately never deletes data. Cleanup remains subject to the agent host's approval system and the user's exact authorization.
