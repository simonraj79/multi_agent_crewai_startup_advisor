"""One seeded deployment, for every `test_admin_*` module in this package.

The admin console reads eight tables and joins a ninth this repository does
not own, so a test that seeds its own rows in its own file would seed a
slightly different world in each one and the modules would slowly stop
describing the same product. This is that world, once.

TWO RULES THIS MODULE EXISTS TO ENFORCE, both of them CLAUDE.md item 63's:

* **Every knob is patched, never inherited.** `brief_crew/__init__.py` calls
  `load_dotenv(override=True)` and CrewAI's own `load_dotenv` walks up from
  `site-packages` into this repository, so a developer's `.env` reaches a
  worktree that has none. `ADMIN_EMAILS` inherited from a shell would make
  these tests pass locally and fail on CI - or, far worse, pass on CI for the
  wrong reason.
* **No network call is possible.** `AdminCase` clears every upstream key from
  the environment for the duration of the test, so a probe that somehow
  reached its HTTP path would answer `available: false` rather than dial
  OpenRouter with the developer's real key. The probe tests then inject an
  `httpx.MockTransport` on top of that.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from decimal import Decimal
import logging
import os
from typing import Any
import unittest
from unittest.mock import patch

from brief_crew import config
from brief_crew.service.auth import AuthenticatedUser, AuthError

#: The window every seeded row is inside, so a default `?from=`/`?to=` sees
#: all of it and a test can name a narrower one without arithmetic.
NOW = datetime.now(timezone.utc)

ADMIN = AuthenticatedUser(id="user_admin", email="admin@example.test", name="The admin")
ALICE = AuthenticatedUser(id="user_alice", email="alice@example.test", name="Alice")
BOB = AuthenticatedUser(id="user_bob", email="bob@example.test", name="Bob")
TOKENS = {"admin-token": ADMIN, "alice-token": ALICE, "bob-token": BOB}

#: Every upstream credential, cleared for the length of a case. Listed by name
#: rather than clearing the whole environment, because `PATH` and `TEMP` are
#: needed and `DATABASE_URL` is how this suite avoids the main tree's Postgres.
UPSTREAM_KEYS = (
    "OPENROUTER_API_KEY",
    "OPENROUTER_MANAGEMENT_KEY",
    "FIRECRAWL_API_KEY",
    "LANGFUSE_PUBLIC_KEY",
    "LANGFUSE_SECRET_KEY",
)

#: A UUID run id, so `trace_id_for` takes its first branch and the deep link
#: is the hex pairing `docs/observability/evidence/` measured.
RUN_UUID = "073c021f-4ff7-43e1-84d5-d9e8dd7fa0ba"
RUN_TRACE_HEX = "073c021f4ff743e184d5d9e8dd7fa0ba"


class AdminCase(unittest.TestCase):
    """A synthetic app, an admin who can sign in, and nothing inherited.

    `synthetic=True` and `AUTH_BASE_URL` set, with `verify_token` patched to a
    three-entry table - the boundary `tests/service/identities.py` chose, for
    its reason: the cryptography is proved against real Ed25519 signatures in
    `test_admin_auth.py`'s neighbour `test_auth_jwt.py`, and what these tests
    are about is what the routes do with the answer.
    """

    #: Overridden by `test_admin_auth.py`, which needs the empty list.
    admin_emails: tuple[str, ...] = ("admin@example.test",)

    def setUp(self) -> None:
        super().setUp()
        for name in (
            "brief_crew.service.persistence",
            "brief_crew.service.registry",
            "brief_crew.service.admin_api",
        ):
            logger = logging.getLogger(name)
            previous = logger.level
            logger.setLevel(logging.CRITICAL)
            self.addCleanup(logger.setLevel, previous)

        def fake_verify(token: str, **_: object) -> AuthenticatedUser:
            try:
                return TOKENS[token]
            except KeyError as exc:
                raise AuthError("token is not valid") from exc

        cleared = {name: "" for name in UPSTREAM_KEYS}
        for item in (
            patch.object(config, "AUTH_BASE_URL", "https://auth.example.test"),
            patch.object(config, "VALIDATOR_REQUIRE_AUTH", True),
            patch.object(config, "CREDENTIALS_MASTER_KEY", _master_key()),
            patch.object(config, "ADMIN_EMAILS", self.admin_emails),
            patch.object(config, "LANGFUSE_PROJECT_ID", ""),
            patch.object(config, "VALIDATOR_RUN_RETENTION_DAYS", 0),
            patch("brief_crew.service.app.verify_token", fake_verify),
            # NO upstream key reaches a probe from this process, whatever is
            # in the developer's `.env`.
            patch.dict(os.environ, cleared),
        ):
            item.start()
            self.addCleanup(item.stop)

        from fastapi.testclient import TestClient

        from brief_crew.service.app import create_app

        self.app = create_app(
            synthetic=True, database_url="sqlite+pysqlite:///:memory:"
        )
        self.client = TestClient(self.app)
        self.addCleanup(self.client.close)
        self.registry = self.app.state.run_registry
        self.store = self.registry.persistence

    # -- the callers --------------------------------------------------------

    @staticmethod
    def auth(token: str) -> dict[str, str]:
        return {"Authorization": f"Bearer {token}"}

    def as_admin(self) -> dict[str, str]:
        return self.auth("admin-token")

    def as_alice(self) -> dict[str, str]:
        return self.auth("alice-token")

    def get(self, path: str, **kwargs: Any) -> Any:
        return self.client.get(f"/api/admin{path}", headers=self.as_admin(), **kwargs)

    def ok(self, path: str, **kwargs: Any) -> dict[str, Any]:
        response = self.get(path, **kwargs)
        self.assertEqual(response.status_code, 200, response.text)
        return response.json()

    # -- the world ----------------------------------------------------------

    def seed_run(
        self,
        run_id: str,
        *,
        user_id: str | None = ALICE.id,
        workflow_id: str = "idea-validator",
        status: str = "completed",
        age_hours: float = 1.0,
        cost: str | None = "0.0500",
        model: str = "openrouter/google/gemini-3.8-flash",
        node_id: str = "scope_idea",
        error: str | None = None,
        mode: str | None = None,
        max_cost_usd: float | None = None,
        account_cap_usd: float | None = None,
        tokens: int = 1000,
    ) -> str:
        """One run, its node metrics and its terminal status.

        `cost=None` seeds a run with NO `run_node_metrics` row at all, which
        criterion 5 asks for by name: the run has to cost `0` rather than
        disappear from a `JOIN`.
        """

        created = NOW - timedelta(hours=age_hours)
        self.store.create_run(
            run_id=run_id,
            session_id="admin-tests",
            workflow_id=workflow_id,
            graph_version="v1",
            inputs={"idea": "a scheduling assistant for clinics"},
            user_id=user_id,
            status="queued",
            created_at=created,
            mode=mode,
            max_cost_usd=max_cost_usd,
            ceiling_kind="account" if account_cap_usd is not None else None,
            account_cap_usd=account_cap_usd,
        )
        if cost is not None:
            self.store.save_node_metrics(
                run_id,
                node_id,
                model=model,
                cost_usd=Decimal(cost),
                total_tokens=tokens,
                prompt_tokens=int(tokens * 0.8),
                completion_tokens=tokens - int(tokens * 0.8),
                call_count=2,
            )
        self.store.update_run_status(
            run_id,
            status,
            started_at=created + timedelta(seconds=1),
            completed_at=created + timedelta(seconds=61),
            error=error,
        )
        return run_id

    def seed_gate(
        self,
        run_id: str,
        gate_id: str = "scope-confirmation",
        *,
        node_id: str = "confirm_scope",
        decision: str | None = "approve",
        seconds: float = 120.0,
        age_hours: float = 1.0,
        note: str = "the segment is right, go on",
    ) -> None:
        opened = NOW - timedelta(hours=age_hours)
        self.store.open_gate(
            run_id,
            gate_id,
            node_id=node_id,
            request={"title": "Confirm the scope"},
            opened_at=opened,
        )
        if decision is not None:
            self.store.answer_gate(
                run_id,
                gate_id,
                outcome="answered",
                response={"decision": decision, "fields": {"note": note}},
                answered_at=opened + timedelta(seconds=seconds),
            )

    def seed_frame(
        self,
        run_id: str,
        *,
        seq: int = 1,
        kind: str = "verdict",
        details: dict[str, Any] | None = None,
        node_id: str = "review_verdict",
    ) -> None:
        from brief_crew.events import FrameData, FrameKind, FrameLevel, UIEventType

        self.store.append_frames(
            run_id,
            [
                FrameData(
                    seq=seq,
                    run_id=run_id,
                    ts=NOW - timedelta(minutes=30),
                    kind=FrameKind(kind),
                    event_type=UIEventType.WORKFLOW_END,
                    level=FrameLevel.INFO,
                    node_id=node_id,
                    message="a frame",
                    details=details or {},
                )
            ],
        )


def _master_key() -> str:
    """A real 32-byte key, minted per process - audit L4's rule.

    The published placeholder is refused at boot whenever `AUTH_BASE_URL` is
    set, and every case here sets it.
    """

    from tests.service.identities import TEST_MASTER_KEY

    return TEST_MASTER_KEY
