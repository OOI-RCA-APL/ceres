from pathlib import Path

import pytest

from ceres.directory import Directory


class TestDirectoryInit:
    def test_explicit_path_is_resolved_to_absolute(self, tmp_path: Path) -> None:
        directory = Directory(tmp_path / "child")
        assert directory.path.is_absolute()

    def test_none_path_generates_temporary_directory(self) -> None:
        directory = Directory()
        assert "ceres-directory-" in str(directory.path)
        assert directory.temporary is True

    def test_temporary_defaults_to_true_when_path_is_none(self) -> None:
        directory = Directory()
        assert directory.temporary is True

    def test_temporary_defaults_to_false_when_path_is_given(self, tmp_path: Path) -> None:
        directory = Directory(tmp_path / "child")
        assert directory.temporary is False

    def test_temporary_can_be_overridden(self, tmp_path: Path) -> None:
        directory = Directory(tmp_path / "child", temporary=True)
        assert directory.temporary is True

    def test_parent_resolves_path_relative_to_parent(self, tmp_path: Path) -> None:
        parent = Directory(tmp_path)
        child = Directory("child", parent=parent)
        assert child.path == (tmp_path / "child").absolute()

    def test_parent_with_none_path_resolves_to_parent_root(self, tmp_path: Path) -> None:
        parent = Directory(tmp_path)
        child = Directory(parent=parent)
        assert child.path == tmp_path.absolute()


class TestDirectoryProperties:
    def test_path_returns_absolute_path(self, tmp_path: Path) -> None:
        directory = Directory(tmp_path)
        assert directory.path == tmp_path
        assert isinstance(directory.path, Path)

    def test_fspath_returns_string(self, tmp_path: Path) -> None:
        directory = Directory(tmp_path)
        import os

        assert os.fspath(directory) == str(tmp_path)

    def test_str_returns_path_string(self, tmp_path: Path) -> None:
        directory = Directory(tmp_path)
        assert str(directory) == str(tmp_path)

    def test_repr_includes_class_name_and_path(self, tmp_path: Path) -> None:
        directory = Directory(tmp_path)
        result = repr(directory)
        assert result.startswith("Directory(")
        assert str(tmp_path) in result

    def test_truediv_returns_child_path(self, tmp_path: Path) -> None:
        directory = Directory(tmp_path)
        result = directory / "file.txt"
        assert result == tmp_path / "file.txt"
        assert isinstance(result, Path)


class TestDirectoryEquality:
    def test_equal_directories_with_same_path(self, tmp_path: Path) -> None:
        first = Directory(tmp_path)
        second = Directory(tmp_path)
        assert first == second

    def test_not_equal_with_different_paths(self, tmp_path: Path) -> None:
        first = Directory(tmp_path / "a")
        second = Directory(tmp_path / "b")
        assert first != second

    def test_not_equal_to_non_directory(self, tmp_path: Path) -> None:
        directory = Directory(tmp_path)
        assert directory != str(tmp_path)

    def test_ne_returns_true_for_different_paths(self, tmp_path: Path) -> None:
        first = Directory(tmp_path / "a")
        second = Directory(tmp_path / "b")
        assert first != second


class TestDirectoryCreate:
    def test_create_makes_directory(self, tmp_path: Path) -> None:
        directory = Directory(tmp_path / "new")
        assert not directory.path.exists()
        directory.create()
        assert directory.path.is_dir()

    def test_create_with_mkdirs_creates_parents(self, tmp_path: Path) -> None:
        directory = Directory(tmp_path / "a" / "b" / "c")
        directory.create(mkdirs=True)
        assert directory.path.is_dir()

    def test_create_exist_ok_does_not_raise(self, tmp_path: Path) -> None:
        directory = Directory(tmp_path)
        directory.create(exist_ok=True)

    def test_create_exist_ok_false_raises_on_existing(self, tmp_path: Path) -> None:
        directory = Directory(tmp_path)
        with pytest.raises(FileExistsError):
            directory.create(exist_ok=False)


