#!/usr/bin/env bash
# Baut die Kartendaten (docs/data/) und die Analyse-Ausgaben (data/output/) komplett neu.
#
#   scripts/build_all.sh            fehlende Rohdaten laden, dann alle Schritte
#   FRESH=1 scripts/build_all.sh    Rohdaten neu laden (aktueller Fahrplan)
#
# Voraussetzungen: Python 3.10+ mit scripts/requirements.txt, Docker, curl.
set -euo pipefail
cd "$(dirname "$0")/.."

PY=${PY:-$( [ -x .venv/bin/python ] && echo .venv/bin/python || echo python3 )}
PFAEDLE_IMAGE=ghcr.io/ad-freiburg/pfaedle:latest
mkdir -p data/raw logs

fetch() {  # fetch <url> <ziel>
  if [ -n "${FRESH:-}" ] || [ ! -s "$2" ]; then
    echo "→ lade $(basename "$2")"
    curl -fL --retry 3 -o "$2.part" "$1" && mv "$2.part" "$2"
  fi
}

echo "== 0  Rohdaten"
fetch https://download.gtfs.de/germany/nv_free/latest.zip                 data/raw/gtfs_de_nv.zip
fetch https://download.gtfs.de/germany/rv_free/latest.zip                 data/raw/gtfs_de_rv.zip
fetch https://download.geofabrik.de/europe/germany/hessen-latest.osm.pbf  data/raw/hessen-latest.osm.pbf

echo "== 1  GTFS auf Darmstadt zuschneiden"
"$PY" scripts/01_filter_gtfs.py

echo "== 2  Linienverläufe per pfaedle auf OSM-Netz legen (≈1 min, Log: logs/pfaedle.log)"
rm -rf data/gtfs_da_shapes && mkdir -p data/gtfs_da_shapes
docker run --rm -u "$(id -u):$(id -g)" -v "$PWD/data:/data" "$PFAEDLE_IMAGE" \
  -x /data/raw/hessen-latest.osm.pbf -i /data/gtfs_da -o /data/gtfs_da_shapes \
  --stats -d /data/gtfs_da_shapes > logs/pfaedle.log 2>&1

echo "== 3  OSM-Gleise und Linienrelationen (Overpass)"
"$PY" scripts/02_fetch_osm.py

echo "== 4  Ausgaben bauen"
"$PY" scripts/03_build_outputs.py

echo "Fertig. Lokal ansehen: python3 -m http.server 8765 -d docs → http://localhost:8765"
