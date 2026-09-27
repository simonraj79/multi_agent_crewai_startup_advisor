"""The teaching evaluation loop, end to end, against a real backend.

`docs/observability/TEACHING-EVAL-LOOP.md` is the problem statement and the
pre-registered protocol; this file is the protocol made executable, so the rule
that rates a run is applied identically to every run of both versions.

    emit      write data/examples/teaching/formative-feedback-tutor.v{1,2}.json
    run       create + publish v1, run the eight submissions, rate each by the
              rule; then save + publish v2 and do the same. Writes runs.json.
    evaluate  Compare v1 vs v2, export the Good runs, one model review, and
              OpenRouter billed cost per run. Writes compare.json, evalset.ndjson,
              review.json, openrouter.json.

Every call goes to `--base` with a bearer token minted by `mint_identity.py`,
so the caller has an identity (and, with ADMIN_EMAILS set to its subject, is
the admin the evaluation routes require). Nothing here spends money by itself:
it is the backend on `--base` that calls models, and only when a run is
launched or a review is requested.
"""

from __future__ import annotations

import argparse
import copy
import json
import re
import subprocess
import sys
import time
import urllib.error
import urllib.request
import uuid
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
EXAMPLES = ROOT / "data" / "examples" / "teaching"
EVIDENCE = ROOT / "docs" / "observability" / "evidence" / "teaching-loop"
# The authored-agent defaults are copied from a committed template fixture
# rather than retyped: `BuilderModel` is extra="forbid" with twenty-two fields,
# and a fixture the frontend and the server both already agree on is the one
# spelling guaranteed to parse.
AGENT_FIXTURE = ROOT / "frontend" / "tests" / "fixtures" / "templates" / "reflection-loop.json"

WORD_LIMIT = 120
FEEDBACK_MARKER = "FEEDBACK FOR THE STUDENT:"

# ---------------------------------------------------------------------------
# The workflow
# ---------------------------------------------------------------------------

TUTOR_V1 = {
    "backstory": (
        "You are a patient, thorough maths and science tutor. Students learn best "
        "when they can see the complete correct method, so you always walk through "
        "the full working and make sure they leave knowing the right answer."
    ),
    "description": (
        "A student answered the question below. An assessor has already diagnosed "
        "their answer.\n\nSUBMISSION:\n{submission}\n\nASSESSMENT:\n{assessment}\n\n"
        "Explain clearly what the student got wrong, show the full correct method "
        "step by step, and state the correct final answer so they can check their "
        "work. If they were right, confirm it and explain why."
    ),
    "expected": "Feedback addressed to the student, in Markdown.",
}

TUTOR_V2 = {
    "backstory": (
        "You give formative feedback, not solutions. Research on feedback is clear "
        "that telling a student the answer ends their thinking, so you name the "
        "misconception, give one hint and ask one question that lets them find the "
        "answer themselves."
    ),
    "description": (
        "A student answered the question below. An assessor has already diagnosed "
        "their answer.\n\nSUBMISSION:\n{submission}\n\nASSESSMENT:\n{assessment}\n\n"
        "Write feedback addressed to the student.\n"
        "If the answer is wrong or partly wrong: (1) name the misconception in one "
        "sentence, without blaming; (2) give ONE hint about the method; (3) end with "
        "ONE guiding question they can answer themselves. NEVER state the correct "
        "final answer, the correct value, or the correct term, and do not work the "
        "problem through for them.\n"
        "If the answer is right: say specifically what they did well and ask one "
        "extension question.\n"
        "At most 90 words."
    ),
    "expected": (
        "At most 90 words of feedback addressed to the student, in Markdown, that "
        "does not contain the correct final answer."
    ),
}


# v3 = v2 plus ONE sentence, added after v2's only Bad run named the answer to a
# "why" question inside its own guiding question (TEACHING-EVAL-LOOP.md 4a).
TUTOR_V3 = dict(TUTOR_V2)
TUTOR_V3["description"] = TUTOR_V2["description"].replace(
    "At most 90 words.",
    "For a 'why' or 'what' question, do not name the scientific term or quantity "
    "that answers it, even inside the hint or the question; point the student at "
    "something they can observe or check instead.\nAt most 90 words.",
)

TUTORS = {1: TUTOR_V1, 2: TUTOR_V2, 3: TUTOR_V3}


