from typing import Any

from fastapi import Response
from starlette.responses import RedirectResponse

from ceres._internal import util
from ceres._internal.app.api.routes.alerts import router as router__alerts
from ceres._internal.app.api.routes.auth import router as router__auth
from ceres._internal.app.api.routes.components import router as router__components
from ceres._internal.app.api.routes.config import router as router__config
from ceres._internal.app.api.routes.logs import router as router__logs
from ceres._internal.app.api.routes.messages import router as router__messages
from ceres._internal.app.api.routes.particles import router as router__particles
from ceres._internal.app.api.routes.settings import router as router__settings
from ceres._internal.app.api.routes.statistics import router as router__statistics
from ceres._internal.app.api.routes.statuses import router as router__statuses
from ceres._internal.app.api.routes.users import router as router__users
from ceres._internal.app.api.routes.workspace_edits import router as router__workspace_edits
from ceres._internal.app.api.routes.workspace_memberships import (
    router as router__workspace_memberships,
)
from ceres._internal.app.api.routes.workspaces import router as router__workspaces
from ceres._internal.app.shared import OPERATOR, CurrentEngine, Router
from ceres.address import Address
from ceres.component import ComponentFilter
from ceres.config import Config
from ceres.data import DataObject
from ceres.error import Failure, NotFoundError
from ceres.result import Fail, Ok

router = Router(prefix="/api")

router.include_router(router__alerts)
router.include_router(router__auth)
router.include_router(router__components)
router.include_router(router__config)
router.include_router(router__logs)
router.include_router(router__messages)
router.include_router(router__particles)
router.include_router(router__settings)
router.include_router(router__statistics)
router.include_router(router__statuses)
router.include_router(router__users)
router.include_router(router__workspace_edits)
router.include_router(router__workspace_memberships)
router.include_router(router__workspaces)


@router.get("/alive")
def get_alive() -> Response:
    return Response(status_code=200)


@router.get("")
async def get_api() -> RedirectResponse:
    return RedirectResponse(url="/api/openapi.json")


@router.post(
    "/reload",
    tags=["engine"],
    dependencies=[OPERATOR],
    response_model=Config,
)
async def reload(engine: CurrentEngine) -> Config:
    match await engine.reload():
        case Ok(config):
            return config
        case Fail(error):
            raise Failure(error)


class StartResult(DataObject):
    started: list[Address]


@router.post("/start", tags=["components"], dependencies=[OPERATOR])
async def start(engine: CurrentEngine, filter: ComponentFilter) -> StartResult:
    stopped = engine.get_components(filter, running=False)
    for component in stopped:
        component.system.start()
    return StartResult(started=sorted(current.system.address for current in stopped))


class StopResult(DataObject):
    stopped: list[Address]


@router.post("/stop", tags=["components"], dependencies=[OPERATOR])
async def stop(engine: CurrentEngine, filter: ComponentFilter) -> StopResult:
    running = engine.get_components(filter, running=True)
    await util.concurrently(component.system.stop() for component in running)

    return StopResult(stopped=sorted(current.system.address for current in running))


class EnableResult(DataObject):
    enabled: list[Address]


@router.post("/enable", tags=["components"], dependencies=[OPERATOR])
async def enable(engine: CurrentEngine, filter: ComponentFilter) -> EnableResult:
    disabled = engine.get_components(filter, enabled=False)
    await util.concurrently(component.system.enable() for component in disabled)

    return EnableResult(enabled=sorted(current.system.address for current in disabled))


class DisableResult(DataObject):
    disabled: list[Address]


@router.post("/disable", tags=["components"], dependencies=[OPERATOR])
async def disable(engine: CurrentEngine, filter: ComponentFilter) -> DisableResult:
    enabled = engine.get_components(filter, enabled=True)
    await util.concurrently(system.system.disable() for system in enabled)

    return DisableResult(disabled=sorted(current.system.address for current in enabled))


class UpResult(DataObject):
    enabled: list[Address]
    started: list[Address]


@router.post("/up", tags=["components"], dependencies=[OPERATOR])
async def up(engine: CurrentEngine, filter: ComponentFilter) -> UpResult:
    disabled = engine.get_components(filter, enabled=False)
    stopped = engine.get_components(filter, running=False)
    await util.concurrently(
        system.system.up() for system in util.uniquify([*disabled, *stopped], key=id)
    )

    return UpResult(
        enabled=sorted(current.system.address for current in disabled),
        started=sorted(current.system.address for current in stopped),
    )


class DownResult(DataObject):
    disabled: list[Address]
    stopped: list[Address]


@router.post("/down", tags=["components"], dependencies=[OPERATOR])
async def down(engine: CurrentEngine, filter: ComponentFilter) -> DownResult:
    enabled = engine.get_components(filter, enabled=True)
    running = engine.get_components(filter, running=True)
    await util.concurrently(
        system.system.down() for system in util.uniquify([*enabled, *running], key=id)
    )

    return DownResult(
        disabled=sorted(current.system.address for current in enabled),
        stopped=sorted(current.system.address for current in running),
    )


@router.get("/{path:path}", include_in_schema=False)
async def get_404() -> Any:
    raise Failure(NotFoundError)
