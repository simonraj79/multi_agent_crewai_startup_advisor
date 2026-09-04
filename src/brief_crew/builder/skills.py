"""Skill packs: parse, store, materialise, attach - plan 08.

"Skills = knowledge." A skill gives an agent domain knowledge without bloating
its prompt: name and description load at run start, and the body loads only
when a task matches. **That is not a feature to build; it is a feature to
expose.** CrewAI 1.15.18 implements the whole mechanism - `SkillFrontmatter`,
three disclosure levels, `discover_skills` at METADATA, `activate_skill` to
INSTRUCTIONS, and `skills/tool.py` letting an agent activate one mid-execution.
This product's entire job is to store a pack, put it on disk, and hand
`Agent.skills` a typed object.

**Never a `str`**: a bare string in `Agent.skills` is an AMP registry lookup
(`crewai/skills/registry.py`), exactly the trap `mcps` sets.

**And not a bare `Path` either**, which is where plan 08's criterion 5 and the
package part company. `Agent.skills` does accept a `Path`, but `load_skill`
treats it as a *search* path and `discover_skills` iterates its CHILDREN - so
the pack's own directory loads nothing (measured: `[]`) and its parent loads
every sibling pack. `loaded_skill` therefore passes a `Skill` object, built by
CrewAI's own `load_skill_metadata` from the materialised directory. Still not a
string, still the package's loader, and it names exactly the one pack the author
attached. `search_path` exists so a test can prove the on-disk layout is a legal
CrewAI search path.

**Parse with the package's parser and refuse with its sentence.**
`parse_frontmatter` plus `SkillFrontmatter` is the only validator - so the
package's own name pattern is the only pattern, and there is no second one to
drift. A `name: "Bad Name"` is refused with pydantic's message about the
pattern, which names the pattern; writing our own would mean maintaining a
regex that has to stay equal to one we do not own.

**Where the plan and the shipped schema disagree, the shipped schema wins.**
Plan 08 D1 specifies `user_skills` with `body`, `version` and `size_bytes`
columns and says the row is the truth. The table plan 15 actually shipped
(C10) carries `path` and `bytes`, and its own comment calls itself "the index
row for a SKILL.md pack **on disk**". So the disk is the store and the row is
the index, `version` lives in the frontmatter's `metadata.version` where D2
already put it, and there is no `body` column to write. The consequence is
recorded rather than papered over: on an ephemeral disk a user's own pack does
not survive a restart, and closing that is a C10 change the Integrator owns.
Built-ins are unaffected - they are committed files.
"""

from __future__ import annotations

import io
import os
import pathlib
import zipfile
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

from brief_crew import config as project_config
from brief_crew.builder.bounds import Problem
from brief_crew.builder.document import BuilderDocument, SkillConfig

# --------------------------------------------------------------------------
# Problem code - declared at module level in the shape the client's grep finds
# --------------------------------------------------------------------------
#: A `skill_id` that is neither a built-in nor one of this caller's packs. One
#: code for absent, deleted and foreign - the `credential-missing` rule.
SKILL_UNKNOWN = "skill-unknown"

#: The file every pack is, by CrewAI's own constant name for it.
SKILL_FILENAME = "SKILL.md"


class SkillError(ValueError):
    """A pack that will not parse. Carries the package's own sentence."""


@dataclass(frozen=True, slots=True)
class SkillPack:
    """One pack: the row's fields plus the body, which lives on disk.

    `owner` is `builtin` or `me`. A built-in has no `user_id` and cannot be
    edited or deleted through the API; every user sees all four, which is what
    makes a fresh account's palette non-empty.
    """

    id: str
    name: str
    description: str
    version: int
    body: str
    owner: str = "builtin"
    user_id: str | None = None
    updated_at: datetime | None = None

    @property
    def size_bytes(self) -> int:
        return len(self.body.encode("utf-8"))

    def summary(self) -> dict[str, Any]:
        """The list shape - deliberately WITHOUT the body.

        A list of thirty packs each carrying 64 KiB is 2 MiB of JSON to draw a
        palette. `GET /api/builder/skills/{id}` is where a body comes from.
        """

        return {
            "id": self.id,
            "name": self.name,
            "description": self.description,
            "version": self.version,
            "owner": self.owner,
            "size_bytes": self.size_bytes,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
        }

    def detail(self) -> dict[str, Any]:
        return {**self.summary(), "body": self.body}


