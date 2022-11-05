import asyncio
import dataclasses
import importlib
import inspect
import traceback
from abc import ABC, abstractmethod
from dataclasses import dataclass
from functools import cache
from logging import Logger
from typing import TYPE_CHECKING, Any, Generic, Mapping, TypeVar
from uuid import UUID

from pydantic import ValidationError, validate_arguments

from ..address import ComponentAddress
from ..component import CompleteComponentContext, Component
from ..config import ComponentConfig, Config, UnitConfig
from ..connection import Connection
from ..driver import Driver
from ..errors import (
    ComponentClassInvalidError,
    ComponentClassNotFoundError,
    ComponentError,
    ComponentInitExceptionError,
    ComponentModuleExceptionError,
    ComponentModuleNotFoundError,
    ComponentParametersInvalidError,
    ComponentReferenceInvalidError,
    ValidationProblem,
)
from ..notifier import Notifier
from ..result import Fail, Ok, Result
from . import logs
from .tasks import Tasklet
from .utilities import frozendict, get_type_annotations, hydrate, object_has_field

if TYPE_CHECKING:
    from .unit import Unit

LoadedComponentT = TypeVar("LoadedComponentT", bound=Component)


def load_component(
    supercls: type[LoadedComponentT],
    config: ComponentConfig,
    context: CompleteComponentContext,
    siblings: Mapping[str, Component],
) -> Result[LoadedComponentT, ComponentError]:
    if not isinstance(config.component, str):
        if not isinstance(config.component, supercls):
            return Fail(
                ComponentClassInvalidError(
                    message=f"component passed in configuration must be an instance of {supercls}, got {config.component}"
                )
            )

        return Ok(config.component)

    try:
        module = importlib.import_module(config.component)
    except Exception as exception:
        if isinstance(exception, ModuleNotFoundError) and exception.name == config.component:
            return Fail(
                ComponentModuleNotFoundError(
                    message=f"component module '{config.component}' was not found"
                )
            )

        return Fail(
            ComponentModuleExceptionError(
                message=f"component module '{config.component}' raised an exception during import",
                traceback=traceback.format_exc(),
            )
        )

    cls: type[LoadedComponentT] | None = None

    # Find the last non-abstract class in the module that is a subclass of the "cls" argument.
    for _, member in inspect.getmembers(module):
        if (
            inspect.isclass(member)
            and not inspect.isabstract(member)
            and member is not supercls
            and issubclass(member, supercls)
        ):
            cls = member

    if cls is None:
        return Fail(
            ComponentClassNotFoundError(
                message=f"component module {module} must contain class a non-abstract subclass of {supercls}"
            )
        )

    parameters_type = cls.get_parameters_type()
    context_type = cls.get_context_type()
    references_type = cls.get_references_type()

    try:
        applied_parameters = hydrate(parameters_type, config.parameters)
    except ValidationError as error:
        return Fail(
            ComponentParametersInvalidError(
                message=f"invalid parameters for {cls}",
                problems=ValidationProblem.extract(error),
            )
        )

    try:
        context_kwargs: dict[str, Any] = {}

        for field in dataclasses.fields(context):
            if object_has_field(context_type, field.name):
                context_kwargs[field.name] = getattr(context, field.name)

        applied_context = context_type(**context_kwargs)
    except Exception:
        return Fail(
            ComponentInitExceptionError(
                message=f"exception raised when creating {context_type} for {cls}",
                traceback=traceback.format_exc(),
            )
        )

    try:
        references_kwargs: dict[str, Any] = {}
        reference_mapping = _get_reference_mapping(references_type)

        for component_alias, component_type in reference_mapping.items():
            if not (name := config.references.get(component_alias)):
                return Fail(
                    ComponentReferenceInvalidError(
                        message=f"reference '{component_alias}' of type {component_type} is specified by {references_type}, but is missing from the component's references configuration",
                    )
                )

            if not (sibling := siblings.get(name)):
                return Fail(
                    ComponentReferenceInvalidError(
                        message=f"reference to component '{name}' of type {component_type} is specified by {references_type}, but it hasn't loaded yet or failed to load"
                    )
                )

            if not isinstance(sibling, component_type):
                return Fail(
                    ComponentReferenceInvalidError(
                        message=f"reference to component '{name}' is specified by {references_type} but component '{name}' is an instance of {type(sibling)}, not {component_type}"
                    )
                )

            references_kwargs[component_alias] = sibling

        applied_references = references_type(**references_kwargs)
    except Exception:
        return Fail(
            ComponentInitExceptionError(
                message=f"exception raised when creating {references_type} for {cls}",
                traceback=traceback.format_exc(),
            )
        )

    try:
        instance = validate_arguments(cls)(
            parameters=applied_parameters,
            context=applied_context,
            references=applied_references,
        )
    except Exception:
        return Fail(
            ComponentInitExceptionError(
                message=f"exception raised when calling __init__() for {cls}",
                traceback=traceback.format_exc(),
            )
        )

    return Ok(instance)


