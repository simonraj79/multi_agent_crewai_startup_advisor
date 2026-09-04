"""A resolved credential reaches the tool and nothing else - plan 06 criterion 3.

The criterion asks that a tool frame captured during a run contain no substring
of the credential. That is asserted here at the two places it can actually be
decided, because a frame is only ever as safe as the two of them:

1. **The redaction walk.** `events/redaction.py::is_secret_key` is what the
   frame serializer and the persistence walk both ask, and this file proves it
   answers True for every field name a tool constructor here is handed -
   `api_key`, `gh_token`, `db_uri`, `headers`, `token`, `dsn`. Plan 06 D4 asks
   for those to be ADDED to `_SECRET_KEYS`; they were already there, three by
   name and the rest through the suffix rule, so the repair is a test rather
   than an edit and this file is that test.

2. **The serializer, end to end.** A frame is built with the real
   `events/serializer.py` over a payload carrying a plaintext key under each of
   those names, and the rendered frame is searched for the key.

Both halves are needed. A redaction list that is right about names proves
nothing if the walk does not consult it, and a serializer that redacts one
frame proves nothing about the name a later tool uses.

No cost: this builds frames in memory. No network, no model, no vault.
"""

from __future__ import annotations

import importlib.util
import io
import json
import unittest
import zipfile
from typing import Any

from brief_crew.builder.runtime import DefaultCrewFactories
from brief_crew.events.redaction import REDACTED, is_secret_key
from brief_crew.service.builder_runner import SyntheticCrewFactories
from tests.builder.test_compiler import (
    attach_edge,
    authored_agent_node,
    input_node,
    output_node,
)
from tests.builder.test_document import document, edge, node as builder_node
from tests.service.identities import AuthenticatedTwoUserCase

FASTAPI_AVAILABLE = importlib.util.find_spec("fastapi") is not None
IDEA = "a scheduling assistant for clinics"

#: Distinctive enough that a substring search cannot pass by luck. The
#: single-character key an earlier draft used answered "leaked" for every tool,
#: because "x" appears in the word "text".
SECRET = "sk-or-v1-LEAK-CANARY-0123456789abcdef"

#: Every constructor keyword a factory in `builder/tools.py` hands a plaintext
#: to, plus the two field names the classes hold them under. Read off the
#: factories rather than invented: `api_key=` on the Firecrawl classes and
#: Tavily and Exa, `gh_token`/`token` on GitHub, `db_uri` on NL2SQL, `headers`
#: on URLRead, and the two environment names `_env_scoped` writes.
CREDENTIAL_KEYS = (
    "api_key",
    "apiKey",
    "gh_token",
    "token",
    "db_uri",
    "dsn",
    "headers",
    "Authorization",
    "SERPER_API_KEY",
    "BRAVE_API_KEY",
    "FIRECRAWL_API_KEY",
    "GITHUB_TOKEN",
)


class RedactionListTests(unittest.TestCase):
    """D4's request, checked rather than performed: they are already covered."""

    def test_every_credential_carrying_key_a_factory_uses_is_secret(self) -> None:
        for key in CREDENTIAL_KEYS:
            with self.subTest(key=key):
                self.assertTrue(
                    is_secret_key(key),
                    f"{key!r} carries a plaintext credential in builder/tools.py and "
                    "the redaction walk does not treat it as secret",
                )

    def test_a_key_that_merely_NAMES_a_credential_is_not_redacted(self) -> None:
        """The other half, and the one a wider list would break.

        `credential_id` is an opaque reference the canvas has to be able to
        render, and `body_key` is the structural name `STRUCTURAL_KEY_NAMES`
        exists for. A redaction rule that swallowed either would hide the
        document from its own author.
        """

        self.assertFalse(is_secret_key("body_key"))
        self.assertFalse(is_secret_key("tool_id"))


