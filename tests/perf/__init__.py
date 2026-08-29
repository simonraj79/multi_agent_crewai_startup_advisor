"""Tests for the F42 performance harness in scripts/.

CrewAI's telemetry exporter is opted out before any test module imports
``scripts.perf_arms`` (and through it, CrewAI), so the suite stays no-cost and
makes no HTTP call.
"""

from scripts.perf_metrics import disable_crewai_telemetry

disable_crewai_telemetry()