@dataclass(kw_only=True, frozen=True)
class ComponentHandleContext:
    id: UUID
    address: ComponentAddress
    root_config: Config
    unit_config: UnitConfig
    component_config: ComponentConfig
    unit: "Unit"

    def __post_init__(self) -> None:
        assert self.root_config.get_component(self.address)
        assert self.unit_config in self.root_config.units
        assert self.component_config in self.unit_config.components


ComponentT = TypeVar("ComponentT", bound=Component, covariant=True)


class ComponentHandle(Generic[ComponentT], Tasklet, ABC):
    def __init__(self, context: ComponentHandleContext) -> None:
        self._context = context
        self._instance: ComponentT | None = None

    @classmethod
    @abstractmethod
    def get_component_type(cls) -> type[ComponentT]:
        ...

    @property
    def id(self) -> UUID:
        return self._context.id

    @property
    def address(self) -> ComponentAddress:
        return self._context.address

    @property
    def config(self) -> ComponentConfig:
        return self._context.component_config

    @property
    def instance(self) -> ComponentT | None:
        return self._instance

    @property
    def logger(self) -> Logger:
        return logs.get(str(self._context.address))

    async def _tasklet_run(self) -> None:
        if not self.instance:
            return

        await asyncio.gather(
            self._process_component(),
            self._process_events(),
        )

    async def _process_component(self) -> None:
        if not self.instance:
            return

        await self.instance.run()

    async def _process_events(self) -> None:
        if not self.instance:
            return

        async for event in self.instance.event_stream:
            await self._context.unit.dispatch_event(event)

    async def _tasklet_stop(self) -> None:
        if not self.instance:
            return

        await self.instance.stop()

    async def load(self) -> Result[ComponentT, ComponentError]:
        if self.instance:
            return Ok(self.instance)

        match load_component(
            self.get_component_type(),
            self.config,
            CompleteComponentContext(
                id=self.id,
                address=self.address,
                root_config=self._context.root_config,
                unit_config=self._context.unit_config,
                component_config=self.config,
                database=self._context.unit.database,
                entities=self._context.unit.database.entities,
            ),
            {
                component.address.name: component.instance
                for component in self._context.unit.components
                if component.instance
            },
        ):
            case Ok(instance):
                self._instance = instance
                return Ok(instance)
            case fail:
                return fail


def _get_reference_mapping(
    references: Component.References | type[Component.References],
) -> Mapping[str, type["Component"]]:
    mapping: dict[str, type[Component]] = {}
    annotations = get_type_annotations(references)

    for name, annotation in annotations.items():
        if isinstance(annotation, type) and issubclass(annotation, Component):
            mapping[name] = annotation

    return frozendict(mapping)


if not TYPE_CHECKING:
    _get_reference_mapping = cache(_get_reference_mapping)


class ConnectionHandle(ComponentHandle[Connection]):
    @classmethod
    def get_component_type(cls) -> type[Connection]:
        return Connection


class DriverHandle(ComponentHandle[Driver]):
    @classmethod
    def get_component_type(cls) -> type[Driver]:
        return Driver


class NotifierHandle(ComponentHandle[Notifier]):
    @classmethod
    def get_component_type(cls) -> type[Notifier]:
        return Notifier
