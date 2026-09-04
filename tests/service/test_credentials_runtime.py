"""A credential resolved INSIDE the step, and nowhere else - 10 D2, criterion 3.

Plan 01 built the vault and `tests/builder/test_credential_resolution.py` holds
the compiler and the API to it; `tests/service/test_secret_redaction.py` holds
the two redaction walks. What is left, and what this module is, is the RUNTIME
half of D2:

* the plaintext reaches one place - the `LLM` the step constructs - and is on no
  state key, no frame, no `flow_states` row, no `runs` row and no export;
* it is resolvable only under `current_run_user`, so a step that somehow ran
  outside a scoped run resolves nothing rather than resolving somebody's;
* another user's id is `credential-not-yours`, by that name, on the frame.

**The credential is REALLY resolved here, and that is the point of the odd
factory below.** A plain `SyntheticCrewFactories` never calls `_authored_llm`,
so a leak test over a synthetic run would pass without the secret ever having
been fetched - the exact "green for the wrong reason" this repository keeps a
section for. `ResolvingFactories` builds the REAL `Agent` and the REAL `LLM`,
which resolves the credential and costs nothing (construction calls no model),
and only then hands back a synthetic crew to kick off.
"""

from __future__ import annotations

import importlib.util
import io
import json
from typing import Any
import unittest
import zipfile

from brief_crew.builder.runtime import DefaultCrewFactories, _authored_llm
from brief_crew.events.redaction import SECRET_KEYS, is_secret_key
from brief_crew.service.builder_runner import SyntheticCrewFactories
from brief_crew.service.credentials import (
    CredentialNotYours,
    credential_scope,
    current_run_user,
    resolve_credential,
)
from tests.builder.test_compiler import authored_agent_node, input_node, output_node
from tests.builder.test_document import document, edge
from tests.service.identities import SECRET, AuthenticatedTwoUserCase, wire

FASTAPI_AVAILABLE = importlib.util.find_spec("fastapi") is not None
IDEA = "a scheduling assistant for clinics"


class ResolvingFactories(SyntheticCrewFactories):
    """Builds the real `Agent` (and so the real `LLM`), kicks off synthetically.

    Constructing an `Agent` with an `LLM` calls no model, so this is free - and
    it is the only shape in which a free run really goes through
    `_agent_api_key`. `built` keeps the constructed agents so a test can look at
    where the plaintext ended up.
    """

    def __init__(self, failures: str | None = None) -> None:
        super().__init__(failures=failures)
        self.built: list[Any] = []

    def authored_agent_crew(self, *, node_id: str, spec: Any) -> Any:
        self.built.append(DefaultCrewFactories()._authored_agent(spec, node_id=node_id))
        return super().authored_agent_crew(node_id=node_id, spec=spec)


def credentialled_graph(credential_id: str) -> Any:
    return document(
        [
            input_node(),
            authored_agent_node("draft", credential_id=credential_id),
            output_node("report", source="${state.out__draft}"),
        ],
        [edge("e1", "idea", "draft"), edge("e2", "draft", "report")],
    )


class SecretListTests(unittest.TestCase):
    """D2's four names, and the one that was missing."""

    def test_the_four_d2_names_are_all_secret(self) -> None:
        for name in ("api_key", "headers", "authorization", "env"):
            with self.subTest(name=name):
                self.assertTrue(is_secret_key(name))

    def test_env_is_an_exact_entry_and_not_a_suffix_accident(self) -> None:
        """`env` ends in none of the suffixes, so it had to be listed.

        An MCP stdio server's whole environment block lives under that name
        (plan 07), which is where a `GITHUB_TOKEN` sits in a shape the suffix
        rule cannot see because the rule looks at the OUTER key.
        """

        self.assertIn("env", SECRET_KEYS)


