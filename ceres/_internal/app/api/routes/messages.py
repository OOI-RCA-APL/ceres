from __future__ import annotations

from fastapi import APIRouter
from pydantic import Field
from pydantic import ValidationError as ValidationError
from starlette.exceptions import HTTPException as HTTPException

from ceres._internal.app.shared import CurrentEngine, CurrentSocket, QueryGroup
from ceres.message import Message, MessageFilter

router = APIRouter(prefix="/messages", tags=["messages"])


class GetMessagesQueryParameters(MessageFilter):
    limit: int = Field(default=100, ge=0, le=1000)
    offset: int = Field(default=0, ge=0)


@router.get("")
async def get_messages(
    engine: CurrentEngine,
    filter: QueryGroup[GetMessagesQueryParameters],
) -> list[Message]:
    return await engine.messages.get_all(filter)


class FollowMessagesQueryParameters(GetMessagesQueryParameters):
    pass


@router.websocket("")
async def follow_messages(
    socket: CurrentSocket,
    engine: CurrentEngine,
    filter: QueryGroup[FollowMessagesQueryParameters],
) -> None:
    async for message in engine.messages.follow(filter):
        await socket.send(message)