# --------------------------------------------------------------------------
# Parsing - D2
# --------------------------------------------------------------------------
def parse_pack(body: str, *, skill_id: str = "", owner: str = "me") -> SkillPack:
    """A `SKILL.md` into a pack, or `SkillError` with the parser's own sentence.

    `version` is `metadata.version` when present, else 1 - D2's rule, and with
    no `version` column on the shipped table the frontmatter is now the ONLY
    place it lives, which is if anything more honest: the version an author
    reads in the file is the version the card shows.
    """

    from crewai.skills.models import SkillFrontmatter
    from crewai.skills.parser import SkillParseError, parse_frontmatter

    encoded = len(body.encode("utf-8"))
    if encoded > project_config.MAX_SKILL_BYTES:
        raise SkillError(
            f"a skill is at most {project_config.MAX_SKILL_BYTES} bytes; this one "
            f"is {encoded}"
        )
    try:
        raw, _text = parse_frontmatter(body)
    except SkillParseError as exc:
        raise SkillError(str(exc)) from exc
    try:
        frontmatter = SkillFrontmatter(**raw)
    except Exception as exc:  # pydantic ValidationError
        raise SkillError(_first_sentence(exc)) from exc
    metadata = frontmatter.metadata or {}
    try:
        version = int(str(metadata.get("version", 1)))
    except (TypeError, ValueError):
        version = 1
    return SkillPack(
        id=skill_id,
        name=frontmatter.name,
        description=frontmatter.description,
        version=max(version, 1),
        body=body,
        owner=owner,
    )


def bumped(body: str) -> str:
    """The same pack with `metadata.version` one higher - D2's `PUT` rule.

    Rewriting the author's own frontmatter is a real cost and it is the smaller
    one: with no `version` column, the alternative is a version nothing records,
    and a card that says `v1` forever is worse than a file that says `v2`.
    """

    pack = parse_pack(body)
    target = pack.version + 1
    lines = body.splitlines(keepends=True)
    out: list[str] = []
    seen_metadata = False
    replaced = False
    for line in lines:
        stripped = line.strip()
        if stripped.startswith("metadata:"):
            seen_metadata = True
        elif seen_metadata and stripped.startswith("version:") and not replaced:
            indent = line[: len(line) - len(line.lstrip())]
            out.append(f'{indent}version: "{target}"\n')
            replaced = True
            continue
        elif stripped == "---" and seen_metadata and not replaced:
            out.append(f'  version: "{target}"\n')
            replaced = True
        out.append(line)
    if replaced:
        return "".join(out)
    # No `metadata:` block at all: insert one just before the closing delimiter
    # of the frontmatter, which is the second `---`.
    seen = 0
    out = []
    for line in lines:
        if line.strip() == "---":
            seen += 1
            if seen == 2:
                out.append(f'metadata:\n  version: "{target}"\n')
        out.append(line)
    return "".join(out)


def _first_sentence(exc: BaseException) -> str:
    """One line an author can act on, out of pydantic's four.

    A pydantic error is a header, a field name, an indented message and a
    documentation link. The useful sentence is the third - it names the pattern
    the value missed - and it is what this returns, prefixed by the field.

    The `[type=..., input_value=..., input_type=...]` tail is CUT, and that is
    not tidiness: it echoes the offending value back into an HTTP response body,
    and a route that echoes its input is the shape
    `service/credentials_api.py` parses by hand specifically to avoid.
    """

    lines = [line.rstrip() for line in str(exc).strip().splitlines()]
    for index, line in enumerate(lines):
        stripped = line.strip()
        if not line.startswith("  ") or not stripped:
            continue
        if stripped.startswith("For further information"):
            continue
        message = stripped.split(" [type=", 1)[0]
        field = lines[index - 1].strip() if index else ""
        return f"{field}: {message}" if field else message
    return lines[0] if lines else type(exc).__name__


