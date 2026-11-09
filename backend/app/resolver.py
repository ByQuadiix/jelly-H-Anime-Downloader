"""Loest eine URL (Einzelfolge oder Serien-/Playlist-Seite) in Episoden auf."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import yt_dlp

from . import naming


@dataclass
class ResolvedEpisode:
    url: str
    title: str
    number: int


@dataclass
class ResolvedSource:
    series: str
    episodes: list[ResolvedEpisode]
    is_playlist: bool


class ResolveError(Exception):
    pass


def _entry_url(entry: dict[str, Any]) -> str | None:
    return entry.get("webpage_url") or entry.get("url")


def resolve(url: str) -> ResolvedSource:
    opts = {
        "quiet": True,
        "no_warnings": True,
        "skip_download": True,
        "extract_flat": "in_playlist",
        "noplaylist": False,
        "socket_timeout": 30,
    }
    try:
        with yt_dlp.YoutubeDL(opts) as ydl:
            info = ydl.extract_info(url, download=False)
    except yt_dlp.utils.DownloadError as exc:
        raise ResolveError(_clean_error(exc)) from exc
    if not info:
        raise ResolveError("Keine Informationen zu dieser URL gefunden.")

    entries = info.get("entries")
    if entries is None:
        title = info.get("title") or ""
        number = (
            info.get("episode_number")
            or naming.guess_episode_number(title)
            or naming.episode_from_url(url)
            or 1
        )
        series = info.get("series") or naming.guess_series_name(title)
        return ResolvedSource(
            series=series,
            episodes=[ResolvedEpisode(url=info.get("webpage_url") or url, title=title, number=int(number))],
            is_playlist=False,
        )

    episodes: list[ResolvedEpisode] = []
    for index, entry in enumerate(e for e in entries if e):
        entry_url = _entry_url(entry)
        if not entry_url:
            continue
        title = entry.get("title") or ""
        number = (
            entry.get("episode_number")
            or naming.guess_episode_number(title)
            or naming.episode_from_url(entry_url)
            or index + 1
        )
        episodes.append(ResolvedEpisode(url=entry_url, title=title, number=int(number)))
    if not episodes:
        raise ResolveError("Die Seite enthaelt keine herunterladbaren Folgen.")
    series = info.get("series") or info.get("title") or naming.guess_series_name(episodes[0].title)
    return ResolvedSource(series=series, episodes=episodes, is_playlist=True)


def _clean_error(exc: Exception) -> str:
    text = str(exc)
    for prefix in ("ERROR: ",):
        if text.startswith(prefix):
            text = text[len(prefix):]
    return text.strip()[:500]
