"""`/api/builder/skills` - plan 08 criteria 1, 2, 3, 6 and 8.

Five criteria in one file because they are five questions about one set of
routes, and splitting them would mean five copies of the same fixture.

**Criterion 1 has a clause this test corrects rather than satisfies.** It asks
that the built-ins list "for an anonymous caller in `SYNTHETIC` mode and for a
signed-in user". Both are asserted - but on an app with `VALIDATOR_REQUIRE_AUTH`
the anonymous half is a **401**, because `Depends(current_user)` refuses before
the handler runs and this route gets no exception to the service's own rule.
`AnonymousSkillTests` builds the app the criterion actually describes - synthetic,
no auth server - and asserts the built-ins are listed there.

**Criterion 1 also says `init_db` seeds them.** It does not, and does not need
to: the four are committed FILES, `load_builtins` parses them at read time, and
their ids are derived from their names rather than minted - so they are the same
ids on every deployment with no row to go stale. A seeding pass would add a
migration whose only job is to duplicate four files into a table nothing reads.
Recorded as a departure in the plan's Status.

No cost: a synthetic app over in-memory SQLite, and a temporary SKILLS_ROOT.
"""

from __future__ import annotations

import pathlib
import tempfile
import unittest
from typing import Any
from unittest.mock import patch

from brief_crew import config as project_config
from brief_crew.builder.skills import BUILTIN_SKILL_IDS, SKILL_UNKNOWN
from tests.builder.test_document import agent_node, chain, document, input_node, node, output_node
from tests.service.identities import AuthenticatedTwoUserCase, wire

try:  # pragma: no cover
    from fastapi.testclient import TestClient  # noqa: F401

    FASTAPI_AVAILABLE = True
except Exception:  # pragma: no cover
    FASTAPI_AVAILABLE = False

SKILLS = "/api/builder/skills"
VALIDATE = "/api/builder/validate"

BODY = """---
name: my-method
description: A method of mine. Use when testing.
metadata:
  version: "1"
---

# My method

Do the thing carefully.
"""


def graph_with_skill(skill_id: str):
    return document(
        [
            input_node(),
            agent_node("writer"),
            node("knowledge", "skill", {"skill_id": skill_id}),
            output_node(),
        ],
        [
            *chain("idea", "writer", "report"),
            {
                "id": "a1",
                "source": "knowledge",
                "source_port": "out",
                "target": "writer",
                "target_port": "attach",
            },
        ],
    )


class TemporaryRoot:
    """A private SKILLS_ROOT per test, so a pack never leaks between them."""

    def install(self, case: unittest.TestCase) -> pathlib.Path:
        root = pathlib.Path(tempfile.mkdtemp(prefix="skills-api-"))
        # The four built-ins are committed under the REAL root and are read
        # from there; only a user's own packs go to the temporary one. So the
        # committed directory is copied rather than the root repointed, which
        # keeps the built-in half of every assertion honest.
        import shutil

        from brief_crew.builder.skills import builtin_root

        shutil.copytree(builtin_root(), root / "builtin")
        patcher = patch.object(project_config, "SKILLS_ROOT", str(root))
        patcher.start()
        case.addCleanup(patcher.stop)
        return root