# --------------------------------------------------------------------------
# The zip import - D2's second door
# --------------------------------------------------------------------------
#: The directory names a pack may NOT carry. `scripts/` is code, and
#: `AGENTS.md:67` stands: nothing a user uploads executes here. `references/`
#: and `assets/` are v2 rather than forbidden, but a v1 row holds one file, so
#: an archive carrying them would import as something other than what it is.
FORBIDDEN_PACK_DIRS: tuple[str, ...] = ("scripts",)


def read_pack_zip(raw: bytes) -> str:
    """The one `SKILL.md` inside an archive, or `SkillError` saying why not.

    The size is refused on the COMPRESSED bytes, before anything is expanded:
    a zip bomb is small until it is read, and the point of a limit is to apply
    it while the input is still small.
    """

    if len(raw) > project_config.MAX_SKILL_IMPORT_BYTES:
        raise SkillError(
            f"a skill archive is at most {project_config.MAX_SKILL_IMPORT_BYTES} "
            f"bytes; this one is {len(raw)}"
        )
    try:
        archive = zipfile.ZipFile(io.BytesIO(raw))
    except zipfile.BadZipFile as exc:
        raise SkillError(f"that is not a zip archive ({exc})") from exc
    names = [name for name in archive.namelist() if not name.endswith("/")]
    for name in names:
        parts = pathlib.PurePosixPath(name).parts
        if any(part in FORBIDDEN_PACK_DIRS for part in parts):
            raise SkillError(
                f"{name!r} is inside a scripts directory. A skill is knowledge, not "
                "code: nothing in a pack executes here, so a pack that ships a "
                "script is a pack whose author expects something this will not do"
            )
        if ".." in parts or pathlib.PurePosixPath(name).is_absolute():
            raise SkillError(f"{name!r} escapes the archive root")
    candidates = [
        name for name in names if pathlib.PurePosixPath(name).name == SKILL_FILENAME
    ]
    if not candidates:
        raise SkillError(f"the archive holds no {SKILL_FILENAME}")
    if len(candidates) > 1:
        raise SkillError(
            f"the archive holds {len(candidates)} {SKILL_FILENAME} files and a pack "
            "is one skill"
        )
    with archive.open(candidates[0]) as handle:
        body = handle.read(project_config.MAX_SKILL_BYTES + 1)
    if len(body) > project_config.MAX_SKILL_BYTES:
        raise SkillError(
            f"{SKILL_FILENAME} is at most {project_config.MAX_SKILL_BYTES} bytes"
        )
    return body.decode("utf-8", "replace")


# --------------------------------------------------------------------------
# The disk - D1
# --------------------------------------------------------------------------
def skills_root() -> pathlib.Path:
    return pathlib.Path(project_config.SKILLS_ROOT)


def builtin_root() -> pathlib.Path:
    return skills_root() / "builtin"


def pack_directory(pack: SkillPack) -> pathlib.Path:
    """Where this pack's `SKILL.md` lives.

    A built-in is a committed file under `builtin/<name>/`; a user's pack is
    under `users/<user_id>/<name>/`. The name is the directory, which is what
    `discover_skills` expects and is why the package's name pattern is the only
    validator: a name that is not a legal directory is refused at parse.
    """

    if pack.owner == "builtin" or pack.user_id is None:
        return builtin_root() / pack.name
    return skills_root() / "users" / _safe_segment(pack.user_id) / pack.name


