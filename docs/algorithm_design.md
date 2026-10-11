# Algorithm Design

Assess algorithm complexity before implementation so the explanation is sufficient to
understand its decisions and maintain its correctness. This guide defines the assessment
and documentation requirements for new algorithms and changes to existing algorithms.
It complements [Conventions](conventions.md), [Testing](testing.md), and
[Formal Verification](formal_verification.md).

## When to assess

Assess a new algorithm during design, before writing implementation code. Reassess an
existing algorithm when changing its rules, state transitions, input assumptions,
numerical treatment, representation, resource strategy, or external effects. Assess the
complete resulting behavior, including interactions across functions and modules.

Record the assessment in the design or change description. For involved and complex
algorithms, also retain it with the algorithm's explanation. An implementation-only
refactor can retain an existing assessment when its assumptions and guarantees still
hold; update implementation links as needed.

Keep the [algorithm note index](algorithms/README.md) and
[coverage inventory](algorithms/INVENTORY.md) current when adding an algorithm or moving
its owning modules. The inventory records existing notes and straightforward assessments;
it does not replace assessing a changed behavior against the rubric below.

The assessment measures reasoning complexity: the context needed to establish that the
behavior is correct. Scores are a project convention for choosing documentation depth,
not an empirical measure of engineering effort. Function length, branch counts, and
the number of helpers can reveal implementation growth, but do not determine this
classification. Splitting an algorithm into helpers does not lower its assessment.

## Complexity rubric

Score each dimension from 0 to 3. A score of 0 means the dimension introduces no
meaningful reasoning burden. Choose the highest applicable description in each
dimension, and give a concrete justification for every nonzero score.

### History and state

- **1:** Local state or simple sequencing.
- **2:** Results depend on event ordering or retained history.
- **3:** Later evidence revises earlier decisions, transfers historical ownership, or
  propagates corrections through saved history.

### Rule interaction

- **1:** Independent rules with straightforward conditions.
- **2:** Interacting thresholds, exceptions, or precedence rules.
- **3:** Conflicting evidence, cycles, or consistency requirements spanning multiple
  entities or decisions.

### Mathematical reasoning

- **1:** A standard algorithm with clear assumptions.
- **2:** Geometry operations, floating-point boundaries, or composed algorithms whose
  assumptions require explanation.
- **3:** Custom optimization, numerical stability requirements, or a nonobvious
  derivation needed to justify the result.

### Scale and representation

- **1:** Ordinary in-memory processing with understood input bounds.
- **2:** Indexing, batching, or operations sensitive to data representation.
- **3:** Streaming or compact representations essential to meeting resource limits,
  with correctness depending on partitioning, encoding, or reconstruction.

### Failure and concurrency

- **1:** One external operation with a simple success or failure contract.
- **2:** Several effects with possible partial outcomes that require coordination.
- **3:** Crash recovery, replay, cancellation, or concurrent operations whose
  correctness spans resource lifetimes or independently durable boundaries.

For example, an ownership algorithm could justify a history score of 3 with: "An
identifier correction can transfer previously published records between current fires."
Name the actual behavior, its input domain, and its assumptions; do not score an entire
module solely because it contains a difficult function.

## Documentation requirements

Add the five scores and apply these rules:

| Classification | Rule |
| --- | --- |
| Straightforward | Total at most 4, with every dimension at most 1. |
| Involved | Any assessment that is neither straightforward nor complex. |
| Complex | Total at least 9, or any dimension scored 3. |

A single severe source of difficulty requires the complex tier even when the other
dimensions are simple. For example, a recoverable write protocol cannot average down
its failure complexity because its arithmetic is trivial.

### Straightforward algorithms

Existing docstrings are sufficient when they explain the purpose and contract, including
relevant assumptions, units, and surprising boundaries. Record the assessment in the
change description; a separate design note is unnecessary.

### Involved algorithms

Provide a focused explanation in an appropriate existing design document or a note under
`docs/algorithms/`. Include:

- Inputs, outputs, assumptions, units, and required ordering.
- Conceptual steps and decision rules, with the reasons for their ordering or precedence.
- Invariants and the argument that the approach preserves them.
- At least one worked example covering the main source of difficulty.
- Boundary cases, time and memory costs, and links to implementation and relevant tests.

### Complex algorithms

Provide a dedicated design note under `docs/algorithms/`, named for the behavior it
explains. Include everything required for involved algorithms, together with:

