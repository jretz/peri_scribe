# Open Questions

## Requirements

- Are perimeters used in QGIS, for example to serve map tiles to CalTopo? Or can this be completely separate from QGIS, and the user needs to bring the output in on their own if they want to use it their?
- How long should a fire stay in the output? Some number of days after the last perimeter change?
- Are any data sources used that require credentials?
- There has been mention of "breaking the format" where polygons are not filled in. Do we know more about that? Is geometry simplification desirable or not?
- The data sources we've been looking at are only for "current" activity. Is there any desired to include past activity at this stage?

## Monitoring

- How is output monitored? There can be tests that data is of at least a certain size before writing it. But something needs to monitor that there has been some update to the KML in the last N hours (N might be season dependent).
- Should notification go out when a data source is down?

## Synchronizing Data From Sources

- Is there a quick check as to whether a data source has changed since the last synchronization? This would help avoid unnecessary data retrieval and processing. Is this lightweight enough to do often (e.g., every few minutes)?
- How is idempotency achieved in the data synchronization process?
  - It appears that at least some of the data sources have various date fields to help with this.
  - Queries can be done by date range, and hopefully sorted by date. This would enable a "high water mark" approach to synchronization, where the all data from the newest seen needs to be retrieved on the next run.
