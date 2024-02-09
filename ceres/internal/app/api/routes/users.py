from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from starlette.status import HTTP_401_UNAUTHORIZED, HTTP_404_NOT_FOUND, HTTP_409_CONFLICT

from ceres.data import EmailStr, ImmutableDataObject, UsernameStr
from ceres.errors import AlreadyExistsError
from ceres.exceptions import Failure
from ceres.filter import UserFilter
from ceres.internal.app.shared import ADMIN, VIEWER, CurrentEngine, CurrentRole, CurrentUser
from ceres.user import User, UserRole, UserUpdate

router = APIRouter(prefix="/users", tags=["users"])


class UserInfo(ImmutableDataObject):
    id: UUID
    username: UsernameStr
    email: EmailStr
    role: UserRole
    disabled: bool


UserInfo.__name__ = "User"


@router.get("/{id}", dependencies=[VIEWER], response_model=UserInfo)
async def get_user(engine: CurrentEngine, id: UUID) -> User:
    user = await engine.get_user(id=id)
    if user is None:
        raise HTTPException(HTTP_404_NOT_FOUND)

    return user


class GetUsersQueryParameters(UserFilter):
    pass


@router.get("", dependencies=[VIEWER], response_model=list[UserInfo])
async def get_users(
    engine: CurrentEngine,
    filter: Annotated[GetUsersQueryParameters, Depends()],
) -> list[User]:
    return await engine.get_users(filter)


@router.post("", dependencies=[ADMIN], response_model=UserInfo)
async def create_user(engine: CurrentEngine, data: User) -> User:
    try:
        user = await engine.create_user(data)
    except Failure as failure:
        match failure.error:
            case AlreadyExistsError():
                raise HTTPException(HTTP_409_CONFLICT)
            case _:
                raise

    return user


@router.patch("/{id}", dependencies=[VIEWER], response_model=UserInfo)
async def update_user(
    engine: CurrentEngine,
    role: CurrentRole,
    user: CurrentUser,
    id: UUID,
    assign: UserUpdate,
) -> User:
    if role is None or role < UserRole.ADMIN:
        if user is None or id != user.id:
            raise HTTPException(HTTP_401_UNAUTHORIZED)

    updated = await engine.update_user(UserFilter(id=id), assign)
    if updated is None:
        raise HTTPException(HTTP_404_NOT_FOUND)

    return updated


@router.delete("/{id}", dependencies=[ADMIN], response_model=UserInfo)
async def delete_user(engine: CurrentEngine, id: UUID) -> User:
    deleted = await engine.delete_user(id=id)
    if deleted is None:
        raise HTTPException(HTTP_404_NOT_FOUND)

    return deleted
