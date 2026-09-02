"""Plan 01 D5: ids in the definition, fields inside the entrypoint, nowhere else.

Three claims, each asserted against the real compiler and the real flow
engine with only the model replaced:

1. **The compiled definition carries ids only (C5).** A document naming three
   credentials compiles to a `crewai.flow/v1` dict whose serialisation
   contains the three ids and not one field value - a string search over the
   whole thing, because a schema assertion would only prove where a key is
   NOT, and the claim is that it is nowhere.
2. **`resolve_credential` inside `run_agent` answers for the run's owner and
   nobody else.** The factories receive the plaintext when the scope is
   Alice's; Bob's scope raises `CredentialNotYours` before anything is built;
   an unowned run raises the same; no scope at all is `VaultUnavailable`.
3. **`last_used_at` moves** when a run resolves a row, and not before.

Then the same refusal through `RunRegistry`, because plan 01 promises it
surfaces as a `node_error` frame carrying `error_class: credential-not-yours`
(C6), and a frame is a fact about the registry rather than the compiler.
"""

from __future__ import annotations

import json
import unittest
from typing import Any, Sequence

import yaml

from brief_crew.builder.compiler import compile_document
from brief_crew.builder.descriptor import build_builder_workflow
from brief_crew.builder.runtime import BuilderRuntimeError
from brief_crew.events.serializer import error_class_of
from brief_crew.service.credentials import (
    CredentialNotYours,
    CredentialStore,
    VaultUnavailable,
    credential_scope,
    current_run_user,
    resolve_credential,
)
from brief_crew.service.persistence import PostgresFlowPersistence
from tests.builder.test_compiler import input_node, output_node, run, scoper_node, straight_line
from tests.builder.test_document import document, edge

ALICE = "user_alice"
BOB = "user_bob"
SECRETS = (
    "sk-or-v1-one-NEVER-IN-A-DEFINITION",
    "sk-or-v1-two-NEVER-IN-A-DEFINITION",
    "sk-or-v1-three-NEVER-IN-A-DEFINITION",
)
IDEA = "a scheduling assistant for clinics"


class KeyCapturingFactories:
    """Records the `api_key` each agent node was built with; builds nothing paid."""

    def __init__(self) -> None:
        self.keys: list[tuple[str, str | None]] = []

    def agent_crew(self, *, node_id: str, api_key: str | None = None, **_: Any) -> Any:
        self.keys.append((node_id, api_key))
        return _Crew(node_id)

    def crew(self, *, node_id: str, **_: Any) -> Any:  # pragma: no cover - no crew nodes here
        return _Crew(node_id)


class _Crew:
    def __init__(self, node_id: str) -> None:
        self.node_id = node_id

    def kickoff(self, inputs: Any = None) -> str:
        return json.dumps({"node_id": self.node_id})


def keyed_chain(credential_ids: Sequence[str | None]) -> Any:
    """input -> s1 -> s2 -> s3 -> report, each agent naming a credential (or not)."""

    nodes: list[dict[str, Any]] = [input_node()]
    for index, credential_id in enumerate(credential_ids, start=1):
        agent = scoper_node(f"s{index}")
        if credential_id is not None:
            agent["config"]["credential_id"] = credential_id
        nodes.append(agent)
    nodes.append(output_node(source=f"${{state.out__s{len(credential_ids)}}}"))
    edges = [edge("e0", "idea", "s1")]
    for index in range(1, len(credential_ids)):
        edges.append(edge(f"e{index}", f"s{index}", f"s{index + 1}"))
    edges.append(edge(f"e{len(credential_ids)}", f"s{len(credential_ids)}", "report"))
    return document(nodes, edges)


class VaultCase(unittest.TestCase):
    """A service store with three of Alice's keys in it."""

    def setUp(self) -> None:
        self.persistence = PostgresFlowPersistence("sqlite+pysqlite:///:memory:")
        self.addCleanup(self.persistence.close)
        # The CONFIG key, deliberately: `credential_scope` builds its own store
        # from `config.CREDENTIALS_MASTER_KEY`, so a test key here would seal
        # rows the run could never open.
        self.store = CredentialStore(self.persistence)
        self.ids = tuple(
            self.store.create(ALICE, kind="openrouter", label=f"key {index}", fields={"api_key": secret}).id
            for index, secret in enumerate(SECRETS)
        )

    def owned_by_alice(self, credential_id: str) -> bool:
        return self.store.exists(ALICE, credential_id)


