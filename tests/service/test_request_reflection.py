"""No door reflects the request back on a refusal (round 3, D-15-21).

FastAPI's default `RequestValidationError` handler answers pydantic's whole
error list with the offending **`input` echoed back**, bounded only by the body
ceiling - 256 KiB on the builder prefix. A 200 KB string in the wrong field
came back as a 200 KB refusal.

This class has now been found on FOUR doors, one at a time: the import envelope
in round 2 (D-15-9, answered by hand-parsing the body in `_import_envelope`),
then create, save and validate in round 3 (D-15-21). The answer this time is
one app-wide handler (`app._install_validation_handler`), because a fifth
hand-written envelope would be the wrong answer to a question that is plainly
app-wide - and because the doors nobody has probed yet get it for free.

What is asserted here is a property, not a wording: for every door, a refusal's
body is SHORT and does not contain the marker the request carried. The marker
is a distinctive string so a substring search cannot pass by accident, and the
size bound is far below the request's own so a truncation could not satisfy it
either.

`/api/sessions/{id}/runs` is included deliberately: it is not a builder route
and nobody has ever probed it, which is the whole argument for a handler over a
fifth envelope.
"""

from __future__ import annotations

from typing import Any

from tests.service.builder_auth import ADA_TOKEN, BuilderAuthCase, document_payload

#: Distinctive enough that finding it in a body cannot be a coincidence.
MARKER = "ECHO-MARKER-DO-NOT-REFLECT"
#: 200 KB, the figure the critic's probe used. Under the builder prefix's
#: 256 KiB ceiling, so the request is accepted and REFUSED rather than 413'd -
#: which is the only way to measure what a refusal says.
BIG = MARKER + ("x" * 200_000)
#: A refusal is a sentence. Anything approaching the request's own size is a
#: reflection, whatever it contains.
MAX_REFUSAL_BYTES = 2_000


class ReflectionCase(BuilderAuthCase):
    def assertNoReflection(self, response: Any, *, where: str) -> None:
        body = response.content
        self.assertEqual(response.status_code, 422, f"{where}: {response.text[:200]}")
        self.assertNotIn(
            MARKER,
            response.text,
            f"{where} reflected the request back ({len(body)} bytes)",
        )
        self.assertLess(
            len(body),
            MAX_REFUSAL_BYTES,
            f"{where} answered {len(body)} bytes; a refusal is a sentence",
        )
        # And it is still usable: a `detail` string the console can render.
        detail = response.json().get("detail")
        self.assertIsInstance(detail, str, where)
        self.assertTrue(detail.strip(), where)


class CreateSaveValidateTests(ReflectionCase):
    """The three doors `BuilderDocumentRequest` stands behind."""

    def test_create_refuses_a_huge_wrong_typed_document_without_echoing_it(self) -> None:
        response = self.client.post(
            "/api/builder/workflows",
            json={"document": BIG},
            headers=self.auth(ADA_TOKEN),
        )
        self.assertNoReflection(response, where="create")

    def test_save_refuses_without_echoing(self) -> None:
        created = self.create_as(ADA_TOKEN)
        response = self.client.put(
            f"/api/builder/workflows/{created['id']}",
            json={"document": BIG, "expected_version": created["version"]},
            headers=self.auth(ADA_TOKEN),
        )
        self.assertNoReflection(response, where="save")

    def test_validate_refuses_without_echoing(self) -> None:
        response = self.client.post(
            "/api/builder/validate",
            json={"document": BIG},
            headers=self.auth(ADA_TOKEN),
        )
        self.assertNoReflection(response, where="validate")

    def test_an_extra_key_names_the_key_and_echoes_nothing(self) -> None:
        """`extra="forbid"` reports the client's own key, which is bounded too."""

        response = self.client.post(
            "/api/builder/workflows",
            json={"document": document_payload(), MARKER: BIG},
            headers=self.auth(ADA_TOKEN),
        )
        self.assertEqual(response.status_code, 422, response.text[:200])
        self.assertLess(len(response.content), MAX_REFUSAL_BYTES)
        # The location names the offending key, so the client can fix itself;
        # what it must never carry is the 200 KB VALUE behind it.
        detail = response.json()["detail"]
        self.assertNotIn(BIG[:400], detail)

    def test_a_bad_expected_version_names_the_field(self) -> None:
        created = self.create_as(ADA_TOKEN)
        response = self.client.put(
            f"/api/builder/workflows/{created['id']}",
            json={"document": document_payload(), "expected_version": MARKER},
            headers=self.auth(ADA_TOKEN),
        )
        self.assertNoReflection(response, where="save/expected_version")
        self.assertIn("expected_version", response.json()["detail"])


class EveryOtherDoorTests(ReflectionCase):
    """The handler is app-wide, so a door nobody probed is covered too."""

    def test_a_run_request_does_not_echo_its_body(self) -> None:
        """40 KB, not 200: this door is behind the 64 KiB GLOBAL body ceiling.

        `MAX_REQUEST_BODY_BYTES` is 64 KiB everywhere except the builder
        prefix, so `BIG` never reaches validation here - it is refused with a
        413 by the middleware, which is correct and measures nothing about
        reflection. `gates` is a `Literal`, so a long string in it is a
        genuine pydantic refusal with the whole value as its `input`.
        """

        payload = MARKER + ("y" * 40_000)
        response = self.client.post(
            "/api/sessions/s-reflection/runs",
            json={"workflow_id": "idea-validator", "inputs": {"idea": "x" * 20}, "gates": payload},
            headers=self.auth(ADA_TOKEN),
        )
        self.assertNoReflection(response, where="create_run")

    def test_the_location_drops_the_body_prefix_and_names_the_field(self) -> None:
        """`body.document` says nothing a client did not know; `document` does."""

        response = self.client.post(
            "/api/builder/workflows",
            json={"document": 7},
            headers=self.auth(ADA_TOKEN),
        )
        detail = response.json()["detail"]
        self.assertTrue(detail.startswith("document:"), detail)


class SentenceShapeTests(ReflectionCase):
    """The formatting rules, asserted on the function rather than through HTTP."""

    def detail(self, errors: list[dict[str, Any]]) -> str:
        from brief_crew.service.app import request_validation_detail

        return request_validation_detail(errors)

    def test_several_problems_are_named_up_to_a_cap(self) -> None:
        errors = [
            {"loc": ("body", f"field{index}"), "msg": f"problem {index}", "input": BIG}
            for index in range(6)
        ]
        detail = self.detail(errors)
        self.assertIn("field0: problem 0", detail)
        self.assertIn("field2: problem 2", detail)
        self.assertNotIn("field3", detail)
        self.assertNotIn(MARKER, detail)

    def test_an_empty_list_still_says_something(self) -> None:
        self.assertEqual(self.detail([]), "request failed validation")

    def test_a_long_message_and_location_are_both_bounded(self) -> None:
        detail = self.detail([{"loc": ("body", "a" * 500), "msg": "b" * 500}])
        self.assertLess(len(detail), 400)

    def test_a_location_that_is_only_body_still_names_something(self) -> None:
        """A whole-body failure has `loc: ("body",)` and must not read `": msg"`."""

        detail = self.detail([{"loc": ("body",), "msg": "Field required"}])
        self.assertEqual(detail, "body: Field required")
