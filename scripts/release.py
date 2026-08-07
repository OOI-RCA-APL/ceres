#!/usr/bin/env -S uv run

"""Cut a release, with the changelog as the source of truth.

The version comes from pyproject.toml and the release notes come from the "Unreleased"
section of CHANGELOG.md, which this script retitles to the version and date, commits, and
pushes, then creates the GitHub release that triggers the wheel build and PyPI publish.
The GitHub release is a projection of the changelog rather than a second thing to write,
so the two cannot disagree.

`--dry-run` runs every check, reports every problem rather than stopping at the first,
and prints the exact steps and release notes a real run would produce.
"""

import argparse
import difflib
import re
import subprocess
import sys
import tempfile
import tomllib
from datetime import date
from pathlib import Path

# ruff: disable[T201] # Allow print statements.

_ROOT = Path(__file__).resolve().parent.parent

_UNRELEASED_HEADER = "## [Unreleased]"


def _run(*arguments: str) -> str:
    """Run a command at the repository root and return its stripped stdout."""
    result = subprocess.run(arguments, cwd=_ROOT, check=True, capture_output=True, encoding="utf-8")
    return result.stdout.strip()


def _unreleased_body(changelog: str) -> str | None:
    """Extract the body of the "Unreleased" section, or None when there is no section.

    The body runs from the "Unreleased" header to the next version header, with
    surrounding blank lines trimmed. An empty body comes back as an empty string, which
    callers treat as its own problem, distinct from the header being missing entirely.
    """
    match = re.search(
        rf"^{re.escape(_UNRELEASED_HEADER)}\n(.*?)(?=^## \[|\Z)",
        changelog,
        flags=re.MULTILINE | re.DOTALL,
    )
    if match is None:
        return None

    return match.group(1).strip()


def main() -> int:
    parser = argparse.ArgumentParser(description="Cut a release from the changelog.")
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Run every check and show what a release would do without doing it.",
    )
    options = parser.parse_args()

    pyproject = tomllib.loads((_ROOT / "pyproject.toml").read_text())
    version = pyproject["project"]["version"]
    changelog_path = _ROOT / "CHANGELOG.md"
    changelog = changelog_path.read_text()
    notes = _unreleased_body(changelog)

    problems: list[str] = []

    branch = _run("git", "branch", "--show-current")
    if branch != "main":
        problems.append(f"Releases cut from main, and this checkout is on {branch}.")

    if _run("git", "status", "--porcelain"):
        problems.append("The working tree has uncommitted changes.")

    _run("git", "fetch", "origin", "main")
    if _run("git", "rev-parse", "main") != _run("git", "rev-parse", "origin/main"):
        problems.append("Local main and origin/main differ, sync them first.")

    if _run("git", "ls-remote", "--tags", "origin", version):
        problems.append(f"The tag {version} already exists on origin.")

    if notes is None:
        problems.append('CHANGELOG.md has no "Unreleased" section.')
    elif not notes:
        problems.append('The "Unreleased" section is empty, write the release notes there.')

    if f"## [{version}]" in changelog:
        problems.append(f"CHANGELOG.md already has an entry for {version}.")

    header = f"## [{version}] - {date.today().isoformat()}"
    updated = changelog.replace(_UNRELEASED_HEADER, f"{_UNRELEASED_HEADER}\n\n{header}", 1)

    for problem in problems:
        print(f"Problem: {problem}")

    if options.dry_run:
        # The dry run renders the same computed results the real run writes, so what it
        # shows is what happens, not a parallel description that can drift.
        print("A release would do the following.\n")
        print("Modify CHANGELOG.md:\n")
        diff = difflib.unified_diff(
            changelog.splitlines(keepends=True),
            updated.splitlines(keepends=True),
            fromfile="CHANGELOG.md",
            tofile="CHANGELOG.md",
        )
        sys.stdout.writelines(diff)
        print(f'\nCommit "Release {version}" on main and push it to origin.')
        print(f"Create the git tag {version} and publish this GitHub release, which")
        print("triggers the wheel builds and the PyPI publish:\n")
        rule = "-" * 72
        print(rule)
        print(f"Title: {version}")
        print(rule)
        if notes:
            print(notes)

        print(rule)
        return 1 if problems else 0

    if problems:
        return 1

    changelog_path.write_text(updated)
    _run("git", "commit", "-am", f"Release {version}")
    _run("git", "push", "origin", "main")

    assert notes is not None
    with tempfile.NamedTemporaryFile("w", suffix=".md", delete_on_close=False) as file:
        file.write(notes)
        file.close()
        _run("gh", "release", "create", version, "--title", version, "--notes-file", file.name)

    print(f"Released {version}. The publish pipeline is running:")
    print(_run("gh", "release", "view", version, "--json", "url", "--jq", ".url"))
    return 0


if __name__ == "__main__":
    sys.exit(main())