@unittest.skipUnless(FASTAPI_AVAILABLE, "FastAPI service extra is not installed")
class SkillRouteTests(AuthenticatedTwoUserCase):
    def setUp(self) -> None:
        super().setUp()
        self.root = TemporaryRoot().install(self)

    def create(self, headers: dict[str, str], body: str = BODY) -> dict[str, Any]:
        response = self.client.post(SKILLS, json={"body": body}, headers=headers)
        self.assertEqual(response.status_code, 201, response.text)
        return response.json()

    # ---------------------------------------------------------- criterion 1
    def test_the_four_builtins_are_listed_for_a_signed_in_user(self) -> None:
        listed = self.client.get(SKILLS, headers=self.as_alice()).json()["skills"]
        builtins = [row for row in listed if row["owner"] == "builtin"]
        self.assertEqual(
            [row["name"] for row in builtins], list(project_config.BUILTIN_SKILL_NAMES)
        )
        self.assertEqual({row["id"] for row in builtins}, set(BUILTIN_SKILL_IDS))

    def test_a_list_carries_no_body_because_thirty_packs_is_two_megabytes(self) -> None:
        listed = self.client.get(SKILLS, headers=self.as_alice()).json()["skills"]
        for row in listed:
            self.assertNotIn("body", row)
        detail = self.client.get(
            f"{SKILLS}/{BUILTIN_SKILL_IDS[0]}", headers=self.as_alice()
        ).json()
        self.assertIn("body", detail)
        self.assertIn("# Market research method", detail["body"])

    # ---------------------------------------------------------- criterion 2
    def test_a_bad_frontmatter_name_is_422_with_the_parsers_own_sentence(self) -> None:
        response = self.client.post(
            SKILLS,
            json={"body": BODY.replace("name: my-method", 'name: "Bad Name"')},
            headers=self.as_alice(),
        )
        self.assertEqual(response.status_code, 422, response.text)
        self.assertIn("pattern", response.json()["detail"])

    def test_a_valid_pack_is_201_and_the_row_matches_the_frontmatter(self) -> None:
        created = self.create(self.as_alice())
        self.assertRegex(created["id"], project_config.SKILL_ID_PATTERN)
        self.assertEqual(created["name"], "my-method")
        self.assertEqual(created["description"], "A method of mine. Use when testing.")
        self.assertEqual(created["version"], 1)
        self.assertEqual(created["owner"], "me")

    def test_a_put_bumps_the_version_in_the_file_that_holds_it(self) -> None:
        created = self.create(self.as_alice())
        updated = self.client.put(
            f"{SKILLS}/{created['id']}",
            json={"body": BODY.replace("carefully", "twice as carefully")},
            headers=self.as_alice(),
        )
        self.assertEqual(updated.status_code, 200, updated.text)
        self.assertEqual(updated.json()["version"], 2)
        self.assertIn("twice as carefully", updated.json()["body"])

    def test_a_builtin_cannot_be_edited_or_deleted_and_the_refusal_is_404(self) -> None:
        """404 rather than 403, matching every other route here: "you may not
        edit this" and "there is no such row of yours" are one answer."""

        path = f"{SKILLS}/{BUILTIN_SKILL_IDS[0]}"
        self.assertEqual(
            self.client.put(path, json={"body": BODY}, headers=self.as_alice()).status_code,
            404,
        )
        self.assertEqual(self.client.delete(path, headers=self.as_alice()).status_code, 404)
        # And it is still readable, by everybody.
        self.assertEqual(self.client.get(path, headers=self.as_bob()).status_code, 200)

    def test_two_people_may_each_have_a_pack_of_the_same_name(self) -> None:
        self.create(self.as_alice())
        self.create(self.as_bob())

    def test_a_second_pack_of_one_name_is_409(self) -> None:
        self.create(self.as_alice())
        response = self.client.post(SKILLS, json={"body": BODY}, headers=self.as_alice())
        self.assertEqual(response.status_code, 409, response.text)

    def test_the_per_user_ceiling_is_a_422_naming_it(self) -> None:
        with patch.object(project_config, "MAX_SKILLS_PER_USER", 1):
            self.create(self.as_alice())
            response = self.client.post(
                SKILLS,
                json={"body": BODY.replace("my-method", "another-method")},
                headers=self.as_alice(),
            )
        self.assertEqual(response.status_code, 422, response.text)
        self.assertIn("ceiling is 1", response.json()["detail"])

    # ---------------------------------------------------------- criterion 6
    def test_another_users_pack_is_404_and_invisible_in_the_list(self) -> None:
        created = self.create(self.as_alice())
        self.assertEqual(
            self.client.get(f"{SKILLS}/{created['id']}", headers=self.as_bob()).status_code,
            404,
        )
        theirs = self.client.get(SKILLS, headers=self.as_bob()).json()["skills"]
        self.assertNotIn(created["id"], [row["id"] for row in theirs])

    def test_a_document_naming_another_users_pack_reports_skill_unknown(self) -> None:
        created = self.create(self.as_alice())
        doc = graph_with_skill(created["id"])
        self.assertNotIn(SKILL_UNKNOWN, self.codes(self.as_alice(), doc))
        self.assertIn(SKILL_UNKNOWN, self.codes(self.as_bob(), doc))

    def test_a_builtin_validates_clean_for_EVERYONE(self) -> None:
        doc = graph_with_skill(BUILTIN_SKILL_IDS[1])
        self.assertNotIn(SKILL_UNKNOWN, self.codes(self.as_alice(), doc))
        self.assertNotIn(SKILL_UNKNOWN, self.codes(self.as_bob(), doc))

    # ---------------------------------------------------------- criterion 8
    def test_delete_orphans_document(self) -> None:
        created = self.create(self.as_alice())
        doc = graph_with_skill(created["id"])
        self.assertNotIn(SKILL_UNKNOWN, self.codes(self.as_alice(), doc))

        self.assertEqual(
            self.client.delete(f"{SKILLS}/{created['id']}", headers=self.as_alice()).status_code,
            204,
        )
        problems = self.problems(self.as_alice(), doc)
        orphaned = [row for row in problems if row["code"] == SKILL_UNKNOWN]
        self.assertEqual(len(orphaned), 1)
        # Anchored to the SKILL node, which is what the problems dock selects.
        self.assertEqual(orphaned[0]["node_id"], "knowledge")

    # ------------------------------------------------------------- helpers
    def problems(self, headers: dict[str, str], doc: Any) -> list[dict[str, Any]]:
        response = self.client.post(
            VALIDATE, json={"document": wire(doc)}, headers=headers
        )
        self.assertEqual(response.status_code, 200, response.text)
        return response.json()["problems"]

    def codes(self, headers: dict[str, str], doc: Any) -> list[str]:
        return [row["code"] for row in self.problems(headers, doc)]


