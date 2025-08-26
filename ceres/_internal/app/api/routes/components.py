from __future__ import annotations

import asyncio
import traceback
from typing import (
    TYPE_CHECKING,
    Annotated,
    Any,
    AsyncIterator,
    Literal,
    Mapping,
    Sequence,
    TypeAlias,
)

from fastapi import APIRouter, Body, Request, Response, WebSocket, WebSocketException
from fastapi.responses import StreamingResponse
from starlette.background import BackgroundTask
from starlette.status import WS_1008_POLICY_VIOLATION, WS_1011_INTERNAL_ERROR

from ceres._internal import util
from ceres._internal.app.shared import (
    VIEWER,
    CurrentEngine,
    CurrentProcedureQueryArguments,
    CurrentRole,
    CurrentSocket,
)
from ceres._internal.util import BytesLike, cancel
from ceres.address import Address
from ceres.component import Component, Media, ProcedureBinding, ProcedureType
from ceres.data import DeferBuild, ImmutableDataObject, Name, StrEnum, jsonify
from ceres.error import (
    Failure,
    NotFoundError,
    ProcedureComponentNotFoundError,
    ProcedureError,
    ProcedureInternalError,
    ProcedureNotFoundError,
    ProcedureNotPermittedError,
)
from ceres.result import Fail
from ceres.stream import WriteStream
from ceres.user import UserRole


class ComponentRole(StrEnum):
    CONNECTION = "connection"
    INTERFACE = "interface"


class APIComponent(ImmutableDataObject, DeferBuild):
    name: Name
    address: Address
    components: Sequence[APIComponent]
    roles: Sequence[ComponentRole]
    procedures: Sequence[ProcedureBinding]


APIComponent.__name__ = "Component"

router = APIRouter(prefix="/components", tags=["components"])


def _get_component_roles(component: Component | type[Component]) -> Sequence[ComponentRole]:
    if not isinstance(component, type):
        component = type(component)

    from ceres.connection import Connection
    from ceres.interface import Interface

    roles: list[ComponentRole] = []
    if issubclass(component, Connection):
        roles.append(ComponentRole.CONNECTION)
    if issubclass(component, Interface):
        roles.append(ComponentRole.INTERFACE)

    return roles


@router.get("/{address}", dependencies=[VIEWER])
async def get_component(engine: CurrentEngine, address: Address) -> APIComponent:
    component = engine.get_component(address)
    if component is None:
        raise Failure(NotFoundError)

    subcomponents: list[APIComponent] = []
    for subcomponent in component.system.children:
        subcomponents.append(await get_component(engine, address / subcomponent.name))

    try:
        info = APIComponent(
            name=component.system.name,
            address=address,
            roles=_get_component_roles(component),
            procedures=list(component.system.get_procedure_bindings().values()),
            components=subcomponents,
        )
        return info
    except Exception:
        traceback.print_exc()
        raise


@router.get("/{address}/procedures", tags=["procedures"])
async def get_procedures(engine: CurrentEngine, address: Address) -> list[ProcedureBinding]:
    component = engine.get_component(address)
    if component is None:
        raise Failure(NotFoundError)

    return list(component.system.get_procedure_bindings().values())


@router.get("/{address}/procedures/{procedure}", tags=["procedures"])
async def get_procedure(
    engine: CurrentEngine,
    address: Address,
    procedure: Name,
) -> ProcedureBinding:
    component = engine.get_component(address)
    if component is None:
        raise Failure(NotFoundError)
    binding = component.system.get_procedure_binding(procedure)
    if binding is None:
        raise Failure(NotFoundError)

    return binding


if TYPE_CHECKING:
    CallResult: TypeAlias = Any | Response | None | ProcedureError
else:
    CallResult = Any


