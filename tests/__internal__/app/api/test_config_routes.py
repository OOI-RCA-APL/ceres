from typing import Any

from fastapi.routing import APIRoute
from pydantic import TypeAdapter

from ceres.__internal__.app.api.routes import config as config_routes
from ceres.config import Config
from ceres.data import validate

SECRET = "a-signing-secret-nobody-should-see"
KEY_PASSWORD = "a-private-key-password"
DATABASE_PASSWORD = "a-database-password"


def _build_config() -> Config:
    return validate(
        Config,
        {
            "components": [],
            "server": {
                "authentication": {"secret": SECRET},
                "ssl": {"key": "/tmp/key.pem", "key_password": KEY_PASSWORD},
            },
            "database": {
                "type": "postgres",
                "host": "localhost",
                "database": "ceres",
                "user": "ceres",
                "password": DATABASE_PASSWORD,
            },
        },
    )


def _serialize(value: Any, exclude: Any) -> str:
    """Serialize `value` the way a route on the config router does."""
    return TypeAdapter(type(value)).dump_json(value, exclude=exclude, by_alias=True).decode()


def test_every_config_route_excludes_credentials() -> None:
    """The exclusion belongs to the router, so a route added later inherits it rather than
    having to remember it.
    """
    routes = [route for route in config_routes.router.routes if isinstance(route, APIRoute)]

    assert len(routes) > 0
    for route in routes:
        assert route.response_model_exclude == config_routes.EXCLUDE_CREDENTIALS, route.path


def test_the_config_response_does_not_carry_the_signing_secret() -> None:
    """The signing secret mints a token for any user, so serving it hands over every account."""
    config = _build_config()

    assert SECRET not in _serialize(config, config_routes.EXCLUDE_CREDENTIALS)
    assert SECRET not in _serialize(config.server, config_routes.EXCLUDE_CREDENTIALS)


def test_the_config_response_does_not_carry_the_private_key_password() -> None:
    config = _build_config()

    assert KEY_PASSWORD not in _serialize(config, config_routes.EXCLUDE_CREDENTIALS)
    assert KEY_PASSWORD not in _serialize(config.server, config_routes.EXCLUDE_CREDENTIALS)


def test_the_config_response_does_not_carry_the_database_password() -> None:
    config = _build_config()

    assert DATABASE_PASSWORD not in _serialize(config, config_routes.EXCLUDE_CREDENTIALS)
    assert DATABASE_PASSWORD not in _serialize(config.database, config_routes.EXCLUDE_CREDENTIALS)


def test_the_config_response_still_carries_everything_else() -> None:
    """Excluding by field name is broad, so the rest of the configuration must survive it."""
    config = _build_config()

    serialized = _serialize(config.server, config_routes.EXCLUDE_CREDENTIALS)
    assert "0.0.0.0" in serialized
    assert "duration" in serialized


def test_the_secret_is_still_readable_where_it_is_used() -> None:
    """The exclusion is for responses only, signing still needs the real value."""
    config = _build_config()

    authentication = config.server.authentication
    assert authentication is not None
    assert authentication.secret == SECRET
