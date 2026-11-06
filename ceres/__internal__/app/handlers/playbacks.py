from typing import TYPE_CHECKING, Self
from uuid import UUID

from pydantic import model_validator

from ceres.__internal__.app.handlers.components import _resolve_component
from ceres.__internal__.app.shared import get_component_access
from ceres.__internal__.playback import PlaybackLevel, PlaybackPlan, PlaybackRangeError
from ceres.component import ComponentAccessLevel
from ceres.data import DataObject, DateTime
from ceres.error import (
    NotPermittedError,
    NotRunningError,
    ValidationFailedError,
    ValidationProblem,
)
from ceres.exporter import ExportConflict, ExportConflictError, ExportRangeMode

if TYPE_CHECKING:
    from ceres.__internal__.app.shared import Actor
    from ceres.__internal__.playback import PlaybackRecord
    from ceres.address import Address
    from ceres.engine import Engine


class PlaybackRequest(DataObject):
    """Body of a request to start a playback."""

    after: DateTime
    """Inclusive start of the range to replay."""
    before: DateTime | None = None
    """Exclusive end of the range to replay, now when omitted."""
    level: PlaybackLevel = PlaybackLevel.PARTICLES
    """What to do with each particle parsed."""
    export: bool = False
    """Whether to write the files of the exporters whose particles the playback replaces."""
    on_export_conflict: ExportConflict | None = None
    """What the export runs do with a file that already exists, `overwrite` when omitted."""
    export_range_mode: ExportRangeMode | None = None
    """How to align the range with the exporters' files, `expand` when omitted."""
    dry_run: bool = False
    """Whether to answer what the playback would do, from a dry run that writes nothing."""

    @model_validator(mode="after")
    def _validate_range(self) -> Self:
        if self.before is not None and self.after >= self.before:
            raise ValueError("`after` must precede `before`")

        if not self.export:
            for field in ("on_export_conflict", "export_range_mode"):
                if getattr(self, field) is not None:
                    raise ValueError(f"`{field}` needs `export`")

        return self


class PlaybackStarted(DataObject):
    """Response to a started playback."""

    id: UUID
    """ID of the playback, listed among the component's playbacks."""


async def get_component_playbacks(
    engine: Engine,
    actor: Actor,
    address: Address,
) -> list[PlaybackRecord]:
    """Return the recent playbacks of the component at the given address, newest first.

    Available to anyone who can access the component at all.

    Raises:
        NotFoundError: If no component matches the given address.
        NotPermittedError: If the caller has no access to the component.
    """
    component = await _resolve_component(engine, actor, address)
    return component.system.playbacks.get_runs()


async def start_playback(
    engine: Engine,
    actor: Actor,
    address: Address,
    request: PlaybackRequest,
) -> PlaybackStarted | PlaybackPlan:
    """Start a playback of the component's stored messages and return its ID without waiting.

    With `dry_run` it returns what the playback would do instead, and changes nothing.

    Raises:
        NotFoundError: If no component matches the given address.
        NotPermittedError: If the caller lacks manage access to the component.
        NotRunningError: If the component is not running.
        ValidationFailedError: If the component cannot replay the range, or export files the
            playback would write already exist and `on_export_conflict` is `error`.
        AlreadyExistsError: If a playback of the component already runs.
    """
    component = await _resolve_component(engine, actor, address)
    if not actor.unrestricted:
        # A playback deletes and rewrites stored particles, so it needs manage access.
        access = await get_component_access(engine, actor.user, component)
        if access is None or access < ComponentAccessLevel.MANAGE:
            raise NotPermittedError()

    if not component.system.running:
        raise NotRunningError()

    playbacks = component.system.playbacks
    on_conflict = request.on_export_conflict or ExportConflict.OVERWRITE
    range_mode = request.export_range_mode or ExportRangeMode.EXPAND
    try:
        if request.dry_run:
            return await playbacks.plan(
                request.after,
                request.before,
                export=request.export,
                on_export_conflict=on_conflict,
                export_range_mode=range_mode,
            )

        run = await playbacks.start(
            request.after,
            request.before,
            level=request.level,
            export=request.export,
            on_export_conflict=on_conflict,
            export_range_mode=range_mode,
        )
    except ValueError as error:
        location: list[str | int] = []
        if isinstance(error, PlaybackRangeError):
            location = ["after"]
        elif isinstance(error, ExportConflictError):
            location = ["on_export_conflict"]

        raise ValidationFailedError(
            problems=[ValidationProblem(type="value_error", location=location, message=str(error))]
        ) from error

    return PlaybackStarted(id=run.id)
