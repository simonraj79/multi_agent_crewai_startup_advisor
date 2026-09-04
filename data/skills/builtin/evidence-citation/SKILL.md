---
name: evidence-citation
description: Every claim cites a URL a tool actually returned; an unknown is stated as unknown and never filled in. Use whenever writing findings from tool output.
metadata:
  version: "1"
---

# Citing evidence

## The rule

**Every claim of fact cites a URL that appeared in a tool result during this
run.** Not a URL you know exists. Not a plausible URL. Not the homepage of a
company a tool mentioned. One that a tool returned, spelled exactly as it
returned it.

A citation is checkable, and here it is checked: the URLs in a finding are
compared against the URLs the tools produced, and a claim citing anything else
fails closure. So an invented link does not merely mislead a reader - it fails,
loudly, after the work is done.

## An unknown is a finding

"No source established whether this competitor is vendor-owned" is a complete,
useful sentence. It is better than a guess and better than silence, because the
scorer downstream treats an absent answer differently from a negative one.

Never round an unknown to a `false`. Where a field can be "yes", "no" or "not
established", use the third.

## Copying a label is not evidence

Tool envelopes report what was retrieved and pass no judgement. Do not copy a
field out of a tool result into a finding as though the tool had decided
something: overlap counts and matched terms are evidence *about* a result, and
turning them into a verdict is the reader's job, not the tool's.

## Say which tool, and when

A finding carries the tool that produced it and the retrieval time. Two
findings from the same URL retrieved a month apart are not the same evidence,
and a reader who cannot tell them apart cannot judge either.

## If a tool failed, the finding is that the tool failed

Do not write around an outage. `status: failed` produces "the feasibility
search did not run", never "no repositories exist". The second is the strongest
possible claim, made from no evidence at all.
