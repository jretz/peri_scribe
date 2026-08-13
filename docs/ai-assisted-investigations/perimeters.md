# Understanding Perimeters in GeoPackages

## Prompt 1

In this session, I do not want you to modify any files. Reading is fine. There are 4 GeoPackages in the root of the project (ignore the ones in subdirectories). Identify the largest 25 fires across those files.

### Method

- **Files**: the 4 root GeoPackages only (`2026-08-09.gpkg` … `2026-08-12.gpkg`); the copies under `perimeters/` were ignored as instructed.
- **Layers used**: the two perimeter layers — `CA_Perimeters_NIFC_FIRIS_public_view_0` (fire name = `incident_name`) and `WFIGS_Interagency_Perimeters_Current_0` (fire name = `poly_IncidentName`). The `WFIGS_Incident_Locations_Current_0` layer is points, so it has no perimeter area and was excluded.
- **Area**: each perimeter was reprojected from its native CRS (EPSG:4269 / 4326) to the global equal-area EPSG:6933 and area computed from the geometry (1 acre = 4046.856 m²). Computed values agree with the sources' own GIS-acre columns (e.g., Big Grass: 579,361.15 vs `poly_GISAcres` 579,361.04), so ranking is robust.
- **Merging**: a fire = incident name, case-insensitive (the CA layer uses e.g. `BUG`, WFIGS `Bug` — I confirmed the 13 overlaps are the same fires by comparing areas). Perimeters with the same name in a snapshot were unioned; each fire's size is its **largest area observed across any of the 4 files and either layer**. 353 named fires total, 0 geometry errors.

### Largest 25 fires

1. **Big Grass** — 579,361 ac (largest in 2026-08-12, WFIGS)
2. **Crosswhite** — 354,687 ac (2026-08-12, WFIGS)
3. **Coleman Creek** — 308,721 ac (2026-08-11, WFIGS)
4. **Tartar** — 158,028 ac (2026-08-10, WFIGS)
5. **Sinlahekin** — 153,076 ac (2026-08-12, WFIGS)
6. **Kaiser Canyon** — 138,272 ac (2026-08-12, WFIGS)
7. **Widemouth 2** — 129,574 ac (2026-08-12, WFIGS)
8. **Little Giant** — 127,429 ac (2026-08-12, WFIGS)
9. **Babylon** — 107,189 ac (2026-08-09, WFIGS)
10. **Second Flat** — 105,501 ac (2026-08-09, WFIGS)
11. **Aspen Acres** — 102,003 ac (2026-08-10, WFIGS)
12. **Cottonwood** — 98,186 ac (2026-08-09, WFIGS)
13. **Grasshopper** — 83,640 ac (2026-08-12, WFIGS)
14. **0449 PORCUPINE RIDGE** — 79,225 ac (2026-08-09, WFIGS)
15. **FOX** — 79,000 ac (2026-08-09, WFIGS)
16. **Bald Mountain** — 76,443 ac (2026-08-09, WFIGS)
17. **Shingle** — 73,020 ac (2026-08-09, WFIGS)
18. **Bug** — 70,758 ac (2026-08-12, WFIGS; CA layer had 57,366 — merged, max used)
19. **Biscar** — 69,354 ac (2026-08-09, CA layer)
20. **Bench** — 67,074 ac (2026-08-09, WFIGS)
21. **Ferris** — 64,881 ac (2026-08-09, WFIGS)
22. **Modrite** — 57,788 ac (2026-08-10, WFIGS)
23. **Hagen** — 53,307 ac (2026-08-12, WFIGS)
24. **Wrights Spring** — 52,532 ac (2026-08-12, WFIGS)
25. **Mouse Meadow** — 51,408 ac (2026-08-12, WFIGS)

### Notes

- All but one of the top 25 come from the national WFIGS layer; **Biscar** (rank 19) is the only CA-layer-only fire in the list.
- "Largest" here means largest perimeter area observed across the 4 daily snapshots (fires grow/shrink between days); the file column shows where each fire's maximum was found. Every fire in the top 25 except Bald Mountain appears in all 4 files.
- No files were modified — everything was read in read-only mode via geopandas/pyogrio and sqlite3.

## Prompt 2

