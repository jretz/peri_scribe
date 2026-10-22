import Std

namespace PeriScribe.PayloadCodec

abbrev Byte := BitVec 8

/-- One byte lane predicts each original byte from the preceding original byte. -/
def predict (previous : Byte) : List Byte → List Byte
  | [] => []
  | value :: rest => (value ^^^ previous) :: predict value rest

/-- Decoding updates its predecessor only after recovering the original byte. -/
def restore (previous : Byte) : List Byte → List Byte
  | [] => []
  | value :: rest =>
    let original := value ^^^ previous
    original :: restore original rest

theorem restore_predict (previous : Byte) (values : List Byte) :
    restore previous (predict previous values) = values := by
  induction values generalizing previous with
  | nil => rfl
  | cons value rest induction =>
    simp [predict, restore, BitVec.xor_assoc, induction]

theorem prediction_is_injective (previous : Byte) (first second : List Byte)
    (same : predict previous first = predict previous second) : first = second := by
  have recovered := congrArg (restore previous) same
  simpa only [restore_predict] using recovered

/-- Byte shuffling transposes a rectangular block; it performs no numeric conversion. -/
def transpose {rows columns : Nat} (matrix : Fin rows → Fin columns → Byte) :
    Fin columns → Fin rows → Byte := fun column row => matrix row column

theorem transpose_twice {rows columns : Nat}
    (matrix : Fin rows → Fin columns → Byte) : transpose (transpose matrix) = matrix := by
  rfl

theorem padding_retains_every_original_byte (values padding : List Byte) :
    (values ++ padding).take values.length = values := by
  simp

/-- The executable adapter lays out complete padded lanes in increasing column order. -/
def padded (width : Nat) (values : List Byte) : List Byte :=
  values ++ List.replicate ((width - values.length % width) % width) 0

def lane (width column : Nat) (values : List Byte) : List Byte :=
  values.zipIdx.filterMap fun (value, index) =>
    if index % width = column then some value else none

def encodedLanes (width : Nat) (values : List Byte) : List Byte :=
  (List.range width).flatMap fun column => predict 0 (lane width column (padded width values))

end PeriScribe.PayloadCodec
