#!/usr/bin/env python3
"""Validate the published map against the captured school and campus rosters."""

import argparse
import copy
import csv
import gzip
import json
import math
from collections import Counter
from functools import lru_cache
from pathlib import Path

ROOT = Path(__file__).resolve().parent
ROSTERS = ROOT


def read_csv(name):
    with (ROSTERS / name).open(encoding="utf-8", newline="") as file:
        return list(csv.DictReader(file))


def inside_ring(x, y, ring):
    inside = False
    previous_x, previous_y = ring[-1]
    for current_x, current_y in ring:
        if (current_y > y) != (previous_y > y):
            crossing_x = (
                (previous_x - current_x) * (y - current_y) / (previous_y - current_y)
                + current_x
            )
            if x < crossing_x:
                inside = not inside
        previous_x, previous_y = current_x, current_y
    return inside


class BoroughBoundaries:
    def __init__(self, features):
        self.polygons = []
        for feature in features:
            geometry = feature["geometry"]
            polygons = geometry["coordinates"]
            if geometry["type"] == "Polygon":
                polygons = [polygons]
            for exterior, *holes in polygons:
                xs, ys = zip(*exterior)
                bounds = min(xs), min(ys), max(xs), max(ys)
                self.polygons.append((feature["properties"]["boroname"], bounds, exterior, holes))

    @lru_cache(maxsize=2048)
    def containing(self, x, y):
        for borough, bounds, exterior, holes in self.polygons:
            left, bottom, right, top = bounds
            if (
                left <= x <= right and bottom <= y <= top
                and inside_ring(x, y, exterior)
                and not any(inside_ring(x, y, hole) for hole in holes)
            ):
                return borough
        return None


def validate(document, schools, campuses, boundaries):
    errors = []
    expected = {row["campus_id"]: row for row in campuses}
    active = {row["beds"]: row for row in schools}
    seen_campuses = Counter()
    seen_schools = set()
    points = set()
    site_addresses = set()
    if document.get("type") != "FeatureCollection":
        return ["Expected a GeoJSON FeatureCollection"], {}
    for feature in document.get("features", []):
        properties = feature.get("properties") or {}
        geometry = feature.get("geometry") or {}
        coordinates = geometry.get("coordinates")
        if (
            feature.get("type") != "Feature" or geometry.get("type") != "Point"
            or not isinstance(coordinates, list) or len(coordinates) != 2
            or not all(type(value) in (float, int) and math.isfinite(value) for value in coordinates)
            or not (-180 <= coordinates[0] <= 180 and -90 <= coordinates[1] <= 90)
        ):
            errors.append(f"Invalid GeoJSON point for {properties.get('title')}")
            continue
        location = tuple(coordinates)
        if location in points:
            errors.append(f"Overlapping pins at {location}")
        points.add(location)
        borough = boundaries.containing(*location)
        if borough != properties.get("borough"):
            errors.append(f"Wrong borough for {properties.get('title')}")
        markers = properties.get("campuses", [])
        if not markers:
            errors.append(f"Pin has no campuses at {location}")
        for mapped in markers:
            campus_id = mapped.get("campus_id")
            seen_campuses[campus_id] += 1
            beds = mapped.get("beds")
            if beds in active:
                seen_schools.add(beds)
            else:
                errors.append(f"Unexpected school {beds} for {campus_id}")
            reference = expected.get(campus_id)
            if not reference:
                errors.append(f"Unexpected campus {campus_id}")
                continue
            for field in ("beds", "dbn", "name", "address"):
                if mapped.get(field) != reference[field]:
                    errors.append(f"Wrong {field} for {campus_id}")
            if reference["borough"] != borough:
                errors.append(f"Campus {campus_id} is outside {reference['borough']}")
            if not reference["longitude"] or location != (
                float(reference["longitude"]), float(reference["latitude"])
            ):
                errors.append(f"Pin differs from verified address point for {campus_id}")
            site_addresses.add((reference["borough"], reference["address"], location))

    missing = set(expected) - seen_campuses.keys()
    duplicates = [campus for campus, count in seen_campuses.items() if count > 1]
    absent_schools = set(active) - seen_schools
    for campus in sorted(missing):
        errors.append(f"Missing campus {campus} ({expected[campus]['name']})")
    for campus in duplicates:
        errors.append(f"Duplicate campus {campus}")
    for beds in sorted(absent_schools):
        errors.append(f"Missing school {beds} ({active[beds]['name']})")

    addresses_to_points = {}
    for borough, address, location in site_addresses:
        addresses_to_points.setdefault((borough, address.casefold()), set()).add(location)
    for site, locations in addresses_to_points.items():
        if len(locations) != 1:
            errors.append(f"One site has multiple pins at {site}")

    metrics = {
        "schools": len(seen_schools),
        "expected_schools": len(active),
        "campuses": len(seen_campuses.keys() & expected.keys()),
        "expected_campuses": len(expected),
        "pins": len(points),
        "schools_by_authorizer": dict(Counter(active[key]["authorizer"] for key in seen_schools)),
        "campuses_by_borough": dict(Counter(expected[key]["borough"] for key in seen_campuses.keys() & expected.keys())),
        "pins_by_borough": dict(Counter(boundaries.containing(*point) for point in points)),
    }
    return errors, metrics


