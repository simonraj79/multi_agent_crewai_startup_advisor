"""The run label: three words, an optional note, and two doors onto one write.

Plan 20. `main` had no human label anywhere - the only durable human signal is
a gate reply, which says what somebody accepted *mid-run*, and the only
automatic Langfuse score is `guardrail_passed`, which says what a machine
checked. Neither answers *was this run any good*, and without that answer a
run is useful only to itself.

WHAT LIVES HERE AND WHY IT IS NOT IN `admin_api.py`
---------------------------------------------------
Two routes write a rating - the owner's `PUT /api/runs/{id}/rating` in
`app.py` and the admin's `PUT /api/admin/runs/{id}/rating` below - and the one
thing that must never differ between them is what a write DOES: what clearing
means, what the note is bounded at, what reaches Langfuse. `write_rating` is
that single implementation, and both doors call it. Putting it in `app.py`
would make `admin_api.py` import from `app.py`, which is the cycle this
package has carefully not had; putting it in `admin_api.py` would make the
owner's own route depend on the admin console.

FOUR RULES, ALL OF THEM ALREADY THIS REPOSITORY'S
-------------------------------------------------
* **404, never 403.** The admin route depends on `auth.require_admin` - the
  same function `admin_api`'s gate calls, imported and not re-typed - so it
  answers FastAPI's own unknown-route body to everybody else. The owner route
  is `require_own_run`, which makes the same call for the same reason: a 403
  confirms the run exists.
* **Last writer wins.** No compare-and-set. `persistence.set_run_rating`'s
  docstring carries the argument; the short version is that a 409 on a double
  click would refuse with nothing to protect.
* **Telemetry never fails the button.** `record_run_score` returns a bool the
  route ignores. A rating is a person pressing a button and Langfuse being
  down is not a reason that button reports an error.
* **The note is content.** It leaves the process only under
  `LANGFUSE_CAPTURE_CONTENT`, decided inside `observability/scores.py` and
  not here.

NO `from __future__ import annotations` here, for the reason `builder_api.py`
and `admin_api.py` both give: FastAPI resolves handler annotations against
module globals, and `Depends` is imported inside the factory because FastAPI
is an optional dependency of this package.
"""

from collections.abc import Callable
from datetime import timezone
import logging
from typing import Any
import unicodedata

from pydantic import BaseModel, ConfigDict, Field, field_validator

from brief_crew import config

__all__ = [
    "RATING_VALUES",
    "RatingRequest",
    "RunRatingModel",
    "create_rating_router",
    "rating_payload",
    "write_rating",
]

logger = logging.getLogger(__name__)

#: The three words a rating may be, and nothing else. A fourth is a 422 - a
#: vocabulary the server does not recognise is a client bug, and answering 200
#: to one would store a word no aggregate can count. `unsure` is a real answer
#: and not a missing one, which is why it is here and `null` is not: `null`
#: CLEARS a rating and is the absence of a value rather than a fourth one.
RATING_VALUES: tuple[str, ...] = ("good", "bad", "unsure")


class RunRatingModel(BaseModel):
    """What every rating route answers, whichever door it came in by."""

    model_config = ConfigDict(extra="forbid")

    run_id: str
    rating: str | None = None
    rating_note: str | None = None
    rated_by: str | None = None
    rated_at: str | None = None


class RatingRequest(BaseModel):
    """`{"rating": "good|bad|unsure|null", "note": "<=500"}`.

    Four accepted values and a fifth is a 422, because a rating vocabulary
    the server does not recognise is a client bug and answering 200 to one
    would store a word nothing can aggregate. `null` CLEARS the rating - it is
    not a fourth value, it is the absence of one, and a person who rates by
    accident needs a way back.
    """

    model_config = ConfigDict(extra="forbid")

    rating: str | None = Field(default=None)
    #: NO `max_length` here, deliberately: a `Field` constraint runs BEFORE
    #: the validator below, so the bound would have been applied to the raw
    #: string and the re-check after stripping could never fire - dead code
    #: guarding nothing. The bound lives in `_printable_note`, where it is
    #: applied to the value that will actually be stored. The whole request
    #: body is capped at `MAX_REQUEST_BODY_BYTES` above this, so there is no
    #: unbounded string to walk.
    note: str | None = Field(default=None)

    @field_validator("rating")
    @classmethod
    def _known_rating(cls, value: str | None) -> str | None:
        """Only JSON `null` clears. `""` and `"   "` are a 422 (D7).

        An empty string used to be a silent clear, which is the worst of the
        three possible answers: a client with a bug in its form binding wiped
        the person's rating and was told it had succeeded. JSON has a spelling
        for absence and this is not it.
        """

        if value is None:
            return None
        candidate = value.strip().lower()
        if candidate not in RATING_VALUES:
            raise ValueError(
                "rating must be one of " + ", ".join(RATING_VALUES) + ", or null"
            )
        return candidate

    @field_validator("note")
    @classmethod
    def _printable_note(cls, value: str | None) -> str | None:
        """Strip control characters, then re-check the length (D2).

        A `\\x00` in a note reached psycopg as a literal NUL, which PostgreSQL
        cannot store in a `text` value at all: the driver raised, the route
        answered **500**, and the note - user content - was written into the
        server log by the traceback. The class of thing is wider than NUL, so
        this removes every C0/C1 control character rather than that one.

        `\\n` and `\\t` survive: somebody typing a two-line note about a run
        is doing the thing this field exists for. A note that is only control
        characters becomes `None`, because a rating with an empty note is an
        unannotated rating and not a rating with an invisible one.

        This is also where `MAX_RATING_NOTE_CHARS` is enforced, on the CLEANED
        value - see the field above for why it is not a `Field` constraint.
        """

        if value is None:
            return None
        cleaned = "".join(
            character
            for character in value
            if character in "\n\t" or not unicodedata.category(character).startswith("C")
        ).strip()
        if not cleaned:
            return None
        if len(cleaned) > config.MAX_RATING_NOTE_CHARS:
            raise ValueError(
                f"note is limited to {config.MAX_RATING_NOTE_CHARS} characters"
            )
        return cleaned

    def normalised(self) -> str | None:
        return self.rating


