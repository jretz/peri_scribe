import Std

namespace PeriScribe.BuildingCentroids

/-- Integer projected coordinates expose exact algebra before numerical rounding. -/
structure Point where
  x : Int
  y : Int
  deriving DecidableEq, Repr

structure Moment where
  area : Int
  x : Int
  y : Int
  deriving DecidableEq, Repr

def zero : Moment := ⟨0, 0, 0⟩
def add (a b : Moment) : Moment := ⟨a.area + b.area, a.x + b.x, a.y + b.y⟩
def negate (a : Moment) : Moment := ⟨-a.area, -a.x, -a.y⟩
def move (p offset : Point) : Point := ⟨p.x + offset.x, p.y + offset.y⟩
def translated (a : Moment) (offset : Point) : Moment :=
  ⟨a.area, a.x + 3 * offset.x * a.area, a.y + 3 * offset.y * a.area⟩

/-- A fan triangle contributes double area and six times its first area moments. -/
def triangle (origin a b : Point) : Moment :=
  let cross := (a.x - origin.x) * (b.y - origin.y) -
    (b.x - origin.x) * (a.y - origin.y)
  ⟨cross, (origin.x + a.x + b.x) * cross,
    (origin.y + a.y + b.y) * cross⟩

def sum : List Moment → Moment
  | [] => zero
  | a :: rest => add a (sum rest)

def normalize (a : Moment) : Moment :=
  if a.area < 0 then negate a else if a.area = 0 then zero else a

def fan (origin : Point) (edges : List (Point × Point)) : Moment :=
  sum (edges.map fun (a, b) => triangle origin a b)

def ring (points : List Point) : Moment :=
  match points with
  | [] => zero
  | origin :: _ => normalize (fan origin (points.zip points.tail))

/-- Ring position determines hole subtraction independently of ring orientation. -/
def polygon : List Moment → Moment
  | [] => zero
  | exterior :: holes => add exterior (negate (sum holes))

theorem add_associative (a b c : Moment) : add (add a b) c = add a (add b c) := by
  cases a; cases b; cases c; simp [add, Int.add_assoc]

theorem add_commutative (a b : Moment) : add a b = add b a := by
  cases a; cases b; simp [add, Int.add_comm]

theorem sum_append (a b : List Moment) : sum (a ++ b) = add (sum a) (sum b) := by
  induction a with
  | nil => simp [sum, add, zero]
  | cons first rest induction => simp [sum, induction, add_associative]

theorem sum_reordered (a b : List Moment) (same : a.Perm b) : sum a = sum b := by
  induction same with
  | nil => rfl
  | cons a same induction => simp [sum, induction]
  | swap a b rest => simp [sum, ← add_associative, add_commutative a b]
  | trans _ _ first second => exact first.trans second

theorem triangle_orientation (origin a b : Point) :
    triangle origin b a = negate (triangle origin a b) := by
  simp only [triangle, negate, Moment.mk.injEq]
  grind

theorem triangle_translation (origin a b offset : Point) :
    triangle (move origin offset) (move a offset) (move b offset) =
      translated (triangle origin a b) offset := by
  simp only [triangle, move, translated, Moment.mk.injEq]
  grind

theorem fan_matches_translated_shoelace (origin a b : Point) :
    triangle origin a b =
      translated (triangle ⟨0, 0⟩ ⟨a.x - origin.x, a.y - origin.y⟩
        ⟨b.x - origin.x, b.y - origin.y⟩) origin := by
  simp only [triangle, translated, Moment.mk.injEq]
  grind

theorem sum_negated (values : List Moment) :
    sum (values.map negate) = negate (sum values) := by
  induction values with
  | nil => rfl
  | cons first rest induction =>
    simp only [List.map_cons, sum, induction, add, negate, Moment.mk.injEq]
    omega

