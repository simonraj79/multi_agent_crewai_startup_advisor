"""The three attachment stores: custom tools, MCP servers and skill packs.

Plans 06, 07 and 08 each need one table read and written the same way, and the
way is already settled by `service/credentials.py`: take the
`PostgresFlowPersistence` rather than an engine (on in-memory SQLite the
database exists only as long as its one connection does), scope every read that
names a row `WHERE user_id = :caller` **in SQL**, and answer absent and foreign
with one exception so a refusal is never an oracle for somebody else's ids.

A separate module rather than three, and rather than inside
`builder/tools.py` and its siblings, for two reasons. The builder package is
importable without the service - `compile_document` and `estimate_budget` must
not pay for SQLAlchemy - and the three tables differ only in their columns, so
one file is where their sameness is visible. Everything policy-shaped
(sanitising, transports, parsing, the catalogue) lives in the builder modules;
this file holds SQL and nothing else that could be called a decision.
"""

from __future__ import annotations

import re
import secrets
from collections.abc import Iterable, Mapping, Sequence
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import delete, insert, select, update
from sqlalchemy.exc import IntegrityError

from brief_crew import config as project_config
from brief_crew.builder import mcp as mcp_module
from brief_crew.builder import skills as skills_module
from brief_crew.builder import tools as tools_module
from brief_crew.service.persistence import (
    PostgresFlowPersistence,
    mcp_servers,
    user_skills,
    user_tools,
    utcnow,
)

__all__ = [
    "AttachmentNotYours",
    "CustomToolStore",
    "McpServerStore",
    "NameTaken",
    "SkillBodyUnreadable",
    "SkillStore",
    "TooManyRows",
]

_MINT_ATTEMPTS = 4


class AttachmentNotYours(LookupError):
    """Absent, deleted or somebody else's. One exception for all three.

    The route answers 404 rather than 403 for the reason `store.py` already
    gives: a 403 confirms the row exists, and confirming that about a stranger's
    id is the oracle every other refusal in this service avoids.
    """


class NameTaken(ValueError):
    """A per-user unique name collided. The author picks another."""


class TooManyRows(ValueError):
    """The per-user ceiling. Carries the ceiling in its sentence."""


class SkillBodyUnreadable(RuntimeError):
    """The row is here and its `SKILL.md` is not readable. Names the path.

    A 500 rather than a 404: the row exists and the caller owns it, so this is
    the server failing to keep its own promise, not a caller asking for
    something absent. The path is in the sentence because the one time this
    fired for real, the path *was* the bug.
    """


def _mint(prefix: str) -> str:
    """`<prefix>_` + 12 hex, the shape `config.py` pins for all three."""

    return f"{prefix}_{secrets.token_hex(6)}"


def _owner(user_id: Any) -> str:
    text = str(user_id or "").strip()
    if not text:
        raise AttachmentNotYours("this row has an owner and this caller has none")
    return text


def _aware(value: Any) -> datetime | None:
    if value is None:
        return None
    if isinstance(value, datetime) and value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value


