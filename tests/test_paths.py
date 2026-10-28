import json
import re
import socket
from datetime import datetime
from pathlib import Path, PurePosixPath
from typing import Any

import pytest
import tzlocal
from pydantic import BaseModel, ValidationError

from ceres.paths import PathTemplate, proj, rel, zone_name


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


# Shared with the console's renderer, `console/tests/path-template.test.ts`.
VECTORS = json.loads((Path(__file__).parent / "vectors/path-template.json").read_text())


def at(when: str) -> datetime:
    return datetime.fromisoformat(when)


class TestPathTemplate:
    @pytest.mark.parametrize("case", VECTORS["render"], ids=lambda case: case["template"])
    def test_renders(self, case: dict[str, Any]) -> None:
        template = PathTemplate(case["template"], atoms=case.get("atoms", ()))
        rendered = template.render(at(case["when"]), case.get("zone", "utc"), case.get("values"))
        assert rendered == case["expected"]

    @pytest.mark.parametrize("case", VECTORS["invalid"], ids=lambda case: case["template"])
    def test_refuses(self, case: dict[str, Any]) -> None:
        with pytest.raises(ValueError):
            PathTemplate(case["template"], atoms=case.get("atoms", ()))

    @pytest.mark.parametrize("case", VECTORS["unrenderable"], ids=lambda case: str(case["values"]))
    def test_refuses_to_render(self, case: dict[str, Any]) -> None:
        with pytest.raises(ValueError):
            PathTemplate(case["template"]).render(at("2026-10-27T13:45:09Z"), values=case["values"])

    @pytest.mark.parametrize(
        ("template", "meant"),
        [
            ("{YYYY}", "'{yyyy}' for the year"),
            ("{DD}", "'{dd}' for the day of the month"),
            ("{yyyy}-{mm}-{dd}", "'{MM}' the month"),
            ("{hh}{mm}", "the 24-hour hour is '{HH}'"),
            ("{zzzz}", "use '{Z}' or '{XX}'"),
            ("{SSSSSSS}", "'{SSSSSS}', the microsecond"),
        ],
    )
    def test_names_the_symbol_meant(self, template: str, meant: str) -> None:
        with pytest.raises(ValueError, match=re.escape(meant)):
            PathTemplate(template)

    def test_refuses_naive_time(self) -> None:
        with pytest.raises(ValueError, match="timezone-aware"):
            PathTemplate("{yyyy}").render(datetime(2026, 10, 27))  # noqa: DTZ001

    def test_renders_local_zone(self) -> None:
        when = at("2026-10-27T13:45:09Z")
        assert PathTemplate("{HH}").render(when, "local") == f"{when.astimezone().hour:02d}"

    def test_renders_host_by_default(self) -> None:
        host = socket.gethostname().partition(".")[0]
        assert PathTemplate("{host}").render(at("2026-10-27T13:45:09Z")) == host

    def test_refuses_unknown_zone(self) -> None:
        with pytest.raises(ValueError, match="not a time zone"):
            PathTemplate("{yyyy}").render(at("2026-10-27T13:45:09Z"), "abc")

    def test_compares_by_source(self) -> None:
        assert PathTemplate("{yyyy}") == PathTemplate("{yyyy}")
        assert len({PathTemplate("{yyyy}"), PathTemplate("{yyyy}")}) == 1
        assert str(PathTemplate("{yyyy}")) == "{yyyy}"


class TestZoneName:
    def test_names_each_zone_by_its_iana_name(self) -> None:
        assert zone_name("utc") == "UTC"
        assert zone_name("America/Los_Angeles") == "America/Los_Angeles"
        assert zone_name("local") == tzlocal.get_localzone_name()

    def test_refuses_unknown_zone(self) -> None:
        with pytest.raises(ValueError, match="not a time zone"):
            zone_name("abc")


class Producer(BaseModel):
    name: PathTemplate = PathTemplate.Field("{yyyy}{MM}{dd}_{sequence}", atoms=["sequence"])
    folder: PathTemplate = PathTemplate("{yyyy}")


class TestPathTemplateField:
    def test_accepts_declared_atoms(self) -> None:
        assert Producer().name == PathTemplate("{yyyy}{MM}{dd}_{sequence}", atoms=["sequence"])
        assert Producer(name="{sequence}").name.atoms == {"sequence"}  # type: ignore[arg-type]

    def test_refuses_undeclared_atom(self) -> None:
        with pytest.raises(ValidationError, match="not an atom"):
            Producer(folder="{sequence}")  # type: ignore[arg-type]

    def test_refuses_bad_default_when_declared(self) -> None:
        with pytest.raises(ValueError, match="not an atom"):
            PathTemplate.Field("{abc}")

    def test_serializes_source(self) -> None:
        assert Producer().model_dump() == {"name": "{yyyy}{MM}{dd}_{sequence}", "folder": "{yyyy}"}
