"""The engine as the native server's host.

The native server owns HTTP and answers most requests by calling one named operation
here. Each operation validates its own arguments through Pydantic and runs the same
engine and query-layer code the API always has, so filters, permissions, and wire
shapes keep their exact behavior while the transport moves to Rust.

Results cross the boundary as one JSON envelope per call, `{"ok": ...}` for a payload,
`{"error": {"status", "envelope"}}` for a typed refusal, and `{"response": ...}` for a
media output the server serves as a body of its own, which it serves verbatim. Streams
open under a handle and yield one pre-serialized message at a time.
"""

from __future__ import annotations

import json
from collections.abc import AsyncIterator, Callable
from dataclasses import dataclass
from itertools import count
from typing import TYPE_CHECKING, Any

from pydantic import ValidationError

from ceres.data import to_json, validate
from ceres.error import (
    Error,
    HTTPError,
    NotAuthenticatedError,
    NotFoundError,
    ProcedureInternalError,
    ValidationFailedError,
    ValidationProblem,
    trace,
)
from ceres.user import User

if TYPE_CHECKING:
    from collections.abc import Awaitable, Mapping
    from uuid import UUID

    from ceres.component import BaseOutput, FileOutput, StreamingOutput
    from ceres.engine import Engine

_OPERATIONS: dict[str, Callable[[Host, dict[str, Any]], Any]] = {}
"""Every named operation, resolved once at import."""

_STREAMS: dict[str, Callable[[Host, dict[str, Any]], AsyncIterator[str]]] = {}
"""Every named stream, each an async iterator of serialized messages."""


@dataclass(frozen=True, slots=True)
class Served:
    """A response the server produces itself, described for it to serve.

    An operation answers with one of these instead of a payload, and it travels in its
    own envelope rather than inside the payload, so a procedure returning data that
    happens to look like a description cannot pass itself off as one.
    """

    description: dict[str, Any]
    """The status, headers, body source, and the handle to release once the body ends."""


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
        self._chunks: dict[int, AsyncIterator[bytes]] = {}
        self._releases: dict[int, Callable[[], Awaitable[Any]]] = {}
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
            if isinstance(payload, Served):
                return json.dumps({"response": payload.description})

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

    def serve(self, output: BaseOutput) -> Served:
        """Describe a media output for the server, which produces its body itself.

        A file names its path, so its bytes never cross the boundary. A stream registers
        its chunks under the description's handle for the server to pull. Either way the
        server releases the handle once the body ends, which is what runs the output's
        exit hook, so a client that leaves early still triggers the cleanup.

        Raises:
            ProcedureInternalError: If the output is not a kind the server can serve.
        """
        from ceres.component import FileOutput, StreamingOutput

        handle = next(self._handles)
        if isinstance(output, FileOutput):
            description = _file_description(output)
        elif isinstance(output, StreamingOutput):
            self._chunks[handle] = _streaming_chunks(output)
            description = {
                "status": output.http_status,
                "headers": _headers(output.http_headers, output.media),
            }
        else:
            raise ProcedureInternalError(
                exception=trace(TypeError(f"{type(output).__name__} is not a servable output"))
            )

        if output.on_exit is not None:
            self._releases[handle] = output.on_exit

        return Served({**description, "handle": handle})

    async def next_chunk(self, handle: int) -> bytes | None:
        """Await the next chunk of a served body, `None` once it ends."""
        chunks = self._chunks.get(handle)
        if chunks is None:
            return None

        try:
            return await anext(chunks)
        except StopAsyncIteration:
            return None

    async def stream_close(self, handle: int) -> None:
        """Release whatever a handle names, a message stream, a body, or an exit hook.

        A handle can name any combination of the three, and each releases even when
        another fails, because an exit hook has to run whatever ended the body.
        """
        iterator: AsyncIterator[Any] | None = self._streams.pop(handle, None)
        if iterator is None:
            iterator = self._chunks.pop(handle, None)

        closer = getattr(iterator, "aclose", None)
        if closer is not None:
            try:
                await closer()
            except Exception:  # noqa: BLE001, S110
                pass

        release = self._releases.pop(handle, None)
        if release is not None:
            try:
                await release()
            except Exception:  # noqa: BLE001, S110
                pass


def _file_description(output: FileOutput) -> dict[str, Any]:
    """Describe a file output, naming its path for the server to stream.

    Stat the file here so a missing one fails as a refusal, before any of the response
    has been sent, rather than truncating a body already on its way.
    """
    from mimetypes import guess_type

    status = output.path.stat()
    headers = _headers(output.http_headers, output.media or guess_type(output.path.name)[0])
    if not _declares(headers, "content-length"):
        headers.append(["content-length", str(status.st_size)])

    if output.http_filename is not None and not _declares(headers, "content-disposition"):
        headers.append(["content-disposition", _disposition(output.http_filename)])

    return {
        "status": output.http_status,
        "headers": headers,
        "file": str(output.path),
    }


async def _streaming_chunks(output: StreamingOutput) -> AsyncIterator[bytes]:
    """Yield a streaming output's chunks, starting its stream lazily when it is a factory."""
    stream = output.stream() if callable(output.stream) else output.stream
    async for chunk in stream:
        yield bytes(chunk)


def _headers(declared: Mapping[str, str] | None, media: str | None) -> list[list[str]]:
    """The response's headers, the content type added only when none is declared."""
    headers = [[name, value] for name, value in (declared or {}).items()]
    if media is not None and not _declares(headers, "content-type"):
        headers.append(["content-type", media])

    return headers


def _declares(headers: list[list[str]], name: str) -> bool:
    """Whether a header is already declared, compared without case."""
    return any(declared.lower() == name for declared, _ in headers)


def _disposition(filename: str) -> str:
    """The content disposition naming a download, encoded when the name is not ASCII."""
    try:
        filename.encode("ascii")
    except UnicodeEncodeError:
        from urllib.parse import quote

        return f"attachment; filename*=utf-8''{quote(filename)}"

    return f'attachment; filename="{filename}"'


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
    """The envelope carrying a typed refusal, with its status and serialized form.

    A generic HTTP error carries the status it stands for on the instance rather than on
    its class, which is the status it serves under.
    """
    from ceres.error import HTTPError, simplify

    if isinstance(error, HTTPError):
        status = error.status
    else:
        status = error.__error_status_code__

    return json.dumps(
        {"error": {"status": status, "envelope": json.loads(to_json(simplify(error)))}}
    )


def _close_of(error: Error) -> dict[str, Any]:
    """The close code and reason a stream failure reports.

    A refusal the caller could have avoided closes with a policy violation carrying the
    error, and anything else reports an internal failure, matching the codes the socket
    routes have always sent.
    """
    from ceres.error import simplify

    policy = isinstance(error, NotFoundError | NotAuthenticatedError | ProcedureInternalError)
    return {"code": 1008 if policy else 1011, "reason": to_json(simplify(error))}
