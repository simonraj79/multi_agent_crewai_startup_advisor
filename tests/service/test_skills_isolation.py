"""One person's packs are invisible to another - plan 08 criterion 6.

The isolation matrix, stated as a matrix: two people, four kinds of reference,
and the answer asserted for both callers rather than for one. That shape is what
catches the two failures a one-sided test passes over - a list that filters
while the validator does not (the author is refused at publish instead of on the
canvas) and a validator that refuses every `sk_` id (which passes an isolation
test by refusing everybody).

A **built-in** is the row that must be visible to everyone, and it is the reason
this cannot simply be "reject anything you do not own": four packs belong to the
repository, have no `user_id`, and validate clean for every caller including an
anonymous one.

Rubric 14. No cost: a synthetic app over in-memory SQLite.
"""

from __future__ import annotations

import pathlib
import shutil
import tempfile
import unittest
from typing import Any
from unittest.mock import patch

from brief_crew import config as project_config
from brief_crew.builder.skills import BUILTIN_SKILL_IDS, SKILL_UNKNOWN, builtin_root
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


@unittest.skipUnless(FASTAPI_AVAILABLE, "FastAPI service extra is not installed")
class SkillIsolationTests(AuthenticatedTwoUserCase):
    def setUp(self) -> None:
        super().setUp()
        root = pathlib.Path(tempfile.mkdtemp(prefix="skills-iso-"))
        shutil.copytree(builtin_root(), root / "builtin")
        patcher = patch.object(project_config, "SKILLS_ROOT", str(root))
        patcher.start()
        self.addCleanup(patcher.stop)

        self.alice_pack = self._create(self.as_alice(), BODY)
        self.bob_pack = self._create(
            self.as_bob(), BODY.replace("my-method", "their-method")
        )

    def _create(self, headers: dict[str, str], body: str) -> str:
        response = self.client.post(SKILLS, json={"body": body}, headers=headers)
        self.assertEqual(response.status_code, 201, response.text)
        return response.json()["id"]

    def _codes(self, headers: dict[str, str], skill_id: str) -> list[str]:
        response = self.client.post(
            VALIDATE,
            json={"document": wire(graph_with_skill(skill_id))},
            headers=headers,
        )
        self.assertEqual(response.status_code, 200, response.text)
        return [row["code"] for row in response.json()["problems"]]

    def test_the_matrix(self) -> None:
        """Four references, two callers, eight answers - all asserted."""

        builtin = BUILTIN_SKILL_IDS[0]
        cases: list[tuple[str, str, dict[str, str], bool]] = [
            ("her own", self.alice_pack, self.as_alice(), False),
            ("his own", self.bob_pack, self.as_bob(), False),
            ("his, as her", self.bob_pack, self.as_alice(), True),
            ("hers, as him", self.alice_pack, self.as_bob(), True),
            ("a built-in, as her", builtin, self.as_alice(), False),
            ("a built-in, as him", builtin, self.as_bob(), False),
            ("no such pack, as her", "sk_ffffffffffff", self.as_alice(), True),
            ("no such pack, as him", "sk_ffffffffffff", self.as_bob(), True),
        ]
        for label, skill_id, headers, expect_unknown in cases:
            with self.subTest(case=label):
                codes = self._codes(headers, skill_id)
                if expect_unknown:
                    self.assertIn(SKILL_UNKNOWN, codes)
                else:
                    self.assertNotIn(SKILL_UNKNOWN, codes)

    def test_each_list_carries_the_four_builtins_and_only_that_callers_own(self) -> None:
        for headers, mine, theirs in (
            (self.as_alice(), self.alice_pack, self.bob_pack),
            (self.as_bob(), self.bob_pack, self.alice_pack),
        ):
            with self.subTest(caller=headers["Authorization"]):
                rows = self.client.get(SKILLS, headers=headers).json()["skills"]
                ids = [row["id"] for row in rows]
                self.assertIn(mine, ids)
                self.assertNotIn(theirs, ids)
                for builtin in BUILTIN_SKILL_IDS:
                    self.assertIn(builtin, ids)

    def test_a_deleted_pack_reads_the_same_as_a_strangers(self) -> None:
        """One code for absent, deleted and foreign, deliberately.

        A canvas that told them apart would be an oracle for other people's
        ids, and the repair is the same in all three cases: pick a pack you
        have.
        """

        self.assertNotIn(SKILL_UNKNOWN, self._codes(self.as_alice(), self.alice_pack))
        self.assertEqual(
            self.client.delete(f"{SKILLS}/{self.alice_pack}", headers=self.as_alice()).status_code,
            204,
        )
        self.assertIn(SKILL_UNKNOWN, self._codes(self.as_alice(), self.alice_pack))

    def test_the_problem_anchors_to_the_skill_node(self) -> None:
        response = self.client.post(
            VALIDATE,
            json={"document": wire(graph_with_skill(self.bob_pack))},
            headers=self.as_alice(),
        )
        rows = [
            row for row in response.json()["problems"] if row["code"] == SKILL_UNKNOWN
        ]
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["node_id"], "knowledge")
        self.assertEqual(rows[0]["severity"], "error")


if __name__ == "__main__":
    unittest.main()
