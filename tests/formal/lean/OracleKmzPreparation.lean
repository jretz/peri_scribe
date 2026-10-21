import PeriScribe.KmzPreparation

namespace PeriScribe.KmzPreparationOracle

def natural (text : String) : Except String Nat :=
  match text.toNat? with
  | some value => pure value
  | none => throw s!"Expected natural number: {text}"

def numbers (text : String) : Except String (List Nat) :=
  (text.splitOn "," |>.filter (· != "")).mapM natural

def identity (text : String) : Except String KmzPreparation.Identity := do
  match ← numbers text with
  | [full, differential, index, threshold, policy, runtime] =>
    return ⟨full, differential, index, threshold, policy, runtime⟩
  | _ => throw "Expected six dependency tokens"

def history (text : String) : Except String KmzPreparation.History := do
  match ← numbers text with
  | [key, payload, qualifies] => return ⟨key, payload, qualifies != 0⟩
  | _ => throw "Expected key,payload,qualification"

def render (values : List Nat) : String := String.intercalate " " (values.map toString)

def respond (line : String) : Except String String := do
  match line.splitOn "|" with
  | ["identity", stored, current] =>
    return render [if KmzPreparation.identityMatches (← identity stored)
      (← identity current) then 1 else 0]
  | ["demands", groups] =>
    return render (KmzPreparation.demands (← (groups.splitOn ";").mapM numbers))
  | ["projection", values, groups] =>
    let rows ← numbers values
    let positions := KmzPreparation.demands (← (groups.splitOn ";").mapM numbers)
    let projected := rows.zipIdx |>.map fun (value, position) =>
      (KmzPreparation.projectedValue (fun offset => (rows[offset]?).getD value)
        positions position).getD 0
    return render projected
  | ["qualifying", entries] =>
    let rows ← (entries.splitOn ";" |>.filter (· != "")).mapM history
    return render ((KmzPreparation.qualifyingHistories rows).flatMap fun row =>
      [row.key, row.payload])
  | _ => throw "Expected KMZ preparation operation and inputs"

end PeriScribe.KmzPreparationOracle

def main : IO UInt32 := do
  let input ← IO.getStdin
  let output ← IO.getStdout
  repeat
    let line ← input.getLine
    if line.isEmpty then break
    match PeriScribe.KmzPreparationOracle.respond line.trimAscii.toString with
    | .ok result => output.putStrLn result
    | .error message =>
      (← IO.getStderr).putStrLn message
      return 1
  return 0
