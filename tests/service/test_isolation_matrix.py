"""The isolation matrix - plan 15 D9, criterion 10; the persistence half of rubric 14.

Every route this plan owns or consumes, run as user A (the owner), user B (a
signed-in stranger) and an anonymous caller, against a document A created,
with authentication on:

| Route                     | A               | B    | anonymous |
| ------------------------- | --------------- | ---- | --------- |
| list                      | sees it         | no   | 401       |
| get / versions / export   | 200             | 404  | 401       |
| save / delete / duplicate | 200 / 204 / 201 | 404  | 401       |
| import                    | 201, owner A    | 201, owner B, no reference to A's id | 401 |
| test inputs               | 200             | 404  | 401       |
| launch (published)        | 202             | 404, clean body OR a body carrying A's state names | 401, either body |

The "test inputs" row has no route in Stage 1 - plan 13 owns the panel - so it
is covered here at the level the table can be: `builder_test_inputs.user_id`
is NOT NULL, the only way to read a row is a query scoped to its owner, and
the rows go with their document. The route asserts the same three things the
day it exists. Plan 15 D9 records the same narrowing beside its table, dated
2026-09-03, so criterion 10's "exactly" is measured against a table that says
what this file checks.

And the UNOWNED row - `user_id IS NULL`, written before authentication or on a
deployment without it - one line per verb (round 2, D-15-7). Readable and
launchable by everyone, writable by nobody who has an identity:

| Route, unowned row        | A                  | B                  | anonymous, auth on | anonymous, auth off |
| ------------------------- | ------------------ | ------------------ | ------------------ | ------------------- |
| list                      | not listed         | not listed         | 401                | listed              |
| get / versions / export   | 200                | 200                | 401                | 200                 |
| duplicate                 | 201, owner A       | 201, owner B       | 401                | 201, unowned        |
| save / publish / delete   | **403**, names Duplicate | **403**, names Duplicate | 401       | 200 / 200 / 204     |
| launch (published)        | 202                | 202                | 401                | 202, or plan 01's gateless-graph 403 |
| create an unowned row     | impossible         | impossible         | 401                | 201                 |

The read carve-out (`store._visible_to`) exists to keep pre-auth rows usable;
it was never a licence to rewrite them, and until round 2 it was exactly that:
`_visible_to` was the sole gate on save, publish and delete, so alice could
overwrite, bob could publish and either could delete a row nobody could be
asked about. `store._writable_by` is the second gate. The anonymous caller on
an auth-off backend keeps write, because there the anonymous caller IS the
author and a refusal would make every local save a 403. An OWNED row stays
invisible to an anonymous caller even with authentication off.

404 and not 403 everywhere B is refused, because a 403 confirms the document
exists; the assertion is on the status AND on the body carrying nothing of A's.

The launch row is plan 01's, added in round 2 (D-01-4): `POST /runs` was in
the matrix only implicitly, through `test_workflow_ownership.py`, and that file
sent clean bodies alone. A body carrying one of A's own state names
(`__builder__`, `out__<node>`) used to answer 422 from the request schema
before the rate limiter and before the ownership 404 - an oracle for which ids
exist and what their nodes are called (D-01-1). Here B and the anonymous caller
send both bodies and must be unable to tell A's id from an invented one.
"""

from __future__ import annotations

import re
from typing import Any
import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient
from sqlalchemy import func, insert, select
from sqlalchemy.exc import IntegrityError

from brief_crew import config
from brief_crew.builder.store import BuilderDocumentStore
from brief_crew.config import BUILDER_DOCUMENT_ID_PATTERN
from brief_crew.service.app import create_app
from brief_crew.service.graph import builder_workflow
from brief_crew.service.persistence import (
    PostgresFlowPersistence,
    builder_test_inputs,
    utcnow,
)
from tests.builder.test_compiler import straight_line
from tests.service.builder_registration import forget_builder_workflow
from tests.service.builder_auth import (
    ADA,
    ADA_TOKEN,
    GRACE,
    GRACE_TOKEN,
    BuilderAuthCase,
    document_payload,
)

