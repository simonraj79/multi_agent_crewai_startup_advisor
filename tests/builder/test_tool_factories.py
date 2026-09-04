"""Every catalogue factory builds its class from a SUPPLIED credential.

Plan 06 criteria 2, 4 and 5. The property under test is the one D4 states and
the one a reader of `builder/tools.py` should be able to check: a factory never
reads `os.environ` to find a user's key, so a process with no environment at all
still constructs every tool.

**The environment is cleared the way `tests/tools/test_github_feasibility.py`
clears it** - `patch.dict(os.environ, {}, clear=True)` - with one addition that
was measured rather than guessed. `crewai_tools` resolves a home directory at
IMPORT time, so importing it inside a cleared environment raises
`RuntimeError: Could not determine home directory`. The imports are therefore
warmed in `setUpModule`, outside the patch, which leaves the assertion about
what the FACTORY reads rather than about what an import does.

Two classes here read `os.environ` inside `_run` and expose no field to inject
through - `SerperDevTool` and `BraveSearchTool` - and `_env_scoped` binds their
key in a closure and writes it for the length of one call. `test_the_env_scoped
_window_closes` is what makes that a bounded claim rather than a comment.

No cost: nothing here calls a tool. Constructing one opens no socket, with the
single exception noted on `postgres_query`, whose constructor dials the database
and is therefore asserted through a recorder rather than built.
"""

from __future__ import annotations

import os
import unittest
from typing import Any
from unittest import mock

from brief_crew import config as project_config
from brief_crew.builder import tools as tools_module
from brief_crew.builder.tools import (
    ToolBuildError,
    builtin,
    catalogue,
    entry_enabled,
    resolved_tool,
)

#: An obviously fake key with an obviously greppable tail, the shape
#: `tests/service/identities.py` already uses for the vault.
SECRET = "sk-FACTORY-FIXTURE-0123456789-NEVER-FROM-THE-ENVIRONMENT"

#: The plaintext fields the vault would answer with, per kind. Taken from
#: `config.CREDENTIAL_FIELDS` rather than invented, so a kind that gains a field
#: fails here instead of at somebody's first paid run.
FIELDS: dict[str, dict[str, str]] = {
    "firecrawl": {"api_key": SECRET},
    "serper": {"api_key": SECRET},
    "tavily": {"api_key": SECRET},
    "exa": {"api_key": SECRET},
    "brave": {"api_key": SECRET},
    "github": {"token": SECRET},
    "postgres": {"dsn": "postgresql+psycopg://user:pw@db.example.test/app"},
    "http_header": {"name": "Authorization", "value": SECRET},
    "e2b": {"api_key": SECRET},
}

#: Its constructor DIALS the database (`model_post_init` reads the catalogue),
#: so building one in a unit test hangs on DNS. Its own behaviour is asserted
#: below through a recorder instead, which is the more precise test anyway.
DIALS_ON_CONSTRUCTION = {"postgres_query"}


def setUpModule() -> None:
    """Warm the imports before any test clears the environment.

    `crewai_tools` resolves a home directory at import, and a cleared
    environment has none. Without this the whole module fails with
    `Could not determine home directory`, which looks exactly like a defect in
    the code under test and is not one.
    """

    import crewai_tools  # noqa: F401
    import brief_crew.tools.github_feasibility  # noqa: F401
    import brief_crew.tools.hn_sentiment  # noqa: F401
    import brief_crew.tools.market_research  # noqa: F401


class CredentialFieldsTests(unittest.TestCase):
    """The fixture above is the vault's own shape, not this file's opinion."""

    def test_every_kind_a_catalogue_entry_names_is_a_real_credential_kind(self) -> None:
        for entry in catalogue(include_disabled=True):
            for kind in _kinds_of(entry):
                with self.subTest(tool=entry.id, kind=kind):
                    self.assertIn(kind, project_config.CREDENTIAL_KINDS)
                    self.assertEqual(
                        sorted(FIELDS[kind]),
                        sorted(project_config.CREDENTIAL_FIELDS[kind]),
                        "this fixture and config.CREDENTIAL_FIELDS disagree about "
                        f"what a {kind} credential holds",
                    )


def _kinds_of(entry: Any) -> tuple[str, ...]:
    if entry.credential_kind_by_param is not None:
        return tuple(entry.credential_kind_by_param["map"].values())
    return (entry.credential_kind,) if entry.credential_kind else ()


