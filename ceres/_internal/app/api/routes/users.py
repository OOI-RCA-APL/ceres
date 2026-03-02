from typing import Annotated
from uuid import UUID

from fastapi import Query
from starlette.status import HTTP_201_CREATED

from ceres._internal.app.shared import (
    ADMIN,
    EXCLUDE_PASSWORDS,
    SELF_OR_ADMIN,
    VIEWER,
    CurrentEngine,
    CurrentRole,
    Limit,
    Router,
    assert_found,
)
from ceres.error import Failure, NotFoundError, NotPermittedError
from ceres.user import User, UserCreate, UserFilter, UserRole, UserUpdate

router = Router(
    prefix="/users",
    tags=["users"],
    default_response_model_exclude=EXCLUDE_PASSWORDS,
)


@router.get("/{id:uuid}", dependencies=[VIEWER])
async def get_user(engine: CurrentEngine, id: UUID) -> User:
    return assert_found(await engine.users.get(id))


@router.get("", dependencies=[VIEWER])
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


@router.post("", dependencies=[ADMIN], status_code=HTTP_201_CREATED)
async def create_user(engine: CurrentEngine, data: UserCreate) -> User:
    return await engine.users.create(data)


@router.patch("/{id:uuid}", dependencies=[SELF_OR_ADMIN])
async def update_user(
    engine: CurrentEngine,
    role: CurrentRole,
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


@router.delete("/{id:uuid}", dependencies=[ADMIN])
async def delete_user(engine: CurrentEngine, id: UUID) -> User:
    return assert_found(await engine.users.where(id=id).delete().first())
