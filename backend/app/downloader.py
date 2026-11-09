"""Download-Queue auf Basis von yt-dlp."""
from __future__ import annotations

import logging
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Callable

import yt_dlp
from yt_dlp.utils import DownloadCancelled

from . import naming
from .config import Settings
from .jobs import Job, JobStore

log = logging.getLogger("downloader")

QUALITIES = {"best": None, "1080": 1080, "720": 720, "480": 480}


def format_selector(quality: str) -> str:
    height = QUALITIES.get(quality)
    if height is None:
        return "bv*+ba/b"
    return f"bv*[height<={height}]+ba/b[height<={height}]/bv*+ba/b"


class DownloadManager:
    def __init__(self, settings: Settings, store: JobStore, on_finished: Callable[[Job], None] | None = None):
        self.settings = settings
        self.store = store
        self._on_finished = on_finished
        self._pool = ThreadPoolExecutor(max_workers=settings.max_concurrent, thread_name_prefix="dl")
        self._tmp_dir = settings.data_dir / "tmp"
        self._tmp_dir.mkdir(parents=True, exist_ok=True)

    # -- Queue --------------------------------------------------------------
    def resume_pending(self) -> None:
        """Nach einem Neustart unterbrochene Jobs erneut einreihen."""
        for job in reversed(self.store.list()):
            if job.status in {"queued", "downloading", "processing"}:
                self.store.update(job, status="queued", progress=0.0, speed="", eta="")
                self._pool.submit(self._run, job)

    def submit(self, job: Job) -> None:
        self.store.add(job)
        self._pool.submit(self._run, job)

    def shutdown(self) -> None:
        self._pool.shutdown(wait=False, cancel_futures=True)

    # -- Worker -------------------------------------------------------------
    def _target(self, job: Job) -> tuple[Path, str]:
        subdir, template = naming.build_relative_path(job.series, job.season, job.episode, job.title)
        return self.settings.media_dir / subdir, template

    def _existing_file(self, folder: Path, template: str) -> Path | None:
        stem = template.rsplit(".", 1)[0].replace("%%", "%")
        if not folder.is_dir():
            return None
        for path in folder.glob("*"):
            if path.is_file() and path.stem == stem and path.suffix.lower() not in {".part", ".ytdl", ".temp"}:
                return path
        return None

    def _run(self, job: Job) -> None:
        if self.store.is_cancelled(job.id):
            return
        folder, template = self._target(job)
        existing = self._existing_file(folder, template)
        if existing:
            self.store.update(job, status="done", progress=100.0, filename=existing.name,
                              error="Bereits vorhanden – uebersprungen.", finished=time.time())
            self.store.save()
            return

        self.store.update(job, status="downloading", progress=0.0, error="")
        self.store.save()

        def hook(d: dict) -> None:
            if self.store.is_cancelled(job.id):
                raise DownloadCancelled("Vom Benutzer abgebrochen")
            status = d.get("status")
            if status == "downloading":
                total = d.get("total_bytes") or d.get("total_bytes_estimate")
                done = d.get("downloaded_bytes") or 0
                if total:
                    pct = done / total * 100
                elif d.get("fragment_count"):
                    pct = (d.get("fragment_index") or 0) / d["fragment_count"] * 100
                else:
                    pct = job.progress
                self.store.update(
                    job,
                    progress=round(min(pct, 99.9), 1),
                    speed=(d.get("_speed_str") or "").strip(),
                    eta=(d.get("_eta_str") or "").strip(),
                )
            elif status == "finished":
                self.store.update(job, status="processing", progress=99.9, speed="", eta="")

        opts = {
            "format": format_selector(job.quality),
            "outtmpl": {"default": template},
            "paths": {"home": str(folder), "temp": str(self._tmp_dir)},
            "merge_output_format": self.settings.output_format,
            "progress_hooks": [hook],
            "quiet": True,
            "no_warnings": True,
            "noprogress": True,
            "noplaylist": True,
            "retries": 10,
            "fragment_retries": 10,
            "concurrent_fragment_downloads": 4,
            "socket_timeout": 30,
            "overwrites": False,
            "windowsfilenames": True,
        }
        if self.settings.rate_limit:
            opts["ratelimit"] = _parse_rate(self.settings.rate_limit)

        try:
            folder.mkdir(parents=True, exist_ok=True)
            with yt_dlp.YoutubeDL(opts) as ydl:
                info = ydl.extract_info(job.url, download=True)
                final = Path(ydl.prepare_filename(info)) if info else None
                if info and info.get("requested_downloads"):
                    final = Path(info["requested_downloads"][0].get("filepath") or final)
            self.store.update(job, status="done", progress=100.0, speed="", eta="",
                              filename=final.name if final else template, finished=time.time())
        except DownloadCancelled:
            self.store.update(job, status="cancelled", speed="", eta="", finished=time.time())
        except Exception as exc:  # noqa: BLE001 - jeder Fehler soll im UI landen
            if self.store.is_cancelled(job.id):
                self.store.update(job, status="cancelled", speed="", eta="", finished=time.time())
            else:
                log.warning("Job %s fehlgeschlagen: %s", job.id, exc)
                msg = str(exc).removeprefix("ERROR: ").strip()[:500]
                self.store.update(job, status="error", error=msg, speed="", eta="", finished=time.time())
        finally:
            self.store.save()
        if job.status == "done" and self._on_finished:
            try:
                self._on_finished(job)
            except Exception:  # noqa: BLE001
                log.exception("on_finished fehlgeschlagen")


def _parse_rate(text: str) -> int | None:
    value = yt_dlp.utils.parse_bytes(text)
    return int(value) if value else None


class LibraryRefresher:
    """Stoesst nach abgeschlossenen Downloads (entprellt) einen Jellyfin-Bibliotheksscan an."""

    def __init__(self, settings: Settings, delay: float = 30.0):
        self.settings = settings
        self.delay = delay
        self._timer: threading.Timer | None = None
        self._lock = threading.Lock()

    @property
    def enabled(self) -> bool:
        return bool(self.settings.jellyfin_url and self.settings.jellyfin_api_key)

    def trigger(self, _job: Job | None = None) -> None:
        if not self.enabled:
            return
        with self._lock:
            if self._timer:
                self._timer.cancel()
            self._timer = threading.Timer(self.delay, self._refresh)
            self._timer.daemon = True
            self._timer.start()

    def _refresh(self) -> None:
        import httpx

        try:
            httpx.post(
                f"{self.settings.jellyfin_url}/Library/Refresh",
                headers={"Authorization": f'MediaBrowser Token="{self.settings.jellyfin_api_key}"'},
                timeout=15,
            ).raise_for_status()
            log.info("Jellyfin-Bibliotheksscan gestartet")
        except Exception as exc:  # noqa: BLE001
            log.warning("Jellyfin-Refresh fehlgeschlagen: %s", exc)