ANON = None
CALLERS = ((ADA_TOKEN, "A"), (GRACE_TOKEN, "B"), (ANON, "anonymous"))


class MatrixCase(BuilderAuthCase):
    """A's document, with two versions so `?version=` has something to pick."""

    def setUp(self) -> None:
        super().setUp()
        self.owned = self.create_as(ADA_TOKEN)["id"]
        saved = self.save_as(
            ADA_TOKEN, self.owned, document_payload(name="A's second"), expected_version=1
        )
        self.assertEqual(saved.status_code, 200, saved.text)

    def request(self, token: str | None, method: str, path: str, **kwargs: Any) -> Any:
        return getattr(self.client, method)(
            path, headers=self.auth(token) if token else {}, **kwargs
        )

    def assert_nothing_of_a_leaks(self, response: Any) -> None:
        self.assertNotIn(self.owned, response.text)
        self.assertNotIn("A's second", response.text)
        self.assertNotIn(ADA.id, response.text)

    def assert_a_untouched(self) -> None:
        body = self.get_as(ADA_TOKEN, self.owned).json()
        self.assertEqual(body["head_version"], 2)
        self.assertEqual(body["document"]["name"], "A's second")
        self.assertEqual(body["status"], "draft")


class ReadRoutes(MatrixCase):
    def test_list(self) -> None:
        self.assertIn(self.owned, self.list_ids_as(ADA_TOKEN))
        self.assertNotIn(self.owned, self.list_ids_as(GRACE_TOKEN))
        self.assertEqual(self.list_ids_as(GRACE_TOKEN), [])
        response = self.request(ANON, "get", "/api/builder/workflows")
        self.assertEqual(response.status_code, 401)
        self.assert_nothing_of_a_leaks(response)

    def test_get(self) -> None:
        for suffix in ("", "?version=1"):
            with self.subTest(route=f"get{suffix}"):
                path = f"/api/builder/workflows/{self.owned}{suffix}"
                self.assertEqual(self.request(ADA_TOKEN, "get", path).status_code, 200)
                refused = self.request(GRACE_TOKEN, "get", path)
                self.assertEqual(refused.status_code, 404)
                self.assert_nothing_of_a_leaks(refused)
                anonymous = self.request(ANON, "get", path)
                self.assertEqual(anonymous.status_code, 401)
                self.assert_nothing_of_a_leaks(anonymous)

    def test_an_unknown_version_is_named_for_a_and_is_the_constant_for_b(self) -> None:
        """D-15-8's other half: the version sentence must not become an oracle.

        A hears which version is missing and which is newest. B hears the same
        constant B hears for an id that does not exist at all, so `?version=`
        cannot be used to learn whether A's document exists.
        """

        path = f"/api/builder/workflows/{self.owned}?version=99"
        named = self.request(ADA_TOKEN, "get", path)
        self.assertEqual(named.status_code, 404)
        self.assertIn("version 99", named.json()["detail"])
        self.assertIn("newest is v2", named.json()["detail"])
        refused = self.request(GRACE_TOKEN, "get", path)
        control = self.request(GRACE_TOKEN, "get", "/api/builder/workflows/ug_00000000?version=99")
        self.assertEqual(refused.status_code, 404)
        self.assertEqual(refused.json(), {"detail": "document not found"})
        self.assertEqual(refused.json(), control.json())
        self.assert_nothing_of_a_leaks(refused)

    def test_versions(self) -> None:
        path = f"/api/builder/workflows/{self.owned}/versions"
        listed = self.request(ADA_TOKEN, "get", path)
        self.assertEqual(listed.status_code, 200)
        self.assertEqual([entry["version"] for entry in listed.json()], [2, 1])
        refused = self.request(GRACE_TOKEN, "get", path)
        self.assertEqual(refused.status_code, 404)
        self.assert_nothing_of_a_leaks(refused)
        self.assertEqual(self.request(ANON, "get", path).status_code, 401)

    def test_export(self) -> None:
        path = f"/api/builder/workflows/{self.owned}/export"
        exported = self.request(ADA_TOKEN, "get", path)
        self.assertEqual(exported.status_code, 200)
        # A's own export carries neither A's row id nor A's identity (D1).
        self.assertNotIn(self.owned, exported.text)
        self.assertNotIn(ADA.id, exported.text)
        refused = self.request(GRACE_TOKEN, "get", path)
        self.assertEqual(refused.status_code, 404)
        self.assert_nothing_of_a_leaks(refused)
        anonymous = self.request(ANON, "get", path)
        self.assertEqual(anonymous.status_code, 401)
        self.assert_nothing_of_a_leaks(anonymous)


