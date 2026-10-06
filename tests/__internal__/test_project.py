"""The project's `.ceres` state directory and the CLI server info file kept in it."""

from __future__ import annotations

import stat
from typing import TYPE_CHECKING

from ceres.__internal__.project import LoadedProject, Project
from ceres.__internal__.server import CLIServerInfo
from ceres.config import ConfigMeta

if TYPE_CHECKING:
    from pathlib import Path


def test_the_state_directory_ignores_itself(tmp_path: Path) -> None:
    project = Project(tmp_path / "ceres.yaml")

    created = project.create_state_directory()

    assert created == tmp_path / ".ceres"
    assert (created / ".gitignore").read_text() == "*\n"


def test_an_edited_gitignore_is_left_alone(tmp_path: Path) -> None:
    project = Project(tmp_path / "ceres.yaml")
    ignore = project.create_state_directory() / ".gitignore"
    ignore.write_text("*\n!keep\n")

    project.create_state_directory()

    assert ignore.read_text() == "*\n!keep\n"


def test_server_info_is_written_owner_only_in_the_state_directory(tmp_path: Path) -> None:
    project = LoadedProject(tmp_path / "ceres.yaml", ConfigMeta())
    path = tmp_path / ".ceres" / "server.json"
    assert project.cli_server_info_path == path

    # A file left by an earlier run with a wider mode is narrowed, not trusted.
    path.parent.mkdir()
    path.write_text("{}")
    path.chmod(0o644)

    project.write_cli_server_info(CLIServerInfo(port=4321, token="secret"))

    assert stat.S_IMODE(path.stat().st_mode) == 0o600
    assert project.get_cli_server_info() == CLIServerInfo(port=4321, token="secret")

    project.delete_cli_server_info()
    assert not path.exists()
    assert project.get_cli_server_info() is None