theorem sum_translated (moments : List Moment) (offset : Point) :
    sum (moments.map (translated · offset)) = translated (sum moments) offset := by
  induction moments with
  | nil => simp [sum, translated, zero]
  | cons first rest induction =>
    change add (translated first offset) (sum (rest.map (translated · offset))) =
      translated (add first (sum rest)) offset
    rw [induction]
    simp only [add, translated, Moment.mk.injEq]
    grind

theorem fan_translation (origin offset : Point) (edges : List (Point × Point)) :
    fan (move origin offset) (edges.map fun (a, b) => (move a offset, move b offset)) =
      translated (fan origin edges) offset := by
  unfold fan
  simp only [List.map_map, Function.comp_def, triangle_translation]
  rw [← sum_translated, List.map_map]
  rfl

theorem normalized_orientation (a : Moment) : normalize (negate a) = normalize a := by
  cases a
  simp only [normalize, negate]
  grind [zero]

theorem fan_orientation (origin : Point) (edges : List (Point × Point)) :
    fan origin (edges.reverse.map fun (a, b) => (b, a)) =
      negate (fan origin edges) := by
  unfold fan
  rw [List.map_map]
  change sum (edges.reverse.map fun e => triangle origin e.2 e.1) =
    negate (sum (edges.map fun e => triangle origin e.1 e.2))
  have swapped : (edges.reverse.map fun e => triangle origin e.2 e.1) =
      ((edges.reverse.map fun e => triangle origin e.1 e.2).map negate) := by
    simp only [List.map_map]
    apply List.map_congr_left
    intro edge _
    exact triangle_orientation origin edge.1 edge.2
  rw [swapped, sum_negated]
  congr 1
  apply sum_reordered
  exact (List.reverse_perm edges).map _

theorem ring_orientation_independent (origin : Point) (edges : List (Point × Point)) :
    normalize (fan origin (edges.reverse.map fun (a, b) => (b, a))) =
      normalize (fan origin edges) := by
  rw [fan_orientation, normalized_orientation]

theorem hole_order_independent (outer : Moment) (a b : List Moment)
    (same : a.Perm b) : polygon (outer :: a) = polygon (outer :: b) := by
  simp [polygon, sum_reordered a b same]

theorem hole_subtracts_area_and_moment (outer hole : Moment) :
    polygon [outer, hole] =
      ⟨outer.area - hole.area, outer.x - hole.x, outer.y - hole.y⟩ := by
  simp [polygon, sum, add, negate, zero, Int.sub_eq_add_neg]

theorem multipart_flatten (parts : List (List Moment)) :
    sum (parts.map sum) = sum parts.flatten := by
  induction parts with
  | nil => rfl
  | cons first rest induction => simp [sum, sum_append, induction]

/-- Cross-multiplication states centroid weighting without rounding rational results. -/
theorem weighted_centroid (a b : Moment) (x y : Int)
    (first : a.x = 3 * a.area * x) (second : b.x = 3 * b.area * y) :
    (add a b).x = 3 * (a.area * x + b.area * y) := by
  simp only [add]
  grind

theorem translation_moves_centroid (a : Moment) (offset : Point) (x y : Int)
    (horizontal : a.x = 3 * a.area * x) (vertical : a.y = 3 * a.area * y) :
    (translated a offset).x = 3 * a.area * (x + offset.x) ∧
    (translated a offset).y = 3 * a.area * (y + offset.y) := by
  simp only [translated]
  grind

/-- Zero-area inputs use the recorded vertices, including closing duplicates. -/
def centroidRatio (moment : Moment) (vertices : List Point) : Int × Int × Int :=
  if moment.area = 0 then
    ((vertices.map (·.x)).sum, (vertices.map (·.y)).sum, (vertices.length : Int))
  else (moment.x, moment.y, 3 * moment.area)

theorem nondegenerate_uses_area (moment : Moment) (vertices : List Point)
    (nonzero : moment.area ≠ 0) :
    centroidRatio moment vertices = (moment.x, moment.y, 3 * moment.area) := by
  simp [centroidRatio, nonzero]

