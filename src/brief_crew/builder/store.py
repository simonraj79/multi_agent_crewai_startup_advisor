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
from brief_crew.config import MAX_BUILDER_DOCUMENT_BYTES
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
    """No document with this id is visible to this caller.

    Deliberately one exception for "no such row" and "not yours": the transport
    answers 404 for both, and a caller who can tell them apart has the oracle
    that distinction exists to remove.
    """

    def __init__(self, document_id: str, version: int | None = None) -> None:
        detail = f"document {document_id}" + (
            f" version {version}" if version is not None else ""
        )
        super().__init__(f"{detail} was not found")
        self.document_id = document_id
        self.version = version


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
    """

    version: int
    created_at: datetime
    bytes: int


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
                raise DocumentNotFound(document_id, version)
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
            raise DocumentNotFound(document_id, wanted)
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
        self, document: BuilderDocument, *, user_id: str | None = None
    ) -> StoredDocument:
        """Insert a brand new document at the version it declares.

        The caller assigns the id with `new_document_id()` and puts it in the
        document, because the id is part of what gets compiled - the flow's
        name is `builder_{id}_v{version}` - and a store that assigned it after
        validation would be handing back a different document from the one it
        was given.
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
    ) -> StoredDocument:
        """Write a new version, if `expected_version` is still the head.

        `document.version` is IGNORED and recomputed as `expected_version + 1`.
        The version is a server fact - the ETag is derived from it and the
        stored budget is versioned against it - and a client that could choose
        it could make two different graphs share one tag, which is precisely
        what the ETag exists to prevent.
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
