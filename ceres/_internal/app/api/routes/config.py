from ceres._internal.app.shared import OPERATOR, CurrentEngine, Router
from ceres.config import Config, ConsoleConfig, DatabaseConfig, ServerConfig, ServiceConfig

router = Router(prefix="/config", tags=["config"])


@router.get("", dependencies=[OPERATOR])
async def get_config(engine: CurrentEngine) -> Config:
    return engine.config


@router.get("/service", dependencies=[OPERATOR])
async def get_service_config(engine: CurrentEngine) -> ServiceConfig:
    return engine.config.service


@router.get("/server", dependencies=[OPERATOR])
async def get_server_config(engine: CurrentEngine) -> ServerConfig:
    return engine.config.server


@router.get("/console")
async def get_console_config(engine: CurrentEngine) -> ConsoleConfig:
    return engine.config.console


@router.get("/database", dependencies=[OPERATOR])
async def get_database_config(engine: CurrentEngine) -> DatabaseConfig:
    return engine.config.database
