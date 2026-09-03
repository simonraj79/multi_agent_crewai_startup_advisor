"""Import is a create with one extra fact - plan 15 D2, S1 ruling 7; criterion 2.

`POST /api/builder/workflows/import` takes the D1 envelope and answers 201 with
the same model shape as `POST /workflows` plus `needs_credentials`, a list of
node ids. It ALWAYS creates: the file carries no id worth honouring - the
export dropped it, and a hand-edited one is somebody else's row - so the
importer mints an id the way `create` does, owns the result, and never touches
the document the file came from.

Two properties carry the weight here. An import as user B of a file A exported
produces a document B owns, with a fresh `ug_` id and NO reference to A's id
anywhere in the answer. And a file that names a credential does not become a
reference to a credential the importer does not own: today the v1 schema
refuses the key outright (`extra="forbid"`), and the day plan 01 lands
`AgentConfig.credential_id` the inbound strip turns it to `null` and the node
lands in `needs_credentials` - which is why the strip is proved to be ON the
path now rather than the day it has a field to act on.

`needs_credentials` is not a problem code (ruling 7): the client renders the
list as an import notice group, and the only server-side `credential-missing`
belongs to `validate`.
"""

from __future__ import annotations

import re
from unittest.mock import patch

from brief_crew.builder.upgrade import KNOWN_SCHEMAS, SCHEMA_V2
from brief_crew.config import BUILDER_DOCUMENT_ID_PATTERN, BUILDER_DOCUMENT_SCHEMA
from brief_crew.service import builder_api
from tests.service.builder_auth import (
    ADA_TOKEN,
    GRACE_TOKEN,
    BuilderAuthCase,
    document_payload,
)

CREATE_KEYS = {
    "id",
    "document",
    "status",
    "version",
    "head_version",
    "created_at",
    "updated_at",
    "problems",
    "budget",
    "graph",
    "published",
}


class ImportRouteCase(BuilderAuthCase):
    def exported_by_ada(self) -> tuple[str, dict]:
        """A's document and the envelope A's export produced for it."""

        created = self.create_as(ADA_TOKEN)
        response = self.export_as(ADA_TOKEN, created["id"])
        self.assertEqual(response.status_code, 200, response.text)
        return created["id"], response.json()


class ImportCreatesForTheImporter(ImportRouteCase):
    def test_the_route_is_not_shadowed_by_the_document_lookup(self) -> None:
        """`import` is a perfectly good-looking document id.

        Declared after `/workflows/{document_id}` it would be answered by
        `get_document` as a 404 for a document called "import", which reads as
        a missing feature rather than a wrong route.
        """

        _, envelope = self.exported_by_ada()
        response = self.import_as(ADA_TOKEN, envelope)
        self.assertEqual(response.status_code, 201, response.text)

    def test_b_importing_a_s_file_owns_a_fresh_draft(self) -> None:
        """Criterion 2, the ownership half."""

        ada_id, envelope = self.exported_by_ada()
        response = self.import_as(GRACE_TOKEN, envelope)
        self.assertEqual(response.status_code, 201, response.text)
        body = response.json()

        self.assertRegex(body["id"], BUILDER_DOCUMENT_ID_PATTERN)
        self.assertNotEqual(body["id"], ada_id)
        self.assertEqual(body["status"], "draft")
        self.assertEqual(body["version"], 1)
        self.assertEqual(body["head_version"], 1)
        self.assertFalse(body["published"])
        self.assertEqual(
            response.headers["Location"], f"/api/builder/workflows/{body['id']}"
        )
        # Owned by the importer: in B's list, absent from A's, invisible to A.
        self.assertIn(body["id"], self.list_ids_as(GRACE_TOKEN))
        self.assertNotIn(body["id"], self.list_ids_as(ADA_TOKEN))
        self.assertEqual(self.get_as(ADA_TOKEN, body["id"]).status_code, 404)
        self.assertEqual(self.get_as(GRACE_TOKEN, body["id"]).status_code, 200)

    def test_the_answer_carries_no_reference_to_the_source_document(self) -> None:
        """D9: B's import of A's file references nothing of A's."""

        ada_id, envelope = self.exported_by_ada()
        response = self.import_as(GRACE_TOKEN, envelope)
        self.assertEqual(response.status_code, 201, response.text)
        self.assertNotIn(ada_id, response.text)
        self.assertNotIn("user_ada", response.text)

    def test_the_source_document_is_untouched(self) -> None:
        """Import never overwrites, even when the file names an existing id."""

        ada_id, envelope = self.exported_by_ada()
        envelope["document"]["id"] = ada_id
        envelope["document"]["version"] = 7
        envelope["document"]["name"] = "Renamed in the file"
        response = self.import_as(ADA_TOKEN, envelope)
        self.assertEqual(response.status_code, 201, response.text)
        self.assertNotEqual(response.json()["id"], ada_id)
        self.assertEqual(response.json()["version"], 1)
        original = self.get_as(ADA_TOKEN, ada_id).json()
        self.assertEqual(original["head_version"], 1)
        self.assertEqual(original["document"]["name"], "Test graph")

    def test_the_answer_is_the_create_shape_plus_exactly_one_key(self) -> None:
        """S1 ruling 7: the client already knows how to open a create."""

        _, envelope = self.exported_by_ada()
        body = self.import_as(ADA_TOKEN, envelope).json()
        self.assertEqual(set(body), CREATE_KEYS | {"needs_credentials"})

    def test_the_envelope_name_fills_a_document_that_has_none(self) -> None:
        _, envelope = self.exported_by_ada()
        del envelope["document"]["name"]
        envelope["name"] = "From the file"
        response = self.import_as(ADA_TOKEN, envelope)
        self.assertEqual(response.status_code, 201, response.text)
        self.assertEqual(response.json()["document"]["name"], "From the file")

    def test_the_nodes_and_edges_arrive_as_exported(self) -> None:
        _, envelope = self.exported_by_ada()
        body = self.import_as(GRACE_TOKEN, envelope).json()
        self.assertEqual(body["document"]["nodes"], envelope["document"]["nodes"])
        self.assertEqual(body["document"]["edges"], envelope["document"]["edges"])
        self.assertEqual(body["document"]["schema"], BUILDER_DOCUMENT_SCHEMA)


