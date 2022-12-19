import asyncio

from ceres.config import Config, ServerConfig, UnitConfig
from ceres.engine import Engine


async def test_engine_can_start() -> None:
    engine = Engine(
        Config(
            server=ServerConfig(port=9000),
            units=[UnitConfig(name="test")],
        )
    )

    engine.start()
    await asyncio.sleep(1)
    await engine.stop(True)
