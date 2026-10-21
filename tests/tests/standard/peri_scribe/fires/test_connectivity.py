"""Keep the transient representative table independent of union order."""

import peri_scribe.fires.connectivity


def test_union_find_groups_preserves_original_encounter_order() -> None:
    components = peri_scribe.fires.connectivity.UnionFind.for_count(6)
    components.union(4, 2)
    components.union(4, 0)
    components.union(3, 1)
    components.union(5, 4)
    components.union(0, 5)
    assert components.groups() == [[0, 2, 4, 5], [1, 3]]


def test_union_find_union_attaches_smaller_component_to_larger() -> None:
    components = peri_scribe.fires.connectivity.UnionFind.for_count(4)
    components.union(0, 1)
    components.union(2, 0)
    components.union(3, 2)
    assert components.find(3) == components.find(1)
    assert components.sizes[components.find(0)] == len(components.parents)
