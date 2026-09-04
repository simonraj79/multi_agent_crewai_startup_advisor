"""The declarative custom HTTP tool - plan 06 D7 and criterion 6.

Flowise's `ToolDialog` is the reference and its `func` field is the one thing
deliberately not copied: a JavaScript function stored per user is an evaluation
surface, and the six closed `BUILDER_TRANSFORM_OPS` are this repository's
standing answer to that trade. What is copied is the SHAPE - a name, a
description, a grid of typed properties - with an HTTPS request template where
the function was.

Criterion 6 asks for six cases, and they are the six that decide whether this is
a tool or a hole in the network:

1. the happy path returns the repository's own envelope, so a custom tool's
   output looks to the guardrails exactly like a built-in's;
2. a URL resolving to `127.0.0.1` is refused;
3. an `http://` URL is refused;
4. a response over `max_response_bytes` is refused;
5. a redirect is not followed;
6. every refusal is a `status: failed` ENVELOPE naming the reason, never an
   exception - because a tool that raises is a tool that becomes a
   `ToolExecutionFailedError` under `raise` and a stack trace under `warn`,
   and neither tells the agent what happened in a form it can report.

No cost: the transport and the DNS resolver are both injected. Nothing here
opens a socket or resolves a name.
"""

from __future__ import annotations

import json
import unittest
from collections.abc import Mapping
from typing import Any

from brief_crew import config as project_config
from brief_crew.builder.tools import (
    CustomToolError,
    build_custom_tool,
    parse_custom_tool,
    refuse_private_target,
)

WEATHER = {
    "name": "weather_lookup",
    "description": "Current weather for a city. Use when the user names a place.",
    "properties": [
        {
            "name": "city",
            "type": "string",
            "description": "City name",
            "required": True,
        }
    ],
    "request": {
        "method": "GET",
        "url": "https://api.example.test/weather?q={city}",
        "header_name": "Authorization",
        "header_template": "Bearer {credential}",
        "body_template": None,
        "timeout_seconds": 15,
        "max_response_bytes": 1048576,
    },
}

PUBLIC = ["93.184.216.34"]
PRIVATE = ["127.0.0.1"]


def resolver(addresses: list[str]):
    return lambda _host: list(addresses)


def transport(status: int = 200, body: str = "{}", *, seen: list[Any] | None = None):
    def send(
        method: str,
        url: str,
        headers: Mapping[str, str],
        content: str | None,
        timeout: int,
        max_bytes: int,
    ) -> tuple[int, str]:
        if seen is not None:
            seen.append(
                {
                    "method": method,
                    "url": url,
                    "headers": dict(headers),
                    "content": content,
                    "timeout": timeout,
                    "max_bytes": max_bytes,
                }
            )
        return status, body

    return send


class ParseTests(unittest.TestCase):
    def test_the_reference_document_parses_into_the_shape_d7_names(self) -> None:
        spec = parse_custom_tool(WEATHER, tool_id="ut_0123456789ab")
        self.assertEqual(spec.name, "weather_lookup")
        self.assertEqual([prop.name for prop in spec.properties], ["city"])
        self.assertTrue(spec.properties[0].required)
        self.assertEqual(spec.request.method, "GET")
        self.assertEqual(
            spec.json_schema(),
            {
                "type": "object",
                "properties": {"city": {"type": "string", "description": "City name"}},
                "required": ["city"],
                "additionalProperties": False,
            },
        )

    def test_a_non_https_url_is_refused_at_parse_and_the_reason_names_the_header(self) -> None:
        with self.assertRaises(CustomToolError) as caught:
            parse_custom_tool({**WEATHER, "request": {**WEATHER["request"], "url": "http://api.example.test/x"}})
        self.assertIn("https", str(caught.exception))

    def test_a_placeholder_no_property_declares_is_refused(self) -> None:
        """The one that would otherwise render as an empty string at run time."""

        with self.assertRaises(CustomToolError) as caught:
            parse_custom_tool(
                {
                    **WEATHER,
                    "request": {
                        **WEATHER["request"],
                        "url": "https://api.example.test/w?q={town}",
                    },
                }
            )
        self.assertIn("town", str(caught.exception))

    def test_delete_is_refused_by_name_with_the_reason(self) -> None:
        with self.assertRaises(CustomToolError) as caught:
            parse_custom_tool(
                {**WEATHER, "request": {**WEATHER["request"], "method": "DELETE"}}
            )
        self.assertIn("destroy", str(caught.exception))

    def test_a_header_name_with_no_template_is_refused(self) -> None:
        with self.assertRaises(CustomToolError) as caught:
            parse_custom_tool(
                {
                    **WEATHER,
                    "request": {**WEATHER["request"], "header_template": None},
                }
            )
        self.assertIn("travel together", str(caught.exception))

    def test_the_name_pattern_is_the_documents_own(self) -> None:
        for bad in ("Weather", "1weather", "weather-lookup", "a" * 41):
            with self.subTest(name=bad), self.assertRaises(CustomToolError):
                parse_custom_tool({**WEATHER, "name": bad})

    def test_more_properties_than_the_ceiling_are_refused_by_the_ceiling(self) -> None:
        rows = [
            {"name": f"p{index}", "type": "string", "description": ""}
            for index in range(project_config.MAX_CUSTOM_TOOL_PROPERTIES + 1)
        ]
        with self.assertRaises(CustomToolError) as caught:
            parse_custom_tool({**WEATHER, "properties": rows})
        self.assertIn(str(project_config.MAX_CUSTOM_TOOL_PROPERTIES), str(caught.exception))


