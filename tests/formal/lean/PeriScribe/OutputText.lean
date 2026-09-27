import Std

namespace PeriScribe.OutputText

def scalar (value : Nat) : Bool :=
  value == 9 || value == 10 || value == 13 ||
    (32 ≤ value && value ≤ 55295) || (57344 ≤ value && value ≤ 65533) ||
    (65536 ≤ value && value ≤ 1114111)

def clean (value : Nat) : Nat :=
  if value == 133 then 10 else if scalar value then value else 65533

def normalize : List Nat → List Nat
  | [] => []
  | 13 :: 10 :: rest => 10 :: normalize rest
  | 13 :: rest => 10 :: normalize rest
  | value :: rest => clean value :: normalize rest

theorem clean_is_valid (value : Nat) : scalar (clean value) = true := by
  unfold clean
  split
  · decide
  · split
    · assumption
    · decide

theorem clean_does_not_keep_next_line (value : Nat) : clean value ≠ 133 := by
  unfold clean
  split
  · decide
  · split
    · rename_i different _valid
      simpa using different
    · decide

theorem clean_does_not_create_carriage_return (value : Nat) (notReturn : value ≠ 13) :
    clean value ≠ 13 := by
  unfold clean
  split
  · decide
  · split
    · exact notReturn
    · decide

theorem normalization_has_only_valid_nonreturn_scalars (values : List Nat) :
    ∀ value ∈ normalize values, scalar value = true ∧ value ≠ 13 ∧ value ≠ 133 := by
  induction values using normalize.induct with
  | case1 => simp [normalize]
  | case2 rest induction =>
    simpa [normalize, scalar] using induction
  | case3 rest notLinefeed induction =>
    intro value member
    have step : normalize (13 :: rest) = 10 :: normalize rest := by
      cases rest with
      | nil => rfl
      | cons first tail =>
        have different : first ≠ 10 := by
          intro same
          exact notLinefeed tail (by simp [same])
        simp [normalize]
    rw [step] at member
    rcases List.mem_cons.mp member with same | later
    · subst value
      decide
    · exact induction value later
  | case4 value rest _notBoth notReturn induction =>
    intro found member
    simp only [normalize] at member
    rcases List.mem_cons.mp member with same | later
    · subst found
      exact ⟨clean_is_valid value, clean_does_not_create_carriage_return value notReturn,
        clean_does_not_keep_next_line value⟩
    · exact induction found later

theorem normalization_preserves_supported_text (values : List Nat)
    (supported : ∀ value ∈ values, scalar value = true ∧ value ≠ 13 ∧ value ≠ 133) :
    normalize values = values := by
  induction values with
  | nil => rfl
  | cons value rest induction =>
    have first := supported value (by simp)
    have later := induction (fun item member => supported item (by simp [member]))
    simp [normalize, first.2.1, clean, first.1, first.2.2, later]

theorem normalization_is_idempotent (values : List Nat) :
    normalize (normalize values) = normalize values :=
  normalization_preserves_supported_text _
    (normalization_has_only_valid_nonreturn_scalars values)

def markdownReserved (value : Nat) : Bool :=
  [9, 10, 13, 35, 38, 42, 60, 62, 91, 92, 93, 95, 96, 124, 126].contains value

def xmlReserved (value : Nat) : Bool := [34, 38, 39, 60, 62].contains value

inductive Atom where
  | literal : Nat → Atom
  | reference : Nat → Atom
  deriving DecidableEq, Repr

def encode (reserved : Nat → Bool) (values : List Nat) : List Atom :=
  values.map fun value => if reserved value then .reference value else .literal value

def decodeAtom : Atom → Nat
  | .literal value | .reference value => value

def decode (atoms : List Atom) : List Nat := atoms.map decodeAtom

def literalValues (atoms : List Atom) : List Nat :=
  atoms.filterMap fun atom => match atom with
    | .literal value => some value
    | .reference _ => none

def whitespace (value : Nat) : Bool :=
  [9, 10, 11, 12, 13, 28, 29, 30, 31, 32, 133, 160, 5760, 8192, 8193, 8194,
    8195, 8196, 8197, 8198, 8199, 8200, 8201, 8202, 8232, 8233, 8239, 8287,
    12288].contains value

def protectHead : List Atom → List Atom
  | .literal value :: rest =>
    (if whitespace value then .reference value else .literal value) :: rest
  | atoms => atoms

def protectBoundary (atoms : List Atom) : List Atom :=
  (protectHead (protectHead atoms).reverse).reverse

theorem protect_head_preserves_content (atoms : List Atom) :
    decode (protectHead atoms) = decode atoms := by
  unfold protectHead
  split
  · split <;> rfl
  · rfl

theorem protect_boundary_preserves_content (atoms : List Atom) :
    decode (protectBoundary atoms) = decode atoms := by
  simp only [protectBoundary, decode, List.map_reverse]
  rw [← decode, protect_head_preserves_content]
  simp only [decode, List.map_reverse, List.reverse_reverse]
  exact protect_head_preserves_content atoms

