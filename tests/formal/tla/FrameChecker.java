import java.io.BufferedOutputStream;
import java.io.BufferedWriter;
import java.io.DataOutputStream;
import java.io.File;
import java.io.IOException;
import java.io.InputStream;
import java.io.OutputStream;
import java.net.URISyntaxException;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.LinkOption;
import java.nio.file.Path;
import java.nio.file.StandardCopyOption;
import java.security.DigestInputStream;
import java.security.MessageDigest;
import java.security.NoSuchAlgorithmException;
import java.util.ArrayList;
import java.util.Arrays;
import java.util.Base64;
import java.util.Collections;
import java.util.HashMap;
import java.util.HashSet;
import java.util.HexFormat;
import java.util.IdentityHashMap;
import java.util.LinkedHashSet;
import java.util.List;
import java.util.Map;
import java.util.Set;
import java.util.jar.JarFile;
import tla2sany.semantic.ASTConstants;
import tla2sany.semantic.LetInNode;
import tla2sany.semantic.LevelNode;
import tla2sany.semantic.OpApplNode;
import tla2sany.semantic.OpDefNode;
import tla2sany.semantic.SemanticNode;
import tla2sany.semantic.SubstInNode;
import tla2sany.semantic.SymbolNode;
import tlc2.output.EC;
import tlc2.tool.Action;
import tlc2.tool.TLCState;
import tlc2.tool.impl.FastTool;
import tlc2.util.Context;
import tlc2.util.FP64;
import tlc2.value.IValue;
import tlc2.value.Values;
import tlc2.value.impl.BoolValue;
import tlc2.value.impl.StringValue;
import tlc2.value.impl.IntValue;
import tlc2.value.impl.IntervalValue;
import util.FilenameToStream;
import util.SimpleFilenameToStream;
import util.UniqueString;

/** Checks reviewed finite models with TLC evaluations and shared immutable state fields. */
public final class FrameChecker {
    private static final int FIELDS_PER_WORD = 4;
    private static final int BITS_PER_FIELD = 16;
    private static final int FIELD_MASK = (1 << BITS_PER_FIELD) - 1;
    private static final int MAX_FIELDS = 5 * FIELDS_PER_WORD;
    private static final int MAX_SOURCE_BYTES = 64 * 1024;
    private static final int ITEMS = 3;
    private static final String TLC_SHA256 =
            "936a262061c914694dfd669a543be24573c45d5aa0ff20a8b96b23d01e050e88";
    private static final Set<String> STANDARD_MODULES = Set.of(
            "Naturals.tla", "Integers.tla", "Sequences.tla", "FiniteSets.tla", "TLC.tla");

    private record Model(
            Map<String, String> sources, String spec, List<String> properties,
            String eventuality, List<String> actions, int actionsPerItem,
            int generated, int states, int initials) {}

    // The source pins qualify the action analysis and the set of pure TLC operators.
    private static final Map<String, Model> MODELS = Map.of(
            "PipelineComposition", new Model(Map.of(
                    "PipelineComposition.tla",
                    "1766b1b756dfdcaee00842eeec691aa42edb67a6c37ff150b98668605e979cff",
                    "PipelineComposition.cfg",
                    "13fede2e77462185ffc39830b0444ce67e31dd9bf2b0c30bb47f2d03e250af0c",
                    "PipelineState.tla",
                    "c428444fdce082f8610c3c69d336fcd8cb9ad2f2895d2d3038b933929ec7193a"),
                    "Spec", List.of("RankDecreases"), null,
                    List.of("Progress", "StartFetch", "ConsumeDeferred", "Fetch",
                            "FinishFetch", "Execute", "Commit", "Invalidate",
                            "Acknowledge", "NextInvocation", "Crash"),
                    0, 195_612, 113_677, 1),
            "JournalReplay", new Model(Map.of(
                    "JournalReplay.tla",
                    "8d234cc446eb276cc548b60288f7230e0f465adc0d21e997284d5dc79250e4a8",
                    "JournalReplay.cfg",
                    "02a805c5a4a7ce0dd2fa4b926440abf7b4e082acba6a4d4a2c79a11982548341",
                    "UpdateJournal.tla",
                    "73d2a95894ae06dd595426666accf676802b5fecabca7176ea8ea13834e7d640"),
                    "ReplaySpec", List.of("BaseRankDecreases"), null,
                    List.of("Explore", "BeginRecovery", "Recover"),
                    0, 110_132, 78_940, 64),
            "FeedCoordinator", new Model(Map.of(
                    "FeedCoordinator.tla",
                    "00248b3a3a0e423303dc6f4ec741e1767fed5989181d33b212515ab0a59d8543",
                    "FeedCoordinator.cfg",
                    "04ae95ca91a0d448b00972641dc24aba5286785a7cc57bbd71b12698f4b44f70"),
                    "Spec", List.of("RankDecreases"), null,
                    List.of("Mark", "Cancel", "Join", "Index", "Ack", "Restore",
                            "Crash", "Start", "Finish", "Start", "Finish", "Start",
                            "Finish"),
                    2, 250_632, 197_898, 2_000),
            "OrderedWorkers", new Model(Map.of(
                    "OrderedWorkers.tla",
                    "070985ecb4f537b2d0d17cf4e305362afa788aa3f34c5e27c0e320d24170b66e",
                    "OrderedWorkers.cfg",
                    "7e70924ecc17a34ff7e581be5d40b7c4f9a3a1348396cc6254b5c562f79d1b2b"),
                    "LiveSpec", List.of("NoAdmissionAfterFailure", "NoDeliveryAfterClosing"),
                    "EventuallyReleased",
                    List.of("Admit", "Deliver", "Raise", "Complete", "Cancel", "Release",
                            "Publish", "Start", "Finish", "Observe", "CancelQueued",
                            "Start", "Finish", "Observe", "CancelQueued",
                            "Start", "Finish", "Observe", "CancelQueued"),
                    4, 29_714, 19_362, 216),
            "FetchCrash", new Model(Map.of(
                    "FetchCrash.tla",
                    "b0d795ad0f965cc8696fccb4201189d152a31a3b66b6005bc089497172cdf770",
                    "FetchCrash.cfg",
                    "04422baf6a933b420597ca729f9104fe8c52eaf50124054775e409e6a15873d5",
                    "PipelineState.tla",
                    "c428444fdce082f8610c3c69d336fcd8cb9ad2f2895d2d3038b933929ec7193a"),
                    "LiveSpec", List.of(), "EventualCompletion",
                    List.of("Capture", "Mark", "FullMarker", "FetchFire", "FetchEvacuations",
                            "FinishFetch", "Retry", "Derive", "Crash"),
                    0, 19_270, 13_594, 512));

    private static final Map<String, Model> RANKED_COHORT = Map.of(
            "BuildingsConstruction", new Model(Map.of(
                    "BuildingsConstruction.tla", "15c97e2dce86048d9723447030502eb2b071b045c185c731ff1141e7c0ab1820",
                    "BuildingsConstruction.cfg", "4c7c9891b339f518556be88301bafd523b586f5909a84e91371ae675c3dc29f4"),
                    "LiveSpec", List.of(), "EventuallyFinished", List.of("Start", "BeginAppend", "FinishAppend", "FinishWorker", "ArchiveFailure", "CancelWaiting", "Start", "BeginAppend", "FinishAppend", "FinishWorker", "ArchiveFailure", "CancelWaiting", "Start", "BeginAppend", "FinishAppend", "FinishWorker", "ArchiveFailure", "CancelWaiting", "NoticeFailure", "Cancel", "Collected", "Aborted", "Build", "Validate", "Publish", "Cleanup"),
                    6, 12918, 6588, 54),
            "MonitorBackwardContextLiveness", new Model(Map.of(
                    "MonitorBackwardContext.tla", "2f8206b42e8f32976736941dc5ec974f7b24e5c5cc5f82d3896e442e5f381c9d",
                    "MonitorBackwardContextLiveness.cfg", "2972ebe68b63fc55b28c3be16b448c3e7295e52edab65cdcc0dd5f98761e40da"),
                    "FairSpec", List.of(), "ContextComplete", List.of("Scan", "Finish"),
                    0, 13771, 13460, 2884),
            "SnapshotCollectionLiveness", new Model(Map.of(
                    "SnapshotCollection.tla", "f5f99fd8c63a5040208598d093c055a629859c06b071520fb3fcd89e993dad5b",
                    "SnapshotCollectionLiveness.cfg", "9b851e0e4942af6e81f243a613532cd9e354cb23a2d6c27fc69d69efc584e841"),
                    "LiveSpec", List.of(), "EventuallyComplete", List.of("Settle", "Mutate", "Metadata", "ChangedIDs", "AllIDs", "Body", "Persist", "Recover"),
                    0, 7626, 3732, 24),
            "GeographyPublicationLiveness", new Model(Map.of(
                    "GeographyPublication.tla", "e562c9201a2a766f108365f3b95f9e973bbf9741fc6643db7b05d57e603519c4",
                    "GeographyPublicationLiveness.cfg", "09ce9bb55f8b068231a16f2c655b0bdd3b24145391ebbe6745021422842d8a17"),
                    "FairSpec", List.of(), "EventuallyPublished", List.of("CheckFull", "WriteFullBytes", "WriteFullMetadata", "CheckDifferential", "WriteDifferentialBytes", "WriteDifferentialMetadata", "Acknowledge", "NewGeneration", "Crash"),
                    0, 7619, 4286, 512));

