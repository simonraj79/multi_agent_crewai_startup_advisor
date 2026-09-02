"""The shape `PROBLEM_CODES`' mirror can actually see.

`frontend/src/types/builder.ts` restates every problem code the server can
emit, and `frontend/tests/builderTypes.spec.ts` keeps the two in step by
grepping the Python for module-level declarations:

    /^[A-Z][A-Z0-9_]* = "([a-z]+(?:-[a-z]+)+)"$/gm

That is a real anti-drift gate - it has already caught three codes missing from
the tuple - but it is a gate on a *spelling*, not on the codes themselves. Write

    problems.append(Problem(code="inline-literal-code", ...))

and the regex finds nothing, the TypeScript tuple stays at its old length, the
frontend suite stays green, and the client renders a problem it does not know.
A mirror that can be bypassed by a legal refactor is a mirror that will be.

So this file guards the assumption from the Python side, which is the side that
would break it. Two rules, both enforced by walking the AST rather than by
reading:

* every ``Problem(...)`` is constructed with ``code=<NAME>``, never a string
  literal - the one shape the regex cannot see;
* every such NAME resolves to a module-level constant written in exactly the
  spelling the regex matches.

Together they say: if a code exists, the frontend's grep finds it. That is the
property `builderTypes.spec.ts` assumes and could not check for itself, because
a test in `frontend/` cannot fail on a refactor it never reads.

No cost: this reads source files and never imports the modules under test.
"""

from __future__ import annotations

import ast
import pathlib
import re
import unittest


BUILDER = pathlib.Path(__file__).resolve().parents[2] / "src" / "brief_crew" / "builder"

#: The frontend's own discovery regex, restated. Anchored per line with no
#: leading whitespace and no type annotation, exactly as
#: `frontend/tests/builderTypes.spec.ts::pythonProblemCodes` writes it - if the
#: two ever disagree this file is asserting about a gate that does not exist.
DECLARATION = re.compile(r'^([A-Z][A-Z0-9_]*) = "([a-z]+(?:-[a-z]+)+)"$', re.MULTILINE)

#: The files that declare codes. The frontend reads exactly these three, and the
#: third was missing there for a while - which is how twenty-seven passed as
#: thirty. A fourth file appearing here without appearing there is the next
#: instance of that defect, so the count test below pins the pair.
SOURCES = ("bounds.py", "budget.py", "compiler.py")


def _module(name: str) -> tuple[ast.Module, str]:
    text = (BUILDER / name).read_text(encoding="utf-8")
    return ast.parse(text), text


def _problem_calls(tree: ast.Module) -> list[ast.Call]:
    return [
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id == "Problem"
    ]


def _module_level_constants(tree: ast.Module) -> dict[str, str]:
    """`NAME = "value"` at column zero, which is what the regex can see."""

    found: dict[str, str] = {}
    for node in tree.body:
        if not isinstance(node, ast.Assign) or len(node.targets) != 1:
            continue
        target = node.targets[0]
        if not isinstance(target, ast.Name):
            continue
        if isinstance(node.value, ast.Constant) and isinstance(node.value.value, str):
            found[target.id] = node.value.value
    return found


def _names_bound_from_constants(tree: ast.Module, constants: dict[str, str]) -> set[str]:
    """Locals that only ever take a module-level constant's value.

    `_identity_problems` loops over a tuple of `(label, code, seen)` triples and
    passes the loop variable as `code=`. That is not a literal and not a
    module-level name, but every value it can hold is one, so it satisfies the
    property this file is really about: the regex finds all of them at their
    declaration.
    """

    safe: set[str] = set()

    def constant_name(node: ast.expr) -> bool:
        return isinstance(node, ast.Name) and node.id in constants

    for node in ast.walk(tree):
        # `CODE = SOME_CONSTANT` - the trivial case, kept because it costs a line.
        if isinstance(node, ast.Assign) and len(node.targets) == 1:
            target = node.targets[0]
            if isinstance(target, ast.Name) and constant_name(node.value):
                safe.add(target.id)
            continue

        # `for a, b, c in ((x, CONST, y), (p, CONST2, q)):` - resolved by
        # POSITION rather than by "every name in here is a constant", because
        # the other slots of that tuple legitimately hold comprehensions over
        # the document. Position 1 is a constant in every row, so the name bound
        # at position 1 is safe no matter what positions 0 and 2 contain.
        if not isinstance(node, ast.For):
            continue
        if not isinstance(node.target, ast.Tuple) or not isinstance(node.iter, ast.Tuple):
            continue
        rows = [row for row in node.iter.elts if isinstance(row, ast.Tuple)]
        if len(rows) != len(node.iter.elts) or not rows:
            continue
        for index, bound in enumerate(node.target.elts):
            if not isinstance(bound, ast.Name):
                continue
            if all(index < len(row.elts) and constant_name(row.elts[index]) for row in rows):
                safe.add(bound.id)
    return safe


