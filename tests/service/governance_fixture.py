"""Serve an isolated, no-cost admin evidence fixture for browser verification.

    python -m tests.service.governance_fixture

Bind only to loopback. Uses an in-memory database and synthetic runners; the
shared AdminCase clears provider credentials before creating the application.
"""

from brief_crew import config
from tests.service.admin_fixtures import AdminCase


def main() -> None:
    import uvicorn

    fixture = AdminCase()
    fixture.setUp()
    try:
        # The Vite E2E proxy supplies this identity. These overrides are confined
        # to this explicitly synthetic process, after dotenv has been loaded.
        config.AUTH_BASE_URL = ""
        config.VALIDATOR_REQUIRE_AUTH = False
        config.ADMIN_EMAILS = ("e2e-user@synthetic",)
        for workflow in ("evidence-review", "quiet-review"):
            for index in range(3):
                run_id = f"{workflow}-{index}"
                fixture.seed_run(
                    run_id,
                    user_id="e2e-user",
                    workflow_id=workflow,
                    status="completed",
                    age_hours=index + 1,
                    cost="0.042",
                )
                fixture.seed_frame(run_id, kind="agent", node_id="draft")
                if workflow == "evidence-review" and index < 2:
                    fixture.seed_frame(
                        run_id,
                        seq=2,
                        kind="guardrail",
                        node_id="draft",
                        details={"stage": "after", "retry_count": 1, "success": True},
                    )
                    fixture.seed_gate(
                        run_id,
                        gate_id="editor-review",
                        node_id="review",
                        decision="revise",
                        note="Add sources before approval",
                    )
                    # Opening a durable gate changes the run to waiting. This
                    # fixture represents history after the resumed run ended.
                    fixture.store.update_run_status(run_id, "completed")
        fixture.seed_run("sparse-review-0", workflow_id="sparse-review")
        uvicorn.run(fixture.app, host="127.0.0.1", port=8109, log_level="warning")
    finally:
        fixture.doCleanups()


if __name__ == "__main__":
    main()