class CompiledDefinitionTests(VaultCase):
    def test_the_definition_carries_the_three_ids_and_no_field_value(self) -> None:
        compiled = compile_document(keyed_chain(self.ids), credential_check=self.owned_by_alice)
        for rendered in (json.dumps(compiled.definition), yaml.safe_dump(compiled.definition)):
            for credential_id in self.ids:
                self.assertIn(credential_id, rendered)
            for secret in SECRETS:
                self.assertNotIn(secret, rendered)
            self.assertNotIn("api_key", rendered)

    def test_each_agent_step_names_its_own_id_in_its_with_block(self) -> None:
        compiled = compile_document(keyed_chain(self.ids), credential_check=self.owned_by_alice)
        # The arguments sit under `do.with` - the C5 shape - not on the method.
        by_node = {
            method["do"]["with"]["node_id"]: method["do"]["with"]
            for method in compiled.definition["methods"].values()
            if "agent_id" in (method.get("do") or {}).get("with", {})
        }
        self.assertEqual(sorted(by_node), ["s1", "s2", "s3"])
        self.assertEqual([by_node[f"s{i}"]["credential_id"] for i in (1, 2, 3)], list(self.ids))

    def test_a_node_naming_no_credential_compiles_without_the_key(self) -> None:
        compiled = compile_document(straight_line())
        with_blocks = [
            (method.get("do") or {}).get("with") or {}
            for method in compiled.definition["methods"].values()
        ]
        # The control: the agent's block IS there, so the absence below is a
        # fact about the key and not about the lookup.
        self.assertTrue(any("agent_id" in block for block in with_blocks))
        for block in with_blocks:
            self.assertNotIn("credential_id", block)

    def test_the_published_workflow_is_as_clean_as_the_definition(self) -> None:
        workflow = build_builder_workflow(
            keyed_chain(self.ids), user_id=ALICE, credential_check=self.owned_by_alice
        )
        rendered = json.dumps(workflow.compiled.definition)
        for secret in SECRETS:
            self.assertNotIn(secret, rendered)
        self.assertEqual(workflow.user_id, ALICE)


class RunTimeResolutionTests(VaultCase):
    def _run(self, *, user_id: str | None, persistence: Any) -> KeyCapturingFactories:
        compiled = compile_document(keyed_chain(self.ids))
        factories = KeyCapturingFactories()
        with credential_scope(user_id=user_id, persistence=persistence):
            run(compiled, inputs={"idea": IDEA}, factories=factories)
        return factories

    def test_the_owner_gets_the_fields_and_last_used_at_moves(self) -> None:
        for credential_id in self.ids:
            self.assertIsNone(self.store.get(ALICE, credential_id).last_used_at)

        factories = self._run(user_id=ALICE, persistence=self.persistence)

        self.assertEqual(factories.keys, [("s1", SECRETS[0]), ("s2", SECRETS[1]), ("s3", SECRETS[2])])
        for credential_id in self.ids:
            self.assertIsNotNone(self.store.get(ALICE, credential_id).last_used_at)

    def test_anybody_else_is_refused_before_a_single_node_is_built(self) -> None:
        compiled = compile_document(keyed_chain(self.ids))
        factories = KeyCapturingFactories()
        with credential_scope(user_id=BOB, persistence=self.persistence):
            with self.assertRaises(CredentialNotYours) as caught:
                run(compiled, inputs={"idea": IDEA}, factories=factories)
        self.assertEqual(factories.keys, [])
        self.assertEqual(caught.exception.error_class, "credential-not-yours")
        self.assertIn(self.ids[0], str(caught.exception))
        for secret in SECRETS:
            self.assertNotIn(secret, str(caught.exception))
        for credential_id in self.ids:
            self.assertIsNone(self.store.get(ALICE, credential_id).last_used_at)

    def test_an_unowned_run_resolves_nothing(self) -> None:
        with self.assertRaises(CredentialNotYours):
            self._run(user_id=None, persistence=self.persistence)

    def test_no_scope_at_all_is_vault_unavailable(self) -> None:
        compiled = compile_document(keyed_chain(self.ids))
        with self.assertRaises(VaultUnavailable):
            run(compiled, inputs={"idea": IDEA}, factories=KeyCapturingFactories())
        with self.assertRaises(VaultUnavailable):
            resolve_credential(self.ids[0])

    def test_a_scope_over_a_bare_crewai_store_has_no_vault(self) -> None:
        import tempfile
        from pathlib import Path

        from crewai.flow.persistence.sqlite import SQLiteFlowPersistence

        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as directory:
            bare = SQLiteFlowPersistence(str(Path(directory) / "flows.db"))
            with self.assertRaises(VaultUnavailable):
                self._run(user_id=ALICE, persistence=bare)

    def test_the_scope_does_not_outlive_the_call(self) -> None:
        with credential_scope(user_id=ALICE, persistence=self.persistence):
            self.assertEqual(current_run_user.get(), ALICE)
        self.assertIsNone(current_run_user.get())
        with self.assertRaises(VaultUnavailable):
            resolve_credential(self.ids[0])

    def test_a_credential_of_the_wrong_kind_is_refused_by_kind_name_only(self) -> None:
        token = "ghp_NEVER-IN-A-SENTENCE"
        github = self.store.create(ALICE, kind="github", label="gh", fields={"token": token}).id
        compiled = compile_document(keyed_chain((github,)))
        with credential_scope(user_id=ALICE, persistence=self.persistence):
            with self.assertRaises(BuilderRuntimeError) as caught:
                run(compiled, inputs={"idea": IDEA}, factories=KeyCapturingFactories())
        message = str(caught.exception)
        self.assertIn("github", message)
        self.assertIn("openrouter", message)
        self.assertNotIn(token, message)

    def test_a_credential_deleted_since_publish_fails_the_owner_too(self) -> None:
        self.store.delete(ALICE, self.ids[1])
        with self.assertRaises(CredentialNotYours) as caught:
            self._run(user_id=ALICE, persistence=self.persistence)
        self.assertIn(self.ids[1], str(caught.exception))


