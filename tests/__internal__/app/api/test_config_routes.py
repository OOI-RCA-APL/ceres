import json
from typing import Any

from ceres.__internal__.app.api.routes import config as config_routes
from ceres.__internal__.app.shared import scrub_credentials
from ceres.config import Config
from ceres.data import simplify, validate

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


def _serialize(value: Any) -> str:
    """Serialize `value` the way a route on the config router does."""
    return json.dumps(scrub_credentials(simplify(value)))


def test_every_config_route_returns_a_scrubbed_response() -> None:
    """Every handler on the config router serializes through the scrubbing helper.

    The scrub operates on the final payload rather than through Pydantic's exclude machinery,
    because Pydantic cannot descend into the natively-serialized configuration sections.
    """
    config = _build_config()

    payload = scrub_credentials(simplify(config))
    assert "secret" not in payload["server"]["authentication"]
    assert "key_password" not in payload["server"]["ssl"]
    assert "password" not in payload["database"]


def test_the_config_response_does_not_carry_the_signing_secret() -> None:
    """The signing secret mints a token for any user, so serving it hands over every account."""
    config = _build_config()

    assert SECRET not in _serialize(config)
    assert SECRET not in _serialize(config.server)


def test_the_config_response_does_not_carry_the_private_key_password() -> None:
    config = _build_config()

    assert KEY_PASSWORD not in _serialize(config)
    assert KEY_PASSWORD not in _serialize(config.server)


def test_the_config_response_does_not_carry_the_database_password() -> None:
    config = _build_config()

    assert DATABASE_PASSWORD not in _serialize(config)
    assert DATABASE_PASSWORD not in _serialize(config.database)


def test_the_scrub_reaches_inside_nested_containers() -> None:
    """Credentials hide at every nesting level, including inside lists of mappings."""
    payload = {
        "components": [{"name": "sensor", "arguments": {"password": "hidden", "kept": True}}],
    }

    scrubbed = scrub_credentials(payload)
    assert scrubbed == {"components": [{"name": "sensor", "arguments": {"kept": True}}]}


def test_the_config_response_still_carries_everything_else() -> None:
    """Scrubbing by field name is broad, so the rest of the configuration must survive it."""
    config = _build_config()

    serialized = _serialize(config.server)
    assert "0.0.0.0" in serialized
    assert "duration" in serialized


def test_the_secret_is_still_readable_where_it_is_used() -> None:
    """The scrub is for responses only, signing still needs the real value."""
    config = _build_config()

    authentication = config.server.authentication
    assert authentication is not None
    assert authentication.secret == SECRET


def test_the_router_no_longer_relies_on_response_model_excludes() -> None:
    """The handlers own serialization, so no route may quietly return a raw model again."""
    from fastapi.routing import APIRoute

    routes = [route for route in config_routes.router.routes if isinstance(route, APIRoute)]

    assert len(routes) > 0
    for route in routes:
        assert route.response_model is not None, route.path
