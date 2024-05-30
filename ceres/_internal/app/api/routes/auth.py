import asyncio

from fastapi import APIRouter, Response

from ceres._internal.app.shared import (
    VIEWER,
    APIIdentity,
    APIUser,
    AuthorizationCookieType,
    CurrentEngine,
    CurrentIdentity,
    Identity,
    RequireUser,
    assign_authorization_cookie,
    create_identity,
)
from ceres.data import DateTime, ImmutableDataObject, NonEmptyStr, PasswordStr
from ceres.error import (
    AuthenticationDisabledError,
    BadCredentialsError,
    Failure,
    NotAuthenticatedError,
    NotFoundError,
)
from ceres.user import User, UserFilter

router = APIRouter(prefix="/auth", tags=["auth"])

WRONG_PASSWORD_DELAY_SECONDS = 2.5


class LoginInput(ImmutableDataObject):
    username: str
    password: str
    cookie: AuthorizationCookieType | None = None


class LoginResult(APIIdentity):
    pass


@router.post("/login")
async def login(
    engine: CurrentEngine,
    response: Response,
    input: LoginInput,
) -> LoginResult:
    authentication = engine.config.server.authentication
    if authentication is None:
        raise Failure(AuthenticationDisabledError)

    user = await engine.users.get(username=input.username)
    if user is None or not await engine.verify_password(input.password, user.password):
        await asyncio.sleep(WRONG_PASSWORD_DELAY_SECONDS)
        raise Failure(BadCredentialsError)

    identity = create_identity(user, authentication)
    if input.cookie is not None:
        assign_authorization_cookie(response, identity, input.cookie)

    return LoginResult(
        user=APIUser.model_validate(identity.user, from_attributes=True),
        token=identity.token,
        expires=identity.expires,
    )


class RefreshInput(ImmutableDataObject):
    cookie: AuthorizationCookieType | None = None


class RefreshResult(APIIdentity):
    pass


@router.post("/refresh", response_model=RefreshResult)
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


@router.post("/logout", response_model=APIIdentity)
async def logout(response: Response, identity: CurrentIdentity) -> Identity:
    response.delete_cookie("Authorization")
    if identity is None:
        raise Failure(NotAuthenticatedError)

    return identity


class MeResult(ImmutableDataObject):
    user: APIUser
    expires: DateTime


@router.get("/me", tags=["auth"], response_model=MeResult)
async def get_me(identity: CurrentIdentity) -> Identity:
    if identity is None:
        raise Failure(NotAuthenticatedError)

    return identity


class ChangePasswordInput(ImmutableDataObject):
    old_password: NonEmptyStr
    new_password: PasswordStr


@router.post("/change-password", dependencies=[VIEWER], response_model=APIUser)
async def change_password(
    engine: CurrentEngine,
    user: RequireUser,
    input: ChangePasswordInput,
) -> User:
    if not await engine.database.verify_password(input.old_password, user.password):
        await asyncio.sleep(WRONG_PASSWORD_DELAY_SECONDS)
        raise Failure(BadCredentialsError)

    changed = await engine.users.update(UserFilter(id=user.id), {"password": input.new_password})
    if changed is None:
        raise Failure(NotFoundError)

    return changed
