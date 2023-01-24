import asyncio
import collections.abc
import importlib
import traceback
from dataclasses import dataclass
from logging import Logger
from pathlib import Path
from types import MappingProxyType
from typing import (
    TYPE_CHECKING,
    Any,
    Mapping,
    Sequence,
    TypeVar,
    cast,
    final,
    get_args,
    get_origin,
)
from uuid import UUID

from pydantic import ValidationError, parse_obj_as, validate_arguments

from ..address import GlobalComponentAddress
from ..component import CompleteContext, Component, ComponentPaths
from ..config import ComponentConfig, ComponentRoleKind, Config, UnitConfig
from ..connection import Connection
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
from ..events import Event
from ..result import Fail, Ok, Result
from ..stream import Stream
from . import logs
from .tasklet import Tasklet
from .utilities import cached, get_field_value, has_field, lenient_issubclass, strify

if TYPE_CHECKING:
    from ..unit import Unit
else:
    Unit = "Unit"

_ComponentT = TypeVar("_ComponentT", bound=Component)


def load_component_cls(config: ComponentConfig) -> Result[type[Component], ComponentError]:
    if not isinstance(config.component, str):
        missing = _get_missing_component_base_classes(config.component, config.roles)
        return Fail(
            ComponentClassInvalidError(
                message=f"component passed in configuration must be a subclass or instance of {strify(missing)}, got {strify(config.component)}"
            )
        )

    last_dot_index = config.component.rindex(".")
    cls_module_path = config.component[:last_dot_index]
    cls_name = config.component[last_dot_index + 1 :]

    try:
        module = importlib.import_module(cls_module_path)
    except Exception as exception:
        if isinstance(exception, ModuleNotFoundError) and exception.name == cls_module_path:
            return Fail(
                ComponentModuleNotFoundError(
                    message=f"component module '{cls_module_path}' was not found"
                )
            )

        return Fail(
            ComponentModuleExceptionError(
                message=f"component module '{cls_module_path}' raised an exception during import",
                traceback=traceback.format_exception(exception),
            )
        )

    cls: type[_ComponentT] = getattr(module, cls_name, None)  # type: ignore
    if cls is None:
        return Fail(
            ComponentClassNotFoundError(
                message=f"component module {module} does not contain component class {cls_name}"
            )
        )

    missing = _get_missing_component_base_classes(cls, config.roles)
    if missing:
        return Fail(
            ComponentClassInvalidError(
                message=f"component {strify(cls)} must be subclass of {strify(missing)}"
            )
        )

    return Ok(cls)


def load_component(
    config: ComponentConfig,
    context: CompleteContext,
    siblings: Mapping[str, Component],
) -> Result[Component, ComponentError]:
    if not isinstance(config.component, str | type):
        if not _get_missing_component_base_classes(type(config.component), config.roles):
            return Ok(config.component)

    match load_component_cls(config):
        case Ok(cls):
            pass
        case Fail(error):
            return Fail(error)

    if not isinstance(config.component, str):
        return Ok(cast(_ComponentT, config.component))

    parameters_type = cls.get_parameters_type()
    context_type = cls.get_context_type()
    references_type = cls.get_references_type()

    try:
        applied_parameters = parse_obj_as(parameters_type, config.parameters)
    except ValidationError as error:
        return Fail(
            ComponentParametersInvalidError(
                message=f"invalid parameters for {strify(cls)}",
                problems=ValidationProblem.extract(error),
            )
        )

    try:
        context_kwargs: dict[str, Any] = {}

        for field in context.__fields__.values():
            if has_field(context_type, field.name):
                context_kwargs[field.name] = get_field_value(context, field.name)

        applied_context = context_type(**context_kwargs)
    except Exception as exception:
        return Fail(
            ComponentInitExceptionError(
                message=f"exception raised when creating {strify(context_type)} for {strify(cls)}",
                traceback=traceback.format_exception(exception),
            )
        )

    try:
        references_kwargs: dict[str, Any] = {}
        reference_mapping = _get_reference_mapping(references_type)

        for alias, reference_definition in reference_mapping.items():
            if (names := config.references.get(alias)) is None and reference_definition.required:
                return Fail(
                    ComponentReferenceInvalidError(
                        message=f"reference '{alias}' of type {strify(reference_definition.cls)} is required by {strify(references_type)}, but is missing from the component's references configuration",
                    )
                )

            if names is None:
                names = []
            elif isinstance(names, str):
                names = [names]

            referenced_components: list[Component] = []

            for name in names:
                if not (referenced_component := siblings.get(name)):
                    return Fail(
                        ComponentReferenceInvalidError(
                            message=f"reference to component '{name}' of type {strify(reference_definition)} is specified by {strify(references_type)}, but it hasn't loaded yet or failed to load"
                        )
                    )

                if not isinstance(referenced_component, reference_definition.cls):
                    return Fail(
                        ComponentReferenceInvalidError(
                            message=f"reference to component '{name}' is specified by {strify(references_type)} but component '{name}' is an instance of {strify(type(referenced_component))}, not {strify(reference_definition)}"
                        )
                    )

                referenced_components.append(referenced_component)

            if reference_definition.multiple:
                applied_reference = referenced_components
            elif len(referenced_components) == 0:
                applied_reference = None
            else:
                applied_reference = referenced_components[0]

            references_kwargs[alias] = applied_reference

        applied_references = references_type(**references_kwargs)
    except Exception as exception:
        return Fail(
            ComponentInitExceptionError(
                message=f"exception raised when creating {strify(references_type)} for {strify(cls)}",
                traceback=traceback.format_exception(exception),
            )
        )

    applied_jobs = config.jobs

    try:
        instance = validate_arguments(cls)(
            parameters=applied_parameters,
            context=applied_context,
            references=applied_references,
            jobs=applied_jobs,
        )
    except Exception as exception:
        return Fail(
            ComponentInitExceptionError(
                message=f"exception raised when calling __init__() for {strify(cls)}",
                traceback=traceback.format_exception(exception),
            )
        )

    return Ok(instance)


