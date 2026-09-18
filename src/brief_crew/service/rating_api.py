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
    note: str | None = Field(default=None, max_length=config.MAX_RATING_NOTE_CHARS)

    @field_validator("rating")
    @classmethod
    def _known_rating(cls, value: str | None) -> str | None:
        if value is None:
            return None
        candidate = value.strip().lower()
        if not candidate:
            return None
        if candidate not in RATING_VALUES:
            raise ValueError(
                "rating must be one of " + ", ".join(RATING_VALUES) + ", or null"
            )
        return candidate

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


def write_rating(
    persistence: Any, run_id: str, request: RatingRequest, actor: str | None
) -> RunRatingModel:
    """The one write behind both rating routes.

    One implementation, two doors: the owner's `PUT` and the admin's. A second
    copy of this would be a second answer to "what does clearing a rating do",
    and the answer - the note and the actor go with it - is the kind that
    drifts.
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

    scored = scores.rating_score_value(rating)
    if scored is not None:
        value, data_type = scored
        scores.record_run_score(
            run_id,
            name=scores.SCORE_HUMAN_RATING,
            value=value,
            data_type=data_type,
            # Free text a person typed. `record_run_score` writes it only
            # under `LANGFUSE_CAPTURE_CONTENT`; the default is not a denylist.
            comment=request.note,
        )
    return rating_payload(run_id, stored)


def create_rating_router(
    *,
    resolve_user: Callable[..., Any],
    persistence_factory: Callable[[], Any],
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
    """

    from fastapi import APIRouter, Depends, HTTPException

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
        """

        stored = write_rating(store(), run_id, request, getattr(user, "id", None))
        logger.warning(
            "admin %s rated run %s as %s",
            getattr(user, "email", None) or getattr(user, "id", None),
            run_id,
            request.normalised() or "unrated",
        )
        return stored

    return router
