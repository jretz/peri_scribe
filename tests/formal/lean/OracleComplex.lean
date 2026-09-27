import PeriScribe.ComplexOwnership

namespace PeriScribe.ComplexOracle

open ComplexOwnership

def natural (text : String) : Except String Nat :=
  match text.toNat? with
  | some value => pure value
  | none => .error s!"Expected natural number: {text}"

def alias (text : String) : Except String (Option Nat) :=
  if text = "n" then pure none else some <$> natural text

def values (text : String) :=
  text.trimAscii.toString.splitOn " " |>.filter (· != "")

def observation (text : String) : Except String Observation := do
  match text.splitOn "," with
  | [child, parent, time, priority, serial] =>
    return ⟨← natural child, ← alias parent, ← natural time,
      ← natural priority, ← natural serial⟩
  | _ => throw "Expected child,parent,time,priority,serial observation"

def parentNumber : Parent → Nat
  | .known fire => fire * 2
  | .external identifier => identifier * 2 + 1

def output (value : Nat) : String := toString value

def respond (line : String) : Except String String := do
  match line.splitOn "|" with
  | [header, rawAliases, rawMemberships] =>
    match values header with
    | ["resolve", count] =>
      let fires := List.range (← natural count)
      let aliases ← (values rawAliases).mapM alias
      let aliases : Aliases := fun identifier => (aliases[identifier]?).getD none
      let observations ← (values rawMemberships).mapM observation
      let parents := (historicalParents aliases observations).eraseDups.mergeSort
        (fun first second => parentNumber first ≤ parentNumber second)
      let owners := fires.map (fun fire =>
        match currentOwner aliases observations (fires.length + 1) fire with
        | none => "-1"
        | some parent => output (parentNumber parent))
      let surviving := currentVisible aliases observations fires
      let forward := parents.flatMap (fun parent =>
        let children := currentMembers aliases observations fires parent
        [parentNumber parent, children.length] ++ children)
      return String.intercalate " " (owners ++
        (surviving.length :: surviving ++ parents.length :: forward).map output)
    | _ => throw "Expected resolve header"
  | _ => throw "Expected aliases and memberships sections"

end PeriScribe.ComplexOracle

/-- Executable transport shares every ownership decision with the proved definitions. -/
def main : IO UInt32 := do
  let input ← IO.getStdin
  let output ← IO.getStdout
  repeat
    let line ← input.getLine
    if line.isEmpty then break
    match PeriScribe.ComplexOracle.respond line.trimAscii.toString with
    | .ok response => output.putStrLn response
    | .error message =>
      (← IO.getStderr).putStrLn message
      return 1
  return 0
