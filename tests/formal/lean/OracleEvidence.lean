import PeriScribe.PerimeterVersions
import PeriScribe.PublicationCandidates

namespace PeriScribe.EvidenceOracle

/-- Invalid vectors fail rather than silently changing the conformance domain. -/
def natural (value : String) : Except String Nat :=
  match value.toNat? with
  | some result => pure result
  | none => throw s!"Expected natural number: {value}"

def optional (value : String) : Except String (Option Nat) :=
  if value = "-1" then pure none else some <$> natural value

def boolean (value : String) : Except String Bool :=
  if value = "0" then pure false
  else if value = "1" then pure true else throw "Expected Boolean"

def members (mask : Nat) : List Nat :=
  (List.range 32).filter (fun value => mask / 2 ^ value % 2 == 1)

def mask (values : List Nat) : Nat :=
  values.eraseDups.foldl (fun result value => result + 2 ^ value) 0

def numbers (values : List Nat) : String :=
  String.intercalate " " (values.map toString)

def observation (value : String) : Except String PerimeterVersions.Observation := do
  match value.splitOn "," with
  | [identity, time, published, serial, object, feed, source, category, start, width,
      capture, sameYear, flight, ancestors] =>
    return ⟨← natural identity, ← natural time, ← natural published, ← natural serial,
      ← natural object, ← natural feed, ← natural source, ← natural category,
      ← natural start, ← natural width, ← optional capture, ← boolean sameYear,
      ← boolean flight, members (← natural ancestors)⟩
  | _ => throw "Expected observation vector"

def observationsText (values : List PerimeterVersions.Observation) : String :=
  numbers (values.flatMap fun value =>
    [value.identity, value.time, mask (PerimeterVersions.lineage value)])

def mapping (value : String) : Except String PublicationCandidates.Mapping := do
  match value.splitOn "," with
  | [identity, identifiers, order, captured, shape, area, collapsed] =>
    return ⟨← natural identity, members (← natural identifiers), ← natural order,
      ← natural captured, ← natural shape, ← optional area, ← boolean collapsed⟩
  | _ => throw "Expected mapping vector"

def pair (value : String) : Except String (Nat × Nat) := do
  match value.splitOn "," with
  | [first, second] => return (← natural first, ← natural second)
  | _ => throw "Expected pair"

def survey (value : String) : Except String PerimeterVersions.Survey := do
  match value.splitOn "," with
  | [time, area, shape, capture, sameYear, flight] =>
    return ⟨← natural time, ← natural area, ← natural shape, ← optional capture,
      ← boolean sameYear, ← boolean flight⟩
  | _ => throw "Expected survey vector"

def surveyFlags (values : List PerimeterVersions.Survey)
    (difference : Nat → Nat → Nat) : List Nat :=
  (values.foldl (fun (state : Option PerimeterVersions.Survey × List Nat) current =>
    let fresh := PerimeterVersions.surveyed state.1 current difference
    (PerimeterVersions.surveyStep state.1 current difference,
      state.2 ++ [if fresh then 1 else 0])) (none, [])).2

def comparison (value : String) : Except String PublicationCandidates.Comparison := do
  match value.splitOn ":" with
  | [current, "none"] => return ⟨← mapping current, none⟩
  | [current, baseline] => return ⟨← mapping current, some (← mapping baseline)⟩
  | _ => throw "Expected current:baseline"

def rawSource (value : String) : Except String PublicationCandidates.RawSource := do
  match value.splitOn ":" with
  | [file, object, item] => return ⟨← natural file, ← natural object, ← mapping item⟩
  | _ => throw "Expected file:object:mapping"

def respond (words : List String) : Except String String := do
  match words with
  | ["capture", previous, current] =>
    return if PerimeterVersions.newCapture (← observation previous)
      (← observation current) then "1" else "0"
  | "collapse" :: values =>
    return observationsText (PerimeterVersions.collapse (← values.mapM observation))
  | "revisions" :: values =>
    return observationsText ((PerimeterVersions.revisionGroups
      (← values.mapM observation)).map PerimeterVersions.RevisionGroup.retained)
  | "absorb" :: current :: preferred =>
    let item ← observation current
    let choices ← preferred.mapM observation
    return match PerimeterVersions.absorb item choices with
    | none => "-1"
    | some result => observationsText result
  | "survey" :: differences :: values =>
    let matrix ← (differences.splitOn ",").mapM natural
    let count := matrix.length.sqrt
    if count * count != matrix.length then throw "Expected square difference matrix"
    return numbers (surveyFlags (← values.mapM survey)
      (fun first second => (matrix[first * count + second]?).getD 0))
  | "first" :: values =>
    return numbers (PublicationCandidates.firstCaptures (← values.mapM mapping))
  | "candidates" :: aliases :: values =>
    let pairs ← if aliases == "none" then pure [] else
      (aliases.splitOn ";").mapM pair
    let result := PublicationCandidates.candidateFold (some ⟨pairs, []⟩)
      (← values.mapM mapping)
    return match result with
    | none => "-1"
    | some state =>
      numbers (state.mappings.flatMap fun (key, item) => [key, item.identity])
  | "compare" :: threshold :: values =>
    let limit ← natural threshold
    let result := PublicationCandidates.comparisons (← values.mapM comparison)
    return match result with
    | none => "1 1 0 -1"
    | some signal => String.intercalate " "
        [if PublicationCandidates.reaches signal limit then "1" else "0", "0",
          toString signal.amount, (signal.identity.map toString).getD "-1"]
  | "raw" :: file :: object :: included :: values =>
    let result := PublicationCandidates.publishedBaseline (← values.mapM rawSource)
      (← natural file) (← natural object) (← boolean included)
    return match result with
    | none => "-1"
    | some none => "-2"
    | some (some item) => toString item.identity
  | _ => throw s!"Unknown evidence request: {words}"

end PeriScribe.EvidenceOracle

/-- Batch evaluation keeps real-code conformance inexpensive enough for local checks. -/
def main : IO UInt32 := do
  let input ← IO.getStdin
  let output ← IO.getStdout
  repeat
    let line ← input.getLine
    if line.isEmpty then break
    let words := (line.trimAscii.toString.splitOn " ").filter (· != "")
    match PeriScribe.EvidenceOracle.respond words with
    | .ok response => output.putStrLn response
    | .error message =>
      (← IO.getStderr).putStrLn message
      return 1
  return 0
