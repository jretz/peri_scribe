# Architecture

## Form

peri_scribe is a command line tool with commands for retrieving data from sources, cleaning and organizing that data, and generating maps. All of that is in place and maturing. At least one additional command is planned:

`report` will read GeoPackage files for the most recent days and generate a report about fires. Examples might include:
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

## Data Validation and Cleansing

Some feeds provide conflicting information about what coordinate reference system is used for their data. The system does its best to detect the correct coordinate reference system from one of those indicated by the feed (e.g., by checking the scale of the coordinates to determine meters vs. degrees).

Many kinds of issues with fire perimeter polygons are detected and corrected in a copy of the data (the original download cache is append-only and is never modified). These include:

- Small perimeters (e.g., 2 acres) published as new perimeter mappings of large fires (e.g., 100,000 acres). These are ignored.
- A series of thousands of collinear points. These excess points are removed.
- Thousands of points in a very small area (one case had 40K points within 10 meters of each other) . These are reduced to a small number of points.

## Code Structure

`main.py` contains all the logic to implement the CLI, and nothing else. All application logic is dispatched to other modules.
