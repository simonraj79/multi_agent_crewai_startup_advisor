"""The Improve digest's prompt, and nothing else.

A package with a `config/tasks.yaml` and no Python, which is deliberate. Plan
21's model review is one `LLM.call` - no `Agent`, no `Crew`, no tools,
no memory, no registry run - so there is nothing here for a `@CrewBase` to
wrap. What there IS is a prompt, and the invariant says a prompt for this
repository's own work lives in YAML beside its siblings rather than in a
Python string. `service/digest.py` loads it; `tests/service/test_digest.py`
patches this file and asserts the prompt changes, which is what proves the
loading is real.
"""
