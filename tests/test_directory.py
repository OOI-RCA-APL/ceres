from typing import TYPE_CHECKING

import pytest

from ceres import Bound, Component, Mount
from ceres.component import get_mount_bindings
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


def test_directory_field_binds_a_mount(tmp_path: Path) -> None:
    class Hoarder(Component):
        stash: Bound[Directory] = Mount.Field(...)

    with pytest.warns(FutureWarning):
        hoarder = Hoarder(stash=Directory(tmp_path))

    assert list(get_mount_bindings(Hoarder)) == ["stash"]
    assert hoarder.system.get_mount("stash") == Mount(tmp_path)
