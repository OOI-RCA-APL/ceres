from ceres.__internal__.app.shared import ADMIN, EXCLUDE_CREDENTIALS, CurrentEngine, Router
from ceres.config import Config, ConsoleConfig, DatabaseConfig, ServerConfig, ServiceConfig

# Every route here serves part of the engine's configuration, which holds the credentials the
# engine was started with. Being an administrator is permission to read the configuration, not
# permission to walk away with the signing secret.
router = Router(
    prefix="/config",
    tags=["config"],
    default_response_model_exclude=EXCLUDE_CREDENTIALS,
)


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
