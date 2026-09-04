"""The postgres probe vets every host BEFORE it dials (round 2, no ledger row).

`POST /api/builder/credentials/{id}/test` on a `postgres` credential ran
`SELECT 1` against whatever DSN a signed-in user had stored -
`psycopg.connect(dsn)`, straight to it. A signed-in user is not a trusted one,
and "whatever DSN" is `127.0.0.1:5432` (this service's own database on
Render), `10.x` (anything on the private network), `169.254.169.254` (the
cloud metadata endpoint), or a hostname that resolves to any of those. That is
server-side request forgery with a five-second timeout and a friendly sentence
back: a port scan of the inside of the deployment, one credential at a time.
The round-1 critic rejected it as out of dimension - not a user-A-versus-user-B
leak - and the owner ruled it built here.

Four classes, a test per class, each asserting two things: the probe answers
a refusal naming the class, and the injected ping was NEVER called. "Refused"
means before the dial, not instead of a successful one. Names are resolved
through an injected table, so nothing here touches DNS.
"""

from __future__ import annotations

import socket
import unittest
from typing import Any
from unittest.mock import patch

from psycopg.conninfo import conninfo_to_dict

from brief_crew.service.credentials import (
    POSTGRES_PROBE_REFUSAL,
    ProbeResult,
    postgres_probe_target,
    probe_credential,
)
from tests.service.identities import CREDENTIALS, AuthenticatedTwoUserCase

try:  # pragma: no cover
    from fastapi.testclient import TestClient  # noqa: F401

    FASTAPI_AVAILABLE = True
except Exception:  # pragma: no cover
    FASTAPI_AVAILABLE = False

PASSWORD = "hunter2-NEVER-IN-A-SENTENCE"
PUBLIC_V4 = "93.184.216.34"
PUBLIC_V6 = "2001:4860:4860::8888"

#: What the fake resolver answers. Anything not here raises like DNS does.
TABLE: dict[str, list[str]] = {
    "db.example.test": [PUBLIC_V4],
    "db6.example.test": [PUBLIC_V6],
    "two.example.test": [PUBLIC_V4, PUBLIC_V6],
    "loop.example.test": ["127.0.0.2"],
    "internal.example.test": ["10.1.2.3"],
    "mixed.example.test": [PUBLIC_V4, "10.1.2.3"],
    "metadata.example.test": ["169.254.169.254"],
    "cgnat.example.test": ["100.64.0.1"],
    "empty.example.test": [],
}


def resolve(host: str) -> list[str]:
    try:
        return list(TABLE[host])
    except KeyError as exc:
        raise socket.gaierror(-2, "Name or service not known") from exc


def dsn(host: str, *, scheme: bool = True, **extra: str) -> str:
    if scheme:
        query = "&".join(f"{k}={v}" for k, v in extra.items())
        return f"postgresql://alice:{PASSWORD}@{host}:5432/app" + (f"?{query}" if query else "")
    parts = [f"host={host}", "dbname=app", "user=alice", f"password={PASSWORD}"]
    parts += [f"{k}={v}" for k, v in extra.items()]
    return " ".join(parts)


class RecordingPing:
    def __init__(self) -> None:
        self.calls: list[tuple[str, float]] = []

    def __call__(self, target: str, timeout: float) -> None:
        self.calls.append((target, timeout))


class ProbeHostCase(unittest.TestCase):
    def probe(self, value: str) -> tuple[ProbeResult, RecordingPing]:
        ping = RecordingPing()
        result = probe_credential("postgres", {"dsn": value}, sql_ping=ping, resolve_host=resolve)
        return result, ping

    def assert_refused(self, value: str, *words: str) -> ProbeResult:
        result, ping = self.probe(value)
        self.assertFalse(result.ok, result)
        self.assertTrue(result.detail.startswith(POSTGRES_PROBE_REFUSAL), result.detail)
        for word in words:
            self.assertIn(word, result.detail)
        self.assertEqual(ping.calls, [], f"{value!r} was dialled")
        self.assertNotIn(PASSWORD, result.detail)
        return result


