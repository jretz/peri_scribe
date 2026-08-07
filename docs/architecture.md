# Architecture

## Data Handling

- A local cache of the source data is maintained in the runtime environment. This copy of the data is close, or identical, to the data in the source. The local copy is synchronized with the source data at regular intervals, ensuring that the local copy remains up-to-date.
- Data synchronization is idempotent so that it can be restarted at any time without causing data corruption or duplication. The synchronization process is designed to handle failures gracefully, ensuring that the system can recover from interruptions without losing data integrity.
- The local cache is in sqlite format.
- KML files are generated from the local cache and stored separately. KML is used for output only.
