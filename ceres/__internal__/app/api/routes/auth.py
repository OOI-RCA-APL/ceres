import asyncio
from uuid import UUID

from fastapi import Response

from ceres.__internal__.app.shared import (
    AUTHENTICATED,
    EXCLUDE_PASSWORDS,
    AuthorizationCookieType,
    CurrentEngine,
    CurrentIdentity,
    Identity,
    RequireUser,
    Router,
    assign_authorization_cookie,
    create_identity,
)
from ceres.concurrency import sleep
from ceres.data import DataObject, Password
from ceres.error import (
    AuthenticationDisabledError,
    BadCredentialsError,
    NotAuthenticatedError,
    NotFoundError,
    NotPermittedError,
)
from ceres.user import User

router = Router(
    prefix="/auth",
    tags=["auth"],
    default_response_model_exclude=EXCLUDE_PASSWORDS,
)

WRONG_PASSWORD_DELAY_SECONDS = 2.5


class LoginInput(DataObject):
    """Request body for user login."""

    username: str
    password: str
    cookie: AuthorizationCookieType | None = None


@router.post("/login")
async def login(
    engine: CurrentEngine,
    response: Response,
    input: LoginInput,
) -> Identity:
    """Authenticate a user with username and password, returning a signed JWT identity.

    Optionally set an authorization cookie on the response. Introduce an artificial delay on
    failed attempts to mitigate brute-force attacks.

    Raises:
        AuthenticationDisabledError: If authentication is disabled.
        BadCredentialsError: If the credentials are invalid.
    """
    authentication = engine.config.server.authentication
    if authentication is None:
        raise AuthenticationDisabledError()

    user = await engine.users.where(username=input.username).first()
    if user is None or not await engine.verify_password(input.password, user.password):
        await asyncio.sleep(WRONG_PASSWORD_DELAY_SECONDS)
        raise BadCredentialsError()

    identity = create_identity(user, authentication)
    if input.cookie is not None:
        assign_authorization_cookie(response, identity, input.cookie)

    return identity


class RefreshInput(DataObject):
    """Request body for refreshing an authentication token."""

    cookie: AuthorizationCookieType | None = None


@router.post("/refresh")
async def refresh(
    engine: CurrentEngine,
    identity: CurrentIdentity,
    response: Response,
    input: RefreshInput,
) -> Identity:
    """Issue a fresh JWT for the currently authenticated user.

    Raises:
        AuthenticationDisabledError: If authentication is disabled.
        NotAuthenticatedError: If the caller is not authenticated.
    """
    authentication = engine.config.server.authentication
    if authentication is None:
        raise AuthenticationDisabledError()
    if identity is None:
        raise NotAuthenticatedError()

    identity = create_identity(identity.user, authentication)
    if input.cookie is not None:
        assign_authorization_cookie(response, identity, input.cookie)

    return identity


class AuthFeatures(DataObject):
    """Optional authentication behavior the console adapts itself to."""

    user_switching: bool
    """Whether an administrator may take on another user's identity."""


@router.get("/features")
async def get_auth_features(engine: CurrentEngine) -> AuthFeatures:
    """Report which optional authentication behavior this engine allows.

    Only a boolean, which probing the routes would reveal anyway, so the console can hide an
    affordance that would not work rather than offer one that fails.
    """
    authentication = engine.config.server.authentication
    return AuthFeatures(
        user_switching=authentication is not None and authentication.allow_user_switching
    )


class SwitchUserInput(DataObject):
    """Request body for taking on another user's identity."""

    user_id: UUID
    cookie: AuthorizationCookieType | None = None


@router.post("/switch")
async def switch_user(
    engine: CurrentEngine,
    identity: CurrentIdentity,
    response: Response,
    input: SwitchUserInput,
) -> Identity:
    """Issue an identity for another user without their password.

    A way to see the console as each user sees it, off unless
    `server.authentication.allow_user_switching` is set, which belongs in development. It is a
    full bypass of password authentication, so the route reports itself missing rather than
    forbidden when the setting is off, and nothing about it is reachable in a default deployment.

    Only an administrator may switch, and the issued identity is not one, so a switch cannot be
    chained onward into a third account. Returning needs no route, because the caller still holds
    the token they had before switching.

    Raises:
        AuthenticationDisabledError: If authentication is disabled.
        NotFoundError: If user switching is off, or the target user does not exist.
        NotAuthenticatedError: If the caller is not authenticated.
        NotPermittedError: If the caller is not an administrator.
    """
    authentication = engine.config.server.authentication
    if authentication is None:
        raise AuthenticationDisabledError()
    if not authentication.allow_user_switching:
        raise NotFoundError()
    if identity is None:
        raise NotAuthenticatedError()
    if not identity.user.admin:
        raise NotPermittedError()

    user = await engine.users.get(input.user_id)
    if user is None:
        raise NotFoundError()

    switched = create_identity(user, authentication, switched_from=identity.user.id)
    if input.cookie is not None:
        assign_authorization_cookie(response, switched, input.cookie)

    return switched


@router.post("/logout")
async def logout(response: Response, identity: CurrentIdentity) -> Identity:
    """Log out by clearing the authorization cookie and returning the current identity.

    Raises:
        NotAuthenticatedError: If the caller is not authenticated.
    """
    response.delete_cookie("Authorization")
    if identity is None:
        raise NotAuthenticatedError()

    return identity


@router.get("/me")
async def get_me(identity: CurrentIdentity) -> Identity:
    """Return the identity of the currently authenticated user.

    Raises:
        NotAuthenticatedError: If the caller is not authenticated.
    """
    if identity is None:
        raise NotAuthenticatedError()

    return identity


class ChangePasswordInput(DataObject):
    """Request body for changing the current user's password."""

    old_password: str
    new_password: Password


@router.post("/change-password", dependencies=[AUTHENTICATED])
async def change_password(
    engine: CurrentEngine,
    user: RequireUser,
    input: ChangePasswordInput,
) -> User:
    """Change the current user's password after verifying the old one.

    Introduce an artificial delay on incorrect old-password attempts.

    Raises:
        BadCredentialsError: If the old password is wrong.
        NotFoundError: If the user cannot be found after the update.
    """
    if not await engine.database.verify_password(input.old_password, user.password):
        await sleep(WRONG_PASSWORD_DELAY_SECONDS)
        raise BadCredentialsError()

    changed = await engine.users.where(id=user.id).update({"password": input.new_password}).first()
    if changed is None:
        raise NotFoundError()

    return changed
