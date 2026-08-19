"""The generated model modules present as part of their public modules.

Each generated module reassigns its classes' `__module__` to the public module that
re-exports them, which is what reprs, pickles, and rendered documentation show. A class
the generator misses keeps working in place, so only this sweep notices.
"""

import pickle
from importlib import import_module

import pytest

MODULES = [
    "ceres.__internal__.models.alerts",
    "ceres.__internal__.models.groups",
    "ceres.__internal__.models.logs",
    "ceres.__internal__.models.messages",
    "ceres.__internal__.models.permissions",
    "ceres.__internal__.models.settings",
    "ceres.__internal__.models.users",
    "ceres.__internal__.models.variables",
    "ceres.__internal__.models.workspaces",
]


@pytest.mark.parametrize("name", MODULES)
def test_generated_classes_present_under_the_public_module(name: str):
    module = import_module(name)
    for exported in module.__all__:
        model = getattr(module, exported)
        if not isinstance(model, type):
            # The `type` aliases stay put, `TypeAliasType.__module__` is read-only.
            continue

        assert model.__module__ != name, exported
        public = import_module(model.__module__)
        assert getattr(public, exported) is model, exported


def test_generated_enums_pickle_through_the_public_module():
    from ceres.message import MessageDirection
    from ceres.permission import PermissionTargetType

    for member in (MessageDirection.SEND, PermissionTargetType.TAG):
        assert pickle.loads(pickle.dumps(member)) is member
