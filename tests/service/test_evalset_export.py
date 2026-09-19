"""Export rated runs: one streamed, redacted NDJSON file (plan 21, T3).

`rating=good` is the runs a person approved; `rating=any` is every run in the
window with the outcome a human left on it, to check a future change against.

It is also **the most privacy-sensitive artifact this repository produces**: an
idea, the model's answer and a human's edit in one file. R3 permits
`rating_note` and `result_summary` on four conditions, and all four are
asserted here rather than cited: every free-text field passes through the
existing redaction AND the exporter's credential scrub; the route is
admin-only (404 to anybody else); the first line is a HEADER saying the file
holds user-typed content - in a sentence, because redaction is key-name based
and does not find a credential pasted into an idea under an innocent name; and
the file is capped on BOTH axes.

**Both caps, because a row cap is a cap on the wrong axis.**
`EVALSET_MAX_RUNS` bounds how many rows there are and says nothing about how
big one is; `EVALSET_MAX_BYTES` bounds the bytes on the wire. Either one ends
the file in a `_truncated` line rather than a 500, which is the shape
`/api/runs/{id}/logs` already took: a partial file is worth more to whoever is
reading it than an error.
"""

from __future__ import annotations

from datetime import timedelta
from decimal import Decimal
import json
import unittest
from unittest.mock import patch

from brief_crew import config
from brief_crew.events import FrameData, FrameKind, FrameLevel, UIEventType
from tests.service.admin_fixtures import ALICE, NOW, AdminCase


WORKFLOW = "ug_evalset01"
PLANTED_KEY = "sk-or-v1-0123456789abcdef-NEVER-IN-AN-EXPORT"


class EvalsetCase(AdminCase):
    def setUp(self) -> None:
        super().setUp()
        self.seed_rated("good-1", rating="good", note="it cited every claim")
        self.seed_rated("good-2", rating="good", note=None)
        self.seed_rated("bad-1", rating="bad", note="the segment was wrong")
        self.seed_rated("unrated-1", rating=None, note=None)

    def seed_rated(self, run_id: str, *, rating: str | None, note: str | None) -> None:
        created = NOW - timedelta(hours=2)
        self.store.create_run(
            run_id=run_id,
            session_id="s",
            workflow_id=WORKFLOW,
            graph_version="v1",
            inputs={"idea": f"a scheduling assistant, key {PLANTED_KEY}"},
            user_id=ALICE.id,
            status="queued",
            created_at=created,
            document_version=4,
        )
        self.store.save_node_metrics(
            run_id,
            "n1",
            model=config.CHEAP_MODEL,
            cost_usd=Decimal("0.0610"),
            total_tokens=100,
            prompt_tokens=80,
            completion_tokens=20,
            call_count=1,
        )
        self.store.update_run_status(
            run_id,
            "completed",
            completed_at=created + timedelta(minutes=1),
            result={"markdown_body": "# The report\n\nEvery claim is cited." * 200},
        )
        if rating is not None:
            self.store.set_run_rating(
                run_id, rating=rating, note=note, rated_by=ALICE.id
            )
        self.store.append_frames(
            run_id,
            [
                FrameData(
                    seq=1,
                    run_id=run_id,
                    ts=created,
                    kind=FrameKind.VERDICT,
                    event_type=UIEventType.WORKFLOW_END,
                    level=FrameLevel.INFO,
                    node_id="n2",
                    message="a verdict",
                    details={"verdict": "VALIDATE", "confidence": 0.71},
                )
            ],
        )
        self.store.open_gate(
            run_id,
            "confirm",
            node_id="n3",
            request={"fields": {"segment": "SMBs", "note": "as proposed"}},
            opened_at=created,
        )
        self.store.answer_gate(
            run_id,
            "confirm",
            {"decision": "revise", "fields": {"segment": "clinics", "note": "as proposed"}},
            answered_at=created + timedelta(seconds=30),
        )

    def export(self, query: str = "") -> list[dict]:
        response = self.get(f"/export/evalset?workflow_id={WORKFLOW}{query}")
        self.assertEqual(response.status_code, 200, response.text)
        self.assertIn("application/x-ndjson", response.headers["content-type"])
        return [
            json.loads(line)
            for line in response.text.splitlines()
            if line.strip()
        ]