@unittest.skipUnless(FASTAPI_AVAILABLE, "fastapi is not installed")
class ResolutionScopeTests(AuthenticatedTwoUserCase):
    def setUp(self) -> None:
        super().setUp()
        self.registry = self.app.state.run_registry
        self.credential = self.create_credential(self.as_alice())["id"]

    def test_the_owner_under_scope_gets_the_plaintext(self) -> None:
        with credential_scope(user_id="user_alice", persistence=self.registry.persistence):
            resolved = resolve_credential(self.credential)
        self.assertEqual(resolved.fields["api_key"], SECRET)

    def test_the_scope_is_the_only_thing_that_authorises_it(self) -> None:
        """No `current_run_user` means no answer, rather than a default one."""

        self.assertIsNone(current_run_user.get())
        with credential_scope(user_id=None, persistence=self.registry.persistence):
            with self.assertRaises(CredentialNotYours):
                resolve_credential(self.credential)

    def test_somebody_else_gets_credential_not_yours_by_that_name(self) -> None:
        with credential_scope(user_id="user_bob", persistence=self.registry.persistence):
            with self.assertRaises(CredentialNotYours) as caught:
                resolve_credential(self.credential)
        self.assertEqual(caught.exception.error_class, "credential-not-yours")
        # And the sentence does not say whose it was.
        self.assertNotIn("alice", str(caught.exception).lower())

    def test_the_plaintext_reaches_the_llm_and_no_state_key(self) -> None:
        """D2: held by the `LLM` for the life of the step, and written nowhere."""

        with credential_scope(user_id="user_alice", persistence=self.registry.persistence):
            llm = _authored_llm(
                {"model": "google/gemini-3.8-flash"},
                credential_id=self.credential,
                node_id="draft",
            )
        self.assertEqual(llm.api_key, SECRET)
        # Constructing it called no model: this whole test costs nothing.
        self.assertEqual(llm.stream, True)


@unittest.skipUnless(FASTAPI_AVAILABLE, "fastapi is not installed")
class SentinelNeverLeavesTests(AuthenticatedTwoUserCase):
    """One run that REALLY resolves the key, then every surface it could reach."""

    def setUp(self) -> None:
        super().setUp()
        self.registry = self.app.state.run_registry
        self.credential = self.create_credential(self.as_alice())["id"]
        _, self.workflow_id = self.publish(
            credentialled_graph(self.credential), self.as_alice()
        )
        self.factories = ResolvingFactories()
        self.registry.workflow_runtime(self.workflow_id).runner.crew_factories = (
            self.factories
        )
        response = self.client.post(
            "/api/sessions/s1/runs",
            json={"workflow_id": self.workflow_id, "inputs": {"idea": IDEA}},
            headers=self.as_alice(),
        )
        self.assertEqual(response.status_code, 202, response.text)
        self.run_id = response.json()["run_id"]
        self.registry.wait(self.run_id, timeout=20)

    def test_the_run_really_did_resolve_the_credential(self) -> None:
        """The control. Without this the four assertions below prove nothing."""

        self.assertEqual(len(self.factories.built), 1)
        self.assertEqual(self.factories.built[0].llm.api_key, SECRET)

    def test_no_frame_carries_it(self) -> None:
        page = self.client.get(
            f"/api/runs/{self.run_id}/frames?limit=500", headers=self.as_alice()
        )
        self.assertNotIn(SECRET, page.text)

    def test_no_flow_states_row_carries_it(self) -> None:
        from sqlalchemy import select

        from brief_crew.service.persistence import flow_states

        with self.registry.persistence.connect() as connection:
            rows = connection.execute(select(flow_states.c.state)).fetchall()
        self.assertTrue(rows, "the run wrote no state at all; this would be vacuous")
        self.assertNotIn(SECRET, json.dumps([dict(row[0]) for row in rows]))

    def test_no_runs_row_carries_it(self) -> None:
        row = self.registry.persistence.get_run(self.run_id)
        self.assertNotIn(SECRET, json.dumps(row, default=str))

    def test_the_status_payload_does_not_carry_it(self) -> None:
        response = self.client.get(
            f"/api/runs/{self.run_id}", headers=self.as_alice()
        )
        self.assertNotIn(SECRET, response.text)

    def test_the_ndjson_export_does_not_carry_it(self) -> None:
        response = self.client.get(
            f"/api/runs/{self.run_id}/logs?format=ndjson", headers=self.as_alice()
        )
        self.assertEqual(response.status_code, 200, response.text)
        self.assertNotIn(SECRET, response.text)

    def test_the_zip_export_does_not_carry_it(self) -> None:
        response = self.client.get(
            f"/api/runs/{self.run_id}/logs?format=zip", headers=self.as_alice()
        )
        self.assertEqual(response.status_code, 200)
        with zipfile.ZipFile(io.BytesIO(response.content)) as archive:
            for name in archive.namelist():
                self.assertNotIn(SECRET, archive.read(name).decode("utf-8", "replace"))

    def test_the_compiled_preview_does_not_carry_it(self) -> None:
        """C7's `compiled` route is handed a LABEL function, never the vault."""

        documents = self.client.get(
            "/api/builder/workflows", headers=self.as_alice()
        ).json()
        document_id = documents[0]["id"]
        response = self.client.get(
            f"/api/builder/workflows/{document_id}/compiled", headers=self.as_alice()
        )
        self.assertEqual(response.status_code, 200, response.text)
        self.assertNotIn(SECRET, response.text)
        # And it says which credential, by the caller's own name for it.
        self.assertIn("My OpenRouter key", response.json()["python"])


