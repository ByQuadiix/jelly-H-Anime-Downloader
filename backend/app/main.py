"""REST-API des H!Anime-Downloaders. Wird vom Jellyfin-Plugin als Proxy angesprochen."""
from __future__ import annotations

import hmac
import logging
from urllib.parse import unquote
from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI, Header, HTTPException
from pydantic import BaseModel, Field

from . import resolver
from .config import Settings
from .config import QUALITIES
from .downloader import DownloadManager, LibraryRefresher, source_options
from .jobs import Job, JobStore
from .security import UrlNotAllowed, validate_url
from .settings_store import SettingsStore

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
log = logging.getLogger("app")


class EpisodeIn(BaseModel):
    url: str
    title: str = ""
    number: int = Field(ge=0, le=9999)


class ResolveIn(BaseModel):
    url: str


class DownloadIn(BaseModel):
    series: str = Field(min_length=1, max_length=200)
    season: int = Field(default=1, ge=0, le=99)
    quality: str = "best"
    episodes: list[EpisodeIn] = Field(min_length=1, max_length=500)


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or Settings.from_env()
    if not settings.api_key:
        raise RuntimeError("API_KEY ist nicht gesetzt. Der Dienst startet nicht ohne Authentifizierung.")

    store = JobStore(settings.data_dir / "jobs.json")
    refresher = LibraryRefresher(settings)
    runtime = SettingsStore(settings.data_dir / "settings.json", settings)
    manager = DownloadManager(settings, store, runtime, on_finished=refresher.trigger)

    def check_url(url: str) -> str:
        """SSRF-Schutz + optional: nur URLs konfigurierter, aktiver Quellen."""
        url = validate_url(url, settings.allow_private_urls)
        if runtime.get().restrict_to_sources and runtime.match(url) is None:
            raise UrlNotAllowed("Diese Seite ist nicht als Quelle freigegeben (Admin-Einstellungen).")
        return url

    @asynccontextmanager
    async def lifespan(_app: FastAPI):
        manager.resume_pending()
        yield
        manager.shutdown()

    app = FastAPI(title="H!Anime Downloader", lifespan=lifespan, docs_url=None, redoc_url=None, openapi_url=None)
    app.state.manager = manager
    app.state.store = store
    app.state.runtime = runtime

    def auth(
        x_api_key: str = Header(default=""),
        x_jellyfin_user: str = Header(default=""),
    ) -> str:
        if not hmac.compare_digest(x_api_key.encode(), settings.api_key.encode()):
            raise HTTPException(401, "Ungueltiger API-Key")
        return unquote(x_jellyfin_user).strip()[:64] or "unbekannt"

    @app.get("/health")
    def health() -> dict:
        return {"status": "ok"}

    @app.get("/api/config")
    def get_config(_user: str = Depends(auth)) -> dict:
        rt = runtime.get()
        return {
            "qualities": list(QUALITIES),
            "defaultQuality": rt.default_quality,
            "outputFormat": rt.output_format,
            "maxConcurrent": rt.max_concurrent,
            "libraryRefresh": refresher.enabled,
            "restrictToSources": rt.restrict_to_sources,
            "sources": [s.name for s in rt.sources if s.enabled],
        }

    # -- Admin (nur ueber den Admin-Proxy des Plugins erreichbar) -------------
    @app.get("/admin/settings")
    def get_settings(_user: str = Depends(auth)) -> dict:
        return runtime.public_view()

    @app.put("/admin/settings")
    def put_settings(body: dict, _user: str = Depends(auth)) -> dict:
        try:
            return runtime.update(body)
        except ValueError as exc:
            raise HTTPException(422, str(exc)) from exc

    @app.post("/api/resolve")
    def post_resolve(body: ResolveIn, _user: str = Depends(auth)) -> dict:
        try:
            url = check_url(body.url)
            with source_options(runtime.match(url), manager.tmp_dir) as extra:
                source = resolver.resolve(url, extra)
        except UrlNotAllowed as exc:
            raise HTTPException(400, str(exc)) from exc
        except resolver.ResolveError as exc:
            raise HTTPException(422, str(exc)) from exc
        return {
            "series": source.series,
            "isPlaylist": source.is_playlist,
            "episodes": [{"url": e.url, "title": e.title, "number": e.number} for e in source.episodes],
        }

    @app.post("/api/jobs")
    def post_jobs(body: DownloadIn, user: str = Depends(auth)) -> list[dict]:
        quality = body.quality if body.quality in QUALITIES else runtime.get().default_quality
        created = []
        for episode in body.episodes:
            try:
                url = check_url(episode.url)
            except UrlNotAllowed as exc:
                raise HTTPException(400, str(exc)) from exc
            job = Job(
                url=url,
                series=body.series.strip(),
                season=body.season,
                episode=episode.number,
                title=episode.title.strip(),
                quality=quality,
                user=user,
            )
            manager.submit(job)
            created.append(job.to_dict())
        return created

    @app.get("/api/jobs")
    def get_jobs(_user: str = Depends(auth)) -> list[dict]:
        return [j.to_dict() for j in store.list()]

    @app.post("/api/jobs/{job_id}/cancel")
    def cancel(job_id: str, _user: str = Depends(auth)) -> dict:
        if not store.request_cancel(job_id):
            raise HTTPException(404, "Job nicht gefunden oder nicht aktiv")
        return {"ok": True}

    @app.delete("/api/jobs/{job_id}")
    def delete(job_id: str, _user: str = Depends(auth)) -> dict:
        if not store.remove(job_id):
            raise HTTPException(404, "Job nicht gefunden oder noch aktiv")
        return {"ok": True}

    @app.post("/api/jobs-clear")
    def clear(_user: str = Depends(auth)) -> dict:
        return {"removed": store.clear_finished()}

    return app


def app_factory() -> FastAPI:
    return create_app()
