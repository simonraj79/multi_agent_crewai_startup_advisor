"""`GET /api/builder/workflows/{id}/export` - plan 15 D1 at the HTTP boundary.

`tests/builder/test_export.py` proves the strip over a raw dict, which is the
property that matters. This module proves the ROUTE: the D1 envelope comes back
as a download with the right headers, built from the parsed document's own
dump, visible on exactly the terms every other route uses, and importable by
the route across the hall.

Three refusals are worth their own line: another user's document is a 404 and
not a 403; a version that does not exist is a 404; and a version this service
can no longer READ is a 422 naming the document - never a file that will not
import anywhere, because the export is built from the parsed row rather than
the stored bytes.
"""

from __future__ import annotations

import json
from typing import Any

from sqlalchemy import update

from brief_crew.builder.export import EXPORT_DROPPED_KEYS
from brief_crew.config import BUILDER_DOCUMENT_SCHEMA
from brief_crew.service.persistence import builder_document_versions
from tests.service.builder_auth import (
    ADA_TOKEN,
    GRACE_TOKEN,
    BuilderAuthCase,
    document_payload,
)

ENVELOPE_KEYS = ["export", "exported_at", "name", "source_version", "needs_credentials", "document"]


class ExportRouteCase(BuilderAuthCase):
    def exported(self, token: str, document_id: str, **params: Any) -> tuple[Any, dict[str, Any]]:
        response = self.export_as(token, document_id, **params)
        self.assertEqual(response.status_code, 200, response.text)
        return response, response.json()


class TheDownload(ExportRouteCase):
    def test_it_is_a_json_attachment_named_after_the_document(self) -> None:
        created = self.create_as(ADA_TOKEN)
        response, envelope = self.exported(ADA_TOKEN, created["id"])
        self.assertTrue(response.headers["content-type"].startswith("application/json"))
        self.assertEqual(
            response.headers["content-disposition"],
            'attachment; filename="Test graph.builder.json"; '
            "filename*=UTF-8''Test%20graph.builder.json",
        )
        # The stem the browser saves under is the envelope's own `name`; the
        # console derives one from the other and the two must agree.
        self.assertEqual(envelope["name"], "Test graph")

    def test_the_exact_name_travels_in_filename_star_even_when_not_header_safe(self) -> None:
        """RFC 6266: `filename=` is the ASCII fallback, `filename*` the truth."""

        created = self.create_as(ADA_TOKEN, document_payload(name="Idée: validée/2"))
        response, envelope = self.exported(ADA_TOKEN, created["id"])
        disposition = response.headers["content-disposition"]
        self.assertIn('filename="Ide valide 2.builder.json"', disposition)
        self.assertIn(
            "filename*=UTF-8''Id%C3%A9e%3A%20valid%C3%A9e%2F2.builder.json", disposition
        )
        self.assertEqual(envelope["name"], "Idée: validée/2")

    def test_the_body_is_the_d1_envelope_in_the_plan_s_order(self) -> None:
        created = self.create_as(ADA_TOKEN)
        response, envelope = self.exported(ADA_TOKEN, created["id"])
        self.assertEqual(list(json.loads(response.text)), ENVELOPE_KEYS)
        self.assertEqual(envelope["export"], BUILDER_DOCUMENT_SCHEMA)
        self.assertEqual(envelope["name"], "Test graph")
        self.assertEqual(envelope["source_version"], 1)
        self.assertEqual(envelope["needs_credentials"], [])
        self.assertTrue(envelope["exported_at"].endswith("+00:00"))

    def test_the_document_carries_no_id_version_budget_or_owner(self) -> None:
        """D1: the importer mints its own. The owner and the row id never leave."""

        created = self.create_as(ADA_TOKEN)
        response, envelope = self.exported(ADA_TOKEN, created["id"])
        for key in EXPORT_DROPPED_KEYS:
            with self.subTest(key=key):
                self.assertNotIn(key, envelope["document"])
        self.assertNotIn(created["id"], response.text)
        self.assertNotIn("user_ada", response.text)

    def test_the_graph_itself_is_what_was_stored(self) -> None:
        created = self.create_as(ADA_TOKEN)
        _, envelope = self.exported(ADA_TOKEN, created["id"])
        self.assertEqual(envelope["document"]["schema"], BUILDER_DOCUMENT_SCHEMA)
        self.assertEqual(envelope["document"]["nodes"], created["document"]["nodes"])
        self.assertEqual(envelope["document"]["edges"], created["document"]["edges"])
        self.assertEqual(envelope["document"]["input_field"], "idea")

    def test_version_exports_that_version_and_says_so(self) -> None:
        created = self.create_as(ADA_TOKEN)
        saved = self.save_as(
            ADA_TOKEN, created["id"], document_payload(name="Second"), expected_version=1
        )
        self.assertEqual(saved.status_code, 200, saved.text)

        _, head = self.exported(ADA_TOKEN, created["id"])
        _, first = self.exported(ADA_TOKEN, created["id"], version=1)
        self.assertEqual((head["name"], head["source_version"]), ("Second", 2))
        self.assertEqual((first["name"], first["source_version"]), ("Test graph", 1))

    def test_the_filename_is_safe_inside_the_header(self) -> None:
        """A name may hold a quote, a slash or a control character."""

        created = self.create_as(ADA_TOKEN, document_payload(name='a"b/c\\d:e'))
        response, _ = self.exported(ADA_TOKEN, created["id"])
        disposition = response.headers["content-disposition"]
        self.assertTrue(disposition.startswith('attachment; filename="a b c d e.builder.json"; '))
        self.assertIn("filename*=UTF-8''a%22b%2Fc%5Cd%3Ae.builder.json", disposition)
        # Nothing raw made it into the header: no bare quote, no control byte.
        parameters = disposition.split("; ")
        self.assertEqual(len(parameters), 3)
        self.assertNotIn("\r", disposition)
        self.assertNotIn("\n", disposition)

    def test_the_file_round_trips_through_import(self) -> None:
        """The two routes agree on the envelope, or neither is worth much."""

        created = self.create_as(ADA_TOKEN)
        _, envelope = self.exported(ADA_TOKEN, created["id"])
        imported = self.import_as(ADA_TOKEN, envelope)
        self.assertEqual(imported.status_code, 201, imported.text)
        body = imported.json()
        self.assertNotEqual(body["id"], created["id"])
        self.assertEqual(body["document"]["nodes"], created["document"]["nodes"])
        self.assertEqual(body["needs_credentials"], [])


