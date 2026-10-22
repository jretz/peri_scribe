# Document-local boundary spill

`BoundarySpill.tla` covers `kml_io.fragments.BoundarySpool.put/get` and the resource
lifetime of `BoundaryCache.spill`, used by `KmlWriter.document`. Only writes completed
within the active scope can become readable entries. An append reserves its encoded
range before I/O; failed or short writes leave no index entry and disable later appends.
Read authentication rejects corrupt bytes. The single-owner scope has no concurrent
reader observing an incomplete write and no persistent recovery path.

The finite configuration uses three keys with encoded lengths two/two/five, a four-byte
budget, both entry limits one/two and every operation prefix through length five. The
18,240 checked prefixes include opening, successful/failed insertion, capacity misses,
reads, corruption and closure. Invariants establish count/byte limits, fresh-entry
provenance, exact hit selection and empty released ownership. No liveness claim is made;
the caller must exit its document context.

`test_boundary_spill.py` replays each complete checked prefix against actual temporary
files and the production API, then compares the entire modeled observation. Logical
payloads have independent exact byte values, and write failures and corruption are
injected at the stream boundary. File closure is observed directly. Private framing is
abstracted by exact encoded lengths; the shared payload-codec proof and conformance
cover compression and ordinary tests cover larger compressed boundary values.

The model assumes stable exact keys, collision-free logical checksums, one owner and
standard Python context unwinding. It does not establish filesystem power-loss behavior,
arbitrary process-termination cleanup, total RSS bounds or independent output publication.
Corrupt/spill misses fall back to the existing renderer; forced persistent-cache reads
remain misses. The staged KMZ writer retains its existing publication contract.
