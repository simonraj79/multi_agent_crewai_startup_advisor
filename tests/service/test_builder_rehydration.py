"""A published builder graph must survive a restart. Spec section 8.1 item 5.

The defect: a publish writes to six process-local places - the four dicts in
``service/graph.py``, the reserved-key map in ``config.py``, and the registry's
own runtime map - and to one durable one, ``builder_documents.status``. A
restart kept the durable half and threw away the other six, and only the six
were consulted. The row said ``published``, the canvas said ``published``, and
``POST /api/sessions/{id}/runs`` answered **404**. Both Render services carry
``autoDeploy: yes``, so that was every push to ``main``.

This is remaining-work item 32 in a different costume - durable state and
process state disagreeing across a restart - and it gets the same test shape:
build the state, throw the process away (a *second* ``create_app`` over the
same store is exactly that), and assert what the new one knows.

Three behaviours the brief names, and they are the first three cases below:
a published document comes back in a NEW app instance, a document that no
longer compiles is skipped without stopping the boot, and an unpublished one is
left alone. The rest pin the refusals.

**No cost.** Nothing here launches a run. ``build_builder_workflow`` compiles a
declaration and prices it without calling anything, ``BuilderFlowRunner`` parses
its definition lazily so constructing one is free, and the runner factory these
tests install is a local object that would raise if anything ever called it.
"""

from __future__ import annotations

import importlib.util
import logging
import unittest
from typing import Any

from tests.service.builder_registration import BuilderRegistrationCleanup


FASTAPI_AVAILABLE = importlib.util.find_spec("fastapi") is not None

#: Distinct ids, because `service/graph.py`'s maps are module globals shared by
#: every test in the process and a collision would let one case see another's
#: registration.
GOOD_ID = "ug_11110000"
BROKEN_ID = "ug_22220000"
SECOND_ID = "ug_33330000"


def _document(document_id: str, *, compiles: bool = True) -> Any:
    """A three-node graph: seed an idea, scope it, emit the report.

    ``compiles=False`` drops the agent node's ``prompt_inputs``, which PARSES -
    the document schema has nothing to say about it - and then fails
    ``compile_document`` because ``scoping_task`` names two template variables
    the node no longer supplies. That is the shape of the real hazard: a
    document written when the rules were laxer is still a perfectly valid
    ``builder.flow/v1`` document, and only the compiler refuses it.
    """

    from brief_crew.builder.document import BuilderDocument
    from brief_crew.config import BUILDER_DOCUMENT_SCHEMA, RUN_RESULT_BODY_KEYS

    agent_config: dict[str, Any] = {
        "agent_id": "scoper",
        "tier": "cheap",
        "tools": [],
        "max_iter": 2,
        "guardrail_max_retries": 2,
    }
    if compiles:
        agent_config["prompt_inputs"] = {
            "idea": "${state.idea}",
            "human_override": "none",
        }
    return BuilderDocument.model_validate(
        {
            "schema": BUILDER_DOCUMENT_SCHEMA,
            "id": document_id,
            "name": f"Graph {document_id}",
            "version": 1,
            "input_field": "idea",
            "nodes": [
                {"id": "idea", "kind": "input", "label": "idea", "config": {"field": "idea"}},
                {"id": "scoper", "kind": "agent", "label": "scoper", "config": agent_config},
                {
                    "id": "report",
                    "kind": "output",
                    "label": "report",
                    "config": {
                        "body_key": RUN_RESULT_BODY_KEYS[0],
                        "source": "${state.out__scoper}",
                    },
                },
            ],
            "edges": [
                {
                    "id": "e0",
                    "source": "idea",
                    "source_port": "out",
                    "target": "scoper",
                    "target_port": "in",
                },
                {
                    "id": "e1",
                    "source": "scoper",
                    "source_port": "out",
                    "target": "report",
                    "target_port": "in",
                },
            ],
        }
    )


