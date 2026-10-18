from __future__ import annotations

import json
import os
import re
import secrets
import stat
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

APP_NAME = "VideoGraphicSnatcher"
DEFAULT_PORT = 43127
NOTION_ID_PATTERN = re.compile(r"(?<![0-9a-fA-F])([0-9a-fA-F]{32})(?![0-9a-fA-F])")


def default_data_dir() -> Path:
    override = os.environ.get("SNATCHER_DATA_DIR")
    if override:
        return Path(override).expanduser().resolve()
    return Path.home() / "Library" / "Application Support" / APP_NAME


def normalize_notion_id(value: str) -> str:
    compact = value.replace("-", "")
    if re.fullmatch(r"[0-9a-fA-F]{32}", compact):
        return (
            f"{compact[0:8]}-{compact[8:12]}-{compact[12:16]}-{compact[16:20]}-{compact[20:32]}"
        ).lower()
    match = NOTION_ID_PATTERN.search(value)
    if not match:
        raise ValueError("Could not find a Notion page ID in that value.")
    return normalize_notion_id(match.group(1))


@dataclass(slots=True)
class AppConfig:
    port: int = DEFAULT_PORT
    max_clip_duration_seconds: float = 900.0
    failed_job_retention_seconds: int = 3600
    notion_parent_page_id: str | None = None
    notion_database_id: str | None = None
    notion_data_source_id: str | None = None
    notion_database_url: str | None = None
    pair_token: str = ""

    def public_dict(self) -> dict[str, Any]:
        value = asdict(self)
        value.pop("pair_token", None)
        return value


class ConfigStore:
    def __init__(self, data_dir: Path | None = None):
        self.data_dir = data_dir or default_data_dir()
        self.path = self.data_dir / "config.json"
        self.jobs_dir = self.data_dir / "jobs"

    def load(self) -> AppConfig:
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.jobs_dir.mkdir(parents=True, exist_ok=True)
        raw: dict[str, Any] = {}
        if self.path.exists():
            raw = json.loads(self.path.read_text(encoding="utf-8"))
        allowed = set(AppConfig.__dataclass_fields__)
        config = AppConfig(**{key: value for key, value in raw.items() if key in allowed})
        if not config.pair_token:
            config.pair_token = secrets.token_urlsafe(32)
            self.save(config)
        return config

    def save(self, config: AppConfig) -> None:
        self.data_dir.mkdir(parents=True, exist_ok=True)
        temporary = self.path.with_suffix(".tmp")
        temporary.write_text(
            json.dumps(asdict(config), indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        os.chmod(temporary, stat.S_IRUSR | stat.S_IWUSR)
        temporary.replace(self.path)