    private record SafetyProfile(String module, Export export, Model model) {}

    private static final Map<String, SafetyProfile> SAFETY = Map.ofEntries(
            Map.entry("BoundarySpill", new SafetyProfile(
                    "BoundarySpill", Export.STATES, new Model(Map.of(
                            "BoundarySpill.tla",
                            "8b9bf1236bbeb07a3c749926421a2db7be015807973fa8998bb2047562d5b473",
                            "BoundarySpill.cfg",
                            "d7e2dd9fb43312e3c08a3735b754c0290df59d8cf3557d35ad6cdebaaf59b54f"),
                            "Spec", List.of(), null,
                            List.of(
                                "Next"),
                            -1, 18240, 18240, 2))),
            Map.entry("CacheRead", new SafetyProfile(
                    "CacheRead", Export.STATES, new Model(Map.of(
                            "CacheDefinitions.tla",
                            "08dbd7f4aed3521e857e68ef62277750727b2e9e8673dca0bab003362f5d9ab9",
                            "CacheRead.tla",
                            "6acdbeb9d04408f6cbc2e86c218c7a14a20cc161090d11563b0c6f068f184c28",
                            "CacheRead.cfg",
                            "897d0df1ad4c7f35c6d8cd8c9b2b67cc6e73285ff3e0c91ef34277e1db141f27"),
                            "Spec", List.of(), null,
                            List.of(
                                "Next"),
                            -1, 12288, 12288, 12288))),
            Map.entry("FeedCache", new SafetyProfile(
                    "FeedCache", Export.STATES, new Model(Map.of(
                            "FeedCache.tla",
                            "ce73ecc2d1b729455461d8433b29aa6206ade3a5ef7a2d6e7d23888d97480d29",
                            "FeedCache.cfg",
                            "7dc82cd478740edb605de1393bc2bbb4791218ec6b2f7e17f44e1999b4798d80"),
                            "Spec", List.of(), null,
                            List.of(
                                "Prepare", "Publish", "FailWrite"),
                            -1, 7680, 4800, 1536))),
            Map.entry("GeographyPublication", new SafetyProfile(
                    "GeographyPublication", Export.GRAPH, new Model(Map.of(
                            "GeographyPublication.tla",
                            "e562c9201a2a766f108365f3b95f9e973bbf9741fc6643db7b05d57e603519c4",
                            "GeographyPublication.cfg",
                            "20b6f22795f6617096fcdd6a69a7a79bbd18164948d1a532b28e25d4d1b21727"),
                            "Spec", List.of(), null,
                            List.of(
                                "CheckFull", "WriteFullBytes", "WriteFullMetadata",
                                "CheckDifferential", "WriteDifferentialBytes",
                                "WriteDifferentialMetadata", "Acknowledge", "NewGeneration",
                                "Crash"),
                            -1, 7619, 4286, 512))),
            Map.entry("GeographyReaders", new SafetyProfile(
                    "GeographyReaders", Export.GRAPH, new Model(Map.of(
                            "GeographyReaders.tla",
                            "b556506180dbe60891f621cb542944dff572c0bdce71bb75205e6c15c49b5921",
                            "GeographyReaders.cfg",
                            "f1e072e3c94a71c4cf08716c10f39f868147a97246fd2b474d128910770fb89b"),
                            "Spec", List.of(), null,
                            List.of(
                                "AcquireWriter", "WriteFull", "SignFull", "WriteDifferential",
                                "SignDifferential", "ReleaseWriter", "AcquireReader",
                                "Authenticate", "Read", "Return"),
                            -1, 2482, 1838, 162))),
            Map.entry("GroupingForest", new SafetyProfile(
                    "GroupingForest", Export.GRAPH, new Model(Map.of(
                            "GroupingForest.tla",
                            "c9d5bbb555960cffe40c7c99cf3b00e80472de203d88c6d5c954f14000b49b1a",
                            "GroupingForest.cfg",
                            "9431dc882b895d1b00be06fba3c972cd0ee7a5cbbfe0efa52cb075822b7500b2"),
                            "Spec", List.of(), null,
                            List.of(
                                "Seed", "Admit", "Discover", "Finish"),
                            -1, 5176, 4314, 64))),
            Map.entry("MonitorBackwardContext", new SafetyProfile(
                    "MonitorBackwardContext", Export.STATES, new Model(Map.of(
                            "MonitorBackwardContext.tla",
                            "2f8206b42e8f32976736941dc5ec974f7b24e5c5cc5f82d3896e442e5f381c9d",
                            "MonitorBackwardContext.cfg",
                            "1c00fc8b7d9cea81ceb7af764c48134074f8ac2bdecad12bf156c21fb90180e8"),
                            "Spec", List.of(), null,
                            List.of(
                                "Scan", "Finish"),
                            -1, 13771, 13460, 2884))),
            Map.entry("MonitorProjection", new SafetyProfile(
                    "MonitorProjection", Export.STATES, new Model(Map.of(
                            "MonitorProjection.tla",
                            "fc674121f5519de03a85cba5cd135231939c68f97b1226bd2cc130c787fd6f3c",
                            "MonitorProjection.cfg",
                            "58d13af91e96cdd3395129d99c83464c13351fa16451ad8e6e2f7987bfdf660a"),
                            "Spec", List.of(), null,
                            List.of(
                                "AppendEvent", "AppendEvent", "AppendEvent", "AppendEvent",
                                "AppendEvent", "AppendEvent", "AppendEvent", "AppendEvent",
                                "Observe", "Refresh"),
                            -1, 32193, 32193, 147))),
            Map.entry("MonitorReader", new SafetyProfile(
                    "MonitorReader", Export.STATES, new Model(Map.of(
                            "MonitorReader.tla",
                            "3c972dff15e0b55524518c10e4f55d590bb385ca37e8442555389070e349e67b",
                            "MonitorReader.cfg",
                            "082372a243db6d0c7c3120c7664d1e5d5cf86cf2c764ab65b2e226454c2d3507"),
                            "Spec", List.of(), null,
                            List.of(
                                "Write", "StartPartial", "FinishPartial", "Poll", "Rotate",
                                "Truncate"),
                            -1, 4299, 4299, 1))),
            Map.entry("MonitorSession", new SafetyProfile(
                    "MonitorSession", Export.GRAPH, new Model(Map.of(
                            "MonitorSession.tla",
                            "7f7fe8c0abdec45655982518a8a288602f4b2430d77a9d8d3ace72bc93189704",
                            "MonitorSession.cfg",
                            "1329043623b52f86d79495fc3b901c0145c2b18faf681941dccd2da4265e80f7"),
                            "Spec", List.of(
                                "MonotonicDelivery", "NoLatePublication"), null,
                            List.of(
                                "Submit", "Admit", "Cancel", "Promote", "Submit", "Admit",
                                "Cancel", "Promote", "Submit", "Admit", "Cancel", "Promote",
                                "Complete", "Fail", "Stop", "Close", "Subscribe", "Receive",
                                "Disconnect", "Subscribe", "Receive", "Disconnect"),
                            -1, 103060, 19166, 1))),
            Map.entry("MonitorTasks", new SafetyProfile(
                    "MonitorTasks", Export.GRAPH, new Model(Map.of(
                            "MonitorTasks.tla",
                            "dcf77876b8d511f5af5de0eb5f77cb27d16ee30cc7e93c270d92f56e86cd44c0",
                            "MonitorTasks.cfg",
                            "87fd5581297e852a1d401011391e610ae0953028ccf936e673f5429c8029367b"),
                            "Spec", List.of(
                                "NoPublicationAfterStop", "EvidencePreserved"), null,
                            List.of(
                                "Admit", "Cancel", "Admit", "Cancel", "Admit", "Cancel",
                                "ReleaseWriter", "StartRead", "FinishRead", "Settle",
                                "FailRead", "Retire", "Stop", "Close"),
                            -1, 27031, 12828, 2))),
            Map.entry("NormalizedCache", new SafetyProfile(
                    "NormalizedCache", Export.STATES, new Model(Map.of(
                            "NormalizedCache.tla",
                            "c9abfe5f0c336db2f1591c66ef8a2f305cf611103ee85f0cf66fe506bff330ff",
                            "NormalizedCache.cfg",
                            "dfb995a0011e032bc8cdb7264018d6e29bdee69815915b68d5bd2b0948cbf80e"),
                            "Spec", List.of(), null,
                            List.of(
                                "Begin", "WriteRow", "Collect", "Publish", "Abort", "Restart",
                                "Read"),
                            -1, 1554, 654, 36))),
            Map.entry("ParallelSourceAuthentication", new SafetyProfile(
                    "ParallelSourceAuthentication", Export.GRAPH, new Model(Map.of(
                            "ParallelSourceAuthentication.tla",
                            "1d66d287dcde53e2342507ea5833f6fba60224884a7e6a2fd80e8359b8f43c04",
                            "ParallelSourceAuthentication.cfg",
                            "e9d7fadd47da22379b838bc399a75e571168c996e197301d601e8e043aa79097"),
                            "Spec", List.of(), null,
                            List.of(
                                "Read", "Fail", "Stop", "Edit", "Read", "Fail", "Stop", "Edit",
                                "Cancel", "Expire", "Fork", "Join", "Resolve", "Cleanup"),
                            -1, 3405, 1372, 1))),
            Map.entry("ParsedCacheCompaction", new SafetyProfile(
                    "ParsedCacheCompaction", Export.GRAPH, new Model(Map.of(
                            "ParsedCacheCompaction.tla",
                            "7fa8da734ba844fc3abf17930ce51d8573e9eb50b361e27c7f2513274758da5d",
                            "ParsedCacheCompaction.cfg",
                            "cc9abc5c3225eb97e906ac79891cd272474d4225254e96a960be843d4cfd0b61"),
                            "Spec", List.of(), null,
                            List.of(
                                "Copy", "Validate", "Close", "Publish", "Fail", "Observe"),
                            -1, 3474, 1542, 6))),
            Map.entry("RunScheduler", new SafetyProfile(
                    "RunScheduler", Export.COUNTS, new Model(Map.of(
                            "PipelineState.tla",
                            "c428444fdce082f8610c3c69d336fcd8cb9ad2f2895d2d3038b933929ec7193a",
                            "RunScheduler.tla",
                            "6b142584fb9d024b4591f759f217d9ba07c971bc276fcf98c16fe1aafccf09c8",
                            "RunScheduler.cfg",
                            "648e9fa47cdd486c1211fa7f678ee3ea7fc557e678c4d522ee5e9bb8ddfecd3a"),
                            "Spec", List.of(), null,
                            List.of(
                                "Acquire", "Acquire", "Acquire", "Acquire", "Acquire",
                                "Acquire", "Acquire", "Acquire", "Acquire", "Acquire",
                                "Acquire", "Acquire", "Acquire", "Acquire", "Acquire",
                                "Acquire", "Acquire", "Acquire", "Acquire", "Acquire",
                                "Acquire", "Acquire", "Acquire", "Acquire", "Acquire",
                                "Acquire", "Acquire", "Acquire", "Acquire", "Acquire",
                                "Acquire", "Acquire", "Acquire", "Acquire", "Acquire",
                                "Acquire", "Acquire", "Acquire", "Acquire", "Acquire",
                                "Acquire", "Acquire", "Acquire", "Acquire", "Acquire",
                                "Acquire", "Acquire", "Acquire", "Acquire", "Acquire",
                                "Acquire", "Acquire", "Acquire", "Acquire", "Acquire",
                                "Acquire", "Acquire", "Acquire", "Acquire", "Acquire",
                                "Acquire", "Acquire", "Acquire", "Acquire", "RequireSelected",
                                "StageReturned", "Acknowledge", "Release", "RequireSelected",
                                "StageReturned", "Acknowledge", "Release", "Crash", "Crash"),
                            -1, 11335, 5583, 1))),
            Map.entry("SnapshotCollection", new SafetyProfile(
                    "SnapshotCollection", Export.STATES, new Model(Map.of(
                            "SnapshotCollection.tla",
                            "f5f99fd8c63a5040208598d093c055a629859c06b071520fb3fcd89e993dad5b",
                            "SnapshotCollection.cfg",
                            "920f189f84dd92c10c321351aecc7f8a4a8154005b96f1e85b155489850aeef5"),
                            "Spec", List.of(), null,
                            List.of(
                                "Settle", "Mutate", "Metadata", "ChangedIDs", "AllIDs", "Body",
                                "Persist", "Recover"),
                            -1, 7626, 3732, 24))),
            Map.entry("SourceWriters", new SafetyProfile(
                    "SourceWriters", Export.STATES, new Model(Map.of(
                            "SourceWriters.tla",
                            "33b853873bba6aefcbabc179540c86746121fa93183f2d3304605bff6e78ba4f",
                            "SourceWriters.cfg",
                            "f4d27776491006a91d4106931ad79775cacb9f7d739618441353f4c1a68f8b3f"),
                            "Spec", List.of(), null,
                            List.of(
                                "Rebuild", "Acquire", "Mark", "Mutate", "Return", "Release",
                                "Crash", "Acquire", "Mark", "Mutate", "Return", "Release",
                                "Crash"),
                            -1, 4293, 3398, 16))));

