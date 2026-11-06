"""Generate the GitHub map from the checked-in school roster and campus crosswalk."""

import csv
import json
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent
SNAPSHOT = "2026-11-05"


def read_rows(name):
    with (ROOT / name).open(encoding="utf-8-sig", newline="") as source:
        return list(csv.DictReader(source))


def build_map():
    roster = read_rows("nyc-open-charter-schools.csv")
    schools = {row["BEDS Code"]: row["Charter Schools"] for row in roster}
    if len(roster) != 286 or len(schools) != 286:
        raise ValueError("Expected 286 unique schools in the 2026–27 roster")
    unresolved = sum(row["decision"] == "unresolved" for row in read_rows("reconciliation.csv"))
    status = "Partial campus coverage" if unresolved else "Campus reconciliation complete"
    groups = defaultdict(list)
    for campus in read_rows("campuses.csv"):
        point = float(campus["longitude"]), float(campus["latitude"])
        groups[point].append(campus)
    features = []
    for point, rows in sorted(groups.items()):
        rows.sort(key=lambda row: (row["name"].casefold(), row["campus_id"]))
        borough, = {row["borough"] for row in rows}
        addresses = sorted({row["address"] for row in rows})
        campuses = []
        for row in rows:
            campus = {key: row[key] for key in ("campus_id", "name", "dbn", "beds", "address", "verified_on")}
            campus.update(school=schools[row["beds"]], source=row["evidence"] or row["source"],
                          coordinate_source=row["geocode_evidence"])
            campuses.append(campus)
        details = " • ".join(f"{c['name']} — {c['address']} (BEDS {c['beds']})" for c in campuses)
        features.append({
            "type": "Feature",
            "geometry": {"type": "Point", "coordinates": list(point)},
            "properties": {
                "title": campuses[0]["name"] if len(campuses) == 1 else addresses[0],
                "description": f"{borough} | {details} | 2026–27 · {SNAPSHOT} · {status}",
                "borough": borough,
                "addresses": addresses,
                "campuses": campuses,
            },
        })
    header = {"type": "FeatureCollection", "name": "NYC charter school campuses · 2026–27",
              "snapshot": SNAPSHOT, "coverage": status, "unresolved_source_records": unresolved}
    def encode(value):
        return json.dumps(value, ensure_ascii=False, allow_nan=False, separators=(",", ":"))
    content = encode(header)[:-1] + ',"features":[\n'
    content += ",\n".join(map(encode, features)) + "\n]}\n"
    (ROOT / "nyc-charter-campuses.geojson").write_text(content, encoding="utf-8")


if __name__ == "__main__":
    build_map()
