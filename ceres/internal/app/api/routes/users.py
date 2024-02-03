from typing import Annotated, Sequence
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from starlette.status import (
    HTTP_400_BAD_REQUEST,
    HTTP_401_UNAUTHORIZED,
    HTTP_404_NOT_FOUND,
    HTTP_409_CONFLICT,
)

from ceres.data import PasswordHash
from ceres.filter import UserFilter
from ceres.internal.app.shared import ADMIN, VIEWER, CurrentEngine, CurrentRole, CurrentUser
from ceres.user import User, UserCreate, UserRole

router = APIRouter(prefix="/users", tags=["users"])


@router.get("/{id}", dependencies=[VIEWER])
async def get_user(engine: CurrentEngine, id: UUID) -> User:
    user = await engine.get_user(id=id)
    if user is None:
        raise HTTPException(HTTP_404_NOT_FOUND)

    return user


class GetUsersQueryParameters(UserFilter):
    pass


@router.get("", dependencies=[VIEWER])
async def get_users(
    engine: CurrentEngine,
    filter: Annotated[GetUsersQueryParameters, Depends()],
) -> Sequence[User]:
    return await engine.get_users(filter)


@router.post("", dependencies=[ADMIN])
async def create_user(engine: CurrentEngine, data: UserCreate) -> User:
    hash = (
        PasswordHash(data.password)
        if data.password_is_hashed
        else await engine.hash_password(data.password)
    )

    values = data.model_dump(exclude={"password_is_hashed"})
    values["password"] = hash

    try:
        user = await engine.create_user(User(**values))
    except Exception:
        if (
            await engine.get_user(id=data.id) is not None
            or await engine.get_user(username=data.username) is not None
        ):
            raise HTTPException(HTTP_409_CONFLICT)
        else:
            raise HTTPException(HTTP_400_BAD_REQUEST)

    return user


@router.put("/{id}", dependencies=[VIEWER])
async def update_user(
    engine: CurrentEngine,
    role: CurrentRole,
    user: CurrentUser,
    id: UUID,
    data: User,
) -> User:
    if role is None or role < UserRole.ADMIN:
        if user is None or id != user.id:
            raise HTTPException(HTTP_401_UNAUTHORIZED)

    updated = await engine.update_user(id, data)
    if updated is None:
        raise HTTPException(HTTP_404_NOT_FOUND)

    return updated


@router.delete("/{id}", dependencies=[ADMIN])
async def delete_user(engine: CurrentEngine, id: UUID) -> User:
    deleted = await engine.delete_user(id)
    if deleted is None:
        raise HTTPException(HTTP_404_NOT_FOUND)

    return deleted
