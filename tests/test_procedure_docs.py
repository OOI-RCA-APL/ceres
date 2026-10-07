from collections.abc import Mapping
from typing import Annotated, Any

from pydantic import Field

from ceres import Component, action, query
from ceres.component import ProcedureRaiseInfo


class _Stage(Component):
    @action
    async def move(
        self,
        x: float,
        y: Annotated[float, Field(description="Declared on the field.")] = 0.0,
        z: float = Field(default=0.0, description="Declared on the default."),
        speed: float = 1.0,
    ) -> bool:
        """Move the stage to a **position**.

        Args:
            x: Where to go along x,
                in millimetres.
            y: Docstring text for y.
            z: Docstring text for z.
            removed: An argument the signature no longer has.

        Returns:
            Whether the stage arrived.

        Raises:
            ValueError: If the position is out of range.
        """
        return True

    @query
    async def position(self) -> float:
        """Where the stage is.

        :returns: The position along x.
        :raises: Never.
        """
        return 0.0

    @query
    async def plain(self) -> int:
        return 0


def _bindings():
    return _Stage(__with_name__="stage").system.get_procedure_bindings()


def _arguments_schema(name: str) -> Mapping[str, Any]:
    arguments = _bindings()[name].arguments
    assert arguments is not None
    return arguments.json_schema


def test_arguments_take_their_docstring_text():
    schema = _arguments_schema("move")
    properties = schema["properties"]

    assert schema["description"] == "Move the stage to a **position**."
    assert properties["x"]["description"] == "Where to go along x,\nin millimetres."
    assert "description" not in properties["speed"]
    assert "removed" not in properties


def test_a_declared_description_wins_over_the_docstring():
    properties = _arguments_schema("move")["properties"]

    assert properties["y"]["description"] == "Declared on the field."
    assert properties["z"]["description"] == "Declared on the default."


def test_bindings_carry_returns_and_raises():
    bindings = _bindings()

    assert bindings["move"].returns == "Whether the stage arrived."
    assert bindings["move"].raises == (
        ProcedureRaiseInfo(type="ValueError", description="If the position is out of range."),
    )
    assert bindings["position"].returns == "The position along x."
    assert bindings["position"].raises == (ProcedureRaiseInfo(type=None, description="Never."),)


def test_a_procedure_without_a_docstring_carries_nothing():
    binding = _bindings()["plain"]

    assert "description" not in _arguments_schema("plain")
    assert binding.returns is None
    assert binding.raises == ()
