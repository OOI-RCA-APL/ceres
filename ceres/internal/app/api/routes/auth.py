from fastapi import APIRouter, HTTPException, Response
from starlette.status import HTTP_401_UNAUTHORIZED, HTTP_403_FORBIDDEN

from ceres.data import DateTime, ImmutableDataObject
from ceres.internal.app.shared import (
    AuthorizationCookieType,
    CurrentEngine,
    CurrentIdentity,
    Identity,
    PrivateIdentity,
    assign_authorization_cookie,
    create_identity,
)
from ceres.internal.auth import verify_password
from ceres.user import User

router = APIRouter(prefix="/auth", tags=["auth"])


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
    if user is None:
        raise HTTPException(HTTP_401_UNAUTHORIZED)
    if not verify_password(input.password, user.password):
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
