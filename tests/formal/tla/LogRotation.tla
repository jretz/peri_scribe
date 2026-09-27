------------------------------ MODULE LogRotation ------------------------------
EXTENDS Naturals, Sequences

CONSTANT MaximumFailures
VARIABLES plain, archive, receipt, source, base, target, staged, expected,
          phase, failures, late
variables == <<plain, archive, receipt, source, base, target, staged, expected,
               phase, failures, late>>
Init ==
    /\ plain = <<1, 1>> /\ archive \in {<<>>, <<2>>}
    /\ expected = archive \o plain
    /\ receipt = FALSE /\ source = <<>> /\ base = <<>> /\ target = <<>>
    /\ staged = <<>> /\ phase = "check" /\ failures = MaximumFailures
    /\ late = FALSE
Check ==
    /\ phase = "check"
    /\ phase' = IF receipt /\ archive = target
                THEN IF plain = <<>> THEN "forget" ELSE "unlink"
                ELSE IF plain = <<>> THEN "idle" ELSE "prepare"
    /\ UNCHANGED <<plain, archive, receipt, source, base, target, staged,
                   expected, failures, late>>
Prepare ==
    /\ phase = "prepare" /\ staged' = archive \o plain /\ phase' = "receipt"
    /\ UNCHANGED <<plain, archive, receipt, source, base, target,
                   expected, failures, late>>
WriteReceipt ==
    /\ phase = "receipt"
    /\ receipt' = TRUE /\ source' = plain /\ base' = archive /\ target' = staged
    /\ phase' = "publish"
    /\ UNCHANGED <<plain, archive, staged, expected, failures, late>>
Publish ==
    /\ phase = "publish" /\ archive' = staged /\ phase' = "unlink"
    /\ UNCHANGED <<plain, receipt, source, base, target, staged,
                   expected, failures, late>>
RemovePlain ==
    /\ phase = "unlink" /\ plain' = <<>> /\ phase' = "forget"
    /\ UNCHANGED <<archive, receipt, source, base, target, staged,
                   expected, failures, late>>
ForgetReceipt ==
    /\ phase = "forget" /\ receipt' = FALSE /\ phase' = "idle"
    /\ source' = <<>> /\ base' = <<>> /\ target' = <<>>
    /\ UNCHANGED <<plain, archive, staged, expected, failures, late>>
\* Late diagnostic content may be byte-identical to an earlier record.
AppendLate ==
    /\ phase = "idle" /\ ~late /\ late' = TRUE
    /\ plain' = <<1>> /\ expected' = expected \o <<1>> /\ phase' = "check"
    /\ UNCHANGED <<archive, receipt, source, base, target, staged, failures>>
Crash ==
    /\ phase # "idle" /\ failures > 0
    /\ phase' = "check" /\ staged' = <<>> /\ failures' = failures - 1
    /\ UNCHANGED <<plain, archive, receipt, source, base, target, expected, late>>
Progress == Check \/ Prepare \/ WriteReceipt \/ Publish \/ RemovePlain
            \/ ForgetReceipt \/ AppendLate
Next == Progress \/ Crash
Spec == Init /\ [][Next]_variables
LiveSpec == Spec /\ WF_variables(Progress)
TypeOK ==
    /\ plain \in Seq({1, 2}) /\ archive \in Seq({1, 2})
    /\ source \in Seq({1, 2}) /\ base \in Seq({1, 2})
    /\ target \in Seq({1, 2}) /\ staged \in Seq({1, 2})
    /\ expected \in Seq({1, 2}) /\ Len(expected) <= 4
    /\ receipt \in BOOLEAN /\ late \in BOOLEAN
    /\ failures \in 0..MaximumFailures
    /\ phase \in {"check", "prepare", "receipt", "publish", "unlink", "forget",
                   "idle"}
LogicalContents == IF receipt /\ archive = target THEN archive ELSE archive \o plain
NoLossOrDuplication == LogicalContents = expected
ReceiptAuthenticatesPublishedData == receipt =>
    archive \in {base, target} /\ target = base \o source
SourceRemainsRecoverable == receipt /\ archive = base => plain = source
RetirementRequiresArchive == plain = <<>> => archive = expected
CompletedRotationIsClean == phase = "idle" => ~receipt /\ plain = <<>>
EventuallyArchived == <> (late /\ phase = "idle" /\ archive = expected)
=============================================================================
