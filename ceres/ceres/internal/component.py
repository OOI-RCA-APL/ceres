import asyncio
import dataclasses
import importlib
import inspect
import traceback
from abc import ABC, abstractmethod
from dataclasses import dataclass
from functools import cache
from logging import Logger
from typing import TYPE_CHECKING, Any, Generic, Mapping, TypeVar, get_type_hints
from uuid import UUID

from pydantic import ValidationError, validate_arguments

from ..address import ComponentAddress
from ..component import (
    CompleteComponentContext,
    Component,
    ComponentInterface,
    ComponentReferences,
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
    ComponentReferenceInvalidError,
    ValidationProblem,
)
from ..result import Fail, Ok, Result
from . import logs
from .database.manager import DatabaseManager
from .tasks import Tasklet
from .utilities import frozendict, hydrate, object_has_field, unwrap

if TYPE_CHECKING:
    from .unit import Unit

ComponentT = TypeVar("ComponentT", bound=Component, covariant=True)


def load_component(
    cls: type[ComponentT],
    config: ComponentConfig,
    context: CompleteComponentContext,
    siblings: Mapping[str, ComponentInterface],
) -> Result[ComponentT, ComponentError]:
    if not isinstance(config.component, str):
        if not isinstance(config.component, cls):
            return Fail(
                ComponentClassInvalidError(
                    message=f"component passed in configuration must be an instance of {cls}, got {config.component}"
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

    __init__ = validate_arguments(target_cls.__init__)
    instance = target_cls.__new__(target_cls)

    parameters_type = target_cls.get_parameters_type()
    context_type = target_cls.get_context_type()
    references_type = target_cls.get_references_type()

    try:
        applied_parameters = hydrate(parameters_type, config.parameters)
    except ValidationError as error:
        return Fail(
            ComponentParametersInvalidError(
                message=f"invalid parameters for {target_cls}",
                problems=ValidationProblem.extract(error),
            )
        )

    try:
        context_arguments: dict[str, Any] = {}

        for field in dataclasses.fields(context):
            if object_has_field(context_type, field.name):
                context_arguments[field.name] = getattr(context, field.name)

        applied_context = context_type(**context_arguments)
    except Exception:
        return Fail(
            ComponentInitExceptionError(
                message=f"exception raised when creating {context_type} for {target_cls}",
                traceback=traceback.format_exc(),
            )
        )

    try:
        references_arguments: dict[str, Any] = {}
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

            references_arguments[component_alias] = sibling

        applied_references = references_type(**references_arguments)
    except Exception:
        return Fail(
            ComponentInitExceptionError(
                message=f"exception raised when creating {references_type} for {target_cls}",
                traceback=traceback.format_exc(),
            )
        )

    applied_arguments = (instance, applied_parameters, applied_context, applied_references)

    try:
        __init__(*applied_arguments)  # type: ignore
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
    unit: "Unit"
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
        ...

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
        if not self.instance:
            return

        await asyncio.gather(
            self._process_component(),
            self._process_events(),
            self._process_alerts(),
        )

    async def _process_component(self) -> None:
        if not self.instance:
            return

        await self.instance.run()

    async def _process_events(self) -> None:
        if not self.instance:
            return

        async for event in self.instance.event_stream:
            await self._context.unit.handle_event(event)

    async def _process_alerts(self) -> None:
        if not self.instance:
            return

        async for alert in self.instance.alert_stream:
            await self._context.unit.handle_alert(alert)

    async def _tasklet_stop(self) -> None:
        pass

    async def load(self) -> Result[ComponentT, ComponentError]:
        if self.instance:
            return Ok(self.instance)

        match load_component(
            self._get_component_type(),
            self.config,
            CompleteComponentContext(
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


ComponentHandleInterface = ComponentHandle[ComponentInterface]


def _get_reference_mapping(
    references: ComponentReferences | type[ComponentReferences],
) -> Mapping[str, type["ComponentInterface"]]:
    mapping: dict[str, type[ComponentInterface]] = {}
    hints = get_type_hints(references)

    for name, hint in hints.items():
        if isinstance(hint, type) and issubclass(hint, Component):
            mapping[name] = hint

    return frozendict(mapping)


if not TYPE_CHECKING:
    _get_reference_mapping = cache(_get_reference_mapping)
