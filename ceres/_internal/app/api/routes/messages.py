from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Query
from pydantic import Field
from pydantic import ValidationError as ValidationError
from starlette.exceptions import HTTPException as HTTPException

from ceres._internal.app.shared import CurrentEngine, CurrentSocket
from ceres.message import Message, MessageFilter

router = APIRouter(prefix="/messages", tags=["messages"])


class GetMessagesQueryParameters(MessageFilter):
    limit: int = Field(default=100, ge=0, le=1000)
    offset: int = Field(default=0, ge=0)


@router.get("")
async def get_messages(
    engine: CurrentEngine,
    filter: Annotated[GetMessagesQueryParameters, Query()],
) -> list[Message]:
    return await engine.messages.get_all(filter)


class FollowMessagesQueryParameters(GetMessagesQueryParameters):
    pass


@router.websocket("")
async def follow_messages(
    socket: CurrentSocket,
    engine: CurrentEngine,
    filter: Annotated[FollowMessagesQueryParameters, Query()],
) -> None:
    async for message in engine.messages.follow(filter):
        await socket.send(message)
