import asyncio

from ceres import Engine
from ceres.config import Config, ServerConfig, UnitConfig


async def test_engine_can_start() -> None:
    engine = Engine(
        config=Config(
            server=ServerConfig(port=9000),
            units=[UnitConfig(name="test")],
        )
    )

    engine.start()
    await asyncio.sleep(1)
    await engine.stop(True)
