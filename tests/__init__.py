"""Project test suite.

Placeholder credentials, set here and nowhere else
==================================================

This module runs before any test module, and therefore before anything imports
``brief_crew`` - which matters, because ``brief_crew/__init__.py`` calls
``load_dotenv(..., override=True)`` at import time. Whatever is decided here is
decided before that.

The suite is deliberately no-cost: every crew, every external API and every
model call is mocked or replaced with a deterministic double. But several tests
still *construct* the real objects in order to assert their wiring - which
model a crew was given, which tools an agent carries, that the Reporter has
none. Two of those constructors demand a key in ``__init__`` and refuse to
build without one:

* ``crewai``'s native OpenRouter provider - ``ImportError: Error importing
  native provider: ... API key required for openrouter``. 24 errors, plus 3
  downstream ``TypeError`` in the gate-recovery integration tests and 4 in
  ``tests/perf`` whose flows could not be constructed at all.
* ``crewai_tools``' Firecrawl tools, via ``firecrawl``'s own client -
  ``ValueError: No API key provided``. 11 errors.

Nothing in the suite ever *calls* either object; the key is a construction-time
formality. Without these two lines the suite does not run on a clean checkout -
it collapses at object construction in ~5s instead of ~38s, with 4 failures and
36 errors - which is exactly what CI sees, since no ``.env`` is ever committed.

Three rules govern what may go here:

1. ``setdefault``, never assignment. A developer with a real ``.env`` or real
   OS-level variables must see identical behaviour, and does: dotenv's
   ``override=True`` re-asserts the real value over the placeholder a moment
   later anyway.
2. The value must be *obviously* fake. It is not a redacted credential, it
   cannot authenticate against anything, and it should be impossible to mistake
   for one in a traceback, a log or a screenshot.
3. Only variables an actual failure demands. This is not a mirror of
   ``.env.example``. ``PINECONE_API_KEY`` and ``COHERE_API_KEY`` are injected
   per-test with ``patch.dict`` where they are needed, and ``GITHUB_TOKEN`` is
   deliberately *cleared* by ``tests/tools/test_github_feasibility.py`` to
   exercise the unauthenticated rate limit - so setting any of the three here
   would be at best noise and at worst a mask over a real assertion.
"""

import os

#: Not a credential. Not a redaction of one. It authenticates against nothing.
_PLACEHOLDER = "ci-placeholder-not-a-real-key"

for _name in ("OPENROUTER_API_KEY", "FIRECRAWL_API_KEY"):
    os.environ.setdefault(_name, _PLACEHOLDER)

# The vault's master key, for the same reason as the two above: `create_app`
# refuses to build with AUTH_BASE_URL set and no CREDENTIALS_MASTER_KEY (plan
# 01 D3), and thirty-odd tests patch AUTH_BASE_URL onto a synthetic app. This
# is base64 of the 32 bytes `ci-placeholder-not-a-master-key!` - decode it and
# it says so - and it protects nothing but an in-memory SQLite the test throws
# away. A test about the UNCONFIGURED vault patches `config.CREDENTIALS_MASTER_KEY`
# to "" itself, the way the key-absent tool tests clear their environment.
os.environ.setdefault(
    "CREDENTIALS_MASTER_KEY", "Y2ktcGxhY2Vob2xkZXItbm90LWEtbWFzdGVyLWtleSE="
)

# The one ASSIGNMENT in this file, and the only place rule 1 above is
# deliberately not followed.
#
# `LANGFUSE_EXPORT_ENABLED` is not a credential and nothing here is standing in
# for one. It defaults to ON whenever both Langfuse keys are present
# (`config.py`, contract section 9), and a developer running this suite with a
# real `.env` has both - so `setdefault` would leave 2,500 tests posting live
# traces to a real project over the network, at a cadence no test controls and
# with runs no person launched. That is the opposite of the trade the three
# lines above make: there, the developer's real value must win; here, the
# suite's answer must, because the suite is not a deployment.
#
# The tests that exercise the exporter build it themselves with an injected
# in-memory sender, so nothing is made untestable by this line - only
# unreachable by accident. `.env` declares no such variable today, so dotenv's
# `override=True` has nothing to re-assert over it; if one is ever added there,
# this line stops working and the symptom is a test run that talks to the
# network, which `tests/observability/test_exporter_isolation.py` is written to
# notice.
os.environ["LANGFUSE_EXPORT_ENABLED"] = "0"
