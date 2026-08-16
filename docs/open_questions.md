# Open Questions

## For Zeke

- The two perimeter sources (CA_Perimeters_NIFC_FIRIS_public_view and WFIGS_Interagency_Perimeters_Current) overlap. Some incidents (in California) are in one and some are in both. When they are in both, and the incident is wholly contained in California, then sometimes the perimeters are very similar, sometimes less so. When they cross state lines, the perimeters are often very different. Some questions:
  - If they have the same fire, do you want both sets of perimeters?
  - If not, does one take precedence over the other?
  - Would it be better to try to merge them, perhaps by taking the union of the two perimeters?
  - *Update* - One significant difference is that CA_Perimeters_NIFC_FIRIS_public_view appears to retain all updates for the season. WFIGS_Interagency_Perimeters_Current appears to only retain the most recent perimeter for each fire, and then only for fires that are still active (or maybe recently active).
- How long should a fire stay in the output KML?
  - Some number of days after the last perimeter change?
  - Until it disappears in the source data?
  - Until the data source marks it as not active?
- I've heard you mention "breaking the format" where polygons are not filled in.
  - I can debug that, but do you know any more about what's happening?
  - Is geometry simplification (e.g., strategically removing points from polygons in a way that doesn't change the shape "too much") acceptable if it helps fix this issue?
  - *UPDATE* - I might have a fix for this. It does require geometry simplification. There are a few problems that break Google Earth's filling of polygons that appear in current perimeters:
    - There are polygons inside the perimeters of several current fires where all points in the polygon (sometimes thousands of points) are all collinear, within the limits of numerical accuracy. These polygons have very close to zero area. These appear to be bad data that doesn't belong in the data set at all.
    - The actual perimeters of several fires will have a point on the perimeter, followed by a point inside the perimeter, followed by a point virtually on top of the first point. Some fires have dozens of these zero area slits.
    - Huge clusters of points nearly on top of each other... one polygon had more than 40K points within a 10m radius.
- I assume that the current day's perimeter will not always wholly contain the previous day's perimeter. There must be cases where perimeter mappings are corrected from one day to the next. Is that right?
  - Would it be desirable to "fix" this? That would mean removing parts of previous day perimeters that are no longer present in most recent perimeter.
- *Mostly moot because of the analysis below* - When is fire mapping "midnight"? In other words, is there a time of day when the last version of perimeters for the previous day are highly likely to be available in data sources, but no updates for the current day are likely to be available yet? This would be a good time to do a final run and "lock down" the archive of the previous day's perimeters. This is about both synchronizing data from sources, and distinguishing "today's" perimeter from "yesterday's" perimeter when symbolizing.
  - *Analysis* - This is about when updates become available in ArcGIS Hub, not when it's available for any given day. CA_Perimeters_NIFC_FIRIS_public_view updates appears to mostly become available in ArcGIS HUB in the midnight hour and within a couple hours of noon, with it much more heavily weight towards noon rather than midnight (this is during a relatively calm wildfire period, so not super reliable). Non-CA_Perimeters_NIFC_FIRIS_public_view updates are spread throughout the day. During this relatively active period, almost every hour of the day see's 5+ updates become available for each non-CA_Perimeters_NIFC_FIRIS_public_view source. The peak is around noon with 30-40 updates per hour for each source. For these non-CA_Perimeters_NIFC_FIRIS_public_view sources, perimeters see a few more updates per hour than points, but less than 1.5x as many.
  - *Conclusion* - Given that data gathering is becoming highly automated, and there would be a lot more flexibility in having a full archive of perimeter updates, it seems like the best approach is to gather updates throughout the day as they become available, and before they are overwritten / deleted (in the case of the non-CA_Perimeters_NIFC_FIRIS_public_view sources). There is an easy approach to checking if new data is available, and it doesn't trigger rate limits. When to distinguish "today's" perimeter from "yesterday's" perimeter is a separate question, and can probably be done by looking at the timestamp of the most recent update for each fire (perhaps together with when fire behavior tends to be most active).

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