@unittest.skipUnless(FASTAPI_AVAILABLE, "FastAPI service extra is not installed")
class AnonymousSkillTests(unittest.TestCase):
    """Criterion 1's anonymous half, on the app the criterion describes.

    `SYNTHETIC=1` with no auth server: `current_user` answers None and the
    built-ins are listed. That is the shape a bare local checkout and the E2E
    harness both run, and it is the only shape in which "anonymous" is a state
    this service has.
    """

    def setUp(self) -> None:
        from fastapi.testclient import TestClient

        from brief_crew.service.app import create_app

        self.root = TemporaryRoot().install(self)
        for item in (
            patch.object(project_config, "AUTH_BASE_URL", ""),
            patch.object(project_config, "VALIDATOR_REQUIRE_AUTH", False),
        ):
            item.start()
            self.addCleanup(item.stop)
        self.client = TestClient(
            create_app(synthetic=True, database_url="sqlite+pysqlite:///:memory:")
        )
        self.addCleanup(self.client.close)

    def test_the_builtins_are_listed_with_no_identity_at_all(self) -> None:
        response = self.client.get(SKILLS)
        self.assertEqual(response.status_code, 200, response.text)
        names = [row["name"] for row in response.json()["skills"]]
        self.assertEqual(names, list(project_config.BUILTIN_SKILL_NAMES))

    def test_writing_one_still_needs_somebody_to_own_it(self) -> None:
        """`user_skills.user_id` is NOT NULL (15 C10), so an ownerless pack is
        not a row this schema can hold."""

        response = self.client.post(SKILLS, json={"body": BODY})
        self.assertEqual(response.status_code, 401, response.text)


if __name__ == "__main__":
    unittest.main()
