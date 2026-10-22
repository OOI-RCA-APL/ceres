from typing import TYPE_CHECKING, Annotated

import pytest

from ceres import Component, Files, Mount
from ceres.component import get_file_root_bindings
from ceres.directory import Directory

if TYPE_CHECKING:
    from pathlib import Path


def test_directory_warns_on_construction(tmp_path: Path) -> None:
    with pytest.warns(FutureWarning):
        directory = Directory(tmp_path)

    assert isinstance(directory, Mount)
    assert directory == Mount(tmp_path)


def test_directory_child_is_a_plain_mount(tmp_path: Path) -> None:
    with pytest.warns(FutureWarning):
        directory = Directory(tmp_path)

    assert type(directory / "abc") is Mount
    assert type(directory.parent) is Mount


def test_directory_field_serves_a_file_root(tmp_path: Path) -> None:
    class Hoarder(Component):
        stash: Annotated[Directory | None, Files()] = None

    with pytest.warns(FutureWarning):
        hoarder = Hoarder(stash=Directory(tmp_path))

    assert list(get_file_root_bindings(Hoarder)) == ["stash"]
    assert hoarder.system.get_file_root("stash") == Mount(tmp_path)