def _iso(moment: Any) -> str | None:
    """A datetime as the `Z`-suffixed ISO string the rest of the API uses."""

    if moment is None:
        return None
    if isinstance(moment, str):
        return moment
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=timezone.utc)
    return (
        moment.astimezone(timezone.utc)
        .isoformat(timespec="milliseconds")
        .replace("+00:00", "Z")
    )


def rating_payload(run_id: str, stored: Any) -> RunRatingModel:
    """One stored mapping (or nothing at all) as the wire shape.

    An unrated run answers four nulls rather than 404: "nobody has said" is a
    true answer to "what did they say", and a 404 there would make the client
    branch on a status code to render an empty control.
    """

    row = stored or {}
    return RunRatingModel(
        run_id=run_id,
        rating=row.get("rating"),
        rating_note=row.get("rating_note"),
        rated_by=row.get("rated_by"),
        rated_at=_iso(row.get("rated_at")),
    )


#: The sentence both doors answer for a run that is still going (D4). One
#: string, so the owner's console and the admin drawer cannot disagree about
#: what happened.
NOT_FINISHED_DETAIL = "this run has not finished; rate it when it has"

#: And for a run nobody owns, asked by somebody who IS signed in (D6).
UNOWNED_DETAIL = (
    "this run has no owner, so only an admin can rate it"
)


def guard_run_id(run_id: str) -> str:
    """A run id this service could have written, or a 404.

    `persistence._identifier` raises `ValueError` above 128 characters and the
    route then answered **500** - a shape question turned into a server fault.
    404 is the honest answer: no run of that id exists, and saying so costs
    nothing a stranger did not already know. The sibling run routes have the
    same hole and are deliberately NOT touched here; this guards the two
    routes this plan adds.
    """

    from fastapi import HTTPException

    text = str(run_id).strip()
    if not text or len(text) > _MAX_RUN_ID_CHARS:
        raise HTTPException(status_code=404, detail="run not found")
    return text


#: `persistence._identifier`'s own default limit, which is the bound that was
#: turning a long id into a 500.
_MAX_RUN_ID_CHARS = 128


def guard_rateable(record: Any, *, actor: str | None, is_admin: bool) -> None:
    """The two refusals that are about the RUN rather than about the body.

    **D4 - a run that has not finished is a 409.** The plan's subject is a
    post-hoc judgement of a finished run, and a `waiting` run has not produced
    the thing being judged. `TERMINAL_STATUSES` is IMPORTED from the registry
    rather than retyped: it is the same set the eviction sweep and the
    orphan recovery read, and a second copy would disagree the first time a
    status was added. A CLEAR is refused for the same reason and not a
    different one - there cannot be a rating on a run nobody could have rated.

    **D6 - a run with no owner is written by an admin or by nobody.**
    `builder_api`'s unowned-document rule, applied to runs: an unowned row is
    readable by everyone, so a signed-in caller who tries to write one gets a
    **403 naming the remedy** rather than a 404 - the row is already visible
    to them and pretending otherwise would be a refusal that contradicts the
    page they are looking at. The anonymous caller on an auth-off deployment
    keeps the write, being that deployment's only author; on an
    auth-configured deployment there is no anonymous caller to reach here,
    because `current_user` answers 401 first.
    """

    from fastapi import HTTPException

    from brief_crew.service.registry import TERMINAL_STATUSES

    if getattr(record, "status", None) not in TERMINAL_STATUSES:
        raise HTTPException(status_code=409, detail=NOT_FINISHED_DETAIL)
    if not is_admin and getattr(record, "user_id", None) is None and actor is not None:
        raise HTTPException(status_code=403, detail=UNOWNED_DETAIL)