class NeedsCredentials(ImportRouteCase):
    def test_a_clean_export_needs_nothing(self) -> None:
        _, envelope = self.exported_by_ada()
        self.assertEqual(envelope["needs_credentials"], [])
        self.assertEqual(self.import_as(ADA_TOKEN, envelope).json()["needs_credentials"], [])

    def test_the_envelope_s_own_list_is_never_trusted(self) -> None:
        """Criterion 2, the problem-group half: the list is RE-DERIVED.

        A client may send `[]`, the list the export wrote, or a list naming
        nodes that have no credential slot at all. None of it reaches the
        answer: the server reads the document's own nulled keys and nothing
        else, so a file cannot talk a node into a notice - or out of one.
        """

        _, envelope = self.exported_by_ada()
        for declared in ([], ["scoper"], ["ghost", "scoper", "scoper", "report"]):
            with self.subTest(declared=declared):
                envelope["needs_credentials"] = declared
                body = self.import_as(GRACE_TOKEN, envelope).json()
                self.assertEqual(body["needs_credentials"], [])

    def test_the_inbound_strip_is_on_the_path_and_is_the_only_source(self) -> None:
        """Nothing makes a file honest, so the importer strips again.

        Proved by observation rather than by a field: no committed schema
        carries a secret-bearing key yet (plan 01 lands `credential_id`), so
        the spy stands in for the day one does - and asserts that what the
        strip reports is what the answer carries, kept to node ids the
        document has, once each, with the envelope's list playing no part.
        """

        _, envelope = self.exported_by_ada()
        envelope["needs_credentials"] = ["scoper"]
        seen: list[dict] = []
        real = builder_api.strip_for_export

        def spy(raw, **kwargs):
            seen.append(dict(raw))
            document, _ = real(raw, **kwargs)
            return document, ["report", "ghost", "report", "idea"]

        with patch.object(builder_api, "strip_for_export", spy):
            response = self.import_as(GRACE_TOKEN, envelope)
        self.assertEqual(response.status_code, 201, response.text)
        self.assertEqual(len(seen), 1)
        self.assertEqual(seen[0]["name"], envelope["document"]["name"])
        self.assertEqual(response.json()["needs_credentials"], ["report", "idea"])

    def test_a_hand_typed_credential_id_never_becomes_a_reference(self) -> None:
        """The v1 schema forbids the key, so the file is refused by name.

        When `AgentConfig.credential_id` exists (S1 ruling 8) this same file
        imports with the value stripped to null and `scoper` in
        `needs_credentials`; either way the importer never holds A's id.
        """

        _, envelope = self.exported_by_ada()
        scoper = next(n for n in envelope["document"]["nodes"] if n["id"] == "scoper")
        scoper["config"]["credential_id"] = "cr_deadbeef"
        response = self.import_as(GRACE_TOKEN, envelope)
        if response.status_code == 201:
            body = response.json()
            self.assertNotIn("cr_deadbeef", response.text)
            self.assertIn("scoper", body["needs_credentials"])
        else:
            self.assertEqual(response.status_code, 422, response.text)
            self.assertIn("credential_id", response.json()["detail"])
            # Refused means nothing was created for the importer.
            self.assertEqual(self.list_ids_as(GRACE_TOKEN), [])


