from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter
from starlette.status import HTTP_201_CREATED

from ceres._internal.app.shared import (
    ADMIN,
    VIEWER,
    APIUser,
    CurrentEngine,
    CurrentRole,
    CurrentUser,
    QueryGroup,
)
from ceres.error import Failure, NotFoundError, NotPermittedError
from ceres.user import User, UserCreate, UserFilter, UserRole, UserUpdate

router = APIRouter(prefix="/users", tags=["users"])


@router.get("/{id}", dependencies=[VIEWER], response_model=APIUser)
async def get_user(engine: CurrentEngine, id: UUID) -> User:
    user = await engine.users.get(id=id)
    if user is None:
        raise Failure(NotFoundError)

    return user


class GetUsersQueryParameters(UserFilter):
    pass


@router.get("", dependencies=[VIEWER], response_model=list[APIUser])
async def get_users(
    engine: CurrentEngine,
    filter: QueryGroup[GetUsersQueryParameters],
) -> list[User]:
    return await engine.users.get_all(filter)


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

    updated = await engine.users.update(UserFilter(id=id), assign)
    if updated is None:
        raise Failure(NotFoundError)

    return updated


@router.delete("/{id}", dependencies=[ADMIN], response_model=APIUser)
async def delete_user(engine: CurrentEngine, id: UUID) -> User:
    deleted = await engine.users.delete(id=id)
    if deleted is None:
        raise Failure(NotFoundError)

    return deleted
