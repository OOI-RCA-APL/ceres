"""The engine host's move of the console listener, which a console dev server relies on."""

from ceres.__internal__.host import _move_console_listener
from ceres.config import ServerConfig, ServerHTTPConfig


def test_the_https_listener_moves_when_there_is_one() -> None:
    server = ServerConfig(https={"port": 8443}, http={"port": 8080, "redirect": True})

    moved = _move_console_listener(server, 9000)

    assert moved.https is not None
    assert moved.https.port == 9000
    assert moved.http == ServerHTTPConfig(port=8080, redirect=True)


def test_the_http_listener_moves_without_https() -> None:
    moved = _move_console_listener(ServerConfig(http={"port": 8080}), 9000)

    assert moved.https is None
    assert moved.http == ServerHTTPConfig(port=9000)


def test_a_section_without_listeners_gains_an_http_one() -> None:
    moved = _move_console_listener(ServerConfig(), 9000)

    assert moved.https is None
    assert moved.http == ServerHTTPConfig(port=9000)
