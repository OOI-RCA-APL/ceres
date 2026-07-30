"""The engine as the native server's host.

The native server owns HTTP and answers most requests by calling one named operation
here. Each operation validates its own arguments through Pydantic and runs the same
engine and query-layer code the API always has, so filters, permissions, and wire
shapes keep their exact behavior while the transport moves to Rust.

Results cross the boundary as one JSON envelope per call, `{"ok": ...}` for a payload
and `{"error": {"status", "envelope"}}` for a typed refusal, which the server serves
verbatim. Streams open under a handle and yield one pre-serialized message at a time.
"""

from __future__ import annotations

import json
from collections.abc import AsyncIterator, Callable
from itertools import count
from typing import TYPE_CHECKING, Any

from pydantic import ValidationError

from ceres.data import to_json, validate
from ceres.error import (
    Error,
    HTTPError,
    NotAuthenticatedError,
    NotFoundError,
    ValidationFailedError,
    ValidationProblem,
)
from ceres.user import User

if TYPE_CHECKING:
    from uuid import UUID

    from ceres.engine import Engine

_OPERATIONS: dict[str, Callable[[Host, dict[str, Any]], Any]] = {}
"""Every named operation, resolved once at import."""

_STREAMS: dict[str, Callable[[Host, dict[str, Any]], AsyncIterator[str]]] = {}
"""Every named stream, each an async iterator of serialized messages."""


def operation(name: str):
    """Register an async operation under its name."""

    def register[T: Callable[..., Any]](function: T) -> T:
        _OPERATIONS[name] = function
        return function

    return register


def stream(name: str):
    """Register an async generator of serialized messages under its name."""

    def register[T: Callable[..., Any]](function: T) -> T:
        _STREAMS[name] = function
        return function

    return register


class Host:
    """The engine behind the native server's host interface."""

    def __init__(self, engine: Engine) -> None:
        self._engine = engine
        self._streams: dict[int, AsyncIterator[str]] = {}
        self._handles = count(1)

    @property
    def engine(self) -> Engine:
        return self._engine

    async def user(self, id: UUID) -> str:
        """Look up a user by ID for the server's identity resolution."""
        return _record(await self._engine.users.get(id))

    async def verify_login(self, username: str, password: str) -> str:
        """Check a username and password, answering with the user when they match."""
        user = await self._engine.users.where(username=username).first()
        if user is None or not await self._engine.verify_password(password, user.password):
            return _record(None)

        return _record(user)

    async def change_password(self, id: UUID, old_password: str, new_password: str) -> str:
        """Replace a user's password, refusing when the old one does not match."""
        try:
            user = await self._engine.users.get(id)
            if user is None or not await self._engine.verify_password(old_password, user.password):
                return _record(None)

            await self._engine.users.where(id=id).update(
                validate(User.Update, {"password": new_password})
            )
            return _record(await self._engine.users.get(id))
        except Error as error:
            return _failure(error)

    async def operate(self, name: str, arguments: str) -> str:
        """Run one named operation, answering with its result envelope."""
        try:
            handler = _OPERATIONS.get(name)
            if handler is None:
                raise NotFoundError()

            payload = await handler(self, json.loads(arguments))
            return json.dumps({"ok": payload})
        except Error as error:
            return _failure(error)
        except ValidationError as error:
            # An operation validates its own arguments, so a validation failure is a bad
            # request rather than an internal one, reported with its problems like the
            # framework's own handler always did.
            return _failure(ValidationFailedError(problems=ValidationProblem.extract(error)))
        except Exception as error:  # noqa: BLE001
            del error
            return _failure(HTTPError(status=500))

    async def stream_open(self, name: str, arguments: str) -> str:
        """Open a stream, answering with the handle its messages arrive under."""
        try:
            opener = _STREAMS.get(name)
            if opener is None:
                raise NotFoundError()

            iterator = opener(self, json.loads(arguments))
            handle = next(self._handles)
            self._streams[handle] = iterator
            return json.dumps({"ok": handle})
        except ValidationError as error:
            return json.dumps(
                {
                    "close": _close_of(
                        ValidationFailedError(problems=ValidationProblem.extract(error))
                    )
                }
            )
        except Error as error:
            return json.dumps({"close": _close_of(error)})
        except Exception as error:  # noqa: BLE001
            return json.dumps({"close": {"code": 1011, "reason": str(error)[:120]}})

    async def stream_next(self, handle: int) -> str:
        """Await the next message on a stream, reporting its end or its failure."""
        iterator = self._streams.get(handle)
        if iterator is None:
            return json.dumps({"end": True})

        try:
            return json.dumps({"message": await anext(iterator)})
        except StopAsyncIteration:
            return json.dumps({"end": True})
        except Error as error:
            return json.dumps({"close": _close_of(error)})
        except Exception as error:  # noqa: BLE001
            return json.dumps({"close": {"code": 1011, "reason": str(error)[:120]}})

    async def stream_close(self, handle: int) -> None:
        """Release a stream, closing its iterator if it supports closing."""
        iterator = self._streams.pop(handle, None)
        closer = getattr(iterator, "aclose", None)
        if closer is not None:
            try:
                await closer()
            except Exception:  # noqa: BLE001, S110
                pass


def _record(user: User | None) -> str:
    """The envelope carrying a user record, or its absence."""
    if user is None:
        return json.dumps({"ok": None})

    payload = json.loads(to_json(user, exclude={"password": True}))
    return json.dumps(
        {
            "ok": {
                "id": str(user.id),
                "admin": user.admin,
                "disabled": user.disabled,
                "payload": payload,
            }
        }
    )


def _failure(error: Error) -> str:
    """The envelope carrying a typed refusal, with its status and serialized form."""
    from ceres.error import simplify

    return json.dumps(
        {
            "error": {
                "status": error.__error_status_code__,
                "envelope": json.loads(to_json(simplify(error))),
            }
        }
    )


def _close_of(error: Error) -> dict[str, Any]:
    """The close code and reason a stream failure reports.

    A refusal the caller could have avoided closes with a policy violation carrying the
    error, and anything else reports an internal failure, matching the codes the socket
    routes have always sent.
    """
    from ceres.error import ProcedureError, ProcedureInternalError, simplify

    policy = isinstance(error, NotFoundError | NotAuthenticatedError | ProcedureInternalError)
    if not policy and isinstance(error, ProcedureError):
        code = 1011
    else:
        code = 1008 if policy else 1011

    return {"code": code, "reason": to_json(simplify(error))}
