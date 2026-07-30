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
        self.assertEqual(manifest["name"], ROOT.name)
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

    def test_helper_never_deletes(self):
        helper = (
            ROOT / "skills" / "claygo" / "scripts" / "claygo_preflight.py"
        ).read_text(encoding="utf-8")
        forbidden = ["shutil.rmtree(", "os.remove(", "os.unlink(", ".unlink("]
        for token in forbidden:
            self.assertNotIn(token, helper)

    def test_tab_hygiene_policy_preserves_other_owners(self):
        skill = (ROOT / "skills" / "claygo" / "SKILL.md").read_text(
            encoding="utf-8"
        )
        self.assertIn("Keep browser tabs lean", skill)
        self.assertIn(
            "Never close user-owned, unrelated, or another active task's tabs",
            skill,
        )
        self.assertIn("When ownership is uncertain, leave the tab open", skill)

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