def _workflow_id(document: Any) -> str:
    """The compiled workflow id for a document, without registering anything."""

    from brief_crew.builder.descriptor import build_builder_workflow

    return build_builder_workflow(document).workflow_id


class RefusesToRun:
    """A runner that would fail loudly if these tests ever launched anything.

    Installed as the rehydrated runtime's runner so a case can assert that the
    sixth registration site got the object the factory produced - and so that a
    test which accidentally started a run fails on this sentence rather than on
    an OpenRouter bill.
    """

    def __call__(self, execution: Any) -> Any:  # pragma: no cover - never called
        raise AssertionError("no test in this module may execute a builder graph")


class BuilderRehydrationTestCase(BuilderRegistrationCleanup):
    """An in-memory store, a registry over it, and cleanup of six globals.

    `forget` and `track` used to live here, which is why the module that had no
    cleanup at all did not get any: a helper in one file is invisible to the
    next one. They now live in `tests/service/builder_registration.py` so both
    files reach the same one.
    """

    def setUp(self) -> None:
        super().setUp()
        self.registered_ids: list[str] = []

    def persistence(self) -> Any:
        from brief_crew.service.persistence import PostgresFlowPersistence

        store = PostgresFlowPersistence("sqlite+pysqlite:///:memory:")
        self.addCleanup(store.close)
        return store

    def publish_into(self, store_persistence: Any, document: Any, *, publish: bool = True) -> str:
        """Write a document the way `create` + `publish` would, and return its id."""

        from brief_crew.builder.store import BuilderDocumentStore

        store = BuilderDocumentStore(store_persistence)
        store.create(document)
        if publish:
            store.mark_published(document.id, document.version)
        return document.id

    def registry(self, store_persistence: Any) -> Any:
        """A two-workflow registry, which is the shape `create_app` builds."""

        from brief_crew.service.graph import (
            BRIEF_GRAPH,
            BRIEF_NODE_REGISTRY,
            VALIDATOR_GRAPH,
            VALIDATOR_NODE_REGISTRY,
        )
        from brief_crew.service.registry import RunRegistry, WorkflowRuntime

        runner = RefusesToRun()
        registry = RunRegistry(
            graph_version=BRIEF_GRAPH.version,
            node_registry=BRIEF_NODE_REGISTRY,
            runner=runner,
            workflows={
                BRIEF_GRAPH.id: WorkflowRuntime(
                    graph_version=BRIEF_GRAPH.version,
                    node_registry=BRIEF_NODE_REGISTRY,
                    runner=runner,
                    input_field="topic",
                ),
                VALIDATOR_GRAPH.id: WorkflowRuntime(
                    graph_version=VALIDATOR_GRAPH.version,
                    node_registry=VALIDATOR_NODE_REGISTRY,
                    runner=runner,
                    input_field="idea",
                ),
            },
            persistence=store_persistence,
            gate_sweep_interval=0,
        )
        self.addCleanup(registry.close)
        return registry

    def sweep(self, store_persistence: Any, registry: Any, **kwargs: Any) -> Any:
        """The boot pass, called directly, with the runner factory a test wants."""

        from brief_crew.builder.store import BuilderDocumentStore
        from brief_crew.service.builder_rehydrate import rehydrate_published_workflows

        options: dict[str, Any] = {
            "store": BuilderDocumentStore(store_persistence),
            "registry": registry,
            "runner_factory": lambda workflow: RefusesToRun(),
        }
        options.update(kwargs)
        return rehydrate_published_workflows(**options)


