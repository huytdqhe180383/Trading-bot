import importlib.util
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class UIRunnerImportTest(unittest.TestCase):
    def test_run_ui_script_imports_from_file_path(self):
        script_path = ROOT / "scripts" / "run_ui.py"
        spec = importlib.util.spec_from_file_location("isolated_run_ui", script_path)
        self.assertIsNotNone(spec)
        self.assertIsNotNone(spec.loader)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        self.assertTrue(callable(module.main))


if __name__ == "__main__":
    unittest.main()