class EnvelopeRefusals(ImportRouteCase):
    def test_an_export_string_this_service_does_not_know_is_refused_naming_both(self) -> None:
        _, envelope = self.exported_by_ada()
        envelope["export"] = "builder.flow/v9"
        response = self.import_as(ADA_TOKEN, envelope)
        self.assertEqual(response.status_code, 422, response.text)
        detail = response.json()["detail"]
        for known in KNOWN_SCHEMAS:
            self.assertIn(known, detail)
        self.assertIn("builder.flow/v9", detail)

    def test_a_v2_file_is_accepted_by_name_and_refused_by_the_schema(self) -> None:
        """S1 ruling 4: v2 imports the day 03 lands. Until then the refusal is
        the schema's own sentence, not a second one about the envelope."""

        _, envelope = self.exported_by_ada()
        envelope["export"] = SCHEMA_V2
        envelope["document"]["schema"] = SCHEMA_V2
        response = self.import_as(ADA_TOKEN, envelope)
        self.assertEqual(response.status_code, 422, response.text)
        detail = response.json()["detail"]
        self.assertIn("unknown document schema", detail)
        self.assertNotIn("export must be one of", detail)

    def test_the_document_is_the_one_part_that_is_not_optional(self) -> None:
        response = self.import_as(ADA_TOKEN, {"export": BUILDER_DOCUMENT_SCHEMA})
        self.assertEqual(response.status_code, 422)
        self.assert_one_sentence(response, names="document")

    def test_a_key_the_envelope_does_not_have_is_refused(self) -> None:
        _, envelope = self.exported_by_ada()
        envelope["owner"] = "user_ada"
        response = self.import_as(ADA_TOKEN, envelope)
        self.assertEqual(response.status_code, 422)
        self.assert_one_sentence(response, names="owner")
        # The refusal names the KEY and never its value.
        self.assertNotIn("user_ada", response.text)

    def test_more_needs_credentials_than_a_graph_can_have_is_refused(self) -> None:
        _, envelope = self.exported_by_ada()
        envelope["needs_credentials"] = [
            f"n{index}" for index in range(builder_api.MAX_IMPORT_NEEDS_CREDENTIALS + 1)
        ]
        response = self.import_as(ADA_TOKEN, envelope)
        self.assertEqual(response.status_code, 422)
        self.assert_one_sentence(response, names="needs_credentials")
        # D-15-9: not one of the entries comes back.
        self.assertNotIn("n0", response.text)
        self.assertNotIn(f"n{builder_api.MAX_IMPORT_NEEDS_CREDENTIALS}", response.text)

    def assert_one_sentence(self, response, *, names: str) -> None:
        """D-15-9: a string, not pydantic's list, and it names the first problem."""

        detail = response.json()["detail"]
        self.assertIsInstance(detail, str, response.text)
        self.assertIn(names, detail)
        self.assertNotIn('"input"', response.text)
        self.assertNotIn('"loc"', response.text)


