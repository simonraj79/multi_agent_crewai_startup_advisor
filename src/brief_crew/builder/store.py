"""Durable storage for builder documents, one row per `(id, version)`.

The shape locked spec C names: a head row per graph saying what its current
version is, and an append-only history keyed by `(document_id, version)`. The
tables are in `service/persistence.py` beside every other table this service
owns, because they share an engine, a transaction guard and the additive-only
migration rule; the *policy* - who may read a document, what a version bump
means, what happens when two browsers save at once - is here.

Three things are deliberate and each one is a defect elsewhere in this repo
restated:

* **A save is a compare-and-set on the head version**, in the same
  `UPDATE ... WHERE ... ; rowcount` shape `answer_gate` and `reopen_gate` use.
  Two browsers editing one graph produce two versions and one 409, never one
  silently lost edit. (It is also the fifth such path with no concurrent-writer
  test on PostgreSQL - remaining-work item 3 - and it is written to match the
  four that came before so that one test would cover all five.)
* **A document with an owner is invisible to everybody else**, and the refusal
  is 404 rather than 403 for exactly the reason `require_own_run` gives: a 403
  confirms the document exists. A document with NO owner stays readable, which
  is what keeps this usable in tests, in SYNTHETIC mode and in a local checkout
  where there is no identity to record.
* **The stored JSON is re-validated on the way out.** A row is not trusted
  because it was validated on the way in: the schema moves, and a document
  written by an older `builder.flow/v1` that no longer parses must fail here,
  where the id is known and the message can name it, rather than deep inside
  the compiler. `load` raises; `published` - which the boot sweep reads, and
  which nobody asked for one document by name - SKIPS the row and reports it,
  because one bad graph must not take every graph behind it in query order down
  with it.

Nothing in this module compiles, registers or runs anything.
"""

from __future__ import annotations

from collections.abc import Callable, Iterator, Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime
import json
import logging
import secrets
from typing import Any

from pydantic import ValidationError
from sqlalchemy import delete, func, insert, select, update

from brief_crew.builder.document import BuilderDocument
from brief_crew.builder.upgrade import upgrade_document
from brief_crew.config import (
    BUILDER_VERSION_SOURCE_MAX_CHARS,
    MAX_BUILDER_DOCUMENT_BYTES,
    MAX_TEST_INPUTS_PER_DOCUMENT,
)
from brief_crew.service.persistence import (
    PostgresFlowPersistence,
    bounded_json,
    builder_document_versions,
    builder_documents,
    builder_test_inputs,
    identifier,
    utcnow,
)


logger = logging.getLogger(__name__)


#: A document that has never compiled. Editable, listed, and not runnable.
STATUS_DRAFT = "draft"
#: A document that compiled and was registered into the service's four maps.
STATUS_PUBLISHED = "published"

#: How many documents one list call returns by default. The canvas shows a
#: sidebar, not an archive.
DEFAULT_LIST_LIMIT = 50
MAX_LIST_LIMIT = 200


class BuilderStoreError(RuntimeError):
    """Base for the two refusals this store makes on its own authority."""


class DocumentNotFound(BuilderStoreError, LookupError):
    """No document with this id is visible to this caller - or no such VERSION.

    Deliberately one exception for "no such row" and "not yours": the transport
    answers 404 for both, and a caller who can tell them apart has the oracle
    that distinction exists to remove.

    `version` is set in exactly one case - the document IS visible to this
    caller and the version they asked for is not stored - and that is what
    the transport reads to choose its sentence (round 2, D-15-8). A caller who
    can see the document and asked for v99 of a v2 is told so, with the head
    named; a caller who cannot see it hears the constant, whatever they asked
    for. Raising with `version` from a visibility failure would leak nothing,
    but it would send the wrong sentence to the one caller entitled to a right
    one.
    """

    def __init__(
        self,
        document_id: str,
        version: int | None = None,
        *,
        head_version: int | None = None,
    ) -> None:
        if version is None:
            detail = f"document {document_id} was not found"
        elif head_version is None:
            detail = f"document {document_id} has no version {version}"
        else:
            detail = (
                f"document {document_id} has no version {version}; "
                f"the newest is v{head_version}"
            )
        super().__init__(detail)
        self.document_id = document_id
        self.version = version
        self.head_version = head_version


class DocumentReadOnly(BuilderStoreError):
    """This caller may read the document and may not write it.

    Raised for an UNOWNED row when the caller has an identity (round 2,
    D-15-7). The read carve-out in `_visible_to` exists so rows written before
    authentication stay usable; it was never a licence for a signed-in stranger
    to overwrite, publish or delete them. The transport answers **403**, not
    404, and that is safe here for the one reason a 403 is refused everywhere
    else: an unowned row is visible to everyone already, so confirming that it
    exists tells nobody anything. The sentence names the way out - Duplicate
    gives the caller a copy they own.
    """

    def __init__(self, document_id: str) -> None:
        super().__init__(
            f"document {document_id} has no owner and is read-only for every "
            "signed-in user; Duplicate it to get a copy you own"
        )
        self.document_id = document_id