class RestartRestoresPublishedGraphs(BuilderRehydrationTestCase):
    """The defect itself: a new process over the same store."""

    def test_a_published_document_is_registered_again_by_the_sweep(self) -> None:
        from brief_crew.config import WORKFLOW_RESERVED_RUN_INPUT_KEYS
        from brief_crew.service.graph import (
            BUILDER_WORKFLOWS,
            GRAPHS,
            NODE_REGISTRIES,
            WORKFLOWS,
        )

        document = _document(GOOD_ID)
        workflow_id = _workflow_id(document)
        self.track(workflow_id)
        persistence = self.persistence()
        self.publish_into(persistence, document)

        # The state a fresh process starts in: the row is published and the six
        # maps have never heard of it.
        self.assertNotIn(workflow_id, WORKFLOWS)
        self.assertNotIn(workflow_id, GRAPHS)

        registry = self.registry(persistence)
        report = self.sweep(persistence, registry)

        self.assertEqual(report.registered, (workflow_id,))
        self.assertEqual(report.skipped, ())
        self.assertFalse(report.stopped_early)
        # All six, named one at a time: a partial registration is the 404 that
        # reads as a service defect rather than as an unrestored graph.
        self.assertIn(workflow_id, GRAPHS)
        self.assertIn(workflow_id, NODE_REGISTRIES)
        self.assertIn(workflow_id, WORKFLOWS)
        self.assertIn(workflow_id, BUILDER_WORKFLOWS)
        self.assertIn(workflow_id, WORKFLOW_RESERVED_RUN_INPUT_KEYS)
        self.assertIn(workflow_id, registry.workflows)

    def test_the_rehydrated_runtime_carries_the_factory_s_runner_and_the_input_field(
        self,
    ) -> None:
        """A graph registered with the wrong runner is registered and unrunnable.

        `RunExecution` carries no `workflow_id`, so each builder graph needs its
        own runner closed over its own compiled definition - which is why the
        sweep takes a factory. This asserts the object the factory produced is
        the one the registry will call, and that the runtime knows which request
        key this graph reads, without launching anything.
        """

        document = _document(GOOD_ID)
        workflow_id = _workflow_id(document)
        self.track(workflow_id)
        persistence = self.persistence()
        self.publish_into(persistence, document)
        registry = self.registry(persistence)

        made: list[Any] = []

        def factory(workflow: Any) -> Any:
            runner = RefusesToRun()
            made.append((workflow.workflow_id, runner))
            return runner

        self.sweep(persistence, registry, runner_factory=factory)

        self.assertEqual([entry[0] for entry in made], [workflow_id])
        runtime = registry.workflow_runtime(workflow_id)
        self.assertIs(runtime.runner, made[0][1])
        self.assertEqual(runtime.input_field, "idea")

    def test_two_published_graphs_both_come_back(self) -> None:
        first = _document(GOOD_ID)
        second = _document(SECOND_ID)
        ids = {_workflow_id(first), _workflow_id(second)}
        self.track(*ids)
        persistence = self.persistence()
        self.publish_into(persistence, first)
        self.publish_into(persistence, second)

        report = self.sweep(persistence, self.registry(persistence))

        self.assertEqual(set(report.registered), ids)
        self.assertEqual(report.attempted, 2)


