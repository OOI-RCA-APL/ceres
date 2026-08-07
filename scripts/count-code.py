#!/usr/bin/env uv run

"""Count the code lines this branch adds and removes, per language.

Written for the migration's pull request description, where the interesting number is how
much of the engine moved from Python to Rust. Code means source that does something, so no
comments, no docstrings, no tests, no tooling, no generated files, and no lines holding
only closing delimiters.

Counted per revision and subtracted, rather than summed from the diff, because a line that
moved between files would otherwise be counted as both an addition and a removal.

    scripts/count-code.py                 # The totals, against origin/main.
    scripts/count-code.py --breakdown     # Which files moved them.
    scripts/count-code.py --base <ref>    # Compare against something else.
"""

import argparse
import ast
import subprocess
from collections.abc import Callable

# ruff: disable[T201] # Allow print statements.

EXCLUDED = (
    "ceres/__internal__/core.pyi",
    "ceres.__internal__.core.data/",
    "console/dist/",
    "docs/reference/",
    "rust/ceres-stubs/",
    "scripts/",
)
"""Paths whose contents are generated or are tooling, so neither is the work being sized.

`scripts/` and `rust/ceres-stubs/` are the tooling, one per language, and counting either
would credit the branch for a stub generator and a line counter as if they were engine
code. Both sides are excluded or neither, or the comparison tilts.
"""

DELIMITERS = set("()[]{},:; ")
"""Characters a line can consist entirely of while carrying no code."""


def _run(*arguments: str) -> str:
    """Return a git command's output."""
    return subprocess.run(["git", *arguments], capture_output=True, text=True, check=False).stdout


def paths(revision: str, suffix: str) -> list[str]:
    """List the files of one language in a revision, minus tests, tooling, and generated."""
    return [
        path
        for path in _run("ls-tree", "-r", "--name-only", revision).splitlines()
        if path.endswith(suffix)
        and not path.startswith("tests/")
        and "/tests/" not in path
        and not any(path.startswith(marker) for marker in EXCLUDED)
    ]


def _counts(line: str) -> bool:
    """Whether a stripped line carries code rather than punctuation."""
    return bool(line) and not all(character in DELIMITERS for character in line)


def python_code_lines(source: str) -> int:
    """Count a Python file's code lines, skipping comments and docstrings."""
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return 0

    # A docstring is an expression statement holding only a string, which covers module,
    # class, function, and the attribute docstrings this project writes under its fields.
    documented: set[int] = set()
    for node in ast.walk(tree):
        body = getattr(node, "body", None)
        for child in body if isinstance(body, list) else []:
            if (
                isinstance(child, ast.Expr)
                and isinstance(child.value, ast.Constant)
                and isinstance(child.value.value, str)
            ):
                documented.update(range(child.lineno, (child.end_lineno or child.lineno) + 1))

    return sum(
        1
        for number, line in enumerate(source.splitlines(), start=1)
        if number not in documented and not line.strip().startswith("#") and _counts(line.strip())
    )


def rust_code_lines(source: str) -> int:
    """Count a Rust file's code lines, skipping comments and inline test modules."""
    lines = source.splitlines()

    # Rust keeps unit tests in the file they cover, so a gated module has to be found and
    # skipped by matching its braces rather than by its path.
    tested: set[int] = set()
    for number, line in enumerate(lines):
        if line.strip() != "#[cfg(test)]":
            continue

        depth = 0
        for following in range(number, len(lines)):
            tested.add(following)
            depth += lines[following].count("{") - lines[following].count("}")
            if depth == 0 and "{" in lines[following]:
                break

    return sum(
        1
        for number, line in enumerate(lines)
        if number not in tested and not line.strip().startswith("//") and _counts(line.strip())
    )


def measure(revision: str, suffix: str, counter: Callable[[str], int]) -> dict[str, int]:
    """Count every file of one language in a revision."""
    return {path: counter(_run("show", f"{revision}:{path}")) for path in paths(revision, suffix)}


def report(
    name: str, base: str, suffix: str, counter: Callable[[str], int], breakdown: bool
) -> None:
    """Print one language's totals, and optionally the files that moved them."""
    before = measure(base, suffix, counter)
    after = measure("HEAD", suffix, counter)
    total = sum(after.values()) - sum(before.values())
    print(f"{name}: {sum(before.values()):,} -> {sum(after.values()):,}  net {total:+,}")
    if not breakdown:
        return

    deltas = {path: after.get(path, 0) - before.get(path, 0) for path in before | after}
    ranked = sorted((delta, path) for path, delta in deltas.items() if delta)
    for delta, path in [*ranked[:10], *ranked[-10:]]:
        print(f"  {delta:+6,}  {path}")


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Count the code lines this branch adds and removes, per language."
    )
    parser.add_argument(
        "--base",
        # The remote branch, not the local one, which is stale on any checkout that has
        # not pulled and would silently move the base and every number with it.
        default="origin/main",
        help="Revision to compare against, defaulting to origin/main.",
    )
    parser.add_argument(
        "--breakdown",
        action="store_true",
        help="List the files that moved the totals furthest in each direction.",
    )
    arguments = parser.parse_args()

    merge_base = _run("merge-base", arguments.base, "HEAD").strip()
    if not merge_base:
        print(f"no merge base between {arguments.base} and HEAD")
        return 1

    print(f"against {arguments.base} at {merge_base[:8]}")
    report("python", merge_base, ".py", python_code_lines, arguments.breakdown)
    report("rust", merge_base, ".rs", rust_code_lines, arguments.breakdown)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