class ErrorClassTests(unittest.TestCase):
    def test_the_exception_names_its_class_for_the_frame(self) -> None:
        self.assertEqual(error_class_of(CredentialNotYours("cr_0000aaaa")), {"error_class": "credential-not-yours"})
        self.assertEqual(error_class_of(RuntimeError("plain")), {})


class RegistryFrameTests(VaultCase):
    """The refusal reaches the operator as a frame, not just a traceback."""

    def test_a_strangers_run_fails_with_a_credential_not_yours_frame(self) -> None:
        from brief_crew.service.builder_runner import BuilderFlowRunner
        from brief_crew.service.models import RunStatus
        from brief_crew.service.registry import RunRegistry, WorkflowRuntime

        workflow = build_builder_workflow(keyed_chain(self.ids))
        factories = KeyCapturingFactories()
        runner = BuilderFlowRunner(workflow, crew_factories=factories)
        registry = RunRegistry(
            graph_version=workflow.graph_version,
            node_registry=workflow.node_registry,
            runner=runner,
            workflows={
                workflow.workflow_id: WorkflowRuntime(
                    graph_version=workflow.graph_version,
                    node_registry=workflow.node_registry,
                    runner=runner,
                    input_field=workflow.input_field,
                )
            },
            persistence=self.persistence,
        )
        self.addCleanup(registry.close)

        record = registry.create_run(
            session_id="s", workflow_id=workflow.workflow_id, inputs={"idea": IDEA}, user_id=BOB
        )
        registry.start_run(record.run_id)
        try:
            registry.wait(record.run_id, timeout=30)
        except Exception:  # noqa: BLE001 - the failure is what is under test
            pass

        self.assertIs(registry.require(record.run_id).status, RunStatus.FAILED)
        self.assertEqual(factories.keys, [])
        frames = registry.all_frames(record.run_id)
        classed = [
            frame for frame in frames
            if (frame.get("details") or {}).get("error_class") == "credential-not-yours"
        ]
        self.assertTrue(classed, "no frame carried error_class=credential-not-yours")
        self.assertTrue(any(frame["node_id"] == "s1" for frame in classed))
        rendered = json.dumps(frames)
        for secret in SECRETS:
            self.assertNotIn(secret, rendered)

    def test_the_owners_run_through_the_registry_completes(self) -> None:
        from brief_crew.service.builder_runner import BuilderFlowRunner
        from brief_crew.service.models import RunStatus
        from brief_crew.service.registry import RunRegistry, WorkflowRuntime

        workflow = build_builder_workflow(keyed_chain(self.ids))
        factories = KeyCapturingFactories()
        runner = BuilderFlowRunner(workflow, crew_factories=factories)
        registry = RunRegistry(
            graph_version=workflow.graph_version,
            node_registry=workflow.node_registry,
            runner=runner,
            workflows={
                workflow.workflow_id: WorkflowRuntime(
                    graph_version=workflow.graph_version,
                    node_registry=workflow.node_registry,
                    runner=runner,
                    input_field=workflow.input_field,
                )
            },
            persistence=self.persistence,
        )
        self.addCleanup(registry.close)

        record = registry.create_run(
            session_id="s", workflow_id=workflow.workflow_id, inputs={"idea": IDEA}, user_id=ALICE
        )
        registry.start_run(record.run_id)
        registry.wait(record.run_id, timeout=30)

        self.assertIs(registry.require(record.run_id).status, RunStatus.COMPLETED)
        self.assertEqual([key for _, key in factories.keys], list(SECRETS))
        rendered = json.dumps(registry.all_frames(record.run_id))
        for secret in SECRETS:
            self.assertNotIn(secret, rendered)


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
