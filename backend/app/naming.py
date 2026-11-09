"""Dateinamen / Episodenerkennung im Jellyfin-Schema (Serie/Season 01/Serie - S01E01 - Titel.mkv)."""
from __future__ import annotations

import re
from urllib.parse import unquote, urlparse

_FORBIDDEN = re.compile(r'[<>:"/\\|?*\x00-\x1f]')
_WS = re.compile(r"\s+")

_EP_PATTERNS = [
    re.compile(r"(?:episode|folge|ep|e)[\s._-]*0*(\d{1,3})\b", re.I),
    re.compile(r"[\s._-]0*(\d{1,3})$"),
]
_EP_SUFFIX = re.compile(r"\s*[-–:|]?\s*(?:(?:episode|folge|ep)[\s._-]*)?\d{1,3}\s*$", re.I)


def sanitize(name: str, fallback: str = "Unbenannt", max_len: int = 120) -> str:
    """Macht einen String dateisystemtauglich (auch fuer Windows/SMB-Shares)."""
    cleaned = _FORBIDDEN.sub(" ", name or "")
    cleaned = _WS.sub(" ", cleaned).strip(" .")
    cleaned = cleaned[:max_len].strip(" .")
    return cleaned or fallback


def escape_template(text: str) -> str:
    """Escaped '%' fuer yt-dlp-Output-Templates."""
    return text.replace("%", "%%")


def guess_episode_number(*texts: str | None) -> int | None:
    for text in texts:
        if not text:
            continue
        text = unquote(text).strip()
        for pattern in _EP_PATTERNS:
            match = pattern.search(text)
            if match:
                value = int(match.group(1))
                if 0 < value < 1000:
                    return value
    return None


def episode_from_url(url: str) -> int | None:
    path = urlparse(url).path.rstrip("/")
    slug = path.rsplit("/", 1)[-1]
    return guess_episode_number(slug)


def guess_series_name(title: str | None) -> str:
    if not title:
        return ""
    stripped = _EP_SUFFIX.sub("", title).strip(" -–:|")
    return stripped or title.strip()


def build_relative_path(series: str, season: int, episode: int, title: str, ext: str = "%(ext)s") -> tuple[str, str]:
    """Liefert (Unterordner, Dateiname-Template) relativ zum Medienordner."""
    series_clean = sanitize(series)
    title_clean = sanitize(title, fallback="", max_len=100)
    base = f"{series_clean} - S{season:02d}E{episode:02d}"
    if title_clean and title_clean.lower() != series_clean.lower():
        base += f" - {title_clean}"
    return f"{series_clean}/Season {season:02d}", f"{escape_template(base)}.{ext}"
