"""Generate finite JSON trees with exact scalar and nested mutation boundaries."""

import hypothesis.strategies as st


JSON_VALUES = st.recursive(
    st.one_of(st.none(), st.booleans(), st.integers(), st.floats(), st.text()),
    lambda children: st.one_of(
        st.lists(children, max_size=5),
        st.dictionaries(st.text(), children, max_size=5),
    ),
    max_leaves=30,
)
