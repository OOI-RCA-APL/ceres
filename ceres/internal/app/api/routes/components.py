import asyncio
import traceback
from asyncio import CancelledError
from typing import Annotated, Any, Literal, Mapping, Sequence

from fastapi import APIRouter, Body, Request, WebSocket

from ceres.address import Address
from ceres.component import Component, ProcedureBinding, ProcedureType
from ceres.data import ImmutableDataObject, Name, StrEnum, jsonify
from ceres.errors import (
    Failure,
    NotFoundError,
    ProcedureComponentNotFoundError,
    ProcedureError,
    ProcedureInternalError,
    ProcedureNotFoundError,
    ProcedureNotPermittedError,
)
from ceres.internal.app.shared import (
    VIEWER,
    CurrentEngine,
    CurrentProcedureQueryArguments,
    CurrentRole,
)
from ceres.internal.utilities import strify
from ceres.result import Fail, Ok, Result
from ceres.user import UserRole


class ComponentRole(StrEnum):
    CONNECTION = "connection"
    INTERFACE = "interface"


class APIComponent(ImmutableDataObject):
    name: Name
    address: Address
    components: Sequence["APIComponent"]
    roles: Sequence[ComponentRole]
    procedures: Sequence[ProcedureBinding]


APIComponent.__name__ = "Component"
APIComponent.model_rebuild()

router = APIRouter(prefix="/components", tags=["components"])


def _get_component_roles(component: Component | type[Component]) -> Sequence[ComponentRole]:
    if not isinstance(component, type):
        component = type(component)

    from ceres.roles.connection import Connection
    from ceres.roles.interface import Interface

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

    children: list[APIComponent] = []
    for child in component.components:
        children.append(await get_component(engine, address / child.name))

    try:
        info = APIComponent(
            name=component.name,
            address=address,
            roles=_get_component_roles(type(component.unref())),
            procedures=list(component.get_procedure_bindings().values()),
            components=children,
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

    return list(component.get_procedure_bindings().values())


@router.get("/{address}/procedures/{procedure}", tags=["procedures"])
async def get_procedure(
    engine: CurrentEngine,
    address: Address,
    procedure: Name,
) -> ProcedureBinding:
    component = engine.get_component(address)
    if component is None:
        raise Failure(NotFoundError)
    binding = component.get_procedure_bindings().get(procedure)
    if binding is None:
        raise Failure(NotFoundError)

    return binding


@router.post("/{address}/procedures/{procedure}/call", tags=["procedures"])
async def call(
    engine: CurrentEngine,
    role: CurrentRole,
    address: Address,
    procedure: Name,
    arguments: Annotated[Mapping[Name, object] | None, Body()] = None,
) -> Result[Any | None, ProcedureError]:
    return await _call(
        method="POST",
        engine=engine,
        role=role,
        address=address,
        procedure=procedure,
        arguments=arguments,
    )


@router.get("/{address}/procedures/{procedure}/call", tags=["procedures"])
async def call_query(
    engine: CurrentEngine,
    role: CurrentRole,
    request: Request,
    address: Address,
    procedure: Name,
    query_arguments: CurrentProcedureQueryArguments,
) -> Result[Any | None, ProcedureError]:
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


async def _call(
    *,
    method: Literal["GET", "POST"],
    engine: CurrentEngine,
    role: CurrentRole,
    address: Address,
    procedure: Name,
    arguments: Mapping[Name, object] | None = None,
) -> Result[Any | None, ProcedureError]:
    try:
        component = engine.get_component(address)
        if component is None:
            return Fail(ProcedureComponentNotFoundError())
        binding = component.get_procedure_bindings().get(procedure)
        if binding is None:
            return Fail(ProcedureNotFoundError())
        if method == "GET" and binding.type == ProcedureType.ACTION:
            return Fail(ProcedureNotPermittedError())
        if binding.type == ProcedureType.ACTION and role < UserRole.OPERATOR:
            return Fail(ProcedureNotPermittedError())

        return Ok(await component.call(procedure, arguments))
    except Failure as exception:
        if isinstance(exception.error, ProcedureError):
            return Fail(exception.error)

        raise


@router.websocket("/{address}/procedures/{procedure}/subscribe")
async def subscribe(
    socket: WebSocket,
    engine: CurrentEngine,
    role: CurrentRole,
    address: Address,
    procedure: Name,
    query_arguments: CurrentProcedureQueryArguments,
) -> None:
    await socket.accept()

    arguments = {}
    arguments.update(query_arguments or {})
    arguments.update(socket.query_params)
    arguments.pop("arguments", None)
    arguments.pop("args", None)

    component = engine.get_component(address)
    if component is None:
        code = 1008  # Set code for policy violation.
        reason = jsonify(Fail(ProcedureComponentNotFoundError()))
        await socket.close(code, reason)
        return

    binding = component.get_procedure_bindings().get(procedure)
    if binding is None:
        code = 1008  # Set code for policy violation.
        reason = jsonify(Fail(ProcedureNotFoundError()))
        await socket.close(code, reason)
        return

    if binding.type == ProcedureType.ACTION and role < UserRole.OPERATOR:
        code = 1008  # Set code for policy violation.
        reason = jsonify(Fail(ProcedureNotPermittedError()))
        await socket.close(code, reason)
        return

    async def read() -> None:
        try:
            while True:
                await socket.receive_text()
        except Exception:
            pass
        finally:
            task_write.cancel()

    async def write() -> None:
        try:
            async for output in component.subscribe(procedure, arguments):
                await socket.send_text(jsonify(output))
        except Exception as exception:
            if isinstance(exception, Failure) and isinstance(exception.error, ProcedureError):
                if not isinstance(exception.error, ProcedureInternalError):
                    code = 1011  # Set code for internal error.
                else:
                    code = 1008  # Set code for policy violation.

                reason = jsonify(Fail(exception.error))
            else:
                code = 1011  # Set code for internal error.
                reason = jsonify(strify(exception)[0:100])

            await socket.close(code, reason)
        finally:
            task_read.cancel()

    task_read = asyncio.create_task(read(), name="read")
    task_write = asyncio.create_task(write(), name="write")

    try:
        await asyncio.gather(task_read, task_write)
    except CancelledError:
        pass