class WriteRoutes(MatrixCase):
    def test_save(self) -> None:
        payload = document_payload(name="edited")
        refused = self.save_as(GRACE_TOKEN, self.owned, payload, expected_version=2)
        self.assertEqual(refused.status_code, 404)
        self.assert_nothing_of_a_leaks(refused)
        self.assertEqual(self.save_as(ANON, self.owned, payload, expected_version=2).status_code, 401)
        self.assert_a_untouched()
        accepted = self.save_as(ADA_TOKEN, self.owned, payload, expected_version=2)
        self.assertEqual(accepted.status_code, 200, accepted.text)
        self.assertEqual(accepted.json()["head_version"], 3)

    def test_duplicate(self) -> None:
        path = f"/api/builder/workflows/{self.owned}/duplicate"
        refused = self.request(GRACE_TOKEN, "post", path)
        self.assertEqual(refused.status_code, 404)
        self.assert_nothing_of_a_leaks(refused)
        self.assertEqual(self.list_ids_as(GRACE_TOKEN), [])
        self.assertEqual(self.request(ANON, "post", path).status_code, 401)
        accepted = self.request(ADA_TOKEN, "post", path)
        self.assertEqual(accepted.status_code, 201, accepted.text)
        self.assertIn(accepted.json()["id"], self.list_ids_as(ADA_TOKEN))
        self.assertEqual(self.list_ids_as(GRACE_TOKEN), [])

    def test_delete(self) -> None:
        path = f"/api/builder/workflows/{self.owned}"
        refused = self.request(GRACE_TOKEN, "delete", path)
        self.assertEqual(refused.status_code, 404)
        self.assert_nothing_of_a_leaks(refused)
        self.assert_a_untouched()
        self.assertEqual(self.request(ANON, "delete", path).status_code, 401)
        self.assert_a_untouched()
        self.assertEqual(self.request(ADA_TOKEN, "delete", path).status_code, 204)
        self.assertEqual(self.get_as(ADA_TOKEN, self.owned).status_code, 404)

    def test_import(self) -> None:
        envelope = self.export_as(ADA_TOKEN, self.owned).json()

        as_a = self.import_as(ADA_TOKEN, envelope)
        self.assertEqual(as_a.status_code, 201, as_a.text)
        self.assertIn(as_a.json()["id"], self.list_ids_as(ADA_TOKEN))
        self.assertNotIn(as_a.json()["id"], self.list_ids_as(GRACE_TOKEN))

        as_b = self.import_as(GRACE_TOKEN, envelope)
        self.assertEqual(as_b.status_code, 201, as_b.text)
        b_id = as_b.json()["id"]
        self.assertRegex(b_id, BUILDER_DOCUMENT_ID_PATTERN)
        self.assertNotEqual(b_id, self.owned)
        self.assertIn(b_id, self.list_ids_as(GRACE_TOKEN))
        self.assertNotIn(b_id, self.list_ids_as(ADA_TOKEN))
        self.assertEqual(self.get_as(ADA_TOKEN, b_id).status_code, 404)
        # No reference to A: not A's row id, not A's identity, and - because
        # the export cannot carry them (D1) - no credential, server or skill
        # id of A's anywhere in what B now holds.
        self.assertNotIn(self.owned, as_b.text)
        self.assertNotIn(ADA.id, as_b.text)
        self.assertEqual(
            re.findall(r"\b(?:cr|mcp|skill)_[0-9a-f]+\b", as_b.text), []
        )

        self.assertEqual(self.import_as(ANON, envelope).status_code, 401)
        self.assertEqual(len(self.list_ids_as(GRACE_TOKEN)), 1)


