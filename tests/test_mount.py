import errno
import gc
import inspect
import os
from collections.abc import Callable, Iterable
from pathlib import Path, PurePath
from typing import TYPE_CHECKING, BinaryIO

import pytest

from ceres import AsyncMount, Mount
from ceres.data import dump, validate

if TYPE_CHECKING:
    from ceres.mount import MountPath


@pytest.fixture
def mount(tmp_path: Path) -> Mount:
    return Mount(tmp_path)


def names(entries: Iterable[MountPath]) -> list[str]:
    return sorted(entry.name for entry in entries)


class TestJoin:
    def test_joins_each_segment(self, mount: Mount) -> None:
        child = mount / "a/b" / "c.txt"
        assert child.relative == PurePath("a/b/c.txt")
        assert child.path == mount.root / "a" / "b" / "c.txt"

    def test_drops_a_dot_segment(self, mount: Mount) -> None:
        assert mount / "./a/." == mount / "a"

    @pytest.mark.parametrize("part", ["..", "a/../b", "", "a//b", "a/", "/abc", "a\\b", "a\0b"])
    def test_refuses_a_part_leaving_the_root(self, mount: Mount, part: str) -> None:
        with pytest.raises(ValueError):
            _ = mount / part

    def test_stops_parent_at_the_root(self, mount: Mount) -> None:
        assert (mount / "a/b").parent.parent == mount
        assert mount.parent == mount

    def test_names_the_root_at_the_root(self, tmp_path: Path, mount: Mount) -> None:
        assert mount.name == tmp_path.name
        assert (mount / "a/b.txt").name == "b.txt"

    def test_resolves_a_relative_root_against_the_current_directory(self) -> None:
        assert Mount("abc").root == Path.cwd() / "abc"


class TestIdentity:
    def test_compares_root_and_relative_across_types(self, mount: Mount) -> None:
        assert mount / "a" == AsyncMount(mount) / "a"
        assert hash(mount / "a") == hash(AsyncMount(mount / "a"))
        assert mount / "a" != mount / "b"
        assert mount != str(mount)

    def test_converts_both_ways_keeping_place_and_writability(self, mount: Mount) -> None:
        source = Mount(mount, writable=False) / "a"
        converted = Mount(AsyncMount(source))
        assert type(converted) is Mount
        assert converted == source
        assert not converted.writable

    def test_offers_the_same_methods_on_both_types(self) -> None:
        def methods(kind: type) -> set[str]:
            return {name for name, _ in inspect.getmembers(kind) if not name.startswith("_")}

        assert methods(Mount) - {"open"} == methods(AsyncMount)

    def test_reads_as_a_path(self, tmp_path: Path, mount: Mount) -> None:
        assert str(mount / "a") == str(tmp_path / "a")
        assert Path(mount / "a") == tmp_path / "a"
        assert repr(mount) == f"Mount({str(tmp_path)!r})"

    def test_validates_and_serializes_as_a_path_string(self, tmp_path: Path) -> None:
        mount = validate(Mount, str(tmp_path))
        assert mount == Mount(tmp_path)
        assert validate(AsyncMount, mount) == mount
        assert validate(Mount, tmp_path) == mount
        assert dump(mount) == str(tmp_path)


class TestTemporary:
    def test_removes_the_directory_with_its_last_reference(self) -> None:
        mount = Mount()
        root = mount.root
        assert mount.temporary
        assert root.is_dir()

        del mount
        assert not root.exists()

    def test_keeps_the_directory_while_a_child_lives(self) -> None:
        mount = Mount()
        root = mount.root
        child = AsyncMount(mount / "a")
        del mount
        gc.collect()
        assert root.is_dir()
        assert child.temporary

        del child
        assert not root.exists()

    def test_leaves_a_given_directory_in_place(self, tmp_path: Path) -> None:
        mount = Mount(tmp_path)
        assert not mount.temporary

        del mount
        assert tmp_path.is_dir()