class MalformedFilesEchoNothing(ImportRouteCase):
    """D-15-9. A malformed or foreign file is refused with one sentence naming
    the first problem, and the body is never reflected back: an uploaded file
    can carry anything, including somebody else's secrets."""

    def post_raw(self, body: bytes, content_type: str = "application/json"):
        return self.client.post(
            "/api/builder/workflows/import",
            content=body,
            headers={**self.auth(ADA_TOKEN), "Content-Type": content_type},
        )

    def test_a_raw_document_with_no_envelope_names_export_and_echoes_no_node(self) -> None:
        document = document_payload(name="A secret-shaped name")
        document["nodes"][0]["label"] = "sk-live-do-not-echo"
        response = self.import_as(ADA_TOKEN, document)
        self.assertEqual(response.status_code, 422, response.text)
        detail = response.json()["detail"]
        self.assertIsInstance(detail, str)
        self.assertIn("export", detail)
        self.assertNotIn("sk-live-do-not-echo", response.text)
        self.assertNotIn("A secret-shaped name", response.text)
        self.assertNotIn(document["nodes"][0]["id"], response.text)

    def test_an_unrelated_object_names_the_first_missing_field_only(self) -> None:
        response = self.import_as(ADA_TOKEN, {"foo": 1})
        self.assertEqual(response.status_code, 422)
        detail = response.json()["detail"]
        self.assertIsInstance(detail, str)
        self.assertEqual(detail.count(":"), 1, detail)
        self.assertIn("export", detail)
        self.assertNotIn("foo", response.text)

    def test_a_json_list_is_named_as_a_list(self) -> None:
        response = self.post_raw(b'["not", "an", "envelope"]')
        self.assertEqual(response.status_code, 422, response.text)
        detail = response.json()["detail"]
        self.assertIsInstance(detail, str)
        self.assertIn("JSON list", detail)
        self.assertNotIn("envelope", detail.replace("`export` and `document`", ""))

    def test_a_file_that_is_not_json_is_named_without_being_quoted(self) -> None:
        response = self.post_raw(b"password=hunter2\nnot json at all")
        self.assertEqual(response.status_code, 422, response.text)
        detail = response.json()["detail"]
        self.assertIsInstance(detail, str)
        self.assertIn("not JSON", detail)
        self.assertNotIn("hunter2", response.text)

    def test_the_document_size_bound_holds_on_the_raw_bytes(self) -> None:
        from brief_crew.config import MAX_BUILDER_DOCUMENT_BYTES

        padding = "x" * (MAX_BUILDER_DOCUMENT_BYTES + 1)
        response = self.post_raw(('{"export": "' + padding + '"}').encode())
        self.assertEqual(response.status_code, 413, response.text[:200])
        self.assertNotIn(padding[:64], response.json()["detail"])

    def test_a_document_the_schema_refuses_is_a_422_naming_the_node(self) -> None:
        _, envelope = self.exported_by_ada()
        envelope["document"]["nodes"][0]["kind"] = "teleporter"
        response = self.import_as(ADA_TOKEN, envelope)
        self.assertEqual(response.status_code, 422, response.text)
        self.assertNotIn("Internal Server Error", response.text)

    def test_an_anonymous_import_is_refused(self) -> None:
        _, envelope = self.exported_by_ada()
        self.assertEqual(self.import_as(None, envelope).status_code, 401)
        # Nothing was created for anybody: A still has only the original.
        self.assertEqual(len(self.list_ids_as(ADA_TOKEN)), 1)
        self.assertEqual(self.list_ids_as(GRACE_TOKEN), [])


class MintedIds(ImportRouteCase):
    def test_two_imports_of_one_file_are_two_documents(self) -> None:
        _, envelope = self.exported_by_ada()
        first = self.import_as(GRACE_TOKEN, envelope).json()["id"]
        second = self.import_as(GRACE_TOKEN, envelope).json()["id"]
        self.assertNotEqual(first, second)
        self.assertTrue(re.fullmatch(BUILDER_DOCUMENT_ID_PATTERN, first))
        self.assertTrue(re.fullmatch(BUILDER_DOCUMENT_ID_PATTERN, second))
        self.assertEqual(sorted(self.list_ids_as(GRACE_TOKEN)), sorted([first, second]))

    def test_the_document_id_in_the_answer_is_the_server_s(self) -> None:
        _, envelope = self.exported_by_ada()
        body = self.import_as(GRACE_TOKEN, envelope).json()
        self.assertEqual(body["document"]["id"], body["id"])
        self.assertEqual(body["document"]["version"], 1)

    def test_the_plain_document_payload_still_imports_without_an_export(self) -> None:
        """A client may build the envelope around a document it has in hand."""

        response = self.import_as(
            ADA_TOKEN,
            {"export": BUILDER_DOCUMENT_SCHEMA, "document": document_payload()},
        )
        self.assertEqual(response.status_code, 201, response.text)
