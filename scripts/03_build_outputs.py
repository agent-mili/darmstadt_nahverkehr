"""Schritt 3: Datensatz + Animationsdaten bauen.

Eingaben:  data/gtfs_da_shapes/ (GTFS mit pfaedle-Shapes), data/osm/*.json
Ausgaben:
  data/output/stops.geojson          Haltestellen (Stationen, zusammengefasst) mit bedienenden Linien
  data/output/routes.geojson         Linienverläufe je Linie/Shape-Variante
  data/output/tram_tracks.geojson    OSM-Straßenbahngleise
  data/output/osm_routes.geojson     OSM-Linienrelationen
  data/output/lines.csv              Linienübersicht (Fahrten je Tagestyp, erste/letzte Abfahrt)
  data/output/timetable_<tag>.csv    Fahrpläne je Tagestyp (eine Zeile je Halt)
  docs/data/shapes.json               vereinfachte Shapes für die Animation
  docs/data/trips_<tag>.json          Fahrten je Tagestyp: Shape-Ref + (Distanz, Zeit)-Stützstellen
  docs/data/meta.json                 Linien, Farben, Stationen, Tagestypen
"""
import csv, json, math, datetime as dt
from pathlib import Path
import pandas as pd
from shapely.geometry import LineString

ROOT = Path(__file__).resolve().parent.parent
G = ROOT / "data/gtfs_da_shapes"
OSM = ROOT / "data/osm"
OUT = ROOT / "data/output"
WEB = ROOT / "docs/data"
OUT.mkdir(parents=True, exist_ok=True)
WEB.mkdir(parents=True, exist_ok=True)

# Repräsentative Stichtage (Schulzeit, keine Feiertage, außerhalb der Herbstferien)
DAYS = {"werktag": "20261020", "samstag": "20261024", "sonntag": "20261018"}
MODE = {0: "tram", 2: "rail", 3: "bus", 109: "rail"}

read = lambda n: pd.read_csv(G / f"{n}.txt", dtype=str, keep_default_na=False)
routes, trips, stops = read("routes"), read("trips"), read("stops")
agency, cal, cd = read("agency"), read("calendar"), read("calendar_dates")
st = read("stop_times")
st["seq"] = st.stop_sequence.astype(int)
st["dist"] = st.shape_dist_traveled.astype(float)
st = st.sort_values(["trip_id", "seq"])


def secs(t):
    h, m, s = map(int, t.split(":"))
    return h * 3600 + m * 60 + s


st["arr"] = st.arrival_time.map(secs)
st["dep"] = st.departure_time.map(secs)

# --- Stationen: Steige über parent_station zusammenfassen, feedübergreifend über die DELFI-ID
stops["lat"], stops["lon"] = stops.stop_lat.astype(float), stops.stop_lon.astype(float)
raw = lambda s: s.split(":", 1)[1] if ":" in s else s
stops["station"] = [raw(p) if p else raw(s) for s, p in zip(stops.stop_id, stops.parent_station)]
station_name = {}
for _, r in stops[stops.location_type == "1"].iterrows():
    station_name.setdefault(raw(r.stop_id), r.stop_name)
for _, r in stops.iterrows():
    station_name.setdefault(r.station, r.stop_name)
stop_station = dict(zip(stops.stop_id, stops.station))
st["station"] = st.stop_id.map(stop_station)
st["stop_name"] = st.station.map(station_name)

# --- Linien
routes["mode"] = routes.route_type.astype(int).map(MODE).fillna("bus")
routes = routes.merge(agency[["agency_id", "agency_name"]], on="agency_id", how="left")
# gleiche Linie (Name+Modus) aus mehreren Feeds/Unternehmen zusammenfassen, z.B. "693"
routes["line_key"] = routes["mode"] + ":" + routes.route_short_name
trips = trips.merge(routes[["route_id", "line_key", "route_short_name", "mode", "agency_name"]], on="route_id")

# --- aktive Fahrten je Stichtag
WD = ["monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"]


def active_services(ds):
    d = dt.datetime.strptime(ds, "%Y%m%d").date()
    act = set(cal[(cal[WD[d.weekday()]] == "1") & (cal.start_date <= ds) & (cal.end_date >= ds)].service_id)
    x = cd[cd.date == ds]
    return (act | set(x[x.exception_type == "1"].service_id)) - set(x[x.exception_type == "2"].service_id)


day_trips = {k: set(trips[trips.service_id.isin(active_services(v))].trip_id) for k, v in DAYS.items()}