class TestFiles:
    def test_writes_and_reads(self, mount: Mount) -> None:
        (mount / "a").mkdir()
        (mount / "a/b.txt").write_text("abc")
        assert (mount / "a/b.txt").read_bytes() == b"abc"
        with (mount / "a/b.txt").open() as stream:
            assert stream.read() == "abc"

        assert (mount / "a").is_dir()
        assert (mount / "a/b.txt").is_file()

    def test_lists_and_globs_inside_the_root(self, mount: Mount) -> None:
        (mount / "a/b").mkdir()
        (mount / "a/c.txt").write_bytes(b"")
        assert names((mount / "a").iterdir()) == ["b", "c.txt"]
        assert [match.relative for match in mount.glob("*/*.txt")] == [PurePath("a/c.txt")]
        with pytest.raises(ValueError):
            list(mount.glob("../*"))

    def test_renames_inside_the_mount(self, tmp_path: Path, mount: Mount) -> None:
        (mount / "a").write_bytes(b"abc")
        assert (mount / "a").rename(mount / "b") == mount / "b"
        assert (mount / "b").read_bytes() == b"abc"
        with pytest.raises(ValueError):
            (mount / "b").rename(Mount(tmp_path / "b") / "c")

    def test_removes_files_and_trees(self, mount: Mount) -> None:
        (mount / "a/b").mkdir()
        (mount / "a/b/c").write_bytes(b"")
        (mount / "a/b/c").unlink()
        (mount / "a/b").rmdir()
        (mount / "a").rmtree()
        assert names(mount.iterdir()) == []


class TestReadOnly:
    @pytest.fixture
    def readonly(self, mount: Mount) -> Mount:
        (mount / "a").write_bytes(b"abc")
        return Mount(mount, writable=False)

    @pytest.mark.parametrize(
        "change",
        [
            lambda mount: (mount / "a").write_bytes(b""),
            lambda mount: (mount / "a").unlink(),
            lambda mount: (mount / "a").open("ab"),
            lambda mount: (mount / "b").mkdir(),
            lambda mount: mount.create("b", b""),
            lambda mount: mount.append("a", b""),
            lambda mount: (mount / "a").rename(mount / "b"),
        ],
    )
    def test_refuses_every_change(self, readonly: Mount, change: Callable[[Mount], object]) -> None:
        with pytest.raises(PermissionError):
            change(readonly)

        assert (readonly / "a").read_bytes() == b"abc"
        assert names(readonly.iterdir()) == ["a"]

    def test_passes_to_children(self, readonly: Mount) -> None:
        assert not (readonly / "a").writable
        assert not AsyncMount(readonly).parent.writable


class TestCreate:
    def test_writes_a_new_file_with_its_parents(self, mount: Mount) -> None:
        created = mount.create("a/b.txt", b"abc")
        assert created == mount / "a/b.txt"
        assert created.read_bytes() == b"abc"
        assert names((mount / "a").iterdir()) == ["b.txt"]

    def test_writes_through_a_callback(self, mount: Mount) -> None:
        def write(stream: BinaryIO) -> None:
            stream.write(b"abc")

        assert mount.create("a", write).read_bytes() == b"abc"

    def test_never_replaces_a_file(self, mount: Mount) -> None:
        mount.create("a", b"abc")
        with pytest.raises(FileExistsError):
            mount.create("a", b"abcd")

        assert (mount / "a").read_bytes() == b"abc"
        assert names(mount.iterdir()) == ["a"]

    def test_leaves_nothing_when_the_callback_raises(self, mount: Mount) -> None:
        def write(stream: BinaryIO) -> None:
            stream.write(b"abc")
            raise RuntimeError

        with pytest.raises(RuntimeError):
            mount.create("a", write)

        assert names(mount.iterdir()) == []

    def test_falls_back_to_a_checked_rename_without_hard_links(
        self, mount: Mount, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        def link(source: object, target: object) -> None:
            raise OSError(errno.EPERM, "abc")

        monkeypatch.setattr(os, "link", link)
        assert mount.create("a", b"abc").read_bytes() == b"abc"
        with pytest.raises(FileExistsError):
            mount.create("a", b"abcd")

        assert (mount / "a").read_bytes() == b"abc"
        assert names(mount.iterdir()) == ["a"]

    def test_appends_creating_the_file(self, mount: Mount) -> None:
        mount.append("a/b", b"ab")
        assert mount.append("a/b", b"c").read_bytes() == b"abc"


class TestAsync:
    async def test_runs_each_operation(self, mount: Mount) -> None:
        directory = AsyncMount(mount) / "a"
        await directory.mkdir()
        created = await directory.create("b", b"ab")
        assert type(created) is AsyncMount
        await directory.append("b", b"c")
        assert await created.read_bytes() == b"abc"
        assert await directory.iterdir() == [created]
        assert await AsyncMount(mount).glob("*/b") == [created]
        assert (await created.stat()).st_size == 3
        await created.unlink()
        assert not await created.exists()
