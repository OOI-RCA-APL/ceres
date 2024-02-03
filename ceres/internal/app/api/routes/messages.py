from typing import Annotated

from fastapi import APIRouter, Depends
from pydantic import Field

from ceres.filter import MessageFilter
from ceres.internal.app.shared import CurrentEngine, CurrentSocket
from ceres.message import Message

router = APIRouter(prefix="/messages", tags=["messages"])


class GetMessagesQueryParameters(MessageFilter):
    limit: int = Field(default=100, ge=0, le=1000)
    offset: int = Field(default=0, ge=0)


@router.get("")
async def get_messages(
    engine: CurrentEngine,
    filter: Annotated[GetMessagesQueryParameters, Depends()],
) -> list[Message]:
    return await engine.get_messages(filter)


class StreamMessagesQueryParameters(GetMessagesQueryParameters):
    pass


@router.websocket("")
async def stream_messages(
    socket: CurrentSocket,
    engine: CurrentEngine,
    filter: Annotated[StreamMessagesQueryParameters, Depends()],
) -> None:
    async for message in engine.stream_messages(filter):
        await socket.send(message)
