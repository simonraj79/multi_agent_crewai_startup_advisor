"""Scan the committed observability artifacts for credential values.

Serves DoD row **F3**: *"does no committed artifact contain a credential
value?"* - `evidence/tests/secret-scan.txt` is this script's output.

Two kinds of finding, and the distinction is the whole point:

* **FAIL** - a byte-for-byte occurrence of a value currently held in one of
  this machine's own `*_KEY` / `*_TOKEN` / `*_SECRET*` variables. That is a
  leaked credential. Exit code 1. The value is never printed, never logged and
  never written to the report; only the path, the line and the variable NAME.
* **WARN** - a string that merely has a credential's SHAPE (`sk-or-`, `sk-lf-`,
  `pk-lf-`, `fc-`, `ghp_`, `github_pat_`, `pcsk_`, `AIza`). These are expected:
  `DEFINITION-OF-DONE.md` and `TRACE-CONTRACT.md` both write the prefixes out
  as the patterns to scan for, and a scanner that failed on its own
  specification would be useless. WARN does not affect the exit code, but a
  WARN whose tail is token-shaped (8+ trailing characters) is labelled
  `token-shaped` so a reader looks at it rather than skimming past.

The report contains no credential value under any circumstance. A matched
prefix is rendered as the public prefix plus the LENGTH of what followed.

Usage:

    .venv/Scripts/python.exe scripts/observability/secret_scan.py \\
        --paths docs/observability --out docs/observability/evidence/tests/secret-scan.txt

    # also scan the staged and working-tree diffs:
    .venv/Scripts/python.exe scripts/observability/secret_scan.py \\
        --paths docs/observability --diff --out FILE
"""

from __future__ import annotations

import argparse
import re
import subprocess
import sys
from pathlib import Path
from typing import Any, Iterable

sys.path.insert(0, str(Path(__file__).resolve().parent))

from _common import (  # noqa: E402
    CREDENTIAL_PREFIX_PATTERN,
    CREDENTIAL_PREFIXES,
    FC_MIN_HEX_CHARS,
    load_env,
    now_iso,
    repo_root,
    split_credential_match,
)

# The shapes the DoD names, plus the two Langfuse keys. Each is a public
# prefix; nothing here is a secret.
#
# The pattern is IMPORTED, not declared here. It used to be a second copy, and
# a second copy of a rule is the failure this repository has recorded twice
# already; more concretely, the boundary fix below had to land in the redactor
# and in this scanner at once, and one shared object is the only arrangement in
# which they cannot disagree. `_common.py` carries the reasoning: a shape must
# begin at a token boundary, and `fc-` needs 20+ hex characters after it,
# because the old rule fired inside a hex UUID - damaging eleven evidence
# files and raising 358 of 461 WARNs in one scan.
PREFIXES = CREDENTIAL_PREFIXES
PREFIX_PATTERN = CREDENTIAL_PREFIX_PATTERN

# A variable whose value is shorter than this is not a credential - it is a
# flag or a name - and matching on it would flood the report with the word
# "true". The names skipped are listed in the report so the choice is visible.
MIN_SECRET_LENGTH = 12
CREDENTIAL_NAME = re.compile(r"(_KEY|_TOKEN|_SECRET\w*)$")
MAX_FILE_BYTES = 20 * 1024 * 1024


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Fail on a real credential value; warn on a credential shape.",
    )
    parser.add_argument(
        "--paths",
        nargs="+",
        default=["docs/observability"],
        help="files or directories to scan (default docs/observability)",
    )
    parser.add_argument(
        "--out",
        default=None,
        help="the report file to write (required unless --self-test)",
    )
    parser.add_argument(
        "--self-test",
        action="store_true",
        help=(
            "check the matching rules against fabricated strings and exit. No "
            "file is read or written and no real credential is used"
        ),
    )
    parser.add_argument(
        "--diff",
        action="store_true",
        help="also scan `git diff --cached` and `git diff` output",
    )
    parser.add_argument(
        "--env-file", default=None, help="the .env to read variable NAMES and values from"
    )
    return parser.parse_args(argv)


