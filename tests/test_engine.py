from typing import Any

import pytest
from pydantic import ValidationError, model_validator

from ceres.address import AddressSelector
from ceres.component import Component
from ceres.config import Config, ConfigCheckType
from ceres.data import validate
from ceres.engine import Engine
from ceres.error import ComponentCombinedError, ConfigCombinedError
from ceres.reference import Ref, unref


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


def test_get_component_resolves_absolute_addresses_across_top_level_trees() -> None:
    engine = Engine()
    alpha = Component(__with_name__="alpha")
    beta = Component(__with_name__="beta")
    child = Component(__with_name__="child")
    beta.system.attach(child)
    engine.attach(alpha)
    engine.attach(beta)

    assert alpha.system.get_component("@beta.child") is child
    assert child.system.get_component("@alpha") is alpha


def test_get_component_with_absolute_address_on_detached_system_stays_local() -> None:
    alpha = Component(__with_name__="alpha")

    assert alpha.system.get_component("@beta") is None
    assert alpha.system.get_component("@alpha") is alpha


async def test_engine_detach_clears_the_system_container() -> None:
    engine = Engine()
    alpha = Component(__with_name__="alpha")
    engine.attach(alpha)

    engine.detach(alpha)

    assert alpha.system.container is None
    assert engine.get_component("@alpha") is None


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


class CrossTreeReferencer(Component):
    """A component holding a reference to a component in another top-level tree."""

    target: Ref[Component]


def _cross_tree_config(target: str) -> Config:
    return validate(
        Config,
        {
            "database": {"type": "sqlite", "path": ":memory:"},
            "components": [
                {
                    "name": "alpha",
                    "class": "tests.test_engine:CrossTreeReferencer",
                    "arguments": {"target": target},
                },
                {
                    "name": "beta",
                    "class": "ceres.component:Component",
                    "components": [{"name": "x", "class": "ceres.component:Component"}],
                },
            ],
        },
    )


async def test_cross_tree_reference_resolves_on_strict_first_load() -> None:
    engine = Engine()
    await engine.load(_cross_tree_config("@beta.x"), checks=())

    alpha = engine.get_component("@alpha")
    target = engine.get_component("@beta.x")
    assert isinstance(alpha, CrossTreeReferencer)
    assert target is not None
    assert unref(alpha.target) is target

    await engine.database.dispose()


async def test_cross_tree_reference_passes_config_checks() -> None:
    # Trial creation with component checks enabled must resolve the cross-tree reference.
    await Config.load(_cross_tree_config("@beta.x"), checks=(ConfigCheckType.COMPONENTS,))


async def test_dangling_cross_tree_reference_fails_strict_first_load() -> None:
    engine = Engine()
    with pytest.raises(ComponentCombinedError):
        await engine.load(_cross_tree_config("@beta.missing"), checks=())

    await engine.database.dispose()


async def test_dangling_cross_tree_reference_fails_config_checks() -> None:
    with pytest.raises(ConfigCombinedError):
        await Config.load(_cross_tree_config("@beta.missing"), checks=(ConfigCheckType.COMPONENTS,))
