from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Query

from ceres._internal.app.shared import CurrentEngine, CurrentSocket
from ceres.address import Address
from ceres.component import ComponentFilter
from ceres.error import Failure, NotFoundError
from ceres.status import Status

router = APIRouter(prefix="/statuses", tags=["statuses"])


@router.get("/{address}?")
async def get_status(engine: CurrentEngine, address: Address | None = None) -> Status:
    component = engine.get_node(address)
    if component is None:
        raise Failure(NotFoundError)

    return await component.get_status()


@router.get("")
async def get_statuses(
    engine: CurrentEngine,
    filter: Annotated[ComponentFilter, Query()],
) -> list[Status]:
    return await engine.get_statuses(filter)


@router.websocket("")
async def follow_statuses(
    socket: CurrentSocket,
    engine: CurrentEngine,
    filter: Annotated[ComponentFilter, Query()],
) -> None:
    async def write() -> None:
        async for statuses in engine.follow_statuses(filter):
            await socket.send(statuses)

    await socket.execute(write)
