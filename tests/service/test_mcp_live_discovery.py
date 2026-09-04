"""Discovery against a REAL MCP server - plan 07 criterion 1's missing half.

Every other test in plan 07 injects a `Resolver`. That is the right seam for
policy, sanitising, truncation and the stale window, and plan 07's Status said
so; what it also meant is that **nothing in this repository had ever constructed
the real `MCPToolResolver`**, and the moment something did, discovery answered:

```text
status: error   could not connect: MCPToolResolver.__init__() missing 2
                required positional arguments: 'agent' and 'logger'
```

`_default_resolver` called it with none. So discovery against any real server
had never worked, in any deployment, and the sentence an author would have read
in the panel was a `TypeError` about CrewAI's constructor. Fixed in
`builder/mcp.py`; this file is what would have caught it and is the only kind of
test that could.

**Both transports the criterion names are here.** An HTTP server over loopback
(`MCP_ALLOW_INSECURE_LOCAL`, the flag whose docstring names this fixture) and a
stdio server on the allow-list (`MCP_STDIO_ENABLED` plus
`MCP_ALLOWED_COMMANDS`, both off in every deployment and both patched on here).
The stdio arm is the only place in the suite where those two flags are lifted
together and a process is actually started.

**No money and no network.** `tests/service/mcp_fixture_server.py` is a
`FastMCP` with two tools; the HTTP arm runs it in a daemon thread on a port the
OS just released, and the stdio arm runs this interpreter on the same file.
Nothing leaves the machine.
"""

from __future__ import annotations

import sys
import unittest
from typing import Any
from unittest.mock import patch

from brief_crew import config as project_config
from brief_crew.builder import mcp as mcp_module
from tests.service import mcp_fixture_server as fixture
from tests.service.identities import AuthenticatedTwoUserCase

try:  # pragma: no cover - the service extra is optional, as elsewhere in tests/
    from fastapi.testclient import TestClient  # noqa: F401

    FASTAPI_AVAILABLE = True
except Exception:  # pragma: no cover
    FASTAPI_AVAILABLE = False

SERVERS = "/api/builder/mcp/servers"

#: `mcp` ships with CrewAI's MCP support; if it is ever absent these skip
#: rather than fail, because a missing optional package is not a defect in this
#: repository and a red suite would say it was.
try:  # pragma: no cover
    import mcp as _mcp  # noqa: F401

    MCP_AVAILABLE = True
except Exception:  # pragma: no cover
    MCP_AVAILABLE = False


def _names(tools: Any) -> list[str]:
    """The bare tool name, out of the address CrewAI prefixes onto it.

    **Measured, and it surprises everyone once.** `MCPNativeTool` derives its
    name from the SERVER, so the loopback fixture's `search` arrives as
    `127_0_0_1_54253_mcp_search` and the stdio one as the whole sanitised
    command line. That is CrewAI's naming, not this repository's sanitiser -
    `sanitise_tool` receives the prefixed name and only normalises it - and it
    has one consequence worth knowing before an author meets it: an HTTP
    server's discovered names contain its PORT, so re-discovering the same
    server on a different port renames every tool and a stored `tool_names`
    selection stops matching. A hosted server has a stable address and does not
    have this problem; a loopback fixture on an ephemeral port always does.
    """

    return [str(tool.name).rsplit("_", 1)[-1] for tool in tools]


@unittest.skipUnless(MCP_AVAILABLE, "the mcp package is not installed")
class DefaultResolverTests(unittest.TestCase):
    """The regression, as narrowly as it can be stated, and it is fast.

    A connection refusal has to come back as a sentence about the CONNECTION.
    Before the repair it came back as a sentence about a Python constructor,
    which is the shape of failure that survives review indefinitely because it
    looks like a connection failure to everyone who is not reading closely.
    """

    def test_a_refused_connection_reports_the_connection_and_not_a_TypeError(
        self,
    ) -> None:
        port = fixture.free_port()  # free, and therefore nothing is listening
        record = mcp_module.McpServerRecord(
            id="mcp_deadbeef1234",
            user_id="user_alice",
            label="nothing here",
            transport="http",
            url=f"http://127.0.0.1:{port}/mcp",
        )
        with patch.object(project_config, "MCP_ALLOW_INSECURE_LOCAL", True):
            result = mcp_module.discover(record)

        self.assertEqual(result.status, "error")
        self.assertIsNotNone(result.error)
        self.assertNotIn("positional argument", result.error or "")
        self.assertNotIn("__init__", result.error or "")