class TestDirectoryExists:
    def test_exists_returns_true_for_existing_directory(self, tmp_path: Path) -> None:
        directory = Directory(tmp_path)
        assert directory.exists()

    def test_exists_returns_false_for_missing_directory(self, tmp_path: Path) -> None:
        directory = Directory(tmp_path / "nonexistent")
        assert not directory.exists()

    def test_exists_with_none_checks_directory_itself(self, tmp_path: Path) -> None:
        directory = Directory(tmp_path)
        assert directory.exists(None)

    def test_exists_with_relative_path_checks_child(self, tmp_path: Path) -> None:
        directory = Directory(tmp_path)
        (tmp_path / "file.txt").write_text("hello")
        assert directory.exists("file.txt")

    def test_exists_returns_false_for_missing_child(self, tmp_path: Path) -> None:
        directory = Directory(tmp_path)
        assert not directory.exists("nonexistent.txt")

    def test_exists_for_self_returns_false_if_path_is_file(self, tmp_path: Path) -> None:
        file_path = tmp_path / "a_file"
        file_path.write_text("content")
        directory = Directory(file_path)
        assert not directory.exists()


class TestDirectoryOpen:
    def test_open_read_existing_file(self, tmp_path: Path) -> None:
        (tmp_path / "file.txt").write_text("hello")
        directory = Directory(tmp_path)
        with directory.open("file.txt", "r") as handle:
            assert handle.read() == "hello"

    def test_open_write_creates_file(self, tmp_path: Path) -> None:
        directory = Directory(tmp_path)
        with directory.open("file.txt", "w") as handle:
            handle.write("hello")
        assert (tmp_path / "file.txt").read_text() == "hello"

    def test_open_write_creates_parent_directories(self, tmp_path: Path) -> None:
        directory = Directory(tmp_path)
        with directory.open("a/b/c/file.txt", "w") as handle:
            handle.write("nested")
        assert (tmp_path / "a" / "b" / "c" / "file.txt").read_text() == "nested"

    def test_open_read_does_not_create_parent_directories(self, tmp_path: Path) -> None:
        directory = Directory(tmp_path)
        with pytest.raises(FileNotFoundError):
            directory.open("nonexistent/file.txt", "r")

    def test_open_binary_mode(self, tmp_path: Path) -> None:
        directory = Directory(tmp_path)
        with directory.open("file.bin", "wb") as handle:
            handle.write(b"\x00\x01\x02")
        with directory.open("file.bin", "rb") as handle:
            assert handle.read() == b"\x00\x01\x02"

    def test_open_append_mode_creates_parent_dirs(self, tmp_path: Path) -> None:
        directory = Directory(tmp_path)
        with directory.open("sub/file.txt", "a") as handle:
            handle.write("appended")
        assert (tmp_path / "sub" / "file.txt").read_text() == "appended"

    def test_open_mkdirs_false_skips_directory_creation(self, tmp_path: Path) -> None:
        directory = Directory(tmp_path)
        with pytest.raises(FileNotFoundError):
            directory.open("missing_dir/file.txt", "w", mkdirs=False)

    def test_open_mkdirs_true_on_read_mode_creates_dirs(self, tmp_path: Path) -> None:
        directory = Directory(tmp_path)
        # Even in read mode, explicit mkdirs=True creates parent dirs.
        with pytest.raises(FileNotFoundError):
            directory.open("created_dir/file.txt", "r", mkdirs=True)
        assert (tmp_path / "created_dir").is_dir()


class TestDirectoryRemove:
    def test_remove_deletes_file(self, tmp_path: Path) -> None:
        file_path = tmp_path / "file.txt"
        file_path.write_text("hello")
        directory = Directory(tmp_path)
        directory.remove("file.txt")
        assert not file_path.exists()

    def test_remove_deletes_directory_recursively(self, tmp_path: Path) -> None:
        child = tmp_path / "child"
        child.mkdir()
        (child / "file.txt").write_text("hello")
        directory = Directory(tmp_path)
        directory.remove("child")
        assert not child.exists()

    def test_remove_non_recursive_fails_on_nonempty_dir(self, tmp_path: Path) -> None:
        child = tmp_path / "child"
        child.mkdir()
        (child / "file.txt").write_text("hello")
        directory = Directory(tmp_path)
        with pytest.raises(OSError):
            directory.remove("child", recursive=False)

    def test_remove_non_recursive_deletes_empty_dir(self, tmp_path: Path) -> None:
        child = tmp_path / "child"
        child.mkdir()
        directory = Directory(tmp_path)
        directory.remove("child", recursive=False)
        assert not child.exists()

    def test_remove_nonexistent_path_does_nothing(self, tmp_path: Path) -> None:
        directory = Directory(tmp_path)
        directory.remove("nonexistent")

    def test_remove_none_deletes_directory_itself(self, tmp_path: Path) -> None:
        target = tmp_path / "to_remove"
        target.mkdir()
        directory = Directory(target)
        directory.remove()
        assert not target.exists()


