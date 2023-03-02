import importlib
import traceback
from typing import Mapping, Sequence, TypeVar, cast

from pydantic import ValidationError, parse_obj_as

from ..component import Component, ComponentPaths, Job
from ..config import ComponentConfig
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
    ValidationProblem,
)
from ..result import Fail, Ok, Result
from .utilities import lenient_isinstance, lenient_issubclass, strify

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

    try:
        parsed_parameters = parse_obj_as(parameters_type, config.parameters)
        match parsed_parameters.assign_references(siblings):
            case Ok(applied_parameters):
                pass
            case fail:
                return fail
    except ValidationError as error:
        return Fail(
            ComponentParametersInvalidError(
                message=f"invalid parameters for {strify(cls)}",
                problems=ValidationProblem.extract(error),
            )
        )

    try:
        instance = cls(
            name=name,
            paths=paths,
            parameters=applied_parameters,
        )
    except ValidationError as error:
        return Fail(
            ComponentParametersInvalidError(
                message=f"invalid parameters for {strify(cls)}",
                problems=ValidationProblem.extract(error),
            )
        )
    except Exception as exception:
        return Fail(
            ComponentInitExceptionError(
                message=f"exception raised when calling __init__() for {strify(cls)}",
                traceback=traceback.format_exception(exception),
            )
        )

    return Ok(instance)


def validate_jobs(
    component: Component | type[Component],
    jobs: Sequence[Job],
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
