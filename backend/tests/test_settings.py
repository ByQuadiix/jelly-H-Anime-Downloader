import time

import pytest
from fastapi.testclient import TestClient

from app import main
from app.config import Settings
from app.downloader import source_options
from app.settings_store import SettingsStore

H = {"X-Api-Key": "secret", "X-Jellyfin-User": "admin"}


def make_settings(tmp_path):
    (tmp_path / "data").mkdir(exist_ok=True)
    return Settings(
        api_key="secret", media_dir=tmp_path / "media", data_dir=tmp_path / "data",
        max_concurrent=2, output_format="mkv", default_quality="best",
        allow_private_urls=True, jellyfin_url="", jellyfin_api_key="", rate_limit="",
    )


@pytest.fixture()
def client(tmp_path, monkeypatch):
    app = main.create_app(make_settings(tmp_path))
    monkeypatch.setattr(app.state.manager, "_run",
                        lambda job: app.state.store.update(job, status="done", progress=100.0, finished=time.time()))
    with TestClient(app) as c:
        yield c


SRC = {"name": "Meine Quelle", "domains": "https://www.Example.org/foo, cdn.example.net",
       "username": "u", "password": "geheim", "cookies": "# Netscape\n.example.org\tTRUE\t/\tFALSE\t0\tk\tv",
       "headers": "Referer: https://example.org/\nX-Test: 1", "proxy": "socks5://127.0.0.1:1080"}


def test_admin_requires_api_key(client):
    assert client.get("/admin/settings").status_code == 401


def test_roundtrip_masks_secrets(client):
    r = client.put("/admin/settings", headers=H, json={"maxConcurrent": 3, "subtitleLangs": "en, de", "sources": [SRC]})
    assert r.status_code == 200, r.text
    data = r.json()
    assert data["maxConcurrent"] == 3 and data["subtitleLangs"] == ["en", "de"]
    src = data["sources"][0]
    assert src["domains"] == ["example.org", "cdn.example.net"]
    assert src["hasPassword"] and src["hasCookies"]
    assert "password" not in src and "cookies" not in src
    assert "Referer: https://example.org/" in src["headers"]


def test_secrets_kept_when_omitted_and_cleared_when_empty(client):
    saved = client.put("/admin/settings", headers=H, json={"sources": [SRC]}).json()["sources"][0]
    edit = {"id": saved["id"], "name": "Umbenannt", "domains": ["example.org"]}  # ohne password/cookies
    kept = client.put("/admin/settings", headers=H, json={"sources": [edit]}).json()["sources"][0]
    assert kept["id"] == saved["id"] and kept["hasPassword"] and kept["hasCookies"]
    cleared = client.put("/admin/settings", headers=H,
                         json={"sources": [{**edit, "password": "", "cookies": ""}]}).json()["sources"][0]
    assert not cleared["hasPassword"] and not cleared["hasCookies"]


@pytest.mark.parametrize("payload", [
    {"maxConcurrent": 0}, {"maxConcurrent": 99}, {"outputFormat": "avi"}, {"defaultQuality": "4k"},
    {"rateLimit": "schnell"}, {"subtitleLangs": "english!"},
    {"sources": [{"name": "", "domains": ["a.org"]}]},
    {"sources": [{"name": "x", "domains": []}]},
    {"sources": [{"name": "x", "domains": ["not a domain"]}]},
    {"sources": [{"name": "x", "domains": ["a.org"], "headers": "Host: evil"}]},
    {"sources": [{"name": "x", "domains": ["a.org"], "proxy": "ftp://p"}]},
])
def test_validation(client, payload):
    assert client.put("/admin/settings", headers=H, json=payload).status_code == 422


def test_settings_persist_across_restart(tmp_path):
    s = make_settings(tmp_path)
    store = SettingsStore(s.data_dir / "settings.json", s)
    store.update({"maxConcurrent": 4, "sources": [SRC]})
    again = SettingsStore(s.data_dir / "settings.json", s)
    assert again.get().max_concurrent == 4
    assert again.get().sources[0].password == "geheim"  # intern erhalten, nur nicht ausgeliefert
    assert oct((s.data_dir / "settings.json").stat().st_mode & 0o777) == "0o600"


def test_source_matching_and_disabled(tmp_path):
    s = make_settings(tmp_path)
    store = SettingsStore(s.data_dir / "settings.json", s)
    store.update({"sources": [SRC, {"name": "Aus", "enabled": False, "domains": ["off.example"]}]})
    assert store.match("https://example.org/a").name == "Meine Quelle"
    assert store.match("https://sub.example.org/a").name == "Meine Quelle"
    assert store.match("https://notexample.org/a") is None
    assert store.match("https://off.example/a") is None


def test_restrict_to_sources(client):
    body = {"series": "S", "episodes": [{"url": "https://other.test/v-1", "title": "", "number": 1}]}
    assert client.post("/api/jobs", json=body, headers=H).status_code == 200
    client.put("/admin/settings", headers=H, json={"restrictToSources": True, "sources": [SRC]})
    assert client.post("/api/jobs", json=body, headers=H).status_code == 400
    ok = {"series": "S", "episodes": [{"url": "https://example.org/v-1", "title": "", "number": 1}]}
    assert client.post("/api/jobs", json=ok, headers=H).status_code == 200
    cfg = client.get("/api/config", headers=H).json()
    assert cfg["restrictToSources"] and cfg["sources"] == ["Meine Quelle"]


def test_source_options_cookie_file_lifecycle(tmp_path):
    s = make_settings(tmp_path)
    store = SettingsStore(s.data_dir / "settings.json", s)
    store.update({"sources": [SRC]})
    with source_options(store.match("https://example.org/x"), tmp_path / "tmp") as opts:
        assert opts["username"] == "u" and opts["proxy"].startswith("socks5://")
        assert opts["http_headers"]["Referer"] == "https://example.org/"
        cookie = tmp_path / "tmp"
        files = list(cookie.glob("cookies-*.txt"))
        assert len(files) == 1 and (files[0].stat().st_mode & 0o777) == 0o600
    assert not list((tmp_path / "tmp").glob("cookies-*.txt"))
    with source_options(None, tmp_path / "tmp") as opts:
        assert opts == {}