class StreamShapeTests(EvalsetCase):
    def test_every_line_parses_as_json(self) -> None:
        """The whole file, not a sample: one malformed line makes an NDJSON
        file useless to the tool that reads it."""

        lines = self.export("&rating=any")
        self.assertGreater(len(lines), 1)

    def test_the_first_line_is_the_header_sentence(self) -> None:
        header = self.export("&rating=any")[0]
        self.assertTrue(header["_header"])
        self.assertIn("USER-TYPED CONTENT", header["note"])
        # In WORDS, because redaction is key-name based and this is exactly
        # where a flag would imply a guarantee it cannot make.
        self.assertIn("api_key", header["note"])
        self.assertIn(WORKFLOW, header["workflow_id"])
        # Both caps are STATED on the header, so a reader of a short file
        # can tell which bound produced it without guessing.
        self.assertEqual(config.EVALSET_MAX_RUNS, header["max_runs"])
        self.assertEqual(config.EVALSET_MAX_BYTES, header["max_bytes"])

    def test_one_line_per_run(self) -> None:
        rows = self.export("&rating=any")[1:]
        self.assertEqual(4, len(rows))
        self.assertEqual(
            {"good-1", "good-2", "bad-1", "unrated-1"},
            {row["run_id"] for row in rows},
        )

    def test_a_row_carries_every_key_a_reader_needs(self) -> None:
        row = self.export("&rating=any")[1]
        for key in (
            "run_id",
            "workflow_id",
            "document_version",
            "graph_version",
            "created_at",
            "status",
            "mode",
            "cost_usd",
            "inputs",
            "outcome",
            "gates",
            "rating",
            "rating_note",
            "rated_at",
        ):
            with self.subTest(key=key):
                self.assertIn(key, row)

    def test_the_outcome_carries_the_verdict_and_a_clipped_report(self) -> None:
        row = next(
            item for item in self.export("&rating=any")[1:] if item["run_id"] == "good-1"
        )
        self.assertEqual("VALIDATE", row["outcome"]["verdict"])
        self.assertEqual(0.71, row["outcome"]["confidence"])
        self.assertLessEqual(
            len(row["outcome"]["result_summary"]), config.EVALSET_MAX_RESULT_CHARS
        )
        self.assertTrue(row["outcome"]["result_summary"])

    def test_the_gate_pairs_are_on_the_row(self) -> None:
        """The label that makes an eval set worth having: what the machine
        proposed, and what a person left there instead."""

        row = self.export("&rating=any")[1]
        gate = row["gates"][0]
        self.assertEqual("revise", gate["decision"])
        pairs = {pair["key"]: pair for pair in gate["pairs"]}
        self.assertTrue(pairs["segment"]["changed"])
        self.assertEqual("SMBs", pairs["segment"]["proposed"])
        self.assertEqual("clinics", pairs["segment"]["corrected"])
        self.assertFalse(pairs["note"]["changed"])

    def test_the_content_disposition_names_a_file(self) -> None:
        response = self.get(f"/export/evalset?workflow_id={WORKFLOW}")
        self.assertIn("attachment", response.headers["content-disposition"])
        self.assertIn(WORKFLOW, response.headers["content-disposition"])


class FilteringTests(EvalsetCase):
    def test_rating_good_returns_only_the_good_runs(self) -> None:
        rows = self.export("&rating=good")[1:]
        self.assertEqual({"good-1", "good-2"}, {row["run_id"] for row in rows})

    def test_rating_good_is_the_default(self) -> None:
        rows = self.export()[1:]
        self.assertEqual({"good-1", "good-2"}, {row["run_id"] for row in rows})

    def test_rating_bad_returns_only_the_bad_ones(self) -> None:
        rows = self.export("&rating=bad")[1:]
        self.assertEqual({"bad-1"}, {row["run_id"] for row in rows})

    def test_rating_any_includes_the_unrated(self) -> None:
        rows = self.export("&rating=any")[1:]
        self.assertIn("unrated-1", {row["run_id"] for row in rows})

    def test_an_unknown_rating_is_422(self) -> None:
        response = self.get(f"/export/evalset?workflow_id={WORKFLOW}&rating=fabulous")
        self.assertEqual(response.status_code, 422, response.text)

    def test_a_narrow_window_returns_the_header_and_nothing_else(self) -> None:
        later = (NOW + timedelta(hours=1)).isoformat().replace("+00:00", "Z")
        until = (NOW + timedelta(hours=2)).isoformat().replace("+00:00", "Z")
        lines = self.export(f"&rating=any&from={later}&to={until}")
        self.assertEqual(1, len(lines))
        self.assertTrue(lines[0]["_header"])