theorem degenerate_uses_every_vertex (moment : Moment) (vertices : List Point)
    (empty : moment.area = 0) :
    centroidRatio moment vertices =
      ((vertices.map (·.x)).sum, (vertices.map (·.y)).sum,
        (vertices.length : Int)) := by
  simp [centroidRatio, empty]

/-- Accepted features remain atomic even when one feature exceeds the vertex budget. -/
structure Feature where
  identifier : Nat
  vertices : Nat
  supported : Bool
  deriving DecidableEq, Repr

def accepted (features : List Feature) : List Feature :=
  features.filter (·.supported)

def takeChunk (limit budget : Nat) : List Feature → List Feature × List Feature
  | [] => ([], [])
  | first :: rest =>
    if limit ≤ 1 ∨ budget ≤ first.vertices then ([first], rest)
    else
      let (front, back) := takeChunk (limit - 1) (budget - first.vertices) rest
      (first :: front, back)

theorem takeChunk_preserves (limit budget : Nat) (features : List Feature) :
    (takeChunk limit budget features).1 ++ (takeChunk limit budget features).2 =
      features := by
  induction features generalizing limit budget with
  | nil => rfl
  | cons first rest induction =>
    simp only [takeChunk]
    split
    · rfl
    · simpa using congrArg (List.cons first) (induction (limit - 1)
        (budget - first.vertices))

theorem takeChunk_feature_bound (limit budget : Nat) (features : List Feature) :
    (takeChunk limit budget features).1.length ≤ max 1 limit := by
  induction features generalizing limit budget with
  | nil => simp [takeChunk]
  | cons first rest induction =>
    simp only [takeChunk]
    split
    · simp only [List.length_singleton]
      omega
    · rename_i continues
      have bound := induction (limit - 1) (budget - first.vertices)
      simp only [List.length_cons]
      omega

theorem takeChunk_progress (limit budget : Nat) (first : Feature)
    (rest : List Feature) :
    (takeChunk limit budget (first :: rest)).2.length < (first :: rest).length := by
  have preserved := takeChunk_preserves limit budget (first :: rest)
  have positive : 0 < (takeChunk limit budget (first :: rest)).1.length := by
    simp only [takeChunk]
    split <;> simp
  have lengths := congrArg List.length preserved
  simp only [List.length_append] at lengths
  omega

def chunks (limit budget : Nat) (features : List Feature) : List (List Feature) :=
  match features with
  | [] => []
  | first :: rest =>
    let split := takeChunk limit budget (first :: rest)
    split.1 :: chunks limit budget split.2
termination_by features.length
decreasing_by exact takeChunk_progress limit budget first rest

theorem chunks_preserve (limit budget : Nat) (features : List Feature) :
    (chunks limit budget features).flatten = features := by
  fun_induction chunks with
  | case1 => rfl
  | case2 first rest split induction =>
    simp only [List.flatten_cons, induction]
    exact takeChunk_preserves limit budget (first :: rest)

theorem streaming_preserves_order_and_duplicates (limit budget : Nat)
    (features : List Feature) :
    ((chunks limit budget (accepted features)).flatten.map (·.identifier)) =
      (accepted features).map (·.identifier) := by rw [chunks_preserve]

theorem converted_chunks_preserve_features (limit budget : Nat)
    (features : List Feature) (convert : Feature → α) :
    ((chunks limit budget (accepted features)).map (List.map convert)).flatten =
      (accepted features).map convert := by
  rw [← List.map_flatten, chunks_preserve]

theorem archive_member_boundaries (members : List (List Feature)) :
    accepted members.flatten = (members.map accepted).flatten := by
  induction members with
  | nil => rfl
  | cons first rest induction =>
    change accepted (first ++ rest.flatten) =
      accepted first ++ (rest.map accepted).flatten
    rw [accepted, List.filter_append]
    change accepted first ++ accepted rest.flatten = _
    rw [induction]

end PeriScribe.BuildingCentroids
