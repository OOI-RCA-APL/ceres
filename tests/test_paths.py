from pathlib import Path, PurePosixPath

from ceres.paths import proj, rel


class TestRel:
    def test_returns_path_object(self) -> None:
        result = rel("something")
        assert isinstance(result, Path)

    def test_resolves_relative_to_calling_module(self) -> None:
        result = rel("child")
        expected = Path(__file__) / "child"
        assert result == expected

    def test_accepts_string_argument(self) -> None:
        result = rel("some/nested/path")
        expected = Path(__file__) / "some/nested/path"
        assert result == expected

    def test_accepts_path_argument(self) -> None:
        result = rel(Path("some/nested/path"))
        expected = Path(__file__) / "some/nested/path"
        assert result == expected

    def test_accepts_pure_posix_path(self) -> None:
        result = rel(PurePosixPath("some/nested/path"))
        expected = Path(__file__) / "some/nested/path"
        assert result == expected


class TestProj:
    def test_returns_path_object(self) -> None:
        result = proj()
        assert isinstance(result, Path)

    def test_no_argument_returns_project_root(self) -> None:
        result = proj()
        assert (result / "pyproject.toml").is_file()

    def test_no_argument_result_is_directory(self) -> None:
        result = proj()
        assert result.is_dir()

    def test_relative_path_joins_onto_root(self) -> None:
        root = proj()
        result = proj("some/path")
        assert result == root / "some/path"

    def test_relative_path_to_known_file(self) -> None:
        result = proj("pyproject.toml")
        assert result.is_file()

    def test_relative_with_path_object(self) -> None:
        root = proj()
        result = proj(Path("ceres/paths.py"))
        assert result == root / "ceres/paths.py"

    def test_none_argument_returns_root(self) -> None:
        result = proj(None)
        root = proj()
        assert result == root