class LoopbackTests(ProbeHostCase):
    def test_loopback_literals_and_names_are_refused_before_the_dial(self) -> None:
        for host in ("127.0.0.1", "127.1.2.3", "[::1]", "[::ffff:127.0.0.1]", "localhost", "db.localhost", "LOCALHOST."):
            with self.subTest(host=host):
                self.assert_refused(dsn(host), "loopback")

    def test_a_name_that_resolves_to_loopback_is_refused(self) -> None:
        self.assert_refused(dsn("loop.example.test"), "resolves to a loopback address")

    def test_the_key_value_spelling_is_refused_too(self) -> None:
        self.assert_refused(dsn("127.0.0.1", scheme=False), "loopback")


class PrivateTests(ProbeHostCase):
    def test_private_literals_are_refused_before_the_dial(self) -> None:
        for host in ("10.0.0.5", "172.16.0.1", "172.31.255.254", "192.168.1.10", "[fd00::1]", "[::ffff:10.0.0.5]"):
            with self.subTest(host=host):
                self.assert_refused(dsn(host), "private")

    def test_a_name_that_resolves_to_a_private_address_is_refused(self) -> None:
        self.assert_refused(dsn("internal.example.test"), "resolves to a private address")

    def test_one_private_answer_among_public_ones_is_enough_to_refuse(self) -> None:
        self.assert_refused(dsn("mixed.example.test"), "private")

    def test_a_private_hostaddr_is_refused_even_beside_a_public_host(self) -> None:
        self.assert_refused(dsn("db.example.test", hostaddr="10.0.0.1"), "private")


class LinkLocalTests(ProbeHostCase):
    def test_link_local_literals_are_refused_before_the_dial(self) -> None:
        for host in ("169.254.169.254", "169.254.0.1", "[fe80::1]"):
            with self.subTest(host=host):
                self.assert_refused(dsn(host), "link-local")

    def test_a_name_that_resolves_to_the_metadata_endpoint_is_refused(self) -> None:
        self.assert_refused(dsn("metadata.example.test"), "resolves to a link-local address")


class NonPublicTests(ProbeHostCase):
    def test_unspecified_multicast_reserved_and_shared_ranges_are_refused(self) -> None:
        for host in ("0.0.0.0", "224.0.0.1", "240.0.0.1", "100.64.0.1", "[::]"):
            with self.subTest(host=host):
                self.assert_refused(dsn(host), "non-public")

    def test_a_name_that_resolves_to_a_shared_range_is_refused(self) -> None:
        self.assert_refused(dsn("cgnat.example.test"), "resolves to a non-public address")


class NoDialableHostTests(ProbeHostCase):
    """The shapes that are not an address class but would still dial inward."""

    def test_a_dsn_naming_no_host_is_refused(self) -> None:
        for value in ("postgresql:///app", f"dbname=app user=alice password={PASSWORD}"):
            with self.subTest(dsn=value):
                self.assert_refused(value, "names no host")

    def test_a_unix_socket_path_is_refused(self) -> None:
        self.assert_refused(dsn("/var/run/postgresql", scheme=False), "Unix socket")

    def test_an_unresolvable_name_is_refused_rather_than_dialled(self) -> None:
        self.assert_refused(dsn("nowhere.example.test"), "could not be resolved")
        self.assert_refused(dsn("empty.example.test"), "could not be resolved")

    def test_a_malformed_dsn_is_a_refusal_not_an_exception(self) -> None:
        result, ping = self.probe("postgresql://[bad")
        self.assertFalse(result.ok)
        self.assertIn("could not be parsed", result.detail)
        self.assertEqual(ping.calls, [])

    def test_a_multi_host_dsn_with_one_private_host_is_refused(self) -> None:
        self.assert_refused(dsn("db.example.test,10.0.0.5"), "private")


