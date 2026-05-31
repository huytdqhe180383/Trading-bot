from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]


class ProjectDocumentationTest(unittest.TestCase):
    def test_readme_contains_required_operational_sections(self):
        readme = (ROOT / "README.md").read_text(encoding="utf-8").lower()

        required_sections = [
            "## setup",
            "## backtest",
            "## current results",
            "## agent cost estimate",
            "## rx6700xt training",
            "## git and data hygiene",
        ]

        for section in required_sections:
            with self.subTest(section=section):
                self.assertIn(section, readme)

    def test_rx6700xt_rocm_guide_contains_verification_path(self):
        guide = (ROOT / "docs" / "rx6700xt_rocm_training.md").read_text(encoding="utf-8").lower()

        required_terms = [
            "rx6700xt",
            "wsl2",
            "rocm",
            "rocminfo",
            "torch.version.hip",
            "stable-baselines3",
        ]

        for term in required_terms:
            with self.subTest(term=term):
                self.assertIn(term, guide)

    def test_architecture_refactor_docs_exist(self):
        required_paths = [
            ROOT / "CONTEXT.md",
            ROOT / "docs" / "README.md",
            ROOT / "docs" / "architecture" / "runtime_spine.md",
            ROOT / "docs" / "adr" / "0001-application-spine-and-artifact-runtime.md",
            ROOT / "scripts" / "README.md",
        ]

        for path in required_paths:
            with self.subTest(path=path):
                self.assertTrue(path.exists(), f"Missing architecture navigation doc: {path}")


if __name__ == "__main__":
    unittest.main()