class KeylessEnvironmentTests(unittest.TestCase):
    """Criterion 2: construction succeeds with a supplied key and no environment."""

    def test_every_entry_builds_with_a_supplied_credential_and_an_empty_env(self) -> None:
        for entry in catalogue(include_disabled=True):
            if entry.id in DIALS_ON_CONSTRUCTION:
                continue
            if entry.missing_packages(entry.default_params()):
                # An entry whose distribution is not installed here is refused
                # by name BEFORE construction, and that refusal is its own test
                # below. Skipping it silently would be the interesting failure.
                continue
            with self.subTest(tool=entry.id):
                kind = entry.kind_for(entry.default_params())
                with mock.patch.dict(os.environ, {}, clear=True):
                    tool = entry.factory(
                        entry.default_params(),
                        FIELDS[kind] if kind else None,
                        "warn",
                    )
                self.assertTrue(hasattr(tool, "_run"))

    def test_the_secret_is_never_a_field_the_tool_can_serialise(self) -> None:
        """Criterion 3's property, asserted on the INSTANCE rather than a frame.

        Two of these classes take the key as a pydantic field and two bind it in
        a closure. The ones that take a field are covered by
        `events/redaction.py`'s `SECRET_KEYS` - `apikey`, `headers`, `dsn` and
        `token` are all in it, and the suffix rule catches `gh_token` - so this
        test asserts the OTHER half: that a closure-bound key is not merely
        redacted but genuinely absent from the model.
        """

        for provider in ("serper", "brave"):
            with self.subTest(provider=provider), mock.patch.dict(
                os.environ, {}, clear=True
            ):
                tool = resolved_tool(
                    "web_search",
                    params={"provider": provider},
                    credential=FIELDS[provider],
                    failure_policy="warn",
                )
                self.assertNotIn(SECRET, repr(tool))
                self.assertNotIn(SECRET, str(tool.model_dump()))

    def test_the_env_scoped_window_closes_even_when_the_call_raises(self) -> None:
        """The key is in the environment for one call and not one instruction more.

        Asserted through a raising `_run` because the `finally` is the half that
        matters: an exception mid-call must not leave a key in a process-global
        variable that every other thread can read.
        """

        class Boom:
            def _run(self, *_: Any, **__: Any) -> str:
                assert os.environ["FIXTURE_KEY"] == SECRET
                raise RuntimeError("the call failed")

        scoped = tools_module._env_scoped(Boom, {"FIXTURE_KEY": SECRET})
        with mock.patch.dict(os.environ, {}, clear=True):
            with self.assertRaises(RuntimeError):
                scoped()._run()
            self.assertNotIn("FIXTURE_KEY", os.environ)


class WebSearchProviderTests(unittest.TestCase):
    """Criterion 4: four providers, four classes, ONE tool name."""

    def test_each_provider_builds_its_own_class_under_the_one_name(self) -> None:
        expected = {
            "serper": "SerperDevTool",
            "tavily": "TavilySearchTool",
            "exa": "EXASearchTool",
            "brave": "BraveSearchTool",
        }
        entry = builtin("web_search")
        assert entry is not None
        for provider, class_name in expected.items():
            with self.subTest(provider=provider):
                missing = entry.missing_packages({"provider": provider})
                with mock.patch.dict(os.environ, {}, clear=True):
                    if missing:
                        # The package is not installed here, and the REFUSAL is
                        # the behaviour under test: `TavilySearchTool.__init__`
                        # calls `click.confirm` to offer to install itself,
                        # which raises `Abort` in a service process. Checking
                        # with `find_spec` first turns that into a sentence.
                        with self.assertRaises(ToolBuildError) as caught:
                            resolved_tool(
                                "web_search",
                                params={"provider": provider},
                                credential=FIELDS[provider],
                            )
                        self.assertIn(missing[0], str(caught.exception))
                        continue
                    tool = resolved_tool(
                        "web_search",
                        params={"provider": provider},
                        credential=FIELDS[provider],
                    )
                self.assertEqual(type(tool).__name__, class_name)
                self.assertEqual(tool.name, tools_module.WEB_SEARCH_NAME)

    def test_the_credential_kind_follows_the_provider(self) -> None:
        entry = builtin("web_search")
        assert entry is not None
        for provider in ("serper", "tavily", "exa", "brave"):
            with self.subTest(provider=provider):
                self.assertEqual(entry.kind_for({"provider": provider}), provider)

    def test_the_agent_sees_one_name_so_a_provider_swap_changes_no_prompt(self) -> None:
        """D5's whole point, stated as an assertion rather than a comment."""

        names = set()
        for provider in ("serper", "brave"):
            with mock.patch.dict(os.environ, {}, clear=True):
                names.add(
                    resolved_tool(
                        "web_search",
                        params={"provider": provider},
                        credential=FIELDS[provider],
                    ).name
                )
        self.assertEqual(names, {"web_search"})


