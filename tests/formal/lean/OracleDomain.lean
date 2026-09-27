import PeriScribe.AreaHistory
import PeriScribe.Grouping
import PeriScribe.Identity
import PeriScribe.SpatialIndex

namespace PeriScribe.DomainOracle

/-- Strict parsing keeps malformed conformance vectors from changing the test domain. -/
def natural (text : String) : Except String Nat :=
  match text.toNat? with
  | some value => .ok value
  | none => .error s!"Expected natural number: {text}"

def optional (text : String) : Except String (Option Nat) :=
  if text = "-1" then pure none else some <$> natural text

def numbers (text : String) : Except String (List Nat) :=
  (text.splitOn ",").mapM natural

def bitset (text : String) : Except String (List Nat) := do
  let mask ← natural text
  if mask > 3 then throw "Evidence bitset must be between 0 and 3"
  return (List.range 2).filter (fun value => mask / 2 ^ value % 2 == 1)

def edge (text : String) : Except String Grouping.Edge := do
  match ← numbers text with
  | [left, right] => return (left, right)
  | _ => throw "Expected pair of edge endpoints"

def point (text : String) : Except String SpatialIndex.Point := do
  match ← numbers text with
  | [longitude, latitude] => return ⟨longitude, latitude⟩
  | _ => throw "Expected encoded offset coordinates"

def mapping (text : String) : Except String AreaHistory.Mapping := do
  match ← numbers text with
  | [time, area, provenance, surveyed] =>
    if surveyed > 1 then throw "Survey evidence must be Boolean"
    return ⟨⟨time, area, provenance⟩, surveyed == 1⟩
  | _ => throw "Expected mapping time, acreage, source, survey flag"

def report (text : String) : Except String AreaHistory.Report := do
  match text.splitOn "," with
  | [time, area, provenance, confirmation] =>
    let confirmedAt ← if confirmation == "-2" then pure none else optional confirmation
    return ⟨⟨← natural time, ← natural area, ← natural provenance⟩, confirmedAt,
      confirmation != "-1"⟩
  | _ => throw "Expected report time, acreage, source, confirmation"

def text (values : List Nat) : String := String.intercalate " " (values.map toString)

def optionalText (value : Option Nat) : String := (value.map toString).getD "-1"

/-- The second oracle isolates domain transport from the pipeline command protocol. -/
def respond (words : List String) : Except String String := do
  match words with
  | "group" :: size :: edges =>
    let count ← natural size
    let graph ← edges.mapM edge
    if graph.any (fun edge => edge.1 ≥ count || edge.2 ≥ count) then
      throw "Grouping edges must reference supplied vertices"
    return text (Grouping.canonical count graph)
  | ["tile", coordinates] => return toString (SpatialIndex.tile (← point coordinates))
  | ["tiles", low, high] =>
    return text (SpatialIndex.tiles ⟨← point low, ← point high⟩)
  | "count" :: low :: high :: points =>
    let box := SpatialIndex.Box.mk (← point low) (← point high)
    let stored ← points.mapM point
    let contains := fun candidate => decide
      (box.minimum.longitude < candidate.longitude ∧
      candidate.longitude < box.maximum.longitude ∧
      box.minimum.latitude < candidate.latitude ∧
        candidate.latitude < box.maximum.latitude)
    return toString
      (SpatialIndex.indexedCount stored box contains (SpatialIndex.tiles box))
  | "area" :: vectors =>
    let sections := (String.intercalate " " vectors).splitOn "|"
    match sections with
    | [maps, reports] =>
      let mappings ← (maps.trimAscii.toString.splitOn " ").filter (· != "")
        |>.mapM mapping
      let reporting ← (reports.trimAscii.toString.splitOn " ").filter (· != "")
        |>.mapM report
      let estimates := AreaHistory.history mappings reporting
      return text (estimates.flatMap fun estimate =>
        [estimate.time, estimate.evidence.time, estimate.evidence.area,
          estimate.evidence.provenance, if estimate.reported then 1 else 0])
    | _ => throw "Expected mappings | reports"
  | ["identity", active, reserved, localAliases, preferredFirst, preferredSecond,
      historySignaturesFirst, historySignaturesSecond, historySourcesFirst,
      historySourcesSecond, fireSignaturesFirst, fireSignaturesSecond, fireSourcesFirst,
      fireSourcesSecond] =>
    let activeFires ← bitset active
    let aliases ← bitset localAliases
    let histories := [
      Identity.History.mk 0 [0] (← bitset historySignaturesFirst)
        (← bitset historySourcesFirst) (if aliases.contains 0 then [0] else []),
      Identity.History.mk 1 [0] (← bitset historySignaturesSecond)
        (← bitset historySourcesSecond) (if aliases.contains 1 then [0] else [])]
    let first := Identity.Fire.mk 0 0 (← bitset fireSignaturesFirst)
      (← bitset fireSourcesFirst) (← optional preferredFirst)
    let second := Identity.Fire.mk 1 0 (← bitset fireSignaturesSecond)
      (← bitset fireSourcesSecond) (← optional preferredSecond)
    let reservedKeys ← bitset reserved
    let options := fun identifier => Identity.candidates histories reservedKeys
      (if identifier == 0 then first else second)
    return String.intercalate " " (([0, 1] : List Nat).map
      (fun identifier => optionalText (if activeFires.contains identifier then
        Identity.uniqueOwner activeFires options identifier else none)))
  | ["stable", first, second] =>
    let firstKey ← optional first
    let secondKey ← optional second
    return optionalText (Identity.stable [0, 1]
      (fun identifier => if identifier == 0 then firstKey else secondKey))
  | _ => throw s!"Unknown domain request: {words}"

end PeriScribe.DomainOracle

/-- One process handles batches so exhaustive finite conformance stays inexpensive. -/
def main : IO UInt32 := do
  let input ← IO.getStdin
  let output ← IO.getStdout
  repeat
    let line ← input.getLine
    if line.isEmpty then break
    match PeriScribe.DomainOracle.respond (line.trimAscii.toString.splitOn " ") with
    | .ok response => output.putStrLn response
    | .error message =>
      (← IO.getStderr).putStrLn message
      return 1
  return 0