class SerializedFrameTests(unittest.TestCase):
    """The walk, end to end, over a payload shaped like a real tool frame."""

    def _serialized(self, payload: dict) -> str:
        """Through the REAL serializer's own `clip`, not a stand-in.

        `FieldBoundedSerializer.clip` is what every frame in this service goes
        through on the way to the ring, the socket, `/frames` and the NDJSON
        export. A test that re-implemented the redaction would be asserting
        about its own copy.
        """

        from brief_crew.events.serializer import FieldBoundedSerializer

        return json.dumps(FieldBoundedSerializer().clip(payload))

    def test_no_credential_bearing_key_survives_into_a_tool_frame(self) -> None:
        payload = {
            "tool_id": "firecrawl_search",
            "status": "ok",
            "query": "a market",
            **{key: SECRET for key in CREDENTIAL_KEYS},
        }
        rendered = self._serialized(payload)
        self.assertNotIn(SECRET, rendered)
        self.assertIn(REDACTED, rendered)
        # And the frame is still USEFUL: what plan 12 renders survives.
        self.assertIn("firecrawl_search", rendered)
        self.assertIn("a market", rendered)

    def test_a_credential_nested_inside_a_tool_result_is_redacted_too(self) -> None:
        """A custom tool echoes the request it made, so the header travels one
        level down rather than at the top."""

        payload = {
            "tool_id": "ut_0123456789ab",
            "results": [
                {
                    "url": "https://api.example.test/x",
                    "headers": {"Authorization": SECRET},
                }
            ],
        }
        self.assertNotIn(SECRET, self._serialized(payload))

    def test_a_dsn_inside_free_TEXT_is_stripped_on_the_way_to_a_ROW(self) -> None:
        """The password a key name cannot protect, and where the two walks differ.

        `postgres_query` is handed a DSN, and a DSN carries its own password
        inside a string. `persistence._redact_text` strips it on the way to a
        row - asserted here - and the serializer's `clip`, which is what reaches
        the RING and the live socket, does NOT. That asymmetry is pre-existing
        and outside plan 06's surfaces; it is a follow-up in the report rather
        than a fix here, and this test records exactly which half holds so the
        next reader does not have to find out by leaking one.
        """

        from brief_crew.service.persistence import _redact_text
        from brief_crew.events.serializer import FieldBoundedSerializer

        dsn = "postgresql://user:hunter2@db.example.test/app"
        self.assertNotIn("hunter2", _redact_text(dsn))
        # The other half, stated rather than hidden.
        self.assertIn("hunter2", FieldBoundedSerializer().clip({"note": dsn})["note"])

    def test_the_KEY_a_dsn_arrives_under_is_redacted_by_both_walks(self) -> None:
        """Which is why the gap above is narrow: a DSN reaches a frame under
        `db_uri` or `dsn`, and both are secret names."""

        rendered = self._serialized(
            {"db_uri": "postgresql://user:hunter2@db.example.test/app"}
        )
        self.assertNotIn("hunter2", rendered)




# --------------------------------------------------------------------------
# The half plan 06 recorded as missing: a REAL run, with a REAL Firecrawl tool
# built from a REAL vault credential, and a REAL tool frame.
# --------------------------------------------------------------------------
#
# Plan 06's Status recorded criterion 3 as `partial` for one stated reason: the
# compiler did not emit `tool` attachments into a definition, so no builder run
# could carry one and the criterion's own sentence - "a tool frame captured
# during a synthetic run with a Firecrawl credential attached" - named a run
# that could not exist. Plan 09 landed that fold (C5,
# `test_compiler.py::AttachmentFoldTests`), so the run exists now and this is it.
#
# Three things have to hold together, and each is useless without the others:
#
# 1. **The control.** The tool really was constructed and really is holding the
#    plaintext. Without this the sweep proves nothing - a run that never
#    resolved a credential trivially leaks none.
# 2. **The sweep.** Every frame the run produced, plus the NDJSON and ZIP
#    exports and the durable rows, searched for the canary.
# 3. **The tool frame itself.** A synthetic run calls no model, so CrewAI
#    raises no `ToolUsageStartedEvent` and the run's own frames contain no TOOL
#    frame at all - which would make the criterion's noun vacuous. So the three
#    real CrewAI tool-usage events are pushed through the real
#    `StreamSinkAdapter` into a real `FrameBuffer`, carrying the constructed
#    tool's OWN `model_dump()`, which is where its `api_key` actually lives.