def render_prefix(prefix: str) -> str:
    """One credential prefix, written so a LATER scan cannot match it.

    MEASURED: a scan of a tree containing previous scan reports inflates its
    own WARN count, because a warning line rendered the prefix verbatim -
    `pk-lf-<36 chars>` - and `pk-lf-` is exactly what the next scan looks for.
    **5,614 of 8,087 warnings** in one run were this file's own earlier output
    reading itself, which buries the handful a reader should actually look at.

    The fix is to break the prefix with brackets around its last character:
    `pk-lf[-]`, `ghp[_]`, `AIz[a]`. A reader loses nothing - the prefix is
    still legible and still says which shape matched - and the literal the
    pattern needs is no longer present, so a report is inert to the scanner
    that produced it. `--self-test` asserts that for every prefix.
    """

    return f"{prefix[:-1]}[{prefix[-1]}]" if prefix else prefix


def credential_values(env_path: Path | None) -> tuple[dict[str, str], list[str]]:
    """`{variable name: value}` for every credential-shaped variable.

    Values are held in memory only. Nothing in this module writes one out; the
    single place they could escape is a match report, and that reports the
    variable name instead.
    """

    import os

    candidates: dict[str, str] = {}
    if env_path and env_path.is_file():
        quotes = ('"', "'")
        for raw in env_path.read_text(encoding="utf-8", errors="replace").splitlines():
            line = raw.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            name, _, value = line.partition("=")
            name = name.strip()
            value = value.strip()
            if len(value) >= 2 and value[0] == value[-1] and value[0] in quotes:
                value = value[1:-1]
            if CREDENTIAL_NAME.search(name) and value:
                candidates[name] = value
    for name, value in os.environ.items():
        if CREDENTIAL_NAME.search(name) and value and name not in candidates:
            candidates[name] = value

    values = {n: v for n, v in candidates.items() if len(v) >= MIN_SECRET_LENGTH}
    skipped = sorted(n for n in candidates if n not in values)
    return values, skipped


def iter_files(paths: Iterable[str], root: Path) -> list[Path]:
    files: list[Path] = []
    for entry in paths:
        path = Path(entry)
        if not path.is_absolute():
            path = root / path
        if path.is_file():
            files.append(path)
        elif path.is_dir():
            files.extend(p for p in sorted(path.rglob("*")) if p.is_file())
    return files


