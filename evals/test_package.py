import json
import re
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class PackageTests(unittest.TestCase):
    def test_plugin_manifest(self):
        manifest = json.loads(
            (ROOT / ".codex-plugin" / "plugin.json").read_text(encoding="utf-8")
        )
        self.assertEqual(manifest["name"], "claygo")
        self.assertRegex(manifest["version"], r"^\d+\.\d+\.\d+$")
        self.assertEqual(manifest["skills"], "./skills/")
        self.assertEqual(manifest["license"], "MIT")
        self.assertTrue(manifest["interface"]["defaultPrompt"])

    def test_skill_frontmatter(self):
        skill = ROOT / "skills" / "claygo" / "SKILL.md"
        text = skill.read_text(encoding="utf-8")
        match = re.match(r"^---\n(.*?)\n---", text, re.DOTALL)
        self.assertIsNotNone(match)
        frontmatter = match.group(1)
        name = re.search(r"^name:\s*(.+)$", frontmatter, re.MULTILINE)
        description = re.search(r"^description:\s*(.+)$", frontmatter, re.MULTILINE)
        self.assertEqual(name.group(1).strip(), "claygo")
        value = description.group(1).strip()
        self.assertLessEqual(len(value), 1024)
        self.assertNotRegex(value, r"[<>]")

    def test_skill_has_no_placeholders(self):
        for path in (ROOT / "skills" / "claygo").rglob("*"):
            if path.is_file():
                self.assertNotIn("[TODO:", path.read_text(encoding="utf-8"))

    def test_canonical_helper_owns_finalization(self):
        helper = (ROOT / "skills" / "claygo" / "scripts" / "claygo_core.py").read_text(
            encoding="utf-8"
        )
        for token in (
            "validate_identity(record, receipt)",
            "check_open_files(candidate",
            "scan_candidate(candidate",
            "bounded_rmtree(candidate",
            'record["state"] = "removed"',
        ):
            self.assertIn(token, helper)

        cli = (ROOT / "skills" / "claygo" / "scripts" / "claygo.py").read_text(
            encoding="utf-8"
        )
        self.assertIn("from claygo_core import (", cli)
        self.assertIn("def build_parser()", cli)

    def test_compatibility_entrypoint_delegates_to_canonical_helper(self):
        helper = (
            ROOT / "skills" / "claygo" / "scripts" / "claygo_preflight.py"
        ).read_text(encoding="utf-8")
        self.assertIn("from claygo import main", helper)

    def test_tab_hygiene_policy_preserves_other_owners(self):
        skill = (ROOT / "skills" / "claygo" / "SKILL.md").read_text(
            encoding="utf-8"
        )
        self.assertIn("Browser tabs and processes", skill)
        self.assertIn(
            "User-owned browser tabs are never task-owned",
            skill,
        )
        self.assertIn("another task's resources", skill)

    def test_profile_reference_and_closeout_hook_are_packaged(self):
        self.assertTrue(
            (ROOT / "skills/claygo/references/resource-profiles.md").is_file()
        )
        self.assertTrue(
            (ROOT / "skills/claygo/scripts/claygo_closeout_hook.py").is_file()
        )

    def test_tab_hygiene_case_study_is_packaged(self):
        case_study = (
            ROOT
            / "skills"
            / "claygo"
            / "references"
            / "codex-tab-hygiene-case-study.md"
        )
        self.assertTrue(case_study.is_file())
        text = case_study.read_text(encoding="utf-8")
        self.assertIn("49 task-owned tabs", text)
        self.assertIn("36.32 to 9.64", text)
        self.assertIn("45 of 45 cases passing", text)
        self.assertIn("826 passes", text)


if __name__ == "__main__":
    unittest.main()
