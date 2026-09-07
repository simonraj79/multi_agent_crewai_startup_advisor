"""Audit L2: an auth origin that is not https cannot be trusted with the JWKS.

``_assert_auth_startup_safety`` refuses to boot a deployment that requires
authentication against a cleartext ``AUTH_BASE_URL``; loopback over plain http
stays allowed for a developer's own machine.
"""

from __future__ import annotations

import unittest
from unittest import mock

from brief_crew import config as project_config
from brief_crew.service import app as app_module


class AuthOriginSchemeTests(unittest.TestCase):
    def _boot(self, base_url: str) -> None:
        with mock.patch.object(project_config, "VALIDATOR_REQUIRE_AUTH", True), mock.patch.object(
            project_config, "AUTH_BASE_URL", base_url
        ), mock.patch.object(project_config, "CORS_ALLOW_ORIGINS", ("https://console.example.test",)):
            app_module._assert_auth_startup_safety()

    def test_https_is_accepted(self) -> None:
        self._boot("https://auth.example.test")

    def test_plain_http_on_a_real_host_is_refused(self) -> None:
        with self.assertRaises(RuntimeError) as caught:
            self._boot("http://auth.example.test")
        self.assertIn("must be https", str(caught.exception))
        self.assertIn("http://auth.example.test", str(caught.exception))

    def test_plain_http_on_loopback_is_allowed(self) -> None:
        for origin in ("http://localhost:5173", "http://127.0.0.1:3000"):
            with self.subTest(origin=origin):
                self._boot(origin)

    def test_the_predicate_alone(self) -> None:
        trustworthy = app_module.auth_base_url_is_trustworthy
        self.assertTrue(trustworthy("https://x.example"))
        self.assertTrue(trustworthy("http://localhost"))
        self.assertFalse(trustworthy("http://x.example"))
        self.assertFalse(trustworthy("ftp://x.example"))
        self.assertFalse(trustworthy("auth.example.test"))

    def test_not_required_means_not_checked(self) -> None:
        with mock.patch.object(project_config, "VALIDATOR_REQUIRE_AUTH", False), mock.patch.object(
            project_config, "AUTH_BASE_URL", "http://auth.example.test"
        ):
            app_module._assert_auth_startup_safety()


if __name__ == "__main__":
    unittest.main()
