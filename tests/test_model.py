import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import runtime.model as model


class ModelConfigTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.root_dir = Path(self.temp_dir.name)

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def test_load_model_config_respects_env_override(self) -> None:
        override_config = self.root_dir / "models.override.yaml"
        override_config.write_text(
            """
models:
  test_fast:
    provider: openai
    provider_id: gpt-4o-mini
""".strip()
            + "\n",
            encoding="utf-8",
        )

        with patch.dict(
            model.os.environ,
            {"CLARITYCLAW_MODELS_CONFIG": str(override_config)},
            clear=True,
        ):
            loaded = model.load_model_config("test_fast")

        self.assertEqual(loaded["provider"], "openai")
        self.assertEqual(loaded["provider_id"], "gpt-4o-mini")


if __name__ == "__main__":
    unittest.main()
