# Open Questions

## Requirements

- Are perimeters used in QGIS, for example to serve map tiles to CalTopo? Or can this be completely separate from QGIS, and the user needs to bring the output in on their own if they want to use it there?
- How long should a fire stay in the output KML? Some number of days after the last perimeter change? Until it disappears in the source data?
- Are any data sources used that require credentials?
- There has been mention of "breaking the format" where polygons are not filled in. Is there more known about that? Is geometry simplification (e.g., strategically removing points from polygons in a way that doesn't change the shape "too much") acceptable if it helps fix this issue?
- The data sources we've been looking at are only for "current" activity. Is there any desired to include past activity at this stage?
- Are all data sources expected to be used in the medium term likely to be in ArcGIS Hub?
  - If not, what other sources are possibilities?
- I assume that the current day's perimeter will not always wholly contain the previous day's perimeter. There must be cases where perimeter mappings are corrected from one day to the next. Is that right?
  - Would it be useful to "fix" this? That would mean removing parts of previous day perimeters that are no longer present in the next day's perimeter.

## Monitoring

- There can be tests that the KML contains a minimum number of features before outputting it. But something needs to check that there has been some update to the KML in the last N hours (N might vary from season to season).
- Should notifications go out when a data source is down or is it enough that KML output is not updated with new data from the unavailable source while still being updated from other sources? Should there be some indicator in the KML in this situation?

## Synchronizing Data From Sources

- Is there a quick check as to whether a data source has changed since the last synchronization? This would help avoid unnecessary data retrieval and processing. Is this lightweight enough to do often (e.g., every few minutes)?
  - It appears that at least some of the data sources have various timestamp fields.
    - Are they on everything?
    - Are they reliable?
- How is idempotency achieved in the data synchronization process?
  - It appears that at least some of the data sources have various timestamp fields to help with this.
  - Queries can possibly be done by timestamp range, and hopefully sorted by timestamp. This would enable a "high water mark" approach to synchronization - all data after the last data downloaded needs to be retrieved on the next run. Need to check that data doesn't appear in data source significantly after their created/updated timestamps.
    - A nuance to this... what if all data with a specific timestamp does not appear atomically? Do future retrievals need to go back earlier than the last timestamp retrieved to ensure there are no gaps?