class LaunchRoute(MatrixCase):
    """`POST /api/sessions/{s}/runs` against A's PUBLISHED document (plan 01 D1).

    Two bodies per caller: the clean one, and one carrying a state name the
    publish registered for this graph. The second is the D-01-4 proof - the
    answer must not depend on the body for anyone but the owner.
    """

    RUNS = "/api/sessions/session-matrix/runs"
    UNKNOWN = "ug_00000000"

    def setUp(self) -> None:
        super().setUp()
        published = self.request(ADA_TOKEN, "post", f"/api/builder/workflows/{self.owned}/publish")
        self.assertEqual(published.status_code, 200, published.text)
        self.workflow_id = published.json()["workflow_id"]
        self.addCleanup(forget_builder_workflow, self.workflow_id)
        registered = config.reserved_run_input_keys(self.workflow_id) - config.GLOBAL_RESERVED_RUN_INPUT_KEYS
        self.state_keys = ["__builder__", next(k for k in sorted(registered) if k.startswith("out__"))]
        for key in self.state_keys:
            self.assertIn(key, registered)

    def bodies(self, workflow_id: str) -> dict[str, dict[str, Any]]:
        clean = {"workflow_id": workflow_id, "inputs": {"idea": "a scheduling assistant for clinics"}}
        out: dict[str, dict[str, Any]] = {"clean": clean}
        for key in self.state_keys:
            out[key] = {**clean, "inputs": {**clean["inputs"], key: "x"}}
        return out

    def test_a_launches_her_own_graph(self) -> None:
        response = self.request(ADA_TOKEN, "post", self.RUNS, json=self.bodies(self.workflow_id)["clean"])
        self.assertEqual(response.status_code, 202, response.text)
        self.app.state.run_registry.wait(response.json()["run_id"], timeout=30)

    def test_a_is_refused_her_own_state_names_with_a_422_naming_them(self) -> None:
        for key, body in self.bodies(self.workflow_id).items():
            if key == "clean":
                continue
            with self.subTest(key=key):
                response = self.request(ADA_TOKEN, "post", self.RUNS, json=body)
                self.assertEqual(response.status_code, 422, response.text)
                self.assertIn(key, response.json()["detail"])

    def test_b_cannot_tell_a_s_graph_from_an_invented_one_with_either_body(self) -> None:
        before = self.app.state.run_registry.admission_status()
        foreign, unknown = self.bodies(self.workflow_id), self.bodies(self.UNKNOWN)
        for key in foreign:
            with self.subTest(body=key):
                refused = self.request(GRACE_TOKEN, "post", self.RUNS, json=foreign[key])
                control = self.request(GRACE_TOKEN, "post", self.RUNS, json=unknown[key])
                self.assertEqual(refused.status_code, 404, refused.text)
                self.assertEqual(refused.json(), {"detail": "workflow not found"})
                self.assertEqual((refused.status_code, refused.json()), (control.status_code, control.json()))
                self.assert_nothing_of_a_leaks(refused)
                self.assertNotIn(key, refused.text)
        self.assertEqual(self.app.state.run_registry.admission_status(), before)
        self.assertEqual(self.request(GRACE_TOKEN, "get", "/api/runs").json()["runs"], [])

    def test_anonymous_is_401_with_either_body_and_for_either_id(self) -> None:
        foreign, unknown = self.bodies(self.workflow_id), self.bodies(self.UNKNOWN)
        for key in foreign:
            with self.subTest(body=key):
                refused = self.request(ANON, "post", self.RUNS, json=foreign[key])
                control = self.request(ANON, "post", self.RUNS, json=unknown[key])
                self.assertEqual(refused.status_code, 401, refused.text)
                self.assertEqual((refused.status_code, refused.json()), (control.status_code, control.json()))
                self.assert_nothing_of_a_leaks(refused)
                self.assertNotIn(key, refused.text)