Okay, for those 25 fires, I want you to look through their geometry to figure out the relationship between all the records you find for a given fire. As you do that, build an understanding of why there are so many records and what is going on from day to day (i.e., GeoPackage file to GeoPackage file). As part of that, figure out the relationship between the CA and WFIGS layer (you might need to look at fires outside the top 25 for that). #18 Bug could help there, and similarly for any fires that cross California state borders. I'm eventually going to be building progression maps for each fire, and I need to know which data to pull from which layers, both for fires in California, and fires in other states.

### The two layers are fundamentally different products

**WFIGS `WFIGS_Interagency_Perimeters_Current` — the national "one current perimeter per fire" feed**
- ~213–222 rows, ≈ ~211–221 distinct fires → essentially one polygon per fire per snapshot.
- Every record is `poly_FeatureCategory = "Wildfire Daily Fire Perimeter"`, `poly_FeatureStatus = Approved`, `poly_Source = "2026 NIFS"`. The distinguishing fields are `poly_MapMethod` (Mixed Methods, IR Image Interpretation, GPS-Flight, Hand Sketch, etc.) and the timestamps.
- It is a **"current" view**: each daily file holds each fire's latest perimeter *as of that day*. Fires are updated in place or replaced day to day, and **drop out when no longer "current"** — e.g. Bald Mountain is present on 08-09 and 08-10 but gone by 08-12.

**CA `CA_Perimeters_NIFC_FIRIS_public_view` — California's append-only archive of individual heat perimeters**
- 295→315 rows but only ~102 distinct fires → many records per fire.
- Every record is `type = "Heat Perimeter"`, but `source` splits across **six** sources: `FIRIS` (176), `CAL FIRE INTEL FLIGHT DATA` (76), `NIFC` (21), `WFIGS` (15), `EGP` (14), `USFS` (13).
- Each record = one perimeter from one mapping mission at one point in time, with its own `poly_DateCurrent` timestamp and `area_acres`.

### Why there are so many records (and what changes day to day)

The decisive evidence is the GlobalID test across the 4 files:

- **CA layer is pure accumulation.** 08-09 has 295 GlobalIDs, 08-12 has 315 → **0 dropped, 20 added, 295 retained**, and **0 retained records changed area**. Records are frozen on creation and never edited or deleted. Each new flight/mission appends a new perimeter, so a long-lived fire accumulates a whole season of perimeters. BUG went from 3 records (08-09) to 7 (08-12) as new perimeters were added. The CA layer's `poly_DateCurrent` spans 2026-01-07 → 08-13, i.e. it retains the whole season to date.
- **WFIGS is replace/update, not accumulate.** Row count stays flat (~216→213). For a growing fire it keeps exactly one polygon that grows: Big Grass 541,079 → 553,972 → 575,343 → 579,361 ac across the four files. Some fires keep the same `SourceGlobalID` and get edited in place; others get a new `SourceGlobalID` each day. Either way, each file contributes exactly one "as-of" polygon per fire.

Concretely, for ELEPHANT the CA layer holds 6 perimeters over time: FIRIS 07-11 (2,157 ac), then CAL FIRE intel 07-15 (16,043), 07-16 (13,406), 07-17 (13,695), 07-18 (13,915), 07-19 (13,926). That is the fire's progression, encoded as separate records in a single file. WFIGS would give you only the *current* polygon.

### The CA ↔ WFIGS relationship

They are **mostly disjoint**, not two views of the same fires:

- Overlap is only **~13 fires** (of ~102 CA fires and ~211 WFIGS fires).
- WFIGS is **national** — the top-25 fires are in OR, WA, ID, UT, CO, NV (e.g. Big Grass OR, Crosswhite OR, Sinlahekin WA, Tartar ID, Aspen Acres CO, Mouse Meadow NV).
- The CA layer is **California's** system — 89 CA-only fires (e.g. **Biscar** is CA-only) plus a couple of border fires.
- The ~13 fires in both are CA fires that also exist in the federal system (Elephant, Rock, Bug, Timber, GANN, etc.). I confirmed 11 of 13 are the same fire by centroid distance (0–2 km).

The CA layer is also an **aggregator**: its `source` field shows it ingests perimeters from FIRIS, CAL FIRE intel flights, NIFC, WFIGS, USFS, and EGP. So for a California fire, the CA layer is the superset (multiple detailed perimeters), while WFIGS contributes the single national "official" perimeter.

### Cross-border fires (and a warning about name collisions)