@unittest.skipUnless(FASTAPI_AVAILABLE, "fastapi is not installed")
class CredentialGoneAtRunTimeTests(AuthenticatedTwoUserCase):
    """The one shape in which a run really meets `credential-not-yours`.

    **Naming somebody else's credential is refused at PUBLISH** (plan 01 D10) -
    asserted below, because a test that assumed otherwise would have been
    exercising a path no author can reach. What IS reachable is the credential
    that was theirs at publish and is not theirs now: deleted since, or
    rehydrated at boot, which passes no identity at all.
    """

    def setUp(self) -> None:
        super().setUp()
        self.registry = self.app.state.run_registry

    def test_naming_somebody_elses_credential_is_refused_at_publish(self) -> None:
        credential = self.create_credential(self.as_alice())["id"]
        created = self.client.post(
            "/api/builder/workflows",
            json={"document": wire(credentialled_graph(credential))},
            headers=self.as_bob(),
        )
        self.assertEqual(created.status_code, 201, created.text)
        published = self.client.post(
            f"/api/builder/workflows/{created.json()['document']['id']}/publish",
            headers=self.as_bob(),
        )
        self.assertEqual(published.status_code, 422, published.text)
        self.assertIn("credential-missing", published.text)

    def test_a_credential_deleted_since_publish_fails_the_node_and_names_nobody(
        self,
    ) -> None:
        credential = self.create_credential(self.as_alice())["id"]
        _, workflow_id = self.publish(
            credentialled_graph(credential), self.as_alice()
        )
        self.registry.workflow_runtime(workflow_id).runner.crew_factories = (
            ResolvingFactories()
        )
        deleted = self.client.delete(
            f"/api/builder/credentials/{credential}", headers=self.as_alice()
        )
        self.assertIn(deleted.status_code, (200, 204), deleted.text)

        run_id = self.client.post(
            "/api/sessions/s1/runs",
            json={"workflow_id": workflow_id, "inputs": {"idea": IDEA}},
            headers=self.as_alice(),
        ).json()["run_id"]
        self.registry.wait(run_id, timeout=20)
        body = self.client.get(f"/api/runs/{run_id}", headers=self.as_alice()).json()
        self.assertEqual(body["status"], "failed")
        rendered = json.dumps(body, default=str)
        self.assertNotIn(SECRET, rendered)
        self.assertNotIn("alice", rendered.lower())


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
