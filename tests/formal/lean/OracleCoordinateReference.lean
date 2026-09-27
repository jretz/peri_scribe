import PeriScribe.CoordinateReference

open PeriScribe.CoordinateReference

def numbers (text : String) : Except String (List Int) :=
  (text.splitOn " " |>.filter (· != "")).mapM fun value =>
    match value.toInt? with
    | some number => pure number
    | none => .error s!"Expected integer: {value}"

def candidate (bounds : List Int) (text : String) : Except String Candidate := do
  match ← numbers text with
  | [key, known, geographic, minimumX, maximumX, minimumY, maximumY,
      areaKnown, west, east, south, north] =>
    match bounds with
    | [lowX, highX, lowY, highY] =>
      let domain := axisFits lowX highX minimumX maximumX &&
        axisFits lowY highY minimumY maximumY
      let area := longitudesFit west east lowX highX &&
        decide (south ≤ lowY ∧ highY ≤ north)
      let kind := classify (known != 0) domain (geographic != 0)
        (areaKnown == 0 || area)
      return ⟨key.toNat, kind⟩
    | [] => return ⟨key.toNat, .excluded⟩
    | _ => throw "Expected four coordinate bounds"
  | _ => throw "Expected reference identity, domain, and area metadata"

def respond (line : String) : Except String (List Int) := do
  match line.splitOn "|" with
  | ["axis", arguments] =>
    match ← numbers arguments with
    | [low, high, minimum, maximum] =>
      return [if axisFits low high minimum maximum then 1 else 0]
    | _ => throw "Expected four axis bounds"
  | ["longitude", arguments] =>
    match ← numbers arguments with
    | [west, east, low, high] =>
      return [if longitudesFit west east low high then 1 else 0]
    | _ => throw "Expected area and observed longitude bounds"
  | "selection" :: arguments :: references =>
    let bounds ← numbers arguments
    let candidates ← references.mapM (candidate bounds)
    let chosen := select (!bounds.isEmpty) candidates
    return (chosen.map Int.ofNat).getD (-1) :: candidates.map (fun item =>
      match item.kind with | .excluded => 0 | .outside => 1 | .matching => 2)
  | _ => throw "Expected axis, longitude, or selection"

def main : IO UInt32 := do
  let input ← IO.getStdin
  let output ← IO.getStdout
  repeat
    let line ← input.getLine
    if line.isEmpty then break
    match respond line.trimAscii.toString with
    | .ok response => output.putStrLn (String.intercalate " " (response.map toString))
    | .error message =>
      (← IO.getStderr).putStrLn message
      return 1
  return 0
