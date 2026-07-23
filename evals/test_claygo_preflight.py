import json
import os
import shutil
import subprocess
import sys
import unittest
import uuid
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPT = REPO_ROOT / "skills" / "claygo" / "scripts" / "claygo_preflight.py"


class ClaygoPreflightTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        configured = os.environ.get("CLAYGO_TEST_ROOT")
        if not configured:
            raise unittest.SkipTest("CLAYGO_TEST_ROOT must name an exact owned test root")
        cls.root = Path(configured)
        if not cls.root.is_absolute():
            raise RuntimeError("CLAYGO_TEST_ROOT must be absolute")
        if os.path.lexists(cls.root):
            raise RuntimeError(f"refusing pre-existing test root: {cls.root}")
        cls.root.mkdir(mode=0o700)
        cls.receipts = cls.root / "receipts"
        cls.receipts.mkdir()

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.root)

    def run_cli(self, *args):
        result = subprocess.run(
            [sys.executable, str(SCRIPT), *map(str, args)],
            capture_output=True,
            text=True,
            check=False,
        )
        try:
            payload = json.loads(result.stdout)
        except json.JSONDecodeError as exc:
            self.fail(f"non-JSON output: {result.stdout!r} stderr={result.stderr!r}: {exc}")
        return result, payload

    def new_paths(self, label):
        suffix = uuid.uuid4().hex[:8]
        candidate = self.root / f"{label}-{suffix}"
        receipt = self.receipts / f"{label}-{suffix}.json"
        return candidate, receipt

    def init_candidate(self, label="case"):
        candidate, receipt = self.new_paths(label)
        result, payload = self.run_cli(
            "init",
            "--path",
            candidate,
            "--temp-root",
            self.root,
            "--receipt",
            receipt,
            "--owner",
            "eval",
            "--purpose",
            label,
        )
        self.assertEqual(result.returncode, 0, payload)
        self.assertEqual(payload["status"], "pass")
        return candidate, receipt

    def test_clean_candidate_passes(self):
        _, receipt = self.init_candidate("clean")
        result, payload = self.run_cli("check", "--receipt", receipt)
        self.assertEqual(result.returncode, 0, payload)
        self.assertTrue(payload["eligible_for_host_cleanup"])

    def test_path_with_spaces_passes(self):
        candidate, receipt = self.new_paths("path with spaces")
        result, payload = self.run_cli(
            "init",
            "--path",
            candidate,
            "--temp-root",
            self.root,
            "--receipt",
            receipt,
            "--owner",
            "eval",
            "--purpose",
            "spaces",
        )
        self.assertEqual(result.returncode, 0, payload)
        result, payload = self.run_cli("check", "--receipt", receipt)
        self.assertEqual(result.returncode, 0, payload)

    def test_existing_path_cannot_be_adopted(self):
        candidate, receipt = self.new_paths("existing")
        candidate.mkdir()
        result, payload = self.run_cli(
            "init",
            "--path",
            candidate,
            "--temp-root",
            self.root,
            "--receipt",
            receipt,
            "--owner",
            "eval",
            "--purpose",
            "existing",
        )
        self.assertEqual(result.returncode, 2)
        self.assertIn("cannot be adopted", payload["error"])

    def test_receipt_inside_candidate_is_rejected(self):
        candidate, _ = self.new_paths("inside-receipt")
        receipt = candidate / "receipt.json"
        result, payload = self.run_cli(
            "init",
            "--path",
            candidate,
            "--temp-root",
            self.root,
            "--receipt",
            receipt,
            "--owner",
            "eval",
            "--purpose",
            "bad receipt",
        )
        self.assertEqual(result.returncode, 2)
        self.assertIn("outside", payload["error"])

    def test_symlink_is_rejected(self):
        candidate, receipt = self.init_candidate("symlink")
        (candidate / "escape").symlink_to("/")
        result, payload = self.run_cli("check", "--receipt", receipt)
        self.assertEqual(result.returncode, 2)
        self.assertIn("symlink", payload["error"].lower())

    def test_nested_git_metadata_is_rejected(self):
        candidate, receipt = self.init_candidate("git")
        (candidate / ".git").mkdir()
        result, payload = self.run_cli("check", "--receipt", receipt)
        self.assertEqual(result.returncode, 2)
        self.assertIn("VCS metadata", payload["error"])

    def test_case_variant_git_metadata_is_rejected(self):
        candidate, receipt = self.init_candidate("case-git")
        (candidate / ".GIT").mkdir()
        result, payload = self.run_cli("check", "--receipt", receipt)
        self.assertEqual(result.returncode, 2)
        self.assertIn("VCS metadata", payload["error"])

    def test_nested_bare_git_repository_is_rejected(self):
        candidate, receipt = self.init_candidate("bare")
        nested = candidate / "nested"
        nested.mkdir()
        (nested / "HEAD").write_text("ref: refs/heads/main\n", encoding="utf-8")
        (nested / "objects").mkdir()
        (nested / "refs").mkdir()
        result, payload = self.run_cli("check", "--receipt", receipt)
        self.assertEqual(result.returncode, 2)
        self.assertIn("Git metadata", payload["error"])

    def test_inode_substitution_is_rejected(self):
        candidate, receipt = self.init_candidate("identity")
        original = candidate.with_name(candidate.name + "-original")
        candidate.rename(original)
        candidate.mkdir()
        result, payload = self.run_cli("check", "--receipt", receipt)
        self.assertEqual(result.returncode, 2)
        self.assertIn("inode changed", payload["error"])

    def test_symlinked_parent_is_rejected_during_init(self):
        real_parent = self.root / f"real-{uuid.uuid4().hex[:8]}"
        real_parent.mkdir()
        alias = self.root / f"alias-{uuid.uuid4().hex[:8]}"
        alias.symlink_to(real_parent, target_is_directory=True)
        candidate = alias / "candidate"
        receipt = self.receipts / f"alias-{uuid.uuid4().hex[:8]}.json"
        result, payload = self.run_cli(
            "init",
            "--path",
            candidate,
            "--temp-root",
            self.root,
            "--receipt",
            receipt,
            "--owner",
            "eval",
            "--purpose",
            "symlinked parent",
        )
        self.assertEqual(result.returncode, 2)
        self.assertIn("symlink component", payload["error"])

    def test_special_file_is_rejected(self):
        if not hasattr(os, "mkfifo"):
            self.skipTest("FIFO creation is unavailable")
        candidate, receipt = self.init_candidate("fifo")
        os.mkfifo(candidate / "active.pipe")
        result, payload = self.run_cli("check", "--receipt", receipt)
        self.assertEqual(result.returncode, 2)
        self.assertIn("special file", payload["error"])

    def test_verify_removed_requires_absence(self):
        candidate, receipt = self.init_candidate("verify")
        result, payload = self.run_cli("verify-removed", "--receipt", receipt)
        self.assertEqual(result.returncode, 2)
        self.assertIn("still present", payload["error"])
        candidate.rmdir()
        result, payload = self.run_cli("verify-removed", "--receipt", receipt)
        self.assertEqual(result.returncode, 0, payload)

    def test_open_file_check_detects_reference(self):
        if shutil.which("lsof") is None:
            self.skipTest("lsof is unavailable")
        candidate, receipt = self.init_candidate("open")
        target = candidate / "held-open.txt"
        with target.open("w", encoding="utf-8") as handle:
            handle.write("open\n")
            handle.flush()
            result, payload = self.run_cli(
                "check", "--receipt", receipt, "--check-open-files"
            )
        self.assertEqual(result.returncode, 2)
        self.assertIn("open files", payload["error"])


if __name__ == "__main__":
    unittest.main()