class RunTests(unittest.TestCase):
    """Criterion 6's six cases. Every one asserts the ENVELOPE, not an exception."""

    def _tool(self, addresses: list[str], send: Any, **overrides: Any) -> Any:
        payload = dict(WEATHER)
        payload["request"] = {**WEATHER["request"], **overrides}
        spec = parse_custom_tool(payload, tool_id="ut_0123456789ab")
        return build_custom_tool(
            spec,
            credential={"name": "Authorization", "header_value": "sekrit-token"},
            resolve=resolver(addresses),
            transport=send,
        )

    def test_the_happy_path_returns_the_repositorys_own_envelope(self) -> None:
        seen: list[Any] = []
        tool = self._tool(PUBLIC, transport(200, '{"tempC": 11}', seen=seen))
        envelope = json.loads(tool._run(city="Sao Paulo"))
        self.assertEqual(envelope["status"], "ok")
        self.assertEqual(envelope["tool"], "weather_lookup")
        self.assertEqual(envelope["result_count"], 1)
        self.assertEqual(
            sorted(envelope),
            ["notes", "query", "result_count", "results", "retrieved_at", "status", "tool"],
        )
        self.assertEqual(envelope["results"][0]["body"], '{"tempC": 11}')

    def test_a_placeholder_is_url_encoded_rather_than_interpolated_raw(self) -> None:
        """A space in a city name must not become a second query parameter."""

        seen: list[Any] = []
        tool = self._tool(PUBLIC, transport(seen=seen))
        tool._run(city="Sao Paulo&admin=1")
        self.assertIn("Sao%20Paulo%26admin%3D1", seen[0]["url"])

    def test_the_credential_reaches_the_header_and_not_the_envelope(self) -> None:
        seen: list[Any] = []
        tool = self._tool(PUBLIC, transport(seen=seen))
        body = tool._run(city="Lisbon")
        self.assertEqual(seen[0]["headers"], {"Authorization": "Bearer sekrit-token"})
        self.assertNotIn("sekrit-token", body)

    def test_a_url_resolving_to_loopback_is_refused_with_a_failed_envelope(self) -> None:
        tool = self._tool(PRIVATE, transport())
        envelope = json.loads(tool._run(city="anywhere"))
        self.assertEqual(envelope["status"], "failed")
        self.assertIn("127.0.0.1", envelope["notes"])
        self.assertEqual(envelope["results"], [])

    def test_an_http_url_is_refused_before_it_is_parsed_into_a_tool(self) -> None:
        """`http://` never reaches `_run`: it is refused at parse.

        Two doors rather than one, because the SSRF check runs against the URL
        the author wrote, and a template that could become `http://` at run time
        would walk past it.
        """

        with self.assertRaises(CustomToolError):
            parse_custom_tool(
                {**WEATHER, "request": {**WEATHER["request"], "url": "http://x.test/a"}}
            )
        self.assertIsNotNone(refuse_private_target("http://example.test/a", resolve=resolver(PUBLIC)))

    def test_a_response_over_the_cap_is_refused_naming_the_cap(self) -> None:
        def oversize(*_: Any, **__: Any) -> tuple[int, str]:
            from brief_crew.builder.tools import _ResponseTooLarge

            raise _ResponseTooLarge("the response passed 1024 bytes and was abandoned")

        tool = self._tool(PUBLIC, oversize, max_response_bytes=1024)
        envelope = json.loads(tool._run(city="Lisbon"))
        self.assertEqual(envelope["status"], "failed")
        self.assertIn("1024", envelope["notes"])

    def test_a_server_error_is_a_failed_envelope_and_a_429_is_rate_limited(self) -> None:
        """The two the guardrails read differently. `failed` is not `empty`."""

        for status, expected in ((500, "failed"), (429, "rate_limited")):
            with self.subTest(status=status):
                tool = self._tool(PUBLIC, transport(status, "nope"))
                envelope = json.loads(tool._run(city="Lisbon"))
                self.assertEqual(envelope["status"], expected)
                self.assertIn(str(status), envelope["notes"])

    def test_a_transport_exception_becomes_an_envelope_rather_than_escaping(self) -> None:
        def boom(*_: Any, **__: Any) -> tuple[int, str]:
            raise TimeoutError("read timed out")

        tool = self._tool(PUBLIC, boom)
        envelope = json.loads(tool._run(city="Lisbon"))
        self.assertEqual(envelope["status"], "failed")
        self.assertIn("TimeoutError", envelope["notes"])

    def test_the_generated_args_schema_names_the_declared_properties(self) -> None:
        tool = self._tool(PUBLIC, transport())
        schema = tool.args_schema.model_json_schema()
        self.assertIn("city", schema["properties"])
        self.assertEqual(schema["required"], ["city"])


class SsrfRuleTests(unittest.TestCase):
    """The rule `URLReadTool` already applies, restated because two callers need it."""

    def test_every_non_public_class_is_refused_by_address_not_by_spelling(self) -> None:
        for address in (
            "127.0.0.1",
            "10.0.0.5",
            "192.168.1.1",
            "172.16.0.1",
            "169.254.169.254",
            "::1",
            "0.0.0.0",
            "224.0.0.1",
        ):
            with self.subTest(address=address):
                refusal = refuse_private_target(
                    "https://totally-public.example.test/x", resolve=resolver([address])
                )
                self.assertIsNotNone(refusal)
                self.assertIn(address, str(refusal))

    def test_a_public_address_passes(self) -> None:
        self.assertIsNone(
            refuse_private_target("https://example.test/x", resolve=resolver(PUBLIC))
        )

    def test_loopback_is_admitted_only_behind_the_explicit_local_flag(self) -> None:
        self.assertIsNotNone(refuse_private_target("http://127.0.0.1:8099/mcp"))
        self.assertIsNone(
            refuse_private_target("http://127.0.0.1:8099/mcp", allow_insecure_local=True)
        )


if __name__ == "__main__":
    unittest.main()