class DocumentVersionConflict(BuilderStoreError):
    """Somebody else saved this document while this edit was in the browser.

    Carries the version that is actually stored, because the only useful thing
    a client can do with this is reload that one and show the author what
    changed.
    """

    def __init__(self, document_id: str, *, expected: int, stored: int) -> None:
        super().__init__(
            f"document {document_id} is at version {stored}, not {expected}; "
            "reload it before saving again"
        )
        self.document_id = document_id
        self.expected = expected
        self.stored = stored


class DocumentTooLarge(BuilderStoreError):
    """The serialised document is over MAX_BUILDER_DOCUMENT_BYTES.

    Checked here as well as at the HTTP edge, and not as a belt-and-braces
    formality: `RequestBodySizeLimitMiddleware` reads the declared
    `Content-Length`, and a chunked request declares none. This is the bound
    that holds whatever the transport did.
    """

    def __init__(self, document_id: str, size: int) -> None:
        super().__init__(
            f"document {document_id} serialises to {size} bytes and the limit is "
            f"{MAX_BUILDER_DOCUMENT_BYTES}"
        )
        self.document_id = document_id
        self.size = size


@dataclass(frozen=True, slots=True)
class StoredDocument:
    """One document at one version, with the head row's metadata beside it."""

    document: BuilderDocument
    status: str
    user_id: str | None
    created_at: datetime
    updated_at: datetime
    #: The head version, which is not `document.version` when an older version
    #: was loaded explicitly.
    head_version: int

    @property
    def id(self) -> str:
        return self.document.id

    @property
    def is_head(self) -> bool:
        return self.document.version == self.head_version


@dataclass(frozen=True, slots=True)
class DocumentSummary:
    """What a list shows: enough to pick one, nothing that needs parsing."""

    id: str
    name: str
    version: int
    status: str
    user_id: str | None
    created_at: datetime
    updated_at: datetime


@dataclass(frozen=True, slots=True)
class VersionSummary:
    """One stored version, as the version browser lists it - never parsed.

    `bytes` is the serialised size of the row as `_checked_size` measures it,
    so the number the browser shows is the one `MAX_BUILDER_DOCUMENT_BYTES` is
    compared against. Not parsed, deliberately: a version written under a
    schema this service no longer reads must still appear in the history, or
    an author cannot see which version it was that stopped opening.

    `name` and `node_count` are READ off the raw row, not validated out of it
    (round 2, D-15-3): a mapping with a `name` string and a `nodes` list gives
    both, anything else gives None, and a row the schema would refuse still
    lists with whatever it can say. `source` is the column of the same round -
    `created`, `saved`, `autosaved`, `restored from v3`, `imported`,
    `duplicated` - and None for a row written before the column existed.
    """

    version: int
    created_at: datetime
    bytes: int
    source: str | None = None
    name: str | None = None
    node_count: int | None = None


@dataclass(frozen=True, slots=True)
class VersionHistory:
    """Every version of one document, newest first, with the head beside it.

    The head's version and status travel with the list because a version has
    no status of its own - `status` lives on the head row - and the transport
    has to say which entry is the head and whether that head is published
    without a second query the browser would then have to reconcile.
    """

    document_id: str
    head_version: int
    status: str
    entries: tuple[VersionSummary, ...]


def new_document_id() -> str:
    """A server-assigned id matching `BUILDER_DOCUMENT_ID_PATTERN`.

    `secrets` rather than `uuid4().hex[:8]` or `random`: the id is the only
    thing standing between an unauthenticated caller and somebody else's
    unowned document, so it is generated the way a token is even though it is
    not one. Eight hex characters is 32 bits, which is not a security boundary
    and is not asked to be - ownership is - but it must not be guessable in
    order.
    """

    return f"ug_{secrets.token_hex(4)}"


def _document_json(document: BuilderDocument) -> dict[str, Any]:
    """The document as stored: by ALIAS, so `schema` is spelled `schema`.

    `document_schema` is the python name only because pydantic refuses a field
    that shadows a `BaseModel` attribute. Storing the python spelling would put
    a key in the database that the wire format does not have and that
    `model_validate` would then reject on the way back out.
    """

    return document.model_dump(mode="json", by_alias=True)


def _encoded_size(payload: Any) -> int:
    """The bytes a row costs, measured the one way this module measures it."""

    return len(json.dumps(payload, separators=(",", ":")).encode("utf-8"))


def _checked_size(document_id: str, payload: dict[str, Any]) -> dict[str, Any]:
    encoded = _encoded_size(payload)
    if encoded > MAX_BUILDER_DOCUMENT_BYTES:
        raise DocumentTooLarge(document_id, encoded)
    return payload


