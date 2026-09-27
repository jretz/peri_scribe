import PeriScribe.IdentityRecomputation

open PeriScribe.IdentityTransfer PeriScribe.IdentityRecomputation

namespace PeriScribe.IdentityRecomputationOracle

def numbers (text : String) : Except String (List Nat) :=
  (text.splitOn " " |>.filter (· != "")).mapM fun word =>
    match word.toNat? with
    | some value => pure value
    | none => throw s!"Expected natural token: {word}"

def pairs : List Nat → Except String (List (Nat × Nat))
  | [] => pure []
  | first :: second :: rest => return (first, second) :: (← pairs rest)
  | _ => throw "Expected paired tokens"

def lookup (entries : List (Nat × Nat)) (key : Nat) : Option Nat :=
  (entries.find? (fun entry => entry.1 == key)).map Prod.snd

def grouped (entries : List (Nat × Nat)) (key : Nat) : List Nat :=
  (entries.filter (fun entry => entry.1 == key)).map Prod.snd

def packed (values : List Nat) : List Nat :=
  let canonical := values.eraseDups.mergeSort
  canonical.length :: canonical

def fires : List Nat → Except String (List Fire)
  | [] => pure []
  | identity :: dated :: time :: rest =>
    return ⟨identity, if dated = 0 then none else some (Int.ofNat time), [], []⟩ ::
      (← fires rest)
  | _ => throw "Expected identity, dated flag, time triples"

def respond (line : String) : Except String (List Nat) := do
  match line.splitOn "|" with
  | [rawCount, rawHistories, rawFires, rawRoutes, rawPreferred, rawOwners,
      rawFresh, rawEvidence, rawSurveys, rawQueries] =>
    let [count] ← numbers rawCount | throw "Expected one repetition count"
    let histories ← numbers rawHistories
    let current ← fires (← numbers rawFires)
    let routes ← pairs (← numbers rawRoutes)
    let preferred ← pairs (← numbers rawPreferred)
    let owners ← pairs (← numbers rawOwners)
    let fresh ← pairs (← numbers rawFresh)
    let previous ← pairs (← numbers rawEvidence)
    let surveys ← pairs (← numbers rawSurveys)
    let queries ← numbers rawQueries
    let input : Feedback := ⟨current, histories, grouped routes, lookup preferred,
      fun history => (lookup owners history).getD history,
      fun fire => (lookup fresh fire).getD
        (freshAbove (histories ++ fresh.map Prod.snd) fire)⟩
    let state := materializedRepetitions input count
    let result := materializedRetry state
    let first := materializedRetry input
    let acknowledged := acknowledgedRecords previous (recordsWithWriters current
      (fun fire => (first.preferred fire).getD 0) (grouped surveys))
    let repeated := acknowledgedRecords acknowledged (recordsWithWriters current
      (fun fire => (result.preferred fire).getD 0) (grouped surveys))
    return current.map (fun fire => (result.preferred fire.identity).getD 0) ++
      queries.map result.previous ++
      current.flatMap (fun fire => packed (result.routes fire.identity)) ++
      queries.flatMap (fun history => packed (grouped repeated history)) ++
      current.map (fun fire => if novel (fun history => some (result.previous history))
        repeated ((result.preferred fire.identity).getD 0)
          (grouped surveys fire.identity)
        then 1 else 0)
  | _ => throw "Expected complete feedback input"

end PeriScribe.IdentityRecomputationOracle

def main : IO UInt32 := do
  let input ← IO.getStdin
  let output ← IO.getStdout
  repeat
    let line ← input.getLine
    if line.isEmpty then break
    match PeriScribe.IdentityRecomputationOracle.respond line.trimAscii.toString with
    | .ok response => output.putStrLn (String.intercalate " " (response.map toString))
    | .error message =>
      (← IO.getStderr).putStrLn message
      return 1
  return 0
