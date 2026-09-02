"""Put published builder graphs back into the registration maps at boot.

Spec section 8.1 item 5, and the same class of defect as remaining-work item
32. A publish writes to six places, every one of them process-local: the four
module dicts in `service/graph.py`, `config.register_workflow_reserved_run_input_keys`,
and the registry's own runtime map. The document that caused those writes is in
the database. So a restart left the two disagreeing, with only the dead half
consulted - `builder_documents.status` still said `published`, the author's
canvas still said `published`, and `POST /api/sessions/{id}/runs` answered
**404** for a graph they had published an hour before. Both Render services
carry `autoDeploy: yes`, which makes that every push to `main`.

`BuilderDocumentStore.published()` was written for exactly this seam and had
zero callers. This module is its caller.

**Three refusals, and each one is a decision rather than defensiveness.**

* **A row that no longer compiles is skipped, not fatal.** Bounds move -
  `MAX_BILLABLE_NODES` and `MAX_ESCALATION_NODES` both carry measured
  justifications and both are expected to be raised - and a graph published
  under a laxer set must not be able to stop this process booting. The author
  gets a graph that is no longer launchable, which is honest; everybody else
  gets a service. The skip is logged with the document id and the compiler's
  own sentence, because a graph that silently stops existing is the defect this
  module was written to close, not a smaller version of it to ship.
* **A row that no longer PARSES is skipped too, and used to end the sweep.**
  `published()` re-validates each stored document, and a raise from inside a
  generator CLOSES it - so one graph written under an older `builder.flow/v1`
  took every graph ordered behind it down with it, and they all answered 404
  after the next restart. The order is `updated_at DESC`, so which graphs died
  was arbitrary. The store now catches that per row and hands the id and the
  reason back through `on_skipped`, which lands in `skipped` beside a graph that
  no longer compiles - the two are the same fact to an author.
  `stopped_early` therefore means what it says: the store itself would not
  answer, not that one document was bad.
* **A registry with no workflow map is left alone.** That is the older
  single-workflow shape, which answers for any id from one default runtime, so
  adding an entry would change what every OTHER workflow resolves to.
  `builder_api._register_runtime` refuses that shape by raising, which is right
  for a publish - somebody asked for something this build cannot do. Here it is
  checked once up front and the sweep is a no-op instead, because a dozen test
  modules build exactly that registry and a boot must not raise about one.

Nothing here raises. A boot must not be able to fail because a document store
had a bad day, so every failure becomes a log line and a skipped row - which is
the same rule `RunRegistry.__init__` applies to its own interrupted-run sweep.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
import logging
from typing import Any

from brief_crew.builder.compiler import BuilderCompileError
from brief_crew.builder.descriptor import build_builder_workflow
from brief_crew.builder.store import BuilderDocumentStore, BuilderStoreError
from brief_crew.config import BUILDER_REHYDRATE_PUBLISHED
from brief_crew.service.builder_api import _register_runtime
from brief_crew.service.graph import register_builder_workflow, unregister_builder_workflow
from brief_crew.service.builder_runner import BuilderRunnerFactory
from brief_crew.service.registry import RunRegistry


logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class RehydrationReport:
    """What the boot sweep did, in a shape a test can assert on.

    Returned rather than only logged for the reason the brief gives: the skip
    has to be observable. A caller that wants to surface it can; the log line
    is written either way, and `assertLogs` is not the only way to prove a row
    was dropped.
    """

    #: The workflow ids now registered in all six places.
    registered: tuple[str, ...] = ()
    #: `(document_id, reason)` for each published row that could not be put
    #: back, in the order they were met.
    skipped: tuple[tuple[str, str], ...] = ()
    #: True when the sweep could not read every published row: the store
    #: refused, mid-query or up front. NOT set by a single unreadable document -
    #: that is one entry in `skipped` and the sweep carries on past it, which is
    #: the whole of the repair described in this module's docstring.
    stopped_early: bool = False

    @property
    def attempted(self) -> int:
        return len(self.registered) + len(self.skipped)


def rehydrate_published_workflows(
    *,
    store: BuilderDocumentStore | None,
    registry: RunRegistry,
    runner_factory: BuilderRunnerFactory,
    enabled: bool | None = None,
) -> RehydrationReport:
    """Re-register every published builder graph, skipping what will not compile.

    Called from `create_app` after the registry exists and before the builder
    router mounts, which is the only window where both halves are available and
    nothing has been served yet.

    `runner_factory` is the same callable `create_builder_router` is handed,
    and passing it here rather than resolving it inside is what keeps a
    rehydrated graph and a freshly published one running through identical
    machinery. It is a factory rather than a runner because `RunExecution`
    carries no `workflow_id`: each graph gets its own runner, closed over its
    own compiled definition, and a rehydrated graph must get one built the same
    way or it would come back registered and unrunnable.
    """

    if not (BUILDER_REHYDRATE_PUBLISHED if enabled is None else enabled):
        return RehydrationReport()
    if store is None:
        # No durable store means no documents to read; the builder routes
        # already answer 503 naming that, and there is nothing to reconcile.
        return RehydrationReport()
    if not getattr(registry, "workflows", None):
        logger.debug(
            "builder rehydration skipped: this registry has no workflow map to "
            "register into"
        )
        return RehydrationReport()

    registered: list[str] = []
    skipped: list[tuple[str, str]] = []
    stopped_early = False

    def note_unreadable(document_id: str, reason: str) -> None:
        # How a row the store could not parse becomes an entry in `skipped`
        # rather than the end of the sweep. A callback rather than a return
        # value because `published()` is a generator: anything it reported at
        # the end would arrive long after the rows behind the bad one had
        # already been decided.
        skipped.append((document_id, reason))

    try:
        rows = iter(store.published(on_skipped=note_unreadable))
    except Exception:
        logger.exception("could not read the published builder graphs at startup")
        return RehydrationReport(stopped_early=True)

    while True:
        try:
            stored = next(rows)
        except StopIteration:
            break
        except BuilderStoreError as exc:
            # The generator is closed by this raise, so the rows behind it are
            # unreachable without a second query. Say so instead of reporting a
            # short list as a complete one.
            #
            # A single document that no longer parses does NOT arrive here any
            # more - `published()` skips it per row and reports it through
            # `on_skipped` - so this is the store refusing, and the message says
            # which of the two it is rather than blaming a document that may be
            # perfectly fine.
            logger.error(
                "builder rehydration stopped: the document store refused mid-sweep "
                "and graphs behind that point were not restored. A single document "
                "that no longer parses is skipped and does not reach here: %s",
                exc,
            )
            stopped_early = True
            break
        except Exception:
            logger.exception(
                "builder rehydration stopped: the document store failed mid-sweep"
            )
            stopped_early = True
            break

        outcome = _restore(stored, registry=registry, runner_factory=runner_factory)
        registered.extend(outcome.registered)
        skipped.extend(outcome.skipped)

    if registered:
        logger.info(
            "rehydrated %d published builder graph(s): %s",
            len(registered),
            ", ".join(registered),
        )
    if skipped:
        logger.warning(
            "%d published builder graph(s) could not be restored and are not "
            "launchable until they are edited and republished: %s",
            len(skipped),
            ", ".join(document_id for document_id, _ in skipped),
        )
    return RehydrationReport(
        registered=tuple(registered),
        skipped=tuple(skipped),
        stopped_early=stopped_early,
    )


@dataclass(frozen=True, slots=True)
class _Outcome:
    registered: tuple[str, ...] = ()
    skipped: tuple[tuple[str, str], ...] = ()


def _restore(
    stored: Any, *, registry: RunRegistry, runner_factory: BuilderRunnerFactory
) -> _Outcome:
    """One document, compiled and registered into both halves or neither.

    The rollback mirrors `publish`'s and for the same reason: a workflow left
    in `WORKFLOWS` with no runtime behind it is a 404 on launch that reads as a
    service defect rather than as a graph that could not be restored.
    """

    document_id = getattr(stored, "id", "<unknown>")
    try:
        # The owner comes back with the row (plan 01 D1), so a restart cannot
        # turn somebody's graph into everybody's. No credential check: a boot
        # has no identity, and a credential deleted since publish is the
        # run-time `credential-not-yours`, not a reason to stop booting.
        workflow = build_builder_workflow(
            stored.document, user_id=getattr(stored, "user_id", None)
        )
    except BuilderCompileError as exc:
        logger.warning(
            "builder graph %s no longer compiles and was not re-registered: %s",
            document_id,
            exc,
        )
        return _Outcome(skipped=((document_id, str(exc)),))
    except Exception as exc:  # pragma: no cover - defence, not a known path
        logger.exception("builder graph %s could not be compiled at startup", document_id)
        return _Outcome(skipped=((document_id, str(exc)),))

    register_builder_workflow(workflow)
    try:
        _register_runtime(registry, workflow, runner_factory(workflow))
    except Exception as exc:
        unregister_builder_workflow(workflow.workflow_id)
        logger.exception(
            "builder graph %s compiled but its runtime could not be registered",
            document_id,
        )
        return _Outcome(skipped=((document_id, str(exc)),))
    return _Outcome(registered=(workflow.workflow_id,))


__all__: Sequence[str] = ("RehydrationReport", "rehydrate_published_workflows")
