from typing import Any

import pytest
from pydantic import ValidationError, model_validator

from ceres.address import AddressSelector
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


async def test_engine_holds_a_forest_of_top_level_components() -> None:
    engine = Engine()
    await engine.load(
        _config({"alpha": "ceres.component:Component", "beta": "ceres.component:Component"}),
        checks=(),
    )

    addresses = {str(component.system.address) for component in engine.get_components()}
    assert addresses == {"@alpha", "@beta"}
    assert engine.get_component("@alpha") is not None
    assert engine.get_component("beta") is not None
    assert engine.get_component(None) is None

    await engine.database.dispose()


def test_engine_get_components_filters_across_the_forest() -> None:
    engine = Engine()
    alpha = Component(__with_name__="alpha")
    beta = Component(__with_name__="beta")
    alpha.system.attach(Component(__with_name__="child"))
    engine.attach(alpha)
    engine.attach(beta)

    def addresses(selector: str) -> set[str]:
        components = engine.get_components(AddressSelector(selector))
        return {str(component.system.address) for component in components}

    assert addresses("@alpha:all") == {"@alpha", "@alpha.child"}
    assert addresses("@alpha") == {"@alpha"}
    assert addresses(":all") == {"@alpha", "@alpha.child", "@beta"}


async def test_root_config_key_is_rejected() -> None:
    with pytest.raises(ValidationError, match="root"):
        validate(Config, {"root": {"components": []}})


async def test_top_level_component_names_must_be_unique() -> None:
    with pytest.raises(ValidationError, match="duplicate"):
        validate(
            Config,
            {"components": [{"name": "alpha"}, {"name": "alpha"}]},
        )


async def test_engine_reload_drops_removed_top_level_components() -> None:
    engine = Engine()
    await engine.load(
        _config({"alpha": "ceres.component:Component", "beta": "ceres.component:Component"}),
        checks=(),
    )

    await engine.load(_config({"alpha": "ceres.component:Component"}), checks=())

    addresses = {str(component.system.address) for component in engine.get_components()}
    assert addresses == {"@alpha"}
    assert engine.get_component("@alpha") is not None
    assert engine.get_component("@beta") is None

    await engine.database.dispose()
