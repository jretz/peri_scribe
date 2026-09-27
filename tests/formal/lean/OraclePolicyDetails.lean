import PeriScribe.NotableViews
import PeriScribe.ChartEvidence

namespace PeriScribe.PolicyDetailsOracle

def integer (text : String) : Except String Int :=
  match text.toInt? with
  | some value => pure value
  | none => throw s!"Invalid integer: {text}"

def natural (text : String) : Except String Nat :=
  match text.toNat? with
  | some value => pure value
  | none => throw s!"Invalid natural: {text}"

def optional (text : String) : Except String (Option Int) :=
  if text = "n" then pure none else some <$> integer text

def boolean (text : String) : Except String Bool :=
  match text with
  | "0" => pure false
  | "1" => pure true
  | _ => throw s!"Invalid Boolean: {text}"

def words (text : String) : List String :=
  text.trimAscii.toString.splitOn " " |>.filter (· != "")

def fire (text : String) : Except String NotableViews.Fire := do
  match text.splitOn "," with
  | owner :: name :: active :: time :: identifiers =>
    return ⟨⟨← natural owner, ← natural name, ← identifiers.mapM natural⟩,
      ← boolean active, ← optional time⟩
  | _ => throw "Expected owner,name,active,time,identifiers"

def score (text : String) : Except String NotableViews.Score := do
  match text.splitOn "," with
  | [identifier, name, value, serial, area, buildings, evacuation] =>
    return ⟨⟨← if identifier = "n" then pure none else some <$> natural identifier,
      ← natural name, ← integer value, ← natural serial⟩,
      ← optional area, ← optional buildings, ← boolean evacuation⟩
  | _ => throw "Expected identifier,name,score,serial,area,buildings,evacuation"

def measurement (text : String) : Except String (Int × Int) := do
  match text.splitOn "," with
  | [time, value] => return (← integer time, ← integer value)
  | _ => throw "Expected time,value"

def point (text : String) : Except String ChartEvidence.Point := do
  match text.splitOn "," with
  | [identity, time, value, style] =>
    return ⟨← natural identity, ← integer time, ← integer value, ← boolean style⟩
  | _ => throw "Expected identity,time,value,style"

def numbers (values : List Int) : String := String.intercalate " " (values.map toString)

def segmentNumbers (segment : ChartEvidence.Segment) : List Int :=
  let points : List Nat := match segment.edges with
    | [] => []
    | first :: _ => first.first.identity :: segment.edges.map (fun edge =>
      edge.second.identity)
  (if segment.dashed then 1 else 0) :: Int.ofNat points.length :: points.map Int.ofNat

def respond (line : String) : Except String String := do
  match line.splitOn "|" with
  | [header, first, second] =>
    match words header with
    | ["notable", now] =>
      let fires ← (words first).mapM fire
      let scores ← (words second).mapM score
      let resolved := NotableViews.resolved fires scores
      let selected := NotableViews.complete (← optional now) fires scores
      return numbers ((NotableViews.threshold resolved).getD (-99999999) ::
        Int.ofNat (NotableViews.activeScores resolved).length ::
        Int.ofNat (NotableViews.topCount (NotableViews.activeScores resolved).length) ::
        selected.flatMap (fun row => [Int.ofNat row.owner, Int.ofNat row.serial]))
    | ["estimates"] =>
      let lengths ← (words first).mapM measurement
      let percents ← (words second).mapM measurement
      return numbers ((ChartEvidence.estimates lengths percents).flatMap fun row =>
        [row.time, row.length, row.percent])
    | _ => throw "Invalid three-section request"
  | [header, content] =>
    match words header with
    | ["segments"] =>
      let points ← (words content).mapM point
      let segments := ChartEvidence.segments points
      let legend := ChartEvidence.legend points
      return numbers (Int.ofNat segments.length :: segments.flatMap segmentNumbers ++
        Int.ofNat legend.length :: legend.map (fun style => if style then 1 else 0))
    | _ => throw "Invalid two-section request"
  | _ => throw "Invalid policy-details request"

end PeriScribe.PolicyDetailsOracle

def main : IO UInt32 := do
  let input ← IO.getStdin
  let output ← IO.getStdout
  repeat
    let line ← input.getLine
    if line.isEmpty then break
    match PeriScribe.PolicyDetailsOracle.respond line.trimAscii.toString with
    | .ok result => output.putStrLn result
    | .error message =>
      (← IO.getStderr).putStrLn message
      return 1
  return 0
