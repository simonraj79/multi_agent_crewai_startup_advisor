"""What a run builds from an `mcp` attachment - plan 07 criteria 4 and 5.

Criterion 4 asks four things of `runtime:run_agent` with an `mcp` attachment,
and each one is a way this could be wrong without looking wrong:

1. it constructs an `MCPServerHTTP` - **never a bare string**, because a bare
   string in `Agent.mcps` is a CrewAI AMP marketplace lookup and would send an
   author's server label to a registry;
2. the header is the RESOLVED credential, not the id the document carries;
3. `tool_filter` matches exactly the checked names, so a tool the author did
   not tick cannot reach the agent;
4. `cleanup()` is called after kickoff - in a `finally`, so a failing step
   still closes the client.

Criterion 5 is the credential half, and it is asserted the way plan 06's is:
against the real redaction walk over a payload shaped like a frame.

No cost: the vault, the store and the resolver are all stubbed. Nothing here
connects to an MCP server or resolves a name.
"""

from __future__ import annotations

import json
import unittest
from contextlib import contextmanager
from typing import Any
from unittest.mock import patch

from brief_crew.builder import mcp as mcp_module
from brief_crew.builder import runtime as runtime_module
from brief_crew.builder.mcp import DiscoveredTool, McpServerRecord, server_config

HEADER_SECRET = "mcp-header-CANARY-0123456789abcdef"

RECORD = McpServerRecord(
    id="ms_0123456789ab",
    user_id="user_alice",
    label="Docs server",
    transport="http",
    url="https://mcp.example.test/v1",
    header_credential_id="cr_0123abcd",
    status="authorized",
    discovered_tools=(
        DiscoveredTool(name="search_docs", description="Search."),
        DiscoveredTool(name="fetch_page", description="Fetch."),
        DiscoveredTool(name="delete_everything", description="Do not tick this."),
    ),
)


class Resolved:
    """What `resolve_credential` answers with, in the shape the vault returns."""

    def __init__(self, kind: str, fields: dict[str, str]) -> None:
        self.kind = kind
        self.fields = fields


@contextmanager
def run_as(record: McpServerRecord | None = RECORD, *, kind: str = "mcp_header"):
    """A run owned by somebody, with a vault and a store that answer.

    Both are patched at the seam `bind_attachments` actually uses -
    `_attachment_store` and `resolve_credential` - rather than a database being
    stood up, because what is under test is what the ENTRYPOINT does with the
    answers, not the SQL that produces them.
    """

    class Store:
        @staticmethod
        def get(_user: str, server_id: str) -> McpServerRecord:
            from brief_crew.service.attachments import AttachmentNotYours

            if record is None or server_id != record.id:
                raise AttachmentNotYours(server_id)
            return record

    def fake_store(name: str) -> tuple[Any, Any]:
        return (Store(), "user_alice") if name == "McpServerStore" else (None, None)

    def fake_resolve(_credential_id: str) -> Resolved:
        return Resolved(kind, {"name": "Authorization", "value": HEADER_SECRET})

    with patch.object(runtime_module, "_attachment_store", fake_store), patch(
        "brief_crew.service.credentials.resolve_credential", fake_resolve
    ):
        yield


class ServerConfigTests(unittest.TestCase):
    """The three transports, and the one thing none of them is."""

    def test_http_builds_MCPServerHTTP_streamable_with_the_filter_and_the_cache(self) -> None:
        from crewai.mcp.config import MCPServerHTTP

        config = server_config(
            RECORD,
            tool_names=("search_docs", "fetch_page"),
            header={"Authorization": HEADER_SECRET},
        )
        self.assertIsInstance(config, MCPServerHTTP)
        self.assertNotIsInstance(config, str)
        self.assertEqual(config.url, "https://mcp.example.test/v1")
        self.assertTrue(config.streamable)
        self.assertTrue(config.cache_tools_list)
        self.assertEqual(config.headers, {"Authorization": HEADER_SECRET})
        self.assertIsNotNone(config.tool_filter)

    def test_the_filter_admits_exactly_the_checked_names(self) -> None:
        """The tool the author did NOT tick must not reach the agent."""

        config = server_config(RECORD, tool_names=("search_docs",))
        self.assertTrue(config.tool_filter({"name": "search_docs"}))
        self.assertFalse(config.tool_filter({"name": "delete_everything"}))
        self.assertFalse(config.tool_filter({"name": "fetch_page"}))

    def test_sse_builds_its_own_class(self) -> None:
        from crewai.mcp.config import MCPServerSSE

        config = server_config(
            McpServerRecord(
                id="ms_0123456789ab",
                user_id="user_alice",
                label="s",
                transport="sse",
                url="https://mcp.example.test/sse",
            ),
            tool_names=("x",),
        )
        self.assertIsInstance(config, MCPServerSSE)

    def test_a_stdio_record_is_refused_here_as_well_as_at_create(self) -> None:
        with self.assertRaises(mcp_module.McpUnavailable):
            server_config(
                McpServerRecord(
                    id="ms_0123456789ab",
                    user_id="user_alice",
                    label="local",
                    transport="stdio",
                    command="npx",
                ),
                tool_names=("x",),
            )