def _safe_segment(value: str) -> str:
    """A user id as one path segment. Ids are opaque and can hold anything."""

    return "".join(
        character if character.isalnum() or character in "-_" else "_"
        for character in str(value)
    )[:128]


def materialise(pack: SkillPack) -> pathlib.Path:
    """Write the pack if it is absent or stale, and return its DIRECTORY.

    Stale is decided by content, not by a timestamp: a mtime comparison against
    `updated_at` reports the clock on two machines rather than the file, and
    this runs on Windows locally and Linux in production. Reading 64 KiB to
    decide whether to write 64 KiB is not a cost worth a wrong answer.

    Boot does not pre-materialise. The first run that attaches a skill does,
    which is `builder_rehydrate`'s lesson applied by construction: a restart
    costs one file write, never a lost skill.
    """

    directory = pack_directory(pack)
    target = directory / SKILL_FILENAME
    if target.exists():
        try:
            if target.read_text(encoding="utf-8") == pack.body:
                return directory
        except OSError:  # pragma: no cover - unreadable file is rewritten
            pass
    directory.mkdir(parents=True, exist_ok=True)
    target.write_text(pack.body, encoding="utf-8")
    return directory


def search_path(pack: SkillPack) -> pathlib.Path:
    """The directory `discover_skills` would SCAN to find this pack.

    **A package fact the plan did not have, and it changes what the runtime
    passes.** `Agent.skills` accepts a `Path`, and `load_skill` treats that path
    as a *search* path: `discover_skills` iterates its CHILDREN looking for
    `<dir>/SKILL.md`. So handing it the pack's own directory loads **nothing**
    (measured: `load_skill(Path('data/skills/builtin/report-writing'))` answers
    `[]`), and handing it the parent loads every sibling - all four built-ins
    when the author attached one.

    Neither is what an attachment means, so `loaded_skill` below passes a typed
    `Skill` object instead, which `Agent.skills` also accepts and which names
    exactly one pack. This function exists for the layout assertion: the parent
    IS a legal CrewAI search path, and a test proves it.
    """

    return pack_directory(pack).parent


def loaded_skill(pack: SkillPack) -> Any:
    """The `Skill` object to hand `Agent(skills=[...])`, at METADATA level.

    Built with the package's own `load_skill_metadata`, so the frontmatter
    rules, the directory-name check and the disclosure level are all CrewAI's.
    The body is NOT read here: METADATA is the point - the agent sees the name
    and description, and `skills/tool.py` promotes to INSTRUCTIONS only when the
    agent decides the task matches.
    """

    from crewai.skills.loader import load_skill_metadata

    return load_skill_metadata(materialise(pack))


def load_builtins() -> tuple[SkillPack, ...]:
    """The four committed packs, parsed with the package's parser.

    Parsed rather than transcribed, so a CrewAI upgrade that tightens the
    frontmatter fails a test rather than a run - which is criterion 10, and the
    only reason these are files rather than Python strings.
    """

    packs: list[SkillPack] = []
    for name in project_config.BUILTIN_SKILL_NAMES:
        path = builtin_root() / name / SKILL_FILENAME
        if not path.exists():
            continue
        pack = parse_pack(path.read_text(encoding="utf-8"), owner="builtin")
        packs.append(
            SkillPack(
                id=builtin_id(name),
                name=pack.name,
                description=pack.description,
                version=pack.version,
                body=pack.body,
                owner="builtin",
            )
        )
    return tuple(packs)


def builtin_id(name: str) -> str:
    """A stable `sk_` id for a built-in, derived from its name.

    Derived rather than minted so it is the same id on every deployment and in
    every test: a document that names `sk_...` for `report-writing` has to keep
    resolving after a redeploy, and a built-in has no row to remember one.
    """

    import hashlib

    digest = hashlib.sha256(f"builtin:{name}".encode("utf-8")).hexdigest()
    return f"sk_{digest[:12]}"


