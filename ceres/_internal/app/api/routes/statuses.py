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


class GetStatusesQueryParameters(ComponentFilter):
    pass


@router.get("")
async def get_statuses(
    engine: CurrentEngine,
    filter: Annotated[GetStatusesQueryParameters, Query()],
) -> list[Status]:
    return await engine.get_statuses(filter)


class FollowStatusesQueryParameters(GetStatusesQueryParameters):
    pass


@router.websocket("")
async def follow_statuses(
    socket: CurrentSocket,
    engine: CurrentEngine,
    filter: Annotated[FollowStatusesQueryParameters, Query()],
) -> None:
    async for statuses in engine.stream_statuses(filter):
        await socket.send(statuses)
