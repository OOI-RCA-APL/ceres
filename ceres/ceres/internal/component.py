import importlib
import traceback
from typing import (
    Any,
    Collection,
    Mapping,
    Sequence,
    TypeVar,
    cast,
)

from pydantic import (
    BaseModel,
    ValidationError,
    parse_obj_as,
)
from typing_extensions import get_origin

from ..component import Component, ComponentPaths, Job
from ..config import ComponentConfig
from ..data import (
    Name,
)
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
from ..ref import RefType
from ..result import Fail, Ok, Result
from .utilities import (
    dictify,
    is_optional,
    lenient_isinstance,
    lenient_issubclass,
    strify,
)

_ComponentT = TypeVar("_ComponentT", bound=Component)


def load_component_cls(config: ComponentConfig) -> Result[type[Component], ComponentError]:
    if not lenient_isinstance(config.cls, str):
        if not lenient_issubclass(config.cls, Component):
            return Fail(
                ComponentClassInvalidError(
                    message=(
                        f"component class must be a subclass of {Component}, got "
                        f"{strify(config.cls)}"
                    )
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
        match _assign_refs(parsed_parameters, siblings):
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
                message=(
                    f"{strify(component)} has no action named '{job.action}', defined actions are "
                    f"{defined}"
                )
            )

        if job.input is None and (action.input is not None and action.input.required):
            return ComponentJobInvalidError(
                message=(
                    f"missing required input for job '{job.name}', set the job's 'input' to a "
                    "non-none value"
                )
            )

        seen.add(action.name)

        # TODO: Validate job input is correct type.


_ModelT = TypeVar("_ModelT", bound=BaseModel)


def _assign_refs(
    obj: _ModelT,
    values: Mapping[str, object],
    /,
) -> "Result[_ModelT, ComponentReferenceInvalidError]":
    output: dict[str, Any] = dictify(obj)

    def _create_reference_invalid_error(
        reference: Any,
        info: "type[RefType]",
    ) -> ComponentReferenceInvalidError:
        return ComponentReferenceInvalidError(
            message=(
                f"reference to component '{reference}' of type {strify(info.cls)} is "
                f"required and specified by {strify(type(obj))}, but it hasn't loaded yet "
                "failed to load"
            )
        )

    for name, info in obj.__fields__.items():
        outer_type = info.outer_type_
        inner_type = info.type_
        value: Any = getattr(obj, name)

        if lenient_issubclass(outer_type, RefType):
            if lenient_isinstance(value, str):
                component = values.get(value)
            else:
                component = value

            if (
                component is None
                and not is_optional(outer_type)
                and not is_optional(outer_type.cls)
            ):
                return Fail(_create_reference_invalid_error(value, outer_type))

            output[name] = component
            continue

        if lenient_issubclass(inner_type, RefType) and lenient_issubclass(
            get_origin(outer_type) or outer_type, Collection
        ):
            if issubclass(inner_type, RefType):
                components: list[Any] = []

                for element in value:
                    if isinstance(element, str):
                        component = values.get(element)
                    else:
                        component = element

                    if (
                        component is None
                        and not is_optional(inner_type)
                        and not is_optional(inner_type.cls)
                    ):
                        return Fail(_create_reference_invalid_error(element, inner_type))

                    components.append(component)

                output[name] = parse_obj_as(outer_type, components)

    return Ok(type(obj)(**output))
