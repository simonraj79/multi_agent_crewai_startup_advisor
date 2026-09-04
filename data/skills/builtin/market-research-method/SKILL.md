---
name: market-research-method
description: How to search for market evidence and read a tool envelope, so a search returns a market rather than a phrasing. Use before running any market or web search tool.
license: MIT
metadata:
  version: "1"
---

# Market research method

## Write the query as keywords, specific to broad

A search tool is not a colleague. Prose queries return nothing and the nothing
looks like an absent market.

This was measured, not guessed. Against the live tools:

```text
"AI tool creates educational materials assessment"   -> 0 results
"AI grading teachers"                                -> 5 results
"AI tool that creates educational materials..."      -> 1 repository
"quiz generator LLM"                                 -> 5 repositories
```

Two to four keywords, ordered from the specific to the broad. If the specific
query returns nothing, broaden and say so; do not conclude from the first
empty answer.

Semantic search engines are the exception. A tool that embeds the query
tolerates a phrase, so do not shorten a query for a semantic search when the
phrase carries meaning the keywords would lose.

## Read the envelope before you read the results

Every tool here answers with the same object:

```json
{"status": "...", "tool": "...", "query": "...", "retrieved_at": "...",
 "result_count": 0, "results": [], "notes": "..."}
```

`status` is the first thing to read, and there are four answers:

- `ok` - the results are evidence.
- `failed` - the tool did not run. This is **not** "the market is empty".
- `rate_limited` - the provider refused, temporarily. Also not an empty market.
- Anything else - treat as `failed`.

Say which one you got. A branch that reports "no competitors found" over a
`failed` envelope has invented the strongest possible finding out of an
outage.

## Record three things about every source

1. The **URL** the tool returned, exactly as it returned it.
2. The **date** the source carries.
3. Whether that date is the source's own or the moment you retrieved it.

The third is the one that gets dropped, and dropping it biases every age
calculation young: a page with no date, stamped with today, reads as fresh
evidence when it is evidence of nothing. If the date is the retrieval time,
say so.

## Name the buyer, or say you could not

"Is there money, and can you name whose?" is two questions. A category-revenue
figure with no named segment answers the first and not the second. Report both
halves separately rather than letting a large number stand in for a buyer.