# --------------------------------------------------------------------------
# Custom HTTP tools - plan 06 D7
# --------------------------------------------------------------------------
class CustomToolStore:
    """`user_tools`: a schema grid and a request template, never code."""

    __slots__ = ("_store",)

    _ID = re.compile(project_config.CUSTOM_TOOL_ID_PATTERN)

    def __init__(self, store: PostgresFlowPersistence) -> None:
        self._store = store

    @staticmethod
    def _spec(row: Mapping[str, Any]) -> tools_module.CustomToolSpec:
        return tools_module.custom_tool_from_row(row)

    def list(self, user_id: Any) -> list[tools_module.CustomToolSpec]:
        owner = _owner(user_id)
        with self._store.connect() as connection:
            rows = (
                connection.execute(
                    select(user_tools)
                    .where(user_tools.c.user_id == owner)
                    .order_by(user_tools.c.updated_at.desc(), user_tools.c.id)
                )
                .mappings()
                .all()
            )
        specs: list[tools_module.CustomToolSpec] = []
        for row in rows:
            try:
                specs.append(self._spec(row))
            except tools_module.CustomToolError:
                # Re-validated on the way OUT, and a row that no longer parses
                # is skipped rather than allowed to break the whole list. The
                # document referencing it validates `tool-unknown`, which is the
                # honest answer and the one the author can act on.
                continue
        return specs

    def get(self, user_id: Any, tool_id: str) -> tools_module.CustomToolSpec:
        owner = _owner(user_id)
        if not self._ID.match(str(tool_id)):
            raise AttachmentNotYours(str(tool_id))
        with self._store.connect() as connection:
            row = (
                connection.execute(
                    select(user_tools).where(
                        user_tools.c.id == tool_id, user_tools.c.user_id == owner
                    )
                )
                .mappings()
                .one_or_none()
            )
        if row is None:
            raise AttachmentNotYours(str(tool_id))
        return self._spec(row)

    def exists(self, user_id: Any, tool_id: str) -> bool:
        try:
            self.get(user_id, tool_id)
        except (AttachmentNotYours, tools_module.CustomToolError):
            return False
        return True

    def create(
        self, user_id: Any, spec: tools_module.CustomToolSpec
    ) -> tools_module.CustomToolSpec:
        owner = _owner(user_id)
        with self._store.connect() as connection:
            count = connection.execute(
                select(user_tools.c.id).where(user_tools.c.user_id == owner)
            ).all()
        if len(count) >= project_config.MAX_CUSTOM_TOOLS_PER_USER:
            raise TooManyRows(
                f"you have {len(count)} custom tools and the ceiling is "
                f"{project_config.MAX_CUSTOM_TOOLS_PER_USER}; delete one first"
            )
        now = utcnow()
        for attempt in range(_MINT_ATTEMPTS):
            tool_id = _mint("ut")
            try:
                with self._store.begin() as connection:
                    connection.execute(
                        insert(user_tools).values(
                            id=tool_id,
                            user_id=owner,
                            name=spec.name,
                            description=spec.description,
                            input_schema=spec.json_schema(),
                            request=_request_json(spec),
                            credential_id=spec.credential_id,
                            created_at=now,
                            updated_at=now,
                        )
                    )
            except IntegrityError:
                if attempt + 1 == _MINT_ATTEMPTS:
                    raise NameTaken(
                        f"you already have a tool called {spec.name!r}"
                    ) from None
                # Either the name collided - which is the constraint doing its
                # job - or twelve hex characters did, at 2^-48. Retrying answers
                # the second and re-raises on the first.
                if self._name_taken(owner, spec.name):
                    raise NameTaken(
                        f"you already have a tool called {spec.name!r}"
                    ) from None
                continue
            return tools_module.CustomToolSpec(
                id=tool_id,
                name=spec.name,
                description=spec.description,
                properties=spec.properties,
                request=spec.request,
                credential_id=spec.credential_id,
            )
        raise RuntimeError("could not mint a tool id")  # pragma: no cover

    def _name_taken(self, owner: str, name: str) -> bool:
        with self._store.connect() as connection:
            return (
                connection.execute(
                    select(user_tools.c.id).where(
                        user_tools.c.user_id == owner, user_tools.c.name == name
                    )
                ).first()
                is not None
            )

    def update(
        self, user_id: Any, tool_id: str, spec: tools_module.CustomToolSpec
    ) -> tools_module.CustomToolSpec:
        owner = _owner(user_id)
        if not self._ID.match(str(tool_id)):
            raise AttachmentNotYours(str(tool_id))
        try:
            with self._store.begin() as connection:
                result = connection.execute(
                    update(user_tools)
                    .where(user_tools.c.id == tool_id, user_tools.c.user_id == owner)
                    .values(
                        name=spec.name,
                        description=spec.description,
                        input_schema=spec.json_schema(),
                        request=_request_json(spec),
                        credential_id=spec.credential_id,
                        updated_at=utcnow(),
                    )
                )
        except IntegrityError as exc:
            raise NameTaken(f"you already have a tool called {spec.name!r}") from exc
        if result.rowcount != 1:
            raise AttachmentNotYours(str(tool_id))
        return tools_module.CustomToolSpec(
            id=str(tool_id),
            name=spec.name,
            description=spec.description,
            properties=spec.properties,
            request=spec.request,
            credential_id=spec.credential_id,
        )

    def delete(self, user_id: Any, tool_id: str) -> None:
        owner = _owner(user_id)
        if not self._ID.match(str(tool_id)):
            raise AttachmentNotYours(str(tool_id))
        with self._store.begin() as connection:
            result = connection.execute(
                delete(user_tools).where(
                    user_tools.c.id == tool_id, user_tools.c.user_id == owner
                )
            )
        if result.rowcount != 1:
            raise AttachmentNotYours(str(tool_id))