async def _call(
    *,
    method: Literal["GET", "POST"],
    engine: CurrentEngine,
    role: CurrentRole,
    address: Address,
    procedure: Name,
    arguments: Mapping[Name, object] | None = None,
) -> CallResult:
    try:
        component = engine.get_component(address)
        if component is None:
            return Fail(ProcedureComponentNotFoundError())
        binding = component.system.get_procedure_binding(procedure)
        if binding is None:
            return Fail(ProcedureNotFoundError())
        if role < binding.permissions:
            return Fail(ProcedureNotPermittedError())
        if method == "GET" and binding.type == ProcedureType.ACTION:
            return Fail(ProcedureNotPermittedError())
        if binding.type == ProcedureType.ACTION and role < UserRole.OPERATOR:
            return Fail(ProcedureNotPermittedError())

        output = await component.system.call(procedure, arguments)
        if not isinstance(output, Media):
            return output

        stream: WriteStream[BytesLike] = WriteStream()
        writer = asyncio.create_task(output.writer(stream))

        async def canceller():
            await cancel(writer)

        # Convert the bytes-like object to something `StreamingResponse` can handle.
        def convert(chunk: BytesLike):
            if isinstance(chunk, bytearray):
                chunk = bytes(chunk)

            return chunk

        # Yield chunks from the stream. Exit if the writer task is exits, or cancel it if this async
        # iterator itself is cancelled.
        async def read() -> AsyncIterator[str | bytes | memoryview]:
            try:
                reader = stream.read()
                while not writer.done():
                    try:
                        async with asyncio.timeout(0.1):
                            chunk = await anext(reader)

                        yield convert(chunk)
                    except TimeoutError:
                        continue

                    # Yield to the event loop.
                    await asyncio.sleep(0)

                # Yield any remaining chunks from the reader buffer after the writer task is done.
                for chunk in reader.clear():
                    yield convert(chunk)
            finally:
                # Attempt to cancel the writer task if it hasn't already.
                try:
                    async with asyncio.timeout(3):
                        await cancel(writer)
                except TimeoutError:
                    pass

        return StreamingResponse(
            read(),
            media_type=output.type,
            background=BackgroundTask(canceller),
        )

    except Failure as exception:
        if isinstance(exception.error, ProcedureError):
            return Fail(exception.error)

        raise


@router.post("/{address}/procedures/{procedure}/call", tags=["procedures"])
async def call(
    engine: CurrentEngine,
    role: CurrentRole,
    address: Address,
    procedure: Name,
    arguments: Annotated[Mapping[Name, object] | None, Body()] = None,
) -> CallResult:
    return await _call(
        method="POST",
        engine=engine,
        role=role,
        address=address,
        procedure=procedure,
        arguments=arguments,
    )


@router.get("/{address}/procedures/{procedure}/call", tags=["procedures"])
async def call_by_get(
    engine: CurrentEngine,
    role: CurrentRole,
    request: Request,
    address: Address,
    procedure: Name,
    query_arguments: CurrentProcedureQueryArguments,
) -> CallResult:
    arguments = {}
    arguments.update(query_arguments or {})
    arguments.update(request.query_params)
    arguments.pop("arguments", None)
    arguments.pop("args", None)

    return await _call(
        method="GET",
        engine=engine,
        role=role,
        address=address,
        procedure=procedure,
        arguments=arguments,
    )


@router.websocket("/{address}/procedures/{procedure}/subscribe")
async def subscribe(
    socket: CurrentSocket,
    connection: WebSocket,
    engine: CurrentEngine,
    role: CurrentRole,
    address: Address,
    procedure: Name,
    query_arguments: CurrentProcedureQueryArguments,
) -> None:
    arguments = {}
    arguments.update(query_arguments or {})
    arguments.update(connection.query_params)
    arguments.pop("arguments", None)
    arguments.pop("args", None)

    component = engine.get_component(address)
    if component is None:
        raise WebSocketException(
            WS_1008_POLICY_VIOLATION,
            jsonify(Fail(ProcedureComponentNotFoundError())),
        )

    binding = component.system.get_procedure_binding(procedure)
    if binding is None:
        raise WebSocketException(
            WS_1008_POLICY_VIOLATION,
            jsonify(Fail(ProcedureNotFoundError())),
        )

    if binding.type == ProcedureType.ACTION and role < UserRole.OPERATOR:
        raise WebSocketException(
            WS_1008_POLICY_VIOLATION,
            jsonify(Fail(ProcedureNotPermittedError())),
        )

    async def write() -> None:
        try:
            async for output in component.system.subscribe(procedure, arguments):
                await socket.send(output)
        except Exception as exception:
            if isinstance(exception, Failure) and isinstance(exception.error, ProcedureError):
                if not isinstance(exception.error, ProcedureInternalError):
                    code = WS_1011_INTERNAL_ERROR
                else:
                    code = WS_1008_POLICY_VIOLATION

                reason = jsonify(Fail(exception.error))
            else:
                code = WS_1011_INTERNAL_ERROR
                reason = jsonify(util.strify(exception)[0:100])

            await socket.close(code, reason)

    await socket.execute(write)