class TestInputNotFound(BuilderStoreError, LookupError):
    """No saved test input with this id belongs to this caller.

    One exception for "no such row" and "not yours", the same conflation
    `DocumentNotFound` makes and for the same reason: the transport answers 404
    for both, and a caller who can tell them apart has the oracle that
    distinction exists to remove.
    """

    def __init__(self, test_input_id: str) -> None:
        super().__init__(f"test input {test_input_id} was not found")
        self.test_input_id = test_input_id


class TestInputLimitReached(BuilderStoreError):
    """This document already holds MAX_TEST_INPUTS_PER_DOCUMENT saved inputs."""

    def __init__(self, document_id: str, count: int) -> None:
        super().__init__(
            f"document {document_id} already has {count} saved test inputs and "
            f"the ceiling is {MAX_TEST_INPUTS_PER_DOCUMENT}; delete one first"
        )
        self.document_id = document_id
        self.count = count


@dataclass(frozen=True, slots=True)
class TestInput:
    """One saved run input, as the panel and the transport both read it."""

    id: str
    document_id: str
    label: str
    inputs: dict[str, Any]
    node_mocks: dict[str, Any]
    created_at: datetime
    updated_at: datetime


#: The owner written for a caller with no identity.
#:
#: `user_id` is NOT NULL on this table (15 D6: these rows never existed before
#: authentication did), so an anonymous caller has to be written as SOMETHING
#: and the choice is between a sentinel and refusing them outright. A sentinel,
#: for the reason `_writable_by` already gives about unowned documents: where
#: identity does not exist - `SYNTHETIC=1` with no auth server, a bare local
#: checkout - the anonymous caller IS the author, and refusing them would make
#: the panel untestable on the one backend the E2E suite is allowed to use.
#:
#: It is a sentinel and not a wildcard: an anonymous caller matches rows written
#: anonymously and nothing else, so this widens nobody's reach into a signed-in
#: author's saved inputs. That is the property plan 10's `load` was protecting
#: when it matched nothing at all; the sentinel keeps it and stops matching
#: nothing.
ANONYMOUS_OWNER = ""


def new_test_input_id() -> str:
    """`ti_` + 12 hex - `config.TEST_INPUT_ID_PATTERN`."""

    return f"ti_{secrets.token_hex(6)}"


class BuilderTestInputStore:
    """The saved test inputs of one document, for their owner and nobody else.

    `13-flow-testing.md` D3 owns this table's behaviour; plan 10 landed the one
    read query C7's `test_input_id` implies and left the rest here, which is
    where the SQL for every other builder table already lives.

    Ownership is a WHERE clause and not a check after the fact, so a row that
    belongs to somebody else and a row that does not exist are the same `None` -
    which is the 404-not-403 rule every other builder route already follows.
    The DOCUMENT's visibility is a separate question and is deliberately not
    asked here: the route asks it first, through `BuilderDocumentStore.load`, so
    somebody else's document 404s before this store is reached at all.
    """

    __slots__ = ("_store",)

    def __init__(self, store: PostgresFlowPersistence) -> None:
        self._store = store

    def load(
        self, test_input_id: str, *, user_id: str | None
    ) -> dict[str, Any] | None:
        statement = select(
            builder_test_inputs.c.id,
            builder_test_inputs.c.document_id,
            builder_test_inputs.c.label,
            builder_test_inputs.c.inputs,
            builder_test_inputs.c.node_mocks,
        ).where(builder_test_inputs.c.id == str(test_input_id))
        statement = statement.where(
            builder_test_inputs.c.user_id == _test_input_owner(user_id)
        )
        with self._store.connect() as connection:
            row = connection.execute(statement).mappings().first()
        return dict(row) if row is not None else None

    def list(self, document_id: str, *, user_id: str | None) -> list[TestInput]:
        """This caller's saved inputs for one document, newest first.

        Ordered by `updated_at` descending, which is what
        `ix_builder_test_inputs_document_updated` was declared for, with the id
        as the tiebreak so two rows saved inside one clock tick have an order at
        all rather than whichever the dialect happens to return.
        """

        with self._store.connect() as connection:
            rows = (
                connection.execute(
                    select(builder_test_inputs)
                    .where(
                        builder_test_inputs.c.document_id == str(document_id),
                        builder_test_inputs.c.user_id == _test_input_owner(user_id),
                    )
                    .order_by(
                        builder_test_inputs.c.updated_at.desc(),
                        builder_test_inputs.c.id,
                    )
                )
                .mappings()
                .all()
            )
        return [_test_input(row) for row in rows]

    def create(
        self,
        document_id: str,
        *,
        user_id: str | None,
        label: str,
        inputs: Mapping[str, Any],
        node_mocks: Mapping[str, Any] | None = None,
    ) -> TestInput:
        """Save one input set against a document. Refuses over the ceiling.

        The count is read and the insert made in two statements rather than one,
        which is a race a second browser could win - and the cost of losing it
        is one row over a soft ceiling, not a lost edit. The compare-and-set
        shape is reserved for the thing that actually matters, which next door
        is somebody's work and here is a saved prompt.
        """

        owner = _test_input_owner(user_id)
        with self._store.connect() as connection:
            existing = connection.execute(
                select(func.count())
                .select_from(builder_test_inputs)
                .where(
                    builder_test_inputs.c.document_id == str(document_id),
                    builder_test_inputs.c.user_id == owner,
                )
            ).scalar_one()
        if int(existing) >= MAX_TEST_INPUTS_PER_DOCUMENT:
            raise TestInputLimitReached(str(document_id), int(existing))

        now = utcnow()
        row: dict[str, Any] = {
            "id": new_test_input_id(),
            "user_id": owner,
            "document_id": str(document_id),
            "label": str(label),
            "inputs": dict(inputs),
            "node_mocks": dict(node_mocks or {}),
            "created_at": now,
            "updated_at": now,
        }
        with self._store.begin() as connection:
            connection.execute(insert(builder_test_inputs).values(**row))
        return _test_input(row)

    def delete(self, test_input_id: str, *, user_id: str | None) -> None:
        """Remove one saved input. Raises when it is not this caller's."""

        with self._store.begin() as connection:
            result = connection.execute(
                delete(builder_test_inputs).where(
                    builder_test_inputs.c.id == str(test_input_id),
                    builder_test_inputs.c.user_id == _test_input_owner(user_id),
                )
            )
        if not result.rowcount:
            raise TestInputNotFound(str(test_input_id))


