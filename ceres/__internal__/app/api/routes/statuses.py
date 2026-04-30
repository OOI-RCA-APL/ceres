from typing import Annotated

from fastapi import Query

from ceres.__internal__.app.shared import CurrentEngine, CurrentSocket, Router
from ceres.address import Address
from ceres.component import ComponentFilter
from ceres.error import NotFoundError
from ceres.status import Status

router = Router(prefix="/statuses", tags=["statuses"])


@router.get("/{address}?")
async def get_status(engine: CurrentEngine, address: Address | None = None) -> Status:
    """Return the status of a single component identified by its address.

    Raises:
        NotFoundError: If no component matches the given address.
    """
    component = engine.get_node(address)
    if component is None:
        raise NotFoundError()

    return await component.get_status()


@router.get("")
async def get_statuses(
    engine: CurrentEngine,
    filter: Annotated[ComponentFilter, Query()],
) -> list[Status]:
    """Return the statuses of all components matching the given filter."""
    return await engine.get_statuses(filter)


@router.websocket("")
async def stream_statuses(
    socket: CurrentSocket,
    engine: CurrentEngine,
    filter: Annotated[ComponentFilter, Query()],
) -> None:
    """Stream component statuses over a WebSocket, pushing updates as they occur."""

    async def write() -> None:
        async for statuses in engine.stream_statuses(filter):
            await socket.send(statuses)

    await socket.execute(write)
