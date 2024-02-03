from typing import Sequence

from fastapi import APIRouter, Response
from starlette.status import HTTP_400_BAD_REQUEST

from ceres.address import Address
from ceres.config import Config
from ceres.data import ImmutableDataObject
from ceres.errors import ReloadError
from ceres.filter import ComponentFilter
from ceres.internal.app.api.routes.alerts import router as router__alerts
from ceres.internal.app.api.routes.auth import router as router__auth
from ceres.internal.app.api.routes.components import router as router__components
from ceres.internal.app.api.routes.config import router as router__config
from ceres.internal.app.api.routes.log_entries import router as router__log_entries
from ceres.internal.app.api.routes.messages import router as router__messages
from ceres.internal.app.api.routes.statistics import router as router__statistics
from ceres.internal.app.api.routes.statuses import router as router__statuses
from ceres.internal.app.api.routes.users import router as router__users
from ceres.internal.app.shared import OPERATOR, CurrentEngine
from ceres.result import Fail, Ok, Result

router = APIRouter(prefix="/api")

router.include_router(router__alerts)
router.include_router(router__auth)
router.include_router(router__components)
router.include_router(router__config)
router.include_router(router__log_entries)
router.include_router(router__messages)
router.include_router(router__statistics)
router.include_router(router__statuses)
router.include_router(router__users)


@router.post("/reload", tags=["engine"], dependencies=[OPERATOR])
async def reload(
    engine: CurrentEngine,
    response: Response,
) -> Result[Config, ReloadError]:
    match await engine.reload():
        case Ok(config):
            return Ok(config)
        case Fail(error):
            response.status_code = HTTP_400_BAD_REQUEST
            return Fail(error)


class StartResult(ImmutableDataObject):
    started: Sequence[Address]


@router.post("/start", tags=["components"], dependencies=[OPERATOR])
async def start(engine: CurrentEngine, filter: ComponentFilter) -> StartResult:
    stopped = engine.get_components(filter, running=False)
    stopped.start()
    return StartResult(started=[component.address for component in stopped])


class StopResult(ImmutableDataObject):
    stopped: Sequence[Address]


@router.post("/stop", tags=["components"], dependencies=[OPERATOR])
async def stop(engine: CurrentEngine, filter: ComponentFilter) -> StopResult:
    running = engine.get_components(filter, running=True)
    await running.stop()
    return StopResult(stopped=[component.address for component in running])


class EnableResult(ImmutableDataObject):
    enabled: Sequence[Address]


@router.post("/enable", tags=["components"], dependencies=[OPERATOR])
async def enable(engine: CurrentEngine, filter: ComponentFilter) -> EnableResult:
    disabled = engine.get_components(filter, enabled=False)
    await disabled.enable()
    return EnableResult(enabled=[component.address for component in disabled])


class DisableResult(ImmutableDataObject):
    disabled: Sequence[Address]


@router.post("/disable", tags=["components"], dependencies=[OPERATOR])
async def disable(engine: CurrentEngine, filter: ComponentFilter) -> DisableResult:
    enabled = engine.get_components(filter, enabled=True)
    await enabled.disable()
    return DisableResult(disabled=[component.address for component in enabled])


class UpResult(ImmutableDataObject):
    enabled: Sequence[Address]
    started: Sequence[Address]


@router.post("/up", tags=["components"], dependencies=[OPERATOR])
async def up(engine: CurrentEngine, filter: ComponentFilter) -> UpResult:
    disabled = engine.get_components(filter, enabled=False)
    await disabled.enable()

    stopped = engine.get_components(filter, running=False)
    stopped.start()

    return UpResult(
        enabled=[component.address for component in disabled],
        started=[component.address for component in stopped],
    )


class DownResult(ImmutableDataObject):
    disabled: Sequence[Address]
    stopped: Sequence[Address]


@router.post("/down", tags=["components"], dependencies=[OPERATOR])
async def down(engine: CurrentEngine, filter: ComponentFilter) -> DownResult:
    enabled = engine.get_components(filter, enabled=True)
    await enabled.disable()

    running = engine.get_components(filter, running=True)
    await running.stop()

    return DownResult(
        disabled=[component.address for component in enabled],
        stopped=[component.address for component in running],
    )
