import time

import pytest
from fastapi.testclient import TestClient

from app import main, resolver
from app.config import Settings
from app.security import UrlNotAllowed, validate_url


@pytest.fixture()
def client(tmp_path, monkeypatch):
    settings = Settings(
        api_key="secret", media_dir=tmp_path / "media", data_dir=tmp_path / "data",
        max_concurrent=1, output_format="mkv", default_quality="best",
        allow_private_urls=True, jellyfin_url="", jellyfin_api_key="", rate_limit="",
    )
    settings.data_dir.mkdir()
    app = main.create_app(settings)

    def fake_run(job):  # kein echter Download in Tests
        app.state.store.update(job, status="done", progress=100.0, finished=time.time())

    monkeypatch.setattr(app.state.manager, "_run", fake_run)
    with TestClient(app) as c:
        yield c


H = {"X-Api-Key": "secret", "X-Jellyfin-User": "tester"}


def test_requires_api_key(client):
    assert client.get("/api/jobs").status_code == 401
    assert client.get("/api/jobs", headers={"X-Api-Key": "falsch"}).status_code == 401
    assert client.get("/health").status_code == 200


def test_refuses_to_start_without_key(tmp_path):
    with pytest.raises(RuntimeError):
        main.create_app(Settings(
            api_key="", media_dir=tmp_path, data_dir=tmp_path, max_concurrent=1, output_format="mkv",
            default_quality="best", allow_private_urls=False, jellyfin_url="", jellyfin_api_key="", rate_limit=""))


def test_create_list_delete_job(client):
    body = {"series": "Show", "season": 1, "quality": "720",
            "episodes": [{"url": "https://example.org/v/show-1", "title": "A", "number": 1}]}
    created = client.post("/api/jobs", json=body, headers=H).json()
    assert created[0]["user"] == "tester" and created[0]["quality"] == "720"
    time.sleep(0.3)
    jobs = client.get("/api/jobs", headers=H).json()
    assert len(jobs) == 1 and jobs[0]["status"] == "done"
    assert client.delete(f"/api/jobs/{jobs[0]['id']}", headers=H).status_code == 200
    assert client.get("/api/jobs", headers=H).json() == []


def test_rejects_non_http_urls(client):
    body = {"series": "S", "episodes": [{"url": "file:///etc/passwd", "title": "x", "number": 1}]}
    assert client.post("/api/jobs", json=body, headers=H).status_code == 400


def test_resolve_maps_errors(client, monkeypatch):
    def boom(_url):
        raise resolver.ResolveError("nicht unterstuetzt")

    monkeypatch.setattr(resolver, "resolve", boom)
    r = client.post("/api/resolve", json={"url": "https://example.org/x"}, headers=H)
    assert r.status_code == 422 and "nicht unterstuetzt" in r.json()["detail"]


def test_ssrf_protection():
    for bad in ("http://127.0.0.1/x", "http://localhost/x", "http://10.0.0.5/x", "http://169.254.169.254/"):
        with pytest.raises(UrlNotAllowed):
            validate_url(bad, allow_private=False)
    with pytest.raises(UrlNotAllowed):
        validate_url("ftp://example.org/x")
    assert validate_url("http://127.0.0.1/x", allow_private=True)
