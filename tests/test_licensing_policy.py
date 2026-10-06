from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]


def normalized(path: str) -> str:
    return " ".join((ROOT / path).read_text(encoding="utf-8").split())


class LicensingPolicyTests(unittest.TestCase):
    """Document consistency checks, not a legal validity assessment."""

    def test_research_sharing_includes_modifications_and_patches(self):
        license_text = normalized("LICENSE")
        self.assertIn("Version 1.1", license_text)
        self.assertIn("including modified versions, derivative works and patches", license_text)
        self.assertIn("public research forks and pull requests", license_text)
        self.assertIn("no separate written authorization or contributor agreement", license_text)
        self.assertIn("clearly mark modifications and their dates", license_text)

    def test_commercial_and_third_party_boundaries_remain(self):
        license_text = normalized("LICENSE")
        self.assertIn("without charge, solely to support Permitted Research Use", license_text)
        self.assertIn("Without separate prior written authorization", license_text)
        self.assertIn("commercial internal use and R&D", license_text)
        self.assertIn("Third-party components and materials are excluded", license_text)
        self.assertIn("not offered under an open-source license", license_text)

    def test_no_stale_modified_sharing_prohibition_in_current_summaries(self):
        for path in ["LICENSE", "README.md", "DISTRIBUTION.md", "docs/LICENSING.md",
                     "paper_monitor/user_guide.html", "scripts/build_user_guide_pdf.py"]:
            with self.subTest(path=path):
                value = normalized(path).lower()
                self.assertNotIn("sharing is limited to", value)
                self.assertNotIn("sharing of unmodified official versions", value)
                self.assertNotIn("publishing modified versions or patches requires", value)
                self.assertIn("modified versions", value)

    def test_external_contribution_policy_does_not_invent_a_cla(self):
        policy = normalized("CONTRIBUTING.md")
        self.assertIn("No finalized CLA or signature-collection process", policy)
        self.assertIn("Submitting a pull request does not transfer your copyright", policy)
        self.assertIn("must not merge external code", policy)
        self.assertIn("commercial use and sublicensing/relicensing", policy)
        self.assertIn("not be treated as evidence", policy)
        self.assertIn("contributors retain copyright", policy)

    def test_packaging_includes_contribution_policy(self):
        self.assertIn('copy_item "CONTRIBUTING.md"', normalized("scripts/make_release.sh"))
        self.assertIn('cp "$PROJECT_DIR/CONTRIBUTING.md"', normalized("scripts/build_macos_app.sh"))

    @__import__("unittest").skipIf(__import__("sys").platform == "win32", "macOS application bundle packaging")
    def test_bundled_license_and_contribution_policy_match(self):
        resources = ROOT / "Gewu Insight.app" / "Contents" / "Resources"
        for source, bundled in [("LICENSE", "LICENSE.txt"), ("CONTRIBUTING.md", "CONTRIBUTING.md")]:
            with self.subTest(source=source):
                self.assertEqual((ROOT / source).read_bytes(), (resources / bundled).read_bytes())


if __name__ == "__main__":
    unittest.main()
