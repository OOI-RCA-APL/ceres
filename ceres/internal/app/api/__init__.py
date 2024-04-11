from typing import Any, Sequence

from fastapi import APIRouter
from starlette.responses import RedirectResponse

from ceres.address import Address
from ceres.config import Config
from ceres.data import ImmutableDataObject
from ceres.errors import Failure, NotFoundError, ReloadError
from ceres.filter import SystemFilter
from ceres.internal.app.api.routes.alerts import router as router__alerts
from ceres.internal.app.api.routes.auth import router as router__auth
from ceres.internal.app.api.routes.config import router as router__config
from ceres.internal.app.api.routes.log_entries import router as router__log_entries
from ceres.internal.app.api.routes.messages import router as router__messages
from ceres.internal.app.api.routes.statistics import router as router__statistics
from ceres.internal.app.api.routes.statuses import router as router__statuses
from ceres.internal.app.api.routes.systems import router as router__systems
from ceres.internal.app.api.routes.users import router as router__users
from ceres.internal.app.shared import OPERATOR, CurrentEngine

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
async def start(engine: CurrentEngine, filter: SystemFilter) -> StartResult:
    stopped = engine.get_systems(filter, running=False)
    stopped.start()
    return StartResult(started=[current.address for current in stopped])


class StopResult(ImmutableDataObject):
    stopped: Sequence[Address]


@router.post("/stop", tags=["systems"], dependencies=[OPERATOR])
async def stop(engine: CurrentEngine, filter: SystemFilter) -> StopResult:
    running = engine.get_systems(filter, running=True)
    await running.stop()
    return StopResult(stopped=[current.address for current in running])


class EnableResult(ImmutableDataObject):
    enabled: Sequence[Address]


@router.post("/enable", tags=["systems"], dependencies=[OPERATOR])
async def enable(engine: CurrentEngine, filter: SystemFilter) -> EnableResult:
    disabled = engine.get_systems(filter, enabled=False)
    await disabled.enable()
    return EnableResult(enabled=[current.address for current in disabled])


class DisableResult(ImmutableDataObject):
    disabled: Sequence[Address]


@router.post("/disable", tags=["systems"], dependencies=[OPERATOR])
async def disable(engine: CurrentEngine, filter: SystemFilter) -> DisableResult:
    enabled = engine.get_systems(filter, enabled=True)
    await enabled.disable()
    return DisableResult(disabled=[current.address for current in enabled])


class UpResult(ImmutableDataObject):
    enabled: Sequence[Address]
    started: Sequence[Address]


@router.post("/up", tags=["systems"], dependencies=[OPERATOR])
async def up(engine: CurrentEngine, filter: SystemFilter) -> UpResult:
    disabled = engine.get_systems(filter, enabled=False)
    await disabled.enable()

    stopped = engine.get_systems(filter, running=False)
    stopped.start()

    return UpResult(
        enabled=[current.address for current in disabled],
        started=[current.address for current in stopped],
    )


class DownResult(ImmutableDataObject):
    disabled: Sequence[Address]
    stopped: Sequence[Address]


@router.post("/down", tags=["systems"], dependencies=[OPERATOR])
async def down(engine: CurrentEngine, filter: SystemFilter) -> DownResult:
    enabled = engine.get_systems(filter, enabled=True)
    await enabled.disable()

    running = engine.get_systems(filter, running=True)
    await running.stop()

    return DownResult(
        disabled=[current.address for current in enabled],
        stopped=[current.address for current in running],
    )


@router.get("/{path:path}", include_in_schema=False)
async def get_404() -> Any:
    raise Failure(NotFoundError)
