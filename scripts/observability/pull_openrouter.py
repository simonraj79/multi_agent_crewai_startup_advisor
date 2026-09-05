"""Resolve each generation id against OpenRouter's own record.

Serves the OPENROUTER column of DoD rows **E5** and **E1**: the only figure in
this programme that is neither an estimate nor a copy of one.
`GET /api/v1/generation?id=` returns the cost OpenRouter actually billed, the
tokens it actually counted (native and normalised), and the provider that
actually served the call - none of which reaches the application, because
`_extract_openai_token_usage` whitelists five keys and drops the rest
(`audit/app-surface.md` §3.4).

The ids come from `app-figures.json`'s `response_ids`, which
`pull_app_run.py` lifts off the LLM `after` frames
(`events/serializer.py:525`). A `langfuse-figures.json` works too, and so does
a bare JSON list.

**404 is expected and is retried.** A generation is not queryable the instant
the call returns; the record is indexed a few seconds later. A 404 that
survives every attempt is reported as `not_found` and counted, never silently
dropped - a missing record is exactly the E1 evidence a verifier needs.

Reads `OPENROUTER_API_KEY` from the environment. Every request is a read; this
script cannot spend money.

Usage:

    .venv/Scripts/python.exe scripts/observability/pull_openrouter.py \
        --response-ids-from DIR/app-figures.json --out DIR
"""

from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path
from typing import Any, Mapping

sys.path.insert(0, str(Path(__file__).resolve().parent))

from _common import (  # noqa: E402
    Http,
    HttpError,
    add_call,
    bucket_for,
    bucket_table,
    ensure_dir,
    env_required,
    load_env,
    md_table,
    now_iso,
    read_json,
    secs,
    sum_buckets,
    usd,
    write_json_redacted,
    write_text_redacted,
)

GENERATION_URL = "https://openrouter.ai"
GENERATION_PATH = "/api/v1/generation"


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Fetch OpenRouter's own record for each generation id.",
    )
    parser.add_argument(
        "--response-ids-from",
        action="append",
        default=[],
        help=(
            "a JSON file carrying the ids: app-figures.json, "
            "langfuse-figures.json, or a plain list. Repeatable."
        ),
    )
    parser.add_argument(
        "--response-id", action="append", default=[], help="one id (repeatable)"
    )
    parser.add_argument("--out", required=True, help="directory to write into")
    parser.add_argument(
        "--retries",
        type=int,
        default=4,
        help="attempts per id when the answer is 404 (default 4)",
    )
    parser.add_argument(
        "--retry-delay",
        type=float,
        default=5.0,
        help="seconds between 404 retries (default 5)",
    )
    parser.add_argument("--timeout", type=float, default=30.0)
    return parser.parse_args(argv)


def ids_from_file(path: str) -> list[str]:
    """Every generation id a figures file carries, in order, deduplicated.

    Four accepted shapes, because the three producers in this tree write
    different files and a verifier should not have to remember which: a bare
    list, `{response_ids: [...]}`, `{calls: [{response_id}]}`, and both at once.
    """

    payload = read_json(path)
    found: list[str] = []
    if isinstance(payload, list):
        found = [str(item) for item in payload if isinstance(item, str)]
    elif isinstance(payload, Mapping):
        for item in payload.get("response_ids") or []:
            if item:
                found.append(str(item))
        for call in payload.get("calls") or []:
            if isinstance(call, Mapping) and call.get("response_id"):
                found.append(str(call["response_id"]))
    ordered: list[str] = []
    seen: set[str] = set()
    for item in found:
        if item not in seen:
            seen.add(item)
            ordered.append(item)
    return ordered


def fetch_generation(
    http: Http, generation_id: str, retries: int, delay: float
) -> dict[str, Any]:
    last_status = 0
    for attempt in range(1, max(1, retries) + 1):
        try:
            status, body = http.get(
                GENERATION_PATH, {"id": generation_id}, allow_status=(404,)
            )
        except HttpError as exc:
            return {
                "id": generation_id,
                "found": False,
                "reason": f"http {exc.status}",
                "attempts": attempt,
            }
        last_status = status
        if status == 200 and isinstance(body, Mapping):
            data = body.get("data")
            if isinstance(data, Mapping):
                return {
                    "id": generation_id,
                    "found": True,
                    "attempts": attempt,
                    "record": dict(data),
                }
            return {
                "id": generation_id,
                "found": False,
                "reason": "200 with no data object",
                "attempts": attempt,
            }
        if attempt < retries:
            time.sleep(delay)
    return {
        "id": generation_id,
        "found": False,
        "reason": f"http {last_status} after {retries} attempts (not yet indexed?)",
        "attempts": retries,
    }


