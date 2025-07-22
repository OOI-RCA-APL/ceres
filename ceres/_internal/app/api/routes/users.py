from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Query
from starlette.status import HTTP_201_CREATED

from ceres._internal.app.shared import (
    ADMIN,
    SELF_OR_ADMIN,
    VIEWER,
    APIUser,
    CurrentEngine,
    CurrentRole,
    CurrentUser,
    Limit,
    assert_found,
)
from ceres.error import Failure, NotFoundError, NotPermittedError
from ceres.user import User, UserCreate, UserFilter, UserRole, UserUpdate

router = APIRouter(prefix="/users", tags=["users"])


@router.get("/{id:uuid}", dependencies=[VIEWER], response_model=APIUser)
async def get_user(engine: CurrentEngine, id: UUID) -> User:
    return assert_found(await engine.users.get(id))


@router.get("", dependencies=[VIEWER], response_model=list[APIUser])
async def get_users(
    engine: CurrentEngine,
    filter: Annotated[UserFilter, Query(), Limit(1000)],
) -> list[User]:
    return await engine.users.where(filter)


@router.get("/count", dependencies=[VIEWER])
async def count_users(
    engine: CurrentEngine,
    filter: Annotated[UserFilter, Query()],
) -> int:
    return await engine.users.where(filter).count()


@router.post("", dependencies=[ADMIN], response_model=APIUser, status_code=HTTP_201_CREATED)
async def create_user(engine: CurrentEngine, data: UserCreate) -> User:
    return await engine.users.create(data)


@router.patch("/{id:uuid}", dependencies=[SELF_OR_ADMIN], response_model=APIUser)
async def update_user(
    engine: CurrentEngine,
    role: CurrentRole,
    user: CurrentUser,
    id: UUID,
    assign: UserUpdate,
) -> User:
    if role < UserRole.ADMIN:
        if "role" in assign or "disabled" in assign:
            raise Failure(NotPermittedError)

    updated = await engine.users.where(id=id).update(assign).first()
    if updated is None:
        raise Failure(NotFoundError)

    return updated


@router.delete("/{id:uuid}", dependencies=[ADMIN], response_model=APIUser)
async def delete_user(engine: CurrentEngine, id: UUID) -> User:
    return assert_found(await engine.users.where(id=id).delete().first())