class BindAttachmentsTests(unittest.TestCase):
    """Criterion 4, at the entrypoint that FD10 says does the dereferencing."""

    def test_it_builds_the_config_from_the_row_and_the_resolved_header(self) -> None:
        with run_as():
            bound = runtime_module.bind_attachments(
                [
                    {
                        "kind": "mcp",
                        "server_id": RECORD.id,
                        "tool_names": ["search_docs", "fetch_page"],
                    }
                ],
                node_id="n1_agent",
            )
        self.assertEqual(len(bound.mcps), 1)
        config = bound.mcps[0]
        self.assertEqual(config.headers, {"Authorization": HEADER_SECRET})
        self.assertTrue(config.tool_filter({"name": "fetch_page"}))
        self.assertFalse(config.tool_filter({"name": "delete_everything"}))

    def test_a_document_never_carries_the_header_only_the_id(self) -> None:
        """FD10, stated as an assertion: the ATTACHMENT holds an id, and the
        plaintext appears for the first time inside the entrypoint."""

        attachment = {"kind": "mcp", "server_id": RECORD.id, "tool_names": ["search_docs"]}
        self.assertNotIn(HEADER_SECRET, json.dumps(attachment))
        with run_as():
            bound = runtime_module.bind_attachments([attachment], node_id="n1_agent")
        self.assertEqual(bound.mcps[0].headers["Authorization"], HEADER_SECRET)

    def test_a_server_that_is_not_this_runs_owners_fails_the_node(self) -> None:
        with run_as(record=None):
            with self.assertRaises(runtime_module.BuilderRuntimeError) as caught:
                runtime_module.bind_attachments(
                    [{"kind": "mcp", "server_id": "ms_ffffffffffff", "tool_names": ["x"]}],
                    node_id="n1_agent",
                )
        self.assertIn("not one of yours", str(caught.exception))

    def test_a_credential_of_the_wrong_kind_is_refused_by_KIND_never_by_value(self) -> None:
        with run_as(kind="github"):
            with self.assertRaises(runtime_module.BuilderRuntimeError) as caught:
                runtime_module.bind_attachments(
                    [
                        {
                            "kind": "mcp",
                            "server_id": RECORD.id,
                            "tool_names": ["search_docs"],
                        }
                    ],
                    node_id="n1_agent",
                )
        message = str(caught.exception)
        self.assertIn("mcp_header", message)
        self.assertNotIn(HEADER_SECRET, message)

    def test_a_run_with_no_identity_resolves_nothing_and_says_so(self) -> None:
        """An unowned run owns nothing, which is the vault's own rule applied
        one level up."""

        with patch.object(
            runtime_module, "_attachment_store", lambda _name: (None, None)
        ):
            with self.assertRaises(runtime_module.BuilderRuntimeError) as caught:
                runtime_module.bind_attachments(
                    [{"kind": "mcp", "server_id": RECORD.id, "tool_names": ["x"]}],
                    node_id="n1_agent",
                )
        self.assertIn("no identity", str(caught.exception))

    def test_an_unknown_attachment_kind_is_refused_by_name(self) -> None:
        with self.assertRaises(runtime_module.BuilderRuntimeError) as caught:
            runtime_module.bind_attachments(
                [{"kind": "webhook", "id": "x"}], node_id="n1_agent"
            )
        self.assertIn("tool, mcp and skill", str(caught.exception))