def source_checks(schools, campuses, audit, pages, hub_ids):
    errors = []
    if len(schools) != len({school["beds"] for school in schools}):
        errors.append("School reference has duplicate BEDS IDs")
    if len(schools) != len({school["dbn"] for school in schools}):
        errors.append("School reference has duplicate DBNs")
    if len(campuses) != len({campus["campus_id"] for campus in campuses}):
        errors.append("Campus reference has duplicate IDs")
    if any(school["status"] != "operating" or school["opened"] > "2026-11-04" for school in schools):
        errors.append("School reference contains a closed or future school")

    expected = {}
    for borough, capture in pages.items():
        ids = set(capture["listing_ids"])
        if len(ids) != capture["page_total"]:
            errors.append(f"Finder pagination coverage gap in {borough}")
        for listing_id in ids:
            if listing_id in expected:
                errors.append(f"Finder listing {listing_id} appears in multiple boroughs")
            expected[listing_id] = borough
    finder_audit = Counter(row["source_id"] for row in audit if row["source"] == "Finder")
    if finder_audit != Counter({key: 1 for key in expected}):
        errors.append("Finder listing audit fails exact ID reconciliation")
    hub_audit = Counter(row["source_id"] for row in audit if row["source"] == "Data Hub + Finder export")
    if hub_audit != Counter(hub_ids):
        errors.append("Data Hub audit fails exact ID reconciliation")
    return errors


def mutation_checks(document, schools, campuses, boundaries, baseline):
    baseline_errors = set(baseline)

    def check(label, edit, expected_error):
        fixture = copy.deepcopy(document)
        edit(fixture["features"])
        errors, _ = validate(fixture, schools, campuses, boundaries)
        return label, any(expected_error in error for error in set(errors) - baseline_errors)

    def remove_school(features):
        beds = features[0]["properties"]["campuses"][0]["beds"]
        for feature in features:
            feature["properties"]["campuses"] = [
                campus for campus in feature["properties"]["campuses"] if campus["beds"] != beds
            ]
        features[:] = [feature for feature in features if feature["properties"]["campuses"]]

    def closed_campus(features):
        campus = copy.deepcopy(features[0]["properties"]["campuses"][0])
        campus.update(campus_id="84M080-M056", beds="310100861031", dbn="84M080")
        features[0]["properties"]["campuses"].append(campus)

    def duplicate(features):
        features[0]["properties"]["campuses"].append(features[0]["properties"]["campuses"][0])

    def wrong_school(features):
        campus = features[0]["properties"]["campuses"][0]
        campus["beds"] = next(school["beds"] for school in schools if school["beds"] != campus["beds"])

    def wrong_borough(features):
        replacement = next(
            feature for feature in features if feature["properties"]["borough"] != features[0]["properties"]["borough"]
        )
        features[0]["geometry"]["coordinates"] = replacement["geometry"]["coordinates"]

    return dict([
        check("missing school", remove_school, "Missing school "),
        check("missing campus", lambda features: features[0]["properties"]["campuses"].pop(), "Missing campus "),
        check("closed school added", closed_campus, "Unexpected school 310100861031"),
        check("duplicate campus", duplicate, "Duplicate campus "),
        check("wrong school association", wrong_school, "Wrong beds "),
        check("wrong borough point", wrong_borough, "Wrong borough "),
    ])


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--report", action="store_true", help="Print the audit for a partial map and return success if its mapped records pass")
    args = parser.parse_args()
    schools = read_csv("schools.csv")
    campuses = read_csv("campuses.csv")
    audit = read_csv("reconciliation.csv")
    pages = json.loads((ROSTERS / "finder-pages.json").read_text(encoding="utf-8"))
    with gzip.open(ROSTERS / "borough-boundaries.geojson.gz", "rt", encoding="utf-8") as file:
        boundaries = BoroughBoundaries(json.load(file)["features"])
    document = json.loads((ROOT / "nyc-charter-campuses.geojson").read_text(encoding="utf-8"))
    errors, metrics = validate(document, schools, campuses, boundaries)
    hub_ids = json.loads((ROSTERS / "data-hub-ids.json").read_text(encoding="utf-8"))
    source_errors = source_checks(schools, campuses, audit, pages, hub_ids)
    roster = read_csv("nyc-open-charter-schools.csv")
    if len(roster) != 286 or {row["BEDS Code"] for row in roster} != {row["beds"] for row in schools}:
        source_errors.append("The school crosswalk differs from the original 286-school roster")
    if any(row["Status"] != "Open with Enrolled Students" for row in roster):
        source_errors.append("The original roster contains a school outside the operating scope")
    mutations = mutation_checks(document, schools, campuses, boundaries, errors)
    unresolved = [row for row in audit if row["decision"] == "unresolved"]
    if document.get("unresolved_source_records") != len(unresolved):
        source_errors.append("The map coverage note differs from the reconciliation log")
    internal_errors = [
        error for error in errors if not error.startswith("Missing campus ")
    ] + source_errors
    release_ok = not errors and not source_errors and not unresolved and all(mutations.values())
    print(json.dumps({
        "complete_release_gate": "PASS" if release_ok else "FAIL",
        "counts": metrics,
        "map_errors": errors,
        "source_errors": source_errors,
        "unresolved_source_records": len(unresolved),
        "mutation_checks": mutations,
    }, indent=2, sort_keys=True))
    return int(not release_ok if not args.report else bool(internal_errors) or not all(mutations.values()))


if __name__ == "__main__":
    raise SystemExit(main())