class TestInputsTable(MatrixCase):
    """The row of the table with no route yet - plan 13 owns the panel."""

    def persistence(self) -> PostgresFlowPersistence:
        return self.app.state.run_registry.persistence

    def seed_input(self, *, user_id: str | None, document_id: str | None = None) -> str:
        row_id = f"ti_{(user_id or 'none')[-4:]}{document_id or self.owned}"[:32]
        now = utcnow()
        with self.persistence().begin() as connection:
            connection.execute(
                insert(builder_test_inputs).values(
                    id=row_id,
                    user_id=user_id,
                    document_id=document_id or self.owned,
                    label="clinics",
                    inputs={"idea": "a scheduling assistant for clinics"},
                    node_mocks=None,
                    created_at=now,
                    updated_at=now,
                )
            )
        return row_id

    def scoped(self, caller: str | None) -> list[str]:
        """The only read the route may make: rows WHERE user_id = caller."""

        predicate = (
            builder_test_inputs.c.user_id.is_(None)
            if caller is None
            else builder_test_inputs.c.user_id == caller
        )
        with self.persistence().connect() as connection:
            rows = connection.execute(
                select(builder_test_inputs.c.id).where(predicate)
            ).scalars().all()
        return [str(row) for row in rows]

    def test_a_row_without_an_owner_is_refused_by_the_table(self) -> None:
        """Isolation rule 1: `user_id` is NOT NULL, so "anonymous" has no row."""

        with self.assertRaises(IntegrityError):
            self.seed_input(user_id=None)
        self.assertEqual(self.scoped(None), [])

    def test_a_s_input_is_visible_to_a_query_scoped_to_a_and_to_nobody_else(self) -> None:
        row_id = self.seed_input(user_id=ADA.id)
        self.assertEqual(self.scoped(ADA.id), [row_id])
        self.assertEqual(self.scoped(GRACE.id), [])
        self.assertEqual(self.scoped(None), [])

    def test_the_rows_go_with_their_document(self) -> None:
        self.seed_input(user_id=ADA.id)
        self.assertEqual(self.request(ADA_TOKEN, "delete", f"/api/builder/workflows/{self.owned}").status_code, 204)
        with self.persistence().connect() as connection:
            remaining = connection.execute(
                select(func.count()).select_from(builder_test_inputs)
            ).scalar_one()
        self.assertEqual(int(remaining), 0)


