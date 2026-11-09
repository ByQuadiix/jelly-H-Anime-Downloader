# Jellyfin H!Anime Downloader

Lädt Serien per Web-Oberfläche direkt in deine Jellyfin-Bibliothek – bedienbar von **jedem angemeldeten Jellyfin-Benutzer**, ohne separaten Login.

```
Browser ──► Jellyfin ──► Plugin (Proxy, prüft Jellyfin-Login) ──► Downloader-Backend (yt-dlp + ffmpeg) ──► /media (= Jellyfin-Bibliothek)
              ▲
              └─ File Transformation fügt Menüeintrag + UI in die Jellyfin-Weboberfläche ein
```

| Teil | Ordner | Aufgabe |
|---|---|---|
| **Backend** | `backend/` | FastAPI-Dienst: URL analysieren, Warteschlange, Download mit yt-dlp, Ablage im Jellyfin-Schema |
| **Web-UI** | `web/client.js` | Overlay in Jellyfin (Seitenleiste „H!Anime Downloader“ + Button in der Kopfzeile) |
| **Plugin** | `plugin/` | Registriert die UI per [File Transformation](https://github.com/IAmParadox27/jellyfin-plugin-file-transformation) und leitet API-Aufrufe sicher ans Backend weiter |

Das Backend ist **nicht** direkt aus dem Browser erreichbar. Nur eingeloggte Jellyfin-Benutzer kommen über das Plugin dran, und das Backend verlangt zusätzlich einen geheimen `API_KEY`.

## Voraussetzungen

- Jellyfin **10.11.x** oder **12.x** mit installiertem [File Transformation](https://github.com/IAmParadox27/jellyfin-plugin-file-transformation)-Plugin
- Docker (für das Backend)
- Die Zielbibliothek muss für den Backend-Container beschreibbar sein

## Installation

### 1. Backend starten

```bash
cp .env.example .env
# API_KEY setzen, z. B.:
echo "API_KEY=$(openssl rand -hex 32)" > .env
```

In `docker-compose.yml` anpassen:

- `/pfad/zu/deinen/Anime:/media` → der Ordner deiner Jellyfin-Bibliothek (Typ **Shows**)
- `user:` → UID/GID, der die Medien gehören
- `networks` → Netzwerk deines Jellyfin-Containers (`docker network ls`), damit Jellyfin das Backend unter `http://hanime-downloader:8080` erreicht

```bash
docker compose up -d --build
```

### 2. Plugin installieren

ZIP aus den CI-Artefakten (GitHub → Actions) oder selbst bauen:

```bash
./plugin/build.sh 10.11    # für Jellyfin 10.11.x  → dist/HAnimeDownloader_10.11.zip
./plugin/build.sh 12       # für Jellyfin 12.x     → dist/HAnimeDownloader_12.zip
```

ZIP entpacken nach `<jellyfin-config>/plugins/HAnimeDownloader_1.0.0.0/` und Jellyfin **neu starten**.

### 3. Plugin konfigurieren

Jellyfin → Dashboard → Plugins → **H!Anime Downloader**:

- **Backend-URL**: `http://hanime-downloader:8080` (so, wie der *Jellyfin-Server* das Backend erreicht)
- **API-Key**: derselbe Wert wie `API_KEY` in `.env`

Danach die Jellyfin-Seite neu laden (Strg+F5). In der Seitenleiste erscheint **H!Anime Downloader**, zusätzlich ein Download-Symbol in der Kopfzeile.

## Benutzung

1. Menüeintrag öffnen, URL einer Serien-/Playlist-Seite oder einer einzelnen Folge einfügen → **Analysieren**
2. Serienname, Staffel, Qualität und Folgen prüfen/anpassen (Folgennummern sind editierbar)
3. **Download starten** – Fortschritt, Abbrechen und Entfernen in der Warteschlange

Ablage im Jellyfin-Schema:

```
/media/<Serie>/Season 01/<Serie> - S01E03 - <Titel>.mkv
```

Bereits vorhandene Folgen werden übersprungen. Mit `JELLYFIN_URL` + `JELLYFIN_API_KEY` stößt das Backend nach fertigen Downloads automatisch einen Bibliotheksscan an.

## Konfiguration (Umgebungsvariablen des Backends)

| Variable | Standard | Bedeutung |
|---|---|---|
| `API_KEY` | – (Pflicht) | Geheimer Schlüssel; Dienst startet ohne ihn nicht |
| `MAX_CONCURRENT` | `2` | Parallele Downloads |
| `OUTPUT_FORMAT` | `mkv` | `mkv` oder `mp4` (Container beim Zusammenführen) |
| `DEFAULT_QUALITY` | `best` | `best`, `1080`, `720`, `480` |
| `RATE_LIMIT` | leer | Bandbreitenlimit pro Download, z. B. `5M` |
| `JELLYFIN_URL` / `JELLYFIN_API_KEY` | leer | Automatischer Bibliotheksscan |
| `ALLOW_PRIVATE_URLS` | `false` | Erlaubt Downloads von internen Adressen (SSRF-Schutz aus) |
| `YTDLP_AUTO_UPDATE` | `true` | Aktualisiert yt-dlp bei jedem Containerstart |

## Unterstützte Quellen

Als Download-Engine dient **[yt-dlp](https://github.com/yt-dlp/yt-dlp)**. Unterstützt ist, was yt-dlp kann (viele Seiten, direkte `.mp4`/`.m3u8`-Links, Seiten mit eingebettetem Player). Für Seiten ohne yt-dlp-Extractor lässt sich ein [yt-dlp-Plugin](https://github.com/yt-dlp/yt-dlp#plugins) in `/data` ablegen. Bitte lade nur Inhalte herunter, zu denen du die Rechte hast bzw. deren Nutzungsbedingungen das erlauben.

## Fehlersuche

- **Kein Menüeintrag**: Jellyfin-Log nach `H!Anime Downloader` durchsuchen. Meldung „FileTransformation … nicht gefunden“ → File Transformation installieren, Jellyfin neu starten. Browser-Cache leeren.
- **„Downloader nicht erreichbar“**: Backend-URL im Plugin prüfen (muss vom Jellyfin-*Container* aus erreichbar sein); beide Container im selben Docker-Netzwerk?
- **401 / Ungültiger API-Key**: `API_KEY` und Plugin-Einstellung stimmen nicht überein.
- **Analyse schlägt fehl**: yt-dlp unterstützt die Seite (noch) nicht oder ist veraltet → Container neu starten (Auto-Update).
- **Dateien gehören root**: `user:` in der Compose-Datei setzen.

## Entwicklung

```bash
cd backend && pip install -r requirements-dev.txt && python -m pytest -q
node --check web/client.js
./plugin/build.sh 10.11
```

Die UI-Datei `web/client.js` wird beim Plugin-Build als Ressource eingebettet.

## Sicherheitshinweise

- API-Key geheim halten und das Backend nicht per Port-Freigabe ins Internet stellen.
- Jeder Jellyfin-Benutzer kann Downloads starten und die gemeinsame Warteschlange sehen (gewünscht: „jeder per WebUI“). Eine Beschränkung auf Administratoren ist aktuell nicht eingebaut.
- URLs auf private/interne Adressen werden standardmäßig abgelehnt (SSRF-Schutz).
