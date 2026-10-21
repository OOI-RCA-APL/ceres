from typing import TYPE_CHECKING, Self
from uuid import UUID

from pydantic import model_validator

from ceres.__internal__.app.handlers.components import (
    ExporterInfo,
    _describe_exporters,
    _resolve_component,
)
from ceres.__internal__.app.shared import get_component_access
from ceres.component import Component, ComponentAccessLevel
from ceres.data import DataObject, DateTime
from ceres.error import (
    NotFoundError,
    NotPermittedError,
    NotRunningError,
    ValidationFailedError,
    ValidationProblem,
)

if TYPE_CHECKING:
    from ceres.__internal__.app.shared import Actor
    from ceres.address import Address
    from ceres.engine import Engine
    from ceres.exporter import ExportRunRecord


class ExportRunRequest(DataObject):
    """Body of a request to start an export run."""

    after: DateTime
    """Inclusive start of the range to export."""
    before: DateTime | None = None
    """Exclusive end of the range to export, now when omitted."""
    replace: bool = False
    """Whether to rewrite each period's file from the database alone."""

    @model_validator(mode="after")
    def _validate_range(self) -> Self:
        if self.before is not None and self.after >= self.before:
            raise ValueError("`after` must precede `before`")

        return self


class ExportRunStarted(DataObject):
    """Response to a started export run."""

    id: UUID
    """ID of the run, listed among the exporter's runs."""


async def get_component_exporters(
    engine: Engine,
    actor: Actor,
    address: Address,
) -> list[ExporterInfo]:
    """Return the exporters of the component at the given address.

    Available to anyone who can access the component at all.

    Raises:
        NotFoundError: If no component matches the given address.
        NotPermittedError: If the caller has no access to the component.
    """
    return _describe_exporters(await _resolve_component(engine, actor, address))


async def _resolve_exporter(
    engine: Engine,
    actor: Actor,
    address: Address,
    name: str,
    *,
    operate: bool,
) -> Component:
    component = await _resolve_component(engine, actor, address)
    if operate and not actor.unrestricted:
        # A run writes files, so starting one needs operate access.
        access = await get_component_access(engine, actor.user, component)
        if access is None or access < ComponentAccessLevel.OPERATE:
            raise NotPermittedError()
    if component.system.exporters.get(name) is None:
        raise NotFoundError()

    return component


async def get_exporter_runs(
    engine: Engine,
    actor: Actor,
    address: Address,
    name: str,
) -> list[ExportRunRecord]:
    """Return the named exporter's recent runs, newest first.

    Available to anyone who can access the component at all.

    Raises:
        NotFoundError: If no component or exporter matches.
        NotPermittedError: If the caller has no access to the component.
    """
    component = await _resolve_exporter(engine, actor, address, name, operate=False)
    return component.system.exporters.get_runs(name)


async def start_exporter_run(
    engine: Engine,
    actor: Actor,
    address: Address,
    name: str,
    request: ExportRunRequest,
) -> ExportRunStarted:
    """Start a run of the named exporter and return its ID without waiting for it.

    Raises:
        NotFoundError: If no component or exporter matches.
        NotPermittedError: If the caller lacks operate access to the component.
        NotRunningError: If the component is not running.
        ValidationFailedError: If the exporter's format cannot merge and `replace` is false.
        AlreadyExistsError: If one run of the exporter already waits for another.
    """
    component = await _resolve_exporter(engine, actor, address, name, operate=True)
    if not component.system.running:
        raise NotRunningError()

    try:
        run = component.system.exporters.start(
            name,
            request.after,
            request.before,
            replace=request.replace,
        )
    except ValueError as error:
        raise ValidationFailedError(
            problems=[
                ValidationProblem(type="value_error", location=["replace"], message=str(error))
            ]
        ) from error

    return ExportRunStarted(id=run.id)