class UnownedRowCarveOut(BuilderAuthCase):
    """The unowned row with auth ON: readable by A and B, writable by neither.

    One test per verb, so the D9 table above is what a red test names. Every
    write asserts the row afterwards - version, status, registration - because
    "403" alone would also be the answer from a handler that refused AFTER it
    had unregistered or half-written something.
    """

    def setUp(self) -> None:
        super().setUp()
        self.unowned = self.store().create(straight_line()).id

    def request(self, token: str | None, method: str, path: str, **kwargs: Any) -> Any:
        return getattr(self.client, method)(
            path, headers=self.auth(token) if token else {}, **kwargs
        )

    def assert_untouched(self) -> None:
        loaded = self.store().load(self.unowned)
        self.assertEqual(loaded.head_version, 1)
        self.assertEqual(loaded.status, "draft")
        self.assertIsNone(loaded.user_id)
        self.assertIsNone(builder_workflow(self.unowned))

    def assert_points_at_duplicate(self, response: Any) -> None:
        self.assertEqual(response.status_code, 403, response.text)
        detail = response.json()["detail"]
        self.assertIn("Duplicate", detail)
        self.assertIn(self.unowned, detail)
        self.assertIn("no owner", detail)

    def test_a_signed_in_a_and_b_both_read_an_unowned_row(self) -> None:
        for token, who in ((ADA_TOKEN, "A"), (GRACE_TOKEN, "B")):
            with self.subTest(caller=who):
                self.assertEqual(self.get_as(token, self.unowned).status_code, 200)
                self.assertEqual(
                    self.request(token, "get", f"/api/builder/workflows/{self.unowned}/versions").status_code,
                    200,
                )
                self.assertEqual(self.export_as(token, self.unowned).status_code, 200)

    def test_an_unowned_row_is_not_in_a_signed_in_user_s_list(self) -> None:
        """`list` is SQL-scoped to the caller: theirs, not theirs-plus-everything."""

        self.assertNotIn(self.unowned, self.list_ids_as(ADA_TOKEN))
        self.assertNotIn(self.unowned, self.list_ids_as(GRACE_TOKEN))

    def test_save_is_403_for_a_and_for_b_and_the_row_is_untouched(self) -> None:
        for token, who in ((ADA_TOKEN, "A"), (GRACE_TOKEN, "B")):
            with self.subTest(caller=who):
                refused = self.save_as(
                    token, self.unowned, document_payload(name="rewritten"), expected_version=1
                )
                self.assert_points_at_duplicate(refused)
                self.assert_untouched()

    def test_publish_is_403_for_a_and_for_b_and_registers_nothing(self) -> None:
        for token, who in ((ADA_TOKEN, "A"), (GRACE_TOKEN, "B")):
            with self.subTest(caller=who):
                refused = self.request(
                    token, "post", f"/api/builder/workflows/{self.unowned}/publish"
                )
                self.assert_points_at_duplicate(refused)
                self.assertNotIn(self.unowned, self.app.state.run_registry.workflows)
                self.assert_untouched()

    def test_delete_is_403_for_a_and_for_b_and_the_row_stays(self) -> None:
        for token, who in ((ADA_TOKEN, "A"), (GRACE_TOKEN, "B")):
            with self.subTest(caller=who):
                refused = self.request(token, "delete", f"/api/builder/workflows/{self.unowned}")
                self.assert_points_at_duplicate(refused)
                self.assert_untouched()
                self.assertEqual(self.get_as(GRACE_TOKEN, self.unowned).status_code, 200)

    def test_duplicate_is_the_remedy_and_each_caller_gets_their_own_copy(self) -> None:
        copies: dict[str, str] = {}
        for token, who in ((ADA_TOKEN, "A"), (GRACE_TOKEN, "B")):
            with self.subTest(caller=who):
                accepted = self.request(
                    token, "post", f"/api/builder/workflows/{self.unowned}/duplicate"
                )
                self.assertEqual(accepted.status_code, 201, accepted.text)
                copies[who] = accepted.json()["id"]
                self.assertIn(copies[who], self.list_ids_as(token))
                # The copy is theirs to write.
                edited = self.save_as(
                    token, copies[who], document_payload(name="mine now"), expected_version=1
                )
                self.assertEqual(edited.status_code, 200, edited.text)
        self.assertNotIn(copies["A"], self.list_ids_as(GRACE_TOKEN))
        self.assertNotIn(copies["B"], self.list_ids_as(ADA_TOKEN))
        self.assert_untouched()

    def test_an_anonymous_caller_is_still_refused_while_auth_is_required(self) -> None:
        self.assertEqual(self.get_as(None, self.unowned).status_code, 401)
        for method, path in (
            ("put", f"/api/builder/workflows/{self.unowned}"),
            ("post", f"/api/builder/workflows/{self.unowned}/publish"),
            ("delete", f"/api/builder/workflows/{self.unowned}"),
            ("post", f"/api/builder/workflows/{self.unowned}/duplicate"),
        ):
            with self.subTest(route=f"{method} {path}"):
                kwargs = (
                    {"json": {"document": document_payload(), "expected_version": 1}}
                    if method == "put"
                    else {}
                )
                self.assertEqual(self.request(None, method, path, **kwargs).status_code, 401)
        self.assert_untouched()

    def test_nobody_can_create_an_unowned_row_while_auth_is_required(self) -> None:
        """The last row of the table: with identity on, every new row has an owner."""

        created = self.client.post("/api/builder/workflows", json={"document": document_payload()})
        self.assertEqual(created.status_code, 401, created.text)
        envelope = self.export_as(ADA_TOKEN, self.unowned).json()
        self.assertEqual(self.import_as(None, envelope).status_code, 401)
        # And A's own create is owned - the only kind this deployment can mint.
        owned = self.create_as(ADA_TOKEN)
        self.assertEqual(self.store().load(owned["id"], user_id=ADA.id).user_id, ADA.id)