def _request_json(spec: tools_module.CustomToolSpec) -> dict[str, Any]:
    request = spec.request
    return {
        "method": request.method,
        "url": request.url,
        "header_name": request.header_name,
        "header_template": request.header_template,
        "body_template": request.body_template,
        "timeout_seconds": request.timeout_seconds,
        "max_response_bytes": request.max_response_bytes,
    }


# --------------------------------------------------------------------------
# MCP servers - plan 07 C12
# --------------------------------------------------------------------------
class McpServerStore:
    """`mcp_servers`: the address, the credential references, the last discovery.

    There is no `header_name` column and none is needed: an `mcp_header`
    credential's two fields ARE the header's name and value
    (`config.CREDENTIAL_FIELDS`), so the plaintext name travels with the secret
    it labels rather than beside it in a second place.
    """

    __slots__ = ("_store",)

    _ID = re.compile(project_config.MCP_SERVER_ID_PATTERN)

    def __init__(self, store: PostgresFlowPersistence) -> None:
        self._store = store

    @staticmethod
    def _record(row: Mapping[str, Any]) -> mcp_module.McpServerRecord:
        return mcp_module.McpServerRecord(
            id=str(row["id"]),
            user_id=str(row["user_id"]),
            label=str(row["label"]),
            transport=str(row["transport"]),
            url=row["url"],
            command=row["command"],
            args=tuple(row["args"] or ()),
            header_credential_id=row["header_credential_id"],
            env_credential_id=row["env_credential_id"],
            status=str(row["status"]),
            discovered_tools=tuple(
                mcp_module.DiscoveredTool.of(entry)
                for entry in (row["discovered_tools"] or ())
            ),
            discovered_at=_aware(row["discovered_at"]),
            last_error=row["last_error"],
        )

    def list(self, user_id: Any) -> list[mcp_module.McpServerRecord]:
        owner = _owner(user_id)
        with self._store.connect() as connection:
            rows = (
                connection.execute(
                    select(mcp_servers)
                    .where(mcp_servers.c.user_id == owner)
                    .order_by(mcp_servers.c.updated_at.desc(), mcp_servers.c.id)
                )
                .mappings()
                .all()
            )
        return [self._record(row) for row in rows]

    def get(self, user_id: Any, server_id: str) -> mcp_module.McpServerRecord:
        owner = _owner(user_id)
        if not self._ID.match(str(server_id)):
            raise AttachmentNotYours(str(server_id))
        with self._store.connect() as connection:
            row = (
                connection.execute(
                    select(mcp_servers).where(
                        mcp_servers.c.id == server_id, mcp_servers.c.user_id == owner
                    )
                )
                .mappings()
                .one_or_none()
            )
        if row is None:
            raise AttachmentNotYours(str(server_id))
        return self._record(row)

    def lookup(self, user_id: Any) -> Any:
        """This caller's servers as the `(server_id) -> record | None` mcp_problems wants."""

        def resolver(server_id: str) -> mcp_module.McpServerRecord | None:
            try:
                return self.get(user_id, server_id)
            except AttachmentNotYours:
                return None

        return resolver

    def create(
        self,
        user_id: Any,
        *,
        label: str,
        transport: str,
        url: str | None = None,
        command: str | None = None,
        args: Sequence[str] = (),
        header_credential_id: str | None = None,
        env_credential_id: str | None = None,
    ) -> mcp_module.McpServerRecord:
        owner = _owner(user_id)
        with self._store.connect() as connection:
            existing = connection.execute(
                select(mcp_servers.c.id).where(mcp_servers.c.user_id == owner)
            ).all()
        if len(existing) >= project_config.MCP_MAX_SERVERS_PER_USER:
            raise TooManyRows(
                f"you have {len(existing)} MCP servers and the ceiling is "
                f"{project_config.MCP_MAX_SERVERS_PER_USER}; delete one first"
            )
        now = utcnow()
        server_id = _mint("ms")
        with self._store.begin() as connection:
            connection.execute(
                insert(mcp_servers).values(
                    id=server_id,
                    user_id=owner,
                    label=label,
                    transport=transport,
                    url=url,
                    command=command,
                    args=list(args),
                    header_credential_id=header_credential_id,
                    env_credential_id=env_credential_id,
                    status="pending",
                    discovered_tools=None,
                    discovered_at=None,
                    last_error=None,
                    created_at=now,
                    updated_at=now,
                )
            )
        return self.get(owner, server_id)

    def update(
        self, user_id: Any, server_id: str, **values: Any
    ) -> mcp_module.McpServerRecord:
        """An edit resets `status` to `pending`: a changed address is a server
        nobody has discovered yet, and leaving an old tool list authorised would
        let a document bind names the new address may not carry."""

        owner = _owner(user_id)
        if not self._ID.match(str(server_id)):
            raise AttachmentNotYours(str(server_id))
        payload = {key: value for key, value in values.items() if value is not None}
        payload.setdefault("status", "pending")
        payload["updated_at"] = utcnow()
        if "args" in payload:
            payload["args"] = list(payload["args"])
        with self._store.begin() as connection:
            result = connection.execute(
                update(mcp_servers)
                .where(mcp_servers.c.id == server_id, mcp_servers.c.user_id == owner)
                .values(**payload)
            )
        if result.rowcount != 1:
            raise AttachmentNotYours(str(server_id))
        return self.get(owner, server_id)

    def record_discovery(
        self, user_id: Any, server_id: str, result: mcp_module.DiscoveryResult
    ) -> mcp_module.McpServerRecord:
        owner = _owner(user_id)
        with self._store.begin() as connection:
            updated = connection.execute(
                update(mcp_servers)
                .where(mcp_servers.c.id == server_id, mcp_servers.c.user_id == owner)
                .values(
                    status=result.status,
                    discovered_tools=[tool.as_dict() for tool in result.tools]
                    if result.tools
                    else None,
                    discovered_at=result.discovered_at,
                    last_error=result.error,
                    updated_at=utcnow(),
                )
            )
        if updated.rowcount != 1:
            raise AttachmentNotYours(str(server_id))
        return self.get(owner, server_id)

    def delete(self, user_id: Any, server_id: str) -> None:
        owner = _owner(user_id)
        if not self._ID.match(str(server_id)):
            raise AttachmentNotYours(str(server_id))
        with self._store.begin() as connection:
            result = connection.execute(
                delete(mcp_servers).where(
                    mcp_servers.c.id == server_id, mcp_servers.c.user_id == owner
                )
            )
        if result.rowcount != 1:
            raise AttachmentNotYours(str(server_id))


