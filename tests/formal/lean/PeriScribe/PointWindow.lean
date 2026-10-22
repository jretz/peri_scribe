import Std

namespace PeriScribe.PointWindow

structure Point where
  longitude : Int
  latitude : Int
  deriving DecidableEq, Repr

structure Box where
  minimumLongitude : Int
  minimumLatitude : Int
  maximumLongitude : Int
  maximumLatitude : Int
  deriving Repr

def within (box : Box) (point : Point) : Bool :=
  decide (box.minimumLongitude ≤ point.longitude ∧
    point.longitude ≤ box.maximumLongitude ∧
    box.minimumLatitude ≤ point.latitude ∧ point.latitude ≤ box.maximumLatitude)

def ordered (points : List Point) : Prop :=
  points.Pairwise (fun first second => first.longitude ≤ second.longitude)

/-- Binary-search endpoints denote exactly this contiguous sorted window. -/
def window (points : List Point) (box : Box) : List Point :=
  let remaining := points.dropWhile
    (fun point => decide (point.longitude < box.minimumLongitude))
  remaining.takeWhile (fun point => decide (point.longitude ≤ box.maximumLongitude))

def select (points : List Point) (box : Box) : List Point :=
  (window points box).filter (fun point => decide
    (box.minimumLatitude ≤ point.latitude ∧ point.latitude ≤ box.maximumLatitude))

theorem drop_lower_equals_filter (points : List Point) (minimum : Int)
    (sorted : ordered points) :
    points.dropWhile (fun point => decide (point.longitude < minimum)) =
      points.filter (fun point => decide (minimum ≤ point.longitude)) := by
  induction points with
  | nil => rfl
  | cons first rest induction =>
    rcases List.pairwise_cons.mp sorted with ⟨least, remaining⟩
    by_cases below : first.longitude < minimum
    · have notInside : ¬ minimum ≤ first.longitude := by omega
      simp [below, notInside, induction remaining]
    · have inside : minimum ≤ first.longitude := by omega
      have allInside : rest.filter (fun point => decide (minimum ≤ point.longitude)) =
          rest := by
        apply List.filter_eq_self.mpr
        intro point member
        have lower := least point member
        simp only [decide_eq_true_eq]
        omega
      simp [below, inside, allInside]

theorem take_upper_equals_filter (points : List Point) (maximum : Int)
    (sorted : ordered points) :
    points.takeWhile (fun point => decide (point.longitude ≤ maximum)) =
      points.filter (fun point => decide (point.longitude ≤ maximum)) := by
  induction points with
  | nil => rfl
  | cons first rest induction =>
    rcases List.pairwise_cons.mp sorted with ⟨least, remaining⟩
    by_cases inside : first.longitude ≤ maximum
    · simp [inside, induction remaining]
    · have allOutside : rest.filter (fun point => decide (point.longitude ≤ maximum)) =
          [] := by
        apply List.filter_eq_nil_iff.mpr
        intro point member
        have lower := least point member
        simp only [decide_eq_true_eq]
        omega
      simp [inside, allOutside]

/-- Selection preserves every qualifying occurrence, including duplicate endpoints. -/
theorem select_equals_filter (points : List Point) (box : Box)
    (sorted : ordered points) : select points box = points.filter (within box) := by
  unfold select window
  rw [drop_lower_equals_filter points box.minimumLongitude sorted]
  rw [take_upper_equals_filter _ box.maximumLongitude (sorted.filter _)]
  simp only [List.filter_filter]
  congr 1
  funext point
  simp only [within, Bool.decide_and]
  ac_rfl

/-- Reordering the tile can never remove or coalesce an occurrence. -/
theorem selected_bag_preserved (points sortedPoints : List Point) (box : Box)
    (sameBag : sortedPoints.Perm points) (sorted : ordered sortedPoints) :
    (select sortedPoints box).Perm (points.filter (within box)) := by
  rw [select_equals_filter sortedPoints box sorted]
  exact sameBag.filter (within box)

/-- Any exact predicate sees the same multiplicities after candidate selection. -/
theorem exact_counts_preserved (points sortedPoints : List Point) (box : Box)
    (contains : Point → Bool) (sameBag : sortedPoints.Perm points)
    (sorted : ordered sortedPoints) :
    (select sortedPoints box).countP contains =
      (points.filter (within box)).countP contains :=
  (selected_bag_preserved points sortedPoints box sameBag sorted).countP_eq contains

def sortedPoints (points : List Point) : List Point :=
  points.mergeSort (fun first second => decide (first.longitude ≤ second.longitude))

def candidates (points : List Point) (box : Box) : List Point :=
  select (sortedPoints points) box

theorem sorted_points_ordered (points : List Point) : ordered (sortedPoints points) := by
  have result := List.pairwise_mergeSort
    (le := fun first second : Point => decide (first.longitude ≤ second.longitude))
    (by intro first second third firstBound secondBound; simp_all; omega)
    (by intro first second; simp; omega) points
  simpa [ordered, sortedPoints] using result

/-- The executable reference establishes its ordering and bag premises by sorting. -/
theorem candidates_preserve_exact_counts (points : List Point) (box : Box)
    (contains : Point → Bool) :
    (candidates points box).countP contains =
      (points.filter (within box)).countP contains :=
  exact_counts_preserved points (sortedPoints points) box contains
    (List.mergeSort_perm points _) (sorted_points_ordered points)

end PeriScribe.PointWindow
