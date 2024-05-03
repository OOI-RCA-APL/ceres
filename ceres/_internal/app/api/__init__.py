from asyncio import gather
from typing import Any, Sequence

from fastapi import APIRouter
from starlette.responses import RedirectResponse

from ceres._internal.app.api.routes.alerts import router as router__alerts
from ceres._internal.app.api.routes.auth import router as router__auth
from ceres._internal.app.api.routes.components import router as router__systems
from ceres._internal.app.api.routes.config import router as router__config
from ceres._internal.app.api.routes.log_entries import router as router__log_entries
from ceres._internal.app.api.routes.messages import router as router__messages
from ceres._internal.app.api.routes.statistics import router as router__statistics
from ceres._internal.app.api.routes.statuses import router as router__statuses
from ceres._internal.app.api.routes.users import router as router__users
from ceres._internal.app.shared import OPERATOR, CurrentEngine
from ceres._internal.utilities import OrderedSet
from ceres.address import Address
from ceres.component import ComponentFilter
from ceres.config import Config
from ceres.data import ImmutableDataObject
from ceres.errors import Failure, NotFoundError, ReloadError

router = APIRouter(prefix="/api")

router.include_router(router__alerts)
router.include_router(router__auth)
router.include_router(router__systems)
router.include_router(router__config)
router.include_router(router__log_entries)
router.include_router(router__messages)
router.include_router(router__statistics)
router.include_router(router__statuses)
router.include_router(router__users)


@router.get("")
async def get_api() -> RedirectResponse:
    return RedirectResponse(url="/api/openapi.json")


@router.post(
    "/reload",
    tags=["engine"],
    dependencies=[OPERATOR],
    response_model=Config | ReloadError,
)
async def reload(engine: CurrentEngine) -> Config:
    return await engine.reload()


class StartResult(ImmutableDataObject):
    started: Sequence[Address]


@router.post("/start", tags=["systems"], dependencies=[OPERATOR])
async def start(engine: CurrentEngine, filter: ComponentFilter) -> StartResult:
    stopped = engine.get_components(filter, running=False)
    for component in stopped:
        component.system.start()
    return StartResult(started=[current.system.address for current in stopped])


class StopResult(ImmutableDataObject):
    stopped: Sequence[Address]


@router.post("/stop", tags=["systems"], dependencies=[OPERATOR])
async def stop(engine: CurrentEngine, filter: ComponentFilter) -> StopResult:
    running = engine.get_components(filter, running=True)
    await gather(*(component.system.stop() for component in running))

    return StopResult(stopped=[current.system.address for current in running])


class EnableResult(ImmutableDataObject):
    enabled: Sequence[Address]


@router.post("/enable", tags=["systems"], dependencies=[OPERATOR])
async def enable(engine: CurrentEngine, filter: ComponentFilter) -> EnableResult:
    disabled = engine.get_components(filter, enabled=False)
    await gather(*(component.system.enable() for component in disabled))

    return EnableResult(enabled=[current.system.address for current in disabled])


class DisableResult(ImmutableDataObject):
    disabled: Sequence[Address]


@router.post("/disable", tags=["systems"], dependencies=[OPERATOR])
async def disable(engine: CurrentEngine, filter: ComponentFilter) -> DisableResult:
    enabled = engine.get_components(filter, enabled=True)
    await gather(*(system.system.disable() for system in enabled))

    return DisableResult(disabled=[current.system.address for current in enabled])


class UpResult(ImmutableDataObject):
    enabled: Sequence[Address]
    started: Sequence[Address]


@router.post("/up", tags=["systems"], dependencies=[OPERATOR])
async def up(engine: CurrentEngine, filter: ComponentFilter) -> UpResult:
    disabled = engine.get_components(filter, enabled=False)
    stopped = engine.get_components(filter, running=False)

    await gather(*(system.system.up() for system in OrderedSet([*disabled, *stopped])))

    return UpResult(
        enabled=[current.system.address for current in disabled],
        started=[current.system.address for current in stopped],
    )


class DownResult(ImmutableDataObject):
    disabled: Sequence[Address]
    stopped: Sequence[Address]


@router.post("/down", tags=["systems"], dependencies=[OPERATOR])
async def down(engine: CurrentEngine, filter: ComponentFilter) -> DownResult:
    enabled = engine.get_components(filter, enabled=True)
    running = engine.get_components(filter, running=True)

    return DownResult(
        disabled=[current.system.address for current in enabled],
        stopped=[current.system.address for current in running],
    )


@router.get("/{path:path}", include_in_schema=False)
async def get_404() -> Any:
    raise Failure(NotFoundError)
