"""Filters the CLI builds from a command's fields.

The settings layer gives every command a value for every field, so a command cannot
report which of them an invocation actually named. Models that read set-ness as a
sentinel depend on the conversion restoring it, and a variable's `value` is one, where
"unmentioned" and "explicitly null" mean different things.
"""

from typing import TYPE_CHECKING

from pydantic_settings import CliApp

from ceres import Engine
from ceres.__internal__.cli.shared import (
    create_entity_count_command,
    create_entity_select_command,
)
from ceres.address import Address
from ceres.config import Config
from ceres.data import validate
from ceres.variable import Variable

if TYPE_CHECKING:
    from pathlib import Path


def _invoke[T](Command: type[T], *arguments: str) -> T:
    """Build one command the way an invocation would."""
    return CliApp.run(
        Command,
        cli_args=[*arguments, "--no-color"],
        cli_cmd_method_name="_globals",
    )


async def _build_project(tmp_path: Path) -> Engine:
    """Write a project config on a file-backed database and store two variables."""
    (tmp_path / "ceres.yaml").write_text(
        "components: []\ndatabase:\n  type: sqlite\n  path: records.sqlite\n"
    )
    engine = Engine()
    await engine.load(
        validate(
            Config,
            {
                "components": [],
                "database": {"type": "sqlite", "path": str(tmp_path / "records.sqlite")},
            },
        ),
        checks=(),
    )
    await engine.database.migrate()
    await engine.variables.create(
        Variable.Create(address=Address("@a"), name="__enabled__", value=True)
    )
    await engine.variables.create(Variable.Create(address=Address("@b"), name="x", value=5))
    return engine


def test_an_unmentioned_field_reaches_the_filter_unset() -> None:
    """A field the invocation never named leaves no constraint behind."""
    Command = create_entity_select_command(Variable)

    assert _invoke(Command).read(Variable.Filter).model_fields_set == set()
    assert _invoke(Command, "--name", "x").read(Variable.Filter).model_fields_set == {"name"}


async def test_an_unfiltered_select_matches_every_variable(tmp_path: Path) -> None:
    """A bare select is unconstrained, which a set-ness sentinel read wrongly would not be."""
    engine = await _build_project(tmp_path)
    Command = create_entity_select_command(Variable)
    command = _invoke(Command, "--config", str(tmp_path / "ceres.yaml"))

    try:
        matched = await engine.variables.where(command.read(Variable.Filter))
        assert [variable.name for variable in matched] == ["__enabled__", "x"]
    finally:
        await engine.database.dispose()


async def test_a_value_filter_compares_against_the_parsed_value(tmp_path: Path) -> None:
    """A value reads as YAML, so a number compares as a number rather than as its text."""
    engine = await _build_project(tmp_path)
    Command = create_entity_select_command(Variable)

    try:
        for argument, expected in (("5", ["x"]), ("true", ["__enabled__"]), ("6", [])):
            command = _invoke(Command, "--value", argument)
            filter = command.read(Variable.Filter)
            assert [variable.name for variable in await engine.variables.where(filter)] == expected
            # The in-memory matcher and the compiled query agree on the same values.
            assert [
                variable.name
                for variable in await engine.variables.where()
                if filter.matches(variable)
            ] == expected
    finally:
        await engine.database.dispose()


async def test_the_internal_predicate_splits_the_two_naming_conventions(tmp_path: Path) -> None:
    """An internal variable is one whose name both opens and closes with two underscores."""
    engine = await _build_project(tmp_path)
    Command = create_entity_count_command(Variable)

    try:
        for argument, expected in (("--internal", 1), ("--no-internal", 1)):
            filter = _invoke(Command, argument).read(Variable.Filter)
            assert await engine.variables.where(filter).count() == expected
    finally:
        await engine.database.dispose()
