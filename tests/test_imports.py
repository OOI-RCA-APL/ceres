# Make sure we can import everything in the root module.

import warnings

import ceres
from ceres import *  # noqa: F403


def test_imports() -> None:
    """
    Make sure all modules are importable without errors or warnings, and that import * on the root
    module works correctly.
    """

    with warnings.catch_warnings():
        warnings.simplefilter("error")
        from ceres._internal.util import import_submodules

        import_submodules(ceres)

    from ceres.component import Component as DirectImportComponent

    assert Component is DirectImportComponent  # noqa: F405


def test_models_are_valid() -> None:
    """
    Because `BaseModel` and Pydantic dataclasses can have `defer_build = True` set in their config
    by default, this test makes sure all models and Pydantic dataclasses can actually be built.
    """
    with warnings.catch_warnings():
        warnings.simplefilter("error")

        from pydantic import BaseModel
        from pydantic.dataclasses import is_pydantic_dataclass, rebuild_dataclass

        from ceres._internal.lazy import unlazy
        from ceres._internal.util import import_submodules

        models: list[type[BaseModel]] = []
        dataclasses: list[type] = []

        for module in import_submodules(ceres).values():
            for value in module.__dict__.values():
                value = unlazy(value)
                if isinstance(value, type):
                    if issubclass(value, BaseModel) and value is not BaseModel:
                        models.append(value)
                    elif is_pydantic_dataclass(value):
                        dataclasses.append(value)

        assert len(models) > 1
        for model in models:
            model.model_rebuild()

        assert len(dataclasses) > 1
        for dataclass in dataclasses:
            rebuild_dataclass(dataclass)