# --- Farben: nur nach Verkehrsart (gleiche Werte wie --tram/--bus/--rail in docs/index.html)
MODE_COLORS = {"tram": "#ff6b6b", "bus": "#2ec4b6", "rail": "#c77dff"}
line_meta = {k: MODE_COLORS[k.split(":")[0]] for k in routes.line_key.unique()}
line_agency = trips.groupby("line_key").agency_name.agg(lambda s: s.mode()[0]).to_dict()

# --- Shapes laden, vereinfachen
sh = read("shapes")
sh["lat"], sh["lon"] = sh.shape_pt_lat.astype(float), sh.shape_pt_lon.astype(float)
sh["seq"] = sh.shape_pt_sequence.astype(int)
sh["d"] = sh.shape_dist_traveled.astype(float)
sh = sh.sort_values(["shape_id", "seq"])
shape_geom, shape_len = {}, {}
for sid, g in sh.groupby("shape_id", sort=False):
    coords = list(zip(g.lon.round(6), g.lat.round(6)))
    shape_geom[sid] = coords
    shape_len[sid] = g.d.iloc[-1]

used_shapes = set(trips.shape_id)


def simplify(coords, tol_m=4.0):
    # grob in Meter projizieren (lokal genügt), Douglas-Peucker, zurück
    lat0 = coords[0][1]
    kx, ky = 111320 * math.cos(math.radians(lat0)), 110540
    ls = LineString([(x * kx, y * ky) for x, y in coords]).simplify(tol_m, preserve_topology=False)
    return [(round(x / kx, 5), round(y / ky, 5)) for x, y in ls.coords]


def cumdist(coords):
    out, acc = [0.0], 0.0
    for (x1, y1), (x2, y2) in zip(coords, coords[1:]):
        kx = 111320 * math.cos(math.radians((y1 + y2) / 2))
        acc += math.hypot((x2 - x1) * kx, (y2 - y1) * 110540)
        out.append(acc)
    return out


web_shapes, shape_index, shape_scale = [], {}, {}
for sid in sorted(used_shapes):
    s = simplify(shape_geom[sid])
    cd_ = cumdist(s)
    shape_index[sid] = len(web_shapes)
    # pfaedle-Distanzen auf die Länge der vereinfachten Linie skalieren
    shape_scale[sid] = (cd_[-1] / shape_len[sid]) if shape_len[sid] > 0 else 1.0
    web_shapes.append([c for xy in s for c in xy])  # flach: [lon,lat,lon,lat,...]
(WEB / "shapes.json").write_text(json.dumps(web_shapes, separators=(",", ":")))

# --- Animationsfahrten je Tagestyp
line_keys = sorted(line_meta, key=lambda k: ({"rail": 0, "tram": 1, "bus": 2}[k.split(":")[0]], len(k), k))
line_idx = {k: i for i, k in enumerate(line_keys)}
tinfo = trips.set_index("trip_id")
groups = {tid: g for tid, g in st.groupby("trip_id", sort=False)}

for day, tids in day_trips.items():
    out = []
    for tid in sorted(tids, key=lambda t: groups[t].arr.iloc[0]):
        g, t = groups[tid], tinfo.loc[tid]
        scale = shape_scale[t.shape_id]
        pts = []
        for d, a, dp in zip(g.dist, g.arr, g.dep):
            d = round(d * scale)
            pts += [d, a]
            if dp > a:
                pts += [d, dp]
        out.append([line_idx[t.line_key], shape_index[t.shape_id], g.stop_name.iloc[-1], pts])
    (WEB / f"trips_{day}.json").write_text(json.dumps(out, separators=(",", ":"), ensure_ascii=False))
    print(day, DAYS[day], len(out), "Fahrten")

# --- Stationen (Punkte) inkl. bedienender Linien
st_line = st.merge(trips[["trip_id", "line_key"]], on="trip_id")
station_lines = st_line.groupby("station").line_key.agg(lambda s: sorted(set(s))).to_dict()
stations = (stops.groupby("station")
            .agg(lat=("lat", "mean"), lon=("lon", "mean"))
            .reset_index())
stations = stations[stations.station.isin(station_lines)]
stations["name"] = stations.station.map(station_name)

feat = lambda geom, props: {"type": "Feature", "geometry": geom, "properties": props}
fc = lambda fs: {"type": "FeatureCollection", "features": fs}
(OUT / "stops.geojson").write_text(json.dumps(fc([
    feat({"type": "Point", "coordinates": [round(r.lon, 6), round(r.lat, 6)]},
         {"id": r.station, "name": r.name,
          "lines": [k.split(":", 1)[1] for k in station_lines[r.station]],
          "modes": sorted({k.split(":")[0] for k in station_lines[r.station]})})
    for r in stations.itertuples()]), ensure_ascii=False))

meta_stations = [[r.name, round(r.lon, 5), round(r.lat, 5),
                  sorted({k.split(":")[0] for k in station_lines[r.station]})]
                 for r in stations.itertuples()]

