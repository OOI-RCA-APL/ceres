import asyncio

from fastapi import APIRouter, HTTPException, Response
from starlette.status import HTTP_400_BAD_REQUEST, HTTP_401_UNAUTHORIZED, HTTP_403_FORBIDDEN

from ceres.data import DateTime, ImmutableDataObject, NonEmptyStr, PasswordStr
from ceres.filter import UserFilter
from ceres.internal.app.shared import (
    VIEWER,
    AuthorizationCookieType,
    CurrentEngine,
    CurrentIdentity,
    Identity,
    PrivateIdentity,
    RequireUser,
    assign_authorization_cookie,
    create_identity,
)
from ceres.user import User

router = APIRouter(prefix="/auth", tags=["auth"])

WRONG_PASSWORD_DELAY_SECONDS = 2.5


class LoginInput(ImmutableDataObject):
    username: str
    password: str
    cookie: AuthorizationCookieType | None = None


class LoginResult(PrivateIdentity):
    pass


@router.post("/login")
async def login(
    engine: CurrentEngine,
    response: Response,
    input: LoginInput,
) -> LoginResult:
    authentication = engine.config.server.authentication
    if authentication is None:
        raise HTTPException(HTTP_403_FORBIDDEN)

    user = await engine.get_user(username=input.username)
    if user is None or not await engine.verify_password(input.password, user.password):
        await asyncio.sleep(WRONG_PASSWORD_DELAY_SECONDS)
        raise HTTPException(HTTP_401_UNAUTHORIZED)

    identity = create_identity(user, authentication)
    if input.cookie is not None:
        assign_authorization_cookie(response, identity, input.cookie)

    return LoginResult(
        user=identity.user,
        token=identity.token,
        expires=identity.expires,
    )


class RefreshInput(ImmutableDataObject):
    cookie: AuthorizationCookieType | None = None


class RefreshResult(PrivateIdentity):
    pass


@router.post("/refresh")
async def refresh(
    engine: CurrentEngine,
    identity: CurrentIdentity,
    response: Response,
    input: RefreshInput,
) -> RefreshResult:
    authentication = engine.config.server.authentication
    if authentication is None:
        raise HTTPException(HTTP_403_FORBIDDEN)
    if identity is None:
        raise HTTPException(HTTP_401_UNAUTHORIZED)

    identity = create_identity(identity.user, authentication)
    if input.cookie is not None:
        assign_authorization_cookie(response, identity, input.cookie)

    return RefreshResult(
        user=identity.user,
        token=identity.token,
        expires=identity.expires,
    )


@router.post("/logout")
async def logout(response: Response, identity: CurrentIdentity) -> Identity | None:
    response.delete_cookie("Authorization")
    if identity is None:
        raise HTTPException(HTTP_401_UNAUTHORIZED)

    return identity


class MeResult(ImmutableDataObject):
    user: User
    expires: DateTime


@router.get("/me", tags=["auth"])
async def get_me(identity: CurrentIdentity) -> MeResult:
    if identity is None:
        raise HTTPException(HTTP_401_UNAUTHORIZED)

    return MeResult(
        user=identity.user,
        expires=identity.expires,
    )


class ChangePasswordInput(ImmutableDataObject):
    old_password: NonEmptyStr
    new_password: PasswordStr


@router.post("/change-password", dependencies=[VIEWER])
async def change_password(
    engine: CurrentEngine,
    user: RequireUser,
    input: ChangePasswordInput,
) -> User:
    if not await engine.verify_password(input.old_password, user.password):
        await asyncio.sleep(WRONG_PASSWORD_DELAY_SECONDS)
        raise HTTPException(HTTP_400_BAD_REQUEST)

    hash = await engine.hash_password(input.new_password)
    await engine.update_user(UserFilter(id=user.id), {"password": hash})
    return user