class TestDirectoryTouch:
    def test_touch_creates_empty_file(self, tmp_path: Path) -> None:
        directory = Directory(tmp_path)
        directory.touch("new_file.txt")
        assert (tmp_path / "new_file.txt").exists()
        assert (tmp_path / "new_file.txt").read_text() == ""

    def test_touch_existing_file_does_not_raise(self, tmp_path: Path) -> None:
        (tmp_path / "existing.txt").write_text("content")
        directory = Directory(tmp_path)
        directory.touch("existing.txt")
        assert (tmp_path / "existing.txt").read_text() == "content"


class TestDirectoryMove:
    def test_move_file_to_new_location(self, tmp_path: Path) -> None:
        (tmp_path / "source.txt").write_text("data")
        directory = Directory(tmp_path)
        directory.move("source.txt", "destination.txt")
        assert not (tmp_path / "source.txt").exists()
        assert (tmp_path / "destination.txt").read_text() == "data"

    def test_move_creates_destination_parent_directories(self, tmp_path: Path) -> None:
        (tmp_path / "source.txt").write_text("data")
        directory = Directory(tmp_path)
        directory.move("source.txt", "a/b/destination.txt")
        assert (tmp_path / "a" / "b" / "destination.txt").read_text() == "data"

    def test_move_directory(self, tmp_path: Path) -> None:
        source_directory = tmp_path / "source"
        source_directory.mkdir()
        (source_directory / "file.txt").write_text("inside")
        directory = Directory(tmp_path)
        directory.move("source", "target")
        assert not source_directory.exists()
        assert (tmp_path / "target" / "file.txt").read_text() == "inside"


class TestDirectorySubpath:
    def test_subpath_returns_absolute_child_path(self, tmp_path: Path) -> None:
        directory = Directory(tmp_path)
        result = directory.subpath("child")
        assert result == tmp_path / "child"
        assert result.is_absolute()

    def test_subpath_with_nested_relative(self, tmp_path: Path) -> None:
        directory = Directory(tmp_path)
        result = directory.subpath("a/b/c")
        assert result == tmp_path / "a" / "b" / "c"


class TestDirectorySubdir:
    def test_subdir_returns_child_directory(self, tmp_path: Path) -> None:
        directory = Directory(tmp_path)
        child = directory.subdir("child")
        assert isinstance(child, Directory)
        assert child.path == (tmp_path / "child").absolute()

    def test_subdir_temporary_forwarded(self, tmp_path: Path) -> None:
        directory = Directory(tmp_path)
        child = directory.subdir("child", temporary=True)
        assert child.temporary is True

    def test_subdir_temporary_defaults_to_false(self, tmp_path: Path) -> None:
        directory = Directory(tmp_path)
        child = directory.subdir("child")
        assert child.temporary is False


class TestDirectorySubpaths:
    def test_subpaths_lists_direct_children(self, tmp_path: Path) -> None:
        (tmp_path / "a.txt").write_text("a")
        (tmp_path / "b.txt").write_text("b")
        (tmp_path / "subdir").mkdir()
        directory = Directory(tmp_path)
        paths = directory.subpaths()
        names = sorted(path.name for path in paths)
        assert names == ["a.txt", "b.txt", "subdir"]

    def test_subpaths_returns_absolute_paths(self, tmp_path: Path) -> None:
        (tmp_path / "file.txt").write_text("content")
        directory = Directory(tmp_path)
        paths = directory.subpaths()
        for path in paths:
            assert path.is_absolute()

    def test_subpaths_with_relative_path(self, tmp_path: Path) -> None:
        child = tmp_path / "child"
        child.mkdir()
        (child / "file.txt").write_text("inner")
        directory = Directory(tmp_path)
        paths = directory.subpaths("child")
        assert len(paths) == 1
        assert paths[0].name == "file.txt"

    def test_subpaths_empty_directory(self, tmp_path: Path) -> None:
        directory = Directory(tmp_path)
        assert directory.subpaths() == []


class TestDirectoryIterSubpaths:
    def test_iter_subpaths_yields_all_children(self, tmp_path: Path) -> None:
        (tmp_path / "one.txt").write_text("1")
        (tmp_path / "two.txt").write_text("2")
        directory = Directory(tmp_path)
        paths = list(directory.iter_subpaths())
        names = sorted(path.name for path in paths)
        assert names == ["one.txt", "two.txt"]

    def test_iter_subpaths_with_none_lists_self(self, tmp_path: Path) -> None:
        (tmp_path / "file.txt").write_text("content")
        directory = Directory(tmp_path)
        paths = list(directory.iter_subpaths(None))
        assert len(paths) == 1
        assert paths[0].name == "file.txt"