def scan_text(
    label: str, text: str, values: dict[str, str]
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    fails: list[dict[str, Any]] = []
    warns: list[dict[str, Any]] = []
    for number, line in enumerate(text.splitlines(), start=1):
        for name, value in values.items():
            if value in line:
                fails.append(
                    {
                        "path": label,
                        "line": number,
                        "variable": name,
                        "detail": f"the value of {name} appears verbatim",
                    }
                )
        for match in PREFIX_PATTERN.finditer(line):
            prefix, tail = split_credential_match(match.group(0))
            kind = (
                "bare prefix"
                if not tail
                else ("token-shaped" if len(tail) >= 8 else "short tail")
            )
            warns.append(
                {
                    "path": label,
                    "line": number,
                    "prefix": prefix,
                    "tail_length": len(tail),
                    "kind": kind,
                }
            )
    return fails, warns


def git_output(root: Path, args: list[str]) -> str:
    try:
        completed = subprocess.run(
            ["git", *args],
            cwd=str(root),
            capture_output=True,
            text=True,
            check=False,
            encoding="utf-8",
            errors="replace",
        )
    except OSError:
        return ""
    return completed.stdout or ""


def self_test() -> int:
    """Check the SHAPE rule against fabricated strings, and the VALUE rule too.

    Every string here is invented: the keys are the right shape and belong to
    nobody, and the run id is the one already published in
    `evidence/proof/validator-live-2/README.md`. Nothing reads `.env`.

    It exists because the shape rule has now been wrong in both directions -
    too greedy (it redacted a UUID out of eleven evidence files) is as bad as
    too loose, and neither shows up in a scan of a clean tree. A rule with a
    published failure needs a test that fails with it.
    """

    from _common import redact_string  # local: the scanner does not otherwise redact

    fake_firecrawl = "fc-" + "0123456789abcdef" * 2          # fc- + 32 hex
    fake_openrouter = "sk-or-v1-" + "0123456789abcdef" * 4   # sk-or-v1- + 64 hex
    damaged_uuid = "1a0bea14-ffb3-459d-b5fc-f714a76e5f71"
    trace_id = "1a0bea14ffb3459db5fcf714a76e5f71"
    planted_value = "not-a-real-credential-9f3c1d"

    cases: list[tuple[str, str, bool, list[str]]] = [
        # label, text, expect a shape match, credential values in play
        ("the run id that was damaged", damaged_uuid, False, []),
        ("the same id as a trace id", trace_id, False, []),
        ("a fabricated Firecrawl key", fake_firecrawl, True, []),
        ("a fabricated OpenRouter key", fake_openrouter, True, []),
        ("a key inside JSON", f'{{"k":"{fake_firecrawl}"}}', True, []),
        ("a bare prefix in prose", "the fc- prefix", False, []),
        ("a UUID beside a real key", f"{damaged_uuid} {fake_firecrawl}", True, []),
        # The VALUE rule is unconditional: no boundary, no shape, still caught.
        ("a held value glued mid-word", f"xx{planted_value}yy", False, [planted_value]),
    ]

    failures = 0
    rows: list[str] = []
    for label, text, expect_shape, values in cases:
        shape_hits = len(PREFIX_PATTERN.findall(text))
        _, redactions = redact_string(text, values)
        value_hits = redactions - shape_hits
        shape_ok = bool(shape_hits) == expect_shape
        value_ok = (not values) or value_hits >= 1
        # A string with no shape and no held value must come back untouched.
        survives = redactions == 0
        intact_ok = survives if (not expect_shape and not values) else True
        ok = shape_ok and value_ok and intact_ok
        failures += 0 if ok else 1
        rows.append(
            f"  [{'ok ' if ok else 'FAIL'}] {label:32} "
            f"shape={shape_hits} expected={'yes' if expect_shape else 'no '} "
            f"value={value_hits}"
        )

    # A WARNING line this script writes must be INERT to this script: a report
    # that matches itself buried 5,614 hits in one run.
    for prefix in CREDENTIAL_PREFIXES:
        rendered = f"  some/file.md:42  {render_prefix(prefix)}<36 chars>  [bare prefix]"
        hits = PREFIX_PATTERN.findall(rendered)
        ok = not hits
        failures += 0 if ok else 1
        rows.append(
            f"  [{'ok ' if ok else 'FAIL'}] a rendered WARN line for "
            f"{render_prefix(prefix):16} scans to {len(hits)} match(es)"
        )

    # The UUID must come back byte-identical, which is the whole point.
    restored, _ = redact_string(damaged_uuid, [])
    if restored != damaged_uuid:
        failures += 1
        rows.append("  [FAIL] the run id was altered by redaction")
    else:
        rows.append("  [ok ] the run id survives redaction byte for byte")

    print("secret_scan self-test - fabricated strings only, no .env read")
    print("=" * 60)
    print("\n".join(rows))
    print(f"\n{len(cases) + len(CREDENTIAL_PREFIXES) + 1} checks, {failures} failure(s)")
    return 1 if failures else 0


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    if args.self_test:
        return self_test()
    if not args.out:
        print("--out is required (or pass --self-test)", file=sys.stderr)
        return 2
    root = repo_root()
    load_env(args.env_file)
    env_path = Path(args.env_file) if args.env_file else root / ".env"
    values, skipped = credential_values(env_path)

    fails: list[dict[str, Any]] = []
    warns: list[dict[str, Any]] = []
    scanned = 0
    binary_scanned = 0
    oversize: list[str] = []

    for path in iter_files(args.paths, root):
        try:
            size = path.stat().st_size
        except OSError:
            continue
        if size > MAX_FILE_BYTES:
            oversize.append(str(path.relative_to(root) if path.is_relative_to(root) else path))
            continue
        raw = path.read_bytes()
        label = str(path.relative_to(root) if path.is_relative_to(root) else path)
        try:
            text = raw.decode("utf-8")
            is_text = True
        except UnicodeDecodeError:
            text = ""
            is_text = False
        if is_text:
            scanned += 1
            file_fails, file_warns = scan_text(label, text, values)
            fails.extend(file_fails)
            warns.extend(file_warns)
        else:
            # A screenshot cannot be line-scanned, but a credential pasted into
            # a binary blob is still a leak, so the raw bytes are searched for
            # each value with no line number.
            binary_scanned += 1
            for name, value in values.items():
                if value.encode("utf-8") in raw:
                    fails.append(
                        {
                            "path": label,
                            "line": 0,
                            "variable": name,
                            "detail": f"the value of {name} appears in the file bytes",
                        }
                    )

    if args.diff:
        for label, git_args in (
            ("<git diff --cached>", ["diff", "--cached"]),
            ("<git diff>", ["diff"]),
        ):
            text = git_output(root, git_args)
            if not text:
                continue
            scanned += 1
            diff_fails, diff_warns = scan_text(label, text, values)
            fails.extend(diff_fails)
            warns.extend(diff_warns)

    token_shaped = [w for w in warns if w["kind"] == "token-shaped"]
    verdict = "FAIL" if fails else "PASS"
    lines = [
        "Secret scan - DoD F3",
        "=" * 60,
        f"scanned at:      {now_iso()}",
        f"repository:      {root}",
        f"paths:           {', '.join(args.paths)}",
        f"git diffs:       {'scanned' if args.diff else 'not scanned (pass --diff)'}",
        f"text files:      {scanned}",
        f"binary files:    {binary_scanned} (byte-searched for values, no line numbers)",
        f"oversize skipped:{len(oversize)}",
        "",
        f"credential variables loaded: {len(values)} (names only, values NEVER printed)",
        "  " + (", ".join(sorted(values)) or "(none)"),
        f"variables skipped as shorter than {MIN_SECRET_LENGTH} characters: "
        + (", ".join(skipped) or "(none)"),
        "",
        f"FAIL - actual credential values found: {len(fails)}",
        f"WARN - credential-shaped prefixes:     {len(warns)}"
        f" (of which token-shaped: {len(token_shaped)})",
        "",
        f"VERDICT: {verdict}",
        "",
    ]
    if not values:
        lines += [
            "NOTE: no credential variable was loaded, so the FAIL half of this scan",
            "checked nothing. Run it on a machine with .env present, or the row is",
            "unverified rather than passed.",
            "",
        ]
    if fails:
        lines += ["FAILURES", "-" * 60]
        for entry in fails:
            lines.append(f"  {entry['path']}:{entry['line']}  {entry['detail']}")
        lines.append("")
    if warns:
        lines += [
            "WARNINGS - credential SHAPES, not values",
            "(the prefixes are written out as scan patterns in DEFINITION-OF-DONE.md",
            " and TRACE-CONTRACT.md; those are the expected hits. The matched text is",
            " rendered as its public prefix plus the length of what followed.)",
            "",
            "Each prefix below is written with its last character in brackets -",
            "pk-lf[-], ghp[_] - so THIS report cannot be matched by the next scan of",
            "a tree that contains it. 5,614 of one run's 8,087 warnings were exactly",
            "that: this file reading its own earlier output.",
            "-" * 60,
        ]
        for entry in warns:
            # `render_prefix`, never the raw prefix: this report is itself a
            # file somebody will scan.
            lines.append(
                f"  {entry['path']}:{entry['line']}  "
                f"{render_prefix(entry['prefix'])}"
                f"<{entry['tail_length']} chars>  [{entry['kind']}]"
            )
        lines.append("")
    if oversize:
        lines += ["SKIPPED (over the size cap)", "-" * 60]
        lines += [f"  {name}" for name in oversize]
        lines.append("")

    report = "\n".join(lines)
    out_path = Path(args.out)
    if not out_path.is_absolute():
        out_path = root / out_path
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(report + "\n", encoding="utf-8")
    print(report)
    print(f"wrote {out_path}", file=sys.stderr)
    return 1 if fails else 0


if __name__ == "__main__":
    raise SystemExit(main())
