from typing import TYPE_CHECKING, Self
from uuid import UUID

from pydantic import model_validator

from ceres.__internal__.app.handlers.components import (
    ExporterInfo,
    _describe_exporters,
    _resolve_component,
)
from ceres.__internal__.app.shared import get_component_access
from ceres.__internal__.pending_exports import PendingExport
from ceres.component import Component, ComponentAccessLevel
from ceres.data import DataObject, DateTime
from ceres.error import (
    NotFoundError,
    NotPermittedError,
    NotRunningError,
    ValidationFailedError,
    ValidationProblem,
)
from ceres.exporter import ExportConflict, ExportConflictError, ExportPlan, ExportRangeMode

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
    on_conflict: ExportConflict = ExportConflict.OVERWRITE
    """What the run does with a file it would write that already exists."""
    range_mode: ExportRangeMode = ExportRangeMode.EXPAND
    """How the run aligns the range with the exporter's files."""
    dry_run: bool = False
    """Whether to answer what the run would do, file by file, instead of starting it."""

    @model_validator(mode="after")
    def _validate_range(self) -> Self:
        if self.before is not None and self.after >= self.before:
            raise ValueError("`after` must precede `before`")

        return self


class PendingExportsRequest(DataObject):
    """Body of a request to export records a load wrote."""

    entries: list[PendingExport]
    """Records the load wrote, one entry per kind and address."""


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
) -> ExportRunStarted | ExportPlan:
    """Start a run of the named exporter and return its ID without waiting for it.

    With `dry_run` it returns what the run would do instead, and starts nothing.

    Raises:
        NotFoundError: If no component or exporter matches.
        NotPermittedError: If the caller lacks operate access to the component.
        NotRunningError: If the component is not running.
        ValidationFailedError: If `on_conflict` is `error` and files the run would write
            already exist.
        AlreadyExistsError: If one run of the exporter already waits for another.
    """
    component = await _resolve_exporter(engine, actor, address, name, operate=True)
    if not component.system.running:
        raise NotRunningError()

    exporters = component.system.exporters
    try:
        if request.dry_run:
            return await exporters.plan(
                name,
                request.after,
                request.before,
                on_conflict=request.on_conflict,
                range_mode=request.range_mode,
            )

        run = exporters.start(
            name,
            request.after,
            request.before,
            on_conflict=request.on_conflict,
            range_mode=request.range_mode,
        )
    except ExportConflictError as error:
        raise _conflict(error, "on_conflict") from error

    return ExportRunStarted(id=run.id)


def _conflict(error: ExportConflictError, field: str) -> ValidationFailedError:
    return ValidationFailedError(
        problems=[ValidationProblem(type="value_error", location=[field], message=str(error))]
    )
