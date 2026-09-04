"""Discovery, the transport policy, and the two flags - plan 07 criteria 1, 2, 7.

`discover` takes an injected resolver, so the whole of discovery is exercisable
without a server: the default builds a real `MCPToolResolver` and a test hands
in one that answers with two tools, or raises, or never returns. That seam is
the same one `service/credentials.py` opened for its probes, and for the same
reason - a test that needed a live MCP server would be a test nobody runs.

**Criterion 2 is the important one and it has two halves.** A stdio command not
on `MCP_ALLOWED_COMMANDS` is refused, and - the half a naive implementation
misses - the DEFAULT allow-list is empty, so every stdio server is refused by
default. On top of that sits `MCP_STDIO_ENABLED`, which is off, so the
allow-list alone opens nothing either. Both are asserted, in both directions.

No cost: nothing here connects to anything.
"""

from __future__ import annotations

import unittest
from datetime import datetime, timedelta, timezone
from typing import Any
from unittest.mock import patch

from brief_crew import config as project_config
from brief_crew.builder.mcp import (
    DiscoveredTool,
    McpServerRecord,
    discover,
    mask_url,
    transport_refusal,
)


class FakeTool:
    def __init__(self, name: str, description: str, schema: dict[str, Any] | None = None):
        self.name = name
        self.description = description
        self.args_schema = _Schema(schema or {}) if schema is not None else None


class _Schema:
    def __init__(self, schema: dict[str, Any]):
        self._schema = schema

    def model_json_schema(self) -> dict[str, Any]:
        return self._schema


def http_server(**overrides: Any) -> McpServerRecord:
    return McpServerRecord(
        id="ms_0123456789ab",
        user_id="user_alice",
        label="Docs server",
        transport="http",
        url="https://mcp.example.test/v1",
        **overrides,
    )


def resolver(*tools: Any):
    def resolve(_config: Any):
        return list(tools)

    return resolve


#: The DNS seam. `mcp.example.test` does not resolve, and without this every
#: test in this file would be asserting about `getaddrinfo` rather than about
#: the transport policy - which is how the first draft of this file failed.
PUBLIC_DNS = lambda _host: ["93.184.216.34"]  # noqa: E731


class DiscoveryTests(unittest.TestCase):
    def test_it_returns_the_tool_list_with_schemas_and_stores_the_sanitised_form(self) -> None:
        result = discover(
            http_server(),
            resolve=PUBLIC_DNS, resolver=resolver(
                FakeTool(
                    "search docs",
                    "Search the documentation.",
                    {"type": "object", "properties": {"q": {"type": "string"}}},
                ),
                FakeTool("fetch", "Fetch one page."),
            ),
        )
        self.assertEqual(result.status, "authorized")
        self.assertEqual([tool.name for tool in result.tools], ["search_docs", "fetch"])
        self.assertEqual(
            result.tools[0].input_schema["properties"]["q"]["type"], "string"
        )
        self.assertIsNotNone(result.discovered_at)

    def test_a_malformed_schema_degrades_to_an_empty_one_rather_than_raising(self) -> None:
        """A third party's schema is not this service's to trust."""

        class Broken:
            name = "x"
            description = "y"

            class args_schema:  # noqa: N801 - mimicking the attribute shape
                @staticmethod
                def model_json_schema() -> dict[str, Any]:
                    raise TypeError("not a model")

        result = discover(http_server(), resolve=PUBLIC_DNS, resolver=resolver(Broken()))
        self.assertEqual(result.status, "authorized")
        self.assertEqual(result.tools[0].input_schema, {})

    def test_more_tools_than_the_ceiling_are_truncated_and_the_row_says_so(self) -> None:
        many = [FakeTool(f"t{index}", "d") for index in range(70)]
        result = discover(http_server(), resolve=PUBLIC_DNS, resolver=resolver(*many))
        self.assertEqual(len(result.tools), project_config.MCP_MAX_TOOLS_PER_SERVER)
        self.assertIn("70", str(result.error))

    def test_a_failure_is_a_RESULT_with_one_sentence_and_never_an_exception(self) -> None:
        def boom(_config: Any):
            raise ConnectionError("Connection refused\nand a stack trace nobody wants")

        result = discover(http_server(), resolve=PUBLIC_DNS, resolver=boom)
        self.assertEqual(result.status, "error")
        self.assertTrue(str(result.error).startswith("could not connect: "))
        self.assertNotIn("\n", str(result.error))
        self.assertEqual(result.tools, ())

    def test_timeout(self) -> None:
        """Criterion 7: a discovery that times out answers `status: error`.

        The timeout is the resolver's - CrewAI's own client has one - and what
        this asserts is that whatever it raises becomes a result rather than a
        504. The route stores that result, so the ROW's status is `error` too,
        which is the half the panel reads.
        """

        def slow(_config: Any):
            raise TimeoutError("timed out after 20s")

        result = discover(http_server(), resolve=PUBLIC_DNS, resolver=slow)
        self.assertEqual(result.status, "error")
        self.assertIn("timed out", str(result.error))
        self.assertEqual(project_config.MCP_DISCOVERY_TIMEOUT_SECONDS, 20)

    def test_the_header_credential_reaches_the_config_and_not_the_result(self) -> None:
        seen: list[Any] = []

        def capture(config: Any):
            seen.append(config)
            return []

        discover(
            http_server(),
            header={"Authorization": "Bearer sekrit"},
            resolve=PUBLIC_DNS, resolver=capture,
        )
        self.assertEqual(seen[0].headers, {"Authorization": "Bearer sekrit"})


