from __future__ import annotations

import asyncio
import dataclasses
import importlib
import inspect
import traceback
from abc import ABC, abstractmethod
from dataclasses import dataclass
from logging import Logger
from typing import Any, Generic, Mapping, TypeVar
from uuid import UUID

from pydantic import ValidationError, validate_arguments

from ..address import ComponentAddress
from ..component import (
    Component,
    ComponentContext,
    ComponentInterface,
    ComponentParameters,
    FullComponentContext,
)
from ..config import ComponentConfig, Config
from ..errors import (
    ComponentClassInvalidError,
    ComponentClassNotFoundError,
    ComponentError,
    ComponentInitExceptionError,
    ComponentModuleExceptionError,
    ComponentModuleNotFoundError,
    ComponentParametersInvalidError,
    ValidationProblem,
)
from ..protocols import GlobalUnitProtocol
from ..result import Fail, Ok, Result
from . import logs
from .database.manager import DatabaseManager
from .tasks import Tasklet
from .utilities import hydrate, object_has_field, unwrap

ComponentT = TypeVar("ComponentT", bound=Component, covariant=True)


def load_component(
    cls: type[ComponentT],
    source: str | object,
    parameters: Mapping[str, Any],
    context: FullComponentContext,
) -> Result[ComponentT, ComponentError]:
    if not isinstance(source, str):
        if not isinstance(source, cls):
            return Fail(
                ComponentClassInvalidError(
                    message=f"component passed in configuration must be an instance of {cls}, got {source}"
                )
            )

        return Ok(source)

    try:
        module = importlib.import_module(source)
    except Exception as exception:
        if isinstance(exception, ModuleNotFoundError) and exception.name == source:
            return Fail(
                ComponentModuleNotFoundError(message=f"component module '{source}' was not found")
            )

        return Fail(
            ComponentModuleExceptionError(
                message=f"component module '{source}' raised an exception during import",
                traceback=traceback.format_exc(),
            )
        )

    target_cls: type[ComponentT] | None = None

    # Find the last non-abstract class in the module that is a subclass of the "cls" argument.
    for _, member in inspect.getmembers(module):
        if (
            inspect.isclass(member)
            and not inspect.isabstract(member)
            and member is not cls
            and issubclass(member, cls)
        ):
            target_cls = member

    if target_cls is None:
        return Fail(
            ComponentClassNotFoundError(
                message=f"component module {module} must contain class a non-abstract subclass of {cls}"
            )
        )

    signature = inspect.signature(target_cls)

    if len(signature.parameters) != 2:
        return Fail(
            ComponentClassInvalidError(
                message=f"{target_cls.__init__} must match signature: def __init__{inspect.signature(Component.__init__)}"
            )
        )

    parameters_type = target_cls.get_parameters_type()
    context_type = target_cls.get_context_type()

    if not issubclass(parameters_type, ComponentParameters):
        return Fail(
            ComponentClassInvalidError(
                message=f"first positional parameter of {target_cls.__init__} must be a subclass of {ComponentParameters}"
            )
        )

    if not issubclass(context_type, ComponentContext):
        return Fail(
            ComponentClassInvalidError(
                message=f"second positional pararmeter {target_cls.__init__} must be a subclass of {ComponentContext}"
            )
        )

    __init__ = validate_arguments(target_cls.__init__)
    instance = target_cls.__new__(target_cls)

    arguments: list[Any] = []
    arguments.append(instance)

    try:
        hydrated_parameters = hydrate(parameters_type, parameters)
    except ValidationError as error:
        return Fail(
            ComponentParametersInvalidError(
                message=f"invalid parameters for {target_cls}",
                problems=ValidationProblem.extract(error),
            )
        )

    arguments.append(hydrated_parameters)

    context_arguments: dict[str, Any] = {}

    for field in dataclasses.fields(context):
        if object_has_field(context_type, field.name):
            context_arguments[field.name] = getattr(context, field.name)

    arguments.append(context_type(**context_arguments))

    try:
        __init__.validate(*arguments)  # type: ignore
    except ValidationError as error:
        return Fail(
            ComponentParametersInvalidError(
                message=f"invalid arguments for {target_cls}",
                problems=ValidationProblem.extract(error),
            )
        )

    try:
        __init__(*arguments)
    except Exception:
        return Fail(
            ComponentInitExceptionError(
                message=f"exception raised when calling __init__() for {target_cls}",
                traceback=traceback.format_exc(),
            )
        )

    return Ok(instance)


@dataclass(kw_only=True, frozen=True)
class ComponentHandleContext:
    id: UUID
    address: ComponentAddress
    config: Config
    unit: GlobalUnitProtocol
    database: DatabaseManager

    def __post_init__(self) -> None:
        if not self.config.get_component(self.address):
            raise ValueError(f"component {self.address} is not defined in configuration")


class ComponentHandle(Generic[ComponentT], Tasklet, ABC):
    def __init__(self, context: ComponentHandleContext) -> None:
        self._context = context
        self._instance: ComponentT | None = None

    @classmethod
    @abstractmethod
    def _get_component_type(cls) -> type[ComponentT]:
        raise NotImplementedError()

    @property
    def id(self) -> UUID:
        return self._context.id

    @property
    def address(self) -> ComponentAddress:
        return self._context.address

    @property
    def config(self) -> ComponentConfig:
        return unwrap(self._context.config.get_component(self._context.address))

    @property
    def instance(self) -> ComponentT | None:
        return self._instance

    @property
    def logger(self) -> Logger:
        return logs.get(str(self._context.address))

    async def _tasklet_run(self) -> None:
        if not self._instance:
            return

        await asyncio.gather(
            self._process_component(),
            self._process_events(),
            self._process_alerts(),
        )

    async def _process_component(self) -> None:
        if self._instance:
            await self._instance.run()

    async def _process_events(self) -> None:
        while True:
            if self._instance:
                async for event in self._instance.event_stream:
                    await self._context.unit.handle_event(event)
            else:
                await asyncio.sleep(1)

    async def _process_alerts(self) -> None:
        while True:
            if self._instance:
                async for alert in self._instance.alert_stream:
                    await self._context.unit.handle_alert(alert)
            else:
                await asyncio.sleep(1)

    async def _tasklet_stop(self) -> None:
        pass

    async def load(self) -> Result[ComponentT, ComponentError]:
        if self._instance:
            return Ok(self._instance)

        match load_component(
            self._get_component_type(),
            self.config.component,
            self.config.parameters,
            FullComponentContext(
                id=self._context.id,
                address=self._context.address,
                references=self.config.references,
                root_config=self._context.config,
                unit_config=unwrap(self._context.config.get_unit(self._context.address.unit)),
                component_config=self.config,
                users=self._context.config.users,
                units=self._context.config.units,
                database=self._context.database,
            ),
        ):
            case Ok(instance):
                self._instance = instance
                return Ok(instance)
            case fail:
                return fail


ComponentHandleInterface = ComponentHandle[ComponentInterface]
