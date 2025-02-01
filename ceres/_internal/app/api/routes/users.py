from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Query
from pydantic import Field
from starlette.status import HTTP_201_CREATED

from ceres._internal.app.shared import (
    ADMIN,
    VIEWER,
    APIUser,
    CurrentEngine,
    CurrentRole,
    CurrentUser,
)
from ceres.error import Failure, NotFoundError, NotPermittedError
from ceres.user import User, UserCreate, UserFilter, UserRole, UserUpdate

router = APIRouter(prefix="/users", tags=["users"])


@router.get("/{id}", dependencies=[VIEWER], response_model=APIUser)
async def get_user(engine: CurrentEngine, id: UUID) -> User:
    user = await engine.users.get(id)
    if user is None:
        raise Failure(NotFoundError)

    return user


class GetUsersQueryParameters(UserFilter):
    limit: int = Field(default=100, ge=0, le=1000)


@router.get("", dependencies=[VIEWER], response_model=list[APIUser])
async def get_users(
    engine: CurrentEngine,
    filter: Annotated[GetUsersQueryParameters, Query()],
) -> list[User]:
    return await engine.users.where(filter)


@router.post("", dependencies=[ADMIN], response_model=APIUser, status_code=HTTP_201_CREATED)
async def create_user(engine: CurrentEngine, data: UserCreate) -> User:
    return await engine.users.create(data)


@router.patch("/{id}", dependencies=[ADMIN], response_model=APIUser)
async def update_user(
    engine: CurrentEngine,
    role: CurrentRole,
    user: CurrentUser,
    id: UUID,
    assign: UserUpdate,
) -> User:
    if role < UserRole.ADMIN:
        if user is None or id != user.id:
            raise Failure(NotPermittedError)

    updated = await engine.users.where(id=id).update(assign).first()
    if updated is None:
        raise Failure(NotFoundError)

    return updated


@router.delete("/{id}", dependencies=[ADMIN], response_model=APIUser)
async def delete_user(engine: CurrentEngine, id: UUID) -> User:
    deleted = await engine.users.where(id=id).delete().first()
    if deleted is None:
        raise Failure(NotFoundError)

    return deleted