class ToolBuildingFactories(SyntheticCrewFactories):
    """Builds the REAL agent - and so the real tool - then kicks off free.

    Constructing a `FirecrawlSearchTool` calls no network: it stores the key on
    the instance and dials nothing until `_run`. So this is the only shape in
    which a $0.00 run really goes through `bind_attachments`, really asks the
    vault, and really ends up with a plaintext key on an object the event
    serializer could reach.
    """

    def __init__(self) -> None:
        super().__init__(failures=None)
        self.tools: list[Any] = []

    def authored_agent_crew(self, *, node_id: str, spec: Any) -> Any:
        agent = DefaultCrewFactories()._authored_agent(spec, node_id=node_id)
        self.tools.extend(agent.tools or [])
        return super().authored_agent_crew(node_id=node_id, spec=spec)


def firecrawl_graph(credential_id: str) -> Any:
    """An authored agent with one Firecrawl tool attached, and nothing else."""

    return document(
        [
            input_node(),
            authored_agent_node("draft"),
            builder_node(
                "search",
                "tool",
                {
                    "tool_id": "firecrawl_search",
                    "params": {"limit": 3},
                    "credential_id": credential_id,
                },
            ),
            output_node("report", source="${state.out__draft}"),
        ],
        [
            edge("e1", "idea", "draft"),
            edge("e2", "draft", "report"),
            attach_edge("a1", "search", "draft"),
        ],
    )


