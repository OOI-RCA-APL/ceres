from typing import Any

import pytest
from pydantic import model_validator

from ceres.component import Component
from ceres.config import Config
from ceres.data import validate
from ceres.engine import Engine
from ceres.error import ComponentCombinedError


class BrokenComponent(Component):
    """A component whose creation always fails once it is attached to a tree."""

    @model_validator(mode="before")
    @classmethod
    def _explode_on_creation(cls, data: Any) -> Any:
        # Configuration validation checks the bare arguments, real creation passes the attach
        # context, so only the latter fails.
        if isinstance(data, dict) and data.get("__with_config__") is not None:
            raise RuntimeError("This component always fails to construct.")

        return data


def _config(component_names_to_classes: dict[str, str]) -> Config:
    return validate(
        Config,
        {
            "database": {"type": "sqlite", "path": ":memory:"},
            "components": [
                {"name": name, "class": cls} for name, cls in component_names_to_classes.items()
            ],
        },
    )


async def test_first_load_fails_when_a_component_cannot_be_created() -> None:
    engine = Engine()
    config = _config({"broken": "tests.test_engine:BrokenComponent"})

    # Bypass the load-time checks so the apply-stage strictness itself is exercised.
    with pytest.raises(ComponentCombinedError):
        await engine.load(config, checks=())

    await engine.database.dispose()


async def test_reload_tolerates_a_component_that_cannot_be_created() -> None:
    engine = Engine()
    await engine.load(_config({"fine": "ceres.component:Component"}), checks=())

    # A reload that introduces a broken component logs the failure and keeps the engine alive.
    await engine.load(
        _config(
            {
                "fine": "ceres.component:Component",
                "broken": "tests.test_engine:BrokenComponent",
            }
        ),
        checks=(),
    )

    names = {component.system.address.name for component in engine.get_components()}
    assert "fine" in names
    assert "broken" not in names

    await engine.database.dispose()