def _agent_defaults() -> dict[str, Any]:
    fixture = json.loads(AGENT_FIXTURE.read_text(encoding="utf-8"))
    for node in fixture["document"]["nodes"]:
        if node["kind"] == "agent":
            return copy.deepcopy(node["config"])
    raise SystemExit(f"no agent node in {AGENT_FIXTURE}")


def _agent(node_id: str, label: str, y: int, *, role: str, goal: str, backstory: str,
           description: str, expected: str, inputs: dict[str, str],
           schema: dict[str, str] | None = None, markdown: bool = False) -> dict[str, Any]:
    config = _agent_defaults()
    config.update(
        role=role, goal=goal, backstory=backstory, prompt_inputs=inputs,
    )
    config["task"].update(
        description=description, expected_output=expected,
        output_schema=schema, markdown=markdown,
    )
    return {"id": node_id, "kind": "agent", "label": label,
            "position": {"x": 340, "y": y}, "config": config}


def _edge(n: int, source: str, target: str, port: str = "out") -> dict[str, Any]:
    return {"id": f"e{n}", "source": source, "source_port": port,
            "target": target, "target_port": "in"}


def build_document(version: int) -> dict[str, Any]:
    tutor = TUTORS[version]
    nodes = [
        {"id": "submission", "kind": "input", "label": "Submission",
         "position": {"x": 340, "y": 0},
         "config": {"field": "submission",
                    "label": "The question and the student's answer",
                    "max_chars": 2000, "required": True}},
        {"id": "teacher_check", "kind": "gate", "label": "Teacher check",
         "position": {"x": 340, "y": 160},
         "config": {"message": "An assessor and a tutor are about to read this submission. Approve it, or send it back.",
                    "editable_fields": [], "max_turns": 1, "expiry_seconds": 1800}},
        _agent(
            "assess", "Assess", 320,
            role="Assessor",
            goal="Decide whether a student's answer is correct and name the misconception behind it if it is not.",
            backstory=("You mark secondary-school maths and science. You judge the final "
                       "answer and the reasoning the student gave, and you name the specific "
                       "misconception rather than saying 'careless error'."),
            description=("Assess the student's answer.\n\nSUBMISSION:\n{submission}"),
            expected=("An object with `verdict` (exactly one of correct, partial, incorrect), "
                      "`misconception` (one sentence, or 'none'), and `next_step` (what the "
                      "student should try next, in one sentence)."),
            inputs={"submission": "${state.submission}"},
            schema={"verdict": "string", "misconception": "string", "next_step": "string"},
        ),
        {"id": "verdict", "kind": "transform", "label": "Verdict",
         "position": {"x": 340, "y": 480},
         "config": {"op": "pick", "args": {"source": "${state.out__assess}", "key": "verdict"}}},
        _agent(
            "tutor", "Tutor", 640,
            role="Tutor",
            goal="Write feedback that moves this student's understanding forward.",
            backstory=tutor["backstory"],
            description=tutor["description"],
            expected=tutor["expected"],
            inputs={"submission": "${state.submission}", "assessment": "${state.out__assess}"},
            markdown=True,
        ),
        {"id": "report", "kind": "transform", "label": "Teacher report",
         "position": {"x": 340, "y": 800},
         "config": {"op": "format", "args": {
             "template": "DIAGNOSIS: {verdict}\n\n" + FEEDBACK_MARKER + "\n{feedback}",
             "verdict": "${state.out__verdict}",
             "feedback": "${state.out__tutor}"}}},
        {"id": "final", "kind": "output", "label": "Feedback",
         "position": {"x": 340, "y": 960},
         "config": {"body_key": "markdown_body", "source": "${state.out__report}"}},
    ]
    edges = [
        _edge(1, "submission", "teacher_check"),
        _edge(2, "teacher_check", "assess", "approve"),
        _edge(3, "assess", "verdict"),
        _edge(4, "verdict", "tutor"),
        _edge(5, "tutor", "report"),
        _edge(6, "report", "final"),
    ]
    return {"schema": "builder.flow/v1", "name": "Formative feedback tutor",
            "version": 1, "input_field": "submission", "nodes": nodes,
            "edges": edges, "joins": {}, "budget": None}


# ---------------------------------------------------------------------------
# The rule (TEACHING-EVAL-LOOP.md section 3). Applied to both versions alike.
# ---------------------------------------------------------------------------

def split_report(body: str) -> tuple[str, str]:
    head, _, feedback = body.partition(FEEDBACK_MARKER)
    verdict = head.replace("DIAGNOSIS:", "").strip().lower()
    return verdict, feedback.strip()


