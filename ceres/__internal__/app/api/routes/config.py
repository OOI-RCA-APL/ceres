from starlette.responses import JSONResponse

from ceres.__internal__.app.shared import ADMIN, CurrentEngine, Router, scrub_credentials
from ceres.config import Config, ConsoleConfig, DatabaseConfig, ServerConfig, ServiceConfig
from ceres.data import simplify

# Every route here serves part of the engine's configuration, which holds the credentials the
# engine was started with. Being an administrator is permission to read the configuration, not
# permission to walk away with the signing secret. Handlers serialize the configuration
# themselves and scrub credentials from the final payload, which reaches inside the
# natively-serialized sections that Pydantic's exclude machinery cannot descend into.
router = Router(prefix="/config", tags=["config"])


def _respond(section: object) -> JSONResponse:
    """Serialize a configuration object and return it with credentials scrubbed."""
    return JSONResponse(scrub_credentials(simplify(section)))


@router.get("", dependencies=[ADMIN], response_model=Config)
async def get_config(engine: CurrentEngine) -> JSONResponse:
    """Return the full engine configuration."""
    return _respond(engine.config)


@router.get("/service", dependencies=[ADMIN], response_model=ServiceConfig)
async def get_service_config(engine: CurrentEngine) -> JSONResponse:
    """Return the service configuration section."""
    return _respond(engine.config.service)


@router.get("/server", dependencies=[ADMIN], response_model=ServerConfig)
async def get_server_config(engine: CurrentEngine) -> JSONResponse:
    """Return the server configuration section."""
    return _respond(engine.config.server)


@router.get("/console", response_model=ConsoleConfig)
async def get_console_config(engine: CurrentEngine) -> JSONResponse:
    """Return the console configuration section."""
    return _respond(engine.config.console)


@router.get("/database", dependencies=[ADMIN], response_model=DatabaseConfig)
async def get_database_config(engine: CurrentEngine) -> JSONResponse:
    """Return the database configuration section."""
    return _respond(engine.config.database)