def _test_input_owner(user_id: str | None) -> str:
    return str(user_id) if user_id else ANONYMOUS_OWNER


def _test_input(row: Mapping[str, Any]) -> TestInput:
    """One stored row as a `TestInput`, with both JSON columns defaulted.

    `node_mocks` is nullable and a row written before the panel could set one
    reads NULL; every reader wants a mapping, so the default is here rather
    than at four call sites.
    """

    return TestInput(
        id=str(row["id"]),
        document_id=str(row["document_id"]),
        label=str(row["label"]),
        inputs=dict(row["inputs"] or {}),
        node_mocks=dict(row["node_mocks"] or {}),
        created_at=row["created_at"],
        updated_at=row["updated_at"],
    )


class BuilderDocumentStore:
    """Read and write builder documents on the service's own engine.

    Takes the `PostgresFlowPersistence` rather than a URL or an `Engine`, and
    that is the point: on in-memory SQLite the database exists only for as long
    as its single connection does, and that store's `_access_lock` is the only
    thing stopping two threads sharing one transaction. A second store opening
    its own engine would see an empty database; one reaching for
    `engine.begin()` would commit somebody else's half-finished unit of work.
    """

    __slots__ = ("_store",)

    def __init__(self, store: PostgresFlowPersistence) -> None:
        self._store = store

    # ------------------------------------------------------------------ read
    def load(
        self,
        document_id: str,
        *,
        version: int | None = None,
        user_id: str | None = None,
        writable: bool = False,
    ) -> StoredDocument:
        """One document, at `version` or at the head.

        `user_id` is the CALLER, not a filter to apply blindly: a document with
        no owner is readable by anyone, and one with an owner is readable only
        by them. Both directions matter - the first is what keeps a bare local
        checkout working, the second is the whole of the access control.

        `writable=True` asks the second question too - `_writable_by` - and
        raises `DocumentReadOnly` when the answer is no. A route that is about
        to unregister a graph or compile one asks BEFORE it does either, so a
        refusal costs nothing and leaves nothing half done (D-15-7, D-15-10).
        """

        document_id = identifier(document_id, label="document_id")
        with self._store.connect() as connection:
            head = connection.execute(
                select(builder_documents).where(builder_documents.c.id == document_id)
            ).mappings().one_or_none()
            if head is None or not _visible_to(head["user_id"], user_id):
                # No version here, on purpose: the caller may not see the
                # document, so the sentence they get is the constant.
                raise DocumentNotFound(document_id)
            if writable and not _writable_by(head["user_id"], user_id):
                raise DocumentReadOnly(document_id)
            wanted = int(head["version"]) if version is None else int(version)
            row = connection.execute(
                select(builder_document_versions).where(
                    builder_document_versions.c.document_id == document_id,
                    builder_document_versions.c.version == wanted,
                )
            ).mappings().one_or_none()
        if row is None:
            # The document is visible and the version is not stored: name both.
            raise DocumentNotFound(document_id, wanted, head_version=int(head["version"]))
        return StoredDocument(
            document=_parse(document_id, row["document"]),
            status=str(head["status"]),
            user_id=head["user_id"],
            created_at=head["created_at"],
            updated_at=head["updated_at"],
            head_version=int(head["version"]),
        )

    def versions(self, document_id: str, *, user_id: str | None = None) -> list[int]:
        """Every stored version of one document, newest first."""

        document_id = identifier(document_id, label="document_id")
        with self._store.connect() as connection:
            head = connection.execute(
                select(builder_documents.c.user_id).where(
                    builder_documents.c.id == document_id
                )
            ).mappings().one_or_none()
            if head is None or not _visible_to(head["user_id"], user_id):
                raise DocumentNotFound(document_id)
            rows = connection.execute(
                select(builder_document_versions.c.version)
                .where(builder_document_versions.c.document_id == document_id)
                .order_by(builder_document_versions.c.version.desc())
            ).scalars().all()
        return [int(value) for value in rows]

    def history(
        self, document_id: str, *, user_id: str | None = None
    ) -> VersionHistory:
        """Every stored version with its size and date, newest first.

        `versions` above answers only the numbers and is what the publish path
        needs. This is what the version browser needs: enough to pick a version
        and to say which one is the head, without parsing any of them - see
        `VersionSummary` for why parsing here would hide the one row an author
        most wants to see.
        """

        document_id = identifier(document_id, label="document_id")
        with self._store.connect() as connection:
            head = connection.execute(
                select(builder_documents).where(builder_documents.c.id == document_id)
            ).mappings().one_or_none()
            if head is None or not _visible_to(head["user_id"], user_id):
                raise DocumentNotFound(document_id)
            rows = connection.execute(
                select(
                    builder_document_versions.c.version,
                    builder_document_versions.c.created_at,
                    builder_document_versions.c.document,
                    builder_document_versions.c.source,
                )
                .where(builder_document_versions.c.document_id == document_id)
                .order_by(builder_document_versions.c.version.desc())
            ).mappings().all()
        return VersionHistory(
            document_id=document_id,
            head_version=int(head["version"]),
            status=str(head["status"]),
            entries=tuple(
                VersionSummary(
                    version=int(row["version"]),
                    created_at=row["created_at"],
                    bytes=_encoded_size(row["document"]),
                    source=row["source"],
                    **_lenient_summary(row["document"]),
                )
                for row in rows
            ),
        )

    def list(
        self, *, user_id: str | None = None, limit: int = DEFAULT_LIST_LIMIT
    ) -> list[DocumentSummary]:
        """The documents this caller may open, most recently edited first.

        The ownership predicate is applied in SQL rather than by fetching and
        filtering in Python, for the reason `list_runs_for_user` gives: a bug in
        the layer above cannot leak a row that was never selected.

        An anonymous caller sees the UNOWNED documents, not all of them. That is
        the same rule `load` applies, and reading it as "no user, no filter"
        would make signing out the cheapest way to read everybody's drafts.
        """

        if limit < 1:
            raise ValueError("limit must be positive")
        limit = min(int(limit), MAX_LIST_LIMIT)
        predicate = (
            builder_documents.c.user_id.is_(None)
            if not user_id
            else builder_documents.c.user_id == identifier(user_id, label="user_id")
        )
        statement = (
            select(builder_documents)
            .where(predicate)
            .order_by(builder_documents.c.updated_at.desc(), builder_documents.c.id)
            .limit(limit)
        )
        with self._store.connect() as connection:
            rows = connection.execute(statement).mappings().all()
        return [
            DocumentSummary(
                id=str(row["id"]),
                name=str(row["name"]),
                version=int(row["version"]),
                status=str(row["status"]),
                user_id=row["user_id"],
                created_at=row["created_at"],
                updated_at=row["updated_at"],
            )
            for row in rows
        ]

    # ----------------------------------------------------------------- write
    def create(
        self,
        document: BuilderDocument,
        *,
        user_id: str | None = None,
        source: str = "created",
    ) -> StoredDocument:
        """Insert a brand new document at the version it declares.

        The caller assigns the id with `new_document_id()` and puts it in the
        document, because the id is part of what gets compiled - the flow's
        name is `builder_{id}_v{version}` - and a store that assigned it after
        validation would be handing back a different document from the one it
        was given.

        `source` is what the version browser will say this first version came
        from (D-15-3): `created` from the canvas, `imported` from a file,
        `duplicated` from another document. The routes that mint rows say
        which; the store only stores it.
        """

        payload = _checked_size(document.id, _document_json(document))
        safe = bounded_json(payload, label="builder document")
        owner = identifier(user_id, label="user_id") if user_id else None
        now = utcnow()
        with self._store.begin() as connection:
            existing = connection.execute(
                select(func.count())
                .select_from(builder_documents)
                .where(builder_documents.c.id == document.id)
            ).scalar_one()
            if existing:
                raise DocumentVersionConflict(
                    document.id, expected=0, stored=document.version
                )
            connection.execute(
                insert(builder_documents).values(
                    id=document.id,
                    user_id=owner,
                    name=document.name,
                    version=document.version,
                    status=STATUS_DRAFT,
                    created_at=now,
                    updated_at=now,
                )
            )
            connection.execute(
                insert(builder_document_versions).values(
                    document_id=document.id,
                    version=document.version,
                    document=safe,
                    created_at=now,
                    source=_version_source(source),
                )
            )
        return StoredDocument(
            document=document,
            status=STATUS_DRAFT,
            user_id=owner,
            created_at=now,
            updated_at=now,
            head_version=document.version,
        )

    def save(
        self,
        document: BuilderDocument,
        *,
        expected_version: int,
        user_id: str | None = None,
        source: str | None = None,
    ) -> StoredDocument:
        """Write a new version, if `expected_version` is still the head.

        `document.version` is IGNORED and recomputed as `expected_version + 1`.
        The version is a server fact - the ETag is derived from it and the
        stored budget is versioned against it - and a client that could choose
        it could make two different graphs share one tag, which is precisely
        what the ETag exists to prevent.

        `source` is the version browser's provenance for the new row (D-15-3),
        composed by the route from what the client declared: `saved`,
        `autosaved`, `restored from v3`. None reads as `saved`.
        """

        expected = int(expected_version)
        next_version = expected + 1
        stamped = document.model_copy(update={"version": next_version})
        payload = _checked_size(stamped.id, _document_json(stamped))
        safe = bounded_json(payload, label="builder document")
        now = utcnow()

        with self._store.begin() as connection:
            head = connection.execute(
                select(builder_documents).where(builder_documents.c.id == stamped.id)
            ).mappings().one_or_none()
            if head is None or not _visible_to(head["user_id"], user_id):
                raise DocumentNotFound(stamped.id)
            if not _writable_by(head["user_id"], user_id):
                raise DocumentReadOnly(stamped.id)
            stored_version = int(head["version"])
            # The compare-and-set. Guarding on the version in the WHERE clause
            # rather than on the row read above is what makes this safe against
            # a concurrent writer: the read is advisory, the UPDATE is the
            # decision, and `rowcount` is how it reports which way it went.
            result = connection.execute(
                update(builder_documents)
                .where(
                    builder_documents.c.id == stamped.id,
                    builder_documents.c.version == expected,
                )
                .values(
                    name=stamped.name,
                    version=next_version,
                    # Editing a published graph makes it a draft again. The
                    # registered workflow keeps running the version that was
                    # published, because that is the one whose budget was
                    # priced and whose ETag is in flight.
                    status=STATUS_DRAFT,
                    updated_at=now,
                )
            )
            if result.rowcount != 1:
                raise DocumentVersionConflict(
                    stamped.id,
                    expected=expected,
                    stored=_head_version_now(connection, stamped.id, stored_version),
                )
            connection.execute(
                insert(builder_document_versions).values(
                    document_id=stamped.id,
                    version=next_version,
                    document=safe,
                    created_at=now,
                    source=_version_source(source or "saved"),
                )
            )
        return StoredDocument(
            document=stamped,
            status=STATUS_DRAFT,
            user_id=head["user_id"],
            created_at=head["created_at"],
            updated_at=now,
            head_version=next_version,
        )

    def mark_published(
        self, document_id: str, version: int, *, user_id: str | None = None
    ) -> StoredDocument:
        """Record that this exact version compiled and was registered.

        Compare-and-set on the version too, for the same reason as `save`: a
        publish that lands after somebody else's edit would otherwise mark a
        version published that is no longer the head, and the canvas would show
        `published` over a document the service is not running.
        """

        loaded = self.load(document_id, version=version, user_id=user_id, writable=True)
        now = utcnow()
        with self._store.begin() as connection:
            result = connection.execute(
                update(builder_documents)
                .where(
                    builder_documents.c.id == loaded.id,
                    builder_documents.c.version == version,
                )
                .values(status=STATUS_PUBLISHED, updated_at=now)
            )
            if result.rowcount != 1:
                raise DocumentVersionConflict(
                    loaded.id,
                    expected=version,
                    stored=_head_version_now(connection, loaded.id, loaded.head_version),
                )
        return StoredDocument(
            document=loaded.document,
            status=STATUS_PUBLISHED,
            user_id=loaded.user_id,
            created_at=loaded.created_at,
            updated_at=now,
            head_version=version,
        )

    def mark_unpublished(
        self, document_id: str, *, user_id: str | None = None
    ) -> StoredDocument:
        """Return a published head to `draft`, touching no version.

        The other half of `mark_published`, and the store half of the
        unpublish route (round 2, D-15-10; PLANS.md decision 24). The status
        has to move HERE and not only in the process-local registration maps,
        because the boot sweep re-registers every row whose status says
        `published`: an unpublish that left the row alone would be undone by
        the next deploy, and both Render services carry `autoDeploy: yes`.

        Idempotent, and guarded on the status rather than on the version. A
        head that is already `draft` - edited after the publish, while an
        older version stayed registered - is left as it is; the route's
        unregister is what takes that older version out of service.
        """

        loaded = self.load(document_id, user_id=user_id, writable=True)
        now = utcnow()
        with self._store.begin() as connection:
            connection.execute(
                update(builder_documents)
                .where(
                    builder_documents.c.id == loaded.id,
                    builder_documents.c.status == STATUS_PUBLISHED,
                )
                .values(status=STATUS_DRAFT, updated_at=now)
            )
        return self.load(document_id, user_id=user_id)

    def delete(self, document_id: str, *, user_id: str | None = None) -> None:
        """Remove a document, every version of it, and its saved test inputs.

        The one destructive operation, and it takes the ownership check before
        it takes the lock. `builder_document_versions` and
        `builder_test_inputs` both carry ON DELETE CASCADE, but SQLite does not
        enforce a foreign key unless the pragma is on, so the child rows are
        deleted explicitly rather than hopefully. Test inputs are plan 13's
        rows; they are named here because they are keyed by this document and
        a document that is gone must not leave inputs that reference it.
        """

        document_id = identifier(document_id, label="document_id")
        with self._store.begin() as connection:
            head = connection.execute(
                select(builder_documents.c.user_id).where(
                    builder_documents.c.id == document_id
                )
            ).mappings().one_or_none()
            if head is None or not _visible_to(head["user_id"], user_id):
                raise DocumentNotFound(document_id)
            if not _writable_by(head["user_id"], user_id):
                raise DocumentReadOnly(document_id)
            connection.execute(
                delete(builder_test_inputs).where(
                    builder_test_inputs.c.document_id == document_id
                )
            )
            connection.execute(
                delete(builder_document_versions).where(
                    builder_document_versions.c.document_id == document_id
                )
            )
            connection.execute(
                delete(builder_documents).where(builder_documents.c.id == document_id)
            )

    # ----------------------------------------------------------------- reuse
    def published(
        self,
        *,
        limit: int = MAX_LIST_LIMIT,
        on_skipped: Callable[[str, str], None] | None = None,
    ) -> Iterator[StoredDocument]:
        """Every published document at its head version, owner or not.

        What a restart reads to put the builder graphs back into the four
        registration maps: the maps live in module globals and do not survive
        the process, while the documents do. Ownership is deliberately not
        applied - registering a workflow is not reading somebody's draft, and a
        run against it is still checked by `require_own_run`.

        **One unparseable row is skipped, not fatal, and that is the whole
        difference between this and `load`.** `_parse` raises, a raise inside a
        generator CLOSES it, and the rows behind the offending document are then
        unreachable without a second query - so a single graph written under an
        older `builder.flow/v1` used to unregister every graph ordered after it
        and answer 404 for all of them after the next restart. The order here is
        `updated_at DESC`, which nobody publishing a graph chose and nothing
        makes stable, so which graphs died was arbitrary. `load` still raises,
        because there the caller asked for that one document by name and a
        silent skip would be a 404 for a row that is sitting right there.

        `on_skipped` receives `(document_id, reason)` for each row dropped this
        way. A callback rather than a swallowed log line because the boot sweep
        reports what it could not restore, and a graph that silently stops
        existing is exactly the defect that sweep was written to close.

        **Two rows are droppable, and both report.** The second is a head whose
        named version has no stored row at all - a partial write, or a version
        deleted from under its head. It used to `continue` in silence purely
        because it is checked two lines earlier than the parse, which made the
        report above incomplete in the one case an operator would most want it.
        """

        with self._store.connect() as connection:
            rows = connection.execute(
                select(builder_documents)
                .where(builder_documents.c.status == STATUS_PUBLISHED)
                .order_by(builder_documents.c.updated_at.desc())
                .limit(max(1, min(int(limit), MAX_LIST_LIMIT)))
            ).mappings().all()
            for head in rows:
                row = connection.execute(
                    select(builder_document_versions.c.document).where(
                        builder_document_versions.c.document_id == head["id"],
                        builder_document_versions.c.version == head["version"],
                    )
                ).mappings().one_or_none()
                document_id = str(head["id"])
                if row is None:
                    # The same silent drop as an unparseable row, one cause
                    # earlier: the head names a version whose row is not there.
                    # It bypassed the reporting below for no better reason than
                    # sitting two lines above it, so a graph could vanish from
                    # the boot sweep's own report of what it could not restore -
                    # which is the single thing that report exists to prevent.
                    reason = (
                        f"head points at version {head['version']}, which has no "
                        "stored row"
                    )
                    logger.warning(
                        "published builder document %s %s and was skipped",
                        document_id,
                        reason,
                    )
                    if on_skipped is not None:
                        on_skipped(document_id, reason)
                    continue
                try:
                    document = _parse(document_id, row["document"])
                except BuilderStoreError as exc:
                    logger.warning(
                        "published builder document %s is stored in a shape this "
                        "service no longer parses and was skipped: %s",
                        document_id,
                        exc,
                    )
                    if on_skipped is not None:
                        on_skipped(document_id, str(exc))
                    continue
                yield StoredDocument(
                    document=document,
                    status=str(head["status"]),
                    user_id=head["user_id"],
                    created_at=head["created_at"],
                    updated_at=head["updated_at"],
                    head_version=int(head["version"]),
                )


