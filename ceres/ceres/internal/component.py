import collections.abc
import importlib
import traceback
from dataclasses import dataclass
from types import MappingProxyType
from typing import Any, Mapping, Sequence, TypeVar, cast, get_args, get_origin

from pydantic import ValidationError, parse_obj_as

from ..component import Component, ComponentPaths
from ..config import ComponentConfig, JobConfig
from ..data import Name
from ..errors import (
    ComponentClassInvalidError,
    ComponentClassNotFoundError,
    ComponentError,
    ComponentInitExceptionError,
    ComponentJobInvalidError,
    ComponentModuleExceptionError,
    ComponentModuleNotFoundError,
    ComponentParametersInvalidError,
    ComponentReferenceInvalidError,
    ValidationProblem,
)
from ..result import Fail, Ok, Result
from .utilities import cached, lenient_isinstance, lenient_issubclass, strify

_ComponentT = TypeVar("_ComponentT", bound=Component)


def load_component_cls(config: ComponentConfig) -> Result[type[Component], ComponentError]:
    if not lenient_isinstance(config.cls, str):
        if not lenient_issubclass(config.cls, Component):
            return Fail(
                ComponentClassInvalidError(
                    message=f"component class must be a subclass of {Component}, got {strify(config.cls)}"
                )
            )

        return Ok(config.cls)

    last_dot_index = config.cls.rindex(".")
    cls_module_path = config.cls[:last_dot_index]
    cls_name = config.cls[last_dot_index + 1 :]

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
                message=f"component module {module} does not contain component class '{cls_name}'"
            )
        )

    if not lenient_issubclass(cls, Component):
        return Fail(
            ComponentClassInvalidError(message=f"{strify(cls)} must be subclass of {Component}")
        )

    return Ok(cls)


def load_component(
    config: ComponentConfig,
    *,
    name: Name,
    paths: ComponentPaths,
    siblings: Mapping[Name, Component],
) -> Result[Component, ComponentError]:
    match load_component_cls(config):
        case Ok(cls):
            pass
        case Fail(error):
            return Fail(error)

    if not isinstance(config.cls, str):
        return Ok(cast(_ComponentT, config.cls))

    parameters_type = cls.get_parameters_type()
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
        references_kwargs: dict[str, Any] = {}
        reference_mapping = _get_reference_mapping(references_type)

        for alias, reference_definition in reference_mapping.items():
            if (
                component_names := config.references.get(alias)
            ) is None and reference_definition.required:
                return Fail(
                    ComponentReferenceInvalidError(
                        message=f"reference '{alias}' of type {strify(reference_definition.cls)} is required by {strify(references_type)}, but is missing from the component's references configuration",
                    )
                )

            if component_names is None:
                component_names = []
            elif isinstance(component_names, str):
                component_names = [component_names]

            referenced_components: list[Component] = []

            for component_name in component_names:
                if not (referenced_component := siblings.get(component_name)):
                    return Fail(
                        ComponentReferenceInvalidError(
                            message=f"reference to component '{component_name}' of type {strify(reference_definition.cls)} is specified by {strify(references_type)}, but it hasn't loaded yet or failed to load"
                        )
                    )

                if not isinstance(referenced_component, reference_definition.cls):
                    return Fail(
                        ComponentReferenceInvalidError(
                            message=f"reference to component '{component_name}' is specified by {strify(references_type)} but component '{component_name}' is an instance of {strify(type(referenced_component))}, not {strify(reference_definition.cls)}"
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

    if config.jobs:
        error = validate_jobs(cls, config.jobs)
        if error is not None:
            return Fail(error)

    applied_jobs = config.jobs

    try:
        instance = cls(
            name=name,
            paths=paths,
            parameters=applied_parameters,
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


def validate_jobs(
    component: Component | type[Component],
    jobs: Sequence[JobConfig],
) -> ComponentJobInvalidError | None:
    seen: set[str] = set()

    for job in jobs:
        if job.name in seen:
            return ComponentJobInvalidError(
                message=f"duplicate job '{job.name}', get the job a unique 'name' value"
            )

        action = component.get_action_bindings().get(job.action)
        if action is None:
            defined = sorted(component.get_action_bindings().keys())
            return ComponentJobInvalidError(
                message=f"{strify(component)} has no action named '{job.action}', defined actions are {defined}"
            )

        if job.input is None and (action.input is not None and action.input.required):
            return ComponentJobInvalidError(
                message=f"missing required input for job '{job.name}', set the job's 'input' to a non-none value"
            )

        seen.add(action.name)

        # TODO: Validate job input is correct type.