- **Bug** is the textbook border case: `attr_POOState = US-CA`, county Lassen, `attr_POOCity = Hallelujah Junction`, but protecting unit = **NVCCD** (Nevada, Carson City District), GACC = GBCC. FIRIS mapped it under mission **`NV-CCD-BUG-N57B`**. Its CA-layer records come from FIRIS (3 early-morning heat perimeters) and EGP (4 growing perimeters: 11,405 → 16,680 → 55,888 → 57,366 ac), while WFIGS carries the single 70,758-ac national perimeter.
- The CA layer's mission unit prefixes are **CA, NV, OR**. Besides Bug, there's an **Oregon** fire (`OR-SWO-DET2-N905RT`, South-Western Oregon, mapped by FIRIS) with no `incident_name`.

**Name collisions are real and will bite you.** Two of the 13 "overlap" pairs are different fires that share a name:
- "Canyon": CA-layer `CANYON` (California, 2,000 ac) vs WFIGS "Canyon" in **Alaska** — centroids 4,000 km apart.
- "Johnson": CA-layer `JOHNSON` vs WFIGS "Johnson" in **New Mexico** — 787 km apart.

So bare fire name is **not** a reliable join key across layers (or even within WFIGS across states). Use **`poly_IRWINID`** (WFIGS) or **`incident_number`** (CA layer) as the stable fire identifier, and disambiguate by state/geometry when joining across layers. Also note WFIGS can hold **two identical polygons** under one name when it's a complex — Coleman Creek has two records with different IRWINIDs but byte-identical geometry; dedupe by geometry or IRWINID before mapping.

### What this means for your progression maps

