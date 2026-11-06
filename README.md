# NYC charter school campus map

**2026–27 school year · November 5, 2026 snapshot · Reconciled November 6, 2026**

[Open the map in GitHub](nyc-charter-campuses.geojson). Each pin marks an instructional location. Select a pin to see the borough, addresses, and campus details. A pin can represent more than one campus at a shared site.

The map includes all **286 operating NYC charter schools** in the October 20 NYSED roster. It shows **422 campus records across 387 pins**. All flagged records have a decision in the reconciliation log.

| Borough | Campus records | Pins |
| --- | ---: | ---: |
| Bronx | 146 | 134 |
| Brooklyn | 134 | 126 |
| Manhattan | 83 | 73 |
| Queens | 49 | 46 |
| Staten Island | 10 | 8 |

## Data and verification

- [Original school roster](nyc-open-charter-schools.csv) preserves the filtered [October 20 NYSED operating roster](https://www.nysed.gov/sites/default/files/programs/charter-schools/allchartersissued102026.pdf). [School crosswalk](schools.csv) links state BEDS codes to NYC Public Schools DBNs.
- [Campus crosswalk](campuses.csv) records addresses, dates, and sources for the mapped locations. Locations were checked against [NYC Public Schools location records](https://infohub.nyced.org/in-our-schools/operations/lcgms), the [NYC Charter School Finder](https://findnyccharterschools.org/), and school or authorizer pages. Coordinates use [NYC GeoSearch](https://geosearch.planninglabs.nyc/docs/) or the source cited in the crosswalk. Borough names use [NYC Planning boundaries](https://data.cityofnewyork.us/City-Government/Borough-Boundaries/gthc-hcne/data).
- [Reconciliation log](reconciliation.csv) records decisions and evidence. The campus count describes this snapshot.

Run these commands from the repository root with Python 3. No additional packages are required.

```sh
python3 build_map.py
python3 validate.py --report
```

The report checks school coverage, campus IDs, pin coordinates, boroughs, and source reconciliation. Run `python3 validate.py` for the strict release check. It returns a failure while any source records remain unresolved.
