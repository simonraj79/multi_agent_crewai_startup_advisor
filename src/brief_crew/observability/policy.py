"""What the exporter is allowed to send, and where it sends it.

One frozen object, built once from `brief_crew.config`, carried by everything
else in this package. It exists so that every policy question has exactly one
answer readable in one place: a reviewer asking "does this run send prompt
text?" reads `capture_content`, not a chain of `os.getenv` calls scattered
through a state machine.

**The one switch the orchestrator may flip.**
`emit_successful_generations` is the REPLACE/SUPPLEMENT decision, and it is a
single boolean on purpose. Under REPLACE (the default, and what is built here)
this application emits every observation itself, including a GENERATION for
every model call, successful or failed. Under SUPPLEMENT the LLM provider's own
integration emits the successful ones and this exporter emits only the failures
- which is `emit_successful_generations = False` and nothing else. No other
line of this package changes.
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from typing import Mapping

from brief_crew import config as project_config


#: Langfuse's `environment` accepts lowercase letters, digits, hyphen and
#: underscore, and refuses anything starting with `langfuse`. Both values this
#: package can produce satisfy that; an operator override is bounded to the
#: same shape below rather than trusted.
_ENVIRONMENT_ALPHABET = set("abcdefghijklmnopqrstuvwxyz0123456789-_")

ENVIRONMENT_SYNTHETIC = "synthetic"
ENVIRONMENT_LIVE = "live"


def _clean_environment(value: str, fallback: str) -> str:
    lowered = value.strip().lower()
    if not lowered or lowered.startswith("langfuse"):
        return fallback
    if any(character not in _ENVIRONMENT_ALPHABET for character in lowered):
        return fallback
    return lowered[:40]


@dataclass(frozen=True, slots=True)
class ExporterPolicy:
    """Everything the exporter reads that is not a frame."""

    public_key: str = ""
    secret_key: str = ""
    base_url: str = "https://cloud.langfuse.com"
    enabled: bool = False
    #: `synthetic` when the run used the no-cost doubles, else `live`.
    environment: str = ENVIRONMENT_LIVE
    #: Contract section 8. False means fingerprints and counts only.
    capture_content: bool = False
    #: Contract section 4, and never on a synthetic run whatever it says.
    resolve_billed_cost: bool = True
    queue_capacity: int = 4096
    flush_interval_seconds: float = 0.25
    http_timeout_seconds: float = 5.0
    batch_max_events: int = 64
    max_billed_lookups_per_run: int = 64
    lookup_workers: int = 4
    billed_lookup_deadline_seconds: float = 3.0
    #: The REPLACE/SUPPLEMENT switch. See the module docstring.
    emit_successful_generations: bool = True
    #: Strings that must never leave the process even under `capture_content`,
    #: compared and never logged. Populated from the process's own credential
    #: environment variables; see `content.py`.
    secret_values: tuple[str, ...] = field(default=())

    @property
    def synthetic(self) -> bool:
        return self.environment == ENVIRONMENT_SYNTHETIC

    @property
    def host(self) -> str:
        return self.base_url.rstrip("/")

    @property
    def usable(self) -> bool:
        """Whether there is anything to send to, and permission to send it."""
        return bool(self.enabled and self.public_key and self.secret_key and self.base_url)

    def reason_unusable(self) -> str:
        """One sentence for the single startup line, naming no value."""
        if not self.enabled:
            return "LANGFUSE_EXPORT_ENABLED is off"
        missing = [
            name
            for name, value in (
                ("LANGFUSE_PUBLIC_KEY", self.public_key),
                ("LANGFUSE_SECRET_KEY", self.secret_key),
                ("LANGFUSE_BASE_URL", self.base_url),
            )
            if not value
        ]
        if missing:
            return f"{', '.join(missing)} is empty"
        return "no reason recorded"

    def with_overrides(self, **changes: object) -> ExporterPolicy:
        return replace(self, **changes)  # type: ignore[arg-type]


def policy_from_config(
    *,
    synthetic: bool,
    overrides: Mapping[str, object] | None = None,
) -> ExporterPolicy:
    """Build the policy from `config.py` and the caller's synthetic flag.

    `synthetic` is the app's, not the environment's: `create_app(synthetic=True)`
    swaps in the no-cost doubles for the whole process, and every run it serves
    is therefore fabricated. It marks the trace rather than disabling the
    exporter, because that path is the only one that can be exercised without
    spending money and is where this package is proved.
    """

    from brief_crew.observability.content import credential_values_in_environment

    derived = ENVIRONMENT_SYNTHETIC if synthetic else ENVIRONMENT_LIVE
    policy = ExporterPolicy(
        public_key=project_config.LANGFUSE_PUBLIC_KEY,
        secret_key=project_config.LANGFUSE_SECRET_KEY,
        base_url=project_config.LANGFUSE_BASE_URL,
        enabled=bool(project_config.LANGFUSE_EXPORT_ENABLED),
        environment=_clean_environment(project_config.LANGFUSE_ENVIRONMENT, derived),
        capture_content=bool(project_config.LANGFUSE_CAPTURE_CONTENT),
        resolve_billed_cost=bool(project_config.LANGFUSE_RESOLVE_BILLED_COST),
        queue_capacity=int(project_config.LANGFUSE_QUEUE_CAPACITY),
        flush_interval_seconds=float(project_config.LANGFUSE_FLUSH_INTERVAL_SECONDS),
        http_timeout_seconds=float(project_config.LANGFUSE_HTTP_TIMEOUT_SECONDS),
        batch_max_events=int(project_config.LANGFUSE_BATCH_MAX_EVENTS),
        max_billed_lookups_per_run=int(
            project_config.LANGFUSE_MAX_BILLED_LOOKUPS_PER_RUN
        ),
        lookup_workers=int(project_config.LANGFUSE_LOOKUP_WORKERS),
        billed_lookup_deadline_seconds=float(
            project_config.LANGFUSE_BILLED_LOOKUP_DEADLINE_SECONDS
        ),
        secret_values=credential_values_in_environment(),
    )
    if overrides:
        policy = policy.with_overrides(**overrides)
    return policy