@unittest.skipUnless(FASTAPI_AVAILABLE, "FastAPI service extra is not installed")
@unittest.skipUnless(MCP_AVAILABLE, "the mcp package is not installed")
class LiveHttpDiscoveryTests(AuthenticatedTwoUserCase):
    """The whole criterion over the route, against a server that is running."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.port = fixture.free_port()
        fixture.serve_http(cls.port)
        cls.url = f"http://127.0.0.1:{cls.port}/mcp"

    def setUp(self) -> None:
        super().setUp()
        # Loopback over plain HTTP is refused by the SSRF rule unless this is
        # set; the flag exists for exactly this fixture and for local
        # development, and `render.yaml` sets neither it nor the stdio pair.
        patcher = patch.object(project_config, "MCP_ALLOW_INSECURE_LOCAL", True)
        patcher.start()
        self.addCleanup(patcher.stop)
        created = self.client.post(
            SERVERS,
            json={"label": "Loopback fixture", "transport": "http", "url": self.url},
            headers=self.as_alice(),
        )
        self.assertEqual(created.status_code, 201, created.text)
        self.server_id = created.json()["id"]

    def _discover(self) -> dict[str, Any]:
        response = self.client.post(
            f"{SERVERS}/{self.server_id}/discover", headers=self.as_alice()
        )
        self.assertEqual(response.status_code, 200, response.text)
        return response.json()

    def _row(self) -> dict[str, Any]:
        listing = self.client.get(SERVERS, headers=self.as_alice())
        self.assertEqual(listing.status_code, 200, listing.text)
        rows = [row for row in listing.json()["servers"] if row["id"] == self.server_id]
        self.assertEqual(len(rows), 1)
        return rows[0]

    def test_discovery_returns_the_tool_list_with_schemas(self) -> None:
        body = self._discover()
        self.assertEqual(body["status"], "authorized", body.get("error"))
        self.assertEqual(
            sorted(_names(mcp_module.DiscoveredTool(**tool) for tool in body["tools"])),
            ["fetch", "search"],
        )
        search = [tool for tool in body["tools"] if tool["name"].endswith("_search")][0]
        # A SCHEMA, not just a name: this is what the inspector's read-only
        # parameter preview renders, and the whole reason discovery stores more
        # than a list of strings.
        self.assertEqual(search["input_schema"]["type"], "object")
        self.assertIn("query", search["input_schema"]["properties"])
        self.assertIn("limit", search["input_schema"]["properties"])

    def test_the_sanitiser_really_ran_over_what_the_server_said(self) -> None:
        """The injection phrase is in the FIXTURE's description on purpose.

        Decision 8: a suspicious tool stays selectable with its pattern shown.
        A fixture whose descriptions were all innocuous could not tell that rule
        working apart from the sanitiser never running.
        """

        body = self._discover()
        fetch = [tool for tool in body["tools"] if tool["name"].endswith("_fetch")][0]
        self.assertTrue(fetch["suspicious"])
        self.assertTrue(fetch["matched_pattern"])
        # And it is still there to be selected, rather than hidden.
        search = [tool for tool in body["tools"] if tool["name"].endswith("_search")][0]
        self.assertFalse(search["suspicious"])

    def test_discovery_stores_the_result_on_the_row(self) -> None:
        self._discover()
        row = self._row()
        self.assertEqual(row["status"], "authorized")
        self.assertEqual(sorted(_names(mcp_module.DiscoveredTool(**t) for t in row["tools"])), ["fetch", "search"])
        self.assertIsNotNone(row["discovered_at"])
        self.assertFalse(row["stale"])
        self.assertIsNone(row["last_error"])

    def test_a_second_read_inside_the_stale_window_is_served_from_the_row(
        self,
    ) -> None:
        """The criterion's second clause, and the proof is that it works OFFLINE.

        The row is read back against a URL nothing is listening on. If the read
        dialled anything it would come back empty or erroring; it comes back
        with both tools and `stale: false`, which is only possible from storage.
        """

        self._discover()
        before = self._row()

        dead = fixture.free_port()
        updated = self.client.put(
            f"{SERVERS}/{self.server_id}",
            json={
                "label": "Loopback fixture",
                "transport": "http",
                "url": f"http://127.0.0.1:{dead}/mcp",
            },
            headers=self.as_alice(),
        )
        self.assertEqual(updated.status_code, 200, updated.text)

        after = self._row()
        self.assertEqual(after["tools"], before["tools"])
        self.assertFalse(after["stale"])
        self.assertEqual(after["discovered_at"], before["discovered_at"])

        # And the control: asking it to RE-discover really does dial, and fails.
        again = self._discover()
        self.assertEqual(again["status"], "error")


@unittest.skipUnless(MCP_AVAILABLE, "the mcp package is not installed")
class LiveStdioDiscoveryTests(unittest.TestCase):
    """The other transport the criterion names, with both gates lifted.

    Driven through `discover` rather than through the route: the route's create
    handler applies the same `transport_refusal`, which is asserted from the
    refusing side in `test_mcp_discovery.py::TransportPolicyTests`, and what is
    new here is that a permitted stdio command really is spawned and really does
    answer. Both flags are patched on and restored; the defaults are off and
    `test_mcp_discovery.py` asserts that they are.
    """

    def _record(self) -> mcp_module.McpServerRecord:
        # Forward slashes deliberately: `_SHELL_METACHARACTERS` includes the
        # backslash, so a Windows path spelled natively is refused as an
        # argument - correctly, and this is how a caller passes one anyway.
        script = fixture.__file__.replace("\\", "/")
        return mcp_module.McpServerRecord(
            id="mcp_deadbeef1234",
            user_id="user_alice",
            label="stdio fixture",
            transport="stdio",
            command=sys.executable.replace("\\", "/"),
            args=(script,),
        )

    def test_a_permitted_stdio_server_is_spawned_and_answers(self) -> None:
        record = self._record()
        with patch.object(project_config, "MCP_STDIO_ENABLED", True), patch.object(
            project_config, "MCP_ALLOWED_COMMANDS", (record.command,)
        ):
            result = mcp_module.discover(record)

        self.assertEqual(result.status, "authorized", result.error)
        self.assertEqual(sorted(_names(result.tools)), ["fetch", "search"])
        self.assertTrue(result.discovered_at)

    def test_the_same_server_is_refused_with_the_flag_off(self) -> None:
        """The control, on the same record, so the arm above is not vacuous."""

        record = self._record()
        with patch.object(project_config, "MCP_STDIO_ENABLED", False):
            result = mcp_module.discover(record)

        self.assertEqual(result.status, "error")
        self.assertIn("remote MCP servers only", result.error or "")


if __name__ == "__main__":
    unittest.main()
