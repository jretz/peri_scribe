# Terminal rendering and image sizing

## Contract and assessment

Terminal row shading should preserve alternate-row brightness, add a recognizable status
hue, and leave focus/selection backgrounds, text and mouse targets intact. Pane resizing
should give mouse and keyboard users the same limits, expressed in terminal cells and
stored as flexible proportions. These presentation algorithms consume Textual/Rich colors,
segment metadata, pane dimensions and pointer positions; they do not decide health status.

| Dimension | Score | Concrete reason |
| --- | --- | --- |
| History and state | 1 | A drag retains its starting screen coordinate and pane size. |
| Rule interaction | 2 | Row parity, status tint and interaction highlights have precedence; pane limits adapt to small terminals. |
| Mathematical reasoning | 2 | RGB tint is constrained to the channel gamut while preserving perceptual brightness before rounding. |
| Scale and representation | 1 | Rendered segment lists and row metadata are ordinary bounded screen data. |
| Failure and concurrency | 0 | These pure rendering and UI-event calculations own no durable protocol. |

**Total 6: involved.** Styling constants, text formatting, command wiring and screenshot
adapters remain straightforward; their existing contracts and ordinary tests suffice.

## Approach and invariants

For background RGB vector b and tint t, let brightness Y use Textual's weighted RGB
brightness:

1. Remove the brightness component from the proposed channel displacement:
   `d = t - b - 255 × (Y(t) - Y(b))`. Because the brightness weights sum to one,
   Y(d) is zero.
2. Start with blend amount 0.12, then reduce it to the most restrictive channel boundary
   so each component of `b + amount × d` stays in [0,255].
3. Round channels and preserve alpha.

This retains background brightness within RGB rounding precision. Ordinary direct blending
would shift brightness and weaken row striping as status hues vary.

`AlternatingRows.apply` obtains logical row metadata in row/line/option precedence. Only
segments whose existing background equals the widget background are eligible. Odd rows
blend the background 5% toward contrast text; a status tint is then applied to that shaded
background. Existing selection/focus highlights are preserved by the equality guard.
Text, segment control data and metadata survive replacement. Row identity, rather than
screen y, keeps stripes aligned through scrolling, wrapping and folded trees.

`PaneDivider.resize_panes` sets width minima to 24/24 cells or height minima to 8/3 cells,
reducing each to at most half the available total. Clamp the requested first-pane size to
`[minimum_before, total - minimum_after]`, then assign `size fr` and `(total - size) fr`.
Using screen coordinates relative to the drag start prevents the moving divider itself
from changing the meaning of pointer displacement.

![One clamp protects both panes](assets/terminal-panes.svg)

*The request moves beyond both limits while the actual divider stops, exposing how the
clamp protects each pane. Motion smooths the implementation's cell-sized updates. The
three fixed splits preserve the comparison without animation: for 80 total cells, requests
10, 40, and 70 produce 24/56, 40/40, and 56/24. The smaller terminal shows why both minima
must be reduced before clamping.*

## Worked examples and boundaries

A gray background (100,100,100) tinted toward red (255,0,0) has a brightness-adjusted
channel displacement approximately (178.755,-76.245,-76.245). With amount 0.12 the rounded
result is (121,91,91), with nearly unchanged weighted brightness. Saturated backgrounds
may reduce the allowed amount to zero; staying inside RGB bounds takes precedence over
showing a tint. Alpha is unchanged. Brightness here is Textual's weighted RGB measure,
not a perceptually uniform color-space guarantee.

For 80 available horizontal cells, a 70-cell request clamps to 56/24. For a 20-cell total,
each minimum reduces to 10 and the split is 10/10. A nonpositive total produces no style
change. Very small totals may give a zero-cell minimum; the function cannot create screen
space. Arrow keys call the same clamp in one-cell increments.

A selected row already painted with a highlight keeps it, even if the row is odd and has
a warning tint. Repainting every segment unconditionally would erase that interaction
feedback. A wrapped logical row keeps the same parity on all its display lines.

## Costs and verification

Tinting and pane clamping take constant time and memory. Shading is O(S) for S rendered
segments with O(S) output, and its 256-entry tint cache is bounded. The algorithm assumes
valid framework colors and metadata; terminal palette rendering remains outside its
numerical guarantee.

Owners: [striping.py](../../src/peri_scribe/monitor/striping.py) and
[widgets.py](../../src/peri_scribe/monitor/widgets.py). Ordinary
[striping tests](../../tests/tests/standard/peri_scribe/monitor/test_striping.py),
[widget tests](../../tests/tests/standard/peri_scribe/monitor/test_widgets.py),
[app tint tests](../../tests/tests/standard/peri_scribe/monitor/test_app_tints.py), and
[scrolling tests](../../tests/tests/standard/peri_scribe/monitor/test_app_scrolling.py)
cover rounding, highlighted cells and user interaction. No additional formal model is
needed for this presentation-only behavior: the arithmetic argument plus ordinary
numerical/UI checks cover the useful guarantee without changing monitor health policy or
resource ownership. Those contracts remain in [monitor evidence](monitor-evidence.md)
and [worker lifetimes](worker-lifetimes.md).