    private record Effect(long reads, long copied, long possibleCopies, long constraints) {
        Effect and(Effect other) {
            return new Effect(reads | other.reads, copied | other.copied,
                    possibleCopies | other.possibleCopies, constraints | other.constraints);
        }
        Effect or(Effect other) {
            return new Effect(reads | other.reads, copied & other.copied,
                    possibleCopies | other.possibleCopies, constraints | other.constraints);
        }
        long dependencies() {
            // A conditional copy or a constrained copy can affect successor feasibility.
            return reads | (possibleCopies & (~copied | constraints));
        }
    }

    private record Vector(long a, long b, long c, long d, long e) {
        int get(int field) {
            return (int) ((switch (field / FIELDS_PER_WORD) {
                case 0 -> a;
                case 1 -> b;
                case 2 -> c;
                case 3 -> d;
                case 4 -> e;
                default -> throw new IllegalArgumentException("Unsupported state width");
            } >>> shift(field)) & FIELD_MASK);
        }

        Vector project(Vector mask) {
            return new Vector(a & mask.a, b & mask.b, c & mask.c, d & mask.d, e & mask.e);
        }

        Vector with(Vector mask, Vector patch) {
            return new Vector((a & ~mask.a) | patch.a, (b & ~mask.b) | patch.b,
                    (c & ~mask.c) | patch.c, (d & ~mask.d) | patch.d, (e & ~mask.e) | patch.e);
        }
    }
    private record TransitionKey(Vector before, Vector after) {}
    private record ActionProperty(Action predicate, Vector mask, Set<TransitionKey> checked) {}
    private record Edge(Plan plan, int target) {}
    private record Guard(Action action, Vector mask, int directField, byte[] direct,
                         Map<Vector, Boolean> checked) {}
    private sealed interface Formula permits Predicate, Conjunction, Implication {}
    private record Predicate(Guard guard) implements Formula {}
    private record Conjunction(List<Formula> items) implements Formula {}
    private record Implication(Formula antecedent, Formula consequent) implements Formula {}
    private record RankProperty(SemanticNode expression, Vector reads, Guard scope,
                                Map<Vector, Integer> values) {}
    private record Invariant(Action action, Vector mask, Set<Vector> checked) {}
    private record Eventuality(Guard goal, Set<Action> fairActions) {}
    private static final class Row {
        final int id;
        final Vector fields;
        final List<Edge> edges = new ArrayList<>();
        TLCState concrete;
        Row(int id, Vector fields) {
            this.id = id;
            this.fields = fields;
        }
    }
    private record Plan(
            Action action, String label, Vector readMask, int[] copied, int[] written,
            Vector writeMask, Guard guard, Map<Vector, List<Vector>> effects) {}

