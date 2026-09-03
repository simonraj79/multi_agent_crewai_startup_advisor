"""`POST /api/builder/workflows/{id}/duplicate` - plan 15 D3; criterion 3.

A duplicate is a new draft: 201 with `Location`, a server-minted `ug_` id,
version 1, status `draft`, name `"<name> copy"`, owned by the CALLER. It goes
through `parse` and `store.create` exactly as a fresh document does, so the
copy is re-priced rather than carrying the source's `budget`, and its id is the
server's rather than anything the source said.

Visibility is `_visible_to`'s: another user's document is the same 404 every
other route answers, because a 403 would confirm the document exists.
"""

from __future__ import annotations

from brief_crew.config import BUILDER_DOCUMENT_ID_PATTERN, BUILDER_MAX_NAME_CHARS
from brief_crew.service.builder_api import COPY_SUFFIX, copy_name
from tests.service.builder_auth import (
    ADA_TOKEN,
    GRACE_TOKEN,
    BuilderAuthCase,
    document_payload,
)


class DuplicateCase(BuilderAuthCase):
    def duplicate_as(self, token: str | None, document_id: str, **params):
        return self.client.post(
            f"/api/builder/workflows/{document_id}/duplicate",
            params=params or None,
            headers=self.auth(token) if token else {},
        )


class OwnDocument(DuplicateCase):
    def test_a_duplicate_is_a_fresh_draft_at_version_one(self) -> None:
        """Criterion 3: 201, version 1, `draft`."""

        source = self.create_as(ADA_TOKEN)
        response = self.duplicate_as(ADA_TOKEN, source["id"])
        self.assertEqual(response.status_code, 201, response.text)
        body = response.json()

        self.assertRegex(body["id"], BUILDER_DOCUMENT_ID_PATTERN)
        self.assertNotEqual(body["id"], source["id"])
        self.assertEqual(body["version"], 1)
        self.assertEqual(body["head_version"], 1)
        self.assertEqual(body["status"], "draft")
        self.assertFalse(body["published"])
        self.assertEqual(body["document"]["id"], body["id"])
        self.assertEqual(
            response.headers["Location"], f"/api/builder/workflows/{body['id']}"
        )

    def test_the_copy_is_named_after_its_source(self) -> None:
        source = self.create_as(ADA_TOKEN)
        body = self.duplicate_as(ADA_TOKEN, source["id"]).json()
        self.assertEqual(body["document"]["name"], f"{source['document']['name']} copy")

    def test_the_copy_belongs_to_the_caller_and_sits_beside_the_source(self) -> None:
        source = self.create_as(ADA_TOKEN)
        copy = self.duplicate_as(ADA_TOKEN, source["id"]).json()
        self.assertEqual(sorted(self.list_ids_as(ADA_TOKEN)), sorted([source["id"], copy["id"]]))
        self.assertEqual(self.list_ids_as(GRACE_TOKEN), [])

    def test_the_graph_is_copied_and_the_price_is_not(self) -> None:
        """`budget` is a price against the ceiling of the day it was measured."""

        source = self.create_as(ADA_TOKEN)
        copy = self.duplicate_as(ADA_TOKEN, source["id"]).json()
        self.assertEqual(copy["document"]["nodes"], source["document"]["nodes"])
        self.assertEqual(copy["document"]["edges"], source["document"]["edges"])
        self.assertIsNone(copy["document"].get("budget"))
        # The answer still prices it, freshly, the way a create does.
        self.assertIn("static_cost_usd", copy["budget"])

    def test_editing_the_copy_leaves_the_source_alone(self) -> None:
        source = self.create_as(ADA_TOKEN)
        copy = self.duplicate_as(ADA_TOKEN, source["id"]).json()
        edited = document_payload(name="Edited copy")
        saved = self.save_as(ADA_TOKEN, copy["id"], edited, expected_version=1)
        self.assertEqual(saved.status_code, 200, saved.text)
        self.assertEqual(saved.json()["version"], 2)
        original = self.get_as(ADA_TOKEN, source["id"]).json()
        self.assertEqual(original["head_version"], 1)
        self.assertEqual(original["document"]["name"], "Test graph")

    def test_version_picks_which_version_is_copied(self) -> None:
        source = self.create_as(ADA_TOKEN)
        saved = self.save_as(
            ADA_TOKEN, source["id"], document_payload(name="Second"), expected_version=1
        )
        self.assertEqual(saved.status_code, 200, saved.text)

        head_copy = self.duplicate_as(ADA_TOKEN, source["id"]).json()
        first_copy = self.duplicate_as(ADA_TOKEN, source["id"], version=1).json()
        self.assertEqual(head_copy["document"]["name"], "Second copy")
        self.assertEqual(first_copy["document"]["name"], "Test graph copy")
        # Either way the copy starts its own history at 1.
        self.assertEqual(first_copy["version"], 1)

    def test_a_version_that_does_not_exist_is_a_404_naming_the_version(self) -> None:
        """D-15-8: the caller can see the document, so the sentence names the
        version they asked for and the newest one - never "document not found"."""

        source = self.create_as(ADA_TOKEN)
        refused = self.duplicate_as(ADA_TOKEN, source["id"], version=9)
        self.assertEqual(refused.status_code, 404)
        detail = refused.json()["detail"]
        self.assertNotEqual(detail, "document not found")
        self.assertIn(source["id"], detail)
        self.assertIn("version 9", detail)
        self.assertIn("newest is v1", detail)
        self.assertEqual(len(self.list_ids_as(ADA_TOKEN)), 1)

    def test_a_name_at_the_bound_still_gets_its_suffix(self) -> None:
        """A 422 about a field the author did not type is the one thing this
        route must not produce."""

        long_name = "n" * BUILDER_MAX_NAME_CHARS
        source = self.create_as(ADA_TOKEN, document_payload(name=long_name))
        response = self.duplicate_as(ADA_TOKEN, source["id"])
        self.assertEqual(response.status_code, 201, response.text)
        name = response.json()["document"]["name"]
        self.assertEqual(len(name), BUILDER_MAX_NAME_CHARS)
        self.assertTrue(name.endswith(COPY_SUFFIX))

    def test_a_copy_of_a_copy_is_named_twice(self) -> None:
        source = self.create_as(ADA_TOKEN)
        first = self.duplicate_as(ADA_TOKEN, source["id"]).json()
        second = self.duplicate_as(ADA_TOKEN, first["id"]).json()
        self.assertEqual(second["document"]["name"], "Test graph copy copy")


