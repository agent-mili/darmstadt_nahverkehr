# Nahverkehr Darmstadt – animierte Karte

Straßenbahnen, Busse und S-Bahnen in Darmstadt im Lauf eines Tages, nach Fahrplan
(Werktag, Samstag, Sonntag) – inkl. Echtzeit-Modus nach aktueller Uhrzeit.

**Live:** https://agent-mili.github.io/darmstadt_nahverkehr/

## Aufbau

```
docs/            die Webseite (GitHub Pages), rein statisch
  index.html     Karte: MapLibre GL + deck.gl, alles im Browser
  data/          vorberechnete Daten (~3 MB): Linien, Haltestellen, Fahrten, Verläufe
scripts/         Pipeline, die docs/data/ erzeugt
data/            Roh- und Zwischendaten (nicht im Repo, ~800 MB)
```

Lokal ansehen (direkt `index.html` öffnen geht nicht, der Browser blockiert dann das Laden der Daten):

```
python3 -m http.server 8765 -d docs     # → http://localhost:8765
```

## Daten neu bauen

Voraussetzungen: Python 3.10+, Docker, curl.

```
python3 -m venv .venv && .venv/bin/pip install -r scripts/requirements.txt
scripts/build_all.sh              # lädt fehlende Rohdaten (~615 MB), dann alle Schritte
FRESH=1 scripts/build_all.sh      # Rohdaten neu laden, z. B. für einen neuen Fahrplan
```

Dauer ohne Download: ca. 2 Minuten.

| Schritt | Skript | Ergebnis |
|---|---|---|
| 0 | Download: [gtfs.de](https://gtfs.de) Nah- und Regionalverkehr, [Geofabrik](https://download.geofabrik.de) Hessen-OSM | `data/raw/` |
| 1 | `01_filter_gtfs.py` – bundesweiten Fahrplan auf Fahrten mit Halt in Darmstadt zuschneiden | `data/gtfs_da/` |
| 2 | [pfaedle](https://github.com/ad-freiburg/pfaedle) (Docker) – Fahrten auf das OSM-Straßen- und Schienennetz legen | `data/gtfs_da_shapes/` |
| 3 | `02_fetch_osm.py` – Straßenbahngleise und Linienrelationen per Overpass | `data/osm/` |
| 4 | `03_build_outputs.py` – Webdaten und Analyse-Dateien (GeoJSON/CSV) | `docs/data/`, `data/output/` |

**Stichtage:** Die drei dargestellten Tage stehen in `scripts/03_build_outputs.py` (`DAYS`).
Sie müssen im Gültigkeitszeitraum des Fahrplans liegen und sollten Ferien und Feiertage meiden –
bei einem neuen Fahrplan also anpassen.

## Quellen und Lizenzen

- Fahrplandaten: DELFI e.V. / [gtfs.de](https://gtfs.de), CC BY 4.0
- Linienverläufe und Gleise: © [OpenStreetMap](https://www.openstreetmap.org/copyright)-Mitwirkende, ODbL
- Hintergrundkarte: © [CARTO](https://carto.com/attributions)