    private final FastTool tool;
    private final boolean prettyStateValues;
    private final TLCState template;
    private final UniqueString[] names;
    private final long allFields;
    private final int[] fieldIndexes;
    private final Map<UniqueString, Integer> positions = new HashMap<>();
    private final List<List<IValue>> values = new ArrayList<>();
    private final List<List<String>> serialized = new ArrayList<>();
    private final List<Map<IValue, Integer>> encoded = new ArrayList<>();
    private final List<Plan> plans = new ArrayList<>();
    private final List<Invariant> invariants = new ArrayList<>();
    private final List<Formula> formulas = new ArrayList<>();
    private RankProperty rankProperty;
    private final List<ActionProperty> properties = new ArrayList<>();
    private final Map<Vector, Row> states = new HashMap<>();
    private final List<Row> agenda = new ArrayList<>();
    private final Set<Integer> initials = new LinkedHashSet<>();
    private final Eventuality eventuality;
    private final Set<Action> progressActions = Collections.newSetFromMap(new IdentityHashMap<>());
    private Guard progressRequired;
    private int generated;

    private FrameChecker(FastTool tool, Model model, Export export) {
        this.tool = tool;
        prettyStateValues = model.actionsPerItem() < 0 && export != Export.COUNTS;
        validateModel(model);
        boolean factor = Set.of("FeedCoordinator", "JournalReplay", "PipelineComposition")
                .contains(tool.getRootName());
        var init = tool.getInitStates();
        require(init.size() == model.initials());
        template = init.first();
        names = Arrays.stream(template.getVars()).map(SymbolNode::getName)
                .toArray(UniqueString[]::new);
        require(names.length > 0 && names.length <= MAX_FIELDS);
        allFields = (1L << names.length) - 1;
        fieldIndexes = indexes(allFields);
        for (int index = 0; index < names.length; index++) {
            positions.put(names[index], index);
            values.add(new ArrayList<>());
            serialized.add(new ArrayList<>());
            encoded.add(new HashMap<>());
        }
        for (Action property : tool.getImpliedActions()) {
            var square = application(property.pred, "$SquareAct", 2);
            require(property.con == Context.Empty
                    && directVariables(square.getArgs()[1]) == allFields);
            var predicate = new Action(square.getArgs()[0], property.con);
            if (factor) {
                require(rankProperty == null);
                rankProperty = compileRank(predicate);
            } else {
                properties.add(new ActionProperty(
                        predicate, mask(indexes(allReads(predicate.pred))), new HashSet<>()));
            }
        }
        Action[] actions = tool.getActions();
        require(actions.length == model.actions().size());
        int actionsPerItem = model.actionsPerItem();
        SymbolNode item = actionsPerItem <= 0 ? null : quantifiedNextItem();
        int quantified = 0;
        for (int index = 0; index < actions.length; index++) {
            Action action = actions[index];
            String label = action.getName().toString();
            require(label.equals(model.actions().get(index)));
            if (action.con != Context.Empty && actionsPerItem >= 0) {
                require(actionsPerItem > 0);
                var number = IntValue.gen(quantified / actionsPerItem + 1);
                require(number.equals(actionItem(action, action.getOpDef(), item)));
                quantified++;
            }
            // Mutate constrains a previously selected primed map. Use the complete
            // actual TLC transition there, with no partial-row memoization.
            Effect effect;
            Guard guard = null;
            if (actionsPerItem < 0) {
                try {
                    action.con.lookupName(symbol -> {
                        // A branch marker has no name and does not denote a fixed binding.
                        require(symbol != null && symbol.getArity() == 0);
                        Object value = action.con.lookup(symbol);
                        require(value instanceof IntValue
                                || value instanceof BoolValue || value instanceof StringValue);
                        return false;
                    });
                    effect = effect(action.pred, Map.of());
                    var leading = leadingGuard(action.pred);
                    guard = leading == null ? null : guard(new Action(leading, action.con));
                } catch (IllegalStateException | IllegalArgumentException unsupported) {
                    effect = new Effect(allFields, 0, 0, allFields);
                }
            } else {
                effect = tool.getRootName().equals("SnapshotCollection") && label.equals("Mutate")
                        ? new Effect(allFields, 0, 0, allFields)
                        : effect(action.pred, Map.of());
                var leading = leadingGuard(action.pred);
                guard = leading == null ? null : guard(new Action(leading, action.con));
            }
            int[] reads = indexes(effect.dependencies());
            int[] written = indexes(allFields & ~effect.copied());
            plans.add(new Plan(action, label, mask(reads), indexes(effect.copied()),
                    written, mask(written), guard, new HashMap<>()));
        }
        if (actionsPerItem >= 0) require(quantified == ITEMS * actionsPerItem);
        eventuality = model.eventuality() == null ? null : bindEventuality(actions, item);
        for (Action invariant : tool.getInvariants()) {
            require(invariant.con == Context.Empty
                    && ((LevelNode) invariant.pred).getLevel() <= 1);
            if (tool.getRootName().equals("PipelineComposition")
                    && invariant.getName().toString().equals("ProgressAvailable")) {
                bindProgress(invariant, actions);
            } else if (factor && tool.getRootName().equals("FeedCoordinator")
                    && invariant.getName().toString().equals("ProgressAvailable")) {
                bindFeedProgress(invariant, actions, item);
            } else if (factor) {
                formulas.add(formula(invariant.pred));
            } else {
                var reads = mask(indexes(allReads(invariant.pred)));
                invariants.add(new Invariant(invariant, reads, new HashSet<>()));
            }
        }
        for (int index = 0; index < init.size(); index++) {
            var state = init.elementAt(index);
            require(tool.isGoodState(state));
            require(initials.add(row(vector(state, fieldIndexes)).id));
            generated++;
        }
    }

    private void validateModel(Model model) {
        var config = tool.getModelConfig();
        require(!tool.hasStateOrActionConstraints() && !tool.hasSymmetry()
                && tool.checkAssumptions() == EC.NO_ERROR);
        require(config.getSpec().equals(model.spec())
                && config.getOverrides().isEmpty() && config.getModOverrides().isEmpty()
                && config.getView().isEmpty()
                && config.getType().isEmpty() && config.getTypeConstraint().isEmpty());
        require(tool.getImpliedInits().length == 0
                && tool.getImpliedActions().length == model.properties().size()
                && List.of(tool.getImpliedActNames()).equals(model.properties()));
        if (model.eventuality() == null) {
            require(tool.getImpliedTemporals().length == 0 && tool.getTemporals().length == 0);
        } else {
            require(tool.getImpliedTemporals().length == 1
                    && List.of(tool.getImpliedTemporalNames()).equals(List.of(model.eventuality())));
        }
        var invariantNames = tool.getInvNames();
        require(invariantNames.length == config.getInvariants().size());
        for (int index = 0; index < invariantNames.length; index++) {
            require(invariantNames[index].equals(config.getInvariants().elementAt(index)));
        }
    }

    private SymbolNode quantifiedNextItem() {
        var terms = new ArrayList<SemanticNode>();
        var next = tool.getNextStateSpec();
        require(next.con == Context.Empty);
        decompose(next.pred, terms);
        var quantified = terms.stream().filter(term -> term instanceof OpApplNode app
                && app.getOperator().getName().toString().equals("$BoundedExists")).toList();
        require(quantified.size() == 1);
        return quantifiedItem(application(quantified.getFirst(), "$BoundedExists", 1));
    }

    private SymbolNode quantifiedItem(OpApplNode quantifier) {
        var symbols = quantifier.getBdedQuantSymbolLists();
        var bounds = quantifier.getBdedQuantBounds();
        require(symbols.length == 1 && symbols[0].length == 1 && bounds.length == 1
                && bounds[0].getLevel() == 0);
        var range = tool.eval(bounds[0], Context.Empty, TLCState.Empty);
        require(new IntervalValue(1, ITEMS).equals(range));
        return symbols[0][0];
    }