class DocumentsThatNoLongerCompile(BuilderRehydrationTestCase):
    """The bounds move. A graph published under laxer ones must not stop a boot."""

    def test_an_uncompilable_document_is_skipped_and_the_others_still_land(self) -> None:
        from brief_crew.service.graph import WORKFLOWS

        good = _document(GOOD_ID)
        broken = _document(BROKEN_ID, compiles=False)
        good_workflow_id = _workflow_id(good)
        self.track(good_workflow_id)
        persistence = self.persistence()
        self.publish_into(persistence, good)
        self.publish_into(persistence, broken)

        report = self.sweep(persistence, self.registry(persistence))

        self.assertEqual(report.registered, (good_workflow_id,))
        self.assertEqual([document_id for document_id, _ in report.skipped], [BROKEN_ID])
        self.assertFalse(report.stopped_early)
        self.assertIn(good_workflow_id, WORKFLOWS)

    def test_the_skip_names_the_document_and_the_compiler_s_own_reason(self) -> None:
        """Observable, not silent. A graph that quietly stops existing is the
        defect this module closes, not a smaller version of it to ship."""

        persistence = self.persistence()
        self.publish_into(persistence, _document(BROKEN_ID, compiles=False))

        with self.assertLogs("brief_crew.service.builder_rehydrate", logging.WARNING) as logs:
            report = self.sweep(persistence, self.registry(persistence))

        self.assertEqual(report.registered, ())
        self.assertEqual(len(report.skipped), 1)
        _, reason = report.skipped[0]
        self.assertIn("scoper", reason)
        joined = "\n".join(logs.output)
        self.assertIn(BROKEN_ID, joined)
        self.assertIn("no longer compiles", joined)

    def test_an_uncompilable_document_registers_in_neither_half(self) -> None:
        """The rollback `publish` makes, made here for the same reason.

        A workflow left in `WORKFLOWS` with no runtime behind it answers 404 on
        launch, which is the sentence a REGISTRATION defect writes.
        """

        from brief_crew.service.graph import BUILDER_WORKFLOWS, GRAPHS, WORKFLOWS

        persistence = self.persistence()
        self.publish_into(persistence, _document(BROKEN_ID, compiles=False))
        registry = self.registry(persistence)

        self.sweep(persistence, registry)

        self.assertEqual([key for key in WORKFLOWS if key.startswith("ug_")], [])
        self.assertEqual([key for key in GRAPHS if key.startswith("ug_")], [])
        self.assertEqual(list(BUILDER_WORKFLOWS), [])
        self.assertEqual([key for key in registry.workflows if key.startswith("ug_")], [])

    def test_a_runtime_registration_failure_rolls_the_other_half_back(self) -> None:
        """The one path where five maps are written before the sixth refuses."""

        from brief_crew.config import WORKFLOW_RESERVED_RUN_INPUT_KEYS
        from brief_crew.service.graph import GRAPHS, WORKFLOWS

        document = _document(GOOD_ID)
        workflow_id = _workflow_id(document)
        self.track(workflow_id)
        persistence = self.persistence()
        self.publish_into(persistence, document)
        registry = self.registry(persistence)

        def hostile(workflow: Any) -> Any:
            raise RuntimeError("this runner cannot be built")

        report = self.sweep(persistence, registry, runner_factory=hostile)

        self.assertEqual(report.registered, ())
        self.assertEqual([document_id for document_id, _ in report.skipped], [GOOD_ID])
        self.assertNotIn(workflow_id, WORKFLOWS)
        self.assertNotIn(workflow_id, GRAPHS)
        self.assertNotIn(workflow_id, registry.workflows)
        # The fifth map, and the one the rollback used to miss. It is asserted
        # here rather than left to `forget` because a leak in this dict is
        # silent where the other four are loud: nothing 404s, the dead graph
        # simply goes on reserving its state names against every later author's
        # `inputs` - and against every unknown id, through the union.
        self.assertNotIn(workflow_id, WORKFLOW_RESERVED_RUN_INPUT_KEYS)


class UnpublishedDocumentsAreLeftAlone(BuilderRehydrationTestCase):
    """A draft is a drawing, not a workflow."""

    def test_a_draft_is_not_registered(self) -> None:
        from brief_crew.service.graph import WORKFLOWS

        document = _document(GOOD_ID)
        workflow_id = _workflow_id(document)
        self.track(workflow_id)
        persistence = self.persistence()
        self.publish_into(persistence, document, publish=False)

        report = self.sweep(persistence, self.registry(persistence))

        self.assertEqual(report.registered, ())
        self.assertEqual(report.skipped, ())
        self.assertEqual(report.attempted, 0)
        self.assertNotIn(workflow_id, WORKFLOWS)

    def test_a_published_document_that_is_then_saved_again_still_rehydrates(self) -> None:
        """`published()` reads the HEAD version, which is what `publish` marked.

        A save after a publish bumps the head, and the sweep follows it rather
        than restoring the version that happened to be published - the store's
        own `mark_published` compare-and-set is what keeps those in step.
        """

        from brief_crew.builder.store import BuilderDocumentStore

        document = _document(GOOD_ID)
        persistence = self.persistence()
        self.publish_into(persistence, document)
        store = BuilderDocumentStore(persistence)
        saved = store.save(document, expected_version=1)
        store.mark_published(saved.id, saved.document.version)
        workflow_id = _workflow_id(saved.document)
        self.track(workflow_id)

        report = self.sweep(persistence, self.registry(persistence))

        self.assertEqual(report.registered, (workflow_id,))


