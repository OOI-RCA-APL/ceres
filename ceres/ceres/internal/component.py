from __future__ import annotations

import importlib
import inspect
import traceback
from abc import ABC, abstractmethod
from dataclasses import dataclass
from logging import Logger
from typing import Any, Generic, Mapping, TypeVar
from uuid import UUID

from pydantic import ValidationError, validate_arguments

from ..alert import Alert, AlertLevel, RawAlertLevel
from ..component import Component, ComponentContext
from ..config import ComponentConfig, Config
from ..errors import (
    ComponentClassInvalidError,
    ComponentError,
    ComponentInitExceptionError,
    ComponentModuleExceptionError,
    ComponentModuleNotFoundError,
    ComponentParametersInvalidError,
    ValidationProblem,
)
from ..path import ComponentPath
from ..protocols import GlobalUnitProtocol
from ..result import Fail, Ok, Result
from ..scheduler import Scheduler
from . import logs
from .database.manager import DatabaseManager
from .tasks import Tasklet
from .utilities import get_now, simplify, unwrap

ComponentT = TypeVar("ComponentT", bound=Component, covariant=True)


def load_component(
    cls: type[ComponentT],
    source: str | object,
    parameters: Mapping[str, Any],
    context: ComponentContext,
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
            ComponentClassInvalidError(
                message=f"component module {module} must contain class a non-abstract subclass of {cls}"
            )
        )

    signature = inspect.signature(target_cls)
    __init__ = validate_arguments(target_cls.__init__)
    instance = target_cls.__new__(target_cls)

    args: list[Any] = []
    args.append(instance)

    if len(signature.parameters) > 0:
        args.append(simplify(parameters))
        if len(signature.parameters) > 1:
            args.append(simplify(context))

    try:
        __init__.validate(*args)  # type: ignore
    except ValidationError as error:
        return Fail(
            ComponentParametersInvalidError(
                message=f"invalid parameters for {target_cls}",
                problems=ValidationProblem.extract(error),
            )
        )

    try:
        __init__(*args)
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
    path: ComponentPath
    config: Config
    unit: GlobalUnitProtocol
    database: DatabaseManager

    def __post_init__(self) -> None:
        if not self.config.get_component(self.path):
            raise ValueError(f"component {self.path} is not defined in configuration")


ComponentHandleContextT = TypeVar(
    "ComponentHandleContextT",
    bound=ComponentHandleContext,
    covariant=True,
)
ComponentContextT = TypeVar(
    "ComponentContextT",
    bound=ComponentContext,
    covariant=True,
)


class ComponentHandle(
    Generic[
        ComponentHandleContextT,
        ComponentT,
        ComponentContextT,
    ],
    Tasklet,
    ABC,
):
    def __init__(self, context: ComponentHandleContextT) -> None:
        self._context = context
        self._instance: ComponentT | None = None
        self._scheduler = Scheduler()

    @property
    def id(self) -> UUID:
        return self._context.id

    @property
    def path(self) -> ComponentPath:
        return self._context.path

    @property
    def config(self) -> ComponentConfig:
        return unwrap(self._context.config.get_component(self._context.path))

    @property
    def instance(self) -> ComponentT | None:
        return self._instance

    @property
    def scheduler(self) -> Scheduler:
        return self._scheduler

    @property
    def logger(self) -> Logger:
        return logs.get(str(self._context.path))

    async def _tasklet_run(self) -> None:
        self._scheduler.start()

    async def _tasklet_stop(self) -> None:
        self._scheduler.stop()

    @classmethod
    @abstractmethod
    def _get_component_type(cls) -> type[ComponentT]:
        raise NotImplementedError()

    @abstractmethod
    def _get_component_context(self) -> ComponentContextT:
        raise NotImplementedError()

    async def load(self) -> Result[ComponentT, ComponentError]:
        if self._instance:
            return Ok(self._instance)

        match load_component(
            self._get_component_type(),
            self.config.component,
            self.config.parameters,
            self._get_component_context(),
        ):
            case Ok(instance):
                self._instance = instance
                return Ok(instance)
            case fail:
                return fail

    async def alert(
        self,
        level: AlertLevel | RawAlertLevel,
        kind: str,
        info: dict[str, Any] | None = None,
    ) -> Alert:
        alert = Alert(
            origin_id=self._context.id,
            timestamp=get_now(),
            level=AlertLevel.create_from(level),
            kind=kind,
            info=info or {},
        )

        await self._context.unit.alert(alert)
        return alert