    private static IntValue actionItem(Action action, OpDefNode definition, SymbolNode binder) {
        var parameters = definition.getParams();
        require(binder != null && parameters.length == 1 && parameters[0].getArity() == 0);
        Object argument = action.con.lookup(parameters[0]);
        require(argument instanceof IntValue && argument.equals(action.con.lookup(binder))
                && action.con.lookupName(symbol -> symbol != parameters[0]
                        && symbol != binder) == null);
        return (IntValue) argument;
    }

    private Eventuality bindEventuality(Action[] actions, SymbolNode nextBinder) {
        var next = tool.getNextStateSpec();
        require(next.con == Context.Empty);
        Set<Action> nextActions = Collections.newSetFromMap(new IdentityHashMap<>());
        addActionCalls(next.pred, null, nextBinder, actions, nextActions, true);
        require(nextActions.size() == actions.length);
        Set<Action> fairActions = Collections.newSetFromMap(new IdentityHashMap<>());
        for (Action temporal : tool.getTemporals()) {
            require(temporal.con == Context.Empty);
            addFairActions(temporal.pred, null, nextBinder, actions, fairActions);
        }
        var property = tool.getImpliedTemporals()[0];
        require(property.con == Context.Empty);
        var eventually = application(property.pred, "<>", 1);
        return new Eventuality(guard(new Action(eventually.getArgs()[0], property.con)),
                fairActions);
    }

    private void addFairActions(
            SemanticNode node, SymbolNode binder, SymbolNode nextBinder, Action[] actions,
            Set<Action> result) {
        require(node instanceof OpApplNode);
        var app = (OpApplNode) node;
        switch (app.getOperator().getName().toString()) {
            case "\\land", "$ConjList" -> {
                for (var argument : app.getArgs()) {
                    addFairActions(argument, binder, nextBinder, actions, result);
                }
            }
            case "$BoundedForall" -> {
                require(binder == null && nextBinder != null && app.getArgs().length == 1);
                addFairActions(app.getArgs()[0], quantifiedItem(app), nextBinder,
                        actions, result);
            }
            case "$WF" -> {
                require(app.getArgs().length == 2
                        && directVariables(app.getArgs()[0]) == allFields);
                Set<Action> witnesses = Collections.newSetFromMap(new IdentityHashMap<>());
                addActionCalls(app.getArgs()[1], binder, nextBinder, actions, witnesses, false);
                require(!witnesses.isEmpty());
                result.addAll(witnesses);
            }
            default -> throw new IllegalArgumentException("Unsupported fairness at "
                    + app.getLocation());
        }
    }

    private void addActionCalls(
            SemanticNode node, SymbolNode binder, SymbolNode nextBinder, Action[] actions,
            Set<Action> result, boolean next) {
        require(node instanceof OpApplNode);
        var app = (OpApplNode) node;
        var arguments = app.getArgs();
        switch (app.getOperator().getName().toString()) {
            case "\\lor", "$DisjList" -> {
                for (var argument : arguments) {
                    addActionCalls(argument, binder, nextBinder, actions, result, next);
                }
                return;
            }
            case "$BoundedExists" -> {
                require(next && binder == null && nextBinder != null && arguments.length == 1);
                var binderHere = quantifiedItem(app);
                addActionCalls(arguments[0], binderHere, nextBinder, actions, result, true);
                return;
            }
        }
        require(app.getOperator() instanceof OpDefNode);
        var definition = (OpDefNode) app.getOperator();
        require(!definition.isBuiltIn() && !definition.getInRecursive()
                && arguments.length == definition.getParams().length);
        if (arguments.length == 0) {
            for (Action action : actions) {
                if (action.getOpDef() == definition && action.pred == definition.getBody()) {
                    require(action.con == Context.Empty && result.add(action));
                    return;
                }
            }
            addActionCalls(definition.getBody(), binder, nextBinder, actions, result, next);
            return;
        }
        require(arguments.length == 1 && binder != null && arguments[0] instanceof OpApplNode);
        var reference = (OpApplNode) arguments[0];
        require(reference.getOperator() == binder && reference.getArgs().length == 0);
        int items = 0;
        for (Action action : actions) {
            if (action.getOpDef() == definition && action.pred == definition.getBody()) {
                int item = actionItem(action, definition, nextBinder).val;
                require(item >= 1 && item <= ITEMS && (items & (1 << item)) == 0);
                require(result.add(action));
                items |= 1 << item;
            }
        }
        require(items == ((1 << ITEMS) - 1) << 1);
    }

    private void bindProgress(Action invariant, Action[] actions) {
        // The implication requires one of these exact actions to change the full tuple.
        var next = tool.getNextStateSpec();
        var effectiveTerms = new ArrayList<SemanticNode>();
        decompose(next.pred, effectiveTerms);
        require(next.con == Context.Empty && effectiveTerms.size() == actions.length);
        for (int index = 0; index < actions.length; index++) {
            require(actions[index].con == Context.Empty
                    && effectiveTerms.get(index) == actions[index].pred);
        }
        var implication = application(invariant.pred, "=>", 2);
        var enabled = application(implication.getArgs()[1], "ENABLED", 1);
        var angle = application(enabled.getArgs()[0], "$AngleAct", 2);
        require(directVariables(angle.getArgs()[1]) == allFields);
        var progress = new ArrayList<SemanticNode>();
        decompose(angle.getArgs()[0], progress);
        require(!progress.isEmpty() && effectiveTerms.containsAll(progress));
        for (var action : actions) {
            if (progress.contains(action.pred)) require(progressActions.add(action));
        }
        require(progressActions.size() == progress.size());
        progressRequired = guard(new Action(implication.getArgs()[0], invariant.con));
    }

    private static OpApplNode reference(SemanticNode node) {
        require(node instanceof OpApplNode app && app.getArgs().length == 0);
        return (OpApplNode) node;
    }

    private void bindFeedProgress(Action invariant, Action[] actions, SymbolNode item) {
        var implication = application(invariant.pred, "=>", 2);
        var enabled = application(implication.getArgs()[1], "ENABLED", 1);
        var angle = application(enabled.getArgs()[0], "$AngleAct", 2);
        require(directVariables(angle.getArgs()[1]) == allFields);
        var conjunction = application(angle.getArgs()[0], "\\land", 2);
        var next = tool.getNextStateSpec();
        var rootNext = tool.getSpecProcessor().getRootModule().getOpDef("Next");
        require(next.con == Context.Empty && reference(conjunction.getArgs()[1]).getOperator() == rootNext);
        require(next.pred == rootNext.getBody() || reference(next.pred).getOperator() == rootNext);
        Set<Action> nextActions = Collections.newSetFromMap(new IdentityHashMap<>());
        addActionCalls(next.pred, null, item, actions, nextActions, true);
        require(nextActions.size() == actions.length);
        addActionCalls(conjunction.getArgs()[0], null, item, actions, progressActions, true);
        require(!progressActions.isEmpty() && nextActions.containsAll(progressActions));
        progressRequired = guard(new Action(implication.getArgs()[0], invariant.con));
    }

    private RankProperty compileRank(Action property) {
        SemanticNode compare = property.pred;
        Guard scope = null;
        if (tool.getRootName().equals("JournalReplay")) {
            var implication = application(compare, "=>", 2);
            var both = application(implication.getArgs()[0], "\\land", 2);
            var unprimed = application(both.getArgs()[0], "\\lnot", 1);
            var primed = application(both.getArgs()[1], "\\lnot", 1);
            var first = reference(unprimed.getArgs()[0]);
            var second = reference(application(primed.getArgs()[0], "'", 1).getArgs()[0]);
            require(first.getOperator() == second.getOperator()
                    && first.getOperator().getName().toString().equals("replaying"));
            scope = guard(new Action(unprimed, property.con));
            compare = implication.getArgs()[1];
        }
        var less = application(compare, "<", 2);
        var left = reference(application(less.getArgs()[0], "'", 1).getArgs()[0]);
        var right = reference(less.getArgs()[1]);
        require(left.getOperator() == right.getOperator()
                && right.getOperator().getName().toString().equals("Rank")
                && right.getLevel() <= 1 && property.con == Context.Empty);
        return new RankProperty(right, mask(indexes(allReads(right))), scope, new HashMap<>());
    }

