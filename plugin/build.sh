#!/usr/bin/env bash
# Baut das Plugin und packt es als ZIP (dll + meta.json) nach dist/.
# Nutzung:  plugin/build.sh [12|10.11]      (Standard: 12 = Jellyfin 12.4)
set -euo pipefail
cd "$(dirname "$0")"

TARGET="${1:-12}"
case "$TARGET" in
  10.11) TFM=net9.0;  JF_VERSION=10.11.0; ABI=10.11.0.0 ;;
  12)    TFM=net10.0; JF_VERSION=12.4.0;  ABI=12.4.0.0 ;;
  *) echo "Unbekanntes Ziel '$TARGET' (erlaubt: 10.11, 12)"; exit 1 ;;
esac

PROJECT=Jellyfin.Plugin.HAnimeDownloader
OUT="$(pwd)/../dist/jellyfin-$TARGET"
rm -rf "$OUT" && mkdir -p "$OUT"

dotnet build "$PROJECT/$PROJECT.csproj" -c Release -p:JellyfinTfm="$TFM" -p:JellyfinVersion="$JF_VERSION" -o "$OUT/build"
cp "$OUT/build/$PROJECT.dll" "$OUT/"
cat > "$OUT/meta.json" <<JSON
{
  "guid": "e286ec7b-b08d-40dc-ac58-3788907d65f7",
  "name": "H!Anime Downloader",
  "description": "Web-Oberflaeche zum Herunterladen von Serien direkt in die Jellyfin-Bibliothek.",
  "overview": "Fuegt Jellyfin ein Download-Menue hinzu (benoetigt File Transformation).",
  "owner": "ByQuadiix",
  "category": "General",
  "version": "1.1.0.0",
  "targetAbi": "$ABI",
  "framework": "$TFM",
  "changelog": "Erste Version"
}
JSON
rm -rf "$OUT/build"
( cd "$OUT" && zip -q -j "../HAnimeDownloader_$TARGET.zip" "$PROJECT.dll" meta.json )
echo "Fertig: dist/HAnimeDownloader_$TARGET.zip"
