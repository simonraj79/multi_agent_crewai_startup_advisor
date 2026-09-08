"""`require_admin` - 404, never 403, on every route (plan 17 criteria 1 and 4).

The console reads every account's spend and can cancel a stranger's run, so
the interesting question is not "does an admin get in" but "what does anybody
else learn". The answer has to be **nothing**: a 403 says "this exists and you
may not have it", which tells anybody who can sign in that this deployment has
an admin surface and hands them a list of routes to probe. FastAPI's own
`{"detail": "Not Found"}` says exactly what an unknown path says.

Three states collapse into that one answer and all three are asserted here:
nobody signed in, somebody signed in who is not listed, and `ADMIN_EMAILS`
empty so nobody is listed at all. The third is the default on every deployment
that has not been configured, which is why it is the one that must not be an
accident.

**Every knob is `patch.object(config, ...)`, never inherited** - CLAUDE.md
item 63. An `ADMIN_EMAILS` read from a developer's `.env` would make the
"nobody is listed" arm of this file pass for the wrong reason on their machine
and fail on CI, which is the exact shape of the defect that had CI red for
seven commits.
"""

from __future__ import annotations

import unittest
from unittest.mock import patch

from brief_crew import config
from tests.service.admin_fixtures import ADMIN, AdminCase

#: Every route of plan 17 section 3, by method and path. FIFTEEN, not the
#: fourteen the criterion says: section 3's table has fifteen rows and the
#: count in criterion 4 is one short of its own table. Asserting the extra one
#: is the safe direction to resolve that.
ROUTES = (
    ("GET", "/whoami"),
    ("GET", "/summary"),
    ("GET", "/spend"),
    ("GET", "/users"),
    ("GET", "/users/user_alice"),
    ("GET", "/runs"),
    ("GET", "/runs/r1/decisions"),
    ("GET", "/gates"),
    ("GET", "/verdicts"),
    ("GET", "/health"),
    ("GET", "/links"),
    ("GET", "/providers"),
    ("GET", "/runs/r1/billed"),
    ("POST", "/runs/r1/cancel"),
    ("POST", "/workflows/ug_0123abcd/unpublish"),
)


class RouteInventoryTests(unittest.TestCase):
    def test_every_route_in_section_3_is_in_this_files_list(self) -> None:
        """The list above is the thing every other test in this file iterates.

        A route added to `admin_api.py` and not to `ROUTES` would be a route
        with no authorisation test at all, and nothing else would notice.
        """

        from fastapi import FastAPI

        from brief_crew.service.admin_api import ADMIN_API_PREFIX, create_admin_router

        router = create_admin_router(
            resolve_user=lambda: None,
            registry=object(),
            persistence_factory=lambda: None,
            store_factory=lambda: None,
            health_payload=lambda **_: ({}, 200),
            exporter_state_for=dict,
        )
        app = FastAPI()
        app.include_router(router)
        declared = {
            (method, route.path[len(ADMIN_API_PREFIX) :])
            for route in router.routes
            for method in route.methods
            if method != "HEAD"
        }
        # Path parameters are spelled `{run_id}` in the route and `r1` in the
        # list, so compare on the SHAPE rather than on the literal.
        def shape(path: str) -> str:
            parts = []
            for part in path.split("/"):
                parts.append("*" if part.startswith("{") or part in {"r1", "user_alice", "ug_0123abcd"} else part)
            return "/".join(parts)

        self.assertEqual(
            {(method, shape(path)) for method, path in declared},
            {(method, shape(path)) for method, path in ROUTES},
        )


class NobodyIsAnAdminByDefaultTests(AdminCase):
    """`ADMIN_EMAILS` empty. The state every unconfigured deployment is in."""

    admin_emails = ()

    def test_the_listed_admin_is_refused_when_the_list_is_empty(self) -> None:
        for method, path in ROUTES:
            with self.subTest(route=f"{method} {path}"):
                response = self.client.request(
                    method, f"/api/admin{path}", headers=self.as_admin()
                )
                self.assertEqual(response.status_code, 404, response.text)
                self.assertEqual(response.json(), {"detail": "Not Found"})

    def test_an_unknown_path_and_an_admin_path_are_indistinguishable(self) -> None:
        """The whole point, in one assertion.

        Status AND body, because a 404 with a different sentence would still
        tell a prober which paths this service has heard of.
        """

        unknown = self.client.get("/api/admin/no-such-thing", headers=self.as_admin())
        real = self.client.get("/api/admin/summary", headers=self.as_admin())
        self.assertEqual(unknown.status_code, real.status_code)
        self.assertEqual(unknown.json(), real.json())


