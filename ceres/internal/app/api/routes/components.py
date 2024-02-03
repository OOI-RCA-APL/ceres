import asyncio
import json
import traceback
from asyncio import CancelledError
from typing import Any, Mapping, Sequence

from fastapi import (
    APIRouter,
    Body,
    HTTPException,
    Request,
    WebSocket,
)
from starlette.status import (
    HTTP_400_BAD_REQUEST,
    HTTP_404_NOT_FOUND,
)

from ceres.address import Address
from ceres.component import Component, ProcedureBinding
from ceres.config import ComponentConfig
from ceres.data import ImmutableDataObject, Name, jsonify
from ceres.errors import (
    ProcedureComponentDoesNotExistError,
    ProcedureError,
    ProcedureInternalError,
)
from ceres.exceptions import ProcedureException
from ceres.internal.app.shared import CurrentEngine, CurrentProcedureQueryArguments
from ceres.internal.utilities import StrEnum, strify
from ceres.result import Fail, Ok, Result


class ComponentRole(StrEnum):
    CONNECTION = "connection"
    INTERFACE = "interface"


class ComponentInfo(ImmutableDataObject):
    name: Name
    address: Address
    components: Sequence["ComponentInfo"]
    config: ComponentConfig
    roles: Sequence[ComponentRole]
    procedures: Sequence[ProcedureBinding]


ComponentInfo.model_rebuild()

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


@router.get("/{address}")
async def get_component(engine: CurrentEngine, address: Address) -> ComponentInfo:
    component_config = engine.config.get_component(address)
    if component_config is not None and type(component_config) is not ComponentConfig:
        component_config = ComponentConfig.model_validate(
            {
                "name": component_config.name,
                "class": component_config.cls,
                "arguments": component_config.arguments,
                "components": component_config.components,
            }
        )

    component_cls = engine.config.get_component_cls(address)
    if component_config is None or component_cls is None:
        raise HTTPException(HTTP_404_NOT_FOUND)

    children: list[ComponentInfo] = []
    for child_config in component_config.components:
        children.append(await get_component(engine, address / child_config.name))

    try:
        info = ComponentInfo(
            name=component_config.name,
            address=address,
            config=component_config,
            roles=_get_component_roles(component_cls),
            procedures=list(component_cls.get_procedure_bindings().values()),
            components=children,
        )
        return info
    except Exception:
        traceback.print_exc()
        raise


@router.api_route(
    "/{address}/procedures/{procedure}/call",
    methods=["GET", "POST"],
    tags=["procedures"],
)
async def call(
    request: Request,
    engine: CurrentEngine,
    address: Address,
    procedure: Name,
    query_arguments: CurrentProcedureQueryArguments,
    body_arguments: Mapping[Name, object] | None = Body(None),
) -> Result[Any | None, ProcedureError]:
    if isinstance(query_arguments, str):
        try:
            query_arguments = json.loads(query_arguments)
        except Exception:
            raise HTTPException(
                HTTP_400_BAD_REQUEST,
                "'arguments' query parameter must be unspecified, null or a valid JSON object",
            )

    if not isinstance(query_arguments, Mapping | None):
        raise HTTPException(
            HTTP_400_BAD_REQUEST,
            "'arguments' query parameter must be unspecified, null or a valid JSON object",
        )

    arguments = {}
    arguments.update(query_arguments or {})
    arguments.update(body_arguments or {})
    arguments.update(request.query_params)
    arguments.pop("arguments", None)
    arguments.pop("args", None)

    try:
        component = engine.get_component(address)
        if component is None:
            return Fail(ProcedureComponentDoesNotExistError())
        return Ok(await component.call(procedure, arguments))
    except ProcedureException as exception:
        return Fail(exception.error)


@router.websocket("/{address}/procedures/{procedure}/subscribe")
async def subscribe(
    socket: WebSocket,
    engine: CurrentEngine,
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
        reason = jsonify(Fail(ProcedureComponentDoesNotExistError()))
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
            if isinstance(exception, ProcedureException):
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
