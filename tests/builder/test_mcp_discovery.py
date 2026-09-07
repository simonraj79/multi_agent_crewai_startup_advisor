"""Discovery, the transport policy, and the two flags - plan 07 criteria 1, 2, 7.

`discover` takes an injected resolver, so the whole of discovery is exercisable
without a server: the default builds a real `MCPToolResolver` and a test hands
in one that answers with two tools, or raises, or never returns. That seam is
the same one `service/credentials.py` opened for its probes, and for the same
reason - a test that needed a live MCP server would be a test nobody runs.

**Criterion 2 is the important one and it has two halves.** A stdio command
line not on the allow-list is refused, and - the half a naive implementation
misses - the DEFAULT allow-list is empty, so every stdio server is refused by
default. On top of that sits `MCP_STDIO_ENABLED`, which is off, so the
allow-list alone opens nothing either. Both are asserted, in both directions.
Since audit M12 the allow-list is `MCP_ALLOWED_ARGV`, which names complete
command lines; `AuditM12ArgvAllowListTests` below is why.

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


class LongAddressNameTests(unittest.TestCase):
    """A stdio server's tools keep their own names under a long command line.

    CrewAI prefixes a discovered tool with the server's sanitised address, and a
    stdio address is the whole command line. Right-truncating that at the cap
    ate the tool's own name first: on the Ubuntu CI runner the fixture's two
    tools both sanitised to one `..._mult` stump (2026-09-05). The tail is what
    an author reads and what `tool_filter` matches on, so it is what survives.
    """

    def test_two_tools_under_one_long_address_stay_distinct(self) -> None:
        from brief_crew import config as project_config
        from brief_crew.builder.mcp import sanitise_name

        address = "/home/runner/work/" + "multi_agent_crewai_startup_advisor/" * 4 + ".venv/bin/python"
        names = [sanitise_name(f"{address} fixture.py_{tool}") for tool in ("search", "fetch")]
        self.assertEqual(len(set(names)), 2, names)
        for name, tool in zip(names, ("search", "fetch")):
            with self.subTest(tool=tool):
                self.assertTrue(name.endswith(f"_{tool}"), name)
                self.assertLessEqual(len(name), project_config.MCP_TOOL_NAME_MAX_CHARS)
                self.assertEqual(name, sanitise_name(f"{address} fixture.py_{tool}"), "not stable")

    def test_a_name_under_the_cap_is_untouched_by_the_digest(self) -> None:
        from brief_crew.builder.mcp import sanitise_name

        self.assertEqual(sanitise_name("127.0.0.1:54253/mcp_search"), "127_0_0_1_54253_mcp_search")


class AuditM12ArgvAllowListTests(unittest.TestCase):
    """The stdio allow-list names COMMAND LINES, not commands - audit M12.

    `MCP_ALLOWED_COMMANDS` matched `command` and let `args` through on a
    shell-metacharacter check alone. `npx -y attacker-pkg` contains no
    metacharacter, so with `MCP_STDIO_ENABLED=1` and `npx` permitted the
    allow-list was doing no work: **the package name in the argument is the
    code**. Production has both knobs unset and `render.yaml` sets neither, so
    this was a configuration trap rather than a live hole - and a trap the old
    comment beside the knob walked the operator into, because it offered
    `npx,uvx` as the example value.

    `config.py` reads the environment at import, so every arm here patches the
    parsed constants the way `TransportPolicyTests` patches
    `MCP_ALLOW_INSECURE_LOCAL`, rather than the environment.
    """

    #: The line a real deployment would permit, and the one the old check could
    #: not tell apart from `npx -y attacker-pkg`.
    FILESYSTEM = ("npx", "-y", "@modelcontextprotocol/server-filesystem", "/srv/docs")

    def _stdio(self, **kwargs: Any) -> str | None:
        return transport_refusal(transport="stdio", **kwargs)

    def test_M12_the_attack_line_is_refused_under_the_OLD_list(self) -> None:
        """`npx` permitted, argv list empty: the demotion refuses the arguments.

        This is the assertion that fails on the unfixed code, where the command
        matched, no argument carried a metacharacter, and the function returned
        None - which is a signed-in author choosing which npm package this
        container executes.
        """

        with patch.object(project_config, "MCP_STDIO_ENABLED", True), patch.object(
            project_config, "MCP_ALLOWED_COMMANDS", ("npx",)
        ), patch.object(project_config, "MCP_ALLOWED_ARGV", ()):
            refusal = self._stdio(command="npx", args=["-y", "attacker-pkg"])
        self.assertIsNotNone(refusal)
        self.assertIn("attacker-pkg", str(refusal))
        self.assertIn("bare command only", str(refusal))

    def test_M12_a_bare_command_is_still_admitted_by_the_OLD_list(self) -> None:
        """The demotion, not a removal: `MCP_ALLOWED_COMMANDS` still speaks for
        the one case in which matching the command really did match the code."""

        with patch.object(project_config, "MCP_STDIO_ENABLED", True), patch.object(
            project_config, "MCP_ALLOWED_COMMANDS", ("npx",)
        ), patch.object(project_config, "MCP_ALLOWED_ARGV", ()):
            self.assertIsNone(self._stdio(command="npx"))
            self.assertIsNone(self._stdio(command="npx", args=[]))

    def test_M12_the_exact_line_is_admitted_and_a_changed_argument_is_not(self) -> None:
        """The control. `/srv/docs` and `/etc` differ in one argument, and that
        argument is the whole of what the filesystem server can read."""

        with patch.object(project_config, "MCP_STDIO_ENABLED", True), patch.object(
            project_config, "MCP_ALLOWED_ARGV", (self.FILESYSTEM,)
        ):
            self.assertIsNone(self._stdio(command="npx", args=list(self.FILESYSTEM[1:])))
            refusal = self._stdio(
                command="npx",
                args=["-y", "@modelcontextprotocol/server-filesystem", "/etc"],
            )
        self.assertIsNotNone(refusal)
        self.assertIn("/etc", str(refusal))
        self.assertIn("COMPLETE command lines", str(refusal))

    def test_M12_the_argv_list_decides_ALONE_when_both_are_set(self) -> None:
        """`MCP_ALLOWED_COMMANDS` cannot widen `MCP_ALLOWED_ARGV`.

        Otherwise the compatibility knob would be a bypass of the control that
        replaced it: an operator who left `npx` on the old list would still be
        running whatever package an author named.
        """

        with patch.object(project_config, "MCP_STDIO_ENABLED", True), patch.object(
            project_config, "MCP_ALLOWED_COMMANDS", ("npx", "uvx")
        ), patch.object(project_config, "MCP_ALLOWED_ARGV", (self.FILESYSTEM,)):
            self.assertIsNone(self._stdio(command="npx", args=list(self.FILESYSTEM[1:])))
            # Bare `npx` is on the old list and is not a permitted LINE.
            self.assertIsNotNone(self._stdio(command="npx"))
            self.assertIsNotNone(self._stdio(command="uvx", args=["mcp-server"]))

    def test_M12_a_line_that_differs_only_in_ORDER_is_refused(self) -> None:
        """The match is a tuple comparison, so it is positional. A set or a
        subset test would admit `npx <package> -y /srv/docs`, which is a
        different program."""

        shuffled = ("npx", "@modelcontextprotocol/server-filesystem", "-y", "/srv/docs")
        with patch.object(project_config, "MCP_STDIO_ENABLED", True), patch.object(
            project_config, "MCP_ALLOWED_ARGV", (self.FILESYSTEM,)
        ):
            self.assertIsNotNone(self._stdio(command="npx", args=list(shuffled[1:])))

    def test_M12_a_prefix_or_a_suffix_of_a_permitted_line_is_refused(self) -> None:
        """Exact, not `startswith`: dropping the trailing path argument changes
        which directory the server serves, and appending one adds a capability."""

        with patch.object(project_config, "MCP_STDIO_ENABLED", True), patch.object(
            project_config, "MCP_ALLOWED_ARGV", (self.FILESYSTEM,)
        ):
            self.assertIsNotNone(
                self._stdio(command="npx", args=list(self.FILESYSTEM[1:-1]))
            )
            self.assertIsNotNone(
                self._stdio(command="npx", args=[*self.FILESYSTEM[1:], "--allow-write"])
            )

    def test_M12_metacharacters_are_still_refused_and_keep_their_sentence(self) -> None:
        """The belt kept beside the braces, checked first so the sentence names
        the shape of the data rather than the policy."""

        with patch.object(project_config, "MCP_STDIO_ENABLED", True), patch.object(
            project_config, "MCP_ALLOWED_ARGV", (self.FILESYSTEM,)
        ):
            refusal = self._stdio(command="npx", args=["-y", "pkg; rm -rf /"])
        self.assertIsNotNone(refusal)
        self.assertIn("metacharacters", str(refusal))

    def test_M12_the_stdio_FLAG_still_outranks_both_lists(self) -> None:
        """The default posture: a permitted line with the flag off is refused,
        and the sentence names the flag rather than the line."""

        self.assertFalse(project_config.MCP_STDIO_ENABLED)
        with patch.object(project_config, "MCP_ALLOWED_ARGV", (self.FILESYSTEM,)):
            refusal = self._stdio(command="npx", args=list(self.FILESYSTEM[1:]))
        self.assertIsNotNone(refusal)
        self.assertIn("remote MCP servers only", str(refusal))

    def test_M12_the_env_key_allow_list_still_runs_after_a_permitted_line(self) -> None:
        """The check the argv match must not have swallowed."""

        with patch.object(project_config, "MCP_STDIO_ENABLED", True), patch.object(
            project_config, "MCP_ALLOWED_ARGV", (self.FILESYSTEM,)
        ):
            refusal = self._stdio(
                command="npx",
                args=list(self.FILESYSTEM[1:]),
                env_keys=("SECRET_TOKEN",),
            )
        self.assertIsNotNone(refusal)
        self.assertIn("SECRET_TOKEN", str(refusal))

    def test_M12_the_refused_line_is_BOUNDED_because_it_is_author_data(self) -> None:
        """`args` is stored author text and the sentence reaches a 422 body, a
        log line and the canvas, so the echo is capped rather than quoted whole."""

        with patch.object(project_config, "MCP_STDIO_ENABLED", True), patch.object(
            project_config, "MCP_ALLOWED_ARGV", (self.FILESYSTEM,)
        ):
            refusal = self._stdio(command="npx", args=["a" * 5000])
        self.assertIsNotNone(refusal)
        self.assertNotIn("a" * 400, str(refusal))
        self.assertIn("…", str(refusal))
        self.assertLess(len(str(refusal)), 500)


class AuditM12ArgvKnobParsingTests(unittest.TestCase):
    """`MCP_ALLOWED_ARGV` is a list of command LINES, parsed with `shlex`.

    Two separators, because a dashboard environment field holds one line: a
    newline, and `;;`. The reader is `config.py` at import, so this exercises
    the real comprehension by importing the module under a patched environment
    in a CHILD process - no `importlib.reload`, and nothing here moves a
    constant in this one.
    """

    def _parse(self, value: str) -> Any:
        import json
        import os
        import pathlib
        import subprocess
        import sys

        root = pathlib.Path(__file__).resolve().parent.parent.parent
        env = dict(os.environ)
        env["MCP_ALLOWED_ARGV"] = value
        env["MCP_ALLOWED_COMMANDS"] = ""
        env["PYTHONPATH"] = str(root / "src")
        env["LANGFUSE_EXPORT_ENABLED"] = "0"
        proc = subprocess.run(
            [
                sys.executable,
                "-c",
                "import json;from brief_crew import config as c;"
                "print(json.dumps([list(line) for line in c.MCP_ALLOWED_ARGV]))",
            ],
            capture_output=True,
            text=True,
            env=env,
            cwd=str(root),
        )
        if proc.returncode != 0:
            return proc.stderr
        return json.loads(proc.stdout.strip().splitlines()[-1])

    def test_M12_the_default_is_empty_so_the_flag_alone_opens_nothing(self) -> None:
        self.assertEqual(project_config.MCP_ALLOWED_ARGV, ())
        self.assertEqual(self._parse(""), [])

    def test_M12_a_double_semicolon_separates_two_lines(self) -> None:
        self.assertEqual(
            self._parse("npx -y pkg-a /srv/a;;uvx mcp-server-b"),
            [["npx", "-y", "pkg-a", "/srv/a"], ["uvx", "mcp-server-b"]],
        )

    def test_M12_a_newline_separates_two_lines_and_blanks_are_dropped(self) -> None:
        self.assertEqual(
            self._parse("npx -y pkg-a\n\n  \nuvx mcp-server-b\n"),
            [["npx", "-y", "pkg-a"], ["uvx", "mcp-server-b"]],
        )

    def test_M12_a_quoted_argument_survives_as_ONE_word(self) -> None:
        """Which is the whole reason it is `shlex.split` and not `str.split`: a
        path with a space in it is one argument to the process."""

        self.assertEqual(
            self._parse('npx -y pkg "/srv/my docs"'),
            [["npx", "-y", "pkg", "/srv/my docs"]],
        )

    def test_M12_an_unbalanced_quote_refuses_the_boot_and_names_the_knob(self) -> None:
        """A bare `ValueError: No closing quotation` out of a module-level
        comprehension is a boot crash with no sentence anywhere."""

        stderr = str(self._parse('npx -y "pkg'))
        self.assertIn("MCP_ALLOWED_ARGV", stderr)
        self.assertIn("complete command line", stderr)

    def test_M12_the_demotion_warns_ONCE_at_import_naming_the_migration(self) -> None:
        """An existing `MCP_ALLOWED_COMMANDS` deployment changes meaning here,
        and a server that stops working with no sentence anywhere is worse than
        the hole. The warning fires only in that one configuration."""

        import os
        import pathlib
        import subprocess
        import sys

        root = pathlib.Path(__file__).resolve().parent.parent.parent
        script = (
            "import logging;logging.basicConfig(level=logging.WARNING);"
            "import brief_crew.config"
        )

        def run(**overrides: str) -> str:
            env = dict(os.environ)
            env["PYTHONPATH"] = str(root / "src")
            env["LANGFUSE_EXPORT_ENABLED"] = "0"
            env["MCP_ALLOWED_COMMANDS"] = ""
            env["MCP_ALLOWED_ARGV"] = ""
            env.update(overrides)
            return subprocess.run(
                [sys.executable, "-c", script],
                capture_output=True,
                text=True,
                env=env,
                cwd=str(root),
            ).stderr

        warned = run(MCP_ALLOWED_COMMANDS="npx,uvx")
        self.assertIn("MCP_ALLOWED_ARGV", warned)
        self.assertIn("no arguments", warned)
        # Silent in the two configurations that are not a migration.
        self.assertNotIn("MCP_ALLOWED_ARGV is empty", run())
        self.assertNotIn(
            "MCP_ALLOWED_ARGV is empty",
            run(MCP_ALLOWED_COMMANDS="npx", MCP_ALLOWED_ARGV="npx -y pkg"),
        )
