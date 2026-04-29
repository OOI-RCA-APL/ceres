import asyncio

from fastapi import Response

from ceres.__internal__.app.shared import (
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
from ceres.concurrency import sleep
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
        Failure: If authentication is disabled or the credentials are invalid.
    """
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
        Failure: If authentication is disabled or the caller is not authenticated.
    """
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
    """Log out by clearing the authorization cookie and returning the current identity.

    Raises:
        Failure: If the caller is not authenticated.
    """
    response.delete_cookie("Authorization")
    if identity is None:
        raise Failure(NotAuthenticatedError)

    return identity


@router.get("/me")
async def get_me(identity: CurrentIdentity) -> Identity:
    """Return the identity of the currently authenticated user.

    Raises:
        Failure: If the caller is not authenticated.
    """
    if identity is None:
        raise Failure(NotAuthenticatedError)

    return identity


class ChangePasswordInput(DataObject):
    """Request body for changing the current user's password."""

    old_password: str
    new_password: Password


@router.post("/change-password", dependencies=[VIEWER])
async def change_password(
    engine: CurrentEngine,
    user: RequireUser,
    input: ChangePasswordInput,
) -> User:
    """Change the current user's password after verifying the old one.

    Introduce an artificial delay on incorrect old-password attempts.

    Raises:
        Failure: If the old password is wrong or the user cannot be found after the update.
    """
    if not await engine.database.verify_password(input.old_password, user.password):
        await sleep(WRONG_PASSWORD_DELAY_SECONDS)
        raise Failure(BadCredentialsError)

    changed = await engine.users.where(id=user.id).update({"password": input.new_password}).first()
    if changed is None:
        raise Failure(NotFoundError)

    return changed