class SomebodyElsesDocument(DuplicateCase):
    def test_another_user_s_document_answers_404_and_creates_nothing(self) -> None:
        """Criterion 3: 404, not 403 - a 403 confirms the document exists."""

        source = self.create_as(ADA_TOKEN)
        response = self.duplicate_as(GRACE_TOKEN, source["id"])
        self.assertEqual(response.status_code, 404, response.text)
        self.assertEqual(response.json()["detail"], "document not found")
        self.assertEqual(self.list_ids_as(GRACE_TOKEN), [])
        self.assertEqual(self.list_ids_as(ADA_TOKEN), [source["id"]])

    def test_an_anonymous_caller_is_refused(self) -> None:
        source = self.create_as(ADA_TOKEN)
        self.assertEqual(self.duplicate_as(None, source["id"]).status_code, 401)
        self.assertEqual(self.list_ids_as(ADA_TOKEN), [source["id"]])

    def test_an_unknown_document_is_a_404(self) -> None:
        self.assertEqual(self.duplicate_as(ADA_TOKEN, "ug_00000000").status_code, 404)

    def test_an_unowned_document_duplicates_into_the_caller_s_ownership(self) -> None:
        """The carve-out: a row with no owner is readable by anyone, and the
        copy belongs to whoever asked for it - the original stays unowned."""

        from tests.builder.test_compiler import straight_line

        unowned = self.store().create(straight_line())
        response = self.duplicate_as(GRACE_TOKEN, unowned.id)
        self.assertEqual(response.status_code, 201, response.text)
        copy_id = response.json()["id"]
        self.assertIn(copy_id, self.list_ids_as(GRACE_TOKEN))
        self.assertNotIn(copy_id, self.list_ids_as(ADA_TOKEN))
        # The original is still unowned: both can still open it.
        self.assertEqual(self.get_as(ADA_TOKEN, unowned.id).status_code, 200)
        self.assertEqual(self.get_as(GRACE_TOKEN, unowned.id).status_code, 200)


class CopyNameTests(DuplicateCase):
    def test_the_suffix_is_appended(self) -> None:
        self.assertEqual(copy_name("Idea validator"), "Idea validator copy")
        self.assertEqual(COPY_SUFFIX, " copy")

    def test_the_base_is_trimmed_so_the_suffix_survives(self) -> None:
        name = copy_name("x" * BUILDER_MAX_NAME_CHARS)
        self.assertEqual(len(name), BUILDER_MAX_NAME_CHARS)
        self.assertTrue(name.endswith(COPY_SUFFIX))

    def test_trimming_does_not_leave_a_trailing_space_before_the_suffix(self) -> None:
        room = BUILDER_MAX_NAME_CHARS - len(COPY_SUFFIX)
        name = copy_name("y" * (room - 1) + " " + "zzzzzz")
        self.assertEqual(name, "y" * (room - 1) + COPY_SUFFIX)