theorem protect_head_never_adds_raw_literals (atoms : List Atom) (value : Nat)
    (member : value ∈ literalValues (protectHead atoms)) :
    value ∈ literalValues atoms := by
  unfold protectHead at member
  split at member
  · split at member
    · simp only [literalValues, List.filterMap_cons] at member ⊢
      exact List.mem_cons_of_mem _ member
    · exact member
  · exact member

theorem protect_boundary_never_adds_raw_literals (atoms : List Atom) (value : Nat)
    (member : value ∈ literalValues (protectBoundary atoms)) :
    value ∈ literalValues atoms := by
  simp only [protectBoundary, literalValues, List.filterMap_reverse,
    List.mem_reverse] at member
  have first := protect_head_never_adds_raw_literals _ value member
  simp only [literalValues, List.filterMap_reverse, List.mem_reverse] at first
  exact protect_head_never_adds_raw_literals atoms value first

theorem decode_encode (reserved : Nat → Bool) (values : List Nat) :
    decode (encode reserved values) = values := by
  simp only [decode, encode, List.map_map]
  have pointwise :
      (decodeAtom ∘ fun value =>
        if reserved value then Atom.reference value else Atom.literal value) = id := by
    funext value
    simp only [Function.comp_apply]
    split <;> rfl
  rw [pointwise, List.map_id]

theorem encoded_literals_are_not_reserved (reserved : Nat → Bool)
    (values : List Nat) (value : Nat)
    (member : value ∈ literalValues (encode reserved values)) :
    reserved value = false := by
  obtain ⟨atom, present, decoded⟩ := List.mem_filterMap.mp member
  obtain ⟨candidate, _input, rfl⟩ := List.mem_map.mp present
  by_cases selected : reserved candidate = true
  · simp [selected] at decoded
  · have no := Bool.eq_false_iff.mpr selected
    simp [no] at decoded
    subst candidate
    exact no

theorem encoding_is_injective (reserved : Nat → Bool) (left right : List Nat)
    (same : encode reserved left = encode reserved right) : left = right := by
  simpa only [decode_encode] using congrArg decode same

theorem encode_append (reserved : Nat → Bool) (left right : List Nat) :
    encode reserved (left ++ right) = encode reserved left ++ encode reserved right := by
  simp [encode]

theorem markdown_cannot_emit_raw_pipe (values : List Nat) :
    124 ∉ literalValues (encode markdownReserved values) := by
  intro member
  have safe := encoded_literals_are_not_reserved markdownReserved values 124 member
  simp [markdownReserved] at safe

theorem markdown_cannot_emit_raw_newline (values : List Nat) :
    10 ∉ literalValues (encode markdownReserved values) := by
  intro member
  have safe := encoded_literals_are_not_reserved markdownReserved values 10 member
  simp [markdownReserved] at safe

theorem markdown_cannot_emit_raw_tag (values : List Nat) :
    60 ∉ literalValues (encode markdownReserved values) := by
  intro member
  have safe := encoded_literals_are_not_reserved markdownReserved values 60 member
  simp [markdownReserved] at safe

theorem xml_cannot_emit_raw_tag (values : List Nat) :
    60 ∉ literalValues (encode xmlReserved values) := by
  intro member
  have safe := encoded_literals_are_not_reserved xmlReserved values 60 member
  simp [xmlReserved] at safe

inductive Piece where
  | text : List Nat → Piece
  | markup : List Nat → Piece
  deriving DecidableEq, Repr

inductive Token where
  | data : Atom → Token
  | syntax : Nat → Token
  deriving DecidableEq, Repr

def renderPiece (reserved : Nat → Bool) : Piece → List Token
  | .text values => (protectBoundary (encode reserved (normalize values))).map .data
  | .markup values => values.map .syntax

def render (reserved : Nat → Bool) (pieces : List Piece) : List Token :=
  pieces.flatMap (renderPiece reserved)

def syntaxTokens (tokens : List Token) : List Nat :=
  tokens.filterMap fun token => match token with
    | .syntax value => some value
    | .data _ => none

def skeleton (pieces : List Piece) : List Nat :=
  pieces.flatMap fun piece => match piece with
    | .markup values => values
    | .text _ => []

def payload (tokens : List Token) : List Nat :=
  tokens.filterMap fun token => match token with
    | .data atom => some (decodeAtom atom)
    | .syntax _ => none

def textContent (pieces : List Piece) : List Nat :=
  pieces.flatMap fun piece => match piece with
    | .text values => normalize values
    | .markup _ => []

theorem text_creates_no_syntax (reserved : Nat → Bool) (values : List Nat) :
    syntaxTokens (renderPiece reserved (.text values)) = [] := by
  simp [syntaxTokens, renderPiece, List.filterMap_map, Function.comp_def]

