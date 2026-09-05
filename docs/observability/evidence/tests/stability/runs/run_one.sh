#!/usr/bin/env bash
# run_one.sh <arm> <run#>   arm = base | current
ARM="$1"; N="$2"
OUT="/d/MultiAgentSystem/docs/observability/evidence/tests/stability/runs/${ARM}-${N}.txt"
PY="/d/MultiAgentSystem/.venv/Scripts/python.exe"
if [ "$ARM" = "base" ]; then
  cd /d/MultiAgentSystem-wt/stability-base || exit 9
  export PYTHONPATH='D:\MultiAgentSystem-wt\stability-base\src'
else
  cd /d/MultiAgentSystem || exit 9
  unset PYTHONPATH
fi
{
  echo "### ARM=$ARM RUN=$N"
  echo "### CWD=$(pwd)"
  echo "### PYTHONPATH=${PYTHONPATH:-<unset>}"
  echo "### START=$(date -Is)"
} > "$OUT"
S=$(date +%s)
"$PY" -X faulthandler -u -m unittest discover -s tests -t . >> "$OUT" 2>&1
RC=$?
E=$(date +%s)
{
  echo "### END=$(date -Is)"
  echo "### EXIT=$RC"
  echo "### WALL_SECONDS=$((E-S))"
} >> "$OUT"
echo "ARM=$ARM RUN=$N EXIT=$RC WALL=$((E-S))s"
grep -c '^Thread 0x' "$OUT" | sed 's/^/THREAD_BLOCKS=/'
grep -E '^Ran [0-9]+ tests' "$OUT" | tail -1
grep -E '^(OK|FAILED)' "$OUT" | tail -1
grep -E 'Windows fatal exception' "$OUT" | head -3