# --------------------------------------------------------------------------
# Skill packs - plan 08 C11
# --------------------------------------------------------------------------
class SkillStore:
    """`user_skills`: the index row for a pack whose body lives on disk.

    The shipped table (15 C10) carries `path` and `bytes` and its own comment
    says the file is the pack, so `create` writes the file and then the row, and
    `get` reads the file back. Plan 08 D1 wanted the row to be the truth and a
    `body` column to hold it; that is a C10 change and it is recorded in the
    plan's Status rather than made here.
    """

    __slots__ = ("_store",)

    _ID = re.compile(project_config.SKILL_ID_PATTERN)

    def __init__(self, store: PostgresFlowPersistence) -> None:
        self._store = store

    # -------------------------------------------------------------- built-ins
    @staticmethod
    def builtins() -> tuple[skills_module.SkillPack, ...]:
        return skills_module.load_builtins()

    # ------------------------------------------------------------------ reads
    def list(self, user_id: Any) -> list[skills_module.SkillPack]:
        """Every built-in, then this caller's own. Anonymous sees the built-ins.

        Built-ins first because a fresh account has nothing else, and a palette
        whose first row is empty teaches an author that the feature is empty.
        """

        packs = list(self.builtins())
        owner = str(user_id or "").strip()
        if not owner:
            return packs
        with self._store.connect() as connection:
            rows = (
                connection.execute(
                    select(user_skills)
                    .where(user_skills.c.user_id == owner)
                    .order_by(user_skills.c.updated_at.desc(), user_skills.c.id)
                )
                .mappings()
                .all()
            )
        for row in rows:
            pack = self._pack(row)
            if pack is not None:
                packs.append(pack)
        return packs

    def _pack(self, row: Mapping[str, Any]) -> skills_module.SkillPack | None:
        path = skills_module.resolve_stored_path(str(row["path"]))
        try:
            body = path.read_text(encoding="utf-8")
        except OSError as exc:
            # This branch used to blank the body and carry on, on the reasoning
            # that "the disk is a cache a restart can empty". It is now proven
            # to have hidden a PATH BUG rather than a missing file for the whole
            # life of the feature: on the shipped relative `SKILLS_ROOT` every
            # user pack read back as `body=""` while its 107 bytes sat on disk,
            # and 2,420 green tests could not see it because every one of them
            # patches the root to an absolute tempdir.
            #
            # So it reports. A row whose file is genuinely gone means the
            # author's content is gone - there is no `body` column to fall back
            # to - and telling them that loudly is strictly better than handing
            # back an empty document they might then save over. The cost is
            # accepted and named: one unreadable file fails the whole palette
            # rather than quietly shortening it.
            raise SkillBodyUnreadable(
                f"this skill's {skills_module.SKILL_FILENAME} could not be read at "
                f"{path}"
            ) from exc
        try:
            parsed = skills_module.parse_pack(body) if body else None
        except skills_module.SkillError:
            parsed = None
        return skills_module.SkillPack(
            id=str(row["id"]),
            name=str(row["name"]),
            description=str(row["description"]),
            version=parsed.version if parsed else 1,
            body=body,
            owner="me",
            user_id=str(row["user_id"]),
            updated_at=_aware(row["updated_at"]),
        )

    def get(self, user_id: Any, skill_id: str) -> skills_module.SkillPack:
        for pack in self.builtins():
            if pack.id == skill_id:
                return pack
        owner = _owner(user_id)
        if not self._ID.match(str(skill_id)):
            raise AttachmentNotYours(str(skill_id))
        with self._store.connect() as connection:
            row = (
                connection.execute(
                    select(user_skills).where(
                        user_skills.c.id == skill_id, user_skills.c.user_id == owner
                    )
                )
                .mappings()
                .one_or_none()
            )
        if row is None:
            raise AttachmentNotYours(str(skill_id))
        pack = self._pack(row)
        if pack is None:  # pragma: no cover - `_pack` never answers None today
            raise AttachmentNotYours(str(skill_id))
        return pack

    def lookup(self, user_id: Any) -> Any:
        """The `(skill_id) -> pack | None` predicate `skill_problems` wants."""

        def resolver(skill_id: str) -> skills_module.SkillPack | None:
            try:
                return self.get(user_id, skill_id)
            except AttachmentNotYours:
                return None

        return resolver

    # ----------------------------------------------------------------- writes
    def create(self, user_id: Any, body: str) -> skills_module.SkillPack:
        owner = _owner(user_id)
        parsed = skills_module.parse_pack(body, owner="me")
        with self._store.connect() as connection:
            existing = connection.execute(
                select(user_skills.c.id).where(user_skills.c.user_id == owner)
            ).all()
        if len(existing) >= project_config.MAX_SKILLS_PER_USER:
            raise TooManyRows(
                f"you have {len(existing)} skills and the ceiling is "
                f"{project_config.MAX_SKILLS_PER_USER}; delete one first"
            )
        skill_id = _mint("sk")
        pack = skills_module.SkillPack(
            id=skill_id,
            name=parsed.name,
            description=parsed.description,
            version=parsed.version,
            body=body,
            owner="me",
            user_id=owner,
        )
        directory = skills_module.materialise(pack)
        now = utcnow()
        try:
            with self._store.begin() as connection:
                connection.execute(
                    insert(user_skills).values(
                        id=skill_id,
                        user_id=owner,
                        name=pack.name,
                        description=pack.description,
                        path=str(directory / skills_module.SKILL_FILENAME),
                        bytes=pack.size_bytes,
                        created_at=now,
                        updated_at=now,
                    )
                )
        except IntegrityError as exc:
            raise NameTaken(f"you already have a skill called {pack.name!r}") from exc
        return skills_module.SkillPack(
            id=skill_id,
            name=pack.name,
            description=pack.description,
            version=pack.version,
            body=body,
            owner="me",
            user_id=owner,
            updated_at=now,
        )

    def update(self, user_id: Any, skill_id: str, body: str) -> skills_module.SkillPack:
        """A `PUT` bumps `metadata.version` in the file, because the shipped
        table has no `version` column to bump."""

        owner = _owner(user_id)
        current = self.get(owner, skill_id)
        if current.owner == "builtin":
            # 404, not 403: a built-in is readable by everyone, so confirming it
            # exists costs nothing - but "you may not edit this" and "there is no
            # such row of yours" are one answer here, matching every other route.
            raise AttachmentNotYours(str(skill_id))
        bumped_body = skills_module.bumped(body)
        parsed = skills_module.parse_pack(bumped_body, owner="me")
        pack = skills_module.SkillPack(
            id=str(skill_id),
            name=parsed.name,
            description=parsed.description,
            version=parsed.version,
            body=bumped_body,
            owner="me",
            user_id=owner,
        )
        directory = skills_module.materialise(pack)
        now = utcnow()
        try:
            with self._store.begin() as connection:
                result = connection.execute(
                    update(user_skills)
                    .where(
                        user_skills.c.id == skill_id, user_skills.c.user_id == owner
                    )
                    .values(
                        name=pack.name,
                        description=pack.description,
                        path=str(directory / skills_module.SKILL_FILENAME),
                        bytes=pack.size_bytes,
                        updated_at=now,
                    )
                )
        except IntegrityError as exc:
            raise NameTaken(f"you already have a skill called {pack.name!r}") from exc
        if result.rowcount != 1:
            raise AttachmentNotYours(str(skill_id))
        return skills_module.SkillPack(
            id=str(skill_id),
            name=pack.name,
            description=pack.description,
            version=pack.version,
            body=bumped_body,
            owner="me",
            user_id=owner,
            updated_at=now,
        )

    def delete(self, user_id: Any, skill_id: str) -> None:
        owner = _owner(user_id)
        if not self._ID.match(str(skill_id)):
            raise AttachmentNotYours(str(skill_id))
        with self._store.begin() as connection:
            result = connection.execute(
                delete(user_skills).where(
                    user_skills.c.id == skill_id, user_skills.c.user_id == owner
                )
            )
        if result.rowcount != 1:
            raise AttachmentNotYours(str(skill_id))
