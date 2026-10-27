import errno
import gc
import inspect
import os
from collections.abc import Callable, Iterable
from datetime import datetime
from pathlib import Path, PurePath
from typing import TYPE_CHECKING, Any, BinaryIO

import pytest
import yaml
from pydantic import ValidationError

from ceres import AsyncMount, Bound, Component, Config, Engine, Mount, PathTemplate, Project
from ceres.component import get_mount_bindings
from ceres.data import dump, validate
from ceres.mount import MountAccess
from ceres.paths import PathLayout

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


class Recorder(Component):
    output: Mount


RECORDER_CONFIG = {
    "components": [
        {
            "name": "recorder",
            "class": "tests.test_mount:Recorder",
            "arguments": {"output": "./data"},
        }
    ]
}


class Archivist(Component):
    output: Bound[Mount] = Mount.Field(...)
    stills: Bound[Mount] = Mount.Field("./stills", writable=False)


ARCHIVIST_CONFIG = {
    "components": [
        {
            "name": "archivist",
            "class": "tests.test_mount:Archivist",
            "arguments": {"output": {"path": "./data", "access": "view"}},
        }
    ]
}


class TestProjectPaths:
    @pytest.fixture
    def elsewhere(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
        """Run from a directory other than the project's."""
        path = tmp_path / "elsewhere"
        path.mkdir()
        monkeypatch.chdir(path)
        return path

    def create(self, source: Path | dict[str, Any]) -> Recorder:
        recorder = Config.read(source).components[0].create()
        assert isinstance(recorder, Recorder)
        return recorder

    def test_resolves_a_file_path_beside_the_file(self, tmp_path: Path, elsewhere: Path) -> None:
        path = tmp_path / "ceres.yaml"
        path.write_text(yaml.safe_dump(RECORDER_CONFIG))
        recorder = self.create(path)
        assert recorder.output == Mount(tmp_path / "data")
        assert dump(recorder.output) == str(tmp_path / "data")

    def test_keeps_a_linked_project_path_as_written(self, tmp_path: Path, elsewhere: Path) -> None:
        real = tmp_path / "real"
        real.mkdir()
        (real / "ceres.yaml").write_text(yaml.safe_dump(RECORDER_CONFIG))
        link = tmp_path / "link"
        link.symlink_to(real)
        assert self.create(link / "ceres.yaml").output == Mount(link / "data")
        assert Project(link / "ceres.yaml").directory == Mount(link)

    def test_resolves_a_mapping_path_against_the_current_directory(self, elsewhere: Path) -> None:
        assert self.create(RECORDER_CONFIG).output == Mount(elsewhere / "data")

    def test_reads_and_dumps_a_setting_with_access(self, tmp_path: Path, elsewhere: Path) -> None:
        path = tmp_path / "ceres.yaml"
        path.write_text(yaml.safe_dump(ARCHIVIST_CONFIG))
        archivist = Config.read(path).components[0].create()
        assert isinstance(archivist, Archivist)
        assert (archivist.output.access, archivist.stills) == (
            MountAccess.VIEW,
            Mount(tmp_path / "stills"),
        )
        assert dump(archivist.output) == {"path": str(tmp_path / "data"), "access": "view"}
        assert not archivist.stills.writable


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

    async def test_dates_and_walks(self, mount: Mount) -> None:
        dated = AsyncMount(mount, layout="{year}/{month}")
        folder = await dated.dated(at("2026-10-27T13:45:09Z"))
        assert type(folder) is AsyncMount
        assert await dated.periods(at("2026-10-01T00:00:00Z"), at("2026-11-01T00:00:00Z")) == [
            folder
        ]


def at(when: str) -> datetime:
    return datetime.fromisoformat(when)


def folders(mount: Mount, *paths: str) -> Mount:
    for path in paths:
        (mount / path).mkdir()

    return mount


def walked(mount: Mount, after: str, before: str) -> list[str]:
    return [folder.relative.as_posix() for folder in mount.periods(at(after), at(before))]


class TestLayout:
    def test_creates_the_folder_for_a_time_in_its_zone(self, tmp_path: Path) -> None:
        mount = Mount(tmp_path, layout="{year}/{month}/{day}", zone="America/Los_Angeles")
        folder = mount.dated(at("2026-10-27T03:00:00Z"))
        assert folder == mount / "2026/10/26"
        assert folder.is_dir()
        assert mount.dated(at("2026-10-27T04:00:00Z")) == folder

    def test_dates_to_itself_without_a_layout(self, mount: Mount) -> None:
        assert mount.dated(at("2026-10-27T13:45:09Z")) is mount

    def test_refuses_a_naive_time(self, tmp_path: Path) -> None:
        with pytest.raises(ValueError, match="timezone-aware"):
            Mount(tmp_path, layout="{year}").dated(datetime(2026, 10, 27))  # noqa: DTZ001

    def test_reads_an_existing_folder_without_writing(self, tmp_path: Path) -> None:
        mount = folders(Mount(tmp_path, layout="{year}"), "2026")
        readonly = Mount(mount, writable=False)
        assert readonly.dated(at("2026-10-27T13:45:09Z")) == mount / "2026"
        with pytest.raises(PermissionError):
            readonly.dated(at("2027-10-27T13:45:09Z"))

    @pytest.mark.parametrize(
        "layout",
        ["{month}", "{year}/{day}", "{year}/{week}", "{year}/{m}{d}", "{time:%Y}", "{connection}"],
    )
    def test_refuses_a_layout_it_cannot_read_back(self, tmp_path: Path, layout: str) -> None:
        with pytest.raises(ValueError):
            Mount(tmp_path, layout=layout)

    def test_refuses_an_unknown_zone(self, tmp_path: Path) -> None:
        with pytest.raises(ValueError, match="not a time zone"):
            Mount(tmp_path, zone="abc")

    def test_walks_the_folders_overlapping_a_range_in_order(self, tmp_path: Path) -> None:
        mount = folders(
            Mount(tmp_path, layout="{year}/{month}/{day}"),
            "2026/10/27",
            "2026/10/01",
            "2026/09/30",
            "2026/11/01",
            "2025/12/31",
            "2026/13/01",
            "2026/10/abc",
            "abc",
        )
        (mount / "2026/10/28").write_bytes(b"")
        assert walked(mount, "2026-10-01T00:00:00Z", "2026-11-01T00:00:00Z") == [
            "2026/10/01",
            "2026/10/27",
        ]

    def test_walks_a_partial_day(self, tmp_path: Path) -> None:
        mount = folders(Mount(tmp_path, layout="{year}/{month}/{day}"), "2026/10/26", "2026/10/27")
        assert walked(mount, "2026-10-26T23:00:00Z", "2026-10-27T01:00:00Z") == [
            "2026/10/26",
            "2026/10/27",
        ]

    def test_walks_in_the_mounts_zone(self, tmp_path: Path) -> None:
        mount = folders(
            Mount(tmp_path, layout="{date}", zone="Asia/Kolkata"), "20261026", "20261027"
        )
        assert walked(mount, "2026-10-26T19:00:00Z", "2026-10-26T20:00:00Z") == ["20261027"]

    def test_walks_unpadded_and_named_months_by_time(self, tmp_path: Path) -> None:
        mount = folders(Mount(tmp_path, layout="{year}/{m}-{mon}"), "2026/10-Oct", "2026/2-Feb")
        (mount / "2026/3-Feb").mkdir()
        assert walked(mount, "2026-01-01T00:00:00Z", "2027-01-01T00:00:00Z") == [
            "2026/2-Feb",
            "2026/10-Oct",
        ]

    def test_walks_days_of_the_year(self, tmp_path: Path) -> None:
        mount = folders(Mount(tmp_path, layout="{year}/{doy}"), "2026/300", "2026/299", "2026/366")
        assert walked(mount, "2026-10-27T00:00:00Z", "2027-01-01T00:00:00Z") == ["2026/300"]

    def test_walks_itself_without_a_layout(self, mount: Mount) -> None:
        assert walked(mount, "2026-10-27T00:00:00Z", "2026-10-28T00:00:00Z") == ["."]

    def test_renders_a_file_name_with_its_names_and_zone(self, tmp_path: Path) -> None:
        mount = Mount(tmp_path, zone="America/Los_Angeles")._named({"mount": "abc"})
        template = PathTemplate("{mount}_{datetime}_{sequence}", atoms=["sequence"])
        rendered = mount.render(template, at("2026-10-27T13:45:09Z"), {"sequence": 7})
        assert rendered == "abc_20261027T064509_7"

    def test_dumps_its_layout_and_zone(self, tmp_path: Path) -> None:
        mount = Mount(tmp_path, layout="{year}", zone="local")
        assert dump(mount) == {"path": str(tmp_path), "layout": "{year}", "zone": "local"}
        assert validate(Mount, dump(mount)).layout == PathLayout("{year}")

    def test_an_empty_layout_clears_a_given_one(self, tmp_path: Path) -> None:
        dated = Mount(tmp_path, layout="{year}")
        assert Mount(dated).layout == PathLayout("{year}")
        assert Mount(dated, layout="").layout is None

    def test_names_a_file_by_kind_or_template(self, tmp_path: Path) -> None:
        mount = Mount(tmp_path, layout="{year}", files={"abc": "abc/{date}.txt"})
        when = at("2026-10-27T13:45:09Z")
        assert mount.file("abc", when) == mount / "2026/abc/20261027.txt"
        assert (tmp_path / "2026/abc").is_dir()
        assert mount.file(PathTemplate("{time}.txt"), when) == mount / "2026/134509.txt"
        with pytest.raises(ValueError, match="no file 'abcd'"):
            mount.file("abcd", when)

    def test_refuses_a_file_on_a_read_only_mount(self, tmp_path: Path) -> None:
        mount = Mount(tmp_path, writable=False, files={"abc": "abc/{date}.txt"})
        with pytest.raises(PermissionError):
            mount.file("abc", at("2026-10-27T13:45:09Z"))

    def test_dumps_its_files(self, tmp_path: Path) -> None:
        mount = Mount(tmp_path, files={"abc": "{date}.txt"})
        assert dump(mount) == {"path": str(tmp_path), "files": {"abc": "{date}.txt"}}
        assert validate(Mount, dump(mount)).files == {"abc": PathTemplate("{date}.txt")}


class Photographer(Component):
    stills: Bound[Mount] = Mount.Field(
        "./stills",
        layout="{mount}/{year}",
        zone="local",
        files={"still": "{datetime}_{sequence}.jpg", "thumb": "thumbs/{datetime}.jpg"},
        atoms=["sequence"],
    )


def photographer(stills: object = None) -> Photographer:
    arguments = {} if stills is None else {"stills": stills}
    component = (
        Config.read(
            {
                "components": [
                    {
                        "name": "abc",
                        "class": "tests.test_mount:Photographer",
                        "arguments": arguments,
                    }
                ]
            }
        )
        .components[0]
        .create()
    )
    assert isinstance(component, Photographer)
    return component


class TestLayoutField:
    def test_declares_a_layout_and_zone(self) -> None:
        stills = photographer().stills
        assert (stills.layout, stills.zone) == (PathLayout("{mount}/{year}"), "local")

    def test_names_the_component_and_mount(self) -> None:
        assert photographer().stills.names == {"component": "abc", "mount": "stills"}

    def test_renames_its_mounts_with_the_component(self) -> None:
        component = photographer()
        component.system.name = "abcd"
        assert component.stills.names["component"] == "abcd"

    async def test_names_the_project_of_its_engine(self, tmp_path: Path) -> None:
        path = tmp_path / "ceres.yaml"
        path.write_text(
            "components: [{name: abc, class: 'tests.test_mount:Photographer'}]\n"
            f"database: {{type: sqlite, path: {tmp_path / 'records.sqlite'}}}\n"
        )
        engine = Engine()
        await engine.load(path, checks=())
        try:
            component = engine.get_component("abc")
            assert isinstance(component, Photographer)
            assert component.stills.names["project"] == tmp_path.name
        finally:
            await engine.database.dispose()

    def test_dates_with_its_names(self, tmp_path: Path) -> None:
        stills = photographer(str(tmp_path)).stills
        assert stills.dated(at("2026-07-01T12:00:00Z")) == stills / "stills/2026"

    def test_takes_a_configured_layout_and_zone(self, tmp_path: Path) -> None:
        setting = {"path": str(tmp_path), "layout": "{year}/{month}", "zone": "utc"}
        stills = photographer(setting).stills
        assert (stills.layout, stills.zone) == (PathLayout("{year}/{month}"), "utc")

    def test_clears_the_layout_from_configuration(self, tmp_path: Path) -> None:
        assert photographer({"path": str(tmp_path), "layout": None}).stills.layout is None

    def test_refuses_a_bad_configured_layout(self, tmp_path: Path) -> None:
        with pytest.raises(ValidationError, match="calendar"):
            validate(Photographer, {"stills": {"path": str(tmp_path), "layout": "{day}"}})

    def test_refuses_a_bad_layout_when_declared(self) -> None:
        with pytest.raises(ValueError, match="calendar"):
            Mount.Field(layout="{day}")

    def test_lists_the_declared_layout(self) -> None:
        binding = get_mount_bindings(Photographer)["stills"]
        assert (binding.layout, binding.zone) == (PathLayout("{mount}/{year}"), "local")
        assert set(binding.files) == {"still", "thumb"}

    def test_writes_each_file_kind_into_the_dated_folder(self, tmp_path: Path) -> None:
        stills = photographer({"path": str(tmp_path), "zone": "utc"}).stills
        when = at("2026-07-01T12:00:00Z")
        assert stills.file("still", when, {"sequence": 7}) == stills / (
            "stills/2026/20260701T120000_7.jpg"
        )
        assert stills.file("thumb", when).parent.is_dir()

    def test_takes_a_configured_file_and_keeps_the_others(self, tmp_path: Path) -> None:
        setting = {"path": str(tmp_path), "files": {"still": "{date}_{sequence}.jpg"}}
        files = photographer(setting).stills.files
        assert {kind: file.source for kind, file in files.items()} == {
            "still": "{date}_{sequence}.jpg",
            "thumb": "thumbs/{datetime}.jpg",
        }

    def test_fills_the_declared_files_into_a_mount_given_in_code(self, tmp_path: Path) -> None:
        stills = Photographer(stills=Mount(tmp_path, files={"still": "abc.jpg"})).stills
        assert {kind: file.source for kind, file in stills.files.items()} == {
            "still": "abc.jpg",
            "thumb": "thumbs/{datetime}.jpg",
        }
        assert Photographer(stills=Mount(tmp_path)).stills.layout is None

    def test_refuses_a_configured_file_kind_it_does_not_declare(self, tmp_path: Path) -> None:
        with pytest.raises(ValidationError, match="declares no file 'abc'"):
            validate(Photographer, {"stills": {"path": str(tmp_path), "files": {"abc": "a"}}})

    def test_refuses_a_bad_file_when_declared(self) -> None:
        with pytest.raises(ValueError, match="not an atom"):
            Mount.Field(files={"abc": "{sequence}"})