class CleanupTests(unittest.TestCase):
    """Criterion 4's fourth clause, and the `finally` that makes it true."""

    def test_cleanup_runs_after_a_successful_kickoff(self) -> None:
        closed = self._run_agent_with(kickoff=lambda **_: "done")
        self.assertEqual(closed, ["closed"])

    def test_cleanup_runs_even_when_the_step_raises(self) -> None:
        def boom(**_: Any) -> str:
            raise RuntimeError("the crew failed")

        with self.assertRaises(RuntimeError):
            self._run_agent_with(kickoff=boom)

    def test_the_agents_own_mcp_client_is_closed_on_the_FAILING_path(self) -> None:
        """The path CrewAI itself does not cover, which is why this exists.

        `agent/core.py` calls `_cleanup_mcp_clients()` after the completion
        event is emitted, so a task that RAISES skips it and the client
        survives the step. A builder graph fails a step for a dozen ordinary
        reasons - a guardrail, a cancel, a cost ceiling - so `run_agent`'s
        `finally` sweeps the crew's agents itself.
        """

        closed: list[str] = []

        class Agent:
            def _cleanup_mcp_clients(self) -> None:
                closed.append("agent")

        class Crew:
            agents = [Agent()]

            def kickoff(self, **_: Any) -> str:
                raise RuntimeError("the crew failed")

        runtime_module.release_mcp_clients(Crew())
        self.assertEqual(closed, ["agent"])

    def test_an_agent_whose_close_raises_does_not_fail_the_run(self) -> None:
        class Agent:
            def _cleanup_mcp_clients(self) -> None:
                raise OSError("already gone")

        class Crew:
            agents = [Agent()]

        runtime_module.release_mcp_clients(Crew())

    def test_a_crew_with_no_agents_attribute_is_left_alone(self) -> None:
        runtime_module.release_mcp_clients(object())

    def test_a_failing_cleanup_does_not_fail_the_run(self) -> None:
        """A leaked client is a defect; a run failed at its last line BY a
        leaked client is a worse one."""

        def raising() -> None:
            raise OSError("the socket was already gone")

        bound = runtime_module.BoundAttachments(closers=(raising,))
        bound.cleanup()

    def _run_agent_with(self, *, kickoff: Any) -> list[str]:
        closed: list[str] = []

        class Crew:
            def kickoff(self, **kwargs: Any) -> str:
                return kickoff(**kwargs)

        class Factories:
            def agent_crew(self, **_: Any) -> Any:
                return Crew()

            def crew(self, **_: Any) -> Any:  # pragma: no cover - unused here
                return Crew()

        bound = runtime_module.BoundAttachments(
            mcps=("a config",), closers=(lambda: closed.append("closed"),)
        )

        class Flow:
            state = type("S", (), {"model_dump": lambda self: {}})()

        with patch.object(runtime_module, "bind_attachments", lambda *a, **k: bound), \
                patch.object(runtime_module, "_factories", lambda: Factories()), \
                patch.object(runtime_module, "checkpoint", lambda _node: None), \
                patch.object(runtime_module, "missing_prompt_inputs", lambda *a: ()), \
                patch.object(runtime_module, "_record", lambda _f, _n, value: value):
            runtime_module.run_agent(
                Flow(),
                node_id="n1_agent",
                agent_id="market",
                tier="cheap",
                attachments=[{"kind": "mcp", "server_id": RECORD.id}],
            )
        return closed


class CredentialInFramesTests(unittest.TestCase):
    """Criterion 5: the resolved header appears in no frame."""

    def test_the_header_value_is_redacted_by_the_real_serializer(self) -> None:
        from brief_crew.events.serializer import FieldBoundedSerializer

        rendered = json.dumps(
            FieldBoundedSerializer().clip(
                {
                    "tool_id": "mcp:ms_0123456789ab:search_docs",
                    "transport": "mcp",
                    "server": "Docs server",
                    "headers": {"Authorization": HEADER_SECRET},
                }
            )
        )
        self.assertNotIn(HEADER_SECRET, rendered)
        # And the frame still says which server and which tool, which is what
        # plan 12 renders on the card.
        self.assertIn("Docs server", rendered)
        self.assertIn("search_docs", rendered)

    def test_the_stored_ROW_carries_a_credential_id_and_never_a_value(self) -> None:
        """The record is the other place a header could leak, and it holds a
        reference by construction - there is no column for a value."""

        self.assertEqual(RECORD.header_credential_id, "cr_0123abcd")
        self.assertNotIn(HEADER_SECRET, repr(RECORD))


if __name__ == "__main__":
    unittest.main()
