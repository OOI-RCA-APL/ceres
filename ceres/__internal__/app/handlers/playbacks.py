from typing import TYPE_CHECKING, Self
from uuid import UUID

from pydantic import model_validator

from ceres.__internal__.app.handlers.components import _resolve_component
from ceres.__internal__.app.shared import get_component_access
from ceres.__internal__.playback import PlaybackLevel
from ceres.component import ComponentAccessLevel
from ceres.data import DataObject, DateTime
from ceres.error import (
    NotPermittedError,
    NotRunningError,
    ValidationFailedError,
    ValidationProblem,
)

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
    export: bool = True
    """Whether to rewrite the files of the exporters whose particles the playback replaces."""

    @model_validator(mode="after")
    def _validate_range(self) -> Self:
        if self.before is not None and self.after >= self.before:
            raise ValueError("`after` must precede `before`")

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
) -> PlaybackStarted:
    """Start a playback of the component's stored messages and return its ID without waiting.

    Raises:
        NotFoundError: If no component matches the given address.
        NotPermittedError: If the caller lacks manage access to the component.
        NotRunningError: If the component is not running.
        ValidationFailedError: If the component cannot replay the range.
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

    try:
        run = await component.system.playbacks.start(
            request.after,
            request.before,
            level=request.level,
            export=request.export,
        )
    except ValueError as error:
        raise ValidationFailedError(
            problems=[ValidationProblem(type="value_error", location=["after"], message=str(error))]
        ) from error

    return PlaybackStarted(id=run.id)
