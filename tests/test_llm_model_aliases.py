import importlib
import os
import unittest
from unittest.mock import patch

import config


class LLMModelAliasesTest(unittest.TestCase):
    def test_preferred_weak_and_strong_model_names_route_to_existing_clients(self):
        original_environment = dict(os.environ)
        try:
            with patch.dict(
                os.environ,
                {
                    "LLM_MODEL": "",
                    "LLM_WEAK_MODEL": "weak-test-model",
                    "LLM_STRONG_MODEL": "strong-test-model",
                    "LLM_BACKGROUND_MODEL": "",
                    "LLM_INTERACTIVE_MODEL": "",
                },
                clear=True,
            ):
                reloaded = importlib.reload(config)
                self.assertEqual(reloaded.LLM_BACKGROUND_MODEL, "weak-test-model")
                self.assertEqual(reloaded.LLM_INTERACTIVE_MODEL, "strong-test-model")
        finally:
            os.environ.clear()
            os.environ.update(original_environment)
            importlib.reload(config)


if __name__ == "__main__":
    unittest.main()
