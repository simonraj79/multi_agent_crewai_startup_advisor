"""Undo a builder registration, for any test that publishes one.

Registering a builder workflow writes FIVE process-global maps - four in
`service/graph.py` and `config.WORKFLOW_RESERVED_RUN_INPUT_KEYS` - and a
`TestCase` outlives none of them. A module that publishes a graph and never
takes it back leaves that graph visible to every test that runs afterwards in
the same process, which makes the suite's result depend on `unittest
discover`'s alphabetical ordering rather than on the code.

That is not hypothetical here. `tests/service/test_builder_runner.py`
published through the real HTTP surface and never unregistered, and
`tests/service/test_builder_rehydration.py::test_an_uncompilable_document_registers_in_neither_half`
asserts that NO `ug_` id is in `WORKFLOWS`. Both were green only because `r-e`
sorts before `r-u`; run the two modules the other way round and the second one
failed on the first one's litter. CLAUDE.md keeps a section for exactly this
shape - a test that passes for the wrong reason - and the reason it is worth a
shared module rather than a copied helper is that the copy is how the two
halves drift: a sixth registration site would have to be remembered twice.
"""

from __future__ import annotations

import unittest


def forget_builder_workflow(workflow_id: str) -> None:
    """Remove a builder graph from every global a registration touched.

    `unregister_builder_workflow` clears all five now. The reserved-key pop is
    repeated here anyway, and deliberately: cleanup that trusts the production
    function is cleanup that stops working at precisely the moment that
    function regresses, and the leak it would then permit does not fail the
    test that caused it - it fails an unrelated module, in one ordering, later.
    Whether the production path clears that map is asserted directly, where the
    rollback is already exercised, not left to be inferred from a green suite.
    """

    from brief_crew.config import WORKFLOW_RESERVED_RUN_INPUT_KEYS
    from brief_crew.service.graph import unregister_builder_workflow

    unregister_builder_workflow(workflow_id)
    WORKFLOW_RESERVED_RUN_INPUT_KEYS.pop(workflow_id, None)


class BuilderRegistrationCleanup(unittest.TestCase):
    """A `TestCase` that hands back every builder graph it registered."""

    def forget(self, workflow_id: str) -> None:
        forget_builder_workflow(workflow_id)

    def track(self, *workflow_ids: str) -> None:
        for workflow_id in workflow_ids:
            self.addCleanup(self.forget, workflow_id)