def derive(results: list[dict[str, Any]], requested: list[str]) -> dict[str, Any]:
    by_model: dict[str, dict[str, Any]] = {}
    by_provider: dict[str, dict[str, Any]] = {}
    calls: list[dict[str, Any]] = []
    native_in = native_out = normalised_in = normalised_out = 0
    total_cost = 0.0
    upstream_cost = 0.0

    for result in results:
        if not result.get("found"):
            continue
        record = result["record"]
        model = str(record.get("model") or "")
        provider = str(record.get("provider_name") or "")
        cost = record.get("total_cost")
        try:
            cost_value = float(cost) if cost is not None else None
        except (TypeError, ValueError):
            cost_value = None
        n_in = int(record.get("native_tokens_prompt") or 0)
        n_out = int(record.get("native_tokens_completion") or 0)
        native_in += n_in
        native_out += n_out
        normalised_in += int(record.get("tokens_prompt") or 0)
        normalised_out += int(record.get("tokens_completion") or 0)
        if cost_value is not None:
            total_cost += cost_value
        try:
            upstream_cost += float(record.get("upstream_inference_cost") or 0.0)
        except (TypeError, ValueError):
            pass
        calls.append(
            {
                "response_id": record.get("id"),
                "model": model,
                "provider": provider,
                "created_at": record.get("created_at"),
                "input_tokens": n_in,
                "output_tokens": n_out,
                "total_tokens": n_in + n_out,
                "normalised_input_tokens": int(record.get("tokens_prompt") or 0),
                "normalised_output_tokens": int(record.get("tokens_completion") or 0),
                "reasoning_tokens": int(record.get("native_tokens_reasoning") or 0),
                "cached_tokens": int(record.get("native_tokens_cached") or 0),
                "cost_usd": cost_value,
                "upstream_inference_cost": record.get("upstream_inference_cost"),
                "cache_discount": record.get("cache_discount"),
                "finish_reason": record.get("finish_reason"),
                "latency_ms": record.get("latency"),
                "generation_time_ms": record.get("generation_time"),
                "streamed": record.get("streamed"),
                "cancelled": record.get("cancelled"),
                "is_byok": record.get("is_byok"),
                "app_id": record.get("app_id"),
                "session_id": record.get("session_id"),
                "request_id": record.get("request_id"),
            }
        )
        for mapping, key in ((by_model, model), (by_provider, provider)):
            add_call(
                bucket_for(mapping, key),
                input_tokens=n_in,
                output_tokens=n_out,
                total_tokens=n_in + n_out,
                cost_usd=cost_value,
            )

    not_found = [r for r in results if not r.get("found")]
    return {
        "source": "openrouter",
        "generated_at": now_iso(),
        "requested_ids": requested,
        "requested": len(requested),
        "found": len(calls),
        "not_found": [
            {"id": r["id"], "reason": r.get("reason"), "attempts": r.get("attempts")}
            for r in not_found
        ],
        "not_found_count": len(not_found),
        "totals": {
            "calls": len(calls),
            "input_tokens": native_in,
            "output_tokens": native_out,
            "total_tokens": native_in + native_out,
            "cost_usd": total_cost,
            "calls_without_cost": sum(1 for c in calls if c["cost_usd"] is None),
            "normalised_input_tokens": normalised_in,
            "normalised_output_tokens": normalised_out,
            "upstream_inference_cost": upstream_cost,
        },
        "by_model": by_model,
        "by_provider": by_provider,
        "calls": calls,
        "response_ids": [c["response_id"] for c in calls],
    }


