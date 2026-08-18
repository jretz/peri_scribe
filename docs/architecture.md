# Architecture

## Form

peri_scribe is a command line tool. It accepts the commands `fetch`, `current-watermarks`, and `list-fires`.

`fetch` retrieves data from the configured sources, one source at a time. Each source's data is written to its own GeoPackage snapshot, named by serial number and the observed watermark, under `data/<year>/sources/<feed name>/`. A source with no prior snapshots is fetched in full; a source that already has snapshots is fetched incrementally, and existing snapshots are never modified. When the current watermark already matches an existing snapshot, that source is skipped.

`symbolize` (PLANNED) will read GeoPackage files for the most recent days, along with a template KML file, and generate a KML file with the styles from the template applied to the geography data from the GeoPackage files.

`report` (FUTURE IDEA) will read GeoPackage files for the most recent days and generate a report about fires. Examples might include:
    - The top 10 active fires by area
    - The fastest growing fires
      - By absolute area growth
      - By percentage growth for fires over a certain area threshold
    - Fires that have exceeded a certain area threshold for the first time

## Data Handling

- The data from each source is kept as close to the format of the sources as is practical. This includes all attributes, geometry, and coordinate reference systems. This reduces the possible number of bugs that could result in data loss in the system (e.g., in CRS transformations). As long as this data is safe, any downstream consumers (e.g., KML generation or reporting) can be re-run after fixing problems there.
- Libraries used for data handling include:
  - [arcgis](https://pypi.org/project/arcgis/) from ESRI is used to retrieve data from ArcGIS Hub.
  - [GeoPandas](https://pypi.org/project/geopandas/) is used to handle data in memory, and to write it to disk as GeoPackage files.
  - [pyproj](https://pypi.org/project/pyproj/) is used to handle coordinate reference system analysis.

## Data Validation

Some feeds provide conflicting information about what coordinate reference system is used for their data. The system does its best to detect the correct coordinate reference system from one of those indicated by the feed (e.g., by checking the scale of the coordinates to determine meters vs. degrees).

## Code Structure

`main.py` contains all the logic to implement the CLI, and nothing else. All application logic is dispatched to other modules.