- A derivation or correctness argument explaining the nonobvious choices.
- Relevant alternatives and the tradeoffs behind the chosen approach.
- Difficult examples or counterexamples that expose incorrect approaches.
- Guarantees, limitations, and the numerical, temporal, resource, or recovery boundaries
  on which they depend.
- Links to applicable formal specifications and conformance checks, or the rationale for
  omitting formal verification as required by the formal-verification guide.

Use the form that explains the difficulty: timelines for history, decision tables for
policy, equations for numerical reasoning, and state diagrams with interruption tables
for recovery. A heuristic search must identify what it actually guarantees, including
whether it selects the best sampled result or establishes a global optimum.

Link algorithm notes from the relevant [Architecture](architecture.md) section and from
the owning module's docstring so maintainers can find the reasoning. Keep detailed
walkthroughs in documentation; prose in code continues to explain why, following the
conventions. Explain the conceptual algorithm rather than transcribing each code line.

Existing requirements, architecture sections, and formal inventories may supply parts
of an explanation by reference. Keep one authoritative explanation of each policy or
guarantee, and make the note understandable without duplicating those sources.

## SVG explanations

Algorithm notes under `docs/algorithms/` must make liberal use of SVG graphics to help
humans follow the reasoning. Plan figures alongside the explanation, including diagrams
for the main sources of difficulty wherever they aid understanding. Prefer several
focused figures near the relevant prose over one crowded diagram. Give each figure a
caption explaining what the reader should learn from it, and use the same terms and
worked examples as the surrounding text.

Use Markdown directly for linear sequences, checklists, ordered criteria, and collections
of text-only cards. Numbered boxes or arrows between successive steps do not add enough
explanatory value to justify an SVG. Use an ordered list when sequence matters, bullets
for independent items, and a table for textual comparisons or condition/action pairs.
Keep a diagram when its geometry, branching, alignment, mapping, or animation reveals a
relationship that the text alone makes harder to follow. A note needs no figure when
Markdown explains all of its reasoning clearly; there is no minimum figure count.
When replacing a list-like SVG, integrate its unique information into the note without
duplicating existing explanations, and remove the unused asset and its references.

Useful subjects include:

- Timelines showing observation order, policy deadlines, and later corrections.
- Ownership graphs showing aliases, competing claims, transfers, and retained history.
- Geometry overlays showing intersections, holes, shrinkage, and successive growth rings.
- Search diagrams showing candidate orientations, objective values, and refinement.
- Storage diagrams showing partitioning, encoded representations, and reconstruction.
- State diagrams showing durable writes, interruption points, and recovery paths.

Draw domain geometry in a form recognizable from the code's inputs: simple irregular
mapped perimeters for fires, orthogonal building footprints with wings or courtyards,
and plausible boundaries for geographic regions. Use a plan view for mapped geometry.
Keep rectangles and circles where they represent actual bounds, tiles, buffers around
points, chart marks, or process boxes. Preserve the relationships the example relies on,
including containment, holes, intersections, shared boundaries, and nearest points.
Recompute centroids, areas, and distances when a shape change affects a stated value.

Animate SVGs only when motion reveals a transformation, causal relationship, propagation,
or change in state that labels, arrows, and numbered steps do not explain as well.
Sequential highlighting that merely repeats an already-visible ordering is insufficient.
Each animation must have a specific explanatory purpose stated in its caption or nearby
prose. Do not animate a figure when motion adds no understanding.

Use the [corrected growth passes SVG](algorithms/corrected-growth-passes.svg), explained
in [Corrected history and growth rings](algorithms/corrected-growth-rings.md), as a
reference example of useful animation:

- Blue copies of all three original perimeters slide into the backward-intersection
  row. The originals remain visible, so readers can see where the working geometry
  comes from and compare it with later corrections.
- A translucent later perimeter slides over its predecessor. Ground outside the overlap
  dissolves, making intersection visible as an operation on area. Repeating this with
  the corrected middle perimeter shows how a later correction propagates backward.
- Copies of the corrected footprints descend into the forward-difference row, changing
  from blue to gold. The movement shows that this pass consumes the corrected results;
  the color transition marks their new role in the growth calculation. These complete
  footprints still include previously counted ground until subtraction occurs.
- A translucent copy of each complete corrected predecessor slides diagonally onto its
  successor, and previously counted ground dissolves. This explains why difference
  leaves only new growth and why the operand must include the full corrected footprint,
  including ground already counted in earlier rings.