class DmlLockTests(unittest.TestCase):
    """Criterion 5: `postgres_query` cannot be writable from any document value."""

    def _record(self) -> tuple[Any, list[dict[str, Any]]]:
        seen: list[dict[str, Any]] = []

        class Recorder:
            def __init__(self, **kwargs: Any) -> None:
                seen.append(kwargs)
                self.allow_dml = kwargs.get("allow_dml", False)
                self.db_uri = kwargs.get("db_uri")

        return Recorder, seen

    def test_dml_locked(self) -> None:
        """No `params` value reaches `allow_dml`, because it is not a param."""

        import crewai_tools

        recorder, seen = self._record()
        entry = builtin("postgres_query")
        assert entry is not None
        self.assertNotIn(
            "allow_dml",
            {spec.name for spec in entry.params},
            "allow_dml must not be an author-settable parameter",
        )
        for attempt in (
            {},
            {"allow_dml": True},
            {"tables": ["users"], "allow_dml": "true"},
        ):
            with self.subTest(params=attempt), mock.patch.object(
                crewai_tools, "NL2SQLTool", recorder
            ):
                # The entry's own validator refuses the unknown key too, but
                # this asserts the FACTORY: even handed the key directly, the
                # constructed tool is read-only.
                entry.factory({**entry.default_params(), **attempt}, FIELDS["postgres"], "warn")
        self.assertTrue(seen)
        for call in seen:
            self.assertIs(call["allow_dml"], False)

    def test_the_env_override_crewai_honours_is_forced_off_across_construction(self) -> None:
        """A package fact plan 06 did not have, and the reason for three locks.

        `NL2SQLTool.model_post_init` reads `CREWAI_NL2SQL_ALLOW_DML=true` and
        OVERRIDES the constructor argument. A deployment with that variable set
        would silently get a writable tool through a constructor that says
        `allow_dml=False`.
        """

        import crewai_tools

        recorder, seen = self._record()
        entry = builtin("postgres_query")
        assert entry is not None
        with mock.patch.dict(os.environ, {"CREWAI_NL2SQL_ALLOW_DML": "true"}), \
                mock.patch.object(crewai_tools, "NL2SQLTool", recorder):
            observed: list[str | None] = []

            class Watcher(recorder):  # type: ignore[misc,valid-type]
                def __init__(self, **kwargs: Any) -> None:
                    observed.append(os.environ.get("CREWAI_NL2SQL_ALLOW_DML"))
                    super().__init__(**kwargs)

            with mock.patch.object(crewai_tools, "NL2SQLTool", Watcher):
                entry.factory(entry.default_params(), FIELDS["postgres"], "warn")
            self.assertEqual(observed, ["false"])
            # And the window closed: the deployment's own value is back.
            self.assertEqual(os.environ["CREWAI_NL2SQL_ALLOW_DML"], "true")

    def test_a_writable_instance_is_refused_rather_than_returned(self) -> None:
        """The third lock: the built instance is asserted, not assumed."""

        import crewai_tools

        class Writable:
            def __init__(self, **_: Any) -> None:
                self.allow_dml = True

        entry = builtin("postgres_query")
        assert entry is not None
        with mock.patch.object(crewai_tools, "NL2SQLTool", Writable):
            with self.assertRaises(ToolBuildError) as caught:
                entry.factory(entry.default_params(), FIELDS["postgres"], "warn")
        self.assertIn("read-only", str(caught.exception))


class FlaggedEntryTests(unittest.TestCase):
    """PLANS.md decision 3: the code interpreter EXISTS and is OFF."""

    def test_the_code_interpreter_is_not_offered_while_its_flag_is_unset(self) -> None:
        self.assertNotIn("code_interpreter", [entry.id for entry in catalogue()])
        self.assertIn(
            "code_interpreter", [entry.id for entry in catalogue(include_disabled=True)]
        )
        entry = builtin("code_interpreter")
        assert entry is not None
        self.assertFalse(entry_enabled(entry))
        self.assertFalse(project_config.BUILDER_CODE_INTERPRETER_ENABLED)

    def test_naming_it_in_a_document_is_refused_by_the_flags_own_name(self) -> None:
        with self.assertRaises(ToolBuildError) as caught:
            resolved_tool("code_interpreter", params={}, credential=FIELDS["e2b"])
        self.assertIn("BUILDER_CODE_INTERPRETER_ENABLED", str(caught.exception))

    def test_lifting_the_flag_is_the_only_thing_between_it_and_shipping(self) -> None:
        """Built, not started - so turning it on is one boolean, not a feature."""

        entry = builtin("code_interpreter")
        assert entry is not None
        with mock.patch.object(project_config, "BUILDER_CODE_INTERPRETER_ENABLED", True):
            self.assertTrue(entry_enabled(entry))
            self.assertIn("code_interpreter", [row.id for row in catalogue()])


if __name__ == "__main__":
    unittest.main()
