import asyncio

from ceres import Engine
from ceres.config import ComponentConfig, Config, ServerConfig


async def test_engine_can_start() -> None:
    engine = Engine()
    await engine.load(
        Config(
            server=ServerConfig(port=9000),
            components=[ComponentConfig(name="test")],
        )
    )

    engine.start()
    await asyncio.sleep(1)
    await engine.stop(True)
