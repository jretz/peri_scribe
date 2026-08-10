# Open Questions

## For Zeke

- The two perimeter sources (CA_Perimeters_NIFC_FIRIS_public_view and WFIGS_Interagency_Perimeters_Current) overlap. Some incidents (in California) are in one and some are in both. When they are in both, and the incident is wholly contained in California, then sometimes the perimeters are very similar, sometimes less so. When they cross state lines, the perimeters are often very different. Some questions:
  - If they have the same fire, do you want both sets of perimeters?
  - If not, does one take precedence over the other?
  - Would it be better to try to merge them, perhaps by taking the union of the two perimeters?
- How long should a fire stay in the output KML? Some number of days after the last perimeter change? Until it disappears in the source data? Until the data source marks it as not active?
- There has been mention of "breaking the format" where polygons are not filled in. Is there more known about that? Is geometry simplification (e.g., strategically removing points from polygons in a way that doesn't change the shape "too much") acceptable if it helps fix this issue?
- I assume that the current day's perimeter will not always wholly contain the previous day's perimeter. There must be cases where perimeter mappings are corrected from one day to the next. Is that right?
  - Would it be desirable to "fix" this? That would mean removing parts of previous day perimeters that are no longer present in the next day's perimeter.
- When is fire mapping "midnight"? In other words, is there a time of day when the last version of perimeters for the previous day are highly likely to be available in data sources, but no updates for the current day are likely to be available yet? This would be a good time to do a final run and "lock down" the archive of the previous day's perimeters. This is about both synchronizing data from sources, and distinguishing "today's" perimeter from "yesterday's" perimeter when symbolizing.

## Monitoring

- There can be tests that the KML contains a minimum number of features before outputting it. But something needs to check that there has been some update to the KML in the last N hours (N might vary from season to season).
- Should notifications go out when a data source is down or is it enough that KML output is not updated with new data from the unavailable source while still being updated from other sources? Should there be some indicator in the KML in this situation?

## Synchronizing Data From Sources

- Is there a quick check as to whether a data source has changed since the last synchronization? This would help avoid unnecessary data retrieval and processing. Is this lightweight enough to do often (e.g., every few minutes)?
  - It appears that at least some of the data sources have various timestamp fields.
    - Are they on everything?
    - Are they reliable?
- How is idempotency achieved in the data synchronization process?
  - This might be easier than first thought... this is not a ton of data. During fire season, there only appears to be O(20 MB) of data. So just pull the entire thing each time. There are rate limits that get hit if retrying too quickly, so there needs to be some kind of throttling.
