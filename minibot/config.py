from __future__ import annotations

import os
from pathlib import Path


DEFAULT_ENV_FILE = Path("minibot.local.env")


def load_env_file(path: Path = DEFAULT_ENV_FILE, override: bool = False) -> None:
    """Load simple KEY=value settings without adding a dotenv dependency."""
    if not path.exists():
        return
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = _clean_value(value.strip())
        if key and (override or key not in os.environ):
            os.environ[key] = value


def _clean_value(value: str) -> str:
    if len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
        return value[1:-1]
    return value