@dataclass(kw_only=True, frozen=True)
class ComponentHandleContext:
    id: UUID
    address: GlobalComponentAddress
    root_config: Config
    unit_config: UnitConfig
    component_config: ComponentConfig
    unit: Unit
    forward: Sequence[Stream[Event]]

    def __post_init__(self) -> None:
        assert self.root_config.get_component(self.address)
        assert self.unit_config in self.root_config.units
        assert self.component_config in self.unit_config.components


@final
class ComponentHandle(Tasklet):
    def __init__(self, context: ComponentHandleContext) -> None:
        self.__context = context
        self.__instance: Component | None = None

    @property
    def id(self) -> UUID:
        return self.__context.id

    @property
    def address(self) -> GlobalComponentAddress:
        return self.__context.address

    @property
    def config(self) -> ComponentConfig:
        return self.__context.component_config

    @property
    def instance(self) -> Component | None:
        return self.__instance

    @property
    def logger(self) -> Logger:
        return logs.get(str(self.__context.address))

    async def __run__(self) -> None:
        if self.instance is None:
            return

        await asyncio.gather(
            self.instance.run(),
            self.__process_events(),
        )

    async def __process_events(self) -> None:
        if self.instance is None:
            return

        async for event in self.instance.events:
            for stream in self.__context.forward:
                stream.put(event)

    async def __stop__(self) -> None:
        if self.instance is None:
            return

        await self.instance.stop()

    async def load(self) -> Result[Component, ComponentError]:
        if self.instance is not None:
            return Ok(self.instance)

        match load_component(
            self.config,
            CompleteContext(
                id=self.id,
                address=self.address,
                root_config=self.__context.root_config,
                unit_config=self.__context.unit_config,
                component_config=self.config,
                database=self.__context.unit.database,
                paths=ComponentPaths(
                    unit=self.__context.unit.paths.local,
                    component=self.__context.unit.paths.local.subdir(
                        Path("components") / self.config.name
                    ),
                    data=self.__context.unit.paths.data,
                ),
            ),
            {
                name: component.instance
                for name, component in self.__context.unit.components.items()
                if component.instance
            },
        ):
            case Ok(instance):
                self.__instance = instance
                return Ok(instance)
            case fail:
                return fail


@dataclass(kw_only=True, frozen=True)
class _ReferenceDefinition:
    cls: type[Component]
    required: bool
    multiple: bool


@cached
def _get_reference_mapping(
    references: Component.References | type[Component.References],
) -> Mapping[str, _ReferenceDefinition]:
    mapping: dict[str, _ReferenceDefinition] = {}

    for field in references.__fields__.values():
        annotation = field.annotation
        if get_origin(annotation) in (collections.abc.Sequence, Sequence, list, tuple, set):
            mapping[field.name] = _ReferenceDefinition(
                cls=get_args(annotation)[0],
                multiple=True,
                required=field.required == True,
            )
        else:
            mapping[field.name] = _ReferenceDefinition(
                cls=annotation,  # type: ignore
                multiple=False,
                required=field.required == True,
            )

    return MappingProxyType(mapping)


def _get_component_role_cls(role: ComponentRoleKind) -> type[Component]:
    match role:
        case ComponentRoleKind.CONNECTION:
            return Connection

    raise ValueError(role)


def _get_required_component_base_classes(
    roles: Sequence[ComponentRoleKind],
) -> tuple[type[Component], ...]:
    classes = [Component]

    for role in roles:
        cls = _get_component_role_cls(role)
        if cls not in classes:
            classes.append(cls)

    return tuple(classes)


def _get_missing_component_base_classes(
    component: type[Component] | Component,
    roles: Sequence[ComponentRoleKind],
) -> Sequence[type[Component]]:
    if not isinstance(component, type):
        component = type(component)

    bases = _get_required_component_base_classes(roles)
    return [base for base in bases if not lenient_issubclass(component, base)]
