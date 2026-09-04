---
name: hn-signal-reading
description: How to classify a discussion thread as PROBLEM, OPINION or OFF_TOPIC and count usable threads honestly. Use when reading Hacker News or any community discussion as demand evidence.
license: MIT
metadata:
  version: "1"
---

# Reading community signal

## Three labels, and the definitions are exact

Every retrieved thread gets exactly one:

- **PROBLEM** - somebody describes a difficulty they actually have. They are
  the one with the problem, and they say what it costs them: time, money,
  a workaround they maintain, a thing they cannot do.
- **OPINION** - somebody has a view about the area. Interesting, and not
  evidence of demand. "This space is overdue for disruption" is an opinion.
  So is "I would use that".
- **OFF_TOPIC** - the thread matched the search and is about something else.

A thread that describes somebody *else's* problem is an OPINION. The
distinction is not pedantry: a market is people with a problem, and a market of
commentators is not one.

## Count usable threads, not rows

A tool may return several comments from one story. They share one URL and they
are **one thread**. Count distinct threads, and say how many of the retrieved
threads you discarded and why.

## Points and comment counts are not demand

A high score means the title was interesting. It says nothing about whether
anybody has the problem. Never infer demand from points alone, and never infer
its absence from a low score - a precise, small thread from somebody living the
problem outweighs a large thread of speculation.

Where the tool reported no score at all, say so rather than treating a missing
number as zero.

## Say what the evidence cannot support

If the search returned three threads and two are OPINION, the honest finding is
"one usable thread", not "weak demand". The first is a fact about what was
retrieved; the second is a conclusion the retrieval cannot carry. A downstream
scorer can work with the first and will be misled by the second.

If a query returned nothing, broaden it once and report both queries before
concluding anything.
