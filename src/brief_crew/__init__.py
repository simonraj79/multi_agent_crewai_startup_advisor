"""brief_crew - a Researcher/Analyst/Writer crew over a warm Pinecone cache.

Credentials are loaded here, on package import, so that importing ``BriefCrew``
directly works the same way as running through ``main.py``.

``override=True`` is deliberate. This machine already carries a *different*
valid ``PINECONE_API_KEY`` at the OS level, and python-dotenv does not override
existing environment variables by default - so without this the project would
silently run on a credential the repository never declared. Both keys currently
reach the same account, which is exactly what makes the shadowing dangerous: it
works until the machine-level key is rotated, and then the failure looks like a
``.env`` problem on a file that was correct all along.

On Render there is no ``.env`` in the image (it is gitignored; secrets arrive as
real environment variables via ``sync: false``), so nothing is overridden there.
"""

import sys
from pathlib import Path

from dotenv import load_dotenv

# --------------------------------------------------------------------------
# Windows console encoding. Not cosmetic: without this the *entire verbose
# trace* is lost on this machine.
#
# Python defaults stdout to cp1252 on Windows. CrewAI's event handlers print
# emoji (✅, 🚀, ⚠️), and cp1252 cannot encode them - so every handler raises
# `UnicodeEncodeError: 'charmap' codec can't encode character '✅'`:
#
#     [CrewAIEventsBus] Sync handler error in on_tool_usage_started: ...
#     [CrewAIEventsBus] Sync handler error in on_task_failed: ...
#     [CrewAIEventsBus] Sync handler error in on_crew_failed: ...
#
# Handler exceptions never break a run, which is exactly what makes this
# dangerous: the crew keeps going while the trace silently disappears. And the
# trace is the deliverable - it is the only view of who handed off to whom.
#
# Setting PYTHONIOENCODING=utf-8 externally works too, but relying on that means
# the trace breaks for anyone who forgets it.
# --------------------------------------------------------------------------
for _stream in (sys.stdout, sys.stderr):
    if hasattr(_stream, "reconfigure") and (getattr(_stream, "encoding", "") or "").lower() not in (
        "utf-8",
        "utf8",
    ):
        try:
            _stream.reconfigure(encoding="utf-8", errors="replace")
        except (ValueError, OSError):  # detached or non-reconfigurable stream
            pass

# Resolve from this file, not the CWD - the crew must behave identically whether
# it is launched from the repo root, from src/, or by uvicorn under Render.
_ENV_PATH = Path(__file__).resolve().parents[2] / ".env"
if _ENV_PATH.is_file():
    load_dotenv(_ENV_PATH, override=True)

__all__ = ["__version__"]
__version__ = "0.1.0"
