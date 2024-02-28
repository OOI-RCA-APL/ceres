from fastapi import APIRouter
from pydantic import Field
from pydantic import ValidationError as ValidationError
from starlette.exceptions import HTTPException as HTTPException

from ceres.filter import MessageFilter
from ceres.internal.app.shared import CurrentEngine, CurrentSocket, QueryGroup
from ceres.message import Message

router = APIRouter(prefix="/messages", tags=["messages"])


class GetMessagesQueryParameters(MessageFilter):
    limit: int = Field(default=100, ge=0, le=1000)
    offset: int = Field(default=0, ge=0)


@router.get("")
async def get_messages(
    engine: CurrentEngine,
    filter: QueryGroup[GetMessagesQueryParameters],
) -> list[Message]:
    return await engine.get_messages(filter)


class StreamMessagesQueryParameters(GetMessagesQueryParameters):
    pass


@router.websocket("")
async def stream_messages(
    socket: CurrentSocket,
    engine: CurrentEngine,
    filter: QueryGroup[StreamMessagesQueryParameters],
) -> None:
    async for message in engine.stream_messages(filter):
        await socket.send(message)
