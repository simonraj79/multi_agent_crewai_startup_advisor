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
    vetted_target,
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
    #: `address` is the seventh argument since audit M3: the address
    #: `vetted_target` checked, which is the one the socket must go to.
    def send(
        method: str,
        url: str,
        headers: Mapping[str, str],
        content: str | None,
        timeout: int,
        max_bytes: int,
        address: str | None = None,
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
                    "address": address,
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


class CredentialInTheUrlTests(unittest.TestCase):
    """Audit M1: a key in the query string never reaches a frame in plaintext.

    `{credential}` is permitted in the URL because a query-string key is a real
    API shape (`.../v1?key=...&q=...`). The rendered URL was then written
    verbatim into the envelope's `query`, its `notes` and each result's `url`,
    and the serializer copies `query` onto the frame - where the redaction walk
    cannot help, because it keys on the FIELD NAME and `query` is not a secret
    name. So the plaintext key reached the 2,000-frame ring, the durable frames
    table, `GET /api/runs/{id}/frames`, the NDJSON and ZIP export, and Langfuse
    with content capture on.

    Both spellings are asserted, because the URL substitution is quoted: a key
    with a `/` or `+` in it appears percent-encoded in the URL and a redaction
    that only looked for the raw bytes would miss every such key.
    """

    #: Deliberately carries characters that change under `quote(safe="")`.
    SECRET = "sk-M1-SECRET/TOKEN+VALUE="
    QUOTED = "sk-M1-SECRET%2FTOKEN%2BVALUE%3D"

    SPEC = {
        "name": "key_in_url",
        "description": "A search API that takes its key as a query parameter.",
        "properties": [
            {"name": "q", "type": "string", "description": "query", "required": True}
        ],
        "request": {
            "method": "GET",
            "url": "https://api.example.test/v1?key={credential}&q={q}",
            "header_name": "Authorization",
            "header_template": "Bearer {credential}",
            "body_template": None,
            "timeout_seconds": 15,
            "max_response_bytes": 1048576,
        },
    }

    def _tool(self, send: Any) -> Any:
        spec = parse_custom_tool(self.SPEC, tool_id="ut_0123456789ab")
        return build_custom_tool(
            spec,
            credential={"name": "Authorization", "header_value": self.SECRET},
            resolve=resolver(PUBLIC),
            transport=send,
        )

    def assert_clean(self, rendered: str, where: str) -> None:
        self.assertNotIn(self.SECRET, rendered, f"the raw key is in {where}")
        self.assertNotIn(self.QUOTED, rendered, f"the encoded key is in {where}")
        self.assertIn("***", rendered, f"nothing was redacted in {where}")

    def test_M1_the_envelope_query_and_result_url_carry_no_key_in_either_spelling(self) -> None:
        seen: list[Any] = []
        tool = self._tool(transport(200, '{"hits": []}', seen=seen))
        raw = tool._run(q="rain")
        envelope = json.loads(raw)

        self.assertEqual(envelope["status"], "ok")
        self.assert_clean(envelope["query"], "envelope['query']")
        self.assert_clean(envelope["results"][0]["url"], "results[0]['url']")
        # The whole serialized envelope, which is what the frame is built from.
        self.assertNotIn(self.SECRET, raw)
        self.assertNotIn(self.QUOTED, raw)
        # The author's own argument is not a secret and must survive.
        self.assertIn("q=rain", envelope["query"])

    def test_M1_the_notes_of_a_transport_failure_carry_no_key(self) -> None:
        """httpx names the URL it was dialling; that sentence became `notes`."""

        def boom(_method: str, url: str, *_rest: Any, **__: Any) -> tuple[int, str]:
            raise TimeoutError(f"read timed out for {url}")

        envelope = json.loads(self._tool(boom)._run(q="rain"))
        self.assertEqual(envelope["status"], "failed")
        self.assertIn("TimeoutError", envelope["notes"])
        self.assert_clean(envelope["notes"], "envelope['notes']")
        self.assert_clean(envelope["query"], "envelope['query']")

    def test_M1_an_oversize_body_refusal_carries_no_key_either(self) -> None:
        def oversize(_method: str, url: str, *_rest: Any, **__: Any) -> tuple[int, str]:
            from brief_crew.builder.tools import _ResponseTooLarge

            raise _ResponseTooLarge(f"the response from {url} was abandoned")

        envelope = json.loads(self._tool(oversize)._run(q="rain"))
        self.assertEqual(envelope["status"], "failed")
        self.assert_clean(envelope["notes"], "envelope['notes']")

    def test_M1_a_refused_target_reports_without_the_key(self) -> None:
        spec = parse_custom_tool(self.SPEC, tool_id="ut_0123456789ab")
        tool = build_custom_tool(
            spec,
            credential={"name": "Authorization", "header_value": self.SECRET},
            resolve=resolver(PRIVATE),
            transport=transport(),
        )
        envelope = json.loads(tool._run(q="rain"))
        self.assertEqual(envelope["status"], "failed")
        self.assert_clean(envelope["query"], "envelope['query']")
        self.assertNotIn(self.SECRET, envelope["notes"])

    def test_M1_the_request_that_goes_out_still_carries_the_real_key(self) -> None:
        """Redaction is on the REPORT. The tool would be useless otherwise."""

        seen: list[Any] = []
        self._tool(transport(200, "{}", seen=seen))._run(q="rain")
        self.assertEqual(seen[0]["headers"], {"Authorization": f"Bearer {self.SECRET}"})
        # In the URL it is quoted, so an `&` or `#` in a key cannot truncate it.
        self.assertIn(f"key={self.QUOTED}", seen[0]["url"])
        self.assertNotIn(self.SECRET, seen[0]["url"])


class CheckThenConnectTests(unittest.TestCase):
    """Audit M3: the address that was CHECKED is the address that is dialled.

    `refuse_private_target` resolved the name, vetted the answers and threw
    them away; `_default_transport` then handed the NAME to httpx, which
    resolved it a second time. A TTL-0 record alternating between a public
    address and `10.0.0.5` passes the check and is dialled at the private one a
    few milliseconds later - and the connection error comes back verbatim in
    the envelope, so even a refused dial is an internal port-scan oracle. The
    repository already pins `hostaddr` in `postgres_probe_target` for exactly
    this reason; this side did not.
    """

    PUBLIC = "93.184.216.34"
    PRIVATE = "10.0.0.5"

    def _tool(self, resolve: Any, send: Any) -> Any:
        spec = parse_custom_tool(WEATHER, tool_id="ut_0123456789ab")
        return build_custom_tool(
            spec,
            credential={"name": "Authorization", "header_value": "sekrit-token"},
            resolve=resolve,
            transport=send,
        )

    def test_M3_the_transport_is_handed_the_vetted_address_not_just_the_name(self) -> None:
        seen: list[Any] = []
        self._tool(resolver([self.PUBLIC]), transport(seen=seen))._run(city="Lisbon")
        self.assertEqual(seen[0]["address"], self.PUBLIC)
        # The URL still names the host: the transport rewrites it, so TLS can
        # stay bound to the NAME through `sni_hostname`.
        self.assertIn("api.example.test", seen[0]["url"])

    def test_M3_a_resolver_answering_public_then_private_never_dials_the_private_one(self) -> None:
        """The rebinding shape, with a transport that resolves the way httpx did.

        The stub stands in for `httpx`: handed no vetted address it looks the
        name up itself, which is precisely the second resolution this fix
        removes. Before the fix the tool passed six arguments, the stub
        resolved, and the dial landed on `10.0.0.5`.
        """

        answers = [[self.PUBLIC], [self.PRIVATE]]
        calls: list[str] = []

        def flapping(host: str) -> list[str]:
            calls.append(host)
            return answers.pop(0) if len(answers) > 1 else answers[0]

        dialled: list[str] = []

        def resolving_transport(
            _method: str,
            url: str,
            _headers: Mapping[str, str],
            _content: str | None,
            _timeout: int,
            _max_bytes: int,
            address: str | None = None,
        ) -> tuple[int, str]:
            host = url.split("//", 1)[1].split("/", 1)[0]
            dialled.append(address if address is not None else flapping(host)[0])
            return 200, "{}"

        envelope = json.loads(self._tool(flapping, resolving_transport)._run(city="Lisbon"))
        self.assertEqual(envelope["status"], "ok")
        self.assertEqual(dialled, [self.PUBLIC])
        self.assertNotIn(self.PRIVATE, dialled)
        # Resolved ONCE. The second answer is never consulted, which is the
        # property: a second lookup is a second chance for the record to move.
        self.assertEqual(calls, ["api.example.test"])

    def test_M3_a_shared_address_space_answer_is_refused_by_the_is_global_catch_all(self) -> None:
        """100.64.0.0/10 is neither private nor reserved in Python 3.13.

        It is carrier-grade NAT and pod addressing on some platforms, and
        `credentials._address_class` has refused it since plan 01. This side
        admitted it, so the two halves of one rule disagreed about "public".
        """

        for address in ("100.64.0.1", "100.127.255.254"):
            with self.subTest(address=address):
                refusal, vetted = vetted_target(
                    "https://api.example.test/x", resolve=resolver([address])
                )
                self.assertIsNotNone(refusal)
                self.assertIsNone(vetted)
                self.assertIn(address, str(refusal))

        seen: list[Any] = []
        envelope = json.loads(
            self._tool(resolver(["100.64.0.1"]), transport(seen=seen))._run(city="x")
        )
        self.assertEqual(envelope["status"], "failed")
        self.assertEqual(seen, [], "the transport was reached")

    def test_M3_vetted_target_answers_the_address_for_a_public_name(self) -> None:
        refusal, address = vetted_target(
            "https://api.example.test/x", resolve=resolver([self.PUBLIC])
        )
        self.assertIsNone(refusal)
        self.assertEqual(address, self.PUBLIC)

    def test_M3_the_local_escape_hatch_pins_nothing_and_dials_the_url_as_written(self) -> None:
        refusal, address = vetted_target(
            "http://127.0.0.1:8099/mcp", allow_insecure_local=True
        )
        self.assertIsNone(refusal)
        self.assertIsNone(address)


class DefaultTransportPinTests(unittest.TestCase):
    """Audit M3, the httpx half: the socket goes to the IP, TLS to the name."""

    class _Response:
        status_code = 200

        def __enter__(self) -> Any:
            return self

        def __exit__(self, *_exc: Any) -> None:
            return None

        @staticmethod
        def iter_bytes():
            yield b"{}"

    def _client(self, calls: list[dict[str, Any]]) -> Any:
        response = self._Response()

        class Client:
            def __init__(self, **kwargs: Any) -> None:
                calls.append({"init": kwargs})

            def __enter__(self) -> Any:
                return self

            def __exit__(self, *_exc: Any) -> None:
                return None

            @staticmethod
            def stream(method: str, url: str, **kwargs: Any) -> Any:
                calls.append({"method": method, "url": url, **kwargs})
                return response

        return Client

    def _send(self, address: str | None) -> dict[str, Any]:
        from unittest.mock import patch

        import httpx

        from brief_crew.builder.tools import _default_transport

        calls: list[dict[str, Any]] = []
        with patch.object(httpx, "Client", self._client(calls)):
            status, text = _default_transport(
                "GET",
                "https://api.example.test/weather?q=x",
                {"Authorization": "Bearer t"},
                None,
                15,
                1024,
                address,
            )
        self.assertEqual((status, text), (200, "{}"))
        return calls[1]

    def test_M3_the_request_line_names_the_ip_and_the_handshake_names_the_host(self) -> None:
        call = self._send("93.184.216.34")
        self.assertEqual(call["url"], "https://93.184.216.34/weather?q=x")
        self.assertEqual(call["extensions"]["sni_hostname"], "api.example.test")
        self.assertEqual(call["headers"]["Host"], "api.example.test")
        # The author's own header survives the rewrite.
        self.assertEqual(call["headers"]["Authorization"], "Bearer t")

    def test_M3_with_no_vetted_address_the_url_is_dialled_as_written(self) -> None:
        call = self._send(None)
        self.assertEqual(call["url"], "https://api.example.test/weather?q=x")
        self.assertEqual(call["extensions"], {})
        self.assertNotIn("Host", call["headers"])


if __name__ == "__main__":
    unittest.main()
