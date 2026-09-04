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
    # `published` answers "is THIS version live"; `live_version` answers WHICH
    # one is, which is the fact the gallery and the document bar were missing
    # (critic round product-1, P-04/P-05).
    "live_version",
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

    def test_the_file_the_export_wrote_names_the_node_that_lost_a_key(self) -> None:
        """The defect, as its own round trip (round 3, D-15-19).

        This is the critic's probe: A sets a credential, exports, and B
        imports THAT FILE. Before the intersection the answer was `[]` - the
        export had already nulled the key, so the inbound strip found nothing
        to strip and reported nothing, the notice built for exactly this case
        was unreachable, and the graph silently dropped from A's key to the
        platform key.

        The secret itself must not be in the file either, which is the
        property the export has always had and this must not cost.
        """

        created = self.create_as(ADA_TOKEN)
        payload = document_payload()
        for node in payload["nodes"]:
            if node["id"] == "scoper":
                node.setdefault("config", {})["credential_id"] = "cr_421c20d8"
        saved = self.save_as(
            ADA_TOKEN, created["id"], payload, expected_version=created["version"]
        )
        if saved.status_code != 200:
            self.skipTest(f"the schema refuses a credential_id here: {saved.text[:120]}")

        exported = self.export_as(ADA_TOKEN, created["id"])
        self.assertEqual(exported.status_code, 200, exported.text)
        envelope = exported.json()
        self.assertEqual(envelope["needs_credentials"], ["scoper"])
        self.assertNotIn("cr_421c20d8", exported.text)

        body = self.import_as(GRACE_TOKEN, envelope).json()
        self.assertEqual(body["needs_credentials"], ["scoper"])
        self.assertNotIn("cr_421c20d8", str(body))

    def test_the_intersection_drops_a_name_the_file_cannot_back_up(self) -> None:
        """Direction one: the envelope alone is a claim, and a file can lie.

        `ghost` is not a node at all; `report` is a node with no credential
        slot, so nothing about it is empty-and-present. Neither reaches the
        answer, which is what stops a hand-written envelope talking a node
        into a notice.
        """

        _, envelope = self.exported_by_ada()
        envelope["needs_credentials"] = ["ghost", "report", "scoper", "scoper"]
        body = self.import_as(GRACE_TOKEN, envelope).json()
        self.assertNotIn("ghost", body["needs_credentials"])
        self.assertNotIn("report", body["needs_credentials"])

    def test_the_intersection_drops_an_empty_key_the_envelope_never_claimed(self) -> None:
        """Direction two: an empty key is not a claim.

        Every agent node serialises with `credential_id: null` since S1
        ruling 8, so reading the keys alone reported every clean export as
        needing a credential. An empty list therefore stays empty however
        many null keys the document carries.
        """

        _, envelope = self.exported_by_ada()
        from brief_crew.builder.export import nulled_reference_nodes

        # The premise: there IS an empty key to be tempted by.
        self.assertTrue(nulled_reference_nodes(envelope["document"]))
        envelope["needs_credentials"] = []
        body = self.import_as(GRACE_TOKEN, envelope).json()
        self.assertEqual(body["needs_credentials"], [])

    def test_the_inbound_strip_is_on_the_path_and_is_one_of_the_two_sources(self) -> None:
        """Nothing makes a file honest, so the importer still strips again.

        What changed in round 3 is that the strip is no longer the ONLY
        source. A node it reports really did lose a value here, which is this
        server's own observation rather than the file's claim, so it is
        answered on its own - that is the case
        `test_a_hand_typed_credential_id_never_becomes_a_reference` fixes in
        place. What the strip cannot do is invent a node: `ghost` is not in
        the document and does not appear, and the list is de-duplicated and
        ordered by the document rather than by the strip.
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
        answered = response.json()["needs_credentials"]
        self.assertNotIn("ghost", answered)
        self.assertEqual(len(answered), len(set(answered)))
        # Document order, not the strip's - the strip said report before idea.
        document_order = [node["id"] for node in envelope["document"]["nodes"]]
        self.assertEqual(answered, [n for n in document_order if n in set(answered)])

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


class ImportedNamesStayDistinct(ImportRouteCase):
    """D-15-4: the import kept the file's exact name, so A's own export imported
    back was a second row reading "Minimal gated agent" letter for letter."""

    def test_your_own_export_imported_back_is_named_as_an_import(self) -> None:
        source_id, envelope = self.exported_by_ada()
        first = self.import_as(ADA_TOKEN, envelope)
        second = self.import_as(ADA_TOKEN, envelope)
        self.assertEqual(first.status_code, 201, first.text)
        self.assertEqual(first.json()["document"]["name"], "Test graph imported")
        self.assertEqual(second.json()["document"]["name"], "Test graph imported 2")
        self.assertEqual(self.get_as(ADA_TOKEN, source_id).json()["document"]["name"], "Test graph")

    def test_a_colleague_s_file_keeps_its_name_in_a_library_without_one(self) -> None:
        _, envelope = self.exported_by_ada()
        as_b = self.import_as(GRACE_TOKEN, envelope)
        self.assertEqual(as_b.status_code, 201, as_b.text)
        self.assertEqual(as_b.json()["document"]["name"], "Test graph")
        again = self.import_as(GRACE_TOKEN, envelope)
        self.assertEqual(again.json()["document"]["name"], "Test graph imported")

    def test_a_name_at_the_bound_still_gets_its_suffix_and_its_number(self) -> None:
        from brief_crew.config import BUILDER_MAX_NAME_CHARS

        long_name = "n" * BUILDER_MAX_NAME_CHARS
        created = self.create_as(ADA_TOKEN, document_payload(name=long_name))
        envelope = self.export_as(ADA_TOKEN, created["id"]).json()
        first = self.import_as(ADA_TOKEN, envelope).json()["document"]["name"]
        second = self.import_as(ADA_TOKEN, envelope).json()["document"]["name"]
        self.assertTrue(first.endswith(" imported"))
        self.assertTrue(second.endswith(" imported 2"))
        self.assertLessEqual(len(first), BUILDER_MAX_NAME_CHARS)
        self.assertLessEqual(len(second), BUILDER_MAX_NAME_CHARS)
        self.assertNotEqual(first, second)


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


class SchemaRefusalsNameSomethingVisible(ImportRouteCase):
    """D-15-29: a refusal for the product's own file is not a JSON array index.

    Every other refusal in this feature names something the author can see -
    the delete 409 says `"Deletable" is live as v1 and cannot be deleted;
    unpublish it first, then delete it`. The import's schema refusal said
    `nodes.3.skill_id: Field required`: an array index, for a node the canvas
    calls Skill, about a field the author never typed. The same server writes
    `the file is not JSON (Expecting value at line 1 column 1)` two branches
    away, so the product already knows how to write these sentences.

    Fixed at the SERVER rather than in `builderApi.ts`'s `readErrorDetail`,
    where the row locates it, because the client passes a `detail` string
    through unmodified BY DESIGN - that is what makes the server's good
    sentences reach the operator at all - and a client-side rewriter would have
    to re-derive which node an index means from a file it does not hold. The
    payload is right here.
    """

    def refuse(self, mutate) -> str:
        _, envelope = self.exported_by_ada()
        mutate(envelope["document"])
        response = self.import_as(ADA_TOKEN, envelope)
        self.assertEqual(response.status_code, 422, response.text)
        detail = response.json()["detail"]
        self.assertIsInstance(detail, str)
        return detail

    def test_the_node_is_named_the_way_the_canvas_names_it(self) -> None:
        def break_the_output(document):
            node = next(n for n in document["nodes"] if n["kind"] == "output")
            node["label"] = "Final report"
            node["config"] = {}

        detail = self.refuse(break_the_output)
        self.assertIn('"Final report"', detail)
        self.assertIn("output node", detail)
        self.assertIn("body_key", detail)
        self.assertIn("Field required", detail)

    def test_the_dotted_location_is_kept_for_whoever_reads_a_bug_report(
        self,
    ) -> None:
        """Naming the node must not cost the only thing a developer can act on."""

        def break_the_output(document):
            node = next(n for n in document["nodes"] if n["kind"] == "output")
            node["config"] = {}

        detail = self.refuse(break_the_output)
        self.assertRegex(detail, r"\(nodes\.\d+\.body_key\)")

    def test_an_unlabelled_node_is_counted_rather_than_indexed_from_zero(self) -> None:
        def break_the_output(document):
            node = next(n for n in document["nodes"] if n["kind"] == "output")
            node["label"] = "   "
            node["config"] = {}

        detail = self.refuse(break_the_output)
        self.assertIn("output node", detail)
        # "node 3 of 4", never "nodes.2" as the subject.
        self.assertRegex(detail, r"output node \d+ of \d+")
        self.assertFalse(detail.startswith("nodes."), detail)

    def test_the_naming_echoes_the_label_and_nothing_else_of_the_payload(self) -> None:
        """The naming must not become a hole in the no-reflection rule.

        `_first_schema_error` never quoted the offending INPUT and still does
        not; the one thing it now quotes is the author's own label, bounded.

        A validator's own message is a separate matter and is unchanged: the
        `body_key` refusal names the key it is refusing, deliberately, because
        "unknown result body key 'x'" is the sentence that tells an author
        which key to change. That is a validator quoting a name it recognised
        as wrong, not the error handler reflecting a body.
        """

        def smuggle(document):
            node = next(n for n in document["nodes"] if n["kind"] == "output")
            node["label"] = "Final report"
            # A list, so the refusal is pydantic's own type message rather than
            # the custom validator's, which would name the key on purpose.
            node["config"] = {"body_key": ["sk-live-do-not-echo"]}

        detail = self.refuse(smuggle)
        self.assertIn("Input should be a valid string", detail)
        self.assertIn('"Final report"', detail)
        self.assertNotIn("sk-live-do-not-echo", detail)

    def test_a_label_longer_than_the_sentence_allows_is_cut(self) -> None:
        def shout(document):
            node = next(n for n in document["nodes"] if n["kind"] == "output")
            node["label"] = "L" * 80
            node["config"] = {}

        detail = self.refuse(shout)
        self.assertNotIn("L" * 60, detail)
        self.assertIn("L" * 40, detail)

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
