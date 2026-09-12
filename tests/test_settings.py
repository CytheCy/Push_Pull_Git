from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from git_repo_sync.settings import AppSettings


class SettingsTests(unittest.TestCase):
    def test_appearance_is_saved_and_loaded(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "settings.json"
            AppSettings(appearance="dark").save(path)

            self.assertEqual(AppSettings.load(path).appearance, "dark")

    def test_missing_or_invalid_appearance_uses_light(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "settings.json"
            path.write_text(json.dumps({"appearance": "unknown"}), encoding="utf-8")

            self.assertEqual(AppSettings.load(path).appearance, "light")


if __name__ == "__main__":
    unittest.main()