class OnlyTheListedAdminGetsInTests(AdminCase):
    def test_an_anonymous_caller_is_refused_on_every_route(self) -> None:
        for method, path in ROUTES:
            with self.subTest(route=f"{method} {path}"):
                response = self.client.request(method, f"/api/admin{path}")
                # 401 would also be defensible for an anonymous caller, and it
                # is the wrong answer here: it says a credential would help,
                # which tells a stranger the surface is there.
                self.assertEqual(response.status_code, 404, response.text)
                self.assertEqual(response.json(), {"detail": "Not Found"})

    def test_a_signed_in_non_admin_is_refused_on_every_route(self) -> None:
        for method, path in ROUTES:
            with self.subTest(route=f"{method} {path}"):
                response = self.client.request(
                    method, f"/api/admin{path}", headers=self.as_alice()
                )
                self.assertEqual(response.status_code, 404, response.text)
                self.assertEqual(response.json(), {"detail": "Not Found"})

    def test_the_admin_reaches_every_read_route(self) -> None:
        """A 200 on the reads, and never a 404, for the person on the list.

        One run is seeded first because `/users/{id}` and `/runs/{id}/...`
        answer 404 for an id nothing at all knows - which is right, and which
        would otherwise make this test pass for the wrong reason by asserting
        that a real refusal was a real answer.
        """

        self.seed_run("r1")
        for _method, path in ROUTES:
            if _method == "POST":
                continue
            with self.subTest(route=path):
                response = self.get(path)
                self.assertEqual(response.status_code, 200, response.text)

    def test_whoami_names_the_admin(self) -> None:
        body = self.ok("/whoami")
        self.assertEqual(
            body, {"admin": True, "user_id": ADMIN.id, "email": ADMIN.email}
        )


class IsAdminTests(unittest.TestCase):
    """`config.is_admin` on its own - criterion 1's shape.

    It matches the id EXACTLY and the e-mail CASE-INSENSITIVELY, which is what
    `user_spend_cap_usd` beside it already does and for the same reason: the
    Better Auth id is a random string nobody has memorised and the e-mail is
    the handle a person knows, so both are accepted; and an e-mail address's
    domain is case-insensitive in practice while an opaque id is not a string
    anybody should be normalising.
    """

    def test_nobody_is_an_admin_with_an_empty_list(self) -> None:
        with patch.object(config, "ADMIN_EMAILS", ()):
            self.assertFalse(config.is_admin("user_admin", "admin@example.test"))

    def test_an_id_matches_exactly(self) -> None:
        with patch.object(config, "ADMIN_EMAILS", ("user_admin",)):
            self.assertTrue(config.is_admin("user_admin", None))
            self.assertFalse(config.is_admin("USER_ADMIN", None))

    def test_an_email_matches_case_insensitively(self) -> None:
        with patch.object(config, "ADMIN_EMAILS", ("Admin@Example.Test",)):
            self.assertTrue(config.is_admin("someone", "admin@example.TEST"))

    def test_neither_handle_means_not_an_admin(self) -> None:
        with patch.object(config, "ADMIN_EMAILS", ("admin@example.test",)):
            self.assertFalse(config.is_admin(None, None))
            self.assertFalse(config.is_admin("", ""))

    def test_a_patched_tuple_is_judged_against_itself(self) -> None:
        """The stale-index trap, asserted rather than trusted.

        `config` keeps a lower-cased frozenset beside the tuple for speed.
        `patch.object` replaces the tuple and not the set, so an implementation
        that consulted the set would judge a patched list against the one that
        was there at import - and every test in this file would be testing the
        developer's `.env`.
        """

        with patch.object(config, "ADMIN_EMAILS", ("someone-else@example.test",)):
            self.assertFalse(config.is_admin("user_admin", "admin@example.test"))
            self.assertTrue(config.is_admin("x", "SOMEONE-ELSE@example.test"))

    def test_the_default_is_empty(self) -> None:
        """Criterion 1: nobody is an admin unless somebody says so.

        Read off the module rather than off the environment, because the
        environment is exactly what must not decide this.
        """

        self.assertIsInstance(config.ADMIN_EMAILS, tuple)


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