class StubStore:
    """A store whose `published()` does exactly what a test needs it to.

    A stub rather than a real row, because the two cases below are about the
    SWEEP: what it does when the generator raises, and what it reports when it
    could not read every row. Provoking those through SQLite would mean writing
    a corrupt payload past the store's own validation, which tests the corrupt
    payload rather than the sweep.

    `on_skipped` is accepted and ignored. The real store calls it for a row it
    could not parse; a stub that refused the keyword would make every case in
    this class fail with a TypeError swallowed as "the store would not answer",
    which is the least informative shape a stub can take.
    """

    def __init__(self, *, rows: Any = (), raises: Exception | None = None) -> None:
        self._rows = rows
        self._raises = raises

    def published(
        self, *, limit: int = 0, on_skipped: Any = None
    ) -> Any:
        if self._raises is not None and not self._rows:
            raise self._raises

        def generate() -> Any:
            for row in self._rows:
                yield row
            if self._raises is not None:
                raise self._raises

        return generate()


class AnUnreadableRowDoesNotTakeTheRestWithIt(BuilderRehydrationTestCase):
    """The defect: `_parse` raised from inside a generator, which closes it.

    Every published graph ordered BEHIND the bad one was then unreachable
    without a second query, so it stayed unregistered and answered 404 after the
    restart - and the order is `updated_at DESC`, which nobody publishing a
    graph chose. One author saving a stale document could unregister everybody
    else's, arbitrarily.

    Written against the REAL store rather than `StubStore`, because the whole
    question is what `BuilderDocumentStore.published()` does with a row - a stub
    could only restate the answer.
    """

    def corrupt(self, persistence: Any, document_id: str) -> None:
        """Make one stored version unparseable, and sort it to the FRONT.

        Written past `create`/`save` on purpose: both re-serialise a validated
        `BuilderDocument`, so a document this service refuses cannot be produced
        through them. The real one arrives by the schema moving under a row that
        was written years - or one deploy - ago.

        `updated_at` is pushed into the future in the same statement because
        `published()` orders by it: without that the bad row could sort second
        and the test would pass over the unfixed code.
        """

        from datetime import timedelta

        from sqlalchemy import update

        from brief_crew.service.persistence import (
            builder_document_versions,
            builder_documents,
            utcnow,
        )

        with persistence.begin() as connection:
            connection.execute(
                update(builder_document_versions)
                .where(builder_document_versions.c.document_id == document_id)
                .values(document={"schema": "builder.flow/v0", "id": document_id})
            )
            connection.execute(
                update(builder_documents)
                .where(builder_documents.c.id == document_id)
                .values(updated_at=utcnow() + timedelta(hours=1))
            )

    def test_a_good_row_behind_an_unparseable_one_is_still_registered(self) -> None:
        from brief_crew.service.graph import WORKFLOWS

        good = _document(GOOD_ID)
        workflow_id = _workflow_id(good)
        self.track(workflow_id)
        persistence = self.persistence()
        self.publish_into(persistence, good)
        self.publish_into(persistence, _document(BROKEN_ID))
        self.corrupt(persistence, BROKEN_ID)

        with self.assertLogs("brief_crew.builder.store", logging.WARNING) as logs:
            report = self.sweep(persistence, self.registry(persistence))

        self.assertEqual(report.registered, (workflow_id,))
        self.assertIn(workflow_id, WORKFLOWS)
        # Skipped, not silent: the id is in the report and in the log, because a
        # graph that stops existing without saying so is the defect this whole
        # module was written to close.
        self.assertEqual([entry[0] for entry in report.skipped], [BROKEN_ID])
        self.assertIn(BROKEN_ID, "\n".join(logs.output))
        # And the sweep read every row, so it must not claim otherwise.
        self.assertFalse(report.stopped_early)
        self.assertEqual(report.attempted, 2)

    def test_the_store_itself_skips_the_row_and_reports_it(self) -> None:
        """One layer down, without the sweep: `published()` is the fix site."""

        from brief_crew.builder.store import BuilderDocumentStore

        persistence = self.persistence()
        self.publish_into(persistence, _document(GOOD_ID))
        self.publish_into(persistence, _document(BROKEN_ID))
        self.corrupt(persistence, BROKEN_ID)

        seen: list[tuple[str, str]] = []
        with self.assertLogs("brief_crew.builder.store", logging.WARNING):
            rows = list(
                BuilderDocumentStore(persistence).published(
                    on_skipped=lambda document_id, reason: seen.append(
                        (document_id, reason)
                    )
                )
            )

        self.assertEqual([row.id for row in rows], [GOOD_ID])
        self.assertEqual([entry[0] for entry in seen], [BROKEN_ID])
        self.assertIn("no longer parses", seen[0][1])

    def test_load_still_raises_for_the_same_row(self) -> None:
        """The skip is `published()`'s policy alone.

        `load` was asked for this document by name, and answering "no such
        document" for a row sitting right there would be a 404 the author
        cannot act on.
        """

        from brief_crew.builder.store import BuilderDocumentStore, BuilderStoreError

        persistence = self.persistence()
        self.publish_into(persistence, _document(BROKEN_ID))
        self.corrupt(persistence, BROKEN_ID)

        with self.assertRaises(BuilderStoreError):
            BuilderDocumentStore(persistence).load(BROKEN_ID)