class ProblemCodeDeclarationTests(unittest.TestCase):
    """The property `builderTypes.spec.ts` assumes and cannot verify."""

    def test_no_problem_is_constructed_with_a_literal_code(self) -> None:
        """A string literal at the call site is invisible to the mirror."""

        offenders: list[str] = []
        for name in SOURCES:
            tree, _ = _module(name)
            for call in _problem_calls(tree):
                for keyword in call.keywords:
                    if keyword.arg != "code":
                        continue
                    if isinstance(keyword.value, ast.Constant):
                        offenders.append(
                            f"{name}:{call.lineno} code={keyword.value.value!r}"
                        )
        self.assertEqual(
            offenders,
            [],
            "a Problem code written as a literal cannot be found by "
            "frontend/tests/builderTypes.spec.ts, so the TypeScript "
            "PROBLEM_CODES tuple would silently stay at its old length; "
            "declare a module-level constant and pass that instead",
        )

    def test_every_code_argument_resolves_to_a_declared_constant(self) -> None:
        """Including the loop variable in `_identity_problems`."""

        unresolved: list[str] = []
        for name in SOURCES:
            tree, _ = _module(name)
            constants = _module_level_constants(tree)
            indirect = _names_bound_from_constants(tree, constants)
            for call in _problem_calls(tree):
                for keyword in call.keywords:
                    if keyword.arg != "code":
                        continue
                    value = keyword.value
                    if not isinstance(value, ast.Name):
                        unresolved.append(f"{name}:{call.lineno} {ast.dump(value)[:60]}")
                    elif value.id not in constants and value.id not in indirect:
                        unresolved.append(f"{name}:{call.lineno} {value.id}")
        self.assertEqual(unresolved, [], "every Problem code must trace to a constant")

    def test_the_declared_constants_are_exactly_what_the_regex_finds(self) -> None:
        """The AST and the frontend's grep must agree about the same files.

        If they diverge, one of the two is reading a shape the other cannot, and
        the mirror is guarding a subset of the codes while claiming all of them.
        """

        for name in SOURCES:
            tree, text = _module(name)
            by_ast = _module_level_constants(tree)
            by_regex = {match.group(1): match.group(2) for match in DECLARATION.finditer(text)}
            # The AST sees every string constant; the regex sees only kebab-case
            # ones, which is the shape a code takes. Compare on that subset.
            codes_by_ast = {
                key: value
                for key, value in by_ast.items()
                if re.fullmatch(r"[a-z]+(?:-[a-z]+)+", value)
            }
            self.assertEqual(
                codes_by_ast,
                by_regex,
                f"{name}: the AST and the frontend's regex disagree about which "
                "codes are declared here",
            )

    def test_the_three_files_carry_every_code_the_frontend_lists(self) -> None:
        """Thirty, and the arithmetic is stated so a change has to face it.

        Twenty-five, two and three. The compiler's three were absent from the
        TypeScript tuple for a while precisely because that file was not in the
        frontend's source list, and one of them - `library-missing-prompt-input`
        - is the most common problem in the whole builder.
        """

        codes: set[str] = set()
        for name in SOURCES:
            _, text = _module(name)
            codes |= {match.group(2) for match in DECLARATION.finditer(text)}
        self.assertEqual(
            len(codes),
            30,
            "the number of problem codes moved; frontend/src/types/builder.ts's "
            "PROBLEM_CODES and builderTypes.spec.ts's length assertion both "
            "have to move with it",
        )


if __name__ == "__main__":
    unittest.main()