    private int rank(RankProperty property, Row row) {
        return property.values().computeIfAbsent(row.fields.project(property.reads()), ignored -> {
            var result = tool.eval(property.expression(), Context.Empty, concrete(row));
            require(result instanceof IntValue);
            return ((IntValue) result).val;
        });
    }

    private Formula formula(SemanticNode node) {
        if (node instanceof OpApplNode app && app.getOperator().getKind() == ASTConstants.BuiltInKind) {
            var arguments = app.getArgs();
            switch (app.getOperator().getName().toString()) {
                case "$ConjList", "\\land" -> {
                    require(arguments.length > 0);
                    return new Conjunction(Arrays.stream(arguments).map(this::formula).toList());
                }
                case "=>" -> {
                    require(arguments.length == 2);
                    return new Implication(formula(arguments[0]), formula(arguments[1]));
                }
            }
        }
        return new Predicate(guard(new Action(node, Context.Empty)));
    }

    private boolean matches(Formula formula, Row row) {
        return switch (formula) {
            case Predicate leaf -> matches(leaf.guard(), row);
            case Implication implication ->
                !matches(implication.antecedent(), row) || matches(implication.consequent(), row);
            case Conjunction conjunction -> {
                boolean valid = true;
                for (Formula clause : conjunction.items()) {
                    if (!matches(clause, row)) {
                        valid = false;
                        break;
                    }
                }
                yield valid;
            }
        };
    }

    private static void require(boolean correct) {
        if (!correct) throw new IllegalStateException("Unsupported or invalid model");
    }

    private static OpApplNode application(SemanticNode node, String operator, int arity) {
        require(node instanceof OpApplNode app
                && app.getOperator().getName().toString().equals(operator)
                && app.getArgs().length == arity);
        return (OpApplNode) node;
    }

    private static int[] indexes(long mask) {
        var positions = new int[Long.bitCount(mask)];
        int next = 0;
        while (mask != 0) {
            long bit = Long.lowestOneBit(mask);
            positions[next++] = Long.numberOfTrailingZeros(bit);
            mask ^= bit;
        }
        return positions;
    }

    private long variable(SymbolNode symbol) {
        if (symbol.getKind() != ASTConstants.VariableDeclKind) return 0;
        Integer index = positions.get(symbol.getName());
        require(index != null);
        return 1L << index;
    }

    private long allReads(SemanticNode node) {
        return allReads(node, Map.of());
    }

    private long allReads(SemanticNode node, Map<SymbolNode, Long> bindings) {
        long result = 0;
        for (SymbolNode symbol : ((LevelNode) node).getAllParams()) {
            result |= variable(symbol) | bindings.getOrDefault(symbol, 0L);
        }
        return result;
    }

    private long directVariables(SemanticNode node) {
        if (node instanceof OpApplNode application) {
            String name = application.getOperator().getName().toString();
            if (name.equals("$Tuple")) {
                long result = 0;
                for (var item : application.getArgs()) result |= directVariables(item);
                return result;
            }
            if (application.getOperator() instanceof OpDefNode definition
                    && application.getArgs().length == 0) {
                require(!definition.getInRecursive());
                return directVariables(definition.getBody());
            }
            long bit = variable(application.getOperator());
            if (bit != 0 && application.getArgs().length == 0) return bit;
        }
        throw new IllegalArgumentException("Unsupported copied variable at " + node.getLocation());
    }

    private Effect readExpression(SemanticNode node, Map<SymbolNode, Long> bindings) {
        require(((LevelNode) node).getLevel() <= 1);
        return new Effect(allReads(node, bindings), 0, 0, 0);
    }

    private long primedInputs(LevelNode node) {
        if (node.getLevel() <= 1) return 0;
        require(node instanceof OpApplNode);
        var app = (OpApplNode) node;
        switch (app.getOperator().getName().toString()) {
            case "'" -> {
                return directVariables(app.getArgs()[0]);
            }
            case "=", "\\land", "\\lor", "$ConjList", "$DisjList", "$IfThenElse",
                    ">", "Len", "$RcdSelect" -> {
                long primed = 0;
                for (var term : app.getArgs()) primed |= primedInputs(term);
                return primed;
            }
            default -> throw new IllegalArgumentException("Unsupported primed input");
        }
    }

    private Effect effect(SemanticNode node, Map<SymbolNode, Long> bindings) {
        require(!(node instanceof SubstInNode));
        if (node instanceof LetInNode local) return effect(local.getBody(), bindings);
        if (!(node instanceof OpApplNode application)) return readExpression(node, bindings);
        String name = application.getOperator().getName().toString();
        var operands = application.getArgs();
        switch (name) {
            case "$ConjList", "\\land" -> {
                Effect result = new Effect(0, 0, 0, 0);
                for (var term : operands) result = result.and(effect(term, bindings));
                return result;
            }
            case "$DisjList", "\\lor" -> {
                Effect result = effect(operands[0], bindings);
                for (int index = 1; index < operands.length; index++) {
                    result = result.or(effect(operands[index], bindings));
                }
                return result;
            }
            case "$IfThenElse" -> {
                require(operands[0].getLevel() <= 1);
                return effect(operands[1], bindings).or(effect(operands[2], bindings))
                        .and(readExpression(operands[0], bindings));
            }
            case "$BoundedExists" -> {
                long boundReads = 0;
                for (var bound : application.getBdedQuantBounds()) {
                    require(bound.getLevel() <= 1);
                    boundReads |= allReads(bound, bindings);
                }
                return effect(operands[0], bindings).and(new Effect(boundReads, 0, 0, 0));
            }
            case "UNCHANGED" -> {
                long copied = directVariables(operands[0]);
                return new Effect(0, copied, copied, 0);
            }
            case "=", "\\in" -> {
                if (operands[0] instanceof OpApplNode left
                        && left.getOperator().getName().toString().equals("'")) {
                    long written = directVariables(left.getArgs()[0]);
                    long reads = allReads(operands[1], bindings);
                    // The same read can constrain a copied next-state field.
                    long primed = primedInputs(operands[1]);
                    return new Effect(reads | primed, 0, 0, written | primed);
                }
            }
        }
        if (application.getLevel() > 1
                && application.getOperator() instanceof OpDefNode definition
                && !definition.isBuiltIn()) {
            var nested = new HashMap<>(bindings);
            var parameters = definition.getParams();
            require(parameters.length == operands.length && !definition.getInRecursive());
            for (int index = 0; index < parameters.length; index++) {
                require(parameters[index].getArity() == 0 && operands[index].getLevel() <= 1);
                nested.put(parameters[index], allReads(operands[index], bindings));
            }
            return effect(definition.getBody(), nested);
        }
        return readExpression(node, bindings);
    }

    private static void decompose(SemanticNode node, List<SemanticNode> terms) {
        if (node instanceof OpApplNode app) {
            String name = app.getOperator().getName().toString();
            if (name.equals("$DisjList") || name.equals("\\lor")) {
                for (var item : app.getArgs()) decompose(item, terms);
                return;
            }
            if (app.getOperator() instanceof OpDefNode definition && !definition.isBuiltIn()
                    && definition.getParams().length == 0 && app.getArgs().length == 0
                    && definition.getBody() != null) {
                require(!definition.getInRecursive());
                decompose(definition.getBody(), terms);
                return;
            }
        }
        terms.add(node);
    }

    private static SemanticNode leadingGuard(SemanticNode node) {
        while (node instanceof OpApplNode app
                && List.of("$ConjList", "\\land")
                        .contains(app.getOperator().getName().toString())) {
            node = app.getArgs()[0];
        }
        return node instanceof LevelNode level && level.getLevel() <= 1 ? node : null;
    }

    private int encode(int field, IValue value) {
        var table = encoded.get(field);
        Integer previous = table.get(value);
        if (previous != null) return previous;
        int number = values.get(field).size();
        require(number < FIELD_MASK);
        // Normalize the shared TLC value before any evaluator can reuse it.
        value.deepNormalize();
        values.get(field).add(value);
        serialized.get(field).add(prettyStateValues ? Values.ppr(value) : value.toString());
        table.put(value, number);
        return number;
    }

    private Guard guard(Action action) {
        require(((LevelNode) action.pred).getLevel() <= 1);
        int[] reads = indexes(allReads(action.pred));
        if (reads.length <= 1) {
            int field = reads.length == 1 ? reads[0] : -1;
            return new Guard(action, null, field, new byte[field >= 0 ? FIELD_MASK + 1 : 1], null);
        }
        return new Guard(action, mask(reads), -1, null, new HashMap<>());
    }

