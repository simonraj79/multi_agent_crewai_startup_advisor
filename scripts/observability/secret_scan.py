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

from _common import load_env, now_iso, repo_root  # noqa: E402

# The shapes the DoD names, plus the two Langfuse keys. Each is a public
# prefix; nothing here is a secret.
PREFIXES = (
    "sk-or-",
    "sk-lf-",
    "pk-lf-",
    "fc-",
    "ghp_",
    "github_pat_",
    "pcsk_",
    "AIza",
)
PREFIX_PATTERN = re.compile(
    "(" + "|".join(re.escape(prefix) for prefix in PREFIXES) + r")([A-Za-z0-9_\-]*)"
)

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
    parser.add_argument("--out", required=True, help="the report file to write")
    parser.add_argument(
        "--diff",
        action="store_true",
        help="also scan `git diff --cached` and `git diff` output",
    )
    parser.add_argument(
        "--env-file", default=None, help="the .env to read variable NAMES and values from"
    )
    return parser.parse_args(argv)


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
            prefix, tail = match.group(1), match.group(2)
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


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
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
            "-" * 60,
        ]
        for entry in warns:
            lines.append(
                f"  {entry['path']}:{entry['line']}  {entry['prefix']}"
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
