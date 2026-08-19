"""A disposable project the CLI runs against.

The `project` fixture writes a configuration dict as `ceres.json` in its own directory
and returns a runner for `ceres` commands there, so a test states the whole project it
needs and asserts on real command output.
"""

import json
import subprocess
import sys
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

import pytest

if TYPE_CHECKING:
    from pathlib import Path

DEFAULT_CONFIG: dict[str, Any] = {"database": {"type": "sqlite", "path": "records.sqlite"}}


@dataclass
class Outcome:
    """One finished command, as a test asserts on it."""

    code: int
    stdout: str
    stderr: str

    @property
    def ok(self) -> bool:
        return self.code == 0

    def rows(self) -> list[dict[str, Any]]:
        """Parse JSONL output rows."""
        return [json.loads(line) for line in self.stdout.splitlines() if line.strip()]


class Project:
    """A project directory the CLI can be run in."""

    def __init__(self, path: Path) -> None:
        self.path = path

    def run(self, *arguments: str, stdin: str | None = None) -> Outcome:
        """Run one `ceres` command in the project and return its outcome."""
        completed = subprocess.run(
            [sys.executable, "-m", "ceres", *arguments],
            cwd=self.path,
            capture_output=True,
            text=True,
            input=stdin,
        )
        return Outcome(completed.returncode, completed.stdout, completed.stderr)


@pytest.fixture
def project(tmp_path: Path):
    """Create a project from a configuration dict, defaulting to a local SQLite database."""

    def make(config: dict[str, Any] | None = None, *, migrate: bool = True) -> Project:
        chosen = DEFAULT_CONFIG if config is None else config
        (tmp_path / "ceres.json").write_text(json.dumps(chosen))
        made = Project(tmp_path)
        if migrate:
            outcome = made.run("database", "migrate", "--yes")
            assert outcome.ok, outcome.stderr

        return made

    return make
