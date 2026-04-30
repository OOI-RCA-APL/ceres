import re
from pathlib import Path
from unittest.mock import mock_open, patch

from ceres.version import __version__


def test_version_is_nonempty_string():
    assert isinstance(__version__, str)
    assert len(__version__) > 0


def test_version_matches_pyproject():
    pyproject_path = Path(__file__).parent.parent / "pyproject.toml"
    expected_version = None

    with open(pyproject_path) as file:
        for line in file:
            if line.startswith("version"):
                expected_version = line.split("=")[1].strip().strip('"')
                break

    assert expected_version is not None
    assert __version__ == expected_version


def test_version_looks_valid():
    assert re.fullmatch(r"\d+(\.\d+)*", __version__)


def test_version_fallback_path():
    fake_toml = 'version = "1.2.3"\n'

    with (
        patch("importlib.metadata.version", side_effect=ImportError),
        patch("builtins.open", mock_open(read_data=fake_toml)),
    ):
        from ceres.version import __get_version

        result = __get_version()

    assert result == "1.2.3"


def test_version_raises_when_all_sources_fail():
    fake_toml = "no-version-here\n"

    with (
        patch("importlib.metadata.version", side_effect=ImportError),
        patch("builtins.open", mock_open(read_data=fake_toml)),
    ):
        from ceres.version import __get_version

        try:
            __get_version()
            assert False, "Expected RuntimeError"
        except RuntimeError:
            pass