class StaleWindowTests(unittest.TestCase):
    """Criterion 1's second half: a stored list is served from the row."""

    def test_a_row_with_no_discovery_is_stale(self) -> None:
        self.assertTrue(http_server().stale())

    def test_a_fresh_row_is_not_stale_and_an_old_one_is(self) -> None:
        now = datetime.now(timezone.utc)
        fresh = http_server(discovered_at=now - timedelta(minutes=5))
        old = http_server(
            discovered_at=now
            - timedelta(seconds=project_config.MCP_DISCOVERY_STALE_SECONDS + 60)
        )
        self.assertFalse(fresh.stale(now=now))
        self.assertTrue(old.stale(now=now))

    def test_the_stored_tools_are_readable_without_a_server(self) -> None:
        """The inspector never needs a live server to render, which is the whole
        reason the discovery result is stored on the row."""

        record = http_server(
            discovered_tools=(DiscoveredTool(name="search_docs", description="d"),),
            discovered_at=datetime.now(timezone.utc),
            status="authorized",
        )
        self.assertIsNotNone(record.tool("search_docs"))
        self.assertIsNone(record.tool("nope"))


class TransportPolicyTests(unittest.TestCase):
    """Criterion 2, and the two flags that stack."""

    def test_the_default_refuses_every_stdio_server_because_the_FLAG_is_off(self) -> None:
        self.assertFalse(project_config.MCP_STDIO_ENABLED)
        refusal = transport_refusal(transport="stdio", command="npx", args=["-y", "x"])
        self.assertIsNotNone(refusal)
        self.assertIn("remote MCP servers only", str(refusal))

    def test_lifting_the_flag_alone_still_refuses_because_the_LIST_is_empty(self) -> None:
        """The two are independent, and this is the assertion that says so.

        `MCP_ALLOWED_COMMANDS` defaults to `()`, so a deployment that turned the
        flag on and set nothing else is still remote-only. `render.yaml` sets
        neither.
        """

        self.assertEqual(project_config.MCP_ALLOWED_COMMANDS, ())
        with patch.object(project_config, "MCP_STDIO_ENABLED", True):
            refusal = transport_refusal(transport="stdio", command="npx")
            self.assertIsNotNone(refusal)
            self.assertIn("allow-list", str(refusal))
            self.assertIn("permits nothing", str(refusal))

    def test_both_lifted_admits_the_named_command_and_nothing_else(self) -> None:
        with patch.object(project_config, "MCP_STDIO_ENABLED", True), patch.object(
            project_config, "MCP_ALLOWED_COMMANDS", ("npx", "uvx")
        ):
            self.assertIsNone(transport_refusal(transport="stdio", command="npx"))
            self.assertIsNotNone(transport_refusal(transport="stdio", command="bash"))

    def test_shell_metacharacters_in_an_argument_are_refused(self) -> None:
        with patch.object(project_config, "MCP_STDIO_ENABLED", True), patch.object(
            project_config, "MCP_ALLOWED_COMMANDS", ("npx",)
        ):
            refusal = transport_refusal(
                transport="stdio", command="npx", args=["-y", "pkg; rm -rf /"]
            )
            self.assertIsNotNone(refusal)
            self.assertIn("metacharacters", str(refusal))

    def test_an_env_key_off_the_list_is_refused_rather_than_dropped(self) -> None:
        """Refused so the author is TOLD. Dropping it silently would produce a
        server that starts and cannot authenticate, for no visible reason."""

        with patch.object(project_config, "MCP_STDIO_ENABLED", True), patch.object(
            project_config, "MCP_ALLOWED_COMMANDS", ("npx",)
        ):
            refusal = transport_refusal(
                transport="stdio", command="npx", env_keys=("SECRET_TOKEN",)
            )
            self.assertIsNotNone(refusal)
            self.assertIn("SECRET_TOKEN", str(refusal))

    def test_a_remote_server_must_be_https_and_must_not_be_on_this_network(self) -> None:
        self.assertIsNotNone(
            transport_refusal(
                transport="http",
                url="http://mcp.example.test/v1",
                resolve=lambda _h: ["93.184.216.34"],
            )
        )
        self.assertIsNotNone(
            transport_refusal(
                transport="http",
                url="https://mcp.example.test/v1",
                resolve=lambda _h: ["169.254.169.254"],
            )
        )
        self.assertIsNone(
            transport_refusal(
                transport="http",
                url="https://mcp.example.test/v1",
                resolve=lambda _h: ["93.184.216.34"],
            )
        )

    def test_loopback_is_admitted_only_behind_the_explicit_local_flag(self) -> None:
        """Which is what the E2E loopback fixture runs on, and nothing else."""

        self.assertFalse(project_config.MCP_ALLOW_INSECURE_LOCAL)
        self.assertIsNotNone(
            transport_refusal(transport="http", url="http://127.0.0.1:8123/mcp")
        )
        with patch.object(project_config, "MCP_ALLOW_INSECURE_LOCAL", True):
            self.assertIsNone(
                transport_refusal(transport="http", url="http://127.0.0.1:8123/mcp")
            )

    def test_a_stdio_record_is_refused_at_DISCOVERY_too_and_never_spawned(self) -> None:
        """Criterion 2's "never spawned": the resolver is not even called."""

        called: list[Any] = []
        result = discover(
            McpServerRecord(
                id="ms_0123456789ab",
                user_id="user_alice",
                label="local",
                transport="stdio",
                command="bash",
            ),
            resolver=lambda config: called.append(config) or [],
        )
        self.assertEqual(result.status, "error")
        self.assertEqual(called, [])


class MaskingTests(unittest.TestCase):
    def test_a_path_is_masked_because_it_can_carry_a_token(self) -> None:
        self.assertEqual(
            mask_url("https://mcp.example.test/v1/abc123secret"),
            "https://mcp.example.test/************",
        )

    def test_a_bare_origin_is_shown_whole(self) -> None:
        self.assertEqual(mask_url("https://mcp.example.test"), "https://mcp.example.test")
        self.assertEqual(mask_url("https://mcp.example.test/"), "https://mcp.example.test")

    def test_no_url_masks_to_nothing(self) -> None:
        self.assertIsNone(mask_url(None))


if __name__ == "__main__":
    unittest.main()