class TestDirectorySubdirs:
    def test_subdirs_returns_only_directories(self, tmp_path: Path) -> None:
        (tmp_path / "file.txt").write_text("a")
        (tmp_path / "dir_a").mkdir()
        (tmp_path / "dir_b").mkdir()
        directory = Directory(tmp_path)
        directories = directory.subdirs()
        names = sorted(str(directory.path.name) for directory in directories)
        assert names == ["dir_a", "dir_b"]

    def test_subdirs_returns_directory_instances(self, tmp_path: Path) -> None:
        (tmp_path / "child").mkdir()
        directory = Directory(tmp_path)
        directories = directory.subdirs()
        assert all(isinstance(directory, Directory) for directory in directories)

    def test_subdirs_empty_when_no_dirs(self, tmp_path: Path) -> None:
        (tmp_path / "file.txt").write_text("a")
        directory = Directory(tmp_path)
        assert directory.subdirs() == []


class TestDirectoryIterSubdirs:
    def test_iter_subdirs_yields_only_directories(self, tmp_path: Path) -> None:
        (tmp_path / "file.txt").write_text("a")
        (tmp_path / "child_dir").mkdir()
        directory = Directory(tmp_path)
        directories = list(directory.iter_subdirs())
        assert len(directories) == 1
        assert directories[0].path.name == "child_dir"

    def test_iter_subdirs_with_relative_path(self, tmp_path: Path) -> None:
        parent = tmp_path / "parent"
        parent.mkdir()
        (parent / "inner_dir").mkdir()
        (parent / "inner_file.txt").write_text("x")
        directory = Directory(tmp_path)
        directories = list(directory.iter_subdirs("parent"))
        assert len(directories) == 1
        assert directories[0].path.name == "inner_dir"


class TestDirectoryPathResolution:
    def test_resolve_relative_path(self, tmp_path: Path) -> None:
        directory = Directory(tmp_path)
        resolved = directory._resolve("child/file.txt")
        assert resolved == (tmp_path / "child" / "file.txt").absolute()

    def test_resolve_absolute_path_unchanged(self, tmp_path: Path) -> None:
        directory = Directory(tmp_path)
        absolute = tmp_path / "other" / "file.txt"
        resolved = directory._resolve(absolute)
        assert resolved == absolute

    def test_resolve_none_returns_directory_path(self, tmp_path: Path) -> None:
        directory = Directory(tmp_path)
        resolved = directory._resolve(None)
        assert resolved == (tmp_path / ".").absolute()

    def test_resolve_string_path(self, tmp_path: Path) -> None:
        directory = Directory(tmp_path)
        resolved = directory._resolve("file.txt")
        assert resolved == (tmp_path / "file.txt").absolute()


class TestDirectoryTemporaryCleanup:
    def test_del_removes_temporary_directory(self, tmp_path: Path) -> None:
        target = tmp_path / "temp_dir"
        target.mkdir()
        directory = Directory(target, temporary=True)
        directory.__del__()
        assert not target.exists()

    def test_del_does_not_remove_non_temporary_directory(self, tmp_path: Path) -> None:
        directory = Directory(tmp_path, temporary=False)
        directory.__del__()
        assert tmp_path.exists()

    def test_del_suppresses_errors_on_missing_directory(self, tmp_path: Path) -> None:
        target = tmp_path / "already_gone"
        directory = Directory(target, temporary=True)
        # Should not raise even though the directory never existed.
        directory.__del__()


class TestDirectorySetupWriteOperation:
    def test_write_mode_creates_parent_directories(self, tmp_path: Path) -> None:
        directory = Directory(tmp_path)
        result = directory._setup_write_operation("a/b/file.txt", None, "w")
        assert result.parent.is_dir()

    def test_read_mode_does_not_create_parent_directories(self, tmp_path: Path) -> None:
        directory = Directory(tmp_path)
        directory._setup_write_operation("missing/file.txt", None, "r")
        assert not (tmp_path / "missing").exists()

    def test_explicit_mkdirs_true_overrides_mode(self, tmp_path: Path) -> None:
        directory = Directory(tmp_path)
        directory._setup_write_operation("x/y/file.txt", True, "r")
        assert (tmp_path / "x" / "y").is_dir()

    def test_explicit_mkdirs_false_overrides_mode(self, tmp_path: Path) -> None:
        directory = Directory(tmp_path)
        directory._setup_write_operation("no_create/file.txt", False, "w")
        assert not (tmp_path / "no_create").exists()