class TheSweepsRefusals(BuilderRehydrationTestCase):
    """Four states in which the sweep does nothing, loudly or quietly."""

    def test_a_store_that_refuses_mid_sweep_ends_it_and_says_so(self) -> None:
        """A raise from inside the generator CLOSES it, so the rows behind it
        are unreachable without a second query, and the report says
        `stopped_early` rather than offering a short list as a complete one.

        This is now the STORE failing, not one bad document: `published()`
        catches an unparseable row per row and reports it through `on_skipped`.
        The case is kept because the failure mode it pins - a short list read as
        a complete one - belongs to the sweep whatever raised."""

        from brief_crew.builder.store import BuilderStoreError

        document = _document(GOOD_ID)
        workflow_id = _workflow_id(document)
        self.track(workflow_id)
        persistence = self.persistence()
        registry = self.registry(persistence)

        class Row:
            id = GOOD_ID

            def __init__(self, doc: Any) -> None:
                self.document = doc

        store = StubStore(
            rows=(Row(document),),
            raises=BuilderStoreError("document ug_dead0000 is stored in a shape ..."),
        )

        with self.assertLogs("brief_crew.service.builder_rehydrate", logging.ERROR) as logs:
            report = self.sweep(persistence, registry, store=store)

        self.assertEqual(report.registered, (workflow_id,))
        self.assertTrue(report.stopped_early)
        self.assertIn("no longer parse", "\n".join(logs.output))

    def test_a_store_that_will_not_answer_at_all_stops_early_without_raising(self) -> None:
        persistence = self.persistence()
        store = StubStore(raises=RuntimeError("the database is not there"))

        with self.assertLogs("brief_crew.service.builder_rehydrate", logging.ERROR):
            report = self.sweep(persistence, self.registry(persistence), store=store)

        self.assertEqual(report.registered, ())
        self.assertTrue(report.stopped_early)

    def test_no_store_is_a_no_op(self) -> None:
        persistence = self.persistence()
        report = self.sweep(persistence, self.registry(persistence), store=None)
        self.assertEqual(report.registered, ())
        self.assertFalse(report.stopped_early)

    def test_a_single_workflow_registry_is_left_alone(self) -> None:
        """The older shape answers for ANY id from one default runtime, so
        adding an entry would change what every other workflow resolves to."""

        from brief_crew.service.graph import BRIEF_GRAPH, BRIEF_NODE_REGISTRY, WORKFLOWS
        from brief_crew.service.registry import RunRegistry

        document = _document(GOOD_ID)
        workflow_id = _workflow_id(document)
        self.track(workflow_id)
        persistence = self.persistence()
        self.publish_into(persistence, document)
        registry = RunRegistry(
            graph_version=BRIEF_GRAPH.version,
            node_registry=BRIEF_NODE_REGISTRY,
            runner=RefusesToRun(),
            persistence=persistence,
            gate_sweep_interval=0,
        )
        self.addCleanup(registry.close)

        report = self.sweep(persistence, registry)

        self.assertEqual(report.registered, ())
        self.assertNotIn(workflow_id, WORKFLOWS)

    def test_the_knob_off_registers_nothing(self) -> None:
        """`BUILDER_REHYDRATE_PUBLISHED=0` boots with no user graph registered.

        The lever for a graph that compiles and then wedges this deployment: a
        deploy-time flip rather than a code edit or a DELETE against somebody
        else's document.
        """

        from brief_crew.service.graph import WORKFLOWS

        document = _document(GOOD_ID)
        workflow_id = _workflow_id(document)
        self.track(workflow_id)
        persistence = self.persistence()
        self.publish_into(persistence, document)

        report = self.sweep(persistence, self.registry(persistence), enabled=False)

        self.assertEqual(report.registered, ())
        self.assertNotIn(workflow_id, WORKFLOWS)


