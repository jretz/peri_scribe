import PeriScribe.PerimeterComposition
import PeriScribe.BorderClassification

namespace PeriScribe.PerimeterOracle

def natural (value : String) : Except String Nat :=
  match value.toNat? with
  | some result => pure result
  | none => throw s!"Expected natural: {value}"

def optional (value : String) : Except String (Option Nat) :=
  if value = "-1" then pure none else some <$> natural value

def boolean (value : String) : Except String Bool :=
  if value = "0" then pure false
  else if value = "1" then pure true else throw "Expected Boolean"

def numbers (values : List Nat) : String :=
  String.intercalate " " (values.map toString)

def bits (values : List Nat) : Nat :=
  values.eraseDups.foldl (fun result value => result + 2 ^ value) 0

def entry (value : String) : Except String PerimeterComposition.Entry := do
  match value.splitOn "," with
  | [identity, time, published, serial, object, feed, source, category, start, width,
      capture, sameYear, flight, ancestors, measured, computed, incident, first, second,
      third, primarySource, secondarySource, primaryCategory, secondaryCategory,
      policyCapture] =>
    let mask ← natural ancestors
    let observation : PerimeterVersions.Observation :=
      ⟨← natural identity, ← natural time, ← natural published, ← natural serial,
        ← natural object, ← natural feed, ← natural source, ← natural category,
        ← natural start, ← natural width, ← optional capture, ← boolean sameYear,
        ← boolean flight,
        (List.range 32).filter (fun value => mask / 2 ^ value % 2 == 1)⟩
    let attributes ← [computed, incident, first, second, third].mapM optional
    let capture ← if policyCapture = "-1" then pure none
      else if policyCapture = "-2" then pure (some (none, true))
      else pure (some (some (← natural policyCapture), ← boolean sameYear))
    let policy : PerimeterComposition.Policy :=
      ⟨← optional primarySource, ← optional secondarySource,
        ← optional primaryCategory, ← optional secondaryCategory, capture⟩
    return PerimeterComposition.normalized
      ⟨observation, fun key => (attributes[key]?).getD none, ← natural measured, policy⟩
  | _ => throw "Expected complete perimeter entry"

def entriesText (entries : List PerimeterComposition.Entry) : String :=
  String.intercalate " " (entries.flatMap fun value =>
    [toString value.observation.identity, toString value.observation.time,
      toString (bits (PerimeterComposition.lineage value))] ++
      (List.range 5).map (fun key => ((value.attributes key).map toString).getD "-1") ++
      [value.policy.source, value.policy.sourceAlias, value.policy.category,
        value.policy.categoryAlias].map (fun value => (value.map toString).getD "-1") ++
      (match value.policy.capture with
      | none => ["-1", "1"]
      | some (none, _) => ["-2", "1"]
      | some (some time, sameYear) => [toString time, if sameYear then "1" else "0"]))

def footprint (value : String) : Except String (List Nat) :=
  if value = "none" then pure [] else (value.splitOn ",").mapM natural

def extentEntry (value : String) : Except String BorderClassification.Extent := do
  match value.splitOn "," with
  | [time, serial, area, shape] =>
    return ⟨← optional time, ← natural serial, ← natural area, ← natural shape⟩
  | _ => throw "Expected extent observation"

def extentList (value : String) : Except String (List BorderClassification.Extent) :=
  if value = "none" then pure [] else (value.splitOn ";").mapM extentEntry

def respond (words : List String) : Except String String := do
  match words with
  | "compose" :: preferred :: values =>
    return entriesText (PerimeterComposition.reconcile (← natural preferred)
      (← values.mapM entry))
  | "reconciled" :: preferred :: values =>
    return entriesText (PerimeterComposition.reconciled (← natural preferred)
      (← values.mapM entry))
  | ["classify", crosses, near, inside, extent, identifier] =>
    let geometry := BorderClassification.Geometry.mk
      (← boolean crosses) (← boolean near) (← boolean inside)
    let extent ← boolean extent
    let identifier ← boolean identifier
    let classification := BorderClassification.classify geometry extent
    return numbers [classification,
      bits (BorderClassification.evidence geometry extent identifier),
      if BorderClassification.preferWfigs classification then 1 else 0]
  | ["geometry", total, inside, distance, buffer, fraction, absolute, majority] =>
    let geometry := BorderClassification.geometry (← natural total) (← natural inside)
      (← natural distance) (← natural buffer) (← natural fraction) (← natural absolute)
      (← natural majority)
    return numbers [if geometry.crosses then 1 else 0, if geometry.near then 1 else 0,
      if geometry.inside then 1 else 0]
  | "union" :: parts =>
    let cells := BorderClassification.unionCells (← parts.mapM footprint)
    return numbers cells.mergeSort
  | ["extent", first, second, differences, tolerance, ratio, symmetric] =>
    let matrix ← (differences.splitOn ",").mapM natural
    let count := matrix.length.sqrt
    if count * count != matrix.length then throw "Expected square difference matrix"
    return if BorderClassification.extent (← extentList first) (← extentList second)
      (fun first second => (matrix[first * count + second]?).getD 0)
      (← natural tolerance) (← natural ratio) (← natural symmetric) then "1" else "0"
  | _ => throw s!"Unknown perimeter request: {words}"

end PeriScribe.PerimeterOracle

def main : IO UInt32 := do
  let input ← IO.getStdin
  let output ← IO.getStdout
  repeat
    let line ← input.getLine
    if line.isEmpty then break
    let words := (line.trimAscii.toString.splitOn " ").filter (· != "")
    match PeriScribe.PerimeterOracle.respond words with
    | .ok response => output.putStrLn response
    | .error message =>
      (← IO.getStderr).putStrLn message
      return 1
  return 0
