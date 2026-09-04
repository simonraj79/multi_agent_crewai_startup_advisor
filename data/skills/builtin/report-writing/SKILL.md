---
name: report-writing
description: The exact Markdown subset the console renders, and how to structure a report so nothing is silently dropped. Use when writing a final report or any Markdown a person will read in the app.
metadata:
  version: "1"
---

# Writing a report this console can render

## The renderer is a subset, and anything outside it degrades

The console does not use a general Markdown library. It escapes every character
of your text first and then recognises a small, fixed set of structures, so
nothing you write can become markup by accident. The cost is that anything
outside the set renders as an escaped paragraph - visible, ugly, and not what
you meant.

**Supported:**

- `#`, `##`, `###` headings
- paragraphs
- `-` bulleted lists and `1.` numbered lists
- `**bold**` and `*italic*`
- `` `code spans` ``
- fenced code blocks
- `[link text](https://example.com)`
- `>` blockquotes
- `---` horizontal rules

**Not supported, and it will show:**

- tables
- raw HTML of any kind
- footnotes, definition lists, task lists
- images
- nested lists deeper than one level

A link is rendered only when its target is `http:` or `https:`. Anything else
renders as text, so do not put a `mailto:` or a bare domain in link syntax and
expect it to work.

## Structure

Lead with the answer. A reader who stops after the first paragraph should have
the verdict and the confidence, not the methodology.

Then, in order:

1. **The verdict**, with its score and confidence band.
2. **What the evidence supports**, one section per dimension, each claim
   carrying its link.
3. **What the evidence does not settle** - named, not omitted. This section is
   the one that makes the rest trustworthy.
4. **What would change the answer.**

## Say the confidence in words as well as numbers

Low confidence is stated in the prose, not only in a field. A report that reads
with certainty and carries `confidence: 0.17` is a report whose two halves
disagree, and the reader will believe the half they read first.

## Every link in the report came from a tool

The final text is checked for URL closure against what the tools returned. A
link that appeared for the first time in the writing stage fails, whatever it
points at.