def write_rating(
    persistence: Any, run_id: str, request: RatingRequest, actor: str | None
) -> RunRatingModel:
    """The one write behind both rating routes.

    One implementation, two doors: the owner's `PUT` and the admin's. A second
    copy of this would be a second answer to "what does clearing a rating do",
    and the answer - the note and the actor go with it - is the kind that
    drifts.

    **Called off the event loop**, by both doors, because everything in it
    blocks: a synchronous database round trip and `record_run_rating`'s
    bounded 2 s join. Measured before the fix: a concurrent `GET /healthz`
    took 2.012 s against 0.112 s. Audit H5's pattern, met a second time.
    """

    from fastapi import HTTPException

    from brief_crew.observability import scores

    rating = request.normalised()
    stored = persistence.set_run_rating(
        run_id,
        rating=rating,
        note=request.note,
        rated_by=actor,
    )
    if stored is None:
        # 404 and not 500: the run is not here, and the route above has
        # already decided the caller is allowed to ask about it.
        raise HTTPException(status_code=404, detail="run not found")

    # ALWAYS, including on a clear - a clear is the delete of the score id,
    # and skipping it is what left a trace saying `good` for a rating the
    # database no longer had. `record_run_rating` owns the id scheme.
    scores.record_run_rating(
        run_id,
        rating,
        # Free text a person typed. The hook writes it only under
        # `LANGFUSE_CAPTURE_CONTENT`; the default is not a denylist.
        comment=request.note,
        # THE SOURCE OF TRUTH, for the deferred half of a clear. A clear is
        # swept twice - now and ~45 s later, because the immediate delete can
        # answer 404 against a create that is still in the SDK's queue - and
        # the second sweep must not delete a rating somebody made in between.
        # So it re-reads this column rather than trusting the decision that
        # armed it: the database is what the trace is a mirror OF.
        still_cleared=lambda: _is_unrated(persistence, run_id),
    )
    return rating_payload(run_id, stored)


def _is_unrated(persistence: Any, run_id: str) -> bool:
    """Whether this run is STILL unrated. A read that fails is a `False`.

    Uncertainty is not a licence to delete: an unreadable store means this
    cannot say nobody re-rated, and the sweep does nothing on anything but a
    plain yes.
    """

    row = persistence.run_ratings([run_id]).get(run_id) or {}
    return row.get("rating") is None


def create_rating_router(
    *,
    resolve_user: Callable[..., Any],
    persistence_factory: Callable[[], Any],
    run_factory: Callable[[str], Any],
) -> Any:
    """The admin's rating lever, under `/api/admin`.

    A router of its own rather than a route on `create_admin_router`, for the
    reason the module docstring gives: the write belongs beside the owner's
    door, not inside the console. It carries the admin prefix so
    `require_admin`'s 404, the CORS middleware, the body limit and the
    client's own `authedFetch` all reach it unchanged.

    `resolve_user` is `optional_user` and NOT `current_user` - plan 17
    criterion 4's rule, restated because it applies here identically: an
    anonymous caller must get the same 404 as a signed-in non-admin, and
    `current_user` would raise 401 first, which makes an admin route
    distinguishable from an unknown path.

    `run_factory` is `app.py`'s own `require_run`, injected rather than
    reimplemented: the D4 finished-run guard has to read the SAME record the
    owner's door reads, including the one a restart restored from the
    database, and a second lookup here would be a second answer to "what
    state is this run in".
    """

    from fastapi import APIRouter, Depends, HTTPException
    from fastapi.concurrency import run_in_threadpool

    # At CALL time, not at import: `admin_api` reads `RunRatingModel` from
    # this module for the drawer's own shape, so a module-scope import here
    # would be a cycle. The prefix is still IMPORTED rather than re-typed -
    # one literal, one place, and a second copy is how two routers end up on
    # two prefixes.
    from brief_crew.service.admin_api import ADMIN_API_PREFIX
    from brief_crew.service.auth import require_admin

    router = APIRouter(prefix=ADMIN_API_PREFIX, tags=["admin"])

    def admin(user: Any = Depends(resolve_user)) -> Any:
        return require_admin(user)

    def store() -> Any:
        persistence = persistence_factory()
        if persistence is None:
            raise HTTPException(
                status_code=503,
                detail="this service has no durable store, so a rating cannot be kept",
            )
        return persistence

    @router.put("/runs/{run_id}/rating", response_model=RunRatingModel)
    async def rate_any_run(
        run_id: str,
        request: RatingRequest,
        user: Any = Depends(admin),
    ) -> RunRatingModel:
        """Rate somebody else's run, and say in the log that it happened.

        The second door onto one write, and the WARNING is what makes it a
        lever rather than a back channel: plan 17's two levers log the actor's
        e-mail and the row they touched, and this one does the same. A rating
        an owner did not write must be findable by the owner's own support
        request, not only by reading the column.

        The log line names the actor, the run and the WORD - never the note,
        which is user content and has no business in a server log.
        """

        run_id = guard_run_id(run_id)
        # `is_admin=True`: an unowned run is exactly the row this lever exists
        # for, and D6's 403 is about a signed-in NON-admin.
        guard_rateable(
            run_factory(run_id), actor=getattr(user, "id", None), is_admin=True
        )
        stored = await run_in_threadpool(
            write_rating, store(), run_id, request, getattr(user, "id", None)
        )
        logger.warning(
            "admin %s rated run %s as %s",
            getattr(user, "email", None) or getattr(user, "id", None),
            run_id,
            request.normalised() or "unrated",
        )
        return stored

    return router
