namespace PeriScribe.CacheCodec

/-- Scalar payloads retain exact bytes; tags distinguish scalar and container kinds. -/
inductive Value where
  | scalar (tag : Nat) (payload : List Nat)
  | empty (tag : Nat)
  | branch (tag : Nat) (head tail : Value)
  deriving DecidableEq, Repr

inductive Token where
  | scalar (tag : Nat) (payload : List Nat)
  | empty (tag : Nat)
  | branch (tag : Nat)
  deriving DecidableEq, Repr

def encode : Value → List Token
  | .scalar tag payload => [.scalar tag payload]
  | .empty tag => [.empty tag]
  | .branch tag head tail => .branch tag :: encode head ++ encode tail

def depth : Value → Nat
  | .scalar .. | .empty .. => 1
  | .branch _ head tail => 1 + max (depth head) (depth tail)

/-- Fuel bounds parsing work; a branch must contain two complete encoded children. -/
def decode : Nat → List Token → Option (Value × List Token)
  | 0, _ => none
  | _ + 1, [] => none
  | _ + 1, .scalar tag payload :: rest => some (.scalar tag payload, rest)
  | _ + 1, .empty tag :: rest => some (.empty tag, rest)
  | fuel + 1, .branch tag :: rest => do
      let (head, remaining) ← decode fuel rest
      let (tail, suffix) ← decode fuel remaining
      return (.branch tag head tail, suffix)

theorem decode_encode_suffix (value : Value) (suffix : List Token) (fuel : Nat)
    (enough : depth value ≤ fuel) :
    decode fuel (encode value ++ suffix) = some (value, suffix) := by
  induction value generalizing fuel suffix with
  | scalar tag payload =>
    cases fuel with
    | zero => simp [depth] at enough
    | succ fuel => rfl
  | empty tag =>
    cases fuel with
    | zero => simp [depth] at enough
    | succ fuel => rfl
  | branch tag head tail headProof tailProof =>
    cases fuel with
    | zero => simp [depth] at enough
    | succ fuel =>
      have headEnough : depth head ≤ fuel := by simp [depth] at enough; omega
      have tailEnough : depth tail ≤ fuel := by simp [depth] at enough; omega
      simp only [encode, List.cons_append, List.append_assoc, decode]
      rw [headProof (encode tail ++ suffix) fuel headEnough]
      simp only [bind, Option.bind]
      rw [tailProof suffix fuel tailEnough]
      rfl

theorem round_trip (value : Value) :
    decode (depth value) (encode value) = some (value, []) := by
  simpa using decode_encode_suffix value [] (depth value) (by omega)

theorem encoding_injective (first second : Value)
    (same : encode first = encode second) : first = second := by
  let fuel := max (depth first) (depth second)
  have one := decode_encode_suffix first [] fuel (Nat.le_max_left ..)
  have two := decode_encode_suffix second [] fuel (Nat.le_max_right ..)
  rw [same] at one
  rw [two] at one
  exact (congrArg Prod.fst (Option.some.inj one)).symm

theorem equal_encoding_iff (first second : Value) :
    encode first = encode second ↔ first = second :=
  ⟨encoding_injective first second, fun same => congrArg encode same⟩

theorem scalar_types_distinct (first second : Nat) (left right : List Nat)
    (different : first ≠ second) :
    encode (.scalar first left) ≠ encode (.scalar second right) := by
  simp [encode, different]

theorem exact_payload_distinct (tag : Nat) (left right : List Nat)
    (different : left ≠ right) :
    encode (.scalar tag left) ≠ encode (.scalar tag right) := by
  simp [encode, different]

theorem scalar_and_container_distinct (tag other : Nat) (payload : List Nat) :
    encode (.scalar tag payload) ≠ encode (.empty other) := by simp [encode]

theorem ordered_children_preserved (tag : Nat) (a b c d : Value)
    (same : encode (.branch tag a b) = encode (.branch tag c d)) :
    a = c ∧ b = d := by
  have result := encoding_injective _ _ same
  simpa using result

theorem swapping_distinct_children_changes_encoding (tag : Nat) (a b : Value)
    (different : a ≠ b) :
    encode (.branch tag a b) ≠ encode (.branch tag b a) := by
  intro same
  exact different (ordered_children_preserved tag a b b a same).1

/-- Accepted payloads cannot hide trailing fields after a complete root. -/
def read (tokens : List Token) : Option Value := do
  let (value, suffix) ← decode tokens.length tokens
  if suffix.isEmpty then some value else none

theorem depth_le_length (value : Value) : depth value ≤ (encode value).length := by
  induction value with
  | scalar tag payload => simp [depth, encode]
  | empty tag => simp [depth, encode]
  | branch tag head tail ihHead ihTail =>
    simp [depth, encode]
    omega

theorem complete_round_trip (value : Value) : read (encode value) = some value := by
  have parsed : decode (encode value).length (encode value) = some (value, []) := by
    simpa using decode_encode_suffix value [] (encode value).length
      (depth_le_length value)
  simp [read, parsed]

theorem decode_sound (fuel : Nat) (tokens suffix : List Token) (value : Value)
    (parsed : decode fuel tokens = some (value, suffix)) :
    tokens = encode value ++ suffix := by
  induction fuel generalizing tokens suffix value with
  | zero => simp [decode] at parsed
  | succ fuel ih =>
    cases tokens with
    | nil => simp [decode] at parsed
    | cons token rest =>
      cases token with
      | scalar tag payload =>
        simp only [decode, Option.some.injEq, Prod.mk.injEq] at parsed
        obtain ⟨rfl, rfl⟩ := parsed
        rfl
      | empty tag =>
        simp only [decode, Option.some.injEq, Prod.mk.injEq] at parsed
        obtain ⟨rfl, rfl⟩ := parsed
        rfl
      | branch tag =>
        cases first : decode fuel rest with
        | none => simp [decode, first, bind, Option.bind] at parsed
        | some pair =>
          obtain ⟨head, remaining⟩ := pair
          cases second : decode fuel remaining with
          | none => simp [decode, first, second, bind, Option.bind] at parsed
          | some pair =>
            obtain ⟨tail, ending⟩ := pair
            simp only [decode, first, second, bind, Option.bind, pure,
              Option.some.injEq, Prod.mk.injEq] at parsed
            obtain ⟨rfl, rfl⟩ := parsed
            rw [ih rest remaining head first, ih remaining ending tail second]
            simp [encode, List.append_assoc]

theorem accepted_is_canonical (tokens : List Token) (value : Value)
    (accepted : read tokens = some value) : tokens = encode value := by
  unfold read at accepted
  cases parsed : decode tokens.length tokens with
  | none => simp [parsed, bind, Option.bind] at accepted
  | some pair =>
    obtain ⟨result, suffix⟩ := pair
    simp only [parsed, bind, Option.bind] at accepted
    split at accepted
    next empty =>
      have absent : suffix = [] := List.isEmpty_iff.mp empty
      simp only [Option.some.injEq] at accepted
      subst result
      simpa [absent] using decode_sound tokens.length tokens suffix value parsed
    next => contradiction

theorem appended_trailing_tokens_rejected (value : Value) (extra : List Token)
    (nonempty : extra ≠ []) : read (encode value ++ extra) ≠ some value := by
  intro accepted
  have same := accepted_is_canonical _ _ accepted
  have lengths := congrArg List.length same
  simp only [List.length_append] at lengths
  have : extra.length = 0 := by omega
  exact nonempty (List.length_eq_zero_iff.mp this)

end PeriScribe.CacheCodec