BUILTIN_SKILL_IDS: tuple[str, ...] = tuple(
    builtin_id(name) for name in project_config.BUILTIN_SKILL_NAMES
)


# --------------------------------------------------------------------------
# Events - D6
#
# `skill_frame_details` is the mapping and nothing more: it takes one of
# CrewAI's four skill events and answers with the `details` a frame carries.
# Registering it on the event bus is `events/serializer.py`'s work and that
# module is C6's, owned by plan 10 - so this side is written, tested against
# REAL event objects, and left for the wave that owns the sink to call. A
# mapping with no caller is a smaller debt than a mapping written twice.
# --------------------------------------------------------------------------
#: CrewAI's three integer levels, as the word a console renders. Derived from
#: the package's own constants rather than written down, so a fourth level
#: appearing upstream is a KeyError here rather than a frame that says nothing.
def _disclosure_words() -> dict[int, str]:
    from crewai.skills.models import INSTRUCTIONS, METADATA, RESOURCES

    return {METADATA: "metadata", INSTRUCTIONS: "instructions", RESOURCES: "resources"}


#: `SkillLoadFailedEvent` is the one that also produces a `node_error` frame
#: (C6). It does NOT fail the step: a missing skill degrades an agent - it
#: carries less knowledge - where a missing tool removes a capability it was
#: told it had.
SKILL_LOAD_ERROR_CLASS = "skill_load"


def skill_frame_details(event: Any) -> dict[str, Any]:
    """One skill event as the `details` of an AGENT frame.

    `skill` and `disclosure` are what the run console shows on the agent's card
    at the one moment a skill is visibly doing something - "activated skill
    hn-signal-reading". `error_class` appears only on a failure, which is what
    lets 12 route it without a second event type.
    """

    details: dict[str, Any] = {"skill": str(getattr(event, "skill_name", "") or "")}
    level = getattr(event, "disclosure_level", None)
    if level is not None:
        details["disclosure"] = _disclosure_words().get(int(level), str(level))
    error = getattr(event, "error", None)
    if error:
        details["error_class"] = SKILL_LOAD_ERROR_CLASS
        details["error"] = str(error)[:500]
    return details


# --------------------------------------------------------------------------
# Validation over a document
# --------------------------------------------------------------------------
#: `(skill_id) -> SkillPack | None`, scoped to the caller with built-ins always
#: visible. `None` for the callable means nobody to ask - a built-in id is still
#: checked, because it does not depend on an identity.
SkillLookup = Callable[[str], SkillPack | None]


def skill_problems(
    document: BuilderDocument, *, skills: SkillLookup | None = None
) -> list[Problem]:
    """Every `skill` node naming a pack this caller cannot attach."""

    problems: list[Problem] = []
    for node in document.nodes:
        if node.kind != "skill":
            continue
        config = node.config
        if not isinstance(config, SkillConfig):  # pragma: no cover
            continue
        if config.skill_id in BUILTIN_SKILL_IDS:
            continue
        if skills is None:
            continue
        if skills(config.skill_id) is not None:
            continue
        problems.append(
            Problem(
                code=SKILL_UNKNOWN,
                severity="error",
                message=(
                    f"{node.id} names the skill {config.skill_id}, which is not one of "
                    "yours and is not a built-in; it may have been deleted"
                ),
                node_id=node.id,
            )
        )
    return problems


__all__ = [
    "BUILTIN_SKILL_IDS",
    "FORBIDDEN_PACK_DIRS",
    "SKILL_FILENAME",
    "SKILL_UNKNOWN",
    "SkillError",
    "SkillPack",
    "builtin_id",
    "builtin_root",
    "bumped",
    "load_builtins",
    "materialise",
    "pack_directory",
    "parse_pack",
    "loaded_skill",
    "read_pack_zip",
    "SKILL_LOAD_ERROR_CLASS",
    "skill_frame_details",
    "skill_problems",
    "search_path",
    "skills_root",
]
