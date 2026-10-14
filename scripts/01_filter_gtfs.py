"""Schritt 1: Bundesweite gtfs.de-Feeds (nv_free + rv_free) auf Darmstadt zuschneiden.

Behält alle Fahrten mit mindestens einem Halt in der Stadtgebiet-BBox (vollständig,
auch Abschnitte außerhalb) plus zugehörige routes/stops/calendar. IDs werden je Feed
präfixiert ("nv:", "rv:"), da die Feeds eigene ID-Räume haben. Ergebnis: ein
zusammengeführter GTFS-Feed in data/gtfs_da/.
"""
import io, re, sys, zipfile
from pathlib import Path
import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
FEEDS = {"nv": ROOT / "data/raw/gtfs_de_nv.zip", "rv": ROOT / "data/raw/gtfs_de_rv.zip"}
OUT = ROOT / "data/gtfs_da"
OUT.mkdir(parents=True, exist_ok=True)

# Stadtgebiet Darmstadt (inkl. Arheilgen, Wixhausen, Eberstadt, Kranichstein)
BBOX = dict(lat_min=49.805, lat_max=49.960, lon_min=8.560, lon_max=8.760)
# Fernverkehr ausschließen (Schreibweisen variieren je Feed)
EXCLUDE_AGENCIES = re.compile(r"flix|fernverkehr|öbb", re.I)
ID_COLS = ["stop_id", "parent_station", "trip_id", "route_id", "service_id", "agency_id"]


def prefix(df, p):
    for c in ID_COLS:
        if c in df:
            df[c] = df[c].where(df[c] == "", p + ":" + df[c])
    return df


def filter_feed(p, path):
    z = zipfile.ZipFile(path)
    read = lambda n: pd.read_csv(z.open(n), dtype=str, keep_default_na=False)

    agency = read("agency.txt")
    routes = read("routes.txt")
    trips = read("trips.txt")
    bad_routes = set(routes[routes.agency_id.isin(agency[agency.agency_name.str.contains(EXCLUDE_AGENCIES)].agency_id)].route_id)
    allowed_trips = set(trips[~trips.route_id.isin(bad_routes)].trip_id)

    stops = read("stops.txt")
    lat, lon = stops.stop_lat.astype(float), stops.stop_lon.astype(float)
    da_stop_ids = set(stops[lat.between(BBOX["lat_min"], BBOX["lat_max"]) &
                            lon.between(BBOX["lon_min"], BBOX["lon_max"])].stop_id)

    # stop_times streamend: Zeilen sind nach trip_id gruppiert -> je Fahrt puffern
    rows, keep = [], set()
    buf, cur, hit, seen = [], None, False, set()
    with z.open("stop_times.txt") as fh:
        txt = io.TextIOWrapper(fh, encoding="utf-8")
        header = txt.readline()
        for line in txt:
            tid, rest = line.split(",", 1)
            if tid != cur:
                if hit and cur in allowed_trips:
                    rows.extend(buf); keep.add(cur)
                if tid in seen:
                    raise SystemExit(f"{p}: stop_times nicht nach trip_id gruppiert ({tid})")
                seen.add(cur)
                buf, cur, hit = [], tid, False
            buf.append(line)
            if not hit:
                hit = rest.split(",", 3)[2] in da_stop_ids
        if hit and cur in allowed_trips:
            rows.extend(buf); keep.add(cur)
    st = pd.read_csv(io.StringIO(header + "".join(rows)), dtype=str, keep_default_na=False)

    trips = trips[trips.trip_id.isin(keep)]
    routes = routes[routes.route_id.isin(trips.route_id)]
    agency = agency[agency.agency_id.isin(routes.agency_id)]
    cal = read("calendar.txt"); cal = cal[cal.service_id.isin(trips.service_id)]
    cd = read("calendar_dates.txt"); cd = cd[cd.service_id.isin(trips.service_id)]
    used = stops[stops.stop_id.isin(st.stop_id)]
    stops = pd.concat([used, stops[stops.stop_id.isin(used.parent_station)]]).drop_duplicates("stop_id")
    print(f"{p}: {len(da_stop_ids)} Stops in BBox, {len(keep)} Fahrten, {len(routes)} Linien", file=sys.stderr)
    return {n: prefix(df, p) for n, df in dict(agency=agency, routes=routes, trips=trips, stop_times=st,
                                               calendar=cal, calendar_dates=cd, stops=stops).items()}


parts = [filter_feed(p, path) for p, path in FEEDS.items()]
for name in parts[0]:
    pd.concat([pt[name] for pt in parts]).to_csv(OUT / f"{name}.txt", index=False)
z = zipfile.ZipFile(FEEDS["nv"])
for n in ("feed_info.txt", "attributions.txt"):
    (OUT / n).write_bytes(z.read(n))