    private static int shift(int field) {
        return (field % FIELDS_PER_WORD) * BITS_PER_FIELD;
    }

    private static Vector mask(int[] fields) {
        long[] words = new long[5];
        for (int field : fields) {
            words[field / FIELDS_PER_WORD] |= (long) FIELD_MASK << shift(field);
        }
        return new Vector(words[0], words[1], words[2], words[3], words[4]);
    }

    private Vector vector(TLCState state, int[] fields) {
        long[] words = new long[5];
        for (int field : fields) {
            long value = encode(field, state.lookup(names[field]));
            words[field / FIELDS_PER_WORD] |= value << shift(field);
        }
        return new Vector(words[0], words[1], words[2], words[3], words[4]);
    }

    private Row row(Vector vector) {
        return states.computeIfAbsent(vector, fields -> {
            Row created = new Row(agenda.size(), fields);
            agenda.add(created);
            return created;
        });
    }

    private TLCState concrete(Row row) {
        if (row.concrete == null) {
            TLCState state = template.createEmpty();
            for (int index = 0; index < names.length; index++) {
                state.bind(names[index], values.get(index).get(row.fields.get(index)));
            }
            row.concrete = state;
        }
        return row.concrete;
    }

    private List<Vector> steps(Row before, Plan plan) {
        TLCState source = concrete(before);
        var successors = tool.getNextStates(plan.action(), source);
        List<Vector> result = new ArrayList<>(successors.size());
        for (int index = 0; index < successors.size(); index++) {
            TLCState successor = successors.elementAt(index);
            require(tool.isGoodState(successor));
            for (int field : plan.copied()) {
                require(source.lookup(names[field]).equals(successor.lookup(names[field])));
            }
            result.add(vector(successor, plan.written()));
        }
        return List.copyOf(result);
    }

    private boolean matches(Guard guard, Row row) {
        var direct = guard.direct();
        if (direct != null) {
            int key = guard.directField() < 0 ? 0 : row.fields.get(guard.directField());
            byte result = direct[key];
            if (result == 0) {
                result = (byte) (tool.isValid(guard.action(), concrete(row)) ? 1 : -1);
                direct[key] = result;
            }
            return result == 1;
        }
        return guard.checked().computeIfAbsent(row.fields.project(guard.mask()),
                ignored -> tool.isValid(guard.action(), concrete(row)));
    }

    private void checkProperties(Row before, Row after) {
        // Each checked property admits stuttering on the whole state tuple.
        if (before == after) return;
        if (rankProperty != null && (rankProperty.scope() == null
                || (matches(rankProperty.scope(), before) && matches(rankProperty.scope(), after)))) {
            require(rank(rankProperty, after) < rank(rankProperty, before));
        }
        for (ActionProperty property : properties) {
            if (property.checked().add(new TransitionKey(
                    before.fields.project(property.mask()),
                    after.fields.project(property.mask())))) {
                require(tool.isValid(property.predicate(), concrete(before), concrete(after)));
            }
        }
    }

    private void explore() {
        for (int index = 0; index < agenda.size(); index++) {
            Row current = agenda.get(index);
            for (Invariant invariant : invariants) {
                if (invariant.checked().add(current.fields.project(invariant.mask()))) {
                    require(tool.isValid(invariant.action(), concrete(current)));
                }
            }
            for (Formula formula : formulas) require(matches(formula, current));
            boolean progress = false;
            for (Plan plan : plans) {
                if (plan.guard() != null && !matches(plan.guard(), current)) continue;
                List<Vector> effects = plan.effects().computeIfAbsent(
                        current.fields.project(plan.readMask()),
                        ignored -> steps(current, plan));
                for (Vector effect : effects) {
                    Row after = row(current.fields.with(plan.writeMask(), effect));
                    checkProperties(current, after);
                    progress |= after != current && progressActions.contains(plan.action());
                    current.edges.add(new Edge(plan, after.id));
                    generated++;
                }
            }
            require(!tool.getModelConfig().getCheckDeadlock() || !current.edges.isEmpty());
            require(progressRequired == null || progress
                    || !matches(progressRequired, current));
        }
    }

    private void checkEventuality(Eventuality obligation) {
        int count = agenda.size();
        int[] incoming = new int[count];
        for (Row row : agenda) {
            boolean progress = false;
            for (Edge edge : row.edges) {
                if (row.id != edge.target()) {
                    incoming[edge.target()]++;
                    progress |= obligation.fairActions().contains(edge.plan().action());
                }
            }
            require(progress || matches(obligation.goal(), row));
        }
        // Each exact WF operand is a fair relation. It can be a disjunction
        // of multiple official actions. Any member edge witnesses that its
        // operand relation is enabled. Reverse topological order gives the
        // rank for eventuallyFinalOfFamily with the WF operands as the family.
        int[] queue = new int[count];
        int admitted = 0;
        for (int row = 0; row < count; row++) {
            if (incoming[row] == 0) queue[admitted++] = row;
        }
        int processed = 0;
        while (processed < admitted) {
            Row row = agenda.get(queue[processed++]);
            for (Edge edge : row.edges) {
                int after = edge.target();
                if (row.id != after && --incoming[after] == 0) queue[admitted++] = after;
            }
        }
        require(processed == count);
    }

    private static void binaryString(DataOutputStream stream, String value) throws IOException {
        byte[] bytes = value.getBytes(StandardCharsets.UTF_8);
        stream.writeInt(bytes.length);
        stream.write(bytes);
    }

    private void binaryReceipt(Path file, boolean withEdges) throws IOException {
        var labels = new java.util.LinkedHashMap<String, Integer>();
        for (var plan : plans) labels.computeIfAbsent(plan.label(), ignored -> labels.size());
        require(labels.size() < 256);
        for (int index = 0; index < initials.size(); index++) require(initials.contains(index));
        int edges = agenda.stream().mapToInt(row -> row.edges.size()).sum();
        require(generated == initials.size() + edges);
        try (var stream = new DataOutputStream(new BufferedOutputStream(Files.newOutputStream(file)))) {
            stream.writeInt(0x50465232);
            stream.writeBoolean(withEdges);
            stream.writeInt(generated);
            stream.writeInt(agenda.size());
            stream.writeInt(initials.size());
            stream.writeInt(edges);
            stream.writeByte(names.length);
            for (int field = 0; field < names.length; field++) {
                binaryString(stream, names[field].toString());
                var table = serialized.get(field);
                stream.writeShort(table.size());
                for (var value : table) binaryString(stream, value);
            }
            for (var row : agenda) {
                for (int field = 0; field < names.length; field++) stream.writeShort(row.fields.get(field));
            }
            if (!withEdges) return;
            stream.writeByte(labels.size());
            for (var label : labels.keySet()) binaryString(stream, label);
            for (var row : agenda) stream.writeInt(row.edges.size());
            for (var row : agenda) {
                for (var edge : row.edges) stream.writeInt(edge.target());
            }
            for (var row : agenda) {
                for (var edge : row.edges) stream.writeByte(labels.get(edge.plan().label()));
            }
        }
    }

    private void receipt(Path file) throws IOException {
        try (BufferedWriter output = Files.newBufferedWriter(file)) {
            write(output, "F", Arrays.stream(names).map(UniqueString::toString).toList());
            for (int field = 0; field < names.length; field++) {
                write(output, "V\t" + field, serialized.get(field));
            }
            for (int initial : initials) output.write("I\t" + initial + "\n");
            int edges = 0;
            for (Row row : agenda) {
                output.write("S\t" + row.id);
                for (int field = 0; field < names.length; field++) {
                    output.write("\t" + row.fields.get(field));
                }
                output.newLine();
                for (Edge edge : row.edges) {
                    output.write("E\t" + row.id + "\t" + edge.plan().label() + "\t"
                            + edge.target() + "\n");
                    edges++;
                }
            }
            require(edges + initials.size() == generated);
            output.write("C\t" + generated + "\t" + states.size() + "\t" + initials.size()
                    + "\t" + edges + "\n");
        }
    }