The explanatory value comes from tracing the operands and watching the retained and
removed areas change. Numbers or a highlight moving between rows would convey only
order. Use motion to expose similarly concrete relationships in other algorithms, and
explain its meaning: here, sliding aligns the same geographic coordinates across
observations; it does not depict a fire moving across the landscape.

Keep animated stages labeled and visible long enough to follow. Make all essential
steps understandable without motion through labeled static states and accompanying
prose, including when animation is unsupported or reduced motion is requested. Show the
intermediate states of transformations in this static explanation; a final frame alone
is insufficient when those states carry the reasoning. Diagrams illustrate the
correctness argument; they do not replace its assumptions or guarantees.

All SVG diagrams must automatically support light and dark appearance.
Declare `color-scheme: light dark`, define a complete dark palette in unconditional
styles, and override it inside `@media (prefers-color-scheme: light)` for light
appearance. Dark must remain the fallback when the renderer does not support media
queries. Include an explicit background using the active palette. Theme backgrounds,
text, shape fills, gradient stops, borders, connectors, and arrowheads so every element
remains legible in both modes. Keep the styles inside the SVG so it works as a standalone
file and an embedded image. See the [monitor presentation
SVG](algorithms/assets/monitor-presentation.svg) for an example.

Save SVG assets beside the note or in its assets subdirectory, with descriptive names
and relative links from the note. Keep SVG sources readable and editable, with semantic
element IDs, scalable layouts, legible labels, and a descriptive title and description.
When boxes correspond to parameters, fields, or ordered outputs, arrange them in the
same order. Center arrows on their actual targets: the relevant box boundary for a
whole-node connection, or the specific parameter or subelement for an individual mapping.
When adding or changing a figure, inspect it in the intended documentation viewer at
normal reading width in both light and dark modes, and verify the dark fallback with
media queries disabled or ignored. For animated figures, inspect both the sequence and
its static or reduced-motion explanation, checking that the illustrated behavior matches
the note.

## Importance and verification

Assess behavioral importance separately. Even a straightforward rule that determines
published acreage needs an explicit policy contract. Consequences can increase the
documentation required without changing the complexity scores; record the reason for
that increase with the assessment.

The formal-verification requirements apply independently of this classification. Assess
formal verification during design and complete applicable models or proofs before
implementation. A low complexity score does not waive required modeling, proof, or
conformance checks; a high score alone does not decide which formal tool is appropriate.

Review the explanation alongside changes to the implementation, tests, and formal
contracts. If implementation exposes an additional exception, dependency, approximation,
or recovery state, reassess the behavior and update its documentation before completing
the change.

## Choosing an explanation

These existing behaviors illustrate what their explanations should address. They do
not substitute for a complete scored assessment of a proposed change.

| Behavior | Reasoning to document |
| --- | --- |
| Fire identity and history ownership | Correction propagation, competing claims, and ownership invariants. |
| Perimeter reconciliation | Conflicting observations and the distinction between surveys and republications. |
| Area selection | Freshness, growth, corroboration, and policy deadlines on a shared timeline. |
| Thumbnail orientation | Search objective, raster-dependent discontinuities, tie rules, and optimality limits. |
| Building centroids and indexing | Numerical stability, quantization, partitioning, and representation boundaries. |
| Corrected growth rings | Why backward correction precedes forward differencing, including shrinkage. |
| Log recovery | Durable transitions and the effect of interruption on loss and duplication. |

## Algorithm note template

Use these sections when creating a note. Scale each section to the behavior and the
required tier, and explain when a normally relevant concern does not apply.

1. **Contract and context:** Purpose, consumers, input domain, outputs, units, ordering,
   and environmental assumptions.
2. **Complexity assessment:** The five scores, their justifications, the resulting tier,
   and any additional documentation required by behavioral importance.
3. **Approach and invariants:** Conceptual steps, decision precedence, derivation or
   correctness argument, relevant alternatives and tradeoffs, and SVG figures where
   visual relationships help explain the main sources of difficulty.
4. **Worked examples and boundaries:** A representative example and the difficult cases
   that motivate the algorithm, including failure transitions when applicable. Use SVG
   walkthroughs where they help; explain the purpose of any animation and provide an
   understandable explanation without motion.
5. **Costs and limitations:** Time and memory costs in terms of named input sizes,
   numerical tolerances, resource bounds, and guarantees or deliberate exclusions.
6. **Implementation and verification:** Owning functions, ordinary tests, applicable
   formal models or proofs, conformance checks, and their assumptions and coverage limits.