class Refusals(ExportRouteCase):
    def test_another_user_s_document_is_a_404(self) -> None:
        created = self.create_as(ADA_TOKEN)
        response = self.export_as(GRACE_TOKEN, created["id"])
        self.assertEqual(response.status_code, 404, response.text)
        self.assertNotIn("Test graph", response.text)

    def test_an_anonymous_caller_is_refused(self) -> None:
        created = self.create_as(ADA_TOKEN)
        self.assertEqual(self.export_as(None, created["id"]).status_code, 401)

    def test_a_version_that_does_not_exist_is_a_404_naming_the_version(self) -> None:
        """D-15-8: the document is on the caller's screen; the 404 says which
        version is missing and which is newest, not that the document is."""

        created = self.create_as(ADA_TOKEN)
        refused = self.export_as(ADA_TOKEN, created["id"], version=4)
        self.assertEqual(refused.status_code, 404)
        detail = refused.json()["detail"]
        self.assertNotEqual(detail, "document not found")
        self.assertIn(created["id"], detail)
        self.assertIn("version 4", detail)
        self.assertIn("newest is v1", detail)

    def test_a_version_this_service_can_no_longer_read_is_a_422_naming_it(self) -> None:
        """Built from the parsed row, so an unreadable one is refused here
        rather than exported as a file nothing will import."""

        created = self.create_as(ADA_TOKEN)
        persistence = self.app.state.run_registry.persistence
        with persistence.begin() as connection:
            connection.execute(
                update(builder_document_versions)
                .where(builder_document_versions.c.document_id == created["id"])
                .values(document={"schema": "builder.flow/v0", "name": "old"})
            )
        response = self.export_as(ADA_TOKEN, created["id"])
        self.assertEqual(response.status_code, 422, response.text)
        self.assertIn(created["id"], response.json()["detail"])

    def test_an_unknown_document_is_a_404(self) -> None:
        self.assertEqual(self.export_as(ADA_TOKEN, "ug_00000000").status_code, 404)