def _version_source(value: str) -> str:
    """The provenance string as stored: bounded to the column, never empty."""

    text = str(value).strip()[:BUILDER_VERSION_SOURCE_MAX_CHARS]
    return text or "saved"


def _lenient_summary(payload: Any) -> dict[str, Any]:
    """`name` and `node_count` off a raw stored row, or None for each.

    Read, not validated (D-15-3): the version browser lists every stored row,
    including one the schema no longer parses, and a summary that went through
    `BuilderDocument` would hide exactly the row an author most wants to see.
    A mapping with a string `name` gives a name; a list under `nodes` gives a
    count; anything else gives None for that field and the row still lists.
    """

    if not isinstance(payload, Mapping):
        return {"name": None, "node_count": None}
    name = payload.get("name")
    nodes = payload.get("nodes")
    return {
        "name": name if isinstance(name, str) and name else None,
        "node_count": len(nodes) if isinstance(nodes, list) else None,
    }


def _head_version_now(connection: Any, document_id: str, fallback: int) -> int:
    """The head version AFTER a compare-and-set lost, for the 409 to name.

    Found by `tests/pg/test_two_writers.py`, and only findable there: the
    version a losing `save` reported was the one it had READ before its UPDATE,
    which under two real writers is the version that had just been replaced. The
    409 then said "is at version 1, not 1; reload it" - nonsense, and worse than
    nonsense, because the client obeys and reloads the version that lost. On
    SQLite the read and the UPDATE can never be separated by a commit, so no
    single-writer test could see it. Read again inside the same transaction:
    under READ COMMITTED the row the UPDATE just re-evaluated against is the one
    this SELECT sees.
    """

    current = connection.execute(
        select(builder_documents.c.version).where(builder_documents.c.id == document_id)
    ).scalar_one_or_none()
    return int(current) if current is not None else int(fallback)