class UnownedCreationWithAuthConfiguredButNotRequired(BuilderAuthCase):
    """`AUTH_BASE_URL` set, `VALIDATOR_REQUIRE_AUTH` switched off by hand.

    The one deployment shape that reaches a handler with nobody in hand while
    identity exists. Reads of an unowned row stay open; minting a new unowned
    row is refused, because on this backend it would be writable by nobody.
    """

    def setUp(self) -> None:
        super().setUp()
        relaxed = patch.object(config, "VALIDATOR_REQUIRE_AUTH", False)
        relaxed.start()
        self.addCleanup(relaxed.stop)
        self.unowned = self.store().create(straight_line()).id

    def test_anonymous_reads_stay_open(self) -> None:
        self.assertEqual(self.get_as(None, self.unowned).status_code, 200)

    def test_anonymous_creation_is_refused_with_401_on_every_minting_route(self) -> None:
        created = self.client.post("/api/builder/workflows", json={"document": document_payload()})
        self.assertEqual(created.status_code, 401, created.text)
        self.assertIn("owner", created.json()["detail"])
        envelope = self.export_as(None, self.unowned).json()
        self.assertEqual(self.import_as(None, envelope).status_code, 401)
        duplicated = self.client.post(f"/api/builder/workflows/{self.unowned}/duplicate")
        self.assertEqual(duplicated.status_code, 401, duplicated.text)
        # Nothing was minted: the unowned row is still the only unowned row.
        self.assertEqual(
            [row["id"] for row in self.client.get("/api/builder/workflows").json()],
            [self.unowned],
        )

    def test_a_signed_in_create_is_owned(self) -> None:
        owned = self.create_as(ADA_TOKEN)
        self.assertEqual(self.store().load(owned["id"], user_id=ADA.id).user_id, ADA.id)