# --- Linienverläufe je Shape-Variante (voller Detailgrad)
counts = {d: trips[trips.trip_id.isin(ts)].groupby("shape_id").size().to_dict() for d, ts in day_trips.items()}
first_last = st.groupby("trip_id").agg(first=("stop_name", "first"), last=("stop_name", "last"))
variants = trips.drop_duplicates("shape_id").set_index("shape_id")

# häufigste Endhalte je Linie (Werktag bevorzugt), für die Linienleiste
def line_ends(g):
    wk = g[g.trip_id.isin(day_trips["werktag"])]
    fl = first_last.loc[(wk if len(wk) else g).trip_id]
    pair = fl.apply(lambda r: tuple(sorted((r["first"], r["last"]))), axis=1).value_counts().index[0]
    return list(pair)
ends = trips.groupby("line_key").apply(line_ends).to_dict()
feats = []
for sid, t in variants.iterrows():
    fl = first_last.loc[t.trip_id]
    feats.append(feat({"type": "LineString", "coordinates": shape_geom[sid]},
                      {"shape_id": sid, "line": t.route_short_name, "mode": t["mode"],
                       "agency": t.agency_name, "color": line_meta[t.line_key],
                       "from": fl["first"], "to": fl["last"],
                       **{f"trips_{d}": int(counts[d].get(sid, 0)) for d in DAYS}}))
(OUT / "routes.geojson").write_text(json.dumps(fc(feats), ensure_ascii=False))

# --- Fahrpläne (CSV) + Linienübersicht
fmt = lambda s: f"{s // 3600:02d}:{s % 3600 // 60:02d}"
summary = []
for day, tids in day_trips.items():
    x = st[st.trip_id.isin(tids)].merge(
        trips[["trip_id", "route_short_name", "mode", "agency_name", "line_key"]], on="trip_id")
    x = x.merge(stops[["stop_id", "lat", "lon"]], on="stop_id")
    x["to"] = x.trip_id.map(first_last["last"])
    x["arrival"], x["departure"] = x.arr.map(fmt), x.dep.map(fmt)
    x = x.sort_values(["mode", "route_short_name", "trip_id", "seq"])
    x[["route_short_name", "mode", "agency_name", "trip_id", "to", "seq", "stop_name", "stop_id",
       "lat", "lon", "arrival", "departure"]].rename(columns={
        "route_short_name": "line", "agency_name": "agency", "seq": "stop_sequence"}).to_csv(
        OUT / f"timetable_{day}.csv", index=False)
    dep0 = x.groupby("trip_id").dep.min()
    for lk, g in x.groupby("line_key"):
        d = dep0[g.trip_id.unique()]
        summary.append(dict(line=lk.split(":", 1)[1], mode=lk.split(":")[0], day=day,
                            agency=line_agency.get(lk), trips=len(d),
                            first_departure=fmt(d.min()), last_departure=fmt(d.max())))
pd.DataFrame(summary).pivot_table(
    index=["mode", "line", "agency"], columns="day",
    values=["trips", "first_departure", "last_departure"], aggfunc="first"
).to_csv(OUT / "lines.csv")

# --- OSM: Tramgleise + Linienrelationen
osm = json.loads((OSM / "tram_tracks.json").read_text())
(OUT / "tram_tracks.geojson").write_text(json.dumps(fc([
    feat({"type": "LineString", "coordinates": [[p["lon"], p["lat"]] for p in e["geometry"]]},
         {"osm_id": e["id"], **e.get("tags", {})})
    for e in osm["elements"] if e["type"] == "way"]), ensure_ascii=False))
rel = json.loads((OSM / "route_relations.json").read_text())
(OUT / "osm_routes.geojson").write_text(json.dumps(fc([
    feat({"type": "MultiLineString",
          "coordinates": [[[p["lon"], p["lat"]] for p in m["geometry"]]
                          for m in e["members"] if m["type"] == "way" and "geometry" in m]},
         {"osm_id": e["id"], **e.get("tags", {})})
    for e in rel["elements"]]), ensure_ascii=False))
tracks_web = [[c for p in e["geometry"] for c in (round(p["lon"], 5), round(p["lat"], 5))]
              for e in osm["elements"] if e["type"] == "way"]

(WEB / "meta.json").write_text(json.dumps({
    "lines": [{"key": k, "name": k.split(":", 1)[1], "mode": k.split(":")[0],
               "agency": line_agency.get(k), "color": line_meta[k], "ends": ends[k]} for k in line_keys],
    "days": DAYS,
    "stations": meta_stations,
    "tram_tracks": tracks_web,
}, separators=(",", ":"), ensure_ascii=False))
print("fertig")
