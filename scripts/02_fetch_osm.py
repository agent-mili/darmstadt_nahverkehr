"""Schritt 2: OSM-Tramgleise und ÖPNV-Linienrelationen für Darmstadt per Overpass holen."""
import json, sys
from pathlib import Path
import requests

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "data/osm"
OUT.mkdir(parents=True, exist_ok=True)
URL = "https://overpass-api.de/api/interpreter"

QUERIES = {
    "tram_tracks": """
[out:json][timeout:120];
area["name"="Darmstadt"]["boundary"="administrative"]["admin_level"="6"]->.a;
( way["railway"~"^(tram|light_rail)$"](area.a); );
out body geom;""",
    "route_relations": """
[out:json][timeout:180];
area["name"="Darmstadt"]["boundary"="administrative"]["admin_level"="6"]->.a;
( relation["type"="route"]["route"~"^(tram|bus|train|light_rail)$"](area.a); );
out body geom;""",
}

for name, q in QUERIES.items():
    r = requests.post(URL, data={"data": q}, timeout=300, headers={"User-Agent": "darmstadt-nahverkehr/0.1"})
    r.raise_for_status()
    data = r.json()
    (OUT / f"{name}.json").write_text(json.dumps(data))
    print(name, len(data["elements"]), file=sys.stderr)