    private static void write(BufferedWriter writer, String prefix, List<String> fields)
            throws IOException {
        writer.write(prefix);
        for (String field : fields) {
            writer.write('\t');
            byte[] bytes = field.getBytes(StandardCharsets.UTF_8);
            writer.write(Base64.getEncoder().encodeToString(bytes));
        }
        writer.newLine();
    }

    /** Resolves only the reviewed modules and their official standard modules. */
    private record SnapshotResolver(Path directory, Set<String> files)
            implements FilenameToStream {
        @Override
        public File resolve(String name, boolean module) {
            if (module && !name.endsWith(".tla")) name += ".tla";
            Path requested = Path.of(name);
            String file = requested.getFileName().toString();
            Path selected = directory.resolve(file);
            require(requested.getNameCount() == 1 || requested.equals(selected));
            if (file.endsWith(".class")) {
                require((files.contains(file.replace(".class", ".tla"))
                        || file.equals("tlc2.overrides.TLCOverrides.class"))
                        && !Files.exists(selected, LinkOption.NOFOLLOW_LINKS));
            } else {
                require(files.contains(file));
            }
            return new TLAFile(selected.toString(), STANDARD_MODULES.contains(file), this);
        }

        @Override
        public String getFullPath() {
            return directory.toString();
        }

        @Override
        public boolean isStandardModule(String name) {
            String file = name.endsWith(".tla") ? name : name + ".tla";
            return STANDARD_MODULES.contains(file);
        }
    }

    private static String digest(byte[] bytes) throws NoSuchAlgorithmException {
        return HexFormat.of().formatHex(MessageDigest.getInstance("SHA-256").digest(bytes));
    }

    private static byte[] sourceBytes(InputStream stream) throws IOException {
        try (stream) {
            byte[] bytes = stream.readNBytes(MAX_SOURCE_BYTES + 1);
            require(bytes.length <= MAX_SOURCE_BYTES);
            return bytes;
        }
    }

    private static void qualifyArchive(Path jar) throws IOException, NoSuchAlgorithmException {
        require(Files.notExists(jar.resolveSibling("CommunityModules.jar"),
                LinkOption.NOFOLLOW_LINKS));
        var digest = MessageDigest.getInstance("SHA-256");
        try (var stream = new DigestInputStream(Files.newInputStream(jar), digest)) {
            stream.transferTo(OutputStream.nullOutputStream());
        }
        require(TLC_SHA256.equals(HexFormat.of().formatHex(digest.digest())));
    }

    private static Map<String, byte[]> reviewedFiles(
            Path specification, Path jar, Model model, FilenameToStream stock)
            throws IOException, NoSuchAlgorithmException {
        Map<String, byte[]> files = new HashMap<>();
        for (var source : model.sources().entrySet()) {
            String name = source.getKey();
            boolean module = name.endsWith(".tla");
            Path path = specification.resolve(name);
            require(Files.isRegularFile(path, LinkOption.NOFOLLOW_LINKS));
            require(stock.resolve(name, module).toPath().toRealPath().equals(path));
            byte[] bytes = sourceBytes(Files.newInputStream(path));
            require(source.getValue().equals(digest(bytes)));
            files.put(name, bytes);
        }
        try (var archive = new JarFile(jar.toFile())) {
            for (String module : STANDARD_MODULES) {
                var entry = archive.getJarEntry("tla2sany/StandardModules/" + module);
                require(entry != null);
                byte[] bytes = sourceBytes(archive.getInputStream(entry));
                Path resolved = stock.resolve(module, true).toPath();
                require(Arrays.equals(bytes, sourceBytes(Files.newInputStream(resolved))));
                files.put(module, bytes);
            }
        }
        for (String name : files.keySet()) {
            if (name.endsWith(".tla")) {
                String override = name.replace(".tla", ".class");
                require(!Files.exists(stock.resolve(override, false).toPath()));
            }
        }
        require(!Files.exists(stock.resolve("tlc2.overrides.TLCOverrides.class", false)
                .toPath()));
        require(!Files.exists(specification.resolve("tlc2/overrides/TLCOverrides.class"),
                LinkOption.NOFOLLOW_LINKS));
        return files;
    }

    private static void qualifySources(
            Path specification, Path snapshot, Path jar, Model model, Map<String, byte[]> files,
            FilenameToStream stock)
            throws IOException, NoSuchAlgorithmException {
        qualifyArchive(jar);
        var current = reviewedFiles(specification, jar, model, stock);
        for (var file : files.entrySet()) {
            require(Arrays.equals(file.getValue(), current.get(file.getKey()))
                    && Arrays.equals(file.getValue(),
                            sourceBytes(Files.newInputStream(snapshot.resolve(file.getKey())))));
        }
    }

    private enum Export { TEXT, GRAPH, STATES, COUNTS }

    private static void checkSnapshot(
            String module, String config, Path specification, Path jar, Model model, Path receipt,
            Export export, FilenameToStream stock)
            throws IOException, NoSuchAlgorithmException {
        qualifyArchive(jar);
        var files = reviewedFiles(specification, jar, model, stock);
        Path snapshot = Files.createTempDirectory(receipt.getParent(), "frame-sources-");
        try {
            for (var file : files.entrySet()) {
                Files.write(snapshot.resolve(file.getKey()), file.getValue());
            }
            FP64.Init();
            var tool = new FastTool(snapshot + File.separator, module, config,
                    new SnapshotResolver(snapshot, files.keySet()));
            qualifySources(specification, snapshot, jar, model, files, stock);
            var checker = new FrameChecker(tool, model, export);
            checker.explore();
            require(checker.generated == model.generated()
                    && checker.states.size() == model.states());
            if (checker.eventuality != null) checker.checkEventuality(checker.eventuality);
            switch (export) {
                case TEXT -> checker.receipt(receipt);
                case GRAPH -> checker.binaryReceipt(receipt, true);
                case STATES -> checker.binaryReceipt(receipt, false);
                case COUNTS -> Files.writeString(receipt, "C\t" + checker.generated + "\t"
                        + checker.states.size() + "\t" + checker.initials.size() + "\t"
                        + (checker.generated - checker.initials.size()) + "\n");
            }
            qualifySources(specification, snapshot, jar, model, files, stock);
        } finally {
            for (String file : files.keySet()) Files.deleteIfExists(snapshot.resolve(file));
            Files.delete(snapshot);
        }
    }

    private static Export expectedExport(String config) {
        return switch (config) {
            case "BuildingsConstruction", "FeedCoordinator" -> Export.STATES;
            case "MonitorBackwardContextLiveness", "SnapshotCollectionLiveness",
                    "GeographyPublicationLiveness" -> Export.COUNTS;
            default -> Export.GRAPH;
        };
    }

    /** Publishes only a complete checked receipt. An unsupported request uses ordinary TLC. */
    public static boolean check(
            String module, String config, String specificationDirectory, String receiptPath,
            String requestedExport) {
        if (module == null || config == null) return false;
        SafetyProfile safety = SAFETY.get(config);
        Model model;
        if (safety != null && safety.module().equals(module)) {
            model = safety.model();
        } else if (module.equals(config) || (module + "Liveness").equals(config)) {
            model = module.equals(config) ? MODELS.get(module) : null;
            if (model == null) model = RANKED_COHORT.get(config);
        } else {
            return false;
        }
        if (model == null) return false;
        try {
            Path jar = Path.of(FastTool.class.getProtectionDomain().getCodeSource()
                    .getLocation().toURI()).toRealPath();
            FilenameToStream resolver = new SimpleFilenameToStream(specificationDirectory);
            Export export = Export.valueOf(requestedExport);
            Export expected = safety == null ? expectedExport(config) : safety.export();
            if (export != Export.TEXT && export != expected) return false;
            Path specification = Path.of(specificationDirectory).toRealPath();
            Path receipt = Path.of(receiptPath).toAbsolutePath().normalize();
            require(!Files.exists(receipt, LinkOption.NOFOLLOW_LINKS));
            Path staged = Files.createTempFile(receipt.getParent(), "frame-", ".tmp");
            try {
                checkSnapshot(module, config, specification, jar, model, staged, export, resolver);
                Files.move(staged, receipt, StandardCopyOption.ATOMIC_MOVE);
                return true;
            } finally {
                Files.deleteIfExists(staged);
            }
        } catch (IOException | URISyntaxException | NoSuchAlgorithmException
                | RuntimeException invalid) {
            return false;
        }
    }
}
