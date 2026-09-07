"""Importing a pack from a zip - plan 08 criterion 3.

`scripts/` is the refusal that matters, and it is a refusal rather than a strip.
A pack that ships a script is a pack whose author expects something this product
will not do - `AGENTS.md:67` stands, and nothing a user uploads executes here -
so importing it silently minus the scripts would hand somebody a skill that
quietly does less than it says. The refusal names the entry.

Everything else here is the archive-handling that a route accepting a file has
to get right and that no criterion asks for by name: a path escaping the root, a
zip that is not a zip, two `SKILL.md` files, and a size refused on the
COMPRESSED bytes before anything is expanded - because a zip bomb is small until
it is read.

No cost: the archives are built in memory.
"""

from __future__ import annotations

import io
import pathlib
import tempfile
import unittest
import zipfile
from unittest.mock import patch

from brief_crew import config as project_config
from tests.service.identities import AuthenticatedTwoUserCase

try:  # pragma: no cover
    from fastapi.testclient import TestClient  # noqa: F401

    FASTAPI_AVAILABLE = True
except Exception:  # pragma: no cover
    FASTAPI_AVAILABLE = False

IMPORT = "/api/builder/skills/import"

BODY = """---
name: imported-method
description: An imported method. Use when testing an import.
---

# Imported

Body text.
"""

#: The code the route answers with. Not a canvas problem code and deliberately
#: not declared beside them: it is an import-time refusal, so it never appears
#: on a node and has nothing for the problems dock to anchor.
SKILL_CONTAINS_SCRIPTS = "skill-contains-scripts"


def archive(entries: dict[str, str]) -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as handle:
        for name, content in entries.items():
            handle.writestr(name, content)
    return buffer.getvalue()


@unittest.skipUnless(FASTAPI_AVAILABLE, "FastAPI service extra is not installed")
class SkillImportTests(AuthenticatedTwoUserCase):
    def setUp(self) -> None:
        super().setUp()
        import shutil

        from brief_crew.builder.skills import builtin_root

        root = pathlib.Path(tempfile.mkdtemp(prefix="skills-import-"))
        shutil.copytree(builtin_root(), root / "builtin")
        patcher = patch.object(project_config, "SKILLS_ROOT", str(root))
        patcher.start()
        self.addCleanup(patcher.stop)

    def post(self, raw: bytes, content_type: str = "application/zip"):
        return self.client.post(
            IMPORT,
            content=raw,
            headers={**self.as_alice(), "Content-Type": content_type},
        )

    def test_an_archive_holding_only_a_SKILL_md_imports(self) -> None:
        response = self.post(archive({"SKILL.md": BODY}))
        self.assertEqual(response.status_code, 201, response.text)
        self.assertEqual(response.json()["name"], "imported-method")

    def test_a_nested_SKILL_md_imports_too(self) -> None:
        """A pack zipped WITH its directory is the shape a person actually
        produces, and refusing it would be refusing the common case."""

        response = self.post(archive({"imported-method/SKILL.md": BODY}))
        self.assertEqual(response.status_code, 201, response.text)

    def test_a_scripts_entry_is_refused_by_name_with_the_reason(self) -> None:
        response = self.post(
            archive({"SKILL.md": BODY, "scripts/run.py": "print('hi')"})
        )
        self.assertEqual(response.status_code, 422, response.text)
        detail = response.json()["detail"]
        self.assertEqual(detail["code"], SKILL_CONTAINS_SCRIPTS)
        self.assertIn("scripts/run.py", detail["message"])
        self.assertIn("knowledge, not", detail["message"])

    def test_a_scripts_entry_nested_under_the_pack_is_refused_too(self) -> None:
        """The check is over every path SEGMENT, not a prefix, because a pack
        zipped with its directory puts `scripts/` one level down."""

        response = self.post(
            archive(
                {
                    "imported-method/SKILL.md": BODY,
                    "imported-method/scripts/run.py": "print('hi')",
                }
            )
        )
        self.assertEqual(response.status_code, 422, response.text)

    def test_the_refusal_code_is_the_one_the_plan_asked_for(self) -> None:
        """`skill-contains-scripts`, stated once so a rename is visible.

        It lives in the route rather than beside the canvas problem codes: an
        import-time refusal never appears on a node, so the problems dock has
        nothing to anchor it to and the client mirror has nothing to render.
        """

        from brief_crew.service.builder_api import SKILL_IMPORT_SCRIPTS_CODE

        self.assertEqual(SKILL_IMPORT_SCRIPTS_CODE, SKILL_CONTAINS_SCRIPTS)

        # And it is NOT in the canvas union, which is the other half of the
        # decision: three separate greps sweep every kebab-case module-level
        # constant in `brief_crew/builder/` into `PROBLEM_CODES`, and a code
        # that can never anchor to a node would arrive there as a row the
        # problems dock could not render.
        from brief_crew.service.builder_api import _problem_code_union

        codes, _warnings = _problem_code_union()
        self.assertNotIn(SKILL_CONTAINS_SCRIPTS, codes)

    def test_a_path_escaping_the_archive_root_is_refused(self) -> None:
        response = self.post(archive({"../outside/SKILL.md": BODY}))
        self.assertEqual(response.status_code, 422, response.text)
        self.assertIn("escapes", response.json()["detail"])

    def test_two_SKILL_md_files_are_refused_because_a_pack_is_one_skill(self) -> None:
        response = self.post(
            archive({"a/SKILL.md": BODY, "b/SKILL.md": BODY.replace("imported", "other")})
        )
        self.assertEqual(response.status_code, 422, response.text)
        self.assertIn("one skill", response.json()["detail"])

    def test_an_archive_with_no_SKILL_md_is_refused(self) -> None:
        response = self.post(archive({"README.md": "nothing here"}))
        self.assertEqual(response.status_code, 422, response.text)
        self.assertIn("SKILL.md", response.json()["detail"])

    def test_something_that_is_not_a_zip_is_refused_rather_than_crashing(self) -> None:
        response = self.post(b"this is not a zip archive at all")
        self.assertEqual(response.status_code, 422, response.text)
        self.assertIn("zip", response.json()["detail"])

    def test_the_size_is_refused_on_the_COMPRESSED_bytes(self) -> None:
        """A zip bomb is small until it is read, so the limit is applied while
        the input is still small.

        **413 rather than 422 since audit M9**, and the property is unchanged:
        the archive is refused on its compressed length, before anything is
        expanded. What moved is which door refuses it - the bytes are now
        counted as they ARRIVE, so an oversize body never finishes being read,
        and `read_pack_zip`'s own ceiling stands behind it for the content.
        413 is what the same ceiling answers everywhere else in this service.
        """

        with patch.object(project_config, "MAX_SKILL_IMPORT_BYTES", 64):
            response = self.post(archive({"SKILL.md": BODY}))
        self.assertEqual(response.status_code, 413, response.text)
        self.assertIn("64", response.json()["detail"])

    def test_a_bad_frontmatter_inside_a_good_archive_is_still_the_parsers_refusal(self) -> None:
        response = self.post(
            archive({"SKILL.md": BODY.replace("name: imported-method", 'name: "Nope!"')})
        )
        self.assertEqual(response.status_code, 422, response.text)
        self.assertIn("pattern", response.json()["detail"])

    def test_it_arrives_as_multipart_too(self) -> None:
        """Both, because the plan says multipart and every command-line client
        will send a raw body; accepting one would be a route that works only
        from the browser we happened to write."""

        response = self.client.post(
            IMPORT,
            files={"file": ("pack.zip", archive({"SKILL.md": BODY}), "application/zip")},
            headers=self.as_alice(),
        )
        self.assertEqual(response.status_code, 201, response.text)

    def test_an_anonymous_caller_may_not_import(self) -> None:
        response = self.client.post(
            IMPORT, content=archive({"SKILL.md": BODY}),
            headers={"Content-Type": "application/zip"},
        )
        self.assertEqual(response.status_code, 401, response.text)