def render(figures: Mapping[str, Any]) -> str:
    totals = figures["totals"]
    lines = [
        "# OpenRouter figures",
        "",
        f"Generated {figures['generated_at']}. DoD E1 / E5, OpenRouter column.",
        "",
        "Token counts here are OpenRouter's **native** counts; `tokens_prompt` /",
        "`tokens_completion` are its normalised (GPT-tokeniser) figures and are",
        "reported separately, because comparing a native count against the app's",
        "provider-reported count is the like-for-like comparison and the",
        "normalised one is not.",
        "",
        md_table(
            ["metric", "value"],
            [
                ["ids requested", figures["requested"]],
                ["records found", figures["found"]],
                ["NOT found", figures["not_found_count"]],
                ["input tokens (native)", totals["input_tokens"]],
                ["output tokens (native)", totals["output_tokens"]],
                ["total tokens (native)", totals["total_tokens"]],
                ["input tokens (normalised)", totals["normalised_input_tokens"]],
                ["output tokens (normalised)", totals["normalised_output_tokens"]],
                ["cost, billed", usd(totals["cost_usd"])],
                ["upstream inference cost", usd(totals["upstream_inference_cost"])],
                ["records with no cost", totals["calls_without_cost"]],
            ],
        ),
        "",
        "## Per model",
        "",
        bucket_table(figures["by_model"], label="model"),
        "",
        "## Per serving provider",
        "",
        bucket_table(figures["by_provider"], label="provider"),
        "",
        "## Per call",
        "",
        md_table(
            ["generation id", "model", "provider", "in", "out", "cost", "latency ms", "finish"],
            [
                [
                    call["response_id"],
                    call["model"],
                    call["provider"],
                    call["input_tokens"],
                    call["output_tokens"],
                    usd(call["cost_usd"]),
                    call["latency_ms"],
                    call["finish_reason"],
                ]
                for call in figures["calls"]
            ],
        ),
        "",
    ]
    if figures["not_found"]:
        lines += [
            "## Not found",
            "",
            md_table(
                ["generation id", "reason", "attempts"],
                [
                    [entry["id"], entry["reason"], entry["attempts"]]
                    for entry in figures["not_found"]
                ],
            ),
            "",
        ]
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    load_env()
    out_dir = ensure_dir(args.out)

    ids: list[str] = []
    seen: set[str] = set()
    for path in args.response_ids_from:
        for value in ids_from_file(path):
            if value not in seen:
                seen.add(value)
                ids.append(value)
    for value in args.response_id:
        if value not in seen:
            seen.add(value)
            ids.append(value)

    if not ids:
        write_text_redacted(
            out_dir,
            "openrouter.md",
            "\n".join(
                [
                    "# OpenRouter figures",
                    "",
                    f"Generated {now_iso()}.",
                    "",
                    "**No generation ids were supplied.** That is the expected answer for",
                    "a SYNTHETIC run: `service/runner.py` writes `response_id: None` on",
                    "the LLM after-frame, because a double has no honest provider id to",
                    "invent. A PAID run whose ids are all absent is a defect - the id is",
                    "on `LLMCallCompletedEvent` and `events/serializer.py:525` records it.",
                ]
            ),
        )
        write_json_redacted(
            out_dir,
            "openrouter-figures.json",
            derive([], []),
        )
        print("no generation ids supplied; wrote the empty-case note and figures.")
        return 0

    key = env_required("OPENROUTER_API_KEY")
    results: list[dict[str, Any]] = []
    with Http(
        GENERATION_URL,
        headers={"Authorization": f"Bearer {key}"},
        timeout=args.timeout,
    ) as http:
        for index, generation_id in enumerate(ids, start=1):
            result = fetch_generation(http, generation_id, args.retries, args.retry_delay)
            results.append(result)
            print(
                f"[{index}/{len(ids)}] {generation_id}: "
                + ("found" if result.get("found") else f"NOT FOUND ({result.get('reason')})"),
                file=sys.stderr,
            )

    write_json_redacted(out_dir, "openrouter-generations.json", results)
    figures = derive(results, ids)
    write_json_redacted(out_dir, "openrouter-figures.json", figures)
    write_text_redacted(out_dir, "openrouter.md", render(figures))
    print(render(figures))
    print(f"wrote {out_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
