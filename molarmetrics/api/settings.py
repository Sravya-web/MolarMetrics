"""Web-app settings (read from the environment or .env, with safe defaults)."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from molarmetrics.config import PROJECT_ROOT  # importing config also loads .env and disables remote tracing


def _env(name: str, default: str) -> str:
    value = os.environ.get(name, "").strip()
    return value or default


@dataclass(frozen=True)
class WebSettings:
    runtime_dir: Path
    retention_hours: float
    max_file_mb: int
    max_files: int
    sweep_minutes: float
    allowed_hosts: tuple[str, ...]

    @property
    def datasets_dir(self) -> Path:
        return self.runtime_dir / "datasets"

    @property
    def staging_dir(self) -> Path:
        return self.runtime_dir / "staging"

    @property
    def registry_path(self) -> Path:
        return self.runtime_dir / "registry.sqlite3"

    @property
    def retention_seconds(self) -> float:
        return self.retention_hours * 3600

    @property
    def max_file_bytes(self) -> int:
        return self.max_file_mb * 1024 * 1024


def get_web_settings() -> WebSettings:
    return WebSettings(
        runtime_dir=Path(_env("MOLARMETRICS_RUNTIME_DIR", str(PROJECT_ROOT / "runtime"))).expanduser(),
        retention_hours=float(_env("MOLARMETRICS_RETENTION_HOURS", "24")),
        max_file_mb=int(_env("MOLARMETRICS_MAX_UPLOAD_MB", "20")),
        max_files=int(_env("MOLARMETRICS_MAX_UPLOAD_FILES", "10")),
        sweep_minutes=float(_env("MOLARMETRICS_CLEANUP_INTERVAL_MINUTES", "10")),
        allowed_hosts=tuple(h.strip() for h in _env("MOLARMETRICS_ALLOWED_HOSTS", "localhost,127.0.0.1").split(",")
                            if h.strip()),
    )