@unittest.skipUnless(FASTAPI_AVAILABLE, "fastapi is not installed")
class FirecrawlRunTests(AuthenticatedTwoUserCase):
    """One published graph, one Firecrawl key, one run, and every surface."""

    def setUp(self) -> None:
        super().setUp()
        self.registry = self.app.state.run_registry
        self.credential = self.create_credential(
            self.as_alice(),
            kind="firecrawl",
            label="My Firecrawl key",
            fields={"api_key": SECRET},
        )["id"]
        _, self.workflow_id = self.publish(
            firecrawl_graph(self.credential), self.as_alice()
        )
        self.factories = ToolBuildingFactories()
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

    def _built_tool(self) -> Any:
        self.assertEqual(len(self.factories.tools), 1, "the run built no tool at all")
        return self.factories.tools[0]

    def test_the_run_really_did_build_a_firecrawl_tool_holding_the_key(self) -> None:
        """The control, and it is the load-bearing half of this file.

        `bind_attachments` dereferences the author's `credential_id` against the
        run's own user, so this is also the proof that a TOOL credential -
        rather than the agent's LLM key, which `test_credentials_runtime.py`
        already covers - travels the vault path at all.
        """

        tool = self._built_tool()
        self.assertEqual(type(tool).__name__, "FirecrawlSearchTool")
        self.assertEqual(tool.api_key, SECRET)

    def test_no_frame_of_the_run_carries_the_key(self) -> None:
        page = self.client.get(
            f"/api/runs/{self.run_id}/frames", headers=self.as_alice()
        )
        self.assertEqual(page.status_code, 200, page.text)
        self.assertNotIn(SECRET, page.text)
        # Anti-vacuity: a run that emitted nothing would pass the line above.
        self.assertGreater(len(page.json()["frames"]), 0)

    def test_no_export_of_the_run_carries_the_key(self) -> None:
        ndjson = self.client.get(
            f"/api/runs/{self.run_id}/logs?format=ndjson", headers=self.as_alice()
        )
        self.assertEqual(ndjson.status_code, 200, ndjson.text)
        self.assertNotIn(SECRET, ndjson.text)

        archive = self.client.get(
            f"/api/runs/{self.run_id}/logs?format=zip", headers=self.as_alice()
        )
        self.assertEqual(archive.status_code, 200)
        with zipfile.ZipFile(io.BytesIO(archive.content)) as bundle:
            self.assertTrue(bundle.namelist())
            for name in bundle.namelist():
                with self.subTest(entry=name):
                    self.assertNotIn(SECRET.encode(), bundle.read(name))

    def test_no_durable_row_of_the_run_carries_the_key(self) -> None:
        """The run snapshot and the per-node state rows the runtime checkpoints."""

        snapshot = self.client.get(f"/api/runs/{self.run_id}", headers=self.as_alice())
        self.assertEqual(snapshot.status_code, 200, snapshot.text)
        self.assertNotIn(SECRET, snapshot.text)

    def test_the_TOOL_frame_is_clean_over_the_built_tools_own_dump(self) -> None:
        """The criterion's own noun, and why it needs its own test.

        A synthetic run calls no model, so CrewAI raises no tool-usage event and
        the run's own frames contain no TOOL frame - which would make "no
        credential substring in a tool frame" true of a set with nothing in it.
        These are the three real CrewAI event classes, pushed through the real
        `StreamSinkAdapter` into a real `FrameBuffer` - the same path `/frames`,
        the socket and both exports read - carrying the constructed tool's own
        `model_dump()`.

        It is the worst case rather than the likely one, deliberately: `api_key`
        is a pydantic FIELD on `FirecrawlSearchTool`, so anything that ever put
        the tool's own dump into an event would put the plaintext in it, and the
        redaction walk is the only thing between that and the socket.
        """

        from datetime import datetime, timedelta, timezone

        from crewai.events.types.flow_events import MethodExecutionStartedEvent
        from crewai.events.types.tool_usage_events import (
            ToolUsageErrorEvent,
            ToolUsageFinishedEvent,
            ToolUsageStartedEvent,
        )

        from brief_crew.events import FrameBuffer, NodeRegistry, StreamSinkAdapter

        dump = self._built_tool().model_dump()
        self.assertEqual(
            dump.get("api_key"), SECRET, "the fixture stopped carrying the key"
        )

        stamp = datetime(2026, 9, 4, 12, 0, tzinfo=timezone.utc)
        buffer = FrameBuffer(capacity=64)
        adapter = StreamSinkAdapter(
            run_id="tool-credential-run",
            buffer=buffer,
            registry=NodeRegistry(flow_method_nodes={"draft": "draft"}),
        )
        adapter(
            None,
            MethodExecutionStartedEvent(
                flow_name="BuilderFlow",
                method_name="draft",
                state={},
                params=None,
                timestamp=stamp,
            ),
        )
        adapter(
            None,
            ToolUsageStartedEvent(
                tool_name="firecrawl_search", tool_args=dump, timestamp=stamp
            ),
        )
        adapter(
            None,
            ToolUsageFinishedEvent(
                tool_name="firecrawl_search",
                tool_args=dump,
                output=dump,
                started_at=stamp,
                finished_at=stamp + timedelta(milliseconds=5),
                timestamp=stamp,
            ),
        )
        adapter(
            None,
            ToolUsageErrorEvent(
                tool_name="firecrawl_search",
                tool_args=dump,
                error=dump,
                timestamp=stamp,
            ),
        )

        frames = [frame for frame in buffer.replay() if frame.kind.value == "tool"]
        self.assertEqual(len(frames), 3, "the three tool events drafted no tool frame")
        rendered = json.dumps([frame.to_dict() for frame in frames], default=str)
        self.assertNotIn(SECRET, rendered)
        self.assertIn(REDACTED, rendered)
        # Still a USEFUL frame: what plan 12 renders survives the redaction.
        self.assertIn("firecrawl_search", rendered)
        self.assertEqual(buffer.stats().emit_errors, 0)


if __name__ == "__main__":
    unittest.main()