## Inline image sizing, terminal queries, and fallbacks

[terminal_images.py](../../src/peri_scribe/terminal_images.py) supplies OSC 1337 image
width/height controls to the [latency display](../../src/peri_scribe/show_latencies/cli.py).
Inputs are an output text stream, a finite positive maximum width with pixel units, and
a
finite positive aspect ratio (image width divided by image height). These numerical
preconditions come from the caller; the sizing helpers do not validate arbitrary invalid
ratios. Outputs are decimal character-cell dimensions when trustworthy terminal geometry
is available, otherwise explicit pixel dimensions.

This is a separate **involved** algorithm, assessed as follows:

| Dimension | Score | Concrete reason |
| --- | --- | --- |
| History and state | 1 | The query temporarily changes terminal input mode and retains its original settings. |
| Rule interaction | 2 | Output redirection, foreground ownership, pending input, logical size reports and OS geometry determine fallback precedence. |
| Mathematical reasoning | 1 | Width uses a floor and height a ceiling to fit cell bounds while respecting image aspect ratio. |
| Scale and representation | 1 | One bounded byte reply is parsed as positive logical cell dimensions. |
| Failure and concurrency | 2 | Terminal query/response and mode restoration have independent failure paths; user input can arrive during the query. |

**Total 7.** This bounded terminal adapter does not claim lossless multiplexing of arbitrary
user input with terminal responses.

![Logical sizing, OS geometry and explicit-pixel fallback](assets/terminal-image-sizing.svg)

*Precedence is static: prefer a logical cell report, then usable OS geometry, then explicit
pixel controls. The image width leaves one terminal column free when cell sizing succeeds.
Motion would not improve this decision diagram.*

The algorithm prepares the pixel fallback first: `int(maximum_width)` pixels wide and
`round(width / aspect_ratio)` pixels high. Redirected streams immediately use it. For a
TTY, obtain rows, columns and optional pixel dimensions with `TIOCGWINSZ`; one or fewer
columns cannot support the one-column-margin policy and uses fallback.

Query the **output** terminal opened read/write, so redirected standard input does not
prevent measuring an interactive output. Before changing input mode, skip the query if
input is already readable or the process group does not own the foreground terminal.
Save terminal attributes, temporarily enter cbreak mode, and check readability again:
this reveals unfinished canonical input that must remain queued for the shell. Restore
saved attributes in `finally`, including parse failure, timeout and interruption.

An eligible query sends `ReportCellSize` and reads one byte at a time until BEL or ST
terminates a reply. A monotonic deadline limits the response wait to 250 milliseconds;
128 bytes bound the reply. Full-match parsing accepts only finite positive height and
width. An optional backing-pixel scale is intentionally ignored: reported dimensions
are logical display points, represented with the shared pixel unit. Multiplying by a
high-density scale would make the displayed image artificially small.

If no usable report arrives, derive cell width/height from OS pixel dimensions only when
rows and both pixel dimensions are present. Reject an unavailable cell size or one whose
width exceeds the image cap. For C columns and logical cell dimensions cw/ch, choose
`w = max(1, min(C - 1, floor(maximum_width / cw)))`, then
`h = ceil(w × cw / ch / aspect_ratio)`. These integer cell dimensions reserve the margin,
keep displayed width within the cap, and round the aspect-derived height upward. The OSC
image renderer owns actual drawing and aspect-preservation behavior.

For 100 columns, an 8-by-16 logical cell, a 600-pixel cap and aspect ratio 2, width is
`min(99,75) = 75` cells and height is `ceil(75 × 8 / 16 / 2) = 19` cells. A report with
backing scale 2 produces the same result. If one cell is 800 pixels wide, cell sizing
cannot honor the cap and returns the explicit 600px-by-300px fallback. Without cell
geometry, that fallback preserves the requested cap but cannot guarantee fitting the
unknown visible terminal width.

Sizing arithmetic is constant work. The query uses O(R) time and memory for at most
R = 128 reply bytes, with a monotonic response-wait budget. This is not a hard deadline
for every OS operation: opening/writing the terminal and restoring attributes depend on
the operating system. Input arriving after the pre-query checks may be consumed as a
nonmatching response; the guards preserve already queued input, not all concurrent
keystrokes. Restoration assumes the OS accepts the saved attributes. Terminal access,
ioctl or parsing failure uses fallback without inventing cell measurements.

[Terminal image tests](../../tests/tests/standard/peri_scribe/test_terminal_images.py)
cover high-density logical reports, width caps, OS fallback, redirected streams, missing
file descriptors, background process groups, queued/unfinished input, bounded partial
replies and attribute restoration after errors. The existing adapter has no dedicated
formal model: these deterministic parsing/arithmetic checks and controlled terminal
boundary tests cover its stated finite behavior. This documentation-only assessment adds
no runtime protocol; a change to query ownership or input-consumption guarantees requires
formal-design assessment under the [verification guide](../formal_verification.md).
