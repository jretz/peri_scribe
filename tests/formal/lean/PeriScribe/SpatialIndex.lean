import Std

namespace PeriScribe.SpatialIndex

/-- Offsetting valid WGS84 encoded coordinates makes division natural-valued. -/
structure Point where
  longitude : Nat
  latitude : Nat
  deriving DecidableEq, Repr

structure Box where
  minimum : Point
  maximum : Point
  deriving Repr

/-- The geographic upper endpoint belongs to the final tile, not an extra tile. -/
def axis (coordinate last : Nat) : Nat := min (coordinate / 50000) last

def tile (point : Point) : Nat :=
  axis point.latitude 359 * 720 + axis point.longitude 719

def within (box : Box) (point : Point) : Bool :=
  decide (box.minimum.longitude ≤ point.longitude ∧
    point.longitude ≤ box.maximum.longitude ∧
    box.minimum.latitude ≤ point.latitude ∧ point.latitude ≤ box.maximum.latitude)

/-- Enumerating each row/column once is essential because payloads are bags. -/
def tiles (box : Box) : List Nat :=
  let firstColumn := axis box.minimum.longitude 719
  let lastColumn := axis box.maximum.longitude 719
  let firstRow := axis box.minimum.latitude 359
  let lastRow := axis box.maximum.latitude 359
  (List.range' firstRow (lastRow + 1 - firstRow)).flatMap fun row =>
    (List.range' firstColumn (lastColumn + 1 - firstColumn)).map
      (fun column => row * 720 + column)

theorem axis_monotone (first second last : Nat) (ordered : first ≤ second) :
    axis first last ≤ axis second last := by
  have divided := Nat.div_le_div_right (c := 50000) ordered
  simp only [axis]
  omega

theorem longitude_upper_endpoint : axis 36000000 719 = 719 := by decide

theorem latitude_upper_endpoint : axis 18000000 359 = 359 := by decide

theorem tile_coordinates_are_unique (firstRow secondRow firstColumn secondColumn : Nat)
    (firstBound : firstColumn < 720) (secondBound : secondColumn < 720)
    (same : firstRow * 720 + firstColumn = secondRow * 720 + secondColumn) :
    firstRow = secondRow ∧ firstColumn = secondColumn := by omega

theorem bounded_axis_member (low value high : Nat) (lower : low ≤ value)
    (upper : value ≤ high) : value ∈ List.range' low (high + 1 - low) := by
  apply List.mem_range'.mpr
  exact ⟨value - low, by omega, by omega⟩

theorem envelope_does_not_skip_tiles (box : Box) (point : Point)
    (inside : within box point = true) : tile point ∈ tiles box := by
  simp only [within, decide_eq_true_eq] at inside
  have xLow := axis_monotone _ _ 719 inside.1
  have xHigh := axis_monotone _ _ 719 inside.2.1
  have yLow := axis_monotone _ _ 359 inside.2.2.1
  have yHigh := axis_monotone _ _ 359 inside.2.2.2
  apply List.mem_flatMap.mpr
  refine ⟨axis point.latitude 359, bounded_axis_member _ _ _ yLow yHigh, ?_⟩
  apply List.mem_map.mpr
  exact ⟨axis point.longitude 719, bounded_axis_member _ _ _ xLow xHigh, rfl⟩

/-- Rows and columns are enumerated once, so an encoded tile is never counted twice. -/
theorem tiles_nodup (box : Box) : (tiles box).Nodup := by
  unfold tiles
  apply List.pairwise_flatMap.mpr
  constructor
  · intro row _
    apply List.pairwise_map.mpr
    apply (List.nodup_range' (s := axis box.minimum.longitude 719)
      (n := axis box.maximum.longitude 719 + 1 - axis box.minimum.longitude 719)).imp
    intro first second different
    omega
  · apply (List.nodup_range' (s := axis box.minimum.latitude 359)
      (n := axis box.maximum.latitude 359 + 1 - axis box.minimum.latitude 359)).imp
    intro firstRow secondRow different first firstMember second secondMember equal
    rcases List.mem_map.mp firstMember with ⟨firstColumn, firstPresent, firstSame⟩
    rcases List.mem_map.mp secondMember with ⟨secondColumn, secondPresent, secondSame⟩
    have upper : axis box.maximum.longitude 719 ≤ 719 := Nat.min_le_right _ _
    have firstRange := List.mem_range'_1.mp firstPresent
    have secondRange := List.mem_range'_1.mp secondPresent
    have firstBound : firstColumn < 720 := by omega
    have secondBound : secondColumn < 720 := by omega
    have same : firstRow * 720 + firstColumn = secondRow * 720 + secondColumn :=
      firstSame.trans (equal.trans secondSame.symm)
    exact different (tile_coordinates_are_unique firstRow secondRow firstColumn
      secondColumn firstBound secondBound same).1

/-- Querying a tile retains the multiplicity of points with equal coordinates. -/
def tileCount (points : List Point) (box : Box) (contains : Point → Bool)
    (identifier : Nat) : Nat :=
  points.countP (fun point =>
    tile point == identifier && within box point && contains point)

def indexedCount (points : List Point) (box : Box) (contains : Point → Bool)
    (identifiers : List Nat) : Nat :=
  (identifiers.map (tileCount points box contains)).sum

/-- Swapping finite summation order connects per-tile IO to per-point multiplicity. -/
theorem sum_map_add (values : List Nat) (first second : Nat → Nat) :
    (values.map (fun value => first value + second value)).sum =
      (values.map first).sum + (values.map second).sum := by
  induction values with
  | nil => simp
  | cons firstValue rest induction => simp [induction, Nat.add_assoc, Nat.add_left_comm]

theorem sum_map_zero (values : List Nat) :
    (values.map (fun _ => (0 : Nat))).sum = 0 := by
  induction values with
  | nil => rfl
  | cons first rest induction => simpa using induction

theorem unique_tile_weight (identifiers : List Nat) (identifier : Nat)
    (unique : identifiers.Nodup) (present : identifier ∈ identifiers) :
    (identifiers.map
      (fun candidate => if identifier = candidate then 1 else 0)).sum = 1 := by
  induction identifiers with
  | nil => simp at present
  | cons first rest induction =>
    have distinct := List.nodup_cons.mp unique
    rcases List.mem_cons.mp present with same | member
    · subst first
      have zero : (rest.map
          (fun candidate => if identifier = candidate then 1 else 0)).sum = 0 := by
        have allZero :
            rest.map (fun candidate => if identifier = candidate then 1 else 0) =
              rest.map (fun _ => 0) := by
          apply List.map_congr_left
          intro candidate member
          have different : identifier ≠ candidate := by
            intro equal
            exact distinct.1 (equal ▸ member)
          simp [different]
        rw [allZero]
        exact sum_map_zero rest
      simp [zero]
    · have different : identifier ≠ first := by
        intro same
        exact distinct.1 (same ▸ member)
      simp [different, induction distinct.2 member]

theorem indexed_count_equals_exhaustive (points : List Point) (box : Box)
    (contains : Point → Bool) (identifiers : List Nat)
    (unique : identifiers.Nodup)
    (envelope : ∀ point ∈ points, contains point = true → within box point = true)
    (available : ∀ point ∈ points, within box point = true → tile point ∈ identifiers) :
    indexedCount points box contains identifiers = points.countP contains := by
  induction points with
  | nil => exact sum_map_zero identifiers
  | cons point rest induction =>
    have previous := induction (fun p member => envelope p (by simp [member]))
      (fun p member => available p (by simp [member]))
    change (identifiers.map (fun identifier =>
      (point :: rest).countP (fun p => tile p == identifier && within box p &&
        contains p))).sum = (point :: rest).countP contains
    change (identifiers.map (fun identifier =>
      rest.countP (fun p => tile p == identifier && within box p && contains p))).sum =
        rest.countP contains at previous
    simp only [List.countP_cons]
    rw [sum_map_add, previous]
    by_cases inside : contains point = true
    · have bounded := envelope point (by simp) inside
      simp only [inside, bounded, Bool.and_true, beq_iff_eq]
      rw [unique_tile_weight identifiers (tile point) unique
        (available point (by simp) bounded)]
      simp
    · have outside : contains point = false := by
        cases value : contains point <;> simp_all
      simp only [outside, Bool.and_false, Bool.false_eq_true, ite_false]
      rw [sum_map_zero]

theorem duplicate_points_are_counted (points : List Point) (contains : Point → Bool)
    (point : Point) (inside : contains point = true) :
    (point :: point :: points).countP contains = points.countP contains + 2 := by
  simp [inside, Nat.add_assoc]

/-- The concrete enumerator meets both index hypotheses for every point bag. -/
theorem concrete_index_equals_exhaustive (points : List Point) (box : Box)
    (contains : Point → Bool)
    (envelope : ∀ point ∈ points, contains point = true → within box point = true) :
    indexedCount points box contains (tiles box) = points.countP contains :=
  indexed_count_equals_exhaustive points box contains (tiles box) (tiles_nodup box)
    envelope (fun point _ bounded => envelope_does_not_skip_tiles box point bounded)

end PeriScribe.SpatialIndex
