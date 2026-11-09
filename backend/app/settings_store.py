"""Zur Laufzeit aenderbare Einstellungen (Admin-Seite) inkl. Quellen-Verwaltung.

Gespeichert in DATA_DIR/settings.json. Geheimnisse (Passwort, Cookies) werden nie an die
Oberflaeche zurueckgegeben, sondern nur als "gesetzt"-Flag.
"""
from __future__ import annotations

import copy
import json
import re
import threading
import uuid
from dataclasses import asdict, dataclass, field
from pathlib import Path
from urllib.parse import urlparse

from .config import QUALITIES, Settings

_HEADER_NAME = re.compile(r"^[A-Za-z0-9-]{1,64}$")
_FORBIDDEN_HEADERS = {"host", "content-length", "transfer-encoding", "connection"}
_LANG = re.compile(r"^[A-Za-z]{2,3}(-[A-Za-z0-9]{2,8})?$")
_RATE = re.compile(r"^(\d+(\.\d+)?[KkMmGg]?)?$")
_DOMAIN = re.compile(r"^[a-z0-9]([a-z0-9-]*[a-z0-9])?(\.[a-z0-9]([a-z0-9-]*[a-z0-9])?)+$")
MAX_COOKIES = 200_000


@dataclass
class Source:
    id: str
    name: str
    enabled: bool = True
    domains: list[str] = field(default_factory=list)
    cookies: str = ""  # Netscape-Cookie-Format (cookies.txt)
    headers: dict[str, str] = field(default_factory=dict)
    username: str = ""
    password: str = ""
    proxy: str = ""


@dataclass
class RuntimeSettings:
    max_concurrent: int = 2
    output_format: str = "mkv"
    default_quality: str = "best"
    rate_limit: str = ""
    restrict_to_sources: bool = False
    subtitle_langs: list[str] = field(default_factory=lambda: ["en"])
    embed_subs: bool = False
    sources: list[Source] = field(default_factory=list)


def _host_matches(host: str, domain: str) -> bool:
    return host == domain or host.endswith("." + domain)