theorem text_content_survives (reserved : Nat → Bool) (values : List Nat) :
    payload (renderPiece reserved (.text values)) = normalize values := by
  simp only [payload, renderPiece, List.filterMap_map, Function.comp_def]
  rw [List.filterMap_eq_map']
  change decode (protectBoundary (encode reserved (normalize values))) = normalize values
  rw [protect_boundary_preserves_content, decode_encode]

theorem complete_structure_is_exactly_trusted_markup (reserved : Nat → Bool)
    (pieces : List Piece) : syntaxTokens (render reserved pieces) = skeleton pieces := by
  induction pieces with
  | nil => rfl
  | cons piece rest induction =>
    cases piece <;>
      simp_all [render, skeleton, syntaxTokens, renderPiece, List.filterMap_append,
        List.filterMap_map, Function.comp_def]

theorem complete_content_preserves_text_order_and_multiplicity (reserved : Nat → Bool)
    (pieces : List Piece) : payload (render reserved pieces) = textContent pieces := by
  induction pieces with
  | nil => rfl
  | cons piece rest induction =>
    have separate : payload (render reserved (piece :: rest)) =
        payload (renderPiece reserved piece) ++ payload (render reserved rest) := by
      simp [payload, render]
    rw [separate, induction]
    cases piece with
    | text values =>
      rw [text_content_survives]
      simp [textContent]
    | markup values =>
      simp [payload, renderPiece, textContent, List.filterMap_map, Function.comp_def]

def cell (values : List Nat) : List Piece :=
  [.markup [1], .text values, .markup [2]]

def row (cells : List (List Nat)) : List Piece :=
  [.markup [3]] ++ cells.flatMap cell ++ [.markup [4]]

theorem cell_structure_is_fixed (reserved : Nat → Bool) (values : List Nat) :
    syntaxTokens (render reserved (cell values)) = [1, 2] := by
  rw [complete_structure_is_exactly_trusted_markup]
  rfl

theorem cell_preserves_exact_normalized_text (reserved : Nat → Bool)
    (values : List Nat) : payload (render reserved (cell values)) = normalize values := by
  rw [complete_content_preserves_text_order_and_multiplicity]
  simp [cell, textContent]

theorem row_structure_preserves_every_cell (reserved : Nat → Bool)
    (cells : List (List Nat)) :
    syntaxTokens (render reserved (row cells)) =
      [3] ++ (cells.flatMap fun _ => [1, 2]) ++ [4] := by
  rw [complete_structure_is_exactly_trusted_markup]
  simp [row, skeleton, List.flatMap_append, List.flatMap_assoc, cell]

def atomWire : Atom → String
  | .literal value => String.singleton (Char.ofNat value)
  | .reference value => "&#" ++ toString value ++ ";"

def wire (reserved : Nat → Bool) (values : List Nat) : String :=
  String.join ((protectBoundary (encode reserved (normalize values))).map atomWire)

inductive CDataAtom where
  | character : Nat → CDataAtom
  | restart : CDataAtom
  deriving DecidableEq, Repr

def closes (brackets value : Nat) : Bool := 2 ≤ brackets && value == 62

def nextBrackets (brackets value : Nat) : Nat :=
  if value == 93 then brackets + 1 else 0

def cdataEncode (brackets : Nat) : List Nat → List CDataAtom
  | [] => []
  | value :: rest =>
    (if closes brackets value then [.restart, .character value] else [.character value]) ++
      cdataEncode (nextBrackets brackets value) rest

def cdataContent (tokens : List CDataAtom) : List Nat :=
  tokens.filterMap fun token => match token with
    | .character value => some value
    | .restart => none

def cdataSafe : Nat → List CDataAtom → Bool
  | _, [] => true
  | _, .restart :: rest => cdataSafe 0 rest
  | brackets, .character value :: rest =>
    !closes brackets value && cdataSafe (nextBrackets brackets value) rest

theorem cdata_restarts_preserve_every_character (brackets : Nat) (values : List Nat) :
    cdataContent (cdataEncode brackets values) = values := by
  induction values generalizing brackets with
  | nil => rfl
  | cons value rest induction =>
    simp only [cdataEncode]
    split <;>
      change value :: cdataContent (cdataEncode (nextBrackets brackets value) rest) =
        value :: rest
    all_goals rw [induction]

theorem cdata_content_cannot_close_its_envelope (brackets : Nat) (values : List Nat) :
    cdataSafe brackets (cdataEncode brackets values) = true := by
  induction values generalizing brackets with
  | nil => rfl
  | cons value rest induction =>
    simp only [cdataEncode]
    split
    · rename_i closing
      have both : 2 ≤ brackets ∧ value = 62 := by simpa [closes] using closing
      have character := both.2
      subst value
      simpa [cdataSafe, closes, nextBrackets] using induction 0
    · rename_i safe
      have noClose : closes brackets value = false := Bool.eq_false_iff.mpr safe
      simp [cdataSafe, noClose, induction]

def cdataAtomWire : CDataAtom → String
  | .character value => String.singleton (Char.ofNat value)
  | .restart => "]]><![CDATA["

def cdataWire (values : List Nat) : String :=
  "<![CDATA[" ++ String.join ((cdataEncode 0 (normalize values)).map cdataAtomWire) ++ "]]>"

theorem cdata_preserves_exact_normalized_content (values : List Nat) :
    cdataContent (cdataEncode 0 (normalize values)) = normalize values :=
  cdata_restarts_preserve_every_character _ _

end PeriScribe.OutputText