class PublicHostTests(ProbeHostCase):
    """The dial happens, and it happens to the address that was vetted."""

    def test_a_public_name_is_dialled_with_hostaddr_pinned(self) -> None:
        result, ping = self.probe(dsn("db.example.test"))
        self.assertTrue(result.ok, result)
        self.assertEqual(len(ping.calls), 1)
        target, timeout = ping.calls[0]
        params = conninfo_to_dict(target)
        self.assertEqual(params["host"], "db.example.test")
        self.assertEqual(params["hostaddr"], PUBLIC_V4)
        self.assertEqual(params["password"], PASSWORD)
        self.assertEqual(timeout, 5.0)

    def test_public_literals_are_dialled_as_themselves(self) -> None:
        for host, expected in (("8.8.8.8", "8.8.8.8"), (f"[{PUBLIC_V6}]", PUBLIC_V6)):
            with self.subTest(host=host):
                result, ping = self.probe(dsn(host))
                self.assertTrue(result.ok, result)
                self.assertEqual(conninfo_to_dict(ping.calls[0][0])["hostaddr"], expected)

    def test_a_dsn_that_already_pins_a_public_hostaddr_is_dialled_unchanged(self) -> None:
        value = dsn("db.example.test", hostaddr=PUBLIC_V4)
        result, ping = self.probe(value)
        self.assertTrue(result.ok, result)
        self.assertEqual(ping.calls, [(value, 5.0)])

    def test_two_public_hosts_are_pinned_in_order(self) -> None:
        result, ping = self.probe(dsn("db.example.test,db6.example.test"))
        self.assertTrue(result.ok, result)
        params = conninfo_to_dict(ping.calls[0][0])
        self.assertEqual(params["host"], "db.example.test,db6.example.test")
        self.assertEqual(params["hostaddr"], f"{PUBLIC_V4},{PUBLIC_V6}")

    def test_a_failing_dial_is_scrubbed_of_the_dsn_and_the_pinned_target(self) -> None:
        def failing(target: str, _timeout: float) -> None:
            raise RuntimeError(f"connection refused for {target}")

        result = probe_credential(
            "postgres", {"dsn": dsn("db.example.test")}, sql_ping=failing, resolve_host=resolve
        )
        self.assertFalse(result.ok)
        self.assertIn("SELECT 1 failed", result.detail)
        self.assertNotIn(PASSWORD, result.detail)

    def test_the_target_function_answers_none_for_a_public_host(self) -> None:
        refusal, target = postgres_probe_target(dsn("db.example.test"), resolve)
        self.assertIsNone(refusal)
        self.assertEqual(conninfo_to_dict(target)["hostaddr"], PUBLIC_V4)


@unittest.skipUnless(FASTAPI_AVAILABLE, "FastAPI service extra is not installed")
class ThroughTheRouteTests(AuthenticatedTwoUserCase):
    """The route reaches the vetting with its defaults, and a literal needs no DNS."""

    def test_a_loopback_dsn_is_refused_over_http_without_dialling_or_resolving(self) -> None:
        ping = RecordingPing()

        def no_dns(host: str) -> list[str]:
            raise AssertionError(f"DNS was consulted for the literal {host!r}")

        mine = self.create_credential(
            self.as_alice(), kind="postgres", label="local pg", fields={"dsn": dsn("127.0.0.1")}
        )["id"]
        with (
            patch("brief_crew.service.credentials._default_sql_ping", ping),
            patch("brief_crew.service.credentials._default_resolve_host", no_dns),
        ):
            response = self.client.post(f"{CREDENTIALS}/{mine}/test", headers=self.as_alice())

        self.assertEqual(response.status_code, 200, response.text)
        body: dict[str, Any] = response.json()
        self.assertFalse(body["ok"])
        self.assertIn("loopback", body["detail"])
        self.assertEqual(ping.calls, [])
        self.assertNotIn(PASSWORD, response.text)

    def test_a_public_dsn_reaches_the_dial_over_http(self) -> None:
        ping = RecordingPing()
        mine = self.create_credential(
            self.as_alice(), kind="postgres", label="remote pg", fields={"dsn": dsn("db.example.test")}
        )["id"]
        with (
            patch("brief_crew.service.credentials._default_sql_ping", ping),
            patch("brief_crew.service.credentials._default_resolve_host", resolve),
        ):
            response = self.client.post(f"{CREDENTIALS}/{mine}/test", headers=self.as_alice())

        self.assertEqual(response.status_code, 200, response.text)
        self.assertTrue(response.json()["ok"], response.text)
        self.assertEqual(len(ping.calls), 1)
        self.assertEqual(conninfo_to_dict(ping.calls[0][0])["hostaddr"], PUBLIC_V4)


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