@unittest.skipUnless(FASTAPI_AVAILABLE, "fastapi is not installed")
class CreateAppRunsTheSweep(BuilderRehydrationTestCase):
    """The wiring, not the sweep: a NEW app instance over the same store.

    This is the whole defect in one assertion - the first app publishes, the
    second app is a restart, and before this pass the second one had never
    heard of the graph.
    """

    def app(self, registry: Any) -> Any:
        from brief_crew.service.app import RunRateLimiter, create_app

        return create_app(
            registry=registry,
            rate_limiter=RunRateLimiter(max_runs=0),
            builder_runner_factory=lambda workflow: RefusesToRun(),
        )

    def test_a_second_app_over_the_same_store_knows_the_published_graph(self) -> None:
        from fastapi.testclient import TestClient

        document = _document(GOOD_ID)
        workflow_id = _workflow_id(document)
        self.track(workflow_id)
        persistence = self.persistence()
        self.publish_into(persistence, document)

        registry = self.registry(persistence)
        client = TestClient(self.app(registry))
        self.addCleanup(client.close)

        self.assertIn(workflow_id, registry.workflows)
        # The topology endpoint is the cheapest proof the graph is reachable
        # again; before the sweep existed this was a 404.
        response = client.get(f"/api/workflows/{workflow_id}/graph")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["id"], workflow_id)

    def test_a_broken_document_does_not_stop_the_app_from_being_built(self) -> None:
        from fastapi.testclient import TestClient

        persistence = self.persistence()
        self.publish_into(persistence, _document(BROKEN_ID, compiles=False))

        client = TestClient(self.app(self.registry(persistence)))
        self.addCleanup(client.close)

        self.assertEqual(client.get("/healthz").status_code, 200)
        self.assertEqual(
            {entry["id"] for entry in client.get("/api/workflows").json()},
            {"brief-flow", "idea-validator"},
        )


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
