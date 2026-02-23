from __future__ import annotations

import asyncio

from fastapi import Response

from ceres._internal.app.shared import (
    EXCLUDE_PASSWORDS,
    VIEWER,
    AuthorizationCookieType,
    CurrentEngine,
    CurrentIdentity,
    Identity,
    RequireUser,
    Router,
    assign_authorization_cookie,
    create_identity,
)
from ceres.data import DataObject, Password
from ceres.error import (
    AuthenticationDisabledError,
    BadCredentialsError,
    Failure,
    NotAuthenticatedError,
    NotFoundError,
)
from ceres.user import User

router = Router(
    prefix="/auth",
    tags=["auth"],
    default_response_model_exclude=EXCLUDE_PASSWORDS,
)

WRONG_PASSWORD_DELAY_SECONDS = 2.5


class LoginInput(DataObject):
    username: str
    password: str
    cookie: AuthorizationCookieType | None = None


@router.post("/login")
async def login(
    engine: CurrentEngine,
    response: Response,
    input: LoginInput,
) -> Identity:
    authentication = engine.config.server.authentication
    if authentication is None:
        raise Failure(AuthenticationDisabledError)

    user = await engine.users.where(username=input.username).first()
    if user is None or not await engine.verify_password(input.password, user.password):
        await asyncio.sleep(WRONG_PASSWORD_DELAY_SECONDS)
        raise Failure(BadCredentialsError)

    identity = create_identity(user, authentication)
    if input.cookie is not None:
        assign_authorization_cookie(response, identity, input.cookie)

    return identity


class RefreshInput(DataObject):
    cookie: AuthorizationCookieType | None = None


@router.post("/refresh")
async def refresh(
    engine: CurrentEngine,
    identity: CurrentIdentity,
    response: Response,
    input: RefreshInput,
) -> Identity:
    authentication = engine.config.server.authentication
    if authentication is None:
        raise Failure(AuthenticationDisabledError)
    if identity is None:
        raise Failure(NotAuthenticatedError)

    identity = create_identity(identity.user, authentication)
    if input.cookie is not None:
        assign_authorization_cookie(response, identity, input.cookie)

    return identity


@router.post("/logout")
async def logout(response: Response, identity: CurrentIdentity) -> Identity:
    response.delete_cookie("Authorization")
    if identity is None:
        raise Failure(NotAuthenticatedError)

    return identity


@router.get("/me")
async def get_me(identity: CurrentIdentity) -> Identity:
    if identity is None:
        raise Failure(NotAuthenticatedError)

    return identity


class ChangePasswordInput(DataObject):
    old_password: str
    new_password: Password


@router.post("/change-password", dependencies=[VIEWER])
async def change_password(
    engine: CurrentEngine,
    user: RequireUser,
    input: ChangePasswordInput,
) -> User:
    if not await engine.database.verify_password(input.old_password, user.password):
        await asyncio.sleep(WRONG_PASSWORD_DELAY_SECONDS)
        raise Failure(BadCredentialsError)

    changed = await engine.users.where(id=user.id).update({"password": input.new_password}).first()
    if changed is None:
        raise Failure(NotFoundError)

    return changed
