from uuid import uuid4

import pytest
from fastapi import Response

from ceres import Engine
from ceres.__internal__.app.api.routes.auth import SwitchUserInput, switch_user
from ceres.__internal__.app.shared import Identity, create_identity
from ceres.config import Config, ServerAuthenticationConfig
from ceres.data import validate
from ceres.error import (
    AuthenticationDisabledError,
    NotAuthenticatedError,
    NotFoundError,
    NotPermittedError,
)
from ceres.user import User


async def _build_engine(allow_user_switching: bool = True) -> Engine:
    engine = Engine()
    await engine.database.migrate()
    await engine.load(
        validate(
            Config,
            {
                "components": [],
                "server": {
                    "authentication": {
                        "secret": "test-secret",
                        "allow_user_switching": allow_user_switching,
                    }
                },
            },
        ),
        checks=(),
    )
    return engine


async def _create_user(engine: Engine, username: str, admin: bool = False) -> User:
    return await engine.database.users.create(
        User.Create(username=username, email=f"{username}@test.com", password="hashed", admin=admin)
    )


def _identity(engine: Engine, user: User) -> Identity:
    authentication = engine.config.server.authentication
    assert authentication is not None
    return create_identity(user, authentication)


async def test_switching_is_absent_unless_it_is_turned_on() -> None:
    """The route reports itself missing rather than forbidden, so a default deployment has no
    trace of it to find.
    """
    engine = await _build_engine(allow_user_switching=False)
    admin = await _create_user(engine, "admin", admin=True)
    viewer = await _create_user(engine, "viewer")

    with pytest.raises(NotFoundError):
        await switch_user(
            engine=engine,
            identity=_identity(engine, admin),
            response=Response(),
            input=SwitchUserInput(user_id=viewer.id),
        )

    await engine.database.dispose()


async def test_switching_requires_authentication_to_be_configured() -> None:
    engine = Engine()
    await engine.database.migrate()
    await engine.load(validate(Config, {"components": []}), checks=())
    viewer = await _create_user(engine, "viewer")

    with pytest.raises(AuthenticationDisabledError):
        await switch_user(
            engine=engine,
            identity=None,
            response=Response(),
            input=SwitchUserInput(user_id=viewer.id),
        )

    await engine.database.dispose()


async def test_switching_requires_a_caller() -> None:
    engine = await _build_engine()
    viewer = await _create_user(engine, "viewer")

    with pytest.raises(NotAuthenticatedError):
        await switch_user(
            engine=engine,
            identity=None,
            response=Response(),
            input=SwitchUserInput(user_id=viewer.id),
        )

    await engine.database.dispose()


async def test_a_non_admin_cannot_switch() -> None:
    engine = await _build_engine()
    viewer = await _create_user(engine, "viewer")
    other = await _create_user(engine, "other")

    with pytest.raises(NotPermittedError):
        await switch_user(
            engine=engine,
            identity=_identity(engine, viewer),
            response=Response(),
            input=SwitchUserInput(user_id=other.id),
        )

    await engine.database.dispose()


async def test_an_admin_switches_and_the_identity_records_who_switched() -> None:
    engine = await _build_engine()
    admin = await _create_user(engine, "admin", admin=True)
    viewer = await _create_user(engine, "viewer")

    switched = await switch_user(
        engine=engine,
        identity=_identity(engine, admin),
        response=Response(),
        input=SwitchUserInput(user_id=viewer.id),
    )

    assert switched.user.id == viewer.id
    assert switched.switched_from == admin.id

    await engine.database.dispose()


async def test_a_switched_identity_cannot_switch_again() -> None:
    """The issued identity is the target user's, so it carries no right to switch onward."""
    engine = await _build_engine()
    admin = await _create_user(engine, "admin", admin=True)
    viewer = await _create_user(engine, "viewer")
    other = await _create_user(engine, "other")

    switched = await switch_user(
        engine=engine,
        identity=_identity(engine, admin),
        response=Response(),
        input=SwitchUserInput(user_id=viewer.id),
    )

    with pytest.raises(NotPermittedError):
        await switch_user(
            engine=engine,
            identity=switched,
            response=Response(),
            input=SwitchUserInput(user_id=other.id),
        )

    with pytest.raises(NotPermittedError):
        await switch_user(
            engine=engine,
            identity=switched,
            response=Response(),
            input=SwitchUserInput(user_id=admin.id),
        )

    await engine.database.dispose()


async def test_switching_to_a_missing_user_is_not_found() -> None:
    engine = await _build_engine()
    admin = await _create_user(engine, "admin", admin=True)

    with pytest.raises(NotFoundError):
        await switch_user(
            engine=engine,
            identity=_identity(engine, admin),
            response=Response(),
            input=SwitchUserInput(user_id=uuid4()),
        )

    await engine.database.dispose()


async def test_user_switching_defaults_to_off() -> None:
    assert ServerAuthenticationConfig(secret="test-secret").allow_user_switching is False
