import asyncio
from pathlib import Path
from tempfile import NamedTemporaryFile

from ceres.config import (
    Config,
    DatabaseKind,
    ServerConfig,
    SQLiteDatabaseConfig,
    UnitConfig,
)
from ceres.engine import Engine
from ceres.internal.utilities import frozenlist


async def test_engine_can_start() -> None:
    with NamedTemporaryFile(suffix=".sqlite") as file:
        engine = Engine(
            Config(
                server=ServerConfig(port=9000),
                database=SQLiteDatabaseConfig(
                    kind=DatabaseKind.SQLITE,
                    path=Path(file.name),
                ),
                units=frozenlist([UnitConfig(name="test")]),
            )
        )

        engine.start()
        await asyncio.sleep(2)
        await engine.stop(True)