def _visible_to(owner: str | None, caller: str | None) -> bool:
    """Whether `caller` may see a row owned by `owner`.

    An unowned row is visible to everybody, which covers rows written before
    authentication existed and every row written while auth is off. An owned
    row is visible to its owner alone.
    """

    return owner is None or (caller is not None and caller == owner)


def _writable_by(owner: str | None, caller: str | None) -> bool:
    """Whether `caller` may WRITE a row owned by `owner`. Presumes `_visible_to`.

    The rule is equality, and the two ends of it are the whole decision
    (round 2, D-15-7):

    * An owned row is writable by its owner. `_visible_to` already hides it
      from everybody else, so this never turns a 404 into a 403.
    * An unowned row is writable by a caller with NO identity, and by nobody
      who has one. Where identity does not exist - `SYNTHETIC=1` with no
      header, a bare local checkout - the anonymous caller IS the author, and
      refusing them would make every local save a 403. Where it does, an
      unowned row is history from before authentication, and "readable by
      everyone" had silently become "controllable by everyone": alice could
      overwrite, bob could publish, and either could delete a row nobody
      could be asked about. Duplicate is the way to own one.
    """

    return owner == caller


def _parse(document_id: str, payload: Any) -> BuilderDocument:
    """Re-validate a stored row, naming the document when it no longer parses.

    A row is not trusted because something validated it once. The schema moves,
    and a document written by an earlier `builder.flow/v1` that this one refuses
    must fail here - where the id is known and the message can say which
    document - rather than three modules later inside the compiler.

    Raising is right for `load`, which was asked for this document by name.
    `published` catches it per row instead: see that method for why a raise from
    inside a generator is a different, much larger failure.

    `upgrade_document` runs first (plan 15 D5), on the raw row and before the
    schema sees it, so a version written under an older `builder.flow/*` parses
    as the current one without the row being rewritten. Only a mapping is
    handed to it: a row that is not even a mapping is not an old shape, it is a
    corrupt one, and the schema's own message names that better than a
    TypeError from the upgrade would.
    """

    try:
        candidate = upgrade_document(payload) if isinstance(payload, Mapping) else payload
        return BuilderDocument.model_validate(candidate)
    except ValidationError as exc:
        raise BuilderStoreError(
            f"document {document_id} is stored in a shape this service no longer "
            f"parses: {exc.errors()[0].get('msg', 'invalid')}"
        ) from exc


__all__: Sequence[str] = (
    "BuilderDocumentStore",
    "BuilderStoreError",
    "BuilderTestInputStore",
    "DEFAULT_LIST_LIMIT",
    "DocumentNotFound",
    "DocumentReadOnly",
    "DocumentSummary",
    "DocumentTooLarge",
    "DocumentVersionConflict",
    "MAX_LIST_LIMIT",
    "STATUS_DRAFT",
    "STATUS_PUBLISHED",
    "StoredDocument",
    "VersionHistory",
    "VersionSummary",
    "new_document_id",
)