class UnownedRowWithAuthOff(unittest.TestCase):
    """The same rows on a service with no identity to check.

    Anonymous here is the author - there is nobody else - so the write verbs
    are open to them. Synthetic identities (`X-Synthetic-User`) are signed-in
    users on this app and meet the same 403 A and B do above; they are what
    proves "launchable by everyone" over a graph an anonymous author published.
    """

    RUNS = "/api/sessions/session-unowned/runs"

    def setUp(self) -> None:
        self.app = create_app(synthetic=True, database_url="sqlite+pysqlite:///:memory:")
        self.client = TestClient(self.app)
        self.addCleanup(self.client.close)
        store = BuilderDocumentStore(self.app.state.run_registry.persistence)
        self.unowned = store.create(straight_line()).id
        owned_payload = straight_line().model_copy(update={"id": "ug_0000aaaa"})
        self.owned = store.create(owned_payload, user_id=ADA.id).id

    def as_user(self, user: str) -> dict[str, str]:
        return {"X-Synthetic-User": user}

    def test_anonymous_reads_and_lists_the_unowned_row(self) -> None:
        self.assertEqual(self.client.get(f"/api/builder/workflows/{self.unowned}").status_code, 200)
        self.assertEqual(
            self.client.get(f"/api/builder/workflows/{self.unowned}/export").status_code, 200
        )
        listed = self.client.get("/api/builder/workflows")
        self.assertEqual(listed.status_code, 200)
        self.assertIn(self.unowned, [row["id"] for row in listed.json()])

    def test_an_owned_row_stays_invisible_to_anonymous_even_with_auth_off(self) -> None:
        """Signing out must not be the cheapest way to read everybody's drafts."""

        self.assertEqual(self.client.get(f"/api/builder/workflows/{self.owned}").status_code, 404)
        listed = self.client.get("/api/builder/workflows")
        self.assertNotIn(self.owned, [row["id"] for row in listed.json()])

    def test_anonymous_creates_saves_and_deletes_an_unowned_row(self) -> None:
        created = self.client.post("/api/builder/workflows", json={"document": document_payload()})
        self.assertEqual(created.status_code, 201, created.text)
        row_id = created.json()["id"]
        saved = self.client.put(
            f"/api/builder/workflows/{row_id}",
            json={"document": document_payload(name="local edit"), "expected_version": 1},
        )
        self.assertEqual(saved.status_code, 200, saved.text)
        self.assertEqual(saved.json()["head_version"], 2)
        self.assertEqual(self.client.delete(f"/api/builder/workflows/{row_id}").status_code, 204)
        self.assertEqual(self.client.get(f"/api/builder/workflows/{row_id}").status_code, 404)

    def test_a_synthetic_user_meets_the_same_403_a_signed_in_user_does(self) -> None:
        refused = self.client.put(
            f"/api/builder/workflows/{self.unowned}",
            json={"document": document_payload(name="rewritten"), "expected_version": 1},
            headers=self.as_user("alice"),
        )
        self.assertEqual(refused.status_code, 403, refused.text)
        self.assertIn("Duplicate", refused.json()["detail"])
        self.assertEqual(
            self.client.delete(
                f"/api/builder/workflows/{self.unowned}", headers=self.as_user("bob")
            ).status_code,
            403,
        )
        self.assertEqual(
            self.client.get(f"/api/builder/workflows/{self.unowned}").json()["head_version"], 1
        )

    def test_an_unowned_graph_the_author_published_launches_for_everyone(self) -> None:
        published = self.client.post(f"/api/builder/workflows/{self.unowned}/publish")
        self.assertEqual(published.status_code, 200, published.text)
        workflow_id = published.json()["workflow_id"]
        self.addCleanup(forget_builder_workflow, workflow_id)
        body = {"workflow_id": workflow_id, "inputs": {"idea": "a scheduling assistant for clinics"}}
        for headers, who in ((self.as_user("alice"), "A"), (self.as_user("bob"), "B")):
            with self.subTest(caller=who):
                launched = self.client.post(self.RUNS, json=body, headers=headers)
                self.assertEqual(launched.status_code, 202, launched.text)
                self.app.state.run_registry.wait(launched.json()["run_id"], timeout=30)
        # The anonymous caller meets a DIFFERENT rule here, and it is named so
        # this row cannot be misread as isolation: `straight_line` bills before
        # any gate, and an anonymous launch of such a graph is refused unless
        # `BUILDER_ALLOW_GATELESS_GRAPHS` is set (CLAUDE.md section 9). Ownership
        # is not what refused it - the sentence says to sign in OR add a gate.
        anonymous = self.client.post(self.RUNS, json=body)
        self.assertEqual(anonymous.status_code, 403, anonymous.text)
        self.assertIn("gate", anonymous.json()["detail"])
