from __future__ import annotations

from pathlib import Path
from tempfile import NamedTemporaryFile

from anyio import sleep

from ceres.config import (
    Config,
    DatabaseKind,
    ServerConfig,
    SQLiteDatabaseConfig,
    UnitConfig,
)
from ceres.engine import Engine


async def test_engine_can_start() -> None:
    with NamedTemporaryFile(suffix=".sqlite") as file:
        engine = Engine(
            Config(
                server=ServerConfig(port=9000),
                database=SQLiteDatabaseConfig(
                    kind=DatabaseKind.SQLITE,
                    path=Path(file.name),
                ),
                units=[UnitConfig(name="test")],
            )
        )

        engine.start()
        await sleep(3)
        await engine.stop(True)
