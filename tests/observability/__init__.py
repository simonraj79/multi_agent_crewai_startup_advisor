"""Tests for the Langfuse exporter.

This file exists so `unittest discover` walks into the directory at all. A test
package without one is skipped in silence and the suite reports a green OK over
tests it never ran - which is how the Python count in this repository sat at 65
for a long time. See `docs/gotchas-and-insights.md` entry 20.

**No test in this package touches the network.** Every one of them builds the
exporter with `RecordingBackend`, an in-memory double that records what would
have been sent, except the three fail-open tests in
`test_exporter_isolation.py`: those build the REAL backend and point it at a
port nothing is listening on, because their whole subject is what happens when
the backend cannot be reached.
"""

import logging

# The per-run summary logs at WARNING, for the reason its own logger's comment
# gives: under `serve.exe` nothing configures the root logger and
# `logging.lastResort` drops anything below WARNING, so an INFO line would be
# invisible in the one place an operator reads it. In a test run that would
# print one line per exercised run into the suite's output. Silencing it here
# keeps `assertLogs` working - that helper attaches its own handler directly to
# the named logger - while keeping the suite readable.
_summary = logging.getLogger("brief_crew.observability.summary")
_summary.addHandler(logging.NullHandler())
_summary.propagate = False
