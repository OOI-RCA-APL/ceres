from typing import Any

from fastapi import Response
from starlette.responses import RedirectResponse

from ceres.__internal__.app.api.routes.alerts import router as _router__alerts
from ceres.__internal__.app.api.routes.auth import router as _router__auth
from ceres.__internal__.app.api.routes.components import router as _router__components
from ceres.__internal__.app.api.routes.config import router as _router__config
from ceres.__internal__.app.api.routes.groups import router as _router__groups
from ceres.__internal__.app.api.routes.logs import router as _router__logs
from ceres.__internal__.app.api.routes.messages import router as _router__messages
from ceres.__internal__.app.api.routes.particles import router as _router__particles
from ceres.__internal__.app.api.routes.permissions import router as _router__permissions
from ceres.__internal__.app.api.routes.settings import router as _router__settings
from ceres.__internal__.app.api.routes.statistics import router as _router__statistics
from ceres.__internal__.app.api.routes.statuses import router as _router__statuses
from ceres.__internal__.app.api.routes.users import router as _router__users
from ceres.__internal__.app.api.routes.workspace_edits import router as _router__workspace_edits
from ceres.__internal__.app.api.routes.workspace_memberships import (
    router as _router__workspace_memberships,
)
from ceres.__internal__.app.api.routes.workspaces import router as _router__workspaces
from ceres.__internal__.app.shared import OPERATOR, CurrentEngine, Router
from ceres.__internal__.utilities.collections import uniq
from ceres.address import Address
from ceres.component import ComponentFilter
from ceres.concurrency import concurrently
from ceres.config import Config
from ceres.data import DataObject
from ceres.error import NotFoundError

router = Router(prefix="/api")

router.include_router(_router__alerts)
router.include_router(_router__auth)
router.include_router(_router__components)
router.include_router(_router__config)
router.include_router(_router__groups)
router.include_router(_router__logs)
router.include_router(_router__messages)
router.include_router(_router__particles)
router.include_router(_router__permissions)
router.include_router(_router__settings)
router.include_router(_router__statistics)
router.include_router(_router__statuses)
router.include_router(_router__users)
router.include_router(_router__workspace_edits)
router.include_router(_router__workspace_memberships)
router.include_router(_router__workspaces)


@router.get("/alive")
def get_alive() -> Response:
    return Response(status_code=200)


@router.get("")
async def get_api() -> RedirectResponse:
    return RedirectResponse(url="/api/openapi.json")


@router.post("/reload", tags=["engine"], dependencies=[OPERATOR])
async def reload(engine: CurrentEngine) -> Config:
    return await engine.reload()


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
    await concurrently(component.system.stop() for component in running)

    return StopResult(stopped=sorted(current.system.address for current in running))


class EnableResult(DataObject):
    enabled: list[Address]


@router.post("/enable", tags=["components"], dependencies=[OPERATOR])
async def enable(engine: CurrentEngine, filter: ComponentFilter) -> EnableResult:
    disabled = engine.get_components(filter, enabled=False)
    await concurrently(component.system.enable() for component in disabled)

    return EnableResult(enabled=sorted(current.system.address for current in disabled))


class DisableResult(DataObject):
    disabled: list[Address]


@router.post("/disable", tags=["components"], dependencies=[OPERATOR])
async def disable(engine: CurrentEngine, filter: ComponentFilter) -> DisableResult:
    enabled = engine.get_components(filter, enabled=True)
    await concurrently(system.system.disable() for system in enabled)

    return DisableResult(disabled=sorted(current.system.address for current in enabled))


class UpResult(DataObject):
    enabled: list[Address]
    started: list[Address]


@router.post("/up", tags=["components"], dependencies=[OPERATOR])
async def up(engine: CurrentEngine, filter: ComponentFilter) -> UpResult:
    disabled = engine.get_components(filter, enabled=False)
    stopped = engine.get_components(filter, running=False)
    await concurrently(system.system.up() for system in uniq([*disabled, *stopped], key=id))

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
    await concurrently(system.system.down() for system in uniq([*enabled, *running], key=id))

    return DownResult(
        disabled=sorted(current.system.address for current in enabled),
        stopped=sorted(current.system.address for current in running),
    )


@router.get("/{path:path}", include_in_schema=False)
async def get_404() -> Any:
    raise NotFoundError()
