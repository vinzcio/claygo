#!/usr/bin/env python3

import json
import os
import stat
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
SKILL_ROOT = REPO_ROOT / "skills/claygo"
CLI = SKILL_ROOT / "scripts/claygo.py"
HOOK = SKILL_ROOT / "scripts/claygo_closeout_hook.py"


class ClaygoCLITests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="claygo-tests-")
        self.root = Path(self.temporary.name)
        self.state = self.root / "state"
        self.env = os.environ.copy()
        self.env["CLAYGO_STATE_DIR"] = str(self.state)

    def tearDown(self):
        self.temporary.cleanup()

    def run_cli(self, *arguments, expected=0):
        result = subprocess.run(
            [sys.executable, str(CLI), *map(str, arguments)],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            env=self.env,
            check=False,
        )
        self.assertEqual(result.returncode, expected, msg=result.stdout + result.stderr)
        return json.loads(result.stdout)

    def init(self, name="candidate", profile="generic", owner="owner"):
        candidate = self.root / name
        receipt = self.root / (name + "-receipt.json")
        payload = self.run_cli(
            "init",
            "--path", candidate,
            "--temp-root", self.root,
            "--receipt", receipt,
            "--owner", owner,
            "--purpose", "regression test",
            "--profile", profile,
        )
        return candidate, receipt, Path(payload["record"]["registry_record"])

    def mark_disposable(self, receipt):
        return self.run_cli(
            "mark", "--receipt", receipt, "--state", "disposable",
            "--reason", "test proof was preserved outside the candidate",
        )

    def test_generic_finalize_removes_root_and_temporary_receipt(self):
        candidate, receipt, registry = self.init()
        (candidate / "proof.txt").write_text("temporary", encoding="utf-8")
        self.mark_disposable(receipt)
        result = self.run_cli("finalize", "--receipt", receipt, "--check-open-files")
        self.assertFalse(candidate.exists())
        self.assertFalse(receipt.exists())
        self.assertTrue(registry.exists())
        self.assertEqual(json.loads(registry.read_text())["state"], "removed")
        self.assertTrue(result["cleanup"]["verified_absent"])

    def test_generic_profile_denies_symlink(self):
        candidate, receipt, _ = self.init()
        (candidate / "target").write_text("x", encoding="utf-8")
        (candidate / "link").symlink_to("target")
        self.mark_disposable(receipt)
        result = self.run_cli("finalize", "--receipt", receipt, expected=2)
        self.assertIn("symlink", result["error"])
        self.assertTrue(candidate.exists())

    def test_swiftpm_allows_internal_symlinks_and_checkout_git_metadata(self):
        candidate, receipt, _ = self.init(profile="swiftpm")
        debug = candidate / "arm64-apple-macosx/debug"
        debug.mkdir(parents=True)
        (debug / "artifact").write_text("built", encoding="utf-8")
        (candidate / "debug").symlink_to("arm64-apple-macosx/debug")
        checkout_git = candidate / "checkouts/Sparkle/.git/objects"
        checkout_git.mkdir(parents=True)
        (checkout_git / "object").write_text("generated dependency", encoding="utf-8")
        self.mark_disposable(receipt)
        result = self.run_cli("finalize", "--receipt", receipt)
        self.assertFalse(candidate.exists())
        self.assertEqual(result["cleanup"]["scan"]["symlinks"], 1)
        self.assertEqual(result["cleanup"]["scan"]["vcs_markers"], 1)

    def test_swiftpm_denies_external_symlink(self):
        candidate, receipt, _ = self.init(profile="swiftpm")
        outside = self.root / "outside.txt"
        outside.write_text("preserve", encoding="utf-8")
        (candidate / "escape").symlink_to(outside)
        self.mark_disposable(receipt)
        result = self.run_cli("finalize", "--receipt", receipt, expected=2)
        self.assertIn("escapes", result["error"])
        self.assertEqual(outside.read_text(), "preserve")

    def test_swiftpm_denies_repository_at_candidate_root(self):
        candidate, receipt, _ = self.init(profile="swiftpm")
        (candidate / ".git/objects").mkdir(parents=True)
        self.mark_disposable(receipt)
        result = self.run_cli("finalize", "--receipt", receipt, expected=2)
        self.assertIn("profile-incompatible VCS", result["error"])

    def test_inode_replacement_is_denied(self):
        candidate, receipt, _ = self.init()
        moved = self.root / "moved-original"
        candidate.rename(moved)
        candidate.mkdir()
        self.mark_disposable(receipt)
        result = self.run_cli("finalize", "--receipt", receipt, expected=2)
        self.assertIn("inode changed", result["error"])
        self.assertTrue(candidate.exists())
        self.assertTrue(moved.exists())

    def test_open_handle_is_denied(self):
        candidate, receipt, _ = self.init()
        path = candidate / "held.txt"
        path.write_text("open", encoding="utf-8")
        self.mark_disposable(receipt)
        with path.open("r", encoding="utf-8"):
            result = self.run_cli("finalize", "--receipt", receipt, "--check-open-files", expected=2)
        self.assertIn("open files", result["error"])
        self.assertTrue(candidate.exists())

    def test_generated_profile_repairs_owner_read_only_directory(self):
        candidate, receipt, _ = self.init(profile="deployment")
        locked = candidate / "locked"
        locked.mkdir()
        (locked / "file").write_text("generated", encoding="utf-8")
        locked.chmod(stat.S_IRUSR | stat.S_IXUSR)
        self.mark_disposable(receipt)
        result = self.run_cli("finalize", "--receipt", receipt)
        self.assertFalse(candidate.exists())
        self.assertGreaterEqual(result["cleanup"]["permission_repairs"], 1)

    def test_closeout_blocks_active_and_finalizes_disposable(self):
        candidate, receipt, _ = self.init(owner="closeout-owner")
        denied = self.run_cli(
            "closeout", "--owner", "closeout-owner", "--finalize-disposable", expected=2
        )
        self.assertEqual(denied["unresolved"][0]["state"], "active")
        self.mark_disposable(receipt)
        passed = self.run_cli(
            "closeout", "--owner", "closeout-owner", "--finalize-disposable"
        )
        self.assertEqual(passed["status"], "pass")
        self.assertFalse(candidate.exists())

    def test_closeout_accepts_specific_protected_reason(self):
        _, receipt, _ = self.init(owner="protected-owner")
        self.run_cli(
            "mark", "--receipt", receipt, "--state", "protected",
            "--reason", "user requested this clean worktree remain for tomorrow's review",
        )
        result = self.run_cli(
            "closeout", "--owner", "protected-owner", "--finalize-disposable"
        )
        self.assertEqual(result["accepted"][0]["state"], "protected")

    def test_reconcile_finalizes_disposable_without_touching_same_owner_active_root(self):
        disposable, disposable_receipt, _ = self.init(name="disposable", owner="mixed-owner")
        active, _, _ = self.init(name="active", owner="mixed-owner")
        self.mark_disposable(disposable_receipt)
        result = self.run_cli("reconcile", "--all-disposable")
        self.assertEqual(result["status"], "pass")
        self.assertFalse(disposable.exists())
        self.assertTrue(active.exists())

    def test_legacy_receipt_can_be_migrated_and_finalized_with_swiftpm_profile(self):
        candidate = self.root / "legacy-swiftpm"
        candidate.mkdir()
        (candidate / "arm64-apple-macosx/debug").mkdir(parents=True)
        (candidate / "debug").symlink_to("arm64-apple-macosx/debug")
        candidate_stat = candidate.stat()
        receipt = self.root / "legacy-receipt.json"
        receipt.write_text(json.dumps({
            "format_version": 1,
            "owner": "legacy-owner",
            "purpose": "old SwiftPM test root",
            "path": str(candidate),
            "resolved_path": str(candidate.resolve()),
            "temp_root": str(self.root),
            "resolved_temp_root": str(self.root.resolve()),
            "device": candidate_stat.st_dev,
            "inode": candidate_stat.st_ino,
            "created_at": "2026-08-18T00:00:00+00:00",
            "state": "active",
        }), encoding="utf-8")
        self.run_cli(
            "migrate-legacy", "--receipt", receipt, "--profile", "swiftpm",
            "--state", "disposable",
            "--reason", "the original task completed and preserved its test proof",
        )
        result = self.run_cli("finalize", "--receipt", receipt)
        self.assertFalse(candidate.exists())
        self.assertEqual(result["profile"], "swiftpm")

    def test_merged_clean_worktree_is_removed_without_force(self):
        repository = self.root / "repository"
        worktree = self.root / "feature-worktree"
        repository.mkdir()
        self.git(repository, "init", "-b", "main")
        self.git(repository, "config", "user.email", "claygo@example.test")
        self.git(repository, "config", "user.name", "CLAYGO Test")
        (repository / "base.txt").write_text("base", encoding="utf-8")
        self.git(repository, "add", "base.txt")
        self.git(repository, "commit", "-m", "base")
        self.git(repository, "worktree", "add", "-b", "feature", str(worktree))
        (worktree / "feature.txt").write_text("feature", encoding="utf-8")
        self.git(worktree, "add", "feature.txt")
        self.git(worktree, "commit", "-m", "feature")
        self.git(repository, "merge", "--ff-only", "feature")
        receipt = self.root / "worktree-receipt.json"
        self.run_cli(
            "register-worktree",
            "--path", worktree,
            "--temp-root", self.root,
            "--receipt", receipt,
            "--owner", "worktree-owner",
            "--purpose", "merged implementation",
            "--repository", repository,
            "--merged-into", "main",
        )
        self.mark_disposable(receipt)
        result = self.run_cli("finalize", "--receipt", receipt)
        self.assertFalse(worktree.exists())
        self.assertEqual(result["cleanup"]["worktree"]["merged_into"], "main")

    def test_stop_hook_blocks_active_then_finalizes_disposable(self):
        candidate, receipt, _ = self.init(owner="hook-owner")
        hook_env = self.env.copy()
        hook_env["CLAYGO_CLI"] = str(CLI)
        event = json.dumps({"session_id": "hook-owner"})
        denied = subprocess.run(
            [sys.executable, str(HOOK)], input=event, text=True,
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, env=hook_env, check=False,
        )
        self.assertEqual(denied.returncode, 2)
        self.assertIn("blocked successful task closeout", denied.stderr)
        self.mark_disposable(receipt)
        passed = subprocess.run(
            [sys.executable, str(HOOK)], input=event, text=True,
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, env=hook_env, check=False,
        )
        self.assertEqual(passed.returncode, 0, msg=passed.stdout + passed.stderr)
        self.assertFalse(candidate.exists())

    def git(self, cwd, *arguments):
        result = subprocess.run(
            ["/usr/bin/git", "-C", str(cwd), *arguments],
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, check=False,
        )
        self.assertEqual(result.returncode, 0, msg=result.stdout + result.stderr)
        return result


if __name__ == "__main__":
    unittest.main()
