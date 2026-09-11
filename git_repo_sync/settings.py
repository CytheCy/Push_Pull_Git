from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from pathlib import Path


APP_DIR = Path.home() / ".git-repo-sync"
SETTINGS_FILE = APP_DIR / "settings.json"


@dataclass
class AppSettings:
    repo_root: str = ""
    log_dir: str = str(APP_DIR / "logs")
    commit_template: str = "Automated sync {date}"
    recursive: bool = True

    @classmethod
    def load(cls, path: Path = SETTINGS_FILE) -> "AppSettings":
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
        except (FileNotFoundError, json.JSONDecodeError, OSError):
            return cls()
        allowed = cls.__dataclass_fields__.keys()
        return cls(**{key: value for key, value in raw.items() if key in allowed})

    def save(self, path: Path = SETTINGS_FILE) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(asdict(self), indent=2) + "\n", encoding="utf-8")
