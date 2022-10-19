from __future__ import annotations

from anyio import sleep

from ceres.config import Config, DatabaseConfig, DatabaseKind, ServerConfig, UnitConfig
from ceres.engine import Engine


async def test_engine_can_start() -> None:
    engine = Engine(
        Config(
            server=ServerConfig(port=9000),
            database=DatabaseConfig(
                kind=DatabaseKind.SQLITE,
                path="/Users/jploskey/Desktop/test.sqlite",
            ),
            units=[UnitConfig(name="test")],
        )
    )

    engine.start()
    await sleep(3)
    await engine.stop(True)
