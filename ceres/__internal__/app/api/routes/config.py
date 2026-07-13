from ceres.__internal__.app.shared import ADMIN, CurrentEngine, Router
from ceres.config import Config, ConsoleConfig, DatabaseConfig, ServerConfig, ServiceConfig

router = Router(prefix="/config", tags=["config"])


@router.get("", dependencies=[ADMIN])
async def get_config(engine: CurrentEngine) -> Config:
    """Return the full engine configuration."""
    return engine.config


@router.get("/service", dependencies=[ADMIN])
async def get_service_config(engine: CurrentEngine) -> ServiceConfig:
    """Return the service configuration section."""
    return engine.config.service


@router.get("/server", dependencies=[ADMIN])
async def get_server_config(engine: CurrentEngine) -> ServerConfig:
    """Return the server configuration section."""
    return engine.config.server


@router.get("/console")
async def get_console_config(engine: CurrentEngine) -> ConsoleConfig:
    """Return the console configuration section."""
    return engine.config.console


@router.get("/database", dependencies=[ADMIN])
async def get_database_config(engine: CurrentEngine) -> DatabaseConfig:
    """Return the database configuration section."""
    return engine.config.database
