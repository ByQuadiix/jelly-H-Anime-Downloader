#!/bin/sh
set -e
mkdir -p "$DATA_DIR" 2>/dev/null || true

# yt-dlp muss haeufig aktualisiert werden, weil sich Webseiten staendig aendern.
# Das Update landet im Datenordner, damit auch nicht-root-Benutzer es ausfuehren koennen.
if [ "${YTDLP_AUTO_UPDATE:-true}" != "false" ]; then
  pip install --quiet --disable-pip-version-check --upgrade --target "$DATA_DIR/ytdlp" yt-dlp \
    || echo "yt-dlp-Update fehlgeschlagen - nutze die mitgelieferte Version."
  export PYTHONPATH="$DATA_DIR/ytdlp:${PYTHONPATH:-}"
fi

exec python -m uvicorn app.main:app_factory --factory --host 0.0.0.0 --port 8080