class SettingsStore:
    def __init__(self, path: Path, defaults: Settings):
        self._path = path
        self._lock = threading.RLock()
        self._rt = RuntimeSettings(
            max_concurrent=defaults.max_concurrent,
            output_format=defaults.output_format if defaults.output_format in {"mkv", "mp4"} else "mkv",
            default_quality=defaults.default_quality if defaults.default_quality in QUALITIES else "best",
            rate_limit=defaults.rate_limit,
        )
        self._load()

    # -- Persistenz ---------------------------------------------------------
    def _load(self) -> None:
        if not self._path.exists():
            return
        try:
            raw = json.loads(self._path.read_text("utf-8"))
            self._rt = self._parse(raw, existing=self._rt, keep_secrets=False)
        except (OSError, ValueError, TypeError):
            pass  # defekte Datei -> Defaults behalten

    def _save(self) -> None:
        tmp = self._path.with_suffix(".tmp")
        self._path.parent.mkdir(parents=True, exist_ok=True)
        tmp.write_text(json.dumps(asdict(self._rt), ensure_ascii=False, indent=2), "utf-8")
        try:
            tmp.chmod(0o600)  # enthaelt ggf. Passwoerter/Cookies
        except OSError:
            pass
        tmp.replace(self._path)

    # -- Lesen --------------------------------------------------------------
    def get(self) -> RuntimeSettings:
        with self._lock:
            return copy.deepcopy(self._rt)

    def match(self, url: str) -> Source | None:
        host = (urlparse(url).hostname or "").lower()
        with self._lock:
            for source in self._rt.sources:
                if source.enabled and any(_host_matches(host, d) for d in source.domains):
                    return copy.deepcopy(source)
        return None

    def public_view(self) -> dict:
        rt = self.get()
        data = asdict(rt)
        data["sources"] = [
            {
                "id": s.id, "name": s.name, "enabled": s.enabled, "domains": s.domains,
                "headers": "\n".join(f"{k}: {v}" for k, v in s.headers.items()),
                "username": s.username, "proxy": s.proxy,
                "hasPassword": bool(s.password), "hasCookies": bool(s.cookies),
            }
            for s in rt.sources
        ]
        return _camel(data)

    # -- Schreiben ----------------------------------------------------------
    def update(self, payload: dict) -> dict:
        with self._lock:
            self._rt = self._parse(_snake(payload), existing=self._rt, keep_secrets=True)
            self._save()
        return self.public_view()

    def _parse(self, raw: dict, existing: RuntimeSettings, keep_secrets: bool) -> RuntimeSettings:
        if not isinstance(raw, dict):
            raise ValueError("Ungueltiges Format.")
        rt = copy.deepcopy(existing)

        if "max_concurrent" in raw:
            rt.max_concurrent = _int_range(raw["max_concurrent"], 1, 8, "Parallele Downloads")
        if "output_format" in raw:
            if raw["output_format"] not in {"mkv", "mp4"}:
                raise ValueError("Ausgabeformat muss mkv oder mp4 sein.")
            rt.output_format = raw["output_format"]
        if "default_quality" in raw:
            if raw["default_quality"] not in QUALITIES:
                raise ValueError("Ungueltige Standard-Qualitaet.")
            rt.default_quality = raw["default_quality"]
        if "rate_limit" in raw:
            limit = str(raw["rate_limit"] or "").strip()
            if not _RATE.match(limit):
                raise ValueError("Bandbreitenlimit z. B. 5M oder 500K.")
            rt.rate_limit = limit
        if "restrict_to_sources" in raw:
            rt.restrict_to_sources = bool(raw["restrict_to_sources"])
        if "embed_subs" in raw:
            rt.embed_subs = bool(raw["embed_subs"])
        if "subtitle_langs" in raw:
            langs = raw["subtitle_langs"]
            if isinstance(langs, str):
                langs = re.split(r"[,\s]+", langs)
            cleaned = [str(x).strip() for x in langs if str(x).strip()]
            if len(cleaned) > 10 or any(not _LANG.match(x) for x in cleaned):
                raise ValueError("Untertitelsprachen als Codes angeben, z. B. en, de.")
            rt.subtitle_langs = cleaned

        if "sources" in raw:
            if not isinstance(raw["sources"], list) or len(raw["sources"]) > 50:
                raise ValueError("Maximal 50 Quellen.")
            old = {s.id: s for s in rt.sources}
            rt.sources = [self._parse_source(item, old, keep_secrets) for item in raw["sources"]]
        return rt

    def _parse_source(self, item: dict, old: dict[str, Source], keep_secrets: bool) -> Source:
        if not isinstance(item, dict):
            raise ValueError("Ungueltige Quelle.")
        source_id = str(item.get("id") or "").strip()
        previous = old.get(source_id)
        if not previous:
            source_id = uuid.uuid4().hex[:10]

        name = str(item.get("name") or "").strip()
        if not name or len(name) > 60:
            raise ValueError("Jede Quelle braucht einen Namen (max. 60 Zeichen).")

        domains = item.get("domains", [])
        if isinstance(domains, str):
            domains = re.split(r"[,\s]+", domains)
        norm = []
        for d in domains:
            d = str(d).strip().lower()
            if not d:
                continue
            d = urlparse(d if "://" in d else "//" + d).hostname or ""
            if d.startswith("www."):
                d = d[4:]
            if not _DOMAIN.match(d):
                raise ValueError(f"Ungueltige Domain bei '{name}'.")
            norm.append(d)
        if not norm:
            raise ValueError(f"'{name}': mindestens eine Domain angeben.")

        headers = item.get("headers", {})
        if isinstance(headers, str):
            parsed = {}
            for line in headers.splitlines():
                if ":" in line:
                    key, _, value = line.partition(":")
                    parsed[key.strip()] = value.strip()
            headers = parsed
        clean_headers = {}
        for key, value in headers.items():
            if not _HEADER_NAME.match(key) or key.lower() in _FORBIDDEN_HEADERS or "\n" in str(value) or "\r" in str(value):
                raise ValueError(f"Ungueltiger Header '{key}'.")
            clean_headers[key] = str(value)

        proxy = str(item.get("proxy") or "").strip()
        if proxy and urlparse(proxy).scheme not in {"http", "https", "socks4", "socks5", "socks5h"}:
            raise ValueError("Proxy muss mit http://, https:// oder socks5:// beginnen.")

        def secret(field_name: str, limit: int) -> str:
            value = item.get(field_name)
            if not keep_secrets:  # beim Laden aus der Datei direkt uebernehmen
                return str(value or "")
            if value is None:  # None/fehlend = unveraendert lassen
                return getattr(previous, field_name, "") if previous else ""
            value = str(value)
            if len(value) > limit:
                raise ValueError(f"'{field_name}' ist zu lang.")
            return value

        password = secret("password", 500)
        cookies = secret("cookies", MAX_COOKIES)

        return Source(
            id=source_id, name=name, enabled=bool(item.get("enabled", True)), domains=norm,
            cookies=cookies, headers=clean_headers, username=str(item.get("username") or "").strip()[:200],
            password=password, proxy=proxy,
        )


def _int_range(value, low: int, high: int, label: str) -> int:
    try:
        number = int(value)
    except (TypeError, ValueError):
        raise ValueError(f"{label}: Zahl erwartet.") from None
    if not low <= number <= high:
        raise ValueError(f"{label}: erlaubt sind {low}-{high}.")
    return number


def _snake(value):
    if isinstance(value, dict):
        return {re.sub(r"(?<!^)(?=[A-Z])", "_", k).lower(): _snake(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_snake(v) for v in value]
    return value


def _camel(value):
    if isinstance(value, dict):
        out = {}
        for k, v in value.items():
            parts = k.split("_")
            out[parts[0] + "".join(p.title() for p in parts[1:])] = _camel(v)
        return out
    if isinstance(value, list):
        return [_camel(v) for v in value]
    return value
