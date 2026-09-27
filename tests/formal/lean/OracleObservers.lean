import PeriScribe.BuildingCentroids
import PeriScribe.MonitorReconstruction

namespace PeriScribe.ObserverOracle

def natural (text : String) : Except String Nat :=
  match text.toNat? with
  | some value => pure value
  | none => throw s!"Expected natural number: {text}"

def integer (text : String) : Except String Int :=
  match text.toInt? with
  | some value => pure value
  | none => throw s!"Expected integer: {text}"

def point (text : String) : Except String BuildingCentroids.Point := do
  match text.splitOn "," with
  | [x, y] => return ⟨← integer x, ← integer y⟩
  | _ => throw "Expected x,y"

def ring (text : String) : Except String BuildingCentroids.Moment := do
  return BuildingCentroids.ring (← (text.splitOn ";").mapM point)

def polygon (text : String) : Except String BuildingCentroids.Moment := do
  return BuildingCentroids.polygon (← (text.splitOn "|").mapM ring)

def feature (text : String) : Except String BuildingCentroids.Feature := do
  match text.splitOn "," with
  | [identifier, vertices, supported] =>
    return ⟨← natural identifier, ← natural vertices, (← natural supported) != 0⟩
  | _ => throw "Expected identifier,vertices,supported"

def kind (text : String) : Except String MonitorReconstruction.Kind := do
  match ← natural text with
  | 0 => return .commandStart
  | 1 => return .phaseStart
  | 2 => return .phaseFinish
  | 3 => return .commandFinish
  | 4 => return .ordinary
  | 5 => return .skipped
  | 6 => return .planned
  | _ => throw "Expected event kind 0..6"

def kindCode : MonitorReconstruction.Kind → Nat
  | .commandStart => 0
  | .phaseStart => 1
  | .phaseFinish => 2
  | .commandFinish => 3
  | .ordinary => 4
  | .skipped => 5
  | .planned => 6

def status (text : String) : Except String MonitorReconstruction.Status := do
  match ← natural text with
  | 0 => return .waiting
  | 1 => return .active
  | 2 => return .completed
  | 3 => return .failed
  | 4 => return .stopped
  | _ => throw "Expected status 0..4"

def statusCode : MonitorReconstruction.Status → Nat
  | .waiting => 0
  | .active => 1
  | .completed => 2
  | .failed => 3
  | .stopped => 4

def path (text : String) : Except String MonitorReconstruction.Path :=
  if text = "_" then pure [] else (text.splitOn ":").mapM natural

def event (text : String) : Except String MonitorReconstruction.Event := do
  match text.splitOn "," with
  | [owner, eventKind, failed, explicit, phase] =>
    return ⟨← natural owner, ← kind eventKind,
      ← (if explicit = "-" then pure none else some <$> path explicit),
      ← (if phase = "-" then pure none else some <$> natural phase),
      (← natural failed) != 0⟩
  | _ => throw "Expected owner,kind,failed,explicit,phase"

def observation (text : String) :
    Except String (MonitorReconstruction.Kind × MonitorReconstruction.Path × Bool) := do
  match text.splitOn "," with
  | [eventKind, observed, failed] =>
    return (← kind eventKind, ← path observed, (← natural failed) != 0)
  | _ => throw "Expected kind,path,failed"

def naturalText (values : List Nat) : String :=
  String.intercalate " " (values.map toString)

def observedPaths (state : MonitorReconstruction.State) :
    List MonitorReconstruction.Event → List Nat
  | [] => []
  | first :: rest =>
    let observed := MonitorReconstruction.eventPath (state first.owner) first
    observed.length :: observed ++
      observedPaths (MonitorReconstruction.step state first) rest

def respond (words : List String) : Except String String := do
  match words with
  | "centroid" :: polygons =>
    let result := BuildingCentroids.sum (← polygons.mapM polygon)
    let vertices ← polygons.flatMapM fun shape =>
      (shape.splitOn "|").flatMapM fun ring => (ring.splitOn ";").mapM point
    let (x, y, denominator) := BuildingCentroids.centroidRatio result vertices
    return s!"{result.area} {x} {y} {denominator}"
  | "chunks" :: limit :: budget :: features =>
    let chunks := BuildingCentroids.chunks (← natural limit) (← natural budget)
      (BuildingCentroids.accepted (← features.mapM feature))
    return String.intercalate " " (chunks.flatMap fun chunk =>
      toString chunk.length ::
        chunk.map (toString ∘ BuildingCentroids.Feature.identifier))
  | "runs" :: owner :: events =>
    let result := MonitorReconstruction.process (fun _ => {}) (← events.mapM event)
      (← natural owner)
    return naturalText (statusCode result.status :: result.path.length :: result.path)
  | "paths" :: events =>
    return naturalText (observedPaths (fun _ => {}) (← events.mapM event))
  | "phase" :: run :: selected :: observations =>
    let result := MonitorReconstruction.phaseStatus (← path selected)
      (← observations.mapM observation)
    return naturalText [statusCode result,
      statusCode (MonitorReconstruction.displayed (← status run) result)]
  | "omission" :: run :: explicit :: parents =>
    return toString (MonitorReconstruction.omission (← status run)
      ((← natural explicit) != 0) (← parents.mapM status))
  | "retain" :: limit :: observations =>
    return naturalText ((MonitorReconstruction.retained (← natural limit)
      (← observations.mapM observation)).flatMap fun (kind, path, failed) =>
        [kindCode kind, if failed then 1 else 0, path.length] ++ path)
  | "retained-runs" :: limit :: owners =>
    return naturalText (MonitorReconstruction.retainedRuns (← natural limit)
      (← owners.mapM natural))
  | _ => throw s!"Unknown observer request: {words}"

end PeriScribe.ObserverOracle

/-- Execute the same definitions used by the centroid and monitor proofs. -/
def main : IO UInt32 := do
  let input ← IO.getStdin
  let output ← IO.getStdout
  repeat
    let line ← input.getLine
    if line.isEmpty then break
    match PeriScribe.ObserverOracle.respond (line.trimAscii.toString.splitOn " ") with
    | .ok response => output.putStrLn response
    | .error message =>
      (← IO.getStderr).putStrLn message
      return 1
  return 0