def judge(sub: dict[str, Any], body: str | None) -> tuple[str, list[str]]:
    if not body:
        return "unsure", ["the run produced no feedback"]
    verdict, feedback = split_report(body)
    reasons: list[str] = []
    said_correct = verdict.startswith("correct")
    if said_correct != (sub["expected"] == "correct"):
        reasons.append(f"assessor said '{verdict}', teacher expected '{sub['expected']}'")
    words = len(re.findall(r"\b\w+\b", feedback))
    if words > WORD_LIMIT:
        reasons.append(f"{words} words (limit {WORD_LIMIT})")
    if sub["expected"] != "correct":
        if sub["answer_pattern"] and re.search(sub["answer_pattern"], feedback, re.I):
            reasons.append("gives the answer away")
        if "?" not in feedback:
            reasons.append("asks the student nothing")
    return ("bad" if reasons else "good"), reasons


# ---------------------------------------------------------------------------
# HTTP
# ---------------------------------------------------------------------------

class Api:
    def __init__(self, base: str, token: str) -> None:
        self.base, self.token = base.rstrip("/"), token

    def call(self, method: str, path: str, body: Any = None, raw: bool = False) -> Any:
        data = None if body is None else json.dumps(body).encode()
        req = urllib.request.Request(self.base + path, data=data, method=method)
        req.add_header("Authorization", f"Bearer {self.token}")
        if data is not None:
            req.add_header("Content-Type", "application/json")
        try:
            with urllib.request.urlopen(req, timeout=120) as resp:
                text = resp.read().decode()
        except urllib.error.HTTPError as err:
            raise SystemExit(f"{method} {path} -> {err.code}: {err.read().decode()[:800]}")
        if raw:
            return text
        return json.loads(text) if text else None


def mint_token(sub: str, email: str) -> str:
    out = subprocess.run(
        [sys.executable, str(Path(__file__).with_name("mint_identity.py")), "token",
         "--sub", sub, "--email", email, "--name", "Teaching proof", "--ttl", "7200"],
        check=True, capture_output=True, text=True)
    return out.stdout.strip()


def wait(api: Api, run_id: str, until: set[str], timeout: float = 300) -> dict[str, Any]:
    deadline = time.time() + timeout
    while time.time() < deadline:
        snap = api.call("GET", f"/api/runs/{run_id}")
        if snap["status"] in until or snap.get("pending_gate"):
            return snap
        time.sleep(1.5)
    raise SystemExit(f"run {run_id} did not reach {until} in {timeout}s")


def run_one(api: Api, workflow_id: str, sub: dict[str, Any]) -> dict[str, Any]:
    text = f"QUESTION: {sub['question']}\nSTUDENT ANSWER: {sub['answer']}"
    created = api.call("POST", f"/api/sessions/{uuid.uuid4()}/runs",
                       {"workflow_id": workflow_id, "inputs": {"submission": text}})
    run_id = created["run_id"]
    snap = wait(api, run_id, {"completed", "failed", "cancelled"})
    if snap.get("pending_gate"):
        gate = snap["pending_gate"]["gate_id"]
        api.call("POST", f"/api/runs/{run_id}/gates/{gate}", {"outcome": "approve"})
        time.sleep(1)
        snap = wait(api, run_id, {"completed", "failed", "cancelled"})
        while snap.get("pending_gate") is not None and snap["status"] not in {"completed", "failed", "cancelled"}:
            time.sleep(1.5)
            snap = api.call("GET", f"/api/runs/{run_id}")
    result = snap.get("result") or {}
    body = result.get("markdown_body") if isinstance(result, dict) else None
    rating, reasons = judge(sub, body)
    note = ("; ".join(reasons) or "meets every rule")[:480]
    api.call("PUT", f"/api/runs/{run_id}/rating", {"rating": rating, "note": note})
    return {"run_id": run_id, "submission": sub["id"], "status": snap["status"],
            "rating": rating, "reasons": reasons, "body": body,
            "usage": snap.get("usage")}


def publish_version(api: Api, version: int, workflow_id: str | None) -> tuple[str, int, dict[str, Any]]:
    doc = json.loads((EXAMPLES / f"formative-feedback-tutor.v{version}.json").read_text(encoding="utf-8"))
    if workflow_id is None:
        stored = api.call("POST", "/api/builder/workflows", {"document": doc})
    else:
        head = api.call("GET", f"/api/builder/workflows/{workflow_id}")
        doc["id"] = workflow_id
        stored = api.call("PUT", f"/api/builder/workflows/{workflow_id}",
                          {"document": doc, "expected_version": head["document"]["version"]})
    wid = stored["document"]["id"]
    published = api.call("POST", f"/api/builder/workflows/{wid}/publish")
    return wid, stored["document"]["version"], published


