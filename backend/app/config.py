"""Konfiguration ausschliesslich ueber Umgebungsvariablen."""
from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


def _bool(name: str, default: bool) -> bool:
    raw = os.environ.get(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on", "ja"}


def _int(name: str, default: int, minimum: int = 1) -> int:
    try:
        return max(minimum, int(os.environ.get(name, default)))
    except ValueError:
        return default


@dataclass(frozen=True)
class Settings:
    api_key: str
    media_dir: Path
    data_dir: Path
    max_concurrent: int
    output_format: str
    default_quality: str
    allow_private_urls: bool
    jellyfin_url: str
    jellyfin_api_key: str
    rate_limit: str  # z.B. "5M"; leer = unbegrenzt

    @classmethod
    def from_env(cls) -> "Settings":
        return cls(
            api_key=os.environ.get("API_KEY", "").strip(),
            media_dir=Path(os.environ.get("MEDIA_DIR", "/media")),
            data_dir=Path(os.environ.get("DATA_DIR", "/data")),
            max_concurrent=_int("MAX_CONCURRENT", 2),
            output_format=os.environ.get("OUTPUT_FORMAT", "mkv").strip().lower(),
            default_quality=os.environ.get("DEFAULT_QUALITY", "best").strip().lower(),
            allow_private_urls=_bool("ALLOW_PRIVATE_URLS", False),
            jellyfin_url=os.environ.get("JELLYFIN_URL", "").strip().rstrip("/"),
            jellyfin_api_key=os.environ.get("JELLYFIN_API_KEY", "").strip(),
            rate_limit=os.environ.get("RATE_LIMIT", "").strip(),
        )
