# Writing Style

Apply this guidance to project-authored text intended for people to read, whether it
lives in documentation, comments, docstrings, help text, or generated output. Use it
where explanation helps. Short labels should stay short, and identifiers, quoted source
text, and fixed legal wording need to retain their required forms.

The goal is to make it easy for readers to understand the point and decide whether they
agree with it. That requires showing enough of the reasoning that they can evaluate it
for themselves.

Use plain language and write conversationally. Assume the reader is intelligent, but
may not have the same background or know why a particular detail matters. Explain those
connections. If understanding one thing depends on understanding another, put them in
that order.

Start with the point or observation, then work through why it matters. Concrete examples
help. So do numbers, especially when a simple calculation makes the implications easier
to see. Be explicit about the assumptions behind those calculations. A precise-looking
answer isn't particularly useful if nobody knows what it's assuming.

Be clear about what's known and what's a judgment. When something is uncertain, explain
where the uncertainty lies. “Very roughly” is useful when it's an accurate description
of a calculation. There's no need to qualify every sentence just because some part of
the argument is uncertain.

Relevant experience can help explain how a conclusion was reached. Explain the
connection, and don't invent experiences or opinions to make the writing sound more
personal.

If there's a reason to disagree, explain it directly. What's the assumption? Does it
hold? What happens if it doesn't? A question can help readers think through an
implication, but it should do some work.

Most of this should fit naturally into paragraphs. Use lists when there are distinct
items or steps that are easier to follow that way. Keep the wording straightforward and
leave out promotional language and unnecessary jargon. If something is interesting,
surprising, or frustrating, it's fine for that to come through. Explain what makes it
so.

Browser reports should follow the reader's light or dark mode preference. Use
`prefers-color-scheme` and `color-scheme` for report surfaces, text, and controls, and
make embedded charts adapt too. Avoid fixed white chart backgrounds in dark reports.
Check the rendered report in both modes, including chart labels and legends.