class TruncationTests(EvalsetCase):
    """Both caps, and neither is a 500 (R3).

    A partial file with a line saying which bound it hit and what to do
    about it is worth more to whoever is reading it than an error - and
    far more than a browser that gives up halfway through a response no
    admission check was bounding.
    """

    def test_a_run_capped_export_ends_in_a_sentinel_line(self) -> None:
        with patch.object(config, "EVALSET_MAX_RUNS", 2):
            lines = self.export("&rating=any")
        self.assertTrue(lines[-1]["_truncated"])
        self.assertIn("narrow the window", lines[-1]["reason"])
        self.assertEqual(2, len(lines) - 2)

    def test_an_untruncated_export_has_no_sentinel(self) -> None:
        lines = self.export("&rating=any")
        self.assertNotIn("_truncated", lines[-1])

    def test_a_byte_capped_export_ends_in_a_sentinel_line(self) -> None:
        """The cap the row count cannot express.

        Two thousand runs each carrying a 2,000-character summary, an
        inputs mapping and every gate pair is tens of megabytes on one
        response, assembled by a generator no admission check bounds.
        """

        with patch.object(config, "EVALSET_MAX_BYTES", 1500):
            lines = self.export("&rating=any")
        self.assertTrue(lines[-1]["_truncated"])
        self.assertIn("1500 bytes", lines[-1]["reason"])
        # Fewer rows than the four that exist, and more than none.
        self.assertLess(len(lines) - 2, 4)

    def test_the_header_survives_a_budget_smaller_than_itself(self) -> None:
        """A file whose first line is a truncation notice says nothing
        about what it is a truncation OF."""

        with patch.object(config, "EVALSET_MAX_BYTES", 1):
            lines = self.export("&rating=any")
        self.assertTrue(lines[0]["_header"])
        self.assertEqual(2, len(lines))
        self.assertTrue(lines[1]["_truncated"])

    def test_the_bytes_really_are_bounded(self) -> None:
        """The measurement, not the flag: a sentinel on an oversized file
        would be a label rather than a cap."""

        with patch.object(config, "EVALSET_MAX_BYTES", 2000):
            response = self.get(f"/export/evalset?workflow_id={WORKFLOW}&rating=any")
        self.assertEqual(response.status_code, 200, response.text)
        body = response.content
        trailer = len(json.dumps({"_truncated": True, "reason": ""})) + 200
        self.assertLess(len(body), 2000 + trailer)


class RedactionTests(EvalsetCase):
    """R3's conditions, asserted rather than cited."""

    def test_the_route_is_404_to_a_non_admin(self) -> None:
        response = self.client.get(
            f"/api/admin/export/evalset?workflow_id={WORKFLOW}",
            headers=self.as_alice(),
        )
        self.assertEqual(response.status_code, 404, response.text)

    def test_a_credential_shaped_string_in_an_idea_is_scrubbed(self) -> None:
        """The SHAPE rule, which is the half key-name redaction cannot do."""

        response = self.get(f"/export/evalset?workflow_id={WORKFLOW}&rating=any")
        self.assertNotIn(PLANTED_KEY, response.text)
        self.assertNotIn("sk-or-v1-0123456789abcdef", response.text)

    def test_a_field_named_like_a_credential_is_redacted(self) -> None:
        """The KEY-NAME rule, which is the half the shape rule cannot do."""

        self.store.create_run(
            run_id="secret-run",
            session_id="s",
            workflow_id=WORKFLOW,
            graph_version="v1",
            inputs={"idea": "an idea", "api_key": "a-value-with-no-telltale-shape"},
            user_id=ALICE.id,
            status="queued",
            created_at=NOW - timedelta(hours=1),
        )
        self.store.update_run_status("secret-run", "completed")
        self.store.set_run_rating(
            "secret-run", rating="good", note=None, rated_by=ALICE.id
        )
        response = self.get(f"/export/evalset?workflow_id={WORKFLOW}&rating=good")
        self.assertNotIn("a-value-with-no-telltale-shape", response.text)

    def test_the_idea_itself_does_survive(self) -> None:
        """The control: an export that dropped everything would pass the two
        tests above and be worth nothing."""

        response = self.get(f"/export/evalset?workflow_id={WORKFLOW}&rating=any")
        self.assertIn("a scheduling assistant", response.text)

    def test_the_rating_note_is_present_and_scrubbed(self) -> None:
        """R3 permits it, on the conditions above."""

        rows = self.export("&rating=good")[1:]
        notes = {row["run_id"]: row["rating_note"] for row in rows}
        self.assertEqual("it cited every claim", notes["good-1"])
        self.assertIsNone(notes["good-2"])


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