@unittest.skipUnless(FASTAPI_AVAILABLE, "FastAPI service extra is not installed")
class ChunkedBodyTests(AuthenticatedTwoUserCase):
    """Audit M9: a chunked body is bounded as it arrives, not after.

    `RequestBodySizeLimitMiddleware` reads `Content-Length` and says so in its
    own docstring, so a `Transfer-Encoding: chunked` POST declares no length
    and walks past it. `_archive_bytes` then did `await request.body()`, which
    buffers the whole stream before `read_pack_zip` gets to measure anything -
    so endless chunks were resident memory in a process the caller does not pay
    for. The bytes are counted while they arrive now, and the read stops at the
    ceiling.
    """

    def _chunks(self, total: int, size: int = 8192):
        """A body sent WITHOUT a Content-Length, because httpx streams an iterator."""

        sent = 0
        while sent < total:
            block = min(size, total - sent)
            sent += block
            yield b"z" * block

    def test_M9_a_chunked_body_over_the_ceiling_is_413_rather_than_buffered(self) -> None:
        limit = project_config.MAX_SKILL_IMPORT_BYTES
        response = self.client.post(
            IMPORT,
            content=self._chunks(limit + 1),
            headers={"Content-Type": "application/zip", **self.as_alice()},
        )
        self.assertEqual(response.status_code, 413, response.text)
        detail = response.json()["detail"]
        self.assertIn(str(limit), detail)
        # And it never learned how big the body actually was, which is the
        # difference between refusing on arrival and refusing after buffering:
        # the old sentence read "...; this one is 262145".
        self.assertNotIn("this one is", detail)
        self.assertNotIn(str(limit + 1), detail)

    def test_M9_the_request_really_was_chunked(self) -> None:
        """Otherwise this would be asserting the Content-Length door instead.

        httpx sends `Transfer-Encoding: chunked` for an iterator body, which is
        the shape that has no declared length for the middleware to read.
        """

        seen: dict[str, str] = {}
        real_send = self.client.send

        def record(request, *args, **kwargs):  # type: ignore[no-untyped-def]
            seen.update({k.lower(): v for k, v in request.headers.items()})
            return real_send(request, *args, **kwargs)

        with patch.object(self.client, "send", record):
            self.client.post(
                IMPORT,
                content=self._chunks(1024),
                headers={"Content-Type": "application/zip", **self.as_alice()},
            )
        self.assertEqual(seen.get("transfer-encoding"), "chunked")
        self.assertNotIn("content-length", seen)

    def test_M9_a_chunked_body_under_the_ceiling_still_imports(self) -> None:
        """The bound must not become a refusal of every streamed upload."""

        payload = archive({"SKILL.md": BODY})

        def one_chunk():
            yield payload

        response = self.client.post(
            IMPORT,
            content=one_chunk(),
            headers={"Content-Type": "application/zip", **self.as_alice()},
        )
        self.assertEqual(response.status_code, 201, response.text)

    def test_M9_an_oversize_multipart_part_is_413_too(self) -> None:
        limit = 512
        with patch.object(project_config, "MAX_SKILL_IMPORT_BYTES", limit):
            response = self.client.post(
                IMPORT,
                files={"file": ("pack.zip", b"z" * (limit + 1), "application/zip")},
                headers=self.as_alice(),
            )
        self.assertEqual(response.status_code, 413, response.text)
        self.assertIn(str(limit), response.json()["detail"])


if __name__ == "__main__":
    unittest.main()