- **Fires in California (and the CA/NV/OR border cases):** pull the **CA FIRIS layer**. Group by `incident_number` (or `incident_name` + state), order by `poly_DateCurrent`, and you get the fire's full high-frequency progression (multiple perimeters, often hours apart) — already present inside even a single file, and accumulating across files.
- **Fires in other states:** WFIGS is your only source. Progressions come from **stitching the daily files** — one current polygon per fire per file date. Track by `poly_IRWINID` across files.
- **Where they overlap (CA fires in both):** use the CA layer for the detailed within-season progression and WFIGS for the single authoritative "as-of" national perimeter; they're the same fire (centroids within ~2 km), so you can cross-check or layer them.
- **Timestamp caveats:** WFIGS `poly_DateCurrent` is often *forward-looking* (Big Grass's 08-09 file already says `dateCurrent = 08-10`); `poly_PolygonDateTime` is the actual mapping time (frequently NaT). The **file date is the reliable "as-of" date** for WFIGS. In the CA layer, `poly_DateCurrent` is the actual observation/mapping time and is generally populated.

## Prompt 3

- You say the "Overlap is only ~13 fires" between CA and WFIGS. Is there something common to those 13 fires that makes them the only ones that overlap?
- For fires that get a new SourceGlobalID each day, is there a reliable way to know they are the same fire?
- Give me a strategy for identifying unique fires across sources and days, regardless of name, SourceGlobalID, etc.

### Q1: What's common to the overlapping fires?

Short answer: **nothing intrinsic to the fires — the overlap is a time-dependent status, not a property.** Here's the evidence:

**The "13" is itself an artifact of name matching.** WFIGS actually contains **17 California fires** in the 08-12 snapshot, not 13:

- 11 match the CA layer by name (`3-1 Pit`, `Loomis`, `Elephant`, `CHUTE`, `Wagon`, `Rock`, `GANN`, `Ridge`, `MP18`, `Bug`, `Timber`).
- 3 more match **geometrically under different names**: WFIGS `5-4` = CA `CINDERCOMPLEX-5-4` (0.0 km), `5-3` = `CINDER COMPLEX` (0.0 km), `Feliz Incident` = `FELIZ` (0.0 km).
- 2 of the "13" are pure name **collisions**: CA `CANYON` vs WFIGS `Canyon` in **Alaska** (4,000 km apart), and CA `JOHNSON` vs WFIGS `Johnson` in **New Mexico** (787 km).
- 3 WFIGS CA fires (`FLAT`, `WOODS`, `Foster Fire`) have **no CA-layer record at all** (nearest CA fire 24–120 km away).

**What the true overlaps share, vs the 86 CA-only fires:**

- **They're the CA fires still "live" in the national system.** In the CA layer, overlap fires are 47% `Active` (27 of 57 records) vs 3% for CA-only fires (4 of 144, and those 4 — BUZZARD, HATCHET, HOLSER — are small). Overlap fires are also more recent (discovery Apr 18–Jul 25 vs Jan 6–Jul 18).
- The CA-only fires are almost entirely **Inactive** (97%) — the season's historical tail that FIRIS archives forever.
- It's **not** size (WFIGS has 0.01-acre fires; CA-only includes the 16,938-acre SANTA ROSA ISLAND), **not** landowner (private and federal both appear), and **not** protection unit (both CAL FIRE units like TCU/LAC and federal units like Tahoe NF, Plumas NF, BLM, BIA appear).

**The mechanism that makes it time-dependent:** the CA layer is append-only (0 records dropped across the 4 files) and ingested WFIGS/NIFC/USFS perimeters all season — 35 distinct federal incident numbers (e.g. `2026-CACDD-007101`) are archived in the CA layer, and **zero** of them still exist in WFIGS' current view. Fires leave WFIGS when their perimeter stops being updated (containment), while the CA layer keeps the ingested copy forever. So the overlap is the moving intersection of "CA fires FIRIS has mapped" and "fires whose perimeter is current in WFIGS today."

### Q2: Reliable way to know a fire with a new SourceGlobalID is the same fire

**Yes — `poly_IRWINID`.** Verified across all 4 files:

- 169 fires appear in all 4 files; **169/169 kept a constant IRWINID**, and all 220 multi-file IRWINIDs map to exactly one fire name across days.
- Crosswhite is the clean demonstration: `SourceGlobalID` changed **every day** ({25C035F → 9A84F94 → 8576C80 → 99CEB4A}), but `poly_IRWINID` = `{1B0219EE…}`, `OBJECTID` = 56241, and `attr_UniqueFireIdentifier` = `2026-ORPRD-000445` stayed constant all 4 days.
- `poly_IRWINID` equals `attr_IrwinID` on 213/213 rows (the same incident ID rides on both the polygon and incident-attribute sides).
- Bonus: `OBJECTID` was also constant 169/169 in this data (it's the ArcGIS feature slot), but it's view-internal and can be recycled, so treat it as corroboration only. `SourceGlobalID` is explicitly **not** reliable — it changed for 32/169 fires (19%).

Caveat: IRWINID is the *incident* key. Complexes can map one name to multiple IRWINIDs (Coleman Creek = two IRWINIDs with identical geometry), so treat IRWINID as the base unit and the incident name as a complex grouping on top.

### Q3: Strategy for identifying unique fires across sources and days

**1. Assign each system a golden key.**
- WFIGS: `poly_IRWINID` (= `attr_IrwinID`) — the national interagency incident ID, stable across days, polygon replacements, and even the two IRWINIDs of a complex.
- CA layer: `incident_number` (same `2026-UNIT-NNNNNN` format as WFIGS' `attr_UniqueFireIdentifier`) — but it's only populated on 39% of rows, so it can't be your sole CA key. `GlobalID` is a per-record ID (stable, append-only), never a fire ID.

**2. Same fire across days (within a system).**
- WFIGS: group by IRWINID across files. When `SourceGlobalID` changes, IRWINID (and empirically OBJECTID) still identify the fire.
- CA layer: records are append-only with stable GlobalIDs; group by normalized name (or incident_number where present) and you get the fire's full record series. Order by `poly_DateCurrent` for progression.

**3. Same fire across systems (CA ↔ WFIGS) — three-tier matching:**
- **ID crosswalk**: CA-layer rows with `source ∈ {WFIGS, NIFC}` carry the federal ID in `mission`/`incident_number`, which equals WFIGS `attr_UniqueFireIdentifier`. Today, zero of the archived IDs still match current WFIGS (those fires dropped out), but this is the exact bridge for any overlapping-window comparison.
- **Spatial fingerprint** (the workhorse): true CA↔WFIGS matches have centroids within 0–2 km (all 14 verified matches were ≤2 km; the 2 collisions were 787 and 4,000 km). Use centroid distance + perimeter-overlap ratio + name similarity.
- **Temporal consistency**: discovery date, and successive perimeters that overlap and grow — as a validation layer.

**4. Never trust names alone.** Proven collisions (Canyon, Johnson) and variants (`5-4`/`CINDERCOMPLEX-5-4`, `Feliz Incident`/`FELIZ`, `Biscar`/`BISCAR`, `3dash1` vs `3-1`). Always: normalize (casefold, strip, unify dashes/spaces), pair name with state, and confirm cross-system joins geometrically.

**5. Concrete pipeline for your progression maps:**
- Build a fire registry: `fire_id` = IRWINID (WFIGS) or synthetic CA fire key (normalized name+state, bridged to IRWINID via geometry) → attributes {name, state, protecting unit, discovery date}.
- Attach perimeters: WFIGS polygons → IRWINID → fire; CA records → incident_number-or-name → fire → geometry-match to IRWINID.
- Per fire, order perimeters by `poly_DateCurrent` (CA) or file-date/`poly_PolygonDateTime` (WFIGS); dedupe identical polygons (complex fires); flag non-monotonic area growth for review.
- Validate the registry with monotonic-growth checks and the 0–2 km centroid rule for any manual joins.

Nothing was modified — all findings are from read-only queries over the four root GeoPackages.

## Prompt 4

Revise the unique fire identification to handle both fires and complexes. Are perimeters for individual fires still included after they join a complex? If so, then the complex part can be as simple as indicating which fires are part of each complex as of a given moment in time.

### What the data shows

**Complexes have a clean, explicit structure in WFIGS** — on both the perimeter layer and (more completely) the incident-locations layer:

- **Complex = an incident with children.** The point layer holds 5 parent complexes (`IsCpxChild=0` with children): **ROWE CREEK COMPLEX** (373,540 ac reported, 11 children), **HAY CREEK COMPLEX** (200,292 ac, 8 children), **CINDER COMPLEX** (2,784 ac, 2 children), plus **COW CAMP COMPLEX** and **MMU AUGUST LIGHTNING COMPLEX** (children not in the current view). Each has its own IRWINID, which is exactly what the children's `attr_CpxID` points to.
- **Membership lives on the child record**: `attr_IsCpxChild=1` + `attr_CpxID` + `attr_CpxName`. 16 children have current perimeters; 21 children total (the point layer adds 5 small ones — REDROCK, TWICKENHAM, COVE CREEK, PAT'S CABIN, 0502 — that have incident records but no current perimeter). Perimeter-layer children ⊂ point-layer children, 0 mismatches.
- **Two of your top-25 are complex children**: Crosswhite (#2, ROWE CREEK) and 0449 PORCUPINE RIDGE (#14, HAY CREEK).

**Yes — individual fire perimeters keep flowing after the fire joins a complex.** Direct evidence: Crosswhite was a ROWE CREEK child on all 4 days *and* its own perimeter grew daily (348,987 → 352,689 → 354,309 → 354,687 ac, new perimeter each day). All 16 children carry their own current perimeters (dateCurrent 07-21 → 08-12) with their own IRWINIDs.

**The complex's own "perimeter" is not usable**: only HAY CREEK has one (record "Esau Canyon", 29 ac, stale since 07-23); ROWE CREEK and CINDER have no perimeter record at all. The real complex footprint at any moment = union of the member fires' perimeters — and the complex's reported `IncidentSize` attribute (point layer) is the official-size cross-check.

**Membership was static in the 4-day window** (all 16 perimeter-layer children held the same CpxID every day, no joins/leaves). The model should still record validity intervals, because membership does change over longer windows.

**Two data quirks to encode:** (1) name variants between WFIGS layers — "Crosswhite" (perimeter) vs "0445 CROSSWHITE" (points), "Cherry Creek" vs "0482 CHERRY CREEK"; always join layers by IRWINID. (2) **Coleman Creek's twin polygons are *not* a complex** — one IRWINID's `attr_IncidentName` is "Coleman Creek", the other's is "Bald Mountain", both carrying the identical 308,721-ac geometry. That's an incident alias/duplicate (a renamed incident leaving two records on one polygon), so geometry-dedupe separately from complex logic.

### Revised identification model

**Three entities + one relationship — your "simple membership table" idea is exactly right:**

1. **Incident registry** (the base unit, key = IRWINID): name (with observed aliases), state, protecting unit, discovery date. This is what perimeters attach to.
2. **Complex registry** (key = complex IRWINID): complex name, reported size. Built from point-layer parents; membership never needs geometry.
3. **Perimeter records** (keyed to incident IRWINID; CA-layer records keyed to incident_number/normalized name, crosswalked to IRWINID by geometry). Perimeters stay per-fire forever — **no geometric merging is required for identity**.
4. **Membership table**: `(fire_irwinid, complex_irwinid, valid_from, valid_to)` — exactly "which fires are part of each complex as of a given moment." Populate from `attr_CpxID`/`attr_IsCpxChild` (either layer); `valid_from` = first snapshot where observed, `valid_to` = last observed, open-ended until a later snapshot contradicts it.

**Consequences for your progression maps:**
- A **fire's** progression = that fire's own perimeters, regardless of complex membership (children keep their perimeters — verified).
- A **complex's** progression = union of member fires' perimeters per timestamp, cross-checked against the complex's reported `IncidentSize`; ignore the complex's own stale/tiny perimeter record when present.
- CA-layer fires have no complex columns, so complex membership is WFIGS-only; the CA↔WFIGS crosswalk (IRWINID/geometry) is unchanged.
- Dedupe identical polygons under different IRWINIDs (Bald Mountain/Coleman Creek) by geometry, and never trust names across layers (IRWINID only).

Nothing was modified — all conclusions are from read-only queries over the four root GeoPackages.

## Prompt 5

What happens with perimeters when two fires in a complex overlap (i.e., burn into each other)?

### Perimeters are never clipped or merged — overlap is published as-is

Each fire in a complex keeps its own full perimeter polygon, with its own IRWINID, its own `poly_GISAcres`, and its own update date, **even where members have burned together**. The data simply allows the polygons to overlap:

- HAY CREEK COMPLEX children overlap by **56,060 acres — 22% of the sum of their areas**. Specifically: `0449 PORCUPINE RIDGE` × `0456` overlap = 25,216 ac, × `0462` = 25,161 ac, `0456` × `0462` = 25,196 ac, plus `0480 WILCOX` overlapping PORCUPINE RIDGE by 5,646 ac.
- ROWE CREEK and CINDER children happen not to overlap (union = sum) — the overlap is per-fire-pair, not a universal rule.

### The complex's reported size is the *union*, not the sum

This is the cleanest evidence of how the systems treat burned-together area:

- **HAY CREEK**: sum of child areas 256,393 ac → union 200,333 ac → reported `IncidentSize` **200,292 ac** (matches the union to 0.02%; summing would overstate by 28%).
- **ROWE CREEK**: union of the 6 perimeter-bearing children = 373,250 ac vs reported 373,540 (the ~290-ac gap is the net contribution of the 5 small children that have no current perimeter — they've burned into the bigger members, and their origin points mostly fall inside the union).
- **CINDER**: union = sum = 2,709 ac vs reported 2,784.

So the correct "complex footprint" at any moment = **union of the members' perimeters**, and the reported size is the agency's own validation of that union.

### Two caveats that matter for your maps

**1. The union inside one file is a composite of different dates.** HAY CREEK's children in the 08-12 file carry `dateCurrent` of 07-21, 07-30, and 07-31 — the union is not a single-moment footprint. (In this 4-day window HAY CREEK's geometry was frozen — identical union every file — but in general you should align each member's perimeter to a common date from the daily progression before unioning.)

**2. The CA layer stores a *merged* complex perimeter explicitly in some cases.** For CINDER COMPLEX it has both the children (`CINDERCOMPLEX-5-4` 1,954 ac, `CINDERCOMPLEX-5-3` 768 ac) *and* a merged `CINDER COMPLEX` record (2,784 ac, 07-26, CAL FIRE INTEL FLIGHT DATA) — and 2,784 matches the WFIGS reported size exactly. But these merged records are sparse and inconsistently labeled (the FIRIS flights name complex perimeters with child missions like `CA-BDU-CinderComplex-5-4-N42Z`), so they're a cross-check, not the primary source.

### Rules for your progression maps

- **Per-fire maps**: use the fire's own perimeter as-is — overlaps with neighboring fires are real burned-together area; never clip or subtract them.
- **Per-complex maps**: union the members' perimeters at each aligned timestamp (never sum — HAY CREEK would be overstated by 56,000 ac), and validate against the complex's reported `IncidentSize`.
- **CA-layer complex maps**: same union rule, applied to the member fires (CINDERCOMPLEX-5-3/5-4, etc.); use the explicit merged `CINDER COMPLEX`-style records as a sanity check where present.

Nothing was modified — all results are from read-only queries over the four root GeoPackages.