# ---------------------------------------------------------------------------
# Commands
# ---------------------------------------------------------------------------

def cmd_emit(_: argparse.Namespace) -> None:
    EXAMPLES.mkdir(parents=True, exist_ok=True)
    for version in TUTORS:
        path = EXAMPLES / f"formative-feedback-tutor.v{version}.json"
        path.write_text(json.dumps(build_document(version), indent=2) + "\n", encoding="utf-8")
        print(path.relative_to(ROOT))


def cmd_run(args: argparse.Namespace) -> None:
    api = Api(args.base, mint_token(args.sub, args.email))
    subs = json.loads((EXAMPLES / "submissions.json").read_text(encoding="utf-8"))["submissions"]
    EVIDENCE.mkdir(parents=True, exist_ok=True)
    runs_path = EVIDENCE / "runs.json"
    record: dict[str, Any] = (json.loads(runs_path.read_text(encoding="utf-8"))
                              if runs_path.exists() and args.resume else
                              {"base": args.base, "versions": {}})
    workflow_id = record.get("workflow_id")
    for version in args.versions:
        workflow_id, doc_version, published = publish_version(api, version, workflow_id)
        print(f"v{version}: {workflow_id} document_version={doc_version} "
              f"estimate=${published.get('estimate', {}).get('static_cost_usd', '?')}")
        runs = []
        for sub in subs:
            row = run_one(api, workflow_id, sub)
            runs.append(row)
            print(f"  {sub['id']:18} {row['status']:9} {row['rating']:6} {'; '.join(row['reasons'])}")
        record["versions"][str(version)] = {"document_version": doc_version, "runs": runs}
        record["workflow_id"] = workflow_id
    runs_path.write_text(json.dumps(record, indent=2) + "\n", encoding="utf-8")


def cmd_evaluate(args: argparse.Namespace) -> None:
    api = Api(args.base, mint_token(args.sub, args.email))
    record = json.loads((EVIDENCE / "runs.json").read_text(encoding="utf-8"))
    wid = record["workflow_id"]
    va = record["versions"][args.a]["document_version"]
    vb = record["versions"][args.b]["document_version"]
    compare = api.call("GET", f"/api/admin/improve/compare?workflow_id={wid}&axis=version&a={va}&b={vb}")
    (EVIDENCE / f"compare-v{args.a}-v{args.b}.json").write_text(json.dumps(compare, indent=2) + "\n", encoding="utf-8")
    hot = api.call("GET", f"/api/admin/improve/hotspots?workflow_id={wid}")
    (EVIDENCE / "hotspots.json").write_text(json.dumps(hot, indent=2) + "\n", encoding="utf-8")
    evalset = api.call("GET", f"/api/admin/export/evalset?workflow_id={wid}&rating=good", raw=True)
    (EVIDENCE / "evalset-good.ndjson").write_text(evalset, encoding="utf-8")
    print(f"evalset lines: {len(evalset.splitlines())}")
    if args.review:
        review = api.call("POST", f"/api/admin/improve/digests?workflow_id={wid}")
        (EVIDENCE / "review.json").write_text(json.dumps(review, indent=2) + "\n", encoding="utf-8")
        print("review:", json.dumps(review)[:600])
    print(json.dumps(compare, indent=1)[:3000])


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--base", default="http://127.0.0.1:8011")
    parser.add_argument("--sub", default="teaching-proof")
    parser.add_argument("--email", default="teaching-proof@example.invalid")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("emit").set_defaults(fn=cmd_emit)
    rn = sub.add_parser("run")
    rn.add_argument("--versions", type=int, nargs="+", default=[1, 2])
    rn.add_argument("--resume", action="store_true", help="append to runs.json and reuse its workflow")
    rn.set_defaults(fn=cmd_run)
    ev = sub.add_parser("evaluate")
    ev.add_argument("--a", default="1")
    ev.add_argument("--b", default="2")
    ev.add_argument("--review", action="store_true", help="also press 'Ask a model to review' (spends <= $0.05)")
    ev.set_defaults(fn=cmd_evaluate)
    args = parser.parse_args()
    args.fn(args)


if __name__ == "__main__":
    main()
